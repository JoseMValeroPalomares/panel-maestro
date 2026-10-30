"""Ronda 2 · fase 2: orden manual persistente del Baúl y de las notas."""


def _res(client, monkeypatch, url, category="Orden", **kw):
    import app.vault as m
    monkeypatch.setattr(m, "do_scrape_and_save", lambda *a, **k: None)
    assert client.post("/api/resources", json={"url": url, "category": category, **kw}).status_code == 200
    return next(r["id"] for r in client.get("/api/resources").json()["resources"] if r["url"] == url)


def _orden(client, category):
    return [r["id"] for r in client.get("/api/resources", params={"category": category}).json()["resources"]]


def test_baul_orden_y_cambio_de_categoria(client, monkeypatch):
    a = _res(client, monkeypatch, "https://orden.example/a")
    b = _res(client, monkeypatch, "https://orden.example/b")
    c = _res(client, monkeypatch, "https://orden.example/c")
    assert _orden(client, "Orden") == [c, b, a]  # lo nuevo arriba
    assert client.post(f"/api/resources/{a}/move", json={"category": "Orden", "before_id": c}).status_code == 200
    assert _orden(client, "Orden") == [a, c, b]
    assert client.post(f"/api/resources/{a}/move", json={"category": "Orden", "before_id": None}).status_code == 200
    assert _orden(client, "Orden") == [c, b, a]
    # a otra categoría
    d = _res(client, monkeypatch, "https://orden.example/d", category="Otra")
    assert client.post(f"/api/resources/{b}/move", json={"category": "Otra", "before_id": d}).status_code == 200
    assert _orden(client, "Otra") == [b, d] and b not in _orden(client, "Orden")


def test_baul_no_mezcla_videos_y_webs(client, monkeypatch):
    web = _res(client, monkeypatch, "https://orden.example/web", category="Mixta")
    yt = _res(client, monkeypatch, "https://www.youtube.com/watch?v=orden123", category="Mixta")
    from app.database import get_db
    with get_db() as conn:  # el tipo lo pone el scraper, desactivado en el test
        conn.execute("UPDATE resources SET resource_type='youtube' WHERE id=?", (yt,))
    tipos = {r["id"]: r["resource_type"] for r in client.get("/api/resources").json()["resources"]}
    assert tipos[yt] == "youtube" and tipos[web] != "youtube"
    r = client.post(f"/api/resources/{web}/move", json={"category": "Mixta", "before_id": yt})
    assert r.status_code == 422


def _nota(client, note_id, title, category):
    assert client.post(f"/api/notes/{note_id}", json={"title": title, "category": category, "content": "x"}).status_code == 200


def _orden_notas(client, category):
    notes = [n for n in client.get("/api/notes").json()["notes"] if n["category"] == category]
    notes.sort(key=lambda n: (n["position"] is None, n["position"] or 0, n["title"].lower()))
    return [n["id"] for n in notes]


def test_notas_orden_dentro_de_su_categoria(client):
    for nid, t in (("ord-a", "Alfa"), ("ord-b", "Beta"), ("ord-c", "Gamma")):
        _nota(client, nid, t, "Orden notas - Sub")
    _nota(client, "ord-x", "Fuera", "Otra categoría")
    assert _orden_notas(client, "Orden notas - Sub") == ["ord-a", "ord-b", "ord-c"]  # alfabético por defecto
    assert client.post("/api/notes/ord-c/move", json={"before_id": "ord-a"}).status_code == 200
    assert _orden_notas(client, "Orden notas - Sub") == ["ord-c", "ord-a", "ord-b"]
    # misma categoría escrita con flecha y en minúsculas: es el mismo grupo
    _nota(client, "ord-d", "Delta", "orden notas->sub")
    assert client.post("/api/notes/ord-d/move", json={"before_id": "ord-c"}).status_code == 200
    # no se mezcla con otras categorías
    assert client.post("/api/notes/ord-a/move", json={"before_id": "ord-x"}).status_code == 422
    # el .md no cambia
    from core import config
    assert "position" not in (config.NOTES_DIR / "ord-c.md").read_text(encoding="utf-8")
    # al cambiar de categoría deja de tener posición
    client.patch("/api/notes/ord-c/meta", json={"category": "Otra categoría"})
    assert next(n for n in client.get("/api/notes").json()["notes"] if n["id"] == "ord-c")["position"] is None
