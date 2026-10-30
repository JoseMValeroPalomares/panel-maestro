"""
Exportación e importación tabular (CSV/JSON) compartida por las apps.

El CSV sale con BOM para que Excel lo abra en UTF-8; al importar se acepta
tanto una lista JSON como un objeto {"<clave>": [...]}.
"""
import csv
import io
import json

from fastapi import HTTPException, UploadFile
from fastapi.responses import Response

MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_IMPORT_ROWS = 5000


def csv_response(rows: list[dict], fields: list[str], filename: str) -> Response:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for row in rows:
        w.writerow({k: ("" if v is None else v) for k, v in row.items()})
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'})


def json_response(key: str, rows: list[dict], filename: str) -> Response:
    return Response(json.dumps({key: rows}, ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{filename}.json"'})


def parse_rows(raw: bytes, filename: str, key: str) -> list[dict]:
    text = raw.decode("utf-8-sig", errors="replace")
    if filename.lower().endswith(".json") or text.lstrip().startswith(("{", "[")):
        data = json.loads(text)
        items = data.get(key, []) if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ValueError(f'El JSON debe ser una lista o {{"{key}": [...]}}')
        return [i for i in items if isinstance(i, dict)]
    return list(csv.DictReader(io.StringIO(text)))


async def read_upload(file: UploadFile, key: str) -> list[dict]:
    """Lee y parsea el archivo subido con límites de tamaño y filas (413/422)."""
    raw = await file.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera los 10 MB")
    try:
        items = parse_rows(raw, file.filename or "", key)
    except (ValueError, json.JSONDecodeError, csv.Error) as e:
        raise HTTPException(status_code=422, detail=f"No se pudo leer el archivo: {e}")
    if len(items) > MAX_IMPORT_ROWS:
        raise HTTPException(status_code=422, detail=f"Máximo {MAX_IMPORT_ROWS} filas por importación")
    return items


def split_list(value) -> list[str]:
    """Lista desde JSON (lista) o CSV ("a, b; c")."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in str(value or "").replace(";", ",").split(",") if p.strip()]


def to_float(value, default=None):
    """Número desde CSV (admite coma decimal y vacío)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value).strip().replace(",", "."))
