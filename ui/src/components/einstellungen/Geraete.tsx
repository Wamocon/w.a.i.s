"use client";

import { memo, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { StatusDetails } from "@/components/Statusleiste";
import {
  BETRIEBSARTEN,
  BUERO_VERFUEGBAR,
  betriebsartSetzen,
  KERN,
  useBetriebsart,
  type Betriebsart,
} from "@/lib/betriebsart";
import { pcAutoSetzen, usePcAuto } from "@/lib/einstellungen";
import { geraeteBloecke, geraeteStandText, PC_STEUERUNG_ID } from "@/lib/einstellungenAbschnitte";
import { useDesktopApp, useServerBrowser } from "@/lib/geraet";
import { nachbar } from "@/lib/modellwahl";
import { geraeteAnzeige } from "@/lib/geraeteAnzeige";
import {
  HINWEIS_LAPTOP,
  HINWEIS_NUR_APP,
  HINWEIS_OHNE_SITZUNG,
  HINWEIS_OHNE_SITZUNG_FERN,
  pcLageHinweis,
  SCHALT_WARTEN_MS,
  TEXT_WARTET,
} from "@/lib/pcSchalter";
import { useSelect } from "@/lib/store";
import { usePcSchalter } from "@/lib/usePcSchalter";
import { istOnline, wamo, zeigeToast } from "@/lib/wamo";
import { Block } from "./Block";
import { Fernzugriff } from "./Fernzugriff";
import { GeraeteVerwaltung } from "./GeraeteVerwaltung";

/**
 * Schalter "PC-Steuerung" für diese Sitzung: Standard aus, nur für Admins (lib/pcSchalter.ts, Laborkonten nie), in der Desktop-App und
 * im Browser gleich. Mit Sitzung geht nur der Wunsch hinaus; was gilt, meldet der Kern in betrieb.pc_steuerung zurück. Ohne Sitzung ist
 * er bedienbar: "an" startet still eine Sitzung (useWamo.pcSteuerung) und schaltet ein, sobald der Kern den PC als verbunden meldet.
 * Solange das läuft, ist er gesperrt (pcEinschalten.wartet); klappt es nicht, steht der Grund darunter (pcEinschalten.hinweis, für
 * Screenreader als Status). Ist der PC in der Sitzung nicht verbunden, sagt ein Satz warum (pcLageHinweis). Im Browser in der Betriebsart
 * Büro steht dabei, dass er den Laptop steuert, dass ein stiller Start eine laufende Sitzung auf einem anderen Gerät beendet, und was nur
 * die Desktop-App kann; den Haken für die Automatik gibt es dort nicht, denn sie wirkt im Büro nur mit dem Rechnernamen der Desktop-App
 * (useWamo). Die Hinweise hängen über aria-describedby am Schalter, damit auch ein gesperrter Schalter seinen Grund nennt.
 */
const PcSteuerungSchalter = memo(function PcSteuerungSchalter({ onSchalten }: { onSchalten: (an: boolean) => boolean }) {
  const { anzeige, fern } = usePcSchalter();
  const an = useSelect(wamo, (s) => s.betrieb?.pcSteuerung === "an");
  const belegt = useSelect(wamo, (s) => s.betrieb?.pcBelegt === true && s.betrieb?.pcSteuerung !== "an");
  const pcName = useSelect(wamo, (s) => s.betrieb?.pcName ?? null);
  const lage = useSelect(wamo, (s) => (istOnline(s) ? pcLageHinweis(s.betrieb) : null));
  const ein = useSelect(wamo, (s) => s.pcEinschalten);
  const [ziel, setZiel] = useState<boolean | null>(null);
  const auto = usePcAuto();
  const id = useId();
  const ausstehend = ein.wartet || (ziel !== null && ziel !== an && !belegt);
  if (anzeige.art === "verborgen") return null;
  const hinweis = ausstehend
    ? ein.wartet
      ? TEXT_WARTET
      : "wird geschaltet …"
    : belegt
      ? "eine andere Sitzung steuert diesen PC gerade"
      : anzeige.art === "gesperrt"
        ? anzeige.hinweis
        : anzeige.ohneSitzung
          ? fern
            ? HINWEIS_OHNE_SITZUNG_FERN
            : HINWEIS_OHNE_SITZUNG
          : (lage ?? `gilt nur für diese Sitzung${pcName ? `, Ziel ${pcName}` : ""}`);
  // Derselbe Satz steht nach einem gescheiterten Wunsch schon im Status darunter: dort genügt er, und daneben steht kein "alles gut"
  const zeile = hinweis === ein.hinweis ? null : hinweis;
  const ids = { zeile: `${id}-zeile`, fern: `${id}-fern`, status: `${id}-status` };
  const beschrieben = [zeile && ids.zeile, fern && ids.fern, ein.hinweis && ids.status].filter(Boolean).join(" ") || undefined;
  return (
    <div className="pc-steuerung" id={PC_STEUERUNG_ID} tabIndex={-1} role="group" aria-label="PC-Steuerung">
      <div className="pc-switch-row">
        <PcSchalterKnopf
          an={an}
          ausstehend={ausstehend}
          gesperrt={anzeige.art === "gesperrt"}
          beschrieben={beschrieben}
          onSchalten={onSchalten}
          setZiel={setZiel}
        />
        {zeile && (
          <span className="pc-switch-hint" id={ids.zeile}>
            {zeile}
          </span>
        )}
      </div>
      {fern && (
        <p className="pc-switch-hint pc-fern-hinweis" id={ids.fern}>
          {HINWEIS_LAPTOP}
        </p>
      )}
      {/* immer eingehängt, nur der Text wechselt: ein neu eingefügter Bereich wird oft überhört */}
      <p className="pc-switch-hint pc-ein-hinweis" role="status" id={ids.status}>
        {ein.hinweis ?? ""}
      </p>
      {fern ? (
        <p className="pc-auto-hint">{HINWEIS_NUR_APP}</p>
      ) : (
        <>
          <label className="pc-auto">
            <input type="checkbox" checked={auto} onChange={(e) => pcAutoSetzen(e.target.checked)} />
            <span>PC-Steuerung beim Start automatisch einschalten (dieses Gerät)</span>
          </label>
          {auto && <p className="pc-auto-hint">Ohne Sprecherprüfung reagiert W.A.I.S. dann auf jede Stimme im Raum.</p>}
        </>
      )}
    </div>
  );
});

function PcSchalterKnopf({
  an,
  ausstehend,
  gesperrt,
  beschrieben,
  onSchalten,
  setZiel,
}: {
  an: boolean;
  ausstehend: boolean;
  gesperrt: boolean;
  /** Kennungen der Hinweise neben und unter dem Schalter (aria-describedby) */
  beschrieben?: string;
  onSchalten: (an: boolean) => boolean;
  setZiel: (ziel: boolean | null) => void;
}) {
  const uhr = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (uhr.current) clearTimeout(uhr.current);
  }, []);
  return (
    <button
      type="button"
      role="switch"
      aria-checked={an}
      className="pc-switch"
      data-an={an || undefined}
      aria-describedby={beschrieben}
      disabled={ausstehend || gesperrt}
      onClick={() => {
        const neu = !an;
        if (!onSchalten(neu)) return;
        setZiel(neu);
        if (uhr.current) clearTimeout(uhr.current);
        uhr.current = setTimeout(() => setZiel(null), SCHALT_WARTEN_MS); // ohne Rückmeldung wieder bedienbar
      }}
    >
      <span className="pc-switch-bahn" aria-hidden="true">
        <span className="pc-switch-knopf" />
      </span>
      {/* feste Beschriftung, der Zustand steht in aria-checked; der sichtbare Zusatz wird nicht doppelt vorgelesen */}
      <span>PC-Steuerung</span>
      <span aria-hidden="true">{an ? "an" : "aus"}</span>
    </button>
  );
}

/**
 * Betriebsart dieses Geräts: Büro (Kern auf Sokrates-2) oder Unterwegs (Kern auf diesem PC). Umschalten nur ohne
 * laufendes Gespräch; es gilt ab dem nächsten Verbinden. In der Desktop-App startet "Unterwegs" den lokalen Kern.
 */
const BetriebsartWahl = memo(function BetriebsartWahl() {
  const art = useBetriebsart();
  const offline = useSelect(wamo, (s) => s.presence === "offline");
  const [laeuft, setLaeuft] = useState(false);
  const serverBrowser = useServerBrowser();
  const knoepfe = useRef<(HTMLButtonElement | null)[]>([]);
  if (!BUERO_VERFUEGBAR || serverBrowser) return null; // Browser auf dem Server: nur Büro, nichts zu wählen
  const waehle = (neu: Betriebsart) => {
    if (neu === art || !offline || laeuft) return;
    setLaeuft(true);
    void betriebsartSetzen(neu)
      .then((gilt) => zeigeToast(`Betriebsart ${KERN[gilt].name}: Kern ${KERN[gilt].ort}`))
      .catch(() => zeigeToast("Betriebsart konnte nicht umgeschaltet werden"))
      .finally(() => setLaeuft(false));
  };
  // Radiogruppe nach WAI-ARIA wie ModellWahl: ein Tabstopp, Pfeiltasten wählen, Home und Ende springen
  const taste = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const ziel = nachbar(index, e.key, BETRIEBSARTEN.length);
    if (ziel === null) return;
    e.preventDefault();
    knoepfe.current[ziel]?.focus();
    waehle(BETRIEBSARTEN[ziel]);
  };
  return (
    <div className="betriebsart">
      <div className="betriebsart-wahl" role="radiogroup" aria-label="Betriebsart">
        {BETRIEBSARTEN.map((a, i) => (
          <button
            key={a}
            ref={(el) => {
              knoepfe.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={a === art}
            data-an={a === art || undefined}
            tabIndex={a === art ? 0 : -1}
            disabled={!offline || laeuft}
            onClick={() => waehle(a)}
            onKeyDown={(e) => taste(e, i)}
          >
            {KERN[a].name}
          </button>
        ))}
      </div>
      <span className="pc-switch-hint">
        Kern: {KERN[art].ort}
        {!offline && " (umschalten nach dem Gespräch)"}
      </span>
    </div>
  );
});

/** Stand der Einrichtung dieses Laptops (Desktop-App, Betriebsart Büro); gelesen aus dem Store von GeraetEinrichtung. */
const EinrichtungStand = memo(function EinrichtungStand() {
  const stand = useSelect(geraeteAnzeige, (s) => s);
  const art = useBetriebsart();
  const desktop = useDesktopApp();
  const { text, art: zustand } = geraeteStandText(stand, { desktop, bueroBetrieb: art === "buero" });
  return (
    <p className="ez-text ez-stand" data-zustand={zustand} role="status">
      {text}
    </p>
  );
});

/**
 * Abschnitt "Geräte und PC": Status der Verbindungen (jeder), Geräteverwaltung, PC-Steuerung samt Autostart und Fernzugriff (nur Admin), Betriebsart
 * (wo es etwas zu wählen gibt) und der Stand der Geräteeinrichtung (nur Desktop-App). Welche Blöcke es gibt, entscheidet
 * geraeteBloecke (lib/einstellungenAbschnitte.ts).
 */
export const GeraeteAbschnitt = memo(function GeraeteAbschnitt({ onPcSteuerung }: { onPcSteuerung: (an: boolean) => boolean }) {
  const rolle = useSelect(wamo, (s) => s.profil?.rolle ?? null);
  const desktop = useDesktopApp();
  const serverBrowser = useServerBrowser();
  const { admin: pcAdmin } = usePcSchalter();
  const bloecke = geraeteBloecke({ rolle, desktop, serverBrowser, bueroVerfuegbar: BUERO_VERFUEGBAR, pcAdmin });
  return (
    <>
      {bloecke.includes("status") && (
        <Block titel="Verbindungen">
          <StatusDetails kompakt={false} />
        </Block>
      )}
      {bloecke.includes("verwaltung") && (
        <Block titel="Geräteverwaltung">
          <GeraeteVerwaltung />
        </Block>
      )}
      {bloecke.includes("pc") && (
        <Block titel="PC-Steuerung">
          <PcSteuerungSchalter onSchalten={onPcSteuerung} />
        </Block>
      )}
      {bloecke.includes("fernzugriff") && (
        <Block titel="Fernzugriff">
          <Fernzugriff />
        </Block>
      )}
      {bloecke.includes("betriebsart") && (
        <Block titel="Betriebsart">
          <BetriebsartWahl />
        </Block>
      )}
      {bloecke.includes("einrichtung") && (
        <Block titel="Gerät einrichten">
          <EinrichtungStand />
        </Block>
      )}
    </>
  );
});
