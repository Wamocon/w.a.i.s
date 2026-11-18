"use client";

import { useEffect, useRef, useState } from "react";
import { useDesktopApp } from "@/lib/geraet";
import { fehlerName, messen } from "@/lib/mikrofon";
import {
  AMPEL_TEXT,
  RUHE_MS,
  SPRECHEN_MS,
  TAKT_MS,
  auswerten,
  dbText,
  ergebnisLesen,
  ergebnisMerken,
  fensterAufnehmen,
  neueMessung,
  phaseBei,
  testFehlerText,
  testSpeicher,
  type Ergebnis,
  type TestPhase,
} from "@/lib/mikrofonTest";
import { useNutzer } from "@/lib/nutzer";
import { useSelect } from "@/lib/store";
import { istOnline, wamo, type WamoState } from "@/lib/wamo";
import { Daten } from "./Block";
import "./mikrofonTest.css";

/**
 * Mikrofontest im Block Eingabe (Abschnitt Sprache und Ton, auch in der Laborsicht; Logik und Schwellen in lib/mikrofonTest.ts): ein Knopf,
 * dann 3 s still sein und 5 s sprechen, danach Ampel, ein Satz, der Name des Mikrofons und die Messwerte. Getestet wird das Gerät, das die
 * Auswahl darüber nennt (fehlt es, das Standardgerät), mit denselben Einstellungen wie im Gespräch. Der Ton bleibt im Browser; nach dem Test,
 * beim Abbrechen, beim Verlassen der Seite und wenn das Gerät getrennt wird, schließt sich das Mikrofon. Läuft ein Gespräch mit offenem
 * Mikrofon, ist es dort während des Tests stumm (sonst hörte W.A.I.S. den Testsatz) und danach wieder an. Während des Tests schweigt W.A.I.S.
 * (Wunsch vom 18.11.2026, einmal war das Ergebnis orange, weil W.A.I.S. dazwischen geredet hat): Läuft ein Gespräch, hält ausgabeAnhalten
 * die Wiedergabe an und lässt den Kern eine laufende Antwort unterbrechen, danach ist sie wieder frei. Meldet der Kern trotzdem, dass W.A.I.S.
 * spricht, während gemessen wird, ist der Test ungültig: kein Ergebnis, keine Ampel, nichts gemerkt, nur der Satz, noch einmal zu testen.
 * Spricht W.A.I.S. beim Start noch, wartet das Einschwingen bis SCHWEIGEN_WARTE_MS, bis die Unterbrechung angekommen ist. Die Laborsicht
 * bekommt kein ausgabeAnhalten und bleibt, wie sie war: Spricht W.A.I.S. dort, sagt das Ergebnis nur, dass es ungenau sein kann.
 * Gespeichert wird nur das letzte Ergebnis je Person und Gerät, in der Laborsicht gar nichts (merken). Eine Statuszeile bleibt immer
 * eingehängt und sagt Phase und Ergebnis an; der Fokus wandert zum Abbrechen und danach zurück.
 */

/** Ein offenes Mikrofon für den Test: Name der Spur, ein Messfenster lesen (RMS linear, Spitze in dBFS), getrennt?, schließen. */
export type MikrofonQuelle = {
  label: string;
  lesen: () => { rms: number; spitzeDb: number };
  /** die Spur ist beendet (Gerät abgezogen, von Windows entzogen) */
  getrennt?: () => boolean;
  schliessen: () => void;
};

/** Öffnet das Gerät (null: Standardgerät) wie der Medienmanager des Gesprächs (lib/geraeteMedien.ts): nur die Kennung, sonst nichts. */
export async function mikrofonOeffnen(geraetId: string | null): Promise<MikrofonQuelle> {
  const geraete = typeof navigator === "undefined" ? undefined : navigator.mediaDevices;
  if (!geraete?.getUserMedia) throw Object.assign(new Error("Kein Zugriff auf Mikrofone"), { name: "NotFoundError" });
  const strom = await geraete.getUserMedia({ audio: geraetId ? { deviceId: { exact: geraetId } } : true });
  const stoppen = () => {
    for (const spur of strom.getTracks()) spur.stop();
  };
  let ctx: AudioContext | null = null;
  try {
    ctx = new AudioContext();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    ctx.createMediaStreamSource(strom).connect(analyser);
    await ctx.resume().catch(() => undefined);
    // Ein angehaltener Kontext (Regel für automatische Wiedergabe) misst nur Nullen: dann lieber ehrlich abbrechen als "Kein Ton" melden
    if (ctx.state !== "running") throw Object.assign(new Error("Messung nicht gestartet"), { name: "MessungAngehalten" });
    const buf = new Float32Array(analyser.fftSize);
    const offen = ctx;
    const spur = strom.getAudioTracks()[0];
    return {
      label: spur?.label ?? "",
      lesen: () => {
        analyser.getFloatTimeDomainData(buf);
        return messen(buf);
      },
      getrennt: () => spur?.readyState === "ended",
      schliessen: () => {
        stoppen();
        void offen.close().catch(() => undefined);
      },
    };
  } catch (e) {
    stoppen();
    void ctx?.close().catch(() => undefined);
    throw e;
  }
}

type Stand = { art: "bereit" } | { art: "oeffnet" } | { art: "laeuft"; phase: TestPhase; rest: number } | { art: "fehler"; text: string };

/** Ist im Gespräch das Mikrofon offen (dann wird es für den Test stumm geschaltet)? Still gestartet ist es zu. */
const gespraechHoert = (s: WamoState): boolean => istOnline(s) && s.micOn && !s.stillStart.still;

const UHR = new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });

const GETRENNT_TEXT = "Das Mikrofon wurde während des Tests getrennt. Schließe es wieder an oder wähle oben ein anderes und teste noch einmal.";
const UNVOLLSTAENDIG_TEXT =
  "Die Messung war unvollständig. Lass die Seite während des Tests im Vordergrund und versuche es noch einmal.";
export const GESPROCHEN_TEXT = "W.A.I.S. hat gesprochen, bitte noch einmal testen.";
/** So lange wartet das Einschwingen höchstens, bis W.A.I.S. nach der Unterbrechung verstummt ist */
const SCHWEIGEN_WARTE_MS = 3000;

function Ampel({ e }: { e: Ergebnis }) {
  return (
    <span className="mt-ampel" data-ampel={e.ampel}>
      <span className="mt-licht" aria-hidden="true" />
      <strong>{AMPEL_TEXT[e.ampel]}</strong>
    </span>
  );
}

function ErgebnisAnzeige({ e, alt, gestoert = false }: { e: Ergebnis; alt: boolean; gestoert?: boolean }) {
  return (
    <div className="mt-ergebnis" data-ampel={e.ampel}>
      {alt && <p className="ez-klein">Letzter Test mit diesem Mikrofon, {UHR.format(new Date(e.zeit))}:</p>}
      <p className="mt-satz">
        <Ampel e={e} /> <span>{e.satz}</span>
      </p>
      <p className="ez-klein">Gemessen mit {e.geraet}.</p>
      {gestoert && <p className="ez-klein">W.A.I.S. hat während des Tests gesprochen, das Ergebnis kann ungenau sein.</p>}
      <Daten
        zeilen={[
          { name: "Sprachpegel", wert: <span className="num">{dbText(e.spracheDb)} dBFS</span> },
          { name: "Grundrauschen", wert: <span className="num">{dbText(e.rauschenDb)} dBFS</span> },
          { name: "Abstand", wert: <span className="num">{dbText(e.abstandDb)} dB</span> },
          {
            name: "Spitze",
            wert: (
              <span className="num">
                {dbText(e.spitzeDb)} dBFS{e.uebersteuert > 0 ? `, an der Grenze in ${Math.round(e.uebersteuert * 100)} % der Zeit` : ""}
              </span>
            ),
          },
        ]}
      />
    </div>
  );
}

/** stumm: dieser Test hat das Mikrofon des Gesprächs stumm geschaltet; ausgabe: er hat die Wiedergabe von W.A.I.S. angehalten */
type Lauf = { quelle: MikrofonQuelle | null; takt: ReturnType<typeof setInterval> | null; stumm: boolean; ausgabe: boolean; aus: boolean };

export function MikrofonTest({
  geraetId,
  geraetName,
  merken = true,
  oeffnen = mikrofonOeffnen,
  mikrofonUmschalten,
  ausgabeAnhalten,
}: {
  /** Kennung des Geräts, das getestet wird; null: Standardgerät */
  geraetId: string | null;
  /** sein Name (aus der Geräteliste), für das letzte Ergebnis */
  geraetName: string | null;
  /** das Ergebnis im Speicher des Browsers merken (in der Laborsicht nicht) */
  merken?: boolean;
  oeffnen?: (geraetId: string | null) => Promise<MikrofonQuelle>;
  /** schaltet das Mikrofon des laufenden Gesprächs um (useWamo, toggleMic) */
  mikrofonUmschalten?: () => void;
  /** hält die Wiedergabe von W.A.I.S. an (true) und gibt sie wieder frei (false), useWamo ausgabeAnhalten; nicht in der Laborsicht */
  ausgabeAnhalten?: (an: boolean) => void;
}) {
  const { id: userId } = useNutzer();
  const desktop = useDesktopApp();
  const hoert = useSelect(wamo, gespraechHoert);
  const [stand, setStand] = useState<Stand>({ art: "bereit" });
  const [ergebnis, setErgebnis] = useState<{ e: Ergebnis; gestoert: boolean } | null>(null);
  const [stumm, setStumm] = useState(false); // dieser Test hat das Mikrofon des Gesprächs stumm geschaltet
  const lauf = useRef<Lauf | null>(null);
  const testKnopf = useRef<HTMLButtonElement>(null);
  const abbrechenKnopf = useRef<HTMLButtonElement>(null);
  /** Fokus lag beim Start auf dem Testknopf: während des Tests auf Abbrechen, danach zurück */
  const fokusFolgt = useRef(false);

  /** Mikrofon zu, Takt aus und das Gespräch wieder hören lassen, wenn der Test es stumm geschaltet hatte. */
  const beenden = () => {
    const l = lauf.current;
    lauf.current = null;
    if (!l) return;
    l.aus = true;
    if (l.takt) clearInterval(l.takt);
    l.quelle?.schliessen();
    if (l.ausgabe) ausgabeAnhalten?.(false);
    setStumm(false);
    const s = wamo.get();
    if (l.stumm && istOnline(s) && !s.micOn && !s.stillStart.still) mikrofonUmschalten?.();
  };
  const beendenRef = useRef(beenden);
  useEffect(() => {
    beendenRef.current = beenden;
  });
  useEffect(() => () => beendenRef.current(), []);

  const laeuft = stand.art === "oeffnet" || stand.art === "laeuft";
  useEffect(() => {
    if (!fokusFolgt.current) return;
    if (laeuft) abbrechenKnopf.current?.focus();
    else {
      fokusFolgt.current = false;
      testKnopf.current?.focus();
    }
  }, [laeuft]);

  const starten = async () => {
    beenden();
    setErgebnis(null);
    fokusFolgt.current = typeof document !== "undefined" && document.activeElement === testKnopf.current;
    const l: Lauf = { quelle: null, takt: null, stumm: false, ausgabe: false, aus: false };
    lauf.current = l;
    if (ausgabeAnhalten && istOnline(wamo.get())) {
      ausgabeAnhalten(true); // W.A.I.S. schweigt, eine laufende Antwort wird unterbrochen
      l.ausgabe = true;
    }
    if (mikrofonUmschalten && gespraechHoert(wamo.get())) {
      mikrofonUmschalten();
      l.stumm = !wamo.get().micOn; // nur, wenn es wirklich stumm wurde
      setStumm(l.stumm);
    }
    setStand({ art: "oeffnet" });
    let quelle: MikrofonQuelle;
    try {
      quelle = await oeffnen(geraetId);
    } catch (e) {
      if (l.aus) return;
      beenden();
      setStand({ art: "fehler", text: testFehlerText(fehlerName(e)) });
      return;
    }
    if (l.aus) {
      quelle.schliessen(); // inzwischen abgebrochen oder die Seite verlassen
      return;
    }
    l.quelle = quelle;
    const messung = neueMessung();
    const start = Date.now();
    let beginn = start;
    // Mit ausgabeAnhalten soll W.A.I.S. schweigen: spricht es doch, ist der Test ungültig. Ohne (Laborsicht) nur ein Hinweis wie bisher.
    const schweigen = ausgabeAnhalten !== undefined;
    let gestoert = false;
    setStand({ art: "laeuft", phase: "einschwingen", rest: RUHE_MS + SPRECHEN_MS });
    l.takt = setInterval(() => {
      if (quelle.getrennt?.()) {
        beenden();
        setStand({ art: "fehler", text: GETRENNT_TEXT });
        return;
      }
      const spricht = wamo.get().presence === "speaking";
      if (schweigen && spricht && phaseBei(Date.now() - beginn) === "einschwingen" && Date.now() - start < SCHWEIGEN_WARTE_MS) {
        beginn = Date.now(); // die Unterbrechung braucht einen Moment: das Einschwingen wartet, bis W.A.I.S. still ist
      }
      const ms = Date.now() - beginn;
      const phase = phaseBei(ms);
      if (phase === "ruhe" || phase === "sprechen") {
        if (spricht && schweigen) {
          // W.A.I.S. spricht, während gemessen wird: der Raum klingt anders, das Ergebnis taugt nicht
          beenden();
          setStand({ art: "fehler", text: GESPROCHEN_TEXT });
          return;
        }
        gestoert ||= spricht;
        fensterAufnehmen(messung, phase, quelle.lesen());
      }
      if (phase !== "fertig") {
        setStand({ art: "laeuft", phase, rest: phase === "sprechen" ? RUHE_MS + SPRECHEN_MS - ms : RUHE_MS - ms });
        return;
      }
      beenden();
      const e = auswerten(messung, quelle.label, Date.now());
      if (!e) {
        setStand({ art: "fehler", text: UNVOLLSTAENDIG_TEXT });
        return;
      }
      if (merken) ergebnisMerken(testSpeicher(), userId, e);
      setErgebnis({ e, gestoert });
      setStand({ art: "bereit" });
    }, TAKT_MS);
  };

  const abbrechen = () => {
    beenden();
    setStand({ art: "bereit" });
  };

  const letztes = !ergebnis && !laeuft && merken ? ergebnisLesen(testSpeicher(), userId, geraetName) : null;
  const sekunden = stand.art === "laeuft" ? Math.max(1, Math.ceil(stand.rest / 1000)) : 0;
  const phase = stand.art === "laeuft" ? stand.phase : stand.art === "oeffnet" ? "einschwingen" : null;
  // Eine Statuszeile, immer eingehängt: Anleitung je Phase, danach das Ergebnis (der Countdown daneben wird nicht angesagt)
  const ansage =
    phase === "einschwingen"
      ? "Mikrofon wird geöffnet …"
      : phase === "ruhe"
        ? "Bitte still sein, ich messe die Geräusche im Raum."
        : phase === "sprechen"
          ? "Jetzt sprechen, zum Beispiel: „Eins, zwei, drei, ich teste mein Mikrofon.“"
          : ergebnis
            ? `Ergebnis des Mikrofontests: ${AMPEL_TEXT[ergebnis.e.ampel]}.`
            : "";

  return (
    <div className="mt">
      <p className="ez-klein">
        Der Test misst, wie gut dein Mikrofon deine Stimme liefert: erst 3 Sekunden still sein, dann 5 Sekunden sprechen. Der Ton bleibt
        {desktop ? " in der App" : " im Browser"}, gespeichert wird nur das Ergebnis.
        {(hoert || stumm) && mikrofonUmschalten
          ? ` Während des Tests ist dein Mikrofon im Gespräch stumm${ausgabeAnhalten ? " und W.A.I.S. schweigt" : ""}.`
          : ""}
      </p>
      <div className="ez-tasten">
        <button ref={testKnopf} type="button" className="btn-secondary btn-small" disabled={laeuft} onClick={() => void starten()}>
          {ergebnis ? "Erneut testen" : "Mikrofon testen"}
        </button>
        {laeuft && (
          <button ref={abbrechenKnopf} type="button" className="btn-secondary btn-small" onClick={abbrechen}>
            Abbrechen
          </button>
        )}
      </div>
      <div className="mt-lauf" data-phase={phase ?? "bereit"}>
        <p className={phase ? "mt-anleitung" : "sr-only"} role="status">
          {ansage}
        </p>
        {sekunden > 0 && (
          <p className="ez-klein num" aria-hidden="true">
            noch {sekunden} s
          </p>
        )}
      </div>
      {stand.art === "fehler" && (
        <p className="ez-klein" role="alert">
          {stand.text}
        </p>
      )}
      {ergebnis && <ErgebnisAnzeige e={ergebnis.e} alt={false} gestoert={ergebnis.gestoert} />}
      {letztes && <ErgebnisAnzeige e={letztes} alt />}
    </div>
  );
}
