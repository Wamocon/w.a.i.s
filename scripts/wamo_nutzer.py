"""WAMO-Nutzer verwalten: Konten und Profile im eigenen WAMO-Supabase auf Sokrates-2 anlegen, übergeben, ändern und sperren.

Aufrufe (im Repo-Hauptordner; alle ändernden Befehle verlangen --schema ausdrücklich, es gibt dafür keinen Standard):
  python scripts/wamo_nutzer.py anlegen --email kollege@wamocon.com --name "Vorname Nachname" --rolle mitglied --anrede du --schema wamo_dev
  python scripts/wamo_nutzer.py freischalten --email kollege@wamocon.com --schema wamo_dev [--frist-stunden 72] [--faktoren-loeschen]
  python scripts/wamo_nutzer.py zuruecksetzen --email kollege@wamocon.com --schema wamo_dev [--frist-stunden 72]
  python scripts/wamo_nutzer.py passwort --email kollege@wamocon.com --schema wamo_dev [--faktoren-loeschen]
  python scripts/wamo_nutzer.py umbenennen --email kollege@wamocon.com --name "Vorname Nachname" --schema wamo_dev
  python scripts/wamo_nutzer.py sperren --schema wamo_dev --email kollege@wamocon.com
  python scripts/wamo_nutzer.py sperren --schema wamo_dev --offene
  python scripts/wamo_nutzer.py austreten --email kollege@wamocon.com --schema wamo_dev
  python scripts/wamo_nutzer.py liste [--schema wamo_dev]
Optionen für alle Befehle: --host sokrates2 (Standard: Umgebung WAMO_SSH_HOST, sonst wamo-sokrates2; erlaubt sind Buchstaben, Ziffern,
Punkt, Unterstrich und Minus, nie ein Minus am Anfang).

Wichtig: freischalten, zuruecksetzen und passwort nur im eigenen Terminal ausführen. Das Passwort wird verdeckt eingetippt (zweimal,
mindestens 12 Zeichen, mindestens 6 verschiedene Zeichen), nie über eine Pipe gelesen und nie ausgegeben; so landet es auch nie im
Verlauf einer KI-Sitzung oder in einem Log. Das Startpasswort denkt sich der Admin aus oder nimmt es aus seinem Passwortmanager und
schreibt es auf das Willkommensblatt.

Befehle
  anlegen         Neues Konto mit einem Zufallspasswort, das niemand kennt (nie ausgegeben), anlegen und sofort in GoTrue sperren
                  (ban_duration 876000h, die Antwort muss banned_until enthalten, sonst Abbruch). Das Profil entsteht mit aktiv = false.
                  Ein vorhandenes Konto behält Passwort und Sperre; der Profil-Upsert ändert nur Anzeigename, Rolle und Anrede, nie aktiv.
                  Ein zweiter anlegen-Lauf sperrt ein vorhandenes, nicht gesperrtes Konto deshalb nicht nach (liste zeigt die Sperre
                  als Konto gesperrt oder Konto frei; freischalten sperrt ohnehin als Erstes). Danach folgt am Übergabetag freischalten.
  freischalten    Übergabetag: Konto und Profil prüfen, dann in fester Reihenfolge (siehe unten) ein neues Startpasswort setzen, den
                  Merker der Erstanmeldung schreiben (Frist 72 Stunden, einstellbar von 1 bis 168), das Profil aktivieren und die Sperre
                  aufheben. Das Startpasswort tippt der Admin verdeckt ein; die lokale Seite schickt es nur über stdin an den Server und
                  gibt es nie aus (nur auf dem Willkommensblatt).
  zuruecksetzen   Wie freischalten, aber die zweiten Faktoren werden immer gelöscht (verlorenes Handy), der Merker wird neu geschrieben.
  passwort        Option Ü: Die Person tippt ihr Passwort am Platz selbst verdeckt ein (zweimal, mindestens 12 Zeichen, mindestens 6
                  verschiedene Zeichen, nicht der Teil der E-Mail vor dem @). Reihenfolge wie freischalten, der Merker wird aber im
                  Schritt 5 als erledigt geschrieben. Das Passwort wird nie ausgegeben.
  umbenennen      Ändert nur den Anzeigenamen (1 bis 60 Zeichen), nie aktiv.
  sperren         Profil auf aktiv = false, Konto in GoTrue sperren, Sitzungen löschen. Mit --offene werden alle Nicht-Laborprofile des
                  Schemas gesperrt, deren Erstanmeldung offen oder abgelaufen ist (wamo_auth.erstanmeldung_stand): der Rückweg von P1b.
                  Bei --offene wird jedes Konto einzeln gesperrt; scheitert eines, geht es mit den übrigen weiter und am Ende nennt
                  das Skript die gescheiterten E-Mails (Exit 1).
  austreten       Zuerst abriegeln (Profil inaktiv, Sperre in GoTrue, Sitzungen), dann Faktoren löschen, die eigenen Geräte widerrufen
                  sowie Claude-Schlüssel und Claude-Code-Token löschen.
  liste           Profile mit Rolle, Aktivstand, E-Mail, Stand der Erstanmeldung (nur wenn wamo_auth.erstanmeldung_stand existiert, sonst -),
                  Frist, Zahl der bestätigten zweiten Faktoren und der Sperre des Kontos in GoTrue.
Laborkonten und Laborprofile fasst keiner dieser Befehle an (außer liste). Dafür gibt es scripts/wamo_labor.py. Geprüft wird über alle drei
Schemas (nur dort, wo profiles die Spalte labor_art hat), denn ein Konto gilt für alle Schemas und die Sperre in GoTrue träfe das Laborprofil
in einem anderen Schema mit. Dazu werden Adressen nach dem Muster labor-NN@wamo.test (NN 01 bis 16 oder schau) abgelehnt.

Reihenfolge von freischalten, zuruecksetzen und passwort, jeder Schritt wird geprüft, bei jedem Fehler bricht das Skript mit dem Namen
des Schritts ab und das Konto bleibt gesperrt (nach einem Fehler wird nie entsperrt):
  0  Konto und Profil im Schema vorhanden, kein Laborprofil in irgendeinem Schema (Rolle ist egal)
  1  Sperre in GoTrue setzen (banned_until in der Antwort)
  1b Sofort ein vorläufiger Merker (Stand offen, mit dem alten Hash): Alte Access-Tokens erreichen am Kern ab jetzt nur noch die
     Erstanmeldung. Der Merker aus Schritt 5 ersetzt ihn.
  2  Sitzungen löschen (delete from auth.sessions), danach darf es keinen gültigen Refresh-Token geben; dazu einmalige Tokens
     (auth.one_time_tokens) und Flow-State (auth.flow_state), sofern die Tabellen existieren, mit Zählprobe
  3  Zweite Faktoren: Gibt es welche und fehlt --faktoren-loeschen, Abbruch (ein Zeichen für eine fremde Einrichtung); sonst je Faktor
     DELETE /admin/users/<id>/factors/<fid>, danach muss die Zählung 0 sein
  4  Neues Startpasswort setzen (die Admin-Schnittstelle prüft die Länge nicht, das Skript verlangt 12 bis 72 Bytes). Der md5 des Werts von
     encrypted_password wird vor und nach dem Setzen gelesen; bleibt er gleich, Abbruch
  5  Erst jetzt den Merker endgültig schreiben: wamo_auth.erstanmeldung_anlegen liest den Hash des neuen Passworts als Startwert
     (bei passwort mit erledigt = true)
  6  Profil aktivieren (der Wächter aus Migration 0021 verlangt dafür den Merker)
  7  Sperre aufheben
Warum diese Reihenfolge: Die Sperre kommt zuerst, damit niemand mit dem alten Zustand des Kontos mitten im Wechsel anmelden kann; der
vorläufige Merker schließt die Lücke bis zum Passwort (alte Tokens); Sitzungen und Faktoren gehen vor dem neuen Passwort weg, damit eine
fremde Einrichtung nicht überlebt; der endgültige Merker entsteht erst nach dem Passwort, weil sein Startwert das neue Passwort ist (ein
Passwortwechsel durch die Person erledigt ihn später; der Trigger auf auth.users ignoriert Wechsel, solange das Konto gesperrt ist); die
Freigabe steht ganz hinten, damit ein Fehler nie ein halb vorbereitetes Konto offen lässt.

Sicherheit
  Der Service-Schlüssel des WAMO-Supabase bleibt auf Sokrates-2: Das Programm läuft dort (ssh, python3, Eingabe als JSON über stdin), liest
  den Schlüssel selbst und gibt ihn nie zurück. Die Admin-Anfragen an GoTrue gehen über Loopback (http://localhost:55321), nie über einen
  Proxy aus der Umgebung, und verlassen den Server nicht (kein TLS nötig, auch in Stufe 2 der WAMO-Firewall erlaubt). Passwörter stehen nie
  in einer Befehlszeile und werden von der entfernten Seite nie ausgegeben; Fehler der Admin-Schnittstelle erscheinen nur mit HTTP-Status
  und kurzer Kennung (zum Beispiel HTTP 422 weak_password). Datenbankzugriffe laufen als postgres über docker exec (psql-Variablen, keine
  Textbausteine im SQL). Die Befehlszeile für ssh ist gepackt (zlib, base64) und bleibt unter 20000 Zeichen (Windows erlaubt 32767); vor
  dem Host steht --, damit er nie als Option gilt.
  Je Auftrag schreibt die Gegenseite eine Zeile ins Journal (logger -t wamo-nutzer): Aktion, Schema, E-Mail, ok oder Fehler mit Schrittnummer,
  nie ein Passwort. Fehler von logger werden ignoriert. Ansehen mit: journalctl -t wamo-nutzer.
  Konten gelten für alle Schemas gemeinsam: Eine Sperre in GoTrue wirkt auf jedes Schema, das Profil wird nur im angegebenen Schema geändert.
  Die Registrierung im WAMO-Supabase ist geschlossen; Konten entstehen nur über dieses Skript.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import re
import secrets
import subprocess
import sys
import zlib

SCHEMA_RE = re.compile(r"wamo_(dev|test|prod)")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# Anmelde-Adressen der Laborkonten (wie scripts/wamo_labor.py): dieses Skript fasst sie nie an
LABOR_EMAIL_RE = re.compile(r"labor-(0[1-9]|1[0-6]|schau)@wamo\.test", re.IGNORECASE)
# Kein Minus am Anfang: ssh nähme den Host sonst als Option
HOST_RE = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._-]*")
MIN_PASSWORD = 12
MIN_VERSCHIEDEN = 6  # verschiedene Zeichen im Passwort
MAX_PASSWORD = 72  # bcrypt schneidet ab 72 Bytes ab, GoTrue lehnt längere Passwörter ab
FRIST_STANDARD = 72
FRIST_MAX = 168

# Läuft auf Sokrates-2 (python3), Eingabe als JSON über stdin. Die Logik steckt in Funktionen, die psql und den GoTrue-Aufruf als
# Parameter bekommen (verarbeite), damit die Tests sie ohne Server mit Attrappen ausführen können. Der Rumpf startet main() nur,
# wenn der Text als Programm läuft (python3 -c, dort ist __name__ gleich __main__).
REMOTE = r'''
import contextlib, json, re, secrets, subprocess, sys, urllib.error, urllib.request

SCHEMA_RE = re.compile(r"wamo_(dev|test|prod)")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
LABOR_EMAIL_RE = re.compile(r"labor-(0[1-9]|1[0-6]|schau)@wamo\.test", re.IGNORECASE)
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
KENNUNG_RE = re.compile(r"[a-z0-9_]{1,40}")
ENV_PFAD = "/home/wamocon/supabase-wamo/.env"
GOTRUE_URL = "http://localhost:55321/auth/v1"
SPERRE_DAUER = "876000h"
MIN_PASSWORD = 12
MIN_VERSCHIEDEN = 6
MAX_PASSWORD = 72
FRIST_STANDARD = 72
FRIST_MAX = 168
GESPERRT_BLEIBT = "Das Konto bleibt gesperrt."
STAND_PRUEFEN = "Stand mit liste prüfen."
FREMD_SATZ = ("Das Konto hat schon zweite Faktoren. Das ist ein Zeichen für eine fremde Einrichtung (jemand kannte das alte Passwort). "
              "Erst klären, dann bewusst mit --faktoren-loeschen entfernen.")

SQL = {
    "konto_suchen": "select id from auth.users where lower(email) = lower(:'email') limit 1;",
    "labor_schemas": """select table_schema from information_schema.columns
        where table_name = 'profiles' and column_name = 'labor_art' and table_schema in ('wamo_dev', 'wamo_test', 'wamo_prod')
        order by table_schema;""",
    "labor_zaehlen": """select count(*) from :"schema".profiles where user_id = :'uid' and labor_art is not null;""",
    "profil_lesen": """select case when p.labor_art is null then 'normal' else 'labor' end || '|'
        || case when p.aktiv then 'aktiv' else 'inaktiv' end || '|' || p.rolle::text
        from :"schema".profiles p where p.user_id = :'uid';""",
    "sitzungen_loeschen": """with d as (delete from auth.sessions where user_id = :'uid' returning 1)
        select count(*) from d;""",
    "refresh_zaehlen": "select count(*) from auth.refresh_tokens where user_id = :'uid' and not revoked;",
    "einmalig_vorhanden": """select (to_regclass('auth.one_time_tokens') is not null)::text || '|'
        || (to_regclass('auth.flow_state') is not null)::text;""",
    # Zwei Anweisungen: erst löschen (Anzahl), dann zählen (Rest); die Ausgabe hat zwei Zeilen
    "ott_loeschen": """with d as (delete from auth.one_time_tokens where user_id = :'uid' returning 1) select count(*) from d;
        select count(*) from auth.one_time_tokens where user_id = :'uid';""",
    "flow_loeschen": """with d as (delete from auth.flow_state where user_id = :'uid' returning 1) select count(*) from d;
        select count(*) from auth.flow_state where user_id = :'uid';""",
    "faktoren_liste": "select id from auth.mfa_factors where user_id = :'uid' order by created_at;",
    "faktoren_zaehlen": "select count(*) from auth.mfa_factors where user_id = :'uid';",
    "passwort_hash": "select md5(encrypted_password) from auth.users where id = :'uid';",
    "merker_anlegen": """select to_char(wamo_auth.erstanmeldung_anlegen(:'uid'::uuid, :'frist'::int, :'durch', :'erledigt'::boolean)
        at time zone 'Europe/Berlin', 'DD.MM.YYYY HH24:MI');""",
    "profil_aktivieren": """update :"schema".profiles set aktiv = true
        where user_id = :'uid' and labor_art is null returning user_id;""",
    "profil_deaktivieren": """update :"schema".profiles set aktiv = false
        where user_id = :'uid' and labor_art is null returning user_id;""",
    "profil_umbenennen": """update :"schema".profiles set display_name = :'name'
        where user_id = :'uid' and labor_art is null returning user_id;""",
    "profil_upsert": """insert into :"schema".profiles as p (user_id, display_name, rolle, anrede, aktiv)
        values (:'uid', :'name', :'rolle', :'anrede', false)
        on conflict (user_id) do update set display_name = excluded.display_name, rolle = excluded.rolle, anrede = excluded.anrede
        where p.labor_art is null
        returning case when p.aktiv then 'aktiv' else 'inaktiv' end;""",
    "stand_vorhanden": """select to_regprocedure('wamo_auth.erstanmeldung_stand(uuid)') is not null
        and to_regclass('wamo_auth.erstanmeldungen') is not null;""",
    "offene_liste": """select p.user_id::text || '|' || u.email
        from :"schema".profiles p join auth.users u on u.id = p.user_id
        where p.labor_art is null and wamo_auth.erstanmeldung_stand(p.user_id) in ('offen', 'abgelaufen')
        order by u.email;""",
    "geraete_widerrufen": """update :"schema".devices set status = 'widerrufen', gesperrt_grund = 'Austritt'
        where user_id = :'uid' and art = 'persoenlich' and status <> 'widerrufen' returning kennung;""",
    "geraete_offen_zaehlen": """select count(*) from :"schema".devices
        where user_id = :'uid' and art = 'persoenlich' and status <> 'widerrufen';""",
    "zugang_loeschen": """update :"schema".model_access set claude_schluessel = null, claude_code_token = null
        where user_id = :'uid' and (claude_schluessel is not null or claude_code_token is not null) returning user_id;""",
    "zugang_zaehlen": """select count(*) from :"schema".model_access
        where user_id = :'uid' and (claude_schluessel is not null or claude_code_token is not null);""",
    "liste_mit_stand": """select p.display_name || ' | ' || p.rolle::text || ' | ' || case when p.aktiv then 'aktiv' else 'gesperrt' end
        || ' | ' || u.email || ' | ' || coalesce(wamo_auth.erstanmeldung_stand(p.user_id), '-')
        || ' | ' || coalesce((select to_char(e.frist_bis at time zone 'Europe/Berlin', 'DD.MM.YYYY HH24:MI')
                               from wamo_auth.erstanmeldungen e where e.user_id = p.user_id), '-')
        || ' | ' || (select count(*) from auth.mfa_factors f where f.user_id = p.user_id and f.status = 'verified')::text
        || ' | ' || case when u.banned_until > now() then 'Konto gesperrt' else 'Konto frei' end
        from :"schema".profiles p join auth.users u on u.id = p.user_id order by p.display_name;""",
    "liste_ohne_stand": """select p.display_name || ' | ' || p.rolle::text || ' | ' || case when p.aktiv then 'aktiv' else 'gesperrt' end
        || ' | ' || u.email || ' | - | - | '
        || (select count(*) from auth.mfa_factors f where f.user_id = p.user_id and f.status = 'verified')::text
        || ' | ' || case when u.banned_until > now() then 'Konto gesperrt' else 'Konto frei' end
        from :"schema".profiles p join auth.users u on u.id = p.user_id order by p.display_name;""",
}


class Fehler(Exception):
    def __init__(self, text, schritt=None):
        super().__init__(text)
        self.schritt = schritt


@contextlib.contextmanager
def schritt(nummer, name, hinweis=""):
    """Fehler eines Schritts bekommen Nummer und Namen, dazu einen Satz über den Zustand des Kontos."""
    try:
        yield
    except Fehler as e:
        text = str(e).rstrip(". ")
        raise Fehler(f"Schritt {nummer} ({name}): {text}. {hinweis}".rstrip(), nummer) from None


# ---------- Zugang zu Datenbank und GoTrue ----------

def psql_ausfuehren(sql, **vars):
    cmd = ["docker", "exec", "-i", "wamo-supabase-db", "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-tA", "-q"]
    for k, v in vars.items():
        cmd += ["-v", f"{k}={v}"]
    try:
        r = subprocess.run(cmd, input=sql, capture_output=True, text=True)
    except OSError:
        raise Fehler("Datenbankfehler: docker ist nicht aufrufbar") from None
    if r.returncode != 0:
        raise Fehler("Datenbankfehler: " + r.stderr.strip()[:300])
    return r.stdout.strip()


def umgebung_lesen(pfad):
    env = {}
    with open(pfad, encoding="utf-8") as fh:
        for zeile in fh:
            if "=" in zeile and not zeile.lstrip().startswith("#"):
                k, v = zeile.rstrip("\n").split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _kennung(fehler):
    """Kurze Kennung aus dem Fehlerkörper von GoTrue (error_code), sonst unbekannt. Der Text selbst wird nie übernommen."""
    try:
        daten = json.loads(fehler.read().decode("utf-8"))
        kennung = daten.get("error_code") if isinstance(daten, dict) else None
    except (OSError, ValueError, AttributeError):
        kennung = None
    return kennung if isinstance(kennung, str) and KENNUNG_RE.fullmatch(kennung) else "unbekannt"


def gotrue_client(env_pfad=ENV_PFAD):
    """Liefert aufruf(methode, pfad, daten=None) für die Admin-Schnittstelle (nur Loopback, nie über einen Proxy aus der Umgebung).
    Fehler nennen nur Status und Kennung."""
    zustand = {}

    def aufruf(methode, pfad, daten=None):
        if "schluessel" not in zustand:
            try:
                zustand["schluessel"] = umgebung_lesen(env_pfad)["SERVICE_ROLE_KEY"]
            except (OSError, KeyError):
                raise Fehler("Der Service-Schlüssel ist nicht lesbar (SERVICE_ROLE_KEY in der .env des WAMO-Supabase)") from None
            # ProxyHandler({}): http_proxy und Verwandte aus der Umgebung gelten hier nie, der Schlüssel geht nur an Loopback
            zustand["opener"] = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        schluessel = zustand["schluessel"]
        req = urllib.request.Request(
            GOTRUE_URL + pfad,
            data=json.dumps(daten).encode("utf-8") if daten is not None else None,
            headers={"apikey": schluessel, "Authorization": "Bearer " + schluessel, "Content-Type": "application/json"},
            method=methode,
        )
        try:
            with zustand["opener"].open(req, timeout=15) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            raise Fehler(f"GoTrue {methode}: HTTP {e.code} {_kennung(e)}") from None
        except (urllib.error.URLError, OSError):
            raise Fehler(f"GoTrue {methode}: nicht erreichbar") from None
        if not body:
            return {}
        try:
            antwort = json.loads(body.decode("utf-8"))
        except ValueError:
            raise Fehler(f"GoTrue {methode}: Antwort nicht lesbar") from None
        return antwort if isinstance(antwort, dict) else {}

    return aufruf


# ---------- Bausteine ----------

def konto_finden(psql, email):
    uid = psql(SQL["konto_suchen"], email=email)
    if uid and not UUID_RE.fullmatch(uid):
        raise Fehler("Unerwartete Antwort der Datenbank bei der Kontosuche")
    return uid


def konto_pflicht(psql, email):
    uid = konto_finden(psql, email)
    if not uid:
        raise Fehler("Kein Konto mit dieser E-Mail")
    return uid


def labor_schemas_lesen(psql):
    """Schemas, deren Tabelle profiles die Spalte labor_art hat (nur dort kann es Laborprofile geben)."""
    schemas = [z.strip() for z in psql(SQL["labor_schemas"]).splitlines() if z.strip()]
    if any(not SCHEMA_RE.fullmatch(s) for s in schemas):
        raise Fehler("Unerwartete Antwort der Datenbank (Schemas mit Laborspalte)")
    return schemas


def labor_pruefen(psql, uid, schemas=None):
    """Konten gelten für alle Schemas: Hat das Konto in IRGENDEINEM Schema ein Laborprofil, fasst dieser Befehl es nie an."""
    for schema in (labor_schemas_lesen(psql) if schemas is None else schemas):
        if _zahl(psql(SQL["labor_zaehlen"], schema=schema, uid=uid), "Laborprofile") > 0:
            raise Fehler(f"Das Konto hat ein Laborprofil im Schema {schema}, dieser Befehl fasst Laborkonten nie an "
                         "(dafür gibt es scripts/wamo_labor.py)")


def profil_pruefen(psql, schema, uid):
    """Kein Laborprofil in irgendeinem Schema, das Profil im Schema vorhanden und kein Laborprofil. Gibt (aktiv, rolle) zurück."""
    labor_pruefen(psql, uid)
    antwort = psql(SQL["profil_lesen"], schema=schema, uid=uid)
    if not antwort:
        raise Fehler(f"Kein WAMO-Profil im Schema {schema}")
    art, stand, rolle = antwort.split("|")
    if art == "labor":
        raise Fehler("Das ist ein Laborprofil, dieser Befehl fasst Laborprofile nie an (dafür gibt es scripts/wamo_labor.py)")
    return stand == "aktiv", rolle


def konto_sperren(gotrue, uid):
    antwort = gotrue("PUT", f"/admin/users/{uid}", {"ban_duration": SPERRE_DAUER})
    if not antwort.get("banned_until"):
        raise Fehler("GoTrue meldet kein banned_until, die Sperre ist nicht bestätigt")


def konto_entsperren(gotrue, uid):
    antwort = gotrue("PUT", f"/admin/users/{uid}", {"ban_duration": "none"})
    if antwort.get("banned_until"):
        raise Fehler("GoTrue meldet noch banned_until, die Sperre ist nicht aufgehoben")


def _zahl(text, was):
    if not re.fullmatch(r"[0-9]+", text or ""):
        raise Fehler(f"Unerwartete Antwort der Datenbank ({was})")
    return int(text)


def sitzungen_beenden(psql, uid):
    """Sitzungen, Refresh-Tokens, einmalige Tokens (Magic Link, Wiederherstellung) und Flow-State des Kontos entfernen und nachzählen."""
    anzahl = _zahl(psql(SQL["sitzungen_loeschen"], uid=uid), "Sitzungen")
    rest = _zahl(psql(SQL["refresh_zaehlen"], uid=uid), "Refresh-Tokens")
    if rest != 0:
        raise Fehler(f"Es gibt noch {rest} gültige Refresh-Tokens")
    vorhanden = psql(SQL["einmalig_vorhanden"]).split("|")
    if len(vorhanden) != 2 or any(v not in ("true", "false") for v in vorhanden):
        raise Fehler("Unerwartete Antwort der Datenbank (einmalige Tokens)")
    for name, tabelle, da in (("ott_loeschen", "auth.one_time_tokens", vorhanden[0] == "true"),
                              ("flow_loeschen", "auth.flow_state", vorhanden[1] == "true")):
        if not da:
            continue
        zeilen = psql(SQL[name], uid=uid).splitlines()
        if len(zeilen) != 2:
            raise Fehler(f"Unerwartete Antwort der Datenbank ({tabelle})")
        uebrig = _zahl(zeilen[1].strip(), tabelle)
        if uebrig != 0:
            raise Fehler(f"In {tabelle} sind noch {uebrig} Zeilen des Kontos")
    return anzahl


def faktoren_behandeln(psql, gotrue, uid, loeschen):
    """Ohne Faktoren: nichts zu tun. Mit Faktoren: ohne loeschen Abbruch, sonst jeden löschen und danach 0 verlangen."""
    ids = [z.strip() for z in psql(SQL["faktoren_liste"], uid=uid).splitlines() if z.strip()]
    if any(not UUID_RE.fullmatch(i) for i in ids):
        raise Fehler("Unerwartete Kennung eines Faktors")
    if not ids:
        return 0
    if not loeschen:
        raise Fehler(FREMD_SATZ)
    for i in ids:
        gotrue("DELETE", f"/admin/users/{uid}/factors/{i}")
    rest = _zahl(psql(SQL["faktoren_zaehlen"], uid=uid), "Faktoren")
    if rest != 0:
        raise Fehler(f"Es sind noch {rest} Faktoren übrig")
    return len(ids)


def passwort_setzen(psql, gotrue, uid, passwort):
    """Setzt das Passwort und prüft, dass sich der Hash wirklich geändert hat (md5 des Werts von encrypted_password vor und nach)."""
    # Die Admin-Schnittstelle prüft die Länge nicht, deshalb hier noch einmal
    if len(passwort) < MIN_PASSWORD or len(passwort.encode("utf-8")) > MAX_PASSWORD:
        raise Fehler("Das Passwort hat nicht 12 bis 72 Bytes")
    vorher = psql(SQL["passwort_hash"], uid=uid)
    gotrue("PUT", f"/admin/users/{uid}", {"password": passwort})
    nachher = psql(SQL["passwort_hash"], uid=uid)
    if not nachher or nachher == vorher:
        raise Fehler("Der Passwort-Hash hat sich nicht geändert, das Passwort wurde nicht gesetzt")


def merker_schreiben(psql, uid, frist, durch, erledigt):
    frist_bis = psql(SQL["merker_anlegen"], uid=uid, frist=str(frist), durch=durch, erledigt="true" if erledigt else "false")
    if not frist_bis:
        raise Fehler("wamo_auth.erstanmeldung_anlegen lieferte keine Frist")
    return frist_bis


def profil_aktivieren(psql, schema, uid):
    if not psql(SQL["profil_aktivieren"], schema=schema, uid=uid):
        raise Fehler("Das Profil wurde nicht aktiviert")


def abriegeln(psql, gotrue, schema, uid):
    """Profil inaktiv, Konto in GoTrue gesperrt, Sitzungen weg (Schritte 1 bis 3). Gibt die Zahl der beendeten Sitzungen zurück."""
    with schritt(1, "Profil sperren"):
        if not psql(SQL["profil_deaktivieren"], schema=schema, uid=uid):
            raise Fehler("Das Profil wurde nicht gesperrt (kein Profil oder ein Laborprofil)")
    with schritt(2, "Sperre in GoTrue", STAND_PRUEFEN):
        konto_sperren(gotrue, uid)
    with schritt(3, "Sitzungen beenden", GESPERRT_BLEIBT):
        return sitzungen_beenden(psql, uid)


# ---------- Befehle ----------

def uebergabe(d, psql, gotrue):
    """freischalten, zuruecksetzen und passwort: feste Reihenfolge, nach einem Fehler wird nie entsperrt."""
    modus, schema, email = d["aktion"], d["schema"], d["email"]
    frist = d.get("frist", FRIST_STANDARD)
    loeschen = bool(d.get("faktoren_loeschen")) or modus == "zuruecksetzen"
    with schritt(0, "Konto und Profil prüfen", "Nichts geändert."):
        uid = konto_pflicht(psql, email)
        profil_pruefen(psql, schema, uid)
    print(f"Konto gefunden, kein Laborprofil, Profil im Schema {schema} vorhanden.")
    with schritt(1, "Sperre in GoTrue", STAND_PRUEFEN):
        konto_sperren(gotrue, uid)
    # Sofort ein vorläufiger Merker (Stand offen mit dem alten Hash): Alte Access-Tokens erreichen am Kern ab jetzt nur noch die
    # Erstanmeldung, nicht erst nach dem Passwortwechsel. Schritt 5 schreibt ihn mit dem neuen Hash neu.
    with schritt("1b", "Vorläufiger Merker", GESPERRT_BLEIBT):
        merker_schreiben(psql, uid, frist, modus, False)
    with schritt(2, "Sitzungen beenden", GESPERRT_BLEIBT):
        sitzungen = sitzungen_beenden(psql, uid)
    with schritt(3, "Zweite Faktoren", GESPERRT_BLEIBT):
        faktoren = faktoren_behandeln(psql, gotrue, uid, loeschen)
    with schritt(4, "Startpasswort setzen", GESPERRT_BLEIBT):
        passwort_setzen(psql, gotrue, uid, d["password"])
    with schritt(5, "Merker schreiben", GESPERRT_BLEIBT):
        frist_bis = merker_schreiben(psql, uid, frist, modus, modus == "passwort")
    with schritt(6, "Profil aktivieren", GESPERRT_BLEIBT):
        profil_aktivieren(psql, schema, uid)
    with schritt(7, "Sperre aufheben", STAND_PRUEFEN):
        konto_entsperren(gotrue, uid)
    wort = {"freischalten": "Freigeschaltet", "zuruecksetzen": "Zurückgesetzt", "passwort": "Passwort gesetzt und freigeschaltet"}[modus]
    print(f"{wort}: {email} im Schema {schema} (Sitzungen beendet: {sitzungen}, Faktoren gelöscht: {faktoren}).")
    print(f"Frist bis: {frist_bis} ({frist} Stunden).")
    if modus == "passwort":
        print("Hinweis: Die Person hat das Passwort selbst gesetzt, der Merker steht auf erledigt. Sie richtet jetzt den zweiten Faktor im Browser ein.")
    else:
        print("Hinweis: Das Startpasswort steht nur auf dem Willkommensblatt, die Person ändert es sofort bei der ersten Anmeldung.")


def aktion_anlegen(d, psql, gotrue):
    schema, email, name = d["schema"], d["email"], d["name"].strip()
    uid = konto_finden(psql, email)
    zufall = None
    if uid:
        labor_pruefen(psql, uid)
        print("Konto existiert bereits: Passwort und Sperre bleiben unverändert.")
    else:
        zufall = secrets.token_urlsafe(32)  # niemand kennt es, es wird nie ausgegeben
        hinweis = "Das Konto hat ein Zufallspasswort, das niemand kennt; freischalten sperrt es vor der Übergabe ohnehin zuerst."
        try:
            with schritt(1, "Konto anlegen"):
                antwort = gotrue("POST", "/admin/users", {"email": email, "password": zufall, "email_confirm": True})
                uid = str(antwort.get("id", ""))
                if not UUID_RE.fullmatch(uid):
                    raise Fehler("GoTrue lieferte keine Kennung des neuen Kontos")
            with schritt(2, "Sperre in GoTrue", hinweis):
                konto_sperren(gotrue, uid)
        except Fehler as e:
            raise Fehler(str(e).replace(zufall, "***"), e.schritt) from None
        print("Anmeldekonto angelegt und gesperrt (Zufallspasswort, niemandem bekannt).")
    with schritt(3, "Profil anlegen"):
        zustand = psql(SQL["profil_upsert"], schema=schema, uid=uid, name=name, rolle=d["rolle"], anrede=d["anrede"])
        if not zustand:
            raise Fehler("Das Profil ist ein Laborprofil, dieser Befehl fasst Laborprofile nie an")
    print(f"WAMO-Profil ({zustand}): {name} ({d['rolle']}) im Schema {schema}, user_id {uid}")
    if zustand == "aktiv":
        print("Das Profil war schon aktiv und bleibt es, anlegen ändert aktiv nie.")
    else:
        print(f"Nächster Schritt am Übergabetag: python scripts/wamo_nutzer.py freischalten --email {email} --schema {schema}")


def aktion_umbenennen(d, psql, gotrue):
    name = d["name"].strip()
    uid = konto_pflicht(psql, d["email"])
    profil_pruefen(psql, d["schema"], uid)
    if not psql(SQL["profil_umbenennen"], schema=d["schema"], uid=uid, name=name):
        raise Fehler("Der Anzeigename wurde nicht geändert")
    print(f"Anzeigename geändert: {name}.")


def aktion_sperren(d, psql, gotrue):
    schema = d["schema"]
    if d.get("offene") is True:
        _sperren_offene(schema, psql, gotrue)
        return
    uid = konto_pflicht(psql, d["email"])
    profil_pruefen(psql, schema, uid)
    sitzungen = abriegeln(psql, gotrue, schema, uid)
    print(f"Gesperrt: {d['email']} im Schema {schema}. Konto in GoTrue gesperrt, {sitzungen} Sitzungen beendet.")


def _sperren_offene(schema, psql, gotrue):
    """Sperrt jedes Konto einzeln. Ein Fehler bei einem Konto lässt die übrigen nicht ungesperrt: Fehler werden gesammelt, am Ende
    stehen die gescheiterten E-Mails im Fehlertext (Exit 1)."""
    if psql(SQL["stand_vorhanden"]) != "t":
        raise Fehler("--offene braucht wamo_auth.erstanmeldung_stand (P1a ist hier nicht eingerichtet)")
    zeilen = [z for z in psql(SQL["offene_liste"], schema=schema).splitlines() if z.strip()]
    if not zeilen:
        print(f"Keine offenen oder abgelaufenen Erstanmeldungen im Schema {schema}.")
        return
    schemas = labor_schemas_lesen(psql)
    gescheitert = []
    for zeile in zeilen:
        uid, _, email = zeile.partition("|")
        if not UUID_RE.fullmatch(uid):
            raise Fehler("Unerwartete Antwort der Datenbank (offene Erstanmeldungen)")
        try:
            if LABOR_EMAIL_RE.fullmatch(email):
                raise Fehler("Laborkonto (labor-NN@wamo.test), dafür gibt es scripts/wamo_labor.py")
            labor_pruefen(psql, uid, schemas)
            sitzungen = abriegeln(psql, gotrue, schema, uid)
        except Fehler as e:
            gescheitert.append(f"{email}: {e}")
            continue
        print(f"Gesperrt: {email} ({sitzungen} Sitzungen beendet).")
    if gescheitert:
        raise Fehler(f"{len(gescheitert)} von {len(zeilen)} Konten nicht gesperrt: " + " | ".join(gescheitert))
    print(f"{len(zeilen)} Konten wegen offener oder abgelaufener Erstanmeldung gesperrt.")


def aktion_austreten(d, psql, gotrue):
    schema, email = d["schema"], d["email"]
    with schritt(0, "Konto und Profil prüfen", "Nichts geändert."):
        uid = konto_pflicht(psql, email)
        profil_pruefen(psql, schema, uid)
    # Zuerst abriegeln (Schritte 1 bis 3), danach Faktoren, Geräte und Schlüssel. Das Profil ist vor dem Widerruf inaktiv: Der
    # Gerätewächter (Migration 0002) erlaubt das Widerrufen ohne Admin als Akteur nur bei einem inaktiven Besitzerprofil.
    sitzungen = abriegeln(psql, gotrue, schema, uid)
    with schritt(4, "Zweite Faktoren", GESPERRT_BLEIBT):
        faktoren = faktoren_behandeln(psql, gotrue, uid, True)
    with schritt(5, "Geräte widerrufen", GESPERRT_BLEIBT):
        geraete = [k for k in psql(SQL["geraete_widerrufen"], schema=schema, uid=uid).splitlines() if k.strip()]
        offen = _zahl(psql(SQL["geraete_offen_zaehlen"], schema=schema, uid=uid), "Geräte")
        if offen != 0:
            raise Fehler(f"Es sind noch {offen} Geräte nicht widerrufen")
    with schritt(6, "Schlüssel und Token löschen", GESPERRT_BLEIBT):
        entfernt = bool(psql(SQL["zugang_loeschen"], schema=schema, uid=uid))
        uebrig = _zahl(psql(SQL["zugang_zaehlen"], schema=schema, uid=uid), "Schlüssel")
        if uebrig != 0:
            raise Fehler("Claude-Schlüssel oder Token sind noch hinterlegt")
    print(f"Austritt abgeschlossen: {email} im Schema {schema}.")
    print(f"Konto in GoTrue gesperrt, Sitzungen beendet: {sitzungen}, Faktoren gelöscht: {faktoren}, Profil inaktiv.")
    print("Geräte widerrufen: " + (", ".join(geraete) if geraete else "keine offenen Geräte") + ".")
    print("Claude-Schlüssel und Claude-Code-Token: " + ("gelöscht." if entfernt else "waren nicht hinterlegt."))
    print("Profile in anderen Schemas bleiben unverändert, der Zugang ist wegen der Sperre in GoTrue überall zu.")


def aktion_liste(d, psql, gotrue):
    mit_stand = psql(SQL["stand_vorhanden"]) == "t"
    zeilen = psql(SQL["liste_mit_stand" if mit_stand else "liste_ohne_stand"], schema=d["schema"])
    if not zeilen:
        print("Keine Profile.")
        return
    print("Name | Rolle | Profil | E-Mail | Erstanmeldung | Frist bis | Faktoren | Konto")
    print(zeilen)


AKTIONEN = {
    "anlegen": aktion_anlegen, "freischalten": uebergabe, "zuruecksetzen": uebergabe, "passwort": uebergabe,
    "umbenennen": aktion_umbenennen, "sperren": aktion_sperren, "austreten": aktion_austreten, "liste": aktion_liste,
}
MIT_PASSWORT = ("freischalten", "zuruecksetzen", "passwort")


# ---------- Eingaben, Protokoll und Einstieg ----------

def _name_pruefen(name):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or not name.strip().isprintable():
        raise Fehler("Der Anzeigename muss 1 bis 60 druckbare Zeichen haben")


def eingabe_pruefen(d):
    aktion = d.get("aktion")
    if aktion not in AKTIONEN:
        raise Fehler("Unbekannte Aktion")
    schema = d.get("schema")
    if not isinstance(schema, str) or not SCHEMA_RE.fullmatch(schema):
        raise Fehler("Ungültiges Schema (wamo_dev, wamo_test oder wamo_prod)")
    if aktion == "liste" or (aktion == "sperren" and d.get("offene") is True):
        return
    email = d.get("email")
    if not isinstance(email, str) or not EMAIL_RE.fullmatch(email):
        raise Fehler("E-Mail-Adresse ungültig")
    if LABOR_EMAIL_RE.fullmatch(email):
        raise Fehler("Laborkonto (labor-NN@wamo.test): Dafür gibt es scripts/wamo_labor.py, dieser Befehl fasst es nie an")
    if aktion in ("anlegen", "umbenennen"):
        _name_pruefen(d.get("name"))
    if aktion == "anlegen" and (d.get("rolle") not in ("admin", "mitglied") or d.get("anrede") not in ("du", "sie")):
        raise Fehler("Rolle (admin, mitglied) oder Anrede (du, sie) ungültig")
    if aktion in MIT_PASSWORT:
        frist = d.get("frist", FRIST_STANDARD)
        if not isinstance(frist, int) or isinstance(frist, bool) or not 1 <= frist <= FRIST_MAX:
            raise Fehler("Die Frist muss 1 bis 168 Stunden betragen")
        passwort = d.get("password")
        if not isinstance(passwort, str) or len(passwort) < MIN_PASSWORD or len(passwort.encode("utf-8")) > MAX_PASSWORD:
            raise Fehler("Das Startpasswort fehlt oder hat nicht 12 bis 72 Bytes")
        if len(set(passwort)) < MIN_VERSCHIEDEN or passwort.lower() == email.split("@")[0].lower():
            raise Fehler("Das Passwort ist zu einfach (mindestens 6 verschiedene Zeichen, nie der Teil der E-Mail vor dem @)")


def _sauber(wert):
    """Nur harmlose Zeichen in die Protokollzeile (keine Umbrüche, kein Leerraum), sonst Fragezeichen."""
    if not isinstance(wert, str) or not wert:
        return "-"
    return re.sub(r"[^A-Za-z0-9@._+-]", "?", wert)[:80]


def protokollzeile(d, code, schritt_nr):
    """Eine Zeile je Auftrag: Aktion, Schema, E-Mail, Ergebnis (bei Fehler mit Schrittnummer). Nie ein Passwort, nie ein Fehlertext."""
    ergebnis = "ok" if code == 0 else "fehler" + ("" if schritt_nr is None else f" schritt={schritt_nr}")
    return (f"aktion={_sauber(d.get('aktion'))} schema={_sauber(d.get('schema'))} email={_sauber(d.get('email'))} "
            f"ergebnis={ergebnis}")


def protokoll_senden(zeile):
    """Schreibt die Zeile ins Journal von Sokrates-2 (journalctl -t wamo-nutzer). Fehler von logger werden ignoriert."""
    try:
        subprocess.run(["logger", "-t", "wamo-nutzer", zeile], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def verarbeite(d, psql, gotrue, protokoll=None):
    """Führt einen Auftrag aus und gibt den Exit-Code zurück. Fehlertexte enthalten nie das Passwort. protokoll(zeile) wird je Auftrag
    einmal aufgerufen, seine Fehler stören den Auftrag nie."""
    code, schritt_nr = 0, None
    try:
        eingabe_pruefen(d)
        AKTIONEN[d["aktion"]](d, psql, gotrue)
    except Fehler as e:
        text = str(e)
        geheim = d.get("password")
        if isinstance(geheim, str) and geheim:
            text = text.replace(geheim, "***")
        print("Fehler: " + text, file=sys.stderr)
        code, schritt_nr = 1, e.schritt
    if protokoll is not None:
        try:
            protokoll(protokollzeile(d, code, schritt_nr))
        except Exception:
            pass
    return code


def main():
    for strom in (sys.stdout, sys.stderr):
        try:
            strom.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    try:
        d = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except ValueError:
        sys.exit("Eingabe ungültig.")
    if not isinstance(d, dict):
        sys.exit("Eingabe ungültig.")
    try:
        code = verarbeite(d, psql_ausfuehren, gotrue_client(), protokoll_senden)
    except Exception as e:  # nur der Typ, nie der Text: er könnte Geheimnisse enthalten
        print("Unerwarteter Fehler: " + type(e).__name__, file=sys.stderr)
        protokoll_senden(protokollzeile(d, 1, None))
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()
'''


# ---------- Lokale Seite ----------

def remote_befehl() -> str:
    """Der Befehl für ssh: das Serverprogramm gepackt (zlib) und base64-kodiert. Ungepackt wäre die Befehlszeile gut 30000 Zeichen lang,
    Windows erlaubt 32767."""
    programm = base64.b64encode(zlib.compress(REMOTE.encode("utf-8"), 9)).decode("ascii")
    return f"python3 -c \"import base64,zlib;exec(zlib.decompress(base64.b64decode('{programm}')).decode('utf-8'))\""


def host_pruefen(host: str) -> str:
    """Nie ein Host, der mit einem Minus beginnt (ssh nähme ihn als Option, zum Beispiel -oProxyCommand=...)."""
    if not isinstance(host, str) or not HOST_RE.fullmatch(host):
        sys.exit("Ungültiger Host (erlaubt sind Buchstaben, Ziffern, Punkt, Unterstrich und Minus, nie ein Minus am Anfang).")
    return host


def run_remote(host: str, payload: dict) -> subprocess.CompletedProcess:
    host = host_pruefen(host)
    return subprocess.run(
        # "--" vor dem Host: ab hier gilt nichts mehr als Option. ensure_ascii (Standard): Umlaute in Namen reisen als \u-Folgen und
        # hängen nicht von der Sprache der Gegenseite ab. Das Passwort steht nur in der Eingabe (stdin), nie in der Befehlszeile.
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--", host, remote_befehl()],
        input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
    )


def passwort_pruefen(pw: str, email: str | None = None) -> None:
    if len(pw) < MIN_PASSWORD:
        sys.exit(f"Passwort zu kurz (mindestens {MIN_PASSWORD} Zeichen).")
    if len(pw.encode("utf-8")) > MAX_PASSWORD:
        sys.exit(f"Passwort zu lang (höchstens {MAX_PASSWORD} Bytes).")
    if len(set(pw)) < MIN_VERSCHIEDEN:
        sys.exit(f"Passwort zu einfach: mindestens {MIN_VERSCHIEDEN} verschiedene Zeichen.")
    if email and pw.lower() == email.split("@")[0].lower():
        sys.exit("Passwort darf nicht der Teil der E-Mail-Adresse vor dem @ sein.")


def ask_password(email: str | None = None, frage: str = "Neues Passwort") -> str:
    first = getpass.getpass(f"{frage} (mindestens {MIN_PASSWORD} Zeichen): ")
    passwort_pruefen(first, email)
    if getpass.getpass("Passwort wiederholen: ") != first:
        sys.exit("Passwörter stimmen nicht überein.")
    return first


def schema_typ(wert: str) -> str:
    if not SCHEMA_RE.fullmatch(wert):
        raise argparse.ArgumentTypeError("Schema muss wamo_dev, wamo_test oder wamo_prod sein.")
    return wert


def email_typ(wert: str) -> str:
    if not EMAIL_RE.fullmatch(wert):
        raise argparse.ArgumentTypeError("E-Mail-Adresse ungültig.")
    if LABOR_EMAIL_RE.fullmatch(wert):
        raise argparse.ArgumentTypeError("Laborkonto (labor-NN@wamo.test): Dafür gibt es scripts/wamo_labor.py.")
    return wert


def host_typ(wert: str) -> str:
    if not HOST_RE.fullmatch(wert):
        raise argparse.ArgumentTypeError("Ungültiger Host (kein Minus am Anfang, nur Buchstaben, Ziffern, Punkt, Unterstrich, Minus).")
    return wert


def name_typ(wert: str) -> str:
    name = wert.strip()
    if not 1 <= len(name) <= 60 or not name.isprintable():
        raise argparse.ArgumentTypeError("Der Anzeigename muss 1 bis 60 druckbare Zeichen haben.")
    return name


def frist_typ(wert: str) -> int:
    try:
        frist = int(wert)
    except ValueError:
        raise argparse.ArgumentTypeError("Die Frist ist eine ganze Zahl von Stunden.") from None
    if not 1 <= frist <= FRIST_MAX:
        raise argparse.ArgumentTypeError(f"Die Frist muss 1 bis {FRIST_MAX} Stunden betragen.")
    return frist


def parser_bauen() -> argparse.ArgumentParser:
    standard_host = os.environ.get("WAMO_SSH_HOST", "wamo-sokrates2")
    parser = argparse.ArgumentParser(prog="wamo_nutzer.py", description="WAMO-Nutzer verwalten (WAMO-Supabase auf Sokrates-2)")
    sub = parser.add_subparsers(dest="aktion", required=True)

    def befehl(name: str, hilfe: str, schema_pflicht: bool = True, email: bool = True) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=hilfe)
        if email:
            p.add_argument("--email", required=True, type=email_typ)
        if schema_pflicht:
            p.add_argument("--schema", required=True, type=schema_typ, help="wamo_dev, wamo_test oder wamo_prod (ausdrücklich, kein Standard)")
        else:
            p.add_argument("--schema", default="wamo_dev", type=schema_typ)
        p.add_argument("--host", default=standard_host, type=host_typ)
        return p

    anlegen = befehl("anlegen", "Konto anlegen (gesperrt) und inaktives WAMO-Profil anlegen oder aktualisieren")
    anlegen.add_argument("--name", required=True, type=name_typ, help="Anzeigename, so spricht W.A.I.S. die Person an (der volle Name)")
    anlegen.add_argument("--rolle", choices=["admin", "mitglied"], default="mitglied")
    anlegen.add_argument("--anrede", choices=["du", "sie"], default="du")

    freischalten = befehl("freischalten", "Übergabetag: Startpasswort setzen, Merker schreiben, Profil aktivieren, Sperre aufheben")
    freischalten.add_argument("--frist-stunden", dest="frist", type=frist_typ, default=FRIST_STANDARD)
    freischalten.add_argument("--faktoren-loeschen", action="store_true", help="vorhandene zweite Faktoren bewusst löschen")

    zuruecksetzen = befehl("zuruecksetzen", "Wie freischalten, Faktoren werden immer gelöscht (verlorenes Handy)")
    zuruecksetzen.add_argument("--frist-stunden", dest="frist", type=frist_typ, default=FRIST_STANDARD)

    passwort = befehl("passwort", "Option Ü: Die Person tippt ihr Passwort selbst, der Merker steht sofort auf erledigt")
    passwort.add_argument("--faktoren-loeschen", action="store_true", help="vorhandene zweite Faktoren bewusst löschen")

    umbenennen = befehl("umbenennen", "Anzeigename ändern (aktiv bleibt unberührt)")
    umbenennen.add_argument("--name", required=True, type=name_typ)

    sperren = befehl("sperren", "Profil, Konto in GoTrue und Sitzungen sperren", email=False)
    ziel = sperren.add_mutually_exclusive_group(required=True)
    ziel.add_argument("--email", type=email_typ)
    ziel.add_argument("--offene", action="store_true", help="alle Nicht-Laborprofile mit offener oder abgelaufener Erstanmeldung")

    befehl("austreten", "Sperren, Faktoren, Geräte, Claude-Schlüssel und Token entfernen")
    befehl("liste", "WAMO-Profile mit Stand der Erstanmeldung anzeigen", schema_pflicht=False, email=False)
    return parser


def nutzlast_bauen(args: argparse.Namespace) -> dict:
    aktion = args.aktion
    nutzlast: dict = {"aktion": aktion, "schema": args.schema}
    if aktion == "sperren" and args.offene:
        nutzlast["offene"] = True
    elif aktion != "liste":
        nutzlast["email"] = args.email
    if aktion in ("anlegen", "umbenennen"):
        nutzlast["name"] = args.name
    if aktion == "anlegen":
        nutzlast.update(rolle=args.rolle, anrede=args.anrede)
    if aktion in ("freischalten", "zuruecksetzen"):
        nutzlast["frist"] = args.frist
    if aktion in ("freischalten", "passwort"):
        nutzlast["faktoren_loeschen"] = args.faktoren_loeschen
    if aktion in ("freischalten", "zuruecksetzen", "passwort"):
        # Passwörter nur verdeckt aus einem Terminal, nie über eine Pipe und nie in einer Ausgabe (auch nicht in einer KI-Sitzung)
        if not sys.stdin.isatty():
            sys.exit(f"{aktion} braucht ein Terminal: Das Passwort wird verdeckt eingetippt, nie über eine Pipe gelesen.")
        frage = "Neues Passwort" if aktion == "passwort" else "Startpasswort für das Willkommensblatt"
        nutzlast["password"] = ask_password(args.email, frage)
    return nutzlast


def main(argv: list[str] | None = None, remote=None) -> None:
    remote = remote or run_remote
    args = parser_bauen().parse_args(argv)
    nutzlast = nutzlast_bauen(args)
    geheim = nutzlast.get("password")

    ergebnis = remote(args.host, nutzlast)
    ausgabe, fehler = ergebnis.stdout.strip(), ergebnis.stderr.strip()
    if geheim:  # Sicherheitsnetz: Die Gegenseite gibt es nie aus, hier wird es trotzdem nie weitergereicht
        ausgabe, fehler = ausgabe.replace(geheim, "***"), fehler.replace(geheim, "***")
    if ausgabe:
        print(ausgabe)
    if ergebnis.returncode != 0:
        sys.exit(fehler or "Fehler auf Sokrates-2.")
    if args.aktion in ("freischalten", "zuruecksetzen"):
        print(f"Das eingetippte Startpasswort gilt jetzt {args.frist} Stunden; es steht nur auf dem Willkommensblatt.")


if __name__ == "__main__":
    main()
