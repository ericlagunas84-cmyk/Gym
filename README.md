# FitStudio Express

Micro app PWA para entrenadores personales: rutinas diarias con video, registro de series y peso, fotos de comidas con contador de calorías por IA, seguimiento corporal y resumen semanal. Los clientes no instalan nada: abren un enlace personal.

## Inicio local

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Abre http://127.0.0.1:8000/login — usuario `admin`, contraseña `fitstudio` (cámbiala en **Ajustes**).

Para probar la cámara desde tu celular, arranca con `uvicorn main:app --host 0.0.0.0` y entra desde la misma red wifi a `http://IP-de-tu-compu:8000/login`.

## Cómo se usa

**Entrenador (`/login` → `/admin`)**

- **Clientes:** alta, enlace personal (copiar o enviar por WhatsApp), meta diaria de calorías y proteína.
  - *Rutina:* asigna ejercicios por día con series, repeticiones, descanso, indicación y video. Aplica o guarda plantillas.
  - *Comidas:* fotos con calorías estimadas, total por día contra la meta y comentario para el cliente.
  - *Avances:* mensaje para el cliente, progreso de peso por ejercicio e historial de series.
  - *Cuerpo:* peso, medidas y fotos de progreso con antes/después.
- **Biblioteca:** ejercicios con video reutilizables (se llena sola al asignar ejercicios) y plantillas de rutina.
- **Resumen:** cumplimiento de los últimos 7 días por cliente, con botón para enviártelo por WhatsApp.
- **Ajustes:** tu WhatsApp, nombre de marca, color y logo (lo ven tus clientes), y contraseña.
- **Entrenadores** (solo la cuenta administradora): crea cuentas para otros entrenadores, suspéndelas o restablece su contraseña. Cada entrenador ve únicamente sus clientes.

**Cliente (`/app?client_id=CÓDIGO`)** — tres pestañas:

- *Rutina:* video en bucle, "la vez pasada levantaste…", contador de series y temporizador de descanso.
- *Comida:* foto → calorías y macros estimados, barra de meta diaria y corrección de la estimación (a mano o recalculando con una descripción).
- *Progreso:* peso y medidas, foto de progreso, antes/después y gráfica de pesos por ejercicio.

## Variables de entorno

| Variable | Para qué | Por defecto |
|---|---|---|
| `ADMIN_USER` / `ADMIN_PASSWORD` | Cuenta administradora que se crea en el primer arranque | `admin` / `fitstudio` |
| `SECRET_KEY` | Firma de las sesiones | se genera y guarda en la base |
| `COOKIE_SECURE` | Pon `1` en producción (HTTPS) | apagado |
| `PUBLIC_URL` | Dirección pública para los enlaces de clientes, p. ej. `https://miapp.onrender.com` | se deduce de la petición |
| `DATABASE_URL` | Postgres, p. ej. la cadena de conexión de Supabase | `sqlite:///./fitstudio.db` |
| `UPLOAD_DIR` | Carpeta de fotos y videos (apúntala a un disco persistente) | `static/uploads` |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_BUCKET` | Guardar fotos y videos en Supabase Storage en vez de en disco | apagado / bucket `fitstudio` |
| `ANTHROPIC_API_KEY` | Activa el contador de calorías por foto | apagado |
| `NUTRITION_MODEL` | Modelo de visión para la estimación | `claude-haiku-4-5-20251001` |
| `TZ_NAME` | Zona horaria para "hoy" | `America/Ciudad_Juarez` |

## Despliegue en Render / Railway

1. Sube esta carpeta a un repositorio (privado) de GitHub.
2. Crea un "Web Service" con Python 3.11+.
3. Build: `pip install -r requirements.txt`
4. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"`
5. Define `ADMIN_PASSWORD`, `SECRET_KEY`, `COOKIE_SECURE=1`, `PUBLIC_URL` y `ANTHROPIC_API_KEY`.
6. **Datos persistentes** — elige una opción; sin esto, la base y las fotos se borran en cada redeploy:
   - **Supabase (recomendado):** crea un proyecto, copia su cadena de conexión a `DATABASE_URL`, crea un bucket **público** llamado `fitstudio` en Storage y define `SUPABASE_URL` y `SUPABASE_SERVICE_KEY`.
   - **Disco persistente:** monta un disco y define `UPLOAD_DIR=/ruta/del/disco/uploads` y `DATABASE_URL=sqlite:////ruta/del/disco/fitstudio.db`.

## Notas

- **Calorías:** son una estimación a partir de una imagen; sirven de referencia, no de medición exacta. Cada foto analizada tiene un costo en tu cuenta de Anthropic. Hay un tope de 20 fotos de comida por cliente al día.
- **Privacidad:** las fotos de comida se envían a Anthropic para analizarlas. Las fotos (incluidas las de progreso corporal) se guardan con nombres aleatorios pero son accesibles para quien tenga la dirección exacta; avísalo a tus clientes.
- **Historial:** al quitar un ejercicio de una rutina se archiva, para conservar el historial de pesos del cliente.
- **Resumen semanal:** no se envía solo; WhatsApp no permite envíos automáticos sin su API de negocio. El botón abre WhatsApp con el texto listo.
- **Bases anteriores:** al arrancar se agregan las columnas nuevas y los clientes existentes quedan asignados a la cuenta administradora.

## Estructura

```
main.py        vista del cliente, API y arranque
admin.py       panel del entrenador
auth.py        contraseñas y sesiones
storage.py     fotos y videos (disco local o Supabase Storage)
nutrition.py   estimación de calorías con IA
core.py        configuración y utilidades
models.py / schemas.py / database.py
templates/     client.html, admin.html, library.html, summary.html, settings.html, trainers.html, login.html
static/        css, js (Alpine), iconos, manifest, service worker, uploads
```
