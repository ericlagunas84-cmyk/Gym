"""Inicio de sesión de entrenadores: contraseñas con PBKDF2 y sesión en cookie firmada."""
import hashlib
import hmac
import secrets
import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

import models
from database import get_db

ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(check.hex(), digest)
    except (ValueError, AttributeError):
        return False


class NotAuthenticated(Exception):
    pass


def current_trainer(request: Request, db: Session = Depends(get_db)) -> models.Trainer:
    tid = request.session.get("tid")
    trainer = db.get(models.Trainer, tid) if tid else None
    if not trainer or not trainer.active:
        request.session.clear()
        raise NotAuthenticated()
    return trainer


def require_owner(trainer: models.Trainer = Depends(current_trainer)) -> models.Trainer:
    if not trainer.is_owner:
        raise HTTPException(403, "Solo el administrador puede gestionar entrenadores")
    return trainer


# Freno simple a intentos de contraseña: 8 fallos por IP cada 10 minutos.
_fails: dict[str, list[float]] = {}


def too_many_attempts(ip: str) -> bool:
    recent = [t for t in _fails.get(ip, []) if time.time() - t < 600]
    _fails[ip] = recent
    return len(recent) >= 8


def register_failure(ip: str) -> None:
    _fails.setdefault(ip, []).append(time.time())
