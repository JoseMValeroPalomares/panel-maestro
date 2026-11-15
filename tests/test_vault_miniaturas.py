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
