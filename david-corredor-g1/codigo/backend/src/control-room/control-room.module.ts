import { Module } from '@nestjs/common';
import { ControlRoomController } from './control-room.controller';
import { ReportsController } from './reports.controller';
import { TicketsModule } from '../tickets/tickets.module';
import { CorrelationModule } from '../correlation/correlation.module';
import { TriageModule } from '../triage/triage.module';
import { AuditModule } from '../audit/audit.module';

@Module({
  imports: [TicketsModule, CorrelationModule, TriageModule, AuditModule],
  controllers: [ControlRoomController, ReportsController],
})
export class ControlRoomModule {}
