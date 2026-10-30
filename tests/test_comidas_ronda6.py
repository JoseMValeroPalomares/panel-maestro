"""Sexta ronda · Comidas: franjas, varios platos con papel, plato doble, plantillas y favoritos,
lista de la compra de la semana (sumada y sin duplicar) y registro de peso con tendencia."""
from datetime import date, timedelta

import pytest

from comidas.planner import sugerencia, tendencia

BASE = "/comidas/api"
SEMANA = "2026-12-07"


@pytest.fixture(scope="module")
def d(client):
    def ing(nombre, k, p, c, g, **extra):
        r = client.post(f"{BASE}/ingredients", json={"nombre": nombre, "categoria": "General", "kcal_100g": k, "proteinas_100g": p,
                                                      "carbohidratos_100g": c, "grasas_100g": g, **extra})
        assert r.status_code == 200, r.text
        return r.json()["id"]
    ids = {"lechuga": ing("Lechuga R6", 15, 1.4, 2.9, 0.2), "aceite": ing("Aceite R6", 884, 0, 0, 100),
           "pollo": ing("Pollo R6", 165, 31, 0, 3.6), "arroz": ing("Arroz R6", 130, 2.7, 28, 0.3),
           "yogur": ing("Yogur R6", 60, 4, 5, 3, gramos_por_unidad=125, unidad_nombre="yogur")}

    def meal(nombre, franja, ingredientes, gramos, tags=""):
        r = client.post(f"{BASE}/meals", json={"nombre": nombre, "franja": franja, "ingredientes": ingredientes,
                                                "gramos_recomendados": gramos, "tags": tags})
        assert r.status_code == 200, r.text
        return r.json()["id"]
    # Ensalada: 200 g lechuga + 10 g aceite = 210 g → 30 + 88.4 = 118.4 kcal
    ids["ensalada"] = meal("Ensalada R6", "comida", [{"ingredient_id": ids["lechuga"], "gramos": 200},
                                                     {"ingredient_id": ids["aceite"], "gramos": 10}], 210, "primero, verdura")
    # Pollo con arroz: 150 + 150 = 300 g → 247.5 + 195 = 442.5 kcal
    ids["pollo_arroz"] = meal("Pollo con arroz R6", "comida", [{"ingredient_id": ids["pollo"], "gramos": 150},
                                                               {"ingredient_id": ids["arroz"], "gramos": 150}], 300, "segundo")
    ids["yogur_m"] = meal("Yogur R6 plato", "merienda", [{"ingredient_id": ids["yogur"], "unidades": 1}], 125, "postre")
    return ids


def _slot(client, dia, franja, semana=SEMANA):
    return client.get(f"{BASE}/weekly-plan/{semana}/full").json()["dias"][dia]["comidas"].get(franja)


def test_franjas_nuevas_y_personalizadas(client, d):
    claves = [f["clave"] for f in client.get(f"{BASE}/franjas").json()["franjas"]]
    assert claves[:5] == ["desayuno", "comida", "merienda", "cena", "extras"] and "media-manana" not in claves  # quitada (migración 3)
    r = client.post(f"{BASE}/franjas", json={"nombre": "Antes de entrenar", "hora": "18:30"})
    clave = r.json()["clave"]
    assert clave == "antes-de-entrenar"
    # se puede usar como cualquier otra comida
    assert client.post(f"{BASE}/weekly-plan/slots", json={"semana": SEMANA, "dia": "martes", "franja": clave,
                                                          "meal_id": d["yogur_m"]}).status_code == 200
    assert client.post(f"{BASE}/weekly-plan/slots", json={"semana": SEMANA, "dia": "martes", "franja": "merienda",
                                                          "meal_id": d["yogur_m"]}).status_code == 200
    state = client.get(f"{BASE}/weekly-plan/{SEMANA}/full").json()
    assert list(state["dias"]["martes"]["comidas"]) == ["merienda", clave]  # en su orden
    assert client.post(f"{BASE}/weekly-plan/slots", json={"semana": SEMANA, "dia": "martes", "franja": "inventada",
                                                          "meal_id": d["yogur_m"]}).status_code == 422
    # una de partida solo se oculta; una propia en uso, también
    assert client.delete(f"{BASE}/franjas/extras").json()["oculta"] is True
    assert client.delete(f"{BASE}/franjas/{clave}").json()["oculta"] is True
    client.patch(f"{BASE}/franjas/extras", json={"activa": True})


def test_comida_con_varios_platos_y_plato_doble(client, d):
    # una comida con un plato y su postre
    client.post(f"{BASE}/weekly-plan/slots", json={"semana": SEMANA, "dia": "lunes", "franja": "cena", "meal_id": d["pollo_arroz"], "gramos": 300, "rol": "unico"})
    client.post(f"{BASE}/weekly-plan/slots", json={"semana": SEMANA, "dia": "lunes", "franja": "cena", "meal_id": d["yogur_m"], "rol": "postre"})
    cena = _slot(client, "lunes", "cena")
    assert [p["rol"] for p in cena["platos"]] == ["unico", "postre"]
    assert cena["platos"][0]["macros"]["kcal"] == pytest.approx(442.5, abs=1)
    assert cena["platos"][1]["macros"]["kcal"] == pytest.approx(75, abs=1)           # 125 g de yogur
    assert cena["total"]["kcal"] == pytest.approx(442.5 + 75, abs=1)
    # plato doble con un clic en la comida
    r = client.post(f"{BASE}/weekly-plan/doble", json={"semana": SEMANA, "dia": "lunes", "franja": "comida"})
    assert r.status_code == 200, r.text
    body = r.json()
    comida = _slot(client, "lunes", "comida")
    assert [p["rol"] for p in comida["platos"]] == ["primero", "segundo"]
    assert [p["meal_id"] for p in comida["platos"]] == [body["primero"]["meal_id"], body["segundo"]["meal_id"]]
    esperado = 0
    for p in comida["platos"]:  # macros de cada plato = su receta escalada a su ración
        m = client.get(f"{BASE}/meals/{p['meal_id']}").json()
        kcal = m["nutricion_total_receta"]["kcal"] * p["gramos"] / m["gramos_totales_receta"]
        assert p["macros"]["kcal"] == pytest.approx(kcal, abs=1)
        esperado += kcal
    assert comida["total"]["kcal"] == pytest.approx(esperado, abs=1.5)
    dia = client.get(f"{BASE}/weekly-plan/{SEMANA}/full").json()["dias"]["lunes"]
    assert dia["total"]["kcal"] == pytest.approx(esperado + 442.5 + 75, abs=2)
    # cambiar el papel de un plato
    p0 = comida["platos"][0]
    assert client.patch(f"{BASE}/weekly-plan/rol", json={"plan_id": p0["plan_id"], "item_id": p0["item_id"], "rol": "guarnicion"}).status_code == 200
    assert _slot(client, "lunes", "comida")["platos"][0]["rol"] == "guarnicion"


def test_plantillas_y_favoritos(client, d):
    cena = _slot(client, "lunes", "cena")
    r = client.post(f"{BASE}/meal-templates", json={"nombre": "Cena de diario", "plan_id": cena["plan_id"], "favorito": True})
    tid = r.json()["id"]
    tpl = next(t for t in client.get(f"{BASE}/meal-templates").json()["plantillas"] if t["id"] == tid)
    assert tpl["favorito"] and [i["nombre"] for i in tpl["items"]] == ["Pollo con arroz R6", "Yogur R6 plato"]
    client.post(f"{BASE}/meal-templates/{tid}/apply", json={"semana": SEMANA, "dia": "jueves", "franja": "cena"})
    jueves = _slot(client, "jueves", "cena")
    assert [p["meal_id"] for p in jueves["platos"]] == [p["meal_id"] for p in cena["platos"]]
    assert jueves["total"]["kcal"] == cena["total"]["kcal"]
    # aplicar reemplazando no acumula
    client.post(f"{BASE}/meal-templates/{tid}/apply", json={"semana": SEMANA, "dia": "jueves", "franja": "cena", "reemplazar": True})
    assert len(_slot(client, "jueves", "cena")["platos"]) == 2
    assert client.patch(f"{BASE}/meals/{d['ensalada']}/favorito", json={"favorito": True}).status_code == 200
    fav = next(m for m in client.get(f"{BASE}/meals").json()["meals"] if m["id"] == d["ensalada"])
    assert fav["favorito"] == 1


def test_lista_de_la_compra_suma_y_no_duplica(client, d):
    semana = "2026-12-14"
    # pollo con arroz dos veces (300 g y 150 g) y plato doble de ensalada (210 g)
    client.post(f"{BASE}/weekly-plan/slots", json={"semana": semana, "dia": "lunes", "franja": "comida", "meal_id": d["pollo_arroz"], "gramos": 300})
    client.post(f"{BASE}/weekly-plan/slots", json={"semana": semana, "dia": "martes", "franja": "cena", "meal_id": d["pollo_arroz"], "gramos": 150})
    client.post(f"{BASE}/weekly-plan/slots", json={"semana": semana, "dia": "martes", "franja": "cena", "meal_id": d["ensalada"], "gramos": 210})
    datos = client.get(f"{BASE}/shopping-list/export/{semana}?formato=json").json()["items"]
    g = {i["ingrediente"]: i["gramos"] for i in datos}
    assert g["Pollo R6"] == 150 + 75 and g["Arroz R6"] == 150 + 75   # sumado por ingrediente
    assert g["Lechuga R6"] == 200 and g["Aceite R6"] == 10
    csv = client.get(f"{BASE}/shopping-list/export/{semana}?formato=csv").text
    assert "Pollo R6" in csv and csv.startswith("categoria,ingrediente,gramos")

    def lista():
        return {i["ingredient_nombre"]: i for i in client.get(f"{BASE}/shopping-list").json()["items"] if i["ingredient_nombre"]}
    client.post(f"{BASE}/shopping-list", json={"ingredient_id": d["pollo"], "cantidad_gramos": 100})  # a mano
    client.post(f"{BASE}/shopping-list/from-week/{semana}")
    client.post(f"{BASE}/shopping-list/from-week/{semana}")  # dos veces: no duplica
    li = lista()
    assert li["Pollo R6"]["cantidad_gramos"] == 100 + 225
    assert li["Arroz R6"]["cantidad_gramos"] == 225
    # quitar un plato del plan y regenerar descuenta lo suyo
    ens = next(p for p in _slot(client, "martes", "cena", semana)["platos"] if p["meal_id"] == d["ensalada"])
    client.delete(f"{BASE}/weekly-plan/items/{ens['item_id']}")
    client.post(f"{BASE}/shopping-list/from-week/{semana}")
    li = lista()
    assert "Lechuga R6" not in li and li["Pollo R6"]["cantidad_gramos"] == 325


def test_tendencia_y_sugerencia():
    hoy = date(2026, 10, 24)
    pts = [(hoy - timedelta(days=21 - i), 80 - 0.1 * i) for i in range(0, 22, 3)]  # −0,7 kg/semana
    t = tendencia(pts, hoy)
    assert t["kg_semana"] == pytest.approx(-0.7, abs=0.01)
    assert tendencia(pts[:2], hoy) is None
    perfil = {"peso_kg": 80, "altura_cm": 180, "edad": 30, "sexo": "hombre", "nivel_actividad": 1.55,
              "objetivo": "mantenimiento", "proteina_g_kg": 1.6, "grasa_pct": 25, "ajuste_pct": None}
    s = sugerencia(t, perfil)  # mantener pero bajando 0,7 kg/sem: hay que comer ~770 kcal más (tope 400)
    assert s["delta_kcal"] == 400 and s["ajuste_pct"] > 0
    perfil["objetivo"] = "definicion"  # objetivo −0,4 kg/sem: va algo rápido
    s = sugerencia(t, perfil)
    assert 0 < s["delta_kcal"] < 400


def test_registro_corporal_api(client):
    hoy = date.today()
    for i, peso in enumerate([82.0, 81.8, 81.5, 81.3, 81.0]):
        r = client.put(f"{BASE}/body/{(hoy - timedelta(days=14 - 3 * i)).isoformat()}", json={"peso_kg": peso, "cintura_cm": 90 - i * 0.5})
        assert r.status_code == 200
    assert client.put(f"{BASE}/body/{hoy.isoformat()}", json={}).status_code == 422
    data = client.get(f"{BASE}/body").json()
    assert len(data["registros"]) >= 5 and data["tendencia"]["kg_semana"] < 0
    s = data["sugerencia"]
    r = client.post(f"{BASE}/body/aplicar-ajuste", json={"ajuste_pct": s["ajuste_pct"]})
    assert r.json()["targets"]["ajuste_pct"] == pytest.approx(s["ajuste_pct"], abs=0.1)
    assert client.get(f"{BASE}/profile").json()["peso_kg"] == 81.0


def test_franja_desactivada_en_algunos_dias(client, d):
    """Séptima ronda: una franja (extras, merienda o cualquiera) se quita en uno, varios o todos los días."""
    semana = "2026-12-21"
    r = client.patch(f"{BASE}/franjas/merienda", json={"dias": ["lunes", "martes", "miercoles", "jueves", "viernes"]})
    assert r.status_code == 200, r.text
    f = next(x for x in client.get(f"{BASE}/franjas").json()["franjas"] if x["clave"] == "merienda")
    assert f["activa"] and f["dias"] == ["lunes", "martes", "miercoles", "jueves", "viernes"]
    plan = client.get(f"{BASE}/weekly-plan/{semana}/full").json()
    assert next(x for x in plan["franjas"] if x["clave"] == "merienda")["dias"][-1] == "viernes"
    # el generador no llena la franja los días en que está quitada
    assert client.post(f"{BASE}/weekly-plan/generate", json={"semana": semana, "franjas": ["merienda", "comida", "cena"]}).status_code == 200
    dias = client.get(f"{BASE}/weekly-plan/{semana}/full").json()["dias"]
    assert not (dias["sabado"]["comidas"].get("merienda") or {}).get("platos")
    assert not (dias["domingo"]["comidas"].get("merienda") or {}).get("platos")
    # los 7 días = todos (NULL); ninguno = oculta
    client.patch(f"{BASE}/franjas/merienda", json={"dias": ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]})
    assert next(x for x in client.get(f"{BASE}/franjas").json()["franjas"] if x["clave"] == "merienda")["dias"] is None
    client.patch(f"{BASE}/franjas/extras", json={"dias": []})
    ex = next(x for x in client.get(f"{BASE}/franjas").json()["franjas"] if x["clave"] == "extras")
    assert not ex["activa"]
    assert client.patch(f"{BASE}/franjas/extras", json={"dias": ["festivo"]}).status_code == 422
    # se deja como estaba para el resto de tests
    client.patch(f"{BASE}/franjas/extras", json={"dias": ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]})
    # (merienda vuelve a todos los días arriba)
