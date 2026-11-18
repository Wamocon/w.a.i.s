"use client";

import { memo, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { KernFehler, kernJson } from "@/lib/kernApi";
import { gleicheRechte, personZeile, pruefeRechteListe, rechteGruppen, type RechteListe, type RechtePerson } from "@/lib/githubZugang";
import { Block } from "./Block";

const PFAD = "/admin/github-rechte";

type Stand = { art: "laedt" } | { art: "fehler"; text: string } | { art: "ok"; liste: RechteListe };

function fehlerSatz(e: unknown): string {
  if (e instanceof KernFehler && e.status === 403) return "Die Rechte der GitHub-Zugänge stellen nur Admins ein.";
  if (e instanceof KernFehler && e.status === 404) return "Der Kern kennt diese Einstellung noch nicht (Version vor Plan C).";
  if (e instanceof KernFehler && e.status === 429) return "Zu viele Anfragen, bitte gleich noch einmal.";
  if (e instanceof KernFehler && e.status === 400 && e.message && !/^Fehler \d+$/.test(e.message)) return e.message;
  if (e instanceof KernFehler && e.status === 503 && e.message && !/^Fehler \d+$/.test(e.message)) return e.message;
  return "Die Einstellung ist gerade nicht erreichbar.";
}

/** Eine Person: Stand ihres Tokens, je erlaubbarem Recht ein Kästchen, Speichern nur bei einer Änderung. */
function Person({ person, gruppen, erlaubbar, onGespeichert, onWartet }: {
  person: RechtePerson;
  gruppen: ReturnType<typeof rechteGruppen>;
  erlaubbar: readonly string[];
  onGespeichert: (userId: string, ausnahmen: string[]) => void;
  onWartet: (an: boolean) => void;
}) {
  const [wahl, setWahl] = useState<string[]>(person.scopesAusnahmen);
  const [wartet, setWartet] = useState(false);
  const [meldung, setMeldung] = useState<{ text: string; fehler: boolean } | null>(null);
  const kopf = useId();
  const geaendert = !gleicheRechte(wahl, person.scopesAusnahmen);

  const speichern = async () => {
    if (wartet || !geaendert) return;
    setWartet(true);
    onWartet(true);
    setMeldung(null);
    try {
      const antwort = (await kernJson(PFAD, "POST", { user_id: person.userId, scopes_ausnahmen: [...wahl].sort() })) as {
        scopes_ausnahmen?: unknown;
      };
      // die Antwort nur mit Scopes, die hier ein Kästchen haben (sonst ginge beim nächsten Speichern ein unsichtbarer Wert mit)
      const neu = (Array.isArray(antwort?.scopes_ausnahmen) ? antwort.scopes_ausnahmen : [...wahl])
        .filter((s): s is string => typeof s === "string" && erlaubbar.includes(s))
        .sort();
      onGespeichert(person.userId, neu);
      setWahl(neu);
      setMeldung({ text: "Gespeichert. Gilt ab dem nächsten Speichern, Prüfen oder Auftrag dieser Person.", fehler: false });
    } catch (e) {
      setMeldung({ text: fehlerSatz(e), fehler: true });
    }
    setWartet(false);
    onWartet(false);
  };

  return (
    <li className="nm-person">
      <details>
        <summary>
          <span className="nm-name" id={kopf}>
            {person.name || "ohne Namen"}
          </span>
          {person.rolle === "admin" && <span className="nm-rolle"> Admin</span>}
          <span className="ez-klein"> {personZeile(person)}</span>
        </summary>
        <fieldset aria-labelledby={kopf} disabled={wartet} className="gr-rechte">
          {gruppen.map((g) => (
            <div key={g.gruppe} className="gr-gruppe">
              <p className="ez-klein">
                <strong>{g.gruppe}</strong>
              </p>
              {g.rechte.map((r) => (
                <label key={r.scope} className="gr-recht">
                  <input
                    type="checkbox"
                    checked={wahl.includes(r.scope)}
                    onChange={(e) => setWahl((alt) => (e.target.checked ? [...alt, r.scope] : alt.filter((s) => s !== r.scope)))}
                  />{" "}
                  {r.text}
                </label>
              ))}
            </div>
          ))}
        </fieldset>
        <div className="mz-knoepfe">
          <button type="button" className="btn-primary btn-small" aria-disabled={wartet || !geaendert || undefined} onClick={() => void speichern()}>
            {wartet ? "wird gespeichert …" : "Speichern"}
          </button>
          {geaendert && !wartet && (
            <button type="button" className="btn-secondary btn-small" onClick={() => setWahl(person.scopesAusnahmen)}>
              Zurücksetzen
            </button>
          )}
        </div>
        <p className="mz-meldung" role="status">
          {meldung && !meldung.fehler ? meldung.text : ""}
        </p>
        {meldung?.fehler && (
          <p className="mz-meldung" role="alert" data-fehler>
            Fehler: {meldung.text}
          </p>
        )}
      </details>
    </li>
  );
}

/**
 * Block "Rechte der GitHub-Zugänge" im Abschnitt "Neue Mitglieder" (nur Admin, Entscheidung vom 18.11.2026, C.2.8): Standard für alle ist
 * eine Erlaubnisliste, ein klassisches Token darf nur repo oder public_repo und lesende Rechte haben. Hier erlaubt ein Admin je Person
 * einzelne Scopes aus SCOPES_AUSNAHMEN (die Liste kommt vom Kern: voice-core/github_zugang_api.py, Tabelle github_rechte, Migration 0027);
 * delete_repo, site_admin, admin:enterprise und dessen Teilrechte bietet sie nie an. Jede Änderung steht beim Kern in actions.
 */
export const GithubRechte = memo(function GithubRechte() {
  const [stand, setStand] = useState<Stand>({ art: "laedt" });
  const [speichert, setSpeichert] = useState(0); // laufende Speichervorgänge: solange kein Neu laden (es würde sie überschreiben)
  const aktiv = useRef(true);
  const erlaubbar = stand.art === "ok" ? stand.liste.erlaubbar : null;
  const gruppen = useMemo(() => (erlaubbar ? rechteGruppen(erlaubbar) : []), [erlaubbar]);
  const wartet = useCallback((an: boolean) => setSpeichert((n) => Math.max(0, n + (an ? 1 : -1))), []);

  const neu = useCallback(async () => {
    setStand({ art: "laedt" });
    let s: Stand;
    try {
      const liste = pruefeRechteListe(await kernJson(PFAD));
      s = liste ? { art: "ok", liste } : { art: "fehler", text: "Unerwartete Antwort des Kerns." };
    } catch (e) {
      s = { art: "fehler", text: fehlerSatz(e) };
    }
    if (aktiv.current) setStand(s);
  }, []);

  useEffect(() => {
    aktiv.current = true;
    const erster = setTimeout(() => void neu(), 0);
    return () => {
      aktiv.current = false;
      clearTimeout(erster);
    };
  }, [neu]);

  const gespeichert = useCallback((userId: string, ausnahmen: string[]) => {
    setStand((s) =>
      s.art === "ok"
        ? { art: "ok", liste: { ...s.liste, personen: s.liste.personen.map((p) => (p.userId === userId ? { ...p, scopesAusnahmen: ausnahmen } : p)) } }
        : s,
    );
  }, []);

  return (
    <Block titel="Rechte der GitHub-Zugänge">
      <p className="ez-klein">
        Standard für alle: Ein klassisches GitHub-Token darf nur repo oder public_repo und lesende Rechte haben. Hier erlaubst du einer
        Person einzelne weitere Rechte. delete_repo, site_admin und admin:enterprise sind nie erlaubt. Für fein-granulare Tokens gilt diese
        Liste nicht; dort zählen die Rechte am Repo.
      </p>
      {stand.art === "laedt" && (
        <p className="ez-leer" role="status">
          Lade die Rechte ...
        </p>
      )}
      {stand.art === "fehler" && (
        <p className="gv-meldung" role="alert" data-art="fehler">
          {stand.text}
        </p>
      )}
      {stand.art === "ok" &&
        (stand.liste.personen.length === 0 ? (
          <p className="ez-leer">Keine Profile.</p>
        ) : (
          <ul className="nm-liste" aria-label="Rechte der GitHub-Zugänge je Person">
            {stand.liste.personen.map((p) => (
              <Person
                key={p.userId}
                person={p}
                gruppen={gruppen}
                erlaubbar={stand.liste.erlaubbar}
                onGespeichert={gespeichert}
                onWartet={wartet}
              />
            ))}
          </ul>
        ))}
      <button
        type="button"
        className="btn-secondary"
        onClick={() => stand.art !== "laedt" && speichert === 0 && void neu()}
        aria-disabled={stand.art === "laedt" || speichert > 0}
      >
        Neu laden
      </button>
    </Block>
  );
});
