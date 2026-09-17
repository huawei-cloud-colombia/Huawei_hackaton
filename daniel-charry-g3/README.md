# 🎟️ NEXUS LIVE // T-80 — Solución del Equipo

## 🧑‍💻 Equipo

| Integrante | Rol |
|---|---|
| Daniel Charry | Líder de desarrollo |

**Rama:** `daniel-charry-g3`
**Reto:** [RETO 3 — NEXUS LIVE](../Retos/RETO_3_NEXUS_LIVE.md)

---

## 📖 Descripción

Este repositorio contiene la solución al **Reto 3: NEXUS LIVE**, cuyo objetivo es reconstruir un **motor de reservas de alta concurrencia** capaz de garantizar que un asiento nunca sea vendido a dos compradores diferentes.

El sistema soporta:

- ✅ Consulta de asientos disponibles.
- ✅ Creación de reservas temporales (`HOLD`).
- ✅ Expiración automática de reservas (TTL configurable).
- ✅ Confirmación de compras (`SOLD`).
- ✅ Reintentos seguros (idempotencia con `Idempotency-Key`).
- ✅ Concurrencia segura bajo alta carga (`asyncio.Lock`).
- ✅ Integración con proveedor de pagos inestable (mock + Circuit Breaker).
- ✅ Trazabilidad de transiciones de estado (audit log).
- ✅ Interfaz visual para simulación (NEXUS Control Room).

---

## 🏗️ Stack seleccionado

| Componente | Tecnología |
|---|---|
| **Lenguaje** | Python 3.11+ |
| **Framework** | FastAPI + Uvicorn (ASGI) |
| **Validación** | Pydantic v2 |
| **Concurrencia** | asyncio.Lock (mutex por operación atómica) |
| **Almacenamiento** | En memoria (dict) |
| **Pagos** | Mock con probabilidades configurables |
| **Resiliencia** | Circuit Breaker (CLOSED / OPEN / HALF_OPEN) |
| **Interfaz** | HTML + JavaScript (servida por FastAPI) |
| **Tests** | pytest + pytest-asyncio + httpx |

---

## 📂 Arquitectura y estructura del proyecto

```text
daniel-charry-g3/
├── README.md                  ← Este archivo
├── requerimientos.txt         ← Dependencias de Python
├── prompt_usado.txt           ← Bitácora de uso de GLM 5.2
└── codigo/
    ├── main.py                ← API FastAPI (endpoints + interfaz)
    ├── config.py              ← Configuración (TTL, límites, secciones)
    ├── models.py              ← Modelos Pydantic (Seat, Hold, enums)
    ├── seat_lock.py           ← Motor de reservas (concurrencia + idempotencia)
    ├── payment.py             ← Mock de pagos + Circuit Breaker
    ├── audit.py               ← Trazabilidad y auditoría
    ├── tests.py               ← Pruebas (escenarios A-F)
    └── static/
        └── index.html         ← Interfaz web NEXUS Control Room
```

### Flujo de una reserva

```text
Cliente → POST /api/reserve (Idempotency-Key)
    → SeatLockEngine.reserve()
        → Validar entrada (asientos existen, no duplicados)
        → Verificar disponibilidad (todo-o-nada)
        → Verificar límite por usuario (máx 6)
        → asyncio.Lock (operación atómica)
        → Crear HOLD + marcar asientos HELD
        → Registrar en audit log
    → Respuesta JSON con hold_id
```

---

## 🚀 Instalación

### Requisitos previos

- Python 3.11 o superior
- pip (gestor de paquetes de Python)

### Pasos

```bash
# 1. Entrar al directorio del código
cd daniel-charry-g3/codigo

# 2. (Recomendado) Crear entorno virtual
python -m venv venv

# 3. Activar entorno virtual
# En Windows:
venv\Scripts\activate
# En Linux/Mac:
source venv/bin/activate

# 4. Instalar dependencias
pip install -r ../requerimientos.txt
```

---

## ⚙️ Configuración

Todas las variables son opcionales (tienen valores por defecto). Se configuran mediante variables de entorno:

| Variable | Default | Descripción |
|---|---|---|
| `HOLD_TTL_SECONDS` | `120` | Tiempo de vida de una reserva (segundos) |
| `MAX_SEATS_PER_USER` | `6` | Máximo de asientos por usuario en reservas activas |
| `CURRENCY` | `COP` | Moneda del evento |
| `DEFAULT_EVENT_ID` | `aurora-bogota-2026` | ID del evento por defecto |
| `CB_FAILURE_THRESHOLD` | `3` | Fallos consecutivos para abrir el circuit breaker |
| `CB_RECOVERY_TIMEOUT` | `15` | Segundos antes de pasar a HALF_OPEN |
| `PAY_PROB_APPROVED` | `0.70` | Probabilidad de pago aprobado |
| `PAY_PROB_DECLINED` | `0.10` | Probabilidad de pago rechazado |
| `PAY_PROB_ERROR` | `0.10` | Probabilidad de error |
| `PAY_PROB_TIMEOUT` | `0.10` | Probabilidad de timeout |
| `PAY_TIMEOUT_SECONDS` | `2.0` | Umbral de timeout del proveedor |

**Ejemplo:**

```bash
# Windows (PowerShell)
$env:HOLD_TTL_SECONDS = "30"
$env:MAX_SEATS_PER_USER = "4"

# Linux/Mac
export HOLD_TTL_SECONDS=30
export MAX_SEATS_PER_USER=4
```

---

## ▶️ Ejecución

```bash
# Desde daniel-charry-g3/codigo/
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

O alternativamente:

```bash
python main.py
```

### Acceder a la aplicación

- **Interfaz web:** http://localhost:8000
- **Documentación API (Swagger):** http://localhost:8000/docs
- **API ReDoc:** http://localhost:8000/redoc

---

## 🧪 Ejecutar pruebas

```bash
# Desde daniel-charry-g3/codigo/
pytest tests.py -v
```

Las pruebas cubren los escenarios A-F del reto:

| Test | Escenario |
|---|---|
| `TestSeatLock` | A — Reserva normal, todo-o-nada, límites |
| `TestConcurrency` | C — Concurrencia (100 usuarios → 1 ganador) |
| `TestIdempotency` | D/E — Replay y conflicto de idempotencia |
| `TestPayment` | F — Aprobado, rechazado, timeout, doble confirmación |
| `TestCircuitBreaker` | F — Circuit breaker abre y bloquea |
| `TestAudit` | Trazabilidad de eventos |
| `TestExpiration` | B — Expiración automática |

---

## 🖥️ Cómo abrir la interfaz

1. Iniciar el servidor: `uvicorn main:app --port 8000`
2. Abrir en el navegador: **http://localhost:8000**

La interfaz permite:

- 🟢🟡🔴 Visualizar asientos con colores (AVAILABLE/HELD/SOLD)
- 🖱️ Seleccionar asientos y crear HOLD
- 📋 Ver información de la reserva (Hold ID, usuario, total, tiempo restante)
- 💳 Confirmar compra con payment_token
- ⚔️ Simular carrera de N usuarios por 1 asiento
- 🔌 Ver estado del Circuit Breaker
- 🧾 Ver trazabilidad de eventos
- ⚙️ Ver configuración y resetear el sistema

---

## ⚔️ Cómo simular concurrencia

### Desde la interfaz

1. Abrir http://localhost:8000
2. En el panel "Simular Carrera", ingresar el asiento (ej: `VIP-A-001`) y número de usuarios (ej: `20`)
3. Click en "Simular Carrera"
4. Ver resultado: `1 ganador, 19 rechazados`

### Desde la API

```bash
curl -X POST http://localhost:8000/api/simulate/race \
  -H "Content-Type: application/json" \
  -d '{"seat_id": "VIP-A-001", "num_users": 100}'
```

---

## 🔒 Estrategia de idempotencia

- Se usa el header `Idempotency-Key` en `POST /api/reserve`.
- Se calcula un hash SHA-256 del payload normalizado.
- **Misma clave + mismo payload** → retorna el mismo resultado cacheado (no crea otro HOLD).
- **Misma clave + payload diferente** → retorna `IDEMPOTENCY_CONFLICT`.
- El cache se mantiene en memoria por la duración de la sesión.

---

## 🛡️ Estrategia para evitar overselling

- **`asyncio.Lock` global** durante la operación atómica de reserva.
- El lock protege la validación de disponibilidad **y** el marcado de asientos como HELD en una sola sección crítica.
- Esto garantiza que 100 solicitudes concurrentes sobre 1 asiento produzcan **exactamente 1 ganador**.
- Reserva **todo-o-nada**: si un asiento no está disponible, no se reserva ninguno.

---

## ⏰ Manejo de expiración de HOLDs

- Cada HOLD tiene un `expires_at` = `created_at + TTL`.
- Un **background task** ejecuta `expire_holds()` cada 1 segundo.
- Al expirar: `HELD → AVAILABLE` (si no fue vendido).
- El TTL es configurable via `HOLD_TTL_SECONDS`.

---

## 💳 Estrategia ante fallos del proveedor de pagos

| Resultado | Acción |
|---|---|
| `APPROVED` | `HELD → SOLD`, compra confirmada |
| `DECLINED` | `HELD → AVAILABLE`, asientos liberados inmediatamente |
| `ERROR` | HOLD se mantiene, no se libera (operación ambigua) |
| `TIMEOUT` | HOLD se mantiene, no se libera (operación ambigua) |

**Circuit Breaker:**

- 3 fallos consecutivos → `OPEN` (no se llama al proveedor)
- 15 segundos → `HALF_OPEN` (1 llamada de prueba)
- Si funciona → `CLOSED`; si falla → `OPEN`
- En `OPEN`, las confirmaciones reciben `PAYMENT_SERVICE_UNAVAILABLE` y el asiento **NO** se marca como `SOLD`.

---

## 🧾 Trazabilidad

Cada cambio de estado se registra en el audit log con:

- `user_id`, `hold_id`, `seat_id`
- `from_state`, `to_state`
- `reason` (hold_created, hold_expired, payment_approved, etc.)
- `timestamp`

Endpoints: `GET /api/audit`, `GET /api/audit/{hold_id}`, `GET /api/audit/export`

---

## 📋 Fases del reto

| Fase | Descripción | Estado |
|---|---|---|
| **Fase 1** | SeatLock: reservas temporales y estados | ✅ Implementado |
| **Fase 2** | Idempotencia y concurrencia segura | ✅ Implementado |
| **Fase 3** | Confirmación, pagos y resiliencia | ✅ Implementado |
| **Fase 4** | Interfaz visual y simulación | ✅ Implementado |

---

## 🤖 Bitácora de uso de GLM 5.2

Ver archivo [`prompt_usado.txt`](prompt_usado.txt) para el registro completo de prompts usados durante el desarrollo.

---

## 📝 Notas

- Tiempo total disponible: **80 minutos**
- Apertura de venta: **10:00:00**
- Usuarios en sala de espera: **180.000**
- Asientos disponibles: **42.000**
- Bonos implementados: Ninguno (los 4 fases base están completas al 100%)
