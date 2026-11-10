"""Rendimiento: alertas guardadas como tareas, rutinas marcadas, exportación y auditoría con IA
(privacidad, esquema, caché, tarea de mañana y nota semanal). Los modelos se simulan con httpx.MockTransport."""
import json
from datetime import date, timedelta

import httpx
import pytest

from app import rendimiento_ia
from app.database import get_db
from core import config

HOY = date.today()


def dia(**kw):
    return {"acostarse": "23:30", "despertar": "07:30", "calidad_sueno": 4, "energia": 3, "niebla": 2, "humor": 4,
            "bloques": [{"asignatura": "Física cuántica", "minutos": 60, "recall": True, "codificacion": "problemas"}], **kw}


def test_alertas_se_guardan_y_crean_una_tarea_por_regla(client):
    # Dos noches tarde (ayer y hoy) → alerta circadiana con tarea; repetirla no duplica la tarea
    ayer = (HOY - timedelta(days=1)).isoformat()
    client.put(f"/api/rendimiento/dia/{ayer}", json=dia(acostarse="01:10"))
    r = client.put(f"/api/rendimiento/dia/{HOY.isoformat()}", json=dia(acostarse="01:20")).json()
    circ = next(a for a in r["alertas"] if a["id"] == "circadiana")
    assert circ["item_id"]
    item = next(i for i in client.get("/api/items").json()["items"] if i["id"] == circ["item_id"])
    assert item["category"] == "Rendimiento" and item["priority"] == "alta" and "circadiana" in item["text"].lower()
    r2 = client.put(f"/api/rendimiento/dia/{HOY.isoformat()}", json=dia(acostarse="01:25")).json()
    assert next(a for a in r2["alertas"] if a["id"] == "circadiana")["item_id"] == circ["item_id"]
    hist = client.get("/api/rendimiento/alertas", params={"dias": 7}).json()["alertas"]
    assert any(a["regla"] == "circadiana" and a["fecha"] == HOY.isoformat() for a in hist)
    # si deja de saltar, se quita del día (la tarea se queda: ya es tuya)
    r3 = client.put(f"/api/rendimiento/dia/{HOY.isoformat()}", json=dia()).json()
    assert not any(a["id"] == "circadiana" for a in r3["alertas"])
    assert not any(a["regla"] == "circadiana" and a["fecha"] == HOY.isoformat() for a in client.get("/api/rendimiento/alertas").json()["alertas"])
    assert any(i["id"] == circ["item_id"] for i in client.get("/api/items").json()["items"])


def test_rellenar_dias_antiguos_no_crea_tareas(client):
    viejo = [(HOY - timedelta(days=n)).isoformat() for n in (40, 41)]
    for f in reversed(viejo):  # la noche anterior primero: la regla mira dos noches seguidas
        client.put(f"/api/rendimiento/dia/{f}", json=dia(acostarse="02:00"))
    a = client.get("/api/rendimiento/alertas", params={"dias": 1, "hasta": viejo[0]}).json()["alertas"]
    assert any(x["regla"] == "circadiana" for x in a) and all(x["item_id"] is None for x in a)


def test_registrar_marca_las_rutinas(client):
    gym = client.post("/api/items", json={"text": "Gym rend", "type": "rutina", "repeat": {"freq": "daily"}}).json()["id"]
    sol = client.post("/api/items", json={"text": "Sol rend", "type": "rutina", "repeat": {"freq": "daily"}}).json()["id"]
    client.put("/api/rendimiento/ajustes", json={"rutinas": {"entreno": gym, "luz_solar": sol, "activacion": 0}})
    f = (HOY - timedelta(days=2)).isoformat()
    r = client.put(f"/api/rendimiento/dia/{f}", json=dia(entreno=True, entreno_fin="19:00", luz_solar=False)).json()
    assert r["rutinas_marcadas"] == ["Gym rend"]
    with get_db() as conn:
        assert conn.execute("SELECT 1 FROM routine_checks WHERE item_id=? AND day=?", (gym, f)).fetchone()
        assert not conn.execute("SELECT 1 FROM routine_checks WHERE item_id=? AND day=?", (sol, f)).fetchone()
    # guardar otra vez no la vuelve a marcar (ya lo está) y quitar el entreno no la desmarca
    assert client.put(f"/api/rendimiento/dia/{f}", json=dia(entreno=False)).json()["rutinas_marcadas"] == []
    with get_db() as conn:
        assert conn.execute("SELECT 1 FROM routine_checks WHERE item_id=? AND day=?", (gym, f)).fetchone()
    client.put("/api/rendimiento/ajustes", json={"rutinas": {}})


def test_exportar(client):
    f = (HOY - timedelta(days=60)).isoformat()
    client.put(f"/api/rendimiento/dia/{f}", json=dia(nota="Hoy bien"))
    j = client.get("/api/rendimiento/exportar", params={"formato": "json"})
    assert j.status_code == 200 and "attachment" in j.headers["content-disposition"]
    d = next(x for x in j.json()["dias"] if x["fecha"] == f)
    assert d["nota"] == "Hoy bien" and d["bloques"][0]["asignatura"] == "Física cuántica"
    c = client.get("/api/rendimiento/exportar", params={"formato": "csv"})
    assert c.headers["content-type"].startswith("text/csv") and f in c.text and "acostarse" in c.text.splitlines()[0]
    b = client.get("/api/rendimiento/exportar", params={"formato": "csv", "tabla": "bloques"})
    assert "Física cuántica" in b.text
    assert client.get("/api/rendimiento/exportar", params={"formato": "xml"}).status_code == 422


# ── Auditoría con IA ──────────────────────────────────────────────────────────

RESPUESTA = {"capas": {c: {"estado": "ámbar" if c == "sueno" else "verde", "diagnostico": f"Diagnóstico {c} con d0.", "correccion": f"Corrección {c}."}
                       for c in ("metabolico", "codificacion", "sueno", "rotacion")},
             "prioridad_manana": "Acostarte antes de las 23:30 y empezar con Active Recall de A.", "alertas": [{"texto": "Sueño corto en d-1"}, "Otra"]}


@pytest.fixture()
def ia(tmp_path, monkeypatch, client):
    f = tmp_path / "m.json"
    f.write_text(json.dumps({"modelos": [
        {"id": "ia-test-or", "proveedor": "OpenRouter", "base_url": "https://or.test/v1", "modelo": "x:free", "clave_env": "CLAVE_IA_TEST",
         "extra": {"provider": {"data_collection": "deny"}}, "json_mode": True},
        {"id": "ia-test-b", "proveedor": "B", "base_url": "https://b.test/v1", "modelo": "y", "clave_env": "CLAVE_IA_TEST"}]}))
    monkeypatch.setattr(config, "LLM_MODELS_FILE", f)
    monkeypatch.setenv("CLAVE_IA_TEST", "k")
    llamadas = []

    def preparar(respuestas):
        def handler(req):
            llamadas.append(req)
            r = respuestas.pop(0) if len(respuestas) > 1 else respuestas[0]
            return r
        return httpx.MockTransport(handler)
    return preparar, llamadas


def ok(d):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(d) if isinstance(d, dict) else d}}]})


def test_auditoria_diaria_privacidad_esquema_cache_y_tarea(client, ia):
    preparar, llamadas = ia
    f = HOY.isoformat()
    client.put(f"/api/rendimiento/dia/{f}", json=dia(nota="Hablé con Marta del examen"))
    # el primer modelo devuelve algo que no cumple el esquema → pasa al segundo
    t = preparar([ok({"capas": {}}), ok(RESPUESTA)])
    r = rendimiento_ia.auditar("dia", f, transport=t, dormir=lambda s: None)
    assert r["cache"] is False and r["modelo"] == "y" and r["intentos_fallidos"] == 1
    assert r["resultado"]["capas"]["sueno"]["estado"] == "ambar" and r["resultado"]["alertas"] == ["Sueño corto en d-1", "Otra"]
    enviado = json.loads(llamadas[0].content)
    texto = json.dumps(enviado, ensure_ascii=False)
    assert enviado["provider"] == {"data_collection": "deny"}
    assert "Marta" not in texto and "Física cuántica" not in texto and f not in texto  # sin nota, nombres ni fechas reales
    datos = json.loads(enviado["messages"][1]["content"].split("\n", 1)[1])
    assert datos["dias"][-1]["dia"] == "d0" and datos["dias"][-1]["bloques"][0]["asignatura"] == "A"
    assert "neurobiología del rendimiento" in enviado["messages"][0]["content"] and '"prioridad_manana"' in enviado["messages"][0]["content"]
    # tarea «Prioridad de mañana» para mañana
    manana = (HOY + timedelta(days=1)).isoformat()
    tarea = next(i for i in client.get("/api/items").json()["items"] if i["id"] == r["tarea_id"])
    assert tarea["due_date"] == manana and tarea["text"].startswith("Prioridad de mañana")
    # mismos datos → caché, sin llamar a nadie
    n = len(llamadas)
    r2 = rendimiento_ia.auditar("dia", f, transport=t)
    assert r2["cache"] is True and r2["id"] == r["id"] and len(llamadas) == n
    # forzar repite la llamada y actualiza la misma tarea
    r3 = rendimiento_ia.auditar("dia", f, forzar=True, transport=preparar([ok(RESPUESTA)]))
    assert r3["cache"] is False and r3["tarea_id"] == r["tarea_id"]
    # el historial la tiene
    h = client.get("/api/rendimiento/ia/historial").json()["auditorias"]
    assert h[0]["id"] == r3["id"] and h[0]["tarea_pendiente"]


def test_incluir_la_nota_si_se_pide(client, ia):
    preparar, llamadas = ia
    f = (HOY - timedelta(days=3)).isoformat()
    client.put(f"/api/rendimiento/dia/{f}", json=dia(nota="Me dolía la espalda"))
    client.put("/api/rendimiento/ajustes", json={"ia_incluir_nota": True})
    rendimiento_ia.auditar("dia", f, transport=preparar([ok(RESPUESTA)]))
    assert "Me dolía la espalda" in llamadas[-1].content.decode()
    client.put("/api/rendimiento/ajustes", json={"ia_incluir_nota": False})


def test_auditoria_semanal_se_guarda_como_nota(client, ia):
    preparar, _ = ia
    f = (HOY - timedelta(days=5)).isoformat()
    client.put(f"/api/rendimiento/dia/{f}", json=dia())
    r = rendimiento_ia.auditar("semana", f, transport=preparar([ok(RESPUESTA)]))
    assert r["periodo"].count("-W") == 1 and r["nota_id"].startswith("auditoria-rendimiento-")
    md = (config.NOTES_DIR / f"{r['nota_id']}.md").read_text()
    assert "category: Rendimiento - Auditorías" in md and "Calidad de codificación" in md and "Diagnóstico sueno" in md
    assert client.get(f"/api/notes/{r['nota_id']}").status_code == 200


def test_sin_claves_o_sin_datos_degrada_con_mensaje(client, ia, monkeypatch):
    monkeypatch.delenv("CLAVE_IA_TEST")
    f = (HOY - timedelta(days=5)).isoformat()
    client.put(f"/api/rendimiento/dia/{f}", json=dia())
    r = client.post("/api/rendimiento/ia/auditar", json={"tipo": "dia", "fecha": f, "forzar": True})
    assert r.status_code == 503 and r.json()["detail"]["sin_claves"] is True
    vacio = (HOY - timedelta(days=200)).isoformat()
    assert client.post("/api/rendimiento/ia/auditar", json={"tipo": "dia", "fecha": vacio}).status_code == 422
    assert client.post("/api/rendimiento/ia/auditar", json={"tipo": "mes"}).status_code == 422
    # el resto sigue funcionando
    assert client.get("/api/rendimiento/panel").status_code == 200


def test_estado_y_prompt_editable(client, ia):
    e = client.get("/api/rendimiento/ia/estado").json()
    assert e["configurados"] == 2 and "entrenar" in e["aviso"] and not e["prompt_propio"]
    client.put("/api/rendimiento/ajustes", json={"ia_prompt": "Sé breve."})
    e = client.get("/api/rendimiento/ia/estado").json()
    assert e["prompt"] == "Sé breve." and e["prompt_propio"]
    client.put("/api/rendimiento/ajustes", json={"ia_prompt": ""})  # vacío = volver al de serie
    assert client.get("/api/rendimiento/ia/estado").json()["prompt"] == rendimiento_ia.PROMPT_DEFECTO
    assert client.put("/api/rendimiento/ajustes", json={"ia_prompt": "x" * 7000}).status_code == 422
