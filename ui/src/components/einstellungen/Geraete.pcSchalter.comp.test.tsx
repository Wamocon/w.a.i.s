// Komponententest des Schalters "PC-Steuerung" ohne laufendes Gespräch (components/einstellungen/Geraete.tsx, lib/pcSchalter.ts):
// In der Desktop-App ist er für Admins auch ohne Sitzung bedienbar (die Rolle kommt dann aus der gemerkten Rolle dieser Person), im
// normalen Browser bleibt er ohne Gespräch gesperrt, Laborkonten und Mitglieder sehen ihn nie. Wartet ein Klick auf Sitzung und PC,
// ist er gesperrt und sagt es; ein Hinweis nach der Wartezeit steht am Schalter.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({ getSupabase: () => null, accessToken: async () => null }));

import { GeraeteAbschnitt } from "@/components/einstellungen/Geraete";
import { nutzerSetzen } from "@/lib/nutzer";
import { HINWEIS_IM_GESPRAECH, HINWEIS_OHNE_SITZUNG, HINWEIS_PC_GETRENNT, HINWEIS_STILL_AUS, TEXT_WARTET } from "@/lib/pcSchalter";
import { resetWamo, wamo } from "@/lib/wamo";

const ID = "0b7f3c1e-2d4a-4c55-9a10-1a2b3c4d5e6f";
type Fenster = { wamoDesktop?: unknown };

function desktop(an: boolean) {
  if (an) (window as unknown as Fenster).wamoDesktop = { isDesktop: true };
  else delete (window as unknown as Fenster).wamoDesktop;
}

function person(email = "niko@wamocon.com", gemerkt: "admin" | "mitglied" | null = "admin") {
  nutzerSetzen({ id: ID, email });
  if (gemerkt) localStorage.setItem(`wamo.rolle.${ID}`, gemerkt);
}

const schalter = () => screen.queryByRole("switch", { name: /PC-Steuerung/ });

describe("Schalter PC-Steuerung ohne Gespräch", () => {
  beforeEach(() => {
    resetWamo();
    localStorage.clear();
    nutzerSetzen({ id: null, email: null });
    desktop(true);
  });
  afterEach(() => {
    desktop(false);
  });

  it("Desktop-App, Admin aus der gemerkten Rolle, keine Sitzung: Block und Schalter sind da und bedienbar, der Klick geht an useWamo", async () => {
    person();
    const onSchalten = vi.fn(() => true);
    render(<GeraeteAbschnitt onPcSteuerung={onSchalten} />);
    expect(screen.getByText("PC-Steuerung", { selector: ".ez-block-titel, h2, h3" })).toBeTruthy();
    const knopf = schalter()!;
    expect(knopf).toBeTruthy();
    expect((knopf as HTMLButtonElement).disabled).toBe(false);
    expect(knopf.getAttribute("aria-checked")).toBe("false");
    expect(screen.getByText(HINWEIS_OHNE_SITZUNG)).toBeTruthy();
    await userEvent.click(knopf);
    expect(onSchalten).toHaveBeenCalledWith(true);
  });

  it("die Rolle vom Kern gilt vor der gemerkten: Mitglied laut Kern sieht keinen Schalter", () => {
    person("niko@wamocon.com", "admin");
    wamo.set((s) => ({ ...s, profil: { name: "Niko", rolle: "mitglied" } }));
    render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    expect(schalter()).toBeNull();
  });

  it("ohne bekannte Rolle (nie verbunden) gibt es keinen Schalter", () => {
    person("niko@wamocon.com", null);
    render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    expect(schalter()).toBeNull();
  });

  it("Laborkonten sehen den Schalter nie, auch nicht mit gemerkter oder gemeldeter Admin-Rolle", () => {
    person("labor-03@wamo.test", "admin");
    wamo.set((s) => ({ ...s, profil: { name: "Platz 3", rolle: "admin" } }));
    render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    expect(schalter()).toBeNull();
    expect(screen.queryByText(/PC-Steuerung beim Start/)).toBeNull();
  });

  it("normaler Browser: ohne Gespräch gesperrt wie bisher", () => {
    desktop(false);
    person();
    render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    expect((schalter() as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(HINWEIS_IM_GESPRAECH)).toBeTruthy();
  });

  it("Desktop-App mit ausgeschaltetem 'Still starten beim Tippen': gesperrt, der Hinweis nennt den Weg", () => {
    person();
    localStorage.setItem(`wamo.stillStart.${ID}`, "aus");
    render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    expect((schalter() as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(HINWEIS_STILL_AUS)).toBeTruthy();
  });

  it("wartet ein Klick auf Sitzung und PC, ist der Schalter gesperrt und sagt es", () => {
    person();
    wamo.set((s) => ({ ...s, presence: "connecting", pcEinschalten: { wartet: true, hinweis: null } }));
    render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    expect((schalter() as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(TEXT_WARTET)).toBeTruthy();
  });

  it("ein Hinweis nach der Wartezeit steht am Schalter, der Schalter ist wieder bedienbar", () => {
    person();
    wamo.set((s) => ({ ...s, pcEinschalten: { wartet: false, hinweis: HINWEIS_PC_GETRENNT } }));
    render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    expect(screen.getByText(HINWEIS_PC_GETRENNT)).toBeTruthy();
    expect((schalter() as HTMLButtonElement).disabled).toBe(false);
  });

  it("mit laufender Sitzung bleibt alles wie bisher: Ziel und 'gilt nur für diese Sitzung'", () => {
    person();
    act(() =>
      wamo.set((s) => ({
        ...s,
        presence: "idle",
        profil: { name: "Niko", rolle: "admin" },
        betrieb: { modus: "buero", modelle: {}, pc: "verbunden", pcSteuerung: "aus", pcName: "WMC-H-04-NS" },
      })),
    );
    render(<GeraeteAbschnitt onPcSteuerung={() => true} />);
    expect((schalter() as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText("gilt nur für diese Sitzung, Ziel WMC-H-04-NS")).toBeTruthy();
  });
});
