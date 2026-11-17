"""
Universidad · ejercicios: modelo propio, de una asignatura y asociable a uno o varios de sus temas.

`uni_ejercicios` (título, enunciado, notas/solución, estado pendiente/hecho, dificultad 1-3, el PDF y la página
donde está) + `uni_ejercicio_temas` (los temas). Se listan con filtros (asignatura, tema, estado, dificultad,
texto) para la vista global y para la de cada tema. Borrar va a la papelera (`rows.ejercicio`, con sus temas).
Un tema fusionado cuenta como el tema con el que se fusionó.
"""

import time

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app import contextos
from app.database import get_db
from app.universidad import get_asig
from core import undo

router = APIRouter(prefix="/api/uni/ejercicios")

ESTADOS = ("pendiente", "hecho")
DIFICULTADES = {1: "fácil", 2: "media", 3: "difícil"}


def _v_estado(v):
    if v is not None and v not in ESTADOS:
        raise ValueError("Estado: pendiente o hecho")
    return v


class EjercicioIn(BaseModel):
    asignatura_id: int
    titulo: str = Field(min_length=1, max_length=300)
    enunciado: str | None = Field(default=None, max_length=20000)
    notas: str | None = Field(default=None, max_length=20000)
    estado: str = Field(default="pendiente", max_length=12)
    dificultad: int | None = Field(default=None, ge=1, le=3)
    temas: list[int] = Field(default_factory=list, max_length=50)
    archivo_id: int | None = None
    pagina: int | None = Field(default=None, ge=1, le=100000)

    @field_validator("estado")
    @classmethod
    def v_estado(cls, v):
        return _v_estado(v)


class EjercicioPatch(BaseModel):
    titulo: str | None = Field(default=None, min_length=1, max_length=300)
    enunciado: str | None = Field(default=None, max_length=20000)
    notas: str | None = Field(default=None, max_length=20000)
    estado: str | None = Field(default=None, max_length=12)
    dificultad: int | None = Field(default=None, ge=0, le=3)  # 0 = sin dificultad
    temas: list[int] | None = Field(default=None, max_length=50)
    archivo_id: int | None = None  # 0 = sin archivo
    pagina: int | None = Field(default=None, ge=0, le=100000)  # 0 = sin página
    before_id: int | None = None  # reordenar dentro de la asignatura (0 = al final)

    @field_validator("estado")
    @classmethod
    def v_estado(cls, v):
        return _v_estado(v)


def _temas_validos(conn, asig_id: int, temas: list[int]) -> list[int]:
    """Los temas tienen que ser de la asignatura; uno fusionado cuenta como su destino."""
    out: list[int] = []
    for tid in temas:
        r = conn.execute("SELECT id, asignatura_id, fusionado_en FROM temas WHERE id=?", (tid,)).fetchone()
        if not r or r["asignatura_id"] != asig_id:
            raise HTTPException(status_code=422, detail="Un ejercicio solo va a temas de su asignatura")
        final = r["fusionado_en"] or r["id"]
        if final not in out:
            out.append(final)
    return out


def _archivo_valido(conn, asig_id: int, archivo_id: int | None) -> int | None:
    if not archivo_id:
        return None
    r = conn.execute("SELECT asignatura_id FROM uni_archivos WHERE id=?", (archivo_id,)).fetchone()
    if not r or r["asignatura_id"] != asig_id:
        raise HTTPException(status_code=422, detail="Ese archivo no es de la asignatura")
    return archivo_id


def _get(conn, ej_id: int):
    r = conn.execute("SELECT * FROM uni_ejercicios WHERE id=?", (ej_id,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Ejercicio no encontrado")
    return r


def _out(r, temas: list[int], archivo) -> dict:
    return {
        "id": r["id"],
        "asignatura_id": r["asignatura_id"],
        "titulo": r["titulo"],
        "enunciado": r["enunciado"] or "",
        "notas": r["notas"] or "",
        "estado": r["estado"],
        "dificultad": r["dificultad"],
        "temas": temas,
        "archivo": archivo,
        "pagina": r["pagina"],
        "orden": r["orden"],
        "hecho_at": r["hecho_at"],
        "created_at": r["created_at"],
    }


def listar(
    asignatura: int | None = None,
    tema: int | None = None,
    estado: str | None = None,
    dificultad: int | None = None,
    q: str | None = None,
) -> list[dict]:
    with get_db() as conn:
        where, args = ["1=1"], []
        if asignatura:
            where.append("e.asignatura_id=?")
            args.append(asignatura)
        if estado in ESTADOS:
            where.append("e.estado=?")
            args.append(estado)
        if dificultad in DIFICULTADES:
            where.append("e.dificultad=?")
            args.append(dificultad)
        elif dificultad == 0:
            where.append("e.dificultad IS NULL")
        if tema:
            r = conn.execute("SELECT fusionado_en FROM temas WHERE id=?", (tema,)).fetchone()
            final = (r["fusionado_en"] if r and r["fusionado_en"] else tema) if r else tema
            where.append("e.id IN (SELECT ejercicio_id FROM uni_ejercicio_temas WHERE tema_id=?)")
            args.append(final)
        rows = conn.execute(
            f"SELECT e.* FROM uni_ejercicios e JOIN asignaturas a ON a.id=e.asignatura_id "
            f"WHERE {' AND '.join(where)} ORDER BY a.orden, e.asignatura_id, e.orden, e.id",
            args,
        ).fetchall()
        ids = [r["id"] for r in rows]
        temas: dict[int, list[int]] = {}
        archivos: dict[int, dict] = {}
        if ids:
            marcas = ",".join("?" * len(ids))
            for t in conn.execute(
                f"SELECT et.ejercicio_id, et.tema_id FROM uni_ejercicio_temas et JOIN temas t ON t.id=et.tema_id "
                f"WHERE et.ejercicio_id IN ({marcas}) ORDER BY t.orden, t.id",
                ids,
            ):
                temas.setdefault(t["ejercicio_id"], []).append(t["tema_id"])
            arch_ids = sorted({r["archivo_id"] for r in rows if r["archivo_id"]})
            if arch_ids:
                for a in conn.execute(
                    f"SELECT id, nombre, ext, falta_desde FROM uni_archivos WHERE id IN ({','.join('?' * len(arch_ids))})",
                    arch_ids,
                ):
                    archivos[a["id"]] = {
                        "id": a["id"],
                        "nombre": a["nombre"],
                        "visor": a["ext"] == "pdf",
                        "falta": a["falta_desde"] is not None,
                    }
    out = [_out(r, temas.get(r["id"], []), archivos.get(r["archivo_id"])) for r in rows]
    if q and q.strip():
        k = contextos.fold(q.strip())
        out = [e for e in out if k in contextos.fold(f"{e['titulo']} {e['enunciado']} {e['notas']}")]
    return out


def crear(data: EjercicioIn) -> int:
    with get_db() as conn:
        get_asig(conn, data.asignatura_id)
        temas = _temas_validos(conn, data.asignatura_id, data.temas)
        archivo = _archivo_valido(conn, data.asignatura_id, data.archivo_id)
        orden = conn.execute(
            "SELECT COALESCE(MAX(orden), 0) FROM uni_ejercicios WHERE asignatura_id=?", (data.asignatura_id,)
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO uni_ejercicios (asignatura_id, titulo, enunciado, notas, estado, dificultad, archivo_id, "
            "pagina, orden, hecho_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data.asignatura_id,
                data.titulo.strip(),
                (data.enunciado or "").strip() or None,
                (data.notas or "").strip() or None,
                data.estado,
                data.dificultad,
                archivo,
                data.pagina if archivo else None,
                orden + 1,
                time.time() if data.estado == "hecho" else None,
            ),
        )
        eid = cur.lastrowid
        conn.executemany(
            "INSERT OR IGNORE INTO uni_ejercicio_temas (ejercicio_id, tema_id) VALUES (?, ?)", [(eid, t) for t in temas]
        )
    return eid


def editar(ej_id: int, data: EjercicioPatch) -> None:
    with get_db() as conn:
        r = _get(conn, ej_id)
        asig = r["asignatura_id"]
        sets: dict = {}
        if data.titulo is not None:
            sets["titulo"] = data.titulo.strip()
        for campo in ("enunciado", "notas"):
            v = getattr(data, campo)
            if v is not None:
                sets[campo] = v.strip() or None
        if data.estado is not None and data.estado != r["estado"]:
            sets["estado"] = data.estado
            sets["hecho_at"] = time.time() if data.estado == "hecho" else None
        if data.dificultad is not None:
            sets["dificultad"] = data.dificultad or None
        if data.archivo_id is not None:
            sets["archivo_id"] = _archivo_valido(conn, asig, data.archivo_id)
            if not sets["archivo_id"]:
                sets["pagina"] = None
        if data.pagina is not None:
            sets["pagina"] = data.pagina or None
        if sets:
            sets["updated_at"] = time.time()
            cols = ", ".join(f"{c}=?" for c in sets)  # columnas fijas de este modelo, nunca del cliente
            conn.execute(f"UPDATE uni_ejercicios SET {cols} WHERE id=?", (*sets.values(), ej_id))
        if data.temas is not None:
            temas = _temas_validos(conn, asig, data.temas)
            conn.execute("DELETE FROM uni_ejercicio_temas WHERE ejercicio_id=?", (ej_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO uni_ejercicio_temas (ejercicio_id, tema_id) VALUES (?, ?)",
                [(ej_id, t) for t in temas],
            )
        if data.before_id is not None:
            ids = [
                x["id"]
                for x in conn.execute(
                    "SELECT id FROM uni_ejercicios WHERE asignatura_id=? AND id != ? ORDER BY orden, id", (asig, ej_id)
                )
            ]
            pos = ids.index(data.before_id) if data.before_id in ids else len(ids)
            ids.insert(pos, ej_id)
            for i, x in enumerate(ids):
                conn.execute("UPDATE uni_ejercicios SET orden=? WHERE id=?", (i + 1, x))


def borrar(ej_id: int) -> str:
    with get_db() as conn:
        r = _get(conn, ej_id)
        token = undo.save_rows(
            conn,
            "rows.ejercicio",
            [
                ("uni_ejercicios", undo.select(conn, "uni_ejercicios", "id=?", (ej_id,))),
                ("uni_ejercicio_temas", undo.select(conn, "uni_ejercicio_temas", "ejercicio_id=?", (ej_id,))),
            ],
            title=r["titulo"],
        )
        conn.execute("DELETE FROM uni_ejercicio_temas WHERE ejercicio_id=?", (ej_id,))
        conn.execute("DELETE FROM uni_ejercicios WHERE id=?", (ej_id,))
    return token


@router.get("")
def api_listar(
    asignatura: int | None = None,
    tema: int | None = None,
    estado: str | None = Query(default=None, max_length=12),
    dificultad: int | None = Query(default=None, ge=0, le=3),
    q: str | None = Query(default=None, max_length=200),
):
    lista = listar(asignatura, tema, estado, dificultad, q)
    return {"ejercicios": lista, "total": len(lista), "hechos": sum(1 for e in lista if e["estado"] == "hecho")}


@router.post("")
def api_crear(data: EjercicioIn):
    return {"id": crear(data)}


@router.patch("/{ej_id}")
def api_editar(ej_id: int, data: EjercicioPatch):
    editar(ej_id, data)
    return {"status": "success"}


@router.delete("/{ej_id}")
def api_borrar(ej_id: int):
    return {"status": "success", "undo_token": borrar(ej_id), "undo_db": "brain"}
