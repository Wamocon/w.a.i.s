"""Pfadregeln für Änderungen aus einem Entwicklungsauftrag mit persönlichem GitHub-Zugang (Plan C, Paket D-b).

Der Dispatcher wendet diese Regeln auf die Dateiliste und die Bytes an, die der netzlose Sandbox-Schritt `pruefung`
(wamo_job_auszug.py) nach `ergebnis/` geschrieben hat, und noch einmal auf die Pfade des fertigen Commits. Grundlage sind die
Regeln aus Folgepaket 1, 3.1.3 (docs/folgepaket-1.md), ergänzt um Plan C, C.5 Laufende 4 (docs/persoenliche-zugaenge.md):

- gesperrt: Ausführungsflächen (`.git` in jeder Schreibweise, `.gitmodules`, `.github/`, `.claude/`, `.vscode/`, `.devcontainer/`,
  `.cursor/`, `.githooks/`, `.mcp.json`), Zeichen außerhalb der Allowlist, Kollisionen, Windows-Gerätenamen, Links mit absolutem
  oder hinausführendem Ziel, Gitlinks und unbekannte Modi, Geheimnisse, Grenzen.
- sensibel: Lockfiles, Build-, CI- und Skriptdateien, `.env*`, Schlüsseldateien, Anweisungsdateien für Agenten, ausführbare und
  binäre Dateien, neue oder geänderte Links. Die Karte verlangt für sie eine Bestätigung je Pfad.
- Pfade, die die Entschärfung entfernt (`.claude/`, `.mcp.json` in der Wurzel): eine Löschung dort wird ausgelassen (es gilt der
  Eintrag der Basis), eine neue oder geänderte Datei dort ist gesperrt.

Reine Funktionen über Bytes, nur Standardbibliothek. Werte von Geheimnissen stehen nie in einem Ergebnis, nur der Name der Regel.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Sequence

# Gründe, die diese Regeln vergeben; jeder Code steht in AENDERUNG_GRUENDE (C.2.6) und hat im Kern einen Satz.
GRUND_PFAD = "pfad_gesperrt"
GRUND_GEHEIMNIS = "geheimnis"
GRUND_ZU_GROSS = "zu_gross"
GRUND_SYMLINK = "symlink"
GRUND_SONDERDATEI = "sonderdatei"
GRUENDE = (GRUND_PFAD, GRUND_GEHEIMNIS, GRUND_ZU_GROSS, GRUND_SYMLINK, GRUND_SONDERDATEI)

ARTEN = ("neu", "geaendert", "geloescht")
MODUS_LEER = "000000"
MODUS_DATEI = "100644"
MODUS_AUSFUEHRBAR = "100755"
MODUS_LINK = "120000"
MODUS_GITLINK = "160000"
MODI_INHALT = (MODUS_DATEI, MODUS_AUSFUEHRBAR, MODUS_LINK)  # die einzigen Modi, die ein Commit aus W.A.I.S. schreibt

KLASSE_NORMAL = "normal"
KLASSE_SENSIBEL = "sensibel"

MAX_PFAD_ZEICHEN = 240
MAX_LINK_BYTES = 1024
MAX_LISTE = 200  # Einträge im Ereignis aenderung
MAX_ANZEIGE = 300
BINAER_PROBE = 8000  # wie git: ein NUL-Byte in den ersten 8000 Byte heißt binär
MIN_GEHEIMNIS_BYTES = 8  # kürzere exakte Werte sind keine Schlüssel und würden Text zerstören

# Namensteile (verglichen nach NFKC, casefold, ohne angehängte Punkte und Leerzeichen), die in jeder Tiefe sperren
# Ausführungsflächen von Editoren und Agenten: Aufgaben, Hooks, MCP-Server, Startkonfigurationen (laufen beim Öffnen des Zweigs)
GESPERRT_ORDNER = frozenset({".github", ".claude", ".vscode", ".devcontainer", ".cursor", ".githooks", ".gemini", ".codex", ".windsurf",
                             ".opencode", ".zed", ".idea", ".fleet", ".continue", ".roo", ".kiro"})
GESPERRT_NAMEN = frozenset({".git", ".gitmodules", ".mcp.json", ".devcontainer.json"})
# Diese Pfade entfernt projekt_entschaerfen vor jedem Lauf in der Wurzel des Projekts (wamo_job_dispatch.py); Löschungen dort gelten
# nicht als Änderung (exakte Schreibweise, so wie die Entschärfung sie trifft).
ENTSCHAERFT_DATEIEN = frozenset({b".mcp.json", b".claude"})
ENTSCHAERFT_ORDNER = (b".claude/",)
GERAETE = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))})
ERLAUBTE_ZEICHEN = frozenset("._-+@=,()[] ")

SENSIBEL_NAMEN = frozenset({
    # Paketverwaltung und Lockfiles
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "pnpm-workspace.yaml", "bun.lock",
    "bun.lockb", "deno.json", "deno.jsonc", "deno.lock", ".npmrc", "pipfile", "pipfile.lock", "poetry.lock", "uv.lock", "pdm.lock",
    "pyproject.toml", "setup.py", "setup.cfg", "cargo.toml", "cargo.lock", "go.mod", "go.sum", "gemfile", "gemfile.lock",
    "composer.json", "composer.lock", "mix.lock", "pubspec.lock", "podfile.lock", "flake.nix", "flake.lock", "gradle.lockfile",
    # Build, Aufgaben, CI
    "makefile", "gnumakefile", "justfile", "rakefile", "build.rs", "cmakelists.txt", "build.gradle", "build.gradle.kts",
    "settings.gradle", "settings.gradle.kts", "gradlew", "pom.xml", "tox.ini", "noxfile.py", "conftest.py", "jenkinsfile",
    "vagrantfile", "procfile", "vercel.json", "netlify.toml", ".gitlab-ci.yml", "azure-pipelines.yml", ".travis.yml",
    "bitbucket-pipelines.yml", ".pre-commit-config.yaml", ".gitattributes", ".envrc", "lefthook.yml", "lefthook.yaml", ".lefthook.yml",
    "mise.toml", ".mise.toml", ".tool-versions", "taskfile.yml", "taskfile.yaml", ".bazelrc", "workspace", "workspace.bazel",
    "module.bazel", "pytest.ini", "directory.build.props", "directory.build.targets", "directory.packages.props", "nuget.config",
    "global.json", ".pnpmfile.cjs", ".yarnrc", "bunfig.toml", ".node-version", ".nvmrc", "pre-commit-config.yaml",
    # Anweisungsdateien für spätere Agenten
    "claude.md", "agents.md", "gemini.md", ".cursorrules", ".windsurfrules",
})
SENSIBEL_ORDNER = frozenset({".husky", ".circleci", ".cargo", ".mvn", ".yarn", ".gradle", ".buildkite", ".gitlab", ".config"})
SENSIBEL_PRAEFIXE = (".env", ".yarnrc", "dockerfile", "docker-compose", "compose.y", "requirements")
SENSIBEL_ENDUNGEN = (".sh", ".bash", ".zsh", ".fish", ".ps1", ".psm1", ".bat", ".cmd", ".mk", ".pem", ".key", ".p12", ".pfx",
                     ".csproj", ".fsproj", ".vbproj", ".props", ".targets", ".sln")

# Muster der Geheimnissuche über Bytes (Name der Regel, Muster). Der Name landet im Ergebnis, nie der Treffer.
GEHEIMNIS_MUSTER = (
    ("anthropic_schluessel", re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("github_token", re.compile(rb"gh[pousr]_[A-Za-z0-9_]{20,}")),
    ("github_pat", re.compile(rb"github_pat_[A-Za-z0-9_]{20,}")),
    ("haus_token", re.compile(rb"wh1-[0-9a-f]{16,32}-[0-9a-f]{64}")),
    ("aws_schluessel", re.compile(rb"(?:AKIA|ASIA)[0-9A-Z]{16}")),
    ("privater_schluessel", re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
)


class PruefFehler(ValueError):
    """Die Eingabe passt nicht zum Vertrag des Auszugs (doppelter Pfad, falsche Art, Inhalt fehlt): Grund pruefung_fehler."""


@dataclass(frozen=True)
class Grenzen:
    datei_bytes: int = 5 * 1024 * 1024
    gesamt_bytes: int = 20 * 1024 * 1024
    aenderungen: int = 300
    sensibel: int = MAX_LISTE


@dataclass(frozen=True)
class Eintrag:
    """Eine Änderung gegen die Basis. pfad sind die rohen Bytes, wie git sie speichert; inhalt sind die Bytes der neuen Datei
    oder das Ziel eines Links, None bei Löschungen und Gitlinks."""

    pfad: bytes
    art: str
    modus: str
    alt_modus: str
    inhalt: bytes | None


@dataclass(frozen=True)
class Befund:
    eintrag: Eintrag
    pfad: str  # lesbare Form ohne Steuerzeichen, für Karte und Protokoll
    klasse: str
    gruende: tuple[str, ...]
    regeln: tuple[str, ...]  # genauer Name der Regel je Treffer, ohne Wert

    @property
    def pfad_roh(self) -> bytes:
        return self.eintrag.pfad

    @property
    def art(self) -> str:
        return self.eintrag.art

    @property
    def gesperrt(self) -> bool:
        return bool(self.gruende)


@dataclass(frozen=True)
class Pruefung:
    befunde: tuple[Befund, ...]  # nur die übernommenen Änderungen, nach Pfad-Bytes sortiert
    ausgelassen: int  # Löschungen entschärfter Pfade (es gilt der Eintrag der Basis)
    gruende: tuple[str, ...] = field(default=())  # alle Gründe, sortiert und eindeutig

    @property
    def gesperrt(self) -> bool:
        return bool(self.gruende)


# ---------------------------------------------------------------- Hilfen
def blob_id(daten: bytes) -> str:
    """Objekt-ID eines Blobs wie `git hash-object` (SHA-1-Repos); der Dispatcher vergleicht sie mit der ID aus dem Auszug."""
    return hashlib.sha1(b"blob %d\x00" % len(daten) + daten).hexdigest()


def pfad_text(roh: bytes) -> str | None:
    """Strikt als UTF-8 dekodiert, None bei ungültigen Bytes."""
    try:
        return roh.decode("utf-8")
    except UnicodeDecodeError:
        return None


def pfad_anzeige(roh: bytes) -> str:
    """Lesbare Form für Karte und Protokoll: ungültige Bytes ersetzt, Steuer- und Formatzeichen als ?, gekürzt."""
    text = roh.decode("utf-8", "replace")
    text = "".join("?" if unicodedata.category(z)[0] == "C" or unicodedata.category(z) in ("Zl", "Zp") else z for z in text)
    return text if len(text) <= MAX_ANZEIGE else text[:MAX_ANZEIGE] + "…"


def _vergleich(teil: str) -> str:
    """Vergleichsform eines Namensteils: NFKC, casefold, nochmals NFKC, ohne angehängte Punkte und Leerzeichen."""
    return unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", teil).casefold()).rstrip(" .")


def _zeichen_erlaubt(z: str) -> bool:
    kategorie = unicodedata.category(z)
    return kategorie[0] in "LN" or z in ERLAUBTE_ZEICHEN


def _teil_gruende(teil: str) -> list[str]:
    """Regeln für einen Namensteil (ohne Schrägstrich)."""
    out = []
    if not teil:
        return ["leerer_teil"]
    if teil.startswith(" "):
        out.append("leerzeichen_vorne")
    if teil.endswith((" ", ".")):
        out.append("punkt_oder_leerzeichen_hinten")
    norm = _vergleich(teil)
    if norm in GESPERRT_NAMEN:
        out.append("ausfuehrungsflaeche")
    if norm.split(".", 1)[0].rstrip(" ") in GERAETE:
        out.append("geraetename")
    return out


def pfad_regeln(roh: bytes) -> list[str]:
    """Alle Regeln der Klasse gesperrt, die der Pfad allein verletzt (ohne Kollisionen und Inhalt)."""
    text = pfad_text(roh)
    if text is None:
        return ["utf8"]
    out = []
    if len(text) > MAX_PFAD_ZEICHEN:
        out.append("laenge")
    if any(not (_zeichen_erlaubt(z) or z == "/") for z in text):
        out.append("zeichen")
    if ".." in text:
        out.append("punktpunkt")
    for teil in text.split("/"):
        out.extend(_teil_gruende(teil))
        if _vergleich(teil) in GESPERRT_ORDNER:  # auch als letzter Teil: ein Link .claude -> docs/x wirkt wie der Ordner
            out.append("ausfuehrungsflaeche")
    return sorted(set(out))


def _ist_entschaerft(roh: bytes) -> bool:
    return roh in ENTSCHAERFT_DATEIEN or roh.startswith(ENTSCHAERFT_ORDNER)


def _ist_sensibel_name(text: str) -> bool:
    teile = [_vergleich(t) for t in text.split("/")]
    name = teile[-1]
    if any(t in SENSIBEL_ORDNER for t in teile[:-1]):
        return True
    return name in SENSIBEL_NAMEN or name.startswith(SENSIBEL_PRAEFIXE) or name.endswith(SENSIBEL_ENDUNGEN)


def link_regeln(pfad: str, ziel: bytes) -> list[str]:
    """Regeln für das Ziel eines Links: nur relativ, innerhalb des Repos, nie auf einen Vorfahren des Links (Schleife) und nie
    durch eine Ausführungsfläche, nur erlaubte Zeichen."""
    if not ziel or len(ziel) > MAX_LINK_BYTES:
        return ["link_laenge"]
    text = pfad_text(ziel)
    if text is None:
        return ["link_utf8"]
    if text.startswith("/"):
        return ["link_absolut"]
    teile = text.split("/")
    if any(t not in (".", "..") and (not t or any(not _zeichen_erlaubt(z) for z in t)) for t in teile):
        return ["link_zeichen"]
    stand = pfad.split("/")[:-1]
    for teil in teile:
        if teil == ".":
            continue
        if teil == "..":
            if not stand:
                return ["link_hinaus"]
            stand.pop()
            continue
        if _teil_gruende(teil) or _vergleich(teil) in GESPERRT_ORDNER:
            return ["link_flaeche"]
        stand.append(teil)
    link_teile = pfad.split("/")
    if not stand or stand == link_teile[: len(stand)]:
        return ["link_schleife"]
    return []


def geheimnis_regeln(daten: bytes, exakt: Sequence[bytes], geheimnis_in: Callable[[bytes], bool] | None = None) -> list[str]:
    """Namen der Regeln, die in daten anschlagen: Muster, exakte Werte dieses Laufs und, mit geheimnis_in, die Werte, die nur der
    Dispatcher kennt (Werkzeuge.geheimnis_in: das GitHub-Token und die Claude-Zugänge des Laufs, ohne dass dieser Code sie sieht)."""
    out = [name for name, muster in GEHEIMNIS_MUSTER if muster.search(daten)]
    if any(wert in daten for wert in exakt) or (geheimnis_in is not None and geheimnis_in(daten)):
        out.append("exakter_wert")
    return out


def _schluessel(text: str) -> tuple[str, ...]:
    return tuple(_vergleich(t) for t in text.split("/"))


# ---------------------------------------------------------------- Kollisionen im Endstand
def _endstand_konflikte(befunde_pfade: list[str], basis: Iterable[bytes], geloescht: set[bytes]) -> dict[str, list[str]]:
    """Kollisionen und Datei-Ordner-Konflikte der neuen und geänderten Pfade im Endstand (Basis ohne Löschungen plus Änderungen).
    Ergebnis: Pfad -> Namen der Regeln."""
    endstand: set[str] = set()
    for roh in basis:
        if roh not in geloescht:
            endstand.add(roh.decode("utf-8", "surrogateescape"))
    endstand.update(befunde_pfade)
    nach_schluessel: dict[tuple[str, ...], set[tuple[str, ...]]] = {}
    ordner: set[tuple[str, ...]] = set()
    for pfad in endstand:
        teile = tuple(pfad.split("/"))
        schluessel = _schluessel(pfad)
        for i in range(1, len(teile) + 1):
            nach_schluessel.setdefault(schluessel[:i], set()).add(teile[:i])
            if i < len(teile):
                ordner.add(teile[:i])
    dateien = {tuple(p.split("/")) for p in endstand}
    out: dict[str, list[str]] = {}
    for pfad in befunde_pfade:
        teile = tuple(pfad.split("/"))
        schluessel = _schluessel(pfad)
        regeln = []
        if any(len(nach_schluessel.get(schluessel[:i], ())) > 1 for i in range(1, len(teile) + 1)):
            regeln.append("kollision")
        if teile in ordner or any(teile[:i] in dateien for i in range(1, len(teile))):
            regeln.append("datei_ordner_konflikt")
        if regeln:
            out[pfad] = regeln
    return out


# ---------------------------------------------------------------- Prüfung
def _vertrag(eintraege: Sequence[Eintrag]) -> None:
    gesehen: set[bytes] = set()
    for e in eintraege:
        if not isinstance(e, Eintrag) or not isinstance(e.pfad, bytes) or not e.pfad:
            raise PruefFehler("Eintrag ungültig")
        if e.pfad in gesehen:
            raise PruefFehler("Pfad doppelt")
        gesehen.add(e.pfad)
        if e.art not in ARTEN or not isinstance(e.modus, str) or not isinstance(e.alt_modus, str):
            raise PruefFehler("Art oder Modus ungültig")
        if e.art == "geloescht":
            if e.modus != MODUS_LEER or e.alt_modus == MODUS_LEER or e.inhalt is not None:
                raise PruefFehler("Löschung ungültig")
        elif e.art == "neu" and e.alt_modus != MODUS_LEER:
            raise PruefFehler("neue Datei mit altem Modus")
        elif e.art == "geaendert" and e.alt_modus == MODUS_LEER:
            raise PruefFehler("Änderung ohne alten Modus")
        if e.art != "geloescht":
            hat_inhalt = isinstance(e.inhalt, bytes)
            if e.modus in MODI_INHALT and not hat_inhalt:
                raise PruefFehler("Inhalt fehlt")
            if e.modus not in MODI_INHALT and e.inhalt is not None:
                raise PruefFehler("Inhalt ohne Datei")


def _eintrag_regeln(e: Eintrag, text: str, exakt: Sequence[bytes], grenzen: Grenzen,
                    geheimnis_in: Callable[[bytes], bool] | None) -> tuple[list[str], list[str], bool]:
    """(Gründe, Regeln, sensibel) einer neuen oder geänderten Datei ohne Kollisionen."""
    gruende: list[str] = []
    regeln: list[str] = []
    sensibel = False
    if e.modus not in MODI_INHALT:
        gruende.append(GRUND_SONDERDATEI)
        regeln.append("gitlink" if e.modus == MODUS_GITLINK else "modus")
        return gruende, regeln, sensibel
    inhalt = e.inhalt or b""
    if e.modus == MODUS_LINK:
        sensibel = True
        link = link_regeln(text, inhalt)
        if link:
            gruende.append(GRUND_SYMLINK)
            regeln.extend(link)
    elif e.modus == MODUS_AUSFUEHRBAR:
        sensibel = True
    if len(inhalt) > grenzen.datei_bytes:
        gruende.append(GRUND_ZU_GROSS)
        regeln.append("datei_groesse")
    if e.modus != MODUS_LINK and b"\x00" in inhalt[:BINAER_PROBE]:
        sensibel = True
    treffer = geheimnis_regeln(inhalt, exakt, geheimnis_in) + geheimnis_regeln(e.pfad, exakt, geheimnis_in)
    if treffer:
        gruende.append(GRUND_GEHEIMNIS)
        regeln.extend(f"geheimnis:{t}" for t in sorted(set(treffer)))
    return gruende, regeln, sensibel


def pruefen(eintraege: Sequence[Eintrag], basis_pfade: Iterable[bytes], *, geheimnisse: Iterable[bytes] = (),
            geheimnis_in: Callable[[bytes], bool] | None = None, grenzen: Grenzen = Grenzen()) -> Pruefung:
    """Wendet alle Regeln auf die Änderungen gegen die Basis an. basis_pfade sind die Pfade des Basis-Trees (rohe Bytes, aus dem
    eigenen basis.git des Dispatchers), geheimnisse die exakten Werte dieses Laufs, geheimnis_in die Suche des Dispatchers nach den
    Werten, die nur er kennt. Wirft PruefFehler bei einer Eingabe außerhalb des Vertrags (fail-closed: Grund pruefung_fehler)."""
    _vertrag(eintraege)
    exakt = [w for w in geheimnisse if isinstance(w, bytes) and len(w) >= MIN_GEHEIMNIS_BYTES]
    basis = list(basis_pfade)
    uebernommen = sorted((e for e in eintraege if not (e.art == "geloescht" and _ist_entschaerft(e.pfad))), key=lambda e: e.pfad)
    ausgelassen = len(eintraege) - len(uebernommen)
    geloescht = {e.pfad for e in uebernommen if e.art == "geloescht"}
    texte = {e.pfad: pfad_text(e.pfad) for e in uebernommen}
    gueltige = [texte[e.pfad] for e in uebernommen if e.art != "geloescht" and texte[e.pfad] is not None]
    konflikte = _endstand_konflikte(gueltige, basis, geloescht)

    befunde = []
    for e in uebernommen:
        text = texte[e.pfad]
        gruende: list[str] = []
        regeln = pfad_regeln(e.pfad)
        if regeln:
            gruende.append(GRUND_PFAD)
        sensibel = text is not None and _ist_sensibel_name(text)
        if e.art != "geloescht":
            if text is not None and text in konflikte:
                gruende.append(GRUND_PFAD)
                regeln = regeln + konflikte[text]
            g, r, s = _eintrag_regeln(e, text or "", exakt, grenzen, geheimnis_in)
            gruende.extend(g)
            regeln = regeln + r
            sensibel = sensibel or s
        klasse = KLASSE_SENSIBEL if sensibel or gruende else KLASSE_NORMAL
        befunde.append(Befund(eintrag=e, pfad=pfad_anzeige(e.pfad), klasse=klasse, gruende=tuple(sorted(set(gruende))),
                              regeln=tuple(regeln)))

    alle = {g for b in befunde for g in b.gruende}
    if len(befunde) > grenzen.aenderungen:
        alle.add(GRUND_ZU_GROSS)
    if sum(len(b.eintrag.inhalt or b"") for b in befunde) > grenzen.gesamt_bytes:
        alle.add(GRUND_ZU_GROSS)
    if sum(1 for b in befunde if b.klasse == KLASSE_SENSIBEL) > grenzen.sensibel:
        alle.add(GRUND_ZU_GROSS)
    return Pruefung(befunde=tuple(befunde), ausgelassen=ausgelassen, gruende=tuple(sorted(alle)))


# ---------------------------------------------------------------- Karte
def _rang(b: Befund) -> int:
    if b.gesperrt:
        return 0
    return 1 if b.klasse == KLASSE_SENSIBEL else 2


def liste_bauen(pruefung: Pruefung, zahlen: Mapping[str, tuple[int, int]],
                hoechstens: int = MAX_LISTE) -> tuple[list[dict], int]:
    """Liste für das Ereignis aenderung: gesperrte und sensible Einträge vollständig und zuerst, danach normale bis zu hoechstens
    Einträgen. zahlen: lesbarer Pfad -> (plus, minus) aus `git diff-tree --numstat` des Dispatchers (Binärdateien fehlen, also 0).
    Ergebnis: (Liste, Zahl der normalen Einträge ohne Platz)."""
    geordnet = sorted(pruefung.befunde, key=lambda b: (_rang(b), b.pfad_roh))
    liste: list[dict] = []
    nicht_gelistet = 0
    for b in geordnet:
        if _rang(b) == 2 and len(liste) >= hoechstens:
            nicht_gelistet += 1
            continue
        plus, minus = zahlen.get(b.pfad, (0, 0))
        liste.append({"pfad": b.pfad, "art": b.art, "klasse": b.klasse, "plus": int(plus), "minus": int(minus)})
    return liste, nicht_gelistet


def sensible_pfade(pruefung: Pruefung) -> list[str]:
    """Die Pfade, die die Person auf der Karte einzeln bestätigen muss (Feld markiert, Prüfung von bestaetigt)."""
    return [b.pfad for b in pruefung.befunde if b.klasse == KLASSE_SENSIBEL]
