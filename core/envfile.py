"""Escritura de claves en el .env del panel (config.ENV_FILE): atómica y con permisos 600."""

from pathlib import Path

from core import config
from core.files import atomic_write


def update_env(values: dict[str, str], path: Path | None = None) -> None:
    """Sustituye o añade KEY=valor conservando el resto de líneas (comentarios incluidos)."""
    path = Path(path or config.ENV_FILE)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = dict(values)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in pending:
            out.append(f"{key}={pending.pop(key)}")
        else:
            out.append(line)
    out.extend(f"{k}={v}" for k, v in pending.items())
    atomic_write(path, "\n".join(out) + "\n")
    path.chmod(0o600)
