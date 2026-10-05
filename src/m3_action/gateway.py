# -*- coding: utf-8 -*-
"""m3_action.gateway · Action Gateway 门面（01 §3.3 冻结 API 的实现载体）。

冻结接口：
- ``register_capability(capability: CapabilityDescriptor) -> CapabilityId``
- ``execute_action(request: ActionRequest) -> ActionResult``（同步边界；
  内部路由 mode ∈ {REAL, SIMULATION}；SIMULATION → M5.simulate()）
- ``query_policy(capability, actor, context) -> PolicyDecision``
- ``submit_approval(action_id, decision: GRANT/DENY, approver) -> ActionResult``

幂等规则：同 idempotency_key 重复请求返回首个结果（含原 action_id），不重复执行；
审批终态（GRANT 执行完成/DENY 拒绝/超时）均回写幂等 journal——同 key 重试
返回终态结果而非过期的 WAITING_APPROVAL 中间态。

Action 生命周期（01 §5.2，表驱动，与 tests/fixtures/frozen_state_machines.yaml
必须 diff 为空——EVAL 断言）：REQUESTED → POLICY_DECIDED → (DENY→DENIED) |
(ASK→WAITING_APPROVAL) | (ALLOW→EXECUTING) → SUCCEEDED/FAILED；
WAITING_APPROVAL → EXECUTING(GRANT) | REJECTED(DENY/超时)。

准入失败（契约/注册/披露/schema/路由）不进事件主链：不落 action.requested，
仅落审计事件（action.policy_decided {decision: DENY, stage: <code>}，沿用 M2
先例——事件目录无独立 error.* 主题）；状态 REJECTED。
"""
from __future__ import annotations

import copy as _copy
from pathlib import Path
from typing import Any, Mapping

from contracts import (
    ActionRequest,
    ActionResult,
    ContractValidationError,
    EventType,
    PolicyDecision,
)

from .approval import DEFAULT_APPROVAL_TIMEOUT_S, ApprovalQueue
from .clocking import normalize_ts, now_iso, to_jsonable
from .events import EventJournal
from .executor import IdempotencyConflictError, IdempotentExecutor
from .observer import Observer
from .policy_engine import PolicyEngine
from .registry import (
    CapabilityDescriptor,
    CapabilityRegistry,
    default_repo_root,
    load_actions_table,
    load_default_registry,
)
from .router import MODE_SIMULATION, Router, RouterModeError
from .validator import RequestValidator, ValidationOutcome

__all__ = ["ActionGateway", "IllegalTransitionError", "ACTION_TRANSITIONS"]

#: Action 生命周期迁移表（01 §5.2 表驱动；COMPENSATED 为条件迁移不进无条件表）
ACTION_TRANSITIONS: dict[str, list[str]] = {
    "REQUESTED": ["POLICY_DECIDED"],
    "POLICY_DECIDED": ["DENIED", "WAITING_APPROVAL", "EXECUTING"],
    "WAITING_APPROVAL": ["EXECUTING", "REJECTED"],
    "EXECUTING": ["SUCCEEDED", "FAILED"],
    "FAILED": ["COMPENSATED"],  # conditional：reversible 且有 compensation（可选）
    "SUCCEEDED": [],
    "REJECTED": [],
    "DENIED": [],
    "COMPENSATED": [],
}


class IllegalTransitionError(ValueError):
    """非法 Action 生命周期迁移（01 §5.2）。"""


#: 终态（action.completed 只对终态发布）
_TERMINAL_ACTION_STATUSES = frozenset(
    {"SUCCEEDED", "FAILED", "REJECTED", "DENIED", "COMPENSATED"})


class ActionGateway:
    """行动网关（校验 → 三值判定 → 审批 → 隔离执行 → 观测回传，全链留痕）。"""

    def __init__(
        self,
        runtime_dir: Path | str | None = None,
        *,
        env: Any = None,
        evaluation: bool | None = None,
        approval_timeout_s: float = DEFAULT_APPROVAL_TIMEOUT_S,
        actor_roles: Mapping[str, str] | None = None,
        role_overrides: Mapping[str, Mapping[str, str]] | None = None,
        registry: CapabilityRegistry | None = None,
        repo_root: Path | str | None = None,
        isolate_execution_env: bool = False,
        dual_approvers: list | None = None,
        events_dir: Path | str | None = None,
    ) -> None:
        """``isolate_execution_env``：执行副作用落在环境深拷贝上（EVAL-M3-09 用——
        模拟"执行器自报成功但真实环境未变"的失联执行器，observer 必须降级）。
        ``events_dir``：事件流目录（缺省 runtime/events；EVAL 沙箱传入独立目录）。"""
        self.repo_root = Path(repo_root) if repo_root else default_repo_root()
        runtime = Path(runtime_dir) if runtime_dir else self.repo_root / "runtime" / "m3_action"
        self.runtime_dir = runtime
        self.env = env
        self.registry = registry or load_default_registry(self.repo_root)
        self.events = EventJournal(Path(events_dir) if events_dir
                                   else self.repo_root / "runtime" / "events")
        self.approvals = ApprovalQueue(runtime / "approvals.jsonl",
                                       timeout_s=approval_timeout_s)
        self.executor = IdempotentExecutor(
            runtime / "idempotency.jsonl",
            key_policy=lambda action_id: (
                (self.registry.by_action(action_id).idempotency_key_policy
                 if self.registry.by_action(action_id) else "CALLER_PROVIDED")))
        self.observer = Observer()
        self.router = Router(evaluation=evaluation, dual_approvers=dual_approvers)
        actions_table = load_actions_table(self.repo_root)
        self.policy = PolicyEngine(
            actions_table,
            role_overrides={r: dict(m) for r, m in (role_overrides or {}).items()},
            emit=self._emit_policy_event,
        )
        self.validator = RequestValidator(self.registry)
        self.actor_roles: dict[str, str] = dict(actor_roles or {})
        if not self.actor_roles and env is not None:
            self.actor_roles = {str(op.get("id")): str(op.get("role"))
                                for op in getattr(env, "operators", [])}
        self.isolate_execution_env = bool(isolate_execution_env)
        self.action_states: dict[str, list[str]] = {}
        self.action_executions: int = 0
        # 重启恢复：审批队列遗留的 WAITING_APPROVAL 动作续接生命周期
        for entry in self.approvals.pending():
            self.action_states.setdefault(entry.action_id, []).append("WAITING_APPROVAL")

    # =================================================================
    # 冻结 API（01 §3.3）
    # =================================================================
    def register_capability(self, capability: CapabilityDescriptor) -> str:
        """注册能力（运行期追加注册——存在性 ≠ 授权 ≠ 模型可见，SPEC-M3-01）。"""
        return self.registry.register_capability(capability)

    def query_policy(self, capability: str, actor: str | Mapping | None,
                     context: Mapping | None = None) -> PolicyDecision:
        """策略查询（纯判定，不执行、不落请求主链事件）。"""
        action_id = str(capability).split("@", 1)[0]
        role = self._role_of(actor)
        return self.policy.decide(action_id, role, record_event=False).decision

    def execute_action(self, request: ActionRequest | Mapping, *,
                       mode: str = MODE_SIMULATION, now: str | None = None,
                       trace_id: str | None = None) -> ActionResult:
        """执行动作（同步边界）。内部：准入 → 幂等 → 判定 → 审批/执行 → 观测。"""
        now = normalize_ts(now or now_iso())
        payload = request.to_dict() if isinstance(request, ActionRequest) else dict(request or {})
        role = self._role_of((payload.get("actor") or {}).get("user")
                             if isinstance(payload.get("actor"), Mapping) else None)

        # ---- 准入管线（失败不进主链，落审计事件，REJECTED）
        outcome = self.validator.validate(payload, actor_role=role)
        if not outcome.ok:
            return self._admission_rejected(outcome, payload, now)

        req = outcome.request
        action_id = req.action_id
        task_id = req.task_id
        trace = trace_id or f"trace-{task_id}"
        stream = self.events.task_stream(task_id)
        descriptor = self.registry.get(req.capability) or self.registry.by_action(
            req.capability.split("@", 1)[0])

        # ---- 路由解析（REAL 门禁在主链之前——被拒不进生命周期）
        try:
            resolved_mode = self.router.resolve(mode, descriptor)
        except RouterModeError as exc:
            failure = ValidationOutcome(
                request=req, action_id=action_id, error_code=exc.code,
                error_path="mode", message=exc.message, intended=outcome.intended)
            return self._admission_rejected(failure, payload, now, trace_id=trace)

        # ---- 幂等（同 key 返回首个结果，不重复执行）
        try:
            first_result, first_time = self.executor.claim(
                req.idempotency_key, action_id=action_id,
                capability=req.capability, arguments=req.arguments,
                pending_result=self._result_dict(
                    action_id, trace, "REQUESTED", outcome.intended,
                    observation="已受理（幂等 claim 已落盘）"))
        except IdempotencyConflictError as exc:
            failure = ValidationOutcome(
                request=req, action_id=action_id, error_code=exc.code,
                error_path="idempotency_key", message=str(exc), intended=outcome.intended)
            return self._admission_rejected(failure, payload, now, trace_id=trace)
        if not first_time:
            return self._as_result(first_result)  # 首个结果（含原 action_id/状态）

        # ---- 主链开始：action.requested + 状态机 REQUESTED
        self._transition(action_id, "REQUESTED")
        self.events.append(EventType.ACTION_REQUESTED.value, action_id,
                           {"capability": req.capability, "actor_user": req.actor.user,
                            "actor_role": role, "mode": resolved_mode,
                            "purpose": req.purpose},
                           trace_id=trace, occurred_at=normalize_ts(req.requested_at), stream=stream)

        # ---- Policy 三值判定（每次请求必出判定事件——落任务主链流）
        verdict = self.policy.decide(descriptor.action_id, role, record_event=False,
                                     subject=action_id)
        self._transition(action_id, "POLICY_DECIDED")
        self.events.append(EventType.ACTION_POLICY_DECIDED.value, action_id,
                           {**verdict.payload(), "task_id": task_id,
                            "capability": req.capability},
                           trace_id=trace, occurred_at=normalize_ts(req.requested_at), stream=stream)

        if verdict.decision is PolicyDecision.DENY:
            result = self._result_dict(
                action_id, trace, "DENIED", outcome.intended,
                observation=f"[POLICY_DENIED] {verdict.reason}",
                error={"code": "POLICY_DENIED", "message": verdict.reason})
            self._transition(action_id, "DENIED")
            return self._finish(result, req, trace, stream, now)

        if verdict.decision is PolicyDecision.ASK:
            entry = self.approvals.enqueue(
                action_id=action_id, task_id=task_id, capability=req.capability,
                trace_id=trace, requested_at=normalize_ts(req.requested_at), created_at=now,
                request=to_jsonable(req.to_dict()))
            self.events.append(EventType.ACTION_WAITING_APPROVAL.value, action_id,
                               {"capability": req.capability, "reason": verdict.reason,
                                "task_id": task_id, "timeout_s": entry.timeout_s},
                               trace_id=trace, occurred_at=now, stream=stream)
            self.events.append(EventType.APPROVAL_REQUESTED.value, action_id,
                               {"capability": req.capability, "task_id": task_id,
                                "timeout_s": entry.timeout_s, "requested_by": req.actor.user},
                               trace_id=trace, occurred_at=now, stream=stream)
            result = self._result_dict(
                action_id, trace, "WAITING_APPROVAL", outcome.intended,
                observation=(f"[WAITING_APPROVAL] {verdict.reason}；"
                             f"审批超时 {entry.timeout_s:.0f}s（approval.requested 已发布）"))
            self._transition(action_id, "WAITING_APPROVAL")
            return self._finish(result, req, trace, stream, now)

        # ALLOW → 执行
        return self._execute_admitted(req, descriptor, outcome.intended,
                                      resolved_mode, trace, stream, now)

    def submit_approval(self, action_id: str, decision: str, approver: str, *,
                        now: str | None = None) -> ActionResult:
        """审批决断（GRANT/DENY）——一次性消费；GRANT 只放行本次，不改缺省。"""
        now = normalize_ts(now or now_iso())
        entry = self.approvals.get(action_id)
        if entry is None:
            return self._as_result(self._result_dict(
                action_id, f"trace-{entry_task_unknown(action_id)}", "REJECTED",
                {"action_id": action_id}, observation="[NO_PENDING_APPROVAL] 无待审批条目",
                error={"code": "NO_PENDING_APPROVAL",
                       "message": f"动作 {action_id!r} 不在审批队列（已决断/超时/不存在）"}))
        trace = entry.trace_id
        stream = self.events.task_stream(entry.task_id)
        approver_role = self.actor_roles.get(str(approver))
        if approver_role != "审批人":
            # 审批权归属（HITL fail-closed）：仅实例已登记且角色=审批人 的人员可决断。
            # 未登记人员（角色 None）与实例未登记任何人员（actor_roles 为空）一律
            # 拒绝——审批权威无法建立时不得静默放行（00§1.4 R-授权规则）。
            if self.actor_roles:
                reason_msg = (f"审批人 {approver!r}（角色 {approver_role!r}）不是审批人")
            else:
                reason_msg = ("实例未登记操作员，审批权威不可建立（HITL fail-closed）"
                              f"——审批人 {approver!r} 请求被拒")
            self.events.append(EventType.APPROVAL_DENIED.value, action_id,
                               {"capability": entry.capability, "approver": approver,
                                "approver_role": approver_role,
                                "reason": "APPROVER_NOT_AUTHORIZED"},
                               trace_id=trace, occurred_at=now, stream=stream)
            result = self._result_dict(
                action_id, trace, "REJECTED", {"action_id": action_id},
                observation=f"[APPROVER_NOT_AUTHORIZED] {reason_msg}",
                error={"code": "APPROVER_NOT_AUTHORIZED",
                       "message": reason_msg})
            return self._as_result(result)

        decision = str(decision).upper()
        if decision not in ("GRANT", "DENY"):
            return self._as_result(self._result_dict(
                action_id, trace, "REJECTED", {"action_id": action_id},
                observation="[BAD_APPROVAL_DECISION] decision 必须 GRANT/DENY",
                error={"code": "BAD_APPROVAL_DECISION",
                       "message": f"decision 必须 GRANT/DENY，实际为 {decision!r}"}))

        resolved = self.approvals.resolve(action_id, decision, approver, at=now)
        req = ActionRequest.from_dict(resolved.request)
        descriptor = self.registry.get(req.capability) or \
            self.registry.by_action(req.capability.split("@", 1)[0])

        if decision == "DENY":
            self.events.append(EventType.APPROVAL_DENIED.value, action_id,
                               {"capability": entry.capability, "approver": approver,
                                "task_id": entry.task_id},
                               trace_id=trace, occurred_at=now, stream=stream)
            self._transition(action_id, "REJECTED", allow_from="WAITING_APPROVAL")
            result = self._result_dict(
                action_id, trace, "REJECTED",
                {"action_id": action_id, "capability": req.capability,
                 "arguments": dict(req.arguments)},
                observation="[APPROVAL_DENIED] 审批人拒绝",
                error={"code": "APPROVAL_DENIED", "message": f"审批人 {approver!r} 拒绝"})
            # 幂等 journal 回写终态：同 key 重试返回 REJECTED 而非过期 WAITING_APPROVAL
            return self._finish(result, req, trace, stream, now)

        # GRANT：只放行单次（policy 缺省不变——EVAL-M3-05 断言）
        self.events.append(EventType.APPROVAL_GRANTED.value, action_id,
                           {"capability": entry.capability, "approver": approver,
                            "task_id": entry.task_id, "single_shot": True},
                           trace_id=trace, occurred_at=now, stream=stream)
        return self._execute_admitted(
            req, descriptor,
            {"action_id": action_id, "capability": req.capability,
             "arguments": dict(req.arguments), "approved_by": approver},
            MODE_SIMULATION, trace, stream, now, from_approval=True)

    def check_approval_timeouts(self, now: str | None = None) -> list:
        """超时批量处置（SPEC-M3-07）：到期 → REJECTED(payload.timeout)+approval.timeout。"""
        now = normalize_ts(now or now_iso())
        results = []
        for entry in self.approvals.expire_due(now):
            trace = entry.trace_id
            stream = self.events.task_stream(entry.task_id)
            self.events.append(EventType.APPROVAL_TIMEOUT.value, entry.action_id,
                               {"capability": entry.capability,
                                "task_id": entry.task_id,
                                "timeout": True,
                                "waited_s": round(entry.waited_s(now), 1),
                                "timeout_s": entry.timeout_s},
                               trace_id=trace, occurred_at=now, stream=stream)
            self._transition(entry.action_id, "REJECTED", allow_from="WAITING_APPROVAL")
            result = self._result_dict(
                entry.action_id, trace, "REJECTED",
                {"action_id": entry.action_id, "capability": entry.capability,
                 "arguments": dict((entry.request or {}).get("arguments") or {})},
                observation=(f"[APPROVAL_TIMEOUT] 审批超时 "
                             f"（等待 {entry.waited_s(now):.0f}s ≥ {entry.timeout_s:.0f}s）"),
                error={"code": "APPROVAL_TIMEOUT",
                       "message": f"审批超时（{entry.timeout_s:.0f}s 无响应）"})
            result["timeout"] = True  # payload.timeout（SPEC-M3-07）
            req = None
            try:
                req = ActionRequest.from_dict(entry.request)
            except ContractValidationError:  # pragma: no cover - 入队前已过契约
                pass
            # 幂等 journal 回写终态：同 key 重试返回 REJECTED/timeout 而非过期 WAITING_APPROVAL
            results.append(self._finish(result, req, trace, stream, now))
        return results

    # =================================================================
    # 内部：执行 / 状态机 / 事件
    # =================================================================
    def _execute_admitted(self, req: ActionRequest, descriptor: CapabilityDescriptor,
                          intended: dict, resolved_mode: str, trace: str, stream: str,
                          now: str, *, from_approval: bool = False) -> ActionResult:
        action_id = req.action_id
        self._transition(action_id, "EXECUTING")
        self.events.append(EventType.ACTION_EXECUTING.value, action_id,
                           {"capability": req.capability, "mode": resolved_mode,
                            "from_approval": from_approval},
                           trace_id=trace, occurred_at=now, stream=stream)

        exec_result: dict | None = None
        if descriptor.adapter is None:
            exec_result = {"status": "FAILED",
                           "error": {"code": "ADAPTER_MISSING",
                                     "message": f"能力 {req.capability} 无执行适配器"},
                           "evidence": {"intended": intended, "issued": None,
                                        "observed": None},
                           "result_refs": []}
        elif resolved_mode == "REAL":
            exec_result = descriptor.adapter.execute_real(req, ctx={
                "runtime_dir": str(self.runtime_dir), "now": now})
            self.executor.mark_executed()
        else:
            execution_env = self.env.deep_copy() if (self.isolate_execution_env
                                                     and self.env is not None) else self.env
            if execution_env is None:
                exec_result = {"status": "FAILED",
                               "error": {"code": "NO_SIMULATION_ENV",
                                         "message": "SIMULATION 路由需要 M5 SimEnv（未注入）"},
                               "evidence": {"intended": intended, "issued": None,
                                            "observed": None},
                               "result_refs": []}
            else:
                exec_result = descriptor.adapter.execute_sim(req, execution_env)
                self.executor.mark_executed()

        # 观测回传：observed 只认环境回读（不信执行器自报，SPEC-M3-09）
        observed = None
        if self.env is not None:
            observed = self.observer.readback(descriptor.adapter, self.env,
                                              dict(req.arguments), action_id)
        verify_ok = self.observer.verify(descriptor.adapter, dict(req.arguments),
                                         (exec_result or {}).get("evidence", {}).get("issued"),
                                         observed)
        result = self.observer.assemble(
            action_id=action_id, trace_id=trace, intended=intended,
            exec_result=exec_result, observed=observed, verify_ok=verify_ok,
            latency_ms=int((exec_result or {}).get("latency_ms", 0)))

        self._transition(action_id, result["status"])
        return self._finish(result, req, trace, stream, now)

    def _finish(self, result: dict, req: ActionRequest | None, trace: str,
                stream: str, now: str) -> ActionResult:
        """幂等完成 + action.completed 事件 + ActionResult 契约化。"""
        if req is not None:
            self.executor.complete(req.idempotency_key, result)
        self._complete_action(result, req, trace, stream, now)
        return self._as_result(result)

    def _complete_action(self, result: dict, req: ActionRequest | None, trace: str,
                         stream: str, now: str) -> None:
        """落 action.completed {status}（仅终态——非终态等待审批不构成 completed）。"""
        if result["status"] not in _TERMINAL_ACTION_STATUSES:
            return
        payload = {"status": result["status"],
                   "task_id": req.task_id if req is not None else None,
                   "capability": (req.capability if req is not None else None)}
        if result.get("timeout"):
            payload["timeout"] = True
        if result.get("error"):
            payload["error_code"] = result["error"]["code"]
        self.events.append(EventType.ACTION_COMPLETED.value, result["action_id"], payload,
                           trace_id=trace, occurred_at=now, stream=stream)

    def _admission_rejected(self, outcome: ValidationOutcome, payload: Mapping,
                            now: str, trace_id: str | None = None) -> ActionResult:
        """准入失败：不进主链（无 action.requested），落审计事件 + REJECTED。"""
        task_id = str(payload.get("task_id") or "unknown") if isinstance(payload, Mapping) \
            else "unknown"
        trace = trace_id or f"trace-{task_id}"
        # 审计事件（事件目录无 error.* 主题——沿用 M2 先例落 policy_decided DENY 审计）
        self.events.append(
            EventType.ACTION_POLICY_DECIDED.value, task_id,
            {"decision": "DENY", "stage": "admission",
             "error_code": outcome.error_code, "error_path": outcome.error_path,
             "message": outcome.message[:200],
             "capability": (payload.get("capability") if isinstance(payload, Mapping)
                            else None)},
            trace_id=trace, occurred_at=now,
            stream=self.events.task_stream(task_id))
        action_id = outcome.request.action_id if outcome.request is not None \
            else str(payload.get("action_id") or "unknown")
        message = outcome.message
        if outcome.error_path and not message.startswith(outcome.error_path) \
                and f"[{outcome.error_path}]" not in message:
            message = f"{outcome.error_path}: {message}"
        return self._as_result(self._result_dict(
            action_id, trace, "REJECTED", outcome.intended,
            observation=f"[{outcome.error_code}] {message}",
            error={"code": outcome.error_code, "message": message}))

    def _emit_policy_event(self, event_type: str, subject: str, payload: dict) -> None:
        """PolicyEngine 事件回调（角色覆盖审计事件：无任务上下文 → 审计流）。"""
        self.events.append(event_type, subject, payload,
                           trace_id=f"trace-policy-{subject}")

    # -------------------------------------------------- 状态机
    def _transition(self, action_id: str, to_state: str, *,
                    allow_from: str | None = None) -> None:
        history = self.action_states.setdefault(action_id, [])
        current = history[-1] if history else None
        if allow_from is not None:
            if current != allow_from:
                raise IllegalTransitionError(
                    f"动作 {action_id}: 期望来自 {allow_from}，实际当前 {current!r}")
        elif current is not None:
            allowed = ACTION_TRANSITIONS.get(current, [])
            if to_state not in allowed:
                raise IllegalTransitionError(
                    f"动作 {action_id}: {current} → {to_state} 不在 01§5.2 迁移表"
                    f"（允许: {'/'.join(allowed) or '终态只读'}）")
        history.append(to_state)

    # -------------------------------------------------- 杂项
    def _role_of(self, actor: str | Mapping | None) -> str | None:
        if actor is None:
            return None
        if isinstance(actor, Mapping):
            user = str(actor.get("user", ""))
            if actor.get("role"):
                return str(actor["role"])
            return self.actor_roles.get(user)
        return self.actor_roles.get(str(actor))

    @staticmethod
    def _result_dict(action_id: str, trace_id: str, status: str, intended: dict, *,
                     observation: str, error: dict | None = None,
                     error_path: str | None = None) -> dict:
        # ActionError 契约只含 code/message（01 §2.2）——错误路径并入 message（可见）
        if error is not None and error_path:
            error = {**error, "message": f"{error_path}: {error['message']}"}
        return {
            "action_id": action_id, "status": status, "result_refs": [],
            "observation": observation,
            "evidence": {"intended": intended, "issued": None, "observed": None},
            "latency_ms": 0, "trace_id": trace_id, "error": error,
        }

    @staticmethod
    def _as_result(result: dict) -> ActionResult:
        payload = {k: v for k, v in result.items() if k != "timeout"}
        payload.setdefault("result_refs", [])
        return ActionResult.from_dict(payload)

    def events_of(self, task_id: str) -> list:
        return self.events.read(self.events.task_stream(task_id))

    def decision_of(self, action_id: str) -> str | None:
        for event in self.events.read_all():
            if event.get("subject") == action_id \
                    and event.get("type") == EventType.ACTION_POLICY_DECIDED.value \
                    and (event.get("payload") or {}).get("stage") != "admission":
                return (event["payload"] or {}).get("decision")
        return None

    def action_history(self, action_id: str) -> list:
        return list(self.action_states.get(action_id, []))


def entry_task_unknown(action_id: str) -> str:  # pragma: no cover - 审计兜底
    return f"unknown-{action_id}"
