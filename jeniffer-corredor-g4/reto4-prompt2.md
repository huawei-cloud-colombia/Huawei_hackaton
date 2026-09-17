# PROMPT — SENTINELPAY RISK ENGINE

## Fase 2 — Detección de Card Testing

### Contexto

Ya existe una primera versión funcional del SentinelPay Risk Engine que implementa:

* modelo de transacción;
* ingesta;
* validación;
* reglas base;
* scoring parcial;
* razones explicables;
* configuración;
* tests.

Ahora debes **extender la implementación existente** para incorporar la Fase 2 del reto.

No reescribas innecesariamente la Fase 1.

---

# 1. Inspección

Antes de modificar:

1. revisa lo implementado;
2. ejecuta los tests existentes;
3. identifica la arquitectura;
4. verifica que la Fase 1 funcione;
5. diseña dónde incorporar velocity tracking.

Si existen errores previos, corrígelos sin romper las funcionalidades existentes.

---

# 2. Sliding Window

Implementa un mecanismo de ventana deslizante.

No utilices una ventana fija ingenua.

Debe existir tracking independiente por:

```text
card_id
device_id
```

El sistema debe conservar timestamps de las transacciones recientes y eliminar automáticamente los eventos que queden fuera de la ventana.

---

# 3. Regla de velocidad por tarjeta

Implementa:

```text
más de 5 transacciones
en 10 segundos
→ +40 puntos
```

Los valores deben ser configurables.

Por ejemplo:

```yaml
velocity:
  card:
    threshold: 5
    window_seconds: 10
    weight: 40
```

La regla debe activarse cuando la transacción actual hace que se supere el límite.

---

# 4. Regla por dispositivo

Implementa:

```text
3 tarjetas diferentes
usando el mismo device_id
en 30 segundos
→ +50 puntos
```

Debe contar tarjetas distintas, no simplemente transacciones.

Ejemplo:

```text
device_A
├── card_1
├── card_2
└── card_3
```

debe activar la regla.

---

# 5. Blocklist temporal

Cuando una tarjeta o dispositivo supere el umbral:

1. agregarlo a una blocklist temporal;
2. guardar timestamp de expiración;
3. duración configurable.

Valor inicial:

```text
120 segundos
```

La blocklist debe expirar automáticamente.

No debe ser necesario reiniciar la aplicación para desbloquear.

---

# 6. Evaluación de transacciones bloqueadas

Si una tarjeta está temporalmente bloqueada:

```text
DECLINE
```

inmediatamente.

Razón:

```text
card_temporarily_blocked
```

No vuelvas a ejecutar todas las reglas innecesariamente.

---

# 7. Velocity Limit

Cuando se activa el límite de tarjeta:

```text
DECLINE
```

con razón equivalente a:

```text
velocity_limit_exceeded: 6 txns in 7s (limit: 5 in 10s)
```

La información debe generarse dinámicamente.

---

# 8. Ejemplo obligatorio

Simula:

```text
6 transacciones
misma tarjeta
7 segundos
montos entre 5.000 y 15.000 COP
```

La transacción número 6 debe:

* activar velocity;
* sumar +40;
* bloquear temporalmente;
* retornar DECLINE;
* explicar la razón.

Las transacciones posteriores dentro de 120 segundos deben devolver:

```text
DECLINE
card_temporarily_blocked
```

El comportamiento está definido explícitamente en la Fase 2 del reto.

---

# 9. Estado y expiración

La implementación debe evitar que la memoria crezca indefinidamente.

Limpia:

* timestamps antiguos;
* bloqueos expirados;
* estructuras que ya no sean necesarias.

---

# 10. Integración con Fase 1

No rompas:

* reglas base;
* configuración;
* razones;
* validación;
* API/función `evaluate`.

El resultado debe integrar las nuevas señales.

---

# 11. Testing

Agrega tests para:

* 1 transacción;
* 5 transacciones;
* sexta transacción;
* expiración;
* transacción durante bloqueo;
* bloqueo por device;
* 3 tarjetas distintas;
* misma tarjeta repetida;
* timestamps fuera de ventana;
* limpieza de estado.

También prueba casos donde los eventos están justo en los límites temporales.

---

# 12. Concurrencia

Diseña el componente de estado de manera que pueda evolucionar hacia procesamiento concurrente.

Si implementas locks en esta fase, deben ser Python estándar y estar encapsulados dentro del componente de estado.

No hagas todavía el bono completo de prueba de carga.

---

# 13. Qué NO implementar todavía

No implementes todavía:

* circuit breaker;
* mock_bank_auth;
* interfaz gráfica;
* bonos;
* grafo;
* auditoría IA.

---

# 14. Verificación

Ejecuta:

```bash
pytest
```

y cualquier otro test necesario.

Prueba manualmente la ráfaga de 6 transacciones.

Corrige todos los errores encontrados.

Al finalizar entrega:

* archivos modificados;
* arquitectura;
* comportamiento implementado;
* tests ejecutados;
* resultado;
* instrucciones para reproducir la ráfaga.

La Fase 2 debe quedar **completamente funcional antes de continuar**.
