# Secret gefunden: Vorgehen bei einer Meldung des Secret Scans

**Stand:** 20.11.2026. **Anlass:** Der Workflow `Secret Scan` (`.github/workflows/secret-scan.yml`, Job `gitleaks`) meldet einen Fund. Seine Zusammenfassung "Secret gefunden" verweist auf dieses Dokument. Es gilt für jede Person, die einen Pull Request oder einen Push verantwortet.

## 1. Grundsatz

Ein gefundenes Geheimnis steht bereits im Repository, denn der Scan prüft nach dem Push. Das Repository ist öffentlich (Stand 20.11.2026), damit ist jeder Commit für alle lesbar, auch der eines Zweigs. Der Fund gilt als bekannt. Darum gilt die Reihenfolge: erst widerrufen, dann aufräumen. Ein Geheimnis nur aus dem Code oder aus dem Verlauf zu löschen, reicht nie.

## 2. Was der Scan tut

- gitleaks 8.30.1 (Prüfsumme im Workflow fest), Standardregeln plus `.gitleaks.toml` (`useDefault = true`).
- Läuft bei jedem Pull Request (Commits `base..head`), bei jedem Push auf `main` (Commits `before..after`), montags um 03:17 UTC über die ganze Historie und von Hand (`workflow_dispatch`).
- Aufruf mit `--redact`: Werte stehen im Protokoll geschwärzt. Mit `--ignore-gitleaks-allow`: Die Marke `gitleaks:allow` im Code ist wirkungslos.

## 3. Ablauf

1. **Anhalten.** Nichts weiter pushen und keinen Pull Request mergen, bis der Fund eingeordnet ist. Jeder Merge auf `main` baut am Server dev und test (`deploy.yml`, ausgenommen reine Doku).
2. **Fund ansehen.** Actions, Lauf "Secret Scan", Schritt "Nach Secrets suchen". Je Fund stehen Regel, Datei, Zeile, Commit und der Fingerabdruck im Format `Commit:Datei:Regel:Zeile` da. Den Wert nie aus dem Protokoll abschreiben und nie in einen Pull Request, ein Issue oder einen Chat kopieren.
3. **Einordnen.** Echt ist jeder Wert, der bei einem Dienst gilt oder galt. Fehlalarm ist nur ein erfundener Wert, zum Beispiel eine Attrappe in einer Testdatei. Im Zweifel gilt der Fund als echt.
4. **Echt: sofort widerrufen und neu erzeugen**, vor jeder Bereinigung (Tabelle unten). Danach den neuen Wert nur dort eintragen, wo er gebraucht wird (`.env`, nie im Repository).
5. **Nutzung prüfen.** Beim Dienst nachsehen, ob der Wert ab dem Zeitpunkt des Commits benutzt wurde (Verbrauch, Anmeldungen, Zugriffe).
6. **Aus dem Code entfernen** in einem neuen Pull Request. Testwerte werden zur Laufzeit gebaut statt fest eingetragen (so geschehen in `desktop/update.test.js` und `voice-core/test_auftrag_entwuerfe.py`).
7. **Fehlalarm markieren.** Nur per Pull Request mit Review, nie durch eine Marke im Code. Zwei Orte, jede Ausnahme mit Begründung:
   - `.gitleaks.toml`, Block `[[allowlists]]` mit `description`, `targetRules` und `paths`. Die Ausnahme gilt nur für die genannte Regel und den genannten Pfad.
   - `.gitleaksignore`, eine Zeile mit dem Fingerabdruck, davor ein Kommentar mit Datum und Grund. Das gilt für einen einzelnen Fund in einem alten Commit, auch für einen bereits widerrufenen Wert.
8. **Verlauf bereinigen nur nach Absprache.** Das Umschreiben der Historie ändert Commit-Kennungen auf `main` und braucht einen Force-Push. Der Server nimmt beim Ausrollen nur Commits aus `origin/main` an und die Kern-Releases heißen nach dem Commit (`v<version>-<commit7>`), ein Umschreiben stört also Ausrollen und Rückweg. Klone, Forks und Zwischenspeicher behalten den Wert ohnehin. Es ersetzt den Widerruf nie.
9. **Melden.** An die Leitung des Projekts und an die Verantwortlichen des betroffenen Dienstes. Sind personenbezogene Daten betroffen, entscheidet die verantwortliche Person für den Datenschutz über eine Meldung nach Art. 33 DSGVO (Frist 72 Stunden ab Kenntnis).
10. **Nachweis im Pull Request.** Regel, Datei und Zeile ohne Wert, Zeitpunkt von Widerruf und Neuausgabe, Ergebnis der Nutzungsprüfung, Ausnahme oder Entfernung, grüner Lauf von `Secret Scan` (bei einer Altlast: Lauf per `workflow_dispatch` über die ganze Historie).

## 4. Wo ein Geheimnis erneuert wird

| Geheimnis | Erneuern |
| --- | --- |
| `ANTHROPIC_API_KEY` | In der Konsole des Sprachmodells neuen Schlüssel erzeugen, alten löschen. Am Server die Zeile in `/etc/wamo/core.env` mit `wamo-core-env` ändern (Wert nur über stdin), danach `wamo-core-slots.sh umschalten-kern <release>` (`docs/labor-runbook.md`) |
| `SONIOX_API_KEY` | Beim Anbieter Soniox neuen Schlüssel erzeugen, alten löschen, den Wert in der Umgebung des Kerns ersetzen (`wamo-core-env`, wirkt mit dem nächsten Kern-Release) |
| `WAMO_DATABASE_URL`, `WAMO_ADMIN_DATABASE_URL` | Passwort der Rolle `wamo_core` bzw. `wamo_admin` in der Datenbank neu setzen, neuen Wert dort eintragen, wo die Verbindung genutzt wird |
| `LITELLM_API_KEY` | Im Gateway (LiteLLM) den Schlüssel sperren und neu ausstellen (`infra/sokrates1/gateway-wamo.md`) |
| GitHub-Token, Deploy-Key `sokrates2-wais-deploy`, Registrierungstoken des Runners | In GitHub widerrufen oder löschen (Settings des Kontos bzw. des Repositorys), den Runner danach nach `docs/runner-einrichten.md` neu einrichten, wenn sein Schlüssel betroffen ist |
| Signaturschlüssel der Updates | Den öffentlichen Schlüssel aus `desktop/update-schluessel.json` und am Server aus `/etc/wamo-verteilung/update-schluessel.json` entfernen, neues Paar erzeugen, mit der Leitung absprechen |
| Jedes andere Geheimnis | Beim Dienst, der es ausgestellt hat |

WAMOCON GmbH, Mergenthalerallee 79-81, 65760 Eschborn
