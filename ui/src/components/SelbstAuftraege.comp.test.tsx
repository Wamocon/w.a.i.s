// Komponententest der Aufträge an W.A.I.S. selbst (components/SelbstAuftraege.tsx, Servernachricht "selbstauftraege"): Den Block gibt es erst,
// wenn der Kern mindestens einmal mit Liste geantwortet hat, und nie im Labor (ohne Aktionen). Er zeigt Nummer, Titel, Art, Priorität, Status,
// den Hinweis nach Fremdinhalt, Bearbeiter und Ergebnis, immer als Text. Verwerfen und Wieder öffnen senden die Nummer, ohne Dialog des
// Browsers; das Formular prüft vor dem Senden, zeigt Fehler des Kerns, leert sich nach Erfolg und sagt jede Rückmeldung über Live-Regionen an.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SelbstAuftraege } from "@/components/SelbstAuftraege";
import {
  SELBST_BESCHREIBUNG_MAX,
  SELBST_LEER,
  SELBST_TITEL_MAX,
  type SelbstAuftrag,
  type SelbstStand,
} from "@/lib/selbstAuftraege";
import { parseServerMessage } from "@/lib/nachrichten";
import type { SelbstAuftragAktionen } from "@/lib/useWamo";
import { applyServerMessage, resetWamo, selbstAuftragWarten, wamo } from "@/lib/wamo";

const A1: SelbstAuftrag = {
  nr: 7,
  titel: "Der Verlauf lädt zu langsam",
  art: "fehlerbehebung",
  prioritaet: 1,
  status: "offen",
  quelle: "sprache",
  unsicher: false,
  erstelltMs: Date.UTC(2026, 10, 18, 9),
};
const A2: SelbstAuftrag = { ...A1, nr: 8, titel: "Dunkles Design prüfen", art: "frontend", prioritaet: 3, status: "verworfen", quelle: "oberflaeche" };
const A3: SelbstAuftrag = { ...A1, nr: 9, titel: "Mitglieder bekommen Hinweise", art: "umsetzung", prioritaet: 2, status: "erledigt", quelle: "claude_code" };
const A4: SelbstAuftrag = { ...A1, nr: 10, titel: "Stimmerkennung messen", art: "analyse", prioritaet: 2, status: "in_arbeit" };

function stand(extra: Partial<SelbstStand> = {}, online = true, liste: SelbstAuftrag[] = [A1]) {
  wamo.set((s) => ({ ...s, presence: online ? "idle" : "offline", selbstAuftraege: { ...SELBST_LEER, liste, max: 200, ...extra } }));
}

/** Aktionen wie in useWamo: Senden sperrt über den Store, bis die Antwort kommt. */
function aktionen(ok = true): SelbstAuftragAktionen {
  const senden = (aktion: "speichern" | "verwerfen" | "oeffnen") =>
    vi.fn(() => {
      if (ok) selbstAuftragWarten(aktion);
      return ok;
    });
  return { speichern: senden("speichern"), verwerfen: senden("verwerfen"), oeffnen: senden("oeffnen") };
}

/** Ein Eintrag so, wie ihn der Kern schickt (Draht), damit die Antwort durch die Prüfung der Oberfläche läuft. */
const draht = (a: SelbstAuftrag) => ({
  nr: a.nr,
  titel: a.titel,
  art: a.art,
  prioritaet: a.prioritaet,
  status: a.status,
  quelle: a.quelle,
  unsicher: a.unsicher,
  erstellt_ms: a.erstelltMs,
  bearbeiter: a.bearbeiter,
  ergebnis: a.ergebnis,
});

/** Antwort des Kerns, geprüft wie im Betrieb (parseServerMessage), dann in den Store übernommen. */
const antwort = (aktion: "liste" | "speichern" | "verwerfen" | "oeffnen", extra: Record<string, unknown> = {}) =>
  act(() => {
    const m = parseServerMessage({ type: "selbstauftraege", aktion, ok: true, ...extra });
    if (!m) throw new Error("Nachricht abgelehnt");
    applyServerMessage(m);
  });

const knopf = (name: string | RegExp) => screen.getByRole("button", { name }) as HTMLButtonElement;
const feld = (name: string | RegExp) => screen.getByRole("textbox", { name }) as HTMLInputElement | HTMLTextAreaElement;
const auswahl = (name: string | RegExp) => screen.getByRole("combobox", { name }) as HTMLSelectElement;

describe("Aufträge an W.A.I.S. selbst: Sichtbarkeit", () => {
  beforeEach(() => resetWamo());

  it("ohne Antwort des Kerns erscheint nichts: keine Überschrift, kein Formular, keine Meldung", () => {
    const { container } = render(<SelbstAuftraege aktionen={aktionen()} />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByRole("heading")).toBeNull();
    expect(screen.queryByRole("form")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("im Labor (ohne Aktionen) bleibt alles weg, auch wenn ein Zustand da wäre", () => {
    stand();
    const { container } = render(<SelbstAuftraege />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByRole("heading", { name: "Aufträge an W.A.I.S. selbst" })).toBeNull();
  });

  it("erscheint, sobald der Kern mit Liste geantwortet hat, und verschwindet mit dem Zustand wieder", () => {
    render(<SelbstAuftraege aktionen={aktionen()} />);
    expect(screen.queryByRole("heading", { name: "Aufträge an W.A.I.S. selbst" })).toBeNull();
    antwort("liste", { auftraege: [], max: 200 });
    expect(screen.getByRole("heading", { name: "Aufträge an W.A.I.S. selbst" })).toBeTruthy();
    act(() => wamo.set((s) => ({ ...s, selbstAuftraege: null })));
    expect(screen.queryByRole("heading", { name: "Aufträge an W.A.I.S. selbst" })).toBeNull();
  });

  it("ein Nein des Kerns oder eine Antwort ohne Liste zeigt nichts, auch keinen Fehler", () => {
    const { container } = render(<SelbstAuftraege aktionen={aktionen()} />);
    antwort("liste", { ok: false, grund: "Das gibt es in dieser Sitzung nicht." });
    antwort("liste");
    expect(container.firstChild).toBeNull();
  });
});

describe("Aufträge an W.A.I.S. selbst: Liste", () => {
  beforeEach(() => resetWamo());

  it("zeigt Nummer, Titel, Art, Priorität, Status, Quelle und Datum, in der Reihenfolge des Kerns", () => {
    stand({}, true, [A2, A1]);
    render(<SelbstAuftraege aktionen={aktionen()} />);
    const eintraege = screen.getAllByRole("listitem");
    expect(eintraege).toHaveLength(2);
    expect(within(eintraege[0]).getByText("SA-8")).toBeTruthy();
    expect(within(eintraege[0]).getByText("Dunkles Design prüfen")).toBeTruthy();
    expect(within(eintraege[0]).getByText("Verworfen")).toBeTruthy();
    expect(eintraege[0].textContent).toMatch(/Frontend · Priorität Niedrig · Quelle Oberfläche · erstellt am 18\.11\.2026/);
    expect(within(eintraege[1]).getByText("SA-7")).toBeTruthy();
    expect(within(eintraege[1]).getByText("Offen")).toBeTruthy();
    expect(eintraege[1].textContent).toMatch(/Fehlerbehebung · Priorität Hoch · Quelle Sprache/);
    expect(screen.getByText(/2 Einträge im Rückstand, höchstens 200/)).toBeTruthy();
  });

  it("alle vier Statusmarken stehen als Text da", () => {
    stand({}, true, [A1, A4, A3, A2]);
    render(<SelbstAuftraege aktionen={aktionen()} />);
    for (const marke of ["Offen", "In Arbeit", "Erledigt", "Verworfen"]) expect(screen.getByText(marke)).toBeTruthy();
  });

  it("eine unsichere Eintragung trägt den Hinweis, eine andere nicht", () => {
    stand({}, true, [{ ...A1, unsicher: true }, A4]);
    render(<SelbstAuftraege aktionen={aktionen()} />);
    const hinweise = screen.getAllByText("Nach Fremdinhalt gespeichert, bitte prüfen");
    expect(hinweise).toHaveLength(1);
    expect(within(screen.getAllByRole("listitem")[0]).getByText("Nach Fremdinhalt gespeichert, bitte prüfen")).toBeTruthy();
  });

  it("zeigt Bearbeiter und Ergebnis, wo es sie gibt", () => {
    stand({}, true, [
      { ...A3, bearbeiter: "claude_code", ergebnis: "Umgesetzt in Version 0.7.0.\nDie Tests laufen." },
      { ...A4, bearbeiter: "wais" },
      A1,
    ]);
    render(<SelbstAuftraege aktionen={aktionen()} />);
    const [erledigt, laufend, offen] = screen.getAllByRole("listitem");
    expect(erledigt.textContent).toMatch(/Bearbeiter: Claude Code/);
    expect(erledigt.textContent).toMatch(/Ergebnis:\s*Umgesetzt in Version 0\.7\.0\.\s*Die Tests laufen\./);
    expect(laufend.textContent).toMatch(/Bearbeiter: W\.A\.I\.S\./);
    expect(laufend.textContent).not.toMatch(/Ergebnis/);
    expect(offen.textContent).not.toMatch(/Bearbeiter/);
  });

  it("Texte stehen nur als Text da, nie als HTML", () => {
    stand({}, true, [{ ...A1, titel: "<img src=x onerror=alert(1)>", ergebnis: "<b>fett</b><script>alert(2)</script>" }]);
    const { container } = render(<SelbstAuftraege aktionen={aktionen()} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeTruthy();
  });

  it("eine leere Liste sagt es in einem Satz, das Formular bleibt", () => {
    stand({}, true, []);
    render(<SelbstAuftraege aktionen={aktionen()} />);
    expect(screen.getByText(/Noch keine Aufträge an W\.A\.I\.S\. selbst/)).toBeTruthy();
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.getByRole("form", { name: "Neuer Auftrag an W.A.I.S." })).toBeTruthy();
  });

  it("eine unbekannte Quelle lässt nur die Quelle weg, der Eintrag bleibt", () => {
    stand({}, true, [{ ...A1, quelle: undefined }]);
    render(<SelbstAuftraege aktionen={aktionen()} />);
    expect(screen.getByText("Der Verlauf lädt zu langsam")).toBeTruthy();
    expect(screen.getByRole("listitem").textContent).not.toMatch(/Quelle/);
  });

  it("eine Art, die ein Name der Prototypkette ist, steht als Text da", () => {
    stand({}, true, [{ ...A1, art: "constructor" }]);
    render(<SelbstAuftraege aktionen={aktionen()} />);
    expect(screen.getByRole("listitem").textContent).toMatch(/constructor · Priorität Hoch/);
  });

  it("ein einzelner Eintrag steht in der Einzahl, ohne Grenze fehlt der Zusatz", () => {
    stand({ max: null });
    render(<SelbstAuftraege aktionen={aktionen()} />);
    expect(screen.getByText("1 Eintrag im Rückstand.")).toBeTruthy();
  });
});

describe("Aufträge an W.A.I.S. selbst: Verwerfen und Wieder öffnen", () => {
  beforeEach(() => resetWamo());

  it("Verwerfen gibt es bei offenen und laufenden, Wieder öffnen bei verworfenen, bei erledigten keinen Knopf", () => {
    stand({}, true, [A1, A4, A2, A3]);
    render(<SelbstAuftraege aktionen={aktionen()} />);
    expect(knopf("Verwerfen: SA-7 Der Verlauf lädt zu langsam")).toBeTruthy();
    expect(knopf("Verwerfen: SA-10 Stimmerkennung messen")).toBeTruthy();
    expect(knopf("Wieder öffnen: SA-8 Dunkles Design prüfen")).toBeTruthy();
    const erledigt = screen.getAllByRole("listitem")[3];
    expect(within(erledigt).queryByRole("button")).toBeNull();
    expect(screen.queryByRole("button", { name: /SA-9/ })).toBeNull();
  });

  it("die Knöpfe senden die Nummer, ohne Dialog des Browsers", () => {
    const dialog = vi.spyOn(window, "confirm").mockReturnValue(true);
    stand({}, true, [A1, A2]);
    const ak = aktionen();
    render(<SelbstAuftraege aktionen={ak} />);
    fireEvent.click(knopf(/^Verwerfen: SA-7/));
    expect(ak.verwerfen).toHaveBeenCalledWith(7);
    antwort("verwerfen", { text: "Verworfen." });
    fireEvent.click(knopf(/^Wieder öffnen: SA-8/));
    expect(ak.oeffnen).toHaveBeenCalledWith(8);
    expect(dialog).not.toHaveBeenCalled();
  });

  it("ohne Verbindung und während eine Aktion wartet, sind alle Knöpfe gesperrt", () => {
    stand({}, false, [A1, A2]);
    const { unmount } = render(<SelbstAuftraege aktionen={aktionen()} />);
    expect(knopf(/^Verwerfen/).disabled).toBe(true);
    expect(knopf(/^Wieder öffnen/).disabled).toBe(true);
    expect(knopf("Speichern").disabled).toBe(true);
    unmount();
    stand({ wartet: { aktion: "verwerfen", n: 1 } }, true, [A1, A2]);
    render(<SelbstAuftraege aktionen={aktionen()} />);
    expect(knopf(/^Verwerfen/).disabled).toBe(true);
    expect(knopf(/^Wieder öffnen/).disabled).toBe(true);
    expect(knopf("Speichern").disabled).toBe(true);
  });

  it("nach der Antwort kehrt der Fokus auf den Knopf des Eintrags zurück, der dann Wieder öffnen heißt", () => {
    stand({}, true, [A1]);
    render(<SelbstAuftraege aktionen={aktionen()} />);
    const verwerfen = knopf(/^Verwerfen: SA-7/);
    verwerfen.focus();
    fireEvent.click(verwerfen);
    expect(knopf(/^Verwerfen: SA-7/).disabled).toBe(true);
    antwort("verwerfen", { text: "Verworfen.", auftraege: [draht({ ...A1, status: "verworfen" })] });
    const oeffnen = knopf(/^Wieder öffnen: SA-7/);
    expect(oeffnen.disabled).toBe(false);
    expect(document.activeElement).toBe(oeffnen);
  });

  it("zwei gleichlautende Erfolge hintereinander sind für die Live-Region zwei Änderungen (neues Element je Meldung)", () => {
    stand({}, true, [A1, A4]);
    render(<SelbstAuftraege aktionen={aktionen()} />);
    const region = screen.getByRole("status");
    fireEvent.click(knopf(/^Verwerfen: SA-7/));
    antwort("verwerfen", { text: "Verworfen." });
    const erste = within(region).getByText("Verworfen.");
    fireEvent.click(knopf(/^Verwerfen: SA-10/));
    expect(region.textContent).toBe(""); // die Meldung zur Aktion davor ist beim nächsten Klick weg
    antwort("verwerfen", { text: "Verworfen." });
    const zweite = within(region).getByText("Verworfen.");
    expect(zweite).not.toBe(erste);
    expect(screen.getByRole("status")).toBe(region); // die Region selbst bleibt dieselbe
  });

  it("die Meldung zum Verwerfen steht in der Live-Region, ein Fehler des Kerns als Alarm", () => {
    stand({}, true, [A1]);
    render(<SelbstAuftraege aktionen={aktionen()} />);
    fireEvent.click(knopf(/^Verwerfen/));
    antwort("verwerfen", { text: "SA-7 ist verworfen." });
    expect(screen.getByRole("status").textContent).toBe("SA-7 ist verworfen.");
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(knopf(/^Verwerfen/));
    antwort("verwerfen", { ok: false, grund: "Dieser Auftrag ist schon in Arbeit." });
    expect(screen.getByRole("alert").textContent).toBe("Dieser Auftrag ist schon in Arbeit.");
    expect(screen.getByRole("status").textContent).toBe(""); // der Erfolgstext ist weg, die Region bleibt im DOM
  });
});

describe("Aufträge an W.A.I.S. selbst: Formular", () => {
  beforeEach(() => resetWamo());

  it("hat beschriftete Felder, die 13 Arten mit Umsetzung als Standard und die drei Prioritäten mit Normal als Standard", () => {
    stand();
    render(<SelbstAuftraege aktionen={aktionen()} />);
    expect(screen.getByRole("form", { name: "Neuer Auftrag an W.A.I.S." })).toBeTruthy();
    expect(feld("Titel")).toBeTruthy();
    expect(feld("Beschreibung")).toBeTruthy();
    const art = auswahl("Art");
    expect(Array.from(art.options).map((o) => o.value)).toEqual([
      "umsetzung",
      "fehlerbehebung",
      "planung",
      "review",
      "test",
      "sicherheit",
      "refactoring",
      "dokumentation",
      "datenbank",
      "frontend",
      "deployment",
      "analyse",
      "recherche",
    ]);
    expect(art.value).toBe("umsetzung");
    expect(Array.from(art.options)[1].textContent).toBe("Fehlerbehebung");
    const prio = auswahl("Priorität");
    expect(Array.from(prio.options).map((o) => o.textContent)).toEqual(["Hoch", "Normal", "Niedrig"]);
    expect(prio.value).toBe("2");
  });

  it("Titel und Beschreibung sind Pflichtfelder und nehmen höchstens das Doppelte der Grenze auf", () => {
    stand();
    render(<SelbstAuftraege aktionen={aktionen()} />);
    expect(feld("Titel").getAttribute("aria-required")).toBe("true");
    expect(feld("Beschreibung").getAttribute("aria-required")).toBe("true");
    expect(feld("Titel").getAttribute("maxlength")).toBe(String(SELBST_TITEL_MAX * 2));
    expect(feld("Beschreibung").getAttribute("maxlength")).toBe(String(SELBST_BESCHREIBUNG_MAX * 2));
  });

  it("die Zähler zählen mit und gehören zu den Feldern", () => {
    stand();
    render(<SelbstAuftraege aktionen={aktionen()} />);
    expect(screen.getByText(`0 von ${SELBST_TITEL_MAX} Zeichen`)).toBeTruthy();
    expect(screen.getByText(`0 von ${SELBST_BESCHREIBUNG_MAX} Zeichen`)).toBeTruthy();
    fireEvent.change(feld("Titel"), { target: { value: "Verlauf" } });
    fireEvent.change(feld("Beschreibung"), { target: { value: "Der Verlauf soll schneller laden." } });
    const zaehlerTitel = screen.getByText(`7 von ${SELBST_TITEL_MAX} Zeichen`);
    expect(feld("Titel").getAttribute("aria-describedby")).toContain(zaehlerTitel.id);
    expect(screen.getByText(`33 von ${SELBST_BESCHREIBUNG_MAX} Zeichen`)).toBeTruthy();
  });

  it("sendet Titel, Beschreibung, Art und Priorität", async () => {
    stand();
    const ak = aktionen();
    const nutzer = userEvent.setup();
    render(<SelbstAuftraege aktionen={ak} />);
    await nutzer.type(feld("Titel"), "Verlauf beschleunigen");
    await nutzer.type(feld("Beschreibung"), "Der Verlauf soll schneller laden.");
    await nutzer.selectOptions(auswahl("Art"), "fehlerbehebung");
    await nutzer.selectOptions(auswahl("Priorität"), "Hoch");
    await nutzer.click(knopf("Speichern"));
    expect(ak.speichern).toHaveBeenCalledTimes(1);
    expect(ak.speichern).toHaveBeenCalledWith({
      titel: "Verlauf beschleunigen",
      beschreibung: "Der Verlauf soll schneller laden.",
      art: "fehlerbehebung",
      prioritaet: 1,
    });
    // während der Kern noch nicht geantwortet hat: gesperrt und mit Hinweis
    expect(knopf("Wird gespeichert …").disabled).toBe(true);
  });

  it("Enter im Titelfeld sendet das Formular", async () => {
    stand();
    const ak = aktionen();
    const nutzer = userEvent.setup();
    render(<SelbstAuftraege aktionen={ak} />);
    await nutzer.type(feld("Beschreibung"), "Der Verlauf soll schneller laden.");
    await nutzer.type(feld("Titel"), "Verlauf beschleunigen{Enter}");
    expect(ak.speichern).toHaveBeenCalledTimes(1);
  });

  it("prüft vor dem Senden: leerer Titel, leere Beschreibung, zu lange Texte; der Fehler steht als Alarm da und das Feld bekommt den Fokus", async () => {
    stand();
    const ak = aktionen();
    const nutzer = userEvent.setup();
    render(<SelbstAuftraege aktionen={ak} />);
    await nutzer.click(knopf("Speichern"));
    expect(screen.getByRole("alert").textContent).toBe("Bitte gib einen Titel an.");
    expect(document.activeElement).toBe(feld("Titel"));
    expect(feld("Titel").getAttribute("aria-invalid")).toBe("true");
    expect(feld("Titel").getAttribute("aria-describedby")).toContain(screen.getByRole("alert").id);
    expect(ak.speichern).not.toHaveBeenCalled();
    // ein Eintippen nimmt den Fehler weg
    fireEvent.change(feld("Titel"), { target: { value: "Ein Titel" } });
    expect(screen.queryByRole("alert")).toBeNull();
    await nutzer.click(knopf("Speichern"));
    expect(screen.getByRole("alert").textContent).toBe("Bitte gib eine Beschreibung an.");
    expect(document.activeElement).toBe(feld("Beschreibung"));
    fireEvent.change(feld("Titel"), { target: { value: "x".repeat(SELBST_TITEL_MAX + 1) } });
    fireEvent.change(feld("Beschreibung"), { target: { value: "Text" } });
    await nutzer.click(knopf("Speichern"));
    expect(screen.getByRole("alert").textContent).toMatch(/höchstens 80 Zeichen/);
    fireEvent.change(feld("Titel"), { target: { value: "Kurz" } });
    fireEvent.change(feld("Beschreibung"), { target: { value: "y".repeat(SELBST_BESCHREIBUNG_MAX + 1) } });
    await nutzer.click(knopf("Speichern"));
    expect(screen.getByRole("alert").textContent).toMatch(/höchstens 4000 Zeichen/);
    expect(ak.speichern).not.toHaveBeenCalled();
  });

  it("nach Erfolg sind die Eingaben leer, die Auswahl steht wieder auf dem Standard und die Meldung steht in der Live-Region", async () => {
    stand();
    const ak = aktionen();
    const nutzer = userEvent.setup();
    render(<SelbstAuftraege aktionen={ak} />);
    await nutzer.type(feld("Titel"), "Verlauf beschleunigen");
    await nutzer.type(feld("Beschreibung"), "Der Verlauf soll schneller laden.");
    await nutzer.selectOptions(auswahl("Art"), "sicherheit");
    await nutzer.selectOptions(auswahl("Priorität"), "Niedrig");
    await nutzer.click(knopf("Speichern"));
    expect(feld("Titel").value).toBe("Verlauf beschleunigen"); // bis zur Antwort bleibt alles stehen
    antwort("speichern", { text: "Gespeichert als SA-11.", auftraege: [draht(A1)], max: 200 });
    expect(feld("Titel").value).toBe("");
    expect(feld("Beschreibung").value).toBe("");
    expect(auswahl("Art").value).toBe("umsetzung");
    expect(auswahl("Priorität").value).toBe("2");
    expect(screen.getByRole("status").textContent).toBe("Gespeichert als SA-11.");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(knopf("Speichern").disabled).toBe(false);
  });

  it("ein Fehler des Kerns steht als Alarm da und lässt die Eingaben stehen", async () => {
    stand();
    const ak = aktionen();
    const nutzer = userEvent.setup();
    render(<SelbstAuftraege aktionen={ak} />);
    await nutzer.type(feld("Titel"), "Verlauf beschleunigen");
    await nutzer.type(feld("Beschreibung"), "Der Verlauf soll schneller laden.");
    await nutzer.click(knopf("Speichern"));
    antwort("speichern", { ok: false, grund: "Der Rückstand ist voll." });
    expect(screen.getByRole("alert").textContent).toBe("Der Rückstand ist voll.");
    expect(feld("Titel").value).toBe("Verlauf beschleunigen");
    expect(feld("Beschreibung").value).toBe("Der Verlauf soll schneller laden.");
    expect(knopf("Speichern").disabled).toBe(false); // jetzt ein zweiter Versuch
  });

  it("was die Person während des Wartens ändert, geht nicht verloren: das Formular leert sich nur, wenn es unverändert ist", async () => {
    stand();
    const ak = aktionen();
    const nutzer = userEvent.setup();
    render(<SelbstAuftraege aktionen={ak} />);
    await nutzer.type(feld("Titel"), "Verlauf beschleunigen");
    await nutzer.type(feld("Beschreibung"), "Der Verlauf soll schneller laden.");
    await nutzer.click(knopf("Speichern"));
    await nutzer.type(feld("Titel"), " und mehr"); // die Person tippt weiter, bevor die Antwort kommt
    antwort("speichern", { text: "Gespeichert als SA-11.", auftraege: [draht(A1)] });
    expect(feld("Titel").value).toBe("Verlauf beschleunigen und mehr");
    expect(feld("Beschreibung").value).toBe("Der Verlauf soll schneller laden.");
    expect(screen.getByRole("status").textContent).toBe("Gespeichert als SA-11.");
  });

  it("kommt die Antwort erst nach der Frist, leert sie das unveränderte Formular trotzdem, und die Sperre eines zweiten Versuchs bleibt", async () => {
    stand();
    const ak = aktionen();
    const nutzer = userEvent.setup();
    render(<SelbstAuftraege aktionen={ak} />);
    await nutzer.type(feld("Titel"), "Verlauf beschleunigen");
    await nutzer.type(feld("Beschreibung"), "Der Verlauf soll schneller laden.");
    await nutzer.click(knopf("Speichern"));
    // Frist abgelaufen (lib/wamo.ts): die Knöpfe sind frei, die Antwort steht noch aus
    act(() =>
      wamo.set((s) => ({ ...s, selbstAuftraege: s.selbstAuftraege && { ...s.selbstAuftraege, wartet: null, verspaetet: "speichern" } })),
    );
    expect(knopf("Speichern").disabled).toBe(false);
    // die Person versucht es noch einmal, dann kommt die späte Antwort des ersten Versuchs
    await nutzer.click(knopf("Speichern"));
    expect(ak.speichern).toHaveBeenCalledTimes(2);
    antwort("speichern", { text: "Gespeichert als SA-11.", auftraege: [draht(A1)] });
    expect(feld("Titel").value).toBe(""); // gespeichert ist gespeichert
    expect(wamo.get().selbstAuftraege?.wartet?.aktion).toBe("speichern"); // der zweite Versuch wartet weiter
    expect(knopf("Wird gespeichert …").disabled).toBe(true);
  });

  it("eine Antwort auf etwas anderes (Sprache) leert das Formular nicht und hebt die Sperre nicht auf", async () => {
    stand();
    const ak = aktionen();
    const nutzer = userEvent.setup();
    render(<SelbstAuftraege aktionen={ak} />);
    await nutzer.type(feld("Titel"), "Verlauf beschleunigen");
    await nutzer.type(feld("Beschreibung"), "Der Verlauf soll schneller laden.");
    await nutzer.click(knopf("Speichern"));
    antwort("verwerfen", { text: "SA-3 ist verworfen." }); // der Kern meldet etwas, das die Person per Sprache angestoßen hat
    expect(feld("Titel").value).toBe("Verlauf beschleunigen");
    expect(knopf("Wird gespeichert …").disabled).toBe(true);
  });

  it("wird das Senden abgelehnt (keine Verbindung, Status passt nicht), bleiben die Eingaben und nichts hängt", async () => {
    stand();
    const ak = aktionen(false);
    const nutzer = userEvent.setup();
    render(<SelbstAuftraege aktionen={ak} />);
    await nutzer.type(feld("Titel"), "Verlauf beschleunigen");
    await nutzer.type(feld("Beschreibung"), "Der Verlauf soll schneller laden.");
    await nutzer.click(knopf("Speichern"));
    expect(feld("Titel").value).toBe("Verlauf beschleunigen");
    expect(knopf("Speichern").disabled).toBe(false);
  });
});
