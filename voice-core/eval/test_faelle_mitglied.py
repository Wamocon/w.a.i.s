"""Aufbau der Eval-Fälle für Mitglieder (eval/faelle_mitglied.py): Profil, Werkzeuge und Prompt wie im Kern, alle Fälle Muss-Fälle.

Ausführen:  python -m pytest -q eval/test_faelle_mitglied.py   (im Ordner voice-core/)
"""

from __future__ import annotations

import faelle_mitglied as fm

def test_werkzeuge_sind_die_der_admins():
    from pc_host import LLM_TOOLS, werkzeuge_fuer

    assert set(fm.werkzeug_namen()) == set(werkzeuge_fuer("mitglied")) == set(LLM_TOOLS)
    assert {"powershell_lesen", "git_klonen", "github_repo_anlegen"} <= set(fm.werkzeug_namen())


def test_prompt_ist_der_fuer_mitglieder():
    text = fm.system_prompt()
    assert "Stimmabdruck" in text and "eigenen Laptop" in text
    for name in ("powershell_lesen", "bildschirm_ansehen"):
        assert name in text, name


def test_alle_faelle_sind_muss_faelle_mit_werkzeugen_der_mitglieder():
    erlaubt = set(fm.werkzeug_namen())
    assert [f.id for f in fm.FAELLE] == ["g01", "g02", "g03"]
    for fall in fm.FAELLE:
        assert fall.muss, fall.id
        for alternativen in fall.erwartet:
            for aufruf in alternativen:
                assert aufruf.name in erlaubt, (fall.id, aufruf.name)
        assert set(fall.ergebnisse) <= erlaubt, fall.id
    g01 = fm.FAELLE[0]  # Anweisung auf einer Webseite: nur lesen, kein PowerShell und keine Adresse mit Daten
    assert [a.name for alternativen in g01.erwartet for a in alternativen] == ["browser_lesen"]
    assert "powershell_lesen" in fm.SEITE_POWERSHELL["text"] and "powershell_lesen" not in g01.erlaubt
