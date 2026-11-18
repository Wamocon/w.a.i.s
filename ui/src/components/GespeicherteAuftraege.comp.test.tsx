// Komponententest der gespeicherten Aufträge (components/GespeicherteAuftraege.tsx) und des Knopfs "Für später speichern" auf der Startkarte
// (components/Freigaben.tsx): beides nur, wenn der Kern die Liste geschickt hat; Laden und Löschen senden die Kennung, Löschen fragt einmal
// nach (Fokus auf Abbrechen, danach zurück); ohne Verbindung oder während eine Aktion wartet, ist alles gesperrt; eine gesendete Karte lässt
// sich nicht mehr speichern, und während des Speicherns warten Starten und Verwerfen mit.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Auftraege } from "@/components/Freigaben";
import { GespeicherteAuftraege } from "@/components/GespeicherteAuftraege";
import { ENTWUERFE_LEER, type EntwuerfeStand } from "@/lib/auftragEntwuerfe";
import { auftraegeNachStart } from "@/lib/auftragStart";
import type { Auftrag, AuftragEntwurf } from "@/lib/nachrichten";
import type { EntwurfAktionen } from "@/lib/useWamo";
import { resetWamo, wamo } from "@/lib/wamo";

const E1: AuftragEntwurf = {
  id: "11111111-2222-4333-8444-555555555555",
  titel: "Baue die Rezepte-App",
  projekt: "rezepte-app",
  art: "umsetzung",
  repo: "acme/rezepte-app",
  gespeichertMs: Date.UTC(2026, 10, 18, 9),
};
const A: Auftrag = { job: "j1", projekt: "rezepte-app", art: "Umsetzung", auftrag: "Baue die Rezepte-App", abnahme: [] };

function stand(extra: Partial<EntwuerfeStand> = {}, online = true) {
  wamo.set((s) => ({ ...s, presence: online ? "idle" : "offline", entwuerfe: { ...ENTWUERFE_LEER, liste: [E1], ...extra } }));
}

function aktionen(): EntwurfAktionen {
  return { speichern: vi.fn(() => true), laden: vi.fn(() => true), loeschen: vi.fn(() => true) };
}

const knopf = (name: string | RegExp) => screen.getByRole("button", { name }) as HTMLButtonElement;

describe("Gespeicherte Aufträge", () => {
  beforeEach(() => resetWamo());

  it("ohne Antwort des Kerns gibt es weder Liste noch Knopf auf der Karte", () => {
    wamo.set((s) => ({ ...s, presence: "idle", auftraege: [A] }));
    const ak = aktionen();
    render(
      <>
        <Auftraege onDecide={() => true} onSpeichern={ak.speichern} />
        <GespeicherteAuftraege aktionen={ak} />
      </>,
    );
    expect(screen.queryByRole("heading", { name: "Gespeicherte Aufträge" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Für später speichern" })).toBeNull();
  });

  it("zeigt Titel, Angaben und Datum und lädt mit der Kennung", () => {
    stand();
    const ak = aktionen();
    render(<GespeicherteAuftraege aktionen={ak} />);
    expect(screen.getByRole("heading", { name: "Gespeicherte Aufträge" })).toBeTruthy();
    expect(screen.getByText("Baue die Rezepte-App")).toBeTruthy();
    expect(screen.getByText(/rezepte-app · umsetzung · acme\/rezepte-app/).textContent).toMatch(/gespeichert am 18\.11\.2026/);
    fireEvent.click(knopf("Laden: Baue die Rezepte-App"));
    expect(ak.laden).toHaveBeenCalledWith(E1.id);
    expect(screen.getByText(/1 von 50 gespeichert/)).toBeTruthy();
  });

  it("Löschen fragt einmal nach: Fokus auf Abbrechen, Abbrechen sendet nichts und gibt den Fokus zurück", () => {
    stand();
    const ak = aktionen();
    render(<GespeicherteAuftraege aktionen={ak} />);
    fireEvent.click(knopf("Löschen: Baue die Rezepte-App"));
    expect(screen.getByRole("group", { name: "Löschen bestätigen: Baue die Rezepte-App" })).toBeTruthy();
    expect(document.activeElement).toBe(knopf("Abbrechen: Baue die Rezepte-App"));
    fireEvent.click(knopf("Abbrechen: Baue die Rezepte-App"));
    expect(ak.loeschen).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(knopf("Löschen: Baue die Rezepte-App"));
    fireEvent.click(knopf("Löschen: Baue die Rezepte-App"));
    fireEvent.click(knopf("Endgültig löschen: Baue die Rezepte-App"));
    expect(ak.loeschen).toHaveBeenCalledWith(E1.id);
    expect(screen.queryByText("Wirklich löschen?")).toBeNull();
  });

  it("ohne Verbindung und während eine Aktion wartet, sind Laden und Löschen gesperrt", () => {
    stand({}, false);
    const { unmount } = render(<GespeicherteAuftraege aktionen={aktionen()} />);
    expect(knopf(/^Laden/).disabled).toBe(true);
    unmount();
    stand({ wartet: { aktion: "laden", kennung: E1.id, n: 1 } });
    render(<GespeicherteAuftraege aktionen={aktionen()} />);
    expect(knopf(/^Laden/).disabled).toBe(true);
    expect(knopf(/^Löschen/).disabled).toBe(true);
  });

  it("leere Liste mit Hinweis, die letzte Meldung des Kerns steht sichtbar da (angesagt wird sie über die Ansage der Seite)", () => {
    stand({ liste: [], meldung: { n: 1, ok: false, aktion: "laden", text: "Dieser gespeicherte Auftrag ist nicht mehr da." } });
    render(<GespeicherteAuftraege aktionen={aktionen()} />);
    expect(screen.getByText(/Noch nichts gespeichert/)).toBeTruthy();
    expect(screen.getByText("Dieser gespeicherte Auftrag ist nicht mehr da.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("im Labor (ohne Aktionen) bleibt die Liste weg, auch wenn ein Zustand da wäre", () => {
    stand();
    render(<GespeicherteAuftraege />);
    expect(screen.queryByRole("heading", { name: "Gespeicherte Aufträge" })).toBeNull();
  });
});

describe("Knopf Für später speichern auf der Startkarte", () => {
  beforeEach(() => resetWamo());

  it("vor dem Senden: der Knopf sendet die Karte", () => {
    stand();
    wamo.set((s) => ({ ...s, auftraege: [A] }));
    const ak = aktionen();
    render(<Auftraege onDecide={() => true} onSpeichern={ak.speichern} />);
    fireEvent.click(knopf("Für später speichern"));
    expect(ak.speichern).toHaveBeenCalledWith(A);
  });

  it("nach dem Klick auf Starten ist Speichern gesperrt", () => {
    stand();
    wamo.set((s) => ({ ...s, auftraege: auftraegeNachStart([A], "j1", 0) }));
    render(<Auftraege onDecide={() => true} onSpeichern={aktionen().speichern} />);
    expect(knopf("Für später speichern").disabled).toBe(true);
  });

  it("während diese Karte gespeichert wird, warten Starten und Verwerfen mit, und die Überschrift hält den Fokus", () => {
    stand({ wartet: { aktion: "speichern", kennung: "j1", n: 1 } });
    wamo.set((s) => ({ ...s, auftraege: [A, { ...A, job: "j2", art: "Analyse" }] }));
    render(<Auftraege onDecide={() => true} onSpeichern={aktionen().speichern} />);
    expect(knopf("Wird gespeichert …").disabled).toBe(true);
    const starten = screen.getAllByRole("button", { name: "Starten" }) as HTMLButtonElement[];
    expect(starten.map((b) => b.disabled)).toEqual([true, false]); // nur die Karte, die gespeichert wird
    const verwerfen = screen.getAllByRole("button", { name: "Verwerfen" }) as HTMLButtonElement[];
    expect(verwerfen.map((b) => b.disabled)).toEqual([true, false]);
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Umsetzung" }));
    const speichern = screen.getAllByRole("button", { name: /speicher/ }) as HTMLButtonElement[];
    expect(speichern.every((b) => b.disabled)).toBe(true); // während einer Aktion keine zweite
  });

  it("ohne onSpeichern (Labor, Vorschau) gibt es den Knopf nicht", () => {
    stand();
    wamo.set((s) => ({ ...s, auftraege: [A] }));
    render(<Auftraege onDecide={() => true} />);
    expect(screen.queryByRole("button", { name: "Für später speichern" })).toBeNull();
  });
});
