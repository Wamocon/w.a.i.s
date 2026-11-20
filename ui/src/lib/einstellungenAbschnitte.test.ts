// Tests für die Logik der Einstellungsseite (lib/einstellungenAbschnitte.ts): Gruppen und Abschnitte je Rolle, Hash, Blöcke je Plattform.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ABSCHNITTE,
  ABSCHNITT_IDS,
  GRUPPEN,
  GRUPPE_IDS,
  abschnitteFuer,
  geraeteBloecke,
  geraeteStandText,
  gruppenFuer,
  gruppeVon,
  hashFuer,
  modellzugangKurz,
  parseHash,
  rolleText,
  sprungAbschnitt,
  wirksameGruppe,
  zurueckZiel,
  type AbschnittId,
  type GruppeId,
} from "./einstellungenAbschnitte.ts";
import type { Modellzugang } from "./nachrichten.ts";

type Rolle = "admin" | "mitglied" | null;
const ids = (rolle: Rolle) => abschnitteFuer({ rolle }).map((a) => a.id);
const gruppenIds = (o: { rolle: Rolle; labor?: boolean; token?: boolean }) => gruppenFuer(o).map((g) => g.id);
const abschnittIds = (g: GruppeId, o: { rolle: Rolle; labor?: boolean; token?: boolean }) =>
  gruppenFuer(o).find((x) => x.id === g)?.abschnitte.map((a) => a.id);

// ---------- Gruppen und Abschnitte ----------
test("jede Kennung steht genau einmal in der Liste und ist ASCII", () => {
  assert.deepEqual(ABSCHNITTE.map((a) => a.id).sort(), [...ABSCHNITT_IDS].sort());
  assert.equal(new Set(ABSCHNITT_IDS).size, ABSCHNITT_IDS.length);
  for (const id of ABSCHNITT_IDS) assert.match(id, /^[a-z]+$/);
  assert.deepEqual(GRUPPEN.map((g) => g.id), [...GRUPPE_IDS]);
  for (const id of GRUPPE_IDS) assert.match(id, /^[a-z]+(-[a-z]+)?$/);
});

test("Gruppen- und Abschnittskennungen überschneiden sich nie (ein Hash meint immer genau eins)", () => {
  for (const g of GRUPPE_IDS) assert.ok(!(ABSCHNITT_IDS as readonly string[]).includes(g), g);
});

test("sechs Gruppen, jeder Abschnitt steht in genau einer, in der vorgesehenen Reihenfolge", () => {
  assert.equal(GRUPPEN.length, 6);
  assert.deepEqual(
    GRUPPEN.map((g) => [g.id, g.abschnitte]),
    [
      ["allgemein", ["konto", "start", "darstellung", "updates", "info"]],
      ["sprache-stimme", ["sprache", "stimme"]],
      ["zugaenge", ["modellzugang", "github", "verbrauch"]],
      ["geraete-pc", ["geraete", "fernzugriff"]],
      ["inhalte", ["gedaechtnis", "teilen"]],
      ["verwaltung", ["mitglieder", "aenderungen", "werkstatt"]],
    ],
  );
  const alle = GRUPPEN.flatMap((g) => g.abschnitte);
  assert.equal(alle.length, ABSCHNITT_IDS.length);
  assert.deepEqual([...alle].sort(), [...ABSCHNITT_IDS].sort());
  for (const id of ABSCHNITT_IDS) assert.equal(GRUPPEN.filter((g) => g.abschnitte.includes(id)).length, 1, id);
});

test("gruppeVon nennt die Gruppe des Abschnitts", () => {
  assert.equal(gruppeVon("stimme"), "sprache-stimme");
  assert.equal(gruppeVon("github"), "zugaenge");
  assert.equal(gruppeVon("fernzugriff"), "geraete-pc");
  assert.equal(gruppeVon("info"), "allgemein");
  for (const g of GRUPPEN) for (const a of g.abschnitte) assert.equal(gruppeVon(a), g.id);
});

test("Admin sieht sechs Gruppen mit allen Abschnitten", () => {
  assert.deepEqual(gruppenIds({ rolle: "admin" }), [...GRUPPE_IDS]);
  assert.equal(abschnitteFuer({ rolle: "admin" }).length, ABSCHNITT_IDS.length);
  assert.deepEqual(abschnittIds("zugaenge", { rolle: "admin" }), ["modellzugang", "github", "verbrauch"]);
  assert.deepEqual(abschnittIds("verwaltung", { rolle: "admin" }), ["mitglieder", "aenderungen", "werkstatt"]);
});

test("Mitglied und unbekannte Rolle: fünf Gruppen ohne Verwaltung, nur die offenen Abschnitte", () => {
  for (const rolle of ["mitglied", null] as const) {
    assert.deepEqual(gruppenIds({ rolle }), ["allgemein", "sprache-stimme", "zugaenge", "geraete-pc", "inhalte"], `Rolle ${rolle}`);
    assert.deepEqual(abschnittIds("zugaenge", { rolle }), ["modellzugang", "github"], `Rolle ${rolle}`);
    assert.deepEqual(abschnittIds("geraete-pc", { rolle }), ["geraete"], `Rolle ${rolle}`);
    assert.deepEqual(abschnittIds("inhalte", { rolle }), ["teilen"], `Rolle ${rolle}`);
    assert.deepEqual(ids(rolle), ["konto", "start", "darstellung", "updates", "info", "sprache", "stimme", "modellzugang", "github", "geraete", "teilen"]);
  }
});

test("Verbrauch: auch für Mitglieder mit eigenem Claude-Code-Token, nie in der Laborsicht", () => {
  const mitToken = (rolle: Rolle) => abschnitteFuer({ rolle, token: true }).map((a) => a.id);
  assert.ok(mitToken("mitglied").includes("verbrauch"));
  assert.ok(mitToken(null).includes("verbrauch"));
  assert.ok(mitToken("admin").includes("verbrauch"));
  assert.ok(!ids("mitglied").includes("verbrauch"));
  assert.deepEqual(abschnittIds("zugaenge", { rolle: "mitglied", token: true }), ["modellzugang", "github", "verbrauch"]);
  assert.deepEqual(abschnittIds("zugaenge", { rolle: "mitglied", token: false }), ["modellzugang", "github"]);
  for (const id of ["gedaechtnis", "fernzugriff", "aenderungen", "werkstatt"] as const) assert.ok(!mitToken("mitglied").includes(id), id);
  assert.ok(!abschnitteFuer({ rolle: "mitglied", token: true, labor: true }).map((a) => a.id).includes("verbrauch"));
  const erlaubt = gruppenFuer({ rolle: "mitglied", token: true });
  assert.equal(wirksameGruppe(parseHash("#einstellungen/verbrauch"), erlaubt, true), "zugaenge");
});

test("Fernzugriff: eigener Abschnitt nur für Admins, nicht mehr zugleich als Block der Geräte", () => {
  assert.ok(ids("admin").includes("fernzugriff"));
  for (const rolle of ["mitglied", null] as const) assert.ok(!ids(rolle).includes("fernzugriff"), `Rolle ${rolle}`);
  assert.equal(abschnitteFuer({ rolle: "admin" }).find((a) => a.id === "fernzugriff")?.nurAdmin, true);
  assert.deepEqual(parseHash("#einstellungen/fernzugriff"), { offen: true, gruppe: "geraete-pc", abschnitt: "fernzugriff" });
  // beide in derselben Gruppe sichtbar: ein Block "Fernzugriff" unter "Geräte" zeigte dieselbe Komponente ein zweites Mal
  for (const rolle of ["admin", "mitglied", null] as const) {
    const bloecke: readonly string[] = geraeteBloecke({ rolle, desktop: true, serverBrowser: false, bueroVerfuegbar: true });
    assert.ok(!bloecke.includes("fernzugriff"), `Block ${rolle}`);
  }
});

test("Änderungen: eigener Abschnitt nur für Admins", () => {
  assert.ok(ids("admin").includes("aenderungen"));
  for (const rolle of ["mitglied", null] as const) assert.ok(!ids(rolle).includes("aenderungen"), `Rolle ${rolle}`);
  assert.equal(abschnitteFuer({ rolle: "admin" }).find((a) => a.id === "aenderungen")?.nurAdmin, true);
  assert.deepEqual(parseHash("#einstellungen/aenderungen"), { offen: true, gruppe: "verwaltung", abschnitt: "aenderungen" });
});

test("Gedächtnis: eigener Abschnitt nur für Admins, mit Adresse", () => {
  assert.ok(ids("admin").includes("gedaechtnis"));
  for (const rolle of ["mitglied", null] as const) assert.ok(!ids(rolle).includes("gedaechtnis"), `Rolle ${rolle}`);
  assert.equal(abschnitteFuer({ rolle: "admin" }).find((a) => a.id === "gedaechtnis")?.nurAdmin, true);
  assert.deepEqual(parseHash("#einstellungen/gedaechtnis"), { offen: true, gruppe: "inhalte", abschnitt: "gedaechtnis" });
  // ein Mitglied sieht den Abschnitt nicht: die Adresse gilt dann wie ohne Ziel, nie als Gruppe Inhalte mit dem anderen Abschnitt
  assert.equal(wirksameGruppe(parseHash("#einstellungen/gedaechtnis"), gruppenFuer({ rolle: "mitglied" }), true), "allgemein");
  assert.equal(wirksameGruppe(parseHash("#einstellungen/gedaechtnis"), gruppenFuer({ rolle: "mitglied" }), false), null);
});

test("Texte der Gliederung ohne Gedankenstrich", () => {
  for (const a of ABSCHNITTE) assert.ok(!/[–—]|\s-\s/.test(`${a.titel} ${a.kurz} ${a.stichwort} ${a.laborKurz ?? ""}`), a.id);
  for (const g of GRUPPEN) assert.ok(!/[–—]|\s-\s/.test(g.titel), g.id);
  for (const rolle of ["admin", "mitglied", null] as const) {
    for (const g of gruppenFuer({ rolle })) assert.ok(!/[–—]|\s-\s/.test(`${g.titel} ${g.kurz}`), `${rolle} ${g.id}`);
  }
});

test("Kurzzeile der Gruppe: die Stichwörter der sichtbaren Abschnitte, mit großem Anfang", () => {
  const kurz = (rolle: Rolle, g: GruppeId) => gruppenFuer({ rolle }).find((x) => x.id === g)?.kurz;
  assert.equal(kurz("admin", "sprache-stimme"), "Mikrofon, Hören und Sprechen, eigene Stimme");
  assert.equal(kurz("admin", "zugaenge"), "Schlüssel und Modelle, GitHub-Zugang, Verbrauch");
  assert.equal(kurz("mitglied", "zugaenge"), "Schlüssel und Modelle, GitHub-Zugang");
  assert.equal(kurz("admin", "inhalte"), "Vorschläge fürs Gedächtnis, geteilte Dokumente");
  assert.equal(kurz("mitglied", "inhalte"), "Geteilte Dokumente");
  assert.equal(kurz("mitglied", "geraete-pc"), "Verbindungen und PC-Steuerung");
  assert.equal(kurz("admin", "geraete-pc"), "Verbindungen und PC-Steuerung, Fernzugriff");
  for (const rolle of ["admin", "mitglied", null] as const) {
    for (const g of gruppenFuer({ rolle })) assert.match(g.kurz, /^[A-ZÄÖÜ]/, `${rolle} ${g.id}`);
  }
});

// ---------- Hash ----------
test("Hash: Seite offen, mit und ohne Ziel", () => {
  const ohne = { offen: true, gruppe: null, abschnitt: null };
  assert.deepEqual(parseHash("#einstellungen"), ohne);
  assert.deepEqual(parseHash("einstellungen"), ohne);
  assert.deepEqual(parseHash("#einstellungen/"), ohne);
  assert.deepEqual(parseHash("#einstellungen/modellzugang"), { offen: true, gruppe: "zugaenge", abschnitt: "modellzugang" });
  assert.deepEqual(parseHash("#einstellungen/modellzugang/"), { offen: true, gruppe: "zugaenge", abschnitt: "modellzugang" });
  assert.deepEqual(parseHash("#Einstellungen/Verbrauch"), { offen: true, gruppe: "zugaenge", abschnitt: "verbrauch" });
  assert.deepEqual(parseHash("#einstellungen/zugaenge"), { offen: true, gruppe: "zugaenge", abschnitt: null });
  assert.deepEqual(parseHash("#einstellungen/Sprache-Stimme/"), { offen: true, gruppe: "sprache-stimme", abschnitt: null });
});

test("Hash: jede alte Abschnittsadresse bleibt gültig und führt zur Gruppe und zum Abschnitt", () => {
  for (const id of ABSCHNITT_IDS) {
    assert.deepEqual(parseHash(`#einstellungen/${id}`), { offen: true, gruppe: gruppeVon(id), abschnitt: id }, id);
  }
  // die drei Namen, die früher Abschnitte waren und jetzt in Gruppen mit anderem Namen stehen
  assert.equal(parseHash("#einstellungen/konto").gruppe, "allgemein");
  assert.equal(parseHash("#einstellungen/sprache").gruppe, "sprache-stimme");
  assert.equal(parseHash("#einstellungen/geraete").gruppe, "geraete-pc");
});

test("Hash: jede Gruppenadresse öffnet die Gruppe ohne Abschnitt", () => {
  for (const id of GRUPPE_IDS) assert.deepEqual(parseHash(`#einstellungen/${id}`), { offen: true, gruppe: id, abschnitt: null }, id);
});

test("Hash: Unbekanntes und Fremdes ergibt nie ein Ziel", () => {
  const ohne = { offen: true, gruppe: null, abschnitt: null };
  for (const h of ["#einstellungen/gibtesnicht", "#einstellungen/konto/mehr", "#einstellungen//konto", "#einstellungen/%6Bonto", "#einstellungen/__proto__"]) {
    assert.deepEqual(parseHash(h), ohne, h);
  }
  // Teile einer Kennung oder zwei Kennungen hintereinander sind keine Kennung
  for (const h of ["#einstellungen/sprache-", "#einstellungen/zugaenge/github", "#einstellungen/sprache/stimme", "#einstellungen/konto-allgemein"]) {
    assert.deepEqual(parseHash(h), ohne, h);
  }
  for (const h of ["", "#", "#konto", "#einstellungenx", "#x/einstellungen"]) {
    assert.deepEqual(parseHash(h), { offen: false, gruppe: null, abschnitt: null }, h);
  }
  // überlanger Rest: die Seite öffnet, aber nie mit einem Ziel (wie bei jeder anderen unbekannten Kennung)
  for (const h of [`#einstellungen/${"a".repeat(80)}`, `#einstellungen/konto/${"a".repeat(80)}`, `#einstellungen/${"zugaenge".repeat(9)}`]) {
    assert.deepEqual(parseHash(h), ohne, h.slice(0, 30));
  }
});

test("Ergebnisse von parseHash sind eingefroren und lassen sich nicht verändern", () => {
  assert.ok(Object.isFrozen(parseHash("#x")));
  assert.ok(Object.isFrozen(parseHash("#einstellungen")));
  assert.ok(Object.isFrozen(parseHash("#einstellungen/konto")));
  assert.ok(Object.isFrozen(parseHash("#einstellungen/zugaenge")));
});

test("hashFuer und parseHash sind zueinander umkehrbar, für Gruppen wie für Abschnitte", () => {
  assert.equal(hashFuer(null), "#einstellungen");
  assert.deepEqual(parseHash(hashFuer(null)), { offen: true, gruppe: null, abschnitt: null });
  for (const id of ABSCHNITT_IDS) assert.deepEqual(parseHash(hashFuer(id)), { offen: true, gruppe: gruppeVon(id), abschnitt: id });
  for (const id of GRUPPE_IDS) assert.deepEqual(parseHash(hashFuer(id)), { offen: true, gruppe: id, abschnitt: null });
  assert.equal(hashFuer("stimme"), "#einstellungen/stimme");
  assert.equal(hashFuer("zugaenge"), "#einstellungen/zugaenge");
});

// ---------- Welche Gruppe gilt, wohin springt die Seite ----------
test("wirksame Gruppe: zweispaltig die erste, einspaltig die Liste", () => {
  const admin = gruppenFuer({ rolle: "admin" });
  const mitglied = gruppenFuer({ rolle: "mitglied" });
  const ziel = (hash: string) => parseHash(hash);
  assert.equal(wirksameGruppe(ziel(""), admin, true), null);
  assert.equal(wirksameGruppe(ziel("#einstellungen"), admin, true), "allgemein");
  assert.equal(wirksameGruppe(ziel("#einstellungen"), admin, false), null);
  assert.equal(wirksameGruppe(ziel("#einstellungen/teilen"), admin, false), "inhalte");
  assert.equal(wirksameGruppe(ziel("#einstellungen/verbrauch"), admin, true), "zugaenge");
  assert.equal(wirksameGruppe(ziel("#einstellungen/verwaltung"), admin, false), "verwaltung");
  // eine Gruppenadresse, die diese Rolle nicht sieht, und ein Abschnitt, den sie nicht sieht: wie ohne Ziel
  assert.equal(wirksameGruppe(ziel("#einstellungen/verwaltung"), mitglied, true), "allgemein");
  assert.equal(wirksameGruppe(ziel("#einstellungen/verwaltung"), mitglied, false), null);
  assert.equal(wirksameGruppe(ziel("#einstellungen/verbrauch"), mitglied, true), "allgemein");
  assert.equal(wirksameGruppe(ziel("#einstellungen/verbrauch"), mitglied, false), null);
  // keine erlaubten Gruppen: nie eine Gruppe
  assert.equal(wirksameGruppe(ziel("#einstellungen/konto"), [], true), null);
  assert.equal(wirksameGruppe(ziel("#einstellungen"), [], true), null);
});

test("Sprung: nur zu einem Abschnitt der wirksamen Gruppe, den die Rolle sieht", () => {
  const admin = gruppenFuer({ rolle: "admin" });
  const mitglied = gruppenFuer({ rolle: "mitglied" });
  const gruppe = (liste: ReturnType<typeof gruppenFuer>, id: GruppeId) => liste.find((g) => g.id === id);
  assert.equal(sprungAbschnitt(parseHash("#einstellungen/github"), gruppe(admin, "zugaenge")), "github");
  assert.equal(sprungAbschnitt(parseHash("#einstellungen/zugaenge"), gruppe(admin, "zugaenge")), null);
  assert.equal(sprungAbschnitt(parseHash("#einstellungen"), gruppe(admin, "zugaenge")), null);
  assert.equal(sprungAbschnitt(parseHash(""), gruppe(admin, "zugaenge")), null);
  // Abschnitt einer anderen Gruppe, unbekannte Gruppe, nicht sichtbarer Abschnitt
  assert.equal(sprungAbschnitt(parseHash("#einstellungen/stimme"), gruppe(admin, "zugaenge")), null);
  assert.equal(sprungAbschnitt(parseHash("#einstellungen/stimme"), undefined), null);
  assert.equal(sprungAbschnitt(parseHash("#einstellungen/verbrauch"), gruppe(mitglied, "zugaenge")), null);
});

test("Zurück: am Handy aus der Gruppe zur Liste, sonst zum Gespräch", () => {
  assert.equal(zurueckZiel("zugaenge", false), "liste");
  assert.equal(zurueckZiel(null, false), "gespraech");
  assert.equal(zurueckZiel("zugaenge", true), "gespraech");
  assert.equal(zurueckZiel(null, true), "gespraech");
});

// ---------- Geräte und PC ----------
const basis = { rolle: "mitglied" as const, desktop: false, serverBrowser: false, bueroVerfuegbar: true };

test("Geräteblöcke je Rolle und Plattform", () => {
  assert.deepEqual(geraeteBloecke(basis), ["status", "betriebsart"]);
  assert.deepEqual(geraeteBloecke({ ...basis, rolle: "admin" }), ["status", "verwaltung", "pc", "betriebsart"]);
  assert.deepEqual(geraeteBloecke({ ...basis, rolle: "admin", desktop: true }), ["status", "verwaltung", "pc", "betriebsart", "einrichtung"]);
  // Browser auf dem Server: nichts zu wählen, aber der Admin sieht den Hinweis zur PC-Steuerung
  assert.deepEqual(geraeteBloecke({ ...basis, rolle: "admin", serverBrowser: true }), ["status", "verwaltung", "pc"]);
  assert.deepEqual(geraeteBloecke({ ...basis, serverBrowser: true }), ["status"]);
  // Büro nicht eingerichtet: keine Betriebsart zu wählen
  assert.deepEqual(geraeteBloecke({ ...basis, bueroVerfuegbar: false, desktop: true }), ["status", "einrichtung"]);
  assert.deepEqual(geraeteBloecke({ ...basis, rolle: null }), ["status", "betriebsart"]);
});

test("Block PC-Steuerung ohne Sitzung: aus der gemerkten Rolle (pcAdmin), Laborkonten nie, die übrigen Admin-Blöcke folgen der Rolle", () => {
  // noch keine Sitzung: der Kern hat keine Rolle gemeldet, die gemerkte ist admin
  assert.deepEqual(geraeteBloecke({ ...basis, rolle: null, desktop: true, pcAdmin: true }), ["status", "pc", "betriebsart", "einrichtung"]);
  // Laborkonto mit gemeldeter Admin-Rolle: kein Block PC-Steuerung
  assert.deepEqual(geraeteBloecke({ ...basis, rolle: "admin", pcAdmin: false }), ["status", "verwaltung", "betriebsart"]);
  assert.deepEqual(geraeteBloecke({ ...basis, rolle: "admin", pcAdmin: true }), ["status", "verwaltung", "pc", "betriebsart"]);
});

test("Stand der Geräteeinrichtung als Satz", () => {
  const stand = { zustand: "eingerichtet" as const, tunnel: "verbunden" as const, kennung: "pc-niko" };
  const buero = { desktop: true, bueroBetrieb: true };
  const t = geraeteStandText(stand, buero);
  assert.equal(t.art, "bereit");
  assert.match(t.text, /Kennung pc-niko/);
  assert.match(t.text, /Tunnel zu W.A.I.S. verbunden/);
  assert.equal(geraeteStandText({ ...stand, tunnel: "aus" }, buero).art, "offen");
  assert.equal(geraeteStandText({ zustand: "wartet", tunnel: null, kennung: null }, buero).art, "wartet");
  const f = geraeteStandText({ zustand: "fehler", text: "Der Kern ist nicht erreichbar.", tunnel: null, kennung: null }, buero);
  assert.deepEqual(f, { text: "Der Kern ist nicht erreichbar.", art: "fehler" });
  assert.equal(geraeteStandText({ zustand: "nicht_noetig", tunnel: null, kennung: null }, buero).art, "offen");
  assert.match(geraeteStandText(stand, { desktop: false, bueroBetrieb: true }).text, /nur in der Desktop-App/);
  assert.match(geraeteStandText(stand, { desktop: true, bueroBetrieb: false }).text, /Betriebsart Büro/);
});

test("Stand der Geräteeinrichtung: alle Tunnelzustände, fehlende Kennung, Fehler ohne Text", () => {
  const buero = { desktop: true, bueroBetrieb: true };
  const eingerichtet = (tunnel: "verbunden" | "host" | "aus" | "unbekannt" | null, kennung: string | null) =>
    geraeteStandText({ zustand: "eingerichtet", tunnel, kennung }, buero);
  assert.equal(eingerichtet("host", "pc-niko").art, "bereit");
  assert.match(eingerichtet("host", "pc-niko").text, /kein Tunnel nötig/);
  assert.equal(eingerichtet("unbekannt", null).art, "offen");
  assert.match(eingerichtet("unbekannt", null).text, /Tunnel unbekannt/);
  // Tunnel noch nicht gemeldet: eingerichtet, aber noch nichts weiter zu sagen
  assert.deepEqual(eingerichtet(null, null), { text: "Eingerichtet.", art: "offen" });
  assert.ok(!eingerichtet("verbunden", null).text.includes("Kennung"));
  assert.match(geraeteStandText({ zustand: "fehler", tunnel: null, kennung: null }, buero).text, /fehlgeschlagen/);
});

const Z: Modellzugang = { aktion: "status", hinterlegt: false, festgelegt: false, codeHinterlegt: false };

test("Kurzzeile Modellzugang: nur der Stand, nie ein Wert", () => {
  assert.equal(modellzugangKurz(null), "wird geladen");
  assert.equal(modellzugangKurz({ ...Z, fehler: "Kern nicht erreichbar" }), "Stand nicht lesbar");
  assert.equal(modellzugangKurz({ ...Z, art: "haus" }), "fehlt");
  assert.equal(modellzugangKurz({ ...Z, art: "claude", hinterlegt: true, ende: "ab12" }), "Claude-Schlüssel hinterlegt");
  assert.equal(modellzugangKurz({ ...Z, art: "haus", codeHinterlegt: true, codeEnde: "cd34" }), "Token hinterlegt");
  assert.equal(modellzugangKurz({ ...Z, art: "claude", hinterlegt: true, codeHinterlegt: true }), "Claude-Schlüssel und Token hinterlegt");
  assert.equal(modellzugangKurz({ ...Z, art: "claude", quelle: "zuordnung" }), "Schlüssel des Kerns");
  // ohne lesbare Art ist der Stand nicht lesbar, auch ohne Fehlertext; mit Art zählt ein anhängender Fehler nicht
  assert.equal(modellzugangKurz({ ...Z }), "Stand nicht lesbar");
  assert.equal(modellzugangKurz({ ...Z, art: "claude", hinterlegt: true, fehler: "alter Fehler" }), "Claude-Schlüssel hinterlegt");
  const alle = [null, Z, { ...Z, hinterlegt: true, ende: "ab12" }].map(modellzugangKurz).join(" ");
  assert.ok(!alle.includes("ab12"));
});

test("Rollentext", () => {
  assert.equal(rolleText("admin"), "Admin");
  assert.equal(rolleText("mitglied"), "Mitglied");
  assert.equal(rolleText(null), "noch unbekannt");
});

// ---------- Laborsicht ----------
test("Laborsicht: genau eine Gruppe mit dem Abschnitt der Mikrofonwahl, für jede Rolle", () => {
  for (const rolle of ["admin", "mitglied", null] as const) {
    assert.deepEqual(abschnitteFuer({ rolle, labor: true }).map((a) => a.id), ["sprache"], `Rolle ${rolle}`);
    assert.deepEqual(gruppenIds({ rolle, labor: true }), ["sprache-stimme"], `Rolle ${rolle}`);
    assert.deepEqual(abschnittIds("sprache-stimme", { rolle, labor: true }), ["sprache"], `Rolle ${rolle}`);
  }
  const g = gruppenFuer({ rolle: "mitglied", labor: true })[0];
  assert.equal(g.titel, "Sprache und Stimme");
  assert.equal(g.kurz, "Mikrofon wählen");
  assert.equal(g.abschnitte[0].titel, "Mikrofon und Sprache");
  assert.equal(g.abschnitte[0].kurz, "Mikrofon wählen");
});

test("Laborsicht aus (oder nicht angegeben): die Gruppen und Abschnitte je Rolle bleiben genau wie vorher", () => {
  for (const rolle of ["admin", "mitglied", null] as const) {
    assert.deepEqual(abschnitteFuer({ rolle, labor: false }), abschnitteFuer({ rolle }), `Rolle ${rolle}`);
    assert.deepEqual(gruppenFuer({ rolle, labor: false }), gruppenFuer({ rolle }), `Rolle ${rolle}`);
  }
  assert.equal(ids("admin").length, ABSCHNITT_IDS.length);
});

test("Laborsicht: ein Hash auf eine gesperrte Gruppe oder einen gesperrten Abschnitt führt zur Mikrofonwahl oder zur Liste", () => {
  const erlaubt = gruppenFuer({ rolle: "mitglied", labor: true });
  const gesperrt = ["modellzugang", "geraete", "konto", "info", "start", "updates", "stimme", "zugaenge", "geraete-pc", "allgemein", "verwaltung"];
  for (const ziel of gesperrt) {
    const hash = `#einstellungen/${ziel}`;
    assert.equal(wirksameGruppe(parseHash(hash), erlaubt, true), "sprache-stimme", hash);
    assert.equal(wirksameGruppe(parseHash(hash), erlaubt, false), null, hash);
  }
  assert.equal(wirksameGruppe(parseHash("#einstellungen/sprache"), erlaubt, false), "sprache-stimme");
  assert.equal(wirksameGruppe(parseHash("#einstellungen/sprache-stimme"), erlaubt, false), "sprache-stimme");
  // die Stimme steht in derselben Gruppe, ist aber in der Laborsicht kein Abschnitt: Adresse wie ohne Ziel
  assert.equal(wirksameGruppe(parseHash("#einstellungen/stimme"), erlaubt, false), null);
});

test("Laborsicht: der Abschnitt hat eine eigene Kurzzeile, die Gliederung der anderen Konten bleibt", () => {
  const labor = abschnitteFuer({ rolle: "mitglied", labor: true });
  assert.equal(labor.length, 1);
  assert.equal(labor[0].kurz, "Mikrofon wählen");
  assert.equal(labor[0].id, "sprache");
  // alle anderen Sichten behalten die Kurzzeile und die Liste selbst bleibt unverändert
  for (const rolle of ["admin", "mitglied", null] as const) {
    assert.equal(abschnitteFuer({ rolle }).find((a) => a.id === "sprache")?.kurz, "Mikrofon, Spracherkennung und Sprachausgabe", `Rolle ${rolle}`);
  }
  assert.equal(ABSCHNITTE.find((a) => a.id === "sprache")?.kurz, "Mikrofon, Spracherkennung und Sprachausgabe");
});

test("Texte der Laborsicht ohne Gedankenstrich, nur an der Laborsicht zu erkennen", () => {
  for (const a of abschnitteFuer({ rolle: null, labor: true })) assert.ok(!/[–—]|\s-\s/.test(`${a.titel} ${a.kurz}`), a.id);
});

// ---------- einzelne Abschnitte ----------
test("Abschnitt Erste Schritte: direkt nach Konto, für jede Rolle, nie in der Laborsicht, mit eigenem Hash", () => {
  for (const rolle of ["admin", "mitglied", null] as const) {
    const liste = abschnittIds("allgemein", { rolle }) ?? [];
    assert.equal(liste.indexOf("start"), liste.indexOf("konto") + 1, `Rolle ${rolle}`);
  }
  const start = ABSCHNITTE.find((a) => a.id === "start");
  // die Updates haben einen eigenen Abschnitt (siehe unten), die Ersten Schritte nennen sie nicht mehr als ihren Inhalt
  assert.deepEqual({ titel: start?.titel, kurz: start?.kurz }, { titel: "Erste Schritte", kurz: "Modellzugang, Installer und Prüfliste" });
  assert.equal(start?.nurAdmin, undefined);
  assert.equal(start?.laborSicht, undefined);
  for (const rolle of ["admin", "mitglied", null] as const) {
    assert.ok(!abschnitteFuer({ rolle, labor: true }).some((a) => a.id === "start"), `Laborsicht ${rolle}`);
  }
  assert.deepEqual(parseHash("#einstellungen/start"), { offen: true, gruppe: "allgemein", abschnitt: "start" });
  // im Labor führt ein Hash auf "start" nie in den Abschnitt
  assert.equal(wirksameGruppe(parseHash("#einstellungen/start"), gruppenFuer({ rolle: "mitglied", labor: true }), true), "sprache-stimme");
  // ohne Ziel in der Adresse bleibt Konto und Allgemeines die erste Gruppe
  assert.equal(wirksameGruppe({ offen: true, gruppe: null, abschnitt: null }, gruppenFuer({ rolle: "mitglied" }), true), "allgemein");
});

test("Abschnitt Updates: für jede Rolle und mit oder ohne Token zwischen Darstellung und Info, nie in der Laborsicht, mit eigenem Hash", () => {
  for (const o of [{ rolle: "admin" }, { rolle: "mitglied" }, { rolle: null }, { rolle: "mitglied", token: true }] as const) {
    const liste = abschnittIds("allgemein", o) ?? [];
    assert.equal(liste.indexOf("updates"), liste.indexOf("darstellung") + 1, JSON.stringify(o));
    assert.equal(liste.indexOf("info"), liste.indexOf("updates") + 1, JSON.stringify(o));
  }
  const updates = ABSCHNITTE.find((a) => a.id === "updates");
  assert.deepEqual({ titel: updates?.titel, kurz: updates?.kurz }, { titel: "Updates", kurz: "Neue Version der Desktop-App suchen und installieren" });
  assert.equal(updates?.nurAdmin, undefined);
  assert.equal(updates?.auchMitToken, undefined);
  assert.equal(updates?.laborSicht, undefined);
  for (const rolle of ["admin", "mitglied", null] as const) {
    assert.ok(!abschnitteFuer({ rolle, labor: true }).some((a) => a.id === "updates"), `Laborsicht ${rolle}`);
  }
  assert.deepEqual(gruppenIds({ rolle: "mitglied", labor: true }), ["sprache-stimme"]);
  assert.deepEqual(parseHash("#einstellungen/updates"), { offen: true, gruppe: "allgemein", abschnitt: "updates" });
  assert.deepEqual(parseHash("#Einstellungen/Updates/"), { offen: true, gruppe: "allgemein", abschnitt: "updates" });
  assert.equal(hashFuer("updates"), "#einstellungen/updates");
  // die alte Adresse der Ersten Schritte bleibt gültig und führt nicht zu den Updates
  assert.deepEqual(parseHash("#einstellungen/start"), { offen: true, gruppe: "allgemein", abschnitt: "start" });
  // im Labor führt ein Hash auf "updates" nie in den Abschnitt
  assert.equal(wirksameGruppe(parseHash("#einstellungen/updates"), gruppenFuer({ rolle: "admin", labor: true }), true), "sprache-stimme");
  assert.equal(wirksameGruppe(parseHash("#einstellungen/updates"), gruppenFuer({ rolle: "mitglied" }), false), "allgemein");
  assert.equal(sprungAbschnitt(parseHash("#einstellungen/updates"), gruppenFuer({ rolle: "mitglied" }).find((g) => g.id === "allgemein")), "updates");
});

test("Kurzzeile von Konto und Allgemeines nennt die Updates, für jede Rolle", () => {
  for (const rolle of ["admin", "mitglied", null] as const) {
    const kurz = gruppenFuer({ rolle }).find((g) => g.id === "allgemein")?.kurz;
    assert.equal(kurz, "Konto, erste Schritte, Darstellung, Updates, Version und Hinweise", `Rolle ${rolle}`);
  }
});

test("Abschnitt Eigene Stimme: für jede Rolle da, in der Laborsicht nicht, mit eigenem Hash", () => {
  for (const rolle of ["admin", "mitglied", null] as const) {
    assert.ok(abschnitteFuer({ rolle }).some((a) => a.id === "stimme"), `Rolle ${rolle}`);
  }
  assert.equal(abschnitteFuer({ rolle: "admin", labor: true }).some((a) => a.id === "stimme"), false, "Laborkonten sehen keine Stimmerkennung");
  assert.deepEqual(parseHash("#einstellungen/stimme"), { offen: true, gruppe: "sprache-stimme", abschnitt: "stimme" });
  assert.equal(ABSCHNITTE.find((a) => a.id === "stimme")?.titel, "Eigene Stimme");
});

test("Titel der Abschnitte sind eindeutig und keiner heißt wie seine Gruppe", () => {
  const titel = ABSCHNITTE.map((a) => a.titel);
  assert.equal(new Set(titel).size, titel.length);
  for (const g of GRUPPEN) assert.ok(!titel.includes(g.titel), g.titel);
});

test("jede alte Adresse #einstellungen/<Abschnitt> öffnet über wirksameGruppe und sprungAbschnitt genau diesen Abschnitt", () => {
  const admin = gruppenFuer({ rolle: "admin" });
  for (const id of ABSCHNITT_IDS as readonly AbschnittId[]) {
    const ziel = parseHash(hashFuer(id));
    const gruppe = wirksameGruppe(ziel, admin, false);
    assert.equal(gruppe, gruppeVon(id), id);
    assert.equal(sprungAbschnitt(ziel, admin.find((g) => g.id === gruppe)), id, id);
  }
});

test("Werkstatt: nur für Admins, nie in der Laborsicht, in der Gruppe Verwaltung", () => {
  assert.ok(ids("admin").includes("werkstatt"));
  for (const rolle of ["mitglied", null] as const) assert.ok(!ids(rolle).includes("werkstatt"), `Rolle ${rolle}`);
  assert.equal(abschnitteFuer({ rolle: "admin" }).find((a) => a.id === "werkstatt")?.nurAdmin, true);
  assert.ok(!abschnitteFuer({ rolle: "admin", labor: true }).some((a) => a.id === "werkstatt"));
  assert.equal(gruppeVon("werkstatt"), "verwaltung");
  assert.deepEqual(parseHash("#einstellungen/werkstatt"), { offen: true, gruppe: "verwaltung", abschnitt: "werkstatt" });
});
