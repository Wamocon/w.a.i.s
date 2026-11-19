// Komponententest der Überschriften mit Ebene nach Seite (components/Ueberschrift.tsx): ohne Versatz bleibt es bei der genannten Ebene,
// mit Versatz rückt sie ein, über Ebene 6 hinaus trägt ein div die Rolle heading mit aria-level. Dazu: Block (Einstellungen) bleibt
// außerhalb der Einstellungsseite bei Stufe 4.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Block } from "@/components/einstellungen/Block";
import { Ueberschrift, UeberschriftVersatz } from "@/components/Ueberschrift";

describe("Ueberschrift", () => {
  it("ohne Versatz die genannte Ebene, mit allen Attributen", () => {
    render(
      <Ueberschrift ebene={4} id="x" className="klasse" tabIndex={-1}>
        Titel
      </Ueberschrift>,
    );
    const h = screen.getByRole("heading", { level: 4, name: "Titel" });
    expect(h.tagName).toBe("H4");
    expect(h.id).toBe("x");
    expect(h.className).toBe("klasse");
    expect(h.getAttribute("tabindex")).toBe("-1");
  });

  it("mit Versatz 1 rückt die Ebene eine Stufe ein", () => {
    render(
      <UeberschriftVersatz value={1}>
        <Ueberschrift ebene={4}>Titel</Ueberschrift>
      </UeberschriftVersatz>,
    );
    expect(screen.getByRole("heading", { level: 5, name: "Titel" }).tagName).toBe("H5");
  });

  it("über Ebene 6 hinaus trägt ein div die Rolle heading mit aria-level, ohne dass die Ebene verloren geht", () => {
    render(
      <UeberschriftVersatz value={1}>
        <Ueberschrift ebene={6} className="name">
          Karte
        </Ueberschrift>
      </UeberschriftVersatz>,
    );
    const h = screen.getByRole("heading", { level: 7, name: "Karte" });
    expect(h.tagName).toBe("DIV");
    expect(h.getAttribute("aria-level")).toBe("7");
    expect(h.className).toBe("name");
  });

  it("reicht ref an das Element weiter, auch beim div", () => {
    let eins: HTMLElement | null = null;
    let zwei: HTMLElement | null = null;
    render(
      <>
        <Ueberschrift
          ebene={3}
          ref={(el) => {
            eins = el;
          }}
        >
          A
        </Ueberschrift>
        <UeberschriftVersatz value={4}>
          <Ueberschrift
            ebene={3}
            ref={(el) => {
              zwei = el;
            }}
          >
            B
          </Ueberschrift>
        </UeberschriftVersatz>
      </>,
    );
    expect((eins as HTMLElement | null)?.tagName).toBe("H3");
    expect((zwei as HTMLElement | null)?.getAttribute("role")).toBe("heading");
  });

  it("Block außerhalb der Einstellungsseite behält die Stufe 4, innerhalb der Seite wird es Stufe 5", () => {
    const { unmount } = render(<Block titel="Außen">x</Block>);
    expect(screen.getByRole("heading", { level: 4, name: "Außen" })).toBeTruthy();
    unmount();
    render(
      <UeberschriftVersatz value={1}>
        <Block titel="Innen">x</Block>
      </UeberschriftVersatz>,
    );
    expect(screen.getByRole("heading", { level: 5, name: "Innen" })).toBeTruthy();
  });
});
