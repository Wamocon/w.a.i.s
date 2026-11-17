"use client";

import { WavMediaManager } from "@pipecat-ai/small-webrtc-transport";

/**
 * Medienmanager für das Gespräch, der beim Verbinden gleich das gewählte Mikrofon öffnet (lib/mikrofon.ts, Gerätewahl je Person).
 *
 * Befund aus dem Code der installierten Pakete (@pipecat-ai/client-js 1.14, @pipecat-ai/small-webrtc-transport 1.11):
 * - Für das Eingabegerät gibt es keine Einstellung beim Verbinden. Der Konstruktor des Transports kennt nur iceServers, waitForICEGathering,
 *   audioCodec, videoCodec, mediaManager und offerUrlTemplate, connect und startBotAndConnect nur die Adressen.
 * - Öffentlich ist allein updateMic(micId): PipecatClient.updateMic gibt an SmallWebRTCTransport.updateMic weiter, das an
 *   WavMediaManager.updateMic. Dieser beendet die Aufnahme, öffnet mit WavRecorder.begin(micId) genau dieses Gerät (getUserMedia mit
 *   deviceId exact; "" heißt Standardgerät), startet die Aufnahme neu und meldet die neue Spur über onTrackStarted. Damit wechselt die
 *   Oberfläche während des Gesprächs (useWamo.ts, mikrofonWaehlen).
 * - Beim Verbinden ruft WavMediaManager.initialize aber immer WavRecorder.begin() ohne Gerät auf, öffnet also zuerst das Standardgerät.
 *   Ein updateMic nach dem Verbinden hieße: Die ersten Sekunden kommen vom falschen Mikrofon, und ein belegtes oder stummes Standardgerät
 *   löst Meldungen aus, obwohl das gewählte Gerät bereitsteht.
 *
 * Dieser Manager öffnet deshalb vor der Initialisierung der Basisklasse das gewählte Gerät mit WavRecorder.begin(id), wie es auch
 * updateMic tut. Danach ruft die Basisklasse begin() ohne Gerät auf; der Recorder läuft schon und lehnt das ab ("Already connected"), und
 * die Basisklasse verschluckt diesen Fehler selbst (initialize in transport-lib: der Fehler von begin wird ignoriert, Listener und Wiedergabe
 * werden trotzdem eingerichtet). Die Aufnahme startet wie immer erst beim Verbinden (connect), die Spur kommt über onTrackStarted.
 *
 * Fehlt das gewählte Gerät (abgezogen, belegt, unbekannt), scheitert begin(id), und die Basisklasse öffnet das Standardgerät wie bisher;
 * mikrofonErsatz sagt das der Oberfläche für einen kurzen Hinweis. Verweigert die Person das Mikrofon (auch: Frage weggeklickt), gilt das
 * nicht als Ersatz: Der Fehler geht an onDeviceError (Meldung "Mikrofon gesperrt" mit Abhilfe), und die Basisklasse fragt nicht ein zweites
 * Mal nach (ihr begin wird für diesen einen Aufruf abgelehnt). Läuft der Recorder schon (zweites initialize), versucht der Manager nichts.
 *
 * Die Basisklasse hat nur lose Typen (die Typen ihres Pakets sind nicht eingebunden), deshalb greifen wir wie lib/stillMedien.ts über
 * einen Typ auf ihre Felder zu.
 */

type Recorder = {
  begin: (id?: string) => Promise<unknown>;
  getStatus?: () => string;
  listenForDeviceErrors: (f: ((e: unknown) => void) | null) => void;
  stream?: { getTracks?: () => { stop: () => void }[] } | null;
};

/** Fehler, bei denen auch das Standardgerät nicht hilft: die Berechtigung fehlt. */
const BERECHTIGUNG = new Set(["NotAllowedError", "SecurityError"]);

/** Name des Fehlers, den der Recorder über listenForDeviceErrors meldet ({ devices, type, error }). */
export function recorderFehlerName(e: unknown): string | undefined {
  const fehler = (e as { error?: { name?: unknown } } | null)?.error;
  return typeof fehler?.name === "string" ? fehler.name.slice(0, 40) : undefined;
}

/** Gilt der Fehler beim Öffnen des gewählten Geräts als "Gerät fehlt" (dann folgt das Standardgerät mit Hinweis)? */
export const istErsatzFall = (name: string | undefined): boolean => !name || !BERECHTIGUNG.has(name);

export class GeraeteMedienManager extends WavMediaManager {
  /** Gerät, das beim Verbinden geöffnet werden soll; undefined heißt Standardgerät. */
  #wunsch: string | undefined;
  #ersatz = false;

  constructor(mikrofon?: string | null) {
    super();
    this.#wunsch = mikrofon || undefined;
  }

  /** Das gewählte Mikrofon ließ sich beim Verbinden nicht öffnen, es läuft das Standardgerät. */
  get mikrofonErsatz(): boolean {
    return this.#ersatz;
  }

  async initialize(): Promise<void> {
    const basis = this as unknown as { _wavRecorder: Recorder; _handleDeviceError?: (e: unknown) => void };
    const rec = basis._wavRecorder;
    const id = this.#wunsch;
    // Nur, wenn der Recorder noch nicht läuft: ein zweites initialize ließe sonst die laufende Spur stoppen
    if (!id || (rec.getStatus?.() ?? "ended") !== "ended") {
      await super.initialize();
      return;
    }
    let fehler: unknown = null;
    const vorher = rec.stream;
    rec.listenForDeviceErrors((e) => {
      fehler = e;
    });
    try {
      await rec.begin(id);
      this.#ersatz = false;
    } catch {
      // begin hat getUserMedia vielleicht schon geöffnet und scheiterte danach: nur diese neue Spur schließen
      if (rec.stream && rec.stream !== vorher) for (const t of rec.stream.getTracks?.() ?? []) t.stop();
      this.#ersatz = istErsatzFall(recorderFehlerName(fehler));
    } finally {
      rec.listenForDeviceErrors(null); // die Basisklasse setzt gleich ihren eigenen Empfänger
    }
    if (fehler && !this.#ersatz) {
      // Berechtigung verweigert: melden und nicht ein zweites Mal nachfragen (die Basisklasse verschluckt die Ablehnung ihres begin)
      basis._handleDeviceError?.call(this, fehler);
      const begin = rec.begin;
      rec.begin = () => Promise.reject(new Error("Mikrofon gesperrt"));
      try {
        await super.initialize();
      } finally {
        rec.begin = begin;
      }
      return;
    }
    await super.initialize();
  }
}
