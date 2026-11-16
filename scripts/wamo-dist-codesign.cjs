// Prüft die Codesignatur (Authenticode) des gebauten Installers und der App (Entscheidung N8, docs/ausrollen-neue-nutzer.md).
//
// Signiert wird beim Bau von electron-builder selbst, sobald ein Zertifikat in der Umgebung des Baus steht (nie im Repo):
//   OV- oder EV-Zertifikat als Datei:  CSC_LINK=<Pfad zur .pfx>  CSC_KEY_PASSWORD=<Passwort>
//   EV auf Token oder Signaturdienst:  siehe README, Abschnitt "Codesignatur"
// "npm run dist" signiert dann von selbst und baut ohne Zertifikat wie bisher unsigniert. "npm run dist:signiert" verlangt die
// Signatur (forceCodeSigning) und bricht ohne Zertifikat ab. Dieses Skript prüft danach, was wirklich signiert ist.
//
// Aufruf:  node scripts/wamo-dist-codesign.cjs <Ordner dist> [--pflicht] [--herausgeber "WAMOCON GmbH"] [--fingerabdruck <SHA1>]
//   --fingerabdruck: nur genau dieses Zertifikat zählt (Thumbprint), nicht jedes gültige mit passendem Namen
//   ohne --pflicht: Bericht, Exit 0 auch ohne Signatur (Hinweis: Ausgabe nur an die sieben Pilotkollegen)
//   mit --pflicht:  Exit 1, wenn eine Datei nicht gültig signiert ist oder der Herausgeber nicht passt
// Nur Windows (Get-AuthenticodeSignature). Keine Netzanfrage außer der Prüfung der Zertifikatskette durch Windows.
"use strict";

const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const STANDARD_HERAUSGEBER = "WAMOCON GmbH";

/** Die Dateien, die signiert sein müssen: Installer und App (uv.exe bringt seine eigene Signatur mit oder keine). */
function zuPruefen(distOrdner, version) {
  return [path.join(distOrdner, `WAIS-Setup-${version}.exe`), path.join(distOrdner, "win-unpacked", "WAMO.exe")];
}

/** Liest die Signatur einer Datei über PowerShell; liefert { datei, status, herausgeber }. */
function leseSignatur(datei) {
  const skript =
    "$s = Get-AuthenticodeSignature -LiteralPath $env:WAIS_CODESIGN_DATEI; " +
    "[pscustomobject]@{ status = [string]$s.Status; herausgeber = [string]$s.SignerCertificate.Subject; " +
    "fingerabdruck = [string]$s.SignerCertificate.Thumbprint } | ConvertTo-Json -Compress";
  const powershell = path.join(process.env.SystemRoot || "C:\\Windows", "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
  // Nur die nötige Umgebung: nie CSC_LINK, CSC_KEY_PASSWORD oder andere Zugangswerte an den Kindprozess
  const env = { SystemRoot: process.env.SystemRoot, PATH: process.env.PATH, TEMP: process.env.TEMP, WAIS_CODESIGN_DATEI: datei };
  const aus = execFileSync(powershell, ["-NoProfile", "-NonInteractive", "-Command", skript], { encoding: "utf8", env, timeout: 60_000 });
  const j = JSON.parse(aus);
  return { datei, status: String(j.status ?? ""), herausgeber: String(j.herausgeber ?? ""), fingerabdruck: String(j.fingerabdruck ?? "") };
}

/** Bewertet die Ergebnisse; reine Funktion (testbar). Liefert { ok, zeilen }. */
function bewerte(ergebnisse, { pflicht = false, herausgeber = STANDARD_HERAUSGEBER, fingerabdruck = "" } = {}) {
  const zeilen = [];
  let alleGut = ergebnisse.length > 0 && typeof herausgeber === "string" && herausgeber.trim() !== "";
  for (const e of ergebnisse) {
    const name = path.basename(e.datei);
    const gueltig = e.status === "Valid" && (!fingerabdruck || String(e.fingerabdruck).toUpperCase() === fingerabdruck.toUpperCase());
    const passt = gueltig && herausgeber.trim() !== "" && new RegExp(`(^|,\\s*)(O|CN)=("?)${herausgeber.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\3(,|$)`).test(e.herausgeber);
    if (!gueltig) zeilen.push(`${name}: nicht signiert oder ungültig (${e.status || "unbekannt"})`);
    else if (!passt) zeilen.push(`${name}: signiert, aber nicht von ${herausgeber}`);
    else zeilen.push(`${name}: gültig signiert von ${herausgeber}`);
    alleGut &&= passt;
  }
  if (!alleGut && !pflicht) zeilen.push("Hinweis: ohne gültige Codesignatur nur an die sieben Pilotkollegen ausgeben (Entscheidung N8).");
  return { ok: alleGut || !pflicht, alleGut, zeilen };
}

function hauptprogramm(args) {
  const ordner = path.resolve(args.find((a) => !a.startsWith("--")) ?? "dist");
  const i = args.indexOf("--herausgeber");
  const herausgeber = i >= 0 ? args[i + 1] : STANDARD_HERAUSGEBER;
  const f = args.indexOf("--fingerabdruck");
  const fingerabdruck = f >= 0 ? args[f + 1] : "";
  const version = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "desktop", "package.json"), "utf8")).version;
  const dateien = zuPruefen(ordner, version);
  for (const d of dateien) if (!fs.existsSync(d)) throw new Error(`${d} fehlt. Erst bauen (npm run dist).`);
  const ergebnis = bewerte(dateien.map(leseSignatur), { pflicht: args.includes("--pflicht"), herausgeber, fingerabdruck });
  for (const z of ergebnis.zeilen) console.log(z);
  return ergebnis.ok ? 0 : 1;
}

if (require.main === module) {
  try {
    process.exit(hauptprogramm(process.argv.slice(2)));
  } catch (err) {
    console.error(`Fehler: ${err.message}`);
    process.exit(1);
  }
}

module.exports = { STANDARD_HERAUSGEBER, bewerte, leseSignatur, zuPruefen };
