"""
Esquemas de validacion usando Pydantic para la salida estructurada del triage.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from enum import Enum


class CategoryEnum(str, Enum):
    CUENTA_ACCESO = "Cuenta y acceso"
    FACTURACION = "Facturacion"
    DISPONIBILIDAD = "Disponibilidad y rendimiento"
    INTEGRACIONES = "Integraciones"
    DATOS_EXPORTACION = "Datos y exportacion"
    SOLICITUD_FUNCION = "Solicitud de funcion"
    SEGURIDAD = "Seguridad"
    OTRO = "Otro"


class PriorityEnum(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class SentimentEnum(str, Enum):
    POSITIVO = "positivo"
    NEUTRAL = "neutral"
    NEGATIVO = "negativo"
    FRUSTRADO = "frustrado"


class ReasonItem(BaseModel):
    rule: str = Field(description="Nombre de la regla aplicada")
    detail: str = Field(description="Detalle de por que se aplico la regla")


class TriageResult(BaseModel):
    """Esquema de salida para un ticket procesado por triage."""
    ticket_id: str = Field(description="ID del ticket")
    category: CategoryEnum = Field(description="Categoria del ticket")
    priority: PriorityEnum = Field(description="Prioridad P1-P4")
    sentiment: SentimentEnum = Field(description="Sentimiento del ticket")
    product_or_module: str = Field(description="Producto o modulo afectado")
    summary: str = Field(description="Resumen tecnico del problema")
    suggested_action: str = Field(description="Accion sugerida")
    suggested_response: str = Field(description="Borrador de primera respuesta al cliente")
    confidence: float = Field(ge=0.0, le=1.0, description="Confianza 0-1")
    requires_human_review: bool = Field(description="Si requiere revision humana")

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v):
        if v < 0.0 or v > 1.0:
            return 0.5
        return v


class IncidentGroupSummary(BaseModel):
    """Resumen de un grupo de incidentes correlacionados."""
    incident_group_id: str
    title: str
    ticket_count: int
    highest_priority: str
    affected_module: str
    affected_region: str
    summary: str
    major_incident_candidate: bool
    operational_priority: Optional[str] = None
    ticket_ids: List[str] = Field(default_factory=list)


class AuditRecord(BaseModel):
    """Registro auditable de una decision."""
    ticket_id: str
    model: str
    attempts: int
    validation_status: str
    correlation_id: Optional[str] = None
    processed_at: str
    error: Optional[str] = None


class TicketInput(BaseModel):
    """Esquema de entrada para un ticket."""
    ticket_id: str
    customer_id: str = ""
    created_at: str = ""
    region: str = ""
    text: str

    @field_validator("ticket_id")
    @classmethod
    def validate_ticket_id(cls, v):
        if not v or not v.strip():
            raise ValueError("ticket_id no puede estar vacio")
        return v.strip()

    @field_validator("text")
    @classmethod
    def validate_text(cls, v):
        if not v or not v.strip():
            raise ValueError("text no puede estar vacio")
        return v.strip()
