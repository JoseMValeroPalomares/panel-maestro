# ruff: noqa: F811 — «ia» es el fixture de tests/test_ia_notas.py, importado aquí
"""F-4: flashcards propuestas por la IA desde una nota. Proveedores simulados con httpx.MockTransport (nada sale a la
red): propuesta válida, respuesta inventada descartada, nota sensible sin proveedor permitido, añadir y deshacer."""

import json

from app import ia_validacion
from app.database import get_db
from tests.test_ia_notas import crear, esperar, ia, ok, texto  # noqa: F401 — «ia» es un fixture

NOTA = """# Neurona

El potencial de reposo de la neurona es de -70 mV.
La bomba de sodio-potasio saca 3 iones de sodio y mete 2 de potasio.
La mielina aumenta la velocidad de conducción del impulso.

¿Qué es la sinapsis? >> La unión entre dos neuronas.
"""


def tarjetas(*pares):
    return ok(json.dumps({"tarjetas": [{"pregunta": q, "respuesta": a} for q, a in pares]}, ensure_ascii=False))


BUENAS = tarjetas(
    ("¿Cuál es el potencial de reposo de la neurona?", "-70 mV"),
    ("¿Qué hace la bomba de sodio-potasio?", "Saca 3 iones de sodio y mete 2 de potasio"),
    ("¿Qué aumenta la mielina?", "La velocidad de conducción del impulso"),
)


def flashcards_bd(nid):
    with get_db() as conn:
        return [r["question"] for r in conn.execute("SELECT question FROM flashcards WHERE note_id=?", (nid,))]


def test_propuesta_valida_se_anade_bajo_flashcards_y_se_deshace(client, ia):
    ids, llamadas = ia([{}], {"0": [BUENAS]})
    crear(client, "fc-ok", contenido=NOTA)
    job = client.post("/api/notes/fc-ok/ia/flashcards").json()["job"]
    r = esperar(client, job)
    assert r["estado"] == "listo" and r["tipo"] == "flashcards" and r["modelo"]["id"] == ids[0]
    assert [t["pregunta"] for t in r["tarjetas"]][0] == "¿Cuál es el potencial de reposo de la neurona?"
    # el modelo solo recibe la nota y las preguntas que ya existen
    enviado = json.loads(llamadas[0].content)["messages"][1]["content"]
    assert "¿Qué es la sinapsis?" in enviado and "-70 mV" in enviado
    assert texto(client, "fc-ok").strip() == NOTA.strip()  # nada escrito todavía

    # elige dos, una editada
    elegidas = [
        {"pregunta": r["tarjetas"][0]["pregunta"], "respuesta": "-70 mV (milivoltios)"},
        {"pregunta": r["tarjetas"][2]["pregunta"], "respuesta": r["tarjetas"][2]["respuesta"]},
    ]
    a = client.post(f"/api/ia/jobs/{job}/flashcards", json={"tarjetas": elegidas}).json()
    assert a["anadidas"] == 2
    t = texto(client, "fc-ok")
    assert "## Flashcards\n\n¿Cuál es el potencial de reposo de la neurona? >> -70 mV (milivoltios)\n" in t
    assert "¿Qué aumenta la mielina? >> La velocidad de conducción del impulso" in t
    assert set(flashcards_bd("fc-ok")) == {
        "¿Qué es la sinapsis?",
        "¿Cuál es el potencial de reposo de la neurona?",
        "¿Qué aumenta la mielina?",
    }
    # no se aplica dos veces
    assert client.post(f"/api/ia/jobs/{job}/flashcards", json={"tarjetas": elegidas}).status_code == 409
    # deshacer devuelve la nota y quita las tarjetas
    assert client.post("/api/notes/fc-ok/ia/deshacer").status_code == 200
    assert texto(client, "fc-ok").strip() == NOTA.strip()
    assert flashcards_bd("fc-ok") == ["¿Qué es la sinapsis?"]


def test_respuesta_inventada_se_descarta(client, ia):
    mezcla = tarjetas(
        ("¿Cuál es el potencial de reposo?", "-70 mV"),
        ("¿Qué neurotransmisor libera la placa motora?", "Acetilcolina"),  # no está en la nota
        ("¿Cuántos iones de sodio saca la bomba?", "5 iones"),  # número inventado
        ("¿Qué es la sinapsis?", "La unión entre dos neuronas."),  # ya existe
    )
    ids, _ = ia([{}], {"0": [mezcla]})
    crear(client, "fc-inventada", contenido=NOTA)
    r = esperar(client, client.post("/api/notes/fc-inventada/ia/flashcards").json()["job"])
    assert r["estado"] == "listo"
    assert [t["respuesta"] for t in r["tarjetas"]] == ["-70 mV"]
    motivos = sorted(d["motivo"] for d in r["descartadas"])
    assert motivos == ["esa pregunta ya existe", "la respuesta no está en la nota", "la respuesta no está en la nota"]


def test_todas_inventadas_pasa_al_siguiente_modelo(client, ia):
    inventadas = tarjetas(("¿Qué es el axón hillock?", "La zona de disparo del axón"))
    ids, llamadas = ia([{}, {}], {"0": [inventadas], "1": [BUENAS]})
    crear(client, "fc-respaldo", contenido=NOTA)
    r = esperar(client, client.post("/api/notes/fc-respaldo/ia/flashcards").json()["job"])
    assert r["estado"] == "listo" and r["modelo"]["id"] == ids[1]
    assert any("esquema no válido" in i["error"] for i in r["intentos"])


def test_nota_sensible_sin_proveedor_permitido(client, ia):
    ids, llamadas = ia([{"entrena": True}], {"0": [BUENAS]}, politica={"permitir_entrenan": True})
    crear(client, "fc-sensible", contenido=NOTA)
    client.put("/api/notes/fc-sensible/sensible", json={"sensible": True})
    d = client.get("/api/notes/fc-sensible/ia").json()
    assert d["sensible"] and d["disponible"] is False and "sensible" in d["motivo"]
    r = client.post("/api/notes/fc-sensible/ia/flashcards")
    assert r.status_code == 409 and llamadas == []


def test_cifrada_vacia_y_un_trabajo_a_la_vez(client, ia):
    ia([{}], {"0": [BUENAS]})
    crear(client, "fc-cifrada", contenido="U2FsdGVkX19cifrado", encrypted=True)
    assert client.post("/api/notes/fc-cifrada/ia/flashcards").status_code == 403
    crear(client, "fc-vacia", contenido="   ")
    assert client.post("/api/notes/fc-vacia/ia/flashcards").status_code == 400


def test_anadir_valida_formato_y_repetidas(client, ia):
    ia([{}], {"0": [BUENAS]})
    crear(client, "fc-formato", contenido=NOTA)
    job = client.post("/api/notes/fc-formato/ia/flashcards").json()["job"]
    esperar(client, job)
    url = f"/api/ia/jobs/{job}/flashcards"
    assert client.post(url, json={"tarjetas": [{"pregunta": "a >> b", "respuesta": "c"}]}).status_code == 422
    assert (
        client.post(url, json={"tarjetas": [{"pregunta": "¿Qué es la sinapsis?", "respuesta": "x"}]}).status_code == 422
    )
    dos = [{"pregunta": "¿Uno?", "respuesta": "x"}, {"pregunta": "¿uno?", "respuesta": "y"}]
    assert client.post(url, json={"tarjetas": dos}).status_code == 422
    muchas = [{"pregunta": f"¿Pregunta {i}?", "respuesta": "x"} for i in range(16)]
    assert client.post(url, json={"tarjetas": muchas}).status_code == 422
    # ninguna elegida = descartar sin tocar la nota
    assert client.post(url, json={"tarjetas": []}).json()["anadidas"] == 0
    assert texto(client, "fc-formato").strip() == NOTA.strip()


def test_la_nota_cambio_mientras_tanto(client, ia):
    ia([{}], {"0": [BUENAS]})
    crear(client, "fc-cambio", contenido=NOTA)
    job = client.post("/api/notes/fc-cambio/ia/flashcards").json()["job"]
    r = esperar(client, job)
    crear(client, "fc-cambio", contenido=NOTA + "\nOtra línea.")
    elegidas = [{"pregunta": t["pregunta"], "respuesta": t["respuesta"]} for t in r["tarjetas"]]
    assert client.post(f"/api/ia/jobs/{job}/flashcards", json={"tarjetas": elegidas}).status_code == 409


def test_respuesta_en_nota_y_anadir():
    assert ia_validacion.respuesta_en_nota("-70 mV", NOTA)
    assert ia_validacion.respuesta_en_nota("la velocidad de conduccion del impulso", NOTA)  # sin tildes
    assert not ia_validacion.respuesta_en_nota("-90 mV", NOTA)
    assert not ia_validacion.respuesta_en_nota("Acetilcolina", NOTA)
    out = ia_validacion.anadir_flashcards(
        "# A\n\n## Flashcards\n\nP1 >> R1\n\n## B\ntexto", [{"pregunta": "P2", "respuesta": "R2"}]
    )
    assert out == "# A\n\n## Flashcards\n\nP1 >> R1\nP2 >> R2\n\n## B\ntexto"
    assert (
        ia_validacion.anadir_flashcards("# A", [{"pregunta": "P", "respuesta": "R"}])
        == "# A\n\n## Flashcards\n\nP >> R\n"
    )
