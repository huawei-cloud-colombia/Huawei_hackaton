import { Injectable } from '@nestjs/common';
import { InjectModel } from '@nestjs/mongoose';
import { Model } from 'mongoose';
import { IncidentDoc } from './incident.schema';

@Injectable()
export class IncidentRepository {
  constructor(
    @InjectModel(IncidentDoc.name) private readonly model: Model<IncidentDoc>,
  ) {}

  async upsert(incidentGroupId: string, data: Partial<IncidentDoc>): Promise<IncidentDoc> {
    return this.model.findOneAndUpdate(
      { incident_group_id: incidentGroupId },
      { $set: data },
      { upsert: true, new: true },
    );
  }

  async findAll(): Promise<IncidentDoc[]> {
    return this.model.find().sort({ major_incident_candidate: -1, highest_priority: 1 }).exec();
  }

  async findById(incidentGroupId: string): Promise<IncidentDoc | null> {
    return this.model.findOne({ incident_group_id: incidentGroupId }).exec();
  }

  async findMajorCandidates(): Promise<IncidentDoc[]> {
    return this.model.find({ major_incident_candidate: true }).exec();
  }
}
