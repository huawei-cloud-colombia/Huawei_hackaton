import { Injectable, Logger } from '@nestjs/common';

/**
 * Logger ligero wrapper sobre el Logger de NestJS.
 * NUNCA loguea API keys, tokens ni secretos — el caller es responsable
 * de no pasarlos. Se incluye para centralizar formato y correlation IDs.
 */
@Injectable()
export class AppLogger {
  private readonly logger = new Logger('ATLAS');

  log(message: string, context?: string) {
    this.logger.log(message, context);
  }
  warn(message: string, context?: string) {
    this.logger.warn(message, context);
  }
  error(message: string, trace?: string, context?: string) {
    this.logger.error(message, trace, context);
  }
  debug(message: string, context?: string) {
    this.logger.debug(message, context);
  }
}
