#!/usr/bin/python3 -I
"""WAMO-Auftragsdispatcher auf Sokrates-2: Forced Command des SSH-Schlüssels "wamo-jobs".

Installiert als /opt/wamo/bin/wamo-job-dispatch (root:wamo 0750; /opt/wamo gehört root, wamo kann nichts
umbenennen) durch wamo-job-einrichten.sh. Der Schlüssel des Voice-Cores steht in
/etc/ssh/authorized_keys.d/wamo (root, über den sshd-Drop-in /etc/ssh/sshd_config.d/wamo.conf) als

    restrict,from="192.168.178.0/24",command="/opt/wamo/bin/wamo-job-dispatch" ssh-ed25519 AAAA... wamo-jobs

Damit startet dieser Schlüssel nie eine Shell, sondern immer dieses Programm. Der gewünschte Befehl kommt
aus SSH_ORIGINAL_COMMAND und wird streng geprüft (feste Muster, keine Shell):

    ping                                        Erreichbarkeit und Version (JSON)
    start   <job> <projekt> <art> [<session>]   Auftrag ausführen, mit Session-ID als Fortsetzung
    status  <job>                               Zustand des Auftrags (JSON)
    pending <job>                               offene Freigabe-Anfragen, geprüft (JSON-Zeilen)
    approve <job> <fingerabdruck>               Freigabe für den nächsten Lauf des Auftrags
    cancel  <job>                               laufenden Auftrag beenden
    pruefen <job>                               ein Befehl der Abnahme in der Sandbox des Auftrags (JSON-Zeile, standardmäßig AUS)
    aenderung  <job> <profil>                   persönlicher GitHub-Weg: das Ereignis aenderung aus aenderung.json (Dispatcher 10)
    einreichen <job> <profil>                   persönlicher GitHub-Weg: Push des Kandidaten und Pull Request (zwei stdin-Zeilen)
    verwerfen  <job> <profil>                   persönlicher GitHub-Weg: Kandidat und Kopien des Repos löschen
    aufraeumen [alle]                           nur lokal (Timer, Rückweg): Kopien privater Repos löschen

start: Die erste stdin-Zeile ist ein JSON-Objekt {"auftrag": "...", "system": "...", "modell": "..." (optional),
"repo": "owner/name" (optional, Ziel-Repo für das GitHub-Token), "zugang": "folgt" | "server" | "haus" (optional),
"profil": "<8 Hexzeichen>" (bei folgt und haus Pflicht, Kennung des Profils für die Buchführung)}. Mit "zugang": "folgt" kommt als
zweite Zeile der persönliche Claude-Zugang des Profils {"typ": "oauth" | "api", "wert": "...", "workspace": "wrkspc_..."
(nur api, optional)}; er gilt für genau diesen Lauf und ersetzt den Claude-Zugang aus geheim.env vollständig (kein
Mischen). "server" erlaubt ausdrücklich den Zugang aus geheim.env (Standard ohne das Feld, für ältere Kerne; mit
WAMO_SERVERZUGANG=aus in geheim.env abschaltbar). Der Wert steht nie in argv, Log, Auftragsordner, Kopfzeile, Ereignissen
oder Fehlertexten und wird nicht gespeichert; in der Ausgabe und in den Dateien unter claude/ wird er geschwärzt.
"haus" (Paket P6b, standardmäßig AUS, nur mit WAMO_HAUS=an in geheim.env; jeder andere Wert und jeder Tippfehler im Namen sperrt) lässt
Claude Code mit einem Hausmodell über den Proxy wamo-haus-proxy auf Loopback (HAUS_URL) laufen. Der Kern schickt dabei nur die Art und
das Profil, nie einen Wert, und keine zweite Zeile. Der Dispatcher erzeugt je Lauf ein Auftragstoken wh1-<job>-<64 Hexzeichen>, gibt
es der Sandbox als ANTHROPIC_API_KEY (dazu ANTHROPIC_BASE_URL, die Modellnamen und CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC, nichts
aus geheim.env für Claude) und legt für den Proxy nur dessen SHA-256 ab: /run/wamo-haus/<job>.json (haus_tokendatei, atomar, 0640,
Felder v, job, hash, profil, bis, max_token), gelöscht am Laufende, auch bei Abbruch, Ausnahme oder Signal. Fehlt der Ordner (tmpfiles.d
des Proxys) oder ist er nicht sicher, startet nichts (Ereignis keine_zugangsdaten mit zugang haus, Exit 5). Das Modell ist HAUS_MODELL,
ein Wunsch im Feld modell gilt nur aus HAUS_MODELLE. Die Buchführung je Projekt zählt HAUS@<profil> als eigenen Zugang.
Danach bleibt stdin
offen und dient als Lebenslinie: endet sie (Auflegen, Verbindungsabbruch, Voice-Core beendet), wird der
Auftrag sofort beendet. stdout trägt die stream-json-Ausgabe von Claude Code und eigene Zeilen
{"type": "wamo", "ereignis": ...}; Zeilen dieses Typs aus der Sandbox werden verworfen. Das Ereignis "kontingent"
gibt die Limits des Max-Abos aus den rate_limit_event von Claude Code weiter (nur Felder einer Allowlist, kontingent.py).
Ablauf je Lauf:

    1. Auftragsordner /srv/wamo/jobs/<job> anlegen bzw. prüfen (Projekt und Art sind an den Auftrag gebunden).
    2. Sperren: ein Lauf je Auftrag, ein Auftrag je Projekt, dann ein Platz je Person und ein Platz gesamt (plaetze_belegen: höchstens
       MAX_PARALLEL_PROFIL je Person und MAX_PARALLEL gesamt aus kernkanal.conf, nie über PARALLEL_MAX). Der Platz bestimmt den eigenen
       Teil der Entwicklungsports (platz_ports), den wamo-job.sh mit --platz an Landlock gibt. Belegt: Ereignis belegt mit grenze.
    3. Freigaben aus freigaben.json (außerhalb der Sandbox) als schreibgeschützte approvals.json für
       diesen Lauf bereitstellen; Anfragen des letzten Laufs nach angefragt.jsonl übernehmen.
       Projektordner entschärfen: .claude/settings*.json, .mcp.json, Git-Hooks weg, .git/config nur
       mit einer Allowlist (Autostart-Flächen, die ein früherer Lauf gepflanzt haben könnte).
    4. Selbsttest in der Sandbox: Wächter-Hook mit einem bekannten Sperrfall (genaue Ablehnung), /etc/wamo
       unsichtbar, approvals.json schreibgeschützt, Wächterpfade nicht umbenennbar, Landlock-Sperre auf
       einen eigenen Probe-Port, Ausgangsfirewall zu Docker-Bridge und LAN. Scheitert er, startet nichts.
    5. Token nur der Auftragsart aus /etc/wamo/geheim.env als Umgebung (nie argv) an wamo-job.sh, dazu genau ein
       Claude-Zugang: der persönliche aus der zweiten stdin-Zeile oder, wenn erlaubt, der aus geheim.env. Bekäme der
       Lauf ein Token, das ein früherer Lauf im selben Projekt nicht hatte (ein persönlicher Zugang zählt je Profil),
       startet er nur nach einer Freigabe (Ereignis zugang_erweitert) oder auf einem frischen, leeren Projektordner.
       Das Modell richtet sich nach der Zugangsart (modell_waehlen): Abo (oauth) Sonnet, Hausmodell (haus) HAUS_MODELL, sonst das
       der Art. Bei haus statt eines Claude-Zugangs das Auftragstoken dieses Laufs (siehe oben).
    6. GitHub im App-Modus (WAMO_GH_APP_ID, WAMO_GH_APP_INSTALLATION_ID, WAMO_GH_APP_SCHLUESSEL in geheim.env):
       der Dispatcher signiert außerhalb der Sandbox ein JWT (RS256) mit dem privaten Schlüssel der App, holt
       damit ein Installations-Token nur mit den Rechten der Auftragsart (Werkzeugkarte, GITHUB_ZUGRIFF) und,
       wenn die Kopfzeile ein Repo nennt, nur für dieses Repo. Es geht als GH_TOKEN in die Sandbox und wird am
       Laufende widerrufen (auch bei Abbruch, cancel, Fehler oder SIGTERM). Scheitert das, startet nichts
       (Ereignis start_abgelehnt, Code 8); ein Rückfall auf GH_TOKEN aus geheim.env gibt es dann nicht.
       Ohne diese drei Variablen gilt weiter GH_TOKEN bzw. GH_TOKEN_LESEN.

pruefen: Führt einen Befehl der Abnahme (befehl:-Kriterium) im Projekt des Auftrags aus, nach einem beendeten Lauf, in einer
engeren Sandbox als der Auftragslauf: kein Netz (--unshare-net), kein Token, kein Claude-Zugang, kein Zustand des Auftrags,
Umgebung nur die Basisumgebung plus Git-Hooks aus (wamo-job.sh --modus pruefen), Zeitlimit 120 s. Standardmäßig AUS: ohne
WAMO_PRUEFEN=an in geheim.env (jeder andere Wert, auch ein Tippfehler im Namen, sperrt) wird jeder Aufruf abgewiesen. Die erste
stdin-Zeile ist {"argv": [...]}: genau dieses Feld, höchstens 8 KiB. Der Dispatcher prüft argv erneut gegen die Allowlist
(abnahme_befehl.py, der Kern ist nicht vertrauenswürdig), dann mit dem Wächter (decide wie ein Bash-Aufruf), und nimmt das Projekt
nur aus auftrag.json. Sperren wie bei start (ein Lauf je Auftrag, ein Auftrag je Projekt, Platz je Person und gesamt; Person pc oder lokal),
höchstens 40 Aufrufe je Auftrag, vorher Projekt entschärfen und den Selbsttest im Modus pruefen (Netz zu). stdin bleibt als
Lebenslinie offen (EOF beendet den Lauf), cancel und das Zeitlimit beenden die Einheit. Antwort: eine JSON-Zeile
{"v":1,"ok","exit","abgebrochen","grund","dauer_s","ausgabe","gekuerzt"} (Ausgabe: das Ende, höchstens 2048 Byte, geschwärzt, nur
als JSON-String); ok nur bei einem echten int 0. Prozess-Exit 0: der Befehl lief (auch wenn er scheiterte), 2 abgewiesen oder
nicht möglich, 3 Selbsttest, 4 belegt, 6 intern, 124 Zeitlimit, 130 abgebrochen: alles außer 0 heißt nicht erfüllt. Die Programme
python3, node 22, npm, make, grep, eslint, git und uv sind in der Sandbox da; pytest, ruff, mypy, tsc, pnpm, yarn, go, cargo und
dotnet fehlen: sie scheitern mit "nicht gefunden", das Kriterium gilt als nicht erfüllt. Die uv-Form läuft nur mit einer .venv.
Fehlt die Prüflogik bei eingeschaltetem Schalter oder ist sie defekt, kommt trotzdem genau eine Zeile (Exit 6). Vor jedem Aufruf: Reste
der Einheiten des Auftrags beenden, Pfade im Aufruf über Links auflösen (müssen im Projekt bleiben), freier Platz (2 GiB) und Projektgröße
(2 GiB, 5 s) messen: eine Eintrittsprüfung, keine Quote (eine echte Plattenquote fehlt). Nach dem Lauf wird das Projekt erneut entschärft.
pruefen führt keine Buchführung der Zugänge (zugang_pruefen): der Lauf hat keine Zugänge. cancel wirkt jobweit (Datei abbruch, alle
Einheiten des Auftrags); der Kern ruft es nach dem Ende von pruefen nicht mehr. Protokollzeilen aus freiem Inhalt sind bereinigt.

Kanäle (Version 7): Jede ssh-Verbindung gehört zu einem Kanal. lokal (ohne SSH_CONNECTION und SSH_ORIGINAL_COMMAND: Betreiber,
Rauchtests, Notaus), pc (Schlüssel aus authorized_keys.d/wamo, Verhalten wie Version 6) oder kern (Schlüssel aus
authorized_keys.d/wamo-kern). Die Zuordnung hängt am benutzten Schlüssel (SSH_USER_AUTH, sshd ExposeAuthInfo), nie an der Adresse.
Existiert ein Kern-Schlüssel oder /etc/wamo/kernkanal.conf, gilt der strikte Modus: was sich nicht eindeutig zuordnen lässt,
endet mit dem Ereignis kanal_gesperrt (herkunft_unklar) und Exit 2, vor jedem Lesen von geheim.env. Im Kern-Kanal gelten Befehlsliste,
nur eigene Aufträge (auftrag.json mit kanal=kern), Namensraum kern-, nur zugang=folgt oder haus (je mit Profil) und die Grenzen aus kernkanal.conf (Wendungen und
Kosten je Lauf als Flags von Claude Code, Starts, Laufzeit, Folgen, Abstand, Platz); eine Notaus-Datei lässt nur ping und status zu.
Version 8 trennt die Profile: Projektname kern-<Kennung>-<Name> mit der Kennung aus profil, die Kennung steht in auftrag.json, ein
Projektordner eines anderen Profils ist gesperrt (projekt), dazu feste Grenzen je Profil (grenze_profil).
Version 9 lässt Aufträge gleichzeitig laufen (Entscheidung von Niko 16.11.2026: sechs gesamt, je Person drei): PARALLEL_MAX ist die harte
Obergrenze, MAX_PARALLEL und MAX_PARALLEL_PROFIL in kernkanal.conf senken sie (ohne gültige Datei höchstens einer, wie bis Version 8). Person:
im Kern-Kanal das Profil, der PC-Kanal zusammen (pc), lokale Aufrufe zusammen (lokal); alle zählen gegen die Gesamtgrenze. Ein Start an einer
Grenze endet mit dem Ereignis belegt, Feld grenze aus BELEGT_GRENZEN (auftrag, projekt, gesamt, profil) und max (die Zahl der Grenze), Exit 4.
Jeder Platz hat seinen Teil der Entwicklungsports (Landlock, siehe wamo-job.sh). Im Kern-Kanal laufen die zweite Prüfung und das Buchen des
Starts unter der Sperre kernkanal (gleichzeitige Starts prüfen nie denselben Stand), laufende Aufträge reservieren in der Laufzeit je Tag ihr
Zeitlimit (lauf_zeitlimit_s).
Version 10 bringt den persönlichen GitHub-Weg (Plan C, docs/persoenliche-zugaenge.md, standardmäßig aus über PERSOENLICH in
kernkanal.conf): Kopffeld github=persoenlich (nur Kern-Kanal, mit repo und profil, gebunden in auftrag.json) und scopes_ausnahmen, die
GitHub-Zeile auf stdin nur über den Bytes-Leser StdinLeser (das Token ist ein Ausschnitt eines bytearray, nie str oder bytes, der Prozess ist
nicht dumpable), git außerhalb der Sandbox nur über den Credential-Helfer wamo-git-zugang mit einer Pipe, die Sandbox-Schritte klon, ausgabe
und pruefung ohne Netz, die Befehle aenderung, einreichen und verwerfen und das Aufräumen. Die GitHub-Logik steht in wamo_job_github.py, die
Schnittstelle dorthin ist das Protokoll Werkzeuge (DispatcherWerkzeuge). Ohne github in der Kopfzeile ist der Weg genau der von Version 9.
Die Regeln stehen in wamo_job_kernkanal.py, hier nur die Einhängepunkte. Jeder Verstoß: {"type": "wamo", "ereignis":
"kanal_gesperrt", "grund": <Code>} und Exit 2. ping meldet kanal und kernkanal, dazu haus (Schalter an und Ordner des Proxys bereit).

Nur Standardbibliothek, im App-Modus zusätzlich das Systempaket python3-cryptography. Wächter, Werkzeugkarte, Kontingent-Parser,
die Prüflogik von pruefen (abnahme_befehl.py, wamo_job_pruefen.py) und die Regeln des Kern-Kanals (wamo_job_kernkanal.py) kommen aus
/opt/wamo/waechter (Kopien aus voice-core und infra/sokrates2).
"""

from __future__ import annotations

import base64
import errno
import hashlib
import http.client
import json
import os
import re
import secrets
import shlex
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from collections import namedtuple
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType

# 10: persönlicher GitHub-Weg (Plan C): Kopffeld github, GitHub-Zeile, Befehle aenderung, einreichen, verwerfen, Sandbox-Schritte ohne Netz.
# 9: gleichzeitige Aufträge (Plätze gesamt und je Person, eigene Entwicklungsports je Platz, Laufzeit mit Reserve laufender Aufträge).
# 8: Trennung je Profil im Kern-Kanal (Projektname kern-<Kennung>-<Name>, Kennung in auftrag.json, Grenzen je Profil). Die Zeile darunter
# bleibt genau so (ohne Kommentar am Ende): wamo-job-kern-einrichten.sh liest die Zahl daraus.
VERSION = "10"

HEIM = Path("/srv/wamo")
APP = Path("/opt/wamo")  # root-eigen; Programme in bin/, Wächter in waechter/ (in der Sandbox derselbe Pfad)
BIN = APP / "bin"
WAECHTER = APP / "waechter"
JOBS = HEIM / "jobs"
PROJEKTE = HEIM / "projekte"
LOGS = HEIM / "logs"
RUNNER = BIN / "wamo-job.sh"
MANAGED = APP / "claude-code" / "managed-settings.json"
GEHEIM = Path("/etc/wamo/geheim.env")
CLAUDE = HEIM / ".local" / "bin" / "claude"  # derselbe Pfad in der Sandbox
NPM_GLOBAL = HEIM / ".npm-global"  # in der Sandbox nur lesbar
# Jeder Name, den das eigene Repo je getragen hat (bis 14.11.2026 wamo, seitdem w.a.i.s), nur ergänzen. Dieselbe Liste steht im Kern
# (voice-core/dev_guard.py) und im Kern-Kanal; geprüft wird allein mit ist_eigenes_repo, test_kernkanal_vertrag.py hält alle drei gleich.
SELF_REPOS = ("wamo", "w.a.i.s")
SELF_REPO = SELF_REPOS[0]  # Alias für ältere Verweise, nie zum Vergleichen
# GitHub-ID des eigenen Repos: bleibt bei jeder Umbenennung gleich, geprüft an jeder Antwort von GitHub zu Token und Installation
SELF_REPO_IDS = frozenset({1425139508})
# Harte Obergrenze gleichzeitiger Aufträge aller Kanäle (wie PARALLEL_HART im Modul des Kern-Kanals); kernkanal.conf kann sie nur senken.
# Die Aufträge teilen sich Benutzer und Loopback (kein eigener Netz-Namensraum): jeder Platz bekommt deshalb seinen eigenen Teil der
# Entwicklungsports (platz_ports), Landlock lässt binden und verbinden im Bereich 20000-20999 nur dort zu.
PARALLEL_MAX = 6
LAN_PROBE = "192.168.178.1"  # Ziel der Firewall-Probe im Selbsttest (Router, Port 443)
ENTWICKLUNGS_PORTS = range(20000, 21000)  # 127.0.0.1:20000-20999 lässt der Ausgangsfilter für eigene Server zu
PORTS_JE_PLATZ = 100  # Platz n: 20000 + n*100 bis 20000 + n*100 + 99 (wamo-job.sh platz_ports, abschottung.py BEREICH_MAX_PORTS)
PLAETZE_SPERRE = "plaetze"  # Sperre, unter der ein Start die Plätze zählt und einen belegt (kurz, nie während eines Laufs gehalten)
PLAETZE_WARTEN_S = 10.0  # so lange wartet ein Start höchstens auf diese Sperre, danach gilt er als belegt (fail closed)
PERSON_RE = re.compile(r"[0-9a-f]{8}|pc|lokal")  # wie PERSON_RE im Modul des Kern-Kanals: Kennung des Profils, PC-Kanal oder lokal
BELEGT_GRENZEN = ("auftrag", "projekt", "gesamt", "profil")  # wie BELEGT_GRENZEN im Modul des Kern-Kanals (Feld grenze im Ereignis belegt)
MAX_OFFENE_FREIGABEN = 10  # Karten je Auftrag
ZUGANG_TOOL = "WAMO-Zugang"  # Freigabe-Anfrage für mehr Zugänge als frühere Läufe im Projekt
WAMO_REPO_GESPERRT = "Das WAMO-Repo selbst ist für Aufträge gesperrt"
KERN_PRAEFIX = "kern-"  # Namensraum der Projekte des Kern-Kanals; dem PC-Kanal verschlossen
KANAL = "lokal"  # Kanal der laufenden Verbindung (lokal, pc, kern; unklar bei unbekannter Herkunft): main setzt ihn, log schreibt ihn mit
KERN_PFADE = None  # nur für Tests: andere Pfade des Kern-Kanals (None: die echten, siehe wamo_job_kernkanal.PFADE)
KERN_LESER = None  # nur für Tests: anderer Dateizugriff (Eigentümer und Rechte)
KERN_UID = None  # nur für Tests: Benutzerkennung des Dispatchers

# Exit-Codes von "start" (zusätzlich zu den Ereignissen im Datenstrom)
EXIT_OK = 0
EXIT_ABGEWIESEN = 2
EXIT_SELBSTTEST = 3
EXIT_BELEGT = 4
EXIT_KEIN_ZUGANG = 5
EXIT_INTERN = 6
EXIT_ZUGANG_ERWEITERT = 7
EXIT_GITHUB_APP = 8  # App-Modus: Token nicht erzeugbar oder Konfiguration kaputt (fail-closed)
EXIT_ZEITLIMIT = 124
EXIT_ABGEBROCHEN = 130

COMMAND_RE = re.compile(r"[a-z]{2,10}(?: [A-Za-z0-9_-]{1,64}){0,4}")
JOB_RE = re.compile(r"[0-9a-f]{16,32}")
PROJECT_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,48}[a-z0-9]")
SESSION_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
FP_RE = re.compile(r"[0-9a-f]{64}")  # voller SHA-256 aus dev_guard.fingerprint
ENV_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
WORKSPACE_RE = re.compile(r"[A-Za-z0-9_-]{1,100}")
MODELL_RE = re.compile(r"[a-z0-9][a-z0-9.-]{1,63}")
# Ziel-Repo owner/name: genau ein Schrägstrich, Owner wie bei GitHub (Buchstaben, Ziffern, Bindestrich, bis 39),
# Name bis 100 Zeichen aus A-Z, a-z, 0-9, Punkt, Unterstrich, Bindestrich (dieselbe Regel in dev_agent.py)
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}")
# Persönlicher Claude-Zugang eines Profils (zweite stdin-Zeile von start). Das Format wird streng geprüft: oauth ist
# der Token aus `claude setup-token` (sk-ant-oat01-...), api ein Anthropic-API-Schlüssel (sk-ant-api03-...); Admin-
# Schlüssel (sk-ant-admin01-...) und Sitzungsschlüssel passen auf keins von beiden.
ZUGANG_MODI = ("folgt", "server", "haus")
ZUGANG_FORMAT = {"oauth": re.compile(r"sk-ant-oat[0-9]{2}-[A-Za-z0-9_-]{20,400}"),
                 "api": re.compile(r"sk-ant-api[0-9]{2}-[A-Za-z0-9_-]{20,250}")}
ZUGANG_VARIABLE = {"oauth": "CLAUDE_CODE_OAUTH_TOKEN", "api": "ANTHROPIC_API_KEY"}
ZUGANG_FELDER = {"typ", "wert", "workspace"}
PROFIL_RE = re.compile(r"[0-9a-f]{8}")
WORKSPACE_ZUGANG_RE = re.compile(r"wrkspc_[A-Za-z0-9]{6,60}")
MAX_ZUGANG_BYTES = 2048
ZUGANG_ERSATZ = b"[CLAUDE_ZUGANG]"
MAX_SCHWAERZ_DATEI = 64 * 1024 * 1024  # größere Dateien unter claude/ werden gelöscht statt gelesen
MAX_SCHWAERZ_DATEIEN = 5000
SCHWAERZ_ZEIT_S = 20.0  # Zeitbudget für das Schwärzen nach dem Lauf; danach gilt es als unvollständig
KONTINGENT_ABSTAND_S = 2.0  # höchstens alle 2 Sekunden ein Ereignis kontingent (die Zeilen kommen aus der Sandbox)
SK_ANT_RE = re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}")  # jeder Anthropic-Schlüssel in der Ausgabe, auch ein fremder
# Zugangsart haus (Paket P6b, Vertrag mit dem Proxy wamo-haus-proxy aus P6a): Claude Code spricht über den Proxy auf Loopback mit einem
# Hausmodell, nur der Proxy kennt den Schlüssel für LiteLLM. Die Sandbox bekommt ein Auftragstoken je Lauf, der Proxy nur dessen SHA-256.
HAUS_SCHALTER = "WAMO_HAUS"  # in geheim.env, nur "an" schaltet ein (Standard aus)
HAUS_MAX_TOKEN_NAME = "WAMO_HAUS_MAX_TOKEN"  # in geheim.env, Höchstmenge an Token je Lauf, die der Proxy durchsetzt
HAUS_URL = "http://127.0.0.1:18090"
# wamo-haus-coder: eigene Gewichte qwen3.6:35b-a3b-coding (Q4_K_M, eigener Digest) im Ollama von Sokrates-2 mit num_ctx 65536, also ein
# eigener Runner neben dem Chat-Modell qwen3.6:35b mit 16k (sie laden sich nie gegenseitig neu); im zentralen LiteLLM als eigenes Modell.
# qwen3.6-35b (Sokrates-1, Kontext 32768) bleibt als Wunsch erlaubt
HAUS_MODELL = "wamo-haus-coder"
HAUS_MODELLE = (HAUS_MODELL, "qwen3.6-35b")  # ein Wunsch im Kopfzeilenfeld modell gilt bei haus nur aus dieser Liste, nie aus der Allowlist der Werkzeugkarte
HAUS_MODELL_VARIABLEN = ("ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
                         "ANTHROPIC_SMALL_FAST_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL")  # jede Modellklasse von Claude Code zeigt aufs Hausmodell
HAUS_ORDNER = Path("/run/wamo-haus")  # tmpfiles.d des Proxys: 2750 wamo:wamo-haus-proxy; der Dispatcher legt ihn nie selbst an
HAUS_TOKEN_RE = re.compile(rb"wh1-[0-9a-f]{16,32}-[0-9a-f]{64}")  # jedes Auftragstoken in der Ausgabe, auch ein fremdes
HAUS_MAX_TOKEN_STANDARD = 3_000_000
HAUS_MAX_TOKEN_MIN, HAUS_MAX_TOKEN_MAX = 10_000, 20_000_000
HAUS_NACHLAUF_S = 300  # die Tokendatei gilt bis Start plus Zeitlimit des Laufs plus diese Sekunden
HAUS_DATEI_MODUS = 0o640
LAUF_KONF = APP / "wamo-job.conf"  # root:wamo 0640, wamo-job.sh liest daraus ZEITLIMIT_S
LAUF_ZEITLIMIT_STANDARD_S = 1800  # wie ZEITLIMIT_S in wamo-job.sh
LAUF_ZEITLIMIT_MAX_S = 7200  # wie ZEITLIMIT_MAX_S in wamo-job.sh
MAX_COMMAND_CHARS = 300
MAX_HEADER_BYTES = 256 * 1024
MAX_TEXT_CHARS = 20000
MAX_PENDING_BYTES = 2 * 1024 * 1024
MAX_PENDING_LINES = 200
MAX_PENDING_LINE_BYTES = 64 * 1024
MAX_STRING_CHARS = 8192
DECIDE_TIMEOUT_S = 1.0
GESAMT_PRUEF_BUDGET_S = 10.0  # N6: Gesamtzeit je gepruefte_anfragen-Aufruf
O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)  # auf Nicht-Linux 0: die fd-Funktionen laufen nur auf dem Server
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
MAX_LOG_BYTES = 2 * 1024 * 1024
MAX_ANGEFRAGT_BYTES = 1024 * 1024
MAX_ZEILE_STDOUT = 4 * 1024 * 1024  # dev_agent liest bis 10 MiB je Zeile; längere Zeilen werden verworfen
MAX_ZEILE_STDERR = 1024 * 1024
SPEICHER_DISPATCHER = 1024 * 1024 * 1024  # weiche Adressraumgrenze dieses Prozesses (RLIMIT_AS)

# Persönlicher GitHub-Weg (Plan C, Dispatcher 10, docs/persoenliche-zugaenge.md C.2 und C.5). Standard aus: ohne PERSOENLICH=an in
# kernkanal.conf weist der Kern-Kanal jeden Start mit github=persoenlich ab (persoenlich_aus). Das Token der Person kommt nur über stdin
# (GitHub-Zeile), wird nie zu str oder bytes, steht nie in einer Umgebung, argv, Datei oder einem Protokoll und erreicht die Sandbox nie.
# Die Werte stehen gleich in wamo_job_github.py (Paket S); test_job_persoenlich.py hält beide gleich.
GITHUB_WEG = "persoenlich"  # einziger Wert des Kopfzeilenfelds github (GITHUB_PERSOENLICH)
# GitHub-Zeile ohne Zeilenende (GITHUB_ZEILE_RE der Schnittstelle): nur fullmatch und Positionen, nie group()
GITHUB_ZEILE_RE = re.compile(rb'\{"typ":"github","wert":"(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82})"\}')
MAX_GITHUB_ZEILE = 256  # GITHUB_ZEILE_MAX_BYTES, mit Zeilenende
MAX_EINREICHEN_ZEILE = 64 * 1024  # EINREICHEN_ZEILE_MAX_BYTES, erste stdin-Zeile von einreichen
STDIN_PUFFER = MAX_HEADER_BYTES + 1 + MAX_ZUGANG_BYTES + 1 + MAX_EINREICHEN_ZEILE + MAX_GITHUB_ZEILE + 4096
LESEN_FRIST_S = 30.0  # so lange wartet der Dispatcher höchstens auf eine stdin-Zeile
# jedes GitHub-Token in Ausgaben, Protokollen und Fehlertexten (auch fremde und kodierte Teile ab 8 Zeichen); das exakte Token kommt dazu
GH_PAT_RE = re.compile(rb"(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{8,}")
GH_PAT_ERSATZ = b"[GITHUB_TOKEN]"
GIT_BENUTZER = b"x-access-token"  # Benutzername für git über HTTPS mit einem persönlichen Token (der Helfer gibt ihn mit aus)
HELFER = BIN / "wamo-git-zugang"  # Credential-Helfer: liest den Zugang aus einer geerbten Pipe, nur get für https://github.com
GIT_PROGRAMM = "/usr/bin/git"
PRLIMIT = "/usr/bin/prlimit"
GIT_ZEITLIMIT_S = 300
GIT_SPEICHER = 2 * 1024 * 1024 * 1024  # RLIMIT_AS je git-Aufruf des Dispatchers
GIT_DATEI_MAX = 4 * 1024 * 1024 * 1024  # RLIMIT_FSIZE je git-Aufruf
MAX_GIT_AUSGABE = 4 * 1024 * 1024
GIT_ARG_RE = re.compile(r"[A-Za-z0-9_@%+=:,./^~-]{1,4096}")  # argv eines git-Aufrufs: druckbar, ohne Leerzeichen, Anführungszeichen, $
# Sandbox-Schritte ohne Netz (wamo-job.sh --modus klon|ausgabe|pruefung, C.5.2): je Modus genau das feste Programm in /opt/wamo/waechter
SCHRITT_PROGRAMME = {"klon": (str(WAECHTER / "wamo-job-klon.sh"),),
                     "ausgabe": (str(WAECHTER / "wamo-job-ausgabe.sh"),),
                     "pruefung": ("/usr/bin/python3", "-I", str(WAECHTER / "wamo_job_auszug.py"))}
SCHRITT_ZEITLIMIT_S = {"klon": 300, "ausgabe": 60, "pruefung": 60}  # wie ZEITLIMIT_SCHRITT_* in wamo-job.sh
SCHRITT_ARG_RE = re.compile(r"--[a-z]{2,20}|[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")
MAX_SCHRITT_AUSGABE = 256 * 1024
# Zustände eines Auftrags mit github=persoenlich (aenderung.json, Feld status, C.5.1; AENDERUNG_STATUS der Schnittstelle)
ZUSTAENDE = ("keine", "gesperrt", "nur_lesen", "bereit", "einreichen_laeuft", "branch_gepusht", "eingereicht", "verworfen")
VERWERFEN_AUS = ("keine", "gesperrt", "nur_lesen", "bereit")
LAUF_ERLAUBT = ("keine", "gesperrt", "nur_lesen", "bereit")  # Folgelauf nur aus diesen Zuständen, sonst schon_eingereicht
AENDERUNG_FELDER = ("job", "status", "commit_id", "tree_id", "basis", "zweig", "dateien", "plus", "minus", "liste", "nicht_gelistet",
                    "gruende", "ungesichert", "lauf", "titel", "pr", "adresse")
MAX_AENDERUNG_BYTES = 512 * 1024
GITHUB_DATEIEN = ("basis.git", "aus.git", "bundle.ein", "ausgabe", "ergebnis")  # Kopien privater Repos im Auftragsordner (Aufräumen)
AUFRAEUMEN_FERTIG_S = 86400  # eingereicht oder verworfen: nach einem Tag
AUFRAEUMEN_SONST_S = 7 * 86400  # alle anderen: nach sieben Tagen
EIGNER_PRAEFIX = "eigner-"  # sperren/eigner-<projekt>.json: welcher Auftrag den Projektordner zuletzt aus seinem Klon gebaut hat
EXIT_GITHUB = EXIT_GITHUB_APP  # start_abgelehnt im persönlichen Weg (Grund aus GITHUB_GRUENDE), Exit 8 wie im App-Modus

SELFTEST_EVENT = {"tool_name": "Bash", "tool_input": {"command": "git push --force origin main"}}
SELFTEST_GRUND = "GESPERRT: Force-Push"  # Anfang der erwarteten Ablehnung durch dev_guard.py
PLUGIN_SETTINGS = json.dumps({"enabledPlugins": {"ecc@ecc": True}})
# Zugangsart haus: zusätzlich keine Vorabprüfung von WebFetch bei Anthropic (sonst ginge die abgerufene Domain an Anthropic)
PLUGIN_SETTINGS_HAUS = json.dumps({"enabledPlugins": {"ecc@ecc": True}, "skipWebFetchPreflight": True})
# Aus der globalen Claude-Konfiguration von wamo nur diese Schlüssel in den Auftrag übernehmen
CLAUDE_JSON_KEYS = (
    "installMethod", "userID", "machineID", "firstStartTime", "firstStartVersion",
    "migrationVersion", "opusProMigrationComplete", "sonnet1m45MigrationComplete",
    "hasResetAutoModeOptInForDefaultOffer", "autoUpdatesProtectedForNative",
)
SETTINGS_KEYS = ("enabledPlugins",)  # Rest (Hooks, Helfer, statusLine, Marktplätze) nie übernehmen; den
# Marktplatz ecc deklariert allein managed-settings.json (lokale Kopie ohne Hooks, wamo-job-ecc.py)


class Abgewiesen(Exception):
    """Aufruf verletzt die Regeln; wird protokolliert und mit Code 2 beantwortet."""


class ZugangUngueltig(Abgewiesen):
    """Die Zugangszeile ist unbrauchbar. Der Text nennt nie den Inhalt der Zeile."""


class HausNichtBereit(Exception):
    """Ein Lauf mit Hausmodell kann nicht starten: Schalter aus, Ordner des Proxys fehlt oder ist nicht sicher, die Tokendatei lässt
    sich nicht schreiben. Der Text nennt nie das Token."""


# Kopfzeile von start; zugang: None (älterer Kern), "folgt" (zweite Zeile mit dem Zugang), "server" oder "haus" (Hausmodell, keine Zeile);
# github: None (App-Weg wie bis Dispatcher 9) oder "persoenlich" (Plan C, nur im Kern-Kanal, mit repo und profil, GitHub-Zeile auf stdin)
# scopes_ausnahmen: die Ausnahmen der Person von der strengen Liste klassischer Scopes (C.2.8), nur mit github=persoenlich
Kopf = namedtuple("Kopf", ("auftrag", "system", "modell", "repo", "zugang", "profil", "github", "scopes_ausnahmen"), defaults=(None, ()))


@dataclass(frozen=True, slots=True)
class ClaudeZugang:
    """Persönlicher Claude-Zugang für einen Lauf: typ oauth | api, wert (Geheimnis!), workspace (nur api), profil. Mit typ haus ist wert
    das Auftragstoken, das der Dispatcher selbst erzeugt (haus_token), nie ein Wert aus der Kopfzeile oder aus geheim.env.
    Der Wert fehlt in der Darstellung (repr=False) und ist weder iterierbar noch in JSON umwandelbar: ein
    versehentliches Protokollieren zeigt ihn nicht."""

    typ: str
    wert: str = field(repr=False)
    workspace: str | None
    profil: str | None


class _Zeitueberschreitung(Exception):
    pass


# ---------------------------------------------------------------- Prüfung der Argumente
def werkzeugkarte():
    return _modul("werkzeugkarte")


def waechter():
    return _modul("dev_guard")


def _modul(name: str):
    if str(WAECHTER) not in sys.path and (WAECHTER / f"{name}.py").is_file():
        sys.path.insert(0, str(WAECHTER))
    return __import__(name)


def abnahme_modul():
    """Die Allowlist der Befehlskriterien (abnahme_befehl.py, Kopie aus voice-core in /opt/wamo/waechter)."""
    return _modul("abnahme_befehl")


def pruefen_modul():
    """Die Prüflogik von pruefen (wamo_job_pruefen.py): in /opt/wamo/waechter installiert, im Repo neben dieser Datei. Wird erst
    gebraucht, wenn der Schalter an ist; fehlt es oder ist es defekt, wirft das Laden (pruefen ist dann nicht verfügbar)."""
    abnahme_modul()  # das Modul importiert die Allowlist; der Pfad zu /opt/wamo/waechter steht danach in sys.path
    geladen = sys.modules.get("wamo_job_pruefen")
    if geladen is not None:
        return geladen
    if (WAECHTER / "wamo_job_pruefen.py").is_file():
        return _modul("wamo_job_pruefen")
    import importlib.util
    spec = importlib.util.spec_from_file_location("wamo_job_pruefen", Path(__file__).resolve().with_name("wamo_job_pruefen.py"))
    modul = importlib.util.module_from_spec(spec)
    sys.modules["wamo_job_pruefen"] = modul
    spec.loader.exec_module(modul)
    return modul


def modul_sha256(name: str) -> str | None:
    """Prüfsumme der Kopie eines Moduls in /opt/wamo/waechter (None, wenn es sie nicht gibt)."""
    try:
        return hashlib.sha256((WAECHTER / f"{name}.py").read_bytes()).hexdigest()
    except OSError:
        return None


def repo_vergleichsname(wert: str) -> str:
    """Vergleichsform eines Repo-Namens: Unicode NFKC, klein (casefold), nur der Teil nach dem letzten Schrägstrich, ohne .git am
    Ende, nur a-z und 0-9. So sind w.a.i.s, W-A-I-S, w_a_i_s, wais und https://github.com/Wamocon/w.a.i.s.git gleich."""
    text = unicodedata.normalize("NFKC", wert).casefold().strip().rstrip("/")
    text = text.rsplit("/", 1)[-1]
    while text.endswith(".git"):
        text = text[:-4]
    return re.sub(r"[^a-z0-9]", "", text)


SELF_REPO_VERGLEICH = frozenset(repo_vergleichsname(n) for n in SELF_REPOS)


def ist_eigenes_repo(wert: object) -> bool:
    """True, wenn wert das eigene Repo benennt: Name, owner/name oder GitHub-Adresse, in jeder Schreibweise und unter jedem Namen aus
    SELF_REPOS. Fail-closed: was kein Text ist, gilt als das eigene Repo. Andere Namen mit demselben Anfang (wamo-extra) sind fremd."""
    if not isinstance(wert, str):
        return True
    return repo_vergleichsname(wert) in SELF_REPO_VERGLEICH


def github_eintrag_ist_eigenes_repo(eintrag: object) -> bool:
    """True, wenn ein Repo-Eintrag einer Antwort von GitHub das eigene Repo ist (ID aus SELF_REPO_IDS oder ein Name aus SELF_REPOS).
    Fail-closed: ein Eintrag ohne lesbaren full_name zählt als das eigene Repo."""
    if not isinstance(eintrag, dict):
        return True
    kennung = eintrag.get("id")
    if isinstance(kennung, int) and not isinstance(kennung, bool) and kennung in SELF_REPO_IDS:
        return True
    return ist_eigenes_repo(eintrag.get("full_name"))


def check_job(value: str) -> str:
    if not JOB_RE.fullmatch(value):
        raise Abgewiesen("Auftrags-ID ungültig")
    return value


def check_project(value: str) -> str:
    if not PROJECT_RE.fullmatch(value) or "--" in value:
        raise Abgewiesen("Projektname ungültig (3 bis 50 Zeichen, a-z, 0-9, Bindestrich)")
    if ist_eigenes_repo(value):
        raise Abgewiesen(WAMO_REPO_GESPERRT)
    return value


def check_art(value: str) -> str:
    if value not in werkzeugkarte().AUFTRAGSARTEN:
        raise Abgewiesen("Auftragsart unbekannt")
    return value


def check_session(value: str) -> str:
    if not SESSION_RE.fullmatch(value):
        raise Abgewiesen("Session-ID ungültig")
    return value


def check_fp(value: str) -> str:
    if not FP_RE.fullmatch(value):
        raise Abgewiesen("Fingerabdruck ungültig")
    return value


def check_profil(value: str) -> str:
    if not PROFIL_RE.fullmatch(value):
        raise Abgewiesen("Profil ungültig (8 Hexzeichen)")
    return value


def check_alle(value: str) -> str:
    if value != "alle":
        raise Abgewiesen("aufraeumen kennt nur das Wort alle")
    return value


BEFEHLE: dict[str, tuple[int, tuple]] = {
    # Befehl: (Pflichtargumente, Prüfer je Position)
    "ping": (0, ()),
    "start": (3, (check_job, check_project, check_art, check_session)),
    "status": (1, (check_job,)),
    "pending": (1, (check_job,)),
    "approve": (2, (check_job, check_fp)),
    "cancel": (1, (check_job,)),
    "pruefen": (1, (check_job,)),  # das Projekt steht nie im Aufruf: es kommt aus auftrag.json
    # persönlicher GitHub-Weg (Dispatcher 10, C.2.3): nur im Kern-Kanal, im Kanal lokal für Rauchtests, im PC-Kanal befehl
    "aenderung": (2, (check_job, check_profil)),
    "einreichen": (2, (check_job, check_profil)),
    "verwerfen": (2, (check_job, check_profil)),
    "aufraeumen": (0, (check_alle,)),  # nur lokal (Timer wamo-job-aufraeumen und wamo-job-rueckweg.sh)
}
BEFEHLE_PERSOENLICH = ("aenderung", "einreichen", "verwerfen")
BEFEHLE_NUR_LOKAL = ("aufraeumen",)


def parse_command(raw: str | None) -> tuple[str, list[str]]:
    """Prüft den Befehl aus SSH_ORIGINAL_COMMAND. Ohne Befehl (interaktive Anmeldung) wird abgewiesen."""
    if not raw:
        raise Abgewiesen("kein Befehl (Shell-Zugang ist mit diesem Schlüssel gesperrt)")
    if len(raw) > MAX_COMMAND_CHARS or not COMMAND_RE.fullmatch(raw):
        raise Abgewiesen("Befehl hat unzulässige Zeichen oder Form")
    name, *args = raw.split(" ")
    spec = BEFEHLE.get(name)
    if spec is None:
        raise Abgewiesen("unbekannter Befehl")
    required, checks = spec
    if not required <= len(args) <= len(checks):
        raise Abgewiesen("falsche Anzahl Argumente")
    return name, [check(arg) for check, arg in zip(checks, args)]


def check_repo(value: object) -> str:
    """Ziel-Repo aus der Kopfzeile: owner/name, streng (REPO_RE, genau ein Schrägstrich, kein . oder .., kein
    .git am Ende). Es begrenzt nur das GitHub-Token; ob es zur Installation gehört, prüft die Antwort von GitHub."""
    if not isinstance(value, str) or len(value) > 140 or not REPO_RE.fullmatch(value) or value.count("/") != 1:
        raise Abgewiesen("Kopfzeile: repo ungültig (Form owner/name, nur A-Z, a-z, 0-9, Punkt, Unterstrich, Bindestrich)")
    name = value.split("/", 1)[1]
    if name in (".", "..") or name.lower().endswith(".git"):
        raise Abgewiesen("Kopfzeile: repo ungültig (Name . oder .. oder mit .git)")
    if ist_eigenes_repo(name):
        raise Abgewiesen(WAMO_REPO_GESPERRT)
    return value


def parse_header(raw: bytes) -> Kopf:
    """Erste stdin-Zeile von start: {"auftrag": str, "system": str, "modell": str (optional), "repo": "owner/name"
    (optional), "zugang": "folgt" | "server" | "haus" (optional), "profil": 8 Hexzeichen (bei folgt und haus Pflicht)}.
    Steuerzeichen außer Zeilenumbruch und Tabulator fliegen heraus; beide Texte sind begrenzt. Das Modell prüft cmd_start
    gegen die Allowlist der Werkzeugkarte (bei haus gegen HAUS_MODELLE), das Repo prüft check_repo. Die Kopfzeile trägt
    nie einen Zugangswert."""
    if not raw.endswith(b"\n") or len(raw) > MAX_HEADER_BYTES:
        raise Abgewiesen("Kopfzeile fehlt oder ist zu lang")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise Abgewiesen("Kopfzeile ist kein JSON") from None
    if not isinstance(data, dict) or set(data) - {"auftrag", "system", "modell", "repo", "zugang", "profil", "github", "scopes_ausnahmen"}:
        raise Abgewiesen("Kopfzeile hat unbekannte Felder")
    modell = data.get("modell")
    if modell is not None and (not isinstance(modell, str) or not MODELL_RE.fullmatch(modell)):
        raise Abgewiesen("Kopfzeile: modell ungültig")
    repo = data.get("repo")
    if repo is not None:
        repo = check_repo(repo)
    zugang, profil = data.get("zugang"), data.get("profil")
    if zugang is not None and zugang not in ZUGANG_MODI:
        raise Abgewiesen("Kopfzeile: zugang ungültig (folgt, server oder haus)")
    if profil is not None and (not isinstance(profil, str) or not PROFIL_RE.fullmatch(profil)):
        raise Abgewiesen("Kopfzeile: profil ungültig")
    if zugang in ("folgt", "haus") and profil is None:  # sonst teilten sich alle Profile eine Kennung in der Buchführung
        raise Abgewiesen(f"Kopfzeile: profil fehlt bei zugang {zugang}")
    github = data.get("github")
    if github is not None:  # persönlicher GitHub-Weg (Plan C, C.2.1): nur im Kern-Kanal, nur mit Repo und Profil
        if github != GITHUB_WEG:
            raise Abgewiesen("Kopfzeile: github ungültig (nur persoenlich)")
        if KANAL != "kern":
            raise Abgewiesen("Kopfzeile: github nur im Kern-Kanal")
        if repo is None or profil is None:
            raise Abgewiesen("Kopfzeile: github braucht repo und profil")
    scopes: tuple[str, ...] = ()
    if "scopes_ausnahmen" in data:  # nur mit github=persoenlich (und damit nur im Kern-Kanal), Werte nur aus SCOPES_AUSNAHMEN
        if github is None:
            raise Abgewiesen("Kopfzeile: scopes_ausnahmen nur mit github")
        scopes = scopes_pruefen(data["scopes_ausnahmen"])
    auftrag, system = data.get("auftrag"), data.get("system", "")
    if not isinstance(auftrag, str) or not isinstance(system, str):
        raise Abgewiesen("Kopfzeile: auftrag und system müssen Text sein")
    if KANAL == "kern" and (_versteckt(auftrag) or _versteckt(system)):
        raise Abgewiesen("Kopfzeile: unsichtbare Zeichen (Unicode-Format-, Tag-, Privat- oder Trennzeichen) sind im Kern-Kanal nicht erlaubt")
    auftrag, system = _clean(auftrag), _clean(system)
    if not auftrag.strip():
        raise Abgewiesen("Auftrag ist leer")
    if len(auftrag) > MAX_TEXT_CHARS or len(system) > MAX_TEXT_CHARS:
        raise Abgewiesen("Auftrag oder Systemtext zu lang")
    return Kopf(auftrag, system, modell or None, repo, zugang, profil, github, scopes)


def parse_zugang(raw: bytes, profil: str | None = None) -> ClaudeZugang:
    """Zweite stdin-Zeile von start (nur bei "zugang": "folgt"): {"typ": "oauth" | "api", "wert": str, "workspace":
    str (nur api, optional)}. Genau diese Felder, Format des Werts streng nach Typ (ZUGANG_FORMAT), eine Zeile bis
    MAX_ZUGANG_BYTES. ZugangUngueltig nennt nie den Inhalt der Zeile, auch nicht in Teilen."""
    if not raw.endswith(b"\n") or len(raw) > MAX_ZUGANG_BYTES:
        raise ZugangUngueltig("Zugangszeile fehlt oder ist zu lang")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ZugangUngueltig("Zugangszeile ist kein JSON") from None
    if not isinstance(data, dict) or set(data) - ZUGANG_FELDER:
        raise ZugangUngueltig("Zugangszeile hat unbekannte Felder")
    typ, wert, workspace = data.get("typ"), data.get("wert"), data.get("workspace")
    if not isinstance(typ, str) or typ not in ZUGANG_FORMAT:
        raise ZugangUngueltig("Zugangszeile: typ ungültig (oauth oder api)")
    if not isinstance(wert, str) or not ZUGANG_FORMAT[typ].fullmatch(wert):
        raise ZugangUngueltig(f"Zugangszeile: wert hat nicht das Format für typ {typ}")
    if workspace is not None and (typ != "api" or not isinstance(workspace, str)
                                  or not WORKSPACE_ZUGANG_RE.fullmatch(workspace)):
        raise ZugangUngueltig("Zugangszeile: workspace ungültig (nur bei api, Form wrkspc_...)")
    return ClaudeZugang(typ, wert, workspace, profil)


def zugang_typ(env: dict[str, str]) -> str:
    """Art des Claude-Zugangs in einer Sandbox-Umgebung: oauth (Abo, Kontingent), api (Guthaben) oder haus (Hausmodell über den
    Proxy, erkennbar an HAUS_URL; die Basis-URL setzt allein sandbox_env, aus geheim.env kommt sie nie)."""
    if env.get("ANTHROPIC_BASE_URL") == HAUS_URL:
        return "haus"
    return "oauth" if env.get("CLAUDE_CODE_OAUTH_TOKEN") else "api"


def haus_modell(wunsch: str | None) -> str:
    """Modell eines Laufs mit Hausmodell: ohne Wunsch HAUS_MODELL, ein Wunsch nur aus HAUS_MODELLE (ValueError sonst). Die Allowlist der
    Werkzeugkarte (Claude-Modelle) gilt hier nicht, ein Hausmodell umgekehrt nie für einen Claude-Zugang."""
    if not wunsch:
        return HAUS_MODELL
    if wunsch not in HAUS_MODELLE:
        raise ValueError(f"Modell {wunsch!r} ist für Hausmodelle nicht erlaubt (erlaubt: {', '.join(HAUS_MODELLE)})")
    return wunsch


def modell_waehlen(art: str, wunsch: str | None, typ: str) -> str:
    """Modell des Laufs. Ein Wunsch (WAMO_ENTWICKLUNG_MODELL, Kopfzeilenfeld modell) gilt nur aus der Allowlist der
    Werkzeugkarte (ValueError sonst). Ohne Wunsch: Abo-Zugang (oauth, Kontingent des Max-Abos) Sonnet, wenn die Art
    nicht ohnehin ein stärkeres Modell festlegt; sonst (api, Guthaben) das Modell der Art, derzeit Haiku. Mit typ haus
    gilt haus_modell."""
    if typ == "haus":
        return haus_modell(wunsch)
    wk = werkzeugkarte()
    modell = wk.modell_fuer(art, wunsch)
    if not wunsch and typ == "oauth" and modell == wk.MODELL_STANDARD:
        return wk.MODELL_SONNET
    return modell


def serverzugang_erlaubt(geheim: dict[str, str]) -> bool:
    """Darf ein Lauf ohne persönlichen Zugang den Claude-Zugang aus geheim.env nutzen? Standard ja (bisheriges Verhalten,
    auch für ältere Kerne ohne Feld zugang); WAMO_SERVERZUGANG=aus schaltet das ab, sobald jedes Profil seinen eigenen
    Zugang hat. Fail-closed: jeder andere Wert als an/ja/1/true/on und jeder Tippfehler im Namen (WAMO_SERVER...) sperrt."""
    if any(n.startswith("WAMO_SERVER") and n != "WAMO_SERVERZUGANG" for n in geheim):
        return False
    return (geheim.get("WAMO_SERVERZUGANG") or "an").strip().lower() in ("an", "ja", "1", "true", "on")


PRUEFEN_SCHALTER = "WAMO_PRUEFEN"


def pruefen_schalter(geheim: dict[str, str]) -> bool:
    """Ist pruefen eingeschaltet? Nur WAMO_PRUEFEN=an in geheim.env schaltet ein (Standard aus); jeder andere Wert und jeder
    Tippfehler im Namen (WAMO_PRUEF...) sperrt. Fail-closed wie serverzugang_erlaubt."""
    if any(n.startswith("WAMO_PRUEF") and n != PRUEFEN_SCHALTER for n in geheim):
        return False
    return geheim.get(PRUEFEN_SCHALTER, "") == "an"


def pruefen_aktiv(geheim: dict[str, str]) -> bool:
    """Schalter an UND beide Module ladbar: nur dann meldet ping pruefen als aktiv."""
    if not pruefen_schalter(geheim):
        return False
    try:
        pruefen_modul()
    except Exception:  # noqa: BLE001 (fehlt oder defekt: nicht aktiv)
        return False
    return True


# ---------------------------------------------------------------- Zugangsart haus: Schalter, Token, Tokendatei für den Proxy
def haus_schalter(geheim: dict[str, str]) -> bool:
    """Ist die Zugangsart haus eingeschaltet? Nur WAMO_HAUS=an in geheim.env (Standard aus). Fail-closed wie pruefen_schalter: jeder
    andere Wert und jeder Name, der mit WAMO_HAU beginnt und weder WAMO_HAUS noch WAMO_HAUS_MAX_TOKEN ist (ein Tippfehler), sperrt."""
    if any(n.startswith("WAMO_HAU") and n not in (HAUS_SCHALTER, HAUS_MAX_TOKEN_NAME) for n in geheim):
        return False
    return geheim.get(HAUS_SCHALTER, "") == "an"


def haus_max_token(geheim: dict[str, str]) -> int:
    """Höchstmenge an Token je Lauf für den Proxy: WAMO_HAUS_MAX_TOKEN aus geheim.env, nur ASCII-Ziffern von HAUS_MAX_TOKEN_MIN bis
    HAUS_MAX_TOKEN_MAX, sonst HAUS_MAX_TOKEN_STANDARD."""
    wert = geheim.get(HAUS_MAX_TOKEN_NAME, "")
    if re.fullmatch(r"[0-9]{1,9}", wert) and HAUS_MAX_TOKEN_MIN <= int(wert) <= HAUS_MAX_TOKEN_MAX:
        return int(wert)
    return HAUS_MAX_TOKEN_STANDARD


def haus_token(job: str) -> str:
    """Neues Auftragstoken für genau einen Lauf: wh1-<job>-<64 Hexzeichen aus secrets>. Es steht nur in der Umgebung der Sandbox und im
    Speicher dieses Prozesses; der Proxy bekommt nur seinen SHA-256 (haus_tokendatei)."""
    return f"wh1-{check_job(job)}-{secrets.token_hex(32)}"


def haus_ordner_problem(ordner: Path | None = None) -> str | None:
    """Warum der Ordner für die Tokendateien nicht taugt, oder None. Er muss ein echter Ordner sein (kein Link), diesem Prozess gehören
    (im Betrieb wamo, angelegt von tmpfiles.d des Proxys) und darf für niemanden außer dem Besitzer beschreibbar sein."""
    ordner = ordner or HAUS_ORDNER
    try:
        st = os.lstat(ordner)
    except OSError:
        return "der Ordner für die Tokendateien des Proxys fehlt (Proxy nicht eingerichtet)"
    if not stat.S_ISDIR(st.st_mode):
        return "der Ordner für die Tokendateien des Proxys ist kein Ordner"
    if hasattr(os, "geteuid") and st.st_uid != os.geteuid():
        return "der Ordner für die Tokendateien des Proxys gehört nicht dem Dispatcher"
    if os.name == "posix" and st.st_mode & 0o022:
        return "der Ordner für die Tokendateien des Proxys ist für andere beschreibbar"
    return None


def haus_problem(geheim: dict[str, str]) -> str | None:
    """Warum ein Lauf mit Hausmodell jetzt nicht starten kann (Schalter, Ordner des Proxys), oder None. Wirft nie."""
    if not haus_schalter(geheim):
        return f"Hausmodelle sind auf diesem Server aus ({HAUS_SCHALTER}=an fehlt in /etc/wamo/geheim.env)"
    return haus_ordner_problem()


def haus_aktiv(geheim: dict[str, str]) -> bool:
    """Schalter an UND Ordner des Proxys bereit: nur dann meldet ping haus als aktiv (wie pruefen)."""
    return haus_problem(geheim) is None


_ZEITLIMIT_ZEILE_RE = re.compile(r"\s*(?:export\s+)?ZEITLIMIT_S=")
_ZEITLIMIT_WERT_RE = re.compile(r"\s*(?:export\s+)?ZEITLIMIT_S=([\"']?)([0-9]{1,6})\1\s*(?:#.*)?")


def lauf_zeitlimit_s(pfad: Path | None = None) -> int:
    """Zeitlimit eines Laufs in Sekunden, wie wamo-job.sh es setzt (der Dispatcher übergibt kein eigenes --zeitlimit): die letzte Zuweisung
    ZEITLIMIT_S in wamo-job.conf, sonst LAUF_ZEITLIMIT_STANDARD_S. Eine Zuweisung, die diese einfache Lesart nicht versteht, ergibt
    LAUF_ZEITLIMIT_MAX_S: die Frist der Tokendatei endet so nie vor dem Lauf."""
    text = read_no_follow(pfad or LAUF_KONF, 64 * 1024)
    wert = LAUF_ZEITLIMIT_STANDARD_S
    for zeile in (text or "").splitlines():
        if _ZEITLIMIT_ZEILE_RE.match(zeile):
            treffer = _ZEITLIMIT_WERT_RE.fullmatch(zeile)
            wert = int(treffer.group(2)) if treffer and int(treffer.group(2)) > 0 else LAUF_ZEITLIMIT_MAX_S
    return wert


def _haus_datei_loeschen(ordner: Path, job: str) -> None:
    try:
        os.unlink(ordner / f"{job}.json")
    except FileNotFoundError:
        pass
    except OSError as e:
        log(f"haus_token {job}: Tokendatei nicht gelöscht ({type(e).__name__}), sie gilt nur bis zu ihrer Frist")


def _haus_datei_schreiben(ordner: Path, job: str, inhalt: bytes) -> None:
    """Atomar: Temp-Datei im selben Ordner (O_EXCL, O_NOFOLLOW, 0640 unabhängig von der umask), fsync, os.replace. Ein Link an der Stelle
    der Zieldatei wird ersetzt, nie verfolgt. Bei einem Fehler bleibt keine Temp-Datei liegen."""
    tmp = ordner / f".{job}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(tmp, flags, HAUS_DATEI_MODUS)
    try:
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, HAUS_DATEI_MODUS)
            rest = memoryview(inhalt)
            while rest:
                rest = rest[os.write(fd, rest):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, ordner / f"{job}.json")
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def haus_alte_dateien_loeschen(ordner: Path, eigener_job: str, jetzt: float | None = None, hoechstens: int = 200) -> int:
    """Löscht abgelaufene Tokendateien (bis vor jetzt) früherer Läufe, etwa nach einem SIGKILL des Dispatchers. Nur Dateien der Form
    <job>.json, nie die des laufenden Auftrags, höchstens hoechstens Dateien je Aufruf; dazu liegengebliebene Temp-Dateien (.<job>.<hex>.tmp)
    älter als eine Stunde. Unlesbares bleibt liegen (der Proxy weist es ohnehin ab). Liefert die Zahl der gelöschten Dateien; wirft nie."""
    jetzt = time.time() if jetzt is None else jetzt
    geloescht = 0
    try:
        alle = sorted(os.listdir(ordner))
    except OSError:
        return 0
    for name in [n for n in alle if n.startswith(".") and n.endswith(".tmp")][:hoechstens]:
        try:
            if os.lstat(ordner / name).st_mtime < jetzt - 3600:
                os.unlink(ordner / name)
                geloescht += 1
        except OSError:
            pass
    namen = [n for n in alle if n.endswith(".json") and JOB_RE.fullmatch(n[:-5]) and n[:-5] != eigener_job][:hoechstens]
    for name in namen:
        inhalt = read_no_follow(ordner / name, 4096)
        try:
            bis = json.loads(inhalt or "").get("bis")
        except (ValueError, AttributeError):
            continue
        if type(bis) is int and bis < jetzt:
            try:
                os.unlink(ordner / name)
                geloescht += 1
            except OSError:
                pass
    if geloescht:
        log(f"haus_token: {geloescht} abgelaufene Tokendateien gelöscht")
    return geloescht


@contextmanager
def haus_tokendatei(job: str, token: str, profil: str, max_token: int, zeitlimit_s: int, ordner: Path | None = None):
    """Legt für die Dauer des Blocks HAUS_ORDNER/<job>.json für den Proxy an, genau {"v": 1, "job", "hash" (SHA-256 des Tokens als Hex),
    "profil", "bis" (Start plus Zeitlimit des Laufs plus HAUS_NACHLAUF_S, Unix-Sekunden), "max_token"}; nie das Token selbst. Die Datei
    verschwindet nach dem Block, auch bei Ausnahme, Abbruch oder Signal. Während des Schreibens sind SIGTERM und SIGHUP aufgeschoben (keine
    Datei ohne Löschen), während des Löschens ignoriert. HausNichtBereit, bevor etwas startet: Ordner fehlt oder ist nicht sicher, Schreiben
    scheitert. Gegen SIGKILL hilft nur die Frist bis: danach weist der Proxy das Token ab."""
    ordner = ordner or HAUS_ORDNER
    grund = haus_ordner_problem(ordner)
    if grund is not None:
        raise HausNichtBereit(grund)
    haus_alte_dateien_loeschen(ordner, job)
    bis = int(time.time()) + int(zeitlimit_s) + HAUS_NACHLAUF_S
    inhalt = json.dumps({"v": 1, "job": check_job(job), "hash": hashlib.sha256(token.encode("utf-8")).hexdigest(), "profil": profil,
                         "bis": bis, "max_token": int(max_token)}).encode("utf-8")
    maske = _signale_aufschieben()
    try:
        _haus_datei_schreiben(ordner, job, inhalt)
    except OSError as e:
        _haus_datei_loeschen(ordner, job)  # eine alte Datei desselben Auftrags bleibt nicht stehen
        _signale_zulassen(maske)
        raise HausNichtBereit(f"die Tokendatei für den Proxy lässt sich nicht schreiben ({type(e).__name__})") from None
    except BaseException:
        _haus_datei_loeschen(ordner, job)  # auch nach einem Abbruch zwischen os.replace und hier bleibt keine Datei stehen
        _signale_zulassen(maske)
        raise
    try:
        _signale_zulassen(maske)  # ein aufgeschobenes Signal kommt jetzt an und endet im finally (Datei weg)
        log(f"haus_token {job} profil={profil} bis={bis} max_token={int(max_token)}", pflicht=True)
        yield
    finally:
        for _versuch in range(2):  # ein erstes Signal genau jetzt (_Beendet) überspringt das Löschen nicht
            try:
                with _signale(signal.SIG_IGN):
                    _haus_datei_loeschen(ordner, job)
                break
            except _Beendet:
                continue


def haus_lauf(job: str, zugang: "ClaudeZugang | None", geheim: dict[str, str]):
    """Die Tokendatei für einen Lauf mit Hausmodell; für jede andere Zugangsart ein leerer Block."""
    if zugang is None or zugang.typ != "haus":
        return nullcontext()
    return haus_tokendatei(job, zugang.wert, zugang.profil or "", haus_max_token(geheim), lauf_zeitlimit_s())


# Unsichtbare Zeichen können eine Zusatzanweisung an Claude Code tragen, die niemand liest. Zwei Stufen:
#  1. _clean (jeder Kanal, auch die Statustexte) entfernt nur die gefährlichen: Tag-Zeichen (U+E0000 bis U+E007F), Bidi-Steuerzeichen
#     (U+202A bis U+202E, U+2066 bis U+2069, U+200E, U+200F, U+061C), U+200B, U+2060 bis U+2064, U+206A bis U+206F, U+180E, U+FEFF, Privatbereich (Co),
#     Surrogate (Cs), Zeilen- und Absatztrenner (Zl, Zp) und Steuerzeichen (Cc). ZWJ (U+200D), ZWNJ (U+200C), Variationsselektoren und das weiche
#     Trennzeichen bleiben, sonst zerfallen Emoji-Sequenzen (Familie, Flaggen, Herz) und persische oder indische Schrift.
#  2. _versteckt (nur der Kern-Kanal) lehnt jedes Format-, Privat-, Trenn-, Tag-Zeichen und jeden Variationsselektor ab, auch ZWJ und ZWNJ.
UNSICHTBAR_KATEGORIEN = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})  # streng (Kern-Kanal)
GEFAEHRLICH_KATEGORIEN = frozenset({"Cc", "Cs", "Co", "Zl", "Zp"})
GEFAEHRLICH_ZEICHEN = frozenset(
    {0x061C, 0x180E, 0x200B, 0x200E, 0x200F, 0x2060, 0xFEFF}
    | set(range(0x202A, 0x202F)) | set(range(0x2061, 0x2065)) | set(range(0x2066, 0x206A)) | set(range(0x206A, 0x2070))
    | set(range(0xE0000, 0xE0080)))


def _unsichtbar(c: str) -> bool:
    """Streng (Kern-Kanal): jedes unsichtbare Zeichen, auch ZWJ, ZWNJ, Variationsselektoren und nicht zugewiesene Zeichen."""
    n = ord(c)
    return unicodedata.category(c) in UNSICHTBAR_KATEGORIEN or 0xFE00 <= n <= 0xFE0F or 0xE0000 <= n <= 0xE01EF


def _gefaehrlich(c: str) -> bool:
    """Mild (alle Kanäle): nur die gefährlichen unsichtbaren Zeichen. Nicht zugewiesene Zeichen bleiben, sie können neue Emojis sein."""
    return unicodedata.category(c) in GEFAEHRLICH_KATEGORIEN or ord(c) in GEFAEHRLICH_ZEICHEN


def _clean(text: str) -> str:
    """Entfernt die gefährlichen unsichtbaren Zeichen (siehe oben), erhalten bleiben Zeilenumbruch, Tabulator, ZWJ, ZWNJ und Variationsselektoren.
    Gilt für jeden Kanal."""
    return "".join(c for c in text if c in "\n\t" or not _gefaehrlich(c))


def _versteckt(text: str) -> bool:
    """Enthält der Text ein unsichtbares Zeichen, das mehr ist als ein gewöhnliches Steuerzeichen unter 32 oder DEL? Der Kern bereinigt selbst:
    kommt so etwas im Kern-Kanal an, ist es keine Panne, sondern ein Versuch, eine unsichtbare Anweisung einzuschleusen."""
    return any(_unsichtbar(c) and not (ord(c) < 32 or ord(c) == 127) for c in text)


# ---------------------------------------------------------------- Geheimnisse und Umgebung
def lese_geheimnisse(path: Path | None = None) -> dict[str, str]:
    """KEY=VALUE aus /etc/wamo/geheim.env (Kommentare, export und Anführungszeichen erlaubt).
    Leere Werte zählen als nicht gesetzt. Werte werden nie protokolliert."""
    try:
        text = (path or GEHEIM).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, value = (part.strip() for part in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if ENV_NAME_RE.fullmatch(name) and value:
            out[name] = value
    return out


GIT_OHNE_HOOKS = (("core.hooksPath", "/dev/null"), ("core.fsmonitor", "false"))


def basis_env() -> dict[str, str]:
    """Umgebung für wamo-job.sh ohne Token (systemd-run --user braucht den Laufzeitordner)."""
    uid = os.getuid() if hasattr(os, "getuid") else 0
    return {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "XDG_RUNTIME_DIR": f"/run/user/{uid}",
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus"}


def _github_variablen() -> set[str]:
    """Persönliche GitHub-Token aus geheim.env (GH_TOKEN, GH_TOKEN_LESEN); im App-Modus nie in der Sandbox."""
    wk = werkzeugkarte()
    return {*wk.ZUGANG_VARIABLEN["github"], *wk.ZUGANG_VARIABLEN["github_lesen"]}


def zugangs_quellen(art: str, geheim: dict[str, str], app_modus: bool = False, repo: str | None = None,
                    zugang: ClaudeZugang | None = None, persoenlich: bool = False) -> set[str]:
    """Namen in geheim.env, deren Werte ein Lauf dieser Art bekommt (für die Buchführung je Projekt). Im
    App-Modus steht statt GH_TOKEN bzw. GH_TOKEN_LESEN der Name GH_APP_SCHREIBEN bzw. GH_APP_LESEN, mit dem
    Umfang des Tokens: "@owner/name" (kleingeschrieben) für ein Repo, "@*" für die ganze Installation. Ein anderes
    oder breiteres Repo als in früheren Läufen des Projekts zählt so als neuer Zugang und braucht eine Freigabe.
    Ein persönlicher Claude-Zugang heißt <Variable>@<Profil> (nie der Wert): der Zugang einer anderen Person, auch
    der aus geheim.env, ist für ein Projekt ein neuer Zugang. Ein Lauf mit Hausmodell heißt HAUS@<Profil>. Im persönlichen GitHub-Weg
    (persoenlich) bekommt die Sandbox kein Token aus geheim.env und keins von GitHub: es zählt nur der Claude-Zugang."""
    wk = werkzeugkarte()
    if zugang is not None and zugang.typ == "haus":
        claude = f"HAUS@{zugang.profil or '?'}"
    elif zugang is not None:
        claude = f"{ZUGANG_VARIABLE[zugang.typ]}@{zugang.profil or '?'}"
    else:
        claude = next((name for name in wk.CLAUDE_VARIABLEN if geheim.get(name)), None)
    if persoenlich:
        return {claude} if claude else set()
    namen = {n for n in wk.zugangs_variablen(art) if geheim.get(n)}
    if app_modus:
        namen -= _github_variablen()
        stufe = wk.github_stufe(art)
        if stufe:
            namen.add(f"{GH_APP_QUELLE[stufe]}@{repo.lower() if repo else '*'}")
    return ({claude} if claude else set()) | namen


def sandbox_env(art: str, geheim: dict[str, str], app_modus: bool = False,
                gh_token: str | None = None, zugang: ClaudeZugang | None = None, modell: str | None = None,
                persoenlich: "PersoenlicherLauf | None" = None) -> dict[str, str] | None:
    """Basis plus genau ein Claude-Zugang und die Token der Auftragsart. None ohne Claude-Zugang. Im App-Modus
    kommt GitHub nur als gh_token (kurzlebiges Installations-Token dieses Laufs) an, nie GH_TOKEN oder
    GH_TOKEN_LESEN aus geheim.env; die App-Variablen (WAMO_GH_APP_*) gelangen nie in die Umgebung.
    Mit einem persönlichen Zugang (zugang) ist das der einzige Claude-Zugang des Laufs: nichts davon kommt aus
    geheim.env, auch nicht der Workspace-Header des Organisationsschlüssels (kein Mischen mit einem fremden Schlüssel).
    Mit zugang.typ haus: Basis-URL des Proxys, das Auftragstoken als ANTHROPIC_API_KEY, jede Modellklasse auf das
    Hausmodell (modell, nur aus HAUS_MODELLE, sonst HAUS_MODELL) und kein Verkehr nebenbei; kein Claude-Zugang, kein
    Workspace und kein Schlüssel für LiteLLM. modell gilt nur für haus.
    Mit persoenlich (persönlicher GitHub-Weg, Plan C): kein GH_TOKEN und kein Dienst-Token der Art aus geheim.env, dafür genau die
    sechs Namen PERSOENLICH_VARIABLEN (Autor und Committer aus der Antwort von GitHub, nie vom Kern, Weg und Zweig des Auftrags)."""
    wk = werkzeugkarte()
    env = basis_env()
    if zugang is not None and zugang.typ == "haus":
        env["ANTHROPIC_BASE_URL"] = HAUS_URL
        env["ANTHROPIC_API_KEY"] = zugang.wert
        for name in HAUS_MODELL_VARIABLEN:
            env[name] = haus_modell(modell)
        for name in ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING"):
            env[name] = "1"  # kein Verkehr nebenbei zu Anthropic (Telemetrie, Fehlerberichte, Aktualisierung)
    elif zugang is not None:
        env[ZUGANG_VARIABLE[zugang.typ]] = zugang.wert
        if zugang.typ == "api" and zugang.workspace:
            env["ANTHROPIC_CUSTOM_HEADERS"] = f"anthropic-workspace-id: {zugang.workspace}"
    else:
        claude = next((name for name in wk.CLAUDE_VARIABLEN if geheim.get(name)), None)
        if claude is None:
            return None
        env[claude] = geheim[claude]
        workspace = geheim.get("ANTHROPIC_WORKSPACE_ID", "")
        if claude == "ANTHROPIC_API_KEY" and WORKSPACE_RE.fullmatch(workspace):
            # Organisationsschlüssel ohne festen Workspace: Claude Code schickt den Header bei jeder Anfrage mit
            env["ANTHROPIC_CUSTOM_HEADERS"] = f"anthropic-workspace-id: {workspace}"
    if persoenlich is not None:
        env.update(persoenlich.umgebung())
    else:
        gh_variablen = _github_variablen()
        for name in wk.zugangs_variablen(art):
            if app_modus and name in gh_variablen:
                continue
            if geheim.get(name):
                env[wk.sandbox_name(name)] = geheim[name]
        if app_modus and gh_token and wk.github_stufe(art):
            env["GH_TOKEN"] = gh_token
    # Git in jedem Repo der Sandbox: keine Hooks und kein fsmonitor (Vorrang vor Repo-Konfigurationen, auch in
    # Submodulen und eingebetteten Repos, die die Entschärfung vor dem Lauf nicht erreicht)
    git = list(GIT_OHNE_HOOKS)
    if "GH_TOKEN" in env:
        # git über HTTPS meldet sich mit dem Token an (gh liest GH_TOKEN selbst); keine Datei nötig
        git += [("credential.https://github.com.helper", ""),
                ("credential.https://github.com.helper", "!/usr/bin/gh auth git-credential")]
    env["GIT_CONFIG_COUNT"] = str(len(git))
    for i, (key, value) in enumerate(git):
        env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"] = key, value
    return env


# ---------------------------------------------------------------- GitHub-App: kurzlebige Token je Lauf
GH_APP_ID = "WAMO_GH_APP_ID"
GH_APP_INSTALLATION = "WAMO_GH_APP_INSTALLATION_ID"
GH_APP_SCHLUESSEL = "WAMO_GH_APP_SCHLUESSEL"
GH_APP_VARIABLEN = (GH_APP_ID, GH_APP_INSTALLATION, GH_APP_SCHLUESSEL)
GH_APP_QUELLE = {"lesen": "GH_APP_LESEN", "schreiben": "GH_APP_SCHREIBEN"}  # Namen für die Buchführung je Projekt
# Der private Schlüssel liegt direkt in /etc/wamo (root:wamo 0750, in der Sandbox unsichtbar; der Selbsttest prüft
# das bei jedem Lauf). Erlaubt sind nur Dateien root:<gruppe>, nicht gruppen- oder weltschreibbar, nicht weltlesbar.
SCHLUESSEL_ORDNER = Path("/etc/wamo")
SCHLUESSEL_BESITZER: tuple[int, ...] = (0,)
SCHLUESSEL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
MAX_SCHLUESSEL_BYTES = 16 * 1024
MIN_RSA_BITS = 2048
APP_ID_RE = re.compile(r"[1-9][0-9]{0,11}")
INSTALLATION_RE = re.compile(r"[1-9][0-9]{0,15}")
# Form des Installations-Tokens: ghs_ plus Zeichen, die als Header und Umgebungswert unbedenklich sind. Echte Token
# sind rund 390 Zeichen lang und enthalten Punkte (Stand 21.10.2026), deshalb Obergrenze 1000 statt 255.
TOKEN_RE = re.compile(r"ghs_[A-Za-z0-9_.-]{16,1000}")
TOKEN_ZEICHEN_RE = re.compile(r"[\x21-\x7e]{1,2000}")  # darf zum Widerruf als Bearer-Header dienen
GITHUB_API_HOST = "api.github.com"
GITHUB_API_VERSION = "2022-11-28"
GITHUB_ZEITLIMIT_S = 15
MAX_GITHUB_ANTWORT = 256 * 1024
JWT_RUECKDATIERT_S = 60  # iat eine Minute zurück (Uhrabweichung)
JWT_GUELTIG_S = 9 * 60   # exp höchstens 9 Minuten nach jetzt (GitHub erlaubt bis 10)
STUFEN_RANG = {"read": 1, "write": 2}


class GithubAppFehler(Exception):
    """Token der GitHub-App nicht erzeugbar oder Konfiguration kaputt. Die Meldung enthält nie Schlüssel oder Token."""


class _Beendet(BaseException):
    """SIGTERM oder SIGHUP während eines Laufs: Sandbox stoppen, Token widerrufen, dann enden."""


# App-Konfiguration: App-ID, Installation-ID, Dateiname des Schlüssels in SCHLUESSEL_ORDNER
GithubApp = namedtuple("GithubApp", ("app_id", "installation_id", "schluessel_name"))


def github_app_konfig(geheim: dict[str, str]) -> GithubApp | None:
    """App-Modus aus geheim.env. None, wenn keine der drei Variablen gesetzt ist (Rückfall auf GH_TOKEN bzw.
    GH_TOKEN_LESEN). Ist nur ein Teil gesetzt oder ein Wert ungültig, GithubAppFehler: wer den App-Modus
    einrichtet, bekommt bei einem Fehler keinen stillen Rückfall auf den persönlichen Token (fail-closed)."""
    unbekannt = sorted(n for n in geheim if n.startswith("WAMO_GH_") and n not in GH_APP_VARIABLEN)
    if unbekannt:  # Tippfehler im Namen schaltet den App-Modus sonst still aus (Rückfall auf den persönlichen Token)
        raise GithubAppFehler(f"unbekannte Einstellung {', '.join(unbekannt)[:120]} (Tippfehler im Namen?)")
    gesetzt = [n for n in GH_APP_VARIABLEN if geheim.get(n)]
    if not gesetzt:
        return None
    fehlt = [n for n in GH_APP_VARIABLEN if n not in gesetzt]
    if fehlt:
        raise GithubAppFehler(f"Konfiguration unvollständig, es fehlt {', '.join(fehlt)}")
    app_id, installation, pfad = (geheim[n].strip() for n in GH_APP_VARIABLEN)
    if not APP_ID_RE.fullmatch(app_id):
        raise GithubAppFehler(f"{GH_APP_ID} ist keine App-ID (nur Ziffern)")
    if not INSTALLATION_RE.fullmatch(installation):
        raise GithubAppFehler(f"{GH_APP_INSTALLATION} ist keine Installation-ID (nur Ziffern)")
    ordner, _, name = pfad.rpartition("/")
    if ordner != SCHLUESSEL_ORDNER.as_posix().rstrip("/") or not SCHLUESSEL_NAME_RE.fullmatch(name):
        raise GithubAppFehler(f"{GH_APP_SCHLUESSEL} muss eine Datei direkt in {SCHLUESSEL_ORDNER.as_posix()} sein "
                              f"(z. B. {SCHLUESSEL_ORDNER.as_posix()}/gh-app.pem)")
    return GithubApp(app_id, installation, name)


def _rechte_grund(st: os.stat_result, was: str, datei: bool) -> str | None:
    """Grund, warum Besitz oder Rechte von Schlüsseldatei bzw. -ordner nicht passen, oder None."""
    if datei and not stat.S_ISREG(st.st_mode):
        return f"{was} ist keine reguläre Datei"
    if not datei and not stat.S_ISDIR(st.st_mode):
        return f"{was} ist kein Ordner"
    if st.st_uid not in SCHLUESSEL_BESITZER:
        return f"{was} gehört nicht root"
    if st.st_mode & 0o022:
        return f"{was} ist für Gruppe oder alle beschreibbar"
    if st.st_mode & 0o007:
        return f"{was} ist für alle zugänglich (chmod o= nötig)"
    return None


def schluessel_lesen(name: str) -> bytearray:
    """Liest den privaten Schlüssel der App, nur im Dispatcher-Prozess: Ordner und Datei ohne Links (O_NOFOLLOW,
    Datei relativ zum geöffneten Ordner), ohne an einer FIFO zu hängen, mit Besitzer- und Rechteprüfung auf dem
    geöffneten Deskriptor und Größenlimit. Der Inhalt landet nie im Log, in argv oder in der Sandbox; der Aufrufer
    überschreibt den Puffer nach Gebrauch (nur best effort, Python-Kopien bleiben bis zur Speicherbereinigung)."""
    if not SCHLUESSEL_NAME_RE.fullmatch(name):
        raise GithubAppFehler("Name der Schlüsseldatei ungültig")
    flags = os.O_RDONLY | O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    ordner_fd = fd = None
    try:
        try:
            if O_DIRECTORY and os.open in os.supports_dir_fd:
                ordner_fd = os.open(SCHLUESSEL_ORDNER, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
                ordner_st = os.fstat(ordner_fd)
            else:  # nur ohne dir_fd (Windows, Tests)
                ordner_st = os.stat(SCHLUESSEL_ORDNER)
        except OSError as e:
            raise GithubAppFehler(f"Schlüsselordner nicht lesbar ({errno.errorcode.get(e.errno, 'Fehler')})") from None
        grund = _rechte_grund(ordner_st, "Schlüsselordner", datei=False)
        if grund:
            raise GithubAppFehler(grund)
        try:
            fd = os.open(name, flags, dir_fd=ordner_fd) if ordner_fd is not None else os.open(SCHLUESSEL_ORDNER / name, flags)
            st = os.fstat(fd)
        except OSError as e:
            raise GithubAppFehler(f"Schlüsseldatei nicht lesbar ({errno.errorcode.get(e.errno, 'Fehler')}; "
                                  "fehlt sie oder ist sie ein Link?)") from None
        grund = _rechte_grund(st, "Schlüsseldatei", datei=True)
        if grund:
            raise GithubAppFehler(grund)
        if st.st_size > MAX_SCHLUESSEL_BYTES:
            raise GithubAppFehler("Schlüsseldatei ist zu groß für einen privaten Schlüssel")
        daten = bytearray()
        while len(daten) <= MAX_SCHLUESSEL_BYTES:
            teil = os.read(fd, MAX_SCHLUESSEL_BYTES + 1 - len(daten))
            if not teil:
                break
            daten += teil
        if len(daten) > MAX_SCHLUESSEL_BYTES:
            daten[:] = bytes(len(daten))
            raise GithubAppFehler("Schlüsseldatei ist zu groß für einen privaten Schlüssel")
        return daten
    finally:
        for f in (fd, ordner_fd):
            if f is not None:
                os.close(f)


def _rsa_schluessel(pem: bytes):
    """Privater RSA-Schlüssel aus PEM (ohne Passwort, mindestens 2048 Bit) über das Systempaket cryptography."""
    try:
        from cryptography.exceptions import UnsupportedAlgorithm
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        raise GithubAppFehler("Python-Paket cryptography fehlt (python3-cryptography)") from None
    if not pem.lstrip().startswith(b"-----BEGIN "):
        raise GithubAppFehler("Schlüsseldatei ist kein PEM-Schlüssel")
    try:
        schluessel = serialization.load_pem_private_key(pem, password=None)
    except (ValueError, TypeError, UnsupportedAlgorithm):
        raise GithubAppFehler("Schlüsseldatei ist kein lesbarer privater Schlüssel ohne Passwort") from None
    if not isinstance(schluessel, rsa.RSAPrivateKey) or schluessel.key_size < MIN_RSA_BITS:
        raise GithubAppFehler(f"Schlüssel ist kein RSA-Schlüssel mit mindestens {MIN_RSA_BITS} Bit")
    return schluessel


def _b64url(daten: bytes) -> str:
    return base64.urlsafe_b64encode(daten).rstrip(b"=").decode("ascii")


def jwt_erzeugen(app_id: str, pem: bytes, jetzt: float | None = None) -> str:
    """JWT für die App (RS256): iat eine Minute zurück, exp höchstens 9 Minuten voraus, iss = App-ID."""
    if not APP_ID_RE.fullmatch(app_id):
        raise GithubAppFehler("App-ID ungültig")
    schluessel = _rsa_schluessel(pem)  # meldet ein fehlendes cryptography als GithubAppFehler
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    t = int(time.time() if jetzt is None else jetzt)
    kopf = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    inhalt = _b64url(json.dumps({"iat": t - JWT_RUECKDATIERT_S, "exp": t + JWT_GUELTIG_S, "iss": app_id},
                                separators=(",", ":")).encode())
    signatur = schluessel.sign(f"{kopf}.{inhalt}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{kopf}.{inhalt}.{_b64url(signatur)}"


def _https(methode: str, pfad: str, kopf: dict[str, str], koerper: bytes | None = None) -> tuple[int, bytes]:
    """Eine HTTPS-Anfrage an api.github.com: Zertifikat und Hostname geprüft (Systemspeicher), mindestens TLS 1.2,
    Zeitlimit, kein Proxy aus der Umgebung, keine Weiterleitung (http.client folgt keiner; ein Token geht so nie
    an einen anderen Host). Antwort höchstens MAX_GITHUB_ANTWORT + 1 Bytes."""
    kontext = ssl.create_default_context()
    kontext.minimum_version = ssl.TLSVersion.TLSv1_2
    verbindung = http.client.HTTPSConnection(GITHUB_API_HOST, 443, timeout=GITHUB_ZEITLIMIT_S, context=kontext)
    try:
        verbindung.request(methode, pfad, body=koerper, headers=kopf)
        antwort = verbindung.getresponse()
        return antwort.status, antwort.read(MAX_GITHUB_ANTWORT + 1)
    finally:
        verbindung.close()


def _github(methode: str, pfad: str, anmeldung: str, koerper: dict | None = None) -> tuple[int, object]:
    """Anfrage an die GitHub-API mit Bearer-Anmeldung (JWT oder Token); Fehler als GithubAppFehler ohne Geheimnisse."""
    kopf = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {anmeldung}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION, "User-Agent": "wamo-job-dispatch"}
    daten = None
    if koerper is not None:
        daten = json.dumps(koerper).encode("utf-8")
        kopf["Content-Type"] = "application/json"
    try:
        status, roh = _https(methode, pfad, kopf, daten)
    except (OSError, http.client.HTTPException, ValueError) as e:
        raise GithubAppFehler(f"GitHub nicht erreichbar ({type(e).__name__})") from None
    if len(roh) > MAX_GITHUB_ANTWORT:
        raise GithubAppFehler("Antwort von GitHub zu groß")
    try:
        obj = json.loads(roh) if roh else None
    except (ValueError, RecursionError):
        obj = None
    return status, obj


def _github_meldung(status: int, obj: object) -> str:
    text = obj.get("message") if isinstance(obj, dict) else None
    text = _clean(str(text)).replace("\n", " ").replace("\t", " ")[:160] if text else ""
    hinweis = {401: "JWT abgelehnt (App-ID, Schlüssel oder Uhrzeit prüfen)",
               403: "keine Berechtigung für diese Installation",
               404: "Installation nicht gefunden (Installation-ID prüfen)",
               422: "Repo oder Rechte nicht in der Installation (Repo freigegeben? Rechte der App gesetzt?)"}.get(status, "")
    return f"GitHub antwortet {status}" + (f": {hinweis}" if hinweis else "") + (f" ({text})" if text else "")


def _antwort_pruefen(obj: dict, rechte: dict[str, str], repo: str | None) -> str | None:
    """Prüft die Token-Antwort: nie mehr Rechte als angefragt, mit Repo genau dieses eine Repo (Owner inklusive)."""
    erhalten = obj.get("permissions")
    if not isinstance(erhalten, dict):
        return "Antwort von GitHub ohne Rechteangabe"
    for bereich, stufe in erhalten.items():
        if bereich not in rechte or not isinstance(stufe, str) \
                or STUFEN_RANG.get(stufe, 99) > STUFEN_RANG[rechte[bereich]]:
            return f"GitHub vergab mehr Rechte als angefragt ({_clean(str(bereich))[:40]})"
    repos = obj.get("repositories")
    eintraege = repos if isinstance(repos, list) else []
    namen = [r.get("full_name") for r in eintraege if isinstance(r, dict)]
    if repo:
        if len(eintraege) != 1 or len(namen) != 1 or not isinstance(namen[0], str) or namen[0].lower() != repo.lower():
            return f"Token gilt nicht genau für {repo} (gehört das Repo zur Installation?)"
        if github_eintrag_ist_eigenes_repo(eintraege[0]):  # die ID bleibt bei einer Umbenennung gleich
            return "Das Token gilt für das WAMO-Repo (für Aufträge gesperrt)"
        return None
    # Ohne Ziel-Repo gilt das Token für die ganze Installation: sie muss auf ausgewählte Repos beschränkt sein, und
    # das WAMO-Repo selbst (für Aufträge gesperrt) darf nicht dazugehören, unter keinem Namen und mit seiner ID nicht
    if obj.get("repository_selection") != "selected":
        return "Installation ist nicht auf ausgewählte Repos beschränkt (Only select repositories einstellen)"
    if any(github_eintrag_ist_eigenes_repo(r) for r in eintraege):
        return "Das WAMO-Repo gehört zur Installation (aus der Auswahl der App entfernen)"
    return None


MAX_REPO_SEITEN = 5  # 500 Repos; mehr gelten als nicht prüfbar


def _repos_der_installation(token: str) -> list[object]:
    """Einträge (wie von GitHub, mit full_name und id) aller Repos, die das Token sieht. GithubAppFehler, wenn die Liste nicht
    lesbar ist. Die Einträge werden nicht gefiltert: einen unlesbaren wertet github_eintrag_ist_eigenes_repo als das eigene Repo."""
    eintraege: list[object] = []
    for seite in range(1, MAX_REPO_SEITEN + 1):
        status, obj = _github("GET", f"/installation/repositories?per_page=100&page={seite}", token)
        repos = obj.get("repositories") if isinstance(obj, dict) else None
        if status != 200 or not isinstance(repos, list):
            raise GithubAppFehler(f"Repos der Installation nicht lesbar (GitHub antwortet {status})")
        eintraege += repos
        if len(repos) < 100:
            return eintraege
    raise GithubAppFehler(f"Installation hat mehr als {MAX_REPO_SEITEN * 100} Repos, die Prüfung auf das WAMO-Repo "
                          "ist nicht möglich")


def installations_token(app: GithubApp, art: str, repo: str | None) -> tuple[str, str]:
    """Holt ein Installations-Token mit den Rechten der Art (Werkzeugkarte) und, falls bekannt, nur für das Ziel-Repo.
    Liefert (token, ablauf). Passt die Antwort nicht, wird das Token sofort widerrufen und GithubAppFehler geworfen."""
    try:
        rechte = werkzeugkarte().github_app_rechte(art)
    except (KeyError, ValueError) as e:
        raise GithubAppFehler(f"Werkzeugkarte: {e}") from None
    if rechte is None:
        raise GithubAppFehler("Auftragsart ohne GitHub-Zugang")
    koerper: dict = {"permissions": rechte}
    if repo:
        koerper["repositories"] = [repo.split("/", 1)[1]]
    pem = schluessel_lesen(app.schluessel_name)
    try:
        jwt = jwt_erzeugen(app.app_id, bytes(pem))
    finally:
        pem[:] = bytes(len(pem))
    status, obj = _github("POST", f"/app/installations/{app.installation_id}/access_tokens", jwt, koerper)
    del jwt
    if status != 201 or not isinstance(obj, dict):
        raise GithubAppFehler(_github_meldung(status, obj))
    token = obj.get("token")
    try:  # ab hier existiert ein Token bei GitHub: jeder Fehler, auch ein unerwarteter, widerruft es
        if not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
            raise GithubAppFehler("Antwort von GitHub ohne gültiges Token")
        grund = _antwort_pruefen(obj, rechte, repo)
        if grund:
            raise GithubAppFehler(grund)
        if not repo and any(github_eintrag_ist_eigenes_repo(e) for e in _repos_der_installation(token)):
            # die Antwort zählt die Repos nicht auf: erst die Liste der Installation zeigt, ob das WAMO-Repo dabei ist (Name oder ID)
            raise GithubAppFehler("Das WAMO-Repo gehört zur Installation (aus der Auswahl der App entfernen)")
        ablauf = obj.get("expires_at")
        ablauf = ablauf if isinstance(ablauf, str) and re.fullmatch(r"[0-9TZ:.+-]{10,40}", ablauf) else "?"
        return token, ablauf
    except BaseException:
        if isinstance(token, str) and TOKEN_ZEICHEN_RE.fullmatch(token) and not token_widerrufen(token):
            log("gh_app_widerruf FEHLGESCHLAGEN (abgelehntes Token, läuft spätestens nach einer Stunde ab)")
            wamo_event("gh_widerruf_fehlgeschlagen", grund="Ein abgelehntes GitHub-Token konnte nicht widerrufen "
                       "werden; es läuft spätestens nach einer Stunde ab")
        raise


WIDERRUF_PAUSEN_S = (1.0, 3.0)  # Pausen vor dem zweiten und dritten Versuch


def token_widerrufen(token: str) -> bool:
    """DELETE /installation/token mit dem Token selbst. True bei 204 (oder 401: schon ungültig). Bis zu drei
    Versuche mit kurzen Pausen bei Netzfehlern, Serverfehlern (5xx) und Ratenbegrenzung (403, 429)."""
    for versuch in range(len(WIDERRUF_PAUSEN_S) + 1):
        if versuch:
            time.sleep(WIDERRUF_PAUSEN_S[versuch - 1])
        try:
            status, _obj = _github("DELETE", "/installation/token", token)
        except GithubAppFehler:
            continue
        if status in (204, 401):
            return True
        if status < 500 and status not in (403, 429):
            return False
    return False


@contextmanager
def _signale(handler):
    """Setzt für SIGTERM und SIGHUP vorübergehend handler (nur im Hauptthread, wo es die Signale gibt)."""
    namen = [s for s in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGHUP", None)) if s is not None]
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    alt = {s: signal.signal(s, handler) for s in namen}
    try:
        yield
    finally:
        for s, h in alt.items():
            signal.signal(s, h)


def _als_ausnahme(signum, _frame):
    """Handler für SIGTERM und SIGHUP: ab dem ersten Signal werden weitere ignoriert (das Aufräumen mit Stopp der
    Sandbox und Widerruf des Tokens darf nicht ein zweites Mal unterbrochen werden), dann endet der Lauf."""
    for s in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGHUP", None)):
        if s is not None:
            signal.signal(s, signal.SIG_IGN)
    raise _Beendet(signum)


def _signale_aufschieben():
    """Blockiert SIGTERM und SIGHUP (sie bleiben anhängig, gehen nicht verloren). Liefert die alte Maske oder None."""
    namen = {s for s in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGHUP", None)) if s is not None}
    if not hasattr(signal, "pthread_sigmask") or threading.current_thread() is not threading.main_thread():
        return None
    return signal.pthread_sigmask(signal.SIG_BLOCK, namen)


def _signale_zulassen(alt) -> None:
    if alt is not None:
        signal.pthread_sigmask(signal.SIG_SETMASK, alt)


@contextmanager
def github_token_fuer_lauf(job: str, art: str, repo: str | None, app: GithubApp | None):
    """Kurzlebiges GitHub-Token für genau einen Lauf: liefert None ohne App-Modus oder für Arten ohne GitHub.
    Sonst Token erzeugen (Fehler: GithubAppFehler, bevor irgendetwas startet) und es nach dem Block widerrufen,
    auch bei Ausnahme, Abbruch oder Signal. Während der Erzeugung sind SIGTERM und SIGHUP aufgeschoben (kein Token
    ohne Widerruf), während des Widerrufs ignoriert. Im Audit stehen nur Auftrag, Repo, Stufe und Ablaufzeit."""
    try:
        stufe = werkzeugkarte().github_stufe(art) if app is not None else None
    except (KeyError, ValueError) as e:
        raise GithubAppFehler(f"Werkzeugkarte: {e}") from None
    if stufe is None:
        yield None
        return
    maske = _signale_aufschieben()
    try:
        token, ablauf = installations_token(app, art, repo)
    except BaseException:
        _signale_zulassen(maske)
        raise
    try:
        _signale_zulassen(maske)  # ein aufgeschobenes Signal kommt jetzt an und endet im finally (Widerruf)
        log(f"gh_app_token {job} repo={repo or '*'} stufe={stufe} ablauf={ablauf}", pflicht=True)
        yield token
    finally:
        ok = False
        for _versuch in range(2):  # ein erstes Signal genau jetzt (_Beendet) überspringt den Widerruf nicht;
            try:                   # _als_ausnahme ignoriert alle weiteren, mehr als ein Wiederholen braucht es nie
                with _signale(signal.SIG_IGN):
                    ok = token_widerrufen(token)
                break
            except _Beendet:
                continue
        if ok:
            log(f"gh_app_widerruf {job} ok")
        else:
            log(f"gh_app_widerruf {job} FEHLGESCHLAGEN (Token läuft spätestens nach einer Stunde ab)")
            wamo_event("gh_widerruf_fehlgeschlagen", grund="Das GitHub-Token konnte nicht widerrufen werden; "
                       "es läuft spätestens nach einer Stunde ab")


def github_status() -> str:
    """Für ping: "token" (kein App-Modus), "app" (Konfiguration und Schlüssel gültig) oder "fehler: <Grund>".
    Ohne Netz; ob GitHub das Token ausstellt, prüft wamo-job-rauchtest --app-echt."""
    try:
        app = github_app_konfig(lese_geheimnisse())
        if app is None:
            return "token"
        pem = schluessel_lesen(app.schluessel_name)
        try:
            _rsa_schluessel(bytes(pem))
        finally:
            pem[:] = bytes(len(pem))
        return "app"
    except GithubAppFehler as e:
        return f"fehler: {e}"


def github_hinweis(repo: str | None) -> str:
    """Zusatz zum Systemtext im App-Modus (nur für Arten mit GitHub)."""
    ziel = f"nur für das Repo {repo}" if repo else "für die Repos der Installation"
    return (f"- GitHub: GH_TOKEN ist ein kurzlebiges Token nur für diesen Auftrag, {ziel}, mit Rechten für Inhalte "
            "und Pull Requests. Repos anlegen, Einstellungen, Workflows, Secrets und Löschen gehen damit nicht; "
            "braucht der Auftrag das, im Ergebnis nennen.")


# ---------------------------------------------------------------- MCP-Server prüfen
PLATZHALTER_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)(?::-([^}]*))?\}")
HARMLOS_RE = re.compile(
    r"(?:Bearer|Basic|Token|token)\s*|true|false|yes|no|on|off|\d{1,6}"
    r"|https?://[A-Za-z0-9.-]+(?::\d{1,5})?(?:/[A-Za-z0-9._~/-]*)?"
    r"|[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}|[A-Za-z][A-Za-z_-]{0,15}|"
)
GEHEIMNISARTIG_RE = re.compile(r"[A-Za-z0-9_+/=-]{24,}")


def _wert_harmlos(text: str) -> bool:
    """Nur ${NAME}-Platzhalter (mit harmlosem Standardwert) plus unkritische Literale."""
    for m in PLATZHALTER_RE.finditer(text):
        if m.group(2) and not HARMLOS_RE.fullmatch(m.group(2)):
            return False
    return bool(HARMLOS_RE.fullmatch(PLATZHALTER_RE.sub("", text)))


def _arg_geheimnisartig(arg: str) -> bool:
    teil = arg.split("=", 1)[-1] if arg.startswith("-") else arg
    return bool(GEHEIMNISARTIG_RE.fullmatch(teil)) and not teil.startswith(("/", "@")) \
        and any(c.isdigit() for c in teil) and any(c.isalpha() for c in teil)


def mcp_server_pruefen(server: object) -> str | None:
    """Grund, warum ein MCP-Eintrag nicht in den Auftrag darf, oder None. Werte in env und headers sowie die
    URL dürfen nur aus ${NAME}-Platzhaltern und unkritischen Literalen bestehen; Argumente dürfen nicht wie
    Schlüssel aussehen. So gelangt ein Token nie über die Konfiguration, nur über die Allowlist der Umgebung."""
    if not isinstance(server, dict):
        return "kein Objekt"
    for feld in ("env", "headers"):
        werte = server.get(feld) or {}
        if not isinstance(werte, dict):
            return f"{feld} ist kein Objekt"
        for key, value in werte.items():
            if not isinstance(value, str) or not _wert_harmlos(value):
                return f"{feld}.{key} enthält ein Literal, das ein Geheimnis sein könnte"
    if "url" in server and (not isinstance(server["url"], str) or not _wert_harmlos(server["url"])):
        return "url enthält Anmeldedaten oder unbekannte Teile"
    args = server.get("args") or []
    if not isinstance(args, list) or any(not isinstance(a, str) or _arg_geheimnisartig(a) for a in args):
        return "args enthält einen Wert, der wie ein Schlüssel aussieht"
    return None


# ---------------------------------------------------------------- Dateien und Sperren
def log(text: str, pflicht: bool = False) -> None:
    """Audit-Protokoll /srv/wamo/logs/auftraege.log. Mit pflicht=True (Start, Freigabe, Selbsttest, Abbruch)
    bricht ein Schreibfehler den Befehl ab, statt still weiterzulaufen."""
    client = (os.environ.get("SSH_CONNECTION") or "lokal").split(" ")[0]
    text = text.replace("\n", " ").replace("\r", " ")
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {client} {text} kanal={KANAL}\n"
    try:
        with open(LOGS / "auftraege.log", "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        print(f"WAMO-Auftrag: Audit-Protokoll nicht schreibbar ({e.strerror})", file=sys.stderr)
        if pflicht:
            raise


def write_json_atomic(path: Path, data: object) -> None:
    """Zufälliger Name mit O_EXCL (folgt keinem gepflanzten Link), dann rename über das Ziel."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_fresh(path: Path, text: str) -> None:
    """Für Dateien in Ordnern, die die Sandbox beschreiben kann: vorhandenen Eintrag (auch einen Link)
    entfernen und neu anlegen, ohne je einem Link zu folgen."""
    path.unlink(missing_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def read_no_follow(path: Path, limit: int, dir_fd: int | None = None) -> str | None:
    """Liest höchstens limit Bytes einer regulären Datei, ohne einem Link zu folgen und ohne an einer FIFO
    zu hängen (O_NONBLOCK, danach fstat); None, wenn es nicht geht."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags, dir_fd=dir_fd) if dir_fd is not None else os.open(path, flags)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        data = os.read(fd, limit + 1)
    except OSError:
        return None
    finally:
        os.close(fd)
    return None if len(data) > limit else data.decode("utf-8", "replace")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return default


@contextmanager
def exklusiv_mit_frist(pfad: Path, frist_s: float):
    """Wie exklusiv, aber höchstens frist_s Sekunden warten (TimeoutError danach): für Sperren, die eine Logik von außen auch halten kann."""
    import fcntl
    ende = time.monotonic() + frist_s
    with open(pfad, "a+") as f:
        while True:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= ende:
                    raise TimeoutError(f"Sperre {pfad.name} belegt") from None
                time.sleep(0.1)
        yield


@contextmanager
def exklusiv(pfad: Path):
    """Wartende Sperre (kurze Abschnitte wie das Eintragen einer Freigabe)."""
    import fcntl
    with open(pfad, "a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield


class Sperre:
    """flock auf einer Datei ohne Warten; gilt, solange das Objekt lebt (offene Datei)."""

    def __init__(self, pfad: Path):
        self.pfad = pfad
        self.datei = None

    def versuchen(self) -> bool:
        import fcntl
        self.datei = open(self.pfad, "a+")
        try:
            fcntl.flock(self.datei.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            self.datei.close()
            self.datei = None
            return False


def sperren_ordner() -> Path:
    path = JOBS / ".sperren"
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def _sperre_freigeben(sperre: object) -> None:
    """Gibt eine gehaltene Sperre sofort frei (die Datei schließen beendet den flock). Wirft nie."""
    datei = getattr(sperre, "datei", None)
    if datei is not None:
        try:
            datei.close()
        except OSError:
            pass
        sperre.datei = None


# ---------------------------------------------------------------- Plätze: gleichzeitige Aufträge (Dispatcher 9)
def platz_ports(platz: int) -> range:
    """Der eigene Teil der Entwicklungsports eines Platzes (wie platz_ports in wamo-job.sh)."""
    if type(platz) is not int or not 0 <= platz < len(ENTWICKLUNGS_PORTS) // PORTS_JE_PLATZ:
        raise ValueError("Platz ungültig")
    von = ENTWICKLUNGS_PORTS.start + platz * PORTS_JE_PLATZ
    return range(von, von + PORTS_JE_PLATZ)


def port_hinweis(platz: int) -> str:
    """Hinweis für Claude Code im Systemprompt: der eigene Portbereich dieses Laufs (Landlock sperrt jeden anderen im Bereich 20000-20999)."""
    ports = platz_ports(platz)
    return (f"Eigene Entwicklungsserver und Tests nur auf 127.0.0.1 mit einem Port von {ports.start} bis {ports.stop - 1} (in der Sandbox "
            "WAMO_PORT_VON und WAMO_PORT_BIS). Die übrigen Ports von 20000 bis 20999 gehören gleichzeitig laufenden Aufträgen und sind "
            "gesperrt.")


def parallel_grenzen() -> tuple[int, int]:
    """(gesamt, je Person) aus kernkanal.conf, nie über PARALLEL_MAX. Fehlt das Modul, ist es defekt oder die Datei fehlerhaft oder
    fehlend: höchstens ein Auftrag gleichzeitig wie bis Version 8 (fail closed)."""
    try:
        gesamt, je_person = kern_modul().parallel_grenzen(kern_zustand(), PARALLEL_MAX)
    except Exception:  # noqa: BLE001 (Modul fehlt oder ist defekt)
        return 1, 1
    gesamt = max(1, min(PARALLEL_MAX, int(gesamt)))
    return gesamt, max(1, min(gesamt, int(je_person)))


def person_schluessel(profil: str | None) -> str | None:
    """Wer für die Grenze je Person zählt (siehe person_schluessel im Modul des Kern-Kanals): Kern-Kanal die Kennung des Profils, PC-Kanal pc,
    lokal lokal. Ohne Modul gilt das für pc und lokal genauso, der Kern-Kanal arbeitet ohnehin nie ohne das Modul."""
    try:
        return kern_modul().person_schluessel(KANAL, profil)
    except Exception:  # noqa: BLE001
        return KANAL if KANAL in ("pc", "lokal") else None


def _belegen_aus(pfade: list[Path], grenze: int) -> tuple[object | None, int | None]:
    """Versucht jede Sperre der Liste und zählt die belegten. Unter der Grenze: (die erste freie, ihre Nummer), alle übrigen sofort wieder
    frei. Sonst (None, None) und nichts gehalten. Der Aufrufer hält dabei die Sperre plaetze (sonst zählten zwei Starts gleichzeitig)."""
    frei: list[tuple[int, object]] = []
    belegt = 0
    for nummer, pfad in enumerate(pfade):
        sperre = Sperre(pfad)
        if sperre.versuchen():
            frei.append((nummer, sperre))
        else:
            belegt += 1
    if belegt >= grenze or not frei:
        for _, sperre in frei:
            _sperre_freigeben(sperre)
        return None, None
    for _, sperre in frei[1:]:
        _sperre_freigeben(sperre)
    return frei[0][1], frei[0][0]


def plaetze_belegen(sperren: Path, person: str | None, gesamt: int, je_person: int) -> tuple[list, int | None, str | None]:
    """Belegt einen Platz je Person (Sperren person-<Person>-<n>) und einen Platz gesamt (platz-<n>), n von 0 bis PARALLEL_MAX - 1.
    Gezählt wird unter der Sperre plaetze; belegt sind Plätze, deren Sperre ein laufender Dispatcher hält (auch über einer gesenkten
    Grenze). Liefert (gehaltene Sperren, Platznummer, None) oder ([], None, Code): profil (die Person hat je_person Aufträge laufen), gesamt
    (gesamt Aufträge laufen oder die Sperre plaetze kam nicht rechtzeitig). Eine ungültige Person ist Abgewiesen (fail closed)."""
    if not isinstance(person, str) or not PERSON_RE.fullmatch(person):
        raise Abgewiesen("Person für die Plätze unbekannt")
    zaehlen = Sperre(sperren / PLAETZE_SPERRE)
    ende = time.monotonic() + PLAETZE_WARTEN_S
    while not zaehlen.versuchen():
        if time.monotonic() > ende:
            return [], None, "gesamt"
        time.sleep(0.05)
    try:
        eigen, _ = _belegen_aus([sperren / f"person-{person}-{n}" for n in range(PARALLEL_MAX)], min(je_person, PARALLEL_MAX))
        if eigen is None:
            return [], None, "profil"
        platz_sperre, platz = _belegen_aus([sperren / f"platz-{n}" for n in range(PARALLEL_MAX)], min(gesamt, PARALLEL_MAX))
        if platz_sperre is None:
            _sperre_freigeben(eigen)
            return [], None, "gesamt"
        return [eigen, platz_sperre], platz, None
    finally:
        _sperre_freigeben(zaehlen)


def belegt_text(grenze: str, n: int | None = None) -> str:
    """Der Grund im Ereignis belegt (für Protokoll und ältere Kerne; der Kern wählt seinen Satz nach grenze und max)."""
    if grenze == "auftrag":
        return "Dieser Auftrag läuft bereits"
    if grenze == "projekt":
        return "Im Projekt läuft schon ein anderer Auftrag"
    if grenze == "profil":
        return "Grenze je Person: ein eigener Auftrag läuft schon" if n == 1 else f"Grenze je Person: {n} eigene Aufträge laufen schon"
    return "Es läuft schon ein Auftrag (der einzige Platz ist belegt)" if n == 1 else f"Es laufen schon {n} Aufträge (alle Plätze belegt)"


def belegt_melden(grenze: str, n: int | None = None) -> None:
    """Ereignis belegt mit grund, grenze (aus BELEGT_GRENZEN) und bei gesamt und profil max (die Zahl der erreichten Grenze)."""
    if grenze not in BELEGT_GRENZEN:
        raise ValueError("Grenze unbekannt")
    log(f"belegt grenze={grenze}" + (f" max={n}" if n is not None else ""))
    wamo_event("belegt", grund=belegt_text(grenze, n), grenze=grenze, **({"max": n} if n is not None else {}))


def job_laeuft(job: str) -> bool:
    lock = JOBS / job / ".lauf"
    if not lock.exists():
        return False
    probe = Sperre(lock)
    if probe.versuchen():
        probe.datei.close()
        return False
    return True


def _no_symlink(path: Path) -> Path:
    if path.is_symlink():
        raise Abgewiesen(f"{path.name} ist ein symbolischer Link")
    return path


def job_ordner(job: str) -> Path:
    jobdir = _no_symlink(JOBS / job)
    jobdir.mkdir(mode=0o700, exist_ok=True)
    return jobdir


def ohne_geheimnisse(obj, geheim: dict[str, str]):
    """Ersetzt wörtlich eingetragene Geheimniswerte (aus geheim.env) durch ${NAME}."""
    if isinstance(obj, dict):
        return {k: ohne_geheimnisse(v, geheim) for k, v in obj.items()}
    if isinstance(obj, list):
        return [ohne_geheimnisse(v, geheim) for v in obj]
    if isinstance(obj, str):
        for name, wert in sorted(geheim.items(), key=lambda kv: -len(kv[1])):
            if len(wert) >= 8 and wert in obj:
                obj = obj.replace(wert, "${" + name + "}")
    return obj


def npx_direkt(server: object) -> object:
    """MCP-Server der Form npx [-y] <paket>[@version] args... laufen direkt aus der schreibgeschützten
    globalen Installation von wamo (.npm-global), wenn das Paket dort in passender Version liegt:
    kein Download je Auftrag, kein beschreibbarer gemeinsamer Cache. Sonst bleibt der Eintrag, wie er ist."""
    if not isinstance(server, dict) or server.get("command") != "npx" or not isinstance(server.get("args"), list):
        return server
    args = [a for a in server["args"] if isinstance(a, str)]
    if len(args) != len(server["args"]):
        return server
    rest = args[1:] if args[:1] in (["-y"], ["--yes"]) else args
    if not rest or rest[0].startswith("-"):
        return server
    spec, rest = rest[0], rest[1:]
    name, version = spec, ""
    if "@" in spec[1:]:
        name, version = spec.rsplit("@", 1)
    if not re.fullmatch(r"(@[a-z0-9._-]+/)?[a-z0-9._-]+", name):
        return server
    meta = read_json(NPM_GLOBAL / "lib" / "node_modules" / name / "package.json", None)
    if not isinstance(meta, dict) or (version not in ("", "latest") and meta.get("version") != version):
        return server
    kurz = name.rsplit("/", 1)[-1]
    bins = meta.get("bin")
    programm = kurz if isinstance(bins, str) or (isinstance(bins, dict) and kurz in bins) else (
        next(iter(bins), None) if isinstance(bins, dict) and bins else None)
    if not programm or not (NPM_GLOBAL / "bin" / programm).exists():
        return server
    return {**server, "command": str(NPM_GLOBAL / "bin" / programm), "args": rest}


def claude_konfiguration(claude_dir: Path, geheim: dict[str, str]) -> None:
    """Globale Claude-Konfiguration des Auftrags (CLAUDE_CONFIG_DIR in der Sandbox), bei JEDEM Lauf neu aus
    der Konfiguration von wamo: nichts, was ein früherer Lauf in .claude.json oder settings.json eingetragen
    hat (Hooks, projektbezogene MCP-Server, Helferbefehle), überlebt. MCP-Server ohne Geheimniswerte und nur,
    wenn mcp_server_pruefen nichts findet. Der Ordner ist in der Sandbox beschreibbar: ohne Links schreiben."""
    # M1: den Auftrags-Konfigordner bis auf projects/ (Sitzungen für --resume) leeren, damit nichts, was ein
    # früherer Lauf dort angelegt hat (agents/, commands/, skills/, settings.local.json), überlebt.
    import shutil
    for eintrag in claude_dir.iterdir() if claude_dir.is_dir() else ():
        if eintrag.name == "projects" and eintrag.is_dir() and not eintrag.is_symlink():
            continue
        try:
            if eintrag.is_dir() and not eintrag.is_symlink():
                shutil.rmtree(eintrag)
            else:
                eintrag.unlink()
        except OSError:
            pass
    host = read_json(HEIM / ".claude.json", {})
    host = host if isinstance(host, dict) else {}
    conf = {k: host[k] for k in CLAUDE_JSON_KEYS if k in host}
    servers = {}
    roh = host.get("mcpServers")
    for name, server in (roh.items() if isinstance(roh, dict) else ()):
        server = ohne_geheimnisse(npx_direkt(server), geheim)
        grund = mcp_server_pruefen(server)
        if grund:
            log(f"MCP-Server {str(name)[:40]} nicht übernommen: {grund}")
            continue
        servers[name] = server
    conf.update({"mcpServers": servers, "autoUpdates": False, "hasCompletedOnboarding": True})
    write_fresh(claude_dir / ".claude.json", json.dumps(conf, ensure_ascii=False))
    host_settings = read_json(HEIM / ".claude" / "settings.json", {})
    host_settings = host_settings if isinstance(host_settings, dict) else {}
    settings = {k: host_settings[k] for k in SETTINGS_KEYS if k in host_settings}
    write_fresh(claude_dir / "settings.json", json.dumps(ohne_geheimnisse(settings, geheim), ensure_ascii=False))
    (claude_dir / "settings.local.json").unlink(missing_ok=True)


def vorbereiten(jobdir: Path, job: str, projekt: str, art: str, repo: str | None = None, kanal: str | None = None,
                profil: str | None = None, github: str | None = None) -> None:
    """Legt den Auftragsordner an oder prüft die Bindung an Projekt, Art und Ziel-Repo (unter der Auftragssperre).
    Das Repo begrenzt das GitHub-Token; eine Fortsetzung mit einem anderen Repo wird abgewiesen. Neue Aufträge aus dem
    Kern-Kanal oder dem PC-Kanal tragen kanal (kern oder pc); ein Auftrag ohne das Feld gehört nie dem Kern-Kanal. Im Kern-Kanal
    steht auch die Kennung des Profils darin (profil), eine Fortsetzung aus einem anderen Profil wird abgewiesen. github
    (persoenlich, Plan C) ist ebenso gebunden: ein Folgelauf mit anderem Wert, auch ohne das Feld, endet mit GithubWechsel."""
    meta_path = jobdir / "auftrag.json"
    meta = read_json(meta_path, None)
    kern_profil = profil if kanal == "kern" and isinstance(profil, str) and PROFIL_RE.fullmatch(profil) else None
    github = github if kanal == "kern" and github == GITHUB_WEG else None
    if meta is None:
        write_json_atomic(meta_path, {"job": job, "projekt": projekt, "art": art, "repo": repo,
                                      "erstellt": int(time.time()), **({"kanal": kanal} if kanal in ("kern", "pc") else {}),
                                      **({"profil": kern_profil} if kern_profil else {}),
                                      **({"github": github} if github else {})})
    elif not isinstance(meta, dict) or meta.get("projekt") != projekt or meta.get("art") != art:
        raise Abgewiesen("Auftrag gehört zu einem anderen Projekt oder einer anderen Art")
    elif meta.get("repo") != repo:
        raise Abgewiesen("Auftrag gehört zu einem anderen Ziel-Repo")
    elif kanal == "kern" and meta.get("profil") != kern_profil:
        raise Abgewiesen("Auftrag gehört zu einem anderen Profil")
    elif meta.get("github") != github:
        raise GithubWechsel("Auftrag gehört zu einem anderen GitHub-Weg")
    for sub in ("claude", "zustand", "etc"):
        _no_symlink(jobdir / sub).mkdir(mode=0o700, exist_ok=True)
    claude_konfiguration(jobdir / "claude", lese_geheimnisse())
    uid = os.getuid() if hasattr(os, "getuid") else 995
    gid = os.getgid() if hasattr(os, "getgid") else 982
    (jobdir / "etc" / "passwd").write_text(
        "root:x:0:0:root:/root:/usr/sbin/nologin\n"
        f"wamo:x:{uid}:{gid}:WAMO:{HEIM}:/bin/bash\n"
        "nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n", encoding="utf-8")
    (jobdir / "etc" / "group").write_text(
        f"root:x:0:\nwamo:x:{gid}:\nnogroup:x:65534:\n", encoding="utf-8")
    projektdir = _no_symlink(PROJEKTE / projekt)
    projektdir.mkdir(mode=0o750, exist_ok=True)


def lauf_vorbereiten(jobdir: Path, projekt: str) -> None:
    """Je Lauf: Anfragen des letzten Laufs sichern, Freigaben als Schnappschuss bereitstellen, Projekt
    entschärfen."""
    zustand = jobdir / "zustand"
    alte = gepruefte_anfragen(jobdir, projekt)
    if alte:
        angefragt_anhaengen(jobdir, alte)
    with exklusiv(jobdir / ".freigaben"):
        neu = read_json(jobdir / "freigaben.json", [])
        (jobdir / "freigaben.json").unlink(missing_ok=True)
    neu = [fp for fp in neu if isinstance(fp, str) and FP_RE.fullmatch(fp)] if isinstance(neu, list) else []
    # zustand/ ist in der Sandbox beschreibbar: nichts darin wird gelesen oder geschrieben, ohne Links
    # auszuschließen. approvals.json hängt im Lauf schreibgeschützt über sich selbst.
    for name in ("pending.jsonl", "approvals.json.used", "approvals.json"):
        if (zustand / name).is_dir() and not (zustand / name).is_symlink():
            import shutil
            shutil.rmtree(zustand / name)  # rmtree folgt keinen Links; die Sandbox läuft gerade nicht
            log(f"zustand/{name} war ein Ordner und wurde ersetzt ({jobdir.name})")
    write_fresh(zustand / "pending.jsonl", "")
    write_fresh(zustand / "approvals.json.used", "")
    write_fresh(zustand / "approvals.json", json.dumps(neu))
    (jobdir / "abbruch").unlink(missing_ok=True)
    for entfernt in projekt_entschaerfen(PROJEKTE / projekt):
        log(f"entschärft {jobdir.name} {projekt}: {entfernt}")


def angefragt_anhaengen(jobdir: Path, eintraege: list[dict]) -> None:
    """angefragt.jsonl (außerhalb der Sandbox) wächst nicht unbegrenzt: über 1 MiB bleiben die jüngsten 500."""
    pfad = jobdir / "angefragt.jsonl"
    with open(pfad, "a", encoding="utf-8") as f:
        for req in eintraege:
            f.write(json.dumps(req, ensure_ascii=False) + "\n")
    try:
        if pfad.stat().st_size > MAX_ANGEFRAGT_BYTES:
            zeilen = pfad.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]
            write_fresh(pfad, "\n".join(zeilen) + "\n")
    except OSError:
        pass


def _kurz_genug(obj, tiefe: int = 0, zaehler: list | None = None) -> bool:
    """Alle Texte höchstens MAX_STRING_CHARS, höchstens 20 Ebenen und 2000 Knoten."""
    zaehler = zaehler if zaehler is not None else [0]
    zaehler[0] += 1
    if tiefe > 20 or zaehler[0] > 2000:
        return False
    if isinstance(obj, str):
        return len(obj) <= MAX_STRING_CHARS
    if isinstance(obj, dict):
        return all(_kurz_genug(k, tiefe + 1, zaehler) and _kurz_genug(v, tiefe + 1, zaehler) for k, v in obj.items())
    if isinstance(obj, list):
        return all(_kurz_genug(v, tiefe + 1, zaehler) for v in obj)
    return True


def mit_zeitlimit(funktion, sekunden: float):
    """Führt funktion() mit hartem Zeitlimit aus (SIGALRM, nur im Hauptthread unter Linux). Wirft
    _Zeitueberschreitung. Schutz gegen langsame Muster im Wächter bei gepflanzten Anfragen."""
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        return funktion()

    def abbrechen(*_):
        raise _Zeitueberschreitung()
    alt = signal.signal(signal.SIGALRM, abbrechen)
    signal.setitimer(signal.ITIMER_REAL, sekunden)
    try:
        return funktion()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, alt)


def gepruefte_anfragen(jobdir: Path, projekt: str) -> list[dict]:
    """Zeilen aus zustand/pending.jsonl (in der Sandbox beschreibbar), neu geprüft: Fingerabdruck und Grund
    kommen vom Wächter. Begrenzt in Zeilen, Länge, Verschachtelung und Rechenzeit je Zeile; Werkzeugnamen
    WAMO-* (eigene Anfragen des Dispatchers) kann die Sandbox nicht anfragen."""
    text = read_no_follow(jobdir / "zustand" / "pending.jsonl", MAX_PENDING_BYTES)
    if text is None:
        return []
    g = waechter()
    out, seen = [], set()
    schluss = time.monotonic() + GESAMT_PRUEF_BUDGET_S
    for line in text.splitlines()[:MAX_PENDING_LINES]:
        if time.monotonic() > schluss:  # N6: Gesamtbudget je Aufruf, Rest gilt als ungültig
            break
        if len(line.encode("utf-8", "replace")) > MAX_PENDING_LINE_BYTES:
            continue
        try:
            req = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(req, dict) or not isinstance(req.get("tool"), str) or not isinstance(req.get("input"), dict):
            continue
        tool, tool_input = req["tool"], req["input"]
        if len(tool) > 200 or tool.startswith("WAMO-") or not _kurz_genug(tool_input):
            continue
        try:
            decision, why = mit_zeitlimit(lambda: g.decide(tool, tool_input, PROJEKTE / projekt), DECIDE_TIMEOUT_S)
        except (Exception, _Zeitueberschreitung):  # unprüfbar oder zu langsam heißt ungültig
            continue
        fp = g.fingerprint(tool, tool_input)
        if decision != "approval" or req.get("id") != fp or fp in seen:
            continue
        seen.add(fp)
        out.append({"id": fp, "grund": why, "tool": tool, "input": tool_input})
        if len(out) >= MAX_OFFENE_FREIGABEN:
            break
    return out


# ---------------------------------------------------------------- Projekt entschärfen (H3)
GIT_ENV = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ATTR_NOSYSTEM": "1", "LANG": "C"}
GIT_ERLAUBT = [re.compile(p) for p in (
    r"core\.(repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|precomposeunicode|symlinks|autocrlf|eol)",
    r"extensions\.objectformat", r"remote\..+\.(url|fetch)", r"branch\..+\.(remote|merge|rebase)",
    r"user\.(name|email)", r"pull\.(rebase|ff)", r"push\.(default|autosetupremote)", r"init\.defaultbranch",
)]
GIT_URL_RE = re.compile(r"https://[A-Za-z0-9.-]+(:\d{1,5})?/[A-Za-z0-9._~/%-]*")
GIT_SICHER = [("core.repositoryformatversion", "0"), ("core.bare", "false")]  # config, wenn die alte unlesbar ist
MAX_CONFIG_BYTES = 1024 * 1024
WALK_MAX_DIRS = 4000      # eingebettete Repos finden, aber node_modules nicht unbegrenzt durchlaufen
WALK_MAX_TIEFE = 8
INVENTUR_FLAECHEN = ("package.json", ".npmrc", ".envrc", "CLAUDE.md", ".claude", "node_modules/.bin")


def git_config_filtern(eintraege: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Nur unkritische Schlüssel; Remote-URLs nur https ohne Anmeldedaten. Alles, was Befehle startet oder
    umlenkt (fsmonitor, hooksPath, sshCommand, pager, filter, textconv, alias, insteadOf, include, http,
    credential, uploadpack, receivepack, worktreeconfig), fällt weg."""
    out = []
    for key, value in eintraege:
        teile = key.split(".")
        norm = ".".join([teile[0].lower(), *teile[1:-1], teile[-1].lower()]) if len(teile) >= 2 else key.lower()
        if not any(p.fullmatch(norm) for p in GIT_ERLAUBT) or "\n" in value:
            continue
        if norm.startswith("remote.") and norm.endswith(".url") and not GIT_URL_RE.fullmatch(value):
            continue
        out.append((key, value))
    return out


def _git(*args: str, eingabe: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], input=eingabe, capture_output=True, env=GIT_ENV, timeout=20, cwd="/")


def git_config_lesen(text: str) -> list[tuple[str, str]] | None:
    """Liest eine Git-Konfiguration ohne Includes (git config --file ... --list -z); None, wenn unlesbar."""
    with tempfile.TemporaryDirectory() as tmp:
        pfad = Path(tmp) / "config"
        pfad.write_text(text, encoding="utf-8")
        p = _git("config", "--file", str(pfad), "--no-includes", "--list", "-z")
    if p.returncode != 0:
        return None
    out = []
    for eintrag in p.stdout.decode("utf-8", "replace").split("\0"):
        if eintrag:
            key, _, value = eintrag.partition("\n")
            out.append((key, value if "\n" in eintrag else "true"))
    return out


def git_config_schreiben(eintraege: list[tuple[str, str]]) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        pfad = Path(tmp) / "config"
        pfad.write_text("", encoding="utf-8")
        for key, value in eintraege:
            _git("config", "--file", str(pfad), "--add", key, value).check_returncode()
        return pfad.read_text(encoding="utf-8")


def _verzeichnis_at(dir_fd: int, name: str) -> int | None:
    """Öffnet name in dir_fd als Verzeichnis, ohne einem Link zu folgen. Ein Link an dieser Stelle wird
    entfernt (nie verfolgt); fehlt der Eintrag oder ist er keine Verzeichnis, None."""
    try:
        st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode):
        os.unlink(name, dir_fd=dir_fd)
        return None
    if not stat.S_ISDIR(st.st_mode):
        return None
    return os.open(name, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW, dir_fd=dir_fd)


def _rmtree_at(dir_fd: int, name: str) -> bool:
    """Entfernt name in dir_fd samt Inhalt, ohne Links zu verfolgen. Ein Link wird nur gelöst (unlink), ein
    Verzeichnis rekursiv geleert. False, wenn es den Eintrag nicht gibt."""
    try:
        st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
        os.unlink(name, dir_fd=dir_fd)
        return True
    sub = os.open(name, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW, dir_fd=dir_fd)
    try:
        for kind in os.listdir(sub):
            if not _rmtree_at(sub, kind):
                os.unlink(kind, dir_fd=sub)
    finally:
        os.close(sub)
    os.rmdir(name, dir_fd=dir_fd)
    return True


def _entfernen_at(dir_fd: int, name: str) -> bool:
    try:
        st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if stat.S_ISDIR(st.st_mode):
        return False
    os.unlink(name, dir_fd=dir_fd)
    return True


def _config_schreiben_at(git_fd: int, praefix: str, gefiltert: list[tuple[str, str]], grund: str,
                         entfernt: list[str]) -> None:
    """Ersetzt git_fd/config durch eine gefilterte Fassung (fail-closed: auch wenn die alte ein Link, zu groß
    oder unlesbar war). os.replace ersetzt die Datei oder den Link selbst, nicht dessen Ziel."""
    neu = git_config_schreiben(gefiltert)
    tmp = ".config.wamo.tmp"
    _entfernen_at(git_fd, tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW, 0o644, dir_fd=git_fd)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(neu)
    os.replace(tmp, "config", src_dir_fd=git_fd, dst_dir_fd=git_fd)
    entfernt.append(f"{praefix}/config bereinigt ({grund})")


def _git_ordner_entschaerfen(git_fd: int, praefix: str, entfernt: list[str]) -> None:
    for name in ("config.worktree",):
        if _entfernen_at(git_fd, name):
            entfernt.append(f"{praefix}/{name}")
    hooks_fd = _verzeichnis_at(git_fd, "hooks")
    if hooks_fd is not None:
        try:
            for name in os.listdir(hooks_fd):
                if not name.endswith(".sample") and _entfernen_at(hooks_fd, name):
                    entfernt.append(f"{praefix}/hooks/{name}")
        finally:
            os.close(hooks_fd)
    # config fail-closed: ein Link, eine Datei über MAX_CONFIG_BYTES oder unlesbares ergibt None und wird durch
    # eine sichere Fassung ersetzt (nicht übersprungen). read_no_follow öffnet mit O_NOFOLLOW, folgt also keinem Link.
    text = read_no_follow(Path("config"), MAX_CONFIG_BYTES, dir_fd=git_fd)
    if text is None:
        _config_schreiben_at(git_fd, praefix, GIT_SICHER, "war Link, zu groß oder unlesbar", entfernt)
        return
    eintraege = git_config_lesen(text)
    if eintraege is None:
        _config_schreiben_at(git_fd, praefix, GIT_SICHER, "nicht parsbar", entfernt)
        return
    gefiltert = git_config_filtern(eintraege)
    if gefiltert == eintraege:
        return
    weg = sorted({k for k, _ in eintraege} - {k for k, _ in gefiltert})
    _config_schreiben_at(git_fd, praefix, gefiltert, ", ".join(weg)[:200] or "nichts", entfernt)


def _git_behandeln(parent_fd: int, praefix: str, st: os.stat_result, entfernt: list[str]) -> None:
    """Ein .git-Eintrag: Link und gitdir-Zeiger (Datei) werden entfernt, ein echtes Verzeichnis entschärft."""
    if stat.S_ISLNK(st.st_mode):
        os.unlink(".git", dir_fd=parent_fd)
        entfernt.append(f"{praefix}.git (Link entfernt)")
        return
    if not stat.S_ISDIR(st.st_mode):  # .git als Datei (gitdir:-Zeiger) oder Sonstiges: entfernen
        os.unlink(".git", dir_fd=parent_fd)
        entfernt.append(f"{praefix}.git (gitdir-Zeiger entfernt)")
        return
    git_fd = os.open(".git", os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW, dir_fd=parent_fd)
    try:
        _git_ordner_entschaerfen(git_fd, f"{praefix}.git", entfernt)
        module_fd = _verzeichnis_at(git_fd, "modules")
        if module_fd is not None:
            try:
                for name in sorted(os.listdir(module_fd))[:200]:
                    sub_fd = _verzeichnis_at(module_fd, name)
                    if sub_fd is not None:
                        try:
                            _git_ordner_entschaerfen(sub_fd, f"{praefix}.git/modules/{name}", entfernt)
                        finally:
                            os.close(sub_fd)
            finally:
                os.close(module_fd)
    finally:
        os.close(git_fd)


def _walk_entschaerfen(parent_fd: int, praefix: str, tiefe: int, zaehler: list[int], entfernt: list[str]) -> None:
    """Begrenzte fd-basierte Suche nach .git-Einträgen (auch eingebettete Repos tief im Baum, H2). Kein Link
    wird verfolgt; node_modules und ähnliche große Bäume begrenzt WALK_MAX_DIRS."""
    if tiefe > WALK_MAX_TIEFE or zaehler[0] > WALK_MAX_DIRS:
        return
    try:
        namen = sorted(os.listdir(parent_fd))
    except OSError:
        return
    unterordner = []
    for name in namen:
        zaehler[0] += 1
        if zaehler[0] > WALK_MAX_DIRS:
            break
        try:
            st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError:
            continue
        if name == ".git":
            _git_behandeln(parent_fd, praefix, st, entfernt)
        elif stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode):
            unterordner.append(name)
    for name in unterordner:
        if zaehler[0] > WALK_MAX_DIRS:
            break
        try:
            sub_fd = os.open(name, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW, dir_fd=parent_fd)
        except OSError:
            continue
        try:
            _walk_entschaerfen(sub_fd, f"{praefix}{name}/", tiefe + 1, zaehler, entfernt)
        finally:
            os.close(sub_fd)


def projekt_entschaerfen(projektdir: Path) -> list[str]:
    """Entfernt Autostart-Flächen, die ein früherer Lauf (mit anderen Token) gepflanzt haben könnte: .mcp.json,
    .claude/settings*.json im Projektwurzel sowie Git-Hooks, config.worktree und eine bereinigte config in jedem
    .git (auch eingebettet oder als gitdir-Zeiger) im Baum. Läuft außerhalb der Sandbox über Verzeichnis-
    Deskriptoren, kein Link wird verfolgt. Fail-closed (H1): lässt sich der Ordner nicht öffnen, wirft os.open,
    der Lauf startet dann nicht. Vorher chmod 0750, damit ein früherer Lauf den Ordner nicht unlesbar machen konnte."""
    entfernt: list[str] = []
    try:
        os.chmod(projektdir, 0o750)
    except OSError:
        pass
    projekt_fd = os.open(projektdir, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW)  # Fehler: fail-closed
    try:
        if _entfernen_at(projekt_fd, ".mcp.json"):
            entfernt.append(".mcp.json")
        # Das projekteigene .claude (settings, agents, skills, commands, hooks) ist ein Ausführungsweg und wird
        # für einen isolierten Lauf nicht gebraucht: ganz entfernen. Ein Link an der Stelle wird nur gelöst.
        if _rmtree_at(projekt_fd, ".claude"):
            entfernt.append(".claude/ entfernt")
        _walk_entschaerfen(projekt_fd, "", 0, [0], entfernt)
    finally:
        os.close(projekt_fd)
    return entfernt


def _signatur_at(projekt_fd: int, rel: str) -> str | None:
    """Kurzsignatur einer Autostart-Fläche: bei package.json die scripts-Schlüssel, bei Ordnern die sortierte
    Namensliste, sonst mtime und Größe. None, wenn es den Eintrag nicht gibt. Folgt keinem Link (dann als Link markiert)."""
    pfade = rel.split("/")
    fd = projekt_fd
    zu_schliessen = []
    try:
        for teil in pfade[:-1]:
            fd = _verzeichnis_at_ro(fd, teil)
            if fd is None:
                return None
            zu_schliessen.append(fd)
        name = pfade[-1]
        try:
            st = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except OSError:
            return None
        if stat.S_ISLNK(st.st_mode):
            return "link"
        if stat.S_ISDIR(st.st_mode):
            try:
                eintraege = sorted(os.listdir(os.open(name, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW, dir_fd=fd)))
            except OSError:
                return "ordner?"
            return f"ordner[{len(eintraege)}]: " + ", ".join(eintraege[:20])
        if rel == "package.json" and stat.S_ISREG(st.st_mode):
            text = read_no_follow(Path(name), 512 * 1024, dir_fd=fd)
            try:
                skripte = json.loads(text).get("scripts") if text else None
            except (ValueError, AttributeError):
                skripte = None
            if isinstance(skripte, dict):
                return "scripts: " + "; ".join(f"{k}={str(v)[:60]}" for k, v in list(skripte.items())[:20])
        return f"{int(st.st_mtime)}:{st.st_size}"
    finally:
        for f in zu_schliessen:
            os.close(f)


def _verzeichnis_at_ro(dir_fd: int, name: str) -> int | None:
    """Wie _verzeichnis_at, aber ohne zu verändern (für die Inventur, nur lesen)."""
    try:
        st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except OSError:
        return None
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
        return None
    try:
        return os.open(name, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW, dir_fd=dir_fd)
    except OSError:
        return None


def projekt_inventur(projektdir: Path) -> dict[str, str]:
    """Signaturen der Autostart-Flächen, die beim Weiterverwenden eines Projekts implizit Code ausführen können
    (package.json-Skripte, .npmrc, .envrc, CLAUDE.md, .claude/, node_modules/.bin). Nur lesen."""
    out: dict[str, str] = {}
    try:
        projekt_fd = os.open(projektdir, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
    except OSError:
        return out
    try:
        for rel in INVENTUR_FLAECHEN:
            sig = _signatur_at(projekt_fd, rel)
            if sig is not None:
                out[rel] = sig
    finally:
        os.close(projekt_fd)
    return out


def inventur_vergleich(vorher: dict, nachher: dict) -> list[str]:
    """Menschlich lesbare Liste der Flächen, die seit dem letzten geprüften Lauf neu oder geändert sind (H3)."""
    vorher = vorher if isinstance(vorher, dict) else {}
    zeilen = []
    for rel, sig in nachher.items():
        if rel not in vorher:
            zeilen.append(f"neu: {rel} ({sig})")
        elif vorher[rel] != sig:
            zeilen.append(f"geändert: {rel} ({sig})")
    for rel in vorher:
        if rel not in nachher:
            zeilen.append(f"entfernt: {rel}")
    return zeilen


def projekt_leeren_sicher(projektdir: Path) -> bool:
    """Löscht den Inhalt des Projektordners (für die Option 'frischer Klon' aus der Freigabekarte). Der Ordner
    selbst bleibt. Fehler beim Öffnen gilt als nicht leer. Kein Link wird verfolgt."""
    import shutil
    try:
        os.chmod(projektdir, 0o750)
    except OSError:
        pass
    try:
        with os.scandir(projektdir) as it:
            eintraege = list(it)
    except OSError:
        return False
    for e in eintraege:
        try:
            if e.is_symlink() or not e.is_dir(follow_symlinks=False):
                os.unlink(e.path)
            else:
                shutil.rmtree(e.path)
        except OSError:
            return False
    return True


def zugang_pruefen(projekt: str, namen: set[str], freigaben: list[str]) -> dict | None:
    """Buchführung je Projekt (außerhalb der Sandbox): Schnittmenge der Token-Namen aller bisherigen Läufe.
    Ein Lauf, der ein Token außerhalb dieser Schnittmenge bekäme, könnte Autostart-Flächen ausführen, die ein
    früherer Lauf ohne dieses Token gepflanzt hat. Er startet deshalb nur, wenn die passende Freigabe in
    diesem Lauf vorliegt (dann gilt das Projekt mit diesen Zugängen als geprüft) oder der Projektordner leer
    ist. Liefert die Freigabe-Anfrage, wenn der Lauf warten muss, sonst None."""
    ordner = JOBS / ".projekte"
    ordner.mkdir(mode=0o700, exist_ok=True)
    pfad = ordner / f"{projekt}.json"
    eintrag = read_json(pfad, None)
    projektdir = PROJEKTE / projekt
    # H1: ein früherer Lauf konnte den Ordner unlesbar machen (chmod 100). Erst wieder lesbar machen; lässt sich
    # das nicht oder ist der Scan nicht möglich, gilt der Ordner NICHT als leer (sonst käme mehr Zugang ohne Freigabe).
    try:
        os.chmod(projektdir, 0o750)
    except OSError:
        pass
    try:
        leer = not any(os.scandir(projektdir))
    except OSError:
        leer = False
    inventur = projekt_inventur(projektdir)
    bisher = set(eintrag["schnitt"]) if isinstance(eintrag, dict) and isinstance(eintrag.get("schnitt"), list) else None
    if leer:
        write_json_atomic(pfad, {"schnitt": sorted(namen), "flaechen": inventur})
        return None
    if bisher is None:  # Projekt mit Inhalt, aber ohne Buchführung (älter, von Hand angelegt): erst prüfen lassen
        bisher = set()
    neu = namen - bisher
    if neu:
        anfrage_input = {"projekt": projekt, "neu": sorted(neu), "bisher": sorted(bisher)}
        fp = waechter().fingerprint(ZUGANG_TOOL, anfrage_input)  # Inventur NICHT im Fingerabdruck (ändert sich je Lauf)
        if fp not in freigaben:
            alte_flaechen = eintrag.get("flaechen") if isinstance(eintrag, dict) else {}
            geaendert = inventur_vergleich(alte_flaechen, inventur)
            return {"id": fp, "grund": "Mehr Zugänge als frühere Aufträge in diesem Projekt: " + ", ".join(sorted(neu)),
                    "tool": ZUGANG_TOOL, "input": anfrage_input,
                    "inventur": geaendert or ["keine geänderten Autostart-Flächen seit dem letzten Lauf"],
                    "hinweis_klon": "Alternative: Projektordner vor dem Start leeren (frischer Klon)."}
        write_json_atomic(pfad, {"schnitt": sorted(namen), "flaechen": inventur})  # geprüft und freigegeben
        return None
    write_json_atomic(pfad, {"schnitt": sorted(bisher & namen), "flaechen": inventur})
    return None


# ---------------------------------------------------------------- Ausgabe
_ausgabe_lock = threading.Lock()


def emit(event: dict) -> bool:
    """Eine JSON-Zeile auf stdout; False, wenn der Empfänger weg ist."""
    return emit_raw((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))


def emit_raw(line: bytes) -> bool:
    with _ausgabe_lock:
        try:
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False


def wamo_event(ereignis: str, **extra) -> bool:
    return emit({"type": "wamo", "ereignis": ereignis, **extra})


def ist_wamo_zeile(raw: bytes) -> bool:
    """Gibt sich eine Zeile aus der Sandbox als eigenes Ereignis aus? (Der Agent kann auf fd 1 von Claude
    Code schreiben.) Solche Zeilen werden verworfen."""
    # Ohne Vorfilter auf Bytes: JSON erlaubt Escapes (wamo) und beliebige Schreibweisen
    try:
        obj = json.loads(raw)
    except (ValueError, RecursionError):
        return False
    return isinstance(obj, dict) and str(obj.get("type", "")).strip().lower() == "wamo"


def zeilen(stream, limit: int):
    """Zeilen höchstens limit Bytes; längere werden bis zum Zeilenende verworfen (None als Marker)."""
    while True:
        line = stream.readline(limit)
        if not line:
            return
        if len(line) >= limit and not line.endswith(b"\n"):
            while True:
                rest = stream.readline(limit)
                if not rest or rest.endswith(b"\n"):
                    break
            yield None
            continue
        yield line


class Freigabezaehler:
    """Zählt im stream-json, wie oft freigegebene Aufrufe wirklich ausgeführt wurden (tool_use mit einem
    tool_result, das keine Hook-Sperre meldet). Öfter als freigegeben heißt: approvals.json.used wurde in der
    Sandbox zurückgesetzt oder parallele Hooks haben dieselbe Freigabe doppelt durchgelassen; der Lauf endet."""

    def __init__(self, freigaben: object):
        self.erlaubt: dict[str, int] = {}
        for fp in freigaben if isinstance(freigaben, list) else []:
            if isinstance(fp, str) and FP_RE.fullmatch(fp):
                self.erlaubt[fp] = self.erlaubt.get(fp, 0) + 1
        self.offen: dict[str, str] = {}
        self.genutzt: dict[str, int] = {}

    def sehen(self, raw: bytes) -> bool:
        """True, sobald eine Freigabe öfter genutzt wurde als erteilt."""
        if not self.erlaubt or (b'"tool_use"' not in raw and b'"tool_result"' not in raw):
            return False
        try:
            ev = json.loads(raw)
        except (ValueError, RecursionError):
            return False
        bloecke = ((ev.get("message") or {}).get("content") if isinstance(ev, dict) else None) or []
        if not isinstance(bloecke, list):
            return False
        g = waechter()
        for b in bloecke:
            if not isinstance(b, dict):
                continue
            if ev.get("type") == "assistant" and b.get("type") == "tool_use" and isinstance(b.get("input"), dict):
                fp = g.fingerprint(str(b.get("name", "")), b["input"])
                if fp in self.erlaubt:
                    self.offen[str(b.get("id"))] = fp
            elif ev.get("type") == "user" and b.get("type") == "tool_result":
                fp = self.offen.pop(str(b.get("tool_use_id")), None)
                if fp is None:
                    continue
                inhalt = b.get("content")
                text = inhalt if isinstance(inhalt, str) else " ".join(
                    str(t.get("text", "")) for t in inhalt if isinstance(t, dict)) if isinstance(inhalt, list) else ""
                if g.tool_ran({"tool_response": text}):
                    self.genutzt[fp] = self.genutzt.get(fp, 0) + 1
                    if self.genutzt[fp] > self.erlaubt[fp]:
                        return True
        return False


class FreigabeServer:
    """Vergibt Freigaben atomar außerhalb der Sandbox (M5). Der Wächter in der Sandbox verbindet sich über
    /run/wamo/zustand/freigabe.sock und reserviert im PreToolUse, bestätigt im PostToolUse oder gibt bei einer
    Hook-Sperre zurück. Ein einziger Thread mit Sperre bedient die Anfragen: ein freigegebener Aufruf kann so
    nie öfter laufen als freigegeben, auch nicht bei parallelen Hooks oder manipuliertem Zustand in der Sandbox.
    Die Freigabeliste kommt aus approvals.json (schreibgeschützt in der Sandbox); verbraucht wird nur hier."""

    def __init__(self, sock_path: Path, freigaben: object):
        self.sock_path = str(sock_path)
        self.granted: dict[str, int] = {}
        for fp in freigaben if isinstance(freigaben, list) else []:
            if isinstance(fp, str) and FP_RE.fullmatch(fp):
                self.granted[fp] = self.granted.get(fp, 0) + 1
        self.reserviert: dict[str, int] = {}
        self.benutzt: dict[str, int] = {}
        self._lock = threading.Lock()
        self._srv: socket.socket | None = None

    def start(self) -> None:
        try:
            os.unlink(self.sock_path)
        except FileNotFoundError:
            pass
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.sock_path)
        os.chmod(self.sock_path, 0o660)
        self._srv.listen(16)
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        while True:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            try:
                conn.settimeout(5)
                self._bedienen(conn)
            except OSError:
                pass
            finally:
                conn.close()

    def _bedienen(self, conn: socket.socket) -> None:
        line = conn.makefile("rb").readline(4096)
        ok = False
        try:
            req = json.loads(line)
            op, fp = req.get("op"), req.get("fp")
        except (ValueError, AttributeError):
            op, fp = None, None
        if isinstance(fp, str) and FP_RE.fullmatch(fp):
            with self._lock:
                frei = self.granted.get(fp, 0) - self.benutzt.get(fp, 0) - self.reserviert.get(fp, 0)
                if op == "reserve" and frei > 0:
                    self.reserviert[fp] = self.reserviert.get(fp, 0) + 1
                    ok = True
                elif op == "commit" and self.reserviert.get(fp, 0) > 0:
                    self.reserviert[fp] -= 1
                    self.benutzt[fp] = self.benutzt.get(fp, 0) + 1
                    ok = True
                elif op == "release" and self.reserviert.get(fp, 0) > 0:
                    self.reserviert[fp] -= 1
                    ok = True
        conn.sendall((json.dumps({"ok": ok}) + "\n").encode("utf-8"))

    def stop(self) -> None:
        if self._srv is not None:
            try:
                self._srv.close()
            except OSError:
                pass
        try:
            os.unlink(self.sock_path)
        except OSError:
            pass


def egress_offen() -> bool:
    """Prüft, ob der Ausgangsfilter steht: ein Verbindungsversuch zu einem privaten Ziel muss scheitern.
    True heißt: der Filter ist weg (z. B. nft neu geladen), der Lauf muss sofort enden (M6)."""
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect(("10.255.255.254", 9))
        return True  # eine Verbindung dorthin dürfte nie zustande kommen
    except OSError as e:
        return e.errno not in (errno.EHOSTUNREACH, errno.ENETUNREACH, errno.EACCES, errno.EPERM, errno.ETIMEDOUT)
    finally:
        s.close()


# ---------------------------------------------------------------- Befehle
def cmd_ping() -> int:
    # abnahme_befehl_sha256 ist nur ein Versionsabgleich für den Kern (stimmt seine Kopie mit dieser überein?). Maßgeblich ist die
    # Kopie in /opt/wamo/waechter, die dieser Dispatcher selbst lädt: gegen sie prüft er jeden Aufruf von pruefen erneut.
    geheim = lese_geheimnisse()
    emit({"ok": True, "version": VERSION, "runner": RUNNER.is_file(), "waechter": (WAECHTER / "dev_guard.py").is_file(),
          "github": github_status(), "serverzugang": serverzugang_erlaubt(geheim),
          "kontingent": kontingent_modul() is not None, "pruefen": pruefen_aktiv(geheim), "haus": haus_aktiv(geheim),
          "abnahme_befehl_sha256": modul_sha256("abnahme_befehl"), "kanal": KANAL, "kernkanal": kernkanal_ping(),
          "parallel": dict(zip(("gesamt", "profil"), parallel_grenzen()), hart=PARALLEL_MAX),
          "persoenlich": persoenlich_aktiv(), "github_helfer": HELFER.is_file()})
    return EXIT_OK


def cmd_status(job: str) -> int:
    status = read_json(JOBS / job / "status.json", None)
    if not isinstance(status, dict):
        emit({"job": job, "bekannt": False})
        return EXIT_OK
    status["laeuft"] = job_laeuft(job)
    emit(status)
    return EXIT_OK


def cmd_pending(job: str) -> int:
    meta = read_json(JOBS / job / "auftrag.json", None)
    if not isinstance(meta, dict) or not isinstance(meta.get("projekt"), str):
        return EXIT_OK
    for req in gepruefte_anfragen(JOBS / job, check_project(meta["projekt"])):
        emit(req)
    return EXIT_OK


def cmd_approve(job: str, fp: str) -> int:
    jobdir = JOBS / job
    meta = read_json(jobdir / "auftrag.json", None)
    if not isinstance(meta, dict):
        raise Abgewiesen("Auftrag unbekannt")
    projekt = check_project(str(meta.get("projekt", "")))
    bekannt = {r["id"] for r in gepruefte_anfragen(jobdir, projekt)}
    text = read_no_follow(jobdir / "angefragt.jsonl", MAX_ANGEFRAGT_BYTES * 2) or ""
    for line in text.splitlines():
        try:
            eintrag = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if isinstance(eintrag, dict):
            bekannt.add(eintrag.get("id"))
    if fp not in bekannt:
        raise Abgewiesen("Fingerabdruck wurde nie angefragt")
    with exklusiv(jobdir / ".freigaben"):
        neu = read_json(jobdir / "freigaben.json", [])
        write_json_atomic(jobdir / "freigaben.json", [*(neu if isinstance(neu, list) else []), fp])
    log(f"approve {job} {fp}", pflicht=True)
    emit({"ok": True})
    return EXIT_OK


def platz_reste_beenden(platz: int) -> None:
    """Beendet alle Einheiten auf diesem Platz (wamo-job-<job>-<zusatz>-p<platz>-<zeit>.scope). Nur wer die Sperre platz-<platz> hält, ruft
    das auf: dann läuft dort kein lebender Dispatcher mehr, und was noch läuft, ist der Rest eines hart beendeten Vorgängers (SIGKILL, OOM),
    dessen Sandbox sonst bis zu ihrem Zeitlimit den Portbereich des Platzes weiter nutzen könnte (Befund des Sicherheitsreviews)."""
    if type(platz) is not int or not 0 <= platz < len(ENTWICKLUNGS_PORTS) // PORTS_JE_PLATZ:
        raise ValueError("Platz ungültig")
    try:
        subprocess.run(["/usr/bin/systemctl", "--user", "stop", f"wamo-job-*-p{platz}-*.scope"],
                       env=basis_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pass


def stop_units(job: str) -> None:
    """Beendet alle systemd-Einheiten des Auftrags (Sandbox samt Kindprozessen)."""
    try:
        subprocess.run(["/usr/bin/systemctl", "--user", "stop", f"wamo-job-{job}-*.scope"],
                       env=basis_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pass


def cmd_cancel(job: str) -> int:
    jobdir = JOBS / job
    if jobdir.is_dir() and not jobdir.is_symlink():
        (jobdir / "abbruch").write_text(str(int(time.time())), encoding="utf-8")
    stop_units(job)
    log(f"cancel {job}", pflicht=True)
    emit({"ok": True})
    return EXIT_OK


NETZPROBE = r"""
import errno, socket, sys
def ziel(host, port, proto=0, timeout=4):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM, proto)
    except PermissionError: return "zu"
    except OSError as e: return "fehler-" + errno.errorcode.get(e.errno, str(e.errno))
    s.settimeout(timeout)
    try:
        s.connect((host, port)); return "offen"
    except PermissionError: return "zu"
    except OSError as e:
        if e.errno in (errno.EHOSTUNREACH, errno.ENETUNREACH): return "zu"
        if isinstance(e, socket.timeout): return "zeit"
        return "fehler-" + errno.errorcode.get(e.errno, str(e.errno))
    except Exception as e: return "fehler-" + type(e).__name__
    finally: s.close()
def lauscher(port):
    try:
        s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(("127.0.0.1", port)); s.listen(1)
    except PermissionError: return None, "zu"
    except OSError as e: return None, "fehler-" + errno.errorcode.get(e.errno, str(e.errno))
    return s, "ok"
def eigener(port):
    s, r = lauscher(port)
    if s is None: return r
    try: return ziel("127.0.0.1", port)
    finally: s.close()
def fremd_binden(port):
    s, r = lauscher(port)
    if s is not None: s.close()
    return r
probe, bruecke, lan, eigen, fremd = int(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
werte = [("landlock", ziel("127.0.0.1", probe)), ("lo9", ziel("127.0.0.1", 9)), ("lo9mptcp", ziel("127.0.0.1", 9, 262)),
         ("netz10", ziel("10.255.255.254", 9)), ("netz10mptcp", ziel("10.255.255.254", 9, 262)),
         ("bruecke", ziel(bruecke, 9)), ("lan", ziel(lan, 443)),
         ("platz_eigen", eigener(eigen)), ("platz_fremd", ziel("127.0.0.1", fremd)), ("platz_fremd_bind", fremd_binden(fremd)),
         ("github", ziel("github.com", 443, timeout=10))]
print("wamo-netz " + " ".join("%s=%s" % w for w in werte), file=sys.stderr)
"""
# platz_eigen: ein eigener Lauscher im eigenen Teil der Entwicklungsports ist erreichbar. platz_fremd: ein Port eines anderen Platzes ist für
# connect zu (Landlock, EACCES; ohne die Sperre käme ECONNREFUSED oder offen), platz_fremd_bind: dort binden geht nicht.
NETZ_ERWARTET = {"landlock": "zu", "lo9": "zu", "lo9mptcp": "zu", "netz10": "zu", "netz10mptcp": "zu",
                 "bruecke": "zu", "lan": "zu", "platz_eigen": "offen", "platz_fremd": "zu", "platz_fremd_bind": "zu", "github": "offen"}
# Modus pruefen: kein Netz (eigener Netz-Namensraum), also ist alles zu. Das Internet wird per IP geprüft (ein Name ergäbe
# einen DNS-Fehler statt "zu"), auch GitHub, das im Lauf-Modus offen sein muss. Im leeren Netz-Namensraum ist Loopback an: Port 9
# dort ist "zu" oder "fehler-ECONNREFUSED" (es lauscht nichts); ein Rest-Zugang zum Host zeigte sich an internet und an
# /proc/net/dev (PRUEFEN_PRUEFUNGEN).
NETZPROBE_PRUEFEN = NETZPROBE.replace('("github", ziel("github.com", 443, timeout=10))', '("internet", ziel("1.1.1.1", 443, timeout=10))')
NETZ_ERWARTET_PRUEFEN = {**{k: ("zu",) for k in NETZ_ERWARTET if k != "github"}, "internet": ("zu",),
                         "lo9": ("zu", "fehler-ECONNREFUSED"), "platz_eigen": ("offen",)}  # Loopback im eigenen Namensraum, Landlock wie im Lauf
# Zusätzliche Grenzen, die nur im Modus pruefen gelten: nichts von Claude, kein Zustand des Auftrags, keine Token in der Umgebung,
# keine Netzschnittstelle außer lo, Git-Hooks aus
PRUEFEN_PRUEFUNGEN = [
    ("[ -e /srv/wamo/.claude ]", "Claude-Konfiguration sichtbar"),
    ("[ -e /srv/wamo/.local/share/claude ]", "Claude Code sichtbar"),
    ("[ -e /run/wamo/zustand ]", "Zustand des Auftrags sichtbar"),
    ("[ -n \"$(env | grep -E '^(ANTHROPIC_|CLAUDE_|GH_TOKEN|GITHUB_|VERCEL_|SUPABASE_|JIRA_|WAMO_)')\" ]", "Token oder Zugang in der Umgebung"),
    ("[ -n \"$(tail -n +3 /proc/net/dev | cut -d: -f1 | tr -d ' ' | grep -vx lo)\" ]", "Netzschnittstelle außer lo sichtbar"),
    ("[ \"$(git config --get core.hooksPath)\" != /dev/null ]", "Git-Hooks nicht abgeschaltet"),
]


def probe_lauscher(platz: int) -> socket.socket:
    """Lauschender Socket auf 127.0.0.1 im eigenen Teil der Entwicklungsports des Platzes (zufällig, erster freier), nie auf dem letzten Port
    (den nimmt die Netzprobe für den eigenen Lauscher). Er lauscht auf dem Host, wenn wamo-job.sh startet: Landlock muss ihn wie jeden Dienst
    des Hosts sperren, obwohl er im eigenen Bereich liegt."""
    import random
    ports = list(platz_ports(platz))[:-1]
    random.shuffle(ports)
    for port in ports[:50]:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            s.listen(1)
            return s
        except OSError:
            s.close()
    raise OSError("kein freier Port für die Landlock-Probe")


def docker_bruecke() -> str | None:
    """Adresse einer Docker-Bridge des Hosts (docker0 oder br-*), Ziel der Firewall-Probe."""
    try:
        p = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True, timeout=10,
                           env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"})
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in p.stdout.splitlines():
        teile = line.split()
        if len(teile) >= 4 and (teile[1] == "docker0" or teile[1].startswith("br-")):
            return teile[3].split("/")[0]
    return None


EPHEMERE_PORTS = Path("/proc/sys/net/ipv4/ip_local_port_range")


def ephemere_ports_getrennt(pfad: Path = EPHEMERE_PORTS) -> bool:
    """Liegt der Bereich der ephemeren Ports (bind auf Port 0, ausgehende Verbindungen) außerhalb der Entwicklungsports 20000-20999? Sonst
    könnte ein Auftrag über bind(0) einen Port im Teil eines anderen Platzes belegen (Befund des Sicherheitsreviews). Unlesbar heißt nein
    (fail closed); nur außerhalb von Linux (Tests unter Windows) gibt es die Datei nicht, dort gilt ja."""
    try:
        teile = pfad.read_text(encoding="ascii").split()
    except FileNotFoundError:
        return not sys.platform.startswith("linux")
    except (OSError, UnicodeDecodeError):
        return False
    if len(teile) != 2 or not all(t.isascii() and t.isdigit() for t in teile):
        return False
    von, bis = int(teile[0]), int(teile[1])
    return bis < ENTWICKLUNGS_PORTS.start or von > ENTWICKLUNGS_PORTS.stop - 1


def selbsttest(job: str, projekt: str, modus: str = "lauf", platz: int | None = None) -> tuple[bool, str]:
    """Führt den Hook-Befehl aus managed-settings.json in der Sandbox mit einem Sperrfall aus und prüft
    nebenbei die Grenzen. Bestanden nur, wenn der Wächter wirklich lief und genau mit der erwarteten
    Begründung ablehnt (ein Absturz mit Exit 2 sperrt im Betrieb auch, zählt hier aber nicht).
    modus "pruefen" läuft in der Sandbox des Befehls pruefen (wamo-job.sh --modus pruefen): kein Netz, nichts von Claude, kein
    Zustand, keine Token; erwartet wird dort überall "zu" und es gelten die zusätzlichen Prüfungen in PRUEFEN_PRUEFUNGEN.
    platz: der Platz, den der Aufrufer hält (Pflicht): die Sandbox des Selbsttests bekommt denselben Teil der Entwicklungsports wie der
    Lauf, die Netzprobe prüft ihn (eigener Lauscher erreichbar, Port des nächsten Platzes für connect und bind zu)."""
    pruefen = modus == "pruefen"
    try:
        eigen, fremd = platz_ports(platz)[-1], platz_ports((platz + 1) % PARALLEL_MAX)[-1]
    except (ValueError, TypeError):
        return False, "kein gültiger Platz für den Selbsttest"
    if not ephemere_ports_getrennt():
        return False, "der Bereich der ephemeren Ports überschneidet die Entwicklungsports 20000-20999 (net.ipv4.ip_local_port_range)"
    try:
        hook = json.loads(MANAGED.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return False, "managed-settings.json unlesbar"
    pp = f"{PROJEKTE}/{projekt}"
    pruefungen = [
        ("[ -e /etc/wamo ]", "/etc/wamo sichtbar"),
        ("[ -e /srv/wamo/.ssh ]", ".ssh sichtbar"),
        ("[ -e /usr/local/lib/wamo/bwrap ]", "bwrap-Kopie sichtbar"),
        ("[ -e /etc/docker ]", "/etc nicht auf die Allowlist begrenzt"),
        ("! [ -r /etc/claude-code/managed-settings.json ]", "managed-settings fehlt"),
        ("[ -w /run/wamo/zustand/approvals.json ]", "approvals beschreibbar"),
        ("! grep -q '^Seccomp:[[:space:]]*2' /proc/self/status", "seccomp nicht aktiv"),
        ("! grep -q '^NoNewPrivs:[[:space:]]*1' /proc/self/status", "no_new_privs nicht gesetzt"),
        ("! grep -qE '^CapEff:[[:space:]]*0+$' /proc/self/status", "Capabilities nicht leer"),
        ("unshare -U true 2>/dev/null", "Benutzer-Namensraum anlegbar (seccomp/disable-userns wirkt nicht)"),
        ("umbenennen /opt/wamo /opt/wamo-x", "Wächterordner umbenennbar"),
        ("umbenennen /opt/wamo/waechter /opt/wamo/x", "Wächter umbenennbar"),
        ("mkdir /opt/wamo/neu 2>/dev/null", "Wächterordner beschreibbar"),
        ("touch /opt/wamo/waechter/x 2>/dev/null", "Wächter beschreibbar"),
        ("umbenennen /srv/wamo/projekte /srv/wamo/projekte-x", "Projekte-Ordner umbenennbar"),
        (f"umbenennen {pp} {pp}-x", "Projektordner umbenennbar"),
        ("mkdir /srv/wamo/projekte/neu 2>/dev/null", "Projekte-Ordner beschreibbar"),
        ("ln -sfn / /run/wamo/projekt 2>/dev/null", "Projektverweis ersetzbar"),
        (f"[ \"$(readlink -f /run/wamo/projekt)\" != {pp} ]", "Projektverweis zeigt woanders hin"),
    ]
    if pruefen:
        pruefungen += PRUEFEN_PRUEFUNGEN
    # Nur rename(2), nie mv: mv kopiert bei EXDEV und löscht danach die Quelle, im Projektordner also dessen Inhalt
    umbenennen = "umbenennen() { /usr/bin/python3 -I -c 'import os,sys; os.rename(sys.argv[1], sys.argv[2])' \"$1\" \"$2\" 2>/dev/null; }"
    teile = ["f=0", umbenennen] + [f"if {bed}; then echo 'wamo-pruefung: {text}' >&2; f=1; fi" for bed, text in pruefungen]
    # Probe-Lauscher im eigenen Bereich, den der Ausgangsfilter auf Loopback zulässt: nur Landlock darf ihn sperren (Dienst des Hosts)
    probe = probe_lauscher(platz)
    port = probe.getsockname()[1]
    bruecke = docker_bruecke()  # N1: None heißt ip fehlt oder keine Bridge -> Fehler, kein stummes Überspringen
    if bruecke is None:
        probe.close()
        return False, "Docker-Bridge nicht ermittelbar (ip fehlt oder keine Bridge); Netzprobe nicht möglich"
    netzprobe = NETZPROBE_PRUEFEN if pruefen else NETZPROBE
    teile += [f"/usr/bin/python3 -I -c '{netzprobe}' {port} {bruecke} {LAN_PROBE} {eigen} {fremd}",
              f"( {hook} ); c=$?; echo \"wamo-selbsttest code=$c fehler=$f\" >&2"]
    argv = [str(RUNNER), "--auftrag", job, "--projekt", projekt, "--platz", str(platz), "--zeitlimit", "60", "--einheit-zusatz",
            "pruefung", *(["--modus", "pruefen"] if pruefen else []), "--", "/bin/sh", "-c", "; ".join(teile)]
    try:
        p = subprocess.run(argv, input=json.dumps(SELFTEST_EVENT).encode(), capture_output=True,
                           env=pruefen_env() if pruefen else basis_env(), timeout=120, cwd="/")  # wie der echte Aufruf: Git-Hooks aus
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"Sandbox nicht startbar ({type(e).__name__})"
    finally:
        probe.close()
    err = p.stderr.decode("utf-8", "replace")[-20000:]
    m = re.search(r"wamo-selbsttest code=(\d+) fehler=(\d)", err)
    if not m:
        return False, "Sandbox oder Hook lief nicht: " + err.strip()[-300:]
    code, fehler = int(m.group(1)), m.group(2) == "1"
    if fehler:
        return False, "Grenzen verletzt: " + " ".join(re.findall(r"wamo-pruefung: [^\n]+", err))
    netz = re.search(r"wamo-netz (.+)", err)
    if not netz:
        return False, "Netzprobe lief nicht"
    werte = dict(w.split("=", 1) for w in netz.group(1).split() if "=" in w)
    erwartet = NETZ_ERWARTET_PRUEFEN if pruefen else NETZ_ERWARTET
    abweichend = {k: werte.get(k, "?") for k, v in erwartet.items() if werte.get(k) not in ((v,) if isinstance(v, str) else v)}
    if abweichend:
        return False, "Netzgrenzen nicht wie erwartet: " + ", ".join(f"{k}={v}" for k, v in abweichend.items())
    try:
        antwort = json.loads(p.stdout.decode("utf-8", "replace"))["hookSpecificOutput"]
        decision, grund = antwort["permissionDecision"], str(antwort.get("permissionDecisionReason", ""))
    except (ValueError, KeyError, TypeError, RecursionError):
        decision, grund = None, ""
    if code == 0 and decision == "deny" and grund.startswith(SELFTEST_GRUND):
        return True, "Hook lehnt ab, Grenzen und Netz geprüft"
    return False, f"Hook lieferte nicht die erwartete Ablehnung (Exit {code}, Entscheidung {decision})"


def aufraeumen() -> None:
    """Räumt als wamo alte Auftrags-Caches auf (N5: nicht als root über Sandbox-beschreibbare Ordner).
    npm/cache/plugin-daten nach 7 Tagen, claude/ nach 30 Tagen; Projektordner, Buchführung und Sperren bleiben.
    Best effort; Fehler stören den Lauf nicht. Folgt keinem Link (ein Link als Cache-Ordner wird entfernt). Jeden Auftrag nur unter seiner
    Auftragssperre (.lauf): mit gleichzeitigen Aufträgen könnte ein anderer Dispatcher ihn sonst genau jetzt starten und seine Caches nutzen."""
    import shutil
    jetzt = time.time()
    alter = {"npm": 7 * 86400, "cache": 7 * 86400, "plugin-daten": 7 * 86400, "claude": 30 * 86400}
    try:
        jobs = [e.name for e in os.scandir(JOBS) if e.is_dir() and not e.is_symlink() and JOB_RE.fullmatch(e.name)]
    except OSError:
        return
    for job in jobs[:500]:
        sperre = Sperre(JOBS / job / ".lauf")
        try:
            if not sperre.versuchen():
                continue  # läuft oder startet gerade
        except OSError:
            continue
        try:
            for teil, grenze in alter.items():
                p = JOBS / job / teil
                try:
                    st = p.lstat()
                except OSError:
                    continue
                if stat.S_ISLNK(st.st_mode):
                    p.unlink(missing_ok=True)
                    continue
                if stat.S_ISDIR(st.st_mode) and jetzt - st.st_mtime > grenze:
                    shutil.rmtree(p, ignore_errors=True)
        finally:
            _sperre_freigeben(sperre)


def _zeile_lesen(limit: int, was: str, fehler=Abgewiesen) -> bytes:
    """Eine Zeile von stdin, höchstens limit Bytes, innerhalb von 30 Sekunden."""
    def zu_spaet(*_):
        raise fehler(f"{was} kam nicht rechtzeitig")
    signal.signal(signal.SIGALRM, zu_spaet)
    signal.alarm(30)
    try:
        return sys.stdin.buffer.readline(limit)
    finally:
        signal.alarm(0)


class StdinLeser:
    """Liest stdin (fd 0) ohne Kopien in Python-Objekte: alles landet in einem festen bytearray, eine Zeile ist ein memoryview darauf.
    Kein sys.stdin, kein readline (dessen Puffer hielte eine nachfolgende GitHub-Zeile als bytes fest). Ab Dispatcher 10 liest start so von
    Anfang an (C.2.2), auch die Kopfzeile, weil die GitHub-Zeile im selben Lesevorgang mitkommen kann. Nach dem Lesen der Zeilen bleibt stdin
    die Lebenslinie: bis_eof liest in einen eigenen kleinen Puffer, der jedes Mal überschrieben wird. Wirft nie mit dem Inhalt."""

    def __init__(self, fd: int = 0, groesse: int = STDIN_PUFFER):
        self.fd = fd
        self.puffer = bytearray(groesse)
        self.anfang = 0  # Beginn der noch nicht gelieferten Daten
        self.ende = 0  # Ende der gelesenen Daten
        self.eof = False

    def _lesen(self, frist: float | None) -> int:
        """Liest einmal an das Ende der Daten. 0 bei EOF oder vollem Puffer; wirft _Zeitueberschreitung nach der Frist."""
        if self.ende >= len(self.puffer):
            return 0
        if frist is not None:
            try:
                import select
                rest = max(0.0, frist - time.monotonic())
                bereit, _, _ = select.select([self.fd], [], [], rest)
                if not bereit:
                    raise _Zeitueberschreitung()
            except (OSError, ValueError, ImportError):
                pass  # kein select für diesen Deskriptor (nur Tests unter Windows): ohne Frist lesen
        ansicht = memoryview(self.puffer)
        try:
            if hasattr(os, "readv"):
                n = os.readv(self.fd, [ansicht[self.ende:]])
            else:  # nur Tests unter Windows
                stueck = os.read(self.fd, len(self.puffer) - self.ende)
                n = len(stueck)
                ansicht[self.ende:self.ende + n] = stueck
        finally:
            ansicht.release()
        if n == 0:
            self.eof = True
        self.ende += n
        return n

    def zeile(self, limit: int, was: str, fehler=Abgewiesen, frist_s: float = LESEN_FRIST_S) -> memoryview:
        """Die nächste Zeile mit Zeilenende, höchstens limit Bytes (wie readline(limit): ohne Zeilenende bei EOF oder Grenze, der Prüfer
        lehnt sie dann ab). Kommt in frist_s Sekunden nichts Vollständiges, wirft fehler("<was> kam nicht rechtzeitig")."""
        frist = time.monotonic() + frist_s
        while True:
            pos = self.puffer.find(b"\n", self.anfang, min(self.ende, self.anfang + limit))
            if pos >= 0:
                von, self.anfang = self.anfang, pos + 1
                return memoryview(self.puffer)[von:pos + 1]
            if self.ende - self.anfang >= limit or self.eof or self.ende >= len(self.puffer):
                von = self.anfang
                self.anfang = min(self.ende, von + limit)
                return memoryview(self.puffer)[von:self.anfang]
            try:
                self._lesen(frist)
            except _Zeitueberschreitung:
                raise fehler(f"{was} kam nicht rechtzeitig") from None

    def ueberschreiben(self, von: int = 0, bis: int | None = None) -> None:
        """Überschreibt einen Bereich (Standard: alles Gelesene) mit Nullen, ohne die Größe zu ändern."""
        bis = self.ende if bis is None else bis
        if bis > von:
            self.puffer[von:bis] = bytes(bis - von)

    def rest_verwerfen(self) -> None:
        """Was nach den gelesenen Zeilen schon im Puffer steht (etwa eine GitHub-Zeile im Folgelauf), ungelesen überschreiben."""
        self.ueberschreiben(self.anfang, self.ende)
        self.anfang = self.ende

    def bis_eof(self) -> None:
        """Lebenslinie: blockiert bis EOF. Liest in einen eigenen Puffer, der nach jedem Lesen überschrieben wird."""
        self.rest_verwerfen()
        if self.eof:
            return
        klein = bytearray(65536)
        ansicht = memoryview(klein)
        try:
            while True:
                if hasattr(os, "readv"):
                    n = os.readv(self.fd, [ansicht])
                else:
                    n = len(os.read(self.fd, len(klein)))
                if n == 0:
                    self.eof = True
                    return
                klein[:n] = bytes(n)
        finally:
            ansicht.release()


LESER: StdinLeser | None = None  # der Leser dieses Aufrufs (start, einreichen); None: noch nichts über ihn gelesen


def _leser() -> StdinLeser:
    global LESER
    if LESER is None:
        LESER = StdinLeser(0)
    return LESER


def _als_bytes(zeile: memoryview, fehler=Abgewiesen) -> bytes:
    """Eine Zeile ohne Geheimnis als bytes. Steht an dieser Stelle eine GitHub-Zeile (falsche Reihenfolge), wird sie überschrieben und
    abgewiesen, ohne je zu bytes oder str zu werden."""
    try:
        if zeile[:len(GITHUB_ZEILE_KOPF)] == GITHUB_ZEILE_KOPF:
            zeile[:] = bytes(len(zeile))
            raise fehler("GitHub-Zeile an falscher Stelle")
        return zeile.tobytes()
    finally:
        zeile.release()


def _kopfzeile_lesen() -> bytes:
    return _als_bytes(_leser().zeile(MAX_HEADER_BYTES + 1, "Kopfzeile"))


def _zugangszeile_lesen() -> bytes:
    return _als_bytes(_leser().zeile(MAX_ZUGANG_BYTES + 1, "Zugangszeile", ZugangUngueltig), ZugangUngueltig)


def _lebenslinie_warten() -> None:
    """Blockiert, bis stdin endet. Mit dem eigenen Leser (start ab Dispatcher 10) über ihn, sonst wie bisher über sys.stdin."""
    if LESER is not None:
        LESER.bis_eof()
        return
    while sys.stdin.buffer.read1(65536):
        pass


class GithubGeheimnis:
    """Das GitHub-Token eines Aufrufs als Ausschnitt des Lesepuffers: nie str, nie bytes, nicht darstellbar, nicht kopierbar. Es geht nur
    über in_pipe (Credential-Helfer) und kopfzeile (Authorization für api.github.com) hinaus; ueberschreiben setzt es auf Nullen."""

    __slots__ = ("_puffer", "_von", "_bis")

    def __init__(self, puffer: bytearray, von: int, bis: int):
        self._puffer, self._von, self._bis = puffer, von, bis

    def __repr__(self) -> str:
        return "GithubGeheimnis(<verborgen>)"

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("GithubGeheimnis lässt sich nicht kopieren")

    def __copy__(self):
        raise TypeError("GithubGeheimnis lässt sich nicht kopieren")

    def __deepcopy__(self, _memo):
        raise TypeError("GithubGeheimnis lässt sich nicht kopieren")

    @property
    def gueltig(self) -> bool:
        return self._bis > self._von and any(self._puffer[self._von:self._von + 4])

    def ansicht(self) -> memoryview:
        """memoryview auf das Token (für Schwärzung und Vergleich); der Aufrufer gibt es mit release() frei."""
        return memoryview(self._puffer)[self._von:self._bis]

    def in_pipe(self, benutzer: bytes = GIT_BENUTZER) -> int:
        """Eine Pipe mit genau "username=<benutzer>\\npassword=<token>\\n" (für wamo-git-zugang); liefert das Leseende, das Schreibende
        ist geschlossen. Geschrieben mit writev aus dem Puffer, ohne eine zusammengesetzte Kopie."""
        r, w = os.pipe()
        try:
            ansicht = self.ansicht()
            try:
                teile = [b"username=", benutzer, b"\npassword=", ansicht, b"\n"]
                if hasattr(os, "writev"):
                    os.writev(w, teile)
                else:  # nur Tests unter Windows
                    for teil in teile:
                        os.write(w, teil)
            finally:
                ansicht.release()
        except BaseException:
            os.close(r)
            raise
        finally:
            os.close(w)
        return r

    def kopfzeile(self) -> bytearray:
        """"Bearer <token>" als eigenes bytearray für die Kopfzeile Authorization; der Aufrufer überschreibt es danach."""
        praefix = b"Bearer "
        wert = bytearray(len(praefix) + self._bis - self._von)  # feste Größe: kein Umkopieren beim Wachsen
        wert[:len(praefix)] = praefix
        ansicht = self.ansicht()
        try:
            wert[len(praefix):] = ansicht
        finally:
            ansicht.release()
        return wert

    def ueberschreiben(self) -> None:
        if self._bis > self._von:
            self._puffer[self._von:self._bis] = bytes(self._bis - self._von)


class GithubZeileFehlt(Exception):
    """Die GitHub-Zeile fehlt, kam nicht rechtzeitig oder hat nicht genau die Form aus C.2.2. Nennt nie den Inhalt."""


def github_zeile_pruefen(leser: StdinLeser, zeile: memoryview) -> GithubGeheimnis:
    """Prüft die GitHub-Zeile mit einer Bytes-Regel auf dem memoryview (ohne Zeilenende genau {"typ":"github","wert":"<token>"}, ohne
    Leerzeichen, mit Zeilenende höchstens MAX_GITHUB_ZEILE Bytes) und liefert das Token als Ausschnitt des Lesepuffers: es beginnt nach
    GITHUB_ZEILE_KOPF und endet vor den letzten drei Zeichen (Anführungszeichen, Klammer, Zeilenende). Nur fullmatch und Positionen, nie
    group(). Bei falscher Form wird die Zeile überschrieben und GithubZeileFehlt geworfen."""
    von = leser.anfang - len(zeile)  # zeile endet genau am Lesezeiger (StdinLeser.zeile)
    try:
        passt = (len(zeile) <= MAX_GITHUB_ZEILE and zeile.obj is leser.puffer and von >= 0 and zeile[-1:] == b"\n"
                 and GITHUB_ZEILE_RE.fullmatch(zeile[:-1]) is not None)
        if not passt:
            leser.ueberschreiben(max(0, von), leser.anfang)
            raise GithubZeileFehlt("GitHub-Zeile hat nicht die erwartete Form")
        return GithubGeheimnis(leser.puffer, von + len(GITHUB_ZEILE_KOPF), von + len(zeile) - 3)
    finally:
        zeile.release()


def _githubzeile_lesen() -> GithubGeheimnis:
    leser = _leser()
    try:
        zeile = leser.zeile(MAX_GITHUB_ZEILE + 1, "GitHub-Zeile", GithubZeileFehlt)
    except GithubZeileFehlt:
        raise GithubZeileFehlt("GitHub-Zeile kam nicht rechtzeitig") from None
    if len(zeile) == 0:
        zeile.release()
        raise GithubZeileFehlt("GitHub-Zeile fehlt")
    return github_zeile_pruefen(leser, zeile)


def _einreichen_zeile_lesen() -> bytes:
    """Erste stdin-Zeile von einreichen (höchstens MAX_EINREICHEN_ZEILE Bytes, kein Geheimnis)."""
    return _als_bytes(_leser().zeile(MAX_EINREICHEN_ZEILE + 1, "Einreichen-Zeile"))


def nicht_dumpbar() -> bool:
    """Ist dieser Prozess nicht dumpable (PR_GET_DUMPABLE liefert 0)? speicher_begrenzen setzt es beim Start; vor dem Lesen eines GitHub-Tokens
    wird es erneut gesetzt und geprüft (C.2.2). Ohne prctl (nicht Linux) False."""
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE=0
        return libc.prctl(3, 0, 0, 0, 0) == 0  # PR_GET_DUMPABLE
    except (OSError, AttributeError, ValueError, TypeError):
        return False


def kontingent_modul():
    """Parser für rate_limit_event (kontingent.py aus /opt/wamo/waechter); None, wenn die Kopie fehlt."""
    try:
        return _modul("kontingent")
    except Exception:  # fehlt oder defekt: ohne Kontingent weiterlaufen, der Auftrag ist wichtiger
        return None


def kontingent_ereignis(modul, raw: bytes) -> dict | None:
    """Ereignis kontingent aus einer Zeile von Claude Code (nur Felder der Allowlist) oder None. Die Zeile kommt aus der
    Sandbox: was nicht passt, wirft nie, sondern ergibt None."""
    try:
        return modul.ereignis_aus_zeile(json.loads(raw))
    except Exception:  # ungültiges JSON, zu tief verschachtelt, absurde Zahlen: ohne Ereignis weiter
        return None


def schwaerzungen(env: dict[str, str]) -> list[tuple[bytes, bytes]]:
    """Geheimnisse dieses Laufs, die in der Ausgabe des Agenten nicht erscheinen sollen: (Wert, Ersatz). Mindestens 8
    Zeichen (kürzere Werte sind keine Schlüssel und würden Text zerstören)."""
    out = []
    for name, ersatz in (("GH_TOKEN", b"[GH_TOKEN]"), ("CLAUDE_CODE_OAUTH_TOKEN", ZUGANG_ERSATZ),
                         ("ANTHROPIC_API_KEY", ZUGANG_ERSATZ)):
        wert = env.get(name, "")
        if len(wert) >= 8:
            out.append((wert.encode("utf-8"), ersatz))
    return out


def schwaerzen(daten: bytes, ersetzungen: list[tuple[bytes, bytes]]) -> bytes:
    """Ersetzt die Werte dieses Laufs wörtlich und danach alles, was wie ein Anthropic-Schlüssel, ein Auftragstoken für
    Hausmodelle oder ein GitHub-Token aussieht (das Token dieses Laufs steht als ANTHROPIC_API_KEY schon in den Ersetzungen; ein Wert
    darf auch ein memoryview sein, das exakte GitHub-Token des persönlichen Wegs wird nie zu bytes)."""
    for wert, ersatz in ersetzungen:
        daten = daten.replace(wert, ersatz)
    if b"sk-ant-" in daten:
        daten = SK_ANT_RE.sub(ZUGANG_ERSATZ, daten)
    if b"wh1-" in daten:
        daten = HAUS_TOKEN_RE.sub(ZUGANG_ERSATZ, daten)
    if b"gh" in daten:
        daten = GH_PAT_RE.sub(GH_PAT_ERSATZ, daten)
    return daten


def _datei_schwaerzen(pfad: str, ordner: str, ersetzungen: list[tuple[bytes, bytes]]) -> str:
    """Eine reguläre Datei (ohne Link) schwärzen. Ergebnis: "unveraendert", "geschwaerzt", "entfernt" (nicht prüfbar, zu
    groß oder nicht ersetzbar: fail-closed gelöscht) oder "offen" (weder geschwärzt noch gelöscht)."""
    flags = os.O_RDONLY | O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    tmp = None
    try:
        fd = os.open(pfad, flags)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                return "unveraendert"
            if st.st_size > MAX_SCHWAERZ_DATEI:
                raise OSError("zu groß")
            with os.fdopen(fd, "rb", closefd=False) as f:
                daten = f.read()
        finally:
            os.close(fd)
        neu = schwaerzen(daten, ersetzungen)
        if neu == daten:
            return "unveraendert"
        tmp_fd, tmp = tempfile.mkstemp(dir=ordner, prefix=".schwaerzen.")
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(neu)
        os.chmod(tmp, stat.S_IMODE(st.st_mode))
        os.replace(tmp, pfad)
        return "geschwaerzt"
    except OSError:
        # nicht lesbar, zu groß oder nicht ersetzbar: fail-closed, die Datei wird entfernt (Sitzungsdaten sind nur
        # eine Zugabe für --resume, ein Zugangswert darf nicht überleben)
        if tmp:
            Path(tmp).unlink(missing_ok=True)
        try:
            os.unlink(pfad)
        except OSError:
            return "offen"
        return "entfernt"


def zugang_aus_dateien_entfernen(wurzel: Path, ersetzungen: list[tuple[bytes, bytes]]) -> tuple[int, int]:
    """Schwärzt Zugangswerte in allen Dateien unter wurzel (der Konfigordner claude/ des Auftrags mit den Sitzungen
    für --resume): dort landet ein Wert, den der Agent trotz Sperre ausgibt, als Werkzeugergebnis. Läuft nach dem Ende
    der Sandbox, ohne Links zu folgen (nur reguläre Dateien, O_NOFOLLOW), mit Grenzen für Zahl und Zeit. Liefert
    (geändert, offen): offen zählt alles, was nicht geprüft oder nicht bereinigt werden konnte (nicht lesbare Ordner,
    Dateien, die sich weder schwärzen noch löschen ließen, Überschreiten der Grenzen)."""
    if not ersetzungen or wurzel.is_symlink() or not wurzel.is_dir():
        return 0, 0
    geaendert = offen = geprueft = 0
    ende = time.monotonic() + SCHWAERZ_ZEIT_S

    def fehler(_e: OSError) -> None:
        nonlocal offen
        offen += 1
    for ordner, unterordner, dateien in os.walk(wurzel, followlinks=False, onerror=fehler):
        unterordner[:] = [d for d in unterordner if not os.path.islink(os.path.join(ordner, d))]
        for name in dateien:
            geprueft += 1
            if geprueft > MAX_SCHWAERZ_DATEIEN or time.monotonic() > ende:
                return geaendert, offen + 1
            ergebnis = _datei_schwaerzen(os.path.join(ordner, name), ordner, ersetzungen)
            if ergebnis in ("geschwaerzt", "entfernt"):
                geaendert += 1
            elif ergebnis == "offen":
                offen += 1
    return geaendert, offen


def _baum_entfernen(pfad: Path) -> None:
    """Entfernt einen Ordner samt Inhalt, auch wenn die Sandbox Rechte entzogen hat (ohne Links zu folgen)."""
    import shutil

    def frei(funktion, p, _exc):
        try:
            eltern = os.path.dirname(p)
            if not os.path.islink(eltern):
                os.chmod(eltern, 0o700)
            if not os.path.islink(p):  # chmod folgt Links: nie die Rechte einer fremden Datei ändern
                os.chmod(p, 0o700)
            funktion(p)
        except OSError:
            pass
    if pfad.is_dir() and not pfad.is_symlink():
        _ordner_freigeben(pfad)
        shutil.rmtree(pfad, onerror=frei)


def _ordner_freigeben(pfad: Path) -> None:
    """Setzt u+rwx auf jeden Ordner unter pfad, von oben nach unten und bevor os.walk hineingeht, ohne Links zu folgen (lstat): ein
    Ordner mit Modus 000, den die Sandbox gepflanzt hat, hält das Löschen so nicht auf. Wirft nie."""
    try:
        if stat.S_ISDIR(os.lstat(pfad).st_mode):
            os.chmod(pfad, stat.S_IMODE(os.lstat(pfad).st_mode) | 0o700)
    except OSError:
        return
    for wurzel, ordner, _dateien in os.walk(pfad, followlinks=False):
        for name in ordner:
            p = os.path.join(wurzel, name)
            try:
                st = os.lstat(p)
                if stat.S_ISDIR(st.st_mode):
                    os.chmod(p, stat.S_IMODE(st.st_mode) | 0o700)
            except OSError:
                continue


def zugang_aufraeumen(jobdir: Path, job: str, ersetzungen: list[tuple[bytes, bytes]]) -> None:
    """Nach dem Lauf: Zugangswerte aus claude/ schwärzen. Bleibt etwas offen, gehen die Sitzungsdaten (projects/)
    verloren statt den Wert zu behalten; das Audit nennt nur Zahlen. Wirft nie."""
    try:
        geaendert, offen = zugang_aus_dateien_entfernen(jobdir / "claude", ersetzungen)
        if offen:
            _baum_entfernen(jobdir / "claude" / "projects")
            log(f"schwaerzen_unvollstaendig {job}: {offen} offen, Sitzungsdaten entfernt")
        elif geaendert:
            log(f"schwaerzen {job}: {geaendert} Dateien unter claude/")
    except Exception as e:  # noqa: BLE001 (Aufräumen darf den Abschluss des Auftrags nie verhindern)
        log(f"schwaerzen {job} FEHLER {type(e).__name__}")


# ---------------------------------------------------------------- Kern-Kanal (Version 7): Einhängepunkte, die Regeln stehen in wamo_job_kernkanal.py
def kern_modul():
    """Das Kern-Kanal-Modul: in /opt/wamo/waechter installiert, im Repo neben dieser Datei. Es wird erst beim ersten Gebrauch geladen
    (jeder ssh-Aufruf, ping); fehlt es oder ist es defekt, wirft das Laden."""
    geladen = sys.modules.get("wamo_job_kernkanal")
    if geladen is not None:
        return geladen
    if (WAECHTER / "wamo_job_kernkanal.py").is_file():
        return _modul("wamo_job_kernkanal")
    import importlib.util
    spec = importlib.util.spec_from_file_location("wamo_job_kernkanal", Path(__file__).resolve().with_name("wamo_job_kernkanal.py"))
    modul = importlib.util.module_from_spec(spec)
    sys.modules["wamo_job_kernkanal"] = modul
    try:
        spec.loader.exec_module(modul)
    except BaseException:
        sys.modules.pop("wamo_job_kernkanal", None)
        raise
    return modul


def kern_zustand():
    """Notaus-Datei und Konfiguration des Kern-Kanals, jedes Mal frisch gelesen (Regeln 1 und 2)."""
    k = kern_modul()
    return k.kanal_zustand(KERN_PFADE or k.PFADE, lesen=KERN_LESER or k.datei_lesen, bekannte_arten=werkzeugkarte().AUFTRAGSARTEN)


def _kern_vorhanden(pfad) -> bool:
    try:
        os.lstat(pfad)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        return True  # unlesbar heißt vorhanden
    return True


def kanal_ermitteln() -> str | None:
    """Kanal dieser Verbindung: lokal, pc oder kern; None, wenn die Herkunft im strikten Modus unklar ist. Fehlt das Modul oder ist
    es defekt, gilt ssh ohne Kern-Schlüssel und ohne kernkanal.conf (Stufe 0) weiter als pc, sonst als unklar (fail-closed)."""
    ssh = "SSH_CONNECTION" in os.environ or "SSH_ORIGINAL_COMMAND" in os.environ
    try:
        k = kern_modul()
        uid = KERN_UID if KERN_UID is not None else (os.getuid() if hasattr(os, "getuid") else None)
        return k.kanal_bestimmen(os.environ, KERN_PFADE or k.PFADE, lesen=KERN_LESER or k.datei_lesen, eigene_uid=uid).kanal
    except Exception:  # noqa: BLE001 (Modul fehlt oder ist defekt)
        if not ssh:
            return "lokal"
        pfade = KERN_PFADE
        strikt = _kern_vorhanden(pfade.kern_schluessel if pfade else "/etc/ssh/authorized_keys.d/wamo-kern") \
            or _kern_vorhanden(pfade.konfig if pfade else "/etc/wamo/kernkanal.conf")
        return None if strikt else "pc"


def kernkanal_ping() -> dict:
    """Das Objekt kernkanal der ping-Antwort (I7). Wirft nie; ein Fehler sieht aus wie ein geschlossener, fehlerhafter Kanal."""
    try:
        k = kern_modul()
        pfade = KERN_PFADE or k.PFADE
        return k.kernkanal_bericht(kern_zustand(), k.existiert(pfade.kern_schluessel) or k.existiert(pfade.konfig))
    except Exception:  # noqa: BLE001 (ping muss immer antworten)
        return {"strikt": True, "offen": False, "grund": "konfig_ungueltig", "arten": [], "repos": [], "ablauf": None, "tage_rest": None}


def kanal_abweisen(grund: str) -> int:
    """Ereignis kanal_gesperrt (I6, Grund aus KANAL_GRUENDE) und Exit 2. Nie mit Token, nie mit einem Wert aus geheim.env."""
    log(f"kanal_gesperrt grund={grund}")
    wamo_event("kanal_gesperrt", grund=grund)
    print(f"WAMO-Auftrag abgewiesen: Kanal gesperrt ({grund})", file=sys.stderr)
    return EXIT_ABGEWIESEN


def kern_befehl_pruefen(name: str, args: list[str]) -> str | None:
    """Regeln 1 bis 4 für einen Befehl aus dem Kern-Kanal: None (erlaubt) oder ein Code. In den anderen Kanälen immer None.
    start prüft cmd_start selbst, nach dem Lesen der Kopfzeile."""
    if KANAL != "kern":
        return None
    k = kern_modul()
    grund = k.pruefe_befehl(name, kern_zustand())
    if grund is None and name in ("status", "pending", "approve", "cancel", *BEFEHLE_PERSOENLICH):
        meta = read_json(JOBS / args[0] / "auftrag.json", None)
        grund = k.pruefe_eigener_auftrag(meta)
        if grund is None and name in BEFEHLE_PERSOENLICH and meta.get("profil") != args[1]:
            grund = "fremd"  # Regel 4 mit profil (C.2.3): der Auftrag gehört einem anderen Profil
    return grund


def kern_projekt_lage(projekt: str, repo: str | None, profil: str | None = None) -> tuple[bool, bool, bool]:
    """(fremd, kollision, profil_fremd) für den Projektordner eines Starts im Kern-Kanal. fremd: der Ordner besteht (oder ein Link steht dort),
    aber kein Auftrag mit kanal=kern hat ihn angelegt (die Auftragsordner sind für die Sandbox unsichtbar, ein Marker im Projektordner wäre
    fälschbar): der Kern-Auftrag liefe sonst in fremdem Inhalt. kollision: ein Kern-Auftrag hat denselben Ordner mit einem anderen Repo belegt
    (my_repo und my-repo ergeben beide kern-my-repo). profil_fremd: ein Kern-Auftrag eines anderen Profils (oder einer ohne Kennung) hat
    denselben Ordner angelegt; so sieht ein Profil nie die Ergebnisse eines anderen."""
    belegt: list[str | None] = []
    profile: list[object] = []
    gefunden = False
    if JOBS.is_dir():
        for meta_pfad in JOBS.glob("*/auftrag.json"):
            meta = read_json(meta_pfad, None)
            if isinstance(meta, dict) and meta.get("kanal") == "kern" and meta.get("projekt") == projekt:
                gefunden = True
                belegt.append(meta.get("repo") if isinstance(meta.get("repo"), str) else None)
                profile.append(meta.get("profil"))
    ordner = PROJEKTE / projekt
    fremd = (ordner.is_symlink() or os.path.lexists(ordner)) and (ordner.is_symlink() or not gefunden)
    k = kern_modul()
    return fremd, k.repo_kollision(repo, belegt), k.profil_fremd(profil, profile)


def kern_start_pruefen(job: str, projekt: str, art: str, kopf: Kopf, app_modus: bool, eigener_versuch: bool = False):
    """Regeln 1 bis 7 und 9 für einen Start aus dem Kern-Kanal. Liefert (Code oder None, Konfiguration). Liest keine Geheimnisse:
    app_modus ist vor dem Lesen von geheim.env nicht bekannt (die erste Prüfung nimmt True an, die zweite den echten Wert).
    eigener_versuch: die zweite Prüfung zählt den Versuch dieses Starts, den die erste schon gebucht hat, nicht mit."""
    k = kern_modul()
    pfade = KERN_PFADE or k.PFADE
    zustand = kern_zustand()
    wk = werkzeugkarte()
    meta_pfad = JOBS / job / "auftrag.json"
    projekt_fremd, projekt_kollision, projekt_profil_fremd = kern_projekt_lage(projekt, kopf.repo, kopf.profil)
    anfrage = k.StartAnfrage(
        job=job, projekt=projekt, art=art, repo=kopf.repo, zugang=kopf.zugang, profil=kopf.profil,
        github=wk.github_stufe(art) is not None, dienste=tuple(sorted(set(wk.KARTEN[art].zugaenge) - {"github", "github_lesen"})),
        app_modus=app_modus, fremd=meta_pfad.exists() and k.pruefe_eigener_auftrag(read_json(meta_pfad, None)) is not None,
        projekt_fremd=projekt_fremd, projekt_kollision=projekt_kollision, projekt_profil_fremd=projekt_profil_fremd,
        persoenlich=kopf.github == GITHUB_WEG)
    try:
        ereignisse = k.zaehler_lesen(pfade.zaehler)
    except OSError:
        ereignisse = None  # nicht lesbar: die Grenzen sind nicht prüfbar, Regel 9 sperrt
    if eigener_versuch and ereignisse is not None:
        eigene = [i for i, e in enumerate(ereignisse) if e["ereignis"] == "versuch" and e["job"] == job]
        if eigene:
            del ereignisse[eigene[-1]]
    grund = k.pruefe_start(anfrage, zustand, ereignisse=ereignisse, jetzt=time.time(), freier_platz_mb=k.freier_platz_mb(pfade.platz),
                           laufzeit_reserve_s=lauf_zeitlimit_s())  # laufende Aufträge zählen mit ihrem Zeitlimit (gleichzeitige Läufe)
    return grund, zustand.konfig


def kern_versuch_buchen(job: str, profil: str | None = None) -> bool:
    """Bucht den Versuch (Ereignis versuch im Zähler, mit der Kennung des Profils), sobald ein Start die erste Prüfung besteht: auch Starts,
    die später an einer Sperre scheitern (belegt, zugang_erweitert, App-Fehler), zählen so gegen die Grenze je Stunde (gesamt und je
    Profil). False, wenn der Zähler nicht schreibbar ist."""
    k = kern_modul()
    try:
        k.zaehler_schreiben((KERN_PFADE or k.PFADE).zaehler, job, "versuch", time.time(), profil=profil)
    except OSError:
        return False
    return True


def kern_fork_grund(repo: str | None, token: str) -> str | None:
    """Regel 8: die Metadaten des Repos bei GitHub abfragen (mit dem Token dieses Laufs) und prüfen. Unklar heißt gesperrt."""
    if not repo:
        return "repo_fehlt"
    try:
        status, obj = _github("GET", f"/repos/{repo}", token)
    except GithubAppFehler:
        return "fork"
    return "fork" if status != 200 else kern_modul().fork_pruefen(obj, repo)


KERN_SPERRE_FRIST_S = 10.0  # so lange wartet der Rückruf kanal (einreichen) höchstens auf die Sperre kernkanal
KERN_SPERRE = "kernkanal"  # unter dieser Sperre prüft ein Start im Kern-Kanal und bucht Versuch bzw. Start (gleichzeitige Starts)


@contextmanager
def kern_buchung(job: str, profil: str | None = None, pruefung=None):
    """Im Kern-Kanal die zweite Prüfung (pruefung: liefert (Code oder None, Konfiguration)) und das Buchen des Starts unter der Sperre
    kernkanal (kernkanal.jsonl, mit der Kennung des Profils): zwei gleichzeitige Starts prüfen so nie denselben Stand, jeder sieht den
    gebuchten Start des anderen (Zählung, Reserve der Laufzeit). Liefert (Code, Konfiguration): mit einem Code ist nichts gebucht, der
    Aufrufer weist ab. Lässt sich der Start nicht buchen, ist der Code grenze_start (die Grenzen wären nicht mehr prüfbar). Das Ende wird
    auch bei einer Ausnahme oder einem Signal gebucht. In den anderen Kanälen: (None, None), nichts gebucht."""
    if KANAL != "kern":
        yield None, None
        return
    k = kern_modul()
    zaehler = (KERN_PFADE or k.PFADE).zaehler
    beginn = None
    try:
        with exklusiv(sperren_ordner() / KERN_SPERRE):
            grund, konfig = pruefung() if pruefung is not None else (None, None)
            if grund is None:
                jetzt = time.time()
                try:
                    k.zaehler_schreiben(zaehler, job, "start", jetzt, profil=profil)
                    beginn = jetzt
                except OSError:
                    grund = "grenze_start"
        yield grund, konfig
    finally:
        if beginn is not None:
            try:
                k.zaehler_schreiben(zaehler, job, "ende", time.time(), dauer_s=max(0, int(time.time() - beginn)), profil=profil)
            except OSError:
                log(f"kernkanal: Ende von {job} nicht gebucht")


# ---------------------------------------------------------------- Persönlicher GitHub-Weg (Plan C, Dispatcher 10): Einhängepunkte
# Die GitHub-Logik (API, Klon, Bereinigung, Übernahme der Sandbox-Ausgaben, Pfadregeln, Commit aus Bytes, Einreichen, Pull Request) steht in
# wamo_job_github.py (Paket D-b, in /opt/wamo/waechter). Hier steht, was der Dispatcher ihr hineinreicht (DispatcherWerkzeuge nach dem
# Protokoll wamo_job_github.Werkzeuge: log, http, git, sandbox, sperre, pfad, uhr, geheimnis_in), wo er sie aufruft (GITHUB_EINSTIEGE), die
# Sandbox-Schritte ohne Netz, die Befehle aenderung, einreichen und verwerfen, die Ereignisse (schreibt nur der Dispatcher) und das Aufräumen.
# Ohne github=persoenlich in der Kopfzeile ändert nichts davon den Weg von Dispatcher 9.
#
# Einstiege der GitHub-Logik (Vertrag D-a zu D-b; Fehler: eine Ausnahme mit dem Attribut grund, ein Code aus GITHUB_GRUENDE, AENDERUNG_GRUENDE,
# EINREICHEN_GRUENDE oder KANAL_GRUENDE; jede andere Ausnahme endet geschlossen mit dem Standardcode des Einstiegs):
#   start(w, *, job, repo, art, profil, scopes_ausnahmen)   C.5 Start 2 bis 4: GitHub prüfen, basis.git klonen und bereinigen, github.json
#                                                            schreiben. Den Sandbox-Schritt klon und die Entschärfung macht danach der
#                                                            Dispatcher (ruft start ihn selbst, erkennt der Dispatcher das am Eigner).
#   laufende(w, *, job, projekt, art, profil, auftrag, lauf) C.5 Laufende 1 bis 5 über w.sandbox("ausgabe") und w.sandbox("pruefung"):
#                                                            aenderung.json, einreichen.json, aus.git. Ohne Token.
#   einreichen(w, *, job, profil, eingabe, kanal)            C.5 Einreichen 2 bis 8; kanal(buchen) liefert None oder einen Code: vor dem
#                                                            Push mit buchen=True (Notaus, Konfiguration, MAX_EINREICHEN_*, bucht einreichen),
#                                                            vor dem Pull Request mit buchen=False. Ergebnis: dict mit zweig, pr, adresse.
GITHUB_EINSTIEGE = ("start", "laufende", "einreichen")
LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
GRUND_RE = re.compile(r"[a-z][a-z_]{1,39}")
SCOPE_RE = re.compile(r"[a-z_]{1,40}(?::[a-z_]{1,40})?")
PERSOENLICH_VARIABLEN = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "WAMO_GITHUB", "WAMO_ZWEIG")
GIT_NETZ_BEFEHLE = ("clone", "ls-remote", "push")  # nur diese gehen mit netz=True (über den Helfer, nur https zu github.com)
# Unterbefehle, die die GitHub-Logik über Werkzeuge.git aufrufen darf (eigene Repos des Dispatchers, C.5); alles andere ist abgewiesen
GIT_BEFEHLE = frozenset({*GIT_NETZ_BEFEHLE, "init", "read-tree", "hash-object", "update-index", "write-tree", "diff-tree", "commit-tree",
                         "update-ref", "rev-parse", "cat-file", "ls-tree", "merge-base", "rev-list", "for-each-ref", "show-ref",
                         "symbolic-ref", "fsck", "count-objects", "pack-refs", "prune", "verify-pack", "mktree", "ls-files"})
# Optionen, die nie hinter dem Unterbefehl stehen dürfen: fremde Programme, Konfiguration, andere Repos oder Vorlagen, Untermodule
GIT_OPTIONEN_GESPERRT = ("-c", "--config", "--config-env", "--git-dir", "--work-tree", "--exec-path", "--namespace", "--super-prefix",
                         "--upload-pack", "--receive-pack", "--exec", "--reference", "--reference-if-able", "--separate-git-dir",
                         "--recurse-submodules", "--shared", "--dissociate", "--server-option", "--filter", "--bundle-uri")
GIT_KURZ_GESPERRT = {"clone": "uc", "ls-remote": "u", "push": "fdo"}  # Kurzoptionen je Unterbefehl (-u upload-pack, -f force, -d delete, -o)
GIT_PUSH_GESPERRT = ("--force", "--force-with-lease", "--force-if-includes", "--mirror", "--delete", "--prune", "--all", "--tags",
                     "--follow-tags", "--set-upstream", "--atomic", "--push-option", "--signed")
# Gemeinsam für jeden git-Aufruf des Dispatchers (C.5): keine Hooks, kein fsmonitor, keine Wartung, nur https, keine Weiterleitung, fsck,
# kein gespeicherter oder fremder Zugang, kein Proxy-, SSH- oder Askpass-Programm.
GIT_GEMEINSAM = (("core.hooksPath", "/dev/null"), ("core.fsmonitor", "false"), ("gc.auto", "0"), ("maintenance.auto", "false"),
                 ("protocol.allow", "never"), ("http.followRedirects", "false"),
                 ("transfer.fsckObjects", "true"), ("fetch.fsckObjects", "true"), ("receive.fsckObjects", "true"),
                 ("credential.helper", ""), ("credential.interactive", "false"), ("credential.useHttpPath", "false"),
                 ("core.askPass", "/bin/false"), ("core.sshCommand", "/bin/false"), ("core.gitProxy", ""), ("push.followTags", "false"),
                 ("push.recurseSubmodules", "no"), ("submodule.recurse", "false"), ("core.alternateRefsCommand", ""))
GIT_STDERR_MAX = 2000
SchrittErgebnis = namedtuple("SchrittErgebnis", ("rc", "ausgabe", "fehler"))  # intern; nach außen SandboxErgebnis der Schnittstelle
SIEBEN_BIT =b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
GITHUB_ZEILE_KOPF = b'{"typ":"github","wert":"'  # die GitHub-Zeile (C.2.2) beginnt immer genau so und endet mit "}


class GithubAbgelehnt(Exception):
    """Der persönliche GitHub-Weg kann nicht starten, auswerten oder einreichen. args[0] ist genau ein Code (GITHUB_GRUENDE, AENDERUNG_GRUENDE,
    EINREICHEN_GRUENDE oder KANAL_GRUENDE), nie ein Text mit Inhalt; das Ereignis nennt nur den Code."""

    @property
    def grund(self) -> str:
        return str(self.args[0]) if self.args else "github_fehler"


class GithubWechsel(Abgewiesen):
    """Ein Folgelauf nennt ein anderes github als der Auftrag (auch ohne Feld): start_abgelehnt mit github_wechsel."""


class KlonFehlgeschlagen(Exception):
    """Der Sandbox-Schritt klon ist gescheitert: kein Lauf, Ereignis wie ein Selbsttestfehler (C.5.2)."""


def github_modul():
    """Die Schnittstelle und Logik des persönlichen Wegs (wamo_job_github.py): in /opt/wamo/waechter installiert, im Repo neben dieser
    Datei. Fehlt sie oder ist sie defekt, wirft das Laden (der persönliche Weg scheitert dann geschlossen)."""
    geladen = sys.modules.get("wamo_job_github")
    if geladen is not None:
        return geladen
    if (WAECHTER / "wamo_job_github.py").is_file():
        return _modul("wamo_job_github")
    import importlib.util
    spec = importlib.util.spec_from_file_location("wamo_job_github", Path(__file__).resolve().with_name("wamo_job_github.py"))
    if spec is None or spec.loader is None:
        raise ImportError("wamo_job_github fehlt")
    modul = importlib.util.module_from_spec(spec)
    sys.modules["wamo_job_github"] = modul
    try:
        spec.loader.exec_module(modul)
    except BaseException:
        sys.modules.pop("wamo_job_github", None)
        raise
    return modul


def bekannte_gruende() -> frozenset[str]:
    """Alle Codes, die ein Ereignis des persönlichen Wegs tragen darf (aus dem Modul des Kern-Kanals). Ohne Modul nur github_fehler."""
    try:
        k = kern_modul()
        return frozenset((*k.KANAL_GRUENDE, *k.GITHUB_GRUENDE, *k.AENDERUNG_GRUENDE, *k.EINREICHEN_GRUENDE))
    except Exception:  # noqa: BLE001
        return frozenset({"github_fehler"})


def _grund_pruefen(grund: object, standard: str) -> str:
    grund = str(grund) if isinstance(grund, str) else ""
    return grund if GRUND_RE.fullmatch(grund) and grund in bekannte_gruende() else standard


def _github_aufruf(name: str, *args, fehler: str = "github_fehler", **kw):
    """Ruft einen Einstieg der GitHub-Logik auf. Fehlt das Modul oder der Einstieg, oder wirft er etwas ohne gültigen Code (Attribut grund),
    endet der Schritt geschlossen mit dem Code fehler; das Protokoll nennt nur den Typ der Ausnahme, nie ihren Text."""
    try:
        funktion = getattr(github_modul(), name)
    except Exception as e:  # noqa: BLE001 (Modul oder Einstieg fehlt: fail closed)
        log(f"github {name} nicht möglich ({type(e).__name__})")
        raise GithubAbgelehnt(fehler) from None
    try:
        return funktion(*args, **kw)
    except GithubAbgelehnt:
        raise
    except Exception as e:  # noqa: BLE001
        grund = _grund_pruefen(getattr(e, "grund", None), "")
        if grund:
            raise GithubAbgelehnt(grund) from None
        log(f"github {name} FEHLER {type(e).__name__}")
        raise GithubAbgelehnt(fehler) from None


def scopes_pruefen(wert: object) -> tuple[str, ...]:
    """Feld scopes_ausnahmen (C.2.8): eine JSON-Liste von Texten, sortiert, ohne Doppel, jeder aus SCOPES_AUSNAHMEN der Schnittstelle. Sonst
    Abgewiesen (fail closed), auch wenn die Schnittstelle fehlt."""
    if not isinstance(wert, list) or len(wert) > 30 or not all(isinstance(s, str) and SCOPE_RE.fullmatch(s) for s in wert):
        raise Abgewiesen("scopes_ausnahmen ungültig")
    if wert != sorted(set(wert)):
        raise Abgewiesen("scopes_ausnahmen ungültig (sortiert, ohne Doppel)")
    try:
        erlaubt = frozenset(github_modul().SCOPES_AUSNAHMEN)
    except Exception:  # noqa: BLE001
        raise Abgewiesen("scopes_ausnahmen nicht prüfbar (wamo_job_github fehlt)") from None
    if not set(wert) <= erlaubt:
        raise Abgewiesen("scopes_ausnahmen ungültig (nur Ausnahmen aus der festen Liste)")
    return tuple(wert)


@dataclass(frozen=True, slots=True)
class PersoenlicherLauf:
    """Was ein Lauf im persönlichen Weg in seiner Umgebung bekommt: Autor und Committer aus der Antwort von GitHub (github.json, nie
    vom Kern), Repo, Basis und den Zweig des Auftrags. Kein Token."""

    job: str
    login: str
    konto_id: int
    repo: str
    basis: str

    def __post_init__(self):
        if not isinstance(self.job, str) or not JOB_RE.fullmatch(self.job) or not isinstance(self.login, str) \
                or not LOGIN_RE.fullmatch(self.login) or type(self.konto_id) is not int or not 0 < self.konto_id < 10 ** 12 \
                or not isinstance(self.repo, str) or not REPO_RE.fullmatch(self.repo) or not isinstance(self.basis, str) \
                or not COMMIT_RE.fullmatch(self.basis):
            raise ValueError("github.json ungültig")

    @classmethod
    def aus_datei(cls, jobdir: Path, job: str, repo: str) -> "PersoenlicherLauf":
        daten = read_no_follow(jobdir / "github.json", 64 * 1024)
        try:
            obj = json.loads(daten) if daten is not None else None
        except (ValueError, RecursionError):
            obj = None
        if not isinstance(obj, dict) or obj.get("repo") != repo:
            raise ValueError("github.json fehlt oder gehört zu einem anderen Repo")
        return cls(job, obj.get("login"), obj.get("konto_id"), repo, obj.get("basis"))

    def umgebung(self) -> dict[str, str]:
        email = f"{self.konto_id}+{self.login}@users.noreply.github.com"
        return {"GIT_AUTHOR_NAME": self.login, "GIT_COMMITTER_NAME": self.login, "GIT_AUTHOR_EMAIL": email,
                "GIT_COMMITTER_EMAIL": email, "WAMO_GITHUB": GITHUB_WEG, "WAMO_ZWEIG": f"wamo/{self.job}"}


def github_hinweis_persoenlich(job: str) -> str:
    """Zusatz zum Systemtext im persönlichen Weg (C.5 Start 7)."""
    return (f"- GitHub: Dieser Lauf hat keinen GitHub-Zugang. Committe nur lokal auf den Zweig wamo/{job} (er ist ausgecheckt) und setze "
            f"in jede Commit-Nachricht den Trailer \"WAIS-Auftrag: {job}\". Nicht pushen, keine Remotes ändern, kein gh: das Einreichen "
            "als Pull Request übernimmt W.A.I.S. nach der Freigabe durch die Person.")


def _git_umgebung() -> dict[str, str]:
    """Umgebung jedes git-Aufrufs des Dispatchers: keine System- und keine globale Konfiguration, keine Rückfrage, kein Repo über dem
    Arbeitsordner, keine optionalen Sperren, keine replace-Objekte, nur https als Protokoll."""
    return {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C", "LC_ALL": "C", "GIT_CEILING_DIRECTORIES": "/",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false",
            "SSH_ASKPASS": "/bin/false", "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1", "GIT_PROTOCOL_FROM_USER": "0"}


def git_aufruf(args: list[str] | tuple[str, ...], *, git_dir: Path | None = None, eingabe: bytes | None = None,
               zugang: "GithubGeheimnis | None" = None, netz: bool = False, zeitlimit_s: float = 60) -> tuple[int, bytes, bytes]:
    """Ein git-Aufruf des Dispatchers (C.5 gemeinsam): --git-dir auf ein eigenes Repo (oder keins für clone), cwd="/", Umgebung
    _git_umgebung, Einstellungen GIT_GEMEINSAM, Grenzen über prlimit (Speicher, Dateigröße, keine Core-Datei) und ein Zeitlimit. Jedes
    Argument muss GIT_ARG_RE erfüllen. Ohne netz ist auch https gesperrt (kein Protokoll erlaubt). Mit netz und zugang meldet sich git
    über den Credential-Helfer an, der das Token aus einer geerbten Pipe liest (nie Umgebung, argv oder Datei). Liefert (Code, stdout
    höchstens MAX_GIT_AUSGABE Bytes, stderr geschwärzt mit dem exakten Token und gekürzt)."""
    for a in args:
        if not isinstance(a, str) or not GIT_ARG_RE.fullmatch(a):
            raise ValueError("git: Argument ungültig")
    lese_fd = zugang.in_pipe() if netz and zugang is not None else None
    argv = [GIT_PROGRAMM]
    # GIT_GEMEINSAM leert die Liste der Helfer (credential.helper=); erst danach kommt genau der feste Helfer mit der Nummer der Pipe
    for schluessel, wert in (*GIT_GEMEINSAM, ("protocol.https.allow", "always" if netz else "never")):
        argv += ["-c", f"{schluessel}={wert}"]
    if lese_fd is not None:
        argv += ["-c", f"credential.helper={HELFER} {lese_fd}"]
    if git_dir is not None:
        argv.append(f"--git-dir={git_dir}")
    argv += list(args)
    if os.name == "posix":  # Grenzen sind Pflicht (fail closed); nur Tests unter Windows laufen ohne prlimit
        argv = [PRLIMIT, f"--as={GIT_SPEICHER}", f"--fsize={GIT_DATEI_MAX}", "--core=0", "--nofile=4096", "--", *argv]
    umgebung = _git_umgebung()
    umgebung["GIT_ALLOW_PROTOCOL"] = "https" if netz else "kein-protokoll"  # ohne Netz kein einziges Protokoll
    try:
        # eigene Prozessgruppe: am Zeitlimit endet auch git-remote-https, das den Zugang im Speicher hält (nicht nur das direkte Kind)
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=umgebung, cwd="/",
                                pass_fds=(lese_fd,) if lese_fd is not None else (), start_new_session=True)
    except OSError as e:
        proc = None
        code, stdout, stderr = 127, b"", f"git: nicht startbar ({type(e).__name__})".encode()
    finally:
        if lese_fd is not None:
            os.close(lese_fd)
    if proc is not None:
        try:
            stdout, stderr = proc.communicate(eingabe if eingabe is not None else b"", timeout=zeitlimit_s)
            code, stdout, stderr = proc.returncode, stdout[:MAX_GIT_AUSGABE], stderr[-8192:]
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, getattr(signal, "SIGKILL", 9))
            except (ProcessLookupError, PermissionError, AttributeError):
                proc.kill()
            proc.communicate()
            code, stdout, stderr = EXIT_ZEITLIMIT, b"", b"git: Zeitlimit"
    ansicht = zugang.ansicht() if zugang is not None and zugang.gueltig else None
    try:
        stderr = schwaerzen(stderr, [(ansicht, GH_PAT_ERSATZ)] if ansicht is not None else [])
    finally:
        if ansicht is not None:
            ansicht.release()
    return code, stdout, stderr


PFAD_API_RE = re.compile(r"(/[A-Za-z0-9._~-]+)+/?(\?[A-Za-z0-9._~=&:/-]{1,500})?")  # kein %, kein #, kein Leerzeichen, kein //


def _https_voll(methode: str, pfad: str, kopf: dict, koerper: bytes | None = None) -> tuple[int, dict[str, str], bytes]:
    """Wie _https, dazu die Kopfzeilen der Antwort (Namen klein). Dieselben Regeln: Zertifikat geprüft, TLS 1.2, kein Proxy, keine
    Weiterleitung, Antwort höchstens MAX_GITHUB_ANTWORT + 1 Bytes."""
    kontext = ssl.create_default_context()
    kontext.minimum_version = ssl.TLSVersion.TLSv1_2
    verbindung = http.client.HTTPSConnection(GITHUB_API_HOST, 443, timeout=GITHUB_ZEITLIMIT_S, context=kontext)
    try:
        verbindung.request(methode, pfad, body=koerper, headers=kopf)
        antwort = verbindung.getresponse()
        kopfzeilen = {k.lower(): v for k, v in antwort.getheaders()[:100]}
        return antwort.status, kopfzeilen, antwort.read(MAX_GITHUB_ANTWORT + 1)
    finally:
        verbindung.close()


def _b64_in(quelle: bytes | bytearray | memoryview) -> bytearray:
    """Base64 in ein eigenes bytearray (ohne Zeilenumbruch), ohne dass ein Ergebnis als bytes entsteht (für geheimnis_in: die Form, in der
    git <benutzername>:<token> über HTTP schickt)."""
    n = len(quelle)
    aus = bytearray(4 * ((n + 2) // 3))
    j = 0
    for i in range(0, n, 3):
        a = quelle[i]
        b = quelle[i + 1] if i + 1 < n else 0
        c = quelle[i + 2] if i + 2 < n else 0
        aus[j] = SIEBEN_BIT[a >> 2]
        aus[j + 1] = SIEBEN_BIT[((a & 3) << 4) | (b >> 4)]
        aus[j + 2] = SIEBEN_BIT[((b & 15) << 2) | (c >> 6)] if i + 1 < n else 61
        aus[j + 3] = SIEBEN_BIT[c & 63] if i + 2 < n else 61
        j += 4
    return aus


class DispatcherWerkzeuge:
    """Umsetzung des Protokolls wamo_job_github.Werkzeuge (C.9, Schnittstelle D-a zu D-b) für genau einen Aufruf (start, Laufende oder
    einreichen). Das Token des Aufrufs (GithubGeheimnis, ein Ausschnitt des Lesepuffers) hält nur dieses Objekt; die GitHub-Logik sieht es
    nie: http und git benutzen es, geheimnis_in sucht danach. werte sind die exakten Claude-Zugänge des Laufs (schwaerzungen), nie im
    Protokoll. gehalten: Sperren, die der Dispatcher für diesen Aufruf schon hält (sperre meldet sie als gehalten, ein zweites flock im
    selben Prozess wäre sonst belegt)."""

    def __init__(self, job: str, projekt: str, jobdir: Path, platz: int | None = None, zugang: "GithubGeheimnis | None" = None,
                 werte: tuple = (), gehalten: tuple[str, ...] = ()):
        self.job, self.projekt, self.jobdir, self.platz = check_job(job), projekt, _no_symlink(jobdir), platz
        self._zugang, self._werte, self._gehalten = zugang, tuple(werte), frozenset(gehalten)

    def _g(self):
        return github_modul()

    def _ersetzungen(self) -> list:
        ersetzungen = [(w, ZUGANG_ERSATZ) for w in self._werte if len(w) >= 8]
        if self._zugang is not None and self._zugang.gueltig:
            ersetzungen.insert(0, (self._zugang.ansicht(), GH_PAT_ERSATZ))
        return ersetzungen

    def log(self, text: str, *, pflicht: bool = False) -> None:
        ersetzungen = self._ersetzungen()
        try:
            sauber = schwaerzen(str(text).encode("utf-8", "replace"), ersetzungen).decode("utf-8", "replace")
        finally:
            for wert, _ in ersetzungen:
                if isinstance(wert, memoryview):
                    wert.release()
        log(f"github {self.job}: " + "".join(" " if not c.isprintable() else c for c in sauber)[:500], pflicht=pflicht)

    def http(self, methode: str, pfad: str, daten=None):
        """Wie Werkzeuge.http. Restrisiko (bewusst, wie beim Claude-Zugang): http.client und die TLS-Puffer legen kurzlebige Kopien der
        Kopfzeile als bytes an, die sich nicht überschreiben lassen; der Prozess ist nicht dumpable (PR_SET_DUMPABLE=0), sein Speicher
        für die Sandbox und andere Prozesse von wamo nicht lesbar. Das eigene bytearray wird nach dem Aufruf überschrieben."""
        g = self._g()
        if self._zugang is None or not self._zugang.gueltig:
            raise g.KeinToken("kein Token in diesem Aufruf")
        teile = pfad.split("?", 1)[0].split("/") if isinstance(pfad, str) else []
        if methode not in ("GET", "POST") or not isinstance(pfad, str) or not PFAD_API_RE.fullmatch(pfad) or any(s in (".", "..") for s in teile):
            raise ValueError("GitHub: Pfad oder Methode ungültig")
        anmeldung = self._zugang.kopfzeile()
        try:
            kopf = {"Accept": "application/vnd.github+json", "Authorization": anmeldung, "X-GitHub-Api-Version": GITHUB_API_VERSION,
                    "User-Agent": "wamo-job-dispatch"}
            koerper = None
            if daten is not None:
                koerper = json.dumps(dict(daten)).encode("utf-8")
                kopf["Content-Type"] = "application/json"
            try:
                status, kopfzeilen, roh = _https_voll(methode, pfad, kopf, koerper)
            except (OSError, http.client.HTTPException, ValueError) as e:
                raise g.NetzFehler(f"GitHub nicht erreichbar ({type(e).__name__})") from None
        finally:
            anmeldung[:] = bytes(len(anmeldung))
        if len(roh) > MAX_GITHUB_ANTWORT:
            raise g.NetzFehler("Antwort von GitHub zu groß")
        try:
            obj = json.loads(roh) if roh else None
        except (ValueError, RecursionError):
            obj = None
        return g.HttpAntwort(status, MappingProxyType(kopfzeilen), obj)

    def _git_regeln(self, args: tuple, git_dir, netz: bool) -> None:
        """argv-Regeln für Werkzeuge.git (die Umsetzung ist die einzige Stelle, die sie durchsetzt): ein bekannter Unterbefehl zuerst, keine
        gesperrte Option, eine Adresse nur mit netz und dann genau https://github.com/<Repo des Auftrags>.git nach "--", clone nur nach
        basis.git, push genau <Commit>:refs/heads/wamo/<job> ohne Force, ls-remote genau refs/heads/wamo/<job>. ValueError sonst."""
        befehl = args[0]
        if befehl not in GIT_BEFEHLE:
            raise ValueError("git: Unterbefehl nicht erlaubt")
        for a in args[1:]:
            if any(a == o or a.startswith(o + "=") for o in GIT_OPTIONEN_GESPERRT) or (a.startswith("--template") and a != "--template="):
                raise ValueError("git: Option nicht erlaubt")
            if len(a) > 1 and a[0] == "-" and a[1] != "-" and set(a[1:]) & set(GIT_KURZ_GESPERRT.get(befehl, "")):
                raise ValueError("git: Option nicht erlaubt")
            if befehl == "push" and (a.startswith("+") or any(a == o or a.startswith(o + "=") for o in GIT_PUSH_GESPERRT)):
                raise ValueError("git: push nur ohne Force, Löschen und Tags")
        adressen = [a for a in args if "://" in a or a.startswith("git@") or a.startswith("file:")]
        if befehl in GIT_NETZ_BEFEHLE:
            if not netz:
                raise ValueError("git: clone, ls-remote und push nur mit netz")
            repo = read_json(self.jobdir / "auftrag.json", {}).get("repo")
            if not isinstance(repo, str) or not REPO_RE.fullmatch(repo) or "--" not in args:
                raise ValueError("git: Repo des Auftrags unbekannt oder kein -- vor den Angaben")
            rest = list(args[args.index("--") + 1:])
            if adressen != [f"https://github.com/{repo}.git"] or not rest or rest[0] != adressen[0]:
                raise ValueError("git: nur die Adresse des Repos dieses Auftrags")
            erwartet = {"clone": [str(self.pfad("basis.git"))], "ls-remote": [f"refs/heads/wamo/{self.job}"]}.get(befehl)
            if befehl == "push":
                if len(rest) != 2 or not re.fullmatch(rf"[0-9a-f]{{40}}:refs/heads/wamo/{self.job}", rest[1]):
                    raise ValueError("git: push nur <Commit>:refs/heads/wamo/<job>")
            elif rest[1:] != erwartet:
                raise ValueError("git: Ziel nicht erlaubt")
        elif netz or adressen:
            raise ValueError("git: Netz nur für clone, ls-remote und push")

    def git(self, args, *, git_dir, eingabe=None, netz=False, zeitlimit_s=60.0):
        g = self._g()
        args = tuple(args)
        if not args or not isinstance(args[0], str):
            raise ValueError("git: Befehl fehlt")
        if git_dir is None:
            if args[0] != "clone":
                raise ValueError("git: ohne git_dir nur clone")
        elif Path(git_dir) not in (self.pfad("basis.git"), self.pfad("aus.git")) or Path(git_dir).is_symlink():
            raise ValueError("git: git_dir ist kein eigenes Repo des Dispatchers")
        self._git_regeln(args, git_dir, bool(netz))
        if netz and (self._zugang is None or not self._zugang.gueltig):
            raise g.KeinToken("kein Token in diesem Aufruf")
        if not 0 < float(zeitlimit_s) <= GIT_ZEITLIMIT_S:
            raise ValueError("git: Zeitlimit ungültig")
        code, stdout, stderr = git_aufruf(args, git_dir=Path(git_dir) if git_dir is not None else None, eingabe=eingabe,
                                          zugang=self._zugang if netz else None, netz=bool(netz), zeitlimit_s=float(zeitlimit_s))
        ersetzungen = self._ersetzungen()
        try:
            text = schwaerzen(stderr, ersetzungen).decode("utf-8", "replace")
        finally:
            for wert, _ in ersetzungen:
                if isinstance(wert, memoryview):
                    wert.release()
        text = " ".join(text.split())[-GIT_STDERR_MAX:]
        return g.GitErgebnis(code, stdout, text)

    def sandbox(self, modus, *, job, projekt, zeitlimit_s):
        g = self._g()
        if modus not in g.SANDBOX_MODI_NETZLOS:
            raise ValueError("Sandbox: nur die netzlosen Schritte")
        if job != self.job or projekt != self.projekt or self.platz is None:
            raise ValueError("Sandbox: anderer Auftrag, anderes Projekt oder kein Platz")
        if type(zeitlimit_s) is not int or not 0 < zeitlimit_s <= SCHRITT_ZEITLIMIT_S[modus]:
            raise ValueError("Sandbox: Zeitlimit ungültig")
        lauf = PersoenlicherLauf.aus_datei(self.jobdir, self.job, read_json(self.jobdir / "auftrag.json", {}).get("repo"))
        argumente = schritt_argumente(modus, lauf, self.jobdir)
        ergebnis = sandbox_schritt(modus, self.job, self.projekt, self.platz, argumente, zeitlimit_s)
        return g.SandboxErgebnis(ergebnis.rc, ergebnis.rc == EXIT_ZEITLIMIT)

    @contextmanager
    def sperre(self, name):
        if name not in self._g().SPERREN:
            raise ValueError("Sperre unbekannt")
        if name in self._gehalten:
            yield True
            return
        sperre = Sperre(sperren_ordner() / KERN_SPERRE if name == KERN_SPERRE else self.jobdir / name)
        try:
            yield bool(sperre.versuchen())
        finally:
            _sperre_freigeben(sperre)

    def pfad(self, name) -> Path:
        if name not in self._g().AUFTRAG_DATEIEN:
            raise ValueError("Eintrag im Auftragsordner unbekannt")
        return _no_symlink(self.jobdir) / name

    def uhr(self) -> float:
        return time.time()

    def geheimnis_in(self, daten) -> bool:
        if isinstance(daten, memoryview):
            daten = daten.tobytes()
        if not isinstance(daten, (bytes, bytearray)):
            raise TypeError("geheimnis_in braucht Bytes")
        if any(len(w) >= 8 and w in daten for w in self._werte):
            return True
        if self._zugang is None or not self._zugang.gueltig:
            return False
        ansicht = self._zugang.ansicht()
        quelle = bytearray(len(GIT_BENUTZER) + 1 + len(ansicht))
        try:
            if ansicht in daten:
                return True
            quelle[:len(GIT_BENUTZER) + 1] = GIT_BENUTZER + b":"
            quelle[len(GIT_BENUTZER) + 1:] = ansicht
            kodiert = _b64_in(quelle)
            try:
                return kodiert in daten
            finally:
                kodiert[:] = bytes(len(kodiert))
        finally:
            ansicht.release()
            quelle[:] = bytes(len(quelle))


def _ordner_leeren(pfad: Path) -> None:
    """Ein Ordner im Auftragsordner, den die Sandbox beschreiben darf (ausgabe/, ergebnis/): alles darin weg (auch Links und FIFOs, ohne
    ihnen zu folgen), danach leer mit 0700."""
    try:
        st = pfad.lstat()
    except FileNotFoundError:
        st = None
    if st is not None:
        if stat.S_ISDIR(st.st_mode):
            _baum_entfernen(pfad)
        else:
            pfad.unlink()
    pfad.mkdir(mode=0o700)


def eigner_datei(projekt: str) -> Path:
    return sperren_ordner() / f"{EIGNER_PRAEFIX}{check_project(projekt)}.json"


def eigner_lesen(projekt: str) -> str | None:
    """Der Auftrag, dessen Klon den Projektordner zuletzt gebaut hat (None: keiner, unlesbar oder ein Lauf ohne persönlichen Weg danach)."""
    daten = read_no_follow(eigner_datei(projekt), 4096)
    try:
        obj = json.loads(daten) if daten else None
    except (ValueError, RecursionError):
        return None
    job = obj.get("job") if isinstance(obj, dict) else None
    return job if isinstance(job, str) and JOB_RE.fullmatch(job) else None


def eigner_schreiben(projekt: str, job: str) -> None:
    write_json_atomic(eigner_datei(projekt), {"job": check_job(job), "t": int(time.time())})


def eigner_entfernen(projekt: str) -> None:
    """Ein Lauf ohne persönlichen Weg im selben Projektordner: der Ordner stammt danach nicht mehr aus dem Klon eines Auftrags."""
    try:
        eigner_datei(projekt).unlink(missing_ok=True)
    except (OSError, Abgewiesen):
        pass


def schritt_argumente(modus: str, lauf: PersoenlicherLauf, jobdir: Path) -> list[str]:
    """Argumente der festen Programme (Werte aus github.json, geprüft in PersoenlicherLauf): klon bekommt Repo, Auftrag, Basis und, wenn es
    ein letztes Bundle gibt, --bundle; ausgabe und pruefung Auftrag und Basis."""
    if modus == "klon":
        bundle = (jobdir / "bundle.ein").is_file() and not (jobdir / "bundle.ein").is_symlink()
        return ["--repo", lauf.repo, "--auftrag", lauf.job, "--basis", lauf.basis, *(["--bundle"] if bundle else [])]
    return ["--auftrag", lauf.job, "--basis", lauf.basis]


def _schritt_umgebung() -> dict[str, str]:
    env = basis_env()
    env["GIT_CONFIG_COUNT"] = str(len(GIT_OHNE_HOOKS))
    for i, (schluessel, wert) in enumerate(GIT_OHNE_HOOKS):
        env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"] = schluessel, wert
    return env


def sandbox_schritt(modus: str, job: str, projekt: str, platz: int, argumente: tuple[str, ...] | list[str] = (),
                    zeitlimit_s: int | None = None) -> SchrittErgebnis:
    """Ein Sandbox-Schritt ohne Netz (wamo-job.sh --modus klon|ausgabe|pruefung, C.5.2) mit dem festen Programm des Modus. Vorher: bei
    ausgabe das Projekt entschärfen und ausgabe/ leeren, bei pruefung ergebnis/ leeren. Nachher bei klon (Erfolg): das Projekt entschärfen
    (C.5 Start 6) und den Eigner des Projektordners schreiben. Die Umgebung trägt nie ein Token (nur Basis und Git-Hooks aus)."""
    if modus not in SCHRITT_PROGRAMME or type(platz) is not int:
        raise ValueError("Sandbox-Schritt unbekannt")
    check_job(job)
    check_project(projekt)
    for a in argumente:
        if not isinstance(a, str) or not SCHRITT_ARG_RE.fullmatch(a):
            raise ValueError("Sandbox-Schritt: Argument ungültig")
    jobdir = _no_symlink(JOBS / job)
    if modus == "ausgabe":
        for entfernt in projekt_entschaerfen(PROJEKTE / projekt):
            log(f"entschärft {job} {projekt}: {entfernt}")
        _ordner_leeren(jobdir / "ausgabe")
    elif modus == "pruefung":
        _ordner_leeren(jobdir / "ergebnis")
    zeit = min(zeitlimit_s or SCHRITT_ZEITLIMIT_S[modus], SCHRITT_ZEITLIMIT_S[modus])
    argv = [str(RUNNER), "--auftrag", job, "--projekt", projekt, "--platz", str(platz), "--modus", modus, "--zeitlimit", str(zeit),
            "--einheit-zusatz", modus, "--", *SCHRITT_PROGRAMME[modus], *argumente]
    try:
        p = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, env=_schritt_umgebung(), cwd="/", timeout=zeit + 90,
                           start_new_session=True)
        rc, ausgabe, fehler = p.returncode, p.stdout[:MAX_SCHRITT_AUSGABE], schwaerzen(p.stderr[-4096:], [])
    except subprocess.TimeoutExpired:
        stop_units(job)
        rc, ausgabe, fehler = EXIT_ZEITLIMIT, b"", b"Zeitlimit"
    except OSError as e:
        rc, ausgabe, fehler = EXIT_INTERN, b"", f"nicht startbar ({type(e).__name__})".encode()
    log(f"schritt {job} {modus} rc={rc}")
    if modus == "klon" and rc == 0:
        for entfernt in projekt_entschaerfen(PROJEKTE / projekt):
            log(f"entschärft {job} {projekt}: {entfernt}")
        eigner_schreiben(projekt, job)
    return SchrittErgebnis(rc, ausgabe, fehler)


def aenderung_lesen(jobdir: Path) -> dict:
    """aenderung.json (geschrieben von der GitHub-Logik): nur die Felder aus AENDERUNG_FELDER und ein Zustand aus ZUSTAENDE, sonst keine."""
    daten = read_no_follow(jobdir / "aenderung.json", MAX_AENDERUNG_BYTES)
    try:
        obj = json.loads(daten) if daten else None
    except (ValueError, RecursionError):
        obj = None
    if not isinstance(obj, dict) or obj.get("status") not in ZUSTAENDE:
        return {"status": "keine"}
    return aenderung_felder_pruefen(obj, jobdir.name)


AENDERUNG_ZAHLEN = ("dateien", "plus", "minus", "nicht_gelistet", "ungesichert", "pr")
MAX_AENDERUNG_LISTE = 200


def _text_sauber(wert: object, laenge: int) -> str | None:
    """Ein Text aus der Auswertung für Kern und Oberfläche: nur str, ohne unsichtbare Zeichen, gekürzt, geschwärzt (ein Token im Pfadnamen
    oder Titel käme sonst bis in die Karte)."""
    if not isinstance(wert, str):
        return None
    text = "".join(c for c in wert if not _unsichtbar(c))[:laenge]
    return schwaerzen(text.encode("utf-8"), []).decode("utf-8", "replace")


def aenderung_felder_pruefen(obj: dict, job: str) -> dict:
    """Die Felder von aenderung.json für das Ereignis (C.2.4), je mit Typ und Grenze; was nicht passt, fällt weg. Die Werte stammen aus Daten
    der Sandbox (über die GitHub-Logik): Kern und Oberfläche bekommen nur geprüfte Formen."""
    aus: dict = {"status": obj["status"]}
    for name in ("commit_id", "tree_id", "basis"):
        if isinstance(obj.get(name), str) and COMMIT_RE.fullmatch(obj[name]):
            aus[name] = obj[name]
    if JOB_RE.fullmatch(job) and obj.get("zweig") == f"wamo/{job}":
        aus["zweig"] = obj["zweig"]
    for name in AENDERUNG_ZAHLEN:
        if type(obj.get(name)) is int and 0 <= obj[name] < 10 ** 9:
            aus[name] = obj[name]
    if obj.get("lauf") in ("fertig", "zeitlimit", "fehler"):
        aus["lauf"] = obj["lauf"]
    if isinstance(obj.get("gruende"), list):
        bekannt = bekannte_gruende()
        aus["gruende"] = [g for g in obj["gruende"][:20] if isinstance(g, str) and g in bekannt]
    titel = _text_sauber(obj.get("titel"), 200)
    if titel is not None:
        aus["titel"] = titel
    meta = read_json(JOBS / job / "auftrag.json", {}) if JOB_RE.fullmatch(job) else {}
    repo = meta.get("repo") if isinstance(meta, dict) else None
    if isinstance(obj.get("adresse"), str) and isinstance(repo, str) and type(obj.get("pr")) is int \
            and obj["adresse"] == f"https://github.com/{repo}/pull/{obj['pr']}":
        aus["adresse"] = obj["adresse"]
    if isinstance(obj.get("liste"), list):
        liste = []
        for eintrag in obj["liste"][:MAX_AENDERUNG_LISTE]:
            if not isinstance(eintrag, dict):
                continue
            pfad = _text_sauber(eintrag.get("pfad"), 4096)
            if not pfad or eintrag.get("art") not in ("neu", "geaendert", "geloescht") or eintrag.get("klasse") not in ("normal", "sensibel"):
                continue
            liste.append({"pfad": pfad, "art": eintrag["art"], "klasse": eintrag["klasse"],
                          **{k: eintrag[k] for k in ("plus", "minus") if type(eintrag.get(k)) is int and 0 <= eintrag[k] < 10 ** 9}})
        aus["liste"] = liste
    return aus


def aenderung_ereignis(job: str) -> dict:
    """Felder des Ereignisses aenderung aus der Datei, ohne neu zu rechnen (C.2.3)."""
    return {**aenderung_lesen(JOBS / job), "job": job}


def _persoenlicher_auftrag(job: str, profil: str) -> Path:
    """Der Auftragsordner eines Auftrags mit github=persoenlich und genau diesem Profil (Regel 4 prüft im Kern-Kanal dasselbe vorher)."""
    jobdir = _no_symlink(JOBS / job)
    meta = read_json(jobdir / "auftrag.json", None)
    if not isinstance(meta, dict) or meta.get("github") != GITHUB_WEG:
        raise Abgewiesen("Auftrag ohne persönlichen GitHub-Weg")
    if meta.get("profil") != profil:
        raise Abgewiesen("Auftrag gehört zu einem anderen Profil")
    return jobdir


def _einreichen_fehler(job: str, grund: str) -> int:
    grund = _grund_pruefen(grund, "github_fehler")
    log(f"einreichen_fehler {job} grund={grund}")
    wamo_event("einreichen_fehler", job=job, grund=grund)
    return EXIT_ABGEWIESEN


def cmd_aenderung(job: str, profil: str) -> int:
    """aenderung <job> <profil>: das Ereignis aenderung aus aenderung.json (rechnet nie neu)."""
    _persoenlicher_auftrag(job, profil)
    wamo_event("aenderung", **aenderung_ereignis(job))
    return EXIT_OK


def einreichen_eingabe_pruefen(raw: bytes) -> dict:
    """Erste Zeile von einreichen (EINREICHEN_FELDER): commit_id und tree_id je 40 Hex, bestaetigt eine Liste von Pfaden (höchstens 300),
    optional scopes_ausnahmen wie in der Kopfzeile (scopes_pruefen). Die Pfade vergleicht die GitHub-Logik als Menge mit den sensiblen."""
    if not raw.endswith(b"\n") or len(raw) > MAX_EINREICHEN_ZEILE:
        raise GithubAbgelehnt("bestaetigung")
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise GithubAbgelehnt("bestaetigung") from None
    if not isinstance(obj, dict) or not {"commit_id", "tree_id", "bestaetigt"} <= set(obj) \
            or set(obj) - {"commit_id", "tree_id", "bestaetigt", "scopes_ausnahmen"}:
        raise GithubAbgelehnt("bestaetigung")
    commit, tree, pfade = obj["commit_id"], obj["tree_id"], obj["bestaetigt"]
    if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit) or not isinstance(tree, str) or not COMMIT_RE.fullmatch(tree):
        raise GithubAbgelehnt("veraltet")
    if not isinstance(pfade, list) or len(pfade) > 300 or not all(isinstance(p, str) and 0 < len(p) <= 4096 for p in pfade):
        raise GithubAbgelehnt("bestaetigung")
    try:
        scopes = scopes_pruefen(obj["scopes_ausnahmen"]) if "scopes_ausnahmen" in obj else ()
    except Abgewiesen:
        raise GithubAbgelehnt("token_rechte") from None
    return {"commit_id": commit, "tree_id": tree, "bestaetigt": tuple(sorted(set(pfade))), "scopes_ausnahmen": scopes}


def _kern_einreichen_pruefen(job: str, profil: str, buchen: bool = False, versuch: bool = False) -> str | None:
    """Kern-Kanal, unter der Sperre kernkanal (pruefe_einreichen): versuch=True am Eingang von einreichen (Kanal, PERSOENLICH, Versuche je
    Stunde und Profil; bucht den Versuch mit befehl=einreichen), buchen=True unmittelbar vor dem Push (dazu MAX_EINREICHEN_*; bucht
    einreichen), sonst nur der Kanal (Notaus, Konfiguration, PERSOENLICH) vor dem Pull Request. Auf die Sperre wartet es höchstens
    KERN_SPERRE_FRIST_S (hält die GitHub-Logik sie selbst, endet es geschlossen statt ohne Ende zu warten). In den anderen Kanälen None."""
    if KANAL != "kern":
        return None
    k = kern_modul()
    zaehler = (KERN_PFADE or k.PFADE).zaehler
    gesperrt = "grenze_einreichen" if buchen else "grenze_profil"
    try:
        with exklusiv_mit_frist(sperren_ordner() / KERN_SPERRE, KERN_SPERRE_FRIST_S):
            if buchen or versuch:
                try:
                    ereignisse = k.zaehler_lesen(zaehler)
                except OSError:
                    ereignisse = None
            else:
                ereignisse = []  # nur der Kanal: keine Grenze zählt
            grund = k.pruefe_einreichen(kern_zustand(), ereignisse=ereignisse, jetzt=time.time(), profil=profil, buchen=buchen)
            if grund is None and (buchen or versuch):
                try:
                    k.zaehler_schreiben(zaehler, job, "einreichen" if buchen else "versuch", time.time(), profil=profil,
                                        **({} if buchen else {"befehl": "einreichen"}))
                except (OSError, ValueError):
                    grund = gesperrt
            return grund
    except TimeoutError:
        return gesperrt


def cmd_einreichen(job: str, profil: str) -> int:
    """einreichen <job> <profil>: Zeile 1 mit Commit, Tree, Bestätigungen und Ausnahmen, Zeile 2 die GitHub-Zeile; dann unter den Sperren
    .lauf und .einreichen die GitHub-Logik (Zustand, Bindung, Konto, Rechte, Geheimnissuche, Kanal und Zähler, ls-remote, Push, Pull Request).
    Ereignis eingereicht oder einreichen_fehler. Das Token wird danach überschrieben, auch bei jedem Fehler."""
    jobdir = _persoenlicher_auftrag(job, profil)
    geheimnis = None
    gehalten = [Sperre(jobdir / ".lauf"), Sperre(jobdir / ".einreichen")]
    try:
        try:
            eingabe = einreichen_eingabe_pruefen(_einreichen_zeile_lesen())
        except GithubAbgelehnt as e:
            return _einreichen_fehler(job, e.grund)
        except Abgewiesen:  # die Zeile kam nicht rechtzeitig oder war die GitHub-Zeile an falscher Stelle
            return _einreichen_fehler(job, "bestaetigung")
        try:
            grund = _kern_einreichen_pruefen(job, profil, versuch=True)  # Kanal, PERSOENLICH, Versuche je Stunde (jeder Aufruf zählt)
        except OSError:
            grund = "github_fehler"
        if grund is not None:
            return _einreichen_fehler(job, grund)
        if not nicht_dumpbar():
            log(f"einreichen {job}: der Prozess ist dumpable, GitHub-Zeile nicht gelesen", pflicht=True)
            return _einreichen_fehler(job, "github_fehler")
        try:
            geheimnis = _githubzeile_lesen()
        except GithubZeileFehlt:
            return _einreichen_fehler(job, "github_fehler")
        if not all(s.versuchen() for s in gehalten):
            return _einreichen_fehler(job, "zustand")  # ein Lauf dieses Auftrags oder ein anderes Einreichen ist aktiv
        projekt = read_json(jobdir / "auftrag.json", {}).get("projekt", "")
        werkzeuge = DispatcherWerkzeuge(job, projekt, jobdir, zugang=geheimnis, gehalten=(".lauf", ".einreichen"))
        try:
            ergebnis = _github_aufruf("einreichen", werkzeuge, job=job, profil=profil, eingabe=eingabe,
                                      kanal=lambda buchen=False: _kern_einreichen_pruefen(job, profil, buchen))
        except GithubAbgelehnt as e:
            return _einreichen_fehler(job, e.grund)
        felder = _eingereicht_felder(ergebnis, read_json(jobdir / "auftrag.json", {}).get("repo"), job)
        if felder is None:
            return _einreichen_fehler(job, "github_fehler")
        if KANAL == "kern":
            try:
                k = kern_modul()
                k.zaehler_schreiben((KERN_PFADE or k.PFADE).zaehler, job, "eingereicht", time.time(), profil=profil, pr=felder["pr"])
            except (OSError, ValueError):
                log(f"kernkanal: eingereicht von {job} nicht gebucht")
        log(f"eingereicht {job} pr={felder['pr']}", pflicht=True)
        wamo_event("eingereicht", job=job, **felder)
        return EXIT_OK
    finally:
        if geheimnis is not None:
            geheimnis.ueberschreiben()
        if LESER is not None:
            LESER.ueberschreiben(0, len(LESER.puffer))
        for s in gehalten:
            _sperre_freigeben(s)


def _eingereicht_felder(ergebnis: object, repo: object, job: str) -> dict | None:
    """Felder des Ereignisses eingereicht (C.2.4), geprüft: Zweig genau wamo/<job>, Nummer größer 0, Adresse genau die des Pull Requests."""
    if not isinstance(ergebnis, dict) or not isinstance(repo, str):
        return None
    zweig, pr, adresse = ergebnis.get("zweig"), ergebnis.get("pr"), ergebnis.get("adresse")
    if zweig != f"wamo/{job}" or type(pr) is not int or pr <= 0 or adresse != f"https://github.com/{repo}/pull/{pr}":
        return None
    return {"zweig": zweig, "pr": pr, "adresse": adresse}


def github_dateien_entfernen(jobdir: Path) -> int:
    """Löscht die Kopien des Repos im Auftragsordner (GITHUB_DATEIEN), nie den Projektordner, auch Ordner mit entzogenen Rechten, ohne Links zu
    folgen. Liefert die Zahl der entfernten Einträge; bleibt einer stehen, OSError (der Aufrufer meldet das, statt Erfolg anzunehmen)."""
    anzahl = 0
    for name in GITHUB_DATEIEN:
        pfad = jobdir / name
        try:
            st = pfad.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(st.st_mode):
            _baum_entfernen(pfad)
        else:
            pfad.unlink(missing_ok=True)
        if os.path.lexists(pfad):
            raise OSError(f"{name} ließ sich nicht entfernen")
        anzahl += 1
    return anzahl


def projekt_leeren_ganz(projektdir: Path) -> bool:
    """Leert den Projektordner auch dann, wenn die Sandbox Rechte entzogen hat (u+rwx von oben nach unten, ohne Links zu folgen), und prüft
    danach, dass er leer ist."""
    if not projektdir.is_dir() or projektdir.is_symlink():
        return False
    _ordner_freigeben(projektdir)
    projekt_leeren_sicher(projektdir)
    try:
        with os.scandir(projektdir) as it:
            return next(it, None) is None
    except OSError:
        return False


def _aenderung_setzen(jobdir: Path, job: str, status: str) -> None:
    write_json_atomic(jobdir / "aenderung.json", {**aenderung_lesen(jobdir), "job": job, "status": status})


def cmd_verwerfen(job: str, profil: str) -> int:
    """verwerfen <job> <profil>: nur aus keine, gesperrt, nur_lesen und bereit, unter den Sperren .lauf und .einreichen; löscht aus.git,
    ergebnis/, Bundle und basis.git, nie den Projektordner (C.2.3). Ereignis verworfen, sonst einreichen_fehler mit zustand."""
    jobdir = _persoenlicher_auftrag(job, profil)
    gehalten = [Sperre(jobdir / ".lauf"), Sperre(jobdir / ".einreichen")]
    try:
        if not all(s.versuchen() for s in gehalten):
            return _einreichen_fehler(job, "zustand")
        status = aenderung_lesen(jobdir).get("status", "keine")
        if status not in VERWERFEN_AUS:
            return _einreichen_fehler(job, "zustand")
        entfernt = github_dateien_entfernen(jobdir)
        _aenderung_setzen(jobdir, job, "verworfen")
        log(f"verworfen {job} aus={status} entfernt={entfernt}", pflicht=True)
        wamo_event("verworfen", job=job)
        return EXIT_OK
    finally:
        for s in gehalten:
            _sperre_freigeben(s)


def _aufraeumen_faellig(jobdir: Path, jetzt: float) -> bool:
    status = aenderung_lesen(jobdir).get("status", "keine")
    grenze = AUFRAEUMEN_FERTIG_S if status in ("eingereicht", "verworfen") else AUFRAEUMEN_SONST_S
    return _alter_s(jobdir, jetzt) > grenze


def _alter_s(jobdir: Path, jetzt: float) -> float:
    """Alter eines Auftrags für das Aufräumen: seit der letzten Änderung von aenderung.json, status.json oder auftrag.json."""
    zeiten = []
    for name in ("aenderung.json", "status.json", "auftrag.json"):
        try:
            zeiten.append((jobdir / name).lstat().st_mtime)
        except OSError:
            continue
    return jetzt - max(zeiten) if zeiten else float("inf")


def github_aufraeumen(alle: bool = False, jetzt: float | None = None, hoechstens: int = 500) -> dict:
    """Aufräumen im persönlichen Weg (C.10.4): Kopien privater Repos in Auftragsordnern mit github=persoenlich löschen, eingereichte und
    verworfene nach AUFRAEUMEN_FERTIG_S, alle anderen nach AUFRAEUMEN_SONST_S (mit alle sofort), und Projektordner leeren, deren
    Eigner-Auftrag so aufgeräumt ist oder seinen Klon nicht mehr hat. Jeden Auftrag nur unter .lauf und .einreichen, jedes Projekt nur unter
    seiner Sperre (nie warten: ein aktiver Auftrag bleibt bis zum nächsten Lauf). Ein Auftrag, der noch nicht fertig war, steht danach auf
    verworfen (Nacharbeit ist ein neuer Auftrag)."""
    jetzt = time.time() if jetzt is None else jetzt
    aufgeraeumt: set[str] = set()
    ergebnis = {"auftraege": 0, "projekte": 0, "uebersprungen": 0}
    try:
        jobs = sorted(e.name for e in os.scandir(JOBS) if JOB_RE.fullmatch(e.name) and e.is_dir(follow_symlinks=False))
    except OSError:
        jobs = []
    for job in jobs[:hoechstens]:
        jobdir = JOBS / job
        meta = read_json(jobdir / "auftrag.json", None)
        if not isinstance(meta, dict) or meta.get("github") != GITHUB_WEG:
            continue
        if not alle and not _aufraeumen_faellig(jobdir, jetzt):
            continue
        gehalten = [Sperre(jobdir / ".lauf"), Sperre(jobdir / ".einreichen")]
        try:
            if not all(s.versuchen() for s in gehalten):
                ergebnis["uebersprungen"] += 1
                continue
            if not alle and not _aufraeumen_faellig(jobdir, jetzt):  # unter den Sperren neu: ein Einreichen kann dazwischen fertig sein
                continue
            status = aenderung_lesen(jobdir).get("status", "keine")
            if github_dateien_entfernen(jobdir):
                ergebnis["auftraege"] += 1
            if status not in ("eingereicht", "verworfen"):
                _aenderung_setzen(jobdir, job, "verworfen")
            aufgeraeumt.add(job)
        except Exception as e:  # noqa: BLE001 (ein Auftrag hält das Aufräumen der anderen nie auf)
            log(f"aufraeumen {job}: nicht vollständig ({type(e).__name__})")
            ergebnis["uebersprungen"] += 1
        finally:
            for s in gehalten:
                _sperre_freigeben(s)
    try:
        eigner = sorted(e.name for e in os.scandir(sperren_ordner()) if e.name.startswith(EIGNER_PRAEFIX) and e.name.endswith(".json"))
    except OSError:
        eigner = []
    for name in eigner[:hoechstens]:
        projekt = name[len(EIGNER_PRAEFIX):-len(".json")]
        if not PROJECT_RE.fullmatch(projekt) or "--" in projekt:
            continue
        job = eigner_lesen(projekt)
        if job is not None and job not in aufgeraeumt and os.path.lexists(JOBS / job / "basis.git"):
            continue  # der Eigner-Auftrag lebt noch und hat seinen Klon
        sperre = Sperre(sperren_ordner() / f"projekt-{projekt}")
        try:
            if not sperre.versuchen():
                ergebnis["uebersprungen"] += 1
                continue
            ordner = PROJEKTE / projekt
            if not os.path.lexists(ordner) or projekt_leeren_ganz(ordner):
                ergebnis["projekte"] += 1 if os.path.lexists(ordner) else 0
                eigner_entfernen(projekt)  # nur nach Erfolg: sonst versucht es der nächste Lauf erneut
            else:
                log(f"aufraeumen: Projektordner {projekt} nicht leer, bleibt beim nächsten Lauf dran")
                ergebnis["uebersprungen"] += 1
        finally:
            _sperre_freigeben(sperre)
    return ergebnis


def cmd_aufraeumen(alle: str | None = None) -> int:
    """aufraeumen [alle]: nur im Kanal lokal (Timer wamo-job-aufraeumen.timer, wamo-job-rueckweg.sh). Antwort eine JSON-Zeile mit Zahlen."""
    if KANAL != "lokal":
        raise Abgewiesen("aufraeumen nur lokal")
    ergebnis = github_aufraeumen(alle=alle == "alle")
    log(f"aufraeumen {'alle' if alle else 'alt'}: {ergebnis['auftraege']} Aufträge, {ergebnis['projekte']} Projekte, "
        f"{ergebnis['uebersprungen']} übersprungen")
    emit({"ok": True, **ergebnis})
    return EXIT_OK


def _github_abgelehnt(jobdir: Path | None, job: str, projekt: str, art: str, grund: str) -> int:
    """Der persönliche Weg startet nicht: Ereignis start_abgelehnt mit genau einem Code (GITHUB_GRUENDE, im Folgelauf auch schon_eingereicht
    aus AENDERUNG_GRUENDE), Exit 8. Nie ein Rückfall auf den App-Weg, nie ein Wert im Text."""
    grund = _grund_pruefen(grund, "klon_fehler")
    log(f"github_abgelehnt {job} {projekt} {art}: {grund}", pflicht=True)
    wamo_event("start_abgelehnt", grund=grund)
    if jobdir is not None:
        _status(jobdir, job, projekt, art, ergebnis="start_abgelehnt", code=EXIT_GITHUB)
    return EXIT_GITHUB


def _github_ereignis(lauf: PersoenlicherLauf, jobdir: Path) -> dict:
    """Felder des Ereignisses github aus github.json (C.2.4): repo, konto, basis, standardzweig, privat, schreiben."""
    obj = read_json(jobdir / "github.json", {})
    obj = obj if isinstance(obj, dict) else {}
    zweig = obj.get("standardzweig")
    return {"repo": lauf.repo, "konto": lauf.login, "basis": lauf.basis,
            "standardzweig": zweig if isinstance(zweig, str) and re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", zweig) else None,
            "privat": obj.get("privat") is True, "schreiben": obj.get("schreiben") is True}


def klon_vorhanden(job: str, repo: str | None) -> bool:
    """Gibt es den Klon dieses Auftrags vollständig (basis.git und ein gültiges github.json)? Sonst gilt der Start als erster Lauf."""
    jobdir = JOBS / job
    if not os.path.isdir(jobdir / "basis.git") or os.path.islink(jobdir / "basis.git") or not isinstance(repo, str):
        return False
    try:
        PersoenlicherLauf.aus_datei(jobdir, job, repo)
    except ValueError:
        return False
    return True


def github_vorlauf(jobdir: Path, job: str, projekt: str, art: str, kopf: Kopf, platz: int,
                   geheimnis: "GithubGeheimnis | None") -> PersoenlicherLauf:
    """Vor dem Lauf im persönlichen Weg (C.5 Start 2 bis 6 und Folgelauf): beim ersten Lauf prüft und klont die GitHub-Logik mit dem Token
    außerhalb der Sandbox (github.json, basis.git), danach wird das Token überschrieben und das Ereignis github gesendet. Dann baut der
    Sandbox-Schritt klon die Arbeitskopie, wenn der Projektordner nicht aus dem Klon dieses Auftrags stammt: im Folgelauf aus basis.git und
    dem letzten Bundle; ohne Bundle nur, wenn der Auftrag noch nie ausgewertet wurde (kein aenderung.json: es gibt nichts zu verlieren),
    sonst projekt_gewechselt. Wirft GithubAbgelehnt mit einem Code oder KlonFehlgeschlagen."""
    if aenderung_lesen(jobdir).get("status", "keine") not in LAUF_ERLAUBT:
        raise GithubAbgelehnt("schon_eingereicht")  # eingereicht, verworfen oder im Einreichen: Nacharbeit ist ein neuer Auftrag
    if geheimnis is not None:
        werkzeuge = DispatcherWerkzeuge(job, projekt, jobdir, platz=platz, zugang=geheimnis, gehalten=(".lauf",))
        max_klon_mb = klon_grenze_mb()
        github_dateien_entfernen(jobdir)  # ein neuer Klon: keine Reste eines früheren Versuchs (Bundle, Kandidat, Ausgaben)
        (jobdir / "github.json").unlink(missing_ok=True)
        try:
            _github_aufruf("start", werkzeuge, job=job, repo=kopf.repo, art=art, profil=kopf.profil,
                           scopes_ausnahmen=kopf.scopes_ausnahmen, max_klon_mb=max_klon_mb, fehler="klon_fehler")
            lauf = PersoenlicherLauf.aus_datei(jobdir, job, kopf.repo)
            if baum_groesse_mb(jobdir / "basis.git", max_klon_mb + 1) > max_klon_mb:  # zweite Sicherung neben der Angabe von GitHub
                raise GithubAbgelehnt("repo_zu_gross")
        except (GithubAbgelehnt, ValueError) as e:
            github_dateien_entfernen(jobdir)  # kein halber Klon bleibt liegen (der nächste Start wäre sonst ein Folgelauf)
            (jobdir / "github.json").unlink(missing_ok=True)
            raise GithubAbgelehnt(e.grund if isinstance(e, GithubAbgelehnt) else "klon_fehler") from None
        finally:
            geheimnis.ueberschreiben()
        wamo_event("github", **_github_ereignis(lauf, jobdir))
    else:
        try:
            lauf = PersoenlicherLauf.aus_datei(jobdir, job, kopf.repo)
        except ValueError:
            raise GithubAbgelehnt("klon_fehler") from None
        bundle = (jobdir / "bundle.ein").is_file() and not (jobdir / "bundle.ein").is_symlink()
        if eigner_lesen(projekt) != job and not bundle and os.path.lexists(jobdir / "aenderung.json"):
            raise GithubAbgelehnt("projekt_gewechselt")
    if eigner_lesen(projekt) == job:
        return lauf  # der Ordner stammt aus dem Klon dieses Auftrags (auch wenn die GitHub-Logik den Schritt selbst gemacht hat)
    schritt = sandbox_schritt("klon", job, projekt, platz, schritt_argumente("klon", lauf, jobdir))
    if schritt.rc != 0:
        raise KlonFehlgeschlagen(f"Sandbox-Schritt klon rc={schritt.rc}: "
                                 + schritt.fehler.decode("utf-8", "replace").replace("\n", " ")[-200:])
    return lauf


def klon_grenze_mb() -> int:
    """MAX_KLON_MB aus kernkanal.conf (Standard 2048); ohne lesbare Konfiguration der Standard."""
    try:
        wert = getattr(kern_zustand().konfig, "max_klon_mb", None)
    except Exception:  # noqa: BLE001
        wert = None
    return wert if type(wert) is int and 100 <= wert <= 4096 else 2048


def baum_groesse_mb(pfad: Path, hoechstens: int) -> int:
    """Größe eines Ordners in MB (Summe der regulären Dateien, ohne Links zu folgen); hört ab hoechstens auf zu zählen."""
    summe = 0
    for wurzel, _ordner, dateien in os.walk(pfad, followlinks=False):
        for name in dateien:
            try:
                st = os.lstat(os.path.join(wurzel, name))
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                summe += st.st_size
                if summe > hoechstens * MIB:
                    return hoechstens
    return summe // MIB


MIB = 1024 * 1024


def _lauf_ergebnis(code: int) -> str:
    return "fertig" if code == EXIT_OK else "zeitlimit" if code == EXIT_ZEITLIMIT else "fehler"


def github_nachlauf(jobdir: Path, job: str, projekt: str, art: str, platz: int, code: int, kopf: Kopf, env: dict[str, str]) -> None:
    """Am Laufende im persönlichen Weg (ohne Token im Prozess, C.5 Laufende): die GitHub-Logik entschärft über die Sandbox-Schritte ausgabe
    und pruefung, prüft die Bytes, baut den Kandidaten in aus.git und schreibt aenderung.json. Danach sendet der Dispatcher das Ereignis
    aenderung aus der Datei. Ein Fehler der Logik setzt den Zustand gesperrt mit dem Code (nie bereit). Wirft nie."""
    try:
        werte = tuple(w for w, _ in schwaerzungen(env))
        werkzeuge = DispatcherWerkzeuge(job, projekt, jobdir, platz=platz, werte=werte, gehalten=(".lauf",))
        _github_aufruf("laufende", werkzeuge, job=job, projekt=projekt, art=art, profil=kopf.profil, auftrag=kopf.auftrag,
                       lauf=_lauf_ergebnis(code), fehler="pruefung_fehler")
    except GithubAbgelehnt as e:
        try:
            write_json_atomic(jobdir / "aenderung.json", {"job": job, "status": "gesperrt", "gruende": [e.grund],
                                                         "lauf": _lauf_ergebnis(code)})
        except OSError:
            log(f"aenderung {job}: aenderung.json nicht schreibbar")
    except Exception as e:  # noqa: BLE001 (der Abschluss des Auftrags darf nie an der Auswertung scheitern)
        log(f"aenderung {job} FEHLER {type(e).__name__}")
    try:
        wamo_event("aenderung", **aenderung_ereignis(job))
    except Exception as e:  # noqa: BLE001
        log(f"aenderung {job}: Ereignis nicht gesendet ({type(e).__name__})")


def persoenlich_aktiv() -> bool:
    """Für ping: gilt PERSOENLICH=an im Kern-Kanal (kernkanal.conf)? Wirft nie; ohne Modul oder Konfiguration False."""
    try:
        konfig = kern_zustand().konfig
        return getattr(konfig, "persoenlich", False) is True
    except Exception:  # noqa: BLE001 (ping muss immer antworten)
        return False


def cmd_start(job: str, projekt: str, art: str, session: str | None = None) -> int:
    """start <job> <projekt> <art> [<session>]: siehe Kopf dieser Datei. Am Ende wird der Lesepuffer von stdin überschrieben (dort stand
    im persönlichen Weg das GitHub-Token), auch bei jeder Abweisung, Ausnahme oder einem Signal."""
    try:
        return _start(job, projekt, art, session)
    finally:
        if LESER is not None:
            LESER.ueberschreiben(0, len(LESER.puffer))


def _start(job: str, projekt: str, art: str, session: str | None = None) -> int:
    kern = KANAL == "kern"
    try:
        kopf = parse_header(_kopfzeile_lesen())
    except Abgewiesen as e:
        if kern and str(e) == WAMO_REPO_GESPERRT:
            return kanal_abweisen("repo")
        raise
    if kern:  # erste Prüfung: vor Geheimnissen, Sperren und Selbsttest; Prüfen und Buchen des Versuchs unter der Sperre kernkanal
        with exklusiv(sperren_ordner() / KERN_SPERRE):
            grund, _konfig = kern_start_pruefen(job, projekt, art, kopf, app_modus=True)
            gebucht = grund is None and kern_versuch_buchen(job, kopf.profil)
        if grund is not None:
            return kanal_abweisen(grund)
        if not gebucht:  # ohne Zähler lassen sich die Grenzen nicht erzwingen
            return kanal_abweisen("grenze_start")
    elif KANAL == "pc" and projekt.startswith(KERN_PRAEFIX):
        raise Abgewiesen("Projektnamen mit kern- sind dem Kern-Kanal vorbehalten")
    wunsch = kopf.modell
    haus = kopf.zugang == "haus"  # Hausmodell über den Proxy: kein Claude-Zugang, keine zweite Zeile, ein Auftragstoken je Lauf
    try:  # ein Wunsch außerhalb der Allowlist scheitert vor allem anderen (bei haus gilt nur die Liste der Hausmodelle)
        if haus:
            haus_modell(wunsch)
        else:
            werkzeugkarte().modell_fuer(art, wunsch)
    except ValueError as e:
        raise Abgewiesen(str(e)) from None
    zugang = None
    if kopf.zugang == "folgt":  # persönlicher Zugang als zweite Zeile, jetzt lesen (vor Sperren und Selbsttest)
        try:
            zugang = parse_zugang(_zugangszeile_lesen(), kopf.profil)
        except ZugangUngueltig as e:
            log(f"zugang_ungueltig {job}: {e}", pflicht=True)
            wamo_event("zugang_ungueltig", grund=str(e)[:200])
            return EXIT_ABGEWIESEN
    persoenlich = kopf.github == GITHUB_WEG  # persönlicher GitHub-Weg (Plan C): nur im Kern-Kanal, das Token nur über stdin
    geheimnis = None
    if persoenlich:
        if not nicht_dumpbar():  # vor dem Lesen des Tokens: /proc dieses Prozesses gehört root (C.2.2)
            log(f"github_abgelehnt {job}: der Prozess ist dumpable, GitHub-Zeile nicht gelesen", pflicht=True)
            raise RuntimeError("PR_SET_DUMPABLE nicht wirksam")
        if not klon_vorhanden(job, kopf.repo):  # erster Lauf (oder halber Klon nach einem Absturz): die GitHub-Zeile ist Pflicht
            try:
                geheimnis = _githubzeile_lesen()
            except GithubZeileFehlt:
                return _github_abgelehnt(None, job, projekt, art, "github_zeile")
        elif LESER is not None:  # Folgelauf: eine mitgeschickte Zeile wird ungelesen verworfen
            LESER.rest_verwerfen()
    try:
        return _start_mit(job, projekt, art, session, kopf, zugang, persoenlich, geheimnis)
    finally:
        if geheimnis is not None:
            geheimnis.ueberschreiben()


def _start_mit(job: str, projekt: str, art: str, session: str | None, kopf: Kopf, zugang: ClaudeZugang | None, persoenlich: bool,
               geheimnis: GithubGeheimnis | None) -> int:
    kern = KANAL == "kern"
    auftrag, system, wunsch, repo = kopf.auftrag, kopf.system, kopf.modell, kopf.repo
    haus = kopf.zugang == "haus"
    aufraeumen()  # N5: alte Caches als wamo entfernen
    sperren = sperren_ordner()
    jobdir = job_ordner(job)
    # Eine Sperre gilt, solange ihr Objekt lebt (offene Datei): deshalb alle bis zum Ende festhalten.
    gehalten = [Sperre(jobdir / ".lauf")]
    if not gehalten[0].versuchen():
        belegt_melden("auftrag")
        return EXIT_BELEGT
    try:
        vorbereiten(jobdir, job, projekt, art, repo, KANAL, kopf.profil, kopf.github)
    except GithubWechsel:
        return _github_abgelehnt(jobdir, job, projekt, art, "github_wechsel")
    gehalten.append(Sperre(sperren / f"projekt-{projekt}"))
    if not gehalten[-1].versuchen():
        belegt_melden("projekt")
        return EXIT_BELEGT
    gesamt, je_person = parallel_grenzen()
    plaetze, platz, grenze = plaetze_belegen(sperren, person_schluessel(kopf.profil), gesamt, je_person)
    if grenze is not None:
        belegt_melden(grenze, je_person if grenze == "profil" else gesamt)
        return EXIT_BELEGT
    gehalten += plaetze
    platz_reste_beenden(platz)  # Reste eines hart beendeten Vorgängers auf diesem Platz
    sessions = read_json(jobdir / "sessions.json", [])
    if session is not None and (not isinstance(sessions, list) or session not in sessions):
        raise Abgewiesen("Session gehört nicht zu diesem Auftrag")
    lauf_persoenlich = None
    if persoenlich:  # Prüfung bei GitHub und Klon (erster Lauf), dann der Sandbox-Schritt klon, erst danach die Entschärfung (C.5 Start 6)
        try:
            lauf_persoenlich = github_vorlauf(jobdir, job, projekt, art, kopf, platz, geheimnis)
        except GithubAbgelehnt as e:
            return _github_abgelehnt(jobdir, job, projekt, art, e.grund)
        except KlonFehlgeschlagen as e:
            log(f"selbsttest {job} FEHLER: {str(e)[:300]}", pflicht=True)
            wamo_event("selbsttest_fehlgeschlagen", grund=str(e)[:300])
            _status(jobdir, job, projekt, art, ergebnis="selbsttest_fehlgeschlagen", code=EXIT_SELBSTTEST)
            return EXIT_SELBSTTEST
        finally:
            if geheimnis is not None:
                geheimnis.ueberschreiben()
    else:
        eigner_entfernen(projekt)  # ein Lauf ohne persönlichen Weg: der Ordner stammt danach nicht mehr aus dem Klon eines Auftrags
    lauf_vorbereiten(jobdir, projekt)

    ok, grund = selbsttest(job, projekt, "lauf", platz)
    log(f"selbsttest {job} {'ok' if ok else 'FEHLER'}: {grund[:300]}", pflicht=True)
    if not ok:
        wamo_event("selbsttest_fehlgeschlagen", grund=grund[:300])
        _status(jobdir, job, projekt, art, ergebnis="selbsttest_fehlgeschlagen", code=EXIT_SELBSTTEST)
        return EXIT_SELBSTTEST
    wamo_event("selbsttest_ok")

    geheim = lese_geheimnisse()
    try:
        app = None if persoenlich else github_app_konfig(geheim)  # der persönliche Weg nutzt die App nie
    except GithubAppFehler as e:
        return _start_abgelehnt(jobdir, job, projekt, art, str(e))
    if haus:  # Schalter und Ordner des Proxys vor allem anderen; nie ein Rückfall auf einen Claude-Zugang
        grund = haus_problem(geheim)
        if grund is not None:
            return _haus_abgelehnt(jobdir, job, projekt, art, grund)
        zugang = ClaudeZugang("haus", haus_token(job), None, kopf.profil)
    elif zugang is None and not serverzugang_erlaubt(geheim):
        wamo_event("keine_zugangsdaten", grund="Kein persönlicher Claude-Zugang übergeben, und der Zugang aus geheim.env "
                   "ist abgeschaltet (WAMO_SERVERZUGANG=aus)")
        _status(jobdir, job, projekt, art, ergebnis="keine_zugangsdaten", code=EXIT_KEIN_ZUGANG)
        return EXIT_KEIN_ZUGANG
    env = sandbox_env(art, geheim, app_modus=app is not None, zugang=zugang, modell=wunsch if haus else None,
                      persoenlich=lauf_persoenlich)
    if env is None:
        wamo_event("keine_zugangsdaten", grund="ANTHROPIC_API_KEY oder CLAUDE_CODE_OAUTH_TOKEN in /etc/wamo/geheim.env fehlt")
        _status(jobdir, job, projekt, art, ergebnis="keine_zugangsdaten", code=EXIT_KEIN_ZUGANG)
        return EXIT_KEIN_ZUGANG
    modell = modell_waehlen(art, wunsch, zugang_typ(env))
    quelle = "haus" if haus else f"persoenlich-{zugang.typ}" if zugang is not None else "server"
    zugaenge = sorted(zugangs_quellen(art, geheim, app_modus=app is not None, repo=repo, zugang=zugang, persoenlich=persoenlich))
    snapshot = read_json(jobdir / "zustand" / "approvals.json", [])
    anfrage = zugang_pruefen(projekt, set(zugaenge), snapshot if isinstance(snapshot, list) else [])
    if anfrage is not None:
        angefragt_anhaengen(jobdir, [anfrage])
        log(f"zugang_erweitert {job} {projekt}: {', '.join(anfrage['input']['neu'])}", pflicht=True)
        wamo_event("zugang_erweitert", **anfrage)
        _status(jobdir, job, projekt, art, ergebnis="zugang_erweitert", code=EXIT_ZUGANG_ERWEITERT)
        return EXIT_ZUGANG_ERWEITERT
    github = GITHUB_WEG if persoenlich else "-" if werkzeugkarte().github_stufe(art) is None else "app" if app is not None else "token"
    if github == "app":
        system = f"{system}\n{github_hinweis(repo)}"
    elif persoenlich:
        system = f"{system}\n{github_hinweis_persoenlich(job)}"
    system = f"{system}\n{port_hinweis(platz)}"

    def zweite_pruefung():  # unmittelbar vor der Token-Erzeugung: eine Notaus-Datei oder eine neue Konfiguration seit der ersten greift noch
        return kern_start_pruefen(job, projekt, art, kopf, app_modus=app is not None, eigener_versuch=True)
    # Ab hier lebt ggf. ein GitHub-Token: SIGTERM und SIGHUP werden zur Ausnahme, damit Sandbox-Stopp und Widerruf
    # (finally in github_token_fuer_lauf) sicher laufen. SIGKILL lässt sich nicht abfangen: dann läuft das Token
    # nach spätestens einer Stunde ab. Im Kern-Kanal prüft kern_buchung zum zweiten Mal und bucht den Start unter einer Sperre.
    with _signale(_als_ausnahme), kern_buchung(job, kopf.profil, zweite_pruefung if kern else None) as (grund, konfig):
        if grund is not None:
            return kanal_abweisen(grund)
        grenzen = (str(konfig.max_turns), konfig.max_budget_usd) if kern else None  # nur aus kernkanal.conf, nie aus der Kopfzeile
        claude = claude_argv(system, modell, session, grenzen, haus=haus)
        argv = [str(RUNNER), "--auftrag", job, "--projekt", projekt, "--platz", str(platz), "--", *claude]
        try:
            with github_token_fuer_lauf(job, art, repo, app) as gh_token:
                if gh_token is not None:
                    env = sandbox_env(art, geheim, app_modus=True, gh_token=gh_token, zugang=zugang, modell=wunsch if haus else None)
                    if kern:  # Regel 8: kein Fork, keine Vorlage, kein Ursprung wamo; das Token wird danach widerrufen
                        grund = kern_fork_grund(repo, gh_token)
                        if grund is not None:
                            return kanal_abweisen(grund)
                log(f"start {job} {projekt} {art} {'fortsetzung' if session else 'neu'} modell={modell} "
                    f"zugaenge={','.join(zugaenge)} github={github} repo={repo or '-'} claude={quelle} "
                    f"profil={kopf.profil or '-'}", pflicht=True)
                with haus_lauf(job, zugang, geheim):  # nur bei haus: die Tokendatei für den Proxy, weg am Laufende
                    code = _ausfuehren(argv, env, auftrag, jobdir, job, projekt, art)
                if persoenlich:  # Laufende ohne Token: Ausgabe, Prüfung und Kandidat, dann das Ereignis aenderung (C.5 Laufende)
                    github_nachlauf(jobdir, job, projekt, art, platz, code, kopf, env)
        except GithubAppFehler as e:
            return _start_abgelehnt(jobdir, job, projekt, art, str(e))
        except HausNichtBereit as e:
            return _haus_abgelehnt(jobdir, job, projekt, art, str(e))
    del gehalten  # erst jetzt frei (Prozessende gibt sie ohnehin frei)
    return code


def _haus_abgelehnt(jobdir: Path, job: str, projekt: str, art: str, grund: str) -> int:
    """Ein Lauf mit Hausmodell startet nicht (Schalter aus, Ordner des Proxys fehlt, Tokendatei nicht schreibbar): Ereignis
    keine_zugangsdaten mit zugang haus (der Kern nennt dann den Satz für Hausmodelle), nie ein Rückfall auf einen anderen Zugang."""
    grund = f"Hausmodelle: {grund}"[:300]
    log(f"haus_abgelehnt {job} {projekt} {art}: {grund}", pflicht=True)
    wamo_event("keine_zugangsdaten", zugang="haus", grund=grund)
    _status(jobdir, job, projekt, art, ergebnis="keine_zugangsdaten", code=EXIT_KEIN_ZUGANG)
    return EXIT_KEIN_ZUGANG


def _start_abgelehnt(jobdir: Path, job: str, projekt: str, art: str, grund: str) -> int:
    """App-Modus kaputt oder Token nicht erzeugbar: nichts startet, kein Rückfall auf den persönlichen Token."""
    grund = f"GitHub-App: {grund}"[:300]
    log(f"start_abgelehnt {job} {projekt} {art}: {grund}", pflicht=True)
    wamo_event("start_abgelehnt", grund=grund)
    _status(jobdir, job, projekt, art, ergebnis="start_abgelehnt", code=EXIT_GITHUB_APP)
    return EXIT_GITHUB_APP


def claude_argv(system: str, modell: str, session: str | None = None, grenzen: tuple[str, str] | None = None,
                haus: bool = False) -> list[str]:
    """Aufruf von Claude Code in der Sandbox (auch vom Rauchtest genutzt). grenzen (Wendungen, Kosten in USD) gibt es nur im
    Kern-Kanal und nur aus kernkanal.conf: --max-turns und --max-budget-usd. haus: Einstellungen ohne Vorabprüfung von WebFetch."""
    argv = [str(CLAUDE), "-p", "--output-format", "stream-json", "--verbose", "--permission-mode",
            "bypassPermissions", "--model", modell, "--settings", PLUGIN_SETTINGS_HAUS if haus else PLUGIN_SETTINGS,
            "--append-system-prompt", system]
    if session:
        argv += ["--resume", session]
    if grenzen:
        argv += ["--max-turns", grenzen[0], "--max-budget-usd", grenzen[1]]
    return argv


def _status(jobdir: Path, job: str, projekt: str, art: str, **fields) -> None:
    status = read_json(jobdir / "status.json", {})
    status = status if isinstance(status, dict) else {}
    status.update({"job": job, "projekt": projekt, "art": art, **fields})
    write_json_atomic(jobdir / "status.json", status)


def _ausfuehren(argv: list[str], env: dict, auftrag: str, jobdir: Path, job: str, projekt: str, art: str) -> int:
    if (jobdir / "abbruch").exists():  # cancel nach dem Vorbereiten (zum Beispiel der Notaus, der alle Aufträge beendet): nichts mehr starten
        _status(jobdir, job, projekt, art, ende=int(time.time()), ergebnis="abgebrochen", code=None)
        log(f"ende {job} abgebrochen vor dem Start (cancel)")
        wamo_event("ende", ergebnis="abgebrochen", code=None)
        return EXIT_ABGEBROCHEN
    start = time.time()
    _status(jobdir, job, projekt, art, start=int(start), ende=None, ergebnis="läuft", code=None)
    log_pfad = jobdir / "lauf.log"
    if log_pfad.is_file() and not log_pfad.is_symlink():
        os.replace(log_pfad, jobdir / "lauf.log.1")  # je Lauf ein Protokoll, das vorige bleibt einmal erhalten
    # Freigaben atomar außerhalb der Sandbox (M5): Socket im Zustand-Ordner, in der Sandbox /run/wamo/zustand/freigabe.sock
    freigabe = FreigabeServer(jobdir / "zustand" / "freigabe.sock",
                              read_json(jobdir / "zustand" / "approvals.json", []))
    freigabe.start()
    gruende: list[str] = []
    gestoppt = threading.Event()
    proc = None  # gesetzt direkt nach dem Start unten; die folgenden Funktionen lesen es erst danach

    def stoppen(grund: str) -> None:
        if gestoppt.is_set():
            return
        gestoppt.set()
        gruende.append(grund)
        stop_units(job)
        if proc is None:  # Signal noch vor dem Start des Prozesses: es gibt nichts zu beenden
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                break
            try:
                proc.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                continue

    def lebenslinie() -> None:
        # stdin der SSH-Verbindung: EOF heißt, der Voice-Core ist weg (Auflegen, Abbruch, Netz)
        try:
            _lebenslinie_warten()
        except (OSError, ValueError):
            pass
        if proc.poll() is None:
            stoppen("verlassen")

    def egress_wache() -> None:
        # M6: fällt der Ausgangsfilter aus (nft neu geladen o. Ä.), sofort stoppen
        while not gestoppt.wait(15):
            if proc.poll() is not None:
                return
            if egress_offen():
                log(f"egress_offen {job}: Ausgangsfilter weg, Auftrag gestoppt", pflicht=True)
                stoppen("egress_offen")
                return

    def stderr_sichern() -> None:
        written = 0
        with open(log_pfad, "ab") as f:
            for raw in zeilen(proc.stderr, MAX_ZEILE_STDERR):
                if raw is not None and written < MAX_LOG_BYTES:
                    raw = schwaerzen(raw, ersetzungen)  # ein Zugangswert gehört auch nicht ins Protokoll des Auftrags
                    f.write(raw)
                    f.flush()
                    written += len(raw)

    # GitHub-Token und Claude-Zugang sind Geheimnisse dieses Laufs: erscheinen sie in der Ausgabe des Agenten, werden sie
    # vor dem Weiterreichen an den PC (Canvas, Sprachmodell) geschwärzt, ebenso im Protokoll und nach dem Lauf in den
    # Dateien unter claude/ (Defense in Depth; kodierte Formen fängt das nicht)
    ersetzungen = schwaerzungen(env)
    kontingent = kontingent_modul()
    kontingent_zuletzt: list | None = None
    kontingent_ungesendet: dict | None = None
    kontingent_gesendet = float("-inf")
    verworfen = 0
    # Der try-Block beginnt vor dem Start: ein Signal ab hier stoppt immer auch die Sandbox, selbst wenn es
    # zwischen Popen und dem ersten Befehl danach eintrifft
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=env, cwd="/", start_new_session=True)
        stderr_thread = threading.Thread(target=stderr_sichern, daemon=True)
        stderr_thread.start()
        threading.Thread(target=lebenslinie, daemon=True).start()
        threading.Thread(target=egress_wache, daemon=True).start()
        try:
            proc.stdin.write(auftrag.encode("utf-8"))
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        wamo_event("gestartet")
        sessions = read_json(jobdir / "sessions.json", [])
        sessions = sessions if isinstance(sessions, list) else []
        zaehler = Freigabezaehler(read_json(jobdir / "zustand" / "approvals.json", []))
        for raw in zeilen(proc.stdout, MAX_ZEILE_STDOUT):
            if raw is None or ist_wamo_zeile(raw):
                verworfen += 1
                continue
            if zaehler.sehen(raw):
                log(f"freigabe_mehrfach {job}: freigegebener Aufruf öfter ausgeführt als freigegeben", pflicht=True)
                stoppen("freigabe_mehrfach")
            if b'"session_id"' in raw:
                try:
                    sid = json.loads(raw).get("session_id")
                except (ValueError, AttributeError, RecursionError):
                    sid = None
                if isinstance(sid, str) and SESSION_RE.fullmatch(sid) and sid not in sessions:
                    sessions.append(sid)
                    write_json_atomic(jobdir / "sessions.json", sessions[-50:])
            ausgabe = raw if raw.endswith(b"\n") else raw + b"\n"
            ausgabe = schwaerzen(ausgabe, ersetzungen)
            if not emit_raw(ausgabe):
                stoppen("verlassen")
                break
            if kontingent is not None and b'"rate_limit_event"' in raw:
                # Limits des Abos: die Zeile kommt aus der Sandbox, also nur Felder der Allowlist und mit Wertebereich;
                # eigene Zeile vom Typ wamo (die der Sandbox werden verworfen). Unveränderte Werte nicht wiederholen,
                # höchstens ein Ereignis alle KONTINGENT_ABSTAND_S; der letzte Stand kommt nach der Schleife nach.
                ereignis = kontingent_ereignis(kontingent, raw)
                if ereignis is not None and ereignis["limits"] != kontingent_zuletzt:
                    kontingent_zuletzt = ereignis["limits"]
                    kontingent_ungesendet = ereignis
                if kontingent_ungesendet is not None and time.monotonic() - kontingent_gesendet >= KONTINGENT_ABSTAND_S:
                    emit(kontingent_ungesendet)
                    kontingent_ungesendet, kontingent_gesendet = None, time.monotonic()
        rc = proc.wait()
        stderr_thread.join(timeout=5)  # das Protokoll des Auftrags ist vollständig, bevor es geprüft wird
        if kontingent_ungesendet is not None:
            emit(kontingent_ungesendet)  # der letzte Stand gehört dazu, auch wenn der Abstand noch nicht um war
        zugang_aufraeumen(jobdir, job, ersetzungen)
    except BaseException:
        # Signal (_Beendet) oder Fehler im Dispatcher: die Sandbox nie unbeobachtet weiterlaufen lassen; der
        # Aufrufer widerruft danach ein GitHub-Token (finally in github_token_fuer_lauf)
        with _signale(signal.SIG_IGN):  # ein zweites SIGTERM darf das Stoppen der Sandbox nicht unterbrechen
            stoppen("intern")
            freigabe.stop()
            zugang_aufraeumen(jobdir, job, ersetzungen)
            try:
                _status(jobdir, job, projekt, art, ende=int(time.time()), ergebnis="abgebrochen", code=None)
            except OSError:
                pass
            log(f"ende {job} intern (Dispatcher unterbrochen, Sandbox gestoppt)")
        raise
    freigabe.stop()
    if (jobdir / "abbruch").exists():
        ergebnis, code = "abgebrochen", EXIT_ABGEBROCHEN
    elif gruende:
        ergebnis, code = gruende[0], EXIT_ABGEBROCHEN
    elif rc in (124, 137):
        ergebnis, code = "zeitlimit", EXIT_ZEITLIMIT
    elif rc == 0:
        ergebnis, code = "fertig", EXIT_OK
    else:
        ergebnis, code = "fehler", rc if 0 < rc < 256 else EXIT_INTERN
    _status(jobdir, job, projekt, art, ende=int(time.time()), ergebnis=ergebnis, code=rc)
    log(f"ende {job} {ergebnis} rc={rc} dauer={int(time.time() - start)}s"
        + (f" verworfene_zeilen={verworfen}" if verworfen else ""))
    wamo_event("ende", ergebnis=ergebnis, code=rc)
    return code


# ---------------------------------------------------------------- pruefen: ein Befehl der Abnahme in der Sandbox
PRUEFEN_ZAEHLER = "pruefen.json"  # im Auftragsordner (die Sandbox sieht ihn nicht): {"aufrufe": n}


def pruefen_env() -> dict[str, str]:
    """Umgebung des Läufers im Modus pruefen: die Basisumgebung plus Git-Hooks aus, sonst nichts. Kein sandbox_env: keine
    Token, kein Claude-Zugang, keine Einstellung der Auftragsart. Der Läufer lässt im Modus pruefen ohnehin nur diese Namen durch."""
    env = basis_env()
    env["GIT_CONFIG_COUNT"] = str(len(GIT_OHNE_HOOKS))
    for i, (schluessel, wert) in enumerate(GIT_OHNE_HOOKS):
        env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"] = schluessel, wert
    return env


def _pruefen_zeile_lesen() -> bytes:
    return _zeile_lesen(pruefen_modul().ZEILE_MAX_BYTES + 1, "argv-Zeile")


def lebenslinie_beobachten(bei_ende) -> threading.Thread:
    """stdin der SSH-Verbindung ist die Lebenslinie: EOF oder ein Lesefehler heißt, der Voice-Core ist weg (Auflegen, Abbruch,
    Netz). Dann ruft der Thread bei_ende genau einmal auf. Daten auf stdin werden gelesen und verworfen."""
    def lesen() -> None:
        try:
            while sys.stdin.buffer.read1(65536):
                pass
        except (OSError, ValueError):
            pass
        bei_ende()
    faden = threading.Thread(target=lesen, daemon=True)
    faden.start()
    return faden


def _pruefen_waechter(argv: list[str], projektdir: Path) -> None:
    """Der Wächter entscheidet wie bei einem Bash-Aufruf des Auftrags. Nur allow läuft: block, Freigabepflicht und jeder Fehler
    heißen nicht ausführen (eine Freigabekarte umgeht die Abnahme nie)."""
    try:
        entscheidung, grund = mit_zeitlimit(lambda: waechter().decide("Bash", {"command": shlex.join(argv)}, projektdir),
                                            DECIDE_TIMEOUT_S)
    except (Exception, _Zeitueberschreitung):
        raise Abgewiesen("Der Wächter konnte den Befehl nicht prüfen, er wurde nicht ausgeführt") from None
    if entscheidung == "block":
        raise Abgewiesen(f"Vom Wächter gesperrt: {str(grund)[:200]}")
    if entscheidung != "allow":
        raise Abgewiesen(f"Der Wächter verlangt eine Freigabe, das läuft nie automatisch: {str(grund)[:200]}")


def _pruefen_sperren(jobdir: Path, projekt: str) -> tuple[list, str | None, int | None]:
    """Sperren wie bei start: ein Lauf je Auftrag, ein Auftrag je Projekt, ein Platz je Person (pruefen kommt nur aus dem PC-Kanal oder
    lokal: Person pc bzw. lokal) und gesamt. Liefert (gehaltene Sperren, Grund für belegt oder None, Platz). Die Sperren gelten, solange die
    Liste lebt."""
    sperren = sperren_ordner()
    gehalten = [Sperre(jobdir / ".lauf")]
    if not gehalten[0].versuchen():
        return gehalten, "belegt: Dieser Auftrag läuft gerade", None
    gehalten.append(Sperre(sperren / f"projekt-{projekt}"))
    if not gehalten[-1].versuchen():
        return gehalten, f"belegt: {belegt_text('projekt')}", None
    gesamt, je_person = parallel_grenzen()
    plaetze, platz, grenze = plaetze_belegen(sperren, person_schluessel(None), gesamt, je_person)
    if grenze is not None:
        return gehalten, f"belegt: {belegt_text(grenze, je_person if grenze == 'profil' else gesamt)}", None
    platz_reste_beenden(platz)  # Reste eines hart beendeten Vorgängers auf diesem Platz
    return gehalten + plaetze, None, platz


def _pruefen_zaehlen(jobdir: Path, aufrufe_max: int) -> None:
    """Höchstens aufrufe_max Prüfungen je Auftrag (die Sandbox ist ein einziger Platz). Ein unlesbarer Zähler sperrt
    (fail-closed); nur der Dispatcher schreibt ihn, die Sandbox sieht den Auftragsordner nicht."""
    pfad = jobdir / PRUEFEN_ZAEHLER
    n: object = 0  # ohne Datei: noch keine Prüfung
    if os.path.lexists(pfad):
        text = read_no_follow(pfad, 4096)
        try:
            daten = json.loads(text) if text is not None else None
        except (ValueError, RecursionError):
            daten = None
        n = daten.get("aufrufe") if isinstance(daten, dict) else None
    if type(n) is not int or n < 0:
        raise Abgewiesen("Der Prüfzähler des Auftrags ist unlesbar")
    if n >= aufrufe_max:
        raise Abgewiesen(f"Höchstens {aufrufe_max} Prüfungen je Auftrag, dieser Auftrag hat sie verbraucht")
    write_json_atomic(jobdir / PRUEFEN_ZAEHLER, {"aufrufe": n + 1})


class PruefenNichtVerfuegbar(RuntimeError):
    """Der Schalter ist an, aber die Prüflogik (wamo_job_pruefen.py, abnahme_befehl.py) fehlt oder ist defekt: ein Fehler der
    Einrichtung, kein Verstoß des Aufrufers (Prozess-Exit 6 statt 2)."""


PRUEFEN_NICHT_VERFUEGBAR = "pruefen ist nicht verfügbar (die Prüflogik fehlt oder ist defekt)"
_LOG_UNSICHTBAR = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})


def antwort_leer_sicher(grund: object) -> dict:
    """Die Antwort für einen Aufruf, der nichts ausgeführt hat, auch wenn die Prüflogik fehlt oder defekt ist: dann genau dieselben
    Felder aus festen Werten (v, ok false, exit null, abgebrochen false, grund, dauer_s 0.0, ausgabe leer, gekuerzt false). Es kommt
    immer genau eine Zeile; der Kern wertet jede Antwort ohne ok true als nicht erfüllt."""
    try:
        return pruefen_modul().antwort_leer(str(grund))
    except Exception:  # noqa: BLE001 (das Modul fehlt oder ist defekt: die feste Antwort ohne das Modul)
        pass
    text = " ".join("".join(" " if c.isspace() else ("" if unicodedata.category(c) in _LOG_UNSICHTBAR else c)
                            for c in str(grund)).split())
    return {"v": 1, "ok": False, "exit": None, "abgebrochen": False, "grund": text if len(text) <= 300 else text[:299].rstrip() + "…",
            "dauer_s": 0.0, "ausgabe": "", "gekuerzt": False}


def _pruefen_logger(pm, ersetzungen: list[tuple[bytes, bytes]]):
    """Liefert (sauber, plog). sauber(text, grenze) macht freien Inhalt (argv, Fehlertext der Sandbox) zu einer Zeile ohne Steuer-
    und Format-Zeichen, geschwärzt und gekürzt; plog schreibt sie mit Pflicht (ein Schreibfehler bricht den Befehl ab) oder ohne."""
    def sauber(text: object, grenze: int | None = None) -> str:
        return pm.log_text(text, pm.LOG_ZEICHEN if grenze is None else grenze, schwaerzen=lambda daten: schwaerzen(daten, ersetzungen))

    def plog(text: str, pflicht: bool = True) -> None:
        log(sauber(text), pflicht=pflicht)
    return sauber, plog


def _pruefen_aufruf(pm, plog, job: str) -> tuple[list[str], str, Path, Path]:
    """Die stdin-Zeile, der Auftrag, das Projekt und der Wächter. Liefert (argv, Projektname, Auftragsordner, Projektordner);
    Abgewiesen für alles, was nicht laufen darf. Das Projekt kommt nie vom Aufrufer."""
    roh = _pruefen_zeile_lesen()
    try:
        argv = pm.argv_aus_zeile(roh)
    except pm.Abgelehnt as e:
        plog(f"pruefen_abgewiesen {job}: {e} zeile={json.dumps(roh.decode('utf-8', 'replace')[:200])}")
        raise Abgewiesen(str(e)) from None
    jobdir = _no_symlink(JOBS / job)
    meta = read_json(jobdir / "auftrag.json", None)
    if not isinstance(meta, dict):
        raise Abgewiesen("Auftrag unbekannt")
    projekt = check_project(str(meta.get("projekt", "")))
    projektdir = _no_symlink(PROJEKTE / projekt)
    if not projektdir.is_dir():
        raise Abgewiesen("Projektordner fehlt")
    try:
        _pruefen_waechter(argv, projektdir)
    except Abgewiesen as e:
        plog(f"pruefen_abgewiesen {job}: {e} argv={shlex.join(argv)}")
        raise
    return argv, projekt, jobdir, projektdir


def _pruefen_vorweg(pm, plog, job: str, projekt: str, jobdir: Path, projektdir: Path, argv: list[str]) -> tuple[int, dict] | None:
    """Unter den Sperren und vor dem ersten Eingriff: Reste einer früheren Sandbox des Auftrags beenden, nur nach einem Lauf, kein
    cancel, kein Pfad aus dem Projekt hinaus, der Zähler, die Platte, zuletzt das Entschärfen. Liefert None (weiter) oder
    (Exit, Antwort) für einen Aufruf, der nichts ausführt."""
    # Die Sperre hängt am Prozess: Wurde ein früherer Dispatcher dieses Auftrags mit SIGKILL beendet, lief seine Sandbox bis
    # RuntimeMaxSec weiter. Wer .lauf hält, darf alles Alte des Auftrags beenden, bevor er prüft oder entschärft.
    stop_units(job)
    status = read_json(jobdir / "status.json", None)  # unter der Auftragssperre: ein Lauf ist nicht mehr dabei zu schreiben
    if not isinstance(status, dict) or status.get("start") is None:
        raise Abgewiesen("Der Auftrag hatte noch keinen Lauf, pruefen gilt nur nach einem beendeten Lauf")
    if (jobdir / "abbruch").exists():
        return EXIT_ABGEBROCHEN, pm.antwort_leer("abgebrochen", abgebrochen=True)
    if grund := pm.pfad_grund(argv, projektdir):  # ein Link im Projekt darf nie aus dem Projektordner hinausführen
        plog(f"pruefen_abgewiesen {job}: {grund} argv={shlex.join(argv)}")
        raise Abgewiesen(grund)
    _pruefen_zaehlen(jobdir, pm.AUFRUFE_MAX)
    if grund := pm.platten_grund(projektdir, HEIM):  # freier Platz und Projektgröße, vor jedem Aufruf (keine echte Quote)
        plog(f"pruefen_nicht_moeglich {job}: {grund}")
        return EXIT_ABGEWIESEN, pm.antwort_leer(grund)
    for entfernt in projekt_entschaerfen(projektdir):
        plog(f"entschärft {job} {projekt}: {entfernt}", pflicht=False)
    return None


def _pruefen_nachher_entschaerfen(plog, job: str, projekt: str, projektdir: Path) -> None:
    """Nach dem Lauf erneut entschärfen: gepflanzte Hooks und .git/config bleiben so nicht bis zum nächsten start oder pruefen
    liegen. Die Sandbox ist hier beendet. Ein Fehler steht im Audit und verdeckt weder das Ergebnis noch eine laufende Ausnahme
    (jeder nächste Lauf entschärft vor dem Start und scheitert dort fail-closed)."""
    try:
        for entfernt in projekt_entschaerfen(projektdir):
            plog(f"entschärft {job} {projekt} (nach dem Lauf): {entfernt}", pflicht=False)
    except Exception as e:  # noqa: BLE001
        plog(f"entschaerfen_nach_dem_lauf_fehlgeschlagen {job} {projekt}: {type(e).__name__}", pflicht=False)


def _pruefen_ausfuehren(pm, sauber, plog, ersetzungen, job: str, projekt: str, jobdir: Path, projektdir: Path,
                        argv: list[str], platz: int) -> tuple[int, dict]:
    """Selbsttest, Lauf und Antwort. cancel kann den Lauf nur beenden, solange eine Einheit läuft: Eine abbruch-Datei, die zwischen
    der letzten Prüfung und dem Start der Einheit entsteht, macht das Ergebnis nach dem Lauf nicht erfüllt (Rest: höchstens die
    120 Sekunden dieses Laufs). cancel wirkt jobweit (abbruch-Datei, alle Einheiten des Auftrags). platz: der gehaltene Platz (Ports)."""
    lauf = pm.Lauf([str(RUNNER), "--auftrag", job, "--projekt", projekt, "--platz", str(platz), "--modus", "pruefen", "--zeitlimit",
                    str(pm.ZEITLIMIT_S), "--einheit-zusatz", "pruefen", "--", *argv], pruefen_env(), lambda: stop_units(job),
                   zeitlimit_s=pm.ZEITLIMIT_S, cwd="/")
    lebenslinie_beobachten(lambda: lauf.stoppen("verlassen"))  # schon während des Selbsttests: Auflegen verhindert den Start
    try:
        with _signale(_als_ausnahme):
            vorher = time.monotonic()
            ok, grund = selbsttest(job, projekt, "pruefen", platz)
            plog(f"selbsttest {job} pruefen {'ok' if ok else 'FEHLER'} dauer={time.monotonic() - vorher:.1f}s: {grund}")
            if lauf.gestoppt:  # Auflegen während des Selbsttests (die Einheit des Selbsttests wurde dabei beendet)
                return EXIT_ABGEBROCHEN, pm.antwort_leer(lauf.grund or "verlassen", abgebrochen=True)
            if (jobdir / "abbruch").exists():  # cancel kam, während der Selbsttest lief (auch dann ist er womöglich gescheitert)
                return EXIT_ABGEBROCHEN, pm.antwort_leer("abgebrochen", abgebrochen=True)
            if not ok:
                return EXIT_SELBSTTEST, pm.antwort_leer(f"selbsttest_fehlgeschlagen: {sauber(grund, pm.GRUND_ZEICHEN)}")
            plog(f"pruefen {job} {projekt} argv={shlex.join(argv)}")
            if (jobdir / "abbruch").exists():  # die letzte Prüfung unmittelbar vor dem Start (cancel, während das Audit geschrieben wurde)
                return EXIT_ABGEBROCHEN, pm.antwort_leer("abgebrochen", abgebrochen=True)
            ergebnis = lauf.ausfuehren()
    except BaseException:
        lauf.stoppen("intern")  # auch ein Signal: die Sandbox nie unbeobachtet weiterlaufen lassen
        raise
    finally:
        stop_units(job)
        _pruefen_nachher_entschaerfen(plog, job, projekt, projektdir)
    if (jobdir / "abbruch").exists() and not ergebnis.abgebrochen:  # cancel beendet die Einheit, der Läufer endet dann "normal"
        ergebnis = replace(ergebnis, rc=None, abgebrochen=True, grund="abgebrochen")
    antwort = pm.antwort(ergebnis, lambda daten: schwaerzen(daten, ersetzungen))  # die Sandbox hat keine Geheimnisse; trotzdem schwärzen
    plog(f"pruefen_ende {job} exit={antwort['exit']} ok={antwort['ok']} abgebrochen={antwort['abgebrochen']} "
         f"grund={antwort['grund'] or '-'} dauer={antwort['dauer_s']}s")
    if antwort["grund"] == "zeitlimit":
        return EXIT_ZEITLIMIT, antwort
    return (EXIT_ABGEBROCHEN if antwort["abgebrochen"] else EXIT_OK), antwort


def _pruefen(job: str) -> tuple[int, dict]:
    """Der ganze Ablauf von pruefen. Liefert (Prozess-Exit, Antwort); Abgewiesen für alles, was nicht lief.

    pruefen führt keine Buchführung der Zugänge (zugang_pruefen): Der Lauf hat keine Zugänge, die Schnittmenge der Token früherer
    Läufe bleibt unberührt. Ein Lauf ohne Zugänge schriebe sie auf leer und löste vor jedem späteren start eine Freigabekarte aus.
    Gepflanzte Autostart-Flächen entfernt das Entschärfen vor und nach jedem Lauf (Hooks, .git/config, .claude, .mcp.json)."""
    pm = pruefen_modul()
    ersetzungen = schwaerzungen(lese_geheimnisse())  # was der Dispatcher kennt, steht nie in Antwort oder Protokoll
    sauber, plog = _pruefen_logger(pm, ersetzungen)
    argv, projekt, jobdir, projektdir = _pruefen_aufruf(pm, plog, job)
    if abnahme_modul().braucht_venv(argv) and not pm.venv_vorhanden(projektdir):
        return EXIT_ABGEWIESEN, pm.antwort_leer(pm.KEIN_VENV)
    gehalten, belegt, platz = _pruefen_sperren(jobdir, projekt)  # die Sperren gelten, bis diese Funktion endet
    if belegt:
        return EXIT_BELEGT, pm.antwort_leer(belegt)
    vorweg = _pruefen_vorweg(pm, plog, job, projekt, jobdir, projektdir, argv)
    if vorweg is not None:
        return vorweg
    ergebnis = _pruefen_ausfuehren(pm, sauber, plog, ersetzungen, job, projekt, jobdir, projektdir, argv, platz)
    del gehalten  # erst jetzt frei (Prozessende gibt sie ohnehin frei)
    return ergebnis


def cmd_pruefen(job: str) -> int:
    """pruefen <job>: siehe Kopf dieser Datei. Genau eine JSON-Zeile auf stdout, auch bei einer Abweisung und auch dann, wenn die
    Prüflogik fehlt oder defekt ist (antwort_leer_sicher)."""
    geheim = lese_geheimnisse()
    if not pruefen_aktiv(geheim):  # als Erstes, vor jedem Lesen und Laden: Schalter UND beide Module
        if not pruefen_schalter(geheim):
            emit(antwort_leer_sicher("pruefen ist abgeschaltet"))
            raise Abgewiesen("pruefen ist abgeschaltet (WAMO_PRUEFEN nicht an)")
        emit(antwort_leer_sicher(PRUEFEN_NICHT_VERFUEGBAR))  # an, aber ohne Modul: ein Fehler der Einrichtung (Exit 6), immer noch fail-closed
        raise PruefenNichtVerfuegbar(PRUEFEN_NICHT_VERFUEGBAR)
    try:
        code, antwort = _pruefen(job)
    except Abgewiesen as e:
        zeile = antwort_leer_sicher(str(e))
        emit(zeile)
        raise Abgewiesen(zeile["grund"]) from None  # bereinigt und gekürzt: auch das Protokoll von main und stderr bekommen nie freien Text
    except Exception as e:  # noqa: BLE001 (ein Fehler im Dispatcher: auch dann genau eine Zeile, main meldet ihn mit Exit 6)
        emit(antwort_leer_sicher(f"interner Fehler ({type(e).__name__})"))
        raise
    emit(antwort)
    return code


HANDLER = {"ping": cmd_ping, "start": cmd_start, "status": cmd_status, "pending": cmd_pending,
           "approve": cmd_approve, "cancel": cmd_cancel, "pruefen": cmd_pruefen,
           "aenderung": cmd_aenderung, "einreichen": cmd_einreichen, "verwerfen": cmd_verwerfen, "aufraeumen": cmd_aufraeumen}


def speicher_begrenzen() -> None:
    """Weiche Adressraumgrenze für diesen Prozess (Kinder setzen sie in wamo-job.sh wieder hoch) und keine
    Core-Dumps, die Token enthalten könnten (N2)."""
    try:
        import resource
        _, hart = resource.getrlimit(resource.RLIMIT_AS)
        weich = SPEICHER_DISPATCHER if hart == resource.RLIM_INFINITY else min(SPEICHER_DISPATCHER, hart)
        resource.setrlimit(resource.RLIMIT_AS, (weich, hart))
    except (ImportError, ValueError, OSError):
        pass
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, ValueError, OSError):
        pass
    try:
        import ctypes
        ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE=0
    except (OSError, AttributeError, ValueError, TypeError):
        pass


def main(argv: list[str] | None = None) -> int:
    # Über SSH zählt NUR SSH_ORIGINAL_COMMAND (argv ist durch command="..." fest leer). Ohne SSH (Rauchtest
    # als wamo) gelten die Argumente, mit derselben Prüfung.
    global KANAL, LESER
    if "SSH_CONNECTION" in os.environ or "SSH_ORIGINAL_COMMAND" in os.environ:
        raw = os.environ.get("SSH_ORIGINAL_COMMAND")
    else:
        raw = " ".join(sys.argv[1:] if argv is None else argv)
    try:
        KANAL = kanal_ermitteln() or "unklar"  # vor allem anderen: unklare Herkunft im strikten Modus endet hier
        if KANAL == "unklar":
            return kanal_abweisen("herkunft_unklar")
        name, args = parse_command(raw)
        if (KANAL == "pc" and name in BEFEHLE_PERSOENLICH) or (KANAL != "lokal" and name in BEFEHLE_NUR_LOKAL):
            return kanal_abweisen("befehl")  # der persönliche Weg gehört dem Kern-Kanal, das Aufräumen nur lokal
        gesperrt = kern_befehl_pruefen(name, args)
        if gesperrt is not None:
            return kanal_abweisen(gesperrt)
        if name == "start":  # Eingang; approve und cancel protokollieren selbst (Pflichtzeile), sonst doppelt
            log(f"{name} {' '.join(args)}")
        return HANDLER[name](*args)
    except Abgewiesen as e:
        log(f"ABGEWIESEN ({e}): {(raw or '')[:80]!r}")
        print(f"WAMO-Auftrag abgewiesen: {e}", file=sys.stderr)
        return EXIT_ABGEWIESEN
    except BrokenPipeError:  # der Voice-Core ist weg; still enden (N2)
        return EXIT_ABGEBROCHEN
    except _Beendet as e:  # SIGTERM/SIGHUP während eines Laufs: Sandbox gestoppt, Token widerrufen
        log(f"beendet durch Signal {e.args[0] if e.args else '?'}")
        return EXIT_ABGEBROCHEN
    except Exception as e:  # nichts durchreichen, aber protokollieren
        log(f"FEHLER {type(e).__name__}: {str(e)[:200]}")
        print(f"WAMO-Auftrag: interner Fehler ({type(e).__name__})", file=sys.stderr)
        return EXIT_INTERN
    finally:
        KANAL = "lokal"  # der Kanal gilt nur für diese Verbindung
        if LESER is not None:
            LESER.ueberschreiben(0, len(LESER.puffer))
        LESER = None


def beenden(code: int) -> None:
    """Hartes Ende nach dem Leeren der Puffer: der Lebenslinien-Thread hängt womöglich noch in einem
    blockierenden stdin-Read; ein normales Herunterfahren bräche dann mit SIGABRT ab (falscher Exit-Code)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    os._exit(code)


if __name__ == "__main__":
    # SIGPIPE bleibt ignoriert (Python-Standard): ein Schreibfehler auf stdout soll den Auftrag erst
    # beenden (BrokenPipeError, dann stoppen), nicht den Dispatcher vorher stumm abbrechen.
    speicher_begrenzen()
    beenden(main())
