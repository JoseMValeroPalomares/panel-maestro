"""comidas/compra.py — lista de la compra: a mano, desde un plato o desde el plan de la semana, y su exportación."""

import csv
import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, Response

from .core import Semana, ShoppingItemIn, ShoppingItemUpdate, _recipe_index
from .database import get_db

router = APIRouter()


def _add_ingredient_to_shopping_list(conn, ingredient_id: int, gramos: float, source: str, source_meal_id: int = None):
    existing = conn.execute(
        "SELECT id, cantidad_gramos, source FROM shopping_list WHERE ingredient_id=?", (ingredient_id,)
    ).fetchone()
    if existing:
        new_qty = existing["cantidad_gramos"] + gramos
        new_source = existing["source"] if existing["source"] == source else "mixto"
        conn.execute(
            "UPDATE shopping_list SET cantidad_gramos=?, source=?, source_meal_id=? WHERE id=?",
            (new_qty, new_source, source_meal_id if new_source != "mixto" else None, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO shopping_list (ingredient_id, cantidad_gramos, source, source_meal_id) VALUES (?, ?, ?, ?)",
            (ingredient_id, gramos, source, source_meal_id),
        )


def _week_ingredient_totals(conn, semana: str) -> dict[int, float]:
    """Gramos de cada ingrediente para la semana: cada plato (principal o extra)
    escala su receta a la ración planificada (antes se sumaba la receta entera)."""
    index = _recipe_index(conn)
    porciones = []
    for r in conn.execute(
        "SELECT meal_id, gramos_racion FROM weekly_plan WHERE semana=? AND meal_id IS NOT NULL", (semana,)
    ):
        porciones.append((r["meal_id"], r["gramos_racion"]))
    for r in conn.execute(
        """SELECT pi.meal_id, pi.gramos_racion FROM plan_items pi JOIN weekly_plan wp ON wp.id = pi.plan_id
                             WHERE wp.semana=?""",
        (semana,),
    ):
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


def _sumar_semana(conn, semana: str, totales: dict[int, float]) -> tuple[int, int]:
    """Pone en la lista lo que pide la semana; devuelve (nuevos, actualizados)."""
    nuevos = actualizados = 0
    for ingredient_id, gramos in totales.items():
        row = conn.execute(
            "SELECT * FROM shopping_list WHERE ingredient_id=? ORDER BY id LIMIT 1", (ingredient_id,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO shopping_list (ingredient_id, cantidad_gramos, source, plan_semana, plan_gramos) "
                "VALUES (?, ?, 'planificador', ?, ?)",
                (ingredient_id, gramos, semana, gramos),
            )
            nuevos += 1
            continue
        previo = (row["plan_gramos"] or 0) if row["plan_semana"] == semana else 0
        cantidad = max(0, (row["cantidad_gramos"] or 0) - previo + gramos)
        source = row["source"] if row["source"] == "planificador" else "mixto"
        conn.execute(
            "UPDATE shopping_list SET cantidad_gramos=?, plan_semana=?, plan_gramos=?, source=? WHERE id=?",
            (cantidad, semana, gramos, source, row["id"]),
        )
        actualizados += 1
    return nuevos, actualizados


def _descontar_lo_que_sobra(conn, semana: str, totales: dict[int, float]) -> None:
    """Lo que esa semana ya no pide: se descuenta (y se quita si solo venía del plan)."""
    quedan = list(totales) or [-1]
    for row in conn.execute(
        f"SELECT * FROM shopping_list WHERE plan_semana=? AND ingredient_id NOT IN ({','.join('?' * len(quedan))})",
        (semana, *quedan),
    ).fetchall():
        cantidad = max(0, (row["cantidad_gramos"] or 0) - (row["plan_gramos"] or 0))
        if row["source"] == "planificador" or cantidad <= 0:
            conn.execute("DELETE FROM shopping_list WHERE id=?", (row["id"],))
        else:
            conn.execute(
                "UPDATE shopping_list SET cantidad_gramos=?, plan_semana=NULL, plan_gramos=NULL WHERE id=?",
                (cantidad, row["id"]),
            )


def _filas_semana(semana: str) -> list[dict]:
    """Lo que pide el plan de la semana, por ingrediente, ordenado por categoría y nombre."""
    with get_db() as conn:
        totales = _week_ingredient_totals(conn, semana)
        info = {
            r["id"]: r
            for r in conn.execute("SELECT id, nombre, categoria, gramos_por_unidad, unidad_nombre FROM ingredients")
        }
    return sorted(
        (
            {
                "categoria": info[i]["categoria"],
                "ingrediente": info[i]["nombre"],
                "gramos": g,
                "unidades": round(g / info[i]["gramos_por_unidad"], 1) if info[i]["gramos_por_unidad"] else None,
                "unidad": info[i]["unidad_nombre"],
            }
            for i, g in totales.items()
            if i in info
        ),
        key=lambda f: (f["categoria"] or "", f["ingrediente"].lower()),
    )


def _texto_compra(semana: str, filas: list[dict]) -> str:
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
    return "\n".join(lineas) + "\n"


@router.get("/api/shopping-list")
def get_shopping_list():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT sl.*, i.nombre as ingredient_nombre, i.categoria, i.gramos_por_unidad, i.unidad_nombre
            FROM shopping_list sl LEFT JOIN ingredients i ON i.id = sl.ingredient_id
            ORDER BY sl.created_at DESC
        """).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.post("/api/shopping-list")
def add_shopping_item(data: ShoppingItemIn):
    with get_db() as conn:
        if data.ingredient_id:
            if not conn.execute("SELECT 1 FROM ingredients WHERE id=?", (data.ingredient_id,)).fetchone():
                raise HTTPException(status_code=422, detail="Ese ingrediente no existe")
            _add_ingredient_to_shopping_list(conn, data.ingredient_id, data.cantidad_gramos, "manual")
        else:
            conn.execute(
                "INSERT INTO shopping_list (nombre_libre, cantidad_gramos, source) VALUES (?, ?, 'manual')",
                (data.nombre_libre, data.cantidad_gramos),
            )
        conn.commit()
    return {"status": "success"}


@router.delete("/api/shopping-list/done")
def clear_done_shopping_items():
    with get_db() as conn:
        conn.execute("DELETE FROM shopping_list WHERE comprado=1")
        conn.commit()
    return {"status": "success"}


@router.post("/api/shopping-list/from-meal/{meal_id}")
def add_meal_to_shopping_list(meal_id: int):
    with get_db() as conn:
        rows = conn.execute("SELECT ingredient_id, gramos FROM meal_ingredients WHERE meal_id=?", (meal_id,)).fetchall()
        for row in rows:
            _add_ingredient_to_shopping_list(conn, row["ingredient_id"], row["gramos"], "planificador", meal_id)
        conn.commit()
    return {"status": "success", "added": len(rows)}


@router.post("/api/shopping-list/from-week/{semana}")
def add_week_to_shopping_list(semana: Semana):
    """Suma a la lista lo que pide el plan de la semana (por ingrediente). Volver a
    pulsarlo no duplica: se reemplaza la parte que venía de esa semana (plan_gramos)
    y se conserva lo añadido a mano."""
    with get_db() as conn:
        totales = _week_ingredient_totals(conn, semana)
        nuevos, actualizados = _sumar_semana(conn, semana, totales)
        _descontar_lo_que_sobra(conn, semana, totales)
    return {"status": "success", "added": nuevos + actualizados, "nuevos": nuevos, "actualizados": actualizados}


@router.get("/api/shopping-list/export/{semana}")
def export_week_shopping_list(semana: Semana, formato: str = "txt"):
    """Lista de la compra de la semana (según el plan y la ración real de cada
    plato), agrupada por categoría. formato: txt | csv | json."""
    filas = _filas_semana(semana)
    nombre = f"lista-compra-{semana}"
    if formato == "json":
        return {"semana": semana, "items": filas}
    if formato == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["categoria", "ingrediente", "gramos", "unidades", "unidad"])
        w.writeheader()
        w.writerows(filas)
        return Response(
            buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{nombre}.csv"'},
        )
    return PlainTextResponse(
        _texto_compra(semana, filas), headers={"Content-Disposition": f'attachment; filename="{nombre}.txt"'}
    )


@router.patch("/api/shopping-list/{item_id}")
def update_shopping_item(item_id: int, data: ShoppingItemUpdate):
    with get_db() as conn:
        cursor = conn.cursor()
        if data.cantidad_gramos is not None:
            cursor.execute("UPDATE shopping_list SET cantidad_gramos=? WHERE id=?", (data.cantidad_gramos, item_id))
        if data.comprado is not None:
            cursor.execute("UPDATE shopping_list SET comprado=? WHERE id=?", (int(data.comprado), item_id))
        conn.commit()
    return {"status": "success"}


@router.delete("/api/shopping-list/{item_id}")
def delete_shopping_item(item_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM shopping_list WHERE id=?", (item_id,))
        conn.commit()
    return {"status": "success"}
