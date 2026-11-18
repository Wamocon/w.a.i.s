// Komponententest des Blocks "Rechte der GitHub-Zugänge" (components/einstellungen/GithubRechte.tsx, nur Admin): Liste laden, Kästchen
// je erlaubbarem Recht, Speichern nur bei einer Änderung, Fehler des Kerns. Der Kern (lib/kernApi.ts) ist durch eine Attrappe ersetzt.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { KernFehler, kernJson } from "@/lib/kernApi";
import { GithubRechte } from "./GithubRechte";

vi.mock("@/lib/kernApi", async (original) => {
  const echt = await original<typeof import("@/lib/kernApi")>();
  return { ...echt, kernJson: vi.fn() };
});

const ID = "00000000-0000-4000-8000-0000000027b1";
const liste = (scopes_ausnahmen: string[] = []) => ({
  personen: [{ user_id: ID, name: "Person Eins", rolle: "mitglied", aktiv: true, scopes_ausnahmen, hinterlegt: false, art: null, login: null, ablauf: null }],
  erlaubbar: ["workflow", "gist", "admin:org"],
  nie: ["delete_repo", "site_admin", "admin:enterprise"],
});

describe("GithubRechte", () => {
  beforeEach(() => vi.mocked(kernJson).mockReset());

  it("erlaubt einer Person ein Recht und speichert nur die Änderung", async () => {
    vi.mocked(kernJson).mockResolvedValueOnce(liste()).mockResolvedValueOnce({ user_id: ID, scopes_ausnahmen: ["gist"] });
    const user = userEvent.setup();
    render(<GithubRechte />);
    const person = within((await screen.findByText("Person Eins")).closest("li") as HTMLElement);
    expect(person.getByText(/kein Token hinterlegt; strenger Standard/)).toBeTruthy();
    expect(person.queryByText(/delete_repo/)).toBeNull();
    const speichern = person.getByRole("button", { name: "Speichern" });
    expect(speichern.getAttribute("aria-disabled")).toBe("true");
    await user.click(person.getByRole("checkbox", { name: /gist: Gists/ }));
    await user.click(speichern);
    expect(kernJson).toHaveBeenLastCalledWith("/admin/github-rechte", "POST", { user_id: ID, scopes_ausnahmen: ["gist"] });
    expect((await person.findByRole("status")).textContent).toContain("Gespeichert.");
    expect(person.getByText(/zusätzlich erlaubt: gist/)).toBeTruthy();
    expect(speichern.getAttribute("aria-disabled")).toBe("true");
  });

  it("zeigt die Ablehnung des Kerns als Satz", async () => {
    vi.mocked(kernJson).mockResolvedValueOnce(liste()).mockRejectedValueOnce(new KernFehler(400, "Dieses Profil gibt es nicht."));
    const user = userEvent.setup();
    render(<GithubRechte />);
    const person = within((await screen.findByText("Person Eins")).closest("li") as HTMLElement);
    await user.click(person.getByRole("checkbox", { name: /workflow/ }));
    await user.click(person.getByRole("button", { name: "Speichern" }));
    expect((await person.findByRole("alert")).textContent).toContain("Dieses Profil gibt es nicht.");
  });

  it("nur für Admins und neu laden", async () => {
    vi.mocked(kernJson).mockRejectedValueOnce(new KernFehler(403, "nein")).mockResolvedValueOnce({ personen: [], erlaubbar: [], nie: [] });
    const user = userEvent.setup();
    render(<GithubRechte />);
    expect((await screen.findByRole("alert")).textContent).toBe("Die Rechte der GitHub-Zugänge stellen nur Admins ein.");
    await user.click(screen.getByRole("button", { name: "Neu laden" }));
    expect(await screen.findByText("Keine Profile.")).toBeTruthy();
  });
});
