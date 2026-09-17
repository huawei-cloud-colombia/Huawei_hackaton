import { TriageResultSchema, TicketInputSchema, extractJson } from './schemas';

describe('Schemas', () => {
  describe('TriageResultSchema', () => {
    it('valida un resultado correcto', () => {
      const valid = {
        category: 'Cuenta y acceso',
        priority: 'P1',
        sentiment: 'negativo',
        product_or_module: 'SSO',
        summary: 'Sin acceso SSO',
        suggested_action: 'Escalar',
        suggested_response: 'Investigando',
        confidence: 0.94,
        requires_human_review: false,
      };
      expect(TriageResultSchema.parse(valid)).toEqual(valid);
    });

    it('rechaza categoría inválida', () => {
      const invalid = { category: 'Invalid', priority: 'P1', sentiment: 'negativo', product_or_module: 'X', summary: 's', suggested_action: 'a', suggested_response: 'r', confidence: 0.5, requires_human_review: false };
      expect(() => TriageResultSchema.parse(invalid)).toThrow();
    });

    it('rechaza prioridad inválida', () => {
      const invalid = { category: 'Otro', priority: 'P9', sentiment: 'negativo', product_or_module: 'X', summary: 's', suggested_action: 'a', suggested_response: 'r', confidence: 0.5, requires_human_review: false };
      expect(() => TriageResultSchema.parse(invalid)).toThrow();
    });

    it('rechaza confidence fuera de rango', () => {
      const invalid = { category: 'Otro', priority: 'P1', sentiment: 'negativo', product_or_module: 'X', summary: 's', suggested_action: 'a', suggested_response: 'r', confidence: 1.5, requires_human_review: false };
      expect(() => TriageResultSchema.parse(invalid)).toThrow();
    });
  });

  describe('TicketInputSchema', () => {
    it('valida un ticket correcto', () => {
      const valid = { ticket_id: 'T1', customer_id: 'ACME', created_at: '2026-09-16T08:15:00Z', region: 'latam', text: 'SSO caído' };
      expect(TicketInputSchema.parse(valid)).toEqual(valid);
    });

    it('rechaza ticket_id vacío', () => {
      expect(() => TicketInputSchema.parse({ ticket_id: '', customer_id: 'C', created_at: '2026-09-16T08:15:00Z', region: 'r', text: 't' })).toThrow();
    });

    it('rechaza text vacío', () => {
      expect(() => TicketInputSchema.parse({ ticket_id: 'T1', customer_id: 'C', created_at: '2026-09-16T08:15:00Z', region: 'r', text: '' })).toThrow();
    });

    it('rechaza timestamp inválido', () => {
      expect(() => TicketInputSchema.parse({ ticket_id: 'T1', customer_id: 'C', created_at: 'not-a-date', region: 'r', text: 't' })).toThrow();
    });
  });

  describe('extractJson', () => {
    it('parsea JSON limpio', () => {
      expect(extractJson('{"a":1}')).toEqual({ a: 1 });
    });

    it('extrae JSON con texto antes', () => {
      expect(extractJson('Aquí está: {"a":1}')).toEqual({ a: 1 });
    });

    it('extrae JSON de markdown code block', () => {
      expect(extractJson('```json\n{"a":1}\n```')).toEqual({ a: 1 });
    });

    it('lanza si no hay JSON', () => {
      expect(() => extractJson('no hay json aqui')).toThrow();
    });
  });
});
