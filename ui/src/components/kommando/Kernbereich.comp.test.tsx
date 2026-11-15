// Komponententest des Namens am Kern (components/kommando/Kernbereich.tsx und ZentraleStatus.tsx): Namensschild und Zentrale zeigen
// W.A.I.S. als Wortmarke (components/Wortmarke.tsx) mit den vier roten Punkten; Zustand und Gruppenname bleiben, wie sie waren.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { darstellungSetzen } from "@/components/kommando/darstellung";
import { Kernbereich } from "@/components/kommando/Kernbereich";
import { resetWamo } from "@/lib/wamo";

beforeEach(() => resetWamo());
afterEach(() => darstellungSetzen("normal", false));

describe("Name am Kern", () => {
  it("das Namensschild zeigt die Wortmarke und danach den Zustand", () => {
    darstellungSetzen("normal", false);
    const { container } = render(<Kernbereich />);
    const schild = container.querySelector(".kz-schild");
    expect(schild?.textContent).toBe("W.A.I.S.schläft");   // im DOM zuerst der Name: Screenreader lesen "W.A.I.S. schläft"
    expect(schild?.querySelector(".kz-schild-name > .marke")?.textContent).toBe("W.A.I.S.");
    expect(schild?.querySelectorAll(".marke-punkt")).toHaveLength(4);
  });

  it("die Zentrale zeigt den großen Namen als Wortmarke", () => {
    darstellungSetzen("zentrale", false);
    const { container } = render(<Kernbereich />);
    expect(container.querySelector(".kz-schild")).toBeNull();
    const gross = container.querySelector(".kz-gross");
    expect(gross?.textContent).toBe("W.A.I.S.");
    expect(gross?.querySelector(":scope > .marke")?.textContent).toBe("W.A.I.S.");
    expect(gross?.querySelectorAll(".marke-punkt")).toHaveLength(4);
    expect(screen.getByRole("group", { name: "W.A.I.S. schläft" })).toBeTruthy();
  });
});
