"""
Facturas de Economía (tabla fin_facturas, migración 30): un PDF o una foto que se guarda para verla o descargarla
cuando haga falta, con título, proveedor, fecha, importe y, si se quiere, el gasto al que corresponde.

  - El archivo vive en data/facturas/<uuid>.<ext> (nunca con el nombre que manda el cliente) y entra en las copias
    (backup.TREES). Se ven en el navegador solo PDF e imágenes de mapa de bits; lo demás se descarga siempre (nada de
    HTML ni SVG en línea: sería ejecutar lo subido en el origen del panel).
  - Borrar una factura va a la papelera (rows.factura): el archivo se queda en disco mientras la papelera la nombre
    y la purga diaria (`purge_files`, desde trash.purge_expired) quita lo que ya nadie nombra.
  - El gasto enlazado va por `movimiento_id` sin clave foránea: borrar el gasto no borra la factura.

    GET    /api/finance/facturas?q=&anio=&movimiento_id=   lista (más recientes primero), años con facturas y total
    POST   /api/finance/facturas                           multipart: archivo + titulo, proveedor, fecha, importe,
                                                           categoria, notas, movimiento_id (todo opcional)
    PATCH  /api/finance/facturas/{id}                      los mismos campos (sin archivo)
    DELETE /api/finance/facturas/{id}                      a la papelera (undo_token)
    GET    /api/finance/facturas/{id}/archivo?descargar=1  el archivo (en línea si se puede, o como descarga)
"""

import mimetypes
import os
import re
import time
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.database import get_db
from core import config, undo
from core.logging_config import get_logger

log = get_logger("facturas")
router = APIRouter(prefix="/api/finance/facturas")

MAX_BYTES = 25 * 1024 * 1024
INLINE = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}
EXT_RE = re.compile(r"^\.[a-z0-9]{1,10}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CAMPOS = ("titulo", "proveedor", "fecha", "importe", "categoria", "notas", "movimiento_id")


def facturas_dir() -> Path:
    return Path(config.DATA_DIR) / "facturas"


def _fecha(v: str | None) -> str | None:
    v = (v or "").strip()
    if not v:
        return None
    if not DATE_RE.match(v):
        raise ValueError("La fecha va como AAAA-MM-DD")
    try:
        date.fromisoformat(v)
    except ValueError as e:
        raise ValueError("Esa fecha no existe") from e
    return v


def _importe(v) -> float | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        n = float(str(v).replace(",", "."))
    except ValueError as e:
        raise ValueError("El importe es un número") from e
    if not (0 <= n < 1e9):
        raise ValueError("El importe no puede ser negativo")
    return round(n, 2)


class FacturaPatch(BaseModel):
    titulo: str | None = Field(default=None, max_length=200)
    proveedor: str | None = Field(default=None, max_length=120)
    fecha: str | None = Field(default=None, max_length=10)  # "" la quita
    importe: float | str | None = None  # "" lo quita
    categoria: str | None = Field(default=None, max_length=60)
    notas: str | None = Field(default=None, max_length=5000)
    movimiento_id: int | None = Field(default=None, ge=0)  # 0 lo suelta

    @field_validator("fecha")
    @classmethod
    def v_fecha(cls, v):
        return None if v is None else (_fecha(v) or "")

    @field_validator("importe")
    @classmethod
    def v_importe(cls, v):
        return None if v is None else (_importe(v) if str(v).strip() else "")


def _out(r, movs: dict | None = None) -> dict:
    mov = (movs or {}).get(r["movimiento_id"]) if r["movimiento_id"] else None
    return {
        "id": r["id"],
        "titulo": r["titulo"],
        "proveedor": r["proveedor"],
        "fecha": r["fecha"],
        "importe": r["importe"],
        "categoria": r["categoria"],
        "notas": r["notas"],
        "movimiento_id": r["movimiento_id"],
        "movimiento": mov,
        "nombre": r["nombre"],
        "mime": r["mime"],
        "bytes": r["bytes"],
        "created_at": r["created_at"],
        "pdf": r["mime"] == "application/pdf",
        "imagen": (r["mime"] or "").startswith("image/") and r["mime"] in INLINE,
        "url": f"/api/finance/facturas/{r['id']}/archivo",
    }


def _movimientos(conn, ids) -> dict:
    ids = [i for i in {*ids} if i]
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {
        r["id"]: {"id": r["id"], "concepto": r["concepto"], "fecha": r["fecha"], "importe": r["importe"]}
        for r in conn.execute(f"SELECT id, concepto, fecha, importe FROM fin_movements WHERE id IN ({marks})", ids)
    }


def _get(conn, fid: int):
    row = conn.execute("SELECT * FROM fin_facturas WHERE id=?", (fid,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    return row


def _mov_ok(conn, mid: int | None) -> None:
    if mid and not conn.execute("SELECT 1 FROM fin_movements WHERE id=?", (mid,)).fetchone():
        raise HTTPException(status_code=422, detail="Ese movimiento ya no existe")


def con_factura(conn, mov_ids: list[int]) -> dict[int, int]:
    """{movimiento_id: nº de facturas} para marcar los movimientos que llevan una."""
    if not mov_ids:
        return {}
    marks = ",".join("?" * len(mov_ids))
    return {
        r[0]: r[1]
        for r in conn.execute(
            f"SELECT movimiento_id, COUNT(*) FROM fin_facturas WHERE movimiento_id IN ({marks}) GROUP BY movimiento_id",
            mov_ids,
        )
    }


@router.get("")
def api_list(q: str | None = None, anio: str | None = None, movimiento_id: int | None = None):
    sql, args = "SELECT * FROM fin_facturas WHERE 1=1", []
    if anio and re.fullmatch(r"\d{4}", anio):
        sql += " AND substr(COALESCE(fecha, date(created_at, 'unixepoch')), 1, 4) = ?"
        args.append(anio)
    if movimiento_id:
        sql += " AND movimiento_id = ?"
        args.append(movimiento_id)
    if q and q.strip():
        sql += " AND (titulo LIKE ? OR proveedor LIKE ? OR categoria LIKE ? OR notas LIKE ? OR nombre LIKE ?)"
        args += [f"%{q.strip()}%"] * 5
    with get_db() as conn:
        rows = conn.execute(sql + " ORDER BY COALESCE(fecha, '') DESC, id DESC LIMIT 1000", args).fetchall()
        movs = _movimientos(conn, [r["movimiento_id"] for r in rows])
        anios = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT substr(COALESCE(fecha, date(created_at, 'unixepoch')), 1, 4) a FROM fin_facturas "
                "ORDER BY a DESC"
            )
            if r[0]
        ]
    facturas = [_out(r, movs) for r in rows]
    return {
        "facturas": facturas,
        "anios": anios,
        "total": round(sum(f["importe"] or 0 for f in facturas), 2),
    }


def _nombre_limpio(nombre: str) -> str:
    base = os.path.basename((nombre or "").replace("\\", "/")).strip()
    base = re.sub(r"[\x00-\x1f\x7f]", "", base)[:180]
    return base or "factura"


@router.post("")
def api_subir(
    archivo: UploadFile = File(...),
    titulo: str = Form(""),
    proveedor: str = Form(""),
    fecha: str = Form(""),
    importe: str = Form(""),
    categoria: str = Form(""),
    notas: str = Form(""),
    movimiento_id: int = Form(0),
):  # def: el disco va en un hilo
    try:
        data = FacturaPatch(
            titulo=titulo, proveedor=proveedor, fecha=fecha, importe=importe, categoria=categoria, notas=notas
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e).split("\n")[-1].replace("Value error, ", "")) from e
    nombre = _nombre_limpio(archivo.filename or "")
    if movimiento_id:
        with get_db() as conn:
            _mov_ok(conn, movimiento_id)
    ext = os.path.splitext(nombre)[1].lower()
    ext = ext if EXT_RE.match(ext) else ""
    rel = f"{uuid.uuid4().hex}{ext}"
    dest = facturas_dir() / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with open(dest, "wb") as f:
            while chunk := archivo.file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise HTTPException(status_code=413, detail="El archivo supera los 25 MB")
                f.write(chunk)
        if not total:
            raise HTTPException(status_code=400, detail="Archivo vacío")
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    mime = mimetypes.guess_type(nombre)[0] or "application/octet-stream"
    sin_ext = re.sub(r"(\.[A-Za-z0-9]{1,5})+$", "", nombre).replace("_", " ").strip() or "Factura"
    with get_db() as conn:
        fid = conn.execute(
            "INSERT INTO fin_facturas (titulo, proveedor, fecha, importe, categoria, notas, movimiento_id, nombre, "
            "archivo, mime, bytes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (data.titulo or "").strip() or sin_ext[:200],
                (data.proveedor or "").strip() or None,
                data.fecha or date.today().isoformat(),
                data.importe if data.importe != "" else None,
                (data.categoria or "").strip() or None,
                (data.notas or "").strip() or None,
                movimiento_id or None,
                nombre,
                rel,
                mime,
                total,
                time.time(),
            ),
        ).lastrowid
        row = _get(conn, fid)
        movs = _movimientos(conn, [row["movimiento_id"]])
    log.info("Factura guardada: %s (%d bytes)", rel, total)
    return _out(row, movs)


@router.patch("/{fid}")
def api_editar(fid: int, data: FacturaPatch):
    with get_db() as conn:
        _get(conn, fid)
        if data.movimiento_id:
            _mov_ok(conn, data.movimiento_id)
        sets, args = [], []
        for campo in CAMPOS:
            v = getattr(data, campo)
            if v is None:
                continue
            if campo == "titulo":
                if not v.strip():
                    raise HTTPException(status_code=422, detail="La factura necesita un título")
                v = v.strip()
            elif campo == "movimiento_id":
                v = v or None
            elif isinstance(v, str):
                v = v.strip() or None
            sets.append(f"{campo}=?")
            args.append(v)
        if sets:
            conn.execute(f"UPDATE fin_facturas SET {', '.join(sets)} WHERE id=?", (*args, fid))
        row = _get(conn, fid)
        movs = _movimientos(conn, [row["movimiento_id"]])
    return _out(row, movs)


@router.delete("/{fid}")
def api_borrar(fid: int):
    with get_db() as conn:
        row = _get(conn, fid)
        token = undo.save_rows(
            conn,
            "rows.factura",
            [("fin_facturas", undo.select(conn, "fin_facturas", "id=?", (fid,)))],
            title=row["titulo"],
        )
        conn.execute("DELETE FROM fin_facturas WHERE id=?", (fid,))
    return {"status": "success", "undo_token": token, "undo_db": "brain"}


def _ruta(rel: str) -> Path:
    base = facturas_dir().resolve()
    path = (base / rel).resolve()
    if base not in path.parents:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    return path


@router.get("/{fid}/archivo")
def api_archivo(fid: int, descargar: bool = False):
    with get_db() as conn:
        row = _get(conn, fid)
    path = _ruta(row["archivo"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="El archivo ya no está en el disco")
    inline = row["mime"] in INLINE and not descargar
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]", "_", row["nombre"]) or "factura"
    return FileResponse(
        path,
        media_type=row["mime"] if inline else "application/octet-stream",
        headers={
            "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(row['nombre'])}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=0",
        },
    )


def purge_files(now: float | None = None) -> int:
    """Borra los archivos que ya no nombra ninguna factura ni la papelera (los recién subidos, no)."""
    now = now or time.time()
    base = facturas_dir()
    if not base.is_dir():
        return 0
    with get_db() as conn:
        vivos = {r[0] for r in conn.execute("SELECT archivo FROM fin_facturas")}
        papelera = "\n".join(r[0] for r in conn.execute("SELECT payload FROM undo_log WHERE kind='rows.factura'"))
    n = 0
    for path in base.iterdir():
        if not path.is_file() or path.name in vivos or path.name in papelera:
            continue
        if path.stat().st_mtime > now - 3600:  # recién subido: puede que su fila aún no esté escrita
            continue
        path.unlink(missing_ok=True)
        n += 1
    if n:
        log.info("Facturas sin fila purgadas: %d", n)
    return n
