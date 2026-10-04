"""FitStudio Express — servidor FastAPI, endpoints REST y renderizado Jinja2."""
import os
import re
import secrets
import uuid
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

import models
import nutrition
import schemas
from database import Base, engine, get_db

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
VIDEO_DIR = UPLOAD_DIR / "videos"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "fitstudio")  # ¡cámbiala en producción!
TZ = ZoneInfo(os.getenv("TZ_NAME", "America/Ciudad_Juarez"))

MAX_PHOTO = 10 * 1024 * 1024
MAX_VIDEO = 60 * 1024 * 1024
IMAGE_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic"}
VIDEO_EXT = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"}

DAYS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
DAY_LABELS = dict(zip(DAYS, ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]))
DAY_ALIASES = dict(zip(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"], DAYS))
DAY_ALIASES.update({"miércoles": "miercoles", "sábado": "sabado"})
MEAL_TYPES = ["Desayuno", "Almuerzo", "Cena", "Snack"]

Base.metadata.create_all(bind=engine)


def migrate():
    """Agrega el código de enlace a bases creadas con la versión anterior."""
    meal_cols = {c["name"] for c in inspect(engine).get_columns("meal_logs")}
    new_cols = {"description": "VARCHAR(120)", "calories": "INTEGER", "protein_g": "INTEGER",
                "carbs_g": "INTEGER", "fat_g": "INTEGER"}
    with engine.begin() as conn:
        for col, kind in new_cols.items():
            if col not in meal_cols:
                conn.execute(text(f"ALTER TABLE meal_logs ADD COLUMN {col} {kind}"))
    if "token" in {c["name"] for c in inspect(engine).get_columns("clients")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE clients ADD COLUMN token VARCHAR(32)"))
        for (cid,) in conn.execute(text("SELECT id FROM clients")).all():
            conn.execute(text("UPDATE clients SET token = :t WHERE id = :i"), {"t": models.new_token(), "i": cid})
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_clients_token ON clients (token)"))


migrate()

app = FastAPI(title="FitStudio Express")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
security = HTTPBasic()


# ---------- utilidades ----------
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
    return re.sub(r"\D", "", phone or "")


def get_setting(db: Session, key: str, default: str = "") -> str:
    s = db.get(models.Setting, key)
    return s.value if s else default


def client_by_token(db: Session, token: str | None) -> models.Client | None:
    if not token:
        return None
    return db.scalar(select(models.Client).where(models.Client.token == token))


def meal_dict(m: models.MealLog) -> dict:
    return {"type": m.meal_type, "url": "/" + m.photo_path, "time": m.created_at.strftime("%H:%M"),
            "desc": m.description, "kcal": m.calories, "p": m.protein_g, "c": m.carbs_g, "f": m.fat_g}


def require_admin(credentials: HTTPBasicCredentials = Depends(security)):
    ok = secrets.compare_digest(credentials.username.encode(), ADMIN_USER.encode()) and \
        secrets.compare_digest(credentials.password.encode(), ADMIN_PASSWORD.encode())
    if not ok:
        raise HTTPException(401, "Credenciales incorrectas", headers={"WWW-Authenticate": "Basic"})


async def save_upload(file: UploadFile, allowed: dict, dest: Path, max_bytes: int) -> str:
    ext = allowed.get((file.content_type or "").lower())
    if not ext:
        raise HTTPException(415, "Tipo de archivo no permitido")
    name = f"{uuid.uuid4().hex}{ext}"
    size = 0
    target = dest / name
    with target.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                out.close()
                target.unlink(missing_ok=True)
                raise HTTPException(413, "El archivo es demasiado grande")
            out.write(chunk)
    if size == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(400, "Archivo vacío")
    return name


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


# ---------- vista cliente ----------
@app.get("/app", response_class=HTMLResponse)
def client_view(request: Request, client_id: str | None = None, day: str | None = None,
                db: Session = Depends(get_db)):
    client = client_by_token(db, client_id)
    ctx = {"client": client, "day": None, "day_label": "", "days": DAY_LABELS, "exercises": [],
           "meals": [], "meal_types": MEAL_TYPES, "trainer_phone": "", "trainer_name": ""}
    if client:
        d = normalize_day(day)
        workouts = db.scalars(select(models.Workout).where(
            models.Workout.client_id == client.id, models.Workout.day == d).order_by(models.Workout.id)).all()
        done = dict(db.execute(
            select(models.WorkoutLog.workout_id, func.count()).where(
                models.WorkoutLog.client_id == client.id, models.WorkoutLog.created_at >= today_start()
            ).group_by(models.WorkoutLog.workout_id)).all())
        meals = db.scalars(select(models.MealLog).where(
            models.MealLog.client_id == client.id, models.MealLog.created_at >= today_start()
        ).order_by(models.MealLog.created_at.desc())).all()
        ctx.update(
            day=d, day_label=DAY_LABELS[d],
            exercises=[{"id": w.id, "name": w.exercise_name, "video": w.video_url, "sets": w.sets,
                        "reps": w.reps, "done": min(done.get(w.id, 0), w.sets)} for w in workouts],
            meals=[meal_dict(m) for m in meals],
            trainer_phone=get_setting(db, "trainer_phone"),
            trainer_name=get_setting(db, "trainer_name", "tu entrenador"),
        )
    return templates.TemplateResponse(request, "client.html", ctx,
                                      status_code=200 if client or not client_id else 404)


# ---------- API ----------
@app.post("/api/logs/workout", response_model=schemas.WorkoutLogOut)
def log_workout(payload: schemas.WorkoutLogIn, db: Session = Depends(get_db)):
    client = client_by_token(db, payload.client_id)
    workout = db.get(models.Workout, payload.workout_id)
    if not client or not workout or workout.client_id != client.id:
        raise HTTPException(404, "Ejercicio no encontrado")
    done = db.scalar(select(func.count()).select_from(models.WorkoutLog).where(
        models.WorkoutLog.workout_id == workout.id, models.WorkoutLog.created_at >= today_start())) or 0
    if done >= workout.sets:
        raise HTTPException(409, "Ya completaste todas las series de hoy")
    db.add(models.WorkoutLog(client_id=workout.client_id, workout_id=workout.id, set_number=done + 1,
                             weight=payload.weight, created_at=now()))
    db.commit()
    return schemas.WorkoutLogOut(set_number=done + 1, sets_total=workout.sets, done=done + 1 >= workout.sets)


@app.post("/api/logs/meal", response_model=schemas.MealLogOut)
async def log_meal(client_id: str = Form(...), meal_type: str = Form(...), photo: UploadFile = File(...),
                   db: Session = Depends(get_db)):
    client = client_by_token(db, client_id)
    if not client:
        raise HTTPException(404, "Cliente no encontrado")
    if meal_type not in MEAL_TYPES:
        raise HTTPException(422, "Tipo de comida inválido")
    name = await save_upload(photo, IMAGE_EXT, UPLOAD_DIR, MAX_PHOTO)
    est = await run_in_threadpool(nutrition.estimate, UPLOAD_DIR / name, meal_type) or {}
    log = models.MealLog(client_id=client.id, meal_type=meal_type,
                         photo_path=f"static/uploads/{name}", created_at=now(), **est)
    db.add(log)
    db.commit()
    return schemas.MealLogOut(id=log.id, meal_type=log.meal_type, photo_url="/" + log.photo_path,
                              created_at=log.created_at, **est)


# ---------- vista admin ----------
@app.get("/admin", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def admin_view(request: Request, client_id: int | None = None, db: Session = Depends(get_db)):
    clients = db.scalars(select(models.Client).order_by(models.Client.name)).all()
    selected = db.get(models.Client, client_id) if client_id else (clients[0] if clients else None)
    routine, meals, logs, kcal_days = {}, [], [], {}
    if selected:
        for w in sorted(selected.workouts, key=lambda w: (DAYS.index(w.day), w.id)):
            routine.setdefault(w.day, []).append(w)
        meals = db.scalars(select(models.MealLog).where(models.MealLog.client_id == selected.id)
                           .order_by(models.MealLog.created_at.desc()).limit(60)).all()
        for m in meals:
            if m.calories is not None:
                key = m.created_at.strftime("%d/%m")
                kcal_days[key] = kcal_days.get(key, 0) + m.calories
        logs = db.scalars(select(models.WorkoutLog).where(models.WorkoutLog.client_id == selected.id)
                          .order_by(models.WorkoutLog.created_at.desc()).limit(40)).all()
    return templates.TemplateResponse(request, "admin.html", {
        "clients": clients, "selected": selected, "routine": routine, "meals": meals, "logs": logs,
        "days": DAY_LABELS, "base_url": str(request.base_url).rstrip("/"),
        "trainer_phone": get_setting(db, "trainer_phone"), "trainer_name": get_setting(db, "trainer_name"),
        "default_password": ADMIN_PASSWORD == "fitstudio",
        "kcal_days": kcal_days, "ai_enabled": nutrition.enabled(),
    })


def back(client_id: int | None = None):
    return RedirectResponse(f"/admin?client_id={client_id}" if client_id else "/admin", status_code=303)


@app.post("/admin/settings", dependencies=[Depends(require_admin)])
def save_settings(trainer_name: str = Form(""), trainer_phone: str = Form(""), db: Session = Depends(get_db)):
    for k, v in {"trainer_name": trainer_name.strip(), "trainer_phone": clean_phone(trainer_phone)}.items():
        db.merge(models.Setting(key=k, value=v))
    db.commit()
    return back()


@app.post("/admin/clients", dependencies=[Depends(require_admin)])
def create_client(name: str = Form(...), phone: str = Form(...), db: Session = Depends(get_db)):
    c = models.Client(name=name.strip(), phone=clean_phone(phone))
    db.add(c)
    db.commit()
    return back(c.id)


@app.post("/admin/clients/{client_id}/delete", dependencies=[Depends(require_admin)])
def delete_client(client_id: int, db: Session = Depends(get_db)):
    c = db.get(models.Client, client_id)
    if c:
        for m in c.meal_logs:
            (BASE_DIR / m.photo_path).unlink(missing_ok=True)
        db.delete(c)
        db.commit()
    return back()


@app.post("/admin/workouts", dependencies=[Depends(require_admin)])
async def create_workout(client_id: int = Form(...), day: str = Form(...), exercise_name: str = Form(...),
                         sets: int = Form(3), reps: int = Form(10), video_url: str = Form(""),
                         video_file: UploadFile | None = File(None), db: Session = Depends(get_db)):
    if not db.get(models.Client, client_id) or day not in DAYS:
        raise HTTPException(404, "Cliente o día inválido")
    url = video_url.strip()
    if url and not re.match(r"^(https?://|/static/)", url):
        raise HTTPException(422, "El enlace del video debe empezar con http(s)://")
    if video_file is not None and video_file.filename:
        url = "/static/uploads/videos/" + await save_upload(video_file, VIDEO_EXT, VIDEO_DIR, MAX_VIDEO)
    db.add(models.Workout(client_id=client_id, day=day, exercise_name=exercise_name.strip(), video_url=url,
                          sets=max(1, min(sets, 20)), reps=max(1, min(reps, 200))))
    db.commit()
    return back(client_id)


@app.post("/admin/workouts/{workout_id}/delete", dependencies=[Depends(require_admin)])
def delete_workout(workout_id: int, db: Session = Depends(get_db)):
    w = db.get(models.Workout, workout_id)
    cid = w.client_id if w else None
    if w:
        db.delete(w)
        db.commit()
    return back(cid)


@app.post("/admin/meals/{meal_id}/delete", dependencies=[Depends(require_admin)])
def delete_meal(meal_id: int, db: Session = Depends(get_db)):
    m = db.get(models.MealLog, meal_id)
    cid = m.client_id if m else None
    if m:
        (BASE_DIR / m.photo_path).unlink(missing_ok=True)
        db.delete(m)
        db.commit()
    return back(cid)
