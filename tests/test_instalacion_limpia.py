"""Lo que ve quien acaba de instalar: sin placa ESP32 y sin datos todo funciona y lo dice."""
from comidas import main as comidas_main
from estudio import main as estudio_main


def test_sin_placa_no_se_intenta_conectar(client, monkeypatch):
    monkeypatch.setattr(estudio_main, "ESP32_HOST", "")
    monkeypatch.setattr(estudio_main, "ESP32_WS_URL", "")
    status = client.get("/estudio/api/esp32-status").json()
    assert status["host"] == "" and status["online"] is False and status["esp32_ws_url"] == ""
    assert "Sin panel ESP32" in client.get("/estudio/").text


def test_generar_la_semana_sin_platos_lo_explica(client, monkeypatch):
    monkeypatch.setattr(comidas_main, "_build_meal_catalog", lambda conn: {"comida": [], "cena": []})
    r = client.post("/comidas/api/weekly-plan/generate", json={"semana": "2026-10-26", "franjas": ["comida"]})
    assert r.status_code == 422 and "añade unos cuantos" in r.json()["detail"]
