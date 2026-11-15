"use client";

import { useEffect, useRef, useState } from "react";
import { useDesktopApp } from "@/lib/geraet";
import {
  appVersion,
  fortschrittText,
  groesseText,
  hashBefehl,
  VERGLEICH_SATZ,
  versionsHinweis,
  type InstallerManifest,
} from "@/lib/installer";
import { installerLaden, installerStand } from "@/lib/installerApi";
import { KOPIERT_MS, kopierChipText, type KopierStatus } from "@/lib/kopieren";
import type { EinrichtungsSchrittProps } from "./schritte";
import { SchrittKnoepfe } from "./SchrittKnoepfe";

type Stand = { art: "laedt" } | { art: "fehler"; text: string } | { art: "bereit"; manifest: InstallerManifest };
type Download =
  | { art: "ruhe" }
  | { art: "laeuft"; geladen: number; gesamt: number | null }
  | { art: "fertig" }
  | { art: "abgebrochen" }
  | { art: "fehler"; text: string };

/** Kopierknopf mit kurzer Bestätigung in einer Live-Region daneben (wie im Canvas, lib/kopieren.ts). */
function KopierKnopf({ text, name }: { text: string; name: string }) {
  const [status, setStatus] = useState<KopierStatus>("");
  const uhr = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (uhr.current) clearTimeout(uhr.current);
    },
    [],
  );
  const kopieren = async () => {
    let neu: KopierStatus = "kopiert";
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      neu = "fehler"; // zum Beispiel Zwischenablage nicht erlaubt
    }
    setStatus(neu);
    if (uhr.current) clearTimeout(uhr.current);
    uhr.current = setTimeout(() => setStatus(""), KOPIERT_MS);
  };
  return (
    <span className="ea-kopie">
      <button type="button" className="btn-secondary btn-small" aria-label={name} onClick={() => void kopieren()}>
        Kopieren
      </button>
      <span className="ea-chip" aria-live="polite" data-art={status === "fehler" ? "fehler" : undefined}>
        {kopierChipText(status)}
      </span>
    </span>
  );
}

/**
 * Installer für Windows aus dem Kern (docs/ausrollen-neue-nutzer.md 4.2): Version, Größe und SHA-256 aus dem geprüften
 * Manifest, Download mit Fortschritt und Abbrechen. Angeboten wird die Datei nur bei passender Prüfsumme; danach stehen
 * der Befehl Get-FileHash zum Kopieren und der Satz zum Vergleich mit dem Willkommensblatt da. In der Desktop-App kommt ein
 * Hinweis zur Version dazu. Als Schritt im Gerüst (weiter gesetzt) mit Knopfzeile, sonst als eigener Block.
 */
export function InstallerDownload({ weiter, zurueck }: Partial<EinrichtungsSchrittProps>) {
  const [stand, setStand] = useState<Stand>({ art: "laedt" });
  const [versuch, setVersuch] = useState(0);
  const [download, setDownload] = useState<Download>({ art: "ruhe" });
  const steuerung = useRef<AbortController | null>(null);
  const inApp = useDesktopApp();
  const hinweis = versionsHinweis(inApp ? appVersion() : null, stand.art === "bereit" ? stand.manifest : null, inApp);

  useEffect(() => {
    let aktiv = true;
    void installerStand().then((e) => {
      if (aktiv) setStand(e.ok ? { art: "bereit", manifest: e.manifest } : { art: "fehler", text: e.text });
    });
    return () => {
      aktiv = false;
    };
  }, [versuch]);

  // Beim Verlassen läuft kein Download weiter
  useEffect(() => () => steuerung.current?.abort(), []);

  const laeuft = download.art === "laeuft";

  const laden = async () => {
    if (stand.art !== "bereit" || laeuft || steuerung.current) return; // auch ein schneller Doppelklick startet nur einen Download
    const c = new AbortController();
    steuerung.current = c;
    setDownload({ art: "laeuft", geladen: 0, gesamt: stand.manifest.groesse });
    let zuletzt = -1;
    const ergebnis = await installerLaden(
      stand.manifest,
      (geladen, gesamt) => {
        // nur bei jedem neuen Prozent (oder MB ohne Gesamtgröße) neu zeichnen
        const schritt = gesamt ? Math.floor((geladen / gesamt) * 100) : Math.floor(geladen / 1_048_576);
        if (schritt === zuletzt || c.signal.aborted) return;
        zuletzt = schritt;
        setDownload({ art: "laeuft", geladen, gesamt: gesamt ?? stand.manifest.groesse });
      },
      c.signal,
    );
    if (steuerung.current === c) steuerung.current = null;
    setDownload(ergebnis.ok ? { art: "fertig" } : ergebnis.abgebrochen ? { art: "abgebrochen" } : { art: "fehler", text: ergebnis.text });
  };

  const befehl = stand.art === "bereit" ? hashBefehl(stand.manifest.datei) : null;

  return (
    <div className="ea-schritt">
      <section className="mz-abschnitt ea-installer" aria-label="Installer für Windows">
        {hinweis && <p className="ea-update">{hinweis}</p>}
        {stand.art === "laedt" && (
          <p className="ea-klein" role="status">
            Angaben zum Installer werden geladen …
          </p>
        )}
        {stand.art === "fehler" && (
          <div className="mz-falsch" role="alert">
            <p className="mz-meldung" data-fehler>
              Fehler: {stand.text}
            </p>
            <button
              type="button"
              className="btn-secondary btn-small"
              onClick={() => {
                setStand({ art: "laedt" });
                setVersuch((v) => v + 1);
              }}
            >
              Erneut versuchen
            </button>
          </div>
        )}
        {stand.art === "bereit" && (
          <>
            <p className="ea-text">
              Der Installer richtet W.A.I.S. auf deinem Laptop ein, ohne Administratorrechte. Vergleiche die Prüfsumme mit deinem
              Willkommensblatt.
            </p>
            <dl className="ea-daten">
              <div>
                <dt>Version</dt>
                <dd className="num">{stand.manifest.version}</dd>
              </div>
              <div>
                <dt>Größe</dt>
                <dd>{groesseText(stand.manifest.groesse)}</dd>
              </div>
              <div>
                <dt>Prüfsumme (SHA-256)</dt>
                <dd className="ea-wert">
                  <code className="ea-hash">{stand.manifest.sha256}</code>
                  <KopierKnopf text={stand.manifest.sha256} name="Prüfsumme kopieren" />
                </dd>
              </div>
            </dl>
            <div className="ea-knoepfe">
              <button
                type="button"
                className="btn-primary"
                aria-disabled={laeuft || undefined}
                onClick={() => void laden()}
              >
                {laeuft ? "Wird geladen …" : "Installer herunterladen"}
              </button>
              {laeuft && (
                <button type="button" className="btn-secondary" onClick={() => steuerung.current?.abort()}>
                  Abbrechen
                </button>
              )}
            </div>
            {download.art === "laeuft" && (
              <div className="ea-fortschritt">
                {/* ohne bekannte Gesamtgröße ohne Wert: ein unbestimmter Balken statt eines vollen */}
                <progress
                  value={download.gesamt ? download.geladen : undefined}
                  max={download.gesamt ?? undefined}
                  aria-label="Fortschritt des Downloads"
                  aria-valuetext={fortschrittText(download.geladen, download.gesamt)}
                />
                <span className="ea-klein">{fortschrittText(download.geladen, download.gesamt)}</span>
              </div>
            )}
            <p className="mz-meldung" role="status">
              {laeuft
                ? "Download läuft."
                : download.art === "fertig"
                  ? `Die Datei ist vollständig angekommen, der Browser speichert ${stand.manifest.datei} (meist im Ordner Downloads). Vergleiche vor dem Start die Prüfsumme mit deinem Willkommensblatt.`
                  : download.art === "abgebrochen"
                    ? "Download abgebrochen."
                    : ""}
            </p>
            {download.art === "fehler" && (
              <p className="mz-meldung" role="alert" data-fehler>
                Fehler: {download.text}
              </p>
            )}
            {download.art === "fertig" && befehl && (
              <div className="ea-pruefen">
                <p className="ea-text">Prüfe die Datei, bevor du sie startest. Öffne PowerShell im Ordner Downloads und gib ein:</p>
                <div className="ea-befehl">
                  <code>{befehl}</code>
                  <KopierKnopf text={befehl} name="Befehl kopieren" />
                </div>
                <p className="ea-text">{VERGLEICH_SATZ}</p>
              </div>
            )}
          </>
        )}
      </section>
      {weiter && <SchrittKnoepfe weiter={weiter} zurueck={zurueck} text="Weiter" gesperrt={laeuft} />}
    </div>
  );
}
