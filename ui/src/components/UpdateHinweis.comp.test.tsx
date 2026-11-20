// Komponententest des Pop-ups "Update verfügbar" (components/UpdateHinweis.tsx): nur in der Desktop-App und nur für angemeldete Profile, nie
// im Browser (Aufruf kommt gar nicht erst), Angebot nur nach Bestätigung der App, "Jetzt aktualisieren" startet dieselbe Installation wie der
// Abschnitt Updates (derselbe Speicher), Fortschritt und Fehler mit "Erneut versuchen", "Später" je Version und Profil mit Speicher und
// ohne, wieder nach 24 Stunden oder einer neueren Version, regelmäßige Prüfung, Fokus bleibt unberührt, Escape schließt wie "Später".
// Kern (lib/kernApi.ts) und Anmeldung (lib/supabase.ts) sind Attrappen, die Desktop-Brücke ist ein falsches window.wamoDesktop.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { kernJson } from "@/lib/kernApi";
import { nutzerSetzen } from "@/lib/nutzer";
import { accessToken } from "@/lib/supabase";
import { FENSTER_ALTER_MS, PRUEFABSTAND_MS, SPAETER_FRIST_MS, spaeterLesen, spaeterRueckfallLeeren, spaeterSchluessel, startId } from "@/lib/updateHinweis";
import { updates, updatesInstallieren, updatesLaden, updatesZuruecksetzen } from "@/lib/updatesStore";
import { resetWamo, wamo } from "@/lib/wamo";
import { UpdateHinweis } from "./UpdateHinweis";

vi.mock("@/lib/kernApi", () => ({ kernJson: vi.fn() }));
vi.mock("@/lib/supabase", () => ({ getSupabase: () => null, accessToken: vi.fn() }));

const ID = "0b7f3c1e-2d4a-4c55-9a10-1a2b3c4d5e6f";
const ANDERE_ID = "9a8b7c6d-1111-4222-8333-444455556666";
const SIGNATUR = `${"B".repeat(86)}==`;
const MANIFEST = { manifest: '{"version":"0.8.0"}', signatur: SIGNATUR, version: "0.8.0" };
const TOKEN = "token-nur-fuer-die-app";

const nichtGefunden = () => Object.assign(new Error("Fehler 404"), { status: 404 });

function kernAntwortet(antworten: Record<string, unknown>) {
  vi.mocked(kernJson).mockImplementation(async (pfad: string) => {
    if (pfad in antworten) return antworten[pfad];
    throw nichtGefunden();
  });
}

type Update = { pruefen: ReturnType<typeof vi.fn>; installieren: ReturnType<typeof vi.fn> };

/** Desktop-App 0.7.0, die ein Update auf 0.8.0 bestätigt (wenn nichts anderes gesagt wird). */
function appSetzen(teil: Record<string, unknown> = {}): Update {
  const update: Update = {
    pruefen: vi.fn().mockResolvedValue({ ok: true, version: "0.8.0", neuer: true }),
    installieren: vi.fn().mockResolvedValue({ ok: true }),
  };
  window.wamoDesktop = { isDesktop: true, levels: () => undefined, version: "0.7.0", update, ...teil } as unknown as Window["wamoDesktop"];
  return update;
}

function spaeter<T>() {
  let erfuellen: (v: T) => void = () => undefined;
  const versprechen = new Promise<T>((r) => {
    erfuellen = r;
  });
  return { versprechen, erfuellen };
}

const karte = () => screen.queryByRole("region", { name: "Update verfügbar" });
const jetztKnopf = () => screen.getByRole("button", { name: "Jetzt aktualisieren" });
const spaeterKnopf = () => screen.getByRole("button", { name: "Später" });

/** Rendern und die erste Prüfung (setTimeout 0) abwarten. */
async function zeige(angemeldet = true) {
  nutzerSetzen({ id: angemeldet ? ID : null, email: angemeldet ? "person@wamocon.com" : null });
  const ergebnis = render(<UpdateHinweis />);
  await act(async () => {
    await new Promise((r) => setTimeout(r, 5));
  });
  return { ...ergebnis, user: userEvent.setup() };
}

function speicherEintrag(userId: string, eintrag: Record<string, unknown>) {
  localStorage.setItem(spaeterSchluessel(userId), JSON.stringify(eintrag));
}

beforeEach(() => {
  updatesZuruecksetzen();
  spaeterRueckfallLeeren();
  resetWamo();
  localStorage.clear();
  vi.mocked(kernJson).mockReset();
  vi.mocked(accessToken).mockReset().mockResolvedValue(TOKEN);
});
afterEach(() => {
  delete window.wamoDesktop;
  nutzerSetzen({ id: null, email: null });
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("wann das Pop-up erscheint", () => {
  it("bei einem von der App bestätigten neueren Update: Titel, Satz und beide Knöpfe, dazu der Link zu den Updates", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    await zeige();
    expect(update.pruefen).toHaveBeenCalledWith({ manifest: MANIFEST.manifest, signatur: SIGNATUR });
    expect(karte()).toBeTruthy();
    expect(screen.getByText("Update verfügbar", { selector: "p" })).toBeTruthy();
    expect(screen.getByText("Version 0.8.0 ist bereit. Die App startet nach der Installation neu.")).toBeTruthy();
    expect(jetztKnopf()).toBeTruthy();
    expect(spaeterKnopf()).toBeTruthy();
    expect(screen.getByRole("link", { name: "Zu den Updates" }).getAttribute("href")).toBe("#einstellungen/updates");
  });

  it("kein Angebot (404, App aktuell, App lehnt ab, Server nicht lesbar): kein Pop-up", async () => {
    for (const fall of ["404", "aktuell", "abgelehnt", "unlesbar"]) {
      updatesZuruecksetzen();
      vi.mocked(kernJson).mockReset();
      kernAntwortet(fall === "404" ? {} : fall === "unlesbar" ? { "/installer": { manifest: 1 } } : { "/installer": MANIFEST });
      const update = appSetzen();
      if (fall === "aktuell") update.pruefen.mockResolvedValue({ ok: true, version: "0.7.0", neuer: false });
      if (fall === "abgelehnt") update.pruefen.mockResolvedValue({ ok: false, text: "Update vom Server nicht bestätigt." });
      const { unmount, container } = await zeige();
      expect(karte(), fall).toBeNull();
      expect(container.textContent, fall).not.toContain("Jetzt aktualisieren");
      unmount();
    }
  });

  it("im Browser (keine Brücke) nichts: kein Abruf, kein Token, kein Rahmen", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const { container } = await zeige();
    expect(container.innerHTML).toBe("");
    expect(kernJson).not.toHaveBeenCalled();
    expect(accessToken).not.toHaveBeenCalled();
  });

  it("ohne angemeldetes Profil nichts, auch nicht in der App", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    const { container } = await zeige(false);
    expect(container.innerHTML).toBe("");
    expect(kernJson).not.toHaveBeenCalled();
  });

  it("eine ältere App ohne Update-Teil: kein Pop-up und keine Anfrage an den Server", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen({ version: undefined, update: undefined });
    await zeige();
    expect(karte()).toBeNull();
    expect(kernJson).not.toHaveBeenCalled();
  });

  it("solange der Abschnitt Updates offen ist, bleibt das Pop-up weg (dort steht dasselbe)", async () => {
    window.history.replaceState(null, "", "/#einstellungen/updates");
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    await zeige();
    expect(karte()).toBeNull();
    window.history.replaceState(null, "", "/");
  });
});

describe("Gespräch und Bedienung", () => {
  it("ohne Gespräch kein Zusatz, mit laufendem Gespräch steht dabei, dass es beendet wird", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    await zeige();
    expect(screen.queryByText(/Das laufende Gespräch wird beendet/)).toBeNull();
    act(() => wamo.set((s) => ({ ...s, presence: "listening" })));
    expect(screen.getByText(/Das laufende Gespräch wird beendet\./)).toBeTruthy();
    act(() => wamo.set((s) => ({ ...s, presence: "offline" })));
    expect(screen.queryByText(/Das laufende Gespräch wird beendet/)).toBeNull();
  });

  it("das Pop-up nimmt keinen Fokus: weder beim Erscheinen noch beim Satzwechsel, es ist weder Dialog noch modal", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    nutzerSetzen({ id: ID, email: "person@wamocon.com" });
    const eingabe = document.createElement("input");
    document.body.append(eingabe);
    eingabe.focus();
    render(<UpdateHinweis />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 5));
    });
    expect(karte()).toBeTruthy();
    expect(document.activeElement).toBe(eingabe);
    act(() => wamo.set((s) => ({ ...s, presence: "listening" })));
    expect(document.activeElement).toBe(eingabe);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(karte()?.closest("[aria-modal]")).toBeNull();
    eingabe.remove();
  });

  it("Region mit Beschriftung in einer höflichen Live-Region, mit der Tastatur erreichbar", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    const { container, user } = await zeige();
    expect(container.querySelector("[aria-live='polite']")?.contains(karte())).toBe(true);
    await user.tab();
    expect(document.activeElement).toBe(jetztKnopf());
    await user.tab();
    expect(document.activeElement).toBe(spaeterKnopf());
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("link", { name: "Zu den Updates" }));
  });

  it("Escape in der Karte schließt wie Später", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    const { user } = await zeige();
    await user.tab();
    await user.keyboard("{Escape}");
    expect(karte()).toBeNull();
    expect(spaeterLesen(ID)?.version).toBe("0.8.0");
  });

  it("die Zeichen sind versteckt, der Zustand steht als Text da", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    await zeige();
    expect(karte()?.querySelector("[aria-hidden='true'] svg")).toBeTruthy();
  });
});

describe("Jetzt aktualisieren", () => {
  it("startet dieselbe Installation: Manifest, Signatur und Token gehen nur an die App, nie ins DOM", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    const antwort = spaeter<unknown>();
    update.installieren.mockReturnValue(antwort.versprechen);
    const { user } = await zeige();
    expect(accessToken).not.toHaveBeenCalled(); // das Token holt erst der Klick
    await user.click(jetztKnopf());
    await waitFor(() => expect(update.installieren).toHaveBeenCalledWith({ manifest: MANIFEST.manifest, signatur: SIGNATUR, token: TOKEN }));
    // Fortschritt: Wird installiert, Knöpfe gesperrt, ein unbestimmter Balken
    expect(screen.getByText(/Wird installiert/)).toBeTruthy();
    expect(jetztKnopf().getAttribute("aria-disabled")).toBe("true");
    expect(jetztKnopf().getAttribute("aria-busy")).toBe("true");
    expect(spaeterKnopf().getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByRole("progressbar", { name: /installiert/i })).toBeTruthy();
    expect(document.body.innerHTML).not.toContain(TOKEN);
    expect(JSON.stringify(updates.get())).not.toContain(TOKEN);
    // nach dem erfolgreichen Start blendet sich das Pop-up aus
    await act(async () => antwort.erfuellen({ ok: true }));
    expect(karte()).toBeNull();
  });

  it("Doppelklick ruft die App nur einmal; Später ruht während der Installation", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    update.installieren.mockReturnValue(spaeter<unknown>().versprechen);
    const { user } = await zeige();
    await user.dblClick(jetztKnopf());
    await waitFor(() => expect(update.installieren).toHaveBeenCalledTimes(1));
    await user.click(jetztKnopf());
    await user.click(spaeterKnopf());
    expect(update.installieren).toHaveBeenCalledTimes(1);
    expect(karte()).toBeTruthy();
    expect(spaeterLesen(ID)).toBeNull();
  });

  it("zusammen mit dem Abschnitt Updates höchstens eine Installation: läuft eine, ruft ein zweiter Aufruf die App nicht noch einmal", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    update.installieren.mockReturnValue(spaeter<unknown>().versprechen);
    const { user } = await zeige();
    await user.click(jetztKnopf());
    await waitFor(() => expect(update.installieren).toHaveBeenCalledTimes(1));
    await act(async () => updatesInstallieren({ version: "0.8.0", manifest: MANIFEST.manifest, signatur: SIGNATUR }));
    expect(update.installieren).toHaveBeenCalledTimes(1);
  });

  it("abgebrochen: still zurück zum Angebot, kein Fehlertext", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen().installieren.mockResolvedValue({ ok: false, text: "Abgebrochen.", abgebrochen: true });
    const { user } = await zeige();
    await user.click(jetztKnopf());
    await waitFor(() => expect(updates.get().phase.art).toBe("ruhe"));
    expect(jetztKnopf().getAttribute("aria-disabled")).toBeNull();
    expect(screen.queryByText("Abgebrochen.")).toBeNull();
  });

  it("Fehler: der Grund der App und Erneut versuchen, das mit demselben Angebot noch einmal startet", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    update.installieren.mockResolvedValueOnce({ ok: false, text: "Signatur passt nicht." }).mockResolvedValueOnce({ ok: true });
    const { user } = await zeige();
    await user.click(jetztKnopf());
    expect(await screen.findByText("Signatur passt nicht.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Jetzt aktualisieren" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Erneut versuchen" }));
    await waitFor(() => expect(update.installieren).toHaveBeenCalledTimes(2));
    expect(update.installieren).toHaveBeenLastCalledWith({ manifest: MANIFEST.manifest, signatur: SIGNATUR, token: TOKEN });
    await waitFor(() => expect(karte()).toBeNull());
  });

  it("ohne Anmeldung kein Aufruf der App: Fehler mit dem Satz zur Anmeldung", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    vi.mocked(accessToken).mockResolvedValue(null);
    const { user } = await zeige();
    await user.click(jetztKnopf());
    expect(await screen.findByText("Die Anmeldung ist abgelaufen. Bitte neu anmelden.")).toBeTruthy();
    expect(update.installieren).not.toHaveBeenCalled();
  });

  it("Später bei einem Fehler blendet das Pop-up ebenfalls aus", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen().installieren.mockResolvedValue({ ok: false, text: "Signatur passt nicht." });
    const { user } = await zeige();
    await user.click(jetztKnopf());
    await screen.findByText("Signatur passt nicht.");
    await user.click(spaeterKnopf());
    expect(karte()).toBeNull();
  });

  it("Aushängen während der Installation: die späte Antwort meldet keinen Fehler und setzt keinen Zustand einer Komponente", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    const antwort = spaeter<unknown>();
    update.installieren.mockReturnValue(antwort.versprechen);
    const fehler = vi.spyOn(console, "error");
    const { unmount, container, user } = await zeige();
    await user.click(jetztKnopf());
    await waitFor(() => expect(update.installieren).toHaveBeenCalledTimes(1));
    unmount();
    await act(async () => antwort.erfuellen({ ok: false, text: "Signatur passt nicht." }));
    expect(container.innerHTML).toBe("");
    expect(fehler).not.toHaveBeenCalled();
  });
});

describe("Später", () => {
  it("blendet das Pop-up aus und merkt es je Version und Profil im Speicher", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    vi.spyOn(Date, "now").mockReturnValue(1_800_000_000_000);
    const { user } = await zeige();
    await user.click(spaeterKnopf());
    expect(karte()).toBeNull();
    expect(spaeterLesen(ID)).toEqual({ version: "0.8.0", zeit: 1_800_000_000_000, start: startId() });
    expect(spaeterLesen(ANDERE_ID)).toBeNull();
    expect(localStorage.getItem(spaeterSchluessel(ID))).toContain("0.8.0");
  });

  it("ein neues Rendern im selben Start (und eine erneute Prüfung) bringt dieselbe Version nicht zurück", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    const { user, unmount } = await zeige();
    await user.click(spaeterKnopf());
    unmount();
    await zeige();
    expect(karte()).toBeNull();
  });

  it("nach dem nächsten Start der App erscheint dieselbe Version wieder (anderer Start im Eintrag)", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    speicherEintrag(ID, { version: "0.8.0", zeit: Date.now(), start: "ein-anderer-start" });
    await zeige();
    expect(karte()).toBeTruthy();
  });

  it("im selben Start bleibt es 24 Stunden aus und kommt danach wieder (gefälschte Zeit)", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
    vi.setSystemTime(new Date("2026-12-01T08:00:00Z"));
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    nutzerSetzen({ id: ID, email: "person@wamocon.com" });
    render(<UpdateHinweis />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    fireClick(spaeterKnopf());
    expect(karte()).toBeNull();
    // 23 Stunden später (regelmäßige Prüfung alle 30 Minuten): immer noch aus
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SPAETER_FRIST_MS - 60 * 60 * 1000);
    });
    expect(karte()).toBeNull();
    // über 24 Stunden: die nächste Prüfung zeigt es wieder
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60 * 60 * 1000 + PRUEFABSTAND_MS);
    });
    expect(karte()).toBeTruthy();
  });

  it("eine neuere Version erscheint sofort, auch im selben Start", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    speicherEintrag(ID, { version: "0.8.0", zeit: Date.now(), start: startId() });
    update.pruefen.mockResolvedValue({ ok: true, version: "0.9.0", neuer: true });
    await zeige();
    expect(screen.getByText("Version 0.9.0 ist bereit. Die App startet nach der Installation neu.")).toBeTruthy();
  });

  it("der Eintrag eines anderen Profils gilt nicht", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    speicherEintrag(ANDERE_ID, { version: "0.8.0", zeit: Date.now(), start: startId() });
    await zeige();
    expect(karte()).toBeTruthy();
  });

  it("localStorage wirft: Später gilt trotzdem für diesen Start", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("gesperrt");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("voll");
    });
    const { user, unmount } = await zeige();
    expect(karte()).toBeTruthy();
    await user.click(spaeterKnopf());
    expect(karte()).toBeNull();
    unmount();
    await zeige();
    expect(karte()).toBeNull();
  });

  it("ein kaputter Eintrag im Speicher zählt nicht: das Pop-up erscheint", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    localStorage.setItem(spaeterSchluessel(ID), "{kaputt");
    await zeige();
    expect(karte()).toBeTruthy();
  });
});

describe("Prüfung beim Start, regelmäßig und beim Wiederöffnen", () => {
  it("prüft beim Start einmal und danach alle 30 Minuten, solange das Fenster offen ist", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    nutzerSetzen({ id: ID, email: "person@wamocon.com" });
    render(<UpdateHinweis />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(kernJson).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PRUEFABSTAND_MS - 100);
    });
    expect(kernJson).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(kernJson).toHaveBeenCalledTimes(2);
  });

  it("nach dem Aushängen läuft kein Zeitgeber mehr", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    nutzerSetzen({ id: ID, email: "person@wamocon.com" });
    const { unmount } = render(<UpdateHinweis />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PRUEFABSTAND_MS * 3);
    });
    expect(kernJson).toHaveBeenCalledTimes(1);
  });

  it("beim Wiederöffnen des Fensters nur, wenn die letzte Prüfung älter als 10 Minuten ist", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    nutzerSetzen({ id: ID, email: "person@wamocon.com" });
    render(<UpdateHinweis />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(kernJson).toHaveBeenCalledTimes(1);
    const sichtbar = () => act(async () => void document.dispatchEvent(new Event("visibilitychange")));
    await sichtbar(); // zu frisch
    expect(kernJson).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FENSTER_ALTER_MS + 1_000);
    });
    await sichtbar();
    expect(kernJson).toHaveBeenCalledTimes(2);
  });

  it("eine neue Version zwischen zwei Prüfungen erscheint beim nächsten Abruf", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    update.pruefen.mockResolvedValueOnce({ ok: true, version: "0.7.0", neuer: false });
    nutzerSetzen({ id: ID, email: "person@wamocon.com" });
    render(<UpdateHinweis />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(karte()).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PRUEFABSTAND_MS + 1_000);
    });
    expect(karte()).toBeTruthy();
  });
});

describe("Störungen und laufende Suche", () => {
  const FAKE: Parameters<typeof vi.useFakeTimers>[0] = { toFake: ["Date", "setTimeout", "clearTimeout", "setInterval", "clearInterval"] };

  it("eine Störung bei der Prüfung im Hintergrund lässt das bestätigte Angebot stehen, und die Zeit der Prüfung schreitet nicht fort", async () => {
    vi.useFakeTimers(FAKE);
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    nutzerSetzen({ id: ID, email: "person@wamocon.com" });
    render(<UpdateHinweis />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(karte()).toBeTruthy();
    const zeit = updates.get().zeit;
    vi.mocked(kernJson).mockRejectedValue(Object.assign(new Error("Fehler 503"), { status: 503 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PRUEFABSTAND_MS + 1_000);
    });
    expect(vi.mocked(kernJson).mock.calls.length).toBeGreaterThan(1);
    expect(karte()).toBeTruthy();
    expect(updates.get().zeit).toBe(zeit);
  });

  it("nimmt der Server das Update zurück (404), verschwindet die Karte bei der nächsten Prüfung", async () => {
    vi.useFakeTimers(FAKE);
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    nutzerSetzen({ id: ID, email: "person@wamocon.com" });
    render(<UpdateHinweis />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(karte()).toBeTruthy();
    vi.mocked(kernJson).mockRejectedValue(nichtGefunden());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PRUEFABSTAND_MS + 1_000);
    });
    expect(karte()).toBeNull();
  });

  it("während einer Suche sind die Knöpfe gesperrt und ein Klick tut nichts", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    const { user } = await zeige();
    const zweite = spaeter<unknown>();
    vi.mocked(kernJson).mockReturnValue(zweite.versprechen);
    let suche: Promise<void> = Promise.resolve();
    act(() => {
      suche = updatesLaden();
    });
    await waitFor(() => expect(jetztKnopf().getAttribute("aria-disabled")).toBe("true"));
    await user.click(jetztKnopf());
    expect(update.installieren).not.toHaveBeenCalled();
    await act(async () => {
      zweite.erfuellen(MANIFEST);
      await suche;
    });
    expect(jetztKnopf().getAttribute("aria-disabled")).toBeNull();
  });

  it("Erneut versuchen während einer Suche löscht den Fehler nicht und startet nichts", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    update.installieren.mockResolvedValue({ ok: false, text: "Signatur passt nicht." });
    const { user } = await zeige();
    await user.click(jetztKnopf());
    await screen.findByText("Signatur passt nicht.");
    const zweite = spaeter<unknown>();
    vi.mocked(kernJson).mockReturnValue(zweite.versprechen);
    let suche: Promise<void> = Promise.resolve();
    act(() => {
      suche = updatesLaden();
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Erneut versuchen" }).getAttribute("aria-disabled")).toBe("true"));
    await user.click(screen.getByRole("button", { name: "Erneut versuchen" }));
    expect(update.installieren).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Signatur passt nicht.")).toBeTruthy();
    await act(async () => {
      zweite.erfuellen(MANIFEST);
      await suche;
    });
  });
});

function fireClick(el: HTMLElement) {
  act(() => el.click());
}
