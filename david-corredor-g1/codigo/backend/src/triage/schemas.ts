import { z } from 'zod';
import { CATEGORIES, PRIORITIES, SENTIMENTS } from '../shared/constants';

/**
 * Schema Zod para la salida de GLM 5.2 en clasificación de triage.
 * Valida estrictamente que la respuesta cumple el contrato del reto.
 */
export const TriageResultSchema = z.object({
  category: z.enum(CATEGORIES),
  priority: z.enum(PRIORITIES),
  sentiment: z.enum(SENTIMENTS),
  product_or_module: z.string().min(1).max(100),
  summary: z.string().min(1).max(500),
  suggested_action: z.string().min(1).max(500),
  suggested_response: z.string().min(1).max(1000),
  confidence: z.number().min(0).max(1),
  requires_human_review: z.boolean(),
});

export type TriageResult = z.infer<typeof TriageResultSchema>;

/**
 * Schema para el ticket de entrada.
 * Un ticket malformado lanza ZodError (manejado por el caller).
 */
export const TicketInputSchema = z.object({
  ticket_id: z.string().min(1, 'ticket_id no puede estar vacío'),
  customer_id: z.string().min(1),
  created_at: z.string().refine((val) => {
    const d = new Date(val);
    return !isNaN(d.getTime());
  }, 'created_at debe ser un timestamp ISO 8601 válido'),
  region: z.string().min(1),
  text: z.string().min(1, 'text no puede estar vacío'),
});

export type TicketInput = z.infer<typeof TicketInputSchema>;

/**
 * Schema para el resultado de correlación de GLM.
 */
export const CorrelationResultSchema = z.object({
  groups: z.array(
    z.object({
      ticket_ids: z.array(z.string()).min(1),
      reason: z.string(),
    }),
  ),
  ungrouped: z.array(z.string()),
});

export type CorrelationResult = z.infer<typeof CorrelationResultSchema>;

/**
 * Extrae JSON de una respuesta que puede tener texto antes/después.
 * Maneja los casos de "GLM devuelve texto antes del JSON".
 */
export function extractJson(raw: string): unknown {
  // Intento 1: parse directo
  try {
    return JSON.parse(raw);
  } catch {
    /* sigue */
  }

  // Intento 2: extraer el primer {...} o [...] balanceado
  const jsonMatch = raw.match(/(\{[\s\S]*\}|\[[\s\S]*\])/);
  if (jsonMatch) {
    try {
      return JSON.parse(jsonMatch[1]);
    } catch {
      /* sigue */
    }
  }

  // Intento 3: buscar ```json ... ``` (markdown)
  const mdMatch = raw.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (mdMatch) {
    try {
      return JSON.parse(mdMatch[1]);
    } catch {
      /* sigue */
    }
  }

  throw new Error(`No se pudo extraer JSON válido de la respuesta: ${raw.slice(0, 200)}...`);
}
