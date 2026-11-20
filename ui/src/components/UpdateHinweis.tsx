"use client";

import { memo, useEffect, useId, useState, type KeyboardEvent } from "react";
import { EinstellungenLink } from "@/components/einstellungen/EinstellungenLink";
import { Zeichen } from "@/components/einstellungen/Zeichen";
import { useEinstellungenZiel } from "@/lib/einstellungenHash";
import { useDesktopApp } from "@/lib/geraet";
import { useSelect } from "@/lib/store";
import { useNutzer } from "@/lib/nutzer";
import {
  FENSTER_ALTER_MS,
  INTERVALL_ALTER_MS,
  PRUEFABSTAND_MS,
  startId,
  hinweisArt,
  hinweisSatz,
  spaeterGilt,
  spaeterLesen,
  spaeterSchreiben,
  type SpaeterEintrag,
} from "@/lib/updateHinweis";
import { SATZ_LAEUFT, angebotAus } from "@/lib/updates";
import { updates, updatesErneutVersuchen, updatesInstallieren, updatesLadenWennAlt } from "@/lib/updatesStore";
import { istOnline, wamo } from "@/lib/wamo";

/**
 * Pop-up "Update verfügbar": eine schwebende Karte (unten rechts, am Handy unten über die Breite), wenn der Server eine neuere Version
 * der Desktop-App anbietet und die App das signierte Angebot bestätigt hat. Nur in der Desktop-App und nur für ein angemeldetes Profil;
 * es hängt in der Hauptansicht (WamoAnsicht, nie in der Laborsicht), die es erst nach Anmeldung und Erstanmeldung gibt, im Browser gibt
 * es keine Brücke und damit weder Abruf noch Karte. Stand, Suche und Installation teilt es mit dem Abschnitt Updates der Einstellungen
 * (lib/updatesStore.ts): dieselbe bestätigte Quelle, dieselben Schutzregeln (das Token holt erst der Klick und steht nie im Zustand),
 * höchstens eine Installation zugleich. Geprüft wird beim Start, danach alle 30 Minuten und beim Wiederöffnen des Fensters, wenn die
 * letzte Prüfung älter als 10 Minuten ist.
 *
 * Gesprächen kommt es nie in den Weg: kein Fokus, kein Dialog, kein Modal, nichts, was den Ton anhält. Die Karte steht in einer höflichen
 * Live-Region, ist mit der Tastatur zu erreichen, und Escape in der Karte wirkt wie "Später". Läuft ein Gespräch, sagt der Satz, dass das
 * Update es beendet. "Später" blendet die Karte für diese Version aus (lib/updateHinweis.ts: je Profil gemerkt, dieselbe Version erst nach dem
 * nächsten Start oder nach 24 Stunden wieder, eine neuere sofort). Nach dem Start der Installation verschwindet sie, die App beendet sich.
 */

type KarteProps = { userId: string };

const Karte = memo(function Karte({ userId }: KarteProps) {
  const titelId = useId();
  const stand = useSelect(updates, (s) => s.stand);
  const phase = useSelect(updates, (s) => s.phase);
  const zeit = useSelect(updates, (s) => s.zeit);
  const sucht = useSelect(updates, (s) => s.sucht);
  const gespraech = useSelect(wamo, istOnline);
  const ziel = useEinstellungenZiel();
  const [eintrag, setEintrag] = useState<SpaeterEintrag | null>(() => spaeterLesen(userId));

  // Beim Start, im Takt und beim Wiederöffnen des Fensters (Sichtbarkeit oder Fokus), jeweils nur, wenn die letzte Prüfung alt genug ist
  useEffect(() => {
    void updatesLadenWennAlt(FENSTER_ALTER_MS); // beim Start (der Speicher liegt außerhalb von React, hier setzt nichts Zustand der Komponente)
    const takt = setInterval(() => void updatesLadenWennAlt(INTERVALL_ALTER_MS), PRUEFABSTAND_MS);
    const wiederoeffnet = () => {
      if (document.visibilityState !== "hidden") void updatesLadenWennAlt(FENSTER_ALTER_MS);
    };
    document.addEventListener("visibilitychange", wiederoeffnet);
    window.addEventListener("focus", wiederoeffnet);
    return () => {
      clearInterval(takt);
      document.removeEventListener("visibilitychange", wiederoeffnet);
      window.removeEventListener("focus", wiederoeffnet);
    };
  }, []);

  const angebot = angebotAus(stand);
  // Maßgeblich ist der Zeitpunkt der letzten Prüfung (zeit), nicht die Uhr jetzt: Die Frist von 24 Stunden wirkt mit der nächsten Prüfung
  // (alle 30 Minuten), ohne dass die Komponente die Uhr im Rendern liest.
  const art = hinweisArt({ angebot, phase, spaeter: angebot !== null && spaeterGilt(eintrag, angebot.version, zeit ?? 0, startId()) });
  const laeuft = art === "laeuft";
  const gesperrt = laeuft || sucht; // läuft eine Suche, tut ein Klick nichts: der Knopf sagt es mit aria-disabled
  // Im Abschnitt Updates steht dasselbe mit denselben Knöpfen: dort keine zweite Karte darüber
  const sichtbar = art !== "aus" && angebot !== null && ziel.abschnitt !== "updates";

  const spaeter = () => {
    if (!angebot || laeuft) return;
    const neu: SpaeterEintrag = { version: angebot.version, zeit: Date.now(), start: startId() };
    spaeterSchreiben(userId, neu);
    setEintrag(neu);
  };
  const beiTaste = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key !== "Escape" || e.defaultPrevented) return;
    e.preventDefault(); // die Einstellungen schließen sich nicht zugleich
    spaeter();
  };

  return (
    <div className="uh-rahmen" aria-live="polite">
      {sichtbar && (
        <div className="uh" role="region" aria-labelledby={titelId} data-art={art} onKeyDown={beiTaste}>
          <div className="uh-kopf">
            <Zeichen stufe="rot" form="pfeil" />
            <p id={titelId} className="uh-titel">
              Update verfügbar
            </p>
          </div>
          {laeuft ? (
            <>
              <p className="uh-satz">Wird installiert. {SATZ_LAEUFT}</p>
              <progress className="uh-balken" aria-label="Update wird installiert" />
            </>
          ) : (
            <p className="uh-satz">{hinweisSatz(angebot.version, gespraech)}</p>
          )}
          {phase.art === "fehler" && <p className="uh-fehler">{phase.text}</p>}
          <div className="uh-knoepfe">
            {art === "fehler" ? (
              <button
                type="button"
                className="btn-primary"
                aria-disabled={sucht || undefined}
                aria-busy={sucht || undefined}
                onClick={() => {
                  if (!sucht) void updatesErneutVersuchen();
                }}
              >
                Erneut versuchen
              </button>
            ) : (
              <button
                type="button"
                className="btn-primary"
                aria-disabled={gesperrt || undefined}
                aria-busy={laeuft || undefined}
                onClick={() => {
                  if (!gesperrt) void updatesInstallieren(angebot);
                }}
              >
                Jetzt aktualisieren
              </button>
            )}
            <button type="button" className="btn-secondary" aria-disabled={laeuft || undefined} onClick={spaeter}>
              Später
            </button>
          </div>
          <p className="uh-link">
            <EinstellungenLink abschnitt="updates">Zu den Updates</EinstellungenLink>
          </p>
        </div>
      )}
    </div>
  );
});

/** Das Pop-up, nur in der Desktop-App und nur mit angemeldetem Profil (je Profil ein eigener Eintrag für "Später"). */
export const UpdateHinweis = memo(function UpdateHinweis() {
  const desktop = useDesktopApp();
  const nutzer = useNutzer();
  if (!desktop || !nutzer.id) return null;
  return <Karte key={nutzer.id} userId={nutzer.id} />;
});
