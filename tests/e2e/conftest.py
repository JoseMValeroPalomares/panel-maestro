"""
Tests de navegador (Playwright): arrancan el panel de verdad en un puerto libre,
con datos temporales, y lo manejan con Chromium. Nunca tocan los datos reales.

Navegador: el de PLAYWRIGHT_CHROMIUM o el de la caché ~/.cache/ms-playwright.
Si no hay ninguno, los tests se saltan (no fallan).
"""
import glob
import os
from functools import partial
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from tests.e2e.helpers import wait_js

ROOT = Path(__file__).resolve().parents[2]


def _chromium() -> str | None:
    env = os.environ.get("PLAYWRIGHT_CHROMIUM")
    if env and os.path.exists(env):
        return env
    found = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome")))
    return found[-1] if found else None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture(scope="session")
def dotfiles_env(tmp_path_factory):
    """Un ~ y un repo de dotfiles de pruebas, con su remoto: el panel de los tests nunca ve los de verdad."""
    root = tmp_path_factory.mktemp("dotfiles")
    home, repo, remote = root / "home", root / "repo", root / "remoto.git"
    live = home / ".config" / "app" / "a.conf"
    tracked = repo / "stow" / "app" / ".config" / "app" / "a.conf"
    live.parent.mkdir(parents=True)
    tracked.parent.mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "check-secrets.sh").write_text(
        "out=$(grep -rIn 'ghp_' stow || true)\nif [ -n \"$out\" ]; then echo \"$out\" | sed 's/^/  ! /'; exit 1; fi\n")
    live.write_text("uno\ndos\ntres\n")
    tracked.write_text("uno\ndos\ntres\n")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    _git(repo, "config", "user.name", "Pruebas")
    _git(repo, "config", "user.email", "pruebas@example.com")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "copia inicial")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "main")
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    return {"home": home, "repo": repo, "remote": remote, "live": live, "base": base}


@pytest.fixture(scope="session")
def proyecto_env(tmp_path_factory):
    """Un repo del panel de pruebas con su remoto; sin scripts/publicar.sh (copias públicas) la tarjeta no aparece."""
    root = tmp_path_factory.mktemp("proyecto")
    repo, remote = root / "repo", root / "remoto.git"
    (repo / "scripts").mkdir(parents=True)
    (repo / "app.py").write_text("print('hola')\n")
    (repo / "PROGRESS.md").write_text("diario privado\n")
    (repo / ".publicignore").write_text(".publicignore\nscripts/publicar.sh\nPROGRESS.md\n")
    if (ROOT / "scripts" / "publicar.sh").is_file():
        shutil.copy(ROOT / "scripts" / "publicar.sh", repo / "scripts" / "publicar.sh")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    _git(repo, "config", "user.name", "Pruebas")
    _git(repo, "config", "user.email", "pruebas@example.com")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "inicio")
    _git(repo, "remote", "add", "github", str(remote))
    return {"repo": repo, "remote": remote}


def _proveedor_ia_falso(tmp: Path) -> dict:
    """Proveedor de IA simulado (API tipo OpenAI) en un puerto libre: devuelve la nota con unas erratas corregidas.
    Así el botón «Corregir con IA» se prueba de principio a fin sin red ni claves reales."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            partes = body["messages"][-1]["content"].split("=== NOTA ===\n", 1)
            nota = partes[1] if len(partes) == 2 else "ok"      # la prueba de Ajustes no lleva nota
            for a, b in (("tension", "tensión"), ("Tension", "Tensión"), ("capitulo", "capítulo"), ("Simbolo", "Símbolo")):
                nota = nota.replace(a, b)
            data = json.dumps({"choices": [{"message": {"content": nota}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 50, "completion_tokens": 50}}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    port = _free_port()
    srv = HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    f = tmp / "modelos-e2e.json"
    f.write_text(json.dumps({"max_intentos_total": 4, "reintentos_por_modelo": 1, "modelos": [
        {"id": "e2e-falso", "proveedor": "Proveedor simulado", "base_url": f"http://127.0.0.1:{port}/v1", "modelo": "modelo-falso", "clave_env": "E2E_IA_KEY", "timeout_s": 10}]}))
    return {"PANEL_LLM_MODELS": str(f), "E2E_IA_KEY": "x", "_srv": srv}


@pytest.fixture(scope="session")
def server(dotfiles_env, proyecto_env):
    tmp = Path(tempfile.mkdtemp(prefix="panel-e2e-"))
    ia = _proveedor_ia_falso(tmp)
    srv_ia = ia.pop("_srv")
    (tmp / "data" / "notes").mkdir(parents=True)
    (tmp / "data" / "notes" / "plan-e2e.md").write_text(
        "---\ncategory: E2E\nstatus: por-escribir\ntitle: Plan E2E\n---\n\n# Plan\n\n- [ ] Tarea de nota uno\n- [ ] Tarea de nota dos\n",
        encoding="utf-8")
    port = _free_port()
    env = {**os.environ, "PANEL_DATA_DIR": str(tmp / "data"), "PANEL_NOTES_DIR": str(tmp / "data" / "notes"),
           "PANEL_BRAIN_DB": str(tmp / "data" / "brain.db"), "PANEL_COMIDAS_DB": str(tmp / "comidas.db"),
           "PANEL_UPLOADS_DIR": str(tmp / "uploads"), "PANEL_BACKUPS_DIR": str(tmp / "backups"),
           "PANEL_LOGS_DIR": str(tmp / "logs"), "PANEL_TRASH_DIR": str(tmp / "data" / "trash"),
           "PANEL_DOTFILES_DIR": str(dotfiles_env["repo"]), "PANEL_DOTFILES_HOME": str(dotfiles_env["home"]),
           "PANEL_DOTFILES_BASE": dotfiles_env["base"], "PANEL_PROJECT_DIR": str(proyecto_env["repo"]),
           "PANEL_AUTH_DISABLED": "1", "PANEL_DISABLE_BRIDGES": "1", "PANEL_DISABLE_SCHEDULER": "1",
           "PANEL_LOG_LEVEL": "WARNING",
           # ESP32 «apagado»: una dirección de documentación (TEST-NET-1) que nunca responde, como la placa sin
           # corriente; la del .env depende de la red (si otro equipo ocupa esa IP, contesta y el test cambia)
           "ESP32_HOST": "192.0.2.1", **ia}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("El servidor de pruebas no arrancó: " + proc.stderr.read().decode()[-2000:])
    yield base
    proc.terminate()
    proc.wait(timeout=10)
    srv_ia.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def browser():
    exe = _chromium()
    if not exe:
        pytest.skip("No hay Chromium para Playwright (define PLAYWRIGHT_CHROMIUM)")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, headless=True)
        yield b
        b.close()


@pytest.fixture()
def context(browser):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, service_workers="block")
    ctx.on("page", lambda pg: setattr(pg, "wait_for_function", partial(wait_js, pg)))
    yield ctx
    ctx.close()


@pytest.fixture()
def page(context, server):
    # vistas que se recuerdan en el servidor: cada test empieza con las de por defecto
    import httpx
    for key, value in (("inbox-pane", "lista"), ("inbox-type", "all"), ("tareas-filters", None), ("tareas-view", None), ("tareas-sizes", None), ("nav-folded", None), ("calendar-hour-size", None)):
        httpx.put(f"{server}/api/prefs/{key}", json={"value": value}, timeout=10)
    pg = context.new_page()
    errors = []
    # Lo que anota el navegador sin que sea un fallo de la app:
    # - los intentos de conexión con el ESP32 de pruebas (192.0.2.1, ver arriba) fallan a propósito (según la red,
    #   «sin respuesta» o lo que conteste un proxy);
    # - la transición entre páginas (@view-transition en ds.css) que Chrome aborta cuando el test navega otra vez
    #   antes de que la página se muestre («Transition was aborted… Page already revealed»);
    # - el 409 de un bloque de rutina que choca con otro: es una respuesta esperada, y la app la enseña en un aviso.
    benign = ("WebSocket connection to 'ws://192.0.2.1/", "Transition was aborted because of invalid state",
              "Failed to load resource: the server responded with a status of 409")
    pg.on("pageerror", lambda e: not str(e).startswith(benign) and errors.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and not m.text.startswith(benign) and errors.append(m.text))
    yield pg
    assert not errors, f"Errores en la consola: {errors}"


@pytest.fixture()
def api(server):
    """Cliente HTTP mínimo contra el servidor de pruebas."""
    import httpx
    with httpx.Client(base_url=server, timeout=10) as c:
        yield c
