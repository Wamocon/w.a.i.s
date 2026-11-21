// Komponententest der Karte "Claude-Zugang des Labors": Quelle und "endet auf", verdecktes Feld, Prüfen und Speichern, Entfernen mit Bestätigung,
// frischer Code des zweiten Faktors, klare Sätze bei Fehlern, und dass der Schlüssel nirgends außer im Feld steht.
// Der Kern (lib/laborZugang.ts) und die Anmeldung (lib/geraeteVerwaltungApi.ts) sind durch Attrappen ersetzt.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { codeBestaetigen } from "@/lib/geraeteVerwaltungApi";
import { KernFehler } from "@/lib/kernApi";
import { faktorIstFrisch, laborZugangEntfernen, laborZugangLaden, laborZugangSetzen } from "@/lib/laborZugang";
import type { LaborZugang as Zugang } from "@/lib/laborZugangLogik";
import { LaborZugang } from "./LaborZugang";

vi.mock("@/lib/geraeteVerwaltungApi", () => ({ codeBestaetigen: vi.fn() }));
vi.mock("@/lib/laborZugang", async (original) => {
  const echt = await original<typeof import("@/lib/laborZugang")>();
  return {
    ...echt,
    laborZugangLaden: vi.fn(),
    laborZugangSetzen: vi.fn(),
    laborZugangEntfernen: vi.fn(),
    faktorIstFrisch: vi.fn(),
  };
});

// Ein Schlüssel wird nie als Ganzes in den Quelltext geschrieben, sondern zusammengesetzt
const MARKER = "MARKERgeheim0815";
const SCHLUESSEL = ["sk", "ant", "api03"].join("-") + `-${MARKER}-0123456789abcdefghij-Zq77`;

const GESPEICHERT: Zugang = {
  quelle: "gespeichert",
  endetAuf: "Ab12",
  workspace: null,
  gesetztAm: "2026-11-21T09:30:00+00:00",
  geprueftAm: "2026-11-21T09:31:00+00:00",
  hinweis: null,
};
const SERVER: Zugang = { quelle: "server", endetAuf: "Sv11", workspace: null, gesetztAm: null, geprueftAm: null, hinweis: null };
const KEINER: Zugang = { quelle: "keiner", endetAuf: null, workspace: null, gesetztAm: null, geprueftAm: null, hinweis: null };

function kernFehler(status: number, code: string | null, text: string) {
  return new KernFehler(status, text, code);
}

beforeEach(() => {
  vi.mocked(laborZugangLaden).mockResolvedValue(SERVER);
  vi.mocked(faktorIstFrisch).mockResolvedValue(true);
  vi.mocked(codeBestaetigen).mockResolvedValue({ ok: true });
});

afterEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

const feld = () => screen.getByLabelText(/^(Neuer )?Claude-Schlüssel/) as HTMLInputElement;

async function bereit(zugang: Zugang = SERVER) {
  vi.mocked(laborZugangLaden).mockResolvedValue(zugang);
  const user = userEvent.setup();
  const onFaktor = vi.fn();
  render(<LaborZugang onFaktor={onFaktor} />);
  await screen.findByRole("button", { name: "Prüfen und speichern" });
  return { user, onFaktor };
}

describe("Anzeige", () => {
  it("zeigt bei einem gespeicherten Schlüssel nur das Ende, den Workspace und die Zeiten, nie den Schlüssel", async () => {
    await bereit({ ...GESPEICHERT, workspace: "wrkspc_Test123456" });
    expect(screen.getByRole("heading", { name: "Claude-Zugang des Labors" })).toBeTruthy();
    expect(screen.getAllByText("gespeichert").length).toBeGreaterThan(0);
    expect(screen.getByText("…Ab12")).toBeTruthy();
    expect(screen.getByText("wrkspc_Test123456")).toBeTruthy();
    expect(screen.getByText("21.11.2026, 09:30")).toBeTruthy();
    expect(screen.getByText("21.11.2026, 09:31")).toBeTruthy();
    expect(screen.getByText(/hier gespeicherte Schlüssel gilt, endet auf …Ab12/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Entfernen …" })).toBeTruthy();
    expect(screen.getByLabelText("Neuer Claude-Schlüssel (ersetzt den gespeicherten)")).toBeTruthy();
  });

  it("nennt beim Schlüssel des Servers dessen Ende und bietet kein Entfernen an", async () => {
    await bereit(SERVER);
    expect(screen.getByText(/Es gilt der Schlüssel des Servers, endet auf …Sv11/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Entfernen/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Prüfen und speichern" })).toBeTruthy();
  });

  it("sagt ohne Schlüssel, dass die Laborsitzungen über Hausmodelle laufen, und zeigt den Hinweis des Kerns", async () => {
    await bereit({ ...KEINER, hinweis: "Ein Schlüssel ist gespeichert, der Kern kann ihn aber nicht lesen." });
    expect(screen.getByText(/laufen über Hausmodelle/)).toBeTruthy();
    expect(screen.getByText(/kann ihn aber nicht lesen/)).toBeTruthy();
  });

  it("zeigt einen Fehler beim Laden mit Neu laden", async () => {
    vi.mocked(laborZugangLaden).mockRejectedValueOnce(kernFehler(404, null, "Fehler 404")).mockResolvedValueOnce(SERVER);
    const user = userEvent.setup();
    render(<LaborZugang />);
    const hinweis = await screen.findByRole("alert");
    expect(hinweis.textContent).toMatch(/Paket Labor-Zugang/);
    await user.click(screen.getByRole("button", { name: "Neu laden" }));
    expect(await screen.findByRole("button", { name: "Prüfen und speichern" })).toBeTruthy();
    expect(laborZugangLaden).toHaveBeenCalledTimes(2);
  });

  it("das Feld für den Schlüssel ist verdeckt und merkt sich nichts", async () => {
    await bereit();
    const f = feld();
    expect(f.type).toBe("password");
    expect(f.getAttribute("autocomplete")).toBe("off");
    expect(f.getAttribute("spellcheck")).toBe("false");
    expect(f.hasAttribute("value")).toBe(false);
  });
});

describe("Prüfen und speichern", () => {
  it("sendet den Schlüssel, leert das Feld, zeigt nur das Ende und lässt den Schlüssel nirgends stehen", async () => {
    vi.mocked(laborZugangSetzen).mockResolvedValue({ ...GESPEICHERT, endetAuf: "Zq77" });
    const { user, onFaktor } = await bereit();
    await user.type(feld(), SCHLUESSEL);
    expect(feld().value).toBe(SCHLUESSEL);
    await user.click(screen.getByRole("button", { name: "Prüfen und speichern" }));
    await waitFor(() => expect(laborZugangSetzen).toHaveBeenCalledWith(SCHLUESSEL, null));
    await screen.findByText(/Geprüft und gespeichert\. Der Schlüssel endet auf …Zq77/);
    expect(feld().value).toBe("");
    expect(onFaktor).toHaveBeenCalled();
    expect(document.body.innerHTML.includes(MARKER)).toBe(false);
    expect(JSON.stringify({ ...window.localStorage }).includes(MARKER)).toBe(false);
    expect(JSON.stringify({ ...window.sessionStorage }).includes(MARKER)).toBe(false);
    expect(window.location.href.includes(MARKER)).toBe(false);
    expect(screen.getAllByText("gespeichert").length).toBeGreaterThan(0); // der Stand ist der neue
  });

  it("geht auch mit der Eingabetaste und schickt den Workspace mit", async () => {
    vi.mocked(laborZugangSetzen).mockResolvedValue(GESPEICHERT);
    const { user } = await bereit();
    await user.type(screen.getByLabelText(/Workspace-ID/), " wrkspc_Test123456 ");
    await user.type(feld(), `${SCHLUESSEL}{Enter}`);
    await waitFor(() => expect(laborZugangSetzen).toHaveBeenCalledWith(SCHLUESSEL, "wrkspc_Test123456"));
  });

  it("lehnt eine falsche Eingabe ab, bevor etwas gesendet wird, und lässt sie im Feld", async () => {
    const { user } = await bereit();
    await user.click(screen.getByRole("button", { name: "Prüfen und speichern" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/Bitte trag den Claude-Schlüssel ein/);
    await user.type(feld(), "kein-schluessel");
    await user.click(screen.getByRole("button", { name: "Prüfen und speichern" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/nicht nach einem Anthropic-API-Schlüssel/);
    expect(feld().getAttribute("aria-invalid")).toBe("true");
    expect(feld().value).toBe("kein-schluessel");
    expect(laborZugangSetzen).not.toHaveBeenCalled();
    await user.type(feld(), "x");
    expect(feld().hasAttribute("aria-invalid")).toBe(false);
  });

  it("erkennt ein Claude-Code-Token und schlägt den falschen Weg nicht vor", async () => {
    const { user } = await bereit();
    await user.type(feld(), ["sk", "ant", "oat01"].join("-") + "-GEHEIMgeheim-0123456789abcdefghijklmnop-Zz99");
    await user.click(screen.getByRole("button", { name: "Prüfen und speichern" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/Claude-Code-Token, kein API-Schlüssel/);
    expect(laborZugangSetzen).not.toHaveBeenCalled();
  });

  it("zeigt den Satz des Kerns bei einer Ablehnung und leert das Feld trotzdem", async () => {
    vi.mocked(laborZugangSetzen).mockRejectedValue(kernFehler(400, "schluessel_abgelehnt", "Anthropic lehnt den Schlüssel ab (401): Er ist ungültig."));
    const { user } = await bereit();
    await user.type(feld(), SCHLUESSEL);
    await user.click(screen.getByRole("button", { name: "Prüfen und speichern" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Anthropic lehnt den Schlüssel ab (401): Er ist ungültig.");
    expect(feld().value).toBe("");
    expect(document.body.innerHTML.includes(MARKER)).toBe(false);
    expect(screen.getByText(/Es gilt der Schlüssel des Servers/)).toBeTruthy(); // der Stand bleibt unverändert
  });

  it("ein Schlüssel im Satz des Kerns erscheint gekürzt", async () => {
    vi.mocked(laborZugangSetzen).mockRejectedValue(kernFehler(400, "schluessel_abgelehnt", `Fehler bei ${SCHLUESSEL}`));
    const { user } = await bereit();
    await user.type(feld(), SCHLUESSEL);
    await user.click(screen.getByRole("button", { name: "Prüfen und speichern" }));
    const text = (await screen.findByRole("alert")).textContent ?? "";
    expect(text).toContain("sk-ant-…");
    expect(text.includes(MARKER)).toBe(false);
  });

  it("sperrt den Knopf, solange die Anfrage läuft (kein zweites Senden)", async () => {
    let fertig: (z: Zugang) => void = () => undefined;
    vi.mocked(laborZugangSetzen).mockReturnValue(new Promise<Zugang>((r) => (fertig = r)));
    const { user } = await bereit();
    await user.type(feld(), SCHLUESSEL);
    await user.click(screen.getByRole("button", { name: "Prüfen und speichern" }));
    const knopf = await screen.findByRole("button", { name: "Einen Moment …" });
    expect((knopf as HTMLButtonElement).disabled).toBe(true);
    expect(feld().disabled).toBe(true);
    fertig(GESPEICHERT);
    await screen.findByText(/Geprüft und gespeichert/);
    expect(laborZugangSetzen).toHaveBeenCalledTimes(1);
  });
});

describe("zweiter Faktor", () => {
  it("fragt bei altem Faktor erst nach dem Code, behält den Schlüssel im Feld und sendet danach", async () => {
    vi.mocked(faktorIstFrisch).mockResolvedValue(false);
    vi.mocked(laborZugangSetzen).mockResolvedValue(GESPEICHERT);
    const { user } = await bereit();
    await user.type(feld(), SCHLUESSEL);
    await user.click(screen.getByRole("button", { name: "Prüfen und speichern" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/braucht der Kern einen frischen Code/);
    expect(laborZugangSetzen).not.toHaveBeenCalled();
    expect(feld().value).toBe(SCHLUESSEL);
    const code = screen.getByLabelText("Code der Authenticator-App");
    await waitFor(() => expect(document.activeElement).toBe(code));
    await user.type(code, "123 456");
    await user.click(screen.getByRole("button", { name: "Prüfen und speichern" }));
    await waitFor(() => expect(codeBestaetigen).toHaveBeenCalledWith("123456"));
    await waitFor(() => expect(laborZugangSetzen).toHaveBeenCalledWith(SCHLUESSEL, null));
    await screen.findByText(/Geprüft und gespeichert/);
    expect(screen.queryByLabelText("Code der Authenticator-App")).toBeNull(); // nach Erfolg wieder weg
  });

  it("verlangt sechs Ziffern und sendet ohne gültigen Code nichts", async () => {
    vi.mocked(faktorIstFrisch).mockResolvedValue(false);
    const { user } = await bereit();
    await user.type(feld(), SCHLUESSEL);
    await user.click(screen.getByRole("button", { name: "Prüfen und speichern" }));
    await screen.findByLabelText("Code der Authenticator-App");
    await user.type(screen.getByLabelText("Code der Authenticator-App"), "12");
    await user.click(screen.getByRole("button", { name: "Prüfen und speichern" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/sechs Ziffern/);
    expect(codeBestaetigen).not.toHaveBeenCalled();
    expect(laborZugangSetzen).not.toHaveBeenCalled();
  });

  it("zeigt den Satz, wenn der Code nicht passt, und behält den Schlüssel im Feld", async () => {
    vi.mocked(faktorIstFrisch).mockResolvedValue(false);
    vi.mocked(codeBestaetigen).mockResolvedValue({ ok: false, text: "Der Code passt nicht. Nimm den aktuellen aus der App." });
    const { user } = await bereit();
    await user.type(feld(), SCHLUESSEL);
    await user.click(screen.getByRole("button", { name: "Prüfen und speichern" }));
    await user.type(await screen.findByLabelText("Code der Authenticator-App"), "654321");
    await user.click(screen.getByRole("button", { name: "Prüfen und speichern" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Der Code passt nicht. Nimm den aktuellen aus der App.");
    expect(laborZugangSetzen).not.toHaveBeenCalled();
    expect((screen.getByLabelText("Code der Authenticator-App") as HTMLInputElement).value).toBe(""); // der Code wird nicht gehalten
    expect(feld().value).toBe(SCHLUESSEL);
  });

  it("verlangt den Code, wenn der Kern den Faktor als zu alt ablehnt, auch wenn das Token frisch aussah, und gibt den Schlüssel zurück ins Feld", async () => {
    vi.mocked(laborZugangSetzen).mockRejectedValueOnce(kernFehler(403, "zweiter_faktor_zu_alt", "egal")).mockResolvedValueOnce(GESPEICHERT);
    const { user } = await bereit();
    await user.type(feld(), SCHLUESSEL);
    await user.click(screen.getByRole("button", { name: "Prüfen und speichern" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/Code des zweiten Faktors ist zu alt/);
    expect(feld().value).toBe(SCHLUESSEL); // der Kern hat nichts verarbeitet
    await user.type(await screen.findByLabelText("Code der Authenticator-App"), "123456");
    await user.click(screen.getByRole("button", { name: "Prüfen und speichern" })); // faktorIstFrisch ist wahr, der Kern bleibt aber maßgeblich
    await waitFor(() => expect(codeBestaetigen).toHaveBeenCalledWith("123456"));
    await waitFor(() => expect(laborZugangSetzen).toHaveBeenCalledTimes(2));
    await screen.findByText(/Geprüft und gespeichert/);
  });
});

describe("Entfernen", () => {
  it("fragt nach, setzt den Fokus auf Abbrechen und schließt mit Escape", async () => {
    const { user } = await bereit(GESPEICHERT);
    await user.click(screen.getByRole("button", { name: "Entfernen …" }));
    const gruppe = screen.getByRole("group", { name: "Gespeicherten Schlüssel entfernen" });
    expect(gruppe.textContent).toMatch(/Wirklich entfernen\?/);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Abbrechen" })));
    expect(screen.queryByLabelText(/Claude-Schlüssel/)).toBeNull(); // die Eingabe tritt hinter die Frage zurück
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("group", { name: "Gespeicherten Schlüssel entfernen" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Entfernen …" })));
    expect(laborZugangEntfernen).not.toHaveBeenCalled();
  });

  it("Abbrechen ändert nichts", async () => {
    const { user } = await bereit(GESPEICHERT);
    await user.click(screen.getByRole("button", { name: "Entfernen …" }));
    await user.click(screen.getByRole("button", { name: "Abbrechen" }));
    expect(screen.queryByRole("group", { name: "Gespeicherten Schlüssel entfernen" })).toBeNull();
    expect(laborZugangEntfernen).not.toHaveBeenCalled();
  });

  it("entfernt nach der Bestätigung und nennt, was danach gilt", async () => {
    vi.mocked(laborZugangEntfernen).mockResolvedValue(SERVER);
    const { user, onFaktor } = await bereit(GESPEICHERT);
    await user.click(screen.getByRole("button", { name: "Entfernen …" }));
    await user.click(screen.getByRole("button", { name: "Ja, entfernen" }));
    await screen.findByText(/Für neue Laborsitzungen gilt wieder der Schlüssel des Servers/);
    expect(laborZugangEntfernen).toHaveBeenCalledTimes(1);
    expect(onFaktor).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Entfernen/ })).toBeNull();
    expect(screen.getByText(/Es gilt der Schlüssel des Servers, endet auf …Sv11/)).toBeTruthy();
  });

  it("sagt ohne Server-Schlüssel, dass nun Hausmodelle gelten", async () => {
    vi.mocked(laborZugangEntfernen).mockResolvedValue(KEINER);
    const { user } = await bereit(GESPEICHERT);
    await user.click(screen.getByRole("button", { name: "Entfernen …" }));
    await user.click(screen.getByRole("button", { name: "Ja, entfernen" }));
    await screen.findByText(/Neue Laborsitzungen laufen über Hausmodelle/);
  });

  it("verlangt bei altem Faktor den Code und entfernt erst danach", async () => {
    vi.mocked(faktorIstFrisch).mockResolvedValue(false);
    vi.mocked(laborZugangEntfernen).mockResolvedValue(SERVER);
    const { user } = await bereit(GESPEICHERT);
    await user.click(screen.getByRole("button", { name: "Entfernen …" }));
    await user.click(screen.getByRole("button", { name: "Ja, entfernen" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/frischen Code/);
    expect(laborZugangEntfernen).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("Code der Authenticator-App"), "123456");
    await user.click(screen.getByRole("button", { name: "Ja, entfernen" }));
    await waitFor(() => expect(laborZugangEntfernen).toHaveBeenCalledTimes(1));
    expect(codeBestaetigen).toHaveBeenCalledWith("123456");
  });

  it("zeigt einen Fehler des Kerns und lässt die Frage offen", async () => {
    vi.mocked(laborZugangEntfernen).mockRejectedValue(kernFehler(429, "zu_oft", "egal"));
    const { user } = await bereit(GESPEICHERT);
    await user.click(screen.getByRole("button", { name: "Entfernen …" }));
    await user.click(screen.getByRole("button", { name: "Ja, entfernen" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/Zu viele Versuche/);
    expect(screen.getByRole("group", { name: "Gespeicherten Schlüssel entfernen" })).toBeTruthy();
  });
});
