# -*- coding: utf-8 -*-
"""m5_simulation.alarm_engine · 规则驱动告警（SPEC-M5-08：判据与规程同源）。

- 阈值**一律**取自 ``regulations/REG-TECH.yaml``（经 ``LoadedOntology.regulations``
  装载）——改规则文件即改仿真告警行为，仿真代码零硬编码阈值（EVAL-M5-08-P）；
- 逐 (规则, 对象) 评估：规则 ``scope`` 字段决定作用对象类型（数据驱动），
  ``metric`` 决定取哪个量测，``thresholds`` 按序评估取最严重级别（P0 最重）；
- 告警对象与 00 §1.1.C Alarm 一致（level/source_ref/code/text/raised_at/cleared_at/ack_by），
  事件为 ``alarm.raised`` / ``alarm.cleared``（01 §4）；
- 故障注入的告警（ALARM_STORM）由 injector 产生、本引擎提供按级别聚合视图，
  不丢弃任何事件（SPEC-M5-05：事件总数=注入数）。

M5 §2 示例口径（">80%→WARN、>95%→ALARM"）与 REG-TECH 阈值（0.80→P2、
1.00→P0）以规程文件为准（SPEC-M5-08 同源要求；REG-TECH 头注释即此声明）。
"""
from __future__ import annotations

from typing import Any

from contracts import EventType

from .env import SimEnv

__all__ = ["AlarmEngine", "aggregate_by_level", "LEVEL_SEVERITY"]

#: 级别严重度（数值越小越严重；取最严重=最小）
LEVEL_SEVERITY = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

#: 判定算子（REG-TECH thresholds.op 字面量）
_OPS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
}


def aggregate_by_level(alarms: list) -> dict:
    """按级别聚合（ALARM_STORM 的限流/聚合呈现口径；不减少事件总数）。"""
    summary: dict[str, int] = {}
    for alarm in alarms:
        level = str(alarm.get("level"))
        summary[level] = summary.get(level, 0) + 1
    return {"by_level": dict(sorted(summary.items())), "total": len(alarms)}


class AlarmEngine:
    """规程阈值驱动的告警评估（无内部状态，随 env 重放确定）。"""

    def __init__(self, env: SimEnv) -> None:
        self.env = env
        # 规程判据（REG-TECH）：metric + thresholds + scope，数据驱动装载
        self._rules: list = []
        tech = (env.ontology.regulations or {}).get("REG-TECH") or {}
        for item in tech.get("rules") or []:
            if item.get("metric") and item.get("thresholds"):
                self._rules.append(item)

    # ---------------------------------------------------------------- 主入口
    def evaluate(self, sim_elapsed_s: float, *, extra_metrics: dict | None = None) -> list:
        """评估全部 (规则, 对象)：越限发 alarm.raised，恢复发 alarm.cleared。

        ``extra_metrics``：非量测库指标（如园区 demand_ratio，来自需量滑窗）。
        返回本步事件列表。
        """
        events: list = []
        extra_metrics = extra_metrics or {}
        active: dict = self._active_index()

        for rule in self._rules:
            rule_id = rule["id"]
            metric = rule["metric"]
            for subject, value in self._subjects_and_values(rule, metric, extra_metrics):
                if value is None:
                    continue
                hit = self._worst_threshold(rule, value)
                key = f"{rule_id}:{subject}"
                current = active.get(key)
                if hit is not None:
                    level, name, threshold_value = hit
                    if current is None:
                        record = self._raise(rule, subject, value, level, name,
                                             threshold_value, sim_elapsed_s)
                        events.extend(self._events_of(record, raised=True,
                                                      sim_elapsed_s=sim_elapsed_s))
                    elif current["level"] != level:
                        # 级别变化：先清后升（保持单一活动告警 per (规则,对象)）
                        events.extend(self._events_of(current, raised=False,
                                                      sim_elapsed_s=sim_elapsed_s))
                        record = self._raise(rule, subject, value, level, name,
                                             threshold_value, sim_elapsed_s)
                        events.extend(self._events_of(record, raised=True,
                                                      sim_elapsed_s=sim_elapsed_s))
                elif current is not None:
                    events.extend(self._events_of(current, raised=False,
                                                  sim_elapsed_s=sim_elapsed_s))

        return events

    # ---------------------------------------------------------------- 内部
    def _active_index(self) -> dict:
        return {
            f"{a['code']}:{a['source_ref']}": a
            for a in self.env.alarms.values() if a["cleared_at"] is None
        }

    def _subjects_and_values(self, rule: dict, metric: str, extra_metrics: dict):
        """规则 scope → 对象集合；对象 → 指标值（量测库 or extra_metrics）。"""
        scope = rule.get("scope")
        if scope == "Park":
            if metric in extra_metrics:
                yield self.env.park_id, extra_metrics[metric]
            return
        for device in self.env.devices_by_type(str(scope)):
            if metric in extra_metrics and device.id in extra_metrics[metric]:
                yield device.id, extra_metrics[metric][device.id]
                continue
            cell = self.env.read_measurement(device.id, metric)
            yield device.id, (cell["value"] if cell else None)

    def _worst_threshold(self, rule: dict, value: float):
        """取满足的最严重阈值（级别 P0 最重；同级别取先声明者）。"""
        worst = None
        for threshold in rule["thresholds"]:
            op = _OPS.get(str(threshold.get("op")))
            if op is None:
                continue
            bound = float(threshold["value"])
            if op(value, bound):
                level = str(threshold.get("level", "P3"))
                if worst is None or LEVEL_SEVERITY.get(level, 9) < LEVEL_SEVERITY.get(worst[0], 9):
                    worst = (level, str(threshold.get("name", "")), bound)
        return worst

    def _raise(self, rule: dict, subject: str, value: float, level: str, name: str,
               threshold_value: float, sim_elapsed_s: float) -> dict:
        alarm_id = self.env.next_alarm_id()
        occurred = self.env.iso_at(sim_elapsed_s)
        record = {
            "alarm_id": alarm_id,
            "level": level,
            "code": str(rule["id"]),
            "source_ref": subject,
            "metric": str(rule.get("metric", "")),
            "text": (f"{subject} {rule.get('title', rule['id'])}越限："
                     f"{name}（{rule.get('metric')}={value:.3f}，阈值 {threshold_value}）"),
            "raised_at": occurred,
            "cleared_at": None,
            "ack_by": None,
        }
        self.env.alarms[alarm_id] = record
        return record

    def _events_of(self, record: dict, *, raised: bool, sim_elapsed_s: float) -> list:
        if raised:
            event = self.env.emit(
                EventType.ALARM_RAISED, record["source_ref"],
                {"alarm_id": record["alarm_id"], "level": record["level"],
                 "rule": record["code"], "text": record["text"]},
                sim_elapsed_s,
            )
        else:
            record["cleared_at"] = self.env.iso_at(sim_elapsed_s)
            event = self.env.emit(
                EventType.ALARM_CLEARED, record["source_ref"],
                {"alarm_id": record["alarm_id"], "level": record["level"],
                 "rule": record["code"], "cleared_at": record["cleared_at"]},
                sim_elapsed_s,
            )
        return [event]
