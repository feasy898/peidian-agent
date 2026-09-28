# -*- coding: utf-8 -*-
"""m1_core.budget · 预算检查点（specs/M1-agent-core.md SPEC-M1-05）。

每轮 Loop 头部（Prepare）检查 Budget Lease 四类口径，任一超限 → 立即 PAUSED +
``budget.exhausted {kind}`` 事件；PAUSED 恢复必须经 ResumeEvent（loop 守卫）。

四类口径（01 §2.3 TaskState.budget）：
- ``token``：token_used ≥ token_max（租约耗尽，无余量进入下一轮模型调用）；
- ``action``：action_used ≥ action_max；
- ``deadline``：deadline 已过（now > deadline）；
- ``price_window``：now 不在 [from, to] 时段内（成本窗口约束——比较基准一律
  由调用方注入的 ``now``，本模块**不读任何真实时钟**；电价判定属 M5 BUSINESS
  时钟域，与此处无关）。

时间纪律：本文件含成本窗口词面，禁止出现任何真实时间源读取（CI 墙钟扫描口径，
EVAL-M5-02-N 同源）；``now`` 一律为入参。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .clocking import parse_iso

__all__ = [
    "BUDGET_KINDS",
    "BudgetCheck",
    "check_budget",
    "budget_remaining",
    "budget_warning_level",
]

#: 超限类别（01 §4 budget.exhausted {kind}）
BUDGET_KINDS: tuple[str, ...] = ("token", "action", "deadline", "price_window")


@dataclass
class BudgetCheck:
    """预算检查结论（ok=True 可继续；exceeded=True 任一超限）。"""

    ok: bool
    exceeded: bool
    kind: str | None = None
    detail: str = ""
    exceeded_kinds: tuple = ()

    def to_dict(self) -> dict:
        return {"ok": self.ok, "exceeded": self.exceeded, "kind": self.kind,
                "detail": self.detail, "exceeded_kinds": list(self.exceeded_kinds)}


def _budget_mapping(budget: Any) -> Mapping:
    if isinstance(budget, Mapping):
        return budget
    if hasattr(budget, "to_dict"):
        data = budget.to_dict()
        if isinstance(data, Mapping):
            return data
    # contracts.Budget（dataclass，无 to_dict）→ 契约字段名映射
    if all(hasattr(budget, key) for key in
           ("token_max", "token_used", "action_max", "action_used")):
        window = getattr(budget, "price_window", None)
        return {
            "token_max": budget.token_max, "token_used": budget.token_used,
            "action_max": budget.action_max, "action_used": budget.action_used,
            "deadline": getattr(budget, "deadline", None),
            "price_window": None if window is None else {
                "from": getattr(window, "from_ts", None),
                "to": getattr(window, "to_ts", None)},
        }
    raise TypeError(f"budget 必须是映射或 Budget 结构，实际 {type(budget).__name__}")


def check_budget(budget: Any, *, now: str) -> BudgetCheck:
    """检查预算租约（任一超限即 exceeded；按 KINDS 顺序报告首个 kind）。

    ``now``：UTC ISO-8601 当前时刻（调用方注入——EVAL 确定性重放；生产缺省
    由 AgentCore 的 now_fn 提供）。
    """
    data = _budget_mapping(budget)
    token_used, token_max = int(data.get("token_used", 0)), int(data.get("token_max", 0))
    action_used, action_max = int(data.get("action_used", 0)), int(data.get("action_max", 0))

    exceeded: list[tuple[str, str]] = []
    if token_max > 0 and token_used >= token_max:
        exceeded.append(("token", f"token_used={token_used} ≥ token_max={token_max}"))
    if action_max > 0 and action_used >= action_max:
        exceeded.append(("action", f"action_used={action_used} ≥ action_max={action_max}"))
    deadline = data.get("deadline")
    if deadline:
        if parse_iso(str(now)) > parse_iso(str(deadline)):
            exceeded.append(("deadline", f"now={now} 已过 deadline={deadline}"))
    window = data.get("price_window") or None
    if window:
        if isinstance(window, Mapping):
            win_from, win_to = window.get("from"), window.get("to")
        else:
            win_from, win_to = getattr(window, "from_ts", None), getattr(window, "to_ts", None)
        if win_from and win_to:
            moment = parse_iso(str(now))
            if not (parse_iso(str(win_from)) <= moment <= parse_iso(str(win_to))):
                exceeded.append(("price_window", f"now={now} 不在 [{win_from}, {win_to}] 内"))

    if not exceeded:
        return BudgetCheck(ok=True, exceeded=False, kind=None, detail="预算充足")
    kind, detail = exceeded[0]
    return BudgetCheck(ok=False, exceeded=True, kind=kind, detail=detail,
                       exceeded_kinds=tuple(k for k, _ in exceeded))


def budget_remaining(budget: Any) -> dict:
    """token/action 租约余量。"""
    data = _budget_mapping(budget)
    return {
        "token": int(data.get("token_max", 0)) - int(data.get("token_used", 0)),
        "action": int(data.get("action_max", 0)) - int(data.get("action_used", 0)),
    }


def budget_warning_level(budget: Any, ratio: float = 0.2) -> dict:
    """预算预警档位（remaining/max < ratio → warning；SPEC-M1-05 伴随事件用）。"""
    data = _budget_mapping(budget)
    out = {}
    for kind, used_key, max_key in (("token", "token_used", "token_max"),
                                    ("action", "action_used", "action_max")):
        used, top = int(data.get(used_key, 0)), int(data.get(max_key, 0))
        remaining = top - used
        out[kind] = {
            "remaining": remaining,
            "warning": top > 0 and remaining >= 0 and remaining / top < float(ratio),
        }
    return out
