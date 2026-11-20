"""Fehlerbild der Werkstatt: { "code": "...", "text": "..." }.

Die Sätze nennen nie interne Namen (Tabellen, Funktionen, Pfade, Rollen) und geben nie Eingaben zurück. Wer mehr wissen will,
liest das Journal (Marke wamo-werkstatt), dort steht je Ablehnung der Code.
"""

from __future__ import annotations

# Code -> (HTTP-Status, Standardsatz). Die Liste ist der Vertrag mit der Oberfläche (docs/adminpanel-bauplan.md, Abschnitt 3).
FEHLER: dict[str, tuple[int, str]] = {
    "nicht_angemeldet": (401, "Bitte melde dich an."),
    "aal2_fehlt": (403, "Für die Werkstatt ist der zweite Faktor nötig."),
    "aal2_alt": (403, "Der Code des zweiten Faktors ist zu alt. Bitte gib einen neuen Code ein."),
    "nicht_berechtigt": (403, "Dafür fehlt dir die Berechtigung."),
    "labor_profil": (403, "Laborprofile haben keinen Zugang zur Werkstatt."),
    "nicht_gefunden": (404, "Das gibt es nicht."),
    "karte_verbraucht": (409, "Diese Karte wurde schon benutzt."),
    "konflikt": (409, "Das passt nicht zum aktuellen Stand. Bitte lade die Ansicht neu."),
    "karte_abgelaufen": (410, "Die Karte ist abgelaufen. Bitte lege eine neue an."),
    "ungueltig": (422, "Die Angaben sind unvollständig oder ungültig."),
    "zu_oft": (429, "Zu viele Anfragen. Bitte warte einen Moment."),
    "nicht_verfuegbar": (503, "Die Werkstatt ist gerade nicht verfügbar. Bitte versuche es gleich noch einmal."),
}


class WerkstattFehler(Exception):
    """Eine Anfrage wird abgelehnt. code steht in FEHLER, text ist der Satz für die Person (nie eine Eingabe, nie ein interner Name)."""

    def __init__(self, code: str, text: str | None = None, *, warte_s: int | None = None):
        if code not in FEHLER:  # ein Tippfehler im Code darf nie zu einem unbekannten Fehlerbild führen
            raise ValueError("unbekannter Fehlercode")
        self.code = code
        self.http = FEHLER[code][0]
        self.text = text or FEHLER[code][1]
        self.warte_s = warte_s
        super().__init__(code)

    def koerper(self) -> dict[str, str]:
        return {"code": self.code, "text": self.text}


def ungueltig(text: str) -> WerkstattFehler:
    """Kurzform für 422 mit einem eigenen Satz (der Satz nennt das Feld, nie den Wert)."""
    return WerkstattFehler("ungueltig", text)
