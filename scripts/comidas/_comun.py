"""Lo común a los scripts de Comidas: la BD de verdad (core.config, que respeta PANEL_COMIDAS_DB) y la copia previa
automática que antes había que hacer a mano con `cp … comidas.db.bak`."""

import sqlite3
import time

from core import config

DB_PATH = str(config.COMIDAS_DB)
EXPORT_DIR = str(config.COMIDAS_DB.parent / "export")
_copiada = None


def copia_previa(script: str) -> str:
    """Copia la BD de Comidas a backups/scripts-comidas/ con la API de backup de SQLite y la comprueba
    (integrity_check) antes de que el script escriba. Una sola vez por ejecución; si falla, el script no sigue."""
    global _copiada
    if _copiada:
        return _copiada
    destino = config.BACKUPS_DIR / "scripts-comidas" / f"comidas-{script}-{time.strftime('%Y%m%d-%H%M%S')}.db"
    destino.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    dst = sqlite3.connect(destino)
    try:
        src.backup(dst)
        estado = dst.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        dst.close()
        src.close()
    if estado != "ok":
        raise SystemExit(f"La copia previa de la BD de Comidas no es válida ({estado}): no se toca nada")
    print(f"Copia previa: {destino}")
    _copiada = str(destino)
    return _copiada
