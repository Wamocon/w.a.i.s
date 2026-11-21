"""Der Befehl, mit dem ein Serverprogramm über ssh startet (gemeinsam für wamo_labor.py, wamo_labor_nachlauf.py und den Lasttest, nur Standardbibliothek).

Die Serverprogramme dieser Werkzeuge reisen als Text in der Befehlszeile von ssh: zlib-gepackt, base64-kodiert, vom Interpreter am Server entpackt
und ausgeführt. Die Eingabe (JSON, nie ein Geheimnis in der Befehlszeile) geht über stdin.

Warum gepackt und warum mit Längengrenze: Das ssh aus Git für Windows (MSYS, es steht in Git Bash vor dem Windows-ssh im Suchpfad) schneidet die
Befehlszeile eines Prozesses bei etwa 8191 Zeichen ab, ohne Fehlermeldung. Der Befehl für den Kern war ungepackt rund 13700 Zeichen lang: Dem fernen
Befehl fehlte dann das schließende Anführungszeichen, und die Shell am Server meldete "Dateiende beim Suchen nach \\"" (bash: -c: Zeile 1). Gepackt ist
er unter 5000 Zeichen, und eine Grenze (BEFEHL_MAX) lässt ein künftig zu großes Programm laut scheitern, statt still abgeschnitten zu werden.
"""
from __future__ import annotations

import base64
import zlib

# Die Grenze liegt weit unter 8191, denn zur Befehlszeile gehören noch der Pfad von ssh, die Optionen, der Host und das Maskieren der Anführungszeichen.
BEFEHL_MAX = 6000
IN_ANFUEHRUNGSZEICHEN_VERBOTEN = '"$`\\'  # Zeichen mit Sonderbedeutung in doppelten Anführungszeichen der fernen Shell


class BefehlFehler(Exception):
    """Der Befehl wäre zu lang oder nicht sicher quotierbar. Der Text ist für die Person gedacht und enthält nie den Inhalt des Programms."""


def programm_code(programm: str) -> str:
    """Der Python-Code, der das Programm entpackt und ausführt (ein Ausdruck, nur Zeichen ohne Sonderbedeutung in doppelten Anführungszeichen)."""
    gepackt = base64.b64encode(zlib.compress(programm.encode("utf-8"), 9)).decode("ascii")
    return f"import base64,zlib;exec(zlib.decompress(base64.b64decode('{gepackt}')).decode('utf-8'))"


def server_befehl(programm: str, *, sudo: bool = False, isoliert: bool = False) -> str:
    """Der ferne Befehl: [sudo -n] python3 [-I] -c "<Code>". isoliert (python3 -I) lädt als root nichts aus dem Ordner oder der Umgebung."""
    code = programm_code(programm)
    if any(zeichen in code for zeichen in IN_ANFUEHRUNGSZEICHEN_VERBOTEN):
        raise BefehlFehler("Der Code für den Server lässt sich nicht sicher in doppelte Anführungszeichen setzen.")
    teile = (["sudo -n"] if sudo else []) + ["python3"] + (["-I"] if isoliert else []) + ["-c", f'"{code}"']
    befehl = " ".join(teile)
    if len(befehl) > BEFEHL_MAX:
        raise BefehlFehler(f"Der Befehl für ssh wäre {len(befehl)} Zeichen lang (erlaubt sind {BEFEHL_MAX}): Das ssh aus Git für Windows schneidet "
                           "Befehlszeilen bei etwa 8191 Zeichen ab. Das Serverprogramm muss kleiner werden.")
    return befehl


def programm_lesen(befehl: str) -> str:
    """Das Programm aus einem Befehl von server_befehl zurück (für Tests und zum Prüfen, nie am Server)."""
    anfang = befehl.index("'") + 1
    gepackt = befehl[anfang:befehl.index("'", anfang)]
    return zlib.decompress(base64.b64decode(gepackt)).decode("utf-8")
