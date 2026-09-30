# -*- coding: utf-8 -*-
"""fault.bridge · python↔node 桥 CLI（线4-1，judge 第 2 轮指定交付）。

协议：stdin 收一行 JSON → stdout 出一行 JSON。由 web/fault_module.js spawn
（也可独立使用/HTTP 包装）。

stdin:
  {"mode": "inject"|"simulate",
   "park":  <parkdsl-web/1 导出 JSON>,
   "text":  "自然语言故障描述",
   "agent_enabled": true,                  # simulate 用；人机对比开关
   "human_actions": [{"op":"open","target":"SG-A01"}, …],  # simulate+manual 用
   "seed": 可选（缺省用 park.park.seed）, "horizon_s": 6.0, "at_s": 1.0}

stdout（inject）:
  {"ok": true, "fault_event": <FaultEvent v0.1>, "llm": {"used": bool, "reason": str}}
  {"ok": false, "rejected": true, "reasons": [...]}            # 白名单/校验拒绝（exit 3）
stdout（simulate）: 上述字段 + {"events": [...], "switches": {...}, "anomalies": [...],
                               "summary": {"cleared": bool, "cleared_by": str,
                                           "escalated": bool, "switch_ops": [...]}}

离线兜底（judge 第 2 轮任务 3）：环境无 HIGRESS_API_KEY（或 FAULT_BRIDGE_FORCE_OFFLINE=1）
→ 规则解析器接管，llm.used=false 并带原因——页面不瘫；凭据到位后同一入口自动走真实
LLM（配额线4≤4，本轮 0 次消耗）。密钥零打印：本 CLI 永不回显任何环境变量值。

用法：.venv/bin/python fault/bridge.py < payload.json
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from fault import (  # noqa: E402
    Engine, EventBus, FaultRejected, FaultSpec, HigressClient, Topology,
    demo_park, nl_to_fault, validate_fault_dict,
)
from fault.fault_event import build_fault_event  # noqa: E402
from fault.park_adapter import AdapterError, park_to_topology  # noqa: E402

__all__ = ["run_inject", "run_simulate", "main"]

MAX_TEXT = 500          # 注入文本长度上限（web_module.js 同口径双保险）


def _llm_client() -> tuple[object | None, str]:
    if os.environ.get("FAULT_BRIDGE_FORCE_OFFLINE") == "1":
        return None, "forced_offline(FAULT_BRIDGE_FORCE_OFFLINE=1)"
    if os.environ.get("HIGRESS_API_KEY"):
        try:
            return HigressClient(), "higress_key_present"
        except (ValueError, OSError) as exc:   # base_url 非法等——不回显值
            return None, f"higress_client_init_failed: {type(exc).__name__}"
    return None, "no_credentials(HIGRESS_API_KEY unset)"


def _build_topology(park: dict) -> tuple[Topology, str]:
    if park is None:
        return demo_park(), "PARK-DEMO(内置演示园区)"
    topo = park_to_topology(park)
    return topo, str(park.get("park", {}).get("id") or topo.park_id)


def run_inject(payload: dict) -> tuple[dict, int]:
    text = payload.get("text")
    if not isinstance(text, str) or not (0 < len(text) <= MAX_TEXT):
        return {"ok": False, "rejected": True,
                "reasons": [f"text 必须为 1..{MAX_TEXT} 字符"]}, 3
    topo, park_id = _build_topology(payload.get("park"))
    client, llm_reason = _llm_client()
    try:
        spec = nl_to_fault(text, topo, client=client)
    except FaultRejected as exc:
        return {"ok": False, "rejected": True, "park_id": park_id,
                "reasons": exc.reasons, "llm": {"used": client is not None,
                                                "reason": llm_reason}}, 3
    ev = build_fault_event(park_id=park_id, text=text, topo=topo, spec=spec,
                           anomaly=None, steps=[], mode="auto", total_ms=0,
                           cleared=False, escalated=False)
    return {"ok": True, "fault_event": ev,
            "llm": {"used": client is not None, "reason": llm_reason}}, 0


def run_simulate(payload: dict) -> tuple[dict, int]:
    text = payload.get("text")
    explicit = payload.get("fault")           # 显式故障 DSL（矩阵/测试用，绕过 NL）
    if not explicit and (not isinstance(text, str) or not (0 < len(text) <= MAX_TEXT)):
        return {"ok": False, "rejected": True,
                "reasons": [f"text 必须为 1..{MAX_TEXT} 字符"]}, 3
    agent_enabled = bool(payload.get("agent_enabled", True))
    horizon = float(payload.get("horizon_s", 6.0))
    at_s = float(payload.get("at_s", 1.0))
    topo, park_id = _build_topology(payload.get("park"))

    client, llm_reason = _llm_client()
    spec: FaultSpec
    try:
        if explicit:
            raw = dict(explicit)
            raw.setdefault("at_s", at_s)
            spec = validate_fault_dict(raw, topo, seq=1)
            llm_used = False
        else:
            spec = nl_to_fault(text, topo, client=client)
            llm_used = client is not None
    except FaultRejected as exc:
        return {"ok": False, "rejected": True, "park_id": park_id,
                "reasons": exc.reasons, "llm": {"used": client is not None,
                                                "reason": llm_reason}}, 3

    # at_s 落到仿真时间轴（NL 解析默认 0 → 取 at_s 参数）
    spec.at_s = max(spec.at_s, at_s) if not explicit else spec.at_s

    stream = EventBus()
    eng = Engine(topo, seed=int(payload.get("seed") or 42), stream=stream,
                 agent_enabled=agent_enabled)
    t0 = time.perf_counter()
    eng.inject(spec)
    human_ran = False
    if not agent_enabled:
        # 人工态：先跑到故障被检出（control.passed），再回放人工操作，再复测
        eng.run(max(eng.sim_s, 2.0))
        human_actions = payload.get("human_actions") or []
        human_ran = False
        for act in human_actions:
            eng.human_action({"op": act.get("op"), "target": act.get("target"),
                              "reason": "matrix 人工回放（与 agent 同款操作面）"})
            human_ran = True
        eng.run(max(eng.sim_s + 3 * eng.dt, horizon))
    else:
        eng.run(horizon)
    total_ms = int((time.perf_counter() - t0) * 1000)

    events = stream.to_list()
    ano = None
    for a in eng.detector.active.values():
        if a.target == spec.target:
            ano = a
            break
    steps = [e for e in events if e["channel"] == "agent"
             and (ano is None or e["payload"].get("anomaly_id") == (ano.anomaly_id if ano else None))]
    cleared_evts = [e for e in events if e["type"] == "anomaly.cleared"]
    escalated = any(e["type"] == "control.escalated" for e in events)
    switch_ops = [{"op": e["payload"]["op"], "target": e["payload"]["target"],
                   "by": e["payload"]["by"], "result": e["payload"]["result"]}
                  for e in events if e["channel"] == "ops"
                  and e["type"] == "action.executed"]
    cleared = bool(cleared_evts)
    cleared_by = cleared_evts[-1]["payload"]["by"] if cleared else ""

    fault_event = build_fault_event(
        park_id=park_id, text=text or str(explicit), topo=topo, spec=spec,
        anomaly=ano, steps=steps, mode="auto" if agent_enabled else "manual",
        total_ms=total_ms, cleared=cleared, escalated=escalated,
        load_rate=(eng.sample.get(spec.target, {}).get("load_rate")
                   if topo.kind_of(spec.target) == "transformer" else None))

    return {"ok": True,
            "fault_event": fault_event,
            "llm": {"used": llm_used, "reason": llm_reason},
            "park_id": park_id,
            "events": events,
            "switches": dict(eng.executor.switch_states),
            "anomalies": [{"id": a.anomaly_id, "hint": a.hint, "target": a.target,
                           "status": a.status, "acked": a.acked}
                          for a in eng.detector.active.values()],
            "summary": {"cleared": cleared, "cleared_by": cleared_by,
                        "escalated": escalated, "switch_ops": switch_ops,
                        "human_replayed": human_ran}}, 0


def main(argv: list[str]) -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "rejected": True,
                          "reasons": [f"stdin 不是合法 JSON: {exc}"]},
                         ensure_ascii=False))
        return 2
    mode = payload.get("mode", "inject")
    try:
        if mode == "inject":
            out, code = run_inject(payload)
        elif mode == "simulate":
            out, code = run_simulate(payload)
        else:
            out, code = {"ok": False, "rejected": True,
                         "reasons": [f"未知 mode: {mode!r}（inject|simulate）"]}, 2
    except AdapterError as exc:
        out, code = {"ok": False, "rejected": True,
                     "reasons": [f"园区适配失败: {exc}"]}, 3
    print(json.dumps(out, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
