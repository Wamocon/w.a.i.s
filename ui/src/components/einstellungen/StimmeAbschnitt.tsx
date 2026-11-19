"use client";

import { memo, useEffect, useId, useRef, useState } from "react";
import { einlernOeffnerMerken } from "@/components/kommando/einlernFokus";
import { einstellungenOeffnen, einstellungenSchliessen } from "@/lib/einstellungenHash";
import {
  ergebnisText,
  kannEinlernen,
  kannLoeschen,
  modusText,
  stimmeStatusText,
} from "@/lib/stimme";
import {
  anderesMikrofon,
  istEingelernt,
  laufenderEintrag,
  mehrereMikrofone,
  stimmMikrofonLesen,
  stimmSpeicher,
  UNBEKANNT,
  type StimmMikrofonEintrag,
} from "@/lib/stimmMikrofon";
import { useNutzer } from "@/lib/nutzer";
import { useSelect } from "@/lib/store";
import type { StimmabdruckAktionen } from "@/lib/useWamo";
import { abdruckAnsichtOeffnen, istOnline, wamo } from "@/lib/wamo";
import { Block, Daten } from "./Block";

const DATUM = new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });

/** Anzeigename eines eingelernten Mikrofons; der Abdruck ohne Namen stammt aus der Zeit, bevor W.A.I.S. Mikrofone unterschied. */
const mikrofonName = (e: StimmMikrofonEintrag): string => e.name ?? "Unbekanntes Mikrofon";

function eingelerntAm(am: string | null): string | null {
  const zeit = am ? Date.parse(am) : Number.NaN;
  return Number.isFinite(zeit) ? DATUM.format(new Date(zeit)) : null;
}

/** Rückfrage vor dem Löschen: alle Abdrücke (der Widerruf) oder der Abdruck eines Mikrofons */
type Frage = { art: "alle" } | { art: "eins"; kennung: string; name: string };
/** Kennung, für die die Rückfrage gilt ("alle" für alle), oder null */
const frageZiel = (f: Frage | null): string | null => (f === null ? null : f.art === "alle" ? "alle" : f.kennung);

/**
 * Abschnitt "Stimme" der Einstellungen (nicht in der Laborsicht, lib/laborPlatz.ts): Stand der Stimmerkennung, Einlernen oder Neu einlernen
 * (öffnet die Einlernansicht in der Mitte und schließt die Einstellungen, damit man sie sieht) und Abdruck löschen mit Rückfrage.
 * Einlernen und Löschen brauchen eine laufende Sitzung, denn der Kern prüft und speichert. Gelöscht wird erst nach einem ausdrücklichen Ja,
 * der Fokus der Rückfrage liegt auf "Behalten". Die Bestätigung kommt vom Kern (Ansage "Stimmabdruck gelöscht", Status "Noch nicht eingelernt").
 *
 * Ein Abdruck je Mikrofon (Wunsch vom 18.11.2026, lib/stimmMikrofon.ts): Meldet der Kern mehrere (Liste mit max über 1), stehen hier
 * die eingelernten Mikrofone mit Datum. Das laufende hat "Neu einlernen", jedes hat "Löschen"; ein noch nicht eingelerntes laufendes
 * Mikrofon kommt mit "Für dieses Mikrofon einlernen" dazu (gesperrt, wenn schon drei eingelernt sind), "Alle Abdrücke löschen" ist der
 * Widerruf. Eingelernt wird immer mit dem Mikrofon, das im Gespräch läuft; ein anderes wählt man unter Mikrofon und Sprache. Ohne Liste oder mit
 * max 1 (Kern ohne Migration 0029) bleibt alles wie zuvor.
 */
export const StimmeAbschnitt = memo(function StimmeAbschnitt({ aktionen }: { aktionen: StimmabdruckAktionen | undefined }) {
  const stand = useSelect(wamo, (s) => s.stimme);
  const online = useSelect(wamo, istOnline);
  const liste = useSelect(wamo, (s) => s.stimmMikrofone);
  const aktuell = useSelect(wamo, (s) => s.mikrofon);
  const [frage, setFrage] = useState<Frage | null>(null);
  const [nachricht, setNachricht] = useState<{ art: "status" | "alert"; text: string } | null>(null);
  const frageId = useId();
  const rueckfrageId = useId();
  const listeId = useId();
  const behalten = useRef<HTMLButtonElement>(null);
  const loeschKnopf = useRef<HTMLButtonElement>(null);
  const einlernKnopf = useRef<HTMLButtonElement>(null);
  const meldung = useRef<HTMLParagraphElement>(null);
  /** der Knopf, der die Rückfrage geöffnet hat: dorthin geht der Fokus beim Behalten */
  const oeffner = useRef<HTMLButtonElement | null>(null);
  /** Nach dem Löschen war das Einlernen gesperrt: der Fokus geht auf die Meldung, sobald sie steht */
  const fokusAufMeldung = useRef(false);
  useEffect(() => {
    if (frage) behalten.current?.focus();
  }, [frage]);
  useEffect(() => {
    if (!nachricht || !fokusAufMeldung.current) return;
    fokusAufMeldung.current = false;
    meldung.current?.focus();
  }, [nachricht]);

  const einlernenOk = kannEinlernen(stand, online);
  const loeschenOk = kannLoeschen(stand, online) && aktionen !== undefined;
  // Mehrere Abdrücke nur mit Sitzung und einem Kern, der sie kann; sonst die Bedienung mit einem Abdruck
  const mehrere = online && mehrereMikrofone(liste) ? liste : null;
  const laufend = mehrere ? laufenderEintrag(mehrere, aktuell) : null;
  const voll = mehrere !== null && !laufend && mehrere.mikrofone.length >= mehrere.max;

  const einlernen = (knopf: HTMLButtonElement | null) => {
    einlernOeffnerMerken(knopf); // Ziel für den Fokus, wenn die Einlernansicht wieder zugeht
    if (!abdruckAnsichtOeffnen()) return;
    einstellungenSchliessen();
  };
  const fragen = (f: Frage, knopf: HTMLButtonElement) => {
    oeffner.current = knopf;
    setNachricht(null);
    setFrage(f);
  };
  const frageSchliessen = () => {
    setFrage(null);
    oeffner.current?.focus(); // der Fokus bleibt bei dem, was die Frage geöffnet hat
  };
  const loeschen = () => {
    const ziel = frage?.art === "eins" ? frage.kennung : null;
    setFrage(null);
    // Der Knopf, der die Frage öffnete, verschwindet gleich, wenn der Kern bestätigt: Fokus auf das Einlernen, solange es bedienbar ist
    // und nicht mit dem gelöschten Eintrag verschwindet, sonst (zum Beispiel ohne Sitzung) auf die Meldung, damit er nicht verloren geht
    const knopf = einlernKnopf.current;
    if (knopf && !knopf.disabled && (ziel === null || ziel !== laufend?.kennung)) knopf.focus();
    else fokusAufMeldung.current = true;
    const ging = (ziel === null ? aktionen?.loeschen() : aktionen?.loeschen(ziel)) ?? false;
    setNachricht(
      ging
        ? { art: "status", text: "Löschen angefragt. Der Kern bestätigt es gleich." }
        : { art: "alert", text: "Das Löschen ging nicht hinaus. Prüfe die Verbindung und versuche es noch einmal." },
    );
  };

  const einlernText = mehrere
    ? mehrere.mikrofone.length > 0
      ? "Für dieses Mikrofon einlernen"
      : "Stimme einlernen"
    : stand.status === "bereit"
      ? "Neu einlernen"
      : "Stimme einlernen";
  const frageText = !frage
    ? ""
    : frage.art === "eins"
      ? `Abdruck für ${frage.name} wirklich löschen? Mit diesem Mikrofon erkennt W.A.I.S. dich danach schlechter, bis du es neu einlernst.`
      : mehrere && mehrere.mikrofone.length > 1
        ? "Alle Abdrücke wirklich löschen? Danach erkennt W.A.I.S. deine Stimme nicht mehr, bis du sie neu einlernst."
        : "Abdruck wirklich löschen? Danach erkennt W.A.I.S. deine Stimme nicht mehr, bis du sie neu einlernst.";
  const ziel = frageZiel(frage);
  const alleLoeschen = loeschenOk && (!mehrere || mehrere.mikrofone.length > 1);

  return (
    <>
      <Block titel="Stimmerkennung">
        <Daten
          zeilen={[
            { name: "Status", wert: stimmeStatusText(stand) },
            { name: "Betriebsart", wert: modusText(stand.modus) },
            { name: "Letzte Äußerung", wert: ergebnisText(stand) },
          ]}
        />
        <p className="ez-text">
          W.A.I.S. erkennt an deinem Stimmabdruck, ob du sprichst. Dafür liest du einmal einen kurzen Text vor. Gespeichert wird nur der Abdruck,
          keine Aufnahme, und du kannst ihn jederzeit löschen.
          {mehrere ? " Lerne jedes Mikrofon, mit dem du sprichst, einmal ein (höchstens drei), dann erkennt W.A.I.S. dich mit jedem sicher." : ""}
        </p>
        {!online ? (
          <p className="ez-klein">Starte ein Gespräch, dann lässt sich die Stimme einlernen oder der Abdruck löschen.</p>
        ) : stand.status === "aus" ? (
          <p className="ez-klein">Die Stimmerkennung ist in dieser Sitzung nicht eingeschaltet.</p>
        ) : stand.status === "laedt" ? (
          <p className="ez-klein">Die Stimmerkennung wird gerade geladen. Einlernen geht gleich.</p>
        ) : null}
        {mehrere && mehrere.mikrofone.length > 0 && (
          <>
            <p className="ez-klein" id={listeId}>
              Eingelernte Mikrofone
            </p>
            <ul className="ez-limits" aria-labelledby={listeId}>
              {mehrere.mikrofone.map((e) => {
                const name = mikrofonName(e);
                const am = eingelerntAm(e.am);
                const istLaufend = laufend?.kennung === e.kennung;
                return (
                  <li key={e.kennung} className="ez-limit">
                    <div className="ez-limit-kopf">
                      <strong>{name}</strong>
                      {istLaufend && <span className="ez-klein">läuft gerade</span>}
                      {am && <span className="ez-klein">eingelernt am {am}</span>}
                    </div>
                    {e.kennung === UNBEKANNT && (
                      <p className="ez-klein">
                        Eingelernt, bevor W.A.I.S. Mikrofone unterschied. Lerne dein Mikrofon neu ein und lösche diesen Abdruck danach.
                      </p>
                    )}
                    <div className="ez-tasten">
                      {istLaufend && (
                        <button
                          type="button"
                          ref={einlernKnopf}
                          className="btn-secondary btn-small"
                          aria-label={`Neu einlernen: ${name}`}
                          disabled={!einlernenOk}
                          onClick={(ev) => einlernen(ev.currentTarget)}
                        >
                          Neu einlernen
                        </button>
                      )}
                      {loeschenOk && (
                        <button
                          type="button"
                          className="btn-secondary btn-small"
                          aria-label={`Löschen: ${name}`}
                          aria-expanded={ziel === e.kennung}
                          aria-controls={ziel === e.kennung ? rueckfrageId : undefined}
                          onClick={(ev) => fragen({ art: "eins", kennung: e.kennung, name }, ev.currentTarget)}
                        >
                          Löschen
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          </>
        )}
        {voll && <p className="ez-klein">Du hast höchstens drei Mikrofone eingelernt. Lösche erst eines, dann lässt sich dieses einlernen.</p>}
        <div className="ez-tasten">
          {!laufend && (
            <button
              type="button"
              ref={einlernKnopf}
              className="btn-primary"
              disabled={!einlernenOk || voll}
              onClick={(ev) => einlernen(ev.currentTarget)}
            >
              {einlernText}
            </button>
          )}
          {alleLoeschen && (
            <button
              type="button"
              ref={loeschKnopf}
              className="btn-secondary"
              aria-expanded={ziel === "alle"}
              aria-controls={ziel === "alle" ? rueckfrageId : undefined}
              onClick={(ev) => fragen({ art: "alle" }, ev.currentTarget)}
            >
              {mehrere ? "Alle Abdrücke löschen" : "Abdruck löschen"}
            </button>
          )}
        </div>
        {frage && (
          <div className="ez-rueckfrage" id={rueckfrageId} role="group" aria-labelledby={frageId}>
            <p id={frageId}>{frageText}</p>
            <div className="ez-tasten">
              <button type="button" ref={behalten} className="btn-secondary" onClick={frageSchliessen}>
                Behalten
              </button>
              <button type="button" className="btn-secondary ez-gefahr" onClick={loeschen}>
                {frage.art === "eins" ? "Ja, löschen" : mehrere ? "Ja, alle löschen" : "Ja, Abdruck löschen"}
              </button>
            </div>
          </div>
        )}
        {nachricht && (
          <p ref={meldung} tabIndex={-1} className="ez-klein" role={nachricht.art === "alert" ? "alert" : "status"}>
            {nachricht.text}
          </p>
        )}
      </Block>
      <MikrofonFuerStimme />
    </>
  );
});

/**
 * Die Stimmprüfung hängt am Mikrofon (Befund 17.11.2026: im Browser lief ein anderes, leises Gerät, der Besitzer galt als fremd). Deshalb
 * steht hier, welches Mikrofon läuft, mit dem Weg zur Wahl im Abschnitt "Mikrofon und Sprache". Die Wahl selbst gibt es nur dort (auch in der
 * Laborsicht, die diesen Abschnitt nicht hat). Seit 18.11.2026 dazu das Mikrofon beim Einlernen (lib/stimmMikrofon.ts) und ein Satz, wenn
 * gerade ein anderes läuft (Hauptursache der Fehlurteile im Befund dieses Tages). Mit einem Abdruck je Mikrofon stehen die eingelernten oben
 * in der Liste, hier nur noch, welches läuft und ob es eingelernt ist.
 */
function MikrofonFuerStimme() {
  const online = useSelect(wamo, istOnline);
  const mikrofon = useSelect(wamo, (s) => s.mikrofon);
  const liste = useSelect(wamo, (s) => s.stimmMikrofone);
  const { id: userId } = useNutzer();
  const mehrere = online && mehrereMikrofone(liste) ? liste : null;
  // Mikrofon beim Einlernen (lib/stimmMikrofon.ts, nur im Speicher dieses Browsers oder dieser App); mit der Liste des Kerns nicht nötig
  const eingelernt = mehrere ? null : stimmMikrofonLesen(stimmSpeicher(), userId);
  // mit dem hier gemerkten Namen für den Abdruck ohne Namen, wie der Hinweis bei Gerätewechsel (useWamo.ts)
  const gemerkt = mehrere ? stimmMikrofonLesen(stimmSpeicher(), userId) : null;
  const nichtEingelernt = mehrere !== null && mehrere.mikrofone.length > 0 && istEingelernt(mehrere, mikrofon, gemerkt) === false;
  const voll = mehrere !== null && mehrere.mikrofone.length >= mehrere.max;
  const zeilen = [
    ...(online && mikrofon ? [{ name: "In Benutzung", wert: mikrofon }] : []),
    ...(eingelernt ? [{ name: "Eingelernt mit", wert: eingelernt }] : []),
  ];
  return (
    <Block titel="Mikrofon">
      {zeilen.length > 0 && <Daten zeilen={zeilen} />}
      {!(online && mikrofon) && <p className="ez-klein">Welches Mikrofon läuft, steht hier während eines Gesprächs.</p>}
      {online && !mehrere && anderesMikrofon(eingelernt, mikrofon) && (
        <p className="ez-klein" data-rueckfall>
          Gerade läuft ein anderes Mikrofon als beim Einlernen. Lerne die Stimme mit diesem Mikrofon neu ein, dann erkennt W.A.I.S. dich
          sicherer.
        </p>
      )}
      {nichtEingelernt && (
        <p className="ez-klein" data-rueckfall>
          Für das Mikrofon, das gerade läuft, gibt es noch keinen Abdruck.{" "}
          {voll
            ? "Lösche oben erst ein anderes Mikrofon, dann lässt sich dieses einlernen."
            : "Lerne es oben ein, dann erkennt W.A.I.S. dich damit sicherer."}
        </p>
      )}
      <p className="ez-text">
        Die Stimmerkennung vergleicht mit dem Abdruck, den du eingelernt hast. Ein anderes oder sehr leises Mikrofon senkt die Übereinstimmung.
        Wähle das Mikrofon, mit dem du sprichst, und lerne die Stimme mit genau diesem Mikrofon ein.
      </p>
      <div>
        <button type="button" className="btn-secondary btn-small" onClick={() => einstellungenOeffnen("sprache")}>
          Mikrofon wählen
        </button>
      </div>
    </Block>
  );
}
