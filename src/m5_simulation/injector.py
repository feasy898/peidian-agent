# -*- coding: utf-8 -*-
"""m5_simulation.injector · 故障注入（SPEC-M5-05）。

五种注入（按 ``at`` 计划触发，全部落 SIM 时间线，事件带精确子步时刻）：

- ``SENSOR_STUTTER``  遥信抖动：目标设备状态在 ``window_s`` 内快速翻转
  ``flips`` 次（EVAL-M5-05-P2：3 秒 4 翻）；``debounced_state`` 提供去抖视图
  （状态稳定 ≥ ``debounce_s`` 才可信）；
- ``SENSING_OUTAGE``  量测中断：窗口内量测保持旧值 + ``STALE`` 标志 +
  中断区间 ``[from, to]``（不得伪造新读数；恢复后刷新）；
- ``COMM_LOSS``       审批通道中断：窗口内 ``approval_channel_open()=False``，
  审批等待走超时语义（approval.timeout）；
- ``ALARM_STORM``     告警风暴：``count`` 条告警按 ``window_s`` 均布注入，
  全部落 SIM 时间线（事件总数=注入数），聚合视图按级别汇总不丢事件；
- ``DEVICE_TRIP``     设备跳闸：状态 → FAULT、分闸（如有），
  ``grid.event`` 近似保护动作（M5 §2 精度边界声明）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from contracts import EventType

from .alarm_engine import aggregate_by_level
from .env import SimEnv, parse_time_ref

__all__ = ["FAULT_TYPES", "FaultInjector", "FAULT_PARAMS_DEFAULTS", "inject"]

FAULT_TYPES = ("SENSOR_STUTTER", "SENSING_OUTAGE", "COMM_LOSS", "ALARM_STORM", "DEVICE_TRIP")

FAULT_PARAMS_DEFAULTS: dict[str, dict] = {
    "SENSOR_STUTTER": {"flips": 4, "window_s": 3.0, "debounce_s": 2.0},
    "SENSING_OUTAGE": {"duration_s": 900.0},
    "COMM_LOSS": {"duration_s": 600.0},
    "ALARM_STORM": {"count": 50, "window_s": 60.0, "levels": ["P2", "P3"]},
    "DEVICE_TRIP": {"breaker_to": "OPEN"},
}


@dataclass
class PlannedFault:
    """一条已计划的注入（at 解析为绝对时刻 + 仿真秒）。"""

    fault_type: str
    target: str
    at_s: float
    params: dict
    fired: bool = False


class FaultInjector:
    """故障注入器：计划按 at 排序，apply_due 触发到期项（确定性顺序）。"""

    def __init__(self, env: SimEnv, *, debounce_s: float = 2.0) -> None:
        self.env = env
        self.default_debounce_s = float(debounce_s)
        self.planned: list[PlannedFault] = []
        self.fired: list[dict] = []
        self.storm_alarms: list[dict] = []   # 风暴告警记录（聚合口径）

    # ---------------------------------------------------------------- 计划
    def plan(self, injections: list) -> list:
        """ScenarioSpec.environment.injections → 计划表（at 升序，稳定排序）。"""
        clock_start = self.env.clock.clock_start
        for injection in injections or []:
            at_abs = parse_time_ref(injection.at, clock_start)
            at_s = (at_abs - clock_start).total_seconds()
            params = dict(FAULT_PARAMS_DEFAULTS.get(injection.type, {}))
            params.update(injection.params or {})
            if injection.type not in FAULT_TYPES:
                raise ValueError(
                    f"未知注入类型: {injection.type!r}（允许: {'/'.join(FAULT_TYPES)}）"
                )
            self.planned.append(PlannedFault(
                fault_type=injection.type, target=injection.target,
                at_s=at_s, params=params,
            ))
        self.planned.sort(key=lambda p: (p.at_s, p.fault_type, p.target))
        return self.planned

    def pending_after(self, sim_s: float) -> bool:
        return any(not p.fired and p.at_s > sim_s for p in self.planned)

    # ---------------------------------------------------------------- 触发
    def apply_due(self, prev_s: float, now_s: float) -> list:
        """触发 (prev_s, now_s] 内到期的注入，返回产生的事件列表。"""
        events: list = []
        for plan in self.planned:
            if plan.fired or not (prev_s < plan.at_s <= now_s):
                continue
            events.extend(self.inject(plan))
        return events

    def inject(self, fault: PlannedFault | dict) -> list:
        """执行一条注入（01 §3.5 冻结 API ``inject(env, fault)`` 的实现载体）。"""
        if isinstance(fault, dict):  # {at, type, target, params}
            clock_start = self.env.clock.clock_start
            at_abs = parse_time_ref(fault.get("at", 0), clock_start)
            params = dict(FAULT_PARAMS_DEFAULTS.get(str(fault.get("type")), {}))
            params.update(fault.get("params") or {})
            fault = PlannedFault(fault_type=str(fault.get("type")), target=str(fault.get("target")),
                                 at_s=(at_abs - clock_start).total_seconds(), params=params)

        handler = {
            "SENSOR_STUTTER": self._inject_stutter,
            "SENSING_OUTAGE": self._inject_outage,
            "COMM_LOSS": self._inject_comm_loss,
            "ALARM_STORM": self._inject_storm,
            "DEVICE_TRIP": self._inject_trip,
        }.get(fault.fault_type)
        if handler is None:
            raise ValueError(f"未知注入类型: {fault.fault_type!r}")

        fault.fired = True
        events: list = [self.env.emit(
            EventType.SIM_INJECTED, fault.target,
            {"fault_type": fault.fault_type, "at_s": fault.at_s, "params": fault.params},
            fault.at_s,
        )]
        events.extend(handler(fault))
        self.fired.append({"fault_type": fault.fault_type, "target": fault.target,
                           "at_s": fault.at_s, "params": fault.params})
        return events

    # ---------------------------------------------------------------- 各类型
    def _inject_stutter(self, fault: PlannedFault) -> list:
        """遥信抖动：flips 次翻转均布在 window_s 内；全部落 SIM 时间线。

        翻转时间线登记到 ``env.chatter``（``env.debounced_state`` 的数据源，
        SPEC-M5-05：agent 应等待去抖确认，不据抖动窗口内状态操作）。
        """
        env = self.env
        device = env.devices.get(fault.target)
        if device is None:
            raise ValueError(f"SENSOR_STUTTER 目标设备不存在: {fault.target!r}")
        flips = max(int(fault.params.get("flips", 4)), 1)
        window_s = float(fault.params.get("window_s", 3.0))
        debounce_s = float(fault.params.get("debounce_s", self.default_debounce_s))
        initial = device.breaker_state or "CLOSED"
        toggle = {"CLOSED": "OPEN", "OPEN": "CLOSED"}

        timeline: list = []
        state = initial
        for index in range(flips):
            offset = fault.at_s + (window_s * index / (flips - 1) if flips > 1 else 0.0)
            previous, state = state, toggle.get(state, state)
            timeline.append({"at_s": offset, "state": state})
            env.emit(EventType.MEASUREMENT_UPDATED, fault.target,
                     {"quantity": "breaker_state", "flip": index + 1,
                      "from": previous, "to": state,
                      "fault_type": "SENSOR_STUTTER"},
                     offset)
        device.breaker_state = state

        env.chatter[fault.target] = {
            "at_s": fault.at_s, "window_s": window_s, "debounce_s": debounce_s,
            "flips": timeline, "initial": initial, "final_state": state,
        }
        return []  # 事件已在时间线内逐条落

    def _inject_outage(self, fault: PlannedFault) -> list:
        """量测中断：登记窗口；量测保持旧值 + STALE + 中断区间（恢复后刷新）。"""
        duration_s = float(fault.params.get("duration_s", 900.0))
        from_s = fault.at_s
        to_s = from_s + duration_s
        self.env.outages.append({
            "target": fault.target, "from_s": from_s, "to_s": to_s,
            "from": self.env.iso_at(from_s), "to": self.env.iso_at(to_s),
        })
        return []

    def _inject_comm_loss(self, fault: PlannedFault) -> list:
        """审批通道中断：窗口内 approval_channel_open()=False（超时语义走场景引擎）。"""
        duration_s = float(fault.params.get("duration_s", 600.0))
        from_s = fault.at_s
        to_s = from_s + duration_s
        self.env.comm_losses.append({
            "target": fault.target or "approval_channel",
            "from_s": from_s, "to_s": to_s,
            "from": self.env.iso_at(from_s), "to": self.env.iso_at(to_s),
        })
        return []

    def _inject_storm(self, fault: PlannedFault) -> list:
        """告警风暴：count 条按 window_s 均布注入；聚合视图按级别汇总，不丢事件。"""
        env = self.env
        count = int(fault.params.get("count", 50))
        window_s = float(fault.params.get("window_s", 60.0))
        levels = fault.params.get("levels") or ["P2", "P3"]
        spacing = window_s / count if count > 0 else 0.0
        created: list = []
        for index in range(count):
            at_s = fault.at_s + spacing * index
            level = str(levels[index % len(levels)])
            alarm_id = env.next_alarm_id()
            record = {
                "alarm_id": alarm_id, "level": level, "code": "ALARM_STORM",
                "source_ref": fault.target, "metric": "storm",
                "text": f"{fault.target} 告警风暴注入 #{index + 1}（{fault.fault_type}）",
                "raised_at": env.iso_at(at_s, ms=True), "cleared_at": None, "ack_by": None,
                "injected": True,
            }
            env.alarms[alarm_id] = record
            created.append(record)
            env.emit(EventType.ALARM_RAISED, fault.target,
                     {"alarm_id": alarm_id, "level": level, "rule": "ALARM_STORM",
                      "text": record["text"], "injected": True},
                     at_s)
        self.storm_alarms.extend(created)
        aggregate = aggregate_by_level(created)
        self.last_storm_aggregate = aggregate
        env.storm_summary = dict(aggregate)  # 聚合呈现（env.state_final 可见）
        return []

    def _inject_trip(self, fault: PlannedFault) -> list:
        """设备跳闸：FAULT + 分闸（保护动作以 grid.event 近似，M5 §2 精度边界）。"""
        env = self.env
        device = env.devices.get(fault.target)
        if device is None:
            raise ValueError(f"DEVICE_TRIP 目标设备不存在: {fault.target!r}")
        device.breaker_state = str(fault.params.get("breaker_to", "OPEN"))
        env.set_device_state(fault.target, "FAULT", fault.at_s, reason="DEVICE_TRIP")
        return [env.emit(EventType.GRID_EVENT, fault.target,
                         {"kind": "保护动作", "detail": "DEVICE_TRIP 注入跳闸",
                          "breaker_state": device.breaker_state},
                         fault.at_s)]


def inject(env: SimEnv, fault: Any) -> SimEnv:
    """01 §3.5 冻结 API：``inject(env, fault) -> SimEnv``。

    ``fault``：``{at, type, target, params}``（FaultSpec 口径，at 为时间引用）。
    就地变更并返回同一 env（进程内语义）。
    """
    FaultInjector(env).inject(fault)
    return env
