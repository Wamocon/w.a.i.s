// Komponententest der Aufträge an W.A.I.S. selbst in useWamo (lib/selbstAuftraege.ts): Die Liste wird einmal je Verbindung abgefragt, aber
// nur für ein Admin-Profil ohne Laborkonto; anlegen, verwerfen und wieder öffnen senden genau die Nachricht aus dem Vertrag, nur passend zur
// Liste und zum Status, und sperren, bis der Kern antwortet (oder die Frist abläuft); das Trennen der Sitzung nimmt den Block wieder weg.
// Pipecat-Client und Transport sind Attrappen, der Kern wird über Rückrufe nachgestellt; es gibt kein Netz.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Rueckrufe = Record<string, (...a: unknown[]) => void>;
type AttrappenClient = {
  opts: { callbacks: Rueckrufe };
  sendClientMessage: ReturnType<typeof vi.fn>;
};

const h = vi.hoisted(() => {
  (URL as unknown as { createObjectURL: (b: unknown) => string }).createObjectURL = () => "blob:wamo-test";
  return { clients: [] as unknown[] };
});

vi.mock("@pipecat-ai/client-js", () => {
  class RTVIError extends Error {
    status?: number;
  }
  class PipecatClient {
    opts: unknown;
    sendText = vi.fn().mockResolvedValue(undefined);
    enableMic = vi.fn();
    updateMic = vi.fn();
    sendClientMessage = vi.fn();
    disconnect = vi.fn().mockResolvedValue(undefined);
    startBotAndConnect = vi.fn(() => Promise.resolve());
    get transport() {
      return (this.opts as { transport: unknown }).transport;
    }
    constructor(opts: unknown) {
      this.opts = opts;
      h.clients.push(this);
    }
  }
  return { PipecatClient, RTVIError };
});
vi.mock("@pipecat-ai/small-webrtc-transport", () => {
  class WavMediaManager {}
  class SmallWebRTCTransport {
    opts: unknown;
    constructor(opts: unknown) {
      this.opts = opts;
    }
  }
  return { SmallWebRTCTransport, WavMediaManager };
});
vi.mock("@/lib/betriebsart", async (orig) => ({
  ...(await orig<typeof import("@/lib/betriebsart")>()),
  betriebsartFuerStart: async () => "buero",
  kernUrl: () => "https://kern.test",
}));
vi.mock("@/lib/kernSlot", async (orig) => ({ ...(await orig<typeof import("@/lib/kernSlot")>()), aktiverSlot: async () => null }));
vi.mock("@/lib/supabase", () => ({ getSupabase: () => null, accessToken: async () => null }));

import { nutzerSetzen } from "@/lib/nutzer";
import { SELBST_WARTEN_MS } from "@/lib/selbstAuftraege";
import { useWamo } from "@/lib/useWamo";
import { applyServerMessage, resetWamo, wamo } from "@/lib/wamo";

const NUTZER = "0b7f3c1e-2d4a-4c55-9a10-1a2b3c4d5e6f";
const clients = () => h.clients as AttrappenClient[];
const letzter = () => clients()[clients().length - 1];
const selbstGesendet = (c: AttrappenClient) => c.sendClientMessage.mock.calls.filter((a) => a[0] === "selbstauftrag");

const fluss = (ms = 10) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

const EINTRAG = { titel: "Der Verlauf lädt zu langsam", art: "fehlerbehebung", prioritaet: 1, quelle: "sprache", unsicher: false, erstellt_ms: 1_763_456_400_000 };
const LISTE = {
  type: "selbstauftraege",
  aktion: "liste",
  ok: true,
  max: 100,
  auftraege: [
    { ...EINTRAG, nr: 7, status: "offen" },
    { ...EINTRAG, nr: 8, status: "verworfen" },
    { ...EINTRAG, nr: 9, status: "erledigt" },
    { ...EINTRAG, nr: 10, status: "in_arbeit" },
  ],
};
const EINGABE = { titel: "Verlauf beschleunigen", beschreibung: "Der Verlauf soll schneller laden.", art: "fehlerbehebung", prioritaet: 1 } as const;

const vomKern = (c: AttrappenClient, nachricht: Record<string, unknown>) =>
  act(async () => {
    c.opts.callbacks.onServerMessage(nachricht);
  });

/** Eine Sitzung ist bereit (Client da, "Bot bereit"); Profil und Betriebsdaten kommen danach, wie beim Kern. */
async function sitzung(email = "niko@wamocon.com") {
  nutzerSetzen({ id: NUTZER, email });
  const r = renderHook(() => useWamo());
  expect(r.result.current.stillStarten?.()).toBe(true);
  await fluss();
  const c = letzter();
  await act(async () => {
    c.opts.callbacks.onBotReady({ version: "2.0.0" });
  });
  return { ...r, c };
}

const profilUndBetrieb = (rolle: "admin" | "mitglied" | null) =>
  act(async () => {
    if (rolle) applyServerMessage({ type: "profil", name: "Test Person", rolle });
    wamo.set((s) => ({ ...s, betrieb: { modus: "buero", modelle: {}, pc: "aus" } }));
  });

describe("useWamo, Aufträge an W.A.I.S. selbst: Abfrage der Liste", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    h.clients.length = 0;
    resetWamo();
    localStorage.clear();
    nutzerSetzen({ id: null, email: null });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("fragt als Admin einmal je Verbindung ab, erst wenn Betriebsmeldung und Profil da sind", async () => {
    const { c } = await sitzung();
    expect(selbstGesendet(c)).toHaveLength(0);
    await act(async () => wamo.set((s) => ({ ...s, betrieb: { modus: "buero", modelle: {}, pc: "aus" } })));
    expect(selbstGesendet(c)).toHaveLength(0); // ohne Profil noch nicht
    await act(async () => applyServerMessage({ type: "profil", name: "Test Person", rolle: "admin" }));
    expect(c.sendClientMessage).toHaveBeenCalledWith("selbstauftrag", { aktion: "liste" });
    await act(async () => wamo.set((s) => ({ ...s, micOn: !s.micOn })));
    await profilUndBetrieb("admin");
    expect(selbstGesendet(c)).toHaveLength(1);
  });

  it("fragt als Mitglied nie ab", async () => {
    const { c } = await sitzung();
    await profilUndBetrieb("mitglied");
    expect(selbstGesendet(c)).toHaveLength(0);
  });

  it("fragt in einem Laborkonto nie ab", async () => {
    const { c } = await sitzung();
    nutzerSetzen({ id: NUTZER, email: "labor-03@wamo.test" });
    await profilUndBetrieb("admin");
    expect(selbstGesendet(c)).toHaveLength(0);
  });

  it("der Block entsteht erst mit der Antwort mit Liste, ein Nein des Kerns lässt ihn weg", async () => {
    const { c } = await sitzung();
    await profilUndBetrieb("admin");
    expect(wamo.get().selbstAuftraege).toBeNull();
    await vomKern(c, { type: "selbstauftraege", aktion: "liste", ok: false, grund: "Das gibt es hier nicht." });
    expect(wamo.get().selbstAuftraege).toBeNull();
    await vomKern(c, LISTE);
    expect(wamo.get().selbstAuftraege?.liste.map((a) => a.nr)).toEqual([7, 8, 9, 10]);
  });

  it("das Trennen der Sitzung nimmt den Block weg", async () => {
    const { c, result } = await sitzung();
    await profilUndBetrieb("admin");
    await vomKern(c, LISTE);
    expect(wamo.get().selbstAuftraege).not.toBeNull();
    await act(async () => {
      await result.current.disconnect();
    });
    expect(wamo.get().selbstAuftraege).toBeNull();
  });
});

describe("useWamo, Aufträge an W.A.I.S. selbst: Aktionen", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    h.clients.length = 0;
    resetWamo();
    localStorage.clear();
    nutzerSetzen({ id: null, email: null });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  async function mitListe() {
    const s = await sitzung();
    await profilUndBetrieb("admin");
    await vomKern(s.c, LISTE);
    s.c.sendClientMessage.mockClear();
    return s;
  }

  it("ohne Antwort mit Liste sendet keine Aktion etwas", async () => {
    const { c, result } = await sitzung();
    await profilUndBetrieb("admin");
    c.sendClientMessage.mockClear();
    const a = result.current.selbstAuftraege!;
    expect(a.speichern(EINGABE)).toBe(false);
    expect(a.verwerfen(7)).toBe(false);
    expect(a.oeffnen(8)).toBe(false);
    expect(selbstGesendet(c)).toHaveLength(0);
  });

  it("speichern schickt genau den Vertrag (getrimmt), sperrt bis zur Antwort und gibt dann frei", async () => {
    const { c, result } = await mitListe();
    const a = result.current.selbstAuftraege!;
    let ok = false;
    act(() => {
      ok = a.speichern({ ...EINGABE, titel: "  Verlauf beschleunigen  ", beschreibung: "\nDer Verlauf soll schneller laden. " });
    });
    expect(ok).toBe(true);
    expect(c.sendClientMessage).toHaveBeenCalledWith("selbstauftrag", {
      aktion: "speichern",
      titel: "Verlauf beschleunigen",
      beschreibung: "Der Verlauf soll schneller laden.",
      art: "fehlerbehebung",
      prioritaet: 1,
    });
    expect(wamo.get().selbstAuftraege?.wartet?.aktion).toBe("speichern");
    // während die Antwort aussteht, geht nichts doppelt hinaus
    expect(a.speichern(EINGABE)).toBe(false);
    expect(a.verwerfen(7)).toBe(false);
    expect(selbstGesendet(c)).toHaveLength(1);
    await vomKern(c, { type: "selbstauftraege", aktion: "speichern", ok: true, text: "Gespeichert als SA-11.", auftraege: LISTE.auftraege, max: 100 });
    expect(wamo.get().selbstAuftraege?.wartet).toBeNull();
    expect(a.verwerfen(7)).toBe(true);
  });

  it("speichern prüft die Eingabe: leerer Titel, zu lange Beschreibung, unbekannte Art oder Priorität gehen nicht hinaus", async () => {
    const { c, result } = await mitListe();
    const a = result.current.selbstAuftraege!;
    expect(a.speichern({ ...EINGABE, titel: "   " })).toBe(false);
    expect(a.speichern({ ...EINGABE, beschreibung: "x".repeat(4001) })).toBe(false);
    expect(a.speichern({ ...EINGABE, art: "unfug" as never })).toBe(false);
    expect(a.speichern({ ...EINGABE, prioritaet: 4 as never })).toBe(false);
    expect(selbstGesendet(c)).toHaveLength(0);
    expect(wamo.get().selbstAuftraege?.wartet).toBeNull();
  });

  it("verwerfen nur für offene und laufende, wieder öffnen nur für verworfene Einträge der Liste", async () => {
    const { c, result } = await mitListe();
    const a = result.current.selbstAuftraege!;
    expect(a.verwerfen(9)).toBe(false); // erledigt
    expect(a.verwerfen(8)).toBe(false); // schon verworfen
    expect(a.verwerfen(99)).toBe(false); // nicht in der Liste
    expect(a.oeffnen(7)).toBe(false); // offen
    expect(a.oeffnen(9)).toBe(false); // erledigt
    expect(a.verwerfen(1.5)).toBe(false);
    expect(selbstGesendet(c)).toHaveLength(0);
    act(() => {
      expect(a.verwerfen(10)).toBe(true); // in Arbeit
    });
    expect(c.sendClientMessage).toHaveBeenCalledWith("selbstauftrag", { aktion: "verwerfen", nr: 10 });
    await vomKern(c, { type: "selbstauftraege", aktion: "verwerfen", ok: true, text: "Verworfen.", auftraege: LISTE.auftraege, max: 100 });
    act(() => {
      expect(a.oeffnen(8)).toBe(true);
    });
    expect(c.sendClientMessage).toHaveBeenLastCalledWith("selbstauftrag", { aktion: "oeffnen", nr: 8 });
  });

  it("kommt keine Antwort, gibt die Frist frei und sagt es", async () => {
    const { result } = await mitListe();
    const a = result.current.selbstAuftraege!;
    act(() => {
      a.verwerfen(7);
    });
    expect(wamo.get().selbstAuftraege?.wartet).not.toBeNull();
    await fluss(SELBST_WARTEN_MS + 10);
    expect(wamo.get().selbstAuftraege?.wartet).toBeNull();
    expect(wamo.get().selbstAuftraege?.verspaetet).toBe("verwerfen");
    expect(wamo.get().toast?.text).toMatch(/Aufträge an W\.A\.I\.S\.: noch keine Antwort vom Kern/);
  });

  it("die späte Antwort des ersten Versuchs entsperrt den zweiten nicht, erst seine eigene Antwort tut es", async () => {
    const { c, result } = await mitListe();
    const a = result.current.selbstAuftraege!;
    act(() => {
      a.verwerfen(7);
    });
    await fluss(SELBST_WARTEN_MS + 10); // Frist abgelaufen, keine Antwort
    act(() => {
      expect(a.verwerfen(7)).toBe(true); // zweiter Versuch
    });
    expect(selbstGesendet(c)).toHaveLength(2);
    const antwortVerwerfen = { type: "selbstauftraege", aktion: "verwerfen", ok: true, text: "Verworfen.", auftraege: LISTE.auftraege, max: 100 };
    await vomKern(c, antwortVerwerfen); // die späte Antwort des ersten Versuchs
    expect(wamo.get().selbstAuftraege?.wartet?.aktion).toBe("verwerfen");
    expect(a.verwerfen(10)).toBe(false); // weiter gesperrt
    await vomKern(c, antwortVerwerfen); // die Antwort des zweiten Versuchs
    expect(wamo.get().selbstAuftraege?.wartet).toBeNull();
    expect(wamo.get().selbstAuftraege?.verspaetet).toBeNull();
  });

  it("ohne Verbindung geht nichts hinaus, mit Hinweis", async () => {
    const { result } = await mitListe();
    const a = result.current.selbstAuftraege!;
    act(() => wamo.set((s) => ({ ...s, presence: "offline" })));
    let ok = true;
    act(() => {
      ok = a.verwerfen(7);
    });
    expect(ok).toBe(false);
    expect(wamo.get().toast?.text).toMatch(/keine Verbindung/);
  });
});
