# Bitácora de uso de GLM 5.2

## Sesión de desarrollo — RETO_3_NEXUS_LIVE

### Fase 0 — Planificación
- **Prompt inicial:** Análisis completo del enunciado + decisiones de arquitectura (colas, pago dummy, recurrencia).
- **Resultado:** `desarrollar.md` con 16 secciones, checklist de cobertura y mapeo a rúbrica.
- **Decisión del equipo:** El equipo no siguió la primera recomendación del modelo de usar Redis para la cola. Se optó por ThreadPoolExecutor de la biblioteca estándar para minimizar dependencias.

### Fase 1 — Motor de asientos y HOLDs
- **Implementación:** config.py, db.py, seat_service.py, hold_service.py, audit_service.py.
- **Audit:** 7 checks (reserva normal, double-booking, todo-o-nada, límite 6, liberar, trazabilidad). Todos pasaron.

### Fase 2 — Concurrencia e idempotencia
- **Implementación:** queue_service.py (SessionQueue 50), idempotency_service.py.
- **Audit:** Carrera de 20 y 100 usuarios → 1 ganador, 0 overselling. Idempotencia replay + conflicto.
- **Propuesta de GLM 5.2 corregida:** El modelo sugirió usar `queue.Queue` directamente. El equipo prefirió `ThreadPoolExecutor` + `BoundedSemaphore` para mejor control del timeout.

### Fase 3 — Pago, circuit breaker y recurrencia
- **Implementación:** payment_mock.py, circuit_breaker.py, payment_service.py, recurrence_service.py.
- **Error encontrado con ayuda del agente:** Deadlock en CircuitBreaker. `allow_request()` adquiría `self._lock` y luego llamaba `self.state` que también adquiría `self._lock`. `threading.Lock` no es reentrante → deadlock. Corregido a `threading.RLock`.
- **Error encontrado:** `recurrence_service.charge_next` no incluía `interval_days` en el SELECT. Corregido.
- **Audit:** 10 checks (APPROVED→SOLD, DECLINED→libera, ERROR/TIMEOUT→mantiene, CB OPEN→503, CB HALF_OPEN→CLOSED, recurrencia 3 cuotas). Todos pasaron.

### Fase 4 — Interfaz
- **Implementación:** index.html, style.css, app.js.
- **Error encontrado:** Colisión de nombres `status` (HTTP code vs domain status). El route handler extraía "SOLD" como HTTP code. Corregido: solo se pop "status" cuando hay "error".
- **Audit:** 12 checks end-to-end con Flask test client. Todos pasaron.

### Fase 5 — Tests
- **Implementación:** 8 archivos de test, 45 tests totales.
- **Error encontrado:** `test_expiracion_automatica` modificaba `config.HOLD_TTL_SECONDS = 1` globalmente, contaminando tests posteriores. Corregido reseteando en el fixture `fresh_db`.
- **Resultado:** 45/45 pasan en 15s.

### Resumen
- **Prompts enviados:** 2 principales (arquitectura + implementación).
- **Audits realizados:** 7 (uno por paso).
- **Bugs encontrados y corregidos con ayuda del agente:** 4 (deadlock, IndexError, colisión de nombres, contaminación de config).
- **Decisión donde el equipo no siguió al modelo:** Redis → ThreadPoolExecutor estándar.
