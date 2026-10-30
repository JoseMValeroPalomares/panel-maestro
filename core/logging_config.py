"""Logging del panel: consola + archivo rotativo en logs/panel.log."""
import logging
import logging.handlers

from core import config

_configured = False


def setup_logging() -> logging.Logger:
    global _configured
    root = logging.getLogger("panel")
    if _configured:
        return root

    root.setLevel(config.LOG_LEVEL.upper() if config.LOG_LEVEL else "INFO")
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            config.LOGS_DIR / "panel.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        root.warning("No se pudo crear el log en %s; solo consola", config.LOGS_DIR)

    root.propagate = False
    _configured = True
    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"panel.{name}")
