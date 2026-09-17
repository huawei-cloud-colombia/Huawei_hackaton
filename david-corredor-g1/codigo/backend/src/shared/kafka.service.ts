import { Injectable, OnModuleInit, OnModuleDestroy } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Kafka, Producer, Consumer, EachMessagePayload } from 'kafkajs';
import { AppLogger } from '../shared/logger';
import { KafkaError } from '../shared/errors';

export const TOPICS = {
  TICKETS_RAW: 'tickets.raw',
  TICKETS_CLASSIFIED: 'tickets.classified',
  INCIDENTS_DETECTED: 'incidents.detected',
} as const;

/**
 * Wrapper sobre KafkaJS — productor y consumidores.
 * Se conecta al broker configurado (por defecto localhost:9092).
 */
@Injectable()
export class KafkaService implements OnModuleInit, OnModuleDestroy {
  private kafka!: Kafka;
  private producer!: Producer;
  private consumers: Consumer[] = [];

  constructor(
    private readonly config: ConfigService,
    private readonly logger: AppLogger,
  ) {}

  async onModuleInit() {
    const brokers = (this.config.get<string>('KAFKA_BROKERS') ?? 'localhost:9092').split(',');
    const clientId = this.config.get<string>('KAFKA_CLIENT_ID') ?? 'atlas-backend';

    this.kafka = new Kafka({ clientId, brokers });
    this.producer = this.kafka.producer();
    await this.producer.connect();
    this.logger.log(`Kafka productor conectado a ${brokers.join(',')}`, 'KafkaService');
  }

  async onModuleDestroy() {
    for (const c of this.consumers) await c.disconnect().catch(() => {});
    await this.producer.disconnect().catch(() => {});
  }

  async emit(topic: string, value: unknown, key?: string): Promise<void> {
    try {
      await this.producer.send({
        topic,
        messages: [{ key: key ?? undefined, value: JSON.stringify(value) }],
      });
    } catch (err) {
      throw new KafkaError(`Error emitiendo a topic ${topic}: ${(err as Error).message}`, err);
    }
  }

  /**
   * Suscribe un handler a un topic con un consumer group.
   * El handler recibe el mensaje parseado.
   */
  async subscribe(
    topic: string,
    groupId: string,
    handler: (value: unknown, key?: string) => Promise<void>,
  ): Promise<void> {
    const consumer = this.kafka.consumer({ groupId });
    this.consumers.push(consumer);
    await consumer.connect();
    await consumer.subscribe({ topic, fromBeginning: true });
    await consumer.run({
      eachMessage: async (payload: EachMessagePayload) => {
        try {
          const value = JSON.parse(payload.message.value?.toString() ?? '{}');
          const key = payload.message.key?.toString();
          await handler(value, key);
        } catch (err) {
          this.logger.error(
            `Error procesando mensaje de ${topic}: ${(err as Error).message}`,
            (err as Error).stack,
            'KafkaService',
          );
        }
      },
    });
    this.logger.log(`Kafka consumer suscrito a ${topic} (group: ${groupId})`, 'KafkaService');
  }
}
