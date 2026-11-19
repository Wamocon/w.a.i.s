# Konfiguration: Umgebungsvariablen und Schalter

| | |
|---|---|
| Zweck | Listet die Umgebungsvariablen und Schalter von W.A.I.S., die der Code des Kerns, der Oberfläche, des Hosts, der Desktop-App und der Dienste liest: Name, Zweck, Standard, Ort der Einstellung. |
| Zielgruppe | Entwicklerinnen und Entwickler, Administratoren. |
| Dokumentart | Referenz |
| Stand | 19.11.2026, geprüft gegen Commit 497e3ce |
| Quellen | `voice-core/.env.example`, `voice-core/env_schalter.py`, `infra/sokrates2/wamo_core_env.py`, `infra/sokrates2/wamo-core@.service`, `host/wamo_host.py`, `desktop/main.js`, `ui/next.config.ts`, `geraete/wamo_geraete/konfig.py`, `labor-dienst/wamo_labor_dienst/konfig.py` |

Dieses Dokument nennt nur Namen, Zweck und Standardwerte aus dem Code. Werte von Geheimnissen stehen nirgends. Variablen, die Geheimnisse tragen, sind mit "Geheimnis" markiert. Zugangsdaten, Schlüsselpfade mit Inhalt und interne Adressen stehen hier bewusst nicht, auch wenn der Code Standardadressen enthält.

Betriebsskripte und Einrichtungsvariablen (Firewall, Remote Desktop, Release, Haus-Proxy, Probeläufe) stehen in [konfiguration-betrieb.md](konfiguration-betrieb.md).

## 1. Wo wird eingestellt?

| Ort | Bedeutung |
|---|---|
| `.env` | Lokaler Kern (Unterwegs): `.env` im Hauptordner des Repos oder `voice-core/.env`. Vorlage `voice-core/.env.example` mit allen gelesenen Einstellungen. Leere Zeilen heißen: Standard aus dem Code. Nie committen. |
| `wamo-core-env` | Kern auf Sokrates-2: Datei `/etc/wamo/core.env`, geschrieben nur über `wamo-core-env setzen` (Werte über stdin, nie über die Befehlszeile). Erlaubt sind nur Namen aus `ERLAUBT` und mit Präfix `WAMO_LLM_` in `infra/sokrates2/wamo_core_env.py`. Pflichtschlüssel: `SONIOX_API_KEY`, `SUPABASE_PUBLISHABLE_KEY`, `WAMO_DATABASE_URL`. Wirkt mit dem nächsten Kern-Release. |
| Unit | Feste Zeilen `Environment=` in `infra/sokrates2/wamo-core@.service` (`WAMO_BETRIEB`, `WAMO_CORE_UDS`, `WAMO_SLOT`, `WAMO_PC_HOST`, `WAMO_PC_REGISTER`, `WAMO_PC_SOCKET_WURZEL`, `WAMO_ENTWICKLUNG=aus`, `WAMO_LOG_LEVEL`, `WAMO_CHANNEL`, `WAMO_CA_FILE`, `PIPECAT_ALLOWED_ORIGINS`, `SUPABASE_URL`). `EnvironmentFile` hätte sonst Vorrang, deshalb lassen sich diese Namen nicht über `wamo-core-env` setzen. |
| Drop-in | `/etc/systemd/system/wamo-core@.service.d/wamo-entwicklung-buero.conf`, geschrieben nur von `wamo-job-kern-einrichten.sh schalter`. Enthält die Büro-Schalter der Entwicklungsaufträge. Kein Name `WAMO_ENTWICKLUNG*` steht in `ERLAUBT`. |
| Build | Zur Build-Zeit der Oberfläche (`NEXT_PUBLIC_*` und `WAMO_UI_STANDALONE`), stehen danach fest im Bundle und in der CSP. |
| Desktop | Umgebung der Desktop-App oder Datei am PC (siehe Abschnitt 11). |

Schalter lesen einheitlich über `voice-core/env_schalter.py` (`schalter_an`, `schalter_oder_none`, `zahl_im_bereich`): leer oder nicht gesetzt gilt der Standard, `aus`, `off`, `0`, `false`, `nein` schalten ab, ein unbekannter Wert behält den Standard und wird einmal gewarnt (Ausnahmen sind bei den Variablen genannt, etwa sicherheitsrelevante Schalter, die bei einem Tippfehler aus bleiben).

## 2. Kern: Betrieb, Sitzung, Protokoll

| Name | Zweck | Standard | Ort | Quelle |
|---|---|---|---|---|
| `WAMO_BETRIEB` | Betriebsart: `buero` (Kern als Dienst auf Sokrates-2) oder sonst `lokal` | `lokal` | Unit | `voice-core/bot.py` |
| `WAMO_CORE_UDS` | Unix-Socket statt TCP, absoluter Pfad ohne `..`, Ordner muss dem Dienstbenutzer gehören und für andere gesperrt sein | leer (TCP) | Unit | `voice-core/kern_dienst.py` |
| `WAMO_SLOT` | Name der Kern-Instanz (`a` oder `b`), schaltet die Ablöse-Brücke zwischen Instanzen ein | leer | Unit | `voice-core/sitzungen_bruecke.py` |
| `WAMO_SITZUNGEN_DIR` | Ordner für die Marken der Ablöse-Brücke | Konstante `ORDNER_STANDARD` | Standard im Code | `voice-core/sitzungen_bruecke.py` |
| `WAMO_SITZUNG_EINZELN` | eine Sitzung je Profil, eine neue löst die laufende ab | an | `.env`, `wamo-core-env` | `voice-core/sitzungen.py` |
| `WAMO_MAX_SITZUNG_MIN` | Höchstdauer einer Sitzung in Minuten (das Profil wird jede Minute neu geprüft) | 120 | `.env`, `wamo-core-env` | `voice-core/bot.py` |
| `WAMO_LOG_LEVEL` | Log-Stufe; INFO enthält keine Gesprächsinhalte, DEBUG schon | INFO | Unit, `.env` | `voice-core/bot.py` |
| `WAMO_CHANNEL` | Kanal, der in der Sitzung gespeichert wird | `web` (Unit: `buero`) | Unit, `.env` | `voice-core/bot.py` |
| `WAMO_CITY`, `WAMO_TIMEZONE` | Ort für die Websuche, Zeitzone | `Eschborn`, `Europe/Berlin` | `.env`, `wamo-core-env` | `voice-core/tools.py`, `voice-core/memory.py` |
| `WAMO_GREETING` | Begrüßung beim Verbinden, `{name}` wird ersetzt, leer schaltet ab | Konstante `DEFAULT_GREETING` | `.env`, `wamo-core-env` | `voice-core/bot.py` |
| `WAMO_AUSGABE_SCHWELLE` | Werkzeugausgaben ab so vielen Zeichen kürzen, 0 schaltet das Kürzen ab | 3000 | `.env`, `wamo-core-env` | `voice-core/ausgaben_kuerzen.py` |
| `WAMO_CACHE_VORWAERMEN` | Prompt-Cache von Claude beim Sitzungsstart vorwärmen | an | `wamo-core-env` | `voice-core/cache_waerme.py` |
| `WAMO_LATENZ_LOG` | Latenz je Gesprächszug ins Log, ohne Inhalte | aus | `.env`, `wamo-core-env` | `voice-core/latenz.py` |
| `PIPECAT_ALLOWED_ORIGINS` | Seiten, von denen Sitzungen starten dürfen, kommagetrennt | `http://localhost:3000,http://127.0.0.1:3000` | Unit, `.env` | `voice-core/bot.py` |
| `MIN_INTERRUPT_WORDS` | Wörter ohne Rückmeldelaute, ab denen unterbrochen wird | 1 | `.env`, `wamo-core-env` | `voice-core/bot.py` |
| `LEARN_EVERY_USER_TURNS` | nach so vielen neuen Sätzen lernt W.A.I.S. im laufenden Gespräch | 4 | `.env`, `wamo-core-env` | `voice-core/.env.example` |
| `SUMMARY_TRIGGER_TOKENS`, `SUMMARY_TARGET_TOKENS` | Zusammenfassung langer Gespräche ab so vielen Tokens, Ziel danach | 60000 und 25000 | `.env`, `wamo-core-env` | `voice-core/.env.example` |
| `WAMO_BOSS_PROBE` | Antwortzeit-Probe des Boss vor der Modellwahl | an | `.env` | `voice-core/boss.py` |

## 3. Kern: Gesprächsverhalten und Persona

Alle als Schalter (`an` oder `aus`), Quelle `voice-core/env_schalter.py` und das genannte Modul. Ort: `.env` oder `wamo-core-env`.

| Name | Zweck | Standard |
|---|---|---|
| `WAMO_ECHO_FILTER`, `WAMO_ECHO_MODUS` | Echo der eigenen Stimme erkennen, bei Echo unterbricht nur ein Stoppwort (der Modus wirkt nur mit dem Filter) | an, an |
| `WAMO_STOPP_GRENZE` | Unterbrechung an der nächsten hörbaren Wortgrenze statt nach bis zu drei weiteren Wörtern | an |
| `WAMO_DUCKEN` | Stimme sofort leiser, sobald die Person spricht | an |
| `WAMO_RUECKMELDUNG`, `WAMO_RUECKMELDUNG_WERKZEUG` | erweiterte Erkennung kurzer Zustimmung, Rückmeldelaut bei laufendem Werkzeug startet keinen Zug | an, an |
| `WAMO_INNEHALTEN`, `WAMO_INNEHALTEN_WEITER_SECS`, `WAMO_INNEHALTEN_MAX_SECS` | Innehalten statt Abbrechen bei einem einzelnen Wort, Stille bis zum Weitersprechen, Höchstdauer | an, 0,7 s, 2,5 s (höchstens 3,5) |
| `WAMO_VAD_STOP_SECS` | Stille für das Ende des Redebeitrags (Voice Activity Detection) | 0,2 |
| `SMART_TURN_STOP_SECS`, `TURN_INCOMPLETE_SHORT_SECS`, `TURN_INCOMPLETE_LONG_SECS` | Satzende-Erkennung in Sekunden | 1,0, 1,5, 3,0 |
| `SOFT_INTERRUPT_MAX_WORDS`, `SOFT_INTERRUPT_LAG_SECS` | weiche Unterbrechung: höchstens so viele Wörter nach einem Einwurf, Ton-Verzug | 3, 0,5 |
| `WAMO_WARTESATZ`, `WAMO_WARTESATZ_SECS` | kurzer Satz, wenn ein Werkzeug lange dauert, Schwelle in Sekunden | aus (`standard=False` in `wartesatz.py`), Schwelle 0,9 s |
| `WAMO_WARTESATZ_MODELL`, `WAMO_WARTESATZ_MODELL_SECS` | kurzer Satz, wenn das Modell zu lange kein Zeichen liefert, Schwelle | aus, 2,5 s |
| `WAMO_FUELLWOERTER`, `WAMO_FUELLWORT_SECS` | vorab aufgenommenes "Moment." bei Werkzeugen, Verzögerung | an, 0,4 s |
| `WAMO_MHM` | Rückmeldelaut "Mhm", wenn das Modell den Satz für unfertig hält | aus |
| `WAMO_JA_WAECHTER` | "Ja" auf eine Rückfrage führt aus, statt erneut zu fragen | an |
| `WAMO_ABBRUCH_HINWEIS`, `WAMO_WERKZEUG_DOPPELT` | abgebrochene Werkzeuge im Verlauf erklären, doppelte Öffnen-Aktion im selben Zug verhindern | an |
| `WAMO_MARKER_FALLBACK` | fehlt der Satzende-Marker, Text sofort freigeben | an |
| `WAMO_LERNEN_OHNE_MOMENT` | Lernen ohne Momentaufnahmen und Aufgabenstände | an |
| `WAMO_LERNEN_HAUS_SECS` | so lange darf ein Hausmodell für "lernen" brauchen, bevor Claude übernimmt (0 = aus) | 15 |
| `WAMO_PAUSEN_PROMPT` | Texte nach einer Pause ohne Floskel "Ich bin noch da" | an |
| `WAMO_TTS_VOR_WERKZEUG` | Text vor einem Werkzeugaufruf sofort sprechen | an |
| `WAMO_TTS_SATZLEERZEICHEN` | Leerzeichen am Satzende, damit Soniox das Satzzeichen nicht vorliest | aus |
| `WAMO_TTS_START_ZEICHEN` | Zeichen ohne Leerraum, ab denen der erste Text an Soniox geht (0 = aus) | Standard in `soniox_tts.py` |
| `WAMO_PERSONA_RUECKFRAGEN` | Persona: Rückfragen begrenzen | an |
| `WAMO_PERSONA_PC_ORDNER` | Persona: Ordner des PCs nie raten | aus |
| `WAMO_PERSONA_BROWSER`, `WAMO_PERSONA_TAB` | Persona: Browserinhalte zuerst lesen, Seiten im offenen Tab laden | an, an |
| `WAMO_PERSONA_GESPRAECH` | Persona: Gesprächsführung | aus (bis zur Messung) |
| `WAMO_PERSONA_NATUERLICH` | Persona: natürliche Sprechweise | an |
| `WAMO_PERSONA_ABNAHME` | Persona: Entwicklungsaufträge mit prüfbarem Ziel in Runden | an |

## 4. Kern: Stimme (Stimmabdruck)

Wirken nur für Profile mit eingelerntem Abdruck, nie für Laborprofile (`voice-core/stimme_gate.py`, `stimme_waechter.py`). Im Standardmodus `beobachten` sperrt die Stimme nichts, die Regeln für Verwerfen, Nur-eigen und Unterbrechen wirken nur im Modus `streng`. Pro Person gibt es seit Migration 0029 einen Abdruck je Mikrofon (höchstens drei), das Urteil nimmt den besten Wert. Ort: `.env` oder `wamo-core-env`, nie in `AUS_ENV` von `scripts/wamo_kern_sokrates2.py` laut `CLAUDE.md`.

| Name | Zweck | Standard |
|---|---|---|
| `WAMO_STIMME_PRUEFUNG` | Modus `aus`, `beobachten` (messen, anzeigen, loggen, nichts sperren) oder `streng` (nur auf ausdrücklichen Wunsch: verwirft fremde Äußerungen, sperrt Werkzeuge). Ein unbekannter Wert wird einmal gewarnt und gilt als Standard. | `beobachten` (Konstante `STANDARD_MODUS` in `stimme_gate.py`; der Docstring von `pruefmodus` spricht noch von `streng`) |
| `WAMO_STIMME_EIGEN_MIN_KURZ`, `WAMO_STIMME_EIGEN_MIN_LANG` | Schwelle (Kosinus) für "eigen" bis 1,5 s und ab 3 s Sprache, dazwischen linear | 0,35 und 0,45 |
| `WAMO_STIMME_EIGEN_MIN` | alte einheitliche Schwelle, gilt nur, wo KURZ oder LANG leer sind | nicht gesetzt |
| `WAMO_STIMME_FREMD_MAX` | bis zu diesem Wert gilt eine Äußerung als fremd | 0,3 |
| `WAMO_STIMME_MIN_SECS` | so viel reine Sprache braucht eine Äußerung für ein Urteil | 1 |
| `WAMO_STIMME_VERTRAUEN_SECS`, `WAMO_STIMME_KURZ_VERTRAUEN_SECS` | so lange gilt "eigen" für Folgesätze, kürzer nach nur kurzen Äußerungen | 120 s, 15 s |
| `WAMO_STIMME_KURZ_ERBEN_SECS` | Äußerung unter der Mindestlänge erbt das Urteil eigen (0 = aus) | 60 |
| `WAMO_STIMME_NUR_EIGEN` | im Modus streng erreicht nur die eigene Stimme das Modell | an |
| `WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN` | während W.A.I.S. spricht, unterbricht nur die eigene Stimme | an |
| `WAMO_STIMME_VERWERFEN_MAX`, `WAMO_STIMME_VERWERFEN_MIN_SECS` | nur mit `WAMO_STIMME_NUR_EIGEN=aus`: unklare Äußerungen unter diesem Wert verwerfen, Mindestsprache | 0,4, 0 |
| `WAMO_STIMME_MODELL` | Pfad der Modelldatei (TitaNet-Large als ONNX) | Cache-Ordner des Dienstes |
| `WAMO_STIMME_SCHATTEN` | zweites Sprechermodell (WeSpeaker ResNet34) im Schattenbetrieb, entscheidet nie | aus |

## 5. Kern: Modelle, Sprachdienste, Suche

| Name | Zweck | Standard | Ort | Quelle |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | Claude-Schlüssel (Geheimnis); im Kern nur für das in `WAMO_CLAUDE_SCHLUESSEL_PROFIL` genannte Profil | leer | `.env`, `wamo-core-env` | `voice-core/modellzugang.py` |
| `ANTHROPIC_WORKSPACE_ID` | Workspace bei Organisationsschlüsseln ohne Workspace-Bindung | leer | `.env`, `wamo-core-env` | `voice-core/modellzugang.py` |
| `WAMO_CLAUDE_SCHLUESSEL_PROFIL` | `user_id` des einen Profils, dem der Schlüssel des Kerns gehört | leer | `wamo-core-env` | `voice-core/modellzugang.py` |
| `WAMO_SCHLUESSEL_KEK`, `WAMO_SCHLUESSEL_KEK_ALT` | Hauptschlüssel für die Verschlüsselung der Schlüssel und Tokens je Profil (Geheimnis), der alte nur zum Entschlüsseln | leer (ohne: nur Hausmodelle) | `wamo-core-env` | `voice-core/schluessel.py` |
| `CLAUDE_MODEL_FAST`, `SEARCH_MODEL`, `VISION_MODEL` | Gesprächsmodell, Modell der Websuche, Bildmodell | Haiku, Haiku, Sonnet (laut `.env.example`) | `.env`, `wamo-core-env` | `voice-core/.env.example` |
| `LITELLM_BASE_URL`, `LITELLM_API_KEY` | Gateway für Hausmodelle, Schlüssel ist ein Geheimnis. Nur über das Gateway, nie direkt an Knoten | leer | `.env`, `wamo-core-env` | `voice-core/llm_anbieter.py` |
| `WAMO_LLM_ANBIETER`, `WAMO_LLM_MODELL` | Anbieter (`claude` oder `litellm`) und Modell für das Gespräch | `claude` | `.env`, `wamo-core-env` (Präfix `WAMO_LLM_`) | `voice-core/llm_anbieter.py` |
| `WAMO_LLM_LERNEN`, `WAMO_LLM_LERNEN_MODELL` | dasselbe für das Lernen | wie Gespräch | wie oben | `voice-core/llm_anbieter.py` |
| `WAMO_LLM_VISION`, `WAMO_LLM_VISION_MODELL` | dasselbe für Bildschirm ansehen und klicken | Claude (`VISION_MODEL`) | wie oben | `voice-core/llm_anbieter.py` |
| `WAMO_LLM_ZUSAMMENFASSUNG`, `WAMO_LLM_ZUSAMMENFASSUNG_MODELL` | dasselbe für die Zusammenfassung | wie Gespräch | wie oben | `voice-core/llm_anbieter.py` |
| `WAMO_LLM_RUECKFALL` | Rückfall auf Claude, wenn LiteLLM nicht nutzbar ist: leer oder `claude` für alle Bausteine, `aus`, oder Liste | leer | wie oben | `voice-core/llm_anbieter.py` |
| `WAMO_LLM_EXTRA` | zusätzliche Parameter je LiteLLM-Anfrage als JSON-Objekt | leer | wie oben | `voice-core/llm_anbieter.py` |
| `WAMO_LLM_AUSBLENDEN` | Wortteile, deren Modellnamen aus Listen und Ausgaben ausgeblendet werden (nur lokale `.env`) | leer | `.env` | `voice-core/llm_anbieter.py` |
| `WAMO_LITELLM_EXTRA` | steht in `ERLAUBT` von `wamo_core_env.py`, im Kern wird er nicht gelesen (der Code liest `WAMO_LLM_EXTRA`) | nicht belegt | `wamo-core-env` | `infra/sokrates2/wamo_core_env.py` |
| `SONIOX_API_KEY` | Spracherkennung und Sprachausgabe (Geheimnis, Pflicht) | leer | `.env`, `wamo-core-env` | `voice-core/bot.py` |
| `SONIOX_STT_URL`, `SONIOX_TTS_URL` | Endpunkte (EU-Spracherkennung, Soniox-Sprachausgabe) | Konstanten in `bot.py` | `.env`, `wamo-core-env` | `voice-core/bot.py` |
| `SONIOX_VOICE`, `SONIOX_TERMS` | Stimme, Fachbegriffe für die Spracherkennung (leer schaltet ab) | Konstanten in `bot.py` | `.env`, `wamo-core-env` | `voice-core/bot.py` |
| `SONIOX_SPEED`, `SONIOX_REDUCE_SILENCE` | Tempo und Pausen der Stimme | Soniox-Standard | `.env`, `wamo-core-env` | `voice-core/bot.py` |
| `WAMO_STT_ANBIETER`, `WAMO_TTS_ANBIETER` | Übersteuerung für alle Sitzungen: `soniox` oder `haus`, leer heißt Wahl des Profils | leer | `wamo-core-env` (nur Server) | `voice-core/sprache_anbieter.py` |
| `WAMO_STT_HAUS_MODELL`, `WAMO_TTS_HAUS_MODELL`, `WAMO_TTS_HAUS_STIMME` | Gateway-Modelle und Stimme für Hören und Sprechen im Haus | leer | `wamo-core-env` | `voice-core/sprache_anbieter.py` |
| `WAMO_TTS_HAUS_STREAM` | gestreamte Sprachausgabe über die Durchreiche des Gateways | aus | `wamo-core-env` | `voice-core/sprache_anbieter.py` |
| `WAMO_SUCHE` | `anthropic` (Claude-Websuche) oder `searxng` | `anthropic` | `.env`, `wamo-core-env` | `voice-core/suche.py` |
| `WAMO_SEARXNG_URL` | Adresse der SearXNG-Instanz, Pflicht bei `WAMO_SUCHE=searxng` | leer | `.env`, `wamo-core-env` | `voice-core/suche.py` |

## 6. Kern: Anmeldung und Datenbank

| Name | Zweck | Standard | Quelle |
|---|---|---|---|
| `SUPABASE_URL` | Adresse des Supabase-Stacks, nur `https://` (http nur über Loopback), sonst lehnt der Kern jede Anmeldung ab | leer (Unit setzt sie) | `voice-core/auth_gate.py` |
| `SUPABASE_PUBLISHABLE_KEY` | öffentlicher Schlüssel für den HS256-Rückfall der Token-Prüfung und den Passwortwechsel | leer | `voice-core/auth_gate.py` |
| `WAMO_AUTH_ISSUER` | nur setzen, wenn der Aussteller der Tokens nicht `SUPABASE_URL/auth/v1` ist | leer | `voice-core/auth_gate.py` |
| `WAMO_CA_FILE` | öffentliches Root-Zertifikat der WAMO-CA, gilt nur für Verbindungen zum WAMO-Stack | leer | `voice-core/wamo_tls.py` |
| `WAMO_GOTRUE_INTERN_URL` | Ziel für den Wechsel des Startpassworts (nur Loopback-http oder https mit dem Host aus `SUPABASE_URL`) | Loopback-Adresse des Stacks | `voice-core/erstanmeldung_api.py` |
| `WAMO_ANMELDUNG_MAX_STUNDEN` | Höchstalter der Anmeldung in Stunden ab Passwort und Code (größer 0, höchstens 720) | 168 | `voice-core/auth_gate.py` |
| `WAMO_DATABASE_URL` | Postgres als Rolle `wamo_core` (Geheimnis, enthält Zugangsdaten); ohne sie ist das Gedächtnis aus und die Anmeldung gesperrt | leer | `voice-core/memory.py` |
| `WAMO_ADMIN_DATABASE_URL` | Postgres als Rolle `wamo_admin`, nur `wamo_admin.py` (Geheimnis) | leer | `voice-core/memory.py` |
| `WAMO_DB_SCHEMA` | `wamo_dev`, `wamo_test` oder `wamo_prod` | `wamo_dev` | `voice-core/memory.py` |

## 7. Kern: PC-Steuerung, Geräte, Fernzugriff

| Name | Zweck | Standard | Ort | Quelle |
|---|---|---|---|---|
| `WAMO_PC_HOST` | `off` schaltet die PC-Werkzeuge ganz ab | `on` | Unit, `.env` | `voice-core/pc_host.py` |
| `WAMO_PC_HOST_TOKEN` | Bearer-Token des Hosts im alten Tunnelweg (Geheimnis) | leer | `wamo-core-env` | `voice-core/pc_host.py` |
| `WAMO_PC_HOST_FREIGABE` | zweites Geheimnis für Freigaben kritischer PC-Aktionen (Geheimnis). Lokal erzeugt der Kern es selbst. | leer | `wamo-core-env` | `voice-core/pc_host.py` |
| `WAMO_PC_HOST_SOCKET`, `WAMO_PC_HOST_PROFILE` | Socket des alten Tunnels, Bindung des PCs an genau eine `user_id` | leer | `wamo-core-env`, Unit | `voice-core/pc_host.py` |
| `WAMO_PC_REGISTER` | Tunnel je Gerät: die Sitzung bekommt nur den eigenen Laptop aus dem Register | `aus` (Unit: `an`) | Unit | `voice-core/pc_geraet.py` |
| `WAMO_PC_SOCKET_WURZEL` | Wurzelordner der Sockets je Laptop | Konstante `WURZEL_STANDARD` | Unit | `voice-core/pc_geraet.py` |
| `WAMO_PC_SSH_HOST`, `WAMO_PC_SSH_HOSTKEY_DATEI` | Ziel und Hostschlüsseldatei, die der Kern bei der Gerätebindung an die Desktop-App meldet | Konstanten in `geraet_api.py` | Standard im Code, kein Eintrag in `ERLAUBT` | `voice-core/geraet_api.py` |
| `WAMO_PC_MITGLIEDER_PROFILE` | Liste von `user_id` der Mitglieder mit PC-Steuerung, leer heißt niemand, Laborprofile nie | leer | `wamo-core-env` | `voice-core/rechte.py` |
| `WAMO_PC_MITGLIEDER` | alter Schalter, wirkt nicht mehr | nicht belegt | nicht belegt | `voice-core/rechte.py` |
| `WAMO_GERAETE`, `WAMO_GERAETE_SOCKET`, `WAMO_GERAETE_BENUTZER` | Gerätedienst im Kern an oder aus, Socket, erwarteter Benutzer des Dienstes | an, Konstanten | Standard im Code, kein Eintrag in `ERLAUBT` | `voice-core/geraete_client.py` |
| `WAMO_GERAETE_REGISTER` | mit Wert `pflicht` verlangt der Kern das Geräteregister | leer | Standard im Code, kein Eintrag in `ERLAUBT` | `voice-core/geraete_werkzeuge.py` |
| `WAMO_RD_AKTIV` | Fernzugriff auf die Sparks im Kern einschalten (nur Admins) | `nein` | Drop-in `wamo-rd.conf`, geschrieben von `wamo-rd-einrichten.sh kern` | `voice-core/rd_api.py` |
| `WAMO_RD_SOCKET`, `WAMO_RD_ZIELE`, `WAMO_RD_ENV`, `WAMO_RD_KEY`, `WAMO_RD_URL` | Socket, Zieldatei, Umgebungsdatei, Schlüsseldatei und Adresse des Gateways (Pfade und Adresse mit Standard im Code) | Konstanten in `rd_api.py` | Standard im Code, kein Eintrag in `ERLAUBT` | `voice-core/rd_api.py` |
| `WAMO_RD_ANMELDUNG_MAX_MIN` | Höchstalter des Codes der Anmeldung nur für den Fernzugriff in Minuten (1 bis 43200). Leer oder 0 heißt aus, jeder andere Wert gilt als strengste Stufe. | aus | `wamo-core-env` | `voice-core/rd_api.py`, `infra/sokrates2/wamo_core_env.py` |
| `WAMO_RELEASE_SOCKET` | Socket des Release-Dienstes | Konstante `SOCKET_STANDARD` | Standard im Code, kein Eintrag in `ERLAUBT` | `voice-core/release_client.py` |

## 8. Entwicklungsaufträge

| Name | Zweck | Standard | Ort | Quelle |
|---|---|---|---|---|
| `WAMO_ENTWICKLUNG` | Entwicklungsaufträge an Claude Code, nur außerhalb des Büros; im Büro zählt er nicht | `aus` | `.env`, Unit (`aus`) | `voice-core/dev_agent.py` |
| `WAMO_ENTWICKLUNG_ORT` | `sokrates2` (Sandbox als Benutzer `wamo`) oder `lokal` | `sokrates2` | `.env`, Drop-in | `voice-core/dev_agent.py` |
| `WAMO_ENTWICKLUNG_LOKAL_BESTAETIGT` | Wert `ja` zusätzlich für Ort `lokal` (ohne Abschottung, Warnung im Log) | leer | `.env` | `voice-core/dev_agent.py` |
| `WAMO_ENTWICKLUNG_SSH_ZIEL`, `_SSH_SCHLUESSEL`, `_SSH_KNOWN_HOSTS` | SSH-Weg zum Dispatcher: Ziel, Schlüsseldatei, `known_hosts` | Konstanten in `dev_agent_weg.py` | `.env` | `voice-core/dev_agent_weg.py` |
| `WAMO_ENTWICKLUNG_SERVERZUGANG_PROFIL` | `user_id`, die ohne eigenen Zugang den Zugang des Servers nutzen darf; leer heißt das Profil aus `WAMO_CLAUDE_SCHLUESSEL_PROFIL` | leer | `.env` | `voice-core/dev_agent.py` |
| `WAMO_ENTWICKLUNG_MODELL` | Modell für Claude Code im Auftrag | leer | `.env` | `voice-core/dev_agent.py` |
| `WAMO_PROJECTS_DIR` | nur lokal: Ordner für Projekte, darf das W.A.I.S.-Repo nicht enthalten | Benutzerordner `Projekte` | `.env` | `voice-core/dev_agent.py` |
| `WAMO_JOB_ENV_PASSTHROUGH` | weitere Namen, die Claude Code erben darf (Allowlist), kommagetrennt | leer | `.env` | `voice-core/dev_agent_regeln.py` |
| `DEV_JOB_TIMEOUT_SECS` | Zeitlimit je Auftrag in Sekunden | 1800 | `.env` | `voice-core/.env.example` |
| `WAMO_ABNAHME_BEFEHLE` | Befehlskriterien der Abnahme; nur bei Ort `lokal`, im Büro zusätzlich `WAMO_ENTWICKLUNG_BEFEHLE_BUERO=an` | aus | `.env`, `wamo-core-env` | `voice-core/abnahme.py` |
| `WAMO_ENTWICKLUNG_BUERO` | Büro-Schalter (`an` oder `aus`) | aus | Drop-in | `voice-core/entwicklung_betrieb.py` |
| `WAMO_ENTWICKLUNG_PROFILE` | `user_id` der Profile mit Zulassung im Büro (Pflicht) | leer | Drop-in | `voice-core/entwicklung_betrieb.py` |
| `WAMO_ENTWICKLUNG_KOSTEN_AUFTRAG_USD`, `WAMO_ENTWICKLUNG_KOSTEN_TAG_USD` | Pflicht-Kostengrenzen je Auftrag und je Tag und Profil in USD, fehlend heißt aus | fehlend | Drop-in | `voice-core/entwicklung_betrieb.py` |
| `WAMO_ENTWICKLUNG_BEFEHLE_BUERO` | Befehlskriterien im Büro | aus | Drop-in | `voice-core/entwicklung_betrieb.py` |
| `WAMO_ENTWICKLUNG_HAUS` | Hausmodelle für Entwicklungsaufträge (nur Büro) | aus | Drop-in | `voice-core/entwicklung_betrieb.py` |
| `WAMO_ENTWICKLUNG_MITGLIEDER` | Entwicklungsaufträge für freigeschaltete Mitglieder (braucht `SCHRANKEN_VERSION` 2 oder höher) | aus | Drop-in | `voice-core/entwicklung_betrieb.py` |
| `WAMO_ENTWICKLUNG_GITHUB` | persönlicher GitHub-Weg (Plan C, braucht Schranken-Version 4) | aus | Drop-in | `voice-core/entwicklung_betrieb.py` |
| `WAMO_PRUEFEN` | Dispatcher: Befehl `pruefen` für Befehlskriterien auf Sokrates-2 (Dispatcher ab Version 6) | aus | `/etc/wamo/geheim.env` laut Docstring | `voice-core/abnahme_remote.py`, `infra/sokrates2/wamo_job_dispatch.py` |
| `WAMO_HAUS`, `WAMO_HAUS_MAX_TOKEN` | Dispatcher: Zugangsart `haus` über den Haus-Proxy (nur `an` schaltet ein, jeder Tippfehler sperrt), Höchstmenge Token je Lauf | aus, 3000000 | `/etc/wamo/geheim.env` | `infra/sokrates2/wamo_job_dispatch.py` |
| `WAMO_SERVERZUGANG` | Dispatcher: `aus` schaltet den Server-Zugang ab, sobald jedes Profil einen eigenen hat | an (Standard nicht belegt) | `/etc/wamo/geheim.env` | `infra/sokrates2/wamo_job_dispatch.py` |
| `WAMO_GITHUB`, `WAMO_ZWEIG` | in der Sandbox: Wert `persoenlich` und Zweig `wamo/<auftrag>`, der Wächter sperrt dann `push`, `gh` und das Ändern von Remotes | gesetzt vom Dispatcher | Sandbox | `voice-core/dev_guard.py`, `infra/sokrates2/wamo-job.sh` |
| `WAMO_PORT_VON`, `WAMO_PORT_BIS` | Portbereich je Platz der Sandbox (20000 + n mal 100 bis plus 99) | gesetzt je Platz | Sandbox | `infra/sokrates2/wamo-job.sh` |

## 9. Office, Jira

Alle nur vom Server, nie aus der `.env` des PCs.

| Name | Zweck | Standard | Quelle |
|---|---|---|---|
| `WAMO_OFFICE` | Liste der Teile `dateien`, `outlook`, `teams`, `onenote`; leer oder unbekannt heißt aus. Gilt nur für Personen mit PC-Stufe, nie im Labor; am PC sperrt zusätzlich die Datei `office.aus`. | leer (aus) | `voice-core/office_werkzeuge.py` |
| `WAMO_JIRA` | Jira-Stories aus dem Canvas (`an` oder `aus`, Tippfehler bleibt aus) | aus | `voice-core/jira_client.py` |
| `WAMO_JIRA_URL` | Jira Cloud, nur `https://<name>.atlassian.net` | Standardtenant im Code | `voice-core/jira_client.py` |
| `WAMO_JIRA_EMAIL`, `WAMO_JIRA_TOKEN` | technischer Jira-Benutzer nur für W.A.I.S.; das Token ist ein Geheimnis (nie in Logs, nie an Entwicklungsaufträge) | leer | `voice-core/jira_client.py` |
| `WAMO_JIRA_PROJEKTE`, `WAMO_JIRA_STANDARD_PROJEKT` | Erlaubnisliste der Projektschlüssel, Standardprojekt (muss in der Liste stehen) | `WMCNL` | `voice-core/jira_client.py` |

## 10. Labor (Kern)

Alle nur vom Server (`wamo-core-env`), Quelle `voice-core/labor*.py`. Das Dienst-Token ist ein Geheimnis.

| Name | Zweck | Standard |
|---|---|---|
| `WAMO_LABOR_URL`, `WAMO_LABOR_TOKEN` | Adresse (HTTPS) und Bearer-Token des Test-Jira-Dienstes (Geheimnis) | leer |
| `WAMO_LABOR_EINWILLIGUNG_MIN` | kleinste gültige Version des Einwilligungshinweises, ohne sie keine Laborsitzung | leer |
| `WAMO_LABOR_TEXT_SPEICHERN` | nur `an` speichert den Gesprächstext | aus |
| `WAMO_LABOR_DATEN` | Ordner mit Regeln, Kontakten, Vorlagen und Wissen (Lader `labor_daten.py`) | Konstante im Lader |
| `WAMO_LABOR_MAIL_DOMAIN` | erlaubte Domäne der Bestätigungsmail | Konstante `DOMAIN_STANDARD` |
| `WAMO_LABOR_FREIGABE_SECS`, `WAMO_LABOR_MAX_OFFEN`, `WAMO_LABOR_MAX_SCHREIBEN` | Grenzen der Freigabekarten | Standard in `labor_freigaben.py` |
| `WAMO_LABOR_TEXT_ABSTAND_SECS`, `WAMO_LABOR_TEXT_MAX_ZEICHEN`, `WAMO_LABOR_SUCHEN_MAX`, `WAMO_LABOR_ANFRAGEN_MAX`, `WAMO_LABOR_KLICK_ABSTAND_SECS`, `WAMO_LABOR_KLICK_MAX` | Ratenbegrenzung je Laborsitzung und Profil, Unbrauchbares heißt Standard | Standard in `labor_limit.py` |

## 11. Host (`host/`)

Umgebung des Host-Prozesses am PC (`host/wamo_host.py` und Module).

| Name | Zweck | Standard |
|---|---|---|
| `WAMO_HOST_BIND`, `WAMO_HOST_PORT` | Bindung des HTTP-Betriebs, nie `0.0.0.0`, nur Loopback | `127.0.0.1`, `8765` |
| `WAMO_HOST_TOKEN_FILE` | Datei mit dem Bearer-Token (mindestens 43 Zeichen), Pflicht im HTTP-Betrieb | nicht gesetzt |
| `WAMO_HOST_FREIGABE`, `WAMO_HOST_FREIGABE_DATEI` | Freigabe-Schlüssel (Geheimnis) als Wert oder Datei; lokal gibt ihn der Kern mit | nicht gesetzt |
| `WAMO_HOST_GERAET_DATEI` | Datei `geraet.json` für die Gerätebindung, aktiviert die Prüfung von `X-WAMO-Geraet` und `X-WAMO-Profil` | leer |
| `WAMO_AUDIT_LOG` | Pfad des Audit-Logs | `wamo_audit.jsonl` neben dem Host |
| `WAMO_HOST_LOG` | Log-Datei des Hosts | leer |
| `WAMO_GITHUB_ORG`, `WAMO_GITHUB_KLONEN_VON` | Organisation für `github_repo_anlegen` und Herkunft für `git_klonen` | Standard im Code, nicht gelistet |
| `WAMO_MAIL_INTERN` | interne Domänen für die Mailkarte | `wamocon.com` laut `CLAUDE.md` |
| `WAMO_ONENOTE_DOMAENE` | Domäne zur Eingrenzung des Firmen-OneDrive für OneNote | leer |
| `WAMO_UI_EXES`, `WAMO_UI_TITLE` | Programme und Fenstertitel der eigenen Oberfläche, die der Host nie bedient | Konstanten in `windows_control.py` |
| `WAMO_OFFICE_ECHT`, `WAMO_OUTLOOK_ECHT`, `WAMO_OUTLOOK_ENTWURF`, `WAMO_OUTLOOK_TESTADRESSE`, `WAMO_TEAMS_ECHT`, `WAMO_TEAMS_TESTADRESSE` | nur für Echttests am Windows-PC (Marker `office`) | nicht gesetzt |

## 12. Desktop-App (`desktop/`)

| Name | Zweck | Standard |
|---|---|---|
| `WAMO_UI_URL`, `WAMO_VOICE_CORE_URL` | Adresse der Oberfläche und des Kerns (http oder https) im Entwicklermodus | `http://localhost:3000` und `http://localhost:7860` (Konstanten in `installation.js`) |
| `WAMO_MANAGE_SERVICES` | `off` verhindert, dass die App Voice-Core und Oberfläche selbst startet | an |
| `WAMO_UI_DEV` | `1` startet `next dev` statt des Produktions-Builds | aus |
| `WAMO_LOG_LEVEL` | Log-Stufe, die an den Voice-Core weitergegeben wird, nie DEBUG | INFO |
| `WAMO_VOLLBILD_LOG`, `WAMO_BERECHTIGUNG_LOG` | Rohwerte des Vollbild-Wächters, jede Berechtigungsanfrage ins Log | aus |
| `WAMO_CA`, `WAMO_CA_SHA256`, `WAMO_NAMEN` | in `zertifikat.js` und `main.js`: Pfad der mitgelieferten CA, fester Fingerabdruck, Liste der erlaubten Servernamen (Werte aus der Installation, nicht aus der Umgebung belegt) | Zweck teilweise nicht belegt |
| `WAMO_PC_SSH_HOST`, `WAMO_PC_SSH_HOSTKEY_FP` | Ziel und Fingerabdruck des Hostschlüssels für die Geräteeinrichtung | Standard in `geraet.js` |
| `WAMO_PROBE_USERDATA` | nur für die Berechtigungsprobe `berechtigungen.probe.js` | nicht gesetzt |

## 13. Oberfläche (`ui/`)

| Name | Zweck | Standard | Quelle |
|---|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Supabase-Adresse und öffentlicher Schlüssel für die Anmeldung (nie `service_role`) | leer | `ui/src/components/LoginGate.tsx` |
| `NEXT_PUBLIC_VOICE_CORE_URL` | lokaler Kern (Betriebsart Unterwegs), steht in der CSP | `http://localhost:7860` | `ui/src/lib/betriebsart.ts`, `ui/next.config.ts` |
| `NEXT_PUBLIC_WAMO_KERN_BUERO` | Kern im Büro, nur https | leer | `ui/src/lib/betriebsart.ts` |
| `NEXT_PUBLIC_WAMO_BETRIEBSART` | Standard der Betriebsart im Browser (`buero`) | `unterwegs` | `ui/src/lib/betriebsart.ts` |
| `NEXT_PUBLIC_WAMO_NUR_BUERO` | Build für Sokrates-2 (`ja`): kein lokaler Kern, nur Büro | aus | `ui/src/lib/geraet.ts`, `ui/next.config.ts` |
| `NEXT_PUBLIC_WAMO_ANMELDUNG_MAX_STUNDEN_BROWSER` | Höchstalter der Anmeldung im Browser in Stunden | 24 (`BROWSER_MAX_STUNDEN`) | `ui/src/lib/anmeldung.ts` |
| `NEXT_PUBLIC_WAMO_MAX_SITZUNG_MIN` | Anzeige der Höchstdauer einer Sitzung | Zweck nach Name, Standard nicht belegt | `ui/src/components/kommando/Statusanzeige.tsx` |
| `NEXT_PUBLIC_WAMO_VORSCHAU` | Entwicklungsvorschau, nur zusammen mit `next dev` | aus | `ui/src/app/page.tsx` |
| `WAMO_UI_STANDALONE` | `1` baut das eigenständige Image (`output: "standalone"`) | aus | `ui/next.config.ts` |
| `WAMO_VERSION`, `WAMO_COMMIT`, `WAMO_BAUZEIT`, `WAMO_SAUBER` | Version (aus `package.json`), Commit, Bauzeit, Sauberkeit des Baums für `GET /version.json` | `WAMO_VERSION` aus `package.json` | `ui/src/app/version.json/route.ts` |

## 14. Gerätedienst (`geraete/`)

Dienst `wamo-geraete` auf Sokrates-2, Konfiguration in `geraete/wamo_geraete/konfig.py`. Die Pfade sind Konstanten des Codes.

| Name | Zweck | Standard |
|---|---|---|
| `WAMO_GERAETE_KONFIG`, `WAMO_GERAETE_BEKANNT`, `WAMO_GERAETE_ENV` | Geräteliste (TOML), bekannte Geräte, Umgebungsdatei mit Zugangsdaten | `/etc/wamo-geraete/geraete.toml`, `bekannt.toml`, `geraete.env` |
| `WAMO_GERAETE_SOCKET`, `WAMO_GERAETE_ZUSTAND`, `WAMO_GERAETE_KERN_BENUTZER` | Unix-Socket, Zustandsordner, erwarteter Benutzer des Kerns | `/run/wamo-geraete/geraete.sock`, `/var/lib/wamo-geraete`, `wamo-core` |
| `WAMO_GERAETE_KOPPLUNG`, `WAMO_GERAETE_SSH_ORDNER`, `WAMO_GERAETE_SCHRIFTEN`, `WAMO_GERAETE_LG_MANIFEST` | Kopplungsdaten des Fernsehers, SSH-Ordner für Serverstatus, Schriften der Rasterausgabe, Manifest des LG-Treibers | Konstanten im Code |
| `WAMO_GERAETE_SELBSTTEST` | Selbsttest beim Start | an |
| `WAMO_GERAETE_SWITCH1_BENUTZER`, `_PASSWORT`, `_PRIVPASSWORT` | SNMPv3-Lesezugang für einen Switch (Benutzer, Anmelde- und Verschlüsselungs-Passphrase, Geheimnisse) | leer |
| `WAMO_GERAETE_<Gerät>_<Feld>` | Zugangsdaten je Gerät laut `infra/sokrates2/geraete.toml.example` (Fritzbox, NAS, Shelly: Benutzer, Passwort; Geheimnisse) | leer |

## 15. Labor-Dienst (`labor-dienst/`)

Test-Jira-Dienst der Kollegen, Konfiguration in `labor-dienst/wamo_labor_dienst/konfig.py`.

| Name | Zweck | Standard |
|---|---|---|
| `WAMO_LABOR_DIENST_PORT`, `WAMO_LABOR_DIENST_HOST` | Port und Bindung | `8080` und nicht belegt |
| `WAMO_LABOR_DIENST_DATEN` | Datenordner (SQLite) | nicht belegt |
| `WAMO_LABOR_DIENST_KERN_TOKEN_DATEI`, `WAMO_LABOR_DIENST_BETREUER_TOKEN_DATEI` | Dateien mit den Bearer-Token von Kern und Betreuern (Geheimnisse, nur Dateinamen) | nicht belegt |
| `WAMO_LABOR_DIENST_PLATZ_MB` | Größe je Platz in MB | nicht belegt |
| `WAMO_LABOR_DIENST_PROXYS`, `WAMO_LABOR_DIENST_BIS` | vertrauenswürdige Proxys, Ablaufdatum der Daten | Zweck nicht belegt |
| `WAMO_LABOR_ECHTZEIT` | steht in `labor-dienst/pyproject.toml`, Zweck nicht belegt | nicht belegt |

## Weiterführend

- [Betriebsvariablen und Einrichtungsskripte](konfiguration-betrieb.md), [Voice-Core](voice-core.md), [Host und Desktop](host-und-desktop.md), [Oberfläche](oberflaeche.md)
- Betrieb und Rückwege: [../betrieb/betriebshandbuch.md](../betrieb/betriebshandbuch.md), [../betrieb/administrationshandbuch.md](../betrieb/administrationshandbuch.md)
- Sicherheit: [../sicherheit/sicherheit-und-datenschutz.md](../sicherheit/sicherheit-und-datenschutz.md)
- Bestehende Dokumente: `voice-core/.env.example`, [../../jira-benutzer-einrichten.md](../../jira-benutzer-einrichten.md), [../../entwicklung-im-betrieb.md](../../entwicklung-im-betrieb.md)
