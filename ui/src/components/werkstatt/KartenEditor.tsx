"use client";

import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { fehlerBildAus, karteAendern, karteAnlegen } from "@/lib/werkstattApi";
import {
  GRENZEN,
  formularPruefen,
  gruppenAus,
  hatSteuerzeichen,
  mitGruppe,
  normalisieren,
  zeichenBudget,
  type FeldName,
  type Formular,
  type Problem,
} from "@/lib/werkstattKarten";
import { WERKZEUGE, WISSEN_ARTEN, type FehlerBild, type Karte as KarteTyp, type WissenArt, type Werkzeug } from "@/lib/werkstattTypen";
import { FehlerHinweis, Karte, Pille } from "./Bausteine";

/**
 * Editor für einen Use Case, von null an: Gruppe (vorhandene oder neue), Kennung (wird vorgeschlagen), Titel, Aufgabe, erwartetes
 * Ergebnis, Fehlerfall, Lernziel, Dauer, Wissen und Werkzeuge. Daneben die Vorschau der gedruckten Karte und das Zeichenbudget des
 * Kerns. Gespeichert wird immer als Entwurf; veröffentlicht wird erst mit dem Vierschritt darunter. Die Prüfung hier entspricht den
 * Grenzen der Datenbank (lib/werkstattKarten.ts), entschieden wird im Dienst.
 */

type Props = {
  start: Formular;
  karten: readonly KarteTyp[];
  /** die festen Gruppen des Katalogs (Buchstabe zu Name) */
  gruppen: Readonly<Record<string, string>>;
  onGespeichert: (id: string) => void;
  onSchliessen: () => void;
};

function Zaehler({ id, wert, max }: { id: string; wert: string; max: number }) {
  return (
    <span id={id} className="ws-zaehler ws-mono">
      {normalisieren(wert).length} von {max}
    </span>
  );
}

export function KartenEditor({ start, karten, gruppen: gruppenKarte, onGespeichert, onSchliessen }: Props) {
  const id = useId();
  const [f, setF] = useState<Formular>(start);
  const [probleme, setProbleme] = useState<Problem[]>([]);
  const [fehler, setFehler] = useState<FehlerBild | null>(null);
  const [laeuft, setLaeuft] = useState(false);
  const zusammenfassung = useRef<HTMLDivElement>(null);
  const gruppen = gruppenAus(gruppenKarte, karten);
  const text = (feld: FeldName) => probleme.find((p) => p.feld === feld)?.text;
  const bei = (feld: FeldName, extra?: string) => ({
    "aria-invalid": text(feld) ? (true as const) : undefined,
    "aria-describedby": [text(feld) ? `${id}-${feld}-f` : "", extra ?? ""].filter(Boolean).join(" ") || undefined,
  });
  const fehlerZeile = (feld: FeldName): ReactNode => (text(feld) ? <p id={`${id}-${feld}-f`} className="ws-feld-fehler">{text(feld)}</p> : null);
  const aendere = (teil: Partial<Formular>) => setF((alt) => ({ ...alt, ...teil }));

  const wissenstext = f.wissen === "Eigener Text" ? normalisieren(f.wissenstext) : "";
  const budget = zeichenBudget(karten, { id: f.id, wissen: f.wissen, wissenstext: wissenstext || null });

  const speichern = async (e: FormEvent) => {
    e.preventDefault();
    if (laeuft) return;
    setFehler(null);
    const r = formularPruefen(f, karten, gruppenKarte);
    setProbleme(r.probleme);
    if (!r.eingabe) {
      requestAnimationFrame(() => zusammenfassung.current?.focus());
      return;
    }
    setLaeuft(true);
    try {
      // Beim Anlegen vergibt der Dienst die Kennung; die Antwort nennt die wirkliche (die Wahl hier war nur ein Vorschlag).
      const ergebnis = f.bestehend ? await karteAendern(r.eingabe) : await karteAnlegen(r.eingabe);
      onGespeichert(ergebnis.karte?.id ?? r.eingabe.id);
    } catch (x) {
      setFehler(fehlerBildAus(x));
    } finally {
      setLaeuft(false);
    }
  };

  const werkzeugWahl = (w: Werkzeug, an: boolean) => aendere({ werkzeuge: an ? [...f.werkzeuge, w] : f.werkzeuge.filter((x) => x !== w) });
  const titel = f.bestehend ? `Use Case ${f.id} bearbeiten` : "Neuen Use Case aufbauen";

  return (
    <div className="ws-gitter ws-gitter-breit">
      <Karte titel={titel} rechts={<button type="button" className="btn-secondary btn-small" onClick={onSchliessen}>Editor schließen</button>}>
        <form onSubmit={(e) => void speichern(e)} noValidate style={{ display: "grid", gap: 12 }}>
          <div className="ws-zeile">
            <div className="ws-feld">
              <label htmlFor={`${id}-gruppe`}>Gruppe</label>
              <select id={`${id}-gruppe`} value={f.gruppeWahl} disabled={f.bestehend} onChange={(e) => setF(mitGruppe(f, e.target.value, karten))} {...bei("gruppe")}>
                <option value="">bitte wählen</option>
                {gruppen.map((g) => (
                  <option key={g.buchstabe} value={g.buchstabe}>{g.buchstabe} {g.name}</option>
                ))}
              </select>
              {fehlerZeile("gruppe")}
            </div>
            <div className="ws-feld">
              <label htmlFor={`${id}-id`}>Kennung (vorgeschlagen)</label>
              <input id={`${id}-id`} className="ws-mono" value={f.id} readOnly size={6} {...bei("id")} />
              {fehlerZeile("id")}
            </div>
          </div>
          <div className="ws-feld">
            <label htmlFor={`${id}-titel`}>Titel</label>
            <input id={`${id}-titel`} value={f.titel} maxLength={GRENZEN.titel + 20} onChange={(e) => aendere({ titel: e.target.value })} {...bei("titel", `${id}-titel-z`)} />
            <Zaehler id={`${id}-titel-z`} wert={f.titel} max={GRENZEN.titel} />
            {fehlerZeile("titel")}
          </div>
          <div className="ws-feld">
            <label htmlFor={`${id}-aufgabe`}>Aufgabe für den Gast (Sprechprobe oder Handlung)</label>
            <textarea id={`${id}-aufgabe`} rows={2} value={f.aufgabe} onChange={(e) => aendere({ aufgabe: e.target.value })} {...bei("aufgabe", `${id}-aufgabe-z`)} />
            <Zaehler id={`${id}-aufgabe-z`} wert={f.aufgabe} max={GRENZEN.aufgabe} />
            {fehlerZeile("aufgabe")}
          </div>
          <div className="ws-feld">
            <label htmlFor={`${id}-erwartung`}>Erwartetes Ergebnis</label>
            <textarea id={`${id}-erwartung`} rows={2} value={f.erwartung} onChange={(e) => aendere({ erwartung: e.target.value })} {...bei("erwartung", `${id}-erwartung-z`)} />
            <Zaehler id={`${id}-erwartung-z`} wert={f.erwartung} max={GRENZEN.erwartung} />
            {fehlerZeile("erwartung")}
          </div>
          {(hatSteuerzeichen(f.aufgabe) || hatSteuerzeichen(f.erwartung) || hatSteuerzeichen(f.wissenstext)) && (
            <p className="ws-klein">Zeilenumbrüche werden beim Speichern zu Leerzeichen, denn Kartentexte stehen in einer Zeile.</p>
          )}
          <div className="ws-feld">
            <label className="ws-pruef">
              <input type="checkbox" checked={f.fehlerfall} onChange={(e) => aendere({ fehlerfall: e.target.checked })} />
              <span>Fehlerfall: Dieser Use Case prüft absichtlich ein Fehlverhalten</span>
            </label>
            <label htmlFor={`${id}-fehlertext`} className="sr-only">Erwarteter Fehler</label>
            <input id={`${id}-fehlertext`} value={f.fehlertext} disabled={!f.fehlerfall} maxLength={GRENZEN.fehler + 20} placeholder="Welcher Fehler wird erwartet?" onChange={(e) => aendere({ fehlertext: e.target.value })} {...bei("fehlertext")} />
            {fehlerZeile("fehlertext")}
          </div>
          <div className="ws-zeile">
            <div className="ws-feld" style={{ flex: "1 1 180px" }}>
              <label htmlFor={`${id}-lernziel`}>Lernziel (optional)</label>
              <input id={`${id}-lernziel`} value={f.lernziel} maxLength={GRENZEN.lernziel + 10} onChange={(e) => aendere({ lernziel: e.target.value })} {...bei("lernziel")} />
              {fehlerZeile("lernziel")}
            </div>
            <div className="ws-feld">
              <label htmlFor={`${id}-dauer`}>Dauer in Minuten</label>
              <input id={`${id}-dauer`} type="number" min={GRENZEN.dauerMin} max={GRENZEN.dauerMax} inputMode="numeric" value={f.dauer} onChange={(e) => aendere({ dauer: e.target.value })} {...bei("dauer")} />
              {fehlerZeile("dauer")}
            </div>
          </div>
          <div className="ws-feld">
            <label htmlFor={`${id}-wissen`}>Wissen für W.A.I.S. an dieser Karte</label>
            <select id={`${id}-wissen`} value={f.wissen} onChange={(e) => aendere({ wissen: e.target.value as WissenArt })}>
              {WISSEN_ARTEN.map((w) => (
                <option key={w} value={w}>{w}</option>
              ))}
            </select>
          </div>
          {f.wissen === "Eigener Text" && (
            <div className="ws-feld">
              <label htmlFor={`${id}-wtext`}>Eigener Wissenstext (zählt gegen das Zeichenbudget des Kerns)</label>
              <textarea id={`${id}-wtext`} rows={4} value={f.wissenstext} onChange={(e) => aendere({ wissenstext: e.target.value })} {...bei("wissenstext", `${id}-wtext-z`)} />
              <Zaehler id={`${id}-wtext-z`} wert={f.wissenstext} max={GRENZEN.wissenstext} />
              {fehlerZeile("wissenstext")}
              <p className="ws-klein">
                Der Text gilt als Wissen, nie als Anweisung. Nicht erlaubt sind Markup, Rollenzeilen (zum Beispiel „System:“) und unsichtbare Zeichen.
                Anweisungen an W.A.I.S. im Text lehnt die Prüfung beim Veröffentlichen ab.
              </p>
              {fehler?.code === "ungueltig" && (
                <p className="ws-feld-fehler">Der Dienst hat den Text abgelehnt. Prüfe ihn auf Markup, Rollenzeilen und unsichtbare Zeichen.</p>
              )}
            </div>
          )}
          <fieldset className="ws-gruppe">
            <legend>Benötigte Werkzeuge</legend>
            <div>
              {WERKZEUGE.map((w) => (
                <label key={w} className="ws-pruef">
                  <input type="checkbox" checked={f.werkzeuge.includes(w)} onChange={(e) => werkzeugWahl(w, e.target.checked)} />
                  <span>{w}</span>
                </label>
              ))}
            </div>
          </fieldset>
          {probleme.length > 0 && (
            <div ref={zusammenfassung} className="ws-fehler" role="alert" tabIndex={-1}>
              <span>Bitte prüfe die Karte: {probleme.map((p) => p.text).join(" ")}</span>
            </div>
          )}
          {fehler && <FehlerHinweis fehler={fehler} />}
          <div className="ws-aktionen">
            <button type="submit" className="btn-primary" disabled={laeuft}>Als Entwurf speichern</button>
            <button type="button" className="btn-secondary" disabled={laeuft} onClick={onSchliessen}>Verwerfen</button>
          </div>
        </form>
      </Karte>
      <Karte titel="Vorschau der gedruckten Karte">
        <Vorschau f={f} />
        <dl className="ws-liste">
          <div>
            <dt>Katalog</dt>
            <dd className="ws-mono">{budget.genutzt} von {budget.max} Zeichen</dd>
          </div>
          <div>
            <dt>Karten mit eigenem Wissenstext</dt>
            <dd className="ws-mono">{budget.eintraege} von {budget.eintraegeMax}</dd>
          </div>
        </dl>
        <div
          className="ws-meter"
          role="img"
          aria-label={`Katalog: ${budget.genutzt} von ${budget.max} Zeichen${budget.ueber ? ", überschritten" : ""}`}
          data-ueber={budget.ueber || undefined}
        >
          <span style={{ width: `${Math.min(100, (budget.genutzt / budget.max) * 100)}%` }} />
        </div>
        {budget.ueber && <p className="ws-feld-fehler">Das Katalogbudget ist überschritten. Kürze die Wissenstexte, sonst lässt sich nicht veröffentlichen.</p>}
        {budget.zuViele && <p className="ws-feld-fehler">Mehr als {budget.eintraegeMax} Karten mit eigenem Wissenstext nimmt der Kern nicht.</p>}
        <p className="ws-klein">Der Kern lädt aus dem Katalog höchstens {budget.eintraegeMax} Wissenstexte mit zusammen {budget.max} Zeichen, je Karte höchstens {GRENZEN.wissenstext}.</p>
      </Karte>
    </div>
  );
}

/** Die Karte, wie der Gast sie in der Hand hält: Kennung, Dauer, Titel, Aufgabe, Erwartung, Fehlerfall und Werkzeuge. */
function Vorschau({ f }: { f: Formular }) {
  const dauer = /^\d{1,2}$/.test(f.dauer.trim()) ? f.dauer.trim() : "?";
  return (
    <div className="ws-gedruckt">
      <div className="ws-karte-kopf">
        <Pille art="akzent">{f.id || "ohne Kennung"}</Pille>
        <span className="ws-klein ws-mono">{dauer} Min.</span>
      </div>
      <h3>{normalisieren(f.titel) || "Titel der Karte"}</h3>
      <p className="ws-klein">Sag oder tu:</p>
      <p>{normalisieren(f.aufgabe) || "Aufgabe für den Gast"}</p>
      <p className="ws-klein">Das ist richtig, wenn:</p>
      <p>{normalisieren(f.erwartung) || "Erwartetes Ergebnis"}</p>
      {f.fehlerfall && (
        <p>
          <Pille art="warn">Fehlerfall</Pille> {normalisieren(f.fehlertext) || "Welcher Fehler wird erwartet?"}
        </p>
      )}
      {f.werkzeuge.length > 0 && <p className="ws-klein">Werkzeuge: {WERKZEUGE.filter((w) => f.werkzeuge.includes(w)).join(", ")}</p>}
    </div>
  );
}
