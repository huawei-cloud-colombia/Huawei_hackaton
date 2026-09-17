import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { Document } from 'mongoose';

@Schema({ timestamps: true })
export class IncidentDoc extends Document {
  @Prop({ required: true, unique: true, index: true })
  incident_group_id: string;

  @Prop({ required: true })
  title: string;

  @Prop({ required: true })
  ticket_count: number;

  @Prop({ required: true })
  highest_priority: string;

  @Prop({ required: true })
  affected_module: string;

  @Prop({ required: true })
  affected_region: string;

  @Prop({ required: true })
  summary: string;

  @Prop({ default: false })
  major_incident_candidate: boolean;

  @Prop({ type: [String], default: [] })
  ticket_ids: string[];

  @Prop({ type: [String], default: [] })
  affected_customers: string[];

  @Prop({ type: [String], default: [] })
  affected_regions: string[];

  @Prop({ type: Object, default: null })
  executive_brief?: Record<string, unknown>;
}

export const IncidentSchema = SchemaFactory.createForClass(IncidentDoc);
