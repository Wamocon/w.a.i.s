// Tests für die Erstanmeldung (lib/erstanmeldung.ts): Stand vom Kern, lokale Passwortprüfung, Übersetzung der Fehler von GoTrue,
// die 403-Codes des Kerns und der Merker des begonnenen Ablaufs.
// Ausführen im Ordner ui/:  npm test   (node:test, Node lädt TypeScript selbst)
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ABLAUF_MERKER_PRAEFIX,
  SATZ_ABGELAUFEN,
  WARNSATZ_CODE,
  ablaufMerkerAlleLoeschen,
  ablaufMerkerGesetzt,
  ablaufMerkerLoeschen,
  ablaufMerkerSetzen,
  passwortFehler,
  passwortPruefen,
  passwortSetzen,
  SATZ_STARTPASSWORT_AENDERN,
  sperrCodeAus,
  sperrSatzAus,
  sperrStandAus,
  sperrStandAusCode,
  standLaden,
  tuerEntscheidung,
  type Holen,
  type ErstanmeldungStand,
} from "./erstanmeldung.ts";

const BASIS = "https://kern.test:55444";

/** Antwort des Kerns als Attrappe: Status und JSON (oder rohen Text). */
function antwort(status: number, daten: unknown): Response {
  const body = typeof daten === "string" ? daten : JSON.stringify(daten);
  return new Response(body, { status, headers: { "Content-Type": "application/json" } });
}

/** Holen-Attrappe: merkt sich den Aufruf, liefert die vorgegebene Antwort oder wirft. */
function holenMit(wert: Response | Error) {
  const aufrufe: { url: string; init: RequestInit | undefined }[] = [];
  const holen: Holen = async (url, init) => {
    aufrufe.push({ url, init });
    if (wert instanceof Error) throw wert;
    return wert.clone();
  };
  return { holen, aufrufe };
}

/** Holen-Attrappe mit einer Folge von Antworten (oder Fehlern); die letzte gilt für alle weiteren Aufrufe. */
function holenFolge(...werte: (Response | Error)[]) {
  const aufrufe: { url: string; init: RequestInit | undefined }[] = [];
  const holen: Holen = async (url, init) => {
    aufrufe.push({ url, init });
    const wert = werte[Math.min(aufrufe.length - 1, werte.length - 1)];
    if (wert instanceof Error) throw wert;
    return wert.clone();
  };
  return { holen, aufrufe };
}

// ---------- standLaden ----------

test("standLaden: fragt GET /wamo/api/erstanmeldung mit Bearer, ohne Cache, Cookies und Umleitung", async () => {
  const { holen, aufrufe } = holenMit(antwort(200, { stand: "offen", mindestlaenge: 12 }));
  assert.equal(await standLaden(BASIS, "tok-123", holen), "offen");
  assert.equal(aufrufe.length, 1);
  assert.equal(aufrufe[0].url, `${BASIS}/wamo/api/erstanmeldung`); // exakter Pfad, keine Query (auch keine leere, der Kern sperrt sie)
  assert.ok(!aufrufe[0].url.includes("?") && !aufrufe[0].url.includes("#"));
  const init = aufrufe[0].init as RequestInit;
  assert.equal(init.method, "GET");
  assert.equal((init.headers as Record<string, string>).Authorization, "Bearer tok-123");
  assert.equal(init.cache, "no-store");
  assert.equal(init.credentials, "omit");
  assert.equal(init.redirect, "error");
});

test("standLaden: liefert jeden der vier Stände des Kerns", async () => {
  for (const stand of ["keine", "offen", "abgelaufen", "erledigt"] satisfies ErstanmeldungStand[]) {
    const { holen } = holenMit(antwort(200, { stand, mindestlaenge: 12 }));
    assert.equal(await standLaden(BASIS, "t", holen), stand, stand);
  }
});

test("standLaden: jede andere Antwort heißt keine (Laborprofil 403, alter Kern 404, Fehler, unbekannter Wert, Netz)", async () => {
  const faelle: [string, Response | Error][] = [
    ["Laborprofil: 403 ohne Erstanmeldungs-Code", antwort(403, { error: "nicht berechtigt", detail: "Nur Labor", code: "labor_gesperrt" })],
    ["403 ohne Inhalt", antwort(403, "")],
    ["alter Kern: 404", antwort(404, { error: "nicht gefunden" })],
    ["503 fail closed", antwort(503, { error: "nicht verfügbar" })],
    ["401", antwort(401, { error: "Anmeldung" })],
    ["500", antwort(500, "kaputt")],
    ["unbekannter Wert", antwort(200, { stand: "irgendwas" })],
    ["Stand fehlt", antwort(200, {})],
    ["Stand ist kein Text", antwort(200, { stand: 1 })],
    ["kein JSON", antwort(200, "<html>")],
    ["JSON ist null", antwort(200, "null")],
    ["Netzfehler", new TypeError("Failed to fetch")],
  ];
  for (const [name, wert] of faelle) {
    const { holen } = holenMit(wert);
    assert.equal(await standLaden(BASIS, "t", holen), "keine", name);
  }
});

test("standLaden: ohne Adresse oder ohne Token wird nichts gesendet", async () => {
  const { holen, aufrufe } = holenMit(antwort(200, { stand: "offen" }));
  assert.equal(await standLaden("", "t", holen), "keine");
  assert.equal(await standLaden(BASIS, "", holen), "keine");
  assert.equal(aufrufe.length, 0);
});

test("standLaden: eine Antwort, die nicht kommt, bricht nach der Zeitgrenze ab und heißt keine", async () => {
  const holen: Holen = (_url, init) =>
    new Promise((_ok, fehler) => {
      init?.signal?.addEventListener("abort", () => fehler(new DOMException("abgebrochen", "AbortError")));
    });
  assert.equal(await standLaden(BASIS, "t", holen, 20), "keine");
});

test("standLaden: bei Netzfehler oder 5xx genau ein Wiederholungsversuch, dessen Antwort zählt", async () => {
  const netz = holenFolge(new TypeError("Failed to fetch"), antwort(200, { stand: "offen" }));
  assert.equal(await standLaden(BASIS, "t", netz.holen, 2000, 1), "offen");
  assert.equal(netz.aufrufe.length, 2);
  const fuenf = holenFolge(antwort(503, { error: "x" }), antwort(200, { stand: "erledigt" }));
  assert.equal(await standLaden(BASIS, "t", fuenf.holen, 2000, 1), "erledigt");
  assert.equal(fuenf.aufrufe.length, 2);
  const durchgehend = holenFolge(antwort(500, "kaputt"));
  assert.equal(await standLaden(BASIS, "t", durchgehend.holen, 2000, 1), "keine");
  assert.equal(durchgehend.aufrufe.length, 2); // nie mehr als ein Wiederholungsversuch
  const beideNetz = holenFolge(new TypeError("Failed to fetch"));
  assert.equal(await standLaden(BASIS, "t", beideNetz.holen, 2000, 1), "keine");
  assert.equal(beideNetz.aufrufe.length, 2);
});

test("standLaden: bei 403 und 404 (und jeder anderen sicheren Antwort) keine Wiederholung", async () => {
  for (const status of [403, 404, 401, 400]) {
    const f = holenFolge(antwort(status, { error: "x" }), antwort(200, { stand: "offen" }));
    assert.equal(await standLaden(BASIS, "t", f.holen, 2000, 1), "keine", String(status));
    assert.equal(f.aufrufe.length, 1, `Status ${status}`);
  }
  const offen = holenFolge(antwort(200, { stand: "offen" }));
  assert.equal(await standLaden(BASIS, "t", offen.holen, 2000, 1), "offen");
  assert.equal(offen.aufrufe.length, 1);
});

test("standLaden: die Zeitgrenze gilt für beide Versuche zusammen, nach ihrem Ablauf kein weiterer Versuch", async () => {
  let aufrufe = 0;
  const holen: Holen = (_url, init) => {
    aufrufe++;
    return new Promise((_ok, fehler) => {
      init?.signal?.addEventListener("abort", () => fehler(new DOMException("abgebrochen", "AbortError")));
    });
  };
  const t0 = Date.now();
  assert.equal(await standLaden(BASIS, "t", holen, 40, 1), "keine");
  assert.equal(aufrufe, 1);
  assert.ok(Date.now() - t0 < 1500);
});

test("standLaden: ein 403 mit den Codes der Erstanmeldung wird zu offen oder abgelaufen", async () => {
  const a = holenMit(antwort(403, { error: "nicht berechtigt", detail: "x", code: "passwort_wechsel_noetig" }));
  assert.equal(await standLaden(BASIS, "t", a.holen), "offen");
  const b = holenMit(antwort(403, { error: "nicht berechtigt", detail: "x", code: "startpasswort_abgelaufen" }));
  assert.equal(await standLaden(BASIS, "t", b.holen), "abgelaufen");
});

// ---------- Passwort setzen über den Kern ----------

const PW = "Ein-neues-Passwort-2026";

test("passwortSetzen: POST /wamo/api/erstanmeldung/passwort mit Bearer und JSON-Rumpf, exakter Pfad ohne Query", async () => {
  const { holen, aufrufe } = holenMit(antwort(200, { stand: "erledigt" }));
  const ergebnis = await passwortSetzen(BASIS, "tok-9", PW, holen);
  assert.deepEqual(ergebnis, { ok: true, stand: "erledigt" });
  assert.equal(aufrufe.length, 1);
  assert.equal(aufrufe[0].url, `${BASIS}/wamo/api/erstanmeldung/passwort`);
  assert.ok(!aufrufe[0].url.includes("?") && !aufrufe[0].url.includes("#"));
  const init = aufrufe[0].init as RequestInit;
  assert.equal(init.method, "POST");
  const kopf = init.headers as Record<string, string>;
  assert.equal(kopf.Authorization, "Bearer tok-9");
  assert.equal(kopf["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(init.body as string), { passwort: PW });
  assert.equal(init.cache, "no-store");
  assert.equal(init.credentials, "omit");
  assert.equal(init.redirect, "error");
});

test("passwortSetzen: 200 mit unbekanntem oder fehlendem Stand ist ok, der Stand heißt keine (dann prüft die Oberfläche neu)", async () => {
  for (const daten of [{ stand: "irgendwas" }, {}, "kein json", "null"]) {
    const { holen } = holenMit(antwort(200, daten));
    assert.deepEqual(await passwortSetzen(BASIS, "t", PW, holen), { ok: true, stand: "keine" }, JSON.stringify(daten));
  }
  const offen = holenMit(antwort(200, { stand: "offen" }));
  assert.deepEqual(await passwortSetzen(BASIS, "t", PW, offen.holen), { ok: true, stand: "offen" });
});

test("passwortSetzen: Fehler tragen Status und den Code des Kerns, sonst null", async () => {
  const faelle: [number, unknown, string | null][] = [
    [400, { error: "ungültig", code: "passwort_ungueltig" }, "passwort_ungueltig"],
    [403, { code: "startpasswort_abgelaufen", detail: "x" }, "startpasswort_abgelaufen"],
    [409, { code: "kein_wechsel_noetig" }, "kein_wechsel_noetig"],
    [422, { code: "same_password" }, "same_password"],
    [422, { code: "weak_password" }, "weak_password"],
    [401, { code: "insufficient_aal" }, "insufficient_aal"],
    [401, { code: "reauthentication_needed" }, "reauthentication_needed"],
    [401, { code: "sitzung_ungueltig" }, "sitzung_ungueltig"],
    [429, { code: "zu_oft" }, "zu_oft"],
    [502, { code: "anmeldedienst" }, "anmeldedienst"],
    [503, "kaputt", null],
    [500, { code: "Kein Code!" }, null], // nur kurze Kennungen aus a-z, 0-9 und _ werden übernommen
    [500, { code: 5 }, null],
  ];
  for (const [status, daten, code] of faelle) {
    const { holen } = holenMit(antwort(status, daten));
    assert.deepEqual(await passwortSetzen(BASIS, "t", PW, holen), { ok: false, status, code }, `${status} ${JSON.stringify(daten)}`);
  }
});

test("passwortSetzen: Netzfehler und Zeitgrenze heißen Status 0, das Ergebnis enthält nie das Passwort", async () => {
  const netz = holenMit(new TypeError("Failed to fetch"));
  assert.deepEqual(await passwortSetzen(BASIS, "t", PW, netz.holen), { ok: false, status: 0, code: null });
  const holen: Holen = (_url, init) =>
    new Promise((_ok, fehler) => {
      init?.signal?.addEventListener("abort", () => fehler(new DOMException("abgebrochen", "AbortError")));
    });
  assert.deepEqual(await passwortSetzen(BASIS, "t", PW, holen, 20), { ok: false, status: 0, code: null });
  // auch ein Echo des Passworts im Rumpf des Servers gelangt nicht ins Ergebnis
  const echo = holenMit(antwort(422, { code: "weak_password", detail: `zu schwach: ${PW}` }));
  assert.doesNotMatch(JSON.stringify(await passwortSetzen(BASIS, "t", PW, echo.holen)), new RegExp(PW));
});

test("passwortSetzen: ohne Adresse oder Token wird nichts gesendet", async () => {
  const { holen, aufrufe } = holenMit(antwort(200, { stand: "erledigt" }));
  assert.deepEqual(await passwortSetzen("", "t", PW, holen), { ok: false, status: 401, code: "sitzung_ungueltig" });
  assert.deepEqual(await passwortSetzen(BASIS, "", PW, holen), { ok: false, status: 401, code: "sitzung_ungueltig" });
  assert.equal(aufrufe.length, 0);
});

// ---------- 403-Codes des Kerns ----------

test("sperrCodeAus: erkennt nur die beiden Codes der Erstanmeldung", () => {
  assert.equal(sperrCodeAus({ code: "passwort_wechsel_noetig" }), "passwort_wechsel_noetig");
  assert.equal(sperrCodeAus({ error: "nicht berechtigt", detail: "Bitte ändere zuerst dein Startpasswort.", code: "passwort_wechsel_noetig" }), "passwort_wechsel_noetig");
  assert.equal(sperrCodeAus({ code: "startpasswort_abgelaufen" }), "startpasswort_abgelaufen");
  for (const roh of [{ code: "zweiter_faktor_zu_alt" }, { code: "" }, { code: 5 }, {}, null, undefined, "passwort_wechsel_noetig", 7, []]) {
    assert.equal(sperrCodeAus(roh), null, JSON.stringify(roh));
  }
});

test("sperrStandAus und sperrStandAusCode: nur bei Status 403", () => {
  assert.equal(sperrStandAus(403, { code: "passwort_wechsel_noetig" }), "offen");
  assert.equal(sperrStandAus(403, { code: "startpasswort_abgelaufen" }), "abgelaufen");
  assert.equal(sperrStandAus(401, { code: "passwort_wechsel_noetig" }), null);
  assert.equal(sperrStandAus(200, { code: "startpasswort_abgelaufen" }), null);
  assert.equal(sperrStandAus(403, { code: "labor_gesperrt" }), null);
  // so liefert es KernFehler: Status und Code getrennt
  assert.equal(sperrStandAusCode(403, "passwort_wechsel_noetig"), "offen");
  assert.equal(sperrStandAusCode(403, "startpasswort_abgelaufen"), "abgelaufen");
  assert.equal(sperrStandAusCode(403, null), null);
  assert.equal(sperrStandAusCode(500, "passwort_wechsel_noetig"), null);
});

test("sperrSatzAus: nur bei 403, nach Code oder (beim Start über client-js ohne Code) nach dem Satz des Kerns", () => {
  assert.equal(SATZ_STARTPASSWORT_AENDERN, "Bitte ändere zuerst dein Startpasswort. Melde dich dafür neu an.");
  assert.equal(sperrSatzAus(403, "passwort_wechsel_noetig"), SATZ_STARTPASSWORT_AENDERN);
  assert.equal(sperrSatzAus(403, "startpasswort_abgelaufen"), SATZ_ABGELAUFEN);
  assert.equal(sperrSatzAus(403, undefined, "Bitte ändere zuerst dein Startpasswort."), SATZ_STARTPASSWORT_AENDERN);
  assert.equal(sperrSatzAus(403, null, SATZ_ABGELAUFEN), SATZ_ABGELAUFEN);
  // client-js stellt dem Satz des Kerns einen eigenen Text voran
  assert.equal(sperrSatzAus(403, undefined, "Fehler beim Start: Bitte ändere zuerst dein Startpasswort."), SATZ_STARTPASSWORT_AENDERN);
  // alles andere ist ein anderer 403 oder ein anderer Status: der Profilsatz bleibt
  assert.equal(sperrSatzAus(403, "zweiter_faktor_zu_alt", "Nur Admins"), null);
  assert.equal(sperrSatzAus(403, null, "Kein aktives Profil"), null);
  assert.equal(sperrSatzAus(401, "passwort_wechsel_noetig"), null);
  assert.equal(sperrSatzAus(undefined, "passwort_wechsel_noetig"), null);
  assert.equal(sperrSatzAus(500, null, SATZ_ABGELAUFEN), null);
  assert.doesNotMatch(SATZ_STARTPASSWORT_AENDERN, /[–—]| - /);
});

// ---------- Tür ----------

test("tuerEntscheidung: offen zeigt den Ablauf, abgelaufen den Satz, sonst die App", () => {
  assert.equal(tuerEntscheidung("offen", false), "ablauf");
  assert.equal(tuerEntscheidung("offen", true), "ablauf");
  assert.equal(tuerEntscheidung("abgelaufen", false), "abgelaufen");
  assert.equal(tuerEntscheidung("abgelaufen", true), "abgelaufen");
  assert.equal(tuerEntscheidung("keine", false), "app");
  assert.equal(tuerEntscheidung("erledigt", false), "app");
});

test("tuerEntscheidung: ein begonnener Ablauf geht nach dem Passwortwechsel weiter, solange der Merker steht", () => {
  assert.equal(tuerEntscheidung("erledigt", true), "ablauf");
  // ohne bestätigten Stand (Laborprofil, alter Kern, Netzfehler) bleibt es bei der App, der Kern setzt die Sperre selbst durch
  assert.equal(tuerEntscheidung("keine", true), "app");
});

// ---------- Passwortprüfung ----------

test("passwortPruefen: gültig ab 12 Zeichen und gleicher Wiederholung", () => {
  assert.equal(passwortPruefen("abcdefghijkl", "abcdefghijkl"), null);
  assert.equal(passwortPruefen("ein sehr langes Passwort 123!", "ein sehr langes Passwort 123!"), null);
});

test("passwortPruefen: zu kurz, leer, ungleich, zu lang, jeweils mit deutschem Satz", () => {
  assert.equal(passwortPruefen("", ""), "Bitte gib ein neues Passwort ein.");
  assert.equal(passwortPruefen("kurz", "kurz"), "Das neue Passwort braucht mindestens 12 Zeichen.");
  assert.equal(passwortPruefen("abcdefghijk", "abcdefghijk"), "Das neue Passwort braucht mindestens 12 Zeichen."); // 11
  assert.equal(passwortPruefen("abcdefghijkl", "abcdefghijkm"), "Die beiden Passwörter sind nicht gleich.");
  assert.equal(passwortPruefen("abcdefghijkl", ""), "Die beiden Passwörter sind nicht gleich.");
  assert.match(passwortPruefen("a".repeat(73), "a".repeat(73)) ?? "", /zu lang.*72/);
});

test("passwortPruefen: die Länge in Zeichen zählt Umlaute und Emoji je als ein Zeichen, die Obergrenze zählt Bytes", () => {
  // 12 Umlaute = 12 Zeichen (24 Bytes): genug
  assert.equal(passwortPruefen("äöüÄÖÜäöüßäö", "äöüÄÖÜäöüßäö"), null);
  // 12 Emoji = 12 Zeichen, aber 48 Bytes: noch erlaubt
  assert.equal(passwortPruefen("😀".repeat(12), "😀".repeat(12)), null);
  // 18 Emoji = 72 Bytes: erlaubt, 19 Emoji = 76 Bytes: zu lang
  assert.equal(passwortPruefen("😀".repeat(18), "😀".repeat(18)), null);
  assert.match(passwortPruefen("😀".repeat(19), "😀".repeat(19)) ?? "", /zu lang/);
  // 36 Umlaute = 72 Bytes: erlaubt, 37 = 74 Bytes: zu lang
  assert.equal(passwortPruefen("ä".repeat(36), "ä".repeat(36)), null);
  assert.match(passwortPruefen("ä".repeat(37), "ä".repeat(37)) ?? "", /zu lang/);
  // genau 72 Bytes aus ASCII
  assert.equal(passwortPruefen("a".repeat(72), "a".repeat(72)), null);
});

test("passwortPruefen: Leerzeichen am Rand gehören zum Passwort und werden nicht abgeschnitten", () => {
  assert.equal(passwortPruefen("            ", "            "), null); // 12 Leerzeichen zählen (GoTrue schneidet nicht ab)
  assert.equal(passwortPruefen(" abcdefghijk", "abcdefghijk "), "Die beiden Passwörter sind nicht gleich.");
});

// ---------- Fehler von GoTrue ----------

test("passwortFehler: übersetzt die Fehlercodes von GoTrue in deutsche Sätze", () => {
  assert.deepEqual(passwortFehler({ code: "same_password", status: 422 }), {
    text: "Das neue Passwort muss sich vom Startpasswort unterscheiden.",
    folge: "anzeigen",
  });
  const schwach = passwortFehler({ code: "weak_password", status: 422 });
  assert.equal(schwach.folge, "anzeigen");
  assert.match(schwach.text, /zu schwach/);
  assert.match(schwach.text, /12 Zeichen/);
  const neu = passwortFehler({ code: "reauthentication_needed", status: 401 });
  assert.equal(neu.text, "Bitte melde dich neu an, dann klappt der Wechsel.");
  assert.equal(neu.folge, "neu_anmelden");
});

test("passwortFehler: die Codes des Kerns (Route /erstanmeldung/passwort) haben je einen deutschen Satz", () => {
  const f = (status: number, code: string) => passwortFehler({ status, code });
  assert.deepEqual(f(429, "zu_oft"), { text: "Zu viele Versuche, bitte in zehn Minuten noch einmal.", folge: "anzeigen" });
  assert.deepEqual(f(502, "anmeldedienst"), { text: "Der Anmeldedienst ist gerade nicht erreichbar.", folge: "anzeigen" });
  const ungueltig = f(400, "passwort_ungueltig");
  assert.equal(ungueltig.folge, "anzeigen");
  assert.match(ungueltig.text, /12 Zeichen/);
  assert.match(ungueltig.text, /72 Bytes/);
  assert.deepEqual(f(403, "startpasswort_abgelaufen"), { text: SATZ_ABGELAUFEN, folge: "abgelaufen" });
  const keinWechsel = f(409, "kein_wechsel_noetig");
  assert.equal(keinWechsel.folge, "pruefen");
  assert.match(keinWechsel.text, /nicht nötig/);
  assert.deepEqual(f(401, "sitzung_ungueltig"), { text: "Bitte melde dich neu an, dann klappt der Wechsel.", folge: "neu_anmelden" });
  // ohne Code zählt der Status
  assert.equal(passwortFehler({ status: 429 }).text, "Zu viele Versuche, bitte in zehn Minuten noch einmal.");
  assert.equal(passwortFehler({ status: 502 }).text, "Der Anmeldedienst ist gerade nicht erreichbar.");
  assert.equal(passwortFehler({ status: 503, code: null }).text, "Das Passwort konnte nicht geändert werden. Bitte versuche es noch einmal.");
  for (const satz of [ungueltig.text, keinWechsel.text]) assert.doesNotMatch(satz, /[–—]| - /);
});

test("passwortFehler: insufficient_aal führt zurück zur Code-Abfrage", () => {
  const f = passwortFehler({ code: "insufficient_aal", status: 401 });
  assert.equal(f.folge, "code");
  assert.match(f.text, /Code/);
});

test("passwortFehler: alles andere ist allgemein und nennt weder Passwort noch Meldung des Servers", () => {
  const allgemein = "Das Passwort konnte nicht geändert werden. Bitte versuche es noch einmal.";
  for (const roh of [
    { code: "unexpected_failure", status: 500, message: "geheim: Passwort hunter2 abgelehnt" },
    { status: 400, message: "irgendwas" },
    {},
    null,
    undefined,
  ]) {
    const f = passwortFehler(roh);
    assert.equal(f.text, allgemein, JSON.stringify(roh));
    assert.equal(f.folge, "anzeigen");
  }
  const netz = passwortFehler({ status: 0, message: "fetch failed" });
  assert.match(netz.text, /nicht erreichbar/);
  assert.equal(netz.folge, "anzeigen");
});

// ---------- Sätze ----------

test("die festen Sätze sind wörtlich die aus dem Planpapier, ohne Gedankenstrich", () => {
  assert.equal(SATZ_ABGELAUFEN, "Dein Startpasswort ist abgelaufen. Bitte melde dich bei Niko.");
  assert.equal(
    WARNSATZ_CODE,
    "Fragt W.A.I.S. nach einem Code, obwohl du noch keine App eingerichtet hast, melde dich sofort bei Niko.",
  );
  for (const satz of [SATZ_ABGELAUFEN, WARNSATZ_CODE]) assert.doesNotMatch(satz, /[–—]| - /);
});

// ---------- Merker des begonnenen Ablaufs ----------

function speicher(): Storage & { werte: Map<string, string> } {
  const werte = new Map<string, string>();
  return {
    werte,
    get length() {
      return werte.size;
    },
    clear: () => werte.clear(),
    key: (i: number) => [...werte.keys()][i] ?? null,
    getItem: (k: string) => werte.get(k) ?? null,
    setItem: (k: string, v: string) => void werte.set(k, v),
    removeItem: (k: string) => void werte.delete(k),
  };
}

test("Merker: setzen, lesen, löschen, je Konto getrennt", () => {
  const sp = speicher();
  assert.equal(ablaufMerkerGesetzt("u-1", sp), false);
  ablaufMerkerSetzen("u-1", sp);
  assert.equal(ablaufMerkerGesetzt("u-1", sp), true);
  assert.equal(ablaufMerkerGesetzt("u-2", sp), false);
  ablaufMerkerSetzen("u-2", sp);
  ablaufMerkerLoeschen("u-1", sp);
  assert.equal(ablaufMerkerGesetzt("u-1", sp), false);
  assert.equal(ablaufMerkerGesetzt("u-2", sp), true);
  // der Schlüssel trägt das Präfix und die Kennung, der Wert nie etwas Geheimes
  assert.deepEqual([...sp.werte.keys()], [`${ABLAUF_MERKER_PRAEFIX}u-2`]);
  assert.equal([...sp.werte.values()][0], "1");
});

test("Merker: ablaufMerkerAlleLoeschen räumt alle Merker der Erstanmeldung weg und lässt Fremdes stehen", () => {
  const sp = speicher();
  ablaufMerkerSetzen("u-1", sp);
  ablaufMerkerSetzen("u-2", sp);
  sp.setItem("wamo-angemeldet-bleiben", "1");
  sp.setItem("etwas-anderes", "x");
  ablaufMerkerAlleLoeschen(sp);
  assert.deepEqual([...sp.werte.keys()].sort(), ["etwas-anderes", "wamo-angemeldet-bleiben"]);
  assert.doesNotThrow(() => ablaufMerkerAlleLoeschen(null));
  const kaputt = {
    get length(): number {
      throw new Error("gesperrt");
    },
  } as unknown as Storage;
  assert.doesNotThrow(() => ablaufMerkerAlleLoeschen(kaputt));
});

test("Merker: ohne nutzbaren Speicher oder bei Fehlern still ohne Wirkung", () => {
  const kaputt = {
    getItem: () => {
      throw new Error("gesperrt");
    },
    setItem: () => {
      throw new Error("voll");
    },
    removeItem: () => {
      throw new Error("gesperrt");
    },
  } as unknown as Storage;
  assert.doesNotThrow(() => ablaufMerkerSetzen("u-1", kaputt));
  assert.equal(ablaufMerkerGesetzt("u-1", kaputt), false);
  assert.doesNotThrow(() => ablaufMerkerLoeschen("u-1", kaputt));
  assert.equal(ablaufMerkerGesetzt("u-1", null), false);
  assert.doesNotThrow(() => ablaufMerkerSetzen("u-1", null));
  // eine leere Kennung setzt nichts
  const sp = speicher();
  ablaufMerkerSetzen("", sp);
  assert.equal(sp.werte.size, 0);
  assert.equal(ablaufMerkerGesetzt("", sp), false);
});
