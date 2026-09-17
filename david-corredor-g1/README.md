# ATLAS CLOUD // SIGNAL-80 — Solución

Motor inteligente de triage y correlación de incidentes — Reto Hackathon Huawei MaaS.

Convierte 12.847 tickets de soporte en decisiones accionables usando **GLM 5.2** como motor semántico.

---

## Stack

| Capa | Tecnología |
|---|---|
| **Backend** | NestJS 10 + TypeScript (Screaming Architecture) |
| **Frontend** | Next.js 16 + React 19 + Tailwind 4 + shadcn (v0.app design) |
| **IA** | GLM 5.2 vía `openai` SDK (Huawei Cloud MaaS OpenAI-compatible) |
| **Eventos** | Kafka (KafkaJS) — topics: `tickets.raw`, `tickets.classified`, `incidents.detected` |
| **Persistencia** | MongoDB 7 (Mongoose) — collections: `tickets`, `incidents`, `auditlogs` |
| **Validación** | Zod (schemas estrictos) |
| **Infra** | Docker Compose (Mongo + Kafka + Zookeeper + Kafka-UI + Mongo-Express) |
| **Tests** | Jest |

---

## Arquitectura

```
tickets_sample.json → POST /api/tickets/ingest → Kafka "tickets.raw"
  → consumer triage → GLM 5.2 classify → Zod validate → Mongo "tickets"
  → Kafka "tickets.classified"
  → consumer correlation → GLM 5.2 correlate → Mongo "incidents"
  → GET /api/control-room/queue → Frontend Next.js
```

### Screaming Architecture (carpetas por dominio)

```
backend/src/
├── tickets/             # Ingesta + persistencia de tickets
├── triage/              # Clasificación GLM 5.2 + Zod + retries
├── correlation/         # Agrupación + incidente mayor + blast radius
├── control-room/        # API para UI + reportes explicabilidad
├── glm/                 # Wrapper GLM 5.2 (kernel compartido)
├── audit/               # Log auditable (sin secretos)
└── shared/              # Config, logger, errors, Kafka
```

---

## Configuración de GLM 5.2

GLM 5.2 se integra vía el SDK oficial de OpenAI (`openai` npm) configurado con `baseURL` apuntando a Huawei Cloud MaaS (endpoint OpenAI-compatible).

- **Endpoint:** `https://api-ap-southeast-1.modelarts-maas.com/openai/v1`
- **Modelo:** `glm-5.2`
- **Auth:** Bearer token
- **Structured output:** Function calling con `tool_choice` forzado
- **Rate limit:** p-limit (max 5 concurrentes) — Bono B

---

## Variables de entorno

Copia `backend/.env.example` a `backend/.env` y completa:

```env
MAAS_API_KEY=tu_api_key_de_huawei_maas
GLM_BASE_URL=https://api-ap-southeast-1.modelarts-maas.com/openai/v1
GLM_MODEL=glm-5.2
MONGO_URI=mongodb://atlas:atlasdev@localhost:27017/atlas?authSource=admin
KAFKA_BROKERS=localhost:9092
CONFIDENCE_THRESHOLD=0.60
MAX_RETRIES=3
GLM_MAX_CONCURRENCY=5
GLM_TIMEOUT_MS=30000
PORT=3001
```

Frontend: copia `frontend/.env.local.example` a `frontend/.env.local`:

```env
NEXT_PUBLIC_API_BASE=http://localhost:3001/api
```

---

## Instalación

### 1. Levantar infraestructura

```bash
docker compose up -d
```

Desde la carpeta `codigo/`:

```bash
cd codigo
docker compose up -d
```

Esto levanta:
- MongoDB en `localhost:27017`
- Mongo-Express en `localhost:8081` (admin/admin)
- Kafka en `localhost:9092`
- Kafka-UI en `localhost:8080`

### 2. Backend

```bash
cd codigo/backend
npm install
cp .env.example .env  # editar con tu MAAS_API_KEY
```

### 3. Frontend

```bash
cd codigo/frontend
npm install
cp .env.local.example .env.local
```

---

## Ejecución

### Backend (puerto 3001)

```bash
cd codigo/backend
npm run start:dev
```

### Frontend (puerto 3000)

```bash
cd codigo/frontend
npm run dev
```

Abrir `http://localhost:3000` → ATLAS Control Room.

---

## Procesamiento por lote

### Ingestar el dataset de muestra

```bash
curl -X POST http://localhost:3001/api/tickets/ingest \
  -H "Content-Type: application/json" \
  -d @codigo/data/tickets_sample.json
```

O desde el frontend: el formulario "Probar ticket" ejecuta el pipeline síncrono.

### Clasificar síncronamente (demo)

```bash
curl -X POST http://localhost:3001/api/tickets/classify \
  -H "Content-Type: application/json" \
  -d @codigo/data/tickets_sample.json
```

### Ejecutar correlación

```bash
curl -X POST http://localhost:3001/api/control-room/correlate
```

---

## Tests

```bash
cd codigo/backend
npm test
```

Incluye:
- Tests de éxito (clasificación correcta de tickets)
- Tests de error (ticket malformado, GLM falla, timeout)
- Tests de schema (Zod validation)
- Tests adversariales (Bono A — prompt injection, secretos, texto largo)
- Tests de retries con backoff

---

## Apertura de la interfaz

1. Levantar backend: `cd codigo/backend && npm run start:dev`
2. Levantar frontend: `cd codigo/frontend && npm run dev`
3. Abrir `http://localhost:3000`

La interfaz muestra:
- Cola priorizada de tickets con datos reales del backend
- Filtros por prioridad y categoría
- Detalle completo de cada ticket
- Panel de incidentes con grupos correlacionados
- Formulario "Probar ticket" para clasificación manual
- Polling automático cada 5 segundos

---

## Validación de respuestas

- **Schema Zod** estricto con enums exactos (8 categorías, 4 prioridades, 3 sentimientos)
- `extractJson()` con 3 fallbacks: parse directo → regex de bloque JSON → markdown code block
- Respuestas inválidas → reintento → degradación con `requires_human_review=true`

---

## Política de retries

```
Intento 1 → falla → esperar 500ms
Intento 2 → falla → esperar 1500ms
Intento 3 → falla → degradar (category=Otro, confidence=0, requires_human_review=true)
```

Backoff exponencial: `delay = 500 * 3^(attempt-1)`. Máximo 3 intentos (configurable via `MAX_RETRIES`). No loops infinitos.

---

## Criterio de abstención

Si `confidence < 0.60` (configurable via `CONFIDENCE_THRESHOLD`):

```json
{ "requires_human_review": true }
```

---

## Estrategia de correlación

1. **Pre-filtro por reglas:** agrupa candidatos por (categoría + módulo + región) para reducir el espacio de búsqueda.
2. **GLM 5.2 para correlación semántica:** envía cada bucket de candidatos a GLM con un prompt que pregunta si los tickets describen el mismo incidente. GLM devuelve grupos + razones.
3. **Detección de incidente mayor:** ≥5 tickets P1/P2 + mismo grupo + ventana temporal → `major_incident_candidate=true`.
4. **Repriorización por blast radius:** si un incidente afecta ≥3 clientes y ≥2 regiones, la prioridad del incidente sube a P1 (sin modificar la prioridad individual de cada ticket).

---

## Bonos implementados

| Bono | Descripción | Estado |
|---|---|---|
| **A — Defensa adversarial (+8)** | Suite de 10 tickets maliciosos (prompt injection, JSON incrustado, texto largo, solicitud de secretos) + tests | ✅ |
| **B — Concurrencia (+8)** | Rate limiter p-limit (max 5), Kafka partitions, idempotency por ticket_id | ✅ |
| **C — Explicabilidad (+7)** | `GET /api/reports/tickets/:id` y `/api/reports/incidents/:id` con evidencia, decisión, factores, recomendación | ✅ |

---

## Seguridad

- ❌ No se suben API keys, tokens ni `.env` con secretos
- ✅ `.env.example` con valores vacíos
- ✅ `.gitignore` excluye `.env`
- ✅ Prompt injection defense: system prompt inmutable, datos delimitados, truncado a 5000 chars
- ✅ Audit log NUNCA registra secretos ni headers
- ✅ Salida validada con Zod — nunca se devuelven credenciales

---

## Estructura del proyecto

```
david-corredor-g1/
├── README.md                    # Este archivo
├── requerimientos.txt           # Dependencias
├── prompt_usado.txt             # Prompts utilizados con GLM 5.2
└── codigo/                      # Código fuente completo
    ├── frontend/                # Next.js 16 (v0.app design)
    ├── backend/                 # NestJS Screaming Architecture
    │   └── src/
    │       ├── tickets/         # Ingesta + persistencia
    │       ├── triage/          # GLM 5.2 + Zod + retries
    │       ├── correlation/     # Agrupación + incidente mayor
    │       ├── control-room/    # API + reportes
    │       ├── glm/             # Wrapper GLM 5.2
    │       ├── audit/           # Log auditable
    │       └── shared/          # Config, Kafka, logger, errors
    ├── data/                    # tickets_sample.json + tickets_adversarial.json
    ├── docs/                    # sesion_ia.md + schema.md
    └── docker-compose.yml       # Mongo + Kafka + UIs
```
