'use strict';
/**
 * web/server.js · peidian-agent 前端服务（node22 零依赖）
 * 静态托管 public/ + JSON API（遥测/故障注入/人机对比判分）。
 *
 * 路由：
 *   GET  /api/health
 *   GET  /api/parks                       — data/*.json 园区清单（元信息）
 *   GET  /api/park/:id                    — 园区全量（parkdsl-web/1）
 *   GET  /api/telemetry?park=&points=&t=  — 确定性伪遥测（同 t 双跑逐字节一致）
 *   POST /api/fault  {park, text}         — 故障注入（FaultEvent v0.1，见 web/docs/fault-events.md）
 *   POST /api/fault/clear {park}          — 清除当前故障
 *   POST /api/human/attempt {park, targets, started_at} — 人工定位判分（人机对比）
 *
 * 环境：PORT(默认 8787)、DATA_DIR(默认 public/data)、FAULT_MODULE(worker-B 模块绝对路径)
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { computeSeries } = require('./telemetry');
const { FaultStore } = require('./faultstore');

const PORT = parseInt(process.env.PORT || '8787', 10);
const PUBLIC = path.join(__dirname, 'public');
const DATA_DIR = process.env.DATA_DIR || path.join(PUBLIC, 'data');
const store = new FaultStore();

/* ---- worker-B 线4 桥客户端（契约：web/docs/fault-events.md §4）----
 * 回退链：bridge（fault/bridge.py 或 env FAULT_BRIDGE_CMD）→ FAULT_MODULE → mock。
 * 桥命令只来自 env/默认路径（操作面），请求参数永不触达文件系统路径。 */
const PARK_ID_RE = /^PARK-[0-9]{3}$/;
const BRIDGE_TIMEOUT_MS = parseInt(process.env.FAULT_BRIDGE_TIMEOUT_MS || '20000', 10);

function bridgeConfigured() {
  if (process.env.FAULT_BRIDGE_CMD) return true;
  return fs.existsSync(path.join(__dirname, '..', 'fault', 'bridge.py'));
}
function bridgeArgv() {
  const envCmd = process.env.FAULT_BRIDGE_CMD;
  if (envCmd) return envCmd.trim().split(/\s+/).filter(Boolean);
  const repoPy = path.join(__dirname, '..', '.venv', 'bin', 'python');
  const py = fs.existsSync(repoPy) ? repoPy : (process.env.FAULT_BRIDGE_PYTHON || 'python3');
  return [py, path.join(__dirname, '..', 'fault', 'bridge.py')];
}
function callBridge(parkJson, text, agentEnabled) {
  return new Promise((resolve, reject) => {
    const argv = bridgeArgv();
    let child, out = '', err = '', settled = false;
    try { child = spawn(argv[0], argv.slice(1), { cwd: path.join(__dirname, '..') }); }
    catch (e) { return reject(e); }
    const timer = setTimeout(() => {
      try { child.kill('SIGKILL'); } catch (_) { /* noop */ }
      const e = new Error(`bridge 超时 ${BRIDGE_TIMEOUT_MS}ms`); e.bridgeBroken = true; reject(e);
    }, BRIDGE_TIMEOUT_MS);
    const done = fn => { if (settled) return; settled = true; clearTimeout(timer); fn(); };
    child.stdout.on('data', c => { out += c; if (out.length > 10 * 1024 * 1024) child.kill('SIGKILL'); });
    child.stderr.on('data', c => { err += c; if (err.length > 64 * 1024) err = err.slice(-32768); });
    child.on('error', e => done(() => { e.bridgeBroken = true; reject(e); }));
    child.on('close', code => done(() => {
      let parsed = null;
      try { parsed = JSON.parse(out); } catch (_) { /* 非 JSON 走 exit 码分支 */ }
      // 白名单拒绝（fault/bridge.py 约定 exit 3 + {ok:false,rejected:true}）：如实上抛，绝不静默 mock
      if (parsed && parsed.ok === false && parsed.rejected) {
        const e = new Error('fault_rejected'); e.rejected = true;
        e.reasons = parsed.reasons || []; e.llm = parsed.llm; e.park_id = parsed.park_id;
        return reject(e);
      }
      if (code !== 0) { const e = new Error(`bridge exit ${code}: ${err.trim().slice(-200)}`); e.bridgeBroken = true; return reject(e); }
      try {
        if (!parsed) throw new Error('stdout 非 JSON');
        return resolve(parsed);
      } catch (e) { e.bridgeBroken = true; reject(e); }
    }));
    child.stdin.on('error', () => { /* EPIPE 交由 close 非零码处理 */ });
    // 实际握手（fault/bridge.py）：mode=simulate 给全量事件流；stdin 一次性写入后关
    child.stdin.end(JSON.stringify({
      mode: 'simulate', park: parkJson, text,
      agent_enabled: agentEnabled !== false, horizon_s: 6,
    }));
  });
}
/** 把桥的原始事件流投影为 FaultEvent v0.2（judge 裁决③：时间线双事件口径） */
function projectBridgeEvent(res) {
  const ev = res.fault_event;
  if (!ev || typeof ev.event_id !== 'string' || !ev.agent || !Array.isArray(ev.agent.steps)) {
    throw new Error('stdout 缺 fault_event/event_id/agent.steps');
  }
  const all = Array.isArray(res.events) ? res.events : [];
  const byNo = new Map(all.filter(x => x.type === 'agent.step')
    .map(x => [x.payload && x.payload.step_no, x.payload || {}]));
  ev.agent.steps = ev.agent.steps.map(s => {
    const raw = byNo.get(s.idx) || {};
    return {
      idx: s.idx, title: s.title || raw.title || '', detail: s.detail || '',
      refs: s.refs || raw.looked_at || [],
      phase: raw.phase, looked_at: raw.looked_at, found: raw.found,
      why: raw.why, conclusion: raw.conclusion,
    };
  });
  ev.agent.total_ms = ev.agent.total_ms || (ev.agent.steps.length * 700 + 800);
  ev.actions = all.filter(x => x.type === 'action.executed' || x.type === 'action.rejected')
    .map(x => ({ action_id: x.payload.action_id, op: x.payload.op, target: x.payload.target,
                 by: x.payload.by, result: x.payload.result, note: x.payload.note,
                 reason: x.payload.reason, ts: x.ts, rejected: x.type === 'action.rejected' }));
  const MARKS = new Set(['fault.detected', 'control.passed', 'control.escalated',
                         'anomaly.cleared', 'mode.agent_enabled', 'mode.agent_disabled']);
  ev.events = all.filter(x => MARKS.has(x.type))
    .map(x => ({ type: x.type, severity: (x.payload && x.payload.severity) || '',
                 target: (x.payload && x.payload.target) || '', by: (x.payload && x.payload.by) || '',
                 note: (x.payload && x.payload.note) || '', ts: x.ts }));
  ev.source = 'fault-engine';
  ev.engine = { llm: res.llm || null, summary: res.summary || null };
  return ev;
}
async function injectFault(parkJson, text, agentEnabled) {
  if (bridgeConfigured()) {
    const t0 = Date.now();
    try {
      const res = await callBridge(parkJson, text, agentEnabled);
      const ev = projectBridgeEvent(res);
      store.adopt(parkJson.park.id, ev);
      console.log('[fault] bridge ok', Date.now() - t0 + 'ms', 'source=' + ev.source,
                  'steps=' + ev.agent.steps.length, 'llm=' + (ev.engine.llm && ev.engine.llm.used));
      return ev;
    } catch (e) {
      if (e.rejected) throw e;   // 白名单拒绝如实上抛（HTTP 422），不静默兜底
      console.error('[fault] bridge 失败，按链回退:', e.message);
    }
  }
  return store.inject(parkJson, text);
}

const MIME = {
  '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.woff2': 'font/woff2',
};

function loadParks() {
  const parks = new Map();
  if (!fs.existsSync(DATA_DIR)) return parks;
  for (const f of fs.readdirSync(DATA_DIR).filter(x => x.endsWith('.json'))) {
    try {
      const j = JSON.parse(fs.readFileSync(path.join(DATA_DIR, f), 'utf-8'));
      if (j && j.api === 'parkdsl-web/1' && j.park) parks.set(j.park.id, j);
    } catch (e) { console.error('[data] 跳过坏文件', f, e.message); }
  }
  return parks;
}
let PARKS = loadParks();
fs.watch(DATA_DIR, () => { PARKS = loadParks(); console.log('[data] reload', PARKS.size, 'parks'); });

function send(res, code, body, type = 'application/json; charset=utf-8') {
  const buf = typeof body === 'string' ? Buffer.from(body) : body;
  res.writeHead(code, { 'Content-Type': type, 'Content-Length': buf.length, 'Cache-Control': 'no-store' });
  res.end(buf);
}
function sendJSON(res, code, obj) { send(res, code, JSON.stringify(obj)); }

function readBody(req) {
  return new Promise((resolve, reject) => {
    let b = ''; req.on('data', c => { b += c; if (b.length > 1e6) req.destroy(); });
    req.on('end', () => { try { resolve(b ? JSON.parse(b) : {}); } catch (e) { reject(e); } });
    req.on('error', reject);
  });
}

async function api(req, res, url) {
  const parts = url.pathname.split('/').filter(Boolean); // ['api', ...]
  const q = url.searchParams;

  if (url.pathname === '/api/health') {
    return sendJSON(res, 200, { ok: true, parks: [...PARKS.keys()], ts: new Date().toISOString() });
  }
  if (url.pathname === '/api/parks' && req.method === 'GET') {
    return sendJSON(res, 200, {
      parks: [...PARKS.values()].map(j => ({
        id: j.park.id, name: j.park.name, tier: j.park.tier,
        description: j.park.description, contract_capacity_kw: j.park.contract_capacity_kw,
        nodes: (j.nodes || []).length, substations: (j.substations || []).length,
      })),
    });
  }
  if (parts[0] === 'api' && parts[1] === 'park' && parts[2]) {
    if (!PARK_ID_RE.test(parts[2])) return sendJSON(res, 400, { error: 'park 白名单校验失败' });
    const j = PARKS.get(parts[2]);
    return j ? sendJSON(res, 200, j) : sendJSON(res, 404, { error: 'park_not_found', id: parts[2] });
  }
  if (url.pathname === '/api/telemetry') {
    const parkArg = q.get('park') || '';
    if (!PARK_ID_RE.test(parkArg)) return sendJSON(res, 400, { error: 'park 白名单校验失败' });
    const j = PARKS.get(parkArg);
    if (!j) return sendJSON(res, 404, { error: 'park_not_found' });
    const nowSec = Math.floor(Date.now() / 1000);
    const t = q.has('t') ? parseInt(q.get('t'), 10) : nowSec;
    const points = Math.max(1, Math.min(480, parseInt(q.get('points') || '1', 10)));
    const parkId = j.park.id;
    const ev = store.activeEvent(parkId);
    const out = computeSeries(j, t, points, store.activeEffects(parkId));
    out.park = parkId;
    out.active_fault = ev ? { event_id: ev.event_id, type: ev.type, severity: ev.severity, targets: ev.targets } : null;
    return sendJSON(res, 200, out);
  }
  if (url.pathname === '/api/fault' && req.method === 'POST') {
    const body = await readBody(req);
    // 白名单（Mimosa advisory②）：park 匹配 ID 正则；body 键封闭白名单（请求参数永不触达文件路径）
    if (typeof body.park !== 'string' || !PARK_ID_RE.test(body.park)) {
      return sendJSON(res, 400, { error: 'park 白名单校验失败（须匹配 ^PARK-[0-9]{3}$）' });
    }
    for (const k of Object.keys(body)) {
      if (!['park', 'text', 'agent_enabled'].includes(k)) {
        return sendJSON(res, 400, { error: 'forbidden_key', key: k });
      }
    }
    if (typeof body.text !== 'string' || !body.text.trim() || body.text.length > 2000) {
      return sendJSON(res, 400, { error: 'text_required（1..2000 字符）' });
    }
    if ('agent_enabled' in body && typeof body.agent_enabled !== 'boolean') {
      return sendJSON(res, 400, { error: 'agent_enabled 须为布尔' });
    }
    const j = PARKS.get(body.park);
    if (!j) return sendJSON(res, 404, { error: 'park_not_found' });
    try {
      const ev = await injectFault(j, body.text, body.agent_enabled);
      console.log('[fault]', ev.event_id, ev.type, ev.severity, 'targets=', (ev.targets || []).join(','), 'source=' + ev.source);
      return sendJSON(res, 200, ev);
    } catch (e) {
      if (e.rejected) {
        // 故障 DSL 白名单拒绝（零信任）：如实传回理由，HTTP 422
        return sendJSON(res, 422, { error: 'fault_rejected', reasons: e.reasons, llm: e.llm, park_id: e.park_id });
      }
      throw e;
    }
  }
  if (url.pathname === '/api/fault/clear' && req.method === 'POST') {
    const body = await readBody(req);
    if (typeof body.park !== 'string' || !PARK_ID_RE.test(body.park)) {
      return sendJSON(res, 400, { error: 'park 白名单校验失败' });
    }
    store.clear(body.park);
    return sendJSON(res, 200, { ok: true });
  }
  if (url.pathname === '/api/human/attempt' && req.method === 'POST') {
    const body = await readBody(req);
    if (typeof body.park !== 'string' || !PARK_ID_RE.test(body.park)) {
      return sendJSON(res, 400, { error: 'park 白名单校验失败' });
    }
    const r = store.score(body.park, body.targets || [], body.started_at);
    return sendJSON(res, r.error ? 404 : 200, r);
  }
  return sendJSON(res, 404, { error: 'no_route', path: url.pathname });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  try {
    if (url.pathname.startsWith('/api/')) return await api(req, res, url);
    // 静态文件
    let p = decodeURIComponent(url.pathname);
    if (p === '/' || p === '') p = '/index.html';
    const fp = path.normalize(path.join(PUBLIC, p));
    if (!fp.startsWith(PUBLIC)) return sendJSON(res, 403, { error: 'forbidden' });
    if (!fs.existsSync(fp) || !fs.statSync(fp).isFile()) return sendJSON(res, 404, { error: 'not_found', path: p });
    const ext = path.extname(fp).toLowerCase();
    if (req.method === 'HEAD') { res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' }); return res.end(); }
    send(res, 200, fs.readFileSync(fp), MIME[ext] || 'application/octet-stream');
  } catch (e) {
    console.error('[server]', e);
    sendJSON(res, 500, { error: 'internal', message: e.message });
  }
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[peidian-agent] http://0.0.0.0:${PORT}  parks=${PARKS.size}  data=${DATA_DIR}`);
});
