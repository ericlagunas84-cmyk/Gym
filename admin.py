"""Panel del entrenador: clientes, rutinas, biblioteca, plantillas, resumen, ajustes y entrenadores."""
import re
from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import auth
import models
import nutrition
import storage
from auth import current_trainer, require_owner
from core import (DAYS, PUBLIC_URL, body_dict, clean_phone, exercise_progress, now, parse_int, templates,
                  today_start, valid_color)
from database import get_db

router = APIRouter(prefix="/admin")
TABS = {"rutina", "comidas", "avances", "cuerpo"}


# ---------- utilidades ----------
def render(request: Request, name: str, trainer: models.Trainer, **ctx):
    ctx.update(trainer=trainer, msg=request.query_params.get("msg"), weak=request.session.get("weak"),
               ai_enabled=nutrition.enabled(), remote_storage=storage.remote())
    return templates.TemplateResponse(request, name, ctx)


def go(path: str, msg: str | None = None):
    if msg:
        path += ("&" if "?" in path else "?") + "msg=" + quote(msg)
    return RedirectResponse(path, status_code=303)


def back(client_id: int | None = None, tab: str = "rutina", msg: str | None = None):
    return go(f"/admin?client_id={client_id}&tab={tab}" if client_id else "/admin", msg)


def owned_client(db: Session, trainer: models.Trainer, client_id: int) -> models.Client:
    client = db.get(models.Client, client_id)
    if not client or client.trainer_id != trainer.id:
        raise HTTPException(404, "Cliente no encontrado")
    return client


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))


def check_video_url(url: str) -> str:
    url = url.strip()
    if url and not re.match(r"^(https?://|/media/)", url):
        raise HTTPException(422, "El enlace del video debe empezar con http(s)://")
    return url[:500]


def remember_exercise(db: Session, trainer: models.Trainer, name: str, video_url: str) -> str:
    """Guarda el ejercicio en la biblioteca o reutiliza su video si ya existe. Devuelve el video a usar."""
    existing = db.scalar(select(models.Exercise).where(
        models.Exercise.trainer_id == trainer.id, func.lower(models.Exercise.name) == name.lower()))
    if not existing:
        db.add(models.Exercise(trainer_id=trainer.id, name=name, video_url=video_url))
        return video_url
    if video_url:
        existing.video_url = video_url
    return existing.video_url


# ---------- clientes ----------
@router.get("", response_class=HTMLResponse)
def admin_home(request: Request, client_id: int | None = None, tab: str = "rutina",
               trainer: models.Trainer = Depends(current_trainer), db: Session = Depends(get_db)):
    clients = db.scalars(select(models.Client).where(models.Client.trainer_id == trainer.id)
                         .order_by(models.Client.name)).all()
    selected = owned_client(db, trainer, client_id) if client_id else (clients[0] if clients else None)
    ctx = {"clients": clients, "selected": selected, "tab": tab if tab in TABS else "rutina",
           "base_url": PUBLIC_URL or str(request.base_url).rstrip("/")}
    if selected:
        routine: dict[str, list] = {}
        for w in sorted((w for w in selected.workouts if not w.archived), key=lambda w: (DAYS.index(w.day), w.id)):
            routine.setdefault(w.day, []).append(w)
        meals = db.scalars(select(models.MealLog).where(models.MealLog.client_id == selected.id)
                           .order_by(models.MealLog.created_at.desc()).limit(60)).all()
        days: dict[str, dict] = {}
        for m in meals:
            if m.calories is not None:
                d = days.setdefault(m.created_at.strftime("%d/%m"), {"kcal": 0, "protein": 0})
                d["kcal"] += m.calories
                d["protein"] += m.protein_g or 0
        progress = []
        for p in exercise_progress(db, selected.id):
            pts = [pt for pt in p["points"] if pt["w"] > 0]
            progress.append({"name": p["name"], "first": pts[0]["w"], "last": pts[-1]["w"], "sessions": len(pts),
                             "best": max(pt["w"] for pt in pts)})
        ctx.update(
            routine=routine, meals=meals, meal_days=days, progress=progress,
            logs=db.scalars(select(models.WorkoutLog).where(models.WorkoutLog.client_id == selected.id)
                            .order_by(models.WorkoutLog.created_at.desc()).limit(40)).all(),
            body=[body_dict(b) for b in db.scalars(
                select(models.BodyLog).where(models.BodyLog.client_id == selected.id)
                .order_by(models.BodyLog.created_at.desc()).limit(40)).all()],
            messages=db.scalars(select(models.Message).where(models.Message.client_id == selected.id)
                                .order_by(models.Message.created_at.desc()).limit(10)).all(),
            exercises=db.scalars(select(models.Exercise).where(models.Exercise.trainer_id == trainer.id)
                                 .order_by(models.Exercise.name)).all(),
            templates_list=db.scalars(select(models.Template).where(models.Template.trainer_id == trainer.id)
                                      .order_by(models.Template.name)).all(),
        )
    return render(request, "admin.html", trainer, **ctx)


@router.post("/clients")
def create_client(name: str = Form(...), phone: str = Form(...),
                  trainer: models.Trainer = Depends(current_trainer), db: Session = Depends(get_db)):
    client = models.Client(trainer_id=trainer.id, name=name.strip()[:120], phone=clean_phone(phone))
    db.add(client)
    db.commit()
    return back(client.id)


@router.post("/clients/{client_id}/goals")
def set_goals(client_id: int, kcal_goal: str = Form(""), protein_goal: str = Form(""),
              trainer: models.Trainer = Depends(current_trainer), db: Session = Depends(get_db)):
    client = owned_client(db, trainer, client_id)
    client.kcal_goal, client.protein_goal = parse_int(kcal_goal, 10000), parse_int(protein_goal, 500)
    db.commit()
    return back(client.id, msg="Metas guardadas")


@router.post("/clients/{client_id}/delete")
def delete_client(client_id: int, trainer: models.Trainer = Depends(current_trainer),
                  db: Session = Depends(get_db)):
    client = owned_client(db, trainer, client_id)
    for url in [m.photo_path for m in client.meal_logs] + [b.photo_url for b in client.body_logs]:
        storage.delete(url)
    db.delete(client)
    db.commit()
    return back()


@router.post("/clients/{client_id}/message")
def send_message(client_id: int, text: str = Form(...), trainer: models.Trainer = Depends(current_trainer),
                 db: Session = Depends(get_db)):
    client = owned_client(db, trainer, client_id)
    if text.strip():
        db.add(models.Message(client_id=client.id, text=text.strip()[:500], created_at=now()))
        db.commit()
    return back(client.id, "avances", "Mensaje publicado")


@router.post("/messages/{message_id}/delete")
def delete_message(message_id: int, trainer: models.Trainer = Depends(current_trainer),
                   db: Session = Depends(get_db)):
    m = db.get(models.Message, message_id)
    if not m or m.client.trainer_id != trainer.id:
        raise HTTPException(404)
    cid = m.client_id
    db.delete(m)
    db.commit()
    return back(cid, "avances")


# ---------- rutina ----------
@router.post("/workouts")
async def create_workout(client_id: int = Form(...), day: str = Form(...), exercise_name: str = Form(...),
                         sets: int = Form(3), reps: int = Form(10), rest_seconds: int = Form(60),
                         note: str = Form(""), video_url: str = Form(""),
                         video_file: UploadFile | None = File(None),
                         trainer: models.Trainer = Depends(current_trainer), db: Session = Depends(get_db)):
    client = owned_client(db, trainer, client_id)
    name = exercise_name.strip()[:120]
    if day not in DAYS or not name:
        raise HTTPException(422, "Día o ejercicio inválido")
    url = check_video_url(video_url)
    if video_file is not None and video_file.filename:
        url, _, _ = await storage.save(video_file, storage.VIDEOS, "videos", storage.MAX_VIDEO)
    url = remember_exercise(db, trainer, name, url)
    db.add(models.Workout(client_id=client.id, day=day, exercise_name=name, video_url=url,
                          sets=clamp(sets, 1, 20), reps=clamp(reps, 1, 200),
                          rest_seconds=clamp(rest_seconds, 0, 600), note=note.strip()[:200] or None))
    db.commit()
    return back(client.id)


@router.post("/workouts/{workout_id}/delete")
def delete_workout(workout_id: int, trainer: models.Trainer = Depends(current_trainer),
                   db: Session = Depends(get_db)):
    w = db.get(models.Workout, workout_id)
    if not w or w.client.trainer_id != trainer.id:
        raise HTTPException(404)
    w.archived = True  # se conserva el historial de pesos
    db.commit()
    return back(w.client_id)


# ---------- plantillas ----------
@router.post("/clients/{client_id}/save-template")
def save_template(client_id: int, name: str = Form(...), trainer: models.Trainer = Depends(current_trainer),
                  db: Session = Depends(get_db)):
    client = owned_client(db, trainer, client_id)
    items = [w for w in client.workouts if not w.archived]
    if not items or not name.strip():
        return back(client.id, msg="Agrega ejercicios y un nombre para guardar la plantilla")
    tpl = models.Template(trainer_id=trainer.id, name=name.strip()[:120])
    tpl.items = [models.TemplateItem(day=w.day, exercise_name=w.exercise_name, video_url=w.video_url, sets=w.sets,
                                     reps=w.reps, rest_seconds=w.rest_seconds or 0, note=w.note)
                 for w in sorted(items, key=lambda w: (DAYS.index(w.day), w.id))]
    db.add(tpl)
    db.commit()
    return back(client.id, msg=f"Plantilla «{tpl.name}» guardada")


@router.post("/clients/{client_id}/apply-template")
def apply_template(client_id: int, template_id: int = Form(...), mode: str = Form("replace"),
                   trainer: models.Trainer = Depends(current_trainer), db: Session = Depends(get_db)):
    client = owned_client(db, trainer, client_id)
    tpl = db.get(models.Template, template_id)
    if not tpl or tpl.trainer_id != trainer.id:
        raise HTTPException(404, "Plantilla no encontrada")
    if mode == "replace":
        for w in client.workouts:
            w.archived = True
    for it in tpl.items:
        db.add(models.Workout(client_id=client.id, day=it.day, exercise_name=it.exercise_name,
                              video_url=it.video_url, sets=it.sets, reps=it.reps,
                              rest_seconds=it.rest_seconds, note=it.note))
    db.commit()
    return back(client.id, msg=f"Plantilla «{tpl.name}» aplicada")


# ---------- comidas ----------
def owned_meal(db: Session, trainer: models.Trainer, meal_id: int) -> models.MealLog:
    m = db.get(models.MealLog, meal_id)
    if not m or m.client.trainer_id != trainer.id:
        raise HTTPException(404)
    return m


@router.post("/meals/{meal_id}/comment")
def comment_meal(meal_id: int, comment: str = Form(""), trainer: models.Trainer = Depends(current_trainer),
                 db: Session = Depends(get_db)):
    m = owned_meal(db, trainer, meal_id)
    m.trainer_comment = comment.strip()[:300] or None
    db.commit()
    return back(m.client_id, "comidas")


@router.post("/meals/{meal_id}/delete")
def delete_meal(meal_id: int, trainer: models.Trainer = Depends(current_trainer), db: Session = Depends(get_db)):
    m = owned_meal(db, trainer, meal_id)
    cid = m.client_id
    storage.delete(m.photo_path)
    db.delete(m)
    db.commit()
    return back(cid, "comidas")


# ---------- biblioteca ----------
@router.get("/biblioteca", response_class=HTMLResponse)
def library(request: Request, trainer: models.Trainer = Depends(current_trainer), db: Session = Depends(get_db)):
    return render(
        request, "library.html", trainer,
        exercises=db.scalars(select(models.Exercise).where(models.Exercise.trainer_id == trainer.id)
                             .order_by(models.Exercise.name)).all(),
        templates_list=db.scalars(select(models.Template).where(models.Template.trainer_id == trainer.id)
                                  .order_by(models.Template.name)).all())


@router.post("/exercises")
async def create_exercise(name: str = Form(...), video_url: str = Form(""),
                          video_file: UploadFile | None = File(None),
                          trainer: models.Trainer = Depends(current_trainer), db: Session = Depends(get_db)):
    name = name.strip()[:120]
    if not name:
        raise HTTPException(422, "Falta el nombre")
    url = check_video_url(video_url)
    if video_file is not None and video_file.filename:
        url, _, _ = await storage.save(video_file, storage.VIDEOS, "videos", storage.MAX_VIDEO)
    remember_exercise(db, trainer, name, url)
    db.commit()
    return go("/admin/biblioteca")


@router.post("/exercises/{exercise_id}/delete")
def delete_exercise(exercise_id: int, trainer: models.Trainer = Depends(current_trainer),
                    db: Session = Depends(get_db)):
    e = db.get(models.Exercise, exercise_id)
    if not e or e.trainer_id != trainer.id:
        raise HTTPException(404)
    db.delete(e)  # el video se conserva: puede estar en uso en rutinas
    db.commit()
    return go("/admin/biblioteca")


@router.post("/templates/{template_id}/delete")
def delete_template(template_id: int, trainer: models.Trainer = Depends(current_trainer),
                    db: Session = Depends(get_db)):
    t = db.get(models.Template, template_id)
    if not t or t.trainer_id != trainer.id:
        raise HTTPException(404)
    db.delete(t)
    db.commit()
    return go("/admin/biblioteca")


# ---------- resumen semanal ----------
@router.get("/resumen", response_class=HTMLResponse)
def summary(request: Request, trainer: models.Trainer = Depends(current_trainer), db: Session = Depends(get_db)):
    start = today_start() - timedelta(days=6)
    rows = []
    clients = db.scalars(select(models.Client).where(models.Client.trainer_id == trainer.id)
                         .order_by(models.Client.name)).all()
    for c in clients:
        logs = db.scalars(select(models.WorkoutLog).where(
            models.WorkoutLog.client_id == c.id, models.WorkoutLog.created_at >= start)).all()
        meals = db.scalars(select(models.MealLog).where(
            models.MealLog.client_id == c.id, models.MealLog.created_at >= start)).all()
        planned = sum(w.sets for w in c.workouts if not w.archived)
        kcal_days: dict = {}
        for m in meals:
            if m.calories is not None:
                kcal_days[m.created_at.date()] = kcal_days.get(m.created_at.date(), 0) + m.calories
        rows.append({
            "id": c.id, "name": c.name, "days": len({l.created_at.date() for l in logs}),
            "sets_done": len(logs), "sets_planned": planned,
            "pct": min(100, round(len(logs) / planned * 100)) if planned else None,
            "meals": len(meals), "avg_kcal": round(sum(kcal_days.values()) / len(kcal_days)) if kcal_days else None,
            "goal": c.kcal_goal, "active": bool(logs or meals),
        })
    period = f"{start.strftime('%d/%m')}–{now().strftime('%d/%m')}"
    lines = [f"📊 Resumen semanal ({period})", ""]
    for r in rows:
        if not r["active"]:
            lines.append(f"⚠️ {r['name']}: sin actividad")
            continue
        parts = [f"{r['days']} día(s) de entrenamiento"]
        if r["pct"] is not None:
            parts.append(f"{r['pct']}% de series")
        parts.append(f"{r['meals']} comida(s)")
        if r["avg_kcal"] is not None:
            parts.append(f"≈{r['avg_kcal']:,} kcal/día")
        lines.append(f"✅ {r['name']}: " + ", ".join(parts))
    text = "\n".join(lines)
    return render(request, "summary.html", trainer, rows=rows, period=period, text=text,
                  wa=f"https://wa.me/{trainer.phone}?text={quote(text)}" if trainer.phone and rows else None)


# ---------- ajustes ----------
@router.get("/ajustes", response_class=HTMLResponse)
def settings(request: Request, trainer: models.Trainer = Depends(current_trainer)):
    return render(request, "settings.html", trainer)


@router.post("/ajustes")
async def save_settings(name: str = Form(""), phone: str = Form(""), brand_name: str = Form(""),
                        brand_color: str = Form(""), remove_logo: str = Form(""),
                        logo: UploadFile | None = File(None),
                        trainer: models.Trainer = Depends(current_trainer), db: Session = Depends(get_db)):
    trainer.name, trainer.phone = name.strip()[:120], clean_phone(phone)
    trainer.brand_name, trainer.brand_color = brand_name.strip()[:60], valid_color(brand_color)
    if logo is not None and logo.filename:
        url, _, _ = await storage.save(logo, storage.IMAGES, "brand", 2 * 1024 * 1024)
        storage.delete(trainer.logo_url)
        trainer.logo_url = url
    elif remove_logo:
        storage.delete(trainer.logo_url)
        trainer.logo_url = ""
    db.commit()
    return go("/admin/ajustes", "Ajustes guardados")


@router.post("/ajustes/password")
def change_password(request: Request, current: str = Form(...), new: str = Form(...),
                    trainer: models.Trainer = Depends(current_trainer), db: Session = Depends(get_db)):
    if not auth.verify_password(current, trainer.password_hash):
        return go("/admin/ajustes", "La contraseña actual no coincide")
    if len(new) < 8:
        return go("/admin/ajustes", "La nueva contraseña debe tener al menos 8 caracteres")
    trainer.password_hash = auth.hash_password(new)
    db.commit()
    request.session["weak"] = False
    return go("/admin/ajustes", "Contraseña actualizada")


# ---------- entrenadores (solo administrador) ----------
@router.get("/entrenadores", response_class=HTMLResponse)
def trainers(request: Request, owner: models.Trainer = Depends(require_owner), db: Session = Depends(get_db)):
    rows = db.scalars(select(models.Trainer).order_by(models.Trainer.id)).all()
    counts = dict(db.execute(select(models.Client.trainer_id, func.count()).group_by(models.Client.trainer_id)).all())
    return render(request, "trainers.html", owner, rows=rows, counts=counts)


@router.post("/entrenadores")
def create_trainer(username: str = Form(...), name: str = Form(""), password: str = Form(...),
                   owner: models.Trainer = Depends(require_owner), db: Session = Depends(get_db)):
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9._@-]{3,80}", username):
        return go("/admin/entrenadores", "Usuario inválido: usa letras, números, punto, guion o un correo")
    if len(password) < 8:
        return go("/admin/entrenadores", "La contraseña debe tener al menos 8 caracteres")
    if db.scalar(select(models.Trainer).where(models.Trainer.username == username)):
        return go("/admin/entrenadores", "Ese usuario ya existe")
    db.add(models.Trainer(username=username, name=name.strip()[:120], password_hash=auth.hash_password(password),
                          created_at=now()))
    db.commit()
    return go("/admin/entrenadores", f"Entrenador «{username}» creado")


@router.post("/entrenadores/{trainer_id}/toggle")
def toggle_trainer(trainer_id: int, owner: models.Trainer = Depends(require_owner), db: Session = Depends(get_db)):
    t = db.get(models.Trainer, trainer_id)
    if not t or t.is_owner:
        raise HTTPException(404)
    t.active = not t.active
    db.commit()
    return go("/admin/entrenadores")


@router.post("/entrenadores/{trainer_id}/password")
def reset_trainer_password(trainer_id: int, password: str = Form(...),
                           owner: models.Trainer = Depends(require_owner), db: Session = Depends(get_db)):
    t = db.get(models.Trainer, trainer_id)
    if not t:
        raise HTTPException(404)
    if len(password) < 8:
        return go("/admin/entrenadores", "La contraseña debe tener al menos 8 caracteres")
    t.password_hash = auth.hash_password(password)
    db.commit()
    return go("/admin/entrenadores", f"Contraseña de «{t.username}» actualizada")
