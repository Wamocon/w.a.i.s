"use client";

import { useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { GeteiltBereich } from "@/components/Geteilt";
import { GithubZugang } from "@/components/GithubZugang";
import { ModellZugang } from "@/components/ModellZugang";
import { UeberschriftVersatz } from "@/components/Ueberschrift";
import { offeneEntscheidungen } from "@/components/kommando/ansicht";
import {
  gruppenFuer,
  hashFuer,
  sprungAbschnitt,
  wirksameGruppe,
  zurueckZiel,
  type AbschnittId,
  type GruppeId,
  type SichtbareGruppe,
} from "@/lib/einstellungenAbschnitte";
import {
  abschnittWaehlen,
  einstellungenSchliessen,
  gruppeWaehlen,
  useEinstellungenZiel,
  useZweispaltig,
  zurListe,
} from "@/lib/einstellungenHash";
import { laborAnsicht } from "@/lib/laborPlatz";
import { useSelect } from "@/lib/store";
import type { WamoAktionen } from "@/lib/useWamo";
import { wamo } from "@/lib/wamo";
import { DarstellungAbschnitt, InfoAbschnitt, KontoAbschnitt, SpracheAbschnitt } from "./Abschnitte";
import { StimmeAbschnitt } from "./StimmeAbschnitt";
import { Block } from "./Block";
import { Fernzugriff } from "./Fernzugriff";
import { GeraeteAbschnitt } from "./Geraete";
import { VerbrauchAbschnitt } from "./Verbrauch";
import { AenderungenAbschnitt } from "./Aenderungen";
import { GedaechtnisAbschnitt } from "./Gedaechtnis";
import { NeueMitglieder } from "./NeueMitglieder";
import { GithubRechte } from "./GithubRechte";
import { ErsteSchritteAbschnitt } from "./ErsteSchritte";
import { UpdatesAbschnitt } from "./Updates";
import { WerkstattAbschnitt } from "./Werkstatt";

/**
 * Die Einstellungsseite: eine Ansicht der Hauptseite, kein eigener Pfad (siehe lib/einstellungenAbschnitte.ts). Sechs Gruppen
 * gliedern sie, jede fasst ihre Abschnitte zusammen. Ab 860 px zwei Spalten, links die Gliederung (nur die Gruppen), rechts die
 * gewählte Gruppe mit ihren Abschnitten untereinander. Darunter eine Liste, die in die Gruppe führt. Gruppe und Abschnitt stehen im
 * Hash (#einstellungen/zugaenge, #einstellungen/modellzugang); eine Abschnittskennung, auch die aus den Adressen vor der
 * Gruppierung, öffnet die Gruppe und springt zum Abschnitt. Das Gespräch läuft im Hintergrund weiter: die Kommandozentrale
 * bleibt eingehängt und ist nur verborgen (kommando/Rahmen.tsx).
 *
 * Überschriften: Seite Stufe 2, Gruppe Stufe 3, Abschnitt Stufe 4, Block Stufe 5 (UeberschriftVersatz, components/Ueberschrift.tsx).
 *
 * Bedienung: Beim Öffnen und bei jedem Wechsel springt der Fokus auf die Überschrift der Gruppe, bei einer Abschnittsadresse oder einem
 * Klick auf die Sprungleiste auf die Überschrift des Abschnitts (am Handy in der Liste auf "Einstellungen"). Escape und "Zum Gespräch"
 * schließen; am Handy führt Escape aus einer Gruppe zuerst zur Liste. Escape lässt Eingaben in Texteingaben in Ruhe (Editor,
 * Schlüsselfelder), damit nichts verloren geht. Meldungen der Kommandozentrale (Fehler, Gemerktes, Hinweise) stehen oben in einem
 * eigenen Streifen, weil die Kommandozentrale verborgen ist und ein Alarm dort nicht vorgelesen würde. Wartet etwas auf eine
 * Entscheidung, steht dort auch der Weg zurück, denn Freigaben erscheinen nur in der Kommandozentrale.
 */

type Props = {
  aktionen: WamoAktionen;
  email: string | null;
  onAbmelden: () => void;
  /** Meldungen der Kommandozentrale (Fehler, Gemerktes, Hinweise, kurze Bestätigungen), die hier sonst unsichtbar wären */
  meldungen: ReactNode;
};

/** Ist gerade ein Popover (Profil, Status) offen? Ältere Browser kennen den Selektor nicht; dann gilt: nein. */
function popoverOffen(): boolean {
  try {
    return document.querySelector(":popover-open") !== null;
  } catch {
    return false;
  }
}

/** Ist ein modales Dialogfenster offen? Dann schließt Escape nur dieses, nicht die Seite. */
function dialogOffen(): boolean {
  return document.querySelector("dialog[open]") !== null;
}

/**
 * Tippt die Person gerade in einem Feld, in dem Escape etwas anderes bedeutet oder etwas verloren ginge? Mehrzeilige
 * Texte (Editor für geteilte Dokumente) und Felder mit Inhalt (Schlüssel, Nachricht) schließen die Seite nicht.
 */
function tippt(ziel: EventTarget | null): boolean {
  if (!(ziel instanceof HTMLElement)) return false;
  if (ziel.isContentEditable || ziel instanceof HTMLTextAreaElement) return true;
  return ziel instanceof HTMLInputElement && ziel.value !== "" && !["checkbox", "radio", "button", "submit"].includes(ziel.type);
}

function Entscheidung() {
  const offen = useSelect(wamo, offeneEntscheidungen);
  if (offen === 0) return null;
  return (
    <div className="ez-meldung">
      <span className="dot dot-rot" aria-hidden="true" />
      <p>
        {offen === 1 ? "Eine Freigabe oder ein Auftrag wartet" : `${offen} Freigaben oder Aufträge warten`} auf deine
        Entscheidung.
      </p>
      <button type="button" className="btn-secondary btn-small" onClick={() => einstellungenSchliessen()}>
        Zum Gespräch
      </button>
    </div>
  );
}

/** Kennung der Überschrift eines Abschnitts: Ziel des Fokus bei einer Abschnittsadresse und der Sprungleiste. */
export const abschnittKopfId = (id: AbschnittId): string => `ez-h-${id}`;
const GRUPPE_KOPF_ID = "ez-h-gruppe";

/** Mehr als zwei Abschnitte in einer Gruppe: eine schlichte Sprungleiste oben (bei zwei Abschnitten genügt das Scrollen). */
const SPRUNGLEISTE_AB = 3;

function waehlenKlick(e: MouseEvent<HTMLAnchorElement>, waehle: () => void) {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  waehle();
}

type InhaltProps = {
  aktionen: WamoAktionen;
  email: string | null;
  onAbmelden: () => void;
  labor: boolean;
  admin: boolean;
};

/** Der Inhalt eines Abschnitts: dieselben Komponenten wie vor der Gruppierung. */
function AbschnittInhalt({ id, aktionen, email, onAbmelden, labor, admin }: InhaltProps & { id: AbschnittId }) {
  switch (id) {
    case "konto":
      return <KontoAbschnitt email={email} onAbmelden={onAbmelden} />;
    case "start":
      return <ErsteSchritteAbschnitt />;
    case "darstellung":
      return <DarstellungAbschnitt />;
    case "updates":
      return <UpdatesAbschnitt />;
    case "info":
      return <InfoAbschnitt admin={admin} />;
    case "sprache":
      return (
        <SpracheAbschnitt
          mikrofone={aktionen.mikrofone}
          mikrofonWaehlen={aktionen.mikrofonWaehlen}
          mikrofonUmschalten={aktionen.toggleMic}
          ausgabeAnhalten={labor ? undefined : aktionen.ausgabeAnhalten}
          modellzugang={aktionen.modellzugang}
          nurMikrofon={labor}
        />
      );
    case "stimme":
      return <StimmeAbschnitt aktionen={aktionen.stimmabdruck} />;
    case "modellzugang":
      return <ModellZugang onAnfrage={aktionen.modellzugang} />;
    case "github":
      return <GithubZugang />;
    case "verbrauch":
      return <VerbrauchAbschnitt />;
    case "geraete":
      return <GeraeteAbschnitt onPcSteuerung={aktionen.pcSteuerung} />;
    case "fernzugriff":
      return (
        <Block titel="Desktop der Sparks">
          <Fernzugriff />
        </Block>
      );
    case "gedaechtnis":
      return <GedaechtnisAbschnitt />;
    case "teilen":
      return (
        <Block titel="Geteilte Arbeit">
          <GeteiltBereich />
        </Block>
      );
    case "mitglieder":
      return (
        <>
          <NeueMitglieder />
          <GithubRechte />
        </>
      );
    case "aenderungen":
      return <AenderungenAbschnitt />;
    case "werkstatt":
      return <WerkstattAbschnitt />;
    default: {
      const unbekannt: never = id; // neue Abschnitte müssen hier behandelt werden
      void unbekannt;
      return null;
    }
  }
}

/**
 * Sprungleiste oben in einer Gruppe mit mehr als zwei Abschnitten: schlichte Links auf die Abschnitte, ohne eigenen Zustand.
 * onGewaehlt läuft nach jedem Klick, auch wenn die Adresse schon stimmt: dann scrollt und fokussiert die Seite trotzdem noch einmal.
 */
function Sprungleiste({ gruppe, onGewaehlt }: { gruppe: SichtbareGruppe; onGewaehlt: () => void }) {
  return (
    <nav className="ez-sprung" aria-label={`Abschnitte in ${gruppe.titel}`}>
      <span className="ez-sprung-label" aria-hidden="true">
        Springe zu:
      </span>
      <ul>
        {gruppe.abschnitte.map((a) => (
          <li key={a.id}>
            <a
              href={hashFuer(a.id)}
              onClick={(e) =>
                waehlenKlick(e, () => {
                  abschnittWaehlen(a.id);
                  onGewaehlt();
                })
              }
            >
              {a.titel}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function Einstellungen({ aktionen, email, onAbmelden, meldungen }: Props) {
  const ziel = useEinstellungenZiel();
  const zweispaltig = useZweispaltig();
  const rolle = useSelect(wamo, (s) => s.profil?.rolle ?? null);
  // Laborkonten (lib/laborPlatz.ts): nur die Mikrofonwahl; ein Hash auf eine andere Gruppe führt dann zur Liste oder zur Mikrofonwahl
  const labor = laborAnsicht(email).einstellungen === "mikrofon";
  // Verbrauch (Kontingent des eigenen Max-Abos) auch für Mitglieder mit eigenem Claude-Code-Token (Ausrollen P5)
  const token = useSelect(wamo, (s) => s.modellzugang?.codeHinterlegt === true);
  const gruppen = useMemo(() => gruppenFuer({ rolle, labor, token }), [rolle, labor, token]);
  const wirksam: GruppeId | null = wirksameGruppe(ziel, gruppen, zweispaltig);
  const gruppe = gruppen.find((g) => g.id === wirksam);
  const sprung = sprungAbschnitt(ziel, gruppe);
  const ersterAbschnitt = gruppe?.abschnitte[0]?.id ?? null;
  const titel = gruppe?.titel ?? "";

  const seitenTitel = useRef<HTMLHeadingElement>(null);
  const gruppenTitel = useRef<HTMLHeadingElement>(null);
  const inhalt = useRef<HTMLDivElement>(null);

  // Fokus auf die Überschrift der Gruppe (oder der Liste), bei einem Sprung auf die des Abschnitts; der Inhalt rückt nach oben oder zum
  // Abschnitt. Nur ein Wechsel der Gruppe oder des Sprungziels (oder eine erneute Wahl, anstoss) zählt: ein Drehen oder Zoomen, bei dem sich
  // nur zweispaltig ändert, setzt den Fokus nicht zurück. Der erste Abschnitt liegt unter dem Kopf der Gruppe: dorthin springen heißt ganz nach oben, damit der Kopf sichtbar bleibt.
  const zweispaltigRef = useRef(zweispaltig);
  const ersterRef = useRef(ersterAbschnitt);
  useEffect(() => {
    zweispaltigRef.current = zweispaltig;
    ersterRef.current = ersterAbschnitt; // über Refs gelesen: ein später eintreffendes Profil verschiebt nicht erneut den Fokus
  });
  // Dieselbe Gruppe oder derselbe Abschnitt noch einmal gewählt (die Adresse bleibt gleich, etwa nach Scrollen von Hand): trotzdem erneut hin
  const [anstoss, setAnstoss] = useState(0);
  const anstossen = () => setAnstoss((n) => n + 1);
  useEffect(() => {
    const nachOben = () => {
      inhalt.current?.scrollTo({ top: 0 });
      if (!zweispaltigRef.current) window.scrollTo({ top: 0 });
    };
    const kopf = sprung ? document.getElementById(abschnittKopfId(sprung)) : null;
    if (kopf) {
      kopf.focus({ preventScroll: true });
      if (sprung === ersterRef.current) nachOben();
      else kopf.scrollIntoView({ block: "start" });
      return;
    }
    (wirksam ? gruppenTitel : seitenTitel).current?.focus({ preventScroll: true });
    nachOben();
  }, [wirksam, sprung, anstoss]);

  // Browserleiste und Screenreader: wo bin ich?
  useEffect(() => {
    const vorher = document.title;
    document.title = `${titel ? `${titel}, ` : ""}Einstellungen | W.A.I.S.`;
    return () => {
      document.title = vorher;
    };
  }, [titel]);

  // Escape wie "Zurück". Was sich selbst auf Escape schließt (Popover, geöffnete Formulare), geht vor.
  const zurueck = () => {
    if (zurueckZiel(wirksam, zweispaltig) === "liste") zurListe();
    else einstellungenSchliessen();
  };
  const zurueckRef = useRef(zurueck);
  useEffect(() => {
    zurueckRef.current = zurueck;
  });
  useEffect(() => {
    const beiTaste = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || e.isComposing) return;
      // ein offener Bestätigungsdialog (Geräteverwaltung) gehört sich selbst; der Fokus kann während einer Anfrage auf body liegen
      if (popoverOffen() || dialogOffen() || tippt(e.target)) return;
      e.preventDefault();
      zurueckRef.current();
    };
    document.addEventListener("keydown", beiTaste);
    return () => document.removeEventListener("keydown", beiTaste);
  }, []);

  const admin = rolle === "admin";

  return (
    <main className="ez" data-ansicht={wirksam === null ? "liste" : "gruppe"}>
      <Entscheidung />
      <div className="ez-meldungen">{meldungen}</div>
      <div className="ez-gitter">
        <div className="ez-seite">
          <div className="ez-kopf">
            <h2 ref={seitenTitel} tabIndex={-1} className="ez-titel">
              Einstellungen
            </h2>
            <button type="button" className="btn-secondary btn-small ez-zumgespraech" onClick={() => einstellungenSchliessen()}>
              Zum Gespräch
            </button>
          </div>
          <nav className="ez-nav" aria-label="Gruppen der Einstellungen">
            <ul>
              {gruppen.map((g) => (
                <li key={g.id}>
                  <a
                    href={hashFuer(g.id)}
                    className="ez-nav-link"
                    aria-current={g.id === wirksam ? "page" : undefined}
                    onClick={(e) =>
                      waehlenKlick(e, () => {
                        gruppeWaehlen(g.id);
                        anstossen();
                      })
                    }
                  >
                    <span className="ez-nav-titel">{g.titel}</span>
                    <span className="ez-nav-kurz">{g.kurz}</span>
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        </div>

        <div ref={inhalt} className="ez-inhalt">
          {gruppe && (
            <UeberschriftVersatz value={1}>
              <section className="ez-gruppe" aria-labelledby={GRUPPE_KOPF_ID} key={gruppe.id}>
                <div className="ez-gruppe-kopf">
                  {!zweispaltig && (
                    <div className="ez-wege">
                      <button type="button" className="ez-zurueck" onClick={zurListe}>
                        <svg viewBox="0 0 16 16" aria-hidden="true">
                          <path d="M10 3L5 8l5 5" />
                        </svg>
                        Alle Einstellungen
                      </button>
                      <button type="button" className="ez-zurueck" onClick={() => einstellungenSchliessen()}>
                        Zum Gespräch
                      </button>
                    </div>
                  )}
                  <h3 id={GRUPPE_KOPF_ID} ref={gruppenTitel} tabIndex={-1} className="ez-gruppe-titel">
                    {gruppe.titel}
                  </h3>
                  <p className="ez-gruppe-kurz">{gruppe.kurz}</p>
                  {gruppe.abschnitte.length >= SPRUNGLEISTE_AB && <Sprungleiste gruppe={gruppe} onGewaehlt={anstossen} />}
                </div>
                {gruppe.abschnitte.map((a) => (
                  <section key={a.id} className="ez-abschnitt" aria-labelledby={abschnittKopfId(a.id)}>
                    <div className="ez-abschnitt-kopf">
                      <h4 id={abschnittKopfId(a.id)} tabIndex={-1} className="ez-abschnitt-titel">
                        {a.titel}
                      </h4>
                      {/* steht die Gruppe nur für diesen einen Abschnitt, sagt ihre Kurzzeile schon dasselbe */}
                      {gruppe.abschnitte.length > 1 && <p className="ez-abschnitt-kurz">{a.kurz}</p>}
                    </div>
                    <div className="ez-abschnitt-inhalt">
                      <AbschnittInhalt id={a.id} aktionen={aktionen} email={email} onAbmelden={onAbmelden} labor={labor} admin={admin} />
                    </div>
                  </section>
                ))}
              </section>
            </UeberschriftVersatz>
          )}
        </div>
      </div>
    </main>
  );
}
