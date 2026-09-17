import { Injectable, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import OpenAI from 'openai';
import pLimit from 'p-limit';
import { AppLogger } from '../shared/logger';
import { GlmApiError, SchemaValidationError } from '../shared/errors';
import {
  TRIAGE_SYSTEM_PROMPT,
  CORRELATION_SYSTEM_PROMPT,
  buildTicketUserMessage,
} from './prompts';
import { TriageResultSchema, CorrelationResultSchema, extractJson, type TriageResult, type CorrelationResult } from '../triage/schemas';
import { CATEGORIES, PRIORITIES, SENTIMENTS } from '../shared/constants';

/**
 * Wrapper sobre el SDK oficial de OpenAI configurado para apuntar a
 * Huawei Cloud MaaS (endpoint OpenAI-compatible) usando el modelo GLM 5.2.
 *
 * - Structured output vía function calling (tool_choice forzado).
 * - Rate limiter (p-limit) para control de cuota — Bono B.
 * - Timeout configurable.
 */
@Injectable()
export class GlmService implements OnModuleInit {
  private client!: OpenAI;
  private model!: string;
  private limit!: ReturnType<typeof pLimit>;
  private timeoutMs!: number;

  constructor(
    private readonly config: ConfigService,
    private readonly logger: AppLogger,
  ) {}

  onModuleInit() {
    const apiKey = this.config.get<string>('MAAS_API_KEY');
    const baseURL =
      this.config.get<string>('GLM_BASE_URL') ??
      'https://api-ap-southeast-1.modelarts-maas.com/openai/v1';

    if (!apiKey) {
      this.logger.warn(
        'MAAS_API_KEY no configurada — GLM 5.2 no disponible. Las llamadas fallarán y los tickets se marcarán para revisión humana.',
        'GlmService',
      );
    }

    this.client = new OpenAI({
      apiKey: apiKey ?? 'missing',
      baseURL,
      maxRetries: 0, // gestionamos retries nosotros para backoff custom
      timeout: Number(this.config.get<string>('GLM_TIMEOUT_MS', '30000')),
    });
    this.model = this.config.get<string>('GLM_MODEL') ?? 'glm-5.2';
    this.timeoutMs = Number(this.config.get<string>('GLM_TIMEOUT_MS', '30000'));
    this.limit = pLimit(Number(this.config.get<string>('GLM_MAX_CONCURRENCY', '5')));
    this.logger.log(`GLM 5.2 configurado — modelo: ${this.model}, baseURL: ${baseURL}`, 'GlmService');
  }

  /**
   * Clasifica un ticket usando function calling para forzar schema.
   * Rate-limited (Bono B). Lanza GlmApiError o SchemaValidationError.
   */
  async classifyTicket(ticketText: string): Promise<TriageResult> {
    return this.limit(async () => {
      try {
        const response = await this.client.chat.completions.create({
          model: this.model,
          messages: [
            { role: 'system', content: TRIAGE_SYSTEM_PROMPT },
            { role: 'user', content: buildTicketUserMessage(ticketText) },
          ],
          temperature: 0.4,
          tools: [CLASSIFY_TOOL],
          tool_choice: { type: 'function', function: { name: 'classify_ticket' } },
        });

        const toolCall = response.choices[0]?.message?.tool_calls?.[0];
        if (!toolCall || !toolCall.function.arguments) {
          // Fallback: intentar parsear el content como JSON
          const content = response.choices[0]?.message?.content ?? '';
          if (!content) {
            throw new SchemaValidationError('GLM no devolvió tool_call ni content');
          }
          const parsed = extractJson(content);
          return TriageResultSchema.parse(parsed);
        }

        const args = JSON.parse(toolCall.function.arguments);
        return TriageResultSchema.parse(args);
      } catch (err) {
        if (err instanceof SchemaValidationError) throw err;
        if (err instanceof OpenAI.APIError) {
          throw new GlmApiError(
            `GLM API error ${err.status}: ${err.message}`,
            err,
          );
        }
        if (err instanceof Error && err.name === 'ZodError') {
          throw new SchemaValidationError('Salida de GLM no cumple el schema', err);
        }
        throw new GlmApiError(`Error inesperado llamando GLM: ${(err as Error).message}`, err);
      }
    });
  }

  /**
   * Correlaciona un batch de tickets usando GLM 5.2.
   * Recibe tickets clasificados y devuelve grupos + ungrouped.
   */
  async correlateTickets(
    tickets: Array<{ ticket_id: string; category: string; product_or_module: string; region: string; created_at: string; summary: string }>,
  ): Promise<CorrelationResult> {
    return this.limit(async () => {
      try {
        const userMessage = `Tickets a correlacionar (JSON):\n${JSON.stringify(tickets, null, 2)}`;
        const response = await this.client.chat.completions.create({
          model: this.model,
          messages: [
            { role: 'system', content: CORRELATION_SYSTEM_PROMPT },
            { role: 'user', content: userMessage },
          ],
          temperature: 0.3,
          response_format: { type: 'json_object' },
        });

        const content = response.choices[0]?.message?.content ?? '';
        if (!content) {
          throw new SchemaValidationError('GLM no devolvió content para correlación');
        }
        const parsed = extractJson(content);
        return CorrelationResultSchema.parse(parsed);
      } catch (err) {
        if (err instanceof SchemaValidationError) throw err;
        if (err instanceof OpenAI.APIError) {
          throw new GlmApiError(`GLM API error en correlación ${err.status}: ${err.message}`, err);
        }
        throw new GlmApiError(`Error en correlación: ${(err as Error).message}`, err);
      }
    });
  }

  /**
   * Genera un brief ejecutivo para un incidente mayor (Bono D — opcional).
   */
  async generateExecutiveBrief(incident: {
    incident_id: string;
    title: string;
    ticket_count: number;
    summary: string;
    affected_module: string;
    affected_region: string;
  }): Promise<{
    executive_summary: string;
    affected_scope: string;
    probable_pattern: string;
    recommended_next_actions: string[];
  }> {
    const response = await this.client.chat.completions.create({
      model: this.model,
      messages: [
        {
          role: 'system',
          content: `Eres un analista de incidentes mayor de ATLAS Cloud. Genera un brief ejecutivo conciso en español para un incidente mayor. Devuelve JSON con: executive_summary, affected_scope, probable_pattern, recommended_next_actions (array de strings).`,
        },
        {
          role: 'user',
          content: `Incidente:\n${JSON.stringify(incident, null, 2)}`,
        },
      ],
      temperature: 0.5,
      response_format: { type: 'json_object' },
    });
    const content = response.choices[0]?.message?.content ?? '';
    return extractJson(content) as Awaited<ReturnType<typeof this.generateExecutiveBrief>>;
  }
}

/** Definición de la function-calling tool para clasificación. */
const CLASSIFY_TOOL: OpenAI.Chat.Completions.ChatCompletionTool = {
  type: 'function',
  function: {
    name: 'classify_ticket',
    description: 'Clasifica un ticket de soporte en categoría, prioridad, sentimiento, módulo, resumen, acción y respuesta sugerida.',
    parameters: {
      type: 'object',
      properties: {
        category: { type: 'string', enum: CATEGORIES as unknown as string[], description: 'Categoría del ticket' },
        priority: { type: 'string', enum: PRIORITIES as unknown as string[], description: 'Prioridad operacional' },
        sentiment: { type: 'string', enum: SENTIMENTS as unknown as string[], description: 'Sentimiento del cliente' },
        product_or_module: { type: 'string', description: 'Producto o módulo afectado' },
        summary: { type: 'string', description: 'Resumen técnico conciso' },
        suggested_action: { type: 'string', description: 'Acción sugerida al equipo de soporte' },
        suggested_response: { type: 'string', description: 'Borrador de primera respuesta al cliente' },
        confidence: { type: 'number', description: 'Confianza 0-1' },
        requires_human_review: { type: 'boolean', description: 'True si requiere revisión humana' },
      },
      required: [
        'category',
        'priority',
        'sentiment',
        'product_or_module',
        'summary',
        'suggested_action',
        'suggested_response',
        'confidence',
        'requires_human_review',
      ],
    },
  },
};
