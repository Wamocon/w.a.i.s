// Komponententest: PC-Steuerung aus dem Browser (components/einstellungen/Geraete.tsx, components/DateiHinweis.tsx, lib/pcSchalter.ts).
// Im Browser in der Betriebsart Büro sagt der Schalter ehrlich, dass er den Laptop aus dem Geräteregister steuert, nicht das Gerät des
// Browsers, und was nur die Desktop-App kann (Automatik beim Start, Lichtrahmen). Der Haken für die Automatik fehlt dort, weil er aus dem
// Browser nie wirkt. Gespeicherte Dateien liegen auf dem Laptop; "Öffnen" sagt das. In der Desktop-App bleibt alles wie bisher.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({ art: "buero" as "buero" | "unterwegs" }));

vi.mock("@/lib/supabase", () => ({ getSupabase: () => null, accessToken: async () => null }));
vi.mock("@/lib/betriebsart", async (orig) => ({
  ...(await orig<typeof import("@/lib/betriebsart")>()),
  useBetriebsart: () => h.art,
}));

import { DateiHinweis } from "@/components/DateiHinweis";
import { MailVersandHinweis } from "@/components/MailVersand";
import { GeraeteAbschnitt } from "@/components/einstellungen/Geraete";
import { nutzerSetzen } from "@/lib/nutzer";
import { HINWEIS_LAPTOP, HINWEIS_NUR_APP, HINWEIS_OHNE_SITZUNG, HINWEIS_OHNE_SITZUNG_FERN } from "@/lib/pcSchalter";
import { applyServerMessage, resetWamo, wamo } from "@/lib/wamo";

const ID = "0b7f3c1e-2d4a-4c55-9a10-1a2b3c4d5e6f";
type Fenster = { wamoDesktop?: unknown };

function desktop(an: boolean) {
  if (an) (window as unknown as Fenster).wamoDesktop = { isDesktop: true };
  else delete (window as unknown as Fenster).wamoDesktop;
}

function admin() {
  nutzerSetzen({ id: ID, email: "admin@wamo.test" });
  localStorage.setItem(`wamo.rolle.${ID}`, "admin");
}

const schalter = () => screen.queryByRole("switch", { name: /PC-Steuerung/ });
const autoHaken = () => screen.queryByRole("checkbox", { name: /automatisch einschalten/ });
/** Beschreibung des Schalters über aria-describedby (auch ein gesperrter Schalter nennt so seinen Grund). */
const beschreibung = (el: Element) =>
  (el.getAttribute("aria-describedby") ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent ?? "")
    .join(" ");

describe("PC-Steuerung aus dem Browser", () => {
  beforeEach(() => {
    resetWamo();
    localStorage.clear();
    nutzerSetzen({ id: null, email: null });
    h.art = "buero";
    desktop(false);
  });
  afterEach(() => desktop(false));

  it("Browser im Büro: Schalter da, der Hinweis nennt den Laptop und was nur die Desktop-App kann, kein Haken für die Automatik", () => {
    admin();
    render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    expect((schalter() as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText(HINWEIS_LAPTOP)).toBeTruthy();
    expect(screen.getByText(HINWEIS_NUR_APP)).toBeTruthy();
    expect(autoHaken()).toBeNull();
    expect(screen.queryByText(/nur in der Desktop-App verfügbar/)).toBeNull();
  });

  it("Browser im Büro ohne Sitzung: der Hinweis sagt, dass eine laufende Sitzung auf einem anderen Gerät endet", () => {
    admin();
    render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    expect(screen.getByText(HINWEIS_OHNE_SITZUNG_FERN)).toBeTruthy();
  });

  it("der Schalter nennt seine Hinweise auch als Beschreibung, gesperrt wie bedienbar", () => {
    admin();
    const { unmount } = render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    const text = beschreibung(schalter()!);
    expect(text).toContain(HINWEIS_OHNE_SITZUNG_FERN);
    expect(text).toContain(HINWEIS_LAPTOP);
    unmount();
    localStorage.setItem(`wamo.stillStart.${ID}`, "aus");
    render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    expect((schalter() as HTMLButtonElement).disabled).toBe(true);
    expect(beschreibung(schalter()!)).toMatch(/Still starten beim Tippen/);
  });

  it("gewählt Büro, aber die Sitzung läuft am lokalen Kern: kein Hinweis auf einen anderen Laptop, der Haken bleibt", () => {
    admin();
    act(() =>
      wamo.set((s) => ({
        ...s,
        presence: "idle",
        profil: { name: "Admin", rolle: "admin" },
        betrieb: { modus: "lokal", modelle: {}, pc: "verbunden", pcSteuerung: "aus" },
      })),
    );
    render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    expect(screen.queryByText(HINWEIS_LAPTOP)).toBeNull();
    expect(autoHaken()).toBeTruthy();
  });

  it("gewählt Unterwegs, aber die Sitzung läuft im Büro: der Hinweis auf den Laptop gilt", () => {
    h.art = "unterwegs";
    admin();
    act(() =>
      wamo.set((s) => ({
        ...s,
        presence: "idle",
        profil: { name: "Admin", rolle: "admin" },
        betrieb: { modus: "buero", modelle: {}, pc: "verbunden", pcSteuerung: "aus" },
      })),
    );
    render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    expect(screen.getByText(HINWEIS_LAPTOP)).toBeTruthy();
  });

  it("Browser im Büro mit Sitzung: der Hinweis auf den Laptop bleibt neben dem Ziel stehen", () => {
    admin();
    act(() =>
      wamo.set((s) => ({
        ...s,
        presence: "idle",
        profil: { name: "Admin", rolle: "admin" },
        betrieb: { modus: "buero", modelle: {}, pc: "verbunden", pcSteuerung: "aus", pcName: "WMC-H-04-NS" },
      })),
    );
    render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    expect(screen.getByText("gilt nur für diese Sitzung, Ziel WMC-H-04-NS")).toBeTruthy();
    expect(screen.getByText(HINWEIS_LAPTOP)).toBeTruthy();
  });

  it("Desktop-App im Büro: kein Hinweis auf den Laptop, der Haken für die Automatik bleibt", () => {
    desktop(true);
    admin();
    render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    expect(schalter()).toBeTruthy();
    expect(screen.queryByText(HINWEIS_LAPTOP)).toBeNull();
    expect(screen.queryByText(HINWEIS_NUR_APP)).toBeNull();
    expect(screen.queryByText(HINWEIS_OHNE_SITZUNG_FERN)).toBeNull();
    expect(screen.getByText(HINWEIS_OHNE_SITZUNG)).toBeTruthy();
    expect(autoHaken()).toBeTruthy();
  });

  it("Browser Unterwegs (Kern und Host auf diesem PC): kein Hinweis auf einen anderen Laptop", () => {
    h.art = "unterwegs";
    admin();
    render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    expect(schalter()).toBeTruthy();
    expect(screen.queryByText(HINWEIS_LAPTOP)).toBeNull();
  });

  it("Mitglieder sehen weder Schalter noch Hinweis", () => {
    nutzerSetzen({ id: ID, email: "mitglied@wamo.test" });
    localStorage.setItem(`wamo.rolle.${ID}`, "mitglied");
    render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    expect(schalter()).toBeNull();
    expect(screen.queryByText(HINWEIS_LAPTOP)).toBeNull();
  });

  it("Datei aus dem Canvas im Browser: der Hinweis sagt, dass sie auf dem Laptop liegt, 'Öffnen' öffnet sie dort", () => {
    const oeffnen = vi.fn(() => true);
    render(<DateiHinweis onOeffnen={oeffnen} />);
    act(() =>
      applyServerMessage({ type: "datei", ok: true, kennung: "0123456789abcdef", name: "Angebot.docx", format: "word", ordner: "Dokumente\\WAIS", geoeffnet: false }),
    );
    expect(screen.getByText("Angebot.docx liegt auf deinem Laptop in Dokumente\\WAIS.")).toBeTruthy();
    act(() => screen.getByRole("button", { name: "Am Laptop im Ordner zeigen" }).click());
    expect(oeffnen).toHaveBeenCalledExactlyOnceWith("0123456789abcdef");
  });

  it("Datei aus dem Canvas in der Desktop-App: Hinweis und Knopf wie bisher", () => {
    desktop(true);
    render(<DateiHinweis onOeffnen={vi.fn(() => true)} />);
    act(() =>
      applyServerMessage({ type: "datei", ok: true, kennung: "0123456789abcdef", name: "Angebot.docx", format: "word", ordner: "Dokumente\\WAIS", geoeffnet: false }),
    );
    expect(screen.getByText("Angebot.docx liegt in Dokumente\\WAIS.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Im Ordner zeigen" })).toBeTruthy();
  });
  it("Mail im neuen Outlook aus dem Browser: der Hinweis sagt, dass der Entwurf auf dem Laptop offen ist", () => {
    render(<MailVersandHinweis onZurueckholen={vi.fn(() => true)} />);
    act(() => wamo.set((s) => ({ ...s, mailVersand: { id: null, zustand: "entwurf", text: "Der Entwurf ist offen." } })));
    expect(screen.getByText("Der Entwurf ist offen.")).toBeTruthy();
    expect(screen.getByText("Der Entwurf ist in Outlook auf deinem Laptop offen, dort sendest du ihn.")).toBeTruthy();
  });

  it("Mail in der Desktop-App: kein Zusatz zum Laptop", () => {
    desktop(true);
    render(<MailVersandHinweis onZurueckholen={vi.fn(() => true)} />);
    act(() => wamo.set((s) => ({ ...s, mailVersand: { id: null, zustand: "entwurf", text: "Der Entwurf ist offen." } })));
    expect(screen.queryByText(/auf deinem Laptop/)).toBeNull();
  });
});
