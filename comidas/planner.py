"""
Planificación ampliada de Comidas (sexta ronda). Modelo: día → comida → platos → ingredientes.

- **Franjas** (`franjas`): las de siempre más extras y las que crees; cada una con su
  hora, su parte de las kcal del día (las de fracción 0 no cuentan para el generador) y la franja
  de los platos con que se llena.
- **Papel** de cada plato en su comida: primero, segundo, guarnición, postre, bebida o único.
- **Plato doble**: primero + segundo elegidos para lo que falta de esa comida, con un clic.
- **Plantillas de comida** (conjunto de platos con su papel y gramos) y **favoritos** (platos y
  plantillas), aplicables a cualquier comida con un clic.
- **Registro corporal** (`body_log`): peso y medidas por fecha, tendencia (kg/semana por mínimos
  cuadrados) y ajuste sugerido de las kcal según el objetivo, que se aplica con un clic.

Los macros salen siempre de los ingredientes de cada plato escalados a su ración (_plan_state).
"""
import json
import random
import re
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import nutrition as nu
from .database import get_db
from .main import (DIAS_SEMANA, PlanSlotAdd, SEMANA_PATTERN, _build_meal_catalog, _build_week_state,
                   _catalogo_de, _check_dia_franja, _gramos_racion_para_objetivo, _plan_state, _slot_id,
                   _sync_franjas, add_plato_to_slot, calculate_targets)

router = APIRouter(prefix="/api")
ROL_RE = r"^(primero|segundo|guarnicion|postre|bebida|unico)$"


# ─────────────────────────────────────────────
# Franjas
# ─────────────────────────────────────────────

class FranjaIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=40)
    hora: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    fraccion: float = Field(default=0, ge=0, le=1)
    catalogo: str | None = Field(default=None, pattern=r"^(desayuno|comida|merienda|cena)$")


class FranjaPatch(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=40)
    hora: str | None = Field(default=None, pattern=r"^(([01]\d|2[0-3]):[0-5]\d)?$")
    fraccion: float | None = Field(default=None, ge=0, le=1)
    activa: bool | None = None
    orden: int | None = Field(default=None, ge=0, le=10_000)
    dias: list[str] | None = None  # días en que se usa («lunes», …); los 7 = todos
    catalogo: str | None = Field(default=None, pattern=r"^(desayuno|comida|merienda|cena)$")


def _slug(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:30] or "franja"


@router.get("/franjas")
def list_franjas():
    with get_db() as conn:
        return {"franjas": _sync_franjas(conn)}


@router.post("/franjas")
def create_franja(data: FranjaIn):
    with get_db() as conn:
        clave, n = _slug(data.nombre), 2
        while conn.execute("SELECT 1 FROM franjas WHERE clave=?", (clave,)).fetchone():
            clave, n = f"{_slug(data.nombre)}-{n}", n + 1
        orden = conn.execute("SELECT COALESCE(MAX(orden), 0) + 10 FROM franjas").fetchone()[0]
        conn.execute("INSERT INTO franjas (clave, nombre, orden, fraccion, hora, catalogo, activa, base) VALUES (?, ?, ?, ?, ?, ?, 1, 0)",
                     (clave, data.nombre.strip(), orden, data.fraccion, data.hora, data.catalogo or "merienda"))
    return {"status": "success", "clave": clave}


@router.patch("/franjas/{clave}")
def update_franja(clave: str, data: FranjaPatch):
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM franjas WHERE clave=?", (clave,)).fetchone():
            raise HTTPException(status_code=404, detail="Franja no encontrada")
        for field in ("nombre", "hora", "fraccion", "orden", "catalogo"):
            v = getattr(data, field)
            if v is not None:
                conn.execute(f"UPDATE franjas SET {field}=? WHERE clave=?", (v.strip() if isinstance(v, str) else v, clave))
        if data.hora == "":
            conn.execute("UPDATE franjas SET hora=NULL WHERE clave=?", (clave,))
        if data.activa is not None:
            conn.execute("UPDATE franjas SET activa=? WHERE clave=?", (int(data.activa), clave))
        if data.dias is not None:
            if any(d not in DIAS_SEMANA for d in data.dias):
                raise HTTPException(status_code=422, detail="Día no válido")
            dias = [d for d in DIAS_SEMANA if d in set(data.dias)]
            if not dias:  # ningún día = ocultarla del todo
                conn.execute("UPDATE franjas SET activa=0, dias=NULL WHERE clave=?", (clave,))
            else:
                conn.execute("UPDATE franjas SET dias=?, activa=1 WHERE clave=?", (None if len(dias) == 7 else json.dumps(dias), clave))
    return {"status": "success"}


@router.delete("/franjas/{clave}")
def delete_franja(clave: str):
    """Las de partida solo se ocultan; una propia se borra si ninguna comida la usa (si no, se oculta)."""
    with get_db() as conn:
        row = conn.execute("SELECT base FROM franjas WHERE clave=?", (clave,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Franja no encontrada")
        usada = conn.execute("SELECT 1 FROM weekly_plan WHERE franja=? AND meal_id IS NOT NULL LIMIT 1", (clave,)).fetchone()
        if row["base"] or usada:
            conn.execute("UPDATE franjas SET activa=0 WHERE clave=?", (clave,))
            return {"status": "success", "oculta": True}
        conn.execute("DELETE FROM weekly_plan WHERE franja=? AND meal_id IS NULL", (clave,))
        conn.execute("DELETE FROM franjas WHERE clave=?", (clave,))
    return {"status": "success", "oculta": False}


# ─────────────────────────────────────────────
# Papel de un plato y plato doble
# ─────────────────────────────────────────────

class RolIn(BaseModel):
    plan_id: int = Field(ge=1)
    item_id: int | None = None          # None = el plato principal de la comida
    rol: str | None = Field(default=None, pattern=ROL_RE)


@router.patch("/weekly-plan/rol")
def set_rol(data: RolIn):
    with get_db() as conn:
        if data.item_id is None:
            cur = conn.execute("UPDATE weekly_plan SET rol=? WHERE id=?", (data.rol, data.plan_id))
        else:
            cur = conn.execute("UPDATE plan_items SET rol=? WHERE id=? AND plan_id=?", (data.rol, data.item_id, data.plan_id))
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="Plato no encontrado")
    return {"status": "success"}


PRIMERO_PALABRAS = ("primero", "salmorejo", "pipirrana", "paella", "fideua", "fideuá", "potaje", "ensalada", "sopa", "crema", "pure", "puré", "gazpacho", "salmorejo", "verdura", "menestra",
                    "lentejas", "garbanzos", "alubias", "judias", "judías", "pasta", "arroz", "espaguetis", "macarrones")
SEGUNDO_PALABRAS = ("segundo", "pollo", "ternera", "cerdo", "pavo", "pescado", "salmon", "salmón", "merluza", "atun", "atún",
                    "huevo", "tortilla", "filete", "hamburguesa", "lomo", "bacalao", "sardina", "caballa", "dorada",
                    "pulpo", "conejo", "chuleta", "albondiga", "albóndiga", "boqueron", "boquerón", "revuelto", "solomillo")


def _tipo_doble(meal: dict, tags: str) -> set[str]:
    """«primero» o «segundo» por puntos: la etiqueta manda; si no, el nombre (la palabra con
    que empieza pesa más: «Merluza con ensalada» es un segundo) y luego la composición."""
    tags_l, nombre = tags.lower(), meal["nombre"].lower()
    if "primero" in tags_l or "segundo" in tags_l:
        return {t for t in ("primero", "segundo") if t in tags_l}
    first = nombre.split()[0] if nombre.split() else ""
    prot_ratio = (meal["prot_100g"] * 4 / meal["kcal_100g"]) if meal["kcal_100g"] else 0
    groups = set(meal["groups"])

    def puntos(palabras, grupos, prot_ok):
        p = 4 if any(first.startswith(w) for w in palabras) else 2 if any(w in nombre for w in palabras) else 0
        return p + (1 if groups & grupos else 0) + (2 if prot_ok else 0)
    p1 = puntos(PRIMERO_PALABRAS, {"verdura", "legumbre"}, prot_ratio < 0.2)
    p2 = puntos(SEGUNDO_PALABRAS, {"pescado", "carne_roja", "carne_blanca", "huevo"}, prot_ratio >= 0.28)
    if p1 == p2:
        return set()
    return {"primero"} if p1 > p2 else {"segundo"}


class DobleIn(BaseModel):
    semana: str = Field(pattern=SEMANA_PATTERN)
    dia: str = Field(max_length=20)
    franja: str = Field(default="comida", max_length=30)


@router.post("/weekly-plan/doble")
def add_plato_doble(data: DobleIn):
    """Primer y segundo plato para esta comida, con los gramos para lo que le falta
    (el primero se lleva ~45 % del hueco y el segundo ~55 %)."""
    _check_dia_franja(data.dia, data.franja)
    with get_db() as conn:
        state = _plan_state(conn, data.semana)
        franja_conf = {f["clave"]: f for f in state["franjas"]}
        targets = state["targets"]
        actual = state["dias"][data.dia]["comidas"].get(data.franja)
        ya = {p["meal_id"] for p in (actual or {}).get("platos", [])}
        kcal_actual = (actual or {}).get("total", {}).get("kcal", 0)
        fraccion = float(franja_conf.get(data.franja, {}).get("fraccion") or 0) or 0.3
        hueco = max(targets["kcal_objetivo"] * fraccion - kcal_actual, targets["kcal_objetivo"] * 0.12)

        catalogo = _build_meal_catalog(conn)
        tags = {r["id"]: r["tags"] or "" for r in conn.execute("SELECT id, tags FROM meals")}
        week = _build_week_state(conn, data.semana, catalogo)
        fuente = _catalogo_de(data.franja)
        pool = [m for m in catalogo.values() if m["id"] not in ya and m["kcal_100g"] > 0
                and (m["franja"] == fuente or m["franja"] in ("comida", "cena"))]
        tipos = {m["id"]: _tipo_doble(m, tags.get(m["id"], "")) for m in pool}

        def elegir(tipo, excluir):
            cands = [m for m in pool if tipo in tipos[m["id"]] and m["id"] not in excluir]
            if not cands:
                return None
            # primero lo de la franja, lo no usado esta semana y lo menos repetido últimamente
            cands.sort(key=lambda m: (m["franja"] != fuente, m["id"] in week["used_main"], week["recent_usage"].get(m["id"], 0)))
            return random.choice(cands[:3])

        primero = elegir("primero", set())
        segundo = elegir("segundo", {primero["id"]} if primero else set())
        if not primero or not segundo:
            falta = "primeros" if not primero else "segundos"
            raise HTTPException(status_code=422, detail=f"No hay {falta} en tus platos: etiqueta alguno con «{falta[:-1]}»")
        g1, _, _ = _gramos_racion_para_objetivo(primero, hueco * 0.45)
        g2, _, _ = _gramos_racion_para_objetivo(segundo, hueco * 0.55)
    r1 = add_plato_to_slot(PlanSlotAdd(semana=data.semana, dia=data.dia, franja=data.franja, meal_id=primero["id"], gramos=g1, rol="primero"))
    r2 = add_plato_to_slot(PlanSlotAdd(semana=data.semana, dia=data.dia, franja=data.franja, meal_id=segundo["id"], gramos=g2, rol="segundo"))
    return {"status": "success", "plan_id": r1["plan_id"],
            "primero": {"meal_id": primero["id"], "nombre": primero["nombre"], "gramos": g1},
            "segundo": {"meal_id": segundo["id"], "nombre": segundo["nombre"], "gramos": g2}, "items": [r1, r2]}


# ─────────────────────────────────────────────
# Favoritos y plantillas de comida
# ─────────────────────────────────────────────

class FavIn(BaseModel):
    favorito: bool


@router.patch("/meals/{meal_id}/favorito")
def set_meal_favorite(meal_id: int, data: FavIn):
    with get_db() as conn:
        if not conn.execute("UPDATE meals SET favorito=? WHERE id=?", (int(data.favorito), meal_id)).rowcount:
            raise HTTPException(status_code=404, detail="Plato no encontrado")
    return {"status": "success"}


class TemplateItem(BaseModel):
    meal_id: int = Field(ge=1)
    gramos: float | None = Field(default=None, gt=0, le=3000)
    rol: str | None = Field(default=None, pattern=ROL_RE)


class TemplateIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    franja: str | None = Field(default=None, max_length=30)
    plan_id: int | None = None                          # guardar una comida del plan tal cual
    items: list[TemplateItem] = Field(default_factory=list, max_length=12)
    favorito: bool = False


class TemplatePatch(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=80)
    favorito: bool | None = None


class ApplyIn(BaseModel):
    semana: str = Field(pattern=SEMANA_PATTERN)
    dia: str = Field(max_length=20)
    franja: str = Field(max_length=30)
    reemplazar: bool = False


def _template_out(conn, row) -> dict:
    items = json.loads(row["items"] or "[]")
    nombres = {r["id"]: r["nombre"] for r in conn.execute(
        f"SELECT id, nombre FROM meals WHERE id IN ({','.join('?' * len(items)) or 'NULL'})", [i["meal_id"] for i in items])}
    return {"id": row["id"], "nombre": row["nombre"], "franja": row["franja"], "favorito": bool(row["favorito"]),
            "items": [{**i, "nombre": nombres.get(i["meal_id"], "Plato borrado")} for i in items]}


@router.get("/meal-templates")
def list_templates():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM meal_templates ORDER BY favorito DESC, nombre").fetchall()
        return {"plantillas": [_template_out(conn, r) for r in rows]}


@router.post("/meal-templates")
def create_template(data: TemplateIn):
    items = [i.model_dump() for i in data.items]
    franja = data.franja
    with get_db() as conn:
        if data.plan_id is not None:
            slot = conn.execute("SELECT * FROM weekly_plan WHERE id=?", (data.plan_id,)).fetchone()
            if not slot:
                raise HTTPException(status_code=404, detail="Comida no encontrada")
            franja = franja or slot["franja"]
            items = []
            if slot["meal_id"]:
                items.append({"meal_id": slot["meal_id"], "gramos": slot["gramos_racion"], "rol": slot["rol"]})
            items += [{"meal_id": r["meal_id"], "gramos": r["gramos_racion"], "rol": r["rol"]}
                      for r in conn.execute("SELECT * FROM plan_items WHERE plan_id=? ORDER BY orden, id", (data.plan_id,))]
        if not items:
            raise HTTPException(status_code=422, detail="La plantilla no tiene platos")
        new_id = conn.execute("INSERT INTO meal_templates (nombre, franja, items, favorito) VALUES (?, ?, ?, ?)",
                              (data.nombre.strip(), franja, json.dumps(items), int(data.favorito))).lastrowid
    return {"status": "success", "id": new_id}


@router.patch("/meal-templates/{tid}")
def update_template(tid: int, data: TemplatePatch):
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM meal_templates WHERE id=?", (tid,)).fetchone():
            raise HTTPException(status_code=404, detail="Plantilla no encontrada")
        if data.nombre is not None:
            conn.execute("UPDATE meal_templates SET nombre=? WHERE id=?", (data.nombre.strip(), tid))
        if data.favorito is not None:
            conn.execute("UPDATE meal_templates SET favorito=? WHERE id=?", (int(data.favorito), tid))
    return {"status": "success"}


@router.delete("/meal-templates/{tid}")
def delete_template(tid: int):
    with get_db() as conn:
        conn.execute("DELETE FROM meal_templates WHERE id=?", (tid,))
    return {"status": "success"}


@router.post("/meal-templates/{tid}/apply")
def apply_template(tid: int, data: ApplyIn):
    _check_dia_franja(data.dia, data.franja)
    with get_db() as conn:
        row = conn.execute("SELECT * FROM meal_templates WHERE id=?", (tid,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Plantilla no encontrada")
        items = [i for i in json.loads(row["items"] or "[]")
                 if conn.execute("SELECT 1 FROM meals WHERE id=?", (i["meal_id"],)).fetchone()]
        if data.reemplazar:
            plan_id = _slot_id(conn, data.semana, data.dia, data.franja)
            conn.execute("DELETE FROM plan_items WHERE plan_id=?", (plan_id,))
            conn.execute("UPDATE weekly_plan SET meal_id=NULL, gramos_racion=NULL, rol=NULL WHERE id=?", (plan_id,))
    for i in items:
        add_plato_to_slot(PlanSlotAdd(semana=data.semana, dia=data.dia, franja=data.franja, meal_id=i["meal_id"],
                                      gramos=i.get("gramos"), rol=i.get("rol")))
    return {"status": "success", "platos": len(items)}


# ─────────────────────────────────────────────
# Registro corporal y ajuste de las kcal según la tendencia
# ─────────────────────────────────────────────

MEDIDAS = ("peso_kg", "cintura_cm", "cadera_cm", "pecho_cm", "brazo_cm", "muslo_cm", "grasa_pct")
KCAL_POR_KG = 7700
# Ritmo buscado (% del peso por semana) según el objetivo del perfil
RITMO_OBJETIVO = {"definicion": -0.5, "mantenimiento": 0.0, "volumen": 0.25}


class BodyIn(BaseModel):
    peso_kg: float | None = Field(default=None, ge=20, le=400)
    cintura_cm: float | None = Field(default=None, ge=30, le=250)
    cadera_cm: float | None = Field(default=None, ge=30, le=250)
    pecho_cm: float | None = Field(default=None, ge=30, le=250)
    brazo_cm: float | None = Field(default=None, ge=10, le=100)
    muslo_cm: float | None = Field(default=None, ge=20, le=150)
    grasa_pct: float | None = Field(default=None, ge=2, le=70)
    notas: str | None = Field(default=None, max_length=500)


def tendencia(puntos: list[tuple[date, float]], hoy: date, dias: int = 28) -> dict | None:
    """Pendiente (kg/semana) por mínimos cuadrados con los pesos de los últimos `dias`.
    Hacen falta al menos 3 pesajes que abarquen una semana."""
    pts = [(d, v) for d, v in puntos if v is not None and (hoy - d).days <= dias]
    if len(pts) < 3 or (max(d for d, _ in pts) - min(d for d, _ in pts)).days < 7:
        return None
    xs = [(d - pts[0][0]).days for d, _ in pts]
    ys = [v for _, v in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if not den:
        return None
    pendiente = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den  # kg/día
    return {"kg_semana": round(pendiente * 7, 2), "pesajes": len(pts), "desde": pts[0][0].isoformat(),
            "peso_medio": round(my, 1)}


def sugerencia(tend: dict | None, perfil: dict) -> dict | None:
    if not tend:
        return None
    objetivo = nu.normalizar_objetivo(perfil.get("objetivo"))
    targets = calculate_targets(perfil)
    peso = tend["peso_medio"]
    buscado = RITMO_OBJETIVO.get(objetivo, 0) / 100 * peso       # kg/semana
    diferencia = buscado - tend["kg_semana"]                     # >0: hay que comer más
    delta = max(-400, min(400, round(diferencia * KCAL_POR_KG / 7 / 10) * 10))
    if abs(delta) < 50:
        return {"delta_kcal": 0, "ajuste_pct": targets["ajuste_pct"], "kg_semana_buscado": round(buscado, 2),
                "texto": "Vas al ritmo de tu objetivo: no hace falta tocar las kcal."}
    tdee = targets["tdee"] or 1
    nuevo_pct = round(targets["ajuste_pct"] + delta / tdee * 100, 1)
    verbo = "Sube" if delta > 0 else "Baja"
    es = lambda v: f"{v:+.2f}".replace(".", ",")  # noqa: E731 — coma decimal
    return {"delta_kcal": delta, "ajuste_pct": max(-40, min(40, nuevo_pct)), "kg_semana_buscado": round(buscado, 2),
            "texto": f"{verbo} unas {abs(delta)} kcal al día: vas a {es(tend['kg_semana'])} kg/semana y tu objetivo pide {es(buscado)}."}


@router.get("/body")
def get_body(dias: int = 120):
    dias = max(7, min(dias, 3650))
    desde = (date.today() - timedelta(days=dias)).isoformat()
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM body_log WHERE fecha >= ? ORDER BY fecha", (desde,))]
        perfil = dict(conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone())
    tend = tendencia([(date.fromisoformat(r["fecha"]), r["peso_kg"]) for r in rows], date.today())
    return {"registros": rows, "tendencia": tend, "sugerencia": sugerencia(tend, perfil),
            "objetivo": nu.normalizar_objetivo(perfil.get("objetivo"))}


@router.put("/body/{fecha}")
def put_body(fecha: str, data: BodyIn):
    try:
        d = date.fromisoformat(fecha)
    except ValueError:
        raise HTTPException(status_code=422, detail="La fecha va como AAAA-MM-DD")
    vals = data.model_dump()
    if all(vals[k] is None for k in MEDIDAS):
        raise HTTPException(status_code=422, detail="Escribe al menos el peso o una medida")
    cols = list(vals)
    with get_db() as conn:
        conn.execute(f"INSERT INTO body_log (fecha, {', '.join(cols)}) VALUES (?, {', '.join('?' * len(cols))}) "
                     f"ON CONFLICT(fecha) DO UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in cols)}",
                     (d.isoformat(), *[vals[c] for c in cols]))
    return {"status": "success"}


@router.delete("/body/{fecha}")
def delete_body(fecha: str):
    with get_db() as conn:
        conn.execute("DELETE FROM body_log WHERE fecha=?", (fecha,))
    return {"status": "success"}


class AjusteIn(BaseModel):
    ajuste_pct: float = Field(ge=-40, le=40)
    actualizar_peso: bool = True


@router.post("/body/aplicar-ajuste")
def apply_adjustment(data: AjusteIn):
    """Aplica el ajuste sugerido al perfil (y, si se pide, el último peso registrado)."""
    with get_db() as conn:
        conn.execute("UPDATE user_profile SET ajuste_pct=? WHERE id=1", (data.ajuste_pct,))
        if data.actualizar_peso:
            last = conn.execute("SELECT peso_kg FROM body_log WHERE peso_kg IS NOT NULL ORDER BY fecha DESC LIMIT 1").fetchone()
            if last:
                conn.execute("UPDATE user_profile SET peso_kg=? WHERE id=1", (last["peso_kg"],))
        perfil = dict(conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone())
    return {"status": "success", "targets": calculate_targets(perfil)}
