# FitStudio Express

Micro app PWA para entrenadores personales: rutinas diarias con video, registro de series/peso y fotos de comidas, sin instalar nada desde una tienda de apps.

## Inicio local

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

- Panel del entrenador: http://127.0.0.1:8000/admin (usuario `admin`, contraseña `fitstudio`)
- Vista del cliente: el enlace personal que el panel genera para cada cliente, p. ej. `/app?client_id=k3Xv9Qm2LpA_&day=lunes` (el código es aleatorio; sin `day` muestra el día de hoy; también acepta `monday`, `tuesday`…)

Para probar la cámara desde tu celular, entra desde la misma red wifi con `uvicorn main:app --host 0.0.0.0` y abre `http://IP-de-tu-compu:8000/admin`.

## Variables de entorno

| Variable | Para qué | Valor por defecto |
|---|---|---|
| `ADMIN_USER` / `ADMIN_PASSWORD` | Acceso al panel `/admin` | `admin` / `fitstudio` |
| `ANTHROPIC_API_KEY` | Activa el contador de calorías por foto (clave de console.anthropic.com) | sin definir = apagado |
| `NUTRITION_MODEL` | Modelo de visión para la estimación | `claude-haiku-4-5-20251001` |
| `TZ_NAME` | Zona horaria para "hoy" | `America/Ciudad_Juarez` |
| `DATABASE_URL` | Base de datos | `sqlite:///./fitstudio.db` |

## Contador de calorías

Al guardar la foto de una comida, el servidor la envía a la API de Anthropic y guarda la estimación de calorías, proteína, carbohidratos y grasa. El cliente ve el resultado y el total del día; el entrenador lo ve en la pestaña Comidas. Es una estimación a partir de una imagen: sirve como referencia, no como medición exacta. Cada foto analizada tiene un costo pequeño en tu cuenta de Anthropic.

## Despliegue en Render / Railway

1. Sube esta carpeta a un repositorio de GitHub.
2. Crea un "Web Service" con Python 3.11+.
3. Build: `pip install -r requirements.txt`
4. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Define `ADMIN_PASSWORD`.
6. **Agrega un disco persistente** y apunta ahí la base de datos y `static/uploads`. Sin disco, en el plan gratuito la base SQLite y las fotos se borran en cada reinicio o redeploy.

## Endpoints

- `GET /app?client_id={id}&day={dia}` — vista del cliente
- `POST /api/logs/workout` — JSON `{client_id, workout_id, weight}` (`client_id` = código del enlace)
- `POST /api/logs/meal` — multipart `client_id`, `meal_type`, `photo`
- `GET /admin` — panel del entrenador (HTTP Basic)
