"""comidas/plan.py — planificador semanal: celdas, platos adicionales, plan completo con progreso, generar y
regenerar (la heurística está en `generador.py`) y sugerencias para lo que queda del día."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from . import generador as gen
from . import nutrition as nu
from .core import (
    DIAS_SEMANA,
    FRANJA_FRACCION,
    FRANJA_ORDEN,
    GenerateWeekRequest,
    GramosUpdate,
    PlanItemAdd,
    PlanSlotAdd,
    Semana,
    WeeklyPlanAssign,
    _catalogo_de,
    _check_dia_franja,
    _recipe_index,
    _slot_id,
    _sync_franjas,
    calculate_targets,
    franja_en_dia,
)
from .database import get_db

router = APIRouter()


# ─────────────────────────────────────────────
# Plan completo: platos → comida → día → semana (con progreso y objetivos)
# ─────────────────────────────────────────────
def _rol(row):
    try:
        return row["rol"]
    except (IndexError, KeyError):
        return None


def _plato(index: dict, meal_id: int, gramos_custom, kind: str, plan_id: int, item_id=None, rol=None) -> dict | None:
    m = index.get(meal_id)
    if not m:
        return None
    gramos = gramos_custom if gramos_custom is not None else m["gramos_base"]
    macros = nu.racion(m["total"], m["gramos_receta"], gramos)
    return {
        "kind": kind,
        "plan_id": plan_id,
        "item_id": item_id,
        "meal_id": meal_id,
        "nombre": m["nombre"],
        "rol": rol,
        "image_url": m["image_url"],
        "gramos": round(gramos or 0),
        "gramos_estandar": round(m["gramos_base"] or 0),
        "personalizado": gramos_custom is not None,
        "macros": nu.redondear(macros),
        "_raw": macros,
    }


def _consejo_macros(index: dict, media: dict, objetivo: dict, targets: dict) -> str | None:
    """Si la semana se pasa claramente de grasa (o se queda corta de hidratos) y la causa es el
    catálogo, lo dice y sugiere los platos de comida y cena que más ayudan."""
    if not objetivo.get("grasas") or not media.get("kcal"):
        return None
    exceso = media["grasas"] / objetivo["grasas"]
    if exceso < 1.25:
        return None
    platos = [m for m in index.values() if m["franja"] in ("comida", "cena") and m["total"].get("kcal")]
    if not platos:
        return None
    pct = lambda m: m["total"]["grasas"] * 9 / m["total"]["kcal"] * 100  # noqa: E731
    media_pct = sum(pct(m) for m in platos) / len(platos)
    magros = sorted(platos, key=pct)[:3]
    return (
        f"La grasa va a {round(media['grasas'])} g/día y tu objetivo es {round(objetivo['grasas'])} g "
        f"({round(targets.get('grasa_pct', 0))} % de las kcal), pero tus comidas y cenas tienen de media un "
        f"{round(media_pct)} % de sus kcal en grasa: el generador ya elige las más magras. Para acercarte, añade platos con menos "
        f"aceite, queso o fritos, o sube el % de grasa en tu perfil. Las más magras que tienes: "
        + ", ".join(m["nombre"] for m in magros)
        + "."
    )


def _extras_por_plan(conn, semana: str) -> dict:
    extras: dict = {}
    for it in conn.execute(
        """
        SELECT pi.* FROM plan_items pi JOIN weekly_plan wp ON wp.id = pi.plan_id
        WHERE wp.semana = ? ORDER BY pi.orden, pi.id
    """,
        (semana,),
    ):
        extras.setdefault(it["plan_id"], []).append(it)
    return extras


def _comidas_por_dia(index: dict, slots, extras: dict) -> dict:
    """Cada día con sus comidas (plato principal y adicionales) y lo que suman."""
    dias = {d: {"comidas": {}, "_total": nu.sumar()} for d in DIAS_SEMANA}
    for s in slots:
        if s["dia"] not in dias:
            continue
        platos = []
        if s["meal_id"]:
            p = _plato(index, s["meal_id"], s["gramos_racion"], "principal", s["id"], rol=_rol(s))
            if p:
                platos.append(p)
        for it in extras.get(s["id"], []):
            p = _plato(index, it["meal_id"], it["gramos_racion"], "extra", s["id"], it["id"], rol=_rol(it))
            if p:
                platos.append(p)
        total = nu.sumar(*[p.pop("_raw") for p in platos])
        dias[s["dia"]]["comidas"][s["franja"]] = {
            "plan_id": s["id"],
            "franja": s["franja"],
            "is_fixed": bool(s["is_fixed"]),
            "platos": platos,
            "total": nu.redondear(total),
        }
        dias[s["dia"]]["_total"] = nu.sumar(dias[s["dia"]]["_total"], total)
    return dias


def _resumen_dias(dias: dict, objetivo: dict) -> tuple[dict, dict]:
    """Comidas en el orden de las franjas, total, progreso y lo que falta de cada día; y el total de la semana."""
    semana_total = nu.sumar()
    out_dias = {}
    for d, info in dias.items():
        total = info["_total"]
        semana_total = nu.sumar(semana_total, total)
        ordenadas = dict(
            sorted(info["comidas"].items(), key=lambda kv: FRANJA_ORDEN.index(kv[0]) if kv[0] in FRANJA_ORDEN else 9)
        )
        out_dias[d] = {
            "comidas": ordenadas,
            "total": nu.redondear(total),
            "progreso": nu.progreso(total, objetivo),
            "restante": nu.restante(total, objetivo),
        }
    return out_dias, semana_total


def _plan_state(conn, semana: str) -> dict:
    franjas = _sync_franjas(conn)
    index = _recipe_index(conn)
    profile = dict(conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone())
    targets = calculate_targets(profile)
    objetivo = nu.objetivos_comparables(targets)
    slots = conn.execute("SELECT * FROM weekly_plan WHERE semana=?", (semana,)).fetchall()
    dias = _comidas_por_dia(index, slots, _extras_por_plan(conn, semana))
    out_dias, semana_total = _resumen_dias(dias, objetivo)
    objetivo_semana = {k: v * 7 for k, v in objetivo.items()}
    dias_con_comida = sum(1 for d in out_dias.values() if d["total"]["kcal"] > 0)
    return {
        "semana": semana,
        "targets": targets,
        "objetivo_dia": objetivo,
        "dias": out_dias,
        "semana_total": nu.redondear(semana_total),
        "objetivo_semana": objetivo_semana,
        "semana_progreso": nu.progreso(semana_total, objetivo_semana),
        "media_diaria": nu.redondear(nu.escalar(semana_total, 1 / dias_con_comida))
        if dias_con_comida
        else nu.redondear(nu.sumar()),
        "dias_planificados": dias_con_comida,
        "consejo": _consejo_macros(index, nu.escalar(semana_total, 1 / dias_con_comida), objetivo, targets)
        if dias_con_comida >= 3
        else None,
        "franjas": [
            {
                k: f[k]
                for k in ("clave", "nombre", "orden", "fraccion", "hora", "activa", "base", "catalogo", "dias")
                if k in f
            }
            for f in franjas
        ],
    }


# ─────────────────────────────────────────────
# Rutas (el orden es el de emparejado: no reordenar)
# ─────────────────────────────────────────────
@router.get("/api/weekly-plan/{semana}")
def get_weekly_plan(semana: Semana):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT wp.id, wp.dia, wp.franja, wp.is_fixed, wp.gramos_racion,
                   m.id as meal_id, m.nombre, m.image_url, m.gramos_recomendados
            FROM weekly_plan wp LEFT JOIN meals m ON m.id = wp.meal_id
            WHERE wp.semana = ?
        """,
            (semana,),
        ).fetchall()
    plan = []
    for r in rows:
        row = dict(r)
        row["gramos_mostrados"] = (
            row["gramos_racion"] if row["gramos_racion"] is not None else row["gramos_recomendados"]
        )
        plan.append(row)
    return {"plan": plan}


@router.get("/api/weekly-plan/{semana}/nutricion")
def get_weekly_plan_nutrition(semana: Semana):
    """Totales por día (todos los platos de cada comida) + objetivos del perfil."""
    with get_db() as conn:
        state = _plan_state(conn, semana)
    dias = {
        d: {k: info["total"][k] for k in ("kcal", "proteinas", "carbohidratos", "grasas", "azucares", "sal")}
        for d, info in state["dias"].items()
    }
    return {
        "semana": semana,
        "dias": dias,
        "targets": state["targets"],
        "semana_total": state["semana_total"],
        "semana_progreso": state["semana_progreso"],
    }


@router.delete("/api/weekly-plan/{semana}/clear")
def clear_week(semana: Semana):
    with get_db() as conn:
        conn.execute(
            "DELETE FROM plan_items WHERE plan_id IN (SELECT id FROM weekly_plan WHERE semana=? AND is_fixed=0)",
            (semana,),
        )
        conn.execute(
            "UPDATE weekly_plan SET meal_id=NULL, gramos_racion=NULL, rol=NULL WHERE semana=? AND is_fixed=0", (semana,)
        )
    return {"status": "success"}


@router.post("/api/weekly-plan/assign")
def assign_weekly_plan(payload: WeeklyPlanAssign):
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM meals WHERE id=?", (payload.meal_id,)).fetchone():
            raise HTTPException(status_code=422, detail="Ese plato no existe")
        # Asignacion manual: se usa la racion estandar de catalogo (sin
        # racion personalizada), hasta que el generador la recalcule.
        conn.execute(
            """
            INSERT INTO weekly_plan (semana, dia, franja, meal_id, is_fixed, gramos_racion)
            VALUES (?, ?, ?, ?, ?, NULL)
            ON CONFLICT(semana, dia, franja) DO UPDATE SET meal_id=excluded.meal_id, is_fixed=excluded.is_fixed, gramos_racion=NULL
        """,
            (payload.semana, payload.dia, payload.franja, payload.meal_id, int(payload.is_fixed)),
        )
        conn.execute("INSERT INTO meal_usage_log (meal_id, semana) VALUES (?, ?)", (payload.meal_id, payload.semana))
        conn.commit()
    return {"status": "success"}


@router.patch("/api/weekly-plan/{plan_id}/toggle-fixed")
def toggle_fixed(plan_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT is_fixed FROM weekly_plan WHERE id=?", (plan_id,)).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": "No encontrado"})
        new_val = 0 if row["is_fixed"] else 1
        conn.execute("UPDATE weekly_plan SET is_fixed=? WHERE id=?", (new_val, plan_id))
        conn.commit()
    return {"status": "success", "is_fixed": bool(new_val)}


@router.delete("/api/weekly-plan/{plan_id}")
def clear_weekly_plan_cell(plan_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM plan_items WHERE plan_id=?", (plan_id,))
        conn.execute(
            "UPDATE weekly_plan SET meal_id=NULL, is_fixed=0, gramos_racion=NULL, rol=NULL WHERE id=?", (plan_id,)
        )
    return {"status": "success"}


@router.post("/api/weekly-plan/generate")
def generate_weekly_plan(payload: GenerateWeekRequest):
    with get_db() as conn:
        gen.generar_semana(conn, payload.semana, payload.franjas)
        conn.commit()
    return {"status": "success"}


@router.post("/api/weekly-plan/{plan_id}/regenerate")
def regenerate_cell(plan_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM weekly_plan WHERE id=?", (plan_id,)).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": "Celda no encontrada"})
        best, gramos_racion = gen.regenerar_celda(conn, row)
        if best is None:
            return JSONResponse(status_code=404, content={"error": "No hay alternativas para esta franja"})
        conn.execute(
            "UPDATE weekly_plan SET meal_id=?, gramos_racion=? WHERE id=?", (best["id"], gramos_racion, plan_id)
        )
        conn.execute("INSERT INTO meal_usage_log (meal_id, semana) VALUES (?, ?)", (best["id"], row["semana"]))
        conn.commit()
    return {"status": "success", "meal_id": best["id"], "nombre": best["nombre"], "gramos_racion": gramos_racion}


@router.get("/api/weekly-plan/{semana}/full")
def get_weekly_plan_full(semana: Semana):
    with get_db() as conn:
        return _plan_state(conn, semana)


@router.post("/api/weekly-plan/slots")
def add_plato_to_slot(payload: PlanSlotAdd):
    """Añade un plato a una comida: si no tiene plato principal pasa a serlo; si
    ya lo tiene, se añade como plato adicional."""
    _check_dia_franja(payload.dia, payload.franja)
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM meals WHERE id=?", (payload.meal_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Plato no encontrado")
        plan_id = _slot_id(conn, payload.semana, payload.dia, payload.franja)
        row = conn.execute("SELECT meal_id FROM weekly_plan WHERE id=?", (plan_id,)).fetchone()
        if row["meal_id"] is None:
            conn.execute(
                "UPDATE weekly_plan SET meal_id=?, gramos_racion=?, rol=? WHERE id=?",
                (payload.meal_id, payload.gramos, payload.rol, plan_id),
            )
            kind, item_id = "principal", None
        else:
            orden = conn.execute(
                "SELECT COALESCE(MAX(orden), 0) + 1 AS o FROM plan_items WHERE plan_id=?", (plan_id,)
            ).fetchone()["o"]
            item_id = conn.execute(
                "INSERT INTO plan_items (plan_id, meal_id, gramos_racion, orden, rol) VALUES (?, ?, ?, ?, ?)",
                (plan_id, payload.meal_id, payload.gramos, orden, payload.rol),
            ).lastrowid
            kind = "extra"
        conn.execute("INSERT INTO meal_usage_log (meal_id, semana) VALUES (?, ?)", (payload.meal_id, payload.semana))
    return {"status": "success", "plan_id": plan_id, "kind": kind, "item_id": item_id}


@router.post("/api/weekly-plan/{plan_id}/items")
def add_plan_item(plan_id: int, payload: PlanItemAdd):
    with get_db() as conn:
        slot = conn.execute("SELECT * FROM weekly_plan WHERE id=?", (plan_id,)).fetchone()
        if not slot:
            raise HTTPException(status_code=404, detail="Comida no encontrada")
    return add_plato_to_slot(
        PlanSlotAdd(
            semana=slot["semana"],
            dia=slot["dia"],
            franja=slot["franja"],
            meal_id=payload.meal_id,
            gramos=payload.gramos,
            rol=payload.rol,
        )
    )


@router.patch("/api/weekly-plan/{plan_id}/gramos")
def set_principal_gramos(plan_id: int, payload: GramosUpdate):
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM weekly_plan WHERE id=?", (plan_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Comida no encontrada")
        conn.execute("UPDATE weekly_plan SET gramos_racion=? WHERE id=?", (payload.gramos, plan_id))
    return {"status": "success"}


@router.patch("/api/weekly-plan/items/{item_id}")
def set_item_gramos(item_id: int, payload: GramosUpdate):
    with get_db() as conn:
        cur = conn.execute("UPDATE plan_items SET gramos_racion=? WHERE id=?", (payload.gramos, item_id))
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="Plato no encontrado")
    return {"status": "success"}


@router.delete("/api/weekly-plan/items/{item_id}")
def delete_plan_item(item_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM plan_items WHERE id=?", (item_id,))
    return {"status": "success"}


def _fraccion_de_la_comida(franja: str, dia: str, dia_state: dict) -> float:
    """Parte de lo que queda del día que le toca a esta comida, entre las que aún están vacías."""
    if not franja:
        return 1.0
    vacias = [f for f in FRANJA_ORDEN if franja_en_dia(f, dia) and not dia_state["comidas"].get(f, {}).get("platos")]
    if franja not in vacias:
        vacias.append(franja)
    peso = sum(FRANJA_FRACCION.get(f, 0) for f in vacias) or 1
    return FRANJA_FRACCION.get(franja, 0.25) / peso if FRANJA_FRACCION.get(franja) else 0.15


def _platos_sugeribles(index: dict, franja: str) -> list[dict]:
    platos = []
    for m in index.values():
        if franja and m["franja"] != _catalogo_de(franja):
            continue
        if not m["gramos_receta"]:
            continue
        base = m["gramos_base"] or m["gramos_receta"]
        platos.append(
            {
                "id": m["id"],
                "nombre": m["nombre"],
                "franja": m["franja"],
                "densidad": nu.densidad_100g(m["total"], m["gramos_receta"]),
                "gramos_base": base,
                "gramos_min": max(gen.GRAMOS_RACION_MIN_ABS, base * gen.ESCALADO_MIN_FACTOR),
                "gramos_max": min(
                    gen.GRAMOS_RACION_MAX_ABS, max(base * gen.ESCALADO_MAX_FACTOR, gen.GRAMOS_RACION_MIN_ABS)
                ),
            }
        )
    return platos


@router.get("/api/weekly-plan/{semana}/sugerencias")
def get_suggestions(semana: Semana, dia: str, franja: str = "", n: int = 5):
    """Platos e ingredientes de tu base de datos que mejor encajan con lo que
    queda del día. Con `franja`, el hueco se reparte según el peso de esa comida
    entre las que aún están vacías."""
    if dia not in DIAS_SEMANA:
        raise HTTPException(status_code=422, detail="Día no válido")
    n = max(1, min(n, 20))
    with get_db() as conn:
        state = _plan_state(conn, semana)
        index = _recipe_index(conn)
        ingredientes = [dict(r) for r in conn.execute("SELECT * FROM ingredients")]
    dia_state = state["dias"][dia]
    hueco = dia_state["restante"]
    fraccion = _fraccion_de_la_comida(franja, dia, dia_state)
    platos = _platos_sugeribles(index, franja)
    hueco_comida = {k: v * fraccion for k, v in hueco.items()}
    return {
        "dia": dia,
        "franja": franja or None,
        "restante_dia": hueco,
        "hueco": {k: round(v, 1) for k, v in hueco_comida.items()},
        "platos": nu.sugerir_platos(hueco, platos, n=n, fraccion_dia=fraccion),
        "ingredientes": nu.sugerir_ingredientes(hueco_comida, ingredientes, n=n),
    }
