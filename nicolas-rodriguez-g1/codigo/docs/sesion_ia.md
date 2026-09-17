# Bitacora de uso de GLM 5.2

## Sesion de desarrollo - Reto 1: ATLAS CLOUD // SIGNAL-80

### Prompt 1: Arquitectura
**Fecha:** 2026-09-17
**Prompt:** "Necesito una arquitectura para un motor de triage de 12.847 tickets con FastAPI + Pydantic, cliente GLM 5.2 con reintentos, y validacion de salida."
**Resultado:** Estructura modular con separacion de concerns: schemas, client, engine, API.

### Prompt 2: Esquema de clasificacion
**Prompt:** "Define un esquema Pydantic para triage con categoria (8 valores), prioridad (P1-P4), sentimiento, confidence 0-1."
**Iteracion:** GLM sugirio confidence como int 0-100. Se corrigio a float 0-1 segun enunciado.

### Prompt 3: Prompt injection
**Prompt:** "Como proteger el sistema contra tickets maliciosos que intentan manipular al modelo?"
**Resultado:** Separar system prompt de datos, detectar patrones, validar salida, no incluir secretos.

### Prompt 4: Correlacion
**Prompt:** "Como agrupar tickets que describen el mismo incidente?"
**Resultado:** Combinar similitud semantica + categoria + modulo + region + ventana temporal.

### Prompt 5: Circuit breaker / resiliencia
**Prompt:** "Como manejar fallos de API de GLM?"
**Resultado:** Reintentos con backoff exponencial, fallback a reglas, modo demo sin API key.

### Edge cases descubiertos:
1. GLM devuelve texto antes del JSON → regex extractor
2. Ticket ambiguo "Hay un problema." → confianza 0.30, human review
3. Prompt injection → categoria Seguridad, human review
4. Ticket vacio → error controlado, no detiene batch
5. JSON incrustado en texto → se procesa normalmente
