# NEXUS LIVE // T-80 — Guía de Desarrollo para el Rol Desarrollador

> **Reto:** RETO_3_NEXUS_LIVE — Motor de Reservas de Alta Concurrencia
> **Equipo:** Samuel Ardila — Grupo 3
> **Stack:** Python 3.11 · Flask · SQLite (WAL) · HTML · CSS · JavaScript (vanilla)
> **Agente de desarrollo:** GLM 5.2

---

## 0. Resumen ejecutivo

Construir un motor de reservas de entradas que garantice la transición
`AVAILABLE → HELD → SOLD` sin overselling, resistiendo concurrencia,
reintentos y un proveedor de pagos inestable, todo demostrable desde
una interfaz gráfica que los jueces pueden usar sin herramientas externas.

### Decisiones de arquitectura del equipo

| Decisión | Elección | Justificación |
|---|---|---|
| Lenguaje / framework | Python 3.11 + Flask | Sencillo, rápido de levantar, suficiente para el reto |
| Persistencia | SQLite en modo WAL | Transacciones `BEGIN IMMEDIATE` para locking a nivel de escritura; cero configuración |
| Concurrencia | **Cola de sesiones (máx. 50 concurrentes)** + pool de hilos | Evita que el sistema se degrade por sobreconsumo; 50 es el punto dulce calibrado |
| Double-booking | Transacción `BEGIN IMMEDIATE` + verificación atómica de estado | SQLite serializa escrituras; garantiza un único ganador |
| Idempotencia | Tabla `idempotency_keys` (clave + hash de payload) | Replay devuelve el mismo resultado; payload distinto = conflicto |
| Pago | **Servicio dummy local** con escenarios seleccionables | APPROVED / DECLINED / ERROR / TIMEOUT / RECURRENCE |
| Resiliencia | Circuit Breaker (CLOSED / OPEN / HALF_OPEN) | 3 fallos → OPEN → 15 s → HALF_OPEN → 1 prueba |
| Trazabilidad | Tabla `audit_log` + endpoint de exportación | Reconstruye la vida completa de una reserva |
| Interfaz | HTML + CSS + JS vanilla servido por Flask | Sin build step; los jueces abren el navegador y prueban |
| Recurrencia | Escenario de pago recurrente (suscripción/cuotas) | Simula cobros periódicos sobre una reserva confirmada |

---

## 1. Estructura del proyecto

```text
samuel-ardila-g3/
├── README.md                  # Instrucciones de instalación y ejecución
├── requerimientos.txt         # Dependencias (pip freeze)
├── prompt_usado.txt           # Bitácora de prompts GLM 5.2
├── desarrollar.md             # Este documento (guía paso a paso)
├── docs/
│   └── sesion_ia.md           # Bitácora de uso de GLM 5.2
└── codigo/
    ├── app.py                 # Entry point Flask + registro de rutas
    ├── config.py              # Configuración central (TTL, límites, cola, CB)
    ├── db.py                  # Conexión SQLite (WAL), init_schema, helpers
    ├── circuit_breaker.py     # Implementación del Circuit Breaker
    ├── payment_mock.py        # Servicio dummy de pago con escenarios
    ├── services/
    │   ├── __init__.py
    │   ├── seat_service.py    # Consulta y gestión de asientos
    │   ├── hold_service.py    # Crear/consultar/liberar/expirar HOLDs
    │   ├── payment_service.py # Confirmación + integración con payment_mock + CB
    │   ├── queue_service.py   # Cola de concurrencia (máx. 50 sesiones)
    │   ├── idempotency_service.py  # Gestión de Idempotency-Key
    │   ├── audit_service.py   # Trazabilidad / audit_log
    │   └── recurrence_service.py   # Pagos recurrentes (suscripción/cuotas)
    ├── templates/
    │   └── index.html         # NEXUS Control Room (UI)
    ├── static/
    │   ├── style.css          # Estilos (semáforo de asientos)
    │   └── app.js             # Lógica de UI (selección, hold, pago, carrera)
    └── tests/
        ├── conftest.py        # Fixtures (DB temporal, cliente Flask)
        ├── test_fase1_seatlock.py
        ├── test_fase2_concurrencia.py
        ├── test_fase2_idempotencia.py
        ├── test_fase3_pago.py
        ├── test_fase3_circuit_breaker.py
        ├── test_trazabilidad.py
        ├── test_recurrencia.py
        └── test_casos_limite.py
```

---

## 2. Configuración inicial

### 2.1 Entorno virtual y dependencias

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install flask
pip freeze > samuel-ardila-g3/requerimientos.txt
```

`requerimientos.txt` mínimo:

```text
flask==3.0.*
```

> No se requieren librerías externas para SQLite, colas ni circuit breaker
> (todo usa la biblioteca estándar: `sqlite3`, `queue`, `threading`, `concurrent.futures`).

### 2.2 `config.py` — parámetros configurables

```python
HOLD_TTL_SECONDS = 120          # Expiración de HOLD (reducible para demo)
MAX_SEATS_PER_USER = 6          # Límite de asientos por usuario
QUEUE_MAX_CONCURRENT = 50       # Punto dulce: sesiones concurrentes
QUEUE_TIMEOUT_SECONDS = 30      # Tiempo máximo en cola antes de rechazar
CB_FAILURE_THRESHOLD = 3        # Fallos consecutivos → OPEN
CB_RECOVERY_SECONDS = 15        # Espera antes de HALF_OPEN
CB_HALF_OPEN_TRIALS = 1         # Llamadas de prueba en HALF_OPEN
PAYMENT_TIMEOUT_SECONDS = 2     # Umbral de timeout del proveedor
DB_PATH = "nexus.db"
EVENT_ID = "aurora-bogota-2026"
CURRENCY = "COP"
```

### 2.3 `db.py` — SQLite en modo WAL

```python
def get_connection():
    conn = sqlite3.connect(config.DB_PATH, timeout=5, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
```

Esquema (tablas):

| Tabla | Columnas |
|---|---|
| `seats` | `seat_id PK, section, price, currency, status, version` |
| `holds` | `hold_id PK, user_id, event_id, status, total, currency, created_at, expires_at` |
| `hold_seats` | `hold_id FK, seat_id FK` (relación N:M) |
| `idempotency_keys` | `key PK, payload_hash, hold_id, response_json, created_at` |
| `audit_log` | `id PK, hold_id, seat_id, from_state, to_state, reason, timestamp` |
| `payments` | `payment_id PK, hold_id, token, scenario, result, amount, created_at` |
| `recurrences` | `recurrence_id PK, hold_id, interval_days, next_charge_at, status, installments_total, installments_paid` |

> La columna `version` en `seats` habilita **optimistic locking** como capa
> adicional; la garantía principal viene de `BEGIN IMMEDIATE`.

---

## 3. FASE 1 — SeatLock: reservas temporales

### 3.1 Modelo de asiento

```
seat_id   : str   (ej. "A-101", "VIP-A-001")
section   : str   (ej. "GENERAL", "VIP")
price     : int   (entero en COP; el servidor calcula el total)
currency  : str   ("COP")
status    : enum  (AVAILABLE | HELD | SOLD)
version   : int   (optimistic lock)
```

### 3.2 Modelo de HOLD

```
hold_id    : str   (ej. "hold_8B72A")
user_id    : str
event_id   : str
seat_ids   : list[str]
created_at : datetime
expires_at : datetime
status     : enum  (HELD | EXPIRED | RELEASED | SOLD)
total      : int   (calculado por el servidor)
currency   : str
```

### 3.3 Endpoints (Flask)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/seats` | Consultar asientos (opcional `?section=`) |
| `POST` | `/api/holds` | Crear un HOLD (todo-o-nada) |
| `GET` | `/api/holds/<hold_id>` | Consultar un HOLD |
| `DELETE` | `/api/holds/<hold_id>` | Liberar un HOLD (HELD → AVAILABLE) |
| `POST` | `/api/holds/expire` | Forzar expiración (uso interno / demo) |

### 3.4 Reglas obligatorias — implementación

1. **Todo o nada:** Dentro de una transacción `BEGIN IMMEDIATE`, verificar
   que **todos** los `seat_ids` están `AVAILABLE`. Si alguno no lo está,
   hacer `ROLLBACK` y devolver `REJECTED` con `reason = seat_not_available`.
   Nunca reservar parcialmente.

2. **Expiración automática:** Un hilo demonio (`hold_service.expiry_worker`)
   recorre cada `HOLD_TTL_SECONDS / 4` los HOLDs con `expires_at < now()`
   y `status = HELD`, los marca `EXPIRED` y libera los asientos a `AVAILABLE`.
   El TTL es configurable; la UI permite reducirlo para la demo (ej. 10 s).

3. **Límite de asientos por usuario:** Antes de crear un HOLD, contar los
   asientos en HOLDs activos del `user_id`. Si `existentes + nuevos > MAX_SEATS_PER_USER`,
   rechazar con `reason = seat_limit_exceeded`.

4. **Precio controlado por el servidor:** El cliente **no** envía el precio.
   `hold_service` suma `price` de la tabla `seats` para los `seat_ids`
   solicitados. El `total` se almacena en `holds.total`.

5. **Estados válidos:** Las transiciones solo ocurren dentro de
   `hold_service`, `payment_service` y `hold_service.release`. No hay
   endpoint directo para cambiar `status` arbitrariamente.

### 3.5 Transiciones permitidas

```text
AVAILABLE ──create_hold──▶ HELD
HELD ──release/expire──▶ AVAILABLE
HELD ──payment_approved──▶ SOLD
```

Cualquier otra transición debe rechazarse y registrarse en `audit_log`.

---

## 4. FASE 2 — Concurrencia segura e idempotencia

### 4.1 Cola de concurrencia (punto dulce = 50 sesiones)

**Objetivo:** evitar que el motor se degrade por sobreconsumo. En lugar de
procesar cada petición inmediatamente, todas pasan por una cola que permite
como máximo `QUEUE_MAX_CONCURRENT = 50` sesiones activas simultáneas.

**Implementación — `queue_service.py`:**

```python
import queue, threading
from concurrent.futures import ThreadPoolExecutor

class SessionQueue:
    def __init__(self, max_concurrent=50):
        self._pool = ThreadPoolExecutor(
            max_workers=max_concurrent,
            thread_name_prefix="nexus-worker"
        )
        self._semaphore = threading.BoundedSemaphore(max_concurrent)
        self._max = max_concurrent

    def submit(self, fn, *args, **kwargs):
        # Si hay 50 sesiones activas, la petición espera en la cola.
        # Si excede QUEUE_TIMEOUT_SECONDS → 503 SERVICE_BUSY.
        return self._pool.submit(fn, *args, **kwargs)

    def stats(self):
        return {
            "max_concurrent": self._max,
            "active": self._max - self._semaphore._value,
            "queued": ...,
        }
```

**Flujo de una petición:**

```text
Cliente → Flask route → queue_service.submit(procesar) → [cola ≤50]
   → BEGIN IMMEDIATE → verificar asientos → commit/rollback → respuesta
```

- Si hay < 50 sesiones activas → procesa inmediatamente.
- Si hay 50 activas → la petición espera en la cola hasta `QUEUE_TIMEOUT_SECONDS`.
- Si expira el timeout → `503 SERVICE_BUSY` (la cola protege el sistema).
- Endpoint `GET /api/queue/stats` expone sesiones activas / en cola para la UI.

**Por qué 50:** es el punto dulce calibrado donde SQLite WAL + transacciones
`IMMEDIATE` mantienen throughput sin degradación. Por encima de 50, el
contencio de locks degrada el rendimiento; por debajo, se subutiliza.

### 4.2 Double-booking — garantía de un único ganador

```python
def create_hold(user_id, event_id, seat_ids):
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")          # lock de escritura inmediato
        # 1. Verificar que TODOS los asientos están AVAILABLE
        placeholders = ",".join("?" * len(seat_ids))
        rows = conn.execute(
            f"SELECT seat_id, status FROM seats WHERE seat_id IN ({placeholders})",
            seat_ids
        ).fetchall()
        if len(rows) != len(seat_ids):
            return reject("seat_not_found")
        if any(r[1] != "AVAILABLE" for r in rows):
            return reject("seat_not_available")  # todo-o-nada
        # 2. Verificar límite por usuario
        # 3. Calcular total desde el servidor
        # 4. Crear HOLD + marcar asientos HELD + audit_log
        conn.execute("COMMIT")
        return hold
    except Exception:
        conn.execute("ROLLBACK")
        raise
```

`BEGIN IMMEDIATE` adquiere el lock de escritura de SQLite **antes** de
cualquier lectura. Si dos hilos intentan reservar el mismo asiento, el
segundo bloquea hasta que el primero haga `COMMIT`/`ROLLBACK`; al
re-ejecutar, el asiento ya está `HELD` → rechazado. **Garantiza exactamente
un ganador.**

### 4.3 Idempotencia

**Mecanismo:** cabecera `Idempotency-Key` + hash del payload.

```text
POST /api/holds
Idempotency-Key: reserve-usr10482-001
```

**Lógica — `idempotency_service.py`:**

1. Calcular `payload_hash = sha256(json.dumps(payload, sort_keys=True))`.
2. `SELECT` la clave en `idempotency_keys`:
   - **No existe** → procesar la operación, guardar `(key, payload_hash, hold_id, response)`.
   - **Existe y `payload_hash` coincide** → devolver la `response` almacenada (replay).
   - **Existe y `payload_hash` difiere** → `409 IDEMPOTENCY_CONFLICT`.

Esto cubre:
- **Reintento seguro** (mismo key + mismo payload → mismo `hold_id`).
- **Conflicto** (mismo key + payload distinto → `IDEMPOTENCY_CONFLICT`).

### 4.4 Prueba clave — carrera por el último asiento

```text
100 usuarios → VIP-A-001 (1 asiento) → 1 HOLD exitoso + 99 rechazados + 0 overselling
```

La UI tiene un botón **"SIMULAR CARRERA"** que lanza N solicitudes
concurrentes (configurable, por defecto 20) sobre un asiento y muestra
el conteo de ganadores / rechazados.

---

## 5. FASE 3 — Confirmación y proveedor de pagos inestable

### 5.1 Servicio dummy de pago — `payment_mock.py`

Servicio local que simula los escenarios del proveedor. **El escenario puede
seleccionarse explícitamente** desde la UI (debajo del botón Pagar) o
dejarse en `AUTO` para comportamiento aleatorio.

```python
def mock_payment_authorize(amount, currency, token, scenario="AUTO"):
    """
    Escenarios:
      APPROVED    → pago aprobado inmediatamente
      DECLINED    → pago rechazado por el proveedor
      ERROR        → el proveedor devuelve un error (500)
      TIMEOUT      → el proveedor tarda > 2 s (latencia extrema)
      RECURRENCE   → primer cargo aprobado; marca para cobros periódicos
      AUTO         → 70% approved, 10% declined, 10% error, 10% timeout
    """
```

| Escenario | Resultado | Latencia | Uso |
|---|---|---|---|
| `APPROVED` | `{"result": "APPROVED", "auth_code": "..."}` | ~100 ms | Flujo normal |
| `DECLINED` | `{"result": "DECLINED", "reason": "insufficient_funds"}` | ~100 ms | Pago rechazado |
| `ERROR` | `{"result": "ERROR", "reason": "provider_500"}` | ~100 ms | Error ambiguo |
| `TIMEOUT` | (no responde dentro de 2 s) | > 2 s | Timeout ambiguo |
| `RECURRENCE` | `{"result": "APPROVED", "recurring": true, ...}` | ~150 ms | Pago recurrente |
| `AUTO` | distribución probabilística | variable | Comportamiento realista |

### 5.2 Selector de escenario en la UI

Debajo del botón **"PAGAR"** hay un `<select>`:

```html
<label for="scenario">Escenario de pago:</label>
<select id="scenario">
  <option value="AUTO">Automático (realista)</option>
  <option value="APPROVED">Aprobado</option>
  <option value="DECLINED">Rechazado</option>
  <option value="ERROR">Error del proveedor</option>
  <option value="TIMEOUT">Timeout (>2s)</option>
  <option value="RECURRENCE">Pago recurrente (cuotas)</option>
</select>
<button id="btn-pay">PAGAR</button>
```

El valor seleccionado se envía en el body del `POST /api/holds/<hold_id>/confirm`.
Esto permite a los jueces demostrar **cada escenario a demanda**.

### 5.3 Operación de confirmación

```text
POST /api/holds/<hold_id>/confirm
Body: { "payment_token": "tok_test_91827", "scenario": "APPROVED" }
```

**Flujo:**

```text
1. Recuperar HOLD → validar que exista y status = HELD
2. Validar que no esté expirado (expires_at > now)
3. Circuit breaker.allow_request()?  → si OPEN: 503 PAYMENT_SERVICE_UNAVAILABLE
4. Llamar mock_payment_authorize(amount, ..., scenario)
5. Según resultado:
     APPROVED  → HELD→SOLD, crear confirmación, audit, (si recurring → crear recurrencia)
     DECLINED  → liberar HOLD (HELD→AVAILABLE), audit reason=payment_declined
     ERROR     → NO liberar; marcar pago como pending_retry; audit reason=payment_error
     TIMEOUT   → NO liberar; marcar pago como pending_retry; audit reason=payment_timeout
6. Registrar resultado en payments + audit_log
7. Actualizar circuit breaker (success/failure)
```

### 5.4 Reglas de consistencia

| Resultado | Acción sobre el HOLD | Acción sobre el asiento | ¿Vendido? |
|---|---|---|---|
| `APPROVED` | `HELD → SOLD` | `HELD → SOLD` | Sí |
| `DECLINED` | `HELD → RELEASED` | `HELD → AVAILABLE` | No |
| `ERROR` | Mantiene `HELD` (pendiente de reintento) | Mantiene `HELD` | No |
| `TIMEOUT` | Mantiene `HELD` (pendiente de reintento) | Mantiene `HELD` | No |

**Estrategia para ERROR/TIMEOUT:** Un timeout **no** significa rechazo. El
HOLD se mantiene activo (dentro de su TTL) y el pago queda en
`pending_retry`. El usuario puede reintentar la confirmación. Si el HOLD
expira mientras hay un pago pendiente, se libera el asiento y se registra
en `audit_log` con `reason = hold_expired_with_pending_payment`. Esto evita:
- vender sin certeza;
- duplicar cobros (idempotencia en la confirmación);
- liberar un asiento incoherentemente.

### 5.5 Circuit Breaker — `circuit_breaker.py`

```text
Estados: CLOSED → OPEN → HALF_OPEN → CLOSED/OPEN

CLOSED:    las llamadas pasan normalmente.
           Si 3 fallos consecutivos → OPEN.
OPEN:      no se llama al proveedor; las confirmaciones reciben
           503 PAYMENT_SERVICE_UNAVAILABLE. El asiento NO se marca SOLD.
           Tras 15 s → HALF_OPEN.
HALF_OPEN: se permite 1 llamada de prueba.
           Si funciona → CLOSED (contador de fallos reseteado).
           Si falla → OPEN (timer reiniciado).
```

Implementación thread-safe con `threading.Lock`. El estado se expone en
`GET /api/circuit-breaker` para que la UI lo muestre en tiempo real.

---

## 6. Trazabilidad — `audit_service.py`

Cada transición de estado genera un registro en `audit_log`:

```json
{
  "hold_id": "hold_8B72A",
  "seat_id": "A-101",
  "from_state": "HELD",
  "to_state": "SOLD",
  "reason": "payment_approved",
  "timestamp": "2026-09-16T14:51:07Z"
}
```

**Razones registradas:** `hold_created`, `hold_released`, `hold_expired`,
`payment_approved`, `payment_declined`, `payment_error`, `payment_timeout`,
`circuit_breaker_open`, `circuit_breaker_recovered`, `recurrence_charged`,
`idempotency_replay`, `idempotency_conflict`.

**Endpoints:**

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/audit/<hold_id>` | Historial completo de una reserva |
| `GET` | `/api/audit` | Historial global (paginado) |
| `GET` | `/api/audit/<hold_id>/export` | Exportar trazabilidad (JSON descargable) |

La UI muestra el historial de la reserva seleccionada en un panel lateral,
permitiendo reconstruir: `AVAILABLE → HELD → PAYMENT_ATTEMPT →
PAYMENT_APPROVED → SOLD`.

---

## 7. Recurrencia — `recurrence_service.py`

**Objetivo:** simular pagos recurrentes (suscripción / pago en cuotas) sobre
una reserva confirmada.

### 7.1 Modelo

```text
recurrences:
  recurrence_id   : str
  hold_id         : str (FK)
  interval_days   : int   (ej. 30)
  next_charge_at  : datetime
  status          : enum (ACTIVE | COMPLETED | FAILED)
  installments_total : int   (ej. 3 cuotas)
  installments_paid  : int   (contador)
```

### 7.2 Flujo

1. Al confirmar con `scenario = RECURRENCE`, el primer cargo se aprueba y
   se crea un registro en `recurrences` con `installments_total` (ej. 3),
   `installments_paid = 1` y `next_charge_at = now + interval_days`.
2. Un hilo demonio (`recurrence_worker`) simula el paso del tiempo:
   cuando `next_charge_at <= now`, ejecuta `mock_payment_authorize` para
   la siguiente cuota, incrementa `installments_paid` y registra en
   `audit_log` con `reason = recurrence_charged`.
3. Si una cuota falla, marca `status = FAILED` y lo registra.
4. La UI permite **acelerar la recurrencia** (botón "Simular siguiente cuota")
   para que los jueces vean el ciclo completo en segundos.

### 7.3 Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/recurrences/<hold_id>` | Estado de la recurrencia |
| `POST` | `/api/recurrences/<hold_id>/charge` | Forzar siguiente cuota (demo) |

---

## 8. FASE 4 — NEXUS Control Room (Interfaz)

### 8.1 Requisitos de la UI

| # | Requisito | Implementación |
|---|---|---|
| 1 | Visualizar asientos | Mapa de asientos con colores: 🟢 AVAILABLE, 🟡 HELD, 🔴 SOLD |
| 2 | Seleccionar asientos | Click multi-selección; contador de seleccionados |
| 3 | Crear HOLD | Botón "RESERVAR" → muestra hold_id, usuario, asientos, total, tiempo restante, estado |
| 4 | Confirmar compra | Botón "PAGAR" + input de payment_token + **selector de escenario** debajo |
| 5 | Simular carrera | Botón "SIMULAR CARRERA" con input de N usuarios → muestra N solicitudes, 1 ganador, N-1 rechazadas |
| 6 | Acceso de jueces | La UI es la puerta de entrada; no requiere curl/Postman/JSON |

### 8.2 Elementos adicionales para jueces

- **Configuración de TTL** (slider): permite reducir el TTL a 10 s para
  demostrar expiración rápida (Escenario B).
- **Panel de cola:** muestra sesiones activas / en cola / máximo (50).
- **Estado del Circuit Breaker:** badge CLOSED / OPEN / HALF_OPEN en vivo.
- **Panel de trazabilidad:** historial de la reserva seleccionada.
- **Panel de recurrencia:** cuotas pagadas / pendientes, botón "Simular siguiente cuota".
- **Selector de usuario:** los jueces pueden cambiar el `user_id` para
  simular múltiples compradores.
- **Botón "SIMULAR UNA RESERVA":** flujo guiado de un clic que crea un HOLD
  sobre asientos libres, muestra la información y deja listo el paso de pago.
  Esto permite a un juez demostrar una reserva completa sin conocimiento técnico.

### 8.3 Layout conceptual

```text
┌─────────────────────────────────────────────────────────┐
│  NEXUS CONTROL ROOM          Cola: 3/50   CB: CLOSED    │
├──────────────────────┬──────────────────────────────────┤
│  MAPA DE ASIENTOS    │  INFO DE LA RESERVA              │
│  🟢🟢🟡🔴🟢🟢        │  Hold ID: hold_8B72A             │
│  🟢🟡🟢🟢🟢🟢        │  Usuario: usr_10482              │
│  ...                 │  Asientos: A-101, A-102          │
│                      │  Total: 420.000 COP              │
│  Seleccionados: 2    │  Tiempo restante: 01:58          │
│  [ RESERVAR ]        │  Estado: HELD                    │
│                      │                                  │
│                      │  Payment token: [tok_test_... ]  │
│                      │  Escenario: [APPROVED ▼]         │
│                      │  [ PAGAR ]                       │
│                      │                                  │
│                      │  [ SIMULAR CARRERA (20 users) ]  │
│                      │  [ SIMULAR UNA RESERVA ]         │
├──────────────────────┴──────────────────────────────────┤
│  TRAZABILIDAD              │  RECURRENCIA                 │
│  AVAILABLE→HELD→SOLD       │  Cuota 1/3 ✓                 │
│  ...                       │  [ Simular siguiente cuota ] │
└────────────────────────────┴─────────────────────────────┘
```

### 8.4 Endpoints de la UI

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/` | Sirve `index.html` (Control Room) |
| `GET` | `/api/queue/stats` | Estado de la cola (activos / en cola / máx) |
| `GET` | `/api/circuit-breaker` | Estado del CB |
| `POST` | `/api/simulate/race` | Lanza N solicitudes concurrentes sobre un asiento |

---

## 9. Escenarios que el jurado debe poder verificar (A–F)

| Escenario | Descripción | Cómo demostrarlo en la UI |
|---|---|---|
| **A — Reserva normal** | AVAILABLE → HOLD → Pago APPROVED → SOLD | Seleccionar asiento → RESERVAR → escenario APPROVED → PAGAR |
| **B — Reserva expirada** | HOLD → esperar TTL → AVAILABLE | Reducir TTL a 10 s con el slider → RESERVAR → no pagar → esperar → ver asiento verde |
| **C — Concurrencia** | 20+ solicitudes sobre 1 asiento → 1 HOLD | Botón SIMULAR CARRERA con N=20 |
| **D — Reintento** | Mismo Idempotency-Key + mismo payload → mismo hold_id | Repetir RESERVAR con la misma clave (la UI la fija) |
| **E — Conflicto** | Mismo Idempotency-Key + payload distinto → IDEMPOTENCY_CONFLICT | Cambiar asientos con la misma clave → ver error 409 |
| **F — Pago degradado** | Proveedor falla → CB OPEN → sistema responde → asiento no SOLD | Seleccionar ERROR/TIMEOUT repetidamente → ver CB OPEN → intentar PAGAR → ver 503 |

---

## 10. Bonos

### Bono A — Sala de espera justa (cola) — **implementado**

La **cola de 50 sesiones** (Sección 4.1) cubre este bono:

- **Orden de atención:** FIFO (la cola preserva el orden de llegada).
- **Criterio de fairness:** un usuario no puede monopolizar reservas porque
  el límite de 6 asientos por usuario se valida antes de entrar al motor,
  y la cola procesa en orden de llegada.
- **Evita monopolización:** combinación de cola FIFO + límite por usuario.
- **Usuario abandona:** si la petición excede `QUEUE_TIMEOUT_SECONDS`
  en cola, se rechaza con `503 SERVICE_BUSY` y se libera el slot.

### Bono B — Prueba de concurrencia real — **implementado**

`tests/test_fase2_concurrencia.py` usa `concurrent.futures.ThreadPoolExecutor`
con 100 hilos golpeando el mismo asiento y verifica:

```text
1 HOLD exitoso + 99 rechazadas + 0 overselling
```

### Bono C — Registro de auditoría reproducible — **implementado**

La tabla `audit_log` + endpoint `/api/audit/<hold_id>/export` permite
reconstruir y exportar la vida completa de una reserva (Sección 6).

### Bono D — GLM 5.2 dentro del producto — **opcional**

Módulo que recibe el historial de `audit_log` de una reserva y genera una
explicación operacional estructurada. Maneja timeout, respuesta vacía,
error de API y formato inesperado. **Se implementa si el tiempo lo permite.**

---

## 11. Tests

### 11.1 Comandos

```bash
cd samuel-ardila-g3\codigo
python -m pytest tests/ -v
```

### 11.2 Cobertura de tests

| Archivo | Qué verifica |
|---|---|
| `test_fase1_seatlock.py` | Crear HOLD, todo-o-nada, TTL, límite de 6, precio del servidor, liberar HOLD |
| `test_fase2_concurrencia.py` | 100 hilos → 1 asiento → 1 ganador, 0 overselling |
| `test_fase2_idempotencia.py` | Replay devuelve mismo hold_id; conflicto con payload distinto |
| `test_fase3_pago.py` | APPROVED→SOLD, DECLINED→libera, ERROR/TIMEOUT→mantiene HOLD |
| `test_fase3_circuit_breaker.py` | 3 fallos→OPEN, 15 s→HALF_OPEN, prueba ok→CLOSED, prueba fail→OPEN |
| `test_trazabilidad.py` | Cada transición genera audit_log; exportación reproducible |
| `test_recurrencia.py` | Crear recurrencia, cobrar cuotas, completar, fallar |
| `test_casos_limite.py` | Ver Sección 12 |

---

## 12. Casos límite

| Caso | Comportamiento esperado |
|---|---|
| `seat_ids` vacío | `400 BAD_REQUEST` — reason `empty_seat_list` |
| Asiento inexistente | `404 NOT_FOUND` — reason `seat_not_found` |
| Asiento duplicado en la solicitud | `400 BAD_REQUEST` — reason `duplicate_seat` |
| Usuario inexistente o vacío | `400 BAD_REQUEST` — reason `invalid_user` |
| HOLD ya expirado | `409 CONFLICT` — reason `hold_expired` |
| Confirmar dos veces el mismo HOLD | `409 CONFLICT` — reason `hold_already_sold` o `hold_already_confirmed` |
| Confirmar un HOLD ya vendido | `409 CONFLICT` — reason `hold_already_sold` |
| `payment_token` vacío | `400 BAD_REQUEST` — reason `empty_payment_token` |
| Solicitud simultánea durante expiración | La transacción `IMMEDIATE` serializa; un solo resultado |
| Reintento después de timeout | Idempotency-Key devuelve el mismo resultado lógico |
| Asientos superan el límite | `409 CONFLICT` — reason `seat_limit_exceeded` |
| Mismo asiento por múltiples usuarios | 1 ganador, resto `seat_not_available` |
| Mismo usuario con varios HOLD activos | Permitido mientras total de asientos ≤ 6 |
| Proveedor de pagos lento | Timeout a 2 s; HOLD se mantiene |
| Proveedor completamente caído | Circuit Breaker OPEN → `503 PAYMENT_SERVICE_UNAVAILABLE` |

---

## 13. Plan de ejecución paso a paso (rol desarrollador)

> Cada paso es un commit atómico. Verificar con tests antes de avanzar.

### Paso 1 — Scaffold y configuración (0–8 min)

- [ ] Crear `config.py` con todos los parámetros.
- [ ] Crear `db.py` con `get_connection()` (WAL) e `init_schema()` (todas las tablas).
- [ ] Crear `app.py` con Flask app vacía y `if __name__ == "__main__"`.
- [ ] Sembrar asientos de prueba (secciones GENERAL y VIP).
- [ ] Verificar: `python app.py` levanta sin errores; `/api/seats` devuelve asientos.

### Paso 2 — FASE 1: Motor de asientos y HOLDs (8–28 min)

- [ ] `seat_service.py`: `get_seats(section=None)`.
- [ ] `hold_service.py`: `create_hold(user_id, event_id, seat_ids)` con `BEGIN IMMEDIATE`, todo-o-nada, límite de 6, precio del servidor.
- [ ] `hold_service.py`: `get_hold(hold_id)`, `release_hold(hold_id)`.
- [ ] `hold_service.py`: hilo demonio `expiry_worker` para expiración automática.
- [ ] `audit_service.py`: `log_transition(hold_id, seat_id, from_state, to_state, reason)`.
- [ ] Rutas Flask: `GET /api/seats`, `POST /api/holds`, `GET /api/holds/<id>`, `DELETE /api/holds/<id>`.
- [ ] Tests `test_fase1_seatlock.py`.
- [ ] Verificar Escenario A (reserva normal) con curl.

### Paso 3 — FASE 2: Cola, concurrencia e idempotencia (28–46 min)

- [ ] `queue_service.py`: `SessionQueue(max_concurrent=50)` con `ThreadPoolExecutor`.
- [ ] Envolver todas las rutas de mutación con `queue_service.submit()`.
- [ ] Ruta `GET /api/queue/stats`.
- [ ] `idempotency_service.py`: guardar/verificar `Idempotency-Key` + `payload_hash`.
- [ ] Integrar idempotencia en `POST /api/holds` (replay y conflicto).
- [ ] Ruta `POST /api/simulate/race` (N solicitudes concurrentes).
- [ ] Tests `test_fase2_concurrencia.py` (100 hilos → 1 ganador).
- [ ] Tests `test_fase2_idempotencia.py` (replay + conflicto).
- [ ] Verificar Escenarios C, D, E.

### Paso 4 — FASE 3: Pago, circuit breaker y recurrencia (46–62 min)

- [ ] `payment_mock.py`: `mock_payment_authorize(amount, currency, token, scenario)` con todos los escenarios.
- [ ] `circuit_breaker.py`: `CircuitBreaker(threshold=3, recovery=15)`.
- [ ] `payment_service.py`: `confirm_hold(hold_id, token, scenario)` integrando mock + CB + reglas de consistencia.
- [ ] Ruta `POST /api/holds/<id>/confirm` con `scenario` en el body.
- [ ] Ruta `GET /api/circuit-breaker`.
- [ ] `recurrence_service.py`: crear recurrencia, `recurrence_worker`, forzar cuota.
- [ ] Rutas `/api/recurrences/...`.
- [ ] Tests `test_fase3_pago.py`, `test_fase3_circuit_breaker.py`, `test_recurrencia.py`.
- [ ] Verificar Escenarios F y recurrencia.

### Paso 5 — FASE 4: Interfaz (62–72 min)

- [ ] `templates/index.html`: layout del Control Room.
- [ ] `static/style.css`: semáforo de asientos, badges, panel.
- [ ] `static/app.js`: carga de asientos, selección, crear HOLD, confirmar con escenario, simular carrera, simular reserva, trazabilidad, recurrencia, estado de cola y CB.
- [ ] Verificar que un juez puede hacer el flujo completo sin herramientas externas.
- [ ] Verificar Escenarios A–F desde la UI.

### Paso 6 — Tests de casos límite y bonos (72–78 min)

- [ ] `test_casos_limite.py`: todos los casos de la Sección 12.
- [ ] Verificar Bono A (cola justa), Bono B (concurrencia real), Bono C (auditoría).
- [ ] Bono D si el tiempo lo permite.

### Paso 7 — Entrega (78–80 min)

- [ ] `README.md` con: stack, arquitectura, instalación, ejecución, pruebas, interfaz, concurrencia, idempotencia, overselling, expiración, fallos de pago, bonos.
- [ ] `requerimientos.txt` (pip freeze).
- [ ] `prompt_usado.txt` + `docs/sesion_ia.md` (bitácora GLM 5.2).
- [ ] `.gitignore` (.env, .venv, __pycache__, *.db).
- [ ] Commit y push a la rama `samuel-ardila-g3`.

---

## 14. Checklist de cobertura contra el enunciado

### FASE 1 — SeatLock

- [x] Asiento: `seat_id, section, price, currency, status`
- [x] HOLD: `hold_id, user_id, event_id, seat_ids, created_at, expires_at, status`
- [x] Operaciones: consultar asientos, crear HOLD, consultar HOLD, liberar HOLD
- [x] Regla 1: reserva todo o nada
- [x] Regla 2: expiración automática (120 s configurable)
- [x] Regla 3: límite de 6 asientos por usuario (configurable)
- [x] Regla 4: precio calculado por el servidor
- [x] Regla 5: estados válidos solo por operaciones del dominio

### FASE 2 — Concurrencia e idempotencia

- [x] Concurrencia segura: `BEGIN IMMEDIATE` + cola de 50 → exactamente un ganador
- [x] Idempotency-Key: replay devuelve mismo resultado
- [x] Conflicto de idempotencia: misma clave + payload distinto → `IDEMPOTENCY_CONFLICT`
- [x] Prueba clave: 100 usuarios → 1 asiento → 1 ganador, 99 rechazadas, 0 overselling

### FASE 3 — Confirmación y pagos

- [x] Confirmación: HOLD válido → validar expiración → pago → SOLD
- [x] Servicio dummy: APPROVED, DECLINED, ERROR, TIMEOUT (+ RECURRENCE)
- [x] Selector de escenario debajo del botón Pagar
- [x] Pago aprobado → SOLD
- [x] Pago rechazado → liberar HOLD
- [x] Timeout/error → estrategia consistente (mantener HOLD, pending_retry)
- [x] Circuit breaker: CLOSED / OPEN / HALF_OPEN (3 fallos, 15 s, 1 prueba)
- [x] CB OPEN → `PAYMENT_SERVICE_UNAVAILABLE`, asiento no SOLD

### Trazabilidad

- [x] `audit_log`: user_id, hold_id, asientos, estado anterior, estado nuevo, timestamp, motivo
- [x] Endpoint de consulta y exportación

### FASE 4 — Interfaz

- [x] Visualizar asientos (🟢🟡🔴)
- [x] Seleccionar asientos y crear HOLD
- [x] Mostrar info de la reserva (hold_id, usuario, asientos, total, tiempo restante, estado)
- [x] Confirmar compra con payment_token y escenario
- [x] Simular carrera (N usuarios → 1 ganador)
- [x] Acceso de jueces sin herramientas externas
- [x] Botón "SIMULAR UNA RESERVA" (flujo guiado para jueces)

### Recurrencia

- [x] Escenario RECURRENCE en el servicio dummy
- [x] Modelo de recurrencia (cuotas / suscripción)
- [x] Worker de cobro periódico + botón para acelerar en la UI

### Escenarios A–F

- [x] A — Reserva normal
- [x] B — Reserva expirada (TTL configurable para demo)
- [x] C — Concurrencia (20+ solicitudes → 1 HOLD)
- [x] D — Reintento (mismo key + mismo payload)
- [x] E — Conflicto (mismo key + payload distinto)
- [x] F — Pago degradado (CB OPEN)

### Bonos

- [x] Bono A — Sala de espera justa (cola FIFO + límite por usuario)
- [x] Bono B — Prueba de concurrencia real (ThreadPoolExecutor)
- [x] Bono C — Registro de auditoría reproducible (audit_log + export)
- [x] Bono D — GLM 5.2 en el producto (opcional)

### Casos límite (Sección 12)

- [x] Los 15 casos límite están cubiertos con tests

### Entregables

- [x] Código fuente funcional
- [x] README.md
- [x] Archivo de dependencias (`requerimientos.txt`)
- [x] Bitácora de GLM 5.2 (`prompt_usado.txt` + `docs/sesion_ia.md`)
- [x] Instrucciones de ejecución
- [x] Tests
- [x] Interfaz gráfica funcional

### README del equipo debe indicar

- [x] Stack seleccionado
- [x] Arquitectura
- [x] Cómo instalar dependencias
- [x] Cómo iniciar el sistema
- [x] Cómo ejecutar pruebas
- [x] Cómo abrir la interfaz
- [x] Cómo simular concurrencia
- [x] Estrategia de idempotencia
- [x] Estrategia para evitar overselling
- [x] Manejo de expiración de HOLDs
- [x] Estrategia ante fallos del proveedor de pagos
- [x] Bonos implementados

---

## 15. Comandos rápidos

```bash
# Entorno
python -m venv .venv
.venv\Scripts\activate
pip install flask

# Ejecutar
cd samuel-ardila-g3\codigo
python app.py
# Abrir http://127.0.0.1:5000

# Tests
python -m pytest tests/ -v

# Git
git add samuel-ardila-g3/
git commit -m "feat: entrega reto 3 NEXUS LIVE - Samuel Ardila G3"
git push origin samuel-ardila-g3
```

---

## 16. Rúbrica — mapeo de puntos

| Categoría | Máx. | Dónde se cubre |
|---|---:|---|
| Motor de reservas (estados, todo-o-nada, TTL, límites) | 12 | Fase 1 — Sección 3 |
| Precio y validaciones de dominio | 6 | Sección 3.4 regla 4 + 3.5 |
| Evita double booking concurrente | 12 | Sección 4.2 |
| Idempotencia (replay + conflicto) | 8 | Sección 4.3 |
| Confirmación (APPROVED/DECLINED/ERROR/TIMEOUT) | 10 | Sección 5.3–5.4 |
| Circuit breaker + degradación segura | 8 | Sección 5.5 |
| Trazabilidad | 6 | Sección 6 |
| Interfaz (reservar, confirmar, visualizar) | 8 | Sección 8 |
| Interfaz (demostrar carrera) | 4 | Sección 8.2 |
| Calidad técnica | 8 | Arquitectura modular + Sección 1 |
| Uso efectivo GLM 5.2 | 10 | `prompt_usado.txt` + `docs/sesion_ia.md` |
| Demo | 8 | Escenarios A–F desde la UI |
| **Subtotal** | **100** | |
| Bonos A+B+C (+D opcional) | +30 | Sección 10 |
