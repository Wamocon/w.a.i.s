"use client";

import { memo, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useSelect } from "@/lib/store";
import { abnahmeEintraege } from "@/lib/auftragAbnahme";
import { speichernMoeglich } from "@/lib/auftragEntwuerfe";
import { kartenAnsicht, repoAnzeige } from "@/lib/auftragStart";
import { einreichenMoeglich, knopfText, ungesichertText, zahlenText } from "@/lib/einreichen";
import { karteTexte } from "@/lib/laborKarte";
import type { Auftrag } from "@/lib/nachrichten";
import { wamo, type Approval } from "@/lib/wamo";

type Entscheide = (a: Approval, ja: boolean) => boolean;
type Einreiche = (a: Approval, aktion: "einreichen" | "verwerfen", bestaetigt: string[]) => boolean;

// Nach einer Entscheidung den Fokus nicht verlieren: nach dem Entfernen der Karte (also nach dem
// Commit) zur nächsten Karte oder zur Hauptschaltfläche. Gilt für Freigaben und Aufträge gemeinsam.
let fokusNachEntscheidung = false;

function fokusWeitergeben() {
  if (!fokusNachEntscheidung) return;
  fokusNachEntscheidung = false;
  const naechste = document.querySelector<HTMLElement>(".approval h3");
  (naechste ?? document.querySelector<HTMLElement>(".actions .wake"))?.focus();
}

/**
 * Freigabe-Karte: immer ganz oben in der Präsenzspalte. Für Entwicklungsaufträge und für kritische PC-Aktionen
 * (job "pc": PowerShell, Senden in Mail und Messenger, lange Suchanfragen), dann mit Zielanwendung und Frist, und für schreibende Aktionen im
 * Testlabor (job "labor": Ticket anlegen, ändern, verschieben, kommentieren, Mail senden; Texte in lib/laborKarte.ts). Sicherheit: kein Tastenkürzel, Esc lehnt
 * nicht ab, keine Freigabe per Sprache. "Freigeben" und "Ablehnen" sind gleichgewichtig gestaltet,
 * damit nichts zum schnellen Bestätigen verleitet. Texte kommen bereinigt und gekürzt aus
 * lib/nachrichten.ts (keine Steuer- oder Bidi-Zeichen). Der Fokus springt auf die Überschrift (nicht
 * auf "Freigeben") und nur, wenn er gerade auf dem body steht. Angesagt wird einmal per role="alert".
 */
function ApprovalCard({ a, onDecide }: { a: Approval; onDecide: (a: Approval, ja: boolean) => void }) {
  const head = useRef<HTMLHeadingElement>(null);
  const karte = useRef<HTMLElement>(null);
  const id = `ap-${a.job}-${a.id}`.replace(/[^a-zA-Z0-9_-]/g, "_");
  const texte = karteTexte(a.job); // Job "pc", "labor" (Testlabor) oder ein Entwicklungsauftrag: lib/laborKarte.ts

  useEffect(() => {
    if (document.activeElement === document.body) head.current?.focus();
  }, []);

  // Verschwindet die Karte ohne Klick (Frist abgelaufen), während der Fokus in ihr liegt: Fokus weitergeben
  useLayoutEffect(() => {
    const el = karte.current;
    return () => {
      if (el && el.contains(document.activeElement)) fokusNachEntscheidung = true;
    };
  }, []);

  return (
    <article className="approval" aria-labelledby={id} data-approval={id} ref={karte}>
      <p className="sr-only" role="alert">
        {texte.ueberschrift}: {a.grund}
        {a.ziel && `, Ziel: ${a.ziel}`}
        {a.warnung && `, Achtung: ${a.warnung}`}
      </p>
      <p className="eyebrow">
        {texte.ueberschrift}
        {a.projekt && <> · {a.projekt}</>}
      </p>
      <h3 id={id} ref={head} tabIndex={-1}>
        {a.grund}
      </h3>
      {texte.hinweis && <p className="approval-hinweis">{texte.hinweis}</p>}
      {a.warnung && <p className="approval-warnung">{a.warnung}</p>}
      {a.von && <p className="approval-von">angefordert von {a.von}</p>}
      {a.ziel && (
        <p className="approval-ziel">
          <span className="approval-ziel-label">{texte.zielLabel}</span> {a.ziel}
        </p>
      )}
      <pre className="approval-detail" tabIndex={0} role="region" aria-label="Was genau ausgeführt wird">
        <code>{a.detail}</code>
      </pre>
      {a.anlass && <p className="approval-anlass">Anlass laut W.A.I.S. (nur Hinweis): {a.anlass}</p>}
      {a.ablauf !== undefined && (
        <p className="approval-frist">
          Gilt bis{" "}
          <time dateTime={new Date(a.ablauf).toISOString()}>
            {new Date(a.ablauf).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </time>{" "}
          Uhr, danach verfällt sie.
        </p>
      )}
      <div className="approval-actions">
        <button type="button" className="btn-decide" onClick={() => onDecide(a, true)}>
          Freigeben
        </button>
        <button type="button" className="btn-decide" onClick={() => onDecide(a, false)}>
          Ablehnen
        </button>
      </div>
    </article>
  );
}

/**
 * Karte "Einreichen" eines Entwicklungsauftrags mit dem eigenen GitHub-Token (Plan C, C.6; Logik in lib/einreichen.ts): Repo (mit "privat"),
 * Zweig wamo/<Auftrag>, Konto, Zahlen und die markierten Pfade mit je einem Kästchen. "Einreichen" ist erst aktiv, wenn jeder markierte Pfad
 * bestätigt ist; "Verwerfen" ist gleichgewichtig. Bei gesperrt gibt es nur "Verwerfen" und die Gründe als Sätze, bei branch_gepusht
 * "Pull Request nachholen". Kein Tastenkürzel, keine Entscheidung per Sprache. Gemergt wird nie durch W.A.I.S.
 */
function EinreichenCard({ a, onEinreichen }: { a: Approval; onEinreichen?: Einreiche }) {
  const head = useRef<HTMLHeadingElement>(null);
  const karte = useRef<HTMLElement>(null);
  const [bestaetigt, setBestaetigt] = useState<ReadonlySet<string>>(new Set());
  const e = a.einreichen;
  const id = `ap-${a.job}-${a.id}`.replace(/[^a-zA-Z0-9_-]/g, "_");

  useEffect(() => {
    if (document.activeElement === document.body) head.current?.focus();
  }, []);

  useLayoutEffect(() => {
    const el = karte.current;
    return () => {
      if (el && el.contains(document.activeElement)) fokusNachEntscheidung = true;
    };
  }, []);

  if (!e) return null;
  const gesperrt = e.status === "gesperrt";
  const moeglich = !!onEinreichen && einreichenMoeglich(e, bestaetigt);
  const umschalten = (pfad: string, an: boolean) =>
    setBestaetigt((alt) => {
      const neu = new Set(alt);
      if (an) neu.add(pfad);
      else neu.delete(pfad);
      return neu;
    });
  const ungesichert = ungesichertText(e);

  return (
    <article className="approval einreichen" aria-labelledby={id} data-approval={id} ref={karte}>
      <p className="sr-only" role="alert">
        Änderung wartet: {a.grund}
      </p>
      <p className="eyebrow">
        Entwicklungsauftrag
        {a.projekt && <> · {a.projekt}</>}
      </p>
      <h3 id={id} ref={head} tabIndex={-1}>
        {a.grund}
      </h3>
      <dl className="auftrag-meta">
        <div>
          <dt>Repo</dt>
          <dd>
            {e.repo ?? "unbekannt"}
            {e.privat && " (privat)"}
          </dd>
        </div>
        <div>
          <dt>Zweig</dt>
          <dd>
            <code>{e.zweig}</code>
          </dd>
        </div>
        <div>
          <dt>Konto</dt>
          <dd>{e.konto ?? "unbekannt"}</dd>
        </div>
        <div>
          <dt>Umfang</dt>
          <dd>{zahlenText(e)}</dd>
        </div>
      </dl>
      {e.titel && <p className="approval-hinweis">Titel des Pull Requests: {e.titel}</p>}
      {gesperrt ? (
        <section aria-label="Warum sich die Änderung nicht einreichen lässt">
          <ul>
            {e.gesperrt.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </section>
      ) : (
        e.markiert.length > 0 && (
          <fieldset className="einreichen-markiert">
            <legend>Bitte jede markierte Datei prüfen und bestätigen</legend>
            {e.markiert.map((p) => (
              <label key={p}>
                <input type="checkbox" checked={bestaetigt.has(p)} onChange={(ev) => umschalten(p, ev.target.checked)} /> <code>{p}</code>
              </label>
            ))}
          </fieldset>
        )
      )}
      {e.pfade.length > 0 && (
        <details>
          <summary>Alle geänderten Dateien</summary>
          <ul>
            {e.pfade.map((p) => (
              <li key={p}>
                <code>{p}</code>
              </li>
            ))}
          </ul>
          {e.weitere > 0 && <p className="approval-hinweis">und {e.weitere} weitere</p>}
        </details>
      )}
      {ungesichert && <p className="approval-warnung">{ungesichert}</p>}
      {e.fehler && (
        <p className="notice" role="alert">
          {e.fehler}
        </p>
      )}
      <p className="approval-hinweis">Erst nach deinem Klick pusht W.A.I.S. den Zweig und öffnet einen Pull Request. Gemergt wird nie durch W.A.I.S.</p>
      <div className="approval-actions">
        {!gesperrt && (
          <button type="button" className="btn-decide" disabled={!moeglich} onClick={() => onEinreichen?.(a, "einreichen", [...bestaetigt])}>
            {knopfText(e)}
          </button>
        )}
        {!e.nachholen && (
          <button type="button" className="btn-decide" disabled={!onEinreichen} onClick={() => onEinreichen?.(a, "verwerfen", [])}>
            Verwerfen
          </button>
        )}
      </div>
    </article>
  );
}

export const Freigaben = memo(function Freigaben({ onDecide, onEinreichen }: { onDecide: Entscheide; onEinreichen?: Einreiche }) {
  const approvals = useSelect(wamo, (s) => s.approvals);
  useEffect(fokusWeitergeben, [approvals]);
  useEffect(fokusWeitergeben); // auch wenn die letzte Karte selbst verfiel (nach dem Aufräumen der Karte)

  const entscheide = (a: Approval, ja: boolean) => {
    fokusNachEntscheidung = true;
    if (!onDecide(a, ja)) fokusNachEntscheidung = false;
  };
  const einreiche = (a: Approval, aktion: "einreichen" | "verwerfen", bestaetigt: string[]) => {
    fokusNachEntscheidung = true;
    const ok = onEinreichen ? onEinreichen(a, aktion, bestaetigt) : false;
    if (!ok) fokusNachEntscheidung = false;
    return ok;
  };

  if (!approvals.length) return null;
  return (
    <section className="approvals" aria-label="Freigaben">
      {approvals.map((a) =>
        a.einreichen ? (
          <EinreichenCard key={`${a.job}-${a.id}-${a.einreichen.commitId ?? ""}`} a={a} onEinreichen={onEinreichen ? einreiche : undefined} />
        ) : (
          <ApprovalCard key={`${a.job}-${a.id}`} a={a} onDecide={entscheide} />
        ),
      )}
    </section>
  );
});

/**
 * Auftragskarte für Entwicklungsaufträge (Servernachricht "auftrag"): Projekt, Auftragsart, der
 * vollständige, bereinigte Auftragstext und, falls vorhanden, die Abnahmekriterien (Befehle in Festbreite,
 * alles als Text, nie als Markup: wer startet, bestätigt auch diese Befehle). "Starten" und "Verwerfen" sind gleichgewichtig; die Karte
 * verschwindet bei "Verwerfen" sofort, bei "Starten" erst mit der Quittung des Kerns (lib/auftragStart.ts): bis dahin
 * wartet sie, bei einem Grund bleibt sie mit dem Grund stehen, nach 15 Sekunden ohne Antwort zeigt sie einen neutralen
 * Hinweis. Meldet der Kern betrieb.entwicklung "aus", ist Starten gesperrt.
 * "Für später speichern" (nur wenn der Kern gespeicherte Aufträge anbietet, lib/auftragEntwuerfe.ts) legt die noch nicht gesendete Karte
 * unter "Gespeicherte Aufträge" ab; sie verschwindet erst mit der Antwort des Kerns.
 */
function AuftragCard({
  a,
  gesperrt,
  onDecide,
  onSpeichern,
  speichernGesperrt,
  speichert,
}: {
  a: Auftrag;
  gesperrt: boolean;
  onDecide: (a: Auftrag, ja: boolean) => void;
  onSpeichern?: (a: Auftrag) => void;
  /** eine Aktion an den gespeicherten Aufträgen wartet auf Antwort (irgendeine) */
  speichernGesperrt: boolean;
  /** genau diese Karte wird gerade gespeichert: Starten und Verwerfen warten mit */
  speichert: boolean;
}) {
  const head = useRef<HTMLHeadingElement>(null);
  const karte = useRef<HTMLElement>(null);
  const id = `auftrag-${a.job}`.replace(/[^a-zA-Z0-9_-]/g, "_");
  const abnahme = abnahmeEintraege(a.abnahme);
  const ansicht = kartenAnsicht(a, gesperrt);
  const repo = repoAnzeige(a);
  const phase = a.stand?.phase;

  useEffect(() => {
    if (document.activeElement === document.body) head.current?.focus();
  }, []);

  // Beim Speichern wird der geklickte Knopf gesperrt und verlöre den Fokus: die Überschrift übernimmt ihn, damit er beim Verschwinden der
  // Karte (Antwort ok) wie bei den anderen Entscheidungen weitergegeben wird
  useEffect(() => {
    if (speichert) head.current?.focus();
  }, [speichert]);

  // Nach "Starten" ist die Schaltfläche gesperrt, bis die Quittung kommt: den Fokus auf die Überschrift der Karte legen
  useEffect(() => {
    if (phase === "wartet") head.current?.focus();
  }, [phase]);

  // Verschwindet die Karte nach der Quittung (ok), während der Fokus in ihr liegt: Fokus weitergeben
  useLayoutEffect(() => {
    const el = karte.current;
    return () => {
      if (el && el.contains(document.activeElement)) fokusNachEntscheidung = true;
    };
  }, []);

  return (
    <article className="approval auftrag" aria-labelledby={id} ref={karte}>
      <p className="sr-only" role="alert">
        Entwicklungsauftrag wartet: {a.art || "Auftrag"}
      </p>
      <p className="eyebrow">Entwicklungsauftrag</p>
      <h3 id={id} ref={head} tabIndex={-1}>
        {a.art || "Auftrag"}
      </h3>
      <dl className="auftrag-meta">
        <div>
          <dt>Projekt</dt>
          <dd>{a.projekt || "unbekannt"}</dd>
        </div>
        <div>
          <dt>Auftragsart</dt>
          <dd>{a.art || "unbekannt"}</dd>
        </div>
        {repo && (
          <div>
            <dt>Repo</dt>
            <dd>{repo}</dd>
          </div>
        )}
        {a.github && (
          <div>
            <dt>GitHub</dt>
            <dd>mit deinem GitHub-Token{a.github.konto && `, Konto ${a.github.konto}`}</dd>
          </div>
        )}
      </dl>
      <div className="auftrag-text" tabIndex={0} role="region" aria-label="Auftragstext">
        {a.auftrag}
      </div>
      {abnahme.length > 0 && (
        <section className="auftrag-abnahme" aria-labelledby={`${id}-abnahme`}>
          <h4 id={`${id}-abnahme`}>Abnahme</h4>
          <p className="auftrag-abnahme-hinweis">
            W.A.I.S. prüft nach jeder Runde.
            {abnahme.some((k) => k.art === "befehl") && " Mit Starten bestätigst du auch die Befehle."}
          </p>
          <ul>
            {abnahme.map((k, i) => (
              <li key={i} className={k.art === "befehl" ? "abnahme-befehl" : undefined}>
                {k.art === "befehl" ? (
                  <>
                    <span className="abnahme-art">Befehl</span> <code>{k.text}</code>
                  </>
                ) : (
                  k.text
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {gesperrt && <p className="notice">Entwicklungsaufträge sind gesperrt.</p>}
      {ansicht.grund && (
        <p className="notice" role="alert">
          Nicht gestartet: {ansicht.grund}
        </p>
      )}
      {ansicht.hinweis && (
        <p className="notice" role="status">
          {ansicht.hinweis}
        </p>
      )}
      <div className="approval-actions">
        <button type="button" className="btn-decide" disabled={ansicht.startGesperrt || speichert} onClick={() => onDecide(a, true)}>
          {ansicht.startText}
        </button>
        <button type="button" className="btn-decide" disabled={ansicht.verwerfenGesperrt || speichert} onClick={() => onDecide(a, false)}>
          Verwerfen
        </button>
        {onSpeichern && (
          <button
            type="button"
            className="btn-decide"
            disabled={speichernGesperrt || !speichernMoeglich(a)}
            onClick={() => onSpeichern(a)}
          >
            {speichert ? "Wird gespeichert …" : "Für später speichern"}
          </button>
        )}
      </div>
    </article>
  );
}

export const Auftraege = memo(function Auftraege({
  onDecide,
  onSpeichern,
}: {
  onDecide: (a: Auftrag, ja: boolean) => boolean;
  /** Karte für später speichern (lib/useWamo.ts, entwuerfe.speichern); fehlt in der Vorschau und im Labor */
  onSpeichern?: (a: Auftrag) => boolean;
}) {
  const auftraege = useSelect(wamo, (s) => s.auftraege);
  const gesperrt = useSelect(wamo, (s) => s.betrieb?.entwicklung === "aus");
  // Nur wenn der Kern gespeicherte Aufträge anbietet (erste Antwort auf die Liste); gesperrt, solange eine Aktion auf Antwort wartet
  const speichernAn = useSelect(wamo, (s) => s.entwuerfe !== null);
  const speichernWartet = useSelect(wamo, (s) => s.entwuerfe?.wartet != null);
  const speichertJob = useSelect(wamo, (s) => (s.entwuerfe?.wartet?.aktion === "speichern" ? s.entwuerfe.wartet.kennung : null));
  useEffect(fokusWeitergeben, [auftraege]);

  const entscheide = (a: Auftrag, ja: boolean) => {
    // Starten lässt die Karte stehen, bis die Quittung des Kerns kommt: nur Verwerfen entfernt sie sofort und gibt den Fokus weiter
    fokusNachEntscheidung = !ja;
    if (!onDecide(a, ja)) fokusNachEntscheidung = false;
  };

  if (!auftraege.length) return null;
  return (
    <section className="approvals" aria-label="Entwicklungsaufträge">
      {auftraege.map((a) => (
        <AuftragCard
          key={a.job}
          a={a}
          gesperrt={gesperrt}
          onDecide={entscheide}
          onSpeichern={speichernAn && onSpeichern ? onSpeichern : undefined}
          speichernGesperrt={speichernWartet}
          speichert={speichertJob === a.job}
        />
      ))}
    </section>
  );
});
