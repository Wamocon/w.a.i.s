// Komponententest der Live-Untertitel unter dem Kern (components/LiveCaption.tsx, lib/untertitel.ts, Block "Untertitel" in den
// Einstellungen unter Darstellung): standardmäßig aus, dann steht in der Mitte nur der Hinweissatz, solange noch nichts gesagt ist. In
// den Einstellungen lassen sie sich je Person auf diesem Gerät einschalten. Laborkonten behalten sie wie bisher.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { DarstellungAbschnitt } from "@/components/einstellungen/Abschnitte";
import { darstellungSetzen } from "@/components/kommando/darstellung";
import { LiveCaption } from "@/components/LiveCaption";
import { untertitelSetzen } from "@/lib/einstellungen";
import { nutzerSetzen } from "@/lib/nutzer";
import { leereCaption, resetWamo, wamo } from "@/lib/wamo";

const NIKO = "0b7f3c1e-2d4a-4c55-9a10-1a2b3c4d5e6f";
const ANDERE = "9c8b7a6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";
const SCHALTER = "Live-Untertitel unter dem Kern zeigen (dieses Gerät)";

beforeEach(() => {
  resetWamo();
  localStorage.clear();
  darstellungSetzen("normal", false);
  nutzerSetzen({ id: NIKO, email: "niko@wamocon.com" });
});

const imGespraech = () =>
  act(() =>
    wamo.set((s) => ({
      ...s,
      presence: "speaking",
      caption: { ...leereCaption, userDone: "Schließ die Tür", userLive: "und dann", text: "Gern, ich schließe sie.", spoken: 2 },
    })),
  );
const nutzerzeile = (c: HTMLElement) => c.querySelector(".caption-user")?.textContent ?? null;
const hinweis = (c: HTMLElement) => c.querySelector(".caption-hint")?.textContent ?? null;
const schalter = () => screen.getByRole("checkbox", { name: SCHALTER }) as HTMLInputElement;

describe("Live-Untertitel: Standard aus", () => {
  it("zeigt im Gespräch weder die Sätze der Person noch die von W.A.I.S.", () => {
    const { container } = render(<LiveCaption />);
    imGespraech();
    expect(nutzerzeile(container)).toBeNull();
    expect(container.querySelector(".caption-bot")).toBeNull();
    expect(container.textContent).not.toContain("Tür");
  });

  it("behält den Hinweissatz, solange noch nichts gesagt ist (offline und online)", () => {
    const { container } = render(<LiveCaption />);
    expect(hinweis(container)).toBe("Tippe auf „Gespräch starten“.");
    act(() => wamo.set((s) => ({ ...s, presence: "idle" })));
    expect(hinweis(container)).toBe("Sag einfach, was du brauchst.");
    imGespraech();
    expect(hinweis(container)).toBeNull();
    expect(container.querySelector(".caption")).not.toBeNull(); // der Platz bleibt, der Kern springt nicht
  });

  it("auch ohne Anmeldung aus, der Schalter ist dann gesperrt", () => {
    nutzerSetzen({ id: null, email: null });
    const { container } = render(
      <>
        <DarstellungAbschnitt />
        <LiveCaption />
      </>,
    );
    imGespraech();
    expect(nutzerzeile(container)).toBeNull();
    expect(schalter().checked).toBe(false);
    expect(schalter().disabled).toBe(true);
  });
});

describe("Live-Untertitel: in den Einstellungen einschalten", () => {
  it("der Schalter unter Darstellung schaltet sie ein und wieder aus und merkt sich die Wahl je Person", () => {
    const { container } = render(
      <>
        <DarstellungAbschnitt />
        <LiveCaption />
      </>,
    );
    expect(screen.getByRole("heading", { name: "Untertitel" })).toBeTruthy();
    expect(schalter().checked).toBe(false);
    imGespraech();
    fireEvent.click(schalter());
    expect(schalter().checked).toBe(true);
    expect(localStorage.getItem(`wamo.untertitel.${NIKO}`)).toBe("an");
    expect(nutzerzeile(container)).toContain("Schließ die Tür");
    expect(container.querySelector(".caption-bot")?.textContent).toBe("Gern, ich schließe sie.");
    fireEvent.click(schalter());
    expect(localStorage.getItem(`wamo.untertitel.${NIKO}`)).toBe("aus");
    expect(nutzerzeile(container)).toBeNull();
  });

  it("die Wahl gilt nur für diese Person", () => {
    untertitelSetzen(NIKO, true);
    const { container } = render(<LiveCaption />);
    imGespraech();
    expect(nutzerzeile(container)).toContain("Schließ die Tür");
    act(() => nutzerSetzen({ id: ANDERE, email: "kollegin@wamocon.com" }));
    expect(nutzerzeile(container)).toBeNull();
  });
});

describe("Live-Untertitel: Laborkonten", () => {
  it("behalten die Untertitel wie bisher (keine Stimmprüfung, kein Abschnitt Darstellung)", () => {
    nutzerSetzen({ id: ANDERE, email: "labor-03@wamo.test" });
    const { container } = render(<LiveCaption />);
    imGespraech();
    expect(nutzerzeile(container)).toContain("Schließ die Tür");
  });
});
