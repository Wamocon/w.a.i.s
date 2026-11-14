# Technischen Jira-Benutzer für W.A.I.S. einrichten

Anleitung für Niko, Stand 14.11.2026, Paket P3 aus `docs/office-und-versand.md`. W.A.I.S. legt aus einem Canvas-Dokument eine User Story in Jira
an, immer erst nach dem Klick auf "Freigeben" auf der Freigabekarte (Job `jira`). Dafür braucht der Kern einen eigenen technischen Jira-Benutzer
nur für W.A.I.S. mit genau zwei Rechten: "Browse Projects" und "Create Issues". Der vorhandene Lese-Zugang der Entwicklungsaufträge
(`JIRA_EMAIL`, `JIRA_API_KEY` in `/etc/wamo/geheim.env`) bleibt unberührt und wird nicht verwendet.

In dieser Anleitung stehen keine echten Werte. Platzhalter stehen in spitzen Klammern.

## Was der Benutzer darf und was nicht

| Darf | Darf nicht |
| --- | --- |
| Projekte aus der Erlaubnisliste sehen (`WAMO_JIRA_PROJEKTE`, zunächst nur `WMCNL`) | Vorgänge bearbeiten, löschen, verschieben, zuweisen oder kommentieren |
| Vorgänge vom Typ Story anlegen, mit Epic über das Feld "Übergeordnet" (`parent`) | Projekte oder Einstellungen verwalten |
| | auf Confluence oder andere Produkte zugreifen |

W.A.I.S. selbst ruft nur fünf Schnittstellen auf (Projekt lesen, eigenes Recht prüfen, Epic lesen, Story anlegen, eigene Stories der letzten 15
Minuten suchen). Ersteller der Story ist der technische Benutzer; wer sie angefordert hat, steht im Protokoll von W.A.I.S. (Tabelle `actions`).

## 1. Benutzer anlegen (Atlassian-Verwaltung)

1. `admin.atlassian.com` öffnen, Organisation WAMOCON, "Verzeichnis", "Benutzer", "Benutzer einladen".
2. Vorschlag für die Angaben:
   - Anzeigename: `W.A.I.S. Jira-Story`
   - Mailadresse: eine eigene Funktionsadresse der Firma, zum Beispiel `wais-jira@<Firmendomäne>` (ein Postfach oder Verteiler, den du liest:
     Einladung, Passwort und Hinweise zum Ablauf des Tokens gehen dorthin). Nie deine eigene Adresse, nie die des Lese-Zugangs.
3. Produktzugang: nur **Jira** mit der Rolle "Benutzer". Kein Confluence, keine Rolle als Administrator. Der Benutzer belegt einen
   Jira-Platz der Lizenz.
4. Einladung über die Funktionsadresse annehmen, ein starkes Passwort setzen und die Zwei-Faktor-Anmeldung einschalten.

Hinweis: Dienstkonten (Service Accounts) der Atlassian-Verwaltung sind für diesen Stand nicht vorgesehen und nicht geprüft. W.A.I.S. erwartet einen
normalen Benutzer mit klassischem API-Token, angesprochen über `https://wamocon.atlassian.net`.

## 2. Rechte nur in WMCNL (Projektrolle)

`WMCNL` ist ein firmenverwaltetes Projekt (Software, nicht vereinfacht). Rechte kommen dort aus dem Berechtigungsschema des Projekts, das sie
an Projektrollen vergibt. So bekommt der Benutzer genau die zwei Rechte:

1. Jira-Einstellungen, "System", "Projektrollen": eine neue Rolle `W.A.I.S.` anlegen (Beschreibung: "Technischer Benutzer, nur Browse
   Projects und Create Issues").
2. Jira-Einstellungen, "Vorgänge", "Berechtigungsschemas": das Schema von `WMCNL` öffnen und der Rolle `W.A.I.S.` genau zwei Rechte geben:
   "Browse Projects" (Projekte durchsuchen) und "Create Issues" (Vorgänge erstellen). Sonst nichts.
   Teilen sich mehrere Projekte das Schema, ist das unkritisch: Die Rolle wirkt nur in Projekten, in denen der Benutzer Mitglied der Rolle ist.
3. Projekt `WMCNL`, "Projekteinstellungen", "Personen": den Benutzer `W.A.I.S. Jira-Story` mit der Rolle `W.A.I.S.` hinzufügen.
4. Prüfen, dass er nicht mehr darf: Jira-Einstellungen, "System", "Berechtigungshelfer" (Permission helper) mit dem Benutzer, dem Projekt
   `WMCNL` und nacheinander "Edit Issues", "Delete Issues", "Assign Issues", "Add Comments", "Administer Projects". Jedes Mal muss "Nein"
   herauskommen. Steht dort "Ja" über eine Gruppe (zum Beispiel alle angemeldeten Benutzer), den Benutzer aus dieser Gruppe nehmen oder das
   Schema anpassen, bevor du das Token erzeugst.
5. Weitere Projekte nur auf Zuruf: dieselbe Rolle im Projekt vergeben und den Schlüssel in `WAMO_JIRA_PROJEKTE` ergänzen (Schritt 4).

## 3. API-Token erzeugen (als der technische Benutzer)

1. In einem privaten Browserfenster als `W.A.I.S. Jira-Story` anmelden (nicht mit deinem eigenen Konto).
2. `id.atlassian.com`, "Sicherheit", "API-Token erstellen und verwalten", "API-Token erstellen" (das klassische Token, ohne Bereiche).
3. Name: `W.A.I.S. Kern Sokrates-2`. Ablauf: höchstens ein Jahr, das Datum im Kalender eintragen (zwei Wochen vorher erneuern, Schritt 3 bis 5).
4. Token einmal kopieren und direkt in Schritt 4 verwenden. Nirgends ablegen, nicht in eine `.env`, nicht in Chat oder Mail.

## 4. Werte am Server setzen (Schalter bleibt aus)

Die Werte gehen nur über stdin an `wamo-core-env` auf Sokrates-2, nie über eine Befehlszeile und nie aus einer `.env` des PCs. In Git Bash
auf deinem PC (das Token erscheint weder am Bildschirm noch im Verlauf der Shell):

```bash
read -r -p "Mailadresse des technischen Benutzers: " JIRA_MAIL
read -r -s -p "API-Token (wird nicht angezeigt): " JIRA_TOKEN; echo
printf 'WAMO_JIRA=aus\nWAMO_JIRA_URL=https://wamocon.atlassian.net\nWAMO_JIRA_EMAIL=%s\nWAMO_JIRA_TOKEN=%s\nWAMO_JIRA_PROJEKTE=WMCNL\nWAMO_JIRA_STANDARD_PROJEKT=WMCNL\n' \
  "$JIRA_MAIL" "$JIRA_TOKEN" | ssh wamo-sokrates2 "sudo -n /usr/local/sbin/wamo-core-env setzen"
unset JIRA_TOKEN JIRA_MAIL
```

Erwartete Antwort: `Übernommen: WAMO_JIRA, WAMO_JIRA_EMAIL, WAMO_JIRA_PROJEKTE, WAMO_JIRA_STANDARD_PROJEKT, WAMO_JIRA_TOKEN, WAMO_JIRA_URL (Werte nicht
angezeigt)`. Kontrolle, nur Namen:

```bash
ssh wamo-sokrates2 "sudo -n /usr/local/sbin/wamo-core-env liste" | grep WAMO_JIRA
```

| Einstellung | Wert | Bedeutung |
| --- | --- | --- |
| `WAMO_JIRA` | `aus`, später `an` | Werkzeug und Knopf am Canvas für Admins im Büro; leer oder ein Tippfehler heißt aus |
| `WAMO_JIRA_URL` | `https://wamocon.atlassian.net` | nur `https://<name>.atlassian.net`, sonst bleibt Jira aus |
| `WAMO_JIRA_EMAIL` | Mailadresse des technischen Benutzers | Anmeldung (Basic-Auth) |
| `WAMO_JIRA_TOKEN` | sein API-Token | Geheimnis, nie angezeigt, nie an Entwicklungsaufträge weitergegeben |
| `WAMO_JIRA_PROJEKTE` | `WMCNL` | Erlaubnisliste, Projektschlüssel durch Komma getrennt |
| `WAMO_JIRA_STANDARD_PROJEKT` | `WMCNL` | Projekt ohne Angabe, muss in der Liste stehen |

Alle Werte wirken erst mit dem nächsten Kern-Release über die Slots (`wamo-core-slots.sh release`, `umschalten-kern`, `bewaehren 30`,
`ausleiten`, siehe `infra/sokrates2/README.md`). Der Kern wird nie mit `systemctl restart` neu gestartet.

## 5. Ausgang prüfen

Der Kern läuft als `wamo-core` und muss `wamocon.atlassian.net` über HTTPS erreichen. Prüfung ohne Token (erwartet eine Zahl wie `200`; `000`
heißt kein Weg nach draußen):

```bash
ssh wamo-sokrates2 "sudo -n -u wamo-core curl -sS -o /dev/null -w '%{http_code}\n' --max-time 10 https://wamocon.atlassian.net/status"
```

## 6. Einschalten

1. Kern-Release mit dem Stand dieses Pakets ausrollen (Schalter noch aus) und die Oberfläche verteilen.
2. Schalter an:

   ```bash
   printf 'WAMO_JIRA=an\n' | ssh wamo-sokrates2 "sudo -n /usr/local/sbin/wamo-core-env setzen"
   ```

3. Nächstes Kern-Release über die Slots. Im Journal steht danach keine Zeile "Jira-Stories aus" (die erscheint, wenn eine Einstellung fehlt
   oder ungültig ist; sie nennt nur den Namen, nie den Wert).

## 7. Rauchtest mit Niko

1. In W.A.I.S. als Admin im Büro ein Dokument aufs Canvas legen lassen, zum Beispiel "Rauchtest W.A.I.S. Jira", mit einem Abschnitt
   `## Akzeptanzkriterien` und zwei Punkten.
2. Im Kopf des Dokuments steht "Als User Story in Jira". Klicken: Die Karte "Jira-Story freigeben" zeigt Projekt `WMCNL` mit Namen, Typ Story,
   Epic keins, Titel, jede Zeile der Beschreibung mit vorangestelltem Größer-Zeichen und die Kriterien nummeriert.
3. "Freigeben": Unter der Karte erscheint "Angelegt als WMCNL-…" mit dem Verweis "… in Jira öffnen". In Jira prüfen: Autor ist der technische
   Benutzer, Beschreibung mit Überschrift, Liste und Abschnitt "Akzeptanzkriterien", keine Zuweisung.
4. Per Sprache mit Epic: "Leg das Dokument Rauchtest als Story an, Epic `WMCNL-<Nummer eines Epics>`". Die Karte zeigt das Epic mit Titel;
   nach "Freigeben" hängt die Story in Jira unter dem Epic ("Übergeordnet"). Meldet Jira beim Anlegen mit Epic eine Ablehnung, fehlt dem
   Benutzer vermutlich ein Recht am Epic; dann ohne Epic anlegen und das Recht prüfen (nicht in der Doku von Atlassian belegt, nur am Gerät).
5. "Ablehnen" auf einer weiteren Karte: W.A.I.S. sagt, dass nichts angelegt wurde.
6. Die Test-Stories danach mit deinem eigenen Konto löschen (der technische Benutzer darf das nicht).
7. Journal ohne Geheimnis: `ssh wamo-sokrates2 "sudo -n journalctl -u 'wamo-core@*' --since -30min | grep -c ATATT"` muss `0` ergeben.

## 8. Widerruf und Rückweg

- **Sofort (wirkt in Sekunden):** als technischer Benutzer unter `id.atlassian.com`, "Sicherheit", "API-Token" das Token widerrufen, oder in
  `admin.atlassian.com` den Benutzer deaktivieren. Danach antwortet Jira mit 401, und W.A.I.S. sagt "Jira hat die Anmeldung abgelehnt".
- **Danach:** Schalter aus und Werte entfernen, wirksam mit dem nächsten Kern-Release:

  ```bash
  printf 'WAMO_JIRA=aus\n' | ssh wamo-sokrates2 "sudo -n /usr/local/sbin/wamo-core-env setzen"
  ssh wamo-sokrates2 "sudo -n /usr/local/sbin/wamo-core-env loeschen WAMO_JIRA_TOKEN WAMO_JIRA_EMAIL"
  ```

- **Code zurück:** `rueckweg-kern` über die Slots und die vorige Oberfläche. Es gibt keine Migration, also keinen Rückweg in der Datenbank.
- **Token erneuern:** neues Token erzeugen (Schritt 3), nur `WAMO_JIRA_TOKEN` neu setzen (Schritt 4 mit einer Zeile), nächstes Kern-Release,
  dann das alte Token widerrufen.

---

WAMOCON GmbH, Mergenthalerallee 79-81, 65760 Eschborn
