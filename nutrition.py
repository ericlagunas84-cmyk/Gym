"""Estimación de calorías a partir de la foto de una comida (API de Anthropic, visión).

Requiere la variable de entorno ANTHROPIC_API_KEY. Sin ella la app funciona igual,
solo que las fotos se guardan sin estimación.
"""
import base64
import logging
import os
from pathlib import Path

log = logging.getLogger("fitstudio.nutrition")

MODEL = os.getenv("NUTRITION_MODEL", "claude-haiku-4-5-20251001")
SUPPORTED = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}

TOOL = {
    "name": "registrar_estimacion",
    "description": "Registra la estimación nutricional de la comida que aparece en la foto.",
    "input_schema": {
        "type": "object",
        "properties": {
            "es_comida": {"type": "boolean", "description": "false si la foto no muestra comida o bebida"},
            "descripcion": {"type": "string", "description": "Qué se ve en el plato, en español, máx. 80 caracteres"},
            "calorias": {"type": "integer", "description": "kcal totales estimadas de la porción visible"},
            "proteina_g": {"type": "integer"},
            "carbohidratos_g": {"type": "integer"},
            "grasa_g": {"type": "integer"},
        },
        "required": ["es_comida", "descripcion", "calorias", "proteina_g", "carbohidratos_g", "grasa_g"],
    },
}

PROMPT = (
    "Eres un nutriólogo. Observa la foto de esta comida ({meal_type}) e identifica los alimentos y el "
    "tamaño aproximado de las porciones. Estima las calorías totales y los gramos de proteína, "
    "carbohidratos y grasa de todo lo que se ve. Considera que suele ser comida mexicana casera o de "
    "restaurante. Si la foto no muestra comida, marca es_comida=false y pon ceros."
)


def enabled() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def estimate(photo: Path, meal_type: str) -> dict | None:
    """Devuelve {description, calories, protein_g, carbs_g, fat_g} o None si no se pudo estimar."""
    media_type = SUPPORTED.get(photo.suffix.lower())
    if not enabled() or not media_type:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(timeout=40.0, max_retries=1)
        msg = client.messages.create(
            model=MODEL,
            max_tokens=400,
            tools=[TOOL],
            tool_choice={"type": "tool", "name": TOOL["name"]},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                             "data": base64.standard_b64encode(photo.read_bytes()).decode()}},
                {"type": "text", "text": PROMPT.format(meal_type=meal_type)},
            ]}],
        )
        data = next(b.input for b in msg.content if b.type == "tool_use")
        if not data.get("es_comida"):
            return None
        clamp = lambda v, hi: max(0, min(int(v or 0), hi))
        return {
            "description": str(data.get("descripcion", ""))[:120],
            "calories": clamp(data.get("calorias"), 5000),
            "protein_g": clamp(data.get("proteina_g"), 500),
            "carbs_g": clamp(data.get("carbohidratos_g"), 800),
            "fat_g": clamp(data.get("grasa_g"), 500),
        }
    except Exception:  # la foto ya quedó guardada; la estimación es opcional
        log.exception("No se pudo estimar las calorías")
        return None
