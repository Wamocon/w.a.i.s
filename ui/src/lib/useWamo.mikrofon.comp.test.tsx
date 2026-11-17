// Komponententest der Mikrofonwahl und der Pegelwarnung in useWamo (Befunde 17.11.2026): Der Gesprächsstart öffnet das Mikrofon, das die
// Person auf diesem Gerät gewählt hat (lib/mikrofon.ts, lib/geraeteMedien.ts), fehlt es, gilt das Standardgerät mit kurzem Hinweis; ein
// Wechsel im Gespräch geht über PipecatClient.updateMic; ein sehr leises Mikrofon beim Sprechen bekommt einmal je Gespräch einen Hinweis
// (lib/pegelWarnung.ts), nie während W.A.I.S. spricht; ohne Anmeldung schickt die Oberfläche kein /start.
// Pipecat-Client, Transport und Audio-APIs sind Attrappen, es gibt kein Netz und kein Mikrofon.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Rueckrufe = Record<string, (...a: unknown[]) => void>;
type Recorder = { begin: ReturnType<typeof vi.fn>; listenForDeviceErrors: ReturnType<typeof vi.fn> };
type Manager = { initialize: () => Promise<void>; mikrofonErsatz: boolean; _wavRecorder: Recorder };
type AttrappenClient = {
  opts: { transport: { opts: { mediaManager: Manager } }; callbacks: Rueckrufe };
  updateMic: ReturnType<typeof vi.fn>;
  startBotAndConnect: ReturnType<typeof vi.fn>;
};

const h = vi.hoisted(() => {
  (URL as unknown as { createObjectURL: (b: unknown) => string }).createObjectURL = () => "blob:wamo-test";
  const zustand = {
    clients: [] as unknown[],
    /** das gewählte Gerät fehlt (getUserMedia mit deviceId exact scheitert) */
    fehlt: false,
    /** Abtastwert des eigenen Mikrofons (konstant): 0,005 ist sehr leise (Anzeige 0,01), 0,1 normale Sprache (Anzeige 0,2) */
    pegel: 0.005,
    supabase: null as unknown,
  };
  // Audio-APIs für den eigenen Pegel (useWamo misst selbst mit einem AnalyserNode)
  class Analyser {
    fftSize = 2048;
    getFloatTimeDomainData(buf: Float32Array) {
      buf.fill(zustand.pegel);
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
  // Recorder wie in der Bibliothek: begin(id) öffnet genau dieses Gerät, ein Fehler geht vorher an den Empfänger von listenForDeviceErrors
  class Recorder {
    empfaenger: ((e: unknown) => void) | null = null;
    stream = null;
    listenForDeviceErrors = vi.fn((f: ((e: unknown) => void) | null) => {
      this.empfaenger = f;
    });
    begin = vi.fn(async (id?: string) => {
      if (id && h.fehlt) {
        this.empfaenger?.({ devices: ["mic"], type: "unknown", error: { name: "OverconstrainedError" } });
        throw new Error("Could not start media stream");
      }
      return true;
    });
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

import { GeraeteMedienManager } from "@/lib/geraeteMedien";
import { MIKROFON_ERSATZ_TEXT, MIKROFON_STANDARD } from "@/lib/mikrofon";
import { nutzerSetzen } from "@/lib/nutzer";
import { LEISE_TEXT } from "@/lib/pegelWarnung";
import { OHNE_ANMELDUNG, useWamo } from "@/lib/useWamo";
import { resetWamo, wamo } from "@/lib/wamo";

const NUTZER = "0b7f3c1e-2d4a-4c55-9a10-1a2b3c4d5e6f";
const ANDERE = "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b";
const clients = () => h.clients as AttrappenClient[];
const letzter = () => clients()[clients().length - 1];
const aktuell = () => wamo.get();
const manager = () => letzter().opts.transport.opts.mediaManager;

const fluss = (ms = 10) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

const spur = (label = "Webcam-Mikrofon") => ({ kind: "audio", label, addEventListener: vi.fn(), getSettings: () => ({}) });

/** Gespräch starten, "Bot bereit" und Betriebsdaten melden. */
async function gespraech() {
  const r = renderHook(() => useWamo());
  await act(async () => {
    void r.result.current.connect();
  });
  await fluss();
  const c = letzter();
  await act(async () => {
    c.opts.callbacks.onBotReady({ version: "2.0.0" });
    wamo.set((s) => ({ ...s, betrieb: { modus: "buero", modelle: {}, pc: "aus" } }));
  });
  return { r, c };
}

/** Der Manager öffnet das Mikrofon (wie beim Verbinden) und meldet die eigene Spur. */
async function mikrofonAuf(c: AttrappenClient, label?: string) {
  await act(async () => {
    await manager().initialize();
    c.opts.callbacks.onTrackStarted(spur(label), { local: true });
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  h.clients.length = 0;
  h.fehlt = false;
  h.pegel = 0.005;
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

describe("Mikrofonwahl beim Gesprächsstart", () => {
  it("der Medienmanager öffnet gleich das gewählte Gerät dieser Person, nicht erst das Standardgerät", async () => {
    localStorage.setItem(`wamo.mikrofon.${NUTZER}`, "mic-b");
    localStorage.setItem(`wamo.mikrofon.${ANDERE}`, "mic-x");
    const { c } = await gespraech();
    expect(manager()).toBeInstanceOf(GeraeteMedienManager);
    await mikrofonAuf(c);
    expect(manager()._wavRecorder.begin.mock.calls[0]).toEqual(["mic-b"]);
    expect(manager().mikrofonErsatz).toBe(false);
    expect(c.updateMic).not.toHaveBeenCalled(); // kein Nachwechseln nach dem Verbinden
    expect(aktuell().toast).toBeNull();
  });

  it("ohne eigene Wahl gilt das Standardgerät (die Wahl einer anderen Person zählt nicht)", async () => {
    localStorage.setItem(`wamo.mikrofon.${ANDERE}`, "mic-x");
    const { c } = await gespraech();
    await mikrofonAuf(c);
    expect(manager()._wavRecorder.begin.mock.calls).toEqual([[]]);
  });

  it("fehlt das gespeicherte Gerät, läuft das Standardgerät mit kurzem Hinweis, einmal je Gespräch", async () => {
    localStorage.setItem(`wamo.mikrofon.${NUTZER}`, "mic-weg");
    h.fehlt = true;
    const { c } = await gespraech();
    await mikrofonAuf(c, "Standard-Mikrofon");
    expect(manager()._wavRecorder.begin.mock.calls).toEqual([["mic-weg"], []]);
    expect(manager().mikrofonErsatz).toBe(true);
    expect(aktuell().toast?.text).toBe(MIKROFON_ERSATZ_TEXT);
    expect(aktuell().mikrofon).toBe("Standard-Mikrofon");
    const erster = aktuell().toast?.key;
    await act(async () => {
      c.opts.callbacks.onTrackStarted(spur("Headset"), { local: true }); // Gerätewechsel danach: kein zweiter Hinweis
    });
    expect(aktuell().toast?.key).toBe(erster);
    expect(localStorage.getItem(`wamo.mikrofon.${NUTZER}`)).toBe("mic-weg"); // die Wahl bleibt für später
  });
});

describe("Mikrofon wechseln", () => {
  it("im Gespräch: sofort über updateMic, gespeichert je Person; leer heißt Standardgerät", async () => {
    const { r, c } = await gespraech();
    expect(r.result.current.mikrofonWaehlen("mic-c")).toBe(true);
    expect(c.updateMic).toHaveBeenLastCalledWith("mic-c");
    expect(localStorage.getItem(`wamo.mikrofon.${NUTZER}`)).toBe("mic-c");
    expect(aktuell().toast?.text).toBe("Mikrofon gewechselt");
    expect(r.result.current.mikrofonWaehlen("")).toBe(true);
    expect(c.updateMic).toHaveBeenLastCalledWith("");
    expect(localStorage.getItem(`wamo.mikrofon.${NUTZER}`)).toBe(MIKROFON_STANDARD);
    expect(aktuell().toast?.text).toBe("Standardgerät eingestellt");
  });

  it("ohne Gespräch: nur gemerkt, das nächste Gespräch öffnet das Gerät", async () => {
    const r = renderHook(() => useWamo());
    expect(r.result.current.mikrofonWaehlen("mic-d")).toBe(true);
    expect(localStorage.getItem(`wamo.mikrofon.${NUTZER}`)).toBe("mic-d");
    await act(async () => {
      void r.result.current.connect();
    });
    await fluss();
    await act(async () => {
      await manager().initialize();
    });
    expect(manager()._wavRecorder.begin.mock.calls[0]).toEqual(["mic-d"]);
  });

  it("Aliase und überlange Kennungen werden nicht angenommen", () => {
    const r = renderHook(() => useWamo());
    expect(r.result.current.mikrofonWaehlen("default")).toBe(false);
    expect(r.result.current.mikrofonWaehlen("communications")).toBe(false);
    expect(r.result.current.mikrofonWaehlen("x".repeat(201))).toBe(false);
    expect(localStorage.getItem(`wamo.mikrofon.${NUTZER}`)).toBeNull();
  });
});

describe("Pegelwarnung", () => {
  it("sehr leise beim Sprechen: nach etwa 10 s ein Hinweis mit dem Weg zur Mikrofonwahl, einmal je Gespräch", async () => {
    const { c } = await gespraech();
    await mikrofonAuf(c);
    await act(async () => c.opts.callbacks.onUserStartedSpeaking());
    await fluss(9_000);
    expect(aktuell().error).toBeNull();
    await fluss(1_200);
    expect(aktuell().error).toEqual({ art: "hinweis", text: LEISE_TEXT, aktion: "mikrofon_waehlen" });
    await act(async () => wamo.set((s) => ({ ...s, error: null })));
    await fluss(30_000);
    expect(aktuell().error).toBeNull(); // einmal je Gespräch
  });

  it("nie während W.A.I.S. spricht: der fällige Hinweis wartet auf das Ende der Antwort (und auf eine freie Anzeige)", async () => {
    const { c } = await gespraech();
    await mikrofonAuf(c);
    await act(async () => wamo.set((s) => ({ ...s, error: { art: "sonst", text: "andere Meldung" } })));
    await act(async () => c.opts.callbacks.onUserStartedSpeaking());
    await fluss(10_500); // fällig, aber eine andere Meldung steht
    expect(aktuell().error?.text).toBe("andere Meldung");
    await act(async () => c.opts.callbacks.onBotStartedSpeaking());
    await act(async () => wamo.set((s) => ({ ...s, error: null })));
    await fluss(5_000);
    expect(aktuell().error).toBeNull(); // W.A.I.S. spricht
    await act(async () => c.opts.callbacks.onBotStoppedSpeaking());
    await fluss(100);
    expect(aktuell().error?.text).toBe(LEISE_TEXT);
  });

  it("normale Sprache und Zeit ohne Sprechen warnen nicht", async () => {
    h.pegel = 0.1;
    const { c } = await gespraech();
    await mikrofonAuf(c);
    await act(async () => c.opts.callbacks.onUserStartedSpeaking());
    await fluss(30_000);
    expect(aktuell().error).toBeNull();
    h.pegel = 0.005;
    await act(async () => c.opts.callbacks.onUserStoppedSpeaking());
    await fluss(30_000); // leise, aber niemand spricht
    expect(aktuell().error).toBeNull();
  });

  it("ein neues Gespräch darf wieder warnen", async () => {
    const { r, c } = await gespraech();
    await mikrofonAuf(c);
    await act(async () => c.opts.callbacks.onUserStartedSpeaking());
    await fluss(10_200);
    expect(aktuell().error?.text).toBe(LEISE_TEXT);
    await act(async () => {
      await r.result.current.disconnect();
    });
    await act(async () => wamo.set((s) => ({ ...s, error: null })));
    await act(async () => {
      void r.result.current.connect();
    });
    await fluss();
    const c2 = letzter();
    await act(async () => {
      c2.opts.callbacks.onBotReady({ version: "2.0.0" });
      wamo.set((s) => ({ ...s, betrieb: { modus: "buero", modelle: {}, pc: "aus" } }));
    });
    await mikrofonAuf(c2);
    await act(async () => c2.opts.callbacks.onUserStartedSpeaking());
    await fluss(10_200);
    expect(aktuell().error?.text).toBe(LEISE_TEXT);
  });
});

describe("kein /start ohne Anmeldung", () => {
  const auth = (session: unknown) => ({
    auth: {
      getSession: vi.fn(async () => ({ data: { session } })),
      onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: () => undefined } } })),
      refreshSession: vi.fn(async () => ({ error: null })),
      signOut: vi.fn(async () => ({ error: null })),
    },
  });

  it("ohne Sitzung: kein Start beim Kern, keine Slot-Abfrage, die Anmeldung wird verlangt", async () => {
    h.supabase = auth(null);
    const r = renderHook(() => useWamo());
    await act(async () => {
      await r.result.current.connect();
    });
    await fluss(30_000);
    expect(clients()).toHaveLength(1);
    expect(letzter().startBotAndConnect).not.toHaveBeenCalled();
    expect(slot.aktiverSlot).not.toHaveBeenCalled();
    expect(aktuell().presence).toBe("offline");
    expect(aktuell().error).toEqual({ art: "anmeldung", text: OHNE_ANMELDUNG });
  });

  it("mit Sitzung: Start mit dem Token im Kopf der Anfrage", async () => {
    // ein frisches Token (Anmeldung jetzt, amr), damit die Altersprüfung der Anmeldung (lib/anmeldung.ts) nicht greift
    const jetzt = Math.floor(Date.now() / 1000);
    const kopf = btoa(JSON.stringify({ alg: "ES256" }));
    const inhalt = btoa(JSON.stringify({ exp: jetzt + 3600, aal: "aal2", amr: [{ method: "password", timestamp: jetzt }] }));
    const token = `${kopf}.${inhalt}.x`;
    h.supabase = auth({ access_token: token, expires_at: Math.floor(Date.now() / 1000) + 3600 });
    const r = renderHook(() => useWamo());
    await act(async () => {
      await r.result.current.connect();
    });
    expect(letzter().startBotAndConnect).toHaveBeenCalledTimes(1);
    const { endpoint, headers } = letzter().startBotAndConnect.mock.calls[0][0] as { endpoint: string; headers: Headers };
    expect(endpoint).toBe("https://kern.test/start");
    expect(headers.get("Authorization")).toBe(`Bearer ${token}`);
  });
});
