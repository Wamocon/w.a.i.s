// Komponententest der Wortmarke (components/Wortmarke.tsx): Nur der Name W.A.I.S. steht in der Markenschrift (Klasse .marke), seine
// Punkte sind eigene Spans in WMC-Rot (.marke-punkt). Ein Zusatz wie "Testlabor, Platz 3" behält die Schrift der Stelle. Der Text
// bleibt unverändert, Screenreader und Tests lesen "W.A.I.S.".
// Ausführen im Ordner ui/:  npm run test:komponenten
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Wortmarke } from "@/components/Wortmarke";

function zeige(text?: string) {
  const { container } = render(
    <h1>
      <Wortmarke text={text} />
    </h1>,
  );
  const titel = container.querySelector("h1");
  return {
    titel,
    marken: [...container.querySelectorAll(".marke")].map((m) => m.textContent),
    punkte: [...container.querySelectorAll(".marke-punkt")],
  };
}

describe("Wortmarke", () => {
  it("zeigt W.A.I.S. in der Markenschrift, die vier Punkte als eigene Spans", () => {
    const { titel, marken, punkte } = zeige();
    expect(titel?.textContent).toBe("W.A.I.S.");
    expect(marken).toEqual(["W.A.I.S."]);
    expect(punkte).toHaveLength(4);
    expect(punkte.every((p) => p.textContent === ".")).toBe(true);
  });

  it("die Punkte sind nur Gestaltung: kein eigenes Label, nichts für Screenreader versteckt", () => {
    const { titel } = zeige();
    expect(titel?.querySelector("[aria-label], [aria-hidden]")).toBeNull();
  });

  it("mit Zusatz (Laborkonten) steht nur der Name in der Markenschrift, der Zusatz behält die Schrift der Stelle", () => {
    const { titel, marken, punkte } = zeige("W.A.I.S. Testlabor, Platz 3");
    expect(titel?.textContent).toBe("W.A.I.S. Testlabor, Platz 3");
    expect(marken).toEqual(["W.A.I.S."]);
    expect(punkte).toHaveLength(4);
    // ein einziges Kind: der Abstand einer Flex-Stelle (Kopfzeile) fällt nicht zwischen Name und Zusatz
    expect(titel?.children).toHaveLength(1);
  });

  it("ein Text ohne den Namen vorne bleibt ganz in der Schrift der Stelle", () => {
    const { titel, marken, punkte } = zeige("Testlabor 1.2");
    expect(titel?.textContent).toBe("Testlabor 1.2");
    expect(marken).toEqual([]);
    expect(punkte).toHaveLength(0);
  });
});
