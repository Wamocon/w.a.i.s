// Tests für die Hilfsskripte des Installer-Baus (scripts/wamo-dist-vorbereiten.cjs, scripts/wamo-dist-pruefen.cjs) und die
// Bau-Konfiguration in package.json. Ausführen im Ordner desktop/:  npm test
"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");
const { ladePin, sha256Datei } = require("../scripts/wamo-dist-vorbereiten.cjs");
const { pruefePfade, pruefeText } = require("../scripts/wamo-dist-pruefen.cjs");

const paket = JSON.parse(fs.readFileSync(path.join(__dirname, "package.json"), "utf8"));
const pinDatei = path.join(__dirname, "build", "uv-pin.json");

test("Die echte uv-Festlegung ist gültig und die Lizenz liegt daneben", () => {
  const pin = ladePin(pinDatei);
  assert.equal(pin.version, "0.13.1");
  assert.match(pin.sha256, /^[0-9a-f]{64}$/);
  assert.ok(fs.existsSync(path.join(__dirname, "build", "uv-LICENSE-MIT.txt")));
});

test("uv-Festlegung: fremde Adresse, falsche Prüfsumme oder Version werden abgelehnt", () => {
  const ordner = fs.mkdtempSync(path.join(os.tmpdir(), "wamo-pin-"));
  try {
    const basis = JSON.parse(fs.readFileSync(pinDatei, "utf8"));
    const pruefe = (aenderung) => {
      const d = path.join(ordner, "pin.json");
      fs.writeFileSync(d, JSON.stringify({ ...basis, ...aenderung }));
      return ladePin(d);
    };
    assert.ok(pruefe({}));
    assert.throws(() => pruefe({ url: "http://github.com/astral-sh/uv/releases/download/0.13.1/uv-x86_64-pc-windows-msvc.zip" }), /Adresse/);
    assert.throws(() => pruefe({ url: "https://evil.example/astral-sh/uv/releases/download/0.13.1/uv-x86_64-pc-windows-msvc.zip" }), /Adresse/);
    assert.throws(() => pruefe({ url: "https://github.com/astral-sh/uv/releases/download/0.12.0/uv-x86_64-pc-windows-msvc.zip" }), /passt nicht/);
    assert.throws(() => pruefe({ sha256: "abc" }), /sha256/);
    assert.throws(() => pruefe({ sha256: basis.sha256.toUpperCase() }), /sha256/);
    assert.throws(() => pruefe({ version: "latest" }), /Version/);
    assert.throws(() => pruefe({ datei: "..\\uv.zip" }), /Adresse|Dateiname/);
  } finally {
    fs.rmSync(ordner, { recursive: true, force: true });
  }
});

test("sha256Datei", () => {
  const ordner = fs.mkdtempSync(path.join(os.tmpdir(), "wamo-sha-"));
  try {
    const d = path.join(ordner, "x.bin");
    fs.writeFileSync(d, "abc");
    assert.equal(sha256Datei(d), crypto.createHash("sha256").update("abc").digest("hex"));
  } finally {
    fs.rmSync(ordner, { recursive: true, force: true });
  }
});

test("Pfadprüfung: Tests, .env, Schlüssel, Umgebungen und Quellordner sind verboten, der Host-Code nicht", () => {
  const schlecht = [
    "host/test_security.py",
    "host/conftest.py",
    "host/.venv/Scripts/python.exe",
    "host/__pycache__/x.pyc",
    ".env",
    "host/.env.local",
    "geraet.test.js",
    "berechtigungen.probe.js",
    "testdaten/ca.crt",
    "id_rsa.key",
    "host/wamo_audit.jsonl",
    "logs/oberflaeche.log",
    "voice-core/bot.py",
    "ui/src/app/page.tsx",
    "node_modules/x/index.js",
  ];
  for (const p of schlecht) assert.equal(pruefePfade([p]).length > 0, true, p);
  const gut = ["host/wamo_host.py", "host/uv.lock", "scripts/wamo-tunnel.ps1", "uv/uv.exe", "wamo-ca.crt", "main.js", "assets/wamo.ico", "overlay.html"];
  assert.deepEqual(pruefePfade(gut), []);
});

test("Textprüfung: Geheimnisse und verbotene Wörter werden gefunden, der Formatkopf allein nicht", () => {
  assert.equal(pruefeText("-----BEGIN OPENSSH PRIVATE KEY-----\n${zeilen}\n-----END", []).length, 0);
  assert.equal(pruefeText(`-----BEGIN PRIVATE KEY-----\n${"A".repeat(64)}\n`).length, 1);
  assert.equal(pruefeText("key = sk-ant-api03-abcdefghijklmnopqrstuvwxyz").length, 1);
  assert.equal(pruefeText("SONIOX_API_KEY=abcdef123456").length, 1);
  assert.equal(pruefeText("SONIOX_API_KEY=\n").length, 0);
  assert.equal(pruefeText("postgresql://wamo_core:geheimespasswort@host/db").length, 1);
  assert.equal(pruefeText("Das ist ein Wort Fremdprojekt hier", ["fremdprojekt"]).length, 1);
  assert.equal(pruefeText("harmlos", ["fremdprojekt"]).length, 0);
});

test("Bau-Konfiguration: Kennung, pro Benutzer ohne Admin, Fuses, Host ohne Tests, kein Updater", () => {
  const b = paket.build;
  assert.equal(b.appId, "de.wamocon.wamo");
  assert.equal(b.win.requestedExecutionLevel, "asInvoker");
  assert.equal(b.nsis.perMachine, false);
  assert.equal(b.nsis.allowElevation, false);
  assert.equal(b.publish, null, "kein automatischer Updater");
  assert.equal(b.win.icon, "assets/wamo.ico");
  assert.ok(fs.existsSync(path.join(__dirname, b.win.icon)));
  assert.equal(b.electronFuses.runAsNode, false);
  assert.equal(b.electronFuses.enableCookieEncryption, true);
  assert.equal(b.electronFuses.enableNodeOptionsEnvironmentVariable, false);
  assert.equal(b.electronFuses.enableNodeCliInspectArguments, false);
  assert.equal(b.electronFuses.enableEmbeddedAsarIntegrityValidation, true);
  assert.equal(b.electronFuses.onlyLoadAppFromAsar, true);
  // start.html, overlay.html und livebild-hinweis.html kommen per file:// aus der asar; mit false scheitern alle drei (ERR_FILE_NOT_FOUND, am gebauten Programm und im Versuch mit Electron 44.10.1 gemessen)
  assert.equal(b.electronFuses.grantFileProtocolExtraPrivileges, true);
  const host = b.extraResources.find((e) => e.to === "host");
  assert.ok(host.filter.includes("!**/test_*.py") && host.filter.includes("!.venv/**") && host.filter.includes("uv.lock"));
  const skripte = b.extraResources.find((e) => e.to === "scripts");
  assert.deepEqual([...skripte.filter].sort(), [
    "wamo-symbol-reparieren.ps1",
    "wamo-tunnel-einrichten.ps1",
    "wamo-tunnel-entfernen.ps1",
    "wamo-tunnel.ps1",
  ]);
  assert.ok(b.files.includes("!**/*.test.js") && b.files.includes("!testdaten/**"));
});

// Namen der Installation. Sichtbar heißt die App W.A.I.S.: Startmenü (shortcutName), Liste "Apps" (uninstallDisplayName), Dateibeschreibung
// und Produktname der EXE (electron-builder schreibt productName in FileDescription und ProductName) und Beschreibung des Installers
// (description). Technisch bleibt alles wie in 0.1.0, damit der neue Installer eine vorhandene Installation ersetzt, ohne Daten,
// Anmeldung oder Autostart zu verlieren:
//   * appId und nsis.guid: derselbe Eintrag in der Registrierung, der alte Stand wird deinstalliert, kein zweiter Eintrag in "Apps".
//   * Programmordner: Bei oneClick pro Benutzer nimmt electron-builder den Paketnamen (%LOCALAPPDATA%\Programs\wamo-desktop, Funktion
//     getWindowsInstallationDirName), beim Update den gespeicherten InstallLocation. productName ändert ihn nicht.
//   * executableName WAMO: Der Autostart-Eintrag (HKCU\...\Run, Name de.wamocon.wamo) zeigt auf ...\wamo-desktop\WAMO.exe, der Host
//     erkennt die eigene Oberfläche an wamo.exe, und der Installer findet die laufende App über diesen Dateinamen.
test("Das Logo für die Office-Dateien kommt mit dem Host ins Paket, sonst nichts Neues aus vorlagen/", () => {
  // host/office_dateien.py braucht vorlagen/wmc-logo.png für Kopfzeile und Folien; fehlt es, erzeugt der Host keine Datei
  const host = paket.build.extraResources.find((e) => e.to === "host");
  assert.ok(host.filter.includes("vorlagen/*.png"), "vorlagen/*.png fehlt im Filter des Hosts");
  assert.ok(!host.filter.some((f) => /vorlagen\/\*\*|vorlagen\/\*\.(?!png)/.test(f)), "nur PNG aus vorlagen/");
  const vorlagen = fs.readdirSync(path.join(__dirname, "..", "host", "vorlagen"));
  assert.deepEqual(vorlagen, ["wmc-logo.png"]);
  const logo = fs.readFileSync(path.join(__dirname, "..", "host", "vorlagen", "wmc-logo.png"));
  assert.equal(logo.subarray(1, 4).toString("ascii"), "PNG");
  assert.deepEqual(pruefePfade(["host/vorlagen/wmc-logo.png"]), []);
});

test("Namen der Installation: sichtbar W.A.I.S., technisch wie in 0.1.0", () => {
  const b = paket.build;
  assert.equal(b.productName, "W.A.I.S.");
  assert.equal(b.nsis.shortcutName, "W.A.I.S.");
  assert.equal(b.nsis.uninstallDisplayName, "W.A.I.S.");
  assert.match(paket.description, /^W\.A\.I\.S\. /);
  assert.doesNotMatch(paket.description, /WAMO/);
  assert.equal(b.artifactName, "WAIS-Setup-${version}.${ext}");
  assert.equal(b.executableName, "WAMO");
  assert.equal(paket.name, "wamo-desktop");
  assert.equal(b.nsis.guid, "c59011d4-a64c-41af-9964-07f5c67d84f4");
  assert.equal(b.nsis.oneClick, true);
  assert.equal(b.nsis.deleteAppDataOnUninstall, false);
});

test("Datei- und Ordnernamen der Installation enden nie mit Punkt oder Leerzeichen (Windows schneidet beides ab)", () => {
  const b = paket.build;
  const setup = b.artifactName.replace("${version}", paket.version).replace("${ext}", "exe");
  const namen = [paket.name, `${b.executableName}.exe`, `Uninstall ${b.executableName}.exe`, setup, `${b.nsis.shortcutName}.lnk`];
  for (const name of namen) {
    assert.doesNotMatch(name, /[. ]$/, name);
    assert.doesNotMatch(name, /[<>:"/\\|?*]/, name);
  }
  assert.equal(setup, `WAIS-Setup-${paket.version}.exe`);
});

test("Die EXE heißt so, wie der Host die eigene Oberfläche erkennt (WAMO_UI_EXES in host/windows_control.py)", () => {
  const quelle = fs.readFileSync(path.join(__dirname, "..", "host", "windows_control.py"), "utf8");
  const zeile = quelle.match(/^WAMO_UI_EXES = \{([^}]*)\}/m);
  assert.ok(zeile, "WAMO_UI_EXES nicht gefunden");
  const exes = [...zeile[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  assert.ok(exes.includes(`${paket.build.executableName.toLowerCase()}.exe`), exes.join(", "));
});

test("Die installierte App behält Daten und Autostart unabhängig vom Anzeigenamen", () => {
  const main = fs.readFileSync(path.join(__dirname, "main.js"), "utf8");
  // userData fest auf %APPDATA%\WAMO (Einstellungen, Sitzung, Cookies, Logs), vor der Einzelinstanz-Sperre, die dort liegt
  const userData = 'if (app.isPackaged) app.setPath("userData", path.join(app.getPath("appData"), "WAMO"));';
  assert.ok(main.includes(userData));
  assert.ok(main.indexOf(userData) < main.indexOf("app.requestSingleInstanceLock()"));
  // Autostart und Verknüpfung hängen an der AppUserModelId: Sie ist die appId (der Installer setzt sie an der Verknüpfung)
  assert.ok(main.includes(`app.setAppUserModelId("${paket.build.appId}")`));
  // Daten des Geräts bleiben unter %LOCALAPPDATA%\WAMO
  assert.match(main, /const datenOrdnerWamo = path\.join\([^\n]*"WAMO"\);/);
});

test("Versionen: electron und electron-builder sind exakt gepinnt", () => {
  for (const [name, version] of Object.entries(paket.devDependencies)) assert.match(version, /^\d+\.\d+\.\d+$/, name);
});

test("Der Paketname des Skripts und die Gerätedatei zeigen auf vorhandene Skripte im Repository", () => {
  for (const s of ["wamo-tunnel.ps1", "wamo-tunnel-einrichten.ps1", "wamo-tunnel-entfernen.ps1", "wamo-symbol-reparieren.ps1"]) {
    assert.ok(fs.existsSync(path.join(__dirname, "..", "scripts", s)), s);
  }
});

test("Der Installer gibt ALLE ANWENDUNGSPAKETE Lesezugriff auf den Installationsordner (sonst startet Electron nicht)", () => {
  const nsh = fs.readFileSync(path.join(__dirname, "build", "installer.nsh"), "utf8");
  assert.match(nsh, /!macro customInstall/);
  assert.match(nsh, /icacls\.exe" "\$INSTDIR" \/grant \*S-1-15-2-1:\(OI\)\(CI\)\(RX\)/);
  assert.doesNotMatch(nsh, /\/grant[^\n]*(F|M|W)\)/, "nur Lesen und Ausführen");
});

// Symbol nach einem Update: Beim Update behält electron-builder die Verknüpfung im Startmenü (--keep-shortcuts) und tauscht nur
// die EXE. In der Nachstellung vom 14.11.2026 las Windows den Eintrag der Kennung im App-Zwischenspeicher der Shell
// (%LOCALAPPDATA%\Microsoft\Windows\Caches) dann nicht neu, nur bei einer umbenannten Verknüpfung. Deshalb schreibt der Installer
// die Verknüpfung neu (WinShell::SetLnkAUMI), meldet Verknüpfung und EXE als geändert und danach neue Symbole, jeweils mit
// SHCNF_FLUSH (wartet, bis die Shell die Meldung hat). customInstall läuft vor dem Start der App (runAfterFinish).
test("Der Installer erneuert nach dem Update Verknüpfung und Symbole, bevor er die App startet", () => {
  const nsh = fs.readFileSync(path.join(__dirname, "build", "installer.nsh"), "utf8");
  const install = nsh.match(/!macro customInstall\r?\n([\s\S]*?)!macroend/);
  assert.ok(install, "customInstall fehlt");
  const teil = install[1];
  const schritte = [
    /\$\{If\} \$\{FileExists\} "\$newStartMenuLink"/,
    /WinShell::SetLnkAUMI "\$newStartMenuLink" "\$\{APP_ID\}"/,
    /System::Call 'shell32::SHChangeNotify\(i 0x00002000, i 0x1005, w "\$newStartMenuLink", p 0\)'/,
    /\$\{EndIf\}/,
    /System::Call 'shell32::SHChangeNotify\(i 0x00002000, i 0x1005, w "\$appExe", p 0\)'/,
    /System::Call 'shell32::SHChangeNotify\(i 0x08000000, i 0x1000, p 0, p 0\)'/,
    // gemessen: Die Shell schreibt den neu gelesenen Eintrag rund 2,2 s nach der neuen Verknüpfung, die App soll danach starten
    /Sleep 3000/,
  ];
  let ab = teil.search(/icacls\.exe/);
  assert.ok(ab >= 0, "icacls zuerst");
  for (const s of schritte) {
    const i = teil.slice(ab).search(s);
    assert.ok(i >= 0, `fehlt oder falsche Reihenfolge: ${s}`);
    ab += i + 1;
  }
  // Keine fremden Systemdateien, kein Eingriff in den Explorer: das bleibt dem Reparaturwerkzeug mit Rückfrage vorbehalten
  assert.doesNotMatch(nsh, /Caches|iconcache|explorer\.exe|taskkill|Stop-Process|ie4uinit/i);
  // electron-builder meldet neue Symbole nur beim Anlegen einer Desktop-Verknüpfung, und die gibt es hier nicht
  assert.equal(paket.build.nsis.createDesktopShortcut, false);
  assert.equal(paket.build.nsis.createStartMenuShortcut, true);
  assert.equal(paket.build.nsis.runAfterFinish, true);
});

test("electron-builder ruft customInstall nach dem Anlegen der Verknüpfung und vor dem Start der App auf", () => {
  const vorlage = path.join(__dirname, "node_modules", "app-builder-lib", "templates", "nsis", "installSection.nsh");
  const text = fs.readFileSync(vorlage, "utf8");
  const verknuepfung = text.indexOf("!insertmacro addStartMenuLink");
  const zusatz = text.indexOf("!insertmacro customInstall");
  const start = text.indexOf("!insertmacro doStartApp", zusatz);
  assert.ok(verknuepfung >= 0 && zusatz > verknuepfung && start > zusatz, "Reihenfolge in installSection.nsh geändert");
  // $newStartMenuLink und $appExe setzt die Vorlage vorher (setLinkVars, StrCpy $appExe)
  assert.ok(text.indexOf("!insertmacro setLinkVars") < zusatz);
  assert.ok(text.indexOf('StrCpy $appExe "$INSTDIR\\${APP_EXECUTABLE_FILENAME}"') < zusatz);
});

test("Version ab 0.3.0: die App meldet ihre Version und prüft Updates (Paket P3)", () => {
  const [haupt, neben] = paket.version.split(".").map(Number);
  assert.match(paket.version, /^\d+\.\d+\.\d+$/);
  assert.ok(haupt > 0 || neben >= 3, `Version ${paket.version} liegt vor 0.3.0`);
  const sperre = JSON.parse(fs.readFileSync(path.join(__dirname, "package-lock.json"), "utf8"));
  assert.equal(sperre.version, paket.version);
  assert.equal(sperre.packages[""].version, paket.version);
});

test("Brücke: genau die bekannten Kanäle, neu nur version und update (REA vergleicht dasselbe am gebauten Paket)", () => {
  const preload = fs.readFileSync(path.join(__dirname, "preload.js"), "utf8");
  const kanaele = [...preload.matchAll(/ipcRenderer\.(?:invoke|send|on)\("([^"]+)"/g)].map((m) => m[1]).sort();
  assert.deepEqual(kanaele, [
    "betriebsart",
    "betriebsart:lesen",
    "betriebsart:setzen",
    "geraet:aktivieren",
    "geraet:signieren",
    "geraet:status",
    "geraet:vorbereiten",
    "levels",
    "markierung",
    "mikrofon:status",
    "rechnername",
    "update:installieren",
    "update:pruefen",
  ]);
  const main = fs.readFileSync(path.join(__dirname, "main.js"), "utf8");
  for (const k of ["update:pruefen", "update:installieren"]) {
    const zeile = main.split(`ipcMain.handle("${k}", (event, `)[1] ?? "";
    assert.match(zeile.slice(0, 80), /^[a-z]+\) =>\s*\(?fromMainUi\(event\) && updater/, k);
  }
  assert.match(main, /additionalArguments: \[`--wamo-version=\$\{app\.getVersion\(\)\}`\]/);
});

test("Der öffentliche Update-Schlüssel kommt ins Paket, die Beispieldaten des Vertragstests nicht", () => {
  const dateien = paket.build.files;
  assert.ok(!dateien.some((f) => f.includes("update-schluessel")));
  assert.ok(dateien.includes("!testdaten/**"));
  assert.ok(fs.existsSync(path.join(__dirname, "update-schluessel.json")));
});
