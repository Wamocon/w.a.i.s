// Komponententest des Mikrofontests (components/einstellungen/MikrofonTest.tsx, lib/mikrofonTest.ts, Wunsch vom 18.11.2026): Knopf im Block
// Eingabe, 3 s Ruhe und 5 s Sprechen, Ergebnis mit Ampel, einem Satz und dem Gerätenamen, das letzte Ergebnis je Gerät im Speicher des
// Browsers, das Mikrofon wird nach dem Test immer geschlossen, im Gespräch ist das Mikrofon während des Tests stumm.
// Mikrofon und Audio-APIs sind Attrappen, die Zeit läuft mit einer falschen Uhr.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({ getSupabase: () => null, accessToken: async () => null }));

import { SpracheAbschnitt } from "@/components/einstellungen/Abschnitte";
import { MikrofonTest, mikrofonOeffnen, type MikrofonQuelle } from "@/components/einstellungen/MikrofonTest";
import type { Mikrofon } from "@/lib/mikrofon";
import { RUHE_MS, SPRECHEN_MS, TEST_PRAEFIX } from "@/lib/mikrofonTest";
import { nutzerSetzen } from "@/lib/nutzer";
import { resetWamo, wamo } from "@/lib/wamo";

const ID = "0b7f3c1e-2d4a-4c55-9a10-1a2b3c4d5e6f";
const LISTE: Mikrofon[] = [
  { id: "a", label: "Mikrofonarray (Realtek)", standard: true },
  { id: "b", label: "Headset (USB)" },
];

/** Pegel (RMS linear) je Phase: still in der Ruhe, sprache beim Sprechen. */
let pegel = { ruhe: 0.001, sprache: 0.1 };
let beginn = 0;

function pegelJetzt(): number {
  return Date.now() - beginn < RUHE_MS ? pegel.ruhe : pegel.sprache;
}

function attrappe(label = "Headset (USB)") {
  const schliessen = vi.fn();
  const zustand = { getrennt: false };
  const oeffnen = vi.fn<(geraetId: string | null) => Promise<MikrofonQuelle>>(async () => {
    beginn = Date.now();
    return {
      label,
      lesen: () => {
        const rms = pegelJetzt();
        return { rms, spitzeDb: rms > 0 ? 20 * Math.log10(rms * 3) : Number.NEGATIVE_INFINITY };
      },
      getrennt: () => zustand.getrennt,
      schliessen,
    };
  });
  return { oeffnen, schliessen, zustand };
}

const laufen = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

/** Klick wie im Browser; mit der falschen Uhr über fireEvent, user-event wartete dort auf echte Zeit */
const klicken = (name: string) =>
  act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
  });

beforeEach(() => {
  vi.useFakeTimers();
  pegel = { ruhe: 0.001, sprache: 0.1 };
  resetWamo();
  localStorage.clear();
  nutzerSetzen({ id: ID, email: "niko@wamocon.com" });
});
afterEach(() => {
  vi.useRealTimers();
  nutzerSetzen({ id: null, email: null });
});

describe("Mikrofontest", () => {
  it("führt durch Ruhe und Sprechen und zeigt Ampel, Satz und Gerät; das Mikrofon ist danach zu", async () => {
    const { oeffnen, schliessen } = attrappe();
    render(<MikrofonTest geraetId="b" geraetName="Headset (USB)" oeffnen={oeffnen} />);
    await klicken("Mikrofon testen");
    expect(oeffnen).toHaveBeenCalledWith("b");
    await laufen(600);
    expect(screen.getByRole("status").textContent).toMatch(/Bitte still sein/);
    await laufen(RUHE_MS);
    expect(screen.getByRole("status").textContent).toMatch(/Jetzt sprechen/);
    expect(schliessen).not.toHaveBeenCalled();
    await laufen(SPRECHEN_MS);
    expect(schliessen).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Grün")).toBeTruthy();
    expect(screen.getByText("Gut: W.A.I.S. hört dich laut und deutlich.")).toBeTruthy();
    expect(screen.getByText(/Gemessen mit Headset \(USB\)/)).toBeTruthy();
    expect(screen.getByText(/Abstand/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Erneut testen" })).toBeTruthy();
    // gespeichert: nur das Ergebnis, je Person und Gerät
    const gespeichert = JSON.parse(localStorage.getItem(`${TEST_PRAEFIX}${ID}`) ?? "{}");
    expect(Object.keys(gespeichert)).toEqual(["headset (usb)"]);
    expect(gespeichert["headset (usb)"].bewertung).toBe("gut");
  });

  it("ein leises Mikrofon ist rot und sagt, was hilft", async () => {
    pegel = { ruhe: 0.0005, sprache: 0.005 };
    const { oeffnen } = attrappe("Mikrofonarray (Realtek)");
    render(<MikrofonTest geraetId={null} geraetName="Mikrofonarray (Realtek)" oeffnen={oeffnen} />);
    await klicken("Mikrofon testen");
    await laufen(RUHE_MS + SPRECHEN_MS + 100);
    expect(oeffnen).toHaveBeenCalledWith(null);
    expect(screen.getByText("Rot")).toBeTruthy();
    expect(screen.getByText(/^Zu leise:/)).toBeTruthy();
  });

  it("zeigt das letzte Ergebnis mit diesem Gerät, auch nach dem Neuladen", async () => {
    const { oeffnen } = attrappe();
    const erst = render(<MikrofonTest geraetId="b" geraetName="Headset (USB)" oeffnen={oeffnen} />);
    await klicken("Mikrofon testen");
    await laufen(RUHE_MS + SPRECHEN_MS + 100);
    erst.unmount();
    render(<MikrofonTest geraetId="b" geraetName="Standard - Headset (USB)" oeffnen={oeffnen} />);
    expect(screen.getByText(/Letzter Test mit diesem Mikrofon/)).toBeTruthy();
    expect(screen.getByText("Grün")).toBeTruthy();
  });

  it("Abbrechen schließt das Mikrofon, gemerkt wird nichts", async () => {
    const { oeffnen, schliessen } = attrappe();
    render(<MikrofonTest geraetId="b" geraetName="Headset (USB)" oeffnen={oeffnen} />);
    await klicken("Mikrofon testen");
    await laufen(RUHE_MS + 1000);
    await klicken("Abbrechen");
    expect(schliessen).toHaveBeenCalledTimes(1);
    await laufen(SPRECHEN_MS);
    expect(localStorage.getItem(`${TEST_PRAEFIX}${ID}`)).toBeNull();
    expect(screen.getByRole("button", { name: "Mikrofon testen" })).toBeTruthy();
  });

  it("verschwindet die Ansicht mitten im Test, schließt sich das Mikrofon", async () => {
    const { oeffnen, schliessen } = attrappe();
    const r = render(<MikrofonTest geraetId="b" geraetName="Headset (USB)" oeffnen={oeffnen} />);
    await klicken("Mikrofon testen");
    await laufen(1000);
    r.unmount();
    expect(schliessen).toHaveBeenCalledTimes(1);
  });

  it("Freigabe verweigert: ein Satz mit Abhilfe, kein Ergebnis", async () => {
    const oeffnen = vi.fn(async () => {
      throw Object.assign(new Error("nein"), { name: "NotAllowedError" });
    });
    render(<MikrofonTest geraetId={null} geraetName={null} oeffnen={oeffnen} />);
    await klicken("Mikrofon testen");
    await laufen(10);
    expect(screen.getByRole("alert").textContent).toMatch(/Mikrofon gesperrt/);
  });

  it("wird das Mikrofon getrennt, endet der Test mit einem Satz statt mit einem falschen Ergebnis", async () => {
    const { oeffnen, schliessen, zustand } = attrappe();
    render(<MikrofonTest geraetId="b" geraetName="Headset (USB)" oeffnen={oeffnen} />);
    await klicken("Mikrofon testen");
    await laufen(RUHE_MS + 500);
    zustand.getrennt = true;
    await laufen(100);
    expect(schliessen).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert").textContent).toMatch(/während des Tests getrennt/);
    expect(screen.queryByText("Rot")).toBeNull();
  });

  it("spricht W.A.I.S. während des Tests, ist der Test ungültig: kein Ergebnis, keine Ampel, nichts gemerkt, Mikrofon zu", async () => {
    // Wunsch vom 18.11.2026: einmal war das Ergebnis orange, weil W.A.I.S. dazwischen geredet hat
    const { oeffnen, schliessen } = attrappe();
    render(<MikrofonTest geraetId="b" geraetName="Headset (USB)" oeffnen={oeffnen} ausgabeAnhalten={vi.fn()} />);
    await klicken("Mikrofon testen");
    await laufen(1000);
    act(() => wamo.set((s) => ({ ...s, presence: "speaking" })));
    await laufen(100);
    expect(screen.getByRole("alert").textContent).toBe("W.A.I.S. hat gesprochen, bitte noch einmal testen.");
    expect(schliessen).toHaveBeenCalledTimes(1);
    expect(screen.queryAllByText(/^(Gelb|Grün|Rot)$/)).toHaveLength(0);
    expect(localStorage.getItem(`${TEST_PRAEFIX}${ID}`)).toBeNull();
    expect(screen.getByRole("button", { name: "Mikrofon testen" })).toBeTruthy();
  });

  it("spricht W.A.I.S. beim Start noch, wartet das Einschwingen, bis die Unterbrechung angekommen ist", async () => {
    const { oeffnen } = attrappe();
    act(() => wamo.set((s) => ({ ...s, presence: "speaking" })));
    render(<MikrofonTest geraetId="b" geraetName="Headset (USB)" oeffnen={oeffnen} ausgabeAnhalten={vi.fn()} />);
    await klicken("Mikrofon testen");
    await laufen(1500); // länger als das Einschwingen: es wartet
    expect(screen.queryByRole("alert")).toBeNull();
    act(() => wamo.set((s) => ({ ...s, presence: "idle" })));
    await laufen(RUHE_MS + SPRECHEN_MS + 100);
    // ein Ergebnis (die Attrappe liefert ihre Pegel nach der Uhr ab dem Öffnen, die Ampel zählt hier nicht), kein ungültiger Test
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("status").textContent).toMatch(/^Ergebnis des Mikrofontests: /);
  });

  it("verstummt W.A.I.S. auch nach der Wartezeit nicht, ist der Test ungültig", async () => {
    const { oeffnen } = attrappe();
    act(() => wamo.set((s) => ({ ...s, presence: "speaking" })));
    render(<MikrofonTest geraetId="b" geraetName="Headset (USB)" oeffnen={oeffnen} ausgabeAnhalten={vi.fn()} />);
    await klicken("Mikrofon testen");
    await laufen(3600);
    expect(screen.getByRole("alert").textContent).toBe("W.A.I.S. hat gesprochen, bitte noch einmal testen.");
  });

  it("Laborsicht (ohne ausgabeAnhalten) bleibt wie bisher: Spricht W.A.I.S., sagt das Ergebnis, dass es ungenau sein kann", async () => {
    const { oeffnen } = attrappe();
    render(<MikrofonTest geraetId="b" geraetName="Headset (USB)" oeffnen={oeffnen} merken={false} />);
    await klicken("Mikrofon testen");
    await laufen(1000);
    act(() => wamo.set((s) => ({ ...s, presence: "speaking" })));
    await laufen(RUHE_MS + SPRECHEN_MS);
    expect(screen.getByText(/W.A.I.S. hat während des Tests gesprochen/)).toBeTruthy();
  });

  it("Statuszeile und Fokus: die Zeile bleibt eingehängt und sagt das Ergebnis an, der Fokus geht zu Abbrechen und zurück", async () => {
    const { oeffnen } = attrappe();
    render(<MikrofonTest geraetId="b" geraetName="Headset (USB)" oeffnen={oeffnen} />);
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("");
    const knopf = screen.getByRole("button", { name: "Mikrofon testen" });
    knopf.focus();
    await klicken("Mikrofon testen");
    await laufen(100);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Abbrechen" }));
    await laufen(RUHE_MS + SPRECHEN_MS);
    expect(screen.getByRole("status")).toBe(status);
    expect(status.textContent).toBe("Ergebnis des Mikrofontests: Grün.");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Erneut testen" }));
  });

  it("ohne Speicher (Laborsicht) wird nichts gemerkt", async () => {
    const { oeffnen } = attrappe();
    render(<MikrofonTest geraetId="b" geraetName="Headset (USB)" oeffnen={oeffnen} merken={false} />);
    await klicken("Mikrofon testen");
    await laufen(RUHE_MS + SPRECHEN_MS + 100);
    expect(screen.getByText("Grün")).toBeTruthy();
    expect(localStorage.getItem(`${TEST_PRAEFIX}${ID}`)).toBeNull();
  });
});

describe("Mikrofontest im Gespräch", () => {
  /** wie toggleMic in useWamo: schaltet das Mikrofon des Gesprächs um */
  let umschalten: ReturnType<typeof vi.fn<() => void>>;
  beforeEach(() => {
    umschalten = vi.fn<() => void>(() => wamo.set((s) => ({ ...s, micOn: !s.micOn })));
  });

  it("das Mikrofon des Gesprächs ist während des Tests stumm und danach wieder an", async () => {
    act(() => wamo.set((s) => ({ ...s, presence: "idle", micOn: true })));
    const { oeffnen } = attrappe();
    render(<MikrofonTest geraetId="b" geraetName="Headset (USB)" oeffnen={oeffnen} mikrofonUmschalten={umschalten} />);
    expect(screen.getByText(/Während des Tests ist dein Mikrofon im Gespräch stumm/)).toBeTruthy();
    await klicken("Mikrofon testen");
    expect(wamo.get().micOn).toBe(false);
    await laufen(RUHE_MS + SPRECHEN_MS + 100);
    expect(umschalten).toHaveBeenCalledTimes(2);
    expect(wamo.get().micOn).toBe(true);
  });

  it("im Gespräch schweigt W.A.I.S. während des Tests: Wiedergabe angehalten und danach wieder frei", async () => {
    act(() => wamo.set((s) => ({ ...s, presence: "idle", micOn: true })));
    const { oeffnen } = attrappe();
    const ausgabe = vi.fn<(an: boolean) => void>();
    render(
      <MikrofonTest geraetId="b" geraetName="Headset (USB)" oeffnen={oeffnen} mikrofonUmschalten={umschalten} ausgabeAnhalten={ausgabe} />,
    );
    expect(screen.getByText(/W.A.I.S. schweigt/)).toBeTruthy();
    await klicken("Mikrofon testen");
    expect(ausgabe.mock.calls).toEqual([[true]]);
    await laufen(RUHE_MS + SPRECHEN_MS + 100);
    expect(ausgabe.mock.calls).toEqual([[true], [false]]);
    expect(screen.getByText("Grün")).toBeTruthy();
  });

  it("ohne Gespräch hält der Test keine Wiedergabe an; Abbrechen gibt sie wieder frei", async () => {
    const { oeffnen } = attrappe();
    const ausgabe = vi.fn<(an: boolean) => void>();
    const r = render(<MikrofonTest geraetId="b" geraetName="Headset (USB)" oeffnen={oeffnen} ausgabeAnhalten={ausgabe} />);
    await klicken("Mikrofon testen");
    await laufen(RUHE_MS + SPRECHEN_MS + 100);
    expect(ausgabe).not.toHaveBeenCalled();
    r.unmount();
    act(() => wamo.set((s) => ({ ...s, presence: "idle" })));
    render(<MikrofonTest geraetId="b" geraetName="Headset (USB)" oeffnen={oeffnen} ausgabeAnhalten={ausgabe} />);
    await klicken("Mikrofon testen");
    await laufen(1000);
    await klicken("Abbrechen");
    expect(ausgabe.mock.calls).toEqual([[true], [false]]);
  });

  it("ein schon stummes oder still gestartetes Gespräch bleibt, wie es ist", async () => {
    const { oeffnen } = attrappe();
    act(() => wamo.set((s) => ({ ...s, presence: "idle", micOn: false })));
    const r = render(<MikrofonTest geraetId="b" geraetName="Headset (USB)" oeffnen={oeffnen} mikrofonUmschalten={umschalten} />);
    await klicken("Mikrofon testen");
    await laufen(RUHE_MS + SPRECHEN_MS + 100);
    r.unmount();
    act(() => wamo.set((s) => ({ ...s, micOn: true, stillStart: { still: true, perTippen: true, uebernommen: false } })));
    render(<MikrofonTest geraetId="b" geraetName="Headset (USB)" oeffnen={oeffnen} mikrofonUmschalten={umschalten} />);
    await klicken("Mikrofon testen");
    await laufen(RUHE_MS + SPRECHEN_MS + 100);
    expect(umschalten).not.toHaveBeenCalled();
  });
});

describe("Mikrofon öffnen", () => {
  type Global = { AudioContext?: unknown };
  let stopp: ReturnType<typeof vi.fn>;
  let zu: ReturnType<typeof vi.fn>;
  let getUserMedia: ReturnType<typeof vi.fn>;
  let laufend = true;

  beforeEach(() => {
    laufend = true;
    stopp = vi.fn();
    zu = vi.fn(() => Promise.resolve());
    getUserMedia = vi.fn(async () => ({ getTracks: () => [{ stop: stopp }], getAudioTracks: () => [{ label: "Headset (USB)", stop: stopp }] }));
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia, addEventListener: vi.fn(), removeEventListener: vi.fn() } });
    (globalThis as unknown as Global).AudioContext = class {
      state = laufend ? "running" : "suspended";
      createAnalyser() {
        return { fftSize: 2048, getFloatTimeDomainData: (b: Float32Array) => b.fill(0.1) };
      }
      createMediaStreamSource() {
        return { connect: () => undefined };
      }
      resume() {
        return Promise.resolve();
      }
      close = zu;
    };
  });
  afterEach(() => {
    delete (globalThis as unknown as Global).AudioContext;
  });

  it("öffnet das gewählte Gerät mit denselben Einstellungen wie im Gespräch und schließt alles wieder", async () => {
    const q = await mikrofonOeffnen("b");
    expect(getUserMedia).toHaveBeenCalledWith({ audio: { deviceId: { exact: "b" } } });
    expect(q.label).toBe("Headset (USB)");
    expect(Math.round(q.lesen().rms * 10) / 10).toBe(0.1);
    q.schliessen();
    expect(stopp).toHaveBeenCalled();
    expect(zu).toHaveBeenCalled();
    await mikrofonOeffnen(null);
    expect(getUserMedia).toHaveBeenLastCalledWith({ audio: true });
  });

  it("ein angehaltener Audiokontext misst nicht: ehrlicher Fehler statt 'Kein Ton', alles wieder zu", async () => {
    laufend = false;
    await expect(mikrofonOeffnen("b")).rejects.toMatchObject({ name: "MessungAngehalten" });
    expect(stopp).toHaveBeenCalled();
    expect(zu).toHaveBeenCalled();
  });

  it("in Sprache und Ton, Block Eingabe, auch in der Laborsicht", async () => {
    render(<SpracheAbschnitt mikrofone={async () => LISTE} mikrofonWaehlen={() => true} nurMikrofon />);
    await act(async () => undefined);
    expect(screen.getByRole("button", { name: "Mikrofon testen" })).toBeTruthy();
  });
});
