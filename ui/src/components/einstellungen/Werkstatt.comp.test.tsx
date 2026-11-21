// Komponententest des Abschnitts "Werkstatt" in den Einstellungen: ein Link auf die eigene Seite, in einem neuen Tab.
// Ausführen im Ordner ui/:  npm run test:komponenten
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WerkstattAbschnitt } from "./Werkstatt";

describe("WerkstattAbschnitt", () => {
  it("bietet den Link auf /werkstatt in einem neuen Tab, ohne Verbindung zum Fenster der Oberfläche", () => {
    render(<WerkstattAbschnitt />);
    const link = screen.getByRole("link", { name: "Werkstatt öffnen (öffnet in einem neuen Tab)" });
    expect(link.getAttribute("href")).toBe("/werkstatt");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(screen.getByText(/nur aus dem Büronetz erreichbar und nur für Admins auf der Erlaubnisliste/)).toBeTruthy();
  });
});
