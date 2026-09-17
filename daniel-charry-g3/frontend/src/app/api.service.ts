// api.service.ts — Servicio para consumir la API de NEXUS LIVE
import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  Seat, Hold, ReserveRequest, ReserveResponse,
  ConfirmRequest, ConfirmResponse, RaceResult,
  CircuitBreakerStatus, AuditEvent, AppConfig,
} from './models';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private baseUrl = 'http://localhost:8000';

  constructor(private http: HttpClient) {}

  // ─── Asientos ──────────────────────────────────────────────
  getSeats(): Observable<Seat[]> {
    return this.http.get<Seat[]>(`${this.baseUrl}/api/seats`);
  }

  getAvailableSeats(): Observable<Seat[]> {
    return this.http.get<Seat[]>(`${this.baseUrl}/api/seats/available`);
  }

  // ─── Reservas ──────────────────────────────────────────────
  reserve(req: ReserveRequest, idempotencyKey?: string): Observable<ReserveResponse> {
    let headers = new HttpHeaders({ 'Content-Type': 'application/json' });
    if (idempotencyKey) {
      headers = headers.set('Idempotency-Key', idempotencyKey);
    }
    return this.http.post<ReserveResponse>(`${this.baseUrl}/api/reserve`, req, { headers });
  }

  getHolds(): Observable<Hold[]> {
    return this.http.get<Hold[]>(`${this.baseUrl}/api/holds`);
  }

  getHold(holdId: string): Observable<Hold> {
    return this.http.get<Hold>(`${this.baseUrl}/api/holds/${holdId}`);
  }

  releaseHold(holdId: string): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/holds/${holdId}/release`, {});
  }

  // ─── Confirmación ──────────────────────────────────────────
  confirm(req: ConfirmRequest): Observable<ConfirmResponse> {
    return this.http.post<ConfirmResponse>(`${this.baseUrl}/api/confirm`, req);
  }

  // ─── Simulación de carrera ────────────────────────────────
  simulateRace(seatId: string, numUsers: number): Observable<RaceResult> {
    return this.http.post<RaceResult>(`${this.baseUrl}/api/simulate/race`, {
      seat_id: seatId,
      num_users: numUsers,
    });
  }

  // ─── Auditoría ────────────────────────────────────────────
  getAudit(): Observable<AuditEvent[]> {
    return this.http.get<AuditEvent[]>(`${this.baseUrl}/api/audit`);
  }

  getAuditByHold(holdId: string): Observable<AuditEvent[]> {
    return this.http.get<AuditEvent[]>(`${this.baseUrl}/api/audit/${holdId}`);
  }

  exportAudit(): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/audit/export`);
  }

  // ─── Circuit Breaker ──────────────────────────────────────
  getPaymentStatus(): Observable<CircuitBreakerStatus> {
    return this.http.get<CircuitBreakerStatus>(`${this.baseUrl}/api/payment/status`);
  }

  forcePayment(result: string): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/payment/force`, { result });
  }

  // ─── Config ───────────────────────────────────────────────
  getConfig(): Observable<AppConfig> {
    return this.http.get<AppConfig>(`${this.baseUrl}/api/config`);
  }

  // ─── Reset ────────────────────────────────────────────────
  resetSystem(): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/reset`, {});
  }
}
