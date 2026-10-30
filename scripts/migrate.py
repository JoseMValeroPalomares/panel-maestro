"""
Migraciones versionadas de las BDs del panel.

    python -m scripts.migrate status            # qué hay aplicado
    python -m scripts.migrate up                # aplicar las pendientes (también se hace al arrancar)
    python -m scripts.migrate down 0 [--db cerebro|comidas]   # revertir hasta la versión indicada

Haz una copia antes de revertir (/backups o `cp data/brain.db{,.bak}`).
"""
import argparse
import sqlite3

from core import config
from core.migrations import apply_pending, revert, status


def registry():
    from app.migrations import MIGRATIONS as CEREBRO
    from comidas.migrations import MIGRATIONS as COMIDAS
    return {"cerebro": (config.BRAIN_DB, CEREBRO), "comidas": (config.COMIDAS_DB, COMIDAS)}


def open_db(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, timeout=10)  # transacciones explícitas
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["status", "up", "down"])
    ap.add_argument("target", nargs="?", type=int, default=0)
    ap.add_argument("--db", choices=["cerebro", "comidas", "todas"], default="todas")
    args = ap.parse_args()
    for name, (path, migs) in registry().items():
        if args.db not in (name, "todas"):
            continue
        conn = open_db(path)
        try:
            if args.action == "up":
                print(name, "aplicadas:", apply_pending(conn, migs) or "ninguna")
            elif args.action == "down":
                print(name, "revertidas:", revert(conn, migs, args.target) or "ninguna")
            for v, n, ok in status(conn, migs):
                print(f"  {name} {v:>3} {'✓' if ok else '·'} {n}")
        finally:
            conn.close()


if __name__ == "__main__":
    main()
