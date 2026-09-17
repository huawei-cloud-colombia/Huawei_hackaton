import * as fs from 'fs';
import * as path from 'path';
import { TicketInputSchema } from '../triage/schemas';

/**
 * Bono A — Defensa adversarial.
 * Verifica que el dataset adversarial se carga y que los tickets maliciosos
 * son validados sin exponer secretos ni romper el schema.
 */
describe('Bono A — Adversarial defense', () => {
  const adversarialPath = path.resolve(__dirname, '../../../data/tickets_adversarial.json');
  const adversarial = JSON.parse(fs.readFileSync(adversarialPath, 'utf-8'));

  it('el dataset adversarial existe y tiene tickets', () => {
    expect(Array.isArray(adversarial)).toBe(true);
    expect(adversarial.length).toBeGreaterThanOrEqual(10);
  });

  it('ningún ticket adversarial contiene secretos en el texto que pasen al prompt', () => {
    for (const ticket of adversarial) {
      // El texto puede INTENTAR pedir secretos, pero no debe contener secretos reales
      expect(ticket.text).not.toMatch(/MAAS_API_KEY=\w/);
      expect(ticket.text).not.toMatch(/password\s*[:=]\s*\w+/i);
    }
  });

  it('los tickets adversarial con prompt injection son detectados', () => {
    const injectionTickets = adversarial.filter((t: { text: string }) =>
      /ignora|ignore|system override|revele|devuelve la api/i.test(t.text),
    );
    expect(injectionTickets.length).toBeGreaterThanOrEqual(5);
  });

  it('un ticket con texto extremadamente largo es truncado por el prompt builder', async () => {
    const { buildTicketUserMessage, MAX_TICKET_TEXT_LENGTH } = await import('../glm/prompts');
    const longTicket = adversarial.find((t: { text: string }) => t.text.length > 200);
    expect(longTicket).toBeDefined();
    const message = buildTicketUserMessage(longTicket.text.repeat(20));
    expect(message.length).toBeLessThan(longTicket.text.length * 20);
    expect(message).toContain('TRUNCADO');
  });

  it('todos los tickets adversarial pasan la validación de entrada (tienen campos requeridos)', () => {
    for (const ticket of adversarial) {
      // Pueden tener texto malicioso, pero la estructura debe ser válida
      const result = TicketInputSchema.safeParse(ticket);
      expect(result.success).toBe(true);
    }
  });
});
