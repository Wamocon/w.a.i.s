"""Tests für die Pfadregeln des persönlichen GitHub-Wegs (infra/sokrates2/wamo_job_pfadregeln.py, Plan C, Paket D-b).

Die Regeln stammen aus Folgepaket 1, 3.1.3, ergänzt um Plan C, C.5 Laufende 4. Das Modul besteht aus reinen Funktionen über
Bytes, es liest keine Datei und startet keinen Prozess; die Tests laufen deshalb unter Windows und Linux.
Ausführen (im Ordner voice-core/):  python -m pytest -q test_job_pfadregeln.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

INFRA = Path(__file__).resolve().parent.parent / "infra" / "sokrates2"


def _lade():
    spec = importlib.util.spec_from_file_location("wamo_job_pfadregeln", INFRA / "wamo_job_pfadregeln.py")
    modul = importlib.util.module_from_spec(spec)
    sys.modules["wamo_job_pfadregeln"] = modul  # nötig für @dataclass
    spec.loader.exec_module(modul)
    return modul


P = _lade()


def neu(pfad: str | bytes, inhalt: bytes = b"x\n", modus: str = "100644") -> object:
    roh = pfad if isinstance(pfad, bytes) else pfad.encode("utf-8")
    return P.Eintrag(pfad=roh, art="neu", modus=modus, alt_modus="000000", inhalt=inhalt)


def geaendert(pfad: str, inhalt: bytes = b"y\n", modus: str = "100644", alt_modus: str = "100644") -> object:
    return P.Eintrag(pfad=pfad.encode("utf-8"), art="geaendert", modus=modus, alt_modus=alt_modus, inhalt=inhalt)


def geloescht(pfad: str, alt_modus: str = "100644") -> object:
    return P.Eintrag(pfad=pfad.encode("utf-8"), art="geloescht", modus="000000", alt_modus=alt_modus, inhalt=None)


def pruefe(*eintraege, basis=(), geheimnisse=(), grenzen=None):
    basis_roh = [b if isinstance(b, bytes) else b.encode("utf-8") for b in basis]
    if grenzen is None:
        return P.pruefen(list(eintraege), basis_roh, geheimnisse=list(geheimnisse))
    return P.pruefen(list(eintraege), basis_roh, geheimnisse=list(geheimnisse), grenzen=grenzen)


def befund(ergebnis, pfad: str):
    treffer = [b for b in ergebnis.befunde if b.pfad == pfad]
    assert len(treffer) == 1, [b.pfad for b in ergebnis.befunde]
    return treffer[0]


# ---------------------------------------------------------------- Vertrag der Gründe
def test_gruende_sind_teil_der_aenderung_gruende():
    # Die Codes müssen in AENDERUNG_GRUENDE (C.2.6) stehen, die der Vertragstest gegen den Kern hält.
    spec = importlib.util.spec_from_file_location("wamo_job_kernkanal_pfadtest", INFRA / "wamo_job_kernkanal.py")
    kk = importlib.util.module_from_spec(spec)
    sys.modules["wamo_job_kernkanal_pfadtest"] = kk
    spec.loader.exec_module(kk)
    assert set(P.GRUENDE) <= set(kk.AENDERUNG_GRUENDE)
    assert set(P.GRUENDE) == {"pfad_gesperrt", "geheimnis", "zu_gross", "symlink", "sonderdatei"}


# ---------------------------------------------------------------- normale und saubere Änderungen
def test_saubere_aenderung_ist_normal_und_frei():
    erg = pruefe(neu("src/app.py", b"print('hallo')\n"), geaendert("README.md"), geloescht("alt.txt"),
                 basis=["README.md", "alt.txt"])
    assert not erg.gesperrt
    assert erg.gruende == ()
    assert [b.klasse for b in erg.befunde] == ["normal", "normal", "normal"]
    assert erg.ausgelassen == 0


def test_umlaute_und_erlaubte_sonderzeichen():
    erg = pruefe(neu("docs/Übersicht (v2) [entwurf]+a@b=c,d_e-f.md"))
    assert not erg.gesperrt


# ---------------------------------------------------------------- gesperrte Pfade
@pytest.mark.parametrize("pfad", [
    ".git/config", ".GIT/hooks/pre-commit", "sub/.git/hooks/post-checkout", ".Git/x", ".git /x", ".git./x",
    "a/.ｇｉｔ/config",  # Vollbreite, NFKC ergibt .git
    ".gitmodules", "sub/.GitModules",
    ".github/workflows/ci.yml", ".GitHub/workflows/x.yml", "pkg/.github/dependabot.yml",
    ".claude/settings.json", ".vscode/tasks.json", ".devcontainer/devcontainer.json", ".cursor/rules",
    ".githooks/pre-commit", ".mcp.json", "sub/.MCP.json", ".claude", ".github", "docs/.vscode",
    ".devcontainer.json", ".gemini/settings.json", ".codex/config.toml", ".windsurf/rules", ".zed/tasks.json", ".idea/workspace.xml",
])
def test_ausfuehrungsflaechen_gesperrt(pfad):
    erg = pruefe(neu(pfad))
    assert erg.gesperrt
    assert "pfad_gesperrt" in befund(erg, pfad).gruende


@pytest.mark.parametrize("pfad", [
    "a\x01b.txt", "a\tb", "a\nb", 'a"b', "a\\b", "a:b", "C:/x", "../x", "a/../b", "a..b", "/abs", "a//b", "a/",
    "a\u200cb", "a\u200db", "a\u202eb", "a\ufeffb",  # Format-Zeichen, die NFKC nicht entfernt
    "a~1", "git~1/x", "a;b", "a|b", "a*b", "a?b", "a<b", "a#b", "a$b", "a'b", "a`b", "a%b",
    "name.", "name ", " name", "dir./x", "dir /x", ".", "a/./b",
    "x" * 241,
])
def test_zeichen_und_formen_gesperrt(pfad):
    erg = pruefe(neu(pfad))
    assert erg.gesperrt, pfad
    assert "pfad_gesperrt" in erg.befunde[0].gruende


def test_laenge_240_ist_erlaubt():
    assert not pruefe(neu("x" * 240)).gesperrt


def test_ungueltiges_utf8_gesperrt_und_lesbar_angezeigt():
    erg = pruefe(neu(b"bad\xff\xfename.txt"))
    assert erg.gesperrt
    b = erg.befunde[0]
    assert "pfad_gesperrt" in b.gruende
    assert b.pfad_roh == b"bad\xff\xfename.txt"
    assert all(ord(z) >= 32 for z in b.pfad)


def test_anzeige_ohne_steuerzeichen():
    erg = pruefe(neu("a\x1b[31mrot"))
    assert "\x1b" not in erg.befunde[0].pfad
    assert P.pfad_anzeige("a\u2028b\u2029c".encode()) == "a?b?c"


@pytest.mark.parametrize("pfad", ["con", "CON.txt", "aux.c", "nul", "prn.md", "com1", "LPT9.log", "sub/com3.txt",
                                  "com\u00b9.txt"])  # COM mit hochgestellter 1 (NFKC)
def test_windows_geraetenamen_gesperrt(pfad):
    erg = pruefe(neu(pfad))
    assert erg.gesperrt
    assert "pfad_gesperrt" in erg.befunde[0].gruende


@pytest.mark.parametrize("pfad", ["console.log", "connect.py", "com10.txt", "auxiliary/x", "nullable.ts", "lpt.md"])
def test_aehnliche_namen_sind_keine_geraete(pfad):
    assert not pruefe(neu(pfad)).gesperrt


def test_dateien_mit_punkt_am_anfang_bleiben_moeglich():
    erg = pruefe(neu(".gitignore"), neu(".eslintrc.json"), neu("web/.prettierrc"))
    assert not erg.gesperrt


# ---------------------------------------------------------------- Kollisionen
def test_kollision_gross_klein_untereinander():
    erg = pruefe(neu("Readme.md"), neu("README.md"))
    assert erg.gesperrt
    assert all("pfad_gesperrt" in b.gruende for b in erg.befunde)


def test_kollision_gegen_die_basis():
    erg = pruefe(neu("src/Main.py"), basis=["src/main.py"])
    assert "pfad_gesperrt" in befund(erg, "src/Main.py").gruende


def test_kollision_im_ordnernamen():
    erg = pruefe(neu("Src/neu.py"), basis=["src/alt.py"])
    assert erg.gesperrt


def test_kollision_nfc_und_nfd():
    nfc = "caf\u00e9.txt"
    nfd = "cafe\u0301.txt"
    erg = pruefe(neu(nfd), basis=[nfc])
    assert erg.gesperrt


def test_umbenennung_nur_in_der_schreibweise_ist_keine_kollision():
    # Löschung von A.txt und neu a.txt: der Endstand hat nur a.txt
    erg = pruefe(geloescht("A.txt"), neu("a.txt"), basis=["A.txt"])
    assert not erg.gesperrt


def test_gleicher_pfad_geaendert_ist_keine_kollision():
    assert not pruefe(geaendert("src/main.py"), basis=["src/main.py"]).gesperrt


def test_datei_unter_einer_datei_der_basis_gesperrt():
    erg = pruefe(neu("lib/x"), basis=["lib"])
    assert erg.gesperrt


def test_basis_mit_eigener_kollision_sperrt_fremde_pfade_nicht():
    erg = pruefe(neu("neu.txt"), basis=["A.txt", "a.txt"])
    assert not erg.gesperrt


# ---------------------------------------------------------------- entschärfte Pfade kommen aus der Basis
def test_loeschung_entschaerfter_pfade_wird_ausgelassen():
    erg = pruefe(geloescht(".mcp.json"), geloescht(".claude/settings.json"), geloescht(".claude/skills/a/SKILL.md"),
                 neu("src/x.py"), basis=[".mcp.json", ".claude/settings.json", ".claude/skills/a/SKILL.md"])
    assert not erg.gesperrt
    assert erg.ausgelassen == 3
    assert [b.pfad for b in erg.befunde] == ["src/x.py"]


def test_aenderung_an_entschaerften_pfaden_gesperrt():
    erg = pruefe(geaendert(".claude/settings.json"), basis=[".claude/settings.json"])
    assert erg.gesperrt and erg.ausgelassen == 0


def test_loeschung_anderer_gesperrter_pfade_wird_nicht_ausgelassen():
    erg = pruefe(geloescht(".github/workflows/ci.yml"), basis=[".github/workflows/ci.yml"])
    assert erg.gesperrt and erg.ausgelassen == 0


def test_loeschung_in_anderer_schreibweise_wird_nicht_ausgelassen():
    erg = pruefe(geloescht(".Claude/x"), basis=[".Claude/x"])
    assert erg.gesperrt and erg.ausgelassen == 0


# ---------------------------------------------------------------- sensible Dateien
@pytest.mark.parametrize("pfad", [
    "package.json", "web/package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "Cargo.lock", "go.sum",
    ".npmrc", ".yarnrc.yml", "Dockerfile", "Dockerfile.prod", "docker-compose.override.yml", "Makefile", "build.sh",
    "tools/run.ps1", "x.bat", "y.cmd", ".husky/pre-commit", ".pre-commit-config.yaml", "pyproject.toml", "setup.py",
    "requirements-dev.txt", "vercel.json", "netlify.toml", ".gitlab-ci.yml", ".gitattributes", ".env", ".env.local",
    ".envrc", "cert.pem", "id.key", "CLAUDE.md", "docs/AGENTS.md", "tests/conftest.py", "Jenkinsfile",
    "azure-pipelines.yml", ".circleci/config.yml", "lefthook.yml", "mise.toml", "Taskfile.yml", ".bazelrc", "pytest.ini",
    "Directory.Build.props", "src/App.csproj", ".cargo/config.toml", ".mvn/wrapper/maven-wrapper.properties", ".yarn/releases/y.cjs",
])
def test_sensible_namen(pfad):
    erg = pruefe(neu(pfad))
    assert not erg.gesperrt
    assert befund(erg, pfad).klasse == "sensibel"


def test_ausfuehrbar_binaer_und_link_sensibel():
    erg = pruefe(neu("bin/tool", b"#!/bin/sh\n", modus="100755"), neu("bild.png", b"\x89PNG\r\n\x1a\n\x00\x00"),
                 neu("verweis", b"src/app.py", modus="120000"), basis=["src/app.py"])
    assert not erg.gesperrt
    assert {b.pfad: b.klasse for b in erg.befunde} == {"bin/tool": "sensibel", "bild.png": "sensibel", "verweis": "sensibel"}


def test_loeschung_einer_sensiblen_datei_ist_sensibel():
    erg = pruefe(geloescht("package.json"), basis=["package.json"])
    assert befund(erg, "package.json").klasse == "sensibel"


def test_moduswechsel_auf_ausfuehrbar_ist_sensibel():
    erg = pruefe(geaendert("run", b"x", modus="100755", alt_modus="100644"), basis=["run"])
    assert befund(erg, "run").klasse == "sensibel"


# ---------------------------------------------------------------- Links
@pytest.mark.parametrize("ziel", [b"/etc/passwd", b"../../x", b"..", b".", b"", b"a/../../../b", b".git/config",
                                  b"sub/.git/hooks", b".github/workflows", b"C:\\x", b"a\\b", b"x\x00y", b"x\ny",
                                  b"bad\xff", b"x" * 1025])
def test_link_ziele_gesperrt(ziel):
    erg = pruefe(neu("sub/link", ziel, modus="120000"))
    assert erg.gesperrt, ziel
    assert "symlink" in erg.befunde[0].gruende


def test_link_mit_relativem_ziel_innerhalb_erlaubt():
    erg = pruefe(neu("sub/link", b"../lib/x.py", modus="120000"))
    assert not erg.gesperrt
    assert erg.befunde[0].klasse == "sensibel"


def test_link_ohne_inhalt_ist_pruefungsfehler():
    with pytest.raises(P.PruefFehler):
        pruefe(P.Eintrag(pfad=b"l", art="neu", modus="120000", alt_modus="000000", inhalt=None))


# ---------------------------------------------------------------- Sonderdateien
def test_gitlink_gesperrt():
    erg = pruefe(P.Eintrag(pfad=b"vendor/lib", art="neu", modus="160000", alt_modus="000000", inhalt=None))
    assert "sonderdatei" in erg.befunde[0].gruende


def test_unbekannter_modus_gesperrt():
    erg = pruefe(P.Eintrag(pfad=b"x", art="neu", modus="100664", alt_modus="000000", inhalt=None))
    assert "sonderdatei" in erg.befunde[0].gruende


def test_loeschung_eines_gitlinks_erlaubt():
    erg = pruefe(geloescht("vendor/lib", alt_modus="160000"), basis=["vendor/lib"])
    assert not erg.gesperrt


def test_ungueltige_art_ist_pruefungsfehler():
    with pytest.raises(P.PruefFehler):
        pruefe(P.Eintrag(pfad=b"x", art="umbenannt", modus="100644", alt_modus="100644", inhalt=b""))


def test_doppelter_pfad_ist_pruefungsfehler():
    with pytest.raises(P.PruefFehler):
        pruefe(neu("a.txt"), neu("a.txt"))


# ---------------------------------------------------------------- Geheimnisse
@pytest.mark.parametrize("inhalt", [
    b"key = 'sk-ant-api03-" + b"A" * 40 + b"'",
    b"ghp_" + b"a" * 36,
    b"token: gho_" + b"B" * 36,
    b"ghs_" + b"c1" * 18,
    b"github_pat_" + b"x" * 82,
    b"wh1-" + b"a" * 16 + b"-" + b"b" * 64,
    b"aws AKIA" + b"IOSFODNN7EXAMPLE",  # zusammengesetzt, damit kein Schlüssel als Text in der Datei steht
    b"-----BEGIN OPENSSH " + b"PRIVATE KEY-----\nabc",
    b"-----BEGIN RSA " + b"PRIVATE KEY-----",
    b"-----BEGIN " + b"PRIVATE KEY-----",
    b"\x00\x01binaer ghp_" + b"Z" * 36 + b"\x00",
])
def test_geheimnis_muster_im_inhalt(inhalt):
    erg = pruefe(neu("src/conf.py", inhalt))
    assert erg.gesperrt
    assert "geheimnis" in erg.befunde[0].gruende
    assert all(b"ghp_" not in r.encode() and "AKIA" not in r for r in erg.befunde[0].regeln)


def test_zertifikat_ohne_schluessel_ist_kein_geheimnis():
    assert not pruefe(neu("ca.crt", b"-----BEGIN CERTIFICATE-----\nMIIB\n")).gesperrt


def test_exakter_wert_des_laufs():
    wert = b"mein-geheimer-wert-123"
    erg = pruefe(neu("notiz.txt", b"vorher " + wert + b" nachher"), geheimnisse=[wert])
    assert "geheimnis" in erg.befunde[0].gruende
    assert all(wert.decode() not in r for r in erg.befunde[0].regeln)


def test_werte_nur_der_dispatcher_kennt():
    """Werkzeuge.geheimnis_in: die Regeln sehen das Token nie, sie fragen nur, ob es in den Bytes steht (Inhalt und Pfad)."""
    gesehen = []

    def geheimnis_in(daten):
        gesehen.append(bytes(daten))
        return b"verborgen" in daten
    erg = P.pruefen([neu("a.txt", b"x verborgen y"), neu("verborgen.txt", b"x"), neu("b.txt", b"sauber")], [],
                    geheimnis_in=geheimnis_in)
    assert {b.pfad: "geheimnis" in b.gruende for b in erg.befunde} == {"a.txt": True, "verborgen.txt": True, "b.txt": False}
    assert b"sauber" in gesehen and b"b.txt" in gesehen


def test_kurze_exakte_werte_werden_ignoriert():
    assert not pruefe(neu("a.txt", b"abc"), geheimnisse=[b"abc"]).gesperrt


def test_geheimnis_im_pfad_und_im_linkziel():
    token = "ghp_" + "Q" * 36
    erg = pruefe(neu(f"docs/{token}.md"), neu("l", f"docs/{token}.md".encode(), modus="120000"))
    assert all("geheimnis" in b.gruende for b in erg.befunde)


def test_loeschungen_werden_nicht_durchsucht():
    # Eine Löschung veröffentlicht keinen neuen Inhalt; der Pfad steht schon in der Basis.
    erg = pruefe(geloescht("fixtures/ghp_" + "Q" * 36 + ".json"), basis=["fixtures/ghp_" + "Q" * 36 + ".json"])
    assert not erg.gesperrt


def test_link_innerhalb_mit_umweg_erlaubt():
    assert not pruefe(neu("sub/link", b"a/../../b", modus="120000")).gesperrt


# ---------------------------------------------------------------- Grenzen
def test_datei_am_rand_der_groesse():
    g = P.Grenzen(datei_bytes=10, gesamt_bytes=100, aenderungen=10, sensibel=5)
    assert not pruefe(neu("a", b"x" * 10), grenzen=g).gesperrt
    erg = pruefe(neu("a", b"x" * 11), grenzen=g)
    assert "zu_gross" in erg.befunde[0].gruende


def test_gesamtgroesse():
    g = P.Grenzen(datei_bytes=10, gesamt_bytes=15, aenderungen=10, sensibel=5)
    erg = pruefe(neu("a", b"x" * 8), neu("b", b"x" * 8), grenzen=g)
    assert "zu_gross" in erg.gruende


def test_zahl_der_aenderungen_am_rand():
    g = P.Grenzen(datei_bytes=10, gesamt_bytes=1000, aenderungen=3, sensibel=5)
    assert not pruefe(neu("a"), neu("b"), neu("c"), grenzen=g).gesperrt
    assert "zu_gross" in pruefe(neu("a"), neu("b"), neu("c"), neu("d"), grenzen=g).gruende


def test_ausgelassene_loeschungen_zaehlen_nicht():
    g = P.Grenzen(datei_bytes=10, gesamt_bytes=1000, aenderungen=1, sensibel=5)
    erg = pruefe(geloescht(".claude/a"), geloescht(".claude/b"), neu("c"), basis=[".claude/a", ".claude/b"], grenzen=g)
    assert not erg.gesperrt


def test_zu_viele_sensible():
    g = P.Grenzen(datei_bytes=10, gesamt_bytes=1000, aenderungen=10, sensibel=2)
    erg = pruefe(neu("a.sh"), neu("b.sh"), neu("c.sh"), grenzen=g)
    assert "zu_gross" in erg.gruende


def test_standardgrenzen_aus_dem_plan():
    g = P.Grenzen()
    assert (g.datei_bytes, g.gesamt_bytes, g.aenderungen, g.sensibel) == (5 * 1024 * 1024, 20 * 1024 * 1024, 300, 200)


# ---------------------------------------------------------------- Liste für die Karte
def test_liste_sensible_zuerst_und_vollstaendig():
    eintraege = [neu(f"src/n{i:03}.py") for i in range(250)]
    eintraege.insert(230, neu("deploy.sh"))
    erg = pruefe(*eintraege)
    liste, nicht_gelistet = P.liste_bauen(erg, zahlen={"deploy.sh": (3, 1)})
    assert len(liste) == 200
    assert liste[0] == {"pfad": "deploy.sh", "art": "neu", "klasse": "sensibel", "plus": 3, "minus": 1}
    assert nicht_gelistet == 251 - 200
    assert all(e["klasse"] == "normal" for e in liste[1:])


def test_liste_gesperrte_vor_sensiblen():
    erg = pruefe(neu("a.sh"), neu(".github/x.yml"), neu("b.txt"))
    liste, _ = P.liste_bauen(erg, zahlen={})
    assert [e["pfad"] for e in liste] == [".github/x.yml", "a.sh", "b.txt"]
    assert liste[0]["klasse"] == "sensibel"
    assert liste[0]["plus"] == 0 and liste[0]["minus"] == 0


def test_sensible_pfade_fuer_die_bestaetigung():
    erg = pruefe(neu("a.sh"), neu("b.txt"), geaendert("package.json"), basis=["package.json"])
    assert P.sensible_pfade(erg) == ["a.sh", "package.json"]


# ---------------------------------------------------------------- Blob-ID für den Abgleich
def test_blob_id_wie_git():
    # git hash-object für "hallo\n"
    assert P.blob_id(b"hallo\n") == "4cf5aa5f9a644263dbe3d6e78bcbef45487a802c"
    assert P.blob_id(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
