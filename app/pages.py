"""Las páginas HTML del panel (Cerebro): cada ruta pinta su plantilla con el layout común."""
from fastapi import APIRouter, Request

from app import dotfiles, proyecto
from core.templating import render

router = APIRouter()


@router.get("/")
def read_root(request: Request):
    return render(request, "index.html", "notas", "Notas")


@router.get("/graph")
def read_graph(request: Request):
    return render(request, "graph.html", "grafo", "Grafo")


@router.get("/vault")
def read_vault(request: Request):
    return render(request, "vault.html", "baul", "Baúl")


@router.get("/inbox")
def read_inbox(request: Request):
    return render(request, "inbox.html", "inbox", "Inbox")


@router.get("/tareas")
def read_tasks_page(request: Request):
    return render(request, "tareas.html", "tareas", "Tareas")


@router.get("/hoy")
def read_today_page(request: Request):
    return render(request, "hoy.html", "hoy", "Hoy")


@router.get("/revision")
def read_week_review_page(request: Request):
    return render(request, "revision.html", "revision", "Revisión semanal")


@router.get("/rutinas")
def read_routines_page(request: Request):
    return render(request, "rutinas.html", "rutinas", "Rutinas")


@router.get("/economia")
def read_finance_page(request: Request):
    return render(request, "economia.html", "economia", "Economía")


@router.get("/rendimiento")
def read_performance_page(request: Request):
    return render(request, "rendimiento.html", "rendimiento", "Rendimiento")


@router.get("/calendario")
def read_calendar_page(request: Request):
    return render(request, "calendario.html", "calendario", "Calendario")


@router.get("/papelera")
def read_trash_page(request: Request):
    return render(request, "papelera.html", "papelera", "Papelera")


@router.get("/buscar")
def read_search_page(request: Request):
    return render(request, "buscar.html", "buscar", "Buscar")


@router.get("/repaso")
def read_review_page(request: Request):
    return render(request, "repaso.html", "repaso", "Repaso")


@router.get("/gestion")
def read_gestion(request: Request):
    return render(request, "gestion.html", "gestion", "Gestión")


@router.get("/backups")
def read_backups_page(request: Request):
    return render(request, "backups.html", "backups", "Copias de seguridad",
                  show_dotfiles=dotfiles.is_available(), show_project=proyecto.is_available())
