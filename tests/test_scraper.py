import httpx
import pytest

from app import scraper


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/api/notes",
    "http://localhost/",
    "http://10.0.0.1/",
    "http://192.168.1.52/ws",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://0.0.0.0/",
    "file:///etc/passwd",
    "ftp://8.8.8.8/",
    "gopher://8.8.8.8/",
])
def test_urls_peligrosas_rechazadas(url):
    with pytest.raises(scraper.UnsafeURLError):
        scraper.validate_public_url(url)


def test_ip_publica_aceptada():
    assert scraper.validate_public_url("http://8.8.8.8/") == "http://8.8.8.8/"


def _patch_client(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(scraper.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def test_redireccion_a_ip_privada_bloqueada(monkeypatch):
    def handler(request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1:8000/api/notes"})
    _patch_client(monkeypatch, handler)
    with pytest.raises(scraper.UnsafeURLError):
        scraper.safe_get("http://8.8.8.8/")


def test_metadatos_con_imagen_relativa_y_javascript(monkeypatch):
    html = b'<html><head><title>Hola</title><meta property="og:image" content="/img.png"></head></html>'
    _patch_client(monkeypatch, lambda r: httpx.Response(200, content=html, headers={"content-type": "text/html"}))
    meta = scraper._web_metadata("http://8.8.8.8/pagina")
    assert meta["title"] == "Hola"
    assert meta["image"] == "http://8.8.8.8/img.png"

    html2 = b'<html><head><meta property="og:image" content="javascript:alert(1)"></head></html>'
    _patch_client(monkeypatch, lambda r: httpx.Response(200, content=html2, headers={"content-type": "text/html"}))
    assert scraper._web_metadata("http://8.8.8.8/")["image"] == ""


def test_respuesta_grande_truncada(monkeypatch):
    big = b"a" * (scraper.MAX_BODY_BYTES * 2)
    _patch_client(monkeypatch, lambda r: httpx.Response(200, content=big, headers={"content-type": "text/html"}))
    _, body = scraper.safe_get("http://8.8.8.8/")
    assert len(body) <= scraper.MAX_BODY_BYTES


def test_scraper_no_descarga_urls_internas():
    meta = scraper.fetch_metadata("http://127.0.0.1:8000/api/notes")
    assert "privada" in meta["description"]
