// Komponententest der Karte "GitHub-Zugang" (components/GithubZugang.tsx): Stand laden, Token hinterlegen (Feld wird sofort geleert, der
// Wert erscheint nie), Fehler des Kerns, falsche Form ohne Anfrage, nicht verfügbar mit Grund, Löschen mit Rückfrage.
// Der Kern (lib/kernApi.ts) ist durch eine Attrappe ersetzt. Ausführen im Ordner ui/:  npm run test:komponenten
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { KernFehler, kernJson } from "@/lib/kernApi";
import { GithubZugang } from "./GithubZugang";

vi.mock("@/lib/kernApi", async (original) => {
  const echt = await original<typeof import("@/lib/kernApi")>();
  return { ...echt, kernJson: vi.fn() };
});

const KLASSISCH = "ghp_" + "Kx7".repeat(12);

const stand = (teil: Record<string, unknown> = {}) => ({
  type: "github_zugang",
  aktion: "stand",
  verfuegbar: true,
  grund: null,
  hinterlegt: false,
  scopes_ausnahmen: [],
  scopes: [],
  bereit: false,
  ...teil,
});

const hinterlegt = (teil: Record<string, unknown> = {}) =>
  stand({
    hinterlegt: true, art: "klassisch", login: "person-eins", ende: "Kx7K", scopes: ["repo"], ablauf: "2027-02-16",
    geprueft: "2026-11-18T12:00+00:00", bereit: true, ...teil,
  });

describe("GithubZugang", () => {
  beforeEach(() => vi.mocked(kernJson).mockReset());

  it("hinterlegt ein Token, leert das Feld sofort und zeigt nur Konto, Art und Ende", async () => {
    vi.mocked(kernJson)
      .mockResolvedValueOnce(stand())
      .mockResolvedValueOnce(hinterlegt({ aktion: "speichern", ok: "Gespeichert. Konto person-eins, gültig bis 2027-02-16." }));
    const user = userEvent.setup();
    const { container } = render(<GithubZugang />);
    expect(await screen.findByText("Kein GitHub-Token hinterlegt.")).toBeTruthy();
    expect(kernJson).toHaveBeenCalledWith("/github-zugang");
    const feld = screen.getByLabelText("GitHub-Token") as HTMLInputElement;
    expect(feld.type).toBe("password");
    await user.type(feld, KLASSISCH);
    await user.click(screen.getByRole("button", { name: "Hinterlegen" }));
    expect(feld.value).toBe("");
    expect(await screen.findByText(/Hinterlegt: Konto person-eins, klassisch, endet auf …Kx7K, gültig bis 16\.02\.2027\./)).toBeTruthy();
    expect(kernJson).toHaveBeenLastCalledWith("/github-zugang", "POST", { aktion: "speichern", token: KLASSISCH });
    expect(screen.getByRole("status").textContent).toContain("Gespeichert.");
    expect(container.innerHTML).not.toContain(KLASSISCH);
    expect(container.innerHTML).not.toContain(KLASSISCH.slice(4, 20));
  });

  it("ein Fehler des Kerns erscheint als Satz, das Feld bleibt leer", async () => {
    vi.mocked(kernJson)
      .mockResolvedValueOnce(stand())
      .mockResolvedValueOnce(stand({ aktion: "speichern", fehler: "GitHub lehnt das Token ab (401): Es ist ungültig." }));
    const user = userEvent.setup();
    const { container } = render(<GithubZugang />);
    const feld = (await screen.findByLabelText("GitHub-Token")) as HTMLInputElement;
    await user.type(feld, KLASSISCH);
    await user.click(screen.getByRole("button", { name: "Hinterlegen" }));
    expect((await screen.findByRole("alert")).textContent).toContain("401");
    expect(feld.value).toBe("");
    expect(container.innerHTML).not.toContain(KLASSISCH);
  });

  it("falsche Form: Satz sofort, keine Anfrage", async () => {
    vi.mocked(kernJson).mockResolvedValueOnce(stand());
    const user = userEvent.setup();
    render(<GithubZugang />);
    const feld = await screen.findByLabelText("GitHub-Token");
    await user.type(feld, "gho_" + "a".repeat(36));
    expect((await screen.findByRole("alert")).textContent).toContain("kein persönliches Zugriffstoken");
    await user.click(screen.getByRole("button", { name: "Hinterlegen" }));
    expect(kernJson).toHaveBeenCalledTimes(1);
  });

  it("nicht verfügbar: Grund statt Formular, Löschen geht trotzdem", async () => {
    vi.mocked(kernJson)
      .mockResolvedValueOnce(hinterlegt({ verfuegbar: false, grund: "Persönliche GitHub-Zugänge sind noch nicht eingeschaltet.", bereit: false }))
      .mockResolvedValueOnce(stand({ aktion: "loeschen", verfuegbar: false, grund: "Persönliche GitHub-Zugänge sind noch nicht eingeschaltet.",
                                     ok: "Gelöscht. Bitte das Token auch bei GitHub widerrufen." }));
    const user = userEvent.setup();
    const { container } = render(<GithubZugang />);
    expect(await screen.findByText("Persönliche GitHub-Zugänge sind noch nicht eingeschaltet.")).toBeTruthy();
    expect(container.querySelector("input")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Löschen" }));
    await user.click(screen.getByRole("button", { name: "Wirklich löschen" }));
    expect(await screen.findByText("Kein GitHub-Token hinterlegt.")).toBeTruthy();
    expect(kernJson).toHaveBeenLastCalledWith("/github-zugang", "POST", { aktion: "loeschen" });
    expect(screen.getByRole("status").textContent).toContain("widerrufen");
  });

  it("zeigt ein Problem des hinterlegten Tokens und prüft erneut", async () => {
    vi.mocked(kernJson)
      .mockResolvedValueOnce(hinterlegt({ bereit: false, problem: "Das Token hat Rechte, die für dein Profil nicht freigegeben sind: gist." }))
      .mockResolvedValueOnce(hinterlegt({ aktion: "pruefen", ok: "Das Token ist gültig." }));
    const user = userEvent.setup();
    render(<GithubZugang />);
    expect(await screen.findByText(/Wird gerade nicht benutzt: .*gist/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Erneut prüfen" }));
    expect((await screen.findByRole("status")).textContent).toContain("Das Token ist gültig.");
    expect(screen.queryByText(/Wird gerade nicht benutzt/)).toBeNull();
    expect(kernJson).toHaveBeenLastCalledWith("/github-zugang", "POST", { aktion: "pruefen" });
  });

  it("Kern nicht erreichbar: Satz und erneuter Versuch", async () => {
    vi.mocked(kernJson).mockRejectedValueOnce(new KernFehler(0, "Zeitüberschreitung")).mockResolvedValueOnce(stand());
    const user = userEvent.setup();
    render(<GithubZugang />);
    expect((await screen.findByRole("alert")).textContent).toContain("Zeitüberschreitung");
    await user.click(screen.getByRole("button", { name: "Erneut versuchen" }));
    expect(await screen.findByText("Kein GitHub-Token hinterlegt.")).toBeTruthy();
  });
});
