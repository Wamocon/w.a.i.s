// Komponententest des geführten Ablaufs beim Ausrollen (components/einrichtung/, Entscheidung D2): erst der Claude-Code-Token, dann
// der API-Schlüssel, beide überspringbar, danach die Zusammenfassung je Fall; dazu der Installer-Download mit Prüfsumme und Befehl.
// Der Kern ist eine Attrappe (lib/kernApi.ts), es geht nichts ins Netz. Ausführen im Ordner ui/:  npm run test:komponenten
import { createHash } from "node:crypto";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EinrichtungsAblauf } from "@/components/einrichtung/EinrichtungsAblauf";
import { InstallerDownload } from "@/components/einrichtung/InstallerDownload";
import { EINRICHTUNG_SCHRITTE } from "@/components/einrichtung/schritte";
import { KernFehler } from "@/lib/kernApi";
import { resetWamo } from "@/lib/wamo";

const kern = vi.hoisted(() => ({ kernJson: vi.fn(), kernDateiStrom: vi.fn() }));
vi.mock("@/lib/kernApi", async (original) => ({
  ...(await original<typeof import("@/lib/kernApi")>()),
  kernJson: kern.kernJson,
  kernDateiStrom: kern.kernDateiStrom,
}));

// Platzhalter, der nur wie ein Token beginnt (kein echter Wert)
const TOKEN = "sk-ant-oat01-" + "x".repeat(40);

type Roh = Record<string, unknown>;
const stand = (o: Roh = {}): Roh => ({
  type: "modellzugang",
  aktion: "status",
  art: "haus",
  quelle: "keiner",
  hinterlegt: false,
  festgelegt: false,
  code_hinterlegt: false,
  modus: "automatisch",
  ...o,
});

const BYTES = new Uint8Array([87, 46, 65, 46, 73, 46, 83, 46]);
const SHA = createHash("sha256").update(BYTES).digest("hex");
const FELDER = {
  v: 1,
  produkt: "wais-desktop",
  version: "0.2.0",
  datei: "WAIS-Setup-0.2.0.exe",
  groesse: BYTES.length,
  sha256: SHA,
  bauzeit: "2026-11-15T14:00:00Z",
  commit: "0123456789".repeat(4),
};
const MANIFEST = { ...FELDER, manifest: JSON.stringify(FELDER), signatur: null };

let aktuellerStand: Roh = stand();
let manifest: unknown = MANIFEST;
const MODELL = EINRICHTUNG_SCHRITTE.filter((s) => s.id !== "installer");

beforeEach(() => {
  resetWamo();
  aktuellerStand = stand();
  manifest = MANIFEST;
  kern.kernJson.mockReset().mockImplementation(async (pfad: string, methode = "GET", body?: Roh) => {
    if (pfad === "/modellzugang" && methode === "GET") return aktuellerStand;
    if (pfad === "/modellzugang" && methode === "POST" && body?.aktion === "hinterlegen") {
      aktuellerStand =
        body.schluesselart === "code"
          ? stand({ ...aktuellerStand, aktion: "hinterlegen", code_hinterlegt: true, code_ende: "xxxx" })
          : stand({ ...aktuellerStand, aktion: "hinterlegen", art: "claude", quelle: "profil", hinterlegt: true, ende: "yyyy" });
      return aktuellerStand;
    }
    if (pfad === "/installer") {
      if (manifest instanceof Error) throw manifest;
      return manifest;
    }
    throw new KernFehler(404, "unbekannt");
  });
  kern.kernDateiStrom.mockReset();
});

const posts = () => kern.kernJson.mock.calls.filter((c) => c[1] === "POST");

describe("EinrichtungsAblauf: Modellzugang nach D2", () => {
  it("fragt zuerst nach dem Claude-Code-Token und danach nach dem API-Schlüssel", async () => {
    const user = userEvent.setup();
    render(<EinrichtungsAblauf schritte={MODELL} />);
    expect(screen.getByText("Schritt 1 von 3")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Claude-Code-Token" })).toBeTruthy();
    expect(screen.getByText(/Hast du ein Claude-Code-Konto \(Max-Tarif\)\?/)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "API-Schlüssel" })).toBeNull();
    await user.click(await screen.findByRole("button", { name: "Überspringen" }));
    expect(screen.getByText("Schritt 2 von 3")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "API-Schlüssel" })).toBeTruthy();
    expect(screen.getByText(/Hast du einen API-Schlüssel\?/)).toBeTruthy();
    // der neue Schritt bekommt den Fokus auf seine Überschrift
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "API-Schlüssel" }));
    await user.click(screen.getByRole("button", { name: "Zurück" }));
    expect(screen.getByRole("heading", { name: "Claude-Code-Token" })).toBeTruthy();
  });

  it("beide Schritte übersprungen: Zusammenfassung mit Hausmodellen für alles und Soniox, nichts gespeichert", async () => {
    const user = userEvent.setup();
    render(<EinrichtungsAblauf schritte={MODELL} />);
    await user.click(await screen.findByRole("button", { name: "Überspringen" }));
    await user.click(await screen.findByRole("button", { name: "Überspringen" }));
    expect(screen.getByRole("heading", { name: "So arbeitet W.A.I.S. für dich" })).toBeTruthy();
    expect(screen.getByText("Schritt 3 von 3")).toBeTruthy();
    expect(await screen.findByText("Hausmodelle für alles.")).toBeTruthy();
    expect(screen.getByText(/Soniox/)).toBeTruthy();
    expect(screen.getByText(/Einstellungen, Modellzugang/)).toBeTruthy();
    expect(posts()).toEqual([]);
  });

  it("nur Token hinterlegt: der Schritt zeigt das Ende und Weiter, die Zusammenfassung den Mischfall", async () => {
    aktuellerStand = stand({ code_hinterlegt: true, code_ende: "abcd" });
    const user = userEvent.setup();
    render(<EinrichtungsAblauf schritte={MODELL} />);
    const schritt = await screen.findByText(/endet auf …abcd/);
    expect(schritt.textContent).toMatch(/Hinterlegt/);
    expect(screen.queryByRole("button", { name: "Überspringen" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Weiter" }));
    await user.click(await screen.findByRole("button", { name: "Überspringen" }));
    const gespraech = await screen.findByText(/Ein Max-Tarif deckt das Gespräch nicht ab/);
    expect(gespraech.textContent).toMatch(/^Hausmodelle/);
    expect(screen.getByText(/Claude Code mit deinem Token \(Max-Tarif, Sonnet\)/).textContent).toMatch(/freigeschaltet/);
  });

  it("nach dem Speichern des Tokens geht es von selbst zum API-Schlüssel, der Wert steht danach nirgends", async () => {
    const user = userEvent.setup();
    render(<EinrichtungsAblauf schritte={MODELL} />);
    await user.type(await screen.findByLabelText("Claude-Code-Token", { selector: "input" }), TOKEN);
    await user.click(screen.getByRole("button", { name: "Hinterlegen" }));
    await screen.findByRole("heading", { name: "API-Schlüssel" });
    expect(posts()).toHaveLength(1);
    expect(posts()[0][2]).toEqual({ aktion: "hinterlegen", schluessel: TOKEN, schluesselart: "code" });
    expect(document.body.innerHTML).not.toContain(TOKEN);
    for (const feld of document.querySelectorAll("input")) expect(feld.value).not.toContain("sk-ant");
  });

  it("vom Admin festgelegt: beide Schlüsselschritte entfallen", async () => {
    aktuellerStand = stand({ festgelegt: true, quelle: "festgelegt" });
    render(<EinrichtungsAblauf schritte={MODELL} />);
    await screen.findByRole("heading", { name: "So arbeitet W.A.I.S. für dich" });
    expect(screen.getByText("Schritt 1 von 1")).toBeTruthy();
    expect(screen.getByText(/Ein Admin hat dein Profil auf Hausmodelle festgelegt/)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Claude-Code-Token" })).toBeNull();
    expect(screen.queryByLabelText("Claude-Code-Token", { selector: "input" })).toBeNull();
  });

  it("die Schnittstelle für das Gerüst: vier Schritte in fester Reihenfolge, jeder für sich mit weiter()", async () => {
    expect(EINRICHTUNG_SCHRITTE.map((s) => s.id)).toEqual(["token", "api", "zusammenfassung", "installer"]);
    expect(EINRICHTUNG_SCHRITTE.map((s) => s.ueberspringbar)).toEqual([true, true, false, true]);
    const weiter = vi.fn();
    const Token = EINRICHTUNG_SCHRITTE[0].Komponente;
    const user = userEvent.setup();
    render(<Token weiter={weiter} />);
    await user.click(await screen.findByRole("button", { name: "Überspringen" }));
    expect(weiter).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Zurück" })).toBeNull();
  });
});

describe("InstallerDownload", () => {
  let angeboten: string[] = [];
  beforeEach(() => {
    angeboten = [];
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:wais-test") });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      angeboten.push(this.download);
    });
  });
  afterEach(() => {
    Reflect.deleteProperty(URL, "createObjectURL");
    Reflect.deleteProperty(URL, "revokeObjectURL");
    delete (window as unknown as { wamoDesktop?: unknown }).wamoDesktop;
    Reflect.deleteProperty(navigator, "clipboard");
  });

  it("zeigt Version, Größe und Prüfsumme; die Prüfsumme lässt sich kopieren", async () => {
    manifest = { ...FELDER, groesse: 117_000_000, manifest: JSON.stringify({ ...FELDER, groesse: 117_000_000 }), signatur: null };
    const user = userEvent.setup();
    // nach userEvent.setup, das sonst eine eigene Zwischenablage einhängt
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<InstallerDownload />);
    expect(await screen.findByText("0.2.0")).toBeTruthy();
    expect(screen.getByText("112 MB")).toBeTruthy();
    expect(screen.getByText(SHA)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Prüfsumme kopieren" }));
    expect(writeText).toHaveBeenCalledWith(SHA);
    expect(await screen.findByText("Kopiert")).toBeTruthy();
    // vor dem Download noch kein Befehl
    expect(screen.queryByText(/Get-FileHash/)).toBeNull();
  });

  it("lädt mit Fortschritt, prüft die Prüfsumme und zeigt danach den Befehl Get-FileHash und den Vergleichssatz", async () => {
    kern.kernDateiStrom.mockImplementation(async (_pfad: string, o: { onFortschritt?: (g: number, s: number | null) => void }) => {
      o.onFortschritt?.(0, BYTES.length);
      o.onFortschritt?.(BYTES.length, BYTES.length);
      return BYTES.slice();
    });
    const user = userEvent.setup();
    render(<InstallerDownload />);
    await user.click(await screen.findByRole("button", { name: "Installer herunterladen" }));
    expect(await screen.findByText("Get-FileHash .\\WAIS-Setup-0.2.0.exe")).toBeTruthy();
    expect(screen.getByText("Vergleiche die Zeichen mit deinem Willkommensblatt.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Befehl kopieren" })).toBeTruthy();
    expect(kern.kernDateiStrom.mock.calls[0][0]).toBe("/installer/datei");
    expect(kern.kernDateiStrom.mock.calls[0][1]).toMatchObject({ hoechstens: BYTES.length });
    expect(angeboten).toEqual(["WAIS-Setup-0.2.0.exe"]);
  });

  it("passt die Prüfsumme nicht, wird die Datei verworfen und nie angeboten", async () => {
    kern.kernDateiStrom.mockResolvedValue(new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]));
    const user = userEvent.setup();
    render(<InstallerDownload />);
    await user.click(await screen.findByRole("button", { name: "Installer herunterladen" }));
    const alarm = await screen.findByRole("alert");
    expect(alarm.textContent).toMatch(/Die Prüfsumme stimmt nicht. Die Datei wurde verworfen./);
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(angeboten).toEqual([]);
    expect(screen.queryByText(/Get-FileHash/)).toBeNull();
  });

  it("Abbrechen beendet den Download ohne Datei", async () => {
    kern.kernDateiStrom.mockImplementation(
      (_pfad: string, o: { signal?: AbortSignal }) =>
        new Promise((_ok, nein) => o.signal?.addEventListener("abort", () => nein(new KernFehler(0, "Abgebrochen")))),
    );
    const user = userEvent.setup();
    render(<InstallerDownload />);
    await user.click(await screen.findByRole("button", { name: "Installer herunterladen" }));
    await user.click(await screen.findByRole("button", { name: "Abbrechen" }));
    await waitFor(() => expect(screen.getByText("Download abgebrochen.")).toBeTruthy());
    expect(angeboten).toEqual([]);
  });

  it("ein ungültiges Manifest zeigt einen Fehler und keine ungeprüften Werte", async () => {
    manifest = { ...FELDER, sha256: SHA.toUpperCase(), manifest: JSON.stringify({ ...FELDER, sha256: SHA.toUpperCase() }), signatur: null };
    render(<InstallerDownload />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/ungültig/);
    expect(screen.queryByText(SHA.toUpperCase())).toBeNull();
    expect(screen.queryByRole("button", { name: "Installer herunterladen" })).toBeNull();
  });

  it("fehlt der Installer am Server, sagt die Karte es konkret", async () => {
    manifest = new KernFehler(503, "fehlt", "installer_fehlt");
    render(<InstallerDownload />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/kein Installer bereit/);
  });

  it("in der App ohne gemeldete Version: Update empfohlen; im Browser kein Hinweis", async () => {
    const { unmount } = render(<InstallerDownload />);
    await screen.findByText("0.2.0");
    expect(screen.queryByText("Update empfohlen.")).toBeNull();
    unmount();
    (window as unknown as { wamoDesktop: unknown }).wamoDesktop = { isDesktop: true };
    render(<InstallerDownload />);
    expect(await screen.findByText("Update empfohlen.")).toBeTruthy();
  });

  it("als Schritt im Gerüst: Weiter ruft weiter()", async () => {
    const weiter = vi.fn();
    const user = userEvent.setup();
    render(<InstallerDownload weiter={weiter} />);
    await screen.findByText("0.2.0");
    await user.click(screen.getByRole("button", { name: "Weiter" }));
    expect(weiter).toHaveBeenCalledTimes(1);
  });
});
