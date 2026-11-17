// Komponententest: Canvas als Datei speichern (Knöpfe im Kopf des Canvas, components/Canvas.tsx) und der Hinweis danach mit "Öffnen"
// (components/DateiHinweis.tsx). Ausführen im Ordner ui/:  npm run test:komponenten
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CanvasBereich } from "@/components/Canvas";
import { DateiHinweis } from "@/components/DateiHinweis";
import type { Betrieb } from "@/lib/nachrichten";
import { applyServerMessage, resetWamo, wamo } from "@/lib/wamo";

const ID = "11111111-1111-4111-8111-111111111111";
const BETRIEB: Betrieb = { modus: "buero", modelle: {}, pc: "verbunden", pcSteuerung: "an", office: ["word", "excel", "pdf"] };

function zustand(item: Record<string, unknown>, betrieb: Betrieb | null = BETRIEB) {
  wamo.set((s) => ({ ...s, canvas: [item as never], betrieb }));
}

function aktionen() {
  return { speichern: vi.fn(() => true), oeffnen: vi.fn(() => true) };
}

describe("Canvas, Speichern als Datei", () => {
  beforeEach(() => resetWamo());
  afterEach(() => resetWamo());

  it("zeigt für ein eigenes Dokument nur die gemeldeten, passenden Formate", () => {
    zustand({ id: ID, kind: "dokument", title: "Angebot", text: "# A" });
    render(<CanvasBereich office={aktionen()} />);
    expect(screen.getByRole("button", { name: "Als Word speichern" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Als PDF speichern" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Als Excel speichern" })).toBeNull(); // nur für Tabellen
    expect(screen.queryByRole("button", { name: "Als PowerPoint speichern" })).toBeNull(); // nicht gemeldet
  });

  it("schickt Kennung und Format und sperrt den Knopf, bis die Antwort kommt", () => {
    const office = aktionen();
    zustand({ id: ID, kind: "tabelle", title: "Liste", columns: ["a"], rows: [["1"]] });
    render(<CanvasBereich office={office} />);
    fireEvent.click(screen.getByRole("button", { name: "Als Excel speichern" }));
    expect(office.speichern).toHaveBeenCalledExactlyOnceWith(ID, "excel");
    const knopf = screen.getByRole("button", { name: "Als Excel speichern" }) as HTMLButtonElement;
    expect(knopf.disabled).toBe(true);
    fireEvent.click(knopf);
    expect(office.speichern).toHaveBeenCalledTimes(1); // kein Doppelklick
    act(() => applyServerMessage({ type: "datei", ok: false, grund: "Die PC-Steuerung ist aus." }));
    expect((screen.getByRole("button", { name: "Als Excel speichern" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("zeigt keine Knöpfe ohne Formate, ohne Aktionen, für geteilte und für nicht gespeicherte Elemente", () => {
    zustand({ id: ID, kind: "dokument", title: "A", text: "x" }, { ...BETRIEB, office: undefined });
    const { unmount } = render(<CanvasBereich office={aktionen()} />);
    expect(screen.queryByRole("button", { name: /speichern/ })).toBeNull();
    unmount();
    zustand({ id: ID, kind: "dokument", title: "A", text: "x" });
    const zwei = render(<CanvasBereich />);
    expect(screen.queryByRole("button", { name: /speichern/ })).toBeNull();
    zwei.unmount();
    zustand({ id: ID, kind: "dokument", title: "A", text: "x", geteilt: { von: "Anna", recht: "bearbeiten" } });
    const drei = render(<CanvasBereich office={aktionen()} />);
    expect(screen.queryByRole("button", { name: /speichern/ })).toBeNull();
    drei.unmount();
    zustand({ kind: "dokument", title: "A", text: "x" });
    render(<CanvasBereich office={aktionen()} />);
    expect(screen.queryByRole("button", { name: /speichern/ })).toBeNull();
  });
});

describe("Canvas, als OneNote-Seite", () => {
  beforeEach(() => resetWamo());
  afterEach(() => resetWamo());

  it("schickt die Kennung, sperrt bis zur Antwort und zeigt sie als Hinweis", () => {
    const office = { ...aktionen(), onenote: vi.fn(() => true) };
    zustand({ id: ID, kind: "dokument", title: "Angebot", text: "# A" }, { ...BETRIEB, onenote: true });
    render(<CanvasBereich office={office} />);
    fireEvent.click(screen.getByRole("button", { name: "Als OneNote-Seite" }));
    expect(office.onenote).toHaveBeenCalledExactlyOnceWith(ID);
    expect((screen.getByRole("button", { name: "Als OneNote-Seite" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Als Word speichern" }) as HTMLButtonElement).disabled).toBe(true);
    act(() => applyServerMessage({ type: "onenote", ok: true, text: "Die OneNote-Seite liegt zur Freigabe bereit." }));
    expect((screen.getByRole("button", { name: "Als OneNote-Seite" }) as HTMLButtonElement).disabled).toBe(false);
    expect(wamo.get().toast?.text).toBe("Die OneNote-Seite liegt zur Freigabe bereit.");
  });

  it("geht auch ohne Dateiformate, aber nie ohne Meldung des Kerns oder ohne Aktion", () => {
    zustand({ id: ID, kind: "tabelle", title: "Liste", columns: ["a"], rows: [["1"]] }, { ...BETRIEB, office: undefined, onenote: true });
    const eins = render(<CanvasBereich office={{ ...aktionen(), onenote: vi.fn(() => true) }} />);
    expect(screen.getByRole("button", { name: "Als OneNote-Seite" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /speichern/ })).toBeNull();
    eins.unmount();
    zustand({ id: ID, kind: "dokument", title: "A", text: "x" });
    const zwei = render(<CanvasBereich office={{ ...aktionen(), onenote: vi.fn(() => true) }} />);
    expect(screen.queryByRole("button", { name: "Als OneNote-Seite" })).toBeNull();
    zwei.unmount();
    zustand({ id: ID, kind: "dokument", title: "A", text: "x" }, { ...BETRIEB, onenote: true });
    render(<CanvasBereich office={aktionen()} />);
    expect(screen.queryByRole("button", { name: "Als OneNote-Seite" })).toBeNull();
  });
});

describe("Hinweis nach dem Speichern", () => {
  beforeEach(() => resetWamo());
  afterEach(() => resetWamo());

  it("nennt Datei und Ordner, öffnet per Klick und lässt sich schließen", () => {
    const oeffnen = vi.fn(() => true);
    render(<DateiHinweis onOeffnen={oeffnen} />);
    act(() =>
      applyServerMessage({
        type: "datei", ok: true, kennung: "0123456789abcdef", name: "2026-11-14 Angebot.docx", format: "word",
        ordner: "Dokumente\\WAIS", pfad: "C:\\Users\\x\\Dokumente\\WAIS\\2026-11-14 Angebot.docx", geoeffnet: false,
      }),
    );
    expect(screen.getByText("2026-11-14 Angebot.docx liegt in Dokumente\\WAIS.")).toBeTruthy();
    expect(screen.getByText("C:\\Users\\x\\Dokumente\\WAIS\\2026-11-14 Angebot.docx")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Im Ordner zeigen" }));
    expect(oeffnen).toHaveBeenCalledExactlyOnceWith("0123456789abcdef");
    fireEvent.click(screen.getByRole("button", { name: "Hinweis schließen" }));
    expect(screen.queryByText(/Angebot\.docx/)).toBeNull();
  });

  it("zeigt einen Fehler als kurzen Hinweis", () => {
    render(<DateiHinweis onOeffnen={vi.fn(() => true)} />);
    act(() => applyServerMessage({ type: "datei", ok: false, grund: "Dieses Format geht an diesem PC nicht." }));
    expect(wamo.get().toast?.text).toBe("Dieses Format geht an diesem PC nicht.");
    expect(screen.queryByRole("button", { name: "Im Ordner zeigen" })).toBeNull();
  });
});
