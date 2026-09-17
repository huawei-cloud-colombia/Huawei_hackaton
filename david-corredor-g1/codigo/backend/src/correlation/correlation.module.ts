import { Module } from '@nestjs/common';
import { MongooseModule } from '@nestjs/mongoose';
import { IncidentDoc, IncidentSchema } from './incident.schema';
import { IncidentRepository } from './incident.repository';
import { CorrelationService } from './correlation.service';
import { GlmModule } from '../glm/glm.module';
import { TicketsModule } from '../tickets/tickets.module';
import { SharedModule } from '../shared/shared.module';

@Module({
  imports: [
    SharedModule,
    GlmModule,
    TicketsModule,
    MongooseModule.forFeature([{ name: IncidentDoc.name, schema: IncidentSchema }]),
  ],
  providers: [IncidentRepository, CorrelationService],
  exports: [IncidentRepository, CorrelationService],
})
export class CorrelationModule {}
