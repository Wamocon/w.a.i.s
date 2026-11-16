// Komponententest des Umschalters für Hören und Stimme (components/SprachWahl.tsx, Paket H5): Soniox ist Standard, eine Wahl schickt
// Hören und Stimme gemeinsam an den Kern, der Zustand kommt nur aus der Antwort, ein Rückfall nennt den Grund, ein Fehler bleibt sichtbar.
// Dazu: die Laborsicht kennt weder die Karte Modellzugang noch den Hinweis zum Umschalten.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SpracheAbschnitt } from "@/components/einstellungen/Abschnitte";
import { SprachWahl } from "@/components/SprachWahl";
import { abschnitteFuer } from "@/lib/einstellungenAbschnitte";
import { parseServerMessage, type Betrieb, type Modellzugang } from "@/lib/nachrichten";
import { applyServerMessage, resetWamo, wamo } from "@/lib/wamo";

const STAND: Modellzugang = {
  aktion: "status",
  art: "haus",
  quelle: "keiner",
  hinterlegt: false,
  festgelegt: false,
  codeHinterlegt: false,
  stt: "soniox",
  tts: "soniox",
  stimmeHaus: "bereit",
};
const BETRIEB: Betrieb = { modus: "buero", modelle: { llm: "gemma4-31b (LiteLLM)", stt: "Soniox", tts: "Soniox Nina" }, pc: "aus" };
const radio = (name: RegExp) => screen.getByRole("radio", { name });

describe("Umschalter Hören und Stimme", () => {
  beforeEach(() => {
    resetWamo();
    wamo.set((s) => ({ ...s, modellzugang: STAND }));
  });

  it("zeigt Soniox als Standard und die Folgen in Worten", () => {
    render(<SprachWahl senden={vi.fn()} />);
    expect(screen.getByRole("radiogroup", { name: "Spracherkennung und Sprachausgabe" })).toBeTruthy();
    expect(radio(/Soniox \(Standard\)/).getAttribute("aria-checked")).toBe("true");
    expect(radio(/Im Haus \(Datenschutz\)/).getAttribute("aria-checked")).toBe("false");
    expect(screen.getByText(/ab der nächsten Sitzung/)).toBeTruthy();
  });

  it("Im Haus schickt Hören und Stimme gemeinsam; der Zustand kommt erst aus der Antwort des Kerns", async () => {
    const senden = vi.fn();
    render(<SprachWahl senden={senden} />);
    await userEvent.click(radio(/Im Haus/));
    expect(senden).toHaveBeenCalledWith({ aktion: "stimme", stt: "haus", tts: "haus" });
    expect(screen.getByText("Wird gespeichert …")).toBeTruthy();
    act(() => {
      applyServerMessage({ type: "modellzugang", ...STAND, aktion: "stimme", stt: "haus", tts: "haus" });
    });
    expect(radio(/Im Haus/).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText(/kein Live-Mitschreiben/)).toBeTruthy();
    expect(screen.queryByText("Wird gespeichert …")).toBeNull();
  });

  it("dieselbe Wahl noch einmal schickt nichts; ohne lesbaren Stand ist nichts bedienbar", async () => {
    const senden = vi.fn();
    const { unmount } = render(<SprachWahl senden={senden} />);
    await userEvent.click(radio(/Soniox/));
    expect(senden).not.toHaveBeenCalled();
    unmount();
    wamo.set((s) => ({ ...s, modellzugang: { ...STAND, art: undefined, fehler: "Der Kern ist nicht erreichbar." } }));
    render(<SprachWahl senden={senden} />);
    expect((radio(/Im Haus/) as HTMLButtonElement).disabled).toBe(true);
  });

  it("ein Fehler des Kerns steht sichtbar da, die Wahl bleibt beim alten Stand", async () => {
    render(<SprachWahl senden={vi.fn()} />);
    await userEvent.click(radio(/Im Haus/));
    act(() => {
      applyServerMessage({
        type: "modellzugang",
        ...STAND,
        aktion: "stimme",
        fehler: "Die eigene Wahl von Hören und Stimme ist in dieser Datenbank noch nicht freigeschaltet (Migration 0023)",
      });
    });
    expect(screen.getByRole("alert").textContent).toMatch(/noch nicht freigeschaltet/);
    expect(radio(/Soniox/).getAttribute("aria-checked")).toBe("true");
  });

  it("Pfeiltasten wählen in der Radiogruppe", async () => {
    const senden = vi.fn();
    render(<SprachWahl senden={senden} />);
    radio(/Soniox/).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(senden).toHaveBeenCalledWith({ aktion: "stimme", stt: "haus", tts: "haus" });
  });

  it("ein Kern, der die Wahl nicht kennt, sperrt den Umschalter mit Satz", async () => {
    const senden = vi.fn();
    wamo.set((s) => ({ ...s, modellzugang: { ...STAND, stimmeHaus: undefined } }));
    render(<SprachWahl senden={senden} />);
    expect((radio(/Im Haus/) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(radio(/Im Haus/));
    expect(senden).not.toHaveBeenCalled();
    expect(screen.getByText(/kennt die Wahl noch nicht/)).toBeTruthy();
  });

  it("Im Haus ist gesperrt, solange der Kern es nicht eingerichtet meldet; zurück zu Soniox geht immer", async () => {
    const senden = vi.fn();
    wamo.set((s) => ({ ...s, modellzugang: { ...STAND, stt: "haus", tts: "haus", stimmeHaus: "im Kern noch nicht eingerichtet" } }));
    render(<SprachWahl senden={senden} />);
    expect(screen.getByText("Im Haus geht gerade nicht: im Kern noch nicht eingerichtet. Bis dahin gilt Soniox.")).toBeTruthy();
    await userEvent.click(radio(/Soniox/));
    expect(senden).toHaveBeenCalledWith({ aktion: "stimme", stt: "soniox", tts: "soniox" });
  });

  it("Im Haus nicht eingerichtet und gewählt ist Soniox: Im Haus lässt sich nicht wählen", async () => {
    const senden = vi.fn();
    wamo.set((s) => ({ ...s, modellzugang: { ...STAND, stimmeHaus: "im Kern noch nicht eingerichtet" } }));
    render(<SprachWahl senden={senden} />);
    expect((radio(/Im Haus/) as HTMLButtonElement).disabled).toBe(true);
    radio(/Soniox/).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(senden).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(radio(/Soniox/));
  });

  it("eine späte Antwort auf eine andere Wahl beendet das Warten nicht", async () => {
    render(<SprachWahl senden={vi.fn()} />);
    await userEvent.click(radio(/Im Haus/));
    act(() => {
      applyServerMessage({ type: "modellzugang", ...STAND, aktion: "stimme", stt: "soniox", tts: "soniox" });
    });
    expect(screen.getByText("Wird gespeichert …")).toBeTruthy();
  });

  it("der Grund der Sitzung kommt aus der Meldung des Kerns bis in den Speicher", () => {
    const m = parseServerMessage({ type: "betrieb", modus: "buero", modelle: {}, pc: "aus", sprache_grund: "Sprachausgabe: im Kern noch nicht eingerichtet" });
    expect(m).toBeTruthy();
    act(() => applyServerMessage(m!));
    expect(wamo.get().betrieb?.spracheGrund).toBe("Sprachausgabe: im Kern noch nicht eingerichtet");
  });

  it("der Zwang des Admins auf Hausmodelle sperrt die Stimme nicht", () => {
    wamo.set((s) => ({ ...s, modellzugang: { ...STAND, festgelegt: true, quelle: "festgelegt" } }));
    render(<SprachWahl senden={vi.fn()} />);
    expect((radio(/Im Haus/) as HTMLButtonElement).disabled).toBe(false);
  });

  it("ein Rückfall der laufenden Sitzung nennt den Grund", () => {
    wamo.set((s) => ({
      ...s,
      modellzugang: { ...STAND, stt: "haus", tts: "haus" },
      betrieb: {
        ...BETRIEB,
        modelle: { stt: "Soniox (Rückfall)", tts: "Soniox Nina (Rückfall)" },
        spracheGrund: "Spracherkennung und Sprachausgabe: das Gateway bietet das Sprachmodell noch nicht an",
      },
    }));
    render(<SprachWahl senden={vi.fn()} />);
    expect(screen.getByRole("status").textContent).toMatch(/weicht von der Wahl ab: Spracherkennung und Sprachausgabe: das Gateway/);
  });

  it("ein gemischter Stand vom Admin wird genannt, keine Wahl ist markiert", () => {
    wamo.set((s) => ({ ...s, modellzugang: { ...STAND, stt: "haus", tts: "soniox" } }));
    render(<SprachWahl senden={vi.fn()} />);
    expect(radio(/Soniox/).getAttribute("aria-checked")).toBe("false");
    expect(radio(/Im Haus/).getAttribute("aria-checked")).toBe("false");
    expect(radio(/Soniox/).tabIndex).toBe(0);
    expect(screen.getByText(/Vom Admin gesetzt: Hören Im Haus, Stimme Soniox/)).toBeTruthy();
  });
});

describe("Abschnitt Sprache und Ton", () => {
  beforeEach(() => resetWamo());

  it("zeigt den Grund eines Rückfalls und wo man umschaltet", () => {
    wamo.set((s) => ({
      ...s,
      betrieb: { ...BETRIEB, modelle: { stt: "Soniox (Rückfall)", tts: "Soniox Nina (Rückfall)" }, spracheGrund: "Sprachausgabe: im Kern noch nicht eingerichtet" },
    }));
    render(<SpracheAbschnitt mikrofone={async () => []} mikrofonWaehlen={() => true} />);
    expect(screen.getByText(/Hinweis zu dieser Sitzung: Sprachausgabe: im Kern noch nicht eingerichtet\./)).toBeTruthy();
    expect(screen.getByText(/Umschalten zwischen Soniox und Im Haus/)).toBeTruthy();
  });

  it("Laborsicht: kein Modellzugang, kein Hinweis zum Umschalten", () => {
    expect(abschnitteFuer({ rolle: "mitglied", labor: true }).map((a) => a.id)).not.toContain("modellzugang");
    wamo.set((s) => ({ ...s, betrieb: { ...BETRIEB, spracheGrund: "x" } }));
    render(<SpracheAbschnitt mikrofone={async () => []} mikrofonWaehlen={() => true} nurMikrofon />);
    expect(screen.queryByText(/Umschalten zwischen Soniox/)).toBeNull();
    expect(screen.queryByText(/Hinweis zu dieser Sitzung/)).toBeNull();
  });
});
