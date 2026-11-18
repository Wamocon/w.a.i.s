// Komponententest der Mikrofonwahl in den Einstellungen (components/einstellungen/Abschnitte.tsx, lib/mikrofon.ts), Befund 17.11.2026:
// Im Browser lief ein anderes Mikrofon als in der Desktop-App, ohne dass man es sah. Die Auswahl nennt das Standardgerät (im Browser das
// des Browsers) mit Namen, zeigt die gespeicherte Wahl dieser Person und was läuft, sagt, wenn das gewählte Gerät fehlt, und bietet ohne
// Freigabe einen Knopf, der die Namen sichtbar macht. Dazu der Knopf "Mikrofon wählen" am Hinweis der Pegelwarnung und im Abschnitt Stimme.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({ getSupabase: () => null, accessToken: async () => null }));

import { FehlerAnzeige } from "@/components/FehlerAnzeige";
import { SpracheAbschnitt } from "@/components/einstellungen/Abschnitte";
import { StimmeAbschnitt } from "@/components/einstellungen/StimmeAbschnitt";
import type { Mikrofon } from "@/lib/mikrofon";
import { nutzerSetzen } from "@/lib/nutzer";
import { LEISE_TEXT } from "@/lib/pegelWarnung";
import { ANDERES_MIKROFON_TEXT } from "@/lib/stimmMikrofon";
import { resetWamo, wamo } from "@/lib/wamo";

const ID = "0b7f3c1e-2d4a-4c55-9a10-1a2b3c4d5e6f";
type Fenster = { wamoDesktop?: unknown };
const LISTE: Mikrofon[] = [
  { id: "a", label: "Mikrofonarray (Realtek)", standard: true },
  { id: "b", label: "Headset (USB)" },
];

const auswahl = () => screen.getByLabelText("Mikrofon") as HTMLSelectElement;
const optionen = () => Array.from(auswahl().options).map((o) => o.textContent);
/** Liste laden lassen (useMikrofonListe fragt asynchron) */
const geladen = () => act(async () => undefined);

function zeigen(laden: () => Promise<Mikrofon[]> = async () => LISTE, waehlen = vi.fn<(id: string) => boolean>(() => true)) {
  render(<SpracheAbschnitt mikrofone={laden} mikrofonWaehlen={waehlen} />);
  return waehlen;
}

let getUserMedia: ReturnType<typeof vi.fn>;

beforeEach(() => {
  resetWamo();
  localStorage.clear();
  nutzerSetzen({ id: ID, email: "niko@wamocon.com" });
  window.location.hash = "";
  getUserMedia = vi.fn();
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia, addEventListener: vi.fn(), removeEventListener: vi.fn() },
  });
});
afterEach(() => {
  delete (window as unknown as Fenster).wamoDesktop;
  nutzerSetzen({ id: null, email: null });
});

describe("Mikrofonwahl in Sprache und Ton", () => {
  it("nennt das Standardgerät des Browsers mit Namen und sagt, was beim nächsten Gespräch läuft", async () => {
    zeigen();
    await geladen();
    expect(optionen()).toEqual(["Standardgerät des Browsers (Mikrofonarray (Realtek))", "Mikrofonarray (Realtek)", "Headset (USB)"]);
    expect(auswahl().value).toBe("");
    expect(screen.getByText(/Beim nächsten Gespräch: Standardgerät des Browsers \(Mikrofonarray \(Realtek\)\)/)).toBeTruthy();
  });

  it("in der Desktop-App heißt es Standardgerät von Windows", async () => {
    (window as unknown as Fenster).wamoDesktop = { isDesktop: true };
    zeigen();
    await geladen();
    expect(optionen()[0]).toBe("Standardgerät von Windows (Mikrofonarray (Realtek))");
  });

  it("zeigt die gespeicherte Wahl dieser Person, nicht die einer anderen", async () => {
    localStorage.setItem(`wamo.mikrofon.${ID}`, "b");
    localStorage.setItem("wamo.mikrofon.9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b", "a");
    zeigen();
    await geladen();
    expect(auswahl().value).toBe("b");
    expect(screen.getByText(/Beim nächsten Gespräch: Headset \(USB\)\. Die Wahl gilt für dich auf diesem Gerät\./)).toBeTruthy();
  });

  it("Rückfall: fehlt das gewählte Gerät, zeigt die Auswahl das Standardgerät und sagt es", async () => {
    localStorage.setItem(`wamo.mikrofon.${ID}`, "weg");
    zeigen();
    await geladen();
    expect(auswahl().value).toBe("");
    expect(screen.getByText(/Dein gewähltes Mikrofon ist gerade nicht angeschlossen/)).toBeTruthy();
  });

  it("die Wahl geht an useWamo (Kennung des Geräts, leer für das Standardgerät)", async () => {
    const waehlen = zeigen();
    await geladen();
    const nutzer = userEvent.setup();
    await nutzer.selectOptions(auswahl(), "b");
    expect(waehlen).toHaveBeenLastCalledWith("b");
    await nutzer.selectOptions(auswahl(), "");
    expect(waehlen).toHaveBeenLastCalledWith("");
  });

  it("im Gespräch: nennt das Gerät, das gerade läuft", async () => {
    act(() => wamo.set((s) => ({ ...s, presence: "idle", mikrofon: "Headset (USB)" })));
    zeigen();
    await geladen();
    expect(screen.getByText("In Benutzung: Headset (USB). Ein Wechsel gilt sofort.")).toBeTruthy();
  });

  it("ohne Freigabe: Hinweis und Knopf; das Freigeben öffnet das Mikrofon nur kurz, danach erscheint die Liste mit Namen", async () => {
    const stopp = vi.fn();
    getUserMedia.mockResolvedValue({ getTracks: () => [{ stop: stopp }] });
    let freigegeben = false;
    zeigen(async () => (freigegeben ? LISTE : []));
    await geladen();
    expect(auswahl().disabled).toBe(true);
    expect(screen.getByText(/Die Namen der Mikrofone zeigt der Browser erst/)).toBeTruthy();
    freigegeben = true;
    await userEvent.setup().click(screen.getByRole("button", { name: "Mikrofon freigeben" }));
    await geladen();
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(stopp).toHaveBeenCalledTimes(1);
    expect(auswahl().disabled).toBe(false);
    expect(optionen()).toContain("Headset (USB)");
    expect(screen.queryByRole("button", { name: "Mikrofon freigeben" })).toBeNull();
  });

  it("still gestartete Sitzung (verbunden, kein Mikrofon offen): ohne Freigabe gibt es den Knopf, nicht 'keine Mikrofone gefunden'", async () => {
    act(() => wamo.set((s) => ({ ...s, presence: "idle", mikrofon: null })));
    zeigen(async () => []);
    await geladen();
    expect(screen.getByRole("button", { name: "Mikrofon freigeben" })).toBeTruthy();
    expect(screen.queryByText(/Keine Mikrofone gefunden/)).toBeNull();
  });

  it("Freigabe abgelehnt: ein Satz sagt, wo man sie erlaubt", async () => {
    getUserMedia.mockRejectedValue(Object.assign(new Error("nein"), { name: "NotAllowedError" }));
    zeigen(async () => []);
    await geladen();
    await userEvent.setup().click(screen.getByRole("button", { name: "Mikrofon freigeben" }));
    await geladen();
    expect(screen.getByRole("alert").textContent).toMatch(/Der Browser hat das Mikrofon nicht freigegeben/);
  });

  it("Laborsicht: die Mikrofonwahl gibt es dort genauso", async () => {
    render(<SpracheAbschnitt mikrofone={async () => LISTE} mikrofonWaehlen={() => true} nurMikrofon />);
    await geladen();
    expect(optionen()).toHaveLength(3);
  });
});

describe("Weg zur Mikrofonwahl", () => {
  it("Pegelwarnung: der Knopf am Hinweis öffnet Sprache und Ton und schließt den Hinweis", async () => {
    act(() => wamo.set((s) => ({ ...s, error: { art: "hinweis", text: LEISE_TEXT, aktion: "mikrofon_waehlen" } })));
    const onSchliessen = vi.fn();
    render(
      <FehlerAnzeige onRetry={vi.fn()} onAbmelden={vi.fn()} onSchliessen={onSchliessen} onMikrofone={async () => []} onMikrofonWaehlen={() => true} />,
    );
    expect(screen.getByRole("status").textContent).toContain(LEISE_TEXT);
    await userEvent.setup().click(screen.getByRole("button", { name: "Mikrofon wählen" }));
    expect(onSchliessen).toHaveBeenCalledTimes(1);
    expect(window.location.hash).toBe("#einstellungen/sprache");
  });

  it("andere Hinweise haben den Knopf nicht", () => {
    act(() => wamo.set((s) => ({ ...s, error: { art: "hinweis", text: "Gespräch beendet." } })));
    render(<FehlerAnzeige onRetry={vi.fn()} onAbmelden={vi.fn()} onSchliessen={vi.fn()} onMikrofone={async () => []} onMikrofonWaehlen={() => true} />);
    expect(screen.queryByRole("button", { name: "Mikrofon wählen" })).toBeNull();
  });

  it("Gerätewechsel: der Knopf am Hinweis öffnet das Einlernen und schließt den Hinweis", async () => {
    act(() =>
      wamo.set((s) => ({
        ...s,
        presence: "idle",
        stimme: { ...s.stimme, status: "bereit", modus: "streng" },
        error: { art: "hinweis", text: ANDERES_MIKROFON_TEXT, aktion: "neu_einlernen" },
      })),
    );
    const onSchliessen = vi.fn();
    render(
      <FehlerAnzeige onRetry={vi.fn()} onAbmelden={vi.fn()} onSchliessen={onSchliessen} onMikrofone={async () => []} onMikrofonWaehlen={() => true} />,
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Neu einlernen" }));
    expect(onSchliessen).toHaveBeenCalledTimes(1);
    expect(wamo.get().abdruck?.phase).toBe("einwilligung");
  });

  it("Gerätewechsel ohne laufendes Gespräch: der Knopf führt zum Abschnitt Stimme", async () => {
    act(() => wamo.set((s) => ({ ...s, error: { art: "hinweis", text: ANDERES_MIKROFON_TEXT, aktion: "neu_einlernen" } })));
    render(<FehlerAnzeige onRetry={vi.fn()} onAbmelden={vi.fn()} onSchliessen={vi.fn()} onMikrofone={async () => []} onMikrofonWaehlen={() => true} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Neu einlernen" }));
    expect(window.location.hash).toBe("#einstellungen/stimme");
  });

  it("Abschnitt Stimme: nennt das Mikrofon des Einlernens und sagt, wenn ein anderes läuft", () => {
    localStorage.setItem(`wamo.stimme.mikrofon.${ID}`, "Headset (Bluetooth)");
    act(() => wamo.set((s) => ({ ...s, presence: "idle", mikrofon: "Mikrofonarray (Realtek)" })));
    render(<StimmeAbschnitt aktionen={undefined} />);
    expect(screen.getByText("Headset (Bluetooth)")).toBeTruthy();
    expect(screen.getByText(/Gerade läuft ein anderes Mikrofon als beim Einlernen/)).toBeTruthy();
  });

  it("Abschnitt Stimme: nennt das laufende Mikrofon und führt zur Wahl", async () => {
    act(() => wamo.set((s) => ({ ...s, presence: "idle", mikrofon: "Webcam-Mikrofon" })));
    render(<StimmeAbschnitt aktionen={undefined} />);
    expect(screen.getByText("Webcam-Mikrofon")).toBeTruthy();
    expect(screen.getByText(/Ein anderes oder sehr leises Mikrofon senkt die Übereinstimmung/)).toBeTruthy();
    await userEvent.setup().click(screen.getByRole("button", { name: "Mikrofon wählen" }));
    expect(window.location.hash).toBe("#einstellungen/sprache");
  });
});
