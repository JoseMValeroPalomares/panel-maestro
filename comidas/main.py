"""
comidas/main.py

Sub-aplicacion FastAPI de "Comidas": catalogo de ingredientes, comidas con
macros calculados a partir de sus ingredientes, planificador semanal con
generador automatico, lista de la compra agregada, y perfil de usuario con
calculo de objetivos nutricionales (Mifflin-St Jeor).

Aquí solo se crea la app, se arranca y se incluyen los routers (el orden de la lista es el de emparejado):
`ingredientes`, `platos`, `compra`, `plan` (con el generador en `generador.py`), `perfil`, la página, `bulk`
(gestión masiva) y `planner` (franjas, plantillas, registro corporal). Utilidades comunes en `core.py`; nada importa
de este módulo. El modelo de nutrición y del generador está explicado en `generador.py`.

Se monta en el proceso raiz con: app.mount("/comidas", app)
"""

import contextlib
import os
import sys
import types

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from core import config
from core.templating import render

from . import compra, core, generador, ingredientes, perfil, plan, platos, rapido
from .bulk import router as bulk_router
from .database import init_db
from .planner import router as planner_router

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not config.DISABLE_SCHEDULER:
        import threading

        threading.Thread(target=platos.backfill_meal_images, name="meal-images", daemon=True).start()
    yield


app = FastAPI(title="Comidas", lifespan=lifespan)

app.include_router(rapido.router)  # /api/meals/rapido y /api/ingredients/rapido, antes que las rutas con {id}
app.include_router(ingredientes.router)
app.include_router(platos.router)
app.include_router(compra.router)
app.include_router(plan.router)
app.include_router(perfil.router)


@app.get("/")
def comidas_page(request: Request):
    return render(request, "comidas.html", "comidas", "Comidas")


# Gestión masiva y planificación ampliada
app.include_router(bulk_router)
app.include_router(planner_router)

# IMPORTANTE: al final, igual que en estudio/main.py
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


# ─────────────────────────────────────────────
# Compatibilidad: nombres que antes vivían aquí (tests y scripts los usan como `comidas.main.X`).
# Asignar uno (p. ej. monkeypatch en un test) lo cambia también en su módulo de verdad, que es el que
# lo usa; si no, el parche no tendría efecto.
# ─────────────────────────────────────────────
_ORIGEN = {
    nombre: modulo
    for modulo, nombres in (
        (core, ("DIAS_SEMANA", "MealIngredientIn", "PlanSlotAdd", "_slot_id", "_suggest_gramos_recomendados")),
        (generador, ("_ajustar_raciones_dia", "_build_meal_catalog", "_score_candidate")),
        (plan, ("_plan_state", "add_plato_to_slot")),
    )
    for nombre in nombres
}
globals().update({nombre: getattr(modulo, nombre) for nombre, modulo in _ORIGEN.items()})


class _Reexportador(types.ModuleType):
    def __setattr__(self, nombre, valor):
        if nombre in _ORIGEN:
            setattr(_ORIGEN[nombre], nombre, valor)
        super().__setattr__(nombre, valor)


sys.modules[__name__].__class__ = _Reexportador
