"""Enlaces tarea/idea ↔ nota: marcador [[tarea:N]] en el .md e índice item_links en la BD."""
from core import config

NOTA = "---\ncategory: Pruebas\nstatus: en-desarrollo\ntitle: Nota enlaces\n---\n\n# Nota enlaces\n\nTexto.\n"


def _nota(client, note_id="nota-enlaces"):
    (config.NOTES_DIR / f"{note_id}.md").write_text(NOTA, encoding="utf-8")
    client.get("/api/items")  # indexa
    return note_id


def _leer(note_id):
    return (config.NOTES_DIR / f"{note_id}.md").read_text(encoding="utf-8")


def _item(client, item_id):
    return next(i for i in client.get("/api/items").json()["items"] if i["id"] == item_id)


def test_enlazar_desde_la_tarea_escribe_en_la_nota(client):
    nid = _nota(client)
    tid = client.post("/api/items", json={"text": "Repasar enlaces", "type": "tarea"}).json()["id"]
    assert client.post(f"/api/items/{tid}/links", json={"note_id": nid}).status_code == 200
    assert f"[[tarea:{tid}]]" in _leer(nid)
    assert _leer(nid).startswith("---\ncategory: Pruebas")  # el frontmatter no se toca
    assert _item(client, tid)["links"] == [{"note_id": nid, "title": "Nota enlaces"}]
    links = client.get(f"/api/notes/{nid}/links").json()["items"]
    assert [x["id"] for x in links] == [tid]
    # enlazar dos veces no duplica
    client.post(f"/api/items/{tid}/links", json={"note_id": nid})
    assert _leer(nid).count(f"[[tarea:{tid}]]") == 1
    # desenlazar quita la línea entera y el índice
    assert client.delete(f"/api/items/{tid}/links/{nid}").status_code == 200
    assert f"tarea:{tid}" not in _leer(nid)
    assert _item(client, tid)["links"] == []


def test_enlazar_desde_la_nota_al_guardar(client):
    nid = _nota(client, "nota-enlaces-2")
    iid = client.post("/api/items", json={"text": "Una idea", "type": "idea"}).json()["id"]
    body = {"title": "Nota enlaces", "category": "Pruebas", "status": "en-desarrollo", "tags": [], "encrypted": False,
            "content": f"# Nota enlaces\n\nVer [[idea:{iid}]] y [[tarea:999999]].\n"}
    assert client.post(f"/api/notes/{nid}", json=body).status_code == 200
    assert [x["id"] for x in client.get(f"/api/notes/{nid}/links").json()["items"]] == [iid]  # el inexistente no cuenta
    assert _item(client, iid)["links"][0]["note_id"] == nid
    # quitar el marcador del texto quita el enlace
    body["content"] = "# Nota enlaces\n\nSin enlaces.\n"
    client.post(f"/api/notes/{nid}", json=body)
    assert _item(client, iid)["links"] == []


def test_borrar_y_deshacer_conserva_el_enlace(client):
    nid = _nota(client, "nota-enlaces-3")
    tid = client.post("/api/items", json={"text": "Se borra", "type": "tarea"}).json()["id"]
    client.post(f"/api/items/{tid}/links", json={"note_id": nid})
    token = client.delete(f"/api/items/{tid}").json()["undo"]
    assert client.get(f"/api/notes/{nid}/links").json()["items"] == []
    client.post("/api/items/undo", json={"token": token})
    assert [x["id"] for x in client.get(f"/api/notes/{nid}/links").json()["items"]] == [tid]


def test_nota_inexistente(client):
    tid = client.post("/api/items", json={"text": "Huérfana", "type": "tarea"}).json()["id"]
    assert client.post(f"/api/items/{tid}/links", json={"note_id": "no-existe"}).status_code == 404
