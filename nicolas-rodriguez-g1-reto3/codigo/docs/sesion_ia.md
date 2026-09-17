# Bitácora de Sesión de IA - Reto 3 NEXUS LIVE

## Sesión 1 - Análisis y Arquitectura

**Fecha:** 2026-09-17
**Modelo:** GLM 5.2 (vía Copilot SDK)

### Análisis del enunciado

Se analizó el enunciado de NEXUS LIVE que describe:
- 180,000 usuarios esperando, 42,000 asientos disponibles
- SeatLock component inestable que necesita reconstrucción
- 4 fases: SeatLock, Concurrencia, Confirmación, Interfaz
- 4 bonos: Sala de espera, Prueba de concurrencia, Auditoría, GLM en producto

### Decisiones de arquitectura

1. **Mecanismo de concurrencia:** `threading.RLock` (reentrant lock)
   - Protege todas las operaciones de cambio de estado
   - Reentrant para permitir expiración automática anidada
   - Garantiza atomicidad de verificación + cambio de estado

2. **Estrategia de idempotencia:** Header `Idempotency-Key`
   - Cache de payload normalizado + resultado
   - Replay: mismo resultado
   - Conflicto: error si payload difiere

3. **Estrategia de pago:**
   - APPROVED → SOLD
   - DECLINED → liberar HOLD
   - ERROR/TIMEOUT → mantener HOLD (no vender sin certeza)
   - Circuit breaker protege contra servicio degradado

4. **Trazabilidad:** Lista de TraceEvent en memoria
   - Cada cambio de estado se registra
   - Consultable por hold_id o global

---

## Sesión 2 - Implementación

### Fase 1 - SeatLock
- Modelos: Seat, Hold, TraceEvent con Pydantic v2
- Engine con RLock, reserve(), confirm_hold(), release_hold()
- Expiración automática lazy
- Validaciones: user_id, seat_ids, duplicados, límites

### Fase 2 - Concurrencia e Idempotencia
- Test: 100 usuarios concurrentes → 1 ganador, 99 rechazadas
- Idempotency-Key con cache de resultados
- Detección de conflictos

### Fase 3 - Checkout y Circuit Breaker
- MockPaymentProvider con APPROVED/DECLINED/ERROR/TIMEOUT
- CircuitBreaker: CLOSED → OPEN → HALF_OPEN
- CheckoutService orquesta todo

### Fase 4 - Interfaz
- NEXUS Control Room con Jinja2
- Mapa de asientos interactivo
- Simulador de carreras
- Control de circuit breaker y pagos

---

## Sesión 3 - Bonos

### Bono A - FairWaitlist
- FIFO con anti-monopolio
- Timeout de entradas
- Abandono voluntario

### Bono B - Tests de concurrencia real
- 20, 50, 100, 200 usuarios
- Carreras simultáneas sobre asientos diferentes

### Bono C - Trazabilidad reproducible
- TraceEvent con timestamp, from_state, to_state, reason
- Exportable via API

### Bono D - OperationsExplainer
- Integración con GLM 5.2
- Fallback rule-based
- Maneja timeout, empty, error, unexpected format

---

## Problemas encontrados y resueltos

1. **Race condition en expiración:** La expiración automática podía interferir con otras operaciones. Solución: `_expire_all()` siempre dentro del lock.

2. **Deadlock potencial:** Lock simple podía causar deadlock si la expiración llamaba a otros métodos protegidos. Solución: RLock reentrant.

3. **Estrategia de timeout:** GLM sugirió liberar HOLD en timeout, pero el enunciado lo prohíbe. Solución: mantener HOLD activo, permitir reintento.

4. **Tests aleatorios:** Los tests de concurrencia a veces fallaban. Solución: idempotency keys únicos por test para evitar interferencia.
