"""Fase 9: búsqueda FTS5, backlinks, historial de versiones, filtros guardados y calendario de repaso."""
import time

from app import versions
from core import config


def _nota(client, note_id, title, content, **kw):
    r = client.post(f"/api/notes/{note_id}", json={"title": title, "category": kw.pop("category", "Buscar - Pruebas"),
                                                   "content": content, **kw})
    assert r.status_code == 200, r.text


def test_busqueda_fts(client):
    _nota(client, "fts-corazon", "Fisiología del corazón", "El miocardio bombea sangre. Canción de prueba.", tags=["cardio"])
    _nota(client, "fts-otra", "Otra cosa", "Habla del corazón de pasada")
    r = client.get("/api/search", params={"q": "corazon"}).json()  # sin tilde
    ids = [n["id"] for n in r["notes"]]
    assert ids[:2] == ["fts-corazon", "fts-otra"]  # el título pesa más
    open_, close = r["marks"]
    hit = r["notes"][0]
    assert f"{open_}corazón{close}" in hit["title_hl"]
    assert client.get("/api/search", params={"q": "mioc"}).json()["notes"][0]["id"] == "fts-corazon"  # prefijo
    assert client.get("/api/search", params={"q": "cardio"}).json()["notes"][0]["id"] == "fts-corazon"  # etiquetas
    assert client.get("/api/search", params={"q": '"bombea sangre"'}).json()["total"] == 1
    # se actualiza al editar
    _nota(client, "fts-otra", "Otra cosa", "Ahora va de riñones")
    assert all(n["id"] != "fts-otra" for n in client.get("/api/search", params={"q": "corazon"}).json()["notes"])
    # consultas raras no rompen
    for q in ['"', "AND OR NOT", "*", "a:b", "(", "NEAR(x"]:
        assert client.get("/api/search", params={"q": q}).status_code == 200


def test_busqueda_no_indexa_contenido_cifrado(client):
    _nota(client, "fts-cifrada", "Diario cifrado", "U2FsdGVkX1secreto", encrypted=True)
    assert client.get("/api/search", params={"q": "U2FsdGVkX1secreto"}).json()["total"] == 0
    assert client.get("/api/search", params={"q": "diario cifrado"}).json()["notes"][0]["id"] == "fts-cifrada"


def test_busqueda_en_inbox(client):
    client.post("/api/inbox", json={"content": "Idea sobre electroforesis capilar", "item_type": "nota"})
    r = client.get("/api/search", params={"q": "electroforesis"}).json()
    assert any("electroforesis" in i["content"] for i in r["inbox"])


def test_backlinks(client):
    _nota(client, "bl-destino", "Ley de Ohm", "V = IR")
    _nota(client, "bl-a", "Circuitos", "Aplica la [[Ley de Ohm]] aquí.\nY otra vez [[ley de ohm]].")
    _nota(client, "bl-b", "Sin enlace", "Habla de la ley de ohm sin enlazar")
    bl = client.get("/api/notes/bl-destino/backlinks").json()["backlinks"]
    assert [b["id"] for b in bl] == ["bl-a"]
    assert bl[0]["count"] == 2 and "[[Ley de Ohm]]" in bl[0]["context"][0]


def test_versiones(client, monkeypatch):
    _nota(client, "ver-n", "Versionada", "uno")
    assert client.get("/api/notes/ver-n/versions").json()["versions"] == []  # nota nueva: nada anterior
    _nota(client, "ver-n", "Versionada", "dos")
    vs = client.get("/api/notes/ver-n/versions").json()["versions"]
    assert len(vs) == 1
    assert client.get(f"/api/notes/ver-n/versions/{vs[0]['id']}").json()["content"].strip() == "uno"
    _nota(client, "ver-n", "Versionada", "tres")  # misma sesión de edición: no crea otra
    assert len(client.get("/api/notes/ver-n/versions").json()["versions"]) == 1

    monkeypatch.setattr(versions, "SESSION_GAP_S", 0)
    time.sleep(0.01)
    _nota(client, "ver-n", "Versionada", "cuatro")
    vs = client.get("/api/notes/ver-n/versions").json()["versions"]
    assert len(vs) == 2

    oldest = vs[-1]["id"]
    r = client.post(f"/api/notes/ver-n/versions/{oldest}/restore")
    assert r.status_code == 200 and r.json()["previous_version"]
    assert client.get("/api/notes/ver-n").json()["content"].strip() == "uno"
    contenidos = [client.get(f"/api/notes/ver-n/versions/{v['id']}").json()["content"].strip()
                  for v in client.get("/api/notes/ver-n/versions").json()["versions"]]
    assert "cuatro" in contenidos  # lo que había antes de restaurar queda guardado

    assert client.get("/api/notes/ver-n/versions/../../x").status_code == 404
    assert client.get("/api/notes/ver-n/versions/abc").status_code == 400
    assert client.get("/api/notes/ver-n/versions/1234567890123").status_code == 404


def test_version_al_borrar(client):
    _nota(client, "ver-borrada", "Se borra", "contenido a salvar")
    client.delete("/api/notes/ver-borrada")
    assert any((config.DATA_DIR / "versions" / "ver-borrada").glob("*.md"))


def test_filtros_guardados(client):
    r = client.post("/api/saved-filters", json={"scope": "notas", "name": "Consolidadas de física", "params": {"chip": "consolidado", "q": "física"}})
    fid = r.json()["id"]
    fs = client.get("/api/saved-filters", params={"scope": "notas"}).json()["filters"]
    assert any(f["id"] == fid and f["params"]["chip"] == "consolidado" for f in fs)
    assert client.post("/api/saved-filters", json={"scope": "otro", "name": "x"}).status_code == 422
    client.delete(f"/api/saved-filters/{fid}")
    assert not client.get("/api/saved-filters", params={"scope": "notas"}).json()["filters"]


def test_calendario_de_repaso(client):
    _nota(client, "rep-n", "Repaso", "¿Capital de Francia? >> París")
    cal = client.get("/api/review/calendar", params={"past_weeks": 4, "future_days": 14}).json()
    assert len(cal["upcoming"]) == 14 and cal["upcoming"][0]["date"] == cal["today"]
    assert cal["due_today"] >= 1  # las flashcards nuevas vencen hoy
    assert cal["heat"][-1]["date"] == cal["today"] and cal["heat"][-1]["studied"] is True
    assert cal["streak"] >= 1
    # nunca repasada (la lista se corta en 30: con muchas notas de otros tests puede quedar fuera)
    assert any(n["id"] == "rep-n" for n in cal["stale_notes"]) or cal["stale_total"] > len(cal["stale_notes"])


def test_paginas(client):
    for path in ("/buscar", "/repaso"):
        assert client.get(path).status_code == 200
