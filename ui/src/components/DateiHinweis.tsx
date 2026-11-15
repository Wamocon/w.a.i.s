"use client";

import { memo } from "react";
import { hinweisText } from "@/lib/export";
import { useSelect } from "@/lib/store";
import { schliesseDateiHinweis, wamo } from "@/lib/wamo";

/**
 * Hinweis nach dem Speichern eines Canvas-Elements als Datei (Servernachricht "datei", voice-core/office_werkzeuge.py): Name, Ordner und
 * voller Pfad am PC, dazu "Öffnen" (öffnet genau diese Datei aus dem Register des Hosts) und "Schließen". Fehler zeigt der kurze Hinweis
 * oben (Toast). Die Live-Region bleibt im DOM, damit Screenreader den neuen Hinweis ansagen.
 */
export const DateiHinweis = memo(function DateiHinweis({ onOeffnen }: { onOeffnen?: (kennung: string) => boolean }) {
  const datei = useSelect(wamo, (s) => s.datei);
  return (
    <div className="memos" role="status" aria-live="polite">
      {datei && (
        <div className="memo datei-hinweis" data-scope="datei" key={datei.kennung}>
          <svg className="memo-icon" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M4 1.5h5.5L13 5v9.5H4z" />
            <path d="M9.5 1.5V5H13" />
          </svg>
          <div className="memo-body">
            <b>{hinweisText(datei)}</b>
            {datei.pfad && <span className="memo-text datei-pfad">{datei.pfad}</span>}
          </div>
          {onOeffnen && (
            <button type="button" className="memo-undo" onClick={() => onOeffnen(datei.kennung)}>
              Öffnen
            </button>
          )}
          <button type="button" className="memo-undo" aria-label="Hinweis schließen" onClick={schliesseDateiHinweis}>
            Schließen
          </button>
        </div>
      )}
    </div>
  );
});
