"""Copia y vuelta atrás de los datos que puede cambiar un arranque (C-4), para scripts/desplegar.sh.

    python3 -I scripts/despliegue_bd.py copiar DESTINO RUTA...     # BDs con la API de backup + integrity_check; el resto, tal cual
    python3 -I scripts/despliegue_bd.py restaurar DESTINO           # deja cada RUTA como estaba al copiar (y lo comprueba)
    python3 -I scripts/despliegue_bd.py huella RUTA...              # sha256 del contenido lógico de cada BD

Solo biblioteca estándar y sin importar nada del panel: se usa justo cuando la versión nueva puede estar rota.
La huella es la del volcado SQL (iterdump), no la del archivo: el mismo contenido da la misma huella aunque SQLite
coloque las páginas o el WAL de otra forma. Solo se llama con el servicio parado.
"""

import hashlib
import json
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

MANIFEST = "manifest.json"


def es_bd(path: Path) -> bool:
    return path.suffix == ".db"


def huella(path: Path) -> str:
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        h = hashlib.sha256()
        for linea in conn.iterdump():
            h.update(linea.encode())
            h.update(b"\n")
        return h.hexdigest()


def _sha_archivo(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _backup(origen: Path, destino: Path) -> None:
    with closing(sqlite3.connect(origen)) as src, closing(sqlite3.connect(destino)) as dst:
        src.backup(dst)
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
    if ok != "ok":
        raise SystemExit(f"integrity_check de {destino} da «{ok}»")


def copiar(destino: Path, rutas: list[Path]) -> None:
    destino.mkdir(parents=True, exist_ok=False)
    entradas = []
    for i, ruta in enumerate(rutas):
        copia = destino / f"{i}-{ruta.name}"
        entrada = {"ruta": str(ruta), "copia": copia.name, "existia": ruta.exists()}
        if ruta.exists():
            if es_bd(ruta):
                _backup(ruta, copia)
                entrada["huella"] = huella(copia)
            else:
                shutil.copy2(ruta, copia)
                entrada["sha256"] = _sha_archivo(copia)
        entradas.append(entrada)
        print(f"  copia de {ruta.name}: {'hecha' if entrada['existia'] else 'no existía'}")
    (destino / MANIFEST).write_text(json.dumps(entradas, indent=2, ensure_ascii=False))


def restaurar(destino: Path) -> None:
    entradas = json.loads((destino / MANIFEST).read_text())
    for e in entradas:
        ruta, copia = Path(e["ruta"]), destino / e["copia"]
        if not e["existia"]:
            if ruta.exists():
                ruta.unlink()  # la versión nueva lo creó: fuera, como estaba
            print(f"  {ruta.name}: no existía, sigue sin existir")
            continue
        if es_bd(ruta):
            _backup(copia, ruta)  # a través de SQLite: respeta y limpia el WAL que dejó la versión nueva
            if huella(ruta) != e["huella"]:
                raise SystemExit(f"{ruta} no ha quedado igual que la copia")
            print(f"  {ruta.name}: restaurada (huella {e['huella'][:12]})")
        else:
            shutil.copy2(copia, ruta)
            if _sha_archivo(ruta) != e["sha256"]:
                raise SystemExit(f"{ruta} no ha quedado igual que la copia")
            print(f"  {ruta.name}: restaurado")


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in ("copiar", "restaurar", "huella"):
        print(__doc__, file=sys.stderr)
        return 2
    orden, resto = argv[0], [Path(a) for a in argv[1:]]
    if orden == "copiar":
        copiar(resto[0], resto[1:])
    elif orden == "restaurar":
        restaurar(resto[0])
    else:
        for ruta in resto:
            print(f"{huella(ruta)}  {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
