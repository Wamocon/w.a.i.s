// Komponententest des Wegs aus der Hauptansicht zum Schalter "PC-Steuerung" (components/Statusleiste.tsx, lib/einstellungenHash.ts):
// In der Kopfzeile ist das Modul PC für Admins ein Link zu "Geräte und PC", auch ohne Sitzung (gemerkte Rolle). Der Klick öffnet die
// Einstellungen ohne Neuladen und setzt den Fokus auf den Schalter. Mitglieder und Laborkonten sehen das Modul wie bisher, ohne Link;
// das ausführliche Menü bleibt ohne Link.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({ getSupabase: () => null, accessToken: async () => null }));

import { GeraeteAbschnitt } from "@/components/einstellungen/Geraete";
import { StatusDetails } from "@/components/Statusleiste";
import { PC_STEUERUNG_ID } from "@/lib/einstellungenAbschnitte";
import { nutzerSetzen } from "@/lib/nutzer";
import { resetWamo, wamo } from "@/lib/wamo";

const ID = "0b7f3c1e-2d4a-4c55-9a10-1a2b3c4d5e6f";
type Fenster = { wamoDesktop?: unknown };

function person(email = "niko@wamocon.com", gemerkt: "admin" | "mitglied" | null = "admin") {
  nutzerSetzen({ id: ID, email });
  if (gemerkt) localStorage.setItem(`wamo.rolle.${ID}`, gemerkt);
}

const weg = () => screen.queryByRole("link", { name: /PC-Steuerung/ });

describe("Weg aus der Kopfzeile zum Schalter PC-Steuerung", () => {
  beforeEach(() => {
    resetWamo();
    localStorage.clear();
    nutzerSetzen({ id: null, email: null });
    window.history.replaceState(null, "", "/");
    (window as unknown as Fenster).wamoDesktop = { isDesktop: true };
  });
  afterEach(() => {
    delete (window as unknown as Fenster).wamoDesktop;
    window.history.replaceState(null, "", "/");
  });

  it("Admin ohne Sitzung (gemerkte Rolle): das Modul PC ist ein Link zu Geräte und PC", () => {
    person();
    const { container } = render(<StatusDetails kompakt />);
    const link = weg()!;
    expect(link).toBeTruthy();
    expect(link.getAttribute("href")).toBe("#einstellungen/geraete");
    expect(container.querySelector('[data-feld="pc"]')!.contains(link)).toBe(true);
    expect(link.textContent).toContain("PC");
  });

  it("der Klick öffnet die Einstellungen ohne Neuladen und setzt den Fokus auf den Schalter", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      person();
      render(
        <>
          <StatusDetails kompakt />
          <GeraeteAbschnitt onPcSteuerung={() => true} />
        </>,
      );
      await userEvent.click(weg()!);
      expect(window.location.hash).toBe("#einstellungen/geraete");
      await act(async () => {
        await vi.advanceTimersByTimeAsync(200);
      });
      const block = document.getElementById(PC_STEUERUNG_ID)!;
      expect(block).toBeTruthy();
      expect(document.activeElement).toBe(screen.getByRole("switch", { name: /PC-Steuerung/ }));
    } finally {
      vi.useRealTimers();
    }
  });

  it("mit Sitzung und PC-Steuerung an: auch das Modul PC-Steuerung führt zum Schalter", () => {
    person();
    wamo.set((s) => ({
      ...s,
      presence: "idle",
      profil: { name: "Niko", rolle: "admin" },
      betrieb: { modus: "buero", modelle: {}, pc: "verbunden", pcSteuerung: "an" },
    }));
    const { container } = render(<StatusDetails kompakt />);
    const links = screen.getAllByRole("link", { name: /PC-Steuerung/ });
    expect(links).toHaveLength(2);
    expect(container.querySelector('[data-feld="pcsteuerung"] a')).toBeTruthy();
  });

  it("Mitglied, Laborkonto und unbekannte Rolle: kein Link, das Modul bleibt wie bisher", () => {
    for (const [email, gemerkt] of [
      ["niko@wamocon.com", "mitglied"],
      ["labor-03@wamo.test", "admin"],
      ["niko@wamocon.com", null],
    ] as const) {
      localStorage.clear();
      person(email, gemerkt);
      const { container, unmount } = render(<StatusDetails kompakt />);
      expect(weg()).toBeNull();
      expect(container.querySelector('[data-feld="pc"]')!.textContent).toContain("PC");
      unmount();
    }
  });

  it("das ausführliche Menü und die Einstellungen (nicht kompakt) zeigen keinen Link", () => {
    person();
    render(<StatusDetails kompakt={false} />);
    expect(weg()).toBeNull();
  });
});
