import { Injectable } from '@nestjs/common';
import { AuditRepository } from './audit.repository';
import { randomUUID } from 'crypto';

/**
 * Servicio de logging auditable.
 * NUNCA registra API keys, tokens, secretos ni headers sensibles.
 */
@Injectable()
export class AuditService {
  constructor(private readonly repo: AuditRepository) {}

  async log(params: {
    ticket_id: string;
    model: string;
    attempts: number;
    validation_status: 'valid' | 'invalid' | 'degraded';
    error_code?: string;
    error_message?: string;
  }): Promise<string> {
    const correlation_id = `corr-${randomUUID().slice(0, 8).toUpperCase()}`;
    await this.repo.log({
      ticket_id: params.ticket_id,
      model_name: params.model,
      attempts: params.attempts,
      validation_status: params.validation_status,
      correlation_id,
      processed_at: new Date().toISOString(),
      ...(params.error_code ? { error_code: params.error_code } : {}),
      ...(params.error_message ? { error_message: params.error_message } : {}),
    });
    return correlation_id;
  }
}
