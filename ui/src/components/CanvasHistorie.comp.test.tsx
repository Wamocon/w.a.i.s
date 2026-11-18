// Komponententest: Reiter schließen, aufklappbare Historie, Werkzeug canvas_schliessen, Bilder und Dateien im Canvas (Wunsch vom 18.11.2026;
// components/Canvas.tsx, CanvasHistorie.tsx, CanvasDateien.tsx, lib/wamo.ts).
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/canvasBild", () => ({
  herunterladen: vi.fn(),
  logoLaden: vi.fn(async () => undefined),
  mermaidSvg: vi.fn(async () => '<svg viewBox="0 0 10 10"></svg>'),
  svgAlsPng: vi.fn(async () => new Blob(["png"], { type: "image/png" })),
  bildAlsPng: vi.fn(async () => new Blob(["png"], { type: "image/png" })),
}));

import { CanvasBereich } from "@/components/Canvas";
import { herunterladen } from "@/lib/canvasBild";
import type { HistorieQuelle } from "@/lib/canvasOeffnen";
import { KernFehler } from "@/lib/kernApi";
import { applyServerMessage, resetWamo, wamo } from "@/lib/wamo";

const A = "aaaaaaaa-0000-4000-8000-000000000001";
const B = "aaaaaaaa-0000-4000-8000-000000000002";
const C = "aaaaaaaa-0000-4000-8000-000000000003";
const D = "aaaaaaaa-0000-4000-8000-000000000004";

function dreiImCanvas() {
  wamo.set((s) => ({
    ...s,
    canvas: [
      { id: A, kind: "dokument", title: "Angebot", text: "Erste Fassung" },
      { id: B, kind: "dokument", title: "Notiz", text: "Notiz" },
      { id: C, kind: "tabelle", title: "Städte", columns: ["Stadt"], rows: [["Frankfurt"]] },
    ],
  }));
}

const titel = (container: HTMLElement) => Array.from(container.querySelectorAll<HTMLButtonElement>(".canvas-tab")).map((r) => r.textContent);
const offen = (container: HTMLElement) =>
  Array.from(container.querySelectorAll<HTMLButtonElement>(".canvas-tab")).find((r) => r.getAttribute("aria-current") === "true")?.textContent;
const historieKnopf = () => screen.getByRole("button", { name: /^Historie/ });

describe("Canvas, Reiter schließen", () => {
  beforeEach(() => {
    resetWamo();
    dreiImCanvas();
  });
  afterEach(() => resetWamo());

  it("hat an jedem Reiter einen Knopf zum Schließen mit Namen, auch bei nur einem Reiter", () => {
    render(<CanvasBereich />);
    for (const t of ["Angebot", "Notiz", "Städte"]) expect(screen.getByRole("button", { name: `${t} schließen` })).toBeTruthy();
    resetWamo();
    act(() => wamo.set((s) => ({ ...s, canvas: [{ id: A, kind: "dokument", title: "Allein", text: "x" }] })));
    expect(screen.getByRole("button", { name: "Allein schließen" })).toBeTruthy();
  });

  it("blendet den Reiter nur aus: er steht danach in der Historie dieser Sitzung, der Fokus geht zum Nachbarn", () => {
    const { container } = render(<CanvasBereich />);
    const knopf = screen.getByRole("button", { name: "Notiz schließen" });
    knopf.focus();
    fireEvent.click(knopf);
    expect(titel(container)).toEqual(["Angebot", "Städte"]);
    expect(wamo.get().canvasZu.map((g) => g.item.id)).toEqual([B]);
    expect(wamo.get().ansage).toBe("Reiter geschlossen: Notiz. Er steht in der Historie.");
    expect(document.activeElement?.textContent).toBe("Städte");
    expect(historieKnopf().textContent).toBe("Historie (1)");
  });

  it("zeigt nach dem Schließen des neuesten Reiters wieder das Neueste, nach dem letzten die leere Fläche mit dem Knopf Historie im Fokus", () => {
    const { container } = render(<CanvasBereich />);
    fireEvent.click(screen.getByRole("button", { name: "Angebot schließen" }));
    expect(offen(container)).toBe("Städte");
    fireEvent.click(screen.getByRole("button", { name: "Städte schließen" }));
    fireEvent.click(screen.getByRole("button", { name: "Notiz schließen" }));
    expect(screen.getByRole("heading", { name: "Was W.A.I.S. dir hier zeigt" })).toBeTruthy();
    expect(document.activeElement).toBe(historieKnopf());
    expect(wamo.get().canvasZu.map((g) => g.item.title)).toEqual(["Notiz", "Städte", "Angebot"]);
  });

  it("meldet dem Kern nach dem Schließen den Reiter, der jetzt offen ist", () => {
    const aktiv = vi.fn();
    render(<CanvasBereich aktiv={aktiv} />);
    fireEvent.click(screen.getByRole("button", { name: "Städte schließen" }));
    expect(aktiv.mock.calls).toEqual([[C], [B]]);
  });

  it("schließt den gezeigten älteren Reiter und zeigt danach den Nachbarn, der auch den Fokus hat", () => {
    const { container } = render(<CanvasBereich />);
    fireEvent.click(container.querySelectorAll<HTMLButtonElement>(".canvas-tab")[0]);
    fireEvent.click(screen.getByRole("button", { name: "Angebot schließen" }));
    expect(offen(container)).toBe("Notiz");
    expect(document.activeElement?.textContent).toBe("Notiz");
  });

  it("Fortschritt an einem geschlossenen Element öffnet es nicht wieder, die Historie hat den neuen Stand", () => {
    const { container } = render(<CanvasBereich />);
    fireEvent.click(screen.getByRole("button", { name: "Notiz schließen" }));
    act(() => applyServerMessage({ type: "canvas", item: { id: B, kind: "dokument", title: "Notiz", text: "Neuer Stand" } }));
    expect(titel(container)).toEqual(["Angebot", "Städte"]);
    const g = wamo.get().canvasZu[0].item;
    expect(g.kind === "dokument" && g.text).toBe("Neuer Stand");
    // eine Überarbeitung (ersetzt) zeigt das Modell dagegen ausdrücklich: sie kommt als Reiter
    act(() => applyServerMessage({ type: "canvas", item: { id: D, kind: "dokument", title: "Notiz 2", text: "x" }, ersetzt: B }));
    expect(titel(container)).toEqual(["Angebot", "Städte", "Notiz 2"]);
  });

  it("ein Element, das vorne herausfällt (mehr als 20), kommt in die Historie", () => {
    resetWamo();
    act(() => {
      for (let i = 0; i < 21; i++) applyServerMessage({ type: "canvas", item: { id: `lokal-${i}`, kind: "dokument", title: `T${i}`, text: "x" } });
    });
    expect(wamo.get().canvas).toHaveLength(20);
    expect(wamo.get().canvasZu.map((g) => g.item.title)).toEqual(["T0"]);
  });
});

describe("Canvas, Werkzeug canvas_schliessen", () => {
  beforeEach(() => {
    resetWamo();
    dreiImCanvas();
  });
  afterEach(() => resetWamo());

  it("ohne Kennung schließt es den Reiter, den das Canvas gerade zeigt", () => {
    const { container } = render(<CanvasBereich />);
    fireEvent.click(container.querySelectorAll<HTMLButtonElement>(".canvas-tab")[1]);
    act(() => applyServerMessage({ type: "canvas_schliessen", ziel: "offen" }));
    expect(titel(container)).toEqual(["Angebot", "Städte"]);
  });

  it("mit Kennungen schließt es genau diese, mit alle alle", () => {
    const { container } = render(<CanvasBereich />);
    act(() => applyServerMessage({ type: "canvas_schliessen", ziel: "ids", ids: [A, "fremd"] }));
    expect(titel(container)).toEqual(["Notiz", "Städte"]);
    act(() => applyServerMessage({ type: "canvas_schliessen", ziel: "alle" }));
    expect(wamo.get().canvas).toEqual([]);
    expect(wamo.get().canvasZu).toHaveLength(3);
    expect(wamo.get().ansage).toBe("Alle Reiter geschlossen. Sie stehen in der Historie.");
  });

  it("ohne Canvas auf dem Bildschirm schließt offen den neuesten Reiter", () => {
    act(() => applyServerMessage({ type: "canvas_schliessen", ziel: "offen" }));
    expect(wamo.get().canvas.map((it) => it.id)).toEqual([A, B]);
  });
});

function quelle(daten?: Partial<Awaited<ReturnType<HistorieQuelle["laden"]>>>): HistorieQuelle & {
  laden: ReturnType<typeof vi.fn>;
  oeffnen: ReturnType<typeof vi.fn>;
} {
  return {
    laden: vi.fn(async () => ({
      eigene: [
        { id: D, titel: "Altes Angebot", art: "dokument" as const, zeit: Date.parse("2026-11-17T09:00:00Z") },
        { id: C, titel: "Städte", art: "tabelle" as const, zeit: Date.parse("2026-11-18T09:00:00Z") }, // gerade offen
      ],
      geteilt: [],
      ...daten,
    })),
    oeffnen: vi.fn(async () => undefined),
  };
}

describe("Canvas, Historie", () => {
  beforeEach(() => {
    resetWamo();
    dreiImCanvas();
  });
  afterEach(() => resetWamo());

  it("ist standardmäßig zu und klappt per Knopf auf, mit aria-expanded", () => {
    render(<CanvasBereich historie={quelle()} />);
    const knopf = historieKnopf();
    expect(knopf.getAttribute("aria-expanded")).toBe("false");
    const liste = document.getElementById(knopf.getAttribute("aria-controls")!)!;
    expect(liste.hidden).toBe(true);
    fireEvent.click(knopf);
    expect(knopf.getAttribute("aria-expanded")).toBe("true");
    expect(liste.hidden).toBe(false);
  });

  it("öffnet einen geschlossenen Reiter dieser Sitzung wieder, klappt zu und gibt den Fokus an den Knopf", () => {
    const { container } = render(<CanvasBereich />);
    fireEvent.click(screen.getByRole("button", { name: "Angebot schließen" }));
    fireEvent.click(historieKnopf());
    const abschnitt = screen.getByRole("region", { name: "In dieser Sitzung geschlossen" });
    fireEvent.click(within(abschnitt).getByRole("button", { name: /Öffnen: Angebot/ }));
    expect(titel(container)).toEqual(["Notiz", "Städte", "Angebot"]);
    expect(offen(container)).toBe("Angebot");
    expect(wamo.get().canvasZu).toEqual([]);
    expect(historieKnopf().getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(historieKnopf());
    expect(wamo.get().ansage).toBe("Wieder geöffnet: Angebot");
  });

  it("lädt ältere Elemente erst beim Aufklappen, ohne die offenen, und öffnet sie über den Kern", async () => {
    const q = quelle();
    render(<CanvasBereich historie={q} />);
    expect(q.laden).not.toHaveBeenCalled();
    fireEvent.click(historieKnopf());
    const aeltere = await screen.findByRole("region", { name: "Ältere Elemente" });
    await within(aeltere).findByRole("button", { name: /Öffnen: Altes Angebot/ });
    expect(within(aeltere).queryByRole("button", { name: /Städte/ })).toBeNull();
    expect(within(aeltere).getByRole("button", { name: /Altes Angebot/ }).textContent).toContain("Dokument");
    await act(async () => {
      fireEvent.click(within(aeltere).getByRole("button", { name: /Altes Angebot/ }));
    });
    expect(q.oeffnen).toHaveBeenCalledExactlyOnceWith(D);
    expect(historieKnopf().getAttribute("aria-expanded")).toBe("false");
  });

  it("zeigt geteilte Elemente mit Besitzer und meldet Fehler beim Öffnen als Hinweis", async () => {
    const q = quelle({ eigene: [], geteilt: [{ id: D, titel: "Plan", art: "mermaid", zeit: null, von: "Kollegin", recht: "lesen" }] });
    q.oeffnen.mockRejectedValueOnce(new KernFehler(404, "Dieses Canvas-Element gibt es nicht oder es ist nicht mit dir geteilt"));
    render(<CanvasBereich historie={q} />);
    fireEvent.click(historieKnopf());
    const eintrag = await screen.findByRole("button", { name: /Öffnen: Plan/ });
    expect(eintrag.textContent).toContain("von Kollegin");
    await act(async () => {
      fireEvent.click(eintrag);
    });
    expect(wamo.get().toast?.text).toBe("Dieses Canvas-Element gibt es nicht oder es ist nicht mit dir geteilt");
    expect(historieKnopf().getAttribute("aria-expanded")).toBe("true");
  });

  it("sagt, wenn die ältere Historie nicht erreichbar ist; die Sitzung bleibt sichtbar", async () => {
    const q = quelle();
    q.laden.mockRejectedValueOnce(new KernFehler(503, "Historie gerade nicht verfügbar"));
    render(<CanvasBereich historie={q} />);
    fireEvent.click(screen.getByRole("button", { name: "Notiz schließen" }));
    fireEvent.click(historieKnopf());
    // sichtbar in der Liste und als Ansage für Screenreader
    expect(await screen.findAllByText("Die ältere Historie ist gerade nicht erreichbar.")).toHaveLength(2);
    expect(screen.getByRole("button", { name: /Öffnen: Notiz/ })).toBeTruthy();
  });

  it("Escape klappt die Historie zu", () => {
    render(<CanvasBereich />);
    fireEvent.click(historieKnopf());
    fireEvent.keyDown(screen.getByRole("region", { name: "In dieser Sitzung geschlossen" }), { key: "Escape" });
    expect(historieKnopf().getAttribute("aria-expanded")).toBe("false");
  });

  it("im Labor (ohne Quelle und ohne Dateien): Schließen und Historie der Sitzung, sonst nichts Neues", () => {
    render(<CanvasBereich />);
    fireEvent.click(historieKnopf());
    expect(screen.getByRole("region", { name: "In dieser Sitzung geschlossen" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Ältere Elemente" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Datei öffnen" })).toBeNull();
    expect(screen.queryByText("Herunterladen")).toBeNull();
  });
});

describe("Canvas, Bilder und Dateien", () => {
  beforeEach(() => resetWamo());
  afterEach(() => {
    resetWamo();
    vi.unstubAllGlobals();
  });

  it("zeigt ein Bild von außen nie eingebettet, sondern als Verweis, der in einem neuen Fenster ohne Referrer aufgeht", () => {
    act(() =>
      applyServerMessage({
        type: "canvas",
        item: { id: "lokal-1", kind: "bild", title: "Rathaus", url: "https://example.com/r.jpg", alt: "Das Rathaus von außen" },
      }),
    );
    const { container } = render(<CanvasBereich dateien />);
    expect(container.querySelector("img")).toBeNull();
    const link = screen.getByRole("link", { name: "Bild im Browser öffnen" });
    expect(link.getAttribute("href")).toBe("https://example.com/r.jpg");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(screen.getByText("example.com")).toBeTruthy();
    expect(screen.getByText("https://example.com/r.jpg")).toBeTruthy(); // die ganze Adresse ist vor dem Klick sichtbar
    expect(screen.getByText("Das Rathaus von außen")).toBeTruthy();
    expect(screen.queryByText("Herunterladen")).toBeNull(); // nichts zum Herunterladen
  });

  it("öffnet eine CSV-Datei als Tabelle, nur im Browser", async () => {
    const { container } = render(<CanvasBereich dateien />);
    const eingabe = container.querySelector<HTMLInputElement>('[data-testid="canvas-datei"]')!;
    const datei = new File(["Stadt;Einwohner\nEschborn;21000\n"], "städte.csv", { type: "text/csv" });
    await act(async () => {
      fireEvent.change(eingabe, { target: { files: [datei] } });
    });
    await waitFor(() => expect(wamo.get().canvas).toHaveLength(1));
    const item = wamo.get().canvas[0];
    expect(item.kind).toBe("tabelle");
    expect(item.id).toMatch(/^lokal-datei-[0-9a-f]{16}$/);
    expect(screen.getByRole("columnheader", { name: "Einwohner" })).toBeTruthy();
    expect(wamo.get().ansage).toBe("Datei geöffnet: städte.csv");
  });

  it("öffnet ein PNG als Bild mit geprüftem Typ und lehnt PDF, SVG als Bild und falsche Endungen ab", async () => {
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:http://localhost/bild-1"), revokeObjectURL: vi.fn() }));
    const { container } = render(<CanvasBereich dateien />);
    const eingabe = container.querySelector<HTMLInputElement>('[data-testid="canvas-datei"]')!;
    const ihdr = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13, 0x49, 0x48, 0x44, 0x52, 0, 0, 0, 40, 0, 0, 0, 30, 8, 6, 0, 0, 0];
    await act(async () => {
      fireEvent.change(eingabe, { target: { files: [new File([Uint8Array.from(ihdr)], "foto.png", { type: "text/html" })] } });
    });
    await waitFor(() => expect(container.querySelector("img")).not.toBeNull());
    const img = container.querySelector("img")!;
    expect(img.getAttribute("src")).toBe("blob:http://localhost/bild-1");
    expect(img.getAttribute("alt")).toBe("foto.png");
    const item = wamo.get().canvas[0];
    expect(item.kind === "bild" && item.datei?.mime).toBe("image/png"); // aus den Bytes, nicht aus der Angabe des Browsers
    for (const [inhalt, name, text] of [
      ["%PDF-1.7", "vertrag.pdf", /zeigt das Canvas nicht an/],
      ["<svg xmlns='http://www.w3.org/2000/svg'/>", "bild.png", /kein Bild/],
    ] as const) {
      await act(async () => {
        fireEvent.change(eingabe, { target: { files: [new File([inhalt], name)] } });
      });
      await waitFor(() => expect(wamo.get().toast?.text).toMatch(text));
    }
    expect(wamo.get().canvas).toHaveLength(1);
  });

  it("bietet im Kopf das Herunterladen je Art an und speichert über den Browser", async () => {
    act(() => wamo.set((s) => ({ ...s, canvas: [{ id: A, kind: "dokument", title: "Angebot", text: "# A" }] })));
    render(<CanvasBereich dateien />);
    const gruppe = screen.getByRole("group", { name: "Im Browser herunterladen" });
    expect(within(gruppe).getAllByRole("button").map((b) => b.textContent)).toEqual(["Als Markdown", "Als Text", "Als HTML", "Als JSON"]);
    await act(async () => {
      fireEvent.click(within(gruppe).getByRole("button", { name: "Als JSON" }));
    });
    expect(herunterladen).toHaveBeenCalledTimes(1);
    const [blob, name] = vi.mocked(herunterladen).mock.calls[0];
    expect(name).toBe("Angebot.json");
    expect(JSON.parse(await (blob as Blob).text())).toMatchObject({ titel: "Angebot", art: "dokument", text: "# A" });
    expect(wamo.get().toast?.text).toBe("Angebot.json liegt im Download-Ordner.");
  });
});
