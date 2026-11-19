"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { KernFehler, kernJson } from "@/lib/kernApi";
import {
  ART_TEXT,
  datumDeutsch,
  fehlerText,
  formFehler,
  pruefeAntwort,
  standZeile,
  tokenForm,
  type GithubAktion,
  type GithubZugang as Stand,
} from "@/lib/githubZugang";
import { Ueberschrift } from "@/components/Ueberschrift";

const PFAD = "/github-zugang";
const LINK_FEIN = "https://github.com/settings/personal-access-tokens/new";
const LINK_KLASSISCH = "https://github.com/settings/tokens/new";

type Meldung = { text: string; fehler: boolean } | null;

const WARTET_TEXT: Record<GithubAktion, string> = {
  stand: "wird geladen …",
  speichern: "wird bei GitHub geprüft …",
  pruefen: "wird geprüft …",
  loeschen: "wird gelöscht …",
};

/**
 * Abschnitt "GitHub-Zugang" der Einstellungen (Plan C, docs/persoenliche-zugaenge.md C.4): Die Person hinterlegt ihr eigenes GitHub-Token
 * für Entwicklungsaufträge. Der Kern (voice-core/github_zugang_api.py) prüft es sofort bei GitHub, speichert es nur verschlüsselt und
 * antwortet nur mit Art, Konto, Rechten, Ablauf und den letzten vier Zeichen. Das Feld wird beim Absenden sofort geleert; der Wert steht in
 * keinem Zustand, keiner Meldung und keinem Speicher der Oberfläche. Ohne Zulassung oder bei ausgeschaltetem Schalter nennt die Karte den
 * Grund; Löschen geht immer. Läuft über HTTP am Kern, auch ohne Gespräch.
 */
export const GithubZugang = memo(function GithubZugang() {
  const [stand, setStand] = useState<Stand | null>(null);
  const [meldung, setMeldung] = useState<Meldung>(null);
  const [wartet, setWartet] = useState<GithubAktion | null>(null);
  const [wert, setWert] = useState("");
  const [loeschenFragen, setLoeschenFragen] = useState(false);
  const aktiv = useRef(true);
  const laeuft = useRef(false);
  const kopf = useRef<HTMLHeadingElement>(null);

  const senden = useCallback(async (aktion: GithubAktion, token?: string) => {
    if (laeuft.current) return;
    laeuft.current = true;
    setWartet(aktion);
    setMeldung(null);
    let neu: Stand | null = null;
    let fehler: string | null = null;
    try {
      const daten = aktion === "stand" ? await kernJson(PFAD) : await kernJson(PFAD, "POST", token ? { aktion, token } : { aktion });
      neu = pruefeAntwort(daten);
      if (!neu) fehler = "Unerwartete Antwort des Kerns.";
    } catch (e) {
      const f = e instanceof KernFehler ? e : new KernFehler(0, "");
      fehler = fehlerText(f.status, f.message);
    }
    laeuft.current = false;
    if (!aktiv.current) return;
    setWartet(null);
    if (neu) {
      setStand(neu);
      setMeldung(neu.fehler ? { text: neu.fehler, fehler: true } : neu.ok ? { text: neu.ok, fehler: false } : null);
    } else {
      setMeldung({ text: fehler ?? "Unerwarteter Fehler.", fehler: true }); // der letzte bekannte Stand bleibt stehen
    }
  }, []);

  useEffect(() => {
    aktiv.current = true;
    const erster = setTimeout(() => void senden("stand"), 0);
    return () => {
      aktiv.current = false;
      clearTimeout(erster);
    };
  }, [senden]);

  const form = tokenForm(wert);
  const falsch = formFehler(form);
  const beschaeftigt = wartet !== null;
  const verfuegbar = stand?.verfuegbar === true;
  const hinterlegt = stand?.hinterlegt === true;

  return (
    <div className="mz-inhalt">
      <section className="mz-abschnitt" aria-labelledby="github-zugang-kopf" aria-busy={beschaeftigt || undefined}>
        <Ueberschrift ebene={4} id="github-zugang-kopf" className="mz-ueberschrift" ref={kopf} tabIndex={-1}>
          Eigenes GitHub-Token
        </Ueberschrift>
        <p className="mz-zweck">
          Damit arbeitet W.A.I.S. in Entwicklungsaufträgen mit deinen Repos: lesen, in einer abgeschotteten Umgebung ändern und erst nach
          deinem Klick einen Zweig wamo/&lt;Auftrag&gt; mit Pull Request einreichen. Gemergt wird nie durch W.A.I.S.
        </p>
        <p className="mz-status" data-hinterlegt={hinterlegt || undefined}>
          <span className="mz-marke" aria-hidden="true" />
          <span>{stand ? standZeile(stand) : meldung?.fehler ? "Stand nicht lesbar." : standZeile(null)}</span>
        </p>
        {hinterlegt && stand && stand.art === "klassisch" && stand.scopes.length > 0 && (
          <p className="mz-klein">Rechte laut GitHub: {stand.scopes.join(", ")}.</p>
        )}
        {stand && stand.scopesAusnahmen.length > 0 && (
          <p className="mz-klein">Ein Admin hat dir zusätzlich erlaubt: {stand.scopesAusnahmen.join(", ")}.</p>
        )}
        {hinterlegt && stand?.problem && (
          <p className="mz-meldung" data-fehler>
            Wird gerade nicht benutzt: {stand.problem}
          </p>
        )}
        {stand && !verfuegbar && stand.grund && <p className="mz-offline">{stand.grund}</p>}
        {!stand && meldung?.fehler && (
          <button type="button" className="btn-secondary btn-small" onClick={() => void senden("stand")}>
            Erneut versuchen
          </button>
        )}

        {verfuegbar && (
          <>
            <details key={String(hinterlegt)} className="mz-mehr" open={!hinterlegt}>
              <summary>So erzeugst du das Token</summary>
              <ol className="mz-schritte">
                <li>
                  Empfohlen, fein-granular: Bei GitHub ein neues Token anlegen,{" "}
                  <a href={LINK_FEIN} target="_blank" rel="noopener noreferrer">
                    Fine-grained token (neuer Tab)
                  </a>
                  . Ablauf höchstens 366 Tage, nur die Repos wählen, an denen W.A.I.S. arbeiten soll.
                </li>
                <li>
                  Rechte: Contents (Read and write), Pull requests (Read and write), Metadata (Read). Keine weiteren, besonders nicht
                  Administration, Secrets und Workflows.
                </li>
                <li>
                  Oder klassisch:{" "}
                  <a href={LINK_KLASSISCH} target="_blank" rel="noopener noreferrer">
                    Token (classic) (neuer Tab)
                  </a>{" "}
                  mit Ablaufdatum und dem Recht repo (oder public_repo), dazu höchstens nur lesende Rechte wie read:org. W.A.I.S.
                  lehnt alle anderen ab, etwa workflow, gist, write:org, Paket-Rechte, user-Rechte und admin:*, außer ein Admin erlaubt sie
                  dir; delete_repo, site_admin und admin:enterprise nie.
                </li>
                <li>Das Token hier eintragen. W.A.I.S. zeigt es danach nie wieder an; widerrufen kannst du es jederzeit bei GitHub.</li>
              </ol>
            </details>
            <form
              className="mz-form"
              autoComplete="off"
              onSubmit={(e) => {
                e.preventDefault();
                if (beschaeftigt || laeuft.current || form === "leer" || falsch) return; // nie leeren, ohne zu senden
                const token = wert.trim();
                setWert(""); // der Wert bleibt nicht in der Oberfläche, auch nicht bei einem Fehler
                void senden("speichern", token);
              }}
            >
              <label className="mz-feld">
                <span>{hinterlegt ? "Neues GitHub-Token" : "GitHub-Token"}</span>
                <input
                  type="password"
                  name="wamo-github"
                  value={wert}
                  onChange={(e) => setWert(e.target.value)}
                  autoComplete="new-password"
                  spellCheck={false}
                  autoCapitalize="off"
                  data-1p-ignore
                  data-lpignore="true"
                  placeholder="github_pat_… oder ghp_…"
                  readOnly={beschaeftigt}
                  aria-invalid={falsch ? true : undefined}
                  aria-describedby={falsch ? "github-zugang-falsch" : undefined}
                />
              </label>
              {falsch && (
                <p id="github-zugang-falsch" className="mz-meldung" role="alert" data-fehler>
                  Fehler: {falsch}
                </p>
              )}
              <div className="mz-knoepfe">
                <button type="submit" className="btn-primary btn-small" aria-disabled={beschaeftigt || form === "leer" || falsch !== null || undefined}>
                  {wartet === "speichern" ? WARTET_TEXT.speichern : hinterlegt ? "Ersetzen" : "Hinterlegen"}
                </button>
                {hinterlegt && (
                  <button
                    type="button"
                    className="btn-secondary btn-small"
                    aria-disabled={beschaeftigt || undefined}
                    onClick={() => !beschaeftigt && void senden("pruefen")}
                  >
                    {wartet === "pruefen" ? WARTET_TEXT.pruefen : "Erneut prüfen"}
                  </button>
                )}
              </div>
            </form>
          </>
        )}

        {hinterlegt && (
          <div className="mz-knoepfe">
            {loeschenFragen ? (
              <>
                <button
                  type="button"
                  className="btn-secondary btn-small"
                  aria-disabled={beschaeftigt || undefined}
                  onClick={() => {
                    if (beschaeftigt) return;
                    setLoeschenFragen(false);
                    kopf.current?.focus(); // die Knöpfe verschwinden mit dem Löschen: der Fokus bleibt in der Karte
                    void senden("loeschen");
                  }}
                >
                  Wirklich löschen
                </button>
                <button type="button" className="btn-secondary btn-small" onClick={() => setLoeschenFragen(false)}>
                  Abbrechen
                </button>
              </>
            ) : (
              <button
                type="button"
                className="btn-secondary btn-small"
                aria-disabled={beschaeftigt || undefined}
                onClick={() => !beschaeftigt && setLoeschenFragen(true)}
              >
                {wartet === "loeschen" ? WARTET_TEXT.loeschen : "Löschen"}
              </button>
            )}
          </div>
        )}

        <p className="mz-meldung" role="status">
          {meldung && !meldung.fehler ? meldung.text : wartet === "stand" ? WARTET_TEXT.stand : ""}
        </p>
        {meldung?.fehler && (
          <p className="mz-meldung" role="alert" data-fehler>
            Fehler: {meldung.text}
          </p>
        )}
        {hinterlegt && stand?.art && (
          <p className="mz-klein">
            Art {ART_TEXT[stand.art]}, gültig bis {datumDeutsch(stand.ablauf)}. Das Token liegt verschlüsselt im Kern und wird nie
            angezeigt, nie in Gesprächen, Aufgaben oder im Gedächtnis gespeichert.
          </p>
        )}
      </section>
    </div>
  );
});
