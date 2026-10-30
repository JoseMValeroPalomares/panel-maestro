"""Estudio: repaso de flashcards (SM-2), racha de días estudiados y salud del cerebro."""
import time
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.database import get_db
from app.notes_core import today_str

router = APIRouter()


class ReviewInput(BaseModel):
    quality: int = Field(ge=0, le=5)  # 0-5, calificación SM-2


# ─────────────────────────────────────────────
# API de Flashcards (SM-2)
# ─────────────────────────────────────────────

def sm2_update(quality: int, repetitions: int, ease_factor: float, interval: float):
    """Algoritmo SM-2 clásico de SuperMemo. quality va de 0 (fallo total) a
    5 (perfecto). Devuelve (repetitions, ease_factor, interval_days) nuevos."""
    if quality < 3:
        repetitions = 0
        interval = 1
    else:
        if repetitions == 0:
            interval = 1
        elif repetitions == 1:
            interval = 6
        else:
            interval = round(interval * ease_factor)
        repetitions += 1

    ease_factor = ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease_factor = max(ease_factor, 1.3)
    return repetitions, ease_factor, interval


@router.get("/api/flashcards/due")
def get_due_flashcards(limit: int = 20):
    with get_db() as conn:
        rows = conn.execute('''
            SELECT f.*, n.title as note_title FROM flashcards f
            JOIN notes n ON n.id = f.note_id
            WHERE f.next_review <= ? ORDER BY f.next_review ASC LIMIT ?
        ''', (time.time(), limit)).fetchall()
    return {"cards": [dict(r) for r in rows]}


@router.get("/api/flashcards/stats")
def get_flashcard_stats():
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) as n FROM flashcards").fetchone()['n']
        due = conn.execute("SELECT COUNT(*) as n FROM flashcards WHERE next_review <= ?", (time.time(),)).fetchone()['n']
    return {"total": total, "due": due}


@router.post("/api/flashcards/{card_id}/review")
def review_flashcard(card_id: int, data: ReviewInput):
    with get_db() as conn:
        card = conn.execute("SELECT * FROM flashcards WHERE id=?", (card_id,)).fetchone()
        if not card:
            return JSONResponse(status_code=404, content={"error": "Tarjeta no encontrada"})
        quality = max(0, min(5, data.quality))
        reps, ef, interval = sm2_update(quality, card['repetitions'], card['ease_factor'], card['interval_days'])
        next_review = time.time() + interval * 86400
        conn.execute('''
            UPDATE flashcards SET repetitions=?, ease_factor=?, interval_days=?, next_review=? WHERE id=?
        ''', (reps, ef, interval, next_review, card_id))
        conn.commit()
    register_study_day()
    return {"status": "success", "next_review_in_days": interval}


# ─────────────────────────────────────────────
# Racha de estudio
# ─────────────────────────────────────────────

def register_study_day():
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO study_days (day) VALUES (?)", (today_str(),))
        conn.commit()


@router.get("/api/streak")
def get_streak():
    with get_db() as conn:
        rows = conn.execute("SELECT day FROM study_days ORDER BY day DESC").fetchall()
    days = {r['day'] for r in rows}
    streak = 0
    cursor_date = datetime.now().date()
    while cursor_date.strftime('%Y-%m-%d') in days:
        streak += 1
        cursor_date = cursor_date.fromordinal(cursor_date.toordinal() - 1)
    return {"streak": streak, "studied_today": today_str() in days, "total_days": len(days)}


# ─────────────────────────────────────────────
# Panel de salud del cerebro
# ─────────────────────────────────────────────

@router.get("/api/brain-health")
def brain_health():
    with get_db() as conn:
        orphans = conn.execute('''
            SELECT id, title FROM notes n
            WHERE NOT EXISTS (SELECT 1 FROM graph_edges e WHERE e.source=n.id OR e.target=n.id)
            ORDER BY title
        ''').fetchall()
        stale = conn.execute('''
            SELECT id, title, last_modified FROM notes
            WHERE last_modified < ? ORDER BY last_modified ASC LIMIT 10
        ''', (time.time() - 60 * 86400,)).fetchall()
        pending_by_category = conn.execute('''
            SELECT category, COUNT(*) as n FROM notes
            WHERE status='por-escribir' GROUP BY category ORDER BY n DESC
        ''').fetchall()
        total_notes = conn.execute("SELECT COUNT(*) as n FROM notes").fetchone()['n']
    return {
        "orphans": [dict(r) for r in orphans],
        "stale": [dict(r) for r in stale],
        "pending_by_category": [dict(r) for r in pending_by_category],
        "total_notes": total_notes,
    }
