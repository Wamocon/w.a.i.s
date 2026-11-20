"use client";

import { memo, useEffect, useRef } from "react";
import { InstallerDownload } from "@/components/einrichtung/InstallerDownload";
import { useDesktopApp } from "@/lib/geraet";
import { uhrzeitText } from "@/lib/einrichtung";
import { appVersion } from "@/lib/installer";
import { BROWSER_SATZ, suchStand, updateAnsicht, type UpdateAnsicht, type UpdateZustand } from "@/lib/updates";
import { Block, Daten } from "./Block";
import { Zeichen, type Form } from "./Zeichen";
import { useUpdates } from "./useUpdates";

/**
 * Abschnitt "Updates" (Kennung updates): die Desktop-App suchen und installieren lassen, was früher nur ein Punkt der Prüfliste in den
 * Ersten Schritten war. Zuerst die installierte Version und die, die der Server anbietet, darunter der Zustand als Zeichen, Titel und
 * Satz (die Farbe trägt nie allein), dann "Update installieren" (nur, wenn die App das signierte Angebot des Servers bestätigt hat)
 * und "Nach Updates suchen" (einmal je 10 Sekunden, nie während einer Installation). Die Logik steht in lib/updates.ts und
 * lib/einrichtung.ts, der Ablauf in useUpdates.ts: Das Token holt erst der Klick und geht nur an die App.
 *
 * Im Browser gibt es nichts zu aktualisieren: ein ruhiger Satz und der Installer für Windows (InstallerDownload), kein Update-Knopf.
 * Bei einer älteren App, die Updates nicht selbst prüfen kann, kommt ebenfalls der Installer als Weg dazu.
 */

/** Zeichen je Zustand; wo nichts steht, zeigt die Stufe das Symbol (Haken, Ausrufezeichen oder i). */
const FORM: Partial<Record<UpdateZustand, Form>> = { verfuegbar: "pfeil", installiert: "punkte", laedt: "punkte" };

function Zustand({ ansicht }: { ansicht: UpdateAnsicht }) {
  return (
    <div className="up-zustand" data-stufe={ansicht.stufe} role="status" aria-live="polite">
      <Zeichen stufe={ansicht.stufe} form={FORM[ansicht.zustand]} />
      <div className="es-inhalt">
        <p className="es-titel">{ansicht.titel}</p>
        <p className="es-text">{ansicht.satz}</p>
      </div>
    </div>
  );
}

function AppUpdates() {
  const { stand, sucht, gesperrt, zeit, phase, suchen, installieren } = useUpdates();
  const ansicht = updateAnsicht({ version: appVersion(), stand, phase });
  const angebot = ansicht.angebot;
  const installiertGerade = phase.art === "laeuft";
  const gestartet = phase.art === "gestartet"; // die App beendet sich: nichts mehr starten
  const sucheKnopf = useRef<HTMLButtonElement>(null);

  // Scheitert die Installation oder startet sie, verschwindet der Knopf "Update installieren" unter dem Fokus: dann geht der Fokus zum Knopf
  // "Nach Updates suchen" (nur, wenn er sonst auf nichts mehr läge, damit nichts gestohlen wird).
  useEffect(() => {
    if ((phase.art === "fehler" || phase.art === "gestartet") && (!document.activeElement || document.activeElement === document.body)) {
      sucheKnopf.current?.focus();
    }
  }, [phase.art]);

  return (
    <>
      <Block titel="Version">
        <Daten
          zeilen={[
            { name: "Installiert", wert: <span className="num">{ansicht.installiert}</span> },
            { name: "Auf dem Server", wert: <span className="num">{ansicht.server}</span> },
          ]}
        />
        <Zustand ansicht={ansicht} />
        {ansicht.hinweis && <p className="ez-klein">{ansicht.hinweis}</p>}
        <div className="es-aktionen">
          {angebot && (
            <button
              type="button"
              className="btn-primary up-installieren"
              aria-disabled={installiertGerade || sucht || undefined}
              aria-busy={installiertGerade || undefined}
              onClick={() => {
                if (!installiertGerade && !sucht) void installieren(angebot);
              }}
            >
              Update installieren
            </button>
          )}
          <button
            ref={sucheKnopf}
            type="button"
            className="btn-secondary es-knopf"
            aria-disabled={sucht || gesperrt || installiertGerade || gestartet || undefined}
            aria-busy={sucht || undefined}
            onClick={suchen}
          >
            Nach Updates suchen
          </button>
          <p className="ez-klein" role="status">
            {suchStand(sucht, gesperrt, zeit === null ? null : uhrzeitText(new Date(zeit)))}
          </p>
        </div>
      </Block>
      {ansicht.installerAnbieten && (
        <Block titel="Installer">
          <InstallerDownload />
        </Block>
      )}
    </>
  );
}

function BrowserUpdates() {
  return (
    <>
      <Block titel="Im Browser">
        <p className="ez-text">{BROWSER_SATZ}</p>
      </Block>
      <Block titel="Installer">
        <InstallerDownload />
      </Block>
    </>
  );
}

export const UpdatesAbschnitt = memo(function UpdatesAbschnitt() {
  const desktop = useDesktopApp();
  return desktop ? <AppUpdates /> : <BrowserUpdates />;
});
