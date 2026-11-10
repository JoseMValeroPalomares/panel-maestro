"""Router de LLM (app/llm_router.py): orden, respaldo ante 429/timeout/5xx/JSON no válido, enfriamiento, cuotas y registro.
Todo con httpx.MockTransport: ningún test sale a la red."""
import itertools
import json

import httpx
import pytest

from app import llm_router
from app.database import get_db
from core import config

_ids = itertools.count()


@pytest.fixture()
def modelos(tmp_path, monkeypatch, client):
    """Escribe una lista de modelos de prueba (ids únicos por test) y devuelve sus ids."""
    def hacer(*specs, **cfg):
        n = next(_ids)
        lista = []
        for i, spec in enumerate(specs):
            m = {"id": f"t{n}-{i}", "proveedor": f"P{i}", "base_url": f"https://p{i}.test/v1", "modelo": f"m{i}",
                 "clave_env": f"CLAVE_TEST_{i}", "limite_dia": 0, "timeout_s": 5, "json_mode": True, **spec}
            lista.append(m)
            if (m.get("clave_env") or "").startswith("CLAVE_TEST_"):  # las demás se dejan sin valor a propósito
                monkeypatch.setenv(m["clave_env"], f"secreto-{i}")
        f = tmp_path / f"modelos-{n}.json"
        f.write_text(json.dumps({"max_intentos_total": 8, "reintentos_por_modelo": 2, "enfriamiento_429_s": 600, **cfg, "modelos": lista}))
        monkeypatch.setattr(config, "LLM_MODELS_FILE", f)
        return [m["id"] for m in lista]
    return hacer


def ok(contenido: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": contenido}}]})


def transporte(respuestas: dict[str, list]):
    """host → lista de respuestas (o excepciones) en orden; registra cada petición."""
    llamadas = []

    def handler(req: httpx.Request):
        llamadas.append(req)
        cola = respuestas[req.url.host]
        r = cola.pop(0) if len(cola) > 1 else cola[0]
        if isinstance(r, Exception):
            raise r
        return r
    return httpx.MockTransport(handler), llamadas


def test_primer_modelo_que_responde(modelos):
    ids = modelos({}, {})
    t, llamadas = transporte({"p0.test": [ok('{"a": 1}')], "p1.test": [ok('{"a": 2}')]})
    r = llm_router.completar([{"role": "user", "content": "hola"}], transport=t)
    assert r.datos == {"a": 1} and r.modelo_id == ids[0] and len(llamadas) == 1
    req = llamadas[0]
    assert req.headers["authorization"] == "Bearer secreto-0" and req.url.path == "/v1/chat/completions"
    body = json.loads(req.content)
    assert body["model"] == "m0" and body["response_format"] == {"type": "json_object"}


def test_429_enfria_el_modelo_y_pasa_al_siguiente(modelos):
    ids = modelos({}, {})
    t, llamadas = transporte({"p0.test": [httpx.Response(429, headers={"Retry-After": "120"})], "p1.test": [ok('{"ok": true}')]})
    ahora = 1_000_000.0
    r = llm_router.completar([], transport=t, reloj=lambda: ahora, dormir=lambda s: None)
    assert r.modelo_id == ids[1] and r.intentos == [{"modelo": ids[0], "error": "429 límite"}]
    with get_db() as conn:
        hasta = conn.execute("SELECT hasta FROM llm_enfriamiento WHERE modelo=?", (ids[0],)).fetchone()["hasta"]
    assert hasta == ahora + 120
    # mientras se enfría no se le llama
    llamadas.clear()
    r = llm_router.completar([], transport=t, reloj=lambda: ahora + 60, dormir=lambda s: None)
    assert [c.url.host for c in llamadas] == ["p1.test"] and r.intentos[0]["error"] == "en enfriamiento"
    # pasado el enfriamiento, vuelve a ser el primero
    t2, llamadas2 = transporte({"p0.test": [ok('{"x": 0}')], "p1.test": [ok("{}")]})
    assert llm_router.completar([], transport=t2, reloj=lambda: ahora + 121).modelo_id == ids[0]


def test_429_sin_retry_after_usa_el_enfriamiento_por_defecto(modelos):
    ids = modelos({}, {}, enfriamiento_429_s=300)
    t, _ = transporte({"p0.test": [httpx.Response(429)], "p1.test": [ok("{}")]})
    llm_router.completar([], transport=t, reloj=lambda: 500.0)
    with get_db() as conn:
        assert conn.execute("SELECT hasta FROM llm_enfriamiento WHERE modelo=?", (ids[0],)).fetchone()["hasta"] == 800.0


def test_timeout_y_5xx_se_reintentan_con_backoff(modelos):
    ids = modelos({}, {}, reintentos_por_modelo=3)
    esperas = []
    t, llamadas = transporte({"p0.test": [httpx.ReadTimeout("lento"), httpx.Response(503), ok('{"v": 1}')], "p1.test": [ok("{}")]})
    r = llm_router.completar([], transport=t, dormir=esperas.append)
    assert r.modelo_id == ids[0] and esperas == [1.0, 2.0] and len(llamadas) == 3
    assert [i["error"] for i in r.intentos] == ["timeout", "503 error del servidor"]


def test_timeout_agotado_pasa_al_siguiente(modelos):
    ids = modelos({}, {})
    t, _ = transporte({"p0.test": [httpx.ConnectTimeout("x")], "p1.test": [ok('{"v": 2}')]})
    r = llm_router.completar([], transport=t, dormir=lambda s: None)
    assert r.modelo_id == ids[1] and [i["error"] for i in r.intentos] == ["timeout", "timeout"]


def test_json_no_valido_vacio_o_esquema_malo_pasan_al_siguiente(modelos):
    ids = modelos({}, {}, {}, {})
    t, _ = transporte({"p0.test": [ok("esto no es json")], "p1.test": [ok("")], "p2.test": [ok('{"capas": 3}')],
                       "p3.test": [ok('```json\n{"capas": {}}\n```')]})

    def validar(d):
        if not isinstance(d.get("capas"), dict):
            raise ValueError("falta capas")
        return d
    r = llm_router.completar([], validar, transport=t)
    assert r.modelo_id == ids[3] and r.datos == {"capas": {}}  # el JSON entre ``` también vale
    assert [i["error"] for i in r.intentos] == ["JSON no válido", "respuesta vacía", "esquema no válido: falta capas"]


def test_errores_4xx_no_se_reintentan(modelos):
    ids = modelos({}, {})
    t, llamadas = transporte({"p0.test": [httpx.Response(401)], "p1.test": [ok("{}")]})
    r = llm_router.completar([], transport=t)
    assert r.modelo_id == ids[1] and [c.url.host for c in llamadas] == ["p0.test", "p1.test"]


def test_sin_clave_se_salta_y_sin_ninguna_avisa(modelos, monkeypatch):
    ids = modelos({"clave_env": "CLAVE_QUE_NO_EXISTE"}, {})
    monkeypatch.delenv("CLAVE_QUE_NO_EXISTE", raising=False)
    t, llamadas = transporte({"p1.test": [ok("{}")]})
    assert llm_router.completar([], transport=t).modelo_id == ids[1]
    modelos({"clave_env": "CLAVE_QUE_NO_EXISTE"})
    with pytest.raises(llm_router.LLMError) as e:
        llm_router.completar([], transport=t)
    assert e.value.sin_claves


def test_todos_fallan(modelos):
    modelos({}, {})
    t, _ = transporte({"p0.test": [httpx.Response(500)], "p1.test": [ok("nada")]})
    with pytest.raises(llm_router.LLMError) as e:
        llm_router.completar([], transport=t, dormir=lambda s: None)
    assert not e.value.sin_claves and len(e.value.intentos) == 3


def test_limite_total_de_intentos(modelos):
    modelos({}, {}, {}, max_intentos_total=2, reintentos_por_modelo=3)
    t, llamadas = transporte({"p0.test": [httpx.Response(500)], "p1.test": [ok("{}")], "p2.test": [ok("{}")]})
    with pytest.raises(llm_router.LLMError):
        llm_router.completar([], transport=t, dormir=lambda s: None)
    assert len(llamadas) == 2


def test_cuota_diaria_compartida(modelos):
    ids = modelos({"cuota": "compartida-x", "limite_dia": 2}, {"cuota": "compartida-x", "limite_dia": 2}, {})
    t, _ = transporte({"p0.test": [ok('{"n": 0}')], "p1.test": [ok('{"n": 1}')], "p2.test": [ok('{"n": 2}')]})
    assert llm_router.completar([], transport=t).modelo_id == ids[0]
    assert llm_router.completar([], transport=t).modelo_id == ids[0]
    r = llm_router.completar([], transport=t)  # la cuota la comparten los dos primeros: ya van 2
    assert r.modelo_id == ids[2] and [i["error"] for i in r.intentos] == ["cuota del día agotada"] * 2


def test_extra_del_proveedor_y_modelo_local_sin_clave(modelos):
    ids = modelos({"extra": {"provider": {"data_collection": "deny"}}, "json_mode": False}, {"clave_env": None, "local": True})
    t, llamadas = transporte({"p0.test": [httpx.Response(404)], "p1.test": [ok("{}")]})
    r = llm_router.completar([], transport=t)
    body = json.loads(llamadas[0].content)
    assert body["provider"] == {"data_collection": "deny"} and "response_format" not in body
    assert r.modelo_id == ids[1] and "authorization" not in llamadas[1].headers


def test_registro_y_estado_sin_contenido(modelos):
    ids = modelos({}, {})
    t, _ = transporte({"p0.test": [httpx.Response(500)], "p1.test": [ok('{"secreto": "no se guarda"}')]})
    llm_router.completar([{"role": "user", "content": "dato sensible"}], transport=t, dormir=lambda s: None)
    with get_db() as conn:
        filas = [dict(r) for r in conn.execute("SELECT * FROM llm_registro WHERE modelo IN (?, ?)", ids)]
    assert {f["ok"] for f in filas} == {0, 1} and not any("sensible" in json.dumps(f) or "secreto" in json.dumps(f) for f in filas)
    e = {m["id"]: m for m in llm_router.estado()["modelos"]}
    assert e[ids[1]]["clave"] and e[ids[1]]["ultima"]["ok"] == 1 and e[ids[0]]["uso_hoy"] == 2


def test_extraer_json():
    assert llm_router.extraer_json('Aquí tienes: {"a": 1} ¡listo!') == {"a": 1}
    with pytest.raises(Exception):
        llm_router.extraer_json("[1, 2]")


def test_config_por_defecto_sin_claves_en_el_repo():
    cfg = json.loads(llm_router.DEFAULT_FILE.read_text())
    assert cfg["modelos"] and not any(k in m for m in cfg["modelos"] for k in ("api_key", "clave", "key"))
    proveedores = {m["proveedor"] for m in cfg["modelos"]}
    assert {"OpenRouter", "Groq", "Google AI Studio", "GitHub Models"} <= proveedores
    assert all(m["extra"]["provider"]["data_collection"] == "deny" for m in cfg["modelos"] if m["proveedor"] == "OpenRouter")
