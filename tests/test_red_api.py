"""API de «Red y dispositivos» (app/red_api.py): estado, redetección, pruebas, ajustes y latido de la extensión."""

from pathlib import Path

import pytest

from app import red_api
from core import config, mdns, red
from tests.conftest import TEST_API_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_API_TOKEN}", "Origin": "moz-extension://1234-abcd"}


@pytest.fixture()
def red_limpia(monkeypatch):
    archivo = Path(config.DATA_DIR) / "red.json"
    archivo.unlink(missing_ok=True)
    red.reiniciar_para_tests()
    monkeypatch.setattr(config, "ESP32_HOST", "auto")
    monkeypatch.setattr(mdns, "ips_locales", lambda: ["192.168.1.36"])
    monkeypatch.setattr(mdns, "resolver", lambda *a, **k: None)
    monkeypatch.setattr(red, "vecinos", dict)
    monkeypatch.setattr(red, "_tailscale", lambda: {"activo": False})
    monkeypatch.setattr(red, "_barrer", lambda mac: None)
    vivas: set[str] = set()
    monkeypatch.setattr(red, "es_la_placa", lambda host, timeout=1.5: host in vivas)
    yield vivas
    archivo.unlink(missing_ok=True)
    red.reiniciar_para_tests()


def test_exige_sesion(anon):
    assert anon.get("/api/red").status_code == 401
    assert anon.post("/api/red/redetectar").status_code == 401
    assert anon.post("/api/red/latido", json={}).status_code == 401


def test_estado_y_avisos_de_reserva(client, red_limpia):
    red_limpia.add("192.168.1.35")
    red.cargar()["esp32"]["ip"] = "192.168.1.35"
    e = client.get("/api/red").json()
    assert e["esp32"]["configurada"] and e["esp32"]["direccion"] == "192.168.1.35"
    assert e["esp32"]["enlace"]["state"] == "disabled"  # los tests no arrancan los puentes
    assert e["servidor"]["ips"] == ["192.168.1.36"] and e["ajustes"]["esp32"] == "192.168.1.60"
    claves = {a["clave"] for a in e["avisos"]}
    assert {"reserva-esp32", "reserva-servidor"} <= claves and "extension-url" not in claves
    assert "192.168.1.60" in next(a["texto"] for a in e["avisos"] if a["clave"] == "reserva-esp32")


def test_redetectar_encuentra_la_placa(client, red_limpia, monkeypatch):
    monkeypatch.setattr(mdns, "resolver", lambda *a, **k: "192.168.1.35")
    r = client.post("/api/red/redetectar").json()
    assert r["resultado"]["ok"] is False and r["resultado"]["motivo"] == "no-responde"
    red_limpia.add("192.168.1.35")
    r = client.post("/api/red/redetectar").json()
    assert r["resultado"] == {
        "ok": True,
        "ip": "192.168.1.35",
        "origen": "mdns",
        "cambio": True,
        "probadas": [["mdns", "192.168.1.35"]],
    }
    assert r["esp32"]["ip"] == "192.168.1.35" and r["esp32"]["en_linea"] is True


def test_probar_esp32_ip_y_servidor(client, red_limpia, monkeypatch):
    assert client.post("/api/red/probar", json={"que": "esp32"}).json()["ok"] is False
    red_limpia.add("192.168.1.60")
    r = client.post("/api/red/probar", json={"que": "esp32"}).json()
    assert r["ok"] is True and r["host"] == "192.168.1.60" and r["error"] == ""
    assert client.post("/api/red/probar", json={"que": "ip", "ip": "192.168.1.44"}).json()["ok"] is False
    r = client.post("/api/red/probar", json={"que": "ip", "ip": "300.1.1.1"})
    assert r.status_code == 422 and "0 a 255" in r.json()["error"]
    assert client.post("/api/red/probar", json={"que": "otra"}).status_code == 422

    monkeypatch.setenv("PANEL_HOST", "127.0.0.1")
    monkeypatch.setattr(red_api, "_probar_url", lambda url, timeout=3.0: {"url": url, "ok": True, "ms": 3, "error": ""})
    r = client.post("/api/red/probar", json={"que": "servidor"}).json()
    assert r["ok"] is True and [p["donde"] for p in r["pruebas"]] == ["este equipo"]


def test_probar_sin_placa(client, red_limpia, monkeypatch):
    monkeypatch.setattr(config, "ESP32_HOST", "")
    r = client.post("/api/red/probar", json={"que": "esp32"}).json()
    assert r["ok"] is False and "ESP32_HOST" in r["error"]
    assert client.get("/api/red").json()["esp32"]["configurada"] is False


def test_probar_url_no_lanza(monkeypatch):
    def cae(url, timeout):
        raise OSError("conexión rechazada")

    monkeypatch.setattr(red_api.urllib.request, "urlopen", cae)
    r = red_api._probar_url("http://127.0.0.1:9")
    assert r["ok"] is False and "rechazada" in r["error"]


def test_ajustes_validan_y_avisan(client, red_limpia):
    r = client.patch("/api/red/ajustes", json={"esp32_manual": "192.168.1.36"})
    assert r.status_code == 422 and "este equipo" in r.json()["error"]
    r = client.patch("/api/red/ajustes", json={"esp32_manual": "hola"})
    assert r.status_code == 422 and "IPv4" in r.json()["error"]
    e = client.patch("/api/red/ajustes", json={"esp32_manual": "192.168.1.35", "servidor": "192.168.1.36"}).json()
    assert e["esp32"]["manual"] == "192.168.1.35" and e["esp32"]["direccion"] == "192.168.1.35"
    assert e["servidor"]["coincide_reserva"] is True
    assert "reserva-servidor" not in {a["clave"] for a in e["avisos"]}
    e = client.patch("/api/red/ajustes", json={"esp32_manual": ""}).json()
    assert e["esp32"]["manual"] == "" and e["esp32"]["direccion"] == "192.168.1.60"


def test_latido_de_la_extension_con_su_token(anon, client, red_limpia, monkeypatch):
    monkeypatch.setenv("PANEL_HOST", "127.0.0.1")
    monkeypatch.setenv("PANEL_PORT", "8000")
    r = anon.post(
        "/api/red/latido",
        headers=AUTH,
        json={"version": "2.11", "url": "http://192.168.1.50:8000", "navegador": "Firefox"},
    )
    assert r.status_code == 200 and r.json()["principal"] == "http://127.0.0.1:8000"
    e = client.get("/api/red").json()
    assert e["extension"]["conocida"] and e["extension"]["version"] == "2.11" and e["extension"]["url_vigente"] is False
    assert "extension-url" in {a["clave"] for a in e["avisos"]}
    anon.post("/api/red/latido", headers=AUTH, json={"version": "2.11", "url": "http://127.0.0.1:8000/"})
    assert client.get("/api/red").json()["extension"]["url_vigente"] is True
    assert anon.post("/api/red/latido", headers=AUTH, json={"version": "x" * 50}).status_code == 422
