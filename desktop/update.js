// WAMO-Desktop: signierte Updates (reines Node-Modul, ohne electron-Import, testbar).
//
// Ablauf (docs/ausrollen-neue-nutzer.md, 4.2): Die Oberfläche holt beim Kern das Manifest (GET /wamo/api/installer) und gibt
// Text und Signatur an die App. Die App vertraut dem Kern dabei nicht: Sie prüft die Ed25519-Signatur über die exakten Bytes
// des Manifests gegen die fest eingebauten öffentlichen Schlüssel (update-schluessel.json), erst danach liest sie das JSON.
// Ein Update gibt es nur bei streng steigender Version, nach einer Rückfrage im Hauptprozess (die Seite kann sie nicht
// fälschen), über eine Verbindung, deren Kette vor dem ersten gesendeten Byte zur WAMO-CA geprüft ist, und nur, wenn Größe
// und SHA-256 der geladenen Datei genau zum signierten Manifest passen. Ohne gültige Signatur lädt die App nichts und fragt
// nichts, die Oberfläche bekommt nur den festen Satz TEXT.nichtBestaetigt.
//
// Manifest (aktuell.json, mit Strang P2 abgestimmt): genau die Schlüssel v, produkt, version, datei, groesse, sha256, bauzeit,
// commit; v = 1, produkt = "wais-desktop", höchstens 4 KB, UTF-8 ohne BOM. Signatur (aktuell.json.sig): eine Zeile Base64 der
// 64 Byte, optional mit LF. Erzeugt beim Bau von scripts/wamo-dist-signieren.cjs.
"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const https = require("node:https");
const path = require("node:path");
const tls = require("node:tls");

const PRODUKT = "wais-desktop";
const MANIFEST_SCHLUESSEL = Object.freeze(["v", "produkt", "version", "datei", "groesse", "sha256", "bauzeit", "commit"]);
const MANIFEST_MAX_BYTES = 4096;
const GROESSE_MAX = 536870912;
const VERSION_RE = /^(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})$/;
const SHA256_RE = /^[0-9a-f]{64}$/;
const BAUZEIT_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z$/;
const COMMIT_RE = /^[0-9a-f]{40}$/;
const SIGNATUR_RE = /^[A-Za-z0-9+/]{86}==\n?$/; // 64 Byte = 88 Zeichen Base64 mit Auffüllung
const SCHLUESSEL_RE = /^[A-Za-z0-9+/]{43}=$/; // 32 Byte
const TOKEN_RE = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;
const TOKEN_MAX = 8192;
const DATEI_PFAD = "/wamo/api/installer/datei";
const INSTALLER_RE = /^WAIS-Setup-\d+\.\d+\.\d+\.exe(\.part)?$/;
const LADE_FRIST_MS = 10 * 60 * 1000; // ganzer Ablauf: Verbinden, Anfrage, Laden, Nachprüfen
const STILL_FRIST_MS = 30 * 1000;
const SPERRE_NACH_ABBRUCH_MS = 10 * 60 * 1000; // nach "Abbrechen" fragt die App so lange nicht erneut

const TEXT = Object.freeze({
  nichtBestaetigt: "Update vom Server nicht bestätigt, bitte Niko fragen.",
  nichtNeuer: "Diese Version ist nicht neuer als die installierte.",
  nurInstalliert: "Updates gibt es nur in der installierten App.",
  anmeldung: "Für das Update fehlt die Anmeldung. Bitte neu anmelden.",
  laeuft: "Ein Update läuft bereits.",
  abgebrochen: "Update abgebrochen.",
  laden: "Der Installer konnte nicht geladen werden. Bitte später erneut versuchen.",
  pruefsumme: "Der geladene Installer passt nicht zum bestätigten Update. Bitte Niko fragen.",
  starten: "Der Installer ließ sich nicht starten. Bitte W.A.I.S. neu starten und es noch einmal versuchen.",
  gesperrt: "Das Update wurde gerade abgebrochen. Die App fragt in einigen Minuten wieder.",
});

class UpdateFehler extends Error {
  constructor(text, grund) {
    super(grund || text);
    this.name = "UpdateFehler";
    this.text = text;
  }
}

/** Öffentliche Ed25519-Schlüssel aus der Liste (Base64 der rohen 32 Byte). Wirft bei leerer oder falscher Liste. */
function schluesselAusListe(liste) {
  if (!Array.isArray(liste) || liste.length === 0 || liste.length > 8) throw new Error("Liste der Update-Schlüssel ungültig");
  return liste.map((b64) => {
    const roh = typeof b64 === "string" && SCHLUESSEL_RE.test(b64) ? Buffer.from(b64, "base64") : null;
    if (!roh || roh.length !== 32 || roh.toString("base64") !== b64) throw new Error("Update-Schlüssel ungültig");
    return crypto.createPublicKey({ key: { kty: "OKP", crv: "Ed25519", x: roh.toString("base64url") }, format: "jwk" });
  });
}

/** -1, 0 oder 1; nur für Versionen, die VERSION_RE erfüllen (numerisch je Teil). */
function vergleicheVersionen(a, b) {
  const x = a.split(".").map(Number);
  const y = b.split(".").map(Number);
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] > y[i] ? 1 : -1;
  return 0;
}

/** Fehlergrund für ein gelesenes Manifest oder null. */
function manifestFehler(m) {
  if (!m || typeof m !== "object" || Array.isArray(m)) return "Manifest ist kein Objekt";
  const schluessel = Object.keys(m).sort();
  if (schluessel.join(",") !== [...MANIFEST_SCHLUESSEL].sort().join(",")) return "Manifest hat andere Schlüssel";
  if (m.v !== 1) return "Manifest-Version unbekannt";
  if (m.produkt !== PRODUKT) return "anderes Produkt";
  if (typeof m.version !== "string" || !VERSION_RE.test(m.version)) return "Version ungültig";
  if (m.datei !== `WAIS-Setup-${m.version}.exe`) return "Dateiname passt nicht zur Version";
  if (!Number.isInteger(m.groesse) || m.groesse < 1 || m.groesse > GROESSE_MAX) return "Größe ungültig";
  if (typeof m.sha256 !== "string" || !SHA256_RE.test(m.sha256)) return "SHA-256 ungültig";
  if (typeof m.bauzeit !== "string" || !BAUZEIT_RE.test(m.bauzeit)) return "Bauzeit ungültig";
  if (typeof m.commit !== "string" || !COMMIT_RE.test(m.commit)) return "Commit ungültig";
  return null;
}

function signaturBytes(signatur) {
  if (typeof signatur !== "string" || !SIGNATUR_RE.test(signatur)) return null;
  const text = signatur.replace(/\n$/, "");
  const roh = Buffer.from(text, "base64");
  return roh.length === 64 && roh.toString("base64") === text ? roh : null;
}

const nein = (grund) => ({ ok: false, grund });

/**
 * Prüft Manifest-Text und Signatur. Erst die Signatur über die exakten Bytes, dann das JSON.
 * Liefert { ok: true, manifest (eingefroren), neuer } oder { ok: false, grund } (grund nur fürs Protokoll).
 */
function pruefeManifest({ manifest, signatur, schluessel, aktuelleVersion }) {
  if (typeof manifest !== "string") return nein("Manifest fehlt");
  const bytes = Buffer.from(manifest, "utf8");
  if (bytes.length === 0 || bytes.length > MANIFEST_MAX_BYTES) return nein("Manifest leer oder zu groß");
  if (manifest.charCodeAt(0) === 0xfeff) return nein("Manifest mit BOM");
  const sig = signaturBytes(signatur);
  if (!sig) return nein("Signatur hat nicht das erwartete Format");
  if (!schluessel.some((k) => crypto.verify(null, bytes, k, sig))) return nein("Signatur passt zu keinem Update-Schlüssel");
  let m;
  try {
    m = JSON.parse(manifest);
  } catch {
    return nein("Manifest ist kein JSON");
  }
  const fehler = manifestFehler(m);
  if (fehler) return nein(fehler);
  if (typeof aktuelleVersion !== "string" || !VERSION_RE.test(aktuelleVersion)) return nein("eigene Version unbekannt");
  return { ok: true, manifest: Object.freeze({ ...m }), neuer: vergleicheVersionen(m.version, aktuelleVersion) > 0 };
}

const tokenGueltig = (t) => typeof t === "string" && t.length <= TOKEN_MAX && TOKEN_RE.test(t);

/**
 * TLS-Verbindung aufbauen und die Kette prüfen (pruefe: zertifikat.pruefeSocket mit der WAMO-CA), BEVOR eine Anfrage und
 * damit das Token darüber geht. Liefert den geprüften Socket.
 */
function verbindeGeprueft(ziel, { pruefe, tlsModul = tls, frist = STILL_FRIST_MS }) {
  return new Promise((resolve, reject) => {
    const host = ziel.hostname.replace(/^\[|\]$/g, "");
    const s = tlsModul.connect({
      host,
      port: Number(ziel.port || 443),
      rejectUnauthorized: false, // die Kette prüft pruefe selbst (Node kann die Namensbeschränkung der WAMO-CA nicht lesen)
      servername: /^[\d.]+$|:/.test(host) ? undefined : host,
      ALPNProtocols: ["http/1.1"],
    });
    s.setTimeout(frist, () => {
      s.destroy();
      reject(new Error("Zeitüberschreitung beim Verbinden"));
    });
    s.once("error", reject);
    s.once("secureConnect", () => {
      let e;
      try {
        e = pruefe(s, host);
      } catch (err) {
        e = { ok: false, grund: err?.message }; // geschlossen scheitern, nie eine Ausnahme im Hauptprozess
      }
      if (e?.ok !== true) {
        s.destroy();
        reject(new Error(`Zertifikat nicht vertraut: ${e?.grund ?? "unbekannt"}`));
        return;
      }
      s.setTimeout(0);
      resolve(s);
    });
  });
}

/** GET über den schon geprüften Socket; liefert die Antwort (IncomingMessage). */
function anfrageUeber(ziel, socket, kopf, httpsModul = https) {
  return new Promise((resolve, reject) => {
    const req = httpsModul.request(ziel, { method: "GET", headers: kopf, createConnection: () => socket }, resolve);
    req.on("error", reject);
    req.end();
  });
}

/** Alte Installer und Reste (WAIS-Setup-*.exe, *.part) im Update-Ordner löschen, sonst nichts. */
function aufraeumen(ordner, dsys) {
  for (const name of dsys.readdirSync(ordner)) {
    if (!INSTALLER_RE.test(name)) continue;
    try {
      dsys.rmSync(path.join(ordner, name), { force: true });
    } catch {
      // eine gesperrte alte Datei hält das Update nicht auf
    }
  }
}

/** Antwort in die Teildatei schreiben und dabei zählen und hashen; prüft am Ende Größe und SHA-256. */
function schreibeGeprueft(res, m, teilDatei, dsys) {
  return new Promise((resolve, reject) => {
    if (res.statusCode !== 200) {
      res.resume?.();
      reject(new UpdateFehler(TEXT.laden, `Status ${res.statusCode}`));
      return;
    }
    const laenge = res.headers?.["content-length"];
    if (laenge !== undefined && Number(laenge) !== m.groesse) {
      res.resume?.();
      reject(new UpdateFehler(TEXT.pruefsumme, "Länge passt nicht zum Manifest"));
      return;
    }
    const hash = crypto.createHash("sha256");
    const aus = dsys.createWriteStream(teilDatei, { flags: "w", mode: 0o600 });
    let bytes = 0;
    let ende = false;
    let geschrieben = false; // erst nach erfolgreichem end() und passender Prüfsumme; erfüllt wird erst nach 'close'
    const scheitern = (fehler) => {
      if (ende) return;
      ende = true;
      res.destroy?.();
      aus.destroy();
      reject(fehler);
    };
    res.on("data", (stueck) => {
      bytes += stueck.length;
      if (bytes > m.groesse) return scheitern(new UpdateFehler(TEXT.pruefsumme, "mehr Bytes als im Manifest"));
      hash.update(stueck);
      if (!aus.write(stueck)) {
        res.pause();
        aus.once("drain", () => res.resume());
      }
    });
    res.on("error", () => scheitern(new UpdateFehler(TEXT.laden, "Antwort abgebrochen")));
    aus.on("error", () => scheitern(new UpdateFehler(TEXT.laden, "Schreiben fehlgeschlagen")));
    aus.on("close", () => {
      if (ende) return;
      if (!geschrieben) return scheitern(new UpdateFehler(TEXT.laden, "Datei vorzeitig geschlossen"));
      ende = true;
      resolve();
    });
    res.on("end", () => {
      if (ende) return;
      aus.end((err) => {
        if (ende) return;
        if (err) return scheitern(new UpdateFehler(TEXT.laden, "Schreiben fehlgeschlagen"));
        if (bytes !== m.groesse || hash.digest("hex") !== m.sha256) {
          return scheitern(new UpdateFehler(TEXT.pruefsumme, "SHA-256 oder Größe passt nicht"));
        }
        geschrieben = true;
      });
    });
  });
}

/** Liest die Datei von der Platte und vergleicht Größe und SHA-256 mit dem Manifest (zählt, nicht der Netzstrom). */
async function pruefeDatei(datei, m, dsys) {
  const hash = crypto.createHash("sha256");
  let bytes = 0;
  for await (const stueck of dsys.createReadStream(datei)) {
    bytes += stueck.length;
    if (bytes > m.groesse) break;
    hash.update(stueck);
  }
  if (bytes !== m.groesse || hash.digest("hex") !== m.sha256) throw new UpdateFehler(TEXT.pruefsumme, "Datei auf der Platte passt nicht");
}

/**
 * Lädt genau die Datei aus dem geprüften Manifest nach ordner. Optionen: manifest (aus pruefeManifest), token, kernUrl,
 * ordner, verbinden(ziel) (geprüfter Socket), anfragen(ziel, socket, kopf), fs, frist. Liefert den Pfad der fertigen Datei;
 * bei jedem Fehler bleibt keine Teildatei liegen.
 */
async function ladeInstaller(opt) {
  const dsys = opt.fs ?? fs;
  const m = opt.manifest;
  const ziel = new URL(DATEI_PFAD, opt.kernUrl);
  if (ziel.protocol !== "https:") throw new UpdateFehler(TEXT.laden, "nur https");
  dsys.mkdirSync(opt.ordner, { recursive: true });
  aufraeumen(opt.ordner, dsys);
  const endDatei = path.join(opt.ordner, m.datei);
  const teilDatei = `${endDatei}.part`;
  let socket = null;
  let res = null;
  let uhr = null;
  // Eine Frist für alles ab dem Verbinden: ein Kern, der nach dem Handshake schweigt, hält das Update nicht fest
  const frist = new Promise((_, reject) => {
    uhr = setTimeout(() => reject(new UpdateFehler(TEXT.laden, "Zeitüberschreitung")), opt.frist ?? LADE_FRIST_MS);
  });
  const ablauf = (async () => {
    socket = await opt.verbinden(ziel).catch((err) => {
      throw new UpdateFehler(TEXT.laden, err?.message);
    });
    const kopf = { Authorization: `Bearer ${opt.token}`, Accept: "application/octet-stream" };
    res = await opt.anfragen(ziel, socket, kopf);
    await schreibeGeprueft(res, m, teilDatei, dsys);
    await pruefeDatei(teilDatei, m, dsys);
  })();
  ablauf.catch(() => {}); // nach einer Zeitüberschreitung endet der Ablauf still
  try {
    await Promise.race([ablauf, frist]);
    dsys.renameSync(teilDatei, endDatei);
    return endDatei;
  } catch (err) {
    res?.destroy?.();
    socket?.destroy?.();
    try {
      dsys.rmSync(teilDatei, { force: true });
    } catch {
      // nichts zu tun
    }
    throw err instanceof UpdateFehler ? err : new UpdateFehler(TEXT.laden, err?.message);
  } finally {
    clearTimeout(uhr);
  }
}

/** Protokollzeile ohne Token und ohne JWT-artige Werte. */
const sauber = (text, token) => {
  let t = String(text ?? "");
  if (typeof token === "string" && token) t = t.split(token).join("***");
  return t.replace(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g, "***").slice(0, 300);
};

/**
 * Der Updater der App. Optionen: schluessel (aus schluesselAusListe), version (app.getVersion()), installiert (nur die
 * installierte App aktualisiert sich), fragen(manifest) -> Promise<boolean> (Rückfrage im Hauptprozess), laden({manifest,
 * token}) -> Promise<Pfad>, starten(pfad) -> Promise, beenden(), log(text).
 */
function erzeugeUpdater(opt) {
  const log = opt.log ?? (() => {});
  const jetzt = opt.jetzt ?? Date.now;
  let laeuft = false;
  let gesperrtBis = 0; // nach "Abbrechen" keine neue Rückfrage, auch wenn die Seite es immer wieder versucht
  const pruefe = (a) => pruefeManifest({ manifest: a?.manifest, signatur: a?.signatur, schluessel: opt.schluessel, aktuelleVersion: opt.version });

  function pruefen(angebot) {
    const e = pruefe(angebot);
    if (!e.ok) {
      log(`Update nicht bestätigt: ${e.grund}`);
      return { ok: false, text: TEXT.nichtBestaetigt };
    }
    return { ok: true, version: e.manifest.version, neuer: e.neuer };
  }

  async function installieren(auftrag) {
    if (!opt.installiert) return { ok: false, text: TEXT.nurInstalliert };
    const e = pruefe(auftrag);
    if (!e.ok) {
      log(`Update nicht bestätigt: ${e.grund}`);
      return { ok: false, text: TEXT.nichtBestaetigt };
    }
    if (!e.neuer) return { ok: false, text: TEXT.nichtNeuer };
    if (!tokenGueltig(auftrag?.token)) return { ok: false, text: TEXT.anmeldung };
    if (laeuft) return { ok: false, text: TEXT.laeuft };
    if (jetzt() < gesperrtBis) return { ok: false, text: TEXT.gesperrt };
    laeuft = true;
    try {
      const ja = await Promise.resolve(opt.fragen(e.manifest)).catch(() => false);
      if (ja !== true) {
        gesperrtBis = jetzt() + SPERRE_NACH_ABBRUCH_MS;
        return { ok: false, abgebrochen: true, text: TEXT.abgebrochen };
      }
      const datei = await opt.laden({ manifest: e.manifest, token: auftrag.token });
      log(`Installer ${e.manifest.version} geladen und geprüft, Start`);
      try {
        await opt.starten(datei);
      } catch (err) {
        throw new UpdateFehler(TEXT.starten, err?.message);
      }
      opt.beenden();
      return { ok: true };
    } catch (err) {
      log(`Update fehlgeschlagen: ${sauber(err?.message, auftrag.token)}`);
      return { ok: false, text: err instanceof UpdateFehler ? err.text : TEXT.laden };
    } finally {
      laeuft = false;
    }
  }

  return { pruefen, installieren };
}

module.exports = {
  SPERRE_NACH_ABBRUCH_MS,
  GROESSE_MAX,
  MANIFEST_MAX_BYTES,
  MANIFEST_SCHLUESSEL,
  PRODUKT,
  TEXT,
  UpdateFehler,
  anfrageUeber,
  erzeugeUpdater,
  ladeInstaller,
  manifestFehler,
  pruefeManifest,
  schluesselAusListe,
  verbindeGeprueft,
  vergleicheVersionen,
};
