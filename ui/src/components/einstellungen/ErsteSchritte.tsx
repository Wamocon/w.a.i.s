"use client";

import { memo, useCallback, useEffect, useId, useRef, useState, type Dispatch, type RefObject, type SetStateAction } from "react";
import { EinrichtungsAblauf } from "@/components/einrichtung/EinrichtungsAblauf";
import { InstallerDownload } from "@/components/einrichtung/InstallerDownload";
import { EINRICHTUNG_SCHRITTE } from "@/components/einrichtung/schritte";
import {
  STUFE_TEXT,
  erneutWartezeit,
  nachInstallation,
  prueflisteLaden,
  updateInstallieren,
  zusammenfassung,
  type Punkt,
  type Stufe,
  type UpdateAngebot,
  type UpdateInstallation,
} from "@/lib/einrichtung";
import { SCHRITT_TITEL } from "@/lib/einrichtungSchritte";
import { kernJson } from "@/lib/kernApi";
import { accessToken } from "@/lib/supabase";
import { Block } from "./Block";

/**
 * Abschnitt "Erste Schritte" (Kennung start), Teil Prüfliste: die Prüfliste der Einrichtung aus Kern und Desktop-App (lib/einrichtung.ts, Planpapier
 * docs/ausrollen-neue-nutzer.md 4.3). Je Zeile ein Zeichen (Haken, Ausrufezeichen, i) und der Zustand als Wort für Screenreader, dazu
 * der Satz; die Farbe trägt nie allein. Ein Update der App gibt es nur als Knopf, wenn die App das Manifest des Servers bestätigt hat.
 * Das Token holt erst der Klick und gibt es nur an die App weiter (lib/einrichtung.ts, updateInstallieren); es steht nie im Zustand.
 * "Erneut prüfen" geht einmal je 10 Sekunden und nie während einer Installation (aria-disabled, damit der Fokus auf dem Knopf bleibt).
 * Nach dem Aushängen setzt nichts mehr Zustand, auch keine Antwort, die erst danach kommt.
 */

const UHRZEIT = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit" });

const PFAD: Record<Stufe, string> = {
  gruen: "M3.5 8.5l3 3 6-7",
  rot: "M8 3.5v5.5M8 12.25v.25",
  hinweis: "M8 7v5.5M8 3.75v.25",
};

function Zeichen({ stufe }: { stufe: Stufe }) {
  return (
    <span className="es-zeichen" aria-hidden="true">
      <svg viewBox="0 0 16 16" focusable="false">
        <path d={PFAD[stufe]} />
      </svg>
    </span>
  );
}

function Zeile({ p, beschaeftigt, onUpdate }: { p: Punkt; beschaeftigt: boolean; onUpdate: (a: UpdateAngebot) => void }) {
  const angebot = p.update;
  return (
    <li className="es-punkt" data-stufe={p.stufe}>
      <Zeichen stufe={p.stufe} />
      <div className="es-inhalt">
        <p className="es-titel">
          <span className="sr-only">{STUFE_TEXT[p.stufe]}: </span>
          {p.titel}
        </p>
        <p className="es-text">{p.text}</p>
        {angebot && (
          <div>
            <button
              type="button"
              className="btn-primary es-update"
              aria-disabled={beschaeftigt || undefined}
              aria-busy={beschaeftigt || undefined}
              onClick={() => {
                if (!beschaeftigt) onUpdate(angebot);
              }}
            >
              Update installieren
            </button>
          </div>
        )}
      </div>
    </li>
  );
}

/**
 * Sperre für "Erneut prüfen" aus einer einzigen Uhr (performance.now, monoton). Der Zeitgeber zeigt nur an, was die Uhr sagt: Er
 * schaut beim Ablauf noch einmal nach und stellt sich bei Bedarf neu. Vor jedem neuen Zeitgeber wird der alte gelöscht.
 */
function useSperre() {
  const [gesperrt, setGesperrt] = useState(false);
  const letzter = useRef<number | null>(null);
  const uhr = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (uhr.current !== null) clearTimeout(uhr.current);
      uhr.current = null;
    },
    [],
  );

  const nachsehen = useCallback(function pruefe() {
    if (uhr.current !== null) clearTimeout(uhr.current);
    const warten = erneutWartezeit(letzter.current, performance.now());
    uhr.current = warten > 0 ? setTimeout(pruefe, warten) : null;
    setGesperrt(warten > 0);
  }, []);

  const frei = useCallback(() => erneutWartezeit(letzter.current, performance.now()) === 0, []);
  const sperren = useCallback(() => {
    letzter.current = performance.now();
    nachsehen();
  }, [nachsehen]);

  return { gesperrt, frei, sperren };
}

type Punkte = readonly Punkt[] | null;

const appPunktNach = (erg: UpdateInstallation) => (alt: Punkte) => alt && alt.map((p) => (p.id === "app" ? nachInstallation(p, erg) : p));

/** Update starten (höchstens eines zugleich); das Ergebnis ersetzt nur den Punkt App-Version, nach dem Aushängen nichts mehr. */
function useInstallation(aktiv: RefObject<boolean>, setPunkte: Dispatch<SetStateAction<Punkte>>) {
  const [installiert, setInstalliert] = useState(false);
  const installiertJetzt = useRef(false); // sofort gesetzt, damit ein Doppelklick die App nur einmal ruft

  const installieren = useCallback(
    async (angebot: UpdateAngebot) => {
      if (installiertJetzt.current) return;
      installiertJetzt.current = true;
      setInstalliert(true);
      try {
        const erg = await updateInstallieren({ update: window.wamoDesktop?.update, angebot, token: accessToken });
        if (aktiv.current) setPunkte(appPunktNach(erg));
      } finally {
        installiertJetzt.current = false;
        if (aktiv.current) setInstalliert(false);
      }
    },
    [aktiv, setPunkte],
  );

  return { installiert, installiertJetzt, installieren };
}

/** Laden, erneut prüfen (gedrosselt) und Update starten. Nach dem Aushängen setzt keine späte Antwort mehr Zustand. */
function usePruefliste() {
  const [punkte, setPunkte] = useState<Punkte>(null);
  const [laeuft, setLaeuft] = useState(true);
  const [zeit, setZeit] = useState<string | null>(null);
  const aktiv = useRef(true);
  const laeuftJetzt = useRef(false); // sofort gesetzt, damit ein zweiter Klick im selben Takt nichts auslöst
  const { gesperrt, frei, sperren } = useSperre();
  const { installiert, installiertJetzt, installieren } = useInstallation(aktiv, setPunkte);

  const laden = useCallback(async () => {
    if (laeuftJetzt.current) return;
    laeuftJetzt.current = true;
    setLaeuft(true);
    try {
      const neu = await prueflisteLaden({ kernJson, bruecke: window.wamoDesktop });
      if (!aktiv.current) return;
      setPunkte(neu);
      setZeit(UHRZEIT.format(new Date()));
    } finally {
      laeuftJetzt.current = false;
      if (aktiv.current) setLaeuft(false);
    }
  }, []);

  useEffect(() => {
    aktiv.current = true;
    const erster = setTimeout(() => void laden(), 0); // nicht im Effekt selbst: Der erste Abruf setzt Zustand
    return () => {
      aktiv.current = false;
      clearTimeout(erster);
    };
  }, [laden]);

  const erneut = useCallback(() => {
    if (laeuftJetzt.current || installiertJetzt.current || !frei()) return;
    sperren();
    void laden();
  }, [laden, frei, sperren, installiertJetzt]);

  return { punkte, laeuft, gesperrt, zeit, installiert, erneut, installieren };
}

function standZeile(laeuft: boolean, gesperrt: boolean, zeit: string | null): string {
  if (laeuft) return "Prüfe ...";
  const geprueft = zeit ? `Geprüft um ${zeit} Uhr.` : "";
  return gesperrt ? `${geprueft} Erneut prüfen geht einmal je 10 Sekunden.`.trim() : geprueft;
}

function zusammenfassungText(punkte: Punkte, laeuft: boolean): string {
  if (punkte) return zusammenfassung(punkte);
  return laeuft ? "Prüfe ..." : "Die Prüfung ist fehlgeschlagen. Bitte erneut prüfen.";
}

const Pruefliste = memo(function Pruefliste() {
  const { punkte, laeuft, gesperrt, zeit, installiert, erneut, installieren } = usePruefliste();
  const offen = punkte !== null && punkte.some((p) => p.stufe === "rot");
  return (
    <Block titel="Prüfliste">
      <p className="ez-text">Hier siehst du, ob auf diesem Gerät und am Server alles für W.A.I.S. bereit ist.</p>
      <p className="es-zusammenfassung" role="status" aria-live="polite" data-offen={offen || undefined}>
        {zusammenfassungText(punkte, laeuft)}
      </p>
      {punkte && (
        <ul className="es-liste" aria-label="Prüfliste">
          {punkte.map((p) => (
            <Zeile key={p.id} p={p} beschaeftigt={installiert} onUpdate={(a) => void installieren(a)} />
          ))}
        </ul>
      )}
      <div className="es-aktionen">
        <button
          type="button"
          className="btn-secondary es-knopf"
          aria-disabled={laeuft || gesperrt || installiert || undefined}
          aria-busy={laeuft || undefined}
          onClick={erneut}
        >
          Erneut prüfen
        </button>
        <p className="ez-klein">{standZeile(laeuft, gesperrt, zeit)}</p>
      </div>
    </Block>
  );
});

const MODELL_SCHRITTE = EINRICHTUNG_SCHRITTE.filter((s) => s.id !== "installer");

/**
 * Abschnitt "Erste Schritte" (Kennung start, docs/ausrollen-neue-nutzer.md 4.2, 4.3, 4.7): zuerst der Modellzugang in Schritten
 * (Claude-Code-Token, API-Schlüssel, Zusammenfassung), dann der Installer zum Herunterladen, zuletzt die Prüfliste mit den Updates
 * der App. Bis das Gerüst der Erstanmeldung die Schritte selbst führt, sind sie hier erreichbar.
 */
export const ErsteSchritteAbschnitt = memo(function ErsteSchritteAbschnitt() {
  const id = useId();
  return (
    <>
      <EinrichtungsAblauf schritte={MODELL_SCHRITTE} />
      <section className="ea" aria-labelledby={id}>
        <h4 id={id} className="ea-titel">
          {SCHRITT_TITEL.installer}
        </h4>
        <InstallerDownload />
      </section>
      <Pruefliste />
    </>
  );
});
