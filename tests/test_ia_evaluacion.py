"""Script de evaluación de modelos con notas sintéticas y un proveedor simulado."""
import json

import httpx

from app import ia_validacion
from core import config
from scripts import evaluar_modelos as ev


def test_fixtures_sinteticos_son_validos_por_si_mismos():
    for nombre, t in {p.stem: p.read_text(encoding="utf-8") for p in ev.FIXTURES.glob("*.md")}.items():
        assert ia_validacion.validar(t, t, ev.TITULOS) == [], nombre


def test_puntua_un_modelo_bueno_y_uno_malo(client, tmp_path, monkeypatch):
    f = tmp_path / "m.json"
    f.write_text(json.dumps({"reintentos_por_modelo": 1, "modelos": [
        {"id": "ev-bueno", "base_url": "https://bueno.test/v1", "modelo": "m", "clave_env": "CLAVE_EV"},
        {"id": "ev-malo", "base_url": "https://malo.test/v1", "modelo": "m", "clave_env": "CLAVE_EV"}]}))
    monkeypatch.setattr(config, "LLM_MODELS_FILE", f)
    monkeypatch.setenv("CLAVE_EV", "x")
    notas = {p.stem: p.read_text(encoding="utf-8") for p in ev.FIXTURES.glob("*.md")}

    def handler(req):
        user = json.loads(req.content)["messages"][-1]["content"]
        nota = user.split("=== NOTA ===\n", 1)[1]
        texto = nota if req.url.host == "bueno.test" else "He corregido la nota. #etiqueta"
        return httpx.Response(200, json={"choices": [{"message": {"content": texto}, "finish_reason": "stop"}]})
    t = httpx.MockTransport(handler)
    ms = {m["id"]: m for m in __import__("app.llm_router", fromlist=["x"]).cargar_config()["modelos"]}
    assert ev.evaluar(ms["ev-bueno"], notas, t)["puntuacion"] == 1.0
    assert ev.evaluar(ms["ev-malo"], notas, t)["puntuacion"] == 0.0
