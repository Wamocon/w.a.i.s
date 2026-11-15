// Komponententest des Canvas: Kopierknopf mit Bestätigungs-Chip (components/Canvas.tsx, lib/kopieren.ts), Überarbeitung an derselben
// Stelle und Meldung des offenen Reiters (lib/canvasWahl.ts).
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CanvasBereich } from "@/components/Canvas";
import { KOPIERT_MS } from "@/lib/kopieren";
import { applyServerMessage, resetWamo, wamo } from "@/lib/wamo";

const CODE = "select * from geraete;";

function codeImCanvas() {
  wamo.set((s) => ({ ...s, canvas: [{ kind: "code", title: "Abfrage", text: CODE, language: "sql" }] }));
}

/** Zwischenablage als Attrappe: Der Aufruf gelingt oder wird abgelehnt (zum Beispiel ohne Erlaubnis). */
function zwischenablage(ergebnis: "ok" | "abgelehnt") {
  const writeText = vi.fn(() => (ergebnis === "ok" ? Promise.resolve() : Promise.reject(new DOMException("verweigert", "NotAllowedError"))));
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  return writeText;
}

/** Die Live-Region des Chips: der einzige Bereich mit aria-live in der Kopfzeile des Codes. */
const chip = (container: HTMLElement) => container.querySelector<HTMLElement>('[aria-live="polite"]')!;

async function kopierenKlicken() {
  // Der Klick startet einen asynchronen Aufruf (writeText): act wartet, bis der Zustand gesetzt ist
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Kopieren" }));
  });
}

describe("Canvas, Kopierknopf", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetWamo();
    codeImCanvas();
  });
  afterEach(() => {
    vi.useRealTimers();
    resetWamo();
    Reflect.deleteProperty(navigator, "clipboard");
  });

  it("hat die Live-Region von Anfang an im Dokument und leer (sonst wird die erste Bestätigung überhört)", () => {
    const { container } = render(<CanvasBereich />);
    const live = chip(container);
    expect(live).not.toBeNull();
    expect(live.getAttribute("aria-live")).toBe("polite");
    expect(live.textContent).toBe("");
  });

  it("zeigt nach dem Kopieren den Chip Kopiert und hat den Text in die Zwischenablage gegeben", async () => {
    const writeText = zwischenablage("ok");
    const { container } = render(<CanvasBereich />);
    await kopierenKlicken();
    expect(writeText).toHaveBeenCalledExactlyOnceWith(CODE);
    expect(chip(container).textContent).toBe("Kopiert");
    expect(chip(container).getAttribute("aria-live")).toBe("polite");
  });

  it("blendet den Chip nach 1,5 Sekunden wieder aus, die Live-Region bleibt stehen", async () => {
    zwischenablage("ok");
    const { container } = render(<CanvasBereich />);
    const live = chip(container);
    await kopierenKlicken();
    act(() => {
      vi.advanceTimersByTime(KOPIERT_MS - 1);
    });
    expect(live.textContent).toBe("Kopiert");
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(live.textContent).toBe("");
    expect(chip(container)).toBe(live); // derselbe Knoten: nur der Text wechselt, die Region wird nicht neu eingefügt
  });

  it("belässt die Beschriftung des Knopfs auf Kopieren, vorher, während der Bestätigung und danach", async () => {
    zwischenablage("ok");
    render(<CanvasBereich />);
    const knopf = screen.getByRole("button", { name: "Kopieren" });
    expect(knopf.textContent).toBe("Kopieren");
    await kopierenKlicken();
    expect(screen.getByRole("button", { name: "Kopieren" })).toBe(knopf);
    expect(knopf.textContent).toBe("Kopieren");
    act(() => {
      vi.advanceTimersByTime(KOPIERT_MS);
    });
    expect(knopf.textContent).toBe("Kopieren");
  });

  it("meldet Nicht kopiert, wenn die Zwischenablage nicht erlaubt ist, und markiert den Chip als Fehler", async () => {
    zwischenablage("abgelehnt");
    const { container } = render(<CanvasBereich />);
    await kopierenKlicken();
    expect(chip(container).textContent).toBe("Nicht kopiert");
    expect(chip(container).getAttribute("data-art")).toBe("fehler");
    expect(screen.getByRole("button", { name: "Kopieren" }).textContent).toBe("Kopieren");
  });

  it("beginnt die 1,5 Sekunden bei einem zweiten Klick neu", async () => {
    zwischenablage("ok");
    const { container } = render(<CanvasBereich />);
    await kopierenKlicken();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    await kopierenKlicken();
    act(() => {
      vi.advanceTimersByTime(1000); // 2 s seit dem ersten, 1 s seit dem zweiten Klick
    });
    expect(chip(container).textContent).toBe("Kopiert");
    act(() => {
      vi.advanceTimersByTime(KOPIERT_MS - 1000);
    });
    expect(chip(container).textContent).toBe("");
  });

  it("lässt beim Schließen keinen Zeitgeber zurück", async () => {
    zwischenablage("ok");
    const { unmount } = render(<CanvasBereich />);
    await kopierenKlicken();
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});

// ---------- Überarbeiten im offenen Reiter (Befund 15.11.2026) und Meldung des offenen Reiters an den Kern ----------
const A = "aaaaaaaa-0000-4000-8000-000000000001";
const B = "aaaaaaaa-0000-4000-8000-000000000002";
const C = "aaaaaaaa-0000-4000-8000-000000000003";
const A2 = "aaaaaaaa-0000-4000-8000-000000000004";

function dreiImCanvas() {
  wamo.set((s) => ({
    ...s,
    canvas: [
      { id: A, kind: "dokument", title: "Angebot", text: "Erste Fassung" },
      { id: B, kind: "dokument", title: "Notiz", text: "Notiz" },
      { id: C, kind: "tabelle", title: "Städte", columns: ["Stadt"], rows: [["Frankfurt"]] },
    ],
  }));
}

const reiter = (container: HTMLElement) => Array.from(container.querySelectorAll<HTMLButtonElement>(".canvas-tab"));
const offen = (container: HTMLElement) => reiter(container).find((r) => r.getAttribute("aria-current") === "true")?.textContent;

describe("Canvas, Überarbeitung im offenen Reiter", () => {
  beforeEach(() => {
    resetWamo();
    dreiImCanvas();
  });
  afterEach(() => resetWamo());

  it("ersetzt das Element an derselben Stelle, legt keinen Reiter an und zeigt die neue Fassung", () => {
    const { container } = render(<CanvasBereich />);
    fireEvent.click(reiter(container)[0]); // die Person liest das Angebot
    act(() => applyServerMessage({ type: "canvas", item: { id: A2, kind: "dokument", title: "Angebot", text: "Zweite Fassung" }, ersetzt: A }));
    expect(reiter(container).map((r) => r.textContent)).toEqual(["Angebot", "Notiz", "Städte"]);
    expect(offen(container)).toBe("Angebot");
    expect(screen.getByText("Zweite Fassung")).toBeTruthy();
    expect(screen.queryByText("Erste Fassung")).toBeNull();
    expect(wamo.get().canvas.map((it) => it.id)).toEqual([A2, B, C]);
    expect(wamo.get().ansage).toBe("Auf dem Canvas überarbeitet: Angebot");
  });

  it("zeigt den überarbeiteten Reiter auch, wenn gerade ein anderer offen war", () => {
    const { container } = render(<CanvasBereich />);
    expect(offen(container)).toBe("Städte"); // ohne eigene Auswahl das Neueste
    act(() => applyServerMessage({ type: "canvas", item: { id: A2, kind: "dokument", title: "Angebot, kürzer", text: "Kurz" }, ersetzt: A }));
    expect(offen(container)).toBe("Angebot, kürzer");
    expect(screen.getByText("Kurz")).toBeTruthy();
  });

  it("hängt ein Element mit unbekanntem ersetzt wie bisher hinten an", () => {
    const { container } = render(<CanvasBereich />);
    act(() => applyServerMessage({ type: "canvas", item: { id: A2, kind: "dokument", title: "Neu", text: "x" }, ersetzt: "fremd" }));
    expect(reiter(container).map((r) => r.textContent)).toEqual(["Angebot", "Notiz", "Städte", "Neu"]);
    expect(wamo.get().ansage).toBe("Neues Ergebnis auf dem Canvas: Neu");
  });

  it("meldet den offenen Reiter beim Zeigen, beim Wechsel und nach der Überarbeitung, je Wechsel genau einmal", () => {
    const aktiv = vi.fn();
    const { container, rerender } = render(<CanvasBereich aktiv={aktiv} />);
    expect(aktiv.mock.calls).toEqual([[C]]);
    fireEvent.click(reiter(container)[1]);
    expect(aktiv.mock.calls).toEqual([[C], [B]]);
    rerender(<CanvasBereich aktiv={aktiv} />);
    fireEvent.click(reiter(container)[1]); // derselbe Reiter noch einmal: keine zweite Meldung
    expect(aktiv.mock.calls).toEqual([[C], [B]]);
    act(() => applyServerMessage({ type: "canvas", item: { id: A2, kind: "dokument", title: "Angebot", text: "Neu" }, ersetzt: A }));
    expect(aktiv.mock.calls).toEqual([[C], [B], [A2]]);
  });

  it("meldet ein Element ohne Kennung als null (der Kern sagt dem Modell, dass es sich nicht überarbeiten lässt)", () => {
    resetWamo();
    wamo.set((s) => ({ ...s, canvas: [{ kind: "tabelle", title: "Geräte", columns: ["Name"], rows: [["Drucker"]] }] }));
    const aktiv = vi.fn();
    render(<CanvasBereich aktiv={aktiv} />);
    expect(aktiv.mock.calls).toEqual([[null]]);
  });

  it("meldet den gewählten älteren Reiter erneut, wenn ein neues Element dazukommt, aber nicht bei Fortschritt am selben Element", () => {
    const aktiv = vi.fn();
    const { container } = render(<CanvasBereich aktiv={aktiv} />);
    fireEvent.click(reiter(container)[0]);
    expect(aktiv.mock.calls).toEqual([[C], [A]]);
    act(() => applyServerMessage({ type: "canvas", item: { id: "dev-7", kind: "dokument", title: "Auftrag", text: "läuft" } }));
    expect(offen(container)).toBe("Angebot"); // die eigene Auswahl bleibt
    expect(aktiv.mock.calls).toEqual([[C], [A], [A]]); // der Kern erfährt: offen ist weiter das Angebot, nicht das Neue
    act(() => applyServerMessage({ type: "canvas", item: { id: "dev-7", kind: "dokument", title: "Auftrag", text: "fertig" } }));
    expect(aktiv.mock.calls).toEqual([[C], [A], [A]]);
  });
});
