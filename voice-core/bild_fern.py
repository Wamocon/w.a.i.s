"""Prüfung der Fernanfrage für das Live-Bild (Entscheidung Niko 04.11.2026).

Die Person bittet in der Oberfläche, zum Beispiel am Handy, den eigenen Laptop um das Live-Bild (Admins und, seit dem 16.11.2026,
freigeschaltete Mitglieder). Die Oberfläche schickt dafür das Zugangstoken mit, das sie nach der Eingabe eines FRISCHEN Codes der
Authenticator-App bekommen hat. Der Kern prüft hier, bevor er den Host bittet:

  * das Token ist gültig und kommt durch dieselbe Zugangskontrolle wie jede Anfrage (Signatur, zweiter Faktor, aktives Profil),
  * es gehört zum Profil dieser Sitzung (kein fremdes Token aus einer anderen Anmeldung) und das Profil hat eine Stufe der
    PC-Steuerung (rechte.pc_stufe: Admin oder freigeschaltetes Mitglied, nie ein Laborprofil),
  * der letzte Code des zweiten Faktors ist höchstens 120 Sekunden alt (wie beim Fernzugriff auf die Sparks).

Das Token wird nie geloggt, gespeichert oder weitergereicht. Der Rest (Einwilligung am Laptop, Besitzer, roter Rahmen, Ablauf) wird
am Laptop selbst entschieden: Der Host legt nur eine Anfrage ab, die Desktop-App schaltet erst nach eigener Prüfung ein.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import rechte
from auth_gate import erstanmeldung_sperre
from geraete_admin_api import aal2_frisch, aal2_zeit

TOKEN_MAX = 8192
TEXT_CODE = "Bitte gib den aktuellen Code der Authenticator-App ein."
TEXT_ALT = "Der Code ist zu alt. Bitte gib einen neuen Code ein."
TEXT_FALSCH = "Diese Anmeldung passt nicht zu dieser Sitzung. Bitte melde dich neu an."


def pruefer(user_id: str, gate: Callable[[], object | None]) -> Callable[[object], Awaitable[str | None]]:
    """Bindet die Prüfung an das Profil der Sitzung. gate() liefert die Zugangskontrolle (auth_gate.AccessGate) oder None."""

    async def pruefen(token: object) -> str | None:
        """None, wenn die Fernanfrage erlaubt ist, sonst ein kurzer Text für die Person."""
        if not isinstance(token, str) or not 20 <= len(token) <= TOKEN_MAX or token.count(".") != 2:
            return TEXT_CODE
        tor = gate()
        if tor is None:
            return "Die Zugangskontrolle ist gerade nicht erreichbar."
        entscheidung = await tor.authorize(token)  # sperrt bei offener oder abgelaufener Erstanmeldung selbst
        if erstanmeldung_sperre(entscheidung) is not None:  # zweite Sicherung, auch bei einem fremden Tor
            return TEXT_FALSCH
        ich = getattr(entscheidung, "identity", None)
        if ich is None or ich.user_id != user_id or rechte.pc_stufe(ich) is None:
            return TEXT_FALSCH
        if not aal2_frisch(aal2_zeit(token)):
            return TEXT_ALT
        return None

    return pruefen
