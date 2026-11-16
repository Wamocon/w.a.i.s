// Komponententest der Tür (components/LoginGate.tsx) für die Erstanmeldung: Nach dem zweiten Faktor fragt sie den Stand beim Kern.
// offen zeigt den geführten Ablauf (Passwortwechsel über die Route des Kerns, nie updateUser, danach signOut für die anderen Sitzungen, weiter erst bei erledigt),
// abgelaufen nur den Satz, keine oder erledigt die App wie bisher. insufficient_aal führt zurück zur Code-Abfrage, die den Warnsatz
// trägt (die Ersteinrichtung mit QR-Code nicht). Laborkonten fragen gar nicht erst.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LoginGate } from "@/components/LoginGate";
import { ablaufMerkerGesetzt, ablaufMerkerSetzen, SATZ_ABGELAUFEN, WARNSATZ_CODE, type ErstanmeldungStand } from "@/lib/erstanmeldung";

const umgebung = vi.hoisted(() => {
  // LoginGate liest die Einrichtung beim Laden des Moduls
  process.env.NEXT_PUBLIC_SUPABASE_URL = "https://auth.test";
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY = "publishable-test";
  return { supabase: null as unknown, standLaden: vi.fn(), passwortSetzen: vi.fn() };
});

vi.mock("@/lib/supabase", async (original) => ({
  ...(await original<typeof import("@/lib/supabase")>()),
  getSupabase: () => umgebung.supabase,
}));
vi.mock("@/lib/erstanmeldung", async (original) => ({
  ...(await original<typeof import("@/lib/erstanmeldung")>()),
  standLaden: umgebung.standLaden,
  passwortSetzen: umgebung.passwortSetzen,
}));
vi.mock("@/lib/betriebsart", async (original) => ({
  ...(await original<typeof import("@/lib/betriebsart")>()),
  betriebsartFuerStart: async () => "buero",
}));
vi.mock("@/lib/kernApi", async (original) => ({
  ...(await original<typeof import("@/lib/kernApi")>()),
  kernBasis: () => "https://kern.test",
}));
// Ein zweiter Schritt hinter dem Passwort, wie ihn die Schritte Token und Schlüssel später bringen
vi.mock("@/components/erstanmeldung/schritte", async (original) => {
  const echt = await original<typeof import("@/components/erstanmeldung/schritte")>();
  const Probe = ({ weiter }: { weiter: () => void }) =>
    createElement("div", null, createElement("p", null, "Inhalt probe"), createElement("button", { onClick: weiter }, "Weiter probe"));
  return {
    ERSTANMELDUNG_SCHRITTE: [...echt.ERSTANMELDUNG_SCHRITTE, { id: "probe", titel: "Probe", ueberspringbar: false, komponente: Probe }],
  };
});

const USER = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
const PASSWORT = "Ein-neues-Passwort-2026";

/** Unsigniertes Test-JWT mit frischem Anmeldezeitpunkt (die Tür liest das Alter der Anmeldung aus amr). */
function jwt(): string {
  const teil = (o: unknown) => btoa(JSON.stringify(o)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const jetzt = Math.floor(Date.now() / 1000);
  return `${teil({ alg: "ES256" })}.${teil({ aal: "aal2", amr: [{ method: "password", timestamp: jetzt }] })}.signatur`;
}

type Optionen = {
  email?: string;
  aal?: "aal1" | "aal2";
  faktoren?: { id: string }[];
};

function supabaseBauen(opt: Optionen = {}) {
  const session = { access_token: jwt(), user: { id: USER, email: opt.email ?? "person@wamocon.com" } };
  const hoerer: { rueckruf: ((ereignis: string) => void) | null } = { rueckruf: null };
  const auth = {
    /** Ereignis der Anmeldeschnittstelle auslösen (zum Beispiel SIGNED_OUT) */
    ereignis: (e: string) => hoerer.rueckruf?.(e),
    getSession: vi.fn(async (): Promise<{ data: { session: typeof session | null } }> => ({ data: { session } })),
    onAuthStateChange: vi.fn((rueckruf: (ereignis: string) => void) => {
      hoerer.rueckruf = rueckruf;
      setTimeout(() => rueckruf("INITIAL_SESSION"), 0);
      return { data: { subscription: { unsubscribe: vi.fn() } } };
    }),
    updateUser: vi.fn(async (): Promise<{ data: { user: object | null }; error: unknown }> => ({ data: { user: {} }, error: null })),
    signOut: vi.fn(async () => ({ error: null })),
    mfa: {
      getAuthenticatorAssuranceLevel: vi.fn(async () => ({ data: { currentLevel: opt.aal ?? "aal2" }, error: null })),
      listFactors: vi.fn(async () => ({ data: { totp: opt.faktoren ?? [{ id: "f-1" }], all: [] }, error: null })),
      challengeAndVerify: vi.fn(async () => ({ error: null })),
      unenroll: vi.fn(async () => ({})),
      enroll: vi.fn(async () => ({
        data: { id: "f-neu", totp: { qr_code: "data:image/svg+xml;utf-8,<svg xmlns='http://www.w3.org/2000/svg'/>", secret: "GEHEIMNIS" } },
        error: null,
      })),
    },
  };
  umgebung.supabase = { auth };
  return auth;
}

function stande(...folge: ErstanmeldungStand[]) {
  const liste = [...folge];
  umgebung.standLaden.mockImplementation(async () => (liste.length > 1 ? liste.shift() : liste[0]));
}

const app = () => screen.queryByText("APP");
const zeigeApp = () => render(<LoginGate>{() => <p>APP</p>}</LoginGate>);

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  umgebung.supabase = null;
  umgebung.standLaden.mockReset();
  umgebung.passwortSetzen.mockReset().mockResolvedValue({ ok: true, stand: "erledigt" });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Tür: Stand der Erstanmeldung nach dem zweiten Faktor", () => {
  it("keine: die App wie bisher; gefragt wird mit dem Kern des Büros und dem Token der Sitzung", async () => {
    supabaseBauen();
    stande("keine");
    zeigeApp();
    expect(await screen.findByText("APP")).toBeTruthy();
    expect(umgebung.standLaden).toHaveBeenCalledTimes(1);
    const [basis, token] = umgebung.standLaden.mock.calls[0] as [string, string];
    expect(basis).toBe("https://kern.test");
    expect(token.split(".")).toHaveLength(3);
  });

  it("erledigt ohne begonnenen Ablauf: die App", async () => {
    supabaseBauen();
    stande("erledigt");
    zeigeApp();
    expect(await screen.findByText("APP")).toBeTruthy();
  });

  it("abgelaufen: nur der Satz und Abmelden, keine App", async () => {
    const auth = supabaseBauen();
    stande("abgelaufen");
    const benutzer = userEvent.setup();
    zeigeApp();
    expect((await screen.findByRole("alert")).textContent).toBe(SATZ_ABGELAUFEN);
    expect(app()).toBeNull();
    expect(screen.queryByLabelText("Neues Passwort")).toBeNull();
    await benutzer.click(screen.getByRole("button", { name: "Abmelden" }));
    expect(auth.signOut).toHaveBeenCalledWith({ scope: "local" });
  });

  it("offen: der Ablauf mit Leiste und Passwortschritt, noch keine App", async () => {
    supabaseBauen();
    stande("offen");
    zeigeApp();
    expect(await screen.findByLabelText("Neues Passwort")).toBeTruthy();
    expect(app()).toBeNull();
    const leiste = within(screen.getByRole("list", { name: "Schritte der Erstanmeldung" })).getAllByRole("listitem");
    expect(leiste.map((p) => p.getAttribute("data-zustand"))).toEqual(["aktuell", "folgt"]);
    expect(ablaufMerkerGesetzt(USER)).toBe(true);
    expect(screen.getByRole("button", { name: "Abmelden" })).toBeTruthy();
  });

  it("ein Laborkonto fragt den Kern gar nicht erst: die App wie bisher", async () => {
    supabaseBauen({ email: "labor-03@wamo.test" });
    stande("offen"); // würde den Ablauf zeigen, wenn gefragt würde
    zeigeApp();
    expect(await screen.findByText("APP")).toBeTruthy();
    expect(umgebung.standLaden).not.toHaveBeenCalled();
  });

  it("ein Merker vom begonnenen Ablauf zeigt ihn auch nach dem Passwortwechsel (Stand erledigt) mit dem nächsten Schritt", async () => {
    supabaseBauen();
    stande("erledigt");
    ablaufMerkerSetzen(USER);
    zeigeApp();
    expect(await screen.findByText("Inhalt probe")).toBeTruthy();
    expect(screen.queryByLabelText("Neues Passwort")).toBeNull(); // Passwort ist schon geändert
    expect(app()).toBeNull();
  });

  it("der Merker eines anderen Kontos zählt nicht", async () => {
    supabaseBauen();
    stande("erledigt");
    ablaufMerkerSetzen("ein-anderes-konto");
    zeigeApp();
    expect(await screen.findByText("APP")).toBeTruthy();
  });
});

describe("Tür: überholte Läufe", () => {
  /** standLaden hängt, bis aufgeloest(...) gerufen wird. */
  function haengendeAbfrage() {
    let aufloesen: (s: ErstanmeldungStand) => void = () => undefined;
    umgebung.standLaden.mockImplementation(() => new Promise<ErstanmeldungStand>((ok) => (aufloesen = ok)));
    return async (stand: ErstanmeldungStand) => {
      await act(async () => {
        aufloesen(stand);
        await new Promise((r) => setTimeout(r, 30));
      });
    };
  }

  it("Abmelden, während die Abfrage hängt: danach erscheint weder die App noch der Ablauf", async () => {
    for (const stand of ["keine", "offen", "erledigt"] as const) {
      const auth = supabaseBauen();
      const aufloesen = haengendeAbfrage();
      const { unmount } = zeigeApp();
      await waitFor(() => expect(umgebung.standLaden).toHaveBeenCalled());
      act(() => auth.ereignis("SIGNED_OUT")); // die Sitzung wird noch gelesen, nur der Zähler der Läufe kann die Anzeige verhindern
      expect(await screen.findByRole("button", { name: "Anmelden" })).toBeTruthy();
      await aufloesen(stand);
      expect(app(), stand).toBeNull();
      expect(screen.queryByLabelText("Neues Passwort"), stand).toBeNull();
      expect(screen.getByRole("button", { name: "Anmelden" }), stand).toBeTruthy();
      unmount();
      umgebung.standLaden.mockReset();
    }
  });

  it("gehört die Sitzung nach der Abfrage einer anderen Person (neue user_id), wird weder die App noch der Ablauf gezeigt", async () => {
    const auth = supabaseBauen();
    const aufloesen = haengendeAbfrage();
    zeigeApp();
    await waitFor(() => expect(umgebung.standLaden).toHaveBeenCalled());
    auth.getSession.mockResolvedValue({
      data: { session: { access_token: jwt(), user: { id: "99999999-0000-0000-0000-000000000000", email: "andere@wamocon.com" } } },
    });
    await aufloesen("keine");
    expect(app()).toBeNull();
    expect(await screen.findByRole("button", { name: "Anmelden" })).toBeTruthy();
  });
});

describe("Tür: Ablauf neu aufsetzen und Merker", () => {
  it("kein_wechsel_noetig bei Stand erledigt: der Ablauf wird neu aufgesetzt und zeigt den nächsten Schritt statt des Passworts", async () => {
    stande("offen", "erledigt");
    umgebung.passwortSetzen.mockResolvedValue({ ok: false, status: 409, code: "kein_wechsel_noetig" });
    const auth = supabaseBauen();
    const benutzer = userEvent.setup();
    zeigeApp();
    await benutzer.type(await screen.findByLabelText("Neues Passwort"), PASSWORT);
    await benutzer.type(screen.getByLabelText("Neues Passwort wiederholen"), PASSWORT);
    await benutzer.click(screen.getByRole("button", { name: "Passwort ändern" }));
    expect(await screen.findByText("Inhalt probe")).toBeTruthy();
    expect(screen.queryByLabelText("Neues Passwort")).toBeNull();
    expect(app()).toBeNull();
    expect(auth.updateUser).not.toHaveBeenCalled();
  });

  it("der Merker verschwindet beim Abmelden (Knopf der Tür und Ereignis SIGNED_OUT)", async () => {
    stande("erledigt");
    ablaufMerkerSetzen(USER);
    const auth = supabaseBauen();
    const benutzer = userEvent.setup();
    zeigeApp();
    expect(await screen.findByText("Inhalt probe")).toBeTruthy();
    expect(ablaufMerkerGesetzt(USER)).toBe(true);
    await benutzer.click(screen.getByRole("button", { name: "Abmelden" }));
    expect(auth.signOut).toHaveBeenCalledWith({ scope: "local" });
    expect(ablaufMerkerGesetzt(USER)).toBe(false);
    // auch eine automatische Abmeldung (zu alt, vom Kern verlangt) räumt ihn weg
    ablaufMerkerSetzen(USER);
    act(() => auth.ereignis("SIGNED_OUT"));
    expect(ablaufMerkerGesetzt(USER)).toBe(false);
  });
});

describe("Tür: Passwortschritt im Ablauf", () => {
  async function bisPasswort() {
    const auth = supabaseBauen();
    const benutzer = userEvent.setup();
    zeigeApp();
    await screen.findByLabelText("Neues Passwort");
    const eingeben = async () => {
      await benutzer.type(screen.getByLabelText("Neues Passwort"), PASSWORT);
      await benutzer.type(screen.getByLabelText("Neues Passwort wiederholen"), PASSWORT);
    };
    const absenden = () => benutzer.click(screen.getByRole("button", { name: "Passwort ändern" }));
    return { auth, benutzer, eingeben, absenden };
  }

  it("ändert das Passwort über den Kern, beendet die anderen Sitzungen und geht bei erledigt zum nächsten Schritt, am Ende zur App", async () => {
    stande("offen");
    const { auth, benutzer, eingeben, absenden } = await bisPasswort();
    await eingeben();
    await absenden();
    expect(await screen.findByText("Inhalt probe")).toBeTruthy();
    expect(umgebung.passwortSetzen).toHaveBeenCalledTimes(1);
    const [basis, token, passwort] = umgebung.passwortSetzen.mock.calls[0] as [string, string, string];
    expect(basis).toBe("https://kern.test");
    expect(token.split(".")).toHaveLength(3);
    expect(passwort).toBe(PASSWORT);
    expect(auth.updateUser).not.toHaveBeenCalled();
    expect(auth.signOut).toHaveBeenCalledWith({ scope: "others" });
    expect(umgebung.standLaden).toHaveBeenCalledTimes(1); // nur die Tür: die Antwort des Kerns sagt erledigt
    expect(app()).toBeNull();
    await benutzer.click(screen.getByRole("button", { name: "Weiter probe" }));
    expect(await screen.findByText("APP")).toBeTruthy();
    expect(ablaufMerkerGesetzt(USER)).toBe(false);
  });

  it("bleibt beim Passwort, solange der Kern nicht erledigt meldet", async () => {
    stande("offen", "offen");
    umgebung.passwortSetzen.mockResolvedValue({ ok: true, stand: "keine" });
    const { eingeben, absenden } = await bisPasswort();
    await eingeben();
    await absenden();
    expect(await screen.findByText(/noch nicht bestätigt/)).toBeTruthy();
    expect(screen.queryByText("Inhalt probe")).toBeNull();
    expect(app()).toBeNull();
  });

  it("insufficient_aal führt zur Code-Abfrage mit Hinweis und Warnsatz; der Code bringt die Person zurück in den Ablauf", async () => {
    stande("offen");
    const { auth, benutzer, eingeben, absenden } = await bisPasswort();
    umgebung.passwortSetzen.mockResolvedValueOnce({ ok: false, status: 401, code: "insufficient_aal" });
    await eingeben();
    await absenden();
    expect(await screen.findByText("Gib den aktuellen Code aus deiner Authenticator-App ein.")).toBeTruthy();
    expect(screen.getByText(WARNSATZ_CODE)).toBeTruthy();
    expect((screen.getByRole("alert")).textContent).toMatch(/frischen Code/);
    expect(screen.queryByLabelText("Neues Passwort")).toBeNull();
    expect(auth.signOut).not.toHaveBeenCalled();
    // Code eingeben: weiter mit aal2, der Stand ist noch offen, also wieder der Ablauf
    await benutzer.type(screen.getByLabelText("Sechsstelliger Code"), "123456");
    await benutzer.click(screen.getByRole("button", { name: "Weiter" }));
    expect(await screen.findByLabelText("Neues Passwort")).toBeTruthy();
    expect(auth.mfa.challengeAndVerify).toHaveBeenCalledWith({ factorId: "f-1", code: "123456" });
  });

  it("abgelaufen während des Wechsels: die Tür zeigt den Satz zum abgelaufenen Startpasswort", async () => {
    stande("offen", "abgelaufen", "abgelaufen");
    umgebung.passwortSetzen.mockResolvedValue({ ok: true, stand: "keine" });
    const { eingeben, absenden } = await bisPasswort();
    await eingeben();
    await absenden();
    await waitFor(() => expect(screen.getAllByText(SATZ_ABGELAUFEN).length).toBeGreaterThan(0));
    expect(app()).toBeNull();
    expect(screen.queryByText("Inhalt probe")).toBeNull();
  });

  it("startpasswort_abgelaufen vom Kern: die Tür zeigt nur noch den Satz", async () => {
    stande("offen", "abgelaufen");
    umgebung.passwortSetzen.mockResolvedValue({ ok: false, status: 403, code: "startpasswort_abgelaufen" });
    const { eingeben, absenden } = await bisPasswort();
    await eingeben();
    await absenden();
    await waitFor(() => expect(screen.queryByLabelText("Neues Passwort")).toBeNull());
    expect((await screen.findByRole("alert")).textContent).toBe(SATZ_ABGELAUFEN);
    expect(app()).toBeNull();
  });
});

describe("Tür: Warnsatz auf dem Code-Bildschirm", () => {
  it("steht auf dem Bildschirm, der den Code einer schon eingerichteten App abfragt", async () => {
    supabaseBauen({ aal: "aal1" });
    zeigeApp();
    expect(await screen.findByText("Gib den aktuellen Code aus deiner Authenticator-App ein.")).toBeTruthy();
    expect(screen.getByText(WARNSATZ_CODE)).toBeTruthy();
    expect(WARNSATZ_CODE).toBe("Fragt W.A.I.S. nach einem Code, obwohl du noch keine App eingerichtet hast, melde dich sofort bei Niko.");
    expect(umgebung.standLaden).not.toHaveBeenCalled(); // vor dem zweiten Faktor wird nichts gefragt
  });

  it("steht nicht bei der Ersteinrichtung mit QR-Code", async () => {
    supabaseBauen({ aal: "aal1", faktoren: [] });
    zeigeApp();
    expect(await screen.findByText(/Scanne den QR-Code/)).toBeTruthy();
    expect(screen.queryByText(WARNSATZ_CODE)).toBeNull();
  });
});
