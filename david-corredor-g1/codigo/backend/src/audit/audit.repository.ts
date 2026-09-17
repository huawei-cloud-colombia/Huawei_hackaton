import { Injectable } from '@nestjs/common';
import { InjectModel } from '@nestjs/mongoose';
import { Model } from 'mongoose';
import { AuditLogDoc } from './audit-log.schema';

@Injectable()
export class AuditRepository {
  constructor(
    @InjectModel(AuditLogDoc.name) private readonly model: Model<AuditLogDoc>,
  ) {}

  async log(entry: Partial<AuditLogDoc>): Promise<void> {
    await this.model.create(entry);
  }

  async findByTicketId(ticketId: string): Promise<AuditLogDoc[]> {
    return this.model.find({ ticket_id: ticketId }).sort({ createdAt: -1 }).exec();
  }
}
