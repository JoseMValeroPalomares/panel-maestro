"""
Economía (página /economia): cuentas, movimientos, deudas y lista de deseos (tablas fin_*, migración 13).

    Cuentas      lo que tienes: efectivo, banco, ahorro… Saldo = inicial + ingresos − gastos ± transferencias.
    Movimientos  gasto, ingreso o transferencia (entre dos cuentas), con fecha, categoría y concepto. Los
                 importes se guardan en euros y siempre en positivo: el tipo dice el signo.
    Deudas       lo que te deben («me-deben») y lo que debes («debo»). Al saldarla se puede apuntar el
                 movimiento en una cuenta (cobro = ingreso, pago = gasto).
    Deseos       lo que quieres comprar, con precio y prioridad. «Comprado» lo apunta como gasto.

    Presupuestos lo que quieres gastar como mucho al mes en una categoría (fin_budgets, migración 15).
    Recurrentes  lo que se repite cada mes (alquiler, suscripciones, la paga): se apunta solo el día que
                 toca, al abrir Economía (fin_recurring; «ultimo» = último mes apuntado).

    GET  /api/finance/summary?month=AAAA-MM      cuentas, mes (gastos, ingresos, por categoría y presupuesto), 6 meses,
                                                 deudas, deseos, recurrentes
    CRUD /api/finance/{accounts|movements|debts|wishes|recurring}
    PUT  /api/finance/budgets/{categoria}        {importe} (0 o vacío lo quita)
    GET  /api/finance/export.csv?month=AAAA-MM   movimientos del mes (o todos sin mes) en CSV
    POST /api/finance/debts/{id}/settle          {cuenta_id?}
    POST /api/finance/wishes/{id}/buy            {cuenta_id?, importe?}

Borrar algo lo deja 30 días en la papelera (core/undo.py, tipos «finance.*»).
"""
import time
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.database import get_db
from core import undo

router = APIRouter(prefix="/api/finance")

GASTO_CATS = ["Comida", "Supermercado", "Transporte", "Ocio", "Universidad", "Casa", "Ropa", "Salud", "Deporte",
              "Suscripciones", "Regalos", "Compras", "Otros"]
INGRESO_CATS = ["Trabajo", "Paga", "Beca", "Regalo", "Venta", "Devolución", "Otros"]
ACCOUNT_TYPES = ("efectivo", "banco", "ahorro", "tarjeta", "otra")
TABLES = {"accounts": "fin_accounts", "movements": "fin_movements", "debts": "fin_debts", "wishes": "fin_wishes", "recurring": "fin_recurring"}
LABEL = {"accounts": "cuenta", "movements": "movimiento", "debts": "deuda", "wishes": "deseo", "recurring": "recurrente"}


def money(v) -> float:
    """«12,50», «1.234,5», «12.5» o 12.5 → 12.5 (dos decimales)."""
    if isinstance(v, (int, float)):
        n = float(v)
    else:
        t = str(v).strip().replace("€", "").replace(" ", "")
        if "," in t:  # formato español: el punto es de miles
            t = t.replace(".", "").replace(",", ".")
        try:
            n = float(t)
        except ValueError:
            raise ValueError("El importe no es un número")
    return round(n, 2)


def _pos(v) -> float:
    n = money(v)
    if n <= 0:
        raise ValueError("El importe tiene que ser mayor que 0")
    return n


def _tipo_mov(v: str) -> str:
    if v not in ("gasto", "ingreso", "transferencia"):
        raise ValueError("Tipo: gasto, ingreso o transferencia")
    return v


def _direccion(v: str) -> str:
    if v not in ("me-deben", "debo"):
        raise ValueError("Dirección: me-deben o debo")
    return v


def _day(v: str | None) -> str | None:
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(v[:10]).isoformat()
    except ValueError:
        raise ValueError("La fecha va como AAAA-MM-DD")


# ─────────────────────────────────────────────
# Modelos
# ─────────────────────────────────────────────

class AccountIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=60)
    tipo: str = "banco"
    saldo_inicial: float | str = 0

    @field_validator("tipo")
    @classmethod
    def v_tipo(cls, v):
        if v not in ACCOUNT_TYPES:
            raise ValueError("Tipo de cuenta: efectivo, banco, ahorro, tarjeta u otra")
        return v

    @field_validator("saldo_inicial")
    @classmethod
    def v_saldo(cls, v):
        return money(v)


class AccountPatch(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=60)
    tipo: str | None = None
    saldo_inicial: float | str | None = None
    archivada: bool | None = None
    orden: int | None = None

    @field_validator("saldo_inicial")
    @classmethod
    def v_saldo(cls, v):
        return None if v is None else money(v)


class MovementIn(BaseModel):
    importe: float | str
    tipo: str = "gasto"
    fecha: str | None = None
    categoria: str | None = Field(default=None, max_length=40)
    concepto: str | None = Field(default=None, max_length=200)
    cuenta_id: int | None = None
    cuenta_destino: int | None = None
    notas: str | None = Field(default=None, max_length=2000)

    @field_validator("importe")
    @classmethod
    def v_importe(cls, v):
        return _pos(v)

    @field_validator("tipo")
    @classmethod
    def v_tipo(cls, v):
        return _tipo_mov(v)

    @field_validator("fecha")
    @classmethod
    def v_fecha(cls, v):
        return _day(v)


class MovementPatch(MovementIn):
    importe: float | str | None = None
    tipo: str | None = None

    @field_validator("importe")
    @classmethod
    def v_importe(cls, v):
        return None if v is None else _pos(v)

    @field_validator("tipo")
    @classmethod
    def v_tipo(cls, v):
        return None if v is None else _tipo_mov(v)


class DebtIn(BaseModel):
    persona: str = Field(min_length=1, max_length=60)
    importe: float | str
    direccion: str = "me-deben"
    concepto: str | None = Field(default=None, max_length=200)
    fecha: str | None = None
    vence: str | None = None
    notas: str | None = Field(default=None, max_length=2000)

    @field_validator("importe")
    @classmethod
    def v_importe(cls, v):
        return _pos(v)

    @field_validator("direccion")
    @classmethod
    def v_dir(cls, v):
        return _direccion(v)

    @field_validator("fecha", "vence")
    @classmethod
    def v_fecha(cls, v):
        return _day(v)


class DebtPatch(DebtIn):
    persona: str | None = Field(default=None, min_length=1, max_length=60)
    importe: float | str | None = None
    direccion: str | None = None

    @field_validator("importe")
    @classmethod
    def v_importe(cls, v):
        return None if v is None else _pos(v)

    @field_validator("direccion")
    @classmethod
    def v_dir(cls, v):
        return None if v is None else _direccion(v)


class WishIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    precio: float | str | None = None
    url: str | None = Field(default=None, max_length=1000)
    prioridad: str | None = None
    notas: str | None = Field(default=None, max_length=2000)

    @field_validator("precio")
    @classmethod
    def v_precio(cls, v):
        return None if v in (None, "") else money(v)

    @field_validator("prioridad")
    @classmethod
    def v_prio(cls, v):
        if v not in (None, "", "alta", "media", "baja"):
            raise ValueError("Prioridad: alta, media o baja")
        return v or None


class WishPatch(WishIn):
    nombre: str | None = Field(default=None, min_length=1, max_length=120)


class SettleIn(BaseModel):
    cuenta_id: int | None = None
    importe: float | str | None = None


# ─────────────────────────────────────────────
# Cálculos
# ─────────────────────────────────────────────

class RecurringIn(BaseModel):
    concepto: str = Field(min_length=1, max_length=200)
    importe: float | str
    tipo: str = "gasto"
    categoria: str | None = Field(default=None, max_length=40)
    cuenta_id: int | None = None
    dia: int = Field(default=1, ge=1, le=28)  # hasta el 28: existe en todos los meses
    activo: bool = True

    @field_validator("importe")
    @classmethod
    def v_importe(cls, v):
        return _pos(v)

    @field_validator("tipo")
    @classmethod
    def v_tipo(cls, v):
        if v not in ("gasto", "ingreso"):
            raise ValueError("Un recurrente es un gasto o un ingreso")
        return v


class RecurringPatch(RecurringIn):
    concepto: str | None = Field(default=None, min_length=1, max_length=200)
    importe: float | str | None = None
    tipo: str | None = None
    dia: int | None = Field(default=None, ge=1, le=28)
    activo: bool | None = None

    @field_validator("importe")
    @classmethod
    def v_importe(cls, v):
        return None if v is None else _pos(v)

    @field_validator("tipo")
    @classmethod
    def v_tipo(cls, v):
        if v not in (None, "gasto", "ingreso"):
            raise ValueError("Un recurrente es un gasto o un ingreso")
        return v


class BudgetIn(BaseModel):
    importe: float | str | None = None


def apply_recurring(conn, today: date | None = None) -> int:
    """Apunta los recurrentes que ya tocan y no están apuntados (también los de meses pasados sin abrir
    Economía). Devuelve cuántos movimientos ha creado."""
    today = today or date.today()
    cur_month = today.strftime("%Y-%m")
    n = 0
    for r in conn.execute("SELECT * FROM fin_recurring WHERE activo=1").fetchall():
        m = _shift(r["ultimo"], 1) if r["ultimo"] else r["desde"]
        while m <= cur_month:
            if m == cur_month and today.day < r["dia"]:
                break
            conn.execute("INSERT INTO fin_movements (fecha, importe, tipo, categoria, concepto, cuenta_id, notas) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (f"{m}-{r['dia']:02d}", r["importe"], r["tipo"], r["categoria"] or "Otros", r["concepto"], r["cuenta_id"], "Recurrente"))
            conn.execute("UPDATE fin_recurring SET ultimo=? WHERE id=?", (m, r["id"]))
            n += 1
            m = _shift(m, 1)
    return n


def _next_date(r, today: date) -> str:
    """Próxima vez que se apunta un recurrente (AAAA-MM-DD)."""
    m = today.strftime("%Y-%m")
    if (r["ultimo"] and r["ultimo"] >= m) or today.day > r["dia"]:
        m = _shift(m, 1)
    return f"{max(m, r['desde'])}-{r['dia']:02d}"


def balances(conn) -> list[dict]:
    out = []
    for a in conn.execute("SELECT * FROM fin_accounts ORDER BY archivada, orden, id"):
        s = a["saldo_inicial"]
        for m in conn.execute("SELECT tipo, importe, cuenta_id, cuenta_destino FROM fin_movements WHERE cuenta_id=? OR cuenta_destino=?", (a["id"], a["id"])):
            if m["tipo"] == "ingreso" and m["cuenta_id"] == a["id"]:
                s += m["importe"]
            elif m["tipo"] == "gasto" and m["cuenta_id"] == a["id"]:
                s -= m["importe"]
            elif m["tipo"] == "transferencia":
                s += m["importe"] if m["cuenta_destino"] == a["id"] else -m["importe"] if m["cuenta_id"] == a["id"] else 0
        out.append({**dict(a), "archivada": bool(a["archivada"]), "saldo": round(s, 2)})
    return out


def _month_bounds(month: str) -> tuple[str, str]:
    y, m = (int(x) for x in month.split("-"))
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return date(y, m, 1).isoformat(), nxt.isoformat()


def _shift(month: str, k: int) -> str:
    y, m = (int(x) for x in month.split("-"))
    i = y * 12 + (m - 1) + k
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def summary(month: str | None = None) -> dict:
    month = month or date.today().strftime("%Y-%m")
    try:
        lo, hi = _month_bounds(month)
    except ValueError:
        raise HTTPException(status_code=422, detail="El mes va como AAAA-MM")
    with get_db() as conn:
        apply_recurring(conn)
        cuentas = balances(conn)
        rows = conn.execute("SELECT tipo, categoria, importe FROM fin_movements WHERE fecha >= ? AND fecha < ? AND tipo != 'transferencia'", (lo, hi)).fetchall()
        budgets = {r["categoria"]: r["importe"] for r in conn.execute("SELECT categoria, importe FROM fin_budgets")}
        today = date.today()
        recurrentes = [{**dict(r), "proxima": _next_date(r, today) if r["activo"] else None}
                       for r in conn.execute("SELECT * FROM fin_recurring ORDER BY activo DESC, dia, concepto")]
        gastos = round(sum(r["importe"] for r in rows if r["tipo"] == "gasto"), 2)
        ingresos = round(sum(r["importe"] for r in rows if r["tipo"] == "ingreso"), 2)
        cats = {}
        for r in rows:
            if r["tipo"] == "gasto":
                k = r["categoria"] or "Otros"
                cats[k] = round(cats.get(k, 0) + r["importe"], 2)
        meses = []
        for k in range(-5, 1):
            mm = _shift(month, k)
            a, b = _month_bounds(mm)
            g, i = conn.execute("SELECT COALESCE(SUM(CASE WHEN tipo='gasto' THEN importe END), 0), COALESCE(SUM(CASE WHEN tipo='ingreso' THEN importe END), 0) "
                                "FROM fin_movements WHERE fecha >= ? AND fecha < ?", (a, b)).fetchone()
            meses.append({"mes": mm, "gastos": round(g, 2), "ingresos": round(i, 2)})
        deudas = [dict(r) for r in conn.execute("SELECT * FROM fin_debts WHERE saldada_at IS NULL ORDER BY COALESCE(vence, '9999'), fecha")]
        deseos = [dict(r) for r in conn.execute("SELECT * FROM fin_wishes WHERE comprado_at IS NULL ORDER BY CASE prioridad WHEN 'alta' THEN 0 WHEN 'media' THEN 1 WHEN 'baja' THEN 2 ELSE 3 END, orden, id")]
    activas = [c for c in cuentas if not c["archivada"]]
    me_deben = round(sum(d["importe"] for d in deudas if d["direccion"] == "me-deben"), 2)
    debo = round(sum(d["importe"] for d in deudas if d["direccion"] == "debo"), 2)
    return {
        "month": month, "today": date.today().isoformat(), "cuentas": cuentas, "total": round(sum(c["saldo"] for c in activas), 2),
        "mes": {"gastos": gastos, "ingresos": ingresos, "balance": round(ingresos - gastos, 2),
                # las categorías con gasto y las que tienen presupuesto aunque aún no se haya gastado nada
                "por_categoria": [{"categoria": k, "total": cats.get(k, 0), "presupuesto": budgets.get(k)}
                                  for k in sorted(set(cats) | set(budgets), key=lambda k: (-cats.get(k, 0), k))]},
        "presupuestos": budgets, "presupuesto_total": round(sum(budgets.values()), 2),
        "recurrentes": recurrentes,
        "recurrentes_mes": round(sum(r["importe"] if r["tipo"] == "gasto" else -r["importe"] for r in recurrentes if r["activo"]), 2),
        "meses": meses, "deudas": deudas, "me_deben": me_deben, "debo": debo,
        "deseos": deseos, "deseos_total": round(sum(w["precio"] or 0 for w in deseos), 2),
        "categorias": {"gasto": GASTO_CATS, "ingreso": INGRESO_CATS}, "tipos_cuenta": list(ACCOUNT_TYPES),
    }


# ─────────────────────────────────────────────
# Rutas
# ─────────────────────────────────────────────

def _get(conn, table: str, rid: int):
    row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (rid,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No existe")
    return row


def _account_ok(conn, cid: int | None) -> None:
    if cid is not None and not conn.execute("SELECT 1 FROM fin_accounts WHERE id=?", (cid,)).fetchone():
        raise HTTPException(status_code=422, detail="Esa cuenta no existe")


REQUIRED = {"fecha", "importe", "tipo", "nombre", "persona", "direccion", "saldo_inicial"}  # nunca a NULL


def _patch(conn, table: str, rid: int, data: BaseModel) -> None:
    for k, v in data.model_dump(exclude_unset=True).items():
        if isinstance(v, bool):
            v = int(v)
        if isinstance(v, str):
            v = v.strip() or None
        if v is None and k in REQUIRED:
            continue
        conn.execute(f"UPDATE {table} SET {k}=? WHERE id=?", (v, rid))


@router.get("/summary")
def api_summary(month: str | None = None):
    return summary(month)


@router.get("/movements")
def api_movements(month: str | None = None, categoria: str | None = None, q: str | None = None, cuenta_id: int | None = None):
    sql, args = "SELECT * FROM fin_movements WHERE 1=1", []
    if month:
        lo, hi = _month_bounds(month)
        sql += " AND fecha >= ? AND fecha < ?"
        args += [lo, hi]
    if categoria:
        sql += " AND categoria = ?"
        args.append(categoria)
    if cuenta_id:
        sql += " AND (cuenta_id = ? OR cuenta_destino = ?)"
        args += [cuenta_id, cuenta_id]
    if q:
        sql += " AND (concepto LIKE ? OR notas LIKE ? OR categoria LIKE ?)"
        args += [f"%{q}%"] * 3
    with get_db() as conn:
        return {"movements": [dict(r) for r in conn.execute(sql + " ORDER BY fecha DESC, id DESC LIMIT 500", args)]}


@router.post("/movements")
def api_create_movement(data: MovementIn):
    if data.tipo == "transferencia" and (not data.cuenta_id or not data.cuenta_destino or data.cuenta_id == data.cuenta_destino):
        raise HTTPException(status_code=422, detail="Una transferencia va de una cuenta a otra distinta")
    with get_db() as conn:
        _account_ok(conn, data.cuenta_id)
        _account_ok(conn, data.cuenta_destino)
        cur = conn.execute("INSERT INTO fin_movements (fecha, importe, tipo, categoria, concepto, cuenta_id, cuenta_destino, notas) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (data.fecha or date.today().isoformat(), data.importe, data.tipo, (data.categoria or "").strip() or None,
                            (data.concepto or "").strip() or None, data.cuenta_id, data.cuenta_destino if data.tipo == "transferencia" else None,
                            (data.notas or "").strip() or None))
    return {"status": "success", "id": cur.lastrowid}


@router.post("/recurring")
def api_create_recurring(data: RecurringIn):
    """Un gasto o ingreso de cada mes. Si su día de este mes ya pasó, empieza el mes que viene (no se
    apunta hacia atrás lo que ya habrás apuntado a mano)."""
    today = date.today()
    desde = today.strftime("%Y-%m") if today.day <= data.dia else _shift(today.strftime("%Y-%m"), 1)
    with get_db() as conn:
        _account_ok(conn, data.cuenta_id)
        cur = conn.execute("INSERT INTO fin_recurring (concepto, importe, tipo, categoria, cuenta_id, dia, activo, desde) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (data.concepto.strip(), data.importe, data.tipo, (data.categoria or "").strip() or None, data.cuenta_id, data.dia, int(data.activo), desde))
        apply_recurring(conn)
    return {"status": "success", "id": cur.lastrowid}


@router.put("/budgets/{categoria}")
def api_budget(categoria: str, data: BudgetIn):
    categoria = categoria.strip()[:40]
    if not categoria:
        raise HTTPException(status_code=422, detail="Falta la categoría")
    importe = money(data.importe) if data.importe not in (None, "") else 0
    if importe < 0:
        raise HTTPException(status_code=422, detail="El presupuesto no puede ser negativo")
    with get_db() as conn:
        if importe:
            conn.execute("INSERT INTO fin_budgets (categoria, importe) VALUES (?, ?) ON CONFLICT(categoria) DO UPDATE SET importe=excluded.importe",
                         (categoria, importe))
        else:
            conn.execute("DELETE FROM fin_budgets WHERE categoria=?", (categoria,))
    return {"status": "success"}


@router.get("/export.csv")
def api_export(month: str | None = None):
    from core.tabular import csv_response
    sql, args = "SELECT m.*, a.nombre AS cuenta, b.nombre AS cuenta_destino_nombre FROM fin_movements m " \
                "LEFT JOIN fin_accounts a ON a.id = m.cuenta_id LEFT JOIN fin_accounts b ON b.id = m.cuenta_destino", []
    if month:
        lo, hi = _month_bounds(month)
        sql += " WHERE m.fecha >= ? AND m.fecha < ?"
        args = [lo, hi]
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute(sql + " ORDER BY m.fecha, m.id", args)]
    for r in rows:
        r["importe"] = f"{r['importe']:.2f}".replace(".", ",")  # coma decimal: lo abre bien una hoja de cálculo en español
        r["a_cuenta"] = r.pop("cuenta_destino_nombre")
    return csv_response(rows, ["fecha", "tipo", "importe", "categoria", "concepto", "cuenta", "a_cuenta", "notas"],
                        f"economia-{month or 'todo'}")


@router.post("/accounts")
def api_create_account(data: AccountIn):
    with get_db() as conn:
        orden = conn.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM fin_accounts").fetchone()[0]
        cur = conn.execute("INSERT INTO fin_accounts (nombre, tipo, saldo_inicial, orden) VALUES (?, ?, ?, ?)",
                           (data.nombre.strip(), data.tipo, data.saldo_inicial, orden))
    return {"status": "success", "id": cur.lastrowid}


@router.post("/debts")
def api_create_debt(data: DebtIn):
    with get_db() as conn:
        cur = conn.execute("INSERT INTO fin_debts (persona, importe, direccion, concepto, fecha, vence, notas) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (data.persona.strip(), data.importe, data.direccion, (data.concepto or "").strip() or None,
                            data.fecha or date.today().isoformat(), data.vence, (data.notas or "").strip() or None))
    return {"status": "success", "id": cur.lastrowid}


@router.post("/wishes")
def api_create_wish(data: WishIn):
    with get_db() as conn:
        orden = conn.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM fin_wishes").fetchone()[0]
        cur = conn.execute("INSERT INTO fin_wishes (nombre, precio, url, prioridad, notas, orden) VALUES (?, ?, ?, ?, ?, ?)",
                           (data.nombre.strip(), data.precio, (data.url or "").strip() or None, data.prioridad, (data.notas or "").strip() or None, orden))
    return {"status": "success", "id": cur.lastrowid}


PATCHES = {"accounts": AccountPatch, "movements": MovementPatch, "debts": DebtPatch, "wishes": WishPatch, "recurring": RecurringPatch}


@router.patch("/{kind}/{rid}")
def api_patch(kind: str, rid: int, body: dict):
    if kind not in TABLES:
        raise HTTPException(status_code=404, detail="No existe")
    try:
        data = PATCHES[kind](**body)
    except ValueError as e:  # pydantic: mensaje legible
        raise HTTPException(status_code=422, detail=str(e).split("\n")[-1].replace("Value error, ", ""))
    with get_db() as conn:
        _get(conn, TABLES[kind], rid)
        if kind == "movements":
            _account_ok(conn, data.cuenta_id)
            _account_ok(conn, data.cuenta_destino)
        if kind == "recurring":
            _account_ok(conn, data.cuenta_id)
            r = _get(conn, "fin_recurring", rid)
            if data.activo and not r["activo"]:
                # al reactivarlo no se apunta lo de los meses en pausa: sigue desde ahora
                today, dia = date.today(), data.dia or r["dia"]
                cur = today.strftime("%Y-%m")
                conn.execute("UPDATE fin_recurring SET ultimo=? WHERE id=?", (cur if today.day > dia else _shift(cur, -1), rid))
        _patch(conn, TABLES[kind], rid, data)
    return {"status": "success"}


@router.delete("/{kind}/{rid}")
def api_delete(kind: str, rid: int):
    if kind not in TABLES:
        raise HTTPException(status_code=404, detail="No existe")
    with get_db() as conn:
        row = dict(_get(conn, TABLES[kind], rid))
        if kind == "accounts" and conn.execute("SELECT 1 FROM fin_movements WHERE cuenta_id=? OR cuenta_destino=? LIMIT 1", (rid, rid)).fetchone():
            raise HTTPException(status_code=422, detail="Tiene movimientos: archívala en vez de borrarla")
        title = row.get("concepto") or row.get("nombre") or row.get("persona") or f"{LABEL[kind]} de {row.get('importe', '')} €"
        token = undo.save(conn, f"finance.{kind}", {"table": TABLES[kind], "row": row}, title=title, count=1)
        conn.execute(f"DELETE FROM {TABLES[kind]} WHERE id=?", (rid,))
    return {"status": "success", "trash": token}


def restore(conn, payload: dict) -> int:
    """Papelera: vuelve a meter la fila tal cual (mismo id si sigue libre)."""
    table, row = payload["table"], payload["row"]
    if table not in TABLES.values():
        return 0
    if conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (row["id"],)).fetchone():
        row = {k: v for k, v in row.items() if k != "id"}
    cols = ", ".join(row)
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
    return 1


@router.post("/debts/{rid}/settle")
def api_settle(rid: int, data: SettleIn):
    """Saldar una deuda; con cuenta, se apunta el cobro (ingreso) o el pago (gasto)."""
    with get_db() as conn:
        d = _get(conn, "fin_debts", rid)
        if d["saldada_at"]:
            raise HTTPException(status_code=422, detail="Ya está saldada")
        _account_ok(conn, data.cuenta_id)
        conn.execute("UPDATE fin_debts SET saldada_at=? WHERE id=?", (time.time(), rid))
        if data.cuenta_id:
            cobro = d["direccion"] == "me-deben"
            conn.execute("INSERT INTO fin_movements (fecha, importe, tipo, categoria, concepto, cuenta_id) VALUES (?, ?, ?, ?, ?, ?)",
                         (date.today().isoformat(), d["importe"], "ingreso" if cobro else "gasto", "Devolución" if cobro else "Otros",
                          f"{'Cobro de' if cobro else 'Pago a'} {d['persona']}{f' · {d['concepto']}' if d['concepto'] else ''}", data.cuenta_id))
    return {"status": "success"}


@router.post("/wishes/{rid}/buy")
def api_buy(rid: int, data: SettleIn):
    """Comprado: sale de la lista y, si se dice el importe (o tiene precio), se apunta como gasto."""
    with get_db() as conn:
        w = _get(conn, "fin_wishes", rid)
        _account_ok(conn, data.cuenta_id)
        importe = money(data.importe) if data.importe not in (None, "") else w["precio"]
        conn.execute("UPDATE fin_wishes SET comprado_at=? WHERE id=?", (time.time(), rid))
        if importe:
            conn.execute("INSERT INTO fin_movements (fecha, importe, tipo, categoria, concepto, cuenta_id) VALUES (?, ?, 'gasto', 'Compras', ?, ?)",
                         (date.today().isoformat(), importe, w["nombre"], data.cuenta_id))
    return {"status": "success"}
