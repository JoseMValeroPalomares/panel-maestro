import json
"""Recorrido de humo por la API existente: protege contra regresiones en refactors."""


def test_flujo_notas_completo(client):
    r = client.post("/api/notes/smoke-a", json={"title": "Smoke A", "category": "Smoke - Sub", "tags": ["x"],
                                                "content": "Enlace a [[Smoke B]]\n¿Pregunta? >> Respuesta"})
    assert r.status_code == 200
    client.post("/api/notes/smoke-b", json={"title": "Smoke B", "category": "Smoke", "content": "Menciona Smoke A"})
    notes = client.get("/api/notes").json()["notes"]
    assert any(n["id"] == "smoke-a" for n in notes)
    assert any(n["id"] == "indice-smoke" for n in notes)  # índice automático por área

    assert client.patch("/api/notes/smoke-a/status", json={"status": "consolidado"}).json()["new_status"] == "consolidado"
    assert client.patch("/api/notes/smoke-a/reviewed").status_code == 200
    assert client.patch("/api/notes/smoke-a/meta", json={"title": "Smoke A2"}).status_code == 200
    assert client.get("/api/notes/smoke-a").json()["title"] == "Smoke A2"
    rel = client.get("/api/notes/smoke-b/related").json()["related"]
    assert any(n["id"] == "smoke-a" for n in rel)
    sug = client.get("/api/notes/smoke-b/wikilink-suggestions").json()["suggestions"]
    assert isinstance(sug, list)

    stats = client.get("/api/flashcards/stats").json()
    assert stats["total"] >= 1
    due = client.get("/api/flashcards/due").json()["cards"]
    card = next(c for c in due if c["note_id"] == "smoke-a")
    assert client.post(f"/api/flashcards/{card['id']}/review", json={"quality": 4}).json()["next_review_in_days"] == 1

    assert client.get("/api/streak").json()["studied_today"] is True
    health = client.get("/api/brain-health").json()
    assert health["total_notes"] >= 2
    client.post("/api/notes/smoke-c", json={"title": "C", "category": "Smoke", "content": "{{resumir:esto}}"})
    ann = client.get("/api/annotations").json()["annotations"]
    assert any(a["note_id"] == "smoke-c" and a["tag"] == "resumir" for a in ann)

    assert client.delete("/api/notes/smoke-c").status_code == 200
    assert client.get("/api/notes/smoke-c").status_code == 404


def test_categorias(client):
    r = client.post("/api/categories", json={"name": "Raíz smoke"})
    cid = r.json()["id"]
    r2 = client.post("/api/categories", json={"name": "Hija", "parent_id": cid})
    assert r2.json()["slug"].startswith("raíz-smoke/")
    tree = client.get("/api/categories/tree").json()["tree"]
    assert any(n["id"] == cid and n["children"] for n in tree)
    assert client.get(f"/api/categories/{cid}/notes").status_code == 200
    assert client.post("/api/categories", json={"name": "Raíz smoke"}).status_code == 409
    assert client.delete(f"/api/categories/{cid}").status_code == 200


def test_grafo(client):
    g = client.get("/api/graph").json()
    assert "nodes" in g and "edges" in g
    assert client.post("/api/graph/edges", json={"source": "smoke-a", "target": "smoke-b"}).status_code == 200
    assert client.post("/api/graph/layout", json={"nodes": [{"id": "smoke-a", "x": 1, "y": 2}], "edges": []}).json()["saved"] == 1
    assert client.request("DELETE", "/api/graph/edges", json={"source": "smoke-a", "target": "smoke-b"}).status_code == 200


def test_recursos(client, monkeypatch):
    import app.vault as m
    monkeypatch.setattr(m, "fetch_metadata", lambda url: {"title": "T", "description": "D", "image": "", "resource_type": "web"})
    assert client.post("/api/resources", json={"url": "https://example.org/a", "category": "Lectura"}).status_code == 200
    assert client.post("/api/resources", json={"url": "https://example.org/a"}).status_code == 409
    res = client.get("/api/resources").json()["resources"]
    rid = next(r["id"] for r in res if r["url"] == "https://example.org/a")
    assert client.get("/api/resources?category=Lectura").json()["resources"]
    assert "Lectura" in client.get("/api/resources/categories").json()["categories"]
    assert client.patch(f"/api/resources/{rid}", json={"title": "Nuevo"}).status_code == 200
    assert client.patch(f"/api/resources/{rid}/watch-later").json()["watch_later"] is True
    assert client.patch(f"/api/resources/{rid}/watched").json()["watched"] is True
    assert client.delete(f"/api/resources/{rid}").status_code == 200


def test_inbox(client):
    """Alias antiguo POST /api/inbox (extensión 2.x) + API única /api/items."""
    pid = client.post("/api/inbox", json={"content": "Idea padre", "item_type": "nota"}).json()["id"]
    hid = client.post("/api/items", json={"text": "Hija", "type": "tarea", "parent_id": pid}).json()["id"]
    items = {i["id"]: i for i in client.get("/api/items").json()["items"]}
    assert items[pid]["type"] == "idea" and items[pid]["origin"] == "ideas"
    assert items[hid]["type"] == "idea"  # un paso toma el tipo de su padre
    assert client.patch(f"/api/items/{pid}", json={"text": "Idea editada", "done": True}).status_code == 200
    item = next(i for i in client.get("/api/items").json()["items"] if i["id"] == pid)
    assert item["text"] == "Idea editada" and item["done"] is True
    assert client.delete(f"/api/items/{pid}").json()["undo"]


def test_tableros(client):
    bid = client.post("/api/boards", json={"name": "Tablero"}).json()["id"]
    assert client.get(f"/api/boards/{bid}").json()["data"] == "{}"
    assert client.post(f"/api/boards/{bid}/canvas", json={"data": '{"format": 2, "nodes": []}'}).status_code == 200
    assert client.patch(f"/api/boards/{bid}", json={"name": "Otro"}).status_code == 200
    assert any(b["id"] == bid for b in client.get("/api/boards").json()["boards"])
    assert client.delete(f"/api/boards/{bid}").status_code == 200
    assert client.get(f"/api/boards/{bid}").status_code == 404


def test_tablero_de_una_tarea(client):
    iid = client.post("/api/items", json={"text": "App de recetas"}).json()["id"]
    data = json.dumps({"format": 2, "nodes": [{"id": "n1", "kind": "inbox", "inboxId": iid}], "edges": [], "strokes": []})
    r = client.post("/api/boards", json={"name": "App de recetas", "item_id": iid, "data": data}).json()
    assert client.get(f"/api/boards/{r['id']}").json()["item_id"] == iid
    assert json.loads(client.get(f"/api/boards/{r['id']}").json()["data"])["nodes"][0]["inboxId"] == iid
    # uno por tarea: crearlo otra vez devuelve el mismo
    again = client.post("/api/boards", json={"name": "Otro", "item_id": iid}).json()
    assert again["id"] == r["id"] and again["existing"]
    assert any(b["item_id"] == iid for b in client.get("/api/boards").json()["boards"])
    assert client.post("/api/boards", json={"name": "X", "item_id": 999999}).status_code == 404
    assert client.post("/api/boards", json={"name": "X", "data": '{"nodes": []}'}).status_code == 422


def test_paginas_html(client):
    for path in ["/", "/graph", "/vault", "/inbox", "/comidas/", "/estudio/"]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert "<html" in r.text.lower()


def test_comidas_crud_y_plan(client):
    base = "/comidas/api"
    ids = {}
    for nombre, cat, k, p, c, g in [("Pollo smoke", "carne", 165, 31, 0, 3.6), ("Arroz smoke", "cereal", 130, 2.7, 28, 0.3),
                                     ("Brócoli smoke", "verdura", 34, 2.8, 7, 0.4)]:
        r = client.post(f"{base}/ingredients", json={"nombre": nombre, "categoria": cat, "kcal_100g": k,
                                                       "proteinas_100g": p, "carbohidratos_100g": c, "grasas_100g": g})
        assert r.status_code == 200, r.text
        ids[nombre] = r.json()["id"]
    assert client.post(f"{base}/ingredients", json={"nombre": "Pollo smoke"}).status_code == 409
    assert client.get(f"{base}/ingredients?search=smoke").json()["ingredients"]

    meal = {"nombre": "Pollo con arroz smoke", "franja": "comida", "ingredientes": [
        {"ingredient_id": ids["Pollo smoke"], "gramos": 150}, {"ingredient_id": ids["Arroz smoke"], "gramos": 200},
        {"ingredient_id": ids["Brócoli smoke"], "gramos": 100}], "instrucciones": ["Cocinar"]}
    r = client.post(f"{base}/meals", json=meal)
    mid = r.json()["id"]
    assert r.json()["gramos_recomendados"] > 0
    detail = client.get(f"{base}/meals/{mid}").json()
    # 150g pollo + 200g arroz + 100g brócoli
    assert abs(detail["nutricion_total_receta"]["kcal"] - (247.5 + 260 + 34)) <= 0.5  # kcal en entero
    assert client.get(f"{base}/meals?franja=comida").json()["meals"]
    assert client.post(f"{base}/meals/suggest-gramos", json={"franja": "comida", "ingredientes": meal["ingredientes"]}).status_code == 200
    meal["nombre"] = "Pollo con arroz smoke 2"
    assert client.patch(f"{base}/meals/{mid}", json=meal).status_code == 200

    semana = "2026-10-12"
    assert client.post(f"{base}/weekly-plan/assign", json={"semana": semana, "dia": "lunes", "franja": "comida", "meal_id": mid}).status_code == 200
    plan = client.get(f"{base}/weekly-plan/{semana}").json()["plan"]
    cell = next(p for p in plan if p["dia"] == "lunes" and p["franja"] == "comida")
    assert client.patch(f"{base}/weekly-plan/{cell['id']}/toggle-fixed").json()["is_fixed"] is True
    nut = client.get(f"{base}/weekly-plan/{semana}/nutricion").json()
    assert nut["dias"]["lunes"]["kcal"] > 0 and nut["targets"]["kcal_objetivo"] > 0
    assert client.post(f"{base}/weekly-plan/generate", json={"semana": semana, "franjas": ["comida", "cena"]}).status_code == 200
    assert client.post(f"{base}/shopping-list/from-week/{semana}").json()["added"] >= 1
    assert client.post(f"{base}/shopping-list/from-meal/{mid}").status_code == 200
    client.post(f"{base}/shopping-list", json={"nombre_libre": "Pan", "cantidad_gramos": 1})
    items = client.get(f"{base}/shopping-list").json()["items"]
    pan = next(i for i in items if i["nombre_libre"] == "Pan")
    assert client.patch(f"{base}/shopping-list/{pan['id']}", json={"comprado": True}).status_code == 200
    assert client.delete(f"{base}/shopping-list/done").status_code == 200
    assert client.delete(f"{base}/weekly-plan/{cell['id']}").status_code == 200
    assert client.delete(f"{base}/weekly-plan/{semana}/clear").status_code == 200

    prof = client.get(f"{base}/profile").json()
    assert prof["targets"]["bmr"] > 0
    upd = dict(edad=30, peso_kg=80, altura_cm=180, sexo="hombre", nivel_actividad=1.55, objetivo="mantener", proteina_g_kg=1.8)
    assert client.patch(f"{base}/profile", json=upd).json()["targets"]["proteina_g"] == 144
    assert client.delete(f"{base}/meals/{mid}").status_code == 200
    assert client.delete(f"{base}/ingredients/{ids['Brócoli smoke']}").status_code == 200


def test_pagina_gestion(client):
    r = client.get("/gestion")
    assert r.status_code == 200 and "gestion.js" in r.text and 'href="/gestion"' in r.text
