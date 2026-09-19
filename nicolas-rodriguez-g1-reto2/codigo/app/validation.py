"""Validaciones de negocio para pedidos entrantes (casos borde de la rubrica:
pedido sin repartidores, distancia negativa, prioridad invalida, timestamps
futuros, etc.).

Se hacen aparte de Pydantic a proposito: un pedido semanticamente invalido no
debe tumbar la peticion con un 422 opaco, debe convertirse en una decision
``REJECTED`` con ``reasons[]`` explicando exactamente que regla se violo, para
que el equipo de soporte (o el propio cliente) entienda que paso.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

VALID_PRIORITIES = ("normal", "express")


def parse_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def validate_order(order: dict, now: float, config: dict) -> list[dict]:
    """Devuelve una lista de razones (``rule``/``detail``) de validacion fallida.
    Lista vacia significa que el pedido es valido y puede seguir al motor de reglas.
    """
    errors: list[dict] = []
    val_cfg = config.get("validation", {})
    max_distance = val_cfg.get("max_reasonable_distance_km", 100.0)
    future_tolerance = val_cfg.get("future_tolerance_seconds", 300.0)

    order_id = order.get("order_id")
    if not order_id or not isinstance(order_id, str):
        errors.append({"rule": "invalid_order_id", "detail": "order_id es requerido y debe ser una cadena no vacia"})

    priority = order.get("priority")
    if priority not in VALID_PRIORITIES:
        errors.append({
            "rule": "invalid_priority",
            "detail": f"priority={priority!r} invalida; valores permitidos: {VALID_PRIORITIES}",
        })

    pickup_zone = order.get("pickup_zone")
    if not pickup_zone or not isinstance(pickup_zone, str):
        errors.append({"rule": "invalid_pickup_zone", "detail": "pickup_zone es requerido y debe ser una cadena no vacia"})

    distance_km = order.get("distance_km")
    if not isinstance(distance_km, (int, float)) or isinstance(distance_km, bool):
        errors.append({"rule": "invalid_distance", "detail": f"distance_km debe ser numerico, recibido: {distance_km!r}"})
    elif distance_km < 0:
        errors.append({"rule": "invalid_distance_negative", "detail": f"distance_km={distance_km} no puede ser negativo"})
    elif distance_km > max_distance:
        errors.append({
            "rule": "invalid_distance_out_of_range",
            "detail": f"distance_km={distance_km} excede el maximo razonable de {max_distance} km",
        })

    ts_raw = order.get("timestamp")
    ts = parse_timestamp(ts_raw)
    if ts is None:
        errors.append({"rule": "invalid_timestamp_format", "detail": f"timestamp={ts_raw!r} no tiene formato ISO 8601 valido"})
    else:
        delta = ts.timestamp() - now
        if delta > future_tolerance:
            errors.append({
                "rule": "invalid_timestamp_future",
                "detail": f"timestamp esta {delta:.0f}s en el futuro; tolerancia maxima {future_tolerance:.0f}s",
            })

    couriers = order.get("couriers")
    if couriers is not None:
        if not isinstance(couriers, list):
            errors.append({"rule": "invalid_couriers_payload", "detail": "couriers debe ser una lista"})
        else:
            for c in couriers:
                if not isinstance(c, dict) or not c.get("courier_id"):
                    errors.append({"rule": "invalid_courier_entry", "detail": f"entrada de courier invalida: {c!r}"})
                    continue
                cid = c["courier_id"]
                cap = c.get("max_capacity")
                act = c.get("active_orders")
                if not isinstance(cap, (int, float)) or isinstance(cap, bool) or cap <= 0:
                    errors.append({"rule": "invalid_courier_capacity", "detail": f"courier {cid}: max_capacity debe ser > 0"})
                if not isinstance(act, (int, float)) or isinstance(act, bool) or act < 0:
                    errors.append({"rule": "invalid_courier_active_orders", "detail": f"courier {cid}: active_orders no puede ser negativo"})

    return errors
