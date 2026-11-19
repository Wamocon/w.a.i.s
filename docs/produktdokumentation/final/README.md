# Fertige Dokumente (PDF)

| | |
|---|---|
| Zweck | Die Produktdokumentation als fertig gesetzte Dokumente im WAMOCON-Design, zum Lesen, Weitergeben und Drucken. |
| Zielgruppe | Alle Leser der Produktdokumentation, auch ohne Zugriff auf das Repo |
| Dokumentart | Erklärung (Verzeichnis der Dokumente) |
| Stand | 19.11.2026, geprüft gegen Commit 497e3ce |
| Quellen | Die Markdown-Dateien in den Ordnern `fachlich/`, `nutzung/`, `architektur/`, `technik/`, `betrieb/`, `sicherheit/` und `entwicklung/` |

Die Datei `00` enthält alle Dokumente in einem PDF mit Titelseite und Inhaltsverzeichnis, die Dateien `01` bis `24` enthalten je ein Dokument. Jede Seite trägt die WAMOCON-Kopfzeile (Anschrift links, Logo rechts) und die Seitenzahl. Die PDF-Lesezeichen folgen den Überschriften.

| Nr | PDF | Quelle | Seiten |
|---|---|---|---|
| 00 | [00-W.A.I.S.-Produktdokumentation-Gesamt.pdf](00-W.A.I.S.-Produktdokumentation-Gesamt.pdf) | alle 24 Dokumente mit Titelseite und Inhaltsverzeichnis | 215 |
| 01 | [01-Einstieg-und-Dokumentenlandkarte.pdf](01-Einstieg-und-Dokumentenlandkarte.pdf) | [README.md](../README.md) | 3 |
| 02 | [02-Dokumentationskonzept.pdf](02-Dokumentationskonzept.pdf) | [dokumentationskonzept.md](../dokumentationskonzept.md) | 8 |
| 03 | [03-Produktuebersicht.pdf](03-Produktuebersicht.pdf) | [fachlich/produktuebersicht.md](../fachlich/produktuebersicht.md) | 7 |
| 04 | [04-Funktionskatalog.pdf](04-Funktionskatalog.pdf) | [fachlich/funktionskatalog.md](../fachlich/funktionskatalog.md) | 12 |
| 05 | [05-Rollen-und-Rechte.pdf](05-Rollen-und-Rechte.pdf) | [fachlich/rollen-und-rechte.md](../fachlich/rollen-und-rechte.md) | 11 |
| 06 | [06-Benutzerhandbuch.pdf](06-Benutzerhandbuch.pdf) | [nutzung/benutzerhandbuch.md](../nutzung/benutzerhandbuch.md) | 14 |
| 07 | [07-Architektur-arc42.pdf](07-Architektur-arc42.pdf) | [architektur/arc42.md](../architektur/arc42.md) | 16 |
| 08 | [08-C4-Diagramme.pdf](08-C4-Diagramme.pdf) | [architektur/c4-diagramme.md](../architektur/c4-diagramme.md) | 10 |
| 09 | [09-Entscheidungsregister.pdf](09-Entscheidungsregister.pdf) | [architektur/entscheidungen.md](../architektur/entscheidungen.md) | 6 |
| 10 | [10-Voice-Core.pdf](10-Voice-Core.pdf) | [technik/voice-core.md](../technik/voice-core.md) | 13 |
| 11 | [11-Oberflaeche.pdf](11-Oberflaeche.pdf) | [technik/oberflaeche.md](../technik/oberflaeche.md) | 9 |
| 12 | [12-Host-und-Desktop.pdf](12-Host-und-Desktop.pdf) | [technik/host-und-desktop.md](../technik/host-und-desktop.md) | 9 |
| 13 | [13-Befunde-Desktop-App-REA.pdf](13-Befunde-Desktop-App-REA.pdf) | [technik/desktop-auslieferung-rea.md](../technik/desktop-auslieferung-rea.md) | 5 |
| 14 | [14-Datenmodell.pdf](14-Datenmodell.pdf) | [technik/datenmodell.md](../technik/datenmodell.md) | 10 |
| 15 | [15-Schnittstellen.pdf](15-Schnittstellen.pdf) | [technik/schnittstellen.md](../technik/schnittstellen.md) | 17 |
| 16 | [16-Konfiguration.pdf](16-Konfiguration.pdf) | [technik/konfiguration.md](../technik/konfiguration.md) | 12 |
| 17 | [17-Konfiguration-Betrieb.pdf](17-Konfiguration-Betrieb.pdf) | [technik/konfiguration-betrieb.md](../technik/konfiguration-betrieb.md) | 6 |
| 18 | [18-Betriebshandbuch.pdf](18-Betriebshandbuch.pdf) | [betrieb/betriebshandbuch.md](../betrieb/betriebshandbuch.md) | 15 |
| 19 | [19-Release-und-Ausrollen.pdf](19-Release-und-Ausrollen.pdf) | [betrieb/release-und-ausrollen.md](../betrieb/release-und-ausrollen.md) | 13 |
| 20 | [20-Administrationshandbuch.pdf](20-Administrationshandbuch.pdf) | [betrieb/administrationshandbuch.md](../betrieb/administrationshandbuch.md) | 12 |
| 21 | [21-Sicherheit-und-Datenschutz.pdf](21-Sicherheit-und-Datenschutz.pdf) | [sicherheit/sicherheit-und-datenschutz.md](../sicherheit/sicherheit-und-datenschutz.md) | 14 |
| 22 | [22-Entwicklerhandbuch.pdf](22-Entwicklerhandbuch.pdf) | [entwicklung/entwicklerhandbuch.md](../entwicklung/entwicklerhandbuch.md) | 5 |
| 23 | [23-Qualitaet-und-Tests.pdf](23-Qualitaet-und-Tests.pdf) | [entwicklung/qualitaet-und-tests.md](../entwicklung/qualitaet-und-tests.md) | 6 |
| 24 | [24-Glossar.pdf](24-Glossar.pdf) | [glossar.md](../glossar.md) | 3 |

## Wichtig für die Pflege

- Die PDF-Dateien sind ein Export. Maßgeblich sind die Markdown-Quellen, bei Abweichungen gilt die Quelle.
- Nach jeder inhaltlichen Änderung an einem Dokument sind das zugehörige PDF und das Gesamtdokument neu zu erzeugen. Das gehört in die Prüfliste vor einem Versionssprung (siehe [Dokumentationskonzept](../dokumentationskonzept.md)).
- Erzeugung: Markdown nach HTML, Diagramme (Mermaid) zeichnen, danach PDF mit der WAMOCON-Kopfzeile und Seitenzahl auf jeder Seite. Das Exportwerkzeug liegt nicht im Repo.
- Verweise auf andere Dokumente sind in einem Einzeldokument normaler Text. Im Gesamtdokument führen sie zu den Abschnitten.

## Weiterführend

- [Einstieg und Dokumentenlandkarte](../README.md)
- [Dokumentationskonzept](../dokumentationskonzept.md)
