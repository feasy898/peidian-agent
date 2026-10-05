'use strict';
/* web/public/js/app.js · 装配：园区加载、三视角切换、遥测轮询、人机对比模式 */
(() => {
  const $ = s => document.querySelector(s);
  const state = {
    parks: [], parkId: null, park: null,   // park = parkdsl-web/1 JSON
    view: 'overview', localSub: null,
    live: new Map(),   // id -> {p,v,i}
    timer: null, tickMs: 2000, failStreak: 0,
    faultIds: new Set(), picks: new Set(),
  };

  /* ---------- 数据面 ---------- */
  async function loadParkList() {
    const r = await API.parks();
    state.parks = r.parks || [];
    const sel = $('#park-select');
    sel.innerHTML = state.parks.map(p => `<option value="${p.id}">${p.name}（${p.tier}）</option>`).join('');
    if (!state.parkId && state.parks.length) state.parkId = state.parks[0].id;
    sel.value = state.parkId;
    return state.parks;
  }

  async function loadPark(id) {
    state.parkId = id;
    state.park = await API.park(id);
    state.live = new Map();
    state.faultIds = new Set(); state.picks = new Set();
    $('#tier-badge').textContent = state.park.park.tier;
    $('#tier-badge').className = 'badge tier-' + state.park.park.tier;
    $('#intro-name').textContent = state.park.park.name;
    $('#intro-desc').textContent = state.park.park.description || '（无简介）';
    $('#intro-cap').textContent = state.park.park.contract_capacity_kw;
    $('#intro-volt').textContent = state.park.park.incoming_voltage;
    $('#intro-subs').textContent = (state.park.substations || []).length;
    $('#intro-nodes').textContent = (state.park.nodes || []).length;
    $('#intro-seed').textContent = state.park.telemetry.seed;
    $('#step-label').textContent = state.park.telemetry.step_sec + 's';
    // 设备清单（按类型分组计数）
    const byType = new Map();
    for (const n of state.park.nodes || []) byType.set(n.type, (byType.get(n.type) || 0) + 1);
    $('#device-inventory').innerHTML = [...byType.entries()]
      .map(([t, c]) => `<div style="display:flex;justify-content:space-between;padding:2.5px 0">
        <span class="muted">${t}</span><b class="num">× ${c}</b></div>`).join('');
    // 局部视图 chips
    const chips = $('#sub-chips');
    chips.innerHTML = (state.park.substations || []).map(s =>
      `<button class="chip${s.id === state.localSub ? ' active' : ''}" data-sub="${s.id}">${s.name}</button>`).join('');
    chips.querySelectorAll('.chip').forEach(b => b.onclick = () => { state.localSub = b.dataset.sub; renderLocal(); });
    // 曲线
    CURVES.init(state.park);
    // 故障面板重置
    FAULTS.init(id, {
      onFaultTargetsChanged: ids => { state.faultIds = new Set(ids); renderTopo(); },
      onPicksChanged: picks => { state.picks = new Set(picks); renderTopo(); },
    });
    FAULTS.setMode($('#mode-switch').classList.contains('on') ? 'human' : 'agent');
    renderAll();
    // 立即取一帧遥测
    tick().catch(() => { /* net-dot 会显示 */ });
  }

  /* ---------- 遥测轮询 ---------- */
  async function tick() {
    try {
      const snap = await API.telemetry(state.parkId, 1);
      state.failStreak = 0;
      $('#net-dot').classList.remove('off');
      for (const [id, s] of Object.entries(snap.series || {})) {
        state.live.set(id, { p: s.p_kw, v: s.v_v, i: s.i_a });
      }
      // 全园统计
      $('#tot-grid').textContent = fmt(snap.totals.grid_kw);
      $('#tot-load').textContent = fmt(snap.totals.load_kw);
      $('#tot-pv').textContent = fmt(snap.totals.pv_kw);
      $('#tot-bess').textContent = fmt(snap.totals.bess_kw);
      CURVES.pushSnapshot(snap);
      renderTopo();
      renderDevCards();
    } catch (e) {
      state.failStreak += 1;
      if (state.failStreak >= 2) $('#net-dot').classList.add('off');
    }
  }
  function fmt(v) {
    if (v == null || !isFinite(v)) return '—';
    return Math.abs(v) >= 1000 ? (v / 1000).toFixed(2) + 'k' : String(Math.round(v * 10) / 10);
  }

  /* ---------- 渲染 ---------- */
  function renderAll() { renderTopo(); renderLocal(); renderDevCards(); }

  function renderTopo() {
    TOPO.render($('#panorama-svg'), state.park, {
      pickable: currentMode() === 'human' && !!FAULTS.event,
      selected: state.picks,
      faultIds: state.faultIds,
      live: state.live,
      onNodeClick: id => FAULTS.onNodePick(id),
    });
  }

  function renderLocal() {
    TOPO.render($('#local-svg'), state.park, {
      substation: state.localSub,
      pickable: currentMode() === 'human' && !!FAULTS.event,
      selected: state.picks,
      faultIds: state.faultIds,
      live: state.live,
      onNodeClick: id => FAULTS.onNodePick(id),
    });
    // chips active
    document.querySelectorAll('#sub-chips .chip').forEach(b =>
      b.classList.toggle('active', b.dataset.sub === state.localSub));
  }

  function renderDevCards() {
    if (!state.localSub) return;
    const nodes = (state.park.nodes || []).filter(n => n.substation === state.localSub);
    const cards = nodes.map(n => {
      const lv = state.live.get(n.id) || {};
      const p = n.params || {};
      const rows = [];
      if (lv.p != null) rows.push(['有功', fmt(lv.p) + ' kW']);
      if (lv.i != null) rows.push(['电流', fmt(lv.i) + ' A']);
      if (lv.v != null) rows.push(['电压', Math.round(lv.v) + ' V']);
      if (p.capacity_kva) rows.push(['容量', p.capacity_kva + ' kVA']);
      if (p.capacity_kwp) rows.push(['装机', p.capacity_kwp + ' kWp']);
      if (p.capacity_kwh) rows.push(['电芯', p.capacity_kwh + ' kWh' + (p.soc != null ? ` · SOC ${p.soc}%` : '')]);
      if (p.peak_kw) rows.push(['峰值', p.peak_kw + ' kW']);
      if (p.profile) rows.push(['曲线', p.profile]);
      if (p.state) rows.push(['状态', String(p.state)]);
      const hit = state.faultIds.has(n.id);
      return `<div class="card dev-card${hit ? ' result-card wrong' : ''}" style="padding:10px 12px">
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
          <b class="num" style="font-size:12.5px">${n.id}</b>
          <span class="badge">${n.type}</span>
          ${hit ? '<span class="badge fault-on">故障</span>' : ''}
        </div>
        ${rows.map(([k, v]) => `<div class="row"><span class="k">${k}</span><span class="num">${v}</span></div>`).join('')}
      </div>`;
    });
    $('#dev-cards').innerHTML = cards.join('') || '<div class="empty">无元件</div>';
  }

  /* ---------- 视角与模式 ---------- */
  function setView(v) {
    state.view = v;
    for (const sec of document.querySelectorAll('.view')) sec.classList.remove('active');
    $('#view-' + v).classList.add('active');
    document.querySelectorAll('#view-tabs .tab').forEach(t => t.classList.toggle('active', t.dataset.view === v));
    if (v === 'curves') CURVES.draw();
    if (v === 'local') renderLocal();
  }
  function currentMode() { return $('#mode-switch').classList.contains('on') ? 'human' : 'agent'; }

  function wire() {
    $('#view-tabs').addEventListener('click', e => {
      const b = e.target.closest('.tab');
      if (b) setView(b.dataset.view);
    });
    $('#park-select').addEventListener('change', e => loadPark(e.target.value).catch(alert));
    $('#mode-switch').addEventListener('click', () => {
      $('#mode-switch').classList.toggle('on');
      const human = currentMode();
      FAULTS.setMode(human ? 'human' : 'agent');
      FAULTS.applyMode();
      renderTopo(); renderLocal();
      if (!human) { state.picks = new Set(); }
    });
    window.addEventListener('resize', () => { CURVES.redrawIfActive(); });
  }

  async function boot() {
    wire();
    try {
      await loadParkList();
      await loadPark(state.parkId);
    } catch (e) {
      document.body.insertAdjacentHTML('beforeend',
        `<div style="position:fixed;inset:auto 16px 16px 16px" class="card"><div class="card-body">初始化失败：${e.message} —— 请确认 web/server.js 已启动且 web/public/data/ 已有园区导出 JSON。</div></div>`);
    }
    state.timer = setInterval(tick, state.tickMs);
  }
  document.addEventListener('DOMContentLoaded', boot);
})();
