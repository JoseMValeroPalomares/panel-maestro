"""
comidas/core.py

Utilidades comunes de Comidas, sin rutas: modelos de entrada, franjas (la tabla `franjas` y las constantes que
refresca), índice de recetas e ingredientes de un plato. Lo usan los routers (`ingredientes`, `platos`, `compra`,
`plan`, `perfil`), el generador y `bulk.py`/`planner.py`; nada de aquí importa de un router ni de `comidas.main`.
"""

import json
import sqlite3
from typing import Annotated

from fastapi import HTTPException
from fastapi import Path as FPath
from pydantic import BaseModel, Field

from . import nutrition as nu
from .database import get_db

DIAS_SEMANA = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]

# ─────────────────────────────────────────────
# Modelos
# ─────────────────────────────────────────────
SEMANA_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
Semana = Annotated[str, FPath(pattern=SEMANA_PATTERN)]


class IngredientIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    categoria: str = Field(default="General", max_length=60)
    kcal_100g: float = Field(default=0, ge=0, le=900)
    proteinas_100g: float = Field(default=0, ge=0, le=100)
    carbohidratos_100g: float = Field(default=0, ge=0, le=100)
    grasas_100g: float = Field(default=0, ge=0, le=100)
    grasas_saturadas_100g: float = Field(default=0, ge=0, le=100)
    grasas_trans_100g: float = Field(default=0, ge=0, le=100)
    azucares_100g: float = Field(default=0, ge=0, le=100)
    sal_100g: float = Field(default=0, ge=0, le=100)
    gramos_por_unidad: float | None = Field(default=None, gt=0, le=5000)
    unidad_nombre: str | None = Field(default=None, max_length=40)


class MealIngredientIn(BaseModel):
    ingredient_id: int = Field(ge=1)
    gramos: float | None = Field(default=None, gt=0, le=10_000)
    unidades: float | None = Field(default=None, gt=0, le=1000)  # alternativa a gramos si el ingrediente tiene g/unidad


class MealIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=200)
    franja: str = Field(default="comida", max_length=30)
    tags: str = Field(default="", max_length=500)
    tiempo_preparacion_min: int = Field(default=0, ge=0, le=10_000)
    gramos_recomendados: float = Field(default=0, ge=0, le=10_000)  # 0/omitido => se autosugiere al guardar
    es_racion_unica: bool = False
    instrucciones: list[str] = Field(default_factory=list, max_length=100)
    image_url: str = Field(default="", max_length=2048)
    image_source: str = Field(default="pexels", max_length=40)
    ingredientes: list[MealIngredientIn] = Field(default_factory=list, max_length=100)


class SuggestGramosRequest(BaseModel):
    franja: str = Field(default="comida", max_length=30)
    ingredientes: list[MealIngredientIn] = Field(default_factory=list, max_length=100)


class ShoppingItemIn(BaseModel):
    ingredient_id: int | None = None
    nombre_libre: str | None = Field(default=None, max_length=200)
    cantidad_gramos: float = Field(default=0, ge=0, le=1_000_000)


class ShoppingItemUpdate(BaseModel):
    cantidad_gramos: float | None = Field(default=None, ge=0, le=1_000_000)
    comprado: bool | None = None


class WeeklyPlanAssign(BaseModel):
    semana: str = Field(pattern=SEMANA_PATTERN)
    dia: str = Field(max_length=20)
    franja: str = Field(max_length=30)
    meal_id: int = Field(ge=1)
    is_fixed: bool = False


class GenerateWeekRequest(BaseModel):
    semana: str = Field(pattern=SEMANA_PATTERN)
    franjas: list[str] = Field(max_length=10)


class UserProfileIn(BaseModel):
    edad: int = Field(ge=10, le=120)
    peso_kg: float = Field(ge=20, le=400)
    altura_cm: float = Field(ge=100, le=250)
    sexo: str = Field(pattern=r"^(hombre|mujer)$")
    nivel_actividad: float = Field(ge=1.0, le=2.5)
    objetivo: str = Field(max_length=30)
    proteina_g_kg: float = Field(ge=0.5, le=4.0)
    grasa_pct: float | None = Field(default=None, ge=10, le=60)
    ajuste_pct: float | None = Field(default=None, ge=-40, le=40)


class PlanSlotAdd(BaseModel):
    semana: str = Field(pattern=SEMANA_PATTERN)
    dia: str = Field(max_length=20)
    franja: str = Field(max_length=30)
    meal_id: int = Field(ge=1)
    gramos: float | None = Field(default=None, gt=0, le=3000)
    rol: str | None = Field(default=None, pattern=r"^(primero|segundo|guarnicion|postre|bebida|unico)$")


class PlanItemAdd(BaseModel):
    meal_id: int = Field(ge=1)
    gramos: float | None = Field(default=None, gt=0, le=3000)
    rol: str | None = Field(default=None, pattern=r"^(primero|segundo|guarnicion|postre|bebida|unico)$")


class GramosUpdate(BaseModel):
    gramos: float | None = Field(default=None, gt=0, le=3000)  # None = volver a la ración estándar


# ─────────────────────────────────────────────
# Objetivos nutricionales
# ─────────────────────────────────────────────
def calculate_targets(profile: dict) -> dict:
    """Objetivos diarios (ver comidas/nutrition.py). Mantiene las claves antiguas."""
    return nu.calcular_objetivos(profile)


# ─────────────────────────────────────────────
# Franjas
# ─────────────────────────────────────────────
# Peso de cada franja en las kcal del día. Los valores de partida; la tabla `franjas`
# (comidas/migrations.py) manda y _sync_franjas() los refresca antes de planificar.
# Se cambian EN EL SITIO (clear/update): quien los importó ve siempre lo último.
SLOT_WEIGHTS_BASE = {"desayuno": 0.25, "comida": 0.35, "merienda": 0.10, "cena": 0.30}
# Franja → franja de los platos con que se llena (extras y las propias tiran de meriendas)
CATALOGO_DE: dict[str, str] = {}
FRANJA_ORDEN = ["desayuno", "comida", "merienda", "cena"]
FRANJA_DIAS: dict[str, set[str] | None] = {}  # franja → días en que se usa (None = todos)
FRANJA_FRACCION = {"desayuno": 0.25, "comida": 0.35, "merienda": 0.10, "cena": 0.30}
FRANJA_NOMBRE: dict[str, str] = {}


def _sync_franjas(conn) -> list[dict]:
    """Lee la tabla `franjas` y deja al día las constantes que usan el generador, las
    sugerencias y el plan (en el sitio: así las funciones antiguas ven lo mismo)."""
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM franjas ORDER BY orden, clave")]
    except sqlite3.OperationalError:
        return [
            {"clave": f, "nombre": f.capitalize(), "fraccion": FRANJA_FRACCION[f], "activa": 1, "catalogo": f}
            for f in FRANJA_ORDEN
        ]
    if rows:
        FRANJA_ORDEN[:] = [r["clave"] for r in rows]
        FRANJA_FRACCION.clear()
        FRANJA_FRACCION.update({r["clave"]: float(r["fraccion"] or 0) for r in rows})
        SLOT_WEIGHTS_BASE.clear()
        SLOT_WEIGHTS_BASE.update(FRANJA_FRACCION)
        CATALOGO_DE.clear()
        CATALOGO_DE.update({r["clave"]: r["catalogo"] or r["clave"] for r in rows})
        FRANJA_NOMBRE.clear()
        FRANJA_NOMBRE.update({r["clave"]: r["nombre"] for r in rows})
        FRANJA_DIAS.clear()
        for r in rows:
            r["dias"] = _parse_dias(r.get("dias"))
            FRANJA_DIAS[r["clave"]] = set(r["dias"]) if r["dias"] is not None else None
    return rows


def _parse_dias(raw) -> list[str] | None:
    """Columna `franjas.dias`: NULL (o los 7) = todos los días; si no, los días en orden."""
    if raw in (None, ""):
        return None
    try:
        dias = json.loads(raw) if isinstance(raw, str) else list(raw)
    except ValueError:
        return None
    dias = [d for d in DIAS_SEMANA if d in set(dias)]
    return None if len(dias) == 7 else dias


def franja_en_dia(franja: str, dia: str) -> bool:
    """¿Se usa esta franja ese día? (las desactivadas en un día no se generan ni se sugieren)"""
    dias = FRANJA_DIAS.get(franja)
    return dias is None or dia in dias


def _catalogo_de(franja: str) -> str:
    return CATALOGO_DE.get(franja, franja)


def _check_dia_franja(dia: str, franja: str):
    if dia not in DIAS_SEMANA:
        raise HTTPException(status_code=422, detail="Día no válido")
    with get_db() as conn:
        _sync_franjas(conn)
    if franja not in FRANJA_ORDEN:
        raise HTTPException(status_code=422, detail="Franja no válida")


def _slot_id(conn, semana, dia, franja) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO weekly_plan (semana, dia, franja, meal_id, is_fixed) VALUES (?, ?, ?, NULL, 0)",
        (semana, dia, franja),
    )
    return conn.execute(
        "SELECT id FROM weekly_plan WHERE semana=? AND dia=? AND franja=?", (semana, dia, franja)
    ).fetchone()["id"]


# ─────────────────────────────────────────────
# Recetas: ingredientes de un plato y ración sugerida
# ─────────────────────────────────────────────
INGREDIENT_FIELDS = (
    "nombre",
    "categoria",
    "kcal_100g",
    "proteinas_100g",
    "carbohidratos_100g",
    "grasas_100g",
    "grasas_saturadas_100g",
    "grasas_trans_100g",
    "azucares_100g",
    "sal_100g",
    "gramos_por_unidad",
    "unidad_nombre",
)

FOOD_GROUP_KEYWORDS = {
    "pescado": ["salmon", "salmón", "merluza", "atun", "atún", "bacalao", "boquerones", "gambas"],
    "carne_blanca": ["pollo", "pavo"],
    "carne_roja": ["ternera", "cerdo", "lomo"],
    "procesada": ["jamon", "jamón", "chorizo", "panceta", "salchich", "morcilla"],
    "huevo": ["huevo"],
}

PROTEIN_PORTION_G = {
    "pescado": 200,
    "carne_blanca": 175,
    "carne_roja": 160,
    "huevo": 130,
    "legumbre": 180,
    "procesada": 90,
}

FRANJA_BASE_PLATE_G = {"desayuno": 300, "comida": 420, "merienda": 180, "cena": 380}


def _food_group_of(nombre_lower: str, categoria: str):
    for group, keywords in FOOD_GROUP_KEYWORDS.items():
        if any(kw in nombre_lower for kw in keywords):
            return group
    if categoria == "legumbre":
        return "legumbre"
    return None


def _suggest_gramos_recomendados(conn, ingredientes: list[MealIngredientIn], franja: str) -> float:
    """Sugiere gramos de plato ya montado para una racion ESTANDAR de
    catalogo (punto de partida; el generador la reescala despues segun
    tu objetivo real, no aqui)."""
    if not ingredientes:
        return float(FRANJA_BASE_PLATE_G.get(franja, 350))

    rows = []
    total_gramos = 0.0
    for ing in ingredientes:
        row = conn.execute(
            "SELECT nombre, categoria, gramos_por_unidad FROM ingredients WHERE id=?", (ing.ingredient_id,)
        ).fetchone()
        gramos = (ing.gramos or (ing.unidades or 0) * (row["gramos_por_unidad"] or 0)) if row else 0
        if not gramos:
            continue
        rows.append({"nombre": row["nombre"], "categoria": row["categoria"], "gramos": gramos})
        total_gramos += gramos

    if not rows or total_gramos <= 0:
        return float(FRANJA_BASE_PLATE_G.get(franja, 350))

    candidates = []
    for r in rows:
        group = _food_group_of(r["nombre"].lower(), r["categoria"])
        if group in PROTEIN_PORTION_G:
            candidates.append((r, group))

    if not candidates:
        return float(FRANJA_BASE_PLATE_G.get(franja, 350))

    main_row, main_group = max(candidates, key=lambda rg: rg[0]["gramos"])
    factor = PROTEIN_PORTION_G[main_group] / main_row["gramos"]
    suggested = total_gramos * factor
    suggested = max(150, min(700, suggested))
    return round(suggested / 5) * 5


def _recipe_index(conn) -> dict:
    """Todas las recetas en dos consultas: macros totales (por plato completo),
    gramos de receta y ración estándar de catálogo."""
    meals = {m["id"]: m for m in conn.execute("SELECT * FROM meals").fetchall()}
    by_meal: dict[int, list] = {mid: [] for mid in meals}
    for r in conn.execute("""
        SELECT mi.meal_id, mi.gramos, i.kcal_100g, i.proteinas_100g, i.carbohidratos_100g, i.grasas_100g,
               i.azucares_100g, i.sal_100g, i.grasas_saturadas_100g
        FROM meal_ingredients mi JOIN ingredients i ON i.id = mi.ingredient_id
    """):
        if r["meal_id"] in by_meal:
            by_meal[r["meal_id"]].append(dict(r))
    index = {}
    for mid, row in meals.items():
        total, gramos = nu.receta(by_meal[mid])
        unica = bool(row["es_racion_unica"])
        index[mid] = {
            "id": mid,
            "row": row,
            "nombre": row["nombre"],
            "franja": row["franja"],
            "image_url": row["image_url"],
            "total": total,
            "gramos_receta": gramos,
            "es_racion_unica": unica,
            "gramos_base": gramos if unica else (row["gramos_recomendados"] or 0),
            "n_ingredientes": len(by_meal[mid]),
        }
    return index


def _resolve_ingredients(conn, ingredientes: list[MealIngredientIn]) -> list[dict]:
    """Convierte cada ingrediente de la receta a gramos. Si viene en unidades se
    usan los g/unidad del ingrediente; sin gramos ni unidades válidas -> 422."""
    out = []
    for ing in ingredientes:
        row = conn.execute(
            "SELECT nombre, gramos_por_unidad FROM ingredients WHERE id=?", (ing.ingredient_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=422, detail=f"El ingrediente {ing.ingredient_id} no existe")
        if ing.unidades is not None:
            if not row["gramos_por_unidad"]:
                raise HTTPException(
                    status_code=422, detail=f"«{row['nombre']}» no tiene definidos los gramos por unidad"
                )
            gramos = ing.unidades * row["gramos_por_unidad"]
        elif ing.gramos:
            gramos = ing.gramos
        else:
            raise HTTPException(status_code=422, detail=f"Indica gramos o unidades para «{row['nombre']}»")
        out.append({"ingredient_id": ing.ingredient_id, "gramos": gramos, "unidades": ing.unidades})
    return out


def _write_meal_ingredients(conn, meal_id: int, resolved: list[dict]):
    conn.execute("DELETE FROM meal_ingredients WHERE meal_id=?", (meal_id,))
    for ing in resolved:
        conn.execute(
            "INSERT INTO meal_ingredients (meal_id, ingredient_id, gramos, unidades) VALUES (?, ?, ?, ?)",
            (meal_id, ing["ingredient_id"], ing["gramos"], ing["unidades"]),
        )
