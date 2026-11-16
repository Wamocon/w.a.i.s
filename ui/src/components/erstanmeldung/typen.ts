import type { SupabaseClient } from "@supabase/supabase-js";
import type { ComponentType } from "react";
import type { ErstanmeldungStand, PasswortErgebnis } from "@/lib/erstanmeldung";

/**
 * Typen des geführten Ablaufs der Erstanmeldung. Die Schritte stehen in einer einzigen Liste (schritte.tsx); wer einen Schritt
 * ergänzt, schreibt nur einen Eintrag dorthin, weder LoginGate noch Erstanmeldung.tsx ändern sich.
 */

/** Was jeder Schritt vom Tor bekommt. Nichts davon ist ein Geheimnis außer dem, was die Funktionen auf Anfrage liefern. */
export type ErstanmeldungKontext = {
  /** Anmeldeclient (Browser, öffentlicher Schlüssel); die Sitzung ist aal2 */
  supabase: SupabaseClient;
  /** aktuelles Zugriffstoken für Aufrufe am Kern (erneuert bei Bedarf), null ohne Sitzung */
  zugriffstoken: () => Promise<string | null>;
  /** Ursprung des Kerns (https oder Loopback) oder "" ohne sicheren Kern; für Aufrufe über lib/kernApi.ts nicht nötig */
  kernBasis: string;
  /** Anzeigename des Assistenten für Sätze an die Person ("W.A.I.S.") */
  anzeigename: string;
  userId: string;
  email: string | null;
  /** Stand der Erstanmeldung, als das Tor den Ablauf geöffnet hat (offen, oder erledigt bei einem Neuladen nach dem Passwortwechsel) */
  standStart: ErstanmeldungStand;
  /** Stand beim Kern neu abfragen (leert dort den Cache); wirft nie, unklar heißt "keine" */
  stand: () => Promise<ErstanmeldungStand>;
  /** Passwort über den Kern ändern (POST /wamo/api/erstanmeldung/passwort); wirft nie, Fehler stehen im Ergebnis. Nur der Schritt "passwort" braucht es. */
  passwortSetzen: (passwort: string) => Promise<PasswortErgebnis>;
  /**
   * Das Tor neu prüfen lassen. Ohne Angabe: Stand und Anmeldestufe neu auswerten (zum Beispiel nach "abgelaufen"). Mit code: zurück
   * zur Abfrage des Codes der Authenticator-App; hinweis erscheint dort als Satz.
   */
  neuPruefen: (optionen?: { code?: boolean; hinweis?: string }) => void;
  /** Lokal abmelden */
  abmelden: () => void;
};

export type SchrittProps = {
  kontext: ErstanmeldungKontext;
  /** Schritt ist erledigt (oder bewusst beendet): zum nächsten nötigen Schritt, nach dem letzten ruft der Ablauf fertig() auf */
  weiter: () => void;
  /** nur bei überspringbaren Schritten gesetzt; wirkt wie weiter, die Komponente bietet dafür den Knopf "Überspringen" an */
  ueberspringen?: () => void;
};

export type ErstanmeldungSchritt = {
  /** stabile Kennung, zum Beispiel "passwort", "token", "schluessel" */
  id: string;
  /** kurzer Name in der Leiste oben */
  titel: string;
  /** Überschrift über dem Schritt (der Ablauf zeigt sie und setzt den Fokus darauf); fehlt sie, gilt der Titel */
  ueberschrift?: string;
  ueberspringbar: boolean;
  komponente: ComponentType<SchrittProps>;
  /** false: Schritt wird übergangen (zum Beispiel weil schon erledigt). Wirft die Prüfung, wird der Schritt gezeigt. Fehlt sie: immer nötig. */
  noetig?: (kontext: ErstanmeldungKontext) => boolean | Promise<boolean>;
};
