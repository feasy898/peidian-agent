# -*- coding: utf-8 -*-
"""m1_core.gates · 阶段门禁（specs/M1-agent-core.md SPEC-M1-04 / §2）。

每阶段出口判定（§2 三条件；SPEC-M1-04 条款以产物为主判据）：
1. **产物齐全**：plan 中当前阶段 ``artifacts_expected`` 每项已存在且
   status ∈ {READY, PUBLISHED}（REJECTED/DRAFT/… 不算过门）；
2. **预算够**：token 与 action 租约均有余量（≥ floor）；
3. **无阻断告警**：任务事件流中存在未清除的阻断级告警（缺省 P0）则拦停。

不满足 → 停留当前阶段，产出明确 gap 清单（:func:`build_gap_todos` 写入 todos）。

匹配口径（数据驱动）：``artifacts_expected`` 条目按 **artifact_id 精确匹配或
schema_id 匹配**（计划先于产物存在，ULID 无法预知——按内容 schema 声明是计划
的自然写法；两口径同时支持，不针对特定实例硬编码）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

__all__ = [
    "GATE_PASS_STATUSES",
    "GateResult",
    "evaluate_stage_gate",
    "active_blocking_alarms",
]

#: 过门允许的产物状态（SPEC-M1-04：已存在且 status ∈ {READY, PUBLISHED}）
GATE_PASS_STATUSES: tuple[str, ...] = ("READY", "PUBLISHED")

#: 环境事件主题（Observe/门禁的告警阻断判定数据源，01 §4）
_ALARM_RAISED = "alarm.raised"
_ALARM_CLEARED = "alarm.cleared"


@dataclass
class GateResult:
    """阶段门禁评估结论。"""

    stage: str
    gate: str
    passed: bool
    missing_artifacts: list = field(default_factory=list)   # [{ref, reason, status}]
    budget_ok: bool = True
    budget_detail: str = ""
    blocking_alarms: list = field(default_factory=list)     # [{alarm_id, level, code}]
    gaps: list = field(default_factory=list)                # gap todos（SPEC-M1-04）
    reasons: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "stage": self.stage, "gate": self.gate, "passed": self.passed,
            "missing_artifacts": self.missing_artifacts, "budget_ok": self.budget_ok,
            "budget_detail": self.budget_detail, "blocking_alarms": self.blocking_alarms,
            "gaps": self.gaps, "reasons": self.reasons,
        }


def active_blocking_alarms(task_events: Iterable[Mapping],
                           blocking_levels: Iterable[str] = ("P0",)) -> list[dict]:
    """从任务事件流提取未清除的阻断级告警（raised 未被后续 cleared 抵消）。"""
    levels = {str(x) for x in blocking_levels}
    active: dict[str, dict] = {}
    for event in task_events:
        etype = str(event.get("type", ""))
        payload = event.get("payload") or {}
        if etype == _ALARM_RAISED and str(payload.get("level", "")) in levels:
            active[str(event.get("subject", ""))] = {
                "alarm_id": str(event.get("subject", "")),
                "level": str(payload.get("level", "")),
                "code": str(payload.get("code", "")),
            }
        elif etype == _ALARM_CLEARED:
            active.pop(str(event.get("subject", "")), None)
    return sorted(active.values(), key=lambda a: a["alarm_id"])


def evaluate_stage_gate(
    state: Any,
    *,
    artifact_lookup: Callable[[str], Mapping | None],
    task_events: Iterable[Mapping] | None = None,
    blocking_levels: Iterable[str] = ("P0",),
    token_floor: int = 1,
    action_floor: int = 1,
) -> GateResult:
    """评估当前阶段出口门禁。

    ``artifact_lookup(ref)``：按 ref（artifact_id 或 schema_id）查任务产物记录
    （返回含 ``status`` 的映射或 None——由 AgentCore 注入 M2 查询）。
    """
    from . import planner

    steps = planner.plan_steps(state)
    current = str(getattr(state, "current_stage", "") or "")
    step = next((s for s in steps if s["stage"] == current), None)
    if step is None:
        # 当前阶段不在 plan：无门禁可评（空 plan / 阶段名漂移），视为通过
        return GateResult(stage=current, gate="", passed=True)

    missing: list[dict] = []
    for ref in step["artifacts_expected"]:
        record = artifact_lookup(ref)
        if record is None:
            missing.append({"ref": ref, "reason": "产物不存在", "status": None})
            continue
        status = str(record.get("status", ""))
        if status not in GATE_PASS_STATUSES:
            missing.append({
                "ref": ref, "reason": f"状态 {status} 不在 {'/'.join(GATE_PASS_STATUSES)}",
                "status": status,
            })

    budget = getattr(state, "budget", None)
    token_left = int(budget.token_max) - int(budget.token_used) if budget else 0
    action_left = int(budget.action_max) - int(budget.action_used) if budget else 0
    budget_ok = token_left >= int(token_floor) and action_left >= int(action_floor)
    budget_detail = f"token 余 {max(token_left, 0)} / action 余 {max(action_left, 0)}"

    alarms = active_blocking_alarms(task_events or [], blocking_levels)

    reasons: list[str] = []
    if missing:
        reasons.append("产物缺口 " + "; ".join(
            f"{m['ref']}({m['reason']})" for m in missing))
    if not budget_ok:
        reasons.append(f"预算不足（{budget_detail}）")
    if alarms:
        reasons.append("阻断告警 " + "; ".join(
            f"{a['alarm_id']}({a['level']})" for a in alarms))

    extra_reasons: list[str] = []
    if not budget_ok:
        extra_reasons.append(f"预算不足：{budget_detail}")
    for alarm in alarms:
        extra_reasons.append(f"阻断告警 {alarm['alarm_id']}（{alarm['level']}）未清除")

    gaps = planner.build_gap_todos(step["stage"], missing, extra_reasons)

    return GateResult(
        stage=step["stage"], gate=step["gate"],
        passed=not missing and budget_ok and not alarms,
        missing_artifacts=missing, budget_ok=budget_ok, budget_detail=budget_detail,
        blocking_alarms=alarms, gaps=gaps, reasons=reasons,
    )
