// Test des API-Clients der Werkstatt (lib/werkstattApi.ts): Adresse, Token nur im Header, Fehlerbilder, Eingaben, Rümpfe.
// fetch und die Anmeldung (lib/supabase.ts) sind durch Attrappen ersetzt, es geht nichts ins Netz.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { accessToken, getSupabase } from "@/lib/supabase";
import {
  WERKSTATT_STANDARD_URL,
  WerkstattFehler,
  checklisteUmschalten,
  freigabeAusfuehren,
  freigabeKarteAnlegen,
  ichLaden,
  karteAendern,
  karteAnlegen,
  karteLoeschen,
  kartenPruefen,
  plaetzeSpeichern,
  protokolleLaden,
  sitzungenLaden,
  terminAnlegen,
  terminLoeschen,
  werkstattBasis,
  zuordnungLaden,
  zuordnungSpeichern,
} from "./werkstattApi";

vi.mock("@/lib/supabase", () => ({ accessToken: vi.fn(), getSupabase: vi.fn() }));

const TOKEN = "eyJ-geheim-token";
const fetchMock = vi.fn();

function antwort(status: number, daten?: unknown): Response {
  return new Response(daten === undefined ? null : JSON.stringify(daten), { status });
}
/** Der Fehler, mit dem ein Aufruf endet (der Test erwartet einen). */
const fange = (p: Promise<unknown>): Promise<WerkstattFehler> => p.then(() => { throw new Error("kein Fehler"); }, (e: unknown) => e as WerkstattFehler);
const aufruf = (n = 0) => {
  const [adresse, init] = fetchMock.mock.calls[n] as [string, RequestInit];
  return { adresse, init, headers: new Headers(init.headers) };
};

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.mocked(accessToken).mockResolvedValue(TOKEN);
  vi.mocked(getSupabase).mockReturnValue(null);
});
afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("Adresse", () => {
  it("nimmt ohne Einstellung die Standardadresse und hängt den festen Pfad an", async () => {
    fetchMock.mockResolvedValue(antwort(200, { rolle: "admin", aal2_alter_s: 5, erlaubt: true }));
    expect(await ichLaden()).toEqual({ rolle: "admin", aal2AlterS: 5, erlaubt: true });
    expect(aufruf().adresse).toBe(`${WERKSTATT_STANDARD_URL}/werkstatt/api/ich`);
  });

  it("nimmt aus der Einstellung nur den Ursprung, nie einen Pfad oder Zugangsdaten", () => {
    vi.stubEnv("NEXT_PUBLIC_WAMO_WERKSTATT_URL", "https://werkstatt.beispiel.test:55448/anderer/pfad?x=1");
    expect(werkstattBasis()).toBe("https://werkstatt.beispiel.test:55448");
    vi.stubEnv("NEXT_PUBLIC_WAMO_WERKSTATT_URL", "http://localhost:18095");
    expect(werkstattBasis()).toBe("http://localhost:18095");
    for (const schlecht of ["http://192.168.178.136:55448", "https://nutzer:pw@werkstatt.test", "kaputt", "ftp://x.test"]) {
      vi.stubEnv("NEXT_PUBLIC_WAMO_WERKSTATT_URL", schlecht);
      expect(() => werkstattBasis(), schlecht).toThrow(WerkstattFehler);
    }
  });

  it("eine unsichere Adresse sendet nichts", async () => {
    vi.stubEnv("NEXT_PUBLIC_WAMO_WERKSTATT_URL", "http://192.168.178.136:55448");
    await expect(ichLaden()).rejects.toMatchObject({ code: "nicht_eingerichtet" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("Token", () => {
  it("steht nur im Header, nie in der Adresse, im Rumpf oder im Fehlertext", async () => {
    fetchMock.mockResolvedValue(antwort(403, { code: "nicht_berechtigt", text: `Token ${TOKEN} ungültig` }));
    const fehler = await karteAnlegen({
      id: "K1", gruppe: "G", titel: "t", aufgabe: "a", erwartung: "e", fehler: null, lernziel: null,
      wissen: "keine", wissenstext: null, werkzeuge: [], dauerMin: 3,
    }).catch((e: unknown) => e);
    const { adresse, init, headers } = aufruf();
    expect(headers.get("Authorization")).toBe(`Bearer ${TOKEN}`);
    expect(adresse).not.toContain(TOKEN);
    expect(String(init.body)).not.toContain(TOKEN);
    expect(fehler).toBeInstanceOf(WerkstattFehler);
    expect((fehler as WerkstattFehler).message).not.toContain(TOKEN);
    expect(init).toMatchObject({ cache: "no-store", credentials: "omit", redirect: "error" });
  });

  it("ohne Token wird nichts gesendet", async () => {
    vi.mocked(accessToken).mockResolvedValue(null);
    await expect(ichLaden()).rejects.toMatchObject({ code: "nicht_angemeldet", status: 401 });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("bei 401 genau einmal mit erneuertem Token, danach Schluss", async () => {
    const erneuern = vi.fn().mockResolvedValue({ data: { session: { access_token: "neu" } }, error: null });
    vi.mocked(getSupabase).mockReturnValue({ auth: { refreshSession: erneuern } } as never);
    fetchMock.mockResolvedValueOnce(antwort(401, { code: "nicht_angemeldet" })).mockResolvedValueOnce(antwort(200, { rolle: "admin", erlaubt: true }));
    await ichLaden();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(aufruf(1).headers.get("Authorization")).toBe("Bearer neu");
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(antwort(401, { code: "nicht_angemeldet" }));
    await expect(ichLaden()).rejects.toMatchObject({ code: "nicht_angemeldet" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("Fehlerbilder", () => {
  it("jeder Fehler der Schnittstelle wird zu Code, Status und deutschem Satz", async () => {
    fetchMock.mockResolvedValue(antwort(410, { code: "karte_abgelaufen", text: "intern" }));
    const f = await fange(freigabeAusfuehren("k1"));
    expect(f).toMatchObject({ code: "karte_abgelaufen", status: 410 });
    expect(f.message).toMatch(/Karte ist abgelaufen/);
    fetchMock.mockResolvedValue(antwort(422, { code: "ungueltig", text: "Titel ist zu lang" }));
    const u = await fange(kartenPruefen());
    expect(u.message).toMatch(/nicht gültig\. Titel ist zu lang/);
  });

  it("kein Netz, falsche Form und kaputtes JSON sind eigene Fehler", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(ichLaden()).rejects.toMatchObject({ code: "netz" });
    // bei einem Schreibaufruf ist unklar, ob die Änderung angekommen ist
    const schreiben = await fange(terminLoeschen("t-1"));
    expect(schreiben.code).toBe("netz");
    expect(schreiben.message).toMatch(/Ob die Änderung angekommen ist, siehst du nach dem Neuladen/);
    const lesen = await fange(ichLaden());
    expect(lesen.message).not.toMatch(/Neuladen der Ansicht/);
    fetchMock.mockResolvedValue(antwort(200, { nichts: 1 }));
    await expect(ichLaden()).rejects.toMatchObject({ code: "antwort" });
    fetchMock.mockResolvedValue(new Response("<html>", { status: 200 }));
    await expect(ichLaden()).rejects.toMatchObject({ code: "antwort" });
    fetchMock.mockResolvedValue(new Response("kein json", { status: 502 }));
    await expect(ichLaden()).rejects.toMatchObject({ code: "nicht_verfuegbar", status: 502 });
  });

  it("ein Abbruch von außen ist ein eigener Fehler", async () => {
    const steuerung = new AbortController();
    steuerung.abort();
    await expect(ichLaden(steuerung.signal)).rejects.toMatchObject({ code: "abgebrochen" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("Aufrufe", () => {
  it("Abfragen: Tage und Stunden bleiben im Bereich, Filter nur in gültiger Form", async () => {
    // jeder Aufruf bekommt eine eigene Antwort: ein Rumpf lässt sich nur einmal lesen
    fetchMock.mockImplementation(async (adresse: string) => antwort(200, adresse.includes("/protokolle") ? { zeilen: [] } : { tage: [] }));
    await sitzungenLaden(99);
    expect(aufruf().adresse).toMatch(/\/dashboard\/sitzungen\?tage=30$/);
    await protokolleLaden({ marke: "wamo-core", stufe: "fehler", stunden: 24 });
    expect(aufruf(1).adresse).toMatch(/\/protokolle\?marke=wamo-core&stufe=fehler&stunden=24$/);
    await protokolleLaden({ marke: "", stufe: "", stunden: Number.NaN });
    expect(aufruf(2).adresse).toMatch(/\/protokolle\?stunden=1$/);
    // ein Filter, der nicht passt, wird nie still weggelassen
    expect(() => protokolleLaden({ marke: "../x y", stufe: "", stunden: 1 })).toThrow(WerkstattFehler);
    expect(() => protokolleLaden({ marke: "", stufe: "Fehler!", stunden: 1 })).toThrow(WerkstattFehler);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("Kennungen werden vor dem Senden geprüft, nichts Fremdes gelangt in den Pfad", async () => {
    for (const aufrufen of [
      () => terminLoeschen("../../x"),
      () => karteLoeschen("w1"),
      () => checklisteUmschalten("t1", -1, true),
      () => plaetzeSpeichern("a/b", []),
      () => zuordnungLaden("t 1"),
    ]) {
      expect(aufrufen).toThrow(WerkstattFehler);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("Schreibaufrufe: Methode, Rumpf und Pfad", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await terminLoeschen("t-1");
    expect(aufruf(0).init.method).toBe("DELETE");
    expect(aufruf(0).adresse).toMatch(/\/labor\/termine\/t-1$/);
    await checklisteUmschalten("t-1", 4, true);
    expect(aufruf(1).init.method).toBe("PATCH");
    expect(JSON.parse(String(aufruf(1).init.body))).toEqual({ erledigt: true });
    expect(aufruf(1).headers.get("Content-Type")).toBe("application/json");
    await plaetzeSpeichern("t-1", [{ platz: 1, zweck: "besucher", kennung: "labor-01", gast: "Gast 1" }]);
    expect(JSON.parse(String(aufruf(2).init.body))).toEqual({ plaetze: [{ platz: 1, zweck: "besucher", kennung: "labor-01", gast: "Gast 1" }] });
    await zuordnungSpeichern("t-1", { 2: ["W1", "A1"], 1: ["G1"] });
    expect(aufruf(3).adresse).toMatch(/\/zuordnung\?termin=t-1$/);
    expect(JSON.parse(String(aufruf(3).init.body))).toEqual({
      zuordnung: [{ platz: 1, karte_id: "G1" }, { platz: 2, karte_id: "A1" }, { platz: 2, karte_id: "W1" }],
    });
    await karteLoeschen("W1");
    expect(aufruf(4).adresse).toMatch(/\/karten\/W1$/);
  });

  it("Termin anlegen schickt die Namen der Schnittstelle und liefert den Termin", async () => {
    fetchMock.mockResolvedValue(
      antwort(201, { id: "t-9", tag: "2026-12-05", beginn: null, ende: null, einwilligung_version: 1, status: "entwurf", aufbewahrung_bis: "2026-12-18" }),
    );
    const r = await terminAnlegen({ tag: "2026-12-05", beginn: null, ende: null, einwilligungVersion: 1, status: "entwurf", aufbewahrungBis: "2026-12-18" });
    expect(r.termin?.id).toBe("t-9");
    expect(JSON.parse(String(aufruf().init.body))).toEqual({
      tag: "2026-12-05", beginn: null, ende: null, einwilligung_version: 1, status: "entwurf", aufbewahrung_bis: "2026-12-18",
    });
  });

  it("Karte ändern geht an die eigene Kennung, immer als Entwurf", async () => {
    fetchMock.mockResolvedValue(antwort(200, {}));
    const r = await karteAendern({
      id: "W2", gruppe: "G", titel: "t", aufgabe: "a", erwartung: "e", fehler: null, lernziel: null,
      wissen: "keine", wissenstext: null, werkzeuge: ["Jira"], dauerMin: 3,
    });
    expect(r.karte).toBeNull();
    expect(aufruf().init.method).toBe("PUT");
    expect(aufruf().adresse).toMatch(/\/karten\/W2$/);
    expect(JSON.parse(String(aufruf().init.body))).toMatchObject({ stand: "entwurf", dauer_min: 3, werkzeuge: ["Jira"] });
  });

  it("Veröffentlichen: Prüfung, Karte und Ausführung", async () => {
    fetchMock.mockResolvedValueOnce(antwort(200, { ok: true, probleme: [], zeichen: 1200 }));
    expect(await kartenPruefen()).toEqual({ ok: true, probleme: [], zeichen: 1200 });
    expect(aufruf(0).init.method).toBe("POST");
    fetchMock.mockResolvedValueOnce(antwort(201, { id: "k1", gilt_bis: "2026-11-20T10:05:00Z", ziel: { anzahl: 1, karten: ["W1"] } }));
    expect(await freigabeKarteAnlegen()).toMatchObject({ id: "k1", aenderungen: 1 });
    fetchMock.mockResolvedValueOnce(antwort(200, { version: 5, zeichen: 1200 }));
    expect(await freigabeAusfuehren("k1")).toEqual({ version: 5, zeichen: 1200 });
    expect(aufruf(2).adresse).toMatch(/\/karten\/karte\/k1\/ausfuehren$/);
  });
});
