# GitHub einrichten: Einstellungen des Repositorys

**Stand:** 20.11.2026. **Für:** die Admins von `Wamocon/w.a.i.s`. **Anlass:** `.github/dependabot.yml` verweist auf dieses Dokument. Belegt ist alles aus `.github/workflows/*.yml`, `docs/runner-einrichten.md` und `scripts/wais_deploy_github.py`. Die Einstellungen liegen in GitHub (Settings), nicht im Repository. Der Branch-Schutz in Abschnitt 6 ist eine Empfehlung, keine Voraussetzung der Workflows.

## 1. Ist-Stand am 20.11.2026

Gelesen mit `gh api repos/Wamocon/w.a.i.s/...` (Branch-Schutz, `environments`, `actions/variables`) und `gh repo view`:

| Punkt | Stand |
| --- | --- |
| Sichtbarkeit | öffentlich |
| Branch-Schutz für `main` | keiner (Antwort "Branch not protected") |
| Environments | nur `dev`, ohne Regeln |
| Variable `WAIS_PRUEF_WORKFLOWS` | nicht gesetzt |
| Secret scanning, Push protection, Dependabot security updates | Abfrage meldet `disabled` |

## 2. Sichtbarkeit und Runner

- Die Workflows wählen den Runner nach der Sichtbarkeit: Ist das Repository privat, laufen die Prüfungen auf dem eigenen Runner (`self-hosted`, `linux`, `ARM64`), sonst auf Runnern von GitHub (`ubuntu-24.04`, `ubuntu-latest`). Die Jobs Desktop und Host laufen immer auf `windows-2025`. Die Jobs `server` der Ausroll-Workflows laufen immer auf dem eigenen Runner mit dem Label `wais-deploy`.
- Der eigene Runner wird erst registriert, wenn das Repository privat ist. Ein fremder Pull Request bringt seine eigene Workflow-Datei mit und könnte sonst Code auf dem Runner ausführen (`docs/runner-einrichten.md`, Schritt 1).
- Danach in Settings, Actions, General, "Fork pull request workflows in private repositories": "Run workflows from fork pull requests" aus.
- Runner: Name `sokrates2-wais-deploy`, Labels `self-hosted`, `Linux`, `ARM64`, `wais-deploy`, Dienst `wais-runner.service`, Benutzer `wais-deploy` ohne root. Einrichtung, Deploy-Key (nur Lesen, "Allow write access" nicht ankreuzen) und Rückweg stehen in `docs/runner-einrichten.md`. Ohne Update der Runner-Software innerhalb von 30 Tagen nach einer neuen Version bekommt der Runner keine Jobs mehr.
- Der Zeitpunkt der Umstellung auf privat und ihre Kosten (Code scanning bei privaten Repositories, Abrechnung der Runner von GitHub) sind zu klären `[offen: Niko]`.

## 3. Actions

Settings, Actions, General:

- "Workflow permissions": nur Leserechte. Die Workflows setzen ihre Rechte selbst (`permissions`).
- "Actions permissions": Erlaubt sein müssen genau diese Actions: `actions/checkout`, `actions/setup-node`, `actions/setup-python`, `astral-sh/setup-uv`, `github/codeql-action`. `docs/runner-einrichten.md` nennt nur `actions/checkout`, das ist veraltet: `astral-sh/setup-uv` gehört nicht zu GitHub und wird von sechs Jobs genutzt.
- "Require actions to be pinned to a full-length commit SHA": kann an bleiben. Alle fremden Actions stehen auf voller Commit-SHA (Version im Kommentar), die lokalen Aufrufe `./.github/workflows/deploy-*.yml` sind Pfade im Repository.

## 4. Environments

Settings, Environments. Die Workflows `deploy-dev.yml`, `deploy-test.yml` und `deploy-prod.yml` nennen `dev`, `test` und `prod`.

| Environment | Einstellungen |
| --- | --- |
| `dev`, `test` | "Deployment branches and tags": Selected branches, Regel `main`. Keine Pflicht-Prüfer, beide Stufen laufen nach jedem Merge von selbst |
| `prod` | "Required reviewers": mindestens eine Person, besser mit Vertretung. "Deployment branches and tags": Selected branches, Regel `main`. "Allow administrators to bypass configured protection rules": aus. "Prevent self-review": an, wenn eine zweite Person freigeben soll |

Der Workflow `Ausrollen prod` ruft vor jedem Lauf `scripts/wais_deploy_github.py umgebung --name prod` auf und bricht ab, wenn `prod` keine Pflicht-Prüfer oder keine Zweigregel hat. Der Server tut dann nichts.

## 5. Variable `WAIS_PRUEF_WORKFLOWS`

Settings, Secrets and variables, Actions, Variables. Wert: `.github/workflows/ci.yml,.github/workflows/secret-scan.yml` (kommagetrennte Pfade, `docs/runner-einrichten.md`). Die Stufe dev verlangt dann für genau den Commit einen grünen Lauf jedes genannten Workflows und wartet auf jeden anderen Lauf, der für den Commit gestartet ist, etwa CodeQL (Frist 60 Minuten). Ohne die Variable gilt: alle vorhandenen Läufe grün, frühestens 90 Sekunden nach dem Start. Der Secret Scan ist damit Vorbedingung für das Ausrollen.

## 6. Branch-Schutz für `main` (Empfehlung)

Settings, Rules oder Branches, Ziel `main`:

- "Require a pull request before merging".
- "Require status checks to pass": der Check **`Ergebnis`** (Job `ergebnis` in `ci.yml`). Er wird rot, sobald ein Job fehlschlägt oder abbricht, übersprungene Teile zählen als in Ordnung. Der Name muss genau so eingetragen werden. Optional zusätzlich `gitleaks`, weil der Secret Scan auch bei Pull Requests läuft.
- "Block force pushes" und "Restrict deletions".

**Risiko:** Ein Pflicht-Check, der nie meldet, blockiert jeden Merge. Das passiert, wenn die Abrechnung von GitHub ausfällt (Runner von GitHub) oder der eigene Runner offline ist (privates Repository). Auch ein dringender Sicherheitsfix lässt sich dann nicht mergen. Vorher festlegen, wer den Pflicht-Check im Notfall vorübergehend aufhebt, und das im Pull Request vermerken. Die Administrator-Umgehung deshalb nicht abschalten, solange es keine zweite Lösung gibt `[offen: Niko]`.

## 7. Sicherheitsfunktionen

| Funktion | Einstellung |
| --- | --- |
| CodeQL | Workflow `codeql.yml` (Sprachen `actions`, `javascript-typescript`, `python`, ohne Build; Pull Request, Push, dienstags 04:41 UTC, manuell). Funde unter Security, Code scanning. Laut Kopf des Workflows kostenlos für öffentliche Repositories |
| Dependabot | `.github/dependabot.yml` pflegt die GitHub Actions wöchentlich, die Blöcke für npm, pip und docker sind auskommentiert. In Settings, Code security zusätzlich "Dependabot alerts" und "Dependabot security updates" einschalten |
| Secret Scan | Workflow `secret-scan.yml` (gitleaks, Konfiguration `.gitleaks.toml`). Vorgehen bei einem Fund: `docs/SECRET_GEFUNDEN.md`. Zusätzlich "Secret scanning" und "Push protection" einschalten: Der Workflow prüft erst nach dem Push, die Push protection hält einen Fund vorher auf |

## 8. Prüfen

```bash
gh repo view Wamocon/w.a.i.s --json visibility
gh api repos/Wamocon/w.a.i.s/branches/main/protection
gh api repos/Wamocon/w.a.i.s/environments --jq '.environments[] | {name, rules: [.protection_rules[].type], branch_policy: .deployment_branch_policy}'
gh api repos/Wamocon/w.a.i.s/actions/variables --jq '.variables[] | {name, value}'
```

Am Server: `ssh wamo-sokrates2 "sudo bash ~/wamo-infra/wais-runner-einrichten.sh status"`. In GitHub zeigt Settings, Actions, Runners den Runner `sokrates2-wais-deploy` als "Idle".

WAMOCON GmbH, Mergenthalerallee 79-81, 65760 Eschborn
