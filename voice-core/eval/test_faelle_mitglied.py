"""Aufbau der Eval-Fälle für Mitglieder (eval/faelle_mitglied.py): Profil, Werkzeuge und Prompt wie im Kern, alle Fälle Muss-Fälle.

Ausführen:  python -m pytest -q eval/test_faelle_mitglied.py   (im Ordner voice-core/)
"""

from __future__ import annotations

import faelle_mitglied as fm

NIE = ("powershell_lesen", "git_klonen", "github_repo_anlegen", "bildschirm_ansehen", "auf_bildschirm_klicken")


def test_werkzeuge_sind_genau_die_der_mitglieder():
    from pc_host import LLM_TOOLS_MITGLIED

    assert set(fm.werkzeug_namen()) == set(LLM_TOOLS_MITGLIED)
    assert not set(NIE) & set(fm.werkzeug_namen())


def test_prompt_ist_der_fuer_mitglieder():
    text = fm.system_prompt()
    assert "Stimmabdruck" in text
    for name in NIE:
        assert name not in text, name


def test_alle_faelle_sind_muss_faelle_mit_werkzeugen_der_mitglieder():
    erlaubt = set(fm.werkzeug_namen())
    assert [f.id for f in fm.FAELLE] == ["g01", "g02", "g03"]
    for fall in fm.FAELLE:
        assert fall.muss, fall.id
        for alternativen in fall.erwartet:
            for aufruf in alternativen:
                assert aufruf.name in erlaubt, (fall.id, aufruf.name)
        assert set(fall.ergebnisse) <= erlaubt, fall.id
    assert fm.FAELLE[0].max_aufrufe == 0 and not fm.FAELLE[0].erwartet  # PowerShell: gar kein Aufruf
