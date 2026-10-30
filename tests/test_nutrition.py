"""Casos conocidos para los cálculos de comidas/nutrition.py."""
import pytest

from comidas import nutrition as nu

POLLO = {"kcal_100g": 165, "proteinas_100g": 31, "carbohidratos_100g": 0, "grasas_100g": 3.6}
ARROZ = {"kcal_100g": 130, "proteinas_100g": 2.7, "carbohidratos_100g": 28, "grasas_100g": 0.3}
ACEITE = {"kcal_100g": 884, "proteinas_100g": 0, "carbohidratos_100g": 0, "grasas_100g": 100}


def test_macros_por_cantidad_escala_por_100g():
    m = nu.macros_por_cantidad(POLLO, 150)
    assert m["kcal"] == pytest.approx(247.5)
    assert m["proteinas"] == pytest.approx(46.5)
    assert m["grasas"] == pytest.approx(5.4)
    assert nu.macros_por_cantidad(POLLO, 0)["kcal"] == 0


def test_receta_suma_y_racion_escala():
    total, gramos = nu.receta([{**POLLO, "gramos": 150}, {**ARROZ, "gramos": 200}, {**ACEITE, "gramos": 10}])
    assert gramos == 360
    assert total["kcal"] == pytest.approx(247.5 + 260 + 88.4)
    assert total["carbohidratos"] == pytest.approx(56)
    mitad = nu.racion(total, gramos, 180)
    assert mitad["kcal"] == pytest.approx(total["kcal"] / 2)
    assert nu.densidad_100g(total, gramos)["kcal"] == pytest.approx(total["kcal"] / 3.6)
    assert nu.racion(total, 0, 100)["kcal"] == 0


def test_suma_por_plato_comida_y_dia():
    plato1 = nu.macros_por_cantidad(POLLO, 100)
    plato2 = nu.macros_por_cantidad(ARROZ, 100)
    comida = nu.sumar(plato1, plato2)
    cena = nu.macros_por_cantidad(POLLO, 200)
    dia = nu.sumar(comida, cena)
    assert comida["kcal"] == pytest.approx(295)
    assert dia["proteinas"] == pytest.approx(31 + 2.7 + 62)


def test_atwater_ok_y_avisos():
    assert nu.kcal_atwater(10, 20, 5) == 165
    assert nu.comprobar_kcal(884, 0, 0, 100)["ok"]              # aceite: 900 esperadas, 1.8 %
    assert nu.comprobar_kcal(165, 31, 0, 3.6)["ok"]              # pollo: 156.4 esperadas
    malo = nu.comprobar_kcal(100, 20, 20, 10)                    # 250 esperadas
    assert not malo["ok"] and malo["esperadas"] == 250 and malo["diferencia"] == -150
    assert nu.comprobar_kcal(20, 1, 2, 0.2)["ok"]                # verdura: diferencia absoluta pequeña


def test_tmb_mifflin_st_jeor():
    assert nu.tmb_mifflin(80, 180, 30, "hombre") == pytest.approx(1780)
    assert nu.tmb_mifflin(60, 165, 25, "mujer") == pytest.approx(1345.25)


def test_objetivos_mantenimiento_y_reparto():
    obj = nu.calcular_objetivos({"peso_kg": 80, "altura_cm": 180, "edad": 30, "sexo": "hombre",
                                 "nivel_actividad": 1.55, "objetivo": "mantenimiento", "proteina_g_kg": 1.8})
    assert obj["bmr"] == 1780 and obj["tdee"] == 2759
    assert obj["kcal_objetivo"] == 2759
    assert obj["proteina_g"] == 144
    assert obj["grasa_g"] == round(2759 * 0.25 / 9)
    assert obj["carbohidratos_g"] == round((2759 - 144 * 4 - 2759 * 0.25) / 4)
    # las kcal de los tres macros reconstruyen el objetivo (±redondeo)
    assert abs(obj["proteina_g"] * 4 + obj["carbohidratos_g"] * 4 + obj["grasa_g"] * 9 - obj["kcal_objetivo"]) < 12


@pytest.mark.parametrize("objetivo,factor", [("definicion", 0.8), ("perder", 0.8), ("volumen", 1.1), ("ganar", 1.1), ("mantener", 1.0), ("otro", 1.0)])
def test_ajuste_por_objetivo_y_alias(objetivo, factor):
    obj = nu.calcular_objetivos({"peso_kg": 80, "altura_cm": 180, "edad": 30, "sexo": "hombre",
                                 "nivel_actividad": 1.55, "objetivo": objetivo, "proteina_g_kg": 1.8})
    assert obj["kcal_objetivo"] == round(1780 * 1.55 * factor)


def test_ajuste_y_grasa_configurables():
    obj = nu.calcular_objetivos({"peso_kg": 70, "altura_cm": 170, "edad": 40, "sexo": "mujer", "nivel_actividad": 1.2,
                                 "objetivo": "definicion", "ajuste_pct": -10, "grasa_pct": 30, "proteina_g_kg": 2})
    tdee = (700 + 1062.5 - 200 - 161) * 1.2
    assert obj["kcal_objetivo"] == round(tdee * 0.9)
    assert obj["grasa_g"] == round(tdee * 0.9 * 0.30 / 9)
    assert obj["proteina_g"] == 140


def test_aviso_si_no_quedan_hidratos():
    obj = nu.calcular_objetivos({"peso_kg": 120, "altura_cm": 150, "edad": 70, "sexo": "mujer", "nivel_actividad": 1.2,
                                 "objetivo": "definicion", "grasa_pct": 45, "proteina_g_kg": 3.5})
    assert obj["carbohidratos_g"] == 0 and obj["aviso"]


def test_progreso_y_restante():
    objetivo = {"kcal": 2000, "proteinas": 150, "carbohidratos": 200, "grasas": 60}
    consumido = {"kcal": 1500, "proteinas": 75, "carbohidratos": 220, "grasas": 30}
    assert nu.progreso(consumido, objetivo) == {"kcal": 75, "proteinas": 50, "carbohidratos": 110, "grasas": 50}
    assert nu.restante(consumido, objetivo) == {"kcal": 500, "proteinas": 75, "carbohidratos": -20, "grasas": 30}


def _plato(pid, nombre, d):
    return {"id": pid, "nombre": nombre, "densidad": d, "gramos_min": 100, "gramos_max": 600, "gramos_base": 300}


def test_sugerir_platos_elige_el_que_encaja():
    hueco = {"kcal": 600, "proteinas": 50, "carbohidratos": 50, "grasas": 15}
    proteico = _plato(1, "Pollo con arroz", {"kcal": 150, "proteinas": 12, "carbohidratos": 13, "grasas": 4})
    graso = _plato(2, "Pasta carbonara", {"kcal": 250, "proteinas": 8, "carbohidratos": 25, "grasas": 13})
    res = nu.sugerir_platos(hueco, [graso, proteico], n=2)
    assert res[0]["id"] == 1
    assert res[0]["gramos"] == 400 and res[0]["aporte"]["kcal"] == 600
    assert nu.sugerir_platos({"kcal": 20, "proteinas": 0, "carbohidratos": 0, "grasas": 0}, [proteico]) == []


def test_sugerir_ingredientes_cubre_el_macro_que_falta():
    hueco = {"kcal": 300, "proteinas": 40, "carbohidratos": 5, "grasas": 2}
    ings = [{"id": 1, "nombre": "Pechuga", **POLLO}, {"id": 2, "nombre": "Arroz", **ARROZ}, {"id": 3, "nombre": "Aceite", **ACEITE}]
    res = nu.sugerir_ingredientes(hueco, ings)
    assert res[0]["nombre"] == "Pechuga" and res[0]["macro"] == "proteinas"
    # no supera las kcal restantes
    assert res[0]["aporte"]["kcal"] <= 300 + 10
