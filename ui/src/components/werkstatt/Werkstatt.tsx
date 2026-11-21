"use client";

import Link from "next/link";
import { useEffect, useRef, useSyncExternalStore, type ReactNode } from "react";
import type { Sitzung } from "@/components/LoginGate";
import { Wortmarke } from "@/components/Wortmarke";
import { istLaborKonto } from "@/lib/stillStart";
import { ichLaden } from "@/lib/werkstattApi";
import { BEREICHE, alterText, bereichHash, bereichTitel, parseBereich, type BereichId } from "@/lib/werkstattAnsicht";
import { Karten as KartenBereich } from "./Karten";
import { FehlerHinweis, Laedt, Pille } from "./Bausteine";
import { Dashboards } from "./Dashboards";
import { LaborPlaner } from "./LaborPlaner";
import { Protokolle } from "./Protokolle";
import { useAbruf } from "./useAbruf";

/**
 * Die Werkstatt (Seite /werkstatt): ein Admin-Panel für Dashboards, den Labor-Planer, Karten und Use Cases und Protokolle. Die Seite
 * spricht mit dem Dienst wamo-werkstatt (lib/werkstattApi.ts) und nutzt dafür die Anmeldung der Oberfläche (LoginGate, Passwort und
 * zweiter Faktor). Wer hier hineinschaut, wird vom Dienst geprüft: aktives Profil, Rolle Admin, kein Laborprofil, zweiter Faktor und
 * Erlaubnisliste. Die Oberfläche zeigt nur, was der Dienst erlaubt, und ein Laborkonto ruft ihn gar nicht erst.
 *
 * Aufbau: links die vier Bereiche als Links mit Hash (#dashboard, #labor, #karten, #protokolle), rechts der gewählte Bereich. Beim
 * Wechsel springt der Fokus auf die Überschrift des Bereichs. Die Seite gehört nicht in die Einstellungen, ein Link dort öffnet sie
 * in einem neuen Tab.
 */

const abonnieren = (rueckruf: () => void) => {
  window.addEventListener("hashchange", rueckruf);
  return () => window.removeEventListener("hashchange", rueckruf);
};

function useBereich(): BereichId {
  const hash = useSyncExternalStore(abonnieren, () => window.location.hash, () => "");
  return parseBereich(hash);
}

function Rahmen({ children, seite }: { children: ReactNode; seite?: ReactNode }) {
  const inhalt = useRef<HTMLElement>(null);
  return (
    <div className="ws">
      <button type="button" className="ws-sprung" onClick={() => inhalt.current?.focus()}>
        Zum Inhalt springen
      </button>
      <div className="ws-rahmen">
        <aside className="ws-seite" aria-label="Werkstatt">
          <div className="ws-marke">
            <span className="ws-marke-name"><Wortmarke /></span>
            <span className="ws-marke-zusatz">Werkstatt</span>
          </div>
          {seite}
        </aside>
        <main id="ws-inhalt" ref={inhalt} tabIndex={-1} className="ws-inhalt">
          {children}
        </main>
      </div>
    </div>
  );
}

function KeinZugriff({ text, sitzung }: { text: string; sitzung: Sitzung }) {
  const titel = useRef<HTMLHeadingElement>(null);
  useEffect(() => titel.current?.focus(), []);
  return (
    <Rahmen>
      <div className="ws-bereich">
        <h1 ref={titel} tabIndex={-1} className="ws-titel">Kein Zugriff</h1>
        <p className="ws-kurz" role="status">{text}</p>
        <div className="ws-aktionen">
          <Link href="/" className="btn-secondary ws-link-knopf">Zur Oberfläche</Link>
          <button type="button" className="btn-secondary" onClick={sitzung.signOut}>Abmelden</button>
        </div>
      </div>
    </Rahmen>
  );
}

const TEXT_KEIN_ZUGRIFF =
  "Die Werkstatt ist nur für Admins auf der Erlaubnisliste, ohne Laborprofil und mit zweitem Faktor. Wenn du Zugang brauchst, frag einen Admin.";

export function Werkstatt({ sitzung }: { sitzung: Sitzung }) {
  const bereich = useBereich();
  const labor = istLaborKonto(sitzung.email);
  const ich = useAbruf((s) => ichLaden(s), "ich", !labor);
  const titel = useRef<HTMLHeadingElement>(null);
  const ersterLauf = useRef(true);

  useEffect(() => {
    document.title = `${bereichTitel(bereich)} | Werkstatt | W.A.I.S.`;
    // Beim ersten Zeichnen bleibt der Fokus, wo er ist; erst ein Wechsel des Bereichs springt auf die Überschrift.
    if (ersterLauf.current) {
      ersterLauf.current = false;
      return;
    }
    titel.current?.focus();
  }, [bereich]);

  if (labor) return <KeinZugriff text="Mit einem Laborprofil gibt es keinen Zugang zur Werkstatt." sitzung={sitzung} />;
  if (ich.fehler && !ich.daten) {
    if (ich.fehler.code === "nicht_berechtigt" || ich.fehler.code === "labor_profil") return <KeinZugriff text={TEXT_KEIN_ZUGRIFF} sitzung={sitzung} />;
    return (
      <Rahmen>
        <div className="ws-bereich">
          <h1 className="ws-titel">Werkstatt</h1>
          <FehlerHinweis fehler={ich.fehler} onNeu={ich.neu} />
        </div>
      </Rahmen>
    );
  }
  if (!ich.daten) {
    return (
      <Rahmen>
        <div className="ws-bereich">
          <h1 className="ws-titel">Werkstatt</h1>
          <Laedt was="Der Zugang" />
        </div>
      </Rahmen>
    );
  }
  if (ich.daten.rolle !== "admin" || !ich.daten.erlaubt) return <KeinZugriff text={TEXT_KEIN_ZUGRIFF} sitzung={sitzung} />;

  const seite = (
    <>
      <nav className="ws-nav" aria-label="Bereiche der Werkstatt">
        <ul>
          {BEREICHE.map((b) => (
            <li key={b.id}>
              <a href={bereichHash(b.id)} aria-current={b.id === bereich ? "page" : undefined}>
                <span>{b.titel}</span>
                <small>{b.art}</small>
              </a>
            </li>
          ))}
        </ul>
      </nav>
      <div className="ws-ich">
        <span><Pille art="ok">Admin, Erlaubnisliste</Pille></span>
        <span>Zweiter Faktor {alterText(ich.daten.aal2AlterS)}</span>
        <span>Zugriff nur aus dem Büronetz</span>
        <div className="ws-ich-links">
          <Link href="/" className="ws-textknopf">Zur Oberfläche</Link>
          <button type="button" className="ws-textknopf" onClick={sitzung.signOut}>Abmelden</button>
        </div>
      </div>
    </>
  );

  return (
    <Rahmen seite={seite}>
      <h1 ref={titel} tabIndex={-1} className="ws-titel">{bereichTitel(bereich)}</h1>
      {bereich === "dashboard" && <Dashboards />}
      {bereich === "labor" && <LaborPlaner />}
      {bereich === "karten" && <KartenBereich onFaktor={ich.neu} />}
      {bereich === "protokolle" && <Protokolle />}
    </Rahmen>
  );
}
