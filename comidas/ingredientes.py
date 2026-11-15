"""comidas/ingredientes.py — catálogo de ingredientes (macros por 100 g y gramos por unidad)."""

import sqlite3

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from . import nutrition as nu
from .bulk import Selection, ingredients_delete
from .core import INGREDIENT_FIELDS, IngredientIn
from .database import get_db

router = APIRouter()


def _ingredient_out(row) -> dict:
    d = dict(row)
    d["kcal_check"] = nu.comprobar_kcal(d["kcal_100g"], d["proteinas_100g"], d["carbohidratos_100g"], d["grasas_100g"])
    return d


@router.get("/api/ingredients")
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


@router.get("/api/ingredients/validation")
def validate_ingredients():
    """Ingredientes cuyas kcal no cuadran con 4·P + 4·C + 9·G (posible error de datos)."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM ingredients ORDER BY nombre").fetchall()
    bad = [i for i in (_ingredient_out(r) for r in rows) if not i["kcal_check"]["ok"]]
    return {"total": len(rows), "inconsistentes": bad}


@router.post("/api/ingredients")
def create_ingredient(data: IngredientIn):
    values = [getattr(data, f) for f in INGREDIENT_FIELDS]
    with get_db() as conn:
        try:
            cursor = conn.execute(
                f"INSERT INTO ingredients ({', '.join(INGREDIENT_FIELDS)}) VALUES ({', '.join('?' * len(INGREDIENT_FIELDS))})",
                values,
            )
            new_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            return JSONResponse(status_code=409, content={"error": "Ese ingrediente ya existe"})
    check = nu.comprobar_kcal(data.kcal_100g, data.proteinas_100g, data.carbohidratos_100g, data.grasas_100g)
    return {"status": "success", "id": new_id, "kcal_check": check}


@router.patch("/api/ingredients/{ingredient_id}")
def update_ingredient(ingredient_id: int, data: IngredientIn):
    with get_db() as conn:
        try:
            conn.execute(
                f"UPDATE ingredients SET {', '.join(f + '=?' for f in INGREDIENT_FIELDS)} WHERE id=?",
                [getattr(data, f) for f in INGREDIENT_FIELDS] + [ingredient_id],
            )
        except sqlite3.IntegrityError:
            return JSONResponse(status_code=409, content={"error": "Ya existe otro ingrediente con ese nombre"})
        # Si cambian los g/unidad, se recalculan los gramos de las recetas que lo usan por unidades
        if data.gramos_por_unidad:
            conn.execute(
                "UPDATE meal_ingredients SET gramos = unidades * ? WHERE ingredient_id=? AND unidades IS NOT NULL",
                (data.gramos_por_unidad, ingredient_id),
            )
    check = nu.comprobar_kcal(data.kcal_100g, data.proteinas_100g, data.carbohidratos_100g, data.grasas_100g)
    return {"status": "success", "kcal_check": check}


@router.delete("/api/ingredients/{ingredient_id}")
def delete_ingredient(ingredient_id: int):
    """A la papelera, como el borrado en lote (la compra conserva la línea como texto libre)."""
    return ingredients_delete(Selection(ids=[ingredient_id]))
