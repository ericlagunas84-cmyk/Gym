"""FitStudio Express — servidor FastAPI: vista del cliente, API y arranque."""
import os
import secrets
import time

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

import admin
import auth
import models
import nutrition
import schemas
import storage
from core import (BASE_DIR, DAY_LABELS, MEAL_TYPES, body_dict, brand, exercise_progress, meal_dict, normalize_day,
                  now, parse_float, templates, today_start)
from database import Base, SessionLocal, engine, get_db

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "fitstudio")  # ¡cámbiala en producción!
MAX_MEALS_PER_DAY = 20  # tope por cliente para acotar el costo de la IA


# ---------- arranque: tablas, migración y cuenta inicial ----------
def migrate():
    """Agrega columnas nuevas a bases creadas con versiones anteriores y crea la cuenta inicial."""
    Base.metadata.create_all(bind=engine)
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing:
                    kind = col.type.compile(engine.dialect)
                    conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {kind}"))
    with SessionLocal() as db:
        owner = db.scalar(select(models.Trainer).where(models.Trainer.is_owner.is_(True)))
        if not owner:
            old = {s.key: s.value for s in db.scalars(select(models.Setting)).all()}
            owner = models.Trainer(username=ADMIN_USER, password_hash=auth.hash_password(ADMIN_PASSWORD),
                                   name=old.get("trainer_name", ""), phone=old.get("trainer_phone", ""),
                                   is_owner=True, active=True, created_at=now())
            db.add(owner)
            db.commit()
        db.execute(text("UPDATE clients SET trainer_id = :o WHERE trainer_id IS NULL"), {"o": owner.id})
        for (cid,) in db.execute(text("SELECT id FROM clients WHERE token IS NULL")).all():
            db.execute(text("UPDATE clients SET token = :t WHERE id = :i"), {"t": models.new_token(), "i": cid})
        db.execute(text("UPDATE workouts SET rest_seconds = 60 WHERE rest_seconds IS NULL"))
        db.execute(text("UPDATE meal_logs SET photo_path = '/media/' || substr(photo_path, 16) "
                        "WHERE photo_path LIKE 'static/uploads/%'"))
        db.execute(text("UPDATE workouts SET video_url = '/media/' || substr(video_url, 17) "
                        "WHERE video_url LIKE '/static/uploads/%'"))
        db.commit()


def session_secret() -> str:
    if os.getenv("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    with SessionLocal() as db:
        s = db.get(models.Setting, "secret_key")
        if not s:
            s = models.Setting(key="secret_key", value=secrets.token_urlsafe(32))
            db.add(s)
            db.commit()
        return s.value


migrate()

app = FastAPI(title="FitStudio Express")
app.add_middleware(SessionMiddleware, secret_key=session_secret(), same_site="lax", max_age=60 * 60 * 24 * 30,
                   https_only=os.getenv("COOKIE_SECURE") == "1")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/media", StaticFiles(directory=storage.UPLOAD_DIR), name="media")
app.include_router(admin.router)


@app.exception_handler(auth.NotAuthenticated)
def not_authenticated(request: Request, exc: auth.NotAuthenticated):
    return RedirectResponse("/login", status_code=303)


# ---------- PWA ----------
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/app")


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(BASE_DIR / "static" / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(BASE_DIR / "static" / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


# ---------- inicio de sesión ----------
@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if request.session.get("tid"):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "?"
    if auth.too_many_attempts(ip):
        return templates.TemplateResponse(request, "login.html",
                                          {"error": "Demasiados intentos. Espera 10 minutos."}, status_code=429)
    trainer = db.scalar(select(models.Trainer).where(models.Trainer.username == username.strip().lower()))
    if not trainer or not trainer.active or not auth.verify_password(password, trainer.password_hash):
        auth.register_failure(ip)
        return templates.TemplateResponse(request, "login.html",
                                          {"error": "Usuario o contraseña incorrectos."}, status_code=401)
    request.session["tid"] = trainer.id
    request.session["weak"] = password == "fitstudio"
    return RedirectResponse("/admin", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------- vista cliente ----------
def client_by_token(db: Session, token: str | None) -> models.Client | None:
    if not token:
        return None
    client = db.scalar(select(models.Client).where(models.Client.token == token))
    return client if client and client.trainer and client.trainer.active else None


@app.get("/app", response_class=HTMLResponse)
def client_view(request: Request, client_id: str | None = None, day: str | None = None,
                db: Session = Depends(get_db)):
    client = client_by_token(db, client_id)
    if not client:
        return templates.TemplateResponse(request, "client.html", {"client": None, "brand": brand(None)},
                                          status_code=404 if client_id else 200)
    d = normalize_day(day)
    today = today_start()
    workouts = db.scalars(select(models.Workout).where(
        models.Workout.client_id == client.id, models.Workout.day == d,
        models.Workout.archived.is_not(True)).order_by(models.Workout.id)).all()
    done = dict(db.execute(
        select(models.WorkoutLog.workout_id, func.count()).where(
            models.WorkoutLog.client_id == client.id, models.WorkoutLog.created_at >= today
        ).group_by(models.WorkoutLog.workout_id)).all())
    progress = exercise_progress(db, client.id)
    today_iso = today.date().isoformat()
    last = {}  # última sesión anterior a hoy, por nombre de ejercicio
    for p in progress:
        prev = [pt for pt in p["points"] if pt["date"] < today_iso and pt["w"] > 0]
        if prev:
            last[p["name"]] = prev[-1]
    meals = db.scalars(select(models.MealLog).where(
        models.MealLog.client_id == client.id, models.MealLog.created_at >= today
    ).order_by(models.MealLog.created_at.desc())).all()
    body = db.scalars(select(models.BodyLog).where(models.BodyLog.client_id == client.id)
                      .order_by(models.BodyLog.created_at.desc()).limit(30)).all()
    message = db.scalar(select(models.Message).where(models.Message.client_id == client.id)
                        .order_by(models.Message.created_at.desc()))
    trainer = client.trainer
    data = {
        "clientId": client.token, "clientName": client.name, "dayLabel": DAY_LABELS[d],
        "today": now().strftime("%d/%m"),
        "exercises": [{"id": w.id, "name": w.exercise_name, "video": w.video_url, "sets": w.sets, "reps": w.reps,
                       "rest": w.rest_seconds or 0, "note": w.note, "done": min(done.get(w.id, 0), w.sets),
                       "last": last.get(w.exercise_name)} for w in workouts],
        "meals": [meal_dict(m) for m in meals], "mealType": MEAL_TYPES[0],
        "kcalGoal": client.kcal_goal, "proteinGoal": client.protein_goal,
        "progress": progress, "body": [body_dict(b) for b in body],
        "trainerPhone": trainer.phone, "aiEnabled": nutrition.enabled(),
    }
    return templates.TemplateResponse(request, "client.html", {
        "client": client, "day": d, "day_label": DAY_LABELS[d], "days": DAY_LABELS, "meal_types": MEAL_TYPES,
        "brand": brand(trainer), "data": data,
        "message": {"text": message.text, "date": message.created_at.strftime("%d/%m")} if message else None,
    })


# ---------- API del cliente ----------
@app.post("/api/logs/workout", response_model=schemas.WorkoutLogOut)
def log_workout(payload: schemas.WorkoutLogIn, db: Session = Depends(get_db)):
    client = client_by_token(db, payload.client_id)
    workout = db.get(models.Workout, payload.workout_id)
    if not client or not workout or workout.client_id != client.id or workout.archived:
        raise HTTPException(404, "Ejercicio no encontrado")
    done = db.scalar(select(func.count()).select_from(models.WorkoutLog).where(
        models.WorkoutLog.workout_id == workout.id, models.WorkoutLog.created_at >= today_start())) or 0
    if done >= workout.sets:
        raise HTTPException(409, "Ya completaste todas las series de hoy")
    db.add(models.WorkoutLog(client_id=client.id, workout_id=workout.id, set_number=done + 1,
                             weight=payload.weight, created_at=now()))
    db.commit()
    return schemas.WorkoutLogOut(set_number=done + 1, sets_total=workout.sets, done=done + 1 >= workout.sets)


@app.post("/api/logs/meal")
async def log_meal(client_id: str = Form(...), meal_type: str = Form(...), photo: UploadFile = File(...),
                   db: Session = Depends(get_db)):
    client = client_by_token(db, client_id)
    if not client:
        raise HTTPException(404, "Cliente no encontrado")
    if meal_type not in MEAL_TYPES:
        raise HTTPException(422, "Tipo de comida inválido")
    count = db.scalar(select(func.count()).select_from(models.MealLog).where(
        models.MealLog.client_id == client.id, models.MealLog.created_at >= today_start())) or 0
    if count >= MAX_MEALS_PER_DAY:
        raise HTTPException(429, "Llegaste al máximo de fotos por hoy")
    url, data, mtype = await storage.save(photo, storage.IMAGES, "meals", storage.MAX_PHOTO)
    est = await run_in_threadpool(nutrition.estimate, data, mtype, meal_type) or {}
    log = models.MealLog(client_id=client.id, meal_type=meal_type, photo_path=url, created_at=now(), **est)
    db.add(log)
    db.commit()
    return meal_dict(log)


def owned_meal(db: Session, token: str, meal_id: int) -> models.MealLog:
    client = client_by_token(db, token)
    meal = db.get(models.MealLog, meal_id)
    if not client or not meal or meal.client_id != client.id:
        raise HTTPException(404, "Comida no encontrada")
    return meal


@app.post("/api/logs/meal/{meal_id}/update")
def update_meal(meal_id: int, payload: schemas.MealUpdateIn, db: Session = Depends(get_db)):
    """El cliente corrige a mano la estimación."""
    meal = owned_meal(db, payload.client_id, meal_id)
    meal.description = payload.description.strip() or meal.description
    meal.calories, meal.protein_g = payload.calories, payload.protein_g
    meal.carbs_g, meal.fat_g = payload.carbs_g, payload.fat_g
    meal.edited = True
    db.commit()
    return meal_dict(meal)


_reestimates: dict[int, int] = {}


@app.post("/api/logs/meal/{meal_id}/reestimate")
async def reestimate_meal(meal_id: int, payload: schemas.MealReestimateIn, db: Session = Depends(get_db)):
    """Recalcula con IA tomando en cuenta la aclaración del cliente."""
    meal = owned_meal(db, payload.client_id, meal_id)
    if not nutrition.enabled():
        raise HTTPException(503, "El recálculo con IA no está disponible. Corrige los valores a mano.")
    if _reestimates.get(meal.id, 0) >= 5:
        raise HTTPException(429, "Ya recalculaste esta comida varias veces. Corrige los valores a mano.")
    _reestimates[meal.id] = _reestimates.get(meal.id, 0) + 1
    data = await run_in_threadpool(storage.read, meal.photo_path)
    est = await run_in_threadpool(nutrition.estimate, data, storage.media_type(meal.photo_path),
                                  meal.meal_type, payload.note.strip())
    if not est:
        raise HTTPException(502, "No se pudo recalcular. Corrige los valores a mano.")
    for key, value in est.items():
        setattr(meal, key, value)
    meal.edited = True
    db.commit()
    return meal_dict(meal)


@app.post("/api/logs/body")
async def log_body(client_id: str = Form(...), weight_kg: str = Form(""), waist_cm: str = Form(""),
                   hip_cm: str = Form(""), chest_cm: str = Form(""), note: str = Form(""),
                   photo: UploadFile | None = File(None), db: Session = Depends(get_db)):
    client = client_by_token(db, client_id)
    if not client:
        raise HTTPException(404, "Cliente no encontrado")
    values = {"weight_kg": parse_float(weight_kg, 400), "waist_cm": parse_float(waist_cm, 300),
              "hip_cm": parse_float(hip_cm, 300), "chest_cm": parse_float(chest_cm, 300)}
    has_photo = photo is not None and bool(photo.filename)
    if not has_photo and not any(values.values()):
        raise HTTPException(422, "Captura al menos tu peso, una medida o una foto")
    count = db.scalar(select(func.count()).select_from(models.BodyLog).where(
        models.BodyLog.client_id == client.id, models.BodyLog.created_at >= today_start())) or 0
    if count >= 5:
        raise HTTPException(429, "Ya registraste tu progreso varias veces hoy")
    url = None
    if has_photo:
        url, _, _ = await storage.save(photo, storage.IMAGES, "body", storage.MAX_PHOTO)
    log = models.BodyLog(client_id=client.id, created_at=now(), photo_url=url, note=note.strip()[:200] or None,
                         **values)
    db.add(log)
    db.commit()
    return body_dict(log)
