"""Persönlicher GitHub-Weg im Entwicklungs-Agenten (Plan C, docs/persoenliche-zugaenge.md C.2 Kern-Teil, C.6): Einhängepunkte für dev_agent.py.

DevAgent erbt GithubWeg. Alles gilt nur im Büro (pc_host.buero), mit gültiger Zulassung, mit WAMO_ENTWICKLUNG_GITHUB=an, mit einem
Dispatcher, der im ping Version 10 und "persoenlich": true meldet, für eine Auftragsart mit GitHub-Stufe und ein Repo, und nur, wenn die
Person ein nutzbares Token hinterlegt hat. Sonst bleibt alles beim App-Weg wie bisher (C8).

  * Karte vor dem Start: persoenlich_konto() entscheidet, die Karte nennt das Konto und "mit deinem GitHub-Token".
  * Start: Kopffelder github und scopes_ausnahmen (sortiert), die GitHub-Zeile nach der Claude-Zeile nur, solange der Kern für den Auftrag
    kein Ereignis github kennt; nach start_abgelehnt mit github_zeile (Exit 8) genau einmal neu mit Zeile (C.2.2).
  * Laufende: Ereignis aenderung, danach die Karte "Einreichen" (C.6).
  * Einreichen und Verwerfen nur aus den UI-Nachrichten einreichen und verwerfen, nie als Werkzeug des Sprachmodells. Für einreichen
    entschlüsselt der Kern das Token frisch und schickt es nur über stdin (Zeile 2), nie in argv, nie ins Log.
  * Ans Sprachmodell gehen nur feste Sätze; Pfade, Titel, Repo-Inhalte und Adressen nur auf Canvas und Karte.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys

from loguru import logger

import entwicklung_betrieb as eb
import github_auftrag as ga
import github_zugang as gz
import pc_host
from memory import normalize_uuid
from schluessel import schwaerzen
from werkzeugkarte import github_stufe

EINREICHEN_TIMEOUT_SECS = 180  # Push und Pull Request auf dem Server, mit Puffer
STEUER_TIMEOUT_SECS = 30  # verwerfen, aenderung


def _da():
    """Das Modul dev_agent zur Laufzeit (ssh_argv, _kill_tree und create_subprocess_exec ersetzen die Tests dort)."""
    return sys.modules["dev_agent"]


class GithubWeg:
    """Methoden des persönlichen GitHub-Wegs; DevAgent liefert _memory, _jobs, _send, _canvas, _notify, _buero_darf, _zulassung, _ping,
    _auftraggeber, _running und _running_job."""

    # ---------- Entscheidung und Karte vor dem Start ----------
    def _github_user(self) -> str | None:
        return normalize_uuid(getattr(self._memory, "user_id", None) or "")

    async def persoenlich_konto(self, art: str, repo: str | None) -> str | None:
        """Login des eigenen Tokens, wenn dieser Auftrag den persönlichen Weg nimmt, sonst None (dann gilt der App-Weg)."""
        uid = self._github_user()
        if not (pc_host.buero() and repo and uid and github_stufe(art) is not None and eb.github_an()):
            return None
        if not eb.zulassung_gueltig(self._zulassung, uid):
            return None
        try:
            await self._ping.auffrischen()
        except Exception as e:  # noqa: BLE001 (auffrischen wirft selbst nie; ein Fehler heißt App-Weg)
            logger.warning("GitHub-Weg: ping nicht möglich ({})", type(e).__name__)
        if not self._ping.github_persoenlich():
            return None
        return await gz.konto_bereit(uid)

    # ---------- Start ----------
    async def github_start_daten(self, job) -> tuple[dict, bytes | None] | None:
        """Kopffelder und (vor dem Ereignis github) die GitHub-Zeile für start; None, wenn das Token gerade nicht nutzbar ist. Ein
        abgelaufenes oder unpassendes Token setzt keinen Rückfall auf die App."""
        uid = self._github_user()
        if uid is None:
            return None
        kopf = ga.kopffelder(await gz.ausnahmen_fuer(uid))
        job.aenderung = None  # jeder Lauf meldet seinen Kandidaten neu; nie die Karte eines früheren Laufs
        if job.github_bekannt:
            return kopf, None
        zugang = await gz.github_zugang_fuer(uid)
        if zugang is None:
            return None
        try:
            return kopf, ga.github_zeile(zugang["wert"])
        except ValueError:
            logger.error("Entwicklungsauftrag {}: GitHub-Zeile nicht gebaut (Form)", job.id)
            return None
        finally:
            zugang.clear()

    def github_neu_starten(self, job, ende_code: int | None) -> bool:
        """Nach start_abgelehnt mit github_zeile (Exit 8) genau einmal je Lauf neu mit Zeile (C.2.2); nie nach dem Auflegen oder Abbruch."""
        abgelehnt = job.ereignisse.get("start_abgelehnt")
        if not job.github or job.github_neu or ende_code != 8 or not isinstance(abgelehnt, dict) or self._zu or job.beendet:
            job.github_neu = False  # gilt je Lauf: der nächste Lauf darf wieder einmal neu starten
            return False
        if abgelehnt.get("grund") != "github_zeile":
            job.github_neu = False
            return False
        job.github_neu, job.github_bekannt = True, False
        logger.info("Entwicklungsauftrag {}: GitHub-Zeile fehlte, einmal neu mit Zeile", job.id)
        return True

    def github_ereignis(self, job, name: str, ev: dict) -> bool:
        """Ereignisse github und aenderung im Datenstrom eines Laufs; True, wenn es eines davon war."""
        if not job.github:
            return False
        if name == "github":
            info = ga.github_info(ev, job.repo)
            if info is not None:
                job.github_info, job.github_bekannt = info, True
                job.steps.append(f"GitHub: {info['repo']} mit dem Konto {info['konto']} geholt, Stand {info['basis'][:12]}")
            else:
                job.steps.append("GitHub: Angaben des Servers ungültig")
            return True
        if name == "aenderung":
            aenderung = ga.aenderung_pruefen(ev, job.id, job.repo)
            if aenderung is not None:
                job.aenderung = aenderung
                job.steps.append(f"Änderung: {aenderung.status}, {aenderung.dateien} Dateien")
            return True
        return False

    async def github_nach_lauf(self, job) -> None:
        """Nach dem letzten Lauf eines Auftrags (keine weitere Runde, keine offene Freigabe): die Karte Einreichen (C.6)."""
        if not job.github or job.aenderung is None or job.weiter is not None or job.pending:
            return
        await self._einreichen_karte(job)

    async def _einreichen_karte(self, job, fehler: str | None = None) -> None:
        nachricht = ga.karte(job.id, job.projekt.name, job.aenderung, job.github_info, self._auftraggeber, fehler=fehler)
        if nachricht is not None:
            await self._send(nachricht)
        elif fehler:
            job.steps.append(f"Einreichen: {fehler}")
            await self._canvas(job)

    # ---------- Einreichen und Verwerfen (nur UI-Nachrichten) ----------
    def _github_job(self, data: dict):
        job = self._jobs.get(str(data.get("job", ""))[:100])
        if job is None or job.github != eb.GITHUB_PERSOENLICH or job.aenderung is None:
            return None
        return job

    def _laeuft(self, job) -> bool:
        return job.einreichen_laeuft or (self._running_job is job and self._running is not None and not self._running.done())

    async def einreichen(self, data: dict) -> None:
        """Klick "Einreichen" (oder "Pull Request nachholen") auf der Karte: frisches Token, einreichen <job> <profil> mit Zeile 1 und
        GitHub-Zeile über stdin, Quittung auf Canvas, Zeile in actions. Jede Abweisung kommt als Satz auf die Karte zurück. Je Auftrag
        läuft höchstens ein Einreichen oder Verwerfen zugleich: das Zeichen steht vor dem ersten await (zwei schnelle Klicks)."""
        if not self._buero_darf("einreichen"):
            return
        job = self._github_job(data)
        if job is None:
            return
        if self._laeuft(job):
            await self._einreichen_karte(job, ga.SATZ_LAEUFT)
            return
        job.einreichen_laeuft = True
        try:
            await self._einreichen_belegt(job, data)
        finally:
            job.einreichen_laeuft = False

    async def _einreichen_belegt(self, job, data: dict) -> None:
        a = job.aenderung
        if a.status not in ga.STATUS_EINREICHEN:
            await self._einreichen_karte(job, ga.SATZ_ZUSTAND)
            return
        if data.get("commit_id") != a.commit_id or data.get("tree_id") != a.tree_id:
            await self._einreichen_karte(job, ga.SATZ_VERALTET)
            return
        roh = data.get("bestaetigt")
        bestaetigt = {p for p in roh if isinstance(p, str)} if isinstance(roh, list) and len(roh) <= ga.MAX_LISTE else None
        if bestaetigt is None or not set(a.markiert) <= bestaetigt:
            await self._einreichen_karte(job, ga.SATZ_BESTAETIGUNG)
            return
        uid = self._github_user()
        # Das hinterlegte Token muss noch zum Konto des Auftrags gehören (die Karte zeigt es); sonst stünde der Pull Request unter einem
        # anderen Namen. Der Dispatcher prüft die Konto-ID zusätzlich (einreichen_fehler konto).
        konto = await gz.konto_bereit(uid) if uid else None
        if konto is None or (job.github_info and konto.casefold() != str(job.github_info.get("konto", "")).casefold()):
            await self._einreichen_karte(job, ga.SATZ_TOKEN_FEHLT if konto is None else eb.EINREICHEN_SAETZE["konto"])
            return
        zugang = await gz.github_zugang_fuer(uid)
        if zugang is None:
            await self._einreichen_karte(job, ga.SATZ_TOKEN_FEHLT)
            return
        aktion = None
        try:
            try:
                zeilen = ga.einreichen_zeile(a.commit_id, a.tree_id, list(a.markiert), await gz.ausnahmen_fuer(uid))
                zeilen += ga.github_zeile(zugang["wert"])
            finally:
                zugang.clear()
            aktion = await self._memory.log_action(
                tool=ga.WERKZEUG_EINREICHEN, params={"repo": job.repo, "zweig": a.zweig, "commit": a.commit_id, "dateien": a.dateien},
                reason="Änderung als Pull Request einreichen (Klick auf der Karte)", risk="critical")
            await self._memory.update_action(aktion, "approved")
            await self._memory.update_action(aktion, "running")
            code, ausgabe = await self._ssh_mit_eingabe(["einreichen", job.id, eb.kennung_von(uid)], zeilen, EINREICHEN_TIMEOUT_SECS)
            del zeilen
            await self._einreichen_auswerten(job, code, ausgabe, aktion)
        except Exception as e:  # noqa: BLE001 (nie bis ins Gespräch; die Karte nennt einen festen Satz)
            logger.error("Entwicklungsauftrag {}: Einreichen gescheitert ({})", job.id, type(e).__name__)
            with contextlib.suppress(Exception):
                await self._memory.update_action(aktion, "failed")
            await self._einreichen_karte(job, ga.SATZ_UNBEKANNT)

    async def _einreichen_auswerten(self, job, code: int, ausgabe: str, aktion: str | None) -> None:
        ev = ga.ereignisse(ausgabe)
        if "aenderung" in ev:  # der Dispatcher meldet den neuen Zustand mit (etwa branch_gepusht nach einem Fehler beim Pull Request)
            job.aenderung = ga.aenderung_pruefen(ev["aenderung"], job.id, job.repo) or job.aenderung
        ergebnis = ga.eingereicht_pruefen(ev.get("eingereicht"), job.id, job.repo) if code == 0 else None
        if ergebnis is not None:
            job.aenderung.status, (job.aenderung.pr, job.aenderung.adresse) = "eingereicht", ergebnis
            await self._memory.update_action(aktion, "done")
            job.steps.append(f"Eingereicht als Pull Request {ergebnis[0]}")
            logger.info("Entwicklungsauftrag {}: eingereicht (Pull Request {})", job.id, ergebnis[0])
            await self._canvas(job)
            await self._notify(f"Entwicklungsauftrag {job.projekt.name}: {ga.SATZ_EINGEREICHT} Der Link steht auf dem Canvas. "
                               f"Sag {self._auftraggeber} das in einem kurzen Satz.")
            return
        satz = ga.fehler_satz(ev.get("einreichen_fehler")) if "einreichen_fehler" in ev else ga.SATZ_UNBEKANNT
        await self._memory.update_action(aktion, "failed")
        logger.warning("Entwicklungsauftrag {}: Einreichen abgewiesen (Code {})", job.id, code)
        job.steps.append(f"Einreichen nicht möglich: {satz}")
        await self._canvas(job)
        await self._einreichen_karte(job, satz)

    async def verwerfen(self, data: dict) -> None:
        """Klick "Verwerfen" auf der Karte: verwerfen <job> <profil>. Der Projektordner bleibt (C.10), nur die Ergebnisse gehen weg. Dasselbe
        Zeichen wie beim Einreichen: nie beides zugleich."""
        if not self._buero_darf("verwerfen"):
            return
        job = self._github_job(data)
        if job is None:
            return
        if self._laeuft(job):
            await self._einreichen_karte(job, ga.SATZ_LAEUFT)
            return
        job.einreichen_laeuft = True
        try:
            await self._verwerfen_belegt(job)
        finally:
            job.einreichen_laeuft = False

    async def _verwerfen_belegt(self, job) -> None:
        if job.aenderung.status not in ga.STATUS_VERWERFEN:
            await self._einreichen_karte(job, ga.SATZ_ZUSTAND)
            return
        code, ausgabe = await self._ssh_kurz(["verwerfen", job.id, eb.kennung_von(self._github_user())], timeout=STEUER_TIMEOUT_SECS)
        ev = ga.ereignisse(ausgabe)
        weg = ev.get("verworfen")
        if code == 0 and isinstance(weg, dict) and weg.get("job") == job.id:
            job.aenderung.status = "verworfen"
            job.steps.append(ga.SATZ_VERWORFEN)
            await self._canvas(job)
            return
        satz = ga.fehler_satz(ev.get("einreichen_fehler")) if "einreichen_fehler" in ev else ga.SATZ_UNBEKANNT
        job.steps.append(f"Verwerfen nicht möglich: {satz}")
        await self._canvas(job)
        await self._einreichen_karte(job, satz)

    async def _ssh_mit_eingabe(self, args: list[str], eingabe: bytes, timeout: float) -> tuple[int, str]:
        """Dispatcher-Befehl mit Daten auf stdin (einreichen). Nie mit Werten in argv; stderr nur geschwärzt und gekürzt ins Log."""
        da = _da()
        try:
            proc = await asyncio.create_subprocess_exec(*da.ssh_argv(args), stdin=asyncio.subprocess.PIPE,
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except (OSError, RuntimeError, ValueError) as e:
            logger.error("Sokrates-2 nicht erreichbar ({})", type(e).__name__)
            return -1, ""
        try:
            out, err = await asyncio.wait_for(proc.communicate(eingabe), timeout)
        except asyncio.TimeoutError:
            await da._kill_tree(proc)
            return -1, ""
        if proc.returncode != 0:
            logger.warning("Dispatcher {}: Code {} {}", args[0], proc.returncode,
                           schwaerzen((err or b"").decode("utf-8", "replace").strip())[-300:])
        return proc.returncode, (out or b"").decode("utf-8", "replace")
