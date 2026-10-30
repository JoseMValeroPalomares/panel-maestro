"""
API de las copias de seguridad (/api/backups): lista, estado, copia ahora, detalle, descarga, restaurar y
borrar. La lógica está en app/backup.py; la página /backups, en app/main.py.
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import backup
from app.indexer import sync_notes_to_db

router = APIRouter(prefix="/api/backups")


class RestoreRequest(BaseModel):
    parts: list[str] = Field(default_factory=lambda: list(backup.PARTS), max_length=len(backup.PARTS))
    confirm: str = Field(max_length=40)


def _backup_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except backup.BackupError as e:
        raise HTTPException(status_code=404 if "No existe" in str(e) else 422, detail=str(e))


@router.get("")
def get_backups():
    return backup.list_backups()


@router.get("/status")
def get_backup_status(request: Request):
    scheduler = request.app.state.scheduler
    job = scheduler.get_job("daily_backup") if scheduler.running else None
    next_run = job.next_run_time.timestamp() if job and job.next_run_time else None
    return backup.status(next_run=next_run)


@router.post("/run")
def trigger_backup():
    info = _backup_call(backup.create_backup, "manual")
    return {"status": "success", "backup": info}


@router.get("/{name}")
def get_backup_detail(name: str):
    return {"filename": name, "manifest": _backup_call(backup.read_manifest, name)}


@router.get("/{name}/download")
def download_backup(name: str):
    path = _backup_call(backup.backup_path, name)
    return FileResponse(path, media_type="application/zip", filename=name)


@router.post("/{name}/restore")
def restore_backup(name: str, data: RestoreRequest):
    if data.confirm != "RESTAURAR":
        raise HTTPException(status_code=422, detail="Escribe RESTAURAR para confirmar")
    result = _backup_call(backup.restore_backup, name, data.parts)
    sync_notes_to_db()
    return {"status": "success", **result}


@router.delete("/{name}")
def delete_backup(name: str):
    _backup_call(backup.delete_backup, name)
    return {"status": "success"}
