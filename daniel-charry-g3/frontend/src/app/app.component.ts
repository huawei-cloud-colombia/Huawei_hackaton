// app.component.ts — Componente principal NEXUS LIVE Control Room
import { Component, OnInit } from '@angular/core';
import { ApiService } from './api.service';
import {
  Seat, Hold, RaceResult, CircuitBreakerStatus, AuditEvent, AppConfig,
} from './models';

@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.css'],
})
export class AppComponent implements OnInit {
  // Datos
  seats: Seat[] = [];
  holds: Hold[] = [];
  auditEvents: AuditEvent[] = [];
  cbStatus?: CircuitBreakerStatus;
  config?: AppConfig;

  // UI State
  selectedSeats = new Set<string>();
  userId = 'usr_demo';
  idempotencyKey = '';
  confirmHoldId = '';
  paymentToken = 'tok_test_12345';
  raceSeatId = 'VIP-A-001';
  raceNumUsers = 20;
  forcePaymentResult = '';

  // Resultados
  holdResult = '';
  confirmResult = '';
  raceResult?: RaceResult;
  raceDetails: string[] = [];

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.loadAll();
    setInterval(() => this.refreshSeats(), 5000);
  }

  loadAll(): void {
    this.loadSeats();
    this.loadHolds();
    this.loadPaymentStatus();
    this.loadConfig();
  }

  // ─── Asientos ──────────────────────────────────────────────
  loadSeats(): void {
    this.api.getSeats().subscribe({
      next: (seats) => this.seats = seats,
      error: (e) => console.error('Error loading seats', e),
    });
  }

  refreshSeats(): void {
    this.loadSeats();
    this.loadHolds();
  }

  toggleSeat(seat: Seat): void {
    if (seat.status === 'SOLD') return;
    if (this.selectedSeats.has(seat.seat_id)) {
      this.selectedSeats.delete(seat.seat_id);
    } else {
      this.selectedSeats.add(seat.seat_id);
    }
  }

  isSelected(seatId: string): boolean {
    return this.selectedSeats.has(seatId);
  }

  // ─── Reservas ──────────────────────────────────────────────
  loadHolds(): void {
    this.api.getHolds().subscribe({
      next: (holds) => this.holds = holds,
      error: (e) => console.error('Error loading holds', e),
    });
  }

  createHold(): void {
    const seatIds = Array.from(this.selectedSeats);
    if (seatIds.length === 0) {
      this.holdResult = '⚠️ Selecciona al menos un asiento.';
      return;
    }
    this.api.reserve(
      { user_id: this.userId, event_id: 'aurora-bogota-2026', seat_ids: seatIds },
      this.idempotencyKey || undefined,
    ).subscribe({
      next: (data: any) => {
        this.holdResult = `✅ HOLD CREADO\nHold ID: ${data.hold_id}\nAsientos: ${data.seat_ids?.join(', ')}\nTotal: ${data.total} ${data.currency}\nExpira: ${data.expires_at}`;
        this.confirmHoldId = data.hold_id;
        this.selectedSeats.clear();
        this.refreshSeats();
      },
      error: (e) => {
        const err = e.error?.detail || e.error || e;
        this.holdResult = `❌ ERROR\nError: ${err.error || 'unknown'}\nRazón: ${err.reason || JSON.stringify(err)}`;
      },
    });
  }

  releaseHold(): void {
    this.api.releaseHold(this.confirmHoldId).subscribe({
      next: (data) => {
        this.confirmResult = `🔓 HOLD liberado: ${this.confirmHoldId}`;
        this.refreshSeats();
      },
      error: (e) => this.confirmResult = `❌ Error: ${JSON.stringify(e.error)}`,
    });
  }

  // ─── Confirmación ──────────────────────────────────────────
  confirmPurchase(): void {
    this.api.confirm({ hold_id: this.confirmHoldId, payment_token: this.paymentToken }).subscribe({
      next: (data: any) => {
        if (data.success || data.status === 'SOLD') {
          this.confirmResult = `✅ COMPRA CONFIRMADA\nHold: ${data.hold_id}\nPago: ${data.payment_result}\nAsientos: ${data.seats?.join(', ')}\nTotal: ${data.total || 'N/A'} ${data.currency || ''}\nCircuit Breaker: ${data.circuit_breaker || 'N/A'}`;
        } else {
          this.confirmResult = `⚠️ ${data.payment_result || data.error || 'RESULT'}\nHold: ${data.hold_id || this.confirmHoldId}\nMensaje: ${data.message || ''}\nCircuit Breaker: ${data.circuit_breaker || 'N/A'}`;
        }
        this.refreshSeats();
        this.loadPaymentStatus();
      },
      error: (e) => this.confirmResult = `❌ Error: ${JSON.stringify(e.error)}`,
    });
  }

  // ─── Simular carrera ───────────────────────────────────────
  simulateRace(): void {
    this.raceDetails = [];
    this.raceResult = undefined;
    this.api.simulateRace(this.raceSeatId, this.raceNumUsers).subscribe({
      next: (data) => {
        this.raceResult = data;
        this.raceDetails = data.details || [];
        this.refreshSeats();
      },
      error: (e) => this.raceDetails = [`❌ Error: ${JSON.stringify(e.error)}`],
    });
  }

  // ─── Circuit Breaker ───────────────────────────────────────
  loadPaymentStatus(): void {
    this.api.getPaymentStatus().subscribe({
      next: (status) => this.cbStatus = status,
      error: (e) => console.error('Error loading CB status', e),
    });
  }

  forcePayment(): void {
    this.api.forcePayment(this.forcePaymentResult).subscribe(() => this.loadPaymentStatus());
  }

  // ─── Auditoría ─────────────────────────────────────────────
  loadAudit(): void {
    this.api.getAudit().subscribe({
      next: (events) => this.auditEvents = events,
      error: (e) => console.error('Error loading audit', e),
    });
  }

  exportAudit(): void {
    this.api.exportAudit().subscribe({
      next: (data: any) => alert(`Auditoría exportada: ${data.events} eventos → ${data.filepath}`),
    });
  }

  // ─── Config ────────────────────────────────────────────────
  loadConfig(): void {
    this.api.getConfig().subscribe({
      next: (config) => this.config = config,
      error: (e) => console.error('Error loading config', e),
    });
  }

  // ─── Reset ─────────────────────────────────────────────────
  resetSystem(): void {
    if (!confirm('¿Reiniciar el sistema completo?')) return;
    this.api.resetSystem().subscribe(() => {
      this.selectedSeats.clear();
      this.holdResult = '';
      this.confirmResult = '';
      this.raceResult = undefined;
      this.raceDetails = [];
      this.auditEvents = [];
      this.loadAll();
    });
  }

  // ─── Helpers ───────────────────────────────────────────────
  getSeatClass(status: string): string {
    return `seat-${status.toLowerCase()}`;
  }

  getStatusClass(status: string): string {
    return `status-${status}`;
  }

  formatTime(expiresAt: string): string {
    return new Date(expiresAt).toLocaleTimeString();
  }
}
