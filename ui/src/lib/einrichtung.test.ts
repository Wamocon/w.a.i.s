// Tests für die Prüfliste im Abschnitt "Erste Schritte" (lib/einrichtung.ts): Punkte aus Kern und App, Reihenfolge, Sätze,
// Updates nur nach bestätigter Signatur, Drosselung "Erneut prüfen". Kern und Desktop-Brücke sind Attrappen.
// Ausführen im Ordner ui/:  npm test   (node:test, Node lädt TypeScript selbst)
import assert from "node:assert/strict";
import { test } from "node:test";
import { PRUEF_ABSTAND_MS, TEXT_MAX, appVersionPunkt, erneutWartezeit, hostPunkt, mikrofonPunkt, offenePunkte } from "./einrichtung.ts";
import { pruefeAppStatus, pruefeInstallation, pruefeKernStand, pruefeManifest, pruefeUpdatePruefung, prueflisteLaden } from "./einrichtung.ts";
import { satz, tunnelPunkt, updateInstallieren, zusammenfassung, zusammenfuehren } from "./einrichtung.ts";
import type { AppStand, KernStand, Punkt, PrueflisteBruecke, UpdateBruecke } from "./einrichtung.ts";

const SIGNATUR = `${"A".repeat(86)}==`;
const MANIFEST = { manifest: '{"version":"0.4.0","datei":"WAIS-Setup-0.4.0.exe"}', signatur: SIGNATUR };
const KERN_IDS = ["passwort", "geraet", "tunnel", "stimme", "gespraech", "entwicklung", "stimmabdruck", "pc"] as const;

const T_TUNNEL = "Der Tunnel steht nicht. Bist du im Büronetz?";
const T_HOST = "Die Python-Umgebung fehlt. Netz zu PyPI und GitHub nötig, die App versucht es beim nächsten Start erneut.";
const T_MIKRO = "Windows blockiert das Mikrofon für W.A.I.S.";
const T_KERN = "Die Prüfung am Server ist gerade nicht erreichbar.";
const T_NUR_APP = "Nur in der Desktop-App prüfbar.";

function kernAlleGruen(): KernStand {
  return Object.fromEntries(KERN_IDS.map((id) => [id, { stufe: "gruen", text: `Punkt ${id} ist bereit.` }])) as KernStand;
}

function appBereit(teil: Partial<AppStand> = {}): AppStand {
  return {
    version: "0.3.0",
    status: { ok: true, tunnel: "verbunden", host: "bereit" },
    mikrofon: "granted",
    update: { art: "geprueft", manifest: MANIFEST, ergebnis: { ok: true, version: "0.3.0", neuer: false } },
    ...teil,
  };
}

const punkt = (liste: readonly Punkt[], id: Punkt["id"]) => liste.find((p) => p.id === id);
const kurz = (p: Punkt | undefined) => ({ stufe: p?.stufe, text: p?.text });
const OHNE_STRICH = /[–—]|\s-\s/;

// ---------- Kern-Antwort ----------
test("Kern-Antwort: unbekannte Kennungen und Stufen fallen weg, Texte werden gekürzt und bereinigt", () => {
  const stand = pruefeKernStand({
    punkte: [
      { id: "passwort", stufe: "gruen", text: "Passwort geändert." },
      { id: "geraet", stufe: "rot", text: "x".repeat(400) },
      { id: "stimme", stufe: "gelb", text: "unbekannte Stufe" },
      { id: "gibtesnicht", stufe: "gruen", text: "unbekannte Kennung" },
      { id: "__proto__", stufe: "gruen", text: "böse" },
      { id: "pc", stufe: "hinweis", text: "Zeile\u0000mit\u0007Steuerzeichen" },
      { id: "gespraech", stufe: "gruen", text: "" },
      { id: "passwort", stufe: "rot", text: "zweiter Eintrag derselben Kennung" },
      "kein Objekt",
    ],
    geprueft: "2026-11-15T10:00:00Z",
  });
  assert.ok(stand);
  assert.deepEqual(Object.keys(stand).sort(), ["geraet", "passwort", "pc"]);
  assert.deepEqual(stand.passwort, { stufe: "gruen", text: "Passwort geändert." });
  assert.equal(stand.geraet?.text.length, TEXT_MAX);
  assert.equal(stand.pc?.text, "ZeilemitSteuerzeichen");
  assert.equal(Object.getPrototypeOf(stand), Object.prototype);
});

test("Kern-Antwort ohne Liste ist nicht lesbar", () => {
  for (const v of [null, undefined, "text", 42, [], {}, { punkte: "x" }, { punkte: {} }]) assert.equal(pruefeKernStand(v), null, String(v));
  assert.deepEqual(pruefeKernStand({ punkte: [] }), {});
});

// ---------- Reihenfolge und Zusammenführen ----------
test("Reihenfolge wie Tabelle 4.3, Anmeldung immer bereit", () => {
  const liste = zusammenfuehren({ kern: kernAlleGruen(), app: appBereit() });
  const ids = ["anmeldung", "passwort", "app", "geraet", "host", "tunnel", "mikrofon", "stimme", "gespraech", "entwicklung", "stimmabdruck", "pc"];
  assert.deepEqual(liste.map((p) => p.id), ids);
  const titel = ["Anmeldung", "Passwort", "App-Version", "Gerät", "Host-Umgebung", "Tunnel", "Mikrofon", "Stimme", "Gespräch"];
  assert.deepEqual(liste.map((p) => p.titel), [...titel, "Entwicklungsaufträge", "Stimmabdruck", "PC-Steuerung"]);
  assert.deepEqual(kurz(punkt(liste, "anmeldung")), { stufe: "gruen", text: "Angemeldet mit zweitem Faktor." });
  assert.equal(zusammenfassung(liste), "Alles bereit.");
  assert.equal(offenePunkte(liste), 0);
});

test("Sätze des Kerns erscheinen unverändert, fehlende Punkte des Kerns fallen weg", () => {
  const kern: KernStand = { passwort: { stufe: "rot", text: "Bitte zuerst dein Passwort ändern." }, tunnel: { stufe: "gruen", text: "ok" } };
  const liste = zusammenfuehren({ kern, app: appBereit() });
  assert.deepEqual(punkt(liste, "passwort"), { id: "passwort", titel: "Passwort", stufe: "rot", text: "Bitte zuerst dein Passwort ändern." });
  assert.deepEqual(liste.map((p) => p.id), ["anmeldung", "passwort", "app", "host", "tunnel", "mikrofon"]);
  assert.equal(zusammenfassung(liste), "Noch 1 Punkt offen.");
});

test("Kern nicht erreichbar: ein Punkt Kern statt der Punkte des Servers, der Tunnel gilt dann nicht als bereit", () => {
  const liste = zusammenfuehren({ kern: null, app: appBereit() });
  assert.deepEqual(liste.slice(0, 2).map((p) => p.id), ["anmeldung", "kern"]);
  assert.deepEqual(punkt(liste, "kern"), { id: "kern", titel: "Kern", stufe: "rot", text: T_KERN });
  for (const id of ["passwort", "geraet", "stimme", "gespraech", "entwicklung", "stimmabdruck", "pc"] as const) assert.equal(punkt(liste, id), undefined, id);
  assert.equal(punkt(liste, "tunnel")?.stufe, "rot");
  assert.equal(zusammenfassung(liste), "Noch 2 Punkte offen.");
});

test("Browser ohne Desktop-Brücke: die Punkte der App sind Hinweise, die Punkte des Kerns bleiben", () => {
  const liste = zusammenfuehren({ kern: kernAlleGruen(), app: null });
  for (const id of ["app", "host", "tunnel", "mikrofon"] as const) assert.deepEqual(kurz(punkt(liste, id)), { stufe: "hinweis", text: T_NUR_APP }, id);
  assert.equal(punkt(liste, "stimme")?.text, "Punkt stimme ist bereit.");
  assert.equal(zusammenfassung(liste), "Alles bereit.");
});

// ---------- App-Version und Updates ----------
test("App-Version: ohne Version (App 0.2.0) oder mit ungültiger Version heißt es Update empfohlen", () => {
  for (const version of [undefined, null, "", "0.3", "v0.3.0", "0.3.0-beta", 3, "1.2.3\n", "01.2.3", "1.02.3", "1.2.10000"]) {
    const p = appVersionPunkt(version, { art: "kein_angebot" });
    assert.deepEqual({ stufe: p.stufe, text: p.text, update: p.update }, { stufe: "rot", text: "Update empfohlen.", update: undefined }, String(version));
  }
});

test("App-Version: Server ohne signiertes Manifest, ohne Update-Prüfung in der App, Manifest nicht abrufbar", () => {
  const ohne = appVersionPunkt("0.3.0", { art: "kein_angebot" });
  assert.deepEqual(kurz(ohne), { stufe: "gruen", text: "Version 0.3.0. Der Server bietet noch kein Update an." });
  const alt = appVersionPunkt("0.3.0", { art: "ohne_pruefung" });
  assert.deepEqual(kurz(alt), { stufe: "gruen", text: "Version 0.3.0." });
  const weg = appVersionPunkt("0.3.0", { art: "unbekannt" });
  assert.equal(weg.stufe, "hinweis");
  assert.match(weg.text, /^Version 0\.3\.0\. /);
  for (const p of [ohne, alt, weg]) assert.equal(p.update, undefined);
});

test("App-Version: aktuell, oder Update nur, wenn die App die Signatur bestätigt hat und die Version neuer ist", () => {
  const aktuell = appVersionPunkt("0.4.0", { art: "geprueft", manifest: MANIFEST, ergebnis: { ok: true, version: "0.4.0", neuer: false } });
  assert.deepEqual({ stufe: aktuell.stufe, text: aktuell.text, update: aktuell.update }, { stufe: "gruen", text: "Version 0.4.0, aktuell.", update: undefined });
  const neu = appVersionPunkt("0.3.0", { art: "geprueft", manifest: MANIFEST, ergebnis: { ok: true, version: "0.4.0", neuer: true } });
  assert.equal(neu.stufe, "rot");
  assert.equal(neu.text, "Update auf Version 0.4.0 verfügbar.");
  assert.deepEqual(neu.update, { version: "0.4.0", manifest: MANIFEST.manifest, signatur: SIGNATUR });
});

test("App-Version: lehnt die App das Manifest ab, steht ihr Satz da und nie ein Update", () => {
  const text = "Update vom Server nicht bestätigt, bitte beim Admin nachfragen.";
  const p = appVersionPunkt("0.3.0", { art: "geprueft", manifest: MANIFEST, ergebnis: { ok: false, text } });
  assert.deepEqual({ stufe: p.stufe, text: p.text, update: p.update }, { stufe: "rot", text, update: undefined });
});

test("Antwort der App auf update.pruefen wird streng gelesen: ohne ok, Version und neuer kein Update", () => {
  assert.deepEqual(pruefeUpdatePruefung({ ok: true, version: "0.4.0", neuer: true }), { ok: true, version: "0.4.0", neuer: true });
  assert.deepEqual(pruefeUpdatePruefung({ ok: true, version: "0.4.0", neuer: false }), { ok: true, version: "0.4.0", neuer: false });
  const unsinn = [null, "ok", { ok: "true", version: "0.4.0", neuer: true }, { ok: true, version: "neu", neuer: true }];
  for (const v of [...unsinn, { ok: true, version: "0.4.0", neuer: "ja" }, { ok: true, neuer: true }]) {
    assert.equal(pruefeUpdatePruefung(v).ok, false, JSON.stringify(v));
  }
  const abgelehnt = pruefeUpdatePruefung({ ok: false, text: "Signatur\u0000 falsch." + "y".repeat(400) });
  assert.equal(abgelehnt.ok, false);
  if (!abgelehnt.ok) {
    assert.ok(abgelehnt.text.startsWith("Signatur falsch."));
    assert.equal(abgelehnt.text.length, TEXT_MAX);
  }
});

test("Manifest vom Server im Format der App: Signatur 64 Byte Base64 (ein LF erlaubt), höchstens 4096 Byte, null heißt kein Angebot", () => {
  assert.deepEqual(pruefeManifest({ ...MANIFEST, version: "0.4.0", groesse: 1 }), MANIFEST);
  assert.deepEqual(pruefeManifest({ manifest: "m", signatur: `${SIGNATUR}\n` }), { manifest: "m", signatur: `${SIGNATUR}\n` });
  assert.deepEqual(pruefeManifest({ manifest: "m".repeat(4096), signatur: SIGNATUR }), { manifest: "m".repeat(4096), signatur: SIGNATUR });
  for (const v of [{ manifest: "m", signatur: null }, { manifest: null, signatur: null }]) assert.equal(pruefeManifest(v), "kein_angebot");
  const falsch = [`${SIGNATUR}\n\n`, `${SIGNATUR}A`, `A${SIGNATUR}`, `${"A".repeat(87)}=`, `${"-".repeat(86)}==`, "AAAA", "kein base64!"];
  const ohneText = [{ signatur: SIGNATUR }, { manifest: "", signatur: SIGNATUR }, { manifest: 1, signatur: SIGNATUR }, { manifest: null, signatur: SIGNATUR }];
  const zuLang = [{ manifest: "m".repeat(4097), signatur: SIGNATUR }, { manifest: "ü".repeat(2049), signatur: SIGNATUR }];
  for (const v of [null, { manifest: "m" }, ...falsch.map((signatur) => ({ manifest: "m", signatur })), ...ohneText, ...zuLang]) {
    assert.equal(pruefeManifest(v), null, JSON.stringify(v)?.slice(0, 40));
  }
});

test("Anzeigetext: ohne Steuer-, Bidi- und Nullbreitenzeichen, gekürzt", () => {
  assert.equal(satz("Update\u202E gnurednA\u200B fertig.\u0007", "x"), "Update gnurednA fertig.");
  assert.equal(satz("\u200B\u202E\u2066 \u0000", "Ersatz."), "Ersatz.");
  assert.equal(satz(`${"\u200B".repeat(2000)}Text`, "Ersatz."), "Ersatz."); // nur die ersten 1200 Zeichen zählen
  assert.equal(satz("a\uD800b", "x"), "ab");
  assert.equal(satz("ü".repeat(500), "x"), "ü".repeat(TEXT_MAX));
});

// ---------- Host-Umgebung, Tunnel, Mikrofon ----------
test("Status der App wird streng gelesen", () => {
  const voll = { ok: true, eingerichtet: true, kennung: "pc-a", stufe: "admin", tunnel: "verbunden", hostUmgebung: "bereit" };
  assert.deepEqual(pruefeAppStatus(voll), { ok: true, tunnel: "verbunden", host: "bereit" });
  assert.deepEqual(pruefeAppStatus({ ok: true, eingerichtet: true, tunnel: "aus" }), { ok: true, tunnel: "aus", host: null });
  assert.deepEqual(pruefeAppStatus({ ok: true, tunnel: "quer", hostUmgebung: "zaubern" }), { ok: true, tunnel: "unbekannt", host: null });
  assert.deepEqual(pruefeAppStatus({ ok: false, text: "Gerät nicht eingerichtet." }), { ok: false, text: "Gerät nicht eingerichtet." });
  for (const v of [null, "x", { ok: "ja" }, { ok: false }]) assert.equal(pruefeAppStatus(v).ok, false, JSON.stringify(v));
});

test("Host-Umgebung: bereit und Entwicklerbetrieb sind grün, fehlt und fehler rot mit dem festen Satz", () => {
  for (const host of ["bereit", "entwickler"] as const) assert.equal(hostPunkt({ ok: true, tunnel: "aus", host }).stufe, "gruen", host);
  for (const host of ["fehlt", "fehler"] as const) assert.deepEqual(kurz(hostPunkt({ ok: true, tunnel: "aus", host })), { stufe: "rot", text: T_HOST });
  // ältere App ohne Angabe: noch nicht prüfbar, kein falscher Alarm
  assert.equal(hostPunkt({ ok: true, tunnel: "aus", host: null }).stufe, "hinweis");
  // die App kann keinen Stand melden: ihr Satz, rot
  assert.deepEqual(kurz(hostPunkt({ ok: false, text: "Kaputt." })), { stufe: "rot", text: "Kaputt." });
});

test("Tunnel: grün nur, wenn die App verbunden (oder Host) meldet und der Kern den Tunnel bestätigt", () => {
  const gruen = { stufe: "gruen", text: "Tunnel geprüft." } as const;
  const rot = { stufe: "rot", text: "Kein Socket." } as const;
  assert.equal(tunnelPunkt({ ok: true, tunnel: "verbunden", host: "bereit" }, gruen).stufe, "gruen");
  assert.equal(tunnelPunkt({ ok: true, tunnel: "host", host: "bereit" }, gruen).stufe, "gruen");
  const app = (tunnel: "verbunden" | "aus" | "unbekannt") => ({ ok: true as const, tunnel, host: "bereit" as const });
  const faelle = [tunnelPunkt(app("verbunden"), rot), tunnelPunkt(app("verbunden"), undefined), tunnelPunkt(app("aus"), gruen)];
  faelle.push(tunnelPunkt(app("unbekannt"), gruen), tunnelPunkt({ ok: false, text: "x" }, gruen), tunnelPunkt(null, gruen));
  for (const p of faelle) assert.deepEqual(kurz(p), { stufe: "rot", text: T_TUNNEL });
});

test("Mikrofon: nur granted ist grün", () => {
  assert.equal(mikrofonPunkt("granted").stufe, "gruen");
  for (const s of ["denied", "restricted", "not-determined", undefined, null, 1]) {
    assert.deepEqual(kurz(mikrofonPunkt(s)), { stufe: "rot", text: T_MIKRO }, String(s));
  }
});

// ---------- Zusammenfassung und Drosselung ----------
test("Zusammenfassung zählt nur offene Punkte, Hinweise zählen nicht", () => {
  const p = (stufe: Punkt["stufe"]): Punkt => ({ id: "pc", titel: "PC-Steuerung", stufe, text: "x" });
  assert.equal(zusammenfassung([]), "Alles bereit.");
  assert.equal(zusammenfassung([p("gruen"), p("hinweis")]), "Alles bereit.");
  assert.equal(zusammenfassung([p("rot"), p("hinweis")]), "Noch 1 Punkt offen.");
  assert.equal(zusammenfassung([p("rot"), p("rot"), p("rot")]), "Noch 3 Punkte offen.");
});

test("Erneut prüfen: einmal je 10 Sekunden, eine rückwärts laufende Uhr verkürzt nie", () => {
  assert.equal(PRUEF_ABSTAND_MS, 10_000);
  const faelle: [number | null, number, number][] = [[null, 5_000, 0], [100_000, 100_000, 10_000], [100_000, 104_000, 6_000]];
  faelle.push([100_000, 110_000, 0], [100_000, 90_000, 10_000]);
  for (const [letzte, jetzt, warten] of faelle) assert.equal(erneutWartezeit(letzte, jetzt), warten, `${letzte} ${jetzt}`);
});

// ---------- Installation ----------
test("Antwort auf update.installieren: ok, still abgebrochen oder ein Satz", () => {
  assert.deepEqual(pruefeInstallation({ ok: true }), { ok: true });
  assert.deepEqual(pruefeInstallation({ ok: false, text: "Abgebrochen.", abgebrochen: true }), { ok: false, text: "Abgebrochen.", abgebrochen: true });
  assert.deepEqual(pruefeInstallation({ ok: false, text: "Signatur passt nicht." }), { ok: false, text: "Signatur passt nicht.", abgebrochen: false });
  assert.deepEqual(pruefeInstallation("ja"), { ok: false, text: "Das Update ließ sich nicht starten.", abgebrochen: false });
  const start = "Der Installer ließ sich nicht starten. Bitte W.A.I.S. neu starten und es noch einmal versuchen.";
  assert.deepEqual(pruefeInstallation({ ok: false, text: start }), { ok: false, text: start, abgebrochen: false });
});

test("updateInstallieren: das Token geht nur an die App, ohne Token und ohne Brücke kein Aufruf", async () => {
  const angebot = { version: "0.4.0", manifest: MANIFEST.manifest, signatur: SIGNATUR };
  const aufrufe: unknown[] = [];
  const update: UpdateBruecke = {
    pruefen: async () => ({ ok: true, version: "0.4.0", neuer: true }),
    installieren: async (a) => {
      aufrufe.push(a);
      return { ok: true };
    },
  };
  assert.deepEqual(await updateInstallieren({ update, angebot, token: async () => "geheim" }), { ok: true });
  assert.deepEqual(aufrufe, [{ manifest: MANIFEST.manifest, signatur: SIGNATUR, token: "geheim" }]);
  const ohneToken = await updateInstallieren({ update, angebot, token: async () => null });
  assert.equal(ohneToken.ok, false);
  assert.equal(aufrufe.length, 1);
  assert.equal((await updateInstallieren({ update: undefined, angebot, token: async () => "geheim" })).ok, false);
  const kaputt = { ...update, installieren: async () => Promise.reject(new Error("weg")) };
  const wirft = await updateInstallieren({ update: kaputt, angebot, token: async () => "geheim" });
  assert.equal(wirft.ok, false);
  assert.ok(!JSON.stringify(wirft).includes("geheim"));
});

// ---------- Ablauf mit Kern und Brücke ----------
type Antworten = Record<string, unknown | Error>;
const fehler = (status: number) => Object.assign(new Error(`Fehler ${status}`), { status });

function kernAttrappe(antworten: Antworten) {
  const pfade: string[] = [];
  const kernJson = async (pfad: string) => {
    pfade.push(pfad);
    const a = antworten[pfad];
    if (a instanceof Error) throw a;
    if (a === undefined) throw fehler(404);
    return a;
  };
  return { kernJson, pfade };
}

const KERN_ANTWORT = { punkte: KERN_IDS.map((id) => ({ id, stufe: "gruen", text: `Punkt ${id} ist bereit.` })), geprueft: "2026-11-15T10:00:00Z" };

function brueckeAttrappe(teil: Partial<PrueflisteBruecke> = {}) {
  const pruefAufrufe: unknown[] = [];
  const bruecke: PrueflisteBruecke = {
    version: "0.3.0",
    geraet: { status: async () => ({ ok: true, eingerichtet: true, kennung: "pc-a", stufe: "mitglied", tunnel: "verbunden", hostUmgebung: "bereit" }) },
    mikrofonStatus: async () => "granted",
    update: {
      pruefen: async (a) => {
        pruefAufrufe.push(a);
        return { ok: true, version: "0.3.0", neuer: false };
      },
      installieren: async () => ({ ok: true }),
    },
    ...teil,
  };
  return { bruecke, pruefAufrufe };
}

test("prueflisteLaden: alles bereit, die App prüft genau Manifest und Signatur", async () => {
  const { kernJson, pfade } = kernAttrappe({ "/einrichtung/stand": KERN_ANTWORT, "/installer": { ...MANIFEST, version: "0.4.0" } });
  const { bruecke, pruefAufrufe } = brueckeAttrappe();
  const liste = await prueflisteLaden({ kernJson, bruecke });
  assert.equal(zusammenfassung(liste), "Alles bereit.");
  assert.deepEqual(pfade.sort(), ["/einrichtung/stand", "/installer"]);
  assert.deepEqual(pruefAufrufe, [MANIFEST]);
  assert.equal(punkt(liste, "app")?.text, "Version 0.3.0, aktuell.");
});

test("prueflisteLaden: Server ohne signiertes Manifest (Signatur null) fragt die App nicht", async () => {
  const { kernJson } = kernAttrappe({ "/einrichtung/stand": KERN_ANTWORT, "/installer": { manifest: null, signatur: null } });
  const { bruecke, pruefAufrufe } = brueckeAttrappe();
  const app = punkt(await prueflisteLaden({ kernJson, bruecke }), "app");
  assert.deepEqual(kurz(app), { stufe: "gruen", text: "Version 0.3.0. Der Server bietet noch kein Update an." });
  assert.equal(pruefAufrufe.length, 0);
});

test("prueflisteLaden: älterer Kern ohne Routen (404)", async () => {
  const { kernJson } = kernAttrappe({});
  const { bruecke, pruefAufrufe } = brueckeAttrappe();
  const liste = await prueflisteLaden({ kernJson, bruecke });
  assert.equal(punkt(liste, "kern")?.text, T_KERN);
  assert.equal(punkt(liste, "app")?.text, "Version 0.3.0. Der Server bietet noch kein Update an.");
  assert.equal(pruefAufrufe.length, 0);
});

test("prueflisteLaden: Kern-Fehler und unlesbares Manifest", async () => {
  const { kernJson } = kernAttrappe({ "/einrichtung/stand": fehler(500), "/installer": { manifest: 1 } });
  const { bruecke, pruefAufrufe } = brueckeAttrappe();
  const liste = await prueflisteLaden({ kernJson, bruecke });
  assert.equal(punkt(liste, "kern")?.stufe, "rot");
  assert.equal(punkt(liste, "app")?.stufe, "hinweis");
  assert.equal(pruefAufrufe.length, 0);
  const unlesbar = await prueflisteLaden({ kernJson: kernAttrappe({ "/einrichtung/stand": "<html>" }).kernJson, bruecke });
  assert.equal(punkt(unlesbar, "kern")?.text, T_KERN);
});

test("prueflisteLaden im Browser: kein Abruf des Manifests, Hinweise für die App", async () => {
  const { kernJson, pfade } = kernAttrappe({ "/einrichtung/stand": KERN_ANTWORT, "/installer": MANIFEST });
  const liste = await prueflisteLaden({ kernJson, bruecke: undefined });
  assert.deepEqual(pfade, ["/einrichtung/stand"]);
  assert.equal(punkt(liste, "app")?.text, T_NUR_APP);
});

test("prueflisteLaden: App 0.2.0 ohne Version und ohne Update fragt nichts an", async () => {
  const { kernJson, pfade } = kernAttrappe({ "/einrichtung/stand": KERN_ANTWORT, "/installer": MANIFEST });
  const { bruecke } = brueckeAttrappe({ version: undefined, update: undefined });
  const liste = await prueflisteLaden({ kernJson, bruecke });
  assert.deepEqual(pfade, ["/einrichtung/stand"]);
  assert.equal(punkt(liste, "app")?.text, "Update empfohlen.");
});

test("prueflisteLaden: Update nur nach Bestätigung der App, mit Knopf-Angebot", async () => {
  const { kernJson } = kernAttrappe({ "/einrichtung/stand": KERN_ANTWORT, "/installer": MANIFEST });
  const { bruecke } = brueckeAttrappe({
    update: { pruefen: async () => ({ ok: true, version: "0.4.0", neuer: true }), installieren: async () => ({ ok: true }) },
  });
  const app = punkt(await prueflisteLaden({ kernJson, bruecke }), "app");
  assert.equal(app?.text, "Update auf Version 0.4.0 verfügbar.");
  assert.equal(app?.update?.version, "0.4.0");
  const { bruecke: ablehnend } = brueckeAttrappe({
    update: { pruefen: async () => ({ ok: false, text: "Update vom Server nicht bestätigt." }), installieren: async () => ({ ok: true }) },
  });
  const abgelehnt = punkt(await prueflisteLaden({ kernJson, bruecke: ablehnend }), "app");
  assert.deepEqual({ text: abgelehnt?.text, update: abgelehnt?.update }, { text: "Update vom Server nicht bestätigt.", update: undefined });
});

test("prueflisteLaden wirft nie: Brücke wirft oder antwortet nicht", async () => {
  const { kernJson } = kernAttrappe({ "/einrichtung/stand": KERN_ANTWORT, "/installer": MANIFEST });
  const nie = () => new Promise<unknown>(() => undefined);
  const { bruecke } = brueckeAttrappe({
    geraet: { status: () => Promise.reject(new Error("weg")) },
    mikrofonStatus: nie,
    update: { pruefen: nie, installieren: async () => ({ ok: true }) },
  });
  const liste = await prueflisteLaden({ kernJson, bruecke, fristMs: 20 });
  assert.equal(punkt(liste, "host")?.stufe, "rot");
  assert.equal(punkt(liste, "tunnel")?.stufe, "rot");
  assert.equal(punkt(liste, "mikrofon")?.stufe, "rot");
  assert.equal(punkt(liste, "app")?.stufe, "rot");
  assert.equal(punkt(liste, "app")?.update, undefined);
});

test("alle festen Sätze ohne Gedankenstrich", async () => {
  const { kernJson } = kernAttrappe({});
  const texte = [
    ...(await prueflisteLaden({ kernJson, bruecke: undefined })),
    ...zusammenfuehren({ kern: kernAlleGruen(), app: appBereit() }),
    appVersionPunkt("0.3.0", { art: "unbekannt" }),
    hostPunkt({ ok: true, tunnel: "aus", host: null }),
    appVersionPunkt("0.3.0", { art: "geprueft", manifest: MANIFEST, ergebnis: { ok: true, version: "0.4.0", neuer: true } }),
  ].map((p) => `${p.titel} ${p.text}`);
  for (const t of [...texte, zusammenfassung([])]) assert.ok(!OHNE_STRICH.test(t), t);
});
