import { Module } from '@nestjs/common';
import { MongooseModule } from '@nestjs/mongoose';
import { AuditLogDoc, AuditLogSchema } from './audit-log.schema';
import { AuditRepository } from './audit.repository';
import { AuditService } from './audit.service';
import { SharedModule } from '../shared/shared.module';

@Module({
  imports: [
    SharedModule,
    MongooseModule.forFeature([{ name: AuditLogDoc.name, schema: AuditLogSchema }]),
  ],
  providers: [AuditRepository, AuditService],
  exports: [AuditRepository, AuditService],
})
export class AuditModule {}
