"""PC-Steuerung verbindet den Laptop nach, wenn der Tunnel erst nach dem Sitzungsstart steht (pc_nachverbinden.py, bot.py).

Befund 15.11.2026: Die Sitzung begann 18 Sekunden, bevor der Tunnel des Laptops stand. build_session fragte pc_zugang genau einmal, die
Sitzung blieb ohne PC, und jeder Klick auf den Schalter PC-Steuerung endete still in "aus". Geprüft wird hier:
  * der Nachholer selbst (höchstens ein Versuch gleichzeitig, Ratenbegrenzung, Zeitplan im Hintergrund, nichts nach dem Ende),
  * wer nachholen darf (nur Admin mit aktivem Gerät im Register, Tunnel je Gerät, Host an, nie Labor, nie Mitglied),
  * die Sitzung (bot.py): der Klick auf "an" holt den Zugang nach und schaltet ein, ein Fehlschlag meldet "getrennt" mit einem Satz,
    der Hintergrund meldet "verbunden" von selbst, der Rechnernamen-Abgleich und das Gate der Stimmprüfung gelten unverändert.

Ausführen:  python -m pytest -q test_pc_nachverbinden.py   (im Ordner voice-core/)
"""

from __future__ import annotations

import asyncio
import json
import types
import uuid
from unittest import mock

import pytest

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.processors.aggregators.llm_response_universal import LLMUserAggregator
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame

import geraete_werkzeuge
import pc_geraet
import pc_host
import pc_nachverbinden
import test_smoke_bot as smoke
from auth_gate import Identity
from geraete_register import Geraet, RegisterFehler
from pc_nachverbinden import PcNachholer, nachholen_moeglich
from stimme_gate import MARKE

bot = smoke.bot
USER = smoke.USER
KENNUNG = "pc-test-01"
RECHNER = "PC-TEST-01"


# ---------- Hilfen ----------
class Uhr:
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class FakeRegister:
    def __init__(self, geraete: dict | None = None, fehler: Exception | None = None):
        self.geraete = geraete or {}
        self.fehler = fehler
        self.abfragen: list[str] = []

    async def aktives_geraet(self, user_id: str):
        self.abfragen.append(user_id)
        if self.fehler:
            raise self.fehler
        return self.geraete.get(user_id)

    async def ist_aktiv(self, device_id: str, user_id: str):
        return True

    async def gesehen(self, kennung: str) -> None:
        return None


def geraet(hostname: str | None = RECHNER) -> Geraet:
    return Geraet(device_id=str(uuid.uuid4()), kennung=KENNUNG, slot=1, name="Laptop", hostname=hostname,
                  fingerabdruck="SHA256:" + "A" * 43)


def pc_zugang_test(hostname: str | None = RECHNER) -> pc_geraet.PcZugang:
    return pc_geraet.PcZugang(geraet=geraet(hostname), user_id=USER, socket="/run/wamo-pc/t01/pc.sock", uid=1001,
                              wurzel="/run/wamo-pc", geheimnisse=pc_geraet.Geheimnisse("a" * 43, "b" * 43), register=FakeRegister())


def admin() -> Identity:
    return Identity(USER, "Erika", "admin", "sie")


def mitglied() -> Identity:
    return Identity(USER, "Erika", "mitglied", "sie")


# ---------- Der Nachholer ----------
async def test_erfolg_gilt_fuer_die_ganze_sitzung():
    aufrufe = []

    async def versuch():
        aufrufe.append(1)
        return True

    n = PcNachholer(versuch, aktiv=lambda: True, uhr=Uhr())
    assert await n.versuchen() is True
    assert await n.versuchen() is True
    assert n.verbunden is True and len(aufrufe) == 1


async def test_hoechstens_ein_versuch_gleichzeitig_und_der_zweite_bekommt_das_ergebnis():
    frei, aufrufe = asyncio.Event(), []

    async def versuch():
        aufrufe.append(1)
        await frei.wait()
        return True

    n = PcNachholer(versuch, aktiv=lambda: True, uhr=Uhr())
    a, b = asyncio.create_task(n.versuchen()), asyncio.create_task(n.versuchen())
    for _ in range(5):
        await asyncio.sleep(0)
    assert len(aufrufe) == 1
    frei.set()
    assert await a is True and await b is True
    assert len(aufrufe) == 1


async def test_ratenbegrenzung_zwischen_zwei_versuchen():
    uhr, aufrufe = Uhr(), []

    async def versuch():
        aufrufe.append(uhr.t)
        uhr.t += 1.0  # ein Versuch dauert eine Sekunde; der Abstand zählt ab seinem Ende
        return False

    n = PcNachholer(versuch, aktiv=lambda: True, uhr=uhr, abstand=2.0)
    assert await n.versuchen() is False
    uhr.t = 2.9
    assert await n.versuchen() is False  # 1,9 s nach dem Ende: kein neuer Versuch
    assert aufrufe == [0.0]
    uhr.t = 3.0
    assert await n.versuchen() is False
    assert aufrufe == [0.0, 3.0]


async def test_nichts_nach_dem_ende_oder_einem_entzug():
    lage = {"aktiv": False}
    versuch = mock.AsyncMock(return_value=True)
    n = PcNachholer(versuch, aktiv=lambda: lage["aktiv"], uhr=Uhr())
    assert await n.versuchen() is False
    versuch.assert_not_awaited()
    # Endet die Sitzung, während ein Klick auf den laufenden Versuch wartet, beginnt danach keiner mehr
    frei = asyncio.Event()

    async def langsam():
        await frei.wait()
        return False

    lage["aktiv"] = True
    n = PcNachholer(langsam, aktiv=lambda: lage["aktiv"], uhr=Uhr(), abstand=0.0)
    erster = asyncio.create_task(n.versuchen())
    await asyncio.sleep(0)
    zweiter = asyncio.create_task(n.versuchen())
    await asyncio.sleep(0)
    lage["aktiv"] = False
    frei.set()
    assert await erster is False and await zweiter is False
    assert n.versuche == 1


async def test_fehler_im_versuch_zaehlt_als_fehlschlag_abbruch_nicht():
    n = PcNachholer(mock.AsyncMock(side_effect=RuntimeError("weg")), aktiv=lambda: True, uhr=Uhr())
    assert await n.versuchen() is False and n.verbunden is False
    n = PcNachholer(mock.AsyncMock(side_effect=asyncio.CancelledError()), aktiv=lambda: True, uhr=Uhr())
    with pytest.raises(asyncio.CancelledError):
        await n.versuchen()


async def test_hintergrund_alle_5_s_in_der_ersten_minute_dann_alle_15_s_bis_3_minuten():
    uhr, versuche = Uhr(), []

    async def schlaf(s):
        uhr.t += s

    async def versuch():
        versuche.append(uhr.t)
        return False

    ende = mock.AsyncMock()
    await PcNachholer(versuch, aktiv=lambda: True, uhr=uhr, schlaf=schlaf).hintergrund(ende)
    assert versuche == [3, 8, 13, 18, 23, 28, 33, 38, 43, 48, 53, 58, 63, 78, 93, 108, 123, 138, 153, 168]
    assert max(versuche) <= pc_nachverbinden.DAUER_SECS
    ende.assert_awaited_once()


async def test_hintergrund_endet_beim_erfolg_und_beim_sitzungsende_ohne_meldung():
    uhr = Uhr()

    async def schlaf(s):
        uhr.t += s

    versuch = mock.AsyncMock(side_effect=[False, False, True])
    ende = mock.AsyncMock()
    n = PcNachholer(versuch, aktiv=lambda: True, uhr=uhr, schlaf=schlaf)
    await n.hintergrund(ende)
    assert versuch.await_count == 3 and n.verbunden
    ende.assert_not_awaited()

    lage = {"aktiv": True}
    zaehler = []

    async def versuch_bis_ende():
        zaehler.append(1)
        if len(zaehler) == 2:
            lage["aktiv"] = False  # Sitzung endet während des zweiten Versuchs
        return False

    await PcNachholer(versuch_bis_ende, aktiv=lambda: lage["aktiv"], uhr=uhr, schlaf=schlaf).hintergrund(ende)
    assert len(zaehler) == 2
    ende.assert_not_awaited()


async def test_hinweis_hoechstens_alle_20_sekunden():
    uhr = Uhr()
    n = PcNachholer(mock.AsyncMock(return_value=False), aktiv=lambda: True, uhr=uhr)
    assert n.hinweis_faellig() is True
    uhr.t = 19.0
    assert n.hinweis_faellig() is False
    uhr.t = 20.0
    assert n.hinweis_faellig() is True


def test_hinweis_ist_ein_klarer_satz():
    text = pc_nachverbinden.HINWEIS_NICHT_VERBUNDEN
    assert "Desktop-App" in text and "Laptop" in text
    assert "–" not in text and "—" not in text and " - " not in text


# ---------- Wer nachholen darf ----------
@pytest.fixture
def buero(monkeypatch):
    for name, wert in smoke.DUMMY_ENV.items():
        monkeypatch.setenv(name, wert)
    monkeypatch.setenv("WAMO_BETRIEB", "buero")
    monkeypatch.setenv("WAMO_PC_REGISTER", "an")
    monkeypatch.setenv("WAMO_PC_HOST", "on")
    return monkeypatch


async def test_nur_admin_mit_aktivem_geraet_holt_nach(buero):
    reg = FakeRegister({USER: geraet()})
    assert await nachholen_moeglich(admin(), zugang_da=False, register=reg) is True
    assert await nachholen_moeglich(mitglied(), zugang_da=False, register=reg) is False
    assert await nachholen_moeglich(admin(), zugang_da=True, register=reg) is False  # schon verbunden: nichts nachzuholen
    assert reg.abfragen == [USER]  # nur der erste Fall fragt das Register
    assert await nachholen_moeglich(admin(), zugang_da=False, register=FakeRegister()) is False  # kein Gerät: bleibt "aus"


async def test_register_nicht_lesbar_heisst_nachholen_ohne_datenbank_nicht(buero):
    assert await nachholen_moeglich(admin(), zugang_da=False, register=FakeRegister(fehler=RegisterFehler("weg"))) is True
    assert await pc_geraet.geraet_erwartet(admin()) is False  # WAMO_DATABASE_URL leer: kein Register, kein Nachholen


@pytest.mark.parametrize("env", [{"WAMO_PC_REGISTER": "aus"}, {"WAMO_BETRIEB": "lokal"}, {"WAMO_PC_HOST": "off"}])
async def test_ohne_tunnel_je_geraet_oder_ohne_host_kein_nachholen(buero, env):
    for name, wert in env.items():
        buero.setenv(name, wert)
    reg = FakeRegister({USER: geraet()})
    assert await nachholen_moeglich(admin(), zugang_da=False, register=reg) is False
    assert reg.abfragen == []


async def test_laborprofil_holt_nie_nach(buero):
    reg = FakeRegister({USER: geraet()})
    labor = Identity(USER, "Gast", "mitglied", "du", labor_art="platz", labor_platz=3, labor_aktiv=True)
    assert await nachholen_moeglich(labor, zugang_da=False, register=reg) is False
    labor_admin = types.SimpleNamespace(user_id=USER, is_admin=True, labor_art="platz")  # auch eine falsch gebaute Identität nicht
    assert await nachholen_moeglich(labor_admin, zugang_da=False, register=reg) is False
    assert reg.abfragen == []


# ---------- Die Sitzung (bot.py) ----------
class Client:
    def __init__(self):
        self.geschlossen = False

    async def close(self):
        self.geschlossen = True


async def host_handler(params):
    await params.result_callback({"status": "success"})


def pc_werkzeuge() -> ToolsSchema:
    return ToolsSchema(standard_tools=[FunctionSchema("programm_oeffnen", "PC", {}, [], handler=host_handler)])


class Lage:
    """Attrappen einer Büro-Sitzung im Tunnel je Gerät: pc_zugang liefert der Reihe nach die Werte aus zugaenge (danach den letzten)."""

    def __init__(self, monkeypatch, zugaenge: list, *, rechner: str = RECHNER, erwartet: bool = True):
        self.zugaenge = list(zugaenge)
        self.pc_zugang = mock.AsyncMock(side_effect=self._naechster)
        self.clients: list[Client] = []
        self.host_client = mock.Mock(side_effect=self._client)
        self.rechner = rechner
        monkeypatch.setattr(bot, "pc_zugang", self.pc_zugang)
        monkeypatch.setattr(bot, "host_client", self.host_client)
        monkeypatch.setattr(bot, "host_tools", mock.AsyncMock(return_value=pc_werkzeuge()))
        monkeypatch.setattr(bot, "call_host_tool", self._aufruf)
        monkeypatch.setattr(pc_nachverbinden, "geraet_erwartet", mock.AsyncMock(return_value=erwartet))
        monkeypatch.setattr(pc_host, "_lease_je_geraet", {})
        monkeypatch.setattr(geraete_werkzeuge.Buerogeraete, "schemas", mock.AsyncMock(return_value=[]))
        monkeypatch.setattr("llm_anbieter.claude_problem", mock.AsyncMock(return_value=None))
        monkeypatch.setattr(pc_nachverbinden, "ERSTE_SECS", 3600.0)  # Hintergrund ruht (bis cleanup), außer ein Test will ihn
        monkeypatch.setattr(pc_nachverbinden, "DAUER_SECS", 7200.0)

    async def _naechster(self, identity):
        return self.zugaenge.pop(0) if len(self.zugaenge) > 1 else self.zugaenge[0]

    def _client(self, zugang=None):
        self.clients.append(Client())
        return self.clients[-1]

    async def _aufruf(self, client, name, arguments):
        return json.dumps({"machine": self.rechner})


async def bauen(identity: Identity, sitzung=None):
    llms = []
    echtes = bot.gespraech_llm

    async def llm_merken(*args, **kwargs):
        ergebnis = await echtes(*args, **kwargs)
        llms.append(ergebnis[0])
        return ergebnis

    with mock.patch.object(bot, "Pipeline", wraps=bot.Pipeline) as pipeline, mock.patch.object(bot, "gespraech_llm", side_effect=llm_merken):
        session = await bot.build_session(smoke.FakeTransport(), identity, sitzung)
    session.task.queue_frames = mock.AsyncMock()
    session.task.queue_frame = mock.AsyncMock()
    await session.task.rtvi._call_event_handler("on_client_ready")
    await abwarten()
    return session, pipeline.call_args.args[0], llms[0]


async def abwarten():
    for _ in range(200):
        await asyncio.sleep(0)


async def bis(bedingung, frist: float) -> None:
    """Wartet höchstens frist Sekunden, bis bedingung() gilt (echte Zeit, für die 2 s in start_pc und den Hintergrund)."""
    ende = asyncio.get_running_loop().time() + frist
    while not bedingung() and asyncio.get_running_loop().time() < ende:
        await asyncio.sleep(0.02)
    await abwarten()


async def klick(session, an: bool):
    await session.task.rtvi._call_event_handler("on_client_message", types.SimpleNamespace(type="pc_steuerung", data={"an": an}))
    await abwarten()


def gesendet(session) -> list[dict]:
    return [f.data for aufruf in session.task.queue_frames.await_args_list for f in aufruf.args[0] if isinstance(f, RTVIServerMessageFrame)]


def betrieb(session) -> dict:
    return [m for m in gesendet(session) if m.get("type") == "betrieb"][-1]


def gesprochen(session) -> list[str]:
    return [f.text for aufruf in session.task.queue_frames.await_args_list for f in aufruf.args[0] if isinstance(f, TTSSpeakFrame)]


def kontext_namen(stufen) -> set[str]:
    nutzer = next(p for p in stufen if isinstance(p, LLMUserAggregator))
    return {s.name for s in nutzer.context.tools.standard_tools if isinstance(s, FunctionSchema)}


async def test_klick_holt_den_zugang_nach_und_schaltet_ein(buero):
    zugang = pc_zugang_test()
    lage = Lage(buero, [None, zugang])
    session, stufen, _llm = await bauen(admin())
    assert betrieb(session)["pc"] == "verbindet"  # nicht "aus": der Laptop kann noch kommen
    assert lage.host_client.call_count == 0 and "programm_oeffnen" not in kontext_namen(stufen)
    await klick(session, True)
    assert lage.pc_zugang.await_count == 2
    lage.host_client.assert_called_once_with(zugang)  # derselbe Weg wie beim Start: Client nur für dieses Gerät
    stand = betrieb(session)
    assert (stand["pc"], stand["pc_steuerung"], stand["pc_name"]) == ("verbunden", "an", RECHNER)
    assert "programm_oeffnen" in kontext_namen(stufen)
    assert pc_host._lease_je_geraet.get(zugang.geraet.device_id) is not None  # die PC-Sperre gilt für dieses Gerät
    assert gesprochen(session) == []
    await session.cleanup()
    assert lage.clients[0].geschlossen


async def test_klick_ohne_tunnel_meldet_getrennt_mit_einem_satz(buero):
    lage = Lage(buero, [None])
    session, stufen, _llm = await bauen(admin())
    await klick(session, True)
    stand = betrieb(session)
    assert (stand["pc"], stand["pc_steuerung"]) == ("getrennt", "aus")
    assert gesprochen(session) == [pc_nachverbinden.HINWEIS_NICHT_VERBUNDEN]
    assert lage.host_client.call_count == 0 and "programm_oeffnen" not in kontext_namen(stufen)
    # Ein zweiter Klick gleich danach: kein neuer Versuch (Ratenbegrenzung) und kein zweiter Satz
    await klick(session, True)
    assert lage.pc_zugang.await_count == 2
    assert gesprochen(session) == [pc_nachverbinden.HINWEIS_NICHT_VERBUNDEN]
    await session.cleanup()


async def test_rechnername_passt_nicht_dann_bleibt_die_steuerung_aus(buero):
    lage = Lage(buero, [None, pc_zugang_test()], rechner="ANDERER-PC")
    session, _stufen, _llm = await bauen(admin())
    await klick(session, True)
    await bis(lambda: betrieb(session)["pc"] == "getrennt", 5.0)  # start_pc versucht es nach 2 s ein zweites Mal
    assert lage.host_client.call_count == 1
    stand = betrieb(session)
    assert (stand["pc"], stand["pc_steuerung"]) == ("getrennt", "aus")
    assert pc_host._lease_je_geraet == {}
    await session.cleanup()


async def test_mitglied_bekommt_nie_einen_nachgeholten_pc(buero):
    lage = Lage(buero, [None, pc_zugang_test()])
    session, _stufen, _llm = await bauen(mitglied())
    assert betrieb(session)["pc"] == "aus"
    await klick(session, True)
    assert lage.pc_zugang.await_count == 1 and lage.host_client.call_count == 0
    assert betrieb(session)["pc_steuerung"] == "aus"
    await session.cleanup()


async def test_admin_ohne_geraet_bleibt_wie_bisher_aus(buero):
    lage = Lage(buero, [None, pc_zugang_test()], erwartet=False)
    session, _stufen, _llm = await bauen(admin())
    assert betrieb(session)["pc"] == "aus"
    await klick(session, True)
    assert lage.pc_zugang.await_count == 1 and lage.host_client.call_count == 0
    assert gesprochen(session) == []
    await session.cleanup()


async def test_ein_neuerer_klick_aus_gewinnt_gegen_den_laufenden_versuch(buero):
    zugang = pc_zugang_test()
    frei = asyncio.Event()
    lage = Lage(buero, [None, zugang])
    session, _stufen, _llm = await bauen(admin())

    async def langsam(identity):
        await frei.wait()
        return zugang

    lage.pc_zugang.side_effect = langsam
    await klick(session, True)
    await klick(session, False)
    frei.set()
    await abwarten()
    stand = betrieb(session)
    assert stand["pc"] == "verbunden" and stand["pc_steuerung"] == "aus"
    assert pc_host._lease_je_geraet == {}
    await session.cleanup()


async def test_hintergrund_meldet_verbunden_ohne_klick_und_endet_mit_der_sitzung(buero):
    lage = Lage(buero, [None, None, pc_zugang_test()])
    for name in ("ERSTE_SECS", "SCHNELL_SECS", "ABSTAND_SECS"):
        buero.setattr(pc_nachverbinden, name, 0.01)
    session, stufen, _llm = await bauen(admin())
    await bis(lambda: betrieb(session)["pc"] == "verbunden", 5.0)
    stand = betrieb(session)
    assert (stand["pc"], stand["pc_steuerung"]) == ("verbunden", "aus")  # einschalten bleibt ein Klick der Person
    assert lage.pc_zugang.await_count == 3 and "programm_oeffnen" in kontext_namen(stufen)
    await klick(session, True)
    assert betrieb(session)["pc_steuerung"] == "an" and lage.pc_zugang.await_count == 3
    await session.cleanup()


async def test_nach_dem_sitzungsende_kein_versuch_mehr(buero):
    lage = Lage(buero, [None])
    buero.setattr(pc_nachverbinden, "ERSTE_SECS", 0.01)
    buero.setattr(pc_nachverbinden, "SCHNELL_SECS", 0.01)
    session, _stufen, _llm = await bauen(admin())
    await asyncio.sleep(0.05)
    await session.cleanup()
    await abwarten()
    vorher = lage.pc_zugang.await_count
    await asyncio.sleep(0.1)
    assert lage.pc_zugang.await_count == vorher
    await klick(session, True)
    assert lage.pc_zugang.await_count == vorher and lage.host_client.call_count == 0


async def test_nachgeholte_werkzeuge_fragen_das_gate_der_stimmpruefung(buero):
    Lage(buero, [None, pc_zugang_test()])
    session, stufen, llm = await bauen(admin())
    await klick(session, True)
    gate = session.stimme.gate
    nutzer = next(p for p in stufen if isinstance(p, LLMUserAggregator))
    schemas = {s.name: s for s in nutzer.context.tools.standard_tools if isinstance(s, FunctionSchema)}
    assert getattr(schemas["programm_oeffnen"].handler, MARKE, None) is gate
    assert getattr(llm._functions["bildschirm_ansehen"].handler, MARKE, None) is gate
    await session.cleanup()


async def test_klick_waehrend_des_namensabgleichs_wartet_auf_den_versuch(buero):
    """Der Hintergrund hat den Client schon gebaut, der Rechnername ist noch nicht geprüft: ein Klick auf "an" wartet auf den laufenden
    Versuch, statt still in "aus" zu enden."""
    lage = Lage(buero, [None, pc_zugang_test()])
    for name in ("ERSTE_SECS", "SCHNELL_SECS", "ABSTAND_SECS"):
        buero.setattr(pc_nachverbinden, name, 0.01)
    frei = asyncio.Event()

    async def langsame_werkzeuge(client):
        await frei.wait()
        return pc_werkzeuge()

    buero.setattr(bot, "host_tools", langsame_werkzeuge)
    session, _stufen, _llm = await bauen(admin())
    await bis(lambda: lage.host_client.call_count == 1, 5.0)
    await klick(session, True)
    frei.set()
    await bis(lambda: betrieb(session)["pc_steuerung"] == "an", 5.0)
    stand = betrieb(session)
    assert (stand["pc"], stand["pc_steuerung"]) == ("verbunden", "an")
    assert gesprochen(session) == []
    await session.cleanup()


async def test_ein_fehler_beim_neuen_prompt_haelt_den_start_nicht_auf(buero):
    lage = Lage(buero, [None, pc_zugang_test()])
    session, _stufen, _llm = await bauen(admin())
    with mock.patch("memory.MemoryStore.recall", mock.AsyncMock(side_effect=RuntimeError("Datenbank weg"))):
        await klick(session, True)
    stand = betrieb(session)
    assert (stand["pc"], stand["pc_steuerung"]) == ("verbunden", "an") and lage.host_client.call_count == 1
    await session.cleanup()


async def test_abgeloeste_sitzung_holt_nichts_mehr_nach(buero):
    from sitzungen import Sitzung

    lage = Lage(buero, [None, pc_zugang_test()])
    sitzung = Sitzung(USER)
    session, _stufen, _llm = await bauen(admin(), sitzung)
    sitzung.abgeloest = True
    await klick(session, True)
    assert lage.pc_zugang.await_count == 1 and lage.host_client.call_count == 0
    await session.cleanup()


async def test_office_onenote_outlook_und_teams_entstehen_auch_beim_nachholen_und_fragen_das_gate(buero):
    """Die Teile, die den PC über lambda: pc_client erreichen, gibt es auch in einer Sitzung, die ihren Zugang erst nachholt; ihre Werkzeuge
    laufen durch das Gate der Stimmprüfung, und ohne Client sagen sie nur, dass es nicht geht."""
    import office_werkzeuge
    import onenote_werkzeuge
    import outlook_werkzeuge
    import teams_werkzeuge

    buero.setenv("WAMO_OFFICE", "dateien,outlook,teams,onenote")
    Lage(buero, [None, pc_zugang_test()])
    session, _stufen, llm = await bauen(admin())
    gate = session.stimme.gate
    for name in (office_werkzeuge.WERKZEUG, onenote_werkzeuge.WERKZEUG, outlook_werkzeuge.WERKZEUG, teams_werkzeuge.WERKZEUG):
        assert getattr(llm._functions[name].handler, MARKE, None) is gate, name
    await klick(session, True)
    assert betrieb(session)["pc_steuerung"] == "an"
    await session.cleanup()


def test_der_nachholer_nimmt_denselben_weg_wie_der_start():
    """Kein zweiter, lockerer Weg: der Versuch ruft pc_zugang, host_client mit dem Gerätezugang und start_pc (Rechnernamen-Abgleich,
    Gerätewache, Tunnelwächter) wie build_session beim Start."""
    import inspect

    quelle = inspect.getsource(bot)
    start = quelle.index("async def pc_nachholen_versuch")
    teil = quelle[start:quelle.index("\n    async def ", start + 10)]
    for noetig in ("await pc_zugang(identity)", "host_client(geraet_neu)", "await start_pc()", 'state["geraet_ok"] = False'):
        assert noetig in teil, noetig
