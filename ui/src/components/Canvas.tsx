"use client";

import { Fragment, memo, useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { BildAnsicht, CanvasDateiOeffnen, CanvasHerunterladen } from "@/components/CanvasDateien";
import { CanvasHistorie } from "@/components/CanvasHistorie";
import { CanvasMail } from "@/components/MailFormular";
import { CanvasTeams } from "@/components/TeamsFormular";
import { JiraStoryKnopf } from "@/components/JiraStory";
import { TeilenKnopf } from "@/components/Teilen";
import type { BildMime } from "@/lib/canvasDatei";
import { artText, canvasSchluessel } from "@/lib/canvasHistorie";
import type { HistorieQuelle } from "@/lib/canvasOeffnen";
import { canvasIndex, canvasOffen, canvasWunsch } from "@/lib/canvasWahl";
import { exportFormate, knopfText, ONENOTE_KNOPF, onenoteMoeglich, type OfficeAktionen, type OfficeFormat } from "@/lib/export";
import { KOPIERT_MS, kopierChipText, type KopierStatus } from "@/lib/kopieren";
import type { MailAktionen } from "@/lib/mail";
import type { TeamsAktionen } from "@/lib/teams";
import { istUuid } from "@/lib/teilenHilfe";
import { useSelect } from "@/lib/store";
import { useThema } from "@/lib/useThema";
import { canvasSchliessen, wamo } from "@/lib/wamo";

/** Bild aus einer Datei der Person (lib/canvasDatei.ts): nur im Browser, src ist eine eigene blob:-Adresse mit geprüftem Typ. */
export type CanvasBild = { src: string; mime: BildMime; groesse: number; name: string; blob: Blob; breite: number; hoehe: number };

/** Was der Voice-Core per canvas_zeigen schickt (siehe voice-core/tools.py), dazu Bilder und eigene Dateien der Person. */
export type CanvasItem = (
  | { id?: string | null; kind: "tabelle"; title: string; columns: string[]; rows: string[][] }
  | { id?: string | null; kind: "code"; title: string; text: string; language?: string }
  | { id?: string | null; kind: "dokument"; title: string; text: string }
  | { id?: string | null; kind: "mermaid"; title: string; text: string }
  /** Bild: vom Kern nur als https-Adresse (url, wird nie geladen, nur verlinkt), aus einer Datei der Person als datei */
  | { id?: string | null; kind: "bild"; title: string; alt?: string; url?: string; datei?: CanvasBild }
) & {
  /** gespeichertes Ergebnis eines Entwicklungsauftrags: teilbar als Dokument oder als ganzes Projekt */
  teilbar?: { id: string; projekt?: string };
  /** von jemand anderem geteilt (geöffnet über geteilte Arbeit) */
  geteilt?: { von: string | null; recht: "lesen" | "bearbeiten" };
  /** nur in der Oberfläche: Schlüssel des Reiters (lib/canvasWahl.ts), bleibt bei Überarbeitungen gleich */
  stelle?: string;
};

const BEISPIELE = [
  { name: "Tabellen", hint: "„Zeig mir die Projektliste als Tabelle“" },
  { name: "Dokumente", hint: "„Entwirf ein Angebot für …“" },
  { name: "Diagramme", hint: "„Skizzier die Systemlandschaft von …“" },
  { name: "Code", hint: "„Zeig mir ein SQL-Statement mit JOIN“" },
  { name: "Websuche", hint: "„Wie wird das Wetter morgen?“" },
  { name: "Am PC", hint: "„Öffne WhatsApp“ · „Klick auf Senden“", nurPc: true },
  { name: "Dateien", hint: "„Datei öffnen“: Bilder, CSV, Markdown, JSON, Code", nurDateien: true },
];

/**
 * Ergebnisfläche: abonniert nur den eigenen Store-Ausschnitt (canvas) und rendert deshalb nicht
 * neu, wenn sich Untertitel oder Zeitleiste ändern. Leer zeigt sie eine ruhige Beispielliste. Darüber eine Leiste mit der aufklappbaren
 * Historie (geschlossene und ältere Elemente) und, außer im Labor, "Datei öffnen".
 */
export const CanvasBereich = memo(function CanvasBereich({
  jiraStory,
  office,
  mail,
  teams,
  aktiv,
  historie,
  dateien = false,
}: {
  jiraStory?: (canvasId: string) => boolean;
  office?: OfficeAktionen;
  mail?: MailAktionen;
  teams?: TeamsAktionen;
  /** offener Reiter an den Kern (Nachricht canvas_aktiv, voice-core/canvas_sitzung.py), null für ein Element ohne Kennung; fehlt im Labor */
  aktiv?: (canvasId: string | null) => void;
  /** ältere Elemente aus der Datenbank laden und öffnen (lib/canvasOeffnen.ts); fehlt im Labor: dann nur diese Sitzung */
  historie?: HistorieQuelle;
  /** Dateien im Browser öffnen und herunterladen (lib/canvasDatei.ts, lib/canvasExport.ts); nie im Labor */
  dateien?: boolean;
}) {
  const items = useSelect(wamo, (s) => s.canvas);
  // PC-Werkzeuge gibt es für Admins und für Mitglieder, die der Kern freigeschaltet hat (betrieb.pcStufe); den anderen den Hinweis ersparen
  const ohnePc = useSelect(wamo, (s) => s.profil?.rolle === "mitglied" && s.betrieb?.pcStufe !== "mitglied");
  // Nach dem Schließen per Knopf bekommt der Nachbarreiter den Fokus, ohne Reiter der Knopf der Historie (der Knopf selbst ist dann weg)
  const flaeche = useRef<HTMLDivElement>(null);
  const fokusNach = useRef<string | null>(null);
  useEffect(() => {
    const ziel = fokusNach.current;
    if (ziel === null) return;
    fokusNach.current = null;
    const reiter = Array.from(flaeche.current?.querySelectorAll<HTMLElement>("[data-reiter]") ?? []).find((r) => r.dataset.reiter === ziel);
    (reiter ?? flaeche.current?.querySelector<HTMLElement>(".canvas-historie-knopf"))?.focus();
  });
  const schliessen = useCallback((schluessel: string, nachbar: string | null) => {
    fokusNach.current = nachbar ?? "";
    if (!canvasSchliessen(schluessel)) fokusNach.current = null; // nichts geschlossen: den Fokus nicht später woanders hinsetzen
  }, []);
  return (
    <div className="canvas-bereich" ref={flaeche}>
      {/* Reihenfolge im DOM wie auf dem Bildschirm: erst die Knöpfe, dann die aufgeklappte Historie über die volle Breite */}
      <div className="canvas-leiste">
        {dateien && <CanvasDateiOeffnen />}
        <CanvasHistorie quelle={historie} />
      </div>
      {items.length ? (
        <Canvas
          items={items}
          jiraStory={jiraStory}
          office={office}
          mail={mail}
          teams={teams}
          aktiv={aktiv}
          dateien={dateien}
          schliessen={schliessen}
        />
      ) : (
        <div className="canvas-empty">
          <p className="eyebrow">Canvas</p>
          <h2>Was W.A.I.S. dir hier zeigt</h2>
          <p>Ergebnisse, die man sehen muss, landen auf dieser Fläche statt in der Sprache.</p>
          <ul className="kinds">
            {BEISPIELE.filter((k) => (!k.nurPc || !ohnePc) && (!k.nurDateien || dateien)).map((k) => (
              <li key={k.name}>
                <strong>{k.name}</strong>
                <span>{k.hint}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
});

function Canvas({
  items,
  jiraStory,
  office,
  mail,
  teams,
  aktiv,
  dateien,
  schliessen,
}: {
  items: CanvasItem[];
  jiraStory?: (canvasId: string) => boolean;
  office?: OfficeAktionen;
  mail?: MailAktionen;
  teams?: TeamsAktionen;
  aktiv?: (canvasId: string | null) => void;
  dateien: boolean;
  /** Reiter schließen; nachbar: Schlüssel des Reiters, der danach den Fokus bekommt */
  schliessen: (schluessel: string, nachbar: string | null) => void;
}) {
  // Eigene Auswahl als Schlüssel des Reiters (lib/canvasHistorie.ts), nicht als Position: Schließen verschiebt die Positionen
  const [picked, setPicked] = useState<string | null>(null);
  // "Ergebnis ansehen" in der Tafel Vorgänge oder Wiederöffnen aus der Historie (lib/canvasWahl.ts): ein neuer Wunsch wählt das Element
  // mit dieser Kennung oder stelle, noch im selben Render (kein Zwischenbild). Ein Wunsch, der schon galt, bevor dieses Canvas entstand,
  // zählt nicht.
  const wunsch = useSelect(canvasWunsch, (w) => w);
  const [gesehen, setGesehen] = useState(wunsch.n);
  if (wunsch.n !== gesehen) {
    setGesehen(wunsch.n);
    const i = wunsch.stelle ? items.findIndex((it) => it.stelle === wunsch.stelle) : wunsch.id ? canvasIndex(items, wunsch.id) : -1;
    if (i >= 0) setPicked(i === items.length - 1 ? null : canvasSchluessel(items[i], i));
  }
  // Ohne eigene Auswahl (oder wenn der gewählte Reiter zu ist) zeigt das Canvas immer das Neueste.
  const gewaehlt = picked === null ? -1 : items.findIndex((it, i) => canvasSchluessel(it, i) === picked);
  if (picked !== null && gewaehlt < 0) setPicked(null);
  const index = gewaehlt >= 0 ? gewaehlt : items.length - 1;
  const item = items[index];
  const schluessel = canvasSchluessel(item, index);
  // Den offenen Reiter dem Kern melden: beim Zeigen, beim Wechsel, nach einer Überarbeitung (neue Kennung) und wenn ein Element dazukommt,
  // während ein älterer Reiter gewählt bleibt (sonst hielte das Modell das Neue für offen). Fortschritt am selben Element meldet nichts.
  const offeneId = item.id ?? null;
  const kennungen = items.map((it) => it.id ?? "").join("|");
  useEffect(() => {
    aktiv?.(offeneId);
  }, [offeneId, kennungen, aktiv]);
  // Welcher Reiter offen ist, braucht auch das Werkzeug canvas_schliessen ohne Kennung (lib/wamo.ts)
  useEffect(() => {
    canvasOffen.set(() => schluessel);
  }, [schluessel]);
  useEffect(() => () => canvasOffen.set(() => null), []);
  // Knöpfe und Formulare am Element bleiben über Überarbeitungen stehen (ein offenes Mail-Formular schickt dann die neue Fassung)
  const stelle = item.stelle ?? item.id ?? item.title;

  return (
    <div className="canvas-board">
      <nav className="canvas-tabs" aria-label="Reiter des Canvas">
        {items.map((it, i) => {
          const k = canvasSchluessel(it, i);
          // Schlüssel des Nachbarn nach dem Schließen (rechts, sonst links): bei einem Schlüssel aus der Position rückt der rechte nach
          const nachbar = i + 1 < items.length ? canvasSchluessel(items[i + 1], i) : i > 0 ? canvasSchluessel(items[i - 1], i - 1) : null;
          return (
            <span key={k} className="canvas-tab-gruppe" data-offen={i === index || undefined}>
              <button
                type="button"
                className="canvas-tab"
                data-reiter={k}
                aria-current={i === index}
                onClick={() => setPicked(i === items.length - 1 ? null : k)}
              >
                {it.title}
              </button>
              <button
                type="button"
                className="canvas-tab-zu"
                aria-label={`${it.title} schließen`}
                title="Schließen (bleibt in der Historie)"
                onClick={() => {
                  // War es der gezeigte Reiter, zeigt das Canvas danach den Nachbarn, der auch den Fokus bekommt (ist er der neueste: keine
                  // eigene Auswahl, das Canvas folgt wieder dem Neuesten)
                  if (i === index) setPicked(i < items.length - 2 ? nachbar : null);
                  schliessen(k, nachbar);
                }}
              >
                <span aria-hidden="true">×</span>
              </button>
            </span>
          );
        })}
      </nav>
      <article className="canvas-item">
        <header className="canvas-item-head">
          <span className="eyebrow">{artText(item.kind)}</span>
          <h2>{item.title}</h2>
          {item.geteilt && (
            <p className="canvas-geteilt">
              Geteilt von {item.geteilt.von ?? "jemandem"}, {item.geteilt.recht === "bearbeiten" ? "du darfst bearbeiten" : "nur lesen"}
            </p>
          )}
          <CanvasTeilen item={item} />
          <JiraStoryKnopf item={item} anfragen={jiraStory} />
          {office && <CanvasSpeichern key={stelle} item={item} office={office} />}
          {dateien && <CanvasHerunterladen key={`laden-${stelle}`} item={item} />}
          {mail && <CanvasMail key={`mail-${stelle}`} item={item} mail={mail} />}
          {teams && <CanvasTeams key={`teams-${stelle}`} item={item} teams={teams} />}
        </header>
        <CanvasBody item={item} />
      </article>
    </div>
  );
}

/** "Teilen" nur für eigene, gespeicherte Elemente (id aus der Datenbank oder gespeichertes Auftragsergebnis). */
function CanvasTeilen({ item }: { item: CanvasItem }) {
  if (item.geteilt) return null; // fremde Arbeit teilt nur ihr Besitzer
  const id = item.teilbar?.id ?? (istUuid(item.id) ? item.id : null);
  if (!id) return null;
  // Ergebnisse von Entwicklungsaufträgen (teilbar) nur zum Lesen
  const ziel = { art: "canvas" as const, id, titel: item.title, projekt: item.teilbar?.projekt, nurLesen: Boolean(item.teilbar) };
  return <TeilenKnopf key={id} ziel={ziel} />;
}

/** Nach so vielen Sekunden ohne Antwort des Kerns gibt der Knopf wieder frei (PDF über Word dauert bis 45 s, dazu der Tunnel). */
const SPEICHERN_FRIST_MS = 90_000;

/**
 * "Als Word, Excel, PowerPoint, PDF speichern": nur für eigene, gespeicherte Elemente und nur in Formaten, die der Kern in betrieb.office
 * meldet (Admin oder freigeschaltetes Mitglied, PC-Steuerung an, der Host kann es; voice-core/office_werkzeuge.py). Dazu
 * "Als OneNote-Seite", wenn der Kern
 * betrieb.onenote meldet (voice-core/onenote_werkzeuge.py): Der Klick legt nur die Freigabekarte an. Bis die Antwort kommt (Nachricht
 * "datei" oder "onenote"), sind die Knöpfe gesperrt: kein Doppelklick, keine zweite Datei.
 */
function CanvasSpeichern({ item, office }: { item: CanvasItem; office: OfficeAktionen }) {
  const verfuegbar = useSelect(wamo, (s) => s.betrieb?.office);
  const onenoteAn = useSelect(wamo, (s) => s.betrieb?.onenote);
  const antworten = useSelect(wamo, (s) => s.dateiAntworten);
  const [laeuft, setLaeuft] = useState<{ format: OfficeFormat | "onenote"; bei: number } | null>(null);
  if (laeuft && antworten !== laeuft.bei) setLaeuft(null); // Antwort da (Erfolg oder Fehler): wieder frei
  useEffect(() => {
    if (!laeuft) return;
    const uhr = setTimeout(() => setLaeuft(null), SPEICHERN_FRIST_MS);
    return () => clearTimeout(uhr);
  }, [laeuft]);
  const formate = exportFormate(item, verfuegbar);
  const onenote = office.onenote && onenoteMoeglich(item, onenoteAn) ? office.onenote : undefined;
  if ((!formate.length && !onenote) || !item.id) return null;
  const id = item.id;
  return (
    <div className="canvas-export" role="group" aria-label="Als Datei am PC speichern">
      {formate.map((f) => (
        <button
          key={f}
          type="button"
          className="btn-secondary btn-small"
          disabled={laeuft !== null}
          aria-busy={laeuft?.format === f ? true : undefined}
          onClick={() => {
            if (laeuft === null && office.speichern(id, f)) setLaeuft({ format: f, bei: antworten });
          }}
        >
          {knopfText(f)}
        </button>
      ))}
      {onenote && (
        <button
          type="button"
          className="btn-secondary btn-small"
          disabled={laeuft !== null}
          aria-busy={laeuft?.format === "onenote" ? true : undefined}
          onClick={() => {
            if (laeuft === null && onenote(id)) setLaeuft({ format: "onenote", bei: antworten });
          }}
        >
          {ONENOTE_KNOPF}
        </button>
      )}
    </div>
  );
}

function CanvasBody({ item }: { item: CanvasItem }) {
  switch (item.kind) {
    case "tabelle":
      return (
        <div className="canvas-table-wrap" tabIndex={0} role="region" aria-label={`Tabelle: ${item.title}`}>
          <table className="canvas-table">
            <thead>
              <tr>
                {item.columns.map((c, i) => (
                  <th key={i}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {item.rows.map((row, r) => (
                <tr key={r}>
                  {item.columns.map((_, c) => (
                    <td key={c}>{row[c] ?? ""}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "code":
      return <CodeView text={item.text} language={item.language} title={item.title} />;
    case "dokument":
      return <div className="canvas-doc">{renderMarkdown(item.text)}</div>;
    case "mermaid":
      return (
        <MermaidView
          key={item.id ?? item.title} // je Element eigener Zustand: ein Klick gilt nie für ein anderes Diagramm
          source={item.text}
          title={item.title}
          geteiltVon={item.geteilt ? (item.geteilt.von ?? null) : undefined}
        />
      );
    case "bild":
      return <BildAnsicht item={item} />;
  }
}

function CodeView({ text, language, title }: { text: string; language?: string; title: string }) {
  // Die Knopfbeschriftung bleibt "Kopieren"; die Bestätigung ist ein Chip in einer Live-Region daneben (lib/kopieren.ts)
  const [status, setStatus] = useState<KopierStatus>("");
  const uhr = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (uhr.current) clearTimeout(uhr.current);
    },
    [],
  );
  const kopieren = async () => {
    let neu: KopierStatus = "kopiert";
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      neu = "fehler"; // z. B. Zwischenablage nicht erlaubt
    }
    setStatus(neu);
    if (uhr.current) clearTimeout(uhr.current);
    uhr.current = setTimeout(() => setStatus(""), KOPIERT_MS);
  };
  return (
    <div className="canvas-code">
      <div className="canvas-code-bar">
        <span>{language || "text"}</span>
        <span className="canvas-code-aktion">
          <span className="canvas-chip" aria-live="polite" data-art={status === "fehler" ? "fehler" : undefined}>
            {kopierChipText(status)}
          </span>
          <button type="button" onClick={() => void kopieren()}>
            Kopieren
          </button>
        </span>
      </div>
      <pre tabIndex={0} role="region" aria-label={`Code: ${title}`}>
        <code>{text}</code>
      </pre>
    </div>
  );
}

// Mermaid im WMC-Theme: schwarze Knotenränder, graue Linien, Hinweise mit roter Kante
const MERMAID_HELL = {
  fontFamily: '"Arial Narrow", "Liberation Sans Narrow", "Roboto Condensed", Arial, sans-serif',
  primaryColor: "#FFFFFF",
  primaryTextColor: "#000000",
  primaryBorderColor: "#000000",
  lineColor: "#6B6B6B",
  secondaryColor: "#F3F3F3",
  tertiaryColor: "#FFFFFF",
  clusterBkg: "#F3F3F3",
  clusterBorder: "#D9D9D9",
  edgeLabelBackground: "#FFFFFF",
  noteBkgColor: "#F3F3F3",
  noteBorderColor: "#F40E0E",
  noteTextColor: "#000000",
};
const MERMAID_DUNKEL = {
  ...MERMAID_HELL,
  darkMode: true,
  primaryColor: "#1A1A1A",
  primaryTextColor: "#F3F3F3",
  primaryBorderColor: "#F3F3F3",
  lineColor: "#A3A3A3",
  secondaryColor: "#0E0E0E",
  tertiaryColor: "#1A1A1A",
  clusterBkg: "#1A1A1A",
  clusterBorder: "#2E2E2E",
  edgeLabelBackground: "#0E0E0E",
  noteBkgColor: "#1A1A1A",
  noteTextColor: "#F3F3F3",
};

/**
 * Mermaid-Diagramm als Bild: das SVG landet nie im DOM der Oberfläche (kein innerHTML), sondern als blob:-URL in einem
 * <img> (dort laufen weder Skripte noch Verweise). Von anderen geteilte Diagramme werden erst nach einem Klick
 * gezeichnet.
 */
function MermaidView({ source, title, geteiltVon }: { source: string; title: string; geteiltVon?: string | null }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const thema = useThema(); // ein Wechsel Hell oder Dunkel zeichnet das Diagramm mit den passenden Farben neu
  const [error, setError] = useState<string | null>(null);
  const [freigegeben, setFreigegeben] = useState(geteiltVon === undefined);
  const [bild, setBild] = useState<{ url: string; breite: number | null } | null>(null);

  useEffect(() => {
    if (!freigegeben) return;
    let cancelled = false;
    let url: string | null = null;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        const dark = thema === "dunkel";
        // strict: Mermaid säubert das SVG selbst (kein HTML/Script aus dem Diagrammtext).
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "base",
          themeVariables: dark ? MERMAID_DUNKEL : MERMAID_HELL,
          // keine eigene Fehlergrafik von Mermaid im Dokument; Fehler zeigen wir selbst
          suppressErrorRendering: true,
        });
        const { svg } = await mermaid.render(`m${id}`, source);
        if (cancelled) return;
        const max = /max-width:\s*([\d.]+)px/.exec(svg);
        url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
        setBild({ url, breite: max ? Number(max[1]) : null });
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setBild(null);
        setError(e instanceof Error ? e.message.slice(0, 300) : "Diagramm konnte nicht gezeichnet werden.");
      }
    })();
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [source, id, freigegeben, thema]);

  if (!freigegeben) {
    return (
      <div className="canvas-mermaid-wartet">
        <p className="notice">Diagramm von {geteiltVon ?? "jemand anderem"}: wird erst nach deinem Klick gezeichnet.</p>
        <button type="button" className="btn-secondary btn-small" onClick={() => setFreigegeben(true)}>
          Diagramm anzeigen
        </button>
      </div>
    );
  }
  return (
    <>
      <div className="canvas-mermaid" tabIndex={0} role="region" aria-label={`Diagramm: ${title}`}>
        {bild && (
          // eslint-disable-next-line @next/next/no-img-element -- lokale blob:-URL, next/image kann sie nicht optimieren
          <img
            src={bild.url}
            alt={`Diagramm: ${title}`}
            style={{ width: "100%", maxWidth: bild.breite ? `${bild.breite}px` : undefined }}
          />
        )}
      </div>
      {error && (
        <>
          <p className="notice">Diagramm fehlerhaft: {error}</p>
          <CodeView text={source} language="mermaid" title={title} />
        </>
      )}
    </>
  );
}

/** Kleines, sicheres Markdown: #-Ueberschriften, Listen, Absaetze, **fett**, `code`. Kein HTML. */
function renderMarkdown(text: string): ReactNode {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flushList = () => {
    if (list.length) {
      blocks.push(
        <ul key={`l${blocks.length}`}>
          {list.map((li, i) => (
            <li key={i}>{inline(li)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    if (bullet) {
      list.push(bullet[1]);
      continue;
    }
    flushList();
    if (heading) {
      const level = heading[1].length;
      const Tag = (["h3", "h4", "h5"] as const)[level - 1];
      blocks.push(<Tag key={`h${blocks.length}`}>{inline(heading[2])}</Tag>);
    } else if (line.trim()) {
      blocks.push(<p key={`p${blocks.length}`}>{inline(line)}</p>);
    }
  }
  flushList();
  return blocks;
}

function inline(text: string): ReactNode {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={i}>{part.slice(1, -1)}</code>;
    return <Fragment key={i}>{part}</Fragment>;
  });
}
