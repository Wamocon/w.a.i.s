// Komponententest des Umschalters für Hören und Sprechen (components/SprachWahl.tsx, Paket H5, getrennt seit 16.11.2026): Soniox ist
// Standard, Spracherkennung und Sprachausgabe gehen je für sich an den Kern, dazu die Stimme im Haus; der Zustand kommt nur aus der
// Antwort, ein Rückfall nennt den Grund, ein Fehler bleibt sichtbar.
// Dazu: die Laborsicht kennt weder die Karte Modellzugang noch den Hinweis zum Umschalten.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
const gruppe = (name: string) => screen.getByRole("radiogroup", { name });
const radio = (name: RegExp, inGruppe = "Spracherkennung") => within(gruppe(inGruppe)).getByRole("radio", { name });
const STIMMEN_STAND = {
  hausStimmeStandard: "sohee",
  hausStimmen: [
    { id: "sohee", name: "Sohee", hinweis: "am schnellsten gemessen, fehlerfrei zurückgelesen" },
    { id: "uncle_fu", name: "Uncle Fu" },
    { id: "ono_anna", name: "Ono Anna" },
  ],
  hausStimmenHinweis: "Keine der Stimmen ist nativ deutsch; sie sprechen Deutsch mit Akzent.",
};

describe("Umschalter Hören und Sprechen", () => {
  beforeEach(() => {
    resetWamo();
    wamo.set((s) => ({ ...s, modellzugang: STAND }));
  });

  it("zeigt Soniox als Standard, je Richtung eine eigene Gruppe, und die Folgen in Worten", () => {
    render(<SprachWahl senden={vi.fn()} />);
    for (const name of ["Spracherkennung", "Sprachausgabe"]) {
      expect(radio(/Soniox \(Standard\)/, name).getAttribute("aria-checked")).toBe("true");
      expect(radio(/Im Haus \(Datenschutz\)/, name).getAttribute("aria-checked")).toBe("false");
    }
    expect(screen.getByText(/ab der nächsten Sitzung/)).toBeTruthy();
    expect(screen.getByText(/Soniox ist der Standard/)).toBeTruthy();
  });

  it("Spracherkennung im Haus schickt nur sie um, die Sprachausgabe bleibt; der Zustand kommt erst aus der Antwort", async () => {
    const senden = vi.fn();
    render(<SprachWahl senden={senden} />);
    await userEvent.click(radio(/Im Haus/));
    expect(senden).toHaveBeenCalledWith({ aktion: "stimme", stt: "haus", tts: "soniox" });
    expect(screen.getByText("Wird gespeichert …")).toBeTruthy();
    act(() => {
      applyServerMessage({ type: "modellzugang", ...STAND, aktion: "stimme", stt: "haus", tts: "soniox" });
    });
    expect(radio(/Im Haus/).getAttribute("aria-checked")).toBe("true");
    expect(radio(/Soniox/, "Sprachausgabe").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText(/kein Live-Mitschreiben/)).toBeTruthy();
    expect(screen.getByText(/Erst wenn beides im Haus läuft/)).toBeTruthy();
    expect(screen.queryByText("Wird gespeichert …")).toBeNull();
  });

  it("Sprachausgabe im Haus schickt die Spracherkennung unverändert mit", async () => {
    const senden = vi.fn();
    wamo.set((s) => ({ ...s, modellzugang: { ...STAND, stt: "haus" } }));
    render(<SprachWahl senden={senden} />);
    await userEvent.click(radio(/Im Haus/, "Sprachausgabe"));
    expect(senden).toHaveBeenCalledWith({ aktion: "stimme", stt: "haus", tts: "haus" });
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
        fehler: "Die eigene Wahl von Hören und Stimme ist in dieser Datenbank noch nicht freigeschaltet",
      });
    });
    expect(screen.getByRole("alert").textContent).toMatch(/noch nicht freigeschaltet/);
    expect(radio(/Soniox/).getAttribute("aria-checked")).toBe("true");
  });

  it("Pfeiltasten wählen in der Radiogruppe", async () => {
    const senden = vi.fn();
    render(<SprachWahl senden={senden} />);
    radio(/Soniox/, "Sprachausgabe").focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(senden).toHaveBeenCalledWith({ aktion: "stimme", stt: "soniox", tts: "haus" });
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
    expect(senden).toHaveBeenCalledWith({ aktion: "stimme", stt: "soniox", tts: "haus" });
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
      applyServerMessage({ type: "modellzugang", ...STAND, aktion: "stimme", stt: "soniox", tts: "haus" });
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
    expect((radio(/Im Haus/, "Sprachausgabe") as HTMLButtonElement).disabled).toBe(false);
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

  it("Stimme im Haus: nur die Stimmen des Kerns in seiner Reihenfolge, Standard markiert, Hinweis nicht nativ deutsch", async () => {
    const senden = vi.fn();
    wamo.set((s) => ({ ...s, modellzugang: { ...STAND, tts: "haus", ...STIMMEN_STAND } }));
    render(<SprachWahl senden={senden} />);
    const auswahl = screen.getByLabelText("Stimme im Haus") as HTMLSelectElement;
    expect(auswahl.value).toBe("sohee");
    expect([...auswahl.options].map((o) => o.textContent)).toEqual(["Sohee (Standard)", "Uncle Fu", "Ono Anna"]);
    expect(screen.getByText(/nativ deutsch/).textContent).toMatch(/Sohee: am schnellsten gemessen/);
    await userEvent.selectOptions(auswahl, "uncle_fu");
    expect(senden).toHaveBeenCalledWith({ aktion: "haus_stimme", stimme: "uncle_fu" });
    expect(screen.getByText("Wird gespeichert …")).toBeTruthy();
    expect(auswahl.disabled).toBe(false); // Fokus bleibt während des Wartens
    act(() => {
      applyServerMessage({ type: "modellzugang", ...STAND, tts: "haus", ...STIMMEN_STAND, aktion: "haus_stimme", hausStimme: "uncle_fu" });
    });
    expect((screen.getByLabelText("Stimme im Haus") as HTMLSelectElement).value).toBe("uncle_fu");
    expect(screen.queryByText("Wird gespeichert …")).toBeNull();
  });

  it("während des Wartens schickt eine zweite Wahl nichts", async () => {
    const senden = vi.fn();
    render(<SprachWahl senden={senden} />);
    await userEvent.click(radio(/Im Haus/));
    await userEvent.click(radio(/Im Haus/, "Sprachausgabe"));
    expect(senden).toHaveBeenCalledTimes(1);
  });

  describe("Zeitgrenze", () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it("ohne Antwort nach 25 s ein Satz und der Stand wird neu geholt, damit keine Wahl einen alten Wert mitschickt", () => {
      const senden = vi.fn();
      render(<SprachWahl senden={senden} />);
      fireEvent.click(radio(/Im Haus/));
      act(() => {
        vi.advanceTimersByTime(25_000);
      });
      expect(senden).toHaveBeenLastCalledWith({ aktion: "status" });
      expect(screen.getByRole("alert").textContent).toMatch(/Keine Antwort vom Kern/);
      act(() => {
        applyServerMessage({ type: "modellzugang", ...STAND, aktion: "status", stt: "haus", tts: "soniox" });
      });
      expect(radio(/Im Haus/).getAttribute("aria-checked")).toBe("true");
      fireEvent.click(radio(/Im Haus/, "Sprachausgabe"));
      expect(senden).toHaveBeenLastCalledWith({ aktion: "stimme", stt: "haus", tts: "haus" });
    });
  });

  it("ein älterer Kern ohne Stimmenliste zeigt keine Stimmauswahl", () => {
    render(<SprachWahl senden={vi.fn()} />);
    expect(screen.queryByLabelText("Stimme im Haus")).toBeNull();
  });
});

describe("Abschnitt Mikrofon und Sprache", () => {
  beforeEach(() => resetWamo());

  it("zeigt den Umschalter für Hören und Sprechen mit dem Grund eines Rückfalls und was gerade läuft", () => {
    wamo.set((s) => ({
      ...s,
      betrieb: { ...BETRIEB, modelle: { stt: "Soniox (Rückfall)", tts: "Soniox Nina (Rückfall)" }, spracheGrund: "Sprachausgabe: im Kern noch nicht eingerichtet" },
    }));
    render(<SpracheAbschnitt mikrofone={async () => []} mikrofonWaehlen={() => true} />);
    expect(screen.getByRole("heading", { name: "Hören und Sprechen" })).toBeTruthy();
    expect(screen.getByRole("radiogroup", { name: "Spracherkennung" })).toBeTruthy();
    expect(screen.getByText(/Diese Sitzung weicht von der Wahl ab: Sprachausgabe: im Kern noch nicht eingerichtet\./)).toBeTruthy();
    expect(screen.getByText("Soniox (Rückfall)")).toBeTruthy();
    // der frühere Satz "Umschalten unter Modellzugang" ist weg: der Umschalter steht jetzt hier
    expect(screen.queryByText(/Umschalten zwischen Soniox und Im Haus/)).toBeNull();
  });

  it("Laborsicht: kein Modellzugang, kein Umschalter für Hören und Sprechen", () => {
    expect(abschnitteFuer({ rolle: "mitglied", labor: true }).map((a) => a.id)).not.toContain("modellzugang");
    wamo.set((s) => ({ ...s, betrieb: { ...BETRIEB, spracheGrund: "x" } }));
    render(<SpracheAbschnitt mikrofone={async () => []} mikrofonWaehlen={() => true} nurMikrofon />);
    expect(screen.queryByRole("radiogroup", { name: "Spracherkennung" })).toBeNull();
    expect(screen.queryByText(/Diese Sitzung weicht von der Wahl ab/)).toBeNull();
    expect(screen.queryByRole("heading", { name: "Hören und Sprechen" })).toBeNull();
  });
});
