"""
comidas/main.py

Sub-aplicacion FastAPI de "Comidas": catalogo de ingredientes, comidas con
macros calculados a partir de sus ingredientes, planificador semanal con
generador automatico, lista de la compra agregada, y perfil de usuario con
calculo de objetivos nutricionales (Mifflin-St Jeor).

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

RACION PERSONALIZADA POR CELDA DEL PLANIFICADOR (nuevo)
----------------------------------------------------------
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

Se monta en el proceso raiz con: app.mount("/comidas", app)
"""
import contextlib
import os
import json
import random
import sqlite3

from typing import Annotated

from fastapi import FastAPI, HTTPException, Path as FPath, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core import config
from core.templating import render
from .database import init_db, get_db
from . import nutrition as nu

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# Foto de stock que el formulario antiguo ponía por defecto a todos los platos:
# se trata como "sin foto" (la interfaz dibuja un icono de la franja).
PLACEHOLDER_IMAGE_PREFIX = "https://images.unsplash.com/photo-1495521821757-a1efb6729352"


def _cache_meal_image(url: str) -> str:
    """Pasa una foto externa a caché local (misma protección SSRF que el Baúl)."""
    from app.scraper import cache_thumbnail
    if not url or url.startswith("/static/") or url.startswith(PLACEHOLDER_IMAGE_PREFIX):
        return url if not (url or "").startswith(PLACEHOLDER_IMAGE_PREFIX) else ""
    return cache_thumbnail(url, str(config.UPLOADS_DIR / "thumbs")) or url


def backfill_meal_images():
    with get_db() as conn:
        rows = conn.execute("SELECT id, image_url FROM meals WHERE image_url LIKE 'http%'").fetchall()
    for r in rows:
        local = _cache_meal_image(r["image_url"])
        if local != r["image_url"] and (local == "" or local.startswith("/static/")):
            with get_db() as conn:
                conn.execute("UPDATE meals SET image_url=? WHERE id=?", (local, r["id"]))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not config.DISABLE_SCHEDULER:
        import threading
        threading.Thread(target=backfill_meal_images, name="meal-images", daemon=True).start()
    yield

app = FastAPI(title="Comidas", lifespan=lifespan)

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
# Helpers: objetivos nutricionales
# ─────────────────────────────────────────────
def calculate_targets(profile: dict) -> dict:
    """Objetivos diarios (ver comidas/nutrition.py). Mantiene las claves antiguas."""
    return nu.calcular_objetivos(profile)

# ─────────────────────────────────────────────
# Constantes del generador y de la heuristica de sugerencia
# ─────────────────────────────────────────────
# Peso de cada franja en las kcal del día. Los valores de partida; la tabla `franjas`
# (comidas/migrations.py) manda y _sync_franjas() los refresca antes de planificar.
SLOT_WEIGHTS_BASE = {"desayuno": 0.25, "comida": 0.35, "merienda": 0.10, "cena": 0.30}
# Franja → franja de los platos con que se llena (extras y las propias tiran de meriendas)
CATALOGO_DE: dict[str, str] = {}
ROLES = ("primero", "segundo", "guarnicion", "postre", "bebida", "unico")

FOOD_GROUP_KEYWORDS = {
    "pescado": ["salmon", "salmón", "merluza", "atun", "atún", "bacalao", "boquerones", "gambas"],
    "carne_blanca": ["pollo", "pavo"],
    "carne_roja": ["ternera", "cerdo", "lomo"],
    "procesada": ["jamon", "jamón", "chorizo", "panceta", "salchich", "morcilla"],
    "huevo": ["huevo"],
}

VERDURA_GRAMOS_MIN = 60

WEEKLY_MIN = {"pescado": 2, "legumbre": 3, "verdura": 10}
WEEKLY_MAX = {"procesada": 3, "carne_roja": 2}
DAILY_MAX = {"procesada": 1, "carne_roja": 1, "pescado": 1}

PROTEIN_PORTION_G = {
    "pescado": 200,
    "carne_blanca": 175,
    "carne_roja": 160,
    "huevo": 130,
    "legumbre": 180,
    "procesada": 90,
}

FRANJA_BASE_PLATE_G = {"desayuno": 300, "comida": 420, "merienda": 180, "cena": 380}

# Rango de escalado que el GENERADOR puede aplicar a la racion de
# catalogo de un plato para que sus kcal encajen en el hueco de esa
# franja/dia. No es un factor global: se calcula plato a plato, cada
# vez, a partir de tu objetivo real (calculate_targets del perfil).
ESCALADO_MIN_FACTOR = 0.6
ESCALADO_MAX_FACTOR = 1.8
GRAMOS_RACION_MIN_ABS = 120
GRAMOS_RACION_MAX_ABS = 900


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
        r["gramos"] for r in ingredient_rows
        if "categoria" in r.keys() and r["categoria"] == "verdura"
    )
    if verdura_gramos >= VERDURA_GRAMOS_MIN:
        groups.add("verdura")

    if not groups & {"pescado", "carne_blanca", "carne_roja", "procesada", "huevo"}:
        groups.add("vegetariano")

    return groups


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


def _build_meal_catalog(conn):
    """Construye, para cada comida, su DENSIDAD por 100g y su racion
    base de catalogo (gramos_base), junto con el rango sano en el que
    el generador puede escalarla (gramos_min/gramos_max). No fija
    ninguna cantidad de kcal: eso se decide por franja/dia en el
    generador, calculando los gramos exactos que hacen falta."""
    catalogo = {}
    for m in conn.execute("SELECT * FROM meals").fetchall():
        ing_rows = conn.execute("""
            SELECT i.nombre, i.categoria, i.kcal_100g, i.proteinas_100g, i.carbohidratos_100g, i.grasas_100g, mi.gramos
            FROM meal_ingredients mi JOIN ingredients i ON i.id = mi.ingredient_id
            WHERE mi.meal_id = ?
        """, (m["id"],)).fetchall()

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

        gramos_min = max(GRAMOS_RACION_MIN_ABS, gramos_base * ESCALADO_MIN_FACTOR) if gramos_base > 0 else GRAMOS_RACION_MIN_ABS
        gramos_max = min(GRAMOS_RACION_MAX_ABS, gramos_base * ESCALADO_MAX_FACTOR) if gramos_base > 0 else GRAMOS_RACION_MAX_ABS
        if gramos_max < gramos_min:
            gramos_max = gramos_min

        catalogo[m["id"]] = {
            "id": m["id"], "nombre": m["nombre"], "franja": m["franja"],
            "kcal_100g": kcal_100g, "prot_100g": prot_100g, "carb_100g": carb_100g, "fat_100g": fat_100g,
            "gramos_base": gramos_base, "gramos_min": gramos_min, "gramos_max": gramos_max,
            "groups": _classify_meal_groups(ing_rows),
            "favorito": bool(m["favorito"]) if "favorito" in m.keys() else False,
        }
    return catalogo


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
            "id": mid, "row": row, "nombre": row["nombre"], "franja": row["franja"], "image_url": row["image_url"],
            "total": total, "gramos_receta": gramos, "es_racion_unica": unica,
            "gramos_base": gramos if unica else (row["gramos_recomendados"] or 0),
            "n_ingredientes": len(by_meal[mid]),
        }
    return index


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


def _build_week_state(conn, semana, catalogo, exclude_plan_id=None):
    used_main, used_side = set(), set()
    used_side_counts, group_counts = {}, {}
    day_group_counts = {}
    side_days: dict[int, set] = {}  # desayunos/meriendas: en qué días (índice) salen

    for r in conn.execute("SELECT * FROM weekly_plan WHERE semana=?", (semana,)).fetchall():
        if exclude_plan_id and r["id"] == exclude_plan_id:
            continue
        if not r["meal_id"]:
            continue
        m = catalogo.get(r["meal_id"])
        if not m:
            continue

        if r["franja"] in ("comida", "cena"):
            used_main.add(r["meal_id"])
        else:
            used_side.add(r["meal_id"])
            used_side_counts[r["meal_id"]] = used_side_counts.get(r["meal_id"], 0) + 1
            if r["dia"] in DIAS_SEMANA:
                side_days.setdefault(r["meal_id"], set()).add(DIAS_SEMANA.index(r["dia"]))

        for g in m["groups"]:
            group_counts[g] = group_counts.get(g, 0) + 1

        day_groups = day_group_counts.setdefault(r["dia"], {})
        for g in m["groups"]:
            day_groups[g] = day_groups.get(g, 0) + 1

    recent_usage = {}
    for r in conn.execute("""
        SELECT meal_id, COUNT(*) as c FROM meal_usage_log
        WHERE semana >= date(?, '-42 days') GROUP BY meal_id
    """, (semana,)).fetchall():
        recent_usage[r["meal_id"]] = r["c"]

    return {
        "used_main": used_main,
        "used_side": used_side,
        "used_side_counts": used_side_counts,
        "group_counts": group_counts,
        "day_group_counts": day_group_counts,
        "recent_usage": recent_usage,
        "side_days": side_days,
    }


MACROS = ("kcal", "prot", "carb", "fat")
# Claves de calculate_targets para cada macro del generador
TARGET_KEYS = {"kcal": "kcal_objetivo", "prot": "proteina_g", "carb": "carbohidratos_g", "fat": "grasa_g"}
PROTEIN_GROUPS = ("pescado", "carne_blanca", "carne_roja", "procesada", "huevo", "legumbre")


def _macros_de(meal, gramos) -> dict:
    return {"kcal": meal["kcal_100g"] * gramos / 100, "prot": meal["prot_100g"] * gramos / 100,
            "carb": meal["carb_100g"] * gramos / 100, "fat": meal["fat_100g"] * gramos / 100}


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
    err = (abs(m["kcal"] - target["kcal"])
           + abs(dp) * 4 * (2.4 if dp < 0 else 0.6)
           + abs(dc) * 4 * (1.0 if dc < 0 else 0.7)
           + abs(df) * 9 * (1.4 if df > 0 else 0.4))
    return err / max(target["kcal"], 100)


def _ajustar_raciones_dia(elegidos: list, hueco_kcal: float) -> None:
    """Cierra el hueco de kcal del día repartiéndolo entre las raciones generadas (no las fijas),
    cada una dentro de su rango sano y en pasos de 5 g. `elegidos` = [[franja, plato, gramos], …]."""
    for _ in range(3):
        if abs(hueco_kcal) < 25:
            return
        movibles = [e for e in elegidos if e[1]["kcal_100g"] > 0
                    and (e[2] < e[1]["gramos_max"] if hueco_kcal > 0 else e[2] > e[1]["gramos_min"])]
        if not movibles:
            return
        total = sum(e[1]["kcal_100g"] * e[2] / 100 for e in movibles) or 1
        for e in movibles:
            kcal = e[1]["kcal_100g"] * e[2] / 100
            nuevo = e[2] + hueco_kcal * (kcal / total) / e[1]["kcal_100g"] * 100
            nuevo = round(max(e[1]["gramos_min"], min(e[1]["gramos_max"], nuevo)) / 5) * 5
            hueco_kcal -= e[1]["kcal_100g"] * (nuevo - e[2]) / 100
            e[2] = nuevo


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

    for g in meal["groups"]:
        if g in WEEKLY_MAX and week_state["group_counts"].get(g, 0) >= WEEKLY_MAX[g]:
            score -= 5.0

    if franja in ("comida", "cena"):
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

    if franja not in ("comida", "cena"):
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


def _add_ingredient_to_shopping_list(conn, ingredient_id: int, gramos: float, source: str, source_meal_id: int = None):
    existing = conn.execute(
        "SELECT id, cantidad_gramos, source FROM shopping_list WHERE ingredient_id=?",
        (ingredient_id,)
    ).fetchone()
    if existing:
        new_qty = existing["cantidad_gramos"] + gramos
        new_source = existing["source"] if existing["source"] == source else "mixto"
        conn.execute(
            "UPDATE shopping_list SET cantidad_gramos=?, source=?, source_meal_id=? WHERE id=?",
            (new_qty, new_source, source_meal_id if new_source != "mixto" else None, existing["id"])
        )
    else:
        conn.execute(
            "INSERT INTO shopping_list (ingredient_id, cantidad_gramos, source, source_meal_id) VALUES (?, ?, ?, ?)",
            (ingredient_id, gramos, source, source_meal_id)
        )

# ─────────────────────────────────────────────
# Ingredientes
# ─────────────────────────────────────────────
INGREDIENT_FIELDS = ("nombre", "categoria", "kcal_100g", "proteinas_100g", "carbohidratos_100g", "grasas_100g",
                     "grasas_saturadas_100g", "grasas_trans_100g", "azucares_100g", "sal_100g",
                     "gramos_por_unidad", "unidad_nombre")


def _ingredient_out(row) -> dict:
    d = dict(row)
    d["kcal_check"] = nu.comprobar_kcal(d["kcal_100g"], d["proteinas_100g"], d["carbohidratos_100g"], d["grasas_100g"])
    return d


@app.get("/api/ingredients")
def get_ingredients(categoria: str = "", search: str = ""):
    with get_db() as conn:
        query = "SELECT * FROM ingredients WHERE 1=1"
        params = []
        if categoria:
            query += " AND categoria=?"
            params.append(categoria)
        if search:
            query += " AND nombre LIKE ?"
            params.append(f"%{search}%")
        rows = conn.execute(query + " ORDER BY nombre", params).fetchall()
    return {"ingredients": [_ingredient_out(r) for r in rows]}


@app.get("/api/ingredients/validation")
def validate_ingredients():
    """Ingredientes cuyas kcal no cuadran con 4·P + 4·C + 9·G (posible error de datos)."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM ingredients ORDER BY nombre").fetchall()
    bad = [i for i in (_ingredient_out(r) for r in rows) if not i["kcal_check"]["ok"]]
    return {"total": len(rows), "inconsistentes": bad}


@app.post("/api/ingredients")
def create_ingredient(data: IngredientIn):
    values = [getattr(data, f) for f in INGREDIENT_FIELDS]
    with get_db() as conn:
        try:
            cursor = conn.execute(
                f"INSERT INTO ingredients ({', '.join(INGREDIENT_FIELDS)}) VALUES ({', '.join('?' * len(INGREDIENT_FIELDS))})",
                values)
            new_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            return JSONResponse(status_code=409, content={"error": "Ese ingrediente ya existe"})
    check = nu.comprobar_kcal(data.kcal_100g, data.proteinas_100g, data.carbohidratos_100g, data.grasas_100g)
    return {"status": "success", "id": new_id, "kcal_check": check}


@app.patch("/api/ingredients/{ingredient_id}")
def update_ingredient(ingredient_id: int, data: IngredientIn):
    with get_db() as conn:
        try:
            conn.execute(f"UPDATE ingredients SET {', '.join(f + '=?' for f in INGREDIENT_FIELDS)} WHERE id=?",
                         [getattr(data, f) for f in INGREDIENT_FIELDS] + [ingredient_id])
        except sqlite3.IntegrityError:
            return JSONResponse(status_code=409, content={"error": "Ya existe otro ingrediente con ese nombre"})
        # Si cambian los g/unidad, se recalculan los gramos de las recetas que lo usan por unidades
        if data.gramos_por_unidad:
            conn.execute("UPDATE meal_ingredients SET gramos = unidades * ? WHERE ingredient_id=? AND unidades IS NOT NULL",
                         (data.gramos_por_unidad, ingredient_id))
    check = nu.comprobar_kcal(data.kcal_100g, data.proteinas_100g, data.carbohidratos_100g, data.grasas_100g)
    return {"status": "success", "kcal_check": check}

@app.delete("/api/ingredients/{ingredient_id}")
def delete_ingredient(ingredient_id: int):
    """A la papelera, como el borrado en lote (la compra conserva la línea como texto libre)."""
    from .bulk import Selection, ingredients_delete
    return ingredients_delete(Selection(ids=[ingredient_id]))

# ─────────────────────────────────────────────
# Comidas (platos del catálogo)
# ─────────────────────────────────────────────
def _resolve_ingredients(conn, ingredientes: list[MealIngredientIn]) -> list[dict]:
    """Convierte cada ingrediente de la receta a gramos. Si viene en unidades se
    usan los g/unidad del ingrediente; sin gramos ni unidades válidas -> 422."""
    out = []
    for ing in ingredientes:
        row = conn.execute("SELECT nombre, gramos_por_unidad FROM ingredients WHERE id=?", (ing.ingredient_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=422, detail=f"El ingrediente {ing.ingredient_id} no existe")
        if ing.unidades is not None:
            if not row["gramos_por_unidad"]:
                raise HTTPException(status_code=422, detail=f"«{row['nombre']}» no tiene definidos los gramos por unidad")
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
        conn.execute("INSERT INTO meal_ingredients (meal_id, ingredient_id, gramos, unidades) VALUES (?, ?, ?, ?)",
                     (meal_id, ing["ingredient_id"], ing["gramos"], ing["unidades"]))


@app.post("/api/meals/suggest-gramos")
def suggest_gramos(payload: SuggestGramosRequest):
    with get_db() as conn:
        resolved = _resolve_ingredients(conn, payload.ingredientes)
        suggestion = _suggest_gramos_recomendados(conn, [MealIngredientIn(ingredient_id=r["ingredient_id"], gramos=r["gramos"]) for r in resolved], payload.franja)
    return {"gramos_recomendados": suggestion}

@app.get("/api/meals")
def get_meals(franja: str = "", tag: str = ""):
    with get_db() as conn:
        index = _recipe_index(conn)
    meals = []
    for m in index.values():
        if franja and m["franja"] != franja:
            continue
        if tag and tag not in (m["row"]["tags"] or ""):
            continue
        meal = dict(m["row"])
        porcion = nu.racion(m["total"], m["gramos_receta"], m["gramos_base"])
        meal["kcal_total"] = round(porcion["kcal"])
        meal["macros_racion"] = nu.redondear(porcion)
        meal["gramos_recomendados"] = m["gramos_base"]
        meal["es_racion_unica"] = m["es_racion_unica"]
        meal["n_ingredientes"] = m["n_ingredientes"]
        meals.append(meal)
    meals.sort(key=lambda x: x["id"])
    return {"meals": meals}

@app.get("/api/meals/{meal_id}")
def get_meal(meal_id: int):
    with get_db() as conn:
        meal = conn.execute("SELECT * FROM meals WHERE id=?", (meal_id,)).fetchone()
        if not meal:
            return JSONResponse(status_code=404, content={"error": "Comida no encontrada"})
        ing_rows = conn.execute('''
            SELECT i.*, mi.gramos, mi.unidades
            FROM meal_ingredients mi JOIN ingredients i ON i.id = mi.ingredient_id
            WHERE mi.meal_id = ? ORDER BY mi.id
        ''', (meal_id,)).fetchall()

    ingredientes = [dict(r) for r in ing_rows]
    total, gramos_totales = nu.receta(ingredientes)
    es_racion_unica = bool(meal["es_racion_unica"])
    gramos_rec = gramos_totales if es_racion_unica else (meal["gramos_recomendados"] or 0)
    ing_list = []
    for ing in ingredientes:
        aporte = nu.macros_por_cantidad(ing, ing["gramos"])
        ing_list.append({"id": ing["id"], "nombre": ing["nombre"], "gramos": ing["gramos"], "unidades": ing["unidades"],
                         "unidad_nombre": ing["unidad_nombre"], "gramos_por_unidad": ing["gramos_por_unidad"],
                         "aporte": nu.redondear(aporte),
                         "kcal_check": nu.comprobar_kcal(ing["kcal_100g"], ing["proteinas_100g"], ing["carbohidratos_100g"], ing["grasas_100g"])})

    result = dict(meal)
    result["ingredientes"] = ing_list
    result["instrucciones"] = json.loads(meal["instrucciones"] or "[]")
    result["gramos_totales_receta"] = round(gramos_totales, 1)
    result["gramos_recomendados"] = gramos_rec
    result["es_racion_unica"] = es_racion_unica
    result["nutricion_total_receta"] = nu.redondear(total)                                   # suma literal
    result["nutricion_por_100g"] = nu.redondear(nu.densidad_100g(total, gramos_totales))
    result["nutricion_total"] = nu.redondear(nu.racion(total, gramos_totales, gramos_rec))   # ración estándar
    result["kcal_check"] = nu.comprobar_kcal(total["kcal"], total["proteinas"], total["carbohidratos"], total["grasas"])
    return result

@app.post("/api/meals")
def create_meal(meal: MealIn):
    with get_db() as conn:
        resolved = _resolve_ingredients(conn, meal.ingredientes)
        gramos_rec = meal.gramos_recomendados
        if not meal.es_racion_unica and (not gramos_rec or gramos_rec <= 0):
            gramos_rec = _suggest_gramos_recomendados(conn, [MealIngredientIn(ingredient_id=r["ingredient_id"], gramos=r["gramos"]) for r in resolved], meal.franja)
        cursor = conn.execute('''
            INSERT INTO meals (nombre, franja, tags, tiempo_preparacion_min, gramos_recomendados, es_racion_unica, instrucciones, image_url, image_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (meal.nombre, meal.franja, meal.tags, meal.tiempo_preparacion_min, gramos_rec, int(meal.es_racion_unica),
              json.dumps(meal.instrucciones), _cache_meal_image(meal.image_url), meal.image_source))
        meal_id = cursor.lastrowid
        _write_meal_ingredients(conn, meal_id, resolved)
    return {"status": "success", "id": meal_id, "gramos_recomendados": gramos_rec}

@app.patch("/api/meals/{meal_id}")
def update_meal(meal_id: int, meal: MealIn):
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM meals WHERE id=?", (meal_id,)).fetchone():
            return JSONResponse(status_code=404, content={"error": "Comida no encontrada"})
        resolved = _resolve_ingredients(conn, meal.ingredientes)
        gramos_rec = meal.gramos_recomendados
        if not meal.es_racion_unica and (not gramos_rec or gramos_rec <= 0):
            gramos_rec = _suggest_gramos_recomendados(conn, [MealIngredientIn(ingredient_id=r["ingredient_id"], gramos=r["gramos"]) for r in resolved], meal.franja)
        conn.execute('''
            UPDATE meals SET nombre=?, franja=?, tags=?, tiempo_preparacion_min=?, gramos_recomendados=?, es_racion_unica=?,
                instrucciones=?, image_url=?, image_source=?
            WHERE id=?
        ''', (meal.nombre, meal.franja, meal.tags, meal.tiempo_preparacion_min, gramos_rec, int(meal.es_racion_unica),
              json.dumps(meal.instrucciones), _cache_meal_image(meal.image_url), meal.image_source, meal_id))
        _write_meal_ingredients(conn, meal_id, resolved)
    return {"status": "success", "gramos_recomendados": gramos_rec}

@app.delete("/api/meals/{meal_id}")
def delete_meal(meal_id: int):
    """A la papelera, como el borrado en lote (el plan y la compra se liberan y se recuperan al restaurar)."""
    from .bulk import Selection, meals_delete
    return meals_delete(Selection(ids=[meal_id]))

# ─────────────────────────────────────────────
# Lista de la compra
# ─────────────────────────────────────────────
@app.get("/api/shopping-list")
def get_shopping_list():
    with get_db() as conn:
        rows = conn.execute('''
            SELECT sl.*, i.nombre as ingredient_nombre, i.categoria, i.gramos_por_unidad, i.unidad_nombre
            FROM shopping_list sl LEFT JOIN ingredients i ON i.id = sl.ingredient_id
            ORDER BY sl.created_at DESC
        ''').fetchall()
    return {"items": [dict(r) for r in rows]}

@app.post("/api/shopping-list")
def add_shopping_item(data: ShoppingItemIn):
    with get_db() as conn:
        if data.ingredient_id:
            if not conn.execute("SELECT 1 FROM ingredients WHERE id=?", (data.ingredient_id,)).fetchone():
                raise HTTPException(status_code=422, detail="Ese ingrediente no existe")
            _add_ingredient_to_shopping_list(conn, data.ingredient_id, data.cantidad_gramos, "manual")
        else:
            conn.execute(
                "INSERT INTO shopping_list (nombre_libre, cantidad_gramos, source) VALUES (?, ?, 'manual')",
                (data.nombre_libre, data.cantidad_gramos)
            )
        conn.commit()
    return {"status": "success"}

@app.delete("/api/shopping-list/done")
def clear_done_shopping_items():
    with get_db() as conn:
        conn.execute("DELETE FROM shopping_list WHERE comprado=1")
        conn.commit()
    return {"status": "success"}

@app.post("/api/shopping-list/from-meal/{meal_id}")
def add_meal_to_shopping_list(meal_id: int):
    with get_db() as conn:
        rows = conn.execute("SELECT ingredient_id, gramos FROM meal_ingredients WHERE meal_id=?", (meal_id,)).fetchall()
        for row in rows:
            _add_ingredient_to_shopping_list(conn, row["ingredient_id"], row["gramos"], "planificador", meal_id)
        conn.commit()
    return {"status": "success", "added": len(rows)}

def _week_ingredient_totals(conn, semana: str) -> dict[int, float]:
    """Gramos de cada ingrediente para la semana: cada plato (principal o extra)
    escala su receta a la ración planificada (antes se sumaba la receta entera)."""
    index = _recipe_index(conn)
    porciones = []
    for r in conn.execute("SELECT meal_id, gramos_racion FROM weekly_plan WHERE semana=? AND meal_id IS NOT NULL", (semana,)):
        porciones.append((r["meal_id"], r["gramos_racion"]))
    for r in conn.execute("""SELECT pi.meal_id, pi.gramos_racion FROM plan_items pi JOIN weekly_plan wp ON wp.id = pi.plan_id
                             WHERE wp.semana=?""", (semana,)):
        porciones.append((r["meal_id"], r["gramos_racion"]))
    totales: dict[int, float] = {}
    for meal_id, gramos_racion in porciones:
        m = index.get(meal_id)
        if not m or not m["gramos_receta"]:
            continue
        gramos = gramos_racion if gramos_racion is not None else m["gramos_base"]
        factor = (gramos or 0) / m["gramos_receta"]
        for ing in conn.execute("SELECT ingredient_id, gramos FROM meal_ingredients WHERE meal_id=?", (meal_id,)):
            totales[ing["ingredient_id"]] = totales.get(ing["ingredient_id"], 0) + ing["gramos"] * factor
    return {k: round(v) for k, v in totales.items()}


@app.post("/api/shopping-list/from-week/{semana}")
def add_week_to_shopping_list(semana: Semana):
    """Suma a la lista lo que pide el plan de la semana (por ingrediente). Volver a
    pulsarlo no duplica: se reemplaza la parte que venía de esa semana (plan_gramos)
    y se conserva lo añadido a mano."""
    with get_db() as conn:
        totales = _week_ingredient_totals(conn, semana)
        nuevos = actualizados = 0
        for ingredient_id, gramos in totales.items():
            row = conn.execute("SELECT * FROM shopping_list WHERE ingredient_id=? ORDER BY id LIMIT 1", (ingredient_id,)).fetchone()
            if row is None:
                conn.execute("INSERT INTO shopping_list (ingredient_id, cantidad_gramos, source, plan_semana, plan_gramos) "
                             "VALUES (?, ?, 'planificador', ?, ?)", (ingredient_id, gramos, semana, gramos))
                nuevos += 1
                continue
            previo = (row["plan_gramos"] or 0) if row["plan_semana"] == semana else 0
            cantidad = max(0, (row["cantidad_gramos"] or 0) - previo + gramos)
            source = row["source"] if row["source"] == "planificador" else "mixto"
            conn.execute("UPDATE shopping_list SET cantidad_gramos=?, plan_semana=?, plan_gramos=?, source=? WHERE id=?",
                         (cantidad, semana, gramos, source, row["id"]))
            actualizados += 1
        # Lo que esa semana ya no pide: se descuenta (y se quita si solo venía del plan)
        quedan = list(totales) or [-1]
        for row in conn.execute(f"SELECT * FROM shopping_list WHERE plan_semana=? AND ingredient_id NOT IN ({','.join('?' * len(quedan))})",
                                (semana, *quedan)).fetchall():
            cantidad = max(0, (row["cantidad_gramos"] or 0) - (row["plan_gramos"] or 0))
            if row["source"] == "planificador" or cantidad <= 0:
                conn.execute("DELETE FROM shopping_list WHERE id=?", (row["id"],))
            else:
                conn.execute("UPDATE shopping_list SET cantidad_gramos=?, plan_semana=NULL, plan_gramos=NULL WHERE id=?", (cantidad, row["id"]))
    return {"status": "success", "added": nuevos + actualizados, "nuevos": nuevos, "actualizados": actualizados}

@app.get("/api/shopping-list/export/{semana}")
def export_week_shopping_list(semana: Semana, formato: str = "txt"):
    """Lista de la compra de la semana (según el plan y la ración real de cada
    plato), agrupada por categoría. formato: txt | csv | json."""
    import csv
    import io
    from fastapi.responses import PlainTextResponse, Response
    with get_db() as conn:
        totales = _week_ingredient_totals(conn, semana)
        info = {r["id"]: r for r in conn.execute("SELECT id, nombre, categoria, gramos_por_unidad, unidad_nombre FROM ingredients")}
    filas = sorted(
        ({"categoria": info[i]["categoria"], "ingrediente": info[i]["nombre"], "gramos": g,
          "unidades": round(g / info[i]["gramos_por_unidad"], 1) if info[i]["gramos_por_unidad"] else None,
          "unidad": info[i]["unidad_nombre"]} for i, g in totales.items() if i in info),
        key=lambda f: (f["categoria"] or "", f["ingrediente"].lower()))
    nombre = f"lista-compra-{semana}"
    if formato == "json":
        return {"semana": semana, "items": filas}
    if formato == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["categoria", "ingrediente", "gramos", "unidades", "unidad"])
        w.writeheader()
        w.writerows(filas)
        return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{nombre}.csv"'})
    lineas = [f"Lista de la compra · semana del {semana}", ""]
    actual = None
    for f in filas:
        if f["categoria"] != actual:
            actual = f["categoria"]
            lineas += ["", f"{(actual or 'Otros').upper()}"]
        extra = f" (≈ {f['unidades']:g} {f['unidad'] or 'ud.'})" if f["unidades"] else ""
        lineas.append(f"[ ] {f['ingrediente']}: {f['gramos']} g{extra}")
    if not filas:
        lineas.append("El plan de esta semana está vacío.")
    return PlainTextResponse("\n".join(lineas) + "\n",
                             headers={"Content-Disposition": f'attachment; filename="{nombre}.txt"'})


@app.patch("/api/shopping-list/{item_id}")
def update_shopping_item(item_id: int, data: ShoppingItemUpdate):
    with get_db() as conn:
        cursor = conn.cursor()
        if data.cantidad_gramos is not None:
            cursor.execute("UPDATE shopping_list SET cantidad_gramos=? WHERE id=?", (data.cantidad_gramos, item_id))
        if data.comprado is not None:
            cursor.execute("UPDATE shopping_list SET comprado=? WHERE id=?", (int(data.comprado), item_id))
        conn.commit()
    return {"status": "success"}

@app.delete("/api/shopping-list/{item_id}")
def delete_shopping_item(item_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM shopping_list WHERE id=?", (item_id,))
        conn.commit()
    return {"status": "success"}

# ─────────────────────────────────────────────
# Planificador semanal
# ─────────────────────────────────────────────
@app.get("/api/weekly-plan/{semana}")
def get_weekly_plan(semana: Semana):
    with get_db() as conn:
        rows = conn.execute('''
            SELECT wp.id, wp.dia, wp.franja, wp.is_fixed, wp.gramos_racion,
                   m.id as meal_id, m.nombre, m.image_url, m.gramos_recomendados
            FROM weekly_plan wp LEFT JOIN meals m ON m.id = wp.meal_id
            WHERE wp.semana = ?
        ''', (semana,)).fetchall()
    plan = []
    for r in rows:
        row = dict(r)
        row["gramos_mostrados"] = row["gramos_racion"] if row["gramos_racion"] is not None else row["gramos_recomendados"]
        plan.append(row)
    return {"plan": plan}

@app.get("/api/weekly-plan/{semana}/nutricion")
def get_weekly_plan_nutrition(semana: Semana):
    """Totales por día (todos los platos de cada comida) + objetivos del perfil."""
    with get_db() as conn:
        state = _plan_state(conn, semana)
    dias = {d: {k: info["total"][k] for k in ("kcal", "proteinas", "carbohidratos", "grasas", "azucares", "sal")}
            for d, info in state["dias"].items()}
    return {"semana": semana, "dias": dias, "targets": state["targets"],
            "semana_total": state["semana_total"], "semana_progreso": state["semana_progreso"]}

@app.delete("/api/weekly-plan/{semana}/clear")
def clear_week(semana: Semana):
    with get_db() as conn:
        conn.execute("DELETE FROM plan_items WHERE plan_id IN (SELECT id FROM weekly_plan WHERE semana=? AND is_fixed=0)", (semana,))
        conn.execute("UPDATE weekly_plan SET meal_id=NULL, gramos_racion=NULL, rol=NULL WHERE semana=? AND is_fixed=0", (semana,))
    return {"status": "success"}

@app.post("/api/weekly-plan/assign")
def assign_weekly_plan(payload: WeeklyPlanAssign):
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM meals WHERE id=?", (payload.meal_id,)).fetchone():
            raise HTTPException(status_code=422, detail="Ese plato no existe")
        # Asignacion manual: se usa la racion estandar de catalogo (sin
        # racion personalizada), hasta que el generador la recalcule.
        conn.execute('''
            INSERT INTO weekly_plan (semana, dia, franja, meal_id, is_fixed, gramos_racion)
            VALUES (?, ?, ?, ?, ?, NULL)
            ON CONFLICT(semana, dia, franja) DO UPDATE SET meal_id=excluded.meal_id, is_fixed=excluded.is_fixed, gramos_racion=NULL
        ''', (payload.semana, payload.dia, payload.franja, payload.meal_id, int(payload.is_fixed)))
        conn.execute("INSERT INTO meal_usage_log (meal_id, semana) VALUES (?, ?)", (payload.meal_id, payload.semana))
        conn.commit()
    return {"status": "success"}

@app.patch("/api/weekly-plan/{plan_id}/toggle-fixed")
def toggle_fixed(plan_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT is_fixed FROM weekly_plan WHERE id=?", (plan_id,)).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": "No encontrado"})
        new_val = 0 if row["is_fixed"] else 1
        conn.execute("UPDATE weekly_plan SET is_fixed=? WHERE id=?", (new_val, plan_id))
        conn.commit()
    return {"status": "success", "is_fixed": bool(new_val)}

@app.delete("/api/weekly-plan/{plan_id}")
def clear_weekly_plan_cell(plan_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM plan_items WHERE plan_id=?", (plan_id,))
        conn.execute("UPDATE weekly_plan SET meal_id=NULL, is_fixed=0, gramos_racion=NULL, rol=NULL WHERE id=?", (plan_id,))
    return {"status": "success"}

@app.post("/api/weekly-plan/generate")
def generate_weekly_plan(payload: GenerateWeekRequest):
    with get_db() as conn:
        _sync_franjas(conn)
        profile_row = conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone()
        targets = calculate_targets(dict(profile_row))
        catalogo = _build_meal_catalog(conn)
        if not any(catalogo.values()):
            raise HTTPException(status_code=422, detail="Aún no tienes platos: añade unos cuantos en «Platos» y vuelve a generar la semana.")
        week_state = _build_week_state(conn, payload.semana, catalogo)

        fixed = conn.execute(
            "SELECT dia, franja, meal_id, gramos_racion FROM weekly_plan WHERE semana=? AND is_fixed=1", (payload.semana,)
        ).fetchall()
        fixed_by_day = {}
        for r in fixed:
            fixed_by_day.setdefault(r["dia"], {})[r["franja"]] = r
        # Platos adicionales ya planificados (ensalada, postre...): se respetan y suman al día
        extras_by_day: dict[str, list] = {}
        for r in conn.execute("""SELECT wp.dia, pi.meal_id, pi.gramos_racion FROM plan_items pi
                                 JOIN weekly_plan wp ON wp.id = pi.plan_id WHERE wp.semana=?""", (payload.semana,)):
            extras_by_day.setdefault(r["dia"], []).append(r)

        main_slots_remaining = sum(
            1 for dia2 in DIAS_SEMANA for franja2 in payload.franjas
            if franja2 in ("comida", "cena") and franja2 not in fixed_by_day.get(dia2, {}) and franja_en_dia(franja2, dia2)
        ) or 1

        objetivo = {k: targets[TARGET_KEYS[k]] for k in MACROS}
        for dia in DIAS_SEMANA:
            dia_fixed = fixed_by_day.get(dia, {})
            llevado = dict.fromkeys(MACROS, 0.0)  # lo que ya suma el día (fijas, extras y lo elegido)
            elegidos = []  # (franja, plato, gramos) generados hoy: se reajustan al final
            for ex in extras_by_day.get(dia, []):
                em = catalogo.get(ex["meal_id"])
                if em:
                    g = ex["gramos_racion"] if ex["gramos_racion"] is not None else em["gramos_base"]
                    for k, v in _macros_de(em, g).items():
                        llevado[k] += v
            pendientes = []
            for franja in payload.franjas:
                if not franja_en_dia(franja, dia):  # desactivada ese día: ni se genera ni cuenta
                    continue
                if franja in dia_fixed:
                    fixed_row = dia_fixed[franja]
                    fm = catalogo.get(fixed_row["meal_id"])
                    if fm:
                        gramos_fija = fixed_row["gramos_racion"] if fixed_row["gramos_racion"] is not None else fm["gramos_base"]
                        for k, v in _macros_de(fm, gramos_fija).items():
                            llevado[k] += v
                else:
                    pendientes.append(franja)

            peso_restante = sum(SLOT_WEIGHTS_BASE.get(f, 0.25) for f in pendientes) or 1.0

            for franja in pendientes:
                target = _compute_slot_targets({k: objetivo[k] - llevado[k] for k in MACROS}, peso_restante, franja)

                candidates = [m for m in catalogo.values() if m["franja"] == _catalogo_de(franja)]
                if franja in ("comida", "cena"):
                    filtered = [m for m in candidates if m["id"] not in week_state["used_main"]]
                else:
                    filtered = [m for m in candidates if m["id"] not in week_state["used_side"]]
                candidates = filtered or candidates
                if not candidates:
                    if franja in ("comida", "cena"):
                        main_slots_remaining = max(main_slots_remaining - 1, 1)
                    peso_restante = max(peso_restante - SLOT_WEIGHTS_BASE.get(franja, 0.25), 0.0001)
                    continue

                scored = sorted(
                    candidates,
                    key=lambda m: _score_candidate(m, target, week_state, franja, dia, main_slots_remaining),
                    reverse=True,
                )
                top = scored[:min(3, len(scored))]
                weights = [max(0.05, 1.0 - 0.3 * i) for i in range(len(top))]
                chosen = random.choices(top, weights=weights, k=1)[0]

                gramos_racion, _, _ = _gramos_racion_para_objetivo(chosen, target["kcal"])
                elegidos.append([franja, chosen, gramos_racion])

                if franja in ("comida", "cena"):
                    week_state["used_main"].add(chosen["id"])
                    main_slots_remaining = max(main_slots_remaining - 1, 1)
                else:
                    week_state["used_side"].add(chosen["id"])
                    week_state["used_side_counts"][chosen["id"]] = week_state["used_side_counts"].get(chosen["id"], 0) + 1
                    week_state["side_days"].setdefault(chosen["id"], set()).add(DIAS_SEMANA.index(dia))

                for g in chosen["groups"]:
                    week_state["group_counts"][g] = week_state["group_counts"].get(g, 0) + 1
                day_groups = week_state["day_group_counts"].setdefault(dia, {})
                for g in chosen["groups"]:
                    day_groups[g] = day_groups.get(g, 0) + 1

                week_state["recent_usage"][chosen["id"]] = week_state["recent_usage"].get(chosen["id"], 0) + 1

                for k, v in _macros_de(chosen, gramos_racion).items():
                    llevado[k] += v
                peso_restante = max(peso_restante - SLOT_WEIGHTS_BASE.get(franja, 0.25), 0.0001)

            _ajustar_raciones_dia(elegidos, objetivo["kcal"] - llevado["kcal"])
            for franja, chosen, gramos_racion in elegidos:
                conn.execute('''
                    INSERT INTO weekly_plan (semana, dia, franja, meal_id, is_fixed, gramos_racion)
                    VALUES (?, ?, ?, ?, 0, ?)
                    ON CONFLICT(semana, dia, franja) DO UPDATE SET meal_id=excluded.meal_id, gramos_racion=excluded.gramos_racion
                ''', (payload.semana, dia, franja, chosen["id"], gramos_racion))
                conn.execute("INSERT INTO meal_usage_log (meal_id, semana) VALUES (?, ?)", (chosen["id"], payload.semana))

        conn.commit()
    return {"status": "success"}

@app.post("/api/weekly-plan/{plan_id}/regenerate")
def regenerate_cell(plan_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM weekly_plan WHERE id=?", (plan_id,)).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": "Celda no encontrada"})

        semana, dia, franja = row["semana"], row["dia"], row["franja"]
        _sync_franjas(conn)
        profile_row = conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone()
        targets = calculate_targets(dict(profile_row))
        catalogo = _build_meal_catalog(conn)
        week_state = _build_week_state(conn, semana, catalogo, exclude_plan_id=plan_id)

        all_day_rows = conn.execute("SELECT * FROM weekly_plan WHERE semana=? AND dia=?", (semana, dia)).fetchall()
        peso_total_dia = sum(SLOT_WEIGHTS_BASE.get(r["franja"], 0.25) for r in all_day_rows)
        otros = dict.fromkeys(MACROS, 0.0)
        peso_otros_llenos = 0.0
        for r in all_day_rows:
            if r["id"] == plan_id:
                continue
            if r["meal_id"]:
                m = catalogo.get(r["meal_id"])
                if m:
                    gramos_otro = r["gramos_racion"] if r["gramos_racion"] is not None else m["gramos_base"]
                    for k, v in _macros_de(m, gramos_otro).items():
                        otros[k] += v
                peso_otros_llenos += SLOT_WEIGHTS_BASE.get(r["franja"], 0.25)

        peso_restante = max(peso_total_dia - peso_otros_llenos, SLOT_WEIGHTS_BASE.get(franja, 0.25))
        target = _compute_slot_targets({k: targets[TARGET_KEYS[k]] - otros[k] for k in MACROS}, peso_restante, franja)
        slot_kcal_target = target["kcal"]

        main_slots_remaining = conn.execute("""
            SELECT COUNT(*) as c FROM weekly_plan
            WHERE semana=? AND franja IN ('comida','cena') AND (meal_id IS NULL OR id=?)
        """, (semana, plan_id)).fetchone()["c"] or 1

        candidates = [m for m in catalogo.values() if m["franja"] == _catalogo_de(franja) and m["id"] != row["meal_id"]]
        if franja in ("comida", "cena"):
            filtered = [m for m in candidates if m["id"] not in week_state["used_main"]]
        else:
            filtered = [m for m in candidates if m["id"] not in week_state["used_side"]]
        candidates = filtered or candidates
        if not candidates:
            return JSONResponse(status_code=404, content={"error": "No hay alternativas para esta franja"})

        best = max(candidates, key=lambda m: _score_candidate(m, target, week_state, franja, dia, main_slots_remaining))
        gramos_racion, _, _ = _gramos_racion_para_objetivo(best, slot_kcal_target)

        conn.execute("UPDATE weekly_plan SET meal_id=?, gramos_racion=? WHERE id=?", (best["id"], gramos_racion, plan_id))
        conn.execute("INSERT INTO meal_usage_log (meal_id, semana) VALUES (?, ?)", (best["id"], semana))
        conn.commit()
    return {"status": "success", "meal_id": best["id"], "nombre": best["nombre"], "gramos_racion": gramos_racion}

# ─────────────────────────────────────────────
# Plan completo: platos → comida → día → semana (con progreso y objetivos)
# ─────────────────────────────────────────────
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
        return [{"clave": f, "nombre": f.capitalize(), "fraccion": FRANJA_FRACCION[f], "activa": 1, "catalogo": f} for f in FRANJA_ORDEN]
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


def _plato(index: dict, meal_id: int, gramos_custom, kind: str, plan_id: int, item_id=None, rol=None) -> dict | None:
    m = index.get(meal_id)
    if not m:
        return None
    gramos = gramos_custom if gramos_custom is not None else m["gramos_base"]
    macros = nu.racion(m["total"], m["gramos_receta"], gramos)
    return {
        "kind": kind, "plan_id": plan_id, "item_id": item_id, "meal_id": meal_id, "nombre": m["nombre"], "rol": rol,
        "image_url": m["image_url"], "gramos": round(gramos or 0), "gramos_estandar": round(m["gramos_base"] or 0),
        "personalizado": gramos_custom is not None, "macros": nu.redondear(macros), "_raw": macros,
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
    return (f"La grasa va a {round(media['grasas'])} g/día y tu objetivo es {round(objetivo['grasas'])} g "
            f"({round(targets.get('grasa_pct', 0))} % de las kcal), pero tus comidas y cenas tienen de media un "
            f"{round(media_pct)} % de sus kcal en grasa: el generador ya elige las más magras. Para acercarte, añade platos con menos "
            f"aceite, queso o fritos, o sube el % de grasa en tu perfil. Las más magras que tienes: "
            + ", ".join(m["nombre"] for m in magros) + ".")


def _plan_state(conn, semana: str) -> dict:
    franjas = _sync_franjas(conn)
    index = _recipe_index(conn)
    profile = dict(conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone())
    targets = calculate_targets(profile)
    objetivo = nu.objetivos_comparables(targets)
    slots = conn.execute("SELECT * FROM weekly_plan WHERE semana=?", (semana,)).fetchall()
    extras = {}
    for it in conn.execute("""
        SELECT pi.* FROM plan_items pi JOIN weekly_plan wp ON wp.id = pi.plan_id
        WHERE wp.semana = ? ORDER BY pi.orden, pi.id
    """, (semana,)):
        extras.setdefault(it["plan_id"], []).append(it)

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
            "plan_id": s["id"], "franja": s["franja"], "is_fixed": bool(s["is_fixed"]),
            "platos": platos, "total": nu.redondear(total),
        }
        dias[s["dia"]]["_total"] = nu.sumar(dias[s["dia"]]["_total"], total)

    semana_total = nu.sumar()
    out_dias = {}
    for d, info in dias.items():
        total = info["_total"]
        semana_total = nu.sumar(semana_total, total)
        ordenadas = dict(sorted(info["comidas"].items(), key=lambda kv: FRANJA_ORDEN.index(kv[0]) if kv[0] in FRANJA_ORDEN else 9))
        out_dias[d] = {"comidas": ordenadas, "total": nu.redondear(total),
                       "progreso": nu.progreso(total, objetivo), "restante": nu.restante(total, objetivo)}
    objetivo_semana = {k: v * 7 for k, v in objetivo.items()}
    dias_con_comida = sum(1 for d in out_dias.values() if d["total"]["kcal"] > 0)
    return {
        "semana": semana, "targets": targets, "objetivo_dia": objetivo, "dias": out_dias,
        "semana_total": nu.redondear(semana_total), "objetivo_semana": objetivo_semana,
        "semana_progreso": nu.progreso(semana_total, objetivo_semana),
        "media_diaria": nu.redondear(nu.escalar(semana_total, 1 / dias_con_comida)) if dias_con_comida else nu.redondear(nu.sumar()),
        "dias_planificados": dias_con_comida,
        "consejo": _consejo_macros(index, nu.escalar(semana_total, 1 / dias_con_comida), objetivo, targets) if dias_con_comida >= 3 else None,
        "franjas": [{k: f[k] for k in ("clave", "nombre", "orden", "fraccion", "hora", "activa", "base", "catalogo", "dias") if k in f} for f in franjas],
    }


def _rol(row):
    try:
        return row["rol"]
    except (IndexError, KeyError):
        return None


@app.get("/api/weekly-plan/{semana}/full")
def get_weekly_plan_full(semana: Semana):
    with get_db() as conn:
        return _plan_state(conn, semana)


def _slot_id(conn, semana, dia, franja) -> int:
    conn.execute("INSERT OR IGNORE INTO weekly_plan (semana, dia, franja, meal_id, is_fixed) VALUES (?, ?, ?, NULL, 0)",
                 (semana, dia, franja))
    return conn.execute("SELECT id FROM weekly_plan WHERE semana=? AND dia=? AND franja=?", (semana, dia, franja)).fetchone()["id"]


def _check_dia_franja(dia: str, franja: str):
    if dia not in DIAS_SEMANA:
        raise HTTPException(status_code=422, detail="Día no válido")
    with get_db() as conn:
        _sync_franjas(conn)
    if franja not in FRANJA_ORDEN:
        raise HTTPException(status_code=422, detail="Franja no válida")


@app.post("/api/weekly-plan/slots")
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
            conn.execute("UPDATE weekly_plan SET meal_id=?, gramos_racion=?, rol=? WHERE id=?", (payload.meal_id, payload.gramos, payload.rol, plan_id))
            kind, item_id = "principal", None
        else:
            orden = conn.execute("SELECT COALESCE(MAX(orden), 0) + 1 AS o FROM plan_items WHERE plan_id=?", (plan_id,)).fetchone()["o"]
            item_id = conn.execute("INSERT INTO plan_items (plan_id, meal_id, gramos_racion, orden, rol) VALUES (?, ?, ?, ?, ?)",
                                   (plan_id, payload.meal_id, payload.gramos, orden, payload.rol)).lastrowid
            kind = "extra"
        conn.execute("INSERT INTO meal_usage_log (meal_id, semana) VALUES (?, ?)", (payload.meal_id, payload.semana))
    return {"status": "success", "plan_id": plan_id, "kind": kind, "item_id": item_id}


@app.post("/api/weekly-plan/{plan_id}/items")
def add_plan_item(plan_id: int, payload: PlanItemAdd):
    with get_db() as conn:
        slot = conn.execute("SELECT * FROM weekly_plan WHERE id=?", (plan_id,)).fetchone()
        if not slot:
            raise HTTPException(status_code=404, detail="Comida no encontrada")
    return add_plato_to_slot(PlanSlotAdd(semana=slot["semana"], dia=slot["dia"], franja=slot["franja"],
                                         meal_id=payload.meal_id, gramos=payload.gramos, rol=payload.rol))


@app.patch("/api/weekly-plan/{plan_id}/gramos")
def set_principal_gramos(plan_id: int, payload: GramosUpdate):
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM weekly_plan WHERE id=?", (plan_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Comida no encontrada")
        conn.execute("UPDATE weekly_plan SET gramos_racion=? WHERE id=?", (payload.gramos, plan_id))
    return {"status": "success"}


@app.patch("/api/weekly-plan/items/{item_id}")
def set_item_gramos(item_id: int, payload: GramosUpdate):
    with get_db() as conn:
        cur = conn.execute("UPDATE plan_items SET gramos_racion=? WHERE id=?", (payload.gramos, item_id))
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="Plato no encontrado")
    return {"status": "success"}


@app.delete("/api/weekly-plan/items/{item_id}")
def delete_plan_item(item_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM plan_items WHERE id=?", (item_id,))
    return {"status": "success"}


@app.get("/api/weekly-plan/{semana}/sugerencias")
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
    fraccion = 1.0
    if franja:
        vacias = [f for f in FRANJA_ORDEN if franja_en_dia(f, dia) and not dia_state["comidas"].get(f, {}).get("platos")]
        if franja not in vacias:
            vacias.append(franja)
        peso = sum(FRANJA_FRACCION.get(f, 0) for f in vacias) or 1
        fraccion = FRANJA_FRACCION.get(franja, 0.25) / peso if FRANJA_FRACCION.get(franja) else 0.15
    platos = []
    for m in index.values():
        if franja and m["franja"] != _catalogo_de(franja):
            continue
        if not m["gramos_receta"]:
            continue
        base = m["gramos_base"] or m["gramos_receta"]
        platos.append({"id": m["id"], "nombre": m["nombre"], "franja": m["franja"],
                       "densidad": nu.densidad_100g(m["total"], m["gramos_receta"]),
                       "gramos_base": base,
                       "gramos_min": max(GRAMOS_RACION_MIN_ABS, base * ESCALADO_MIN_FACTOR),
                       "gramos_max": min(GRAMOS_RACION_MAX_ABS, max(base * ESCALADO_MAX_FACTOR, GRAMOS_RACION_MIN_ABS))})
    hueco_comida = {k: v * fraccion for k, v in hueco.items()}
    return {
        "dia": dia, "franja": franja or None, "restante_dia": hueco, "hueco": {k: round(v, 1) for k, v in hueco_comida.items()},
        "platos": nu.sugerir_platos(hueco, platos, n=n, fraccion_dia=fraccion),
        "ingredientes": nu.sugerir_ingredientes(hueco_comida, ingredientes, n=n),
    }


# ─────────────────────────────────────────────
# Perfil de usuario
# ─────────────────────────────────────────────
@app.get("/api/profile")
def get_profile():
    with get_db() as conn:
        row = conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone()
    profile = dict(row)
    profile["objetivo"] = nu.normalizar_objetivo(profile["objetivo"])
    profile["targets"] = calculate_targets(profile)
    profile["niveles_actividad"] = {str(k): v for k, v in nu.NIVELES_ACTIVIDAD.items()}
    profile["objetivos"] = nu.OBJETIVOS
    return profile

@app.patch("/api/profile")
def update_profile(data: UserProfileIn):
    with get_db() as conn:
        objetivo = nu.normalizar_objetivo(data.objetivo)
        conn.execute('''
            UPDATE user_profile SET edad=?, peso_kg=?, altura_cm=?, sexo=?, nivel_actividad=?, objetivo=?, proteina_g_kg=?,
                   grasa_pct=?, ajuste_pct=?
            WHERE id=1
        ''', (data.edad, data.peso_kg, data.altura_cm, data.sexo, data.nivel_actividad, objetivo, data.proteina_g_kg,
              data.grasa_pct if data.grasa_pct is not None else nu.GRASA_PCT_DEFECTO, data.ajuste_pct))
    return {"status": "success", "targets": calculate_targets({**data.model_dump(), "objetivo": objetivo})}

@app.get("/")
def comidas_page(request: Request):
    return render(request, "comidas.html", "comidas", "Comidas")


# Gestión masiva y planificación ampliada (importan utilidades de este módulo, por eso van al final)
from .bulk import router as bulk_router  # noqa: E402
from .planner import router as planner_router  # noqa: E402

app.include_router(bulk_router)
app.include_router(planner_router)

# IMPORTANTE: al final, igual que en estudio/main.py
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
