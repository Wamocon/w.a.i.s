import type { Metadata } from "next";
import type { ReactNode } from "react";

// Die Werkstatt ist ein Werkzeug für Admins: keine Aufnahme in Suchmaschinen, eigener Titel in der Browserleiste.
export const metadata: Metadata = {
  title: "Werkstatt | W.A.I.S.",
  description: "Admin-Panel für Dashboards, Labor-Planer, Karten und Protokolle",
  robots: { index: false, follow: false },
};

export default function WerkstattLayout({ children }: Readonly<{ children: ReactNode }>) {
  return children;
}
