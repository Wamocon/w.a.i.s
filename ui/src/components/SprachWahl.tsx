"use client";

import { memo, useEffect, useId, useRef, useState } from "react";
import { nachbar } from "@/lib/modellwahl";
import { ANTWORT_MS } from "@/lib/modellzugangHilfe";
import type { SprachAnbieter } from "@/lib/nachrichten";
import {
  BAUSTEINE,
  bausteinErklaerung,
  datenschutzText,
  gewaehlt,
  gewaehlteHausStimme,
  hausBereit,
  sperrText,
  type SprachBaustein,
  STIMMEN,
  stimmeHinweis,
  stimmenAuswahl,
  stimmeWaehlbar,
  stimmeWirksamText,
} from "@/lib/sprachwahl";
import { useSelect } from "@/lib/store";
import type { ModellzugangAnfrage } from "@/lib/useWamo";
import { wamo } from "@/lib/wamo";

type Paar = { stt: SprachAnbieter; tts: SprachAnbieter };

/** Eine Radiogruppe nach WAI-ARIA wie ModellWahl: ein Tabstopp, Pfeiltasten wählen, Home und Ende springen. */
function SprachGruppe({
  id,
  name,
  angezeigt,
  gesperrt,
  waehle,
}: {
  id: string;
  name: string;
  angezeigt: SprachAnbieter | null;
  gesperrt: (wert: SprachAnbieter) => boolean;
  waehle: (wert: SprachAnbieter) => boolean;
}) {
  const knoepfe = useRef<(HTMLButtonElement | null)[]>([]);
  const taste = (e: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    const ziel = nachbar(index, e.key, STIMMEN.length);
    if (ziel === null) return;
    e.preventDefault();
    if (gesperrt(STIMMEN[ziel].id)) return; // Fokus und Tabstopp bleiben beim gewählten Eintrag
    if (waehle(STIMMEN[ziel].id)) knoepfe.current[ziel]?.focus();
  };
  // Ohne gewählten Eintrag (Stand unbekannt) bekommt der erste den Tabstopp
  const tabstopp = STIMMEN.some((s) => s.id === angezeigt) ? angezeigt : STIMMEN[0].id;
  return (
    <div className="mz-wahl">
      <p id={`${id}-label`} className="mz-wahlLabel">
        {name}
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
    </div>
  );
}

/**
 * Hören und Sprechen in der Karte Modellzugang (Paket H5, getrennt seit dem Wunsch von Niko vom 16.11.2026): Spracherkennung und
 * Sprachausgabe je "Soniox (Standard)" oder "Im Haus (Datenschutz)", dazu die Stimme der Sprachausgabe im Haus. Die Wahl gehört der Person
 * und gilt ab der nächsten Sitzung. Der Zwang des Admins auf Hausmodelle sperrt sie nicht. Laborkonten sehen die Karte nicht
 * (lib/einstellungenAbschnitte.ts), und der Kern lehnt die Wahl für sie ab. "Im Haus" ist gesperrt, solange der Kern es nicht eingerichtet
 * meldet (stimmeHaus), der ganze Umschalter bei einem Kern, der die Wahl noch nicht kennt. Der Zustand kommt allein vom Kern zurück
 * (modellzugang.stt, tts, hausStimme), nicht aus dem Klick. Weicht die laufende Sitzung ab, steht der Grund darunter (betrieb.spracheGrund).
 */
export const SprachWahl = memo(function SprachWahl({ senden }: { senden: (anfrage: ModellzugangAnfrage) => void }) {
  const id = useId();
  const zugang = useSelect(wamo, (s) => s.modellzugang);
  const betrieb = useSelect(wamo, (s) => s.betrieb);
  const [wartet, setWartet] = useState<Paar | null>(null);
  const [wartetStimme, setWartetStimme] = useState<string | null>(null);
  const [fehler, setFehler] = useState("");
  const uhr = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Antwort des Kerns auf die eigene Wahl beendet das Warten, ein Fehler steht danach sichtbar da (abgeleiteter Zustand wie in
  // ModellWahl). Erfolg zählt bei jeder Meldung, deren Stand die gewartete Wahl zeigt (auch ein Status); ein Fehler nur aus der Antwort auf
  // dieselbe Aktion. Eine späte Antwort auf eine frühere Wahl beendet das Warten nicht. Kommt nach einer Zeitüberschreitung doch noch
  // ein Erfolg, verschwindet der Satz "Keine Antwort".
  const [gesehen, setGesehen] = useState(zugang);
  if (zugang !== gesehen) {
    setGesehen(zugang);
    if (zugang && wartet !== null) {
      const fertig = !zugang.fehler && zugang.stt === wartet.stt && zugang.tts === wartet.tts;
      if (fertig || (zugang.aktion === "stimme" && zugang.fehler)) {
        setWartet(null);
        setFehler(zugang.aktion === "stimme" ? (zugang.fehler ?? "") : "");
      }
    } else if (zugang && wartetStimme !== null) {
      const fertig = !zugang.fehler && zugang.hausStimmen !== undefined && gewaehlteHausStimme(zugang) === wartetStimme;
      if (fertig || (zugang.aktion === "haus_stimme" && zugang.fehler)) {
        setWartetStimme(null);
        setFehler(zugang.aktion === "haus_stimme" ? (zugang.fehler ?? "") : "");
      }
    } else if (zugang && (zugang.aktion === "stimme" || zugang.aktion === "haus_stimme") && !zugang.fehler) {
      setFehler("");
    }
  }

  const beschaeftigt = wartet !== null || wartetStimme !== null;
  useEffect(() => {
    if (!beschaeftigt && uhr.current) {
      clearTimeout(uhr.current);
      uhr.current = null;
    }
  }, [beschaeftigt]);

  useEffect(() => () => {
    if (uhr.current) clearTimeout(uhr.current);
  }, []);

  const waehlbar = stimmeWaehlbar(zugang);
  // Gesperrt (disabled) nur, was dauerhaft nicht geht; während des Wartens fängt der Handler ab, damit der Fokus nicht verloren geht
  const gesperrt = (wert: SprachAnbieter) => !waehlbar || (wert === "haus" && !hausBereit(zugang));
  const sperre = sperrText(zugang);
  const angezeigt = (b: SprachBaustein) => wartet?.[b] ?? gewaehlt(zugang, b);

  const warten = () => {
    setFehler("");
    if (uhr.current) clearTimeout(uhr.current);
    uhr.current = setTimeout(() => {
      setWartet(null);
      setWartetStimme(null);
      setFehler("Keine Antwort vom Kern. Bitte später noch einmal versuchen.");
      // Den Stand neu holen: Hat der Kern die Wahl doch gespeichert, schickte die nächste Wahl sonst den alten Wert der anderen Richtung
      senden({ aktion: "status" });
    }, ANTWORT_MS);
  };

  const waehle = (baustein: SprachBaustein, wert: SprachAnbieter): boolean => {
    const stt = gewaehlt(zugang, "stt");
    const tts = gewaehlt(zugang, "tts");
    if (beschaeftigt || gesperrt(wert) || !stt || !tts || wert === (baustein === "stt" ? stt : tts)) return false;
    const neu: Paar = { stt, tts, [baustein]: wert };
    setWartet(neu);
    warten();
    senden({ aktion: "stimme", ...neu });
    return true;
  };

  const stimmen = stimmenAuswahl(zugang);
  const stimme = wartetStimme ?? gewaehlteHausStimme(zugang);
  const waehleStimme = (wert: string) => {
    if (!waehlbar || beschaeftigt || wert === gewaehlteHausStimme(zugang)) return;
    setWartetStimme(wert);
    warten();
    senden({ aktion: "haus_stimme", stimme: wert });
  };

  return (
    <div className="mz-wahl mz-sprache">
      {BAUSTEINE.map((b) => (
        <div key={b.id} className="mz-wahl">
          <SprachGruppe
            id={`${id}-${b.id}`}
            name={b.name}
            angezeigt={angezeigt(b.id)}
            gesperrt={gesperrt}
            waehle={(wert) => waehle(b.id, wert)}
          />
          <p id={`${id}-${b.id}-text`} className="mz-klein">
            {bausteinErklaerung(b.id, angezeigt(b.id))}
          </p>
        </div>
      ))}
      <p className="mz-klein">{datenschutzText(zugang)}</p>
      {sperre && <p className="mz-klein">{sperre}</p>}
      {stimmen.length > 0 && (
        <div className="mz-wahl mz-modell">
          <label htmlFor={`${id}-stimme`} className="mz-wahlLabel">
            Stimme im Haus
          </label>
          <select
            id={`${id}-stimme`}
            value={stimme}
            disabled={!waehlbar}
            aria-describedby={`${id}-stimme-text`}
            onChange={(e) => waehleStimme(e.target.value)}
          >
            {stimmen.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <p id={`${id}-stimme-text`} className="mz-klein">
            {stimmeHinweis(zugang, stimme)}
          </p>
        </div>
      )}
      <p className="mz-klein" role="status">
        {beschaeftigt ? "Wird gespeichert …" : stimmeWirksamText(betrieb)}
      </p>
      {fehler && (
        <p className="mz-meldung" role="alert" data-fehler>
          {fehler}
        </p>
      )}
    </div>
  );
});
