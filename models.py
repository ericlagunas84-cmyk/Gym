"""Modelos ORM: Clients, Workouts, WorkoutLogs, MealLogs, Settings."""
import secrets
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def new_token() -> str:
    return secrets.token_urlsafe(9)  # 12 caracteres


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20))  # con código de país, solo dígitos
    # Código aleatorio del enlace personal: evita que alguien adivine el enlace de otro cliente.
    token: Mapped[str] = mapped_column(String(32), unique=True, index=True, default=lambda: new_token())

    workouts = relationship("Workout", back_populates="client", cascade="all, delete-orphan")
    meal_logs = relationship("MealLog", back_populates="client", cascade="all, delete-orphan")
    workout_logs = relationship("WorkoutLog", back_populates="client", cascade="all, delete-orphan")


class Workout(Base):
    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    day: Mapped[str] = mapped_column(String(12), index=True)  # lunes..domingo
    exercise_name: Mapped[str] = mapped_column(String(120))
    video_url: Mapped[str] = mapped_column(String(500), default="")
    sets: Mapped[int] = mapped_column(Integer, default=3)
    reps: Mapped[int] = mapped_column(Integer, default=10)

    client = relationship("Client", back_populates="workouts")
    logs = relationship("WorkoutLog", back_populates="workout", cascade="all, delete-orphan")


class WorkoutLog(Base):
    """Cada serie completada por el alumno (POST /api/logs/workout)."""
    __tablename__ = "workout_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("workouts.id"), index=True)
    set_number: Mapped[int] = mapped_column(Integer)
    weight: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    client = relationship("Client", back_populates="workout_logs")
    workout = relationship("Workout", back_populates="logs")


class MealLog(Base):
    __tablename__ = "meal_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    meal_type: Mapped[str] = mapped_column(String(20))  # Desayuno / Almuerzo / Cena
    photo_path: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    # Estimación por IA a partir de la foto (vacío si no se pudo estimar)
    description: Mapped[str | None] = mapped_column(String(120), nullable=True)
    calories: Mapped[int | None] = mapped_column(Integer, nullable=True)
    protein_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    carbs_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fat_g: Mapped[int | None] = mapped_column(Integer, nullable=True)

    client = relationship("Client", back_populates="meal_logs")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), default="")
