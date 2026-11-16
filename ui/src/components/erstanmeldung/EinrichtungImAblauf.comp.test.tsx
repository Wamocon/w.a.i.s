// Komponententest der Erstanmeldung mit den Schritten des Ausrollens (components/erstanmeldung/schritte.tsx, Entscheidung D2): nach dem
// Passwort zuerst der Claude-Code-Token, dann der API-Schlüssel (beide überspringbar), dann die Zusammenfassung und zuletzt der Installer.
// Ist das Profil vom Admin auf Hausmodelle festgelegt, entfallen die beiden Schlüsselschritte; in der Desktop-App entfällt der Installer.
// Kern und Passwortschritt sind Attrappen, es geht nichts ins Netz. Ausführen im Ordner ui/:  npm run test:komponenten
import { createHash } from "node:crypto";
import { createElement } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Erstanmeldung } from "@/components/erstanmeldung/Erstanmeldung";
import { ERSTANMELDUNG_SCHRITTE } from "@/components/erstanmeldung/schritte";
import type { ErstanmeldungKontext, ErstanmeldungSchritt } from "@/components/erstanmeldung/typen";
import { KernFehler } from "@/lib/kernApi";
import { resetWamo } from "@/lib/wamo";

const kern = vi.hoisted(() => ({ kernJson: vi.fn(), kernDateiStrom: vi.fn() }));
vi.mock("@/lib/kernApi", async (original) => ({
  ...(await original<typeof import("@/lib/kernApi")>()),
  kernJson: kern.kernJson,
  kernDateiStrom: kern.kernDateiStrom,
}));

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
const FELDER = {
  v: 1,
  produkt: "wais-desktop",
  version: "0.3.0",
  datei: "WAIS-Setup-0.3.0.exe",
  groesse: BYTES.length,
  sha256: createHash("sha256").update(BYTES).digest("hex"),
  bauzeit: "2026-11-16T08:00:00.000Z",
  commit: "0123456789".repeat(4),
};
const MANIFEST = { ...FELDER, manifest: JSON.stringify(FELDER), signatur: null };

let aktuellerStand: Roh = stand();

const kontext = {
  userId: "11111111-2222-3333-4444-555555555555",
  standStart: "offen",
  anzeigename: "W.A.I.S.",
} as unknown as ErstanmeldungKontext;

/** Passwortschritt als Attrappe (sein eigener Test steht in Erstanmeldung.comp.test.tsx); der Rest ist die echte Liste. */
const passwortAttrappe: ErstanmeldungSchritt = {
  ...ERSTANMELDUNG_SCHRITTE[0],
  komponente: ({ weiter }) => createElement("button", { type: "button", onClick: weiter }, "Passwort gesetzt"),
};
const liste = () => [passwortAttrappe, ...ERSTANMELDUNG_SCHRITTE.slice(1)];

beforeEach(() => {
  resetWamo();
  aktuellerStand = stand();
  kern.kernJson.mockReset().mockImplementation(async (pfad: string, methode = "GET", body?: Roh) => {
    if (pfad === "/modellzugang" && methode === "GET") return aktuellerStand;
    if (pfad === "/modellzugang" && methode === "POST" && body?.aktion === "hinterlegen") {
      aktuellerStand = stand({ ...aktuellerStand, aktion: "hinterlegen", code_hinterlegt: true, code_ende: "xxxx" });
      return aktuellerStand;
    }
    if (pfad === "/installer") return MANIFEST;
    throw new KernFehler(404, "unbekannt");
  });
  kern.kernDateiStrom.mockReset();
});

afterEach(() => {
  delete (window as unknown as { wamoDesktop?: unknown }).wamoDesktop;
});

const leiste = () => screen.getAllByRole("listitem").filter((li) => li.classList.contains("ea-punkt"));

describe("Erstanmeldung mit den Schritten des Ausrollens", () => {
  it("die Liste: Passwort, Token, API-Schlüssel, Zusammenfassung, Installer; nur die Schlüssel und der Installer sind überspringbar", () => {
    expect(ERSTANMELDUNG_SCHRITTE.map((s) => s.id)).toEqual(["passwort", "token", "api", "zusammenfassung", "installer"]);
    expect(ERSTANMELDUNG_SCHRITTE.map((s) => s.ueberspringbar)).toEqual([false, true, true, false, true]);
    for (const s of ERSTANMELDUNG_SCHRITTE) expect(typeof s.komponente).toBe("function");
  });

  it("führt nach dem Passwort durch Token, API-Schlüssel, Zusammenfassung und Installer; beide Schlüssel übersprungen heißt Hausmodelle", async () => {
    const user = userEvent.setup();
    const fertig = vi.fn();
    render(<Erstanmeldung kontext={kontext} fertig={fertig} schritte={liste()} />);
    expect(leiste().map((li) => li.textContent?.replace(/\s*\(.*\)$/, ""))).toEqual(
      ["1Passwort", "2Token", "3API-Schlüssel", "4Überblick", "5Installer"],
    );
    await user.click(await screen.findByRole("button", { name: "Passwort gesetzt" }));

    expect(await screen.findByRole("heading", { name: "Claude-Code-Token" })).toBeTruthy();
    expect(screen.getByText(/Hast du ein Claude-Code-Konto \(Max-Tarif\)\?/)).toBeTruthy();
    await user.click(await screen.findByRole("button", { name: "Überspringen" }));

    expect(await screen.findByRole("heading", { name: "API-Schlüssel" })).toBeTruthy();
    expect(screen.getByText(/Hast du einen API-Schlüssel\?/)).toBeTruthy();
    await user.click(await screen.findByRole("button", { name: "Überspringen" }));

    expect(await screen.findByRole("heading", { name: "So arbeitet W.A.I.S. für dich" })).toBeTruthy();
    expect(await screen.findByText(/Hausmodelle für alles/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Weiter" }));

    expect(await screen.findByRole("heading", { name: "Installer laden" })).toBeTruthy();
    expect(await screen.findByText(FELDER.sha256)).toBeTruthy();
    expect(fertig).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Weiter" }));
    await waitFor(() => expect(fertig).toHaveBeenCalledTimes(1));
    // nichts wurde hinterlegt
    expect(kern.kernJson.mock.calls.filter((c) => c[1] === "POST")).toEqual([]);
  });

  it("vom Admin auf Hausmodelle festgelegt: nach dem Passwort direkt die Zusammenfassung, keine Schlüsselschritte", async () => {
    aktuellerStand = stand({ festgelegt: true, quelle: "festgelegt" });
    const user = userEvent.setup();
    render(<Erstanmeldung kontext={kontext} fertig={vi.fn()} schritte={liste()} />);
    await user.click(await screen.findByRole("button", { name: "Passwort gesetzt" }));
    expect(await screen.findByRole("heading", { name: "So arbeitet W.A.I.S. für dich" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Claude-Code-Token" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "API-Schlüssel" })).toBeNull();
  });

  it("ein schon hinterlegter Token wird übergangen (zum Beispiel nach einem Neuladen mitten im Ablauf)", async () => {
    aktuellerStand = stand({ code_hinterlegt: true, code_ende: "abcd" });
    const user = userEvent.setup();
    render(<Erstanmeldung kontext={kontext} fertig={vi.fn()} schritte={liste()} />);
    await user.click(await screen.findByRole("button", { name: "Passwort gesetzt" }));
    expect(await screen.findByRole("heading", { name: "API-Schlüssel" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Claude-Code-Token" })).toBeNull();
  });

  it("ist der Stand nicht lesbar, kommt der Schritt trotzdem (lieber zeigen als verschweigen)", async () => {
    kern.kernJson.mockImplementation(async (pfad: string) => {
      if (pfad === "/modellzugang") throw new KernFehler(503, "weg");
      if (pfad === "/installer") return MANIFEST;
      throw new KernFehler(404, "unbekannt");
    });
    const user = userEvent.setup();
    render(<Erstanmeldung kontext={kontext} fertig={vi.fn()} schritte={liste()} />);
    await user.click(await screen.findByRole("button", { name: "Passwort gesetzt" }));
    expect(await screen.findByRole("heading", { name: "Claude-Code-Token" })).toBeTruthy();
  });

  it("in der Desktop-App entfällt der Installer: nach der Zusammenfassung ist der Ablauf fertig", async () => {
    (window as unknown as { wamoDesktop?: unknown }).wamoDesktop = { isDesktop: true, levels: () => undefined };
    aktuellerStand = stand({ festgelegt: true, quelle: "festgelegt" });
    const user = userEvent.setup();
    const fertig = vi.fn();
    render(<Erstanmeldung kontext={kontext} fertig={fertig} schritte={liste()} />);
    await user.click(await screen.findByRole("button", { name: "Passwort gesetzt" }));
    await user.click(await screen.findByRole("button", { name: "Weiter" }));
    await waitFor(() => expect(fertig).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("heading", { name: "Installer laden" })).toBeNull();
  });
});
