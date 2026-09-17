// models.ts — Modelos de dominio NEXUS LIVE

export interface Seat {
  seat_id: string;
  section: string;
  price: number;
  currency: string;
  status: 'AVAILABLE' | 'HELD' | 'SOLD';
}

export interface Hold {
  hold_id: string;
  user_id: string;
  event_id: string;
  seat_ids: string[];
  status: 'ACTIVE' | 'EXPIRED' | 'CONFIRMED' | 'RELEASED';
  total: number;
  currency: string;
  created_at: string;
  expires_at: string;
  time_remaining?: number;
}

export interface ReserveRequest {
  user_id: string;
  event_id: string;
  seat_ids: string[];
}

export interface ReserveResponse {
  success: boolean;
  hold_id?: string;
  user_id?: string;
  event_id?: string;
  seat_ids?: string[];
  status?: string;
  total?: number;
  currency?: string;
  expires_at?: string;
  error?: string;
  reason?: string;
}

export interface ConfirmRequest {
  hold_id: string;
  payment_token: string;
}

export interface ConfirmResponse {
  success: boolean;
  hold_id: string;
  status: string;
  payment_result?: string;
  seats?: string[];
  total?: number;
  currency?: string;
  message?: string;
  circuit_breaker?: string;
}

export interface RaceResult {
  success: boolean;
  seat_id: string;
  total_requests: number;
  winners: number;
  rejected: number;
  hold_id?: string;
  details: string[];
}

export interface CircuitBreakerStatus {
  state: 'CLOSED' | 'OPEN' | 'HALF_OPEN';
  failure_count: number;
  failure_threshold: number;
  recovery_timeout: number;
}

export interface AuditEvent {
  hold_id?: string;
  user_id?: string;
  seat_id?: string;
  from_state?: string;
  to_state?: string;
  reason: string;
  timestamp: string;
  extra?: any;
}

export interface AppConfig {
  hold_ttl_seconds: number;
  max_seats_per_user: number;
  currency: string;
  default_event_id: string;
  circuit_breaker: CircuitBreakerStatus;
  payment_probs: {
    approved: number;
    declined: number;
    error: number;
    timeout: number;
  };
  seat_sections: Record<string, { prefix: string; count: number; price: number }>;
}
