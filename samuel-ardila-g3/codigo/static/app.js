const API = '';
let selectedSeats = new Set();
let currentHoldId = null;
let refreshTimer = null;

function toast(msg, isError) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show' + (isError ? ' error' : '');
  setTimeout(() => el.className = 'toast', 3000);
}

async function api(path, opts) {
  const res = await fetch(API + path, opts);
  return { ok: res.ok, status: res.status, data: await res.json() };
}

async function apiPost(path, body, headers) {
  const opts = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(headers || {}) },
    body: JSON.stringify(body),
  };
  return api(path, opts);
}

async function loadSeats() {
  const section = document.getElementById('section-filter').value;
  const r = await api('/api/seats' + (section ? '?section=' + section : ''));
  const map = document.getElementById('seat-map');
  map.innerHTML = '';
  for (const s of r.data.seats) {
    const el = document.createElement('div');
    el.className = `seat seat-${s.status}` + (selectedSeats.has(s.seat_id) ? ' seat-selected' : '');
    el.textContent = s.seat_id.replace('GEN-A-', 'G').replace('VIP-A-', 'V');
    el.title = `${s.seat_id} | ${s.section} | ${s.price} ${s.currency} | ${s.status}`;
    if (s.status === 'AVAILABLE') {
      el.onclick = () => toggleSeat(s.seat_id, el);
    }
    map.appendChild(el);
  }
}

function toggleSeat(seatId, el) {
  if (selectedSeats.has(seatId)) {
    selectedSeats.delete(seatId);
    el.classList.remove('seat-selected');
  } else {
    selectedSeats.add(seatId);
    el.classList.add('seat-selected');
  }
  document.getElementById('selected-count').textContent = `${selectedSeats.size} seleccionados`;
}

async function createHold(seatIds, userId) {
  const idemKey = `reserve-${userId}-${Date.now()}`;
  const r = await apiPost('/api/holds', {
    user_id: userId || document.getElementById('user-id').value,
    event_id: 'aurora-bogota-2026',
    seat_ids: seatIds,
  }, { 'Idempotency-Key': idemKey });
  return r;
}

async function btnReserve() {
  if (selectedSeats.size === 0) { toast('Selecciona al menos un asiento', true); return; }
  const seatIds = Array.from(selectedSeats);
  const r = await createHold(seatIds, document.getElementById('user-id').value);
  if (r.ok) {
    toast(`Hold creado: ${r.data.hold_id}`);
    currentHoldId = r.data.hold_id;
    selectedSeats.clear();
    showHoldInfo(r.data);
    await loadSeats();
    await loadAudit(r.data.hold_id);
  } else {
    toast(`Error: ${r.data.error}`, true);
  }
}

async function btnSimReserve() {
  const r = await api('/api/seats');
  const avail = r.data.seats.filter(s => s.status === 'AVAILABLE');
  if (avail.length < 2) { toast('No hay asientos disponibles', true); return; }
  const pick = [avail[0].seat_id, avail[1].seat_id];
  toast(`Simulando reserva de ${pick.join(', ')}...`);
  const res = await createHold(pick, 'usr_juez_sim');
  if (res.ok) {
    toast(`Reserva simulada: ${res.data.hold_id}`);
    currentHoldId = res.data.hold_id;
    showHoldInfo(res.data);
    await loadSeats();
    await loadAudit(res.data.hold_id);
  } else {
    toast(`Error: ${res.data.error}`, true);
  }
}

function showHoldInfo(hold) {
  const el = document.getElementById('hold-info');
  const fmt = v => v ? v : '-';
  el.innerHTML = `
    <div class="field"><span class="label">Hold ID</span><span class="value">${hold.hold_id}</span></div>
    <div class="field"><span class="label">Usuario</span><span class="value">${hold.user_id}</span></div>
    <div class="field"><span class="label">Asientos</span><span class="value">${hold.seat_ids.join(', ')}</span></div>
    <div class="field"><span class="label">Total</span><span class="value">${hold.total} ${hold.currency}</span></div>
    <div class="field"><span class="label">Estado</span><span class="value">${hold.status}</span></div>
    <div class="field"><span class="label">Expira</span><span class="value">${hold.expires_at}</span></div>
    <div class="field"><span class="label">Restante</span><span class="value">${Math.round(hold.remaining_seconds || 0)}s</span></div>
  `;
  document.getElementById('pay-section').style.display = hold.status === 'HELD' ? 'block' : 'none';
}

async function refreshHold() {
  if (!currentHoldId) return;
  const r = await api('/api/holds/' + currentHoldId);
  if (r.ok) {
    showHoldInfo(r.data);
    if (r.data.status === 'HELD') {
      await loadAudit(currentHoldId);
    }
  }
}

async function btnPay() {
  if (!currentHoldId) { toast('No hay reserva activa', true); return; }
  const token = document.getElementById('payment-token').value;
  const scenario = document.getElementById('scenario').value;
  toast('Procesando pago...');
  const r = await apiPost('/api/holds/' + currentHoldId + '/confirm', {
    payment_token: token,
    scenario: scenario,
  });
  if (r.ok) {
    toast(`Pago: ${r.data.result} - Asiento: ${r.data.status}`);
    showHoldInfo({ ...r.data, seat_ids: [], remaining_seconds: 0 });
    await loadSeats();
    await loadAudit(currentHoldId);
    if (r.data.recurrence) {
      showRecurrence(r.data.recurrence);
    }
  } else {
    toast(`Error: ${r.data.error}`, true);
    if (r.data.error === 'PAYMENT_SERVICE_UNAVAILABLE') {
      await updateCB();
    }
  }
}

async function btnRelease() {
  if (!currentHoldId) return;
  const r = await api('/api/holds/' + currentHoldId, { method: 'DELETE' });
  if (r.ok) {
    toast('Hold liberado');
    document.getElementById('pay-section').style.display = 'none';
    await loadSeats();
    await loadAudit(currentHoldId);
  } else {
    toast(`Error: ${r.data.error}`, true);
  }
}

async function btnRace() {
  const seatId = document.getElementById('race-seat').value;
  const n = parseInt(document.getElementById('race-n').value);
  toast(`Lanzando ${n} solicitudes sobre ${seatId}...`);
  const r = await apiPost('/api/simulate/race', { seat_id: seatId, n: n });
  const el = document.getElementById('race-result');
  if (r.ok) {
    el.innerHTML = `
      <div>Solicitudes: ${r.data.total_requests}</div>
      <div class="winner">Ganadores: ${r.data.winners}</div>
      <div class="rejected">Rechazadas: ${r.data.rejected}</div>
      <div class="oversell">Overselling: ${r.data.overselling}</div>
      ${r.data.winner_hold ? `<div>Hold: ${r.data.winner_hold}</div>` : ''}
    `;
    toast(`Carrera: ${r.data.winners} ganador, ${r.data.rejected} rechazadas, 0 overselling`);
    await loadSeats();
  } else {
    toast(`Error: ${r.data.error}`, true);
  }
}

async function loadAudit(holdId) {
  if (!holdId) return;
  const r = await api('/api/audit/' + holdId);
  const el = document.getElementById('audit-log');
  if (r.ok && r.data.history.length > 0) {
    el.innerHTML = r.data.history.map(h => `
      <div class="audit-entry">
        ${h.seat_id || '*'} <span class="arrow">${h.from_state || '?'} -> ${h.to_state || '?'}</span>
        <span class="reason">${h.reason}</span>
      </div>
    `).join('');
  } else {
    el.innerHTML = '<p class="placeholder">Sin eventos.</p>';
  }
}

function showRecurrence(rec) {
  const el = document.getElementById('recurrence-info');
  el.innerHTML = `
    <div class="field"><span class="label">Recurrence ID</span><span class="value">${rec.recurrence_id}</span></div>
    <div class="field"><span class="label">Cuotas</span><span class="value">${rec.installments_paid}/${rec.installments_total}</span></div>
    <div class="field"><span class="label">Monto/cuota</span><span class="value">${rec.amount_per_installment} ${rec.currency}</span></div>
    <div class="field"><span class="label">Estado</span><span class="value">${rec.status}</span></div>
    <button id="btn-charge" class="btn-secondary">Simular siguiente cuota</button>
  `;
  document.getElementById('btn-charge').onclick = btnCharge;
}

async function btnCharge() {
  if (!currentHoldId) return;
  const r = await apiPost('/api/recurrences/' + currentHoldId + '/charge', { scenario: 'APPROVED' });
  if (r.ok) {
    toast(`Cuota cobrada: ${r.data.installments_paid}/${r.data.installments_total}`);
    showRecurrence(r.data);
    await loadAudit(currentHoldId);
  } else {
    toast(`Error: ${r.data.error}`, true);
  }
}

async function loadRecurrence() {
  if (!currentHoldId) return;
  const r = await api('/api/recurrences/' + currentHoldId);
  if (r.ok) {
    showRecurrence(r.data);
  }
}

async function updateQueueStats() {
  const r = await api('/api/queue/stats');
  if (r.ok) {
    document.getElementById('badge-queue').textContent = `Cola: ${r.data.active}/${r.data.max_concurrent}`;
  }
}

async function updateCB() {
  const r = await api('/api/circuit-breaker');
  if (r.ok) {
    const badge = document.getElementById('badge-cb');
    badge.textContent = `CB: ${r.data.state}`;
    badge.className = 'badge cb-' + r.data.state.toLowerCase().replace('_', '-');
  }
}

async function btnApplyConfig() {
  const ttl = parseInt(document.getElementById('ttl-input').value);
  const r = await apiPost('/api/config', { HOLD_TTL_SECONDS: ttl });
  if (r.ok) {
    document.getElementById('badge-ttl').textContent = `TTL: ${ttl}s`;
    toast(`TTL actualizado a ${ttl}s`);
  }
}

async function btnResetCB() {
  const r = await apiPost('/api/circuit-breaker/reset', {});
  if (r.ok) {
    toast('Circuit breaker reseteado');
    await updateCB();
  }
}

function init() {
  document.getElementById('btn-reserve').onclick = btnReserve;
  document.getElementById('btn-sim-reserve').onclick = btnSimReserve;
  document.getElementById('btn-pay').onclick = btnPay;
  document.getElementById('btn-release').onclick = btnRelease;
  document.getElementById('btn-race').onclick = btnRace;
  document.getElementById('btn-apply-config').onclick = btnApplyConfig;
  document.getElementById('section-filter').onchange = loadSeats;

  loadSeats();
  updateQueueStats();
  updateCB();

  refreshTimer = setInterval(() => {
    loadSeats();
    updateQueueStats();
    updateCB();
    refreshHold();
    if (currentHoldId) loadRecurrence();
  }, 2000);
}

init();
