#!/usr/bin/env python3
"""
Abridor de carpetas y archivos del Panel (esquema panelmaestro://) — para el PORTÁTIL.

El navegador no abre file:// desde una página http, y si lo abriera el servidor saldría en su
pantalla. Así que la página enlaza a

    panelmaestro://abrir/<asignatura|tema|proyecto>/<id>

y este script (registrado con xdg-mime, ver instalar.sh) hace, sin recibir NUNCA una ruta:
  1. valida la URL con una expresión estricta (tipo conocido + número);
  2. pide al panel la ruta RELATIVA de ese id (GET /api/abrir/<tipo>/<id>, con el token del escritorio);
  3. la resuelve contra la raíz permitida de ~/.config/panel-maestro/abrir.conf (permisos 600):
     sin rutas absolutas ni «..», realpath dentro de la raíz (un enlace simbólico que escape se rechaza)
     y que exista;
  4. la abre con xdg-open (carpeta → gestor de archivos, archivo → su programa).
Cualquier otra cosa no hace nada (solo un aviso).

    abrir.py panelmaestro://abrir/tema/12            abre
    abrir.py --dry-run panelmaestro://abrir/tema/12  imprime la ruta que abriría (pruebas)

abrir.conf (INI):
    [raices]
    universidad = /run/media/usuario/DISCO/Universidad
    proyectos = ~/Projects
PANEL_ABRIR_CONF, PANEL_NOTIFY y PANEL_OPENER permiten sustituirlos en las pruebas.
"""

import configparser
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import panel_client as pc  # noqa: E402

URL_RE = re.compile(r"^panelmaestro://abrir/(asignatura|tema|proyecto)/([1-9]\d{0,8})/?$")
CONF = Path(os.environ.get("PANEL_ABRIR_CONF") or pc.CONF / "abrir.conf")
RAICES = ("universidad", "proyectos")


class Rechazo(Exception):
    """No se abre nada (motivo para el aviso)."""


def notify(title: str, body: str) -> None:
    try:
        subprocess.run(
            [os.environ.get("PANEL_NOTIFY", "notify-send"), "-a", "Panel", "-i", "folder", title, body],
            timeout=5,
            check=False,
            capture_output=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def raices() -> dict[str, Path]:
    if not CONF.exists():
        raise Rechazo(f"Falta {CONF} (ejecuta instalar.sh)")
    st = CONF.stat()
    if stat.S_IMODE(st.st_mode) & 0o077 or st.st_uid != os.getuid():
        raise Rechazo(f"{CONF} debe ser tuyo y con permisos 600")
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(CONF, encoding="utf-8")
    out = {}
    for k in RAICES:
        v = cp.get("raices", k, fallback="").strip()
        if v:
            p = Path(os.path.expanduser(v))
            if not p.is_absolute():
                raise Rechazo(f"La raíz «{k}» de {CONF} no es una ruta absoluta")
            out[k] = p
    return out


def resolver(raiz: Path, rel: str) -> Path:
    """La ruta relativa del panel dentro de la raíz permitida, o Rechazo."""
    if not isinstance(rel, str) or not rel or "\x00" in rel or any(ord(c) < 32 for c in rel):
        raise Rechazo("Ruta no válida")
    if rel.startswith(("/", "~", "\\")) or re.match(r"^[a-zA-Z]:", rel) or ".." in Path(rel).parts:
        raise Rechazo("La ruta tiene que ser relativa y sin «..»")
    base = os.path.realpath(raiz)
    full = os.path.realpath(os.path.join(base, rel))
    if full != base and not full.startswith(base + os.sep):
        raise Rechazo("La ruta sale de la carpeta permitida")
    if not os.path.exists(full):
        raise Rechazo(f"No existe {full} (¿disco sin montar?)")
    return Path(full)


def destino(url: str) -> Path:
    m = URL_RE.match(url.strip())
    if not m:
        raise Rechazo("Enlace no válido")
    tipo, ident = m.group(1), int(m.group(2))
    rs = raices()
    try:
        info = pc.request("GET", f"/api/abrir/{tipo}/{ident}")
    except pc.Offline:
        raise Rechazo("El panel no responde")
    except (pc.AuthError, RuntimeError) as e:
        raise Rechazo(str(e))
    raiz = info.get("raiz")
    if raiz not in rs:
        raise Rechazo(f"La raíz «{raiz}» no está permitida en {CONF}")
    return resolver(rs[raiz], info.get("ruta"))


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    args = [a for a in argv[1:] if a != "--dry-run"]
    if len(args) != 1:
        print(__doc__)
        return 2
    try:
        path = destino(args[0])
    except Rechazo as e:
        if dry:
            print(f"RECHAZADO: {e}")
        else:
            notify("Panel: no se abre", str(e))
        return 1
    if dry:
        print(path)
        return 0
    subprocess.Popen(
        [os.environ.get("PANEL_OPENER", "xdg-open"), str(path)],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
