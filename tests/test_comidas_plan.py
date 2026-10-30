"""Fase 5: varios platos por comida, unidades, totales, objetivos y sugerencias."""
import pytest

BASE = "/comidas/api"
SEMANA = "2026-11-02"


@pytest.fixture(scope="module")
def datos(client):
    def ing(nombre, cat, k, p, c, g, **extra):
        r = client.post(f"{BASE}/ingredients", json={"nombre": nombre, "categoria": cat, "kcal_100g": k, "proteinas_100g": p,
                                                      "carbohidratos_100g": c, "grasas_100g": g, **extra})
        assert r.status_code == 200, r.text
        return r.json()["id"]
    ids = {
        "pollo": ing("Pechuga F5", "proteina", 165, 31, 0, 3.6),
        "arroz": ing("Arroz F5", "cereal", 130, 2.7, 28, 0.3),
        "huevo": ing("Huevo F5", "proteina", 143, 12.6, 0.7, 9.5, gramos_por_unidad=60, unidad_nombre="huevo"),
        "pan": ing("Pan F5", "cereal", 265, 9, 49, 3.2),
        "malo": ing("Dato raro F5", "General", 100, 20, 20, 10),
    }
    def meal(nombre, franja, ingredientes, gramos=0, unica=False):
        r = client.post(f"{BASE}/meals", json={"nombre": nombre, "franja": franja, "ingredientes": ingredientes,
                                                "gramos_recomendados": gramos, "es_racion_unica": unica})
        assert r.status_code == 200, r.text
        return r.json()["id"]
    ids["m_pollo"] = meal("Pollo con arroz F5", "comida", [{"ingredient_id": ids["pollo"], "gramos": 200},
                                                           {"ingredient_id": ids["arroz"], "gramos": 200}], gramos=400)
    ids["m_huevos"] = meal("Huevos F5", "desayuno", [{"ingredient_id": ids["huevo"], "unidades": 2}], unica=True)
    ids["m_pan"] = meal("Pan F5 plato", "comida", [{"ingredient_id": ids["pan"], "gramos": 100}], unica=True)
    return ids


def test_unidades_se_convierten_a_gramos(client, datos):
    meal = client.get(f"{BASE}/meals/{datos['m_huevos']}").json()
    ing = meal["ingredientes"][0]
    assert ing["unidades"] == 2 and ing["gramos"] == 120
    assert meal["nutricion_total"]["kcal"] == round(143 * 1.2)
    r = client.post(f"{BASE}/meals", json={"nombre": "Sin unidad", "ingredientes": [{"ingredient_id": datos["pollo"], "unidades": 1}]})
    assert r.status_code == 422 and "gramos por unidad" in r.json()["error"]


def test_cambiar_gramos_por_unidad_recalcula_recetas(client, datos):
    base = {"nombre": "Huevo F5", "categoria": "proteina", "kcal_100g": 143, "proteinas_100g": 12.6,
            "carbohidratos_100g": 0.7, "grasas_100g": 9.5, "unidad_nombre": "huevo"}
    client.patch(f"{BASE}/ingredients/{datos['huevo']}", json={**base, "gramos_por_unidad": 50})
    assert client.get(f"{BASE}/meals/{datos['m_huevos']}").json()["ingredientes"][0]["gramos"] == 100
    client.patch(f"{BASE}/ingredients/{datos['huevo']}", json={**base, "gramos_por_unidad": 60})


def test_validacion_atwater(client, datos):
    bad = client.get(f"{BASE}/ingredients/validation").json()["inconsistentes"]
    nombres = {b["nombre"] for b in bad}
    assert "Dato raro F5" in nombres and "Pechuga F5" not in nombres
    lista = client.get(f"{BASE}/ingredients?search=F5").json()["ingredients"]
    assert all("kcal_check" in i for i in lista)


def test_varios_platos_por_comida_y_totales(client, datos):
    r1 = client.post(f"{BASE}/weekly-plan/slots", json={"semana": SEMANA, "dia": "lunes", "franja": "comida", "meal_id": datos["m_pollo"]})
    assert r1.json()["kind"] == "principal"
    r2 = client.post(f"{BASE}/weekly-plan/slots", json={"semana": SEMANA, "dia": "lunes", "franja": "comida", "meal_id": datos["m_pan"], "gramos": 50})
    assert r2.json()["kind"] == "extra"
    client.post(f"{BASE}/weekly-plan/slots", json={"semana": SEMANA, "dia": "lunes", "franja": "desayuno", "meal_id": datos["m_huevos"]})

    state = client.get(f"{BASE}/weekly-plan/{SEMANA}/full").json()
    lunes = state["dias"]["lunes"]
    comida = lunes["comidas"]["comida"]
    assert [p["kind"] for p in comida["platos"]] == ["principal", "extra"]
    pollo_kcal = (165 * 2 + 130 * 2)          # 400 g de receta = ración completa
    pan_kcal = 265 * 0.5                      # 50 g
    assert comida["total"]["kcal"] == round(pollo_kcal + pan_kcal)
    huevos_kcal = 143 * 1.2
    assert lunes["total"]["kcal"] == round(pollo_kcal + pan_kcal + huevos_kcal)
    assert list(lunes["comidas"]) == ["desayuno", "comida"]          # orden natural
    assert lunes["progreso"]["kcal"] == round(lunes["total"]["kcal"] / state["objetivo_dia"]["kcal"] * 100)
    assert state["semana_total"]["kcal"] == lunes["total"]["kcal"]
    assert state["objetivo_semana"]["kcal"] == state["objetivo_dia"]["kcal"] * 7
    # el endpoint antiguo de nutrición incluye también el plato extra
    nut = client.get(f"{BASE}/weekly-plan/{SEMANA}/nutricion").json()
    assert nut["dias"]["lunes"]["kcal"] == lunes["total"]["kcal"]


def test_raciones_personalizadas_y_borrado(client, datos):
    state = client.get(f"{BASE}/weekly-plan/{SEMANA}/full").json()
    comida = state["dias"]["lunes"]["comidas"]["comida"]
    plan_id = comida["plan_id"]
    extra = comida["platos"][1]
    client.patch(f"{BASE}/weekly-plan/{plan_id}/gramos", json={"gramos": 200})        # media ración del principal
    client.patch(f"{BASE}/weekly-plan/items/{extra['item_id']}", json={"gramos": 100})
    comida = client.get(f"{BASE}/weekly-plan/{SEMANA}/full").json()["dias"]["lunes"]["comidas"]["comida"]
    assert comida["platos"][0]["gramos"] == 200 and comida["platos"][0]["personalizado"]
    assert comida["total"]["kcal"] == round((165 * 2 + 130 * 2) / 2 + 265)
    client.patch(f"{BASE}/weekly-plan/{plan_id}/gramos", json={"gramos": None})       # vuelve a la ración estándar
    client.delete(f"{BASE}/weekly-plan/items/{extra['item_id']}")
    comida = client.get(f"{BASE}/weekly-plan/{SEMANA}/full").json()["dias"]["lunes"]["comidas"]["comida"]
    assert len(comida["platos"]) == 1 and not comida["platos"][0]["personalizado"]


def test_lista_compra_usa_la_racion_real(client, datos):
    client.delete(f"{BASE}/shopping-list/done")
    for it in client.get(f"{BASE}/shopping-list").json()["items"]:
        client.delete(f"{BASE}/shopping-list/{it['id']}")
    plan_id = client.get(f"{BASE}/weekly-plan/{SEMANA}/full").json()["dias"]["lunes"]["comidas"]["comida"]["plan_id"]
    client.patch(f"{BASE}/weekly-plan/{plan_id}/gramos", json={"gramos": 200})        # mitad de la receta
    client.post(f"{BASE}/shopping-list/from-week/{SEMANA}")
    items = {i["ingredient_nombre"]: i["cantidad_gramos"] for i in client.get(f"{BASE}/shopping-list").json()["items"]}
    assert items["Pechuga F5"] == 100 and items["Arroz F5"] == 100 and items["Huevo F5"] == 120
    client.patch(f"{BASE}/weekly-plan/{plan_id}/gramos", json={"gramos": None})


def test_sugerencias(client, datos):
    r = client.get(f"{BASE}/weekly-plan/{SEMANA}/sugerencias", params={"dia": "martes", "franja": "comida"})
    assert r.status_code == 200
    body = r.json()
    assert body["platos"] and all(p["franja"] == "comida" for p in body["platos"])
    assert body["hueco"]["kcal"] < body["restante_dia"]["kcal"]
    assert isinstance(body["ingredientes"], list)
    assert client.get(f"{BASE}/weekly-plan/{SEMANA}/sugerencias", params={"dia": "funday"}).status_code == 422


def test_perfil_con_reparto_configurable(client):
    r = client.patch(f"{BASE}/profile", json={"edad": 30, "peso_kg": 80, "altura_cm": 180, "sexo": "hombre",
                                               "nivel_actividad": 1.55, "objetivo": "perder", "proteina_g_kg": 2.0,
                                               "grasa_pct": 30, "ajuste_pct": -15})
    t = r.json()["targets"]
    assert t["objetivo"] == "definicion" and t["kcal_objetivo"] == round(2759 * 0.85)
    assert t["proteina_g"] == 160 and t["grasa_g"] == round(2759 * 0.85 * 0.30 / 9)
    prof = client.get(f"{BASE}/profile").json()
    assert prof["objetivo"] == "definicion" and prof["grasa_pct"] == 30 and prof["ajuste_pct"] == -15
    assert client.patch(f"{BASE}/profile", json={**{k: prof[k] for k in ("edad", "peso_kg", "altura_cm", "sexo", "nivel_actividad", "objetivo", "proteina_g_kg")},
                                                 "grasa_pct": 80}).status_code == 422


def test_generador_respeta_los_platos_extra(client, datos):
    semana = "2026-11-09"
    client.post(f"{BASE}/weekly-plan/slots", json={"semana": semana, "dia": "lunes", "franja": "comida", "meal_id": datos["m_pollo"]})
    client.post(f"{BASE}/weekly-plan/slots", json={"semana": semana, "dia": "lunes", "franja": "comida", "meal_id": datos["m_pan"]})
    assert client.post(f"{BASE}/weekly-plan/generate", json={"semana": semana, "franjas": ["comida", "cena"]}).status_code == 200
    comida = client.get(f"{BASE}/weekly-plan/{semana}/full").json()["dias"]["lunes"]["comidas"]["comida"]
    assert any(p["kind"] == "extra" for p in comida["platos"])
    client.delete(f"{BASE}/weekly-plan/{semana}/clear")
    comida = client.get(f"{BASE}/weekly-plan/{semana}/full").json()["dias"]["lunes"]["comidas"]["comida"]
    assert comida["platos"] == []


def test_exportar_lista_semana(client, datos):
    r = client.get(f"{BASE}/shopping-list/export/{SEMANA}?formato=txt")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert "Pechuga F5: 200 g" in r.text and "Huevo F5: 120 g (≈ 2 huevo)" in r.text
    csv_ = client.get(f"{BASE}/shopping-list/export/{SEMANA}?formato=csv")
    assert csv_.text.splitlines()[0] == "categoria,ingrediente,gramos,unidades,unidad"
    js = client.get(f"{BASE}/shopping-list/export/{SEMANA}?formato=json").json()
    assert any(i["ingrediente"] == "Arroz F5" and i["gramos"] == 200 for i in js["items"])
