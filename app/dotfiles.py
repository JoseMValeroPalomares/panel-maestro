"""
Dotfiles (/api/dotfiles): ver qué ha cambiado en la configuración del sistema y subirla a GitHub con un botón.

En este equipo las configuraciones son archivos reales, no enlaces al repo (los enlaces de Stow solo existen tras una
instalación nueva), así que `git add` no vería nada: antes hay que traer a stow/ y seeds/ lo que cambió en ~.
Tampoco vale copiar sin más: el repo es público y está limpio (sin rastro del autor original, archivos renombrados) y esa
limpieza no existe en ~. Por eso cada archivo se fusiona a tres bandas con `git merge-file`:
  antepasado = cómo estaba en ~ la última vez (data/dotfiles_base/ o, si nunca se subió, el commit config.DOTFILES_BASE)
  repo = lo limpio; vivo = ~ ahora
Entra lo que cambió y la limpieza se queda. Lo que solo difiere por la limpieza no cuenta como cambio.

Reglas:
- ~ no se toca nunca: aquí solo se escribe en el repo y en data/dotfiles_base/.
- Nada se borra del repo: lo que falta en ~ se avisa y se conserva (hay archivos que solo viven en el repo).
- Archivos nuevos: solo los creados tras la última subida (antes de la primera, tras la copia base), en carpetas de las
  que el repo ya guarda algo y que pasen el .gitignore. Lo anterior se dejó fuera a propósito; una carpeta nueva es un
  componente nuevo.
- Si un archivo choca se queda fuera de la subida y se avisa; el resto sube.
- Antes de subir pasa scripts/check-secrets.sh: si falla o no está, no se sube nada y el repo queda como estaba.
- Nunca se fuerza el push.
"""
import difflib
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from core import config
from core.logging_config import get_logger

log = get_logger("dotfiles")
router = APIRouter(prefix="/api/dotfiles")

BASE_DIR = config.DATA_DIR / "dotfiles_base"
UPLOADED_MARK = ".ultima-subida"
TREES = ("stow", "seeds")
LINK_MODE = "120000"
MAX_NEW_BYTES = 1024 * 1024
MAX_DIFF_LINES = 400
# Copias, restos de editores y estado de aplicaciones: nunca son configuración nueva
NOT_NEW = re.compile(r"\.bak([.-]|$)|\.(orig|old|save|swp|tmp|log|pid)$|~$|(^|/)\.gitignore$|^\.config/Code - OSS/")
_lock = threading.Lock()


class RepoError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass
class Change:
    path: str              # ruta dentro del repo
    kind: str              # modificado | nuevo | enlace | conflicto | repo (cambio hecho directamente en el repo)
    before: bytes | None   # lo que hay ahora en el repo (None: no existe)
    after: bytes | None    # lo que quedará (en «enlace», el destino; en «conflicto», lo que hay en ~)
    live: Path | None = None
    live_bytes: bytes | None = None


# ─────────────────────────────────────────────
# Git
# ─────────────────────────────────────────────

def git_env() -> dict:
    return {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C",
            "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=15"}  # sin clave utilizable falla, no se cuelga


def run_git(repo: Path, *args: str, timeout: int = 30, check: bool = True, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    try:
        run = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, input=stdin, timeout=timeout, env=git_env())
    except subprocess.TimeoutExpired:
        raise RepoError(504, f"Git no respondió a tiempo ({args[0]})")
    if check and run.returncode:
        raise RepoError(502, f"git {args[0]}: {run.stderr.decode(errors='replace').strip()[-300:]}")
    return run


def _git(*args: str, **options) -> subprocess.CompletedProcess:
    return run_git(config.DOTFILES_DIR, *args, **options)


def _text(run: subprocess.CompletedProcess) -> str:
    return os.fsdecode(run.stdout).strip()


def _tree(ref: str) -> dict[str, tuple[str, str]]:
    """{ruta: (modo, sha)} de stow/ y seeds/ en un commit."""
    out = {}
    for record in _git("ls-tree", "-r", "-z", ref, "--", *TREES).stdout.split(b"\0"):
        if record:
            meta, path = record.split(b"\t", 1)
            mode, _, sha = meta.decode().split()
            out[os.fsdecode(path)] = (mode, sha)
    return out


def _renames(ref: str) -> dict[str, str]:
    """{ruta actual: ruta en `ref`} de lo que el repo renombró (en ~ sigue con el nombre antiguo)."""
    fields = os.fsdecode(_git("diff", "--name-status", "-M50%", "-z", ref, "HEAD", "--", *TREES).stdout).split("\0")
    out, i = {}, 0
    while i < len(fields) - 1:
        if fields[i][0] == "R":
            out[fields[i + 2]] = fields[i + 1]
            i += 3
        else:
            i += 2
    return out


def _blob(content: bytes) -> str:
    """El sha que git daría a este contenido: compara con el árbol sin leer el repo."""
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def _counts() -> tuple[int, int]:
    """Commits (por subir, por bajar) respecto a la rama remota; (0, 0) si no tiene."""
    run = _git("rev-list", "--left-right", "--count", "HEAD...@{u}", check=False)
    if run.returncode:
        return 0, 0
    ahead, behind = _text(run).split()
    return int(ahead), int(behind)


def is_available() -> bool:
    return (config.DOTFILES_DIR / ".git").exists() and _git("rev-parse", "--verify", "-q", "HEAD", check=False).returncode == 0


# ─────────────────────────────────────────────
# Qué ha cambiado
# ─────────────────────────────────────────────

def _home_path(repo_path: str) -> str:
    """stow/<componente>/.config/x -> .config/x"""
    return repo_path.split("/", 2)[2]


def read_entry(path: Path) -> bytes | None:
    try:
        return os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
    except OSError:
        return None


def _merge(repo: bytes, ancestor: bytes | None, live: bytes) -> bytes | None:
    """Fusión a tres bandas; None si choca. Sin antepasado o sin tocar en el repo, manda ~."""
    if ancestor is None or ancestor == repo:
        return live
    if b"\0" in repo + ancestor + live:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        names = []
        for name, content in (("repo", repo), ("base", ancestor), ("vivo", live)):
            Path(tmp, name).write_bytes(content)
            names.append(name)
        run = subprocess.run(["git", "merge-file", "-p", *names], cwd=tmp, capture_output=True, timeout=30)
    return run.stdout if run.returncode == 0 else None


def _scan_link(path: str, sha: str, live: Path) -> Change | None:
    if not live.is_symlink():
        return None
    target = os.readlink(live)
    if _blob(target.encode()) == sha:
        return None
    home = f"{config.DOTFILES_HOME}/"
    if target.startswith(home):  # dentro de ~ van relativos en el repo: «/home/x/.config/a» y «.config/a» son el mismo
        target = os.path.relpath(target, live.parent)
        if _blob(target.encode()) == sha:
            return None
    return Change(path, "enlace", read_entry(config.DOTFILES_DIR / path), target.encode())


def _scan_file(path: str, sha: str, live: Path, base_sha: str | None) -> Change | None:
    content = read_entry(live) if not live.is_symlink() else read_entry(live.resolve())
    if content is None:
        return None
    digest = _blob(content)
    if digest == sha:
        return None
    saved = BASE_DIR / path
    ancestor = saved.read_bytes() if saved.is_file() else None
    if digest == (_blob(ancestor) if ancestor is not None else base_sha):
        return None  # en ~ sigue igual: la diferencia es la limpieza del repo
    if ancestor is None and base_sha:
        ancestor = _git("cat-file", "blob", base_sha).stdout
    current = read_entry(config.DOTFILES_DIR / path)
    if current is None:
        return None  # borrado a mano en el repo: lo cuenta _dirty
    merged = _merge(current, ancestor, content)
    if merged is None:
        return Change(path, "conflicto", current, content, live, content)
    return None if merged == current else Change(path, "modificado", current, merged, live, content)


def _new_since(base_ref: str) -> float:
    try:
        return float((BASE_DIR / UPLOADED_MARK).read_text())
    except (OSError, ValueError):
        return int(_text(_git("log", "-1", "--format=%ct", base_ref or "HEAD")))


def _new_files(head: dict, sources: set[str], since: float) -> list[Change]:
    owners: dict[str, Counter] = {}
    for path in head:
        top, component, rel = path.split("/", 2)
        owners.setdefault(os.path.dirname(rel), Counter())[f"{top}/{component}"] += 1
    found: dict[str, Path] = {}
    for folder, components in owners.items():
        if not folder:
            continue
        try:
            entries = list(os.scandir(config.DOTFILES_HOME / folder))
        except OSError:
            continue
        for entry in entries:
            rel = f"{folder}/{entry.name}"
            if rel in sources or NOT_NEW.search(rel) or not entry.is_file(follow_symlinks=False):
                continue
            info = entry.stat(follow_symlinks=False)
            if info.st_mtime > since and info.st_size <= MAX_NEW_BYTES:
                found[f"{components.most_common(1)[0][0]}/{rel}"] = Path(entry.path)
    if not found:
        return []
    listed = _git("check-ignore", "--stdin", "-z", check=False, stdin=b"\0".join(os.fsencode(p) for p in found)).stdout
    ignored = {os.fsdecode(p) for p in listed.split(b"\0") if p}
    changes = []
    for path, live in found.items():
        content = read_entry(live)
        if path not in ignored and content is not None and b"\0" not in content:
            changes.append(Change(path, "nuevo", None, content, live, content))
    return changes


def _dirty(seen: set[str]) -> list[Change]:
    """Lo cambiado directamente en el repo, sin pasar por ~."""
    out = _git("status", "--porcelain", "-z", "--no-renames", "-uall").stdout
    changes = []
    for record in out.split(b"\0"):
        path = os.fsdecode(record[3:])
        if path and path not in seen:
            head = _git("show", f"HEAD:{path}", check=False)
            changes.append(Change(path, "repo", head.stdout if head.returncode == 0 else None, read_entry(config.DOTFILES_DIR / path)))
    return changes


def _scan() -> tuple[list[Change], list[str], dict]:
    """(cambios, archivos que ya no están en ~, árbol de HEAD). No escribe nada."""
    base_ref = config.DOTFILES_BASE
    base, renames = {}, {}
    if base_ref:
        if _git("rev-parse", "-q", "--verify", f"{base_ref}^{{commit}}", check=False).returncode:
            # sin él, toda la limpieza parecería un cambio y se desharía al subir
            raise RepoError(409, f"No encuentro el commit base ({base_ref}) en el repo. Revisa PANEL_DOTFILES_BASE.")
        base, renames = _tree(base_ref), _renames(base_ref)
    head = _tree("HEAD")
    changes, missing, sources = [], [], set()
    for path, (mode, sha) in head.items():
        rel = _home_path(path)
        if rel == "README.md":  # la documentación de cada componente solo vive en el repo
            continue
        old = renames.get(path, path)
        source = _home_path(old)
        sources.update((rel, source))
        live = config.DOTFILES_HOME / source
        if mode == LINK_MODE:
            change = _scan_link(path, sha, live)
        elif live.is_dir():
            continue
        elif not live.exists():
            missing.append(path)
            continue
        else:
            change = _scan_file(path, sha, live, base.get(old, (None, None))[1])
        if change:
            changes.append(change)
    changes += _new_files(head, sources, _new_since(base_ref))
    changes += _dirty({c.path for c in changes})
    return changes, missing, head


def _component(path: str) -> str:
    parts = path.split("/")
    return parts[1] if parts[0] in TREES and len(parts) > 2 else "repositorio"


def _web_url() -> str | None:
    url = _text(_git("remote", "get-url", "origin", check=False))
    match = re.fullmatch(r"(?:git@github\.com:|https://github\.com/)(.+?)(?:\.git)?", url)
    return f"https://github.com/{match[1]}" if match else None


def status() -> dict:
    if not is_available():
        return {"available": False, "repo": str(config.DOTFILES_DIR)}
    changes, missing, head = _scan()
    ahead, behind = _counts()
    log_lines = _text(_git("log", "-12", "--format=%h%x00%ct%x00%s")).splitlines()
    commits = []
    for i, line in enumerate(log_lines):
        short, when, subject = line.split("\0", 2)
        commits.append({"hash": short, "date": int(when), "subject": subject, "pushed": i >= ahead})
    pushed = _git("log", "-1", "--format=%ct", "@{u}", check=False)
    components = Counter(_component(path) for path in head)
    return {
        "available": True,
        "repo": str(config.DOTFILES_DIR),
        "branch": _text(_git("branch", "--show-current")),
        "web_url": _web_url(),
        "ahead": ahead,
        "behind": behind,
        "last_push": int(_text(pushed)) if pushed.returncode == 0 else None,
        "changes": [{"path": c.path, "kind": c.kind, "component": _component(c.path)} for c in changes],
        "missing": missing,
        "commits": commits,
        "components": [{"name": name, "files": files} for name, files in sorted(components.items())],
        "total_files": len(head),
    }


def file_diff(path: str) -> dict:
    """Solo de lo que está en la lista de cambios: la ruta no se usa para abrir nada."""
    if not is_available():
        raise RepoError(404, "No hay repositorio de dotfiles")
    change = next((c for c in _scan()[0] if c.path == path), None)
    if change is None:
        raise RepoError(404, "Ese archivo no tiene cambios")
    return diff_payload(path, change.kind, change.before, change.after)


def diff_payload(path: str, kind: str, before: bytes | None, after: bytes | None) -> dict:
    before, after = before or b"", after or b""
    if b"\0" in before + after:
        return {"path": path, "kind": kind, "binary": True, "lines": [], "truncated": False}
    lines = list(difflib.unified_diff(before.decode(errors="replace").splitlines(),
                                      after.decode(errors="replace").splitlines(), lineterm="", n=3))[2:]
    return {"path": path, "kind": kind, "binary": False, "lines": lines[:MAX_DIFF_LINES], "truncated": len(lines) > MAX_DIFF_LINES}


# ─────────────────────────────────────────────
# Subir
# ─────────────────────────────────────────────

def _apply(changes: list[Change]) -> None:
    for change in changes:
        target = config.DOTFILES_DIR / change.path
        if change.kind == "enlace":
            target.unlink(missing_ok=True)
            target.symlink_to(change.after.decode())
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(change.after)
            shutil.copymode(change.live, target)


def _undo(changes: list[Change]) -> None:
    for change in changes:
        target = config.DOTFILES_DIR / change.path
        if change.kind == "enlace":
            target.unlink(missing_ok=True)
            target.symlink_to(change.before.decode())
        elif change.before is None:
            target.unlink(missing_ok=True)
        else:
            target.write_bytes(change.before)


def _check_secrets() -> None:
    """scripts/check-secrets.sh del propio repo. Si no se puede comprobar, no se sube."""
    script = config.DOTFILES_DIR / "scripts" / "check-secrets.sh"
    if not script.is_file():
        raise RepoError(422, "Falta scripts/check-secrets.sh en el repo: sin comprobar secretos no se sube nada.")
    try:
        run = subprocess.run(["bash", str(script)], cwd=config.DOTFILES_DIR, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise RepoError(504, "La comprobación de secretos tardó demasiado: no se ha subido nada.")
    if run.returncode == 0:
        return
    # Solo el sitio, nunca el texto encontrado: este mensaje acaba en la pantalla y en el registro
    lines = run.stdout.splitlines()
    places = [m[1] for line in lines if (m := re.match(r"\s+! (.+?:\d+):", line))]
    names = [line for line in lines if line and not line.startswith((" ", "==>", "Posibles", "Todo"))]
    found = ", ".join((places + names)[:8]) or "revisa ./scripts/check-secrets.sh"
    raise RepoError(422, f"Posibles secretos en {found}. No se ha subido nada.")


def _save_ancestors(changes: list[Change], scanned_at: float) -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    (BASE_DIR / UPLOADED_MARK).write_text(str(scanned_at))
    for change in changes:
        if change.live_bytes is not None:
            saved = BASE_DIR / change.path
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(change.live_bytes)


def _commit(applied: list[Change], scanned_at: float) -> str | None:
    _git("add", "-A")
    staged = [p for p in _git("diff", "--cached", "--name-only", "-z").stdout.split(b"\0") if p]
    if not staged:
        return None
    names = sorted({_component(os.fsdecode(p)) for p in staged})
    summary = ", ".join(names[:4]) + ("…" if len(names) > 4 else "")
    _git("commit", "-m", f"Actualiza la configuración desde el panel: {len(staged)} archivo(s) ({summary})")
    _save_ancestors(applied, scanned_at)
    return _text(_git("rev-parse", "--short", "HEAD"))


def _send() -> None:
    try:
        _git("fetch", timeout=90)
        if _counts()[1] and _git("rebase", "@{u}", check=False, timeout=60).returncode:
            _git("rebase", "--abort", check=False)
            raise RepoError(409, "GitHub tiene cambios que chocan con los de aquí. Queda guardado en ~/dotfiles sin subir: "
                                     "resuélvelo allí a mano.")
        if _counts()[0]:
            _git("push", timeout=120)
    except RepoError as e:
        if e.status == 409:
            raise
        log.warning("Dotfiles: %s", e.detail)
        raise RepoError(502, "No he podido conectar con GitHub (¿sin red o sin acceso con la clave SSH?). Queda guardado "
                                 "en ~/dotfiles: vuelve a pulsar «Subir a GitHub» y se enviará.")


def publish() -> dict:
    """Trae ~ al repo, comprueba secretos, hace commit y sube. Una sola subida a la vez."""
    if not _lock.acquire(blocking=False):
        raise RepoError(409, "Ya hay una subida en marcha")
    try:
        if not is_available():
            raise RepoError(404, "No hay repositorio de dotfiles")
        if not _text(_git("branch", "--show-current")) or _git("rev-parse", "--verify", "-q", "@{u}", check=False).returncode:
            raise RepoError(409, "El repo no está en una rama con remoto (¿rebase a medias?): revísalo en ~/dotfiles.")
        scanned_at = time.time()
        changes = _scan()[0]
        conflicts = [c.path for c in changes if c.kind == "conflicto"]
        applied = [c for c in changes if c.kind in ("modificado", "nuevo", "enlace")]
        _apply(applied)
        try:
            _check_secrets()
            commit = _commit(applied, scanned_at)
        except Exception:
            _undo(applied)  # lo que no se sube no se queda a medias en el repo
            raise
        if not commit and not _counts()[0]:
            return {"status": "al-dia", "files": 0, "commit": None, "conflicts": conflicts}
        _send()
        log.info("Dotfiles subidos: commit %s, %d archivos", commit, len(changes))
        return {"status": "subido", "files": len(changes) - len(conflicts), "commit": commit, "conflicts": conflicts}
    finally:
        _lock.release()


# ─────────────────────────────────────────────
# Rutas
# ─────────────────────────────────────────────

def route_call(fn, *args):
    try:
        return fn(*args)
    except RepoError as e:
        if e.status >= 500:
            log.warning("Dotfiles: %s", e.detail)
        raise HTTPException(status_code=e.status, detail=e.detail)


@router.get("")
def get_dotfiles():
    return route_call(status)


@router.get("/diff")
def get_dotfiles_diff(path: str = Query(max_length=1024)):
    return route_call(file_diff, path)


@router.post("/push")
def push_dotfiles():
    return route_call(publish)
