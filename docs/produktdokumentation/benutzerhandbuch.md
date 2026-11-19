# Benutzerhandbuch W.A.I.S.

| | |
|---|---|
| Zweck | Führt Mitglieder Schritt für Schritt von der Anmeldung bis zur täglichen Arbeit mit W.A.I.S. und hilft bei den häufigsten Meldungen. |
| Zielgruppe | Mitglieder und Administratoren ohne technische Vorkenntnisse |
| Dokumentart | Anleitung und Lernpfad |
| Stand | 19.11.2026, geprüft gegen Commit 497e3ce |
| Quellen | `ui/src/components/`, `ui/src/lib/`, `voice-core/einrichtung_api.py`, `voice-core/erstanmeldung_api.py`, `README.md`, `docs/komfort-paket.md` |

## So benutzt du dieses Handbuch

W.A.I.S. ist der Sprachassistent der WAMOCON GmbH. Du sprichst mit ihm oder tippst, und er antwortet. Auf Wunsch öffnet er Programme an deinem Laptop, erstellt Dateien, bereitet Mails vor und merkt sich Dinge. Wichtig: Alles, was etwas verändert oder nach außen geht, passiert erst, wenn du auf einer Karte auf „Freigeben“ klickst. Das kann W.A.I.S. nie selbst.

Nicht jede Funktion steht jedem Profil offen. Was du siehst, hängt von deiner Rolle und davon ab, was dein Admin für dich freigeschaltet hat (siehe [Rollen und Rechte](fachkonzept.md#rollen-und-rechte)). Fehlt dir etwas in diesem Handbuch an deinem Bildschirm, frag deinen Admin.

### Lernpfad in vier Stufen

| Stufe | Kapitel | Nach dieser Stufe kannst du |
|---|---|---|
| 1. Starten | 1 | dich anmelden, dein Passwort wechseln, das Mikrofon prüfen und deine Stimme einlernen |
| 2. Sprechen und Zeigen | 2, 3 | ein Gespräch führen und Ergebnisse auf dem Canvas lesen, kopieren, herunterladen und teilen |
| 3. Am PC arbeiten | 4, 5 | W.A.I.S. an deinem Laptop arbeiten lassen und Dateien, Mails, Teams-Nachrichten und OneNote-Seiten anlegen |
| 4. Einrichten und Erweitern | 6, 7, 8, 9 | dich auf das Gedächtnis verlassen, Modelle und Stimme einstellen und Entwicklungsaufträge nutzen, falls sie für dich freigeschaltet sind |

Kapitel 10 hilft bei Meldungen und Störungen.

## 1. Erste Schritte

### 1.1 Installer laden und installieren

Du brauchst einen Windows-Laptop. Die Desktop-App heißt „W.A.I.S.“ und wird pro Benutzer installiert, ohne Administratorrechte.

1. Öffne W.A.I.S. im Browser. Die Adresse für das Büro steht auf deinem Willkommensblatt (laut `README.md` im Büronetz oder über WireGuard erreichbar).
2. Melde dich an (Abschnitt 1.2) und öffne in den Einstellungen den Abschnitt „Erste Schritte“. Dort bietet die Seite den Installer `WAIS-Setup-<Version>.exe` zum Laden an. Den Installer gibt es nur im Browser.
3. Starte die geladene Datei. Zeigt Windows SmartScreen eine Warnung, wähle „Weitere Informationen“ und dann „Trotzdem ausführen“. Das passiert, solange der Installer noch nicht mit einem Firmenzertifikat signiert ist.
4. Starte „W.A.I.S.“ aus dem Startmenü.
5. Warte beim ersten Start etwa eine halbe bis eine Minute. Die App richtet im Hintergrund die Umgebung für die PC-Steuerung ein und braucht dafür einmal Netz.

Quellen: `README.md` (Abschnitt „Windows-Installer“), `voice-core/verteilung_api.py`, `ui/src/components/einrichtung/InstallerDownload.tsx`.

### 1.2 Anmelden

1. Gib E-Mail und Passwort ein. Beim ersten Mal ist das Passwort das Startpasswort, das du von deinem Admin bekommen hast.
2. Lass „Angemeldet bleiben“ angekreuzt, wenn du nicht bei jedem Start neu anmelden willst. Ohne Haken endet die Anmeldung, wenn du die App oder den Tab schließt. Spätestens nach der angezeigten Zeit meldet W.A.I.S. dich ab (Standard: in der App sieben Tage, im Browser 24 Stunden).
3. Wähle „Anmelden“.

Ohne aktives W.A.I.S.-Profil und zweiten Faktor kommst du nicht hinein.

### 1.3 Zweiten Faktor einrichten

Beim ersten Anmelden richtet W.A.I.S. eine Authenticator-App ein (zum Beispiel Google Authenticator, Microsoft Authenticator oder 1Password).

1. Scanne den QR-Code mit der Authenticator-App. Lässt er sich nicht scannen, klappe „QR-Code lässt sich nicht scannen?“ auf und tippe den Schlüssel ein.
2. Gib die sechs Ziffern aus der App ein.
3. Wähle „Bestätigen“.

Bei jeder weiteren Anmeldung fragt W.A.I.S. nach dem aktuellen Code aus der App („Gib den aktuellen Code aus deiner Authenticator-App ein“). Fragt W.A.I.S. nach einem Code, obwohl du noch keine App eingerichtet hast, melde dich sofort bei deinem Admin, denn dann hat jemand anderes dein Konto benutzt.

### 1.4 Passwort wechseln (Erstanmeldung)

Das Startpasswort gilt nur für den ersten Zugang.

1. Gib ein neues Passwort mit mindestens 12 Zeichen ein und wiederhole es.
2. Wähle „Passwort ändern“. Nach dem Wechsel meldet W.A.I.S. alle anderen Geräte ab, auf denen du angemeldet warst.
3. Schreibe das Passwort nirgends ins Gespräch.

Ist die Frist für das Startpasswort abgelaufen, siehst du „Dein Startpasswort ist abgelaufen. Bitte melde dich bei Niko.“ Dann setzt dein Admin das Konto neu auf.

Danach führt dich W.A.I.S. durch den Modellzugang: Schritt „Claude-Code-Token“ und Schritt „API-Schlüssel“ (beide kannst du überspringen, wenn du keinen hast), dann die Zusammenfassung „So arbeitet W.A.I.S. für dich“ und im Browser der Installer. Ohne eigene Schlüssel arbeitet W.A.I.S. mit den Hausmodellen der Firma. Das alles lässt sich später unter Einstellungen, Modellzugang ändern.

Quellen: `voice-core/erstanmeldung_api.py`, `ui/src/components/erstanmeldung/PasswortSchritt.tsx`, `ui/src/lib/erstanmeldung.ts`, `ui/src/lib/einrichtungSchritte.ts`.

### 1.5 Prüfliste „Erste Schritte“ ansehen

1. Öffne Einstellungen, dann „Erste Schritte“.
2. Lies die Punkte: Anmeldung, Kern, Passwort, App-Version, Gerät, Host-Umgebung, Tunnel, Mikrofon, Stimme, Gespräch, Entwicklungsaufträge, Stimmabdruck, PC-Steuerung. Jeder Punkt zeigt „Bereit“, „Offen“ oder „Hinweis“ als Wort, nicht nur als Farbe.
3. Behebe, was „Offen“ ist. Danach wähle „Erneut prüfen“ (höchstens alle zehn Sekunden).
4. Zeigt die Liste „Update auf Version … verfügbar“, wähle „Update installieren“. Die App fragt vorher nach und startet danach neu.

Steht beim Laptop „Dein Laptop wartet auf die Freigabe durch einen Admin“, gib deinem Admin Bescheid. Ein Mitglied, das noch kein Gerät hatte, wird beim ersten Binden sofort freigegeben, bei einem Gerätewechsel entscheidet ein Admin.

Quellen: `voice-core/einrichtung_api.py`, `ui/src/lib/einrichtung.ts`, `ui/src/components/einstellungen/ErsteSchritte.tsx`.

### 1.6 Mikrofon prüfen

1. Erlaube Windows das Mikrofon für W.A.I.S. (Windows, Einstellungen, Datenschutz und Sicherheit, Mikrofon). Im Browser erlaubst du es für die Seite.
2. Öffne Einstellungen, dann „Sprache und Ton“ und wähle dein Mikrofon.
3. Wähle „Mikrofon testen“. Du brauchst dafür kein Gespräch.
4. Sei etwa drei Sekunden still, solange W.A.I.S. die Geräusche im Raum misst („Bitte still sein, ich messe die Geräusche im Raum“).
5. Sprich dann etwa fünf Sekunden, zum Beispiel: „Eins, zwei, drei, ich teste mein Mikrofon.“
6. Lies das Ergebnis mit Ampel, einem Satz, dem Namen des Mikrofons und den Messwerten: Gut, Etwas leise, Zu leise, Sehr laut oder Übersteuert. Bei „Zu leise“ sprich näher am Mikrofon oder wähle ein anderes Gerät, bei „Übersteuert“ weiter weg oder senke den Eingangspegel in Windows.

Während des Tests schweigt W.A.I.S.: Läuft ein Gespräch, hält die Seite die Wiedergabe an und lässt eine laufende Antwort abbrechen, und dein Mikrofon im Gespräch ist solange stumm. Spricht W.A.I.S. trotzdem, ist der Test ungültig, du bekommst kein Ergebnis und wiederholst ihn. Die Seite merkt sich nur das letzte Ergebnis je Gerät.

Quellen: `ui/src/components/einstellungen/MikrofonTest.tsx`, `ui/src/lib/mikrofonTest.ts`, `ui/src/lib/mikrofon.ts`.

### 1.7 Stimmabdruck einlernen (freiwillig)

Mit einem Stimmabdruck kann W.A.I.S. deine Stimme von anderen unterscheiden. Es speichert dafür nur Zahlen, nie eine Aufnahme. Ohne Abdruck nutzt du W.A.I.S. ohne Nachteil weiter, nur gesprochene PC-Befehle sind für Mitglieder dann nicht möglich, sondern nur getippte.

1. Starte ein Gespräch (Kapitel 2). Das Einlernen geht nur während eines Gesprächs.
2. Öffne Einstellungen, dann „Stimme“, und wähle „Stimme einlernen“.
3. Lies die Einwilligung und setze den Haken bei „Ich habe den Text gelesen und willige ein.“
4. W.A.I.S. sagt kurz, worum es geht. Lies danach den Text „Der Nordwind und die Sonne“ laut vor. Pausen sind kein Problem. Ein Balken zeigt, wie viele von etwa 20 Sekunden Sprache schon da sind.
5. Warte auf „Fertig. W.A.I.S. erkennt jetzt deine Stimme.“

Gut zu wissen:

- Es gibt einen Abdruck je Mikrofon, höchstens drei je Person. W.A.I.S. speichert dazu den Namen des Mikrofons, wie dein Browser oder die App ihn nennt. Ein Abdruck, der vor der Einführung dieser Regel eingelernt wurde, gilt als „Unbekanntes Mikrofon“. Wechselst du das Mikrofon, fragt W.A.I.S. „Für dieses Mikrofon ist deine Stimme noch nicht eingelernt. Jetzt einlernen?“, dazu gibt es „Für dieses Mikrofon einlernen“. „Neu einlernen“ ersetzt nur den Abdruck dieses einen Mikrofons. Hast du schon drei, lösche zuerst einen.
- Löschen: „Löschen“ bei einem Mikrofon entfernt nur dessen Abdruck, „Alle Abdrücke löschen“ entfernt alle und gilt zugleich als Widerruf deiner Einwilligung. Beides fragt noch einmal nach („Ja, Abdruck löschen“, „Ja, alle löschen“).
- Im Standardmodus misst W.A.I.S. die Stimme nur, zeigt das Ergebnis im Modul „Stimme“ (Eigen, Fremd, Unklar, Nicht eingelernt) und sperrt nichts: Jede Stimme darf unterbrechen, und deine Äußerungen erreichen das Modell auch bei ungenauer Erkennung. Der strenge Modus, in dem nur deine Stimme zählt, gilt nur, wenn dein Admin ihn ausdrücklich am Server einschaltet. Hintergrund zur Genauigkeit: [Recherche zur Sprechererkennung](../stimme-recherche-2026-11-18.md).
- Der Stimmabdruck ist keine Freigabe und schützt nicht vor Aufnahmen oder geklonten Stimmen.

Quellen: `voice-core/stimme_einlernen.py`, `voice-core/stimme_einwilligung.py`, `voice-core/stimme_mikrofon.py`, `voice-core/stimme_gate.py`, `ui/src/components/einstellungen/StimmeAbschnitt.tsx`, `ui/src/lib/stimme.ts`, `ui/src/lib/stimmMikrofon.ts`.

## 2. Ein Gespräch führen

1. Wähle „Gespräch starten“. W.A.I.S. verbindet sich („Verbinde …“) und begrüßt dich.
2. Sprich einfach los, oder tippe in das Eingabefeld „Nachricht an W.A.I.S.“ und wähle „Senden“. Mit Strg+M schaltest du das Mikrofon stumm oder wieder ein.
3. Unterbrich W.A.I.S. jederzeit, indem du sprichst. Sagst du beim Zuhören nur „mhm“ oder „genau“, redet es weiter. Ein einzelnes Wort lässt es an der Wortgrenze innehalten, und es setzt fort, wenn nichts nachkommt.
4. Frage nach der Uhrzeit, dem Datum oder aktuellen Dingen („Öffnungszeiten“, „Wetter“). W.A.I.S. fragt dafür die Uhr und das Web, statt zu raten.
5. Nutze die Schnellaktionen „Überblick“, „Tagesplan“ und „Offene Aufträge“, wenn du einen schnellen Einstieg willst, und „Verlauf“, um frühere Beiträge zu lesen.
6. Beende mit „Gespräch beenden“. Offene Freigaben und Aufträge verfallen dann (Meldung „Gespräch beendet. Offene Freigaben und Aufträge sind verfallen.“).

Was W.A.I.S. sagt, ist kurz und ohne Aufzählungen, denn es liest vor. Seinen Namen schreibt es als „Wais“.

Weitere Möglichkeiten:

- **Still starten beim Tippen:** In den Einstellungen (Sprache und Ton) lässt sich ein Schalter „Still starten beim Tippen“ je Gerät einschalten. Dann startet der erste Tastendruck eine Sitzung ohne Mikrofon, und die Antworten kommen als Text. Mit „Gespräch starten“ wird daraus ein Sprachgespräch.
- **Darstellung:** Über dem Kern wählst du Normal, Fokus, Zentrale oder Nacht. Hell oder Dunkel stellst du mit dem Schalter in der Kopfzeile oder unter Darstellung ein.
- **Untertitel:** Sie sind standardmäßig aus. Du schaltest sie in den Einstellungen unter Darstellung ein.
- **Warum ging etwas nicht?** Frag W.A.I.S. einfach: „Warum hat das nicht geklappt?“ Es nennt den Grund und was du tun kannst.
- **Eine Sitzung je Profil:** Meldest du dich auf einem zweiten Gerät an, übernimmt die neue Sitzung, und die alte zeigt „Sitzung beendet: Eine neue Sitzung dieses Profils hat übernommen.“
- **Hinweise:** Oben in der linken Spalte erscheinen höchstens drei Karten, zum Beispiel wenn jemand Arbeit mit dir geteilt hat.
- **Statusleiste:** In der Kopfzeile zeigen Module den Zustand von Büro, Modellen, PC, Mikrofon, Stimme, PC-Steuerung, Entwicklung und Netz.

Quellen: `ui/src/components/WamoAnsicht.tsx`, `ui/src/components/kommando/Bedienung.tsx`, `ui/src/lib/useWamo.ts`, `voice-core/soft_interrupt.py`, `voice-core/fehlerbuch.py`, `voice-core/sitzungen.py`, `docs/komfort-paket.md`.

## 3. Canvas nutzen

Das Canvas ist die Fläche neben dem Gespräch. Was man lesen muss, landet dort statt in der Sprache: Tabellen, Code, Dokumente, Mermaid-Diagramme und Bilder (als Verweis).

1. Bitte W.A.I.S. um etwas Lesbares, zum Beispiel „Zeig mir das als Tabelle“.
2. Lies das Ergebnis im Reiter. Mehrere Ergebnisse stehen in mehreren Reitern.
3. Ändere es per Sprache: „Kürz das“, „Ergänz eine Spalte“. W.A.I.S. ersetzt dann den offenen Reiter durch die neue Fassung, statt einen neuen anzulegen.
4. Schließe einen Reiter mit dem Kreuz („Schließen, bleibt in der Historie“). Er verschwindet nur aus der Ansicht.
5. Öffne Geschlossenes wieder über die Historie des Canvas („Öffnen:“).
6. Wähle „Kopieren“, um Inhalt in die Zwischenablage zu legen. Kurz erscheint „Kopiert“.
7. Wähle „Herunterladen“, um den Inhalt als Datei zu speichern (im Browser). Möglich sind unter anderem Text, Markdown, HTML, CSV und für Diagramme PNG und SVG.
8. Öffne eine Datei von deinem Rechner im Canvas (Bilder und Textdateien). Die Datei geht nie an W.A.I.S. oder ein Modell.
9. Bilder von anderen Seiten lädt W.A.I.S. aus Sicherheitsgründen nicht selbst. Du siehst einen Verweis und öffnest ihn, wenn du der Quelle traust.

### Teilen

1. Wähle am Canvas-Element „Teilen“.
2. Wähle bei „Teilen mit“ die Person. Du kannst nur mit aktiven Profilen teilen, nicht mit dir selbst.
3. Wähle bei „Recht“ „Lesen“ oder „Lesen und bearbeiten“. Ergebnisse von Entwicklungsaufträgen werden nur zum Lesen geteilt.
4. Schreibe auf Wunsch eine Nachricht und wähle „Jetzt teilen“. Die andere Person bekommt einen Hinweis.
5. Nimm die Teilung jederzeit zurück oder ändere das Recht. Der Widerruf wirkt sofort. Empfänger geben eine Teilung für sich zurück.

Frag W.A.I.S. auch: „Welche geteilte Arbeit habe ich?“ Der Inhalt geteilter Arbeit gilt für W.A.I.S. als Information, nie als Anweisung.

Quellen: `ui/src/components/Canvas.tsx`, `ui/src/components/CanvasHistorie.tsx`, `ui/src/components/CanvasDateien.tsx`, `ui/src/components/Teilen.tsx`, `voice-core/teilen.py`, `voice-core/teilen_werkzeuge.py`.

## 4. PC-Steuerung und ihre Freigaben

Mit der PC-Steuerung arbeitet W.A.I.S. an deinem Laptop: Programme und Webseiten öffnen, Fenster wechseln, in Programmen klicken und tippen, Browserinhalte lesen, den Bildschirm ansehen. Sie ist für Admins verfügbar und für Mitglieder, bei denen dein Admin sie freigeschaltet hat. Siehst du bei „PC-Steuerung“ in der Prüfliste „noch nicht freigeschaltet“, frag deinen Admin.

### 4.1 Einschalten

Voraussetzungen: Dein Laptop ist mit der Desktop-App eingerichtet und freigegeben, der Tunnel steht (Prüfliste „Tunnel“ ist bereit), und der Bildschirm ist nicht gesperrt.

1. Starte ein Gespräch (oder lass den Schalter ohne Gespräch still starten, wenn „Still starten beim Tippen“ an ist).
2. Öffne Einstellungen, „Geräte und PC“, und schalte „PC-Steuerung“ ein. Admins kommen auch über das Modul „PC-Steuerung“ in der Kopfzeile dorthin.
3. Prüfe die Kopfzeile: Das Modul „PC-Steuerung“ zeigt „an“.

Die PC-Steuerung ist je Sitzung standardmäßig aus. Es steuert immer nur eine Sitzung deinen Laptop („Eine andere Sitzung steuert diesen PC gerade“). In der Desktop-App zeigt ein Lichtrahmen das Fenster, in dem W.A.I.S. gerade handelt, im Browser gibt es den Rahmen nicht. Den Schalter „PC-Steuerung beim Start automatisch einschalten (dieses Gerät)“ nutze nur, wenn du allein bist: Ohne Sprecherprüfung reagiert W.A.I.S. dann auf jede Stimme im Raum.

### 4.2 Freigabekarten

Aktionen, die etwas ändern oder nach außen gehen, führt W.A.I.S. nicht selbst aus. Es zeigt eine Karte.

1. Lies die Karte genau. Sie nennt das Zielprogramm und den genauen Text, jedes Enter steht als ⏎ da. Was die Karte nicht ganz zeigen kann, wird gar nicht erst angefragt.
2. Wähle „Freigeben“ oder „Ablehnen“. Beide Knöpfe sind gleich wichtig. Eine Freigabe per Sprache gibt es nicht, auch kein gesprochenes „Ja“.
3. Entscheide zügig. Befehle und Webseiten gelten fünf Minuten, Senden, Tasten und Klicks zwei Minuten, danach verfällt die Karte. Es warten höchstens fünf Karten zugleich.

Solange eine Karte offen ist, ruhen am Laptop alle Eingaben. Das schützt davor, dass sich unter der Karte etwas ändert. Typische Karten: Senden in einem Mail- oder Chatfenster, ein Befehl, der etwas ändert, ein neues GitHub-Repository, Klicks auf Senden, Bezahlen, Löschen oder Veröffentlichen.

Ist der Bildschirm gesperrt, tut W.A.I.S. nichts am Laptop. Nur du kannst entsperren. W.A.I.S. sagt das und versucht es nicht auf anderem Weg.

### 4.3 Zusätzliche Regeln für Mitglieder

- **Stimmabdruck:** PC-Befehle per Sprache gehen nur mit eingelerntem Stimmabdruck. Ohne ihn tippst du den Befehl.
- **Karte nach Inhalten von außen:** Kamen im Gespräch Inhalte von einer Webseite, aus einer Websuche, vom Bildschirm oder aus einem Ergebnis, braucht jede Änderung am Laptop eine Karte („Änderung am Laptop nach Inhalten von außen“). Das gilt bis zum Ende der Sitzung.
- **Bildschirm ansehen:** Vor dem ersten Foto fragt W.A.I.S. einmal je Sitzung per Karte: „W.A.I.S. möchte deinen Bildschirm ansehen. Das Bild geht an das KI-Modell deines Profils.“ Ohne dein Ja gibt es kein Bild.

### 4.4 Live-Bild

Mit dem Live-Bild siehst du deinen eigenen Laptop in der Oberfläche, zum Beispiel am Handy. Das Bild wird nie aufgezeichnet und geht nie an ein Sprachmodell.

1. Schalte das Live-Bild am Laptop ein (Tray-Menü der Desktop-App, „Live-Bild einschalten …“). Dort bestätigst du die Einwilligung, und ein roter Rahmen zeigt, dass es läuft.
2. Öffne in der Oberfläche die Live-Ansicht und wähle den Monitor.
3. Willst du es aus der Ferne einschalten, bestätigst du mit einem frischen Code deiner Authenticator-App.

Das Live-Bild endet bei gesperrtem Bildschirm, beim Trennen, beim Abmelden und nach einer Zeitgrenze.

Quellen: `voice-core/pc_host.py`, `voice-core/pc_mitglied.py`, `host/wamo_host.py`, `ui/src/components/Freigaben.tsx`, `ui/src/lib/pcSchalter.ts`, `ui/src/components/BildschirmAnsicht.tsx`, `voice-core/bildstrom.py`.

## 5. Office-Funktionen: Dateien, Mail, Teams, OneNote

Diese Funktionen gehören zur PC-Steuerung. Sie erscheinen nur, wenn dein Admin sie am Server eingeschaltet hat und die PC-Steuerung an ist. Alles landet in deinem Büro-Programm, nicht bei W.A.I.S.

### 5.1 Datei speichern

1. Lass W.A.I.S. ein Ergebnis auf dem Canvas zeigen.
2. Wähle am Element zum Beispiel „Als Word speichern“ (möglich sind Word, Excel, PowerPoint, PDF, CSV, Markdown; Excel und CSV nur für Tabellen). Oder sag: „Speicher das als Word.“
3. Lies den Hinweis: Die Datei liegt im Ordner `Dokumente\WAIS` und ist geöffnet. Ist Dokumente auf OneDrive umgeleitet, synchronisiert OneDrive sie.

Das Speichern braucht keine Karte (Mitglieder nach Inhalten von außen schon).

### 5.2 Mail über Outlook

1. Sag: „Schreib eine Mail an …“ und nenne Empfänger, Betreff und Inhalt. Oder wähle am Canvas „Als E-Mail“ und fülle das Formular aus (Empfänger, Betreff, Text, optional ein Anhang). Nenne nur Adressen, die du kennst, W.A.I.S. rät keine.
2. Prüfe die Freigabekarte. Sie zeigt genau, was gesendet wird.
3. Wähle „Freigeben“. Im klassischen Outlook sendet W.A.I.S. nach dem Klick, und du kannst den Versand 30 Sekunden lang zurückholen. Im neuen Outlook öffnet W.A.I.S. einen fertigen Entwurf, und du sendest selbst.

W.A.I.S. sagt vorher nur, dass die Mail zur Freigabe bereitliegt, nie „gesendet“.

### 5.3 Teams-Nachricht

1. Sag: „Schreib in Teams an …“ oder wähle „Als Teams-Nachricht“ (Empfänger, Text, bei mehreren Empfängern ein Gruppenname). Der Text darf höchstens 1000 Zeichen lang sein.
2. Prüfe die Karte und wähle „Freigeben“.
3. Teams öffnet sich mit dem Text im Eingabefeld. Sende selbst mit Enter. W.A.I.S. sendet in Teams nie.

### 5.4 OneNote-Seite

1. Wähle am Canvas „Als OneNote-Seite“ oder sag es.
2. Prüfe die Karte und wähle „Freigeben“. Die Seite entsteht im Notizbuch „W.A.I.S.“ im OneDrive der Firma, nie in einem anderen Notizbuch.
3. Geht OneNote nicht, legt W.A.I.S. stattdessen eine Word-Datei in `Dokumente\WAIS` ab und nennt den Grund.

Quellen: `voice-core/office_werkzeuge.py`, `voice-core/outlook_werkzeuge.py`, `voice-core/teams_werkzeuge.py`, `voice-core/onenote_werkzeuge.py`, `ui/src/lib/export.ts`, `ui/src/components/MailFormular.tsx`, `ui/src/components/TeamsFormular.tsx`, `docs/office-und-versand.md`.

## 6. Gedächtnis

W.A.I.S. merkt sich, was für deine Arbeit nützlich ist.

1. Sag: „Merk dir, dass …“. W.A.I.S. speichert einen Satz.
2. Achte auf den Hinweis „Gemerkt“. Er zeigt, ob der Eintrag „persönlich“ ist (nur für dich, sofort gültig) oder „gemeinsam“. Gemeinsame Einträge von Mitgliedern warten als Vorschlag („Für alle vorgeschlagen, wartet auf Freigabe“), bis ein Admin sie freigibt.
3. Mit „Rückgängig“ im Hinweis vergisst W.A.I.S. den Eintrag wieder.
4. Sag keine Passwörter, Zugangsdaten, Konto- oder Gesundheitsdaten. W.A.I.S. speichert sie nicht.

Admins prüfen Vorschläge unter Einstellungen, Gedächtnis: „Für alle freigeben“ oder „Ablehnen“. Ein Admin, der ausdrücklich „für alle“ sagt, macht einen Eintrag sofort gültig, außer im selben Zug kamen Inhalte von außen vor. Persönliches merkt sich W.A.I.S. nach Inhalten von außen nur, wenn du es ausdrücklich sagst.

Quellen: `voice-core/tools.py`, `voice-core/gedaechtnis_api.py`, `ui/src/components/GemerktHinweis.tsx`, `ui/src/components/einstellungen/Gedaechtnis.tsx`.

## 7. Einstellungen

Die Einstellungen sind eine eigene Ansicht der Hauptseite (Adresse mit `#einstellungen`). Ein laufendes Gespräch bleibt dabei bestehen.

| Abschnitt | Wofür | Wer sieht ihn |
|---|---|---|
| Konto und Profil | E-Mail, Rolle, Abmelden | alle |
| Erste Schritte | Prüfliste, Installer, Updates | alle |
| Modellzugang | API-Schlüssel, Claude-Code-Token, Modus, Modelle, Stimme | alle |
| GitHub-Zugang | eigenes Token für Entwicklungsaufträge | alle, nutzbar nur mit Zulassung |
| Verbrauch | Kontingent deines Claude-Abos | Admins und Profile mit eigenem Claude-Code-Token |
| Sprache und Ton | Mikrofon, Mikrofontest, Hören und Stimme | alle |
| Stimme | Stimmabdruck einlernen oder löschen | alle |
| Gedächtnis | Vorschläge prüfen | nur Admins |
| Neue Mitglieder | Einrichtungsstand je Person, GitHub-Rechte | nur Admins |
| Darstellung | Ansicht, Helligkeit, Untertitel | alle |
| Geräte und PC | Verbindungen, PC-Steuerung, Betriebsart, Gerät einrichten | alle, Geräteverwaltung nur Admins |
| Fernzugriff | Desktop der Sparks unterwegs bedienen | nur Admins |
| Änderungen | Stand der Selbstüberarbeitung | nur Admins |
| Teilen | Geteilte Dokumente und Dateien | alle |
| Info | Version, Kern und Hinweise | alle |

### 7.1 Modelle einstellen

1. Öffne Einstellungen, dann „Modellzugang“.
2. Hinterlege auf Wunsch deinen eigenen API-Schlüssel („Claude mit eigenem Schlüssel“) oder deinen Claude-Code-Token. Tippe oder sprich den Schlüssel nie im Gespräch, sondern nur im Formular. Ein Schlüssel im Gesagten wird entfernt.
3. Wähle den Modus. „Automatisch“ lässt W.A.I.S. das beste Modell wählen, „Nur Hausmodelle“ lässt nichts an Anthropic gehen. Hat ein Admin dein Profil auf Hausmodelle festgelegt, ist der eigene Schlüssel gesperrt.
4. Wähle unter „Modelle je Aufgabe“ für Gespräch, Bilder und Hintergrund ein Modell oder „Automatisch (Standard)“.
5. Warte auf „Wird gespeichert …“. Änderungen gelten ab der nächsten Sitzung.

### 7.2 Hören und Stimme einstellen

1. Öffne Einstellungen, „Sprache und Ton“.
2. Wähle bei Hören und bei Stimme „Soniox (Standard)“ oder „Im Haus (Datenschutz)“. Im Haus bleiben Sprache und Ton auf den Servern der Firma.
3. Wähle bei „Im Haus“ eine der angebotenen Stimmen.

Ist „Im Haus“ am Server nicht eingerichtet, zeigt die Seite einen Satz dazu, und W.A.I.S. nutzt Soniox.

Quellen: `ui/src/lib/einstellungenAbschnitte.ts`, `ui/src/components/ModellZugang.tsx`, `ui/src/components/ModellAuswahl.tsx`, `ui/src/components/SprachWahl.tsx`, `voice-core/modellzugang.py`.

## 8. Büro-Karte und Geräte

Der Reiter „Büro“ zeigt den Zustand der gemeinsamen Bürogeräte (Server, Drucker, Netz, Speicher, Fernseher, Lautsprecher, Steckdosen) mit Wort und Form, nicht nur mit Farbe. Per Sprache fragst du Zustände ab („Wie voll ist der Toner?“) und schaltest Fernseher, Lautsprecher und Steckdosen („Mach den Fernseher aus“), aber nur, wenn du es ausdrücklich sagst. Drucken (nur eigene Canvas-Dokumente, höchstens 20 Seiten) braucht immer eine Karte. Scans landen in deiner Ablage unter „Scans“. Die Knöpfe in der Büro-Karte sehen nur Admins.

Den Bildschirm deines Laptops auf einen Fernseher spiegeln kann W.A.I.S. noch nicht.

Quellen: `voice-core/buero_api.py`, `voice-core/geraete_werkzeuge.py`, `ui/src/components/kommando/BueroKarte.tsx`, `ui/src/components/Scans.tsx`.

## 9. Entwicklungsaufträge

Mit Entwicklungsaufträgen lässt du Claude Code Software planen, prüfen, testen oder recherchieren. Das läuft in einer geschützten Umgebung auf einem Firmenserver, nicht auf deinem Laptop. Für wen? Admins, und Mitglieder nur im Büro und nur, wenn dein Admin es für dich freigeschaltet hat. Du brauchst außerdem einen eigenen Zugang für Claude Code (Token, API-Schlüssel) oder Hausmodelle, falls das eingeschaltet ist. Steht „Entwicklungsaufträge sind für dein Profil noch nicht freigeschaltet“ in der Prüfliste, frag deinen Admin.

### 9.1 Einen Auftrag starten

1. Beschreibe den Auftrag: „Bereite einen Entwicklungsauftrag vor, der …“. W.A.I.S. fragt höchstens einmal nach, wenn etwas fehlt.
2. Prüfe die Karte „Entwicklungsauftrag“ im Reiter „Aufträge“: Projekt, Auftragsart, Auftragstext und Abnahme (die prüfbaren Ziele).
3. Wähle „Starten“, oder „Verwerfen“, oder „Für später speichern“. Gespeicherte Aufträge findest du unter „Gespeicherte Aufträge“ und lädst sie mit „Laden“.
4. Verfolge den Fortschritt im Reiter „Vorgänge“: Schritte, Prozent, Restzeit. Mit „Zur Freigabe“ springst du zu einer Karte, die auf dich wartet.
5. Sieh dir das Ergebnis an („Ergebnis ansehen“) und teile es auf Wunsch (nur zum Lesen).

Aufträge mit Abnahmekriterien arbeiten in Runden, bis das Ziel erreicht ist. Ist es nicht erreicht, sagt W.A.I.S. das ehrlich. Höchstens drei Aufträge laufen für dich zugleich, sechs für alle. Mitglieder bekommen ohne eigenen GitHub-Zugang nur Recherchen ohne Repository.

### 9.2 Änderungen einreichen (eigener GitHub-Zugang)

1. Hinterlege unter Einstellungen, „GitHub-Zugang“ dein eigenes Token. Es wird verschlüsselt gespeichert, du siehst danach nur Konto, Art und Ablauf.
2. Nach einem Auftrag am Repository erscheint die Karte „Einreichen“.
3. Prüfe jede markierte Datei und bestätige sie einzeln. „Einreichen“ ist erst dann aktiv.
4. Wähle „Einreichen“. Erst jetzt schiebt W.A.I.S. den Zweig `wamo/<auftrag>` hoch und öffnet einen Pull Request. Gemergt wird nie durch W.A.I.S. Mit „Verwerfen“ wirfst du die Änderung weg.

Quellen: `voice-core/dev_agent.py`, `voice-core/entwicklung_betrieb.py`, `ui/src/components/Freigaben.tsx`, `ui/src/components/GespeicherteAuftraege.tsx`, `ui/src/components/GithubZugang.tsx`, `ui/src/components/kommando/Vorgaenge.tsx`, `docs/persoenliche-zugaenge.md`.

## 10. Fehlerbehebung

### 10.1 Anmeldung und Konto

| Meldung | Ursache | Was du tust |
|---|---|---|
| „E-Mail oder Passwort stimmt nicht.“ | Tippfehler oder falsches Passwort | Eingabe prüfen, bei Bedarf Admin bitten, das Konto zurückzusetzen |
| „Der Code passt nicht. Nimm den aktuellen aus der App.“ | Der Code ist abgelaufen oder falsch | Warte auf den nächsten Code in der Authenticator-App und gib ihn ein |
| „Anmeldeserver nicht erreichbar. Bist du im Büronetz oder per WireGuard verbunden?“ | Kein Netz zum Büro | Büronetz oder WireGuard verbinden, dann erneut versuchen |
| „Kein Zugang: kein aktives W.A.I.S.-Profil oder zweiter Faktor fehlt.“ | Profil gesperrt oder zweiter Faktor nicht eingerichtet | Admin fragen |
| „Bitte ändere zuerst dein Startpasswort. Melde dich dafür neu an.“ | Erstanmeldung noch offen | Neu anmelden und das Passwort wechseln (Abschnitt 1.4) |
| „Dein Startpasswort ist abgelaufen. Bitte melde dich bei Niko.“ | Frist abgelaufen | Admin bitten, das Konto neu aufzusetzen |
| „Das neue Passwort braucht mindestens 12 Zeichen.“ oder „Die beiden Passwörter sind nicht gleich.“ | Eingabe unzulässig | Passwort mit mindestens 12 Zeichen zweimal gleich eingeben |
| „Das neue Passwort muss sich vom Startpasswort unterscheiden.“ | Gleiches Passwort | Ein anderes wählen |
| „Zu viele Versuche, bitte in zehn Minuten noch einmal.“ | Zu oft versucht | Zehn Minuten warten |
| „Deine Anmeldung ist abgelaufen. Bitte neu anmelden.“ oder „Deine Anmeldung ist zu alt. Bitte neu anmelden.“ | Höchstalter der Anmeldung erreicht | Neu anmelden |

### 10.2 Gespräch und Mikrofon

| Meldung oder Beobachtung | Ursache | Was du tust |
|---|---|---|
| „Mikrofon gesperrt: bitte in den Windows-Einstellungen für diese App freigeben.“ | Windows blockiert das Mikrofon | Windows, Einstellungen, Datenschutz und Sicherheit, Mikrofon: Zugriff für Desktop-Apps erlauben, im Browser für die Seite |
| „Es kommt keine Mikrofonspur an, W.A.I.S. hört dich nicht.“ | falsches oder stummes Gerät | Unter „Sprache und Ton“ ein Mikrofon wählen, Kabel und Stummschaltung prüfen, Test wiederholen |
| „Dein Mikrofon ist sehr leise. Ist das richtige Gerät gewählt?“ | geringer Pegel | Näher sprechen oder Gerät wechseln |
| Das Mikrofon lässt sich nicht öffnen | ein anderes Programm (Teams, Zoom) nutzt es | Das Programm schließen oder ein anderes Mikrofon wählen |
| „Die Wiedergabe wurde vom Browser blockiert. Bitte einmal in die Seite klicken.“ | Browser blockiert Ton | Einmal in die Seite klicken |
| „Voice-Core nicht erreichbar“ | Der Kern antwortet nicht | Verbindung prüfen, Gespräch neu starten, sonst Admin fragen |
| „Verbindung getrennt. Verbindung weg, Freigabe verfällt (auch offene Entwicklungsaufträge).“ | Netz weg | Neu verbinden und die Karten neu anlegen lassen |
| „Sitzung vom Voice-Core beendet.“ | Du hast dich anderswo angemeldet, die Anmeldung ist zu alt oder das Profil wurde geändert | Neu anmelden |
| „Sitzung beendet: Eine neue Sitzung dieses Profils hat übernommen.“ | zweite Anmeldung mit demselben Profil | Nur ein Gerät zugleich nutzen |

### 10.3 PC-Steuerung

| Meldung oder Beobachtung | Ursache | Was du tust |
|---|---|---|
| „PC-Steuerung nicht eingeschaltet: Diese Sitzung hat keinen PC-Host (Laptop nicht eingerichtet oder keine Admin-Rolle).“ | Dein Laptop ist nicht gebunden, oder die PC-Steuerung ist für dich nicht freigeschaltet | Laptop in der Desktop-App einrichten, sonst Admin fragen |
| „PC-Steuerung nicht eingeschaltet: Der PC ist nicht erreichbar.“ | Tunnel oder Host laufen nicht | Prüfliste „Tunnel“ ansehen, im Büronetz sein, App neu starten |
| „PC-Steuerung nicht eingeschaltet: Der Bildschirm am PC ist gesperrt.“ | Laptop gesperrt | Entsperren und den Schalter erneut betätigen |
| „Eine andere Sitzung steuert diesen PC gerade“ | zweite Sitzung | Die andere Sitzung beenden |
| „Der Tunnel steht nicht. Bist du im Büronetz?“ | Verbindung zum Büro fehlt | Büronetz oder WireGuard verbinden |
| „Dein Laptop wartet auf die Freigabe durch einen Admin.“ | Gerät beantragt | Admin bitten, es freizugeben |
| „Dein Laptop ist gesperrt, bitte wende dich an einen Admin.“ | Gerät gesperrt oder widerrufen | Admin fragen |
| „Die Python-Umgebung fehlt. Netz zu PyPI und GitHub nötig, die App versucht es beim nächsten Start erneut.“ | Erstes Einrichten ohne Netz | Mit Netz die App neu starten |
| W.A.I.S. sagt, ein Befehl gehe nur getippt (Stimmabdruck) | Mitglied ohne eingelernten Stimmabdruck | Stimme einlernen (Abschnitt 1.7) oder den Befehl tippen |
| Eine Karte ist verschwunden | Frist abgelaufen oder Verbindung weg | Den Auftrag neu stellen und die neue Karte entscheiden |

### 10.4 Funktionen fehlen

| Beobachtung | Ursache | Was du tust |
|---|---|---|
| Kein Knopf „Als Word speichern“, „Als E-Mail“, „Als Teams-Nachricht“ oder „Als OneNote-Seite“ | Office ist am Server nicht eingeschaltet, oder PC-Steuerung ist aus oder nicht freigeschaltet | PC-Steuerung einschalten, sonst Admin fragen |
| „Entwicklungsaufträge sind für dein Profil noch nicht freigeschaltet.“ oder „... am Server ausgeschaltet.“ | Freischaltung oder Schalter fehlt | Admin fragen |
| „Für Entwicklungsaufträge fehlt dein eigener Zugang zu Claude Code (Karte Modellzugang).“ | Kein Token und kein Schlüssel | Unter Modellzugang hinterlegen oder Admin nach Hausmodellen fragen |
| „Dieses Bild lässt sich nicht anzeigen.“ | Fremdes Bild wird nie von W.A.I.S. geladen | Verweis öffnen, wenn du der Quelle traust |
| Menüpunkt fehlt (zum Beispiel Gedächtnis, Fernzugriff, Änderungen) | Der Abschnitt ist nur für Admins | Admin fragen |

Hilft nichts davon, nenne deinem Admin die genaue Meldung und frage W.A.I.S. im Gespräch: „Warum ging das nicht?“ Es erklärt den Grund aus dem Verlauf der Sitzung.

## Weiterführend

- [Produktübersicht](fachkonzept.md#produktübersicht-wais): was W.A.I.S. kann und was nicht
- [Funktionskatalog](fachkonzept.md#funktionskatalog-wais): alle Funktionen mit Voraussetzung und Freigabe
- [Rollen und Rechte](fachkonzept.md#rollen-und-rechte): wer was darf
- [Administrationshandbuch](betrieb.md#administrationshandbuch): Anleitung für Admins
- [Glossar](glossar.md)
- Bestehende Dokumente: [Komfort-Paket](../komfort-paket.md), [Office und Versand](../office-und-versand.md), [Ausrollen neuer Nutzer](../ausrollen-neue-nutzer.md)
