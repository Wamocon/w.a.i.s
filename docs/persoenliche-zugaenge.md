# Persönliche Zugänge für Entwicklungsaufträge (GitHub, Vercel, später Supabase und Konnektoren)

> **Planpapier, Stand 18.11.2026 nach Sicherheitsreview**, Basis `main` 4d41a1c, Zweig `docs/persoenliche-zugaenge-plan`. Dieses Papier ändert weder Code noch Server.
> Kennzeichnung wie in `docs/folgepaket-1.md`: **B** belegt (Datei:Zeile im Arbeitsbaum der Basis), **A** abgeleitet, **Annahme** nicht belegt (Prüfstelle in 2.3).
> Pfade relativ zur Repo-Wurzel, Bezeichner in ASCII. Schritte, die nur der Admin ausführen kann, heißen **Admin, manuell**. Die Pakete heißen PZ-0 bis PZ-16 (Abschnitt 4).
>
> **Entschieden am 18.11.2026: Plan C.** Der Abschnitt „Plan C“ direkt hierunter ist die verbindliche Bauvorlage bis zum Freeze (Pakete S, K, D-a, D-b, R). Alles ab
> „Kurzfassung der Ausbaustufe“ beschreibt Plan A und B mit Zugangsdienst, Git-Tor und Geräteschlüssel; das ist die Ausbaustufe für nach dem Labortag am 05.12.

## Plan C (entschieden 18.11.2026)

**Kurzfassung.** Das GitHub-Token der Person wird wie der persönliche Claude-Zugang gespeichert (AES-256-GCM mit `WAMO_SCHLUESSEL_KEK`, eigener Zweck in der AAD), der Kern
entschlüsselt es je Aufruf frisch und gibt es dem Dispatcher nur über stdin. Der Dispatcher klont damit **außerhalb der Sandbox** als bare Repo in den Auftragsordner, prüft und
bereinigt den Klon und verwirft das Token, bevor die Sandbox startet. Die Arbeitskopie entsteht **in einem netzlosen Sandbox-Schritt** aus diesem bare Repo, danach entschärft
der Dispatcher den Projektordner wie heute. Die Sandbox hat keinen GitHub-Zugang und committet nur lokal auf `wamo/<job>`. Am Laufende exportiert ein netzloser Schritt die Commits
als Bundle, ein zweiter netzloser Schritt **ohne Projektordner** liest das Bundle und gibt nur eine Dateiliste mit den Inhalten zurück. Der Dispatcher prüft diese Bytes und baut
daraus mit eigenem git **einen** Commit (Autor die Person, Trailer mit dem Auftrag); er verarbeitet selbst nie Git-Objekte aus der Sandbox und führt nie git mit der Konfiguration
oder den Hooks eines Repos aus, das die Sandbox beschrieben hat. Erst nach dem Klick auf der Freigabekarte schickt der Kern das Token erneut, und der Dispatcher pusht genau
`<commit>:refs/heads/wamo/<job>` (nie Force, nie ein anderer Ref, nie Tags) und öffnet den Pull Request per API. Gemergt wird nie durch W.A.I.S. Alles steht hinter Schaltern, die
standardmäßig aus sind, der App-Weg bleibt unverändert.

**IQ:** Das Token liegt nur kurz im Speicher von Kern, Dispatcher und einem git-Prozess, nie in einer Umgebung, nie in der Sandbox, nie in einer Datei, nie in argv. Alles, was
feindlich sein kann (Arbeitskopie, Hooks, Konfiguration, Checkout, Pack-Daten der Sandbox), läuft in netzlosen Sandbox-Schritten; außerhalb verarbeitet der Dispatcher nur geprüfte
Dateibytes und eigene Repos. **EQ:** Die Person hinterlegt ihr Token einmal, sieht danach nur Konto, Art und Ablauf, und gibt jede Veröffentlichung auf der vertrauten Freigabekarte
frei. **VQ:** Ablaufbild, Schnittstellentabellen, Zustandsautomat, Fehlertabelle, Paketliste mit getrennten Dateien. **Synthese:** Plan C ist bis Sonntag knapp baubar, wenn Paket D
auf zwei Agenten verteilt wird und die Zweige `feat/auftrag-speichern` und `feat/fp1-1-expiry-time` vorher gemergt sind (C.9); der gekaperte Kern bleibt bewusst als Restrisiko wie
beim Claude-Zugang.

### C.0 Entscheidungen (verbindlich)

| Nr. | Entscheidung |
| --- | --- |
| C1 | Das GitHub-Token kommt nie in die Sandbox. Gespeichert verschlüsselt wie der persönliche Claude-Zugang (`voice-core/modellzugang.py`, `dev_agent.persoenlicher_zugang`), je Aufruf frisch entschlüsselt, an den Dispatcher nur über stdin, nie in Argumenten oder Log |
| C2 | Der Dispatcher klont außerhalb der Sandbox mit dem Token (Credential-Helfer oder `GIT_ASKPASS`, nie in der URL), entfernt danach alle Zugangsdaten und gibt den Arbeitsordner an die Sandbox. Die Sandbox committet nur lokal (Autor GitHub-Login und noreply-Adresse der Person, Trailer mit Auftrags-ID) |
| C3 | Erst nach dem Klick auf der Freigabekarte pusht der Dispatcher außerhalb der Sandbox mit fester Refspec nur `refs/heads/wamo/<job>` (nie Force, nie ein anderer Ref, nie Tags) und öffnet den Pull Request per API. Kein Merge durch W.A.I.S. |
| C4 | Restrisiko gekaperter Kern (sieht das entschlüsselte Token) ist bewusst akzeptiert, wie beim Claude-Zugang |
| C5 | Klassische Tokens nur mit Ablaufdatum (höchstens 366 Tage) und ohne `delete_repo`, `admin:*`, `site_admin`, Paket- und `user`-Rechte; fein-granulare Tokens mit Ablauf. Prüfung beim Speichern (`GET /user`, Kopfzeilen zu Ablauf und Scopes), Login anzeigen, Wert nie wieder anzeigen |
| C6 | Lesen und Pull Requests in allen Repos, auf die das Token Zugriff hat, außer dem eigenen Repo (`SELF_REPOS`, `SELF_REPO_IDS`, auch Forks und Vorlagen davon) |
| C7 | Vercel und Supabase erst nach dem 05.12. Laborprofile nie; Mitglieder nur mit ihrer bestehenden Zulassung für Entwicklungsaufträge |
| C8 | Alles hinter einem Schalter (Standard aus), App-Weg unverändert |

**Umsetzung von C2 und C3 im Detail (begründet):** „Arbeitsordner an die Sandbox geben“ heißt, dass der Dispatcher ein bare Repo ohne Arbeitsbaum klont und die Arbeitskopie in
einem Sandbox-Schritt ohne Netz daraus entsteht; so läuft kein Checkout, kein Filter und kein Hook des Repos außerhalb der Sandbox. „Pusht nur `wamo/<job>`“ heißt, dass der
Dispatcher einen eigenen Commit aus dem Dateistand der lokalen Spitze baut (Eltern die Basis). Gepusht werden damit nie Zwischenstände der Sandbox (ein Geheimnis in Commit 1, in
Commit 2 gelöscht, wäre sonst im Pull Request), nie Metadaten der Sandbox (Autor, Trailer, Nachricht) und nie Git-Objekte, die die Sandbox gebaut hat.

### C.1 Ablauf

```text
Hinterlegen  Oberfläche ── POST /wamo/api/github-zugang {aktion: speichern, token} ──> Kern: Form, GET /user, Regeln C5, Chiffrat in github_zugang
Start        Kern ── ssh "start <job> <projekt> <art>" ──> Dispatcher 10
             stdin: Kopfzeile {..., "github": "persoenlich"}, [Claude-Zeile], GitHub-Zeile (nur solange der Kern für den Auftrag kein Ereignis github kennt)
             Dispatcher: Regeln 1-9, GitHub-Prüfung, git clone --bare --single-branch nach JOBDIR/basis.git über den Helfer, Prüfung auf Token-Reste, Token verworfen
             Sandbox-Schritt klon (ohne Netz): Projektordner leeren, Arbeitskopie aus basis.git, Zweig wamo/<job>
             Dispatcher: projekt_entschaerfen (wie heute), Selbsttest, Lauf ohne GitHub-Zugang; lokale Commits auf wamo/<job>
             Dispatcher: projekt_entschaerfen; Sandbox-Schritt ausgabe (ohne Netz, Projekt nur lesend): git bundle create
             Sandbox-Schritt pruefung (ohne Netz, ohne Projektordner): Bundle lesen, Dateiliste und Inhalte nach JOBDIR/ergebnis
             Dispatcher (ohne Token): Bytes prüfen, Commit mit eigenem git in aus.git bauen, aenderung.json, Ereignis aenderung
Karte        Kern zeigt die Freigabekarte "Einreichen" (Daten aus dem Ereignis aenderung)
Einreichen   Klick (nur UI-Nachricht) ── Kern entschlüsselt frisch ── ssh "einreichen <job> <profil>" ──> Dispatcher
             stdin: {commit_id, tree_id, bestaetigt}, GitHub-Zeile
             Dispatcher: Zustand, Bindung, Konto, Scopes, Repo-ID, Geheimnissuche mit dem Token, ls-remote, push aus aus.git, PR, Ereignis eingereicht
```

### C.2 Schnittstelle Kern zu Dispatcher

**C.2.1 Kopfzeile von `start`.** Neues optionales Feld `github` mit dem einzigen Wert `"persoenlich"` (fehlt es, gilt der App-Weg wie heute). `parse_header` nimmt es nur im
Kanal `kern` an; im Kanal `pc` und `lokal` ist es `Abgewiesen` (Kopfzeile: github nur im Kern-Kanal). Pflicht dazu: `repo` und `profil`. Der Wert wird in `auftrag.json` gebunden
wie Projekt, Art, Repo und Profil: Ein Folgelauf mit anderem `github` (auch ohne Feld) wird abgewiesen. Der Kern schickt das Feld nur, wenn `ping` `"version": "10"` und
`"persoenlich": true` meldet.

**C.2.2 stdin-Zeilen von `start`.** Feste Reihenfolge, JSON-Objekt, Zeilenende `\n`:

| Zeile | Wann | Inhalt |
| --- | --- | --- |
| 1 | immer | Kopfzeile (C.2.1), wie heute höchstens `MAX_HEADER_BYTES` |
| 2 | nur bei `"zugang": "folgt"` | Claude-Zeile wie heute (`{"typ", "wert", "workspace"}`), höchstens 2048 Byte |
| 2 oder 3 | bei `"github": "persoenlich"`, solange der Kern für diesen Auftrag noch kein Ereignis `github` erhalten hat | GitHub-Zeile `{"typ":"github","wert":"<token>"}`, genau diese Form ohne Leerzeichen, höchstens 256 Byte, `wert` passt auf `ghp_[A-Za-z0-9]{36}` oder `github_pat_[A-Za-z0-9_]{82}` |

**Lesen ohne Kopien.** Im persönlichen Weg liest der Dispatcher stdin von Anfang an mit einem eigenen Leser (`os.readv` bzw. `readinto` in ein `bytearray`, kein `sys.stdin`,
kein `readline`). Die GitHub-Zeile wird nie zu `str` oder `bytes` gewandelt: Prüfung mit einer Bytes-Regel auf einem `memoryview`, der Wert geht direkt in die Pipe des
Credential-Helfers (C.5 Start 3) und das `bytearray` wird danach überschrieben. Vor dem Lesen setzt der Dispatcher `PR_SET_DUMPABLE=0` (prctl) und `RLIMIT_CORE=0`: Seine
`/proc`-Einträge gehören dann root, ein Prozess desselben Benutzers (etwa eine ausgebrochene Sandbox) kann Speicher und Umgebung nicht lesen. Fehlt die Zeile, obwohl kein
`basis.git` existiert, endet `start` mit `start_abgelehnt`, Grund `github_zeile`, Exit 8; der Kern startet einmal neu mit Zeile. Ist sie da, obwohl `basis.git` existiert, wird sie
ungelesen verworfen. Fehlertexte nennen nie den Inhalt.

**C.2.3 Neue Befehle** (passen zu `COMMAND_RE`, nur im Kern-Kanal, im PC-Kanal `befehl`, im Kanal `lokal` nur für Rauchtests):

| Befehl | stdin | Antwort |
| --- | --- | --- |
| `aenderung <job> <profil>` | nichts | Ereignis `aenderung` aus `aenderung.json`, rechnet nie neu. Auch bei geschlossenem Kanal, nicht bei Notaus |
| `einreichen <job> <profil>` | Zeile 1 `{"commit_id": "<40 Hex>", "tree_id": "<40 Hex>", "bestaetigt": ["<pfad>", ...]}` höchstens 64 KiB, Zeile 2 GitHub-Zeile | Ereignis `eingereicht` oder `einreichen_fehler`, Exit 0 oder 2 |
| `verwerfen <job> <profil>` | nichts | Ereignis `verworfen`; nur aus `keine`, `gesperrt`, `nur_lesen`, `bereit`, unter den Sperren `.lauf` und `.einreichen`; löscht `aus.git`, `ergebnis/`, Bundle und `basis.git`, nie den Projektordner (er gehört dem Eigner, C.10). Auch bei geschlossenem Kanal |

`profil` ist bei allen drei Pflicht; Regel 4 prüft zusätzlich, dass es mit `auftrag.json` übereinstimmt (sonst `fremd`). `BEFEHLE_KERN` bekommt die drei Befehle,
`BEFEHLE_GESCHLOSSEN` bekommt `aenderung` und `verwerfen`. `einreichen` löst der Kern nur auf die UI-Nachricht `einreichen` aus, nie als Werkzeug des Sprachmodells (Test).

**C.2.4 Ereignisse im Datenstrom** (`{"type": "wamo", "ereignis": ...}`):

| Ereignis | Wann | Felder |
| --- | --- | --- |
| `github` | nach Klon und Prüfung, vor dem Lauf | `repo`, `konto` (Login), `basis` (Commit-ID), `standardzweig`, `privat` (bool), `schreiben` (bool: Art schreibend und `permissions.push`) |
| `start_abgelehnt` | GitHub-Teil gescheitert | `grund` aus `GITHUB_GRUENDE`, Exit 8 |
| `aenderung` | am Laufende und auf `aenderung` | `job`, `status` (C.5.1), `commit_id`, `tree_id`, `basis`, `zweig` (`wamo/<job>`), `dateien`, `plus`, `minus`, `liste` (Einträge `pfad`, `art` `neu`, `geaendert` oder `geloescht`, `klasse` `normal` oder `sensibel`, `plus`, `minus`; sensible zuerst und vollständig, insgesamt höchstens 200), `nicht_gelistet`, `gruende` (aus `AENDERUNG_GRUENDE`), `ungesichert` (Zahl nicht committeter Dateien), `lauf` (`fertig`, `zeitlimit`, `fehler`), `titel`, `pr`, `adresse` (bei `branch_gepusht` und `eingereicht`) |
| `eingereicht` | nach Push und Pull Request | `job`, `zweig`, `pr` (Nummer), `adresse` |
| `einreichen_fehler` | sonst | `job`, `grund` aus `EINREICHEN_GRUENDE` oder `KANAL_GRUENDE` |
| `verworfen` | nach `verwerfen` | `job` |

Der Kern prüft `adresse` gegen `^https://github\.com/<repo>/pull/[0-9]+$` und gibt `titel`, Pfade und Adressen nie an das Sprachmodell, nur an Canvas und Karte.

**C.2.5 Zähler in `kernkanal.jsonl`.** `EREIGNISSE` wird zu `("start", "ende", "versuch", "einreichen", "eingereicht")` (unbekannte Ereignisse überspringt `zaehler_lesen`
schon heute, der Rückweg ist sicher). `einreichen`: jeder Aufruf, der bis zum Push kommt (Schritt 6), Felder `t`, `job`, `ereignis`, `profil`; zählt gegen `MAX_EINREICHEN_TAG`
und `MAX_EINREICHEN_TAG_PROFIL`. Fehlklicks vor dem Push zählen nicht gegen diese Grenzen, aber als `versuch` gegen `MAX_VERSUCH_STUNDE_PROFIL`. `eingereicht`: nach Erfolg,
zusätzlich `pr` (Nummer). Kein Token, kein Repo-Inhalt.

**C.2.6 Gründe.** Alle Listen sind die feste Schnittstelle; `voice-core/test_kernkanal_vertrag.py` hält Dispatcher und Kern gleich.

| Liste (Dispatcher) | Neue Codes | Sätze im Kern (`voice-core/entwicklung_betrieb.py`) |
| --- | --- | --- |
| `KANAL_GRUENDE` (ergänzt) | `persoenlich_aus`, `grenze_einreichen` | in `GRUND_SAETZE`: „Persönliche GitHub-Zugänge sind im Kanal nicht eingeschaltet.“, „Für heute sind genug Änderungen eingereicht.“ |
| `GITHUB_GRUENDE` (neu) | `github_zeile`, `token_ungueltig`, `token_abgelaufen`, `token_rechte`, `repo_nicht_erreichbar`, `eigenes_repo`, `repo_zu_gross`, `klon_fehler`, `bereinigung`, `projekt_gewechselt`, `github_wechsel` | `GITHUB_SAETZE`, je ein Satz |
| `AENDERUNG_GRUENDE` (neu) | `pfad_gesperrt`, `geheimnis`, `zu_gross`, `zu_viele_commits`, `symlink`, `sonderdatei`, `basis_fehlt`, `bundle_ungueltig`, `pruefung_fehler`, `schon_eingereicht` | `AENDERUNG_SAETZE` |
| `EINREICHEN_GRUENDE` (neu) | `zustand`, `veraltet`, `bestaetigung`, `konto`, `token_rechte`, `repo_geaendert`, `keine_schreibrechte`, `zweig_belegt`, `geheimnis`, `token_abgelaufen`, `github_fehler` | `EINREICHEN_SAETZE` |

**C.2.7 Konfiguration und Schalter.** `kernkanal.conf`: `PERSOENLICH` (`an` oder `aus`, Standard aus), `MAX_EINREICHEN_TAG` (1 bis 50, Standard 10), `MAX_EINREICHEN_TAG_PROFIL`
(1 bis 50, Standard 5), `MAX_KLON_MB` (100 bis 4096, Standard 2048; verglichen mit `size` aus der API, das GitHub in KB liefert). Gesetzt mit
`wamo-job-kern-einrichten.sh kanal --persoenlich an|aus` und den Optionen für die Zahlen. Erst nach Dispatcher 10 setzen (Dispatcher 9 schließt bei unbekannten Schlüsseln den
Kanal), Rückweg umgekehrt. Kern: `WAMO_ENTWICKLUNG_GITHUB` (`an` oder `aus`, Standard aus) im Drop-in `wamo-entwicklung-buero.conf`, geschrieben nur von
`wamo-job-kern-einrichten.sh schalter ... --github an|aus`; `--github an` verlangt Dispatcher 10 und ein Kern-Release mit `SCHRANKEN_VERSION = 4` (`MIN_SCHRANKEN_GITHUB`).
`ping` meldet `persoenlich: true`, wenn `PERSOENLICH=an` gilt. Regel 5 im Kern-Kanal bei `github=persoenlich`: Repo Pflicht, nicht in `REPOS` nötig, nicht das eigene Repo
(Name), App-Modus nicht nötig, Dienste der Art zählen nicht (der persönliche Weg gibt keine Dienst-Tokens aus `geheim.env` weiter); ohne `PERSOENLICH=an` ergibt das
`persoenlich_aus`.

### C.3 Migration 0027_github_zugang

0026 ist im Zweig `feat/auftrag-speichern` belegt (`0026_auftrag_entwuerfe`), Plan C nimmt deshalb **0027**. Neue Tabelle statt neuer Spalten in `model_access` (deren Wächter
und die Regel „0010 nie erneut anwenden“ bleiben unberührt). Dateien `supabase/migrations/0027_github_zugang.sql`, `0027_github_zugang.down.sql`,
`supabase/tests/0027_github_zugang_test.sql`, Platzhalter `__SCHEMA__`, Regeln aus CLAUDE.md.

| Spalte | Typ und Prüfung |
| --- | --- |
| `user_id` | uuid, Primärschlüssel, FK `profiles(user_id)` `on delete cascade` |
| `art` | text, `fein` oder `klassisch` |
| `token` | bytea, Chiffrat, `octet_length` 40 bis 1024 |
| `token_ende` | text, `^[A-Za-z0-9_]{4}$` |
| `login` | text, `^[A-Za-z0-9]([A-Za-z0-9-]{0,38})$` |
| `konto_id` | bigint, größer 0 |
| `scopes` | text[], höchstens 30 Einträge (bei fein-granular leer) |
| `ablauf` | timestamptz, Pflicht (C5) |
| `geprueft_at`, `angelegt_at` | timestamptz |

Trigger `github_zugang_guard` (`drop trigger if exists` davor): Einfügen und Ändern nur für ein Profil ohne `labor_art`. RLS an, Policy `core_all` für `wamo_core`. Rechte:
`wamo_core` select, insert, update, delete (delete für den Widerruf); `wamo_admin` select nur auf `user_id`, `art`, `login`, `ablauf`, `geprueft_at`; `revoke all` für `public`,
`anon`, `authenticated`, `service_role`, `wamo_release`, `wamo_anker`. Die Tabelle kommt in `voice-core/labor_loeschliste.py` (gehört nicht zum Labor, `test_labor_loeschen.py`
bleibt grün). Audit ohne Migration in `actions` (Werkzeug `github_zugang` mit `aktion`, `art`, `login`, `ablauf`, nie der Wert; Werkzeug `auftrag_einreichen` mit Repo, Zweig, Pull
Request, Commit). Test: `wamo_core` liest und schreibt, `wamo_admin` liest `token` nicht, `anon` nichts, Laborprofil abgewiesen, zweiter Lauf bricht nicht ab, Down entfernt alles.

**Verschlüsselung:** `voice-core/schluessel.py` bekommt den Zweck `GITHUB = "github"` mit der AAD `wamo-github-token:<user_id>`; ein Chiffrat dieses Zwecks lässt sich nicht als
Claude-Schlüssel entschlüsseln und umgekehrt. `schwaerzen` erkennt zusätzlich `ghp_`, `gho_`, `ghs_`, `ghu_`, `ghr_` und `github_pat_` ab 8 Zeichen.

### C.4 Speichern und Prüfen (Kern)

Neues Modul `voice-core/github_zugang.py` nach dem Muster von `modellzugang.py`, Route `POST /wamo/api/github-zugang` und Client-Nachricht `github_zugang` (Aktionen `stand`,
`speichern`, `pruefen`, `loeschen`), nur für zugelassene Profile (`entwicklung_betrieb.zulassung_fuer`), nie für Laborprofile (nicht in der Erlaubnisliste des Labors), 5 Versuche je
10 Minuten.

1. Form: `ghp_` plus 36 Zeichen (klassisch) oder `github_pat_` plus 82 Zeichen (fein-granular); `gho_`, `ghu_`, `ghs_`, `ghr_` mit eigenem Satz abgewiesen.
2. `GET https://api.github.com/user` (Zeitlimit 10 s, keine Weiterleitung): 200 mit `login`, `id`, `type` `User`; 401 heißt ungültig.
3. Klassisch: `X-OAuth-Scopes` muss `repo` oder `public_repo` enthalten und darf `delete_repo`, kein `admin:*`, `site_admin`, `write:packages`, `delete:packages`, `read:packages`,
   `user`, `user:*` und `codespace` enthalten (C5). Beide Arten: `GitHub-Authentication-Token-Expiration` Pflicht, höchstens 366 Tage in der Zukunft (Annahme A2 aus 2.3).
   Fein-granular: Die Karte nennt die nötigen Rechte (Contents lesen und schreiben, Pull requests lesen und schreiben, Metadata lesen) und rät von allen anderen ab
   (Administration, Secrets, Workflows sind nicht abfragbar).
4. Speichern als Chiffrat mit Metadaten, Zeile in `actions`. Antwort nur Metadaten (Art, Login, Scopes, Ablauf, „endet auf …abcd“). Kein Weg gibt den Wert zurück.
5. `github_zugang_fuer(user_id)` liefert für genau einen Aufruf `{"typ": "github", "wert": ...}` oder None (nichts hinterlegt, abgelaufen, Chiffrat unlesbar, Labor); abgelaufene
   Tokens setzen keinen Rückfall auf die App.

Weil klassische Scopes sich bei GitHub nachträglich erweitern lassen, prüft der **Dispatcher bei jedem Start und Einreichen** Scopes und Ablauf erneut aus den Kopfzeilen von
`GET /user` mit denselben Regeln (Grund `token_rechte` bzw. `token_abgelaufen`).

### C.5 Ablauf im Dispatcher mit Fehlerfällen

**Gemeinsam für alle git-Aufrufe des Dispatchers:** immer mit `--git-dir=<eigenes Repo>`, `cwd="/"`, `GIT_CEILING_DIRECTORIES=/`, `GIT_CONFIG_NOSYSTEM=1`,
`GIT_CONFIG_GLOBAL=/dev/null`, `GIT_TERMINAL_PROMPT=0`, `core.hooksPath=/dev/null`, `core.fsmonitor=false`, `gc.auto=0`, `maintenance.auto=false`, Zeit- und Speichergrenzen
(rlimits), nie in einem Repo, das die Sandbox beschrieben hat. Werte aus GitHub oder Sandbox stehen nie in argv, außer geprüft: Repo nach `REPO_RE`, Job nach `JOB_RE`, Commit-IDs
40 Hex, `default_branch` nach `[A-Za-z0-9._/-]{1,100}` ohne führendes `-`, ohne `..`, nur als `refs/heads/<name>` nach `--end-of-options`.

**Start, erster Lauf eines Auftrags**

1. Kopfzeile, Claude-Zeile, GitHub-Zeile lesen (C.2.2); Regeln 1 bis 9 (Regel 5 wie C.2.7); zweite Prüfung unter der Sperre `kernkanal` wie heute.
2. Mit dem Token über `api.github.com` (Muster der App-Aufrufe, `http.client`, Zertifikatsprüfung, keine Weiterleitung, Antwort höchstens 256 KiB): `GET /user` (Login, ID, Scopes und
   Ablauf wie C.4), `GET /repos/<repo>`: `full_name` gleich dem Repo (sonst `repo_nicht_erreichbar`, eine Umbenennung fällt so auf), `id`, `id` von `parent`, `source` und
   `template_repository` nicht in `SELF_REPO_IDS` und deren Name nicht in `SELF_REPOS` (sonst `eigenes_repo`), `size` in KB höchstens `MAX_KLON_MB` mal 1024, `default_branch`
   (Prüfung oben), `private`, `permissions.pull` Pflicht, `permissions.push` für `schreiben`.
3. Klon: `git clone --bare --single-branch --branch <default_branch> --no-tags --template=<leerer Ordner> -- https://github.com/<repo>.git JOBDIR/basis.git` mit der gemeinsamen
   Umgebung, dazu `protocol.allow=never`, `protocol.https.allow=always`, `http.followRedirects=false`, `transfer.fsckObjects=true`, `fetch.fsckObjects=true`, `credential.helper`
   leer und danach genau der feste Helfer `/opt/wamo/bin/wamo-git-zugang <fd-Nummer>`, `GIT_ASKPASS=/bin/false`. Der Helfer liest Benutzername und Token aus der geerbten Pipe
   (die Nummer steht als Argument, sie ist nicht geheim), beantwortet nur `get` für genau `protocol=https` und `host=github.com`, ignoriert `store` und `erase` und schließt die Pipe.
   Das Token steht so in keiner Umgebung und keinem argv. Rückfall nur nach der Vorprobe, falls git den Deskriptor nicht weiterreicht: `GIT_ASKPASS` auf denselben Helfer. Zeitlimit
   300 s, stderr nur geschwärzt und gekürzt ins Protokoll.
4. Bereinigen und prüfen: `basis.git/config` neu schreiben (nur `core.bare`, `remote.origin.url=https://github.com/<repo>.git`, Fetch-Refspec), `hooks/`, `FETCH_HEAD` und `logs/`
   löschen, dann alle Dateien in `basis.git` außer `objects/` mit `O_NOFOLLOW` auf das Token durchsuchen (exakte Bytes, dazu Base64 von `<benutzername>:<token>` mit dem tatsächlich
   benutzten Benutzernamen): ein Treffer ergibt `bereinigung` und löscht `basis.git`. Größe gegen `MAX_KLON_MB`. `github.json` im Auftragsordner (für die Sandbox unsichtbar):
   `v`, `repo`, `repo_id`, `login`, `konto_id`, `basis`, `standardzweig`, `privat`, `schreiben`, `geklont_at`. Pipe-Puffer überschrieben, Ereignis `github`.
5. Sandbox-Schritt `klon` (C.5.2): leert den Projektordner (Rechte vorher setzen, nie Links folgen), klont aus `/run/wamo/basis.git` ohne Hardlinks und ohne Vorlage, setzt
   `origin` auf `https://github.com/<repo>.git`, legt `wamo/<job>` auf `basis` an und checkt ihn aus. Den Eigner des Projektordners schreibt der Dispatcher nach
   `sperren/eigner-<projekt>.json`.
6. **Danach** `projekt_entschaerfen` wie heute (entfernt `.claude/settings*.json`, `.mcp.json`, Hooks, filtert `.git/config`), dann Selbsttest und Lauf. So laufen Autostart-Flächen
   des geklonten Repos nie mit dem Claude-Zugang in der Sandbox.
7. Lauf wie heute, Umgebung ohne `GH_TOKEN` und ohne jedes Dienst-Token aus `geheim.env` (der Runner entfernt sie bei `WAMO_GITHUB=persoenlich` zusätzlich selbst), dazu
   `GIT_AUTHOR_NAME` und `GIT_COMMITTER_NAME` = Login, `GIT_AUTHOR_EMAIL` und `GIT_COMMITTER_EMAIL` = `<id>+<login>@users.noreply.github.com` (Werte aus der Antwort von GitHub,
   nie vom Kern), `WAMO_GITHUB=persoenlich`, `WAMO_ZWEIG=wamo/<job>`; `ERLAUBT_RE` bekommt genau diese sechs Namen. Systemtext `github_hinweis` für diesen Weg: kein GitHub-Zugang,
   lokal auf `wamo/<job>` committen, Trailer `WAIS-Auftrag: <job>`, nicht pushen, Einreichen übernimmt W.A.I.S. nach der Freigabe. Der Wächter sperrt bei
   `WAMO_GITHUB=persoenlich` `git push`, `git send-pack`, `gh` und `git remote set-url` mit diesem Satz.

**Folgelauf.** `basis.git` und `github.json` vorhanden: kein Klon, eine mitgeschickte Zeile wird ungelesen verworfen. Zustand nach C.5.1 muss einen Lauf erlauben (sonst
`schon_eingereicht`, Nacharbeit ist ein neuer Auftrag). Ist der Eigner des Projektordners ein anderer Auftrag, baut der Schritt `klon` die Arbeitskopie neu aus `basis.git` und dem
letzten Bundle dieses Auftrags; danach wieder Entschärfung. Ohne Bundle und mit fremdem Eigner: `projekt_gewechselt`, kein Lauf.

**Laufende (ohne Token im Prozess)**

1. `projekt_entschaerfen`, dann Sandbox-Schritt `ausgabe` (C.5.2): `git -c core.hooksPath=/dev/null -c core.fsmonitor=false bundle create /run/wamo/ausgabe/aenderung.bundle
   refs/heads/wamo/<job> ^<basis>` und `status.json` (Zahl nicht committeter Dateien). Fehlt der Zweig oder gibt es keine Commits, Status `keine`. Der Ordner `ausgabe/` wird vorher
   geleert.
2. Dispatcher übernimmt das Bundle nur so: `lstat`, `O_NOFOLLOW|O_NONBLOCK`, `S_ISREG`, Größe höchstens 200 MB, Kopie in eine eigene Datei `JOBDIR/bundle.ein` (für die Sandbox
   unsichtbar); `status.json` höchstens 4 KiB, nur eine ganze Zahl in Grenzen.
3. Sandbox-Schritt `pruefung` (C.5.2, ohne Projektordner, ohne Netz, ohne `/etc/wamo`): festes Programm `/opt/wamo/waechter/wamo_job_auszug.py` legt ein leeres Repo mit Alternates
   auf `/run/wamo/basis.git` an, holt `bundle.ein` mit fsck und `fetch.unpackLimit=1`, prüft genau einen Kopf `refs/heads/wamo/<job>` (sonst `bundle_ungueltig`),
   `merge-base --is-ancestor basis spitze` (sonst `basis_fehlt`), höchstens 200 Commits (`zu_viele_commits`), prüft Größen mit `cat-file --batch-check` vor dem Lesen und schreibt nach
   `/run/wamo/ergebnis`: `liste.json` (je Änderung `pfad` als Bytes in Base64, `modus`, `art`, `groesse`) und je neue oder geänderte Datei ihren Inhalt als eigene Datei
   (`dateien/<n>`), für Links das Ziel. Grenzen: 300 Dateien, 5 MB je Datei, 20 MB gesamt, Zeitlimit 60 s, rlimits. Die Sandbox verarbeitet damit die Pack-Daten, nicht der Dispatcher.
4. Dispatcher liest `ergebnis/` mit denselben Regeln wie in Schritt 2 (kein Link, nur reguläre Dateien, Größen) und wendet auf die Bytes die Regeln aus Folgepaket 1, 3.1.3 an:
   gesperrt (`.git` in jeder Schreibweise, `.gitmodules`, `.github/`, `.claude/`, `.vscode/`, `.devcontainer/`, `.cursor/`, `.githooks/`, `.mcp.json`, Zeichen außerhalb der
   Allowlist, Kollisionen, Gerätenamen, Links mit absolutem oder hinausführendem Ziel, Gitlinks), sensibel (Lockfiles, Build- und Skriptdateien, `.env*`, `.envrc`, `CLAUDE.md`,
   `AGENTS.md`, `conftest.py`, `Jenkinsfile`, `azure-pipelines.yml`, `.circleci/`, ausführbare und binäre Dateien). **Pfade, die die Entschärfung entfernt** (`.claude/`, `.mcp.json`):
   immer der Eintrag der Basis; eine Löschung dort wird nicht gemeldet und nicht übernommen, eine neue oder geänderte Datei dort ist gesperrt. Geheimnissuche über die Bytes aller
   neuen und geänderten Dateien mit Mustern (`sk-ant-`, `ghp_`, `gho_`, `ghs_`, `github_pat_`, `wh1-`, `AKIA`, PEM) und den exakten Werten des Laufs (Claude-Zugang aus
   `schwaerzungen(env)`). Ein Fehler der Prüfung oder ungültige Ausgabe heißt `pruefung_fehler`.
5. Commit mit eigenem git in `JOBDIR/aus.git` (bare, vom Dispatcher angelegt, Alternates auf `basis.git`): `read-tree <basis>` in einen eigenen Index, je Datei
   `hash-object -w --no-filters --stdin` mit den geprüften Bytes, `update-index -z --index-info` (Pfade nur über stdin, Löschungen als Modus 0), `write-tree`, Abgleich mit
   `diff-tree -r -z --no-renames` gegen die Liste (Abweichung heißt `pruefung_fehler`), `commit-tree -F - <tree> -p <basis>`: Autor Login und noreply-Adresse aus `github.json`,
   Committer `W.A.I.S.` mit `wais@wamocon.invalid`, Zeit einmal gesetzt. Nachricht nur aus der Vorlage: Titel aus der ersten Zeile des Auftragstexts, nur ASCII-Buchstaben,
   Ziffern, Leerzeichen und `. , ; ( ) - _ +`, ohne `/`, `:` und `://`, Schließwörter (`close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`, `resolved`) entfernt,
   höchstens 72 Zeichen, sonst „Änderung aus W.A.I.S.“; dann `Erstellt von W.A.I.S. im Entwicklungsauftrag <job>.` und die Trailer `WAIS-Auftrag: <job>`, `WAIS-Art: <art>`,
   `WAIS-Beauftragt-von: <login aus github.json>`, `WAIS-Profil: <kennung>`. Ref `refs/wamo/kandidat`, `aenderung.json` und `einreichen.json` atomar, Ereignis `aenderung`.

**Einreichen**

1. Regeln 1 bis 4 mit `profil`, `PERSOENLICH=an`; Sperren `.einreichen` und `.lauf` (kein Lauf dieses Auftrags aktiv).
2. Zustand nach C.5.1 aus `bereit`, `einreichen_laeuft` (nach Klärung über `ls-remote`) oder `branch_gepusht` (sonst `zustand`, bei `eingereicht` mit Adresse); `commit_id` und
   `tree_id` gleich `aenderung.json` und gleich `rev-parse refs/wamo/kandidat` in `aus.git` (sonst `veraltet`); `bestaetigt` als Menge enthält alle sensiblen Pfade (sonst
   `bestaetigung`).
3. GitHub-Zeile (Lesen wie C.2.2); `GET /user`: `id` gleich `konto_id` (sonst `konto`), Scopes und Ablauf wie C.4; `GET /repos/<repo>`: `id` gleich `repo_id` (sonst
   `repo_geaendert`), eigenes Repo wie beim Start, `permissions.push` (sonst `keine_schreibrechte`).
4. Geheimnissuche erneut über die Bytes aus `ergebnis/`, jetzt auch mit dem exakten GitHub-Token. Zweite Kanalprüfung (Notaus, Konfiguration). Zähler `einreichen` (sonst
   `grenze_einreichen`).
5. `git ls-remote -- https://github.com/<repo>.git refs/heads/wamo/<job>` (über den Helfer): fehlt der Zweig, wird gepusht; zeigt er auf `commit_id`, entfällt der Push; sonst
   `zweig_belegt`.
6. Zustand `einreichen_laeuft`, dann `git --git-dir=aus.git push --no-verify --no-follow-tags --porcelain -- https://github.com/<repo>.git <commit_id>:refs/heads/wamo/<job>` mit
   `push.followTags=false`, `push.recurseSubmodules=no`, ohne `+`. Die Ausgabe muss genau eine Zeile für `refs/heads/wamo/<job>` mit Erfolg enthalten, jede andere Zeile heißt
   `github_fehler`. Zustand `branch_gepusht`.
7. Notaus erneut prüfen. `GET /repos/<repo>/pulls?head=<owner>:wamo/<job>&state=open`: wiederverwendet wird nur ein offener Pull Request mit `head.sha` gleich `commit_id` und
   `head.repo.id` gleich `repo_id`; sonst `POST /repos/<repo>/pulls` mit `head` `wamo/<job>`, `base` `default_branch` aus Schritt 3 (bei einem Fork dessen eigener Standardzweig, nie
   das Ursprungsprojekt), `draft` an (bei 422 ohne), `maintainer_can_modify` aus. Titel `W.A.I.S.: <Titel>`, Text aus der Vorlage: Auftrags-ID (nie der Auftragstext), Art,
   Konto, Zahl der Dateien, Plus und Minus, höchstens 50 Pfade in einem Codeblock (dann „und N weitere“; Pfade enthalten nach der Allowlist keine Backticks), Satz „Nicht gemergt,
   bitte prüfen.“ Kein Text des Agenten, kein `@`, kein `#`.
8. Zustand `eingereicht` mit Nummer und Adresse, Ereignis `eingereicht`, Zähler `eingereicht`, Puffer überschrieben.

#### C.5.1 Zustände eines Auftrags mit `github=persoenlich`

| Zustand (`aenderung.status`) | Bedeutung | erlaubt | Übergänge |
| --- | --- | --- | --- |
| `keine` | kein Commit auf `wamo/<job>` | Folgelauf, `verwerfen` | `bereit`, `gesperrt` (nach einem Folgelauf), `verworfen` |
| `gesperrt` | Regel verletzt | Folgelauf, `verwerfen` | `bereit`, `keine` (Folgelauf), `verworfen` |
| `nur_lesen` | Art lesend oder kein Schreibrecht | Folgelauf, `verwerfen` | `verworfen` |
| `bereit` | Kandidat in `aus.git` | Folgelauf (ersetzt den Kandidaten), `einreichen`, `verwerfen` | `einreichen_laeuft`, `keine`, `gesperrt`, `bereit` (neuer Kandidat), `verworfen` |
| `einreichen_laeuft` | Push oder Pull Request laufen | nichts außer `einreichen` nach Klärung | `branch_gepusht`, `bereit` (Fehler vor dem Push), `eingereicht` |
| `branch_gepusht` | Zweig gepusht, Pull Request fehlt | nur `einreichen` (holt den Pull Request nach) | `eingereicht` |
| `eingereicht` | Pull Request offen | nichts; Nacharbeit ist ein neuer Auftrag | Ende |
| `verworfen` | verworfen | nichts | Ende |

Übergänge nur unter der Sperre `.einreichen`, Dateien atomar (`write_json_atomic`). Nach `branch_gepusht` und `eingereicht` gibt es keinen Folgelauf, damit der Zweig nie einen
anderen Commit braucht (sonst dauerhaft `zweig_belegt`).

#### C.5.2 Neue Sandbox-Modi in `wamo-job.sh`

`MODUS` mit `case` und Ablehnung als Standard: `lauf`, `pruefen`, `klon`, `ausgabe`, `pruefung`. Für `klon`, `ausgabe` und `pruefung` gilt immer `--unshare-net`, eine eigene enge
Umgebungs-Allowlist (nur `XDG_RUNTIME_DIR` und die Git-Einträge für Hooks und fsmonitor), kein Claude, kein Wächter-Hook nötig, kein `/etc/wamo`, Zeitlimit 300 s (`klon`) bzw.
60 s, Dateigrenze per `ulimit -f`. Mounts: `klon` Projektordner beschreibbar, `basis.git` nur lesend, letztes Bundle nur lesend; `ausgabe` Projektordner **nur lesend**
(`--ro-bind`), `ausgabe/` beschreibbar; `pruefung` ohne Projektordner, `bundle.ein` und `basis.git` nur lesend, `ergebnis/` beschreibbar. Die festen Skripte liegen unter
`/opt/wamo/waechter/` (in der Sandbox sichtbar): `wamo-job-klon.sh`, `wamo-job-ausgabe.sh`, `wamo_job_auszug.py`. Rauchtest-Probe: in allen drei Modi kein Netz und keine Token in
der Umgebung.

| Fall | Verhalten |
| --- | --- |
| GitHub-Zeile fehlt oder Form falsch | `start_abgelehnt` `github_zeile`, kein Lauf |
| 401, Ablauf überschritten, Scopes außerhalb von C5 | `token_ungueltig`, `token_abgelaufen` oder `token_rechte`, kein Lauf; der Kern bittet um ein neues Token |
| Repo nicht lesbar, umbenannt, zu groß | `repo_nicht_erreichbar` oder `repo_zu_gross` |
| Eigenes Repo, auch als Fork oder Vorlage | `eigenes_repo` |
| Klon scheitert oder Zeitlimit | `klon_fehler`, `basis.git` gelöscht |
| Token-Rest im Klon gefunden | `bereinigung`, `basis.git` gelöscht, Protokoll ohne Wert |
| Folgelauf mit anderem `github` | `github_wechsel` |
| Sandbox-Schritt `klon` scheitert | kein Lauf, Ereignis wie ein Selbsttestfehler |
| Kein Commit auf `wamo/<job>` | Status `keine`, Karte „keine Änderung“, Hinweis bei `ungesichert` |
| Bundle ist Link, FIFO, zu groß; Ergebnis ungültig | `bundle_ungueltig` oder `pruefung_fehler` |
| Regel verletzt | Status `gesperrt` mit Gründen, die Karte zeigt nur „Verwerfen“ |
| Art lesend oder kein Schreibrecht | Status `nur_lesen`, keine Freigabekarte |
| Notaus während des Einreichens | vor dem Push: Zustand `bereit`; nach dem Push: `branch_gepusht`, ein neuer Klick holt nur den Pull Request nach |
| Pull Request scheitert nach dem Push | `branch_gepusht`, `github_fehler` |
| Dispatcher stirbt in `einreichen_laeuft` | nächster Aufruf klärt über `ls-remote`: Zweig mit `commit_id` heißt `branch_gepusht`, sonst `bereit` |
| Fein-granulares Token ohne Contents-Schreibrecht | Push 403, `keine_schreibrechte` |
| Token inzwischen eines anderen Kontos | `konto` |

### C.6 Freigabekarte für den Push

**Heute.** Der Kern schickt `{"type": "freigaben", "job", "projekt", "items": [{"id", "grund", "detail", "warnung", "von"}]}`; `ui/src/components/Freigaben.tsx` zeigt je Eintrag
eine Karte (`ApprovalCard`) oben in der Präsenzspalte mit Überschrift, Grund, Detail, Warnung und den gleichgewichtigen Knöpfen „Freigeben“ und „Ablehnen“, ohne Tastenkürzel und
ohne Sprache. Der Klick schickt `{"type": "freigabe", "job", "id", "entscheidung"}`, der Kern ruft `approve <job> <fingerabdruck>` (voice-core/dev_agent.py:943-972).

**Neu.** Ein Eintrag mit `"id": "einreichen"` und dem Zusatzfeld `einreichen`: `repo`, `privat`, `zweig`, `konto`, `commit_id`, `tree_id`, `dateien`, `plus`, `minus`, `markiert`
(sensible Pfade), `gesperrt` (Gründe), `ungesichert`, `lauf`. Die Karte zeigt Repo (mit „privat“), Zweig `wamo/<job>`, Konto, Zahlen, die markierten Pfade mit je einem Kästchen;
„Einreichen“ ist erst aktiv, wenn alle markierten Pfade bestätigt sind, „Verwerfen“ ist gleichgewichtig. Bei `gesperrt` gibt es nur „Verwerfen“ und die Gründe als Sätze. Der
Klick schickt `{"type": "einreichen", "job", "commit_id", "tree_id", "bestaetigt": [...]}` oder `{"type": "verwerfen", "job"}`. Der Kern entschlüsselt das Token frisch, ruft
`einreichen <job> <profil>` und zeigt danach eine Quittung mit dem geprüften Link zum Pull Request im Canvas; `actions` bekommt `auftrag_einreichen`. Bei `branch_gepusht` (auch nach
einem Neustart über `aenderung`) zeigt die Karte „Pull Request nachholen“. Die Auftragskarte vor dem Start zeigt bei `github=persoenlich` Repo und Konto und den Hinweis „mit deinem
GitHub-Token“. Texte und Prüfung der Felder in `ui/src/lib/einreichen.ts`.

### C.7 Logs und Schwärzung

- Dispatcher: `schwaerzen` bekommt `GH_PAT_RE` (`ghp_`, `gho_`, `ghs_`, `ghu_`, `ghr_`, `github_pat_`) und das exakte Token des Aufrufs; stderr von git und Antworten von GitHub
  gehen nur geschwärzt und gekürzt ins Protokoll. Ausgaben der Sandbox werden wie heute geschwärzt. `kernkanal.jsonl` trägt nur Kennungen und Zahlen.
- Kern: der Wert steht nie in einem Objekt außer für den einen Aufruf, nie in `actions`, `turns` oder Gedächtnis; `schluessel.schwaerzen` erkennt die GitHub-Formen; loguru läuft
  ohne `diagnose`.
- Test in beiden Paketen: ein Lauf mit einem Attrappen-Token, danach kommt der Wert in keinem Protokoll, keiner Datei unter `/srv/wamo`, keinem Ereignis und keiner Umgebung eines
  Kindprozesses vor.

### C.8 Tests je Teil

| Teil | Tests (rot zuerst) |
| --- | --- |
| Migration | `supabase/tests/0027_github_zugang_test.sql`: Rechte je Rolle, Spaltenrechte für `wamo_admin`, Laborprofil abgewiesen, Prüfregeln, zweiter Lauf, Down; `voice-core/test_labor_loeschen.py` grün |
| Kern, Speichern | `voice-core/test_github_zugang.py`: Formen, 401, Scopes erlaubt und verboten, Ablauf fehlt, über 366 Tage, Drosselung, Labor, nicht zugelassen, kein Wert in Antwort und Log; `test_schluessel.py`: Zweck GitHub, Schwärzung |
| Kern, Aufträge | `voice-core/test_dev_agent_sokrates2.py`: Kopffeld nur mit Schalter und Dispatcher 10, GitHub-Zeile nach der Claude-Zeile nur bis zum Ereignis `github`, Neustart nach `github_zeile`, nie in argv, Freigabekarte aus `aenderung`, Einreichen nur aus der UI-Nachricht, frisches Token, Quittung mit geprüfter Adresse, Verwerfen, nichts davon ans Sprachmodell; `test_entwicklung_betrieb.py`: Sätze, `SCHRANKEN_VERSION` |
| Oberfläche | `ui/src/lib/githubZugang.test.ts`, `ui/src/components/GithubZugang.comp.test.tsx` (Feld wird geleert, Wert nie angezeigt), `ui/src/lib/einreichen.test.ts`, `ui/src/components/Freigaben.comp.test.tsx` (Kästchen, Sperre, Verwerfen, Nachholen) |
| Vertrag | `voice-core/test_kernkanal_vertrag.py`: alle vier Listen gleich auf beiden Seiten, jeder Code hat einen Satz |
| Dispatcher | `voice-core/test_sokrates2_dispatch.py`: Feld nur im Kern-Kanal, Bindung in `auftrag.json`, Zeilenfolge, Bytes-Leser ohne `str`, `PR_SET_DUMPABLE`, keine Dienst-Tokens, sechs Umgebungsnamen, Token nie in argv, Umgebung oder Datei (Attrappe von git mit Zähler), Helfer nur `get` für `github.com`, Schwärzung; neu `voice-core/test_job_github.py`: API-Antworten (Umbenennung, Fork des eigenen Repos per ID, Vorlage, `size` in KB, `push`, `default_branch` mit `-` und `..`), Bereinigung mit gepflanztem Token-Rest, Bundle als Link und FIFO, Ergebnis mit Link, Basis fehlt, Pfadregeln (aus FP1 3.1.8), Entschärfungs-Pfade aus der Basis, Commit aus Bytes mit Abgleich, Titel-Allowlist mit Schließwörtern und URL, Einreichen in jeder Reihenfolge der Fehler, Zustände aus C.5.1, Refspec exakt, PR-Wiederverwendung nur offen mit gleichem SHA, höchstens 50 Pfade, Absturz nach dem Push |
| Auszug | `voice-core/test_job_auszug.py`: zwei Köpfe, fremde Basis, zu viele Commits, Größen vor dem Lesen, Ausgabe nur reguläre Dateien |
| Kern-Kanal | `voice-core/test_kernkanal.py`: `PERSOENLICH`, Regel 5 für den persönlichen Weg, Befehle offen und geschlossen, `profil` in Regel 4, Zähler und Grenzen |
| Sandbox-Modi | `voice-core/test_job_kern_skripte.py` bzw. Probelauf von `wamo-job.sh` in `klon`, `ausgabe`, `pruefung` (kein Netz, Mounts, nur lesend, Grenzen, unbekannter Modus abgewiesen); Rauchtest-Proben in `wamo_job_kern_rauchtest.py` |
| Wächter | `voice-core/test_dev_guard.py`: Sperren bei `WAMO_GITHUB=persoenlich`, sonst unverändert |

### C.9 Arbeitspakete

**Reihenfolge der Zweige.** `feat/auftrag-speichern` (ändert `dev_agent.py`, `Freigaben.tsx`, `nachrichten.ts`, `useWamo.ts`, `wamo.ts`, `WamoAnsicht.tsx`, Migration 0026) wird vor
K gemergt, `feat/fp1-1-expiry-time` (ändert `wamo-job-kern-einrichten.sh`, `wamo_job_kern_rauchtest.py`, `test_job_kern_skripte.py`, `test_kernkanal_vertrag.py`) vor S und D-a;
sonst baut K bzw. D-a auf diesen Zweigen auf. Danach ändern S, K, D-a und D-b keine gemeinsamen Dateien, außer in der festgelegten Folge S vor K und D-a.

**Schnittstelle D-a zu D-b.** D-b liefert die Module ohne Abhängigkeit vom Dispatcher; D-a reicht beim Aufruf eine kleine Umgebung hinein (`Werkzeuge`: `log`, `http`
(GitHub-Aufruf mit Token aus der Pipe), `git` (Aufruf mit der gemeinsamen Umgebung), `sandbox` (Start eines Modus), `sperre`, `uhr`). Die Signaturen stehen vor dem Bau in
`wamo_job_github.py` als Protokoll-Klasse (Teil von S).

| Paket | Inhalt | Dateien | h |
| --- | --- | --- | --- |
| **S** Schnittstelle (zuerst, ein Pull Request) | Gründe und Sätze aus C.2.6, Vertragstest, Protokoll-Klasse `Werkzeuge` | `infra/sokrates2/wamo_job_kernkanal.py` (nur die vier Listen der Gründe), `voice-core/entwicklung_betrieb.py` (nur Sätze), `voice-core/test_kernkanal_vertrag.py`, `infra/sokrates2/wamo_job_github.py` (nur Protokoll-Klasse und Konstanten) | 3 |
| **K** Kern, Oberfläche, Migration | C.3, C.4, Kern-Teil von C.2, C.6, C.7, Schalter lesen, `SCHRANKEN_VERSION = 4` | `supabase/migrations/0027_github_zugang.sql`, `.down.sql`, `supabase/tests/0027_github_zugang_test.sql`, `voice-core/schluessel.py`, `voice-core/github_zugang.py` (neu), `voice-core/bot.py`, `voice-core/labor_loeschliste.py`, `voice-core/dev_agent.py`, `voice-core/entwicklung_betrieb.py` (nach S: Schalter, Version), `ui/src/lib/githubZugang.ts`, `ui/src/components/GithubZugang.tsx`, `ui/src/lib/einreichen.ts`, `ui/src/components/Freigaben.tsx`, `ui/src/lib/nachrichten.ts`, `ui/src/lib/useWamo.ts`, `ui/src/lib/wamo.ts`, `ui/src/components/WamoAnsicht.tsx`, Tests aus C.8 (Kern, Oberfläche, Migration) | 34 |
| **D-a** Dispatcher, Kern-Kanal, Runner, Skripte | Einhängepunkte, C.2 Dispatcher-Seite, Bytes-Leser, Helfer, C.5.2, Wächter, Aufräumen, Einrichten und Rückweg | `infra/sokrates2/wamo_job_dispatch.py` (nur Einhängepunkte, `VERSION = "10"`, Kopffeld, Zeile, Umgebung, Schwärzung, Befehle, `ping`), `infra/sokrates2/wamo_job_kernkanal.py` (nach S: Schlüssel, Regel 5, `BEFEHLE_KERN`, `EREIGNISSE`, Zähler), `infra/sokrates2/wamo-job.sh`, `infra/sokrates2/wamo-job-klon.sh`, `wamo-job-ausgabe.sh`, `wamo-git-zugang` (neu), `infra/sokrates2/wamo-job-einrichten.sh`, `wamo-job-rueckweg.sh`, `wamo-job-kern-einrichten.sh`, `wamo-job-kern-rueckweg.sh`, `wamo_job_kern_rauchtest.py`, `voice-core/dev_guard.py`, Aufräum-Timer (neu), Tests dazu | 24 |
| **D-b** GitHub-Logik und Auszug | API, Klon, Bereinigung, Übernahme der Sandbox-Ausgaben, Regeln, Commit aus Bytes, Einreichen, Pull Request, Auszug in der Sandbox | `infra/sokrates2/wamo_job_github.py` (nach S), `infra/sokrates2/wamo_job_pfadregeln.py` (neu, Regeln aus FP1 3.1.3), `infra/sokrates2/wamo_job_auszug.py` (neu), `voice-core/test_job_github.py`, `voice-core/test_job_pfadregeln.py`, `voice-core/test_job_auszug.py` | 29 |
| **R** Review, Rollout, Doku (nach K und D) | Sicherheitsreview des Codes und Korrekturen (6), Migration dev, test, prod mit `database-reviewer`, Dispatcher 10, `kanal --persoenlich an`, Kern- und Oberflächen-Release, Rauchtest mit Testrepo und Wegwerf-Token, Rückweg-Probe, Schalter zuerst nur für das Admin-Profil, Zeile im Namensvertrag von CLAUDE.md, Abschnitt in `infra/sokrates2/README.md` (6) | Server, `CLAUDE.md`, `infra/sokrates2/README.md` | 12 |
| | **Summe Plan C** | | **102** |

Kritischer Pfad: S (3) → D-b (29) → R (12) = 44 Stunden mit drei Agenten (K, D-a, D-b); mit einem Agenten für D sind es S (3) → D (53) → R (12) = 68 Stunden.
**Admin, manuell:** Testrepo und Wegwerf-Token (fein-granular und klassisch, Ablauf 7 Tage) am Donnerstagmorgen, Merge von `feat/auftrag-speichern` und `feat/fp1-1-expiry-time`
oder Zustimmung zum Aufbauen darauf, Ja zu den Pull Requests, Go oder No-Go am Samstag 21.11. 18 Uhr.

### C.10 Rückweg und Aufräumen

1. `wamo-job-kern-einrichten.sh schalter ... --github aus`: der Kern schickt nie mehr `github`, die Karte verschwindet.
2. `kanal --persoenlich aus`, dann die Schlüssel `PERSOENLICH`, `MAX_EINREICHEN_*`, `MAX_KLON_MB` entfernen, erst danach Dispatcher 9 zurück (`wamo-job-rueckweg.sh`).
3. Gespeicherte Tokens bleiben verschlüsselt; `0027_github_zugang.down.sql` löscht sie. Die Personen widerrufen ihre Tokens bei GitHub.
4. Aufräumen: ein Timer (`wamo-job-aufraeumen.timer`, täglich) löscht `basis.git`, `aus.git`, `bundle.ein`, `ausgabe/`, `ergebnis/` von Aufträgen, die `eingereicht` oder
   `verworfen` sind, nach einem Tag, alle anderen nach 7 Tagen, und leert Projektordner mit `github=persoenlich`, deren Eigner-Auftrag so alt ist. `wamo-job-rueckweg.sh` macht
   denselben Schritt sofort, damit nach dem Rückweg keine Kopien privater Repos liegen bleiben.

### C.11 Restrisiken von Plan C

| Nr. | Restrisiko | Begründung |
| --- | --- | --- |
| RC1 | Gekaperter Kern hat alle GitHub-Tokens | bewusst akzeptiert (C4), wie beim Claude-Zugang. Begrenzt durch Ablaufpflicht und Scope-Regeln (C5), die der Dispatcher bei jeder Benutzung erneut prüft |
| RC2 | Ausbruch aus einer Sandbox auf `wamo` greift auf einen gleichzeitig laufenden Klon oder Push einer anderen Person zu | Der Dispatcher ist nicht dumpable, das Token steht in keiner Umgebung; offen bleibt der Speicher des git-Kindes für die Dauer von Klon oder Push. Schutz durch Yama (`ptrace_scope` mindestens 1, Vorprobe). Kleiner als beim Claude-Zugang, der während des ganzen Laufs in der Umgebung der Sandbox steht |
| RC3 | Code des Agenten läuft nach dem Push in CI und Vorschau mit Secrets | Push auf `wamo/**` startet Workflows; `.github/` und weitere CI-Flächen sind gesperrt, sensible Dateien zu bestätigen. Die CI-Prüfung der Ausbaustufe (3.5 Schicht 3) folgt nach dem 05.12. |
| RC4 | Fehler in git beim Lesen des Bundles | läuft nur im netzlosen Sandbox-Schritt `pruefung` ohne `/etc/wamo` und ohne Token; der Dispatcher übernimmt nur Dateibytes. Ein Fehler in git beim Push aus `aus.git` betrifft nur Objekte, die der Dispatcher selbst gebaut hat |
| RC5 | Quelltext des Auftragsrepos fließt über 443 ab | wie heute |
| RC6 | Fein-granulare Rechte sind nicht abfragbar | Anleitung auf der Karte; W.A.I.S. benutzt das Token nur für die festen Wege aus C.5 |

### C.12 Review von Plan C

Adversariales Review durch `ecc:security-reviewer` mit Fokus Token-Leck, Git-Hooks und Konfiguration, Ref- und Refspec-Injektion, PR-Text, Logs: 0 CRITICAL, 2 HIGH, 7 MEDIUM,
4 LOW. HIGH und MEDIUM sind eingearbeitet, LOW überwiegend.

| Nr. | Befund | Schwere | Lösung | Abschnitt |
| --- | --- | --- | --- | --- |
| 1 | Bundle und Objekte würden im Dispatcher verarbeitet (Prozess mit `geheim.env`, Claude-Zugang, App-Schlüssel); RC4 war falsch | HIGH | eigener netzloser Sandbox-Schritt `pruefung` ohne Projektordner und `/etc/wamo` gibt nur Dateiliste und Bytes zurück; der Dispatcher baut Blobs und Tree aus geprüften Bytes; Grenzen und rlimits; RC4 neu | C.5 Laufende 3 bis 5, C.11 |
| 2 | Reihenfolge Klon und Entschärfung: Autostart-Flächen des Klons liefen mit dem Claude-Zugang, und entschärfte Pfade machten Repos mit `.claude/` nie einreichbar | HIGH | Entschärfung nach `klon` und vor `ausgabe`; für entschärfte Pfade gilt immer der Basis-Eintrag | C.5 Start 6, Laufende 1 und 4 |
| 3 | Neue Modi nicht netzlos, falsche Allowlist, Projekt beschreibbar, Skript nicht sichtbar | MEDIUM | `case` mit Ablehnung, `--unshare-net`, eigene Allowlist, `--ro-bind`, Skripte unter `waechter/`, Runner entfernt Token zusätzlich | C.5.2 |
| 4 | Zustandsautomat widersprüchlich, `github` nicht gebunden, `verwerfen` ohne Sperre | MEDIUM | Zustandstabelle, Bindung in `auftrag.json`, `verwerfen` nur aus vier Zuständen mit Sperren | C.2.1, C.2.3, C.5.1 |
| 5 | Token bleibt als `str` im Speicher des Dispatchers, Helfer ungenau, Folgeläufe laden es unnötig | MEDIUM | Bytes-Leser ohne Kopien, `PR_SET_DUMPABLE=0`, `RLIMIT_CORE=0`, Helfer nur `get` für `github.com`, Zeile nur bis zum Ereignis `github` | C.2.2, C.5 Start 3 |
| 6 | `ausgabe/` als Schreibfläche der Sandbox (Link, FIFO, Reste) | MEDIUM | Ordner leeren, `lstat`, `O_NOFOLLOW`, Kopie, git nur mit `--git-dir`, `cwd="/"`, `GIT_CEILING_DIRECTORIES` | C.5 gemeinsam, Laufende 1 bis 2 |
| 7 | Scope-Prüfung nur beim Speichern | MEDIUM | Prüfung bei jedem Start und Einreichen; Allowlist statt Blacklist bleibt als Empfehlung (C5 ist entschieden) | C.4 |
| 8 | Pakete überschneiden sich mit offenen Zweigen, 0026 belegt, Abhängigkeit D-b zum Dispatcher | MEDIUM | Migration 0027, Reihenfolge der Zweige, Protokoll `Werkzeuge`, Dateilisten ergänzt | C.3, C.9 |
| 9 | PR-Wiederverwendung zu weit, PR-Text zu lang, Titel mit URL und Schließwörtern | MEDIUM | nur offener PR mit gleichem SHA und Repo, höchstens 50 Pfade, ASCII-Titel ohne `/` und `:`, Schließwörter entfernt, `commit-tree -F -`, Login aus `github.json` | C.5 Laufende 5, Einreichen 7 |
| 10 | Grenze der Einreichen-Zeile, Zähler zählt Fehlklicks | LOW | 64 KiB, Menge, nur Versuche bis zum Push | C.2.3, C.2.5 |
| 11 | `size` in KB, Klon aller Zweige, `default_branch` ungeprüft | LOW | Umrechnung, `--single-branch`, Prüfung und `--end-of-options`, 300 s | C.5 |
| 12 | Aufräumen nur beim nächsten Start | LOW | Timer und Schritt im Rückweg | C.10 |
| 13 | Ereignistexte ins Sprachmodell, `einreichen` als Werkzeug, Base64 nur mit festem Namen, Startkarte, Sensibel-Liste | LOW | alles übernommen | C.2.3, C.2.4, C.5, C.6 |

**Nicht übernommen:** Allowlist der klassischen Scopes statt der Liste aus C5 (würde auch `workflow`, `write:org` und `gist` verbieten). Das weicht von der Entscheidung C5 ab und
ist dem Admin als Empfehlung vorgelegt; die erneute Prüfung bei jeder Benutzung ist übernommen.

## Kurzfassung der Ausbaustufe (Plan A und B, nach dem 05.12.)

**Kurzfassung.** Entwicklungsaufträge sollen mit den eigenen Zugängen der Person arbeiten (GitHub mit fein-granularem oder klassischem Token, Vercel mit eigenem
Token), weil die GitHub-App nicht alle Repos der Person sieht. Leitsatz: **Das persönliche Token verlässt den Zugangsdienst nie.** Es geht nicht in die Sandbox, nicht in
den Dispatcher, nicht in den Kern und nicht in den Ursprung der Oberfläche. Die Person tippt es in ein **Bedienfeld**, das der neue Dienst `wamo-zugang` selbst auf Port 55444
ausliefert (eigener Ursprung, als Rahmen in der Oberfläche); der Dienst prüft es bei GitHub und speichert es nur verschlüsselt mit einem eigenen Schlüssel. Jede Handlung mit
dem Token (Starten, Einreichen, Repo freischalten, Token ändern) braucht die Signatur eines **Geräteschlüssels**, den das Bedienfeld im Browser nicht exportierbar erzeugt und
einmal je Gerät mit einem frischen Code des zweiten Faktors anmeldet. So kann auch ein gekaperter Kern, der das Sitzungstoken sieht, das Token nicht benutzen. Die Sandbox bekommt
je Lauf nur ein wertloses Auftragstoken für ein **Git-Tor** auf Loopback (eigener Benutzer, ohne Token, ohne Internet): Klonen aus einem Spiegel, Pushen nur nach
`refs/heads/wamo/<auftrag>` in eine **Quarantäne**. Ein getrennter **Prüfer** ohne Netz und ohne Geheimnisse baut daraus genau einen Commit und prüft Pfade, Geheimnisse und die
CI des Repos. Erst nach dem signierten Klick pusht ein kurzlebiges Kind in bwrap, das nur dieses eine Token kennt, mit fester Refspec nach `wamo/<auftrag>` und öffnet den Pull
Request. Gemergt wird nie durch W.A.I.S. Vercel, Supabase (Proxy nur für ausgewählte Projekte) und Konnektoren folgen nach dem Labortag am 05.12.; claude.ai-Konnektoren gehen
in einem Lauf mit `claude setup-token` laut Doku gar nicht (4.4). Der Pflichtumfang für GitHub liegt nach dem Review bei etwa 146 Stunden, der kritische Pfad bei etwa
71 Stunden. **Ein abgesicherter Live-Gang vor dem Freeze am 23.11. ist damit nicht realistisch.** Empfehlung (D4): bis Sonntag bauen, in der Freeze-Woche prüfen und
korrigieren, ab dem 07.12. als Pilot für das Admin-Profil live, danach für alle.

**IQ:** Ein klassisches Token mit `repo` erreicht alle Repos der Person und ihrer Organisationen, monatelang. Jeder Ort, an dem es im Klartext liegt (Sandbox mit offenem
Port 443, Prozess des Benutzers `wamo`, Kern mit dem Hauptschlüssel aller Profile, ein Prozess, der feindliche Git-Daten verarbeitet), ist ein Ort, an dem es abfließen kann.
Deshalb wird das Token aus allen diesen Orten herausgenommen, und was W.A.I.S. damit tun darf, steht als feste Liste im Code, nicht in den Rechten des Tokens. Das Review hat
gezeigt, dass ein Klick ohne Geräteschlüssel gegen den Kern nichts beweist: Der Geräteschlüssel ist die tragende Neuerung.
**EQ:** Die Person sieht ihr Token nie wieder, sieht aber jede Benutzung mit dem Gerät, das sie ausgelöst hat; einmal je Gerät ein Code, danach ein Klick. Der Pull Request steht
unter ihrem Namen und trägt den Auftrag. Die ehrliche Botschaft an den Admin: Vor dem Freeze geht es nur mit weniger Sicherheit, und das empfiehlt dieses Papier nicht.
**VQ:** Ablaufbild, Rechtetabelle, Zustandsautomat, Bedrohungstabelle mit gleichen Spalten, je Paket Dateien, Abnahme und Stunden. **Synthese:** Zuerst die neue Grenze (Tor,
Prüfer, Bedienfeld mit Geräteschlüssel), dann Dispatcher und Kern; Live erst, wenn das Review des Codes ohne offene CRITICAL und HIGH ist und ein Korrekturfenster bleibt.

## Stand nach Review (18.11.2026)

Das Papier hat ein adversariales Sicherheitsreview (Agent `ecc:security-reviewer`, Auftrag: Lücken finden, im Zweifel Befund annehmen) durchlaufen: 16 Befunde, 1 CRITICAL,
5 HIGH, 7 MEDIUM, 3 LOW. Alle sind eingearbeitet, zwei nur teilweise (unten).

| Nr. | Befund | Schwere | Änderung im Papier | Abschnitt |
| --- | --- | --- | --- | --- |
| 1 | Der Kern hat das Sitzungstoken (E1) und kann Repo-Freischaltung, Start, Kandidat und Einreichen selbst aufrufen; D2 und die Bestätigung markierter Dateien begrenzen ihn nicht | CRITICAL | Bedienfeld des Dienstes im eigenen Ursprung (Port 55444) als Rahmen in der Oberfläche; Geräteschlüssel (WebCrypto, nicht exportierbar) signiert jede Handlung, angemeldet einmal je Gerät mit einem Code, der höchstens 60 Sekunden alt ist; das Token nach dem Code geht nie an den Kern; optional Netzregel gegen `wamo-core` auf 55444 | 3.3, 3.4, 3.9, 3.1, D3 |
| 2 | CI und Vorschau führen Code des Agenten mit Repo-Secrets aus, ein Hinweis reicht nicht | HIGH | Der Prüfer liest die Workflows der Basis; Auslöser `push`, `pull_request` oder `pull_request_target` ohne Ausschluss von `wamo/**` zusammen mit `secrets.` oder `environment:` sperrt das Einreichen, außer nach signierter Bestätigung je Repo mit frischem Code; vor dem Live-Gang, nicht erst nach dem 05.12. | 3.5 Schicht 3, D2 |
| 3 | Git-Prozesse mit feindlichen Bytes laufen unter derselben Kennung wie Schlüssel und Tokens | HIGH | Der Dienst selbst verarbeitet nie Git-Objekte. Import, fsck und Kandidat im Prüfer (eigener Benutzer, ohne Netz, ohne Geheimnisse); Spiegel und Push in einem Kind in bwrap ohne Credentials, ohne Datenbank, eigener PID-Namensraum, nur das eine Token; Ausgang des Dienstes nur über einen Domain-Proxy | 3, 3.4, 3.5 |
| 4 | Eigener pkt-line-Parser im Tor erzeugt Parser-Differenzen | HIGH | Das Tor parst nicht, es reicht an `git http-backend` weiter; einzige Instanz für Ref-Regeln sind root-eigene Hooks `pre-receive` und `update` über die Prozess-Konfiguration; Push-Optionen und signierte Pushes aus; Fuzz-Tests mit echtem git | 3.5 Schicht 2 |
| 5 | Besitz und Rechte fehlen; `fetch` aus der Quarantäne liest deren Konfiguration und Alternates; ein gekapertes Tor könnte fremde Spiegel einhängen | HIGH | Rechtetabelle (3.4.1); das Tor übergibt nur eine Pack-Datei, der Prüfer importiert mit `index-pack --strict` in ein frisches Repo, dessen Alternates er selbst aus dem Startdatensatz setzt; die Quarantäne öffnet außer dem Tor niemand; Zugriffe mit `O_NOFOLLOW` | 3.4.1, 3.5 |
| 6 | Zeitplan ohne Korrekturfenster, PZ-4 und PZ-5 unterschätzt, großer Sonntags-Rollout an alle | HIGH | Stunden neu (146 statt 113), kritischer Pfad 71 Stunden, Plan B als Empfehlung (D4): kein Live vor dem Freeze, Pilot für das Admin-Profil ab 07.12. | 4.1 bis 4.5, D4 |
| 7 | Zustandsautomat des Startdatensatzes fehlt | MEDIUM | Zustände, Frist, Folgeläufe, `stufe`, Bindung an gespeicherten Kandidaten, atomare Übergänge | 3.5.1 |
| 8 | Selbstschutz bei Ursprung nur über den Namen | MEDIUM | `id` von `parent`, `source`, `template_repository` gegen `SELF_REPO_IDS`; Repo-ID nach dem Spiegeln und vor dem Push erneut | 3.5 Schicht 4 |
| 9 | Datenmodell: Leserechte auf `profiles` und Erstanmeldung, `revoke` für andere Rollen, Löschlauf ohne Delete-Recht, Schema je Instanz, Schlüsselkennung im Chiffrat | MEDIUM | alles in 3.2 ergänzt | 3.2 |
| 10 | Der Dienst kennt Zulassung und Grenzen nicht | MEDIUM | eigene Zulassungsliste, Grenzen je Person und Stunde, Plattenquoten | 3.5.2 |
| 11 | Text des Agenten in der Commit-Nachricht unter dem Namen der Person | MEDIUM | nur feste Vorlage, Titel aus dem signierten Start, Trailer nur vom Dienst | 3.6 |
| 12 | `sandbox_env` gäbe im persönlichen Weg Server-Tokens aus `geheim.env` mit; Feld `github` in PC-Kanal und lokal; `ERLAUBT_RE` erlaubt höchstens 10 Git-Einträge | MEDIUM | im persönlichen Weg keine Dienst-Tokens aus `geheim.env`, Feld nur im Kern-Kanal, Test; höchstens 6 Git-Einträge | PZ-7 |
| 13 | Vercel vor dem Freeze bringt wenig und hat keinen Nur-Lese-Bereich | MEDIUM | Vercel nach dem 05.12. (PZ-12) | 3.11, D4 |
| 14 | Widerruf wirkt nicht sofort auf Spiegel und Datensätze | LOW | Löschen und Ungültig setzen alle offenen Datensätze der Person auf `verworfen`, das Tor prüft je Anfrage | 3.7 |
| 15 | Oberfläche und Caddy: CSP, Eingabe im Ursprung der Oberfläche, Körpergrenze, Methoden, Quelladresse, Form der Kennungen | LOW | Eingabe nur im Bedienfeld, CSP mit `frame-ancestors`, `request_body max_size`, nur `GET` und `POST`, Quelle aus Caddy, Kennungen streng geprüft, voller Hash der `user_id` im Datensatz | 3.4, 3.9 |
| 16 | Supabase: nur SELECT ist kein Schreibschutz, `sbp_`-Tokens gelten kontoweit | LOW | Produktion nur über eine eigene Datenbankrolle `READ ONLY` der Person, nie über die Management-API | PZ-13 |

**Nicht oder nur teilweise übernommen**

- **Befund 1, Restfenster:** Der Geräteschlüssel schließt den gekaperten Kern aus, solange er keinen Code im Ursprung des Bedienfelds ausführen kann und kein Token mit frischem
  Code bekommt. Verbindet sich die Oberfläche in den 60 Sekunden nach einem Code neu mit dem Kern, hätte er ein frisches Token und könnte in diesem Fenster einen eigenen
  Geräteschlüssel anmelden. Gegenmaßnahme: Die Oberfläche verbindet sich nach einem Code 90 Sekunden lang nicht neu, und jede Anmeldung eines Geräts erscheint als deutlicher Hinweis
  auf allen Geräten der Person. Ganz geschlossen ist das nur mit einer Netzregel, die `wamo-core` den Port 55444 verbietet (Annahme A11, optional in PZ-3).
- **Befund 6, „besser erst nach dem Freeze“:** übernommen als Empfehlung D4. Die Entscheidung Z7 des Admins steht dagegen, deshalb bleibt Plan A (Pilot nur für das Admin-Profil vor
  dem Freeze) als ausdrücklich nicht empfohlene Möglichkeit beschrieben.

## 1. Ziel, Entscheidungen, Abgrenzung

**Entscheidungen des Admins vom 18.11.2026 (verbindlich)**

| Nr. | Entscheidung | Wirkung im Papier |
| --- | --- | --- |
| Z1 | Entwicklungsaufträge arbeiten mit den eigenen Zugängen der Person statt nur mit der GitHub-App. Das muss gut abgesichert sein, und man soll sehen, in welchem Auftrag welcher Person W.A.I.S. etwas geändert hat | ganzes Papier, Kennzeichnung 3.6, Audit 3.8 |
| Z2 | Jede Person hinterlegt in der Oberfläche eigene Tokens. Personen ohne Claude-Zugang müssen Tokens hinterlegen, Personen mit Claude später auch über ihre Claude-Konnektoren oder alternativ Token | 3.9, Konnektoren 4.4 |
| Z3 | GitHub: fein-granulare (`github_pat_`) und klassische (`ghp_`) Tokens werden angenommen | 3.3, D1 |
| Z4 | Schreiben nur auf einen eigenen Zweig `wamo/<auftrag>` plus Pull Request, nie auf den Standardzweig, kein Löschen, keine Repo-Einstellungen, Push erst nach dem Klick auf der Freigabekarte, Merge durch Menschen | 3.5 |
| Z5 | Vercel: eigenes Token der Person | 3.11, PZ-12 |
| Z6 | Supabase: nur ausgewählte Projekte der Person über einen Proxy am Server, nie Produktion ohne Auswahl | PZ-13 |
| Z7 | Zeitplan: GitHub und Vercel live vor dem Freeze am Montag 23.11. (Umsetzung bis Sonntag 22.11.), Supabase und Konnektoren nach dem Labortag am 05.12. | 4.1 bis 4.5; das Review empfiehlt eine Abweichung (D4) |
| Z8 | Laborprofile bekommen davon nie etwas | 3.1 (Zeile Laborprofil), 3.9, Tests |

**Ziel.** (1) Kein persönliches Token liegt je im Klartext in der Sandbox, im Dispatcher, im Kern, im Ursprung der Oberfläche, in einer Datei, in einer Protokollzeile, in der Datenbank
oder in einem Prozess, der feindliche Git-Daten verarbeitet (außer dem kurzlebigen Kind, das genau dieses eine Token für genau einen Push braucht). (2) W.A.I.S. kann mit einem
persönlichen Token nur das eine Repo des Auftrags lesen, in eine Quarantäne schreiben und nach dem signierten Klick der Person genau einen Commit nach `wamo/<auftrag>` pushen und
einen Pull Request öffnen, unabhängig von den Rechten des Tokens. (3) Keine Handlung mit dem Token ohne Signatur eines angemeldeten Geräts der Person. (4) Jede Benutzung ist der
Person sichtbar, aus einer Quelle, die der Kern nicht fälschen kann. (5) Widerruf wirkt sofort, abgelaufene Tokens werden nie benutzt. (6) Laborprofile, der PC-Kanal und der
bisherige App-Weg bleiben unverändert.

**Nicht-Ziele.** Merge durch W.A.I.S. (nie). Schreiben ohne Pull Request. Vercel-Deploys aus der Sandbox oder Produktion. Supabase und Konnektoren vor dem 05.12. Schutz vor einem
Admin mit root auf Sokrates-2. Die Release-Freigabe und der App-Weg (Folgepaket 1) ändern sich nicht; PZ-16 kann den App-Weg später auf denselben Dienst umstellen. Der persönliche
Claude-Zugang bleibt, wie er ist (zweite stdin-Zeile).

## 2. Ist-Stand mit Belegen

| Nr. | Aussage | Beleg | Folge für den Plan |
| --- | --- | --- | --- |
| 1 | Der persönliche Claude-Zugang liegt je Profil verschlüsselt in `model_access` (AES-256-GCM, AAD Profil und Zweck, Schlüsselkennung im Kopf), der Hauptschlüssel liegt beim Kern, der Kern entschlüsselt je Lauf und schickt den Wert als zweite stdin-Zeile, der Dispatcher legt ihn in die Umgebung der Sandbox | voice-core/schluessel.py:1-14,83-118, voice-core/modellzugang.py:703-745, voice-core/dev_agent.py:203-222,1310-1318, infra/sokrates2/wamo_job_dispatch.py:21-28,871-893 | Gutes Muster für „nie in argv“. Für GitHub **nicht** übernehmen: Der Kern kennt alle Werte, die Sandbox hat den Wert, Port 443 ist offen |
| 2 | GitHub heute: App-Modus mit Installations-Token je Lauf als `GH_TOKEN` in der Sandbox (Rechte je Art, ein Repo, Widerruf am Ende), sonst `GH_TOKEN` aus `geheim.env`; git meldet sich über `gh auth git-credential` an; ohne App-Modus gehen auch `VERCEL_TOKEN` und `SUPABASE_ACCESS_TOKEN` der Art mit | wamo_job_dispatch.py:61-67,903-920, voice-core/werkzeugkarte.py:52-97,283-286 | Ein schreibendes Token liegt heute in der Sandbox. Im neuen Weg gibt es dort kein Dienst-Token, auch keines aus `geheim.env` |
| 3 | Im Kern-Kanal gilt GitHub nur im App-Modus und nur für ein Repo aus `REPOS` (global, höchstens 10) | infra/sokrates2/wamo_job_kernkanal.py:100,407-417,830-835 | Genau das fehlt der Person. Der neue Weg braucht eine eigene Regel statt `REPOS` |
| 4 | Supabase ist im Kern-Kanal nie erlaubt, andere Dienste nur aus `DIENSTE` | wamo_job_kernkanal.py:427-432,837-839 | bleibt bis PZ-13 so |
| 5 | Der Wächter fordert für `git push` eine Freigabe, sieht aber nur Bash-Aufrufe von Claude Code; Projektcode sieht `GH_TOKEN`; „kein Push auf den Standardbranch“ wird nur beobachtet | voice-core/dev_guard.py:166-181, docs/entwicklung-im-betrieb-arbeitsliste.md:311, docs/entwicklung-im-betrieb.md 4.6 (Zeile „Direkter Push“) | Durchsetzung muss außerhalb der Sandbox liegen (3.5) |
| 6 | Die Sandbox (Benutzer `wamo`) erreicht das Internet auf TCP 80 und 443, Loopback nur 20000 bis 20999 und 18090 | infra/sokrates2/wamo-egress.nft:31-39 | Jeder Wert in der Sandbox kann abfließen. Neuer Loopback-Port 18091 für das Git-Tor |
| 7 | Dispatcher und Sandbox laufen beide als `wamo`, der App-Schlüssel ist für den Dispatcher lesbar | wamo_job_dispatch.py:930-933, docs/folgepaket-1.md 2.1 Nr. 27 | Ein Ausbruch auf `wamo` darf keine persönlichen Tokens erreichen |
| 8 | Vorbild Haus-Proxy: eigener Benutzer, Schlüssel nur als Credential, Auftragstoken je Lauf, nur der Hash in `/run/wamo-haus/<job>.json`, Landlock öffnet den Port nur für diese Zugangsart | infra/sokrates2/wamo_haus_proxy.py:1-30, infra/sokrates2/wamo-haus-proxy.service:17,56, wamo_job_dispatch.py:29-36, infra/sokrates2/wamo-job.sh:242-275 | Git-Tor und Auftragstoken `wz1-` folgen diesem Muster |
| 9 | Vorbild Freigabe-Dienst: Route am Kern vorbei über Caddy (Port 55444) an einen Unix-Socket, `SO_PEERCRED`, Token über JWKS, aal2 mit Frische des jüngsten Codes (60 s) | infra/sokrates2/anker/freigabe_dienst.py:1-20,64-66, infra/sokrates2/anker/freigabe.py:102-147, infra/sokrates2/wamo-caddy/kern/wamo-core.caddy:28-54 | Routen und Bedienfeld `/wamo/zugang/...` bauen genauso; die Frischeprüfung gilt für die Anmeldung eines Geräts |
| 10 | Der Kern sieht das Sitzungstoken der Oberfläche, ein frischer Code beim Einreichen wurde abgelehnt (E1) | docs/folgepaket-1.md 2.1 Nr. 13 und Entscheidung E1 | Ohne Geräteschlüssel kann ein gekaperter Kern jede Route selbst aufrufen (Befund 1) |
| 11 | Die Kopfzeile von `start` weist unbekannte Felder ab, `kernkanal.conf` schließt bei unbekannten Schlüsseln den Kanal | wamo_job_dispatch.py:459-472, wamo_job_kernkanal.py:145-146 | Neues Feld `github` nur an Dispatcher 10 (ping), neuer Schlüssel `PERSOENLICH` erst danach, Rückweg umgekehrt |
| 12 | `managed-mcp.json` bindet den GitHub-MCP-Server mit `${GH_TOKEN}` ein | infra/sokrates2/claude-code/managed-mcp.json:11-17 | Ohne `GH_TOKEN` bleibt er im neuen Weg leer, Ersatz mit PZ-14 |
| 13 | Folgepaket 1 (Veröffentlichung durch den Dispatcher, Beleg) ist nicht gebaut | docs/folgepaket-1.md:3-8, kein `einreichen` in wamo_job_dispatch.py | Der neue Dienst übernimmt für den persönlichen Weg die Rolle von F1 und F2, mit dessen Pfadregeln (FP1 3.1.3) |
| 14 | Laborprofile tragen `labor_art`; der Freigabe-Dienst prüft Admin und Stand | supabase/migrations/0021_profil_freischaltung.sql:3-7,42, infra/sokrates2/anker/freigabe.py:90-92 | Der Dienst prüft aktiv, nicht Labor, Erstanmeldung, Zulassung, aal2 |
| 15 | Dienst-Rollen legt eine Migration `nologin` an, Rechte anderer Dienst-Rollen werden ausdrücklich entzogen | supabase/migrations/0013_release_freigaben.sql:17,67-76 | Rolle `wamo_zugang` nach diesem Muster (PZ-1) |
| 16 | `fork_pruefen` vergleicht `parent`, `source` und `template_repository` nur über `full_name` | wamo_job_kernkanal.py:853-877 | Im Dienst zusätzlich über die ID (Befund 8) |
| 17 | Die Sandbox lässt nur die Namen aus `ERLAUBT_RE` durch, Git-Einträge `GIT_CONFIG_KEY_[0-9]` | infra/sokrates2/wamo-job.sh:229-233 | Höchstens 10 Einträge, der persönliche Weg braucht 4 |

### 2.1 Welche Risiken aus Folgepaket 1 und dem Hauptpapier mit persönlichen Tokens größer werden

Verglichen wird der heutige App-Weg mit einem persönlichen Token, das man wie den Claude-Zugang führen würde (Kern entschlüsselt, Wert in die Sandbox).

| Risiko (Quelle) | Heute mit der App | Mit persönlichem Token nach Muster Claude-Zugang | Vor Live zwingend? | Lösung hier |
| --- | --- | --- | --- | --- |
| Token in der Sandbox, Port 443 offen (Hauptpapier 4.6 „Token-Abfluss GitHub“) | ein Repo, eine Stunde, am Ende widerrufen | bis zu einem Jahr oder unbefristet, alle Repos der Person und ihrer Organisationen, bei `delete_repo` auch Löschen | **ja** | Token nie in der Sandbox, Git-Tor mit Auftragstoken (3.4) |
| Gekaperter Kern kennt alle Profilzugänge über den Hauptschlüssel (Hauptpapier 4.2, 4.6) | Claude-Zugänge | dazu die vollen GitHub- und Vercel-Konten aller Personen | **ja** | Eingabe im Bedienfeld, eigener Schlüssel im Dienst, Chiffrat für `wamo_core` gesperrt (3.2, 3.4) |
| Kern sieht das Sitzungstoken und kann Belege selbst holen (FP1 3.2, E1) | Pull Request auf `wamo/<job>` in einem Repo aus `REPOS` | Repos lesen, Zweige und Pull Requests unter dem Namen der Person in allen ihren Repos | **ja** (Befund 1) | Geräteschlüssel signiert jede Handlung, Anmeldung je Gerät mit frischem Code (3.3, 3.9) |
| Push nur beobachtet (Arbeitsliste S10, Hauptpapier 4.6 „Direkter Push“) | Testrepo | Push auf `main`, Force-Push, Löschen in Produktionsrepos | **ja** | Quarantäne, Hooks als einzige Instanz, Push nur durch den Dienst mit fester Refspec (3.5) |
| Ausbruch auf `wamo` liest den App-Schlüssel (FP1 Risiko 8) | alle Repos der Installation | alle persönlichen Tokens, wenn der Dispatcher sie hält | **ja** | Dispatcher sieht nie ein Token, Startdatensatz nur vom Dienst schreibbar und vom Gerät signiert (3.4, 3.5.1) |
| CI auf `wamo/**` mit Repo-Secrets (FP1 Risiko 2) | nur Repos aus `REPOS` mit geprüfter Voraussetzung | jedes Repo der Person, ohne Prüfung | **ja** (Befund 2) | Prüfung der Workflows, Sperre ohne Bestätigung je Repo (3.5 Schicht 3) |
| Selbstschutz, Kopie des eigenen Repos (Hauptpapier 4.6) | Auswahl der App-Installation | das Token des Admins erreicht `Wamocon/w.a.i.s` selbst | **ja** | Name und GitHub-ID, auch der Ursprünge, beim Start, nach dem Spiegeln und vor dem Push (3.5 Schicht 4) |
| Feindliches `.git` aus der Sandbox (FP1 2.2) | entfällt, der Agent pusht selbst | Dienst würde Objekte und Konfiguration aus der Sandbox verarbeiten | **ja** (Befunde 3, 5) | Pack-Übergabe an den Prüfer ohne Geheimnisse, eigener Commit, zweite Prüfung im Push-Kind (3.5) |
| Gestohlenes Sitzungstoken aus dem Browser (FP1 Risiko 13) | Beleg ohne Code | wie gekaperter Kern | nein, mit Gerätebindung | ohne Geräteschlüssel keine Handlung; neues Gerät nur mit Code |
| Release-Freigabe ohne frischen Code (FP1 Risiko 16) | unverändert | unverändert | nein | keine Folge dieses Papiers |

### 2.2 Was daraus folgt

- **Das Token gehört in genau einen Prozess und für einen Push in genau ein Kind.** Nur `wamo-zugang` entschlüsselt. Er verarbeitet selbst nie Git-Objekte. Für Spiegel und Push
  bekommt ein Kind in bwrap das eine Token in seiner Umgebung, sonst nichts. Was W.A.I.S. mit dem Token tun kann, bestimmen die Konstanten `GITHUB_WEGE` und die eine Refspec.
- **Der Klick muss beweisbar von der Person kommen.** Ein Sitzungstoken beweist das nicht, weil der Kern es hat. Ein nicht exportierbarer Schlüssel im Ursprung des Bedienfelds
  schon, solange dort kein fremder Code läuft. Daher: Bedienfeld vom Dienst, CSP, kein Inhalt aus dem Kern im Bedienfeld.
- **Die Sandbox braucht für GitHub nur Git.** Issues, Kommentare, `gh` und der GitHub-MCP-Server fallen im persönlichen Weg vorerst weg (PZ-14, PZ-15).

### 2.3 Annahmen, die nicht belegt sind

| Nr. | Annahme | Prüfstelle |
| --- | --- | --- |
| A1 | GitHub antwortet auf `GET /user` mit einem klassischen Token mit `X-OAuth-Scopes`, mit einem fein-granularen ohne sie | PZ-0, Wegwerf-Tokens beider Arten |
| A2 | GitHub nennt das Ablaufdatum in `GitHub-Authentication-Token-Expiration`, für beide Arten | PZ-0. Sonst fragt das Bedienfeld das Datum ab und der Dienst prüft täglich (3.7) |
| A3 | `git clone --mirror` über HTTPS mit `http.extraHeader` aus `GIT_CONFIG_*` funktioniert ohne Credential-Helper, mit `http.followRedirects=false`, in bwrap über einen CONNECT-Proxy | PZ-0 |
| A4 | `git http-backend` hinter einem kleinen HTTP-Server bedient Klon und Push der Sandbox über `url.<tor>.insteadOf=https://github.com/`, auch mit `Content-Encoding: gzip`; `core.hooksPath` aus `GIT_CONFIG_*` des Prozesses gilt für `receive-pack` und lässt sich vom Repo nicht überschreiben; eine Quarantäne mit `objects/info/alternates` auf den Spiegel bekommt nur neue Objekte | PZ-0, Probe in einem Wegwerf-Repo |
| A5 | Vercel liefert die Metadaten des eigenen Tokens über `GET /v5/user/tokens/current` (nur in einem Spiegel der Doku belegt) | PZ-12 |
| A6 | Supavisor nimmt einen weiteren Datenbankbenutzer `wamo_zugang.wamo` mit `sslmode=verify-full` an | PZ-0 (nur Konfiguration lesen), PZ-3 |
| A7 | Caddy auf 55444 reicht `/wamo/zugang/...` an einen zweiten Unix-Socket und liefert das Bedienfeld mit eigener CSP aus | PZ-3 |
| A8 | Die Vercel-Projekte bauen Vorschauen für Zweige `wamo/*` über die Git-Integration | PZ-12, je Projekt |
| A9 | GitHub leitet umbenannte Repos für git und REST weiter; mit `followRedirects=false` und der ID-Prüfung wird das sichtbar | PZ-0 |
| A10 | Der vorhandene Domain-Proxy der Prüfer-Sandbox (`wamo-pruefer-proxy@`) lässt sich als eigene Instanz für `github.com` und `api.github.com` betreiben | PZ-0, PZ-3 |
| A11 | Eine nft-Regel kann `wamo-core` die Verbindung zu Port 55444 verbieten, ohne die Reihenfolge zur NAT-Kette von Docker zu brechen (wie FP1 Annahme 11) | PZ-3, optional |
| A12 | bwrap aus der Prüfer-Einrichtung (`/usr/local/lib/wamo-pruefer/bwrap` mit AppArmor-Profil) ist für den Benutzer `wamo-zugang` nutzbar, oder eine eigene Kopie mit eigenem Profil | PZ-0 |

## 3. Entwurf

```text
Gerät anmelden (einmal je Browser, mit frischem Code)
  Oberfläche ─ Rahmen ─> Bedienfeld (vom Dienst, https://...:55444/wamo/zugang/feld)
             Bedienfeld erzeugt Geräteschlüssel (WebCrypto P-256, nicht exportierbar), Oberfläche holt einen frischen Code (mfa verify),
             gibt das frische Token nur ans Bedienfeld, nie an den Kern; Dienst prüft Code höchstens 60 s alt, speichert den öffentlichen Schlüssel
Token hinterlegen
  Bedienfeld ── POST /wamo/zugang/github {token, Signatur} ──unix──> wamo-zugang: prüft bei GitHub (über den Domain-Proxy), verschlüsselt, Chiffrat in die DB
Start (Klick im Bedienfeld auf der Auftragskarte)
  Bedienfeld ── POST /wamo/zugang/auftrag/<job>/start {repo, art, titel, Signatur} ──> wamo-zugang
             prüft Person, Zulassung, Repo (ID, Ursprünge), Kind in bwrap legt Spiegel an, Startdatensatz (frei)
  Oberfläche ── auftrag_start ──> Kern ── ssh ──> Dispatcher 10 (Kopf {"github": "persoenlich"}): prüft Startdatensatz, wz1-Token, Hash nach /run
Lauf
  Sandbox (wamo) ── git über http://127.0.0.1:18091 (insteadOf, wz1) ──> wamo-zugang-git (kein Token, kein Internet)
             Klon aus dem Spiegel; Push nur refs/heads/wamo/<job> in die Quarantäne (root-eigene Hooks entscheiden)
Kandidat
  wamo-zugang-git legt eine Pack-Datei ab ──> wamo-zugang-pruef (kein Netz, keine Geheimnisse): index-pack --strict, ein Commit, Regeln, CI-Prüfung
Einreichen (Klick im Bedienfeld auf der Änderungskarte)
  Bedienfeld ── POST .../einreichen {tree_id, bestätigte Dateien, Signatur} ──> wamo-zugang
             Kind in bwrap mit nur diesem Token: importiert den Kandidaten, prüft erneut, push <commit>:refs/heads/wamo/<job>, Pull Request
```

| Baustein | Benutzer | Kennt das Token | Verarbeitet feindliche Git-Daten | Netz |
| --- | --- | --- | --- | --- |
| `wamo-zugang` (Zugangsdienst mit Bedienfeld) | `wamo-zugang`, Schlüssel nur als systemd-Credential | ja, entschlüsselt je Handlung | nein | nur Unix-Socket eingehend, ausgehend Datenbank und Domain-Proxy |
| Transport-Kind (Spiegel, Push) | `wamo-zugang` in bwrap ohne Credentials-Ordner, ohne Datenbank, eigener PID- und IPC-Namensraum | nur das eine Token des Vorgangs | ja (Repo von GitHub, Kandidat) | nur Domain-Proxy |
| `wamo-zugang-git` (Git-Tor) | `wamo-zugang-git` | nein | ja (Push der Sandbox) | nur Loopback eingehend, kein Ausgang (`IPAddressDeny=any`) |
| `wamo-zugang-pruef` (Prüfer, socket-aktiviert) | `wamo-zugang-pruef` | nein | ja (Pack aus der Quarantäne) | keins |
| `wamo-zugang-proxy` (Domain-Proxy) | eigener Benutzer, Instanz nach `wamo-pruefer-proxy@` | nein (TLS geht durch) | nein | nur `github.com`, `api.github.com` (später `api.vercel.com`) |
| Dispatcher 10 | `wamo` | nein, nur `wz1-` | wie heute | wie heute |
| Kern | `wamo-core` | nein, nur Metadaten | nein | wie heute |
| Oberfläche | Browser, Ursprung 55445 | nein | nein | wie heute |
| Datenbank | `wamo_zugang` schreibt, `wamo_core` liest Metadaten | nur Chiffrat | nein | |

### 3.1 Bedrohungsmodell

| Angreifer | Ohne Schutz möglich | Gegenmaßnahme | Restrisiko |
| --- | --- | --- | --- |
| **Prompt-Injection im Auftrag** (README, Issue, Abhängigkeit, Webseite, Testskript) steuert Claude Code in der Sandbox | Token aus der Umgebung lesen und über 443 senden; mit klassischem Token alle Repos lesen, schreiben, Workflows ändern, eventuell löschen | Kein Token in der Sandbox. `wz1-` gilt nur am Tor auf Loopback, nur für diesen Auftrag, nur während des Laufs, nur Lesen aus dem Spiegel und Schreiben nach `wamo/<job>` in die Quarantäne | Quelltext des Auftragsrepos kann über 443 abfließen (wie heute). Eine Hintertür im Code landet im Pull Request, das Tor ist das Lesen der Person und der Merge durch Menschen |
| **Ausbruch aus der Sandbox auf `wamo`** | Speicher des Dispatchers lesen, Auftragsdateien fälschen | Der Dispatcher hält nie ein Token. Das Tor verlangt den Startdatensatz des Dienstes, den nur `wamo-zugang` schreibt und den ein Gerät der Person signiert hat. Die Datei in `/run/wamo-zugang-auftraege` ist für `wamo` schreibbar und beweist nur die Laufzeit, nicht die Berechtigung | Lesen der Repos und Schreiben in die Quarantänen gerade laufender, signierter Aufträge (auch anderer Personen) für deren Frist. App-Schlüssel wie heute lesbar (FP1 Risiko 8) |
| **Übernahme des Git-Tors** | Quarantäne fälschen, fremde Spiegel einhängen | eigener Benutzer ohne Schlüssel, Datenbank und Internet. Es übergibt nur eine Pack-Datei; der Prüfer setzt die Alternates selbst aus dem Startdatensatz, öffnet die Quarantäne nie und importiert mit `index-pack --strict` | Ein gefälschter Kandidat geht durch Prüfer und Push-Kind erneut durch dieselben Regeln. Ein Fehler in `index-pack` trifft den Prüfer (ohne Geheimnisse) |
| **Übernahme des Prüfers** (Fehler in git beim Import) | falscher Prüfbericht | ohne Netz und Geheimnisse; das Push-Kind prüft den Kandidaten erneut mit `diff-tree` und denselben Regeln, bevor es pusht | Ein Fehler in git im Push-Kind trifft genau das eine Token dieses Vorgangs |
| **Gekaperter Kern** (`wamo-core`) | Bei einem Muster wie beim Claude-Zugang alle Tokens entschlüsseln; mit dem Sitzungstoken jede Route aufrufen | Weder Schlüssel noch Chiffrat für `wamo_core`; jede Handlung braucht die Signatur eines Geräteschlüssels aus dem Ursprung des Bedienfelds; neues Gerät nur mit Code höchstens 60 Sekunden alt; nach einem Code verbindet sich die Oberfläche 90 Sekunden nicht neu; jede Geräteanmeldung als Hinweis auf allen Geräten; optional Netzregel (A11) | Restfenster aus „Stand nach Review“: frisches Token bei einer Neuverbindung im Fenster. Ohne Gerät kann er Aufträge mit App oder ohne GitHub starten wie heute |
| **Fremder Code im Ursprung der Oberfläche** (XSS über Inhalte des Kerns) | Eingabefeld mitlesen, Geräteschlüssel benutzen | Eingabe und Schlüssel liegen im Ursprung des Bedienfelds (55444), nicht in dem der Oberfläche (55445); das Bedienfeld zeigt nur Daten des Dienstes, hat eine strenge CSP (kein Inline-Skript, `frame-ancestors` nur der Ursprung der Oberfläche) und signiert nur nach einem Klick in sich selbst | Ein Fehler im Bedienfeld selbst. Der Code ist klein und ohne Abhängigkeiten |
| **Übernahme des Zugangsdienstes** | alle hinterlegten Tokens | kleiner Code, nur Standardbibliothek und hash-gesicherte Bibliotheken wie beim Freigabe-Dienst, keine Git-Verarbeitung im Prozess, systemd-Härtung wie `wamo-haus-proxy.service`, eingehend nur Unix-Socket (Caddy, root), ausgehend nur Datenbank und Domain-Proxy, Sicherheitsreview (PZ-10) | Totalschaden der hinterlegten Tokens. Begrenzt durch Ablaufpflicht (D1) und Notaus mit Aufforderung zum Widerruf bei GitHub (3.7) |
| **Log-Leck** | Wert in Journal, `actions`, `turns`, Gedächtnis, Fehlertext, Ausgabe | Dienst protokolliert nur Codes, Person (8 Zeichen), Auftrag; stderr der Kinder geschwärzt (exakter Wert und Muster); Kern und Dispatcher haben keinen Wert; Schwärzung des Dispatchers und des Kerns um `ghp_`, `github_pat_`, `wz1-` ergänzt | Ein Wert, den die Person selbst in einen Auftragstext diktiert, wird nur über das Muster erkannt |
| **Gestohlene Datenbank oder Sicherung** | Chiffrat entschlüsseln | AES-256-GCM, eigener Schlüssel nur als Credential des Dienstes, nie in `core.env` oder der Datenbank; AAD bindet Person, Dienst und Art | Diebstahl von Datenbank und Schlüsseldatei zusammen (root). Metadaten lesbar |
| **Gestohlenes Sitzungstoken** (Browser) | Token ersetzen oder löschen, Aufträge auslösen | ohne Geräteschlüssel keine Handlung; ein neues Gerät verlangt einen frischen Code | Wer Sitzung und Code hat, ist die Person |
| **Bösartiges Ziel-Repo** | Hooks, Filter, `.gitmodules`, riesige Packs beim Spiegeln | Spiegel als `--mirror` im Transport-Kind (bare, ohne Hooks, Filter und Checkout), `fetch.fsckObjects`, Größe und Zeit begrenzt; Code des Repos läuft nur in der Sandbox | keins über heute hinaus |
| **CI und Vorschau-Builds** mit Secrets | Code des Agenten läuft nach dem Push in Actions oder als Vorschau mit Secrets | Prüfung der Workflows der Basis sperrt das Einreichen (3.5 Schicht 3), `.github/` und Ausführungsflächen gesperrt, sensible Dateien einzeln bestätigt | Mit bestätigter Ausnahme je Repo läuft der Code wie bei jedem menschlichen Push; Vercel-Vorschauen erkennt die Prüfung nicht (Hinweis bei der Freischaltung) |
| **Verwechslung** zwischen Personen oder Aufträgen | Token von A im Auftrag von B | Startdatensatz mit der vollen `user_id` aus dem geprüften Token und deren Hash; Dispatcher und Tor prüfen Kennung und Repo gegen Datei und Datensatz; AAD verhindert vertauschte Chiffrate | keins erkennbar |
| **Laborprofil** | Zugang zu Tokens oder Repos im Testlabor | Dienst weist jedes Profil mit `labor_art` ab (`labor_pfad_gesperrt`), Bedienfeld erscheint nie, der Kern schickt für Laborsitzungen nie `persoenlich`, Tests auf allen Ebenen | keins erkennbar |
| **Eigenes Repo und Kopien** | W.A.I.S. ändert sich selbst über das Token des Admins | Name und ID gegen `SELF_REPO_IDS`, auch für `parent`, `source` und `template_repository`, beim Start, nach dem Spiegeln und vor dem Push; keine Weiterleitungen | Eine Kopie ohne Fork-Beziehung unter anderem Namen; das gilt heute ebenso |

### 3.2 Datenmodell (Migration 00NN, nächste freie Nummer nach Plan C, 0026 und 0027 sind belegt)

Neue Migration `supabase/migrations/00NN_entwicklung_zugaenge.sql` mit `.down.sql` und Test `supabase/tests/00NN_entwicklung_zugaenge_test.sql` (0026 und 0027 sind belegt), Platzhalter `__SCHEMA__`, nach
den Regeln aus CLAUDE.md (RLS, eigene Policies, nur nötige Grants, FK-Indizes, keine Rechte für `anon`, `authenticated`, `service_role`, `drop ... if exists` vor Policies und
Triggern), keine `admin_all`-Policy auf den neuen Tabellen, ausdrückliches `revoke all` für `wamo_admin`, `wamo_release`, `wamo_anker` nach dem Muster von 0013. Rolle
`wamo_zugang` `nologin` wie in 0013, das Anmelden richtet `zugang-einrichten.sh` ein. Agent `database-reviewer` vor jedem Apply in PROD.

| Tabelle | Spalten | Rechte |
| --- | --- | --- |
| `entwicklung_zugaenge` | `user_id` (FK `profiles`, `on delete cascade`), `dienst` (`github`, später `vercel`, `supabase`), `art` (`fein`, `klassisch`, `token`), `chiffrat` (bytea, höchstens 2048 Byte), `ende` (4 Zeichen), `konto`, `konto_id`, `rechte`, `ablauf`, `status` (`gueltig`, `ungueltig`, `abgelaufen`), `geprueft_at`, `angelegt_at`, `geaendert_at`, `geaendert_von_geraet`; Primärschlüssel (`user_id`, `dienst`) | `wamo_zugang`: select, insert, update, delete. `wamo_core`: select **nur auf Spalten ohne `chiffrat`** |
| `entwicklung_zugang_geraete` | `geraet` (16 Hex), `user_id`, `schluessel` (öffentlicher P-256-Schlüssel, SPKI), `name` (vom Browser, bereinigt), `angemeldet_at`, `code_at` (Zeit des Codes), `zuletzt_at`, `widerrufen_at` | `wamo_zugang`: select, insert, update. `wamo_core`: select ohne `schluessel` |
| `entwicklung_zugang_repos` | `user_id`, `repo`, `repo_id`, `freigeschaltet_at`, `geraet`, `ci_ausnahme` (bool, nur mit eigenem signiertem Schritt und frischem Code) | `wamo_zugang`: select, insert, delete. `wamo_core`: select |
| `entwicklung_zugang_auftraege` | `job` (16 bis 32 Hex), `user_id`, `user_hash` (SHA-256 der vollen `user_id`), `repo`, `repo_id`, `art`, `stufe`, `titel`, `basis`, `standardzweig`, `status` (3.5.1), `bis`, `kandidat_commit`, `kandidat_tree`, `pr_nummer`, `pr_adresse`, `geraet_start`, `geraet_einreichen`, Zeiten | `wamo_zugang`: select, insert, update. `wamo_core`: select |
| `entwicklung_zugang_ereignisse` | `id`, `t`, `user_id`, `dienst`, `ereignis` (`geraet_angemeldet`, `geraet_widerrufen`, `hinterlegt`, `geprueft`, `geloescht`, `ungueltig`, `repo_frei`, `start`, `spiegel`, `kandidat`, `einreichen`, `eingereicht`, `abgewiesen`, `notaus`), `job`, `repo`, `ergebnis`, `grund`, `quelle` (Adresse, die Caddy als Gegenstelle sah), `geraet` | `wamo_zugang`: select, insert. `wamo_core`: select. Löschen nur über die Funktion `ereignisse_aufraeumen()` (security definer, löscht nur Zeilen älter als 365 Tage), Ausführen nur für `wamo_zugang` |

Zum Lesen braucht `wamo_zugang` außerdem `select` auf `profiles` (`user_id`, `aktiv`, `rolle`, `labor_art`) und `execute` auf `wamo_auth.erstanmeldung_stand(uuid)`. Prüfregeln in der
Datenbank: Aufzählungen als Check, `ende` genau vier Zeichen, `repo` in der Form `owner/name`, `job` und `geraet` als Hex.

**Verschlüsselung.** AES-256-GCM wie `voice-core/schluessel.py`: `z1 | Kennung des Schlüssels (4 Byte) | Nonce (12 Byte) | Chiffrat mit Prüfsumme`, AAD
`wamo-entwicklung-zugang:v1:<user_id>:<dienst>:<art>`. Schlüssel 32 Byte in `/etc/wamo-zugang/kek` (root:root 0400), nur über `LoadCredential=` an den Dienst; Wechsel über
`kek.alt` (die Kennung im Kopf wählt den Schlüssel, kein Probieren). Kein Backup nötig: Geht der Schlüssel verloren, tragen die Personen ihre Tokens neu ein. **Wer liest:** nur der
Prozess `wamo-zugang`, je Handlung frisch; er reicht den Wert nur an das Transport-Kind dieses Vorgangs weiter.

**Instanzen.** Eine Instanz je Schema mit eigenem Socket, eigenem Schlüssel und eigener Rolle in der Verbindung: live nur `wamo_prod`, für den Rauchtest eine zweite Instanz auf
`wamo_test` (Caddy-Route nur für prod).

**Verworfen:** Tokens in `model_access` mit `WAMO_SCHLUESSEL_KEK` (Kern entschlüsselt alles). Tokens als Datei ohne Datenbank (keine Spaltenrechte, kein Schema).

### 3.3 Geräte und Prüfung beim Speichern

**Gerät anmelden.** Das Bedienfeld erzeugt mit WebCrypto ein ECDSA-P-256-Schlüsselpaar mit `extractable: false` und legt es in seiner IndexedDB ab (Ursprung 55444). Die Oberfläche
holt einen frischen Code des zweiten Faktors (wie bei der Release-Freigabe, `ui/src/lib/aenderungenFreigabe.ts`) und gibt das neue Token per `postMessage` nur an das Bedienfeld
(Ursprung geprüft), nie an den Kern; danach verbindet sie sich 90 Sekunden nicht neu. `POST /wamo/zugang/geraet` mit öffentlichem Schlüssel und Namen: Der Dienst verlangt aal2 mit
einem Code höchstens 60 Sekunden alt (`aal2_zeit` aus `anker/freigabe.py`), aktives Profil ohne `labor_art`, Erstanmeldung erledigt, Zulassung (3.5.2), höchstens 5 Geräte je Person.
Jedes angemeldete Gerät erscheint als Hinweis auf allen anderen Geräten der Person.

**Signierte Handlungen.** Jede Route außer `stand` verlangt zusätzlich zum Sitzungstoken die Kopfzeile mit Gerät und Signatur über
`wamo-zugang-v1:<route>:<job oder ->:<SHA-256 des Körpers>:<Zeit>` (Zeit höchstens 60 Sekunden alt, jede Signatur einmal verwendbar). Das Bedienfeld signiert nur nach einem Klick
in sich selbst und zeigt vorher, was es signiert (Repo, Art, Titel, Zahl der Dateien, markierte Dateien).

**Token speichern.** `POST /wamo/zugang/<dienst>` mit `{"token": "..."}` (höchstens 512 Byte), signiert, Drosselung 5 Versuche je 10 Minuten. Die Prüfung läuft vollständig vor dem
Speichern; jeder Fehler nennt nur die Art des Problems.

| Schritt | GitHub |
| --- | --- |
| Form | `ghp_` plus 36 Zeichen aus A-Z, a-z, 0-9 (klassisch) oder `github_pat_` plus 82 Zeichen aus A-Z, a-z, 0-9, `_` (fein-granular). `gho_`, `ghu_`, `ghs_`, `ghr_` mit eigenem Satz abgewiesen |
| Echtheit | `GET https://api.github.com/user` über den Domain-Proxy: 200 mit `login`, `id`, `type` `User`; 401 heißt ungültig; keine Weiterleitung |
| Rechte | klassisch: `X-OAuth-Scopes` (A1), Pflicht `repo` oder `public_repo`; abgewiesen nach D1: `delete_repo`, alle `admin:*`, `site_admin`, `delete:packages`, `write:packages`, `codespace`, `user`; `workflow` angenommen und genannt. Fein-granular: Rechte nicht abfragbar, das Bedienfeld nennt die nötigen (Contents lesen und schreiben, Pull requests lesen und schreiben, Metadata lesen) und rät von allen anderen ab |
| Ablauf | `GitHub-Authentication-Token-Expiration` (A2); nach D1 Pflicht, höchstens 366 Tage |
| Speichern | Chiffrat und Metadaten, `geaendert_von_geraet`, Ereignis `hinterlegt`; eine Änderung erscheint als Hinweis auf allen Geräten |
| Antwort | nur Metadaten: Art, Konto, Rechte, Ablauf, „endet auf …abcd“, geprüft am |

Es gibt keinen Weg, der den Wert zurückgibt. Das Bedienfeld leert das Feld nach dem Senden und speichert den Wert nicht.

### 3.4 Weg des Tokens (es erreicht die Sandbox nie)

1. **Eingabe:** im Bedienfeld (Ursprung 55444), TLS zu Caddy, Unix-Socket `/run/wamo-zugang/zugang.sock` mit `SO_PEERCRED` nur für Caddy und root. Caddy-Route mit
   `request_body max_size 16KB`, nur `GET` und `POST`, Ursprünge der Oberfläche; die Quelladresse nimmt der Dienst aus dem letzten Eintrag, den Caddy setzt, wie der Freigabe-Dienst.
2. **Ruhe:** nur Chiffrat (3.2).
3. **Benutzung:** `wamo-zugang` entschlüsselt für eine Handlung. REST-Aufrufe macht er selbst (kein Git), über den Domain-Proxy, mit Zertifikatsprüfung, ohne Weiterleitungen. Für
   Spiegel und Push startet er ein Transport-Kind in bwrap: kein Zugriff auf den Credentials-Ordner, die Datenbank und `/proc` des Dienstes, eigene PID- und IPC-Namensräume, nur
   der Spiegel- oder Push-Ordner dieses Auftrags beschreibbar, Netz nur zum Domain-Proxy. Das Token steht nur in seiner Umgebung (`GIT_CONFIG_COUNT` mit
   `http.https://github.com/.extraHeader`, dazu `GIT_TERMINAL_PROMPT=0`, leerer `credential.helper`, `http.followRedirects=false`, `protocol.allow=never`,
   `protocol.https.allow=always`, `core.hooksPath=/dev/null`, `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`), nie in argv, URL, Datei oder `.git/config`.
4. **Sandbox:** bekommt kein Dienst-Token, auch keines aus `geheim.env`. Der Dispatcher erzeugt je Lauf `wz1-<job>-<64 Hex>`, legt nur dessen SHA-256 in
   `/run/wamo-zugang-auftraege/<job>.json` ab (`v`, `job`, `hash`, `profil`, `repo`, `bis`) und gibt der Sandbox in vier Git-Einträgen `core.hooksPath`, `core.fsmonitor`,
   `url.http://127.0.0.1:18091/git/<job>/.insteadOf=https://github.com/` und `http.http://127.0.0.1:18091/.extraHeader` mit dem Auftragstoken. Landlock öffnet 18091 nur bei
   `github=persoenlich`, `wamo-egress.nft` bekommt `127.0.0.1:18091`. Die Datei wird am Laufende gelöscht, auch bei Abbruch und Signal.
5. **Git-Tor:** prüft je Anfrage Auftragstoken (Form, Datei ohne Link, Frist, Hash zeitkonstant), Startdatensatz (gleicher Auftrag, Repo, Kennung, Zustand aus 3.5.1, `stufe`), Pfad
   `/git/<job>/<owner>/<repo>.git/...` mit genau diesem Repo und eine Allowlist der Kopfzeilen; dann `git http-backend`.

#### 3.4.1 Besitz und Rechte

| Pfad | Besitzer, Gruppe, Modus | schreibt | liest |
| --- | --- | --- | --- |
| `/etc/wamo-zugang/kek`, `kek.alt`, `db.zugang` | root:root 0400 | Einrichtungsskript | nur `wamo-zugang` über `LoadCredential` |
| `/etc/wamo-zugang/notaus` | root:root 0644 | Skript | Dienst, Tor |
| `/run/wamo-zugang/zugang.sock` | `wamo-zugang`, 0660, Gruppe für Caddy | Dienst | Caddy, root (`SO_PEERCRED`) |
| `/srv/wamo-zugang/freigaben/<job>.json` (Kopie des Startdatensatzes) | `wamo-zugang:wamo-zugang-leser`, Ordner 2750, Dateien 0640 | Dienst | Tor, Prüfer, Dispatcher (Gruppe `wamo-zugang-leser`: `wamo`, `wamo-zugang-git`, `wamo-zugang-pruef`) |
| `/srv/wamo-zugang/spiegel/<job>.git` | `wamo-zugang:wamo-zugang-leser`, 2750, Dateien 0640 | Transport-Kind | Tor, Prüfer |
| `/run/wamo-zugang-auftraege/<job>.json` | tmpfiles `wamo:wamo-zugang-git` 2750, Dateien 0640 | Dispatcher | Tor |
| `/srv/wamo-zugang-git/ausgang/<job>.git` (Quarantäne) | `wamo-zugang-git`, 0700 | Tor | niemand sonst |
| `/srv/wamo-zugang-git/uebergabe/<job>.pack`, `.spitze` | `wamo-zugang-git:wamo-zugang-pruef`, 2750, Dateien 0640 | Tor | Prüfer |
| `/var/lib/wamo-zugang-pruef/<job>.git` | `wamo-zugang-pruef`, 0700 | Prüfer | niemand sonst |
| `/srv/wamo-zugang-pruef/kandidat/<job>.pack`, `bericht.json` | `wamo-zugang-pruef:wamo-zugang`, 2750, Dateien 0640 | Prüfer | Dienst, Transport-Kind |
| `/var/lib/wamo-zugang/push/<job>.git` | `wamo-zugang`, 0700 | Transport-Kind | Transport-Kind |

Jeder Zugriff auf Dateien eines anderen Benutzers mit `O_NOFOLLOW`, Prüfung von Besitzer und Modus am offenen Deskriptor, Größengrenzen; `safe.directory` nur für den einen Pfad des
Vorgangs.

### 3.5 Durchsetzung „nur Zweig und Pull Request“

Technisch in sechs Schichten, keine davon im Prompt:

1. **Kein Schreibweg aus der Sandbox.** Ohne Token erreicht die Sandbox GitHub nur anonym. Pushen geht nur ans Tor.
2. **Git-Tor.** Das Tor parst das Git-Protokoll nicht selbst. Es reicht an `git http-backend` weiter, mit Prozess-Konfiguration (`GIT_CONFIG_COUNT`, `GIT_CONFIG_NOSYSTEM=1`,
   `GIT_CONFIG_GLOBAL=/dev/null`): `core.hooksPath` auf einen root-eigenen Ordner, `receive.denyDeletes=true`, `receive.fsckObjects=true`, `receive.maxInputSize` 100 MB,
   `receive.advertisePushOptions=false`, `receive.certNonceSeed` leer (signierte Pushes scheitern), `receive.shallowUpdate=false`. **Einzige Instanz** für Ref-Regeln sind die
   root-eigenen Hooks `pre-receive` und `update`: genau eine Aktualisierung, Ziel genau `refs/heads/wamo/<job>`, neue ID nicht null, Zustand und `stufe` aus dem Startdatensatz.
   Die Quarantäne hat `objects/info/alternates` auf den Spiegel dieses Auftrags (A4). Nach jedem angenommenen Push legt das Tor eine Pack-Datei `basis..spitze` und die Spitze in
   `uebergabe/` ab. Nichts davon geht nach GitHub. Fuzz-Tests mit echtem git: `--signed`, `--atomic`, `-o`, `:ref`, `+ref`, mehrere Refspecs, gzip, Tags, andere Zweige.
3. **Prüfer.** Socket-aktiviert für einen Auftrag: neues Repo, Alternates **selbst** auf den Spiegel aus dem Startdatensatz, `index-pack --strict --fix-thin` mit der Pack-Datei,
   `merge-base --is-ancestor basis spitze`, dann **ein** neuer Commit: Tree der Spitze, Eltern `basis`, Autor die Person, Committer W.A.I.S. (3.6). Die Commits des Agenten werden nie
   übernommen. Auf dem fertigen Commit laufen `git diff-tree -r -z --no-renames` und die Regeln aus Folgepaket 1, 3.1.3 (als eigenes Modul, gleich in Prüfer und Push-Kind):
   gesperrt (`.git` in jeder Schreibweise, `.gitmodules`, `.github/`, `.claude/`, `.vscode/`, `.devcontainer/`, `.mcp.json`, Zeichen außerhalb der Allowlist, Kollisionen,
   Gerätenamen, Links mit absolutem Ziel, Gitlinks), sensibel (Lockfiles, Build- und Skriptdateien, `.env*`, `CLAUDE.md`, `AGENTS.md`, ausführbare und binäre Dateien), Geheimnissuche
   über Muster (`sk-ant-`, `ghp_`, `gho_`, `ghs_`, `github_pat_`, `wz1-`, `wh1-`, `AKIA`, PEM), Grenzen (300 Dateien, 20 MB, 5 MB je Datei), `git fsck --strict`. **CI-Prüfung:**
   Der Prüfer liest `.github/workflows/*` der Basis; ein Workflow mit Auslöser `push`, `pull_request` oder `pull_request_target`, der `wamo/**` nicht ausschließt und `secrets.` oder
   `environment:` enthält, macht den Kandidaten `gesperrt` mit Grund `ci_secrets`, außer das Repo hat `ci_ausnahme` (eigener signierter Schritt mit frischem Code, Satz zur CI). Ergebnis:
   Kandidaten-Pack und `bericht.json` (Commit, Tree, Liste, Gründe).
4. **Einreichen nur durch den Dienst nach dem signierten Klick.** `POST .../einreichen` mit der `kandidat_tree`, die das Bedienfeld gezeigt hat, und den bestätigten markierten
   Dateien, signiert. Der Dienst prüft Notaus, Schalter, Zustand `bereit` (atomar nach `einreichen_laeuft`), Tree gleich dem gespeicherten Kandidaten, Repo in
   `entwicklung_zugang_repos` (D2), Token gültig und nicht abgelaufen, dann `GET /repos/<repo>`: ID gleich der beim Start, nicht in `SELF_REPO_IDS`, ebenso die IDs von `parent`,
   `source` und `template_repository`, Standardzweig nicht `wamo/<job>`. Das Transport-Kind importiert den Kandidaten in ein frisches Repo, prüft Commit-ID und Tree gegen den Datensatz
   und **wiederholt `diff-tree` und die Pfad- und Geheimnisregeln** (zweite, unabhängige Prüfung, auch mit den exakten Werten der eigenen Tokens), fragt `git ls-remote` nach
   `refs/heads/wamo/<job>` (fehlt: pushen; gleicher Commit: entfällt; sonst `zweig_belegt`, nie überschreiben) und pusht genau `<commit>:refs/heads/wamo/<job>` ohne `+`, ohne
   `--force`, mit `--no-verify`. Danach öffnet der Dienst `POST /repos/<repo>/pulls` (`head` `wamo/<job>`, `base` der Standardzweig aus der Antwort, `maintainer_can_modify` aus,
   Entwurf wenn möglich). Als GitHub-Wege kennt der Dienst nur `GITHUB_WEGE` (`GET /user`, `GET /repos/{r}`, `GET /repos/{r}/pulls` mit `head`-Filter, `POST /repos/{r}/pulls`), das
   Kind nur `clone --mirror`, `ls-remote` und `push` mit dieser einen Refspec; ein Test sucht in den Modulen nach jedem anderen Weg.
5. **Selbstschutz und Forks.** Gesperrt sind das eigene Repo und Forks oder Vorlagen mit Ursprung im eigenen Repo (Name und ID). Andere Forks sind erlaubt; der Pull Request geht in
   den Fork selbst, nie ins Ursprungsprojekt. Die Repo-ID wird beim Start, nach dem Spiegeln (eine Umbenennung zwischen `GET` und Klon fällt so auf) und vor dem Push geprüft.
6. **Merge nie.** Kein Weg im Code, Text im Pull Request „Nicht gemergt, bitte prüfen“. Rulesets je Repo bleiben eine Empfehlung an die Personen.

#### 3.5.1 Zustände des Startdatensatzes

| Zustand | Bedeutung | Tor | Übergänge |
| --- | --- | --- | --- |
| `spiegel` | Spiegel wird angelegt | nichts | `frei`, `fehler` |
| `frei` | Läufe möglich, bis `bis` (Start plus 12 Stunden, deckt Freigaben und Abnahme-Runden) | lesen; schreiben nur bei `stufe=schreiben` | `bereit` (Prüfer hat einen Kandidaten), `verworfen`, `abgelaufen` |
| `bereit` | Kandidat gespeichert (`kandidat_commit`, `kandidat_tree`) | lesen; ein neuer Push setzt auf `frei` zurück, der Kandidat gilt nicht mehr | `einreichen_laeuft` (signierter Klick mit passendem Tree), `frei`, `verworfen`, `abgelaufen` |
| `einreichen_laeuft` | Push und Pull Request laufen | nichts | `eingereicht`, `bereit` (Fehler vor dem Push), `fehler`; nach 10 Minuten ohne Ende klärt `ls-remote` den Stand |
| `eingereicht` | Pull Request offen | nichts | Ende; Nacharbeit ist ein neuer Auftrag |
| `verworfen`, `abgelaufen`, `fehler` | Ende | nichts | Spiegel, Quarantäne und Kandidat werden gelöscht (Aufräumen nach höchstens 7 Tagen) |

Jeder Übergang als `update ... where job = $1 and status = $2 returning`, kein Lesen-dann-Schreiben. `stufe=lesen` (lesende Arten) sperrt das Schreiben im Tor und das Einreichen.

#### 3.5.2 Zulassung und Grenzen im Dienst

Der Dienst hat eine eigene Zulassungsliste `WAMO_ZUGANG_PROFILE` im Drop-in seiner Unit, die das Einrichtungsskript zusammen mit `WAMO_ENTWICKLUNG_PROFILE` schreibt. Grenzen je
Person: 6 Starts je Stunde und 20 je Tag, höchstens 3 Datensätze in `frei` oder `bereit` gleichzeitig, Spiegel höchstens 2 GB je Auftrag und 5 GB je Person, Übergabe höchstens
100 MB je Push und 500 MB je Auftrag, 10 Speicherversuche je Stunde.

### 3.6 Kennzeichnung von Commit und Pull Request

- **Zweig:** `wamo/<job>`.
- **Commit:** Autor die Person mit GitHub-Login und `<id>+<login>@users.noreply.github.com`, Committer `W.A.I.S.` mit `wais@wamocon.invalid`. Nachricht nur aus einer festen Vorlage:
  Titel aus dem signierten Start (`titel`, bereinigt, höchstens 72 Zeichen), eine feste Zeile `Erstellt von W.A.I.S. im Entwicklungsauftrag <job>`, am Ende die Trailer
  `WAIS-Auftrag: <job>`, `WAIS-Art: <art>`, `WAIS-Beauftragt-von: <login>`, `WAIS-Profil: <8 Hexzeichen>`. Kein Text des Agenten, keine Trailer aus der Sandbox.
- **Pull Request:** geöffnet mit dem Token der Person, also unter ihrem Namen. Titel `W.A.I.S.: <Titel>`, Text aus der Vorlage: Auftrag, Art, Person, vom Prüfer berechnete
  Übersicht, markierte Dateien, „Nicht gemergt, bitte prüfen.“ `@` entwertet, keine Links, kein Auftragstext außer dem Titel.
- **In W.A.I.S.:** Zeile `eingereicht` in `entwicklung_zugang_ereignisse` mit Gerät, Repo, Pull Request, Commit; Zeile `auftrag_einreichen` in `actions` durch den Kern.

### 3.7 Widerruf und Ablauf

| Fall | Verhalten |
| --- | --- |
| Person löscht das Token | Chiffrat sofort gelöscht, **alle** Datensätze der Person in `spiegel`, `frei`, `bereit` werden `verworfen`, das Tor prüft den Zustand je Anfrage, Spiegel und Quarantänen werden gelöscht. Das Bedienfeld verlinkt die Stelle zum Widerruf bei GitHub |
| Gerät widerrufen | `widerrufen_at`, Signaturen dieses Geräts gelten nicht mehr, Hinweis auf allen Geräten |
| Token läuft in 7 Tagen ab | Hinweis im Bedienfeld und beim Verbinden |
| Token abgelaufen oder 401 | Status `abgelaufen` oder `ungueltig`, alle offenen Datensätze `verworfen`. Ein täglicher Prüflauf (`GET /user`) findet widerrufene Tokens ohne Benutzung |
| Person verlässt die Firma | `scripts/wamo_nutzer.py austreten` löscht die Zeilen (Kaskade), der Admin bittet um den Widerruf bei GitHub |
| Notaus | `zugang-einrichten.sh notaus`: alle Routen außer Stand und Löschen antworten 503, das Tor weist alles ab, offene Datensätze `verworfen`. Bei Verdacht auf einen übernommenen Dienst widerrufen alle Personen ihre Tokens bei GitHub |
| Schlüsselwechsel | neuer `kek`, alter als `kek.alt`, Umschlüsseln mit `zugang-einrichten.sh umschluesseln` |

### 3.8 Audit

- **Dienst:** jede Handlung als Zeile in `entwicklung_zugang_ereignisse` mit Gerät, ohne Wert; Journal `logger -t wamo-zugang` nur Code, Dauer, Kürzel.
- **Verwendungsliste im Bedienfeld:** letzte 30 Tage der eigenen Person, direkt vom Dienst. Jede Handlung zeigt das Gerät mit Namen; Handlungen eines anderen Geräts und jede
  Geräteanmeldung sind deutlich hervorgehoben.
- **GitHub:** Zweig, Trailer, Pull Request (3.6). **Kern:** `actions` wie heute plus `auftrag_einreichen`.

### 3.9 Oberfläche und Bedienfeld

- **Bedienfeld** `https://<server>:55444/wamo/zugang/feld`: statische Seite des Dienstes ohne Abhängigkeiten, CSP `default-src 'self'; script-src 'self'; frame-ancestors <Ursprung der
  Oberfläche>`, kein Inhalt aus dem Kern. Als Rahmen in der Oberfläche eingebettet, `postMessage` nur mit geprüftem Ursprung und strenger Form (Kennungen als Hex). Es enthält die
  Eingabe der Tokens, die Gerätanmeldung, die Repo-Freischaltung, die Startbestätigung, die Änderungskarte mit Einreichen und Verwerfen sowie die Verwendungsliste.
- **Karte „Zugänge für Entwicklungsaufträge“** in den Einstellungen (nur ohne `labor_art` und mit `zugaenge: true` im Feld `betrieb`): rahmt das Bedienfeld ein.
- **Auftragskarte** (vom Kern): zeigt „mit deinem GitHub-Token“; der Start mit Token geschieht im Bedienfeld, erst nach dessen `ok` geht `auftrag_start` an den Kern.
- **Fehlertabelle** wie `ui/src/lib/aenderungenFreigabe.ts`: jeder Code des Dienstes hat einen Satz.

### 3.10 Verhalten ohne Token und bei Fehlern

| Fall | Verhalten |
| --- | --- |
| Kein GitHub-Token, Repo in `REPOS` | App-Weg wie heute |
| Kein GitHub-Token, Repo nicht in `REPOS` | Karte: „Für dieses Repo brauchst du ein eigenes GitHub-Token (Einstellungen, Zugänge)“; Arten ohne GitHub laufen |
| Kein angemeldetes Gerät | Bedienfeld führt durch die Anmeldung (ein Code) |
| Token abgelaufen oder ungültig | wie ohne Token, mit passendem Satz |
| Person ohne Claude-Zugang | unverändert (Hausmodelle, falls freigeschaltet); der persönliche GitHub-Weg geht mit beiden Zugangsarten |
| Dienst, Tor oder Prüfer aus | fail-closed: kein Start mit `persoenlich`, kein Einreichen; App-Weg läuft |
| Dispatcher 9 | Der Kern schickt `github` nur, wenn `ping` Version 10 und `persoenlich: true` meldet |
| Schalter aus | Karte unsichtbar, Kern schickt nie `persoenlich`, Dienst antwortet nur auf Stand und Löschen |

### 3.11 Vercel (nach dem 05.12., PZ-12)

Vercel-Tokens haben keinen Nur-Lese-Bereich (Befund 13). Ein Token im Dienst senkt den Schaden bei dessen Übernahme nicht, und vor dem Freeze brächte es nur eine Statusanzeige.
Deshalb folgt Vercel mit PZ-12: hinterlegen und prüfen wie GitHub (A5), nur `GET`-Wege in `VERCEL_WEGE` (Projekte, Deployments für `wamo/<job>`, Build-Logs), Anzeige der Vorschau
nach dem Einreichen, Lesewege für die Sandbox über das Tor. Nie `POST`, nie Deploy, nie `env`, nie Produktion; das Token kommt nie in die Sandbox. Die Vorschau baut die
Git-Integration von Vercel nach dem Push ohnehin selbst (A8).

### 3.12 Rückweg

1. **Schalter:** `WAMO_ZUGAENGE=aus` im Drop-in des Kerns, das Bedienfeld verschwindet aus der Oberfläche.
2. **Kern-Kanal:** Schlüssel `PERSOENLICH` aus `kernkanal.conf` entfernen (zuerst), dann Dispatcher 9 zurück.
3. **Dienste:** `zugang-rueckweg.sh` stoppt Dienst, Tor, Prüfer und Proxy, entfernt Caddy-Route (Sicherung `wamo-core.caddy.vorher`), Ausgangsregeln und Loopback-Port; mit
   `--entfernen` auch Benutzer, Ordner und Schlüssel.
4. **Datenbank:** `00NN_entwicklung_zugaenge.down.sql` löscht die Tabellen; die Personen widerrufen ihre Tokens bei GitHub.

## 4. Arbeitspakete

### 4.1 Pflichtumfang GitHub

Stränge: **A1**, **A2** und **A3** mit dem stärksten Modell (die neue Grenze), **B** und **C** mit dem Standardmodell. Jedes Paket ist ein Pull Request mit Tests (rot zuerst),
Review durch `ecc:security-reviewer` (A und B), `ecc:react-reviewer` (C), `ecc:database-reviewer` (PZ-1).

| Paket | Kurzbrief | Dateien (Auswahl) | Abnahme | h | hängt ab von | Strang |
| --- | --- | --- | --- | --- | --- | --- |
| PZ-0 | Vorprobe und Schnittstellenblatt: A1 bis A12, Formate von Startdatensatz, Auftragsdatei, Übergabe, Bericht, Signatur, Routen, Codes. **Admin, manuell:** Testrepo, Wegwerf-Tokens (fein und klassisch, Ablauf 7 Tage) | dieses Papier | jede Annahme mit Ergebnis | 5 | keins | A1 |
| PZ-1 | Migration 00NN mit Down und SQL-Test, Rolle `wamo_zugang` | `supabase/migrations/00NN_*`, `supabase/tests/00NN_*` | `wamo_core` liest kein `chiffrat` und keinen Schlüssel, schreibt nichts; andere Rollen nichts; zweiter Lauf bricht nicht ab | 6 | PZ-0 | C |
| PZ-2 | Regeln und Tresor ohne Netz: Formprüfung, Auswertung der GitHub-Antworten, D1, AES-GCM, Repo-Regeln mit IDs, Pfad-, Geheimnis- und CI-Regeln als ein Modul für Prüfer und Push-Kind, Signaturprüfung | `infra/sokrates2/zugang/zugang_regeln.py`, `zugang_tresor.py`, `zugang_signatur.py`, Tests `voice-core/test_zugang_*.py` | jede Regel mit Grenzfall, kein Wert in Fehlertexten | 10 | PZ-0 | A1 |
| PZ-3 | Zugangsdienst: Unix-Socket, JWT, aal2 und Frische, Geräte, Signaturen, Routen, Zulassung und Grenzen, Ereignisse, Auslieferung des Bedienfelds mit CSP; Unit mit Härtung, Benutzer, Credentials, Domain-Proxy, Ausgangsregel, Caddy-Route, `zugang-einrichten.sh`, `zugang-rueckweg.sh`, Rauchtest; optional Netzregel gegen `wamo-core` (A11) | `infra/sokrates2/zugang/wamo_zugang_dienst.py`, `wamo-zugang.service`, `wamo-zugang-proxy` (Instanz), `zugang-einrichten.sh`, `zugang-rueckweg.sh`, `zugang_rauchtest.py`, `wamo-caddy/kern/wamo-core.caddy` | Labor 403, ohne Signatur 403, Signatur wiederverwendet 403, Gerät ohne frischen Code 403, kein Weg gibt den Wert zurück, Peer fremd abgewiesen, Probelauf ohne root | 20 | PZ-1, PZ-2 | A1 |
| PZ-4 | Git-Tor: Loopback 18091, `http-backend`, Prozess-Konfiguration, root-eigene Hooks als einzige Instanz, Startdatensatz und Auftragsdatei, Übergabe-Pack, Grenzen; Unit ohne Internet; Fuzz-Tests mit echtem git | `infra/sokrates2/zugang/wamo_zugang_git.py`, `hooks/`, `wamo-zugang-git.service`, tmpfiles | alle Fälle aus 3.5 Schicht 2 abgewiesen; echter Klon und Push gegen ein Wegwerf-Repo | 16 | PZ-0 | A2 |
| PZ-5 | Prüfer: socket-aktiviert, Import mit eigenen Alternates, ein Commit, Regeln, CI-Prüfung, Bericht | `infra/sokrates2/zugang/wamo_zugang_pruef.py`, `wamo-zugang-pruef.socket`, `@.service` | feindliches Pack, fremde Alternates, Pfadtricks, Geheimnisse, CI mit Secrets ergeben `gesperrt`; kein Netz in der Unit | 16 | PZ-2, PZ-4 | A2 |
| PZ-6 | Transport-Kind und Zustände: bwrap-Aufruf, Spiegel beim Start, erneute Prüfung, `ls-remote`, Push, Pull Request, Idempotenz, Zustandsautomat, Aufräumen, Widerruf | `infra/sokrates2/zugang/zugang_transport.py`, Routen `start`, `aenderung`, `einreichen`, `verwerfen` | jeder Schritt aus 3.5 Schicht 4 und 3.5.1; Token nie in argv (Zähler); Refspec exakt; `zweig_belegt`; Absturz nach dem Push; Kind sieht weder Credentials noch Datenbank | 12 | PZ-3, PZ-5 | A3 |
| PZ-7 | Dispatcher 10 und Kern-Kanal: Feld `github` nur im Kern-Kanal, Prüfung des Startdatensatzes, `wz1-`, keine Dienst-Tokens aus `geheim.env` im persönlichen Weg, vier Git-Einträge, Schwärzung, Landlock 18091, `wamo-egress.nft`, `ping`; Regel 5 ohne `REPOS` bei `PERSOENLICH=an`; Wächter (`gh` gesperrt, `git push` nur `HEAD:wamo/<job>` ohne Karte); `disableClaudeAiConnectors: true` | `infra/sokrates2/wamo_job_dispatch.py`, `wamo_job_kernkanal.py`, `wamo-job.sh`, `wamo-egress.nft`, `voice-core/dev_guard.py`, `claude-code/managed-settings.json` | PC-Kanal und lokal weisen `github` ab; Umgebung der Sandbox ohne jedes Dienst-Token (Test); Vertragstest; ohne Datensatz kein Start | 13 | PZ-0 | B |
| PZ-8 | Kern: Schalter `WAMO_ZUGAENGE`, Feld `zugaenge` in `betrieb`, Weg je Auftrag, Systemtext für den persönlichen Weg, Sätze für neue Codes, `SCHRANKEN_VERSION = 4`, Labor nie, Schwärzung der neuen Muster | `voice-core/dev_agent.py`, `entwicklung_betrieb.py`, `boss.py` | Laborsitzung schickt nie `persoenlich`; jeder Code hat einen Satz | 8 | PZ-7 | B |
| PZ-9 | Oberfläche und Bedienfeld: Seite des Bedienfelds (WebCrypto, Signaturen, Eingabe, Karten, Verwendungsliste), Rahmen in den Einstellungen, Code holen ohne Weitergabe an den Kern, 90 Sekunden ohne Neuverbindung, Fehlertabelle | `infra/sokrates2/zugang/feld/`, `ui/src/lib/zugaenge.ts`, `ui/src/components/ZugaengeKarte.tsx` | Token und frisches Token nie über die Kern-Verbindung (Test), Schlüssel nicht exportierbar, Labor sieht nichts | 18 | PZ-0, PZ-3 (Routen) | C |
| PZ-10 | Sicherheitsreview des Codes (adversarial), Befunde CRITICAL und HIGH beheben, erneute Prüfung | alle | keine offenen CRITICAL und HIGH | 12 | PZ-2 bis PZ-9 | A1 |
| PZ-11 | Rollout: Migration dev, test, prod; Dienste, Caddy, Ausgangsregeln, Dispatcher 10, `PERSOENLICH`, Kern- und Oberflächen-Release; Rauchtest mit Testrepo und Wegwerf-Tokens; Rückweg-Probe; Zeile im Namensvertrag von CLAUDE.md, Abschnitt in `infra/sokrates2/README.md` | Server, Doku | Rauchtest grün, Rückweg geprobt, Schalter zuerst nur für das Admin-Profil | 10 | PZ-10 | A1, B |
| | **Summe Pflichtumfang GitHub** | | | **146** | | |

### 4.2 Reihenfolge und Zeitplan

Kritischer Pfad: PZ-0 (5) → PZ-4 (16) → PZ-5 (16) → PZ-6 (12) → PZ-10 (12) → PZ-11 (10) = **71 Stunden**. Parallel laufen A1 (PZ-2, PZ-3: 30), B (PZ-7, PZ-8: 21) und C
(PZ-1, PZ-9: 24).

**Plan B (empfohlen, D4).**

```text
Do 19.11. bis So 22.11.  PZ-0 bis PZ-9 in Zweigen, je Paket Review und Pull Request, kein Rollout
Freeze-Woche             PZ-10 (Review des Codes und Korrekturen) in Zweigen, Probelauf in einer Wegwerf-Umgebung ohne Eingriff am Server
Mo 07.12.                PZ-11: Rollout, Schalter nur für das Admin-Profil (Pilot, Testrepos, fein-granulares Token)
ab etwa 10.12.           Freigabe für alle zugelassenen Personen nach einer Pilotwoche ohne Befund; danach PZ-12 (Vercel)
```

**Plan A (nicht empfohlen).** Pilot nur für das Admin-Profil vor dem Freeze: dieselben Pakete bis Sonntag, PZ-10 auf die neue Grenze beschränkt (PZ-4, PZ-5, PZ-6, Bedienfeld),
Rollout am Sonntagabend nur dunkel (Schalter für das Admin-Profil, alle anderen aus). Das verlangt etwa 18 Stunden je Tag auf dem kritischen Pfad, lässt kein Korrekturfenster und
fällt mit dem Freeze zusammen; ein Fehler müsste in der Freeze-Woche mit dem Notaus statt mit einer Korrektur behandelt werden.

Kürzungsreihenfolge bei Zeitnot in beiden Plänen: nie die Schichten aus 3.5, der Weg aus 3.4 oder der Geräteschlüssel. Kürzbar sind die optionale Netzregel (A11), die
Verwendungsliste als einfache Liste ohne Hervorhebung und die Vorprobe der zweiten Instanz auf `wamo_test` (Rauchtest dann nur in prod mit dem Admin-Profil).

### 4.3 Nach dem 05.12.

| Paket | Kurzbrief | h |
| --- | --- | --- |
| PZ-12 | **Vercel:** hinterlegen und prüfen (A5), D1 für Vercel (Ablauf, Team-Bereich), Vorschau-Status nach dem Einreichen, Lesewege für Build-Logs über das Tor, `VERCEL_WEGE` nur `GET`; Domain-Proxy um `api.vercel.com` erweitert | 10 |
| PZ-13 | **Supabase-Proxy.** `sbp_`-Tokens gelten kontoweit (A13, Vorprobe), der Dienst wird damit ein Ort für alle Projekte der Person: Ablaufpflicht wie D1. Die Person wählt Projekte im Bedienfeld und markiert je Projekt „Produktion“. Für Nicht-Produktion: Proxy mit Allowlist der Management-Wege je Projekt-Ref, gesperrt API-Schlüssel, Secrets, Funktionen ausrollen, Löschen, Pausieren, Netz, Auth-Einstellungen; der MCP-Server `mcp-server-supabase` zeigt per Einstellung auf den Proxy (A14). **Produktion nie über die Management-API:** nur über eine eigene Datenbankrolle der Person mit `default_transaction_read_only`, ohne Rechte auf `vault`, `auth`, `pg_net` und Funktionen mit Nebenwirkung, deren Verbindung die Person im Bedienfeld hinterlegt; ein reines SELECT ist kein Schreibschutz (Befund 16). `DIENSTE` im Kern-Kanal bleibt ohne `supabase`, der persönliche Weg bekommt eine eigene Regel | 32 (davon 4 Vorprobe) |
| PZ-14 | **Konnektor-Ersatz** (4.4): ausgewählte entfernte MCP-Server über den Dienst mit den Tokens der Person (GitHub-MCP und Vercel-MCP nur lesend), Allowlist der Werkzeuge, kein claude.ai-Login in der Sandbox | 19 (davon 3 Vorprobe) |
| PZ-15 | Lesewege für die Sandbox über das Tor: Issues und Kommentare des Auftragsrepos nur `GET` | 6 |
| PZ-16 | optional: App-Weg auf denselben Dienst umstellen (ersetzt F1 und F2 aus Folgepaket 1 auch für die App, App-Schlüssel nicht mehr für `wamo` lesbar) | 20 |
| | **Summe nach dem 05.12.** | **67 ohne PZ-16, 87 mit** |

### 4.4 Konnektoren: was die Doku von Claude Code sagt

- „This token authenticates with your Claude subscription [...] It can only make model requests, so it can't establish Remote Control sessions or fetch claude.ai connectors. MCP
  servers you configure locally still work.“ ([Authentication, Generate a long-lived token](https://code.claude.com/docs/en/authentication))
- „Connectors from claude.ai are fetched only when your active authentication method is a claude.ai subscription login. They aren't loaded, even if you previously ran `/login`,
  when: [...] `CLAUDE_CODE_OAUTH_TOKEN` holds a token from `claude setup-token`, which can only make model requests“, ebenso nicht bei `ANTHROPIC_API_KEY`,
  `ANTHROPIC_AUTH_TOKEN` oder `apiKeyHelper` ([MCP, Use MCP servers from claude.ai](https://code.claude.com/docs/en/mcp)).
- Ausgangsziele: „Anthropic calls connector tools from its own infrastructure rather than from your runner. [...] that traffic goes through `api.anthropic.com`“ (für selbst betriebene
  Umgebungen, [Self-hosted environments, Connector traffic leaves your network](https://code.claude.com/docs/en/self-hosted-environments-deploy)). Für Terminal-Sitzungen nennt die Doku
  keine eigene Hostliste (Annahme: `api.anthropic.com` und claude.ai für das Erneuern der Anmeldung).
- Abschalten: `disableClaudeAiConnectors: true` oder `ENABLE_CLAUDEAI_MCP_SERVERS=false` ([MCP, Disable claude.ai connectors](https://code.claude.com/docs/en/mcp)).

**Folgerung.** Mit dem heutigen Weg (`claude setup-token`, API-Schlüssel oder Hausmodell über den Proxy) gibt es in einem kopflosen Lauf keine claude.ai-Konnektoren. Möglich wäre es
nur mit der vollen claude.ai-Anmeldung der Person in der Sandbox (`.credentials.json` mit Refresh-Token): ein voller Kontozugang mit allen Konnektoren der Person (auch Mail,
Kalender, Ablagen) in einer Umgebung mit offenem Port 443 und Prompt-Injection als Hauptgefahr. **Empfehlung: nicht so.** Stattdessen PZ-14 über den Zugangsdienst. Neue
Ausgangsziele bräuchte die Sandbox dafür keine, nur Loopback zum Dienst. Vorsorglich setzt PZ-7 `disableClaudeAiConnectors: true` in `managed-settings.json`.

### 4.5 Aufwand und Einschätzung

Pflichtumfang GitHub 146 Stunden, kritischer Pfad 71 Stunden. Von Donnerstag 8 Uhr bis Sonntagabend wären das etwa 18 Stunden je Tag auf dem kritischen Pfad, mit fünf parallelen
Strängen, Admin-Zeit für Tokens, Testrepo und Rollout und ohne Korrekturfenster nach dem Review des Codes. **Einschätzung: vor dem Freeze nicht realistisch in der abgesicherten Form.**
Realistisch ist Plan B: bis Sonntag gebaut und je Paket geprüft, in der Freeze-Woche das Review des Codes mit Korrekturen, Pilot ab dem 07.12. Nach dem 05.12. kommen 67 Stunden
(87 mit PZ-16) dazu. Der Freeze ist in keinem Plan gefährdet, weil alles standardmäßig aus ist und der App-Weg unverändert bleibt.

## 5. Zwingend vor dem Live-Gang

1. Kein persönliches Token in Sandbox, Dispatcher, Kern, Ursprung der Oberfläche, Datei, Protokoll, Datenbank (Klartext) oder einem Prozess, der Git-Daten verarbeitet, außer dem
   Transport-Kind des Vorgangs (3.4), mit Tests auf jeder Ebene.
2. Geräteschlüssel im Bedienfeld, Signatur jeder Handlung, Anmeldung je Gerät nur mit frischem Code, frisches Token nie an den Kern (3.3, 3.9).
3. Git-Tor ohne Token und Internet, Hooks als einzige Instanz, Fuzz-Tests (3.5 Schicht 2).
4. Prüfer ohne Netz und Geheimnisse, ein eigener Commit, Pfad-, Geheimnis- und CI-Regeln, zweite Prüfung im Push-Kind, feste Refspec, `GITHUB_WEGE` (3.5 Schichten 3 und 4).
5. Startdatensatz mit Zustandsautomat, Selbstschutz über Name und IDs, Zulassung und Grenzen im Dienst (3.5.1, 3.5.2).
6. Rechtetabelle umgesetzt und im Rauchtest geprüft (3.4.1).
7. Laborprofile, Erstanmeldung und aal2 im Dienst geprüft, Labor-Tests auf allen Ebenen.
8. Verwendungsliste vom Dienst, Widerruf mit Verwerfen aller offenen Datensätze, Ablauf vor jeder Benutzung (3.7, 3.8). Regeln nach D1.
9. Schalter standardmäßig aus, Rückweg geprobt, Rauchtest am Server, Review des Codes ohne offene CRITICAL und HIGH mit Korrekturfenster (PZ-10, PZ-11).

## 6. Entscheidungen der Ausbaustufe

Stand 18.11.2026: D1 ist mit C5 entschieden, D2 mit C6 (Lesen und Pull Requests in allen erreichbaren Repos außer dem eigenen). D3 und D4 sind durch Plan C für den Freeze ersetzt und werden vor dem Bau der Ausbaustufe nach dem 05.12. neu entschieden. Die Empfehlungen unten bleiben als Grundlage dafür.

| Nr. | Frage | Empfehlung |
| --- | --- | --- |
| D1 | Unter welchen Bedingungen werden klassische Tokens angenommen? | Nur mit Ablaufdatum, höchstens 366 Tage; abgewiesen mit `delete_repo`, allen `admin:*`, `site_admin`, `write:packages`, `delete:packages`, `codespace`, `user`; `workflow` erlaubt, weil `.github/` gesperrt ist. Das Bedienfeld empfiehlt fein-granulare Tokens. Für Vercel später dieselbe Regel mit höchstens 90 Tagen und Team-Bereich |
| D2 | In welche Repos darf eingereicht werden? | Lesen in jedem Repo, das das Token erreicht (außer dem eigenen Repo), Einreichen nur in Repos, die die Person im Bedienfeld signiert freischaltet. Repos mit CI und Secrets ohne Ausschluss von `wamo/**` sind gesperrt, bis die Person je Repo mit frischem Code eine Ausnahme bestätigt |
| D3 | Gerätebindung statt Code je Klick (Ergänzung zu E1)? | Ja: einmal je Gerät ein frischer Code, danach Einreichen ohne Code mit Signatur des Geräteschlüssels. E1 bleibt im Sinn erhalten (kein Code je Klick), der gekaperte Kern verliert aber den Zugriff auf die Tokens |
| D4 | Zeitplan (Abweichung von Z7) | Plan B: bis Sonntag bauen, in der Freeze-Woche Review und Korrekturen, Pilot für das Admin-Profil ab 07.12., danach alle; Vercel nach dem 05.12. Plan A (Pilot vor dem Freeze ohne Korrekturfenster) nur, wenn der Admin das Risiko ausdrücklich trägt |

## 7. Restrisiken

| Nr. | Restrisiko | Begründung | Sichtbar durch |
| --- | --- | --- | --- |
| R1 | Gekaperter Kern meldet im Fenster nach einem Code ein eigenes Gerät an | er bekäme bei einer Neuverbindung ein frisches Token | Hinweis auf allen Geräten, 90 Sekunden ohne Neuverbindung, optional Netzregel (A11) |
| R2 | Quelltext des Auftragsrepos fließt über 443 ab | Port 443 bleibt offen (Hauptpapier 4.6) | nicht |
| R3 | Code des Agenten läuft in CI und Vorschau mit Secrets nach bestätigter Ausnahme | Push auf `wamo/**` startet Workflows | Ausnahme je Repo mit Code, Ereignis |
| R4 | Übernahme des Zugangsdienstes trifft alle Tokens | ein Ort für alle Tokens | Ablaufpflicht, Notaus, Widerruf bei GitHub |
| R5 | Ausgebrochener Benutzer `wamo` liest Repos laufender, signierter Aufträge und schreibt in deren Quarantäne | die Auftragsdatei in `/run` ist für `wamo` schreibbar, der Startdatensatz gilt bis zu 12 Stunden | Ereignisse im Dienst, Prüfer und Klick vor jedem Push |
| R6 | Fehler in git im Transport-Kind trifft das eine Token des Vorgangs | das Kind braucht Token und Git-Daten zugleich | Ereignis, Widerruf |
| R7 | Fein-granulare Rechte sind nicht prüfbar | GitHub bietet keine Abfrage | Anleitung im Bedienfeld; die Wege des Dienstes sind fest |

## Anhang: Quellen

- Claude Code, Authentication: <https://code.claude.com/docs/en/authentication>
- Claude Code, MCP (Use MCP servers from claude.ai, Disable claude.ai connectors): <https://code.claude.com/docs/en/mcp>
- Claude Code, Self-hosted environments (Connector traffic leaves your network): <https://code.claude.com/docs/en/self-hosted-environments-deploy>
- Vercel REST API, get auth token metadata: <https://vercel.com/docs/rest-api/authentication/get-auth-token-metadata> (Wert `current` nur in einem Spiegel belegt, A5)
- GitHub, Scopes for OAuth apps (Kopfzeile `X-OAuth-Scopes`): <https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps>
