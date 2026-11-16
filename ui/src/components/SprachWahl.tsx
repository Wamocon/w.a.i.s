"use client";

import { memo, useEffect, useId, useRef, useState } from "react";
import { nachbar } from "@/lib/modellwahl";
import { ANTWORT_MS } from "@/lib/modellzugangHilfe";
import type { SprachAnbieter } from "@/lib/nachrichten";
import {
  gewaehlteStimme,
  hausBereit,
  sperrText,
  STIMMEN,
  stimmeErklaerung,
  stimmeWaehlbar,
  stimmeWirksamText,
} from "@/lib/sprachwahl";
import { useSelect } from "@/lib/store";
import type { ModellzugangAnfrage } from "@/lib/useWamo";
import { wamo } from "@/lib/wamo";

/**
 * Umschalter "Spracherkennung und Sprachausgabe: Soniox (Standard) | Im Haus (Datenschutz)" in der Karte Modellzugang (Paket H5).
 * Eine Wahl stellt Hören und Stimme gemeinsam um (lib/sprachwahl.ts sagt warum); sie gehört der Person und gilt ab der nächsten
 * Sitzung. Der Zwang des Admins auf Hausmodelle sperrt sie nicht. Laborkonten sehen die Karte nicht (lib/einstellungenAbschnitte.ts),
 * und der Kern lehnt die Wahl für sie ab. "Im Haus" ist gesperrt, solange der Kern es nicht eingerichtet meldet (stimmeHaus), der
 * ganze Umschalter bei einem Kern, der die Wahl noch nicht kennt. Radiogruppe nach WAI-ARIA wie ModellWahl: ein Tabstopp, Pfeiltasten
 * wählen, Home und Ende springen. Der Zustand kommt allein vom Kern zurück (modellzugang.stt und tts), nicht aus dem Klick. Weicht die
 * laufende Sitzung von der Wahl ab, steht der Grund darunter (betrieb.spracheGrund).
 */
export const SprachWahl = memo(function SprachWahl({ senden }: { senden: (anfrage: ModellzugangAnfrage) => void }) {
  const id = useId();
  const zugang = useSelect(wamo, (s) => s.modellzugang);
  const betrieb = useSelect(wamo, (s) => s.betrieb);
  const [wartet, setWartet] = useState<SprachAnbieter | null>(null);
  const [fehler, setFehler] = useState("");
  const uhr = useRef<ReturnType<typeof setTimeout> | null>(null);
  const knoepfe = useRef<(HTMLButtonElement | null)[]>([]);

  // Antwort des Kerns auf die eigene Wahl beendet das Warten, ein Fehler steht danach sichtbar da (abgeleiteter Zustand wie in
  // ModellWahl). Erfolg zählt nur, wenn der gemeldete Stand die gewartete Wahl ist: eine späte Antwort auf eine frühere Wahl beendet
  // das Warten nicht. Kommt nach einer Zeitüberschreitung doch noch ein Erfolg, verschwindet der Satz "Keine Antwort".
  const [gesehen, setGesehen] = useState(zugang);
  if (zugang !== gesehen) {
    setGesehen(zugang);
    if (zugang && zugang.aktion === "stimme") {
      if (wartet !== null && (zugang.fehler || (zugang.stt === wartet && zugang.tts === wartet))) {
        setWartet(null);
        setFehler(zugang.fehler ?? "");
      } else if (wartet === null && !zugang.fehler) {
        setFehler("");
      }
    }
  }

  useEffect(() => {
    if (wartet === null && uhr.current) {
      clearTimeout(uhr.current);
      uhr.current = null;
    }
  }, [wartet]);

  useEffect(() => () => {
    if (uhr.current) clearTimeout(uhr.current);
  }, []);

  const stand = gewaehlteStimme(zugang);
  const angezeigt = wartet ?? stand;
  const waehlbar = stimmeWaehlbar(zugang);
  const gesperrt = (wert: SprachAnbieter) => !waehlbar || (wert === "haus" && !hausBereit(zugang));
  const sperre = sperrText(zugang);

  const waehle = (wert: SprachAnbieter) => {
    if (gesperrt(wert) || wartet !== null || wert === stand) return;
    setFehler("");
    setWartet(wert);
    if (uhr.current) clearTimeout(uhr.current);
    uhr.current = setTimeout(() => {
      setWartet(null);
      setFehler("Keine Antwort vom Kern. Bitte später noch einmal versuchen.");
    }, ANTWORT_MS);
    senden({ aktion: "stimme", stt: wert, tts: wert });
  };

  const taste = (e: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    const ziel = nachbar(index, e.key, STIMMEN.length);
    if (ziel === null) return;
    e.preventDefault();
    if (wartet !== null || gesperrt(STIMMEN[ziel].id)) return; // Fokus und Tabstopp bleiben beim gewählten Eintrag
    knoepfe.current[ziel]?.focus();
    waehle(STIMMEN[ziel].id);
  };

  // Ohne gewählten Eintrag (gemischt oder unbekannt) bekommt der erste den Tabstopp
  const tabstopp = STIMMEN.some((s) => s.id === angezeigt) ? angezeigt : STIMMEN[0].id;
  return (
    <div className="mz-wahl">
      <p id={`${id}-label`} className="mz-wahlLabel">
        Spracherkennung und Sprachausgabe
      </p>
      <div
        className="betriebsart-wahl mz-wahlGruppe"
        role="radiogroup"
        aria-labelledby={`${id}-label`}
        aria-describedby={`${id}-text`}
      >
        {STIMMEN.map((s, i) => (
          <button
            key={s.id}
            ref={(el) => {
              knoepfe.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={s.id === angezeigt}
            data-an={s.id === angezeigt || undefined}
            tabIndex={s.id === tabstopp ? 0 : -1}
            disabled={gesperrt(s.id) && s.id !== angezeigt}
            onClick={() => waehle(s.id)}
            onKeyDown={(e) => taste(e, i)}
          >
            {s.name}
          </button>
        ))}
      </div>
      <p id={`${id}-text`} className="mz-klein">
        {stimmeErklaerung(angezeigt)}
      </p>
      {sperre && <p className="mz-klein">{sperre}</p>}
      <p className="mz-klein" role="status">
        {wartet ? "Wird gespeichert …" : stimmeWirksamText(zugang, betrieb)}
      </p>
      {fehler && (
        <p className="mz-meldung" role="alert" data-fehler>
          {fehler}
        </p>
      )}
    </div>
  );
});
