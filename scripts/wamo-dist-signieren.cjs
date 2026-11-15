// Signiert das Manifest des gebauten Installers (docs/ausrollen-neue-nutzer.md, 4.2 und Paket P3).
//
// Aus dist\WAIS-Setup-<Version>.exe entstehen daneben aktuell.json (Version, Dateiname, Größe, SHA-256, Bauzeit, Commit) und
// aktuell.json.sig (Ed25519 über die exakten Bytes von aktuell.json, eine Zeile Base64). Die App prüft beides gegen die fest
// eingebauten öffentlichen Schlüssel in desktop/update-schluessel.json (desktop/update.js); das Skript signiert nur, wenn die
// Signatur dort passt, und prüft danach mit genau derselben Funktion wie die App.
//
// Befehle (im Ordner desktop/ oder aus der Repo-Wurzel):
//   node scripts/wamo-dist-signieren.cjs signieren <exe> --schluessel <datei>      Übergang: Schlüsseldatei nur bei Niko
//   node scripts/wamo-dist-signieren.cjs signieren <exe> --pkcs11-modul <dll> --pkcs11-id <hex> [--pkcs11-tool <exe>]
//                                                                                  Ziel: Hardware-Token (PIN am Token)
//   node scripts/wamo-dist-signieren.cjs pruefen <exe>                              Manifest, Signatur und Datei prüfen
//   node scripts/wamo-dist-signieren.cjs schluessel-erzeugen <datei>                neuer Übergangsschlüssel (nie im Repo)
//   node scripts/wamo-dist-signieren.cjs schluessel-schuetzen <datei>               Schlüsseldatei mit Passwort verschlüsseln
// Ein verschlüsselter Schlüssel liest sein Passwort aus WAIS_SIGNATUR_PASSWORT (nur in der Sitzung setzen, nie speichern).
// Der private Schlüssel wird nie ausgegeben, nie ins Repo geschrieben und nie in eine Datei innerhalb eines Git-Arbeitsbaums.
"use strict";

const crypto = require("node:crypto");
const { execFileSync, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const REPO = path.resolve(__dirname, "..");
const DESKTOP = path.join(REPO, "desktop");
const { pruefeManifest, schluesselAusListe } = require(path.join(DESKTOP, "update.js"));

const EXE_RE = /^WAIS-Setup-(\d+\.\d+\.\d+)\.exe$/;
const PASSWORT_ENV = "WAIS_SIGNATUR_PASSWORT";

function fehler(text) {
  const e = new Error(text);
  e.signierFehler = true;
  return e;
}

/** Liegt der Pfad in einem Git-Arbeitsbaum (irgendein Elternordner mit .git)? Dann nie einen privaten Schlüssel dorthin. */
function imGitBaum(pfad, existiert = fs.existsSync) {
  let ordner = path.resolve(path.dirname(pfad));
  for (;;) {
    if (existiert(path.join(ordner, ".git"))) return true;
    const oben = path.dirname(ordner);
    if (oben === ordner) return false;
    ordner = oben;
  }
}

/** Manifest-Text in fester Reihenfolge, ohne Zeilenende (die Bytes werden signiert). */
function manifestText({ version, groesse, sha256, bauzeit, commit }) {
  return JSON.stringify({ v: 1, produkt: "wais-desktop", version, datei: `WAIS-Setup-${version}.exe`, groesse, sha256, bauzeit, commit });
}

function sha256Datei(datei) {
  const hash = crypto.createHash("sha256");
  const fd = fs.openSync(datei, "r");
  try {
    const puffer = Buffer.alloc(1024 * 1024);
    let n;
    while ((n = fs.readSync(fd, puffer, 0, puffer.length, null)) > 0) hash.update(puffer.subarray(0, n));
  } finally {
    fs.closeSync(fd);
  }
  return hash.digest("hex");
}

const git = (...args) => execFileSync("git", ["-C", REPO, ...args], { encoding: "utf8" }).trim();

function appSchluessel() {
  return schluesselAusListe(JSON.parse(fs.readFileSync(path.join(DESKTOP, "update-schluessel.json"), "utf8")));
}

/** Prüft Name und Version der EXE gegen desktop/package.json und liefert die Angaben fürs Manifest. */
function angabenFuer(exe, { commit, bauzeit = new Date().toISOString(), paketVersion }) {
  const name = path.basename(exe);
  const treffer = EXE_RE.exec(name);
  if (!treffer) throw fehler(`Dateiname ${name} passt nicht zu WAIS-Setup-<Version>.exe.`);
  if (treffer[1] !== paketVersion) throw fehler(`Version ${treffer[1]} passt nicht zu desktop/package.json (${paketVersion}).`);
  const groesse = fs.statSync(exe).size;
  return { version: treffer[1], groesse, sha256: sha256Datei(exe), bauzeit, commit };
}

function privatSchluessel(datei) {
  const pem = fs.readFileSync(datei, "utf8");
  const passwort = process.env[PASSWORT_ENV];
  try {
    const k = crypto.createPrivateKey(pem.includes("ENCRYPTED") ? { key: pem, passphrase: passwort ?? "" } : { key: pem });
    if (k.asymmetricKeyType !== "ed25519") throw fehler("Die Schlüsseldatei enthält keinen Ed25519-Schlüssel.");
    return k;
  } catch (err) {
    if (err.signierFehler) throw err;
    throw fehler(`Schlüsseldatei nicht lesbar (verschlüsselt? Dann ${PASSWORT_ENV} in dieser Sitzung setzen).`);
  }
}

/** Signatur mit dem Hardware-Token über pkcs11-tool (OpenSC); die PIN fragt das Werkzeug selbst ab. */
function signiereMitToken(bytes, { modul, id, werkzeug = "pkcs11-tool" }) {
  if (!/^[0-9a-fA-F]{2,40}$/.test(id ?? "")) throw fehler("--pkcs11-id muss eine Hex-Kennung sein (zum Beispiel 02).");
  if (!modul || !fs.existsSync(modul)) throw fehler("--pkcs11-modul fehlt oder existiert nicht.");
  const ordner = fs.mkdtempSync(path.join(os.tmpdir(), "wais-sign-"));
  const ein = path.join(ordner, "manifest.bin");
  const aus = path.join(ordner, "signatur.bin");
  try {
    fs.writeFileSync(ein, bytes);
    const args = ["--module", modul, "--login", "--sign", "--mechanism", "EDDSA", "--id", id, "--input-file", ein, "--output-file", aus];
    const lauf = spawnSync(werkzeug, args, { stdio: "inherit" });
    if (lauf.status !== 0) throw fehler("pkcs11-tool hat nicht signiert (PIN, Token oder Kennung prüfen).");
    const sig = fs.readFileSync(aus);
    if (sig.length !== 64) throw fehler(`Das Token lieferte ${sig.length} statt 64 Byte (Mechanismus EDDSA mit Ed25519 nötig).`);
    return sig;
  } finally {
    fs.rmSync(ordner, { recursive: true, force: true });
  }
}

/** Prüft aktuell.json und aktuell.json.sig neben der EXE wie die App und vergleicht Größe und SHA-256 der Datei. */
function pruefeAusgabe(exe, schluessel = appSchluessel()) {
  const ordner = path.dirname(exe);
  const manifest = fs.readFileSync(path.join(ordner, "aktuell.json"), "utf8");
  const signatur = fs.readFileSync(path.join(ordner, "aktuell.json.sig"), "utf8");
  const e = pruefeManifest({ manifest, signatur, schluessel, aktuelleVersion: "0.0.0" });
  if (!e.ok) throw fehler(`Prüfung wie in der App fehlgeschlagen: ${e.grund}.`);
  if (e.manifest.datei !== path.basename(exe)) throw fehler("Dateiname im Manifest passt nicht.");
  if (fs.statSync(exe).size !== e.manifest.groesse || sha256Datei(exe) !== e.manifest.sha256) throw fehler("Größe oder SHA-256 der Datei passt nicht.");
  return e.manifest;
}

/** Schreibt Manifest und Signatur neben die EXE und prüft sie danach wie die App. */
function signieren(exe, opt, schluessel = appSchluessel()) {
  const text = manifestText(angabenFuer(exe, opt));
  const bytes = Buffer.from(text, "utf8");
  const sig = opt.schluesselDatei ? crypto.sign(null, bytes, privatSchluessel(opt.schluesselDatei)) : signiereMitToken(bytes, opt.token);
  if (!schluessel.some((k) => crypto.verify(null, bytes, k, sig))) {
    throw fehler("Die Signatur passt zu keinem Schlüssel in desktop/update-schluessel.json. Nichts geschrieben.");
  }
  const ordner = path.dirname(exe);
  fs.writeFileSync(path.join(ordner, "aktuell.json"), bytes);
  fs.writeFileSync(path.join(ordner, "aktuell.json.sig"), `${sig.toString("base64")}\n`, "ascii");
  return pruefeAusgabe(exe, schluessel);
}

/** Nur Besitzer: Vererbung weg, nur der angemeldete Benutzer mit Vollzugriff (Windows). */
function nurBesitzer(datei) {
  if (process.platform !== "win32") {
    fs.chmodSync(datei, 0o600);
    return;
  }
  execFileSync("icacls", [datei, "/inheritance:r", "/grant:r", `${os.userInfo().username}:F`], { stdio: "ignore" });
}

const rohOeffentlich = (k) => Buffer.from(crypto.createPublicKey(k).export({ format: "jwk" }).x, "base64url").toString("base64");

function schluesselErzeugen(datei) {
  const ziel = path.resolve(datei);
  if (imGitBaum(ziel)) throw fehler("Die Schlüsseldatei darf nie in einem Git-Arbeitsbaum liegen.");
  if (fs.existsSync(ziel)) throw fehler("Die Datei gibt es schon; ein Schlüssel wird nie überschrieben.");
  const { privateKey } = crypto.generateKeyPairSync("ed25519");
  const passwort = process.env[PASSWORT_ENV];
  const pem = passwort
    ? privateKey.export({ type: "pkcs8", format: "pem", cipher: "aes-256-cbc", passphrase: passwort })
    : privateKey.export({ type: "pkcs8", format: "pem" });
  fs.mkdirSync(path.dirname(ziel), { recursive: true });
  fs.writeFileSync(ziel, pem, { flag: "wx", mode: 0o600 });
  nurBesitzer(ziel);
  return rohOeffentlich(privateKey);
}

function schluesselSchuetzen(datei) {
  const passwort = process.env[PASSWORT_ENV];
  if (!passwort || passwort.length < 12) throw fehler(`${PASSWORT_ENV} fehlt oder ist kürzer als 12 Zeichen.`);
  const ziel = path.resolve(datei);
  const pem = fs.readFileSync(ziel, "utf8");
  if (pem.includes("ENCRYPTED")) throw fehler("Die Schlüsseldatei ist schon verschlüsselt.");
  const k = crypto.createPrivateKey(pem);
  const neu = `${ziel}.neu`;
  fs.writeFileSync(neu, k.export({ type: "pkcs8", format: "pem", cipher: "aes-256-cbc", passphrase: passwort }), { flag: "wx", mode: 0o600 });
  nurBesitzer(neu);
  fs.renameSync(neu, ziel);
  return rohOeffentlich(k);
}

function wert(args, name) {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : undefined;
}

function hauptprogramm(args) {
  const [befehl, ziel] = args;
  if (befehl === "schluessel-erzeugen" && ziel) {
    console.log(`Öffentlicher Schlüssel (für desktop/update-schluessel.json): ${schluesselErzeugen(ziel)}`);
    return;
  }
  if (befehl === "schluessel-schuetzen" && ziel) {
    console.log(`Verschlüsselt. Öffentlicher Schlüssel unverändert: ${schluesselSchuetzen(ziel)}`);
    return;
  }
  if (befehl === "pruefen" && ziel) {
    const m = pruefeAusgabe(path.resolve(ziel));
    console.log(`In Ordnung: ${m.datei}, ${m.groesse} Byte, SHA-256 ${m.sha256}, Commit ${m.commit}`);
    return;
  }
  if (befehl === "signieren" && ziel) {
    if (git("status", "--porcelain", "--untracked-files=no") !== "") throw fehler("Der Arbeitsbaum ist nicht sauber; signiert wird nur ein committeter Stand.");
    const paketVersion = JSON.parse(fs.readFileSync(path.join(DESKTOP, "package.json"), "utf8")).version;
    const schluesselDatei = wert(args, "--schluessel");
    const token = { modul: wert(args, "--pkcs11-modul"), id: wert(args, "--pkcs11-id"), werkzeug: wert(args, "--pkcs11-tool") };
    if (!schluesselDatei && !token.modul) throw fehler("--schluessel <datei> oder --pkcs11-modul <dll> angeben.");
    const m = signieren(path.resolve(ziel), { commit: git("rev-parse", "HEAD"), paketVersion, schluesselDatei, token });
    console.log(`Signiert: ${m.datei}, ${m.groesse} Byte, SHA-256 ${m.sha256}, Commit ${m.commit}`);
    return;
  }
  throw fehler("Aufruf: signieren <exe> (--schluessel <datei> | --pkcs11-modul <dll> --pkcs11-id <hex>) | pruefen <exe> | schluessel-erzeugen <datei> | schluessel-schuetzen <datei>");
}

if (require.main === module) {
  try {
    hauptprogramm(process.argv.slice(2));
  } catch (err) {
    console.error(err.signierFehler ? err.message : `Fehler: ${err.message}`);
    process.exit(1);
  }
}

module.exports = { angabenFuer, imGitBaum, manifestText, pruefeAusgabe, schluesselErzeugen, signieren, signiereMitToken };
