"""Escritura atómica de archivos de texto: los .md son la fuente de verdad y un corte a mitad no puede dejarlos a medias."""
import os
import tempfile


def atomic_write(path: str | os.PathLike, text: str, newline: str | None = None) -> None:
    """Escribe en un temporal de la misma carpeta y lo cambia por `path` de golpe. El temporal empieza por «.» y no
    acaba en .md: ni el indexador ni las copias lo recogen. Conserva los permisos del archivo que sustituye."""
    path = os.fspath(path)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, os.stat(path).st_mode & 0o777 if os.path.exists(path) else 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
