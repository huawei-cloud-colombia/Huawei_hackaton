# Arquitectura de SentinelPay Risk Engine

## Visión General

SentinelPay Risk Engine es un motor de scoring de riesgo para transacciones financieras.
Evalúa cada transacción contra un conjunto de reglas configurables y produce un score,
una decisión (APPROVE / REVIEW / REJECT) y una lista de razones explicables.

## Estructura del Proyecto

```
jeniffer-corredor-g4/
├── codigo/
│   └── sentinelpay/
│       ├── __init__.py              # Punto de entrada del paquete
│       ├── app/
│       │   ├── models/
│       │   │   └── transaction.py   # Modelo Pydantic de transacción
│       │   ├── ingestion/
│       │   │   └── loader.py        # Carga de transacciones desde JSON
│       │   ├── rules/
│       │   │   ├── base.py          # Clase base abstracta
│       │   │   ├── anomalous_amount.py  # Regla 1: monto anómalo
│       │   │   ├── country_mismatch.py  # Regla 2: país diferente
│       │   │   └── unusual_hour.py      # Regla 3: hora inusual
│       │   ├── scoring/
│       │   │   └── engine.py        # Motor de scoring
│       │   ├── config/
│       │   │   ├── settings.py      # Carga de configuración
│       │   │   └── rules_config.yaml # Config de reglas (pesos, enabled)
│       │   └── services/
│       │       └── evaluator.py     # Orquestador + evaluate()
│       └── persistence/
│           └── store.py             # Almacén en memoria
├── tests/                           # Suite de pruebas pytest
├── data/                            # Datasets de ejemplo
├── docs/                            # Documentación
├── pyproject.toml                   # Config del proyecto + pytest
├── requirements.txt                 # Dependencias
├── .env.example                     # Variables de entorno
└── conftest.py                      # Path setup para pytest
```

## Flujo de Evaluación

1. **Entrada**: `evaluate(transaction)` recibe un dict o `Transaction`.
2. **Validación**: Pydantic valida tipos, campos obligatorios, monto > 0, IP válida, timestamp válido.
   - Si falla, retorna `decision=ERROR` sin tumbar el proceso.
3. **Reglas**: Cada regla (si está habilitada) evalúa la transacción contra el estado en memoria.
   - Regla 1 (anomalous_amount): `amount > 3 × promedio histórico` → +25
   - Regla 2 (country_mismatch): `country != ip_country` → +30
   - Regla 3 (unusual_hour): hora local entre 01:00 y 05:00 → +10
4. **Score**: Suma de pesos de reglas disparadas.
5. **Decisión**:
   - `score >= 50` → REJECT
   - `score > 0` → REVIEW
   - `score == 0` → APPROVE
6. **Persistencia**: La transacción y el resultado se guardan en `InMemoryStore`.
   - El promedio histórico de la tarjeta se actualiza después de la evaluación.

## Determinación de Hora Local

La regla `unusual_hour` convierte el timestamp UTC al horario local del comercio:

1. Si `merchant_id` está en `merchant_timezones`, usa esa zona horaria.
2. Si no, usa `default_timezone` (configurable, default: `UTC`).
3. El rango `[01:00, 05:00)` es inclusivo en inicio, exclusivo en fin.

## Configuración

- **YAML** (`rules_config.yaml`): pesos, enabled/disabled, parámetros de reglas, umbrales.
- **.env**: zona horaria default, umbrales, ruta de config.

Cada regla puede activarse, desactivarse y modificar su peso sin tocar código.

## Extensibilidad

La arquitectura está diseñada para la Fase 2:
- `InMemoryStore` puede extenderse con ventanas deslizantes.
- Nuevas reglas heredan de `BaseRule` e implementan `_evaluate()`.
- La configuración YAML permite añadir reglas sin recompilar.
