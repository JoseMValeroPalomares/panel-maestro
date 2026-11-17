"""Datos compartidos con Windows (P-12, docs/windows.md §6 y §8).

    python -m scripts.datos_compartidos estado                       # cerrojo, WAL, integrity_check y recuentos
    python -m scripts.datos_compartidos seguir                       # tras un cierre sucio del otro sistema
    python -m scripts.datos_compartidos mover --destino DIR [--hacer]  # mueve los datos a la partición (con el panel parado)
    python -m scripts.datos_compartidos volver [--hacer] [--sin-copiar]  # deshace `mover`

Sin --hacer, `mover` y `volver` solo dicen qué harían. Opción común: --entorno ARCHIVO (por defecto el panel.env del
despliegue, ~/.local/share/panel-maestro/panel.env, si existe; «ninguno» para no leer ninguno). Sus rutas mandan
sobre las del .env, como en el servicio.

`mover` no borra nada: los datos viejos se quedan donde estaban (con una marca que impide arrancar el panel sobre
ellos) y son la vuelta atrás. Antes de copiar hace una copia completa verificada en <copias>/pre-12-<fecha>/.
"""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

CLAVES_RUTAS = (
    "PANEL_DATA_DIR",
    "PANEL_NOTES_DIR",
    "PANEL_BRAIN_DB",
    "PANEL_TRASH_DIR",
    "PANEL_COMIDAS_DB",
    "PANEL_UPLOADS_DIR",
    "PANEL_CALENDAR_STATE",
)
SUFIJO_ANTES = ".antes-12"
# Lo que no se copia de la carpeta de datos: las BDs van con la API de backup; el cerrojo y el estado de Windows son de
# cada carpeta; los temporales de atomic_write y las copias a medias no son datos
NO_SE_COPIA = {"brain.db", "brain.db-wal", "brain.db-shm", "panel-cerrojo.json", "windows-estado.json"}
TABLAS_HUELLA = ("notes", "inbox", "events", "boards", "resources", "routine_checks", "item_log", "sesiones")


class Error(RuntimeError):
    pass


def _entorno_por_defecto() -> Path | None:
    raiz = os.environ.get("PANEL_DEPLOY_ROOT") or Path(
        os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share", "panel-maestro"
    )
    p = Path(raiz) / "panel.env"
    return p if p.is_file() and sys.platform != "win32" else None


def leer_entorno(path: Path) -> dict[str, str]:
    out = {}
    for linea in path.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            k, v = linea.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def escribir_entorno(path: Path, cambios: dict[str, str]) -> None:
    """Cambia (o añade al final) las claves de `cambios` conservando el resto del archivo, comentarios incluidos."""
    from core.files import atomic_write

    lineas, vistas = [], set()
    for linea in path.read_text(encoding="utf-8").splitlines():
        k = linea.split("=", 1)[0].strip() if "=" in linea and not linea.lstrip().startswith("#") else None
        if k in cambios:
            lineas.append(f"{k}={cambios[k]}")
            vistas.add(k)
        else:
            lineas.append(linea)
    lineas += [f"{k}={v}" for k, v in cambios.items() if k not in vistas]
    atomic_write(path, "\n".join(lineas) + "\n")


# ─────────────────────────────────────────────
# Dónde están los datos
# ─────────────────────────────────────────────


@dataclass(frozen=True)
class Datos:
    data: Path
    comidas_db: Path
    uploads: Path
    calendario: Path

    @property
    def brain_db(self) -> Path:
        return self.data / "brain.db"

    @property
    def notas(self) -> Path:
        return self.data / "notes"

    def rutas(self) -> dict[str, str]:
        return {
            "PANEL_DATA_DIR": str(self.data),
            "PANEL_NOTES_DIR": str(self.notas),
            "PANEL_BRAIN_DB": str(self.brain_db),
            "PANEL_TRASH_DIR": str(self.data / "trash"),
            "PANEL_COMIDAS_DB": str(self.comidas_db),
            "PANEL_UPLOADS_DIR": str(self.uploads),
            "PANEL_CALENDAR_STATE": str(self.calendario),
        }


def en_carpeta(raiz: Path) -> Datos:
    """La disposición de la carpeta compartida (docs/windows.md §1); la misma para las copias previas."""
    return Datos(
        raiz / "data", raiz / "comidas" / "comidas.db", raiz / "uploads", raiz / "estudio" / "calendar_sync_v2.json"
    )


def desde_config() -> Datos:
    from core import config

    datos = Datos(Path(config.DATA_DIR), Path(config.COMIDAS_DB), Path(config.UPLOADS_DIR), Path(config.CALENDAR_STATE))
    raros = [
        n
        for n, real, esperado in (
            ("PANEL_NOTES_DIR", config.NOTES_DIR, datos.notas),
            ("PANEL_BRAIN_DB", config.BRAIN_DB, datos.brain_db),
            ("PANEL_TRASH_DIR", config.TRASH_DIR, datos.data / "trash"),
        )
        if Path(real) != esperado
    ]
    if raros:
        raise Error(f"{', '.join(raros)} no están dentro de PANEL_DATA_DIR como siempre: muévelo a mano")
    return datos


def desde_entorno(valores: dict[str, str]) -> Datos:
    try:
        return Datos(
            Path(valores["PANEL_DATA_DIR"]),
            Path(valores["PANEL_COMIDAS_DB"]),
            Path(valores["PANEL_UPLOADS_DIR"]),
            Path(valores["PANEL_CALENDAR_STATE"]),
        )
    except KeyError as e:
        raise Error(f"Falta {e} en el entorno guardado") from e


# ─────────────────────────────────────────────
# Copia verificada
# ─────────────────────────────────────────────

INVALIDOS_WINDOWS = set('<>:"\\|?*')


def nombre_valido_en_windows(rel: Path) -> bool:
    from app.notes_core import windows_reserved

    return all(
        not (set(p) & INVALIDOS_WINDOWS)
        and not any(ord(c) < 32 for c in p)
        and not p.endswith((" ", "."))
        and not windows_reserved(p)
        for p in rel.parts
    )


def _es_temporal(p: Path) -> bool:
    return (p.name.startswith(".") and p.name.endswith(".tmp")) or p.name.endswith(".part")


def archivos(origen: Datos) -> list[tuple[Path, Path]]:
    """(archivo, ruta relativa dentro de la disposición compartida) de todo lo que no es una BD."""
    out = []
    raiz_data = Path("data")
    if origen.data.is_dir():
        for p in sorted(origen.data.rglob("*")):
            rel = p.relative_to(origen.data)
            if p.is_symlink() or not p.is_file() or _es_temporal(p):
                continue
            if rel.parent == Path(".") and (p.name in NO_SE_COPIA or p.name.startswith("MOVIDO-")):
                continue
            out.append((p, raiz_data / rel))
    if origen.uploads.is_dir():
        out += [
            (p, Path("uploads") / p.relative_to(origen.uploads))
            for p in sorted(origen.uploads.rglob("*"))
            if p.is_file() and not p.is_symlink() and not _es_temporal(p)
        ]
    for estado in (origen.calendario, origen.calendario.with_name("calendar_sync_state.json")):
        if estado.is_file():
            out.append((estado, Path("estudio") / estado.name))
    return out


def _destino(destino: Datos, rel: Path) -> Path:
    top, resto = rel.parts[0], Path(*rel.parts[1:])
    return {
        "data": destino.data,
        "uploads": destino.uploads,
        "estudio": destino.calendario.parent,
    }[top] / resto


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def recuentos(db: Path) -> dict[str, int]:
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)) as conn:
        tablas = [
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        ]
        return {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in sorted(tablas)}


def _copiar_bd(origen: Path, destino: Path) -> dict:
    from scripts.despliegue_bd import huella

    destino.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(f"file:{origen}?mode=ro", uri=True, timeout=30)) as src:
        with closing(sqlite3.connect(destino)) as dst:
            src.backup(dst)
            ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
    if ok != "ok":
        raise Error(f"{destino} no supera integrity_check: {ok}")
    a, b = recuentos(origen), recuentos(destino)
    if a != b:
        distintas = {t: (a.get(t), b.get(t)) for t in set(a) | set(b) if a.get(t) != b.get(t)}
        raise Error(f"Recuentos distintos en {destino.name}: {distintas}")
    if huella(origen) != huella(destino):
        raise Error(f"El contenido de {destino.name} no es idéntico al original (huella del volcado SQL)")
    return {"filas": sum(b.values()), "tablas": len(b)}


def copiar_datos(origen: Datos, destino: Datos, avisar=print) -> dict:
    """Copia todo de `origen` a `destino` y lo comprueba: sha256 de cada archivo, integrity_check, recuentos de todas
    las tablas y huella del volcado SQL de las dos BDs. Conserva las fechas de modificación (el indexador no ve
    cambiadas las notas). Lanza Error a la primera diferencia."""
    lista = archivos(origen)
    malos = [str(rel) for _p, rel in lista if not nombre_valido_en_windows(rel)]
    if malos:
        raise Error(f"Nombres que Windows no admite (renómbralos antes): {malos[:20]}")
    total = 0
    for p, rel in lista:
        dst = _destino(destino, rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dst)
        st = p.stat()
        try:
            os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns))
        except OSError:
            pass
        if _sha(p) != _sha(dst):
            raise Error(f"La copia de {rel} no es idéntica")
        total += st.st_size
    informe = {
        "archivos": len(lista),
        "bytes": total,
        "notas": sum(1 for _p, r in lista if r.parent == Path("data/notes")),
    }
    for nombre, src, dst in (
        ("brain.db", origen.brain_db, destino.brain_db),
        ("comidas.db", origen.comidas_db, destino.comidas_db),
    ):
        if src.is_file():
            informe[nombre] = _copiar_bd(src, dst)
    destino.notas.mkdir(parents=True, exist_ok=True)
    avisar(
        f"   {informe['archivos']} archivos ({informe['bytes'] / 1e6:.1f} MB, {informe['notas']} notas) y "
        + ", ".join(f"{k}: {v['filas']} filas en {v['tablas']} tablas" for k, v in informe.items() if k.endswith(".db"))
        + " — todo comprobado"
    )
    return informe


def tamano(origen: Datos) -> int:
    t = sum(p.stat().st_size for p, _rel in archivos(origen))
    return t + sum(db.stat().st_size for db in (origen.brain_db, origen.comidas_db) if db.is_file())


# ─────────────────────────────────────────────
# Comprobaciones previas
# ─────────────────────────────────────────────


def servicio_activo(datos: Datos) -> bool:
    """¿Está en marcha el servicio de usuario Y usa estos datos? (Una copia de prueba no depende del servicio real.)"""
    if sys.platform == "win32" or not shutil.which("systemctl"):
        return False
    from core import config

    desplegado = _entorno_por_defecto()
    del_servicio = (
        Path(leer_entorno(desplegado).get("PANEL_DATA_DIR", "")) if desplegado else config.PROJECT_ROOT / "data"
    )
    if os.path.realpath(del_servicio) != os.path.realpath(datos.data):
        return False
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", "--quiet", "panel-maestro"], timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def comprobar_parado(datos: Datos) -> None:
    from app import datos_compartidos as dc

    if servicio_activo(datos):
        raise Error("El servicio panel-maestro está en marcha: systemctl --user stop panel-maestro")
    c = dc.leer_cerrojo()
    yo = dc.identidad()
    if (
        c
        and not c.get("cerrado")
        and (c.get("sistema"), c.get("equipo")) == (yo["sistema"], yo["equipo"])
        and dc._mismo_arranque(c.get("arranque"), yo["arranque"])
        and dc._proceso_vivo(c.get("pid") or 0)
    ):
        raise Error(f"Hay un panel en marcha con estos datos (proceso {c['pid']}): páralo antes")


def _sistema_de_archivos(p: Path) -> str:
    from app.datos_compartidos import sistema_de_archivos

    q = next((x for x in (p, *p.parents) if x.exists()), p)
    return sistema_de_archivos(q) or "?"


# ─────────────────────────────────────────────
# Órdenes
# ─────────────────────────────────────────────


def mover(destino_raiz: Path, hacer: bool, entorno: Path | None, avisar=print) -> int:
    from app import datos_compartidos as dc
    from core import config

    origen = desde_config()
    destino_raiz = Path(os.path.abspath(destino_raiz))
    destino = en_carpeta(destino_raiz)
    avisar(f"Origen:  {origen.data}  ·  {origen.comidas_db}  ·  {origen.uploads}  ·  {origen.calendario}")
    avisar(f"Destino: {destino_raiz}  (sistema de archivos: {_sistema_de_archivos(destino_raiz)})")
    if (origen.data / dc.MARCA_MOVIDO).exists():
        raise Error(f"Estos datos ya se movieron ({origen.data / dc.MARCA_MOVIDO}); para deshacerlo: volver")
    if not origen.brain_db.is_file():
        raise Error(f"No hay {origen.brain_db}: ¿son estas las rutas del panel? (--entorno)")
    if destino_raiz.exists() and (not destino_raiz.is_dir() or any(destino_raiz.iterdir())):
        raise Error(f"{destino_raiz} ya existe y no está vacía: elige otra carpeta o vacíala tú")
    padre = destino_raiz.parent
    if not padre.is_dir():
        raise Error(f"No existe {padre} (¿partición sin montar?)")
    if not os.access(padre, os.W_OK):
        raise Error(f"No se puede escribir en {padre}")
    if entorno and Path(f"{entorno}{SUFIJO_ANTES}").exists():
        raise Error(f"Ya existe {entorno}{SUFIJO_ANTES}: los datos ya se movieron una vez (usa volver antes)")
    hace_falta = tamano(origen)
    libre = shutil.disk_usage(padre).free
    if libre < hace_falta * 1.2:
        raise Error(f"Sin espacio en {padre}: hacen falta {hace_falta / 1e6:.0f} MB y quedan {libre / 1e6:.0f} MB")
    copias = Path(config.BACKUPS_DIR)
    if _misma(copias, destino_raiz):
        raise Error(f"Las copias ({copias}) quedarían en la misma unidad que los datos: cambia PANEL_BACKUPS_DIR")
    comprobar_parado(origen)
    previa = copias / f"pre-12-{datetime.now():%Y%m%d-%H%M%S}"
    pasos = [
        f"1. Copia completa verificada en {previa}",
        f"2. Copia verificada a {destino_raiz} (sha256, integrity_check, recuentos, huella)",
        f"3. {entorno} con las rutas nuevas (antes: {entorno}{SUFIJO_ANTES})"
        if entorno
        else "3. Sin panel.env: te diré qué rutas poner en el .env",
        f"4. Marca {origen.data / dc.MARCA_MOVIDO}: el panel ya no arranca con los datos viejos (no se borran)",
    ]
    avisar(f"Tamaño: {hace_falta / 1e6:.1f} MB; libres: {libre / 1e6:.0f} MB.")
    avisar("\n".join(pasos))
    if not hacer:
        avisar("\nSimulacro: no se ha cambiado nada. Para hacerlo, con el panel parado: añade --hacer")
        return 0
    avisar(f"\n==> {pasos[0]}")
    copiar_datos(origen, en_carpeta(previa), avisar)
    avisar(f"==> {pasos[1]}")
    try:
        copiar_datos(origen, destino, avisar)
    except BaseException:
        avisar(f"La copia al destino falló: no se ha cambiado nada más. Lo copiado a medias está en {destino_raiz}.")
        raise
    nuevas = destino.rutas()
    avisar(f"==> {pasos[2]}")
    if entorno:
        shutil.copyfile(entorno, f"{entorno}{SUFIJO_ANTES}")
        escribir_entorno(entorno, nuevas)
    else:
        avisar(
            "   Pon esto en tu .env (o en el entorno del panel):\n"
            + "\n".join(f"   {k}={v}" for k, v in nuevas.items())
        )
    avisar(f"==> {pasos[3]}")
    (origen.data / dc.MARCA_MOVIDO).write_text(
        f"Desde el {datetime.now():%d/%m/%Y %H:%M} los datos están en {destino_raiz}. "
        f"Copia previa en {previa}. Vuelta atrás: python -m scripts.datos_compartidos volver\n",
        encoding="utf-8",
    )
    avisar(
        "\nHecho. Arranca el panel (systemctl --user start panel-maestro) y comprueba: python -m scripts.datos_compartidos estado"
    )
    return 0


def _misma(a: Path, b: Path) -> bool:
    try:
        a = next(x for x in (a, *a.parents) if x.exists())
        b = next(x for x in (b, *b.parents) if x.exists())
        return os.stat(a).st_dev == os.stat(b).st_dev
    except (OSError, StopIteration):
        return False


def volver(hacer: bool, sin_copiar: bool, entorno: Path | None, avisar=print) -> int:
    from app import datos_compartidos as dc
    from core import config

    if not entorno:
        raise Error("volver necesita el panel.env del despliegue (--entorno)")
    antes = Path(f"{entorno}{SUFIJO_ANTES}")
    if not antes.is_file():
        raise Error(f"No hay {antes}: los datos no se movieron con este script")
    viejos = desde_entorno(leer_entorno(antes))
    actuales = desde_config()
    previa = Path(config.BACKUPS_DIR) / f"pre-volver-{datetime.now():%Y%m%d-%H%M%S}"
    avisar(
        f"Ahora:  {actuales.data} (y compañía)\nVuelven a: {viejos.data}  ·  {viejos.comidas_db}  ·  {viejos.uploads}"
    )
    if sin_copiar:
        pasos = [f"1. {entorno} como estaba ({antes})", f"2. Quitar {viejos.data / dc.MARCA_MOVIDO}"]
        avisar(
            "\n".join(pasos)
            + "\n(Vuelves a los datos del momento de mover: lo escrito después se queda en la partición.)"
        )
    else:
        pasos = [
            f"1. Lo que hay en las carpetas de siempre, a {previa} (se aparta, no se borra)",
            f"2. Copia verificada de {actuales.data} (y compañía) a las carpetas de siempre",
            f"3. {entorno} como estaba ({antes})",
        ]
        avisar("\n".join(pasos))
    comprobar_parado(actuales)
    if not hacer:
        avisar("\nSimulacro: no se ha cambiado nada. Para hacerlo, con el panel parado: añade --hacer")
        return 0
    if not sin_copiar:
        avisar(f"==> {pasos[0]}")
        apartar(viejos, en_carpeta(previa))
        avisar(f"==> {pasos[1]}")
        copiar_datos(actuales, viejos, avisar)
    else:
        (viejos.data / dc.MARCA_MOVIDO).unlink(missing_ok=True)
    os.replace(antes, entorno)
    avisar(f"\nHecho: {entorno} vuelve a las rutas de siempre. Arranca el panel: systemctl --user start panel-maestro")
    return 0


def apartar(datos: Datos, aparte: Datos) -> None:
    """Mueve (renombra) los datos a otra carpeta; si no se puede (otra unidad), los copia comprobados y luego los quita."""
    pares = [
        (datos.data, aparte.data),
        (datos.comidas_db, aparte.comidas_db),
        (datos.uploads, aparte.uploads),
        (datos.calendario, aparte.calendario),
        (
            datos.calendario.with_name("calendar_sync_state.json"),
            aparte.calendario.with_name("calendar_sync_state.json"),
        ),
    ]
    for extra in ("-wal", "-shm"):
        pares.append((Path(f"{datos.comidas_db}{extra}"), Path(f"{aparte.comidas_db}{extra}")))
    for src, dst in pares:
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(src, dst)
        except OSError:
            if src.is_dir():
                shutil.copytree(src, dst)
                shutil.rmtree(src)
            else:
                shutil.copy2(src, dst)
                src.unlink()


def estado(avisar=print) -> int:
    from app import datos_compartidos as dc
    from core import config

    datos = desde_config()
    avisar(f"Sistema: {config.PLATFORM}  ·  datos en {datos.data} ({_sistema_de_archivos(datos.data)})")
    avisar(f"Copias: {config.BACKUPS_DIR}  ·  compartida con Windows: {'sí' if dc.compartida() else 'no'}")
    c = dc.leer_cerrojo()
    if c:
        cuando = lambda t: datetime.fromtimestamp(t).strftime("%d/%m/%Y %H:%M") if t else "—"  # noqa: E731
        avisar(
            f"Cerrojo: {dc.quien(c)}, abierto {cuando(c.get('abierto'))}, "
            + (f"cerrado {cuando(c.get('cerrado'))}" if c.get("cerrado") else "SIN CERRAR")
            + (" (confirmado con seguir)" if c.get("aceptado") else "")
        )
    else:
        avisar("Cerrojo: ninguno (nunca se ha abierto con P-12)")
    pendiente = dc.wal_pendiente()
    avisar(f"WAL pendiente: {', '.join(pendiente) if pendiente else 'nada (datos en reposo)'}")
    if (datos.data / dc.MARCA_MOVIDO).exists():
        avisar(f"MARCA: {(datos.data / dc.MARCA_MOVIDO).read_text(encoding='utf-8').strip()}")
    try:
        w = json.loads((datos.data / dc.ESTADO_WINDOWS).read_text(encoding="utf-8"))
        avisar(
            f"Windows ({w.get('comprobado', '?')}): inicio rápido {'ACTIVO' if w.get('inicio_rapido') else 'no'}, "
            f"hibernación {'ACTIVA' if w.get('hibernacion') else 'no'}"
        )
    except (OSError, ValueError):
        pass
    notas = len(list(datos.notas.glob("*.md"))) if datos.notas.is_dir() else 0
    huella = [f"notas .md={notas}"]
    bien = True
    for db in (datos.brain_db, datos.comidas_db):
        if not db.is_file():
            avisar(f"{db.name}: no existe")
            continue
        try:
            with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)) as conn:
                ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
            n = recuentos(db)
        except sqlite3.Error as e:
            ok, n = f"no se puede abrir en solo lectura ({e})", {}
        bien = bien and ok == "ok"
        avisar(f"{db.name}: integrity_check {ok}")
        huella += [f"{t}={n[t]}" for t in TABLAS_HUELLA if t in n]
    avisar("Recuentos (compáralos entre Linux y Windows): " + "  ".join(huella))
    return 0 if bien else 1


def cargar_entorno(arg: str | None) -> Path | None:
    """Antes de importar core.config: las rutas del panel.env mandan sobre las del .env (como en el servicio); lo que ya
    venga en el entorno del proceso, sobre las dos."""
    if arg == "ninguno":
        return None
    path = Path(arg).expanduser() if arg else _entorno_por_defecto()
    if path is None:
        return None
    if not path.is_file():
        raise Error(f"No existe {path}")
    for k, v in leer_entorno(path).items():
        os.environ.setdefault(k, v)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scripts.datos_compartidos", description=__doc__.split("\n\n")[0])
    ap.add_argument("--entorno", help="panel.env con las rutas (por defecto el del despliegue; «ninguno»)")
    sub = ap.add_subparsers(dest="orden", required=True)
    sub.add_parser("estado", help="cerrojo, WAL, integrity_check y recuentos")
    sub.add_parser("seguir", help="confirmar tras un cierre sucio del otro sistema")
    m = sub.add_parser("mover", help="mover los datos a la partición compartida")
    m.add_argument("--destino", required=True, type=Path)
    m.add_argument("--hacer", action="store_true")
    v = sub.add_parser("volver", help="deshacer «mover»")
    v.add_argument("--hacer", action="store_true")
    v.add_argument("--sin-copiar", action="store_true", help="solo panel.env y la marca (vuelves a los datos viejos)")
    args = ap.parse_args(argv)
    try:
        entorno = cargar_entorno(args.entorno)
        os.environ.setdefault("PANEL_DISABLE_BRIDGES", "1")
        os.environ.setdefault("PANEL_DISABLE_SCHEDULER", "1")
        if entorno:
            print(f"(rutas de {entorno})")
        if args.orden == "estado":
            return estado()
        if args.orden == "seguir":
            from app import datos_compartidos as dc

            r = dc.seguir()
            print(r["mensaje"])
            return 0 if r["ok"] else 1
        if args.orden == "mover":
            return mover(args.destino, args.hacer, entorno)
        return volver(args.hacer, args.sin_copiar, entorno)
    except Error as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except sqlite3.Error as e:
        print(f"ERROR de SQLite: {e}. Si el panel no se cerró bien, arráncalo y páralo una vez.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
