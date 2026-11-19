# W.A.I.S. Produktdokumentation

| | |
|---|---|
| Zweck | Einstieg in die gesamte Dokumentation von W.A.I.S.: fachlich, architektonisch, technisch, im Betrieb und in der Nutzung. |
| Zielgruppe | Alle, die W.A.I.S. nutzen, betreiben, weiterentwickeln oder bewerten |
| Dokumentart | Erklärung (Landkarte) |
| Stand | 19.11.2026, geprüft gegen Commit 497e3ce, Produktversion 0.6.0 |
| Quellen | `CLAUDE.md`, `README.md` und `CHANGELOG.md` im Wurzelordner, der Code der Teile, `docs/` |

## Was W.A.I.S. ist

W.A.I.S. (WAMOCON's Artificial Intelligence System) ist der Sprachassistent der WAMOCON GmbH. Mitglieder sprechen mit ihm, er merkt sich Wissen, zeigt Ergebnisse in einer Arbeitsfläche (Canvas), bedient auf Wunsch und nach Freigabe den PC, erstellt Office-Dateien und führt Entwicklungsaufträge aus. Das Produkt besteht aus einer Web-Oberfläche, einer Desktop-App, einem PC-Host, dem Voice-Core (Kern) und einer Datenbank auf eigenen Servern. Kennungen im Code heißen `wamo`, der Anzeigename ist `W.A.I.S.`. Einen Überblick mit Leistungsumfang und Stand gibt [Produktübersicht](fachlich/produktuebersicht.md).

## Wähle deinen Weg

| Ich bin ... | Ich lese zuerst | Danach |
|---|---|---|
| Mitglied und will W.A.I.S. nutzen | [Benutzerhandbuch](nutzung/benutzerhandbuch.md) | [Glossar](glossar.md) |
| in Fachbereich oder Produktverantwortung | [Produktübersicht](fachlich/produktuebersicht.md) | [Funktionskatalog](fachlich/funktionskatalog.md), [Rollen und Rechte](fachlich/rollen-und-rechte.md) |
| Architekt oder Architektin | [Architektur nach arc42](architektur/arc42.md) | [C4-Diagramme](architektur/c4-diagramme.md), [Entscheidungsregister](architektur/entscheidungen.md) |
| Entwickler oder Entwicklerin | [Entwicklerhandbuch](entwicklung/entwicklerhandbuch.md) | [Voice-Core](technik/voice-core.md), [Oberfläche](technik/oberflaeche.md), [Host und Desktop](technik/host-und-desktop.md), [Datenmodell](technik/datenmodell.md), [Schnittstellen](technik/schnittstellen.md), [Konfiguration](technik/konfiguration.md) und [Betriebsvariablen](technik/konfiguration-betrieb.md), [Qualität und Tests](entwicklung/qualitaet-und-tests.md) |
| in Administration oder Betrieb | [Administrationshandbuch](betrieb/administrationshandbuch.md) | [Betriebshandbuch](betrieb/betriebshandbuch.md), [Release und Ausrollen](betrieb/release-und-ausrollen.md) |
| in Sicherheit oder Datenschutz | [Sicherheit und Datenschutz](sicherheit/sicherheit-und-datenschutz.md) | [Rollen und Rechte](fachlich/rollen-und-rechte.md), [Befunde der ausgelieferten App](technik/desktop-auslieferung-rea.md) |
| verantwortlich für Releases | [Release und Ausrollen](betrieb/release-und-ausrollen.md) | [Befunde der ausgelieferten App](technik/desktop-auslieferung-rea.md), [Qualität und Tests](entwicklung/qualitaet-und-tests.md) |

## Fertige Dokumente (PDF)

Alle Dokumente liegen zusätzlich als fertig gesetzte PDF-Dateien im WAMOCON-Design im Ordner [final/](final/README.md): das [Gesamtdokument](final/00-W.A.I.S.-Produktdokumentation-Gesamt.pdf) und je ein PDF pro Dokument. Die Markdown-Dateien in den Unterordnern sind die Quellen und bleiben maßgeblich.

## Dokumentenlandkarte

Die Dokumentart folgt Diátaxis (Erklärung, Referenz, Anleitung, Lernpfad). Begründung und Pflegeregeln stehen im [Dokumentationskonzept](dokumentationskonzept.md).

| Dokument | Inhalt | Art |
|---|---|---|
| [fachlich/produktuebersicht.md](fachlich/produktuebersicht.md) | Zweck, Zielgruppen, Leistungsumfang, Abgrenzung, Produktstand | Erklärung |
| [fachlich/funktionskatalog.md](fachlich/funktionskatalog.md) | Funktionen je Fachgebiet mit stabilen IDs | Referenz |
| [fachlich/rollen-und-rechte.md](fachlich/rollen-und-rechte.md) | Rollen, Rechtematrix, Freigabestufen | Referenz, Erklärung |
| [nutzung/benutzerhandbuch.md](nutzung/benutzerhandbuch.md) | Erste Schritte, Alltag, Fehlerbehebung | Anleitung, Lernpfad |
| [architektur/arc42.md](architektur/arc42.md) | Architektur in zwölf Abschnitten | Erklärung |
| [architektur/c4-diagramme.md](architektur/c4-diagramme.md) | Kontext, Container, Komponenten, Deployment, Abläufe | Erklärung |
| [architektur/entscheidungen.md](architektur/entscheidungen.md) | Register der Architekturentscheidungen | Referenz |
| [technik/voice-core.md](technik/voice-core.md) | Aufbau des Python-Kerns | Erklärung, Referenz |
| [technik/oberflaeche.md](technik/oberflaeche.md) | Aufbau der Web-Oberfläche | Erklärung, Referenz |
| [technik/host-und-desktop.md](technik/host-und-desktop.md) | PC-Host und Desktop-App | Erklärung, Referenz |
| [technik/desktop-auslieferung-rea.md](technik/desktop-auslieferung-rea.md) | Befunde am ausgelieferten Artefakt | Referenz |
| [technik/datenmodell.md](technik/datenmodell.md) | Datenbank, Rollen, Migrationen | Referenz |
| [technik/schnittstellen.md](technik/schnittstellen.md) | HTTP-Routen, Nachrichten, Werkzeuge, Kanäle | Referenz |
| [technik/konfiguration.md](technik/konfiguration.md) | Umgebungsvariablen und Schalter des Kerns, der Oberfläche und des Hosts | Referenz |
| [technik/konfiguration-betrieb.md](technik/konfiguration-betrieb.md) | Betriebsvariablen aus Infrastruktur und Skripten | Referenz |
| [betrieb/betriebshandbuch.md](betrieb/betriebshandbuch.md) | Topologie, Dienste, Störungen, Rückwege | Referenz, Anleitung |
| [betrieb/release-und-ausrollen.md](betrieb/release-und-ausrollen.md) | Weg von der Änderung zur Produktion | Erklärung, Anleitung |
| [betrieb/administrationshandbuch.md](betrieb/administrationshandbuch.md) | Aufgaben der Administration | Anleitung |
| [sicherheit/sicherheit-und-datenschutz.md](sicherheit/sicherheit-und-datenschutz.md) | Sicherheitsmodell, Daten, Datenschutz | Erklärung, Referenz |
| [entwicklung/entwicklerhandbuch.md](entwicklung/entwicklerhandbuch.md) | Einrichtung, Konventionen, Arbeitsablauf | Anleitung |
| [entwicklung/qualitaet-und-tests.md](entwicklung/qualitaet-und-tests.md) | Teststrategie, Prüfungen, Lücken | Referenz |
| [glossar.md](glossar.md) | Begriffe | Referenz |
| [dokumentationskonzept.md](dokumentationskonzept.md) | Recherche, Struktur, Pflege der Dokumentation | Erklärung |

## Bestehende Unterlagen in docs/

Diese Planpapiere, Anleitungen und Berichte bleiben unverändert und sind die Quelle für Hintergründe und Entscheidungen. Der Kopf jedes Papiers nennt seinen Stand, einige sind überholt oder beschreiben nur einen Plan.

| Thema | Unterlagen |
|---|---|
| Ausrollen und Zugänge | [Ausrollen für neue Nutzer](../ausrollen-neue-nutzer.md), [Persönliche Zugänge](../persoenliche-zugaenge.md), [Jira-Benutzer einrichten](../jira-benutzer-einrichten.md), [Eigener Runner](../runner-einrichten.md) |
| Entwicklungsaufträge | [Entwicklung im Betrieb](../entwicklung-im-betrieb.md), [Arbeitsliste](../entwicklung-im-betrieb-arbeitsliste.md), [Folgepaket 1](../folgepaket-1.md), [Selbstüberarbeitung (nur Konzept)](../selbstueberarbeitung.md) |
| Modelle, Sprache, Gespräch | [Hausmodelle für W.A.I.S. (Sokrates)](../hausmodelle-und-kikollege.md), [Sprache: Soniox oder ElevenLabs](../sprache-elevenlabs-soniox.md), [Gespräch natürlicher machen](../gespraech-optimierung.md), [Recherche zur Stimmerkennung](../stimme-recherche-2026-11-18.md) |
| Office, Komfort, Fernzugriff | [Office und Versand](../office-und-versand.md), [Komfort-Paket](../komfort-paket.md), [Remote Desktop](../remote-desktop.md) |
| Testlabor | [Planpapier](../testlabor-wamo.md), [Runbook](../labor-runbook.md), [Morgencheckliste](../labor-morgencheckliste.md), [Restplan](../labor-restplan.md), [Platz einrichten](../labor-platz-einrichten.md), [Dienst-Vertrag](../labor-dienst-vertrag.md), [Messrunde 1](../labor-messrunde-1.md), [Lasttest](../labor-lasttest.md), [Datenschutzhinweis (Entwurf)](../labor-datenschutz-entwurf.md) |

## Weitere Quellen im Repo

- [README.md](../../README.md): Stand, Einrichtung und ausführliche Betriebsabschnitte
- [CHANGELOG.md](../../CHANGELOG.md): Änderungen je Version
- [CLAUDE.md](../../CLAUDE.md): Namensvertrag und Arbeitsregeln
- [infra/sokrates2/README.md](../../infra/sokrates2/README.md): Einrichtung der Server

## Hinweise zum Gebrauch

- Jedes Dokument nennt im Kopf Zweck, Zielgruppe, Dokumentart, geprüften Commit und seine Quellen. Widersprechen sich Dokument und Code, gilt der Code.
- Das Repository ist öffentlich. Die Dokumentation enthält deshalb keine Zugangsdaten und beschreibt Betrieb und Sicherheit nur so weit, wie `README.md`, `CLAUDE.md` und `docs/` es ohnehin tun.
- Zahlen mit Datum sind Momentaufnahmen. Der Zustand der Server ist, wo nicht anders vermerkt, "laut README, Stand" mit Datum angegeben und wurde in diesem Dokumentationsstand nicht am Server geprüft.
