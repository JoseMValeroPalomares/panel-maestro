"""Baúl (V-3): una miniatura que falla se recuerda y no se reintenta en cada arranque, solo pasada una semana."""

from app import vault
from app.database import get_db

URL_ROTA = "https://ejemplo.test/rota.jpg"
URL_BUENA = "https://ejemplo.test/buena.jpg"


def test_miniatura_que_falla_no_se_reintenta_en_el_siguiente_arranque(client, monkeypatch):
    with get_db() as conn:  # la BD de tests es compartida: solo las dos de esta prueba
        conn.execute("DELETE FROM resources WHERE image LIKE 'http%'")
        for i, img in enumerate((URL_ROTA, URL_BUENA)):
            conn.execute(
                "INSERT INTO resources (url, title, category, image) VALUES (?, 't', 'Pruebas', ?)",
                (f"https://ejemplo.test/r{i}", img),
            )
    vault._thumb_failures_file().unlink(missing_ok=True)
    pedidas = []

    def cache(url, _dir):
        pedidas.append(url)
        return "/static/uploads/thumbs/x.webp" if url == URL_BUENA else ""

    monkeypatch.setattr(vault, "cache_thumbnail", cache)

    t0 = 1_800_000_000.0
    vault.backfill_thumbnails(now=t0)  # primer arranque: las dos se piden
    assert sorted(pedidas) == [URL_BUENA, URL_ROTA]
    estado = vault._load_thumb_failures()
    assert estado == {URL_ROTA: {"intentos": 1, "fecha": t0}}  # solo la rota queda recordada

    pedidas.clear()
    vault.backfill_thumbnails(now=t0 + 3600)  # segundo arranque, una hora después
    assert pedidas == []  # ni la rota (en espera) ni la buena (ya local)

    vault.backfill_thumbnails(now=t0 + vault.THUMB_RETRY_S + 1)  # pasada la semana: un reintento
    assert pedidas == [URL_ROTA]
    assert vault._load_thumb_failures()[URL_ROTA]["intentos"] == 2

    with get_db() as conn:  # recurso borrado: se olvida su fallo
        conn.execute("DELETE FROM resources WHERE image=?", (URL_ROTA,))
    vault.backfill_thumbnails(now=t0 + 2 * vault.THUMB_RETRY_S + 2)
    assert vault._load_thumb_failures() == {}


# ── Reparar una miniatura que no carga (4.2) ─────────────────────────────
def _recurso(url, image):
    from app.database import get_db

    with get_db() as conn:
        conn.execute("DELETE FROM resources WHERE url=?", (url,))
        cur = conn.execute(
            "INSERT INTO resources (url, title, description, image, resource_type, category) VALUES (?, 't', '', ?, ?, 'General')",
            (url, image, "youtube" if "youtu" in url else "web"),
        )
        return cur.lastrowid


def test_reparar_miniatura_que_ya_no_esta_en_disco(client, monkeypatch):
    from app import vault
    from app.database import get_db

    vault._thumb_repairs.clear()
    rid = _recurso("https://www.youtube.com/watch?v=abcdefghijk", "/static/uploads/thumbs/" + "0" * 32 + ".webp")
    pedidas = []

    def cache(url, _dir):
        pedidas.append(url)
        return "/static/uploads/thumbs/" + "1" * 32 + ".webp"

    monkeypatch.setattr(vault, "cache_thumbnail", cache)
    r = client.post(f"/api/resources/{rid}/miniatura").json()
    assert r == {"image": "/static/uploads/thumbs/" + "1" * 32 + ".webp", "motivo": "recuperada"}
    assert pedidas == ["https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg"]  # la del vídeo, sin pedir la página
    with get_db() as conn:
        assert conn.execute("SELECT image FROM resources WHERE id=?", (rid,)).fetchone()["image"] == r["image"]


def test_reparar_no_insiste_y_no_toca_la_que_esta_bien(client, monkeypatch, tmp_path):
    from app import vault

    vault._thumb_repairs.clear()
    monkeypatch.setattr(vault, "cache_thumbnail", lambda url, _dir: "")
    monkeypatch.setattr(vault, "fetch_metadata", lambda url: {"image": "https://ejemplo.org/i.png"})
    rid = _recurso("https://ejemplo.org/articulo", "")
    assert client.post(f"/api/resources/{rid}/miniatura").json() == {"image": "", "motivo": "sin-imagen"}
    assert client.post(f"/api/resources/{rid}/miniatura").json() == {"image": "", "motivo": "espera"}  # 10 min

    monkeypatch.setattr(vault, "THUMBS_DIR", str(tmp_path))
    (tmp_path / ("2" * 32 + ".webp")).write_bytes(b"RIFF")
    rid2 = _recurso("https://ejemplo.org/otra", "/static/uploads/thumbs/" + "2" * 32 + ".webp")
    assert client.post(f"/api/resources/{rid2}/miniatura").json()["motivo"] == "ya-estaba"
    assert client.post("/api/resources/999999/miniatura").status_code == 404
    assert vault._thumb_file("/static/uploads/thumbs/../../etc/passwd") == ""


def test_metadatos_que_fallan_no_dejan_el_recurso_cargando(client, monkeypatch):
    from app import vault
    from app.database import get_db

    def rota(url):
        raise RuntimeError("web rara")

    monkeypatch.setattr(vault, "fetch_metadata", rota)
    _recurso("https://www.ejemplo.org/pagina", "")
    vault.do_scrape_and_save("https://www.ejemplo.org/pagina", "General")
    with get_db() as conn:
        fila = conn.execute(
            "SELECT title, resource_type FROM resources WHERE url=?", ("https://www.ejemplo.org/pagina",)
        ).fetchone()
    assert fila["title"] == "ejemplo.org" and fila["resource_type"] == "web"
