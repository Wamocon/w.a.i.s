#!/usr/bin/python3 -E -s
"""Laborkonten löschen und ihre Sitzungen widerrufen (Testlabor, Entscheidung Q11, Befund 11, Löschfrist E12: spätestens Fr 11.12.2026).

Nur Standardbibliothek, eine Datei. Läuft auf Sokrates-2 als Benutzer wamocon (ohne sudo), wie labor_tokentest.py. Der Ordner liegt wie
immer unter ~/wamo-infra (infra/sokrates2/README.md, Abschnitt 0, "Ablage der Skripte").

Aufrufe auf Sokrates-2 (vom PC aus mit ssh wamo-sokrates2 "<Aufruf>"):

    python3 -E -s ~/wamo-infra/wamo_labor_konten_loeschen.py                       # Trockenlauf: Liste, Zählung, Plan, es ändert sich nichts
    python3 -E -s ~/wamo-infra/wamo_labor_konten_loeschen.py --kennung labor-09    # Trockenlauf nur für ein Konto
    python3 -E -s ~/wamo-infra/wamo_labor_konten_loeschen.py --kennung labor-09 --ausfuehren --bestaetigung LABORKONTEN-LOESCHEN
    python3 -E -s ~/wamo-infra/wamo_labor_konten_loeschen.py --ausfuehren --bestaetigung LABORKONTEN-LOESCHEN

Empfohlene Reihenfolge: erst der Nachlauf (scripts/wamo_labor_nachlauf.py, Runbook Abschnitt 10), dann der Trockenlauf, dann ein Echtlauf mit
einem Reservekonto (--kennung labor-09), dann der Echtlauf für alle. Jeder Lauf ist wiederholbar: Was schon gelöscht ist, findet er nicht mehr.

Was ein Laborkonto ist (beides muss zutreffen, sonst fasst das Werkzeug das Konto nie an):
  1. Laborprofil: Das Konto hat in mindestens einem Schema (wamo_dev, wamo_test, wamo_prod, dort wo profiles die Spalte labor_art hat) ein Profil
     mit labor_art (platz oder schaufenster, Migration 0018, voice-core/labor.py ist_labor). In keinem Schema hat es ein Profil ohne labor_art,
     die Rolle ist überall mitglied und aktiv überall falsch (beides verlangt 0018 ohnehin).
  2. Adresse: Die Anmelde-Adresse endet auf @wamo.test und ist genau <Kennung>@wamo.test, also labor-01 bis labor-16 oder labor-schau (Kennung aus
     labor_art und labor_platz, so legt scripts/wamo_labor.py anlegen die Konten an).
Ein Konto mit @wamo.test ohne Laborprofil, ein Laborprofil mit anderer Adresse und jedes Admin- oder Mitgliedskonto bleiben unberührt. Sie stehen
im Trockenlauf unter "Nicht angefasst" mit Grund. Höchstgrenze: Gibt es mehr als 12 Konten mit Laborprofil, bricht das Werkzeug vor jeder
Änderung ab (auch im Trockenlauf).

Echtlauf (nur mit --ausfuehren --bestaetigung LABORKONTEN-LOESCHEN, sonst Exit 2 ohne jeden Zugriff):
  0. Dienstschlüssel lesen, Konten suchen und prüfen wie im Trockenlauf.
  1. Alle Ziel-Profile sperren (labor_aktiv = false), falls noch freigeschaltet. Wurde ein Ziel-Profil vor weniger als 185 Sekunden geändert
     (profiles.updated_at, auch durch einen abgebrochenen Lauf oder wamo_labor.py sperren), wartet das Werkzeug den Rest ab: Der Kern kennt ein
     Profil bis zu 2 Minuten aus dem Zwischenspeicher (wie die Sperrfrist von labor_loeschen in 0018). Danach sucht und prüft es die Konten neu,
     gelöscht wird nur, was vorher und jetzt Ziel ist.
  Dann je Konto, ein Fehler stoppt nur dieses Konto, die übrigen laufen weiter:
  2. Vorprüfung, vor jeder Änderung am Konto: Zählung vorher vollständig lesbar, keine laufende Sitzung im Kern (sessions ohne ended_at, jünger
     als 135 Minuten), kein Verweis mit Löschsperre (restrict oder no action mit Zeilen), kein Verweis, den das Löschen nur auf null setzen würde
     (set null oder set default mit Zeilen: die Zeile bliebe ohne Besitzer stehen, erst der Nachlauf mit labor_loeschen räumt sie), Profile
     unverändert seit der Suche, GoTrue nennt dieselbe Adresse (GET /auth/v1/admin/users/<id>).
  3. Konto in GoTrue sperren (PUT /auth/v1/admin/users/<id> mit ban_duration 876000h, banned_until muss in der Antwort stehen): keine neue
     Anmeldung und kein Refresh mehr bis zum Löschen.
  4. Sitzungen widerrufen: delete from auth.sessions where user_id, dazu übrige auth.refresh_tokens des Kontos. Das ist genau das, was GoTrue
     bei POST /logout?scope=global tut (models.Logout). Einen Admin-Endpunkt, der die Sitzungen eines fremden Kontos beendet, hat GoTrue v2.196.0
     nicht (die Admin-Pfade sind users, factors, generate_link, audit, sso, oauth und custom-providers). Danach muss die Zählung 0 sein.
  5. Einträge des Kontos im Anmeldeprotokoll löschen (auth.audit_log_entries, payload actor_id oder traits.user_id). Sie haben keinen
     Fremdschlüssel und blieben sonst stehen (voice-core/labor_loeschliste.py, AUSSERHALB).
  6. Konto hart löschen: DELETE /auth/v1/admin/users/<id> mit should_soft_delete false. Die Datenbank löscht per Fremdschlüssel das
     WAMO-Profil und alle Zeilen mit einem Verweis auf das Konto (on delete cascade), auch solche, in denen es nur Empfänger ist (zum Beispiel
     teilungen und hinweise; Laborprofile teilen nicht, der Nachlauf hat diese Zeilen schon geleert).
  7. Nachprüfung: GoTrue meldet user_not_found, die Zählung danach ist in jeder Tabelle 0. GoTrue schreibt beim Löschen selbst einen Eintrag
     user_deleted ins Anmeldeprotokoll (Kennung und Adresse des Laborkontos, keine Daten von Besuchern). Er bleibt als Nachweis der Löschung
     und zählt nicht mit.
  8. Nachweis: Zahl der verbliebenen Laborkonten (soll 0 sein), Konten mit einer Laboradresse ohne Laborprofil (nur Hinweis, nicht angefasst),
     Datum. Ins Journal (logger -t wamo-labor-loeschen, ohne Adressen) gehen eine Zeile vor der ersten Änderung und eine mit dem Ergebnis
     (oder dem Abbruch), ansehen mit journalctl -t wamo-labor-loeschen.

Zählung: Das Werkzeug liest die Fremdschlüssel aus dem Katalog (alle Verweise auf auth.users und auf profiles der WAMO-Schemas) und zählt je
Tabelle und Spalte die Zeilen dieses Kontos, dazu auth.refresh_tokens (ohne Fremdschlüssel auf das Konto) und das Anmeldeprotokoll. Es liest nur
Zahlen, nie Inhalte. Als "nicht lesbar" gilt eine Tabelle ohne Leserecht für postgres, eine mit Zeilenregel (RLS), die postgres nicht umgeht
(dann wäre eine 0 wertlos), und ein Verweis über mehrere Spalten oder auf eine andere Spalte als id bzw. user_id. Dann löscht das Werkzeug das
Konto nicht (fail closed). Ebenso bricht es ab, wenn eine Profiltabelle für postgres nicht vollständig lesbar ist. Jede lesende Anweisung läuft
in einer Transaktion nur zum Lesen (default_transaction_read_only), der Trockenlauf kann darum nichts ändern.

Zugänge: Datenbank als Betriebsrolle postgres im Container wamo-supabase-db (docker exec ... psql, wie scripts/wamo_nutzer.py), Werte nur als
psql-Variablen. GoTrue über Loopback (http://localhost:55321, nur Loopback erlaubt, kein Proxy aus der Umgebung, keine Umleitung).

Geheimnisse: Der Dienstschlüssel (SERVICE_ROLE_KEY) kommt nur aus der env-Datei am Server (/home/wamocon/supabase-wamo/.env, wie
labor_tokentest.py), nur im Echtlauf, und steht nur im Kopf der Anfragen an Loopback. Er steht nie in einer Befehlszeile, nie in der Ausgabe und nie
in einem Fehlertext: Fehler von GoTrue erscheinen nur als HTTP-Status und kurze Kennung, Fehler der Datenbank nur mit der ersten Zeile (Adressen
maskiert). Der Trockenlauf liest den Schlüssel nicht. Adressen erscheinen in der Ausgabe nur maskiert (l***1@wamo.test), im Journal gar nicht.

Grenzen, ehrlich: (1) Ob postgres die Tabellen im Schema auth lesen und in auth.sessions, auth.refresh_tokens und auth.audit_log_entries löschen darf
und RLS dort umgeht, zeigt erst der Lauf am Server (wamo_nutzer.py sperren nutzt denselben Weg für auth.sessions). (2) Ein schon ausgegebenes
Zugriffstoken bleibt bis zu seinem Ablauf formal gültig. GoTrue lehnt es nach dem Löschen der Sitzung ab, der Kern ohne Profil ebenso; PostgREST
prüft nur die Signatur (die Rolle authenticated hat auf WAMO-Tabellen keine Rechte, gemessen mit labor_tokentest.py). (3) Ob das Löschen mit allen
Kaskaden durchgeht (Prüfungen auf den Tabellen, die per set null mitgeändert werden), zeigt erst GoTrue: Scheitert es, antwortet GoTrue mit HTTP 500,
die Transaktion bleibt aus und das Konto gesperrt und ohne Sitzungen; darum zuerst ein Konto mit --kennung. (4) Sicherungen, Snapshots und
Journal-Rotation des Servers fasst das Werkzeug nicht an (Runbook Abschnitt 10, Punkt 7). (5) Ein Aufruf der Datenbank hat 120 Sekunden Zeit. Läuft
die Zeit ab, endet nur docker exec, psql im Container kann den Schritt noch abschließen; der Lauf meldet dann einen Fehler und ist wiederholbar.

Ausgänge: 0 Trockenlauf gelungen, oder Echtlauf ohne Fehler und Nachweis erbracht (ohne --kennung: 0 verbliebene Laborkonten; mit --kennung: keines
der gewählten mehr da). 1 mindestens ein Konto mit Fehler, offene Nachprüfung, Nachweis nicht erbracht oder Datenbank nicht erreichbar. 2 Aufruf
oder Einstellung falsch, Höchstgrenze überschritten oder Bestätigungswort fehlt: Es wurde nichts geändert. 130 Abbruch mit Strg+C, SIGHUP (die
ssh-Verbindung fällt weg) oder SIGTERM, der Lauf ist wiederholbar.

Tests: infra/sokrates2/test_wamo_labor_konten_loeschen.py (Attrappen für GoTrue und die Datenbank, kein Server).

Einzeldatei: Die Datei hat bewusst über 800 Zeilen und bleibt eine Einzeldatei, weil sie als `python3 -E -s` allein am Server läuft (einzeln
kopiert wie labor_tokentest.py, ohne Modulpfad und ohne Zusatzpakete).
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import ipaddress
import json
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

BASIS = "http://localhost:55321"
ENV_DATEI = "/home/wamocon/supabase-wamo/.env"
DB_CONTAINER = "wamo-supabase-db"
DOMAIN = "wamo.test"
BESTAETIGUNG = "LABORKONTEN-LOESCHEN"
MAX_KONTEN = 12
SPERRE_DAUER = "876000h"
SPERRFRIST_S = 185
JOURNAL_MARKE = "wamo-labor-loeschen"
EXIT_OK, EXIT_FEHLER, EXIT_EINGABE, EXIT_ABBRUCH = 0, 1, 2, 130
ANTWORT_GRENZE = 1_000_000
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SCHEMA_RE = re.compile(r"wamo_(dev|test|prod)")
KENNUNG_RE = re.compile(r"labor-(0[1-9]|1[0-6]|schau)")
KURZKENNUNG_RE = re.compile(r"[A-Za-z0-9_]{1,40}")
MAIL_RE = re.compile(r"[^\s@<>()\"'|,;:]+@[^\s@<>()\"'|,;:]+")
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")
GEHEIM_NAME_RE = re.compile(r"KEY|SECRET|PASSWORD|TOKEN|PASS", re.IGNORECASE)
LOESCHARTEN = {"c": "cascade", "n": "set null", "d": "set default", "r": "restrict", "a": "no action", "-": "ohne Fremdschlüssel"}
SPERRENDE_ARTEN = frozenset({"r", "a"})  # restrict, no action: das Löschen scheitert
NULLENDE_ARTEN = frozenset({"n", "d"})  # set null, set default: die Zeile bliebe ohne Besitzer stehen
REFRESH, PROTOKOLL = "auth.refresh_tokens", "auth.audit_log_entries"
SCHRITTE = {2: "Vorprüfung", 3: "Konto sperren", 4: "Sitzungen widerrufen", 5: "Anmeldeprotokoll", 6: "Konto löschen"}
GEHEIMNISSE: list[str] = []

# Alle Anweisungen an einer Stelle. Werte gehen nur als psql-Variablen hinein (:'uid' als Literal, :"schema" als Bezeichner), geprüft vorher
# (UUID, Schema aus fester Liste). Lesende Anweisungen liefern JSON, jede läuft in einer Transaktion nur zum Lesen (Datenbank.sql).
_ZIEL_TABELLEN = """select x.oid from pg_class x join pg_namespace y on y.oid = x.relnamespace
                     where (y.nspname = 'auth' and x.relname = 'users')
                        or (y.nspname in ('wamo_dev', 'wamo_test', 'wamo_prod') and x.relname = 'profiles')"""


def _voll_lesbar(t: str) -> str:
    """SQL: Liest postgres die Tabelle (Alias t aus pg_class) vollständig? Leserecht und keine Zeilenregel, die Zeilen ausblendet. RLS greift nicht
    für Superuser, für Rollen mit bypassrls und für den Besitzer, solange force row level security aus ist. Sonst wäre eine Zählung von 0 wertlos."""
    return (f"(has_table_privilege({t}.oid, 'select') and (not {t}.relrowsecurity"
            " or (select r.rolsuper or r.rolbypassrls from pg_roles r where r.rolname = current_user)"
            f" or (pg_has_role({t}.relowner, 'USAGE') and not {t}.relforcerowsecurity)))")


SQL: dict[str, str] = {
    # Aus dem Katalog statt aus information_schema (das blendet Tabellen ohne Recht aus). unlesbar: Profiltabellen, die postgres nicht
    # vollständig liest; dann bricht das Werkzeug ab, denn ein Profil dort bliebe unsichtbar.
    "schemas": f"""select json_build_object(
  'profile', coalesce(json_agg(n.nspname::text order by n.nspname), '[]'::json),
  'labor', coalesce(json_agg(n.nspname::text order by n.nspname) filter (where exists (select 1 from pg_attribute a
             where a.attrelid = t.oid and a.attname = 'labor_art' and not a.attisdropped)), '[]'::json),
  'unlesbar', coalesce(json_agg(n.nspname::text order by n.nspname) filter (where not {_voll_lesbar('t')}), '[]'::json))
from pg_class t join pg_namespace n on n.oid = t.relnamespace
where t.relname = 'profiles' and t.relkind in ('r', 'p') and n.nspname in ('wamo_dev', 'wamo_test', 'wamo_prod');""",
    "laborprofile": """select coalesce(json_agg(json_build_object('uid', p.user_id, 'art', p.labor_art, 'platz', p.labor_platz,
    'labor_aktiv', p.labor_aktiv, 'rolle', p.rolle::text, 'aktiv', p.aktiv) order by p.user_id), '[]'::json)
  from :"schema".profiles p where p.labor_art is not null;""",
    "andere_profile": """select coalesce(json_agg(p.user_id order by p.user_id), '[]'::json)
  from :"schema".profiles p where p.labor_art is null and p.user_id = any(:'uids'::uuid[]);""",
    "profile_ohne_laborspalte": """select coalesce(json_agg(p.user_id order by p.user_id), '[]'::json)
  from :"schema".profiles p where p.user_id = any(:'uids'::uuid[]);""",
    "konten": """select coalesce(json_agg(json_build_object('uid', u.id, 'email', u.email,
    'letzte', to_char(u.last_sign_in_at at time zone 'Europe/Berlin', 'DD.MM.YYYY HH24:MI'),
    'gesperrt', coalesce(u.banned_until > now(), false)) order by u.id), '[]'::json)
  from auth.users u where u.id = any(:'uids'::uuid[]);""",
    "muster_konten": r"""select coalesce(json_agg(u.id order by u.id), '[]'::json) from auth.users u
  where lower(u.email) ~ '^labor-(0[1-9]|1[0-6]|schau)@wamo\.test$';""",
    "kernsitzungen": """select count(*) from :"schema".sessions s
  where s.user_id = :'uid'::uuid and s.ended_at is null and s.started_at > clock_timestamp() - interval '135 minutes';""",
    # Sekunden, bis die Sperrfrist des jüngst geänderten Ziel-Profils abgelaufen ist (profiles.updated_at, wie labor_loeschen in 0018). Gilt
    # auch, wenn ein abgebrochener Lauf oder wamo_labor.py sperren das Profil gerade erst gesperrt hat.
    "sperrfrist": f"""select coalesce(max(ceil(extract(epoch from (p.updated_at + interval '{SPERRFRIST_S} seconds' - clock_timestamp())))), 0)::int
  from :"schema".profiles p where p.user_id = any(:'uids'::uuid[]) and p.labor_art is not null
   and p.updated_at > clock_timestamp() - interval '{SPERRFRIST_S} seconds';""",
    # Je Verweis eine Zeile JSON (die Zählanweisungen entstehen aus dem Katalog und laufen mit \gexec), dazu auth.refresh_tokens und das
    # Anmeldeprotokoll (Art "-", ohne Fremdschlüssel), zuletzt eine Zeile mit konto. n = null heißt: nicht vollständig lesbar oder nicht
    # prüfbar (Verweis über mehrere Spalten oder auf eine andere Spalte als id bzw. user_id).
    "zaehlen": f"""with ziel(nspname, relname, spalte, art, pruefbar, bedingung) as (
  select n.nspname::text, t.relname::text, a.attname::text, c.confdeltype::text,
         cardinality(c.conkey) = 1 and ra.attname in ('id', 'user_id'), format('%I = %L', a.attname, :'uid')
    from pg_constraint c
    join pg_class t on t.oid = c.conrelid
    join pg_namespace n on n.oid = t.relnamespace
    join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
    join pg_attribute ra on ra.attrelid = c.confrelid and ra.attnum = c.confkey[1]
   where c.contype = 'f' and c.confrelid in ({_ZIEL_TABELLEN})
  union all
  values ('auth', 'refresh_tokens', 'user_id', '-', true, format('user_id = %L', :'uid')),
         ('auth', 'audit_log_entries', 'payload', '-', true,
          format('(payload->>''actor_id'' = %1$L or payload->''traits''->>''user_id'' = %1$L) and coalesce(payload->>''action'', '''') <> ''user_deleted''',
                 :'uid')))
select format('select json_build_object(''tabelle'', %L, ''spalte'', %L, ''art'', %L, ''n'', %s);',
         z.nspname || '.' || z.relname, z.spalte, z.art,
         case when z.pruefbar and {_voll_lesbar('t')} then format('(select count(*) from %I.%I where %s)', z.nspname, z.relname, z.bedingung)
              else 'null' end)
  from ziel z
  join pg_namespace n on n.nspname = z.nspname
  join pg_class t on t.relnamespace = n.oid and t.relname = z.relname
 order by z.nspname, z.relname, z.spalte, z.art
\\gexec
select json_build_object('konto', (select count(*) from auth.users u where u.id = :'uid'::uuid));""",
    "profil_sperren": """with x as (update :"schema".profiles set labor_aktiv = false
    where user_id = :'uid'::uuid and labor_art is not null and labor_aktiv returning 1)
select count(*) from x;""",
    # drei Zeilen: gelöschte Sitzungen, gelöschte übrige Refresh-Tokens, Rest (muss 0 sein)
    "sitzungen_widerrufen": """with s as (delete from auth.sessions where user_id = :'uid'::uuid returning 1)
select count(*) from s;
with r as (delete from auth.refresh_tokens where user_id = :'uid' returning 1)
select count(*) from r;
select (select count(*) from auth.sessions where user_id = :'uid'::uuid) + (select count(*) from auth.refresh_tokens where user_id = :'uid');""",
    "protokoll_loeschen": """with d as (delete from auth.audit_log_entries e
    where e.payload->>'actor_id' = :'uid' or e.payload->'traits'->>'user_id' = :'uid' returning 1)
select count(*) from d;""",
}
SCHREIBEND = frozenset({"profil_sperren", "sitzungen_widerrufen", "protokoll_loeschen"})


# ---------------------------------------------------------------------------------------------------------------------------------
# Ausgabe ohne Geheimnisse
# ---------------------------------------------------------------------------------------------------------------------------------

def merke(wert: object) -> None:
    """Merkt einen Wert, der nie in der Ausgabe stehen darf. Zu kurze Werte würden nur Text zerstören."""
    if isinstance(wert, str) and len(wert) >= 8 and wert not in GEHEIMNISSE:
        GEHEIMNISSE.append(wert)


def bereinigen(text: str) -> str:
    for g in sorted(GEHEIMNISSE, key=len, reverse=True):
        text = text.replace(g, "***")
    return JWT_RE.sub("***", text)


def ausgabe(text: str = "") -> None:
    text = bereinigen(text)
    try:
        try:
            print(text, flush=True)
        except UnicodeEncodeError:
            print(text.encode("ascii", "replace").decode("ascii"), flush=True)
    except (OSError, ValueError):
        pass  # die Ausgabe ist weg (Pipe geschlossen): der Lauf geht weiter, das Löschen hängt nie an ihr


def maskiert(email: str) -> str:
    """l***1@wamo.test: erster und letzter Buchstabe vor dem @, die Domäne bleibt (sie sagt, warum ein Konto nicht angefasst wird)."""
    lokal, at, domain = (email or "").rpartition("@")
    if not at or not lokal:
        return "***"
    return f"{lokal[0]}***{lokal[-1] if len(lokal) > 1 else ''}@{domain}"


def journal_schreiben(zeile: str) -> None:
    """Eine Zeile ins Journal von Sokrates-2 (journalctl -t wamo-labor-loeschen). Fehler von logger werden ignoriert."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(["logger", "-t", JOURNAL_MARKE, "--", MAIL_RE.sub("***", bereinigen(zeile))], capture_output=True, timeout=5)


class Fehler(Exception):
    """Ablauffehler mit kurzem Text ohne Geheimnisse."""


class Eingabefehler(Exception):
    """Aufruf, Einstellung oder Höchstgrenze: Es wurde nichts geändert (Exit 2)."""


# ---------------------------------------------------------------------------------------------------------------------------------
# Zugänge: Dienstschlüssel, GoTrue, Datenbank
# ---------------------------------------------------------------------------------------------------------------------------------

def _ist_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def basis_pruefen(basis: str) -> str:
    """Der Dienstschlüssel verlässt den Server nie: nur http an Loopback, ohne Zugangsdaten, Pfad und Abfrage."""
    try:
        u = urllib.parse.urlsplit(basis)
        host = u.hostname
        _ = u.port  # prüft den Port (ValueError außerhalb 0 bis 65535)
    except ValueError:
        raise Eingabefehler("--basis ist keine gültige Adresse") from None
    if u.scheme != "http" or not host or not _ist_loopback(host):
        raise Eingabefehler("--basis muss eine http-Adresse auf diesem Rechner sein (Loopback), der Dienstschlüssel verlässt den Server nie")
    if u.username is not None or u.password is not None or u.path not in ("", "/") or u.query or u.fragment:
        raise Eingabefehler("--basis darf nur Schema, Rechner und Port enthalten")
    return basis.rstrip("/")


def dienstschluessel_lesen(datei: str) -> str:
    """SERVICE_ROLE_KEY aus der env-Datei am Server. Alle Werte mit geheimem Namen werden gemerkt und nie ausgegeben."""
    try:
        with open(datei, encoding="utf-8") as f:
            zeilen = f.read().splitlines()
    except (OSError, UnicodeDecodeError):
        raise Eingabefehler(f"Umgebungsdatei {datei} nicht lesbar") from None
    werte: dict[str, str] = {}
    for z in zeilen:
        if "=" in z and not z.lstrip().startswith("#"):
            k, v = z.split("=", 1)
            werte[k.strip()] = v.strip().strip('"').strip("'")
    for k, v in werte.items():
        if GEHEIM_NAME_RE.search(k):
            merke(v)
    schluessel = werte.get("SERVICE_ROLE_KEY", "")
    if not schluessel:
        raise Eingabefehler(f"Umgebungsdatei {datei}: SERVICE_ROLE_KEY fehlt")
    merke(schluessel)
    return schluessel


@dataclass(frozen=True)
class Antwort:
    status: int
    roh: bytes = b""

    def als_json(self) -> object:
        try:
            return json.loads(self.roh) if self.roh else None
        except ValueError:
            return None


def kennung(a: Antwort) -> str:
    """Kurze Fehlerkennung aus der Antwort (nur kurze Bezeichner, nie Sätze, nie Inhalte)."""
    d = a.als_json()
    if not isinstance(d, dict):
        return ""
    for schluessel in ("error_code", "code", "error"):
        w = d.get(schluessel)
        if isinstance(w, str) and KURZKENNUNG_RE.fullmatch(w):
            return w
    return ""


def kurz(a: Antwort) -> str:
    if a.status == 0:
        return "nicht erreichbar"
    k = kennung(a)
    return f"HTTP {a.status}" + (f" {k}" if k else "")


class _OhneUmleitung(urllib.request.HTTPRedirectHandler):
    """Folgt keiner Umleitung: Ein Aufruf mit dem Dienstschlüssel darf den Server nie verlassen."""

    def redirect_request(self, *args, **kwargs):
        return None


class GoTrue:
    """Admin-Schnittstelle von GoTrue über Loopback. Der Schlüssel steht nur im Kopf der Anfrage."""

    def __init__(self, basis: str, schluessel: str):
        self.basis = basis
        self._schluessel = schluessel
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _OhneUmleitung())

    def anfrage(self, methode: str, pfad: str, daten: dict | None = None) -> Antwort:
        kopf = {"apikey": self._schluessel, "Authorization": "Bearer " + self._schluessel}
        if daten is not None:
            kopf["Content-Type"] = "application/json"
        req = urllib.request.Request(self.basis + pfad, data=None if daten is None else json.dumps(daten).encode(), method=methode,
                                     headers=kopf)
        try:
            with self._opener.open(req, timeout=20) as r:
                return Antwort(r.status, r.read(ANTWORT_GRENZE))
        except urllib.error.HTTPError as e:
            try:
                return Antwort(e.code, e.read(ANTWORT_GRENZE))
            except (OSError, http.client.HTTPException):
                return Antwort(e.code)
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError):
            return Antwort(0)

    @staticmethod
    def _pfad(uid: str) -> str:
        return "/auth/v1/admin/users/" + urllib.parse.quote(uid, safe="")

    def konto_lesen(self, uid: str) -> Antwort:
        return self.anfrage("GET", self._pfad(uid))

    def sperren(self, uid: str) -> Antwort:
        return self.anfrage("PUT", self._pfad(uid), {"ban_duration": SPERRE_DAUER})

    def loeschen(self, uid: str) -> Antwort:
        return self.anfrage("DELETE", self._pfad(uid), {"should_soft_delete": False})


def db_fehlertext(stderr: str) -> str:
    """Erste Zeile der Fehlermeldung, Adressen maskiert, gekürzt. Die Anweisungen enthalten keine Geheimnisse, die Werte sind Kennungen."""
    zeile = next((z.strip() for z in (stderr or "").splitlines() if z.strip()), "ohne Meldung")
    return MAIL_RE.sub("***", zeile)[:160]


class Datenbank:
    """psql als Betriebsrolle postgres im Container des WAMO-Supabase (docker exec, wie scripts/wamo_nutzer.py)."""

    def __init__(self, container: str = DB_CONTAINER):
        self.container = container

    def sql(self, name: str, **werte: str) -> str:
        # Jede Anweisung außer den drei schreibenden läuft in einer Transaktion nur zum Lesen: Der Trockenlauf kann nichts ändern, auch nicht
        # aus Versehen.
        nur_lesen = [] if name in SCHREIBEND else ["-e", "PGOPTIONS=-c default_transaction_read_only=on"]
        befehl = ["docker", "exec", "-i", *nur_lesen, self.container, "psql", "-X", "-U", "postgres", "-v", "ON_ERROR_STOP=1",
                  "--single-transaction", "-tA", "-q"]
        for k, v in werte.items():
            befehl += ["-v", f"{k}={v}"]
        try:
            r = subprocess.run(befehl, input=SQL[name], capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            raise Fehler("Datenbank nicht erreichbar (docker exec)") from None
        if r.returncode != 0:
            raise Fehler("Datenbankfehler: " + db_fehlertext(r.stderr))
        return r.stdout.strip()


def json_lesen(text: str, typ: type) -> object:
    try:
        d = json.loads(text)
    except ValueError:
        raise Fehler("Unerwartete Antwort der Datenbank") from None
    if not isinstance(d, typ):
        raise Fehler("Unerwartete Antwort der Datenbank")
    return d


def zahl(text: str) -> int:
    if not re.fullmatch(r"[0-9]+", (text or "").strip()):
        raise Fehler("Unerwartete Antwort der Datenbank (Zahl)")
    return int(text.strip())


def uid_pruefen(wert: object) -> str:
    if not isinstance(wert, str) or not UUID_RE.fullmatch(wert):
        raise Fehler("Unerwartete Kennung eines Kontos in der Antwort der Datenbank")
    return wert


def uid_liste(uids: list[str]) -> str:
    return "{" + ",".join(uid_pruefen(u) for u in uids) + "}"


# ---------------------------------------------------------------------------------------------------------------------------------
# Bestand: Laborprofile, Konten, Prüfung
# ---------------------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Laborprofil:
    schema: str
    art: str
    platz: int | None
    labor_aktiv: bool
    rolle: str
    aktiv: bool

    @property
    def kennung(self) -> str:
        if self.art == "schaufenster" and self.platz is None:
            return "labor-schau"
        if self.art == "platz" and isinstance(self.platz, int) and 1 <= self.platz <= 16:
            return f"labor-{self.platz:02d}"
        return "labor-unklar"

    def text(self) -> str:
        wo = f"platz {self.platz}" if self.art == "platz" else self.art
        return f"{self.schema} {wo} {'freigeschaltet' if self.labor_aktiv else 'gesperrt'}"


@dataclass
class Konto:
    uid: str
    profile: list[Laborprofil]
    email: str = ""
    letzte: str | None = None
    gesperrt: bool = False
    andere: list[str] = field(default_factory=list)
    grund: str = ""

    @property
    def kennung(self) -> str:
        kennungen = sorted({p.kennung for p in self.profile})
        return kennungen[0] if len(kennungen) == 1 else "/".join(kennungen)


@dataclass
class Bestand:
    ziele: list[Konto]
    ausgeschlossen: list[Konto]
    nicht_gewaehlt: list[Konto]
    fehlend: list[str]
    laborkonten: int
    muster_ohne_profil: int
    profil_schemas: list[str]
    labor_schemas: list[str]

    def alle(self) -> list[Konto]:
        return self.ziele + self.ausgeschlossen + self.nicht_gewaehlt


def _schemas(wert: object) -> list[str]:
    if not isinstance(wert, list) or any(not isinstance(s, str) or not SCHEMA_RE.fullmatch(s) for s in wert):
        raise Fehler("Unerwartete Antwort der Datenbank (Schemas)")
    return list(wert)


def _laborprofil(schema: str, z: object) -> tuple[str, Laborprofil]:
    if not isinstance(z, dict) or not isinstance(z.get("art"), str):
        raise Fehler("Unerwartete Antwort der Datenbank (Laborprofil)")
    platz = z.get("platz")
    return uid_pruefen(z.get("uid")), Laborprofil(schema, z["art"], platz if isinstance(platz, int) else None, z.get("labor_aktiv") is True,
                                                  str(z.get("rolle")), z.get("aktiv") is True)


def laborprofile_lesen(db, labor_schemas: list[str]) -> dict[str, Konto]:
    konten: dict[str, Konto] = {}
    for schema in labor_schemas:
        for z in json_lesen(db.sql("laborprofile", schema=schema), list):
            uid, profil = _laborprofil(schema, z)
            konten.setdefault(uid, Konto(uid, [])).profile.append(profil)
    return konten


def konten_ergaenzen(db, konten: dict[str, Konto], profil_schemas: list[str], labor_schemas: list[str]) -> None:
    """Profile ohne Laborkennzeichen in jedem Schema und die Angaben aus auth.users (Adresse, letzte Anmeldung, Sperre)."""
    uids = uid_liste(sorted(konten))
    for schema in profil_schemas:
        name = "andere_profile" if schema in labor_schemas else "profile_ohne_laborspalte"
        for uid in json_lesen(db.sql(name, schema=schema, uids=uids), list):
            if uid_pruefen(uid) in konten:
                konten[uid].andere.append(schema)
    for z in json_lesen(db.sql("konten", uids=uids), list):
        if not isinstance(z, dict) or uid_pruefen(z.get("uid")) not in konten:
            raise Fehler("Unerwartete Antwort der Datenbank (Konten)")
        k = konten[z["uid"]]
        k.email = z.get("email") if isinstance(z.get("email"), str) else ""
        k.letzte = z.get("letzte") if isinstance(z.get("letzte"), str) else None
        k.gesperrt = z.get("gesperrt") is True


def ausschlussgrund(k: Konto) -> str:
    """Leer, wenn das Konto ein Laborkonto nach beiden Bedingungen ist. Sonst der Grund, warum es nie angefasst wird."""
    if not k.email:
        return "kein Anmeldekonto mit Adresse gefunden"
    if k.andere:
        return f"hat ein Profil ohne Laborkennzeichen (Schema {', '.join(k.andere)})"
    if any(p.rolle != "mitglied" for p in k.profile):
        return "Rolle ist nicht mitglied"
    if any(p.aktiv for p in k.profile):
        return "Profil ist als Mitglied freigeschaltet (aktiv)"
    if not KENNUNG_RE.fullmatch(k.kennung):
        return "Kennung unklar (Art und Platz passen nicht oder die Schemas widersprechen sich)"
    lokal, _, domain = k.email.lower().rpartition("@")
    if domain != DOMAIN:
        return f"Adresse endet nicht auf @{DOMAIN}"
    if lokal != k.kennung:
        return "Adresse passt nicht zur Kennung"
    return ""


def bestand_lesen(db, nur: frozenset[str]) -> Bestand:
    s = json_lesen(db.sql("schemas"), dict)
    profil_schemas, labor_schemas, unlesbar = _schemas(s.get("profile")), _schemas(s.get("labor")), _schemas(s.get("unlesbar"))
    if unlesbar:
        raise Fehler(f"Profiltabelle im Schema {', '.join(unlesbar)} für postgres nicht vollständig lesbar (Recht oder Zeilenregel). Abbruch ohne "
                     "Änderung, denn ein Profil dort bliebe unsichtbar")
    konten = laborprofile_lesen(db, labor_schemas)
    if len(konten) > MAX_KONTEN:
        raise Eingabefehler(f"{len(konten)} Konten mit Laborprofil gefunden, die Höchstgrenze ist {MAX_KONTEN}. Abbruch ohne Änderung, "
                            "bitte den Bestand prüfen")
    if konten:
        konten_ergaenzen(db, konten, profil_schemas, labor_schemas)
    muster = {uid_pruefen(u) for u in json_lesen(db.sql("muster_konten"), list)}
    b = Bestand([], [], [], [], len(konten), len(muster - set(konten)), profil_schemas, labor_schemas)
    for k in sorted(konten.values(), key=lambda k: k.kennung):
        k.grund = ausschlussgrund(k)
        if k.grund:
            b.ausgeschlossen.append(k)
        elif nur and k.kennung not in nur:
            b.nicht_gewaehlt.append(k)
        else:
            b.ziele.append(k)
    b.fehlend = sorted(nur - {k.kennung for k in konten.values()})
    return b


# ---------------------------------------------------------------------------------------------------------------------------------
# Zählung
# ---------------------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Verweis:
    tabelle: str
    spalte: str
    art: str  # Löschart des Fremdschlüssels (LOESCHARTEN), "-" für auth.refresh_tokens und das Anmeldeprotokoll
    n: int | None  # None: nicht vollständig lesbar oder nicht prüfbar

    @property
    def name(self) -> str:
        if self.tabelle == PROTOKOLL:
            return "Anmeldeprotokoll"
        return self.tabelle if self.art == "-" else f"{self.tabelle}.{self.spalte}"


@dataclass(frozen=True)
class Zaehlung:
    verweise: tuple[Verweis, ...]
    konto: int

    def _zusatz(self, tabelle: str) -> int | None:
        return next(v.n for v in self.verweise if v.art == "-" and v.tabelle == tabelle)

    @property
    def refresh(self) -> int | None:
        return self._zusatz(REFRESH)

    @property
    def protokoll(self) -> int | None:
        return self._zusatz(PROTOKOLL)

    def fremdschluessel(self) -> list[Verweis]:
        return [v for v in self.verweise if v.art != "-"]

    def sperrend(self) -> list[Verweis]:
        return [v for v in self.verweise if v.art in SPERRENDE_ARTEN and v.n]

    def nullend(self) -> list[Verweis]:
        return [v for v in self.verweise if v.art in NULLENDE_ARTEN and v.n]

    def unlesbar(self) -> list[str]:
        return [v.name for v in self.verweise if v.n is None]

    def hindernisse(self) -> list[str]:
        """Was das Löschen dieses Kontos vor jeder Änderung stoppt (außer laufenden Sitzungen im Kern)."""
        saetze = []
        if self.unlesbar():
            saetze.append("Zählung unvollständig, nicht lesbar oder nicht prüfbar: " + ", ".join(self.unlesbar()))
        if self.sperrend():
            saetze.append("Verweis mit Löschsperre: " + ", ".join(f"{v.name} {v.n}" for v in self.sperrend()))
        if self.nullend():
            saetze.append("Verweis, den das Löschen nur auf null setzen würde (die Zeile bliebe stehen): "
                          + ", ".join(f"{v.name} {v.n}" for v in self.nullend()) + ". Erst den Nachlauf laufen lassen (labor_loeschen)")
        return saetze

    def text(self) -> str:
        teile = [f"{v.name} {v.n}" + ("" if v.art in ("c", "-") else f" ({LOESCHARTEN[v.art]})")
                 for v in self.verweise if v.n and v.tabelle != PROTOKOLL]
        teile += [f"{v} nicht lesbar" for v in self.unlesbar()]
        zeilen = ", ".join(teile) if teile else "keine"
        protokoll = "nicht lesbar" if self.protokoll is None else self.protokoll
        return f"Zeilen: {zeilen}; Anmeldeprotokoll {protokoll}"

    def rest(self) -> list[str]:
        """Was nach dem Löschen noch da ist (soll leer sein)."""
        rest = [f"{v.name} {v.n}" for v in self.verweise if v.n]
        rest += [f"auth.users {self.konto}"] if self.konto else []
        return rest + [f"{v} nicht lesbar" for v in self.unlesbar()]


def _verweis(v: dict) -> Verweis:
    n = v.get("n")
    if (not isinstance(v.get("tabelle"), str) or not isinstance(v.get("spalte"), str) or v.get("art") not in LOESCHARTEN
            or not (n is None or (isinstance(n, int) and not isinstance(n, bool) and n >= 0))):
        raise Fehler("Unerwartete Antwort der Datenbank (Verweise)")
    return Verweis(v["tabelle"], v["spalte"], v["art"], n)


def zaehlen(db, uid: str) -> Zaehlung:
    """Eine Zeile JSON je Verweis (dazu auth.refresh_tokens und das Anmeldeprotokoll), die letzte Zeile mit konto."""
    zeilen = [json_lesen(z, dict) for z in db.sql("zaehlen", uid=uid_pruefen(uid)).splitlines() if z.strip()]
    if not zeilen or "konto" not in zeilen[-1] or any("tabelle" not in z for z in zeilen[:-1]):
        raise Fehler("Unerwartete Antwort der Datenbank (Zählung)")
    verweise = tuple(_verweis(z) for z in zeilen[:-1])
    if sorted(v.tabelle for v in verweise if v.art == "-") != sorted([PROTOKOLL, REFRESH]):
        raise Fehler("Zählung unvollständig: auth.refresh_tokens oder auth.audit_log_entries fehlt")
    konto = zeilen[-1].get("konto")
    if not isinstance(konto, int) or isinstance(konto, bool) or konto < 0:
        raise Fehler("Unerwartete Antwort der Datenbank (Zählung konto)")
    return Zaehlung(verweise, konto)


def offene_kernsitzungen(db, uid: str, schemas: list[str]) -> list[str]:
    return [s for s in schemas if zahl(db.sql("kernsitzungen", schema=s, uid=uid_pruefen(uid))) > 0]


# ---------------------------------------------------------------------------------------------------------------------------------
# Anzeige
# ---------------------------------------------------------------------------------------------------------------------------------

def konto_zeilen(k: Konto, z: Zaehlung | None = None, offen: list[str] | None = None) -> list[str]:
    profile = "; ".join(p.text() for p in k.profile)
    letzte = k.letzte or "nie"
    zeilen = [f"  {k.kennung:<11} {maskiert(k.email):<18} {profile}, letzte Anmeldung {letzte}, Konto in GoTrue "
              f"{'gesperrt' if k.gesperrt else 'frei'}"]
    if z is not None:
        zeilen.append(f"{'':14}{z.text()}")
        zeilen += [f"{'':14}Achtung: {satz}" for satz in z.hindernisse()]
    if offen:
        zeilen.append(f"{'':14}Achtung: laufende Sitzung im Kern (Schema {', '.join(offen)})")
    return zeilen


def plan_zeilen() -> list[str]:
    return [
        f"Plan (nur mit --ausfuehren --bestaetigung {BESTAETIGUNG}):",
        f"  1. Ziel-Profile sperren (labor_aktiv = false), falls noch freigeschaltet; Sperrfrist bis {SPERRFRIST_S} Sekunden nach der letzten",
        "     Änderung eines Ziel-Profils abwarten, danach die Konten neu suchen und prüfen",
        "  Je Konto, ein Fehler stoppt nur dieses Konto:",
        "  2. Vorprüfung: Zählung vorher vollständig lesbar, keine laufende Sitzung im Kern, kein Verweis mit Löschsperre und keiner, den das",
        "     Löschen nur auf null setzen würde, GoTrue nennt dieselbe Adresse",
        "  3. Konto in GoTrue sperren (PUT /auth/v1/admin/users/<id>, ban_duration)",
        "  4. Sitzungen widerrufen (auth.sessions und übrige auth.refresh_tokens, wie GoTrue bei /logout?scope=global)",
        "  5. Einträge im Anmeldeprotokoll löschen (auth.audit_log_entries)",
        "  6. Konto hart löschen (DELETE /auth/v1/admin/users/<id>, should_soft_delete false), die Datenbank löscht per Fremdschlüssel mit",
        "  7. Nachprüfung: GoTrue meldet user_not_found, Zählung danach 0",
        "  8. Nachweis: verbliebene Laborkonten (soll 0 sein), Datum, Journal (Start und Ergebnis, ohne Adressen)",
    ]


def bestand_ausgeben(b: Bestand, zaehlungen: dict[str, Zaehlung], offen: dict[str, list[str]]) -> None:
    ausgabe(f"Schemas mit Laborspalte: {', '.join(b.labor_schemas) or 'keines'}. Konten mit Laborprofil: {b.laborkonten} "
            f"(Höchstgrenze {MAX_KONTEN}).")
    ausgabe()
    ausgabe(f"Ziel ({anzahl_konten(len(b.ziele))}):" if b.ziele else "Ziel: kein Konto.")
    for k in b.ziele:
        for z in konto_zeilen(k, zaehlungen.get(k.uid), offen.get(k.uid)):
            ausgabe(z)
    if b.ausgeschlossen:
        ausgabe()
        ausgabe(f"Nicht angefasst ({anzahl_konten(len(b.ausgeschlossen))} mit Laborprofil):")
        for k in b.ausgeschlossen:
            ausgabe(f"  {k.kennung:<11} {maskiert(k.email):<18} {k.grund}")
    if b.nicht_gewaehlt:
        ausgabe(f"Nicht gewählt (--kennung): {', '.join(k.kennung for k in b.nicht_gewaehlt)}")
    for kennung_ in b.fehlend:
        ausgabe(f"{kennung_}: kein Konto mit diesem Laborprofil gefunden (schon gelöscht?)")
    if b.muster_ohne_profil:
        ausgabe(f"Hinweis: Konten mit einer Laboradresse (labor-..@{DOMAIN}) ohne Laborprofil: {b.muster_ohne_profil}. Sie werden nicht "
                "angefasst, bitte von Hand prüfen.")


def vorschau(db, b: Bestand) -> tuple[dict[str, Zaehlung], dict[str, list[str]]]:
    zaehlungen = {k.uid: zaehlen(db, k.uid) for k in b.ziele}
    offen = {k.uid: offene_kernsitzungen(db, k.uid, b.profil_schemas) for k in b.ziele}
    return zaehlungen, offen


# ---------------------------------------------------------------------------------------------------------------------------------
# Echtlauf je Konto
# ---------------------------------------------------------------------------------------------------------------------------------

@dataclass
class Ergebnis:
    kennung: str
    geloescht: bool
    ok: bool
    text: str


def vorpruefen(db, gt: GoTrue, k: Konto, vorher: Zaehlung, schemas: list[str]) -> None:
    hindernisse = vorher.hindernisse()
    if hindernisse:
        raise Fehler("; ".join(hindernisse))
    offen = offene_kernsitzungen(db, k.uid, schemas)
    if offen:
        raise Fehler(f"es läuft noch eine Sitzung im Kern (Schema {', '.join(offen)}), später wiederholen")
    if vorher.konto != 1:
        raise Fehler("das Konto ist in auth.users nicht (mehr) vorhanden")
    # frisch aus der Zählung: Profile gibt es genau in den Schemas der Laborprofile (seit der Suche kam keines dazu, keines fehlt)
    profile = {v.tabelle.split(".")[0]: v.n for v in vorher.verweise if v.tabelle.endswith(".profiles") and v.spalte == "user_id"}
    if {s for s, n in profile.items() if n} != {p.schema for p in k.profile}:
        raise Fehler("die Profile des Kontos haben sich seit der Suche geändert, bitte neu starten")
    a = gt.konto_lesen(k.uid)
    d = a.als_json()
    if a.status != 200 or not isinstance(d, dict):
        raise Fehler(f"GoTrue {kurz(a)}")
    if d.get("id") != k.uid or str(d.get("email") or "").lower() != k.email.lower():
        raise Fehler("GoTrue nennt ein anderes Konto oder eine andere Adresse")


def konto_sperren(gt: GoTrue, k: Konto) -> None:
    a = gt.sperren(k.uid)
    d = a.als_json()
    if a.status != 200 or not isinstance(d, dict) or not d.get("banned_until"):
        raise Fehler(f"Sperre nicht bestätigt (GoTrue {kurz(a)})")


def sitzungen_widerrufen(db, k: Konto) -> int:
    zeilen = db.sql("sitzungen_widerrufen", uid=k.uid).splitlines()
    if len(zeilen) != 3:
        raise Fehler("Unerwartete Antwort der Datenbank (Sitzungen)")
    sitzungen, _refresh, rest = (zahl(z) for z in zeilen)
    if rest:
        raise Fehler(f"noch {rest} Sitzungen oder Refresh-Tokens des Kontos vorhanden")
    return sitzungen


def konto_hart_loeschen(gt: GoTrue, k: Konto) -> None:
    a = gt.loeschen(k.uid)
    if a.status in (200, 204) or (a.status == 404 and kennung(a) == "user_not_found"):
        return
    raise Fehler(f"GoTrue {kurz(a)}, das Konto bleibt gesperrt und ohne Sitzungen")


def nachpruefen(db, gt: GoTrue, k: Konto, sitzungen: int, protokoll: int) -> Ergebnis:
    erledigt = f"Sitzungen widerrufen {sitzungen}, Protokolleinträge gelöscht {protokoll}"
    try:
        a = gt.konto_lesen(k.uid)
        nachher = zaehlen(db, k.uid)
    except Fehler as e:
        return Ergebnis(k.kennung, True, False, f"gelöscht ({erledigt}), Nachprüfung gescheitert: {e}")
    offen = [] if (a.status == 404 and kennung(a) == "user_not_found") else [f"GoTrue bestätigt das Löschen nicht ({kurz(a)})"]
    offen += nachher.rest()
    if offen:
        return Ergebnis(k.kennung, True, False, f"gelöscht ({erledigt}), Nachprüfung offen: {', '.join(offen)}")
    return Ergebnis(k.kennung, True, True, f"gelöscht ({erledigt}), danach 0 Zeilen in {len(nachher.fremdschluessel())} Verweisen, "
                                          "auth.refresh_tokens 0, Anmeldeprotokoll 0")


def konto_loeschen(db, gt: GoTrue, k: Konto, schemas: list[str]) -> Ergebnis:
    schritt = 2
    try:
        vorher = zaehlen(db, k.uid)
        ausgabe(f"{k.kennung}: vorher {vorher.text()}")
        vorpruefen(db, gt, k, vorher, schemas)
        schritt = 3
        konto_sperren(gt, k)
        schritt = 4
        sitzungen = sitzungen_widerrufen(db, k)
        schritt = 5
        protokoll = zahl(db.sql("protokoll_loeschen", uid=k.uid))
        schritt = 6
        konto_hart_loeschen(gt, k)
    except Fehler as e:
        return Ergebnis(k.kennung, False, False, f"FEHLER Schritt {schritt} ({SCHRITTE[schritt]}): {e}")
    except Exception as e:  # noqa: BLE001 (ein Fehler bei einem Konto darf die übrigen nie verhindern)
        return Ergebnis(k.kennung, False, False, f"FEHLER Schritt {schritt} ({SCHRITTE[schritt]}): unerwarteter Fehler {type(e).__name__}")
    try:
        return nachpruefen(db, gt, k, sitzungen, protokoll)
    except Exception as e:  # noqa: BLE001
        return Ergebnis(k.kennung, True, False, f"gelöscht, Nachprüfung gescheitert: unerwarteter Fehler {type(e).__name__}")


def profile_sperren(db, ziele: list[Konto]) -> int:
    """Schritt 1: setzt labor_aktiv = false bei jedem Ziel-Profil, das noch freigeschaltet ist. Liefert die Zahl der gesperrten Profile."""
    return sum(zahl(db.sql("profil_sperren", schema=p.schema, uid=k.uid)) for k in ziele for p in k.profile)


def sperrfrist_rest(db, ziele: list[Konto]) -> int:
    """Sekunden bis zum Ende der Sperrfrist des jüngst geänderten Ziel-Profils (0, wenn alle länger als die Frist unverändert sind)."""
    schemas = sorted({p.schema for k in ziele for p in k.profile})
    uids = uid_liste(sorted(k.uid for k in ziele))
    return max([zahl(db.sql("sperrfrist", schema=s, uids=uids)) for s in schemas] + [0])


# ---------------------------------------------------------------------------------------------------------------------------------
# Abläufe
# ---------------------------------------------------------------------------------------------------------------------------------

def anzahl_konten(n: int) -> str:
    return f"{n} Konto" if n == 1 else f"{n} Konten"


def jetzt() -> str:
    return datetime.now().astimezone().strftime("%d.%m.%Y %H:%M %Z").strip()


def trockenlauf(db, nur: frozenset[str]) -> int:
    ausgabe(f"Laborkonten löschen, Trockenlauf ({jetzt()}): Es wird nichts geändert und kein Schlüssel gelesen.")
    b = bestand_lesen(db, nur)
    zaehlungen, offen = vorschau(db, b)
    bestand_ausgeben(b, zaehlungen, offen)
    ausgabe()
    for z in plan_zeilen():
        ausgabe(z)
    ausgabe()
    ausgabe(f"Trockenlauf beendet: zu löschen {anzahl_konten(len(b.ziele))}, unberührt {anzahl_konten(len(b.ausgeschlossen))} mit Laborprofil.")
    return EXIT_OK


def nachweis(db, nur: frozenset[str], ergebnisse: list[Ergebnis]) -> tuple[bool, str]:
    """Liest den Bestand neu. Ohne --kennung zählt jedes verbliebene Konto mit Laborprofil, mit --kennung nur die gewählten."""
    b = bestand_lesen(db, frozenset())
    rest = {k.kennung for k in b.alle()}
    offen = sorted(rest & nur) if nur else sorted(rest)
    geloescht = sum(e.geloescht for e in ergebnisse)
    fehler = sum(not e.ok for e in ergebnisse)
    ausgabe()
    ausgabe(f"Nachweis ({jetzt()}):")
    ausgabe(f"  Ziel {len(ergebnisse)}, gelöscht {geloescht}, mit Fehler oder offener Nachprüfung {fehler}")
    ausgabe(f"  verbliebene Laborkonten (Konten mit Laborprofil in einem Schema): {b.laborkonten}"
            + (f", davon gewählt: {len(offen)}" if nur else ""))
    if b.muster_ohne_profil:
        ausgabe(f"  Konten mit Laboradresse ohne Laborprofil: {b.muster_ohne_profil} (nicht angefasst, von Hand prüfen)")
    ok = not offen and fehler == 0
    ausgabe("Ergebnis: Nachweis erbracht." if ok else "Ergebnis: Nachweis NICHT erbracht. Die Zeilen oben nennen Konto und Grund, der Lauf ist "
            "wiederholbar.")
    zeile = (f"echtlauf ziel={len(ergebnisse)} geloescht={geloescht} fehler={fehler} verblieben={b.laborkonten} "
             f"nachweis={'ok' if ok else 'offen'}" + (f" auswahl={','.join(sorted(nur))}" if nur else ""))
    return ok, zeile


def ziele_loeschen(db, gt: GoTrue, b: Bestand, nur: frozenset[str], warte: Callable[[float], None], ergebnisse: list[Ergebnis]) -> None:
    ausgabe()
    gesperrt = profile_sperren(db, b.ziele)
    rest = sperrfrist_rest(db, b.ziele)
    if rest:
        ausgabe(f"Schritt 1: jetzt gesperrt: {gesperrt} Profile. Ein Ziel-Profil wurde vor weniger als {SPERRFRIST_S} Sekunden geändert. Sperrfrist: "
                f"warte {rest + 1} Sekunden, damit der Kern keine neue Sitzung mehr beginnt.")
        warte(rest + 1)
    else:
        ausgabe(f"Schritt 1: jetzt gesperrt: {gesperrt} Profile, die Sperrfrist ist bei allen Ziel-Profilen abgelaufen.")
    # Nach der Sperrfrist neu suchen: Gelöscht wird nur, was vorher und jetzt Ziel ist
    jetzt_ziele = {k.uid: k for k in bestand_lesen(db, nur).ziele}
    for k in b.ziele:
        if k.uid not in jetzt_ziele:
            e = Ergebnis(k.kennung, False, False, "FEHLER Schritt 2 (Vorprüfung): nach der Sperrfrist kein Ziel mehr, nicht angefasst")
        else:
            e = konto_loeschen(db, gt, jetzt_ziele[k.uid], b.profil_schemas)
        ausgabe(f"{e.kennung}: {e.text}")
        ergebnisse.append(e)


def auswahl_text(nur: frozenset[str]) -> str:
    return f" auswahl={','.join(sorted(nur))}" if nur else ""


def echtlauf(db, gt: GoTrue, nur: frozenset[str], warte: Callable[[float], None], journal: Callable[[str], None]) -> int:
    ausgabe(f"Laborkonten löschen, ECHTLAUF ({jetzt()}).")
    try:
        b = bestand_lesen(db, nur)
    except Eingabefehler:
        journal("echtlauf abgebrochen ohne Änderung: Höchstgrenze überschritten")
        raise
    except (Exception, KeyboardInterrupt):
        journal("echtlauf abgebrochen ohne Änderung: Bestand nicht lesbar")
        raise
    bestand_ausgeben(b, {}, {})
    ergebnisse: list[Ergebnis] = []
    try:
        if b.ziele:
            journal(f"echtlauf start ziel={len(b.ziele)}{auswahl_text(nur)}")  # vor der ersten Änderung, damit auch ein harter Abbruch eine Spur hat
            ziele_loeschen(db, gt, b, nur, warte, ergebnisse)
        ok, zeile = nachweis(db, nur, ergebnisse)
    except (Exception, KeyboardInterrupt):
        journal(f"echtlauf abgebrochen ziel={len(b.ziele)} bearbeitet={len(ergebnisse)} geloescht={sum(e.geloescht for e in ergebnisse)} "
                "nachweis=fehlt")
        raise
    journal(zeile)
    return EXIT_OK if ok else EXIT_FEHLER


def argumente(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Laborkonten löschen und ihre Sitzungen widerrufen. Ohne --ausfuehren nur Trockenlauf.")
    ap.add_argument("--ausfuehren", action="store_true", help=f"wirklich löschen (nur mit --bestaetigung {BESTAETIGUNG})")
    ap.add_argument("--bestaetigung", default=None, help=f"Bestätigungswort {BESTAETIGUNG}")
    ap.add_argument("--kennung", action="append", default=[], help="nur diese Laborkennungen, zum Beispiel labor-09 (mehrfach oder mit Komma)")
    ap.add_argument("--basis", default=BASIS, help=f"GoTrue über Loopback (Standard {BASIS})")
    ap.add_argument("--env-datei", default=ENV_DATEI, help="Datei mit SERVICE_ROLE_KEY (nur im Echtlauf gelesen)")
    return ap.parse_args(argv)


def kennungen_lesen(werte: list[str]) -> frozenset[str]:
    nur = {w.strip().lower() for wert in werte for w in wert.split(",") if w.strip()}
    falsch = sorted(w for w in nur if not KENNUNG_RE.fullmatch(w))
    if falsch:
        raise Eingabefehler(f"--kennung: {', '.join(falsch)} ist keine Laborkennung (labor-01 bis labor-16 oder labor-schau)")
    return frozenset(nur)


def lauf(argv: list[str], *, db=None, journal: Callable[[str], None] | None = None, warte: Callable[[float], None] | None = None) -> int:
    GEHEIMNISSE.clear()
    try:
        a = argumente(argv)
        basis = basis_pruefen(a.basis)
        nur = kennungen_lesen(a.kennung)
        if a.ausfuehren and a.bestaetigung != BESTAETIGUNG:
            raise Eingabefehler(f"Der Echtlauf verlangt --bestaetigung {BESTAETIGUNG}")
        if a.bestaetigung is not None and not a.ausfuehren:
            raise Eingabefehler("--bestaetigung gilt nur zusammen mit --ausfuehren")
        gt = GoTrue(basis, dienstschluessel_lesen(a.env_datei)) if a.ausfuehren else None
    except Eingabefehler as e:
        ausgabe(f"FEHLER {e}")
        ausgabe("Es wurde nichts geändert.")
        return EXIT_EINGABE
    db = db if db is not None else Datenbank()
    try:
        if gt is None:
            return trockenlauf(db, nur)
        return echtlauf(db, gt, nur, warte or time.sleep, journal or journal_schreiben)
    except Eingabefehler as e:
        ausgabe(f"FEHLER {e}")
        return EXIT_EINGABE
    except Fehler as e:
        ausgabe(f"FEHLER {e}. Der Lauf ist wiederholbar.")
        return EXIT_FEHLER
    except KeyboardInterrupt:
        ausgabe("Abbruch mit Strg+C. Der Lauf ist wiederholbar: Gelöschte Konten findet er nicht mehr, die übrigen behandelt er neu.")
        return EXIT_ABBRUCH
    except Exception as e:  # noqa: BLE001 (nie ein Traceback: er könnte Werte aus der Datenbank zeigen)
        ausgabe(f"FEHLER unerwarteter Fehler ({type(e).__name__}). Der Lauf ist wiederholbar.")
        return EXIT_FEHLER


def _als_abbruch(nummer, rahmen) -> None:
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    # Fällt die ssh-Verbindung weg (SIGHUP) oder wird der Lauf beendet (SIGTERM), gilt das wie Strg+C: Journalzeile, Ausgang 130, wiederholbar
    for name in ("SIGHUP", "SIGTERM"):
        if hasattr(signal, name):
            with contextlib.suppress(ValueError, OSError):
                signal.signal(getattr(signal, name), _als_abbruch)
    return lauf(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
