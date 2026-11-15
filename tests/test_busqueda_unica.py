"""F-3: una sola búsqueda (FTS5) para notas, tareas/ideas/rutinas, recursos del Baúl y eventos."""

import uuid

import pytest

from app import search
from app.database import get_db


def _buscar(client, q, **kw):
    r = client.get("/api/search", params={"q": q, "contexto": "todo", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _nota(client, note_id, title, content, **kw):
    r = client.post(
        f"/api/notes/{note_id}", json={"title": title, "category": "Buscar - Única", "content": content, **kw}
    )
    assert r.status_code == 200, r.text


def _recurso(title, description="", channel="", category="Lectura", contexto="puntual"):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO resources (url, title, description, channel, category, contexto) VALUES (?, ?, ?, ?, ?, ?)",
            (f"https://example.org/{uuid.uuid4().hex}", title, description, channel, category, contexto),
        )
        return cur.lastrowid


@pytest.mark.parametrize("q", ["fotosíntesis", "fotosintesis", "FOTOSINT"])
def test_cada_tipo_aparece_con_y_sin_tildes(client, q):
    _nota(client, "bu-nota", "Apuntes de botánica", "La fotosíntesis convierte la luz en azúcar.")
    t = client.post("/api/items", json={"text": "Repasar la fotosíntesis C4", "type": "tarea"}).json()
    i = client.post(
        "/api/items", json={"text": "Idea suelta", "type": "idea", "details": "Vídeo sobre fotosíntesis"}
    ).json()
    rid = _recurso("Clase de biología", description="Fotosíntesis explicada en 10 minutos", channel="Canal Ciencia")
    ev = client.post(
        "/api/calendar/events",
        json={"title": "Seminario", "start": "2026-12-01T10:00", "notes": "Charla: fotosíntesis"},
    ).json()
    r = _buscar(client, q)
    assert "bu-nota" in [n["id"] for n in r["notes"]]
    ids = [x["id"] for x in r["items"]]
    assert t["id"] in ids and i["id"] in ids
    assert rid in [x["id"] for x in r["resources"]]
    assert ev["id"] in [x["id"] for x in r["events"]]
    # enlace directo a cada sitio
    assert next(x for x in r["items"] if x["id"] == t["id"])["href"] == f"/tareas?item={t['id']}"
    assert next(x for x in r["resources"] if x["id"] == rid)["href"] == f"/vault?recurso={rid}"
    assert next(x for x in r["events"] if x["id"] == ev["id"])["href"] == "/calendario?dia=2026-12-01"
    # el fragmento lleva la coincidencia marcada
    o, c = r["marks"]
    hit = next(x for x in r["items"] if x["id"] == i["id"])
    assert o in hit["snippet"] and c in hit["snippet"]


def test_campos_propios_de_cada_tipo(client):
    rid = _recurso("Vídeo cualquiera", channel="Ribosomaticos", category="Bioquímica")
    client.post(
        "/api/calendar/events",
        json={"title": "Quedada", "start": "2026-12-02T18:00", "location": "Biblioteca Zarzuela"},
    )
    assert rid in [x["id"] for x in _buscar(client, "ribosomaticos")["resources"]]  # canal
    assert rid in [x["id"] for x in _buscar(client, "bioquimica")["resources"]]  # categoría
    assert [x["title"] for x in _buscar(client, "zarzuela")["events"]] == ["Quedada"]  # lugar


def test_editar_y_borrar_actualiza_el_indice(client):
    t = client.post("/api/items", json={"text": "Comprar xilófono", "type": "tarea"}).json()
    assert [x["id"] for x in _buscar(client, "xilofono")["items"]] == [t["id"]]
    client.patch(f"/api/items/{t['id']}", json={"text": "Comprar guitarra"})
    assert _buscar(client, "xilofono")["items"] == []
    client.delete(f"/api/items/{t['id']}")
    assert _buscar(client, "guitarra")["items"] == []

    rid = _recurso("Documental de quásares")
    assert _buscar(client, "quasares")["resources"]
    client.delete(f"/api/resources/{rid}")
    assert _buscar(client, "quasares")["resources"] == []

    ev = client.post("/api/calendar/events", json={"title": "Cita con el otorrino", "start": "2026-12-03"}).json()
    assert _buscar(client, "otorrino")["events"]
    client.delete(f"/api/calendar/events/{ev['id']}")
    assert _buscar(client, "otorrino")["events"] == []

    _nota(client, "bu-borrable", "Nota efímera", "Palabra rarísima: zigurat")
    assert _buscar(client, "zigurat")["notes"]
    client.delete("/api/notes/bu-borrable")
    assert _buscar(client, "zigurat")["notes"] == []
    with get_db() as conn:  # sin restos en el índice
        assert not conn.execute("SELECT 1 FROM search_fts_state WHERE kind='nota' AND ref='bu-borrable'").fetchone()


def test_nota_cifrada_solo_por_su_titulo(client):
    _nota(client, "bu-cifrada", "Diario guardado", "U2FsdGVkX1contenidosecreto", encrypted=True)
    assert _buscar(client, "U2FsdGVkX1contenidosecreto")["total"] == 0
    assert [n["id"] for n in _buscar(client, "diario guardado")["notes"]] == ["bu-cifrada"]


def test_nota_sensible_sin_cuerpo_ni_casillas(client):
    _nota(client, "bu-sensible", "Salud privada", "Tratamiento con levotiroxina\n\n- [ ] Pedir cita del tiroides")
    assert _buscar(client, "levotiroxina")["notes"]
    assert _buscar(client, "tiroides")["items"]
    assert client.put("/api/notes/bu-sensible/sensible", json={"sensible": True}).status_code == 200
    r = _buscar(client, "levotiroxina")
    assert r["notes"] == [] and r["total"] == 0
    assert _buscar(client, "tiroides")["items"] == []  # su casilla tampoco
    assert [n["id"] for n in _buscar(client, "salud privada")["notes"]] == ["bu-sensible"]  # el título sí
    client.put("/api/notes/bu-sensible/sensible", json={"sensible": False})
    assert _buscar(client, "levotiroxina")["notes"]


def test_categoria_sensible_de_la_politica(client):
    _nota(client, "bu-cat", "Revisión anual", "Analítica con ferritina baja", category="Íntimo - Médico")
    assert _buscar(client, "ferritina")["notes"]
    client.post("/api/ia/politica", json={"categorias_sensibles": ["íntimo"]})
    try:
        assert _buscar(client, "ferritina")["notes"] == []
        assert _buscar(client, "revision anual")["notes"]
    finally:
        client.post("/api/ia/politica", json={"categorias_sensibles": []})
    assert _buscar(client, "ferritina")["notes"]


def test_filtro_de_contexto(client):
    client.post("/api/items", json={"text": "Entregar práctica de mecatrónica", "contexto": "universidad"})
    client.post("/api/items", json={"text": "Leer sobre mecatrónica", "contexto": "puntual"})
    uni = _buscar(client, "mecatronica", contexto="universidad")
    assert [x["text"] for x in uni["items"]] == ["Entregar práctica de mecatrónica"]
    assert uni["fuera"] == 1
    assert len(_buscar(client, "mecatronica")["items"]) == 2  # «todo»


def test_tipo_y_filtros_de_nota(client):
    _nota(client, "bu-tipo", "Nota de pólipos", "pólipos")
    client.post("/api/items", json={"text": "Tarea de pólipos"})
    assert _buscar(client, "polipos", tipo="item")["notes"] == []
    assert _buscar(client, "polipos", tipo="nota")["items"] == []
    r = _buscar(client, "polipos", status="por-escribir")  # filtro de nota: solo notas
    assert r["notes"] and r["items"] == []


def test_refresco_solo_toca_lo_cambiado(client):
    search.refresh_index()
    assert search.refresh_index() == 0
    client.post("/api/items", json={"text": "Una más para el índice"})
    assert search.refresh_index() == 1


def test_consultas_raras(client):
    for q in ['"', "AND OR NOT", "*", "a:b", "(", "NEAR(x", "kind:nota", "ref:1"]:
        assert client.get("/api/search", params={"q": q}).status_code == 200
