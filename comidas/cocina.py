"""comidas/cocina.py — modo cocina (P-10): la receta paso a paso con las cantidades de tu ración, tiempos de cada paso,
partir un texto pegado en pasos y «marcar como cocinado» (tabla `cocinados`, migración 5)."""

import json
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import pasos as P
from .database import get_db

router = APIRouter()


class PartirIn(BaseModel):
    texto: str = Field(default="", max_length=100_000)


class CocinadoIn(BaseModel):
    meal_id: int = Field(ge=1)
    plan_id: int | None = Field(default=None, ge=1)
    item_id: int | None = Field(default=None, ge=1)
    gramos: float | None = Field(default=None, gt=0, le=10_000)


@router.post("/api/meals/pasos/partir")
def partir_pasos(data: PartirIn):
    """Vista previa del editor: el texto (pegado o escrito) partido en pasos, con los tiempos que se detectan."""
    return {"pasos": P.describir(P.partir(data.texto))}


@router.get("/api/meals/{meal_id}/cocina")
def modo_cocina(meal_id: int, gramos: float | None = Query(default=None, gt=0, le=10_000)):
    """La receta para cocinarla: ingredientes escalados a la ración (`gramos`; sin él, la ración estándar del plato) y
    cada paso con sus tiempos y los ingredientes que nombra (índices en `ingredientes`)."""
    with get_db() as conn:
        meal = conn.execute("SELECT * FROM meals WHERE id=?", (meal_id,)).fetchone()
        if not meal:
            raise HTTPException(status_code=404, detail="Plato no encontrado")
        ings = conn.execute(
            """SELECT i.nombre, i.gramos_por_unidad, i.unidad_nombre, mi.gramos, mi.unidades
               FROM meal_ingredients mi JOIN ingredients i ON i.id = mi.ingredient_id
               WHERE mi.meal_id=? ORDER BY mi.id""",
            (meal_id,),
        ).fetchall()
    gramos_receta = sum(r["gramos"] or 0 for r in ings)
    estandar = gramos_receta if meal["es_racion_unica"] else (meal["gramos_recomendados"] or gramos_receta)
    racion = gramos or estandar
    factor = racion / gramos_receta if gramos_receta else 1
    ingredientes = []
    for r in ings:
        g = (r["gramos"] or 0) * factor
        ud = None
        if r["gramos_por_unidad"]:
            ud = round(g / r["gramos_por_unidad"], 1)
        ingredientes.append(
            {
                "nombre": r["nombre"],
                "gramos": round(g) if g >= 10 else round(g, 1),
                "unidades": ud,
                "unidad": r["unidad_nombre"],
            }
        )
    lista = json.loads(meal["instrucciones"] or "[]")
    return {
        "meal_id": meal_id,
        "nombre": meal["nombre"],
        "image_url": meal["image_url"],
        "tiempo_min": meal["tiempo_preparacion_min"],
        "gramos": round(racion),
        "gramos_estandar": round(estandar),
        "factor": round(factor, 4),
        "ingredientes": ingredientes,
        "pasos": P.describir(lista, [i["nombre"] for i in ingredientes]),
    }


@router.post("/api/cocinados")
def marcar_cocinado(data: CocinadoIn):
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM meals WHERE id=?", (data.meal_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Plato no encontrado")
        if data.plan_id and not conn.execute("SELECT 1 FROM weekly_plan WHERE id=?", (data.plan_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Comida no encontrada")
        new_id = conn.execute(
            "INSERT INTO cocinados (meal_id, plan_id, item_id, gramos, fecha) VALUES (?, ?, ?, ?, ?)",
            (data.meal_id, data.plan_id, data.item_id, data.gramos, date.today().isoformat()),
        ).lastrowid
    return {"status": "success", "id": new_id}


@router.delete("/api/cocinados/{cocinado_id}")
def desmarcar_cocinado(cocinado_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM cocinados WHERE id=?", (cocinado_id,))
    return {"status": "success"}


def cocinados_de(conn, plan_ids: list[int]) -> dict[tuple[int, int | None], int]:
    """(plan_id, item_id) → id del último «cocinado» de esas comidas (para marcarlas en el plan)."""
    if not plan_ids:
        return {}
    out: dict[tuple[int, int | None], int] = {}
    for r in conn.execute(
        f"SELECT id, plan_id, item_id FROM cocinados WHERE plan_id IN ({','.join('?' * len(plan_ids))}) ORDER BY id",
        plan_ids,
    ):
        out[(r["plan_id"], r["item_id"])] = r["id"]
    return out
