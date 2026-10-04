"""Modelos ORM de FitStudio Express."""
import secrets
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def new_token() -> str:
    return secrets.token_urlsafe(9)  # 12 caracteres


class Trainer(Base):
    """Cuenta de entrenador: cada uno ve solo sus clientes."""
    __tablename__ = "trainers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(20), default="")  # WhatsApp para recibir reportes
    brand_name: Mapped[str] = mapped_column(String(60), default="")
    brand_color: Mapped[str] = mapped_column(String(7), default="#10b981")
    logo_url: Mapped[str] = mapped_column(String(500), default="")
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False)  # puede crear entrenadores
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    clients = relationship("Client", back_populates="trainer", cascade="all, delete-orphan")
    exercises = relationship("Exercise", cascade="all, delete-orphan")
    templates = relationship("Template", cascade="all, delete-orphan")


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trainer_id: Mapped[int | None] = mapped_column(ForeignKey("trainers.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20))  # con código de país, solo dígitos
    # Código aleatorio del enlace personal: evita que alguien adivine el enlace de otro cliente.
    token: Mapped[str] = mapped_column(String(32), unique=True, index=True, default=new_token)
    kcal_goal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    protein_goal: Mapped[int | None] = mapped_column(Integer, nullable=True)

    trainer = relationship("Trainer", back_populates="clients")
    workouts = relationship("Workout", back_populates="client", cascade="all, delete-orphan")
    meal_logs = relationship("MealLog", back_populates="client", cascade="all, delete-orphan")
    workout_logs = relationship("WorkoutLog", back_populates="client", cascade="all, delete-orphan")
    body_logs = relationship("BodyLog", back_populates="client", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="client", cascade="all, delete-orphan")


class Exercise(Base):
    """Biblioteca de ejercicios del entrenador (nombre + video reutilizable)."""
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    video_url: Mapped[str] = mapped_column(String(500), default="")


class Template(Base):
    """Rutina guardada que se puede aplicar a cualquier cliente."""
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))

    items = relationship("TemplateItem", cascade="all, delete-orphan", order_by="TemplateItem.id")


class TemplateItem(Base):
    __tablename__ = "template_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"), index=True)
    day: Mapped[str] = mapped_column(String(12))
    exercise_name: Mapped[str] = mapped_column(String(120))
    video_url: Mapped[str] = mapped_column(String(500), default="")
    sets: Mapped[int] = mapped_column(Integer, default=3)
    reps: Mapped[int] = mapped_column(Integer, default=10)
    rest_seconds: Mapped[int] = mapped_column(Integer, default=60)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Workout(Base):
    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    day: Mapped[str] = mapped_column(String(12), index=True)  # lunes..domingo
    exercise_name: Mapped[str] = mapped_column(String(120))
    video_url: Mapped[str] = mapped_column(String(500), default="")
    sets: Mapped[int] = mapped_column(Integer, default=3)
    reps: Mapped[int] = mapped_column(Integer, default=10)
    rest_seconds: Mapped[int | None] = mapped_column(Integer, default=60, nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)  # indicación del entrenador
    # Al quitar un ejercicio se archiva (no se borra) para conservar el historial de pesos.
    archived: Mapped[bool | None] = mapped_column(Boolean, default=False, nullable=True)

    client = relationship("Client", back_populates="workouts")
    logs = relationship("WorkoutLog", back_populates="workout", cascade="all, delete-orphan")


class WorkoutLog(Base):
    """Cada serie completada por el alumno."""
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
    meal_type: Mapped[str] = mapped_column(String(20))
    photo_path: Mapped[str] = mapped_column(String(500))  # URL de la foto (/media/... o Supabase)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    # Estimación por IA (vacío si no se pudo estimar); el cliente puede corregirla.
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    calories: Mapped[int | None] = mapped_column(Integer, nullable=True)
    protein_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    carbs_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fat_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    edited: Mapped[bool | None] = mapped_column(Boolean, default=False, nullable=True)
    trainer_comment: Mapped[str | None] = mapped_column(String(300), nullable=True)

    client = relationship("Client", back_populates="meal_logs")


class BodyLog(Base):
    """Seguimiento corporal: peso, medidas y foto de progreso."""
    __tablename__ = "body_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    waist_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    hip_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    chest_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    client = relationship("Client", back_populates="body_logs")


class Message(Base):
    """Mensaje del entrenador visible para el cliente."""
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    text: Mapped[str] = mapped_column(String(500))

    client = relationship("Client", back_populates="messages")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), default="")
