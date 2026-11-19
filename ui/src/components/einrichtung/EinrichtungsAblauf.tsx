"use client";

import { useEffect, useId, useRef, useState } from "react";
import {
  nachbarSchritt,
  schrittPosition,
  schrittSichtbar,
  wirksamerSchritt,
  type SchrittId,
} from "@/lib/einrichtungSchritte";
import { useSelect } from "@/lib/store";
import { wamo } from "@/lib/wamo";
import { EINRICHTUNG_SCHRITTE, type EinrichtungsSchritt } from "./schritte";
import { Ueberschrift } from "@/components/Ueberschrift";

/**
 * Führt durch die Schritte beim Ausrollen (D2): oben "Schritt x von n" mit einer Leiste, darunter der Titel und der Schritt
 * selbst mit Weiter, Zurück und Überspringen (die Knöpfe liegen im Schritt, damit er auch im Gerüst aus P1b allein läuft).
 * Welche Schritte gelten, folgt aus dem Stand des Kerns: Ist das Profil auf Hausmodelle festgelegt, entfallen Token und
 * API-Schlüssel, auch wenn der Stand erst nach dem Start ankommt. Bei jedem Wechsel springt der Fokus auf den Titel.
 */
export function EinrichtungsAblauf({
  schritte = EINRICHTUNG_SCHRITTE,
  onFertig,
}: {
  schritte?: readonly EinrichtungsSchritt[];
  onFertig?: () => void;
}) {
  const zugang = useSelect(wamo, (s) => s.modellzugang);
  const kopfId = useId();
  const titelRef = useRef<HTMLHeadingElement>(null);
  const alle = schritte.map((s) => s.id);
  const sichtbar = schritte.filter((s) => schrittSichtbar(s.id, zugang));
  const ids = sichtbar.map((s) => s.id);
  const [gewaehlt, setGewaehlt] = useState<SchrittId | null>(alle[0] ?? null);
  const [fertig, setFertig] = useState(false);
  const aktuellId = gewaehlt ? wirksamerSchritt(alle, ids, gewaehlt) : null;
  const aktuell = sichtbar.find((s) => s.id === aktuellId) ?? null;

  // Fokus auf den Titel, wenn die Person den Schritt gewechselt hat (Weiter, Zurück, "Noch einmal durchgehen"), nie von selbst: weder beim
  // ersten Zeigen noch wenn der Stand des Kerns später die Schritte ändert. Der Ablauf steht auch in den Einstellungen neben anderen
  // Abschnitten, und ein Fokussprung von selbst risse die Person aus dem Abschnitt, zu dem sie gerade gesprungen ist.
  const wechselVonPerson = useRef(false);
  const wechseln = (neu: SchrittId | null) => {
    wechselVonPerson.current = true;
    setGewaehlt(neu);
  };
  useEffect(() => {
    if (!wechselVonPerson.current) return;
    wechselVonPerson.current = false;
    titelRef.current?.focus();
  }, [aktuellId, fertig]);

  if (fertig) {
    return (
      <section className="ea-ablauf" aria-labelledby={kopfId}>
        <Ueberschrift ebene={4} id={kopfId} ref={titelRef} tabIndex={-1} className="ea-ueberschrift">
          Erste Schritte erledigt
        </Ueberschrift>
        <p className="ea-text">Den Stand siehst und änderst du jederzeit unter Einstellungen, Modellzugang.</p>
        <div className="ea-knoepfe">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              setFertig(false);
              wechseln(alle[0] ?? null);
            }}
          >
            Noch einmal durchgehen
          </button>
        </div>
      </section>
    );
  }
  if (!aktuell) return null;

  const position = schrittPosition(ids, aktuell.id);
  const naechster = nachbarSchritt(ids, aktuell.id, 1);
  const voriger = nachbarSchritt(ids, aktuell.id, -1);
  const weiter = () => {
    if (naechster) {
      wechseln(naechster);
      return;
    }
    wechselVonPerson.current = true;
    setFertig(true);
    onFertig?.();
  };
  const Schritt = aktuell.Komponente;

  return (
    <section className="ea-ablauf" aria-labelledby={kopfId}>
      <div className="ea-kopf">
        <p className="ea-position">{position.text}</p>
        <ol className="ea-balken" aria-label="Fortschritt der Einrichtung">
          {sichtbar.map((s, i) => (
            <li
              key={s.id}
              aria-current={s.id === aktuell.id ? "step" : undefined}
              data-stand={i < position.nummer - 1 ? "erledigt" : s.id === aktuell.id ? "aktuell" : "offen"}
            >
              <span className="sr-only">{s.titel}</span>
            </li>
          ))}
        </ol>
        <Ueberschrift ebene={4} id={kopfId} ref={titelRef} tabIndex={-1} className="ea-ueberschrift">
          {aktuell.titel}
        </Ueberschrift>
      </div>
      <Schritt key={aktuell.id} weiter={weiter} zurueck={voriger ? () => wechseln(voriger) : undefined} />
    </section>
  );
}
