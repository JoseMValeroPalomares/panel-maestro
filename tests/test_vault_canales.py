"""Baúl: relleno en segundo plano del canal de los vídeos antiguos (con límite de velocidad y reintentos)."""
from app import vault
from app.database import get_db


def poner(url, canal=None, tipo="youtube", visto=1):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO resources (url, title, category, resource_type, channel, watched) VALUES (?, ?, 'Pruebas', ?, ?, ?)",
                     (url, url, tipo, canal, visto))


def canal_de(url):
    with get_db() as conn:
        return conn.execute("SELECT channel FROM resources WHERE url=?", (url,)).fetchone()["channel"]


def test_rellena_canales_con_reintentos_y_sin_tocar_el_resto(client, monkeypatch):
    with get_db() as conn:                                                           # la BD de tests es compartida: sin pendientes ajenos
        conn.execute("DELETE FROM resources WHERE resource_type='youtube' AND (channel IS NULL OR TRIM(channel)='')")
    poner("https://www.youtube.com/watch?v=AAAAAAAAAAA")                          # sin canal → se rellena
    poner("https://www.youtube.com/watch?v=BBBBBBBBBBB")                          # falla dos veces y luego responde
    poner("https://www.youtube.com/watch?v=CCCCCCCCCCC", canal="Ya tenía")        # no se toca
    poner("https://www.youtube.com/watch?v=DDDDDDDDDDD")                          # nunca responde → sigue sin canal
    poner("https://www.youtube.com/@alguien")                                      # un canal no es un vídeo: se ignora
    poner("https://ejemplo.test/x", tipo="web")
    llamadas = {}

    def meta(url):
        llamadas[url] = llamadas.get(url, 0) + 1
        if url.endswith("AAAAAAAAAAA"):
            return {"channel": "Canal A"}
        if url.endswith("BBBBBBBBBBB"):
            return {"channel": "Canal B"} if llamadas[url] >= 3 else {"channel": ""}
        raise RuntimeError("YouTube no responde") if url.endswith("DDDDDDDDDDD") else AssertionError(url)
    monkeypatch.setattr(vault, "fetch_metadata", meta)
    pausas = []
    hechos = vault.backfill_channels(pausa_s=1.5, reintentos=3, dormir=pausas.append)
    assert hechos == 2
    assert canal_de("https://www.youtube.com/watch?v=AAAAAAAAAAA") == "Canal A" and canal_de("https://www.youtube.com/watch?v=BBBBBBBBBBB") == "Canal B"
    assert canal_de("https://www.youtube.com/watch?v=CCCCCCCCCCC") == "Ya tenía" and not canal_de("https://www.youtube.com/watch?v=DDDDDDDDDDD")
    assert "https://www.youtube.com/@alguien" not in llamadas and "https://ejemplo.test/x" not in llamadas
    assert llamadas["https://www.youtube.com/watch?v=DDDDDDDDDDD"] == 3                  # reintentos acotados
    assert pausas.count(1.5) == 3 and max(pausas) <= 30                                  # una pausa entre peticiones y espera creciente


def test_endpoint_informa_de_pendientes_y_no_se_solapa(client, monkeypatch):
    monkeypatch.setattr(vault, "backfill_channels", lambda: 0)
    poner("https://www.youtube.com/watch?v=EEEEEEEEEEE")
    r = client.post("/api/resources/backfill-channels").json()
    assert r["pendientes"] >= 1
    with vault._canales_lock:                                                          # ya hay una tarea en curso
        assert client.post("/api/resources/backfill-channels").json()["en_curso"] is True
