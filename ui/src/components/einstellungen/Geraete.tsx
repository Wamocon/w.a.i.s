"use client";

import { memo, useEffect, useRef, useState, type KeyboardEvent } from "react";
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
import { HINWEIS_OHNE_SITZUNG, SCHALT_WARTEN_MS, TEXT_WARTET } from "@/lib/pcSchalter";
import { useSelect } from "@/lib/store";
import { usePcSchalter } from "@/lib/usePcSchalter";
import { wamo, zeigeToast } from "@/lib/wamo";
import { Block } from "./Block";
import { Fernzugriff } from "./Fernzugriff";
import { GeraeteVerwaltung } from "./GeraeteVerwaltung";

/**
 * Schalter "PC-Steuerung" für diese Sitzung: Standard aus, nur für Admins (lib/pcSchalter.ts, Laborkonten nie). Mit Sitzung geht nur
 * der Wunsch hinaus; was gilt, meldet der Kern in betrieb.pc_steuerung zurück. Ohne Sitzung ist er in der Desktop-App bedienbar: "an"
 * startet still eine Sitzung (useWamo.pcSteuerung) und schaltet ein, sobald der Kern den PC als verbunden meldet. Solange das läuft,
 * ist er gesperrt (pcEinschalten.wartet); klappt es nicht, steht der Grund darunter (pcEinschalten.hinweis, für Screenreader als Status).
 */
const PcSteuerungSchalter = memo(function PcSteuerungSchalter({ onSchalten }: { onSchalten: (an: boolean) => boolean }) {
  const { anzeige } = usePcSchalter();
  const an = useSelect(wamo, (s) => s.betrieb?.pcSteuerung === "an");
  const belegt = useSelect(wamo, (s) => s.betrieb?.pcBelegt === true && s.betrieb?.pcSteuerung !== "an");
  const pcName = useSelect(wamo, (s) => s.betrieb?.pcName ?? null);
  const ein = useSelect(wamo, (s) => s.pcEinschalten);
  const [ziel, setZiel] = useState<boolean | null>(null);
  const auto = usePcAuto();
  const ausstehend = ein.wartet || (ziel !== null && ziel !== an && !belegt);
  if (anzeige.art === "verborgen") return null;
  if (anzeige.art === "nur_desktop") {
    // Browser auf dem Server: die PC-Werkzeuge gehören zur Desktop-App (lib/geraet.ts)
    return (
      <div className="pc-steuerung">
        <p className="pc-switch-hint">PC-Steuerung: nur in der Desktop-App verfügbar</p>
      </div>
    );
  }
  const hinweis = ausstehend
    ? ein.wartet
      ? TEXT_WARTET
      : "wird geschaltet …"
    : belegt
      ? "eine andere Sitzung steuert diesen PC gerade"
      : anzeige.art === "gesperrt"
        ? anzeige.hinweis
        : anzeige.ohneSitzung
          ? HINWEIS_OHNE_SITZUNG
          : `gilt nur für diese Sitzung${pcName ? `, Ziel ${pcName}` : ""}`;
  return (
    <div className="pc-steuerung" id={PC_STEUERUNG_ID} tabIndex={-1} role="group" aria-label="PC-Steuerung">
      <div className="pc-switch-row">
        <PcSchalterKnopf
          an={an}
          ausstehend={ausstehend}
          gesperrt={anzeige.art === "gesperrt"}
          onSchalten={onSchalten}
          setZiel={setZiel}
        />
        <span className="pc-switch-hint">{hinweis}</span>
      </div>
      {/* immer eingehängt, nur der Text wechselt: ein neu eingefügter Bereich wird oft überhört */}
      <p className="pc-switch-hint pc-ein-hinweis" role="status">
        {ein.hinweis ?? ""}
      </p>
      <label className="pc-auto">
        <input type="checkbox" checked={auto} onChange={(e) => pcAutoSetzen(e.target.checked)} />
        <span>PC-Steuerung beim Start automatisch einschalten (dieses Gerät)</span>
      </label>
      {auto && <p className="pc-auto-hint">Ohne Sprecherprüfung reagiert W.A.I.S. dann auf jede Stimme im Raum.</p>}
    </div>
  );
});

function PcSchalterKnopf({
  an,
  ausstehend,
  gesperrt,
  onSchalten,
  setZiel,
}: {
  an: boolean;
  ausstehend: boolean;
  gesperrt: boolean;
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
