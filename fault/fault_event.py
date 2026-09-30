# -*- coding: utf-8 -*-
"""fault.fault_event · FaultEvent v0.1（web/docs/fault-events.md，集成基准）构造器。

类型映射（我方四类 → v0.1 taxonomy 十类；severity 对齐仓内 AlarmLevel 语义）：
  SHORT_CIRCUIT@transformer → transformer.trip (P0)
  SHORT_CIRCUIT@line        → line.fault        (P0，检测器severity为准)
  LINE_BREAK@line           → line.fault        (P0/P1 按检测器)
  TX_OVERLOAD@transformer   → overload          (P0，REG-TECH 重过载口径)
  PV_TRIP@pv                → breaker.trip      (P2，taxonomy 无 pv 专类，取保护跳闸语义)
telemetry_effects 口径对齐 mock（web/faultstore.js §5）：跳闸→目标功率归零并下探一级
失电；过载→目标 loading×ratio；光伏→目标功率归零。
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Optional

from .detect import Anomaly
from .topology import KIND_LINE, KIND_PV, KIND_TX, Topology

__all__ = ["build_fault_event", "TYPE_MAP"]

TYPE_MAP = {
    ("SHORT_CIRCUIT", KIND_TX): "transformer.trip",
    ("SHORT_CIRCUIT", KIND_LINE): "line.fault",
    ("LINE_BREAK", KIND_LINE): "line.fault",
    ("TX_OVERLOAD", KIND_TX): "overload",
    ("PV_TRIP", KIND_PV): "breaker.trip",
}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".%03dZ" % (
        int(time.time() * 1000) % 1000)


def _event_id(park_id: str, text: str, ts: str) -> str:
    h = hashlib.sha1(f"{park_id}|{text}".encode("utf-8")).hexdigest()[:4]
    return "FLT-" + ts.replace("-", "").replace(":", "").replace(".", "")[:14] + f"-{h}"


def build_fault_event(*, park_id: str, text: str, topo: Topology,
                      spec: Optional[Any], anomaly: Optional[Anomaly],
                      steps: list[dict], mode: str, total_ms: int,
                      cleared: bool, escalated: bool,
                      load_rate: Optional[float] = None) -> dict:
    """构造 FaultEvent v0.1 dict。spec=None 表示注入被拒（调用方不应走到这，兜底 generic）。"""
    ftype = spec.type if spec is not None else "PV_TRIP"
    kind = topo.kind_of(spec.target) if spec is not None and topo.has(spec.target) else ""
    ev_type = TYPE_MAP.get((ftype, kind), "generic.alarm")
    ts = _now_iso()
    severity = anomaly.severity if anomaly is not None else "P2"

    effects: list[dict] = []
    if spec is not None and topo.has(spec.target):
        tgt = spec.target
        if ftype in ("SHORT_CIRCUIT", "LINE_BREAK"):
            effects.append({"component": tgt, "metric": "power", "multiplier": 0.0})
            # 失电下探：目标边对端母线的下游功率归零（对齐 mock“跳闸→功率归零”口径）
            end = topo.get(tgt).to
            if end and topo.has(end):
                for d in topo.downstream(end):
                    if topo.kind_of(d) in ("load", "pv", "bess", "evcharger"):
                        effects.append({"component": d, "metric": "power",
                                        "multiplier": 0.0})
        elif ftype == "TX_OVERLOAD":
            effects.append({"component": tgt, "metric": "loading",
                            "multiplier": round(float(load_rate or
                                                     spec.params.get("overload_ratio", 1.2)), 3)})
        elif ftype == "PV_TRIP":
            effects.append({"component": tgt, "metric": "power", "multiplier": 0.0})

    agent_block = {
        "mode": "auto" if mode == "auto" else "manual",
        "total_ms": int(total_ms),
        "steps": [
            {"idx": s["payload"]["step_no"],
             "title": s["payload"]["title"],
             "detail": s["payload"]["why"] + (
                 "；" + s["payload"]["conclusion"] if s["payload"].get("conclusion") else ""),
             "refs": list(s["payload"].get("looked_at") or [])}
            for s in steps
        ],
        "cleared": bool(cleared),
        "escalated": bool(escalated),
    }

    return {
        "event_id": _event_id(park_id, text, ts),
        "ts": ts,
        "park_id": park_id,
        "request_text": text,
        "type": ev_type,
        "severity": severity,
        "targets": [spec.target] if spec is not None else [],
        "telemetry_effects": effects,
        "agent": agent_block,
        "source": "agent",
        "module": "fault/bridge.py",
        "fault_type": ftype,      # 我方四类 DSL 原名（v0.2 升级候选字段）
    }
