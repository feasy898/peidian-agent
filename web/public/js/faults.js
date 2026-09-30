'use strict';
/* web/public/js/faults.js · 故障注入面板 / agent 处置时间线 / 人工定位判分（人机对比） */
const FAULTS = (() => {
  const state = {
    parkId: null, event: null, mode: 'agent',
    picks: new Set(), startedAt: null, timer: null, pickablesBound: false,
  };
  const $ = s => document.querySelector(s);
  let hooks = {}; // { onFaultTargetsChanged(ids), getPickable(), clearPicks() } 由 app 注入

  const PRESETS = [
    '2 号变压器重瓦斯跳闸', '10kV 母线短路，电压骤降', '1 号线路覆冰断线',
    '光伏逆变器全部停运', '储能变流器过温告警', '充电桩群长时间过载',
  ];

  function init(parkId, h) {
    state.parkId = parkId; hooks = h || {};
    state.event = null; state.picks.clear();
    $('#fault-result').innerHTML = '';
    $('#timeline').innerHTML = '<div class="empty">注入一次故障，观察 agent 的定位与处置步骤</div>';
    $('#human-result').innerHTML = '';
    $('#fault-badge').style.display = 'none';
    // 预设
    const pre = $('#fault-presets'); pre.innerHTML = '';
    for (const p of PRESETS) {
      const b = document.createElement('button');
      b.className = 'preset'; b.textContent = p;
      b.onclick = () => { $('#fault-input').value = p; inject(); };
      pre.appendChild(b);
    }
  }

  function setMode(m) { state.mode = m; }

  async function inject() {
    const text = $('#fault-input').value.trim();
    if (!text) { $('#fault-input').focus(); return; }
    const btn = $('#btn-inject'); btn.disabled = true;
    try {
      const ev = await API.fault(state.parkId, text);
      state.event = ev; state.picks.clear(); state.startedAt = Date.now();
      $('#fault-badge').style.display = '';
      $('#fault-badge-text').textContent = `故障 ${ev.severity} · ${ev.type} · ${ev.targets.join(',') || '未定位'}`;
      $('#agent-source-badge').textContent = ev.source || 'mock';
      $('#human-result').innerHTML = '';
      if (hooks.onFaultTargetsChanged) hooks.onFaultTargetsChanged(ev.targets || []);
      if (state.mode === 'agent') renderTimeline(ev);
      else { $('#timeline').innerHTML = '<div class="empty">人工模式：时间线已隐藏</div>'; refreshHumanPanel(); }
    } catch (e) { alert('注入失败：' + e.message); }
    btn.disabled = false;
  }

  /* ---- Agent 模式：步骤逐步点亮，总耗时 = ev.agent.total_ms ---- */
  function renderTimeline(ev) {
    const steps = (ev.agent && ev.agent.steps) || [];
    const total = (ev.agent && ev.agent.total_ms) || steps.length * 900;
    const tl = $('#timeline');
    tl.innerHTML = steps.map(s => `
      <div class="tl-step pending" data-idx="${s.idx}">
        <div class="tl-dot">✓</div>
        <div class="tl-body">
          <div class="t">${s.idx}. ${esc(s.title)} <span class="tl-meta" data-meta></span></div>
          <div class="d">${esc(s.detail)}</div>
          ${s.refs && s.refs.length ? `<div class="refs">${s.refs.map(esc).join(' · ')}</div>` : ''}
        </div>
      </div>`).join('');
    clearInterval(state.timer);
    const t0 = performance.now();
    state.timer = setInterval(() => {
      const el = performance.now() - t0;
      let allDone = true;
      for (const row of tl.querySelectorAll('.tl-step')) {
        const i = parseInt(row.dataset.idx, 10);
        const endAt = (total * i) / steps.length;
        if (el >= endAt) {
          if (!row.classList.contains('done')) {
            row.classList.remove('pending', 'running'); row.classList.add('done');
            row.querySelector('[data-meta]').textContent = `${Math.round(endAt)}ms`;
          }
        } else if (el >= endAt - total / steps.length) {
          if (!row.classList.contains('running') && !row.classList.contains('done')) { row.classList.remove('pending'); row.classList.add('running'); }
          allDone = false;
        } else allDone = false;
      }
      if (el >= total) {
        clearInterval(state.timer);
        $('#fault-result').innerHTML = `
          <div class="card result-card"><div class="card-body">
            <div class="kicker">处置完成</div>
            <div style="margin-top:6px;display:flex;gap:14px;align-items:baseline">
              <span class="verdict ok">闭环</span>
              <span class="muted" style="font-size:12.5px">端到端 <b class="num" style="color:hsl(var(--foreground))">${total} ms</b>（演示计时） · 目标 <b class="num">${esc((ev.targets || []).join(', ')) || '—'}</b></span>
            </div>
          </div></div>`;
      }
    }, 160);
  }

  /* ---- 人工模式 ---- */
  function refreshHumanPanel() {
    $('#human-panel').style.display = '';
    $('#agent-panel').style.display = 'none';
    $('#human-pick-count').textContent = state.picks.size;
    $('#btn-human-submit').disabled = state.picks.size === 0;
  }
  function onNodePick(id) {
    if (state.mode !== 'human' || !state.event) return;
    if (state.picks.has(id)) state.picks.delete(id); else state.picks.add(id);
    if (hooks.onPicksChanged) hooks.onPicksChanged([...state.picks]);
    refreshHumanPanel();
  }
  async function submitAttempt() {
    if (!state.event) return;
    try {
      const r = await API.attempt(state.parkId, [...state.picks], state.startedAt);
      const ok = r.verdict === 'CORRECT';
      $('#human-result').innerHTML = `
        <div class="card result-card ${ok ? '' : 'wrong'}"><div class="card-body">
          <div class="kicker">人工定位判分</div>
          <div class="verdict ${ok ? 'ok' : 'bad'}" style="margin:4px 0">${r.verdict}${r.verdict === 'PARTIAL' ? '（部分命中）' : ''}</div>
          <div class="muted" style="font-size:12.5px">
            命中 <b class="num">${r.hits}/${r.truth.length}</b> · 精确率 <b class="num">${(r.precision * 100).toFixed(0)}%</b> ·
            召回 <b class="num">${(r.recall * 100).toFixed(0)}%</b> ·
            用时 <b class="num">${r.elapsed_ms != null ? (r.elapsed_ms / 1000).toFixed(1) + 's' : '—'}</b><br>
            真值 <span class="num" style="color:hsl(var(--success))">${r.truth.join(', ') || '—'}</span>
          </div>
        </div></div>`;
    } catch (e) { $('#human-result').innerHTML = `<div class="hint">判分失败：${esc(e.message)}</div>`; }
  }
  function resetPicks() { state.picks.clear(); if (hooks.onPicksChanged) hooks.onPicksChanged([]); refreshHumanPanel(); $('#human-result').innerHTML = ''; }

  function applyMode() {
    $('#human-panel').style.display = state.mode === 'human' ? '' : 'none';
    $('#agent-panel').style.display = state.mode === 'human' ? 'none' : '';
    $('#mode-label').textContent = state.mode === 'human' ? '人工定位' : 'Agent 自动';
    if (state.mode === 'human' && state.event) refreshHumanPanel();
    if (state.mode === 'agent' && state.event) renderTimeline(state.event);
  }

  async function clearFault() {
    try { await API.clear(state.parkId); } catch (_) { /* noop */ }
    state.event = null;
    $('#fault-badge').style.display = 'none';
    $('#fault-result').innerHTML = '';
    if (hooks.onFaultTargetsChanged) hooks.onFaultTargetsChanged([]);
  }

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

  document.addEventListener('DOMContentLoaded', () => {
    $('#btn-inject').addEventListener('click', inject);
    $('#fault-input').addEventListener('keydown', e => { if (e.key === 'Enter') inject(); });
    $('#btn-clear-fault').addEventListener('click', clearFault);
    $('#btn-human-submit').addEventListener('click', submitAttempt);
    $('#btn-human-reset').addEventListener('click', resetPicks);
  });

  return { init, setMode, applyMode, onNodePick, get event() { return state.event; }, get picks() { return state.picks; } };
})();
