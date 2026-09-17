# SeatLock — Sistema de Reserva de Entradas

Núcleo **Fase 1 (SeatLock)**: reservas temporales sobre asientos con garantía de que un asiento
`AVAILABLE → HELD → SOLD` **nunca** se vende a dos compradores diferentes, incluso bajo solicitudes
concurrentes.

Implementado con **FastAPI + SQLite (WAL, `BEGIN IMMEDIATE`)**. Incluye GUI web sencilla para demostrarlo.

---

## Transiciones de estado

```
                 create_hold (todo-o-nada)
   AVAILABLE  ─────────────────────────────►  HELD
       ▲                                         │
       │ release_hold                            │ confirm_hold
       │ expire (auto, TTL)                      ▼
       └─────────────────────────────────────  SOLD  (terminal)
```

| Transición          | Disparador                          | Resultado                              |
|---------------------|-------------------------------------|----------------------------------------|
| `AVAILABLE → HELD`  | `POST /holds` (todos los asientos libres) | asientos `HELD`, se crea `hold_id`     |
| `HELD → SOLD`       | `POST /holds/{id}/confirm`           | asientos `SOLD`, hold `SOLD`            |
| `HELD → AVAILABLE`  | `DELETE /holds/{id}` (release)       | asientos `AVAILABLE`, hold `RELEASED`   |
| `HELD → AVAILABLE`  | expiración automática (TTL)          | asientos `AVAILABLE`, hold `EXPIRED`    |
| `SOLD → *`          | —                                   | terminal, no se puede revertir          |

Transiciones inválidas (ej. `SOLD → HELD`, confirmar un hold ajeno o expirado) se rechazan con
`409 REJECTED` y un `reason` de dominio. El cliente **no** puede setear `status` directamente.

---

## Reglas obligatorias (cumplidas)

1. **Todo o nada** — si algún asiento pedido no está `AVAILABLE`, la reserva falla completa y no se hold parcial. (`reason = seat_not_available`, `conflicting_seats` indicados.)
2. **Expiración automática** — cada `HOLD` expira a los `SEATLOCK_HOLD_TTL` segundos (default `120`). Al expirar, `HELD → AVAILABLE`. Hay un *sweeper* en background + expiración *lazy* dentro de cada transacción.
3. **Límite de asientos por usuario** — máximo `SEATLOCK_MAX_SEATS` (default `6`) asientos activos en holds no expirados. (`reason = max_seats_exceeded`.)
4. **El precio lo controla el servidor** — el request no incluye precio; `total` se calcula del catálogo de asientos en la DB.
5. **Estados válidos** — las transiciones solo ocurren por operaciones de dominio; `status` no es entrada del cliente.

---

## Cómo garantizar "nunca dos compradores"

Cada operación de escritura abre una transacción SQLite **`BEGIN IMMEDIATE`**, que adquiere el
*write lock* antes de cualquier lectura. Dos `POST /holds` concurrentes sobre el mismo asiento:

1. El primero adquiere el write lock, verifica `AVAILABLE`, marca `HELD`, hace `COMMIT`.
2. El segundo espera el lock (busy_timeout 10s), luego ve `HELD` → `REJECTED seat_not_available`.

No hay ventana de intercalación. Verificado por `test_concurrency_*` (20/15 hilos → exactamente 1 ganador).

---

## Ejecutar

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

- GUI: <http://127.0.0.1:8000/>  (o `/ui`)
- Swagger: <http://127.0.0.1:8000/docs>

### Variables de entorno

| Variable                    | Default      | Descripción                         |
|-----------------------------|--------------|-------------------------------------|
| `SEATLOCK_DB_PATH`          | `seatlock.db`| Archivo SQLite                      |
| `SEATLOCK_HOLD_TTL`         | `120`        | TTL del hold en segundos            |
| `SEATLOCK_MAX_SEATS`        | `6`          | Máx. asientos activos por usuario   |
| `SEATLOCK_SWEEPER_INTERVAL` | `5`          | Intervalo del sweeper (segundos)    |

---

## API

### Consultar asientos
`GET /events/{event_id}/seats` → lista de `Seat` (status efectivo, considerando holds expirados).

### Crear HOLD
`POST /holds`
```json
{ "user_id": "usr_10482", "event_id": "aurora-bogota-2026", "seat_ids": ["A-101","A-102"] }
```
→ `201` Hold  ·  `409` `{ "status":"REJECTED", "reason":"seat_not_available", "conflicting_seats":["A-102"] }`

### Consultar / Liberar / Confirmar
- `GET /holds/{hold_id}` → Hold
- `DELETE /holds/{hold_id}?user_id=...` → Hold `RELEASED`
- `POST /holds/{hold_id}/confirm` body `{"user_id":"..."}` → `SOLD`

### Utilidades
- `GET /health`, `GET /config`, `POST /admin/expire` (forzar expiración)

---

## Tests

```bash
python -m pytest tests/ -v
```

Cubren: seed disponible, creación y precio por servidor, todo-o-nada (sin hold parcial),
rechazo a segundo usuario, límite de 6 asientos, release, confirm terminal, expiración
automática, expiración determinística, y concurrencia (1 ganador entre 20 hilos).

---

## Estructura

```
app/
  config.py    settings (env)
  db.py        schema SQLite + WAL + seed
  models.py    Pydantic (Seat, Hold, enums, Reason)
  service.py   dominio: transacciones BEGIN IMMEDIATE, reglas, máquina de estados
  main.py      FastAPI: rutas, lifespan + sweeper, static GUI
static/index.html   GUI (mapa de asientos, reservar, liberar, confirmar, test concurrencia)
tests/test_api.py   13 pruebas
```

---

## Notas

- **Persistencia:** SQLite con WAL; los datos sobreviven reinicios. Para resetear, borra `seatlock.db*`.
- **Concurrencia:** los endpoints de DB son síncronos (FastAPI los corre en threadpool); cada operación abre su propia conexión y transacción `BEGIN IMMEDIATE`.
- **Pago:** fuera del alcance de Fase 1. La transición `HELD → SOLD` existe como operación de dominio (`confirm_hold`) para completar el diagrama de estados; la integración con un proveedor de pagos inestable + reintentos seguros queda para Fase 2.
