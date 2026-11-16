// Komponententest der Modellwahl je Aufgabe (components/ModellAuswahl.tsx, Wunsch von Niko vom 16.11.2026): Automatisch ist Standard, die
// Auswahl zeigt nur, was der Kern für diesen Zugang anbietet (Claude nur mit Claude-Zugang), ein vom Admin festgelegtes Profil ist gesperrt
// mit Grund, die Wahl geht an den Kern und der Zustand kommt nur aus seiner Antwort; die Laborsicht kennt die Karte nicht.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ModellAuswahl } from "@/components/ModellAuswahl";
import { abschnitteFuer } from "@/lib/einstellungenAbschnitte";
import type { ModellBereichStand, Modellzugang } from "@/lib/nachrichten";
import { applyServerMessage, resetWamo, wamo } from "@/lib/wamo";

const HAUS: ModellBereichStand["optionen"] = [
  { id: "gemma4-31b", name: "Gemma 4 31B", art: "haus", zeile: "Güte 92 %, Tempo mittel (erstes Wort 0,6 s)" },
  { id: "qwen3.6-35b", name: "Qwen 3.6 35B", art: "haus", zeile: "Güte 74 %, Tempo mittel, nur als Notlösung" },
];
const CLAUDE: ModellBereichStand["optionen"] = [
  { id: "claude-haiku-5-5", name: "Claude Haiku 5.5", art: "claude", zeile: "Güte 88 %, Tempo schnell, Cloud, kostet je Anfrage" },
  { id: "claude-sonnet-5-5", name: "Claude Sonnet 5.5", art: "claude", zeile: "nicht gemessen, Cloud, deutlich teurer als Haiku" },
];
const stand = (optionen: ModellBereichStand["optionen"], wahl = "automatisch"): ModellBereichStand => ({ wahl, optionen });
const HAUSPROFIL: Modellzugang = {
  aktion: "status",
  art: "haus",
  quelle: "keiner",
  hinterlegt: false,
  festgelegt: false,
  codeHinterlegt: false,
  modelle: { gespraech: stand(HAUS), bilder: stand(HAUS), hintergrund: stand(HAUS) },
};
const CLAUDEPROFIL: Modellzugang = {
  ...HAUSPROFIL,
  art: "claude",
  quelle: "profil",
  hinterlegt: true,
  modelle: { gespraech: stand([...CLAUDE, ...HAUS]), bilder: stand([...CLAUDE, ...HAUS]), hintergrund: stand([...CLAUDE, ...HAUS]) },
};
const auswahl = (name: string) => screen.getByLabelText(name) as HTMLSelectElement;
const texte = (s: HTMLSelectElement) => [...s.options].map((o) => o.value);

describe("Modelle je Aufgabe", () => {
  beforeEach(() => {
    resetWamo();
    wamo.set((s) => ({ ...s, modellzugang: HAUSPROFIL }));
  });

  it("drei Auswahllisten, Automatisch ist Standard, ein Hausprofil sieht keine Claude-Modelle", () => {
    render(<ModellAuswahl senden={vi.fn()} />);
    for (const name of ["Gesprächsmodell", "Bildschirm und Bilder", "Lernen und Zusammenfassung"]) {
      expect(auswahl(name).value).toBe("automatisch");
      expect(texte(auswahl(name))).toEqual(["automatisch", "gemma4-31b", "qwen3.6-35b"]);
    }
    expect(screen.queryByText(/Claude/)).toBeNull();
    expect([...auswahl("Gesprächsmodell").options][1].textContent).toBe("Gemma 4 31B · Güte 92 %, Tempo mittel (erstes Wort 0,6 s)");
    expect(screen.getAllByText(/Das ist der Standard/).length).toBe(3);
  });

  it("ein Claude-Profil sieht die Claude-Modelle in eigener Gruppe, mit Hinweis auf die Kosten und den Rückfall", () => {
    const modelle = { ...CLAUDEPROFIL.modelle, gespraech: stand([...CLAUDE, ...HAUS], "claude-sonnet-5-5"), bilder: stand([...CLAUDE, ...HAUS], "gemma4-31b") };
    wamo.set((s) => ({ ...s, modellzugang: { ...CLAUDEPROFIL, modelle } }));
    render(<ModellAuswahl senden={vi.fn()} />);
    const gruppen = [...auswahl("Gesprächsmodell").querySelectorAll("optgroup")].map((g) => g.label);
    expect(gruppen).toEqual(["Claude (Cloud, über deinen Schlüssel)", "Im Haus"]);
    expect(texte(auswahl("Gesprächsmodell"))).toContain("claude-sonnet-5-5");
    expect(screen.getByText(/Claude Sonnet 5.5: .*geht von deinem Guthaben ab/)).toBeTruthy();
    expect(screen.getByText(/Gemma 4 31B: .*auch Claude in der Cloud/)).toBeTruthy();
  });

  it("eine Wahl geht an den Kern; der Zustand kommt erst aus der Antwort", async () => {
    const senden = vi.fn();
    render(<ModellAuswahl senden={senden} />);
    await userEvent.selectOptions(auswahl("Gesprächsmodell"), "qwen3.6-35b");
    expect(senden).toHaveBeenCalledWith({ aktion: "modell", bereich: "gespraech", modell: "qwen3.6-35b" });
    expect(screen.getByText("Wird gespeichert …")).toBeTruthy();
    // während des Wartens bleibt die Auswahl bedienbar (Fokus bleibt), eine zweite Wahl geht aber nicht weg
    expect(auswahl("Gesprächsmodell").disabled).toBe(false);
    await userEvent.selectOptions(auswahl("Bildschirm und Bilder"), "gemma4-31b");
    expect(senden).toHaveBeenCalledTimes(1);
    expect(auswahl("Bildschirm und Bilder").value).toBe("automatisch");
    expect(screen.getByText(/Qwen 3.6 35B: .*nächstbeste Modell im Haus/)).toBeTruthy();
    act(() => {
      applyServerMessage({
        type: "modellzugang",
        ...HAUSPROFIL,
        aktion: "modell",
        modelle: { ...HAUSPROFIL.modelle, gespraech: stand(HAUS, "qwen3.6-35b") },
      });
    });
    expect(auswahl("Gesprächsmodell").value).toBe("qwen3.6-35b");
    expect(screen.getByText(/Qwen 3.6 35B: Güte 74 %.*nur als Notlösung/)).toBeTruthy();
    expect(screen.queryByText("Wird gespeichert …")).toBeNull();
  });

  it("ein Fehler des Kerns steht beim Bereich, die Wahl bleibt beim alten Stand", async () => {
    render(<ModellAuswahl senden={vi.fn()} />);
    await userEvent.selectOptions(auswahl("Lernen und Zusammenfassung"), "gemma4-31b");
    act(() => {
      applyServerMessage({ type: "modellzugang", ...HAUSPROFIL, aktion: "modell", fehler: "Zu viele Wechsel, bitte in zehn Minuten noch einmal" });
    });
    const bereich = auswahl("Lernen und Zusammenfassung").closest(".mz-modell") as HTMLElement;
    expect(within(bereich).getByRole("alert").textContent).toMatch(/Zu viele Wechsel/);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(auswahl("Lernen und Zusammenfassung").value).toBe("automatisch");
  });

  describe("Zeitgrenze", () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it("ohne Antwort nach 25 s ein Satz; ein später Erfolg nimmt ihn zurück; ein Status mit der Wahl beendet das Warten", () => {
      const senden = vi.fn();
      render(<ModellAuswahl senden={senden} />);
      fireEvent.change(auswahl("Gesprächsmodell"), { target: { value: "gemma4-31b" } });
      act(() => {
        vi.advanceTimersByTime(25_000);
      });
      expect(screen.getByRole("alert").textContent).toMatch(/Keine Antwort vom Kern/);
      act(() => {
        applyServerMessage({ type: "modellzugang", ...HAUSPROFIL, aktion: "modell", modelle: { ...HAUSPROFIL.modelle, gespraech: stand(HAUS, "gemma4-31b") } });
      });
      expect(screen.queryByRole("alert")).toBeNull();
      fireEvent.change(auswahl("Bildschirm und Bilder"), { target: { value: "qwen3.6-35b" } });
      expect(screen.getByText("Wird gespeichert …")).toBeTruthy();
      act(() => {
        applyServerMessage({
          type: "modellzugang",
          ...HAUSPROFIL,
          aktion: "status",
          modelle: { ...HAUSPROFIL.modelle, gespraech: stand(HAUS, "gemma4-31b"), bilder: stand(HAUS, "qwen3.6-35b") },
        });
      });
      expect(screen.queryByText("Wird gespeichert …")).toBeNull();
    });
  });

  it("vom Admin festgelegt: alles gesperrt, mit Grund", async () => {
    const senden = vi.fn();
    wamo.set((s) => ({
      ...s,
      modellzugang: { ...HAUSPROFIL, festgelegt: true, quelle: "festgelegt", modellSperre: "Ein Admin hat dein Profil auf Hausmodelle festgelegt. Die Modellwahl ist gesperrt." },
    }));
    render(<ModellAuswahl senden={senden} />);
    expect(screen.getByText(/Die Modellwahl ist gesperrt/)).toBeTruthy();
    for (const name of ["Gesprächsmodell", "Bildschirm und Bilder", "Lernen und Zusammenfassung"]) expect(auswahl(name).disabled).toBe(true);
  });

  it("ein älterer Kern ohne Modellwahl: gesperrt mit Satz; eine gespeicherte Wahl, die nicht gilt, wird genannt", () => {
    wamo.set((s) => ({ ...s, modellzugang: { ...HAUSPROFIL, modelle: undefined } }));
    const { unmount } = render(<ModellAuswahl senden={vi.fn()} />);
    expect(screen.getByText(/kennt die Modellwahl noch nicht/)).toBeTruthy();
    expect(auswahl("Gesprächsmodell").disabled).toBe(true);
    unmount();
    const hinweis = "Gespeichert ist Claude Sonnet 5.5. Mit deinem Zugang gilt das gerade nicht, deshalb wählt W.A.I.S. automatisch.";
    wamo.set((s) => ({ ...s, modellzugang: { ...HAUSPROFIL, modelle: { ...HAUSPROFIL.modelle, gespraech: { ...stand(HAUS), hinweis } } } }));
    render(<ModellAuswahl senden={vi.fn()} />);
    expect(screen.getByText(hinweis)).toBeTruthy();
  });

  it("die laufende Sitzung nennt den Grund, wenn sie vom Gesprächsmodell abweicht", () => {
    wamo.set((s) => ({ ...s, betrieb: { modus: "buero", modelle: {}, pc: "aus", modellHinweis: "Qwen 3.6 35B: antwortet zu langsam" } }));
    render(<ModellAuswahl senden={vi.fn()} />);
    expect(screen.getByRole("status").textContent).toBe("Diese Sitzung: Qwen 3.6 35B: antwortet zu langsam. Die Wahl gilt ab der nächsten Sitzung.");
  });

  it("Laborsicht: kein Abschnitt Modellzugang", () => {
    expect(abschnitteFuer({ rolle: "mitglied", labor: true }).map((a) => a.id)).not.toContain("modellzugang");
    expect(abschnitteFuer({ rolle: "mitglied" }).find((a) => a.id === "modellzugang")?.kurz).toMatch(/Modelle/);
  });
});
