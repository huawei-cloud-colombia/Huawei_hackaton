# NEXUS Live — Motor de Reservas en RAM (v2)

Rediseño del motor para **42.000 asientos / 180.000 usuarios concurrentes**.
SQLite sale del camino crítico: toda la lógica transaccional vive en **RAM** y SQLite es un
**sumidero asíncrono (write-behind)**.

---

## Arquitectura

```
 HTTP (async)  ──►  BookingService ──►  StateMachine (RAM)  ──►  asyncio.Queue (events)
                         │                      ▲                        │
                         ▼                      │                        ▼
                  IdempotencyStore (RAM)   Reaper (TTL, RAM)      WriterWorker (single-writer)
                                                                         │
                                                                         ▼
                                                                     SQLite (WAL)
```

- **StateMachine** (`nexus/state.py`): 42.000 `SeatRuntime` en un dict. Transiciones atómicas
  `AVAILABLE → HELD → SOLD` (y `HELD → AVAILABLE` por timeout). Exclusión mutua con
  **locks particionados** (256 `asyncio.Lock`) y **adquisición ordenada** por índice de shard
  → imposible reservar dos veces el mismo asiento y sin deadlock.
- **IdempotencyStore** (`nexus/idempotency.py`): dict en RAM de `Idempotency-Key` → respuesta.
  Peticiones duplicadas en vuelo se coordinan con `asyncio.Future` (el segundo espera al primero);
  peticiones repetidas devuelven el resultado cacheado sin reejecutar lógica.
- **Reaper** (`nexus/state.py::reap`): worker asíncrono que cada `0.5s` devuelve los `HELD`
  expirados (TTL 600s) a `AVAILABLE` sin tocar SQLite en tiempo real (emite eventos).
- **WriterWorker** (`nexus/persistence.py`): único consumidor de la `asyncio.Queue`. Hace
  **batching** (hasta 200 eventos o 50ms) y vuelca a SQLite en un solo hilo vía
  `asyncio.to_thread` → **0 colisiones de cerrojo** ("database is locked" imposible).
  PRAGMAs: `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`.

---

## Garantía de no doble venta

Cada mutación adquiere los locks de los shards de los asientos involucrados **en orden ascendente**
(anti-deadlock). Dentro de la sección crítica (puramente síncrona, sin `await`) se valida y muta.
Dos `POST /holds` sobre el mismo asiento: ambos compiten por el mismo `asyncio.Lock` → uno marca
`HELD`, el otro ve `HELD` → `REJECTED seat_not_available`. Verificado con **500 concurrentes → 1 ganador**.

---

## Endpoints (no bloqueantes)

| Método | Path | Descripción |
|--------|------|-------------|
| `POST` | `/holds` | Reserva temporal (RAM → HELD, encola persistencia). Body: `{user_id,event_id,seat_ids}`. Header opcional `Idempotency-Key`. |
| `POST` | `/checkout` | Confirma compra `HELD → SOLD`. Body: `{hold_id,user_id}`. |
| `POST` | `/release` | Libera hold anticipadamente `HELD → AVAILABLE`. |
| `GET`  | `/seats/{id}` | Estado en RAM (sub-milisegundo). |
| `GET`  | `/events/{event_id}/seats?section=&limit=` | Listado en RAM. |
| `GET`  | `/admin/stats` | Contadores y `writer_errors`. |
| `GET`  | `/admin/bench?cycles=` | Latencia del motor en proceso (sin HTTP). |
| `GET`  | `/health`, `/config` | — |

---

## Reglas (heredadas de Fase 1, cumplidas en RAM)

1. **Todo o nada**: si un asiento no está `AVAILABLE`, la reserva falla completa.
2. **Expiración automática**: TTL configurable (default 600s) vía reaper en RAM.
3. **Límite 6 asientos** por usuario (contador O(1) en RAM).
4. **Precio por servidor**: el cliente no envía precio; `total` se calcula del catálogo en RAM.
5. **Estados válidos**: transiciones solo por operaciones de dominio.

---

## Ejecutar

```bash
pip install -r requirements.txt
uvicorn nexus.main:app --port 8000
```
Swagger: `http://127.0.0.1:8000/docs`

### Variables de entorno

| Variable | Default | |
|----------|---------|-|
| `NEXUS_DB_PATH` | `nexus.db` | |
| `NEXUS_HOLD_TTL` | `600` | segundos |
| `NEXUS_MAX_SEATS` | `6` | |
| `NEXUS_SHARDS` | `256` | locks particionados |
| `NEXUS_REAPER_INTERVAL` | `0.5` | segundos |
| `NEXUS_WRITER_BATCH` | `200` | eventos por lote |
| `NEXUS_WRITER_FLUSH_MS` | `50` | |

---

## Stress test

```bash
python stress_test.py 500
```

Resultado observado (500 intentos simultáneos sobre `VIP-0001`):

```
 Ganadores (201)          : 1
 Rechazados (409)         : 499
 Checkout del ganador     : HTTP 200
 SQLite errores ('locked'): 0
 Motor en RAM p50 / p99   : ~10 / ~50 us  (p99 = 0.05 ms, meta <5ms)
 Idempotencia misma key   : status=[201,201] same_hold=True
 RESULTADO: PASS
```

La latencia HTTP end-to-end bajo hot-spot (500 sobre un mismo shard) es alta porque las conexiones
se serializan en un solo event loop; **la latencia del motor en RAM es ~50 µs p99** (medida por
`/admin/bench`). Con carga repartida entre 256 shards la contención por shard es baja.

---

## Estructura

```
nexus/
  config.py        settings (env)
  models.py        Pydantic + Event
  state.py         StateMachine en RAM, locks particionados, reaper
  idempotency.py   store en RAM con Future
  persistence.py   schema SQLite + WriterWorker (cola + batching)
  service.py       orquestación state + idempotency + encolado
  main.py          FastAPI endpoints + lifespan + stats/bench
stress_test.py     500 concurrentes + idempotencia + asserts
tests/test_nexus.py  wrapper pytest
```

---

## Notas de diseño

- **¿Por qué locks y no un solo lock global?** 256 shards permiten paralelismo entre asientos de
  distintos shards; la adquisición ordenada por índice evita deadlock al reservar asientos multi-shard.
- **¿Por qué no expiración lazy dentro de `create_hold`?** Reclamar un hold multi-asiento expirado
  tocaría shards fuera del conjunto pedido, complicando el razonamiento. Se delega al reaper
  (ventana ≤ `reaper_interval`). Trade-off documentado.
- **Durabilidad**: `SOLD` se persiste y se restaura al reiniciar; los `HELD` son efímeros (se
  reinician a `AVAILABLE` al arrancar, pues su TTL vive en RAM).
- **Fase 1** (`app/`) se conserva como referencia del diseño anterior sobre SQLite directo.

---

# FASE 2 — La carrera por el último asiento

100 solicitudes concurrentes sobre un solo asiento premium `VIP-A-001` con disponibilidad 1.

## Requisito 1 — Concurrencia segura
Mecanismo: **locks particionados (256 `asyncio.Lock`) con adquisición ordenada por índice de shard**.
La sección crítica es síncrona (sin `await`), por lo que la transición `AVAILABLE → HELD` es atómica
respecto a otras coroutines. Dos `POST /holds` sobre el mismo asiento compiten por el mismo lock →
exactamente uno gana. Elección documentada en `nexus/state.py`.

## Requisito 2 — Idempotencia con conflicto
`IdempotencyStore` (`nexus/idempotency.py`) guarda un **fingerprint** del payload junto a cada `Idempotency-Key`:
- Misma key + mismo payload → devuelve el resultado cacheado (mismo `hold_id`), sin reejecutar.
- Misma key + payload distinto → `409 IDEMPOTENCY_CONFLICT`.
- Peticiones duplicadas en vuelo se coordinan con `asyncio.Future`.

## Resultado (`python stress_test_fase2.py 100`)
```
 Ganadores (201)          : 1
 Rechazados (409)         : 99
 Overselling (SOLD)       : 0
 Idempotencia replay      : 201, same_hold=True
 Idempotencia conflicto   : 409, IDEMPOTENCY_CONFLICT
 RESULTADO: PASS
```

---

# FASE 3 — Confirmación y proveedor de pagos inestable

`POST /checkout` ahora valida el hold, llama al proveedor de pagos y aplica la transición según el resultado.

## Proveedor mock (`nexus/payment.py::PaymentProvider`)
Produce `APPROVED`, `DECLINED`, `ERROR`, `TIMEOUT`. Es **idempotente por `charge_key`** (`hold_id:payment_token`):
el resultado verdadero se determina una sola vez; reintentos re-entregan el mismo resultado → **0 cobros duplicados**.
Modo forzable vía `POST /admin/payment/mode` (`always_approved|always_declined|always_error|always_timeout|random`).

## Reglas de consistencia
| Resultado | Acción | Cacheable |
|-----------|--------|-----------|
| `APPROVED` | `HELD → SOLD` + confirmación | sí |
| `DECLINED` | `HELD → AVAILABLE` (hold liberado) | sí |
| `ERROR` / `TIMEOUT` | **no vender, no liberar**: hold queda `HELD`, retorno `409 PAYMENT_PENDING` (reintentable) | **no** (permite retry) |

**Estrategia timeout/error ambiguo:** un timeout no implica rechazo. El asiento **no se vende** (sin certeza)
ni **se libera** (podría haber un cobro pendiente). Se devuelve `PAYMENT_PENDING` y **no se cachea** el resultado
de idempotencia, de modo que el cliente puede reintentar con la misma `Idempotency-Key`. El proveedor idempotente
garantiza que el reintento no duplique el cobro. Un flag `checking` en el hold evita que el reaper lo expire
mientras hay una operación de pago en curso.

## Circuit Breaker (`nexus/payment.py::CircuitBreaker`)
`CLOSED →` 3 fallos consecutivos `→ OPEN →` (recovery 15s, vía `tick()` del reaper) `→ HALF_OPEN →` 1 trial
`→ CLOSED` (éxito) / `→ OPEN` (fallo). En `OPEN`, `checkout` devuelve `503 PAYMENT_SERVICE_UNAVAILABLE`
sin llamar al proveedor ni marcar `SOLD`. En `HALF_OPEN` se permite exactamente 1 trial.

## Resultado (`python stress_test_fase3.py`)
```
 A. APPROVED -> SOLD        : checkout=200 seat=SOLD conf=True
 B. DECLINED -> release     : checkout=402 PAYMENT_DECLINED seat=AVAILABLE
 C. TIMEOUT -> retry -> SOLD: timeout=409(PAYMENT_PENDING) seat=HELD | retry=200 seat=SOLD
 D. CB CLOSED->OPEN->503->HALF_OPEN->CLOSED : 3 errors=OPEN | 4th=503 | recovery=HALF_OPEN | trial=200 -> CLOSED
 E. CB HALF_OPEN failure -> OPEN : halfopen=HALF_OPEN -> after failure=OPEN
 Stats: writer_errors=0
 RESULTADO: PASS
```

## Endpoints nuevos
`POST /checkout` (con `payment_token`), `GET /confirmations/{hold_id}`,
`POST /admin/payment/mode`, `GET /admin/payment/stats`, `POST /admin/payment/reset`,
`GET /admin/circuit-breaker`, `POST /admin/circuit-breaker/reset`.

## Ejecutar todo
```bash
python stress_test.py 500        # Fase 1 — 500 concurrentes, 1 ganador, 0 'database is locked'
python stress_test_fase2.py 100  # Fase 2 — carrera + idempotencia + conflicto
python stress_test_fase3.py      # Fase 3 — pagos + circuit breaker
python -m pytest                 # 18/18 (Fase 1 + NEXUS + Fase 2 + Fase 3 + trazabilidad)
```

---

# Trazabilidad mínima

Cada transición de estado persiste en SQLite (tabla `transitions`) vía write-behind, con:

| Campo | Descripción |
|-------|-------------|
| `user_id` | usuario que disparó la transición |
| `hold_id` | reserva afectada |
| `seat_ids` | asientos involucrados |
| `prev_status` | estado anterior (`AVAILABLE`/`HELD`/`SOLD`) |
| `new_status` | estado nuevo |
| `timestamp` | momento de la transición |
| `reason` | motivo (`hold_created`, `payment_approved`, `payment_declined`, `released`, `expired`) |

Una sola tabla cubre reservas y compras. Se mantiene además un espejo en RAM (`state.trace`)
para consulta inmediata.

## Endpoints
- `GET /admin/traceability?hold_id=&limit=` — traza en RAM (inmediata).
- `GET /admin/traceability/db?hold_id=&limit=` — tabla `transitions` en SQLite (persistente).
- `GET /holds/{hold_id}/trace` — historial de un hold.

## Verificación (`python trace_test.py`)
```
 RAM hold transitions     : [('AVAILABLE','HELD','hold_created'), ('HELD','SOLD','payment_approved')]
 SQLite hold transitions  : [('HELD','SOLD','payment_approved'), ('AVAILABLE','HELD','hold_created')]
 todos campos presentes   : True (RAM y SQLite)
 RESULTADO: PASS
```

---

# Interfaz gráfica

Servida en `http://127.0.0.1:8000/` (o `/ui`). Un solo HTML autónomo (`static/nexus.html`).

## Funcionalidades
1. **Visualizar asientos**: mapa con 🟢 AVAILABLE / 🟡 HELD / 🔴 SOLD, filtrable por sección.
2. **Seleccionar asientos**: clic para togglear; total estimado client-side; `Crear HOLD` (precio real lo calcula el servidor).
3. **Info de la reserva**: por cada hold — Hold ID, Usuario, Asientos, Total, **tiempo restante (countdown)**, Estado.
4. **Confirmar compra**: `payment_token` (generable) + `checkout`; también `Liberar hold`.
5. **Simular carrera**: `SIMULAR N USUARIOS POR ESTE ASIENTO` (N por defecto 20) → muestra `N solicitudes → 1 ganador, N-1 rechazadas`, overselling y detalle por solicitud.

## Multi-sesión (clave para validar concurrencia)
El panel izquierdo tiene **3 sesiones independientes** (Sesión A/B/C), cada una con su propio
`user_id` editable, asientos seleccionados y lista de holds. Al cambiar de sesión cambia el mapa
de selección y las reservas activas. Así el juez puede, p.ej.: que la Sesión A holda `VIP-A-004`,
la Sesión B holda `VIP-A-005`, y comprobar que la Sesión C no puede tomar `VIP-A-004` (409 `seat_not_available`).

## Controles de Fase 3 en la GUI
- Selector de **modo de pago** (`random`/`always_approved`/`always_declined`/`always_error`/`always_timeout`).
- Estado del **circuit breaker** en vivo (CLOSED/OPEN/HALF_OPEN).
- Botón **Ver trazabilidad** (transiciones recientes).

## Verificación manual previa (`python manual_gui_check.py`)
Comprueba los 5 flujos contra el servidor real antes de la GUI: asientos, hold, info de reserva,
checkout con `payment_token`, release y carrera 20→1/19.
