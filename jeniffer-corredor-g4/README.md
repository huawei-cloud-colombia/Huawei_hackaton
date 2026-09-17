# SentinelPay Risk Engine

Motor de scoring de riesgo para transacciones financieras.

## Arquitectura

```
codigo/sentinelpay/
├── app/
│   ├── models/          # Modelo de transacción (Pydantic)
│   ├── ingestion/       # Carga de datos desde JSON
│   ├── rules/           # Reglas de scoring (base + velocity)
│   ├── scoring/         # Motor de scoring
│   ├── config/          # Configuración YAML + settings
│   └── services/        # Evaluador (punto de entrada evaluate)
├── persistence/         # Almacén en memoria + velocity tracker + blocklist
tests/                   # Suite pytest (105 tests)
data/                    # Datasets de ejemplo
docs/                    # Documentación de arquitectura
```

## Requisitos

- **Python 3.11+**
- pydantic >= 2.0
- pyyaml >= 6.0
- python-dotenv >= 1.0
- pytest >= 7.0

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/Mac
pip install -r requirements.txt
```

## Configuración

### Reglas (`codigo/sentinelpay/app/config/rules_config.yaml`)

```yaml
rules:
  anomalous_amount:
    enabled: true
    weight: 25
    multiplier: 3.0
  country_mismatch:
    enabled: true
    weight: 30
  unusual_hour:
    enabled: true
    weight: 10
    start_hour: 1
    end_hour: 5
    default_timezone: UTC
  velocity_card:
    enabled: true
    threshold: 5
    window_seconds: 10
    weight: 40
    block_duration: 120
  velocity_device:
    enabled: true
    threshold: 3
    window_seconds: 30
    weight: 50
    block_duration: 120

scoring:
  reject_threshold: 50
  review_threshold: 0
```

Cada regla puede activarse (`enabled`), desactivarse y modificar su peso (`weight`).

### Variables de entorno (`.env`)

```
SENTINELPAY_DEFAULT_TIMEZONE=UTC
SENTINELPAY_REJECT_THRESHOLD=50
SENTINELPAY_REVIEW_THRESHOLD=0
```

## Cómo ejecutar

### Evaluación individual

```python
from sentinelpay import evaluate

result = evaluate({
    "id": "txn_00234",
    "card_id": "card_9F21",
    "merchant_id": "merch_petshop_bog",
    "amount": 850000,
    "currency": "COP",
    "country": "CO",
    "ip_country": "RU",
    "device_id": "dev_a19x",
    "ip": "185.220.101.14",
    "timestamp": "2024-11-28T04:58:12Z",
})
print(result)
```

### Evaluación batch

```python
from sentinelpay import Evaluator
from sentinelpay.app.ingestion.loader import load_transactions_from_json

ev = Evaluator()
txns = load_transactions_from_json("data/sample_transactions.json")
results = ev.evaluate_batch([t.model_dump() for t in txns])
```

## Reglas implementadas

### Fase 1 — Reglas base

| Regla              | Condición                              | Peso | Configurable |
|--------------------|----------------------------------------|------|--------------|
| anomalous_amount   | `amount > 3 × promedio histórico`      | +25  | Sí           |
| country_mismatch   | `country != ip_country`                | +30  | Sí           |
| unusual_hour       | hora local entre 01:00 y 05:00         | +10  | Sí           |

### Fase 2 — Detección de Card Testing

| Regla                  | Condición                              | Peso | Acción           |
|------------------------|----------------------------------------|------|------------------|
| velocity_card          | >5 txns misma tarjeta en 10s           | +40  | DECLINE + block  |
| velocity_device        | 3 tarjetas distintas mismo device 30s  | +50  | DECLINE + block  |

### Blocklist temporal

- Cuando se supera un umbral de velocity, la tarjeta/dispositivo se bloquea por 120s (configurable).
- Transacciones bloqueadas retornan `DECLINE` inmediato con `card_temporarily_blocked`.
- La blocklist expira automáticamente (no requiere reinicio).

## Decisiones de scoring

| Score / Condición         | Decisión |
|---------------------------|----------|
| Velocity limit excedido   | DECLINE  |
| Tarjeta/dispositivo bloqueado | DECLINE |
| `score >= 50`             | REJECT   |
| `score > 0`               | REVIEW   |
| `score == 0`              | APPROVE  |

## Cómo ejecutar tests

```bash
pytest tests/ -v
```

## Casos obligatorios del reto

### Fase 1: CO/RU/04:58

```
country = CO, ip_country = RU, hora = 04:58
→ country_mismatch = +30, unusual_hour = +10, score = 40, REVIEW
```

### Fase 2: ráfaga de 6 transacciones

```
6 transacciones, misma tarjeta, 7 segundos, montos 5000-10000 COP
→ txn 6: velocity_limit_exceeded = +40, score = 40, DECLINE, card bloqueada 120s
→ txn 7 (dentro de 120s): DECLINE, card_temporarily_blocked
→ txn 8 (después de 120s): APPROVE (bloqueo expirado)
```

## Reproducir la ráfaga

```python
from sentinelpay import Evaluator

ev = Evaluator()
amounts = [5000, 6000, 7000, 8000, 9000, 10000]
for i in range(6):
    r = ev.evaluate({
        "id": f"txn_{i+1:05d}",
        "card_id": "card_9F21",
        "merchant_id": "merch_1",
        "amount": amounts[i],
        "currency": "COP",
        "country": "CO",
        "ip_country": "CO",
        "device_id": "dev_1",
        "ip": "190.24.6.10",
        "timestamp": f"2024-11-28T12:00:0{i}Z",
    })
    print(r["decision"], r["score"], [x["rule"] for x in r["reasons"]])
```
