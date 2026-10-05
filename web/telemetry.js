'use strict';
/**
 * web/telemetry.js · 确定性伪遥测引擎（服务端）
 * 公式与 dsl/docs/dsl-spec.md §8 一一对应；形状表来自 DSL 导出 JSON（源头 dsl/dsl_spec.yaml）。
 * 同 (seed, id, t) 必得同值 —— judge 可用 curl 双跑同 t 比对逐字节一致。
 */
const DEFAULTS = {
  step_sec: 15, noise_amplitude: 0.04, wander_amplitude: 0.02, wander_period_sec: 600,
  voltage_drop_factor: 0.03, voltage_noise: 0.004,
};

function hash32(s) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
  return h >>> 0;
}
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
/** 确定性 [0,1)：仅由 (seed,id,tStep) 决定 */
function unit(seed, id, tStep) {
  const h = hash32(String(id));
  const x = (Math.imul(tStep + 1, 2654435761) ^ Math.imul(h, 2246822519)) >>> 0;
  return mulberry32((x ^ h) >>> 0)();
}
function shapeAt(shapes, profile, tSec) {
  const arr = shapes[profile] || shapes.office;
  const h = ((tSec / 3600) % 24 + 24) % 24;
  const i0 = Math.floor(h) % 24, i1 = (i0 + 1) % 24, f = h - Math.floor(h);
  return arr[i0] * (1 - f) + arr[i1] * f;
}

/**
 * 计算一段遥测。
 * @param parkJson  parkdsl-web/1 导出 JSON
 * @param tEndSec   末点 epoch 秒
 * @param points    点数
 * @param effects   故障乘子 [{component, metric:'power'|'voltage', multiplier}]
 * @returns {t0, step_sec, points, series, totals}
 */
function computeSeries(parkJson, tEndSec, points, effects) {
  const tel = Object.assign({}, DEFAULTS, parkJson.telemetry || {});
  const seed = tel.seed >>> 0;
  const step = tel.step_sec;
  const t0 = tEndSec - (points - 1) * step;
  const effP = new Map(), effV = new Map();
  (effects || []).forEach(e => {
    if (e.metric === 'voltage') effV.set(e.component, e.multiplier);
    else effP.set(e.component, e.multiplier);
  });

  const comps = tel.components || [];
  const buses = tel.buses || [];
  const compIds = comps.map(c => c.id);
  const P = new Map();   // id -> Float64Array
  const I = new Map();
  compIds.forEach(id => { P.set(id, new Array(points).fill(0)); I.set(id, new Array(points).fill(0)); });
  const V = new Map();
  buses.forEach(b => V.set(b.id, new Array(points).fill(0)));

  // 有功（含形状/噪声/故障乘子）
  for (const c of comps) {
    const arr = P.get(c.id);
    const isBess = c.profile === 'bess';
    for (let k = 0; k < points; k++) {
      const t = t0 + k * step;
      const sh = shapeAt(tel.shapes, c.profile, t) * (isBess ? 2 : 1);
      const u = unit(seed, c.id, Math.floor(t / step));
      const wander = tel.wander_amplitude * Math.sin(2 * Math.PI * t / tel.wander_period_sec + (hash32(c.id) % 628) / 100);
      const eps = tel.noise_amplitude * (u - 0.5) * 2 + wander;
      let p = (c.rated_kw || 0) * sh * (1 + eps);
      const m = effP.get(c.id);
      if (m !== undefined) p *= m;
      arr[k] = Math.round(p * 100) / 100;
    }
  }

  // 变压器潮流（演示口径）：= 同配电房全部功率元件代数和（负荷+储能−光伏）
  const subOfId = new Map();
  for (const n of parkJson.nodes || []) subOfId.set(n.id, n.substation || '_');
  const powerCompIds = comps.filter(c => c.metric === 'power').map(c => c.id);
  for (const tx of comps) {
    if (tx.metric !== 'loading') continue;
    const arr = P.get(tx.id), sub = subOfId.get(tx.id);
    for (let k = 0; k < points; k++) {
      let s = 0;
      for (const cid of powerCompIds) if (subOfId.get(cid) === sub) s += P.get(cid)[k];
      arr[k] = Math.round(s * 100) / 100;
    }
  }

  // 母线电压：V = vnom×(1 − drop×loading + vnoise·u)
  const contract = (parkJson.park && parkJson.park.contract_capacity_kw) || 1;
  for (let k = 0; k < points; k++) {
    const t = t0 + k * step;
    let loadSum = 0;
    for (const c of comps) if (c.metric === 'power' && c.profile !== 'pv' && c.profile !== 'bess') loadSum += P.get(c.id)[k];
    const loading = Math.min(1.2, loadSum / contract);
    for (const b of buses) {
      const u = unit(seed, b.id + ':v', Math.floor(t / step));
      let v = b.vnom_kv * 1000 * (1 - tel.voltage_drop_factor * loading + tel.voltage_noise * (u - 0.5) * 2);
      const m = effV.get(b.id);
      if (m !== undefined) v *= m;
      V.get(b.id)[k] = Math.round(v * 100) / 100;
    }
  }

  // 电流：I = P/(√3·V·pf)，电压取同名(配电房字母)最低压母线或全园 0.4kV 首母线
  const busBySub = new Map();
  for (const n of parkJson.nodes || []) {
    if (n.type === 'Bus') {
      const key = n.substation || '_';
      if (!busBySub.has(key)) busBySub.set(key, n);
    }
  }
  const subOf = new Map();
  for (const n of parkJson.nodes || []) subOf.set(n.id, n.substation || '_');
  for (const c of comps) {
    const arrP = P.get(c.id), arrI = I.get(c.id);
    let bus = busBySub.get(subOf.get(c.id)) || busBySub.get('_');
    const vArr = bus ? V.get(bus.id) : null;
    const vnom = (bus ? bus.vnom_kv * 1000 : 380) || 380;
    for (let k = 0; k < points; k++) {
      const v = vArr ? vArr[k] : vnom;
      const i = v > 0 ? (Math.abs(arrP[k]) * 1000) / (1.7320508 * v * (c.pf || 0.85)) : 0;
      arrI[k] = Math.round(i * 10) / 10;
    }
  }

  // 全园总加
  const totals = { load_kw: new Array(points).fill(0), pv_kw: new Array(points).fill(0), bess_kw: new Array(points).fill(0), grid_kw: new Array(points).fill(0) };
  for (let k = 0; k < points; k++) {
    for (const c of comps) {
      if (c.metric !== 'power') continue;
      const p = P.get(c.id)[k];
      if (c.profile === 'pv') totals.pv_kw[k] += p;
      else if (c.profile === 'bess') totals.bess_kw[k] += p;
      else totals.load_kw[k] += p;
    }
    totals.grid_kw[k] = Math.round((totals.load_kw[k] + totals.bess_kw[k] - totals.pv_kw[k]) * 100) / 100;
  }

  const series = {};
  compIds.forEach(id => { series[id] = { p_kw: P.get(id), i_a: I.get(id) }; });
  buses.forEach(b => { series[b.id] = { v_v: V.get(b.id) }; });
  return { t0, t: tEndSec, step_sec: step, points, series, totals };
}

/** 全景用瞬时快照（points=1 的便捷封装） */
function snapshot(parkJson, tSec, effects) {
  const s = computeSeries(parkJson, tSec, 1, effects);
  const out = { t: tEndNorm(s.t, s.step_sec), series: {}, totals: {} };
  for (const id of Object.keys(s.series)) out.series[id] = Object.fromEntries(Object.entries(s.series[id]).map(([k, a]) => [k, a[0]]));
  for (const id of Object.keys(s.totals)) out.totals[id] = s.totals[id][0];
  return out;
}
function tEndNorm(t, step) { return Math.floor(t / step) * step; }

module.exports = { computeSeries, snapshot, hash32, mulberry32, unit, shapeAt, DEFAULTS };
