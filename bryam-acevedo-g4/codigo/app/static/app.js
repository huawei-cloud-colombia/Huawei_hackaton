const form = document.getElementById("txn-form");
const resultEmpty = document.getElementById("result-empty");
const resultCard = document.getElementById("result-card");
const decisionBadge = document.getElementById("decision-badge");
const scoreValue = document.getElementById("score-value");
const bankStatus = document.getElementById("bank-status");
const reasonsList = document.getElementById("reasons-list");

const burstEmpty = document.getElementById("burst-empty");
const burstTable = document.getElementById("burst-table");
const burstBody = burstTable.querySelector("tbody");

function readForm() {
  const data = Object.fromEntries(new FormData(form).entries());
  data.amount = parseFloat(data.amount);
  return data;
}

function renderResult(result) {
  resultEmpty.classList.add("hidden");
  resultCard.classList.remove("hidden");
  decisionBadge.textContent = result.decision;
  decisionBadge.className = `badge ${result.decision}`;
  scoreValue.textContent = result.score;
  bankStatus.textContent = result.bank_auth_status;
  reasonsList.innerHTML = "";
  if (result.reasons.length === 0) {
    const li = document.createElement("li");
    li.textContent = "Sin señales de riesgo activadas.";
    reasonsList.appendChild(li);
  } else {
    for (const r of result.reasons) {
      const li = document.createElement("li");
      li.textContent = `${r.rule} (+${r.weight} pts): ${r.detail}`;
      reasonsList.appendChild(li);
    }
  }
}

async function evaluateTransaction(payload) {
  const res = await fetch("/evaluate/auto", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = readForm();
  const result = await evaluateTransaction(payload);
  renderResult(result);
});

document.getElementById("reset-btn").addEventListener("click", async () => {
  await fetch("/reset", { method: "POST" });
  resultCard.classList.add("hidden");
  resultEmpty.classList.remove("hidden");
  burstTable.classList.add("hidden");
  burstEmpty.classList.remove("hidden");
  burstBody.innerHTML = "";
});

document.getElementById("burst-btn").addEventListener("click", async () => {
  const base = readForm();
  burstEmpty.classList.add("hidden");
  burstTable.classList.remove("hidden");
  burstBody.innerHTML = "";

  for (let i = 1; i <= 6; i++) {
    const payload = { ...base, amount: 5000 + i * 1000 };
    const result = await evaluateTransaction(payload);
    const row = document.createElement("tr");
    row.className = result.decision;
    const mainReason = result.reasons[0] ? result.reasons[0].rule : "-";
    row.innerHTML = `<td>${i}</td><td>${result.score}</td><td class="decision-cell">${result.decision}</td><td>${mainReason}</td>`;
    burstBody.appendChild(row);
    renderResult(result);
    await new Promise((r) => setTimeout(r, 150));
  }
});
