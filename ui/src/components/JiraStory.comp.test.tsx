// Komponententest für Jira-Stories (components/JiraStory.tsx, components/Canvas.tsx, components/Freigaben.tsx): Der Knopf "Als User Story in
// Jira" steht nur an eigenen, gespeicherten Dokumenten, wenn der Kern Stories anbietet, und fragt nur die Freigabekarte an. Die Karte mit Job
// "jira" zeigt jede Zeile; das Ergebnis zeigt den Schlüssel mit einem Verweis, der in einem neuen Tab ohne Rückgriff auf die Seite öffnet.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CanvasBereich, type CanvasItem } from "@/components/Canvas";
import { Freigaben } from "@/components/Freigaben";
import { JiraErgebnisHinweis } from "@/components/JiraStory";
import { applyServerMessage, resetWamo, wamo, type Approval } from "@/lib/wamo";

const ID = "11111111-2222-4333-8444-555555555555";
const DOKUMENT: CanvasItem = { id: ID, kind: "dokument", title: "Login per Stimme", text: "# Ziel\nAls Admin" };
const KNOPF = { name: "„Login per Stimme“ als User Story in Jira anlegen (mit Freigabekarte)" };

function zeige(item: CanvasItem, { jira = true, online = true } = {}) {
  wamo.set((s) => ({
    ...s,
    presence: online ? "listening" : "offline",
    canvas: [item],
    jira: { ...s.jira, status: jira ? { projekte: ["WMCNL"], standard: "WMCNL" } : null },
  }));
  const anfragen = vi.fn(() => true);
  render(<CanvasBereich jiraStory={anfragen} />);
  return anfragen;
}

describe("Knopf am Canvas", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetWamo();
  });
  afterEach(() => {
    vi.useRealTimers();
    resetWamo();
  });

  it("fragt für ein eigenes Dokument die Freigabekarte an", () => {
    const anfragen = zeige(DOKUMENT);
    fireEvent.click(screen.getByRole("button", KNOPF));
    expect(anfragen).toHaveBeenCalledWith(ID);
    expect(screen.getByText("Freigabekarte wird vorbereitet")).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(6000);
    });
    expect(screen.queryByText("Freigabekarte wird vorbereitet")).toBeNull();
  });

  it("sagt es, wenn der Klick nicht gesendet wurde", () => {
    wamo.set((s) => ({ ...s, presence: "listening", canvas: [DOKUMENT], jira: { ...s.jira, status: { projekte: ["WMCNL"], standard: "WMCNL" } } }));
    render(<CanvasBereich jiraStory={() => false} />);
    fireEvent.click(screen.getByRole("button", KNOPF));
    expect(screen.getByText("Nicht gesendet, keine Verbindung")).toBeTruthy();
  });

  it.each([
    ["ohne Angebot des Kerns", DOKUMENT, { jira: false }],
    ["ohne Verbindung", DOKUMENT, { online: false }],
    ["bei einer Tabelle", { id: ID, kind: "tabelle", title: "Liste", columns: ["a"], rows: [["b"]] } as CanvasItem, {}],
    ["bei Code", { id: ID, kind: "code", title: "SQL", text: "select 1" } as CanvasItem, {}],
    ["ohne gespeicherte Kennung", { ...DOKUMENT, id: null }, {}],
    ["bei geteilter Arbeit", { ...DOKUMENT, geteilt: { von: "Anna", recht: "lesen" } } as CanvasItem, {}],
  ])("fehlt %s", (_name, item, optionen) => {
    zeige(item, optionen);
    expect(screen.queryByRole("button", KNOPF)).toBeNull();
  });

  it("fehlt ganz ohne Aktion (Vorschau ohne Kern)", () => {
    wamo.set((s) => ({ ...s, presence: "listening", canvas: [DOKUMENT], jira: { ...s.jira, status: { projekte: ["WMCNL"], standard: "WMCNL" } } }));
    render(<CanvasBereich />);
    expect(screen.queryByRole("button", KNOPF)).toBeNull();
  });
});

describe("Karte und Ergebnis", () => {
  beforeEach(() => resetWamo());
  afterEach(() => resetWamo());

  it("die Karte mit Job jira zeigt Überschrift, Hinweis und jede Zeile", () => {
    const detail = ["Typ: Story", "Epic: keins", "Titel: Login per Stimme", "Beschreibung:", "> Als Admin", "Akzeptanzkriterien: (keine)"].join("\n");
    const karte: Approval = {
      job: "jira",
      projekt: "",
      id: "0123456789abcdef0123456789abcdef",
      grund: "Jira-Story anlegen",
      detail,
      von: "Niko",
      ziel: "Jira, Projekt WMCNL (WMC Next Level)",
    };
    wamo.set((s) => ({ ...s, approvals: [karte] }));
    const onDecide = vi.fn(() => true);
    render(<Freigaben onDecide={onDecide} />);
    expect(screen.getByText("Jira-Story freigeben", { selector: ".eyebrow" })).toBeTruthy();
    expect(screen.getByText("Du entscheidest, nicht W.A.I.S. Angelegt wird genau, was hier steht.")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Was genau ausgeführt wird" }).textContent).toBe(detail);
    fireEvent.click(screen.getByRole("button", { name: "Freigeben" }));
    expect(onDecide).toHaveBeenCalledWith(expect.objectContaining({ job: "jira", id: karte.id }), true);
  });

  it("zeigt den Schlüssel mit Verweis in einem neuen Tab und lässt sich schließen", () => {
    applyServerMessage({
      type: "jira_ergebnis",
      ok: true,
      schluessel: "WMCNL-123",
      link: "https://wamocon.atlassian.net/browse/WMCNL-123",
      text: "Angelegt als WMCNL-123.",
    });
    render(<JiraErgebnisHinweis />);
    expect(screen.getByText("Angelegt als WMCNL-123.")).toBeTruthy();
    const verweis = screen.getByRole("link", { name: "WMCNL-123 in Jira öffnen" });
    expect(verweis.getAttribute("href")).toBe("https://wamocon.atlassian.net/browse/WMCNL-123");
    expect(verweis.getAttribute("target")).toBe("_blank");
    expect(verweis.getAttribute("rel")).toBe("noopener noreferrer");
    fireEvent.click(screen.getByRole("button", { name: "Hinweis zu Jira schließen" }));
    expect(screen.queryByText("Angelegt als WMCNL-123.")).toBeNull();
  });

  it("ein Fehler steht ohne Verweis da", () => {
    applyServerMessage({ type: "jira_ergebnis", ok: false, text: "Kein eigenes Canvas-Dokument gefunden." });
    render(<JiraErgebnisHinweis />);
    expect(screen.getByText("Kein eigenes Canvas-Dokument gefunden.")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("jira_status schaltet den Knopf frei", () => {
    applyServerMessage({ type: "jira_status", projekte: ["WMCNL"], standard: "WMCNL" });
    expect(wamo.get().jira.status).toEqual({ projekte: ["WMCNL"], standard: "WMCNL" });
  });
});
