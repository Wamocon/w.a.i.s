// Komponententest der Mikrofonkette im Protokoll (19.11.2026, lib/mikrofonKette.ts, Verdrahtung in useWamo.eigeneSpur): Nach jeder neuen eigenen
// Mikrofonspur geht dem Kern genau eine Nachricht mikrofon_info mit sechs Feldern, erst nach der Betriebsmeldung, höchstens einmal je Änderung,
// nie mit dem Gerätenamen und nie für ein Laborkonto. Pipecat-Client, Transport und Audio-APIs sind Attrappen, es gibt kein Netz und kein Mikrofon.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Rueckrufe = Record<string, (...a: unknown[]) => void>;
type AttrappenClient = {
  opts: { transport: { opts: { mediaManager: unknown } }; callbacks: Rueckrufe };
  sendClientMessage: ReturnType<typeof vi.fn>;
};

const h = vi.hoisted(() => {
  (URL as unknown as { createObjectURL: (b: unknown) => string }).createObjectURL = () => "blob:wamo-test";
  const zustand = { clients: [] as unknown[], supabase: null as unknown };
  // Audio-APIs für den eigenen Pegel (useWamo misst selbst mit einem AnalyserNode)
  class Analyser {
    fftSize = 2048;
    getFloatTimeDomainData(buf: Float32Array) {
      buf.fill(0.1);
    }
  }
  class FalscherAudioContext {
    state = "running";
    createAnalyser() {
      return new Analyser();
    }
    createMediaStreamSource() {
      return { connect: () => undefined };
    }
    resume() {
      return Promise.resolve();
    }
    close() {
      return Promise.resolve();
    }
  }
  (globalThis as unknown as { AudioContext: unknown }).AudioContext = FalscherAudioContext;
  (globalThis as unknown as { MediaStream: unknown }).MediaStream = class {
    constructor(public spuren: unknown[]) {}
  };
  return zustand;
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
    startBotAndConnect = vi.fn(() => Promise.resolve());
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
  class Recorder {
    listenForDeviceErrors = vi.fn();
    begin = vi.fn(async () => true);
  }
  class WavMediaManager {
    _wavRecorder = new Recorder();
    async initialize() {
      await this._wavRecorder.begin().catch(() => undefined);
    }
  }
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
const slot = vi.hoisted(() => ({ aktiverSlot: vi.fn(async () => null) }));
vi.mock("@/lib/kernSlot", async (orig) => ({ ...(await orig<typeof import("@/lib/kernSlot")>()), aktiverSlot: slot.aktiverSlot }));
vi.mock("@/lib/supabase", () => ({ getSupabase: () => h.supabase, accessToken: async () => null }));

import { nutzerSetzen } from "@/lib/nutzer";
import { useWamo } from "@/lib/useWamo";
import { resetWamo, wamo } from "@/lib/wamo";

const NUTZER = "0b7f3c1e-2d4a-4c55-9a10-1a2b3c4d5e6f";
const clients = () => h.clients as AttrappenClient[];
const letzter = () => clients()[clients().length - 1];
const aktuell = () => wamo.get();

const fluss = (ms = 10) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

const EINSTELLUNGEN = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
  sampleRate: 48000,
  channelCount: 1,
  deviceId: "geheime-kennung-1",
};
const spur = (label = "Webcam-Mikrofon", getSettings: () => unknown = () => EINSTELLUNGEN) => ({
  kind: "audio",
  label,
  addEventListener: vi.fn(),
  getSettings,
});

const meldungen = (c: AttrappenClient) => c.sendClientMessage.mock.calls.filter((a) => a[0] === "mikrofon_info");
const klassen = (c: AttrappenClient) => meldungen(c).map((m) => m[1].klasse);

/** Verbinden und "Bot bereit", aber noch ohne Betriebsmeldung (so beginnt jedes Gespräch). */
async function verbinden() {
  const r = renderHook(() => useWamo());
  await act(async () => {
    void r.result.current.connect();
  });
  await fluss();
  const c = letzter();
  await act(async () => {
    c.opts.callbacks.onBotReady({ version: "2.0.0" });
  });
  return { r, c };
}
const betrieb = () => act(async () => wamo.set((s) => ({ ...s, betrieb: { modus: "buero", modelle: {}, pc: "aus" } })));
const spurStart = (c: AttrappenClient, s: unknown) => act(async () => c.opts.callbacks.onTrackStarted(s, { local: true }));

beforeEach(() => {
  vi.useFakeTimers();
  h.clients.length = 0;
  h.supabase = null;
  slot.aktiverSlot.mockClear();
  resetWamo();
  localStorage.clear();
  nutzerSetzen({ id: NUTZER, email: "niko@wamocon.com" });
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("Mikrofonkette im Protokoll", () => {
  it("die Spur kommt vor der Betriebsmeldung: sie wartet und geht danach genau einmal hinaus, mit sechs Feldern", async () => {
    const { c } = await verbinden();
    await spurStart(c, spur("Headset (AirPods Pro)"));
    expect(meldungen(c)).toHaveLength(0); // der Kern ist noch nicht bereit
    await betrieb();
    expect(meldungen(c)).toHaveLength(1);
    expect(meldungen(c)[0]).toEqual([
      "mikrofon_info",
      { echo: true, rauschen: true, verstaerkung: true, rate: 48000, kanaele: 1, klasse: "bluetooth" },
    ]);
    await act(async () => wamo.set((s) => ({ ...s, ansage: "anderes" }))); // weitere Änderungen im Speicher senden nichts mehr
    await betrieb();
    expect(meldungen(c)).toHaveLength(1);
  });

  it("nie der Name oder die Kennung des Geräts in der Nachricht", async () => {
    const { c } = await verbinden();
    await betrieb();
    await spurStart(c, spur("Sony WH-1000XM4 von Erika (Bluetooth)"));
    const text = JSON.stringify(meldungen(c));
    expect(text).toContain("bluetooth");
    for (const name of ["Sony", "WH-1000", "Erika", "geheime-kennung"]) expect(text).not.toContain(name);
  });

  it("die Spur kommt nach der Betriebsmeldung: sofort, auch ein Gerätewechsel, je Wechsel eine Nachricht", async () => {
    const { c } = await verbinden();
    await betrieb();
    await spurStart(c, spur("Mikrofonarray (Intel Smart Sound)"));
    expect(klassen(c)).toEqual(["eingebaut"]);
    await spurStart(c, spur("Headset (AirPods Pro)"));
    expect(klassen(c)).toEqual(["eingebaut", "bluetooth"]);
    await spurStart(c, spur("Mikrofonarray (Intel Smart Sound)")); // zurück
    expect(klassen(c)).toEqual(["eingebaut", "bluetooth", "eingebaut"]);
  });

  it("dieselbe Spur noch einmal oder eine neue Spur desselben Geräts mit derselben Kette sendet nichts", async () => {
    const { c } = await verbinden();
    await betrieb();
    const s = spur("Headset (AirPods Pro)");
    await spurStart(c, s);
    await spurStart(c, s); // Mikrofon aus und wieder an meldet dieselbe Spur noch einmal
    await spurStart(c, spur("Headset (AirPods Pro)")); // neue Spur, gleiche Kette
    expect(meldungen(c)).toHaveLength(1);
  });

  it("zwei Spuren vor der Betriebsmeldung: gesendet wird nur die jüngste", async () => {
    const { c } = await verbinden();
    await spurStart(c, spur("Mikrofonarray (Intel Smart Sound)"));
    await spurStart(c, spur("Headset (AirPods Pro)"));
    await betrieb();
    expect(klassen(c)).toEqual(["bluetooth"]);
  });

  it("fehlt etwas oder wirft getSettings, ist das Feld null und die Nachricht geht trotzdem", async () => {
    const { c } = await verbinden();
    await betrieb();
    await spurStart(
      c,
      spur("Headset (AirPods Pro)", () => {
        throw new Error("kaputt");
      }),
    );
    expect(meldungen(c)[0][1]).toEqual({ echo: null, rauschen: null, verstaerkung: null, rate: null, kanaele: null, klasse: "bluetooth" });
    await spurStart(c, spur("Mikrofonarray (Intel Smart Sound)", () => ({ sampleRate: 48000 })));
    expect(meldungen(c)[1][1]).toEqual({ echo: null, rauschen: null, verstaerkung: null, rate: 48000, kanaele: null, klasse: "eingebaut" });
  });

  it("ein Laborkonto sendet nie (auch nicht nach der Betriebsmeldung)", async () => {
    nutzerSetzen({ id: NUTZER, email: "labor-03@wamo.test" });
    const { c } = await verbinden();
    await spurStart(c, spur("Headset (AirPods Pro)"));
    await betrieb();
    await spurStart(c, spur("Mikrofonarray (Intel Smart Sound)"));
    expect(meldungen(c)).toHaveLength(0);
  });

  it("scheitert das Senden, gibt es keinen Absturz, keine Fehlermeldung und keine Wiederholung", async () => {
    const { c } = await verbinden();
    c.sendClientMessage.mockImplementation(() => {
      throw new Error("Verbindung weg");
    });
    await betrieb();
    await spurStart(c, spur("Headset (AirPods Pro)"));
    expect(meldungen(c)).toHaveLength(1); // versucht, aber nur einmal
    await act(async () => wamo.set((s) => ({ ...s, ansage: "x" })));
    await act(async () => wamo.set((s) => ({ ...s, ansage: "y" })));
    expect(meldungen(c)).toHaveLength(1); // versucht, aber nur einmal
    expect(aktuell().error).toBeNull();
  });

  it("eine neue Verbindung meldet die Kette noch einmal (der Kern fängt je Sitzung neu an)", async () => {
    const { r, c } = await verbinden();
    await betrieb();
    await spurStart(c, spur("Headset (AirPods Pro)"));
    expect(meldungen(c)).toHaveLength(1);
    await act(async () => {
      await r.result.current.disconnect();
    });
    await act(async () => {
      void r.result.current.connect();
    });
    await fluss();
    const c2 = letzter();
    await act(async () => c2.opts.callbacks.onBotReady({ version: "2.0.0" }));
    await spurStart(c2, spur("Headset (AirPods Pro)"));
    await betrieb();
    expect(meldungen(c2)).toHaveLength(1);
    expect(meldungen(c)).toHaveLength(1);
  });

  it("nach dem Trennen: eine wartende Meldung und die Spur eines alten Clients erreichen niemanden mehr", async () => {
    const { r, c } = await verbinden();
    await spurStart(c, spur("Headset (AirPods Pro)")); // wartet auf die Betriebsmeldung
    await act(async () => {
      await r.result.current.disconnect();
    });
    await betrieb();
    await spurStart(c, spur("Mikrofonarray (Intel Smart Sound)")); // verspätete Spur des alten Clients
    expect(meldungen(c)).toHaveLength(0);
  });

  it("ein Laborkonto bekommt keinen Melder: auch ein späterer Wechsel auf ein Nicht-Laborkonto in derselben Sitzung sendet nichts mehr", async () => {
    nutzerSetzen({ id: NUTZER, email: "labor-schau@wamo.test" });
    const { c } = await verbinden();
    await betrieb();
    nutzerSetzen({ id: NUTZER, email: "niko@wamocon.com" }); // ändert nichts an der laufenden Verbindung
    await spurStart(c, spur("Headset (AirPods Pro)"));
    expect(meldungen(c)).toHaveLength(0);
  });

  it("viele Änderungen im Speicher lösen keine weitere Meldung aus (keine Schleife, kein Flackern)", async () => {
    const { c } = await verbinden();
    await betrieb();
    await spurStart(c, spur("Headset (AirPods Pro)"));
    for (let i = 0; i < 30; i += 1) await act(async () => wamo.set((s) => ({ ...s, ansage: `a${i}` })));
    expect(meldungen(c)).toHaveLength(1);
  });
});
