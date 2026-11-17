"""
Preferencias de interfaz guardadas en el servidor (tabla ui_prefs): plegado de
categorías y notas, grupos de Tareas e Inbox… Así sobreviven a reiniciar el
ordenador y se comparten entre navegadores. El navegador guarda una copia en
localStorage solo para pintar al instante (static/js/ui.js, window.Prefs).

Cada preferencia es una clave con un valor JSON (un objeto pequeño).
"""

import json
import re
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database import get_db

router = APIRouter(prefix="/api/prefs")

KEY_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
MAX_BYTES = 64_000
# Claves que solo escribe el servidor (p. ej. el hash del enlace .ics): /api/prefs ni las enseña ni deja tocarlas
PRIVATE = {"calendario.ics", "reminders.vistos"}


class PrefIn(BaseModel):
    value: dict | list | str | int | float | bool | None


def _check_key(key: str, private: bool = False) -> None:
    if not KEY_RE.match(key) or (key in PRIVATE and not private):
        raise HTTPException(status_code=422, detail="Clave de preferencia no válida")


def get_all() -> dict:
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM ui_prefs").fetchall()
    return {r["key"]: json.loads(r["value"]) for r in rows if r["key"] not in PRIVATE}


def get(key: str, default=None):
    with get_db() as conn:
        row = conn.execute("SELECT value FROM ui_prefs WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def put(key: str, value, private: bool = False) -> None:
    _check_key(key, private)
    raw = json.dumps(value, ensure_ascii=False)
    if len(raw.encode()) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Preferencia demasiado grande")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO ui_prefs (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, raw, time.time()),
        )


@router.get("")
def api_all():
    return {"prefs": get_all()}


@router.put("/{key}")
def api_put(key: str, data: PrefIn):
    put(key, data.value)
    return {"status": "success"}
