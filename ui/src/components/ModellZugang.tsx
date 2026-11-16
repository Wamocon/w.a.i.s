"use client";

import { memo } from "react";
import { ModellWahl } from "@/components/ModellWahl";
import { FELD, SchluesselFormular, useSchluesselAktionen } from "@/components/SchluesselFormular";
import { SprachWahl } from "@/components/SprachWahl";
import type { Modellzugang } from "@/lib/nachrichten";
import { useSelect } from "@/lib/store";
import type { ModellzugangAnfrage } from "@/lib/useWamo";
import { istOnline, wamo } from "@/lib/wamo";

function kopfzeile(z: Modellzugang | null): string {
  if (!z?.art) return z?.fehler ? "Stand nicht lesbar" : "Stand wird geladen …";
  if (z.art === "haus") {
    if (z.festgelegt) return "Nur Hausmodelle (vom Admin festgelegt)";
    return z.quelle === "wahl" ? "Nur Hausmodelle (von dir gewählt)" : "Nur Hausmodelle";
  }
  return z.quelle === "zuordnung" ? "Claude über den Schlüssel des Kerns" : "Claude mit eigenem Schlüssel";
}

/**
 * Karte Modellzugang des Profils (eigene Karte in der linken Spalte, auch ohne laufendes Gespräch). Oben der
 * Umschalter Automatisch oder Nur Hausmodelle (ModellWahl), darunter zwei getrennte Schlüsseltypen: der
 * Anthropic-API-Schlüssel für das Gespräch (bezahlt nach Verbrauch, Standardmodell Haiku) und der Claude-Code-Token
 * für Entwicklungsaufträge (aus dem Max-Tarif). Ganz unten die Wahl für Hören und Stimme (SprachWahl: Soniox oder im Haus).
 * Mit Sitzung gehen die Anfragen über den Datenkanal, sonst über die
 * HTTP-Schnittstelle des Kerns (lib/modellzugangApi.ts); der Kern speichert den Schlüssel verschlüsselt. Der
 * API-Schlüssel wird vorher mit einer kleinen Anfrage geprüft, der Token nur auf sein Format (eine Anfrage würde das
 * Kontingent verbrauchen). Nichts kommt zurück: es erscheinen nur "hinterlegt" und die letzten vier Zeichen.
 * Feld und Senden liegen in components/SchluesselFormular.tsx (auch für die Schritte beim Ausrollen).
 */
export const ModellZugang = memo(function ModellZugang({
  onAnfrage,
}: {
  onAnfrage?: (anfrage: ModellzugangAnfrage) => boolean;
}) {
  const online = useSelect(wamo, istOnline);
  const { zugang, sende, wartet, hinweis, hinterlegen, loeschen } = useSchluesselAktionen(onAnfrage);

  const festgelegt = zugang?.festgelegt === true;
  const hinterlegt = zugang?.hinterlegt === true;

  // Stand nicht lesbar (Kern nicht erreichbar, Anmeldung abgelaufen, Datenbank weg): konkreter Satz und neuer Versuch
  const standFehler = zugang && !zugang.art && zugang.fehler ? zugang.fehler : null;

  // Was für das Gespräch gerade gilt (nur der Stand, nie der Schlüssel)
  const wirkungGespraech =
    hinterlegt && zugang?.quelle === "wahl"
      ? "Im Modus Nur Hausmodelle wird der Schlüssel nicht benutzt."
      : hinterlegt
        ? zugang?.art === "claude" && zugang.modell
          ? `Das Gespräch läuft mit ${zugang.modell}.`
          : undefined
        : zugang?.quelle === "zuordnung"
          ? "Kein eigener Schlüssel hinterlegt; dein Profil nutzt den Schlüssel des Kerns."
          : "Ohne eigenen Schlüssel laufen Gespräch, Lernen, Zusammenfassung, Bilder und Websuche über die Hausmodelle.";

  return (
    <div className="mz-inhalt">
      {!online && (
        <p className="mz-offline" role="status">
          Gerade läuft kein Gespräch. Du kannst Schlüssel, Token, Modus und Stimme trotzdem hier einstellen: Die Änderung wird
          direkt am Kern gespeichert und gilt ab der nächsten Sitzung.
        </p>
      )}
      {standFehler && (
        <div className="mz-falsch" role="alert">
          <p className="mz-meldung" data-fehler>
            Fehler: {standFehler}
          </p>
          <button
            type="button"
            className="btn-secondary btn-small"
            onClick={() => {
              // Stand löschen und neu fragen: die Hauptansicht holt ihn dann wieder (useModellzugangStandHalten)
              wamo.set((s) => ({ ...s, modellzugang: null }));
            }}
          >
            Erneut versuchen
          </button>
        </div>
      )}
      {festgelegt ? (
        <p className="mz-offline">
          Ein Admin hat dein Profil auf Hausmodelle festgelegt. Eigene Schlüssel und Token sind nicht möglich.
        </p>
      ) : (
        <>
          <SchluesselFormular
            art="api"
            {...FELD.api}
            wirkung={wirkungGespraech}
            hinterlegt={hinterlegt}
            ende={zugang?.ende}
            gesetzt={zugang?.geprueft}
            wartet={wartet}
            hinweis={hinweis}
            workspace
            onHinterlegen={(wert, ws) => hinterlegen("api", wert, ws)}
            onUmleiten={(art, wert) => hinterlegen(art, wert, "")}
            onLoeschen={() => loeschen("api")}
          />
          <SchluesselFormular
            art="code"
            {...FELD.code}
            hinterlegt={zugang?.codeHinterlegt === true}
            ende={zugang?.codeEnde}
            gesetzt={zugang?.codeGesetzt}
            wartet={wartet}
            hinweis={hinweis}
            onHinterlegen={(wert) => hinterlegen("code", wert, "")}
            onUmleiten={(art, wert) => hinterlegen(art, wert, "")}
            onLoeschen={() => loeschen("code")}
          />
        </>
      )}
      <section className="mz-abschnitt" aria-labelledby="modellzugang-modus">
        <h4 id="modellzugang-modus" className="mz-ueberschrift">
          Modus
        </h4>
        <p className="mz-zweck">Welche Modelle W.A.I.S. benutzen darf, unabhängig davon, welche Schlüssel hinterlegt sind.</p>
        <p className="mz-statuszeile">
          <span className="mz-art" data-art={zugang?.art}>
            {kopfzeile(zugang)}
          </span>
        </p>
        <ModellWahl senden={sende} />
      </section>
      <section className="mz-abschnitt" aria-labelledby="modellzugang-stimme">
        <h4 id="modellzugang-stimme" className="mz-ueberschrift">
          Hören und Sprechen
        </h4>
        <p className="mz-zweck">Wo dein Gesprochenes in Text und die Antworten von W.A.I.S. in Sprache umgewandelt werden.</p>
        <SprachWahl senden={sende} />
      </section>
      <p className="mz-klein">
        Beides liegt verschlüsselt im Kern, wird nie angezeigt und nie in Gesprächen, Aufgaben oder im Gedächtnis
        gespeichert. API-Schlüssel und Token sind getrennt: Der Token ersetzt den Schlüssel nicht. Änderungen gelten ab
        der nächsten Sitzung.
      </p>
    </div>
  );
});
