// Tests für die Logik der Admin-Übersicht "Neue Mitglieder" (mitgliederUebersicht.ts). Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { datumKurz, naechsterSchritt, pruefeListe, pruefeMitglied, schritte, zusammenfassung, type Mitglied } from "./mitgliederUebersicht.ts";

const ID = "00000000-0000-4000-8000-0000000022b1";
const roh = (teil: Record<string, unknown> = {}) => ({
  user_id: ID,
  anzeigename: "Person A",
  rolle: "mitglied",
  aktiv: true,
  angelegt: "2026-11-15T09:00:00+00:00",
  letzte_anmeldung: "2026-11-16T08:00:00+00:00",
  faktor_bestaetigt: true,
  passwort_stand: null,
  geraet_stand: "aktiv",
  modellzugang: "haus",
  stimmabdruck: true,
  ...teil,
});
const mitglied = (teil: Record<string, unknown> = {}): Mitglied => pruefeMitglied(roh(teil)) as Mitglied;

test("pruefeMitglied: nur bekannte Werte, Unbekanntes wird null, ohne Kennung keine Zeile", () => {
  const m = mitglied({ geraet_stand: "quatsch", modellzugang: "sk-ant-api03-x", rolle: "chef", passwort_stand: "Erledigt!" });
  assert.equal(m.geraet, null);
  assert.equal(m.modellzugang, null);
  assert.equal(m.rolle, null);
  assert.equal(m.passwort, null);
  assert.equal(pruefeMitglied(roh({ user_id: "x" })), null);
  assert.equal(pruefeMitglied([]), null);
  assert.equal(mitglied({ anzeigename: "A‮B​C\u0000" }).name, "ABC");
  assert.equal(mitglied({ aktiv: "true" }).aktiv, false);
});

test("pruefeListe: nur mit der Liste mitglieder, kaputte Zeilen fallen weg", () => {
  assert.equal(pruefeListe({}), null);
  assert.equal(pruefeListe({ mitglieder: "x" }), null);
  assert.equal(pruefeListe({ mitglieder: [roh(), roh({ user_id: 1 })] })?.length, 1);
});

test("schritte: Reihenfolge des Ablaufs, Passwort unbekannt solange P1a fehlt", () => {
  const s = schritte(mitglied());
  assert.deepEqual(s.map((x) => x.id), ["anmeldung", "faktor", "passwort", "geraet", "stimme"]);
  assert.equal(s[2].erledigt, null);
  assert.equal(schritte(mitglied({ passwort_stand: "erledigt" }))[2].erledigt, true);
  assert.equal(schritte(mitglied({ passwort_stand: "offen" }))[2].erledigt, false);
});

test("naechsterSchritt: genau der erste fehlende Schritt", () => {
  assert.equal(naechsterSchritt(mitglied({ aktiv: false })), "Profil gesperrt. Erst nach der persönlichen Übergabe freischalten.");
  assert.equal(naechsterSchritt(mitglied({ letzte_anmeldung: null })), "Noch nie angemeldet.");
  assert.equal(naechsterSchritt(mitglied({ faktor_bestaetigt: false })), "Der zweite Faktor fehlt noch.");
  assert.equal(naechsterSchritt(mitglied({ passwort_stand: "offen" })), "Das Startpasswort ist noch nicht gewechselt.");
  assert.equal(naechsterSchritt(mitglied({ geraet_stand: "beantragt" })), "Der Laptop wartet auf deine Freigabe (Geräte und PC).");
  assert.equal(naechsterSchritt(mitglied({ geraet_stand: "keins" })), "Der Laptop ist noch nicht eingerichtet.");
  assert.equal(naechsterSchritt(mitglied({ stimmabdruck: false })), "Alles Wichtige steht, der Stimmabdruck fehlt noch.");
  assert.equal(naechsterSchritt(mitglied()), "Fertig eingerichtet.");
});

test("zusammenfassung und Datum", () => {
  assert.equal(zusammenfassung([]), "Keine Profile.");
  assert.equal(zusammenfassung([mitglied(), mitglied({ faktor_bestaetigt: false })]), "1 von 2 Profilen fertig eingerichtet.");
  assert.equal(datumKurz(null), "nie");
  assert.match(datumKurz("2026-11-15T12:00:00+00:00"), /^15\.11\.2026$/);
});

test("Texte ohne Gedankenstriche", () => {
  const texte = [naechsterSchritt(mitglied({ aktiv: false })), zusammenfassung([mitglied()])];
  for (const t of texte) assert.doesNotMatch(t, /[–—]|\s-\s/);
});
