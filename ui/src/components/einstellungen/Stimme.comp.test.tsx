// Komponententest des Abschnitts "Stimme" in den Einstellungen (components/einstellungen/StimmeAbschnitt.tsx, lib/stimme.ts): Status und
// Betriebsart, Einlernen und Neu einlernen (öffnet die Einlernansicht und schließt die Einstellungen), Abdruck löschen mit Rückfrage.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StimmeAbschnitt } from "@/components/einstellungen/StimmeAbschnitt";
import { applyServerMessage, resetWamo, wamo } from "@/lib/wamo";

function aktionen() {
  return { start: vi.fn(() => true), abbrechen: vi.fn(() => true), loeschen: vi.fn(() => true) };
}
const online = () => act(() => wamo.set((s) => ({ ...s, presence: "idle" })));
const status = (s: "aus" | "fehlt" | "laedt" | "kaputt" | "bereit", modus: "aus" | "beobachten" | "streng" = "streng") =>
  act(() => applyServerMessage({ type: "stimme_status", status: s, modus }));

beforeEach(() => {
  resetWamo();
  window.location.hash = "";
});

describe("Abschnitt Stimme: Anzeige", () => {
  it("sagt ehrlich, dass der Kern nichts meldet, und sperrt das Einlernen", () => {
    render(<StimmeAbschnitt aktionen={aktionen()} />);
    expect(screen.getByText("Der Kern meldet noch nichts")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Stimme einlernen" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Starte ein Gespräch/)).toBeTruthy();
  });

  it("zeigt Status, Betriebsart und die letzte Äußerung", () => {
    render(<StimmeAbschnitt aktionen={aktionen()} />);
    online();
    status("bereit", "streng");
    act(() => applyServerMessage({ type: "stimme_ergebnis", ergebnis: "eigen", wert: 0.78, modus: "streng" }));
    const daten = document.querySelector(".ez-daten") as HTMLElement;
    expect(within(daten).getByText("Eingelernt")).toBeTruthy();
    expect(within(daten).getByText("Streng: nur deine Stimme darf Aufträge auslösen")).toBeTruthy();
    expect(within(daten).getByText("Deine Stimme 0,78")).toBeTruthy();
  });

  it("erklärt, dass nur ein Abdruck gespeichert wird, keine Aufnahme", () => {
    render(<StimmeAbschnitt aktionen={aktionen()} />);
    expect(screen.getByText(/keine Aufnahme/)).toBeTruthy();
  });

  it("bei ausgeschalteter Stimmerkennung gibt es kein Einlernen", () => {
    render(<StimmeAbschnitt aktionen={aktionen()} />);
    online();
    status("aus", "aus");
    expect((screen.getByRole("button", { name: "Stimme einlernen" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/nicht eingeschaltet/)).toBeTruthy();
  });
});

describe("Abschnitt Stimme: Einlernen", () => {
  it("Stimme einlernen öffnet die Einlernansicht in der Einwilligung", () => {
    render(<StimmeAbschnitt aktionen={aktionen()} />);
    online();
    status("fehlt");
    fireEvent.click(screen.getByRole("button", { name: "Stimme einlernen" }));
    expect(wamo.get().abdruck?.phase).toBe("einwilligung");
  });

  it("mit vorhandenem Abdruck heißt der Knopf Neu einlernen", () => {
    render(<StimmeAbschnitt aktionen={aktionen()} />);
    online();
    status("bereit");
    fireEvent.click(screen.getByRole("button", { name: "Neu einlernen" }));
    expect(wamo.get().abdruck?.phase).toBe("einwilligung");
  });

  it("schließt dabei die Einstellungen, damit die Einlernansicht sichtbar wird", () => {
    window.location.hash = "#einstellungen/stimme";
    render(<StimmeAbschnitt aktionen={aktionen()} />);
    online();
    status("fehlt");
    fireEvent.click(screen.getByRole("button", { name: "Stimme einlernen" }));
    expect(window.location.hash).not.toMatch(/einstellungen/);
  });
});

describe("Abschnitt Stimme: Abdruck löschen", () => {
  it("gibt es nur, wenn ein Abdruck da ist", () => {
    render(<StimmeAbschnitt aktionen={aktionen()} />);
    online();
    status("fehlt");
    expect(screen.queryByRole("button", { name: "Abdruck löschen" })).toBeNull();
    status("bereit");
    expect(screen.getByRole("button", { name: "Abdruck löschen" })).toBeTruthy();
  });

  it("fragt erst nach und löscht nichts, solange die Person nicht bestätigt", () => {
    const a = aktionen();
    render(<StimmeAbschnitt aktionen={a} />);
    online();
    status("bereit");
    fireEvent.click(screen.getByRole("button", { name: "Abdruck löschen" }));
    const frage = screen.getByRole("group", { name: /Abdruck wirklich löschen/ });
    expect(within(frage).getByRole("button", { name: "Behalten" })).toBeTruthy();
    expect(a.loeschen).not.toHaveBeenCalled();
    fireEvent.click(within(frage).getByRole("button", { name: "Behalten" }));
    expect(a.loeschen).not.toHaveBeenCalled();
    expect(screen.queryByRole("group", { name: /Abdruck wirklich löschen/ })).toBeNull();
  });

  it("setzt den Fokus der Rückfrage auf Behalten (die sichere Wahl)", () => {
    render(<StimmeAbschnitt aktionen={aktionen()} />);
    online();
    status("bereit");
    fireEvent.click(screen.getByRole("button", { name: "Abdruck löschen" }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Behalten" }));
  });

  it("löscht erst nach Ja und meldet, dass der Kern bestätigt", () => {
    const a = aktionen();
    render(<StimmeAbschnitt aktionen={a} />);
    online();
    status("bereit");
    fireEvent.click(screen.getByRole("button", { name: "Abdruck löschen" }));
    fireEvent.click(screen.getByRole("button", { name: "Ja, Abdruck löschen" }));
    expect(a.loeschen).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status").textContent).toMatch(/Löschen angefragt/);
    expect(screen.queryByRole("group", { name: /Abdruck wirklich löschen/ })).toBeNull();
  });

  it("der Knopf Abdruck löschen nennt die Rückfrage, die er öffnet (aria-controls zu aria-expanded)", () => {
    render(<StimmeAbschnitt aktionen={aktionen()} />);
    online();
    status("bereit");
    const knopf = screen.getByRole("button", { name: "Abdruck löschen" });
    expect(knopf.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(knopf);
    const frage = screen.getByRole("group", { name: /Abdruck wirklich löschen/ });
    expect(knopf.getAttribute("aria-expanded")).toBe("true");
    expect(frage.id).not.toBe("");
    expect(knopf.getAttribute("aria-controls")).toBe(frage.id);
    fireEvent.click(screen.getByRole("button", { name: "Behalten" }));
    expect(knopf.getAttribute("aria-expanded")).toBe("false");
    expect(knopf.hasAttribute("aria-controls")).toBe(false);
  });

  it("nach dem Löschen steht der Fokus auf dem Einlernen, solange es bedienbar ist", () => {
    render(<StimmeAbschnitt aktionen={aktionen()} />);
    online();
    status("bereit");
    fireEvent.click(screen.getByRole("button", { name: "Abdruck löschen" }));
    fireEvent.click(screen.getByRole("button", { name: "Ja, Abdruck löschen" }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Neu einlernen" }));
  });

  it("ist das Einlernen gesperrt (Sitzung weg), geht der Fokus nach dem Löschen auf die Meldung statt verloren", () => {
    const a = { ...aktionen(), loeschen: vi.fn(() => false) };
    render(<StimmeAbschnitt aktionen={a} />);
    online();
    status("bereit");
    fireEvent.click(screen.getByRole("button", { name: "Abdruck löschen" }));
    act(() => wamo.set((s) => ({ ...s, presence: "offline" })));
    expect((screen.getByRole("button", { name: "Neu einlernen" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Ja, Abdruck löschen" }));
    const meldung = screen.getByRole("alert");
    expect(document.activeElement).toBe(meldung);
    expect(document.activeElement).not.toBe(document.body);
  });

  it("sagt, wenn das Löschen nicht hinausging", () => {
    const a = { ...aktionen(), loeschen: vi.fn(() => false) };
    render(<StimmeAbschnitt aktionen={a} />);
    online();
    status("bereit");
    fireEvent.click(screen.getByRole("button", { name: "Abdruck löschen" }));
    fireEvent.click(screen.getByRole("button", { name: "Ja, Abdruck löschen" }));
    expect(screen.getByRole("alert").textContent).toMatch(/nicht hinaus/);
  });
});

describe("Abschnitt Stimme: ein Abdruck je Mikrofon", () => {
  const LAPTOP = { kennung: "a".repeat(32), name: "Mikrofonarray (Realtek)", am: "2026-11-18T09:30:00+00:00" };
  const HEADSET = { kennung: "b".repeat(32), name: "Headset (Jabra)", am: "2026-11-18T10:00:00+00:00" };
  const ALT = { kennung: "unbekannt", name: null, am: null };
  const liste = (mikrofone: (typeof LAPTOP | typeof ALT)[], max = 3, laeuft = "Headset (Jabra)") =>
    act(() => {
      applyServerMessage({ type: "stimmabdruck_mikrofone", mikrofone, max });
      wamo.set((s) => ({ ...s, mikrofon: laeuft }));
    });

  it("zeigt die eingelernten Mikrofone mit Datum; das laufende hat Neu einlernen, jedes hat Löschen", () => {
    render(<StimmeAbschnitt aktionen={aktionen()} />);
    online();
    status("bereit");
    liste([LAPTOP, HEADSET, ALT]);
    const eintraege = within(screen.getByRole("list", { name: "Eingelernte Mikrofone" })).getAllByRole("listitem");
    expect(eintraege.map((e) => e.textContent)).toEqual([
      expect.stringContaining("Mikrofonarray (Realtek)"),
      expect.stringContaining("läuft gerade"),
      expect.stringContaining("Unbekanntes Mikrofon"),
    ]);
    expect(eintraege[0].textContent).toContain("18.11.2026");
    expect(screen.getByRole("button", { name: "Neu einlernen: Headset (Jabra)" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Neu einlernen: Mikrofonarray (Realtek)" })).toBeNull();
    expect(screen.getAllByRole("button", { name: /^Löschen: / })).toHaveLength(3);
    // das laufende ist eingelernt: kein zweiter Knopf zum Einlernen
    expect(screen.queryByRole("button", { name: "Für dieses Mikrofon einlernen" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Neu einlernen: Headset (Jabra)" }));
    expect(wamo.get().abdruck?.phase).toBe("einwilligung");
  });

  it("ein noch nicht eingelerntes Mikrofon lässt sich dazu einlernen", () => {
    render(<StimmeAbschnitt aktionen={aktionen()} />);
    online();
    status("bereit");
    liste([LAPTOP], 3, "Webcam");
    fireEvent.click(screen.getByRole("button", { name: "Für dieses Mikrofon einlernen" }));
    expect(wamo.get().abdruck?.phase).toBe("einwilligung");
  });

  it("bei drei Mikrofonen ist ein viertes gesperrt und der Abschnitt sagt, was hilft", () => {
    render(<StimmeAbschnitt aktionen={aktionen()} />);
    online();
    status("bereit");
    liste([LAPTOP, HEADSET, { ...LAPTOP, kennung: "c".repeat(32), name: "Konferenz" }], 3, "Webcam");
    expect((screen.getByRole("button", { name: "Für dieses Mikrofon einlernen" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/höchstens drei Mikrofone/i)).toBeTruthy();
  });

  it("einen Abdruck löschen fragt nach und schickt nur dessen Kennung", () => {
    const a = aktionen();
    render(<StimmeAbschnitt aktionen={a} />);
    online();
    status("bereit");
    liste([LAPTOP, HEADSET]);
    fireEvent.click(screen.getByRole("button", { name: "Löschen: Mikrofonarray (Realtek)" }));
    const frage = screen.getByRole("group", { name: /Abdruck für Mikrofonarray \(Realtek\) wirklich löschen/ });
    expect(document.activeElement).toBe(within(frage).getByRole("button", { name: "Behalten" }));
    fireEvent.click(within(frage).getByRole("button", { name: "Ja, löschen" }));
    expect(a.loeschen).toHaveBeenCalledWith(LAPTOP.kennung);
  });

  it("bestätigt der Kern das Löschen, verschwindet der Eintrag sofort; ohne Kennung verschwinden alle", () => {
    render(<StimmeAbschnitt aktionen={aktionen()} />);
    online();
    status("bereit");
    liste([LAPTOP, HEADSET]);
    act(() => applyServerMessage({ type: "stimmabdruck", status: "geloescht", mikrofon: LAPTOP.kennung }));
    expect(screen.queryByRole("button", { name: "Löschen: Mikrofonarray (Realtek)" })).toBeNull();
    expect(screen.getByRole("button", { name: "Löschen: Headset (Jabra)" })).toBeTruthy();
    act(() => applyServerMessage({ type: "stimmabdruck", status: "geloescht" }));
    expect(wamo.get().stimmMikrofone?.mikrofone).toEqual([]);
  });

  it("wird das laufende Mikrofon gelöscht, geht der Fokus auf die Meldung statt mit dem Eintrag verloren", () => {
    render(<StimmeAbschnitt aktionen={aktionen()} />);
    online();
    status("bereit");
    liste([LAPTOP, HEADSET]);
    fireEvent.click(screen.getByRole("button", { name: "Löschen: Headset (Jabra)" }));
    fireEvent.click(screen.getByRole("button", { name: "Ja, löschen" }));
    expect(document.activeElement).toBe(screen.getByRole("status"));
  });

  it("alle Abdrücke löschen ist der Widerruf und schickt keine Kennung", () => {
    const a = aktionen();
    render(<StimmeAbschnitt aktionen={a} />);
    online();
    status("bereit");
    liste([LAPTOP, HEADSET]);
    fireEvent.click(screen.getByRole("button", { name: "Alle Abdrücke löschen" }));
    fireEvent.click(screen.getByRole("button", { name: "Ja, alle löschen" }));
    expect(a.loeschen).toHaveBeenCalledWith();
  });

  it("kann der Kern nur einen Abdruck, bleibt alles wie bisher", () => {
    render(<StimmeAbschnitt aktionen={aktionen()} />);
    online();
    status("bereit");
    liste([ALT], 1, "Webcam");
    expect(screen.queryByRole("list", { name: "Eingelernte Mikrofone" })).toBeNull();
    expect(screen.getByRole("button", { name: "Neu einlernen" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Abdruck löschen" })).toBeTruthy();
  });
});
