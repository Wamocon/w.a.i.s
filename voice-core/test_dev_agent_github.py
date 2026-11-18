"""Tests des persönlichen GitHub-Wegs im Entwicklungs-Agenten (dev_agent_github.py, github_auftrag.py; Plan C, C.2 Kern-Teil, C.6, C.7).

Büro-Kern wie in test_entwicklung_betrieb.BueroFlow, ssh gemockt. Geprüft: Kopffeld nur mit Schalter, Dispatcher 10 und nutzbarem Token,
GitHub-Zeile nach der Claude-Zeile nur bis zum Ereignis github, Neustart nach github_zeile, Token nie in argv, Log oder Nachrichten,
Karte aus dem Ereignis aenderung, Einreichen und Verwerfen nur aus der UI-Nachricht, frisches Token, geprüfte Adresse, nichts davon ans
Sprachmodell. Den echten Weg prüft der Rauchtest auf Sokrates-2 (Paket R)."""

from __future__ import annotations

import asyncio
import json
import os
from unittest import mock

from loguru import logger

import abnahme_remote
import dev_agent
import dev_agent_github
import entwicklung_betrieb as eb
import github_auftrag as ga
import test_entwicklung_betrieb as tb

TOKEN = "ghp_" + "Tk9" * 12
ANDERES_TOKEN = "github_pat_" + "Zz7_" * 20 + "Q1"
COMMIT, TREE, BASIS = "a" * 40, "b" * 40, "c" * 40
PING_10 = {"ok": True, "version": "10", "persoenlich": True}


def ereignis(name: str, **felder) -> dict:
    return {"type": "wamo", "ereignis": name, **felder}


def aenderung_ev(job: str, status: str = "bereit", **felder) -> dict:
    daten = {"job": job, "status": status, "commit_id": COMMIT, "tree_id": TREE, "basis": BASIS, "zweig": f"wamo/{job}",
             "dateien": 2, "plus": 10, "minus": 3, "liste": [
                 {"pfad": "package.json", "art": "geaendert", "klasse": "sensibel", "plus": 1, "minus": 1},
                 {"pfad": "src/app.ts", "art": "neu", "klasse": "normal", "plus": 9, "minus": 2}],
             "nicht_gelistet": 0, "gruende": [], "ungesichert": 0, "lauf": "fertig", "titel": "Rezepte anlegen"}
    daten.update(felder)
    return ereignis("aenderung", **daten)


class GithubFlow(tb.BueroFlow):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        sk = self.sk
        self.ping_antwort = dict(PING_10)
        self.einreichen_ausgabe: list = []
        self.einreichen_rc = 0
        self.verwerfen_ausgabe: list = [ereignis("verworfen", job="")]
        self.eingaben: dict[str, bytes] = {}
        self.ausnahmen = ("workflow", "gist")
        self.konto = "person-eins"
        self.zugang_wert = TOKEN
        self.einreichen_tor: asyncio.Event | None = None  # gesetzt: der Aufruf einreichen wartet, bis der Test ihn freigibt
        self.zeichen_beim_ersten_await: list[bool] = []

        class MitEingabe(sk.FakeProc):
            def __init__(self, test, befehl, *a, **kw):
                super().__init__(*a, **kw)
                self._test, self._befehl = test, befehl

            async def communicate(self, input=None):
                self._test.eingaben[self._befehl] = input or b""
                if self._test.einreichen_tor is not None:
                    await self._test.einreichen_tor.wait()
                return await super().communicate(input)

        async def fake_exec(*argv, **kwargs):
            self.calls.append(list(argv))
            befehl = argv[-1].split(" ")[0]
            if befehl == "start":
                return self.start_procs.pop(0)
            if befehl == "ping":
                return sk.FakeProc([self.ping_antwort])
            if befehl == "pending":
                return sk.FakeProc(self.pending_lines, returncode=0)
            if befehl == "einreichen":
                return MitEingabe(self, "einreichen", self.einreichen_ausgabe, returncode=self.einreichen_rc)
            if befehl == "verwerfen":
                return sk.FakeProc(self.verwerfen_ausgabe)
            return sk.FakeProc([{"ok": True}])

        self.patches[2].stop()
        self.patches[2] = mock.patch.object(dev_agent.asyncio, "create_subprocess_exec", side_effect=fake_exec)
        self.patches[2].start()

        async def konto_bereit(uid):
            self.zeichen_beim_ersten_await.extend(j.einreichen_laeuft for j in self.agent._jobs.values() if j.aenderung is not None)
            return self.konto

        async def zugang_fuer(uid):
            return {"typ": "github", "wert": self.zugang_wert} if self.zugang_wert else None

        async def ausnahmen_fuer(uid):
            return self.ausnahmen

        for name, ersatz in (("konto_bereit", konto_bereit), ("github_zugang_fuer", zugang_fuer), ("ausnahmen_fuer", ausnahmen_fuer)):
            p = mock.patch.object(dev_agent_github.gz, name, side_effect=ersatz)
            p.start()
            self.patches.append(p)
        self.schalter = mock.patch.dict(os.environ, {"WAMO_ENTWICKLUNG_GITHUB": "an"})
        self.schalter.start()
        self.agent = self.neuer_agent()
        self.log: list[str] = []
        self.senke = logger.add(lambda m: self.log.append(str(m)), level="DEBUG")

    async def asyncTearDown(self):
        logger.remove(self.senke)
        self.schalter.stop()
        await super().asyncTearDown()

    def neuer_agent(self, memory=None, zulassung=None):
        ping = abnahme_remote.DispatcherPing(lambda a: dev_agent.ssh_argv(a), beenden=lambda p: dev_agent._kill_tree(p))
        agent = dev_agent.DevAgent(memory=memory or self.memory, auftraggeber="Niko", zulassung=zulassung or eb.BueroZulassung(tb.NIKO),
                                   dispatcher_ping=ping)
        agent.attach(self.task)
        return agent

    async def karte(self, **argumente):
        ergebnis = await self.vorbereiten(self.agent, art="umsetzung", **argumente)
        self.assertTrue(ergebnis["ok"], ergebnis)
        return self.agent._jobs[ergebnis["auftrag_id"]]

    async def starten(self, job, *procs):
        self.start_procs.extend(procs)
        await self.agent.on_client_message("auftrag_start", {"job": job.id, "entscheidung": "ja"})
        await self.agent._running

    def stream_mit_aenderung(self, job, **felder):
        return [ereignis("github", repo="acme/testrepo", konto="person-eins", basis=BASIS, standardzweig="main", privat=True,
                         schreiben=True),
                ereignis("selbsttest_ok"), ereignis("gestartet"),
                {"type": "result", "result": "Erledigt.", "total_cost_usd": 0.1},
                aenderung_ev(job.id, **felder), ereignis("ende", ergebnis="fertig", code=0)]

    def stdin_zeilen(self, proc) -> list[bytes]:
        return proc.stdin.data.split(b"\n")[:-1]

    def nachrichten(self, typ: str) -> list[dict]:
        return [m for m in self.task.messages() if m.get("type") == typ]

    def nirgends_das_token(self):
        alles = json.dumps(self.task.messages(), default=str) + json.dumps(self.task.llm_texts()) + "\n".join(self.log)
        alles += json.dumps(self.calls) + json.dumps(self.memory.zeilen, default=str)
        for wert in (TOKEN, ANDERES_TOKEN):
            self.assertNotIn(wert, alles)
            self.assertNotIn(wert[4:24], alles)


class KarteUndStartTests(GithubFlow):
    async def test_karte_nennt_konto_und_den_eigenen_weg(self):
        job = await self.karte()
        self.assertEqual((job.github, job.github_konto), (eb.GITHUB_PERSOENLICH, "person-eins"))
        karte = self.nachrichten("auftrag")[-1]
        self.assertEqual(karte["github"], {"konto": "person-eins", "hinweis": "mit deinem GitHub-Token"})
        self.assertEqual(self.remote("ping"), ["ping"])

    async def test_ohne_dispatcher_10_schalter_oder_token_gilt_der_app_weg(self):
        for name, aendern in (("version 9", lambda: self.ping_antwort.update(version="9")),
                              ("ohne persoenlich", lambda: self.ping_antwort.pop("persoenlich")),
                              ("kein token", lambda: setattr(self, "konto", None))):
            with self.subTest(name=name):
                self.ping_antwort, self.konto = dict(PING_10), "person-eins"
                aendern()
                self.agent = self.neuer_agent()
                job = await self.karte()
                self.assertIsNone(job.github)
                self.assertNotIn("github", self.nachrichten("auftrag")[-1])
        with mock.patch.dict(os.environ, {"WAMO_ENTWICKLUNG_GITHUB": "aus"}):
            self.agent = self.neuer_agent()
            vorher = len(self.remote("ping"))
            job = await self.karte()
            self.assertIsNone(job.github)
            self.assertEqual(len(self.remote("ping")), vorher)  # ohne Schalter fragt der Kern nicht einmal

    async def test_mitglied_bekommt_ein_repo_nur_mit_eigenem_token(self):
        mitglied = tb.AuditMemory(user_id=tb.ANDERE)
        with tb.buero(WAMO_ENTWICKLUNG_PROFILE=f"{tb.NIKO},{tb.ANDERE}", WAMO_ENTWICKLUNG_MITGLIEDER="an"):
            self.agent = self.neuer_agent(memory=mitglied, zulassung=eb.BueroZulassung(tb.ANDERE, mitglied=True))
            job = await self.karte()
            self.assertEqual(job.github, eb.GITHUB_PERSOENLICH)
            self.konto = None
            ergebnis = await self.vorbereiten(self.agent, art="umsetzung")
            self.assertFalse(ergebnis["ok"])
            self.assertEqual(ergebnis["fehler"], eb.SATZ_MITGLIED_REPO)

    async def test_start_mit_kopffeldern_und_github_zeile_nach_der_claude_zeile(self):
        job = await self.karte()
        proc = self.sk.FakeProc(self.stream_mit_aenderung(job))
        await self.starten(job, proc)
        zeilen = self.stdin_zeilen(proc)
        kopf = json.loads(zeilen[0])
        self.assertEqual(kopf[eb.FELD_GITHUB], eb.GITHUB_PERSOENLICH)
        self.assertEqual(kopf[eb.FELD_SCOPES_AUSNAHMEN], ["gist", "workflow"])  # sortiert (C.2.8)
        self.assertEqual(kopf["repo"], "acme/testrepo")
        self.assertEqual(json.loads(zeilen[1])["typ"], "api")  # Claude-Zeile zuerst
        self.assertEqual(zeilen[2], b'{"typ":"github","wert":"' + TOKEN.encode() + b'"}')  # genau diese Form
        self.assertEqual(len(zeilen), 3)
        self.assertTrue(job.github_bekannt)
        self.assertEqual(job.github_info["konto"], "person-eins")
        self.nirgends_das_token()

    async def test_folgelauf_ohne_github_zeile(self):
        job = await self.karte()
        job.github_bekannt = True
        self.assertEqual(await self.agent.github_start_daten(job), (ga.kopffelder(self.ausnahmen), None))

    async def test_neustart_nach_github_zeile(self):
        job = await self.karte()
        job.github_bekannt = True  # der Kern glaubt den Klon vorhanden, der Server hat ihn nicht mehr
        erster = self.sk.FakeProc([ereignis("start_abgelehnt", grund="github_zeile")], returncode=8)
        zweiter = self.sk.FakeProc(self.stream_mit_aenderung(job))
        await self.starten(job, erster, zweiter)
        self.assertEqual(len(self.remote("start")), 2)
        self.assertEqual(len(self.stdin_zeilen(erster)), 2)  # ohne GitHub-Zeile
        self.assertEqual(self.stdin_zeilen(zweiter)[2][:24], b'{"typ":"github","wert":"')
        quittungen = self.nachrichten("auftrag_quittung")
        self.assertEqual([q["ok"] for q in quittungen], [True])  # keine Absage für den ersten Versuch
        self.assertFalse(job.github_neu)  # gilt je Lauf

    async def test_neustart_nur_einmal_je_lauf(self):
        job = await self.karte()
        job.github_bekannt = True
        procs = [self.sk.FakeProc([ereignis("start_abgelehnt", grund="github_zeile")], returncode=8) for _ in range(3)]
        await self.starten(job, *procs)
        self.assertEqual(len(self.remote("start")), 2)  # erster Versuch und genau ein Neustart
        self.assertEqual(self.nachrichten("auftrag_quittung")[-1]["grund"], eb.GITHUB_SAETZE["github_zeile"])
        self.assertFalse(job.github_neu)

    async def test_kein_neustart_nach_dem_auflegen(self):
        job = await self.karte()
        job.ereignisse = {"start_abgelehnt": {"grund": "github_zeile"}}
        self.agent._zu = True
        self.assertFalse(self.agent.github_neu_starten(job, 8))
        self.agent._zu = False
        job.beendet = True
        self.assertFalse(self.agent.github_neu_starten(job, 8))

    async def test_jeder_lauf_vergisst_die_alte_aenderung(self):
        job = await self.karte()
        job.aenderung = ga.aenderung_pruefen(aenderung_ev(job.id), job.id, job.repo)
        await self.agent.github_start_daten(job)
        self.assertIsNone(job.aenderung)

    async def test_ohne_nutzbares_token_kein_start_und_kein_rueckfall(self):
        job = await self.karte()
        self.zugang_wert = None
        await self.agent.on_client_message("auftrag_start", {"job": job.id, "entscheidung": "ja"})
        await self.agent._running
        self.assertEqual(self.remote("start"), [])
        self.assertEqual(self.nachrichten("auftrag_quittung")[-1]["grund"], ga.SATZ_TOKEN_FEHLT)

    async def test_start_abgelehnt_mit_satz_aus_der_schnittstelle(self):
        job = await self.karte()
        await self.starten(job, self.sk.FakeProc([ereignis("start_abgelehnt", grund="eigenes_repo")], returncode=8))
        self.assertEqual(self.nachrichten("auftrag_quittung")[-1]["grund"], eb.GITHUB_SAETZE["eigenes_repo"])
        self.assertIn(f"Start abgelehnt: {eb.GITHUB_SAETZE['eigenes_repo']}", job.steps)


class EinreichenTests(GithubFlow):
    async def bereit(self, **felder):
        job = await self.karte()
        await self.starten(job, self.sk.FakeProc(self.stream_mit_aenderung(job, **felder)))
        return job

    async def test_karte_aus_dem_ereignis_aenderung(self):
        job = await self.bereit()
        karte = self.nachrichten("freigaben")[-1]
        punkt = karte["items"][0]
        self.assertEqual(punkt["id"], ga.KARTE_ID)
        e = punkt["einreichen"]
        self.assertEqual((e["repo"], e["privat"], e["zweig"], e["konto"]), ("acme/testrepo", True, f"wamo/{job.id}", "person-eins"))
        self.assertEqual((e["commit_id"], e["tree_id"], e["markiert"], e["status"]), (COMMIT, TREE, ["package.json"], "bereit"))
        self.assertFalse(e["nachholen"])
        llm = " ".join(self.task.llm_texts())
        for privat in ("package.json", "Rezepte anlegen", "acme/testrepo"):
            self.assertNotIn(privat, llm)  # Pfade, Titel und Repo nie ans Sprachmodell

    async def test_einreichen_mit_frischem_token_nur_ueber_stdin(self):
        job = await self.bereit()
        self.zugang_wert = ANDERES_TOKEN  # frisch entschlüsselt: gilt der heutige Wert
        self.einreichen_ausgabe = [ereignis("eingereicht", job=job.id, zweig=f"wamo/{job.id}", pr=7,
                                            adresse="https://github.com/acme/testrepo/pull/7")]
        await self.agent.on_client_message("einreichen", {"job": job.id, "commit_id": COMMIT, "tree_id": TREE,
                                                          "bestaetigt": ["package.json"]})
        self.assertEqual(self.remote("einreichen"), [f"einreichen {job.id} {eb.kennung_von(tb.NIKO)}"])
        zeile1, zeile2, rest = self.eingaben["einreichen"].split(b"\n")
        self.assertEqual(json.loads(zeile1), {"commit_id": COMMIT, "tree_id": TREE, "bestaetigt": ["package.json"],
                                              "scopes_ausnahmen": ["gist", "workflow"]})
        self.assertEqual(zeile2, b'{"typ":"github","wert":"' + ANDERES_TOKEN.encode() + b'"}')
        self.assertEqual(rest, b"")
        self.assertEqual((job.aenderung.status, job.aenderung.pr), ("eingereicht", 7))
        zeile = next(z for z in self.memory.zeilen.values() if z["tool"] == ga.WERKZEUG_EINREICHEN)
        self.assertEqual((zeile["status"], zeile["params"]["repo"], zeile["params"]["commit"]), ("done", "acme/testrepo", COMMIT))
        canvas = self.nachrichten("canvas")[-1]["item"]["text"]
        self.assertIn("https://github.com/acme/testrepo/pull/7", canvas)
        llm = " ".join(self.task.llm_texts())
        self.assertIn(ga.SATZ_EINGEREICHT, llm)
        self.assertNotIn("pull/7", llm)
        self.nirgends_das_token()

    async def test_einreichen_wird_vorher_abgewiesen(self):
        job = await self.bereit()
        for daten, satz in (({"commit_id": "d" * 40, "tree_id": TREE, "bestaetigt": ["package.json"]}, ga.SATZ_VERALTET),
                            ({"commit_id": COMMIT, "tree_id": TREE, "bestaetigt": []}, ga.SATZ_BESTAETIGUNG),
                            ({"commit_id": COMMIT, "tree_id": TREE, "bestaetigt": "package.json"}, ga.SATZ_BESTAETIGUNG)):
            with self.subTest(satz=satz):
                await self.agent.on_client_message("einreichen", {"job": job.id, **daten})
                self.assertEqual(self.nachrichten("freigaben")[-1]["items"][0]["einreichen"]["fehler"], satz)
        self.zugang_wert = None
        await self.agent.on_client_message("einreichen", {"job": job.id, "commit_id": COMMIT, "tree_id": TREE,
                                                          "bestaetigt": ["package.json"]})
        self.assertEqual(self.nachrichten("freigaben")[-1]["items"][0]["einreichen"]["fehler"], ga.SATZ_TOKEN_FEHLT)
        self.assertEqual(self.remote("einreichen"), [])

    async def test_zwei_schnelle_klicks_reichen_nur_einmal_ein(self):
        """Deterministisch, ohne Wettlauf der Ereignisschleife: der erste Klick hängt im Aufruf einreichen fest (Tor), während zweiter Klick
        und Verwerfen kommen. Beide bekommen den Satz "läuft schon", erst nach dem Tor endet der erste."""
        job = await self.bereit()
        self.einreichen_ausgabe = [ereignis("eingereicht", job=job.id, zweig=f"wamo/{job.id}", pr=7,
                                            adresse="https://github.com/acme/testrepo/pull/7")]
        daten = {"job": job.id, "commit_id": COMMIT, "tree_id": TREE, "bestaetigt": ["package.json"]}
        self.einreichen_tor = asyncio.Event()
        erster = asyncio.create_task(self.agent.on_client_message("einreichen", daten))
        await self.warte_auf(lambda: "einreichen" in self.eingaben, "erster Klick am Dispatcher")
        self.assertTrue(job.einreichen_laeuft)
        vorher = len(self.nachrichten("freigaben"))
        await self.agent.on_client_message("einreichen", dict(daten))
        await self.agent.on_client_message("verwerfen", {"job": job.id})
        neu = [m["items"][0]["einreichen"].get("fehler") for m in self.nachrichten("freigaben")[vorher:]]
        self.assertEqual(neu, [ga.SATZ_LAEUFT, ga.SATZ_LAEUFT])
        self.einreichen_tor.set()
        await erster
        self.assertEqual(len(self.remote("einreichen")), 1)
        self.assertEqual(self.remote("verwerfen"), [])
        self.assertEqual(job.aenderung.status, "eingereicht")
        self.assertFalse(job.einreichen_laeuft)

    async def test_das_zeichen_steht_vor_dem_ersten_await(self):
        """Die Sperre ist dicht, auch wenn die Ereignisschleife nie zwischen zwei Klicks wechselt: einreichen_laeuft ist schon gesetzt, wenn
        das erste await (Abgleich des Kontos) läuft, und nach dem Ende wieder frei."""
        job = await self.bereit()
        self.einreichen_ausgabe = [ereignis("eingereicht", job=job.id, zweig=f"wamo/{job.id}", pr=7,
                                            adresse="https://github.com/acme/testrepo/pull/7")]
        await self.agent.on_client_message("einreichen", {"job": job.id, "commit_id": COMMIT, "tree_id": TREE,
                                                          "bestaetigt": ["package.json"]})
        self.assertEqual(self.zeichen_beim_ersten_await, [True])
        self.assertFalse(job.einreichen_laeuft)

    async def test_token_eines_anderen_kontos_reicht_nicht_ein(self):
        job = await self.bereit()
        self.konto = "anderes-konto"
        await self.agent.on_client_message("einreichen", {"job": job.id, "commit_id": COMMIT, "tree_id": TREE,
                                                          "bestaetigt": ["package.json"]})
        self.assertEqual(self.nachrichten("freigaben")[-1]["items"][0]["einreichen"]["fehler"], eb.EINREICHEN_SAETZE["konto"])
        self.assertEqual(self.remote("einreichen"), [])
        self.konto = "Person-Eins"  # GitHub-Logins unterscheiden nicht nach Groß und Klein
        self.einreichen_ausgabe = [ereignis("eingereicht", job=job.id, zweig=f"wamo/{job.id}", pr=8,
                                            adresse="https://github.com/Acme/TestRepo/pull/8")]
        await self.agent.on_client_message("einreichen", {"job": job.id, "commit_id": COMMIT, "tree_id": TREE,
                                                          "bestaetigt": ["package.json"]})
        self.assertEqual((job.aenderung.status, job.aenderung.pr), ("eingereicht", 8))

    async def test_fehler_des_dispatchers_und_ungepruefte_adresse(self):
        job = await self.bereit()
        self.einreichen_rc = 2
        self.einreichen_ausgabe = [ereignis("einreichen_fehler", job=job.id, grund="zweig_belegt")]
        daten = {"job": job.id, "commit_id": COMMIT, "tree_id": TREE, "bestaetigt": ["package.json"]}
        await self.agent.on_client_message("einreichen", daten)
        self.assertEqual(self.nachrichten("freigaben")[-1]["items"][0]["einreichen"]["fehler"], eb.EINREICHEN_SAETZE["zweig_belegt"])
        self.assertEqual([z["status"] for z in self.memory.zeilen.values() if z["tool"] == ga.WERKZEUG_EINREICHEN], ["failed"])
        self.einreichen_rc = 0
        self.einreichen_ausgabe = [ereignis("eingereicht", job=job.id, zweig=f"wamo/{job.id}", pr=7,
                                            adresse="https://github.com/fremd/repo/pull/7")]
        await self.agent.on_client_message("einreichen", daten)
        self.assertEqual(job.aenderung.status, "bereit")
        self.assertEqual(self.nachrichten("freigaben")[-1]["items"][0]["einreichen"]["fehler"], ga.SATZ_UNBEKANNT)

    async def test_pull_request_nachholen_nach_branch_gepusht(self):
        job = await self.bereit()
        self.einreichen_rc = 2
        self.einreichen_ausgabe = [aenderung_ev(job.id, status="branch_gepusht"),
                                   ereignis("einreichen_fehler", job=job.id, grund="github_fehler")]
        daten = {"job": job.id, "commit_id": COMMIT, "tree_id": TREE, "bestaetigt": ["package.json"]}
        await self.agent.on_client_message("einreichen", daten)
        e = self.nachrichten("freigaben")[-1]["items"][0]
        self.assertEqual((e["grund"], e["einreichen"]["nachholen"], e["einreichen"]["status"]),
                         ("Pull Request nachholen", True, "branch_gepusht"))

    async def test_gesperrte_aenderung_nur_verwerfen(self):
        job = await self.bereit(status="gesperrt", gruende=["geheimnis", "unbekannt"])
        e = self.nachrichten("freigaben")[-1]["items"][0]["einreichen"]
        self.assertEqual(e["gesperrt"], [eb.AENDERUNG_SAETZE["geheimnis"]])
        await self.agent.on_client_message("einreichen", {"job": job.id, "commit_id": COMMIT, "tree_id": TREE,
                                                          "bestaetigt": ["package.json"]})
        self.assertEqual(self.remote("einreichen"), [])
        self.verwerfen_ausgabe = [ereignis("verworfen", job=job.id)]
        await self.agent.on_client_message("verwerfen", {"job": job.id})
        self.assertEqual(self.remote("verwerfen"), [f"verwerfen {job.id} {eb.kennung_von(tb.NIKO)}"])
        self.assertEqual(job.aenderung.status, "verworfen")

    async def test_nie_als_werkzeug_des_sprachmodells(self):
        namen = {s.name for s in self.agent.schemas()}
        self.assertFalse({"einreichen", "verwerfen", "auftrag_einreichen"} & namen)
        self.assertFalse([n for n in namen if "einreich" in n or "github" in n])

    async def test_fremder_oder_unbekannter_auftrag_bleibt_ohne_wirkung(self):
        await self.bereit()
        await self.agent.on_client_message("einreichen", {"job": "f" * 16, "commit_id": COMMIT, "tree_id": TREE, "bestaetigt": []})
        await self.agent.on_client_message("verwerfen", {"job": "f" * 16})
        self.assertEqual(self.remote("einreichen") + self.remote("verwerfen"), [])


class AuftragHilfenTests(GithubFlow):
    async def test_aenderung_pruefen_verlangt_job_zweig_und_ids(self):
        self.assertIsNone(ga.aenderung_pruefen({"job": "y"}, "x", "a/b"))
        ev = aenderung_ev("j1")
        self.assertIsNotNone(ga.aenderung_pruefen(ev, "j1", "a/b"))
        for kaputt in ({"zweig": "main"}, {"status": "fertig"}, {"commit_id": "kurz"}, {"job": "j2"}):
            with self.subTest(kaputt=kaputt):
                self.assertIsNone(ga.aenderung_pruefen({**ev, **kaputt}, "j1", "a/b"))
        a = ga.aenderung_pruefen({**ev, "liste": [{"pfad": "a\u202eb", "art": "neu", "klasse": "sensibel"}] * 300}, "j1", "a/b")
        self.assertEqual(a.markiert, ["a b"])

    async def test_adresse_nur_fuer_genau_dieses_repo(self):
        self.assertEqual(ga.adresse_ok("https://github.com/a/b/pull/3", "a/b"), "https://github.com/a/b/pull/3")
        for falsch in ("https://github.com/a/b/pull/3#x", "http://github.com/a/b/pull/3", "https://github.com/a/bc/pull/3",
                       "https://github.com/a/b/pull/x", "https://evil.example/a/b/pull/3"):
            self.assertIsNone(ga.adresse_ok(falsch, "a/b"), falsch)

    async def test_zeilen_haben_feste_formen(self):
        with self.assertRaises(ValueError) as info:
            ga.github_zeile("ghp_kurz")
        self.assertNotIn("ghp_kurz", str(info.exception))
        with self.assertRaises(ValueError):
            ga.einreichen_zeile("x", TREE, [], ())
        zeile = ga.einreichen_zeile(COMMIT, TREE, ["b", "a", "a"], ["workflow", "delete_repo", "gist"])
        self.assertEqual(json.loads(zeile), {"commit_id": COMMIT, "tree_id": TREE, "bestaetigt": ["a", "b"],
                                             "scopes_ausnahmen": ["gist", "workflow"]})
