"""API del grafo automático: guarda posiciones, respeta fijados y se deshace (nada de esto toca las notas)."""
import math


def crear(client, nid, cat):
    assert client.post(f"/api/notes/{nid}", json={"title": nid, "category": cat, "content": "x", "status": "en-desarrollo"}).status_code == 200


def pos_guardadas(client):
    return {n["id"]: (n["x"], n["y"], n["fijado"]) for n in client.get("/api/graph").json()["nodes"]}


def test_auto_guarda_posiciones_y_se_deshace(client):
    for i in range(4):
        crear(client, f"ga-fis-{i}", "GA Física - Cuántica")
    crear(client, "ga-bio-0", "GA Biología")
    crear(client, "ga-sin-0", "")
    antes = pos_guardadas(client)
    r = client.post("/api/graph/auto", json={"respetar_fijados": False}).json()
    assert r["hay_deshacer"] and r["total"] >= 8
    despues = pos_guardadas(client)
    assert all(despues[i][0] is not None for i in ("ga-fis-0", "ga-bio-0", "ga-sin-0", "cat:ga física"))
    assert client.get("/api/graph").json()["hay_deshacer"] is True
    # la mayor (Física) en el centro entre las de la prueba y la suelta en el exterior
    assert math.hypot(*despues["ga-sin-0"][:2]) > math.hypot(*despues["ga-fis-0"][:2])
    assert client.post("/api/graph/auto/deshacer").status_code == 200
    assert pos_guardadas(client) == antes
    assert client.post("/api/graph/auto/deshacer").status_code == 404


def test_respetar_fijados(client):
    crear(client, "gf-a", "GF Uno")
    crear(client, "gf-b", "GF Uno")
    client.post("/api/graph/layout", json={"nodes": [{"id": "gf-a", "x": 7, "y": 9}], "fijados": ["gf-a"]})
    client.post("/api/graph/auto", json={"respetar_fijados": True})
    assert pos_guardadas(client)["gf-a"] == (7, 9, True)
    # guardar posiciones sin fijados no pierde la marca
    client.post("/api/graph/layout", json={"nodes": [{"id": "gf-a", "x": 7, "y": 9}]})
    assert pos_guardadas(client)["gf-a"][2] is True
    client.post("/api/graph/auto", json={"respetar_fijados": False})
    x, y, fij = pos_guardadas(client)["gf-a"]
    assert fij is False and (x, y) != (7, 9)
    client.post("/api/graph/fijar", json={"id": "gf-a", "fijado": True})
    assert pos_guardadas(client)["gf-a"][2] is True
