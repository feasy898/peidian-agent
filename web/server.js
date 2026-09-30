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
function callBridge(parkJson, text) {
  return new Promise((resolve, reject) => {
    const argv = bridgeArgv();
    let child, out = '', err = '', settled = false;
    try { child = spawn(argv[0], argv.slice(1), { cwd: path.join(__dirname, '..') }); }
    catch (e) { return reject(e); }
    const timer = setTimeout(() => {
      try { child.kill('SIGKILL'); } catch (_) { /* noop */ }
      reject(new Error(`bridge 超时 ${BRIDGE_TIMEOUT_MS}ms`));
    }, BRIDGE_TIMEOUT_MS);
    const done = fn => { if (settled) return; settled = true; clearTimeout(timer); fn(); };
    child.stdout.on('data', c => { out += c; if (out.length > 10 * 1024 * 1024) child.kill('SIGKILL'); });
    child.stderr.on('data', c => { err += c; if (err.length > 64 * 1024) err = err.slice(-32768); });
    child.on('error', e => done(() => reject(e)));
    child.on('close', code => done(() => {
      if (code !== 0) return reject(new Error(`bridge exit ${code}: ${err.trim().slice(-200)}`));
      try {
        const ev = JSON.parse(out);
        if (!ev || typeof ev.event_id !== 'string' || !ev.agent) throw new Error('缺 event_id/agent');
        return resolve(ev);
      } catch (e) { reject(new Error('stdout 不可解析: ' + e.message)); }
    }));
    child.stdin.on('error', () => { /* EPIPE 交由 close 非零码处理 */ });
    child.stdin.end(JSON.stringify({ park: parkJson, text }));
  });
}
async function injectFault(parkJson, text) {
  if (bridgeConfigured()) {
    const t0 = Date.now();
    try {
      const ev = await callBridge(parkJson, text);
      if (!ev.source) ev.source = 'fault-engine';
      store.adopt(parkJson.park.id, ev);
      console.log('[fault] bridge ok', Date.now() - t0 + 'ms', 'source=' + ev.source);
      return ev;
    } catch (e) {
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
    // 白名单（Mimosa advisory②）：park 必须匹配 ID 正则；body 键白名单，路径类键直接拒
    if (typeof body.park !== 'string' || !PARK_ID_RE.test(body.park)) {
      return sendJSON(res, 400, { error: 'park 白名单校验失败（须匹配 ^PARK-[0-9]{3}$）' });
    }
    for (const k of ['path', 'file', 'out', 'dir', 'sink']) {
      if (k in body) return sendJSON(res, 400, { error: 'forbidden_key', key: k });
    }
    if (typeof body.text !== 'string' || !body.text.trim() || body.text.length > 2000) {
      return sendJSON(res, 400, { error: 'text_required（1..2000 字符）' });
    }
    const j = PARKS.get(body.park);
    if (!j) return sendJSON(res, 404, { error: 'park_not_found' });
    const ev = await injectFault(j, body.text);
    console.log('[fault]', ev.event_id, ev.type, ev.severity, 'targets=', (ev.targets || []).join(','), 'source=' + ev.source);
    return sendJSON(res, 200, ev);
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
