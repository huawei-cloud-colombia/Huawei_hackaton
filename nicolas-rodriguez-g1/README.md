# ATLAS CLOUD // SIGNAL-80
## Motor Inteligente de Triage y Correlacion de Incidentes

### Nicolas Rodriguez Ricardo - MESA-RETO1

---

## Stack

- **Lenguaje:** Python 3.10+
- **Framework:** FastAPI (API REST + servidor web)
- **Validacion:** Pydantic v2 (schemas y validacion de salida)
- **Cliente HTTP:** httpx (llamadas a GLM 5.2)
- **Interfaz:** HTML/CSS/JS (Jinja2 templates)
- **Tests:** pytest

## Arquitectura

```
codigo/
├── app/
│   ├── main.py              # API FastAPI + ATLAS Control Room (Fase 4)
│   ├── schemas.py           # Esquemas Pydantic (validacion)
│   ├── glm_client.py        # Cliente GLM 5.2 (reintentos, backoff, modo demo)
│   ├── triage_engine.py     # Motor de triage (Fases 1-2)
│   ├── correlation_engine.py # Motor de correlacion (Fase 3)
│   ├── config.json          # Configuracion (categorias, prioridades, umbrales)
│   ├── templates/
│   │   └── index.html       # ATLAS Control Room (interfaz grafica)
│   └── static/
├── tests/
│   ├── test_atlas.py        # Tests Fases 1-3 + Bono A
│   └── test_concurrency.py  # Tests Bono B
├── data/
│   └── tickets_sample.json  # Dataset de ejemplo (20 tickets)
└── docs/
    └── sesion_ia.md         # Bitacora de prompts
```

## Configuracion de GLM 5.2

El sistema usa GLM 5.2 como motor semantico principal. La configuracion esta en `app/config.json`:

- Modelo: `glm-5.2`
- API: `https://open.bigmodel.cn/api/paas/v4`
- Temperature: 0.1 (deterministico)
- Max tokens: 1024
- Timeout: 30s
- Max reintentos: 3 con backoff exponencial

### Modo Demo

Si no hay API Key configurada, el sistema opera en **modo demo** usando clasificacion por reglas. Esto permite probar toda la funcionalidad sin dependencia externa.

## Variables de entorno

| Variable | Descripcion | Ejemplo |
|----------|-------------|---------|
| `GLM_API_KEY` | API Key para GLM 5.2 | (ver .env.example) |

Copie `.env.example` a `.env` y configure su API Key:

```bash
cp .env.example .env
# Editar .env con su API Key real
```

## Instalacion

```bash
cd codigo
pip install -r ../requerimientos.txt
```

## Ejecucion

```bash
cd codigo
uvicorn app.main:app --reload --port 8000
```

Abrir http://localhost:8000 en el navegador.

## Tests

```bash
cd codigo
python -m pytest tests/ -v
```

## Apertura de la interfaz

La interfaz ATLAS Control Room esta disponible en http://localhost:8000

Permite:
1. **Cargar dataset de ejemplo** - Procesa 20 tickets de muestra
2. **Probar ticket manual** - Formulario para escribir un ticket nuevo
3. **Ver cola priorizada** - Tickets ordenados por prioridad (P1-P4)
4. **Filtrar** - Por prioridad y categoria
5. **Inspeccionar ticket** - Detalle completo de cada ticket
6. **Visualizar grupos de incidentes** - Tickets correlacionados
7. **Generar brief ejecutivo** - Para incidentes mayores (Bono D)

## Procesamiento por lote

Endpoint: `POST /api/triage/batch`

Acepta un array de tickets y los procesa **concurrentemente** (hasta `max_concurrent_requests`, configurable en `config.json`, por defecto 5 a la vez) usando un `ThreadPoolExecutor`, para no exceder irresponsablemente la cuota del modelo. Los resultados se devuelven en el mismo orden de entrada, sin perder ni duplicar tickets. Un ticket malformado no detiene el resto del lote.

Las rutas de la API que llaman al motor (`/api/triage`, `/api/triage/batch`, `/api/load-sample`, `/api/incident/{id}/brief`) ejecutan esas llamadas en un threadpool (`starlette.concurrency.run_in_threadpool`) para no bloquear el event loop de FastAPI mientras GLM 5.2 responde o se reintenta con backoff.

## Validacion de respuestas

El sistema valida la salida de GLM 5.2 usando Pydantic:
- Categoria debe ser una de 8 valores validos
- Prioridad debe ser P1, P2, P3 o P4
- Sentimiento debe ser valido
- Confianza entre 0.0 y 1.0
- Campos de texto truncados a longitud maxima

Si la validacion falla, se usa un valor por defecto y se registra en auditoria.

## Politica de retries

- Maximo 3 intentos
- Backoff exponencial: 1s, 2s, 4s
- Si todos los intentos fallan, se usa el fallback de reglas (modo demo)
- No hay loops infinitos

## Criterio de abstencion

- Si `confidence < 0.60` → `requires_human_review = true`
- Si se detecta prompt injection → `requires_human_review = true` + categoria "Seguridad"
- Umbral configurable en `config.json`

## Estrategia de correlacion

1. **GLM 5.2** analiza semantically los tickets y propone grupos
2. **Fallback por reglas:** si GLM no esta disponible, se usa similitud Jaccard + categoria + modulo + region + ventana temporal (10 min)
3. **Deteccion de incidente mayor:** 5+ tickets P1/P2 en mismo grupo dentro de ventana de 10 minutos
4. **Repriorizacion por blast radius:** prioridad operacional del incidente puede subir (P2 → P1) segun numero de tickets afectados

## Bonos implementados

| Bono | Descripcion | Estado |
|------|-------------|--------|
| **A** | Defensa adversarial (prompt injection, JSON incrustado, texto largo, etc.) | ✅ Implementado |
| **B** | Procesamiento concurrente sin perdidas ni duplicados | ✅ Implementado |
| **C** | Explicabilidad exportable (audit log con evidencia) | ✅ Implementado |
| **D** | Brief ejecutivo automatico para incidentes mayores | ✅ Implementado |

## Esquema de salida documentado

Cada ticket procesado devuelve:

```json
{
  "ticket_id": "T-10482",
  "category": "Cuenta y acceso",
  "priority": "P1",
  "sentiment": "negativo",
  "product_or_module": "SSO",
  "summary": "Organizacion completa sin acceso mediante SSO despues del despliegue.",
  "suggested_action": "Escalar al equipo de identidad y verificar regresion del despliegue.",
  "suggested_response": "Estamos investigando de forma prioritaria el problema de acceso por SSO...",
  "confidence": 0.92,
  "requires_human_review": false,
  "correlation_id": "corr-A91D2F",
  "incident_group_id": "INC-001"
}
```

## Seguridad

- No se suben API Keys, tokens ni credenciales
- Variables de entorno para secretos
- `.env.example` sin valores secretos
- Prompt injection detectado y neutralizado
- No se incluyen secretos en prompts al modelo
- Audit log no registra informacion sensible
