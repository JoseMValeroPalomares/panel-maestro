"""App raíz del panel (Cerebro): arranque, tareas programadas y rutas. Cada área vive en su módulo de app/."""

import contextlib
import os
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.atrasadas import router as atrasadas_router
from app.backup import ensure_recent_backup
from app.backups_api import router as backups_router
from app.boards import api_router as boards_api_router
from app.boards import router as boards_router
from app.bulk import router as bulk_router
from app.calendar import router as calendar_router
from app.capture import router as capture_router
from app.contador import router as contador_router
from app.contextos import router as contextos_router
from app.database import get_db, init_db
from app.dotfiles import router as dotfiles_router
from app.extension import router as extension_router
from app.finance import router as finance_router
from app.graph import router as graph_router
from app.ia_flashcards import router as ia_flashcards_router
from app.ia_notas import router as ia_notas_router
from app.indexer import sync_notes_to_db
from app.items import router as items_router
from app.links import router as links_router
from app.note_tasks import sync_all_note_items
from app.notes import router as notes_router
from app.ordering import router as ordering_router
from app.overview import router as overview_router
from app.pages import router as pages_router
from app.plantillas import router as plantillas_router
from app.prefs import router as prefs_router
from app.proyecto import router as proyecto_router
from app.proyectos import router as proyectos_router
from app.reminders import router as reminders_router
from app.rendimiento import router as rendimiento_router
from app.rendimiento_ia import router as rendimiento_ia_router
from app.review import router as review_router
from app.routine_templates import router as routine_templates_router
from app.rutina_rapida import router as rutina_rapida_router
from app.search import router as search_router
from app.study import router as study_router
from app.trash import purge_if_due as purge_trash_if_due
from app.trash import router as trash_router
from app.universidad import open_router as abrir_router
from app.universidad import router as universidad_router
from app.uploads import router as uploads_router
from app.vault import backfill_channels, backfill_thumbnails, backfill_video_metadata
from app.vault import router as vault_router
from app.versions import router as versions_router
from core import config
from core.logging_config import get_logger

log = get_logger("cerebro")

# ─────────────────────────────────────────────
# Programador: copias diarias, miniaturas y purga de la papelera
# ─────────────────────────────────────────────

scheduler = BackgroundScheduler()


def _catch_up() -> None:
    ensure_recent_backup()
    purge_trash_if_due()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Iniciando Segundo Cerebro...")
    init_db()
    sync_notes_to_db()
    with get_db() as conn:  # casillas de las notas -> lista única de tareas
        sync_all_note_items(conn)
    if not config.DISABLE_SCHEDULER:
        # Una vez al arrancar, en segundo plano: miniaturas externas -> caché local
        scheduler.add_job(backfill_thumbnails, id="backfill_thumbnails", replace_existing=True)
        scheduler.add_job(backfill_video_metadata, id="backfill_video_metadata", replace_existing=True)
        scheduler.add_job(backfill_channels, id="backfill_channels", replace_existing=True)
        # Copia de cada noche. El portátil suele estar dormido a esa hora: si el disparo se pierde, se lanza al despertar
        # (misfire_grace_time, una sola vez con coalesce), y si hubo una en las últimas 12 h no se repite
        scheduler.add_job(
            ensure_recent_backup,
            CronTrigger(hour=3, minute=30),
            kwargs={"max_age_h": 12},
            id="daily_backup",
            replace_existing=True,
            misfire_grace_time=12 * 3600,
            coalesce=True,
        )
        # Papelera: lo que lleva más de 30 días se vacía solo (app/trash.py), como mucho una vez al día
        scheduler.add_job(
            purge_trash_if_due,
            CronTrigger(hour=3, minute=40),
            id="trash_purge",
            replace_existing=True,
            misfire_grace_time=12 * 3600,
            coalesce=True,
        )
        # Recuperación: al arrancar (en segundo plano: no retrasa el arranque) y cada hora, copia si la última automática
        # tiene más de 24 h y purga si hace más de un día
        scheduler.add_job(
            _catch_up,
            IntervalTrigger(hours=1),
            id="catch_up",
            next_run_time=datetime.now(),
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        scheduler.start()
    yield
    log.info("Apagando Segundo Cerebro...")
    if scheduler.running:
        scheduler.shutdown()


app = FastAPI(title="Digital Brain API", lifespan=lifespan)

STATIC_DIR = str(config.PROJECT_ROOT / "static")
UPLOADS_DIR = str(config.UPLOADS_DIR)
os.makedirs(UPLOADS_DIR, exist_ok=True)
# Las imagenes subidas se montan aparte para que su carpeta sea configurable.
app.mount("/static/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.state.scheduler = scheduler

# El orden importa: FastAPI empareja la primera ruta que encaja
for module_router in (
    pages_router,
    notes_router,
    graph_router,
    vault_router,
    extension_router,
    study_router,
    uploads_router,
    bulk_router,
    contador_router,
    atrasadas_router,  # /api/items/atrasadas, antes que las rutas /api/items/{item_id}
    items_router,
    search_router,
    boards_router,
    boards_api_router,
    backups_router,
    ordering_router,
    versions_router,
    review_router,
    prefs_router,
    links_router,
    calendar_router,
    trash_router,
    reminders_router,
    capture_router,
    overview_router,
    routine_templates_router,
    rutina_rapida_router,
    plantillas_router,
    finance_router,
    rendimiento_router,
    rendimiento_ia_router,
    ia_notas_router,
    ia_flashcards_router,
    dotfiles_router,
    proyecto_router,
    contextos_router,
    universidad_router,
    abrir_router,
    proyectos_router,
):
    app.include_router(module_router)
