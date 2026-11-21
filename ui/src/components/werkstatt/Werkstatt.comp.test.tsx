// Komponententest des Rahmens der Werkstatt (components/werkstatt/Werkstatt.tsx): Zugang, Bereiche per Hash, Fokus, Fehler.
// Die Bereiche und der Dienst (lib/werkstattApi.ts) sind durch Attrappen ersetzt.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WerkstattFehler, ichLaden } from "@/lib/werkstattApi";
import { eigenerFehler, fehlerBild } from "@/lib/werkstattFehler";
import { Werkstatt } from "./Werkstatt";

vi.mock("@/lib/werkstattApi", async (original) => {
  const echt = await original<typeof import("@/lib/werkstattApi")>();
  return { ...echt, ichLaden: vi.fn() };
});
vi.mock("./Dashboards", () => ({ Dashboards: () => <p>Bereich Dashboards</p> }));
vi.mock("./LaborPlaner", () => ({ LaborPlaner: () => <p>Bereich Labor</p> }));
vi.mock("./Karten", () => ({ Karten: ({ onFaktor }: { onFaktor: () => void }) => <button onClick={onFaktor}>Bereich Karten</button> }));
vi.mock("./Protokolle", () => ({ Protokolle: () => <p>Bereich Protokolle</p> }));

const sitzung = (email: string | null = "admin@beispiel.test") => ({ signOut: vi.fn(), email });
const ADMIN = { rolle: "admin" as const, aal2AlterS: 720, erlaubt: true };

function hash(neu: string) {
  act(() => {
    window.location.hash = neu;
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
}

beforeEach(() => {
  window.location.hash = "";
});
afterEach(() => {
  window.location.hash = "";
});

describe("Zugang", () => {
  it("ein Laborkonto bekommt Kein Zugriff und ruft den Dienst nie", async () => {
    render(<Werkstatt sitzung={sitzung("labor-03@wamo.test")} />);
    expect(await screen.findByRole("heading", { level: 1, name: "Kein Zugriff" })).toBeTruthy();
    expect(screen.getByText(/Laborprofil gibt es keinen Zugang/)).toBeTruthy();
    expect(ichLaden).not.toHaveBeenCalled();
  });

  it("ein Mitglied und ein Admin außerhalb der Liste bekommen Kein Zugriff", async () => {
    vi.mocked(ichLaden).mockResolvedValueOnce({ rolle: "mitglied", aal2AlterS: 10, erlaubt: false });
    const { unmount } = render(<Werkstatt sitzung={sitzung()} />);
    expect(await screen.findByRole("heading", { name: "Kein Zugriff" })).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: "Bereiche der Werkstatt" })).toBeNull();
    unmount();
    vi.mocked(ichLaden).mockResolvedValueOnce({ rolle: "admin", aal2AlterS: 10, erlaubt: false });
    render(<Werkstatt sitzung={sitzung()} />);
    expect(await screen.findByRole("heading", { name: "Kein Zugriff" })).toBeTruthy();
  });

  it("403 des Dienstes (nicht berechtigt) zeigt Kein Zugriff, mit Abmelden", async () => {
    vi.mocked(ichLaden).mockRejectedValue(new WerkstattFehler(fehlerBild(403, "nicht_berechtigt", null)));
    const s = sitzung();
    const user = userEvent.setup();
    render(<Werkstatt sitzung={s} />);
    expect(await screen.findByRole("heading", { name: "Kein Zugriff" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Abmelden" }));
    expect(s.signOut).toHaveBeenCalledTimes(1);
  });

  it("ein Netzfehler ist kein Zugriffsfehler: Satz, Neu laden, dann der Rahmen", async () => {
    vi.mocked(ichLaden).mockRejectedValueOnce(new WerkstattFehler(eigenerFehler("netz"))).mockResolvedValueOnce(ADMIN);
    const user = userEvent.setup();
    render(<Werkstatt sitzung={sitzung()} />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/nicht erreichbar/);
    await user.click(screen.getByRole("button", { name: "Neu laden" }));
    expect(await screen.findByRole("navigation", { name: "Bereiche der Werkstatt" })).toBeTruthy();
  });
});

describe("Rahmen eines Admins", () => {
  beforeEach(() => vi.mocked(ichLaden).mockResolvedValue(ADMIN));

  it("vier Bereiche als Links, die Dashboards sind der Anfang, Überschrift der Ebene 1", async () => {
    render(<Werkstatt sitzung={sitzung()} />);
    const nav = await screen.findByRole("navigation", { name: "Bereiche der Werkstatt" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((l) => l.textContent?.replace(/lesen|schreiben/, ""))).toEqual(["Dashboards", "Labor-Planer", "Karten und Use Cases", "Protokolle"]);
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["#dashboard", "#labor", "#karten", "#protokolle"]);
    expect(links[0].getAttribute("aria-current")).toBe("page");
    expect(links.slice(1).every((l) => !l.hasAttribute("aria-current"))).toBe(true);
    expect(screen.getByRole("heading", { level: 1, name: "Dashboards" })).toBeTruthy();
    expect(screen.getByText("Bereich Dashboards")).toBeTruthy();
    expect(screen.getByText("Admin, Erlaubnisliste")).toBeTruthy();
    expect(screen.getByText("Zweiter Faktor vor 12 Minuten")).toBeTruthy();
  });

  it("der Hash wählt den Bereich, setzt aria-current und den Fokus auf die Überschrift", async () => {
    window.location.hash = "#labor";
    render(<Werkstatt sitzung={sitzung()} />);
    expect(await screen.findByText("Bereich Labor")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Labor-Planer/ }).getAttribute("aria-current")).toBe("page");
    hash("#protokolle");
    expect(await screen.findByText("Bereich Protokolle")).toBeTruthy();
    expect(screen.queryByText("Bereich Labor")).toBeNull();
    const h1 = screen.getByRole("heading", { level: 1, name: "Protokolle" });
    await waitFor(() => expect(document.activeElement).toBe(h1));
    expect(document.title).toBe("Protokolle | Werkstatt | W.A.I.S.");
    hash("#gibtesnicht");
    expect(await screen.findByText("Bereich Dashboards")).toBeTruthy();
  });

  it("der Sprunglink setzt den Fokus in den Inhalt und ändert die Adresse nicht", async () => {
    const user = userEvent.setup();
    window.location.hash = "#karten";
    render(<Werkstatt sitzung={sitzung()} />);
    await screen.findByRole("navigation", { name: "Bereiche der Werkstatt" });
    await user.click(screen.getByRole("button", { name: "Zum Inhalt springen" }));
    expect(document.activeElement?.id).toBe("ws-inhalt");
    expect(window.location.hash).toBe("#karten");
  });

  it("nach einem frischen Code lädt der Rahmen den Zugang neu (Alter des zweiten Faktors)", async () => {
    const user = userEvent.setup();
    window.location.hash = "#karten";
    vi.mocked(ichLaden).mockResolvedValueOnce(ADMIN).mockResolvedValueOnce({ ...ADMIN, aal2AlterS: 5 });
    render(<Werkstatt sitzung={sitzung()} />);
    await user.click(await screen.findByRole("button", { name: "Bereich Karten" }));
    expect(await screen.findByText("Zweiter Faktor vor 5 Sekunden")).toBeTruthy();
  });

  it("Abmelden in der Seitenleiste ruft die Abmeldung der Sitzung", async () => {
    const s = sitzung();
    const user = userEvent.setup();
    render(<Werkstatt sitzung={s} />);
    await user.click(await screen.findByRole("button", { name: "Abmelden" }));
    expect(s.signOut).toHaveBeenCalledTimes(1);
  });
});
