// Hauptfenster: die Oberfläche darf nur ihren Zustand melden (Kanal "levels", für Energiesparschutz und Markierung), die
// Betriebsart (buero oder unterwegs) lesen und setzen und den Rechnernamen, den Windows-Datenschutzstatus des Mikrofons
// erfragen, (nur Büro) den Laptop einrichten, die Markierung für den Lichtrahmen melden (Zahlen und Gerätekennung, nie
// Titel), die Version der App lesen und ein vom Kern angebotenes Update prüfen und installieren lassen (update.js: Signatur,
// steigende Version, Rückfrage im Hauptprozess), sonst nichts. main.js prüft Absender und Werte.
const { contextBridge, ipcRenderer } = require("electron");

// Nur Text und ganze Zahlen gehen über die Brücke; main.js und geraet.js prüfen die Werte danach streng.
const text = (v) => (typeof v === "string" ? v.slice(0, 512) : "");
const zahlOderNull = (v) => (Number.isInteger(v) ? v : null);
const textOderNull = (v) => (typeof v === "string" ? v.slice(0, 512) : null);
const textBis = (v, max) => (typeof v === "string" ? v.slice(0, max) : "");

// Version der App (app.getVersion()), von main.js über additionalArguments mitgegeben; nur x.y.z, sonst fehlt sie
const VERSION = (() => {
  const arg = process.argv.find((a) => typeof a === "string" && a.startsWith("--wamo-version="));
  const v = arg ? arg.slice("--wamo-version=".length) : "";
  return /^\d{1,4}\.\d{1,4}\.\d{1,4}$/.test(v) ? v : undefined;
})();

/** Update-Angebot des Kerns auf zwei Texte begrenzen; main.js (update.js) prüft Signatur, Format und Version. */
const schmalesAngebot = (a) => ({ manifest: textBis(a?.manifest, 8192), signatur: textBis(a?.signatur, 128) });

/** Markierung des Lichtrahmens auf die festen Felder und ganze Zahlen verkleinern; main.js (lichtrahmen.js) prüft sie noch einmal. */
const rechteck = (r) => (r && typeof r === "object" ? { x: zahlOderNull(r.x), y: zahlOderNull(r.y), b: zahlOderNull(r.b), h: zahlOderNull(r.h) } : null);
const punkt = (p) => (p && typeof p === "object" ? { x: zahlOderNull(p.x), y: zahlOderNull(p.y) } : null);
function schmaleMarkierung(m) {
  return {
    art: text(m?.art),
    geraet: textOderNull(m?.geraet),
    rechner: textOderNull(m?.rechner),
    fenster: rechteck(m?.fenster),
    monitor: rechteck(m?.monitor),
    punkt: punkt(m?.punkt),
  };
}

/** Antwort des Kerns auf die Gerätebindung auf die bekannten Felder und einfache Typen verkleinern. */
function schmaleAntwort(a) {
  const z = a && typeof a === "object" && a.ziel && typeof a.ziel === "object" ? a.ziel : null;
  return {
    ergebnis: text(a?.ergebnis),
    status: text(a?.status),
    name: text(a?.name),
    kennung: textOderNull(a?.kennung),
    slot: zahlOderNull(a?.slot),
    stufe: text(a?.stufe),
    user_id: text(a?.user_id),
    ziel: z
      ? { benutzer: text(z.benutzer), host: text(z.host), socket: text(z.socket), hostschluessel: text(z.hostschluessel) }
      : null,
  };
}

contextBridge.exposeInMainWorld("wamoDesktop", {
  isDesktop: true,
  version: VERSION,
  // Nur der Zustand geht hinaus; Pegel, die ältere Oberflächen mitschicken, bleiben hier
  levels: (meldung) => ipcRenderer.send("levels", { zustand: text(meldung?.zustand) }),
  // Lichtrahmen ums Zielfenster und Welle am Klickpunkt: nur Zahlen, Art und Gerätekennung; gezeichnet wird nur auf dem
  // Laptop, der handelt (main.js vergleicht die Kennung mit geraet.json)
  markierung: (m) => ipcRenderer.send("markierung", schmaleMarkierung(m)),
  betriebsart: {
    lesen: () => ipcRenderer.invoke("betriebsart:lesen"),
    setzen: (art) => ipcRenderer.invoke("betriebsart:setzen", art === "buero" ? "buero" : "unterwegs"),
    abonnieren: (rueckruf) => {
      const hoerer = (_event, art) => rueckruf(art);
      ipcRenderer.on("betriebsart", hoerer);
      return () => ipcRenderer.removeListener("betriebsart", hoerer);
    },
  },
  rechnername: () => ipcRenderer.invoke("rechnername"),
  mikrofonStatus: () => ipcRenderer.invoke("mikrofon:status"),
  // Einrichtung des Laptops (nur Büro, geraet.js): nur einfache Werte gehen hinaus, der private Schlüssel bleibt im
  // Hauptprogramm. Antworten: { ok: true, ... } oder { ok: false, text }.
  geraet: {
    vorbereiten: () => ipcRenderer.invoke("geraet:vorbereiten"),
    signieren: (anfrage) => ipcRenderer.invoke("geraet:signieren", { nonce: text(anfrage?.nonce), userId: text(anfrage?.userId) }),
    aktivieren: (antwort) => ipcRenderer.invoke("geraet:aktivieren", schmaleAntwort(antwort)),
    status: () => ipcRenderer.invoke("geraet:status"),
  },
  // Updates (update.js): pruefen liefert { ok, version, neuer } oder { ok: false, text }; installieren fragt im Hauptprozess
  // nach, lädt mit dem Token nur von der festen Adresse des Kerns, prüft Größe und SHA-256 und startet erst dann den Installer
  update: {
    pruefen: (angebot) => ipcRenderer.invoke("update:pruefen", schmalesAngebot(angebot)),
    installieren: (auftrag) =>
      ipcRenderer.invoke("update:installieren", { ...schmalesAngebot(auftrag), token: textBis(auftrag?.token, 8192) }),
  },
});
