# PROMPT — SENTINELPAY RISK ENGINE

## Fase 3 — Scoring ponderado y resiliencia

### Contexto

El proyecto ya contiene:

* Fase 1;
* reglas configurables;
* validación;
* explicabilidad;
* sliding windows;
* velocity checks;
* blocklist temporal.

Ahora implementa la Fase 3.

No elimines ni reemplaces funcionalidades anteriores.

---

# 1. Scoring único

Combina todas las señales en un único score:

```text
0–100
```

Reglas:

```text
APPROVE < 40
REVIEW 40–74
DECLINE >= 75
```

El score nunca puede superar 100.

Implementa una estrategia clara de normalización/cap.

---

# 2. Señales

Integra:

### Fase 1

* anomalous amount;
* country mismatch;
* unusual hour.

### Fase 2

* card velocity;
* device velocity;
* temporal block.

Cada señal debe conservar:

```text
rule
weight
detail
```

---

# 3. Resultado

La función principal debe devolver una estructura equivalente a:

```json
{
  "transaction_id": "txn_00234",
  "score": 40,
  "decision": "REVIEW",
  "reasons": [
    {
      "rule": "country_mismatch",
      "weight": 30,
      "detail": "card_country=CO, ip_country=RU"
    },
    {
      "rule": "unusual_hour",
      "weight": 10,
      "detail": "04:58 local time"
    }
  ],
  "bank_auth_status": "..."
}
```

---

# 4. Mock Bank Authorization

Implementa:

```python
mock_bank_auth()
```

Debe simular un servicio externo que:

* ocasionalmente falla;
* ocasionalmente demora;
* puede producir timeout.

Utiliza aproximadamente:

```text
30% de probabilidad
```

de fallo o demora superior a 2 segundos.

Hazlo configurable y testeable.

No hagas que los tests dependan de aleatoriedad real.

Permite inyectar un mock/deterministic failure para testing.

---

# 5. Circuit Breaker

Implementa un circuit breaker.

Estados:

```text
CLOSED
OPEN
HALF_OPEN
```

Comportamiento:

### CLOSED

Las llamadas se realizan normalmente.

### Después de 3 fallos consecutivos

Cambiar a:

```text
OPEN
```

Durante:

```text
15 segundos
```

no realizar llamadas al servicio externo.

### OPEN

La transacción debe degradarse de forma segura.

Ejemplo:

```text
REVIEW
```

con:

```text
bank_auth_status = circuit_open_degraded
```

### Después de 15 segundos

Cambiar a:

```text
HALF_OPEN
```

Permitir una sola llamada de prueba.

Si funciona:

```text
CLOSED
```

Si falla:

```text
OPEN
```

---

# 6. Resiliencia

No permitas que la caída de `mock_bank_auth()` tumbe el motor completo.

Debe existir siempre una respuesta controlada.

---

# 7. Explicabilidad

Cada resultado debe contener el desglose de las reglas.

No devuelvas solamente:

```text
score=90
```

Debe poder determinarse:

```text
qué reglas
qué pesos
qué detalles
```

produjeron el score.

---

# 8. Testing

Agrega tests para:

* score < 40;
* score 40;
* score 74;
* score 75;
* score > 100;
* múltiples reglas;
* bank auth exitoso;
* bank auth timeout;
* 1 fallo;
* 2 fallos;
* 3 fallos;
* circuito abierto;
* circuito abierto durante 15 segundos;
* transición a HALF_OPEN;
* recuperación;
* nuevo fallo en HALF_OPEN.

Utiliza tiempo controlable en tests cuando sea necesario.

No hagas tests frágiles esperando físicamente 15 segundos.

---

# 9. Casos obligatorios

Reproduce el ejemplo del reto:

```text
country = CO
ip_country = RU
hora = 04:58
```

Resultado:

```text
score = 40
decision = REVIEW
```

El reto utiliza este caso como ejemplo de salida de Fase 3.

También reproduce el escenario de card testing de Fase 2.

---

# 10. Calidad

Mantén:

* modularidad;
* type hints;
* tests;
* configuración;
* separación entre dominio y servicios externos.

El circuit breaker no debe quedar mezclado dentro de una función gigante.

---

# 11. Verificación

Ejecuta todos los tests existentes y los nuevos.

Corrige cualquier regresión.

Verifica:

```text
Fase 1
+
Fase 2
+
Fase 3
```

funcionando juntas.