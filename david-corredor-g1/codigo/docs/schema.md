# Esquemas de salida documentados

## Ticket de entrada

```json
{
  "ticket_id": "string (required, min 1)",
  "customer_id": "string (required, min 1)",
  "created_at": "string (required, ISO 8601 válido)",
  "region": "string (required, min 1)",
  "text": "string (required, min 1)"
}
```

## Resultado de triage (salida por ticket)

```json
{
  "ticket_id": "string",
  "category": "Cuenta y acceso | Facturación | Disponibilidad y rendimiento | Integraciones | Datos y exportación | Solicitud de función | Seguridad | Otro",
  "priority": "P1 | P2 | P3 | P4",
  "sentiment": "positivo | neutral | negativo",
  "product_or_module": "string",
  "summary": "string",
  "suggested_action": "string",
  "suggested_response": "string",
  "confidence": "number (0-1)",
  "requires_human_review": "boolean",
  "degraded": "boolean (true si GLM falló y se degradó)"
}
```

## Incidente (grupo correlacionado)

```json
{
  "incident_group_id": "string (INC-001)",
  "title": "string",
  "ticket_count": "number",
  "highest_priority": "P1 | P2 | P3 | P4",
  "affected_module": "string",
  "affected_region": "string",
  "summary": "string",
  "major_incident_candidate": "boolean",
  "ticket_ids": ["string"],
  "affected_customers": ["string"],
  "affected_regions": ["string"]
}
```

## Audit log

```json
{
  "ticket_id": "string",
  "model": "GLM-5.2",
  "attempts": "number",
  "validation_status": "valid | invalid | degraded",
  "correlation_id": "string (corr-XXXXXXXX)",
  "processed_at": "ISO 8601",
  "error_code": "string (opcional)",
  "error_message": "string (opcional)"
}
```

## Reporte de explicabilidad (Bono C)

```json
{
  "report_type": "ticket_explainability | incident_explainability",
  "generated_at": "ISO 8601",
  "model": "GLM-5.2",
  "ticket_id": "string",
  "decision": { "category": "...", "priority": "..." },
  "confidence": "number",
  "evidence": { "original_text": "...", "summary": "..." },
  "factors_considered": ["string"],
  "recommendation": "string",
  "audit_trail": [{ "correlation_id": "...", "attempts": 1 }]
}
```
