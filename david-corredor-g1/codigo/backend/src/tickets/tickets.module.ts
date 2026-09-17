import { Module, forwardRef } from '@nestjs/common';
import { MongooseModule } from '@nestjs/mongoose';
import { TicketDoc, TicketSchema } from './ticket.schema';
import { TicketRepository } from './ticket.repository';
import { TicketsService } from './tickets.service';
import { TicketsController } from './tickets.controller';
import { TriageModule } from '../triage/triage.module';
import { SharedModule } from '../shared/shared.module';

@Module({
  imports: [
    SharedModule,
    forwardRef(() => TriageModule),
    MongooseModule.forFeature([{ name: TicketDoc.name, schema: TicketSchema }]),
  ],
  providers: [TicketRepository, TicketsService],
  controllers: [TicketsController],
  exports: [TicketRepository, TicketsService],
})
export class TicketsModule {}
