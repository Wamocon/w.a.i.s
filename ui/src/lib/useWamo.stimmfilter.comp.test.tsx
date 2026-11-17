// Komponententest des Stimmfilters im Chat links (lib/stimmFilter.ts, lib/useWamo.ts, components/kommando/Gespraech.tsx,
// components/Verlauf.tsx): Mit {"type": "stimme", "status": "bereit", "modus": "streng"} erscheint ein endgültiger Satz der Person erst nach
// dem Urteil des Kerns mit derselben zeit, ein verworfener nie; Rückfall nach 4 s ohne Urteil und sobald W.A.I.S. antwortet. Zwischenstände
// erscheinen dann nicht im Chat, getippter Text sofort. Ohne Filter (und für Laborkonten) bleibt alles wie bisher.
// Pipecat-Client und Transport sind Attrappen, es gibt kein Netz und kein Mikrofon.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, render, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Rueckrufe = Record<string, (...a: unknown[]) => void>;
type AttrappenClient = { opts: { callbacks: Rueckrufe } };

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

import { Gespraech } from "@/components/kommando/Gespraech";
import { Verlauf } from "@/components/Verlauf";
import { nutzerSetzen } from "@/lib/nutzer";
import { useWamo } from "@/lib/useWamo";
import { resetWamo, wamo } from "@/lib/wamo";

const NUTZER = "0b7f3c1e-2d4a-4c55-9a10-1a2b3c4d5e6f";
const T1 = "2026-11-17T10:00:01.100+00:00";
const T2 = "2026-11-17T10:00:03.200+00:00";
const clients = () => h.clients as AttrappenClient[];
const letzter = () => clients()[clients().length - 1];

const fluss = (ms = 10) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

/** Eine Sitzung ist bereit (Client da, "Bot bereit" gemeldet), daneben der Block "Gespräch" und der Verlauf wie in der linken Spalte. */
async function sitzung() {
  nutzerSetzen({ id: NUTZER, email: "niko@wamocon.com" });
  const r = renderHook(() => useWamo());
  expect(r.result.current.stillStarten?.()).toBe(true);
  await fluss();
  const c = letzter();
  await act(async () => {
    c.opts.callbacks.onBotReady({ version: "2.0.0" });
    wamo.set((s) => ({ ...s, betrieb: { modus: "buero", modelle: {}, pc: "aus" } }));
  });
  const ansicht = render(
    <>
      <Gespraech />
      <Verlauf offen={false} onSchliessen={() => undefined} />
    </>,
  );
  const du = () => ansicht.container.querySelector(".kz-zeile-mensch")?.textContent ?? "";
  const verlauf = () => [...ansicht.container.querySelectorAll(".verlauf-eintrag[data-wer='nutzer'] .verlauf-text")].map((e) => e.textContent);
  const rufe = (name: string, ...a: unknown[]) => act(async () => void c.opts.callbacks[name](...a));
  return {
    ...r,
    c,
    du,
    verlauf,
    kern: (nachricht: Record<string, unknown>) => rufe("onServerMessage", nachricht),
    hoert: (text: string, timestamp = T1, final = true) => rufe("onUserTranscript", { text, final, timestamp, user_id: "" }),
    llmBeginnt: () => rufe("onBotLlmStarted"),
    sprichtAn: () => rufe("onBotStartedSpeaking"),
  };
}

const FILTER_AN = { type: "stimme", status: "bereit", modus: "streng" } as const;
const urteil = (ergebnis: string, ignoriert: boolean, zeit: string) => ({ type: "stimme", ergebnis, wert: 0.8, modus: "streng", ignoriert, zeit });

describe("Stimmfilter im Chat links", () => {
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

  describe("Filter aus", () => {
    it("zeigt Zwischenstand und endgültigen Satz sofort, wie bisher", async () => {
      const s = await sitzung();
      await s.kern({ type: "stimme", status: "bereit", modus: "beobachten" });
      await s.hoert("Mach die", T1, false);
      expect(s.du()).toContain("Mach die");
      await s.hoert("Mach die Heizung an");
      expect(s.du()).toContain("Mach die Heizung an");
      await s.sprichtAn();
      expect(s.verlauf()).toEqual(["Mach die Heizung an"]);
    });

    it("ohne Abdruck (Stand fehlt) ebenso", async () => {
      const s = await sitzung();
      await s.kern({ type: "stimme", status: "fehlt", modus: "streng" });
      await s.hoert("Mach die Heizung an");
      expect(s.du()).toContain("Mach die Heizung an");
    });

    it("für ein Laborkonto ebenso, auch wenn der Kern Abdruck und Modus streng meldet", async () => {
      const s = await sitzung();
      await s.kern(FILTER_AN);
      act(() => nutzerSetzen({ id: NUTZER, email: "labor-03@wamo.test" }));
      await s.hoert("Mach die", T1, false);
      expect(s.du()).toContain("Mach die");
      await s.hoert("Mach die Heizung an");
      expect(s.du()).toContain("Mach die Heizung an");
    });
  });

  describe("Filter an", () => {
    it("hält den Satz zurück, bis das Urteil mit derselben zeit ignoriert false meldet", async () => {
      const s = await sitzung();
      await s.kern(FILTER_AN);
      await s.hoert("Mach die Heizung an");
      expect(s.du()).not.toContain("Heizung");
      await s.kern(urteil("eigen", false, T2)); // gehört zu einer anderen Äußerung
      expect(s.du()).not.toContain("Heizung");
      await s.kern(urteil("eigen", false, T1));
      expect(s.du()).toContain("Mach die Heizung an");
      await s.sprichtAn();
      expect(s.verlauf()).toEqual(["Mach die Heizung an"]);
    });

    it("verwirft den Satz still bei ignoriert true: nie im Chat, nie im Verlauf, auch nicht nach der Frist", async () => {
      const s = await sitzung();
      await s.kern(FILTER_AN);
      await s.hoert("Schließ die Tür");
      await s.kern(urteil("fremd", true, T1));
      expect(s.du()).not.toContain("Tür");
      await fluss(5000);
      expect(s.du()).not.toContain("Tür");
      await s.sprichtAn();
      expect(s.verlauf()).toEqual([]);
    });

    it("verwirft den Satz ebenso beim leeren Ersatztranskript des Kerns", async () => {
      const s = await sitzung();
      await s.kern(FILTER_AN);
      await s.hoert("Schließ die Tür");
      await s.hoert(" ");
      await fluss(5000);
      expect(s.du()).not.toContain("Tür");
    });

    it("Rückfall nach 4 s ohne passendes Urteil (älterer Kern ohne zeit): der Satz erscheint", async () => {
      const s = await sitzung();
      await s.kern(FILTER_AN);
      await s.hoert("Mach die Heizung an");
      await s.kern({ type: "stimme", ergebnis: "eigen", wert: 0.8, modus: "streng" });
      await fluss(3900);
      expect(s.du()).not.toContain("Heizung");
      await fluss(200);
      expect(s.du()).toContain("Mach die Heizung an");
    });

    it("Rückfall, sobald W.A.I.S. zu sprechen beginnt: der Satz erscheint und steht im Verlauf", async () => {
      const s = await sitzung();
      await s.kern(FILTER_AN);
      await s.hoert("Wie spät ist es");
      expect(s.du()).not.toContain("spät");
      await s.sprichtAn();
      expect(s.du()).toContain("Wie spät ist es");
      expect(s.verlauf()).toEqual(["Wie spät ist es"]);
    });

    it("Rückfall, sobald das Modell zu antworten beginnt", async () => {
      const s = await sitzung();
      await s.kern(FILTER_AN);
      await s.hoert("Wie spät ist es");
      await s.llmBeginnt();
      expect(s.du()).toContain("Wie spät ist es");
    });

    it("zeigt Zwischenstände nicht im Chat und nimmt sie nicht in den Verlauf", async () => {
      const s = await sitzung();
      await s.kern(FILTER_AN);
      await s.hoert("Schließ die", T1, false);
      expect(s.du()).not.toContain("Schließ");
      expect(s.du()).toContain("Noch nichts gesagt.");
      await s.hoert("Mach die Heizung an");
      await s.kern(urteil("eigen", false, T1));
      await s.hoert("und dann", T2, false);
      expect(s.du()).toContain("Mach die Heizung an");
      expect(s.du()).not.toContain("und dann");
      await s.sprichtAn();
      expect(s.verlauf()).toEqual(["Mach die Heizung an"]);
    });

    it("zeigt getippten Text sofort", async () => {
      const s = await sitzung();
      await s.kern(FILTER_AN);
      act(() => void s.result.current.textSenden?.("Wie spät ist es?"));
      await fluss();
      expect(s.du()).toContain("Wie spät ist es?");
    });
  });
});
