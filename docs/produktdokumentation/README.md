# W.A.I.S. Produktdokumentation

| | |
|---|---|
| Zweck | Einstieg in die gesamte Dokumentation von W.A.I.S.: fachlich, architektonisch, technisch, im Betrieb und in der Nutzung. |
| Zielgruppe | Alle, die W.A.I.S. nutzen, betreiben, weiterentwickeln oder bewerten |
| Dokumentart | Erklärung (Landkarte) |
| Stand | 20.11.2026, geprüft gegen Commit 7caf977, Produktversion 0.7.0 |
| Quellen | `CLAUDE.md`, `README.md` und `CHANGELOG.md` im Wurzelordner, der Code der Teile, `docs/` |

## Was W.A.I.S. ist

W.A.I.S. (WAMOCON's Artificial Intelligence System) ist der Sprachassistent der WAMOCON GmbH. Mitglieder sprechen mit ihm, er merkt sich Wissen, zeigt Ergebnisse in einer Arbeitsfläche (Canvas), bedient auf Wunsch und nach Freigabe den PC, erstellt Office-Dateien und führt Entwicklungsaufträge aus. Das Produkt besteht aus einer Web-Oberfläche, einer Desktop-App, einem PC-Host, dem Voice-Core (Kern) und einer Datenbank auf eigenen Servern. Kennungen im Code heißen `wamo`, der Anzeigename ist `W.A.I.S.`. Einen Überblick mit Leistungsumfang und Stand gibt das Kapitel [Produktübersicht](fachkonzept.md#produktübersicht-wais).

## Stand der Produktversion 0.7.0

Diese Dokumentation beschreibt Version 0.7.0 (20.11.2026). Die wichtigsten Änderungen gegenüber 0.6.0:

- **Stimme:** Die Stimmerkennung sperrt nichts mehr. Der Standard ist `beobachten`, die Sperre gibt es nur mit ausdrücklich `WAMO_STIMME_PRUEFUNG=streng`. Mitglieder brauchen für gesprochene PC-Befehle weiter einen eingelernten Abdruck. Es gibt einen Abdruck je Mikrofon (höchstens drei je Person), einen Mikrofontest ohne dass W.A.I.S. spricht, einen Hinweis beim Gerätewechsel und die Mikrofonkette im Protokoll. Ein zweites Sprechermodell läuft nur im Schattenbetrieb.
- **Einstellungen:** Sechs Gruppen statt einer langen Liste: Konto und Allgemeines, Sprache und Stimme, Modelle und Zugänge, Geräte und PC, Gedächtnis und Teilen, Verwaltung (nur für Admins).
- **Entwicklungsaufträge:** Persönliche GitHub-Zugänge (Plan C, Dispatcher 10), alle 14 Auftragsarten im Kern-Kanal, Aufträge für später speichern, Rückstand für Aufträge an W.A.I.S. selbst (nur Admins, ein Eintrag ist ein Vorschlag und keine Anweisung).
- **Gespräch und Canvas:** W.A.I.S. erklärt auf Nachfrage, warum etwas nicht ging (Fehlerbuch). Canvas-Reiter lassen sich schließen, dazu kommen Historie, Bilder und Dateien.
- **Release:** Version 0.7.0 in allen vier Teilen (Oberfläche, Desktop-App, Kern, Host). Die neueste Migration ist 0030.

Ausführlich steht das im [Changelog](../../CHANGELOG.md), Abschnitt 0.7.0.

## Wähle deinen Weg

| Ich bin ... | Ich lese zuerst | Danach |
|---|---|---|
| Mitglied und will W.A.I.S. nutzen | [Benutzerhandbuch](benutzerhandbuch.md) | [Glossar](glossar.md) |
| in Fachbereich oder Produktverantwortung | [Produktübersicht](fachkonzept.md#produktübersicht-wais) | [Funktionskatalog](fachkonzept.md#funktionskatalog-wais), [Rollen und Rechte](fachkonzept.md#rollen-und-rechte) |
| Architekt oder Architektin | [Architektur nach arc42](architektur.md#architekturdokumentation-nach-arc42) | [C4-Diagramme](architektur.md#c4-diagramme-von-wais), [Entscheidungsregister](architektur.md#entscheidungsregister) |
| Entwickler oder Entwicklerin | [Entwicklerhandbuch](entwicklung.md#entwicklerhandbuch) | [Voice-Core](technik.md#voice-core-aufbau-des-python-kerns), [Oberfläche](technik.md#oberfläche-aufbau-der-nextjs-anwendung), [Host und Desktop](technik.md#pc-host-und-desktop-app), [Datenmodell](technik.md#datenmodell-datenbank-rollen-und-migrationen), [Schnittstellen](technik.md#schnittstellen-von-wais), [Konfiguration](technik.md#konfiguration-umgebungsvariablen-und-schalter) und [Betriebsvariablen](technik.md#konfiguration-betriebsskripte-und-einrichtungsvariablen), [Qualität und Tests](entwicklung.md#qualität-und-tests) |
| in Administration oder Betrieb | [Administrationshandbuch](betrieb.md#administrationshandbuch) | [Betriebshandbuch](betrieb.md#betriebshandbuch), [Release und Ausrollen](betrieb.md#release-und-ausrollen) |
| in Sicherheit oder Datenschutz | [Sicherheit und Datenschutz](sicherheit-und-datenschutz.md) | [Rollen und Rechte](fachkonzept.md#rollen-und-rechte), [Befunde der ausgelieferten App](technik.md#befunde-der-ausgelieferten-desktop-app-rea) |
| verantwortlich für Releases | [Release und Ausrollen](betrieb.md#release-und-ausrollen) | [Befunde der ausgelieferten App](technik.md#befunde-der-ausgelieferten-desktop-app-rea), [Qualität und Tests](entwicklung.md#qualität-und-tests) |

## Dokumentenlandkarte

Ein Thema, eine Datei. Die Dokumentart folgt Diátaxis (Erklärung, Referenz, Anleitung, Lernpfad). Begründung und Pflegeregeln stehen im [Dokumentationskonzept](dokumentationskonzept.md). Jede Datei beginnt mit einem Inhaltsverzeichnis, und jedes Kapitel nennt in seiner Kopftabelle Zweck, Zielgruppe, Dokumentart und Quellen.

| Datei | Inhalt | Art |
|---|---|---|
| [fachkonzept.md](fachkonzept.md) | Produktübersicht, Funktionskatalog mit stabilen IDs, Rollen und Rechte | Erklärung, Referenz |
| [benutzerhandbuch.md](benutzerhandbuch.md) | Erste Schritte, Alltag, Fehlerbehebung | Anleitung, Lernpfad |
| [architektur.md](architektur.md) | arc42 in zwölf Abschnitten, C4-Diagramme, Entscheidungsregister | Erklärung, Referenz |
| [technik.md](technik.md) | Voice-Core, Oberfläche, Host und Desktop-App, Befunde der ausgelieferten App (REA), Datenmodell, Schnittstellen, Konfiguration | Erklärung, Referenz |
| [betrieb.md](betrieb.md) | Betriebshandbuch, Release und Ausrollen, Administrationshandbuch | Referenz, Anleitung |
| [sicherheit-und-datenschutz.md](sicherheit-und-datenschutz.md) | Sicherheitsmodell, Datenarten und Fristen, Zulieferung für das Datenschutzmanagement | Erklärung, Referenz |
| [entwicklung.md](entwicklung.md) | Entwicklerhandbuch, Qualität und Tests | Anleitung, Referenz |
| [glossar.md](glossar.md) | Begriffe | Referenz |
| [dokumentationskonzept.md](dokumentationskonzept.md) | Recherche, Struktur, Pflege der Dokumentation | Erklärung |

## Fertige Dokumente (PDF)

Alle Dokumente liegen zusätzlich als fertig gesetzte PDF-Dateien im WAMOCON-Design im Ordner `final/`: Kopfzeile mit Anschrift und Logo, Seitenzahl auf jeder Seite, Lesezeichen nach Überschriften. Die Markdown-Dateien sind die Quellen und bleiben maßgeblich. Nach inhaltlichen Änderungen werden die PDFs neu erzeugt.

| PDF | Inhalt |
|---|---|
| [00-W.A.I.S.-Produktdokumentation-Gesamt.pdf](final/00-W.A.I.S.-Produktdokumentation-Gesamt.pdf) | alle Dokumente mit Titelseite und Inhaltsverzeichnis |
| [01-Einstieg-und-Dokumentenlandkarte.pdf](final/01-Einstieg-und-Dokumentenlandkarte.pdf) | dieser Einstieg |
| [02-Dokumentationskonzept.pdf](final/02-Dokumentationskonzept.pdf) | Dokumentationskonzept |
| [03-Fachkonzept.pdf](final/03-Fachkonzept.pdf) | Fachkonzept |
| [04-Benutzerhandbuch.pdf](final/04-Benutzerhandbuch.pdf) | Benutzerhandbuch |
| [05-Architektur.pdf](final/05-Architektur.pdf) | Architektur |
| [06-Technik.pdf](final/06-Technik.pdf) | Technik |
| [07-Betrieb.pdf](final/07-Betrieb.pdf) | Betrieb |
| [08-Sicherheit-und-Datenschutz.pdf](final/08-Sicherheit-und-Datenschutz.pdf) | Sicherheit und Datenschutz |
| [09-Entwicklung.pdf](final/09-Entwicklung.pdf) | Entwicklung |
| [10-Glossar.pdf](final/10-Glossar.pdf) | Glossar |

## Bestehende Unterlagen in docs/

Diese Planpapiere, Anleitungen und Berichte bleiben unverändert und sind die Quelle für Hintergründe und Entscheidungen. Der Kopf jedes Papiers nennt seinen Stand, einige sind überholt oder beschreiben nur einen Plan.

| Thema | Unterlagen |
|---|---|
| Ausrollen und Zugänge | [Ausrollen für neue Nutzer](../ausrollen-neue-nutzer.md), [Persönliche Zugänge](../persoenliche-zugaenge.md), [Jira-Benutzer einrichten](../jira-benutzer-einrichten.md), [Eigener Runner](../runner-einrichten.md) |
| Entwicklungsaufträge | [Entwicklung im Betrieb](../entwicklung-im-betrieb.md), [Arbeitsliste](../entwicklung-im-betrieb-arbeitsliste.md), [Folgepaket 1](../folgepaket-1.md), [Aufträge an W.A.I.S. selbst (Rückstand)](../selbstauftraege.md), [Selbstüberarbeitung (nur Konzept)](../selbstueberarbeitung.md) |
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
- Die Dokumentation enthält keine Zugangsdaten und beschreibt Betrieb und Sicherheit nur so weit, wie `README.md`, `CLAUDE.md` und `docs/` es ohnehin tun.
- Zahlen mit Datum sind Momentaufnahmen. Der Zustand der Server ist, wo nicht anders vermerkt, "laut README, Stand" mit Datum angegeben und wurde in diesem Dokumentationsstand nicht am Server geprüft.
