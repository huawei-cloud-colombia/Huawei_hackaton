/**
 * Jerarquía de errores de dominio.
 * Permite manejar de forma controlada los distintos fallos del pipeline.
 */

export class DomainError extends Error {
  constructor(
    message: string,
    public readonly code: string,
  ) {
    super(message);
    this.name = this.constructor.name;
    Error.captureStackTrace?.(this, this.constructor);
  }
}

/** Ticket malformado: id vacío, text vacío, timestamp inválido, etc. */
export class TicketValidationError extends DomainError {
  constructor(message: string) {
    super(message, 'TICKET_VALIDATION_ERROR');
  }
}

/** La API de GLM 5.2 falló (timeout, 5xx, red). */
export class GlmApiError extends DomainError {
  constructor(message: string, public readonly cause?: unknown) {
    super(message, 'GLM_API_ERROR');
  }
}

/** GLM respondió pero la salida no pasa el schema Zod. */
export class SchemaValidationError extends DomainError {
  constructor(message: string, public readonly raw?: unknown) {
    super(message, 'SCHEMA_VALIDATION_ERROR');
  }
}

/** Error al interactuar con Kafka. */
export class KafkaError extends DomainError {
  constructor(message: string, public readonly cause?: unknown) {
    super(message, 'KAFKA_ERROR');
  }
}

/** Error al interactuar con MongoDB. */
export class MongoError extends DomainError {
  constructor(message: string, public readonly cause?: unknown) {
    super(message, 'MONGO_ERROR');
  }
}
