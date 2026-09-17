import { Injectable } from '@nestjs/common';
import { TicketRepository } from './ticket.repository';
import { TriageService } from '../triage/triage.service';
import { KafkaService, TOPICS } from '../shared/kafka.service';
import { AppLogger } from '../shared/logger';
import * as fs from 'fs/promises';

/**
 * Servicio de ingesta de tickets.
 * Acepta arrays de tickets, valida y publica en Kafka para procesamiento async.
 */
@Injectable()
export class TicketsService {
  constructor(
    private readonly repo: TicketRepository,
    private readonly triage: TriageService,
    private readonly kafka: KafkaService,
    private readonly logger: AppLogger,
  ) {}

  /**
   * Ingiere un lote de tickets. Publica cada uno en Kafka (fire-and-forget)
   * y también dispara procesamiento triage (para demo sin esperar Kafka).
   */
  async ingestBatch(rawTickets: unknown[]): Promise<{
    accepted: number;
    results: Array<{ ticket_id: string; status: string }>;
  }> {
    const results: Array<{ ticket_id: string; status: string }> = [];
    let accepted = 0;

    for (const raw of rawTickets) {
      const ticketId = (raw as { ticket_id?: string })?.ticket_id ?? 'unknown';
      try {
        // Publicar en Kafka (best-effort)
        await this.kafka.emit(TOPICS.TICKETS_RAW, raw, ticketId).catch((err) => {
          this.logger.warn(`Kafka emit falló para ${ticketId}: ${(err as Error).message}`, 'TicketsService');
        });
        accepted++;
        results.push({ ticket_id: ticketId, status: 'accepted' });
      } catch (err) {
        results.push({ ticket_id: ticketId, status: `rejected: ${(err as Error).message}` });
      }
    }

    return { accepted, results };
  }

  /**
   * Ingiere desde un archivo JSON (path absoluto o relativo al cwd).
   */
  async ingestFromFile(filePath: string): Promise<{
    accepted: number;
    results: Array<{ ticket_id: string; status: string }>;
  }> {
    const content = await fs.readFile(filePath, 'utf-8');
    const data = JSON.parse(content);
    if (!Array.isArray(data)) {
      throw new Error('El archivo debe contener un array de tickets');
    }
    return this.ingestBatch(data);
  }

  /**
   * Procesa un lote síncronamente (triage + correlación) — útil para demo
   * y para el formulario manual del Control Room.
   */
  async processSync(rawTickets: unknown[]): Promise<unknown[]> {
    return this.triage.processBatch(rawTickets);
  }
}
