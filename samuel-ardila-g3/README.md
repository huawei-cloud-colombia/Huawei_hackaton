# NEXUS LIVE // T-80 — Motor de Reservas de Alta Concurrencia

**Equipo:** Samuel Ardila — Grupo 3
**Reto:** RETO_3_NEXUS_LIVE
**Stack:** Python 3.12 · Flask · SQLite (WAL) · HTML · CSS · JavaScript (vanilla)

---

## Stack seleccionado

- **Python 3.12** — lenguaje principal
- **Flask 3.1** — framework web
- **SQLite** (modo WAL) — persistencia con transacciones `BEGIN IMMEDIATE`
- **HTML + CSS + JS vanilla** — interfaz (NEXUS Control Room)
- **pytest** — testing

## Arquitectura

```text
Cliente (navegador) → Flask → Cola (máx 50 sesiones) → Servicios → SQLite (WAL)
```

- **Cola de concurrencia:** `SessionQueue` con `ThreadPoolExecutor` (máx 50). Evita degradación por sobreconsumso.
- **Double-booking:** transacciones `BEGIN IMMEDIATE` en SQLite WAL. Garantiza un único ganador.
- **Idempotencia:** tabla `idempotency_keys` con hash de payload. Replay devuelve mismo resultado; payload distinto = conflicto.
- **Pago dummy:** `mock_payment_authorize` con escenarios APPROVED/DECLINED/ERROR/TIMEOUT/RECURRENCE, seleccionables desde la UI.
- **Circuit Breaker:** CLOSED → OPEN (3 fallos) → HALF_OPEN (15s) → CLOSED/OPEN.
- **Recurrencia:** modelo de cuotas con worker periódico y botón para acelerar cobros.
- **Trazabilidad:** tabla `audit_log` con cada transición de estado.

## Cómo instalar dependencias

```bash
cd samuel-ardila-g3\codigo
py -m venv .venv
.venv\Scripts\activate
pip install flask pytest
```

## Cómo iniciar el sistema

```bash
cd samuel-ardila-g3\codigo
py app.py
```

El servidor levanta en `http://127.0.0.1:5000`.

## Cómo abrir la interfaz

Abrir `http://127.0.0.1:5000` en el navegador. La interfaz (NEXUS Control Room) permite:

- Visualizar asientos (🟢 AVAILABLE, 🟡 HELD, 🔴 SOLD)
- Seleccionar asientos y crear HOLDs
- Confirmar compra con selector de escenario debajo del botón Pagar
- Simular carrera (N usuarios sobre 1 asiento)
- Simular una reserva (flujo guiado de un clic para jueces)
- Ver trazabilidad y recurrencia en tiempo real
- Configurar TTL para demo

## Cómo ejecutar pruebas

```bash
cd samuel-ardila-g3\codigo
py -m pytest tests/ -v
```

Resultado: 45 tests, todos pasan.

## Cómo simular concurrencia

Desde la UI: botón "SIMULAR CARRERA" con asiento y N usuarios configurables.
Desde la API: `POST /api/simulate/race` con `{"seat_id": "VIP-A-001", "n": 20}`.

## Estrategia de idempotencia

Cabecera `Idempotency-Key` + hash SHA-256 del payload. Si la clave ya existe:
- Mismo hash → devuelve la respuesta cacheada (replay).
- Hash distinto → `409 IDEMPOTENCY_CONFLICT`.

## Estrategia para evitar overselling

Transacciones `BEGIN IMMEDIATE` en SQLite WAL. El lock de escritura se adquiere antes de cualquier lectura. Dos hilos que compiten por el mismo asiento se serializan: el primero hace COMMIT, el segundo ve el asiento como HELD y es rechazado. Garantiza exactamente un ganador.

## Manejo de expiración de HOLDs

Hilo demonio (`expiry_worker`) que recorre HOLDs con `expires_at < now()` cada `TTL/4` segundos. Los marca `EXPIRED` y libera los asientos a `AVAILABLE`. TTL configurable (default 120s, reducible desde la UI para demo).

## Estrategia ante fallos del proveedor de pagos

| Resultado | Acción |
|---|---|
| APPROVED | HELD → SOLD |
| DECLINED | HELD → AVAILABLE (libera) |
| ERROR | Mantiene HELD (pending_retry) |
| TIMEOUT | Mantiene HELD (pending_retry) |

Circuit Breaker: 3 fallos consecutivos → OPEN (503 PAYMENT_SERVICE_UNAVAILABLE, asiento no se marca SOLD). Tras 15s → HALF_OPEN → 1 prueba → CLOSED/OPEN.

## Bonos implementados

- **Bono A — Sala de espera justa:** cola FIFO de 50 sesiones + límite de 6 asientos por usuario.
- **Bono B — Prueba de concurrencia real:** `test_fase2_concurrencia.py` con 100 hilos → 1 ganador.
- **Bono C — Registro de auditoría reproducible:** tabla `audit_log` + endpoint de exportación.
- **Bono D — GLM 5.2 en el producto:** opcional (no implementado por tiempo).

## Recurrencia

Escenario `RECURRENCE` en el servicio dummy. Crea un plan de 3 cuotas. El primer cargo se aprueba al confirmar. La UI permite simular siguientes cuotas con un botón. Un worker periódico simula el paso del tiempo.

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Interfaz (Control Room) |
| GET | `/api/seats` | Consultar asientos |
| POST | `/api/holds` | Crear HOLD |
| GET | `/api/holds/<id>` | Consultar HOLD |
| DELETE | `/api/holds/<id>` | Liberar HOLD |
| POST | `/api/holds/<id>/confirm` | Confirmar compra |
| POST | `/api/simulate/race` | Simular carrera |
| GET | `/api/queue/stats` | Estado de la cola |
| GET | `/api/circuit-breaker` | Estado del CB |
| POST | `/api/circuit-breaker/reset` | Resetear CB |
| GET | `/api/audit/<id>` | Trazabilidad de una reserva |
| GET | `/api/recurrences/<id>` | Estado de recurrencia |
| POST | `/api/recurrences/<id>/charge` | Cobrar siguiente cuota |
| GET | `/api/config` | Configuración |
| POST | `/api/config` | Actualizar configuración |
