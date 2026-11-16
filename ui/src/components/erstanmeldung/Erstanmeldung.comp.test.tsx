// Komponententest des geführten Ablaufs der Erstanmeldung (components/erstanmeldung/Erstanmeldung.tsx, schritte.tsx, PasswortSchritt.tsx):
// Reihenfolge und Leiste der Schritte, Überspringen, Schritte ohne Bedarf, Merker des begonnenen Ablaufs, und der Passwortschritt
// (lokale Prüfung, Wechsel über die Route des Kerns, nie über updateUser, danach signOut für die anderen Sitzungen, Weiter erst bei
// erledigt, Fehlersätze nach den Codes des Kerns).
// Ausführen im Ordner ui/:  npm run test:komponenten
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SupabaseClient } from "@supabase/supabase-js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Erstanmeldung } from "@/components/erstanmeldung/Erstanmeldung";
import { ERSTANMELDUNG_SCHRITTE } from "@/components/erstanmeldung/schritte";
import type { ErstanmeldungKontext, ErstanmeldungSchritt, SchrittProps } from "@/components/erstanmeldung/typen";
import { ablaufMerkerGesetzt, ablaufMerkerSetzen, type ErstanmeldungStand, type PasswortErgebnis } from "@/lib/erstanmeldung";

const USER = "11111111-2222-3333-4444-555555555555";
const NEUES_PASSWORT = "Ein-neues-Passwort-2026";

type AuthAttrappe = {
  updateUser: ReturnType<typeof vi.fn>;
  signOut: ReturnType<typeof vi.fn>;
};

function kontextBauen(optionen: { standStart?: ErstanmeldungStand; staende?: ErstanmeldungStand[] } = {}): {
  kontext: ErstanmeldungKontext;
  auth: AuthAttrappe;
  stand: ReturnType<typeof vi.fn>;
  neuPruefen: ReturnType<typeof vi.fn>;
  passwortSetzen: ReturnType<typeof vi.fn>;
} {
  // updateUser bleibt als Spion da: Der Wechsel geht über die Route des Kerns, updateUser darf nie aufgerufen werden
  const auth: AuthAttrappe = {
    updateUser: vi.fn(async () => ({ data: { user: {} }, error: null })),
    signOut: vi.fn(async () => ({ error: null })),
  };
  const folge = [...(optionen.staende ?? ["erledigt"])];
  const stand = vi.fn(async () => (folge.length > 1 ? folge.shift()! : folge[0]));
  const neuPruefen = vi.fn();
  const passwortSetzen = vi.fn(async (): Promise<PasswortErgebnis> => ({ ok: true, stand: "erledigt" }));
  const kontext: ErstanmeldungKontext = {
    supabase: { auth } as unknown as SupabaseClient,
    zugriffstoken: async () => "tok",
    kernBasis: "https://kern.test",
    anzeigename: "W.A.I.S.",
    userId: USER,
    email: "person@wamocon.com",
    standStart: optionen.standStart ?? "offen",
    stand,
    passwortSetzen,
    neuPruefen,
    abmelden: vi.fn(),
  };
  return { kontext, auth, stand, neuPruefen, passwortSetzen };
}

/** Schritt mit einfacher Komponente: Text, "Weiter" und (wenn angeboten) "Überspringen". */
function schritt(id: string, zusatz: Partial<ErstanmeldungSchritt> = {}): ErstanmeldungSchritt {
  function Inhalt({ weiter, ueberspringen }: SchrittProps) {
    return (
      <div>
        <p>Inhalt {id}</p>
        <button onClick={weiter}>Weiter {id}</button>
        {ueberspringen && <button onClick={ueberspringen}>Überspringen {id}</button>}
      </div>
    );
  }
  return { id, titel: `Titel ${id}`, ueberspringbar: false, komponente: Inhalt, ...zusatz };
}

const punkte = () => within(screen.getByRole("list", { name: "Schritte der Erstanmeldung" })).getAllByRole("listitem");
const zustaende = () => punkte().map((p) => p.getAttribute("data-zustand"));

beforeEach(() => {
  sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Ablauf: Reihenfolge und Leiste", () => {
  it("führt der Reihe nach durch, zeigt oben erledigt, aktuell und folgt und ruft am Ende fertig auf", async () => {
    const { kontext } = kontextBauen();
    const fertig = vi.fn();
    const benutzer = userEvent.setup();
    render(<Erstanmeldung kontext={kontext} fertig={fertig} schritte={[schritt("eins"), schritt("zwei"), schritt("drei")]} />);

    expect(await screen.findByText("Inhalt eins")).toBeTruthy();
    expect(screen.queryByText("Inhalt zwei")).toBeNull();
    expect(zustaende()).toEqual(["aktuell", "folgt", "folgt"]);
    expect(punkte()[0].getAttribute("aria-current")).toBe("step");
    expect(punkte().map((p) => p.textContent)).toEqual([
      "1Titel eins (aktuell)",
      "2Titel zwei (folgt)",
      "3Titel drei (folgt)",
    ]);

    await benutzer.click(screen.getByRole("button", { name: "Weiter eins" }));
    expect(await screen.findByText("Inhalt zwei")).toBeTruthy();
    expect(zustaende()).toEqual(["erledigt", "aktuell", "folgt"]);
    expect(fertig).not.toHaveBeenCalled();

    await benutzer.click(screen.getByRole("button", { name: "Weiter zwei" }));
    await benutzer.click(await screen.findByRole("button", { name: "Weiter drei" }));
    await waitFor(() => expect(fertig).toHaveBeenCalledTimes(1));
  });

  it("überspringt Schritte, die nicht nötig sind (auch mit asynchroner Prüfung)", async () => {
    const { kontext } = kontextBauen();
    const fertig = vi.fn();
    const schritte = [
      schritt("eins", { noetig: () => false }),
      schritt("zwei", { noetig: async () => false }),
      schritt("drei", { noetig: async () => true }),
    ];
    render(<Erstanmeldung kontext={kontext} fertig={fertig} schritte={schritte} />);
    expect(await screen.findByText("Inhalt drei")).toBeTruthy();
    expect(screen.queryByText("Inhalt eins")).toBeNull();
    expect(screen.queryByText("Inhalt zwei")).toBeNull();
    expect(zustaende()).toEqual(["erledigt", "erledigt", "aktuell"]);
  });

  it("gibt den Kontext an noetig weiter und zeigt den Schritt, wenn die Prüfung scheitert", async () => {
    const { kontext } = kontextBauen();
    const noetig = vi.fn(async (k: ErstanmeldungKontext) => {
      if (k.userId !== USER) throw new Error("falscher Kontext");
      throw new Error("Prüfung kaputt");
    });
    render(<Erstanmeldung kontext={kontext} fertig={vi.fn()} schritte={[schritt("eins", { noetig })]} />);
    expect(await screen.findByText("Inhalt eins")).toBeTruthy();
    expect(noetig).toHaveBeenCalledWith(kontext);
  });

  it("ruft fertig sofort auf, wenn kein Schritt nötig ist", async () => {
    const { kontext } = kontextBauen();
    const fertig = vi.fn();
    render(<Erstanmeldung kontext={kontext} fertig={fertig} schritte={[schritt("eins", { noetig: () => false })]} />);
    await waitFor(() => expect(fertig).toHaveBeenCalledTimes(1));
  });

  it("bietet Überspringen nur bei überspringbaren Schritten an, und das Überspringen geht zum nächsten", async () => {
    const { kontext } = kontextBauen();
    const fertig = vi.fn();
    const benutzer = userEvent.setup();
    render(
      <Erstanmeldung
        kontext={kontext}
        fertig={fertig}
        schritte={[schritt("fest"), schritt("frei", { ueberspringbar: true })]}
      />,
    );
    expect(await screen.findByText("Inhalt fest")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Überspringen/ })).toBeNull();
    await benutzer.click(screen.getByRole("button", { name: "Weiter fest" }));
    await benutzer.click(await screen.findByRole("button", { name: "Überspringen frei" }));
    await waitFor(() => expect(fertig).toHaveBeenCalledTimes(1));
  });

  it("legt beim Start den Merker an und räumt ihn am Ende weg; ein Neuladen mitten im Ablauf behält ihn", async () => {
    const { kontext } = kontextBauen();
    const fertig = vi.fn();
    const benutzer = userEvent.setup();
    const { unmount } = render(<Erstanmeldung kontext={kontext} fertig={fertig} schritte={[schritt("eins"), schritt("zwei")]} />);
    await screen.findByText("Inhalt eins");
    expect(ablaufMerkerGesetzt(USER)).toBe(true);
    unmount(); // Neuladen: der Merker bleibt
    expect(ablaufMerkerGesetzt(USER)).toBe(true);

    render(<Erstanmeldung kontext={kontext} fertig={fertig} schritte={[schritt("eins", { noetig: () => false }), schritt("zwei")]} />);
    await benutzer.click(await screen.findByRole("button", { name: "Weiter zwei" }));
    await waitFor(() => expect(fertig).toHaveBeenCalledTimes(1));
    expect(ablaufMerkerGesetzt(USER)).toBe(false);
  });
});

describe("Gerüst für weitere Schritte", () => {
  it("die Liste der Schritte hat jetzt genau einen Eintrag: passwort, nicht überspringbar, mit Titel und Komponente", () => {
    expect(ERSTANMELDUNG_SCHRITTE.map((s) => s.id)).toEqual(["passwort"]);
    const passwort = ERSTANMELDUNG_SCHRITTE[0];
    expect(passwort.ueberspringbar).toBe(false);
    expect(passwort.titel).toBe("Passwort");
    expect(typeof passwort.komponente).toBe("function");
  });

  it("der Passwortschritt ist nur nötig, solange die Erstanmeldung offen ist (nach einem Neuladen mit erledigt nicht mehr)", async () => {
    const passwort = ERSTANMELDUNG_SCHRITTE[0];
    expect(await passwort.noetig?.(kontextBauen({ standStart: "offen" }).kontext)).toBe(true);
    expect(await passwort.noetig?.(kontextBauen({ standStart: "erledigt" }).kontext)).toBe(false);
  });

  it("nach einem Neuladen mit erledigtem Passwort übergeht der Ablauf den Passwortschritt und zeigt den nächsten (Strang 2 hängt sich so ein)", async () => {
    const { kontext } = kontextBauen({ standStart: "erledigt" });
    ablaufMerkerSetzen(USER);
    render(<Erstanmeldung kontext={kontext} fertig={vi.fn()} schritte={[...ERSTANMELDUNG_SCHRITTE, schritt("token")]} />);
    expect(await screen.findByText("Inhalt token")).toBeTruthy();
    expect(screen.queryByLabelText("Neues Passwort")).toBeNull();
    expect(zustaende()).toEqual(["erledigt", "aktuell"]);
  });
});

describe("Ablauf: Fokus, Überschrift und Zeitgrenze", () => {
  it("setzt den Fokus bei jedem Schrittwechsel auf die Überschrift des Schritts (tabIndex -1); eigene Überschrift vor dem Titel", async () => {
    const { kontext } = kontextBauen();
    const benutzer = userEvent.setup();
    render(
      <Erstanmeldung
        kontext={kontext}
        fertig={vi.fn()}
        schritte={[schritt("eins", { ueberschrift: "Erste Überschrift" }), schritt("zwei")]}
      />,
    );
    const erste = await screen.findByRole("heading", { name: "Erste Überschrift" });
    expect(erste.tagName).toBe("H2");
    expect(erste.getAttribute("tabindex")).toBe("-1");
    await waitFor(() => expect(document.activeElement).toBe(erste));
    expect(screen.getAllByRole("heading")).toHaveLength(1);
    await benutzer.click(screen.getByRole("button", { name: "Weiter eins" }));
    const zweite = await screen.findByRole("heading", { name: "Titel zwei" });
    await waitFor(() => expect(document.activeElement).toBe(zweite));
  });

  it("zeigt in der Leiste bei erledigten Schritten ein Häkchen statt der Ziffer (guter Kontrast)", async () => {
    const { kontext } = kontextBauen();
    const benutzer = userEvent.setup();
    render(<Erstanmeldung kontext={kontext} fertig={vi.fn()} schritte={[schritt("eins"), schritt("zwei")]} />);
    await benutzer.click(await screen.findByRole("button", { name: "Weiter eins" }));
    await screen.findByText("Inhalt zwei");
    expect(punkte().map((p) => p.textContent)).toEqual(["✓Titel eins (erledigt)", "2Titel zwei (aktuell)"]);
  });

  it("zeigt einen Schritt, dessen noetig() nicht antwortet, nach der Zeitgrenze statt ihn zu verschlucken", async () => {
    const { kontext } = kontextBauen();
    const haengt = vi.fn(() => new Promise<boolean>(() => undefined));
    render(
      <Erstanmeldung
        kontext={kontext}
        fertig={vi.fn()}
        schritte={[schritt("eins", { noetig: haengt }), schritt("zwei")]}
        noetigZeitMs={40}
      />,
    );
    expect(screen.getByText("Einen Moment …")).toBeTruthy();
    expect(await screen.findByText("Inhalt eins")).toBeTruthy();
    expect(haengt).toHaveBeenCalledTimes(1);
  });

  it("die Zeitgrenze gilt je Schritt: ein langsamer erster Schritt hält die Prüfung des zweiten nicht auf", async () => {
    const { kontext } = kontextBauen();
    render(
      <Erstanmeldung
        kontext={kontext}
        fertig={vi.fn()}
        schritte={[schritt("eins", { noetig: () => false }), schritt("zwei", { noetig: () => new Promise<boolean>(() => undefined) })]}
        noetigZeitMs={40}
      />,
    );
    expect(await screen.findByText("Inhalt zwei")).toBeTruthy();
  });
});

describe("Schritt Passwort", () => {
  async function oeffnen(optionen: Parameters<typeof kontextBauen>[0] = {}) {
    const bau = kontextBauen(optionen);
    const fertig = vi.fn();
    const benutzer = userEvent.setup();
    render(<Erstanmeldung kontext={bau.kontext} fertig={fertig} />);
    const neu = (await screen.findByLabelText("Neues Passwort")) as HTMLInputElement;
    const wieder = screen.getByLabelText("Neues Passwort wiederholen") as HTMLInputElement;
    const eingeben = async (a = NEUES_PASSWORT, b = a) => {
      await benutzer.type(neu, a);
      await benutzer.type(wieder, b);
    };
    const absenden = () => benutzer.click(screen.getByRole("button", { name: "Passwort ändern" }));
    return { ...bau, fertig, benutzer, neu, wieder, eingeben, absenden };
  }

  it("zeigt zwei Passwortfelder mit neuem Passwort als Autovervollständigung und den Hinweis auf 12 Zeichen", async () => {
    const { neu, wieder } = await oeffnen();
    for (const feld of [neu, wieder]) {
      expect(feld.type).toBe("password");
      expect(feld.getAttribute("autocomplete")).toBe("new-password");
      expect(feld.required).toBe(true);
    }
    expect(screen.getByText(/Mindestens 12 Zeichen/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Neues Passwort" })).toBeTruthy();
    expect(zustaende()).toEqual(["aktuell"]);
  });


  it("ändert über die Route des Kerns (nie über updateUser), beendet danach die anderen Sitzungen und geht bei erledigt weiter", async () => {
    const { auth, stand, passwortSetzen, fertig, eingeben, absenden } = await oeffnen();
    await eingeben();
    await absenden();
    await waitFor(() => expect(fertig).toHaveBeenCalledTimes(1));
    expect(passwortSetzen).toHaveBeenCalledTimes(1);
    expect(passwortSetzen).toHaveBeenCalledWith(NEUES_PASSWORT);
    expect(auth.updateUser).not.toHaveBeenCalled();
    expect(auth.signOut).toHaveBeenCalledTimes(1);
    expect(auth.signOut).toHaveBeenCalledWith({ scope: "others" });
    // die Antwort des Kerns sagt erledigt: kein zweiter Abruf des Stands nötig
    expect(stand).not.toHaveBeenCalled();
    // Reihenfolge: erst ändern, dann die anderen Sitzungen beenden
    const [p] = passwortSetzen.mock.invocationCallOrder;
    const [s] = auth.signOut.mock.invocationCallOrder;
    expect(p).toBeLessThan(s);
  });

  it("geht nicht weiter, solange der Kern nicht erledigt meldet, und lässt erneut prüfen (ohne das Passwort noch einmal zu senden)", async () => {
    const { auth, stand, passwortSetzen, fertig, eingeben, absenden, benutzer } = await oeffnen({
      staende: ["offen", "offen", "erledigt"],
    });
    passwortSetzen.mockResolvedValue({ ok: true, stand: "keine" }); // 200 ohne bestätigten Stand: wie bisher erneut prüfen
    await eingeben();
    await absenden();
    expect(await screen.findByText(/noch nicht bestätigt/)).toBeTruthy();
    expect(screen.getByText(/noch nicht bestätigt/).textContent).toContain("W.A.I.S.");
    expect(stand).toHaveBeenCalledTimes(1);
    expect(fertig).not.toHaveBeenCalled();
    // die Passwortfelder sind weg: ein zweites Absenden desselben Passworts (same_password) ist nicht möglich
    expect(screen.queryByLabelText("Neues Passwort")).toBeNull();
    await benutzer.click(screen.getByRole("button", { name: "Erneut prüfen" }));
    await waitFor(() => expect(stand).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "Erneut prüfen" }).getAttribute("aria-disabled")).toBeNull());
    expect(fertig).not.toHaveBeenCalled();
    await benutzer.click(screen.getByRole("button", { name: "Erneut prüfen" }));
    await waitFor(() => expect(fertig).toHaveBeenCalledTimes(1));
    expect(passwortSetzen).toHaveBeenCalledTimes(1);
    expect(auth.updateUser).not.toHaveBeenCalled();
  });

  it("zeigt einen Fehler beim Beenden der anderen Sitzungen an, blockiert aber nicht", async () => {
    const { auth, fertig, eingeben, absenden, benutzer } = await oeffnen();
    auth.signOut.mockResolvedValue({ error: { message: "Server weg", status: 500 } });
    await eingeben();
    await absenden();
    expect(await screen.findByText(/Andere angemeldete Geräte konnten nicht abgemeldet werden/)).toBeTruthy();
    expect(fertig).not.toHaveBeenCalled(); // die Meldung bleibt sichtbar, bis die Person auf Weiter klickt
    await benutzer.click(screen.getByRole("button", { name: "Weiter" }));
    await waitFor(() => expect(fertig).toHaveBeenCalledTimes(1));
  });

  it("behandelt auch einen geworfenen Fehler beim Beenden der anderen Sitzungen als Hinweis", async () => {
    const { auth, fertig, eingeben, absenden, benutzer } = await oeffnen();
    auth.signOut.mockRejectedValue(new Error("Netz weg"));
    await eingeben();
    await absenden();
    expect(await screen.findByText(/Andere angemeldete Geräte konnten nicht abgemeldet werden/)).toBeTruthy();
    await benutzer.click(screen.getByRole("button", { name: "Weiter" }));
    await waitFor(() => expect(fertig).toHaveBeenCalledTimes(1));
  });

  it("prüft lokal: zu kurz, ungleich, zu lang; dann wird nichts gesendet", async () => {
    const { auth, passwortSetzen, eingeben, absenden, neu, wieder, benutzer } = await oeffnen();
    await eingeben("kurz");
    await absenden();
    expect((await screen.findByRole("alert")).textContent).toBe("Das neue Passwort braucht mindestens 12 Zeichen.");
    await benutzer.clear(neu);
    await benutzer.clear(wieder);
    await eingeben("zwölf-zeichen-lang", "zwölf-zeichen-anders");
    await absenden();
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Die beiden Passwörter sind nicht gleich."));
    await benutzer.clear(neu);
    await benutzer.clear(wieder);
    await eingeben("a".repeat(73));
    await absenden();
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/zu lang/));
    expect(passwortSetzen).not.toHaveBeenCalled();
    expect(auth.updateUser).not.toHaveBeenCalled();
    expect(auth.signOut).not.toHaveBeenCalled();
  });

  /** Ein Fehler des Kerns: Satz sichtbar, nichts weiter (kein signOut, kein weiter), die Eingabe bleibt zum Korrigieren. */
  const FEHLER: [string, number, string, RegExp | string][] = [
    ["same_password", 422, "same_password", "Das neue Passwort muss sich vom Startpasswort unterscheiden."],
    ["weak_password", 422, "weak_password", /zu schwach/],
    ["passwort_ungueltig", 400, "passwort_ungueltig", /nicht zulässig.*12 Zeichen.*72 Bytes/],
    ["zu_oft", 429, "zu_oft", "Zu viele Versuche, bitte in zehn Minuten noch einmal."],
    ["anmeldedienst", 502, "anmeldedienst", "Der Anmeldedienst ist gerade nicht erreichbar."],
    ["reauthentication_needed", 401, "reauthentication_needed", "Bitte melde dich neu an, dann klappt der Wechsel."],
    ["sitzung_ungueltig", 401, "sitzung_ungueltig", "Bitte melde dich neu an, dann klappt der Wechsel."],
    ["503 ohne Code", 503, "", "Das Passwort konnte nicht geändert werden. Bitte versuche es noch einmal."],
  ];
  it.each(FEHLER)("zeigt bei %s den Satz zum Fehler des Kerns und bleibt im Formular", async (_name, status, code, erwartet) => {
    const { auth, passwortSetzen, neuPruefen, fertig, eingeben, absenden, neu } = await oeffnen();
    passwortSetzen.mockResolvedValue({ ok: false, status, code: code || null });
    await eingeben();
    await absenden();
    const meldung = (await screen.findByRole("alert")).textContent ?? "";
    if (typeof erwartet === "string") expect(meldung).toBe(erwartet);
    else expect(meldung).toMatch(erwartet);
    expect(fertig).not.toHaveBeenCalled();
    expect(neuPruefen).not.toHaveBeenCalled();
    expect(auth.signOut).not.toHaveBeenCalled();
    expect(auth.updateUser).not.toHaveBeenCalled();
    expect(neu.value).toBe(NEUES_PASSWORT); // zum Korrigieren
  });

  it("zeigt bei Netzfehler (Status 0) den Satz zum Anmeldeserver und bei einem geworfenen Fehler den allgemeinen Satz", async () => {
    const { passwortSetzen, fertig, eingeben, absenden } = await oeffnen();
    passwortSetzen.mockResolvedValueOnce({ ok: false, status: 0, code: null });
    await eingeben();
    await absenden();
    expect((await screen.findByRole("alert")).textContent).toMatch(/Anmeldeserver nicht erreichbar/);
    passwortSetzen.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await absenden();
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe("Das Passwort konnte nicht geändert werden. Bitte versuche es noch einmal."),
    );
    expect(fertig).not.toHaveBeenCalled();
  });

  it("führt bei insufficient_aal zurück zur Code-Abfrage (neuPruefen des Tors, mit Hinweis)", async () => {
    const { auth, passwortSetzen, neuPruefen, fertig, eingeben, absenden } = await oeffnen();
    passwortSetzen.mockResolvedValue({ ok: false, status: 401, code: "insufficient_aal" });
    await eingeben();
    await absenden();
    await waitFor(() => expect(neuPruefen).toHaveBeenCalledTimes(1));
    expect(neuPruefen).toHaveBeenCalledWith({ code: true, hinweis: expect.stringMatching(/frischen Code/) });
    expect(fertig).not.toHaveBeenCalled();
    expect(auth.signOut).not.toHaveBeenCalled();
  });

  it("zeigt bei abgelaufenem Startpasswort den Satz und lässt das Tor neu prüfen", async () => {
    const { passwortSetzen, neuPruefen, fertig, eingeben, absenden } = await oeffnen();
    passwortSetzen.mockResolvedValue({ ok: false, status: 403, code: "startpasswort_abgelaufen" });
    await eingeben();
    await absenden();
    expect((await screen.findByRole("alert")).textContent).toBe("Dein Startpasswort ist abgelaufen. Bitte melde dich bei Niko.");
    await waitFor(() => expect(neuPruefen).toHaveBeenCalledTimes(1));
    expect(neuPruefen).toHaveBeenCalledWith();
    expect(fertig).not.toHaveBeenCalled();
  });

  it("lässt das Tor neu prüfen, wenn kein Wechsel nötig ist (kein_wechsel_noetig)", async () => {
    const { passwortSetzen, neuPruefen, fertig, eingeben, absenden } = await oeffnen();
    passwortSetzen.mockResolvedValue({ ok: false, status: 409, code: "kein_wechsel_noetig" });
    await eingeben();
    await absenden();
    expect((await screen.findByRole("alert")).textContent).toMatch(/nicht nötig/);
    await waitFor(() => expect(neuPruefen).toHaveBeenCalledTimes(1));
    expect(fertig).not.toHaveBeenCalled();
  });

  it("prüft das Tor neu, wenn die Frist während des Wechsels abgelaufen ist (Stand abgelaufen)", async () => {
    const { passwortSetzen, neuPruefen, fertig, eingeben, absenden } = await oeffnen({ staende: ["abgelaufen"] });
    passwortSetzen.mockResolvedValue({ ok: true, stand: "keine" });
    await eingeben();
    await absenden();
    await waitFor(() => expect(neuPruefen).toHaveBeenCalledTimes(1));
    expect(fertig).not.toHaveBeenCalled();
  });

  it("hat genau eine Überschrift (die des Ablaufs), mit dem Fokus darauf, und keine doppelte im Schritt", async () => {
    await oeffnen();
    const ueberschriften = screen.getAllByRole("heading");
    expect(ueberschriften).toHaveLength(1);
    expect(ueberschriften[0].textContent).toBe("Neues Passwort");
    await waitFor(() => expect(document.activeElement).toBe(ueberschriften[0]));
  });

  it("verbindet das Feld mit dem Hinweis zur Mindestlänge (aria-describedby) und markiert bei einem Fehler beide Felder als ungültig", async () => {
    const { neu, wieder, eingeben, absenden } = await oeffnen();
    for (const feld of [neu, wieder]) {
      const ids = (feld.getAttribute("aria-describedby") ?? "").split(" ");
      expect(ids.map((id) => document.getElementById(id)?.textContent).join(" ")).toMatch(/Mindestens 12 Zeichen/);
      expect(feld.getAttribute("aria-invalid")).toBeNull();
    }
    await eingeben("kurz");
    await absenden();
    const meldung = await screen.findByRole("alert");
    for (const feld of [neu, wieder]) {
      expect(feld.getAttribute("aria-invalid")).toBe("true");
      expect((feld.getAttribute("aria-describedby") ?? "").split(" ")).toContain(meldung.id);
    }
    expect(meldung.id).not.toBe("");
  });

  it("hat ein verstecktes Feld autocomplete=username mit der E-Mail, damit Passwortmanager das neue Passwort richtig ablegen", async () => {
    await oeffnen();
    const benutzername = document.querySelector('input[autocomplete="username"]') as HTMLInputElement;
    expect(benutzername).not.toBeNull();
    expect(benutzername.value).toBe("person@wamocon.com");
    expect(benutzername.readOnly).toBe(true);
    expect(benutzername.getAttribute("tabindex")).toBe("-1");
    expect(benutzername.getAttribute("aria-hidden")).toBe("true");
  });

  it("hat eine Live-Region (status, polite), die von Anfang an da ist und die Statussätze trägt", async () => {
    const { passwortSetzen, auth, eingeben, absenden } = await oeffnen();
    const region = screen.getByRole("status");
    expect(region.getAttribute("aria-live")).toBe("polite");
    expect(region.textContent).toBe("");
    passwortSetzen.mockResolvedValue({ ok: true, stand: "keine" });
    auth.signOut.mockResolvedValue({ error: { message: "x", status: 500 } });
    await eingeben();
    await absenden();
    await screen.findByText(/Dein Passwort ist geändert/);
    expect(screen.getByRole("status")).toBe(region); // dasselbe Element, nicht neu eingehängt
    expect(region.textContent).toMatch(/Dein Passwort ist geändert/);
    expect(region.textContent).toMatch(/Andere angemeldete Geräte/);
  });

  it("sperrt den Knopf während der Anfrage mit aria-disabled (nicht disabled) und sendet nie doppelt", async () => {
    const { passwortSetzen, eingeben, absenden, benutzer } = await oeffnen();
    let fertigMelden: (e: PasswortErgebnis) => void = () => undefined;
    passwortSetzen.mockImplementation(() => new Promise<PasswortErgebnis>((ok) => (fertigMelden = ok)));
    await eingeben();
    await absenden();
    const knopf = await screen.findByRole("button", { name: "Ändere …" });
    expect(knopf.getAttribute("aria-disabled")).toBe("true");
    expect((knopf as HTMLButtonElement).disabled).toBe(false);
    await benutzer.click(knopf);
    expect(passwortSetzen).toHaveBeenCalledTimes(1);
    fertigMelden({ ok: false, status: 429, code: "zu_oft" });
    expect((await screen.findByRole("alert")).textContent).toMatch(/Zu viele Versuche/);
    expect(screen.getByRole("button", { name: "Passwort ändern" }).getAttribute("aria-disabled")).toBeNull();
  });

  it("liest die Passwörter erst beim Absenden aus dem Formular und setzt es nach dem Erfolg zurück (form.reset)", async () => {
    const zuruecksetzen = vi.spyOn(HTMLFormElement.prototype, "reset");
    const { passwortSetzen, neu, wieder, eingeben, absenden } = await oeffnen();
    expect(neu.getAttribute("value")).toBeNull(); // keine Vorbelegung aus dem Zustand von React
    await eingeben();
    expect(neu.value).toBe(NEUES_PASSWORT);
    expect(wieder.value).toBe(NEUES_PASSWORT);
    expect(zuruecksetzen).not.toHaveBeenCalled();
    await absenden();
    await waitFor(() => expect(zuruecksetzen).toHaveBeenCalledTimes(1));
    expect(passwortSetzen).toHaveBeenCalledWith(NEUES_PASSWORT);
  });

  it("setzt bei einem Fehler nicht zurück: die Eingabe bleibt zum Korrigieren", async () => {
    const zuruecksetzen = vi.spyOn(HTMLFormElement.prototype, "reset");
    const { passwortSetzen, neu, eingeben, absenden } = await oeffnen();
    passwortSetzen.mockResolvedValue({ ok: false, status: 422, code: "same_password" });
    await eingeben();
    await absenden();
    await screen.findByRole("alert");
    expect(zuruecksetzen).not.toHaveBeenCalled();
    expect(neu.value).toBe(NEUES_PASSWORT);
  });

  it("setzt den Fokus nach dem Wechsel auf den Knopf, der als Nächstes dran ist (der Absendeknopf ist weg)", async () => {
    const { passwortSetzen, eingeben, absenden } = await oeffnen({ staende: ["offen", "offen"] });
    passwortSetzen.mockResolvedValue({ ok: true, stand: "keine" });
    await eingeben();
    await absenden();
    const knopf = await screen.findByRole("button", { name: "Erneut prüfen" });
    await waitFor(() => expect(document.activeElement).toBe(knopf));
  });

  it("schreibt das Passwort nirgends hin: nicht ins Log, nicht in den Speicher, nicht in die Seite nach dem Wechsel", async () => {
    const spione = (["log", "info", "warn", "error", "debug"] as const).map((n) => vi.spyOn(console, n).mockImplementation(() => undefined));
    const { auth, passwortSetzen, eingeben, absenden } = await oeffnen({ staende: ["offen"] }); // nicht bestätigt: der Ablauf bleibt stehen
    passwortSetzen.mockResolvedValue({ ok: true, stand: "keine" });
    auth.signOut.mockResolvedValue({ error: { message: `mit ${NEUES_PASSWORT}`, status: 500 } });
    await eingeben();
    await absenden();
    expect(await screen.findByText(/Dein Passwort ist geändert/)).toBeTruthy();
    for (const spion of spione) {
      for (const aufruf of spion.mock.calls) expect(JSON.stringify(aufruf)).not.toContain(NEUES_PASSWORT);
    }
    const speicher = [localStorage, sessionStorage].flatMap((s) => Object.keys(s).map((k) => `${k}=${s.getItem(k)}`));
    expect(speicher.join("\n")).not.toContain(NEUES_PASSWORT);
    expect(document.body.innerHTML).not.toContain(NEUES_PASSWORT);
    expect(screen.queryByLabelText("Neues Passwort")).toBeNull(); // Felder nach dem Erfolg weg
  });
});
