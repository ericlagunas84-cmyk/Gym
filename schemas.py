"""Validaciones Pydantic para los endpoints API."""
from datetime import datetime

from pydantic import BaseModel, Field


class WorkoutLogIn(BaseModel):
    client_id: str  # código del enlace personal del cliente
    workout_id: int
    weight: float = Field(default=0, ge=0, le=1000)


class WorkoutLogOut(BaseModel):
    ok: bool = True
    set_number: int
    sets_total: int
    done: bool


class MealLogOut(BaseModel):
    ok: bool = True
    id: int
    meal_type: str
    photo_url: str
    created_at: datetime
    description: str | None = None
    calories: int | None = None
    protein_g: int | None = None
    carbs_g: int | None = None
    fat_g: int | None = None
