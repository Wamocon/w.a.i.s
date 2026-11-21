// Komponententest der Einstellungsseite in Gruppen (components/einstellungen/Einstellungen.tsx, lib/einstellungenAbschnitte.ts):
// die Gliederung zeigt nur die Gruppen (je Rolle sechs oder fünf), eine Gruppe zeigt ihre Abschnitte untereinander, die Überschriften
// laufen sauber von Stufe 2 (Seite) über 3 (Gruppe) und 4 (Abschnitt) zu 5 (Block), die alten Adressen der Abschnitte öffnen die Gruppe
// und setzen den Fokus auf die Überschrift des Abschnitts, die Sprungleiste gibt es erst ab drei Abschnitten, am Handy führt eine Liste
// in die Gruppe. Die schweren Abschnitte (Netz, Geräte, Verwaltung) sind durch Platzhalter ersetzt, ihre eigenen Tests laufen anderswo.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({ getSupabase: () => null, accessToken: async () => null }));
vi.mock("./ErsteSchritte", () => ({ ErsteSchritteAbschnitt: () => <p>Platzhalter Erste Schritte</p> }));
vi.mock("./Updates", () => ({ UpdatesAbschnitt: () => <p>Platzhalter Updates</p> }));
vi.mock("./Geraete", () => ({ GeraeteAbschnitt: () => <p>Platzhalter Geräte</p> }));
vi.mock("./Fernzugriff", () => ({ Fernzugriff: () => <p>Platzhalter Fernzugriff</p> }));
vi.mock("./Gedaechtnis", () => ({ GedaechtnisAbschnitt: () => <p>Platzhalter Gedächtnis</p> }));
vi.mock("./NeueMitglieder", () => ({ NeueMitglieder: () => <p>Platzhalter Mitglieder</p> }));
vi.mock("./GithubRechte", () => ({ GithubRechte: () => <p>Platzhalter GitHub-Rechte</p> }));
vi.mock("./Aenderungen", () => ({ AenderungenAbschnitt: () => <p>Platzhalter Änderungen</p> }));
vi.mock("@/components/Geteilt", () => ({ GeteiltBereich: () => <p>Platzhalter Teilen</p> }));
vi.mock("@/components/GithubZugang", () => ({ GithubZugang: () => <p>Platzhalter GitHub-Zugang</p> }));

import { Einstellungen } from "@/components/einstellungen/Einstellungen";
import { einstellungenOeffnen, einstellungenSchliessen, zurListe } from "@/lib/einstellungenHash";
import type { WamoAktionen } from "@/lib/useWamo";
import { resetWamo, wamo } from "@/lib/wamo";

// Breite: zweispaltig oder Handy, je Test umschaltbar (lib/einstellungenHash.ts liest die Breite über matchMedia und merkt sich das Objekt)
let breit = true;
beforeAll(() => {
  // jsdom kennt Element.scrollTo und window.scrollTo nicht, die Seite ruft sie beim Öffnen und Wechseln der Gruppe
  if (typeof Element.prototype.scrollTo !== "function") Element.prototype.scrollTo = () => undefined;
  window.scrollTo = () => undefined;
  window.matchMedia = ((query: string) => ({
    get matches() {
      return breit;
    },
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});

const AKTIONEN = {
  mikrofone: async () => [],
  mikrofonWaehlen: () => true,
  toggleMic: () => undefined,
  ausgabeAnhalten: () => undefined,
  modellzugang: () => false,
  stimmabdruck: undefined,
  pcSteuerung: () => true,
} as unknown as WamoAktionen;

function zeige(hash: string, o: { admin?: boolean; token?: boolean } = {}) {
  window.history.replaceState(null, "", `/${hash}`);
  wamo.set((s) => ({
    ...s,
    profil: o.admin ? { name: "Admin", rolle: "admin" } : { name: "Mitglied", rolle: "mitglied" },
    modellzugang: o.token
      ? { aktion: "status", art: "claude", hinterlegt: false, festgelegt: false, codeHinterlegt: true }
      : null,
  }));
  return render(<Einstellungen aktionen={AKTIONEN} email="person@wamocon.com" onAbmelden={() => undefined} meldungen={null} />);
}

const nav = () => screen.getByRole("navigation", { name: "Gruppen der Einstellungen" });
const gruppenLinks = () => within(nav()).getAllByRole("link");
const ueberschrift = (level: number, name: string | RegExp) => screen.getByRole("heading", { level, name });
const geladen = () => act(async () => undefined);

beforeEach(() => {
  breit = true;
  resetWamo();
  localStorage.clear();
});
afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("Gliederung: nur die Gruppen", () => {
  it("Admin sieht sechs Gruppen mit Titel und Kurzzeile", async () => {
    zeige("#einstellungen", { admin: true });
    await geladen();
    expect(gruppenLinks().map((l) => l.querySelector(".ez-nav-titel")?.textContent)).toEqual([
      "Konto und Allgemeines",
      "Sprache und Stimme",
      "Modelle und Zugänge",
      "Geräte und PC",
      "Gedächtnis und Teilen",
      "Verwaltung",
    ]);
    const kurz = (name: string) => gruppenLinks().find((l) => l.textContent?.startsWith(name))?.querySelector(".ez-nav-kurz")?.textContent;
    expect(kurz("Konto und Allgemeines")).toBe("Konto, erste Schritte, Darstellung, Updates, Version und Hinweise");
    expect(kurz("Sprache und Stimme")).toBe("Mikrofon, Hören und Sprechen, eigene Stimme");
    expect(kurz("Modelle und Zugänge")).toBe("Schlüssel und Modelle, GitHub-Zugang, Verbrauch");
    expect(kurz("Verwaltung")).toBe("Neue Mitglieder und GitHub-Rechte, Änderungen an W.A.I.S., Werkstatt");
  });

  it("Mitglied sieht fünf Gruppen ohne Verwaltung, mit nur den offenen Abschnitten in den Kurzzeilen", async () => {
    zeige("#einstellungen");
    await geladen();
    const titel = gruppenLinks().map((l) => l.querySelector(".ez-nav-titel")?.textContent);
    expect(titel).toEqual(["Konto und Allgemeines", "Sprache und Stimme", "Modelle und Zugänge", "Geräte und PC", "Gedächtnis und Teilen"]);
    expect(gruppenLinks()[0].querySelector(".ez-nav-kurz")?.textContent).toBe("Konto, erste Schritte, Darstellung, Updates, Version und Hinweise");
    expect(gruppenLinks()[2].querySelector(".ez-nav-kurz")?.textContent).toBe("Schlüssel und Modelle, GitHub-Zugang");
    expect(gruppenLinks()[4].querySelector(".ez-nav-kurz")?.textContent).toBe("Geteilte Dokumente");
  });

  it("die Gliederung ist eine nav mit Beschriftung, die Links sind echte Links mit Adresse, nur die aktive Gruppe trägt aria-current", async () => {
    zeige("#einstellungen/zugaenge");
    await geladen();
    expect(gruppenLinks().map((l) => l.getAttribute("href"))).toEqual([
      "#einstellungen/allgemein",
      "#einstellungen/sprache-stimme",
      "#einstellungen/zugaenge",
      "#einstellungen/geraete-pc",
      "#einstellungen/inhalte",
    ]);
    expect(gruppenLinks().map((l) => l.getAttribute("aria-current"))).toEqual([null, null, "page", null, null]);
  });

  it("zweispaltig ohne Ziel in der Adresse gilt die erste Gruppe", async () => {
    zeige("#einstellungen");
    await geladen();
    expect(gruppenLinks()[0].getAttribute("aria-current")).toBe("page");
    expect(ueberschrift(3, "Konto und Allgemeines")).toBeTruthy();
    expect(document.querySelector(".ez")?.getAttribute("data-ansicht")).toBe("gruppe");
  });

  it("am Handy zeigt #einstellungen nur die Liste der Gruppen, der Fokus liegt auf Einstellungen", async () => {
    breit = false;
    zeige("#einstellungen");
    await geladen();
    expect(document.querySelector(".ez")?.getAttribute("data-ansicht")).toBe("liste");
    expect(screen.queryByRole("heading", { level: 3 })).toBeNull();
    expect(document.activeElement).toBe(ueberschrift(2, "Einstellungen"));
    expect(gruppenLinks().every((l) => l.getAttribute("aria-current") === null)).toBe(true);
  });

  it("ein Klick auf eine Gruppe öffnet sie ohne Neuladen und setzt den Fokus auf ihre Überschrift", async () => {
    zeige("#einstellungen");
    await geladen();
    await userEvent.click(within(nav()).getByRole("link", { name: /Modelle und Zugänge/ }));
    expect(window.location.hash).toBe("#einstellungen/zugaenge");
    await geladen();
    expect(document.activeElement).toBe(ueberschrift(3, "Modelle und Zugänge"));
    expect(gruppenLinks()[2].getAttribute("aria-current")).toBe("page");
  });

  it("ist mit der Tastatur zu bedienen: Fokus auf den Link, Enter wählt die Gruppe", async () => {
    zeige("#einstellungen");
    await geladen();
    const link = within(nav()).getByRole("link", { name: /Sprache und Stimme/ });
    link.focus();
    await userEvent.keyboard("{Enter}");
    await geladen();
    expect(window.location.hash).toBe("#einstellungen/sprache-stimme");
    expect(document.activeElement).toBe(ueberschrift(3, "Sprache und Stimme"));
  });

  it("der Dokumenttitel nennt die Gruppe", async () => {
    zeige("#einstellungen/geraete-pc");
    await geladen();
    expect(document.title).toBe("Geräte und PC, Einstellungen | W.A.I.S.");
  });
});

describe("Eine Gruppe: Überschriften und Bereiche", () => {
  it("Seite Stufe 2, Gruppe Stufe 3, Abschnitte Stufe 4, Blöcke Stufe 5", async () => {
    zeige("#einstellungen/allgemein");
    await geladen();
    expect(ueberschrift(2, "Einstellungen")).toBeTruthy();
    expect(ueberschrift(3, "Konto und Allgemeines")).toBeTruthy();
    for (const abschnitt of ["Konto", "Erste Schritte", "Darstellung", "Updates", "Info"]) expect(ueberschrift(4, abschnitt)).toBeTruthy();
    // Blöcke der Abschnitte tragen eine Stufe mehr als der Abschnitt
    for (const block of ["Angemeldet", "Helligkeit", "Ansicht", "Untertitel", "Diese Version", "Kern"]) expect(ueberschrift(5, block)).toBeTruthy();
    // genau eine Überschrift der Stufe 3 in der Gruppe, nie eine übersprungene Stufe
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(1);
    expect(screen.queryAllByRole("heading", { level: 6 })).toHaveLength(0);
  });

  it("jeder Abschnitt ist ein eigener Bereich, benannt nach seiner Überschrift", async () => {
    zeige("#einstellungen/allgemein");
    await geladen();
    for (const abschnitt of ["Konto", "Erste Schritte", "Darstellung", "Updates", "Info"]) {
      expect(screen.getByRole("region", { name: abschnitt })).toBeTruthy();
    }
    expect(screen.getByRole("region", { name: "Konto und Allgemeines" })).toBeTruthy();
  });

  it("die Abschnitte stehen in der Reihenfolge der Gruppe untereinander, jeder mit seiner Kurzzeile", async () => {
    zeige("#einstellungen/zugaenge", { token: true });
    await geladen();
    const titel = Array.from(document.querySelectorAll(".ez-abschnitt-titel")).map((h) => h.textContent);
    expect(titel).toEqual(["Modellzugang", "GitHub-Zugang", "Verbrauch"]);
    expect(Array.from(document.querySelectorAll(".ez-abschnitt-kurz")).map((p) => p.textContent)).toEqual([
      "Schlüssel, Token, Modus und Modelle",
      "Eigenes Token für Entwicklungsaufträge",
      "Kontingent deines Claude-Abos",
    ]);
  });

  it.each([
    ["Mitglied", false],
    ["Admin", true],
  ])("%s: der Abschnitt Updates steht zwischen Darstellung und Info, mit seiner Kurzzeile", async (_rolle, admin) => {
    zeige("#einstellungen/allgemein", { admin });
    await geladen();
    expect(Array.from(document.querySelectorAll(".ez-abschnitt-titel")).map((h) => h.textContent)).toEqual([
      "Konto",
      "Erste Schritte",
      "Darstellung",
      "Updates",
      "Info",
    ]);
    expect(within(screen.getByRole("region", { name: "Updates" })).getByText("Platzhalter Updates")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Updates" }).querySelector(".ez-abschnitt-kurz")?.textContent).toBe(
      "Neue Version der Desktop-App suchen und installieren",
    );
  });

  it("Info nennt die Version der Oberfläche, die installierte App steht nur bei den Updates", async () => {
    zeige("#einstellungen/allgemein");
    await geladen();
    const info = within(screen.getByRole("region", { name: "Info" }));
    expect(info.getByText("Version der Oberfläche", { selector: "dt" })).toBeTruthy();
    expect(info.queryByText("Installiert")).toBeNull();
  });

  it("zeigt nur die Abschnitte, die diese Rolle sieht: kein Verbrauch ohne Admin und ohne Token", async () => {
    zeige("#einstellungen/zugaenge");
    await geladen();
    expect(Array.from(document.querySelectorAll(".ez-abschnitt-titel")).map((h) => h.textContent)).toEqual(["Modellzugang", "GitHub-Zugang"]);
  });

  it("Admin: die Gruppe Geräte und PC hat den Fernzugriff einmal, als eigenen Abschnitt", async () => {
    zeige("#einstellungen/geraete-pc", { admin: true });
    await geladen();
    expect(screen.getAllByText("Platzhalter Fernzugriff")).toHaveLength(1);
    expect(ueberschrift(4, "Fernzugriff")).toBeTruthy();
    expect(ueberschrift(4, "Geräte und PC-Steuerung")).toBeTruthy();
  });

  it("die Hören-und-Sprechen-Wahl steht in der Gruppe Sprache und Stimme, der Modellzugang hat sie nicht mehr", async () => {
    zeige("#einstellungen/sprache-stimme");
    await geladen();
    expect(ueberschrift(5, "Hören und Sprechen")).toBeTruthy();
    expect(screen.getByRole("radiogroup", { name: "Spracherkennung" })).toBeTruthy();
    expect(ueberschrift(4, "Eigene Stimme")).toBeTruthy();
    window.history.replaceState(null, "", "/#einstellungen/zugaenge");
    act(() => window.dispatchEvent(new HashChangeEvent("hashchange")));
    await geladen();
    expect(screen.queryByRole("radiogroup", { name: "Spracherkennung" })).toBeNull();
    expect(screen.getAllByText(/Modus/).length).toBeGreaterThan(0);
  });

  it("eine Gruppe mit nur einem Abschnitt wiederholt dessen Kurzzeile nicht", async () => {
    zeige("#einstellungen/geraete-pc");
    await geladen();
    expect(document.querySelectorAll(".ez-abschnitt")).toHaveLength(1);
    expect(document.querySelector(".ez-abschnitt-kurz")).toBeNull();
    expect(document.querySelector(".ez-gruppe-kurz")?.textContent).toBe("Verbindungen und PC-Steuerung");
  });
});

describe("Alte Adressen der Abschnitte", () => {
  it.each([
    ["stimme", "sprache-stimme", "Sprache und Stimme", "Eigene Stimme"],
    ["modellzugang", "zugaenge", "Modelle und Zugänge", "Modellzugang"],
    ["github", "zugaenge", "Modelle und Zugänge", "GitHub-Zugang"],
    ["darstellung", "allgemein", "Konto und Allgemeines", "Darstellung"],
    ["info", "allgemein", "Konto und Allgemeines", "Info"],
    ["updates", "allgemein", "Konto und Allgemeines", "Updates"],
    ["teilen", "inhalte", "Gedächtnis und Teilen", "Teilen"],
  ])("#einstellungen/%s öffnet die Gruppe %s und setzt den Fokus auf die Überschrift des Abschnitts", async (abschnitt, gruppe, gruppenTitel, abschnittsTitel) => {
    zeige(`#einstellungen/${abschnitt}`);
    await geladen();
    expect(ueberschrift(3, gruppenTitel)).toBeTruthy();
    expect(gruppenLinks().find((l) => l.getAttribute("aria-current") === "page")?.getAttribute("href")).toBe(`#einstellungen/${gruppe}`);
    expect(document.activeElement).toBe(ueberschrift(4, abschnittsTitel));
  });

  it("ein Abschnitt nach dem ersten wird in Sicht gescrollt, der erste lässt den Kopf der Gruppe stehen", async () => {
    const spion = vi.spyOn(Element.prototype, "scrollIntoView");
    zeige("#einstellungen/github");
    await geladen();
    expect(spion).toHaveBeenCalledTimes(1);
    expect(spion.mock.contexts[0]).toBe(ueberschrift(4, "GitHub-Zugang"));
    spion.mockClear();
    window.history.replaceState(null, "", "/#einstellungen/modellzugang");
    act(() => window.dispatchEvent(new HashChangeEvent("hashchange")));
    await geladen();
    expect(spion).not.toHaveBeenCalled(); // erster Abschnitt: nach oben statt scrollIntoView
    expect(document.activeElement).toBe(ueberschrift(4, "Modellzugang"));
  });

  it("ein Abschnitt, den die Rolle nicht sieht, gilt wie keine Angabe: die erste Gruppe, nie die Gruppe des Abschnitts", async () => {
    zeige("#einstellungen/gedaechtnis");
    await geladen();
    expect(ueberschrift(3, "Konto und Allgemeines")).toBeTruthy();
    expect(screen.queryByText("Platzhalter Gedächtnis")).toBeNull();
  });

  it("Admin sieht denselben Abschnitt", async () => {
    zeige("#einstellungen/gedaechtnis", { admin: true });
    await geladen();
    expect(ueberschrift(3, "Gedächtnis und Teilen")).toBeTruthy();
    expect(screen.getByText("Platzhalter Gedächtnis")).toBeTruthy();
    expect(document.activeElement).toBe(ueberschrift(4, "Gedächtnis"));
  });

  it("eine unbekannte Kennung öffnet zweispaltig die erste Gruppe und am Handy die Liste", async () => {
    zeige("#einstellungen/gibtesnicht");
    await geladen();
    expect(ueberschrift(3, "Konto und Allgemeines")).toBeTruthy();
    cleanup();
    breit = false;
    zeige(`#einstellungen/${"a".repeat(80)}`);
    await geladen();
    expect(document.querySelector(".ez")?.getAttribute("data-ansicht")).toBe("liste");
  });
});

describe("Sprungleiste", () => {
  it("steht in einer Gruppe mit fünf Abschnitten, benannt nach der Gruppe, und führt zu jedem", async () => {
    zeige("#einstellungen/allgemein");
    await geladen();
    const leiste = screen.getByRole("navigation", { name: "Abschnitte in Konto und Allgemeines" });
    const links = within(leiste).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(["Konto", "Erste Schritte", "Darstellung", "Updates", "Info"]);
    expect(links.map((l) => l.getAttribute("href"))).toEqual([
      "#einstellungen/konto",
      "#einstellungen/start",
      "#einstellungen/darstellung",
      "#einstellungen/updates",
      "#einstellungen/info",
    ]);
  });

  it("ein Klick bleibt in der Gruppe, springt zum Abschnitt und setzt den Fokus auf dessen Überschrift", async () => {
    const spion = vi.spyOn(Element.prototype, "scrollIntoView");
    zeige("#einstellungen/allgemein");
    await geladen();
    spion.mockClear();
    await userEvent.click(within(screen.getByRole("navigation", { name: /^Abschnitte in / })).getByRole("link", { name: "Darstellung" }));
    await geladen();
    expect(window.location.hash).toBe("#einstellungen/darstellung");
    expect(ueberschrift(3, "Konto und Allgemeines")).toBeTruthy();
    expect(document.activeElement).toBe(ueberschrift(4, "Darstellung"));
    expect(spion).toHaveBeenCalled();
  });

  it("steht bei drei Abschnitten für Mitglieder mit Token, bei zwei Abschnitten gibt es keine", async () => {
    zeige("#einstellungen/zugaenge", { token: true });
    await geladen();
    expect(within(screen.getByRole("navigation", { name: /^Abschnitte in / })).getAllByRole("link")).toHaveLength(3);
  });

  it("fehlt in Gruppen mit höchstens zwei Abschnitten", async () => {
    zeige("#einstellungen/sprache-stimme");
    await geladen();
    expect(screen.queryByRole("navigation", { name: /^Abschnitte in / })).toBeNull();
  });

  it("derselbe Link noch einmal (etwa nach Scrollen von Hand) scrollt und fokussiert erneut", async () => {
    const spion = vi.spyOn(Element.prototype, "scrollIntoView");
    zeige("#einstellungen/allgemein");
    await geladen();
    const link = () => within(screen.getByRole("navigation", { name: "Abschnitte in Konto und Allgemeines" })).getByRole("link", { name: "Info" });
    await userEvent.click(link());
    await geladen();
    const erste = spion.mock.calls.length;
    expect(erste).toBeGreaterThan(0);
    (document.activeElement as HTMLElement).blur();
    await userEvent.click(link());
    await geladen();
    expect(spion.mock.calls.length).toBeGreaterThan(erste);
    expect(document.activeElement).toBe(ueberschrift(4, "Info"));
  });

  it("der Klick der Gliederung auf die Gruppe, in der man schon ist, führt an ihren Anfang", async () => {
    zeige("#einstellungen/info");
    await geladen();
    expect(document.activeElement).toBe(ueberschrift(4, "Info"));
    await userEvent.click(within(nav()).getByRole("link", { name: /Konto und Allgemeines/ }));
    await geladen();
    expect(window.location.hash).toBe("#einstellungen/allgemein");
    expect(document.activeElement).toBe(ueberschrift(3, "Konto und Allgemeines"));
  });
});

describe("Am Handy: Liste, dann Gruppe", () => {
  beforeEach(() => {
    breit = false;
  });

  it("die Gruppe zeigt Alle Einstellungen und Zum Gespräch, die Liste ist verborgen", async () => {
    zeige("#einstellungen/stimme");
    await geladen();
    expect(document.querySelector(".ez")?.getAttribute("data-ansicht")).toBe("gruppe");
    expect(screen.getByRole("button", { name: "Alle Einstellungen" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Zum Gespräch" }).length).toBeGreaterThan(0);
    expect(ueberschrift(3, "Sprache und Stimme")).toBeTruthy();
    expect(document.activeElement).toBe(ueberschrift(4, "Eigene Stimme"));
  });

  it("die Gruppenadresse setzt den Fokus auf die Überschrift der Gruppe", async () => {
    zeige("#einstellungen/zugaenge");
    await geladen();
    expect(document.activeElement).toBe(ueberschrift(3, "Modelle und Zugänge"));
  });

  it("zweispaltig gibt es die Wege Alle Einstellungen nicht", async () => {
    breit = true;
    zeige("#einstellungen/stimme");
    await geladen();
    expect(screen.queryByRole("button", { name: "Alle Einstellungen" })).toBeNull();
  });

  it("öffnen mit Ziel aus dem Gespräch legt am Handy Liste und Gruppe an: Alle Einstellungen führt zur Liste, Zum Gespräch zurück", async () => {
    window.history.replaceState(null, "", "/");
    const push = vi.spyOn(window.history, "pushState");
    einstellungenOeffnen("stimme");
    expect(push.mock.calls.map((c) => c[2])).toEqual(["/#einstellungen", "/#einstellungen/stimme"]);
    expect(window.location.hash).toBe("#einstellungen/stimme");
    zurListe();
    await waitFor(() => expect(window.location.hash).toBe("#einstellungen"));
    einstellungenSchliessen();
    await waitFor(() => expect(window.location.hash).toBe(""));
  });

  it("zweispaltig legt das Öffnen mit Ziel nur einen Eintrag an", async () => {
    breit = true;
    window.history.replaceState(null, "", "/");
    const push = vi.spyOn(window.history, "pushState");
    einstellungenOeffnen("stimme");
    expect(push.mock.calls.map((c) => c[2])).toEqual(["/#einstellungen/stimme"]);
    einstellungenSchliessen();
    await waitFor(() => expect(window.location.hash).toBe(""));
  });

  it("Escape schließt die Seite (zweispaltig)", async () => {
    breit = true;
    zeige("#einstellungen/zugaenge");
    await geladen();
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => expect(window.location.hash).toBe(""));
  });

  it("Escape lässt eine Eingabe mit Inhalt in Ruhe", async () => {
    zeige("#einstellungen/zugaenge");
    await geladen();
    const feld = document.createElement("input");
    feld.type = "text";
    feld.value = "geheim";
    document.body.append(feld);
    feld.focus();
    fireEvent.keyDown(feld, { key: "Escape" });
    await geladen();
    expect(window.location.hash).toBe("#einstellungen/zugaenge");
    feld.remove();
  });
});
