# Ausrollen für neue Nutzer: Erstanmeldung, Passwort, Installer, Ersteinrichtung und Rechte

Planpapier, Stand 15.11.2026, Basis `origin/main` b0f0bb0 (Zweig `docs/ausrollen-plan`, nur dieses Papier, kein Code). Grundlage sind der Wunsch und die
Entscheidungen von Niko vom 15.11.2026, der Stand der sieben neu angelegten Konten, die Befunde aus dem Repo und zwei Reviews des Entwurfs (Sicherheit und
Architektur, Abschnitt 11). Kennzeichnung wie in den anderen Planpapieren: **B** belegt (Datei:Zeile), **A** abgeleitet, **V** vermutet oder nur am Server, am
Laptop oder in GoTrue prüfbar. Nichts wurde am Server, an der Datenbank, an GoTrue oder an einem Laptop berührt. Pfade gelten relativ zur Repo-Wurzel, Bezeichner
stehen in ASCII. Im Text heißt der Assistent W.A.I.S., technisch bleibt alles `wamo`. Das Testlabor am Sa 28.11.2026 hat Vorrang und darf nie gefährdet werden;
Laborprofile bekommen keine der neuen Funktionen.

## Entscheidungen und Kurzfassung

**Wunsch von Niko (wörtlich, 15.11.2026).** "Wir brauchen einen Ausrollmechanismus! Ich stelle mir das so vor: 1. User meldet sich das erste mal an! 2. MFA
hinterlegen! 3. Passwort sofort ändern! 4. Dann wird man gebeten die Installationsdatei herunterzuladen in der Oberfläche! 5. Mit der Installation wird alles auf
dem Laptop das erste mal für W.A.I.S. eingerichtet, Tunnel, PC Steuerung und alles Tools die W.A.I.S. braucht um mit dem User den eigenen Laptop zu steuern und
Entwicklunsaufträge auf Sokrates 2 zu starten mit seinem Claude Code Konto! Wenn er kein Claude Code Konto hat dann werden die Hauseigenen Modelle für die
Enwicklungsaufträge benutzt!" Dazu: "SONIOX läuft bei allen Usern!" und der Anzeigename ist der volle Name (zum Beispiel "Nikolaj Schefner").

**Entscheidungen von Niko, verbindlich (15.11.2026).**

| Nr | Bereich | Entscheidung | Folge im Papier |
| --- | --- | --- | --- |
| D1 | Ablauf | Erste Anmeldung, zweiter Faktor, Passwort sofort ändern, Installer aus der Oberfläche, Einrichtung durch die Installation | Abschnitt 3, Pakete P1 bis P3 |
| D2 | Modellzugang | Wörtlich: "Ok, dann beim Ausrollen wird der User erst nach Claude Code Auth Token und dann nach Claude Code API Key gefragt, wenn er beides nicht hat dann, werden die Hausmodelle benutzt für alles!" Also nach Faktor und Passwortwechsel zuerst der Claude-Code-Token (`sk-ant-oat`, Vorrang für Entwicklungsaufträge), dann der API-Schlüssel (`sk-ant-api`), beides überspringbar; ohne beides alles über Hausmodelle | 4.7, Stationen 3a und 3b in Abschnitt 3, Pakete P2 und P6 |
| D3 | Stimme | Soniox für alle Profile, unabhängig vom Modellzugang | 2.5 (heute schon so), 4.7 |
| D4 | Name | Anzeigename ist der volle Name | 2.1, `wamo_nutzer.py umbenennen` |

**Kurzfassung.**

1. **Vieles steht schon.** Anmeldung mit zweitem Faktor, Ersteinrichtung der Authenticator-App, Bindung des Laptops mit eigenem Schlüssel, Tunnel je Gerät,
   Host-Umgebung aus dem Installer, geführte Eingabe von API-Schlüssel und Claude-Code-Token, Hausmodelle als Rückfall im Gespräch und Soniox für alle sind gebaut
   (Abschnitt 2). Es fehlen: der erzwungene Passwortwechsel, der Download vom Server, eine Abschlussprüfung mit klarer Rückmeldung, die Rechte der Mitglieder für
   PC-Steuerung und Entwicklungsaufträge sowie Entwicklungsaufträge ohne Claude-Zugang über Hausmodelle.
2. **Sofort und ohne Code:** Die sieben Konten sind nur im Profil gesperrt, nicht in GoTrue. Wer ein Startpasswort kennt, kann heute schon einen eigenen zweiten
   Faktor binden (A, 2.1). Empfehlung: die sieben Konten jetzt in GoTrue sperren (`ban_duration` über die Admin-Schnittstelle am Server) und ihre Startpasswörter als
   verbraucht ansehen (Entscheidung N4). Das berührt weder Kern noch Migration noch Oberfläche.
3. **Passwortwechsel: zuerst messen.** GoTrue ist mit `GOTRUE_SECURITY_UPDATE_PASSWORD_REQUIRE_REAUTHENTICATION` eingerichtet (B). Ob GoTrue dann auch in einer
   frischen Sitzung einen Bestätigungscode verlangt, ist offen (B, der Token-Test nennt es selbst offen). **Ergebnis P0 (15.11.): Zweig A, mit Weg über den Kern, siehe 6.2.** Paket P0 misst das zuerst auf einem Wegwerf-Stack. Zweig A:
   Wechsel ohne Code möglich, dann ruft die Oberfläche GoTrue direkt auf (einfach), und die Laborhärtung ist für frische Sitzungen wirkungslos (eigener Befund für das
   Labor). Zweig B: Code nötig, dann fängt ein Hook in der Datenbank den Code, und der Kern gibt ihn nur in der Erstanmeldung nach einem frischen Code aus der
   Authenticator-App heraus (4.1). In beiden Zweigen gibt es keinen Service-Schlüssel im Kern oder in `ui/`.
4. **Der Merker liegt auf der Ebene des Kontos und erledigt sich selbst.** Konten sind für alle Schemas gemeinsam (`auth.users`), deshalb liegt der Merker in einem
   eigenen kleinen Schema `wamo_auth`, eingerichtet mit eigenem SQL und eigenem Rückweg, nicht in der Migrationskette je Schema. Ein Trigger auf `auth.users` setzt
   "erledigt", sobald GoTrue das Passwort innerhalb der Frist geändert hat. Der Kern kann das weder setzen noch zurücksetzen; er sperrt bis dahin alles außer den
   Wegen der Erstanmeldung, in der Middleware und bei jeder Route.
5. **Download nur aus dem Kern**, weil die Oberfläche auf Sokrates-2 nur liest und niemanden kennt. Ein Update-Knopf in der App kommt erst zusammen mit einer
   Signaturprüfung in der App (Schlüssel offline auf einem Hardware-Token); vorher würde ein kompromittierter Kern zur Verteilstelle.
6. **Befund H1 wird mit einem Rechte-Modul gelöst** (`voice-core/rechte.py`): PC-Steuerung und Entwicklungsaufträge fragen dieselbe Stelle, auch Prompt,
   Host-Client, Nachholen, Freigaben und Oberfläche. Mitglieder bekommen eine engere Werkzeugliste, eine Freischaltung je Profil (Pilot möglich) und Schutz gegen
   Prompt-Injection; Laborprofile nie etwas.
7. **Modellzugang nach D2:** Die Logik steht fast vollständig (B): Ein Token hat für Entwicklungsaufträge Vorrang, ohne API-Schlüssel läuft das Gespräch auf
   Hausmodellen, auch mit Token (Mischfall, 4.7). Neu sind die zwei Schritte im Ablauf und Entwicklungsaufträge mit Hausmodellen; dafür braucht es einen Prüfauftrag
   und einen Proxy auf Sokrates-2, weil die Sandbox den Port von LiteLLM absichtlich sperrt (B).
8. **Kapazität:** Der Dispatcher führt genau einen Auftrag gleichzeitig aus, und Projektnamen kennen kein Profil (B). Vor Entwicklungsaufträgen für acht Personen
   braucht es Trennung je Profil, Grenzen je Profil und eine Warteschlange (4.6).
9. **Aufwand 197 Stunden in zehn Paketen** (Abschnitt 6), mit Zweig A etwa 190. **Zeit:** Das Planpapier des Labors legt den Freeze auf So 15.11.
   (`docs/testlabor-wamo.md:34`, E14), der Auftrag nennt Fr 20.11. Empfohlen ist in beiden Fällen: vor dem Labor nur Prüfaufträge, rote Tests und Code auf Zweigen,
   keine Merges (jeder Merge auf `main` baut am Server dev und test, `.github/workflows/deploy.yml:1` bis `:6`), Rollout ab Mo 30.11. Eine Pilotperson ab etwa
   Mi 9.12., alle sieben Kollegen ab etwa Mi 16.12.2026.

**IQ:** Jede Pflicht sitzt dort, wo sie sich nicht umgehen lässt: Passwortstärke in GoTrue, Erledigung im Trigger, Sperre im Kern, Rechte in einem Modul, Vertrauen
in die Updates in der App. **EQ:** Ein neuer Kollege bekommt ein Blatt, folgt klaren Schritten und sieht am Ende eine grüne Liste statt einer stillen Fehlermeldung;
Niko sieht, wer wie weit ist, und muss beim Start nichts einstellen. **VQ:** Ein Ablauf in Stationen (Abschnitt 3), je Schritt eine IST-SOLL-Tabelle, je Paket ein
Block mit immer gleichen Feldern. **Synthese:** Jetzt die sieben Konten in GoTrue sperren und P0 messen; nach dem Labor zuerst Erstanmeldung und Download, dann
Prüfliste mit signierten Updates, dann Rechte der Mitglieder, zuletzt Hausmodelle für Entwicklungsaufträge. Alles hinter Schaltern, Standard aus.

## 1. Ziel, Erfolgsmaße, Nicht-Ziele

**Ziel.** Ein neues Mitglied kommt mit einem Willkommensblatt in höchstens 20 Minuten von "Konto angelegt" zu "W.A.I.S. läuft auf meinem Laptop", ohne
Admin-Rechte am Laptop, ohne Repo und ohne Hilfe von Niko. Am Ende zeigt W.A.I.S. eine Prüfliste, die für jeden Punkt "in Ordnung" oder einen konkreten nächsten
Schritt nennt.

**Erfolgsmaße.** (1) Ein Konto in der Erstanmeldung kommt an keine Funktion des Kerns außer den Wegen der Erstanmeldung (Test über alle Routen, Start und Offer).
(2) Nach dem Wechsel gilt das Startpasswort nicht mehr, ein Wechsel auf dasselbe Passwort wird abgelehnt (V, GoTrue). (3) Ein Startpasswort, das 72 Stunden nicht
gewechselt wurde, öffnet nichts mehr. (4) Nach `freischalten` und `zuruecksetzen` gibt es keine fremde Sitzung und keinen fremden Faktor mehr. (5) Der Installer kommt
nur mit aal2 und erledigter Erstanmeldung; die App installiert ein Update nur mit gültiger Signatur und steigender Version. (6) Ein Mitglied steuert nur den eigenen
Laptop, nur mit der Mitgliederliste und nur wenn es freigeschaltet ist; ein Laborprofil bekommt nie ein PC-Werkzeug, einen Entwicklungsauftrag oder einen Download
(Tests). (7) Zwei Profile sehen nie die Auftragsordner des anderen. (8) Die Prüfliste erkennt "Tunnel steht nicht", "Gerät wartet auf Freigabe", "Host-Umgebung
fehlt" und "kein Modellzugang" und nennt je einen Satz, was zu tun ist.

**Nicht-Ziele.** Selbstregistrierung, Passwort vergessen per Mail, Single Sign-on mit Microsoft, automatische Rollenvergabe, Admin-Rechte für Mitglieder,
Repos in Entwicklungsaufträgen der Mitglieder vor Folgepaket 1 (Bildschirm sehen und Office-Werkzeuge für Mitglieder waren bis zum 16.11.2026 ein Nicht-Ziel;
seitdem gelten sie für den eigenen Laptop, siehe N10 und 4.5),
Einrichtung im NSIS-Installer selbst (der Installer kennt keine Anmeldung; eingerichtet wird beim ersten Anmelden in der App), Änderungen an Laborcode.

## 2. IST und SOLL je Schritt

### 2.1 Schritt 1: Erste Anmeldung

| Befund | Beleg | Kennzeichen |
| --- | --- | --- |
| Konten legt nur der Admin an, die Registrierung ist zu | `scripts/wamo_nutzer.py:1` bis `:20`, `infra/sokrates2/supabase-wamo-einrichten.sh:81` | B |
| `anlegen` setzt bei neuen Konten das Startpasswort, bei vorhandenen bleibt es; jeder Lauf setzt das Profil auf `aktiv = true` | `scripts/wamo_nutzer.py:74` bis `:98` | B |
| `sperren` setzt nur `aktiv = false` (ohne Sperre in GoTrue) und nimmt ohne Angabe das Schema `wamo_dev` | `scripts/wamo_nutzer.py:67` bis `:72`, `:132` | B |
| Ein Profil mit `aktiv = false` sperrt nur den Kern (403); bei GoTrue anmelden und den zweiten Faktor einrichten geht trotzdem | `voice-core/auth_gate.py:383` bis `:390`, `ui/src/components/LoginGate.tsx:122` bis `:166` | B für den Kern, A für GoTrue |
| Folge: Wer ein Startpasswort der sieben gesperrten Konten kennt, kann heute schon den zweiten Faktor binden, bevor die Person es tut | aus den beiden Zeilen davor | A |
| Anmeldung mit E-Mail und Passwort, "Angemeldet bleiben" | `ui/src/components/LoginGate.tsx:226` bis `:245`, `:302` bis `:335` | B |
| Die Oberfläche im Browser liegt auf `https://192.168.178.136:55445` und braucht vorher den Import der WAMO-CA in den Zertifikatsspeicher des Benutzers | `README.md:130`, `:170`, `:194` | B |
| Die installierte App vertraut der CA nur intern, ohne Import; die CA hat eine Namensbeschränkung | `README.md:345` bis `:353` | B |
| Der Anzeigename ist `display_name` (1 bis 60 Zeichen), so spricht W.A.I.S. die Person an | `scripts/wamo_nutzer.py:125`, `:144` bis `:147`, `supabase/migrations/0001_wamo_init.sql:74`, `voice-core/persona.py:93` | B |
| Ob die sieben Konten schon den vollen Namen tragen | nur am Server (`wamo_nutzer.py liste`) | V |

**SOLL.** Niko übergibt ein Willkommensblatt (Adresse, E-Mail, Startpasswort, Fingerabdruck der CA, Prüfsumme des Installers, die Stationen aus Abschnitt 3). Bis
zur Übergabe ist das Konto in GoTrue gesperrt, nicht nur das Profil. `wamo_nutzer.py freischalten` räumt am Übergabetag Sitzungen und Faktoren ab, erzeugt ein neues
Startpasswort mit 72 Stunden Frist, legt den Merker an und hebt die Sperre auf (Reihenfolge in 4.1). Anzeigename ist der volle Name; `umbenennen` ändert ihn, ohne das
Profil zu aktivieren.

### 2.2 Schritt 2: Zweiter Faktor (MFA)

| Befund | Beleg | Kennzeichen |
| --- | --- | --- |
| Ohne bestätigten Faktor legt die Oberfläche einen TOTP-Faktor an (QR-Code und Geheimnis), alte unbestätigte räumt sie vorher ab | `ui/src/components/LoginGate.tsx:138` bis `:166`, `:337` bis `:360` | B |
| Der Kern nimmt nur Tokens mit `aal2` und mit Anmeldezeitpunkt (`amr`) an, und zwar nur lokal geprüft (ohne Abgleich der Sitzung bei GoTrue) | `voice-core/auth_gate.py:281` bis `:319` | B |
| Ändernde Admin-Aktionen verlangen einen frischen Code (höchstens 120 Sekunden alt) | `voice-core/geraete_admin_api.py:13`, `:47`, `:92` bis `:93` | B |
| Sitzungen bleiben bis zur Zeitbox (168 Stunden) oder 72 Stunden Inaktivität erneuerbar | `infra/sokrates2/supabase-wamo/docker-compose.wamo-sitzungen.yml:19` bis `:20` | B |
| Ein verlorenes Handy kann heute nur ein Admin mit Werkzeugen außerhalb von W.A.I.S. lösen | kein Befehl in `scripts/wamo_nutzer.py` | B |

**SOLL.** Ablauf unverändert. Neu: `wamo_nutzer.py zuruecksetzen` (Faktoren und Sitzungen weg, neues Startpasswort, neuer Merker). Ein Hinweis an alle Admins kommt
schon, wenn eine Erstanmeldung beginnt, und noch einmal beim Abschluss, damit eine fremde Einrichtung auffällt.

### 2.3 Schritt 3: Passwort sofort ändern

| Befund | Beleg | Kennzeichen |
| --- | --- | --- |
| Es gibt keinen erzwungenen Wechsel und keinen Merker | `scripts/wamo_nutzer.py:74` bis `:76`, keine Spalte in `supabase/migrations/0001_wamo_init.sql:72` bis `:83` | B |
| Die Oberfläche hat keine Funktion zum Passwortwechsel (`updateUser`, `reauthenticate` kommen in `ui/src` nicht vor) | Suche in `ui/src` | B |
| GoTrue ist eingestellt, beim Passwortwechsel einen Bestätigungscode aus einer erneuten Anmeldung zu verlangen | `infra/sokrates2/supabase-wamo/docker-compose.wamo-sitzungen.yml:12` bis `:21` | B im Repo, V am Server |
| Ob das auch für frische Sitzungen gilt (oder nur für Sitzungen älter als 24 Stunden), ist offen | `infra/sokrates2/labor_tokentest.py:29` bis `:31`, `:1053` bis `:1054` | B (offen), V (Messung) |
| GoTrue schickt diesen Code per Mail; im Repo ist kein Mailweg für den Stack eingerichtet | keine SMTP-Einstellung unter `infra/sokrates2` | V |
| GoTrue prüft die Passwortlänge nur mit seinem Standard (6 Zeichen), das Skript verlangt 12 | `scripts/wamo_nutzer.py:34`, `:111` bis `:117`; Standard von GoTrue | B, V für GoTrue |

**SOLL.** Nach dem zweiten Faktor verlangt W.A.I.S. ein neues Passwort, bevor irgendetwas anderes geht. Durchgesetzt wird das im Kern (Middleware und Routen) und auf
der Ebene des Kontos (Merker, Trigger), nicht in der Oberfläche. Entwurf in 4.1.

### 2.4 Schritt 4: Installationsdatei herunterladen

| Befund | Beleg | Kennzeichen |
| --- | --- | --- |
| Den Installer baut nur ein Mensch lokal, es gibt keinen Workflow dafür | `README.md:306` bis `:316`, `:1592` | B |
| Name `WAIS-Setup-<Version>.exe`, Version 0.2.0, kein Updater (`publish` ist `null`) | `desktop/package.json:3`, `:25`, `:26`; `README.md:369` bis `:375` | B |
| Ausgabe bisher über das GitHub-Release; das Repo wird am Mo 16.11. privat | laut Auftrag | V |
| Installer und `WAMO.exe` sind nicht signiert, SmartScreen warnt; bis dahin soll die Prüfsumme getrennt weitergegeben werden | `README.md:363` bis `:368` | B |
| Die Oberfläche auf Sokrates-2 liefert nur Seiten aus, nimmt nur GET und HEAD und kennt keine Anmeldung | `infra/sokrates2/wamo-ui/wamo-ui.caddy.vorlage:26` bis `:33`, `ui/src/app/version.json/route.ts` | B |
| Der Kern hat geprüfte Routen unter `/wamo/api` mit aal2 und aktivem Profil; Antworten werden gestreamt; Lesen unter `/var/lib` erlaubt | `voice-core/wamo_api.py:7` bis `:14`, `:59` bis `:66`; `infra/sokrates2/wamo-caddy/kern/wamo-core.caddy:10` bis `:26`; `infra/sokrates2/wamo-core@.service:53` | B |
| Die Brücke der Desktop-App meldet Mikrofon und Gerätestatus, aber keine Version | `desktop/preload.js:43` bis `:69` | B |

**SOLL.** Nach Passwort, Token und Schlüssel öffnet sich der Abschnitt "Erste Schritte". Er zeigt Version, Größe und SHA-256 des aktuellen Installers und lädt ihn aus
dem Kern. In der App meldet er Updates, installiert sie aber erst mit Signaturprüfung (4.2).

### 2.5 Schritt 5: Ersteinrichtung durch die Installation

| Befund | Beleg | Kennzeichen |
| --- | --- | --- |
| Installation pro Benutzer ohne Admin-Rechte, App lädt fest die Büro-Oberfläche | `desktop/package.json:104` bis `:121`; `desktop/installation.js:15` bis `:16`, `:62` bis `:66` | B |
| Die Host-Umgebung entsteht beim ersten Start mit `uv` aus `host/uv.lock`, einmalig mit Netz zu PyPI und GitHub | `README.md:336` bis `:344`, `desktop/host-umgebung.js:1` bis `:8` | B |
| Bindung beim Anmelden in der App: eigener Schlüssel, Herausforderung, Signatur, Bindung, dann Dateien und Tunnel | `ui/src/lib/geraet.ts:215` bis `:258`, `voice-core/geraet_api.py:207` bis `:251`, `desktop/geraet.js:500` bis `:592` | B |
| Erstes Gerät eines Mitglieds wird automatisch aktiv; jedes frühere Gerät (auch gesperrt oder widerrufen), Admins und doppelte Rechnernamen warten auf einen Admin; jede Bindung meldet sich bei den Admins | `supabase/migrations/0002_wamo_geraete.sql:13` bis `:16`, `:432` bis `:442`, `:477` bis `:492` | B |
| Geplante Aufgabe "WAMO Tunnel" in der Sitzung der Person, ohne erhöhte Rechte; Abgleich am Server binnen 10 Sekunden | `scripts/wamo-tunnel-einrichten.ps1:164` bis `:170`; `infra/sokrates2/README.md:878`, `:892` bis `:905` | B |
| Tunnelschlüssel gelten nur aus dem Büronetz `192.168.178.0/24` | `infra/sokrates2/wamo_pc_abgleich.py:67`, `:233` | B (über WireGuard: V) |
| Einrichtung läuft nur in der App und nur in der Betriebsart Büro; Rückmeldung ist eine einzelne Zeile; ein Block `einrichtung` gibt es schon in "Geräte und PC" | `ui/src/components/GeraetEinrichtung.tsx:55` bis `:60`, `:121` bis `:131`; `ui/src/lib/geraet.ts:271` bis `:278`; `ui/src/lib/einstellungenAbschnitte.ts:133` | B |
| Mitglieder bekommen PC-Werkzeuge nur mit `WAMO_PC_MITGLIEDER=an`, kernweit (Standard aus); der Name steht nicht in der Erlaubnisliste von `wamo-core-env` | `voice-core/pc_geraet.py:61` bis `:62`, `:194` bis `:196`; `infra/sokrates2/wamo_core_env.py:38` bis `:104` | B |
| **H1:** Der Handler `pc_steuerung` prüft keine Rolle; Freigaben, Bildschirm und Office hängen an `is_admin` | `voice-core/bot.py:1374` bis `:1390`, `:458` bis `:461`, `:795` bis `:831`, `:1126`, `:1403` | B |
| Die Werkzeugliste ist eine einzige Liste, fest im Host-Client; das Nachholen ist nur für Admins; der Prompt nennt PowerShell und Bildschirm für jedes Profil mit PC-Werkzeugen; die Oberfläche zeigt den PC-Block nur Admins | `voice-core/pc_host.py:61` bis `:66`, `:212`, `:225`, `:243`; `voice-core/pc_nachverbinden.py:44` bis `:47`; `voice-core/persona.py:271` bis `:273`, `voice-core/bot.py:691`; `ui/src/lib/einstellungenAbschnitte.ts:157` | B |
| Laborprofile haben die Rolle `mitglied` | `voice-core/test_labor_pc_unveraendert.py:77` | B |
| Entwicklungsaufträge nur für Admins aus `WAMO_ENTWICKLUNG_PROFILE`, im Büro nur mit eigenem Zugang | `voice-core/entwicklung_betrieb.py:165` bis `:199`, `voice-core/bot.py:657`, `:668`, `:707` bis `:715`, `:776`, `:1045`, `voice-core/dev_agent.py:187` bis `:196` | B |
| Der Dispatcher führt höchstens einen Auftrag gleichzeitig aus (gemeinsames Loopback); Projektnamen `kern-<Name>` kennen kein Profil; der Kern-Kanal verlangt `zugang == "folgt"` | `infra/sokrates2/wamo_job_dispatch.py:138`, `:176`; `voice-core/entwicklung_betrieb.py:252` bis `:254`; `infra/sokrates2/wamo_job_kernkanal.py:689` | B |
| Der Kern-Kanal ist am Server offen, nur Art `recherche`, keine Repos | `docs/entwicklung-im-betrieb-arbeitsliste.md:292`, laut Auftrag | B (Plan), V (Server) |
| Gespräch ohne eigenen Schlüssel läuft auf Hausmodellen (LiteLLM, SearXNG); Entwicklungsaufträge ohne Claude-Zugang starten nicht | `voice-core/modellzugang.py:1` bis `:7`, `:186`; `voice-core/bot.py:710` bis `:715` | B |
| Die Auftrags-Sandbox sperrt den Port von LiteLLM (4000); `ANTHROPIC_BASE_URL` steht schon in ihrer Umgebungsliste | `infra/sokrates2/wamo-job.sh:92`, `:209`; `infra/sokrates2/wamo-job-einrichten.sh:253` bis `:254` | B |
| Geführte Eingabe für API-Schlüssel und Claude-Code-Token mit Anleitung gibt es; Lesen und Ändern auch ohne Gespräch | `ui/src/lib/schluesselhilfe.ts:1` bis `:48`, `ui/src/components/ModellZugang.tsx:120` bis `:144`, `:282` bis `:449`; `voice-core/modellzugang_api.py:46` bis `:56` | B |
| Ein Claude-Code-Token hat für Entwicklungsaufträge Vorrang vor dem API-Schlüssel; ohne API-Schlüssel bleibt das Gespräch auf Hausmodellen, auch mit Token; ohne Claude-Zugang gilt "automatisch" wirksam als "nur Hausmodelle" | `voice-core/boss.py:195` bis `:221`, `voice-core/modellzugang.py:160` bis `:186` | B |
| Der Abschnitt "Verbrauch" (Kontingent des Max-Tarifs) ist nur für Admins sichtbar | `ui/src/lib/einstellungenAbschnitte.ts:47` | B |
| Soniox ist Standard für Spracherkennung und Sprachausgabe jedes Profils; die Sitzung wählt die Sprache nur nach `stt` und `tts` des Profils, nicht nach dem Modellzugang | `supabase/migrations/0010_modellzugang.sql:26` bis `:27`, `voice-core/modellzugang.py:153` bis `:154`, `voice-core/bot.py:733` bis `:738`, `voice-core/sprache_anbieter.py:3` bis `:7`, `:45` bis `:53` | B |
| Der Kommentar "Profile ohne Claude-Konto laufen später ganz im Haus" widerspricht D3 | `voice-core/sprache_anbieter.py:6` | B |

**SOLL.** Installer ausführen, App startet, Anmeldung mit Code, dann läuft die Einrichtung wie heute und endet in einer Prüfliste (4.3). Mitglieder bekommen
PC-Steuerung über eine Freischaltung je Profil (4.5) und Entwicklungsaufträge mit eigenem Token, eigenem API-Schlüssel oder, ohne beides, mit Hausmodellen (4.6, 4.7).

### 2.6 Befunde, die den Auftrag ändern

1. **Passwortwechsel heute vermutlich unmöglich** (2.3): Ob GoTrue in frischen Sitzungen einen Code verlangt, entscheidet über den Weg (4.1, P0 misst zuerst).
2. **Gesperrte Profile schützen nicht vor fremder Einrichtung des zweiten Faktors** (2.1): Die Sperre gehört zusätzlich in GoTrue, sofort (N4).
3. **`wamo_nutzer.py anlegen` aktiviert jedes Profil** (2.1): Ein Lauf nur zum Korrigieren des Namens würde ein gesperrtes Konto öffnen. Neuer Befehl `umbenennen`,
   dazu eine Sperre in der Datenbank (Migration 0021).
4. **Der Browser braucht vorher die CA** (2.1): Weg über das Willkommensblatt (Entscheidung N3).
5. **Nach dem Wechsel auf ein privates Repo** fehlt bis Paket P2 ein Downloadweg. Übergang: Ordner der Firma mit Prüfsumme auf Papier (Entscheidung N9).
6. **Ein Auftrag gleichzeitig für alle** (2.5): Entwicklungsaufträge für acht Personen brauchen Trennung, Grenzen je Profil und eine Warteschlange (4.6).
7. **Freeze-Datum widersprüchlich**: `docs/testlabor-wamo.md:34` (E14) nennt So 15.11., der Auftrag Fr 20.11. Beide führen zur selben Empfehlung (Abschnitt 8).

## 3. Nutzerablauf (SOLL)

| Station | Was die Person tut | Was W.A.I.S. tut und prüft |
| --- | --- | --- |
| 0. Willkommensblatt | erhält von Niko persönlich: Adresse, E-Mail, Startpasswort (72 Stunden gültig), Fingerabdruck der CA, Prüfsumme des Installers; importiert die CA mit einem Befehl | Konto war bis zur Übergabe in GoTrue gesperrt; `freischalten` räumt ab und legt Startpasswort, Frist und Merker an |
| 1. Anmelden | öffnet die Adresse im Browser, gibt E-Mail und Startpasswort ein | GoTrue prüft das Passwort (aal1) |
| 2. Zweiter Faktor | scannt den QR-Code mit der Authenticator-App, gibt den Code ein | Faktor bestätigt, Token aal2; Hinweis an die Admins "Erstanmeldung begonnen"; die Oberfläche sagt: "Fragt W.A.I.S. nach einem Code, obwohl du noch keine App eingerichtet hast, melde dich sofort bei Niko." |
| 3. Neues Passwort | gibt ein neues Passwort zweimal ein (mindestens 12 Zeichen) | GoTrue ändert das Passwort (Weg nach 4.1); der Trigger setzt "erledigt"; Hinweis an die Admins |
| 3a. Claude-Code-Token | erzeugt mit `claude setup-token` den Token seines Max-Tarifs und fügt ihn ein, oder "Überspringen" | Kern prüft nur das Format und speichert verschlüsselt (wie heute); der Token gilt nur für Entwicklungsaufträge |
| 3b. API-Schlüssel | legt in der Anthropic-Konsole einen Schlüssel mit Ausgabenlimit an und fügt ihn ein, oder "Überspringen" | Kern prüft mit einer Testanfrage und speichert verschlüsselt (wie heute); danach die Zusammenfassung "So arbeitet W.A.I.S. für dich" (4.7) |
| 4. Installer | klickt "Installer herunterladen", vergleicht die Prüfsumme mit dem Blatt, startet die Datei | Kern liefert die Datei nur mit aal2 und erledigter Erstanmeldung |
| 5. Einrichtung | meldet sich in der App an (Code), spricht optional die Stimme ein | Gerät binden, Host-Umgebung, Tunnel; Prüfliste zeigt jeden Punkt grün oder mit einem nächsten Schritt |

## 4. Entwurf

### 4.1 Erstanmeldung und erzwungener Passwortwechsel

**Merker auf der Ebene des Kontos.** Konten sind für alle drei Schemas dieselben (`auth.users`), die Erstanmeldung gehört also zum Konto, nicht zu einem Schema.
Neues kleines Schema `wamo_auth` mit eigener SQL-Datei, eigenem Rückweg und eigenem SQL-Test unter `infra/sokrates2/supabase-wamo/`, eingerichtet mit
`wamo-auth-einrichten.sh` (nicht über `scripts/render-migration.sh` je Schema; ein Rückweg von `wamo_test` darf es nie abbauen). Tabelle
`wamo_auth.erstanmeldungen`: `user_id` (Schlüssel, `on delete cascade` auf `auth.users`), `start_hash` (SHA-256 des Werts von `encrypted_password` beim
Freischalten, nie der Hash selbst), `angelegt_at`, `frist_bis` (Standard 72 Stunden), `begonnen_at`, `erledigt_at`, `angelegt_durch`. RLS an, keine Rechte für
`anon`, `authenticated`, `service_role`. Schreiben darf nur das Admin-Skript (als `postgres` über `docker exec`, wie heute). `wamo_core` bekommt nur `execute` auf
`wamo_auth.erstanmeldung_stand(uuid)` und `wamo_auth.erstanmeldung_begonnen(uuid)`.

**Wer löscht den Merker: niemand, er erledigt sich.** Ein Trigger `AFTER UPDATE OF encrypted_password ON auth.users` (nur wenn sich der Wert wirklich ändert) setzt
`erledigt_at`, wenn ein offener Merker besteht und die Frist nicht überschritten ist, und schickt einen Hinweis an alle Admins. Der Trigger fängt jeden eigenen Fehler
ab und schreibt dann nur ins Log; er darf GoTrue nie blockieren. Damit gibt es keine Schreibwirkung in einer Lesefunktion und keinen Wettlauf zwischen Frist und
Prüfung. `erstanmeldung_stand` liefert nur noch `keine`, `offen`, `abgelaufen` oder `erledigt`. Ist die Frist vorbei, bevor "erledigt" gesetzt wurde, bleibt der
Zustand `abgelaufen`, auch wenn sich der Passwort-Hash später ändert. Nur GoTrue (mit gültiger Sitzung) oder das Admin-Skript ändern den Hash; der Kern kann den
Zustand weder setzen noch zurücksetzen. Fällt P0 gegen den Trigger aus (etwa weil GoTrue `auth.users` bei Updates umbaut), gilt der Ersatz: Vergleich des Hashes mit
`start_hash` beim Lesen, mit 15 Minuten Kulanz nach der Frist (V).

**Kein Profil ohne Merker aktivieren.** Migration 0021 (je Schema, mit `.down.sql` und Test) legt einen Trigger auf `<schema>.profiles`: Ein Wechsel von `aktiv`
von `false` auf `true` für ein Profil ohne `labor_art` braucht einen Merker in `wamo_auth.erstanmeldungen` (gleich welcher Zustand). So öffnet eine alte Kopie von
`anlegen` keines der sieben Konten. Bestehende aktive Profile (Niko) sind nicht betroffen, Laborprofile auch nicht.

**Durchsetzung im Kern.** Der Stand reist in der Entscheidung der Zugangskontrolle mit (`Decision`, `voice-core/auth_gate.py:182` bis `:187`), Cache wie das Profil,
bei `offen` 10 Sekunden. Für Laborprofile ruft der Kern die Funktion nie auf (eine fehlende Funktion darf das Labor nie auf 503 setzen). Zwei Stellen setzen die
Sperre durch:

- `AccessMiddleware` (`voice-core/auth_gate.py:523` bis `:560`) prüft bei `offen` eine feste Pfadliste mit `raw_path` nach dem Muster `_labor_urteil` (`:504` bis
  `:521`, `voice-core/labor.py:151`): `GET /wamo/api/erstanmeldung`, `POST /wamo/api/erstanmeldung/code` (nur Zweig B), `GET` und `POST /wamo/api/modellzugang`
  erst nach "erledigt". Alles andere 403 mit Code `passwort_wechsel_noetig`. Kein Start, kein Offer, keine Gerätebindung, kein Download.
- `identitaet()` (`voice-core/wamo_api.py:59` bis `:66`) lehnt `offen` und `abgelaufen` ab, außer eine Route ruft `identitaet(request, erstanmeldung=True)` auf
  (nur die Routen der Erstanmeldung). So fängt auch jeder spätere Aufrufer von `authorize` ohne Pfad (etwa `voice-core/bild_fern.py`) die Sperre.

Bei `abgelaufen` gibt es 403 mit Code `startpasswort_abgelaufen` und dem Satz "Dein Startpasswort ist abgelaufen. Bitte melde dich bei Niko." Fehlt die Funktion für
ein Nicht-Laborprofil (falsche Reihenfolge beim Ausrollen), antwortet der Kern mit 503 (fail closed) und schreibt eine Zeile ins Journal. `SessionGuard`
(`voice-core/bot.py:516`) prüft jede Minute auch den Merker und beendet eine Sitzung, deren Konto zurückgesetzt wurde. Alte Access-Tokens gelten am Kern bis zu ihrem
Ablauf (`JWT_EXPIRY`, V), helfen aber nicht: Mit Stand `offen` kommen sie nur an die Wege der Erstanmeldung, und dort braucht es einen frischen Faktor, den
`zuruecksetzen` gelöscht hat.

**Weg für den Passwortwechsel (P0 entscheidet).**

- **Zweig A, GoTrue nimmt den Wechsel in frischen Sitzungen ohne Code an:** Die Oberfläche ruft nach aal2 `supabase.auth.updateUser({ password })`. Kein Hook, keine
  Route `/code`. Eigener Befund für das Labor: Dann schützt die Einstellung die Laborplätze nicht, weil Laborsitzungen frisch sind; das geht vor dem Labortag an Niko.
- **Zweig B, GoTrue verlangt den Code (Variante V2, empfohlen):** GoTrue bekommt einen Hook für den Mailversand, der keine Mail schickt, sondern eine Funktion in
  `wamo_auth` aufruft (Send-Email-Hook über `pg-functions`, V für v2.196.0). Die Funktion speichert nur Codes der Art `reauthentication` in
  `wamo_auth.bestaetigungscodes`, verwirft jede andere Art (Registrierung, Einladung, Wiederherstellung) und räumt abgelaufene Codes ab. Der Code lebt in GoTrue nur
  so lange wie `GOTRUE_MAILER_OTP_EXP=300` (Name V). Der Kern holt ihn über `wamo_auth.erstanmeldung_code(uuid)` (SECURITY DEFINER), die ihn nur bei Stand `offen`
  liefert und dabei löscht (genau einmal). Ablauf: (1) Ist der Code des zweiten Faktors älter als 120 Sekunden (`aal2Frisch`, `ui/src/lib/anmeldung.ts:56` bis
  `:85`), fragt die Oberfläche ihn erneut ab. (2) `supabase.auth.reauthenticate()`: GoTrue erzeugt den Code, der Hook legt ihn ab. (3) `POST
  /wamo/api/erstanmeldung/code`: Kern prüft aal2, frischen Code (`voice-core/geraete_admin_api.py:92`), Stand `offen`, Ratengrenze (5 je 10 Minuten), kein
  Laborprofil; Antwort mit `Cache-Control: no-store`, der Code steht nie im Log. (4) `supabase.auth.updateUser({ password, nonce })`. Das Passwort geht nur vom
  Browser an GoTrue, nie durch den Kern.

Nach dem Wechsel meldet die Oberfläche alle anderen Sitzungen ab (`signOut({ scope: "others" })`), fragt `GET /wamo/api/erstanmeldung` erneut (der Kern leert dabei
seinen Cache für das Profil) und geht zu Station 3a.

**Varianten für Zweig B.**

| Variante | Weg | Für | Gegen |
| --- | --- | --- | --- |
| V1 | GoTrue schickt den Code per Mail (SMTP der Firma) | Standardweg von GoTrue, zweiter Kanal Postfach | braucht SMTP-Zugang und Ausgang am Server, Abhängigkeit von Microsoft 365, Mails der Wiederherstellung werden möglich |
| **V2** | Hook in `wamo_auth`, Kern gibt den Code nach frischem TOTP nur in der Erstanmeldung heraus | kein Service-Schlüssel, kein Mailweg, GoTrue ändert selbst, Wirkung nur auf Konten im Stand `offen` | Hook-Unterstützung in v2.196.0 erst zu belegen (P0), Hook gilt für den ganzen Auth-Dienst |
| V3 | eigener kleiner Dienst mit Service-Schlüssel (Muster Freigabe-Dienst) setzt das Passwort über die Admin-Schnittstelle | unabhängig von Hooks, eigene Passwortregeln | neuer Halter des Service-Schlüssels mit Macht über alle Konten, Passwort läuft durch einen weiteren Dienst |

**Reihenfolge MFA vor Passwort.** Wie von Niko gewünscht und richtig: (1) In Zweig B kommt der Code nur mit aal2 und frischem Faktor heraus; in beiden Zweigen
geschieht der Wechsel in einer Sitzung, die den Besitz des Authenticators belegt. (2) Ohne aal2 kommt nichts am Kern an (B). (3) Wer nur das Startpasswort hat,
ändert damit nichts. Restrisiko (beide Reihenfolgen gleich): Wer das Startpasswort vor der Person nutzt, bindet seinen eigenen Faktor. Dagegen helfen Sperre in
GoTrue bis zur Übergabe, die Reihenfolge in `freischalten`, Übergabe nur persönlich, 72 Stunden Frist und die zwei Hinweise an die Admins.

**Passwortregeln am Server.** `GOTRUE_PASSWORD_MIN_LENGTH=12` in derselben Ergänzungsdatei wie die Sitzungsgrenzen
(`infra/sokrates2/supabase-wamo/docker-compose.wamo-sitzungen.yml`). Keine Prüfung gegen Leak-Listen (Sokrates-2 ruft dafür keinen fremden Dienst auf).

**Admin-Skript.** `scripts/wamo_nutzer.py` (der Service-Schlüssel bleibt auf Sokrates-2, `scripts/wamo_nutzer.py:1` bis `:9`). Feste Reihenfolge in `freischalten`,
`zuruecksetzen` und `passwort` (Option Ü): (1) Konto in GoTrue sperren, (2) alle Sitzungen und Refresh-Tokens des Kontos löschen, (3) Faktoren löschen (bei
vorhandenen Faktoren in `freischalten` ohne `--faktoren-loeschen` abbrechen und melden: das ist ein Zeichen für fremde Einrichtung), (4) Passwort setzen, (5) erst dann
`start_hash` lesen und den Merker schreiben, (6) Profil aktiv, Sperre aufheben. Dazu `umbenennen` (nur `display_name`), `sperren` mit Sperre in GoTrue und Pflicht
`--schema`, `austreten` (Gerät widerrufen, Token und Schlüssel löschen, Konto in GoTrue sperren), `anlegen` legt künftig gesperrt und inaktiv an, `liste` zeigt den
Stand der Erstanmeldung. Ob die Admin-Schnittstelle von GoTrue Sitzungen beim Passwortwechsel selbst beendet, misst P0 (V); das Skript verlässt sich nicht darauf.

### 4.2 Installer vom Server

**Ablage.** `/var/lib/wamo-verteilung/` (root:wamo-core 0750, Dateien 0640): `WAIS-Setup-<Version>.exe`, `aktuell.json` (Version, Dateiname, Größe, SHA-256,
Bauzeit, Commit) und `aktuell.json.sig` (Ed25519-Signatur). Die vorige Fassung bleibt liegen (Rückweg). Der Kern liest nur (`ProtectSystem=strict` lässt Lesen
unter `/var/lib` zu). Einsetzen: lokal `scripts/wamo_installer_sokrates2.py verteilen <exe>` (prüft Name, Größe, SHA-256, Signatur und
`scripts/wamo-dist-pruefen.cjs`, kopiert per `scp`), am Server `wamo-verteilung-einrichten.sh einsetzen|status|rueckweg` (prüft SHA-256 und Signatur erneut,
verlangt eine steigende Version, schreibt das Manifest atomar, nur root).

**Kern.** Neues Modul `voice-core/verteilung_api.py` in `ROUTEN_MODULE` (`voice-core/wamo_api.py:35`):

- `GET /wamo/api/installer` liefert das Manifest mit Signatur (ohne Pfade).
- `GET /wamo/api/installer/datei` liefert genau die Datei aus dem Manifest über `FileResponse` mit Range (kein Name vom Client, Pfad fest),
  `Content-Disposition: attachment` mit festem Namen, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, höchstens 3 Abrufe je Stunde und Profil (Richtwert
  je Prozess, zwei Slots), Eintrag in `actions` (Werkzeug `installer_download`, ohne Inhalt). Nur Büro-Kern, nie für Laborprofile. P2 misst, ob 117 MB während eines
  laufenden Gesprächs Aussetzer erzeugen; wenn ja, Ersatz durch Caddy `file_server` mit `forward_auth` auf den Kern (braucht eine Änderung am gemeinsamen
  Caddy-Container, deshalb nur bei Bedarf).

Beide Routen liegen hinter der Zugangskontrolle, also nur mit aal2, aktivem Profil und erledigter Erstanmeldung.

**Oberfläche.** Neuer Abschnitt "Erste Schritte" (Kennung `start`, neben `konto`, `ui/src/lib/einstellungenAbschnitte.ts:45`; nicht `einrichtung`, das gibt es
als Block in "Geräte und PC"), nach der Erstanmeldung automatisch offen. Der Download läuft mit dem Token über `fetch` (der Browser schickt bei einem Link keinen
Bearer mit; eine Ausnahme in der Zugangskontrolle für Einmal-Links ist bewusst nicht geplant), mit Fortschritt, als Datei über eine Blob-Adresse (etwa 117 MB im
Speicher, V: in Chrome, Edge und Electron zu messen, P0). Daneben stehen Version, Größe und SHA-256 zum Kopieren und der Befehl
`Get-FileHash .\WAIS-Setup-<Version>.exe` mit dem Satz "Vergleiche die Zeichen mit deinem Willkommensblatt".

**Versionsabgleich und Updates.** Die Brücke der App meldet ihre Version (`window.wamoDesktop.version`, aus `app.getVersion()`, neu in `desktop/preload.js`). Fehlt
sie (App 0.2.0), zeigt die Oberfläche "Update empfohlen". Ein Update aus der App gibt es erst zusammen mit der Prüfung in der App (P3): Laden im Hauptprozess über
dieselbe geprüfte Verbindung wie heute (`pruefeSocket`, `desktop/zertifikat.js`), SHA-256 und Ed25519-Signatur des Manifests gegen einen in der App festen
öffentlichen Schlüssel, Version muss steigen, Rückfrage, dann Start des Installers (Weg über die feste GUID, `README.md:369` bis `:373`). Ohne gültige Signatur zeigt
die App nur "Update vom Server nicht bestätigt, bitte Niko fragen" und lädt nichts.

**Vertrauen.** Liefert der Server Datei und Prüfsumme, belegt die Prüfsumme nur eine heile Übertragung. Unabhängig davon sind: die Prüfsumme auf dem Willkommensblatt,
die Signatur des Manifests mit einem Schlüssel, der nur auf einem Hardware-Token liegt (nie als Datei auf einem Laptop, den W.A.I.S. steuert; der Bau-Laptop signiert
nur, solange das Token steckt), und eine Codesignatur des Installers (Entscheidung N8).

### 4.3 Ersteinrichtung durch die Installation und Abschlussprüfung

Die Installation selbst bleibt schlicht (pro Benutzer, ohne Netz, ohne Anmeldung). Eingerichtet wird beim ersten Anmelden in der App, wie heute (B, 2.5). Neu ist
die Prüfliste im Abschnitt "Erste Schritte", gespeist aus der App (lokal) und dem Kern (`GET /wamo/api/einrichtung/stand`, neues Modul
`voice-core/einrichtung_api.py`). Die Zeilen zu Gerät und Tunnel nutzen die vorhandenen Texte (`geraeteStandText`, `GeraetEinrichtung.tsx`) wieder.

| Punkt | Quelle | Grün, wenn | Satz bei Rot |
| --- | --- | --- | --- |
| Anmeldung | Token | aal2 | (kommt nicht vor, sonst keine Seite) |
| Passwort gewechselt | Kern, `erstanmeldung_stand` | `erledigt` oder `keine` | "Bitte zuerst dein Passwort ändern." |
| App-Version | Brücke und Manifest | gleich oder neuer | "Update auf Version x.y.z verfügbar." oder "Update empfohlen." |
| Gerät gebunden | Kern (Register) und App | aktives Gerät dieses Profils | "Dein Laptop wartet auf die Freigabe durch einen Admin." |
| Host-Umgebung | App (`host-umgebung.js`) | bereit | "Die Python-Umgebung fehlt. Netz zu PyPI und GitHub nötig, die App versucht es beim nächsten Start erneut." |
| Tunnel | App (`tunnel.status`) und Kern | App meldet verbunden und der Kern findet Ordner, Dateien und Fingerabdruck des eigenen Geräts und erreicht den Socket mit passender Gegenstelle (`SO_PEERCRED`) | "Der Tunnel steht nicht. Bist du im Büronetz?" |
| Mikrofon | Brücke `mikrofonStatus` | erlaubt | "Windows blockiert das Mikrofon für W.A.I.S." |
| Stimme (Soniox) | Kern | Server-Schlüssel gesetzt und Profil auf `soniox` | "Die Stimme ist am Server nicht eingerichtet." |
| Gespräch | Kern (Modellzugang) | eigener API-Schlüssel oder Hausmodelle | "Ohne eigenen Schlüssel spricht W.A.I.S. mit den Hausmodellen." (Hinweis, nicht Rot) |
| Entwicklungsaufträge | Kern (`rechte.py`) | freigeschaltet und Token, Schlüssel oder Hausmodelle verfügbar | der Grund in einem Satz, auch für Mitglieder (heute sehen nur Admins den Grund, `voice-core/bot.py:1045`) |
| Stimmabdruck | Kern | eingelernt | "Ohne Stimmabdruck nimmt W.A.I.S. PC-Befehle nur getippt an." (Hinweis, ab P4, nach N10) |
| PC-Steuerung | Kern (`rechte.py`) | für dieses Profil freigeschaltet und Gerät erreichbar | "PC-Steuerung ist für dein Profil noch nicht freigeschaltet." |

Die Prüfung des Tunnels trennt Lesen von Recht: Sie liest Gerät und Ordner wie `pc_zugang_fuer` (`voice-core/pc_geraet.py:120` bis `:161`), aber ohne dessen
Rechteprüfung, startet kein MCP und ruft kein Werkzeug auf (keine PC-Sperre, keine Aufrufgrenze verbraucht), gibt der Sitzung keinen Zugang und gilt nur für das
eigene Gerät. Ein Knopf "Erneut prüfen" ist auf einmal je 10 Sekunden gedrosselt.

Am gebauten Installer prüft REA bei jeder neuen Version: `inspect_electron_fuses` (die Fuses aus `desktop/package.json:83` bis `:91` wirken),
`analyze_javascript_application` auf `app.asar` (nur die bekannten Kanäle der Brücke, neu genau `version` und `update`), `compare_application_versions` gegen 0.2.0
(nur die geplanten Änderungen), dazu `scripts/wamo-dist-pruefen.cjs`.

### 4.4 Freigabe neuer Geräte

| Fall | Heute | Empfehlung |
| --- | --- | --- |
| Erstes Gerät eines Mitglieds, neuer Schlüssel, freier Rechnername | automatisch aktiv, Hinweis an Admins (B) | **so lassen.** Die Erstanmeldung muss erledigt sein; das erzwingt 4.1, weil die Bindung hinter der Zugangskontrolle liegt |
| Gerätewechsel, zweites Gerät, doppelter Rechnername, jedes Profil mit früherem Gerät | Admin entscheidet (B) | so lassen, Karte in der Geräteverwaltung (`voice-core/geraete_admin_api.py:227`, `:244`) |
| Admin-Profil | Admin entscheidet (B) | so lassen |

Begründung: Ein Angreifer mit Passwort und Faktor einer Person gewinnt mit einem eigenen ersten Gerät nur die Steuerung dieses eigenen Geräts und einen sehr engen
Tunnelplatz; die Person merkt es, weil ihr Laptop dann auf einen Admin wartet, und Niko sieht jeden Fall als Hinweis. Weil jedes frühere Gerät, auch ein gesperrtes,
zur Freigabe durch einen Admin führt (`supabase/migrations/0002_wamo_geraete.sql:435`), ist das Sperren eines Geräts ein echter Notaus ohne erneute automatische
Bindung. Eine Pflichtfreigabe für jedes Gerät kostet Niko sieben Klicks und verzögert jeden Start ohne nennenswerten Gewinn.

### 4.5 PC-Steuerung für Mitglieder (Lösung für H1)

- **Ein Modul für Rechte:** `voice-core/rechte.py` mit `pc_stufe(identity) -> "admin" | "mitglied" | None` und `entwicklung_erlaubt(identity)`. `None` für jedes
  Laborprofil (ausdrücklich, denn Laborprofile haben die Rolle `mitglied`), für Mitglieder ohne Freischaltung und für unbekannte Rollen.
- **Freischaltung je Profil:** `WAMO_PC_MITGLIEDER_PROFILE` (Liste von `user_id`, neu in der Erlaubnisliste von `wamo-core-env`,
  `infra/sokrates2/wamo_core_env.py:38`) ersetzt den kernweiten Schalter `WAMO_PC_MITGLIEDER`. So geht ein Pilot mit einer Person.
- **Alle Stellen fragen `pc_stufe`:** `pc_zugang_fuer` (`voice-core/pc_geraet.py:194`), `nachholen_moeglich` (`voice-core/pc_nachverbinden.py:46`), der Handler
  `pc_steuerung` (`voice-core/bot.py:1385`, neu mit Stufenprüfung), `darf_pc_freigeben` (`:458` bis `:461`), Freigabekarten und Klick (`:1126`, `:1403`), der
  Host-Client (`host_client` bekommt die Stufe und filtert mit ihr, `voice-core/pc_host.py:212`, `:225`, `:243`, auch beim Nachholen `voice-core/bot.py:1310`), der
  Prompt (`build_system_prompt` bekommt die Stufe und einen eigenen Textblock für Mitglieder, statt `voice-core/persona.py:271` bis `:273` mit PowerShell und
  Bildschirm) und die Oberfläche (PC-Block und Schalter für freigeschaltete Mitglieder, `ui/src/lib/einstellungenAbschnitte.ts:157`, `ui/src/lib/usePcSchalter.ts`).
- **Werkzeugliste (geändert am 16.11.2026, N10):** Freigeschaltete Mitglieder bekommen für ihren eigenen Laptop dieselben PC-Werkzeuge wie Admins:
  `pc_host.werkzeuge_fuer` gibt beiden Stufen `LLM_TOOLS` (also auch `powershell_lesen`, `git_klonen`, `github_repo_anlegen`), dazu Bildschirm sehen und klicken
  (`screen.py`), Live-Bild (`bildstrom.py`, Fernanfrage `bild_fern.py`) und Office (`office_werkzeuge.py`, `outlook_werkzeuge.py`, `teams_werkzeuge.py`,
  `onenote_werkzeuge.py`), jeweils nur mit dem Schalter am Server (`WAMO_OFFICE` usw.). Die eigene Liste `LLM_TOOLS_MITGLIED` und der eigene Prompt
  `PC_MITGLIED_PROMPT` entfallen; Mitglieder bekommen den PC-Block der Admins und den Zusatz `PC_MITGLIED_ZUSATZ` (eigener Laptop, Stimmabdruck, Karte nach
  Fremdinhalt). Wer Office und Live-Bild bekommt, entscheidet überall `rechte.pc_stufe` (`office_werkzeuge.pc_person`), nie die Rolle allein. Unverändert:
  nur das eigene, gebundene Gerät, Freischaltung je Person, Laborprofile nie, Admin-Rechte am Server (Geräte freigeben, Gedächtnis, Konten) nur für Admins.
- **Schutz der Mitglieder für alle PC-Werkzeuge (16.11.2026):** `pc_mitglied.MitgliedSchutz` gilt jetzt auch für die Werkzeuge, die der Kern selbst ausführt
  (`KERN_WERKZEUGE`: `bildschirm_ansehen`, `auf_bildschirm_klicken`, `canvas_exportieren`, `outlook_senden`, `teams_nachricht`, `onenote_seite`), über
  `kern_werkzeuge_absichern` nach dem Gate der Stimmprüfung. Einteilung: lesend ohne Karte (`LESEN_MITGLIED`, dazu `powershell_lesen`, das der Host nur als
  reines Lesen ausführt und sonst selbst als Karte vorlegt, und `bildschirm_ansehen`), mit eigener Karte bei jedem Aufruf (`EIGENE_KARTE`: `github_repo_anlegen`
  ist beim Host critical, Mail, Teams und OneNote legen ihre Karte immer an), alles andere ändernd (`AENDERN_MITGLIED`, auch `git_klonen`,
  `auf_bildschirm_klicken`, `canvas_exportieren`): nach Fremdinhalt Karte des Kerns. Ein Klick auf den Bildschirm und eine Office-Datei laufen nach dem Ja
  über ihren Ausführer (`PcFreigaben`, `kern_ausfuehrer`); das Bildmodell sucht das Ziel erst dann auf einem frischen Foto. Der Auftrag an den Boss mit der
  Art `bild` fragt vor dem Foto denselben Schutz. In `actions` steht bei Mitgliedern auch für Office-Dateien kein Dateiname (`knapp`).
- **Live-Bild am Laptop eines Mitglieds (16.11.2026):** Host (`host/live_bild.py`) und Desktop-App (`desktop/livebild.js`) lassen das Live-Bild auch bei der
  Stufe `mitglied` in `geraet.json` zu; Einwilligung, Schalter am Laptop, roter Rahmen, Herzschlag, ein Zuschauer und die Fernanfrage nur mit frischem Code
  bleiben wie bei Admins. Ob jemand zusehen darf, entscheidet der Kern (Freischaltung je Person). Ein Host vor 0.4.0 meldet bei Mitgliedern weiter `stufe`;
  dann sagt der Kern, dass der Laptop dafür die neue Version braucht.
- **Prompt-Injection (S15):** Mitglieder behalten Lesewerkzeuge (`browser_lesen`, `element_lesen`) und ändernde Werkzeuge (`webseite_oeffnen`, `tastatur_tippen`),
  deren Klasse `change` heute ohne Karte läuft (`host/wamo_host.py:9` bis `:23`). Für Mitglieder verlangt der Kern deshalb nach Fremdinhalt im selben Zug
  (`turn.tainted`) auch für `change` eine Karte; die Lesewerkzeuge kommen erst mit diesem Schutz dazu. Eval-Fälle in `voice-core/eval/faelle.py`.
- **Freigaben:** Kritische Aktionen am eigenen Laptop gibt das Mitglied selbst frei (Karte in der eigenen Sitzung, zweites Geheimnis des Hosts wie heute), nie ein
  Admin für fremde Laptops.
- **Stimme:** Für Mitglieder nehmen PC-Werkzeuge Sprache nur mit eingelerntem Stimmabdruck an, sonst nur getippten Text, und zwar unabhängig vom Modus
  `WAMO_STIMME_PRUEFUNG`. Das weicht von der heutigen Zusage "Einwilligung freiwillig, Fehlen ohne Nachteil" ab (`voice-core/stimme_gate.py:14` bis `:17`): Ohne
  Abdruck gibt es keine gesprochene PC-Steuerung. Niko entscheidet das ausdrücklich (N10); der Abdruck wird dann ein Schritt der Prüfliste.
- **Notaus je Person:** Gerät in der Geräteverwaltung sperren; die Wache beendet die Steuerung binnen 60 Sekunden (`voice-core/pc_geraet.py:235` bis `:264`).

### 4.6 Entwicklungsaufträge für Mitglieder

- Neuer Schalter `WAMO_ENTWICKLUNG_MITGLIEDER` (an oder aus, Standard aus) im Drop-in `wamo-entwicklung-buero.conf`, geschrieben nur von
  `wamo-job-kern-einrichten.sh schalter --mitglieder an|aus`. `SCHRANKEN_VERSION` steigt auf 2; `schalter --mitglieder an` verlangt mindestens 2 im Zielrelease (heute
  nimmt das Skript jede Zahl; die Tests nageln 1 fest, `voice-core/test_entwicklung_betrieb.py:44`, `voice-core/test_kernkanal_vertrag.py:303`).
- `rechte.entwicklung_erlaubt` ersetzt die Admin-Prüfungen in `zulassung_erteilen` und `grund_vorab` (`voice-core/entwicklung_betrieb.py:165` bis `:199`) und in
  `voice-core/bot.py:657`, `:668`, `:776`: Mitglieder nur mit Schalter und mit ihrer `user_id` in `WAMO_ENTWICKLUNG_PROFILE`. Laborprofile nie (`voice-core/bot.py:671`
  bis `:672` bleibt).
- **Trennung je Profil:** Die Kurzkennung des Profils (8 Hexzeichen, `BueroZulassung.kennung`) wird Teil des Projektnamens (`kern-<kennung>-<Name>`) und steht in
  `auftrag.json`; der Dispatcher behandelt den Ordner eines anderen Profils als Konflikt `projekt`. Grenzen je Profil im Kanal (Versuche je Stunde je Profil statt nur
  gesamt, `infra/sokrates2/wamo_job_kernkanal.py:76`). Weil `PARALLEL_MAX = 1` bleibt (gemeinsames Loopback), meldet der Kern "Ein anderer Auftrag läuft, deiner
  startet danach" und stellt den Start in eine kleine Warteschlange je Profil (höchstens ein wartender Auftrag je Person). Vertragstest beider Seiten erweitern.
- Zugang: eigener Token vor eigenem API-Schlüssel (wie heute im Büro, `voice-core/dev_agent.py:187` bis `:196`), ohne beides die Hausmodelle (4.7). Kostengrenzen je
  Auftrag und je Tag und Profil gelten unverändert (`voice-core/entwicklung_betrieb.py:96` bis `:103`). Arten nach dem Kern-Kanal (heute `recherche`); Repos für
  Mitglieder erst mit Folgepaket 1 und einer Liste je Profil (Entscheidung N6).
- Vorbedingung vor dem Onboarding aller sieben: das Ergebnis des Labor-Lasttests mit 8 parallelen Sitzungen (Stimmmodell, Hausmodelle), weil die Kollegen danach
  dieselben Dienste nutzen.

### 4.7 Modellzugang je Person und Rückfall auf Hausmodelle (nach D2)

**Geführter Ablauf.** Nach Faktor und Passwortwechsel (Station 3) fragt die Oberfläche in zwei Schritten, beide mit "Überspringen":

1. **Claude-Code-Token** (`sk-ant-oat…` aus `claude setup-token`, Max-Tarif). Text: "Hast du ein Claude-Code-Konto (Max-Tarif)? Dann laufen deine
   Entwicklungsaufträge darüber." Die Anleitung `TOKEN_ANLEITUNG` (`ui/src/lib/schluesselhilfe.ts:37` bis `:48`) nennt, dass Claude Code dafür auf dem eigenen Laptop
   installiert und angemeldet sein muss (die Person führt den offiziellen Installationsbefehl selbst aus; W.A.I.S. installiert nichts dafür). Gespeichert wird über
   `POST /wamo/api/modellzugang` wie heute (nur Formatprüfung, verschlüsselt, `voice-core/modellzugang.py:9` bis `:22`).
2. **API-Schlüssel** (`sk-ant-api…`, Guthaben in der Anthropic-Konsole). Text: "Hast du einen API-Schlüssel? Dann führst du Gespräche mit Claude Haiku; ohne Token
   laufen auch deine Entwicklungsaufträge darüber." Anleitung `API_ANLEITUNG` (`ui/src/lib/schluesselhilfe.ts:24` bis `:35`), Prüfung mit einer Testanfrage wie
   heute (höchstens 5 je 10 Minuten).

Die Bausteine dafür gibt es in `ui/src/components/ModellZugang.tsx` (Feld, Anleitung, Erkennung des falschen Felds über `falschesFeld`); der Ablauf verwendet sie
wieder. Danach zeigt eine Zusammenfassung "So arbeitet W.A.I.S. für dich" eine der vier Zeilen unten. Der Modus bleibt `automatisch`; Niko muss nichts einstellen.

**Die vier Fälle.**

| Hinterlegt | Gespräch, Lernen, Websuche, Bildschirm | Entwicklungsaufträge | Stimme | Beleg |
| --- | --- | --- | --- | --- |
| Token und API-Schlüssel | Claude Haiku über den eigenen Schlüssel | Claude Code mit dem Token (Max-Tarif, Standardmodell Sonnet); der Token hat Vorrang | Soniox | `voice-core/boss.py:215` bis `:216`, `infra/sokrates2/wamo_job_dispatch.py:49`, `:467` bis `:471` |
| **nur Token (Mischfall)** | **Hausmodelle** (LiteLLM, Suche über SearXNG); ein Max-Tarif deckt die Messages-API des Gesprächs nicht ab | **Claude Code mit dem Token** (Max-Tarif, Sonnet) | Soniox | `voice-core/modellzugang.py:11` bis `:14`, `:186`; `voice-core/boss.py:210` bis `:216` |
| nur API-Schlüssel | Claude Haiku über den eigenen Schlüssel | Claude Code mit dem API-Schlüssel (Guthaben, Standardmodell Haiku) | Soniox | `voice-core/boss.py:217` bis `:218` |
| nichts | Hausmodelle; `automatisch` gilt wirksam als `nur_haus` | heute keine; ab P6 Claude Code mit Hausmodell über `ANTHROPIC_BASE_URL` auf LiteLLM | Soniox | `voice-core/boss.py:195` bis `:198`, `:207` bis `:209`, `:221` |

Der fünfte Fall (Quelle `zuordnung`, Schlüssel des Kerns, Übergang) gilt nur für das Profil von Niko und bleibt unverändert (`voice-core/modellzugang.py:181` bis
`:185`).

**Mischfall "nur Token" ausdrücklich.** Das Profil hat keinen API-Schlüssel, also baut `zugang_laden` einen Hauszugang mit Quelle `keiner` und dem Merkmal
`claude_code` (`voice-core/modellzugang.py:160`, `:186`). Gespräch, Zusammenfassung, Lernen und Boss laufen damit über LiteLLM; kein Aufruf geht mit dem Token an
die Messages-API (der Token wird nur über `claude_code_zugang_fuer` je Lauf an den Dispatcher gegeben, `voice-core/dev_agent.py:18` bis `:24`, `:199` bis `:218`).
`entwicklung_quelle` liefert `token` (`voice-core/boss.py:215` bis `:216`), der Dispatcher setzt `CLAUDE_CODE_OAUTH_TOKEN` in der Sandbox und wählt Sonnet
(`infra/sokrates2/wamo_job_dispatch.py:177` bis `:179`, `:467` bis `:471`). Kosten: keine Rechnung je Aufruf, aber Verbrauch des Abo-Kontingents; der Kern speichert
es je Profil (`voice-core/dev_agent.py:22` bis `:24`). Weil der Abschnitt "Verbrauch" heute nur Admins zeigt (B), öffnet P5 ihn für jedes Profil mit Token. Grenze des
Falls: Wählt die Person selbst "Nur Hausmodelle", läuft heute gar kein Claude Code (`voice-core/boss.py:210` bis `:214`); ab P6 laufen ihre Aufträge dann mit dem
Hausmodell.

**Stimme.** Soniox für alle (D3). Die Sitzung baut Spracherkennung und Sprachausgabe nur nach `stt` und `tts` des Profils, beide stehen auf `soniox` (B, 2.5), auch
bei Hausprofilen. `boss.sprachmodelle` beschränkt bei Hausprofilen nur die Modellkarte des Boss, nicht die Pipeline (`voice-core/boss.py:224` bis `:239`, A). P2 passt
den widersprechenden Kommentar in `voice-core/sprache_anbieter.py:6` an.

**Später ändern in den Einstellungen.** Abschnitt "Modellzugang" (`ui/src/lib/einstellungenAbschnitte.ts:46`, `ui/src/components/ModellZugang.tsx:282` bis `:449`):

- Token oder API-Schlüssel nachtragen, ersetzen oder löschen (Löschen mit Rückfrage). Angezeigt wird nur "hinterlegt, endet auf …abcd", nie der Wert.
- Umschalter "Automatisch" oder "Nur Hausmodelle". "Nur Hausmodelle" schickt nichts mehr an Anthropic, auch keinen Entwicklungsauftrag mit Token.
- Jede Änderung gilt ab der nächsten Sitzung (`voice-core/modellzugang.py:22`); die Prüfliste (4.3) zeigt den neuen Stand sofort.
- Ein Admin kann ein Profil auf Hausmodelle festlegen; dann sind eigene Schlüssel gesperrt (`voice-core/modellzugang.py:155` bis `:156`, `ModellZugang.tsx:423`).

**Entwicklungsaufträge mit Hausmodellen.** `wamo-job.sh` lässt `ANTHROPIC_BASE_URL` in der Umgebung der Sandbox zu (`infra/sokrates2/wamo-job.sh:209`), das Netz der
Sandbox sperrt aber den Port von LiteLLM (`:92`) und alle Ports, auf denen Sokrates-2 lauscht. Ein Eintrag der Variablen allein reicht deshalb nicht:

1. **Prüfauftrag P6-0 (4 Stunden, vor dem Bau festgelegte Abbruchwerte):** Claude Code (die in der Sandbox festgeschriebene Version) gegen LiteLLM als
   Anthropic-kompatiblen Endpunkt (`/v1/messages`) mit einem LiteLLM-Schlüssel nur für den Test, Kandidat `qwen3.6:35b` (der in `voice-core/boss.py:208` genannte
   Name `wamo-coder` wird dabei angeglichen; nicht `sokrates-steuer`, nicht `sokrates-fable-qwen27`). Gemessen: Kontextfenster (Claude Code schickt Systemprompt und
   Werkzeuge mit fünfstelliger Tokenzahl), Zeit bis zum ersten Token, Werkzeugaufrufe, Abbruchrate in 5 Aufträgen der Art `recherche`, Last parallel zu einem
   Hausgespräch. Nur über LiteLLM, nie an Knoten-IPs.
2. **Proxy `wamo-haus-proxy`** auf Sokrates-2 (eigener Benutzer, TCP-Port auf Loopback, weil die Sandbox Loopback mit dem Host teilt und `ANTHROPIC_BASE_URL` eine
   http-Adresse braucht; `infra/sokrates2/wamo_job_dispatch.py:138`): nur `POST /v1/messages` und `/v1/messages/count_tokens`, Streaming (SSE) durchreichen, Modell
   aus einer festen Liste, Größen- und Zeitgrenzen, Grenze für gleichzeitige Anfragen (damit die Gespräche auf LiteLLM nicht leiden), Kostenzählung je Auftrag. Der
   LiteLLM-Schlüssel liegt nur beim Proxy (eigener virtueller Schlüssel mit Budget), nie in der Sandbox. Die Sandbox bekommt ein Auftragstoken, das der Proxy gegen den
   laufenden Auftrag prüft. Grenzen und Protokoll nach dem Muster von `infra/sokrates2/release/pruefer/pruefer_proxy.py` (der ist selbst nur ein CONNECT-Tunnel und
   taugt nicht als Vorlage für den Rest).
3. **Sandbox, Dispatcher, Kanal:** eine Ausnahme im Ausgang nur zum Port des Proxys (`infra/sokrates2/wamo-job.sh`), `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` und
   die Modellnamen in `ERLAUBT_RE` (`:209`), Zugangsart `haus` in `ZUGANG_MODI`, `ZUGANG_FORMAT`, `ZUGANG_VARIABLE` und `zugang_typ`
   (`infra/sokrates2/wamo_job_dispatch.py:173` bis `:180`, `:460`), eine Regel für `haus` im Kern-Kanal (`infra/sokrates2/wamo_job_kernkanal.py:689`) samt
   Vertragstest.
4. **Kern:** neue Quelle `haus` in `entwicklung_quelle` (`voice-core/boss.py:201` bis `:221`) für Profile ohne Token und ohne API-Schlüssel (Quelle `keiner`) und für
   Profile im Modus "Nur Hausmodelle" (`wahl`, `festgelegt`); nie für `fehler` und `labor`. Verdrahtung in `voice-core/bot.py:707` bis `:715`, nur mit Schalter
   `WAMO_ENTWICKLUNG_HAUS` im Drop-in. Der Kern gibt dem Dispatcher dabei kein Geheimnis mit, nur die Art `haus`.

Fällt der Prüfauftrag schlecht aus, bekommen Kollegen ohne Token und ohne API-Schlüssel vorerst keine Entwicklungsaufträge, und die Prüfliste sagt das ehrlich
(Entscheidung N7). D2 gilt dann für Gespräch und Stimme sofort und für Entwicklungsaufträge, sobald ein Hausmodell die Messung besteht.

## 5. Sicherheitsanalyse des Entwurfs

| Nr | Bedrohung | Wirkung | Gegenmaßnahme | Restrisiko |
| --- | --- | --- | --- | --- |
| S1 | Fremder nutzt das Startpasswort vor der Person | bindet eigenen Faktor, übernimmt das Konto | Sperre in GoTrue sofort und bis zur Übergabe, feste Reihenfolge in `freischalten` (Sitzungen und Faktoren weg, Abbruch bei fremden Faktoren), Übergabe persönlich, Frist 72 Stunden, Hinweise an Admins bei Beginn und Abschluss, Satz in der Oberfläche | gering |
| S2 | Umgehen der Oberfläche (direkt an den Kern) | Funktionen ohne Passwortwechsel | Sperre in Middleware (Pfadliste mit `raw_path`) und in `identitaet()`, Test über alle Routen, Start und Offer | gering |
| S3 | Andere Türen ohne Kern | Funktionen ohne Passwortwechsel | Freigabe-Dienst nur für Admins und prüft den Stand ebenfalls; Schema nicht in PostgREST; Labor-Dienst mit eigenem Token | gering |
| S4 | Einbruch in den Kern (Zweig B) | Übernahme der Konten im Stand `offen` (der Kern sieht jedes Bearer-Token und kann Codes holen) | Codes nur für Konten im Stand `offen`, nur einmal, 5 Minuten; Frist 72 Stunden; kein Service-Schlüssel im Kern | gering, weil nur wenige Konten zugleich offen sind |
| S5 | Fehlalarm "erledigt" ohne echten Wechsel | Startpasswort gilt weiter | Trigger nur bei Änderung von `encrypted_password`; P0 belegt, dass Anmelden den Hash nicht ändert; Frist; Hinweis an Admins | gering, V |
| S6 | Manipulierter Installer auf dem Server oder kompromittierter Kern | Schadcode auf neuen Laptops | Ablage nur root, Prüfsumme auf Papier, Update aus der App nur mit Ed25519-Signatur (Schlüssel auf Hardware-Token) und steigender Version, Codesignatur (N8), REA vor jeder Ausgabe | hoch bis zur Signaturprüfung in der App (P3), danach mittel bis zur Codesignatur |
| S7 | Download als Datenquelle für Fremde | Installer und interne Adressen | nur aal2 und erledigte Erstanmeldung, Ratengrenze, Protokoll | gering |
| S8 | Mitglied steuert fremden Laptop | Zugriff auf fremde Daten | Gerät nur aus dem Register zum eigenen Profil (B), ein Rechte-Modul, Tests | gering |
| S9 | Fremde Stimme löst PC-Befehle bei einem Mitglied aus | Aktionen am Laptop | Stimmabdruck Pflicht für Sprache unabhängig vom Modus, sonst nur getippt; Karten für kritische Aktionen | gering |
| S10 | Laborprofil bekommt neue Funktionen | Labor gefährdet | `rechte.py` schließt Laborprofile ausdrücklich aus, jede neue Stelle prüft `ist_labor`, eigener Test je Paket, Laborlisten unverändert, keine Abfrage des Merkers für Laborprofile | gering |
| S11 | Kosten durch Entwicklungsaufträge der Mitglieder | Rechnung oder Kontingent | Kostengrenzen je Auftrag und Tag, eigener Zugang, Hausmodelle mit Budget im Proxy, Notaus des Kanals | gering |
| S12 | Ausbruch aus der Sandbox über den Haus-Proxy | Zugriff auf LiteLLM oder das LAN | Proxy mit fester Pfad- und Modellliste, Schlüssel nie in der Sandbox, Auftragstoken, nur ein Port | gering |
| S13 | Rückweg des Kerns mit Konten außerhalb von `erledigt` | alter Kern kennt keine Sperre | Rückweg beginnt mit `sperren` (mit Sperre in GoTrue und `--schema`) für alle Konten außer `erledigt`; `down` behält die Tabelle | gering, wenn der Ablauf eingehalten wird |
| S14 | CA im Benutzerspeicher | Vertrauen für alle Programme des Benutzers | Namensbeschränkung der CA (B), Fingerabdruck auf dem Blatt | gering |
| S15 | Prompt-Injection bei Mitgliedern (Webseite liest, Modell tippt), auf Hausmodellen eher leichter | Aktionen am Laptop ohne Absicht | nach Fremdinhalt im Zug Karte auch für `change`, Lesewerkzeuge erst mit diesem Schutz, Eval-Fälle | mittel, wie bei jeder Steuerung durch ein Modell |
| S16 | Mitglied liest Auftragsergebnisse eines anderen oder blockiert den Kanal | Datenabfluss, Ausfall für alle | Profilkennung im Projektnamen, fremder Ordner ist Konflikt, Grenzen je Profil, Warteschlange | gering |

## 6. Pakete

Jedes Paket ist ein eigener Zweig und ein eigener PR, Tests zuerst (rot, dann grün), danach `verification-loop`. Modell: Sonnet für Umsetzung, Opus für Entwurf
und Review sicherheitskritischer Teile. Jede Änderung an Datenbank oder `wamo_auth` mit `database-reviewer` vor dem Anwenden auf das Betriebsschema.

| Paket | Inhalt | Stunden | Hängt ab von | Freeze berührt |
| --- | --- | --- | --- | --- |
| P0 | Prüfaufträge nur auf einem Wegwerf-Stack (nie das Auth des Betriebs): zuerst Wechsel in frischer aal2-Sitzung mit und ohne Code (entscheidet Zweig A oder B), dann Send-Email-Hook über `pg-functions`, `GOTRUE_MAILER_OTP_EXP`, `same_password`, `GOTRUE_PASSWORD_MIN_LENGTH`, Trigger auf `auth.users`, Hash bleibt beim Anmelden gleich, Sitzungen nach Admin-Wechsel; Download von 117 MB per `fetch` in Chrome, Edge und Electron; Tunnel über WireGuard | 8 | nichts | nein |
| P1a | Konto-Ebene am Server: `wamo_auth` (SQL, Rückweg, SQL-Test, Einrichtungsskript, Trigger, je nach Zweig Hook) (6), Migration 0021 (Sperre gegen Aktivieren ohne Merker, `.down.sql`, Test) (2), `wamo_nutzer.py` mit `freischalten`, `zuruecksetzen`, `umbenennen`, `sperren`, `austreten`, `passwort`, neuem `anlegen` (8), GoTrue-Ergänzung (1,5), Reviews `database-reviewer` und `security-reviewer` (2,5) | 20 | P0 | ja (GoTrue, Migration) |
| P1b | Kern und Oberfläche der Erstanmeldung: Stand in `Decision`, Middleware, `identitaet`, `SessionGuard`, `erstanmeldung_api.py`, Hinweise (12), Gerüst des geführten Ablaufs mit Schritteliste in `LoginGate` und Schritt Passwort (6), Tests und Reviews `python-reviewer`, `react-reviewer`, `security-reviewer` (4) | 22 | P1a | ja |
| P2 | Installer vom Server und Schritte 3a und 3b: Ablage und Skripte (5), `verteilung_api.py` mit `FileResponse` und Messung (5), Oberfläche Download (4), Schritte Token und API-Schlüssel mit Überspringen und Zusammenfassung aus den Bausteinen von `ModellZugang.tsx`, Kommentar in `sprache_anbieter.py` (3), Tests und Reviews (3) | 20 | P0; entwickelbar parallel zu P1, ausrollbar nach P1b | ja |
| P3 | Prüfliste und signierte Updates: App meldet Version und Host-Umgebung, Version 0.3.0 (4), Signatur des Manifests beim Bau mit Hardware-Token und Prüfung in der App, Update erst danach (6), `einrichtung_api.py` (5), Abschnitt "Erste Schritte" mit Prüfliste (6), Tests und REA-Abnahme (4) | 25 | P1b, P2 | ja (App: nein) |
| P4 | PC-Steuerung für Mitglieder (H1): `rechte.py` und Freischaltung je Profil (4), alle Stellen aus 4.5 samt Host-Client, Nachholen, Prompt und Oberfläche (10), Karte nach Fremdinhalt für `change` (3), Pflichtstufe der Stimme (3), Tests und Eval (4), `security-reviewer` (2) | 26 | nichts; nach dem Labor | ja |
| P5 | Entwicklungsaufträge für Mitglieder: `rechte.py`, `entwicklung_betrieb.py`, `bot.py` (5), Trennung je Profil im Kern und im Dispatcher, Grenzen je Profil, Warteschlange (8), Abschnitt "Verbrauch" für Profile mit Token (1), Skript `schalter` mit Versionsprüfung (3), Vertragstest (2), Tests und Review (4) | 23 | P4 (beide ändern `bot.py`, nacheinander) | ja |
| P6a | Hausmodelle, Teil Server: Prüfauftrag P6-0 (4), Proxy mit Streaming und Grenzen (14), LiteLLM-Schlüssel mit Budget (1, Niko), Ausnahme in der Sandbox (3) | 22 | P5 für den Einsatz, P6-0 vor allem anderen | ja (Server) |
| P6b | Hausmodelle, Teil Dispatcher und Kern: Zugangsart `haus` und Kanalregel mit Vertragstest (5), Quelle `haus` im Kern (3), Tests, Rauchtest, Review (7) | 15 | P6a | ja |
| P7 | Übersicht und Codesignatur: Admin-Übersicht "Neue Mitglieder" mit eigener SECURITY-DEFINER-Funktion (8), Codesignatur in den Bau einbinden (2), Doku (`README.md`, `CLAUDE.md` Namensvertrag, `CHANGELOG.md`, Willkommensblatt als Word im WMC-Design außerhalb des Repos) (6) | 16 | P3 | teilweise |
| **Summe** | | **197** plus 2 Stunden Option Ü | | |

Mit Zweig A (kein Hook) entfallen in P1a und P1b etwa 7 Stunden. Die Schätzungen sind an vergleichbaren Modulen gemessen (`voice-core/geraet_api.py` mit Migration
0002, `voice-core/geraete_admin_api.py` mit 0014, `ui/src/components/ModellZugang.tsx`).

### 6.1 Blöcke je Paket

**P1a Konto-Ebene.** Kontext: 2.1 bis 2.3, 4.1. Tests zuerst: SQL-Test für `wamo_auth` (Stände, Frist, `abgelaufen` bleibt, Trigger nur bei Änderung des Hashes,
Trigger blockiert GoTrue nie, Rechte nur `execute`, keine Rechte für `anon`, `authenticated`, `service_role`, RLS an, Hook verwirft fremde Arten, Code genau einmal),
`supabase/tests/0021_profil_freischaltung_test.sql` (Aktivieren ohne Merker scheitert, Laborprofil und aktive Profile unberührt), `scripts/test_wamo_nutzer.py`
(Reihenfolge in `freischalten`, Abbruch bei vorhandenen Faktoren, `umbenennen` aktiviert nicht, `sperren` verlangt `--schema`). Prüfung: alles nur auf dem
Wegwerf-Stack und auf `wamo_test`, zweimal hoch, runter, hoch. Ausstieg: Tests grün, `database-reviewer` und `security-reviewer` ohne CRITICAL und HIGH.

**P1b Kern und Oberfläche.** Tests zuerst: `voice-core/test_erstanmeldung.py` (Pfadliste mit `raw_path`, `identitaet` ohne Schlüsselwort lehnt ab, 403-Codes,
Laborprofil ohne Abfrage, fail closed bei fehlender Funktion, Cache geleert, Ratengrenze, frischer Code, `SessionGuard` beendet nach `zuruecksetzen`),
`ui/src/lib/erstanmeldung.test.ts` und ein Komponententest für `LoginGate` (Reihenfolge der Schritte, erneute Code-Abfrage, Warnsatz). Ausstieg: zusätzlich
Labor-Rauchtest und Laborfälle unverändert grün.

**P2 Installer und Schritte 3a und 3b.** Tests zuerst: `voice-core/test_verteilung_api.py` (nur Manifest-Datei, kein Pfad vom Client, Range, Ratengrenze,
Kopfzeilen, Laborprofil 403, fehlende Datei 503), `scripts/test_wamo_installer_sokrates2.py` (falsche Prüfsumme oder Signatur, sinkende Version heißt Abbruch),
`ui/src/lib/einrichtung.test.ts` (Token vor API-Schlüssel, beide überspringbar, Zusammenfassung je Fall), ein Kerntest als Wächter, dass ein Profil nur mit Token
`entwicklung_quelle == "token"` und ein Gespräch über Hausmodelle hat. Ausstieg: Download im Büro in Chrome und Edge belegt, kein Aussetzer im laufenden Gespräch,
alle vier Fälle richtig.

**P3 Prüfliste und signierte Updates.** Tests zuerst: `voice-core/test_einrichtung_api.py` (jede Zeile der Tabelle mit Attrappen, nie ein MCP-Start oder
Werkzeugaufruf), `desktop/geraet.test.js`, `desktop/installation.test.js` und ein neuer Test für die Updateprüfung (falsche Signatur, fremder Schlüssel, alte Version,
Abbruch ohne Rückfrage), `ui/src/lib/einrichtung.test.ts` erweitert. Abnahme am gebauten Installer mit REA (4.3) und mit einem frischen Windows-Konto ohne
Admin-Rechte.

**P4 PC-Steuerung für Mitglieder.** Tests zuerst: `voice-core/test_rechte.py` (Wertetabelle Rolle, Freischaltung, Labor), Erweiterung von
`voice-core/test_labor_pc_unveraendert.py`, ein Test, dass `pc_steuerung` mit `an: true` für ein nicht freigeschaltetes Mitglied aus bleibt, Werkzeugliste eines
Mitglieds exakt `LLM_TOOLS_MITGLIED` (auch nach dem Nachholen), Prompt eines Mitglieds ohne PowerShell und Bildschirm, Karte für `change` nach Fremdinhalt,
Eval-Fälle. Review `security-reviewer` Pflicht. Nachtrag 16.11.2026 (N10 geändert): Werkzeugliste eines Mitglieds gleich der Liste der Admins bei gleichen
Schaltern (`voice-core/test_pc_mitglied.py`, `test_rechte.py`, `test_pc_geraet.py`), Office, Bildschirm und Live-Bild nur mit Freischaltung und Schalter,
Laborprofile weiter ohne alles (`test_labor_pc_unveraendert.py`), Schutz für die Werkzeuge des Kerns, Karte und Ausführer für Klick und Datei, Prompt der
Admins mit Zusatz, Eval-Fall g01 neu (Anweisung auf einer Webseite, PowerShell zu nutzen), Host- und App-Tests für das Live-Bild und die Texte der Karten.

**P5 Entwicklungsaufträge für Mitglieder.** Tests zuerst: `voice-core/test_entwicklung_betrieb.py` und `voice-core/test_entwicklung_haertung.py` erweitert
(Mitglied mit und ohne Schalter, nicht in der Liste, Laborprofil), Projektname mit Profilkennung auf beiden Seiten (`voice-core/test_kernkanal_vertrag.py`), fremder
Ordner ist Konflikt, Grenzen je Profil, Warteschlange, `voice-core/test_job_kern_skripte.py` (`schalter --mitglieder` verlangt Version 2).

**P6a und P6b Hausmodelle.** Erst nach einem guten Ergebnis von P6-0. Tests zuerst: Proxy (Pfad, Modell, Größe, Streaming, Token, Budget, Gleichzeitigkeit),
Dispatcher (Zugangsart `haus`, nie ein Schlüssel in der Umgebung der Sandbox), Kanalregel und Vertragstest, Kern (`haus` nie für `fehler` und `labor`), Rauchtest am
Server mit Attrappe statt LiteLLM, danach ein echter Auftrag `recherche`.

**P7 Übersicht und Codesignatur.** Tests zuerst: Übersicht nur für Admins und ohne Geheimnisse, eigene Funktion mit genau den nötigen Spalten. REA wie in 4.3.

### 6.2 P0-Ergebnis (15.11.2026)

**Aufbau.** Wegwerf-Stack auf Sokrates-2, Compose-Projekt `wamo-p0` (Container `wamo-p0-db` und `wamo-p0-auth`), nur Datenbank und Auth, dieselben Images
wie `supabase-wamo` (`supabase/postgres:17.6.1.136`, `supabase/gotrue:v2.196.0`) und dieselben Auth-Einstellungen wie im Betrieb (Sitzungsgrenzen,
`GOTRUE_SECURITY_UPDATE_PASSWORD_REQUIRE_REAUTHENTICATION=true`), eigene Geheimnisse, Auth nur auf `127.0.0.1:59991`, ohne Verbindung zum Betrieb. Gemessen mit
Wegwerf-Konten (Anmeldung, TOTP mit selbst berechnetem Code, Admin-Schnittstelle mit eigenem Dienst-Token). Danach dort `wamo_auth`, die Migrationen 0001 bis 0021
im Schema `wamo_test`, alle SQL-Tests und ein Durchlauf von `scripts/wamo_nutzer.py` gegen echtes GoTrue. Der Stack ist danach vollständig entfernt.

| Nr | Frage | Ergebnis |
| --- | --- | --- |
| 1 | Passwortwechsel (`PUT /user`) in frischer aal2-Sitzung ohne Code | **HTTP 200, Hash geändert.** GoTrue verlangt den Code nur bei Sitzungen über 24 Stunden |
| 2 | Wechsel in einer aal1-Sitzung eines Kontos mit bestätigtem Faktor | HTTP 401 `insufficient_aal`, Hash unverändert |
| 3 | Wechsel auf dasselbe Passwort | HTTP 422 `same_password` |
| 4 | `GOTRUE_PASSWORD_MIN_LENGTH=12`, Wechsel mit 11 Zeichen | HTTP 422 `weak_password`; die Admin-Schnittstelle legt trotzdem Konten mit 11 Zeichen an (prüft die Länge nicht) |
| 5 | Ändert Anmelden den Hash | nein (zwei Anmeldungen, Hash gleich) |
| 6 | Andere Sitzungen nach dem Wechsel durch die Person | beendet (`refresh_token_not_found`), die eigene bleibt |
| 7 | Sitzungen nach einem Wechsel über die Admin-Schnittstelle | alle beendet |
| 8 | Sitzungen per SQL löschen (`delete from auth.sessions`) | Refresh-Tokens weg; ein altes Access-Token bekommt bei GoTrue `session_not_found` (am Kern gilt es bis zum Ablauf, lokale Prüfung) |
| 9 | `ban_duration` `876000h`, danach `none` | Anmeldung `user_banned`, danach wieder möglich |
| 10 | Faktor über die Admin-Schnittstelle löschen | gelöscht |
| 11 | `GET /reauthenticate` ohne Mailweg | HTTP 500 (der Code ließe sich nur über Mail oder Hook zustellen) |
| 12 | Trigger `after update of encrypted_password` auf `auth.users` als `postgres` | anlegbar (`postgres` ist kein Superuser, Besitzer ist `supabase_auth_admin`); feuert beim Wechsel durch die Person und durch die Admin-Schnittstelle, nie beim Anmelden |
| 13 | Ende zu Ende mit `wamo_auth`, 0021 und `wamo_nutzer.py` | anlegen (gesperrt, inaktiv), Aktivieren ohne Merker scheitert, freischalten, Wechsel durch die Person setzt `erledigt`, freischalten mit fremdem Faktor bricht ab und lässt das Konto gesperrt, zuruecksetzen (Faktoren und Sitzungen weg, Stand `offen`), `sperren --offene`, umbenennen, Option Ü, austreten |

Nicht gemessen, weil nicht mehr nötig oder nicht Teil von Strang 1: Send-Email-Hook über `pg-functions` und `GOTRUE_MAILER_OTP_EXP` (Zweig B entfällt), Sitzungen
über 24 Stunden (erwartet `reauthentication_needed`, die Oberfläche bittet dann um eine neue Anmeldung), Download von 117 MB (P2), Tunnel über WireGuard (am Gerät).

**Entscheidung: Zweig A.** Kein Hook, keine Tabelle `bestaetigungscodes`, keine Route `/code`. Der Trigger auf `auth.users` trägt (Ersatz über den Hash-Vergleich
entfällt). Ein Wechsel, während das Konto in GoTrue gesperrt ist, zählt nicht als erledigt: Das ist immer das Admin-Skript (es sperrt zuerst und löscht alle
Sitzungen), so meldet `zuruecksetzen` nie fälschlich "abgeschlossen".

**Neuer Befund, der den Weg ändert.** Caddy auf 55443 weist seit dem Token-Test vom 12.11.2026 jedes `PUT` und `PATCH` auf `.../auth/.../user` ab
(`infra/sokrates2/wamo-caddy/Caddyfile:40` bis `:51`, Test `voice-core/test_caddy_passwortwechsel.py`). Das ist der eigentliche Schutz der Laborplätze, denn die
Einstellung in GoTrue wirkt in frischen Sitzungen nicht (Nr. 1). Der Browser kann `updateUser` deshalb nicht direkt aufrufen. Weg in P1b: eine Route des Kerns
`POST /wamo/api/erstanmeldung/passwort`, nur im Stand `offen`, nie für Laborprofile, mit aal2 und Ratengrenze; der Kern reicht das Passwort mit dem eigenen
Token der Person über Loopback an GoTrue weiter (Envoy `127.0.0.1:55321`, wie `wamo_nutzer.py`), ohne Service-Schlüssel und ohne Log des Inhalts. Die Sperre in Caddy
bleibt unverändert, das Labor ist weiter geschützt. Bedingung dafür: Envoy 55321 ist aus dem Büro-LAN nicht erreichbar (Firewall Stufe 2, `WAMO_FW_HTTP_NUR_INTERN=ja`, `infra/sokrates2/wamo-firewall.sh`); am 16.11.2026 geprüft, die Kette `WAMO-FW-HTTP` lässt nur Loopback und das Caddy-Netz durch. Ein Rückfall auf Stufe 1 öffnet den Passwortwechsel für jedes aal2-Token aus dem LAN, auch für Laborgäste. Ein kompromittierter Kern gewinnt damit nichts Neues (er sieht die Bearer-Tokens ohnehin und erreicht Loopback,
S4). Umgesetzt in P1b: Sperre zentral in `auth_gate.erstanmeldung_sperre`, Ausnahme nur mit `identitaet(request, weg_frei=True)` in den beiden Routen der Erstanmeldung. Spätere Möglichkeit ohne Passwort im Kern: `forward_auth` in Caddy auf eine Prüfroute des Kerns (Änderung am Caddy, nur bei Bedarf).

**Befund für das Labor (an Niko).** Die Einstellung `GOTRUE_SECURITY_UPDATE_PASSWORD_REQUIRE_REAUTHENTICATION` schützt frische Laborsitzungen nicht. Geschützt sind
die Laborplätze durch die Sperre in Caddy, die seit dem 12.11. aktiv ist. Bis zum Labortag nichts ändern, die Sperre in Caddy darf nicht fallen.

## 7. Tests (Rot zuerst), Übersicht

| Teil | Tests |
| --- | --- |
| Datenbank und Konto | SQL-Test `wamo_auth` unter `infra/sokrates2/supabase-wamo/`, `supabase/tests/0021_profil_freischaltung_test.sql` |
| Kern | `voice-core/test_erstanmeldung.py`, `test_verteilung_api.py`, `test_einrichtung_api.py`, `test_rechte.py`, erweitert: `test_labor_pc_unveraendert.py`, `test_entwicklung_betrieb.py`, `test_entwicklung_haertung.py`, `test_kernkanal_vertrag.py`, `eval/faelle.py` (Mitglied bittet um PowerShell, Mitglied ohne Abdruck spricht einen PC-Befehl, Webseite mit Anweisung zum Tippen) |
| Server | `scripts/test_wamo_nutzer.py`, `scripts/test_wamo_installer_sokrates2.py`, `voice-core/test_job_kern_skripte.py`, Proxy- und Dispatchertests unter `infra/sokrates2` |
| Oberfläche | `ui/src/lib/erstanmeldung.test.ts`, `ui/src/lib/einrichtung.test.ts`, Komponententests für `LoginGate` und den Abschnitt "Erste Schritte" (vitest nur aus PowerShell mit `D:\`) |
| Desktop | `desktop/geraet.test.js`, `desktop/installation.test.js`, `desktop/dist.test.js` (Version, neue Kanäle), Test der Updateprüfung, REA am gebauten Installer |
| Am Gerät | frisches Windows-Konto ohne Admin: Blatt, Browser, CA, Erstanmeldung, Token und Schlüssel überspringen, Download, Installation, Prüfliste grün; einmal ohne Netz zu PyPI (Prüfliste nennt es) |

## 8. Zeitplan: vor dem Freeze und danach

**Sofort, ohne Code (Nikos Ja nötig):** die sieben Konten in GoTrue sperren (Admin-Schnittstelle am Server, wie `wamo_nutzer.py` sie nutzt). Kein Kern, keine
Migration, keine Oberfläche, kein Neustart.

**Vor dem Freeze (Mo 16.11. bis Do 19.11.), ohne Wirkung am Betrieb:** P0 (8 Stunden, nur Wegwerf-Stack), P6-0 vom Laptop gegen LiteLLM, rote Tests und Code von P1a,
P1b und P2 auf Zweigen ohne Merge, Willkommensblatt als Entwurf. Kein Kern-Release, keine Migration, kein Neustart des Auth-Dienstes, keine neue Oberfläche und kein
Merge auf `main` (jeder Merge außerhalb von `docs/` baut am Server dev und test, `.github/workflows/deploy.yml:1` bis `:20`). Gründe: Die Messrunden und der Lasttest
des Labors messen ab Mo 16.11. den Stand des Labortags (`docs/testlabor-wamo.md:34`, `:76` bis `:79`), P1b ändert die Zugangskontrolle, durch die jede Laborsitzung
läuft, und ein Hook oder Neustart von GoTrue trifft auch alle Laborkonten.

**Nach dem Labor (ab Mo 30.11.), bei etwa 6 Stunden je Tag in zwei Strängen, ohne Puffer für Rollout, Bewährung und Nikos Ja:**

| Strang | Folge | Ende etwa |
| --- | --- | --- |
| 1 | P1a (20), P1b (22), P3 (25), P7 (16), P6b (15) | P1a Do 3.12., P1b Di 8.12., P3 Di 15.12., P7 Do 17.12., P6b Di 22.12. |
| 2 | P2 (20), P4 (26), P5 (23), P6a (18, ohne P6-0) | P2 Do 3.12., P4 Mi 9.12., P5 Di 15.12., P6a Fr 18.12. |

Eine Pilotperson ab etwa **Mi 9.12.** (nach P1a, P1b und P2, mit Niko daneben). Alle sieben Kollegen nach P3 und dem Lasttest-Ergebnis, etwa **Mi 16.12.2026**.
PC-Steuerung je freigeschalteter Person mit dem nächsten Kern-Release nach P4, Entwicklungsaufträge mit Token oder API-Schlüssel nach P5 (etwa Mi 16.12.), mit
Hausmodellen nach P6b (etwa Di 22.12., sonst Januar). Streichreihenfolge bei Zeitnot: P7 Übersicht, dann P6, dann die Warteschlange in P5 (dann nur "anderer
Auftrag läuft, später noch einmal").

**Option Ü (Übergang ohne Änderung an Kern, Migration und Oberfläche), nur wenn einzelne Kollegen vor dem 9.12. starten müssen:** Befehl `wamo_nutzer.py passwort`
(Skript, nicht im Freeze, etwa 2 Stunden mit Test) mit derselben Reihenfolge wie `freischalten` (Sperre, Sitzungen und Faktoren weg, Passwort, Freigabe): Die Person
tippt ihr Passwort am Platz von Niko selbst verdeckt ein, Niko schaltet das Profil frei, die Person richtet den Faktor im Browser ein. Installer aus dem Ordner der
Firma mit Prüfsumme auf Papier. Ergebnis: Gespräch (nach D2 mit eigenem Schlüssel aus der Karte Modellzugang oder Hausmodellen), Stimme über Soniox, eigener Laptop mit
Tunnel; keine PC-Werkzeuge, keine Entwicklungsaufträge. Etwa 20 Minuten je Person mit Niko. Nicht in der Labor-Woche (23. bis 28.11.).

## 9. Rollout am Server und Rückweg

Vor jedem Merge und jedem Rollout fragt der Umsetzer Niko ausdrücklich. Nur bei Ruhe, Skripte mit `--trocken` zuerst, **nie `systemctl restart wamo-core`**.
Reihenfolge je Paket: Datenbank vor Merge (der Merge baut den Kern im freien Slot), Kern vor Oberfläche, Schalter zuletzt. Einstellungen über `wamo-core-env` wirken
erst mit dem nächsten Kern-Release. Neustarts von GoTrue nie in der Labor-Woche und immer vor der Kernfreigabe. P1b und P2 bringen zwei Kern-Releases kurz
nacheinander, je mit `bewaehren 30`. Der Cache des Merkers wird nur im antwortenden Slot geleert; bis zu 10 Sekunden Verzögerung sind hinnehmbar.

| Paket | Reihenfolge | Rückweg |
| --- | --- | --- |
| P1a | 1. `wamo_auth` mit `wamo-auth-einrichten.sh` (`--trocken`, dann echt, SQL-Test), `database-reviewer`. 2. Migration 0021 auf `wamo_test` (zweimal, Test), dann auf das Betriebsschema (`psql -v ON_ERROR_STOP=1 --single-transaction`). 3. GoTrue-Ergänzung (Mindestlänge, je nach Zweig Hook), nur Auth-Container neu (Muster `NUR_SITZUNGSGRENZEN=1`, `infra/sokrates2/supabase-wamo-einrichten.sh:27`), Anmeldung von Niko und einem Laborprofil prüfen | GoTrue-Ergänzung zurück (Auth-Container neu), `0021.down.sql`, `wamo_auth` zurück mit eigenem Rückweg; die Tabelle der Merker bleibt (nur Rechte entzogen) |
| P1b | 1. Merge, Kern über die Slots (`release`, `umschalten-kern`, `bewaehren 30`, `ausleiten`), Labor-Rauchtest. 2. Oberfläche (`wamo_ui_sokrates2.py verteilen`, `umschalten`). 3. `wamo_nutzer.py freischalten` für eine Pilotperson mit Niko daneben | erst `wamo_nutzer.py sperren --schema <Betriebsschema>` mit Sperre in GoTrue für alle Konten außer `erledigt`, dann Oberfläche `zurueck`, `rueckweg-kern` |
| P2 | 1. Ablage einrichten und Installer einsetzen. 2. Kern. 3. Oberfläche | Oberfläche und Kern zurück; Ablage bleibt (wirkungslos ohne Route) oder `wamo-verteilung-einrichten.sh rueckweg` |
| P3 | 1. Installer 0.3.0 bauen, signieren, REA, einsetzen über P2. 2. Kern. 3. Oberfläche | Kern und Oberfläche zurück; App 0.3.0 bleibt nutzbar (Prüfliste fehlt nur) |
| P4 | Kern-Release mit leerer Freischaltung, dann `wamo-core-env setzen WAMO_PC_MITGLIEDER_PROFILE <user_id>` für eine Pilotperson, nächster Kern-Release, Rauchprobe | sofort je Person: Gerät sperren; dann Liste leer und Kern-Release |
| P4 Nachtrag 16.11.2026 (Werkzeuge der Admins für Mitglieder) | Kern-Release (wirkt sofort für alle Personen in `WAMO_PC_MITGLIEDER_PROFILE`; PowerShell, Git, GitHub und Bildschirm ohne weiteren Schalter, Office nur mit `WAMO_OFFICE`), Oberfläche; Live-Bild und die neuen Texte der Karten am Laptop erst mit Installer 0.4.0 | sofort je Person: Gerät sperren oder Person aus der Liste nehmen und Kern-Release; ganz: `rueckweg-kern` auf den Stand davor, Oberfläche `zurueck`; Installer 0.3.0 bleibt nutzbar (Mitglieder ohne Live-Bild) |
| P5 | Kern-Release, Dispatcher, dann `wamo-job-kern-einrichten.sh schalter --mitglieder an` | sofort: `wamo-job-kern-rueckweg.sh notaus`; dann Schalter aus |
| P6a, P6b | Proxy einrichten (Rauchtest mit Attrappe), LiteLLM-Schlüssel, Sandbox, Dispatcher, Kern-Release, Schalter `WAMO_ENTWICKLUNG_HAUS` | sofort: Proxy stoppen (Aufträge mit Hausmodellen scheitern geschlossen), dann Schalter aus |
| P7 | Kern und Oberfläche; Codesignatur ab dem nächsten Installer | Übersicht über die Oberfläche zurück |

## 10. Offene Entscheidungen für Niko

Ohne Antwort gilt die Empfehlung.

| Nr | Frage | Empfehlung |
| --- | --- | --- |
| N1 | Wann geht es los? Laut `docs/testlabor-wamo.md` (E14) gilt der Freeze schon seit So 15.11., laut Auftrag ab Fr 20.11. | Vor dem Labor nur Prüfaufträge und Code auf Zweigen ohne Merge, Rollout ab Mo 30.11., Pilot ab etwa Mi 9.12., alle ab etwa Mi 16.12. Option Ü nur für einzelne Kollegen mit echtem Bedarf, nicht in der Labor-Woche |
| N2 | Weg für den Passwortwechsel, falls GoTrue in frischen Sitzungen einen Code verlangt (Zweig B): V1 Mail, V2 Hook mit Code über den Kern, V3 eigener Dienst mit Service-Schlüssel | V2, wenn P0 den Hook belegt, sonst V3 mit eigenem Review. Verlangt GoTrue keinen Code (Zweig A), der direkte Weg, und der Befund zur Laborhärtung geht vor dem Labortag an dich |
| N3 | Zertifikat für den Browser beim ersten Anmelden: Import der WAMO-CA nach dem Blatt oder ein eigener Name mit öffentlichem Zertifikat | Jetzt der Import nach dem Blatt (ein Befehl, Fingerabdruck zum Vergleichen); einen eigenen Namen mittelfristig prüfen |
| N4 | Die sieben Konten jetzt in GoTrue sperren, die heutigen Startpasswörter verwerfen, am Übergabetag neue erzeugen (72 Stunden gültig, nur persönlich auf Papier) | Ja, die Sperre sofort |
| N5 | Gerätefreigabe: erstes Gerät eines Mitglieds weiter automatisch | Ja, wie heute; alles andere entscheidet ein Admin |
| N6 | Entwicklungsaufträge der Mitglieder: welche Arten, welche Kostengrenzen, Repos | Arten wie für dich freigegeben (heute `recherche`), keine Repos bis Folgepaket 1 mit einer Liste je Person. Kostengrenzen: zuerst empfohlen je Auftrag 2 US-Dollar und je Tag und Person 10 US-Dollar; **entschieden am 16.11.2026: keine eigene Grenze für Mitglieder**, es gelten dieselben Grenzen aus dem Drop-in wie für Admins (Grund: Mitglieder mit eigenem Claude-Code-Max-Tarif hinterlegen ihren eigenen Token und Schlüssel; "Keine Grenze von 2 USD setzen!") |
| N7 | Entwicklungsaufträge mit Hausmodellen (D2): was gilt, wenn der Prüfauftrag schlecht ausfällt | Prüfauftrag zuerst mit `qwen3.6:35b` über LiteLLM; reicht die Qualität nicht, vorerst keine Entwicklungsaufträge für Kollegen ohne Token und Schlüssel, Gespräch und Stimme gelten trotzdem sofort |
| N8 | Codesignatur des Installers (Zertifikat OV oder Signaturdienst von Microsoft, etwa 10 US-Dollar im Monat, V) | Ja, vor einer Ausgabe an mehr als die sieben Kollegen; bis dahin Prüfsumme auf dem Blatt und signiertes Manifest |
| N9 | Downloadweg bis P2 (das Repo wird privat) | Ordner der Firma nur für Mitarbeiter, Prüfsumme auf dem Blatt |
| N10 | PC-Werkzeuge der Mitglieder: Liste ohne PowerShell lesen, Git klonen, Repo anlegen, ohne Bildschirm und Office; Sprache nur mit Stimmabdruck (damit wird der Abdruck für gesprochene PC-Befehle Pflicht, heute ist er freiwillig) | Ja, so; der Abdruck wird ein Schritt der Prüfliste. **Geändert am 16.11.2026**, Niko wörtlich zur Regel "Nie für Kollegen: PowerShell, Git und GitHub, Bildschirmbild, Live-Bild und Office": "DAS SOLLTE FÜR KOLLEGEN AUCH MÖGLICH SEIN FÜR IHREN LAPTOP!" Seitdem bekommen freigeschaltete Mitglieder für ihren eigenen Laptop dieselben PC-Werkzeuge wie Admins (jeweils nur mit dem Schalter am Server); Stimmabdruck als Pflicht, Karte nach Fremdinhalt, Freischaltung je Person und Laborprofile nie bleiben (4.5, 11.1) |
| N11 | Bleiben die sieben Kollegen Mitglieder (nicht Admin)? | Ja |
| N12 | Signaturschlüssel für Updates: Hardware-Token (zum Beispiel ein FIDO2- oder PIV-Schlüssel) statt Datei auf dem Bau-Laptop | Ja, ein eigenes Token nur dafür, bei dir verwahrt |
| N13 | Kapazität der Entwicklungsaufträge: ein Auftrag gleichzeitig für alle, Warteschlange mit höchstens einem wartenden Auftrag je Person | Zuerst empfohlen: ja, mehr Parallelität erst mit eigenem Netz-Namensraum je Auftrag. **Entschieden am 16.11.2026: sechs gleichzeitig gesamt, je Person drei** (Dispatcher 9, einstellbar in `kernkanal.conf`); die Trennung gleichzeitiger Aufträge leistet ein eigener Portbereich je Platz mit Landlock, ein eigener Netz-Namensraum bleibt ein Folgepaket (`infra/sokrates2/README.md` 18.2) |

## 11. Ergebnis des Sicherheitsreviews

Zwei unabhängige Reviews des Entwurfs vom 15.11.2026 (Agent `security-reviewer` und Agent `architect`), beide nur lesend gegen den Code. Urteil Sicherheit:
**freigeben mit Änderungen, kein CRITICAL, drei HIGH.** Urteil Architektur: gut belegt, Rollout und Rückweg tragfähig; Nonce-Frage klären, Einbindung ins Zugangstor
ändern, Pakete teilen, Stunden anheben. Alle Befunde sind in diesem Papier eingearbeitet.

**Sicherheitsreview.**

| Nr | Stufe | Befund | Lösung im Plan |
| --- | --- | --- | --- |
| 1 | HIGH | Fremde Faktoren und Sitzungen überleben `freischalten`, `zuruecksetzen` und Option Ü; ein Fremder mit eigenem TOTP könnte im Stand `offen` den Code holen und das Passwort ändern; der Kern prüft Tokens nur lokal | feste Reihenfolge im Skript (Sperre, Sitzungen und Refresh-Tokens weg, Faktoren weg mit Abbruch bei fremden, Passwort, Hash, Freigabe), `SessionGuard` prüft den Merker, Hinweis an Admins schon beim Beginn, Warnsatz in der Oberfläche (4.1, 3, S1) |
| 2 | HIGH | Update-Hinweis vor der Signaturprüfung macht einen kompromittierten Kern zur Verteilstelle; Widerspruch "Bau-Laptop" gegen "offline" | Update aus der App erst mit Ed25519-Prüfung und steigender Version in P3 (vorgezogen aus P7), Schlüssel auf Hardware-Token, S6 bis dahin hoch (4.2, S6, N12) |
| 3 | HIGH | Kern-Kanal trennt Profile nicht (gleiche Projektnamen, ein Auftrag für alle, gemeinsame Grenzen) | Profilkennung im Projektnamen und in `auftrag.json`, fremder Ordner ist Konflikt, Grenzen je Profil, Warteschlange, Vertragstest in P5 (4.6, S16, N13) |
| 4 | MEDIUM | Fehlender Merker heißt Durchlass; eine alte Kopie von `anlegen` öffnet ein Konto | Migration 0021: Aktivieren ohne Merker scheitert; `anlegen` legt gesperrt an (4.1) |
| 5 | MEDIUM | Rückweg P1 lässt Lücken (`abgelaufen`, `sperren` ohne GoTrue und mit Standardschema, `down` löscht Merker) | Rückweg sperrt alles außer `erledigt` mit GoTrue und `--schema`, `down` behält die Tabelle (9, S13) |
| 6 | MEDIUM | `wamo_auth` hängt am Migrationsweg je Schema; P0 auf dem Test-Schema träfe dasselbe GoTrue | `wamo_auth` eigenes SQL mit eigenem Rückweg, P0 nur auf einem Wegwerf-Stack (4.1, P0) |
| 7 | MEDIUM | Prompt-Injection bei Mitgliedern fehlte; Pflichtstufe der Stimme wäre bei Modus `aus` wirkungslos | S15, Karte für `change` nach Fremdinhalt, Lesewerkzeuge erst mit diesem Schutz, Pflichtstufe unabhängig vom Modus, Eval-Fälle (4.5) |
| 8 | LOW | Ort der Pfadsperre: `authorize` kennt keinen Pfad | Stand in `Decision`, Pfadliste in der Middleware mit `raw_path`, `identitaet(erstanmeldung=True)`, keine Abfrage für Laborprofile (4.1) |
| 9 | LOW | Code lebt in GoTrue länger als 5 Minuten; "Token zusätzlich nötig" trägt nicht | `GOTRUE_MAILER_OTP_EXP=300`, `no-store`, nie loggen, S4 ehrlich formuliert |
| 10 | LOW | Lücken in P6 (Kanalregel `folgt`, `haus` nie für `fehler` und `labor`, Telemetrie, Gleichzeitigkeit, Socket oder URL) | alles in 4.7, Punkte 2 bis 4 |
| 11 | LOW | Merge auf `main` baut den Kern sofort im freien Slot; 117 MB durch den Kern | "Datenbank vor Merge", keine Merges vor dem Labor; `FileResponse` mit Messung, `forward_auth` als Ersatz (8, 9, 4.2) |

**Architekturreview (Auswahl der Befunde mit Wirkung auf den Plan).**

| Nr | Stufe | Befund | Lösung im Plan |
| --- | --- | --- | --- |
| 1 | wichtig | Nonce in frischen Sitzungen ist offen; der Satz "schützt weiter die Laborplätze" war unbelegt | P0 misst das zuerst, Zweig A oder B, Befund zum Labor geht an Niko (4.1, N2) |
| 2, 8 (Sicherheit) | wichtig | Sperre passt nicht in `authorize`, Aufrufe ohne Pfad | Middleware plus `identitaet` (4.1) |
| 3 | wichtig | einfachere Variante: Trigger auf `auth.users` statt Schreiben in der Lesefunktion | übernommen, Trigger setzt "erledigt"; Hash-Vergleich nur noch als Ersatz (4.1) |
| 4 | wichtig | globales Schema passt nicht in die Kette je Schema | eigenes SQL für `wamo_auth`, Migration 0021 nur je Schema (4.1, 12) |
| 5, 6 | wichtig | Prompt bewirbt fehlende Werkzeuge; weitere Stellen (Host-Client, Nachholen, Klick, Oberfläche) | alle Stellen in 4.5 und P4, P4 auf 26 Stunden |
| 7 | wichtig | Schalter kernweit, kein Pilot; Laborprofile haben Rolle `mitglied` | Freischaltung je Profil, ausdrücklicher Ausschluss der Laborprofile (4.5) |
| 8 | wichtig | Haus-Proxy größer, Kanalregel, Loopback statt Socket | P6 in P6a und P6b geteilt, 37 Stunden (4.7) |
| 9 | wichtig | ein Auftrag für alle, Projektnamen global, Last | 4.6, Lasttest als Vorbedingung, N13 |
| 10, 11 | mittel | Pakete zu groß, Stunden zu niedrig | P1 in P1a und P1b, P6 geteilt, P7 verkleinert, Summe 197 Stunden |
| 12, 13 | mittel | Kernroute passt; Namenskollision `einrichtung`; Tunnelprüfung nicht über `pc_zugang_fuer` | Abschnitt "Erste Schritte" (`start`), Lesen ohne Recht, kein MCP-Start (4.2, 4.3) |
| 14 | mittel | Pflichtabdruck widerspricht der freiwilligen Einwilligung | ausdrücklich in N10 |
| 15 | mittel | weitere `is_admin`-Stellen, `SCHRANKEN_VERSION` festgenagelt | `rechte.py` für beides, Versionsprüfung im Skript (4.6) |
| 16 | mittel | Fall `zuordnung` fehlte; Abbruchwerte für P6-0 | ergänzt (4.7) |
| 17 | mittel | Auth-Neustart vor Kernfreigabe, nie in der Labor-Woche; sieben Konten sofort sperrbar | Abschnitt 8 und 9, N4 |
| 18 | gering | Station 5 fragte Token und Schlüssel doppelt; Offboarding fehlte; Übersicht braucht eigene Funktion; Modellname | Station 5 gekürzt, `austreten`, P7, Namensangleich (3, 4.1, 4.7) |

### 11.1 Nachtrag 16.11.2026: Werkzeuge der Admins für Mitglieder (N10 geändert)

Review `security-reviewer` und `python-reviewer` des Zweigs `feat/mitglieder-werkzeuge`, nur lesend. Urteil Sicherheit: **kein CRITICAL, zwei HIGH**; Python:
kein CRITICAL, kein HIGH.

**Abwägung.** Seit dem 16.11.2026 beruht der Schutz der Mitglieder nicht mehr auf einer engen Werkzeugliste, sondern auf drei Schichten im Kern: Stimmabdruck als
Pflicht für gesprochene PC-Befehle, eine Karte für jede Änderung am Laptop nach Inhalten von außen und die Karten des Hosts für alles Kritische (PowerShell, das
nicht rein liest, GitHub, Senden, Klicks in Mail und Messenger). Restrisiken sind der Mensch, der eine Karte ungeprüft bestätigt, und Fremdinhalt, der länger
im Gesprächsverlauf bleibt als die Nachwirkung von zwei Beiträgen (`NACHWIRKUNG_ZUEGE`). Das gilt bei Admins gleich, trifft bei Mitgliedern aber weniger geübte
Freigebende. Lesen am Laptop (PowerShell, Bildschirm) gibt Inhalte an das Modell des Profils weiter (eigener Zugang oder Hausmodell); der Datenschutz gehört
deshalb zur Freischaltung je Person.

| Nr | Stufe | Befund | Stand |
| --- | --- | --- | --- |
| 1 | HIGH | Karten des Hosts (PowerShell, GitHub, Klick) trugen nach Fremdinhalt keinen Hinweis, nur Mail-Karten | behoben: bei Mitgliedern trägt nach Fremdinhalt jede Karte außer der des Kerns `WARNUNG_FREMD` (`PcFreigaben`, `fremd_warnung`) |
| 2 | HIGH | Die Kartenpflicht nach Fremdinhalt läuft nach zwei Beiträgen ab, der Fremdtext bleibt im Verlauf; danach gehen auch Klick auf den Bildschirm, `git_klonen` und `canvas_exportieren` ohne Karte | offen, Entscheidung für Niko: vorbestehend seit P4 (Befund M1, bewusst zwei Beiträge wegen zu vieler Rückfragen); Vorschlag des Reviews: für Mitglieder bis Sitzungsende |
| 3 | MEDIUM | `SENSITIVE_READ` des Hosts lässt einige Pfade und Befehle als reines Lesen durch (zum Beispiel PSReadLine-Verlauf, Prozess-Befehlszeilen) | behoben (Entscheidung von Niko 16.11.2026): `SENSITIVE_READ` erfasst Eingabeverlauf (PSReadLine, `Get-History`), Befehlszeilen und Startdaten von Prozessen, die Ordner `.wamo*` im Benutzerordner, Schlüsseldateien (`.key`, `.p12`, `.ppk`), Browser-Passwörter (`logins.json`, `key4.db`, `Local State`, `Web Data`), Windows-Tresor (`Protect`, `Vault`), WireGuard, Wörter wie `secret`, `token`, `api_key` und die Registry-Dateien des Benutzers; Tests `test_heikle_lesepfade_brauchen_eine_karte` und Gegenprobe; wirkt mit Installer 0.4.1 |
| 4 | MEDIUM | Klickziel und Canvas-Inhalt werden erst nach dem Ja gesucht beziehungsweise gelesen | offen; der Host prüft Mail- und Messenger-Fenster weiter selbst |
| 5 | MEDIUM | Bildschirmbild und Boss-Bild gehen an das Bildmodell ohne eigene Einwilligung | offen, Entscheidung für Niko (Schalter am Server oder Einwilligung am Laptop, AVV) |
| 6 bis 9 | LOW | Doppelklick aus einem Text, Stufenprüfung des Hosts beim Live-Bild fast wirkungslos, parallele Aufrufe vor dem Vormerken, Absenderkonto in actions bei Mail | Doppelklick behoben (`is True`), Rest offen |

## 12. Neue Namen (passend zum Namensvertrag in `CLAUDE.md`)

| Bereich | Name |
| --- | --- |
| Konto-Ebene | Schema `wamo_auth` (eigenes SQL mit Rückweg und Test unter `infra/sokrates2/supabase-wamo/`, Skript `wamo-auth-einrichten.sh`), Tabellen `wamo_auth.erstanmeldungen` und `wamo_auth.bestaetigungscodes` (nur Zweig B), Funktionen `wamo_auth.erstanmeldung_stand(uuid)`, `wamo_auth.erstanmeldung_begonnen(uuid)`, `wamo_auth.erstanmeldung_code(uuid)` (nur Zweig B), Trigger auf `auth.users` für das Passwort, Hook-Funktion `mail_hook` (nur Zweig B). Gebaut (P1a, Zweig A): Tabelle `wamo_auth.erstanmeldungen`, Funktionen `erstanmeldung_stand`, `erstanmeldung_begonnen`, `erstanmeldung_anlegen`, `erstanmeldung_uebersicht`, `hinweis_senden`, `hash_von`, Trigger `wamo_auth_passwort_geaendert` mit Funktion `passwort_geaendert` |
| Datenbank je Schema | Migration `0021_profil_freischaltung` (Trigger auf `<schema>.profiles`, mit `.down.sql`, Test `supabase/tests/0021_profil_freischaltung_test.sql`) |
| GoTrue | `GOTRUE_PASSWORD_MIN_LENGTH=12`, `GOTRUE_MAILER_OTP_EXP=300` und Send-Email-Hook (nur Zweig B) in `infra/sokrates2/supabase-wamo/docker-compose.wamo-sitzungen.yml` |
| Kern, Module | `voice-core/erstanmeldung_api.py`, `voice-core/verteilung_api.py`, `voice-core/einrichtung_api.py`, `voice-core/rechte.py` |
| Kern, Routen | `GET /wamo/api/erstanmeldung`, `POST /wamo/api/erstanmeldung/passwort` (Zweig A mit Sperre in Caddy, 6.2), `GET /wamo/api/installer`, `GET /wamo/api/installer/datei`, `GET /wamo/api/einrichtung/stand` |
| Kern, Codes | `passwort_wechsel_noetig`, `startpasswort_abgelaufen`; Aktion `installer_download` in `actions`; Quelle `haus` in `entwicklung_quelle` |
| Kern, Umgebung | `WAMO_PC_MITGLIEDER_PROFILE` (neu in der Erlaubnisliste von `wamo-core-env`, ersetzt `WAMO_PC_MITGLIEDER`), im Drop-in `WAMO_ENTWICKLUNG_MITGLIEDER` und `WAMO_ENTWICKLUNG_HAUS`; Liste `LLM_TOOLS_MITGLIED` in `voice-core/pc_host.py` (seit 16.11.2026 entfallen, Mitglieder bekommen `LLM_TOOLS`); `SCHRANKEN_VERSION = 2` |
| Server | Ablage `/var/lib/wamo-verteilung` (`aktuell.json`, `aktuell.json.sig`), Skript `wamo-verteilung-einrichten.sh`, Proxy `wamo-haus-proxy` (eigener Benutzer, Dienst, TCP-Port auf Loopback), Projektnamen `kern-<kennung>-<Name>` |
| Skripte am PC | `scripts/wamo_installer_sokrates2.py`, `scripts/wamo-dist-signieren.cjs`, `wamo_nutzer.py` mit `freischalten`, `zuruecksetzen`, `umbenennen`, `sperren --schema`, `austreten`, `passwort` (Option Ü) |
| Oberfläche und App | Abschnitt `start` ("Erste Schritte") in den Einstellungen, `ui/src/lib/erstanmeldung.ts`, `ui/src/lib/einrichtung.ts`, Brücke `window.wamoDesktop.version` und `update` |
| Zweig | `docs/ausrollen-plan` (dieses Papier), später `feat/ausrollen-p1a` bis `feat/ausrollen-p7` |

---

WAMOCON GmbH, Mergenthalerallee 79-81, 65760 Eschborn
