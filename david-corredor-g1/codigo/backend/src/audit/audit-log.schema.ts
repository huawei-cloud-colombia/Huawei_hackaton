import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { Document } from 'mongoose';

/**
 * Log auditable — NUNCA contiene API keys, tokens ni secretos.
 */
@Schema({ timestamps: true })
export class AuditLogDoc extends Document {
  @Prop({ required: true, index: true })
  ticket_id: string;

  @Prop({ required: true })
  model_name: string;

  @Prop({ required: true })
  attempts: number;

  @Prop({ required: true })
  validation_status: 'valid' | 'invalid' | 'degraded';

  @Prop({ required: true })
  correlation_id: string;

  @Prop({ required: true })
  processed_at: string;

  @Prop({ default: null })
  error_code?: string;

  @Prop({ default: null })
  error_message?: string;
}

export const AuditLogSchema = SchemaFactory.createForClass(AuditLogDoc);
