"use client";

import { Block } from "./Block";

/**
 * Abschnitt "Werkstatt" (nur Admin): ein Link auf die eigene Seite /werkstatt. Die Werkstatt öffnet in einem neuen Tab, damit das
 * Gespräch hier unberührt weiterläuft. Ob die Person hinein darf, entscheidet der Dienst der Werkstatt (Erlaubnisliste, zweiter
 * Faktor), nicht diese Oberfläche.
 */
export function WerkstattAbschnitt() {
  return (
    <Block titel="Werkstatt öffnen">
      <p className="ez-text">
        Dashboards mit Zahlen zum Betrieb, der Labor-Planer, Karten und Use Cases für das Testlabor und gefilterte Protokolle. Die Werkstatt öffnet in einem neuen Tab.
      </p>
      <p className="ez-klein">Sie ist nur aus dem Büronetz erreichbar und nur für Admins auf der Erlaubnisliste. Beim Veröffentlichen verlangt sie einen frischen Code deines zweiten Faktors.</p>
      <div>
        <a href="/werkstatt" target="_blank" rel="noopener noreferrer" className="btn-primary ws-link-knopf">
          Werkstatt öffnen
        </a>
      </div>
    </Block>
  );
}
