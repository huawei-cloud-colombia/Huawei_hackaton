import { Body, Controller, Get, Param, Post, Query } from '@nestjs/common';
import { TicketRepository } from '../tickets/ticket.repository';
import { IncidentRepository } from '../correlation/incident.repository';
import { CorrelationService } from '../correlation/correlation.service';
import { TriageService } from '../triage/triage.service';
import { AuditRepository } from '../audit/audit.repository';
import { ApiTags, ApiOperation } from '@nestjs/swagger';

/**
 * Control Room — endpoints agregados para la UI del frontend.
 * Fase 4 del reto.
 */
@ApiTags('control-room')
@Controller('control-room')
export class ControlRoomController {
  constructor(
    private readonly tickets: TicketRepository,
    private readonly incidentRepo: IncidentRepository,
    private readonly correlation: CorrelationService,
    private readonly triage: TriageService,
    private readonly audit: AuditRepository,
  ) {}

  @Get('queue')
  @ApiOperation({ summary: 'Cola priorizada de tickets (con filtros)' })
  async queue(
    @Query('priority') priority?: string,
    @Query('category') category?: string,
    @Query('region') region?: string,
    @Query('module') module?: string,
    @Query('incident_group_id') incidentGroupId?: string,
  ) {
    const filter: Record<string, unknown> = { status: 'classified' };
    if (priority) filter['triage.priority'] = priority;
    if (category) filter['triage.category'] = category;
    if (region) filter.region = region;
    if (module) filter['triage.product_or_module'] = module;
    if (incidentGroupId) filter.incident_group_id = incidentGroupId;
    return this.tickets.findAll(filter);
  }

  @Get('tickets/:id')
  @ApiOperation({ summary: 'Detalle completo de un ticket' })
  async ticketDetail(@Param('id') id: string) {
    const ticket = await this.tickets.findByTicketId(id);
    const audit = await this.audit.findByTicketId(id);
    return { ticket, audit };
  }

  @Get('incidents')
  @ApiOperation({ summary: 'Lista de grupos de incidentes' })
  async incidents() {
    return this.incidentRepo.findAll();
  }

  @Get('incidents/:id')
  @ApiOperation({ summary: 'Detalle de un incidente con tickets miembros' })
  async incidentDetail(@Param('id') id: string) {
    const incident = await this.incidentRepo.findById(id);
    const tickets = await this.tickets.findByIncidentGroup(id);
    return { incident, tickets };
  }

  @Post('correlate')
  @ApiOperation({ summary: 'Ejecuta correlación sobre todos los tickets clasificados' })
  async correlate() {
    await this.correlation.correlateAll();
    return { status: 'ok', message: 'Correlación ejecutada' };
  }

  @Post('classify-manual')
  @ApiOperation({ summary: 'Clasifica un ticket manualmente (formulario Control Room)' })
  async classifyManual(@Body() body: { text: string; customer_id?: string; region?: string }) {
    const ticket = {
      ticket_id: `MANUAL-${Date.now()}`,
      customer_id: body.customer_id ?? 'MANUAL',
      created_at: new Date().toISOString(),
      region: body.region ?? 'unknown',
      text: body.text,
    };
    const result = await this.triage.processTicket(ticket);
    return { ticket, result };
  }

  @Get('stats')
  @ApiOperation({ summary: 'Estadísticas del war room' })
  async stats() {
    const all = await this.tickets.findAll({ status: 'classified' });
    const incidents = await this.incidentRepo.findAll();
    const majorIncidents = incidents.filter((i) => i.major_incident_candidate);
    const p1 = all.filter((t) => t.triage?.priority === 'P1').length;
    const p2 = all.filter((t) => t.triage?.priority === 'P2').length;
    const p3 = all.filter((t) => t.triage?.priority === 'P3').length;
    const p4 = all.filter((t) => t.triage?.priority === 'P4').length;
    return {
      total_tickets: all.length,
      by_priority: { P1: p1, P2: p2, P3: p3, P4: p4 },
      total_incidents: incidents.length,
      major_incidents: majorIncidents.length,
      requires_human_review: all.filter((t) => t.triage?.requires_human_review).length,
    };
  }
}
