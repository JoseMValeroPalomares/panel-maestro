"""
Copias de seguridad del panel completo.

Cada copia es un .zip con:
  data/brain.db, comidas/comidas.db   copiadas con la API de backup de SQLite
                                      (coherentes aunque el panel esté escribiendo)
  notes/*.md                          las notas (fuente de verdad del Cerebro)
  versions/**                         historial de versiones de las notas
  uploads/**                          imágenes subidas y miniaturas
  trash/**                            notas en la papelera (sus filas están en undo_log de brain.db)
  dotfiles_base/**                    lo último subido de los dotfiles (antepasado de la fusión)
  data/llm_modelos.json               lista de modelos de IA editada en Ajustes (si existe)
  estudio/calendar_sync_*.json        estado de la sincronización del calendario
  manifest.json                       tipo, fecha, recuentos y sha256 de cada archivo

Tipos y retención: diaria (7), semanal (4), manual (10) y "antes de restaurar"
(5). La tarea programada de las 03:30 hace la diaria y, si no hay una semanal
de los últimos 7 días, la marca como semanal. Las copias con el formato
antiguo (backup_AAAAMMDD_HHMMSS.zip) se listan pero nunca se borran solas.

Restaurar siempre crea antes una copia "antes de restaurar" y se puede
limitar a partes: notas, historial (versiones), cerebro (brain.db y la papelera),
comidas, imagenes y ajustes (modelos de IA y base de los dotfiles). Lo que ya existe
en disco de historial, papelera e imágenes nunca se pisa ni se borra: solo se añade lo
que falta. Todo se escribe de forma atómica. Admite los zips de formato 1 (solo notas y
brain.db) y 2 (sin papelera ni ajustes): lo que la copia no trae no se toca.

Espejo (PANEL_BACKUP_MIRROR): tras cada copia correcta el zip se copia a esa carpeta
(otra unidad o una carpeta que sincronice Syncthing/rclone), se comprueba su sha256 y
se rota con la misma retención. Si la carpeta no está, la copia local sigue siendo
correcta y el estado lo avisa. La carpeta nunca se crea: así un disco sin montar no se
confunde con su punto de montaje vacío.
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
from core.files import atomic_write_bytes
from core.logging_config import get_logger

log = get_logger("backup")

BACKUPS_DIR = Path(config.BACKUPS_DIR)
STATUS_FILE = BACKUPS_DIR / "status.json"
# Estado heredado de la sincronía antigua: junto al de ahora (C-4: el código desplegado no está donde los datos; y una
# instancia de pruebas ya no copia el del panel real)
ESTUDIO_STATE = config.CALENDAR_STATE.with_name("calendar_sync_state.json")

KINDS = {"diaria": 7, "semanal": 4, "manual": 10, "pre-restauracion": 5}
NAME_RE = re.compile(r"^backup_(?:(diaria|semanal|manual|pre-restauracion)_)?(\d{8}_\d{6})(?:_\d+)?\.zip$")
PARTS = ("notas", "historial", "cerebro", "comidas", "imagenes", "ajustes")
FORMAT_VERSION = 3
# Carpetas copiadas enteras: (prefijo en el zip, carpeta en disco, parte que las restaura)
TREES = (
    ("versions/", lambda: Path(config.DATA_DIR) / "versions", "historial"),
    ("uploads/", lambda: Path(config.UPLOADS_DIR), "imagenes"),
    ("trash/", lambda: Path(config.TRASH_DIR), "cerebro"),
    ("dotfiles_base/", lambda: Path(config.DATA_DIR) / "dotfiles_base", "ajustes"),
)
LLM_ARC = "data/llm_modelos.json"

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
    try:
        ts = datetime.strptime(m.group(2), "%Y%m%d_%H%M%S").timestamp()
    except ValueError:  # tiene la forma pero no es una fecha (backup_20269999_000000.zip)
        return None
    return m.group(1) or "antigua", ts


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


def _is_temp(p: Path) -> bool:
    """Temporales de atomic_write (.xxx.tmp) y copias a medias: no van a la copia."""
    return p.name.startswith(".") and p.name.endswith(".tmp") or p.name.endswith(".part")


def _sources() -> list[tuple[str, Path]]:
    """(nombre dentro del zip, ruta en disco) de los archivos normales."""
    files = []
    notes = Path(config.NOTES_DIR)
    if notes.is_dir():
        files += [(f"notes/{p.name}", p) for p in sorted(notes.glob("*.md"))]
    for prefix, root, _part in TREES:
        root = root()
        if root.is_dir():
            files += [
                (f"{prefix}{p.relative_to(root).as_posix()}", p)
                for p in sorted(root.rglob("*"))
                if p.is_file() and not p.is_symlink() and not _is_temp(p)
            ]
    if Path(config.LLM_MODELS_FILE).is_file():
        files.append((LLM_ARC, Path(config.LLM_MODELS_FILE)))
    if ESTUDIO_STATE.is_file():
        files.append(("estudio/calendar_sync_state.json", ESTUDIO_STATE))
    if config.CALENDAR_STATE.is_file():
        files.append(("estudio/calendar_sync_v2.json", config.CALENDAR_STATE))
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
        manifest = {
            "format": FORMAT_VERSION,
            "kind": kind,
            "created_at": started,
            "created": datetime.now().isoformat(timespec="seconds"),
            "files": {},
        }
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
                    "versiones": sum(1 for a in manifest["files"] if a.startswith("versions/")),
                    "papelera": sum(1 for a in manifest["files"] if a.startswith("trash/")),
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
        _rotate(BACKUPS_DIR)
        mirror = _mirror(final)
        if mirror:
            info = {**info, "mirror": mirror["state"]}
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


AUTO_KINDS = ("diaria", "semanal")
CATCH_UP_H = 24


def last_auto() -> dict | None:
    """La copia automática (diaria o semanal) más reciente; las manuales no cuentan."""
    autos = [b for b in _all() if b["kind"] in AUTO_KINDS]
    return max(autos, key=lambda b: b["created_at"]) if autos else None


def ensure_recent_backup(max_age_h: float = CATCH_UP_H) -> str | None:
    """Recuperación (al arrancar y cada hora): el portátil suele estar dormido a las 03:30, así que si la última
    automática tiene más de `max_age_h` horas (o no hay ninguna) se hace ahora. Devuelve el zip creado o None.
    Nunca lanza: un fallo queda en status.json (last_error) y en el log."""
    last = last_auto()
    age_h = (time.time() - last["created_at"]) / 3600 if last else None
    if age_h is not None and age_h < max_age_h:
        return None
    log.info(
        "Última copia automática %s: se hace ahora", f"de hace {age_h:.0f} h" if age_h is not None else "inexistente"
    )
    try:
        return run_daily_backup()
    except BackupError:
        return None  # create_backup ya lo anotó en status.json y en el log


def _rotate(folder: Path) -> None:
    by_kind: dict[str, list[dict]] = {}
    for b in _all(folder):
        by_kind.setdefault(b["kind"], []).append(b)
    for kind, keep in KINDS.items():
        for old in sorted(by_kind.get(kind, []), key=lambda b: b["created_at"], reverse=True)[keep:]:
            (folder / old["filename"]).unlink(missing_ok=True)
            log.info("Copia antigua eliminada: %s%s", old["filename"], "" if folder == BACKUPS_DIR else " (espejo)")


# ─────────────────────────────────────────────
# Espejo en otra unidad (PANEL_BACKUP_MIRROR)
# ─────────────────────────────────────────────


def _mirror_dir() -> Path | None:
    return Path(config.BACKUP_MIRROR) if config.BACKUP_MIRROR else None


def _mirror(final: Path) -> dict | None:
    """Copia el zip al espejo con sha256 comprobado y rota allí. Nunca lanza: un fallo es un aviso."""
    folder = _mirror_dir()
    if folder is None:
        return None
    try:
        if not folder.is_dir():  # no se crea: un disco sin montar dejaría su punto de montaje vacío
            raise OSError(f"La carpeta del espejo no existe (¿unidad sin montar?): {folder}")
        if folder.resolve() == BACKUPS_DIR.resolve():
            raise OSError("El espejo es la misma carpeta que las copias")
        expected = _sha256(final)
        part = folder / (final.name + ".part")
        try:
            with open(final, "rb") as src, open(part, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
                dst.flush()
                os.fsync(dst.fileno())
            got = _sha256(part)
            if got != expected:
                raise OSError(f"La copia del espejo no coincide (sha256 {got[:12]}… ≠ {expected[:12]}…)")
            part.replace(folder / final.name)
        finally:
            part.unlink(missing_ok=True)
        _rotate(folder)
        same_disk = os.stat(folder).st_dev == os.stat(BACKUPS_DIR).st_dev
        state = {"state": "ok", "at": time.time(), "file": final.name, "sha256": expected, "same_disk": same_disk}
        log.info("Copia %s copiada al espejo %s", final.name, folder)
    except OSError as e:
        state = {"state": "error", "at": time.time(), "file": final.name, "error": str(e)}
        log.warning("Espejo de las copias no disponible: %s", e)
    _write_status(mirror=state)
    return state


def mirror_status() -> dict | None:
    """Estado del espejo para /api/backups/status y /api/status (None si no está configurado)."""
    folder = _mirror_dir()
    if folder is None:
        return None
    st = _read_status().get("mirror") or {}
    available = folder.is_dir()
    copies = sorted(_all(folder), key=lambda b: b["created_at"], reverse=True) if available else []
    state = "error" if not available or st.get("state") == "error" else ("ok" if copies else "pendiente")
    error = (
        st.get("error")
        if st.get("state") == "error"
        else (None if available else "La carpeta del espejo no está disponible")
    )
    return {
        "dir": str(folder),
        "state": state,
        "available": available,
        "error": error,
        "last": copies[0] if copies else None,
        "count": len(copies),
        "same_disk": st.get("same_disk"),
        "at": st.get("at"),
    }


# ─────────────────────────────────────────────
# Consultar
# ─────────────────────────────────────────────


def _info(path: Path) -> dict:
    kind, ts = _parse_name(path.name)
    return {"filename": path.name, "kind": kind, "created_at": ts, "size_bytes": path.stat().st_size}


def _all(folder: Path | None = None) -> list[dict]:
    folder = folder or BACKUPS_DIR
    if not folder.is_dir():
        return []
    return [_info(p) for p in folder.iterdir() if p.is_file() and _parse_name(p.name)]


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
        return {
            "format": 1,
            "files": {n: {} for n in names},
            "counts": {
                "notas": sum(1 for n in names if n.startswith("notes/")),
                "imagenes": 0,
                "bases_de_datos": sum(1 for n in names if n.endswith(".db")),
            },
        }


def status(next_run: float | None = None) -> dict:
    backups = sorted(_all(), key=lambda b: b["created_at"], reverse=True)
    st = _read_status()
    last = backups[0] if backups else None
    age_h = (time.time() - last["created_at"]) / 3600 if last else None
    health = (
        "sin-copias"
        if not last
        else (
            "error"
            if st.get("last_error") and st["last_error"]["at"] > last["created_at"]
            else ("antigua" if age_h > 36 else "ok")
        )
    )
    return {
        "health": health,
        "age_h": round(age_h, 1) if age_h is not None else None,
        "last": last,
        "last_error": st.get("last_error"),
        "next_run": next_run,
        "mirror": mirror_status(),
        "count": len(backups),
        "total_bytes": sum(b["size_bytes"] for b in backups),
        "disk_free_bytes": shutil.disk_usage(BACKUPS_DIR if BACKUPS_DIR.exists() else config.PROJECT_ROOT).free,
    }


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
        rel = m.filename[len(prefix) :]
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


def _restore_tree(zf: zipfile.ZipFile, prefix: str, root: Path, overwrite: bool = False) -> int:
    """Devuelve a `root` los archivos de la copia bajo `prefix`. Sin `overwrite` solo añade lo que falta: lo que ya
    hay (historial, papelera, imágenes) nunca se pisa. Nada se borra."""
    n = 0
    for m in _safe_members(zf, prefix):
        target = root / m.filename[len(prefix) :]
        if target.exists() and not overwrite:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(m) as src:
            atomic_write_bytes(target, src)
        n += 1
    return n


def _restore_notes(zf: zipfile.ZipFile) -> int | None:
    members = [m for m in _safe_members(zf, "notes/") if m.filename.endswith(".md") and "/" not in m.filename[6:]]
    if not members:  # una copia sin notas no vacía la carpeta
        return None
    notes = Path(config.NOTES_DIR)
    notes.mkdir(parents=True, exist_ok=True)
    wanted = {m.filename[6:] for m in members}
    for m in members:  # primero se escriben todas (atómicas); después se quitan las que la copia no tiene
        with zf.open(m) as src:
            atomic_write_bytes(notes / m.filename[6:], src)
    for current in notes.glob("*.md"):
        if current.name not in wanted:
            current.unlink()
    return len(members)


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
                    # Lo que la sincronía recuerda ya no cuadra con estos eventos: lo que falte en el Panel lo daría por
                    # borrado y lo quitaría de iCloud y del ESP32. Sin «última vez», los lados se unen y nada se borra
                    config.CALENDAR_STATE.unlink(missing_ok=True)
                if "comidas" in parts and "comidas/comidas.db" in names:
                    _restore_db(zf, "comidas/comidas.db", Path(config.COMIDAS_DB), tmp)
                    done["comidas"] = True
                if "notas" in parts:
                    n = _restore_notes(zf)
                    if n is not None:
                        done["notas"] = n
                for prefix, root, part in TREES:
                    if part in parts and any(x.startswith(prefix) for x in names):
                        added = _restore_tree(zf, prefix, root(), overwrite=prefix == "dotfiles_base/")
                        key = {
                            "versions/": "historial",
                            "uploads/": "imagenes",
                            "trash/": "papelera",
                            "dotfiles_base/": "dotfiles_base",
                        }[prefix]
                        done[key] = added
                if "imagenes" in parts:
                    done.setdefault("imagenes", 0)
                if "ajustes" in parts and LLM_ARC in names:
                    target = Path(config.LLM_MODELS_FILE)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    atomic_write_bytes(target, zf.read(LLM_ARC))
                    done["modelos_ia"] = True
        finally:
            _lock.release()
    _write_status(last_restore={"at": time.time(), "from": name, "parts": parts, "pre_backup": pre["filename"]})
    log.warning("Restaurada la copia %s (%s); estado anterior en %s", name, ", ".join(parts), pre["filename"])
    return {"restored": done, "pre_backup": pre["filename"]}
