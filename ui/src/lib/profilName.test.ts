import assert from "node:assert/strict";
import test from "node:test";
import { nameAusEmail, profilAnzeige } from "./profilName.ts";

test("aus der Anmelde-E-Mail wird ein lesbarer voller Name", () => {
  assert.equal(nameAusEmail("vorname.nachname@firma.example"), "Vorname Nachname");
  assert.equal(nameAusEmail("anna-lena.muster_test@firma.example"), "Anna Lena Muster Test");
  assert.equal(nameAusEmail("ÖZGE.ÜNAL@firma.example"), "Özge Ünal");
});

test("ohne brauchbare E-Mail gibt es keinen abgeleiteten Namen", () => {
  for (const wert of [null, undefined, "", "keine-mail", "@firma.example", "...@firma.example"]) {
    assert.equal(nameAusEmail(wert), null, String(wert));
  }
});

test("der volle Name vom Kern hat Vorrang, sonst der Name aus der E-Mail", () => {
  assert.equal(profilAnzeige("Vorname Nachname", "x.y@firma.example"), "Vorname Nachname");
  assert.equal(profilAnzeige("  Vorname Nachname  ", null), "Vorname Nachname");
  assert.equal(profilAnzeige(null, "vorname.nachname@firma.example"), "Vorname Nachname");
  assert.equal(profilAnzeige("   ", "vorname.nachname@firma.example"), "Vorname Nachname");
  assert.equal(profilAnzeige(null, null), "Profil");
});
