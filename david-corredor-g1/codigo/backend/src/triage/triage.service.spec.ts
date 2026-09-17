import { Test } from '@nestjs/testing';
import { TriageService } from './triage.service';
import { GlmService } from '../glm/glm.service';
import { TicketRepository } from '../tickets/ticket.repository';
import { KafkaService } from '../shared/kafka.service';
import { AuditService } from '../audit/audit.service';
import { ConfigService } from '@nestjs/config';
import { AppLogger } from '../shared/logger';
import type { TriageResult } from './schemas';

describe('TriageService', () => {
  let service: TriageService;
  let glm: { classifyTicket: jest.Mock };
  let tickets: { upsert: jest.Mock; updateTriage: jest.Mock };
  let kafka: { emit: jest.Mock };
  let audit: { log: jest.Mock };

  beforeEach(async () => {
    glm = { classifyTicket: jest.fn() };
    tickets = { upsert: jest.fn().mockResolvedValue(undefined), updateTriage: jest.fn().mockResolvedValue(undefined) };
    kafka = { emit: jest.fn().mockResolvedValue(undefined) };
    audit = { log: jest.fn().mockResolvedValue('corr-1') };

    const module = await Test.createTestingModule({
      providers: [
        TriageService,
        { provide: GlmService, useValue: glm },
        { provide: TicketRepository, useValue: tickets },
        { provide: KafkaService, useValue: kafka },
        { provide: AuditService, useValue: audit },
        { provide: ConfigService, useValue: { get: (k: string, d?: unknown) => d } },
        { provide: AppLogger, useValue: { log: jest.fn(), warn: jest.fn(), error: jest.fn(), debug: jest.fn() } },
      ],
    }).compile();

    service = module.get(TriageService);
  });

  const validTicket = {
    ticket_id: 'T1',
    customer_id: 'ACME',
    created_at: '2026-09-16T08:15:00Z',
    region: 'latam-north',
    text: '1.800 usuarios no pueden iniciar sesión con SSO.',
  };

  const validResult: TriageResult = {
    category: 'Cuenta y acceso',
    priority: 'P1',
    sentiment: 'negativo',
    product_or_module: 'SSO',
    summary: 'Usuarios sin acceso SSO',
    suggested_action: 'Escalar a identidad',
    suggested_response: 'Investigando...',
    confidence: 0.94,
    requires_human_review: false,
  };

  it('clasifica un ticket válido correctamente', async () => {
    glm.classifyTicket.mockResolvedValue(validResult);
    const result = await service.processTicket(validTicket);
    expect(result.ticket_id).toBe('T1');
    expect(result.category).toBe('Cuenta y acceso');
    expect(result.priority).toBe('P1');
    expect(result.degraded).toBe(false);
    expect(tickets.updateTriage).toHaveBeenCalledWith('T1', expect.any(Object), 'classified');
  });

  it('marca requires_human_review cuando confidence < threshold', async () => {
    glm.classifyTicket.mockResolvedValue({ ...validResult, confidence: 0.4 });
    const result = await service.processTicket(validTicket);
    expect(result.requires_human_review).toBe(true);
  });

  it('degrada gracefully cuando GLM falla en todos los intentos', async () => {
    glm.classifyTicket.mockRejectedValue(new Error('API timeout'));
    const result = await service.processTicket(validTicket);
    expect(result.degraded).toBe(true);
    expect(result.requires_human_review).toBe(true);
    expect(result.category).toBe('Otro');
  });

  it('no detiene el lote ante un ticket malformado', async () => {
    const malformed = { ticket_id: '', text: '' };
    const result = await service.processTicket(malformed);
    expect(result.degraded).toBe(true);
    expect(result.requires_human_review).toBe(true);
  });

  it('reintenta con backoff cuando GLM falla temporalmente', async () => {
    glm.classifyTicket
      .mockRejectedValueOnce(new Error('temporal'))
      .mockResolvedValueOnce(validResult);
    const result = await service.processTicket(validTicket);
    expect(result.degraded).toBe(false);
    expect(glm.classifyTicket).toHaveBeenCalledTimes(2);
  });
});
