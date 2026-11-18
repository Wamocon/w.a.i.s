"""Priorität des Host-Prozesses unter Windows (Befund 17.11.2026).

Die geplante Aufgabe "WAMO Tunnel" startete Host und ssh mit der Standardpriorität der Aufgabenplanung (7): Rechenzeit unter normal,
dazu niedrige Speicher- und E/A-Priorität. Windows lagerte den Host fast ganz aus (2 MB im Arbeitsspeicher). Lief daneben eine
Sicherung oder ein Build, antwortete der Host 12 bis 40 s nicht: Export, Öffnen und Teilen liefen in ihre Zeitgrenzen, der Kern meldete
"PC-Host nicht erreichbar". Die Aufgabe startet jetzt mit Priorität 4 (scripts/wamo-tunnel-einrichten.ps1). Dieser Baustein hebt den
Host zusätzlich selbst auf normal, auch wenn ihn noch eine alte Aufgabe startet, und schaltet die Energiedrosselung (EcoQoS) für ihn ab.

Nie über normal (kein Vorrang vor der Arbeit der Person). Wirft nie: scheitert ein Schritt, läuft der Host wie bisher.
"""

from __future__ import annotations

import ctypes
import sys

IDLE_PRIORITY_CLASS = 0x40
BELOW_NORMAL_PRIORITY_CLASS = 0x4000
NORMAL_PRIORITY_CLASS = 0x20
PROCESS_MEMORY_PRIORITY = 0  # PROCESS_INFORMATION_CLASS ProcessMemoryPriority
PROCESS_POWER_THROTTLING = 4  # PROCESS_INFORMATION_CLASS ProcessPowerThrottling
MEMORY_PRIORITY_NORMAL = 5
PROCESS_IO_PRIORITY = 33  # PROCESSINFOCLASS ProcessIoPriority (ntdll)
IO_PRIORITY_NORMAL = 2
POWER_THROTTLING_VERSION = 1
POWER_THROTTLING_EXECUTION_SPEED = 0x1
_FEHLER = (AttributeError, OSError, TypeError, ValueError)
SELBST = ctypes.c_void_p(-1)  # GetCurrentProcess() liefert immer dieses Pseudo-Handle


class _Speicher(ctypes.Structure):
    _fields_ = [("MemoryPriority", ctypes.c_ulong)]


class _Drossel(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]


def normal_setzen(kernel32: object | None = None, ntdll: object | None = None) -> dict:
    """Hebt den eigenen Prozess auf normal: Rechenzeit (nur wenn darunter), Speicher, E/A; Energiedrosselung aus. Liefert, was
    geklappt hat (für das Audit). kernel32 und ntdll nur für Tests."""
    if kernel32 is None and sys.platform != "win32":
        return {"windows": False}
    try:
        k32 = kernel32 or ctypes.WinDLL("kernel32", use_last_error=True)
        nt = ntdll or ctypes.WinDLL("ntdll")
    except _FEHLER as e:
        return {"fehler": type(e).__name__}
    # Pseudo-Handle des eigenen Prozesses in voller Zeigerbreite. Befund 18.11.2026: k32.GetCurrentProcess() kam ohne restype als
    # 32-Bit-int -1 zurück und ging so wieder hinein; unter 64-Bit-Windows ist das ein ungültiges Handle, alle Aufrufe scheiterten.
    selbst = SELBST
    ergebnis: dict = {}
    try:
        vorher = int(k32.GetPriorityClass(selbst))
        ergebnis["cpu_vorher"] = hex(vorher)
        if vorher in (IDLE_PRIORITY_CLASS, BELOW_NORMAL_PRIORITY_CLASS):
            ergebnis["cpu"] = bool(k32.SetPriorityClass(selbst, NORMAL_PRIORITY_CLASS))
    except _FEHLER as e:
        ergebnis["cpu_fehler"] = type(e).__name__
    try:
        speicher = _Speicher(MEMORY_PRIORITY_NORMAL)
        ergebnis["speicher"] = bool(k32.SetProcessInformation(selbst, PROCESS_MEMORY_PRIORITY, ctypes.byref(speicher),
                                                              ctypes.sizeof(speicher)))
    except _FEHLER as e:
        ergebnis["speicher_fehler"] = type(e).__name__
    try:
        io = ctypes.c_ulong(IO_PRIORITY_NORMAL)
        ergebnis["io"] = int(nt.NtSetInformationProcess(selbst, PROCESS_IO_PRIORITY, ctypes.byref(io), ctypes.sizeof(io))) == 0
    except _FEHLER as e:
        ergebnis["io_fehler"] = type(e).__name__
    try:
        drossel = _Drossel(POWER_THROTTLING_VERSION, POWER_THROTTLING_EXECUTION_SPEED, 0)  # Steuerung an, Drosselung aus
        ergebnis["drossel_aus"] = bool(k32.SetProcessInformation(selbst, PROCESS_POWER_THROTTLING, ctypes.byref(drossel),
                                                                 ctypes.sizeof(drossel)))
    except _FEHLER as e:
        ergebnis["drossel_fehler"] = type(e).__name__
    return ergebnis
