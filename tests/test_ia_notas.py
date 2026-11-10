"""Corregir con IA: respaldo ante límites, rechazo de respuestas que rompen la nota, notas cifradas y sensibles,
presupuesto, aplicar por partes y deshacer. Los proveedores se simulan con httpx.MockTransport (nada sale a la red)."""
import itertools
import json
import time

import httpx
import pytest

from app import ia_notas, llm_router
from core import config

_n = itertools.count()
ORIG = """# Ohm

La tension es V = 12 V y la resistencia 4 ohmios, así que $I = V/R$ = 3 A.

| Magnitud | Unidad |
|---|---|
| V | voltio |

Ver [[Nota inicial]].
"""
BUENA = ORIG.replace("La tension", "La tensión")


def ok(texto):
    return httpx.Response(200, json={"choices": [{"message": {"content": texto}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 100, "completion_tokens": 80}})


@pytest.fixture()
def ia(tmp_path, monkeypatch, client):
    """ia(modelos, respuestas) → (transport, llamadas). Modelos con ids únicos; claves en el entorno."""
    def hacer(specs, respuestas, politica=None):
        n = next(_n)
        lista = []
        for i, sp in enumerate(specs):
            m = {"id": f"n{n}-{i}", "proveedor": f"P{i}", "base_url": f"https://q{n}x{i}.test/v1", "modelo": f"m{i}", "clave_env": f"CLAVE_IA_{n}_{i}",
                 "limite_dia": 0, "timeout_s": 5, "json_mode": False, **sp}
            lista.append(m)
            monkeypatch.setenv(m["clave_env"], "secreto")
        f = tmp_path / f"m{n}.json"
        f.write_text(json.dumps({"max_intentos_total": 12, "reintentos_por_modelo": 1, "enfriamiento_429_s": 600, "modelos": lista}))
        monkeypatch.setattr(config, "LLM_MODELS_FILE", f)
        llamadas = []

        def handler(req):
            llamadas.append(req)
            cola = respuestas[req.url.host.split("x")[1].split(".")[0]]
            return cola.pop(0) if len(cola) > 1 else cola[0]
        monkeypatch.setattr(ia_notas, "_transport", httpx.MockTransport(handler))
        llm_router.guardar_politica({"permitir_entrenan": False, "permitir_pago": False, "presupuesto_mes": 0, "categorias_sensibles": [], **(politica or {})})
        ia_notas._jobs.clear()
        ia_notas._recientes.clear()
        return [m["id"] for m in lista], llamadas
    return hacer


def crear(client, nid, contenido=ORIG, **extra):
    body = {"title": nid, "category": "Pruebas - IA", "content": contenido, "status": "en-desarrollo", **extra}
    assert client.post(f"/api/notes/{nid}", json=body).status_code == 200


def esperar(client, job):
    for _ in range(100):
        r = client.get(f"/api/ia/jobs/{job}").json()
        if r["estado"] not in ("cola", "trabajando"):
            return r
        time.sleep(0.05)
    raise AssertionError("el trabajo no terminó")


def texto(client, nid):
    return client.get(f"/api/notes/{nid}").json()["content"]


def test_sin_proveedor_explica_que_falta(client, tmp_path, monkeypatch):
    f = tmp_path / "vacio.json"
    f.write_text(json.dumps({"modelos": [{"id": "x", "base_url": "https://x.test/v1", "modelo": "m", "clave_env": "CLAVE_IA_INEXISTENTE"}]}))
    monkeypatch.setattr(config, "LLM_MODELS_FILE", f)
    crear(client, "ia-sin-proveedor")
    d = client.get("/api/notes/ia-sin-proveedor/ia").json()
    assert d["disponible"] is False and d["sin_claves"] and ".env" in d["motivo"]
    assert client.post("/api/notes/ia-sin-proveedor/ia/corregir").status_code == 409


def test_flujo_completo_con_respaldo_aplicar_por_partes_y_deshacer(client, ia):
    ids, llamadas = ia([{}, {}], {"0": [httpx.Response(429, headers={"retry-after": "30"})], "1": [ok(BUENA.replace("ohmios", "ohmios (Ω)").replace("Ver ", "Véase "))]})
    crear(client, "ia-flujo")
    job = client.post("/api/notes/ia-flujo/ia/corregir").json()["job"]
    r = esperar(client, job)
    assert r["estado"] == "listo" and r["modelo"]["id"] == ids[1]                       # respaldo tras el 429 del primero
    assert len(r["partes"]) == 2
    # acepta solo la primera parte
    assert client.post(f"/api/ia/jobs/{job}/aplicar", json={"aceptadas": [r["partes"][0]["id"]]}).json()["aplicadas"] == 1
    t = texto(client, "ia-flujo")
    assert "La tensión" in t and "Ver [[Nota inicial]]" in t and "Véase" not in t
    # historial: modelo que corrigió y estado
    h = client.get("/api/notes/ia-flujo/ia").json()["ultimas"][0]
    assert h["estado"] == "parcial" and h["proveedor"] == "P1"
    assert client.post("/api/notes/ia-flujo/ia/deshacer").status_code == 200
    assert texto(client, "ia-flujo").strip() == ORIG.strip()


def test_rechaza_formula_rota_y_etiquetas_y_pasa_al_siguiente(client, ia):
    rota = BUENA.replace("$I = V/R$", "$I = \\frac{V}{R$")
    etiquetas = BUENA + "\n#electricidad #fisica #ohm #circuitos\n"
    ids, llamadas = ia([{}, {}, {}], {"0": [ok(rota)], "1": [ok(etiquetas)], "2": [ok(BUENA)]})
    crear(client, "ia-rechazo")
    r = esperar(client, client.post("/api/notes/ia-rechazo/ia/corregir").json()["job"])
    assert r["estado"] == "listo" and r["modelo"]["id"] == ids[2]
    assert len(llamadas) == 5            # dos intentos (normal + estricto) con cada uno de los dos primeros, y uno del tercero
    assert sum("esquema no válido" in i["error"] for i in r["intentos"]) == 4


def test_enlace_a_nota_inexistente_se_rechaza(client, ia):
    ids, _ = ia([{}], {"0": [ok(BUENA.replace("[[Nota inicial]]", "[[Inventada]]"))]})
    crear(client, "ia-enlace")
    r = esperar(client, client.post("/api/notes/ia-enlace/ia/corregir").json()["job"])
    assert r["estado"] == "error" and "no existe" in r["error"]


def test_nunca_envia_notas_cifradas(client, ia):
    _, llamadas = ia([{}], {"0": [ok(BUENA)]})
    crear(client, "ia-cifrada", contenido="U2FsdGVkX19cifrado", encrypted=True)
    d = client.get("/api/notes/ia-cifrada/ia").json()
    assert d["disponible"] is False and "cifradas" in d["motivo"]
    assert client.post("/api/notes/ia-cifrada/ia/corregir").status_code == 403
    assert llamadas == []


def test_proveedores_que_entrenan_y_notas_sensibles(client, ia):
    ids, llamadas = ia([{"entrena": True}, {}], {"0": [ok(BUENA)], "1": [ok(BUENA)]})
    crear(client, "ia-entrena")
    r = esperar(client, client.post("/api/notes/ia-entrena/ia/corregir").json()["job"])
    assert r["modelo"]["id"] == ids[1]                      # por defecto no se usa el que entrena
    ids, llamadas = ia([{"entrena": True}], {"0": [ok(BUENA)]}, politica={"permitir_entrenan": True})
    crear(client, "ia-sensible")
    assert client.put("/api/notes/ia-sensible/sensible", json={"sensible": True}).status_code == 200
    d = client.get("/api/notes/ia-sensible/ia").json()
    assert d["sensible"] and d["disponible"] is False       # sensible + solo entrena → ninguno
    r = client.post("/api/notes/ia-sensible/ia/corregir")
    assert r.status_code == 409 and "política" in r.json()["error" if "error" in r.json() else "detail"] and llamadas == []
    assert "sensible: true" in (config.NOTES_DIR / "ia-sensible.md").read_text()


def test_presupuesto_nunca_se_supera(client, ia):
    pago = {"pago": True, "precio_in_1m": 3000.0, "precio_out_1m": 15000.0}
    ids, llamadas = ia([pago], {"0": [ok(BUENA)]}, politica={"permitir_pago": True, "presupuesto_mes": 0.001})
    crear(client, "ia-pago")
    r = client.post("/api/notes/ia-pago/ia/corregir")
    assert r.status_code == 409 and "presupuesto" in json.dumps(r.json()) and llamadas == []
    ids, llamadas = ia([{"pago": True, "precio_in_1m": 3.0, "precio_out_1m": 15.0}], {"0": [ok(BUENA)]}, politica={"permitir_pago": True, "presupuesto_mes": 5})
    r = esperar(client, client.post("/api/notes/ia-pago/ia/corregir").json()["job"])
    assert r["estado"] == "listo" and r["coste"] > 0 and llm_router.gasto_mes() > 0


def test_cancelar_y_nota_cambiada(client, ia):
    ia([{}], {"0": [ok(BUENA)]})
    crear(client, "ia-cambia")
    r = esperar(client, client.post("/api/notes/ia-cambia/ia/corregir").json()["job"])
    crear(client, "ia-cambia", contenido=ORIG + "\nAñadido a mano.\n")
    lista = [k for k, j in ia_notas._jobs.items() if j.note_id == "ia-cambia" and j.estado == "listo"]
    assert lista and client.post(f"/api/ia/jobs/{lista[0]}/aplicar", json={}).status_code == 409


def test_registro_sin_contenido(client, ia):
    ia([{}], {"0": [ok(BUENA)]})
    crear(client, "ia-log")
    esperar(client, client.post("/api/notes/ia-log/ia/corregir").json()["job"])
    from app.database import get_db
    with get_db() as conn:
        filas = [dict(r) for r in conn.execute("SELECT * FROM llm_registro WHERE uso='notas'")]
    assert filas and all("tension" not in json.dumps(f) and "Ohm" not in json.dumps(f) for f in filas)
    assert filas[-1]["tokens_in"] == 100 and filas[-1]["ok"] == 1


def test_deshacer_cuando_la_version_previa_ya_era_identica(client, ia):
    """El front guarda justo antes de corregir: la última versión ya coincide con la nota y snapshot() devuelve None."""
    ia([{}], {"0": [ok(BUENA)]})
    crear(client, "ia-identica")
    crear(client, "ia-identica", contenido=ORIG + " ")      # un guardado más: queda una versión con el contenido anterior
    crear(client, "ia-identica", contenido=ORIG)
    job = client.post("/api/notes/ia-identica/ia/corregir").json()["job"]
    esperar(client, job)
    assert client.post(f"/api/ia/jobs/{job}/aplicar", json={}).status_code == 200
    assert "tensión" in texto(client, "ia-identica")
    assert client.post("/api/notes/ia-identica/ia/deshacer").status_code == 200
    assert "La tension" in texto(client, "ia-identica")


def test_dividir_respeta_encabezados_y_bloques():
    texto = "# T\n\n" + "\n".join(f"## S{i}\n" + ("palabra " * 60 + "\n") for i in range(10)) + "\n```python\n" + "x = 1\n" * 300 + "```\n"
    trozos = ia_notas.dividir(texto, 400)                         # ≈ 1 400 caracteres por trozo
    assert len(trozos) > 3 and "\n".join(trozos) == texto           # no se pierde ni se inventa nada
    assert all(t.count("```") % 2 == 0 for t in trozos)              # un bloque de código nunca se parte
    assert ia_notas.dividir("corto", 400) == ["corto"]


def test_nota_larga_se_corrige_por_trozos_en_un_modelo_de_contexto_pequeno(client, ia):
    larga = "# Larga\n\n" + "\n".join(f"## Parte {i}\n\nLa tension es {i} V en el circuito de prueba numero {i}, con mas texto de relleno para pesar.\n" for i in range(40))
    ids, llamadas = ia([{"max_entrada_tokens": 2600}], {"0": [ok("x")]})   # la guía+títulos ocupan ≈ 2 000: solo caben trozos pequeños
    import httpx as _h

    def eco(req):
        import json as _j
        nota = _j.loads(req.content)["messages"][-1]["content"].split("=== NOTA ===\n", 1)[1]
        llamadas.append(req)
        return _h.Response(200, json={"choices": [{"message": {"content": nota.replace("tension", "tensión")}, "finish_reason": "stop"}]})
    ia_notas._transport = _h.MockTransport(eco)
    llamadas.clear()
    crear(client, "ia-larga", contenido=larga)
    r = esperar(client, client.post("/api/notes/ia-larga/ia/corregir").json()["job"])
    assert r["estado"] == "listo" and len(llamadas) > 1                      # varias peticiones, cada una dentro del límite
    assert len(r["partes"]) >= 1 and all("tensión" in "".join(p["despues"]) for p in r["partes"])


def test_prompt_para_chat_incluye_contexto_formato_simulaciones_y_titulos(client):
    crear(client, "ia-prompt-a", contenido="x")
    p = client.get("/api/ia/prompt").json()["prompt"]
    for frag in ("Panel", "[[Título exacto]]", "$$P = V", "Pregunta >> Respuesta", "```sim", "NO hay red", "SIN cambiar mi forma de explicar",
                 "NO añadas información nueva", "cuatro comillas invertidas", "Mis reglas de estilo", "ia-prompt-a"):
        assert frag.replace("NO hay red", "NO hay red") in p, frag
    assert "<!--" not in p.split("# Mis reglas de estilo")[1].split("# Notas existentes")[0].replace("<!-- REVISAR", "")   # los comentarios de la guía no se envían
