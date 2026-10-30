"""Décima ronda: el generador elige por proteína, hidratos y grasa (no solo kcal y proteína) y cierra el día."""
from comidas import main as cm


def _plato(id_, kcal, prot, carb, fat, grupos=(), base=300):
    """Plato de prueba con sus macros por 100 g y una ración base."""
    return {"id": id_, "nombre": f"Plato {id_}", "franja": "comida", "kcal_100g": kcal, "prot_100g": prot,
            "carb_100g": carb, "fat_100g": fat, "gramos_base": base, "gramos_min": base * 0.6, "gramos_max": base * 1.8,
            "groups": list(grupos), "favorito": False}


def _estado():
    return {"used_main": set(), "used_side": set(), "used_side_counts": {}, "group_counts": {},
            "day_group_counts": {}, "recent_usage": {}, "side_days": {}}


def test_con_hueco_de_hidratos_elige_el_plato_magro():
    target = {"kcal": 800, "prot": 50, "carb": 110, "fat": 15}
    graso = _plato(1, 200, 12, 5, 15)     # 67 % de grasa
    magro = _plato(2, 150, 9, 22, 2.5)    # 15 % de grasa, mucho hidrato
    s_graso = cm._score_candidate(graso, target, _estado(), "comida", "lunes", 10)
    s_magro = cm._score_candidate(magro, target, _estado(), "comida", "lunes", 10)
    assert s_magro > s_graso


def test_rota_la_proteina_en_el_mismo_dia():
    target = {"kcal": 700, "prot": 45, "carb": 80, "fat": 20}
    estado = _estado()
    estado["day_group_counts"]["lunes"] = {"carne_blanca": 1}
    pollo = _plato(1, 150, 12, 12, 5, grupos=("carne_blanca",))
    pescado = _plato(2, 150, 12, 12, 5, grupos=("pescado",))
    assert cm._score_candidate(pescado, target, estado, "cena", "lunes", 10) > cm._score_candidate(pollo, target, estado, "cena", "lunes", 10)


def test_desayuno_no_se_repite_en_dias_seguidos():
    target = {"kcal": 500, "prot": 30, "carb": 60, "fat": 15}
    estado = _estado()
    estado["side_days"] = {1: {0}}  # el plato 1 salió el lunes
    a, b = _plato(1, 150, 9, 18, 4), _plato(2, 150, 9, 18, 4)
    a["franja"] = b["franja"] = "desayuno"
    assert cm._score_candidate(b, target, estado, "desayuno", "martes", 10) > cm._score_candidate(a, target, estado, "desayuno", "martes", 10)


def test_ajuste_del_dia_cierra_el_hueco_de_kcal_dentro_de_los_limites():
    p1, p2 = _plato(1, 150, 10, 15, 5), _plato(2, 200, 12, 20, 7)
    elegidos = [["comida", p1, 300], ["cena", p2, 300]]
    cm._ajustar_raciones_dia(elegidos, 300)  # faltan 300 kcal
    extra = sum(e[1]["kcal_100g"] * (e[2] - 300) / 100 for e in elegidos)
    assert abs(extra - 300) < 25
    assert all(e[1]["gramos_min"] <= e[2] <= e[1]["gramos_max"] and e[2] % 5 == 0 for e in elegidos)
    # sin margen (ya en el máximo), no se pasa del rango
    tope = [["comida", p1, p1["gramos_max"]]]
    cm._ajustar_raciones_dia(tope, 500)
    assert tope[0][2] == p1["gramos_max"]
