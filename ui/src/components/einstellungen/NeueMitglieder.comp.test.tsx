// Komponententest des Abschnitts "Neue Mitglieder" (components/einstellungen/NeueMitglieder.tsx): Laden, Liste, Fehler, Neu laden.
// Der Kern (lib/kernApi.ts) ist durch eine Attrappe ersetzt.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { KernFehler, kernJson } from "@/lib/kernApi";
import { NeueMitglieder } from "./NeueMitglieder";

vi.mock("@/lib/kernApi", async (original) => {
  const echt = await original<typeof import("@/lib/kernApi")>();
  return { ...echt, kernJson: vi.fn() };
});

const zeile = (teil: Record<string, unknown> = {}) => ({
  user_id: "00000000-0000-4000-8000-0000000022b1",
  anzeigename: "Person A",
  rolle: "mitglied",
  aktiv: true,
  angelegt: "2026-11-15T09:00:00+00:00",
  letzte_anmeldung: "2026-11-16T08:00:00+00:00",
  faktor_bestaetigt: true,
  passwort_stand: null,
  geraet_stand: "beantragt",
  modellzugang: "token",
  stimmabdruck: false,
  ...teil,
});

describe("NeueMitglieder", () => {
  beforeEach(() => vi.mocked(kernJson).mockReset());

  it("zeigt je Person den nächsten Schritt, die Schritte mit Wort und den Modellzugang", async () => {
    vi.mocked(kernJson).mockResolvedValue({
      mitglieder: [zeile(), zeile({ user_id: "00000000-0000-4000-8000-0000000022b2", anzeigename: "Person B", geraet_stand: "aktiv", stimmabdruck: true })],
    });
    render(<NeueMitglieder />);
    expect(await screen.findByText("1 von 2 Profilen fertig eingerichtet.")).toBeTruthy();
    expect(kernJson).toHaveBeenCalledWith("/admin/neue-mitglieder");
    const a = within(screen.getByText("Person A").closest("li") as HTMLElement);
    expect(a.getByText("Der Laptop wartet auf deine Freigabe (Geräte und PC).")).toBeTruthy();
    expect(a.getByText(/Laptop eingerichtet: fehlt/)).toBeTruthy();
    expect(a.getByText(/Passwort gewechselt: noch nicht prüfbar/)).toBeTruthy();
    expect(a.getByText(/eigener Claude-Code-Token/)).toBeTruthy();
    const b = within(screen.getByText("Person B").closest("li") as HTMLElement);
    expect(b.getByText("Fertig eingerichtet.")).toBeTruthy();
  });

  it("nennt einen Fehler des Kerns als ruhigen Satz und lädt auf Wunsch neu", async () => {
    vi.mocked(kernJson).mockRejectedValueOnce(new KernFehler(403, "nein")).mockResolvedValueOnce({ mitglieder: [] });
    const user = userEvent.setup();
    render(<NeueMitglieder />);
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Die Übersicht ist nur für Admins.");
    await user.click(screen.getByRole("button", { name: "Neu laden" }));
    expect(await screen.findByText("Keine Profile.")).toBeTruthy();
    expect(kernJson).toHaveBeenCalledTimes(2);
  });

  it("eine unerwartete Antwort zeigt keine Liste", async () => {
    vi.mocked(kernJson).mockResolvedValue({ etwas: 1 });
    render(<NeueMitglieder />);
    expect(await screen.findByText("Unerwartete Antwort des Kerns.")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Neue Mitglieder" })).toBeNull();
  });
});
