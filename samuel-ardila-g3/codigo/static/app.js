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

let simRunning = false;
let simTimer = null;
let simCounters = { holds: 0, rejected: 0, sold: 0, released: 0 };
let simUserCounter = 0;

function logConsole(level, msg) {
  const el = document.getElementById('console-log');
  const now = new Date().toLocaleTimeString('es', { hour12: false }) + '.' + String(Date.now() % 1000).padStart(3, '0');
  const line = document.createElement('div');
  line.className = 'log-line';
  line.innerHTML = `<span class="log-time">[${now}]</span> <span class="log-${level}">${msg}</span>`;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
  while (el.children.length > 500) el.removeChild(el.firstChild);
}

function updateSimStats() {
  document.getElementById('sim-stat-holds').textContent = `Holds: ${simCounters.holds}`;
  document.getElementById('sim-stat-rejected').textContent = `Rechazados: ${simCounters.rejected}`;
  document.getElementById('sim-stat-sold').textContent = `Vendidos: ${simCounters.sold}`;
  document.getElementById('sim-stat-released').textContent = `Liberados: ${simCounters.released}`;
}

async function simUser() {
  const userId = `usr_sim_${simUserCounter++}`;
  logConsole('user', `${userId} >> buscando asiento disponible...`);

  try {
    const seatsRes = await api('/api/seats');
    const avail = seatsRes.data.seats.filter(s => s.status === 'AVAILABLE');
    if (avail.length === 0) {
      logConsole('warn', `${userId} >> no hay asientos disponibles`);
      return;
    }
    const seat = avail[Math.floor(Math.random() * avail.length)];
    logConsole('debug', `${userId} >> intenta reservar ${seat.seat_id}`);

    const idemKey = `sim-${userId}-${Date.now()}`;
    const holdRes = await apiPost('/api/holds', {
      user_id: userId,
      event_id: 'aurora-bogota-2026',
      seat_ids: [seat.seat_id],
    }, { 'Idempotency-Key': idemKey });

    if (!holdRes.ok) {
      simCounters.rejected++;
      updateSimStats();
      logConsole('error', `${userId} >> RECHAZADO ${seat.seat_id} (${holdRes.data.error})`);
      return;
    }

    simCounters.holds++;
    updateSimStats();
    logConsole('success', `${userId} >> HOLD ${holdRes.data.hold_id} | ${seat.seat_id} | ${holdRes.data.total} COP`);

    const releaseAfter = parseInt(document.getElementById('sim-release').value) * 1000;
    const payPct = parseInt(document.getElementById('sim-pay-pct').value);
    const willPay = Math.random() * 100 < payPct;

    setTimeout(async () => {
      if (!simRunning) return;
      if (willPay) {
        const payRes = await apiPost('/api/holds/' + holdRes.data.hold_id + '/confirm', {
          payment_token: 'tok_sim_' + userId,
          scenario: 'APPROVED',
        });
        if (payRes.ok && payRes.data.result === 'APPROVED') {
          simCounters.sold++;
          updateSimStats();
          logConsole('success', `${userId} >> PAGADO ${seat.seat_id} -> SOLD`);
        } else {
          logConsole('error', `${userId} >> pago fallo: ${payRes.data?.error || 'unknown'}`);
        }
      } else {
        const relRes = await api('/api/holds/' + holdRes.data.hold_id, { method: 'DELETE' });
        if (relRes.ok) {
          simCounters.released++;
          updateSimStats();
          logConsole('info', `${userId} >> LIBERADO ${seat.seat_id} -> AVAILABLE`);
        }
      }
    }, releaseAfter);
  } catch (e) {
    logConsole('error', `${userId} >> excepcion: ${e.message}`);
  }
}

function startSim() {
  simRunning = true;
  simCounters = { holds: 0, rejected: 0, sold: 0, released: 0 };
  simUserCounter = 0;
  updateSimStats();
  const usersPerSec = parseInt(document.getElementById('sim-users').value);
  logConsole('info', `=== SIMULACION INICIADA | ${usersPerSec} usuarios/seg ===`);
  document.getElementById('btn-sim-start').disabled = true;
  document.getElementById('btn-sim-stop').disabled = false;

  simTimer = setInterval(() => {
    if (!simRunning) return;
    for (let i = 0; i < usersPerSec; i++) {
      simUser();
    }
  }, 1000);
}

function stopSim() {
  simRunning = false;
  if (simTimer) clearInterval(simTimer);
  logConsole('warn', `=== SIMULACION DETENIDA ===`);
  document.getElementById('btn-sim-start').disabled = false;
  document.getElementById('btn-sim-stop').disabled = true;
}

function clearConsole() {
  document.getElementById('console-log').innerHTML = '';
}

function init() {
  document.getElementById('btn-reserve').onclick = btnReserve;
  document.getElementById('btn-sim-reserve').onclick = btnSimReserve;
  document.getElementById('btn-pay').onclick = btnPay;
  document.getElementById('btn-release').onclick = btnRelease;
  document.getElementById('btn-race').onclick = btnRace;
  document.getElementById('btn-apply-config').onclick = btnApplyConfig;
  document.getElementById('section-filter').onchange = loadSeats;
  document.getElementById('btn-sim-start').onclick = startSim;
  document.getElementById('btn-sim-stop').onclick = stopSim;
  document.getElementById('btn-sim-clear').onclick = clearConsole;

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
