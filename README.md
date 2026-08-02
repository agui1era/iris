# IRIS

[English](#english) · [Español](#español)

## English

IRIS is a multi-camera monitoring service for care environments. It reads RTSP
streams, captures the newest frame from each camera, and sends scheduled images
to Alibaba Model Studio for structured risk analysis. The web dashboard shows
camera health, recent captures, risk scores, detection history, and system
settings in English or Spanish.

```text
RTSP cameras
     │
     ▼
parallel readers ──► latest frame per camera (single-frame buffer)
                         │ per-camera polling, 10-second minimum
                         ▼
              aspect-preserving resize
                         │
                         ▼
       JPEG + camera prompt ──► Alibaba Model Studio
                         │ serialized requests
                         ▼
          versioned preview + JSONL/Mongo event
                         │
                         ▼
                    web dashboard
```

### What it does

- Discovers cameras from `CAMn_*` environment variables and also lets
  administrators manage them from the dashboard.
- Keeps only the newest RTSP frame, so delayed frames never build up in a
  processing queue.
- Reads cameras in parallel while limiting Alibaba analysis to one active
  request at a time.
- Reconnects unavailable cameras without interrupting the rest of the system.
- Stores editable runtime settings in SQLite with revision checks to prevent
  one browser session from overwriting another.
- Writes every completed analysis to JSONL and can also publish detections to
  MongoDB.
- Can retain JPEG evidence according to severity and send camera-specific
  threshold alerts through Telegram.
- Keeps RTSP credentials and API keys out of logs. The Alibaba key is
  write-only in the dashboard.

IRIS assigns severity from the returned `risk_score`: `none` (0–9), `info`
(10–29), `low` (30–49), `medium` (50–69), `high` (70–89), and `critical`
(90–100). Model confidence is displayed separately and is never treated as a
risk score.

### Requirements

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- Node.js 20 or newer with npm
- RTSP cameras and Alibaba Model Studio credentials for live analysis

### Install

The setup script installs the Python and frontend dependencies and creates
local `.env` files without overwriting existing ones:

```bash
chmod +x install.sh
./install.sh
```

Use `./install.sh --create-admin` if you also want to create the first
administrator during setup. The password is requested interactively and is not
stored in shell history. Run `./install.sh --help` for the remaining options.

Manual setup is also available:

```bash
cp .env.example .env
uv sync --extra dev
uv run iris-monitor --check-config
uv run iris-users create --username admin --role admin

cd frontend
cp .env.example .env
npm ci
```

Edit the root `.env` before starting the services. At minimum, replace the
Alibaba credentials, camera URLs and prompts, and `AUTH_JWT_SECRET`.

### Run

Start each process in a separate terminal from the repository root:

```bash
uv run iris-monitor
uv run iris-api
cd frontend && npm run dev
```

The dashboard is served at `http://localhost:5173` and expects the API at
`http://localhost:8000` by default. Its language selector is available on both
the sign-in screen and the main navigation bar; the preference is saved in the
browser.

### Main configuration

| Variable | Default | Purpose |
|---|---:|---|
| `FRAME_WIDTH` / `FRAME_HEIGHT` | `640` / `360` | Output resolution shared by all cameras |
| `JPEG_QUALITY` | `82` | JPEG quality sent for analysis |
| `MAX_API_CALLS_PER_MINUTE` | `60` | Global API budget; `0` disables the limit |
| `CHANGE_THRESHOLD_PERCENT` | `0` | Minimum visual change before reanalysis; `0` analyzes every fresh frame |
| `SAVE_IMAGE_MIN_SEVERITY` | `high` | Minimum severity required to retain a JPEG |
| `CAPTURE_DIR` | `data/captures` | Capture and preview directory |
| `EVENTS_JSONL_PATH` | `data/events.jsonl` | Local event log |
| `IRIS_CONFIG_DB` | `data/config.db` | SQLite settings and users database |
| `AUTH_JWT_SECRET` | none | Required secret for `iris-api` |
| `API_CORS_ORIGINS` | `http://localhost:5173` | Comma-separated dashboard origins |

Each camera uses the following pattern:

```dotenv
CAM1_NAME=Bedroom
CAM1_RTSP_URL=rtsp://username:password@host:554/stream
CAM1_PROMPT=Detect falls and visible hazards near the bed.
CAM1_POLL_INTERVAL_SECONDS=30
CAM1_NOTIFICATION_THRESHOLD=high
```

Alibaba Model Studio requires `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL`, and
`DASHSCOPE_MODEL`. MongoDB and Telegram are optional; their variables and
operational details are documented in the Spanish reference below.

### Dashboard API

`iris-api` is separate from the monitor. It provides JWT authentication,
detection history, camera previews, and administrator routes for users,
cameras, and analysis settings. All routes except `/health` and `/auth/login`
require a bearer token. Administrator routes are restricted to the `admin`
role.

Create the first administrator before signing in:

```bash
uv run iris-users create --username admin --role admin
```

### Tests

```bash
uv run pytest
uv run ruff check .
cd frontend && npm run lint && npm run build
```

Tests use fake cameras and Alibaba responses; they do not contact real streams
or external APIs.

### Production notes

Build the dashboard with `npm run build` inside `frontend/` and serve
`frontend/dist/` with a static web server. Set `VITE_API_BASE_URL` at build
time and include the deployed dashboard origin in `API_CORS_ORIGINS`.

Camera images may contain sensitive personal data. Define access, consent,
retention, and data-residency policies before deploying IRIS in a real care
environment.

---

## Español

Servicio de monitoreo semántico multi-cámara. Lee streams RTSP y, cada 10
segundos o más, extrae una captura a la resolución global configurada y la
consulta en Alibaba Model Studio.

```text
RTSP CAM1..N
     │
     ▼
lectores paralelos ──► último frame por cámara (buffer de tamaño 1)
                         │ polling por cámara (mínimo 10 s, escalonado)
                         ▼
              resize con aspecto preservado
                         │
                         ▼
       JPEG + prompt de cámara ──► latest.jpg
                         │
                         ▼ llamadas serializadas (máximo 1 activa)
              Alibaba Model Studio (JSON)
                         │
                         ▼
       preview versionado + evento JSONL/Mongo
                         │
                         ▼
                  dashboard web
```

## Comportamiento

- Descubre dinámicamente cámaras desde `.env` mediante `CAMn_RTSP_URL`.
- `CAMn_POLL_INTERVAL_SECONDS` fija el ritmo de cada cámara. Su mínimo es 10
  segundos; el default es 30.
- `FRAME_WIDTH` y `FRAME_HEIGHT` fijan una única resolución para todas las
  capturas. Cada cámara configura nombre, URL RTSP, prompt e intervalo.
- Conserva sólo el frame más nuevo de cada RTSP: no acumula video ni analiza
  frames atrasados.
- Cada frame RTSP fresco encontrado al llegar su turno se analiza por defecto,
  aunque la escena sea visualmente igual a la anterior (`CHANGE_THRESHOLD_PERCENT=0`).
  Una secuencia RTSP repetida no se envía dos veces.
- Los lectores RTSP trabajan en paralelo, pero Alibaba procesa como máximo una
  solicitud global a la vez. El primer ciclo se escalona entre cámaras y cada
  una conserva, como máximo, su frame pendiente más nuevo.
- Si el primer intento ocurre antes de que RTSP entregue imagen, reintenta cada
  segundo hasta obtenerla; recién entonces comienza el intervalo normal.
- Aplica un presupuesto global de llamadas por minuto.
- Reconecta una cámara caída sin detener las demás.
- Persiste la configuración editable en SQLite con revisión atómica y la
  recarga sin solapar generaciones de lectores RTSP.
- Empareja cada mensaje semántico histórico con un preview inmutable por
  `event_id`; la portada separa explícitamente la captura operacional más
  reciente de la hora y el estado del último intento semántico.
- Guarda `latest.jpg` antes de llamar a Alibaba, por lo que la vista operativa
  funciona incluso si la API semántica falla.
- Nunca registra la URL RTSP ni la API key.

La protección principal contra saturación es el polling mínimo de 10 segundos,
complementado por la serialización global (una sola solicitud activa a la vez)
y el presupuesto de llamadas por minuto.

### Gating por variación (opcional)

Con `CHANGE_THRESHOLD_PERCENT` en `0` (default), todo frame fresco se analiza
siempre. Configurado por encima de `0`, IRIS puede evitar llamar a Alibaba
cuando la escena no cambió lo suficiente desde el último frame realmente
analizado por esa cámara:

- Compara el frame nuevo contra el último frame *analizado* (no el último
  capturado) en escala de grises, reducido a `DELTA_WIDTH`x`DELTA_HEIGHT`
  píxeles. Cuenta qué porcentaje de píxeles cambió más de
  `PIXEL_CHANGE_THRESHOLD` (0-255) y lo compara contra
  `CHANGE_THRESHOLD_PERCENT`.
- Si la variación queda por debajo del umbral, **omite la llamada a Alibaba**
  para ese frame: no se gasta cupo de RPM ni se genera un nuevo evento
  semántico. `latest.jpg` igual se actualiza (la vista operativa siempre
  muestra el frame más reciente) y queda un evento liviano
  `analysis.skipped` con `variation_index_percent` para trazabilidad.
- **Resguardo de seguridad**: sólo se permite omitir el análisis si la
  *última severidad confirmada* de esa cámara fue `none`, `info` o `low`. En
  cuanto una cámara registra `medium` o superior, cada frame fresco se
  vuelve a analizar sin importar cuánto varíe la imagen — así una situación
  crítica que se mantiene estable visualmente (una persona inmóvil, un foco
  de riesgo que no se mueve) nunca deja de re-evaluarse. Tampoco se omite
  jamás el primer frame de una cámara, al no existir todavía una base de
  comparación.
- El umbral (`change_threshold_percent`) es ajustable desde Administración;
  `PIXEL_CHANGE_THRESHOLD`, `DELTA_WIDTH` y `DELTA_HEIGHT` sólo se configuran
  por entorno (afinación interna, no expuesta en el dashboard).

## Inicio rápido

Requiere Python 3.11 o posterior.

La forma más rápida instala las dependencias de Python y del frontend y crea
los archivos `.env` locales sin reemplazar los que ya existan:

```bash
chmod +x install.sh
./install.sh
```

Usa `./install.sh --create-admin` para crear también el primer administrador
durante la instalación, o `./install.sh --help` para ver todas las opciones.

Instalación manual:

```bash
cp .env.example .env
uv sync --extra dev
uv run iris-monitor --check-config
uv run iris-users create --username admin --role admin
```

También se puede usar `python -m venv` y `pip install -e '.[dev]'`.

`--check-config` valida todo e imprime una vista redactada: nunca muestra claves,
prompts ni credenciales RTSP.

Luego levanta los tres procesos en terminales separadas:

```bash
uv run iris-monitor
uv run iris-api
cd frontend && npm install && npm run dev
```

## Configuración

Variables principales:

| Variable | Default | Descripción |
|---|---:|---|
| `FRAME_WIDTH` / `FRAME_HEIGHT` | `640` / `360` | Resolución global de salida |
| `JPEG_QUALITY` | `82` | Calidad de la captura enviada |
| `MAX_API_CALLS_PER_MINUTE` | `60` | Presupuesto global; `0` lo desactiva |
| `MAX_FRAME_PIXELS` | `2621440` | Techo de resolución para evitar OOM/costo |
| `SAVE_CAPTURES` | `true` | Habilita el guardado de capturas en disco |
| `SAVE_IMAGE_MIN_SEVERITY` | `high` | Severidad mínima para guardar el JPEG en disco |
| `CHANGE_THRESHOLD_PERCENT` | `0` | % mínimo de variación para re-analizar; `0` analiza siempre (ver [Gating por variación](#gating-por-variación-opcional)) |
| `PIXEL_CHANGE_THRESHOLD` | `24` | Delta mínimo (0-255) por píxel para contarlo como cambiado |
| `DELTA_WIDTH` / `DELTA_HEIGHT` | `160` / `90` | Resolución interna del índice de variación (no es la imagen enviada a Alibaba) |
| `CAPTURE_DIR` | `data/captures` | Directorio de capturas |
| `CAPTURE_RETENTION_DAYS` | `7` | Elimina evidencia más antigua; `0` desactiva |
| `CAPTURE_MAX_FILES_PER_CAMERA` | `1000` | Tope por cámara; `0` desactiva |
| `EVENTS_JSONL_PATH` | `data/events.jsonl` | Archivo de eventos completos |
| `EVENTS_MAX_BYTES` | `50000000` | Tamaño de cada JSONL antes de rotar |
| `EVENTS_BACKUP_COUNT` | `5` | Cantidad de archivos rotados |

Contrato por cámara:

```dotenv
CAM1_NAME=Dormitorio
CAM1_RTSP_URL=rtsp://usuario:clave@host:554/stream
CAM1_PROMPT=Detecta caídas y riesgos alrededor de la cama.
CAM1_POLL_INTERVAL_SECONDS=30
CAM1_NOTIFICATION_THRESHOLD=high
```

`CAMn_NOTIFICATION_THRESHOLD` (default `high`) es la severidad mínima para
notificar esa cámara por un canal externo (Telegram u otro). **Hoy sólo se
valida y persiste el umbral**: todavía no existe el envío real de
notificaciones; es la base para conectar ese canal más adelante sin tener que
rediseñar la configuración por cámara.

Para agregar otra cámara, se crean `CAM2_*`, luego `CAM3_*`, y así sucesivamente.
También se permiten canales con huecos (`CAM1`, `CAM3`, `CAM6`) y se conservan
sus identificadores físicos. Cada cámara debe tener su propio `CAMn_PROMPT`.

`ANALYSIS_COOLDOWN_SECONDS` y los overrides por cámara de resolución/variación
(`CAMn_FRAME_WIDTH`, `CAMn_FRAME_HEIGHT`, `CAMn_CHANGE_THRESHOLD_PERCENT`) son
legacy y se ignoran con una advertencia. Elimínalas durante el upgrade: la
resolución y el umbral de variación son siempre globales
(`FRAME_WIDTH`/`FRAME_HEIGHT`/`CHANGE_THRESHOLD_PERCENT`), nunca por cámara.
Tanto el default compatible `POLL_INTERVAL_SECONDS` como cada
`CAMn_POLL_INTERVAL_SECONDS` fallan de forma explícita si son menores a 10.

Por compatibilidad de migración, IRIS también reconoce
`VITE_RTSP_URL_CAMn`, pero emitirá una advertencia. No debe quedar como
configuración permanente: Vite expone variables `VITE_*` al código cliente y una
URL RTSP con usuario/clave podría terminar visible en el navegador. Migra así:

```dotenv
CAM1_RTSP_URL=rtsp://...
CAM3_RTSP_URL=rtsp://...
CAM1_PROMPT=Supervisa el dormitorio.
CAM3_PROMPT=Supervisa el acceso principal.
CAM1_POLL_INTERVAL_SECONDS=30
CAM3_POLL_INTERVAL_SECONDS=60
```

Después elimina las versiones `VITE_RTSP_URL_CAMn` y rota las credenciales que
hayan estado expuestas.

### Alibaba Model Studio

Son obligatorias:

```dotenv
DASHSCOPE_API_KEY=...
DASHSCOPE_BASE_URL=https://.../compatible-mode/v1
DASHSCOPE_MODEL=qwen3.6-flash
```

Si Model Studio entregó un CSV de workspace, se puede evitar copiar la clave:

```dotenv
DASHSCOPE_CREDENTIALS_CSV=".secrets/Default Workspace-apiKey-.csv"
DASHSCOPE_MODEL=qwen3.6-flash
```

IRIS lee `apiKey` y `openAiCompatible` de ese archivo. Si además se definen
variables explícitas, estas tienen prioridad. Guarda el CSV fuera del repositorio
o dentro de `.secrets/` (ignorado por Git) y restringe sus permisos:

```bash
chmod 600 '.secrets/Default Workspace-apiKey-.csv'
```

La URL y la clave son regionales y deben coincidir. IRIS usa Chat Completions
compatible con OpenAI, envía una sola imagen JPEG como Data URI y solicita JSON
con `enable_thinking=false`. Consulta la documentación oficial de
[Chat Completions](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions),
[entrada visual/base64](https://www.alibabacloud.com/help/en/model-studio/vision)
y [claves API](https://www.alibabacloud.com/help/en/model-studio/get-api-key).

El único prompt funcional es `CAMn_PROMPT`: IRIS lo envía en un mensaje de
usuario junto al nombre de cámara, timestamp UTC y un contrato técnico no
editable con el esquema JSON. No existe system prompt global.

#### Contrato de riesgo

Alibaba debe devolver `risk_score` como entero de `0` a `100`. Representa el
riesgo visible e inmediato para la seguridad de la persona, no la certeza del
modelo. `confidence` sigue siendo un número separado de `0` a `1`: es el
propio juicio del modelo sobre qué tan bien pudo interpretar la escena (baja
si la imagen está ocluida, mal iluminada, borrosa, o si sus propias
`observations`/`summary` resultan vagas o inciertas; alta si pudo describir la
escena con claridad y detalle), nunca el nivel de riesgo:

| `risk_score` | Severidad normalizada |
|---:|---|
| `0–9` | `none` |
| `10–29` | `info` |
| `30–49` | `low` |
| `50–69` | `medium` |
| `70–89` | `high` |
| `90–100` | `critical` |

IRIS calcula siempre `severity` con esta tabla y fija `alert=true` sólo desde
`70`. Si el modelo envía valores contradictorios de severidad o alerta, el
backend los reemplaza. También rechaza scores booleanos, decimales, strings o
fuera de rango.

Además de `risk_score`, Alibaba debe devolver `criticidad` como uno de cuatro
colores exactos: `verde`, `amarillo`, `naranja` o `rojo` (normalizado a
minúsculas; cualquier otro valor, o su ausencia, hace fallar el análisis). A
diferencia de `severity`/`alert`, `criticidad` **no** la calcula IRIS: es el
juicio propio e independiente del modelo sobre qué tan crítica se ve la
escena, e IRIS la muestra tal cual junto a la severidad calculada, sin usarla
para severity, alert ni para el gating de `SAVE_IMAGE_MIN_SEVERITY`. El
dashboard la presenta como una insignia separada ("Criticidad IA"); un color
`negro`/"Sin datos" en la UI significa que esa cámara todavía no tiene ningún
análisis, no un quinto nivel de riesgo devuelto por el modelo.

Desde la UI, la Base URL se restringe a endpoints oficiales HTTPS bajo
`.aliyuncs.com/compatible-mode/v1`; así una edición accidental no puede enviar
la API key write-only a un host ajeno. El timeout editable está limitado a
`1–300` segundos.

### Configuración en SQLite (recomendado en producción)

El dashboard guarda en SQLite las cámaras, prompts, polling por cámara y
parámetros operacionales (resolución global, límite de llamadas, severidad,
umbral de variación y proveedor Alibaba). Cada cambio incrementa una revisión dentro de
la misma transacción; un formulario desactualizado recibe `409` en vez de pisar
otra edición.

En el primer arranque, API o monitor siembran una sola vez estos valores desde
el entorno. SQLite pasa a tener prioridad para las claves persistidas; el entorno
sigue siendo fallback. La clave Alibaba se persiste en el SQLite desde el
primer arranque y se puede reemplazar desde Administración: es write-only, un
campo vacío conserva la actual y ninguna respuesta HTTP la devuelve. Que el
archivo exista sólo porque `iris-users` creó la tabla de usuarios no hace que
IRIS ignore el `.env`.

Para migrar una instalación basada en `.env`, IRIS incluye una operación
one-shot:

```bash
uv run iris-monitor --migrate-env-to-sqlite
```

Esto lee `--dotenv-path` (por defecto `.env`), valida la configuración completa
y guarda sólo claves reconocidas por IRIS en `IRIS_CONFIG_DB` (o `--config-db`).
Si el store ya fue inicializado, se niega a sobrescribirlo. Así un `.env`
antiguo no pisa cambios hechos después desde Administración.

Una vez migrado, ejecuta el servicio apuntando al archivo resultante:

```bash
uv run iris-monitor --config-db data/config.db
# o, de forma equivalente:
IRIS_CONFIG_DB=data/config.db uv run iris-monitor
```

El archivo y su directorio se crean con permisos `0600`/`0700`. Conserva en un
secret manager o entorno del proceso JWT y las conexiones de infraestructura
que decidas no migrar.

### Sink de detecciones en MongoDB (opcional)

Por defecto, cada evento de análisis completado se escribe únicamente en el
JSONL local (`EVENTS_JSONL_PATH`). Si además quieres consultarlos desde
MongoDB, define:

```dotenv
MONGO_URI=mongodb://usuario:clave@localhost:27017
MONGO_DATABASE=iris
MONGO_DETECTION_COLLECTION=iris_detections
```

Cuando `MONGO_URI` está configurada, IRIS escribe cada evento en MongoDB
además del JSONL local: el JSONL sigue funcionando como red de seguridad si
Mongo no está disponible momentáneamente (un fallo al publicar en un sink no
detiene la publicación en el otro). Si `MONGO_URI` no está definida, el
comportamiento es idéntico al actual: sólo se usa el JSONL local.

Para convivir con la configuración existente de Sentinex también se aceptan
`SENTINEX_MONGO_URI`, `SENTINEX_MONGO_DB` y
`SENTINEX_MONGO_DETECTION_COLLECTION` como aliases.

### Notificaciones por Telegram (opcional)

```dotenv
ENABLE_TELEGRAM=true
TELEGRAM_BOT_TOKEN=123456:AAExampleTokenNoEsReal
TELEGRAM_CHAT_ID=-1001234567890
```

Un único bot/chat global recibe la notificación (foto + texto) de cualquier
análisis completado cuya severidad alcance o supere el
`notification_threshold` **de esa cámara** (editable por cámara desde
Administración; default `high`). Sin `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`
definidas, el envío queda desactivado y el comportamiento es idéntico al
actual. `ENABLE_TELEGRAM` (default `true`) es un interruptor maestro aparte:
permite guardar las credenciales y dejar el envío apagado explícitamente sin
borrarlas. Un fallo o timeout de Telegram se registra en el log y nunca
interrumpe el análisis semántico ni los demás sinks — mismo principio que el
sink de MongoDB. No existe (todavía) enrutamiento de chats distintos por
cámara: todas las cámaras que superen su propio umbral notifican al mismo
chat.

### Guardado de imágenes según severidad

Todo análisis programado se registra siempre en el historial de eventos
(JSONL y, si aplica, MongoDB), sin excepción. Lo que ahora es condicional es
si además se guarda el JPEG correspondiente en disco: la imagen sólo se
persiste cuando la severidad reportada por el análisis (`analysis.severity`)
alcanza o supera `SAVE_IMAGE_MIN_SEVERITY` (por defecto `high`). Valores
válidos, de menor a mayor: `none`, `info`, `low`, `medium`, `high`, `critical`.

- Un análisis por debajo del umbral se registra igual, pero su evento trae
  `"snapshot_path": null`: nunca se escribió un JPEG para él.
- Un análisis fallido (`analysis.failed`) tampoco tiene imagen, ya que no hay
  severidad que evaluar: `snapshot_path` siempre es `null` en ese caso. Aun
  así, su frame operacional ya quedó disponible como `latest.jpg`.
- Subir el umbral (por ejemplo a `critical`) reduce cuántas imágenes se
  guardan en disco sin afectar el historial de eventos, que sigue completo.

## Resultados

Cada solicitud completada genera un objeto JSON con cámara, fechas, resolución,
captura, modelo, uso y análisis. `snapshot_path` es la ruta al JPEG guardado en
disco, o `null` si la severidad quedó por debajo de
`SAVE_IMAGE_MIN_SEVERITY` (o si el análisis falló):

```json
{
  "event_type": "analysis.completed",
  "event_id": "832e8c5a7f6c4bf9b1066a387928fa28",
  "camera_id": "CAM1",
  "resolution": {"width": 640, "height": 360},
  "trigger": "poll",
  "preview_path": "data/captures/CAM1/preview-832e8c5a7f6c4bf9b1066a387928fa28.jpg",
  "snapshot_path": "data/captures/CAM1/20260727T120000.000000Z_Dormitorio_frame-000000000042.jpg",
  "analysis": {
    "risk_score": 82,
    "alert": true,
    "severity": "high",
    "event": "possible_fall",
    "confidence": 0.86,
    "summary": "Persona visible en el suelo.",
    "observations": ["Postura horizontal junto a la cama."],
    "recommended_action": "Solicitar revisión inmediata.",
    "requires_human_review": true,
    "criticidad": "rojo"
  }
}
```

Con `CHANGE_THRESHOLD_PERCENT` activo, un ciclo con variación insuficiente no
genera un `analysis.completed`: genera en cambio un evento liviano
`analysis.skipped` (sin `analysis` ni `snapshot_path`, sólo
`variation_index_percent` y `change_threshold_percent`), y el dashboard sigue
mostrando la última lectura semántica real como vigente.

Este servicio genera evidencia y eventos; el canal final de alerta (webhook,
mensajería, central de cuidadores, etc.) queda desacoplado para integrarlo sin
cambiar la captura RTSP.

Las carpetas de evidencia se crean con modo `0700` y los archivos con `0600`.
Los logs de consola incluyen sólo metadatos operacionales; el resumen y las
observaciones completas quedan en el JSONL privado. Antes de desplegar, define
políticas de consentimiento, acceso, residencia y retención apropiadas para
datos sensibles de personas mayores.

## API del dashboard (iris-api)

`iris-api` es un proceso de larga duración **separado** de `iris-monitor`:
expone por HTTP el historial de detecciones (leído de MongoDB) y la
administración de usuarios/roles (leída del SQLite de `iris.users_store`)
para un dashboard. Comparte el mismo almacén de configuración
(`config.py`/`config_store.py`) que `iris-monitor`, pero no depende de él ni
lo reemplaza: puedes correr uno sin el otro.

### Bootstrap del primer administrador

No existe usuario ni contraseña inicial por defecto. Antes de levantar la API
crea al menos un usuario con rol `admin`:

```bash
uv run iris-users create --username admin --role admin
```

El comando pide la contraseña de forma interactiva (no queda en el historial
de la shell). Ver `uv run iris-users --help` para `list`, `set-role` y
`set-active`.

### Variables de entorno

| Variable | Default | Descripción |
|---|---:|---|
| `AUTH_JWT_SECRET` | *(ninguno)* | Obligatoria para `iris-api`; sin ella el proceso se niega a arrancar |
| `AUTH_JWT_EXPIRES_MINUTES` | `480` | Minutos de validez de cada token (mínimo `5`) |
| `API_CORS_ORIGINS` | `http://localhost:5173` | Orígenes permitidos, separados por coma; nunca `*` |
| `API_HOST` | `0.0.0.0` | Interfaz donde escucha uvicorn |
| `API_PORT` | `8000` | Puerto donde escucha uvicorn |

`AUTH_JWT_SECRET` es la única variable de este bloque que `iris-monitor` jamás
lee: sólo le importa a `iris-api`. `load_config()` la deja en `None` si falta
—no lanza `ConfigurationError`—, porque un despliegue de sólo-monitoreo no
necesita definirla. Es `iris-api`, en su propio arranque, quien falla de forma
clara si `AUTH_JWT_SECRET` no está configurada. Genera un secreto con:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Ejecutar la API

```bash
uv run iris-api
```

Arranca uvicorn en `API_HOST:API_PORT` sirviendo la app de
`iris.api.app:create_app`. La configuración (incluida `AUTH_JWT_SECRET`) se
resuelve igual que en `iris-monitor`: SQLite tiene prioridad para las claves
persistidas y el entorno completa secretos/infraestructura no almacenados.

### Endpoints

Todos (salvo `/health` y `/auth/login`) requieren
`Authorization: Bearer <token>` obtenido en `/auth/login`.

| Método y ruta | Rol requerido | Descripción |
|---|---|---|
| `GET /health` | ninguno | `{"status": "ok"}` |
| `POST /auth/login` | ninguno | Recibe `{username, password}`, devuelve `access_token`, `token_type`, `username`, `role` |
| `GET /auth/me` | cualquiera autenticado | Usuario y rol del token actual |
| `GET /detections/latest?limit=` | cualquiera autenticado | Detecciones más recientes (máx. `200`) |
| `GET /detections?date_from=&date_to=&camera_id=&severity=&criticidad=&sort_by=&sort_order=&page=&page_size=` | cualquiera autenticado | Historial paginado y filtrado (`page_size` máx. `200`). `sort_by` es `captured_at` (default), `camera_id` o `criticidad`; `sort_order` es `desc` (default) o `asc` |
| `GET /detections/{id}/image` | cualquiera autenticado | JPEG de la detección, si existe y está dentro de `CAPTURE_DIR` |
| `DELETE /detections/{id}` | `admin` | Elimina una detección del historial (Mongo); no borra el JPEG asociado en disco |
| `GET /api/dashboard` | cualquiera autenticado | Una tarjeta por cámara: conectividad, captura operacional y estado `completed/failed/pending` del último intento semántico |
| `GET /cameras/{camera_id}/latest-frame` | cualquiera autenticado | Último frame capturado para el siguiente análisis de visión de esa cámara |
| `GET /cameras/{camera_id}/events/{event_id}/frame` | cualquiera autenticado | Preview inmutable asociado exactamente a ese análisis |
| `GET /admin/users` | `admin` | Lista de usuarios (sin `password_hash`) |
| `POST /admin/users` | `admin` | Crea un usuario: `{username, password, role}` |
| `PATCH /admin/users/{username}` | `admin` | Actualiza `{role?, is_active?}` |
| `GET /admin/settings` | `admin` | Revisión y configuración editable del motor de análisis |
| `PATCH /admin/settings` | `admin` | Actualiza captura global, límites, severidad y proveedor Alibaba |
| `GET /admin/cameras` | `admin` | Lista cámaras con URL RTSP completa, prompt e intervalo |
| `POST /admin/cameras` | `admin` | Agrega `{name, rtsp_url, prompt, poll_interval_seconds, notification_threshold?}` |
| `PATCH /admin/cameras/{index}` | `admin` | Actualiza campos parciales de una cámara existente |
| `DELETE /admin/cameras/{index}` | `admin` | Elimina una cámara (rechaza borrar la última restante) |

`/admin/settings` expone únicamente parámetros operacionales: resolución
global, RPM, calidad JPEG, severidad mínima de evidencia, umbral de variación
y proveedor Alibaba. La API key es write-only:
la respuesta sólo incluye `alibaba_api_key_configured`. Un valor vacío conserva
la clave actual. JWT, Mongo, CORS, host/puerto y rutas de infraestructura no se
exponen en esta API.

El `PATCH /admin/settings` debe incluir la `revision` leída por el formulario.
La mutación y la validación completa ocurren dentro de un único
`BEGIN IMMEDIATE`: una revisión obsoleta recibe `409` y un valor inválido recibe
`400`/`422`, sin escrituras parciales ni rollback que pueda pisar cambios de otra
sesión.

Las cámaras (`CAMn_RTSP_URL`, `CAMn_PROMPT`, `CAMn_NAME`,
`CAMn_POLL_INTERVAL_SECONDS`) también pueden
agregarse, editarse y eliminarse vía la API del dashboard
(`POST`/`PATCH`/`DELETE /admin/cameras`), además de editar el almacén SQLite.
`/admin/cameras` reutiliza toda la validación de
`iris.config.load_config()` (forma de la URL RTSP, prompt no vacío e intervalo
de al menos 10 segundos). `GET /admin/cameras` devuelve la URL RTSP completa
exclusivamente al rol `admin`; en un `PATCH`, omitirla o enviar `""` conserva
el valor existente.

`iris-monitor` observa la revisión SQLite. Valida el snapshot nuevo, detiene por
completo la generación anterior y sólo entonces crea lectores/analyzer nuevos.
Un lock de instancia evita dos monitores sobre la misma configuración.

Si `MONGO_URI` no está configurada, los endpoints de `/detections/*` responden
`503` en lugar de fallar de forma confusa: el historial no existe sin Mongo.

### Vista previa del último frame capturado

`GET /cameras/{camera_id}/latest-frame` ofrece el alias operacional del último
frame capturado para análisis, incluso mientras Alibaba procesa el anterior o
si la llamada semántica termina con error. La escritura ocurre antes de la
llamada semántica, usa un temporal y termina con
`os.replace`, por lo que una lectura concurrente nunca observa un JPEG parcial.
Es
un mecanismo completamente **separado** de las capturas históricas con
gating por severidad (`SAVE_IMAGE_MIN_SEVERITY`, `/detections/{id}/image`):
no depende de `SAVE_CAPTURES` ni de que el análisis haya resultado relevante,
y tampoco depende de MongoDB (a diferencia de `/detections/*`, este endpoint
funciona igual con o sin `MONGO_URI` configurada, ya que sólo lee un archivo
de `CAPTURE_DIR`). Responde `404` si la cámara no está configurada o si
todavía no produjo ningún frame capturable desde que arrancó
`iris-monitor`, e incluye siempre `Cache-Control: no-store` para que el
navegador nunca cachee un frame ya obsoleto. Como el historial de
detecciones, es visible para **cualquier rol autenticado** (no es exclusivo
de `admin`): el mismo nivel de acceso que las imágenes de detecciones
históricas.

La vista principal usa preferentemente
`/cameras/{camera_id}/latest-frame`, de modo que una falla de Alibaba no deje
congelada una foto anterior. La hora mostrada sobre esa foto corresponde a la
captura operacional; el texto, score y severidad conservan la hora del último
análisis completado y pueden ser anteriores mientras avanza el turno serial.
El historial usa
`/cameras/{camera_id}/events/{event_id}/frame`: cada análisis exitoso genera un
`event_id` y un preview inmutable con ese identificador para conservar la
evidencia emparejada con su resultado semántico.

No confundir con streaming de video real: reproducir RTSP en el navegador
requeriría una capa de transcodificación (p. ej. a HLS/WebRTC) que está fuera
del alcance de este endpoint; esto es sólo una foto fija que se refresca cada
ciclo de análisis, no un stream en vivo.

Cada rol ve exactamente lo mismo en `/detections/*` (sólo lectura); `admin` es
estrictamente necesario para `/admin/*`.

## Dashboard web (frontend/)

`frontend/` es una SPA de Vite + React + TypeScript separada de los procesos
Python. Su portada es el centro de monitoreo: una tarjeta por cámara con
conectividad, captura, risk score, severidad, hora, confianza y último resumen
Alibaba. Consulta `/api/dashboard` con polling encadenado cada 3 segundos, sin
solapar requests, y sólo vuelve a bajar la imagen cuando cambia la fecha de la
captura operacional.

También conserva el historial y una administración exclusiva para rol `admin`.
Allí se gestionan usuarios, cámaras/prompts/intervalos y los parámetros
operacionales del motor. La clave Alibaba se escribe pero nunca vuelve al
navegador; las URL RTSP completas se muestran sólo en Administración y las
credenciales Mongo/JWT no se exponen.

### Ejecutar el dashboard

```bash
cd frontend
npm install
cp .env.example .env   # ajusta VITE_API_BASE_URL si iris-api no corre en localhost:8000
npm run dev
```

Esto arranca Vite en `http://localhost:5173` (el origen por defecto en
`API_CORS_ORIGINS`, ver arriba). El dashboard **no** funciona por sí solo:
`VITE_API_BASE_URL` debe apuntar a una instancia de `iris-api` corriendo (ver
la sección anterior para levantarla con `uv run iris-api`), y esa API necesita
al menos un usuario `admin` creado con `iris-users` y, para las vistas de
detecciones, `MONGO_URI` configurada.

Para producción: `npm run build` genera un `frontend/dist/` estático que puede
servirse con cualquier servidor de archivos (nginx, Caddy, etc.), siempre que
`VITE_API_BASE_URL` haya sido fijada en tiempo de build y el origen resultante
esté incluido en `API_CORS_ORIGINS` de `iris-api`.

## Pruebas

```bash
uv run pytest
uv run ruff check .
```

Las pruebas usan cámaras y respuestas Alibaba falsas: no consumen streams ni API
reales. Las pruebas de `iris-api` (`tests/test_api_*.py`) usan
`fastapi.testclient.TestClient` contra un SQLite temporal y, para las rutas de
detecciones, un fake de colección Mongo escrito a mano (sin dependencias
adicionales), siguiendo el mismo estilo que `MemoryEventSink` en
`tests/test_service.py`.
