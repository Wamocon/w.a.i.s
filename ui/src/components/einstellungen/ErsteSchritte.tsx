"use client";

import { memo, useId } from "react";
import { EinrichtungsAblauf } from "@/components/einrichtung/EinrichtungsAblauf";
import { InstallerDownload } from "@/components/einrichtung/InstallerDownload";
import { EINRICHTUNG_SCHRITTE } from "@/components/einrichtung/schritte";
import { SCHRITT_TITEL } from "@/lib/einrichtungSchritte";

const MODELL_SCHRITTE = EINRICHTUNG_SCHRITTE.filter((s) => s.id !== "installer");

/**
 * Abschnitt "Erste Schritte" der Einstellungen (docs/ausrollen-neue-nutzer.md 4.2 und 4.7), bis das Gerüst des geführten
 * Ablaufs aus P1b da ist: oben der Modellzugang in Schritten (Token, API-Schlüssel, Zusammenfassung), darunter der
 * Installer als eigener Block. Bewusst klein gehalten, denn hier kommt später die Prüfliste der Einrichtung dazu (4.3).
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
    </>
  );
});
