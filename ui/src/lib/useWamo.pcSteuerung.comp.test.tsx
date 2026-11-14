// Komponententest des Ablaufs "PC-Steuerung ohne Gespräch einschalten" in useWamo (lib/pcSchalter.ts): Ein Klick auf "an" ohne Sitzung
// startet in der Desktop-App still eine Sitzung (Regeln des stillen Starts), schickt den Wunsch, sobald der Kern den PC als verbunden
// meldet, und nennt nach der Wartezeit den Grund, wenn es nicht klappt. Mitglieder, Laborkonten und der normale Browser starten nichts.
// Pipecat-Client und Transport sind Attrappen, der Kern wird über Rückrufe und Betriebsmeldungen nachgestellt; es gibt kein Netz.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Rueckrufe = Record<string, (...a: unknown[]) => void>;
type AttrappenClient = {
  opts: { enableMic: boolean; callbacks: Rueckrufe };
  sendClientMessage: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
};

const h = vi.hoisted(() => {
  (URL as unknown as { createObjectURL: (b: unknown) => string }).createObjectURL = () => "blob:wamo-test";
  return { clients: [] as unknown[], start: null as null | (() => Promise<void>) };
});

vi.mock("@pipecat-ai/client-js", () => {
  class RTVIError extends Error {
    status?: number;
  }
  class PipecatClient {
    opts: unknown;
    sendText = vi.fn().mockResolvedValue(undefined);
    enableMic = vi.fn();
    updateMic = vi.fn();
    sendClientMessage = vi.fn();
    disconnect = vi.fn().mockResolvedValue(undefined);
    startBotAndConnect = vi.fn(() => (h.start ? h.start() : Promise.resolve()));
    get transport() {
      return (this.opts as { transport: unknown }).transport;
    }
    constructor(opts: unknown) {
      this.opts = opts;
      h.clients.push(this);
    }
  }
  return { PipecatClient, RTVIError };
});
vi.mock("@pipecat-ai/small-webrtc-transport", () => {
  class WavMediaManager {}
  class SmallWebRTCTransport {
    opts: unknown;
    constructor(opts: unknown) {
      this.opts = opts;
    }
  }
  return { SmallWebRTCTransport, WavMediaManager };
});
vi.mock("@/lib/betriebsart", async (orig) => ({
  ...(await orig<typeof import("@/lib/betriebsart")>()),
  betriebsartFuerStart: async () => "buero",
  kernUrl: () => "https://kern.test",
}));
vi.mock("@/lib/kernSlot", async (orig) => ({ ...(await orig<typeof import("@/lib/kernSlot")>()), aktiverSlot: async () => null }));
vi.mock("@/lib/supabase", () => ({ getSupabase: () => null, accessToken: async () => null }));

import type { Betrieb } from "@/lib/nachrichten";
import { nutzerSetzen } from "@/lib/nutzer";
import {
  HINWEIS_NICHT_BESTAETIGT,
  HINWEIS_PC_AUS,
  HINWEIS_PC_GETRENNT,
  HINWEIS_STILL_AUS,
  PC_EIN_LEER,
  PC_VERBINDEN_MS,
  SCHALT_WARTEN_MS,
} from "@/lib/pcSchalter";
import { HINWEIS_ANDERES_FENSTER, STILL_AUS } from "@/lib/stillStart";
import { useWamo } from "@/lib/useWamo";
import { applyServerMessage, resetWamo, wamo } from "@/lib/wamo";

const ID = "0b7f3c1e-2d4a-4c55-9a10-1a2b3c4d5e6f";
type Fenster = { wamoDesktop?: unknown };
const clients = () => h.clients as AttrappenClient[];
const letzter = () => clients()[clients().length - 1];
const aktuell = () => wamo.get();
const pcGesendet = (c: AttrappenClient) => c.sendClientMessage.mock.calls.filter((a) => a[0] === "pc_steuerung");

const fluss = (ms = 10) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

function person(email = "niko@wamocon.com", gemerkt: "admin" | "mitglied" | null = "admin") {
  nutzerSetzen({ id: ID, email });
  if (gemerkt) localStorage.setItem(`wamo.rolle.${ID}`, gemerkt);
}

/** Der Kern meldet "Bot bereit", das Profil und die Betriebsdaten. */
async function bereit(c: AttrappenClient, betrieb: Partial<Betrieb>) {
  await act(async () => {
    c.opts.callbacks.onBotReady({ version: "2.0.0" });
    applyServerMessage({ type: "profil", name: "Niko", rolle: "admin" });
    wamo.set((s) => ({ ...s, betrieb: { modus: "buero", modelle: {}, pc: "verbindet", pcSteuerung: "aus", ...betrieb } }));
  });
}

async function betriebNeu(b: Partial<Betrieb>) {
  await act(async () => {
    wamo.set((s) => ({ ...s, betrieb: s.betrieb ? { ...s.betrieb, ...b } : null }));
  });
}

/** Klick auf "an" ohne Sitzung, dann bis zur Betriebsmeldung des Kerns. */
async function klickUndBereit(betrieb: Partial<Betrieb>) {
  const r = renderHook(() => useWamo());
  let gesendet = false;
  await act(async () => {
    gesendet = r.result.current.pcSteuerung(true);
  });
  expect(gesendet).toBe(true);
  await fluss();
  await bereit(letzter(), betrieb);
  return r;
}

describe("useWamo, PC-Steuerung ohne Gespräch einschalten", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    h.clients.length = 0;
    h.start = null;
    resetWamo();
    localStorage.clear();
    nutzerSetzen({ id: null, email: null });
    // Brücke der Desktop-App (preload.js): nur, was useWamo hier ruft; levels gibt es dort immer
    (window as unknown as Fenster).wamoDesktop = { isDesktop: true, levels: () => undefined };
  });
  afterEach(() => {
    delete (window as unknown as Fenster).wamoDesktop;
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("Klick auf 'an': startet still (ohne Mikrofon), wartet auf den PC, schickt den Wunsch einmal, sobald er verbunden ist", async () => {
    person();
    const { result } = renderHook(() => useWamo());
    await act(async () => {
      expect(result.current.pcSteuerung(true)).toBe(true);
    });
    expect(aktuell().presence).toBe("connecting");
    expect(aktuell().stillStart.still).toBe(true);
    expect(aktuell().pcEinschalten.wartet).toBe(true);
    await fluss();
    const c = letzter();
    expect(clients()).toHaveLength(1);
    expect(c.opts.enableMic).toBe(false);

    await bereit(c, { pc: "verbindet" });
    expect(pcGesendet(c)).toHaveLength(0); // der PC ist noch nicht da
    await fluss(2000);
    await betriebNeu({ pc: "verbunden", pcName: "WMC-H-04-NS" });
    expect(pcGesendet(c)).toEqual([["pc_steuerung", { an: true }]]);
    await betriebNeu({ pcLatenzMs: 12 }); // weitere Meldungen schicken nichts doppelt
    expect(pcGesendet(c)).toHaveLength(1);

    await betriebNeu({ pcSteuerung: "an" });
    expect(aktuell().pcEinschalten).toEqual(PC_EIN_LEER);
    await fluss(PC_VERBINDEN_MS + SCHALT_WARTEN_MS);
    expect(aktuell().error).toBeNull(); // kein Hinweis, es hat geklappt
    expect(aktuell().presence).toBe("idle"); // die Sitzung bleibt
  });

  it("PC nicht erreichbar: nach der Wartezeit ein Hinweis mit dem Grund, am Schalter und in der Hauptansicht", async () => {
    person();
    await klickUndBereit({ pc: "verbindet" });
    await betriebNeu({ pc: "getrennt" });
    await fluss(PC_VERBINDEN_MS - 1000);
    expect(aktuell().pcEinschalten.wartet).toBe(true);
    expect(aktuell().error).toBeNull();
    await fluss(1500);
    expect(aktuell().pcEinschalten).toEqual({ wartet: false, hinweis: HINWEIS_PC_GETRENNT });
    expect(aktuell().error).toEqual({ art: "hinweis", text: HINWEIS_PC_GETRENNT });
    expect(pcGesendet(letzter())).toHaveLength(0);
  });

  it("Kern bestätigt nicht: nach der Wartezeit des Schalters ein Hinweis", async () => {
    person();
    await klickUndBereit({ pc: "verbunden" });
    expect(pcGesendet(letzter())).toHaveLength(1);
    await fluss(SCHALT_WARTEN_MS + 100);
    expect(aktuell().pcEinschalten).toEqual({ wartet: false, hinweis: HINWEIS_NICHT_BESTAETIGT });
    expect(aktuell().error?.text).toBe(HINWEIS_NICHT_BESTAETIGT);
  });

  it("Sitzung ohne PC-Host: sofort ein klarer Hinweis, nichts gesendet", async () => {
    person();
    await klickUndBereit({ pc: "aus" });
    expect(aktuell().pcEinschalten).toEqual({ wartet: false, hinweis: HINWEIS_PC_AUS });
    expect(pcGesendet(letzter())).toHaveLength(0);
  });

  it("Start scheitert: der Wunsch verfällt still, es bleibt die Meldung der Verbindung", async () => {
    person();
    h.start = () => Promise.reject(new Error("weg"));
    const { result } = renderHook(() => useWamo());
    await act(async () => {
      result.current.pcSteuerung(true);
    });
    await fluss();
    expect(aktuell().presence).toBe("offline");
    expect(aktuell().error?.art).toBe("verbindung");
    expect(aktuell().pcEinschalten).toEqual(PC_EIN_LEER);
  });

  it("ein späteres 'Gespräch starten' schaltet nach einem verfallenen Wunsch nichts ein", async () => {
    person();
    const r = await klickUndBereit({ pc: "verbindet" });
    await act(async () => r.result.current.disconnect());
    expect(aktuell().pcEinschalten).toEqual(PC_EIN_LEER);
    await act(async () => {
      void r.result.current.connect();
      await vi.advanceTimersByTimeAsync(10);
    });
    await bereit(letzter(), { pc: "verbunden" });
    await fluss(1000);
    expect(pcGesendet(letzter())).toHaveLength(0);
  });

  it("während des Verbindens (zum Beispiel nach dem Tippen) genügt der Wunsch: kein zweiter Start", async () => {
    person();
    const { result } = renderHook(() => useWamo());
    expect(result.current.stillStarten?.()).toBe(true);
    await act(async () => {
      expect(result.current.pcSteuerung(true)).toBe(true);
    });
    await fluss();
    expect(clients()).toHaveLength(1);
    await bereit(letzter(), { pc: "verbunden" });
    expect(pcGesendet(letzter())).toHaveLength(1);
  });

  it("'aus' ohne Sitzung: nichts zu tun, keine Sitzung", async () => {
    person();
    const { result } = renderHook(() => useWamo());
    let r = false;
    await act(async () => {
      r = result.current.pcSteuerung(false);
    });
    expect(r).toBe(true);
    await fluss();
    expect(clients()).toHaveLength(0);
    expect(aktuell().presence).toBe("offline");
  });

  it("mit laufender Sitzung bleibt es wie bisher: sofort senden", async () => {
    person();
    const { result } = renderHook(() => useWamo());
    await act(async () => {
      void result.current.connect();
      await vi.advanceTimersByTimeAsync(10);
    });
    await bereit(letzter(), { pc: "verbunden" });
    await act(async () => {
      expect(result.current.pcSteuerung(true)).toBe(true);
    });
    expect(pcGesendet(letzter())).toEqual([["pc_steuerung", { an: true }]]);
    expect(aktuell().pcEinschalten).toEqual(PC_EIN_LEER);
  });

  describe("Sperren", () => {
    it("Geräteschalter 'Still starten beim Tippen' aus: kein Start, der Hinweis nennt den Weg", async () => {
      person();
      localStorage.setItem(`wamo.stillStart.${ID}`, "aus");
      const { result } = renderHook(() => useWamo());
      let r = true;
      await act(async () => {
        r = result.current.pcSteuerung(true);
      });
      expect(r).toBe(false);
      await fluss();
      expect(clients()).toHaveLength(0);
      expect(aktuell().pcEinschalten).toEqual({ wartet: false, hinweis: HINWEIS_STILL_AUS });
    });

    it("Übernahme durch ein anderes Fenster: kein Start, kein Verdrängen", async () => {
      person();
      wamo.set((s) => ({ ...s, stillStart: { ...STILL_AUS, uebernommen: true } }));
      const { result } = renderHook(() => useWamo());
      await act(async () => {
        expect(result.current.pcSteuerung(true)).toBe(false);
      });
      await fluss();
      expect(clients()).toHaveLength(0);
      expect(aktuell().error?.text).toBe(HINWEIS_ANDERES_FENSTER);
    });

    it("Laborkonto: nie, auch mit gemerkter Admin-Rolle", async () => {
      person("labor-05@wamo.test", "admin");
      const { result } = renderHook(() => useWamo());
      await act(async () => {
        expect(result.current.pcSteuerung(true)).toBe(false);
      });
      await fluss();
      expect(clients()).toHaveLength(0);
    });

    it("Mitglied (gemerkte Rolle) und unbekannte Rolle: kein Start", async () => {
      for (const gemerkt of ["mitglied", null] as const) {
        localStorage.clear();
        person("niko@wamocon.com", gemerkt);
        const { result, unmount } = renderHook(() => useWamo());
        await act(async () => {
          expect(result.current.pcSteuerung(true)).toBe(false);
        });
        await fluss();
        expect(clients()).toHaveLength(0);
        unmount();
      }
    });

    it("normaler Browser (keine Desktop-App): ohne Gespräch kein Start", async () => {
      delete (window as unknown as Fenster).wamoDesktop;
      person();
      const { result } = renderHook(() => useWamo());
      await act(async () => {
        expect(result.current.pcSteuerung(true)).toBe(false);
      });
      await fluss();
      expect(clients()).toHaveLength(0);
    });
  });

  it("die Rolle, die der Kern meldet, merkt sich die Oberfläche je Person (für den Schalter ohne Sitzung)", async () => {
    person("niko@wamocon.com", null);
    renderHook(() => useWamo());
    await act(async () => {
      applyServerMessage({ type: "profil", name: "Niko", rolle: "admin" });
    });
    expect(localStorage.getItem(`wamo.rolle.${ID}`)).toBe("admin");
    await act(async () => {
      applyServerMessage({ type: "profil", name: "Niko", rolle: "mitglied" });
    });
    expect(localStorage.getItem(`wamo.rolle.${ID}`)).toBe("mitglied");
  });
});
