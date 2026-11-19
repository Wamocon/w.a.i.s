# Konfiguration: Betriebsskripte und Einrichtungsvariablen

| | |
|---|---|
| Zweck | Listet die `WAMO_*`-Variablen, die nur die Einrichtungs- und Betriebsskripte unter `infra/` und `scripts/` lesen, sowie die Konfiguration der Dienste auf Sokrates-2, soweit sie im Code belegt ist. |
| Zielgruppe | Administratoren und Betriebsverantwortliche. |
| Dokumentart | Referenz |
| Stand | 19.11.2026, geprüft gegen Commit 497e3ce |
| Quellen | `infra/sokrates2/` (Skripte, Units, `wamo_job_dispatch.py`, `release/quelle.py`, `anker/freigabe_dienst.py`), `infra/sparks/`, `scripts/` |

Die Variablen des Kerns, der Oberfläche, des Hosts und der Desktop-App stehen in [konfiguration.md](konfiguration.md). Hier stehen nur Namen, Zweck und Standardwerte aus dem Code, nie Werte von Geheimnissen, Adressen interner Systeme oder Zugangsdaten. Die Bedeutung folgt aus dem Kommentar am Lesepunkt. Wo er fehlt, steht "Zweck nicht belegt". Betriebsabläufe: [../betrieb/betriebshandbuch.md](../betrieb/betriebshandbuch.md).

## 1. Probeläufe ohne root (Tests der Einrichtungsskripte)

Ein gesetzter `*_WURZEL`-Wert leitet das Skript auf einen Wegwerf-Ordner statt auf das echte System. Ein Probelauf läuft nie als root (belegt für `anker-einrichten.sh`). Die übrigen Skripte folgen laut `CLAUDE.md` demselben Muster.

| Name | Skript | Zusatz |
|---|---|---|
| `WAMO_ANKER_WURZEL`, `WAMO_ANKER_PYTHON` | `anker-einrichten.sh` | Python für den Probelauf |
| `WAMO_FREIGABE_WURZEL`, `WAMO_FREIGABE_PYTHON` | `freigabe-einrichten.sh` | wie oben |
| `WAMO_PRUEFER_WURZEL`, `WAMO_PRUEFER_PYTHON` | `pruefer-einrichten.sh` | wie oben |
| `WAMO_RELEASE_WURZEL`, `WAMO_RELEASE_PYTHON` | `release-einrichten.sh` | wie oben |
| `WAMO_VERTEILUNG_WURZEL`, `WAMO_VERTEILUNG_PYTHON` | `wamo-verteilung-einrichten.sh` | Installer vom Server |
| `WAMO_JOB_KERN_WURZEL`, `WAMO_JOB_KERN_PYTHON`, `WAMO_JOB_KERN_SUCHFRIST_S` | `wamo-job-kern-einrichten.sh`, `wamo-job-kern-rueckweg.sh` | Suchfrist in Sekunden |
| `WAMO_JOB_WURZEL` | `wamo-job-einrichten.sh` | Dispatcher |
| `WAMO_HAUS_PROXY_WURZEL` | `wamo-haus-proxy-einrichten.sh` | Haus-Proxy |
| `WAMO_LABOR_DATEN_WURZEL`, `WAMO_LABOR_DATEN_LADER`, `WAMO_LABOR_DATEN_PYTHON` | `wamo-labor-daten-einrichten.sh` | Lader für die Prüfung |
| `WAMO_LABOR_WURZEL`, `WAMO_LABOR_HEUTE`, `WAMO_LABOR_HERKUNFT` | `wamo-labor-loeschlauf.sh`, `wamo-labor-einrichten.sh` | `HEUTE` als Datum `JJJJMMTT`; `HERKUNFT=ja` erzwingt den Herkunftsschutz auch im Probelauf |
| `WAMO_LABOR_GERAETE_WURZEL`, `WAMO_LABOR_GERAETE_JETZT` | `wamo-labor-geraete-aktualisieren.sh` | Betreuer-Geräte |
| `WAMO_AUTH_DB_CONTAINER`, `WAMO_AUTH_SQL_DIR` | `wamo-auth-einrichten.sh` | Datenbank-Container und SQL-Ordner für die Probe |
| `WAMO_CADDY_ETC`, `WAMO_DROPIN_ALT`, `WAMO_DROPIN_NEU` | `wamo-core-slots.sh` | Ordner der Caddy-Einbindung (nur Tests) und Drop-in-Pfade |
| `WAMO_RD_AUSGANG_WURZEL`, `WAMO_RD_KONTO_WURZEL`, `WAMO_RD_ZIEL_WURZEL`, `WAMO_XRDP_WURZEL`, `WAMO_SUDO_WURZEL` | `infra/sparks/*.sh` | Skripte auf den Sparks |

## 2. Server und Benutzer `wamo`

| Name | Zweck | Standard | Quelle |
|---|---|---|---|
| `WAMO_USER`, `WAMO_HOME` | Benutzer und Heimatordner der Aufträge | `wamo`, `/srv/wamo` | `infra/sokrates2/wamo-einrichten.sh` |
| `WAMO_GH_APP_ID`, `WAMO_GH_APP_INSTALLATION_ID`, `WAMO_GH_APP_SCHLUESSEL` | GitHub-App des Benutzers `wamo` (Schlüssel ist ein Geheimnis) | leer | `infra/sokrates2/wamo-einrichten.sh` |
| `WAMO_GIT_NAME`, `WAMO_GIT_EMAIL` | Autor der Commits aus Aufträgen | nicht belegt | `infra/sokrates2/wamo-einrichten.sh` |
| `WAMO_UID` | Platzhalter `@WAMO_UID@` in der Vorlage `wamo-egress.nft`, ersetzt von `wamo-job-einrichten.sh` | gesetzt vom Skript | `infra/sokrates2/wamo-egress.nft` |
| `WAMO_JOBS_FROM_EXTRA` | zusätzliche Quelladresse im `from=` des Dispatcher-Schlüssels (ergänzt das Büro-LAN) | leer | `infra/sokrates2/wamo-job-einrichten.sh` |
| `WAMO_PC_FROM_EXTRA`, `WAMO_PC_FROM`, `WAMO_TUNNEL_FROM_EXTRA` | dasselbe für den PC-Tunnel und den alten Tunnel; `WAMO_PC_FROM` ist das Ergebnis im Skript | leer | `infra/sokrates2/wamo-pc-tunnel-einrichten.sh`, `wamo-tunnel-einrichten.sh` |
| `WAMO_PC_SCHEMA`, `WAMO_DB_CONTAINER` | Schema (`wamo_dev`, `wamo_test`, `wamo_prod`) und Container für die Geräteliste beim ersten Einrichten | automatisch | `infra/sokrates2/wamo-pc-tunnel-einrichten.sh` |
| `WAMO_MODUS`, `WAMO_PORT_VON`, `WAMO_PORT_BIS`, `WAMO_ZWEIG`, `WAMO_GITHUB` | Sandbox je Auftrag: Modus (`klon`, `ausgabe`, `pruefung`), Portbereich, Zweig, persönlicher GitHub-Weg | gesetzt von `wamo-job.sh` | `infra/sokrates2/wamo-job.sh`, `wamo-job-klon.sh` |

## 3. Dispatcher (Aufträge)

Diese Namen liest `infra/sokrates2/wamo_job_dispatch.py` aus der Datei `/etc/wamo/geheim.env` laut Kommentaren im Code. Namen mit unbekannter Fortsetzung (`WAMO_SERVER...`, `WAMO_PRUEF...`, `WAMO_HAU...`) sperren die Zugangsart (Schutz gegen Tippfehler).

| Name | Zweck | Standard |
|---|---|---|
| `WAMO_SERVERZUGANG` | `aus` schaltet den Zugang des Servers ab, sobald jedes Profil einen eigenen hat | an (fail-closed gegen Tippfehler) |
| `WAMO_HAUS` | Zugangsart `haus` mit Hausmodellen über den Haus-Proxy; nur `an` schaltet ein | aus |
| `WAMO_HAUS_MAX_TOKEN` | Höchstmenge Token je Lauf, die der Proxy durchsetzt | 3000000 |
| `WAMO_PRUEFEN` | Dispatcher-Befehl `pruefen` für Befehlskriterien (ab Dispatcher 6) | aus |

Der Haus-Proxy liest seine Einstellungen aus einer Datei ohne Geheimnisse (`proxy.env`) und den Schlüssel für das Gateway aus einer eigenen Datei als Credential. Namen laut `CLAUDE.md`: `MODELLE` (Standard `wamo-haus-coder,qwen3.6-35b`), `PARALLEL` (2), `TAG_TOKEN_MAX`, `FELDER_ERLAUBT`. Quelle: `infra/sokrates2/wamo_haus_proxy.py`.

## 4. Release, Quelle, Freigabe-Dienst

| Name | Zweck | Standard | Quelle |
|---|---|---|---|
| `WAMO_RELEASE_SCHEMA` | Schema des Release-Dienstes | nicht belegt | `infra/sokrates2/release/wamo-release.service` |
| `WAMO_QUELLE_URL`, `WAMO_QUELLE_REPO`, `WAMO_QUELLE_PROXY` | Quelle der Releases: Adresse, Repo, optionaler Proxy | Repo `wamo` | `infra/sokrates2/release/quelle.py` |
| `WAMO_QUELLE_APP_ID`, `WAMO_QUELLE_INSTALLATION_ID`, `WAMO_QUELLE_PEM` | GitHub-App für den Zugriff auf die Quelle (`PEM` ist ein Geheimnis, nur der Name) | nicht belegt | `infra/sokrates2/release/quelle.py` |
| `WAMO_FREIGABE_SCHEMA`, `WAMO_FREIGABE_JWKS_URL`, `WAMO_FREIGABE_ISS`, `WAMO_FREIGABE_AUD` | Freigabe-Dienst: Schema, Schlüsselquelle, Aussteller und Zielgruppe der geprüften Tokens (`AUD` Standard `authenticated`) | `AUD`: `authenticated` | `infra/sokrates2/anker/freigabe_dienst.py` |
| `WAMO_FREIGABE_PEERS` | erlaubte Benutzerkennungen der Gegenseite am Socket | `0` | `infra/sokrates2/anker/freigabe_dienst.py` |

Konfiguration kommt hier "nur aus der Unit (Umgebung)" laut Modulbeschreibung, die Zugangsdatei und das Zertifikat liegen fest.

## 5. Firewall

| Name | Zweck | Standard |
|---|---|---|
| `WAMO_FW_CONF` | Konfigurationsdatei der Firewall | `/etc/wamo/firewall.conf` |
| `WAMO_FW_HTTP_NUR_INTERN` | `nein`: Stufe 1, Port 55321 auch aus dem Büro-LAN (Übergang); `ja`: Stufe 2, nur Loopback und Caddy-Netz. Gelesen aus der Konfigurationsdatei, ungültige Werte brechen ab. | `nein` (nicht belegt als Konstante) |
| `WAMO_FW_LABOR_QUELLEN` | Datei mit den Quelladressen der Laborplätze | `/etc/wamo-labor/plaetze-adressen` |
| `WAMO_FW_ADMIN_QUELLEN` | Datei mit den Quelladressen der Administratoren | `/etc/wamo/admin-quellen` |
| `WAMO_FW_RD_ZIELE` | Zieldatei des Remote-Desktop-Gateways | `/etc/wamo-rd/ziele.toml` |

## 6. Oberfläche auf Sokrates-2 (blau und grün)

Skripte `wamo-ui-einrichten.sh` und `wamo-ui-umschalten.sh` (Umschaltlogik, Rauchtest `wamo_ui_rauchtest.py`).

| Name | Zweck |
|---|---|
| `WAMO_UI_PRAEFIX` | Namenspräfix der Container: nichts (Betrieb: `wamo-`) oder `wamo-test-NAME-` (nur Rauchtest) |
| `WAMO_UI_BASIS`, `WAMO_UI_CADDY_DIR`, `WAMO_UI_QUELLE`, `WAMO_UI_BAUDATEI`, `WAMO_UI_BAUKONTEXT` | im Testmodus Pflicht: Arbeitsordner, Caddy-Ordner, Quelle, Build-Datei und Build-Kontext |
| `WAMO_UI_BEREIT_S` | Wartezeit in Sekunden bis zur Bereitschaft (1 bis 3 Ziffern) |
| `WAMO_UI_BILD`, `WAMO_UI_NETZ` | Image und Netz der Container |
| `WAMO_UI_TLS`, `WAMO_UI_HSTS` | Einstellungen beim Einrichten (Zweck im Detail nicht belegt) |

## 7. Remote Desktop (Gateway)

Skripte `wamo-rd-einrichten.sh`, `wamo-rd-rueckweg.sh`, Compose-Datei `infra/sokrates2/wamo-rd/docker-compose.yml`, Dienst `wamo-rd/zugang/`. Die Platzhalter mit Vorgabe (`WAMO_RD_PRAEFIX`, `*_NETZ`, `*_SUBNETZ`, `WAMO_RD_KEY`) setzt nach dem Kommentar der Compose-Datei nur der Rauchtest.

| Name | Zweck |
|---|---|
| `WAMO_RD_BASIS`, `WAMO_RD_HOME`, `WAMO_RD_RUN`, `WAMO_RD_CADDY_DIR`, `WAMO_RD_CA` | Ordner und Dateien des Gateways, Caddy-Einbindung, CA |
| `WAMO_RD_UID`, `WAMO_RD_GID`, `WAMO_RD_KERN_UID` | Benutzer- und Gruppenkennungen |
| `WAMO_RD_PRAEFIX`, `WAMO_RD_NETZ`, `WAMO_RD_GUACD_NETZ`, `WAMO_RD_ZIEL_NETZ`, `WAMO_RD_GUACD_SUBNETZ`, `WAMO_RD_ZIEL_SUBNETZ`, `WAMO_RD_GUACD_IP`, `WAMO_RD_ZUGANG_IP`, `WAMO_RD_VERTRAUT`, `WAMO_RD_PROXY_REGEX`, `WAMO_RD_GUAC_HOST`, `WAMO_RD_GUAC_PORT`, `WAMO_RD_UPSTREAM` | Namen und Adressräume der Container-Netze, vertrauenswürdiges Netz, Weiterleitung (Werte stehen in der Compose-Datei, hier bewusst nicht) |
| `WAMO_RD_ZIELE_DATEI`, `WAMO_RD_ZIEL`, `WAMO_RD_ZIEL_SCHLUESSELGRUPPE`, `WAMO_RD_PASSWORT_NAME` | Zieldatei, Ziel, Schlüsselgruppe des Zielkontos, Name der Passwortdatei (nie ein Wert) |
| `WAMO_RD_AUFSEHER_TAKT`, `WAMO_RD_GETRENNT_SECS`, `WAMO_RD_NICHT_GEOEFFNET_SECS`, `WAMO_RD_MEHRFACH_SECS` | Zeiten der Aufsicht im Zugangsdienst: Takt, Frist nach Trennung, Frist für nicht geöffnete Sitzungen, Sperre gegen Mehrfachstarts |
| `WAMO_XRDP_QUELLE`, `WAMO_XRDP_WURZEL` | Quelle und Wurzel für xrdp auf den Sparks |

## 8. Testlabor (Betrieb)

| Name | Zweck | Standard |
|---|---|---|
| `WAMO_LABOR_QUELLE` | Quellordner des Dienstes für `wamo-labor-einrichten.sh` | Ordner im Heimatverzeichnis des Betriebsbenutzers |
| `WAMO_LABOR_CA`, `WAMO_LABOR_CADDY_DIR` | CA-Datei und Caddy-Ordner für die Site `wamo-labor.caddy` | nicht belegt |
| `WAMO_LABOR_WARTE_RUNDEN`, `WAMO_LABOR_WARTE_SEKUNDEN` | Wartegrenzen beim Start des Containers | 60 Runden, 2 s |
| `WAMO_LABOR_BASIS_IMAGE`, `WAMO_LABOR_ETC`, `WAMO_LABOR_STAND` | in `wamo-labor/docker-compose.yml`: Basis-Image, Konfigurationsordner, Stand | nicht belegt |

Die Variablen `WAMO_LABOR_DIENST_*` des Dienstes selbst stehen in [konfiguration.md](konfiguration.md), Abschnitt 15.

## 9. Messskripte und Hilfen (`scripts/`)

| Name | Zweck |
|---|---|
| `WAMO_MESS_DIR`, `WAMO_MESS_FEST` | Ordner und Festlegung der Latenzmessung (`scripts/wamo-latenz-messen.cjs`, `wamo-stimme-messen.cjs`) |
| `WAMO_PYTHON`, `WAMO_REPO` | Python und Repo für die Messskripte |
| `WAMO_SPRECH_TEXT`, `WAMO_SPRECH_ZIEL` | Text und Ziel für Sprechproben der Laststrecke (`scripts/wamo_labor_last.py`) |
| `WAMO_LABOR_PLATZ_TOKEN` | Platz-Token für die Abnahme (Geheimnis, nur der Name; `scripts/wamo_labor_abnahme.py`) |
| `WAMO_SSH_HOST` | SSH-Alias für `scripts/wamo_db_rolle.py` |

## Weiterführend

- [Konfiguration (Kern, Oberfläche, Host, Desktop)](konfiguration.md)
- Betrieb: [../betrieb/betriebshandbuch.md](../betrieb/betriebshandbuch.md), [../betrieb/release-und-ausrollen.md](../betrieb/release-und-ausrollen.md), [../betrieb/administrationshandbuch.md](../betrieb/administrationshandbuch.md)
- Bestehende Dokumente: `infra/sokrates2/README.md`, [../../remote-desktop.md](../../remote-desktop.md), [../../runner-einrichten.md](../../runner-einrichten.md), [../../labor-runbook.md](../../labor-runbook.md)
