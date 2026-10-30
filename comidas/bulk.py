"""
Gestión masiva de Comidas: ingredientes, platos del catálogo y celdas del plan.

Edición en lote, borrado con deshacer (instantánea en `undo_log` de
comidas.db), duplicado e importación/exportación CSV y JSON con vista previa.
Las filas de otras tablas que el borrado modifica (lista de la compra, plan)
se guardan también y se restauran con UPDATE, nunca con REPLACE: un REPLACE
en weekly_plan dispararía el ON DELETE CASCADE de plan_items.
"""
import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, ValidationError

from core import tabular, undo
from core.logging_config import get_logger
from . import nutrition as nu
from .database import get_db
from .main import (DIAS_SEMANA, INGREDIENT_FIELDS, SEMANA_PATTERN, IngredientIn, MealIn, _recipe_index,
                   MealIngredientIn, _resolve_ingredients, _suggest_gramos_recomendados,
                   _write_meal_ingredients)

log = get_logger("comidas.bulk")
router = APIRouter(prefix="/api/bulk")

MAX_IDS = 2000
FRANJAS = ("desayuno", "comida", "merienda", "cena")


class Selection(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=MAX_IDS)


class IngredientsUpdate(Selection):
    categoria: str | None = Field(default=None, min_length=1, max_length=60)


class MealsUpdate(Selection):
    franja: str | None = Field(default=None, max_length=30)
    tags_add: list[str] = Field(default_factory=list, max_length=50)
    tags_remove: list[str] = Field(default_factory=list, max_length=50)


class CopyWeek(BaseModel):
    origen: str = Field(pattern=SEMANA_PATTERN)
    destino: str = Field(pattern=SEMANA_PATTERN)
    sobrescribir: bool = False


def _rows(conn, sql: str, ids: list[int]) -> list[dict]:
    marks = ",".join("?" * len(ids))
    return undo.rows_to_dicts(conn.execute(sql.format(ids=marks), ids))


def _restore_columns(conn, table: str, rows: list[dict], cols: list[str]) -> None:
    for r in rows:
        conn.execute(f"UPDATE {table} SET {', '.join(c + '=?' for c in cols)} WHERE id=?", [r[c] for c in cols] + [r["id"]])


def _split_tags(raw: str | None) -> list[str]:
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def _unique_name(conn, table: str, base: str, max_len: int) -> str:
    name, n = f"{base} (copia)"[:max_len], 2
    while conn.execute(f"SELECT 1 FROM {table} WHERE nombre=?", (name,)).fetchone():
        name, n = f"{base} (copia {n})"[:max_len], n + 1
    return name


def _error_text(e: Exception) -> str:
    """Mensaje legible para una fila de importación no válida."""
    if isinstance(e, ValidationError):
        campo = e.errors()[0]["loc"][0]
        return "Falta el nombre" if campo == "nombre" else f"Valor no válido en «{campo}»"
    return getattr(e, "detail", None) or str(e)


# ─────────────────────────────────────────────
# Ingredientes
# ─────────────────────────────────────────────

@router.post("/ingredients/update")
def ingredients_update(data: IngredientsUpdate):
    if data.categoria is None:
        return {"status": "success", "updated": 0}
    with get_db() as conn:
        cur = conn.execute(f"UPDATE ingredients SET categoria=? WHERE id IN ({','.join('?' * len(data.ids))})",
                           [data.categoria.strip(), *data.ids])
    return {"status": "success", "updated": cur.rowcount}


@router.post("/ingredients/delete")
def ingredients_delete(data: Selection):
    ids = list(dict.fromkeys(data.ids))
    with get_db() as conn:
        snap = {
            "ingredients": _rows(conn, "SELECT * FROM ingredients WHERE id IN ({ids})", ids),
            "meal_ingredients": _rows(conn, "SELECT * FROM meal_ingredients WHERE ingredient_id IN ({ids})", ids),
            "shopping_list": _rows(conn, "SELECT * FROM shopping_list WHERE ingredient_id IN ({ids})", ids),
        }
        if not snap["ingredients"]:
            return {"status": "success", "deleted": 0, "undo_token": None}
        found = [r["id"] for r in snap["ingredients"]]
        names = [r["nombre"] for r in snap["ingredients"]]
        token = undo.save(conn, "ingredients.delete", snap, title=names[0] if len(names) == 1 else f"{len(names)} ingredientes", count=len(names))
        marks = ",".join("?" * len(found))
        # Igual que el borrado individual: la lista de la compra conserva la línea como texto libre
        conn.execute(f"""
            UPDATE shopping_list SET nombre_libre = COALESCE(nombre_libre, (SELECT nombre FROM ingredients WHERE id=ingredient_id)),
                   ingredient_id = NULL
            WHERE ingredient_id IN ({marks})
        """, found)
        conn.execute(f"DELETE FROM ingredients WHERE id IN ({marks})", found)
    log.info("Borrado en lote de %d ingredientes", len(found))
    return {"status": "success", "deleted": len(found), "undo_token": token}


@router.post("/ingredients/duplicate")
def ingredients_duplicate(data: Selection):
    created = []
    with get_db() as conn:
        for row in _rows(conn, "SELECT * FROM ingredients WHERE id IN ({ids})", list(dict.fromkeys(data.ids))):
            values = {f: row[f] for f in INGREDIENT_FIELDS}
            values["nombre"] = _unique_name(conn, "ingredients", row["nombre"], 120)
            cur = conn.execute(f"INSERT INTO ingredients ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
                               list(values.values()))
            created.append(cur.lastrowid)
    return {"status": "success", "created": created}


@router.get("/ingredients/export")
def ingredients_export(format: str = "json", ids: str = ""):
    wanted = {int(i) for i in ids.split(",") if i.strip().isdigit()} if ids else None
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute(f"SELECT id, {', '.join(INGREDIENT_FIELDS)} FROM ingredients ORDER BY nombre")]
    rows = [r for r in rows if wanted is None or r["id"] in wanted]
    if format == "csv":
        return tabular.csv_response(rows, ["id", *INGREDIENT_FIELDS], "ingredientes")
    return tabular.json_response("ingredients", rows, "ingredientes")


def _ingredient_from_item(item: dict, base: dict | None = None) -> IngredientIn:
    """Valida una fila. Con `base` (el ingrediente existente) solo cambian las
    columnas que trae el archivo: un CSV sin «gramos_por_unidad» no la borra."""
    values = {f: base[f] for f in INGREDIENT_FIELDS} if base else {}
    for f in INGREDIENT_FIELDS:
        raw = item.get(f)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue
        if f.endswith("_100g") or f == "gramos_por_unidad":
            values[f] = tabular.to_float(raw)
        else:
            values[f] = str(raw).strip()
    values.setdefault("categoria", "General")
    values.setdefault("nombre", "")
    return IngredientIn(**values)


@router.post("/ingredients/import")
async def ingredients_import(file: UploadFile = File(...), mode: str = Form("skip"), dry_run: bool = Form(False)):
    """Se identifican por nombre. mode=skip conserva los existentes; overwrite los actualiza."""
    items = await tabular.read_upload(file, "ingredients")
    result = {"crear": [], "sobrescribir": [], "omitir": [], "errores": [], "avisos": []}
    plan = []
    with get_db() as conn:
        existing = {r["nombre"].lower(): dict(r) for r in conn.execute("SELECT * FROM ingredients")}
        seen = set()
        for n, item in enumerate(items, start=1):
            key = str(item.get("nombre") or "").strip().lower()
            try:
                ing = _ingredient_from_item(item, existing.get(key) if mode == "overwrite" else None)
            except (ValidationError, ValueError) as e:
                result["errores"].append({"fila": n, "error": _error_text(e)})
                continue
            if key in seen:
                result["errores"].append({"fila": n, "error": f"«{ing.nombre}» está repetido en el archivo"})
                continue
            seen.add(key)
            check = nu.comprobar_kcal(ing.kcal_100g, ing.proteinas_100g, ing.carbohidratos_100g, ing.grasas_100g)
            if not check["ok"]:
                result["avisos"].append({"fila": n, "aviso": f"«{ing.nombre}»: las kcal no cuadran con los macros"})
            if key in existing and mode != "overwrite":
                result["omitir"].append(ing.nombre)
                continue
            result["sobrescribir" if key in existing else "crear"].append(ing.nombre)
            plan.append(((existing.get(key) or {}).get("id"), ing))
        if dry_run:
            return {"status": "preview", **result}
        for ing_id, ing in plan:
            values = [getattr(ing, f) for f in INGREDIENT_FIELDS]
            if ing_id:
                conn.execute(f"UPDATE ingredients SET {', '.join(f + '=?' for f in INGREDIENT_FIELDS)} WHERE id=?", values + [ing_id])
            else:
                conn.execute(f"INSERT INTO ingredients ({', '.join(INGREDIENT_FIELDS)}) VALUES ({', '.join('?' * len(INGREDIENT_FIELDS))})", values)
    log.info("Importación de ingredientes: %d nuevos, %d actualizados", len(result["crear"]), len(result["sobrescribir"]))
    return {"status": "success", **result}


# ─────────────────────────────────────────────
# Platos del catálogo
# ─────────────────────────────────────────────

@router.post("/meals/update")
def meals_update(data: MealsUpdate):
    if data.franja is not None and data.franja not in FRANJAS:
        raise HTTPException(status_code=422, detail="Franja no válida")
    add = [t.strip() for t in data.tags_add if t.strip()]
    remove = {t.strip() for t in data.tags_remove}
    updated = 0
    with get_db() as conn:
        for row in _rows(conn, "SELECT id, franja, tags FROM meals WHERE id IN ({ids})", list(dict.fromkeys(data.ids))):
            tags = [t for t in _split_tags(row["tags"]) if t not in remove]
            tags += [t for t in add if t not in tags]
            conn.execute("UPDATE meals SET franja=?, tags=? WHERE id=?",
                         (data.franja or row["franja"], ", ".join(tags)[:500], row["id"]))
            updated += 1
    return {"status": "success", "updated": updated}


@router.post("/meals/delete")
def meals_delete(data: Selection):
    ids = list(dict.fromkeys(data.ids))
    with get_db() as conn:
        snap = {
            "meals": _rows(conn, "SELECT * FROM meals WHERE id IN ({ids})", ids),
            "meal_ingredients": _rows(conn, "SELECT * FROM meal_ingredients WHERE meal_id IN ({ids})", ids),
            "plan_items": _rows(conn, "SELECT * FROM plan_items WHERE meal_id IN ({ids})", ids),
            "meal_usage_log": _rows(conn, "SELECT * FROM meal_usage_log WHERE meal_id IN ({ids})", ids),
            "weekly_plan": _rows(conn, "SELECT * FROM weekly_plan WHERE meal_id IN ({ids})", ids),
            "shopping_list": _rows(conn, "SELECT * FROM shopping_list WHERE source_meal_id IN ({ids})", ids),
        }
        if not snap["meals"]:
            return {"status": "success", "deleted": 0, "undo_token": None}
        found = [r["id"] for r in snap["meals"]]
        names = [r["nombre"] for r in snap["meals"]]
        token = undo.save(conn, "meals.delete", snap, title=names[0] if len(names) == 1 else f"{len(names)} platos", count=len(names))
        marks = ",".join("?" * len(found))
        conn.execute(f"UPDATE weekly_plan SET meal_id=NULL, gramos_racion=NULL WHERE meal_id IN ({marks})", found)
        conn.execute(f"UPDATE shopping_list SET source_meal_id=NULL WHERE source_meal_id IN ({marks})", found)
        conn.execute(f"DELETE FROM meals WHERE id IN ({marks})", found)
    log.info("Borrado en lote de %d platos", len(found))
    return {"status": "success", "deleted": len(found), "undo_token": token}


@router.post("/meals/duplicate")
def meals_duplicate(data: Selection):
    created = []
    with get_db() as conn:
        for row in _rows(conn, "SELECT * FROM meals WHERE id IN ({ids})", list(dict.fromkeys(data.ids))):
            copy = {k: v for k, v in row.items() if k not in ("id", "created_at")}
            copy["nombre"] = _unique_name(conn, "meals", row["nombre"], 200)
            cur = conn.execute(f"INSERT INTO meals ({', '.join(copy)}) VALUES ({', '.join('?' * len(copy))})", list(copy.values()))
            conn.execute("""INSERT INTO meal_ingredients (meal_id, ingredient_id, gramos, unidades)
                            SELECT ?, ingredient_id, gramos, unidades FROM meal_ingredients WHERE meal_id=? ORDER BY id""",
                         (cur.lastrowid, row["id"]))
            created.append(cur.lastrowid)
    return {"status": "success", "created": created}


MEAL_CSV_FIELDS = ["id", "nombre", "franja", "tags", "tiempo_preparacion_min", "gramos_recomendados", "es_racion_unica",
                   "kcal_racion", "proteinas_racion", "carbohidratos_racion", "grasas_racion", "ingredientes", "instrucciones"]


@router.get("/meals/export")
def meals_export(format: str = "json", ids: str = ""):
    wanted = {int(i) for i in ids.split(",") if i.strip().isdigit()} if ids else None
    with get_db() as conn:
        index = _recipe_index(conn)
        ings: dict[int, list] = {}
        for r in conn.execute("""SELECT mi.meal_id, i.nombre, mi.gramos, mi.unidades FROM meal_ingredients mi
                                 JOIN ingredients i ON i.id = mi.ingredient_id ORDER BY mi.id"""):
            ings.setdefault(r["meal_id"], []).append({"nombre": r["nombre"], "gramos": r["gramos"], "unidades": r["unidades"]})
    out = []
    for mid in sorted(index):
        if wanted is not None and mid not in wanted:
            continue
        m = index[mid]
        row = m["row"]
        macros = nu.redondear(nu.racion(m["total"], m["gramos_receta"], m["gramos_base"]))
        out.append({"id": mid, "nombre": row["nombre"], "franja": row["franja"], "tags": row["tags"] or "",
                    "tiempo_preparacion_min": row["tiempo_preparacion_min"], "gramos_recomendados": m["gramos_base"],
                    "es_racion_unica": m["es_racion_unica"], "kcal_racion": macros["kcal"],
                    "proteinas_racion": macros["proteinas"], "carbohidratos_racion": macros["carbohidratos"],
                    "grasas_racion": macros["grasas"], "ingredientes": ings.get(mid, []),
                    "instrucciones": json.loads(row["instrucciones"] or "[]")})
    if format == "csv":
        flat = [{**m, "es_racion_unica": int(m["es_racion_unica"]),
                 "ingredientes": "; ".join(f"{i['nombre']}: {f'{i['unidades']:g} ud' if i['unidades'] else f'{i['gramos']:g} g'}"
                                           for i in m["ingredientes"]),
                 "instrucciones": " | ".join(m["instrucciones"])} for m in out]
        return tabular.csv_response(flat, MEAL_CSV_FIELDS, "platos")
    return tabular.json_response("meals", out, "platos")


def _parse_ingredient_list(value) -> list[dict]:
    """[{nombre, gramos|unidades}] desde JSON o «Arroz: 80 g; Huevo: 2 ud» desde CSV."""
    if isinstance(value, list):
        return [i for i in value if isinstance(i, dict)]
    out = []
    for part in str(value or "").split(";"):
        if not part.strip():
            continue
        nombre, _, cantidad = part.rpartition(":")
        if not nombre:
            raise ValueError(f"Ingrediente sin cantidad: «{part.strip()}»")
        cantidad = cantidad.strip().lower()
        if cantidad.endswith("ud"):
            out.append({"nombre": nombre.strip(), "unidades": tabular.to_float(cantidad[:-2])})
        else:
            out.append({"nombre": nombre.strip(), "gramos": tabular.to_float(cantidad.removesuffix("g"))})
    return out


def _meal_from_item(item: dict, ing_ids: dict[str, int]) -> MealIn:
    ingredientes = []
    for i in _parse_ingredient_list(item.get("ingredientes")):
        nombre = str(i.get("nombre") or "").strip()
        if nombre.lower() not in ing_ids:
            raise ValueError(f"No existe el ingrediente «{nombre}»")
        ingredientes.append(MealIngredientIn(ingredient_id=ing_ids[nombre.lower()],
                                             gramos=tabular.to_float(i.get("gramos")), unidades=tabular.to_float(i.get("unidades"))))
    instr = item.get("instrucciones") or []
    if isinstance(instr, str):
        instr = [s.strip() for s in instr.split("|") if s.strip()]
    unica = item.get("es_racion_unica")
    return MealIn(nombre=str(item.get("nombre") or "").strip(), franja=str(item.get("franja") or "comida").strip(),
                  tags=str(item.get("tags") or ""), tiempo_preparacion_min=int(tabular.to_float(item.get("tiempo_preparacion_min"), 0)),
                  gramos_recomendados=tabular.to_float(item.get("gramos_recomendados"), 0),
                  es_racion_unica=unica is True or str(unica).strip().lower() in ("1", "true", "si", "sí"),
                  instrucciones=[str(s) for s in instr], ingredientes=ingredientes)


@router.post("/meals/import")
async def meals_import(file: UploadFile = File(...), mode: str = Form("skip"), dry_run: bool = Form(False)):
    """Se identifican por nombre; los ingredientes deben existir ya en el catálogo."""
    items = await tabular.read_upload(file, "meals")
    result = {"crear": [], "sobrescribir": [], "omitir": [], "errores": []}
    with get_db() as conn:
        ing_ids = {r["nombre"].lower(): r["id"] for r in conn.execute("SELECT id, nombre FROM ingredients")}
        existing = {}
        for r in conn.execute("SELECT id, nombre FROM meals ORDER BY id"):
            existing.setdefault(r["nombre"].lower(), r["id"])
        plan, seen = [], set()
        for n, item in enumerate(items, start=1):
            try:
                meal = _meal_from_item(item, ing_ids)
                if meal.franja not in FRANJAS:
                    raise ValueError(f"Franja no válida: {meal.franja}")
                resolved = _resolve_ingredients(conn, meal.ingredientes)
            except (ValidationError, ValueError, HTTPException) as e:
                result["errores"].append({"fila": n, "error": _error_text(e)})
                continue
            key = meal.nombre.lower()
            if key in seen:
                result["errores"].append({"fila": n, "error": f"«{meal.nombre}» está repetido en el archivo"})
                continue
            seen.add(key)
            if key in existing and mode != "overwrite":
                result["omitir"].append(meal.nombre)
                continue
            result["sobrescribir" if key in existing else "crear"].append(meal.nombre)
            plan.append((existing.get(key), meal, resolved))
        if dry_run:
            return {"status": "preview", **result}
        for meal_id, meal, resolved in plan:
            gramos = meal.gramos_recomendados
            if not meal.es_racion_unica and not gramos:
                gramos = _suggest_gramos_recomendados(conn, meal.ingredientes, meal.franja)
            vals = (meal.nombre, meal.franja, meal.tags, meal.tiempo_preparacion_min, gramos, int(meal.es_racion_unica),
                    json.dumps(meal.instrucciones, ensure_ascii=False))
            if meal_id:
                conn.execute("""UPDATE meals SET nombre=?, franja=?, tags=?, tiempo_preparacion_min=?, gramos_recomendados=?,
                                es_racion_unica=?, instrucciones=? WHERE id=?""", (*vals, meal_id))
            else:
                meal_id = conn.execute("""INSERT INTO meals (nombre, franja, tags, tiempo_preparacion_min, gramos_recomendados,
                                          es_racion_unica, instrucciones, image_url) VALUES (?, ?, ?, ?, ?, ?, ?, '')""", vals).lastrowid
            _write_meal_ingredients(conn, meal_id, resolved)
    log.info("Importación de platos: %d nuevos, %d actualizados", len(result["crear"]), len(result["sobrescribir"]))
    return {"status": "success", **result}


# ─────────────────────────────────────────────
# Celdas del plan semanal
# ─────────────────────────────────────────────

@router.post("/plan/delete")
def plan_delete(data: Selection):
    ids = list(dict.fromkeys(data.ids))
    with get_db() as conn:
        snap = {"weekly_plan": _rows(conn, "SELECT * FROM weekly_plan WHERE id IN ({ids})", ids),
                "plan_items": _rows(conn, "SELECT * FROM plan_items WHERE plan_id IN ({ids})", ids)}
        if not snap["weekly_plan"]:
            return {"status": "success", "deleted": 0, "undo_token": None}
        found = [r["id"] for r in snap["weekly_plan"]]
        token = undo.save(conn, "plan.delete", snap, title=f"{len(found)} comida{'s' if len(found) != 1 else ''} del plan", count=len(found))
        conn.execute(f"DELETE FROM weekly_plan WHERE id IN ({','.join('?' * len(found))})", found)
    return {"status": "success", "deleted": len(found), "undo_token": token}


@router.post("/plan/copy-week")
def plan_copy_week(data: CopyWeek):
    """Copia los platos (principal y adicionales) de una semana a otra."""
    copied = skipped = 0
    with get_db() as conn:
        for cell in conn.execute("SELECT * FROM weekly_plan WHERE semana=?", (data.origen,)).fetchall():
            dst = conn.execute("SELECT id FROM weekly_plan WHERE semana=? AND dia=? AND franja=?",
                               (data.destino, cell["dia"], cell["franja"])).fetchone()
            if dst and not data.sobrescribir:
                skipped += 1
                continue
            if dst:
                conn.execute("DELETE FROM plan_items WHERE plan_id=?", (dst["id"],))
                conn.execute("UPDATE weekly_plan SET meal_id=?, is_fixed=?, gramos_racion=? WHERE id=?",
                             (cell["meal_id"], cell["is_fixed"], cell["gramos_racion"], dst["id"]))
                new_id = dst["id"]
            else:
                new_id = conn.execute("INSERT INTO weekly_plan (semana, dia, franja, meal_id, is_fixed, gramos_racion) VALUES (?, ?, ?, ?, ?, ?)",
                                      (data.destino, cell["dia"], cell["franja"], cell["meal_id"], cell["is_fixed"],
                                       cell["gramos_racion"])).lastrowid
            conn.execute("""INSERT INTO plan_items (plan_id, meal_id, gramos_racion, orden)
                            SELECT ?, meal_id, gramos_racion, orden FROM plan_items WHERE plan_id=? ORDER BY orden, id""",
                         (new_id, cell["id"]))
            copied += 1
    return {"status": "success", "copied": copied, "skipped": skipped}


# ─────────────────────────────────────────────
# Deshacer (común)
# ─────────────────────────────────────────────

@router.post("/undo/{token}")
def bulk_undo(token: str):
    with get_db() as conn:
        entry = undo.pop(conn, token)
        if not entry:
            raise HTTPException(status_code=404, detail="No hay nada que deshacer (o ha caducado)")
        kind, snap = entry
        if kind == "ingredients.delete":
            restored = undo.insert_rows(conn, "ingredients", snap["ingredients"])
            undo.insert_rows(conn, "meal_ingredients", snap["meal_ingredients"])
            _restore_columns(conn, "shopping_list", snap["shopping_list"], ["ingredient_id", "nombre_libre"])
        elif kind == "meals.delete":
            restored = undo.insert_rows(conn, "meals", snap["meals"])
            undo.insert_rows(conn, "meal_ingredients", snap["meal_ingredients"])
            undo.insert_rows(conn, "meal_usage_log", snap["meal_usage_log"])
            _restore_columns(conn, "weekly_plan", snap["weekly_plan"], ["meal_id", "gramos_racion"])
            _restore_columns(conn, "shopping_list", snap["shopping_list"], ["source_meal_id"])
            # Los platos adicionales cuya celda siga existiendo
            alive = {r["id"] for r in conn.execute("SELECT id FROM weekly_plan")}
            undo.insert_rows(conn, "plan_items", [r for r in snap["plan_items"] if r["plan_id"] in alive])
        elif kind == "plan.delete":
            free = [r for r in snap["weekly_plan"] if not conn.execute(
                "SELECT 1 FROM weekly_plan WHERE semana=? AND dia=? AND franja=?", (r["semana"], r["dia"], r["franja"])).fetchone()]
            restored = undo.insert_rows(conn, "weekly_plan", free)
            ids = {r["id"] for r in free}
            undo.insert_rows(conn, "plan_items", [r for r in snap["plan_items"] if r["plan_id"] in ids])
        else:
            raise HTTPException(status_code=404, detail="No hay nada que deshacer")
    return {"status": "success", "restored": restored}
