"use client";

import { memo, useId, useState } from "react";
import { HinweiseListe } from "@/components/Hinweise";
import { mikrofonFreigeben, useMikrofonListe } from "@/components/MikrofonWahl";
import { SprachWahl } from "@/components/SprachWahl";
import { useEffektiveDarstellung } from "@/components/kommando/ansicht";
import {
  DARSTELLUNGEN,
  DARSTELLUNG_BESCHREIBUNG,
  DARSTELLUNG_TEXT,
  darstellungSetzen,
} from "@/components/kommando/darstellung";
import { KERN, kernUrl, useBetriebsart } from "@/lib/betriebsart";
import { rolleText } from "@/lib/einstellungenAbschnitte";
import { useDesktopApp, useServerBrowser } from "@/lib/geraet";
import { gewaehltesMikrofon, standardText, type Mikrofon } from "@/lib/mikrofon";
import { untertitelSetzen, useUntertitel } from "@/lib/einstellungen";
import { useModellzugangSenden } from "@/lib/modellzugangApi";
import { useNutzer } from "@/lib/nutzer";
import { zurGeraeteverwaltung } from "@/lib/einstellungenHash";
import { useSelect } from "@/lib/store";
import { THEMEN, themaWaehlen, type Thema } from "@/lib/thema";
import type { ModellzugangAnfrage } from "@/lib/useWamo";
import { useThema } from "@/lib/useThema";
import { istOnline, wamo } from "@/lib/wamo";
import { Block, Daten } from "./Block";
import { MikrofonTest } from "./MikrofonTest";
import { StillStartEinstellung } from "./StillStart";

/** Version aus package.json, zur Build-Zeit eingesetzt (next.config.ts), wie in der Fußzeile der Anmeldeseite. */
const VERSION = process.env.WAMO_VERSION ?? "0.1.0";

// ---------- Konto ----------
export const KontoAbschnitt = memo(function KontoAbschnitt({
  email,
  onAbmelden,
}: {
  email: string | null;
  onAbmelden: () => void;
}) {
  const profil = useSelect(wamo, (s) => s.profil);
  const rolle = profil?.rolle ?? null;
  return (
    <>
      <Block titel="Angemeldet">
        <Daten
          zeilen={[
            { name: "E-Mail", wert: email ?? "unbekannt" },
            { name: "Aktives Profil", wert: profil?.name ?? "erscheint mit dem ersten Gespräch" },
            {
              name: "Rolle",
              wert: rolle ? (
                <span className="role-tag" data-rolle={rolle}>
                  {rolleText(rolle)}
                </span>
              ) : (
                rolleText(null)
              ),
            },
          ]}
        />
        <p className="ez-klein">
          Abmelden beendet ein laufendes Gespräch und meldet dich auf diesem Gerät ab. Für einen Profilwechsel meldest du dich danach
          mit dem anderen Profil wieder an.
        </p>
        <div>
          <button type="button" className="btn-secondary" onClick={onAbmelden}>
            Abmelden
          </button>
        </div>
      </Block>
    </>
  );
});

// ---------- Mikrofon und Sprache ----------
/**
 * Mikrofonwahl (lib/mikrofon.ts): gespeichert je Person auf diesem Gerät, in diesem Browser oder dieser App. Die Auswahl nennt das
 * Standardgerät (im Browser das des Browsers, das nicht dem von Windows folgen muss, in der Desktop-App das von Windows) mit Namen und
 * sagt, welches Gerät gerade läuft oder beim nächsten Gespräch läuft. Ohne Freigabe nennt der Browser keine Geräte: Dann gibt es einen
 * Knopf, der das Mikrofon kurz öffnet und gleich wieder schließt. Darunter der Mikrofontest (MikrofonTest.tsx) für genau dieses Gerät.
 */
function MikrofonEinstellung({
  laden,
  waehlen,
  umschalten,
  ausgabeAnhalten,
  merken,
}: {
  laden: () => Promise<Mikrofon[]>;
  waehlen: (id: string) => boolean;
  umschalten?: () => void;
  ausgabeAnhalten?: (an: boolean) => void;
  merken: boolean;
}) {
  const id = useId();
  const nutzer = useNutzer();
  const desktop = useDesktopApp();
  const [anstoss, setAnstoss] = useState(0);
  const [freigabe, setFreigabe] = useState<"bereit" | "laeuft" | "abgelehnt">("bereit");
  const [, setGewechselt] = useState(0); // nach einer Wahl neu zeichnen; die Wahl selbst liegt in lib/mikrofon.ts
  const liste = useMikrofonListe(laden, anstoss);
  const online = useSelect(wamo, istOnline);
  const aktuell = useSelect(wamo, (s) => s.mikrofon);
  const gewaehlt = gewaehltesMikrofon(nutzer.id);
  const angeschlossen = liste?.find((m) => m.id === gewaehlt) ?? null;
  const standard = liste?.find((m) => m.standard) ?? null;
  const standardName = standard ? `${standardText(desktop)} (${standard.label})` : standardText(desktop);
  const fehlt = gewaehlt !== null && liste !== null && liste.length > 0 && angeschlossen === null;
  const ohneGeraete = liste !== null && liste.length === 0;

  const freigeben = async () => {
    setFreigabe("laeuft");
    const ok = await mikrofonFreigeben();
    setFreigabe(ok ? "bereit" : "abgelehnt");
    setAnstoss((n) => n + 1);
  };

  const stand = !liste
    ? "Mikrofone werden gesucht …"
    : ohneGeraete
      ? aktuell
        ? "Keine Mikrofone gefunden. Schließe ein Mikrofon oder Headset an."
        : "Noch keine Mikrofone sichtbar."
      : online
        ? aktuell
          ? `In Benutzung: ${aktuell}. Ein Wechsel gilt sofort.`
          : "Im Gespräch ist gerade kein Mikrofon offen. Die Wahl gilt, sobald es läuft."
        : `Beim nächsten Gespräch: ${angeschlossen ? angeschlossen.label : standardName}. Die Wahl gilt für dich auf diesem Gerät.`;

  return (
    <>
      <div className="ez-feld">
        <label htmlFor={id}>Mikrofon</label>
        <select
          id={id}
          value={angeschlossen ? angeschlossen.id : ""}
          disabled={!liste || ohneGeraete}
          onChange={(e) => {
            if (waehlen(e.target.value)) setGewechselt((n) => n + 1);
          }}
        >
          <option value="">{standardName}</option>
          {liste?.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
      </div>
      <p className="ez-klein" role="status">
        {stand}
      </p>
      {fehlt && (
        <p className="ez-klein" data-rueckfall>
          Dein gewähltes Mikrofon ist gerade nicht angeschlossen. Bis es wieder da ist, nimmt W.A.I.S. das {standardText(desktop)}.
        </p>
      )}
      {/* ohne offenes Mikrofon (auch in einer still gestarteten Sitzung) fehlt oft nur die Freigabe */}
      {ohneGeraete && !aktuell && (
        <>
          <p className="ez-klein">
            Die Namen der Mikrofone zeigt {desktop ? "die App" : "der Browser"} erst, wenn du W.A.I.S. das Mikrofon einmal freigegeben hast.
            Beim Freigeben öffnet sich das Mikrofon kurz und schließt sofort wieder, aufgenommen wird nichts.
          </p>
          <div>
            <button type="button" className="btn-secondary btn-small" disabled={freigabe === "laeuft"} onClick={() => void freigeben()}>
              Mikrofon freigeben
            </button>
          </div>
          {freigabe === "abgelehnt" && (
            <p className="ez-klein" role="alert">
              {desktop
                ? "Windows hat das Mikrofon nicht freigegeben. Erlaube es unter Einstellungen > Datenschutz und Sicherheit > Mikrofon."
                : "Der Browser hat das Mikrofon nicht freigegeben. Erlaube es für diese Seite (Symbol links neben der Adresse) und versuche es noch einmal."}
            </p>
          )}
        </>
      )}
      {/* erst mit der Geräteliste: sonst träfe ein schneller Klick das Standardgerät statt des gewählten */}
      {liste !== null && !ohneGeraete && (
        <MikrofonTest
          geraetId={angeschlossen ? angeschlossen.id : null}
          geraetName={angeschlossen ? angeschlossen.label : (standard?.label ?? null)}
          merken={merken}
          mikrofonUmschalten={umschalten}
          ausgabeAnhalten={ausgabeAnhalten}
        />
      )}
    </>
  );
}

/**
 * Abschnitt "Mikrofon und Sprache": Mikrofonwahl mit Test, der Schalter "Still starten beim Tippen" und Hören und Sprechen (SprachWahl:
 * Soniox oder im Haus je Richtung, dazu die Stimme im Haus; früher ein Teil des Modellzugangs, dort stand der Satz "Umschalten unter
 * Modellzugang" für eine Anzeige, die hier nur las). Darunter, was in dieser Sitzung gerade läuft.
 * nurMikrofon: Laborsicht (lib/laborPlatz.ts), nur die Mikrofonwahl mit dem Mikrofontest als reiner Anzeige (ohne Speicher); die übrigen
 * Blöcke entfallen. mikrofonUmschalten: Mikrofon des laufenden Gesprächs umschalten (useWamo, toggleMic), für die Dauer des Tests.
 * ausgabeAnhalten: W.A.I.S. schweigt während des Tests (useWamo, ausgabeAnhalten); die Laborsicht bekommt es nicht.
 * modellzugang: Datenkanal des Kerns für die Wahl von Hören und Sprechen (useWamo, modellzugang); ohne ihn geht die Wahl über die
 * HTTP-Schnittstelle (lib/modellzugangApi.ts).
 */
export const SpracheAbschnitt = memo(function SpracheAbschnitt({
  mikrofone,
  mikrofonWaehlen,
  mikrofonUmschalten,
  ausgabeAnhalten,
  modellzugang,
  nurMikrofon = false,
}: {
  mikrofone: () => Promise<Mikrofon[]>;
  mikrofonWaehlen: (id: string) => boolean;
  mikrofonUmschalten?: () => void;
  ausgabeAnhalten?: (an: boolean) => void;
  modellzugang?: (anfrage: ModellzugangAnfrage) => boolean;
  nurMikrofon?: boolean;
}) {
  const modelle = useSelect(wamo, (s) => s.betrieb?.modelle ?? null);
  const senden = useModellzugangSenden(modellzugang);
  if (nurMikrofon) {
    return (
      <Block titel="Eingabe">
        <MikrofonEinstellung laden={mikrofone} waehlen={mikrofonWaehlen} umschalten={mikrofonUmschalten} merken={false} />
      </Block>
    );
  }
  return (
    <>
      <Block titel="Eingabe">
        <MikrofonEinstellung
          laden={mikrofone}
          waehlen={mikrofonWaehlen}
          umschalten={mikrofonUmschalten}
          ausgabeAnhalten={ausgabeAnhalten}
          merken
        />
      </Block>
      <Block titel="Start beim Tippen">
        <StillStartEinstellung />
      </Block>
      <Block titel="Hören und Sprechen">
        <SprachWahl senden={senden} />
        {modelle && (modelle.stt || modelle.tts) && (
          <Daten
            zeilen={[
              { name: "Läuft gerade: Spracherkennung", wert: modelle.stt ?? "unbekannt" },
              { name: "Läuft gerade: Sprachausgabe", wert: modelle.tts ?? "unbekannt" },
            ]}
          />
        )}
      </Block>
    </>
  );
});

// ---------- Darstellung ----------
const THEMA_TEXT: Record<Thema, string> = { dunkel: "Dunkel", hell: "Hell" };
const THEMA_BESCHREIBUNG: Record<Thema, string> = {
  dunkel: "Dunkler Grund mit rotem Licht. Das ist der Standard.",
  hell: "Heller Grund mit denselben Farben, gut für helle Räume.",
};

/** Hell oder Dunkel, je Gerät gespeichert (lib/thema.ts). In der Darstellung Nacht bleibt es dunkel, die Auswahl ist dann gesperrt. */
function HelligkeitBlock() {
  const id = useId();
  const thema = useThema();
  const nacht = useEffektiveDarstellung().effektiv === "nacht";
  return (
    <Block titel="Helligkeit">
      <fieldset className="ez-radios" disabled={nacht}>
        <legend className="sr-only">Helligkeit</legend>
        {THEMEN.map((t) => (
          <label key={t} className="ez-radio" data-an={thema === t || undefined}>
            <input
              type="radio"
              name={`${id}-thema`}
              value={t}
              checked={thema === t}
              onChange={() => themaWaehlen(t)}
              aria-labelledby={`${id}-${t}-n`}
              aria-describedby={`${id}-${t}-b`}
            />
            <span className="ez-radio-text">
              <span id={`${id}-${t}-n`} className="ez-radio-name">
                {THEMA_TEXT[t]}
              </span>
              <span id={`${id}-${t}-b`} className="ez-radio-beschr">
                {THEMA_BESCHREIBUNG[t]}
              </span>
            </span>
          </label>
        ))}
      </fieldset>
      <p className="ez-klein" role="status">
        {nacht ? "In der Darstellung Nacht bleibt die Oberfläche dunkel." : ""}
      </p>
    </Block>
  );
}

/**
 * Live-Untertitel unter dem Kern, je Person auf diesem Gerät, Standard aus (lib/untertitel.ts). Der Hinweis sagt, warum: Die
 * Untertitel zeigen alles, was das Mikrofon hört, der Chat links nur Sätze nach der Stimmprüfung (lib/stimmFilter.ts).
 */
function UntertitelBlock() {
  const id = useId();
  const { id: userId } = useNutzer();
  const an = useUntertitel(userId);
  return (
    <Block titel="Untertitel">
      <label className="pc-auto" htmlFor={`${id}-untertitel`}>
        <input
          id={`${id}-untertitel`}
          type="checkbox"
          checked={an}
          disabled={userId === null}
          aria-describedby={`${id}-hinweis`}
          onChange={(e) => untertitelSetzen(userId, e.target.checked)}
        />
        <span>Live-Untertitel unter dem Kern zeigen (dieses Gerät)</span>
      </label>
      <div id={`${id}-hinweis`}>
        <p className="ez-klein">
          Standard aus. Die Untertitel zeigen sofort, was das Mikrofon hört, auch Sätze einer fremden Stimme, bevor W.A.I.S. sie verwirft. Im
          Gespräch links erscheinen nur Sätze, die die Stimmprüfung angenommen hat.
        </p>
        {userId === null && <p className="ez-klein">Wählbar, sobald du angemeldet bist.</p>}
      </div>
    </Block>
  );
}

export const DarstellungAbschnitt = memo(function DarstellungAbschnitt() {
  const id = useId();
  const { gewaehlt, pausiert } = useEffektiveDarstellung();
  return (
    <>
      <HelligkeitBlock />
      <Block titel="Ansicht">
        <fieldset className="ez-radios">
          <legend className="sr-only">Darstellung</legend>
          {DARSTELLUNGEN.map((d) => (
            <label key={d} className="ez-radio" data-an={gewaehlt === d || undefined}>
              <input
                type="radio"
                name={`${id}-darstellung`}
                value={d}
                checked={gewaehlt === d}
                onChange={() => darstellungSetzen(d)}
                aria-labelledby={`${id}-${d}-n`}
                aria-describedby={`${id}-${d}-b`}
              />
              <span className="ez-radio-text">
                <span id={`${id}-${d}-n`} className="ez-radio-name">
                  {DARSTELLUNG_TEXT[d]}
                </span>
                <span id={`${id}-${d}-b`} className="ez-radio-beschr">
                  {DARSTELLUNG_BESCHREIBUNG[d]}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
        <p className="ez-klein" role="status">
          {pausiert ? `${DARSTELLUNG_TEXT[gewaehlt]} pausiert, solange etwas auf deine Entscheidung wartet.` : ""}
        </p>
        <p className="ez-klein">Im Gespräch wechselst du oben in der Mitte.</p>
      </Block>
      <UntertitelBlock />
    </>
  );
});

// ---------- Info ----------
export const InfoAbschnitt = memo(function InfoAbschnitt({ admin }: { admin: boolean }) {
  const gewaehlt = useBetriebsart();
  const betrieb = useSelect(wamo, (s) => s.betrieb);
  const desktop = useDesktopApp();
  const serverBrowser = useServerBrowser();
  // Verbunden: was der Kern meldet. Sonst: die gewählte Betriebsart für das nächste Gespräch.
  const art = betrieb ? (betrieb.modus === "lokal" ? "unterwegs" : "buero") : gewaehlt;
  const adresse = kernUrl(art);
  return (
    <>
      <Block titel="Diese Version">
        <Daten
          zeilen={[
            { name: "Version", wert: <span className="num">{VERSION}</span> },
            { name: "Gerät", wert: desktop ? "Desktop-App" : serverBrowser ? "Browser auf Sokrates-2" : "Browser" },
          ]}
        />
      </Block>
      <Block titel="Kern">
        <Daten
          zeilen={[
            { name: "Betriebsart", wert: `${KERN[art].name}${betrieb ? "" : " (gewählt)"}` },
            { name: "Ort", wert: KERN[art].ort },
            { name: "Adresse", wert: adresse ? <span className="ez-adresse">{adresse}</span> : "nicht eingerichtet" },
          ]}
        />
      </Block>
      {admin && (
        <Block titel="Hinweise für Admins">
          <p className="ez-text">Neue und wartende Geräte sowie weitere Meldungen an dein Profil.</p>
          <div>
            <button type="button" className="btn-secondary btn-small" onClick={zurGeraeteverwaltung}>
              Zur Geräteverwaltung
            </button>
          </div>
          <HinweiseListe />
        </Block>
      )}
    </>
  );
});
