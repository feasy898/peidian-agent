# -*- coding: utf-8 -*-
"""m1_core.loop · Agent Loop 五阶段执行内核（specs/M1-agent-core.md）。

每轮严格 ``Prepare → Model → Act → Observe → Verify``（SPEC-M1-01）：

- **Prepare**：权威状态读取（M2，SPEC-M1-03）→ 预算检查点（SPEC-M1-05，
  任一超限 → PAUSED + budget.exhausted，**本轮不进 Model**）→ 上下文编译（M2）；
- **Model**：统一模型客户端调用（model_client）；每轮调用后成本写
  TaskState.budget 与事件流 cost 字段（SPEC-M1-10）；
- **Act**：tool_calls 逐个经 M3 网关执行（ActionRequest 通道；绑定 DONE todo
  的动作跳过——幂等续跑 SPEC-M1-09）；
- **Observe**：只接受 ActionResult.observation 与环境事件（M2 事件流，
  SPEC-M1-07）；SUCCEEDED 证据落 evidence/，产物策略落 M2 ArtifactRecord；
- **Verify**：todo 更新（DONE 粘滞）→ 阶段门禁（SPEC-M1-04，gap 写 todos）→
  完成申请判定（SPEC-M1-06，申请与判定分离）→ 轮末等待态迁移。

冻结 API（01 §3.1）：run_task / resume_task / request_completion；
run_loop 为规格 §2 的循环驱动入口（WAITING_*/PAUSED 必须经 resume_task）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from contracts import ActionRequest, TaskState
from contracts.base import asdict_plain

from .budget import check_budget
from .clocking import now_iso, normalize_ts
from .completion import (
    CompletionClaim,
    CompletionVerifier,
    CompletionVerdict,
    claim_fingerprint,
)
from .gates import evaluate_stage_gate
from .ids import new_ulid
from .middleware import Middleware, MiddlewareChain, TurnContext, default_middlewares
from .model_client import ModelClient
from . import planner
from .planner import apply_todo_updates, merge_gap_todos, next_stage
from .state_machine import (
    TASK_TRANSITIONS,
    TERMINAL_STATUSES,
    CompletionRequiredError,
    IllegalTransitionError,
    TaskStateMachine,
)
from .trace import LoopTrace, validate_replay

__all__ = [
    "AgentCore",
    "TaskContext",
    "ResumeEvent",
    "ResumeKind",
    "LoopNotResumableError",
    "LoopError",
    "DEFAULT_ARTIFACT_POLICY",
    "TASK_TRANSITIONS",
    "IllegalTransitionError",
    "CompletionRequiredError",
]

#: ResumeEvent 种类（01 §3.1）
ResumeKind = ("USER_INPUT", "APPROVAL_GRANTED", "APPROVAL_DENIED", "ENV_EVENT", "TIMEOUT")

#: 各等待态接受的 ResumeEvent（其余拒绝——LoopNotResumableError）
_RESUME_RULES: dict[str, tuple[str, ...]] = {
    "PAUSED": ResumeKind,
    "WAITING_INPUT": ("USER_INPUT",),
    "WAITING_APPROVAL": ("APPROVAL_GRANTED", "APPROVAL_DENIED", "TIMEOUT"),
    "WAITING_EVENT": ("ENV_EVENT",),
    "VERIFYING": ("USER_INPUT", "ENV_EVENT", "TIMEOUT"),
}

#: 环境事件主题（Observe 数据源，01 §4：环境/告警/量测/电价时钟）
_ENV_EVENT_TYPES = (
    "alarm.raised", "alarm.cleared", "measurement.updated", "grid.event",
    "price.period_changed", "demand.month_rolled",
)

#: 产物策略：SUCCEEDED 动作 → M2 ArtifactRecord（数据驱动，可注入覆盖）
DEFAULT_ARTIFACT_POLICY: dict[str, dict] = {
    "write.report": {
        "artifact_type": "REPORT",
        "schema_id": "report.daily@v1",
        "content_sections": ["devices", "measurements", "conclusion", "regulation_refs"],
    },
}


class LoopError(RuntimeError):
    """执行内核错误基类。"""


class LoopNotResumableError(LoopError):
    """任务处于等待/暂停态但未提供（或提供了不匹配的）ResumeEvent。"""


@dataclass
class TaskContext:
    """run_task 的任务上下文（计划/预算/执行者/模型脚本等，全量数据驱动）。"""

    task_id: str
    actor_user: str = "OP-001"
    actor_agent: str = "park-agent@v1"
    trace_id: str = ""
    plan: list | None = None
    todos: list | None = None
    budget: dict | None = None
    current_stage: str = "INTAKE"
    max_turns: int = 8
    model_script: list | None = None      # mock provider 响应脚本（EVAL 离线）
    model_options: dict | None = None

    def trace_id_of(self) -> str:
        return str(self.trace_id or f"trace-{self.task_id}")


@dataclass
class ResumeEvent:
    """恢复事件（01 §3.1：USER_INPUT/APPROVAL_GRANTED/APPROVAL_DENIED/ENV_EVENT/TIMEOUT）。"""

    kind: str
    text: str = ""
    payload: dict = field(default_factory=dict)
    at: str = ""


@dataclass
class _TurnOutcome:
    stop: bool = False
    reason: str = ""


class AgentCore:
    """执行内核门面（持有 M2/M3/模型客户端/中间件链；不持有任务权威数据）。"""

    def __init__(
        self,
        info: Any,
        gateway: Any | None = None,
        model: ModelClient | None = None,
        *,
        journal_dir: Path | str | None = None,
        now_fn: Callable[[], str] | None = None,
        middlewares: Iterable[Middleware] | None = None,
        safety_directives: Iterable[str] | None = None,
        artifact_policy: Mapping[str, Mapping] | None = None,
        blocking_levels: Iterable[str] = ("P0",),
    ) -> None:
        self.info = info
        self.gateway = gateway
        self.model = model
        self._now = now_fn or now_iso
        self._journal_dir = Path(journal_dir) if journal_dir else \
            Path(info.root) / "m1_core" / "loop"
        self.artifact_policy = {k: dict(v) for k, v in
                                (artifact_policy or DEFAULT_ARTIFACT_POLICY).items()}
        self.blocking_levels = tuple(blocking_levels)
        self.verifier = CompletionVerifier(info)
        self._accepted_claims: dict[str, str] = {}
        self.last_verdicts: dict[str, list[dict]] = {}
        self._task_ctxs: dict[str, TaskContext] = {}
        self._models: dict[str, ModelClient] = {}
        self._traces: dict[str, LoopTrace] = {}
        if middlewares is None:
            middlewares = default_middlewares(safety_directives)
        self.chain = MiddlewareChain(middlewares)
        self.machine = TaskStateMachine(
            get_task=self._get_task,
            commit=self._commit,
            emit=self._emit,
            is_completable=lambda task_id: task_id in self._accepted_claims,
        )

    # ================================================================ 冻结 API
    def run_task(self, user_input: str, task_ctx: TaskContext) -> TaskState:
        """主入口：创建/恢复任务，驱动 Loop 直至 WAITING_* 或终态（01 §3.1）。"""
        task_id = str(task_ctx.task_id)
        self._task_ctxs[task_id] = task_ctx
        if self.info.store.has_task(task_id):
            return self.resume_task(task_id, ResumeEvent(kind="USER_INPUT", text=user_input))
        self.info.create_task(
            task_id,
            user_input=str(user_input),
            trace_id=task_ctx.trace_id_of(),
            plan=list(task_ctx.plan or []),
            todos=list(task_ctx.todos or []),
            budget=dict(task_ctx.budget or {}),
            current_stage=str(task_ctx.current_stage or "INTAKE"),
        )
        return self.run_loop(task_id, user_input=user_input)

    def resume_task(self, task_id: str, event: ResumeEvent) -> TaskState:
        """恢复等待/暂停任务（ResumeEvent 与状态必须匹配，01 §3.1）。"""
        task_id = str(task_id)
        if not isinstance(event, ResumeEvent):
            raise TypeError(f"event 必须为 ResumeEvent，实际 {type(event).__name__}")
        if event.kind not in ResumeKind:
            raise LoopError(f"未知 ResumeEvent 种类: {event.kind!r}")
        state = self._get_task(task_id)
        status = state.status.value
        if status in TERMINAL_STATUSES:
            return state  # 终态只读
        if status in ("CREATED", "RUNNING"):
            return self.run_loop(task_id, user_input=event.text)

        allowed = _RESUME_RULES.get(status, ())
        if event.kind not in allowed:
            raise LoopNotResumableError(
                f"任务 {task_id} 处于 {status}，只接受 {'/'.join(allowed)}，"
                f"实际 {event.kind!r}（Loop 拒绝进入下一轮）")

        if status == "PAUSED":
            # 恢复前重查预算：仍超限 → 保持 PAUSED（拒绝进入下一轮，SPEC-M1-05）
            budget_check = check_budget(self._get_task(task_id).budget, now=self._now())
            if budget_check.exceeded:
                raise LoopNotResumableError(
                    f"任务 {task_id} 预算仍超限（{budget_check.kind}: {budget_check.detail}），"
                    f"恢复被拒绝——需先调整预算租约再 Resume")
            self.machine.transition(task_id, "RUNNING",
                                    trace_id=self._trace_id(task_id),
                                    reason=f"resume:{event.kind}")
            return self.run_loop(task_id, user_input=event.text)

        if status == "WAITING_INPUT":
            self.machine.transition(task_id, "RUNNING",
                                    trace_id=self._trace_id(task_id),
                                    reason=f"resume:{event.kind}")
            return self.run_loop(task_id, user_input=event.text)

        if status == "WAITING_EVENT":
            self.machine.transition(task_id, "RUNNING",
                                    trace_id=self._trace_id(task_id),
                                    reason=f"resume:{event.kind}")
            return self.run_loop(task_id, user_input=event.text)

        if status == "VERIFYING":
            self.machine.transition(task_id, "RUNNING",
                                    trace_id=self._trace_id(task_id),
                                    reason=f"resume:{event.kind}")
            return self.run_loop(task_id, user_input=event.text)

        # WAITING_APPROVAL：审批决断（M3 submit_approval）→ 带观测回 RUNNING
        self._resolve_approval(task_id, event)
        self.machine.transition(task_id, "RUNNING",
                                trace_id=self._trace_id(task_id),
                                reason=f"resume:{event.kind}")
        return self.run_loop(task_id, user_input=event.text)

    def request_completion(self, task_id: str,
                           claim: CompletionClaim | Mapping) -> CompletionVerdict:
        """完成申请判定（01 §3.1；SPEC-M1-06：申请与判定分离）。"""
        task_id = str(task_id)
        parsed = claim if isinstance(claim, CompletionClaim) else CompletionClaim.from_dict(claim)
        if not parsed.task_id:
            parsed.task_id = task_id
        state = self._get_task(task_id)
        status = state.status.value
        if status in TERMINAL_STATUSES or status not in ("RUNNING", "VERIFYING"):
            verdict = CompletionVerdict(
                verdict="REJECTED",
                reasons=[f"任务处于 {status}，完成判定只接受 RUNNING/VERIFYING"],
            )
            self.last_verdicts.setdefault(task_id, []).append(verdict.to_dict())
            return verdict
        if status == "RUNNING":
            self.machine.transition(task_id, "VERIFYING",
                                    trace_id=self._trace_id(task_id),
                                    reason="completion_claim")
        verdict = self.verifier.judge(task_id, parsed)
        self.last_verdicts.setdefault(task_id, []).append(verdict.to_dict())
        if verdict.verdict == "ACCEPTED":
            self._accepted_claims[task_id] = claim_fingerprint(parsed)
            self.machine.transition(
                task_id, "COMPLETED",
                mutation={"note": f"completion ACCEPTED（claim {claim_fingerprint(parsed)[:12]}）"},
                trace_id=self._trace_id(task_id))
            return verdict
        # NEED_MORE_EVIDENCE：回 RUNNING 并注入缺口 todos（SPEC-M1-06）
        state = self._get_task(task_id)
        todos = merge_gap_todos(state, verdict.gaps) if verdict.gaps \
            else planner.todos_of(state)
        note = f"completion={verdict.verdict}: {'; '.join(verdict.reasons)[:180]}"
        self.machine.transition(task_id, "RUNNING",
                                mutation={"todos": todos, "note": note},
                                trace_id=self._trace_id(task_id))
        return verdict

    # ================================================================ 循环驱动
    def run_loop(self, task_id: str, task_ctx: TaskContext | None = None,
                 *, user_input: str = "") -> TaskState:
        """五阶段循环驱动（specs/M1 §2 run_loop）。

        WAITING_*/PAUSED 态直接调用 → LoopNotResumableError（必须经 resume_task
        携带 ResumeEvent；SPEC-M1-05 恢复语义）。
        """
        task_id = str(task_id)
        state = self._get_task(task_id)
        status = state.status.value
        if status in TERMINAL_STATUSES:
            return state
        if status == "CREATED":
            state = self.machine.transition(task_id, "RUNNING",
                                            trace_id=self._trace_id(task_id))
            status = "RUNNING"
        elif status != "RUNNING":
            raise LoopNotResumableError(
                f"任务 {task_id} 处于 {status}：run_loop 拒绝驱动等待/暂停态"
                f"（需 resume_task + ResumeEvent）")
        ctx = task_ctx or self._task_ctxs.get(task_id) or TaskContext(task_id=task_id)
        self._task_ctxs.setdefault(task_id, ctx)
        max_turns = int(ctx.max_turns)
        turns_run = 0
        first_input = str(user_input or "")
        while True:
            state = self._get_task(task_id)
            if state.status.value in TERMINAL_STATUSES:
                return state
            if state.status.value != "RUNNING":
                return state  # 轮末迁往等待态（WAITING_*/PAUSED）
            if turns_run >= max_turns:
                self.machine.transition(
                    task_id, "WAITING_INPUT",
                    trace_id=self._trace_id(task_id),
                    reason=f"max_turns={max_turns}")
                return self._get_task(task_id)
            turn_no = self._trace_of(task_id).last_turn() + 1
            outcome = self._run_turn(task_id, ctx, turn_no,
                                     user_input=first_input if turns_run == 0 else "")
            turns_run += 1
            if outcome.stop:
                return self._get_task(task_id)

    # ================================================================ 单轮
    def _run_turn(self, task_id: str, ctx: TaskContext, turn: int,
                  *, user_input: str = "") -> _TurnOutcome:
        trace = self._trace_of(task_id)
        trace_id = self._trace_id(task_id)
        turn_ctx = TurnContext(task_id, turn, user_input=user_input, trace_id=trace_id)
        contained = self.chain.dispatch("on_turn_start", turn_ctx)
        turn_ctx.notes.extend(contained)
        now = self._now()

        # ---------------- PREPARE：权威状态 + 预算检查点 + 上下文编译
        self.chain.dispatch("before_phase", "PREPARE", turn_ctx)
        state = self._get_task(task_id)  # SPEC-M1-03：每轮从 M2 读取权威状态
        turn_ctx.phase = "PREPARE"
        budget_check = check_budget(state.budget, now=now)
        if budget_check.exceeded:
            # SPEC-M1-05：任一超限 → 立即 PAUSED + budget.exhausted；本轮不进 Model
            self._emit(task_id, "budget.exhausted",
                       {"kind": budget_check.kind, "detail": budget_check.detail,
                        "turn": turn, "exceeded_kinds": list(budget_check.exceeded_kinds)},
                       trace_id)
            self.machine.transition(task_id, "PAUSED", trace_id=trace_id,
                                    reason=f"budget:{budget_check.kind}")
            trace.append(turn=turn, phase="PREPARE", at=self._now(), trace_id=trace_id,
                         summary=f"预算超限（{budget_check.kind}），本轮中断不进 Model",
                         data={"aborted": True, "budget": budget_check.to_dict(),
                               "state_version": state.version})
            self.chain.dispatch("on_turn_end", turn_ctx)
            return _TurnOutcome(stop=False, reason=f"budget:{budget_check.kind}")
        manifest = self.info.compile_context(task_id, turn)
        turn_ctx.manifest = manifest
        state = self._get_task(task_id)
        trace.append(turn=turn, phase="PREPARE", at=self._now(), trace_id=trace_id,
                     summary=(f"预算 OK；上下文编译 {manifest.total_tokens} tokens"
                              f"（hash {manifest.hash[:10]}）"),
                     data={"manifest_hash": manifest.hash,
                           "manifest_tokens": manifest.total_tokens,
                           "state_version": state.version,
                           "status": state.status.value,
                           "current_stage": state.current_stage})
        self.chain.dispatch("after_phase", "PREPARE", turn_ctx)

        # ---------------- MODEL：统一客户端 + 成本上报
        self.chain.dispatch("before_phase", "MODEL", turn_ctx)
        turn_ctx.phase = "MODEL"
        request = self._build_model_request(task_id, ctx, turn_ctx, state, manifest)
        turn_ctx.model_request = request
        response = self._model_of(ctx).complete(request)
        turn_ctx.model_response = response
        cost_report = self._report_cost(task_id, turn, response, trace_id)
        trace.append(turn=turn, phase="MODEL", at=self._now(), trace_id=trace_id,
                     summary=f"模型响应 {len(str(response.get('text', '')))} 字"
                             f"（cost {cost_report['cost']['tokens']} tokens）",
                     data={"cost": cost_report["cost"], "usage": response.get("usage"),
                           "tool_calls": len(response.get("tool_calls") or [])})
        self.chain.dispatch("after_phase", "MODEL", turn_ctx)

        # ---------------- ACT：ActionRequest 通道执行（DONE todo 绑定跳过）
        self.chain.dispatch("before_phase", "ACT", turn_ctx)
        turn_ctx.phase = "ACT"
        state = self._get_task(task_id)
        actions, skipped = self._execute_tool_calls(task_id, ctx, turn, response, state,
                                                    trace_id)
        turn_ctx.actions = actions
        if actions:
            self._commit(task_id, {
                "budget": {"action_used_delta": len(actions)},
                "note": f"actions@turn={turn}: {len(actions)}",
                "trace_id": trace_id,
            })
        trace.append(turn=turn, phase="ACT", at=self._now(), trace_id=trace_id,
                     summary=f"执行 {len(actions)} 个动作（跳过 {len(skipped)} 个 DONE 绑定）",
                     data={"actions": [
                         {"action_id": r.action_id,
                          "capability": (r.evidence.intended or {}).get("capability"),
                          "status": r.status.value} for r in actions],
                         "skipped": skipped})
        self.chain.dispatch("after_phase", "ACT", turn_ctx)

        # ---------------- OBSERVE：观测即事实（ActionResult + 环境事件）
        self.chain.dispatch("before_phase", "OBSERVE", turn_ctx)
        turn_ctx.phase = "OBSERVE"
        observations, env_events = self._observe(task_id, turn, actions, trace_id)
        turn_ctx.observations = observations
        trace.append(turn=turn, phase="OBSERVE", at=self._now(), trace_id=trace_id,
                     summary=f"采信 {len(observations)} 条动作观测 + "
                             f"{len(env_events)} 条环境事件",
                     data={"observations": [
                               {"action_id": o["action_id"], "status": o["status"]}
                               for o in observations],
                           "env_events": [e.get("event_id") for e in env_events],
                           "env_event_ids": [e.get("event_id") for e in env_events]})
        self.chain.dispatch("after_phase", "OBSERVE", turn_ctx)

        # ---------------- VERIFY：todos → 门禁 → 完成判定 → 轮末状态
        self.chain.dispatch("before_phase", "VERIFY", turn_ctx)
        turn_ctx.phase = "VERIFY"
        verify_data = self._verify(task_id, turn, response, trace_id, turn_ctx)
        trace.append(turn=turn, phase="VERIFY", at=self._now(), trace_id=trace_id,
                     summary=verify_data.get("summary", ""),
                     data=verify_data)
        self.chain.dispatch("after_phase", "VERIFY", turn_ctx)
        self.chain.dispatch("on_turn_end", turn_ctx)
        state = self._get_task(task_id)
        return _TurnOutcome(stop=state.status.value in TERMINAL_STATUSES,
                            reason=verify_data.get("end_reason", ""))

    # ================================================================ Verify 细分
    def _verify(self, task_id: str, turn: int, response: Mapping, trace_id: str,
                turn_ctx: TurnContext) -> dict:
        # 1) todo 更新（DONE 粘滞，SPEC-M1-09）
        state = self._get_task(task_id)
        todos, ignored = apply_todo_updates(state, response.get("todo_updates"))
        if todos != planner.todos_of(state) or ignored:
            self._commit(task_id, {"todos": todos,
                                   "note": f"todos@turn={turn}"
                                           + (f"；忽略 {ignored}" if ignored else ""),
                                   "trace_id": trace_id})

        # 2) 阶段门禁（SPEC-M1-04）
        state = self._get_task(task_id)
        gate = evaluate_stage_gate(
            state,
            artifact_lookup=self._artifact_lookup(task_id),
            task_events=self.info.event_log.events_for_task(task_id),
            blocking_levels=self.blocking_levels,
        )
        self._emit(task_id, "task.stage_gate",
                   {"stage": gate.stage, "verdict": "PASSED" if gate.passed else "BLOCKED",
                    "passed": gate.passed, "turn": turn,
                    "missing_artifacts": gate.missing_artifacts,
                    "blocking_alarms": gate.blocking_alarms,
                    "reasons": gate.reasons},
                   trace_id)
        if gate.passed:
            following = next_stage(state)
            mutation: dict = {"note": f"stage_gate PASSED@{gate.stage}（turn {turn}）"}
            # 门禁通过：既有 gap todos 置 DONE（缺口已消）
            resolved = planner.todos_of(state)
            for index, todo in enumerate(resolved):
                if str(todo["id"]).startswith(f"gap-{gate.stage}-") \
                        or str(todo["id"]).startswith("gap-completion-"):
                    resolved[index] = {**todo, "status": "DONE"}
            if resolved != planner.todos_of(state):
                mutation["todos"] = resolved
            if following and following != state.current_stage:
                mutation["current_stage"] = following
            self._commit(task_id, mutation)
        elif gate.gaps:
            merged = merge_gap_todos(state, gate.gaps)
            if merged != planner.todos_of(state):
                self._commit(task_id, {"todos": merged,
                                       "note": f"stage_gate BLOCKED@{gate.stage}"
                                               f"（gap 注入 turn {turn}）",
                                       "trace_id": trace_id})

        # 3) 完成申请（SPEC-M1-06：申请与判定分离；ACCEPTED → 终态 COMPLETED）
        claim = response.get("completion_claim")
        verdict_dict = None
        if claim is not None:
            verdict = self.request_completion(task_id, claim)
            verdict_dict = verdict.to_dict()

        state = self._get_task(task_id)
        end_reason = ""
        # 4) 轮末等待态：动作审批等待优先（01 §5.1 注：ASK → WAITING_APPROVAL）
        waiting_approval = any(
            getattr(r, "status", None) is not None and r.status.value == "WAITING_APPROVAL"
            for r in turn_ctx.actions)
        if state.status.value == "RUNNING" and waiting_approval:
            self.machine.transition(task_id, "WAITING_APPROVAL", trace_id=trace_id,
                                    reason="action WAITING_APPROVAL（ASK）")
            end_reason = "waiting_approval"
        elif state.status.value == "RUNNING":
            failure = response.get("fail")
            if failure:
                self.machine.transition(
                    task_id, "FAILED",
                    mutation={"note": f"模型报告失败: {dict(failure)}"},
                    trace_id=trace_id)
                end_reason = "failed"
            elif response.get("request_input"):
                self.machine.transition(task_id, "WAITING_INPUT", trace_id=trace_id,
                                        reason="模型请求用户输入")
                end_reason = "waiting_input"
            elif response.get("wait_event"):
                self.machine.transition(task_id, "WAITING_EVENT", trace_id=trace_id,
                                        reason="模型等待环境事件")
                end_reason = "waiting_event"

        state = self._get_task(task_id)
        summary = (f"门禁 {gate.stage}:{'PASSED' if gate.passed else 'BLOCKED'}；"
                   f"任务 {state.status.value}")
        if verdict_dict:
            summary += f"；完成判定 {verdict_dict['verdict']}"
        return {
            "summary": summary,
            "stage_gate": {"stage": gate.stage, "passed": gate.passed,
                           "missing": gate.missing_artifacts},
            "completion_verdict": verdict_dict,
            "end_reason": end_reason or state.status.value,
            "status_after": state.status.value,
            "current_stage": state.current_stage,
            "notes": list(turn_ctx.notes),
        }

    # ================================================================ 组件
    def _execute_tool_calls(self, task_id: str, ctx: TaskContext, turn: int,
                            response: Mapping, state: TaskState,
                            trace_id: str) -> tuple[list, list[str]]:
        if self.gateway is None:
            raise LoopError("未装配 M3 ActionGateway：Act 阶段不可用")
        actions: list = []
        skipped: list[str] = []
        calls = response.get("tool_calls") or []
        for index, call in enumerate(calls):
            call = dict(call or {})
            todo_id = str(call.get("todo_id", "") or "")
            if todo_id:
                if planner.todo_status(state, todo_id) == "DONE":
                    skipped.append(f"{todo_id}:{call.get('capability', '?')}（todo 已 DONE，幂等跳过）")
                    continue
            actions.append(self._execute_call(task_id, ctx, turn, index, call, trace_id))
        return actions, skipped

    def _execute_call(self, task_id: str, ctx: TaskContext, turn: int, index: int,
                      call: dict, trace_id: str) -> Any:
        capability = str(call.get("capability", "") or "")
        if "@" not in capability:
            raise LoopError(f"tool_calls[{index}].capability 必须为 '动作ID@版本': {capability!r}")
        todo_id = str(call.get("todo_id", "") or "")
        idempotency_key = str(call.get("idempotency_key", "") or "") or (
            f"{task_id}:todo:{todo_id}:{capability}" if todo_id
            else f"{task_id}:turn{turn}:{index}:{capability}")
        action_id = str(call.get("action_id", "") or "") or f"act-{new_ulid()}"
        request = {
            "action_id": action_id,
            "task_id": task_id,
            "turn": int(turn),
            "capability": capability,
            "actor": {"user": str(ctx.actor_user), "agent": str(ctx.actor_agent)},
            "purpose": str(call.get("purpose", "") or f"{capability}（第 {turn} 轮）"),
            "arguments": dict(call.get("arguments") or {}),
            "risk": self._risk_of(call),
            "idempotency_key": idempotency_key,
            "requested_at": normalize_ts(self._now()),
        }
        ActionRequest.from_dict(request)  # 契约前置校验（失败即抛，不进网关）
        return self.gateway.execute_action(request, mode="SIMULATION",
                                           trace_id=trace_id)

    def _risk_of(self, call: Mapping) -> dict:
        risk = call.get("risk")
        if isinstance(risk, Mapping) and risk.get("level"):
            return {"level": str(risk["level"]),
                    "reversible": bool(risk.get("reversible", False)),
                    "compensation": risk.get("compensation")}
        capability = str(call.get("capability", "")).split("@", 1)[0]
        if self.gateway is not None:
            descriptor = self.gateway.registry.get(str(call.get("capability", ""))) \
                or self.gateway.registry.by_action(capability)
            if descriptor is not None:
                return {"level": descriptor.risk_level.value,
                        "reversible": bool(descriptor.reversible),
                        "compensation": descriptor.compensation}
        return {"level": "LOW", "reversible": False, "compensation": None}

    def _observe(self, task_id: str, turn: int, actions: list,
                 trace_id: str) -> tuple[list, list]:
        """Observe：只采信 ActionResult 与环境事件（SPEC-M1-07）。"""
        observations: list = []
        for result in actions:
            status = result.status.value
            observations.append({
                "action_id": result.action_id, "status": status,
                "observation": result.observation,
            })
            if status == "SUCCEEDED":
                # 三态证据落 evidence/（SPEC-M2-09 口径）→ evidence_refs
                rel = self.info.save_evidence(
                    task_id, f"action-{result.action_id}",
                    {"action_id": result.action_id,
                     "evidence": asdict_plain(result.evidence)},
                    trace_id=trace_id)
                self._commit(task_id, {"evidence_refs_add": [rel],
                                       "note": f"evidence@turn={turn}:{result.action_id}",
                                       "trace_id": trace_id})
                # 产物策略：SUCCEEDED 写类动作 → M2 ArtifactRecord
                self._apply_artifact_policy(task_id, result, trace_id)
        env_events = self._new_env_events(task_id)
        return observations, env_events

    def _new_env_events(self, task_id: str) -> list:
        """本轮新到的环境事件（按 event_id 去重——已观测过的不再重复采信）。"""
        observed: set[str] = set()
        for entry in self._trace_of(task_id).entries():
            for event_id in (entry.get("data") or {}).get("env_event_ids") or []:
                observed.add(str(event_id))
        fresh = []
        for event in self.info.event_log.events_for_task(task_id):
            if str(event.get("type")) in _ENV_EVENT_TYPES \
                    and str(event.get("event_id")) not in observed:
                fresh.append(event)
        return fresh

    def _apply_artifact_policy(self, task_id: str, result: Any, trace_id: str) -> None:
        capability = str((result.evidence.intended or {}).get("capability", "")).split("@", 1)[0]
        policy = self.artifact_policy.get(capability)
        if not policy:
            return
        # 幂等入账：同 action_id 已落产物则跳过（M3 幂等键回放返回首结果——
        # 原 action_id 重入 Observe 不重复建 ArtifactRecord；CHANGELOG 偏差 5 口径）
        for existing in self.info.store.list_artifacts(task_id):
            if existing.created_by.action_id == result.action_id:
                return
        arguments = dict((result.evidence.intended or {}).get("arguments") or {})
        content = {str(section): arguments.get(section)
                   for section in policy.get("content_sections", [])}
        record = self.info.artifacts.create(
            task_id,
            type=str(policy["artifact_type"]),
            schema_id=str(policy["schema_id"]),
            content=content,
            action_id=result.action_id,
            trace_id=trace_id,
        )
        # DRAFT→VALIDATING（schema 校验）→ 校验通过续迁 READY（失败停 REJECTED 带 detail）
        after_validate = self.info.artifacts.transition(
            record.artifact_id, "VALIDATING", trace_id=trace_id)
        if after_validate.status.value == "VALIDATING":
            self.info.artifacts.transition(record.artifact_id, "READY",
                                           trace_id=trace_id)
        final = self.info.artifacts.get(record.artifact_id)
        self._commit(task_id, {"artifacts_add": [record.artifact_id],
                               "note": f"artifact {record.artifact_id}"
                                       f"→{final.status.value}@{capability}",
                               "trace_id": trace_id})

    def _report_cost(self, task_id: str, turn: int, response: Mapping,
                     trace_id: str) -> dict:
        """SPEC-M1-10：成本写 TaskState.budget + 事件流（cost 字段）。"""
        cost = dict(response.get("cost") or {})
        delta = int(cost.get("tokens") or 0)
        self._commit(task_id, {
            "budget": {"token_used_delta": delta},
            "note": f"model-cost@turn={turn}",
            "trace_id": trace_id,
        })
        budget = self._get_task(task_id).budget
        remaining = int(budget.token_max) - int(budget.token_used)
        # 事件目录无 model.* 主题：budget.warning 兼作每轮成本上报通道
        # （payload 保留 kind/remaining 语义字段并扩展 cost——偏差已登记 CHANGELOG）
        self._emit(task_id, "budget.warning",
                   {"kind": "token", "remaining": remaining, "turn": turn,
                    "cost": {**cost, "turn": turn, "token_used_delta": delta}},
                   trace_id)
        return {"cost": {**cost, "token_used_delta": delta}, "remaining": remaining}

    def _build_model_request(self, task_id: str, ctx: TaskContext,
                             turn_ctx: TurnContext, state: TaskState,
                             manifest: Any) -> dict:
        from .planner import pending_todos

        pending = pending_todos(state)
        todo_lines = "\n".join(
            f"- [{t['status']}] {t['id']}: {t['text']}" for t in pending) or "-（无待办）"
        tools = []
        if self.gateway is not None:
            for descriptor in self.gateway.registry.descriptors():
                tools.append({"capability": descriptor.capability_id,
                              "description": descriptor.name_cn})
        messages = [
            {"role": "system",
             "content": "你是园区配电运维智能体。严格按计划与规程执行；"
                        "一切动作走 ActionRequest 通道；完成必须申请并附证据。"},
            {"role": "system",
             "content": (f"任务 {task_id}（第 {turn_ctx.turn} 轮）：状态 "
                         f"{state.status.value}，当前阶段 {state.current_stage}。\n"
                         f"待办：\n{todo_lines}\n"
                         f"上下文指纹 {manifest.hash[:12]}（{manifest.total_tokens} tokens）")},
            {"role": "user",
             "content": str(turn_ctx.user_input or "继续按计划执行当前任务。")},
        ]
        return {
            "messages": messages,
            "tools": tools,
            "trace_id": turn_ctx.trace_id,
            "task_id": task_id,
            "turn": turn_ctx.turn,
        }

    # ================================================================ 恢复辅助
    def _resolve_approval(self, task_id: str, event: ResumeEvent) -> Any:
        """WAITING_APPROVAL 的审批决断（GRANT/DENY/TIMEOUT → M3）。"""
        if self.gateway is None:
            raise LoopError("未装配 M3 ActionGateway：审批恢复不可用")
        entries = [e for e in self.gateway.approvals.pending()
                   if e.task_id == task_id]
        if not entries:
            return None  # 无待审批条目（已决断/超时）：直接回 RUNNING
        entry = entries[0]
        trace_id = self._trace_id(task_id)
        if event.kind == "TIMEOUT":
            outcomes = self.gateway.check_approval_timeouts(self._now())
            return outcomes[0] if outcomes else None
        decision = "GRANT" if event.kind == "APPROVAL_GRANTED" else "DENY"
        approver = str(event.payload.get("approver", "") or
                       self._default_approver() or "APPROVER")
        result = self.gateway.submit_approval(entry.action_id, decision, approver,
                                              now=self._now())
        self._absorb_approval_result(task_id, result, trace_id)
        return result

    def _absorb_approval_result(self, task_id: str, result: Any, trace_id: str) -> None:
        """审批后的执行结果入账（证据/产物/动作预算——与 Observe 同口径）。"""
        if result is None or result.status.value != "SUCCEEDED":
            if result is not None:
                self._commit(task_id, {
                    "budget": {"action_used_delta": 1},
                    "note": f"approval action {result.action_id}"
                            f"→{result.status.value}",
                    "trace_id": trace_id})
            return
        rel = self.info.save_evidence(
            task_id, f"action-{result.action_id}",
            {"action_id": result.action_id, "evidence": asdict_plain(result.evidence)},
            trace_id=trace_id)
        self._apply_artifact_policy(task_id, result, trace_id)
        self._commit(task_id, {
            "evidence_refs_add": [rel],
            "budget": {"action_used_delta": 1},
            "note": f"approval action {result.action_id}→SUCCEEDED",
            "trace_id": trace_id})

    def _default_approver(self) -> str:
        if self.gateway is None:
            return ""
        for user, role in (getattr(self.gateway, "actor_roles", None) or {}).items():
            if str(role) == "审批人":
                return str(user)
        return ""

    # ================================================================ 基础设施
    def _get_task(self, task_id: str) -> TaskState:
        return self.info.get_task(task_id)

    def _commit(self, task_id: str, mutation: dict) -> TaskState:
        mutation = dict(mutation)
        mutation.setdefault("trace_id", self._trace_id(task_id))
        return self.info.commit_state(task_id, mutation)

    def _emit(self, task_id: str, event_type: str, payload: dict,
              trace_id: str) -> None:
        self.info.event_log.append(
            {"type": event_type, "subject": task_id, "payload": dict(payload),
             "trace_id": trace_id or self._trace_id(task_id), "producer": "M1"},
            stream=f"task-{task_id}", now_fn=self._now)

    def _trace_id(self, task_id: str) -> str:
        ctx = self._task_ctxs.get(task_id)
        return ctx.trace_id_of() if ctx else f"trace-{task_id}"

    def _trace_of(self, task_id: str) -> LoopTrace:
        if task_id not in self._traces:
            self._traces[task_id] = LoopTrace(self._journal_dir, task_id)
        return self._traces[task_id]

    def _model_of(self, ctx: TaskContext) -> ModelClient:
        if self.model is not None:
            return self.model
        if ctx.task_id not in self._models:
            options = dict(ctx.model_options or {})
            self._models[ctx.task_id] = ModelClient(
                provider=str(options.pop("provider", "mock")),
                script=ctx.model_script, **options)
        return self._models[ctx.task_id]

    def _artifact_lookup(self, task_id: str) -> Callable[[str], Mapping | None]:
        def lookup(ref: str) -> Mapping | None:
            for record in self.info.store.list_artifacts(task_id):
                if record.artifact_id == str(ref) or record.schema_id == str(ref):
                    return {"artifact_id": record.artifact_id,
                            "status": record.status.value,
                            "schema_id": record.schema_id}
            return None
        return lookup

    # ================================================================ 审计辅助
    def bind_context(self, task_ctx: TaskContext) -> None:
        """绑定任务上下文（恢复/审计驱动用——run_task 自动绑定）。"""
        self._task_ctxs[str(task_ctx.task_id)] = task_ctx

    def replay_report(self, task_id: str) -> dict:
        """回放校验（EVAL/审计：trace 五阶段序合法性）。"""
        return validate_replay(self._trace_of(task_id).entries())
