/* peidian-agent · 练习场人类体验 UI 逻辑（零依赖，SSE 消费 EventBus） */
"use strict";

const state = {
  runId: null,
  since: 0,
  events: [],
  filter: "all",
  faults: [],
  anomalies: new Map(),   // anomaly_id -> card data
  es: null,
};

const $ = (id) => document.getElementById(id);
const fmtSim = (s) => {
  s = Math.max(0, Math.round(s || 0));
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600),
        m = Math.floor((s % 3600) / 60), ss = s % 60;
  return (d ? d + "d " : "") + String(h).padStart(2, "0") + ":" +
         String(m).padStart(2, "0") + ":" + String(ss).padStart(2, "0");
};

async function api(path, opts) {
  const r = await fetch(path, opts ? {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opts),
  } : undefined);
  return r.json();
}

/* ---------------- 初始化：场景/园区/故障库 ---------------- */
async function initLists() {
  const [sc, pk] = await Promise.all([api("/api/scenarios"), api("/api/parks")]);
  const ss = $("scenarioSel");
  ss.innerHTML = sc.scenarios.map((s) =>
    `<option value="${s.id}">${s.id} · ${s.park}（${fmtSim(s.duration_sim_s)}）</option>`).join("");
  const ps = $("parkSel");
  ps.innerHTML = pk.parks.map((p) =>
    `<option value="${p.id}">${p.id} · ${p.park}（${p.tier}）</option>`).join("");
}

/* ---------------- 启动 run ---------------- */
async function startRun() {
  if (state.runId && state.es) state.es.close();
  const scenario = $("scenarioSel").value || $("parkSel").value;
  const body = {
    scenario,
    seed: Number($("seedInput").value || 42),
    agent_enabled: $("agentOn").checked,
  };
  const r = await api("/api/runs", body);
  if (r.error) { alert(r.error + (r.reasons ? "\n" + r.reasons.join("\n") : "")); return; }
  state.runId = r.run_id;
  state.since = 0; state.events = []; state.anomalies.clear();
  $("timeline").innerHTML = "";
  $("agentToggle").checked = r.agent_enabled;
  $("agentToggleLabel").textContent = r.agent_enabled ? "agent 在线" : "人工接管";
  $("chipRun").textContent = r.run_id;
  $("chipRun").className = "chip live " + (r.agent_enabled ? "" : "human");
  renderFaultButtons(r.faults || []);
  connectSSE(r.run_id);
  $("startBtn").disabled = true;
  setTimeout(() => $("startBtn").disabled = false, 1500);
}

/* ---------------- SSE ---------------- */
function connectSSE(runId) {
  const es = new EventSource(`/api/runs/${runId}/stream`);
  state.es = es;
  es.onmessage = (m) => {
    try {
      const evt = JSON.parse(m.data);
      ingest(evt);
    } catch (_) { /* ignore */ }
  };
  es.onerror = () => { /* 断线由轮询兜底 */ };
}

/* ---------------- 事件摄入 ---------------- */
function ingest(evt) {
  state.since = Math.max(state.since, evt.seq || 0);
  state.events.push(evt);
  const p = evt.payload || {};
  if (evt.type === "fault.detected") bump("stDetected");
  if (evt.type === "anomaly.cleared") { bump("stCleared"); state.anomalies.delete(p.anomaly_id); }
  if (evt.type === "control.escalated") bump("stEscalated");
  if (evt.type === "control.passed") addAnomaly(p, "P2");
  if (evt.channel === "agent") bump("stAgentSteps");
  if (evt.channel === "ops") bump("stActions");
  if (evt.channel === "control" && evt.type === "control.human_action") bump("stActions");
  if (String(evt.type || "").startsWith("ops.") && p.source === "arena.calendar") bump("stBusiness");
  if (evt.type === "fault.detected") addAnomaly(p, p.severity || "P2");
  if (evt.type === "fault.planned") updateTargetHints();
  if (evt.type === "run.failed") alert("run 失败: " + (p.error || ""));
  $("chipSim").textContent = "sim_s " + fmtSim(evt.sim_s);
  appendTimeline(evt);
  renderAnomalies();
  if (evt.type === "anomaly.cleared" || evt.type === "control.human_action") refreshEval();
}

function bump(id) { $(id).textContent = String(Number($(id).textContent) + 1); }

function addAnomaly(p, sev) {
  if (!p || !p.anomaly_id) return;
  state.anomalies.set(p.anomaly_id, {
    id: p.anomaly_id, hint: p.hint || "?", target: p.target || "?",
    severity: p.severity || sev || "P2", basis: (p.evidence || {}).basis || "",
  });
}

/* ---------------- 时间线渲染 ---------------- */
function appendTimeline(evt) {
  if (state.filter !== "all" && evt.channel !== state.filter) return;
  const li = document.createElement("li");
  li.className = "ch-" + evt.channel;
  const p = evt.payload || {};
  const detail = p.title || p.note || p.basis || p.type || evt.type;
  const who = p.by ? ` [${p.by}]` : "";
  li.innerHTML = `<span class="t">${fmtSim(evt.sim_s)}</span>` +
    `<span class="c ch-${evt.channel}">${evt.channel}</span>` +
    `<span class="d"><b>${evt.type}</b>${who} · ${escapeHtml(String(detail).slice(0, 220))}</span>`;
  const ol = $("timeline");
  ol.prepend(li);
  while (ol.children.length > 400) ol.removeChild(ol.lastChild);
}
function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ---------------- 异常卡 ---------------- */
function renderAnomalies() {
  const box = $("anomalyCards");
  if (!state.anomalies.size) {
    box.innerHTML = '<p class="hint">暂无活动异常。</p>';
    return;
  }
  box.innerHTML = "";
  for (const a of state.anomalies.values()) {
    const div = document.createElement("div");
    div.className = "anom " + a.severity;
    div.innerHTML = `<h3>${a.id} · ${a.hint}@${a.target}</h3>` +
      `<div class="ev">[${a.severity}] ${escapeHtml(a.basis)}</div>`;
    const b = document.createElement("button");
    b.textContent = "ack 确认并派工";
    b.onclick = () => act("ack", a.id, "人工确认派工");
    div.appendChild(b);
    box.appendChild(div);
  }
}

/* ---------------- 控制动作 ---------------- */
async function act(op, target, reason) {
  if (!state.runId) { alert("先启动 run"); return; }
  await api(`/api/runs/${state.runId}/actions`, { op, target, reason: reason || "" });
}
async function injectFault(faultId) {
  if (!state.runId) { alert("先启动 run"); return; }
  if (!confirm(`确认注入故障 ${faultId}？（危险操作，全程留痕）`)) return;
  await api(`/api/runs/${state.runId}/actions`, { op: "inject", fault_id: faultId });
}
async function toggleAgent() {
  if (!state.runId) { $("agentOn").checked = $("agentToggle").checked; return; }
  await api(`/api/runs/${state.runId}/agent`, { enabled: $("agentToggle").checked });
  $("agentToggleLabel").textContent = $("agentToggle").checked ? "agent 在线" : "人工接管";
  $("chipRun").className = "chip live " + ($("agentToggle").checked ? "" : "human");
}
async function refreshEval() {
  if (!state.runId) return;
  const d = await api(`/api/runs/${state.runId}/eval`);
  if (d && !d.error) {
    $("evalBox").textContent = JSON.stringify({
      detected: d.anomalies.detected, cleared: d.anomalies.cleared,
      escalated: d.anomalies.escalated, active_at_end: d.anomalies.active_at_end,
      actions: d.gateway, latency_detect: d.latency.detect.slice(0, 6),
    }, null, 1);
  }
}

/* ---------------- 故障按钮 ---------------- */
function renderFaultButtons(faultIds) {
  const box = $("faultBtns");
  box.innerHTML = "";
  if (!faultIds.length) {
    box.innerHTML = '<p class="hint">本例无可注入故障。</p>';
    return;
  }
  for (const fid of faultIds) {
    const b = document.createElement("button");
    b.className = "fault-btn";
    b.innerHTML = `<span>⚡ ${fid}</span><span class="k">inject</span>`;
    b.onclick = () => injectFault(fid);
    box.appendChild(b);
  }
}
function updateTargetHints() {
  const dl = $("targetHints");
  const ids = new Set();
  for (const e of state.events) {
    const p = e.payload || {};
    if (p.target) ids.add(p.target);
    if (p.anomaly_id) ids.add(p.anomaly_id);
  }
  dl.innerHTML = [...ids].slice(0, 200).map((x) => `<option value="${x}">`).join("");
}

/* ---------------- 事件绑定 ---------------- */
$("startBtn").onclick = startRun;
$("actBtn").onclick = () => act($("opSel").value, $("opTarget").value.trim(), $("opReason").value.trim());
$("agentToggle").onchange = toggleAgent;
document.querySelectorAll("#chanFilters .f").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll("#chanFilters .f").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    state.filter = b.dataset.ch;
    const ol = $("timeline");
    ol.innerHTML = "";
    for (const e of [...state.events].reverse()) appendTimeline(e);
  };
});

initLists();
