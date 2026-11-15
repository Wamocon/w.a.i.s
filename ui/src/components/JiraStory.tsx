"use client";

import { memo, useEffect, useRef, useState } from "react";
import type { CanvasItem } from "@/components/Canvas";
import { useSelect } from "@/lib/store";
import { istUuid } from "@/lib/teilenHilfe";
import { istOnline, jiraErgebnisSchliessen, wamo } from "@/lib/wamo";

/** So lange steht "Freigabekarte wird vorbereitet" neben dem Knopf (der Kern liest Jira, dann erscheint die Karte). */
export const JIRA_HINWEIS_MS = 5000;

/**
 * Knopf "Als User Story in Jira" im Kopf eines eigenen, gespeicherten Canvas-Dokuments. Er erscheint nur, wenn der Kern Jira-Stories
 * anbietet (jira_status: Admin im Büro mit Schalter) und die Sitzung läuft. Der Klick fragt nur die Freigabekarte an; angelegt wird erst
 * nach "Freigeben" auf der Karte. Projekt ist das Standardprojekt; Epic oder ein anderes Projekt nennt die Person per Sprache.
 */
export function JiraStoryKnopf({ item, anfragen }: { item: CanvasItem; anfragen?: (canvasId: string) => boolean }) {
  const an = useSelect(wamo, (s) => s.jira.status !== null && istOnline(s));
  const [status, setStatus] = useState<"" | "angefragt" | "fehler">("");
  const uhr = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (uhr.current) clearTimeout(uhr.current);
    },
    [],
  );
  if (!anfragen || !an || item.kind !== "dokument" || item.geteilt || !istUuid(item.id)) return null;
  const id = item.id;
  const klick = () => {
    setStatus(anfragen(id) ? "angefragt" : "fehler");
    if (uhr.current) clearTimeout(uhr.current);
    uhr.current = setTimeout(() => setStatus(""), JIRA_HINWEIS_MS);
  };
  return (
    <span className="canvas-jira">
      <button
        type="button"
        className="btn-secondary btn-small"
        aria-label={`„${item.title}“ als User Story in Jira anlegen (mit Freigabekarte)`}
        onClick={klick}
      >
        Als User Story in Jira
      </button>
      <span className="canvas-chip" aria-live="polite" data-art={status === "fehler" ? "fehler" : undefined}>
        {status === "angefragt" ? "Freigabekarte wird vorbereitet" : status === "fehler" ? "Nicht gesendet, keine Verbindung" : ""}
      </span>
    </span>
  );
}

/**
 * Ergebnis einer Jira-Story (jira_ergebnis): angelegt mit Schlüssel und Verweis (nur auf Jira Cloud, geprüft in lib/nachrichten.ts, öffnet
 * in einem neuen Tab ohne Rückgriff auf diese Seite) oder ein Satz, warum nicht. Bleibt stehen, bis die Person es schließt.
 */
export const JiraErgebnisHinweis = memo(function JiraErgebnisHinweis() {
  const ergebnis = useSelect(wamo, (s) => s.jira.ergebnis);
  if (!ergebnis) return null;
  return (
    <section className="jira-ergebnis" aria-label="Jira" data-ok={ergebnis.ok ? "ja" : "nein"}>
      <p className="eyebrow">Jira</p>
      <p className="jira-ergebnis-text">{ergebnis.text}</p>
      {ergebnis.ok && ergebnis.link && (
        <a href={ergebnis.link} target="_blank" rel="noopener noreferrer">
          {ergebnis.schluessel} in Jira öffnen
        </a>
      )}
      <button type="button" className="btn-secondary btn-small" aria-label="Hinweis zu Jira schließen" onClick={jiraErgebnisSchliessen}>
        Schließen
      </button>
    </section>
  );
});
