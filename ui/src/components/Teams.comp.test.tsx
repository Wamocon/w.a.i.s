// Komponententest: Teams-Nachricht aus dem Canvas ("Als Teams-Nachricht" im Kopf, components/TeamsFormular.tsx).
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CanvasBereich } from "@/components/Canvas";
import type { Betrieb } from "@/lib/nachrichten";
import type { TeamsDaten } from "@/lib/teams";
import { applyServerMessage, resetWamo, wamo } from "@/lib/wamo";

const ID = "11111111-1111-4111-8111-111111111111";
const BETRIEB: Betrieb = { modus: "buero", modelle: {}, pc: "verbunden", pcSteuerung: "an", teams: true };
const DOKUMENT = { id: ID, kind: "dokument", title: "Stand Angebot", text: "# Stand\n**Fertig** ist das Angebot." };

function zustand(item: Record<string, unknown>, betrieb: Betrieb | null = BETRIEB) {
  wamo.set((s) => ({ ...s, canvas: [item as never], betrieb }));
}

function teamsAktionen(ergebnis = true) {
  return { vorbereiten: vi.fn<(d: TeamsDaten) => boolean>(() => ergebnis) };
}

describe("Canvas, Als Teams-Nachricht", () => {
  beforeEach(() => resetWamo());
  afterEach(() => resetWamo());

  it("schlägt den Inhalt des Canvas als Klartext vor und schickt die Angaben zur Freigabe", () => {
    const teams = teamsAktionen();
    zustand(DOKUMENT);
    render(<CanvasBereich teams={teams} />);
    fireEvent.click(screen.getByRole("button", { name: "Als Teams-Nachricht" }));
    const text = screen.getByLabelText("Text") as HTMLTextAreaElement;
    expect(text.value).toBe("Stand\nFertig ist das Angebot.");
    expect(screen.getByText(/W.A.I.S. sendet nie/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("An"), { target: { value: "max@firma.example; Anna Schmidt" } });
    fireEvent.change(screen.getByLabelText("Gruppenname (nur bei mehreren)"), { target: { value: "Angebot" } });
    fireEvent.click(screen.getByRole("button", { name: "Zur Freigabe vorbereiten" }));
    expect(teams.vorbereiten).toHaveBeenCalledExactlyOnceWith({
      an: ["max@firma.example", "Anna Schmidt"],
      gruppenname: "Angebot",
      text: "Stand\nFertig ist das Angebot.",
    });
    const knopf = screen.getByRole("button", { name: "Zur Freigabe vorbereiten" }) as HTMLButtonElement;
    expect(knopf.disabled).toBe(true); // bis die Antwort kommt: kein zweites Mal
    act(() => applyServerMessage({ type: "teams_antwort", ok: true }));
    expect(screen.queryByLabelText("An")).toBeNull(); // Karte liegt bereit, Formular zu
  });

  it("zeigt die Länge, Fehler aus Formular und Kern und schickt Ungültiges nicht", () => {
    const teams = teamsAktionen();
    zustand(DOKUMENT);
    render(<CanvasBereich teams={teams} />);
    fireEvent.click(screen.getByRole("button", { name: "Als Teams-Nachricht" }));
    fireEvent.click(screen.getByRole("button", { name: "Zur Freigabe vorbereiten" }));
    expect(screen.getByRole("alert").textContent).toMatch(/Empfänger/);
    fireEvent.change(screen.getByLabelText("An"), { target: { value: "max@firma.example" } });
    fireEvent.change(screen.getByLabelText("Text"), { target: { value: "ä".repeat(1001) } });
    expect(screen.getByText("1001 von 1000 Zeichen")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Zur Freigabe vorbereiten" }));
    expect(screen.getByRole("alert").textContent).toMatch(/kürzen/);
    expect(teams.vorbereiten).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Text"), { target: { value: "Hallo" } });
    fireEvent.click(screen.getByRole("button", { name: "Zur Freigabe vorbereiten" }));
    act(() => applyServerMessage({ type: "teams_antwort", ok: false, grund: "Nur interne Adressen." }));
    expect(screen.getByRole("alert").textContent).toBe("Nur interne Adressen.");
  });

  it("gibt es nur mit betrieb.teams und nur für eigene, gespeicherte Elemente", () => {
    const teams = teamsAktionen();
    zustand(DOKUMENT, { ...BETRIEB, teams: undefined });
    const { unmount } = render(<CanvasBereich teams={teams} />);
    expect(screen.queryByRole("button", { name: "Als Teams-Nachricht" })).toBeNull();
    unmount();
    zustand({ ...DOKUMENT, geteilt: { von: "Anna", recht: "lesen" } });
    render(<CanvasBereich teams={teams} />);
    expect(screen.queryByRole("button", { name: "Als Teams-Nachricht" })).toBeNull();
  });
});
