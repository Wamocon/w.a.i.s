// Tests für die Logik des Pop-ups "Update verfügbar" (lib/updateHinweis.ts): wann "Später" gilt (je Version, bis zum nächsten Start oder
// 24 Stunden), strenges Lesen des Eintrags, Speicher mit Rückfall, welche Art von Pop-up der Stand ergibt und die Sätze.
// Ausführen im Ordner ui/:  npm test   (node:test, Node lädt TypeScript selbst)
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import {
  SPAETER_FRIST_MS,
  startId,
  hinweisArt,
  hinweisSatz,
  pruefeSpaeterEintrag,
  spaeterGilt,
  spaeterLesen,
  spaeterRueckfallLeeren,
  spaeterSchluessel,
  spaeterSchreiben,
  type SpaeterEintrag,
} from "./updateHinweis.ts";

const ANGEBOT = { version: "0.8.0", manifest: "{}", signatur: "s" };
const JETZT = 1_800_000_000_000;
const EINTRAG: SpaeterEintrag = { version: "0.8.0", zeit: JETZT, start: "start-a" };
const OHNE_STRICH = /[–—]|\s-\s/;

beforeEach(() => spaeterRueckfallLeeren());

// ---------- Später ----------
test("ohne Eintrag gilt kein Später", () => {
  assert.equal(spaeterGilt(null, "0.8.0", JETZT, "start-a"), false);
});

test("dieselbe Version im selben Start innerhalb von 24 Stunden bleibt ausgeblendet", () => {
  assert.equal(spaeterGilt(EINTRAG, "0.8.0", JETZT, "start-a"), true);
  assert.equal(spaeterGilt(EINTRAG, "0.8.0", JETZT + SPAETER_FRIST_MS - 1, "start-a"), true);
});

test("nach 24 Stunden kommt dieselbe Version wieder", () => {
  assert.equal(spaeterGilt(EINTRAG, "0.8.0", JETZT + SPAETER_FRIST_MS, "start-a"), false);
  assert.equal(spaeterGilt(EINTRAG, "0.8.0", JETZT + SPAETER_FRIST_MS + 60_000, "start-a"), false);
});

test("nach dem nächsten Start der App kommt dieselbe Version wieder, auch nach einer Minute", () => {
  assert.equal(spaeterGilt(EINTRAG, "0.8.0", JETZT + 60_000, "start-b"), false);
});

test("eine neuere Version erscheint sofort, auch im selben Start (0.10.0 ist neuer als 0.9.9)", () => {
  assert.equal(spaeterGilt(EINTRAG, "0.8.1", JETZT + 1, "start-a"), false);
  assert.equal(spaeterGilt(EINTRAG, "0.9.0", JETZT + 1, "start-a"), false);
  assert.equal(spaeterGilt({ ...EINTRAG, version: "0.9.9" }, "0.10.0", JETZT + 1, "start-a"), false);
});

test("eine ältere Version (der Server nimmt ein Update zurück) bleibt im selben Start ausgeblendet", () => {
  assert.equal(spaeterGilt(EINTRAG, "0.7.5", JETZT + 1, "start-a"), true);
});

test("eine Version, die sich nicht vergleichen lässt, zeigt das Pop-up", () => {
  assert.equal(spaeterGilt(EINTRAG, "neu", JETZT + 1, "start-a"), false);
});

// ---------- Eintrag lesen ----------
test("pruefeSpaeterEintrag: genau Version, Zeit und Start, sonst kein Eintrag", () => {
  assert.deepEqual(pruefeSpaeterEintrag({ version: "0.8.0", zeit: 5, start: "a" }), { version: "0.8.0", zeit: 5, start: "a" });
  assert.deepEqual(pruefeSpaeterEintrag({ version: "0.8.0", zeit: 5, start: "a", extra: 1 }), { version: "0.8.0", zeit: 5, start: "a" });
  for (const schlecht of [
    null,
    "text",
    [],
    {},
    { version: "0.8", zeit: 5, start: "a" },
    { version: "0.8.0-beta", zeit: 5, start: "a" },
    { version: "0.8.0", zeit: "5", start: "a" },
    { version: "0.8.0", zeit: -1, start: "a" },
    { version: "0.8.0", zeit: Number.NaN, start: "a" },
    { version: "0.8.0", zeit: Infinity, start: "a" },
    { version: "0.8.0", zeit: 5, start: "" },
    { version: "0.8.0", zeit: 5, start: "x".repeat(65) },
  ]) {
    assert.equal(pruefeSpaeterEintrag(schlecht), null, JSON.stringify(schlecht));
  }
});

// ---------- Speicher ----------
function speicher(werte: Record<string, string> = {}) {
  return {
    werte,
    getItem: (k: string) => werte[k] ?? null,
    setItem: (k: string, v: string) => {
      werte[k] = v;
    },
  };
}

test("der Eintrag liegt je Profil unter einem eigenen Schlüssel und kommt unverändert zurück", () => {
  const s = speicher();
  spaeterSchreiben("profil-a", EINTRAG, s);
  assert.deepEqual(Object.keys(s.werte), [spaeterSchluessel("profil-a")]);
  assert.equal(spaeterSchluessel("profil-a"), "wamo.update.spaeter.profil-a");
  assert.deepEqual(spaeterLesen("profil-a", s), EINTRAG);
  assert.equal(spaeterLesen("profil-b", s), null);
});

test("ein kaputter Eintrag im Speicher gilt als keiner", () => {
  assert.equal(spaeterLesen("p", speicher({ [spaeterSchluessel("p")]: "{kaputt" })), null);
  assert.equal(spaeterLesen("p", speicher({ [spaeterSchluessel("p")]: '{"version":"x"}' })), null);
});

test("ein Speicher, der wirft, bricht nichts: Später gilt über den Arbeitsspeicher weiter", () => {
  const wirft = {
    getItem: () => {
      throw new Error("gesperrt");
    },
    setItem: () => {
      throw new Error("voll");
    },
  };
  assert.equal(spaeterLesen("p", wirft), null);
  assert.doesNotThrow(() => spaeterSchreiben("p", EINTRAG, wirft));
  assert.deepEqual(spaeterLesen("p", wirft), EINTRAG);
  assert.deepEqual(spaeterLesen("p", null), EINTRAG);
});

test("ohne localStorage überhaupt (null) funktioniert es wie mit einem werfenden", () => {
  assert.doesNotThrow(() => spaeterSchreiben("q", EINTRAG, null));
  assert.deepEqual(spaeterLesen("q", null), EINTRAG);
});

test("die Kennung des Starts ist ein kurzer Text und bleibt innerhalb des Starts gleich", () => {
  assert.match(startId(), /^[a-z0-9]+-[a-z0-9]+$/);
  assert.ok(startId().length <= 64);
  assert.equal(startId(), startId());
});

// ---------- Anzeige ----------
test("hinweisArt: Angebot, Installation, Fehler; sonst nichts", () => {
  const phase = (art: "ruhe" | "laeuft" | "gestartet" | "fehler") => (art === "fehler" ? ({ art, text: "x" } as const) : ({ art } as const));
  assert.equal(hinweisArt({ angebot: ANGEBOT, phase: phase("ruhe"), spaeter: false }), "angebot");
  assert.equal(hinweisArt({ angebot: ANGEBOT, phase: phase("laeuft"), spaeter: false }), "laeuft");
  assert.equal(hinweisArt({ angebot: ANGEBOT, phase: phase("fehler"), spaeter: false }), "fehler");
  // nach dem Start der Installation beendet sich die App: nichts mehr zeigen
  assert.equal(hinweisArt({ angebot: ANGEBOT, phase: phase("gestartet"), spaeter: false }), "aus");
  // ohne bestätigtes Angebot nie, nach Später nicht
  for (const art of ["ruhe", "laeuft", "fehler", "gestartet"] as const) {
    assert.equal(hinweisArt({ angebot: null, phase: phase(art), spaeter: false }), "aus", art);
    assert.equal(hinweisArt({ angebot: ANGEBOT, phase: phase(art), spaeter: true }), "aus", art);
  }
});

test("hinweisSatz: der Satz zur Version, mit dem Zusatz nur bei einem laufenden Gespräch", () => {
  assert.equal(hinweisSatz("0.8.0", false), "Version 0.8.0 ist bereit. Die App startet nach der Installation neu.");
  assert.equal(
    hinweisSatz("0.8.0", true),
    "Version 0.8.0 ist bereit. Die App startet nach der Installation neu. Das laufende Gespräch wird beendet.",
  );
  assert.ok(!OHNE_STRICH.test(hinweisSatz("0.8.0", true)));
});
