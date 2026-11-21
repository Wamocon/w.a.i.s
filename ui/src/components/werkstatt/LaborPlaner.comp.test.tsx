// Komponententest des Labor-Planers der Werkstatt: Termin und Fristen, Plätze, Checkliste, Stand der Laborprofile.
// Der Dienst (lib/werkstattApi.ts) ist durch Attrappen ersetzt.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  WerkstattFehler,
  checklisteLaden,
  checklistePunktAnlegen,
  checklisteUmschalten,
  laborStandLaden,
  plaetzeLaden,
  plaetzeSpeichern,
  terminAnlegen,
  terminAendern,
  terminLoeschen,
  termineLaden,
} from "@/lib/werkstattApi";
import { fehlerBild } from "@/lib/werkstattFehler";
import { LaborPlaner } from "./LaborPlaner";

vi.mock("@/lib/werkstattApi", async (original) => {
  const echt = await original<typeof import("@/lib/werkstattApi")>();
  return {
    ...echt,
    termineLaden: vi.fn(),
    terminAnlegen: vi.fn(),
    terminAendern: vi.fn(),
    terminLoeschen: vi.fn(),
    plaetzeLaden: vi.fn(),
    plaetzeSpeichern: vi.fn(),
    checklisteLaden: vi.fn(),
    checklistePunktAnlegen: vi.fn(),
    checklisteUmschalten: vi.fn(),
    laborStandLaden: vi.fn(),
  };
});

const TERMIN = { id: "t1", tag: "2099-12-05", beginn: "09:00", ende: "17:00", einwilligungVersion: 1, status: "entwurf" as const, aufbewahrungBis: "2099-12-18" };

beforeEach(() => {
  vi.mocked(termineLaden).mockResolvedValue([TERMIN]);
  vi.mocked(plaetzeLaden).mockResolvedValue([{ platz: 1, zweck: "besucher", kennung: "labor-01", gast: "Gast 1" }]);
  vi.mocked(checklisteLaden).mockResolvedValue([
    { nr: 1, titel: "Zertifikat prüfen", quelle: "Runbook 9", faellig: "2000-01-01", erledigt: false },
    { nr: 2, titel: "Karten drucken", quelle: null, faellig: null, erledigt: true },
  ]);
  vi.mocked(laborStandLaden).mockResolvedValue([
    { kennung: null, art: "platz", platz: 1, aktiv: false, zeilen: 12 },
    { kennung: null, art: "schaufenster", platz: null, aktiv: true, zeilen: null },
  ]);
  vi.mocked(terminAnlegen).mockResolvedValue({ termin: { ...TERMIN, id: "t2" } });
  vi.mocked(terminAendern).mockResolvedValue({ termin: TERMIN });
  vi.mocked(terminLoeschen).mockResolvedValue(true);
  vi.mocked(plaetzeSpeichern).mockResolvedValue(true);
  vi.mocked(checklisteUmschalten).mockResolvedValue(true);
  vi.mocked(checklistePunktAnlegen).mockResolvedValue(true);
});

describe("Termin und Fristen", () => {
  it("zeigt den Termin mit den berechneten Fristen und dem Stand der Laborprofile (nur lesend)", async () => {
    render(<LaborPlaner />);
    expect(await screen.findByLabelText("Labortag")).toHaveProperty("value", "2099-12-05");
    expect(screen.getByText("Fr 18.12.2099")).toBeTruthy();
    expect(screen.getByText("Sa 19.12.2099")).toBeTruthy();
    expect(screen.getByText("Mo 07.12.2099")).toBeTruthy();
    const stand = await screen.findByRole("table", { name: "Laborprofile, nur lesend" });
    expect(within(stand).getByText("gesperrt")).toBeTruthy();
    expect(within(stand).getByText("freigeschaltet")).toBeTruthy();
    expect(screen.getByText(/laufen bis zur nächsten Stufe weiter über die Skripte/)).toBeTruthy();
  });

  it("ein neuer Labortag verschiebt die Fristen mit, bis die Aufbewahrung von Hand gewählt wird", async () => {
    const user = userEvent.setup();
    render(<LaborPlaner />);
    const tag = await screen.findByLabelText("Labortag");
    await user.clear(tag);
    await user.type(tag, "2099-12-12");
    expect(screen.getByLabelText("Aufbewahrung bis")).toHaveProperty("value", "2099-12-25");
    expect(screen.getByText("Fr 25.12.2099")).toBeTruthy();
    const bis = screen.getByLabelText("Aufbewahrung bis");
    await user.clear(bis);
    await user.type(bis, "2099-12-20");
    await user.clear(tag);
    await user.type(tag, "2099-12-13");
    expect(screen.getByLabelText("Aufbewahrung bis")).toHaveProperty("value", "2099-12-20");
  });

  it("speichert den Termin mit den Namen der Eingabe und meldet es", async () => {
    const user = userEvent.setup();
    render(<LaborPlaner />);
    await screen.findByLabelText("Labortag");
    await user.click(screen.getByRole("button", { name: "Termin speichern" }));
    expect(terminAendern).toHaveBeenCalledWith("t1", { tag: "2099-12-05", beginn: "09:00", ende: "17:00", einwilligungVersion: 1, status: "entwurf", aufbewahrungBis: "2099-12-18" });
    expect(await screen.findByText("Der Termin ist gespeichert.")).toBeTruthy();
  });

  it("eine Eingabe gegen die Regeln geht nicht raus und nennt den Grund", async () => {
    const user = userEvent.setup();
    render(<LaborPlaner />);
    await screen.findByLabelText("Labortag");
    const bis = screen.getByLabelText("Aufbewahrung bis");
    await user.clear(bis);
    await user.type(bis, "2100-02-01");
    await user.click(screen.getByRole("button", { name: "Termin speichern" }));
    const alarm = await screen.findByRole("alert");
    expect(alarm.textContent).toMatch(/höchstens 14 Tage danach/);
    expect(terminAendern).not.toHaveBeenCalled();
    expect(bis.getAttribute("aria-invalid")).toBe("true");
  });

  it("Neuer Termin legt an; ein Fehler des Dienstes erscheint als Satz", async () => {
    const user = userEvent.setup();
    vi.mocked(termineLaden).mockResolvedValue([]);
    vi.mocked(terminAnlegen).mockRejectedValueOnce(new WerkstattFehler(fehlerBild(409, "konflikt", "Für diesen Tag gibt es schon einen Termin.")));
    render(<LaborPlaner />);
    const tag = await screen.findByLabelText("Labortag");
    expect(screen.getByText(/Lege zuerst den Termin an/)).toBeTruthy();
    await user.type(tag, "2099-12-05");
    await user.click(screen.getByRole("button", { name: "Termin anlegen" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/Für diesen Tag gibt es schon einen Termin/);
    await user.click(screen.getByRole("button", { name: "Termin anlegen" }));
    expect(terminAnlegen).toHaveBeenLastCalledWith({ tag: "2099-12-05", beginn: null, ende: null, einwilligungVersion: 1, status: "entwurf", aufbewahrungBis: "2099-12-18" });
  });

  it("Löschen fragt erst nach und gilt nur für Entwürfe", async () => {
    const user = userEvent.setup();
    render(<LaborPlaner />);
    await screen.findByLabelText("Labortag");
    await user.click(screen.getByRole("button", { name: "Termin löschen …" }));
    expect(terminLoeschen).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Abbrechen" }));
    await user.click(screen.getByRole("button", { name: "Termin löschen …" }));
    await user.click(screen.getByRole("button", { name: "Ja, löschen" }));
    expect(terminLoeschen).toHaveBeenCalledWith("t1");
  });

  it("ein freigegebener Termin lässt sich nicht löschen", async () => {
    vi.mocked(termineLaden).mockResolvedValue([{ ...TERMIN, status: "freigegeben" }]);
    render(<LaborPlaner />);
    await screen.findByLabelText("Labortag");
    expect(screen.queryByRole("button", { name: "Termin löschen …" })).toBeNull();
  });
});

describe("Plätze", () => {
  it("zeigt 16 Plätze, Abnahme nur an 15 und 16, die Kennung kommt als Vorschlag", async () => {
    const user = userEvent.setup();
    render(<LaborPlaner />);
    const tabelle = await screen.findByRole("table", { name: "Plätze 1 bis 16" });
    expect(within(tabelle).getAllByRole("row")).toHaveLength(17);
    const platz3 = screen.getByLabelText("Zweck von Platz 3");
    expect(within(platz3).queryByRole("option", { name: "Abnahme" })).toBeNull();
    expect(within(screen.getByLabelText("Zweck von Platz 15")).getByRole("option", { name: "Abnahme" })).toBeTruthy();
    expect(screen.getByLabelText("Kennung von Platz 3")).toHaveProperty("disabled", true);
    await user.selectOptions(platz3, "reserve");
    expect(screen.getByLabelText("Kennung von Platz 3")).toHaveProperty("value", "labor-03");
  });

  it("speichert nur belegte Plätze und meldet Regelverstöße vorher", async () => {
    const user = userEvent.setup();
    render(<LaborPlaner />);
    await screen.findByRole("table", { name: "Plätze 1 bis 16" });
    await user.selectOptions(screen.getByLabelText("Zweck von Platz 2"), "reserve");
    await user.clear(screen.getByLabelText("Kennung von Platz 2"));
    await user.type(screen.getByLabelText("Kennung von Platz 2"), "labor-01");
    await user.click(screen.getByRole("button", { name: "Plätze speichern" }));
    expect((await screen.findAllByRole("alert")).some((a) => /schon an einem anderen Platz/.test(a.textContent ?? ""))).toBe(true);
    expect(plaetzeSpeichern).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText("Kennung von Platz 2"));
    await user.type(screen.getByLabelText("Kennung von Platz 2"), "labor-02");
    await user.click(screen.getByRole("button", { name: "Plätze speichern" }));
    expect(plaetzeSpeichern).toHaveBeenCalledWith("t1", [
      { platz: 1, zweck: "besucher", kennung: "labor-01", gast: "Gast 1" },
      { platz: 2, zweck: "reserve", kennung: "labor-02", gast: null },
    ]);
    expect(await screen.findByText("Die Plätze sind gespeichert.")).toBeTruthy();
  });
});

describe("Checkliste", () => {
  it("zeigt Fortschritt, Fälligkeit als Wort und Quelle", async () => {
    render(<LaborPlaner />);
    expect(await screen.findByRole("img", { name: "1 von 2 Punkten erledigt" })).toBeTruthy();
    expect(screen.getByText("1 von 2 erledigt")).toBeTruthy();
    expect(screen.getByText("Runbook 9")).toBeTruthy();
    expect(screen.getByText(/überfällig seit Sa 01\.01\.2000/)).toBeTruthy();
    expect(screen.getByText("erledigt")).toBeTruthy();
  });

  it("Abhaken schreibt sofort, Anlegen prüft den Titel", async () => {
    const user = userEvent.setup();
    render(<LaborPlaner />);
    await user.click(await screen.findByRole("checkbox", { name: /Zertifikat prüfen/ }));
    expect(checklisteUmschalten).toHaveBeenCalledWith("t1", 1, true);
    await user.click(screen.getByRole("checkbox", { name: /Karten drucken/ }));
    expect(checklisteUmschalten).toHaveBeenLastCalledWith("t1", 2, false);
    await user.click(screen.getByRole("button", { name: "Punkt anlegen" }));
    expect(await screen.findByText("Der Titel fehlt.")).toBeTruthy();
    expect(checklistePunktAnlegen).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("Neuer Punkt"), "Generalprobe");
    await user.click(screen.getByRole("button", { name: "Punkt anlegen" }));
    expect(checklistePunktAnlegen).toHaveBeenCalledWith("t1", { titel: "Generalprobe", quelle: null, faellig: null });
  });
});
