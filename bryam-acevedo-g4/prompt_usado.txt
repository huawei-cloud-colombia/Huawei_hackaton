# Bitácora de prompts

> Nota de contexto: el plan original era usar **GLM 5.2** (Huawei MaaS) como copiloto, tal como pide el enunciado del reto. Durante el hackathon se agotó una parte importante del tiempo intentando conectar OpenCode/Continue a Huawei MaaS (problemas de región en la consola, permisos IAM, y una "Virtual Key" entregada por el equipo de integración que resultó ser de un tipo/infraestructura distinta a la esperada — confirmado con pruebas `curl` directas contra el endpoint, que devolvían `Invalid authorization header` incluso con el formato correcto). Para no perder el tiempo restante, se decidió construir el proyecto con un asistente de IA de propósito general como copiloto, dejando documentado el intento de conexión a GLM 5.2 como parte del proceso real vivido en el hackathon.

## 1. Planeación de arquitectura

**Prompt (resumen):** "Aquí está el enunciado completo del reto 4 (SentinelPay Risk Engine). Quiero un stack Python con FastAPI + HTML simple. Constrúyelo fase por fase sin saltarte prerequisitos."

**Resultado:** se definió la estructura de carpetas (`app/engine.py`, `app/bank.py`, `app/models.py`, `app/main.py`, `app/static/`), separando reglas de negocio (motor), infraestructura simulada (banco/circuit breaker) y capa HTTP.

## 2. Fase 1 — Ingesta y reglas base

**Prompt (resumen):** "Implementa `evaluate(transaction)` con las 3 reglas estáticas del enunciado (monto anómalo, país distinto, hora inusual), cada una con peso y activación configurables."

**Iteración:** se decidió calcular el promedio histórico de la tarjeta **antes** de registrar el monto de la transacción actual (para no auto-contaminar su propio promedio), y se documentó explícitamente el supuesto de que el `timestamp` recibido ya está en hora local del comercio.

## 3. Fase 2 — Ventanas deslizantes y blocklist

**Prompt (resumen):** "Agrega detección de card testing con sliding window real (no ventana fija) y blocklist temporal con expiración automática."

**Iteración clave:** la primera versión solo sumaba puntaje por velocidad, pero el ejemplo del enunciado exige que la transacción #6 sea `DECLINE` aunque el score acumulado (40) caiga en rango `REVIEW` (40-74). Se introdujo el concepto de `hard_decline`: ciertas reglas (velocidad por tarjeta, velocidad por dispositivo) fuerzan `DECLINE` sin importar el score total, replicando cómo un sistema antifraude real trataría una señal crítica.

## 4. Fase 3 — Scoring ponderado + resiliencia

**Prompt (resumen):** "Combina las señales en un score 0-100 con umbrales APPROVE/REVIEW/DECLINE, simula `mock_bank_auth()` con 30% de fallo, e implementa un circuit breaker (abre tras 3 fallos seguidos, semi-abierto tras 15s)."

**Iteración:** se decidió sacar la llamada al banco simulado **fuera** del lock de concurrencia, para que el circuit breaker no serialice todas las evaluaciones — solo las mutaciones de estado compartido (ventanas, blocklist) necesitan exclusión mutua.

## 5. Fase 4 — Interfaz gráfica

**Prompt (resumen):** "Arma una UI simple servida por el mismo FastAPI: formulario sin JSON a mano, resultado con colores por decisión, y un botón que dispare 6 transacciones seguidas para ver el bloqueo en vivo."

**Resultado:** `index.html` + `app.js` vanilla, sin build step. El botón de ráfaga reutiliza el mismo endpoint `/evaluate/auto` que usaría un usuario real, para que la demo sea fiel al comportamiento de la API.

## 6. Bonos

- **Bono A (grafo de colusión):** prompt: "Detecta cuando varias tarjetas distintas comparten el mismo device_id o ip en poco tiempo, y explica qué tarjetas están conectadas." Se reutilizó la misma estructura de ventana deslizante ya construida para velocidad, evitando duplicar lógica.
- **Bono B (concurrencia):** prompt: "Escribe una prueba con hilos reales (no solo afirmarlo) que demuestre que el conteo por tarjeta no pierde actualizaciones."
  - **Bug real encontrado y corregido durante la iteración:** la primera versión de la prueba de concurrencia fallaba (solo 4 de 30 "tarjetas distintas" quedaban registradas). Se investigó paso a paso (trazas con hilos, logging de `set` en el diccionario) antes de concluir que **no era una condición de carrera**: las transacciones de prueba compartían el mismo `device_id` por defecto, así que la regla `device_card_hopping` bloqueaba legítimamente las tarjetas siguientes. Se corrigió la prueba (no el motor) asignando `device_id`/`ip` únicos por hilo. Este proceso de diagnóstico quedó documentado aquí porque es exactamente el tipo de "pensamiento crítico sobre la respuesta de la IA" que pide la rúbrica: no se aceptó el resultado a ciegas, se verificó la causa raíz antes de decidir qué cambiar.
- **Bono C (explicabilidad):** ver nota al inicio de este documento — implementado con plantilla determinística en vez de un LLM real, por el bloqueo de acceso a GLM 5.2.
- **Bono D (pruebas adversariales):** prompt: "Escribe pruebas que simulen ataques reales: ráfaga de microtransacciones, spoofing de IP entre transacciones consecutivas, dispositivo reciclado entre tarjetas." Se verificó que cada patrón dispara la regla esperada de forma aislada.

## 7. Verificación final

Se corrió la suite completa (`pytest -v`, 18/18 tests) y se levantó el servidor real (`uvicorn`) para probar manualmente con `curl`: evaluación individual (caso de ejemplo del enunciado, país+hora → score 40, REVIEW), ráfaga de 6 transacciones (6ª → DECLINE por velocidad), y el endpoint de reportes de auditoría — confirmando que el comportamiento end-to-end coincide con los ejemplos del enunciado antes de dar el proyecto por terminado.
