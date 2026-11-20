"use client";

import { memo, useCallback, useEffect, useId, useRef, useState } from "react";
import { EinrichtungsAblauf } from "@/components/einrichtung/EinrichtungsAblauf";
import { InstallerDownload } from "@/components/einrichtung/InstallerDownload";
import { EINRICHTUNG_SCHRITTE } from "@/components/einrichtung/schritte";
import { PRUEF_ABSTAND_MS, STUFE_TEXT, prueflisteLaden, uhrzeitText, zusammenfassung, type Punkt } from "@/lib/einrichtung";
import { SCHRITT_TITEL } from "@/lib/einrichtungSchritte";
import { kernJson } from "@/lib/kernApi";
import { Block } from "./Block";
import { EinstellungenLink } from "./EinstellungenLink";
import { Zeichen } from "./Zeichen";
import { useSperre } from "./useSperre";
import { Ueberschrift } from "@/components/Ueberschrift";

/**
 * Abschnitt "Erste Schritte" (Kennung start), Teil Prüfliste: die Prüfliste der Einrichtung aus Kern und Desktop-App (lib/einrichtung.ts, Planpapier
 * docs/ausrollen-neue-nutzer.md 4.3). Je Zeile ein Zeichen (Haken, Ausrufezeichen, i) und der Zustand als Wort für Screenreader, dazu
 * der Satz; die Farbe trägt nie allein. Ein Update der App steht hier nur als Stand da: Hat die App das Manifest des Servers bestätigt,
 * verweist die Zeile "App-Version" auf den Abschnitt Updates (Updates.tsx). Dort, und nur dort, wird installiert; diese Liste ruft die
 * Installation der App nie und holt nie ein Token.
 * "Erneut prüfen" geht einmal je 10 Sekunden (aria-disabled, damit der Fokus auf dem Knopf bleibt). Nach dem Aushängen setzt nichts
 * mehr Zustand, auch keine Antwort, die erst danach kommt.
 */

function Zeile({ p }: { p: Punkt }) {
  return (
    <li className="es-punkt" data-stufe={p.stufe}>
      <Zeichen stufe={p.stufe} />
      <div className="es-inhalt">
        <p className="es-titel">
          <span className="sr-only">{STUFE_TEXT[p.stufe]}: </span>
          {p.titel}
        </p>
        <p className="es-text">{p.text}</p>
        {p.update && (
          <p className="es-verweis">
            <EinstellungenLink abschnitt="updates">Zu den Updates</EinstellungenLink>
          </p>
        )}
      </div>
    </li>
  );
}

type Punkte = readonly Punkt[] | null;

/** Laden und erneut prüfen (gedrosselt). Nach dem Aushängen setzt keine späte Antwort mehr Zustand. */
function usePruefliste() {
  const [punkte, setPunkte] = useState<Punkte>(null);
  const [laeuft, setLaeuft] = useState(true);
  const [zeit, setZeit] = useState<string | null>(null);
  const aktiv = useRef(true);
  const laeuftJetzt = useRef(false); // sofort gesetzt, damit ein zweiter Klick im selben Takt nichts auslöst
  const { gesperrt, frei, sperren } = useSperre();

  const laden = useCallback(async () => {
    if (laeuftJetzt.current) return;
    laeuftJetzt.current = true;
    setLaeuft(true);
    try {
      const neu = await prueflisteLaden({ kernJson, bruecke: window.wamoDesktop });
      if (!aktiv.current) return;
      setPunkte(neu);
      setZeit(uhrzeitText(new Date()));
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
    if (laeuftJetzt.current || !frei()) return;
    sperren();
    void laden();
  }, [laden, frei, sperren]);

  return { punkte, laeuft, gesperrt, zeit, erneut };
}

function standZeile(laeuft: boolean, gesperrt: boolean, zeit: string | null): string {
  if (laeuft) return "Prüfe ...";
  const geprueft = zeit ? `Geprüft um ${zeit} Uhr.` : "";
  return gesperrt ? `${geprueft} Erneut prüfen geht einmal je ${PRUEF_ABSTAND_MS / 1000} Sekunden.`.trim() : geprueft;
}

function zusammenfassungText(punkte: Punkte, laeuft: boolean): string {
  if (punkte) return zusammenfassung(punkte);
  return laeuft ? "Prüfe ..." : "Die Prüfung ist fehlgeschlagen. Bitte erneut prüfen.";
}

const Pruefliste = memo(function Pruefliste() {
  const { punkte, laeuft, gesperrt, zeit, erneut } = usePruefliste();
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
            <Zeile key={p.id} p={p} />
          ))}
        </ul>
      )}
      <div className="es-aktionen">
        <button
          type="button"
          className="btn-secondary es-knopf"
          aria-disabled={laeuft || gesperrt || undefined}
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
 * (Claude-Code-Token, API-Schlüssel, Zusammenfassung), dann der Installer zum Herunterladen, zuletzt die Prüfliste (der Stand der
 * App-Version verweist auf den Abschnitt Updates). Bis das Gerüst der Erstanmeldung die Schritte selbst führt, sind sie hier erreichbar.
 */
export const ErsteSchritteAbschnitt = memo(function ErsteSchritteAbschnitt() {
  const id = useId();
  return (
    <>
      <EinrichtungsAblauf schritte={MODELL_SCHRITTE} />
      <section className="ea-ablauf" aria-labelledby={id}>
        <Ueberschrift ebene={4} id={id} className="ea-ueberschrift">
          {SCHRITT_TITEL.installer}
        </Ueberschrift>
        <InstallerDownload />
      </section>
      <Pruefliste />
    </>
  );
});
