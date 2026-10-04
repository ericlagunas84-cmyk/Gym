"""Configuración y utilidades compartidas."""
import os
import re
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

import models

BASE_DIR = Path(__file__).parent
TZ = ZoneInfo(os.getenv("TZ_NAME", "America/Ciudad_Juarez"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
DEFAULT_COLOR = "#10b981"

DAYS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
DAY_LABELS = dict(zip(DAYS, ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]))
DAY_ALIASES = dict(zip(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"], DAYS))
DAY_ALIASES.update({"miércoles": "miercoles", "sábado": "sabado"})
MEAL_TYPES = ["Desayuno", "Almuerzo", "Cena", "Snack"]

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals.update(
    FIELD="w-full h-12 rounded-xl bg-slate-900 border border-slate-700 px-3 focus:border-emerald-500 focus:outline-none",
    BTN="h-12 px-5 rounded-xl bg-emerald-500 text-slate-900 font-bold",
    CARD="rounded-2xl bg-slate-800 ring-1 ring-slate-700 p-4",
    DAY_LABELS=DAY_LABELS,
)
templates.env.filters["num"] = lambda v: f"{v:,}" if v is not None else ""
templates.env.filters["g"] = lambda v: f"{v:g}" if v is not None else ""


def now() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)


def today_start() -> datetime:
    return datetime.combine(now().date(), time.min)


def normalize_day(day: str | None) -> str:
    if not day:
        return DAYS[now().weekday()]
    d = day.strip().lower()
    d = DAY_ALIASES.get(d, d)
    return d if d in DAYS else DAYS[now().weekday()]


def clean_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")[:20]


def parse_float(value: str | None, hi: float = 1000) -> float | None:
    try:
        v = float((value or "").strip().replace(",", "."))
    except ValueError:
        return None
    return v if 0 < v <= hi else None


def parse_int(value: str | None, hi: int = 10000) -> int | None:
    v = parse_float(value, hi)
    return round(v) if v is not None else None


def valid_color(color: str | None) -> str:
    return color if re.fullmatch(r"#[0-9a-fA-F]{6}", color or "") else DEFAULT_COLOR


def brand(trainer: models.Trainer | None) -> dict:
    """Variables de marca para la vista del cliente (color, texto legible encima, logo)."""
    color = valid_color(trainer.brand_color if trainer else None)
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    on = "15 23 42" if 0.299 * r + 0.587 * g + 0.114 * b > 140 else "255 255 255"
    return {"rgb": f"{r} {g} {b}", "on": on,
            "name": (trainer.brand_name or trainer.name) if trainer else "",
            "logo": trainer.logo_url if trainer else ""}


def meal_dict(m: models.MealLog) -> dict:
    return {"id": m.id, "type": m.meal_type, "url": m.photo_path, "time": m.created_at.strftime("%H:%M"),
            "desc": m.description, "kcal": m.calories, "p": m.protein_g, "c": m.carbs_g, "f": m.fat_g,
            "edited": bool(m.edited), "comment": m.trainer_comment}


def body_dict(b: models.BodyLog) -> dict:
    return {"id": b.id, "date": b.created_at.strftime("%d/%m/%y"), "weight": b.weight_kg, "waist": b.waist_cm,
            "hip": b.hip_cm, "chest": b.chest_cm, "photo": b.photo_url, "note": b.note}


def exercise_progress(db: Session, client_id: int) -> list[dict]:
    """Peso máximo por sesión de cada ejercicio (por nombre, aunque cambie la rutina)."""
    rows = db.execute(
        select(models.Workout.exercise_name, models.WorkoutLog.created_at, models.WorkoutLog.weight)
        .join(models.Workout, models.WorkoutLog.workout_id == models.Workout.id)
        .where(models.WorkoutLog.client_id == client_id).order_by(models.WorkoutLog.created_at)).all()
    series: dict[str, dict] = {}
    for name, ts, weight in rows:
        days = series.setdefault(name, {})
        days[ts.date()] = max(days.get(ts.date(), 0), weight or 0)
    return [{"name": name, "points": [{"d": d.strftime("%d/%m"), "date": d.isoformat(), "w": w}
                                      for d, w in list(days.items())[-12:]]}
            for name, days in series.items() if any(w > 0 for w in days.values())]
