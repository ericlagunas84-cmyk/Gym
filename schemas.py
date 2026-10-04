"""Validaciones Pydantic para los endpoints API."""
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


class MealUpdateIn(BaseModel):
    client_id: str
    description: str = Field(default="", max_length=200)
    calories: int = Field(ge=0, le=5000)
    protein_g: int = Field(default=0, ge=0, le=500)
    carbs_g: int = Field(default=0, ge=0, le=800)
    fat_g: int = Field(default=0, ge=0, le=500)


class MealReestimateIn(BaseModel):
    client_id: str
    note: str = Field(min_length=2, max_length=200)
