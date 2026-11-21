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
  aktionenLaden,
  betriebLaden,
  checklisteLaden,
  checklistePunktAnlegen,
  ichLaden,
  kartenLaden,
  laborStandLaden,
  latenzLaden,
  plaetzeLaden,
  termineLaden,
  versionenLaden,
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
import { API, ID_FREIGABE, ID_TERMIN } from "./werkstattTestdaten";

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
    const f = await fange(freigabeAusfuehren(ID_FREIGABE));
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
    const schreiben = await fange(terminLoeschen(ID_TERMIN));
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
    fetchMock.mockImplementation(async (adresse: string) => antwort(200, adresse.includes("/protokolle") ? { stunden: 24, marken: [], stufen: [], zeilen: [] } : { tage: 30, zeilen: [] }));
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
      () => terminLoeschen("t-1"), // keine UUID
    ]) {
      expect(aufrufen).toThrow(WerkstattFehler);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("Schreibaufrufe: Methode, Rumpf und Pfad", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await terminLoeschen(ID_TERMIN);
    expect(aufruf(0).init.method).toBe("DELETE");
    expect(aufruf(0).adresse).toMatch(new RegExp(`/labor/termine/${ID_TERMIN}$`));
    await checklisteUmschalten(ID_TERMIN, 4, true);
    expect(aufruf(1).init.method).toBe("PATCH");
    expect(JSON.parse(String(aufruf(1).init.body))).toEqual({ erledigt: true });
    expect(aufruf(1).headers.get("Content-Type")).toBe("application/json");
    await plaetzeSpeichern(ID_TERMIN, [{ platz: 1, zweck: "besucher", kennung: "labor-01", gast: "Gast 1" }]);
    expect(JSON.parse(String(aufruf(2).init.body))).toEqual({ plaetze: [{ platz: 1, zweck: "besucher", kennung: "labor-01", gast: "Gast 1" }] });
    await zuordnungSpeichern(ID_TERMIN, { 2: ["W1", "A1"], 1: ["G1"] });
    expect(aufruf(3).adresse).toMatch(new RegExp(`/zuordnung\\?termin=${ID_TERMIN}$`));
    // der Dienst will ein Objekt Platz zu Karten (matrix_pruefen), keine Liste von Paaren
    expect(JSON.parse(String(aufruf(3).init.body))).toEqual({ zuordnung: { "1": ["G1"], "2": ["A1", "W1"] } });
    await karteLoeschen("W1");
    expect(aufruf(4).adresse).toMatch(/\/karten\/W1$/);
  });

  it("Termin anlegen schickt die Namen der Schnittstelle und liefert den Termin", async () => {
    fetchMock.mockResolvedValue(antwort(201, API.terminAntwort));
    const r = await terminAnlegen({ tag: "2026-12-05", beginn: null, ende: null, einwilligungVersion: 1, status: "entwurf", aufbewahrungBis: "2026-12-18" });
    expect(r.termin?.id).toBe(ID_TERMIN);
    expect(JSON.parse(String(aufruf().init.body))).toEqual({
      tag: "2026-12-05", beginn: null, ende: null, einwilligung_version: 1, status: "entwurf", aufbewahrung_bis: "2026-12-18",
    });
  });

  it("Karte ändern geht an die eigene Kennung, ohne Kennung und ohne Stand im Rumpf", async () => {
    fetchMock.mockResolvedValue(antwort(200, API.karteAntwort));
    const r = await karteAendern({
      id: "W1", gruppe: "Wissen", titel: "t", aufgabe: "a", erwartung: "e", fehler: null, lernziel: null,
      wissen: "keine", wissenstext: null, werkzeuge: ["Jira"], dauerMin: 3,
    });
    expect(r.karte?.id).toBe("W1");
    expect(aufruf().init.method).toBe("PUT");
    expect(aufruf().adresse).toMatch(/\/karten\/W1$/);
    const rumpf = JSON.parse(String(aufruf().init.body));
    expect(rumpf).toMatchObject({ gruppe: "Wissen", dauer_min: 3, werkzeuge: ["Jira"] });
    expect(rumpf).not.toHaveProperty("id");
    expect(rumpf).not.toHaveProperty("stand");
  });

  it("Karte anlegen: der Dienst vergibt die Kennung, die Antwort nennt sie", async () => {
    fetchMock.mockResolvedValue(antwort(201, { karte: { ...API.karteAntwort.karte, id: "W2" } }));
    const r = await karteAnlegen({
      id: "W1", gruppe: "Wissen", titel: "t", aufgabe: "a", erwartung: "e", fehler: null, lernziel: null,
      wissen: "keine", wissenstext: null, werkzeuge: [], dauerMin: 3,
    });
    expect(r.karte?.id).toBe("W2");
    expect(aufruf().init.method).toBe("POST");
    expect(aufruf().adresse).toMatch(/\/karten$/);
    expect(JSON.parse(String(aufruf().init.body))).not.toHaveProperty("id");
  });

  it("Veröffentlichen: Prüfung, Karte (verpackt in { karte }) und Ausführung", async () => {
    fetchMock.mockResolvedValueOnce(antwort(200, API.pruefen));
    expect(await kartenPruefen()).toEqual({ ok: true, probleme: [], zeichen: 1200 });
    expect(aufruf(0).init.method).toBe("POST");
    expect(aufruf(0).adresse).toMatch(/\/karten\/pruefen$/);
    fetchMock.mockResolvedValueOnce(antwort(201, API.freigabeKarte));
    expect(await freigabeKarteAnlegen()).toMatchObject({ id: ID_FREIGABE, aenderungen: 1, karten: ["W1"], basisVersion: 4 });
    expect(aufruf(1).adresse).toMatch(/\/karten\/karte$/);
    fetchMock.mockResolvedValueOnce(antwort(200, API.ausgefuehrt));
    expect(await freigabeAusfuehren(ID_FREIGABE)).toEqual({ version: 5, zeichen: 1200 });
    expect(aufruf(2).adresse).toMatch(new RegExp(`/karten/karte/${ID_FREIGABE}/ausfuehren$`));
  });
});

describe("Endpunkte mit den Antworten der echten API", () => {
  const FALL: [string, () => Promise<unknown>, unknown, string, (e: unknown) => void][] = [
    ["GET /ich", () => ichLaden(), API.ich, "/ich", (e) => expect(e).toMatchObject({ rolle: "admin", aal2AlterS: 42, erlaubt: true })],
    ["GET /betrieb", () => betriebLaden(), API.betrieb, "/betrieb", (e) => expect((e as { kern: unknown[] }).kern).toHaveLength(2)],
    ["GET /dashboard/sitzungen", () => sitzungenLaden(14), API.sitzungen, "/dashboard/sitzungen?tage=14", (e) => expect(e).toHaveLength(2)],
    ["GET /dashboard/latenz", () => latenzLaden(14), API.latenz, "/dashboard/latenz?tage=14", (e) => expect(e).toHaveLength(2)],
    ["GET /dashboard/aktionen", () => aktionenLaden(14), API.aktionen, "/dashboard/aktionen?tage=14", (e) => expect(e).toHaveLength(2)],
    ["GET /protokolle", () => protokolleLaden({ marke: "", stufe: "", stunden: 24 }), API.protokolle, "/protokolle?stunden=24", (e) => expect((e as { zeilen: unknown[] }).zeilen).toHaveLength(2)],
    ["GET /labor/stand", () => laborStandLaden(), API.laborStand, "/labor/stand", (e) => expect(e).toHaveLength(2)],
    ["GET /labor/termine", () => termineLaden(), API.termine, "/labor/termine", (e) => expect(e).toHaveLength(1)],
    ["GET .../plaetze", () => plaetzeLaden(ID_TERMIN), API.plaetze, `/labor/termine/${ID_TERMIN}/plaetze`, (e) => expect(e).toHaveLength(3)],
    ["GET .../checkliste", () => checklisteLaden(ID_TERMIN), API.checkliste, `/labor/termine/${ID_TERMIN}/checkliste`, (e) => expect(e).toHaveLength(2)],
    ["GET /karten", () => kartenLaden(), API.karten, "/karten", (e) => expect(e).toMatchObject({ version: 4 })],
    ["GET /karten/versionen", () => versionenLaden(), API.versionen, "/karten/versionen", (e) => expect(e).toHaveLength(1)],
    ["GET /zuordnung", () => zuordnungLaden(ID_TERMIN), API.zuordnung, `/zuordnung?termin=${ID_TERMIN}`, (e) => expect(e).toEqual({ 1: ["A1", "W1"], 2: ["W1"] })],
  ];

  it.each(FALL)("%s", async (_name, aufrufen, antwortKoerper, pfad, pruefen) => {
    fetchMock.mockResolvedValue(antwort(200, antwortKoerper));
    pruefen(await aufrufen());
    expect(aufruf().adresse).toBe(`${WERKSTATT_STANDARD_URL}/werkstatt/api${pfad}`);
    expect(aufruf().init.method).toBe("GET");
  });

  it("Schreibaufrufe nehmen die Antworten des Dienstes an (201, 200, { geloescht }, { punkt })", async () => {
    fetchMock.mockImplementation(async () => antwort(200, API.geloescht));
    expect(await terminLoeschen(ID_TERMIN)).toBe(true);
    expect(await karteLoeschen("W1")).toBe(true);
    fetchMock.mockImplementation(async () => antwort(200, API.punktAntwort));
    expect(await checklisteUmschalten(ID_TERMIN, 3, true)).toBe(true);
    expect(await checklistePunktAnlegen(ID_TERMIN, { titel: "Generalprobe", quelle: null, faellig: null })).toBe(true);
    fetchMock.mockImplementation(async () => antwort(200, API.plaetze));
    expect(await plaetzeSpeichern(ID_TERMIN, [{ platz: 1, zweck: "besucher", kennung: "labor-01", gast: "Gast 1" }])).toBe(true);
    fetchMock.mockImplementation(async () => antwort(200, API.zuordnung));
    expect(await zuordnungSpeichern(ID_TERMIN, { 1: ["W1"] })).toBe(true);
    const aufrufe = fetchMock.mock.calls.map(([adresse, init]) => `${(init as RequestInit).method} ${String(adresse).replace(WERKSTATT_STANDARD_URL, "")}`);
    expect(aufrufe).toEqual([
      `DELETE /werkstatt/api/labor/termine/${ID_TERMIN}`,
      "DELETE /werkstatt/api/karten/W1",
      `PATCH /werkstatt/api/labor/termine/${ID_TERMIN}/checkliste/3`,
      `POST /werkstatt/api/labor/termine/${ID_TERMIN}/checkliste`,
      `PUT /werkstatt/api/labor/termine/${ID_TERMIN}/plaetze`,
      `PUT /werkstatt/api/zuordnung?termin=${ID_TERMIN}`,
    ]);
  });

  it("die Fehlerantwort des Dienstes ({ code, text }) wird zum Fehlerbild mit Status", async () => {
    fetchMock.mockResolvedValue(antwort(410, API.fehler));
    await expect(freigabeAusfuehren(ID_FREIGABE)).rejects.toMatchObject({ code: "karte_abgelaufen", status: 410 });
  });
});
