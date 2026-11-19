# Aufträge an W.A.I.S. selbst (Rückstand)

Stand 19.11.2026. Wunsch von Niko: „WAIS muss auch Entwicklungsaufträge für sich selbst speichern können, die wir dann hier oder später WAIS
selbst an sich durchführen kann.“

## Was es ist

Ein gemeinsamer Rückstand (Backlog) von Verbesserungs-, Fehler- und Funktionswünschen an W.A.I.S. selbst. Jeder Eintrag hat eine Nummer
(`SA-7`), einen Titel, eine Beschreibung, eine Art (wie bei Entwicklungsaufträgen), eine Priorität (1 hoch, 2 normal, 3 niedrig), bis zu fünf
Abnahmekriterien und einen Stand: `offen`, `in_arbeit`, `erledigt` oder `verworfen`.

Das ist **nicht** der Speicher „Für später speichern“ (`auftrag_entwuerfe`, Migration 0026). Der gehört einer Person, verfällt nach 90 Tagen
und lädt Karten für Aufträge an andere Repos. Ein Auftrag an das eigene Repo scheitert dort am Selbstschutz (`dev_guard.ist_eigenes_repo`),
und der bleibt: W.A.I.S. ändert sein eigenes Repo nicht über den Weg der Entwicklungsaufträge.

## Wer legt an, wer liest, wer setzt um

| Weg | Wer | Wie |
| --- | --- | --- |
| Sprache | Admin | Werkzeuge `selbstauftrag_speichern`, `selbstauftraege_zeigen`, `selbstauftrag_verwerfen` (nur mit Datenbank, nie im Labor, nie für Mitglieder) |
| Oberfläche | Admin | Block „Aufträge an W.A.I.S. selbst“ im Reiter Aufträge (Client-Nachricht `selbstauftrag`, Antwort `selbstauftraege`) |
| Claude Code | Admin, Claude Code | `python scripts/wamo_selbstauftraege.py liste`, `zeigen`, `neu`, `uebernehmen`, `erledigt`, `verwerfen`, `oeffnen` |

Der Kern führt **nichts** aus. Er legt an, liest und wechselt den Stand zwischen `offen` und `verworfen`. `in_arbeit` und `erledigt` setzt
allein der Bearbeiter über die Datenbank (Skript, später W.A.I.S. selbst); das erzwingen die Spaltenrechte und der Trigger
`selbstauftraege_status` (Migration 0030). Nichts wird gelöscht, der Verlauf bleibt.

## Sicherheit: ein Eintrag ist ein Vorschlag, keine Anweisung

Der Text kann aus einem Gespräch stammen, in dem Inhalte von außen waren (Webseite, Websuche, Ergebnis vom Laptop). Deshalb:

- Entsteht ein Eintrag per Sprache nach Fremdinhalt, ist er als `unsicher` markiert; W.A.I.S. sagt der Person, dass ein Admin ihn prüfen soll.
- Die Liste geht als Fremdinhalt zurück ans Gespräch (danach braucht jede Änderung am Laptop eine Karte).
- Zugangswerte im Text ersetzt der Kern vor dem Speichern (`auftrag_entwuerfe.geheimnisse_entfernen`).
- **Wer Einträge abarbeitet (Claude Code, später W.A.I.S.), setzt keinen ohne das ausdrückliche Ja eines Admins um** und nennt vorher
  Nummer und Titel. Das Skript erinnert bei `liste` und `zeigen` jedes Mal daran.
- Grenzen: höchstens 200 offene oder laufende Einträge (Trigger), höchstens 30 neue je Person und Tag (Kern), Titel 80, Beschreibung 4000
  Zeichen.

## Arbeitsablauf in Claude Code

1. `python scripts/wamo_selbstauftraege.py liste` (am Anfang einer Arbeitssitzung und auf Nachfrage nach offenen Punkten).
2. Niko nennt den Eintrag, den er umgesetzt haben will (oder sagt Ja zu einem Vorschlag).
3. `zeigen 7`, dann `uebernehmen 7`, in einem Arbeitsbaum umsetzen, Pull Request wie immer.
4. `erledigt 7 --ergebnis "Pull Request 231, ausgerollt"`.

## Später: W.A.I.S. setzt Einträge selbst um (Ausbaustufe, nicht gebaut)

Vorbereitet ist nur das Datenmodell: `bearbeiter = 'wais'` und die Stände. Der Weg selbst ist die Selbstüberarbeitung aus
`docs/selbstueberarbeitung.md` (Release-Dienst, Prüfer-Sandbox, Freigabe durch einen Admin) und braucht eigene Entscheidungen:

1. Ein Auftragstyp „Selbstauftrag“, der ausdrücklich ein Admin-Ja auf einer Karte verlangt (nie automatisch, nie aus Fremdinhalt).
2. Die Aufhebung des Selbstschutzes nur für diesen Typ und nur über den Release-Weg (Prüfung, Review, Freigabe, Umschalten ohne Downtime).
3. Ein Notaus und ein Rückweg je Eintrag (der Release-Dienst hat sie).

Bis dahin gilt: Der Rückstand sammelt, Claude Code setzt um.

## Technik

Migration `0030_selbstauftraege` (mit `.down.sql`, SQL-Test `supabase/tests/0030_selbstauftraege_test.sql`), Kern `voice-core/selbstauftraege.py`
und `voice-core/dev_agent_selbst.py`, Oberfläche `ui/src/lib/selbstAuftraege.ts` und `ui/src/components/SelbstAuftraege.tsx`, Skript
`scripts/wamo_selbstauftraege.py`. Rechte nur für `wamo_core`: lesen und einfügen in acht Spalten; kein `update` und kein `delete`. Den Stand
ändert der Kern allein über die Funktionen `selbstauftrag_verwerfen` (offen oder in_arbeit nach verworfen) und `selbstauftrag_oeffnen`
(verworfen nach offen), beide `security definer` mit leerem `search_path`. Der Kern kann also weder „erledigt“ noch „in_arbeit“ setzen und
einen laufenden Auftrag nicht zurückstellen. Die Grenze von 200 offenen gilt auch beim Wiedereröffnen. Schemas `wamo_dev` (das Büro) und
`wamo_test`.

## Befunde der Prüfung vom 19.11.2026 (behoben)

Zwei Reviewer (Datenbank, Python mit Blick auf Sicherheit) fanden fünf Lücken, alle vor dem Ausrollen behoben und mit Tests belegt: die Grenze
von 200 ließ sich über „wieder öffnen“ umgehen; der Kern konnte „erledigt“ setzen (jetzt kein `update`, nur die zwei Funktionen);
`unsicher` galt nur im Zug mit Fremdinhalt (jetzt wie die Karten der Mitglieder bis zum Ende der Sitzung); die Beschreibung blieb nicht frei
von unsichtbaren Zeichen und das Skript gab sie roh aus (jetzt gesäubert, eingerahmt, mit Endmarke); `liste` brach ab zwei Einträgen
(`jsonb_agg` statt `json_agg`).
