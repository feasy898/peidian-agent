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
    'TX-B01 短路', 'TX-A01 过载', 'LN-01 断线', 'PV-01 光伏脱网',
    '2 号变压器重瓦斯跳闸',       // 引擎侧规则解析不识别；LLM 凭据到位后可用，mock 回退亦可
    '10kV 母线电压骤降',
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
      else {
        $('#timeline').innerHTML = '<div class="empty">人工模式：时间线已隐藏</div>';
        $('#fault-result').innerHTML = opsBlock(ev);
        refreshHumanPanel();
      }
    } catch (e) {
      if (e.status === 422 && e.body && Array.isArray(e.body.reasons)) {
        // 故障 DSL 白名单拒绝（零信任，不静默兜底）：如实展示理由
        $('#fault-result').innerHTML = `<div class="card result-card wrong"><div class="card-body">
          <div class="kicker">注入被拒绝（FaultDSL 白名单）</div>
          <div style="margin-top:6px;font-size:12.8px">${e.body.reasons.map(esc).join('<br>')}</div>
          ${e.body.llm && e.body.llm.used === false ? `<div class="muted" style="font-size:11.5px;margin-top:6px">LLM 通道：未启用（${esc(e.body.llm.reason || '')}）——当前为规则解析离线兜底，可用预设：元件ID + 短路/过载/断线/光伏脱网</div>` : ''}
        </div></div>`;
      } else {
        alert('注入失败：' + e.message);
      }
    }
    btn.disabled = false;
  }

  /* ---- v0.2 扩展字段渲染：looked_at/found/why（agent.step）+ actions/events 投影 ---- */
  function stepExt(s) {
    if (!s.phase && !s.looked_at && !s.why) return '';
    const looked = (s.looked_at || []).map(esc).join(' ');
    const found = s.found && typeof s.found === 'object'
      ? Object.entries(s.found).slice(0, 4)
          .map(([k, v]) => `${esc(k)}=${esc(typeof v === 'object' ? JSON.stringify(v) : String(v))}`).join(' ')
      : '';
    return `<div class="d" style="margin-top:3px">
      ${s.phase ? `<span class="badge">${esc(s.phase)}</span>` : ''}
      看：<span class="num" style="color:hsl(var(--accent))">${looked || '—'}</span>
      ${found ? `｜判：<span class="num">${found}</span>` : ''}
      ${s.why ? `｜据：${esc(s.why)}` : ''}
    </div>${s.conclusion ? `<div class="refs">${esc(s.conclusion)}</div>` : ''}`;
  }
  function opsBlock(ev) {
    const acts = (ev.actions || []).map(a => {
      const human = a.by === 'human';
      const bad = a.result && a.result !== 'ok';
      return `<span class="badge" style="color:${bad ? 'hsl(var(--destructive))' : human ? 'hsl(var(--accent))' : 'hsl(var(--success))'}">
        ${human ? '👤' : '🤖'} ${esc(a.op)} ${esc(a.target)} → ${esc(a.result || '?')}</span>`;
    }).join(' ');
    const marks = (ev.events || []).map(e => {
      if (e.type === 'control.passed') return `<div class="hint">⏸ 已交人工（agent 反应已关闭，界面交给人定位）</div>`;
      if (e.type === 'anomaly.cleared') return `<span class="badge tier-simple">✓ 异常清除 by=${esc(e.by || '?')}</span>`;
      if (e.type === 'fault.detected') return `<span class="badge fault-on">检测 ${esc(e.severity || '')} @ ${esc(e.target || '')}</span>`;
      if (e.type === 'control.escalated') return `<span class="badge tier-complex">⚠ 复测未消除，升级</span>`;
      return '';
    }).filter(Boolean).join(' ');
    if (!acts && !marks) return '';
    return `<div class="card"><div class="card-head"><span class="card-title">操作面与事件标记</span></div>
      <div class="card-body" style="display:flex;flex-direction:column;gap:7px;font-size:12.5px">
        ${marks ? `<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">${marks}</div>` : ''}
        ${acts ? `<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center"><span class="kicker">操作</span>${acts}</div>` : ''}
      </div></div>`;
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
          <div class="d">${esc(s.detail || '')}</div>
          ${stepExt(s)}
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
          </div></div>` + opsBlock(ev);
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
