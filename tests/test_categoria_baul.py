"""Categoría propuesta para un enlace nuevo del Baúl (app/categoria_baul.py, GET /api/ext/categoria)."""

import pytest

import app.vault as vault
from app import categoria_baul as cb


@pytest.fixture
def baul(client, monkeypatch):
    monkeypatch.setattr(
        vault, "fetch_metadata", lambda url: {"title": url, "description": "", "image": "", "resource_type": "web"}
    )
    from app.database import get_db

    def add(url, cat, title="", channel=None, rtype="web"):
        assert client.post("/api/resources", json={"url": url, "category": cat}).status_code == 200
        with get_db() as conn:
            conn.execute(
                "UPDATE resources SET title=?, channel=?, resource_type=? WHERE url=?",
                (title or url, channel, rtype, url),
            )

    return add


def sugerida(client, **q):
    return client.get("/api/ext/categoria", params=q).json()


def test_ya_guardado_canal_y_web(client, baul):
    baul("https://www.youtube.com/@CanalCatTest", "CatCanal", "Canal Cat Test", "Canal Cat Test", "youtube")
    baul("https://docs.cattest.invalid/a", "CatWeb", "Página A")
    baul("https://docs.cattest.invalid/b", "CatWeb", "Página B")
    # el mismo enlace
    r = sugerida(client, url="https://docs.cattest.invalid/a")
    assert r["category"] == "CatWeb" and r["certain"] and r["source"] == "baul"
    # vídeo de un canal guardado (por su @)
    r = sugerida(client, url="https://www.youtube.com/watch?v=abcdefghijk", channel="/@canalcattest")
    assert r["category"] == "CatCanal" and r["certain"] and r["source"] == "canal"
    # sin el @, por el nombre del canal
    r = sugerida(client, url="https://www.youtube.com/watch?v=abcdefghijl", channel_name="Canal Cat Test")
    assert r["category"] == "CatCanal" and r["source"] == "canal"
    # otra página de la misma web: segura (dos y coinciden)
    r = sugerida(client, url="https://www.docs.cattest.invalid/c", title="Otra")
    assert r["category"] == "CatWeb" and r["certain"] and "docs.cattest.invalid" in r["reason"]
    # y la lista de categorías en el orden del Baúl, para elegirla a mano
    assert {"CatCanal", "CatWeb"} <= set(r["categories"])


def test_por_el_titulo_y_sin_pistas(client, baul):
    baul("https://a.cattxt.invalid/", "Astronomía", "Telescopios y planetas del sistema solar")
    baul("https://b.cattxt.invalid/", "Astronomía", "Galaxias, planetas y estrellas")
    baul("https://c.cattxt.invalid/", "Cocina", "Recetas de cuchara")
    # el nombre de la categoría en el título basta
    r = sugerida(client, url="https://nuevo.cattxt.invalid/1", title="Astronomia para principiantes")
    assert r["category"] == "Astronomía" and r["certain"] is False and r["source"] == "texto"
    # dos palabras de lo que ya tiene
    r = sugerida(client, url="https://nuevo.cattxt.invalid/2", title="Los planetas y sus estrellas - YouTube")
    assert r["category"] == "Astronomía"
    # una sola palabra suelta no basta: mejor que la elijas tú
    r = sugerida(client, url="https://nuevo.cattxt.invalid/3", title="Planetas")
    assert r["category"] is None and r["source"] is None


def test_palabras_y_parecidas():
    assert cb.palabras("¿Qué es la Mecánica Cuántica? | Física") == ["mecanica", "cuantica", "fisica"]
    assert cb._parecidas("matematica", "matematicas") and not cb._parecidas("informe", "informatica")
