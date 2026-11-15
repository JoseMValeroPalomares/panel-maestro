"""
comidas/generador.py

Generador semanal y heurística de sugerencia (Python puro, sin numpy/scipy). Sin rutas: las llama `plan.py`
(generar la semana, regenerar una celda) y `planner.py` (plato doble, plantillas).

MODELO DE NUTRICION DE CADA COMIDA (catalogo)
-----------------------------------------------
Cada ingrediente aporta sus macros de forma literal:
    aporte_ingrediente = macro_100g_ingrediente * (gramos_ingrediente / 100)
Sumando esos aportes se obtiene la nutricion TOTAL Y LITERAL de la receta
completa ("nutricion_total_receta" en /api/meals/{id}). Reacciona 1:1 a
cualquier cambio de gramos en cualquier ingrediente.

Cada comida tiene "gramos_recomendados": una racion ESTANDAR de ese
plato ya montado (editable, con sugerencia automatica). Es lo que se ve
en la ficha y en las tarjetas del catalogo. Si "es_racion_unica" esta
activo (batidos, cremas individuales...), la receta completa YA ES la
racion, sin ningun escalado.

RACION PERSONALIZADA POR CELDA DEL PLANIFICADOR
-------------------------------------------------
La racion "estandar" del catalogo es solo el punto de partida. El
generador semanal NO usa un factor de ajuste global inventado: para
cada franja de cada dia calcula cuanto queda REALMENTE del objetivo
diario (kcal y proteina) de tu perfil, elige el plato que mejor encaja
por su perfil de macros, y calcula los gramos EXACTOS de ese plato que
hacen falta para llegar a ese hueco de kcal, dentro de un rango sano
(entre 0.6x y 1.8x su racion de catalogo, con techo de 900g y suelo de
120g para no generar platos absurdos). Esos gramos se guardan en la
propia celda del planificador (weekly_plan.gramos_racion) y son los que
se usan para el resumen nutricional diario - no la racion de catalogo.

Las asignaciones manuales (cuando tu elige la comida a mano) no llevan
gramos_racion propio: usan la racion estandar del catalogo tal cual,
hasta que se regeneran automaticamente.

GENERADOR SEMANAL
------------------
Para cada dia, el generador reparte lo que queda del objetivo diario
entre las franjas pendientes segun su peso relativo, escogiendo en cada
hueco el plato cuya proporcion proteina/kcal mas se parezca a la que
necesitas ahi, y cuidando la diversidad nutricional a lo largo de la
semana: cuotas minimas de pescado/legumbre/verdura (con urgencia
creciente si quedan pocos huecos), cuotas maximas de procesados/carne
roja (en cualquier franja), y tope de repeticion del mismo grupo el
mismo dia.
"""

import random

from fastapi import HTTPException

from .core import (
    DIAS_SEMANA,
    FOOD_GROUP_KEYWORDS,
    SLOT_WEIGHTS_BASE,
    _catalogo_de,
    _sync_franjas,
    calculate_targets,
    franja_en_dia,
)

ROLES = ("primero", "segundo", "guarnicion", "postre", "bebida", "unico")

VERDURA_GRAMOS_MIN = 60

WEEKLY_MIN = {"pescado": 2, "legumbre": 3, "verdura": 10}
WEEKLY_MAX = {"procesada": 3, "carne_roja": 2}
DAILY_MAX = {"procesada": 1, "carne_roja": 1, "pescado": 1}

# Rango de escalado que el GENERADOR puede aplicar a la racion de
# catalogo de un plato para que sus kcal encajen en el hueco de esa
# franja/dia. No es un factor global: se calcula plato a plato, cada
# vez, a partir de tu objetivo real (calculate_targets del perfil).
ESCALADO_MIN_FACTOR = 0.6
ESCALADO_MAX_FACTOR = 1.8
GRAMOS_RACION_MIN_ABS = 120
GRAMOS_RACION_MAX_ABS = 900

MACROS = ("kcal", "prot", "carb", "fat")
# Claves de calculate_targets para cada macro del generador
TARGET_KEYS = {"kcal": "kcal_objetivo", "prot": "proteina_g", "carb": "carbohidratos_g", "fat": "grasa_g"}
PROTEIN_GROUPS = ("pescado", "carne_blanca", "carne_roja", "procesada", "huevo", "legumbre")
PRINCIPALES = ("comida", "cena")


# ─────────────────────────────────────────────
# Catálogo: densidad y rango de ración de cada plato
# ─────────────────────────────────────────────
def _classify_meal_groups(ingredient_rows):
    names = " ".join(r["nombre"].lower() for r in ingredient_rows)
    cats = {r["categoria"] for r in ingredient_rows if "categoria" in r.keys()}
    groups = set()

    for group, keywords in FOOD_GROUP_KEYWORDS.items():
        if any(kw in names for kw in keywords):
            groups.add(group)

    if "legumbre" in cats:
        groups.add("legumbre")
    if "lacteo" in cats:
        groups.add("lacteo")

    verdura_gramos = sum(
        r["gramos"] for r in ingredient_rows if "categoria" in r.keys() and r["categoria"] == "verdura"
    )
    if verdura_gramos >= VERDURA_GRAMOS_MIN:
        groups.add("verdura")

    if not groups & {"pescado", "carne_blanca", "carne_roja", "procesada", "huevo"}:
        groups.add("vegetariano")

    return groups


def _sumar_macros_receta(ing_rows):
    """Suma LITERAL de macros de una lista de filas de meal_ingredients
    ya unidas con ingredients. Reacciona 1:1 a cualquier cambio de
    gramos, sin ningun escalado."""
    total = {"kcal": 0.0, "proteinas": 0.0, "carbohidratos": 0.0, "grasas": 0.0}
    gramos_totales = 0.0
    for ing in ing_rows:
        f = ing["gramos"] / 100
        total["kcal"] += ing["kcal_100g"] * f
        total["proteinas"] += ing["proteinas_100g"] * f
        total["carbohidratos"] += ing["carbohidratos_100g"] * f
        total["grasas"] += ing["grasas_100g"] * f
        gramos_totales += ing["gramos"]
    return total, gramos_totales


def _nutrition_factor(es_racion_unica, gramos_recomendados, gramos_totales):
    if es_racion_unica:
        return 1.0
    if gramos_totales and gramos_totales > 0:
        return (gramos_recomendados or 0) / gramos_totales
    return 0.0


def _rango_racion(gramos_base) -> tuple[float, float]:
    """Rango sano en el que el generador puede escalar la ración de catálogo."""
    gramos_min = (
        max(GRAMOS_RACION_MIN_ABS, gramos_base * ESCALADO_MIN_FACTOR) if gramos_base > 0 else GRAMOS_RACION_MIN_ABS
    )
    gramos_max = (
        min(GRAMOS_RACION_MAX_ABS, gramos_base * ESCALADO_MAX_FACTOR) if gramos_base > 0 else GRAMOS_RACION_MAX_ABS
    )
    return gramos_min, max(gramos_max, gramos_min)


def _plato_del_catalogo(m, ing_rows) -> dict:
    total, gramos_totales = _sumar_macros_receta(ing_rows)
    es_racion_unica = bool(m["es_racion_unica"]) if "es_racion_unica" in m.keys() else False
    gramos_base = gramos_totales if es_racion_unica else (m["gramos_recomendados"] or 0)

    if gramos_totales > 0:
        kcal_100g = total["kcal"] / gramos_totales * 100
        prot_100g = total["proteinas"] / gramos_totales * 100
        carb_100g = total["carbohidratos"] / gramos_totales * 100
        fat_100g = total["grasas"] / gramos_totales * 100
    else:
        kcal_100g = prot_100g = carb_100g = fat_100g = 0.0

    gramos_min, gramos_max = _rango_racion(gramos_base)
    return {
        "id": m["id"],
        "nombre": m["nombre"],
        "franja": m["franja"],
        "kcal_100g": kcal_100g,
        "prot_100g": prot_100g,
        "carb_100g": carb_100g,
        "fat_100g": fat_100g,
        "gramos_base": gramos_base,
        "gramos_min": gramos_min,
        "gramos_max": gramos_max,
        "groups": _classify_meal_groups(ing_rows),
        "favorito": bool(m["favorito"]) if "favorito" in m.keys() else False,
    }


def _build_meal_catalog(conn):
    """Construye, para cada comida, su DENSIDAD por 100g y su racion
    base de catalogo (gramos_base), junto con el rango sano en el que
    el generador puede escalarla (gramos_min/gramos_max). No fija
    ninguna cantidad de kcal: eso se decide por franja/dia en el
    generador, calculando los gramos exactos que hacen falta."""
    catalogo = {}
    for m in conn.execute("SELECT * FROM meals").fetchall():
        ing_rows = conn.execute(
            """
            SELECT i.nombre, i.categoria, i.kcal_100g, i.proteinas_100g, i.carbohidratos_100g, i.grasas_100g, mi.gramos
            FROM meal_ingredients mi JOIN ingredients i ON i.id = mi.ingredient_id
            WHERE mi.meal_id = ?
        """,
            (m["id"],),
        ).fetchall()
        catalogo[m["id"]] = _plato_del_catalogo(m, ing_rows)
    return catalogo


def _gramos_racion_para_objetivo(meal, slot_kcal_target):
    """Gramos EXACTOS de este plato para que sus kcal encajen en el
    hueco pedido, acotados a un rango sano de racion. Devuelve
    (gramos, kcal_resultante, prot_resultante)."""
    if meal["kcal_100g"] <= 0:
        gramos = meal["gramos_base"] or GRAMOS_RACION_MIN_ABS
    else:
        ideal = slot_kcal_target / meal["kcal_100g"] * 100
        gramos = max(meal["gramos_min"], min(meal["gramos_max"], ideal))
    gramos = round(gramos / 5) * 5
    kcal_resultante = meal["kcal_100g"] * gramos / 100
    prot_resultante = meal["prot_100g"] * gramos / 100
    return gramos, kcal_resultante, prot_resultante


# ─────────────────────────────────────────────
# Estado de la semana (lo ya usado, por grupos y días)
# ─────────────────────────────────────────────
def _anotar_en_semana(week_state, meal, franja, dia) -> None:
    """Cuenta un plato (ya planificado o recién elegido) en el estado de la semana."""
    if franja in PRINCIPALES:
        week_state["used_main"].add(meal["id"])
    else:
        week_state["used_side"].add(meal["id"])
        week_state["used_side_counts"][meal["id"]] = week_state["used_side_counts"].get(meal["id"], 0) + 1
        if dia in DIAS_SEMANA:
            week_state["side_days"].setdefault(meal["id"], set()).add(DIAS_SEMANA.index(dia))

    for g in meal["groups"]:
        week_state["group_counts"][g] = week_state["group_counts"].get(g, 0) + 1

    day_groups = week_state["day_group_counts"].setdefault(dia, {})
    for g in meal["groups"]:
        day_groups[g] = day_groups.get(g, 0) + 1


def _build_week_state(conn, semana, catalogo, exclude_plan_id=None):
    week_state = {
        "used_main": set(),
        "used_side": set(),
        "used_side_counts": {},
        "group_counts": {},
        "day_group_counts": {},
        "recent_usage": {},
        "side_days": {},  # desayunos/meriendas: en qué días (índice) salen
    }
    for r in conn.execute("SELECT * FROM weekly_plan WHERE semana=?", (semana,)).fetchall():
        if exclude_plan_id and r["id"] == exclude_plan_id:
            continue
        if not r["meal_id"]:
            continue
        m = catalogo.get(r["meal_id"])
        if not m:
            continue
        _anotar_en_semana(week_state, m, r["franja"], r["dia"])

    for r in conn.execute(
        """
        SELECT meal_id, COUNT(*) as c FROM meal_usage_log
        WHERE semana >= date(?, '-42 days') GROUP BY meal_id
    """,
        (semana,),
    ).fetchall():
        week_state["recent_usage"][r["meal_id"]] = r["c"]
    return week_state


# ─────────────────────────────────────────────
# Puntuación de un candidato
# ─────────────────────────────────────────────
def _macros_de(meal, gramos) -> dict:
    return {
        "kcal": meal["kcal_100g"] * gramos / 100,
        "prot": meal["prot_100g"] * gramos / 100,
        "carb": meal["carb_100g"] * gramos / 100,
        "fat": meal["fat_100g"] * gramos / 100,
    }


def _compute_slot_targets(restante_dia: dict, peso_restante, franja) -> dict:
    """Lo que le toca a esta franja de lo que queda del día (kcal, proteína, hidratos y grasa)."""
    peso_slot = SLOT_WEIGHTS_BASE.get(franja, 0.25)
    cuota = (peso_slot / peso_restante) if peso_restante > 0 else 1.0
    return {k: max(restante_dia[k], 0) * cuota for k in MACROS}


def _macro_error(meal, target) -> float:
    """Cuánto se desvía el plato del hueco, en proporción a sus kcal, con la ración ya ajustada a esas
    kcal: así compiten platos de tamaños distintos. Quedarse corto de proteína y pasarse de grasa pesan
    más que lo contrario (son los dos errores que más se notan en la semana)."""
    gramos, _, _ = _gramos_racion_para_objetivo(meal, target["kcal"])
    m = _macros_de(meal, gramos)
    dp, dc, df = m["prot"] - target["prot"], m["carb"] - target["carb"], m["fat"] - target["fat"]
    err = (
        abs(m["kcal"] - target["kcal"])
        + abs(dp) * 4 * (2.4 if dp < 0 else 0.6)
        + abs(dc) * 4 * (1.0 if dc < 0 else 0.7)
        + abs(df) * 9 * (1.4 if df > 0 else 0.4)
    )
    return err / max(target["kcal"], 100)


def _ajustar_raciones_dia(elegidos: list, hueco_kcal: float) -> None:
    """Cierra el hueco de kcal del día repartiéndolo entre las raciones generadas (no las fijas),
    cada una dentro de su rango sano y en pasos de 5 g. `elegidos` = [[franja, plato, gramos], …]."""
    for _ in range(3):
        if abs(hueco_kcal) < 25:
            return
        movibles = [
            e
            for e in elegidos
            if e[1]["kcal_100g"] > 0 and (e[2] < e[1]["gramos_max"] if hueco_kcal > 0 else e[2] > e[1]["gramos_min"])
        ]
        if not movibles:
            return
        total = sum(e[1]["kcal_100g"] * e[2] / 100 for e in movibles) or 1
        for e in movibles:
            kcal = e[1]["kcal_100g"] * e[2] / 100
            nuevo = e[2] + hueco_kcal * (kcal / total) / e[1]["kcal_100g"] * 100
            nuevo = round(max(e[1]["gramos_min"], min(e[1]["gramos_max"], nuevo)) / 5) * 5
            hueco_kcal -= e[1]["kcal_100g"] * (nuevo - e[2]) / 100
            e[2] = nuevo


def _puntos_por_grupos(score, meal, week_state, franja, dia, main_slots_remaining) -> float:
    """Cuotas semanales (mínimos y máximos) y tope diario de cada grupo de alimentos. Suma en el
    mismo orden que antes (coma flotante: otro orden cambiaría empates y, con ellos, el sorteo)."""
    for g in meal["groups"]:
        if g in WEEKLY_MAX and week_state["group_counts"].get(g, 0) >= WEEKLY_MAX[g]:
            score -= 5.0

    if franja in PRINCIPALES:
        for g in meal["groups"]:
            if g in WEEKLY_MIN:
                faltan = WEEKLY_MIN[g] - week_state["group_counts"].get(g, 0)
                if faltan > 0:
                    urgencia = min(faltan / max(main_slots_remaining, 1), 1.0)
                    score += urgencia * 6.0

    day_groups = week_state["day_group_counts"].get(dia, {})
    for g in meal["groups"]:
        if g in DAILY_MAX and day_groups.get(g, 0) >= DAILY_MAX[g]:
            score -= 4.0
    return score


def _puntos_por_variedad(score, meal, week_state, franja, dia) -> float:
    """Que no se repita: desayunos y meriendas en días seguidos, la misma proteína el mismo día, entre semanas."""
    day_groups = week_state["day_group_counts"].get(dia, {})
    if franja not in PRINCIPALES:
        score -= week_state["used_side_counts"].get(meal["id"], 0) * 1.2
        # variedad: el mismo desayuno o merienda, no en días seguidos
        cerca = week_state.get("side_days", {}).get(meal["id"], set())
        di = DIAS_SEMANA.index(dia) if dia in DIAS_SEMANA else 0
        if any(abs(di - x) <= 1 for x in cerca):
            score -= 2.0
    else:
        # rotar la fuente de proteína: no la misma en la comida y la cena de un día
        for g in meal["groups"]:
            if g in PROTEIN_GROUPS and day_groups.get(g, 0) >= 1:
                score -= 1.5

    if meal.get("favorito"):
        score += 0.8
    score -= week_state["recent_usage"].get(meal["id"], 0) * 0.8  # rotar entre semanas (últimos 42 días)
    return score


def _score_candidate(meal, target, week_state, franja, dia, main_slots_remaining):
    # Lo que más cuenta: que el plato, con su ración ajustada a las kcal del hueco, cuadre en
    # proteína, hidratos y grasa con lo que le queda al día (ver _macro_error)
    slot_kcal_target = target["kcal"]
    score = -_macro_error(meal, target) * 4.0

    # Factibilidad: si el hueco de kcal cae fuera del rango de racion
    # sana de este plato, se podra escalar pero forzando un limite -
    # penalizacion suave para preferir platos que encajen sin forzar.
    if meal["kcal_100g"] > 0:
        gramos_ideal = slot_kcal_target / meal["kcal_100g"] * 100
        if gramos_ideal < meal["gramos_min"] or gramos_ideal > meal["gramos_max"]:
            score -= 1.5

    score += min(meal["prot_100g"] * meal["gramos_base"] / 100, 40) / 40.0 * 0.4
    score = _puntos_por_grupos(score, meal, week_state, franja, dia, main_slots_remaining)
    return _puntos_por_variedad(score, meal, week_state, franja, dia)


def _candidatos(catalogo, franja, week_state, excluir=None) -> list:
    """Platos del catálogo de esa franja; si hay alguno sin usar esta semana, solo esos."""
    candidates = [m for m in catalogo.values() if m["franja"] == _catalogo_de(franja) and m["id"] != excluir]
    usados = week_state["used_main"] if franja in PRINCIPALES else week_state["used_side"]
    filtered = [m for m in candidates if m["id"] not in usados]
    return filtered or candidates


def _objetivos(conn) -> dict:
    """Refresca las franjas y devuelve los objetivos diarios del perfil."""
    _sync_franjas(conn)
    profile_row = conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone()
    return calculate_targets(dict(profile_row))


def _racion(meal, gramos_racion):
    """Gramos de una celda: los suyos o, si no tiene, la ración de catálogo."""
    return gramos_racion if gramos_racion is not None else meal["gramos_base"]


# ─────────────────────────────────────────────
# Generar la semana
# ─────────────────────────────────────────────
def _fijas_y_extras(conn, semana) -> tuple[dict, dict]:
    """Celdas fijas por día y franja, y platos adicionales ya planificados por día."""
    fixed_by_day: dict[str, dict] = {}
    for r in conn.execute(
        "SELECT dia, franja, meal_id, gramos_racion FROM weekly_plan WHERE semana=? AND is_fixed=1",
        (semana,),
    ).fetchall():
        fixed_by_day.setdefault(r["dia"], {})[r["franja"]] = r
    # Platos adicionales ya planificados (ensalada, postre...): se respetan y suman al día
    extras_by_day: dict[str, list] = {}
    for r in conn.execute(
        """SELECT wp.dia, pi.meal_id, pi.gramos_racion FROM plan_items pi
                                 JOIN weekly_plan wp ON wp.id = pi.plan_id WHERE wp.semana=?""",
        (semana,),
    ):
        extras_by_day.setdefault(r["dia"], []).append(r)
    return fixed_by_day, extras_by_day


def _huecos_principales(franjas, fixed_by_day) -> int:
    """Comidas y cenas que quedan por llenar en la semana (mínimo 1)."""
    return (
        sum(
            1
            for dia in DIAS_SEMANA
            for franja in franjas
            if franja in PRINCIPALES and franja not in fixed_by_day.get(dia, {}) and franja_en_dia(franja, dia)
        )
        or 1
    )


def _lo_ya_puesto(catalogo, dia, franjas, dia_fixed, extras) -> tuple[dict, list]:
    """Lo que ya suma el día (extras y fijas) y las franjas que quedan por elegir."""
    llevado = dict.fromkeys(MACROS, 0.0)
    for ex in extras:
        em = catalogo.get(ex["meal_id"])
        if em:
            for k, v in _macros_de(em, _racion(em, ex["gramos_racion"])).items():
                llevado[k] += v
    pendientes = []
    for franja in franjas:
        if not franja_en_dia(franja, dia):  # desactivada ese día: ni se genera ni cuenta
            continue
        if franja in dia_fixed:
            fm = catalogo.get(dia_fixed[franja]["meal_id"])
            if fm:
                for k, v in _macros_de(fm, _racion(fm, dia_fixed[franja]["gramos_racion"])).items():
                    llevado[k] += v
        else:
            pendientes.append(franja)
    return llevado, pendientes


def _elegir(candidates, target, week_state, franja, dia, main_slots_remaining):
    """Uno de los tres mejores, con más probabilidad cuanto mejor puntúa."""
    scored = sorted(
        candidates,
        key=lambda m: _score_candidate(m, target, week_state, franja, dia, main_slots_remaining),
        reverse=True,
    )
    top = scored[: min(3, len(scored))]
    weights = [max(0.05, 1.0 - 0.3 * i) for i in range(len(top))]
    return random.choices(top, weights=weights, k=1)[0]


def _generar_dia(catalogo, week_state, objetivo, dia, llevado, pendientes, main_slots_remaining):
    """Elige plato y ración para cada franja pendiente del día. Devuelve ([[franja, plato, gramos], …], huecos)."""
    elegidos: list = []
    peso_restante = sum(SLOT_WEIGHTS_BASE.get(f, 0.25) for f in pendientes) or 1.0
    for franja in pendientes:
        target = _compute_slot_targets({k: objetivo[k] - llevado[k] for k in MACROS}, peso_restante, franja)
        candidates = _candidatos(catalogo, franja, week_state)
        if candidates:
            chosen = _elegir(candidates, target, week_state, franja, dia, main_slots_remaining)
            gramos_racion, _, _ = _gramos_racion_para_objetivo(chosen, target["kcal"])
            elegidos.append([franja, chosen, gramos_racion])
            _anotar_en_semana(week_state, chosen, franja, dia)
            week_state["recent_usage"][chosen["id"]] = week_state["recent_usage"].get(chosen["id"], 0) + 1
            for k, v in _macros_de(chosen, gramos_racion).items():
                llevado[k] += v
        if franja in PRINCIPALES:
            main_slots_remaining = max(main_slots_remaining - 1, 1)
        peso_restante = max(peso_restante - SLOT_WEIGHTS_BASE.get(franja, 0.25), 0.0001)
    return elegidos, main_slots_remaining


def _guardar_dia(conn, semana, dia, elegidos) -> None:
    for franja, chosen, gramos_racion in elegidos:
        conn.execute(
            """
            INSERT INTO weekly_plan (semana, dia, franja, meal_id, is_fixed, gramos_racion)
            VALUES (?, ?, ?, ?, 0, ?)
            ON CONFLICT(semana, dia, franja) DO UPDATE SET meal_id=excluded.meal_id, gramos_racion=excluded.gramos_racion
        """,
            (semana, dia, franja, chosen["id"], gramos_racion),
        )
        conn.execute("INSERT INTO meal_usage_log (meal_id, semana) VALUES (?, ?)", (chosen["id"], semana))


def generar_semana(conn, semana: str, franjas: list[str]) -> None:
    """Rellena las celdas no fijas de la semana, día a día, y cierra el hueco de kcal de cada día."""
    targets = _objetivos(conn)
    catalogo = _build_meal_catalog(conn)
    if not any(catalogo.values()):
        raise HTTPException(
            status_code=422,
            detail="Aún no tienes platos: añade unos cuantos en «Platos» y vuelve a generar la semana.",
        )
    week_state = _build_week_state(conn, semana, catalogo)
    fixed_by_day, extras_by_day = _fijas_y_extras(conn, semana)
    main_slots_remaining = _huecos_principales(franjas, fixed_by_day)
    objetivo = {k: targets[TARGET_KEYS[k]] for k in MACROS}
    for dia in DIAS_SEMANA:
        llevado, pendientes = _lo_ya_puesto(
            catalogo, dia, franjas, fixed_by_day.get(dia, {}), extras_by_day.get(dia, [])
        )
        elegidos, main_slots_remaining = _generar_dia(
            catalogo, week_state, objetivo, dia, llevado, pendientes, main_slots_remaining
        )
        _ajustar_raciones_dia(elegidos, objetivo["kcal"] - llevado["kcal"])
        _guardar_dia(conn, semana, dia, elegidos)


# ─────────────────────────────────────────────
# Regenerar una celda
# ─────────────────────────────────────────────
def _hueco_de_la_celda(conn, row, catalogo, targets) -> dict:
    """Lo que le toca a esta celda de lo que dejan libre las demás franjas del día."""
    plan_id, franja = row["id"], row["franja"]
    all_day_rows = conn.execute(
        "SELECT * FROM weekly_plan WHERE semana=? AND dia=?", (row["semana"], row["dia"])
    ).fetchall()
    peso_total_dia = sum(SLOT_WEIGHTS_BASE.get(r["franja"], 0.25) for r in all_day_rows)
    otros = dict.fromkeys(MACROS, 0.0)
    peso_otros_llenos = 0.0
    for r in all_day_rows:
        if r["id"] == plan_id:
            continue
        if r["meal_id"]:
            m = catalogo.get(r["meal_id"])
            if m:
                for k, v in _macros_de(m, _racion(m, r["gramos_racion"])).items():
                    otros[k] += v
            peso_otros_llenos += SLOT_WEIGHTS_BASE.get(r["franja"], 0.25)

    peso_restante = max(peso_total_dia - peso_otros_llenos, SLOT_WEIGHTS_BASE.get(franja, 0.25))
    return _compute_slot_targets({k: targets[TARGET_KEYS[k]] - otros[k] for k in MACROS}, peso_restante, franja)


def regenerar_celda(conn, row):
    """El mejor plato distinto del actual para esta celda y su ración. (None, None) si no hay alternativas."""
    plan_id, semana, dia, franja = row["id"], row["semana"], row["dia"], row["franja"]
    targets = _objetivos(conn)
    catalogo = _build_meal_catalog(conn)
    week_state = _build_week_state(conn, semana, catalogo, exclude_plan_id=plan_id)
    target = _hueco_de_la_celda(conn, row, catalogo, targets)

    main_slots_remaining = (
        conn.execute(
            """
        SELECT COUNT(*) as c FROM weekly_plan
        WHERE semana=? AND franja IN ('comida','cena') AND (meal_id IS NULL OR id=?)
    """,
            (semana, plan_id),
        ).fetchone()["c"]
        or 1
    )

    candidates = _candidatos(catalogo, franja, week_state, excluir=row["meal_id"])
    if not candidates:
        return None, None
    best = max(candidates, key=lambda m: _score_candidate(m, target, week_state, franja, dia, main_slots_remaining))
    gramos_racion, _, _ = _gramos_racion_para_objetivo(best, target["kcal"])
    return best, gramos_racion
