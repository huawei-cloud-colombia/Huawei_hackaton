# NEXUS LIVE - Motor de Reservas de Alta Concurrencia
## Reto 3 - Huawei Colombia MaaS Hackathon

**Autor:** Nicolas Rodriguez Ricardo
**Grupo:** MESA-RETO3

---

## Stack Seleccionado

- **Python 3.13** - Lenguaje principal
- **FastAPI** - Framework web async
- **Pydantic v2** - Validación de datos
- **Jinja2** - Templates HTML
- **httpx** - Cliente HTTP para GLM 5.2
- **pytest** - Testing
- **threading.RLock** - Mecanismo de concurrencia

---

## Arquitectura

```
┌─────────────────────────────────────────────────┐
│              NEXUS Control Room                  │
│            (Interfaz Web - FastAPI)              │
└──────────────────┬──────────────────────────────┘
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│ SeatLock │ │ Checkout │ │ Waitlist │
│  Engine  │ │ Service  │ │  (Bono A)│
└────┬─────┘ └────┬─────┘ └──────────┘
     │            │
     │     ┌──────┼──────┐
     │     ▼      ▼      ▼
     │ ┌────────┐ ┌──────────┐
     │ │Payment │ │ Circuit  │
     │ │Provider│ │ Breaker  │
     │ └────────┘ └──────────┘
     │
     ▼
┌──────────┐
│  Trace   │
│ (Audit)  │
└──────────┘
```

### Componentes

1. **SeatLockEngine** (`seatlock.py`): Núcleo del motor de reservas. Maneja estados de asientos (AVAILABLE → HELD → SOLD), creación de HOLDs, expiración automática, idempotencia y límites por usuario.

2. **CheckoutService** (`checkout.py`): Servicio de confirmación que integra el motor de reservas con el proveedor de pagos y el circuit breaker.

3. **MockPaymentProvider** (`payment_provider.py`): Proveedor de pagos simulado que produce APPROVED, DECLINED, ERROR, TIMEOUT.

4. **CircuitBreaker** (`circuit_breaker.py`): Protege al sistema contra fallos del proveedor de pagos. Estados: CLOSED → OPEN → HALF_OPEN.

5. **FairWaitlist** (`waitlist.py`): Sala de espera justa (Bono A). FIFO con anti-monopolio.

6. **OperationsExplainer** (`glm_explainer.py`): Integración de GLM 5.2 para explicaciones operacionales (Bono D).

---

## Cómo Instalar Dependencias

```bash
cd codigo
pip install -r ../requerimientos.txt
```

---

## Cómo Iniciar el Sistema

```bash
cd codigo
python -m uvicorn app.main:app --port 8000
```

El servidor arranca en `http://localhost:8000`

---

## Cómo Ejecutar Pruebas

```bash
cd codigo
python -m pytest tests/ -v
```

---

## Cómo Abrir la Interfaz

Abrir `http://localhost:8000` en el navegador.

La interfaz permite:
- Visualizar asientos con estados distinguibles (🟢 AVAILABLE, 🟡 HELD, 🔴 SOLD)
- Seleccionar asientos y crear HOLDs
- Ver información de la reserva (Hold ID, usuario, asientos, total, tiempo restante, estado)
- Confirmar compra con payment_token
- Simular carreras concurrentes
- Ver trazabilidad
- Controlar el circuit breaker
- Gestionar la sala de espera

---

## Cómo Simular Concurrencia

### Desde la interfaz
1. Ir a la sección "Simular Carrera"
2. Especificar el asiento y número de usuarios
3. Click "Simular Carrera"
4. Ver resultados: N solicitudes, 1 ganador, N-1 rechazadas

### Desde la API
```bash
curl -X POST http://localhost:8000/api/race \
  -H "Content-Type: application/json" \
  -d '{"concurrent_users": 100, "seat_id": "VIP-A-001"}'
```

### Desde los tests
```bash
python -m pytest tests/test_concurrency.py -v
```

---

## Estrategia de Idempotencia

Se usa el header `Idempotency-Key`:

- **Replay**: Misma key + mismo payload → mismo resultado lógico (mismo hold_id).
- **Conflicto**: Misma key + payload diferente → `IDEMPOTENCY_CONFLICT`.
- **Keys independientes**: Diferentes keys → operaciones independientes.

La implementación guarda el payload normalizado (user_id, event_id, seat_ids ordenados) y el resultado asociado a cada key.

---

## Estrategia para Evitar Overselling

**Mecanismo: `threading.RLock` (reentrant lock)**

Todas las operaciones de cambio de estado de asientos están protegidas por un RLock reentrant. Esto garantiza:

1. **Atomicidad**: La verificación de disponibilidad y el cambio de estado ocurren atomically dentro del lock.
2. **Todo-o-nada**: Si un asiento no está disponible, la operación completa falla sin afectar otros asientos.
3. **No overselling**: Es imposible que dos hilos reserven el mismo asiento simultáneamente.

El RLock es reentrant para permitir que operaciones internas (como expiración automática) llamen a métodos protegidos sin deadlock.

---

## Manejo de Expiración de HOLDs

- Cada HOLD tiene un TTL configurable (default: 120 segundos).
- La expiración se evalúa de forma lazy: al acceder a cualquier hold o asiento.
- Se puede forzar la expiración con `POST /api/expire`.
- Al expirar, los asientos vuelven a AVAILABLE y se registra en la trazabilidad.

---

## Estrategia ante Fallos del Proveedor de Pagos

| Resultado | Acción |
|-----------|--------|
| APPROVED | HELD → SOLD, compra confirmada |
| DECLINED | HOLD liberado, asientos vuelven a AVAILABLE |
| ERROR | HOLD se mantiene activo, cliente puede reintentar |
| TIMEOUT | HOLD se mantiene activo, cliente puede reintentar |
| CB OPEN | No se llama al proveedor, `PAYMENT_SERVICE_UNAVAILABLE` |

**Circuit Breaker**:
- 3 fallos consecutivos → OPEN
- 15 segundos sin llamadas → HALF_OPEN
- 1 llamada de prueba en HALF_OPEN
- Éxito → CLOSED, Fallo → OPEN

**Estrategia para TIMEOUT/ERROR**: No se vende sin certeza ni se libera inmediatamente. El HOLD se mantiene activo para que el cliente pueda reintentar con el mismo payment_token (idempotencia de pago).

---

## Trazabilidad

Cada cambio de estado genera un `TraceEvent` con:
- `timestamp`
- `hold_id`
- `seat_id`
- `user_id`
- `from_state` / `to_state`
- `reason`

Endpoints: `GET /api/trace` y `GET /api/trace/{hold_id}`

---

## Bonos Implementados

### Bono A - Sala de Espera Justa (+8 pts)
- FIFO con orden de atención por llegada
- Anti-monopolio: un usuario solo puede estar una vez por evento
- Abandono: el usuario puede salir de la cola
- Timeout: entradas expiran automáticamente

### Bono B - Prueba de Concurrencia Real (+8 pts)
- Tests con 20, 50, 100, 200 usuarios concurrentes
- Verifica: 1 ganador, N-1 rechazadas, 0 overselling
- Tests con carreras simultáneas sobre asientos diferentes

### Bono C - Registro de Auditoría Reproducible (+7 pts)
- Trazabilidad completa: AVAILABLE → HELD → PAYMENT_ATTEMPT → SOLD
- Exportable via API
- Estructura reproducible

### Bono D - GLM 5.2 dentro del Producto (+7 pts)
- `OperationsExplainer` genera explicaciones operacionales
- Analiza historial de reservas, eventos de pago, cambios de estado
- Maneja: timeout, respuesta vacía, error de API, formato inesperado
- Fallback rule-based cuando GLM no está disponible

---

## Configuración

| Parámetro | Default | Descripción |
|-----------|---------|-------------|
| hold_ttl_seconds | 120 | Tiempo de vida de un HOLD |
| max_seats_per_user | 6 | Máximo de asientos por usuario |
| failure_threshold | 3 | Fallos para abrir el circuit breaker |
| recovery_timeout | 15s | Tiempo para HALF_OPEN |

---

## Estructura del Proyecto

```
nicolas-rodriguez-mesa-reto3/
├── README.md
├── requerimientos.txt
├── prompt_usado.txt
├── .gitignore
└── codigo/
    ├── app/
    │   ├── __init__.py
    │   ├── main.py              # FastAPI API + Control Room
    │   ├── schemas.py           # Modelos de datos
    │   ├── seatlock.py          # Motor de reservas
    │   ├── checkout.py          # Servicio de checkout
    │   ├── circuit_breaker.py   # Circuit breaker
    │   ├── payment_provider.py  # Proveedor de pagos mock
    │   ├── waitlist.py          # Sala de espera (Bono A)
    │   ├── glm_explainer.py     # GLM 5.2 (Bono D)
    │   └── templates/
    │       └── index.html       # NEXUS Control Room
    ├── tests/
    │   ├── test_nexus.py        # Tests principales
    │   └── test_concurrency.py  # Bono B
    └── docs/
        └── sesion_ia.md         # Bitácora de IA
```
