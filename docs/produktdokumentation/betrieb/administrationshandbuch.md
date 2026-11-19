# Administrationshandbuch

| | |
|---|---|
| Zweck | Führt Administratorinnen und Administratoren Schritt für Schritt durch die wiederkehrenden Aufgaben: Nutzer, Geräte, Zugänge, Schalter, Freischaltungen, Labor, Installer. |
| Zielgruppe | Personen mit der Rolle `admin` und Zugang zu Sokrates-2 (SSH-Alias `wamo-sokrates2`, Benutzer `wamocon`) |
| Dokumentart | Anleitung |
| Stand | 19.11.2026, geprüft gegen Commit 497e3ce |
| Quellen | `README.md`, `scripts/wamo_nutzer.py`, `voice-core/wamo_admin.py`, `scripts/wamo_labor.py`, `docs/ausrollen-neue-nutzer.md`, `docs/persoenliche-zugaenge.md`, `docs/jira-benutzer-einrichten.md`, `infra/sokrates2/README.md`, `infra/sokrates2/wamo-job-kern-einrichten.sh`, `infra/sokrates2/wamo_core_env.py` |

## 0. Vor dem Start

**Was Sie brauchen**

- Ein Admin-Profil in W.A.I.S. mit zweitem Faktor und SSH-Zugang `wamo-sokrates2` (Dienstkonto `wamocon` mit sudo) auf dem Server.
- Das Repo auf dem eigenen PC, Python mit der Umgebung von `voice-core/` (`uv`), Git Bash oder PowerShell.
- Für `wamo_admin.py` und `wamo_labor.py` die Anmeldung der Datenbankrolle `wamo_admin` in `WAMO_ADMIN_DATABASE_URL` (Umgebung oder `.env`), eingerichtet mit `python scripts/wamo_db_rolle.py --rolle wamo_admin`. Fehlt sie, brechen diese beiden Skripte vor dem ersten Serveraufruf ab. `wamo_nutzer.py` braucht sie nicht, es arbeitet über `ssh` auf dem Server.

**Grundregeln (aus `CLAUDE.md` und der Server-README)**

1. Skripte vom Server zuerst mit `--trocken` aufrufen.
2. Skripte liegen auf dem Server in `~/wamo-infra`, nie in `/tmp` (Betriebshandbuch, Abschnitt 1).
3. Passwörter, Token und Schlüssel nie in Befehlszeilen, Chats oder Dateien im Repo. Werte gehen nur über stdin oder verdeckte Eingabe.
4. Alle ändernden Befehle von `wamo_nutzer.py` verlangen `--schema` ausdrücklich. Das Betriebsschema nennt `WAMO_DB_SCHEMA` im Kern (Schemas laut Namensvertrag: `wamo_dev`, `wamo_test`, `wamo_prod`).
5. Einstellungen am Kern wirken erst mit dem nächsten Kern-Release (`wamo-core-slots.sh umschalten-kern`). Nie `systemctl restart wamo-core`.
6. Laborkonten und Laborprofile fasst `wamo_nutzer.py` nicht an. Dafür gibt es `scripts/wamo_labor.py` (Abschnitt 15).

**Rollen im Überblick** (Details: [../fachlich/rollen-und-rechte.md](../fachlich/rollen-und-rechte.md))

| Rolle | Merkmal |
| --- | --- |
| `admin` | Server-Verwaltung in der Oberfläche (Geräte, Gedächtnis, Neue Mitglieder, Fernzugriff), PC-Steuerung und Entwicklungsaufträge |
| `mitglied` | PC-Steuerung und Entwicklungsaufträge nur mit Freischaltung je Person (Abschnitte 10 und 11) |
| Laborprofil (`labor_art`, Kennung `labor-01` bis `labor-16`, `labor-schau`) | hat immer die Rolle `mitglied`, bleibt dauerhaft `aktiv = false` und wird nur über `labor_aktiv` freigeschaltet; bekommt keine der Mitglieder-Funktionen |

## 1. Neuen Nutzer anlegen und freischalten

Ein Konto gilt für alle Schemas (`auth.users`), das Profil gehört zu einem Schema. Das Skript läuft lokal und führt über `ssh` auf dem Server aus; der Service-Schlüssel von Supabase bleibt dort.

**Vorbereitung (vor dem Übergabetag)**

1. Konto und inaktives Profil anlegen. Das Konto bekommt ein Zufallspasswort, das niemand kennt, und wird sofort in GoTrue gesperrt:

   ```bash
   python scripts/wamo_nutzer.py anlegen --email vorname.nachname@wamocon.com --name "Vorname Nachname" --rolle mitglied --anrede du --schema <Betriebsschema>
   ```

   Der Anzeigename ist der volle Name. Rolle `admin` oder `mitglied`, Anrede `du` oder `sie`.
2. Kontrolle: `python scripts/wamo_nutzer.py liste --schema <Betriebsschema>` zeigt Rolle, Aktivstand, Stand der Erstanmeldung, Frist, Zahl der bestätigten zweiten Faktoren und die Sperre in GoTrue.

**Übergabetag** (im eigenen Terminal, nie über eine Pipe)

3. Startpasswort ausdenken oder aus dem Passwortmanager nehmen: mindestens 12 Zeichen, mindestens 6 verschiedene Zeichen. Es steht nur auf dem Willkommensblatt.
4. Freischalten:

   ```bash
   python scripts/wamo_nutzer.py freischalten --email vorname.nachname@wamocon.com --schema <Betriebsschema> [--frist-stunden 72]
   ```

   Das Skript fragt das Passwort verdeckt zweimal ab und arbeitet feste Schritte ab: Konto sperren, vorläufiger Merker der Erstanmeldung, Sitzungen und einmalige Token löschen, zweite Faktoren prüfen, Startpasswort setzen, Merker endgültig schreiben (Frist 72 Stunden, einstellbar von 1 bis 168), Profil aktivieren, Sperre aufheben. Bei einem Fehler bricht es mit dem Namen des Schritts ab und das Konto bleibt gesperrt.
5. Gibt es noch zweite Faktoren, bricht es ab. Nur wenn die Einrichtung wirklich verworfen werden soll: `--faktoren-loeschen`.
6. Option Ü ("Person tippt selbst"): `python scripts/wamo_nutzer.py passwort --email ... --schema ...`. Die Person tippt ihr Passwort am Platz verdeckt ein, der Merker steht danach auf erledigt.
7. Die Person meldet sich in der Oberfläche an, richtet den zweiten Faktor ein, wechselt das Startpasswort (Pflicht innerhalb der Frist, sonst Stand `abgelaufen`) und folgt den Schritten unter "Erste Schritte" bis zum Installer ([benutzerhandbuch.md](../nutzung/benutzerhandbuch.md)).

Voraussetzungen für den Ablauf auf der Serverseite: Schema `wamo_auth` ist eingerichtet (`bash ~/wamo-infra/wamo-auth-einrichten.sh einrichten`), GoTrue hat `GOTRUE_PASSWORD_MIN_LENGTH=12`. Quelle: `docs/ausrollen-neue-nutzer.md` 4.1.

## 2. Einrichtungsstand neuer Mitglieder prüfen

1. Menü: Einstellungen, "Neue Mitglieder" (nur Admins).
2. Je Profil der letzten 90 Tage (ohne Laborprofile) zeigt die Übersicht als Datum, nie als Uhrzeit: angemeldet, zweiter Faktor, Passwort gewechselt, Laptop eingerichtet, Stimmabdruck, Modellzugang als Art (eigener Token, eigener Schlüssel, Hausmodelle) und einen Satz zum nächsten Schritt.
3. Die Daten kommen aus der Funktion `<schema>.neue_mitglieder(p_admin)` (Migration `0022`), sie liefert nie E-Mail, Schlüssel, Token oder Stimmvektor. Route `GET /wamo/api/admin/neue-mitglieder`, 30 Abrufe je Minute.
4. Dieselbe Seite enthält den Block "Rechte der GitHub-Zugänge" (Abschnitt 14.3).

## 3. Passwort oder zweiten Faktor zurücksetzen

1. Verlorenes Handy oder vergessenes Passwort: im eigenen Terminal `python scripts/wamo_nutzer.py zuruecksetzen --email ... --schema ... [--frist-stunden 72]`. Es löscht die zweiten Faktoren immer, setzt ein neues Startpasswort und schreibt den Merker neu (wie in Abschnitt 1).
2. Danach meldet sich die Person neu an, richtet den Faktor erneut ein und wechselt das Passwort.
3. Hinweis: Passwortwechsel verlangt in GoTrue die erneute Anmeldung (`GOTRUE_SECURITY_UPDATE_PASSWORD_REQUIRE_REAUTHENTICATION`, laut `infra/sokrates2/README.md` Abschnitt 11).

## 4. Anzeigename und Rolle ändern

1. Nur den Namen: `python scripts/wamo_nutzer.py umbenennen --email ... --name "Vorname Nachname" --schema ...` (1 bis 60 Zeichen, ändert nie `aktiv`).
2. Rolle oder Anrede ändern: Laut Kopfkommentar von `scripts/wamo_nutzer.py` ändert ein zweiter Lauf von `anlegen` bei einem vorhandenen Konto nur Anzeigename, Rolle und Anrede und nie Passwort, Sperre oder `aktiv`. Ein eigener Befehl dafür steht nicht im Skript. Vorher in `liste` prüfen.
3. Zur Kontrolle ohne Konto-Zugriff: `cd voice-core && uv run python wamo_admin.py profile` listet alle Profile.

## 5. Nutzer sperren oder austragen

1. Sperren (Profil `aktiv = false`, Konto in GoTrue gesperrt, Sitzungen gelöscht): `python scripts/wamo_nutzer.py sperren --schema ... --email ...`.
2. Alle Konten mit offener oder abgelaufener Erstanmeldung auf einmal (Rückweg des Ausrollens): `python scripts/wamo_nutzer.py sperren --schema ... --offene`. Scheitert ein Konto, geht es mit den übrigen weiter, am Ende nennt das Skript die gescheiterten E-Mails (Exit 1).
3. Austritt: `python scripts/wamo_nutzer.py austreten --email ... --schema ...`. Erst abriegeln, dann Faktoren löschen, eigene Geräte widerrufen, Claude-Schlüssel und Claude-Code-Token löschen.
4. `wamo_nutzer.py` löscht weder Konto noch Profil, Stimmabdruck, Gedächtnis oder Verlauf. Löscht jemand ein Konto in `auth.users` von Hand, gehen die zugehörigen Zeilen über `on delete cascade` mit (`supabase/migrations/0001_wamo_init.sql`). Das Löschkonzept steht im [Sicherheits- und Datenschutzdokument](../sicherheit/sicherheit-und-datenschutz.md).
5. Jede Aktion schreibt eine Zeile ins Journal: `journalctl -t wamo-nutzer` auf dem Server (nie ein Passwort).

## 6. Geräte und Tunnel verwalten

Jeder persönliche Laptop hat ein eigenes Gerät im Register, einen Schlüssel und einen Tunnelplatz (`wamo-t-01` bis `wamo-t-64`). Die Desktop-App bindet das Gerät bei der Anmeldung. Ein Mitglied ohne früheres Gerät wird sofort `aktiv`. Jedes Admin-Profil und jeder Gerätewechsel steht auf `beantragt`, bis ein Admin entscheidet.

**Gerät freigeben oder ablehnen**

1. Menü: Einstellungen, "Geräte und PC", Karte "Geräteverwaltung" (nur Admins). Wartende Geräte stehen oben mit Kennung, Rechnername, Profil und Fingerabdruck in Vierergruppen.
2. Aktion wählen: freigeben, ablehnen oder widerrufen (endgültig, Grund Pflicht), sperren (Grund Pflicht), entsperren.
3. Im Dialog den Fingerabdruck mit dem Fingerabdruck am Laptop vergleichen und den Vergleich ausdrücklich bestätigen (Freigeben und Entsperren).
4. Den Code der Authenticator-App eingeben. Der Kern nimmt ändernde Aktionen nur an, wenn der letzte TOTP-Zeitstempel höchstens 120 Sekunden alt ist.
5. Die Freigabe meldet sich bei allen Admins als Hinweis. Der Verlauf steht in `device_events`.

**Tunnel prüfen**

6. Auf dem Server: `journalctl -u wamo-pc-abgleich -u wamo-pc-streuner --since -1h | grep WAMO-GERAET`. Der Abgleich läuft alle 10 Sekunden, der Streuner alle 5 Minuten.
7. Laptop-Seite: geplante Aufgabe "WAMO Tunnel", Herzschlag in `%LOCALAPPDATA%\WAMO\tunnel.status`, Logs in `%LOCALAPPDATA%\WAMO\logs`.
8. Rückweg für einen Laptop: Gerät sperren oder widerrufen. Danach nimmt der Abgleich den Schlüssel binnen Sekunden weg.

Gemeinsame Geräte (Drucker, Scanner und Ähnliches) und Notfälle ohne Oberfläche laufen über `wamo_admin` (SQL), siehe `README.md`, Abschnitt "Geräte, Tunnel je Gerät und Geräteverwaltung".

## 7. Modelle und Zugänge je Profil

Jedes Profil hat genau einen von zwei Modellzugängen: eigener Claude-Schlüssel oder nur Hausmodelle (`voice-core/modellzugang.py`, Tabelle `model_access`). Die Person pflegt ihre Zugänge selbst in der Karte "Modellzugang". Der Admin steuert nur Vorgaben.

1. Überblick: `cd voice-core && uv run python wamo_admin.py modellzugang` (zeigt Art, nie den Schlüssel, nur die letzten vier Zeichen).
2. Profil auf Hausmodelle festlegen: `uv run python wamo_admin.py modellzugang-setzen --user-id <uuid> --nur-haus an`. Ein Trigger löscht dabei den Schlüssel, die Verwaltung kann nie einen setzen oder lesen. Zurück: `--nur-haus aus`.
3. Claude-Modell eines Profils vorgeben: `--modell claude-haiku-5-5` (Standard Haiku).
4. Stimme im Haus erzwingen: `--stt haus --tts haus` (Soniox bleibt Standard, die Person kann in der Karte selbst wählen, Migration `0023`).
5. Voraussetzung "Im Haus": am Kern `WAMO_STT_HAUS_MODELL`, `WAMO_TTS_HAUS_MODELL`, `WAMO_TTS_HAUS_STIMME` und die Einträge im Gateway (Betriebsnotiz `infra/sokrates1/gateway-wamo.md`), sonst Rückfall auf Soniox mit Grund in der Oberfläche.
6. Für Entwicklungsaufträge nutzt W.A.I.S. zuerst den Claude-Code-Token der Person (`sk-ant-oat...`, Sonnet), dann ihren API-Schlüssel (Haiku), ohne beides auf Wunsch Hausmodelle (Abschnitt 11).
7. Der Serverzugang aus `/etc/wamo/geheim.env` ist nur ein Rückfall für ein Profil. Haben alle Profile eigene Zugänge, dort `WAMO_SERVERZUGANG=aus` setzen (kein Neustart nötig).
8. Der Schlüssel in `ANTHROPIC_API_KEY` der Kern-Umgebung gehört einer Person und gilt nur für das Profil in `WAMO_CLAUDE_SCHLUESSEL_PROFIL`. Besser ist, ihn mit `uv run python modellzugang.py hinterlegen --user-id <uuid>` abzulegen und die Variable zu entfernen.

## 8. Kontingente und Grenzen

| Wo | Was | Einstellen |
| --- | --- | --- |
| Einstellungen, "Verbrauch" (nur Admin) | zeigt das Kontingent des Max-Abos (Sitzungslimit, Wochenlimit, modellbezogenes Limit) aus dem Lauf des Profils; Datenformat laut README noch an keinem echten Token bestätigt | nur Anzeige |
| Entwicklungsaufträge, Kosten | `--kosten-auftrag` und `--kosten-tag` (US-Dollar), im Büro Pflicht; fehlend heißt aus | `wamo-job-kern-einrichten.sh schalter ...` (Abschnitt 11) |
| Entwicklungsaufträge, Kanal | `--max-start-stunde`, `--max-start-tag`, `--max-laufzeit-tag-s`, `--max-versuch-stunde`, je Profil `--max-neu-stunde-profil`, `--max-neu-tag-profil`, `--max-versuch-stunde-profil`, `--max-laufzeit-tag-s-profil` | `wamo-job-kern-einrichten.sh kanal ...` |
| Gleichzeitige Aufträge | `--max-parallel` (1 bis 6, Standard 6), `--max-parallel-profil` (1 bis 6, Standard 3) | `kanal --max-parallel N --max-parallel-profil N`; 1 und 1 heißt einer gleichzeitig |
| GitHub-Einreichungen | `--max-einreichen-tag` (Standard 10), `--max-einreichen-tag-profil` (Standard 5), `--max-klon-mb` (Standard 2048) | `kanal --persoenlich an ...` |
| Haus-Proxy | Token je Lauf, je Profil und Tag, je Tag; höchstens zwei gleichzeitige Anfragen | `/etc/wamo-haus-proxy/proxy.env` (`TAG_TOKEN_MAX`, `PARALLEL`) |
| Fernzugriff | 60 Minuten je Sitzung, 10 Minuten Leerlauf, höchstens 3 Sitzungen gleichzeitig, 6 Starts je Stunde und Profil | fest im Code, Anmeldealter über `WAMO_RD_ANMELDUNG_MAX_MIN` |

Ein bestehendes `kernkanal.conf` behält seine Werte, bis `kanal` sie ändert. Ein Aufruf von `kanal --arten ...` ersetzt Arten, Repos und Dienste vollständig. Quelle: `infra/sokrates2/README.md` 18.1 bis 18.3.

## 9. Schalter am Kern setzen

Alle Einstellungen des Kerns stehen in `/etc/wamo/core.env` (root:wamo-core 0640) und werden nur über das Hilfsprogramm geändert. Es hat eine Allowlist der Namen, schreibt atomar und zeigt nie Werte.

1. Namen ansehen: `ssh wamo-sokrates2 "sudo -n /usr/local/sbin/wamo-core-env liste"`.
2. Wert setzen (stdin, nie in der Befehlszeile):

   ```bash
   printf 'NAME=Wert\n' | ssh wamo-sokrates2 "sudo -n /usr/local/sbin/wamo-core-env setzen"
   ```

3. Wert entfernen: `ssh wamo-sokrates2 "sudo -n /usr/local/sbin/wamo-core-env loeschen NAME"`.
4. Pflichtwerte prüfen: `... wamo-core-env pruefen` (Exit 0, wenn alle gesetzt sind: `SONIOX_API_KEY`, `SUPABASE_PUBLISHABLE_KEY`, `WAMO_DATABASE_URL`).
5. Wirksam machen: neues Kern-Release über die Slots (`wamo-core-slots.sh release`, `umschalten-kern`, `bewaehren 30`, `ausleiten`, siehe [release-und-ausrollen.md](release-und-ausrollen.md)).

Was die Unit festlegt (Betriebsart, Sockets, `SUPABASE_URL`, CA, `WAMO_ENTWICKLUNG=aus`) lässt sich hier nicht überschreiben. Schalter der Entwicklungsaufträge (`WAMO_ENTWICKLUNG_*`) sind nicht in der Allowlist und stehen im Drop-in (Abschnitt 11). Eine vollständige Liste der Umgebungsvariablen steht in [../technik/konfiguration.md](../technik/konfiguration.md).

Häufige Schalter (Name, Standard, Quelle):

| Name | Zweck | Quelle |
| --- | --- | --- |
| `WAMO_PC_MITGLIEDER_PROFILE` | PC-Steuerung für Mitglieder, Liste von `user_id`, Standard leer | `voice-core/rechte.py` |
| `WAMO_OFFICE` | Liste aus `dateien`, `outlook`, `teams`, `onenote`; Standard leer (aus) | `CLAUDE.md` |
| `WAMO_JIRA` und `WAMO_JIRA_*` | Jira-Stories (Abschnitt 14.1) | `docs/jira-benutzer-einrichten.md` |
| `WAMO_RD_AKTIV` | Fernzugriff (`ja`), erst nach `wamo-rd-einrichten.sh` | `README.md` Fernzugriff |
| `WAMO_STIMME_PRUEFUNG` | Prüfmodus der Stimme: `aus`, `beobachten` (Standard seit 18.11.2026, die Stimme sperrt nichts) oder `streng` (nur auf ausdrücklichen Wunsch) | `voice-core/stimme_gate.py`, `CLAUDE.md` |
| `WAMO_STIMME_SCHATTEN`, `WAMO_STIMME_NUR_EIGEN`, `WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN` | Stimmwächter (die beiden letzten gelten nur im Modus `streng`) | `CLAUDE.md` |
| `WAMO_TTS_HAUS_STREAM` | gestreamte Sprachausgabe im Haus, `an` oder `aus` | `CLAUDE.md` |
| `WAMO_LABOR_URL`, `WAMO_LABOR_TOKEN`, `WAMO_LABOR_DATEN` | Labor-Dienst und Labor-Daten | `CLAUDE.md` |

## 10. PC-Steuerung für ein Mitglied freischalten

Seit dem 16.11.2026 bekommt ein freigeschaltetes Mitglied für den eigenen Laptop dieselben PC-Werkzeuge wie Admins (laut `voice-core/rechte.py`). Gesprochene PC-Befehle gehen nur mit eingelerntem Stimmabdruck, sonst nur getippt. Laborprofile nie.

1. Das Gerät der Person ist in der Geräteverwaltung `aktiv` (Abschnitt 6).
2. `user_id` der Person nachschlagen (`wamo_admin.py profile` oder `wamo_nutzer.py liste`).
3. Liste setzen (alle Personen in einer Liste, durch Komma getrennt, höchstens 64):

   ```bash
   printf 'WAMO_PC_MITGLIEDER_PROFILE=%s\n' '<user_id>[,<user_id>]' | ssh wamo-sokrates2 "sudo -n /usr/local/sbin/wamo-core-env setzen"
   ```

   Ein einziger ungültiger Eintrag macht die ganze Liste ungültig (niemand, eine Zeile im Journal).
4. Neues Kern-Release (Abschnitt 9, Punkt 5). Erst danach gilt die Freischaltung.
5. Prüfen: Die Statusleiste der Person zeigt die PC-Steuerung, in "Neue Mitglieder" steht der Stand. Office-Werkzeuge nur zusätzlich mit `WAMO_OFFICE`.
6. Notaus je Person: Gerät sperren, dann die Liste ohne die Person setzen (oder `wamo-core-env loeschen WAMO_PC_MITGLIEDER_PROFILE` für alle) und Kern-Release.
7. Ablehnungen stehen mit Präfix `WAMO-GERAET` im Journal.

## 11. Entwicklungsaufträge freischalten

Entwicklungsaufträge starten im Büro über den Kern-Kanal des Dispatchers. Alles ist standardmäßig aus. Der Kanal und der Kern haben ein Versionspaar (heute Dispatcher 10 und Kern ab `SCHRANKEN_VERSION` 4 für den GitHub-Weg); `schalter an` prüft das. Alle Schritte nur bei Ruhe (kein laufender Auftrag) und als root über `ssh wamo-sokrates2`.

1. Voraussetzung: `wamo-einrichten.sh` lief (Benutzer `wamo`, Claude Code, ECC, REA). Dispatcher einrichten (einmalig, mit Totmannschalter): `sudo bash ~/wamo-infra/wamo-job-einrichten.sh`, danach binnen 5 Minuten über eine neue Verbindung `sudo touch /run/wamo-sshd-bestaetigt`. Rauchtest: `sudo -u wamo -H /opt/wamo/bin/wamo-job-rauchtest --mcp --attrappe`.
2. Schlüssel und Regeln anlegen: `sudo bash ~/wamo-infra/wamo-job-kern-einrichten.sh schluessel --trocken`, dann `schluessel --ablauf <JJJJMMTT> --hostfingerabdruck <SHA256:...>`. Den Fingerabdruck des Hostschlüssels vergleicht das Skript. Der Kanal bleibt zu.
3. Rauchtest: `sudo /opt/wamo-core/bin/wamo-job-kern-rauchtest --produktiv`. Alle Proben sind nur am Server prüfbar.
4. Kanal öffnen: `sudo bash ~/wamo-infra/wamo-job-kern-einrichten.sh kanal --arten recherche [--repos <owner>/<name>] [--max-start-stunde 12 --max-start-tag 40 --max-laufzeit-tag-s 28800 --max-versuch-stunde 60 --max-parallel 6 --max-parallel-profil 3]` (Beispielwerte aus `infra/sokrates2/README.md` 18.2). Schließen: `kanal zu`.
5. Schalter im Kern setzen (schreibt das Drop-in, schaltet über `umschalten-kern` um):

   ```bash
   sudo bash ~/wamo-infra/wamo-job-kern-einrichten.sh schalter an <release> --profil <user_id>[,<user_id>] \
     --kosten-auftrag 3 --kosten-tag 10 --mitglieder an --haus an --github an --trocken
   ```

   Ohne `--trocken` ausführen, wenn die Ausgabe stimmt. Jeder Aufruf ohne eine Option schreibt diese Option als aus. `--mitglieder an` lässt auch Mitglieder aus `--profil` zu (Laborprofile nie), `--haus an` Hausmodelle (zusätzlich `WAMO_HAUS=an` in `/etc/wamo/geheim.env` und der Haus-Proxy, Abschnitt 12), `--github an` den persönlichen GitHub-Weg (zusätzlich `kanal --persoenlich an`). Die Zahlen 3 und 10 sind die Beispiele aus der README.
6. Danach `wamo-core-slots.sh bewaehren 30` und `ausleiten` (das Skript `schalter` ruft `umschalten-kern` selbst auf).
7. Zustand: `sudo bash ~/wamo-infra/wamo-job-kern-einrichten.sh status` (Resttage des Schlüssels, Kanalzustand, Schalter je Slot, laufende Kern-Aufträge).
8. Schlüssel verlängern (er läuft nach `ABLAUF` ab, höchstens 400 Tage voraus): `schluessel --ablauf <JJJJMMTT> --hostfingerabdruck <SHA256:...>`.
9. **Notaus:** `sudo bash ~/wamo-infra/wamo-job-kern-rueckweg.sh notaus` (Details im [Betriebshandbuch](betriebshandbuch.md), Abschnitt 12).

Voraussetzung je Person: eigener Claude-Zugang oder (mit `--haus an`) Hausmodelle, Zulassung über `--profil` (die Liste landet in `WAMO_ENTWICKLUNG_PROFILE`). Mitglieder bekommen keine Repos, solange keine Liste je Person festgelegt ist (laut Abschnitt 18.1). Quelle: `infra/sokrates2/README.md` 18 bis 18.3, `CLAUDE.md`.

## 12. Haus-Proxy für Aufträge mit Hausmodellen

1. Proxy einrichten: `sudo bash ~/wamo-infra/wamo-haus-proxy-einrichten.sh einrichten --trocken`, dann ohne `--trocken`.
2. Schlüssel für LiteLLM verdeckt eingeben: `sudo bash ~/wamo-infra/wamo-haus-proxy-einrichten.sh schluessel` (nur über stdin).
3. Zustand: `... status`. Rauchtest: `wamo_haus_proxy_rauchtest.py --nur-attrappe` bzw. `--echt`.
4. Schalter im Dispatcher: `WAMO_HAUS=an` in `/etc/wamo/geheim.env` (ein Tippfehler im Namen sperrt), dann Abschnitt 11 mit `--haus an`.
5. Rückweg: Proxy stoppen (Aufträge mit Hausmodellen scheitern geschlossen), `--haus` weglassen. Vollständig: `wamo-haus-proxy-rueckweg.sh --entfernen`.

## 13. Gedächtnis-Vorschläge entscheiden

Gemeinsame Gedächtnis-Einträge wirken erst nach Freigabe durch einen Admin. Persönliche Einträge gehören nur der Person.

1. Menü: Einstellungen, "Gedächtnis" (nur Admins). Offene Vorschläge zeigen vollen Text, Art, Autor und Zeit.
2. "Für alle freigeben" oder "Ablehnen" wählen (gleich gewichtet). Ein freigegebener Eintrag gilt in allen Sitzungen, die danach beginnen.
3. Alternativ auf der Kommandozeile: `cd voice-core && uv run python wamo_admin.py vorschlaege`, dann `freigeben <id> --admin <uuid>` oder `ablehnen <id> --admin <uuid>`.
4. Die Entscheidung läuft über die Datenbankfunktion `gedaechtnis_vorschlag_entscheiden`, die den Admin noch einmal prüft (Migration `0020`).

## 14. Jira-Stories und GitHub-Zugänge

### 14.1 Jira: User Stories aus dem Canvas

Dafür braucht der Kern einen eigenen technischen Jira-Benutzer nur für W.A.I.S. mit zwei Rechten: "Browse Projects" und "Create Issues". Die vollständige Anleitung mit Platzhaltern steht in [../../jira-benutzer-einrichten.md](../../jira-benutzer-einrichten.md). Kurzfassung:

1. Benutzer in der Atlassian-Verwaltung anlegen (eigene Funktionsadresse, nur Produkt Jira mit Rolle "Benutzer", Zwei-Faktor-Anmeldung).
2. Rolle `W.A.I.S.` in den Projektrollen anlegen und im Berechtigungsschema von `WMCNL` genau diese zwei Rechte geben; mit dem Berechtigungshelfer prüfen, dass Bearbeiten, Löschen, Zuweisen, Kommentieren und Administrieren "Nein" ergeben.
3. Als dieser Benutzer ein klassisches API-Token mit Ablauf (höchstens ein Jahr) erzeugen und nur über stdin setzen: `WAMO_JIRA=aus`, `WAMO_JIRA_URL`, `WAMO_JIRA_EMAIL`, `WAMO_JIRA_TOKEN`, `WAMO_JIRA_PROJEKTE`, `WAMO_JIRA_STANDARD_PROJEKT` (Abschnitt 9).
4. Ausgang des Kerns zu `wamocon.atlassian.net` prüfen, dann `WAMO_JIRA=an` und ein Kern-Release.
5. Rauchtest mit einem Canvas-Dokument ("Als User Story in Jira", Karte "Jira-Story freigeben").
6. Widerruf: Token des technischen Benutzers widerrufen oder den Benutzer deaktivieren, danach `WAMO_JIRA=aus` und `wamo-core-env loeschen WAMO_JIRA_TOKEN WAMO_JIRA_EMAIL`, Kern-Release.

Das ist getrennt vom Lese-Zugang der Entwicklungsaufträge (`JIRA_EMAIL`, `JIRA_API_KEY` in `/etc/wamo/geheim.env`, nur lesend).

### 14.2 GitHub-App für Entwicklungsaufträge (Server)

1. In GitHub für die App nur diese Repository-Rechte setzen: Contents Read and write, Pull requests Read and write, Metadata Read-only; alle anderen Rechte auf "No access".
2. Bei der Installation "Only select repositories" wählen und nur die Repos nennen, an denen Aufträge arbeiten dürfen. Das W.A.I.S.-Repo selbst gehört nicht dazu.
3. Privaten Schlüssel der App auf dem Server nach `/etc/wamo/` legen (Datei `root:wamo 0640`), die App-ID und die Installations-ID als `WAMO_GH_APP_ID`, `WAMO_GH_APP_INSTALLATION_ID` und `WAMO_GH_APP_SCHLUESSEL` in `/etc/wamo/geheim.env` eintragen (nur alle drei zusammen, sonst startet kein Auftrag mit GitHub).
4. Prüfen: `sudo -u wamo -H /opt/wamo/bin/wamo-job-dispatch ping` muss `"github": "app"` melden. Rauchtest `wamo-job-rauchtest --mcp --attrappe --app-echt` (nur lesend).
5. Persönliche Token (`GH_TOKEN`, `GH_TOKEN_LESEN`) aus `geheim.env` entfernen und in GitHub widerrufen.
6. Zum Schutz der Zielrepos empfiehlt die README ein Ruleset für den Standardbranch (kein direkter Push, Pull Request Pflicht, Genehmigung durch einen Menschen). Einzelheiten und Voraussetzungen: `infra/sokrates2/README.md`, Abschnitt "GitHub-App einrichten".

### 14.3 Persönliche GitHub-Zugänge der Personen (Plan C)

Jede Person hinterlegt in den Einstellungen unter "GitHub-Zugang" ein eigenes Token (fein granular `github_pat_` oder klassisch `ghp_`, Ablauf höchstens 366 Tage). Der Kern prüft Konto, Ablauf und Scopes beim Speichern und zeigt danach nur Konto, Art und Ablauf.

1. Scopes über die strenge Liste hinaus stellt der Admin je Person ein: Einstellungen, "Neue Mitglieder", Block "Rechte der GitHub-Zugänge".
2. Server einschalten (einmalig, laut `infra/sokrates2/README.md` 18.3): `wamo-job-einrichten.sh` (Dispatcher 10), Rauchtest `wamo-job-rauchtest --persoenlich`, `wamo-job-kern-einrichten.sh kanal --persoenlich an`, Kern-Release mit `schalter an ... --github an` (Abschnitt 11).
3. Ablauf je Auftrag: Das Token geht nur kurz über stdin an den Dispatcher. Die Sandbox arbeitet ohne Token und committet lokal. Erst der Klick auf "Einreichen" pusht genau `refs/heads/wamo/<job>` und öffnet den Pull Request. Gemergt wird nie durch W.A.I.S.
4. Rückweg: `kanal --persoenlich aus` (neue Aufträge mit persönlichem Weg enden mit `persoenlich_aus`, der App-Weg bleibt), im Kern `schalter an <release> ...` ohne `--github an`.
5. Kopien privater Repos löscht der Timer `wamo-job-aufraeumen.timer` täglich, sofort mit `sudo -u wamo -H /opt/wamo/bin/wamo-job-dispatch aufraeumen alle`.

## 15. Labor einrichten und löschen

Der Labortag am 28.11.2026 hat eigene Unterlagen. Dieser Abschnitt nennt nur die Verwaltungsbefehle, die Abläufe stehen im Runbook.

**Profile** (`scripts/wamo_labor.py`, Standard ist der Trockenlauf, ändern nur mit `--ausfuehren`)

1. Anlegen: `python scripts/wamo_labor.py anlegen --kennung labor-01 labor-02 labor-schau --umschlag-datei <Pfad außerhalb des Repos> --ausfuehren`. Es entstehen 24 Zeichen lange Zufallspasswörter, die nur in die Umschlag-Datei und zum Server gehen.
2. Aktivieren: `... aktivieren --kennung labor-01 --ausfuehren`. Sperren: `... sperren --alle --ausfuehren`. Stand: `... status`.
3. Löschen: erst sperren, dann die Sitzung beenden lassen, dann `... loeschen --alle --ausfuehren` (oder `--kennung ... --ab ... --bis ...`). Eine Sperrfrist von 3 Minuten nach der letzten Änderung wartet das Skript selbst ab und prüft danach auf null Zeilen.
4. Laborkonten (Anmeldung) löschen und Sitzungen widerrufen: `infra/sokrates2/wamo_labor_konten_loeschen.py`.

**Dienst und Daten am Server**

5. Labor-Dienst (Test-Jira): `sudo bash ~/wamo-infra/wamo-labor-einrichten.sh einrichten --trocken --basis-image python:3.11-slim@sha256:<Digest>`, dann echt, `status`, `pruefen` (20 Proben).
6. Adresslisten in `/etc/wamo-labor`: `betreuer-adressen`, `betreuer-geraete`, `plaetze-adressen`. Nach einer Änderung `einrichten` erneut bzw. `sudo systemctl reload wamo-firewall`.
7. Labor-Daten des Kerns (Regeln, Kontakte, Vorlagen): `sudo bash ~/wamo-infra/wamo-labor-daten-einrichten.sh einrichten [--persona standard|streng] [--trocken]`, wirksam mit dem nächsten Kern-Release.
8. Platz-Skript am Laptop: `scripts/wamo_labor_platz.py einrichten --kiosk-konto` (Anleitung `docs/labor-platz-einrichten.md`).

**Nach dem Labortag**

9. Nachlauf: `python scripts/wamo_labor_nachlauf.py nachlauf` (Trockenlauf), dann `nachlauf --ausfuehren` (frühestens am 28.11.2026): Zählung, Laborprofile sperren, Plätze des Dienstes löschen, Gesprächsdaten löschen, Zählung danach.
10. Löschlauf am Server nach der Aufbewahrung (frühestens am 12.12.2026): `sudo bash ~/wamo-infra/wamo-labor-loeschlauf.sh --bestaetigung LABOR-LOESCHEN`. Ohne das Bestätigungswort zeigt das Skript nur den Plan. Es schreibt einen Nachweis nach `/var/log/wamo-labor/loeschnachweis-<Zeit>.txt` (Namen, Größen, Zählungen, nie Inhalte).
11. Nicht in der Hand der Skripte: Snapshots und Sicherungen des Servers über den 11.12.2026 hinaus.

Weiter: [../../labor-runbook.md](../../labor-runbook.md), [../../labor-morgencheckliste.md](../../labor-morgencheckliste.md), [../../labor-platz-einrichten.md](../../labor-platz-einrichten.md), [../../labor-datenschutz-entwurf.md](../../labor-datenschutz-entwurf.md).

## 16. Installer verteilen

Ausführlich in [release-und-ausrollen.md](release-und-ausrollen.md), Abschnitt 8. Für die Administration genügt:

1. Fertigen, signierten Installer prüfen: `python scripts/wamo_installer_sokrates2.py pruefen <exe>`.
2. `python scripts/wamo_installer_sokrates2.py verteilen <exe> --trocken`, dann ohne `--trocken`.
3. `python scripts/wamo_installer_sokrates2.py status` zeigt die Ablage.
4. Zurück: `python scripts/wamo_installer_sokrates2.py rueckweg --trocken`, dann ohne `--trocken`.
5. Laborprofile bekommen keinen Download (403 `installer_labor`), je Profil höchstens drei ganze Downloads je Stunde.

## 17. Fernzugriff und Firewall-Quellen

**Remote-Desktop-Gateway** (Ziele Sokrates-1, Sokrates-2, Caesar)

1. Einrichten: `bash ~/wamo-infra/wamo-rd-einrichten.sh --trocken`, dann echt, `status`; Ziel eintragen in `/etc/wamo-rd/ziele.toml`.
2. Weitere Ziele: `infra/sparks/wamo-rd-ziel-einrichten.sh` und `wamo-rd-konto-einrichten.sh` am Ziel, danach `sudo systemctl reload wamo-firewall` und gemeinsam `docker restart wamo-rd-web wamo-rd-zugang`.
3. Einschalten: `WAMO_RD_AKTIV=ja` im Kern (Abschnitt 9) nach den Proben aus `wamo_rd_rauchtest.py`.
4. Nutzen: Einstellungen, "Fernzugriff" (nur Admin), "Verbinden". Jeder Start meldet sich als Hinweis bei allen Admins.

**Quellen für die Admin-Ports** (55446, 55322, 56543)

5. `/etc/wamo/admin-quellen` bearbeiten (eine Adresse oder ein Netz je Zeile, privater Bereich, höchstens 64 Einträge): `sudoedit /etc/wamo/admin-quellen`.
6. Prüfen: `sudo wamo-firewall start --trocken`, übernehmen mit `sudo systemctl reload wamo-firewall`.
7. Ohne Einträge gilt das ganze Büro-LAN; nur ungültige Einträge öffnen für niemanden. WireGuard-Clients der FRITZ!Box brauchen ihre Adresse ebenfalls in der Liste.

## Weiterführend

- Betrieb, Logs, Störungen: [betriebshandbuch.md](betriebshandbuch.md)
- Release, Installer, Rückwege: [release-und-ausrollen.md](release-und-ausrollen.md)
- Sicherheit und Datenschutz: [../sicherheit/sicherheit-und-datenschutz.md](../sicherheit/sicherheit-und-datenschutz.md)
- Rollen und Rechte: [../fachlich/rollen-und-rechte.md](../fachlich/rollen-und-rechte.md)
- Benutzerhandbuch (was die Person erlebt): [../nutzung/benutzerhandbuch.md](../nutzung/benutzerhandbuch.md)
- Konfiguration: [../technik/konfiguration.md](../technik/konfiguration.md)
- Planpapier Ausrollen neuer Nutzer: [../../ausrollen-neue-nutzer.md](../../ausrollen-neue-nutzer.md)
- Plan Persönliche Zugänge: [../../persoenliche-zugaenge.md](../../persoenliche-zugaenge.md)
- Begriffe: [../glossar.md](../glossar.md)
