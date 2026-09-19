"""Modelos Pydantic de entrada/salida de la API.

Los modelos de *entrada* son deliberadamente permisivos en los tipos (``str``
para ``priority``/``timestamp``, ``float`` sin cota inferior para
``distance_km``): la validacion semantica real (prioridad desconocida,
distancia negativa, timestamp mal formado o futuro, etc.) la hace
``app.validation`` para poder devolver un ``REJECTED`` explicado con
``reasons[]`` en vez de un 422 generico de FastAPI que no dice nada al equipo
de soporte.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class CourierIn(BaseModel):
    courier_id: str
    zone: str
    active_orders: int
    max_capacity: int


class OrderIn(BaseModel):
    order_id: str
    timestamp: str
    pickup_zone: str
    distance_km: float
    priority: str
    couriers: Optional[List[CourierIn]] = None


class BatchAssignIn(BaseModel):
    orders: List[OrderIn]


class BurstSimulateIn(BaseModel):
    pickup_zone: str
    distance_km: float = 3.0
    priority: str = "normal"
    count: int = Field(default=6, ge=1, le=50)
    order_id_prefix: str = "burst"


class Reason(BaseModel):
    rule: str
    detail: str


class AssignmentResult(BaseModel):
    order_id: str
    status: str
    assigned_courier: Optional[str] = None
    reasons: List[Reason] = Field(default_factory=list)
    cost: Optional[float] = None
    pricing_status: Optional[str] = None
