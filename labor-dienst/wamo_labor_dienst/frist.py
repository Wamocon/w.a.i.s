"""Die Frist des Testlabors an einer einzigen Stelle: der Labortag und alles, was daraus folgt.

Eine weitere Verschiebung ändert nur LABORTAG. Daraus entstehen das Ende der Aufbewahrung (Vertrag D10: der Dienst behält die Daten bis einschließlich
AUFBEWAHRUNG_BIS), das erste Datum für den Löschlauf am Server (LOESCHLAUF_AB) und das Datum im Hinweistext für die Besucher (Platzhalter PLATZHALTER).

Skripte, die allein auf dem Server laufen (Löschlauf, Rauchtest), kennen dieses Paket nicht. Sie lesen die erzeugte Datei
infra/sokrates2/wamo-labor/frist.env (Zeilen WAMO_LABOR_...=JJJJMMTT). Nach einer Änderung von LABORTAG wird sie neu erzeugt, im Ordner labor-dienst:
    python -m wamo_labor_dienst.frist --schreiben ../infra/sokrates2/wamo-labor/frist.env
Ein Test hält die Datei gleich. Nur Standardbibliothek, keine Abhängigkeit vom Rest des Pakets.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

LABORTAG = date(2026, 12, 5)  # Entscheidung steht aus (Vorschlag): bisher der 28.11.2026
AUFBEWAHRUNG_NACH_LABORTAG_TAGE = 13  # D10: wie bisher, der 28.11. und der 11.12. lagen ebenso weit auseinander
AUFBEWAHRUNG_BIS = LABORTAG + timedelta(days=AUFBEWAHRUNG_NACH_LABORTAG_TAGE)  # letzter Tag, an dem der Dienst die Daten noch hält
LOESCHLAUF_AB = AUFBEWAHRUNG_BIS + timedelta(days=1)  # erster Tag, an dem der Löschlauf am Server löschen darf

PLATZHALTER = "{{AUFBEWAHRUNG_BIS}}"  # in der Seite für die Besucher; auslieferung.py setzt das Datum ein


def deutsch(tag: date) -> str:
    """TT.MM.JJJJ mit führenden Nullen, wie die Besucher es lesen."""
    return f"{tag.day:02d}.{tag.month:02d}.{tag.year}"


def einsetzen(text: str) -> str:
    """Setzt das Ende der Aufbewahrung in jeden Platzhalter ein. Text ohne Platzhalter bleibt unverändert."""
    return text.replace(PLATZHALTER, deutsch(AUFBEWAHRUNG_BIS))


def einsetzen_bytes(inhalt: bytes) -> bytes:
    """Wie einsetzen, für eine Seite im Speicher (UTF-8)."""
    return inhalt.replace(PLATZHALTER.encode("ascii"), deutsch(AUFBEWAHRUNG_BIS).encode("utf-8"))


def umgebungszeilen() -> list[str]:
    """Die Werte für Shell-Skripte und den Rauchtest, je Zeile NAME=JJJJMMTT (ohne Anführungszeichen, ohne Leerzeichen)."""
    return [f"WAMO_LABOR_LABORTAG={LABORTAG:%Y%m%d}", f"WAMO_LABOR_AUFBEWAHRUNG_BIS={AUFBEWAHRUNG_BIS:%Y%m%d}", f"WAMO_LABOR_LOESCHLAUF_AB={LOESCHLAUF_AB:%Y%m%d}"]


def datei_inhalt() -> str:
    """Der Inhalt von infra/sokrates2/wamo-labor/frist.env (nur LF)."""
    kopf = ("# Erzeugt aus labor-dienst/wamo_labor_dienst/frist.py, nie von Hand ändern. Neu erzeugen im Ordner labor-dienst:\n"
            "#   python -m wamo_labor_dienst.frist --schreiben ../infra/sokrates2/wamo-labor/frist.env\n"
            "# Gelesen von wamo-labor-loeschlauf.sh und wamo_labor_rauchtest.py (nur die Zeilen NAME=JJJJMMTT, nie als Skript ausgeführt).\n")
    return kopf + "\n".join(umgebungszeilen()) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Ohne Argument die Zeilen auf die Standardausgabe, mit --schreiben PFAD in eine Datei, mit --pruefen PFAD nur vergleichen (Ausgang 1 bei Abweichung)."""
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        sys.stdout.buffer.write(datei_inhalt().encode("utf-8"))  # Bytes: Windows ergänzte sonst CR vor jedem LF
        return 0
    if len(argv) == 2 and argv[0] in ("--schreiben", "--pruefen"):
        pfad = Path(argv[1])
        if argv[0] == "--schreiben":
            pfad.write_bytes(datei_inhalt().encode("utf-8"))
            return 0
        try:
            gleich = pfad.read_bytes() == datei_inhalt().encode("utf-8")
        except OSError:
            gleich = False
        if not gleich:
            sys.stderr.write(f"{pfad} stimmt nicht mit frist.py überein (neu erzeugen: python -m wamo_labor_dienst.frist --schreiben {pfad}).\n")
        return 0 if gleich else 1
    sys.stderr.write("Aufruf: python -m wamo_labor_dienst.frist [--schreiben PFAD | --pruefen PFAD]\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
