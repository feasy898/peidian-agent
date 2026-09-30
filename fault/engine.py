# -*- coding: utf-8 -*-
"""fault.engine · 仿真引擎：把拓扑/遥测/注入/检测/反应/操作/事件流串成一台戏。

对外 API（worker-A web/ 集成面，详见 fault/README.md §6）：
  eng = Engine(topo=None, seed=20261001)
  eng.set_agent_enabled(False)          # 人机对比开关
  spec = eng.inject(dict_or_FaultSpec)  # 校验不过抛 FaultRejected
  eng.run(until_s) / eng.tick()
  eng.human_action({"op","target","reason"})   # 人工操作（与 agent 同款执行器）
  eng.state_snapshot() / eng.stream / eng.sample
"""
from __future__ import annotations

from typing import Any, Optional

from .actions import ActionExecutor
from .agent import AgentResponder
from .detect import Anomaly, Detector
from .dsl import FaultRejected, FaultSpec, validate_fault_dict
from .stream import EventBus
from .telemetry import DAYLIGHT, TelemetryModel
from .topology import KIND_BUS, KIND_TX, Topology, demo_park

__all__ = ["Engine"]

MAX_CONVERGE_ITERS = 4  # 单拍内 收敛圈数上限（动作→新样本→新检测）


class Engine:
    def __init__(self, topo: Optional[Topology] = None, seed: int = 20261001,
                 agent_enabled: bool = True, stream: Optional[EventBus] = None,
                 dt: float = 0.5) -> None:
        self.topo = topo or demo_park()
        # 注意：EventBus 定义了 __len__，空流为 falsy——必须用 is None 判断
        self.stream = stream if stream is not None else EventBus()
        self.dt = dt
        self.sim_s = 0.0
        self.telem = TelemetryModel(self.topo, seed=seed)
        self.detector = Detector(self.topo)
        self.executor = ActionExecutor(self.topo, self.stream)
        self.responder = AgentResponder(
            self.topo, self.stream, self.executor,
            sample_fn=lambda: self.sample,
            active_faults_fn=lambda: self.active_faults,
            enabled=agent_enabled)
        self.agent_enabled = agent_enabled
        self.planned: list[FaultSpec] = []
        self.active_faults: list[FaultSpec] = []
        self._fired: set[str] = set()
        self.sample: dict[str, dict] = {}
        self._warned: dict[str, bool] = {}

    # ================================================================ 模式开关
    def set_agent_enabled(self, enabled: bool, note: str = "") -> None:
        """人机对比总开关。关闭后异常只上报不处置，操作面交给人工（同款执行器）。"""
        prev = self.agent_enabled
        self.agent_enabled = bool(enabled)
        self.responder.enabled = self.agent_enabled
        if prev != self.agent_enabled or note:
            self.stream.append("control",
                               "mode.agent_enabled" if enabled else "mode.agent_disabled",
                               {"enabled": self.agent_enabled,
                                "note": note or ("agent 反应开启" if enabled
                                                 else "agent 反应关闭，界面交人工定位")},
                               sim_s=self.sim_s)

    # ================================================================ 注入
    def inject(self, raw: Any) -> FaultSpec:
        """自然层入口：dict（或 FaultSpec）→ 校验 → 计划。越界即拒。"""
        if isinstance(raw, FaultSpec):
            spec = validate_fault_dict(raw.to_dict(), self.topo,
                                       seq=len(self.planned) + 1)
            spec.fault_id = raw.fault_id or spec.fault_id
        else:
            spec = validate_fault_dict(raw, self.topo, seq=len(self.planned) + 1)
        for p in self.planned:
            if p.type == spec.type and p.target == spec.target:
                raise FaultRejected(
                    [f"目标已有同型计划/活跃故障: {spec.type}@{spec.target}（{p.fault_id}）"])
        self.planned.append(spec)
        self.stream.append("fault", "fault.planned", {
            "fault_id": spec.fault_id, "type": spec.type, "target": spec.target,
            "at_s": spec.at_s, "params": spec.params, "note": spec.note,
        }, sim_s=self.sim_s)
        return spec

    def _activate_due(self) -> None:
        for spec in list(self.planned):
            if spec.at_s <= self.sim_s and spec.fault_id not in self._fired:
                self._fired.add(spec.fault_id)
                self.active_faults.append(spec)
                self.stream.append("fault", "fault.injected", {
                    "fault_id": spec.fault_id, "type": spec.type,
                    "target": spec.target, "at_s": spec.at_s,
                    "params": spec.params, "note": spec.note,
                }, sim_s=self.sim_s)

    # ================================================================ 运行
    def tick(self) -> None:
        self.sim_s += self.dt
        self._activate_due()
        handled_now: list[Anomaly] = []
        for _ in range(MAX_CONVERGE_ITERS):
            self.sample = self.telem.sample(self.executor.switch_states,
                                            self.active_faults)
            energ = self.topo.energized(self.executor.switch_states)
            new, cleared = self.detector.scan(self.sample,
                                              self.executor.switch_states,
                                              self.sim_s, energ)
            for a in cleared:
                by = "agent" if self.agent_enabled else "human"
                self.stream.append("fault", "anomaly.cleared", {
                    "anomaly_id": a.anomaly_id, "hint": a.hint,
                    "target": a.target, "by": by,
                    "cleared_at_s": self.sim_s,
                }, sim_s=self.sim_s)
                self.responder.on_cleared(a, self.sim_s, by)
            if not new:
                self._warn_checks()
                break
            for a in new:
                self.executor.anomalies[a.anomaly_id] = a
                self.stream.append("fault", "fault.detected", {
                    "anomaly_id": a.anomaly_id, "hint": a.hint,
                    "target": a.target, "severity": a.severity,
                    "evidence": a.evidence,
                }, sim_s=self.sim_s)
            if self.agent_enabled:
                for a in new:
                    self.responder.handle(a, self.sim_s)
                    handled_now.append(a)
            else:
                for a in new:
                    self.stream.append("control", "control.passed", {
                        "anomaly_id": a.anomaly_id, "hint": a.hint,
                        "target": a.target,
                        "note": "agent 反应已关闭，交人工处置（操作面与 agent 同款）",
                    }, sim_s=self.sim_s)
            self._warn_checks()
        # 动作后征兆未消除 → 如实升级（绝不假绿）
        keys_active = set(self.detector.active)
        for a in handled_now:
            if a.key() in keys_active and a.status == "active":
                self.responder.on_stuck(a, self.sim_s)
                self.stream.append("control", "control.escalated", {
                    "anomaly_id": a.anomaly_id, "hint": a.hint,
                    "target": a.target,
                    "note": "agent 动作后复测未消除，升级人工",
                }, sim_s=self.sim_s)

    def run(self, until_s: float) -> None:
        while self.sim_s < until_s - 1e-9:
            self.tick()

    def human_action(self, action: dict) -> dict:
        """人工操作入口（人机对比模式）。action={op,target,reason}，同款执行器。"""
        return self.executor.execute(
            str(action.get("op", "")), str(action.get("target", "")),
            by="human", reason=str(action.get("reason", "")), sim_s=self.sim_s)

    # ================================================================ 观测
    def _warn_checks(self) -> None:
        for w in self.detector.warn_crossings(self.sample, self.sim_s):
            t = w["target"]
            if not self._warned.get(t):
                self._warned[t] = True
                self.stream.append("fault", "threshold.warn", w, sim_s=self.sim_s)
            else:
                self._warned[t] = True
        for t in list(self._warned):
            lr = float(self.sample.get(t, {}).get("load_rate", 0.0))
            if lr <= 0.80:
                self._warned.pop(t, None)

    def state_snapshot(self) -> dict:
        return {
            "sim_s": round(self.sim_s, 3),
            "switches": dict(self.executor.switch_states),
            "active_faults": [f.to_dict() for f in self.active_faults],
            "anomalies": {k: {"id": a.anomaly_id, "hint": a.hint,
                              "target": a.target, "status": a.status,
                              "acked": a.acked}
                          for k, a in self.detector.active.items()},
            "sample": self.sample,
            "daylight": DAYLIGHT,
        }
