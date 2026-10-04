"""Almacenamiento de fotos y videos.

- Por defecto: carpeta local (UPLOAD_DIR, servida en /media). En Render/Railway apunta
  UPLOAD_DIR a un disco persistente.
- Con SUPABASE_URL + SUPABASE_SERVICE_KEY: Supabase Storage (bucket público SUPABASE_BUCKET).
"""
import os
import uuid
from pathlib import Path

import httpx
from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "static" / "uploads")).resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
BUCKET = os.getenv("SUPABASE_BUCKET", "fitstudio")

IMAGES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
VIDEOS = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"}
MAX_PHOTO = 10 * 1024 * 1024
MAX_VIDEO = 60 * 1024 * 1024
_MEDIA = {ext: mt for mt, ext in {**IMAGES, **VIDEOS}.items()}


def remote() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def media_type(url: str) -> str:
    return _MEDIA.get(Path(url.split("?")[0]).suffix.lower(), "application/octet-stream")


def _headers(content_type: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {SUPABASE_KEY}", "apikey": SUPABASE_KEY}
    if content_type:
        h["Content-Type"] = content_type
    return h


def _local_path(url: str) -> Path | None:
    if not url.startswith("/media/"):
        return None
    path = (UPLOAD_DIR / url[len("/media/"):]).resolve()
    return path if path.is_relative_to(UPLOAD_DIR) else None


def _remote_key(url: str) -> str | None:
    prefix = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/"
    return url[len(prefix):] if remote() and url.startswith(prefix) else None


def _put(key: str, data: bytes, content_type: str) -> str:
    if remote():
        r = httpx.post(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{key}", content=data,
                       headers=_headers(content_type), timeout=120)
        r.raise_for_status()
        return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{key}"
    path = UPLOAD_DIR / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return f"/media/{key}"


async def save(file: UploadFile, allowed: dict, folder: str, max_bytes: int) -> tuple[str, bytes, str]:
    """Valida y guarda un archivo subido. Devuelve (url, bytes, tipo)."""
    ctype = (file.content_type or "").lower()
    ext = allowed.get(ctype)
    if not ext:
        raise HTTPException(415, "Tipo de archivo no permitido")
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data += chunk
        if len(data) > max_bytes:
            raise HTTPException(413, "El archivo es demasiado grande")
    if not data:
        raise HTTPException(400, "Archivo vacío")
    key = f"{folder}/{uuid.uuid4().hex}{ext}"
    try:
        url = await run_in_threadpool(_put, key, bytes(data), ctype)
    except httpx.HTTPError:
        raise HTTPException(502, "No se pudo guardar el archivo. Intenta de nuevo.")
    return url, bytes(data), ctype


def read(url: str) -> bytes | None:
    try:
        if (path := _local_path(url)) is not None:
            return path.read_bytes() if path.is_file() else None
        if _remote_key(url):
            r = httpx.get(url, timeout=60)
            return r.content if r.status_code == 200 else None
    except (OSError, httpx.HTTPError):
        pass
    return None


def delete(url: str | None) -> None:
    if not url:
        return
    try:
        if (path := _local_path(url)) is not None:
            path.unlink(missing_ok=True)
        elif (key := _remote_key(url)):
            httpx.delete(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{key}", headers=_headers(), timeout=30)
    except (OSError, httpx.HTTPError):
        pass
