// Komponententest des Abschnitts "Updates" der Einstellungen (components/einstellungen/Updates.tsx): Zustände mit Titel, Satz und
// Zeichen, Update nur nach Bestätigung der App, Token erst beim Klick und nur an die App, höchstens eine Installation zugleich,
// "Nach Updates suchen" einmal je 10 Sekunden, nach dem Aushängen setzt keine späte Antwort mehr Zustand, im Browser nur ein Satz
// und der Installer. Kern (lib/kernApi.ts) und Anmeldung (lib/supabase.ts) sind Attrappen, die Desktop-Brücke ist ein falsches
// window.wamoDesktop.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { UeberschriftVersatz } from "@/components/Ueberschrift";
import { kernJson } from "@/lib/kernApi";
import { accessToken } from "@/lib/supabase";
import { updates, updatesInstallieren, updatesLaden, updatesZuruecksetzen } from "@/lib/updatesStore";
import { UpdatesAbschnitt } from "./Updates";

vi.mock("@/lib/kernApi", () => ({ kernJson: vi.fn() }));
vi.mock("@/lib/supabase", () => ({ accessToken: vi.fn() }));
// der Installer zum Herunterladen hat eigene Tests; hier nur ein Platzhalter
vi.mock("@/components/einrichtung/InstallerDownload", () => ({ InstallerDownload: () => <div data-testid="installer-download" /> }));

const SIGNATUR = `${"B".repeat(86)}==`;
const MANIFEST = { manifest: '{"version":"0.8.0"}', signatur: SIGNATUR, version: "0.8.0" };
const TOKEN = "token-nur-fuer-die-app";

const nichtGefunden = () => Object.assign(new Error("Fehler 404"), { status: 404 });

function kernAntwortet(antworten: Record<string, unknown>) {
  vi.mocked(kernJson).mockImplementation(async (pfad: string) => {
    if (pfad in antworten) return antworten[pfad];
    throw nichtGefunden();
  });
}

type Update = { pruefen: ReturnType<typeof vi.fn>; installieren: ReturnType<typeof vi.fn> };

/** Desktop-App 0.7.0, die ein Update auf 0.8.0 bestätigt (wenn nichts anderes gesagt wird). */
function appSetzen(teil: Record<string, unknown> = {}): Update {
  const update: Update = {
    pruefen: vi.fn().mockResolvedValue({ ok: true, version: "0.8.0", neuer: true }),
    installieren: vi.fn().mockResolvedValue({ ok: true }),
  };
  window.wamoDesktop = { isDesktop: true, levels: () => undefined, version: "0.7.0", update, ...teil } as unknown as Window["wamoDesktop"];
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

const wert = (name: string) => screen.getByText(name, { selector: "dt" }).nextElementSibling?.textContent;
const zustand = () => document.querySelector<HTMLElement>(".up-zustand") as HTMLElement; // daneben gibt es die Live-Region der Suche
const installieren = () => screen.getByRole("button", { name: "Update installieren" });
const suchen = () => screen.getByRole("button", { name: "Nach Updates suchen" });

async function zeige() {
  const user = userEvent.setup();
  render(<UpdatesAbschnitt />);
  await screen.findByText(/^Geprüft um /);
  return user;
}

describe("UpdatesAbschnitt in der Desktop-App", () => {
  beforeEach(() => {
    updatesZuruecksetzen();
    vi.mocked(kernJson).mockReset();
    vi.mocked(accessToken).mockReset().mockResolvedValue(TOKEN);
  });
  afterEach(() => {
    delete window.wamoDesktop;
    vi.useRealTimers();
  });

  it("Update verfügbar: installierte Version, Angebot des Servers, Titel mit der Version und der Knopf", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    await zeige();
    expect(wert("Installiert")).toBe("0.7.0");
    expect(wert("Auf dem Server")).toBe("0.8.0");
    expect(zustand().textContent).toContain("Update verfügbar (Version 0.8.0)");
    expect(update.pruefen).toHaveBeenCalledWith({ manifest: MANIFEST.manifest, signatur: SIGNATUR });
    expect(installieren()).toBeTruthy();
    expect(suchen()).toBeTruthy();
    expect(screen.queryByTestId("installer-download")).toBeNull();
  });

  it("Aktuell: Satz und Haken, kein Update-Knopf", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen().pruefen.mockResolvedValue({ ok: true, version: "0.7.0", neuer: false });
    await zeige();
    expect(zustand().textContent).toContain("Aktuell");
    expect(zustand().textContent).toContain("Du nutzt die neueste Version.");
    expect(wert("Auf dem Server")).toBe("0.7.0");
    expect(screen.queryByRole("button", { name: "Update installieren" })).toBeNull();
    expect(suchen()).toBeTruthy();
  });

  it("der Server bietet nichts an (404): Aktuell mit dem Satz dazu", async () => {
    kernAntwortet({});
    const update = appSetzen();
    await zeige();
    expect(zustand().textContent).toContain("Der Server bietet noch kein Update an.");
    expect(wert("Auf dem Server")).toBe("noch kein Update");
    expect(update.pruefen).not.toHaveBeenCalled();
  });

  it("Server nicht lesbar: Prüfung nicht möglich, kein Knopf zum Installieren", async () => {
    kernAntwortet({ "/installer": { manifest: 1 } });
    appSetzen();
    await zeige();
    expect(zustand().textContent).toContain("Prüfung nicht möglich");
    expect(screen.queryByRole("button", { name: "Update installieren" })).toBeNull();
    expect(screen.queryByTestId("installer-download")).toBeNull();
  });

  it("lehnt die App das Manifest ab: ihr Satz, Prüfung nicht möglich und nie ein Update-Knopf", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen().pruefen.mockResolvedValue({ ok: false, text: "Update vom Server nicht bestätigt." });
    await zeige();
    expect(zustand().textContent).toContain("Prüfung nicht möglich");
    expect(zustand().textContent).toContain("Update vom Server nicht bestätigt.");
    expect(screen.queryByRole("button", { name: "Update installieren" })).toBeNull();
  });

  it("ältere App ohne Version und ohne Update-Teil: sagt es, fragt den Server nichts und bietet den Installer an", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen({ version: undefined, update: undefined });
    await zeige();
    expect(zustand().textContent).toContain("Prüfung nicht möglich");
    expect(wert("Installiert")).toBe("unbekannt");
    expect(screen.getByTestId("installer-download")).toBeTruthy();
    expect(vi.mocked(kernJson)).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Update installieren" })).toBeNull();
  });

  it("während der ersten Prüfung steht Wird geprüft da, ohne Knöpfe zum Installieren", async () => {
    const antwort = spaeter<unknown>();
    vi.mocked(kernJson).mockReturnValue(antwort.versprechen);
    appSetzen();
    render(<UpdatesAbschnitt />);
    await waitFor(() => expect(kernJson).toHaveBeenCalledTimes(1));
    expect(zustand().textContent).toContain("Wird geprüft");
    expect(screen.getByText("Prüfe ...")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Update installieren" })).toBeNull();
    await act(async () => antwort.erfuellen(MANIFEST));
    expect(await screen.findByText(/^Geprüft um /)).toBeTruthy();
  });

  it("jeder Zustand hat ein Zeichen, das für Screenreader versteckt ist, und seinen Titel als Text", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    await zeige();
    const zeichen = zustand().querySelector(".es-zeichen");
    expect(zeichen?.getAttribute("aria-hidden")).toBe("true");
    expect(zeichen?.querySelector("svg")).toBeTruthy();
    expect(zustand().querySelector(".es-titel")?.textContent).toBe("Update verfügbar (Version 0.8.0)");
  });

  it("Installieren: Manifest, Signatur und Token gehen nur an die App, Wird installiert, dann der Satz zum Neustart", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    const antwort = spaeter<unknown>();
    update.installieren.mockReturnValue(antwort.versprechen);
    const user = await zeige();
    expect(accessToken).not.toHaveBeenCalled(); // das Token holt erst der Klick
    await user.click(installieren());
    await waitFor(() => expect(update.installieren).toHaveBeenCalledWith({ manifest: MANIFEST.manifest, signatur: SIGNATUR, token: TOKEN }));
    expect(zustand().textContent).toContain("Wird installiert");
    expect(zustand().textContent).toContain("Rückfrage");
    // der Knopf bleibt stehen (der Fokus geht nicht verloren), ist aber gesperrt
    expect(installieren().getAttribute("aria-disabled")).toBe("true");
    expect(installieren().getAttribute("aria-busy")).toBe("true");
    expect(document.body.innerHTML).not.toContain(TOKEN);
    await act(async () => antwort.erfuellen({ ok: true }));
    expect(zustand().textContent).toContain("Die App installiert das Update und startet danach neu.");
    expect(screen.queryByRole("button", { name: "Update installieren" })).toBeNull();
    expect(document.body.innerHTML).not.toContain(TOKEN);
  });

  it("abgebrochen: still zurück, der Knopf bleibt, kein Fehlertext", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen().installieren.mockResolvedValue({ ok: false, text: "Abgebrochen.", abgebrochen: true });
    const user = await zeige();
    await user.click(installieren());
    await waitFor(() => expect(zustand().textContent).toContain("Update verfügbar (Version 0.8.0)"));
    expect(installieren().getAttribute("aria-disabled")).toBeNull();
    expect(screen.queryByText("Abgebrochen.")).toBeNull();
    expect(zustand().textContent).not.toContain("Fehler");
  });

  it("scheitert die Installation: Fehler mit dem Satz der App, der Knopf verschwindet, der Fokus geht zu Nach Updates suchen", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen().installieren.mockResolvedValue({ ok: false, text: "Signatur passt nicht." });
    const user = await zeige();
    await user.click(installieren());
    expect(await screen.findByText("Signatur passt nicht.")).toBeTruthy();
    expect(zustand().querySelector(".es-titel")?.textContent).toBe("Fehler");
    expect(screen.queryByRole("button", { name: "Update installieren" })).toBeNull();
    expect(screen.getByText(/Nach Updates suchen/, { selector: "p" })).toBeTruthy(); // der Hinweis zum erneuten Versuch
    expect(document.activeElement).toBe(suchen());
  });

  it("nach einem Fehler holt Nach Updates suchen den frischen Stand: wieder Update verfügbar mit Knopf", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    update.installieren.mockResolvedValue({ ok: false, text: "Signatur passt nicht." });
    const user = await zeige();
    await user.click(installieren());
    await screen.findByText("Signatur passt nicht.");
    await user.click(suchen());
    expect(await screen.findByRole("button", { name: "Update installieren" })).toBeTruthy();
    expect(screen.queryByText("Signatur passt nicht.")).toBeNull();
    expect(update.pruefen).toHaveBeenCalledTimes(2);
  });

  it("ohne Anmeldung kein Aufruf der App: Fehler mit dem Satz zur Anmeldung", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    vi.mocked(accessToken).mockResolvedValue(null);
    const user = await zeige();
    await user.click(installieren());
    expect(await screen.findByText("Die Anmeldung ist abgelaufen. Bitte neu anmelden.")).toBeTruthy();
    expect(update.installieren).not.toHaveBeenCalled();
  });

  it("Doppelklick auf Update installieren ruft die App nur einmal, Nach Updates suchen ruht währenddessen", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    const antwort = spaeter<unknown>();
    update.installieren.mockReturnValue(antwort.versprechen);
    const user = await zeige();
    const aufrufe = vi.mocked(kernJson).mock.calls.length;
    await user.dblClick(installieren());
    await waitFor(() => expect(update.installieren).toHaveBeenCalledTimes(1));
    await user.click(installieren());
    expect(suchen().getAttribute("aria-disabled")).toBe("true");
    await user.click(suchen());
    expect(vi.mocked(kernJson).mock.calls.length).toBe(aufrufe);
    expect(update.installieren).toHaveBeenCalledTimes(1);
    await act(async () => antwort.erfuellen({ ok: false, text: "Abgebrochen.", abgebrochen: true }));
    expect(suchen().getAttribute("aria-disabled")).toBeNull();
  });

  it("Während einer Suche startet keine Installation", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    const user = await zeige();
    const zweite = spaeter<unknown>();
    vi.mocked(kernJson).mockReturnValue(zweite.versprechen);
    await user.click(suchen());
    await waitFor(() => expect(suchen().getAttribute("aria-busy")).toBe("true"));
    expect(installieren().getAttribute("aria-disabled")).toBe("true");
    await user.click(installieren());
    expect(update.installieren).not.toHaveBeenCalled();
    await act(async () => zweite.erfuellen(MANIFEST));
    expect(installieren().getAttribute("aria-disabled")).toBeNull();
  });

  it("Aushängen während des Ladens: die späte Antwort ändert nichts und meldet keinen Fehler", async () => {
    const fehler = vi.spyOn(console, "error");
    const antwort = spaeter<unknown>();
    vi.mocked(kernJson).mockReturnValue(antwort.versprechen);
    appSetzen();
    const { unmount, container } = render(<UpdatesAbschnitt />);
    await waitFor(() => expect(kernJson).toHaveBeenCalledTimes(1));
    unmount();
    await act(async () => antwort.erfuellen(MANIFEST));
    expect(container.innerHTML).toBe("");
    expect(fehler).not.toHaveBeenCalled();
  });

  it("Aushängen während der Installation: die späte Antwort ändert nichts und meldet keinen Fehler", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    const antwort = spaeter<unknown>();
    update.installieren.mockReturnValue(antwort.versprechen);
    const fehler = vi.spyOn(console, "error");
    const user = userEvent.setup();
    const { unmount, container } = render(<UpdatesAbschnitt />);
    await user.click(await screen.findByRole("button", { name: "Update installieren" }));
    await waitFor(() => expect(update.installieren).toHaveBeenCalledTimes(1));
    unmount();
    await act(async () => antwort.erfuellen({ ok: false, text: "Signatur passt nicht." }));
    expect(container.innerHTML).toBe("");
    expect(fehler).not.toHaveBeenCalled();
  });

  it("Nach Updates suchen lädt neu und ist danach 10 Sekunden gesperrt", async () => {
    vi.useFakeTimers();
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    render(<UpdatesAbschnitt />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(kernJson).toHaveBeenCalledTimes(1);
    const knopf = suchen();
    fireEvent.click(knopf);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(kernJson).toHaveBeenCalledTimes(2);
    expect(knopf.getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByText(/Nach Updates suchen geht einmal je 10 Sekunden/)).toBeTruthy();
    fireEvent.click(knopf);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9_980);
    });
    expect(kernJson).toHaveBeenCalledTimes(2);
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

  it("nach einem gestarteten Update ruht alles: Wird installiert, keine Suche, kein zweiter Aufruf, der Fokus geht zu Nach Updates suchen", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    const user = await zeige();
    await user.click(installieren());
    await waitFor(() => expect(zustand().textContent).toContain("Die App installiert das Update und startet danach neu."));
    expect(suchen().getAttribute("aria-disabled")).toBe("true");
    expect(document.activeElement).toBe(suchen());
    const aufrufe = vi.mocked(kernJson).mock.calls.length;
    await user.click(suchen());
    await act(async () => updatesLaden());
    expect(vi.mocked(kernJson).mock.calls.length).toBe(aufrufe);
    await act(async () => updatesInstallieren({ version: "0.8.0", manifest: MANIFEST.manifest, signatur: SIGNATUR }));
    expect(update.installieren).toHaveBeenCalledTimes(1);
  });

  it("der Speicher ist gemeinsam: Ist schon geprüft (etwa vom Pop-up), lädt der Abschnitt nicht noch einmal und zeigt das Angebot gleich", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen();
    await act(async () => updatesLaden());
    expect(kernJson).toHaveBeenCalledTimes(1);
    render(<UpdatesAbschnitt />);
    await act(async () => undefined);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 5));
    });
    expect(kernJson).toHaveBeenCalledTimes(1);
    expect(zustand().textContent).toContain("Update verfügbar (Version 0.8.0)");
  });

  it("läuft eine Installation (vom Pop-up angestoßen), zeigt der Abschnitt Wird installiert und sperrt seine Knöpfe", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    const update = appSetzen();
    const antwort = spaeter<unknown>();
    update.installieren.mockReturnValue(antwort.versprechen);
    await zeige();
    await act(async () => {
      void updatesInstallieren({ version: "0.8.0", manifest: MANIFEST.manifest, signatur: SIGNATUR });
    });
    await waitFor(() => expect(zustand().textContent).toContain("Wird installiert"));
    expect(installieren().getAttribute("aria-disabled")).toBe("true");
    expect(suchen().getAttribute("aria-disabled")).toBe("true");
    await userEvent.setup().click(installieren()); // ein Klick auf den gesperrten Knopf ruft die App kein zweites Mal
    expect(update.installieren).toHaveBeenCalledTimes(1);
    await act(async () => antwort.erfuellen({ ok: false, text: "Abgebrochen.", abgebrochen: true }));
    expect(updates.get().phase.art).toBe("ruhe");
  });

  it("Überschriften: die Blöcke tragen in den Einstellungen die Stufe 5, nie eine übersprungene", async () => {
    kernAntwortet({ "/installer": MANIFEST });
    appSetzen({ version: undefined, update: undefined });
    render(
      <UeberschriftVersatz value={1}>
        <UpdatesAbschnitt />
      </UeberschriftVersatz>,
    );
    await screen.findByTestId("installer-download");
    expect(screen.getByRole("heading", { level: 5, name: "Version" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 5, name: "Installer" })).toBeTruthy();
    expect(screen.queryAllByRole("heading", { level: 6 })).toHaveLength(0);
    expect(screen.queryAllByRole("heading", { level: 4 })).toHaveLength(0);
  });
});

describe("UpdatesAbschnitt im Browser", () => {
  beforeEach(() => {
    updatesZuruecksetzen();
    vi.mocked(kernJson).mockReset();
    vi.mocked(accessToken).mockReset().mockResolvedValue(TOKEN);
    delete window.wamoDesktop;
  });

  it("ein ruhiger Satz und der Installer, kein Update-Knopf, kein Abruf des Servers", async () => {
    render(<UpdatesAbschnitt />);
    expect(screen.getByText(/Updates installiert die Desktop-App/)).toBeTruthy();
    expect(screen.getByTestId("installer-download")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Update installieren" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Nach Updates suchen" })).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    await act(async () => undefined);
    expect(kernJson).not.toHaveBeenCalled();
    expect(accessToken).not.toHaveBeenCalled();
  });

  it("Überschriften: Stufe 5 in den Einstellungen", () => {
    render(
      <UeberschriftVersatz value={1}>
        <UpdatesAbschnitt />
      </UeberschriftVersatz>,
    );
    expect(screen.getByRole("heading", { level: 5, name: "Im Browser" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 5, name: "Installer" })).toBeTruthy();
    expect(screen.queryAllByRole("heading", { level: 6 })).toHaveLength(0);
  });
});
