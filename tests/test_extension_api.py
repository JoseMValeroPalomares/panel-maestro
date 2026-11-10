"""Ronda 2 · fase 5: lo que usa la extensión de Firefox (token Bearer, estado, Inbox con prioridad y categoría)."""
import sqlite3

from app.migrations import MIGRATIONS
from core.migrations import apply_pending, revert
from tests.conftest import TEST_API_TOKEN

import pytest


@pytest.fixture(autouse=True)
def _sin_red(monkeypatch):
    """Los vídeos creados al marcarlos vistos piden sus metadatos en segundo plano: en los tests, sin red."""
    monkeypatch.setattr("app.extension.do_scrape_and_save", lambda url, cat: None)


AUTH = {"Authorization": f"Bearer {TEST_API_TOKEN}", "Origin": "moz-extension://1234-abcd"}


def test_estado_exige_token_y_cuenta_pendientes(anon):
    assert anon.get("/api/ext/status").status_code == 401
    assert anon.get("/api/ext/status", headers={"Authorization": "Bearer malo"}).status_code == 401
    r = anon.get("/api/ext/status", headers=AUTH)
    assert r.status_code == 200 and r.json()["ok"] is True and isinstance(r.json()["pending"], int)


def test_captura_con_prioridad_y_categoria_desde_otro_origen(anon):
    antes = anon.get("/api/ext/status", headers=AUTH).json()["pending"]
    # con token, un origen moz-extension:// no se bloquea (la defensa de Origin es para la cookie de sesión)
    r = anon.post("/api/inbox", headers=AUTH, json={"content": "Leer artículo\n\nhttps://ejemplo.org/a", "item_type": "tarea",
                                                    "priority": "alta", "category": " Lecturas "})
    assert r.status_code == 200
    iid = r.json()["id"]
    item = next(i for i in anon.get("/api/items", headers=AUTH).json()["items"] if i["id"] == iid)
    assert (item["priority"], item["category"], item["type"]) == ("alta", "Lecturas", "tarea")
    st = anon.get("/api/ext/status", headers=AUTH).json()
    assert st["pending"] == antes + 1 and "Lecturas" in st["inbox_categories"]
    # editar y quitar
    assert anon.patch(f"/api/items/{iid}", headers=AUTH, json={"priority": "baja", "category": "Otra"}).status_code == 200
    assert anon.patch(f"/api/items/{iid}", headers=AUTH, json={"priority": "", "category": ""}).status_code == 200
    item = next(i for i in anon.get("/api/items", headers=AUTH).json()["items"] if i["id"] == iid)
    assert item["priority"] is None and item["category"] is None
    assert anon.post("/api/inbox", headers=AUTH, json={"content": "x", "priority": "urgentísima"}).status_code == 422


def test_baul_con_token(anon):
    r = anon.post("/api/resources", headers=AUTH, json={"url": "https://ejemplo.org/extension", "category": "Leer", "watch_later": True})
    assert r.status_code == 200
    assert anon.post("/api/resources", headers=AUTH, json={"url": "https://ejemplo.org/extension"}).status_code == 409
    assert "Leer" in anon.get("/api/resources/categories", headers=AUTH).json()["categories"]


def test_migracion_6_arriba_y_abajo_sin_perder(tmp_path):
    conn = sqlite3.connect(tmp_path / "m6.db", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE inbox (id INTEGER PRIMARY KEY, content TEXT, item_type TEXT, status TEXT DEFAULT 'pending',
                    parent_id INTEGER, sort_order REAL DEFAULT 0, created_at REAL DEFAULT 0, note_id TEXT, note_task TEXT)""")
    conn.execute("CREATE TABLE resources (id INTEGER PRIMARY KEY, url TEXT, title TEXT, category TEXT, resource_type TEXT, channel TEXT, added_at REAL)")
    conn.execute("INSERT INTO inbox (id, content, item_type) VALUES (1, 'a', 'tarea'), (2, 'b', 'nota')")
    apply_pending(conn, MIGRATIONS)
    conn.execute("UPDATE inbox SET priority='alta', category='C' WHERE id=1")
    revert(conn, MIGRATIONS, 5)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(inbox)")]
    assert "priority" not in cols and [tuple(r) for r in conn.execute("SELECT id, content FROM inbox ORDER BY id")] == [(1, "a"), (2, "b")]
    assert tuple(conn.execute("SELECT id, priority, category FROM inbox_meta_backup").fetchone()) == (1, "alta", "C")
    apply_pending(conn, MIGRATIONS)
    assert "priority" in [r[1] for r in conn.execute("PRAGMA table_info(inbox)")]


def test_youtube_visto_solo_de_canales_del_baul(anon):
    vid = "dQw4w9WgXcQ"
    # canal que no está en el Baúl: no se guarda nada
    r = anon.post("/api/ext/youtube/visto", headers=AUTH, json={"video_id": vid, "channel": "@desconocido"})
    assert r.json() == {"tracked": False}
    assert anon.get("/api/ext/youtube/canal", headers=AUTH, params={"channel": "@desconocido"}).json()["tracked"] is False
    assert anon.post("/api/ext/youtube/visto", headers=AUTH, json={"video_id": "corto", "channel": "@x"}).status_code == 422
    # con el canal en el Baúl
    assert anon.post("/api/resources", headers=AUTH, json={"url": "https://www.youtube.com/@CanalPrueba", "category": "Mates"}).status_code == 200
    r = anon.post("/api/ext/youtube/visto", headers=AUTH, json={"video_id": vid, "channel": "@canalprueba", "title": "Un vídeo"})
    assert r.json() == {"tracked": True, "created": True}
    assert anon.post("/api/ext/youtube/visto", headers=AUTH, json={"video_id": vid, "channel": "@CanalPrueba"}).json()["created"] is False
    res = [x for x in anon.get("/api/resources", headers=AUTH).json()["resources"] if vid in x["url"]]
    assert len(res) == 1 and res[0]["watched"] == 1 and res[0]["category"] == "Mates" and res[0]["title"] == "Un vídeo"
    c = anon.get("/api/ext/youtube/canal", headers=AUTH, params={"channel": "@CanalPrueba"}).json()
    assert c == {"tracked": True, "watched": [vid]}


def test_youtube_visto_marca_el_video_que_ya_estaba_en_el_baul(anon):
    vid = "abcdefghijk"
    anon.post("/api/resources", headers=AUTH, json={"url": "https://www.youtube.com/@Otro", "category": "Ocio"})
    anon.post("/api/resources", headers=AUTH, json={"url": f"https://www.youtube.com/watch?v={vid}", "category": "Ocio", "watch_later": True})
    assert anon.post("/api/ext/youtube/visto", headers=AUTH, json={"video_id": vid, "channel": "https://www.youtube.com/@Otro"}).json() == {"tracked": True, "created": False}
    res = [x for x in anon.get("/api/resources", headers=AUTH).json()["resources"] if vid in x["url"]]
    assert len(res) == 1 and res[0]["watched"] == 1 and res[0]["watch_later"] == 0


def test_baul_guarda_ya_como_visto(anon):
    r = anon.post("/api/resources", headers=AUTH, json={"url": "https://www.youtube.com/watch?v=vistoYaaaaa", "watched": True, "watch_later": True})
    assert r.status_code == 200
    res = next(x for x in anon.get("/api/resources", headers=AUTH).json()["resources"] if "vistoYaaaaa" in x["url"])
    assert res["watched"] == 1 and res["watch_later"] == 0


def test_youtube_visto_pide_los_metadatos_al_crear(anon, monkeypatch):
    llamadas = []
    monkeypatch.setattr("app.extension.do_scrape_and_save", lambda url, cat: llamadas.append((url, cat)))
    anon.post("/api/resources", headers=AUTH, json={"url": "https://www.youtube.com/@ConMiniatura", "category": "Cine"})
    anon.post("/api/ext/youtube/visto", headers=AUTH, json={"video_id": "miniatura01", "channel": "@conminiatura"}).json()
    anon.post("/api/ext/youtube/visto", headers=AUTH, json={"video_id": "miniatura01", "channel": "@conminiatura"})
    assert llamadas == [("https://www.youtube.com/watch?v=miniatura01", "Cine")]  # solo al crearlo
