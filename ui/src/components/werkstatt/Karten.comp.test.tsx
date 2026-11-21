// Komponententest des Bereichs Karten und Use Cases: Editor von null, Prüfung, Katalog, Zuordnung und der Vierschritt zum
// Veröffentlichen. Der Dienst (lib/werkstattApi.ts) und der zweite Faktor (lib/geraeteVerwaltungApi.ts) sind durch Attrappen ersetzt.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { codeBestaetigen } from "@/lib/geraeteVerwaltungApi";
import {
  WerkstattFehler,
  freigabeAusfuehren,
  freigabeKarteAnlegen,
  karteAendern,
  karteAnlegen,
  karteLoeschen,
  kartenLaden,
  kartenPruefen,
  plaetzeLaden,
  termineLaden,
  versionenLaden,
  zuordnungLaden,
  zuordnungSpeichern,
} from "@/lib/werkstattApi";
import { fehlerBild } from "@/lib/werkstattFehler";
import type { Karte } from "@/lib/werkstattTypen";
import { Karten } from "./Karten";

vi.mock("@/lib/geraeteVerwaltungApi", () => ({ codeBestaetigen: vi.fn() }));
vi.mock("@/lib/werkstattApi", async (original) => {
  const echt = await original<typeof import("@/lib/werkstattApi")>();
  return {
    ...echt,
    kartenLaden: vi.fn(),
    versionenLaden: vi.fn(),
    termineLaden: vi.fn(),
    karteAnlegen: vi.fn(),
    karteAendern: vi.fn(),
    karteLoeschen: vi.fn(),
    plaetzeLaden: vi.fn(),
    zuordnungLaden: vi.fn(),
    zuordnungSpeichern: vi.fn(),
    kartenPruefen: vi.fn(),
    freigabeKarteAnlegen: vi.fn(),
    freigabeAusfuehren: vi.fn(),
  };
});

function karte(id: string, teil: Partial<Karte> = {}): Karte {
  return {
    id, gruppe: `Gruppe ${id.charAt(0)}`, titel: `Titel ${id}`, aufgabe: "Aufgabe", erwartung: "Erwartung", fehler: null, lernziel: null,
    wissen: "keine", wissenstext: null, werkzeuge: [], dauerMin: 3, stand: "veroeffentlicht", ...teil,
  };
}
const GRUPPEN = { A: "Gruppe A", B: "Gruppe B", K: "Gruppe K" };
const TERMIN = { id: "t1", tag: "2099-12-05", beginn: null, ende: null, einwilligungVersion: 1, status: "entwurf" as const, aufbewahrungBis: "2099-12-18" };
const noop = () => undefined;

beforeEach(() => {
  vi.mocked(kartenLaden).mockResolvedValue({ karten: [karte("A1"), karte("A2", { stand: "entwurf" })], version: 4, gruppen: GRUPPEN });
  vi.mocked(versionenLaden).mockResolvedValue([]);
  vi.mocked(termineLaden).mockResolvedValue([TERMIN]);
  vi.mocked(plaetzeLaden).mockResolvedValue([
    { platz: 1, zweck: "besucher", kennung: "labor-01", gast: "Gast 1" },
    { platz: 2, zweck: "besucher", kennung: "labor-02", gast: null },
    { platz: 15, zweck: "abnahme", kennung: "labor-15", gast: null },
  ]);
  vi.mocked(zuordnungLaden).mockResolvedValue({ 1: ["A1"] });
  vi.mocked(karteAnlegen).mockResolvedValue({ karte: null });
  vi.mocked(karteAendern).mockResolvedValue({ karte: null });
  vi.mocked(karteLoeschen).mockResolvedValue(true);
  vi.mocked(zuordnungSpeichern).mockResolvedValue(true);
});
afterEach(() => vi.useRealTimers());

describe("Katalog und Editor", () => {
  it("zeigt die Version und den Katalog mit Stand als Wort; Löschen nur bei Entwürfen", async () => {
    render(<Karten onFaktor={noop} />);
    expect(await screen.findByText("Katalog Version 4")).toBeTruthy();
    expect(screen.getByText("2 von 2 Karten")).toBeTruthy();
    const tabelle = screen.getByRole("table", { name: "Karten des Katalogs" });
    expect(within(tabelle).getByText("Entwurf")).toBeTruthy();
    expect(within(tabelle).getByText("veröffentlicht")).toBeTruthy();
    expect(screen.getByRole("button", { name: "A2 löschen" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "A1 löschen" })).toBeNull();
  });

  it("von null: die Gruppe kommt aus der festen Liste, Pflichtfelder werden geprüft, dann als Entwurf gespeichert", async () => {
    const user = userEvent.setup();
    vi.mocked(kartenLaden).mockResolvedValue({ karten: [], version: null, gruppen: GRUPPEN });
    render(<Karten onFaktor={noop} />);
    expect(await screen.findByText("Noch keine veröffentlichte Version")).toBeTruthy();
    expect(screen.getByText(/Der Katalog ist noch leer/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Neuen Use Case aufbauen" }));
    expect(screen.getByRole("heading", { name: "Neuen Use Case aufbauen", level: 2 })).toBeTruthy();
    expect(screen.getByLabelText("Gruppe")).toHaveProperty("value", "");
    // es gibt keine Möglichkeit, eine eigene Gruppe anzulegen: der Dienst kennt nur seine feste Liste
    expect(screen.queryByRole("option", { name: /Neue Gruppe/ })).toBeNull();
    expect(within(screen.getByLabelText("Gruppe")).getAllByRole("option").map((o) => o.textContent)).toEqual(["bitte wählen", "A Gruppe A", "B Gruppe B", "K Gruppe K"]);
    await user.click(screen.getByRole("button", { name: "Als Entwurf speichern" }));
    const alarm = (await screen.findAllByRole("alert")).map((a) => a.textContent).join(" ");
    expect(alarm).toMatch(/Wähle eine Gruppe/);
    expect(alarm).toMatch(/Der Titel fehlt/);
    expect(karteAnlegen).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Titel").getAttribute("aria-invalid")).toBe("true");

    await user.selectOptions(screen.getByLabelText("Gruppe"), "K");
    expect(screen.getByLabelText("Kennung (vorgeschlagen)")).toHaveProperty("value", "K1");
    await user.type(screen.getByLabelText("Titel"), "Mail mit Anhang");
    await user.type(screen.getByLabelText(/Aufgabe für den Gast/), "Schreib eine Mail.");
    await user.type(screen.getByLabelText("Erwartetes Ergebnis"), "Ein Entwurf liegt vor.");
    await user.click(screen.getByLabelText(/Fehlerfall: Dieser Use Case/));
    await user.type(screen.getByLabelText("Erwarteter Fehler"), "falsches Datum");
    await user.click(screen.getByLabelText("Mail"));
    // die Vorschau folgt dem Formular
    const vorschau = within(screen.getByRole("heading", { name: "Vorschau der gedruckten Karte" }).closest("section") as HTMLElement);
    expect(vorschau.getByText("Mail mit Anhang")).toBeTruthy();
    expect(vorschau.getByText("K1")).toBeTruthy();
    expect(vorschau.getByText("Werkzeuge: Mail")).toBeTruthy();
    vi.mocked(karteAnlegen).mockResolvedValueOnce({ karte: karte("K2") }); // der Dienst vergibt die Kennung, die Antwort gilt
    await user.click(screen.getByRole("button", { name: "Als Entwurf speichern" }));
    expect(karteAnlegen).toHaveBeenCalledWith({
      id: "K1", gruppe: "Gruppe K", titel: "Mail mit Anhang", aufgabe: "Schreib eine Mail.", erwartung: "Ein Entwurf liegt vor.",
      fehler: "falsches Datum", lernziel: null, wissen: "keine", wissenstext: null, werkzeuge: ["Mail"], dauerMin: 4,
    });
    expect(await screen.findByText(/Der Use Case K2 ist als Entwurf gespeichert/)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Neuen Use Case aufbauen", level: 2 })).toBeNull();
  });

  it("Katalogbudget: Eigener Text zählt, zu viel verhindert das Speichern", async () => {
    const user = userEvent.setup();
    vi.mocked(kartenLaden).mockResolvedValue({
      karten: [
        karte("A1", { wissen: "Eigener Text", wissenstext: "x".repeat(900) }),
        karte("A2", { wissen: "Eigener Text", wissenstext: "x".repeat(900) }),
      ],
      version: 1, gruppen: GRUPPEN
    });
    render(<Karten onFaktor={noop} />);
    await user.click(await screen.findByRole("button", { name: "Neuen Use Case aufbauen" }));
    expect(screen.getByText("1800 von 2000 Zeichen")).toBeTruthy();
    expect(screen.getByText("2 von 20")).toBeTruthy();
    await user.type(screen.getByLabelText("Titel"), "T");
    await user.type(screen.getByLabelText(/Aufgabe für den Gast/), "A");
    await user.type(screen.getByLabelText("Erwartetes Ergebnis"), "E");
    await user.selectOptions(screen.getByLabelText(/Wissen für W.A.I.S./), "Eigener Text");
    await user.click(screen.getByLabelText(/Eigener Wissenstext/));
    await user.paste("y".repeat(300));
    expect(screen.getByText("2100 von 2000 Zeichen")).toBeTruthy();
    expect(screen.getByText("3 von 20")).toBeTruthy();
    expect(screen.getByText(/Das Katalogbudget ist überschritten/)).toBeTruthy();
    expect(screen.getByRole("img", { name: /Katalog: 2100 von 2000 Zeichen, überschritten/ })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Als Entwurf speichern" }));
    expect((await screen.findAllByRole("alert")).map((a) => a.textContent).join(" ")).toMatch(/Katalogbudget ist überschritten: 2100 von 2000 Zeichen/);
    expect(karteAnlegen).not.toHaveBeenCalled();
  });

  it("Wissenstext mit Markup wird vor dem Senden gemeldet; lehnt der Dienst ihn ab, steht ein klarer Satz da", async () => {
    const user = userEvent.setup();
    vi.mocked(kartenLaden).mockResolvedValue({ karten: [karte("A1")], version: 1, gruppen: GRUPPEN });
    render(<Karten onFaktor={noop} />);
    await user.click(await screen.findByRole("button", { name: "Neuen Use Case aufbauen" }));
    await user.selectOptions(screen.getByLabelText("Gruppe"), "A");
    await user.type(screen.getByLabelText("Titel"), "T");
    await user.type(screen.getByLabelText(/Aufgabe für den Gast/), "A");
    await user.type(screen.getByLabelText("Erwartetes Ergebnis"), "E");
    await user.selectOptions(screen.getByLabelText(/Wissen für W.A.I.S./), "Eigener Text");
    await user.click(screen.getByLabelText(/Eigener Wissenstext/));
    await user.paste("Text mit <b>Markup</b>");
    await user.click(screen.getByRole("button", { name: "Als Entwurf speichern" }));
    const meldung = (await screen.findAllByRole("alert")).find((a) => /enthält Markup/.test(a.textContent ?? ""));
    expect(meldung).toBeTruthy();
    expect(karteAnlegen).not.toHaveBeenCalled();
    // Nach der Prüfung springt der Fokus (im nächsten Bild) auf die Meldung. Erst wenn er dort ist, wird der Text ersetzt,
    // sonst fiele das Einfügen ins Leere: der Test war davon abhängig, wie schnell der Rechner das nächste Bild zeichnet.
    await waitFor(() => expect(document.activeElement).toBe(meldung));
    // ein Text, den nur der Dienst beanstandet (zum Beispiel eine Rollenzeile mitten im Text)
    const feld = screen.getByLabelText(/Eigener Wissenstext/);
    await user.click(feld);
    await user.clear(feld);
    await user.paste("Ein erlaubter Satz.");
    expect(feld).toHaveProperty("value", "Ein erlaubter Satz.");
    vi.mocked(karteAnlegen).mockRejectedValueOnce(new WerkstattFehler(fehlerBild(422, "ungueltig", "Der Wissenstext enthält eine Rollenzeile.")));
    await user.click(screen.getByRole("button", { name: "Als Entwurf speichern" }));
    expect((await screen.findAllByRole("alert")).map((a) => a.textContent).join(" ")).toMatch(/Der Wissenstext enthält eine Rollenzeile/);
    expect(screen.getByText("Der Dienst hat den Text abgelehnt. Prüfe ihn auf Markup, Rollenzeilen und unsichtbare Zeichen.")).toBeTruthy();
  });

  it("Bearbeiten hält Kennung und Gruppe fest, Kopieren vergibt die nächste Kennung, Löschen fragt nach", async () => {
    const user = userEvent.setup();
    render(<Karten onFaktor={noop} />);
    await user.click(await screen.findByRole("button", { name: "A1 bearbeiten" }));
    expect(screen.getByRole("heading", { name: "Use Case A1 bearbeiten", level: 2 })).toBeTruthy();
    expect(screen.getByLabelText("Gruppe")).toHaveProperty("disabled", true);
    await user.clear(screen.getByLabelText("Titel"));
    await user.type(screen.getByLabelText("Titel"), "Neuer Titel");
    await user.click(screen.getByRole("button", { name: "Als Entwurf speichern" }));
    expect(karteAendern).toHaveBeenCalledWith(expect.objectContaining({ id: "A1", gruppe: "Gruppe A", titel: "Neuer Titel" }));

    await user.click(await screen.findByRole("button", { name: "A1 kopieren" }));
    expect(screen.getByLabelText("Kennung (vorgeschlagen)")).toHaveProperty("value", "A3");
    expect(screen.getByLabelText("Titel")).toHaveProperty("value", "Titel A1 (Kopie)");
    expect(screen.queryByRole("button", { name: "A1 löschen" })).toBeNull(); // veröffentlicht: nicht löschbar
    await user.click(screen.getByRole("button", { name: "A2 löschen" }));
    expect(karteLoeschen).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Ja, A2 löschen" }));
    expect(karteLoeschen).toHaveBeenCalledWith("A2");
    expect(await screen.findByText("Der Entwurf A2 ist gelöscht.")).toBeTruthy();
  });

  it("der Gruppenfilter schränkt die Tabelle ein", async () => {
    const user = userEvent.setup();
    vi.mocked(kartenLaden).mockResolvedValue({ karten: [karte("A1"), karte("B1")], version: 1, gruppen: GRUPPEN });
    render(<Karten onFaktor={noop} />);
    await screen.findByText("2 von 2 Karten");
    await user.selectOptions(screen.getByLabelText("Gruppe anzeigen"), "B");
    expect(screen.getByText("1 von 2 Karten")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "A1 bearbeiten" })).toBeNull();
  });
});

describe("Zuordnung", () => {
  it("Matrix mit den Plätzen der Gäste, Zeit je Spalte, Speichern erst bei einer Änderung", async () => {
    const user = userEvent.setup();
    render(<Karten onFaktor={noop} />);
    const kreuz = await screen.findByRole("checkbox", { name: "A1 für Gast 1, Platz 1" });
    expect((kreuz as HTMLInputElement).checked).toBe(true);
    expect(screen.queryByRole("checkbox", { name: /für Platz 15/ })).toBeNull(); // Abnahme hat keinen Kartensatz
    const speichern = screen.getByRole("button", { name: "Zuordnung speichern" });
    expect(speichern).toHaveProperty("disabled", true);
    await user.click(screen.getByRole("checkbox", { name: "A2 für Platz 2" }));
    await user.click(screen.getByRole("checkbox", { name: "A2 für Gast 1, Platz 1" }));
    expect(screen.getByText("Es gibt ungespeicherte Änderungen.")).toBeTruthy();
    expect(speichern).toHaveProperty("disabled", false);
    await user.click(speichern);
    expect(zuordnungSpeichern).toHaveBeenCalledWith("t1", { 1: ["A1", "A2"], 2: ["A2"] });
    expect(await screen.findByText("Die Zuordnung ist gespeichert.")).toBeTruthy();
  });

  it("Zeiten über dem Richtwert werden als Wort gemeldet", async () => {
    vi.mocked(kartenLaden).mockResolvedValue({
      karten: Array.from({ length: 3 }, (_, i) => karte(`A${i + 1}`, { dauerMin: 10 })), version: 1, gruppen: GRUPPEN
    });
    vi.mocked(zuordnungLaden).mockResolvedValue({ 1: ["A1", "A2", "A3"] });
    render(<Karten onFaktor={noop} />);
    expect(await screen.findByText("30 Min.")).toBeTruthy();
    expect(screen.getByText(/, lang/)).toBeTruthy();
  });

  it("ohne Termin ein Hinweis auf den Labor-Planer", async () => {
    vi.mocked(termineLaden).mockResolvedValue([]);
    render(<Karten onFaktor={noop} />);
    expect(await screen.findByText(/Lege im Labor-Planer zuerst einen Termin an/)).toBeTruthy();
  });
});

describe("Veröffentlichen in vier Schritten", () => {
  const frischeKarte = () => ({ id: "k1", giltBis: new Date(Date.now() + 300_000).toISOString(), aenderungen: 1, karten: ["A2"], basisVersion: 4 });

  beforeEach(() => {
    vi.mocked(kartenPruefen).mockResolvedValue({ ok: true, probleme: [], zeichen: 1200 });
    vi.mocked(freigabeKarteAnlegen).mockImplementation(async () => frischeKarte());
    vi.mocked(codeBestaetigen).mockResolvedValue({ ok: true });
    vi.mocked(freigabeAusfuehren).mockResolvedValue({ version: 5, zeichen: 1200 });
  });

  const schritt = (name: string) => within(screen.getByRole("heading", { name: new RegExp(`^${name}`), level: 3 }).closest("li") as HTMLElement);

  it("Prüfung, Karte, Code, Ergebnis: jeder Schritt wird erledigt, der Katalog lädt neu, der Rahmen erfährt vom Code", async () => {
    const user = userEvent.setup();
    const onFaktor = vi.fn();
    render(<Karten onFaktor={onFaktor} />);
    expect(await screen.findByText(/1 Entwurf: A2/)).toBeTruthy();
    expect(schritt("Prüfung").getByText("jetzt dran")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Prüfen" }));
    expect(await screen.findByText("Geprüft: 1200 von 2000 Zeichen im Katalog, keine Probleme.")).toBeTruthy();
    expect(screen.getByText("Katalog Version 5 mit 1 Änderung: A2.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Karte anlegen" }));
    expect(await screen.findByText(/Gültig noch/)).toBeTruthy();
    expect(schritt("Karte").getByText("erledigt")).toBeTruthy();
    expect(schritt("Zweiter Faktor").getByText("jetzt dran")).toBeTruthy();
    const veroeffentlichen = screen.getByRole("button", { name: "Veröffentlichen" });
    expect(veroeffentlichen).toHaveProperty("disabled", true);
    await user.type(screen.getByLabelText("Sechsstelliger Code"), "123 456");
    await user.click(veroeffentlichen);
    expect(codeBestaetigen).toHaveBeenCalledWith("123456");
    expect(freigabeAusfuehren).toHaveBeenCalledWith("k1");
    expect(await screen.findByText(/Version 5 ist veröffentlicht, 1200 Zeichen/)).toBeTruthy();
    expect(schritt("Kern lädt nach").getByText("erledigt")).toBeTruthy();
    expect(onFaktor).toHaveBeenCalledTimes(1);
    expect(kartenLaden).toHaveBeenCalledTimes(2);
    expect(versionenLaden).toHaveBeenCalledTimes(2);
  });

  it("ohne Entwürfe gibt es nichts zu prüfen", async () => {
    vi.mocked(kartenLaden).mockResolvedValue({ karten: [karte("A1")], version: 1, gruppen: GRUPPEN });
    render(<Karten onFaktor={noop} />);
    expect(await screen.findByText("Keine Entwürfe. Speichere zuerst einen Use Case.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Prüfen" })).toBeNull();
  });

  it("eine abgelehnte Prüfung nennt die Probleme und legt keine Karte an", async () => {
    const user = userEvent.setup();
    vi.mocked(kartenPruefen).mockResolvedValue({ ok: false, probleme: ["Die Karte A2 enthält eine Anweisung."], zeichen: 2100 });
    render(<Karten onFaktor={noop} />);
    await user.click(await screen.findByRole("button", { name: "Prüfen" }));
    const alarm = await screen.findByText(/Die Prüfung lehnt die Karten ab \(2100 Zeichen\)/);
    expect(alarm.textContent).toMatch(/enthält eine Anweisung/);
    expect(screen.getByRole("button", { name: "Noch einmal prüfen" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Karte anlegen" })).toBeNull();
    expect(freigabeKarteAnlegen).not.toHaveBeenCalled();
  });

  it("ein falscher oder zu alter Code lässt die Karte stehen und leert das Feld", async () => {
    const user = userEvent.setup();
    render(<Karten onFaktor={noop} />);
    await user.click(await screen.findByRole("button", { name: "Prüfen" }));
    await user.click(await screen.findByRole("button", { name: "Karte anlegen" }));
    await screen.findByText(/Gültig noch/);
    vi.mocked(codeBestaetigen).mockResolvedValueOnce({ ok: false, text: "Der Code passt nicht. Nimm den aktuellen aus der App." });
    await user.type(screen.getByLabelText("Sechsstelliger Code"), "111111");
    await user.click(screen.getByRole("button", { name: "Veröffentlichen" }));
    expect((await screen.findAllByRole("alert")).some((a) => /Der Code passt nicht/.test(a.textContent ?? ""))).toBe(true);
    expect(freigabeAusfuehren).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Sechsstelliger Code")).toHaveProperty("value", "");

    vi.mocked(freigabeAusfuehren).mockRejectedValueOnce(new WerkstattFehler(fehlerBild(403, "aal2_alt", null)));
    await user.type(screen.getByLabelText("Sechsstelliger Code"), "222222");
    await user.click(screen.getByRole("button", { name: "Veröffentlichen" }));
    expect((await screen.findAllByRole("alert")).some((a) => /Code des zweiten Faktors ist zu alt/.test(a.textContent ?? ""))).toBe(true);
    expect(screen.getByText(/Gültig noch/)).toBeTruthy();
  });

  it("eine abgelaufene oder verbrauchte Karte führt zurück zum Anlegen einer neuen", async () => {
    const user = userEvent.setup();
    render(<Karten onFaktor={noop} />);
    await user.click(await screen.findByRole("button", { name: "Prüfen" }));
    await user.click(await screen.findByRole("button", { name: "Karte anlegen" }));
    await screen.findByText(/Gültig noch/);
    vi.mocked(freigabeAusfuehren).mockRejectedValueOnce(new WerkstattFehler(fehlerBild(410, "karte_abgelaufen", null)));
    await user.type(screen.getByLabelText("Sechsstelliger Code"), "123456");
    await user.click(screen.getByRole("button", { name: "Veröffentlichen" }));
    expect((await screen.findAllByRole("alert")).some((a) => /Die Karte ist abgelaufen/.test(a.textContent ?? ""))).toBe(true);
    expect(await screen.findByRole("button", { name: "Karte anlegen" })).toBeTruthy();
  });

  it("die Uhr der Karte läuft ab: nach fünf Minuten steht der Satz und ein Knopf für eine neue Karte", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true, toFake: ["setInterval", "clearInterval", "Date"] });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<Karten onFaktor={noop} />);
    await user.click(await screen.findByRole("button", { name: "Prüfen" }));
    await user.click(await screen.findByRole("button", { name: "Karte anlegen" }));
    expect(await screen.findByText(/Gültig noch/)).toBeTruthy();
    await act(async () => {
      vi.advanceTimersByTime(301_000);
    });
    expect(await screen.findByText("Die Karte ist abgelaufen. Bitte lege eine neue Karte an.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Neue Karte" }));
    expect(await screen.findByRole("button", { name: "Karte anlegen" })).toBeTruthy();
  });
});
