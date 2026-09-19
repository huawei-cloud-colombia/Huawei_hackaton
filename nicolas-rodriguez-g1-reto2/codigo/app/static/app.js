// FlowMatch Assignment Engine - interfaz de verificacion (Fase 4)
// Vanilla JS sin dependencias: todo el mundo puede correrlo con solo abrir /.

let orderCounter = 1;

async function postJSON(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await resp.json();
  return { ok: resp.ok, status: resp.status, data };
}

async function getJSON(url) {
  const resp = await fetch(url);
  return resp.json();
}

function statusBadgeClass(status) {
  return `result-${status}`;
}

function renderResult(result) {
  const card = document.getElementById("result-card");
  card.className = `result-card ${statusBadgeClass(result.status)}`;

  const costLine = result.cost != null
    ? `Costo: <strong>$${Number(result.cost).toLocaleString("es-CO")}</strong> COP` +
      (result.pricing_status ? ` · pricing_status: <code>${result.pricing_status}</code>` : "")
    : "";

  const reasonsHtml = (result.reasons || [])
    .map((r) => `<li><code>${r.rule}</code> — ${r.detail}</li>`)
    .join("");

  card.innerHTML = `
    <div class="result-status">${result.status}</div>
    <div class="result-meta">
      pedido <strong>${result.order_id}</strong>
      ${result.assigned_courier ? ` → repartidor <strong>${result.assigned_courier}</strong>` : ""}
    </div>
    <div class="result-meta">${costLine}</div>
    <ul class="reasons-list">${reasonsHtml}</ul>
  `;
}

function loadBarClass(active, max) {
  const ratio = max > 0 ? active / max : 0;
  if (ratio >= 1) return "full";
  if (ratio >= 0.66) return "mid";
  return "";
}

async function refreshCouriers() {
  const [state, couriers] = await Promise.all([getJSON("/state"), getJSON("/couriers")]);
  const body = document.getElementById("couriers-body");
  body.innerHTML = couriers
    .map((c) => {
      const cls = loadBarClass(c.active_orders, c.max_capacity);
      const pct = c.max_capacity > 0 ? Math.min(100, (c.active_orders / c.max_capacity) * 100) : 0;
      return `<tr>
        <td>${c.courier_id}</td>
        <td>${c.zone}</td>
        <td>
          <span class="load-bar"><span class="load-bar-fill ${cls}" style="width:${pct}%"></span></span>
          ${c.active_orders}/${c.max_capacity}
        </td>
      </tr>`;
    })
    .join("");

  const banner = document.getElementById("surge-banner");
  if (state.surge && state.surge.active) {
    banner.classList.remove("hidden");
    banner.textContent = `⚠ Modo de contención activo — quedan ~${state.surge.remaining_seconds}s (pedidos normal se rechazan de inmediato; express siguen en cola). Cola de espera: ${state.queue_length}.`;
  } else {
    banner.classList.add("hidden");
  }
}

async function refreshRejectionReports() {
  const reports = await getJSON("/reports/rejections?limit=8");
  const container = document.getElementById("rejection-reports");
  if (!reports.length) {
    container.innerHTML = `<p class="muted">Aún no hay pedidos rechazados en esta sesión.</p>`;
    return;
  }
  container.innerHTML = reports
    .map(
      (r) => `<div class="report-card">
        <span class="order-id">${r.order_id}</span> · ${r.generated_at}
        <div class="explanation">${r.customer_explanation}</div>
      </div>`
    )
    .join("");
}

document.getElementById("order-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const orderIdField = document.getElementById("order_id");
  const orderId = orderIdField.value.trim() || `ord_ui_${orderCounter++}`;

  const order = {
    order_id: orderId,
    timestamp: new Date().toISOString(),
    pickup_zone: document.getElementById("pickup_zone").value.trim(),
    distance_km: parseFloat(document.getElementById("distance_km").value),
    priority: document.getElementById("priority").value,
  };

  const { data } = await postJSON("/assign", order);
  renderResult(data);
  await refreshCouriers();
  await refreshRejectionReports();
});

document.getElementById("burst-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const payload = {
    pickup_zone: document.getElementById("burst_zone").value.trim(),
    count: parseInt(document.getElementById("burst_count").value, 10),
    priority: document.getElementById("burst_priority").value,
    order_id_prefix: `rafaga_${Date.now()}`,
  };
  const { data } = await postJSON("/simulate-burst", payload);

  const container = document.getElementById("burst-results");
  container.innerHTML = data
    .map(
      (r) => `<div class="burst-item status-${r.status}">
        <span>${r.order_id}</span>
        <span>${r.status}${r.assigned_courier ? " → " + r.assigned_courier : ""}</span>
      </div>`
    )
    .join("");

  if (data.length) renderResult(data[data.length - 1]);
  await refreshCouriers();
  await refreshRejectionReports();
});

document.getElementById("refresh-couriers").addEventListener("click", refreshCouriers);

document.getElementById("reset-couriers").addEventListener("click", async () => {
  const couriers = await getJSON("/couriers");
  // Vuelve a poner active_orders en 0 conservando zona/capacidad configuradas.
  const reset = couriers.map((c) => ({ ...c, active_orders: 0 }));
  await fetch("/couriers/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(reset),
  });
  document.getElementById("burst-results").innerHTML = "";
  await refreshCouriers();
});

refreshCouriers();
refreshRejectionReports();
setInterval(refreshCouriers, 8000);
