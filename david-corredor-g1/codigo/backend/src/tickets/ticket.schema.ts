import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { Document } from 'mongoose';

/**
 * Documento de ticket persistido en MongoDB.
 * Contiene el ticket original + el resultado de triage embebido.
 */
@Schema({ timestamps: true })
export class TicketDoc extends Document {
  @Prop({ required: true, index: true })
  ticket_id: string;

  @Prop({ required: true })
  customer_id: string;

  @Prop({ required: true })
  created_at: string;

  @Prop({ required: true, index: true })
  region: string;

  @Prop({ required: true })
  text: string;

  // Resultado de triage (embebido)
  @Prop({ type: Object, default: null })
  triage?: {
    category: string;
    priority: string;
    sentiment: string;
    product_or_module: string;
    summary: string;
    suggested_action: string;
    suggested_response: string;
    confidence: number;
    requires_human_review: boolean;
  };

  @Prop({ default: 'pending' })
  status: 'pending' | 'classified' | 'failed';

  @Prop({ type: Object, default: null })
  failure_reason?: { code: string; message: string };

  @Prop({ default: null, index: true })
  incident_group_id?: string;
}

export const TicketSchema = SchemaFactory.createForClass(TicketDoc);
