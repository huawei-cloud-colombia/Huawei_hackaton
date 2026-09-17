import { Injectable } from '@nestjs/common';
import { InjectModel } from '@nestjs/mongoose';
import { Model } from 'mongoose';
import { TicketDoc, TicketSchema } from './ticket.schema';

@Injectable()
export class TicketRepository {
  constructor(
    @InjectModel(TicketDoc.name) private readonly model: Model<TicketDoc>,
  ) {}

  async upsert(ticketId: string, data: Partial<TicketDoc>): Promise<TicketDoc> {
    return this.model.findOneAndUpdate(
      { ticket_id: ticketId },
      { $set: data },
      { upsert: true, new: true },
    );
  }

  async findByTicketId(ticketId: string): Promise<TicketDoc | null> {
    return this.model.findOne({ ticket_id: ticketId }).exec();
  }

  async findClassified(): Promise<TicketDoc[]> {
    return this.model.find({ status: 'classified' }).exec();
  }

  async findPending(): Promise<TicketDoc[]> {
    return this.model.find({ status: 'pending' }).exec();
  }

  async findAll(filter: Record<string, unknown> = {}): Promise<TicketDoc[]> {
    return this.model.find(filter).sort({ 'triage.priority': 1, created_at: 1 }).exec();
  }

  async updateTriage(
    ticketId: string,
    triage: TicketDoc['triage'],
    status: 'classified' | 'failed',
    failureReason?: { code: string; message: string },
  ): Promise<void> {
    await this.model.updateOne(
      { ticket_id: ticketId },
      {
        $set: {
          triage,
          status,
          ...(failureReason ? { failure_reason: failureReason } : {}),
        },
      },
    );
  }

  async setIncidentGroup(ticketId: string, incidentGroupId: string): Promise<void> {
    await this.model.updateOne(
      { ticket_id: ticketId },
      { $set: { incident_group_id: incidentGroupId } },
    );
  }

  async countByIncidentGroup(incidentGroupId: string): Promise<number> {
    return this.model.countDocuments({ incident_group_id: incidentGroupId }).exec();
  }

  async findByIncidentGroup(incidentGroupId: string): Promise<TicketDoc[]> {
    return this.model.find({ incident_group_id: incidentGroupId }).exec();
  }
}
