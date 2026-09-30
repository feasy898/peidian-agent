'use strict';
/**
 * fault/web_module.js · worker-B 线3↔worker-A 线2 的 node 挂点模块（线4-1）。
 *
 * 用法（server.js 零改动，符合 web/docs/fault-events.md §4）：
 *   FAULT_MODULE=<repo>/fault/web_module.js node web/server.js
 * 契约：module.inject(parkJson, text) -> FaultEvent（v0.1，source="agent"）。
 * 另导出 simulate(parkJson, opts) 供 v0.2 时间线取完整事件流（agent.step +
 * action.executed，judge 第 2 轮口径③）。
 *
 * 实现：spawn python 桥（fault/bridge.py，stdin/stdout JSON）。
 *   PYTHON_BIN 环境变量可覆盖；默认 repo 根 .venv/bin/python
 *   （⚠️ 系统 /usr/bin/python=3.11 缺依赖且不认 PEP 701，judge 第 2 轮已标假红，勿用）。
 *
 * 入口守卫（Mimosa advisory② 集成轮复核项·请求路径白名单）：
 *   - park.park.id 必须匹配 ^[A-Z0-9][A-Z0-9-]{0,31}$（ParkDSL ID 命名空间）；
 *   - text 必须为 1..500 字符字符串；
 *   - 桥进程 30s 超时、stdout 上限 16MB；
 *   - 本模块不接收任何文件路径输入，不落盘（事件流落盘由调用方显式指定）。
 * 注入被拒（白名单/校验越界）→ 抛 Error（reasons JSON 附于 message）→ server 按
 * 契约 §4 回退 mock 并日志留痕——拒绝语义不静默吞掉。
 */
const { spawn } = require('child_process');
const path = require('path');

const PY = process.env.PYTHON_BIN ||
  path.join(path.dirname(__dirname), '.venv', 'bin', 'python');
const BRIDGE = path.join(__dirname, 'bridge.py');
const ID_RE = /^[A-Z0-9][A-Z0-9-]{0,31}$/;

function guard(parkJson, text, extra) {
  if (!parkJson || parkJson.api !== 'parkdsl-web/1' || !parkJson.park ||
      !ID_RE.test(String(parkJson.park.id || ''))) {
    throw new Error('guard_reject: parkJson 必须为 parkdsl-web/1 且 park.id 匹配 ^[A-Z0-9][A-Z0-9-]{0,31}$');
  }
  if (typeof text !== 'string' || text.length < 1 || text.length > 500) {
    throw new Error('guard_reject: text 必须为 1..500 字符');
  }
  if (extra && typeof extra !== 'object') {
    throw new Error('guard_reject: opts 必须为对象');
  }
}

function callBridge(payload) {
  return new Promise((resolve, reject) => {
    const proc = spawn(PY, [BRIDGE], {
      cwd: path.dirname(BRIDGE),
      env: Object.assign({}, process.env),   // 凭证经环境传递，argv-free 零打印
    });
    let out = '', err = '', killed = false;
    const timer = setTimeout(() => { killed = true; proc.kill('SIGKILL'); }, 30000);
    proc.stdout.on('data', d => { out += d; if (out.length > 16 * 1024 * 1024) proc.kill('SIGKILL'); });
    proc.stderr.on('data', d => { err += d; });
    proc.on('close', code => {
      clearTimeout(timer);
      if (killed) return reject(new Error('bridge_timeout(30s)'));
      let j;
      try { j = JSON.parse(out.trim().split('\n').pop() || '{}'); }
      catch (e) { return reject(new Error(`bridge_bad_output(exit=${code}): ${err.slice(0, 400)}`)); }
      if (!j.ok) {
        const reason = (j.reasons || []).join('; ') || 'bridge_rejected';
        const e = new Error(`bridge_rejected: ${reason}`);
        e.rejected = true; e.reasons = j.reasons || [];
        return reject(e);
      }
      resolve(j);
    });
    proc.stdin.write(JSON.stringify(payload));
    proc.stdin.end();
  });
}

/** FaultEvent v0.1（含 agent.steps——内部跑完整 simulate(auto) 取步骤流） */
function inject(parkJson, text) {
  guard(parkJson, text);
  return callBridge({
    mode: 'simulate', park: parkJson, text,
    agent_enabled: true,
    seed: parkJson.park.seed,
  }).then(j => j.fault_event);
}

/** v0.2 时间线用：完整事件流 + 开关终态 + 处置摘要。opts 见 fault/bridge.py 模块头。 */
function simulate(parkJson, opts) {
  opts = opts || {};
  const text = opts.text !== undefined ? opts.text : (opts.fault ? '' : null);
  if (text === null && !opts.fault) {
    throw new Error('guard_reject: simulate 需要 text 或 opts.fault');
  }
  const p = {
    mode: 'simulate', park: parkJson,
    agent_enabled: opts.agent_enabled !== false,
    seed: opts.seed || parkJson.park.seed,
    horizon_s: opts.horizon_s, at_s: opts.at_s,
    human_actions: Array.isArray(opts.human_actions) ? opts.human_actions : undefined,
  };
  if (opts.fault) p.fault = opts.fault; else p.text = text;
  if (p.horizon_s === undefined) delete p.horizon_s;
  if (p.at_s === undefined) delete p.at_s;
  if (!p.human_actions) delete p.human_actions;
  guard(parkJson, typeof p.text === 'string' && p.text ? p.text : `explicit:${p.fault.type || 'fault'}`, p);
  return callBridge(p);
}

module.exports = { inject, simulate, callBridge, guard };
