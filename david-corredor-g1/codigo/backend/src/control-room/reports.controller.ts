import { Body, Controller, Get, Param, Post } from '@nestjs/common';
import { TicketRepository } from '../tickets/ticket.repository';
import { IncidentRepository } from '../correlation/incident.repository';
import { AuditRepository } from '../audit/audit.repository';
import { ApiTags, ApiOperation } from '@nestjs/swagger';

/**
 * Bono C — Explicabilidad exportable.
 * Genera reportes estructurados para tickets P1 e incidentes mayores.
 */
@ApiTags('reports')
@Controller('reports')
export class ReportsController {
  constructor(
    private readonly tickets: TicketRepository,
    private readonly incidentRepo: IncidentRepository,
    private readonly audit: AuditRepository,
  ) {}

  @Get('tickets/:id')
  @ApiOperation({ summary: 'Reporte de explicabilidad para un ticket (Bono C)' })
  async ticketReport(@Param('id') id: string) {
    const ticket = await this.tickets.findByTicketId(id);
    if (!ticket) return { error: 'Ticket no encontrado' };

    const audit = await this.audit.findByTicketId(id);

    return {
      report_type: 'ticket_explainability',
      generated_at: new Date().toISOString(),
      model: 'GLM-5.2',
      ticket_id: ticket.ticket_id,
      decision: {
        category: ticket.triage?.category,
        priority: ticket.triage?.priority,
        sentiment: ticket.triage?.sentiment,
        requires_human_review: ticket.triage?.requires_human_review,
      },
      confidence: ticket.triage?.confidence,
      evidence: {
        original_text: ticket.text,
        customer_id: ticket.customer_id,
        region: ticket.region,
        created_at: ticket.created_at,
        summary: ticket.triage?.summary,
      },
      factors_considered: [
        'Contenido semántico del texto del ticket',
        'Número de usuarios/organización afectada mencionada',
        'Códigos de error mencionados (503, 500, etc.)',
        'Módulo/producto identificado',
        'Región del ticket',
        'Timestamp relativo al despliegue',
      ],
      recommendation: ticket.triage?.suggested_action,
      audit_trail: audit.map((a) => ({
        correlation_id: a.correlation_id,
        attempts: a.attempts,
        validation_status: a.validation_status,
        processed_at: a.processed_at,
      })),
    };
  }

  @Get('incidents/:id')
  @ApiOperation({ summary: 'Reporte de explicabilidad para un incidente mayor (Bono C)' })
  async incidentReport(@Param('id') id: string) {
    const incident = await this.incidentRepo.findById(id);
    if (!incident) return { error: 'Incidente no encontrado' };

    const tickets = await this.tickets.findByIncidentGroup(id);

    return {
      report_type: 'incident_explainability',
      generated_at: new Date().toISOString(),
      model: 'GLM-5.2',
      incident_id: incident.incident_group_id,
      decision: {
        highest_priority: incident.highest_priority,
        major_incident_candidate: incident.major_incident_candidate,
      },
      confidence: tickets.filter((t) => t.triage).reduce((acc, t) => acc + (t.triage?.confidence ?? 0), 0) / (tickets.length || 1),
      evidence: {
        title: incident.title,
        summary: incident.summary,
        affected_module: incident.affected_module,
        affected_region: incident.affected_region,
        affected_customers: incident.affected_customers,
        ticket_count: incident.ticket_count,
        sample_tickets: tickets.slice(0, 5).map((t) => ({
          ticket_id: t.ticket_id,
          text: t.text.slice(0, 200),
          priority: t.triage?.priority,
        })),
      },
      factors_considered: [
        'Agrupación semántica vía GLM 5.2',
        'Categoría y módulo compartidos',
        'Proximidad temporal de los tickets',
        'Región afectada',
        'Número de clientes distintos reportando el mismo síntoma',
        'Prioridades individuales de los tickets miembros',
        'Blast radius (clientes × regiones)',
      ],
      recommendation: incident.major_incident_candidate
        ? 'Activar protocolo de incidente mayor. Escalar a equipo de guardia. Comunicar a clientes enterprise afectados.'
        : 'Monitorear evolución. Si el número de tickets aumenta, reevaluar como incidente mayor.',
    };
  }
}
