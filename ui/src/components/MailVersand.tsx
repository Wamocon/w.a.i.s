"use client";

import { memo, useEffect, useState } from "react";
import { restSekunden, versandText, type MailVersand } from "@/lib/mail";
import { useSelect } from "@/lib/store";
import { schliesseMailVersand, wamo } from "@/lib/wamo";

/**
 * Hinweis nach der Freigabe einer Mail (Servernachricht mail_versand, voice-core/outlook_werkzeuge.py): Solange die Mail im klassischen
 * Outlook wartet, zählt er die Sekunden herunter und bietet "Zurückholen" (nur bis zum Ende der Frist, danach entscheidet der Kern). Danach
 * zeigt er den Endstand (gesendet, zurückgeholt, Fehler) oder, im neuen Outlook, dass der Entwurf offen ist. Die Live-Region bleibt im DOM,
 * damit Screenreader jeden neuen Stand ansagen.
 */
export const MailVersandHinweis = memo(function MailVersandHinweis({ onZurueckholen }: { onZurueckholen?: (id: string) => boolean }) {
  const v = useSelect(wamo, (s) => s.mailVersand);
  return (
    <div className="memos" role="status" aria-live="polite">
      {v && <VersandZeile key={`${v.id}-${v.zustand}-${v.bis ?? 0}`} v={v} onZurueckholen={onZurueckholen} />}
    </div>
  );
});

function VersandZeile({ v, onZurueckholen }: { v: MailVersand; onZurueckholen?: (id: string) => boolean }) {
  const wartet = v.zustand === "wartet";
  const [jetzt, setJetzt] = useState(() => Date.now());
  useEffect(() => {
    if (!wartet) return;
    const uhr = setInterval(() => setJetzt(Date.now()), 1000);
    return () => clearInterval(uhr);
  }, [wartet]);
  const rest = wartet ? restSekunden(v.bis, jetzt) : 0;
  const vid = v.id;
  return (
    <div className="memo mail-versand" data-zustand={v.zustand}>
      <svg className="memo-icon" viewBox="0 0 16 16" aria-hidden="true">
        <path d="M1.5 3.5h13v9h-13z" />
        <path d="M1.5 3.5 8 9l6.5-5.5" />
      </svg>
      <div className="memo-body">
        <b>{versandText(v, rest)}</b>
      </div>
      {wartet && rest > 0 && vid && onZurueckholen && (
        <button type="button" className="memo-undo" onClick={() => onZurueckholen(vid)}>
          Zurückholen
        </button>
      )}
      <button type="button" className="memo-undo" aria-label="Hinweis schließen" onClick={schliesseMailVersand}>
        Schließen
      </button>
    </div>
  );
}
