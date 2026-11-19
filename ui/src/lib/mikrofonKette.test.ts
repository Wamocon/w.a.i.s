// Tests für die Mikrofonkette im Protokoll (lib/mikrofonKette.ts, 19.11.2026): Klasse aus dem Gerätenamen, Lesen von getSettings(), Grenzen und
// null-Fälle, und der Melder, der je Änderung höchstens eine Nachricht freigibt. Festgehalten wird vor allem: nie der Name im Ergebnis.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  KANAELE_MAX,
  KANAELE_MIN,
  KLASSEN,
  KettenMelder,
  MAX_MELDUNGEN,
  RATE_MAX,
  RATE_MIN,
  klasseAusName,
  mikrofonInfo,
  type MikrofonInfo,
} from "./mikrofonKette.ts";

const SECHS_FELDER = ["echo", "rauschen", "verstaerkung", "rate", "kanaele", "klasse"];

// ---------- Klasse aus dem Namen ----------

test("Klasse: Bluetooth, Hands-Free, AirPods, Buds und Verwandte heißen bluetooth", () => {
  for (const name of [
    "Headset (WH-1000XM4 Hands-Free AG Audio)",
    "Hands-Free AG Audio",
    "Handsfree Telephony",
    "Bluetooth-Headset",
    "Kopfhörer (Bluetooth)",
    "Headset (AirPods Pro)",
    "AirPods Pro von Erika",
    "Galaxy Buds2 Pro",
    "Galaxy Buds Live",
    "FreeBuds Pro 3",
    "Headset (JBL TUNE 510BT Bluetooth)",
    "Freisprecheinrichtung",
    "Standard - Headset (Jabra Elite 75t Hands-Free)",
    "BT Headset",
    "Headset (A2DP SNK)",
  ]) {
    assert.equal(klasseAusName(name), "bluetooth", name);
  }
});

test("Klasse: Headset und Kopfhörer am Kabel heißen headset", () => {
  for (const name of [
    "Headset",
    "Headset Microphone (Realtek(R) Audio)",
    "Headset Earphone (Realtek High Definition Audio)",
    "Kommunikation - Headset (Jabra Evolve2 65)",
    "Kopfhörer",
    "Kopfhoerer (USB)",
    "Mikrofon (USB Headphones)",
    "Earbuds",
    "Sprechgarnitur",
    "Default - Headset (Logitech H340)",
  ]) {
    assert.equal(klasseAusName(name), "headset", name);
  }
});

test("Klasse: eingebaute Mikrofone heißen eingebaut", () => {
  for (const name of [
    "Mikrofonarray (Intel® Smart Sound Technologie für digitale Mikrofone)",
    "Microphone Array (Realtek(R) Audio)",
    "Standard - Mikrofonarray (Intel® Smart Sound Technology for Digital Microphones)",
    "Integriertes Mikrofon",
    "Internal Microphone",
    "Built-in Microphone",
    "Builtin Microphone",
    "MacBook Pro Microphone",
    "Onboard Mikrofon",
    "Eingebautes Mikrofon",
    "Mic Array",
    "Laptop Mikrofon",
    "FaceTime HD Camera (Built-in)",
    "Internes Mikrofon",
    "Smart Sound Microphone",
  ]) {
    assert.equal(klasseAusName(name), "eingebaut", name);
  }
});

test("Klasse: alles ohne erkennbares Wort heißt unbekannt", () => {
  for (const name of ["", " ", "Mikrofon", "Mikrofon (USB Audio Device)", "Microphone (Logitech BRIO)", "Blue Yeti", "default", "communications", "Rode NT-USB", "x"]) {
    assert.equal(klasseAusName(name), "unbekannt", JSON.stringify(name));
  }
});

test("Klasse: Groß- und Kleinschreibung zählt nicht", () => {
  assert.equal(klasseAusName("BLUETOOTH HEADSET"), "bluetooth");
  assert.equal(klasseAusName("bUiLt-In mIcRoPhOnE"), "eingebaut");
  assert.equal(klasseAusName("HEADSET"), "headset");
});

test("Klasse: Bluetooth gewinnt gegen Headset und eingebaut, Headset gegen eingebaut", () => {
  assert.equal(klasseAusName("Headset (Intel Bluetooth)"), "bluetooth");
  assert.equal(klasseAusName("Headset Microphone (Realtek Audio)"), "headset");
  assert.equal(klasseAusName("Intel Hands-Free"), "bluetooth");
});

test("Klasse: Wörter, die nur so aussehen, zählen nicht (Teile anderer Wörter)", () => {
  assert.equal(klasseAusName("Internationales Mikrofon"), "unbekannt");
  assert.equal(klasseAusName("Arrayless Mikrofon"), "unbekannt");
  assert.equal(klasseAusName("Rebuds Studio"), "unbekannt");
  assert.equal(klasseAusName("Abt Audio"), "unbekannt");
});

test("Klasse: kein Text ergibt unbekannt, auch kein Wurf", () => {
  for (const wert of [null, undefined, 0, 1, true, false, {}, [], ["Bluetooth"], () => "Bluetooth", Symbol("x")]) {
    assert.equal(klasseAusName(wert), "unbekannt", String(typeof wert));
  }
});

test("Klasse: unbekannt ist besser als falsch (Realtek allein, Klinke am Desktop, USB-Audio)", () => {
  for (const name of ["Mikrofon (Realtek(R) Audio)", "Line In (Realtek)", "USB High Definition Audio Device", "Realtek High Definition Audio"]) {
    assert.equal(klasseAusName(name), "unbekannt", name);
  }
});

test("Klasse: Bluetooth-Marken ohne Stichwort im Namen (der gemessene Fall: Sony, Jabra, Beats)", () => {
  for (const name of ["WH-1000XM4", "WF-1000XM5", "Sony WH-1000XM3", "Jabra Elite 85t", "Beats Studio Buds Plus", "Beats Flex"]) {
    assert.equal(klasseAusName(name), "bluetooth", name);
  }
});

test("Klasse: zusammengesetztes und getrenntes Umlautzeichen (NFC) ergeben dasselbe", () => {
  assert.equal(klasseAusName("Kopfhörer"), "headset");
  assert.equal(klasseAusName("Kopfhörer"), "headset");
});

test("Klasse: das Ergebnis ist immer eine der vier festen Klassen", () => {
  for (const name of ["Sony WH-1000XM4 Bluetooth", "Erikas AirPods", "irgendwas", "Mikrofon (Realtek)", "", "\u0000​\ud800"]) {
    assert.ok((KLASSEN as readonly string[]).includes(klasseAusName(name)), name);
  }
});

test("Klasse: Wiederholungen, die ein Muster zum Ausufern bringen könnten, kosten keine Zeit", () => {
  const start = Date.now();
  for (const name of ["hands ".repeat(40), "buds".repeat(50), "bt ".repeat(66), "wh-".repeat(66), "intern".repeat(33), "mic ".repeat(50), "a".repeat(199) + "!"]) {
    klasseAusName(name);
  }
  assert.ok(Date.now() - start < 200);
});

test("Klasse: ein sehr langer Name braucht keine Zeit und wird nur vorn gelesen", () => {
  const lang = "x".repeat(1_000_000);
  const start = Date.now();
  assert.equal(klasseAusName(lang), "unbekannt");
  assert.equal(klasseAusName(`${lang}bluetooth`), "unbekannt"); // hinter der Grenze von 200 Zeichen: nicht mehr gelesen
  assert.equal(klasseAusName(`bluetooth${lang}`), "bluetooth");
  assert.ok(Date.now() - start < 500);
});

// ---------- Lesen der Spur ----------

const VOLL = { echoCancellation: true, noiseSuppression: false, autoGainControl: true, sampleRate: 48000, channelCount: 1 };
const spur = (settings: unknown, label: unknown = "Mikrofonarray (Intel Smart Sound)") => ({ label, getSettings: () => settings });

test("mikrofonInfo: liest die fünf Zahlen und die Klasse", () => {
  assert.deepEqual(mikrofonInfo(spur(VOLL, "Headset (AirPods Pro)")), {
    echo: true,
    rauschen: false,
    verstaerkung: true,
    rate: 48000,
    kanaele: 1,
    klasse: "bluetooth",
  });
});

test("mikrofonInfo: genau sechs Felder, nie ein Name oder eine Kennung", () => {
  const info = mikrofonInfo({ ...spur({ ...VOLL, deviceId: "abc123", groupId: "g1", label: "Geheim" }, "Sony WH-1000XM4 Bluetooth") });
  assert.deepEqual(Object.keys(info).sort(), [...SECHS_FELDER].sort());
  const text = JSON.stringify(info);
  for (const name of ["Sony", "WH-1000", "abc123", "g1", "Geheim", "XM4"]) assert.ok(!text.includes(name), name);
});

test("mikrofonInfo: fehlende Werte sind null", () => {
  assert.deepEqual(mikrofonInfo(spur({}, "")), { echo: null, rauschen: null, verstaerkung: null, rate: null, kanaele: null, klasse: "unbekannt" });
});

test("mikrofonInfo: ohne Spur oder mit Unsinn sind alle Felder null, ohne Wurf", () => {
  const leer = { echo: null, rauschen: null, verstaerkung: null, rate: null, kanaele: null, klasse: "unbekannt" };
  assert.deepEqual(mikrofonInfo(null), leer);
  assert.deepEqual(mikrofonInfo(undefined), leer);
  assert.deepEqual(mikrofonInfo({}), leer);
  for (const roh of [null, undefined, 5, "text", true, [], () => 1]) assert.deepEqual(mikrofonInfo({ getSettings: () => roh }), leer, String(roh));
});

test("mikrofonInfo: wirft getSettings, bleiben die Zahlen null, die Klasse kommt trotzdem aus dem Namen", () => {
  const info = mikrofonInfo({
    label: "Bluetooth Headset",
    getSettings: () => {
      throw new Error("kaputt");
    },
  });
  assert.deepEqual(info, { echo: null, rauschen: null, verstaerkung: null, rate: null, kanaele: null, klasse: "bluetooth" });
});

test("mikrofonInfo: wirft der Zugriff auf ein einzelnes Feld, ist nur dieses Feld null", () => {
  const settings = {
    echoCancellation: true,
    get noiseSuppression(): boolean {
      throw new Error("kaputt");
    },
    autoGainControl: false,
    sampleRate: 44100,
    channelCount: 2,
  };
  assert.deepEqual(mikrofonInfo(spur(settings, "Mikrofonarray (Intel Smart Sound)")), {
    echo: true,
    rauschen: null,
    verstaerkung: false,
    rate: 44100,
    kanaele: 2,
    klasse: "eingebaut",
  });
});

test("mikrofonInfo: wirft der Zugriff auf den Namen, bleiben die Zahlen erhalten und die Klasse ist unbekannt", () => {
  const info = mikrofonInfo({
    getSettings: () => VOLL,
    get label(): string {
      throw new Error("kaputt");
    },
  });
  assert.deepEqual(info, { echo: true, rauschen: false, verstaerkung: true, rate: 48000, kanaele: 1, klasse: "unbekannt" });
});

test("mikrofonInfo: Schalter sind nur wahr oder falsch, alles andere ist null", () => {
  for (const wert of ["all", "true", 1, 0, [], {}, null, undefined]) {
    const info = mikrofonInfo(spur({ echoCancellation: wert, noiseSuppression: wert, autoGainControl: wert }));
    assert.deepEqual([info.echo, info.rauschen, info.verstaerkung], [null, null, null], String(wert));
  }
});

test("mikrofonInfo: Rate in den Grenzen, sonst null", () => {
  for (const rate of [RATE_MIN, 16000, 44100, 48000, 96000, RATE_MAX]) assert.equal(mikrofonInfo(spur({ sampleRate: rate })).rate, rate);
  for (const rate of [0, -1, RATE_MIN - 1, RATE_MAX + 1, 44100.5, NaN, Infinity, -Infinity, "48000", null, undefined, true, [], {}]) {
    assert.equal(mikrofonInfo(spur({ sampleRate: rate })).rate, null, String(rate));
  }
});

test("mikrofonInfo: Kanäle von 1 bis 8, sonst null", () => {
  for (const k of [KANAELE_MIN, 2, 4, KANAELE_MAX]) assert.equal(mikrofonInfo(spur({ channelCount: k })).kanaele, k);
  for (const k of [0, -1, KANAELE_MAX + 1, 100, 1.5, NaN, Infinity, "2", null, undefined, true, []]) {
    assert.equal(mikrofonInfo(spur({ channelCount: k })).kanaele, null, String(k));
  }
});

// ---------- Melder ----------

const info = (klasse: MikrofonInfo["klasse"] = "bluetooth", rate: number | null = 48000): MikrofonInfo => ({
  echo: true,
  rauschen: true,
  verstaerkung: true,
  rate,
  kanaele: 1,
  klasse,
});

test("Melder: ohne Meldung gibt es nichts", () => {
  assert.equal(new KettenMelder().abholen(), null);
});

test("Melder: eine Spur ergibt genau eine Nachricht", () => {
  const m = new KettenMelder();
  m.merken(info());
  assert.deepEqual(m.abholen(), info());
  assert.equal(m.abholen(), null);
  assert.equal(m.abholen(), null);
});

test("Melder: dieselbe Kette noch einmal (Mikrofon aus und an, neue Spur desselben Geräts) sendet nichts", () => {
  const m = new KettenMelder();
  m.merken(info());
  assert.ok(m.abholen());
  m.merken(info());
  assert.equal(m.abholen(), null);
  m.merken({ ...info() });
  assert.equal(m.abholen(), null);
});

test("Melder: eine geänderte Kette wird gesendet, auch der Rückweg auf die vorige", () => {
  const m = new KettenMelder();
  m.merken(info("bluetooth"));
  assert.equal(m.abholen()?.klasse, "bluetooth");
  m.merken(info("eingebaut", 44100));
  assert.equal(m.abholen()?.klasse, "eingebaut");
  m.merken(info("bluetooth"));
  assert.equal(m.abholen()?.klasse, "bluetooth");
});

test("Melder: vor der Freigabe ersetzt die neuere Spur die ältere, gesendet wird nur die jüngste", () => {
  const m = new KettenMelder();
  m.merken(info("eingebaut"));
  m.merken(info("headset"));
  m.merken(info("bluetooth"));
  assert.equal(m.abholen()?.klasse, "bluetooth");
  assert.equal(m.abholen(), null);
});

test("Melder: höchstens MAX_MELDUNGEN je Verbindung, auch bei lauter verschiedenen Ketten", () => {
  const m = new KettenMelder();
  let gesendet = 0;
  for (let i = 0; i < MAX_MELDUNGEN * 5; i += 1) {
    m.merken(info("bluetooth", RATE_MIN + i));
    if (m.abholen()) gesendet += 1;
  }
  assert.equal(gesendet, MAX_MELDUNGEN);
});

test("Melder: ein neuer Melder fängt neu an (neue Verbindung, neue Sitzung im Kern)", () => {
  const a = new KettenMelder();
  a.merken(info());
  assert.ok(a.abholen());
  const b = new KettenMelder();
  b.merken(info());
  assert.deepEqual(b.abholen(), info());
});
