import { Module } from '@nestjs/common';
import { GlmService } from './glm.service';
import { SharedModule } from '../shared/shared.module';

@Module({
  imports: [SharedModule],
  providers: [GlmService],
  exports: [GlmService],
})
export class GlmModule {}
