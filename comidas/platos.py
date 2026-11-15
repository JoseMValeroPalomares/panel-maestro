"""comidas/platos.py — platos del catálogo: recetas, ración estándar sugerida y fotos (en caché local)."""

import json

from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import JSONResponse

from core import config

from . import nutrition as nu
from .bulk import Selection, meals_delete
from .core import (
    MealIn,
    MealIngredientIn,
    SuggestGramosRequest,
    _recipe_index,
    _resolve_ingredients,
    _suggest_gramos_recomendados,
    _write_meal_ingredients,
)
from .database import get_db

router = APIRouter()

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


def find_meal_photo(meal_id: int, nombre: str) -> None:
    """Plato nuevo sin foto: busca una por su nombre y la guarda en local (en segundo plano, tras crearlo).
    Si el usuario ya puso una mientras tanto, no la pisa."""
    from app.scraper import cache_thumbnail, search_images

    for o in search_images(f"{nombre} plato receta", n=6):
        local = cache_thumbnail(o["image"], str(config.UPLOADS_DIR / "thumbs"))
        if local:
            with get_db() as conn:
                conn.execute(
                    "UPDATE meals SET image_url=?, image_source='busqueda' WHERE id=? AND (image_url IS NULL OR image_url='')",
                    (local, meal_id),
                )
            return


def _gramos_estandar(conn, meal: MealIn, resolved: list[dict]) -> float:
    """La ración estándar que se guarda: la indicada o, si falta (y no es ración única), la sugerida."""
    gramos_rec = meal.gramos_recomendados
    if not meal.es_racion_unica and (not gramos_rec or gramos_rec <= 0):
        gramos_rec = _suggest_gramos_recomendados(
            conn,
            [MealIngredientIn(ingredient_id=r["ingredient_id"], gramos=r["gramos"]) for r in resolved],
            meal.franja,
        )
    return gramos_rec


def _valores_plato(meal: MealIn, gramos_rec) -> tuple:
    """Columnas de `meals` en el orden de INSERT y UPDATE (la foto ya en caché local)."""
    return (
        meal.nombre,
        meal.franja,
        meal.tags,
        meal.tiempo_preparacion_min,
        gramos_rec,
        int(meal.es_racion_unica),
        json.dumps(meal.instrucciones),
        _cache_meal_image(meal.image_url),
        meal.image_source,
    )


def _ingrediente_de_ficha(ing: dict) -> dict:
    aporte = nu.macros_por_cantidad(ing, ing["gramos"])
    return {
        "id": ing["id"],
        "nombre": ing["nombre"],
        "gramos": ing["gramos"],
        "unidades": ing["unidades"],
        "unidad_nombre": ing["unidad_nombre"],
        "gramos_por_unidad": ing["gramos_por_unidad"],
        "aporte": nu.redondear(aporte),
        "kcal_check": nu.comprobar_kcal(
            ing["kcal_100g"], ing["proteinas_100g"], ing["carbohidratos_100g"], ing["grasas_100g"]
        ),
    }


@router.get("/api/photo-search")
def photo_search(q: str = Query(..., min_length=2, max_length=120)):
    """Fotos candidatas para un plato (búsqueda de imágenes en la web). Se eligen en el formulario del plato; al
    guardar, la elegida se descarga a la caché local (_cache_meal_image) y deja de depender de internet."""
    from app.scraper import search_images

    return {"options": search_images(f"{q} plato receta", n=12)}


@router.post("/api/meals/suggest-gramos")
def suggest_gramos(payload: SuggestGramosRequest):
    with get_db() as conn:
        resolved = _resolve_ingredients(conn, payload.ingredientes)
        suggestion = _suggest_gramos_recomendados(
            conn,
            [MealIngredientIn(ingredient_id=r["ingredient_id"], gramos=r["gramos"]) for r in resolved],
            payload.franja,
        )
    return {"gramos_recomendados": suggestion}


@router.get("/api/meals")
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


@router.get("/api/meals/{meal_id}")
def get_meal(meal_id: int):
    with get_db() as conn:
        meal = conn.execute("SELECT * FROM meals WHERE id=?", (meal_id,)).fetchone()
        if not meal:
            return JSONResponse(status_code=404, content={"error": "Comida no encontrada"})
        ing_rows = conn.execute(
            """
            SELECT i.*, mi.gramos, mi.unidades
            FROM meal_ingredients mi JOIN ingredients i ON i.id = mi.ingredient_id
            WHERE mi.meal_id = ? ORDER BY mi.id
        """,
            (meal_id,),
        ).fetchall()

    ingredientes = [dict(r) for r in ing_rows]
    total, gramos_totales = nu.receta(ingredientes)
    es_racion_unica = bool(meal["es_racion_unica"])
    gramos_rec = gramos_totales if es_racion_unica else (meal["gramos_recomendados"] or 0)

    result = dict(meal)
    result["ingredientes"] = [_ingrediente_de_ficha(ing) for ing in ingredientes]
    result["instrucciones"] = json.loads(meal["instrucciones"] or "[]")
    result["gramos_totales_receta"] = round(gramos_totales, 1)
    result["gramos_recomendados"] = gramos_rec
    result["es_racion_unica"] = es_racion_unica
    result["nutricion_total_receta"] = nu.redondear(total)  # suma literal
    result["nutricion_por_100g"] = nu.redondear(nu.densidad_100g(total, gramos_totales))
    result["nutricion_total"] = nu.redondear(nu.racion(total, gramos_totales, gramos_rec))  # ración estándar
    result["kcal_check"] = nu.comprobar_kcal(total["kcal"], total["proteinas"], total["carbohidratos"], total["grasas"])
    return result


@router.post("/api/meals")
def create_meal(meal: MealIn, background_tasks: BackgroundTasks):
    with get_db() as conn:
        resolved = _resolve_ingredients(conn, meal.ingredientes)
        gramos_rec = _gramos_estandar(conn, meal, resolved)
        cursor = conn.execute(
            """
            INSERT INTO meals (nombre, franja, tags, tiempo_preparacion_min, gramos_recomendados, es_racion_unica, instrucciones, image_url, image_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            _valores_plato(meal, gramos_rec),
        )
        meal_id = cursor.lastrowid
        _write_meal_ingredients(conn, meal_id, resolved)
        con_foto = bool(conn.execute("SELECT image_url FROM meals WHERE id=?", (meal_id,)).fetchone()["image_url"])
    if not con_foto and not config.DISABLE_SCHEDULER:  # en pruebas (sin programador) no se sale a internet
        background_tasks.add_task(find_meal_photo, meal_id, meal.nombre)
    return {"status": "success", "id": meal_id, "gramos_recomendados": gramos_rec}


@router.patch("/api/meals/{meal_id}")
def update_meal(meal_id: int, meal: MealIn):
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM meals WHERE id=?", (meal_id,)).fetchone():
            return JSONResponse(status_code=404, content={"error": "Comida no encontrada"})
        resolved = _resolve_ingredients(conn, meal.ingredientes)
        gramos_rec = _gramos_estandar(conn, meal, resolved)
        conn.execute(
            """
            UPDATE meals SET nombre=?, franja=?, tags=?, tiempo_preparacion_min=?, gramos_recomendados=?, es_racion_unica=?,
                instrucciones=?, image_url=?, image_source=?
            WHERE id=?
        """,
            (*_valores_plato(meal, gramos_rec), meal_id),
        )
        _write_meal_ingredients(conn, meal_id, resolved)
    return {"status": "success", "gramos_recomendados": gramos_rec}


@router.delete("/api/meals/{meal_id}")
def delete_meal(meal_id: int):
    """A la papelera, como el borrado en lote (el plan y la compra se liberan y se recuperan al restaurar)."""
    return meals_delete(Selection(ids=[meal_id]))
