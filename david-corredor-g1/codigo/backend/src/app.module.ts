import { Module } from '@nestjs/common';
import { MongooseModule } from '@nestjs/mongoose';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { SharedModule } from './shared/shared.module';
import { KafkaService } from './shared/kafka.service';
import { AppLogger } from './shared/logger';
import { GlmModule } from './glm/glm.module';
import { TicketsModule } from './tickets/tickets.module';
import { TriageModule } from './triage/triage.module';
import { CorrelationModule } from './correlation/correlation.module';
import { AuditModule } from './audit/audit.module';
import { ControlRoomModule } from './control-room/control-room.module';
import { HealthController } from './health.controller';

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true, envFilePath: '.env' }),
    MongooseModule.forRootAsync({
      imports: [ConfigModule],
      inject: [ConfigService],
      useFactory: (config: ConfigService) => ({
        uri:
          config.get<string>('MONGO_URI') ??
          'mongodb://atlas:atlasdev@localhost:27017/atlas?authSource=admin',
      }),
    }),
    SharedModule,
    GlmModule,
    AuditModule,
    TicketsModule,
    TriageModule,
    CorrelationModule,
    ControlRoomModule,
  ],
  controllers: [HealthController],
  providers: [AppLogger],
})
export class AppModule {}
