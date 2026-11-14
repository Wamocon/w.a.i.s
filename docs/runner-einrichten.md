# Eigener GitHub-Runner auf Sokrates-2: Ausrollen in den Stufen dev, test und prod

**Stand:** 14.11.2026. **Für:** Niko, Einrichtung am Montag. **Dauer:** etwa 45 Minuten, davon 30 Minuten Bewährung beim ersten prod-Lauf.

Nach jedem Merge auf `main` laufen die Stufen dev und test von selbst. prod startet nur von Hand und nur nach deiner Freigabe in GitHub. Der Runner läuft im Büro auf Sokrates-2 als eigener Benutzer `wais-deploy` ohne root. Er darf per sudo genau die Aufrufe des Ausroll-Einstiegs `/usr/local/sbin/wais-deploy`, sonst nichts. Der Einstieg ruft dieselben Skripte auf wie das Ausrollen von Hand (`wamo-core-slots.sh`, `wamo-ui-umschalten.sh`, `wamo-labor-einrichten.sh`) und nimmt nur Commits an, die in `origin/main` enthalten sind.

## Überblick

| Teil | Ort | Aufgabe |
| --- | --- | --- |
| Workflow `Ausrollen` | `.github/workflows/deploy.yml` | bei Push auf `main` (nicht bei reiner Doku: `docs/**`, Markdown im Hauptordner) und von Hand: dev, danach test |
| Workflow `Ausrollen dev` | `.github/workflows/deploy-dev.yml` | Stand auflösen, Prüf-Workflows abwarten, am Server `pruefen-stand` und `verteilen` |
| Workflow `Ausrollen test` | `.github/workflows/deploy-test.yml` | `test-kern`, `test-oberflaeche`, `rauchtest` (baut und startet, schaltet nie um) |
| Workflow `Ausrollen prod` | `.github/workflows/deploy-prod.yml` | nur von Hand, Environment `prod` mit Pflicht-Prüfer: `prod-kern`, `prod-oberflaeche`, `rauchtest`, `ausleiten`, Rückweg |
| Hilfsskript für GitHub | `scripts/wais_deploy_github.py` | läuft auf einem Runner von GitHub, nie am Server: Stand auflösen, Prüfungen abwarten, Schutz von prod prüfen |
| Einstieg am Server | `infra/sokrates2/wais-deploy.sh`, installiert als `/usr/local/sbin/wais-deploy` | feste Unterbefehle, Sperre, Protokoll, Prüfung auf `origin/main` |
| Einrichtung | `infra/sokrates2/wais-runner-einrichten.sh` | Benutzer, Runner-Software (Version und SHA-256 fest), sudoers, Dienst, Rückweg |
| Runner | `/opt/wais-runner`, Dienst `wais-runner.service`, Name `sokrates2-wais-deploy`, Label `wais-deploy` | holt Jobs mit `runs-on: [self-hosted, linux, ARM64, wais-deploy]` |
| Daten | `/var/lib/wais-deploy` (Spiegel `repo.git`, `staende/<commit>`, `zustand/`), `/etc/wais-deploy` (Quelle, Lese-Schlüssel) | |
| Protokoll | `/var/log/wais-deploy/protokoll.log`, Journal `journalctl -t wais-deploy` | jeder Aufruf mit Befehl, Commit, Ausgabe und Rückgabe |

## Ablauf je Stufe

| Stufe | Auslöser | Am Server | Wirkung auf den Betrieb |
| --- | --- | --- | --- |
| dev | Merge auf `main`, oder von Hand | `pruefen-stand <commit>` holt `origin/main` frisch in den eigenen Spiegel und lehnt jeden Commit ab, der dort fehlt. `verteilen <commit>` legt den Stand wie `verteilen` vom PC ab (infra/sokrates2, Kern-Dateien, ui/ ohne `.env`, `bau.info` mit `sauber=ja`). | keine |
| test | nach dev, oder von Hand | `test-kern` baut das Kern-Release `v<version>-<commit7>` und startet es im freien Slot (`bereiten`), prüft den Slot dreimal. `test-oberflaeche` baut die neue Fassung in der freien Farbe (`bauen`) und prüft sie. Danach `rauchtest` (aktiver Slot, live Farbe, Labor-Dienst). | keine: live bleiben aktiver Slot und live Farbe |
| prod | nur von Hand, dann Freigabe | `prod-kern` schaltet Caddy auf den in test gestarteten Slot (`schalten`, 60 Sekunden Nachlauf) und bewährt 30 Minuten (`bewaehren 30`, dreimal ungesund heißt automatisch zurück). `prod-oberflaeche` schaltet auf die in test gebaute Farbe (`umschalten --ohne-bau`, Bewährung 120 Sekunden, höchstens 5 Prozent Fehler, sonst automatisch zurück). Danach `rauchtest`; fällt er durch, geht es mit `rueckweg` auf den vorher live gewesenen Stand. Zum Schluss ein Versuch `ausleiten`. | Umschalten ohne Lücke |

Reihenfolge wie beim Ausrollen von Hand: Kern zuerst, dann Oberfläche; beim Rückweg umgekehrt. prod geht nur für einen Stand, der am Server die Stufe test bestanden hat. Alle Deploy-Jobs teilen sich die Gruppe `wais-deploy`: ein laufender Lauf wird nie abgebrochen, ein wartender wird durch einen neueren ersetzt (der neueste Stand gewinnt).

## Montag, Schritt für Schritt

### 1. Reihenfolge klären: erst privat, dann Runner

Ein eigener Runner an einem öffentlichen Repo ist gefährlich: Pull Requests aus Forks können Workflows mit eigenen Dateien starten. Die Workflows hier haben keinen Auslöser `pull_request`, aber ein fremder Pull Request bringt seine eigene Workflow-Datei mit. Deshalb den Runner **erst registrieren, wenn `Wamocon/w.a.i.s` privat ist** (Schritt 4). Bis dahin kann alles andere schon eingerichtet werden (`--ohne-registrierung`).

Danach in den Einstellungen des Repos: Settings, Actions, General, Abschnitt "Fork pull request workflows in private repositories": "Run workflows from fork pull requests" **aus**.

### 2. Pull Request mergen, Skripte auf den Server legen

Nach dem Merge im Arbeitsbaum auf dem gemergten `main` (Git Bash):

```bash
python scripts/wamo_kern_sokrates2.py verteilen      # legt infra/sokrates2 neu nach ~/wamo-infra (leert den Ordner vorher)
```

### 3. Einrichten ohne Registrierung

```bash
ssh wamo-sokrates2 "sudo bash ~/wamo-infra/wais-runner-einrichten.sh einrichten --trocken"
ssh wamo-sokrates2 "sudo bash ~/wamo-infra/wais-runner-einrichten.sh einrichten --ohne-registrierung"
```

Das legt Benutzer, Ordner, Runner-Software (Version 2.338.2, SHA-256 geprüft), Einstieg, sudoers (mit `visudo -c` und zehn Proben `sudo -l -U wais-deploy`) und den Dienst an. Am Ende steht der **öffentliche Teil des Lese-Schlüssels** (eine Zeile `ssh-ed25519 ...`).

**Deploy-Key eintragen:** Repo, Settings, Deploy keys, "Add deploy key". Titel `sokrates2-wais-deploy`, Inhalt die Zeile von oben, **"Allow write access" nicht ankreuzen**. Der Server holt damit `main` in seinen eigenen Spiegel, auch wenn das Repo privat ist.

Probe (holt `main`, ändert nichts am Betrieb):

```bash
ssh wamo-sokrates2 "sudo /usr/local/sbin/wais-deploy pruefen-stand $(git rev-parse origin/main)"
# erwartet am Ende: WAIS ergebnis=ok
```

### 4. Registrierungstoken holen und Runner registrieren (erst wenn das Repo privat ist)

Das Token gilt eine Stunde und geht nur über stdin an das Skript, nie als Argument und nie in eine Datei.

Weg A, mit der GitHub-Kommandozeile (am einfachsten, das Token sieht niemand):

```bash
gh api -X POST repos/Wamocon/w.a.i.s/actions/runners/registration-token --jq .token \
  | ssh wamo-sokrates2 "sudo bash ~/wamo-infra/wais-runner-einrichten.sh einrichten"
```

Weg B, im Browser: Repo, Settings, Actions, Runners, "New self-hosted runner", Linux, ARM64. Im Abschnitt "Configure" steht ein Befehl mit `--token ...`: nur den Wert nach `--token` kopieren, dann

```bash
ssh -t wamo-sokrates2 "sudo bash ~/wamo-infra/wais-runner-einrichten.sh einrichten"
# fragt: Registrierungstoken (wird nicht angezeigt):
```

Die Befehle der GitHub-Seite selbst (`./config.sh`, `./svc.sh`) **nicht** ausführen; das erledigt das Skript als `wais-deploy`.

Variante Organisation: Wer den Runner für die Organisation in einer eigenen Runner-Gruppe registriert (nur dieses Repo, "Allow public repositories" aus), nimmt `--url https://github.com/Wamocon --gruppe <Name>` und das Token aus `gh api -X POST orgs/Wamocon/actions/runners/registration-token --jq .token`.

Prüfen: Settings, Actions, Runners zeigt `sokrates2-wais-deploy` mit "Idle" und den Labels `self-hosted`, `Linux`, `ARM64`, `wais-deploy`. Am Server: `ssh wamo-sokrates2 "sudo bash ~/wamo-infra/wais-runner-einrichten.sh status"`.

### 5. Environments und Pflicht-Prüfer

Settings, Environments:

| Environment | Einstellungen |
| --- | --- |
| `dev` | "Deployment branches and tags": Selected branches, Regel `main` |
| `test` | wie `dev` |
| `prod` | "Required reviewers": Niko (und eine Vertretung). "Prevent self-review" aus lassen, wenn du selbst startest und freigibst (an: es braucht eine zweite Person). "Deployment branches and tags": Selected branches, Regel `main`. "Allow administrators to bypass configured protection rules" **aus**. |

Der Workflow `Ausrollen prod` prüft vor jedem Lauf über die API, dass `prod` Pflicht-Prüfer und eine Regel für Zweige hat. Fehlt eins davon, bricht er ab, bevor der Server etwas tut.

### 6. Weitere Einstellungen

- Settings, Actions, General, "Workflow permissions": "Read repository contents and packages permissions" (nur lesen).
- Settings, Actions, General, "Actions permissions": nur Actions von GitHub erlauben (genutzt wird nur `actions/checkout`, auf Commit-SHA festgenagelt); wenn angeboten, "Require actions to be pinned to a full-length commit SHA" einschalten.
- Variable `WAIS_PRUEF_WORKFLOWS` (Settings, Secrets and variables, Actions, Variables): sobald die Prüf-Workflows aus dem Zweig `ci/pruef-workflows` gemergt sind, ihre Pfade kommagetrennt eintragen: `.github/workflows/ci.yml,.github/workflows/secret-scan.yml` (Stand des Zweigs am 14.11.2026: `ci.yml` heißt "Prüfungen" und läuft bei jedem Push, auch auf `main`). dev verlangt dann für genau diesen Commit einen grünen Lauf jedes genannten Workflows und wartet zusätzlich auf jeden anderen Lauf, der für den Commit gestartet ist (etwa CodeQL). Ohne Variable wartet dev auf alle Prüf-Workflows, die für den Commit laufen, mindestens 90 Sekunden lang, heute nur der Secret Scan. Die Frist beträgt 60 Minuten.

### 7. Erster Lauf

1. Actions, "Ausrollen", "Run workflow": Stand leer, Teil `beides`, **Trockenlauf an**. Die Zusammenfassung des Laufs zeigt Stand, Kern-Release und Ergebnis je Schritt.
2. Dasselbe ohne Trockenlauf. Danach läuft das neue Kern-Release im freien Slot und die neue Farbe ist gebaut, live ist nichts verändert.
3. Actions, "Ausrollen prod", Aktion `ausrollen`, Stand = Commit oder Release-Name aus Schritt 2, **Trockenlauf an**, dann "Review deployments" und freigeben.
4. Dasselbe ohne Trockenlauf. Der Lauf dauert gut 35 Minuten (30 Minuten Bewährung des Kerns). Gelingt das Ausleiten am Ende nicht (Sitzung auf der alten Instanz oder keine 15 Minuten Ruhe), steht eine Warnung in der Zusammenfassung: später "Ausrollen prod" mit Aktion `ausleiten` starten. Solange die alte Instanz läuft, bricht `test-kern` des nächsten Standes mit einem klaren Hinweis ab.

## Betrieb

| Wozu | Befehl |
| --- | --- |
| Zustand | `ssh wamo-sokrates2 "sudo /usr/local/sbin/wais-deploy status"` |
| Protokoll | `ssh wamo-sokrates2 "sudo tail -n 80 /var/log/wais-deploy/protokoll.log"`, Kurzfassung `journalctl -t wais-deploy` |
| Rückweg ohne GitHub (Notfall) | `ssh wamo-sokrates2 "sudo /usr/local/sbin/wais-deploy rueckweg beides"` (erst `--trocken`); geht nur, solange die vorige Instanz und die vorige Farbe noch laufen |
| Notanker | `ssh wamo-sokrates2 "sudo wamo-anker status"`, dann `rueckweg kern` oder `rueckweg ui` (Abschnitt 14 in `infra/sokrates2/README.md`) |
| Runner neu starten | `ssh wamo-sokrates2 "sudo systemctl restart wais-runner"` (ein laufendes Ausrollen läuft weiter, `KillMode=process`) |

Rückgabewerte des Einstiegs: 0 in Ordnung, 1 Fehler, 2 Aufruf ungültig, 3 Vorbedingung nicht erfüllt (nichts geändert), 4 nach dem Umschalten automatisch zurückgenommen, 5 Rückweg nicht möglich (Handarbeit, Notanker).

Ausrollen von Hand vom PC aus (`D:\tmp\uebernahme\2026-11-14\40-ausrollen.md`, README Abschnitt 12 und 14) bleibt möglich, nimmt aber die Sperre des Einstiegs nicht. Nie gleichzeitig mit einem laufenden Workflow verwenden.

### Runner-Software aktualisieren

Ohne automatische Updates verlangt GitHub ein Update innerhalb von 30 Tagen nach einer neuen Runner-Version, sonst bekommt der Runner keine Jobs mehr. Einmal im Monat: auf github.com/actions/runner/releases die neue Version und die SHA-256 der Datei `actions-runner-linux-arm64-<Version>.tar.gz` ablesen, `RUNNER_VERSION` und `RUNNER_SHA256` in `infra/sokrates2/wais-runner-einrichten.sh` gemeinsam ändern (Pull Request), nach dem Merge Schritt 2 und `einrichten` wiederholen. Das Skript stoppt den Dienst, tauscht die Programme und startet ihn wieder; die Registrierung bleibt.

Ebenso gilt: Eine Änderung an `wais-deploy.sh` wirkt erst, wenn `einrichten` den Einstieg neu installiert hat (`status` zeigt, ob er dem Stand in `~/wamo-infra` gleicht). Ein Pull Request allein ändert am Server nichts.

## Rückweg

```bash
# 1. ansehen
ssh wamo-sokrates2 "sudo bash ~/wamo-infra/wais-runner-einrichten.sh rueckweg --trocken"
# 2. Runner abmelden und entfernen (Entfernungstoken nur über stdin)
gh api -X POST repos/Wamocon/w.a.i.s/actions/runners/remove-token --jq .token \
  | ssh wamo-sokrates2 "sudo bash ~/wamo-infra/wais-runner-einrichten.sh rueckweg --abmelden"
#    ohne Abmelden: rueckweg allein, dann in GitHub unter Settings, Actions, Runners den Runner entfernen
# 3. wenn auch Lese-Schlüssel, Spiegel, Stände und Zustand weg sollen
ssh wamo-sokrates2 "sudo bash ~/wamo-infra/wais-runner-einrichten.sh rueckweg --alles"
```

Der Rückweg entfernt zuerst die sudoers-Datei (sofort keine root-Aufrufe mehr), dann Dienst, Runner-Software, Home, Benutzer und Einstieg. Er bricht ab, solange ein Ausrollen läuft. Das Protokoll bleibt. In GitHub danach den Deploy-Key `sokrates2-wais-deploy` löschen. Am laufenden Betrieb (Kern-Slots, Oberfläche, Labor) ändert der Rückweg nichts.

## Grenzen

- Wer Schreibrechte am Repo hat, kann einen Workflow auf einem anderen Zweig von Hand starten und dabei die Workflow-Datei verändern. Die Jobs prüfen zwar `refs/heads/main` und das Environment `prod` lässt nur `main` zu, eine veränderte Datei kann das aber weglassen. Dann bleibt die Prüfung am Server: Der Runner kann nur die festen Unterbefehle aufrufen, und die nehmen nur Commits aus `origin/main` (also nur, was durch Review gegangen ist). prod verlangt zusätzlich die bestandene Stufe test für genau diesen Stand.
- Der Runner-Benutzer erreicht das Büro-Netz (kein eigener Ausgangsfilter). Er hat keine Gruppe außer seiner eigenen, kein docker und kein sudo außer dem Einstieg.
- Die automatische Rücknahme innerhalb der Bewährung des Kerns schaltet Caddy ohne die gemeinsame Sperre der Labor-Dienste (wie bisher beim Ausrollen von Hand).
- Die Stufe test baut die Oberfläche in die freie Farbe. Damit ist die bisher vorige Farbe ersetzt; ein schneller Rückweg der Oberfläche führt danach auf die neue Fassung, ältere Fassungen holt der Notanker aus dem Archiv.
