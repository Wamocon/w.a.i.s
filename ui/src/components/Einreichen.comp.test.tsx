// Komponententest der Karte "Einreichen" (components/Freigaben.tsx, lib/einreichen.ts; Plan C, C.6): Kästchen der markierten Pfade, Einreichen
// erst nach allen Bestätigungen, Sperre mit Gründen, Verwerfen, Pull Request nachholen, Konto auf der Startkarte.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Auftraege, Freigaben } from "@/components/Freigaben";
import { pruefeEinreichen, type Einreichen } from "@/lib/einreichen";
import { resetWamo, wamo, type Approval } from "@/lib/wamo";

const roh = (teil: Record<string, unknown> = {}) => ({
  status: "bereit",
  repo: "acme/testrepo",
  privat: true,
  zweig: "wamo/ab12cd34ef56ab12",
  konto: "person-eins",
  commit_id: "a".repeat(40),
  tree_id: "b".repeat(40),
  dateien: 2,
  plus: 10,
  minus: 3,
  markiert: ["package.json", "Dockerfile"],
  pfade: ["package.json", "Dockerfile", "src/app.ts"],
  weitere: 0,
  gesperrt: [],
  ungesichert: 0,
  lauf: "fertig",
  titel: "Rezepte anlegen",
  nachholen: false,
  ...teil,
});

function karte(teil: Record<string, unknown> = {}): Approval {
  const einreichen = pruefeEinreichen(roh(teil)) as Einreichen;
  return { job: "ab12cd34ef56ab12", projekt: "kern-testrepo", id: "einreichen", grund: "Änderung als Pull Request einreichen",
           detail: "Repo acme/testrepo", einreichen };
}

const knopf = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;

function aufbauen(a: Approval) {
  wamo.set((s) => ({ ...s, approvals: [a] }));
  const onEinreichen = vi.fn(() => true);
  const onDecide = vi.fn(() => true);
  render(<Freigaben onDecide={onDecide} onEinreichen={onEinreichen} />);
  return { onEinreichen, onDecide };
}

describe("Karte Einreichen", () => {
  beforeEach(() => resetWamo());

  it("Einreichen erst, wenn jede markierte Datei bestätigt ist", () => {
    const a = karte();
    const { onEinreichen, onDecide } = aufbauen(a);
    expect(screen.getByText("acme/testrepo (privat)")).toBeTruthy();
    expect(screen.getByText("wamo/ab12cd34ef56ab12")).toBeTruthy();
    expect(screen.getByText("2 Dateien, +10 -3")).toBeTruthy();
    expect(knopf("Einreichen").disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: "package.json" }));
    expect(knopf("Einreichen").disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: "Dockerfile" }));
    expect(knopf("Einreichen").disabled).toBe(false);
    fireEvent.click(knopf("Einreichen"));
    expect(onEinreichen).toHaveBeenCalledWith(a, "einreichen", ["package.json", "Dockerfile"]);
    expect(onDecide).not.toHaveBeenCalled();
  });

  it("Verwerfen ist gleichgewichtig und geht ohne Bestätigung", () => {
    const a = karte();
    const { onEinreichen } = aufbauen(a);
    expect(knopf("Verwerfen").disabled).toBe(false);
    fireEvent.click(knopf("Verwerfen"));
    expect(onEinreichen).toHaveBeenCalledWith(a, "verwerfen", []);
  });

  it("gesperrt: nur Verwerfen und die Gründe als Sätze", () => {
    aufbauen(karte({ status: "gesperrt", commit_id: null, tree_id: null, gesperrt: ["In einer geänderten Datei steht ein Schlüssel."] }));
    expect(screen.queryByRole("button", { name: "Einreichen" })).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByText("In einer geänderten Datei steht ein Schlüssel.")).toBeTruthy();
    expect(knopf("Verwerfen").disabled).toBe(false);
  });

  it("branch_gepusht: Pull Request nachholen, kein Verwerfen, Fehler des Kerns sichtbar", () => {
    const a = karte({ status: "branch_gepusht", nachholen: true, markiert: [], fehler: "GitHub hat das Einreichen nicht angenommen." });
    const { onEinreichen } = aufbauen(a);
    expect(screen.queryByRole("button", { name: "Verwerfen" })).toBeNull();
    expect(screen.getByText("GitHub hat das Einreichen nicht angenommen.")).toBeTruthy();
    fireEvent.click(knopf("Pull Request nachholen"));
    expect(onEinreichen).toHaveBeenCalledWith(a, "einreichen", []);
  });

  it("ohne Aktion (Labor, Vorschau) sind beide Knöpfe gesperrt", () => {
    wamo.set((s) => ({ ...s, approvals: [karte({ markiert: [] })] }));
    render(<Freigaben onDecide={vi.fn(() => true)} />);
    expect(knopf("Einreichen").disabled).toBe(true);
    expect(knopf("Verwerfen").disabled).toBe(true);
  });

  it("die Startkarte nennt den eigenen GitHub-Weg mit Konto", () => {
    wamo.set((s) => ({ ...s, auftraege: [{ job: "j1", projekt: "kern-x", art: "Umsetzung", auftrag: "Baue", abnahme: [], repo: "acme/x",
                                         github: { konto: "person-eins" } }] }));
    render(<Auftraege onDecide={vi.fn(() => true)} />);
    expect(screen.getByText("mit deinem GitHub-Token, Konto person-eins")).toBeTruthy();
  });
});
