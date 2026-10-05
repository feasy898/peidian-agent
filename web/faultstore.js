'use strict';
/**
 * web/faultstore.js · 故障注入（mock 实现 + worker-B 模块挂点）
 *
 * 接口契约：web/docs/fault-events.md（FaultEvent v0.1，元件 ID 权威源 = ParkDSL 导出 JSON）。
 * 对齐点：env FAULT_MODULE=/abs/path/module.js 时，require 该模块并调用
 *   module.inject(parkJson, text) -> FaultEvent（同 schema，source 标注真实实现）
 * 未设置或模块抛错 → 内置 mock（source: "mock"）。前端不感知差别。
 */
const crypto = require('crypto');

const SEVERITY = { P0: 'P0', P1: 'P1', P2: 'P2', P3: 'P3' };

/** 从文本抽取显式元件 ID（权威源 = 导出 JSON 的节点/连线 ID） */
function findExplicitIds(parkJson, text) {
  const ids = new Set();
  for (const n of parkJson.nodes || []) if (text.includes(n.id)) ids.add(n.id);
  for (const l of parkJson.links || []) if (l.id && text.includes(l.id)) ids.add(l.id);
  return [...ids];
}

/** 口语序号定位："2 号变压器" → 该类型第 2 台（按 ID 排序，房间字母优先） */
function ordinalResolve(parkJson, text) {
  const out = new Set();
  const typeWords = [
    [/(\d+)\s*号变压器|变压器.*?(\d+)\s*号/, 'Transformer'],
    [/(\d+)\s*号母线|母线.*?(\d+)\s*号/, 'Bus'],
    [/(\d+)\s*号线路|线路.*?(\d+)\s*号/, 'LN'],
    [/(\d+)\s*号充电桩|充电桩.*?(\d+)\s*号/, 'EVCharger'],
  ];
  const nodes = parkJson.nodes || [];
  for (const [re, type] of typeWords) {
    const m = text.match(re);
    if (!m) continue;
    const n = parseInt(m[1] || m[2], 10);
    if (!n || n < 1) continue;
    let cands;
    if (type === 'LN') cands = (parkJson.links || []).filter(l => l.kind === 'line').map(l => ({ id: l.id }));
    else cands = nodes.filter(x => x.type === type);
    cands.sort((a, b) => String(a.id).localeCompare(String(b.id), 'zh'));
    if (cands[n - 1]) out.add(cands[n - 1].id);
  }
  return [...out];
}

function classify(text) {
  const t = text || '';
  if (/重瓦斯|差动/.test(t)) return { type: 'transformer.trip', severity: 'P0' };
  if (/火灾|起火/.test(t)) return { type: 'fire', severity: 'P0' };
  if (/母线.*失压|全所失电|停电/.test(t)) return { type: 'bus.deenergized', severity: 'P0' };
  if (/短路|母线故障/.test(t)) return { type: 'bus.fault', severity: 'P1' };
  if (/断线|覆冰|杆塔|接地/.test(t)) return { type: 'line.fault', severity: 'P1' };
  if (/跳闸/.test(t)) return { type: 'breaker.trip', severity: 'P1' };
  if (/过载|重过载|过负荷/.test(t)) return { type: 'overload', severity: 'P2' };
  if (/通信|遥信.*中断/.test(t)) return { type: 'comm.loss', severity: 'P2' };
  if (/低压|电压偏低|闪变/.test(t)) return { type: 'voltage.sag', severity: 'P3' };
  return { type: 'generic.alarm', severity: 'P2' };
}

/** 故障的遥测效应：跳闸→功率归零；母线短路→电压跌至 0.6；线路故障→线路两端失电 */
function telemetryEffectsFor(parkJson, targets, cls) {
  const effects = [];
  const nodeType = new Map((parkJson.nodes || []).map(n => [n.id, n.type]));
  for (const id of targets) {
    const type = nodeType.get(id);
    if (cls.type === 'bus.fault' || cls.type === 'bus.deenergized') {
      effects.push({ component: id, metric: 'voltage', multiplier: 0.6 });
      // 该母线下游全部功率清零
      for (const l of parkJson.links || []) if (l.from === id) effects.push({ component: l.to, metric: 'power', multiplier: 0 });
    } else if (cls.type === 'voltage.sag') {
      effects.push({ component: id, metric: 'voltage', multiplier: 0.92 });
    } else if (type === 'Load' || type === 'EVCharger' || type === 'PV' || type === 'BESS' || type === 'Transformer' || type === 'Switchgear') {
      effects.push({ component: id, metric: 'power', multiplier: 0 });
    } else if (type === undefined && /^LN-/.test(id)) {
      for (const l of parkJson.links || []) if (l.id === id) effects.push({ component: l.to, metric: 'power', multiplier: 0 });
    } else if (/^CP-/.test(id)) {
      // 联络点故障不直接作用遥测
    }
  }
  return effects;
}

/** agent 处置步骤骨架（演示管线；worker-B 接入后由其覆盖 agent 字段） */
function agentStepsFor(parkJson, targets, cls, text) {
  const nodeType = new Map((parkJson.nodes || []).map(n => [n.id, n.type]));
  const subsOf = new Map((parkJson.nodes || []).map(n => [n.id, n.substation]));
  const subName = new Map((parkJson.substations || []).map(s => [s.id, s.name]));
  const tgt = targets[0] || '未知元件';
  const sub = subsOf.get(tgt);
  const downstreamLoads = (parkJson.nodes || []).filter(n => n.type === 'Load' && n.substation === sub);
  const sgIn = (parkJson.nodes || []).find(n => n.type === 'Switchgear' && n.substation === sub);
  const steps = [
    { idx: 1, title: '告警接入与确认', detail: `SCADA 推读事件：「${(text || cls.type).slice(0, 40)}」→ 初判 ${cls.severity} 级`, refs: [] },
    { idx: 2, title: '故障定位', detail: `遥测突变比对 + 拓扑追溯，锁定故障元件 ${tgt}（${nodeType.get(tgt) || '线路'}）`, refs: [tgt] },
    { idx: 3, title: '影响分析', detail: `失电范围：${sub ? subName.get(sub) || sub : '全园'} · 下游负荷 ${downstreamLoads.length} 回路`, refs: downstreamLoads.map(l => l.id) },
    { idx: 4, title: '规程检索', detail: '命中运行规程：故障隔离与转供条款（演示检索）', refs: [] },
    { idx: 5, title: '隔离方案', detail: `拉开 ${sgIn ? sgIn.id : '就近开关'} 隔离故障区段，校验防误闭锁`, refs: sgIn ? [sgIn.id] : [] },
    { idx: 6, title: '转供与恢复', detail: (parkJson.links || []).some(l => l.kind === 'coupler') ? '合上联络点转供失电负荷（备自投演练）' : '无联络点，走检修流程，负荷走错峰', refs: [] },
    { idx: 7, title: '复盘报告', detail: '生成处置时间线与整改建议（模拟）', refs: [] },
  ];
  return steps;
}

/** mock 故障注入主入口 */
function injectMock(parkJson, text, seq) {
  const cls = classify(text);
  let targets = findExplicitIds(parkJson, text);
  if (!targets.length) targets = ordinalResolve(parkJson, text);
  if (!targets.length) {
    // 兜底：按类型关键词挑第一个匹配元件
    const kwMap = [['变压器', 'Transformer'], ['母线', 'Bus'], ['线路', 'LN'], ['光伏', 'PV'], ['储能', 'BESS'], ['充电', 'EVCharger'], ['负荷', 'Load']];
    for (const [kw, type] of kwMap) {
      if ((text || '').includes(kw)) {
        if (type === 'LN') { const l = (parkJson.links || []).find(x => x.kind === 'line'); if (l) { targets = [l.id]; break; } }
        const n = (parkJson.nodes || []).find(x => x.type === type);
        if (n) { targets = [n.id]; break; }
      }
    }
  }
  const now = Date.now();
  const event_id = `FLT-${new Date(now).toISOString().slice(0, 10).replace(/-/g, '')}-${String(seq).padStart(4, '0')}`;
  return {
    event_id,
    ts: new Date(now).toISOString(),
    park_id: parkJson.park.id,
    request_text: text || '',
    type: cls.type,
    severity: cls.severity,
    targets,
    telemetry_effects: telemetryEffectsFor(parkJson, targets, cls),
    agent: { mode: 'auto', total_ms: 1800 + targets.length * 900 + Math.floor(Math.random() * 600), steps: agentStepsFor(parkJson, targets, cls, text) },
    source: 'mock',
  };
}

class FaultStore {
  constructor() { this.bySeq = new Map(); this.seq = 0; this.active = new Map(); /* park -> event */ }
  moduleHook() {
    const p = process.env.FAULT_MODULE;
    if (!p) return null;
    try { return require(p); } catch (e) { console.error('[faultstore] FAULT_MODULE 加载失败，回退 mock:', e.message); return null; }
  }
  inject(parkJson, text) {
    this.seq += 1;
    const mod = this.moduleHook();
    let ev;
    try {
      ev = mod && typeof mod.inject === 'function' ? mod.inject(parkJson, text) : injectMock(parkJson, text, this.seq);
    } catch (e) {
      console.error('[faultstore] 外部模块异常，回退 mock:', e.message);
      ev = injectMock(parkJson, text, this.seq);
    }
    if (!ev.event_id) ev.event_id = `FLT-ADHOC-${crypto.randomBytes(3).toString('hex')}`;
    this.bySeq.set(ev.event_id, { ev, park: parkJson.park.id, born: Date.now() });
    this.active.set(parkJson.park.id, ev);
    return ev;
  }
  /** 桥模式登记：FaultEvent 由外部引擎产出，仅入册供遥测效应与人工判分使用 */
  adopt(parkId, ev) {
    this.seq += 1;
    this.bySeq.set(ev.event_id, { ev, park: parkId, born: Date.now() });
    this.active.set(parkId, ev);
  }
  activeEffects(parkId) {
    const ev = this.active.get(parkId);
    return ev ? ev.telemetry_effects : [];
  }
  activeEvent(parkId) { return this.active.get(parkId) || null; }
  clear(parkId) { this.active.delete(parkId); }
  score(parkId, chosen, startedAtMs) {
    const ev = this.active.get(parkId);
    if (!ev) return { error: 'no_active_event' };
    const truth = new Set(ev.targets || []);
    const pick = new Set(chosen || []);
    let hits = 0;
    for (const c of pick) if (truth.has(c)) hits += 1;
    return {
      event_id: ev.event_id,
      truth: [...truth],
      chosen: [...pick],
      hits, precision: pick.size ? hits / pick.size : 0, recall: truth.size ? hits / truth.size : 0,
      elapsed_ms: startedAtMs ? Date.now() - startedAtMs : null,
      verdict: hits === truth.size && pick.size === truth.size ? 'CORRECT' : (hits > 0 ? 'PARTIAL' : 'WRONG'),
    };
  }
}

module.exports = { FaultStore, injectMock, classify, SEVERITY };
