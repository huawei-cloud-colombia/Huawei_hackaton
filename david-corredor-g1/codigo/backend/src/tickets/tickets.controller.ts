import { Body, Controller, Get, Param, Post, Query } from '@nestjs/common';
import { TicketsService } from './tickets.service';
import { TicketRepository } from './ticket.repository';
import { ApiTags, ApiOperation, ApiBody } from '@nestjs/swagger';

@ApiTags('tickets')
@Controller('tickets')
export class TicketsController {
  constructor(
    private readonly service: TicketsService,
    private readonly repo: TicketRepository,
  ) {}

  @Post('ingest')
  @ApiOperation({ summary: 'Ingiere un lote de tickets (publica a Kafka)' })
  @ApiBody({ description: 'Array de tickets' })
  async ingest(@Body() body: unknown) {
    const tickets = Array.isArray(body) ? body : [body];
    return this.service.ingestBatch(tickets);
  }

  @Post('ingest-file')
  @ApiOperation({ summary: 'Ingiere tickets desde un archivo JSON' })
  async ingestFile(@Body('path') path: string) {
    return this.service.ingestFromFile(path);
  }

  @Post('classify')
  @ApiOperation({ summary: 'Clasifica tickets síncronamente (pipeline completo)' })
  async classify(@Body() body: unknown) {
    const tickets = Array.isArray(body) ? body : [body];
    return this.service.processSync(tickets);
  }

  @Get()
  @ApiOperation({ summary: 'Lista todos los tickets (con filtros opcionales)' })
  async list(
    @Query('priority') priority?: string,
    @Query('category') category?: string,
    @Query('region') region?: string,
    @Query('module') module?: string,
    @Query('incident_group_id') incidentGroupId?: string,
  ) {
    const filter: Record<string, unknown> = {};
    if (priority) filter['triage.priority'] = priority;
    if (category) filter['triage.category'] = category;
    if (region) filter.region = region;
    if (module) filter['triage.product_or_module'] = module;
    if (incidentGroupId) filter.incident_group_id = incidentGroupId;
    return this.repo.findAll(filter);
  }

  @Get(':id')
  @ApiOperation({ summary: 'Obtiene el detalle de un ticket' })
  async getById(@Param('id') id: string) {
    return this.repo.findByTicketId(id);
  }
}
