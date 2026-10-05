'use strict';
/* web/public/js/curves.js · 曲线视角：全园总加 + 元件级时序（滚动窗口 180 点） */
const CURVES = (() => {
  const MAXPTS = 180;
  const COLORS = ['#60a5fa', '#fbbf24', '#a78bfa', '#34d399', '#f87171', '#2dd4bf', '#f472b6', '#c084fc', '#facc15', '#4ade80'];
  const state = {
    parkId: null, comps: [],       // [{id,type,profile,sub}]
    buf: new Map(),                // id -> {p:[],v:[],i:[]}
    totalsBuf: { t: [], grid: [], load: [], pv: [], bess: [] },
    selected: new Set(), metric: 'p', lastT: 0,
    totalsChart: null, compChart: null,
  };
  const $ = s => document.querySelector(s);

  function colorOf(c) {
    const m = { Load: 0, EVCharger: 3, PV: 1, BESS: 2, Transformer: 4, Switchgear: 5 };
    return COLORS[(m[c.type] ?? 6) % COLORS.length];
  }

  function init(parkJson) {
    state.parkId = parkJson.park.id;
    state.buf = new Map();
    state.totalsBuf = { t: [], grid: [], load: [], pv: [], bess: [] };
    state.selected = new Set();
    state.comps = (parkJson.telemetry.components || []).map(c => ({
      id: c.id, type: (parkJson.nodes.find(n => n.id === c.id) || {}).type || '',
      profile: c.profile, sub: (parkJson.nodes.find(n => n.id === c.id) || {}).substation || '',
    }));
    const buses = (parkJson.telemetry.buses || []).map(b => ({ id: b.id, type: 'Bus', profile: '', sub: (parkJson.nodes.find(n => n.id === b.id) || {}).substation || '' }));
    state.all = [...state.comps, ...buses];
    // 默认选前 5 个负荷类
    state.all.filter(c => c.type === 'Load').slice(0, 5).forEach(c => state.selected.add(c.id));
    renderCompList();
    state.totalsChart = new LineChart($('#chart-totals'), { unit: ' kW' });
    state.compChart = new LineChart($('#chart-comp'), { unit: '' });
  }

  function renderCompList() {
    const box = $('#comp-list'); box.innerHTML = '';
    const groups = new Map();
    for (const c of state.all) {
      if (!groups.has(c.type)) groups.set(c.type, []);
      groups.get(c.type).push(c);
    }
    for (const [type, arr] of groups) {
      const h = document.createElement('div');
      h.className = 'kicker'; h.style.margin = '8px 0 3px'; h.textContent = type;
      box.appendChild(h);
      for (const c of arr) {
        const lab = document.createElement('label');
        lab.className = 'comp-item';
        lab.innerHTML = `<input type="checkbox" ${state.selected.has(c.id) ? 'checked' : ''}>
          <span class="cid">${c.id}</span><span class="ctype">${esc(c.sub)}</span>`;
        lab.querySelector('input').addEventListener('change', e => {
          if (e.target.checked) state.selected.add(c.id); else state.selected.delete(c.id);
        });
        box.appendChild(lab);
      }
    }
  }

  /** 每个遥测 tick 调用 */
  function pushSnapshot(snap) {
    if (!snap || snap.t === state.lastT) return;
    state.lastT = snap.t;
    const tb = state.totalsBuf;
    tb.t.push(snap.t); tb.grid.push(snap.totals.grid_kw); tb.load.push(snap.totals.load_kw);
    tb.pv.push(snap.totals.pv_kw); tb.bess.push(snap.totals.bess_kw);
    for (const k of ['t', 'grid', 'load', 'pv', 'bess']) if (tb[k].length > MAXPTS) tb[k].shift();

    for (const c of state.all) {
      const s = snap.series[c.id] || {};
      let b = state.buf.get(c.id);
      if (!b) { b = { p: [], v: [], i: [] }; state.buf.set(c.id, b); }
      b.p.push(s.p_kw != null ? s.p_kw : null);
      b.v.push(s.v_v != null ? s.v_v : null);
      b.i.push(s.i_a != null ? s.i_a : null);
      for (const k of ['p', 'v', 'i']) if (b[k].length > MAXPTS) b[k].shift();
    }
    if (document.querySelector('#view-curves').classList.contains('active')) draw();
  }

  function draw() {
    const tb = state.totalsBuf;
    state.totalsChart.setData(tb.t, [
      { label: '下网', color: '#e5e7eb', values: tb.grid },
      { label: '负荷', color: '#60a5fa', values: tb.load },
      { label: '光伏', color: '#fbbf24', values: tb.pv },
      { label: '储能', color: '#a78bfa', values: tb.bess },
    ]);
    const unit = state.metric === 'p' ? ' kW' : state.metric === 'v' ? ' V' : ' A';
    state.compChart.opts.unit = unit;
    const series = [];
    let i = 0;
    for (const c of state.all) {
      if (!state.selected.has(c.id)) continue;
      const b = state.buf.get(c.id);
      if (b) series.push({ label: c.id, color: COLORS[i++ % COLORS.length], values: b[state.metric] });
    }
    state.compChart.setData(tb.t, series);
  }

  function setMetric(m) { state.metric = m; draw(); }
  function redrawIfActive() { if (document.querySelector('#view-curves').classList.contains('active')) draw(); }

  function esc(s) { return String(s == null ? '' : s); }
  document.addEventListener('DOMContentLoaded', () => {
    $('#metric-tabs').addEventListener('click', e => {
      const b = e.target.closest('[data-metric]');
      if (!b) return;
      document.querySelectorAll('#metric-tabs [data-metric]').forEach(x => x.classList.remove('primary'));
      b.classList.add('primary');
      setMetric(b.dataset.metric);
    });
  });

  return { init, pushSnapshot, draw, redrawIfActive };
})();
