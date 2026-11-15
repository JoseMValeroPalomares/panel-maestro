"""comidas/perfil.py — perfil de usuario y objetivos nutricionales (Mifflin-St Jeor, en nutrition.py)."""

from fastapi import APIRouter

from . import nutrition as nu
from .core import UserProfileIn, calculate_targets
from .database import get_db

router = APIRouter()


@router.get("/api/profile")
def get_profile():
    with get_db() as conn:
        row = conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone()
    profile = dict(row)
    profile["objetivo"] = nu.normalizar_objetivo(profile["objetivo"])
    profile["targets"] = calculate_targets(profile)
    profile["niveles_actividad"] = {str(k): v for k, v in nu.NIVELES_ACTIVIDAD.items()}
    profile["objetivos"] = nu.OBJETIVOS
    return profile


@router.patch("/api/profile")
def update_profile(data: UserProfileIn):
    with get_db() as conn:
        objetivo = nu.normalizar_objetivo(data.objetivo)
        conn.execute(
            """
            UPDATE user_profile SET edad=?, peso_kg=?, altura_cm=?, sexo=?, nivel_actividad=?, objetivo=?, proteina_g_kg=?,
                   grasa_pct=?, ajuste_pct=?
            WHERE id=1
        """,
            (
                data.edad,
                data.peso_kg,
                data.altura_cm,
                data.sexo,
                data.nivel_actividad,
                objetivo,
                data.proteina_g_kg,
                data.grasa_pct if data.grasa_pct is not None else nu.GRASA_PCT_DEFECTO,
                data.ajuste_pct,
            ),
        )
    return {"status": "success", "targets": calculate_targets({**data.model_dump(), "objetivo": objetivo})}
