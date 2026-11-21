"""Sicherheitsproben der Anmeldung: Token, zweiter Faktor, Profil, Erlaubnisliste, Drosselung, Fehlerbild."""

from __future__ import annotations

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

import conftest as k
from conftest import AUSSERHALB, FREMDER_SCHLUESSEL, LABOR, MITGLIED, OHNE_PROFIL, kopf, token
from wamo_werkstatt import anmeldung
from wamo_werkstatt.anmeldung import JwksQuelle, QuelleNichtErreichbar, TokenPruefer, aal2_alter_s
from wamo_werkstatt.fehler import FEHLER, WerkstattFehler

PFAD = "/werkstatt/api/ich"


def code(antwort) -> str:
    return antwort.json()["code"]


def test_ich_fuer_admin(client):
    r = client.get(PFAD, headers=kopf())
    assert r.status_code == 200
    daten = r.json()
    assert daten["rolle"] == "admin" and daten["erlaubt"] is True
    assert 0 <= daten["aal2_alter_s"] <= 10
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("header", [{}, {"Authorization": "Bearer"}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer a b"},
                                    {"Authorization": "Bearer kein.token.hier"}, {"Authorization": "Bearer " + "x" * 9000}])
def test_ohne_oder_mit_kaputtem_token_401(client, header):
    r = client.get(PFAD, headers=header)
    assert r.status_code == 401 and code(r) == "nicht_angemeldet"
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("tok", [
    lambda: token(exp_in=-120),
    lambda: token(iss="https://fremd.test/auth/v1"),
    lambda: token(aud="anon"),
    lambda: token(schluessel=FREMDER_SCHLUESSEL),
    lambda: token(kid="unbekannt"),
    lambda: token(kid=None),
    lambda: token(sub="kein-uuid"),
    lambda: jwt.encode({"sub": k.ADMIN, "aud": k.AUD, "iss": k.ISS, "exp": 9999999999, "aal": "aal2"}, "geheim" * 8, algorithm="HS256",
                       headers={"kid": "k1"}),
])
def test_ungueltige_tokens_401(client, tok):
    r = client.get(PFAD, headers=kopf(tok()))
    assert r.status_code == 401 and code(r) == "nicht_angemeldet"


def test_token_ohne_signatur_401(client):
    kopfzeile, nutzlast, _ = token().split(".")
    r = client.get(PFAD, headers=kopf(f"{kopfzeile}.{nutzlast}."))
    assert r.status_code == 401


def test_algorithmus_none_401(client):
    tok = jwt.encode({"sub": k.ADMIN, "aud": k.AUD, "iss": k.ISS, "exp": 9999999999, "aal": "aal2"}, None, algorithm="none", headers={"kid": "k1"})
    assert client.get(PFAD, headers=kopf(tok)).status_code == 401


def test_anmeldedienst_nicht_erreichbar_503(client, quelle):
    quelle.ausfall = True
    r = client.get(PFAD, headers=kopf())
    assert r.status_code == 503 and code(r) == "nicht_verfuegbar"


@pytest.mark.parametrize("aal", ["aal1", None])
def test_ohne_zweiten_faktor_403(client, aal):
    r = client.get(PFAD, headers=kopf(token(aal=aal)))
    assert r.status_code == 403 and code(r) == "aal2_fehlt"


def test_laborprofil_403_auch_wenn_in_der_liste(client):
    r = client.get(PFAD, headers=kopf(token(sub=LABOR)))
    assert r.status_code == 403 and code(r) == "labor_profil"


def test_laborprofil_mit_unbekannter_art_ist_labor(client, db):
    from wamo_werkstatt.daten import Profil

    db.profile[k.ADMIN] = Profil(k.ADMIN, "admin", True, "etwas_neues")
    assert code(client.get(PFAD, headers=kopf())) == "labor_profil"


def test_mitglied_403(client):
    r = client.get(PFAD, headers=kopf(token(sub=MITGLIED)))
    assert r.status_code == 403 and code(r) == "nicht_berechtigt"


def test_admin_ausserhalb_der_liste_403(client):
    r = client.get(PFAD, headers=kopf(token(sub=AUSSERHALB)))
    assert r.status_code == 403 and code(r) == "nicht_berechtigt"


@pytest.mark.parametrize("sub", [OHNE_PROFIL])
def test_ohne_profil_403(client, sub):
    assert code(client.get(PFAD, headers=kopf(token(sub=sub)))) == "nicht_berechtigt"


def test_inaktiver_admin_403(client, db):
    from wamo_werkstatt.daten import Profil

    db.profile[k.ADMIN] = Profil(k.ADMIN, "admin", False, None)
    assert code(client.get(PFAD, headers=kopf())) == "nicht_berechtigt"


def test_datenbank_ausfall_503(client, db):
    db.ausfall = True
    r = client.get(PFAD, headers=kopf())
    assert r.status_code == 503 and code(r) == "nicht_verfuegbar"
    assert "Attrappe" not in r.text


def test_liste_wirkt_ohne_neustart(client, konfig):
    assert code(client.get(PFAD, headers=kopf(token(sub=AUSSERHALB)))) == "nicht_berechtigt"
    konfig.admins_datei.write_text(f"{AUSSERHALB.upper()}\n", encoding="utf-8")
    assert client.get(PFAD, headers=kopf(token(sub=AUSSERHALB))).status_code == 200
    assert code(client.get(PFAD, headers=kopf())) == "nicht_berechtigt"


def test_unlesbare_liste_laesst_niemanden_hinein(client, konfig):
    konfig.admins_datei.unlink()
    assert code(client.get(PFAD, headers=kopf())) == "nicht_berechtigt"


def test_kaputte_zeilen_der_liste_werden_ignoriert(client, konfig):
    konfig.admins_datei.write_text(f"nonsens\n\n#{k.ADMIN}\n{k.ADMIN[:-1]}\n{k.ADMIN}\n", encoding="utf-8")
    assert client.get(PFAD, headers=kopf()).status_code == 200


def test_zu_grosse_liste_ist_leer(client, konfig):
    konfig.admins_datei.write_text(("#" + "x" * 100 + "\n") * 300 + f"{k.ADMIN}\n", encoding="utf-8")
    assert code(client.get(PFAD, headers=kopf())) == "nicht_berechtigt"


def test_drosselung_61_abrufe(client, mono):
    for _ in range(60):
        assert client.get(PFAD, headers=kopf()).status_code == 200
    r = client.get(PFAD, headers=kopf())
    assert r.status_code == 429 and code(r) == "zu_oft"
    assert int(r.headers["retry-after"]) >= 1
    # eine andere Person ist nicht betroffen, nach dem Fenster geht es wieder
    assert client.get(PFAD, headers=kopf(token(sub=k.ANDERER_ADMIN))).status_code == 200
    mono.t += 61
    assert client.get(PFAD, headers=kopf()).status_code == 200


def test_drosselung_zaehlt_auch_abgewiesene_personen(client):
    for _ in range(60):
        client.get(PFAD, headers=kopf(token(sub=MITGLIED)))
    assert code(client.get(PFAD, headers=kopf(token(sub=MITGLIED)))) == "zu_oft"


def test_unbekannter_pfad_und_falsche_methode_404(client):
    for r in (client.get("/werkstatt/api/gibtesnicht", headers=kopf()), client.post(PFAD, headers=kopf()), client.get("/", headers=kopf()),
              client.get("/docs"), client.get("/openapi.json")):
        assert r.status_code == 404 and code(r) == "nicht_gefunden"


def test_cors_nur_fuer_die_oberflaeche(client):
    erlaubt = client.options(PFAD, headers={"Origin": k.HERKUNFT, "Access-Control-Request-Method": "GET",
                                           "Access-Control-Request-Headers": "authorization"})
    assert erlaubt.status_code == 200 and erlaubt.headers["access-control-allow-origin"] == k.HERKUNFT
    fremd = client.options(PFAD, headers={"Origin": "https://boese.test", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in fremd.headers
    antwort = client.get(PFAD, headers={**kopf(), "Origin": "https://boese.test"})
    assert "access-control-allow-origin" not in antwort.headers


def test_schutzkopfzeilen_auf_jeder_antwort(client):
    for r in (client.get(PFAD), client.get(PFAD, headers=kopf()), client.get("/nirgends")):
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["x-content-type-options"] == "nosniff"


def test_fehlercodes_haben_feste_saetze():
    assert set(FEHLER) == {"nicht_angemeldet", "aal2_fehlt", "aal2_alt", "nicht_berechtigt", "labor_profil", "nicht_gefunden", "karte_verbraucht",
                           "konflikt", "karte_abgelaufen", "ungueltig", "zu_oft", "nicht_verfuegbar"}
    with pytest.raises(ValueError):
        WerkstattFehler("gibt_es_nicht")
    assert WerkstattFehler("zu_oft", warte_s=3).koerper() == {"code": "zu_oft", "text": FEHLER["zu_oft"][1]}


@pytest.mark.parametrize("amr, erwartet", [
    ([], None),
    ("kaputt", None),
    ([{"method": "password", "timestamp": 990}], None),
    ([{"method": "totp", "timestamp": 990}], 10),
    ([{"method": "totp", "timestamp": 900}, {"method": "totp", "timestamp": 995}], 5),  # der jüngste zählt
    ([{"method": "totp", "timestamp": 1002}], 0),
    ([{"method": "totp", "timestamp": 1100}], None),  # aus der Zukunft
    ([{"method": "totp", "timestamp": True}, {"method": "totp", "timestamp": "x"}, "x"], None),
])
def test_aal2_alter(amr, erwartet):
    assert aal2_alter_s({"amr": amr}, 1000.0) == erwartet


async def test_pruefer_direkt():
    pruefer = TokenPruefer(k.FesteQuelle(), aussteller=k.ISS, zielgruppe=k.AUD)
    assert (await pruefer.pruefen(token()))["sub"] == k.ADMIN
    with pytest.raises(WerkstattFehler) as e:
        await pruefer.pruefen(None)
    assert e.value.code == "nicht_angemeldet"


def _jwks(schluessel=k.SCHLUESSEL, kid="k1", **mehr) -> dict:
    import json

    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(schluessel.public_key()))
    return {"keys": [{**jwk, "kid": kid, "use": "sig", **mehr}, {"kty": "RSA", "kid": "rsa"}, "kaputt"]}


class _Zaehler:
    def __init__(self, antwort):
        self.antwort, self.aufrufe = antwort, 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.aufrufe += 1
        return self.antwort(request) if callable(self.antwort) else self.antwort


async def test_jwks_quelle_holt_und_cached():
    zaehler = _Zaehler(httpx.Response(200, json=_jwks()))
    uhr = {"t": 0.0}
    quelle = JwksQuelle("https://stack.test/jwks", transport=httpx.MockTransport(zaehler), mono=lambda: uhr["t"])
    assert await quelle.schluessel("k1") is not None
    assert await quelle.schluessel("k1") is not None
    assert zaehler.aufrufe == 1
    # eine erfundene Kennung löst höchstens alle 30 Sekunden einen neuen Abruf aus
    for _ in range(3):
        with pytest.raises(KeyError):
            await quelle.schluessel("erfunden")
    assert zaehler.aufrufe == 1
    uhr["t"] = 31
    with pytest.raises(KeyError):
        await quelle.schluessel("erfunden")
    assert zaehler.aufrufe == 2
    with pytest.raises(KeyError):
        await quelle.schluessel(None)


async def test_jwks_quelle_ausfall_und_alter_satz():
    antworten = [httpx.Response(200, json=_jwks()), httpx.Response(500), httpx.Response(500)]
    zaehler = _Zaehler(lambda r: antworten.pop(0))
    uhr = {"t": 0.0}
    quelle = JwksQuelle("https://stack.test/jwks", transport=httpx.MockTransport(zaehler), mono=lambda: uhr["t"])
    await quelle.schluessel("k1")
    uhr["t"] = 400  # veraltet, Abruf scheitert: der alte Satz gilt weiter
    assert await quelle.schluessel("k1") is not None
    uhr["t"] = 5000  # zu alt: nicht mehr verwendbar
    with pytest.raises(QuelleNichtErreichbar):
        await quelle.schluessel("k1")


async def test_jwks_quelle_nie_erreichbar():
    def kaputt(_r):
        raise httpx.ConnectError("weg")

    quelle = JwksQuelle("https://stack.test/jwks", transport=httpx.MockTransport(kaputt))
    with pytest.raises(QuelleNichtErreichbar):
        await quelle.schluessel("k1")


@pytest.mark.parametrize("antwort", [httpx.Response(200, content=b"kein json"), httpx.Response(200, json={"keys": "x"}),
                                     httpx.Response(200, content=b"x" * 70000)])
async def test_jwks_quelle_unbrauchbare_antworten(antwort):
    quelle = JwksQuelle("https://stack.test/jwks", transport=httpx.MockTransport(lambda r: antwort))
    with pytest.raises(QuelleNichtErreichbar):
        await quelle.schluessel("k1")


def test_fremder_schluessel_im_satz_wird_nicht_genutzt():
    assert isinstance(FREMDER_SCHLUESSEL, ec.EllipticCurvePrivateKey) and anmeldung.AAL2_MAX_ALTER_S == 60


async def test_jwks_leerer_satz_widerruft_alte_schluessel():
    antworten = [httpx.Response(200, json=_jwks()), httpx.Response(200, json={"keys": []})]
    uhr = {"t": 0.0}
    quelle = JwksQuelle("https://stack.test/jwks", transport=httpx.MockTransport(lambda r: antworten.pop(0)), mono=lambda: uhr["t"])
    assert await quelle.schluessel("k1") is not None
    uhr["t"] = 400  # veraltet: neuer Abruf, GoTrue nennt keinen Schlüssel mehr
    with pytest.raises(KeyError):
        await quelle.schluessel("k1")


async def test_jwks_kaputter_einzelschluessel_verwirft_den_satz_nicht():
    satz = _jwks()
    satz["keys"].insert(0, {"kty": "EC", "crv": "P-256", "kid": "kaputt", "use": "sig", "x": "!!", "y": "!!"})
    quelle = JwksQuelle("https://stack.test/jwks", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=satz)))
    assert await quelle.schluessel("k1") is not None
    with pytest.raises(KeyError):
        await quelle.schluessel("kaputt")


async def test_jwks_schluessel_nur_zum_signieren():
    quelle = JwksQuelle("https://stack.test/jwks", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_jwks(use="enc"))))
    with pytest.raises(KeyError):
        await quelle.schluessel("k1")
