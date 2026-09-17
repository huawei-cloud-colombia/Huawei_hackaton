import { Global, Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { AppLogger } from './logger';
import { KafkaService } from './kafka.service';

@Global()
@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      envFilePath: '.env',
    }),
  ],
  providers: [AppLogger, KafkaService],
  exports: [AppLogger, KafkaService, ConfigModule],
})
export class SharedModule {}
