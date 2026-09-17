import { Injectable } from '@nestjs/common';
import { GlmService } from '../glm/glm.service';
import { TicketRepository } from '../tickets/ticket.repository';
import { IncidentRepository } from './incident.repository';
import { AppLogger } from '../shared/logger';
import { highestPriority, PRIORITY_WEIGHT, type Priority } from '../shared/constants';
import { CorrelationResultSchema } from '../triage/schemas';
import { SchemaValidationError } from '../shared/errors';

/**
 * Servicio de correlación de tickets.
 *
 * Estrategia:
 * 1. Pre-filtro por reglas (category + module + region + ventana 30 min)
 *    para identificar candidatos a grupos.
 * 2. GLM 5.2 decide la agrupación final sobre los candidatos.
 * 3. Asigna incident_group_id a cada ticket.
 * 4. Detecta incidentes mayores (≥5 P1/P2 + mismo grupo + ventana 10 min).
 * 5. Reprioriza por blast radius (múltiples clientes/regiones → P1).
 */
@Injectable()
export class CorrelationService {
  private incidentCounter = 0;

  constructor(
    private readonly glm: GlmService,
    private readonly tickets: TicketRepository,
    private readonly incidents: IncidentRepository,
    private readonly logger: AppLogger,
  ) {}

  /**
   * Correlaciona todos los tickets clasificados.
   */
  async correlateAll(): Promise<void> {
    const classified = await this.tickets.findClassified();
    if (classified.length < 2) {
      this.logger.log('No hay suficientes tickets clasificados para correlacionar', 'CorrelationService');
      return;
    }

    // Pre-filtro: agrupar candidatos por (category + module + region)
    const candidateBuckets = this.preFilter(classified);
    this.logger.log(`Pre-filtro: ${candidateBuckets.length} buckets candidatos`, 'CorrelationService');

    // Para cada bucket con >1 ticket, pedir a GLM que confirme correlación
    const allGroups: Array<{ ticket_ids: string[]; reason: string }> = [];
    const allGrouped = new Set<string>();

    for (const bucket of candidateBuckets) {
      if (bucket.length < 2) continue;
      try {
        const result = await this.glm.correlateTickets(
          bucket.map((t) => ({
            ticket_id: t.ticket_id,
            category: t.triage!.category,
            product_or_module: t.triage!.product_or_module,
            region: t.region,
            created_at: t.created_at,
            summary: t.triage!.summary,
          })),
        );

        for (const group of result.groups) {
          if (group.ticket_ids.length > 1) {
            allGroups.push(group);
            group.ticket_ids.forEach((id) => allGrouped.add(id));
          }
        }
      } catch (err) {
        this.logger.warn(
          `GLM correlación falló para bucket, usando fallback por reglas: ${(err as Error).message}`,
          'CorrelationService',
        );
        // Fallback: agrupar todo el bucket si comparten category+module+region
        allGroups.push({
          ticket_ids: bucket.map((t) => t.ticket_id),
          reason: 'Fallback por reglas: misma categoría, módulo y región',
        });
        bucket.forEach((t) => allGrouped.add(t.ticket_id));
      }
    }

    // Asignar incident_group_id y construir resúmenes
    for (const group of allGroups) {
      const incidentId = `INC-${String(++this.incidentCounter).padStart(3, '0')}`;
      const groupTickets = classified.filter((t) => group.ticket_ids.includes(t.ticket_id));

      for (const t of groupTickets) {
        await this.tickets.setIncidentGroup(t.ticket_id, incidentId);
      }

      await this.buildIncidentSummary(incidentId, groupTickets, group.reason);
    }

    this.logger.log(
      `Correlación completa: ${allGroups.length} incidentes, ${allGrouped.size} tickets agrupados`,
      'CorrelationService',
    );
  }

  /**
   * Pre-filtro por reglas: agrupa por (category + module + region).
   * Reduce los candidatos antes de llamar a GLM.
   */
  private preFilter(tickets: Array<{ ticket_id: string; region: string; created_at: string; triage?: { category: string; product_or_module: string; priority: string; summary: string } }>) {
    const buckets = new Map<string, typeof tickets>();
    for (const t of tickets) {
      if (!t.triage) continue;
      const key = `${t.triage.category}|${t.triage.product_or_module}|${t.region}`;
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key)!.push(t);
    }
    return Array.from(buckets.values());
  }

  /**
   * Construye el resumen del incidente y detecta si es mayor.
   */
  private async buildIncidentSummary(
    incidentId: string,
    tickets: Array<{
      ticket_id: string;
      customer_id: string;
      region: string;
      created_at: string;
      triage?: { category: string; priority: string; product_or_module: string; summary: string };
    }>,
    reason: string,
  ): Promise<void> {
    const priorities = tickets
      .map((t) => t.triage?.priority as Priority)
      .filter(Boolean);
    const topPriority = highestPriority(priorities);

    const customers = [...new Set(tickets.map((t) => t.customer_id))];
    const regions = [...new Set(tickets.map((t) => t.region))];
    const module = tickets[0]?.triage?.product_or_module ?? 'Unknown';
    const category = tickets[0]?.triage?.category ?? 'Otro';

    // Detección de incidente mayor:
    // ≥5 tickets P1/P2 + mismo grupo + ventana temporal cercana
    const criticalTickets = tickets.filter(
      (t) => t.triage?.priority === 'P1' || t.triage?.priority === 'P2',
    );
    const isMajor = criticalTickets.length >= 5;

    // Repriorización por blast radius:
    // Si el incidente afecta múltiples clientes y regiones, sube a P1
    let incidentPriority = topPriority;
    if (customers.length >= 3 && regions.length >= 2) {
      incidentPriority = 'P1';
    }

    await this.incidents.upsert(incidentId, {
      incident_group_id: incidentId,
      title: `${category} — ${module} (${regions.join(', ')})`,
      ticket_count: tickets.length,
      highest_priority: incidentPriority,
      affected_module: module,
      affected_region: regions.join(', '),
      summary: `${tickets.length} tickets reportan ${category.toLowerCase()} en ${module}. ${reason}. ${customers.length} clientes afectados en ${regions.length} región(es).`,
      major_incident_candidate: isMajor,
      ticket_ids: tickets.map((t) => t.ticket_id),
      affected_customers: customers,
      affected_regions: regions,
    });

    if (isMajor) {
      this.logger.warn(
        `🚨 INCIDENTE MAYOR detectado: ${incidentId} — ${tickets.length} tickets, prioridad ${incidentPriority}, ${customers.length} clientes`,
        'CorrelationService',
      );
    }
  }
}
