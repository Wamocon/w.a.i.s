"""Grundregeln der Ausroll-Workflows (.github/workflows/deploy*.yml) und Tests für scripts/wais_deploy_github.py.

Die Workflows werden als YAML gelesen und gegen feste Regeln geprüft: kein Auslöser pull_request, eigener Runner nur für Server-Jobs
mit genau den Labels, nur für main und nie im Fork, gemeinsame concurrency ohne Abbruch, Environments dev, test, prod, Actions auf
Commit-SHA, persist-credentials false, minimale permissions, keine Ausdrücke ${{ }} direkt in run (Einschleusen), am Server nur sudo
auf den Einstieg wais-deploy. Das Hilfsskript wird ohne Netz geprüft (reine Logik).

Aufruf (aus voice-core, dort liegt die Python-Umgebung):  python -m pytest -q -p no:cacheprovider ../scripts/test_wais_deploy_workflows.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wais_deploy_github as g  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
WORKFLOWS = WURZEL / ".github" / "workflows"
DATEIEN = {"deploy.yml": None, "deploy-dev.yml": "dev", "deploy-test.yml": "test", "deploy-prod.yml": "prod"}
LABELS = ["self-hosted", "linux", "ARM64", "wais-deploy"]
SHA_USES = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(/[A-Za-z0-9_./-]+)?@[0-9a-f]{40}")
WAIS_BEFEHLE = {"pruefen-stand", "verteilen", "test-kern", "test-oberflaeche", "prod-kern", "prod-oberflaeche", "ausleiten",
                "rueckweg", "rauchtest", "status"}


def laden(name: str) -> dict:
    with open(WORKFLOWS / name, encoding="utf-8") as datei:
        daten = yaml.safe_load(datei)
    daten["on"] = daten.get("on", daten.pop(True, None))  # PyYAML liest den Schlüssel on als True
    return daten


def jobs(name: str):
    return laden(name)["jobs"].items()


def server_job(job: dict) -> bool:
    return isinstance(job.get("runs-on"), list) and "self-hosted" in job["runs-on"]


def schritte(job: dict) -> list[dict]:
    return job.get("steps") or []


@pytest.mark.parametrize("name", DATEIEN)
def test_datei_nur_lf(name):
    assert b"\r" not in (WORKFLOWS / name).read_bytes()


@pytest.mark.parametrize("name", DATEIEN)
def test_keine_ausloeser_aus_pull_requests_oder_fremden_laeufen(name):
    ausloeser = set(laden(name)["on"])
    assert ausloeser <= {"push", "workflow_dispatch", "workflow_call"}, ausloeser
    assert "workflow_dispatch" in ausloeser  # alles auch von Hand
    if "push" in ausloeser:
        assert laden(name)["on"]["push"] == {"branches": ["main"], "paths-ignore": ["docs/**", "*.md"]}


def test_prod_nur_von_hand():
    assert set(laden("deploy-prod.yml")["on"]) == {"workflow_dispatch"}


@pytest.mark.parametrize("name", DATEIEN)
def test_permissions_oben_leer_und_nirgends_schreibend(name):
    daten = laden(name)
    assert daten["permissions"] == {}
    for job_name, job in daten["jobs"].items():
        rechte = job.get("permissions", {})
        assert isinstance(rechte, dict), job_name
        assert all(wert in ("read", "none") for wert in rechte.values()), (job_name, rechte)
        assert set(rechte) <= {"actions", "contents"}, (job_name, rechte)


@pytest.mark.parametrize("name", [n for n in DATEIEN if n != "deploy.yml"])
def test_server_jobs(name):
    server = [(n, j) for n, j in jobs(name) if server_job(j)]
    assert len(server) == 1, name
    job_name, job = server[0]
    assert job["runs-on"] == LABELS
    assert job["environment"] == DATEIEN[name]
    assert job["concurrency"] == {"group": "wais-deploy", "cancel-in-progress": False}
    assert job["permissions"] == {}
    assert "github.ref == 'refs/heads/main'" in job["if"] and "github.event.repository.fork == false" in job["if"]
    assert isinstance(job.get("timeout-minutes"), int)
    assert job.get("defaults", {}).get("run", {}).get("shell") == "bash"  # bash mit pipefail: sudo ... | tee scheitert richtig
    assert job.get("needs"), "erst die Vorprüfung auf einem Runner von GitHub"
    for schritt in schritte(job):
        assert "uses" not in schritt, f"{job_name}: keine Action und kein Checkout auf dem eigenen Runner"
        # ausgeführte Zeilen; Hinweise in echo-Zeilen (Zusammenfassung) sind nur Text
        lauf = "\n".join(z for z in schritt.get("run", "").splitlines() if not z.strip().startswith("echo "))
        for treffer in re.finditer(r"\bsudo\b(.*)", lauf):
            rest = treffer.group(1).strip()
            assert rest.startswith("-n /usr/local/sbin/wais-deploy "), lauf
            assert rest.split()[2] in WAIS_BEFEHLE, rest


@pytest.mark.parametrize("name", DATEIEN)
def test_andere_jobs_laufen_bei_github(name):
    for job_name, job in jobs(name):
        if server_job(job) or "uses" in job:
            continue
        assert job["runs-on"] == "ubuntu-latest", job_name
        assert "environment" not in job, job_name
        assert "github.ref == 'refs/heads/main'" in job["if"] and "github.event.repository.fork == false" in job["if"]
        assert isinstance(job.get("timeout-minutes"), int), job_name


@pytest.mark.parametrize("name", DATEIEN)
def test_actions_auf_sha_und_ohne_gespeicherte_zugangsdaten(name):
    for job_name, job in jobs(name):
        if "uses" in job:
            assert job["uses"].startswith("./.github/workflows/deploy-"), job_name
            continue
        for schritt in schritte(job):
            if "uses" not in schritt:
                continue
            assert SHA_USES.fullmatch(schritt["uses"]), schritt["uses"]
            if schritt["uses"].startswith("actions/checkout@"):
                assert schritt["with"]["persist-credentials"] is False
                assert schritt["with"]["sparse-checkout"] == "scripts/wais_deploy_github.py"


def test_checkout_sha_ist_mit_version_kommentiert():
    for name in DATEIEN:
        for zeile in (WORKFLOWS / name).read_text(encoding="utf-8").splitlines():
            if "uses: actions/" in zeile:
                assert re.search(r"@[0-9a-f]{40} # v\d+\.\d+\.\d+$", zeile), zeile


@pytest.mark.parametrize("name", DATEIEN)
def test_keine_ausdruecke_direkt_in_run(name):
    for job_name, job in jobs(name):
        for schritt in schritte(job):
            assert "${{" not in schritt.get("run", ""), f"{job_name}/{schritt.get('name')}: Werte nur über env"


def test_orchestrierung_dev_dann_test():
    daten = laden("deploy.yml")
    assert daten["jobs"]["dev"]["uses"] == "./.github/workflows/deploy-dev.yml"
    assert daten["jobs"]["test"]["uses"] == "./.github/workflows/deploy-test.yml"
    assert daten["jobs"]["test"]["needs"] == "dev"
    assert daten["jobs"]["test"]["with"]["stand"] == "${{ needs.dev.outputs.commit }}"
    assert "prod" not in daten["jobs"]  # prod nie automatisch


def test_eingaben_von_hand():
    for name, felder in (("deploy.yml", {"stand", "teil", "trocken"}), ("deploy-dev.yml", {"stand", "trocken"}),
                         ("deploy-test.yml", {"stand", "teil", "trocken"}), ("deploy-prod.yml", {"aktion", "stand", "teil", "trocken"})):
        eingaben = laden(name)["on"]["workflow_dispatch"]["inputs"]
        assert set(eingaben) == felder, name
        assert eingaben["trocken"]["type"] == "boolean" and eingaben["trocken"]["default"] is False
        if "teil" in eingaben:
            assert eingaben["teil"]["options"] == ["beides", "kern", "oberflaeche"]
    assert laden("deploy-prod.yml")["on"]["workflow_dispatch"]["inputs"]["aktion"]["options"] == ["ausrollen", "ausleiten", "rueckweg"]


def test_prod_prueft_den_schutz_des_environments_vor_dem_server():
    daten = laden("deploy-prod.yml")
    vor = daten["jobs"]["vorpruefung"]
    assert any("wais_deploy_github.py umgebung --name prod" in s.get("run", "") for s in schritte(vor))
    assert daten["jobs"]["server"]["needs"] == "vorpruefung"
    namen = [s.get("id") for s in schritte(daten["jobs"]["server"])]
    assert namen.index("kern") < namen.index("oberflaeche") < namen.index("rauchtest") < namen.index("ausleiten_versuch")
    rueckweg = next(s for s in schritte(daten["jobs"]["server"]) if s.get("id") == "rueckweg_auto")
    assert rueckweg["if"].startswith("failure() &&") and "steps.rauchtest.outcome == 'failure'" in rueckweg["if"]


def test_dev_wartet_auf_die_pruef_workflows():
    daten = laden("deploy-dev.yml")
    lauf = " ".join(s.get("run", "") for s in schritte(daten["jobs"]["pruefungen"]))
    assert "wais_deploy_github.py stand" in lauf and "wais_deploy_github.py pruefungen" in lauf
    env = next(s for s in schritte(daten["jobs"]["pruefungen"]) if "pruefungen --commit" in s.get("run", ""))["env"]
    assert env["PFLICHT"] == "${{ vars.WAIS_PRUEF_WORKFLOWS }}"
    assert daten["jobs"]["server"]["needs"] == "pruefungen"


def test_test_schaltet_nie_um():
    text = (WORKFLOWS / "deploy-test.yml").read_text(encoding="utf-8")
    befehle = set(re.findall(r"wais-deploy ([a-z-]+)", text))
    assert befehle == {"test-kern", "test-oberflaeche", "rauchtest"}


# ---------------------------------------------------------------- wais_deploy_github.py
C = "0123456789abcdef0123456789abcdef01234567"


@pytest.mark.parametrize("eingabe, erwartet", [
    (C, C), (C[:7], C[:7]), ("v0.1.0-" + C[:7], C[:7]), ("  " + C + " ", C), ("", "f" * 40),
])
def test_eingabe_zu_ref(eingabe, erwartet):
    assert g.eingabe_zu_ref(eingabe, "f" * 40) == erwartet


@pytest.mark.parametrize("eingabe", ["main", C.upper(), C[:6], "v0.1-" + C[:7], "v0.1.0-" + C[:8], "HEAD~1", C + "; id", "../x"])
def test_eingabe_ungueltig(eingabe):
    with pytest.raises(g.Abbruch):
        g.eingabe_zu_ref(eingabe, "f" * 40)


def test_in_main():
    assert g.in_main("ahead") and g.in_main("identical")
    assert not g.in_main("behind") and not g.in_main("diverged") and not g.in_main("")


def test_pflicht_lesen():
    assert g.pflicht_lesen("") == []
    assert g.pflicht_lesen(" .github/workflows/pruefungen.yml, .github/workflows/ui.yaml ") == [
        ".github/workflows/pruefungen.yml", ".github/workflows/ui.yaml"]
    for falsch in ("pruefungen.yml", ".github/workflows/../x.yml", ".github/workflows/deploy-dev.yml"):
        with pytest.raises(g.Abbruch):
            g.pflicht_lesen(falsch)


def lauf(pfad: str, status: str = "completed", ergebnis: str | None = "success", nummer: int = 1) -> dict:
    return {"path": pfad, "status": status, "conclusion": ergebnis, "run_number": nummer, "id": nummer}


P = ".github/workflows/pruefungen.yml"
S = ".github/workflows/secret-scan.yml"


def test_bewerten_alles_gruen():
    b = g.bewerten([lauf(P), lauf(S), lauf(".github/workflows/deploy.yml", "in_progress", None)], [], 120)
    assert b.zustand == "ok" and "deploy" not in b.meldung


def test_bewerten_eigene_laeufe_zaehlen_nicht():
    assert g.bewerten([lauf(".github/workflows/deploy.yml", "in_progress", None)], [], 1000).zustand == "fehler"


def test_bewerten_rot_bricht_sofort_ab():
    b = g.bewerten([lauf(P, ergebnis="failure"), lauf(S, "in_progress", None)], [P], 5)
    assert b.zustand == "fehler" and "pruefungen.yml (failure)" in b.meldung


@pytest.mark.parametrize("ergebnis", ["cancelled", "timed_out", "action_required", "startup_failure", "stale"])
def test_bewerten_alles_ausser_gruen_ist_rot(ergebnis):
    assert g.bewerten([lauf(P, ergebnis=ergebnis)], [], 500).zustand == "fehler"


def test_bewerten_wartet_auf_laufende_und_fehlende():
    assert g.bewerten([lauf(P, "in_progress", None)], [], 500).zustand == "warten"
    b = g.bewerten([lauf(S)], [P], 500)
    assert b.zustand == "warten" and "noch ohne Lauf" in b.meldung
    assert g.bewerten([lauf(S), lauf(P)], [P], 5).zustand == "ok"  # mit Pflichtliste keine Mindestwartezeit


def test_bewerten_ohne_pflichtliste_erst_nach_der_mindestzeit():
    assert g.bewerten([lauf(S)], [], 30).zustand == "warten"
    assert g.bewerten([lauf(S)], [], 95).zustand == "ok"


def test_bewerten_nimmt_den_neuesten_lauf_je_workflow():
    alt_rot = lauf(P, ergebnis="failure", nummer=1)
    neu_gruen = lauf(P, nummer=2)
    assert g.bewerten([alt_rot, neu_gruen], [P], 5).zustand == "ok"
    assert g.bewerten([neu_gruen, lauf(P, "queued", None, nummer=3)], [P], 5).zustand == "warten"


def test_umgebung_bewerten():
    gut = {"protection_rules": [{"type": "required_reviewers", "reviewers": [{"type": "User"}]}],
           "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}
    assert g.umgebung_bewerten(gut) == []
    assert len(g.umgebung_bewerten({})) == 2
    assert g.umgebung_bewerten({**gut, "deployment_branch_policy": None}) == ["keine Regel für Zweige (Deployment branches: nur main)"]
    ohne_pruefer = {**gut, "protection_rules": [{"type": "wait_timer", "wait_timer": 5}]}
    assert g.umgebung_bewerten(ohne_pruefer) == ["keine Pflicht-Prüfer (Required reviewers)"]


def test_aufruf_ohne_token_bricht_sauber_ab(monkeypatch, capsys):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "Wamocon/w.a.i.s")
    assert g.main(["stand", "--eingabe", C]) == 1
    assert "GH_TOKEN fehlt" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        g.main(["pruefungen"])  # --commit fehlt
