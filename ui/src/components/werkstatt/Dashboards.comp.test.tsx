// Komponententest der Dashboards und Protokolle der Werkstatt: Zahlen, Diagramme mit Tabelle, Zeitraum, Filter, Fehler.
// Der Dienst (lib/werkstattApi.ts) ist durch Attrappen ersetzt.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WerkstattFehler, aktionenLaden, betriebLaden, latenzLaden, protokolleLaden, sitzungenLaden } from "@/lib/werkstattApi";
import { eigenerFehler } from "@/lib/werkstattFehler";
import { Dashboards } from "./Dashboards";
import { Protokolle } from "./Protokolle";

vi.mock("@/lib/werkstattApi", async (original) => {
  const echt = await original<typeof import("@/lib/werkstattApi")>();
  return { ...echt, betriebLaden: vi.fn(), sitzungenLaden: vi.fn(), latenzLaden: vi.fn(), aktionenLaden: vi.fn(), protokolleLaden: vi.fn() };
});

const BETRIEB = {
  zeit: "2026-11-20T10:00:00Z",
  alterS: 30,
  kern: [
    { slot: "a", release: "v0.7.1-abc", aktiv: true },
    { slot: "b", release: "v0.7.0-def", aktiv: false },
  ],
  oberflaeche: { farbe: "grün", version: "0.7.1" },
  installer: { version: "0.7.1" },
  kanal: { zustand: "zu" },
  laborDienst: { zustand: "ok" },
};
const TAGE = [
  { tag: "2026-11-18", anzahl: 12, dauerP50S: 90, dauerP95S: 300, offen: 0 },
  { tag: "2026-11-19", anzahl: 31, dauerP50S: 120, dauerP95S: 400, offen: 1 },
];
const LATENZ = [
  { tag: "2026-11-18", zuege: 100, p50Ms: 1700, p95Ms: 3100 },
  { tag: "2026-11-19", zuege: 140, p50Ms: 1750, p95Ms: 3300 },
];

describe("Dashboards", () => {
  beforeEach(() => {
    vi.mocked(betriebLaden).mockResolvedValue(BETRIEB);
    vi.mocked(sitzungenLaden).mockResolvedValue(TAGE);
    vi.mocked(latenzLaden).mockResolvedValue(LATENZ);
    vi.mocked(aktionenLaden).mockResolvedValue([{ tool: "werkstatt_karten_veroeffentlichen", status: "done", anzahl: 2 }]);
  });

  it("zeigt den Betrieb mit Wort und Form, den Stand des Sammlers und die Aktionen", async () => {
    render(<Dashboards />);
    const betrieb = await screen.findByRole("heading", { name: "Betrieb jetzt" });
    const karte = within(betrieb.closest("section") as HTMLElement);
    expect(await karte.findByText(/v0\.7\.1-abc/)).toBeTruthy();
    expect(karte.getAllByText(/aktiv$/)).toHaveLength(2); // a: aktiv, b: nicht aktiv
    // der zweite Slot steht als eigene Zeile, nicht aktiv
    expect(karte.getByText("Kern, Slot b")).toBeTruthy();
    expect(karte.getByText(/v0\.7\.0-def/)).toBeTruthy();
    expect(karte.getByText(/nicht aktiv/)).toBeTruthy();
    expect(karte.getByText("zu")).toBeTruthy();
    expect(karte.getByText("in Ordnung")).toBeTruthy();
    expect(karte.getByText("Stand vor 30 Sekunden, der Sammler schreibt jede Minute.")).toBeTruthy();
    const tabelle = await screen.findByRole("table", { name: "Aktionen im Zeitraum, insgesamt 2" });
    expect(within(tabelle).getByText("werkstatt_karten_veroeffentlichen")).toBeTruthy();
    expect(within(tabelle).getByText("erledigt")).toBeTruthy(); // done als deutsches Wort
  });

  it("ein alter Stand des Sammlers wird als Warnung gemeldet", async () => {
    vi.mocked(betriebLaden).mockResolvedValue({ ...BETRIEB, alterS: 900 });
    render(<Dashboards />);
    expect((await screen.findByText(/Der Sammler hat zuletzt vor 15 Minuten gemeldet/)).getAttribute("role")).toBe("alert");
  });

  it("die Diagramme haben eine Beschreibung und eine Tabelle mit denselben Zahlen", async () => {
    render(<Dashboards />);
    const sitzungen = await screen.findByRole("img", { name: /Sitzungen je Tag, 2 Tage, am letzten Tag 31/ });
    expect(sitzungen.tagName.toLowerCase()).toBe("svg");
    expect(await screen.findByRole("img", { name: /p50 1750 ms, p95 3300 ms/ })).toBeTruthy();
    const tabelle = screen.getByRole("table", { name: "Sitzungen je Tag", hidden: true });
    expect(within(tabelle).getAllByRole("row", { hidden: true })).toHaveLength(3);
    expect(within(tabelle).getByText("2 min", { exact: false, selector: "td" })).toBeTruthy();
    expect(screen.getByText(/Grenze des Lasttests, 3500 ms/)).toBeTruthy();
  });

  it("der Zeitraum wechselt für alle Abfragen, Standard 14 Tage", async () => {
    const user = userEvent.setup();
    render(<Dashboards />);
    await screen.findByText("Betrieb jetzt");
    expect(sitzungenLaden).toHaveBeenLastCalledWith(14, expect.anything());
    expect(screen.getByRole("button", { name: "14 Tage" }).getAttribute("aria-pressed")).toBe("true");
    await user.click(screen.getByRole("button", { name: "30 Tage" }));
    expect(sitzungenLaden).toHaveBeenLastCalledWith(30, expect.anything());
    expect(latenzLaden).toHaveBeenLastCalledWith(30, expect.anything());
    expect(aktionenLaden).toHaveBeenLastCalledWith(30, expect.anything());
    expect(screen.getByRole("button", { name: "30 Tage" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "14 Tage" }).getAttribute("aria-pressed")).toBe("false");
  });

  it("Fehler einer Abfrage stehen an ihrer Karte, die übrigen bleiben; Aktualisieren lädt alles neu", async () => {
    vi.mocked(latenzLaden).mockRejectedValueOnce(new WerkstattFehler(eigenerFehler("zeit")));
    const user = userEvent.setup();
    render(<Dashboards />);
    const alarm = await screen.findByRole("alert");
    expect(alarm.textContent).toMatch(/nicht rechtzeitig geantwortet/);
    expect(await screen.findByRole("img", { name: /Sitzungen je Tag/ })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Aktualisieren" }));
    expect(await screen.findByRole("img", { name: /p50 1750 ms/ })).toBeTruthy();
    expect(betriebLaden).toHaveBeenCalledTimes(2);
  });

  it("ohne Daten steht ein Satz statt eines leeren Bildes", async () => {
    vi.mocked(sitzungenLaden).mockResolvedValue([]);
    vi.mocked(latenzLaden).mockResolvedValue([]);
    vi.mocked(aktionenLaden).mockResolvedValue([]);
    render(<Dashboards />);
    expect(await screen.findByText("Für diesen Zeitraum gibt es noch keine Sitzungen.")).toBeTruthy();
    expect(screen.getByText("Für diesen Zeitraum gibt es noch keine Züge.")).toBeTruthy();
    expect(screen.getByText("In diesem Zeitraum gab es keine Aktionen.")).toBeTruthy();
  });
});

describe("Protokolle", () => {
  const ANTWORT = {
    marken: ["wamo-core", "wamo-ui"],
    zeilen: [
      { zeit: "2026-11-20T12:47:00", marke: "wamo-core", stufe: "info", code: "labor_stufe_ende", zahlen: "sitzungen 1" },
      { zeit: "2026-11-20T11:10:00", marke: "wamo-ui", stufe: "fehler", code: "farbe_fehler", zahlen: "" },
    ],
  };
  beforeEach(() => vi.mocked(protokolleLaden).mockResolvedValue(ANTWORT));

  it("zeigt Zeit, Quelle, Stufe als Wort mit Form, Code und Zahlen", async () => {
    render(<Protokolle />);
    const tabelle = await screen.findByRole("table", { name: /2 Einträge/ });
    const zeilen = within(tabelle).getAllByRole("row");
    expect(zeilen).toHaveLength(3);
    expect(within(zeilen[1]).getByText("20.11. 12:47")).toBeTruthy();
    expect(within(zeilen[1]).getByText("labor_stufe_ende")).toBeTruthy();
    expect(within(zeilen[1]).getByText("sitzungen 1")).toBeTruthy();
    expect(within(zeilen[2]).getByText("fehler")).toBeTruthy();
    expect(protokolleLaden).toHaveBeenLastCalledWith({ marke: "", stufe: "", stunden: 24 }, expect.anything());
  });

  it("die Filter gehen an den Dienst, die Quellen bleiben wählbar", async () => {
    const user = userEvent.setup();
    render(<Protokolle />);
    await screen.findByRole("table");
    await user.selectOptions(screen.getByLabelText("Quelle"), "wamo-ui");
    expect(protokolleLaden).toHaveBeenLastCalledWith({ marke: "wamo-ui", stufe: "", stunden: 24 }, expect.anything());
    vi.mocked(protokolleLaden).mockResolvedValue({ marken: [], zeilen: [ANTWORT.zeilen[1]] });
    await user.selectOptions(screen.getByLabelText("Stufe"), "fehler");
    await user.selectOptions(screen.getByLabelText("Zeitraum"), "6");
    expect(protokolleLaden).toHaveBeenLastCalledWith({ marke: "wamo-ui", stufe: "fehler", stunden: 6 }, expect.anything());
    // die andere Quelle bleibt wählbar, auch wenn die Antwort nur eine zeigt
    expect(within(screen.getByLabelText("Quelle")).getByRole("option", { name: "wamo-core" })).toBeTruthy();
  });

  it("ohne Treffer ein Satz, bei der Höchstmenge ein Hinweis, bei Fehlern Neu laden", async () => {
    const user = userEvent.setup();
    vi.mocked(protokolleLaden).mockResolvedValueOnce({ marken: [], zeilen: [] });
    render(<Protokolle />);
    expect(await screen.findByText("Keine Einträge für diesen Filter.")).toBeTruthy();
    const viele = Array.from({ length: 500 }, (_, i) => ({ zeit: "2026-11-20T10:00:00", marke: "m", stufe: "info", code: `c${i}`, zahlen: "" }));
    vi.mocked(protokolleLaden).mockResolvedValueOnce({ marken: [], zeilen: viele });
    await user.click(screen.getByRole("button", { name: "Aktualisieren" }));
    expect(await screen.findByRole("table", { name: /500 Einträge, das ist die Höchstmenge/ })).toBeTruthy();
    vi.mocked(protokolleLaden).mockRejectedValueOnce(new WerkstattFehler(eigenerFehler("netz")));
    await user.click(screen.getByRole("button", { name: "Aktualisieren" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/nicht erreichbar/);
  });
});
