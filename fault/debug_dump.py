# -*- coding: utf-8 -*-
"""fault/debug_dump.py · 场景事件流转储（联调工具：worker-A web/ 对接口时用）。

用法：python fault/debug_dump.py [sc|lb|txover|pv|human|mixed]
打印指定演示场景的完整事件流（seq/channel/type/关键 payload），用于人工核对
步骤流与异常归属。退出码恒 0（诊断工具）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fault import Engine, demo_park  # noqa: E402


def _brief(e):
    p = e["payload"]
    extra = ""
    if e["type"] == "agent.step":
        extra = f" step={p['step_no']}:{p['phase']}:{p['title']} concl={p['conclusion'][:40]}"
    elif e["type"] in ("fault.detected",):
        extra = f" {p['hint']}@{p['target']} sev={p['severity']} ano={p['anomaly_id']}"
    elif e["type"] in ("fault.injected", "fault.planned"):
        extra = f" {p['type']}@{p['target']} at={p['at_s']}"
    elif e["type"] in ("anomaly.cleared",):
        extra = f" ano={p['anomaly_id']} by={p['by']}"
    elif e["type"] in ("action.executed", "action.rejected"):
        extra = f" {p['op']} {p['target']} by={p['by']} → {p['result']}"
    elif e["type"] in ("threshold.warn",):
        extra = f" {p['target']} rate={p['load_rate']}"
    elif e["type"].startswith("mode.") or e["type"] == "control.passed":
        extra = f" {p.get('note', '')}"
    return f"#{e['seq']:03d} t={e['sim_s']:>5} [{e['channel']:>9}] {e['type']}{extra}"


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "sc"
    eng = Engine(demo_park(), seed=20261001 if which != "mixed" else 7)
    if which == "sc":
        eng.inject({"type": "SHORT_CIRCUIT", "target": "TX-01", "at_s": 1.0})
        eng.run(4.0)
    elif which == "lb":
        eng.inject({"type": "LINE_BREAK", "target": "LN-A1", "at_s": 1.0})
        eng.run(4.0)
    elif which == "txover":
        eng.inject({"type": "TX_OVERLOAD", "target": "TX-01", "at_s": 1.0,
                    "params": {"overload_ratio": 1.1}})
        eng.run(4.0)
    elif which == "pv":
        eng.inject({"type": "PV_TRIP", "target": "PV-01", "at_s": 1.0})
        eng.run(4.0)
    elif which == "human":
        eng.set_agent_enabled(False, note="人机对比：交人工")
        eng.inject({"type": "TX_OVERLOAD", "target": "TX-01", "at_s": 1.0,
                    "params": {"overload_ratio": 1.1}})
        eng.run(1.5)
        for act in ({"op": "open", "target": "SG-A1H", "reason": "人工隔离1号主变"},
                    {"op": "open", "target": "SG-A02", "reason": "人工隔离低压侧"},
                    {"op": "close", "target": "SG-TIE", "reason": "人工倒闸转供"}):
            eng.human_action(act)
        eng.run(4.0)
        eng.set_agent_enabled(True, note="人机对比：agent 接管")
        eng.inject({"type": "PV_TRIP", "target": "PV-01", "at_s": 5.0})
        eng.run(8.0)
    elif which == "mixed":
        eng.inject({"type": "SHORT_CIRCUIT", "target": "TX-01", "at_s": 1.0})
        eng.inject({"type": "PV_TRIP", "target": "PV-01", "at_s": 3.0})
        eng.run(6.0)
    for e in eng.stream.to_list():
        print(_brief(e))
    snap = eng.state_snapshot()
    print("SWITCHES:", {k: v for k, v in snap["switches"].items()})
    print("TX-01:", snap["sample"].get("TX-01"), " TX-02:", snap["sample"].get("TX-02"))
    print("ANOMALIES:", snap["anomalies"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
