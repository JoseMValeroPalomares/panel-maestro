"""Escritura atómica de archivos de texto: los .md son la fuente de verdad y un corte a mitad no puede dejarlos a medias."""

import os
import sys
import tempfile
import time


def _umask() -> int:
    """La umask del proceso sin cambiarla (os.umask la cambia y no es seguro entre hilos): main.py la pone a 077."""
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("Umask:"):
                    return int(line.split()[1], 8)
    except (OSError, ValueError):
        pass
    return 0o022


def _chmod(path: str, mode: int) -> None:
    """Permisos del temporal. En NTFS (la partición compartida con Windows, P-12) no hay permisos Unix y en Windows
    os.chmod solo cambia «solo lectura»: si no se puede, se sigue (los permisos los pone el montaje)."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _replace(tmp: str, path: str) -> None:
    """os.replace. En Windows falla con «acceso denegado» si el antivirus o el indexador tienen abierto el destino un
    instante (docs/windows.md §2.6): se reintenta durante ~1 s antes de rendirse."""
    if sys.platform != "win32":
        os.replace(tmp, path)
        return
    for intento in range(10):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if intento == 9:
                raise
            time.sleep(0.1)


def _atomic(path: str | os.PathLike, write, mode: str, **open_kw) -> None:
    path = os.fspath(path)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, mode, **open_kw) as f:
            write(f)
            f.flush()
            os.fsync(f.fileno())
        _chmod(tmp, os.stat(path).st_mode & 0o777 if os.path.exists(path) else 0o666 & ~_umask())
        _replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def atomic_write(path: str | os.PathLike, text: str, newline: str | None = "\n") -> None:
    """Escribe en un temporal de la misma carpeta y lo cambia por `path` de golpe. El temporal empieza por «.» y no
    acaba en .md: ni el indexador ni las copias lo recogen. Conserva los permisos del archivo que sustituye;
    uno nuevo nace con los de la umask (600 en el panel, S-6). Saltos de línea: «\n» también en Windows (P-12: el
    mismo .md, y la misma huella de D-4, en los dos sistemas); newline="" escribe el texto tal cual."""
    _atomic(path, lambda f: f.write(text), "w", encoding="utf-8", newline=newline)


def atomic_write_bytes(path: str | os.PathLike, data_or_stream) -> None:
    """Igual que atomic_write, byte a byte (lo que sale de un zip queda idéntico). Acepta bytes o un archivo abierto."""
    if isinstance(data_or_stream, (bytes, bytearray)):
        _atomic(path, lambda f: f.write(data_or_stream), "wb")
    else:
        import shutil

        _atomic(path, lambda f: shutil.copyfileobj(data_or_stream, f), "wb")
