# -*- coding: utf-8 -*-
"""m1_core · Agent Core（执行内核）：Agent Loop 五阶段、任务状态机驱动与迁移守卫、
Planning/Todo 外部化、阶段门禁、预算检查点、完成验证、Middleware 链、LLM 统一客户端
（specs/M1-agent-core.md；冻结接口 specs/01-contracts.md §3.1）。

冻结调用接口（01 §3.1，由 :class:`AgentCore` 提供）::

    run_task(user_input, task_ctx) -> TaskState
    resume_task(task_id, event: ResumeEvent) -> TaskState
    request_completion(task_id, claim: CompletionClaim) -> CompletionVerdict
    # verdict ∈ {ACCEPTED, NEED_MORE_EVIDENCE, REJECTED}

模块不持有任何持久任务数据（权威状态全部外置 M2）；模型调用统一走
``m1_core.model_client``（01 §8：禁止业务模块直连 SDK）。
"""
from __future__ import annotations

from .budget import BUDGET_KINDS, BudgetCheck, budget_remaining, budget_warning_level, check_budget
from .clocking import iso_z, normalize_ts, now_iso, parse_iso
from .completion import (
    ACCEPTED_ARTIFACT_STATUSES,
    VERDICTS,
    CompletionClaim,
    CompletionVerifier,
    CompletionVerdict,
    claim_fingerprint,
)
from .gates import GATE_PASS_STATUSES, GateResult, evaluate_stage_gate
from .ids import new_seq_id, new_ulid
from .loop import (
    DEFAULT_ARTIFACT_POLICY,
    AgentCore,
    LoopError,
    LoopNotResumableError,
    ResumeEvent,
    ResumeKind,
    TaskContext,
)
from .middleware import (
    DEFAULT_SAFETY_DIRECTIVES,
    DelegationMiddleware,
    LoggingMiddleware,
    Middleware,
    MiddlewareChain,
    SafetyInjectionMiddleware,
    TurnContext,
    default_middlewares,
)
from .model_client import (
    PROVIDERS,
    ModelClient,
    ModelClientError,
    ModelRetryExhaustedError,
    ModelTimeoutError,
    estimate_tokens,
)
from .planner import (
    apply_todo_updates,
    build_gap_todos,
    final_step,
    gap_todo,
    merge_gap_todos,
    next_stage,
    pending_todos,
    stage_index,
    stage_step,
    todo_by_id,
    todo_status,
)
from .state_machine import (
    TASK_STATES,
    TASK_TRANSITIONS,
    TERMINAL_STATUSES,
    CompletionRequiredError,
    IllegalTransitionError,
    TaskStateMachine,
    assert_legal,
    assert_table_consistency,
    load_frozen_table,
    rejection_payload,
    table_diff,
    transition_allowed,
)
from .trace import PHASE_ORDER, LoopTrace, validate_replay

__all__ = [
    # 冻结 API 门面
    "AgentCore", "TaskContext", "ResumeEvent", "ResumeKind",
    "LoopError", "LoopNotResumableError",
    # 状态机（SPEC-M1-02）
    "TASK_TRANSITIONS", "TASK_STATES", "TERMINAL_STATUSES",
    "IllegalTransitionError", "CompletionRequiredError", "TaskStateMachine",
    "transition_allowed", "assert_legal", "load_frozen_table", "table_diff",
    "assert_table_consistency", "rejection_payload",
    # 预算（SPEC-M1-05）
    "BUDGET_KINDS", "BudgetCheck", "check_budget", "budget_remaining",
    "budget_warning_level",
    # 门禁（SPEC-M1-04）
    "GATE_PASS_STATUSES", "GateResult", "evaluate_stage_gate",
    # 完成（SPEC-M1-06）
    "VERDICTS", "ACCEPTED_ARTIFACT_STATUSES", "CompletionClaim",
    "CompletionVerdict", "CompletionVerifier", "claim_fingerprint",
    # 中间件（SPEC-M1-08）
    "Middleware", "MiddlewareChain", "TurnContext", "LoggingMiddleware",
    "SafetyInjectionMiddleware", "DelegationMiddleware", "default_middlewares",
    "DEFAULT_SAFETY_DIRECTIVES",
    # 模型客户端
    "ModelClient", "ModelClientError", "ModelRetryExhaustedError",
    "ModelTimeoutError", "PROVIDERS", "estimate_tokens",
    # 计划（01 §2.3）
    "apply_todo_updates", "build_gap_todos", "final_step", "gap_todo",
    "merge_gap_todos", "next_stage", "pending_todos", "stage_index",
    "stage_step", "todo_by_id", "todo_status",
    # Loop 轨迹回放（SPEC-M1-01）
    "PHASE_ORDER", "LoopTrace", "validate_replay",
    # 产物策略与时间助手
    "DEFAULT_ARTIFACT_POLICY", "parse_iso", "iso_z", "normalize_ts", "now_iso",
    "new_ulid", "new_seq_id",
]
