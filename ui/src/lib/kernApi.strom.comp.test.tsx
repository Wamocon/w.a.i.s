// Test des gestreamten Downloads am Kern (lib/kernApi.ts, kernDateiStrom) für den Installer: Fortschritt, gleiche Regeln wie jede
// Anfrage an den Kern (Token, kein Cache, keine Cookies, keine Umleitung), Abbruch, Größengrenze und Fehler mit Code.
// Das Netz ist eine Attrappe (fetch), es geht nichts hinaus. Ausführen im Ordner ui/:  npm run test:komponenten
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({ getSupabase: () => null, accessToken: async () => "token-der-sitzung" }));
vi.mock("@/lib/anmeldung", () => ({ merkeAbmeldeGrund: () => undefined }));
vi.mock("@/lib/betriebsart", async (orig) => ({
  ...(await orig<typeof import("@/lib/betriebsart")>()),
  betriebsartAktuell: () => "buero",
  kernUrl: () => "https://kern.test",
}));

import { KernFehler, kernDateiStrom } from "@/lib/kernApi";

function strom(teile: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(c) {
      for (const t of teile) c.enqueue(t);
      c.close();
    },
  });
}

const fetchAttrappe = vi.fn<typeof fetch>();

beforeEach(() => {
  fetchAttrappe.mockReset();
  vi.stubGlobal("fetch", fetchAttrappe);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("kernDateiStrom", () => {
  it("lädt in Stücken, meldet den Fortschritt und schickt die Anfrage wie jede andere an den Kern", async () => {
    fetchAttrappe.mockResolvedValue(
      new Response(strom([new Uint8Array([1, 2]), new Uint8Array([3, 4, 5]), new Uint8Array([6])]), {
        headers: { "Content-Length": "6" },
      }),
    );
    const fortschritt: [number, number | null][] = [];
    const bytes = await kernDateiStrom("/installer/datei", { hoechstens: 6, onFortschritt: (g, s) => fortschritt.push([g, s]) });
    expect([...bytes]).toEqual([1, 2, 3, 4, 5, 6]);
    expect(fortschritt).toEqual([
      [0, 6],
      [2, 6],
      [5, 6],
      [6, 6],
    ]);
    const [url, init] = fetchAttrappe.mock.calls[0];
    expect(url).toBe("https://kern.test/wamo/api/installer/datei");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer token-der-sitzung");
    expect(init?.cache).toBe("no-store");
    expect(init?.credentials).toBe("omit");
    expect(init?.redirect).toBe("error");
    expect(init?.signal).toBeInstanceOf(AbortSignal);
  });

  it("ohne Content-Length ist die Gesamtgröße unbekannt, die Bytes kommen trotzdem vollständig", async () => {
    fetchAttrappe.mockResolvedValue(new Response(strom([new Uint8Array([7]), new Uint8Array([8, 9])])));
    const gesamt: (number | null)[] = [];
    const bytes = await kernDateiStrom("/installer/datei", { hoechstens: 100, onFortschritt: (_g, s) => gesamt.push(s) });
    expect([...bytes]).toEqual([7, 8, 9]);
    expect(new Set(gesamt)).toEqual(new Set([null]));
  });

  it("kommen mehr Bytes als angekündigt (komprimiert übertragen), aber nicht mehr als erlaubt, kommen alle an", async () => {
    fetchAttrappe.mockResolvedValue(
      new Response(strom([new Uint8Array([1, 2]), new Uint8Array([3, 4]), new Uint8Array([5])]), { headers: { "Content-Length": "3" } }),
    );
    const bytes = await kernDateiStrom("/installer/datei", { hoechstens: 10 });
    expect([...bytes]).toEqual([1, 2, 3, 4, 5]);
  });

  it("kommen weniger Bytes als angekündigt, bleibt nur der gelesene Teil", async () => {
    fetchAttrappe.mockResolvedValue(new Response(strom([new Uint8Array([9, 8])]), { headers: { "Content-Length": "5" } }));
    const bytes = await kernDateiStrom("/installer/datei", { hoechstens: 10 });
    expect([...bytes]).toEqual([9, 8]);
  });

  it("eine angekündigte Größe über der Grenze bricht vor dem Lesen ab", async () => {
    fetchAttrappe.mockResolvedValue(new Response(strom([new Uint8Array(4)]), { headers: { "Content-Length": "4" } }));
    await expect(kernDateiStrom("/installer/datei", { hoechstens: 3 })).rejects.toMatchObject({ status: 413 });
  });

  it("mehr Bytes als erlaubt brechen beim Lesen ab", async () => {
    fetchAttrappe.mockResolvedValue(new Response(strom([new Uint8Array(2), new Uint8Array(2)])));
    const fehler = await kernDateiStrom("/installer/datei", { hoechstens: 3 }).catch((e: unknown) => e);
    expect(fehler).toBeInstanceOf(KernFehler);
    expect((fehler as KernFehler).status).toBe(413);
  });

  it("ein Abbruch von außen endet mit Abgebrochen, nicht mit Zeitüberschreitung", async () => {
    fetchAttrappe.mockImplementation(
      (_url, init) =>
        new Promise<Response>((_ok, nein) => {
          init?.signal?.addEventListener("abort", () => nein(new DOMException("abgebrochen", "AbortError")));
        }),
    );
    const steuerung = new AbortController();
    const laden = kernDateiStrom("/installer/datei", { hoechstens: 10, signal: steuerung.signal });
    await Promise.resolve();
    steuerung.abort();
    await expect(laden).rejects.toMatchObject({ status: 0, message: "Abgebrochen" });
  });

  it("ein schon abgebrochenes Signal ruft gar nicht erst an", async () => {
    const steuerung = new AbortController();
    steuerung.abort();
    await expect(kernDateiStrom("/installer/datei", { hoechstens: 10, signal: steuerung.signal })).rejects.toMatchObject({
      status: 0,
      message: "Abgebrochen",
    });
    expect(fetchAttrappe).not.toHaveBeenCalled();
  });

  it("ein Fehler des Kerns kommt mit Satz und Code an", async () => {
    fetchAttrappe.mockResolvedValue(
      new Response(JSON.stringify({ detail: "Zu viele Downloads.", code: "installer_zu_oft" }), { status: 429 }),
    );
    await expect(kernDateiStrom("/installer/datei", { hoechstens: 10 })).rejects.toMatchObject({
      status: 429,
      message: "Zu viele Downloads.",
      code: "installer_zu_oft",
    });
  });
});
