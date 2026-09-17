# 🛡️ SentinelPay Risk Engine

Motor de scoring de riesgo en tiempo real para transacciones de pago, construido para el reto 4 del hackathon Huawei Cloud Colombia.

## Arquitectura

- **Backend:** FastAPI (Python), un único servicio que expone la API y sirve la interfaz web (no hay build front-end separado).
- **Motor de reglas (`app/engine.py`):** clase `RiskEngine`, con estado en memoria (sin base de datos externa), protegida por un `threading.RLock` para concurrencia segura.
- **Persistencia:** 100% en memoria (diccionarios + `collections.deque` para ventanas deslizantes). Se reinicia con `POST /reset` o al reiniciar el proceso.
- **UI (Fase 4):** HTML/CSS/JS vanilla servido como estáticos por el mismo FastAPI (`app/static/`), sin frameworks de frontend, para minimizar dependencias y tiempo de setup.

```
sentinelpay/
  app/
    config.py     # configuración de reglas (pesos, umbrales, activar/desactivar)
    models.py     # esquemas Pydantic (entrada/salida)
    bank.py       # mock_bank_auth() + CircuitBreaker
    explain.py    # generación de explicación en lenguaje natural + reporte de auditoría
    engine.py     # RiskEngine: reglas, ventanas deslizantes, blocklist, scoring, grafo
    main.py       # rutas FastAPI
    static/       # index.html, app.js, styles.css (Fase 4)
  tests/          # 18 pruebas (unitarias, concurrencia, adversariales, grafo)
  requirements.txt
  conftest.py
```

## Cómo correr el proyecto

```bash
python -m venv .venv
./.venv/Scripts/activate        # Windows
pip install -r requirements.txt

# Servidor + UI
uvicorn app.main:app --reload --port 8000
# abrir http://127.0.0.1:8000

# Tests
pytest -v
```

## Decisiones de diseño

- **Hard decline vs. score acumulado:** las reglas de velocidad (`velocity_card`, `velocity_device`) y el flag `hard_decline` fuerzan `DECLINE` independientemente del score total. Esto refleja el comportamiento esperado del caso (la 6ª transacción de una ráfaga debe rechazarse aunque el score acumulado no llegue a 75) y evita que un ataque de "card testing" quede en zona gris de `REVIEW`.
- **Lock de concurrencia acotado:** el `RLock` solo protege las estructuras compartidas en memoria (ventanas, blocklist, promedios). La llamada al banco simulado (`mock_bank_auth`) se hace **fuera** del lock para no serializar innecesariamente las evaluaciones concurrentes — ver Bono B.
- **Hora inusual:** se asume que el `timestamp` recibido ya está en hora local del comercio (el caso no provee huso horario por `merchant_id`). En producción esto se resolvería con un lookup `merchant_id -> timezone`.
- **Explicabilidad sin LLM real (Bono C):** la idea original era generar la explicación en lenguaje natural con **GLM 5.2** vía Huawei MaaS, como pedía el enunciado del hackathon. La conexión (OpenCode/Continue → LiteLLM/Huawei MaaS con la Virtual Key entregada) quedó bloqueada por temas de credenciales e infraestructura fuera de nuestro control durante la ventana del hackathon (ver bitácora de prompts). Para no dejar el bono sin resolver, `app/explain.py` genera la explicación con una plantilla determinística sobre las mismas razones estructuradas; el punto de extensión está aislado para conectar un LLM real sin tocar el resto del pipeline.

## Bonos implementados

| Bono | Estado | Dónde |
| --- | --- | --- |
| A — Colusión por grafo | ✅ Implementado | `engine.py`, regla `collusion_graph`, tests en `tests/test_graph.py` |
| B — Concurrencia segura | ✅ Implementado + probado con hilos reales | `tests/test_concurrency.py` |
| C — Explicabilidad exportable | ✅ Implementado (plantilla, ver nota arriba) | `app/explain.py`, endpoint `GET /reports` |
| D — Suite adversarial | ✅ Implementado | `tests/test_adversarial.py` |

## Endpoints principales

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/` | UI (Fase 4) |
| POST | `/evaluate` | Evalúa una transacción completa (requiere `id` y `timestamp`) |
| POST | `/evaluate/auto` | Igual, pero autogenera `id`/`timestamp` (usado por la UI) |
| GET | `/reports` | Lista los reportes de auditoría de transacciones `DECLINE` |
| GET | `/reports/{id}` | Reporte de auditoría de una transacción específica |
| POST | `/reset` | Limpia todo el estado en memoria (para demos) |

## Dependencias

Ver `requirements.txt`: `fastapi`, `uvicorn`, `pydantic`, `pytest`, `httpx`.

## Bitácora de prompts

Ver [`PROMPTS.md`](PROMPTS.md).
