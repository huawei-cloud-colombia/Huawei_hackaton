# PROMPT — SENTINELPAY RISK ENGINE

## Fundación, arquitectura, ingesta y reglas base

### Rol

Actúa como un **ingeniero de software senior especializado en Python, sistemas de scoring de riesgo, procesamiento de transacciones, arquitectura modular, testing y seguridad**.

Tu objetivo en esta etapa es construir la **fundación funcional** de SentinelPay Risk Engine.

Este es el primer paso de un desarrollo progresivo. **NO implementes todavía las funcionalidades de las fases 2, 3 o 4 ni los bonos.**

Debes dejar una base sólida, ejecutable y testeada sobre la cual podamos continuar con los siguientes prompts.

---

## 1. Inspecciona primero el repositorio

Antes de modificar cualquier archivo:

1. Recorre la estructura del proyecto.
2. Identifica:

   * versión de Python;
   * punto de entrada;
   * arquitectura existente;
   * dependencias;
   * tests;
   * configuración;
   * documentación;
   * datasets;
   * código relacionado con transacciones o scoring.
3. Reutiliza código existente cuando sea razonable.
4. No destruyas funcionalidades existentes sin necesidad.
5. Identifica qué debe crearse y qué puede reutilizarse.

Después de inspeccionar, continúa directamente con la implementación.

---

# 2. Requisito tecnológico

La implementación debe realizarse principalmente en:

**Python 3.11+**

Utiliza:

* type hints;
* arquitectura modular;
* Pydantic o equivalente para validación;
* pytest para pruebas;
* configuración externa;
* excepciones controladas.

La lógica de negocio no debe estar mezclada directamente con la interfaz.

---

# 3. Arquitectura inicial

Construye una arquitectura similar a:

```text
sentinelpay/
├── app/
│   ├── models/
│   ├── ingestion/
│   ├── rules/
│   ├── scoring/
│   ├── config/
│   └── services/
├── tests/
├── data/
├── docs/
├── README.md
├── requirements.txt
└── .env.example
```

Adapta los nombres a la estructura existente.

No crees una arquitectura monolítica.

---

# 4. Modelo de transacción

Implementa un modelo Python para una transacción.

Debe soportar como mínimo:

```text
id
card_id
merchant_id
amount
currency
country
ip_country
device_id
ip
timestamp
```

Ejemplo:

```json
{
  "id": "txn_00234",
  "card_id": "card_9F21",
  "merchant_id": "merch_petshop_bog",
  "amount": 850000,
  "currency": "COP",
  "country": "CO",
  "ip_country": "RU",
  "device_id": "dev_a19x",
  "ip": "185.220.101.14",
  "timestamp": "2024-11-28T04:58:12Z"
}
```

Valida:

* campos obligatorios;
* tipos;
* monto válido;
* timestamp válido;
* identificadores no vacíos.

---

# 5. Motor de evaluación

Implementa:

```python
evaluate(transaction)
```

Debe devolver una estructura claramente definida.

Como mínimo:

```json
{
  "transaction_id": "txn_00234",
  "score": 40,
  "decision": "REVIEW",
  "reasons": []
}
```

En esta fase el score será únicamente el resultado de las reglas base.

---

# 6. Reglas obligatorias

Implementa estas tres reglas:

### Regla 1 — Monto anómalo

Si:

```text
amount > 3 × promedio histórico de esa tarjeta
```

sumar:

```text
+25
```

al score.

Debes implementar una forma de mantener el promedio histórico en memoria.

No es necesario utilizar una base de datos externa.

---

### Regla 2 — País diferente

Si:

```text
country != ip_country
```

sumar:

```text
+30
```

---

### Regla 3 — Hora inusual

Si la transacción ocurre entre:

```text
01:00 y 05:00
```

hora local del comercio:

```text
+10
```

La implementación debe documentar claramente cómo determina la hora local.

Si no existe información de timezone del comercio, implementa una estrategia configurable y documentada.

---

# 7. Reglas configurables

No hardcodees los pesos directamente dentro de la lógica.

Crea una configuración equivalente a:

```yaml
rules:
  anomalous_amount:
    enabled: true
    weight: 25

  country_mismatch:
    enabled: true
    weight: 30

  unusual_hour:
    enabled: true
    weight: 10
```

Puede utilizarse JSON, YAML, `.env` u otra solución razonable.

Cada regla debe poder:

* activarse;
* desactivarse;
* modificar su peso.

---

# 8. Explicabilidad

Cada regla disparada debe aparecer en `reasons`.

Ejemplo:

```json
{
  "rule": "country_mismatch",
  "weight": 30,
  "detail": "card_country=CO, ip_country=RU"
}
```

Otro ejemplo:

```json
{
  "rule": "unusual_hour",
  "weight": 10,
  "detail": "04:58 local time"
}
```

Nunca devuelvas únicamente el score.

Debe poder saberse qué reglas contribuyeron al resultado.

---

# 9. Persistencia

En esta fase está permitido mantener el estado en memoria.

Implementa una estructura Python segura para conservar:

* promedio histórico por tarjeta;
* transacciones procesadas;
* resultados.

Diseña esta estructura pensando en que será utilizada posteriormente por las ventanas deslizantes de la fase 2.

---

# 10. Validación de errores

El sistema debe manejar correctamente:

* monto negativo;
* monto cero;
* timestamp inválido;
* campos faltantes;
* card_id vacío;
* device_id vacío;
* IP inválida;
* datos inconsistentes.

Una transacción inválida no debe tumbar todo el proceso.

---

# 11. Testing

Implementa pytest.

Cubre como mínimo:

### Monto

* monto normal;
* monto > 3x promedio;
* historial inexistente;
* monto inválido.

### País

* mismo país;
* país diferente.

### Hora

* 00:59;
* 01:00;
* 04:59;
* 05:00;
* horario normal.

### Configuración

* regla habilitada;
* regla deshabilitada;
* peso personalizado.

### Validación

* campo faltante;
* timestamp inválido;
* monto negativo.

---

# 12. Caso obligatorio del reto

Debes poder reproducir el caso:

```text
country = CO
ip_country = RU
hora = 04:58
```

El resultado debe incluir:

```text
country_mismatch = +30
unusual_hour = +10
score = 40
```

El reto establece precisamente este comportamiento para la fase 1.

---

# 13. README

Documenta:

* arquitectura;
* instalación;
* versión Python;
* dependencias;
* configuración;
* cómo ejecutar;
* cómo ejecutar tests;
* ejemplo de transacción;
* ejemplo de resultado.

---

# 14. Qué NO implementar todavía

No implementes todavía:

* sliding window;
* velocity checks;
* blocklist temporal;
* circuit breaker;
* mock_bank_auth;
* scoring completo de fase 3;
* interfaz gráfica;
* bonos;
* grafo de fraude.

Esas funcionalidades serán construidas posteriormente.

---

# 15. Verificación final

Antes de terminar:

1. instala dependencias;
2. ejecuta pytest;
3. corrige errores;
4. prueba el caso CO/RU/04:58;
5. verifica configuración de reglas;
6. verifica validación;
7. verifica que el repositorio siga ejecutándose.

Al finalizar, entrega un resumen de:

* archivos creados/modificados;
* arquitectura;
* funcionalidades implementadas;
* tests ejecutados;
* resultado de los tests;
* cómo ejecutar el proyecto.

**No afirmes que una prueba fue ejecutada si realmente no la ejecutaste.**

El resultado de este prompt debe ser una **base Python funcional y estable para continuar con la Fase 2.**
