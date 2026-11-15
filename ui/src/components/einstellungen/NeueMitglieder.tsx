"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { KernFehler, kernJson } from "@/lib/kernApi";
import { datumKurz, modellText, naechsterSchritt, pruefeListe, schritte, zusammenfassung, type Mitglied } from "@/lib/mitgliederUebersicht";
import { Block } from "./Block";

const PFAD = "/admin/neue-mitglieder";

type Stand = { art: "laedt" } | { art: "fehler"; text: string } | { art: "ok"; liste: Mitglied[] };

function fehlerText(e: unknown): string {
  if (e instanceof KernFehler && e.status === 403) return "Die Übersicht ist nur für Admins.";
  if (e instanceof KernFehler && e.status === 404) return "Der Kern kennt diese Übersicht noch nicht (Version vor Paket P7).";
  return "Die Übersicht ist gerade nicht erreichbar.";
}

async function laden(): Promise<Stand> {
  try {
    const liste = pruefeListe(await kernJson(PFAD));
    return liste ? { art: "ok", liste } : { art: "fehler", text: "Unerwartete Antwort des Kerns." };
  } catch (e) {
    return { art: "fehler", text: fehlerText(e) };
  }
}

/** Eine Person: Name, nächster Schritt, Schritte als Liste mit Wort (Farbe nie allein), Modellzugang und Daten. */
function Person({ m }: { m: Mitglied }) {
  return (
    <li className="nm-person">
      <p className="nm-kopf">
        <span className="nm-name">{m.name || "ohne Namen"}</span>
        {m.rolle === "admin" && <span className="nm-rolle">Admin</span>}
      </p>
      <p className="nm-satz">{naechsterSchritt(m)}</p>
      <ul className="nm-schritte" aria-label={`Schritte von ${m.name || "ohne Namen"}`}>
        {schritte(m).map((s) => (
          <li key={s.id} className="nm-schritt" data-stand={s.erledigt === null ? "offen" : s.erledigt ? "ja" : "nein"}>
            <span aria-hidden="true">{s.erledigt === null ? "?" : s.erledigt ? "✓" : "!"}</span> {s.titel}:{" "}
            {s.erledigt === null ? "noch nicht prüfbar" : s.erledigt ? "erledigt" : "fehlt"}
          </li>
        ))}
      </ul>
      <p className="ez-klein">
        Modellzugang: {modellText(m)}. Angelegt {datumKurz(m.angelegt)}, zuletzt angemeldet {datumKurz(m.letzteAnmeldung)}.
      </p>
    </li>
  );
}

/**
 * Abschnitt "Neue Mitglieder" (nur Admin, Paket P7): je Profil ohne Laborprofile, wie weit die Einrichtung ist (Kern:
 * voice-core/mitglieder_admin_api.py, Migration 0022). Lädt beim Öffnen und mit "Neu laden", nie von selbst. Keine Geheimnisse:
 * Der Kern liefert nur Stände.
 */
export const NeueMitglieder = memo(function NeueMitglieder() {
  const [stand, setStand] = useState<Stand>({ art: "laedt" });
  const aktiv = useRef(true);

  const neu = useCallback(async () => {
    setStand({ art: "laedt" });
    const s = await laden();
    if (aktiv.current) setStand(s);
  }, []);

  useEffect(() => {
    aktiv.current = true;
    const erster = setTimeout(() => void neu(), 0);
    return () => {
      aktiv.current = false;
      clearTimeout(erster);
    };
  }, [neu]);

  return (
    <Block titel="Wie weit sind die neuen Mitglieder?">
      {stand.art === "laedt" && (
        <p className="ez-leer" role="status">
          Lade die Übersicht ...
        </p>
      )}
      {stand.art === "fehler" && (
        <p className="gv-meldung" role="alert" data-art="fehler">
          {stand.text}
        </p>
      )}
      {stand.art === "ok" && (
        <>
          <p className="ez-klein" role="status">
            {zusammenfassung(stand.liste)}
          </p>
          <ul className="nm-liste" aria-label="Neue Mitglieder">
            {stand.liste.map((m) => (
              <Person key={m.userId} m={m} />
            ))}
          </ul>
        </>
      )}
      <button type="button" className="btn-secondary" onClick={() => stand.art !== "laedt" && void neu()} aria-disabled={stand.art === "laedt"}>
        Neu laden
      </button>
    </Block>
  );
});
