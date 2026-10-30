"""
Copias de seguridad del panel completo.

Cada copia es un .zip con:
  data/brain.db, comidas/comidas.db   copiadas con la API de backup de SQLite
                                      (coherentes aunque el panel esté escribiendo)
  notes/*.md                          las notas (fuente de verdad del Cerebro)
  versions/**                         historial de versiones de las notas
  uploads/**                          imágenes subidas y miniaturas
  estudio/calendar_sync_state.json    estado de la sincronización con iCloud
  manifest.json                       tipo, fecha, recuentos y sha256 de cada archivo

Tipos y retención: diaria (7), semanal (4), manual (10) y "antes de restaurar"
(5). La tarea programada de las 03:30 hace la diaria y, si no hay una semanal
de los últimos 7 días, la marca como semanal. Las copias con el formato
antiguo (backup_AAAAMMDD_HHMMSS.zip) se listan pero nunca se borran solas.

Restaurar siempre crea antes una copia "antes de restaurar" y se puede
limitar a partes concretas (notas, cerebro, comidas, imágenes).
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

from core import config
from core.logging_config import get_logger

log = get_logger("backup")

BACKUPS_DIR = Path(config.BACKUPS_DIR)
STATUS_FILE = BACKUPS_DIR / "status.json"
ESTUDIO_STATE = config.PROJECT_ROOT / "estudio" / "calendar_sync_state.json"

KINDS = {"diaria": 7, "semanal": 4, "manual": 10, "pre-restauracion": 5}
NAME_RE = re.compile(r"^backup_(?:(diaria|semanal|manual|pre-restauracion)_)?(\d{8}_\d{6})(?:_\d+)?\.zip$")
PARTS = ("notas", "cerebro", "comidas", "imagenes")
FORMAT_VERSION = 2

_lock = threading.Lock()


class BackupError(Exception):
    pass


# ─────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sqlite_copy(src: Path, dst: Path) -> None:
    """Copia coherente de una BD en uso (API de backup) + comprobación de integridad."""
    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=30)
    target = sqlite3.connect(dst)
    try:
        source.backup(target)
        ok = target.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise BackupError(f"La copia de {src.name} no supera integrity_check: {ok}")
    finally:
        target.close()
        source.close()


def _parse_name(name: str) -> tuple[str, float] | None:
    m = NAME_RE.match(name)
    if not m:
        return None
    kind = m.group(1) or "antigua"
    ts = datetime.strptime(m.group(2), "%Y%m%d_%H%M%S").timestamp()
    return kind, ts


def backup_path(name: str) -> Path:
    """Ruta de una copia validando el nombre (nada de rutas relativas)."""
    if not isinstance(name, str) or not _parse_name(name):
        raise BackupError("Nombre de copia no válido")
    path = BACKUPS_DIR / name
    if path.resolve().parent != BACKUPS_DIR.resolve() or not path.is_file():
        raise BackupError("No existe esa copia")
    return path


def _read_status() -> dict:
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_status(**changes) -> None:
    status = {**_read_status(), **changes}
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATUS_FILE)


# ─────────────────────────────────────────────
# Crear
# ─────────────────────────────────────────────

def _sources() -> list[tuple[str, Path]]:
    """(nombre dentro del zip, ruta en disco) de los archivos normales."""
    files = []
    notes = Path(config.NOTES_DIR)
    if notes.is_dir():
        files += [(f"notes/{p.name}", p) for p in sorted(notes.glob("*.md"))]
    uploads = Path(config.UPLOADS_DIR)
    if uploads.is_dir():
        files += [(f"uploads/{p.relative_to(uploads).as_posix()}", p) for p in sorted(uploads.rglob("*")) if p.is_file()]
    versions = Path(config.DATA_DIR) / "versions"
    if versions.is_dir():
        files += [(f"versions/{p.relative_to(versions).as_posix()}", p) for p in sorted(versions.rglob("*.md"))]
    if ESTUDIO_STATE.is_file():
        files.append(("estudio/calendar_sync_state.json", ESTUDIO_STATE))
    return files


def create_backup(kind: str = "manual") -> dict:
    if kind not in KINDS:
        raise BackupError("Tipo de copia no válido")
    if not _lock.acquire(timeout=120):
        raise BackupError("Ya hay otra copia en marcha")
    started = time.time()
    try:
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name, n = f"backup_{kind}_{stamp}.zip", 2
        while (BACKUPS_DIR / name).exists():
            name, n = f"backup_{kind}_{stamp}_{n}.zip", n + 1
        final = BACKUPS_DIR / name
        partial = final.with_suffix(".zip.part")
        manifest = {"format": FORMAT_VERSION, "kind": kind, "created_at": started,
                    "created": datetime.now().isoformat(timespec="seconds"), "files": {}}
        with tempfile.TemporaryDirectory(prefix="panel-backup-") as tmp:
            entries = list(_sources())
            for arc, db in (("data/brain.db", Path(config.BRAIN_DB)), ("comidas/comidas.db", Path(config.COMIDAS_DB))):
                if db.is_file():
                    copy = Path(tmp) / Path(arc).name
                    _sqlite_copy(db, copy)
                    entries.append((arc, copy))
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for arc, path in entries:
                    zf.write(path, arc)
                    manifest["files"][arc] = {"size": path.stat().st_size, "sha256": _sha256(path)}
                manifest["counts"] = {
                    "notas": sum(1 for a in manifest["files"] if a.startswith("notes/")),
                    "imagenes": sum(1 for a in manifest["files"] if a.startswith("uploads/")),
                    "bases_de_datos": sum(1 for a in manifest["files"] if a.endswith(".db")),
                }
                zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        with zipfile.ZipFile(partial) as zf:
            bad = zf.testzip()
            if bad:
                raise BackupError(f"El zip está dañado ({bad})")
        partial.replace(final)
        info = _info(final)
        _write_status(last_ok=info, last_error=None)
        log.info("Copia %s creada: %s (%d bytes, %.1fs)", kind, name, info["size_bytes"], time.time() - started)
        _rotate()
        return info
    except Exception as e:
        for leftover in BACKUPS_DIR.glob("*.zip.part"):
            leftover.unlink(missing_ok=True)
        _write_status(last_error={"at": time.time(), "kind": kind, "error": str(e)})
        log.exception("Falló la copia %s", kind)
        raise BackupError(str(e)) from e
    finally:
        _lock.release()


def run_daily_backup() -> str:
    """Tarea programada (03:30): diaria, o semanal si no hay ninguna de los últimos 7 días."""
    week_ago = time.time() - 7 * 86400
    has_weekly = any(b["kind"] == "semanal" and b["created_at"] > week_ago for b in _all())
    return create_backup("diaria" if has_weekly else "semanal")["filename"]


def _rotate() -> None:
    by_kind: dict[str, list[dict]] = {}
    for b in _all():
        by_kind.setdefault(b["kind"], []).append(b)
    for kind, keep in KINDS.items():
        for old in sorted(by_kind.get(kind, []), key=lambda b: b["created_at"], reverse=True)[keep:]:
            (BACKUPS_DIR / old["filename"]).unlink(missing_ok=True)
            log.info("Copia antigua eliminada: %s", old["filename"])


# ─────────────────────────────────────────────
# Consultar
# ─────────────────────────────────────────────

def _info(path: Path) -> dict:
    kind, ts = _parse_name(path.name)
    return {"filename": path.name, "kind": kind, "created_at": ts, "size_bytes": path.stat().st_size}


def _all() -> list[dict]:
    if not BACKUPS_DIR.is_dir():
        return []
    return [_info(p) for p in BACKUPS_DIR.iterdir() if p.is_file() and _parse_name(p.name)]


def list_backups() -> dict:
    """Lista (más reciente primero). Mantiene las claves que ya usaba la API."""
    backups = sorted(_all(), key=lambda b: b["created_at"], reverse=True)
    return {"backups": backups, "retention": KINDS}


def read_manifest(name: str) -> dict:
    with zipfile.ZipFile(backup_path(name)) as zf:
        if "manifest.json" in zf.namelist():
            return json.loads(zf.read("manifest.json"))
        # Formato antiguo: sin manifiesto, se deduce del contenido
        names = zf.namelist()
        return {"format": 1, "files": {n: {} for n in names},
                "counts": {"notas": sum(1 for n in names if n.startswith("notes/")), "imagenes": 0,
                           "bases_de_datos": sum(1 for n in names if n.endswith(".db"))}}


def status(next_run: float | None = None) -> dict:
    backups = sorted(_all(), key=lambda b: b["created_at"], reverse=True)
    st = _read_status()
    last = backups[0] if backups else None
    age_h = (time.time() - last["created_at"]) / 3600 if last else None
    health = "sin-copias" if not last else ("error" if st.get("last_error") and st["last_error"]["at"] > last["created_at"]
                                            else ("antigua" if age_h > 36 else "ok"))
    return {"health": health, "last": last, "last_error": st.get("last_error"), "next_run": next_run,
            "count": len(backups), "total_bytes": sum(b["size_bytes"] for b in backups),
            "disk_free_bytes": shutil.disk_usage(BACKUPS_DIR if BACKUPS_DIR.exists() else config.PROJECT_ROOT).free}


def delete_backup(name: str) -> None:
    backup_path(name).unlink()
    log.info("Copia borrada a mano: %s", name)


# ─────────────────────────────────────────────
# Restaurar
# ─────────────────────────────────────────────

def _safe_members(zf: zipfile.ZipFile, prefix: str) -> list[zipfile.ZipInfo]:
    out = []
    for m in zf.infolist():
        if not m.filename.startswith(prefix) or m.is_dir():
            continue
        rel = m.filename[len(prefix):]
        if not rel or rel.startswith("/") or ".." in Path(rel).parts or "\\" in rel:
            raise BackupError(f"Ruta sospechosa dentro de la copia: {m.filename}")
        out.append(m)
    return out


def _restore_db(zf: zipfile.ZipFile, arc: str, live: Path, tmp: Path) -> None:
    extracted = Path(zf.extract(arc, tmp))
    check = sqlite3.connect(extracted)
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError(f"{arc} de la copia está dañada")
        # Volcado sobre la BD viva con la API de backup: respeta las conexiones abiertas y el WAL
        target = sqlite3.connect(live, timeout=30)
        try:
            check.backup(target)
        finally:
            target.close()
    finally:
        check.close()


def restore_backup(name: str, parts: list[str] | None = None) -> dict:
    parts = [p for p in (parts or PARTS) if p in PARTS]
    if not parts:
        raise BackupError("Elige qué restaurar")
    path = backup_path(name)
    with zipfile.ZipFile(path) as zf:
        if zf.testzip():
            raise BackupError("La copia está dañada")
        names = set(zf.namelist())
        _safe_members(zf, "")  # rutas sospechosas -> error antes de tocar nada
        # Antes de tocar nada, copia del estado actual (si falla, no se restaura)
        pre = create_backup("pre-restauracion")
        if not _lock.acquire(timeout=120):
            raise BackupError("Hay una copia en marcha; inténtalo en un momento")
        done = {}
        try:
            with tempfile.TemporaryDirectory(prefix="panel-restore-") as tmp:
                tmp = Path(tmp)
                if "cerebro" in parts and "data/brain.db" in names:
                    _restore_db(zf, "data/brain.db", Path(config.BRAIN_DB), tmp)
                    done["cerebro"] = True
                if "comidas" in parts and "comidas/comidas.db" in names:
                    _restore_db(zf, "comidas/comidas.db", Path(config.COMIDAS_DB), tmp)
                    done["comidas"] = True
                if "notas" in parts:
                    members = [m for m in _safe_members(zf, "notes/") if m.filename.endswith(".md") and "/" not in m.filename[6:]]
                    if members:  # una copia sin notas no vacía la carpeta
                        notes = Path(config.NOTES_DIR)
                        notes.mkdir(parents=True, exist_ok=True)
                        wanted = {m.filename[6:] for m in members}
                        for current in notes.glob("*.md"):
                            if current.name not in wanted:
                                current.unlink()
                        for m in members:
                            with zf.open(m) as src, open(notes / m.filename[6:], "wb") as dst:
                                shutil.copyfileobj(src, dst)
                        done["notas"] = len(members)
                if "imagenes" in parts:
                    uploads = Path(config.UPLOADS_DIR)
                    added = 0
                    for m in _safe_members(zf, "uploads/"):
                        target = uploads / m.filename[8:]
                        if not target.exists():  # las imágenes actuales nunca se pisan
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(m) as src, open(target, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            added += 1
                    done["imagenes"] = added
        finally:
            _lock.release()
    _write_status(last_restore={"at": time.time(), "from": name, "parts": parts, "pre_backup": pre["filename"]})
    log.warning("Restaurada la copia %s (%s); estado anterior en %s", name, ", ".join(parts), pre["filename"])
    return {"restored": done, "pre_backup": pre["filename"]}
