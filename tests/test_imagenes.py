"""Imágenes automáticas: avatar real de los canales del Baúl y fotos de platos buscadas en la web (sin red: simulado)."""
from app import scraper

PAGINA_CANAL = """<html><head><script>var x = "</head>";</script></head><body>
<meta property="og:title" content="Nate &amp; Gentile"><meta property="og:image"
 content="https://yt3.googleusercontent.com/abc=s900-c-k-c0x00ffffff-no-rj">
</body></html>"""


class _Resp:
    status_code = 200


def test_og_tags_aunque_esten_tras_un_head_falso():
    og = scraper._og_tags(PAGINA_CANAL)
    assert og["title"] == "Nate & Gentile" and og["image"].startswith("https://yt3.googleusercontent.com/")


def test_canal_toma_su_avatar_real_reducido(monkeypatch):
    llamadas = {}

    def falso(url, **kw):
        llamadas.update(kw)
        return _Resp(), PAGINA_CANAL.encode()
    monkeypatch.setattr(scraper, "safe_get", falso)
    meta = scraper._youtube_channel_metadata("https://www.youtube.com/@NateGentile7")
    assert meta["title"] == meta["channel"] == "Nate & Gentile"
    assert meta["image"] == "https://yt3.googleusercontent.com/abc=s240-c-k-c0x00ffffff-no-rj"
    assert llamadas["cookies"] == {"SOCS": "CAI"}  # sin muro de consentimiento


def test_canal_ilegible_sin_foto_inventada(monkeypatch):
    def falla(url, **kw):
        raise scraper.UnsafeURLError("404")
    monkeypatch.setattr(scraper, "safe_get", falla)
    meta = scraper._youtube_channel_metadata("https://www.youtube.com/@borrado")
    assert meta["image"] == "" and meta["title"] == "borrado"


def test_busqueda_de_imagenes_filtra_lo_que_no_es_una_foto(monkeypatch):
    resultados = [
        {"image": "https://x.test/logo.svg", "width": 800, "height": 600},
        {"image": "https://x.test/mini.jpg", "width": 120, "height": 90},
        {"image": "https://x.test/tira.jpg", "width": 2000, "height": 300},
        {"image": "javascript:alert(1)", "width": 800, "height": 600},
        {"image": "https://x.test/buena.jpg", "thumbnail": "https://x.test/t.jpg", "width": 1200, "height": 800, "title": "Tortilla"},
    ]

    class FalsoDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def images(self, query, **kw):
            assert "tortilla" in query.lower()
            return resultados
    monkeypatch.setattr(scraper, "DDGS", FalsoDDGS)
    out = scraper.search_images("Tortilla de patatas plato receta")
    assert [o["image"] for o in out] == ["https://x.test/buena.jpg"]


def test_busqueda_de_fotos_de_un_plato(client, monkeypatch):
    pedido = {}

    def falso(q, n=8):
        pedido["q"] = q
        return [{"image": "https://x.test/a.jpg", "thumbnail": "", "width": 800, "height": 600, "title": "A"}]
    monkeypatch.setattr(scraper, "search_images", falso)
    r = client.get("/comidas/api/photo-search", params={"q": "Lentejas con verduras"})
    assert r.status_code == 200 and r.json()["options"][0]["image"] == "https://x.test/a.jpg"
    assert pedido["q"] == "Lentejas con verduras plato receta"
    assert client.get("/comidas/api/photo-search", params={"q": "x"}).status_code in (400, 422)
