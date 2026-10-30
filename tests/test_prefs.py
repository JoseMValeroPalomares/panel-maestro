"""Preferencias de interfaz en el servidor (plegados de notas, categorías y grupos)."""


def test_guardar_y_leer(client):
    assert client.put("/api/prefs/notes-fold", json={"value": {"Biologia": True}}).status_code == 200
    assert client.put("/api/prefs/items-fold", json={"value": {"page:g:ideas": True}}).status_code == 200
    prefs = client.get("/api/prefs").json()["prefs"]
    assert prefs["notes-fold"] == {"Biologia": True}
    assert prefs["items-fold"] == {"page:g:ideas": True}
    client.put("/api/prefs/notes-fold", json={"value": {}})
    assert client.get("/api/prefs").json()["prefs"]["notes-fold"] == {}


def test_clave_no_valida_y_tamano(client):
    assert client.put("/api/prefs/../x", json={"value": 1}).status_code in (404, 422)
    assert client.put("/api/prefs/Mayus", json={"value": 1}).status_code == 422
    assert client.put("/api/prefs/grande", json={"value": "x" * 70_000}).status_code == 413
