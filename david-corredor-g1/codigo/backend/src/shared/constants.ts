/**
 * Constantes de dominio — categorías, prioridades y sentimientos válidos.
 * Fuente de verdad para Zod schemas, prompts y validaciones.
 */

export const CATEGORIES = [
  'Cuenta y acceso',
  'Facturación',
  'Disponibilidad y rendimiento',
  'Integraciones',
  'Datos y exportación',
  'Solicitud de función',
  'Seguridad',
  'Otro',
] as const;
export type Category = (typeof CATEGORIES)[number];

export const PRIORITIES = ['P1', 'P2', 'P3', 'P4'] as const;
export type Priority = (typeof PRIORITIES)[number];

export const SENTIMENTS = ['positivo', 'neutral', 'negativo'] as const;
export type Sentiment = (typeof SENTIMENTS)[number];

/** Orden numérico de prioridad para sorting (P1=1 ... P4=4). */
export const PRIORITY_WEIGHT: Record<Priority, number> = {
  P1: 1,
  P2: 2,
  P3: 3,
  P4: 4,
};

/** Convierte un peso numérico de vuelta a etiqueta de prioridad. */
export function weightToPriority(weight: number): Priority {
  const match = Object.entries(PRIORITY_WEIGHT).find(([, w]) => w === weight);
  return (match?.[0] as Priority) ?? 'P4';
}

/** Devuelve la prioridad más alta (menor peso) de una lista. */
export function highestPriority(priorities: Priority[]): Priority {
  if (priorities.length === 0) return 'P4';
  return priorities.reduce((acc, p) =>
    PRIORITY_WEIGHT[p] < PRIORITY_WEIGHT[acc] ? p : acc,
  );
}
