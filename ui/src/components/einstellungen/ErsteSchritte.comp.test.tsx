// Komponententest des Abschnitts "Erste Schritte" (components/einstellungen/ErsteSchritte.tsx): Prüfliste aus Kern und App, Reihenfolge,
// Zustand als Text, Update nur nach Bestätigung durch die App, Token nur an die App, "Erneut prüfen" einmal je 10 Sekunden.
// Kern (lib/kernApi.ts) und Anmeldung (lib/supabase.ts) sind Attrappen, die Desktop-Brücke ist ein falsches window.wamoDesktop.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { kernJson } from "@/lib/kernApi";
import { accessToken } from "@/lib/supabase";
import { ErsteSchritteAbschnitt } from "./ErsteSchritte";

vi.mock("@/lib/kernApi", () => ({ kernJson: vi.fn() }));
vi.mock("@/lib/supabase", () => ({ accessToken: vi.fn() }));
// Modellzugang in Schritten und Installer haben eigene Tests (components/einrichtung/EinrichtungsAblauf.comp.test.tsx); hier nur Platzhalter
vi.mock("@/components/einrichtung/EinrichtungsAblauf", () => ({ EinrichtungsAblauf: () => <div data-testid="modellzugang-schritte" /> }));
vi.mock("@/components/einrichtung/InstallerDownload", () => ({ InstallerDownload: () => <div data-testid="installer-download" /> }));

const KERN_IDS = ["passwort", "geraet", "tunnel", "stimme", "gespraech", "entwicklung", "stimmabdruck", "pc"];
const KERN = { punkte: KERN_IDS.map((id) => ({ id, stufe: "gruen", text: `Punkt ${id} ist bereit.` })), geprueft: "2026-11-15T10:00:00Z" };
const SIGNATUR = `${"B".repeat(86)}==`;
const MANIFEST = { manifest: '{"version":"0.4.0"}', signatur: SIGNATUR, version: "0.4.0" };
const TOKEN = "token-nur-fuer-die-app";

const nichtGefunden = () => Object.assign(new Error("Fehler 404"), { status: 404 });

function kernAntwortet(antworten: Record<string, unknown>) {
  vi.mocked(kernJson).mockImplementation(async (pfad: string) => {
    if (pfad in antworten) return antworten[pfad];
    throw nichtGefunden();
  });
}

type Update = { pruefen: ReturnType<typeof vi.fn>; installieren: ReturnType<typeof vi.fn> };

function appSetzen(teil: Record<string, unknown> = {}): Update {
  const update: Update = {
    pruefen: vi.fn().mockResolvedValue({ ok: true, version: "0.3.0", neuer: false }),
    installieren: vi.fn().mockResolvedValue({ ok: true }),
  };
  window.wamoDesktop = {
    isDesktop: true,
    levels: () => undefined,
    version: "0.3.0",
    mikrofonStatus: async () => "granted",
    geraet: { status: async () => ({ ok: true, eingerichtet: true, kennung: "pc-a", stufe: "mitglied", tunnel: "verbunden", hostUmgebung: "bereit" }) },
    update,
    ...teil,
  } as unknown as Window["wamoDesktop"];
  return update;
}

/** Ein Versprechen, das der Test selbst erfüllt (Antwort kommt später). */
function spaeter<T>() {
  let erfuellen: (v: T) => void = () => undefined;
  const versprechen = new Promise<T>((r) => {
    erfuellen = r;
  });
  return { versprechen, erfuellen };
}

const zusammenfassung = () => screen.getByRole("status");
const zeile = (titel: string) => within(screen.getByText(titel).closest("li") as HTMLElement);

async function zeige() {
  const user = userEvent.setup();
  render(<ErsteSchritteAbschnitt />);
  await screen.findByRole("list", { name: "Prüfliste" });
  return user;
}

describe("ErsteSchritteAbschnitt", () => {
  beforeEach(() => {
    vi.mocked(kernJson).mockReset();
    vi.mocked(accessToken).mockReset().mockResolvedValue(TOKEN);
  });
  afterEach(() => {
    delete window.wamoDesktop;
    vi.useRealTimers();
  });

  it("im Browser: Punkte des Kerns, Hinweise für die App, Alles bereit", async () => {
    kernAntwortet({ "/einrichtung/stand": KERN, "/installer": MANIFEST });
    await zeige();
    expect(zusammenfassung().textContent).toBe("Alles bereit.");
    expect(screen.getAllByText("Nur in der Desktop-App prüfbar.")).toHaveLength(4);
    expect(screen.getByText("Punkt stimme ist bereit.")).toBeTruthy();
    expect(vi.mocked(kernJson).mock.calls.map((c) => c[0])).toEqual(["/einrichtung/stand"]);
    expect(screen.queryByRole("button", { name: "Update installieren" })).toBeNull();
  });

  it("zuerst Modellzugang, dann Installer, zuletzt die Prüfliste", async () => {
    kernAntwortet({ "/einrichtung/stand": KERN, "/installer": MANIFEST });
    await zeige();
    const schritte = screen.getByTestId("modellzugang-schritte");
    const installer = screen.getByTestId("installer-download");
    const liste = screen.getByRole("list", { name: "Prüfliste" });
    expect(schritte.compareDocumentPosition(installer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(installer.compareDocumentPosition(liste) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Installer laden" })).toBeTruthy();
  });

  it("in der App: Reihenfolge der Tabelle, Zustand als Wort neben dem Zeichen", async () => {
    kernAntwortet({ "/einrichtung/stand": KERN, "/installer": MANIFEST });
    appSetzen();
    await zeige();
    const zeilen = screen.getAllByRole("listitem");
    expect(zeilen.map((z) => z.querySelector(".es-titel")?.textContent)).toEqual(
      ["Anmeldung", "Passwort", "App-Version", "Gerät", "Host-Umgebung", "Tunnel", "Mikrofon", "Stimme", "Gespräch", "Entwicklungsaufträge", "Stimmabdruck", "PC-Steuerung"].map(
        (t) => `Bereit: ${t}`,
      ),
    );
    for (const z of zeilen) expect(z.querySelector("svg")?.closest("[aria-hidden='true']")).toBeTruthy();
    expect(zusammenfassung().textContent).toBe("Alles bereit.");
    expect(screen.getByText("Version 0.3.0, aktuell.")).toBeTruthy();
  });

  it("älterer Kern ohne Route: ein Punkt Kern mit Satz statt einer stillen Fehlermeldung", async () => {
    vi.mocked(kernJson).mockRejectedValue(nichtGefunden());
    appSetzen();
    await zeige();
    expect(zeile("Kern").getByText("Die Prüfung am Server ist gerade nicht erreichbar.")).toBeTruthy();
    expect(zeile("Kern").getByText(/^Offen:/)).toBeTruthy();
    expect(screen.getByText("Version 0.3.0. Der Server bietet noch kein Update an.")).toBeTruthy();
    expect(zusammenfassung().textContent).toBe("Noch 2 Punkte offen.");
  });

  it("Host-Umgebung und Mikrofon mit den festen Sätzen", async () => {
    kernAntwortet({ "/einrichtung/stand": KERN, "/installer": MANIFEST });
    appSetzen({
      mikrofonStatus: async () => "denied",
      geraet: { status: async () => ({ ok: true, eingerichtet: true, tunnel: "verbunden", hostUmgebung: "fehlt" }) },
    });
    await zeige();
    expect(screen.getByText("Windows blockiert das Mikrofon für W.A.I.S.")).toBeTruthy();
    expect(screen.getByText(/^Die Python-Umgebung fehlt\./)).toBeTruthy();
    expect(zusammenfassung().textContent).toBe("Noch 2 Punkte offen.");
  });

  it("Update erst nach Bestätigung der App; der Knopf gibt Manifest, Signatur und Token nur an die App", async () => {
    kernAntwortet({ "/einrichtung/stand": KERN, "/installer": MANIFEST });
    const update = appSetzen();
    update.pruefen.mockResolvedValue({ ok: true, version: "0.4.0", neuer: true });
    update.installieren.mockResolvedValue({ ok: false, text: "Abgebrochen.", abgebrochen: true });
    const user = await zeige();
    expect(update.pruefen).toHaveBeenCalledWith({ manifest: MANIFEST.manifest, signatur: SIGNATUR });
    expect(zeile("App-Version").getByText("Update auf Version 0.4.0 verfügbar.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Update installieren" }));
    expect(update.installieren).toHaveBeenCalledWith({ manifest: MANIFEST.manifest, signatur: SIGNATUR, token: TOKEN });
    // abgebrochen: still zurück, der Knopf bleibt, kein Fehlertext
    expect(await screen.findByRole("button", { name: "Update installieren" })).toBeTruthy();
    expect(screen.queryByText("Abgebrochen.")).toBeNull();
    expect(document.body.innerHTML).not.toContain(TOKEN);
  });

  it("lehnt die App das Manifest ab: ihr Satz und nie ein Update-Knopf", async () => {
    kernAntwortet({ "/einrichtung/stand": KERN, "/installer": MANIFEST });
    const update = appSetzen();
    update.pruefen.mockResolvedValue({ ok: false, text: "Update vom Server nicht bestätigt." });
    await zeige();
    expect(zeile("App-Version").getByText("Update vom Server nicht bestätigt.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Update installieren" })).toBeNull();
  });

  it("scheitert die Installation, steht der Satz der App da und der Knopf verschwindet", async () => {
    kernAntwortet({ "/einrichtung/stand": KERN, "/installer": MANIFEST });
    const update = appSetzen();
    update.pruefen.mockResolvedValue({ ok: true, version: "0.4.0", neuer: true });
    update.installieren.mockResolvedValue({ ok: false, text: "Signatur passt nicht." });
    const user = await zeige();
    await user.click(screen.getByRole("button", { name: "Update installieren" }));
    expect(await screen.findByText("Signatur passt nicht.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Update installieren" })).toBeNull();
  });

  it("ohne Anmeldung kein Aufruf der App", async () => {
    kernAntwortet({ "/einrichtung/stand": KERN, "/installer": MANIFEST });
    const update = appSetzen();
    update.pruefen.mockResolvedValue({ ok: true, version: "0.4.0", neuer: true });
    vi.mocked(accessToken).mockResolvedValue(null);
    const user = await zeige();
    await user.click(screen.getByRole("button", { name: "Update installieren" }));
    expect(await screen.findByText("Die Anmeldung ist abgelaufen. Bitte neu anmelden.")).toBeTruthy();
    expect(update.installieren).not.toHaveBeenCalled();
  });

  it("Doppelklick auf Update installieren ruft die App nur einmal, Erneut prüfen ruht während der Installation", async () => {
    kernAntwortet({ "/einrichtung/stand": KERN, "/installer": MANIFEST });
    const update = appSetzen();
    update.pruefen.mockResolvedValue({ ok: true, version: "0.4.0", neuer: true });
    const antwort = spaeter<unknown>();
    update.installieren.mockReturnValue(antwort.versprechen);
    const user = await zeige();
    const aufrufe = vi.mocked(kernJson).mock.calls.length;
    await user.dblClick(screen.getByRole("button", { name: "Update installieren" }));
    await waitFor(() => expect(update.installieren).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: "Update installieren" }));
    const erneut = screen.getByRole("button", { name: "Erneut prüfen" });
    expect(erneut.getAttribute("aria-disabled")).toBe("true");
    await user.click(erneut);
    expect(vi.mocked(kernJson).mock.calls.length).toBe(aufrufe);
    expect(update.installieren).toHaveBeenCalledTimes(1);
    await act(async () => antwort.erfuellen({ ok: false, text: "Abgebrochen.", abgebrochen: true }));
    expect(erneut.getAttribute("aria-disabled")).toBeNull();
  });

  it("Aushängen während des Ladens: die späte Antwort ändert nichts und meldet keinen Fehler", async () => {
    const fehler = vi.spyOn(console, "error");
    const antwort = spaeter<unknown>();
    vi.mocked(kernJson).mockReturnValue(antwort.versprechen);
    const { unmount, container } = render(<ErsteSchritteAbschnitt />);
    await waitFor(() => expect(kernJson).toHaveBeenCalledTimes(1));
    unmount();
    await act(async () => antwort.erfuellen(KERN));
    expect(container.innerHTML).toBe("");
    expect(fehler).not.toHaveBeenCalled();
  });

  it("Aushängen während der Installation: die späte Antwort ändert nichts und meldet keinen Fehler", async () => {
    kernAntwortet({ "/einrichtung/stand": KERN, "/installer": MANIFEST });
    const update = appSetzen();
    update.pruefen.mockResolvedValue({ ok: true, version: "0.4.0", neuer: true });
    const antwort = spaeter<unknown>();
    update.installieren.mockReturnValue(antwort.versprechen);
    const fehler = vi.spyOn(console, "error");
    const user = userEvent.setup();
    const { unmount, container } = render(<ErsteSchritteAbschnitt />);
    await user.click(await screen.findByRole("button", { name: "Update installieren" }));
    await waitFor(() => expect(update.installieren).toHaveBeenCalledTimes(1));
    unmount();
    await act(async () => antwort.erfuellen({ ok: false, text: "Signatur passt nicht." }));
    expect(container.innerHTML).toBe("");
    expect(fehler).not.toHaveBeenCalled();
  });

  it("zeigt den Satz der App, wenn der Installer nicht startet", async () => {
    kernAntwortet({ "/einrichtung/stand": KERN, "/installer": MANIFEST });
    const update = appSetzen();
    update.pruefen.mockResolvedValue({ ok: true, version: "0.4.0", neuer: true });
    const satz = "Der Installer ließ sich nicht starten. Bitte W.A.I.S. neu starten und es noch einmal versuchen.";
    update.installieren.mockResolvedValue({ ok: false, text: satz });
    const user = await zeige();
    await user.click(screen.getByRole("button", { name: "Update installieren" }));
    expect(await zeile("App-Version").findByText(satz)).toBeTruthy();
  });

  it("Erneut prüfen lädt neu und ist danach 10 Sekunden gesperrt", async () => {
    vi.useFakeTimers();
    kernAntwortet({ "/einrichtung/stand": KERN });
    render(<ErsteSchritteAbschnitt />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(kernJson).toHaveBeenCalledTimes(1);
    const knopf = screen.getByRole("button", { name: "Erneut prüfen" });
    fireEvent.click(knopf);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(kernJson).toHaveBeenCalledTimes(2);
    expect(knopf.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(knopf);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9_980);
    });
    expect(kernJson).toHaveBeenCalledTimes(2);
    expect(knopf.getAttribute("aria-disabled")).toBe("true");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(knopf.getAttribute("aria-disabled")).toBeNull();
    fireEvent.click(knopf);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(kernJson).toHaveBeenCalledTimes(3);
  });
});
