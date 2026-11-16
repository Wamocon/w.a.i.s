// Komponententest der Statusleiste (components/Statusleiste.tsx): Der Grund, warum Entwicklungsaufträge aus sind, steht für Admins und
// Mitglieder (den Text für Mitglieder filtert der Kern),
// einmal und ohne title-Attribut (per Tastatur und Touch nicht erreichbar): kompakt für Screenreader, ausführlich sichtbar.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { StatusDetails } from "@/components/Statusleiste";
import { resetWamo, wamo } from "@/lib/wamo";

const GRUND = "Der Schalter für Entwicklungsaufträge im Büro ist aus";

function zustand(rolle: "admin" | "mitglied", grund: string | null = GRUND) {
  wamo.set((s) => ({
    ...s,
    profil: { name: "Niko", rolle },
    betrieb: { modus: "buero", modelle: {}, pc: "aus", entwicklung: "aus", entwicklungGrund: grund ?? undefined },
  }));
}

const feld = (c: HTMLElement) => c.querySelector<HTMLElement>('[data-feld="entwicklung"]');

describe("Statusleiste, Grund der gesperrten Entwicklung", () => {
  beforeEach(() => resetWamo());

  it("ausführlich: der Grund steht sichtbar und genau einmal im Text, ohne title", () => {
    zustand("admin");
    const { container } = render(<StatusDetails kompakt={false} />);
    const dd = feld(container)!.querySelector("dd")!;
    expect(dd.textContent).toContain(GRUND);
    expect(dd.textContent!.split(GRUND)).toHaveLength(2);
    expect(feld(container)!.querySelector("[title]")).toBeNull();
    expect(dd.hasAttribute("title")).toBe(false);
    expect(dd.querySelector(".sr-only")).toBeNull();
  });

  it("kompakt: der Grund steht für Screenreader im Text (sr-only), nicht im title", () => {
    zustand("admin");
    const { container } = render(<StatusDetails kompakt />);
    const dd = feld(container)!.querySelector("dd")!;
    expect(dd.textContent).toContain("Entwicklung gesperrt");
    expect(dd.hasAttribute("title")).toBe(false);
    const leise = dd.querySelector(".sr-only");
    expect(leise?.textContent).toContain(GRUND);
  });

  it("ein Mitglied sieht den Satz, den der Kern ihm schickt (Paket P5)", () => {
    const satz = "Entwicklungsaufträge sind für Mitglieder noch nicht freigeschaltet";
    zustand("mitglied", satz);
    for (const kompakt of [true, false]) {
      const { container, unmount } = render(<StatusDetails kompakt={kompakt} />);
      expect(container.textContent).toContain(satz);
      expect(feld(container)!.textContent).toMatch(/gesperrt/);
      unmount();
    }
  });

  it("ohne Grund bleibt es bei der bisherigen Anzeige", () => {
    zustand("admin", null);
    const { container } = render(<StatusDetails kompakt />);
    const dd = feld(container)!.querySelector("dd")!;
    expect(dd.textContent).toBe("Entwicklung gesperrt");
    expect(dd.querySelector(".sr-only")).toBeNull();
  });
});
