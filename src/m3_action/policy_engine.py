# -*- coding: utf-8 -*-
"""m3_action.policy_engine · Policy 三值判定（ALLOW/ASK/DENY，SPEC-M3-04/05/06）。

规则（00§1.3 动作表缺省 Policy + 00§1.4 R-授权规则）：
- 判定输入=动作缺省 Policy（ontology/actions.yaml 数据）+ 角色覆盖表；
- **每次请求必出 ``action.policy_decided`` 事件**（gateway 在请求路径调用 emit）；
- 不可改清单（硬编码于 registry.IMMUTABLE_DENY_ACTIONS / PERMANENT_ASK_ACTIONS）：
  三个 CRITICAL 动作 DENY 永久、``execute.remote_control`` ASK 永久——任何角色/
  审批均不可翻转；审批只放行"本次"（approval 消费一次性条目），不改缺省；
- 角色覆盖只能收紧（ALLOW→ASK / ALLOW→DENY / ASK→DENY 单向合法；放宽一律拒绝
  且判定维持缺省；policy_locked 动作任何覆盖都被拒绝并落审计事件）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from contracts import EventType, PolicyDecision

from .registry import (
    IMMUTABLE_DENY_ACTIONS,
    PERMANENT_ASK_ACTIONS,
)

__all__ = ["PolicyEngine", "PolicyVerdict", "TIGHTEN_STEPS", "is_tightening"]

#: 单向收紧合法集（SPEC-M3-06：收紧方向单向，放宽禁止）
TIGHTEN_STEPS = frozenset({
    (PolicyDecision.ALLOW, PolicyDecision.ASK),
    (PolicyDecision.ALLOW, PolicyDecision.DENY),
    (PolicyDecision.ASK, PolicyDecision.DENY),
})


def is_tightening(base: PolicyDecision, target: PolicyDecision) -> bool:
    """target 是否为 base 的合法收紧（相等视为无操作，不属收紧也不属放宽）。"""
    if base is target:
        return False
    return (base, target) in TIGHTEN_STEPS


@dataclass
class PolicyVerdict:
    """三值判定结论（含判定依据，进 ``action.policy_decided`` payload）。"""

    decision: PolicyDecision
    base: PolicyDecision
    action_id: str
    actor_role: str | None
    locked: bool
    override_applied: bool = False
    override_rejected: bool = False
    reason: str = ""

    def payload(self) -> dict:
        return {
            "decision": self.decision.value,
            "base": self.base.value,
            "capability_action": self.action_id,
            "actor_role": self.actor_role,
            "locked": self.locked,
            "override_applied": self.override_applied,
            "override_rejected": self.override_rejected,
            "reason": self.reason,
        }


class PolicyEngine:
    """三值判定引擎（无状态判定 + 角色覆盖表管理；事件经 emit 回调外发）。"""

    def __init__(
        self,
        actions: Mapping[str, Mapping],
        role_overrides: Mapping[str, Mapping[str, PolicyDecision | str]] | None = None,
        *,
        emit: Callable[..., dict] | None = None,
    ) -> None:
        """``actions``：action_id → {default_policy, policy_locked}（数据驱动）。"""
        self._actions = {aid: {"default_policy": PolicyDecision(str(a.get("default_policy"))),
                               "policy_locked": bool(a.get("policy_locked", False))}
                         for aid, a in actions.items()}
        self._overrides: dict[str, dict[str, PolicyDecision]] = {}
        self._emit = emit
        for role, mapping in (role_overrides or {}).items():
            for action_id, decision in (mapping or {}).items():
                verdict = self.set_role_override(role, action_id, decision, record_event=False)
                if not verdict.get("accepted", False):
                    raise ValueError(
                        f"初始角色覆盖非法: role={role} action={action_id}"
                        f" decision={decision} reason={verdict.get('reason')}")

    # -------------------------------------------------- 判定
    def decide(self, action_id: str, actor_role: str | None,
               *, record_event: bool = True, subject: str = "") -> PolicyVerdict:
        """三值判定（每次请求必出判定事件——record_event=False 仅限内部复核）。"""
        action = self._actions.get(action_id)
        if action is None:
            verdict = PolicyVerdict(
                decision=PolicyDecision.DENY, base=PolicyDecision.DENY,
                action_id=action_id, actor_role=actor_role, locked=True,
                reason="动作不在授权规则表内（按 DENY 处置，红线 1）")
            if record_event:
                self._emit_event(verdict, subject)
            return verdict
        base = action["default_policy"]
        locked = action["policy_locked"] or action_id in IMMUTABLE_DENY_ACTIONS \
            or action_id in PERMANENT_ASK_ACTIONS
        override = (self._overrides.get(actor_role or "", {}) or {}).get(action_id) \
            if actor_role else None
        if locked and override is not None:
            verdict = PolicyVerdict(
                decision=base, base=base, action_id=action_id, actor_role=actor_role,
                locked=True, override_applied=False, override_rejected=True,
                reason=f"缺省 Policy={base.value} 为系统级不可覆盖（审批只放行单次）")
        elif override is not None:
            verdict = PolicyVerdict(
                decision=override, base=base, action_id=action_id, actor_role=actor_role,
                locked=False, override_applied=True,
                reason=f"角色覆盖收紧 {base.value}→{override.value}（单向收紧合法）")
        else:
            verdict = PolicyVerdict(
                decision=base, base=base, action_id=action_id, actor_role=actor_role,
                locked=locked,
                reason="缺省 Policy（00§1.3 动作表）" if not locked
                else f"缺省 Policy={base.value} 不可覆盖（永久）")
        if record_event:
            self._emit_event(verdict, subject)
        return verdict

    # -------------------------------------------------- 角色覆盖（SPEC-M3-06）
    def set_role_override(self, role: str, action_id: str, decision: PolicyDecision | str,
                          *, record_event: bool = True) -> dict:
        """配置角色覆盖：只能收紧；policy_locked 动作任何覆盖拒绝；尝试即落审计事件。

        返回 {accepted, base, requested, effective, reason}。
        """
        target = decision if isinstance(decision, PolicyDecision) \
            else PolicyDecision(str(decision))
        action = self._actions.get(action_id)
        if action is None:
            return self._override_audit(role, action_id, target, accepted=False,
                                        reason=f"动作不在授权规则表内: {action_id!r}",
                                        record_event=record_event)
        base = action["default_policy"]
        locked = action["policy_locked"] or action_id in IMMUTABLE_DENY_ACTIONS \
            or action_id in PERMANENT_ASK_ACTIONS
        if locked:
            return self._override_audit(
                role, action_id, target, accepted=False, base=base, effective=base,
                reason=(f"{action_id} 缺省 Policy={base.value} 为系统级不可覆盖"
                        "（不可改清单，SPEC-M3-05）"),
                record_event=record_event)
        # 收紧基准=当前生效判定（已存覆盖优先于缺省）——对已收紧角色的"放宽回缺省"
        # 同样属于放宽（ASK→ALLOW），必须拒绝（SPEC-M3-06 单向收紧）
        current = (self._overrides.get(role) or {}).get(action_id, base)
        if current is target:
            return self._override_audit(
                role, action_id, target, accepted=True, base=base, effective=current,
                reason="覆盖与当前生效判定一致（无操作）", record_event=record_event)
        if not is_tightening(current, target):
            return self._override_audit(
                role, action_id, target, accepted=False, base=base, effective=current,
                reason=(f"角色覆盖只能收紧（{current.value}→{target.value} 为放宽/非法方向，"
                        "SPEC-M3-06 单向收紧）"),
                record_event=record_event)
        self._overrides.setdefault(role, {})[action_id] = target
        return self._override_audit(
            role, action_id, target, accepted=True, base=base, effective=target,
            reason=f"覆盖收紧 {current.value}→{target.value} 生效", record_event=record_event)

    def effective_overrides(self) -> dict:
        return {role: {a: d.value for a, d in mapping.items()}
                for role, mapping in self._overrides.items()}

    # -------------------------------------------------- 事件
    def _override_audit(self, role: str, action_id: str, target: PolicyDecision, *,
                        accepted: bool, base: PolicyDecision | None = None,
                        effective: PolicyDecision | None = None,
                        reason: str, record_event: bool) -> dict:
        outcome = {
            "accepted": accepted,
            "role": role,
            "action_id": action_id,
            "base": None if base is None else base.value,
            "requested": target.value,
            "effective": (effective or base or PolicyDecision.DENY).value,
            "reason": reason,
        }
        if record_event:
            verdict = PolicyVerdict(
                decision=effective or base or PolicyDecision.DENY,
                base=base or PolicyDecision.DENY,
                action_id=action_id, actor_role=role,
                locked=not accepted,
                override_applied=accepted and base is not target,
                override_rejected=not accepted,
                reason=f"角色覆盖尝试: {reason}")
            self._emit_event(verdict, subject=f"policy:{role}")
        return outcome

    def _emit_event(self, verdict: PolicyVerdict, subject: str) -> None:
        if self._emit is None:
            return
        self._emit(EventType.ACTION_POLICY_DECIDED.value, subject or verdict.action_id,
                   verdict.payload())
