# FlowMatch Assignment Engine — Reto 2 (Hackathon Huawei)

Motor de asignación en tiempo real de pedidos a repartidores para **QuickBite**, construido con
**Python + FastAPI**, usando **GLM 5.2** como copiloto de desarrollo (ver `prompt_usado.txt` para la
bitácora de prompts).

Implementa las 4 fases del reto (asignación base por prioridad, control de ráfagas con ventana
deslizante y contención, optimización de costo con circuit breaker, e interfaz gráfica de
verificación) y los 4 bonos (A: optimización por lotes, B: concurrencia segura, C: explicabilidad
exportable con IA, D: suite de pruebas de escenarios extremos).

---

## 1. Cómo correr el proyecto

Requiere Python 3.11+.

```bash
cd codigo
pip install -r ../requerimientos.txt
uvicorn app.main:app --reload
```

Abrir **http://127.0.0.1:8000/** en el navegador: ahí está la interfaz gráfica de la Fase 4 (formulario
de pedido, tabla de repartidores en vivo, botón de "Simular ráfaga"). No se necesita `curl` ni Postman
para probar nada — aunque la API también queda documentada automáticamente en
**http://127.0.0.1:8000/docs** (Swagger, generado por FastAPI) si se prefiere probarla directamente.

### Correr las pruebas

```bash
cd codigo
pytest -q
```

38 pruebas, cubren las Fases 1-3 y los 4 bonos (ver sección 6). Corren en menos de un segundo: la
configuración de pruebas (`tests/conftest.py::fast_config`) reduce a milisegundos la latencia
simulada del servicio de tarifas para que la suite sea rápida y determinista, sin tocar la
configuración real que usa el servidor (`app/config.json`).

### Variable de entorno opcional

Si se define `GLM_API_KEY` en el entorno, el Bono C (explicaciones en lenguaje natural para pedidos
rechazados) llama a GLM 5.2 de verdad. Sin la variable, el sistema funciona igual de punta a punta
usando plantillas locales (**modo demo**), para que la evaluación no dependa de tener credenciales a
mano.

---

## 2. Arquitectura

```
codigo/
├── app/
│   ├── main.py            API (FastAPI) + interfaz grafica (Fase 4)
│   ├── engine.py          Orquestador: FlowMatchEngine (Fases 1+2+3 + Bono A)
│   ├── rules_engine.py    Cadena de reglas Fase 1+2 (zona, capacidad, ritmo, menor carga, costo)
│   ├── rate_limiter.py    Ventana deslizante por repartidor + deteccion de avalancha de zona
│   ├── surge_control.py   Modo de contencion por saturacion sostenida (con auto-expiracion)
│   ├── pricing.py         mock_pricing() + circuit breaker (Fase 3)
│   ├── batch_optimizer.py Asignacion optima por lotes con algoritmo hungaro (Bono A)
│   ├── explainability.py  Reportes estructurados para pedidos REJECTED (Bono C)
│   ├── glm_client.py      Cliente GLM 5.2 (con modo demo sin API key)
│   ├── state.py           Estado en memoria de repartidores, thread-safe (Bono B)
│   ├── validation.py      Validaciones de negocio / casos borde
│   ├── schemas.py         Modelos Pydantic de entrada/salida
│   ├── config.py          Carga de configuracion
│   ├── config.json        Todas las reglas/umbrales configurables
│   ├── templates/index.html, static/{style.css,app.js}   Interfaz grafica (Fase 4)
├── data/couriers_sample.json   Estado inicial de repartidores (semilla de la demo)
├── tests/                      38 pruebas (pytest)
└── pytest.ini
docs/BONO_A_LOTES.md            Desarrollo numerico completo del Bono A
requerimientos.txt
prompt_usado.txt
```

**Flujo de una petición `POST /assign`:** `main.py` recibe el JSON, lo valida con Pydantic
(tipos permisivos a propósito, ver sección 3) y lo pasa a `FlowMatchEngine.assign_single`, que:

1. Valida reglas de negocio (`validation.py`) → si falla, `REJECTED` explicado, sin tocar estado.
2. Si el modo de contención está activo y el pedido es `normal` → `REJECTED` inmediato (Fase 2).
3. Aplica la cadena de reglas (`rules_engine.select_courier`): capacidad → ritmo (ventana deslizante)
   → zona (misma zona / balanceo a vecinas) → menor carga → costo como desempate.
4. Si hay repartidor elegido, reserva el cupo de forma atómica (`state.py`) y cotiza el envío
   (`pricing.py`, con circuit breaker).
5. Si no, decide `QUEUED` o `REJECTED` según el estado de saturación/contención (Fase 2).
6. Si el resultado es `REJECTED`, genera un reporte estructurado + explicación en lenguaje natural
   (Bono C, `explainability.py`) — fuera de la sección crítica, para no bloquear otras asignaciones.

---

## 3. Decisiones de diseño

- **Quién manda en el estado de los repartidores.** El payload de `/assign` puede incluir el arreglo
  `couriers` (igual que el ejemplo del enunciado), pero el motor lo trata como una **semilla**: si un
  `courier_id` ya es conocido, se ignoran `zone`/`active_orders`/`max_capacity` del payload y manda el
  registro interno (`CourierStateStore`), que es el único que incrementa `active_orders` al asignar.
  Así un cliente puede seguir enviando el `couriers` del ejemplo del enunciado en cada request (y
  funciona igual, sin estado previo) *y* el sistema soporta el comportamiento con estado real que
  exige la Fase 2/4 (ráfagas, simulación en vivo) sin contradecirse.

- **Concurrencia: un lock global de sección crítica, no locks fino por repartidor.** Toda la decisión
  (leer estado, aplicar reglas, reservar el cupo) ocurre bajo un único `threading.RLock`. Es la forma
  más simple de garantizar que dos hilos nunca vean "hay cupo" para el mismo repartidor y lo reserven
  los dos (ver Bono B). El costo es que la *decisión* se serializa entre pedidos concurrentes; las
  llamadas de I/O lentas (cotización de tarifa, explicación con GLM) se hacen **fuera** de ese lock a
  propósito, para que un servicio externo lento no bloquee otras asignaciones. Para el volumen de un
  motor en memoria de un solo proceso, es un compromiso razonable — quedó documentado como una
  optimización futura (locks finos por repartidor) si el throughput lo exigiera.

- **Validación de negocio separada de Pydantic.** Los modelos de entrada (`schemas.py`) son
  permisivos a propósito (`priority`/`timestamp` como `str`, `distance_km` sin cota inferior). Un
  pedido con `distance_km: -5` o `priority: "ya"` no debe tumbar la petición con un 422 genérico: debe
  convertirse en un `REJECTED` con `reasons[]` explicando exactamente qué regla se violó
  (`validation.py`), que es lo que necesita el equipo de soporte.

- **Modelo de costo (Fase 3).** `cost = tarifa_base + tarifa_por_km × distance_km + recargo_fijo` si
  el repartidor no está en la `pickup_zone` del pedido. Con los valores por defecto (2000 + 1500/km),
  reproduce exactamente el ejemplo del enunciado (3.2 km, misma zona → **6.800 COP**). El "degradado"
  del circuit breaker usa esta misma fórmula determinista (sin el ±10% dinámico del servicio externo
  simulado) — ver el razonamiento completo en el docstring de `pricing.py`.

- **Contención por saturación es de todo el sistema, no solo de una zona.** "Todos los repartidores
  al tope" (Fase 2) se interpreta literalmente: *todos* los repartidores registrados, no solo los de
  la zona del pedido. Si hay capacidad libre en una zona vecina, el balanceo de zona (Fase 2, primer
  punto) ya la usa antes de llegar a esa situación. Queda documentado en `engine.py`.

- **Bono A modela la capacidad como "ranuras".** Cada repartidor se expande en tantas columnas de la
  matriz de costos como capacidad libre tenga, para que el algoritmo húngaro pueda darle más de un
  pedido del mismo lote sin exceder `max_capacity` (ver `docs/BONO_A_LOTES.md`).

---

## 4. Formato de salida

Mismo objeto en todas las fases, enriquecido:

```json
{
  "order_id": "ord_00234",
  "status": "ASSIGNED",
  "assigned_courier": "cour_A",
  "reasons": [
    { "rule": "same_zone_preferred", "detail": "..." },
    { "rule": "capacity_ok", "detail": "..." },
    { "rule": "least_loaded", "detail": "..." }
  ],
  "cost": 6800.0,
  "pricing_status": "ok"
}
```

`cost`/`pricing_status` quedan en `null` cuando el pedido no llegó a cotizarse (`QUEUED`/`REJECTED`).

---

## 5. Endpoints principales

| Método y ruta | Uso |
| --- | --- |
| `GET /` | Interfaz gráfica (Fase 4). |
| `POST /assign` | Evalúa un pedido (Fases 1-3). |
| `POST /assign/batch` | Asignación óptima conjunta de un lote de pedidos (Bono A). |
| `POST /simulate-burst` | Dispara N pedidos seguidos a una zona (para ver la contención en vivo). |
| `GET /couriers` / `POST /couriers/reset` | Consultar / reiniciar el estado de repartidores. |
| `GET /queue` | Cola de espera actual. |
| `GET /reports/rejections` | Reportes estructurados + explicación en lenguaje natural de los últimos `REJECTED` (Bono C). |
| `GET /state`, `GET /health` | Estado general / salud (incluye estado del modo de contención y del circuit breaker). |

---

## 6. Bonos implementados

- **Bono A — Optimización global por lotes** (`app/batch_optimizer.py`, endpoint `POST /assign/batch`).
  Algoritmo húngaro sobre una matriz de costos `pedidos × cupos-de-repartidor`. Desarrollo numérico
  completo de por qué supera al greedy en `docs/BONO_A_LOTES.md` y pruebas en
  `tests/test_bono_a_batch.py`.

- **Bono B — Concurrencia segura** (`app/state.py`, `app/engine.py`). Prueba de carga real con hilos
  concurrentes (no solo afirmada) en `tests/test_bono_b_concurrency.py`: 60 y 200 pedidos concurrentes
  contra un pool de repartidores de capacidad limitada, verificando que `active_orders` nunca excede
  `max_capacity` y que no hay asignaciones duplicadas ni conteos descuadrados.

- **Bono C — Explicabilidad exportable** (`app/explainability.py`, `app/glm_client.py`, endpoint
  `GET /reports/rejections`). Cada pedido `REJECTED` genera automáticamente un reporte JSON (reglas
  activadas, snapshot de repartidores, timestamp) más una explicación en lenguaje natural para el
  cliente, generada por GLM 5.2 (o por plantillas locales si no hay `GLM_API_KEY`).

- **Bono D — Suite de pruebas de escenarios extremos** (`tests/test_bono_d_edge_cases.py`). Pedido sin
  repartidores, distancia negativa, prioridad inválida, timestamp mal formado/futuro, ráfaga a una
  sola zona, todos los repartidores llenos de golpe, avalancha de pedidos `express`, y el instante
  exacto en que expira la ventana de contención.

---

## 7. Bitácora de prompts

Ver [`prompt_usado.txt`](./prompt_usado.txt).
