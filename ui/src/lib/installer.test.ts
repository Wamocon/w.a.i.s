// Tests für die reine Logik des Installer-Downloads (lib/installer.ts): Manifest des Kerns prüfen, Versionen vergleichen,
// Größe und Prüfsumme anzeigen, Fehler in Sätze übersetzen. Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  appVersion,
  appVersionAus,
  fortschrittText,
  groesseText,
  hashBefehl,
  hexAusBytes,
  installerFehlerText,
  manifestAusAntwort,
  sha256Gleich,
  VERGLEICH_SATZ,
  versionsHinweis,
  versionVergleich,
  type InstallerManifest,
} from "./installer.ts";

const SHA = "0123456789abcdef".repeat(4);
const COMMIT = "89abcdef01".repeat(4);
const ANTWORT = {
  manifest: '{"version":"0.2.0"}',
  signatur: "AAAA" + "b".repeat(84),
  v: 1,
  produkt: "wais-desktop",
  version: "0.2.0",
  datei: "WAIS-Setup-0.2.0.exe",
  groesse: 117_000_000,
  sha256: SHA,
  bauzeit: "2026-11-15T14:00:00Z",
  commit: COMMIT,
};
const GEDANKENSTRICH = /[–—]|\s-\s/;

test("Manifest: gültige Antwort wird übernommen, fremde Felder fallen weg", () => {
  const m = manifestAusAntwort({ ...ANTWORT, pfad: "/var/lib/wamo-verteilung/x" });
  assert.deepEqual(m, ANTWORT);
  assert.ok(m && !("pfad" in m));
  assert.equal(manifestAusAntwort({ ...ANTWORT, signatur: null })?.signatur, null);
  assert.equal(manifestAusAntwort({ ...ANTWORT, version: "0.10.0", datei: "WAIS-Setup-0.10.0.exe" })?.version, "0.10.0");
  assert.equal(manifestAusAntwort({ ...ANTWORT, groesse: 536_870_912 })?.groesse, 536_870_912);
  assert.equal(manifestAusAntwort({ ...ANTWORT, bauzeit: "2026-11-15T14:00:00+00:00" })?.bauzeit, "2026-11-15T14:00:00+00:00");
});

test("Manifest: alles außerhalb der Regeln wird verworfen", () => {
  const falsch: Record<string, unknown>[] = [
    { version: "01.2.3", datei: "WAIS-Setup-01.2.3.exe" },
    { version: "1.2", datei: "WAIS-Setup-1.2.exe" },
    { version: "1.2.3.4", datei: "WAIS-Setup-1.2.3.4.exe" },
    { version: "10000.0.0", datei: "WAIS-Setup-10000.0.0.exe" },
    { version: "v1.2.3", datei: "WAIS-Setup-v1.2.3.exe" },
    { version: "0.2.0 ", datei: "WAIS-Setup-0.2.0 .exe" },
    { datei: "WAIS-Setup-0.2.1.exe" },
    { datei: "..\\WAIS-Setup-0.2.0.exe" },
    { datei: "wais-setup-0.2.0.exe" },
    { groesse: 0 },
    { groesse: -1 },
    { groesse: 1.5 },
    { groesse: 536_870_913 },
    { groesse: "117000000" },
    { sha256: SHA.toUpperCase() },
    { sha256: SHA.slice(1) },
    { sha256: `${SHA.slice(1)}g` },
    { commit: COMMIT.slice(1) },
    { commit: COMMIT.toUpperCase() },
    { v: 2 },
    { v: "1" },
    { produkt: "anderes" },
    { manifest: 5 },
    { manifest: "x".repeat(20_000) },
    { signatur: "kein base64!" },
    { signatur: 12 },
    { bauzeit: "gestern" },
    { bauzeit: 1731679200 },
  ];
  for (const f of falsch) assert.equal(manifestAusAntwort({ ...ANTWORT, ...f }), null, JSON.stringify(f).slice(0, 80));
  for (const feld of Object.keys(ANTWORT).filter((k) => k !== "signatur")) {
    const ohne: Record<string, unknown> = { ...ANTWORT };
    delete ohne[feld];
    assert.equal(manifestAusAntwort(ohne), null, `ohne ${feld}`);
  }
  for (const roh of [null, undefined, "x", 1, [], [ANTWORT]]) assert.equal(manifestAusAntwort(roh), null);
});

test("Versionen numerisch je Teil vergleichen", () => {
  assert.equal(versionVergleich("0.10.0", "0.9.9"), 1);
  assert.equal(versionVergleich("0.9.9", "0.10.0"), -1);
  assert.equal(versionVergleich("1.0.0", "0.99.99"), 1);
  assert.equal(versionVergleich("0.2.0", "0.2.0"), 0);
  assert.equal(versionVergleich("0.2.1", "0.2.0"), 1);
  assert.equal(versionVergleich("0.2", "0.2.0"), null);
  assert.equal(versionVergleich("0.2.0", "x"), null);
});

const M = manifestAusAntwort(ANTWORT) as InstallerManifest;

test("Versionshinweis: im Browser nie, in der App ohne Version Update empfohlen, ältere App mit Zielversion", () => {
  assert.equal(versionsHinweis(null, M, false), null);
  assert.equal(versionsHinweis("0.1.0", M, false), null);
  assert.equal(versionsHinweis(null, M, true), "Update empfohlen.");
  assert.equal(versionsHinweis(null, null, true), "Update empfohlen.");
  assert.equal(versionsHinweis("kaputt", M, true), "Update empfohlen.");
  const neu = manifestAusAntwort({ ...ANTWORT, version: "0.3.0", datei: "WAIS-Setup-0.3.0.exe" });
  assert.equal(versionsHinweis("0.2.0", neu, true), "Update auf Version 0.3.0 verfügbar.");
  assert.equal(versionsHinweis("0.2.0", M, true), null);
  assert.equal(versionsHinweis("0.4.0", neu, true), null);
  assert.equal(versionsHinweis("0.2.0", null, true), null);
});

test("App-Version tolerant lesen: nur ein Text der Form X.Y.Z", () => {
  assert.equal(appVersionAus({ isDesktop: true, version: "0.3.0" }), "0.3.0");
  assert.equal(appVersionAus({ isDesktop: true }), null);
  assert.equal(appVersionAus({ version: 3 }), null);
  assert.equal(appVersionAus({ version: "0.3.0-beta" }), null);
  assert.equal(appVersionAus({ version: () => "0.3.0" }), null);
  assert.equal(appVersionAus(null), null);
  assert.equal(appVersionAus("0.3.0"), null);
  const g = globalThis as { window?: unknown };
  const vorher = g.window;
  try {
    delete g.window;
    assert.equal(appVersion(), null);
    g.window = { wamoDesktop: { isDesktop: true, version: "0.4.1" } };
    assert.equal(appVersion(), "0.4.1");
    g.window = {};
    assert.equal(appVersion(), null);
  } finally {
    if (vorher === undefined) delete g.window;
    else g.window = vorher;
  }
});

test("Größe deutsch, mit Komma", () => {
  assert.equal(groesseText(117_000_000), "112 MB");
  assert.equal(groesseText(536_870_912), "512 MB");
  assert.equal(groesseText(1_572_864), "1,5 MB");
  assert.equal(groesseText(2048), "2 KB");
  assert.equal(groesseText(512), "512 Bytes");
  assert.equal(groesseText(1), "1 Byte");
});

test("Fortschritt als Text", () => {
  assert.equal(fortschrittText(35_651_584, 117_000_000), "34 von 112 MB (30 %)");
  assert.equal(fortschrittText(0, 117_000_000), "0 von 112 MB (0 %)");
  assert.equal(fortschrittText(117_000_000, 117_000_000), "112 von 112 MB (100 %)");
  assert.equal(fortschrittText(35_651_584, null), "34 MB geladen");
});

test("Befehl zum Prüfen der Datei und Vergleichssatz", () => {
  assert.equal(hashBefehl("WAIS-Setup-0.2.0.exe"), "Get-FileHash .\\WAIS-Setup-0.2.0.exe");
  for (const name of ["WAIS-Setup-0.2.0.exe; Remove-Item x", "WAIS-Setup-0.2.0.exe\n", "..\\WAIS-Setup-0.2.0.exe", "setup.exe", ""]) {
    assert.equal(hashBefehl(name), null, JSON.stringify(name));
  }
  assert.equal(VERGLEICH_SATZ, "Vergleiche die Zeichen mit deinem Willkommensblatt.");
});

test("Prüfsummen vergleichen: Groß- und Kleinschreibung egal, nur hex", () => {
  assert.equal(sha256Gleich(SHA, SHA.toUpperCase()), true);
  assert.equal(sha256Gleich(` ${SHA.toUpperCase()}\n`, SHA), true);
  assert.equal(sha256Gleich(SHA, SHA.replace(/.$/, "0")), false);
  assert.equal(sha256Gleich(SHA.slice(1), SHA.slice(1)), false);
  assert.equal(sha256Gleich("z".repeat(64), "z".repeat(64)), false);
  assert.equal(sha256Gleich("", ""), false);
});

test("Bytes als Hex klein", () => {
  assert.equal(hexAusBytes(new Uint8Array([0, 1, 15, 16, 255])), "00010f10ff");
  assert.equal(hexAusBytes(new Uint8Array([171, 205]).buffer), "abcd");
});

test("Fehler als konkrete Sätze", () => {
  assert.match(installerFehlerText(403, "installer_labor"), /Laborprofile/);
  assert.match(installerFehlerText(403, null), /nicht frei/);
  assert.match(installerFehlerText(429, "installer_zu_oft"), /dreimal/);
  assert.match(installerFehlerText(503, "installer_fehlt"), /kein Installer bereit/);
  assert.match(installerFehlerText(401, null), /Anmeldung ist abgelaufen/);
  assert.match(installerFehlerText(0, null, "Zeitüberschreitung"), /Zeitüberschreitung/);
  assert.match(installerFehlerText(0, null, "Abgebrochen"), /abgebrochen/);
  assert.match(installerFehlerText(0, null, "Kern nicht erreichbar"), /nicht erreichbar/);
  assert.match(installerFehlerText(413, null), /größer als angekündigt/);
  assert.match(installerFehlerText(500, null), /Problem/);
  assert.match(installerFehlerText(400, null), /\(400\)/);
  for (const [s, c, t] of [
    [403, "installer_labor"],
    [403, null],
    [429, null],
    [503, null],
    [401, null],
    [0, null, "Zeitüberschreitung"],
    [0, null, "Abgebrochen"],
    [0, null, ""],
    [413, null],
    [500, null],
    [400, null],
  ] as [number, string | null, string?][]) {
    const text = installerFehlerText(s, c, t);
    assert.ok(!GEDANKENSTRICH.test(text), text);
    assert.ok(text.endsWith("."), text);
  }
});
