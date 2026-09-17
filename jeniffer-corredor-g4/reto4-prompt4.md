# PROMPT — SENTINELPAY RISK ENGINE

## Fase 4 — Interfaz gráfica de verificación

### Contexto

El motor Python ya debe tener implementadas y testeadas:

* ingesta;
* validación;
* reglas base;
* scoring;
* sliding windows;
* velocity checks;
* blocklist;
* circuit breaker;
* resiliencia;
* explicabilidad.

Ahora construye la interfaz gráfica del sistema.

---

# 1. Framework

Utiliza preferentemente:

**Streamlit**

y Python.

La interfaz debe conectarse directamente con los servicios existentes.

No dupliques la lógica de scoring dentro de Streamlit.

---

# 2. Objetivo

Un juez debe poder probar todo el sistema:

**sin consola, curl ni Postman.**

El reto exige explícitamente esta experiencia.

---

# 3. Formulario

Crea un formulario para:

* card_id;
* merchant_id;
* amount;
* currency;
* country;
* ip_country;
* device_id;
* ip;
* timestamp.

No obligues al usuario a escribir JSON.

---

# 4. Resultado

Después de presionar:

```text
Evaluar
```

mostrar:

```text
Score: 40
Decision: REVIEW
```

y las razones.

Mostrar:

* regla;
* peso;
* detalle;
* bank auth status.

---

# 5. Visualización

Utiliza una presentación clara.

Idealmente:

```text
APPROVE → verde
REVIEW → amarillo
DECLINE → rojo
```

El objetivo es que el juez pueda entender el resultado en segundos.

---

# 6. Simulación de ráfaga

Implementa un botón:

```text
Simular ráfaga
```

Debe permitir:

```text
N = 6
```

y enviar N transacciones rápidamente utilizando la misma tarjeta.

Mostrar cada resultado:

```text
#1 APPROVE
#2 APPROVE
#3 APPROVE
#4 APPROVE
#5 APPROVE
#6 DECLINE
```

y mostrar:

```text
velocity_limit_exceeded
```

cuando corresponda.

El reto especifica que esta demostración debe poder hacerse directamente desde la interfaz.

---

# 7. Estado visual

Mostrar claramente:

* blocklist activa;
* tiempo restante del bloqueo;
* estado del circuit breaker;
* número de transacciones recientes;
* reglas activadas.

---

# 8. Historial

Agrega una sección para visualizar las últimas evaluaciones.

Mostrar:

* transaction_id;
* timestamp;
* score;
* decision;
* principales razones.

---

# 9. Casos de demostración

Incluye botones o ejemplos precargados para:

### P1 / alto riesgo

Caso con múltiples señales.

### Card testing

Ráfaga de 6 transacciones.

### Country mismatch

CO/RU.

### Unusual hour

04:58.

### Approve

Caso limpio.

### Review

Score entre 40 y 74.

---

# 10. UX

La interfaz debe ser:

* sencilla;
* profesional;
* clara;
* rápida;
* demostrable.

No sacrifiques funcionalidad por diseño.

---

# 11. Testing

Verifica:

* aplicación inicia;
* formulario funciona;
* evaluación funciona;
* resultado aparece;
* razones aparecen;
* ráfaga funciona;
* blocklist se refleja;
* errores se muestran correctamente.

Si el proyecto tiene tests de UI, ejecútalos.

También ejecuta todos los tests Python existentes.

---

# 12. README

Actualiza instrucciones:

```bash
streamlit run ...
```

Explica:

* instalación;
* ejecución;
* flujo de demo;
* cómo reproducir card testing.

---

# 13. Criterio de terminado

Un juez debe poder:

1. abrir el navegador;
2. ingresar una transacción;
3. presionar Evaluar;
4. ver score;
5. ver decisión;
6. ver razones;
7. presionar Simular ráfaga;
8. observar el bloqueo.

Todo sin tocar código.

No implementes todavía los bonos avanzados.
