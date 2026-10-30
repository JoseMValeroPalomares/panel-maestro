#!/usr/bin/env python3
"""
Cliente del Panel para el escritorio (captura rápida con rofi y módulo de la Waybar).
Solo biblioteca estándar: lo lanza el python del sistema, sin el venv del proyecto.

    panel_client.py capture "e: dentista mañana 17:00" [--dry-run]   → JSON (exit 0 ok, 3 en cola, 1 error)
    panel_client.py flush                                             → reenvía la cola (exit 0)
    panel_client.py get /api/calendar/agenda?days=3                   → JSON

Configuración (nunca en el repositorio):
    ~/.config/panel-maestro/token   token Bearer (permisos 600; lo crea `python -m scripts.desktop_token`)
    ~/.config/panel-maestro/url     dirección del panel (por defecto http://127.0.0.1:8000)
    PANEL_URL / PANEL_TOKEN_FILE / PANEL_STATE_DIR                    para pruebas
Cola sin conexión: ~/.local/state/panel-maestro/cola.jsonl (un texto por línea, en orden).
"""
import json
import os
import stat
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CONF = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "panel-maestro"
STATE = Path(os.environ.get("PANEL_STATE_DIR") or Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "panel-maestro")
QUEUE = STATE / "cola.jsonl"
TIMEOUT = float(os.environ.get("PANEL_TIMEOUT", "4"))


class Offline(Exception):
    """El panel no responde (se encola)."""


class AuthError(Exception):
    """Falta el token o no vale."""


def base_url() -> str:
    if os.environ.get("PANEL_URL"):
        return os.environ["PANEL_URL"].rstrip("/")
    f = CONF / "url"
    return f.read_text().strip().rstrip("/") if f.exists() else "http://127.0.0.1:8000"


def token() -> str:
    path = Path(os.environ.get("PANEL_TOKEN_FILE") or CONF / "token")
    if not path.exists():
        raise AuthError(f"Falta el token en {path}: python -m scripts.desktop_token")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise AuthError(f"{path} debe tener permisos 600 (tiene {oct(mode)}): chmod 600 {path}")
    return path.read_text().strip()


def request(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(base_url() + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json",
                                          "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise AuthError("El panel no acepta el token (¿reiniciado tras crearlo?)")
        try:
            detail = json.loads(e.read()).get("error") or f"Error {e.code}"
        except ValueError:
            detail = f"Error {e.code}"
        raise RuntimeError(detail)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise Offline(str(e))


def enqueue(text: str) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    with open(QUEUE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"text": text, "at": time.time()}, ensure_ascii=False) + "\n")


def queued() -> list[dict]:
    if not QUEUE.exists():
        return []
    out = []
    for line in QUEUE.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def flush() -> dict:
    """Reenvía la cola en orden; lo que no sale se queda (y lo que sale, se quita)."""
    pending = queued()
    sent, results = 0, []
    for i, item in enumerate(pending):
        try:
            results.append(request("POST", "/api/capture", {"text": item["text"]}))
            sent += 1
        except Offline:
            break
        except RuntimeError as e:  # el panel lo rechaza: se descarta para no atascar la cola
            results.append({"status": "error", "message": str(e), "text": item["text"]})
            sent += 1
    rest = pending[sent:]
    if rest:
        STATE.mkdir(parents=True, exist_ok=True)
        tmp = QUEUE.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rest), encoding="utf-8")
        tmp.replace(QUEUE)
    elif QUEUE.exists():
        QUEUE.unlink()
    return {"sent": sent, "left": len(rest), "results": results}


def capture(text: str, dry_run: bool = False) -> dict:
    """Primero vacía la cola (el orden importa) y después manda esto; sin panel, a la cola."""
    try:
        if not dry_run and queued():
            flush()
        return request("POST", "/api/capture", {"text": text, "dry_run": dry_run})
    except Offline:
        if dry_run:
            return {"status": "offline", "message": "El panel no responde"}
        enqueue(text)
        return {"status": "queued", "message": f"Sin conexión: guardado en la cola ({len(queued())} pendiente{'s' if len(queued()) != 1 else ''})"}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    try:
        if argv[1] == "capture":
            res = capture(argv[2], dry_run="--dry-run" in argv)
            print(json.dumps(res, ensure_ascii=False))
            return 3 if res.get("status") in ("queued", "offline") else 0
        if argv[1] == "flush":
            print(json.dumps(flush(), ensure_ascii=False))
            return 0
        if argv[1] == "get":
            print(json.dumps(request("GET", argv[2]), ensure_ascii=False))
            return 0
    except Offline as e:
        print(json.dumps({"status": "offline", "message": f"El panel no responde ({e})"}, ensure_ascii=False))
        return 3
    except (AuthError, RuntimeError) as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
        return 1
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
