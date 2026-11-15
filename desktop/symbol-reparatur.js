"use strict";

/**
 * "Taskleisten-Symbol reparieren" im Tray (nur Windows, reines Node-Modul ohne electron-Import, testbar).
 *
 * Befund 14.11.2026: Nach einem Update zeigte die Taskleiste für das Fenster von W.A.I.S. ein leeres Datei-Symbol, obwohl EXE,
 * Verknüpfung im Startmenü und Fenster das richtige Symbol hatten. Der Zustand hing an der App-Kennung (ein Testfenster mit
 * anderer Kennung zeigte dasselbe Symbol richtig) und überstand Neustarts des Explorers. Geholfen hat nur: Explorer beenden, die
 * Dateien *.db in %LOCALAPPDATA%\Microsoft\Windows\Caches löschen (App-Zwischenspeicher der Shell, Windows legt sie neu an) und
 * den Explorer starten. Der Installer beugt vor (build/installer.nsh), repariert aber keinen schon hängengebliebenen Eintrag.
 * Das erledigt scripts/wamo-symbol-reparieren.ps1, hier nur nach einer Rückfrage.
 */

const path = require("node:path");

const SKRIPT_NAME = "wamo-symbol-reparieren.ps1";
const MENUE_TEXT = "Taskleisten-Symbol reparieren …";

/** Rückfrage vor der Reparatur (Optionen für dialog.showMessageBox). Abbrechen ist die Vorgabe. */
function frageDialog() {
  return {
    type: "question",
    title: "W.A.I.S.",
    message: "Taskleisten-Symbol reparieren?",
    detail:
      "Hilft, wenn W.A.I.S. in der Taskleiste nur ein leeres Symbol zeigt.\n\n" +
      "Dafür wird der Windows-Explorer beendet und neu gestartet. Die Taskleiste verschwindet für einige Sekunden, " +
      "offene Explorer-Fenster schließen sich. Gelöscht wird nur der App-Zwischenspeicher der Shell " +
      "(%LOCALAPPDATA%\\Microsoft\\Windows\\Caches\\*.db), Windows legt ihn neu an. W.A.I.S. läuft weiter.",
    buttons: ["Reparieren", "Abbrechen"],
    defaultId: 1,
    cancelId: 1,
    noLink: true,
  };
}

/** Aufruf des Skripts: installiert aus resources\scripts, im Entwicklermodus aus dem Repository (beides ressourcen\scripts). */
function aufruf({ ressourcen, powershell }) {
  return {
    datei: powershell,
    argumente: ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path.join(ressourcen, "scripts", SKRIPT_NAME), "-Bestaetigt"],
  };
}

/** Letzte Zeile der Ausgabe als JSON (das Skript schreibt sein Ergebnis zuletzt), sonst null. */
function ergebnisZeile(stdout) {
  const zeilen = String(stdout ?? "").trim().split(/\r?\n/);
  try {
    const j = JSON.parse(zeilen[zeilen.length - 1]);
    return j && typeof j.ergebnis === "string" ? j : null;
  } catch {
    return null;
  }
}

/** Ergebnis des Skripts in eine Meldung für den Nutzer übersetzen: { ok, meldung }. */
function auswerten({ stdout, fehler = null }) {
  const j = ergebnisZeile(stdout);
  if (j?.ergebnis === "repariert") {
    const n = Array.isArray(j.geloescht) ? j.geloescht.length : 0;
    return {
      ok: true,
      meldung: `Erledigt: ${n} ${n === 1 ? "Datei" : "Dateien"} des App-Zwischenspeichers gelöscht, Explorer ${j.explorer ?? "neu gestartet"}. ` +
        "Zeigt die Taskleiste noch ein leeres Symbol, W.A.I.S. im Tray beenden und neu starten.",
    };
  }
  if (j?.ergebnis === "teilweise") {
    const gesperrt = Array.isArray(j.gesperrt) ? j.gesperrt.join(", ") : "";
    return {
      ok: false,
      meldung: `Nicht alles ließ sich löschen (gesperrt: ${gesperrt}). Bitte bei Windows abmelden und neu anmelden oder den PC neu starten, dann die Reparatur noch einmal ausführen.`,
    };
  }
  const grund = fehler ? `Code ${fehler.code ?? "?"}` : "keine Antwort des Skripts";
  return { ok: false, meldung: `Die Reparatur ist fehlgeschlagen (${grund}).` };
}

/**
 * Fragt nach, führt das Skript aus und meldet das Ergebnis. Wirft nie.
 * Optionen: plattform, ressourcen (PFADE.ressourcen), powershell (Pfad), fragen (dialog.showMessageBox), ausfuehren (datei,
 * argumente) => Promise<{ stdout }> (wirft bei Fehlercode, err.stdout wird ausgewertet), melden (dialog.showMessageBox), log.
 * Liefert "nicht-windows", "abgebrochen", "repariert" oder "fehler".
 */
async function symbolReparieren({ plattform, ressourcen, powershell, fragen, ausfuehren, melden, log = () => {} }) {
  if (plattform !== "win32") return "nicht-windows";
  const antwort = await fragen(frageDialog());
  if (antwort?.response !== 0) return "abgebrochen";
  const { datei, argumente } = aufruf({ ressourcen, powershell });
  let ergebnis;
  try {
    const r = await ausfuehren(datei, argumente);
    ergebnis = auswerten({ stdout: r?.stdout });
  } catch (err) {
    log(`Symbol-Reparatur fehlgeschlagen (Code ${err?.code ?? "?"}): ${String(err?.stderr ?? err?.message ?? "").trim().slice(0, 300)}`);
    ergebnis = auswerten({ stdout: err?.stdout, fehler: err });
  }
  try {
    await melden({ type: ergebnis.ok ? "info" : "warning", title: "W.A.I.S.", message: ergebnis.meldung, buttons: ["OK"] });
  } catch {
    // Meldung ist nur Rückmeldung, die Reparatur ist schon gelaufen
  }
  return ergebnis.ok ? "repariert" : "fehler";
}

module.exports = { MENUE_TEXT, SKRIPT_NAME, aufruf, auswerten, frageDialog, symbolReparieren };
