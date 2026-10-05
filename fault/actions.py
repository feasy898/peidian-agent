# -*- coding: utf-8 -*-
"""fault.actions · 操作执行器（ActionExecutor）——agent 与人工**同款操作面**。

唯一合法操作（白名单）：
  open/close  目标必须是 operable 开关（拉闸/合闸/倒闸）
  ack         目标必须是已存在异常 ID（告警确认/复归）
每次执行落 ops 事件（by=agent|human），执行前后开关态变化如实记录。
"""
from __future__ import annotations

from typing import Any

from .detect import Anomaly
from .stream import EventBus
from .topology import KIND_SW, Topology

__all__ = ["ActionExecutor", "OPS_WHITELIST"]

OPS_WHITELIST = ("open", "close", "ack")


class ActionExecutor:
    def __init__(self, topo: Topology, stream: EventBus) -> None:
        self.topo = topo
        self.stream = stream
        self.switch_states: dict[str, str] = {
            e.id: str(e.attrs.get("normally", "OPEN"))
            for e in topo.by_kind(KIND_SW)
        }
        self.anomalies: dict[str, Anomaly] = {}  # id → Anomaly（engine 注入）
        self._seq = 0
        self.log: list[dict] = []

    # ------------------------------------------------------------------
    def execute(self, op: str, target: str, by: str, reason: str,
                sim_s: float) -> dict:
        """执行并落事件。返回 {ok, result, note}；非法操作拒绝并落 ops 事件。"""
        if op not in OPS_WHITELIST:
            return self._reject(op, target, by, reason, sim_s,
                                f"操作越界: {op!r} 不在白名单 {list(OPS_WHITELIST)}")
        if by not in ("agent", "human"):
            return self._reject(op, target, by, reason, sim_s,
                                f"操作主体非法: {by!r}（允许 agent/human）")
        if op in ("open", "close"):
            if not self.topo.has(target):
                return self._reject(op, target, by, reason, sim_s,
                                    f"目标开关不存在: {target}")
            e = self.topo.get(target)
            if e.kind != KIND_SW:
                return self._reject(op, target, by, reason, sim_s,
                                    f"目标 {target} 不是开关（{e.kind}，不可遥控）")
            if not e.attrs.get("operable", False):
                return self._reject(op, target, by, reason, sim_s,
                                    f"目标 {target} 不可遥控（operable=False）")
            want = "OPEN" if op == "open" else "CLOSED"
            before = self.switch_states.get(target, "OPEN")
            if before == want:
                res = "noop"
                note = f"{target} 已是 {want}，无需操作"
            else:
                self.switch_states[target] = want
                res = "ok"
                note = f"{target}: {before} → {want}"
        else:  # ack
            a = self.anomalies.get(target)
            if a is None:
                return self._reject(op, target, by, reason, sim_s,
                                    f"目标异常不存在: {target}")
            a.acked = True
            res, note = "ok", f"异常 {target} 已确认/复归（{a.hint}@{a.target}）"

        self._seq += 1
        evt = self.stream.append("ops", "action.executed", {
            "action_id": f"ACT-{self._seq:03d}", "op": op, "target": target,
            "by": by, "result": res, "note": note, "reason": reason,
        }, sim_s=sim_s)
        rec = {"action_id": f"ACT-{self._seq:03d}", "op": op, "target": target,
               "by": by, "result": res, "reason": reason, "sim_s": sim_s}
        self.log.append(rec)
        return {"ok": True, "result": res, "note": note, "event": evt}

    # ------------------------------------------------------------------
    def _reject(self, op, target, by, reason, sim_s, why: str) -> dict:
        self._seq += 1
        self.stream.append("ops", "action.rejected", {
            "action_id": f"ACT-{self._seq:03d}", "op": op, "target": target,
            "by": by, "result": "rejected", "note": why, "reason": reason,
        }, sim_s=sim_s)
        return {"ok": False, "result": "rejected", "note": why}
