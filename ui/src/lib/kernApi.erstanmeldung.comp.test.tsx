// Test der Aufrufe am Kern (lib/kernApi.ts) bei 403 mit den Codes der Erstanmeldung: Statt des Profilsatzes steht ein Satz mit Hinweis auf
// neues Anmelden, und die Person wird lokal abgemeldet (die Anmeldemaske zeigt den Grund, nach dem Anmelden führt die Tür zum Wechsel).
// Jeder andere 403 bleibt, wie er war: Satz des Kerns, keine Abmeldung.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { KernFehler, kernJson } from "@/lib/kernApi";
import { nimmAbmeldeGrund } from "@/lib/anmeldung";
import { SATZ_ABGELAUFEN, SATZ_STARTPASSWORT_AENDERN } from "@/lib/erstanmeldung";

const umgebung = vi.hoisted(() => ({ signOut: vi.fn(async () => ({ error: null })) }));

vi.mock("@/lib/supabase", () => ({
  getSupabase: () => ({ auth: { signOut: umgebung.signOut, refreshSession: vi.fn(async () => ({ data: { session: null }, error: { message: "x" } })) } }),
  accessToken: async () => "tok",
}));
vi.mock("@/lib/betriebsart", () => ({
  betriebsartAktuell: () => "buero",
  kernUrl: () => "https://kern.test",
}));

function antwort(status: number, daten: unknown): Response {
  return new Response(JSON.stringify(daten), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  umgebung.signOut.mockClear();
  nimmAbmeldeGrund(); // alten Grund wegräumen
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function ablehnung(status: number, daten: unknown): Promise<KernFehler> {
  vi.stubGlobal("fetch", vi.fn(async () => antwort(status, daten)));
  try {
    await kernJson("/modellzugang");
  } catch (e) {
    return e as KernFehler;
  }
  throw new Error("kein Fehler");
}

describe("Kernaufruf: 403 der Erstanmeldung", () => {
  it("passwort_wechsel_noetig: Satz mit Hinweis auf neues Anmelden, lokale Abmeldung mit demselben Grund", async () => {
    const f = await ablehnung(403, { error: "nicht berechtigt", detail: "Bitte ändere zuerst dein Startpasswort.", code: "passwort_wechsel_noetig" });
    expect(f.status).toBe(403);
    expect(f.code).toBe("passwort_wechsel_noetig");
    expect(f.message).toBe(SATZ_STARTPASSWORT_AENDERN);
    expect(umgebung.signOut).toHaveBeenCalledWith({ scope: "local" });
    expect(nimmAbmeldeGrund()).toBe(SATZ_STARTPASSWORT_AENDERN);
  });

  it("startpasswort_abgelaufen: der Satz zum abgelaufenen Startpasswort, ebenfalls mit Abmeldung", async () => {
    const f = await ablehnung(403, { error: "nicht berechtigt", detail: SATZ_ABGELAUFEN, code: "startpasswort_abgelaufen" });
    expect(f.message).toBe(SATZ_ABGELAUFEN);
    expect(umgebung.signOut).toHaveBeenCalledWith({ scope: "local" });
    expect(nimmAbmeldeGrund()).toBe(SATZ_ABGELAUFEN);
  });

  it("ein anderer 403 behält den Satz des Kerns und meldet nicht ab", async () => {
    const f = await ablehnung(403, { error: "nicht berechtigt", detail: "Nur für Admins.", code: "zweiter_faktor_zu_alt" });
    expect(f.message).toBe("Nur für Admins.");
    expect(f.code).toBe("zweiter_faktor_zu_alt");
    expect(umgebung.signOut).not.toHaveBeenCalled();
    expect(nimmAbmeldeGrund()).toBeNull();
  });

  it("dieselben Codes bei einem anderen Status (zum Beispiel 500) lösen nichts aus", async () => {
    const f = await ablehnung(500, { detail: "Fehler", code: "passwort_wechsel_noetig" });
    expect(f.message).toBe("Fehler");
    expect(umgebung.signOut).not.toHaveBeenCalled();
  });
});
