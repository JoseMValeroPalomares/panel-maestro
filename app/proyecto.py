"""
Proyecto (/api/proyecto): publicar el propio panel en GitHub con un botón.

main guarda el historial privado (el diario de desarrollo) y nunca se sube. El botón hace commit en main de lo pendiente y
llama a scripts/publicar.sh, que crea una instantánea sin ese historial ni lo que lista .publicignore, busca secretos y datos
personales y sube solo esa rama, sin forzar. Si algo falla no se publica nada: el commit se queda en main, que es privado.

Ese script y .publicignore no se publican: en una copia instalada desde GitHub no existen y la tarjeta no aparece.
"""
import os
import re
import subprocess
import threading
from collections import Counter

from fastapi import APIRouter, Query

from app.dotfiles import RepoError, diff_payload, git_env, read_entry, route_call, run_git
from core import config
from core.logging_config import get_logger

log = get_logger("proyecto")
router = APIRouter(prefix="/api/proyecto")

SCRIPT = "scripts/publicar.sh"
IGNORE_FILE = ".publicignore"
MAIN = "main"
REMOTE_REF = "refs/remotes/github/main"   # lo último que hay en GitHub
PUBLISHED_REF = "refs/panel/publicado"    # el commit de main que se publicó
_lock = threading.Lock()


def _git(*args: str, **options) -> subprocess.CompletedProcess:
    return run_git(config.PROJECT_DIR, *args, **options)


def _text(run: subprocess.CompletedProcess) -> str:
    return os.fsdecode(run.stdout).strip()


def _ref(name: str) -> str | None:
    run = _git("rev-parse", "-q", "--verify", name, check=False)
    return _text(run) if run.returncode == 0 else None


def is_available() -> bool:
    root = config.PROJECT_DIR
    return (root / ".git").exists() and (root / SCRIPT).is_file() and (root / IGNORE_FILE).is_file()


def _public_paths() -> list[str]:
    """Pathspec de lo publicable: todo menos lo que lista .publicignore."""
    lines = (config.PROJECT_DIR / IGNORE_FILE).read_text(encoding="utf-8").splitlines()
    return [".", *(f":(exclude){line.strip()}" for line in lines if line.strip() and not line.startswith("#"))]


def _dirty(*paths: str) -> list[tuple[str, str]]:
    """(estado de git, ruta) de lo que no tiene commit."""
    out = _git("status", "--porcelain", "-z", "--no-renames", "-uall", "--", *paths).stdout
    return [(os.fsdecode(r[:2]), os.fsdecode(r[3:])) for r in out.split(b"\0") if r]


def _changes() -> dict[str, str]:
    """{ruta: tipo} de lo que difiere de GitHub. Antes de la primera subida va todo: no hace falta listarlo."""
    base = _ref(REMOTE_REF)
    if not base:
        return {}
    paths = _public_paths()
    fields = os.fsdecode(_git("diff", "--name-status", "--no-renames", "-z", base, "HEAD", "--", *paths).stdout).split("\0")
    kinds = {"A": "nuevo", "D": "borrado"}
    rows = {path: kinds.get(code, "modificado") for code, path in zip(fields[::2], fields[1::2])}
    for code, path in _dirty(*paths):
        rows.setdefault(path, "nuevo" if code == "??" else "borrado" if "D" in code else "modificado")
    return dict(sorted(rows.items()))


def _component(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else "raíz del proyecto"


def _web_url() -> str | None:
    text = (config.PROJECT_DIR / SCRIPT).read_text(encoding="utf-8")
    match = re.search(r"^URL=git@github\.com:(.+?)\.git$", text, re.MULTILINE)
    return f"https://github.com/{match[1]}" if match else None


def status() -> dict:
    if not is_available():
        return {"available": False}
    changes = _changes()
    published = _ref(PUBLISHED_REF)
    unpublished = int(_text(_git("rev-list", "--count", f"{published}..HEAD"))) if published else None
    commits = []
    for i, line in enumerate(_text(_git("log", "-12", "--format=%h%x00%ct%x00%s")).splitlines()):
        short, when, subject = line.split("\0", 2)
        commits.append({"hash": short, "date": int(when), "subject": subject[:160], "pushed": unpublished is not None and i >= unpublished})
    tracked = [p for p in os.fsdecode(_git("ls-files", "-z", "--", *_public_paths()).stdout).split("\0") if p]
    components = Counter(_component(path) for path in tracked)
    pushed_at = _git("log", "-1", "--format=%ct", REMOTE_REF, check=False)
    return {
        "available": True,
        "repo": str(config.PROJECT_DIR),
        "branch": _text(_git("branch", "--show-current")),
        "web_url": _web_url(),
        "first": _ref(REMOTE_REF) is None,
        "ahead": 0,
        "behind": 0,
        "last_push": int(_text(pushed_at)) if pushed_at.returncode == 0 else None,
        "changes": [{"path": p, "kind": k, "component": _component(p)} for p, k in changes.items()],
        "missing": [],
        "commits": commits,
        "commit_links": False,  # los commits de main no existen en GitHub
        "components": [{"name": name, "files": files} for name, files in sorted(components.items())],
        "total_files": len(tracked),
    }


def file_diff(path: str) -> dict:
    """Solo de lo que está en la lista de cambios: la ruta no se usa para abrir nada."""
    if not is_available():
        raise RepoError(404, "No hay nada que publicar en este equipo")
    kind = _changes().get(path)
    if kind is None:
        raise RepoError(404, "Ese archivo no tiene cambios")
    before = _git("show", f"{REMOTE_REF}:{path}", check=False)
    return diff_payload(path, kind, before.stdout if before.returncode == 0 else None, read_entry(config.PROJECT_DIR / path))


def _commit_pending() -> None:
    pending = _dirty(".")
    if pending:
        _git("add", "-A")
        _git("commit", "-m", f"Cambios desde el panel: {len(pending)} archivo(s)")


def _run_script() -> None:
    try:
        run = subprocess.run(["bash", SCRIPT], cwd=config.PROJECT_DIR, capture_output=True, text=True, timeout=180, env=git_env())
    except subprocess.TimeoutExpired:
        raise RepoError(504, "La publicación tardó demasiado: revisa la conexión y vuelve a intentarlo.")
    if run.returncode:
        detail = " ".join(run.stderr.split()).removeprefix("ERROR: ")
        log.warning("Proyecto: %s", detail)
        raise RepoError(422, detail or "No se ha podido publicar.")


def publish() -> dict:
    """Guarda lo pendiente y publica. Una sola subida a la vez."""
    if not _lock.acquire(blocking=False):
        raise RepoError(409, "Ya hay una subida en marcha")
    try:
        if not is_available():
            raise RepoError(404, "No hay nada que publicar en este equipo")
        branch = _text(_git("branch", "--show-current"))
        if branch != MAIN:
            raise RepoError(409, f"El proyecto está en la rama «{branch or 'sin rama'}»: vuelve a {MAIN} para publicar.")
        first = _ref(REMOTE_REF) is None
        changes = _changes()
        if not first and not changes:
            return {"status": "al-dia", "files": 0, "commit": None, "conflicts": []}
        _commit_pending()
        _run_script()
        commit = _text(_git("rev-parse", "--short", "refs/heads/publico"))
        log.info("Proyecto publicado: %s, %d archivos", commit, len(changes))
        return {"status": "subido", "files": len(changes), "commit": commit, "conflicts": []}
    finally:
        _lock.release()


@router.get("")
def get_proyecto():
    return route_call(status)


@router.get("/diff")
def get_proyecto_diff(path: str = Query(max_length=1024)):
    return route_call(file_diff, path)


@router.post("/push")
def push_proyecto():
    return route_call(publish)
