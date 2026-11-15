// Komponententest: Mail über Outlook aus dem Canvas ("Als E-Mail" im Kopf, components/MailFormular.tsx), der Hinweis zum Versand mit
// "Zurückholen" (components/MailVersand.tsx) und die Warnung auf der Freigabekarte (components/Freigaben.tsx).
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CanvasBereich } from "@/components/Canvas";
import { Freigaben } from "@/components/Freigaben";
import { MailVersandHinweis } from "@/components/MailVersand";
import type { MailDaten } from "@/lib/mail";
import type { Betrieb } from "@/lib/nachrichten";
import { applyServerMessage, resetWamo, wamo } from "@/lib/wamo";

const ID = "11111111-1111-4111-8111-111111111111";
const VID = "fedcba9876543210";
const BETRIEB: Betrieb = { modus: "buero", modelle: {}, pc: "verbunden", pcSteuerung: "an", office: ["word", "pdf"], mail: true };

function zustand(item: Record<string, unknown>, betrieb: Betrieb | null = BETRIEB) {
  wamo.set((s) => ({ ...s, canvas: [item as never], betrieb }));
}

function mailAktionen() {
  return { vorbereiten: vi.fn<(d: MailDaten) => boolean>(() => true), zurueckholen: vi.fn<(id: string) => boolean>(() => true) };
}

const DOKUMENT = { id: ID, kind: "dokument", title: "Angebot Kunde X", text: "# Angebot" };

describe("Canvas, Als E-Mail", () => {
  beforeEach(() => resetWamo());
  afterEach(() => resetWamo());

  it("öffnet das Formular mit dem Titel als Betreff und schickt die Angaben zur Freigabe", () => {
    const mail = mailAktionen();
    zustand(DOKUMENT);
    render(<CanvasBereich mail={mail} />);
    fireEvent.click(screen.getByRole("button", { name: "Als E-Mail" }));
    expect((screen.getByLabelText("Betreff") as HTMLInputElement).value).toBe("Angebot Kunde X");
    expect((screen.getByLabelText("Anhang") as HTMLSelectElement).value).toBe("pdf");
    fireEvent.change(screen.getByLabelText("An"), { target: { value: "max@firma.example, Anna Schmidt" } });
    fireEvent.change(screen.getByLabelText("Cc"), { target: { value: "x@kunde.example" } });
    fireEvent.change(screen.getByLabelText("Text"), { target: { value: "Hallo Max,\nanbei das Angebot." } });
    fireEvent.click(screen.getByRole("button", { name: "Zur Freigabe vorbereiten" }));
    expect(mail.vorbereiten).toHaveBeenCalledExactlyOnceWith({
      canvasId: ID,
      an: ["max@firma.example", "Anna Schmidt"],
      cc: ["x@kunde.example"],
      betreff: "Angebot Kunde X",
      text: "Hallo Max,\nanbei das Angebot.",
      anhang: "pdf",
    });
    const knopf = screen.getByRole("button", { name: "Zur Freigabe vorbereiten" }) as HTMLButtonElement;
    expect(knopf.disabled).toBe(true); // bis die Antwort kommt: kein zweites Mal
    act(() => applyServerMessage({ type: "mail_antwort", ok: true }));
    expect(screen.queryByLabelText("An")).toBeNull(); // Karte liegt bereit, Formular zu
  });

  it("zeigt Fehler aus Formular und Kern und schickt Ungültiges nicht", () => {
    const mail = mailAktionen();
    zustand(DOKUMENT);
    render(<CanvasBereich mail={mail} />);
    fireEvent.click(screen.getByRole("button", { name: "Als E-Mail" }));
    fireEvent.click(screen.getByRole("button", { name: "Zur Freigabe vorbereiten" }));
    expect(mail.vorbereiten).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toMatch(/Empfänger/);
    fireEvent.change(screen.getByLabelText("An"), { target: { value: "max@firma.example" } });
    fireEvent.change(screen.getByLabelText("Anhang"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Zur Freigabe vorbereiten" }));
    expect(mail.vorbereiten.mock.calls[0][0].anhang).toBeNull();
    act(() => applyServerMessage({ type: "mail_antwort", ok: false, grund: "Outlook ist nicht geöffnet." }));
    expect(screen.getByRole("alert").textContent).toMatch(/Outlook ist nicht geöffnet/);
    expect((screen.getByRole("button", { name: "Zur Freigabe vorbereiten" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("gibt es nur mit betrieb.mail, mit Aktionen und für eigene, gespeicherte Elemente", () => {
    zustand(DOKUMENT, { ...BETRIEB, mail: undefined });
    const eins = render(<CanvasBereich mail={mailAktionen()} />);
    expect(screen.queryByRole("button", { name: "Als E-Mail" })).toBeNull();
    eins.unmount();
    zustand(DOKUMENT);
    const zwei = render(<CanvasBereich />);
    expect(screen.queryByRole("button", { name: "Als E-Mail" })).toBeNull();
    zwei.unmount();
    zustand({ ...DOKUMENT, geteilt: { von: "Anna", recht: "lesen" } });
    const drei = render(<CanvasBereich mail={mailAktionen()} />);
    expect(screen.queryByRole("button", { name: "Als E-Mail" })).toBeNull();
    drei.unmount();
    zustand({ ...DOKUMENT, id: null });
    render(<CanvasBereich mail={mailAktionen()} />);
    expect(screen.queryByRole("button", { name: "Als E-Mail" })).toBeNull();
  });

  it("überarbeitet W.A.I.S. das Element, bleibt das offene Formular stehen und schickt die neue Fassung", () => {
    const NEU = "22222222-2222-4222-8222-222222222222";
    const mail = mailAktionen();
    zustand(DOKUMENT);
    render(<CanvasBereich mail={mail} />);
    fireEvent.click(screen.getByRole("button", { name: "Als E-Mail" }));
    fireEvent.change(screen.getByLabelText("An"), { target: { value: "max@firma.example" } });
    act(() =>
      applyServerMessage({ type: "canvas", item: { id: NEU, kind: "dokument", title: DOKUMENT.title, text: "# Angebot, überarbeitet" }, ersetzt: ID }),
    );
    expect((screen.getByLabelText("An") as HTMLInputElement).value).toBe("max@firma.example");
    fireEvent.click(screen.getByRole("button", { name: "Zur Freigabe vorbereiten" }));
    expect(mail.vorbereiten.mock.calls[0][0].canvasId).toBe(NEU);
  });
});

describe("Versand mit Zurückholen", () => {
  beforeEach(() => {
    resetWamo();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    resetWamo();
  });

  it("zählt herunter, holt zurück und zeigt danach den Endstand ohne Knopf", () => {
    const zurueck = vi.fn<(id: string) => boolean>(() => true);
    render(<MailVersandHinweis onZurueckholen={zurueck} />);
    act(() => applyServerMessage({ type: "mail_versand", id: VID, zustand: "wartet", restS: 30, text: "x" }));
    expect(screen.getByText("Die Mail geht in 30 Sekunden raus.")).toBeTruthy();
    act(() => vi.advanceTimersByTime(5_000));
    expect(screen.getByText("Die Mail geht in 25 Sekunden raus.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Zurückholen" }));
    expect(zurueck).toHaveBeenCalledExactlyOnceWith(VID);
    act(() =>
      applyServerMessage({
        type: "mail_versand",
        id: VID,
        zustand: "zurueckgeholt",
        text: "Zurückgeholt: Die Mail ist nicht rausgegangen und liegt in Outlook unter Entwürfe.",
      }),
    );
    expect(screen.getByText(/liegt in Outlook unter Entwürfe/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Zurückholen" })).toBeNull();
  });

  it("nach der Frist kein Zurückholen mehr, der Endstand kommt vom Kern", () => {
    render(<MailVersandHinweis onZurueckholen={vi.fn(() => true)} />);
    act(() => applyServerMessage({ type: "mail_versand", id: VID, zustand: "wartet", restS: 2, text: "x" }));
    act(() => vi.advanceTimersByTime(3_000));
    expect(screen.getByText("Die Mail geht jetzt raus.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Zurückholen" })).toBeNull();
    act(() => applyServerMessage({ type: "mail_versand", id: VID, zustand: "gesendet", text: "Die Mail ist gesendet." }));
    expect(screen.getByText("Die Mail ist gesendet.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Hinweis schließen" }));
    expect(screen.queryByText("Die Mail ist gesendet.")).toBeNull();
  });
});

describe("Freigabekarte einer Mail", () => {
  beforeEach(() => resetWamo());
  afterEach(() => resetWamo());

  it("zeigt die Warnung bei Fremdinhalt und den ganzen langen Text", () => {
    const detail = "So geht es: Outlook (klassisch) läuft\nAn: max@firma.example (intern)\nText:\n" + "> Zeile\n".repeat(400);
    render(<Freigaben onDecide={() => true} />);
    act(() =>
      applyServerMessage({
        type: "freigaben",
        job: "pc",
        projekt: "PC",
        items: [{ id: "0123456789abcdef", grund: "Mail über Outlook senden", detail, warnung: "Prüfe Empfänger und Text besonders genau." }],
      }),
    );
    expect(screen.getByText("Prüfe Empfänger und Text besonders genau.")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Was genau ausgeführt wird" }).textContent).toBe(detail);
  });
});
