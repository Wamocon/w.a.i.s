# Oberfläche: Aufbau der Next.js-Anwendung

| | |
|---|---|
| Zweck | Beschreibt, wie die Web-Oberfläche von W.A.I.S. (Ordner `ui/`) aufgebaut ist: Seiten, Komponenten, Logik, Anmeldung, Darstellung, Sicherheitsrichtlinien und Tests. |
| Zielgruppe | Entwicklerinnen und Entwickler, die an der Oberfläche arbeiten oder sie prüfen. |
| Dokumentart | Erklärung mit Referenztabellen |
| Stand | 19.11.2026, geprüft gegen Commit 497e3ce |
| Quellen | `ui/package.json`, `ui/next.config.ts`, `ui/src/app/`, `ui/src/components/`, `ui/src/lib/`, `ui/vitest.config.ts`, `ui/AGENTS.md` |

## 1. Überblick

Die Oberfläche ist eine Next.js-Anwendung (`next` 16.4.6, `react` 19.3.0, laut `ui/package.json`, Version 0.6.0). Sie ist die "Kommandozentrale" im WMC-Corporate-Design: ein Präsenzkern, Live-Untertitel, Stimmlinie, Zeitleiste der Werkzeuge, Canvas, Freigabekarten und die Einstellungen. Sprachverbindung zum Kern über den Pipecat-Client (`@pipecat-ai/client-js`) mit `@pipecat-ai/small-webrtc-transport`, Anmeldung über `@supabase/supabase-js`, Diagramme über `mermaid`.

Dieselbe Oberfläche läuft an drei Orten:

| Ort | Wie | Kern |
|---|---|---|
| Desktop-App | Electron lädt die Oberfläche (siehe [host-und-desktop.md](host-und-desktop.md)) | lokal ("Unterwegs") oder Büro, wählbar |
| Browser am PC | `next start` oder Entwicklungsserver auf Port 3000 | lokal oder Büro |
| Browser im Büro-LAN | Container `wamo-ui-blau` und `wamo-ui-gruen` auf Sokrates-2, gebaut mit `NEXT_PUBLIC_WAMO_NUR_BUERO=ja` | nur Büro |

Der Build für Sokrates-2 kennt keinen lokalen Kern: er steht nicht in der Sicherheitsrichtlinie (CSP), und die Betriebsart "unterwegs" gibt es dort nicht (`ui/src/lib/geraet.ts`, `ui/src/lib/betriebsart.ts`). Das Image entsteht mit `WAMO_UI_STANDALONE=1` (`output: "standalone"` in `ui/next.config.ts`).

Hinweis aus `ui/AGENTS.md`: Diese Next.js-Version hat laut Datei Änderungen gegenüber früheren Versionen, vor Änderungen an der Struktur gilt die mitgelieferte Dokumentation unter `ui/node_modules/next/dist/docs/`.

## 2. App-Router und Seiten

Es gibt genau eine Seite. Alles andere sind Ansichten innerhalb dieser Seite, erreichbar über den Hash der Adresse.

| Datei | Aufgabe |
|---|---|
| `ui/src/app/page.tsx` | Einzige Seite (`"use client"`). Zeigt `LoginGate`, nach der Anmeldung `Wamo`, das `useWamo()` aufruft und `WamoAnsicht` rendert. Eine Entwicklungsvorschau (`?vorschau=...`) lädt `components/Vorschau.tsx`, nur bei `next dev` und `NEXT_PUBLIC_WAMO_VORSCHAU=1`. |
| `ui/src/app/layout.tsx` | Schriften (vier lokale Schriftfamilien über `next/font/local`), Metadaten, Viewport (`viewportFit: "cover"`), Initialskript für das Farbschema vor dem ersten Zeichnen. |
| `ui/src/app/manifest.ts` | Web-App-Manifest (installierbar, `display: standalone`, Hintergrund `#07070a`). |
| `ui/src/app/version.json/route.ts` | Route `GET /version.json`: Gesundheitsprobe mit Version, Commit und Bauzeit (`no-store`). Das Umschaltskript `wamo-ui-umschalten.sh` nutzt sie laut `CLAUDE.md`. |
| `ui/src/app/globals.css` | Designtokens und Importe aller Komponenten-Stile. |
| `ui/src/app/fonts/` | Schriftdateien mit Lizenzen und `HERKUNFT.md`, Bau und Betrieb laden nichts von Fremdservern. |

Die Einstellungen sind keine eigene Route. Der Hash (`#einstellungen`, `#einstellungen/modellzugang`) wählt die Ansicht (`ui/src/lib/einstellungenAbschnitte.ts`, `einstellungenHash.ts`). Das funktioniert im Browser wie in der Desktop-App.

## 3. Zustand und Verbindung

| Pfad | Aufgabe |
|---|---|
| `ui/src/lib/useWamo.ts` | Der zentrale Hook. Baut `PipecatClient` mit `SmallWebRTCTransport`, startet über `startBotAndConnect({ endpoint, headers })`, empfängt Servernachrichten (`onServerMessage`), sendet Client-Nachrichten (`sendClientMessage`) und liefert die Aktionen (`WamoAktionen`: `connect`, `disconnect`, `decide`, `toggleMic`, `textSenden`, `stimmabdruck`, `office`, `mail`, `teams`, `entwuerfe` und weitere). Deklariert auch den Typ der Desktop-Brücke `window.wamoDesktop`. |
| `ui/src/lib/wamo.ts` | Zustand der Sitzung (`WamoState`, `initialState`) und abgeleitete Auswahlen (`istOnline`, `offeneEntscheidungen`, `wartetAufEntscheidung`). Der Store `wamo` ist global. |
| `ui/src/lib/store.ts` | Kleiner Store (`createStore`, `useSelect` über `useSyncExternalStore`): Komponenten abonnieren nur ihren Ausschnitt, ein neues Satzstück im Untertitel rendert nur den Untertitel. |
| `ui/src/lib/nachrichten.ts` | Prüft jede Servernachricht des Kerns (RTVI), unbekannte oder unvollständige ergeben `null` und werden ignoriert. Typen `Profil`, `Betrieb`, `Activity`, `Vorgang` und weitere. |
| `ui/src/lib/kernApi.ts` | Aufrufe an `/wamo/api` des Kerns mit dem Token der Sitzung (nur https oder Loopback, keine Cookies, einmal Token erneuern bei 401, `KernFehler`). |
| `ui/src/lib/kernSlot.ts` | Fragt `GET /wamo/slot` nach der aktiven Kern-Instanz (`a` oder `b`) und startet über `<kern>/i/<slot>/start`. Älterer Server ohne Slot: `<kern>/start`. |
| `ui/src/lib/betriebsart.ts` | Betriebsart `unterwegs` oder `buero` je Gerät. In der Desktop-App hält sie das Hauptprogramm, im Browser `localStorage`. Adressen stehen zur Build-Zeit fest, über die Brücke kommt nur der Name. |
| `ui/src/lib/geraet.ts`, `umgebung.ts` | Browser-Betrieb auf dem Server, Einrichtung des Laptops, Prüfung öffentlicher Adressen (Hinweis auf unverschlüsselte Verbindungen). |
| `ui/src/lib/verbindungsfrist.ts`, `drossel.ts`, `useGedrosselt.ts` | Fristen beim Verbinden, Drosselung von Anzeigen. |

## 4. Anmeldung und Erstanmeldung

| Pfad | Aufgabe |
|---|---|
| `ui/src/components/LoginGate.tsx` | Tür der Oberfläche: E-Mail und Passwort, danach der Code der Authenticator-App (zweiter Faktor, aal2). Rendert die App erst mit gültiger Sitzung (`Sitzung`). |
| `ui/src/lib/supabase.ts` | Browser-Client nur für die Anmeldung, öffentlicher Schlüssel, nie `service_role`. |
| `ui/src/lib/anmeldung.ts` | "Angemeldet bleiben" (`localStorage` oder `sessionStorage`), Höchstalter der Anmeldung: 168 Stunden in der Desktop-App (`DESKTOP_MAX_STUNDEN`), 24 Stunden im Browser (`BROWSER_MAX_STUNDEN`, `NEXT_PUBLIC_WAMO_ANMELDUNG_MAX_STUNDEN_BROWSER`). Komfortgrenze, erzwungen wird im Kern. |
| `ui/src/lib/nutzer.ts` | Kennung und E-Mail der angemeldeten Person in einem Modulspeicher (nichts wird gespeichert). |
| `ui/src/lib/erstanmeldung.ts` | Reine Logik der Erstanmeldung: Stand `keine`, `offen`, `abgelaufen`, `erledigt` von `GET /wamo/api/erstanmeldung`. Jede andere Antwort heißt `keine`, durchgesetzt wird im Kern. Passwörter stehen nie in Meldungen oder Speichern. |
| `ui/src/components/erstanmeldung/` | Geführter Ablauf: `Erstanmeldung.tsx` (Leiste der Schritte), `schritte.tsx` (Liste `ERSTANMELDUNG_SCHRITTE`), `PasswortSchritt.tsx`, `typen.ts`. Merker im `sessionStorage` (`wamo-erstanmeldung-<user_id>`). |
| `ui/src/components/einrichtung/` | Geführte Einrichtung beim Ausrollen: `EinrichtungsAblauf.tsx`, Schritte Token, API-Schlüssel, Zusammenfassung, Installer (`InstallerDownload.tsx`), Anbindung `fuerErstanmeldung.tsx`. |
| `ui/src/lib/einrichtung.ts`, `einrichtungSchritte.ts`, `installer.ts`, `installerApi.ts` | Prüfliste (`GET /wamo/api/einrichtung/stand`), Schritteliste, Installer-Download, Updates der App über die Brücke. |

## 5. Kommandozentrale (Hauptansicht)

Die Hauptansicht setzt `components/WamoAnsicht.tsx` zusammen, den Rahmen mit Reitern liefert `components/kommando/Rahmen.tsx`. Es gibt vier Darstellungen (`ui/src/components/kommando/darstellung.ts`): `normal` (drei Spalten), `fokus` (nur Kern und Untertitel), `zentrale` (große Kommandozentrale) und `nacht` (erzwungen dunkel).

| Pfad (unter `ui/src/components/`) | Aufgabe |
|---|---|
| `WamoAnsicht.tsx`, `kommando/Rahmen.tsx`, `kommando/Reiter.tsx` | Zusammenbau, Reiter, Hauptschaltfläche |
| `Kopfzeile.tsx`, `Statusleiste.tsx`, `ProfilChip.tsx`, `kommando/Statusanzeige.tsx`, `kommando/ZentraleStatus.tsx` | Wortmarke, Profil, Verbindung, Betriebsart, Modelle, PC-Host, Mikrofon, Uhrzeit, Zahnrad zu den Einstellungen |
| `kommando/PraesenzKern.tsx`, `Orb.tsx`, `kommando/KernRinge.tsx`, `kommando/Kernbereich.tsx` | Lichtkugel (WebGL, ein Fragment-Shader) in HUD-Ringen (SVG). Fehlt WebGL, zeigt das Stylesheet eine Kugel aus einem Farbverlauf. |
| `VoiceLine.tsx`, `kommando/Gespraech.tsx`, `LiveCaption.tsx`, `Verlauf.tsx` | Stimmlinie, Block Gespräch, Live-Untertitel, Verlauf (`role="log"`, nur fertige Züge) |
| `ActivityFeed.tsx`, `kommando/Aufgabenanzeige.tsx`, `kommando/Vorgaenge.tsx` | Zeitleiste der Werkzeugaufrufe, Aufgabenanzeige, Tafel "Vorgänge" |
| `Freigaben.tsx` | Freigabekarten und Auftragskarten, Entscheidung nur per Klick (ein getipptes Ja ersetzt keine Freigabe) |
| `kommando/Bedienung.tsx`, `MikrofonWahl.tsx` | Eingabepille mit Mikrofon, Texteingabe, Senden, Mikrofonliste |
| `kommando/StimmeEinlernen.tsx`, `kommando/StimmeIgnoriert.tsx`, `kommando/KernOderEinlernen.tsx` | Einlernen des Stimmabdrucks, Hinweis auf nicht angenommene Äußerungen (gibt es nur im Modus `streng`, im Standard `beobachten` verwirft der Kern nichts) |
| `kommando/BueroKarte.tsx`, `kommando/BueroSchalter.tsx` | Radialkarte der Bürogeräte |
| `Hinweise.tsx`, `GemerktHinweis.tsx`, `FehlerAnzeige.tsx`, `StillStart.tsx`, `AbmeldenRueckfrage.tsx` | Hinweiskarten, "Gemerkt"-Hinweis, Fehler, Hinweis nach Übernahme einer Sitzung, Rückfrage vor Abmelden (Laborkonten) |
| `BildschirmAnsicht.tsx` | Live-Bild des eigenen Laptops (Admin oder freigeschaltetes Mitglied mit laufender PC-Steuerung) |

## 6. Canvas, Dateien und Arbeitsergebnisse

| Pfad | Aufgabe |
|---|---|
| `ui/src/components/Canvas.tsx` | Zeigt, was W.A.I.S. per `canvas_zeigen` schickt: Tabelle, Code, Dokument, Diagramm (`mermaid`, per dynamischem Import geladen), Bild. |
| `ui/src/components/CanvasDateien.tsx`, `ui/src/lib/canvasDatei.ts` | Dateien der Person öffnen, nur im Browser und nie für Laborkonten. Typ nach den ersten Bytes, Grenzen laut `CLAUDE.md`: 10 MB, 16384 Pixel je Seite, 40 Megapixel, Text höchstens 2 MB. Die Datei geht nie an Kern oder Modell. |
| `ui/src/lib/canvasExport.ts`, `canvasBild.ts`, `export.ts` | Herunterladen als Text, Markdown, HTML im WMC-Design, JSON, CSV, Quelltext, Mermaid als PNG und SVG; Office-Dateien am PC (`export.ts`, Host). |
| `ui/src/components/CanvasHistorie.tsx`, `ui/src/lib/canvasHistorie.ts`, `canvasOeffnen.ts`, `canvasWahl.ts` | Historie geschlossener Reiter, Wiederöffnen |
| `ui/src/components/DateiHinweis.tsx` | Hinweis nach dem Speichern einer Datei am PC (Pfad, "Im Ordner zeigen") |
| `ui/src/components/MailFormular.tsx`, `MailVersand.tsx`, `TeamsFormular.tsx`, `JiraStory.tsx`, `ui/src/lib/mail.ts`, `teams.ts`, `jiraStory.ts` | Mail über Outlook, Teams-Nachricht, User Story in Jira: jeweils vorbereiten, Karte freigeben lassen |
| `ui/src/components/GespeicherteAuftraege.tsx`, `ui/src/lib/auftragEntwuerfe.ts`, `auftragStart.ts`, `auftragFrist.ts`, `auftragAbnahme.ts`, `einreichen.ts` | Entwicklungsaufträge: starten, für später speichern, Frist, Abnahme, Einreichen mit eigenem GitHub-Token (nur per Klick) |
| `ui/src/components/Teilen.tsx`, `Geteilt.tsx`, `Scans.tsx`, `ui/src/lib/teilenHilfe.ts` | Arbeit teilen, geteilte Arbeit, Scans und NAS-Dateien |

## 7. Einstellungen

Die Ansicht liegt in `ui/src/components/einstellungen/`, die Gliederung in `ui/src/lib/einstellungenAbschnitte.ts` (`ABSCHNITTE`). Wer welchen Abschnitt sieht, bestimmt `nurAdmin`, `auchMitToken` und `laborSicht` dort. Die Rolle kommt vom Kern, der sie noch einmal prüft.

| Abschnitt (ID) | Titel | Sichtbar | Komponente oder Logik |
|---|---|---|---|
| `konto` | Konto und Profil | alle | `KontoAbschnitt` in `Abschnitte.tsx` |
| `start` | Erste Schritte | alle, nie in der Laborsicht | `ErsteSchritte.tsx`, `einrichtung/` |
| `modellzugang` | Modellzugang | alle | `ModellZugang.tsx` mit `ModellWahl.tsx`, `ModellAuswahl.tsx`, `SprachWahl.tsx`, `SchluesselFormular.tsx` |
| `github` | GitHub-Zugang | alle (der Kern sagt, ob erlaubt) | `GithubZugang.tsx`, `lib/githubZugang.ts` |
| `verbrauch` | Verbrauch | Admins und Profile mit eigenem Claude-Code-Token | `Verbrauch.tsx`, `lib/verbrauch.ts` |
| `sprache` | Sprache und Ton | alle, auch Laborsicht (nur Mikrofon) | `SpracheAbschnitt` in `Abschnitte.tsx`, `MikrofonTest.tsx` (Mikrofontest in Sprache und Ton ohne W.A.I.S., Ergebnis je Gerät und Person im Browser), `SprachWahl.tsx` |
| `stimme` | Stimme | alle | `StimmeAbschnitt.tsx`: Liste der eingelernten Mikrofone (ein Abdruck je Mikrofon, höchstens drei), Einlernen, Löschen einzeln oder alle |
| `gedaechtnis` | Gedächtnis | nur Admins | `Gedaechtnis.tsx`, `lib/gedaechtnis.ts` |
| `mitglieder` | Neue Mitglieder | nur Admins | `NeueMitglieder.tsx`, `GithubRechte.tsx`, `lib/mitgliederUebersicht.ts` |
| `darstellung` | Darstellung | alle | `DarstellungAbschnitt` in `Abschnitte.tsx`, `kommando/darstellung.ts` |
| `geraete` | Geräte und PC | alle | `Geraete.tsx`, `GeraeteVerwaltung.tsx` |
| `fernzugriff` | Fernzugriff | nur Admins | `Fernzugriff.tsx`, `lib/fernzugriff.ts` |
| `aenderungen` | Änderungen | nur Admins | `Aenderungen.tsx`, `AenderungenFreigabe.tsx`, `lib/aenderungen.ts` |
| `teilen` | Teilen | alle | `Geteilt.tsx` (Block "Geteilte Arbeit") |
| `info` | Info | alle | `InfoAbschnitt` in `Abschnitte.tsx` (Version aus `WAMO_VERSION`) |

## 8. Logik unter `ui/src/lib/` nach Themen

Reine Logik liegt in `.ts`-Dateien ohne React, damit sie unter `node:test` prüfbar ist. Hooks haben das Präfix `use` und liegen daneben.

| Thema | Dateien | Aufgabe |
|---|---|---|
| Gespräch und Ton | `gespraech.ts`, `untertitel.ts`, `weicherStopp.ts`, `stillStart.ts`, `useStillStart.ts`, `pegelWarnung.ts`, `mikrofon.ts`, `mikrofonTest.ts` | Zeilen, Untertitel, Verhalten beim Unterbrechen, stiller Start beim Tippen, Mikrofon und Test |
| Stimme | `stimme.ts`, `stimmFilter.ts`, `stimmMikrofon.ts`, `mikrofonTest.ts`, `stimmfarben.ts`, `sprachwahl.ts` | Stimmabdruck, Sätze erst nach dem Urteil zeigen, Liste der Mikrofone der Abdrücke und Hinweis "Für dieses Mikrofon einlernen" (Name des Mikrofons nur im Browser, Schlüssel `wamo.stimme.mikrofon.<user_id>`), Mikrofontest (Schlüssel `wamo.mikrofontest.<user_id>`), Farben, Wahl Soniox oder Haus |
| Modelle | `modellauswahl.ts`, `modellwahl.ts`, `modellKurz.ts`, `modellzugangApi.ts`, `modellzugangHilfe.ts`, `schluesselhilfe.ts` | Wahl je Bereich, Zugang, Hilfetexte |
| Geräte und PC | `geraeteApi.ts`, `geraeteVerwaltung.ts`, `geraeteAnzeige.ts`, `geraeteMedien.ts`, `pcSchalter.ts`, `usePcSchalter.ts`, `liveBild.ts`, `bueroApi.ts`, `fernzugriff.ts`, `fernzugriffApi.ts` | Geräteliste, PC-Steuerung, Live-Bild, Büro-Karte, Fernzugriff |
| Labor | `laborPlatz.ts`, `laborKarte.ts`, `laborNeuladen.ts` | Laborsicht (Laborkonten), Karten, Neuladen |
| Darstellung | `thema.ts`, `useThema.ts`, `anzeigename.ts`, `kernRinge.ts`, `profilName.ts` | Hell und Dunkel, Namensschreibweisen, Ringe |
| Einstellungen | `einstellungen.ts`, `einstellungenAbschnitte.ts`, `einstellungenHash.ts`, `einstellungenVerlauf.ts` | gemerkte Wahl je Person und Gerät, Abschnitte, Hash |
| Sonstiges | `aenderungen*.ts`, `gedaechtnis*.ts`, `vorgaenge*.ts`, `buildInfo.ts`, `kopieren.ts`, `textEingabe.ts` | Selbstüberarbeitung, Gedächtnisvorschläge, Vorgänge, Version, Zwischenablage, Eingabe |

Der Name des Assistenten steht an einer Stelle: `ui/src/lib/anzeigename.ts` (Konstanten wie `LANGFORM`), gespiegelt zu `voice-core/persona.py`.

## 9. Darstellung und WMC-Design

- Dunkel ist der Standard, Hell wählbar je Gerät (`ui/src/lib/thema.ts`, Schlüssel `wamo.thema` in `localStorage`, Attribut `data-theme` am Element `html`). Ein Initialskript (`INIT_SKRIPT` in `layout.tsx`) setzt es vor dem ersten Zeichnen. Jeder Speicherzugriff steht in `try/catch`.
- Farben und Rollen als CSS-Variablen in `ui/src/app/globals.css` (`:root`). Hauptfarbe ist WMC-Rot `#F40E0E`, dazu Grautöne, Bernstein für "wartet" und Pink für Fehler, kein Blau (laut Kommentar in `globals.css` und `CLAUDE.md`). Hintergrund `#07070a` dunkel, `#f3f3f3` hell (`LEISTENFARBE` in `thema.ts`).
- Vier Schriften, je eine Aufgabe (`layout.tsx`): Cormorant Garamond nur für den Namen W.A.I.S., Unbounded für Überschriften und große Zahlen, JetBrains Mono für Beschriftungen und Zähler, Atkinson Hyperlegible für Fließtext. Die Dateien liegen im Repo, Lizenzen (OFL) daneben.
- Logos: `ui/public/wmc-logo.png`, `wmc-logo-dunkel.png`, `wmc-logo-klein.png`, Symbole für die installierbare App unter `ui/public/icons/`.
- Stile je Bereich in eigenen CSS-Dateien neben den Komponenten, mit Präfixen (`.kz` Kommandozentrale, `.kr-` Kernringe, `.vg-` Vorgänge, `.ez` Einstellungen, `.mz-` Modellzugang, `.ea-` Einrichtung, `.bk-` Büro-Karte, `.lb-` Live-Bild). `globals.css` importiert sie alle.
- Barrierefreiheit: Kontrastwerte sind im Kommentar von `globals.css` genannt (zum Beispiel WMC-Rot auf dem Hintergrund 4,7:1), Radiogruppen nach WAI-ARIA, Fokus wird nach Entscheidungen weitergegeben (`Freigaben.tsx`), das Zoomen bleibt erlaubt.

## 10. Sicherheitsrichtlinien

Die Header setzt `ui/next.config.ts` für alle Pfade (`source: "/:path*"`).

| Header | Wert und Wirkung |
|---|---|
| `Content-Security-Policy` | `default-src 'self'`. `connect-src` erlaubt nur die eigene Seite, die Supabase-Adresse und die Adressen der Kerne (`NEXT_PUBLIC_VOICE_CORE_URL`, im Sokrates-2-Build ohne lokalen Kern; `NEXT_PUBLIC_WAMO_KERN_BUERO` nur über https). `script-src` mit `'unsafe-inline'` (Hydration) und `blob:` (Audio-Worklet des Mikrofons), `'unsafe-eval'` nur in der Entwicklung. `style-src 'unsafe-inline'`. `img-src 'self' data: blob:`, also keine fremden Bilder. `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`, `frame-ancestors 'none'`. |
| `Referrer-Policy` | `no-referrer` |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Permissions-Policy` | `microphone=(self)`, `screen-wake-lock=(self)`, Kamera, Standort, Zahlung und USB aus |

Weitere Eigenschaften im Code: `poweredByHeader: false`, kein `service_role`-Schlüssel in `ui/`, Token gehen nur an https oder Loopback (`kernApi.ts`), jede Servernachricht wird geprüft (`nachrichten.ts`), Dateien der Person gehen nie an den Kern (`canvasDatei.ts`). Wer etwas Sicherheitsrelevantes tut, entscheidet der Kern, die Oberfläche führt nur durch den Ablauf.

## 11. Brücke zur Desktop-App

In der Desktop-App gibt es `window.wamoDesktop` (Typ in `ui/src/lib/useWamo.ts`). Felder: `isDesktop`, `levels` (Zustand melden), `markierung`, `betriebsart`, `rechnername`, `mikrofonStatus`, `geraet`, `version`, `update`. Im Browser fehlt das Objekt, die Oberfläche nennt dort, was fehlt. Die Gegenseite beschreibt [host-und-desktop.md](host-und-desktop.md).

## 12. Tests und Befehle

| Befehl (im Ordner `ui/`) | Wirkung |
|---|---|
| `npm run dev` | Entwicklungsserver |
| `npm run build`, `npm start` | Produktions-Build und Start |
| `npm run lint` | ESLint 9 mit `eslint-config-next` |
| `npm test` | Logiktests: `node --test "src/**/*.test.ts"` (Node lädt TypeScript selbst, kein DOM). 86 Dateien. |
| `npm run test:komponenten` | `vitest run` in jsdom für `*.comp.test.tsx` (Testing Library, user-event). 66 Dateien. |

Zwei getrennte Systeme, damit sich beide nicht stören (Begründung im Kopf von `ui/vitest.config.ts`). Testdateien liegen neben dem Code und gehören nie zum Build. Strategie insgesamt: [../entwicklung/qualitaet-und-tests.md](../entwicklung/qualitaet-und-tests.md).

## Weiterführend

- [Voice-Core](voice-core.md) (Gegenstelle der Nachrichten), [Host und Desktop](host-und-desktop.md), [Schnittstellen](schnittstellen.md), [Konfiguration](konfiguration.md)
- Benutzersicht: [../nutzung/benutzerhandbuch.md](../nutzung/benutzerhandbuch.md)
- Architektur: [../architektur/c4-diagramme.md](../architektur/c4-diagramme.md)
- Bestehende Planpapiere: [../../ausrollen-neue-nutzer.md](../../ausrollen-neue-nutzer.md), [../../komfort-paket.md](../../komfort-paket.md)
