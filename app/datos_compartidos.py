"""
Guardas de la carpeta de datos (P-12): la misma carpeta la abren el panel de Linux y el de Windows (arranque dual,
partición NTFS compartida). Diseño y motivos: docs/windows.md §2–§3.

Corren al principio del arranque, ANTES de abrir ninguna BD (`al_arrancar`, desde main.py). Si algo no cuadra, lanzan
`ArranqueDenegado`: el panel no arranca (uvicorn sale con 3), el motivo queda en logs/arranque-denegado.json (lo enseña
start.ps1 en Windows) y no se escribe nada en la carpeta de datos.

- Marca de datos movidos (MOVIDO-A-LA-PARTICION.txt): estos datos son los viejos → se niega.
- Estado de Windows (data/windows-estado.json, lo escribe start.ps1): inicio rápido o hibernación activos → se niega.
- Carpetas escribibles: no montadas en solo lectura y con un archivo de prueba que se escribe y se borra.
- Cerrojo (data/panel-cerrojo.json) con sistema, equipo, proceso y encendido: detecta otro panel con los mismos datos y
  el cierre sucio de este sistema o del otro (tabla en docs/windows.md §3.3).

Al cerrar (`al_cerrar`): checkpoint TRUNCATE de las dos BDs y cerrojo «cerrado». En Windows, además, al recibir el fin
de sesión (ventana oculta: Windows mata sin avisar a un proceso sin ventana). Cada 2 min, `checkpoint_en_reposo`
vacía el WAL si tiene algo: así un apagado brusco casi siempre deja los datos en reposo.
"""

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from core import config
from core.files import atomic_write
from core.logging_config import get_logger

log = get_logger("datos")

CERROJO = "panel-cerrojo.json"
ESTADO_WINDOWS = "windows-estado.json"
MARCA_MOVIDO = "MOVIDO-A-LA-PARTICION.txt"
DENEGADO = "arranque-denegado.json"
NTFS = {"ntfs", "ntfs3", "fuseblk"}

_estado: dict = {}  # lo que vio el último arranque (para /api/status)
_cierre = threading.Lock()
_abiertos = 0  # lifespans activos en este proceso (los tests anidan varios): el cerrojo se cierra con el último


class ArranqueDenegado(RuntimeError):
    def __init__(self, motivo: str, mensaje: str, accion: str | None = None):
        super().__init__(mensaje)
        self.motivo, self.mensaje, self.accion = motivo, mensaje, accion

    def __str__(self) -> str:
        return self.mensaje + (f"\n→ {self.accion}" if self.accion else "")


# ─────────────────────────────────────────────
# Rutas e identidad
# ─────────────────────────────────────────────


def cerrojo_path() -> Path:
    return Path(config.DATA_DIR) / CERROJO


def denegado_path() -> Path:
    return Path(config.LOGS_DIR) / DENEGADO


def bases() -> list[Path]:
    return [Path(config.BRAIN_DB), Path(config.COMIDAS_DB)]


def carpetas() -> list[Path]:
    """Las carpetas en las que el panel escribe datos, sin repetir."""
    vistas, out = set(), []
    for d in (
        config.DATA_DIR,
        config.NOTES_DIR,
        Path(config.BRAIN_DB).parent,
        Path(config.COMIDAS_DB).parent,
        config.UPLOADS_DIR,
        config.TRASH_DIR,
        Path(config.CALENDAR_STATE).parent,
    ):
        d = Path(d)
        if d not in vistas:
            vistas.add(d)
            out.append(d)
    return out


def arranque() -> str:
    """Identifica este encendido del equipo: el boot_id en Linux; en Windows, la hora de inicio (al minuto)."""
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError:
        pass
    if sys.platform == "win32":
        import ctypes

        ms = ctypes.windll.kernel32.GetTickCount64
        ms.restype = ctypes.c_ulonglong
        return f"inicio-{int(time.time() - ms() / 1000) // 60}"
    return "?"


def _mismo_arranque(a: str | None, b: str | None) -> bool:
    if not a or not b or "?" in (a, b):
        return False
    if a.startswith("inicio-") and b.startswith("inicio-"):  # Windows: al minuto, con un minuto de margen
        try:
            return abs(int(a[7:]) - int(b[7:])) <= 1
        except ValueError:
            return False
    return a == b


def identidad() -> dict:
    return {"sistema": config.PLATFORM, "equipo": socket.gethostname(), "pid": os.getpid(), "arranque": arranque()}


def _proceso_vivo(pid: int) -> bool:
    """¿Sigue en marcha un panel con ese pid? (En Windows os.kill MATA el proceso: no se usa.)"""
    if not pid or int(pid) <= 0:  # os.kill(0, …) iría al grupo de procesos entero
        return False
    if sys.platform == "win32":
        import ctypes

        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    try:  # el pid pudo reutilizarse tras una caída: solo cuenta si es un Python
        return b"python" in Path(f"/proc/{int(pid)}/cmdline").read_bytes()
    except OSError:
        return True


def sistema_de_archivos(path: Path) -> str | None:
    """Tipo del sistema de archivos que contiene `path` (Linux, /proc/self/mounts); None si no se sabe."""
    try:
        real = os.path.realpath(path)
        mejor, tipo = "", None
        with open("/proc/self/mounts", encoding="utf-8") as f:
            for linea in f:
                partes = linea.split()
                if len(partes) < 3:
                    continue
                punto = partes[1].replace("\\040", " ")
                if (real == punto or real.startswith(punto.rstrip("/") + "/")) and len(punto) >= len(mejor):
                    mejor, tipo = punto, partes[2]
        return tipo
    except OSError:
        return None


def compartida() -> bool:
    """¿La carpeta de datos es la compartida con Windows? (en Windows siempre; en Linux, si está en NTFS)."""
    return config.IS_WINDOWS or sistema_de_archivos(Path(config.DATA_DIR)) in NTFS


# ─────────────────────────────────────────────
# Comprobaciones
# ─────────────────────────────────────────────

CONSEJO_NTFS = (
    "Si es la partición compartida con Windows, lo normal es que Windows se quedara hibernado o con el inicio rápido "
    "activo y Linux la montara en solo lectura: arranca Windows, apágalo del todo (Inicio → Apagar, con el inicio "
    "rápido desactivado: docs/windows.md §5) y vuelve."
)


def comprobar_marca() -> None:
    marca = Path(config.DATA_DIR) / MARCA_MOVIDO
    if marca.is_file():
        try:
            texto = marca.read_text(encoding="utf-8").strip()
        except OSError:
            texto = ""
        raise ArranqueDenegado(
            "datos-movidos",
            f"Los datos de {config.DATA_DIR} se movieron a otra carpeta y estos son los viejos. {texto}".strip(),
            "Arranca el panel con las rutas nuevas (panel.env) o deshaz el cambio: "
            "python -m scripts.datos_compartidos volver",
        )


def comprobar_windows() -> None:
    """En Linux: lo que vio start.ps1 la última vez que arrancó en Windows."""
    if config.IS_WINDOWS:
        return
    try:
        estado = json.loads((Path(config.DATA_DIR) / ESTADO_WINDOWS).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return
    activos = [
        n for k, n in (("inicio_rapido", "el inicio rápido"), ("hibernacion", "la hibernación")) if estado.get(k)
    ]
    if activos:
        raise ArranqueDenegado(
            "windows-hibernacion",
            f"Windows dijo el {estado.get('comprobado', '?')} que tiene {' y '.join(activos)} activos: podría pisar al "
            "volver lo que escriba Linux en la partición. El panel no escribe nada.",
            "En Windows: powercfg /h off (docs/windows.md §5), entra una vez para que start.ps1 lo vea y apaga del todo.",
        )


def comprobar_escritura() -> None:
    for d in carpetas():
        try:
            if not d.is_dir():
                if not d.parent.is_dir():  # p. ej. la partición sin montar: no se crea una carpeta de datos vacía
                    raise OSError(f"no existe {d.parent} (¿unidad sin montar?)")
                d.mkdir(exist_ok=True)
            if hasattr(os, "statvfs") and os.statvfs(d).f_flag & getattr(os, "ST_RDONLY", 1):
                raise OSError("montada en solo lectura")
            prueba = d / f".panel-prueba-{os.getpid()}.tmp"
            with open(prueba, "wb") as f:
                f.write(b"ok")
                f.flush()
                os.fsync(f.fileno())
            prueba.unlink()
        except OSError as e:
            raise ArranqueDenegado(
                "solo-lectura",
                f"No se puede escribir en {d} ({e}). El panel no arranca para no dejar datos a medias.",
                CONSEJO_NTFS,
            ) from e


def leer_cerrojo() -> dict | None:
    try:
        return json.loads(cerrojo_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log.warning("Cerrojo ilegible (%s): se trata como un cierre sucio", e)
        return {"sistema": "?", "equipo": "?", "pid": 0, "arranque": "?", "abierto": None, "cerrado": None}


def _escribir_cerrojo(datos: dict) -> None:
    atomic_write(cerrojo_path(), json.dumps(datos, ensure_ascii=False, indent=1) + "\n")


def wal_pendiente() -> list[str]:
    """BDs con algo en el -wal (transacciones que aún no pasaron al .db)."""
    out = []
    for db in bases():
        wal = Path(f"{db}-wal")
        try:
            if wal.stat().st_size > 0:
                out.append(db.name)
        except OSError:
            pass
    return out


def quien(c: dict | None) -> str:
    if not c:
        return "nadie"
    nombre = {"linux": "Linux", "windows": "Windows"}.get(c.get("sistema"), c.get("sistema") or "?")
    return f"{nombre} ({c.get('equipo') or '?'})"


def _es_otro_sistema(c: dict, yo: dict) -> bool:
    return (c.get("sistema"), c.get("equipo")) != (yo["sistema"], yo["equipo"])


def revisar_copia(motivo: str) -> dict:
    """Copia en bruto (.db + -wal, sin abrirlas) a las copias de ESTE sistema y integrity_check sobre la copia (abrirla
    recupera allí el WAL). Nunca escribe en la carpeta de datos. {carpeta, bases: {nombre: "ok" | error}, ok}."""
    carpeta = Path(config.BACKUPS_DIR) / f"{motivo}-{datetime.now():%Y%m%d-%H%M%S}"
    carpeta.mkdir(parents=True, exist_ok=True)
    resultado: dict = {}
    for db in bases():
        if not db.is_file():
            continue
        destino = carpeta / db.name
        try:
            shutil.copyfile(db, destino)
            if Path(f"{db}-wal").is_file():
                shutil.copyfile(f"{db}-wal", f"{destino}-wal")
            conn = sqlite3.connect(destino)
            try:
                ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                conn.close()
            resultado[db.name] = ok
        except (OSError, sqlite3.Error) as e:
            resultado[db.name] = f"error: {e}"
    if Path(config.CALENDAR_STATE).is_file():
        try:
            shutil.copyfile(config.CALENDAR_STATE, carpeta / Path(config.CALENDAR_STATE).name)
        except OSError:
            pass
    return {
        "carpeta": str(carpeta),
        "bases": resultado,
        "ok": bool(resultado) and all(v == "ok" for v in resultado.values()),
        "at": time.time(),
    }


def _revisiones_path() -> Path:
    # En las copias de ESTE sistema, no en la carpeta de datos: con un cierre sucio no se escribe nada allí
    return Path(config.BACKUPS_DIR) / "cierre-sucio.json"


def _clave(c: dict) -> str:
    return f"{c.get('sistema')}|{c.get('equipo')}|{c.get('pid')}|{c.get('abierto')}"


def _revision_guardada(c: dict) -> dict | None:
    """La comprobación ya hecha de este mismo cierre sucio: reintentar el arranque no hace otra copia."""
    try:
        datos = json.loads(_revisiones_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rev = datos.get("revision") if datos.get("clave") == _clave(c) else None
    return rev if rev and Path(rev.get("carpeta", "")).is_dir() else None


def _guardar_revision(c: dict, revision: dict) -> None:
    try:
        atomic_write(_revisiones_path(), json.dumps({"clave": _clave(c), "revision": revision}, ensure_ascii=False))
    except OSError:
        pass


def _recuperar_wal() -> None:
    """Pasa al .db lo que quedó en el -wal (abrir en escritura hace la recuperación de SQLite) y lo vacía."""
    for db in bases():
        if db.is_file():
            conn = sqlite3.connect(db, timeout=30)
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                conn.close()


def _copia_cambio_sistema() -> str:
    from app import backup

    try:
        return backup.create_backup("cambio-sistema")["filename"]
    except backup.BackupError as e:
        raise ArranqueDenegado(
            "copia",
            f"No se pudo hacer la copia previa al cambio de sistema ({e}): el panel no escribe sin ella.",
            f"Revisa el espacio y la carpeta de copias ({config.BACKUPS_DIR}) y vuelve a arrancar.",
        ) from e


def _denegar_cierre_sucio(c: dict, revision: dict, yo: dict) -> None:
    detalle = ", ".join(f"{k}: {v}" for k, v in revision["bases"].items()) or "sin BDs"
    if revision["ok"]:
        raise ArranqueDenegado(
            "cierre-sucio",
            f"{quien(c)} no cerró bien el panel (quedaron cambios en el WAL). La copia de comprobación está bien "
            f"({detalle}; en {revision['carpeta']}), pero el panel no escribe nada hasta que lo confirmes.",
            "python -m scripts.datos_compartidos seguir"
            + ("  (en Windows: start.ps1 -Seguir)" if yo["sistema"] == "windows" else ""),
        )
    raise ArranqueDenegado(
        "cierre-sucio-dañado",
        f"{quien(c)} no cerró bien el panel y la comprobación de las BDs FALLA ({detalle}). Copia en bruto en "
        f"{revision['carpeta']}. El panel no escribe nada.",
        "Restaura la última copia buena desde las copias de este sistema (docs/recuperacion.md) antes de seguir.",
    )


def comprobar_cerrojo() -> dict:
    """Decide con el cerrojo que encuentra (docs/windows.md §3.3). Devuelve un informe; no escribe el cerrojo."""
    yo, c = identidad(), leer_cerrojo()
    informe: dict = {"anterior": c, "aviso": None, "copia": None}
    if not c or c.get("cerrado"):
        if c and _es_otro_sistema(c, yo):
            informe["copia"] = _copia_cambio_sistema()
            informe["nota"] = f"Último en abrir los datos: {quien(c)}; copia {informe['copia']}"
        return informe
    # Abierto
    if c.get("pid") == yo["pid"] and not _es_otro_sistema(c, yo) and _mismo_arranque(c.get("arranque"), yo["arranque"]):
        return informe  # este mismo proceso (el lifespan vuelve a entrar: tests, recargas)
    if (
        not _es_otro_sistema(c, yo)
        and _mismo_arranque(c.get("arranque"), yo["arranque"])
        and _proceso_vivo(c.get("pid") or 0)
    ):
        raise ArranqueDenegado(
            "en-uso",
            f"Ya hay otro panel usando estos datos (proceso {c['pid']}, desde "
            f"{datetime.fromtimestamp(c.get('abierto') or 0):%d/%m %H:%M}).",
            "Para ese panel antes de arrancar este, o arranca este con otra carpeta de datos (PANEL_DATA_DIR…).",
        )
    pendiente = wal_pendiente()
    otro = _es_otro_sistema(c, yo)
    if not pendiente:  # se apagó sin cerrar, pero los datos estaban en reposo: como un cierre limpio
        informe["nota"] = f"{quien(c)} no cerró el panel, pero los datos estaban en reposo"
        if otro:
            informe["copia"] = _copia_cambio_sistema()
        return informe
    revision = _revision_guardada(c)
    if not revision:
        revision = revisar_copia("cierre-sucio")
        _guardar_revision(c, revision)
    if otro:
        _denegar_cierre_sucio(c, revision, yo)
    if not revision["ok"]:
        _denegar_cierre_sucio(c, revision, yo)
    # Este mismo sistema se cayó (corte de luz, proceso matado): la copia está bien → se recupera el WAL y se sigue
    _recuperar_wal()
    informe["aviso"] = (
        f"El panel no se cerró bien la última vez ({', '.join(pendiente)} con cambios en el WAL). Comprobado: las BDs "
        f"están bien; copia en «{Path(revision['carpeta']).name}», en las copias."
    )
    return informe


# ─────────────────────────────────────────────
# Arranque y cierre
# ─────────────────────────────────────────────


def _anotar_denegado(e: ArranqueDenegado) -> None:
    try:
        Path(config.LOGS_DIR).mkdir(parents=True, exist_ok=True)
        atomic_write(
            denegado_path(),
            json.dumps(
                {"motivo": e.motivo, "mensaje": e.mensaje, "accion": e.accion, "at": time.time()},
                ensure_ascii=False,
                indent=1,
            ),
        )
    except OSError:
        pass
    # Bajo systemd (INVOCATION_ID) nadie ve la consola: notificación del escritorio, si la hay. PANEL_NOTIFY, como en los
    # scripts del escritorio, cambia el programa (los tests lo apuntan a `true`: si no, sus casos de cierre sucio y BD rota
    # salían como avisos de verdad en el escritorio, porque la terminal también hereda INVOCATION_ID de la sesión)
    notify = os.environ.get("PANEL_NOTIFY", "notify-send")
    if os.environ.get("INVOCATION_ID") and not config.IS_WINDOWS and shutil.which(notify):
        try:
            subprocess.run(
                [notify, "-u", "critical", "-a", "Panel Maestro", "El panel no arranca", str(e)],
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            pass


def al_arrancar() -> dict:
    """Todas las guardas, en orden. Lanza ArranqueDenegado (ya anotado) o devuelve el informe."""
    try:
        comprobar_marca()
        comprobar_windows()
        comprobar_escritura()
        informe = comprobar_cerrojo()
        _escribir_cerrojo({**identidad(), "abierto": time.time(), "cerrado": None})
    except ArranqueDenegado as e:
        log.critical("El panel NO arranca [%s]: %s", e.motivo, e)
        _anotar_denegado(e)
        raise
    global _abiertos
    with _cierre:
        _abiertos += 1
    denegado_path().unlink(missing_ok=True)
    if informe.get("aviso"):
        log.warning("%s", informe["aviso"])
    elif informe.get("nota"):
        log.info("%s", informe["nota"])
    _estado.clear()
    _estado.update(informe, at=time.time(), compartida=compartida())
    if sys.platform == "win32":
        vigilar_apagado_windows()
    return informe


def checkpoint(modo: str = "TRUNCATE") -> None:
    for db in bases():
        if not db.is_file():
            continue
        try:
            conn = sqlite3.connect(db, timeout=10)
            try:
                conn.execute(f"PRAGMA wal_checkpoint({modo})")
            finally:
                conn.close()
        except sqlite3.Error as e:
            log.warning("Checkpoint de %s: %s", db.name, e)


def checkpoint_en_reposo() -> None:
    """Tarea cada 2 min: si el WAL tiene algo, pasa al .db. Un apagado brusco deja así los datos en reposo."""
    if wal_pendiente():
        checkpoint("TRUNCATE")


def al_cerrar(forzar: bool = False) -> None:
    """Checkpoint de las dos BDs y cerrojo «cerrado» (si sigue siendo nuestro y era el último lifespan abierto, o con
    `forzar`: fin de sesión de Windows). Se puede llamar más de una vez."""
    global _abiertos
    with _cierre:
        _abiertos = max(0, _abiertos - 1)
        checkpoint("TRUNCATE")
        if _abiertos and not forzar:
            return
        c, yo = leer_cerrojo(), identidad()
        if c and c.get("pid") == yo["pid"] and not _es_otro_sistema(c, yo) and not c.get("cerrado"):
            try:
                _escribir_cerrojo({**c, "cerrado": time.time()})
            except OSError as e:
                log.warning("No se pudo marcar el cerrojo como cerrado: %s", e)
                return
            log.info("Datos cerrados limpiamente")


def seguir() -> dict:
    """Tras un cierre sucio del otro sistema (lo pide quien arranca a mano): repite la comprobación y, solo si está
    bien, recupera el WAL y deja el cerrojo cerrado. No arranca el panel. {ok, mensaje, revision?}."""
    c = leer_cerrojo()
    if not c or c.get("cerrado"):
        return {"ok": True, "mensaje": "No hay ningún cierre sucio pendiente."}
    yo = identidad()
    if (
        not _es_otro_sistema(c, yo)
        and _mismo_arranque(c.get("arranque"), yo["arranque"])
        and _proceso_vivo(c.get("pid") or 0)
    ):
        return {"ok": False, "mensaje": f"El panel está en marcha (proceso {c['pid']}): no hay nada que confirmar."}
    if not wal_pendiente():
        revision = None
    else:
        revision = revisar_copia("cierre-sucio")
        if not revision["ok"]:
            return {
                "ok": False,
                "revision": revision,
                "mensaje": f"La comprobación falla: {revision['bases']}. Restaura una copia (docs/recuperacion.md).",
            }
        _recuperar_wal()
    _escribir_cerrojo({**c, "cerrado": time.time(), "aceptado": time.time(), "revision": revision})
    return {
        "ok": True,
        "revision": revision,
        "mensaje": "Comprobado: las BDs están bien. Ya puedes arrancar el panel"
        + (f" (copia en {revision['carpeta']})." if revision else "."),
    }


# ─────────────────────────────────────────────
# Windows: cierre limpio al apagar
# ─────────────────────────────────────────────

_vigilando = False


def vigilar_apagado_windows() -> None:
    """Ventana oculta que recibe el fin de sesión (WM_ENDSESSION): un proceso sin ventana no se entera y Windows lo mata.
    Es lo que indica la documentación de SetConsoleCtrlHandler para una aplicación que carga user32."""
    global _vigilando
    if _vigilando or sys.platform != "win32":
        return
    _vigilando = True
    threading.Thread(target=_bucle_ventana, name="apagado-windows", daemon=True).start()


def _bucle_ventana() -> None:  # pragma: no cover - solo en Windows (prueba guiada en docs/windows.md §8)
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    lresult = ctypes.c_ssize_t
    wndproc_t = ctypes.WINFUNCTYPE(lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    wm_queryendsession, wm_endsession = 0x0011, 0x0016

    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = lresult

    def proc(hwnd, msg, wparam, lparam):
        try:
            if msg == wm_queryendsession:
                log.info("Aviso de fin de sesión de Windows recibido")
                checkpoint("TRUNCATE")  # adelanta el trabajo; el cerrojo, solo si la sesión termina de verdad
                return 1
            if msg == wm_endsession:
                if wparam:
                    al_cerrar(forzar=True)
                return 0
        except Exception:  # noqa: BLE001 - una excepción aquí no puede tumbar el bucle de mensajes
            log.exception("Cierre por fin de sesión")
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", wndproc_t),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    callback = wndproc_t(proc)  # referencia viva mientras dure el bucle
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    instancia = kernel32.GetModuleHandleW(None)
    clase = WNDCLASSW()
    clase.lpfnWndProc = callback
    clase.hInstance = instancia
    clase.lpszClassName = "PanelMaestroApagado"
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    if not user32.RegisterClassW(ctypes.byref(clase)):
        log.warning("Sin aviso de apagado: RegisterClassW falló (%s)", ctypes.get_last_error())
        return
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    # Ventana normal sin mostrar (no «solo mensajes»: esas no reciben el aviso de fin de sesión)
    hwnd = user32.CreateWindowExW(0, clase.lpszClassName, "Panel Maestro", 0, 0, 0, 0, 0, None, None, instancia, None)
    if not hwnd:
        log.warning("Sin aviso de apagado: CreateWindowExW falló (%s)", ctypes.get_last_error())
        return
    log.info("Vigilando el fin de sesión de Windows para cerrar los datos limpiamente")
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


# ─────────────────────────────────────────────
# Estado para «Conexiones» (/api/status)
# ─────────────────────────────────────────────


def _misma_unidad(a: Path, b: Path) -> bool:
    """¿Misma unidad? Una carpeta que aún no existe cuenta por la primera de sus padres que sí."""
    try:
        a = next((p for p in (a, *a.parents) if p.exists()), a)
        return b.exists() and os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def status_item() -> dict | None:
    """Aviso de la carpeta de datos: cierre sucio recuperado, o copias en la misma unidad que unos datos compartidos.
    Nada si todo es lo de siempre (datos locales sin incidencias)."""
    if not _estado:
        return None
    avisos = []
    if _estado.get("aviso"):
        avisos.append(_estado["aviso"])
    if _estado.get("compartida"):
        data = Path(config.DATA_DIR)
        if _misma_unidad(Path(config.BACKUPS_DIR), data):
            avisos.append(f"Las copias ({config.BACKUPS_DIR}) están en la misma unidad que los datos compartidos.")
        if config.BACKUP_MIRROR and _misma_unidad(Path(config.BACKUP_MIRROR), data):
            avisos.append(f"El espejo ({config.BACKUP_MIRROR}) está en la misma unidad que los datos compartidos.")
    if not avisos and not _estado.get("compartida"):
        return None
    anterior = _estado.get("anterior")
    return {
        "key": "datos",
        "name": "Carpeta de datos",
        "icon": "folder-sync",
        "state": "aviso" if avisos else "ok",
        "label": "Revisar" if avisos else "Compartida con Windows",
        "last_ok": _estado.get("at"),
        "detail": " ".join(avisos) or (_estado.get("nota") or f"Antes la abrió {quien(anterior)}"),
        "action": None,
    }
