"""Tests für prozess_prioritaet.py: Der Host hebt sich auf normal, nie darüber, und wirft nie (Befund 17.11.2026).

kernel32 und ntdll sind Attrappen; geprüft wird, welche Aufrufe mit welchen Werten ankommen. Dazu der Vertrag mit der geplanten
Aufgabe: scripts/wamo-tunnel-einrichten.ps1 legt sie mit Priorität 4 an, und wamo_host.py ruft normal_setzen im HTTP-Betrieb.
"""

import ctypes
import sys
import unittest
from pathlib import Path

import prozess_prioritaet as pp

WURZEL = Path(__file__).resolve().parent.parent


class _Kernel32:
    def __init__(self, klasse: int, ok: bool = True):
        self.klasse = klasse
        self.ok = ok
        self.gesetzt: list[int] = []
        self.informationen: list[tuple[int, bytes]] = []

    def GetCurrentProcess(self):  # noqa: N802 (Name der Windows-Funktion)
        return -1

    def GetPriorityClass(self, _h):  # noqa: N802
        return self.klasse

    def SetPriorityClass(self, _h, klasse):  # noqa: N802
        self.gesetzt.append(klasse)
        return 1 if self.ok else 0

    def SetProcessInformation(self, _h, art, zeiger, groesse):  # noqa: N802
        self.informationen.append((art, ctypes.string_at(ctypes.addressof(zeiger._obj), groesse)))
        return 1 if self.ok else 0


class _Ntdll:
    def __init__(self, status: int = 0):
        self.status = status
        self.werte: list[tuple[int, int]] = []

    def NtSetInformationProcess(self, _h, art, zeiger, _groesse):  # noqa: N802
        self.werte.append((art, zeiger._obj.value))
        return self.status


class NormalSetzen(unittest.TestCase):
    def test_unter_normal_wird_normal(self):
        for klasse in (pp.BELOW_NORMAL_PRIORITY_CLASS, pp.IDLE_PRIORITY_CLASS):
            k32, nt = _Kernel32(klasse), _Ntdll()
            ergebnis = pp.normal_setzen(k32, nt)
            self.assertEqual(k32.gesetzt, [pp.NORMAL_PRIORITY_CLASS])
            self.assertTrue(ergebnis["cpu"])
            self.assertTrue(ergebnis["speicher"])
            self.assertTrue(ergebnis["io"])
            self.assertTrue(ergebnis["drossel_aus"])
            self.assertEqual(nt.werte, [(pp.PROCESS_IO_PRIORITY, pp.IO_PRIORITY_NORMAL)])

    def test_normal_oder_hoeher_bleibt_unberuehrt(self):
        for klasse in (pp.NORMAL_PRIORITY_CLASS, 0x8000, 0x80):  # normal, über normal, hoch
            k32 = _Kernel32(klasse)
            ergebnis = pp.normal_setzen(k32, _Ntdll())
            self.assertEqual(k32.gesetzt, [])
            self.assertNotIn("cpu", ergebnis)

    def test_speicher_normal_und_drossel_aus(self):
        k32 = _Kernel32(pp.BELOW_NORMAL_PRIORITY_CLASS)
        pp.normal_setzen(k32, _Ntdll())
        arten = dict(k32.informationen)
        self.assertEqual(int.from_bytes(arten[pp.PROCESS_MEMORY_PRIORITY], "little"), pp.MEMORY_PRIORITY_NORMAL)
        drossel = arten[pp.PROCESS_POWER_THROTTLING]
        self.assertEqual([int.from_bytes(drossel[i:i + 4], "little") for i in (0, 4, 8)],
                         [pp.POWER_THROTTLING_VERSION, pp.POWER_THROTTLING_EXECUTION_SPEED, 0])

    def test_scheitern_wird_gemeldet_nie_geworfen(self):
        ergebnis = pp.normal_setzen(_Kernel32(pp.BELOW_NORMAL_PRIORITY_CLASS, ok=False), _Ntdll(status=0xC0000022))
        self.assertEqual((ergebnis["cpu"], ergebnis["speicher"], ergebnis["io"], ergebnis["drossel_aus"]),
                         (False, False, False, False))

        class Kaputt:
            def GetCurrentProcess(self):  # noqa: N802
                return -1

            def __getattr__(self, name):
                raise OSError(name)

        ergebnis = pp.normal_setzen(Kaputt(), Kaputt())
        for schluessel in ("cpu_fehler", "speicher_fehler", "io_fehler", "drossel_fehler"):
            self.assertEqual(ergebnis[schluessel], "OSError")


@unittest.skipUnless(sys.platform == "win32", "nur unter Windows")
class EchtUnterWindows(unittest.TestCase):
    """Befund 18.11.2026: Mit den Attrappen war alles grün, am Laptop scheiterte jeder Aufruf (Handle als 32-Bit-int). Hier gegen das
    echte kernel32 und ntdll; der Testprozess wird dabei höchstens auf normal gesetzt."""

    def test_echter_aufruf_liest_die_klasse_und_setzt_speicher_und_ea(self):
        ergebnis = pp.normal_setzen()
        self.assertNotEqual(ergebnis.get("cpu_vorher"), "0x0", ergebnis)
        self.assertTrue(ergebnis.get("speicher"), ergebnis)
        self.assertTrue(ergebnis.get("io"), ergebnis)


class Vertrag(unittest.TestCase):
    def test_aufgabe_startet_mit_prioritaet_vier(self):
        skript = (WURZEL / "scripts" / "wamo-tunnel-einrichten.ps1").read_text(encoding="utf-8")
        block = skript.split("$einstellungen = New-ScheduledTaskSettingsSet", 1)[1].split("Register-ScheduledTask", 1)[0]
        self.assertIn("-Priority 4", block)

    def test_host_hebt_sich_im_http_betrieb(self):
        quelle = (WURZEL / "host" / "wamo_host.py").read_text(encoding="utf-8")
        http = quelle.split('elif "--http" in sys.argv:', 1)[1].split("host_http.starte(", 1)[0]
        self.assertIn("prozess_prioritaet.normal_setzen()", http)


if __name__ == "__main__":
    unittest.main()
