"""Fase 6: gestión masiva de ingredientes, platos y celdas del plan (con deshacer)."""
import pytest

BASE = "/comidas/api"
BULK = f"{BASE}/bulk"
SEMANA = "2027-01-04"


@pytest.fixture(scope="module")
def cat(client):
    def ing(nombre, k, p, c, g, **extra):
        r = client.post(f"{BASE}/ingredients", json={"nombre": nombre, "categoria": "LoteCat", "kcal_100g": k,
                                                      "proteinas_100g": p, "carbohidratos_100g": c, "grasas_100g": g, **extra})
        return r.json()["id"]
    ids = {"a": ing("Lote Avena", 380, 13, 60, 7), "b": ing("Lote Leche", 46, 3.4, 4.8, 1.5),
           "h": ing("Lote Huevo", 143, 12.6, 0.7, 9.5, gramos_por_unidad=60, unidad_nombre="huevo")}
    r = client.post(f"{BASE}/meals", json={"nombre": "Lote Porridge", "franja": "desayuno", "tags": "rápido, dulce",
                                           "ingredientes": [{"ingredient_id": ids["a"], "gramos": 60},
                                                            {"ingredient_id": ids["b"], "gramos": 250}]})
    ids["m"] = r.json()["id"]
    return ids


def test_ingredientes_lote_y_deshacer(client, cat):
    r = client.post(f"{BULK}/ingredients/update", json={"ids": [cat["a"], cat["b"]], "categoria": "Desayuno"})
    assert r.json()["updated"] == 2
    client.post(f"{BASE}/shopping-list", json={"ingredient_id": cat["b"], "cantidad_gramos": 500})

    r = client.post(f"{BULK}/ingredients/delete", json={"ids": [cat["b"]]}).json()
    assert r["deleted"] == 1
    meal = client.get(f"{BASE}/meals/{cat['m']}").json()
    assert [i["nombre"] for i in meal["ingredientes"]] == ["Lote Avena"]
    linea = next(i for i in client.get(f"{BASE}/shopping-list").json()["items"] if i.get("nombre_libre") == "Lote Leche")
    assert linea["ingredient_id"] is None

    assert client.post(f"{BULK}/undo/{r['undo_token']}").json()["restored"] == 1
    meal = client.get(f"{BASE}/meals/{cat['m']}").json()
    assert sorted(i["nombre"] for i in meal["ingredientes"]) == ["Lote Avena", "Lote Leche"]
    items = client.get(f"{BASE}/shopping-list").json()["items"]
    assert any(i["ingredient_id"] == cat["b"] for i in items)
    assert client.post(f"{BULK}/undo/{r['undo_token']}").status_code == 404


def test_ingredientes_duplicar_exportar_importar(client, cat):
    new = client.post(f"{BULK}/ingredients/duplicate", json={"ids": [cat["a"], cat["a"]]}).json()["created"]
    assert len(new) == 1
    nombres = {i["nombre"] for i in client.get(f"{BASE}/ingredients", params={"search": "Lote Avena"}).json()["ingredients"]}
    assert "Lote Avena (copia)" in nombres

    csv_txt = client.get(f"{BULK}/ingredients/export", params={"format": "csv", "ids": cat["h"]}).text
    assert "Lote Huevo" in csv_txt and "huevo" in csv_txt
    data = ("nombre,categoria,kcal_100g,proteinas_100g,carbohidratos_100g,grasas_100g\n"
            "Lote Nuevo,Fruta,\"52,0\",0.3,14,0.2\n"
            "Lote Huevo,Proteína,150,13,1,10\n"
            "Lote Raro,X,10,50,50,50\n"
            ",X,1,1,1,1\n")
    files = {"file": ("i.csv", data.encode(), "text/csv")}
    prev = client.post(f"{BULK}/ingredients/import", files=files, data={"dry_run": "1"}).json()
    assert prev["crear"] == ["Lote Nuevo", "Lote Raro"] and prev["omitir"] == ["Lote Huevo"]
    assert len(prev["errores"]) == 1 and prev["avisos"][0]["fila"] == 3
    res = client.post(f"{BULK}/ingredients/import", files=files, data={"mode": "overwrite"}).json()
    assert res["sobrescribir"] == ["Lote Huevo"]
    huevo = next(i for i in client.get(f"{BASE}/ingredients", params={"search": "Lote Huevo"}).json()["ingredients"]
                 if i["nombre"] == "Lote Huevo")
    assert huevo["kcal_100g"] == 150
    nuevo = client.get(f"{BASE}/ingredients", params={"search": "Lote Nuevo"}).json()["ingredients"][0]
    assert nuevo["kcal_100g"] == 52


def test_platos_lote_duplicar_exportar_importar(client, cat):
    r = client.post(f"{BULK}/meals/update", json={"ids": [cat["m"]], "franja": "merienda", "tags_add": ["fibra"], "tags_remove": ["dulce"]})
    assert r.json()["updated"] == 1
    meal = client.get(f"{BASE}/meals/{cat['m']}").json()
    assert meal["franja"] == "merienda" and meal["tags"] == "rápido, fibra"
    assert client.post(f"{BULK}/meals/update", json={"ids": [cat["m"]], "franja": "brunch"}).status_code == 422

    dup = client.post(f"{BULK}/meals/duplicate", json={"ids": [cat["m"]]}).json()["created"][0]
    copia = client.get(f"{BASE}/meals/{dup}").json()
    assert copia["nombre"] == "Lote Porridge (copia)" and len(copia["ingredientes"]) == 2

    exp = client.get(f"{BULK}/meals/export", params={"ids": cat["m"]}).json()["meals"][0]
    assert exp["kcal_racion"] > 0 and {i["nombre"] for i in exp["ingredientes"]} == {"Lote Avena", "Lote Leche"}
    csv_txt = client.get(f"{BULK}/meals/export", params={"format": "csv", "ids": cat["m"]}).text
    assert "Lote Avena: 60 g" in csv_txt

    data = ("nombre,franja,ingredientes,es_racion_unica,instrucciones\n"
            "Lote Tortilla,cena,Lote Huevo: 3 ud; Lote Leche: 30 g,1,Batir | Cuajar\n"
            "Lote Imposible,cena,Unicornio: 10 g,0,\n"
            "Lote Porridge,desayuno,Lote Avena: 50 g,0,\n")
    files = {"file": ("p.csv", data.encode(), "text/csv")}
    prev = client.post(f"{BULK}/meals/import", files=files, data={"dry_run": "true"}).json()
    assert prev["crear"] == ["Lote Tortilla"] and prev["omitir"] == ["Lote Porridge"], prev
    assert "Unicornio" in prev["errores"][0]["error"]
    client.post(f"{BULK}/meals/import", files=files)
    tortilla = next(m for m in client.get(f"{BASE}/meals").json()["meals"] if m["nombre"] == "Lote Tortilla")
    detalle = client.get(f"{BASE}/meals/{tortilla['id']}").json()
    huevo = next(i for i in detalle["ingredientes"] if i["nombre"] == "Lote Huevo")
    assert huevo["unidades"] == 3 and huevo["gramos"] == 180
    assert detalle["instrucciones"] == ["Batir", "Cuajar"] and detalle["es_racion_unica"] is True


def test_platos_borrar_y_deshacer_con_plan(client, cat):
    client.post(f"{BASE}/weekly-plan/slots", json={"semana": SEMANA, "dia": "lunes", "franja": "desayuno", "meal_id": cat["m"], "gramos": 250})
    full = client.get(f"{BASE}/weekly-plan/{SEMANA}/full").json()
    plan_id = full["dias"]["lunes"]["comidas"]["desayuno"]["plan_id"]
    client.post(f"{BASE}/weekly-plan/{plan_id}/items", json={"meal_id": cat["m"], "gramos": 100})

    r = client.post(f"{BULK}/meals/delete", json={"ids": [cat["m"]]}).json()
    assert r["deleted"] == 1
    assert client.get(f"{BASE}/meals/{cat['m']}").status_code == 404
    assert not client.get(f"{BASE}/weekly-plan/{SEMANA}/full").json()["dias"]["lunes"]["comidas"].get("desayuno", {}).get("platos")

    client.post(f"{BULK}/undo/{r['undo_token']}")
    assert len(client.get(f"{BASE}/meals/{cat['m']}").json()["ingredientes"]) == 2
    platos = client.get(f"{BASE}/weekly-plan/{SEMANA}/full").json()["dias"]["lunes"]["comidas"].get("desayuno", {}).get("platos")
    assert len(platos) == 2


def test_plan_copiar_y_borrar_celdas(client, cat):
    destino = "2027-01-11"
    r = client.post(f"{BULK}/plan/copy-week", json={"origen": SEMANA, "destino": destino}).json()
    assert r["copied"] >= 1
    assert client.post(f"{BULK}/plan/copy-week", json={"origen": SEMANA, "destino": destino}).json()["skipped"] >= 1
    dia = client.get(f"{BASE}/weekly-plan/{destino}/full").json()["dias"]["lunes"]["comidas"]["desayuno"]
    assert len(dia["platos"]) == 2

    r = client.post(f"{BULK}/plan/delete", json={"ids": [dia["plan_id"]]}).json()
    assert r["deleted"] == 1
    assert not client.get(f"{BASE}/weekly-plan/{destino}/full").json()["dias"]["lunes"]["comidas"].get("desayuno", {}).get("platos")
    client.post(f"{BULK}/undo/{r['undo_token']}")
    assert len(client.get(f"{BASE}/weekly-plan/{destino}/full").json()["dias"]["lunes"]["comidas"]["desayuno"]["platos"]) == 2


def test_importar_sobrescribir_conserva_columnas_ausentes(client, cat):
    data = "nombre,kcal_100g\nLote Huevo,155\n"
    client.post(f"{BULK}/ingredients/import", files={"file": ("i.csv", data.encode(), "text/csv")}, data={"mode": "overwrite"})
    huevo = next(i for i in client.get(f"{BASE}/ingredients", params={"search": "Lote Huevo"}).json()["ingredients"]
                 if i["nombre"] == "Lote Huevo")
    assert huevo["kcal_100g"] == 155 and huevo["gramos_por_unidad"] == 60 and huevo["proteinas_100g"] == 13
