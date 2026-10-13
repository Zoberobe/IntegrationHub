const model = { stage: 0, replayed: false };

const byId = (id) => document.getElementById(id);

function setStep(id, status) {
  byId(id).className = `timeline-step ${status}`;
}

function render() {
  const { stage, replayed } = model;
  const state = ["awaiting_payment", "shipping_retrying", "shipped"][stage];
  const badge = byId("state-badge");
  badge.textContent = state;
  badge.className = `state-badge ${["neutral", "warning", "success"][stage]}`;

  byId("attempt-count").textContent = String(stage === 0 ? 0 : stage === 1 ? 1 : 2);
  byId("shipment-count").textContent = String(stage === 2 ? 1 : 0);
  byId("event-count").textContent = String(stage === 0 ? 0 : 1);
  byId("next-action").textContent = ["Start payment", "Wait for shipping retry", "Complete"][stage];
  byId("status-message").textContent = stage === 0
    ? "The order exists. No external operation has started."
    : stage === 1
      ? "The first shipping attempt failed with simulated_503. The persisted job is due for a retry."
      : replayed
        ? "The repeated webhook was acknowledged as duplicate. The shipment count remains one."
        : "The second attempt succeeded. One shipment exists and the order is complete.";

  setStep("step-payment", stage > 0 ? "complete" : "waiting");
  setStep("step-webhook", stage > 0 ? "complete" : "waiting");
  setStep("step-failure", stage > 0 ? "failed" : "waiting");
  setStep("step-recovery", stage === 2 ? "complete" : "waiting");
  byId("payment-detail").textContent = stage > 0 ? "Test payment confirmed" : "Awaiting request";
  byId("webhook-detail").textContent = stage > 0 ? (replayed ? "Duplicate acknowledged; one event stored" : "Signature accepted; one event stored") : "Not received";
  byId("failure-detail").textContent = stage > 0 ? "Attempt 1 · simulated_503" : "Not started";
  byId("recovery-detail").textContent = stage === 2 ? "Attempt 2 · shipment created" : "Awaiting retry";

  byId("start-button").disabled = stage !== 0;
  byId("retry-button").disabled = stage !== 1;
  byId("replay-button").disabled = stage !== 2 || replayed;

  const list = byId("attempt-list");
  list.replaceChildren();
  const entries = stage === 0 ? [] : stage === 1
    ? [["01", "temporary_failure", "simulated_503"]]
    : [["01", "temporary_failure", "simulated_503"], ["02", "succeeded", "shipment created"]];
  if (!entries.length) {
    const empty = document.createElement("li");
    empty.className = "empty-log";
    empty.textContent = "No attempts yet.";
    list.append(empty);
  }
  for (const [number, outcome, detail] of entries) {
    const item = document.createElement("li");
    item.innerHTML = `<span>Attempt ${number}</span><strong class="${outcome}">${outcome}</strong><small>${detail}</small>`;
    list.append(item);
  }
}

byId("start-button").addEventListener("click", () => { model.stage = 1; render(); });
byId("retry-button").addEventListener("click", () => { model.stage = 2; render(); });
byId("replay-button").addEventListener("click", () => { model.replayed = true; render(); });
byId("reset-button").addEventListener("click", () => { model.stage = 0; model.replayed = false; render(); });
render();
