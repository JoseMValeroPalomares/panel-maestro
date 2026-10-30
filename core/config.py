"""
Configuración central del panel.

Todo lo sensible o dependiente de la máquina se lee de variables de
entorno (cargadas desde `.env` en la raíz). Ver `.env.example`.
Las rutas de datos también son configurables para que los tests puedan
apuntar a un directorio temporal sin tocar los datos reales.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# override=False: si una variable ya viene del entorno (tests, systemd), manda esa.
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


# ── Rutas de datos ──────────────────────────────────────────────
DATA_DIR = Path(_env("PANEL_DATA_DIR") or PROJECT_ROOT / "data")
NOTES_DIR = Path(_env("PANEL_NOTES_DIR") or DATA_DIR / "notes")
BRAIN_DB = Path(_env("PANEL_BRAIN_DB") or DATA_DIR / "brain.db")
COMIDAS_DB = Path(_env("PANEL_COMIDAS_DB") or PROJECT_ROOT / "comidas" / "data" / "comidas.db")
UPLOADS_DIR = Path(_env("PANEL_UPLOADS_DIR") or PROJECT_ROOT / "static" / "uploads")
BACKUPS_DIR = Path(_env("PANEL_BACKUPS_DIR") or PROJECT_ROOT / "backups")
LOGS_DIR = Path(_env("PANEL_LOGS_DIR") or PROJECT_ROOT / "logs")
TRASH_DIR = Path(_env("PANEL_TRASH_DIR") or DATA_DIR / "trash")
# Repo de dotfiles y el ~ del que salen (app/dotfiles.py). BASE: commit con ~ tal cual si el repo se retocó después
DOTFILES_DIR = Path(_env("PANEL_DOTFILES_DIR") or Path.home() / "dotfiles")
DOTFILES_HOME = Path(_env("PANEL_DOTFILES_HOME") or Path.home())
DOTFILES_BASE = _env("PANEL_DOTFILES_BASE")
# Repo del propio panel que publica la página Copias (app/proyecto.py); los tests lo apuntan a uno temporal
PROJECT_DIR = Path(_env("PANEL_PROJECT_DIR") or PROJECT_ROOT)
# Última vez que se sincronizó el calendario (estudio/calendar_sync.py). Restaurar una copia lo borra: una instancia con
# otros datos (tests, demo, verificación) lo guarda con ellos y nunca toca el del panel real
CALENDAR_STATE = Path(_env("PANEL_CALENDAR_STATE") or (
    PROJECT_ROOT / "estudio" / "calendar_sync_v2.json" if DATA_DIR == PROJECT_ROOT / "data" else DATA_DIR / "calendar_sync_v2.json"))

# ── Autenticación ───────────────────────────────────────────────
PASSWORD_HASH = _env("PANEL_PASSWORD_HASH")
SESSION_SECRET = _env("PANEL_SESSION_SECRET")
API_TOKEN_HASH = _env("PANEL_API_TOKEN_HASH")
# Token aparte para los scripts del escritorio (captura con rofi, Waybar): así no se toca el de la extensión
DESKTOP_TOKEN_HASH = _env("PANEL_DESKTOP_TOKEN_HASH")
SESSION_DAYS = int(_env("PANEL_SESSION_DAYS", "30") or 30)
# Solo poner a true si se sirve detrás de HTTPS (si no, el navegador no guarda la cookie).
COOKIE_SECURE = _env_bool("PANEL_COOKIE_SECURE", False)
AUTH_DISABLED = _env_bool("PANEL_AUTH_DISABLED", False)  # solo para desarrollo local

# ── Integraciones ───────────────────────────────────────────────
ICLOUD_USERNAME = _env("ICLOUD_USERNAME")
ICLOUD_APP_PASSWORD = _env("ICLOUD_APP_PASSWORD")
ICLOUD_CALENDAR_NAME = _env("ICLOUD_CALENDAR_NAME", "Panel estudio")
# Sin ESP32_HOST no hay placa: la página Estudio funciona igual y no se intenta conectar
ESP32_HOST = _env("ESP32_HOST")
SERVER_BASE_URL = _env("SERVER_BASE_URL", "http://localhost:8000")

# Tests / modo headless: no arrancar puentes ESP32/iCloud ni el scheduler.
DISABLE_BRIDGES = _env_bool("PANEL_DISABLE_BRIDGES", False)
DISABLE_SCHEDULER = _env_bool("PANEL_DISABLE_SCHEDULER", False)
LOG_LEVEL = _env("PANEL_LOG_LEVEL", "INFO")
