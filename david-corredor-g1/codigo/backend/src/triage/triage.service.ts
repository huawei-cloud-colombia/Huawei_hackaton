import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { GlmService } from '../glm/glm.service';
import { AppLogger } from '../shared/logger';
import { GlmApiError, SchemaValidationError } from '../shared/errors';
import { AuditService } from '../audit/audit.service';
import { TriageResultSchema, TicketInputSchema, type TriageResult, type TicketInput } from './schemas';
import { TicketRepository } from '../tickets/ticket.repository';
import { KafkaService, TOPICS } from '../shared/kafka.service';

const MODEL_NAME = 'GLM-5.2';

/**
 * Orquestador del triage:
 * 1. Valida el ticket de entrada (Zod).
 * 2. Llama a GLM 5.2 con retries + backoff exponencial.
 * 3. Valida la salida con Zod.
 * 4. Aplica abstención (confidence < threshold → requires_human_review).
 * 5. Persiste en Mongo.
 * 6. Emite evento Kafka tickets.classified.
 * 7. Escribe audit log.
 *
 * Un ticket malformado o un fallo de GLM NO detiene el lote.
 */
@Injectable()
export class TriageService {
  private readonly maxRetries: number;
  private readonly confidenceThreshold: number;

  constructor(
    private readonly glm: GlmService,
    private readonly tickets: TicketRepository,
    private readonly kafka: KafkaService,
    private readonly audit: AuditService,
    private readonly config: ConfigService,
    private readonly logger: AppLogger,
  ) {
    this.maxRetries = Number(this.config.get<string>('MAX_RETRIES', '3'));
    this.confidenceThreshold = Number(this.config.get<string>('CONFIDENCE_THRESHOLD', '0.6'));
  }

  /**
   * Procesa un ticket individual. Nunca lanza — devuelve siempre un resultado
   * (degradado si falla) para que el lote continúe.
   */
  async processTicket(rawTicket: unknown): Promise<TriageResult & { ticket_id: string; degraded: boolean }> {
    // 1. Validar entrada con Zod — un ticket malformado no detiene el lote
    let ticket: TicketInput;
    try {
      ticket = TicketInputSchema.parse(rawTicket);
    } catch (err) {
      this.logger.warn(`Ticket malformado, saltando: ${(err as Error).message}`, 'TriageService');
      await this.audit.log({
        ticket_id: (rawTicket as { ticket_id?: string })?.ticket_id ?? 'unknown',
        model: MODEL_NAME,
        attempts: 0,
        validation_status: 'invalid',
        error_code: 'INPUT_VALIDATION_ERROR',
        error_message: (err as Error).message.slice(0, 300),
      });
      return this.degradedResult(
        (rawTicket as { ticket_id?: string })?.ticket_id ?? 'unknown',
        'Ticket malformado',
      );
    }

    // Persistir ticket raw (status pending)
    await this.tickets.upsert(ticket.ticket_id, {
      ticket_id: ticket.ticket_id,
      customer_id: ticket.customer_id,
      created_at: ticket.created_at,
      region: ticket.region,
      text: ticket.text,
      status: 'pending',
    });

    // 2. Llamar GLM con retries + backoff
    let result: TriageResult | null = null;
    let attempts = 0;
    let lastError: Error | null = null;

    for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
      attempts = attempt;
      try {
        result = await this.glm.classifyTicket(ticket.text);
        lastError = null;
        break;
      } catch (err) {
        lastError = err as Error;
        const isSchema = err instanceof SchemaValidationError;
        const isApi = err instanceof GlmApiError;
        this.logger.warn(
          `Intento ${attempt}/${this.maxRetries} falló para ${ticket.ticket_id}: ${(err as Error).message}`,
          'TriageService',
        );
        if (attempt < this.maxRetries) {
          // Backoff exponencial: 500ms, 1500ms, ...
          const delay = 500 * Math.pow(3, attempt - 1);
          await new Promise((r) => setTimeout(r, delay));
        }
        // Si es schema error, reintentar puede ayudar (modelo puede corregir)
        // Si es API error (429/5xx), backoff ayuda
        void isSchema; void isApi;
      }
    }

    // 3. Manejar fallo total → degradar
    if (!result || lastError) {
      const degraded = this.degradedResult(ticket.ticket_id, lastError?.message ?? 'GLM falló');
      await this.tickets.updateTriage(
        ticket.ticket_id,
        {
          category: 'Otro',
          priority: 'P3',
          sentiment: 'neutral',
          product_or_module: 'Unknown',
          summary: 'Clasificación no disponible — requiere revisión humana.',
          suggested_action: 'Revisar manualmente el ticket original.',
          suggested_response: 'Hemos recibido tu ticket y lo estamos revisando manualmente.',
          confidence: 0,
          requires_human_review: true,
        },
        'failed',
        { code: lastError?.name ?? 'UNKNOWN', message: lastError?.message.slice(0, 300) ?? '' },
      );
      await this.audit.log({
        ticket_id: ticket.ticket_id,
        model: MODEL_NAME,
        attempts,
        validation_status: 'degraded',
        error_code: lastError?.name ?? 'UNKNOWN',
        error_message: lastError?.message.slice(0, 300),
      });
      this.logger.warn(`Ticket ${ticket.ticket_id} degradado tras ${attempts} intentos`, 'TriageService');
      return degraded;
    }

    // 4. Abstención: confidence baja → revisión humana
    if (result.confidence < this.confidenceThreshold) {
      result = { ...result, requires_human_review: true };
    }

    // 5. Persistir resultado
    await this.tickets.updateTriage(ticket.ticket_id, result, 'classified');

    // 6. Emitir evento Kafka
    try {
      await this.kafka.emit(TOPICS.TICKETS_CLASSIFIED, {
        ticket_id: ticket.ticket_id,
        ...result,
      }, ticket.ticket_id);
    } catch (err) {
      this.logger.warn(`No se pudo emitir evento Kafka para ${ticket.ticket_id}: ${(err as Error).message}`, 'TriageService');
    }

    // 7. Audit log
    await this.audit.log({
      ticket_id: ticket.ticket_id,
      model: MODEL_NAME,
      attempts,
      validation_status: 'valid',
    });

    return { ticket_id: ticket.ticket_id, ...result, degraded: false };
  }

  /**
   * Procesa un lote completo. Un ticket malformado NO detiene el resto.
   */
  async processBatch(rawTickets: unknown[]): Promise<Array<TriageResult & { ticket_id: string; degraded: boolean }>> {
    const results: Array<TriageResult & { ticket_id: string; degraded: boolean }> = [];
    for (const raw of rawTickets) {
      try {
        const r = await this.processTicket(raw);
        results.push(r);
      } catch (err) {
        // processTicket nunca lanza, pero por seguridad:
        this.logger.error(`Error inesperado procesando ticket: ${(err as Error).message}`, (err as Error).stack, 'TriageService');
        results.push(this.degradedResult('unknown', (err as Error).message));
      }
    }
    return results;
  }

  private degradedResult(ticketId: string, reason: string): TriageResult & { ticket_id: string; degraded: boolean } {
    return {
      ticket_id: ticketId,
      category: 'Otro',
      priority: 'P3',
      sentiment: 'neutral',
      product_or_module: 'Unknown',
      summary: `Clasificación degradada: ${reason.slice(0, 100)}`,
      suggested_action: 'Revisar manualmente.',
      suggested_response: 'Hemos recibido tu ticket y lo estamos revisando.',
      confidence: 0,
      requires_human_review: true,
      degraded: true,
    };
  }
}
