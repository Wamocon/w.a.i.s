// Beleg für die Gerätewahl beim Verbinden (lib/geraeteMedien.ts, lib/stillMedien.ts): Der Medienmanager öffnet gleich das gewählte
// Mikrofon, nicht erst das Standardgerät; fehlt es, folgt das Standardgerät mit Hinweis (mikrofonErsatz); eine verweigerte Berechtigung
// ist kein "Gerät fehlt". Die Tests laufen gegen die echte Klasse der Bibliothek (@pipecat-ai/small-webrtc-transport 1.11), ersetzt
// sind nur getUserMedia und die Wiedergabe, die jsdom nicht kennt.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GeraeteMedienManager, istErsatzFall, recorderFehlerName } from "@/lib/geraeteMedien";
import { StillMedienManager } from "@/lib/stillMedien";

// Die Bibliothek erzeugt beim Laden Blob-Adressen für ihre Audio-Worklets (URL.createObjectURL), das kennt jsdom nicht
vi.hoisted(() => {
  (URL as unknown as { createObjectURL: (b: unknown) => string }).createObjectURL = () => "blob:wamo-test";
});

type Optionen = { enableMic: boolean; enableCam: boolean; callbacks: Record<string, ((...a: unknown[]) => void) | undefined> };
const optionen = (extra: Partial<Optionen["callbacks"]> = {}, enableMic = true): Optionen => ({ enableMic, enableCam: false, callbacks: { ...extra } });

const fehler = (name: string) => Object.assign(new Error(name), { name });

type Innen = { _wavStreamPlayer: { connect: () => Promise<unknown> }; setClientOptions: (o: unknown) => void };
/** Wiedergabe ersetzen (sie braucht einen AudioContext, den jsdom nicht hat); alles andere bleibt die echte Bibliothek. */
function vorbereiten<T>(m: T, o: Optionen = optionen()): T {
  const innen = m as unknown as Innen;
  innen._wavStreamPlayer.connect = vi.fn().mockResolvedValue(true);
  innen.setClientOptions(o);
  return m;
}

describe("Medienmanager mit Gerätewahl (Gespräch)", () => {
  let getUserMedia: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    getUserMedia = vi.fn().mockRejectedValue(fehler("NotAllowedError"));
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia, enumerateDevices: vi.fn().mockResolvedValue([]), addEventListener: vi.fn(), removeEventListener: vi.fn() },
    });
    // listenForDeviceChange der Bibliothek fragt den Zustand der Berechtigung ab
    Object.defineProperty(navigator, "permissions", { configurable: true, value: { query: vi.fn().mockResolvedValue({ state: "granted" }) } });
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("Befund: ohne Wahl öffnet der Manager beim Verbinden das Standardgerät, wie die Bibliothek", async () => {
    const m = vorbereiten(new GeraeteMedienManager(null));
    await m.initialize();
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(getUserMedia.mock.calls[0][0]).toEqual({ audio: true });
    expect(m.mikrofonErsatz).toBe(false);
  });

  it("mit Wahl fragt der erste Zugriff genau das gewählte Gerät an (deviceId exact), nicht das Standardgerät", async () => {
    getUserMedia.mockRejectedValueOnce(fehler("OverconstrainedError"));
    const m = vorbereiten(new GeraeteMedienManager("mic-b"));
    await m.initialize();
    expect(getUserMedia.mock.calls[0][0]).toEqual({ audio: { deviceId: { exact: "mic-b" } } });
    // fehlt das Gerät, folgt das Standardgerät, und der Manager sagt es
    expect(getUserMedia.mock.calls[1][0]).toEqual({ audio: true });
    expect(m.mikrofonErsatz).toBe(true);
  });

  it("verweigerte Berechtigung ist kein fehlendes Gerät: kein Ersatzhinweis, onDeviceError, und keine zweite Frage", async () => {
    const onDeviceError = vi.fn();
    const m = vorbereiten(new GeraeteMedienManager("mic-b"), optionen({ onDeviceError }));
    await m.initialize();
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(onDeviceError).toHaveBeenCalledTimes(1);
    expect(m.mikrofonErsatz).toBe(false);
    // die Ablehnung galt nur für diesen einen Aufruf der Basisklasse: ein späterer Wechsel fragt wieder
    getUserMedia.mockClear();
    await (m as unknown as { updateMic: (id: string) => Promise<void> }).updateMic("mic-c");
    expect(getUserMedia).toHaveBeenCalledTimes(1);
  });

  it("läuft der Recorder schon (zweites initialize), versucht der Manager nichts und stoppt keine Spur", async () => {
    const m = vorbereiten(new GeraeteMedienManager("mic-b"));
    const rec = (m as unknown as { _wavRecorder: { begin: unknown; getStatus: () => string; stream: unknown } })._wavRecorder;
    const stopp = vi.fn();
    rec.getStatus = () => "paused";
    rec.stream = { getTracks: () => [{ stop: stopp }] };
    rec.begin = vi.fn().mockRejectedValue(new Error("Already connected: please call .end() to start a new session"));
    await m.initialize();
    expect(rec.begin).toHaveBeenCalledTimes(1); // nur der Aufruf der Basisklasse, ohne Gerät
    expect((rec.begin as ReturnType<typeof vi.fn>).mock.calls[0]).toEqual([]);
    expect(stopp).not.toHaveBeenCalled();
    expect(m.mikrofonErsatz).toBe(false);
  });

  it("gelingt das gewählte Gerät, versucht die Basisklasse kein zweites Öffnen mit Erfolg (der Recorder läuft schon)", async () => {
    const m = vorbereiten(new GeraeteMedienManager("mic-b"));
    const rec = (m as unknown as { _wavRecorder: { begin: (id?: string) => Promise<unknown> } })._wavRecorder;
    const geoeffnet: (string | undefined)[] = [];
    let laeuft = false;
    rec.begin = vi.fn(async (id?: string) => {
      if (laeuft) throw new Error("Already connected: please call .end() to start a new session");
      geoeffnet.push(id);
      laeuft = true;
      return true;
    });
    await expect(m.initialize()).resolves.toBeUndefined();
    expect(geoeffnet).toEqual(["mic-b"]);
    expect(rec.begin).toHaveBeenCalledTimes(2); // der zweite Aufruf der Basisklasse wird abgelehnt und von ihr verschluckt
    expect(m.mikrofonErsatz).toBe(false);
  });

  it("Fehlername aus der Meldung des Recorders; nur Berechtigungsfehler zählen nicht als Ersatz", () => {
    expect(recorderFehlerName({ devices: ["mic"], type: "unknown", error: fehler("NotFoundError") })).toBe("NotFoundError");
    expect(recorderFehlerName(null)).toBeUndefined();
    expect(istErsatzFall("OverconstrainedError")).toBe(true);
    expect(istErsatzFall("NotReadableError")).toBe(true);
    expect(istErsatzFall(undefined)).toBe(true);
    expect(istErsatzFall("NotAllowedError")).toBe(false);
    expect(istErsatzFall("SecurityError")).toBe(false);
  });
});

describe("stiller Manager mit Gerätewahl (Sprechen nach dem Tippen)", () => {
  let getUserMedia: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    getUserMedia = vi.fn().mockRejectedValue(fehler("NotAllowedError"));
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia, enumerateDevices: vi.fn().mockResolvedValue([]), addEventListener: vi.fn(), removeEventListener: vi.fn() },
    });
    // listenForDeviceChange der Bibliothek fragt den Zustand der Berechtigung ab
    Object.defineProperty(navigator, "permissions", { configurable: true, value: { query: vi.fn().mockResolvedValue({ state: "granted" }) } });
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("Sprechen öffnet das gewählte Gerät; fehlt es, das Standardgerät, und nur der letzte Fehler geht an onDeviceError", async () => {
    getUserMedia.mockRejectedValueOnce(fehler("OverconstrainedError"));
    const onDeviceError = vi.fn();
    const m = vorbereiten(new StillMedienManager("mic-b"), optionen({ onDeviceError }, false));
    await m.connect();
    expect(getUserMedia).not.toHaveBeenCalled();
    await m.enableMic(true);
    expect(getUserMedia.mock.calls.map((c) => c[0])).toEqual([{ audio: { deviceId: { exact: "mic-b" } } }, { audio: true }]);
    expect(m.mikrofonErsatz).toBe(true);
    expect(onDeviceError).toHaveBeenCalledTimes(1); // nur die Ablehnung des Standardgeräts, nicht das fehlende gewählte Gerät
    expect(m.isMicEnabled).toBe(false);
  });

  it("verweigert die Person das gewählte Gerät, wird nicht noch das Standardgerät angefragt", async () => {
    const onDeviceError = vi.fn();
    const m = vorbereiten(new StillMedienManager("mic-b"), optionen({ onDeviceError }, false));
    await m.connect();
    await m.enableMic(true);
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(onDeviceError).toHaveBeenCalledTimes(1);
    expect(m.mikrofonErsatz).toBe(false);
  });

  it("ein Wechsel vor dem Sprechen ersetzt die Wahl aus dem Konstruktor, Standard ('') hebt sie auf", async () => {
    const m = vorbereiten(new StillMedienManager("mic-b"), optionen({}, false));
    await m.connect();
    await m.updateMic("");
    await m.enableMic(true);
    expect(getUserMedia.mock.calls[0][0]).toEqual({ audio: true });
  });
});
