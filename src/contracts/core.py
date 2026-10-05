# -*- coding: utf-8 -*-
"""冻结数据结构（一）：运行核心六件（specs/01-contracts.md §2.1–§2.6）。

- ActionRequest（M1→M3）/ ActionResult（M3→M1）
- TaskState（M2 持有，M1 读写）/ ContextManifest（M2→M1）
- EventRecord（全系统事件，追加写 runtime/events/*.jsonl）
- ArtifactRecord（M2 持有）

全部字段名与枚举值和 01 §2 逐字一致；提供 to_dict / from_dict（加载即校验）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from . import enums as E
from .base import (
    ContractValidationError as _ContractError,
    asdict_plain,
    check_bool,
    check_capability_format,
    check_enum,
    check_id,
    check_int,
    check_keys,
    check_mapping,
    check_str,
    check_str_list,
    check_timestamp,
    require,
)

__all__ = [
    "Actor",
    "Risk",
    "ActionRequest",
    "Evidence",
    "ActionError",
    "ActionResult",
    "PlanStep",
    "Todo",
    "PriceWindow",
    "Budget",
    "TaskState",
    "ContextSource",
    "ContextManifest",
    "EventRecord",
    "CreatedBy",
    "ValidationCheck",
    "ArtifactValidation",
    "ArtifactRecord",
]


# ---------------------------------------------------------------- §2.1
@dataclass
class Actor:
    """ActionRequest.actor。"""

    user: str
    agent: str
    on_behalf_of: str | None = None  # 委托链（L3+ 才使用）

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "actor") -> "Actor":
        check_keys(data, ("user", "agent", "on_behalf_of"), path)
        on_behalf_of = data.get("on_behalf_of")
        return cls(
            user=check_str(require(data, "user", path), f"{path}.user"),
            agent=check_str(require(data, "agent", path), f"{path}.agent"),
            on_behalf_of=None if on_behalf_of is None else check_str(on_behalf_of, f"{path}.on_behalf_of"),
        )


@dataclass
class Risk:
    """ActionRequest.risk。"""

    level: E.RiskLevel
    reversible: bool
    compensation: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "risk") -> "Risk":
        check_keys(data, ("level", "reversible", "compensation"), path)
        compensation = data.get("compensation")
        return cls(
            level=check_enum(require(data, "level", path), E.RiskLevel, f"{path}.level"),
            reversible=check_bool(require(data, "reversible", path), f"{path}.reversible"),
            compensation=None if compensation is None else check_str(compensation, f"{path}.compensation"),
        )


@dataclass
class ActionRequest:
    """M1→M3 行动请求（01 §2.1）。"""

    action_id: str
    task_id: str
    turn: int
    capability: str  # 格式 "动作ID@版本"
    actor: Actor
    purpose: str
    arguments: dict
    risk: Risk
    idempotency_key: str
    requested_at: str  # UTC ISO-8601

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ActionRequest":
        check_keys(data, (
            "action_id", "task_id", "turn", "capability", "actor", "purpose",
            "arguments", "risk", "idempotency_key", "requested_at",
        ), "ActionRequest")
        return cls(
            action_id=check_id(require(data, "action_id", "ActionRequest"), "ActionRequest.action_id"),
            task_id=check_str(require(data, "task_id", "ActionRequest"), "ActionRequest.task_id"),
            turn=check_int(require(data, "turn", "ActionRequest"), "ActionRequest.turn"),
            capability=check_capability_format(
                require(data, "capability", "ActionRequest"), "ActionRequest.capability"
            ),
            actor=Actor.from_dict(require(data, "actor", "ActionRequest")),
            purpose=check_str(require(data, "purpose", "ActionRequest"), "ActionRequest.purpose"),
            arguments=check_mapping(require(data, "arguments", "ActionRequest"), "ActionRequest.arguments"),
            risk=Risk.from_dict(require(data, "risk", "ActionRequest")),
            idempotency_key=check_str(
                require(data, "idempotency_key", "ActionRequest"), "ActionRequest.idempotency_key"
            ),
            requested_at=check_timestamp(
                require(data, "requested_at", "ActionRequest"), "ActionRequest.requested_at"
            ),
        )

    def to_dict(self) -> dict:
        return asdict_plain(self)


# ---------------------------------------------------------------- §2.2
@dataclass
class Evidence:
    """ActionResult.evidence（三态：intended/issued/observed）。"""

    intended: dict  # 计划动作（=ActionRequest 摘要）
    issued: dict | None = None  # 已发出动作（执行器确认）
    observed: dict | None = None  # 环境确认结果（真实读数/状态回读）

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "evidence") -> "Evidence":
        check_keys(data, ("intended", "issued", "observed"), path)
        return cls(
            intended=check_mapping(require(data, "intended", path), f"{path}.intended"),
            issued=None if data.get("issued") is None else check_mapping(data["issued"], f"{path}.issued"),
            observed=None if data.get("observed") is None else check_mapping(data["observed"], f"{path}.observed"),
        )


@dataclass
class ActionError:
    """ActionResult.error。"""

    code: str
    message: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "error") -> "ActionError":
        check_keys(data, ("code", "message"), path)
        return cls(
            code=check_str(require(data, "code", path), f"{path}.code"),
            message=check_str(require(data, "message", path), f"{path}.message"),
        )


@dataclass
class ActionResult:
    """M3→M1 行动结果（01 §2.2）。

    Evidence 三态规则：SUCCEEDED 必须三者齐全；EXECUTING 允许 intended+issued；
    observed 必须来自环境回读，不得由执行器自报（构造时对 SUCCEEDED 强制校验）。
    """

    action_id: str
    status: E.ActionStatus
    result_refs: list
    observation: str
    evidence: Evidence
    latency_ms: int
    trace_id: str
    error: ActionError | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ActionResult":
        check_keys(data, (
            "action_id", "status", "result_refs", "observation", "evidence",
            "latency_ms", "trace_id", "error",
        ), "ActionResult")
        status = check_enum(require(data, "status", "ActionResult"), E.ActionStatus, "ActionResult.status")
        evidence = Evidence.from_dict(require(data, "evidence", "ActionResult"))
        # 01 §2.2 Evidence 三态规则
        if status is E.ActionStatus.SUCCEEDED and (
            evidence.intended is None or evidence.issued is None or evidence.observed is None
        ):
            raise _ContractError(
                "ActionResult.evidence", "SUCCEEDED 要求 evidence 三态齐全（intended/issued/observed）"
            )
        error = data.get("error")
        return cls(
            action_id=check_id(require(data, "action_id", "ActionResult"), "ActionResult.action_id"),
            status=status,
            result_refs=check_str_list(require(data, "result_refs", "ActionResult"), "ActionResult.result_refs"),
            observation=check_str(require(data, "observation", "ActionResult"), "ActionResult.observation"),
            evidence=evidence,
            latency_ms=check_int(require(data, "latency_ms", "ActionResult"), "ActionResult.latency_ms"),
            trace_id=check_str(require(data, "trace_id", "ActionResult"), "ActionResult.trace_id"),
            error=None if error is None else ActionError.from_dict(error),
        )

    def to_dict(self) -> dict:
        return asdict_plain(self)


# ---------------------------------------------------------------- §2.3
@dataclass
class PlanStep:
    """TaskState.plan[]。"""

    stage: str
    gate: str
    artifacts_expected: list

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str) -> "PlanStep":
        check_keys(data, ("stage", "gate", "artifacts_expected"), path)
        return cls(
            stage=check_str(require(data, "stage", path), f"{path}.stage"),
            gate=check_str(require(data, "gate", path), f"{path}.gate"),
            artifacts_expected=check_str_list(
                require(data, "artifacts_expected", path), f"{path}.artifacts_expected"
            ),
        )


@dataclass
class Todo:
    """TaskState.todos[]。"""

    id: str
    text: str
    status: E.TodoStatus

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str) -> "Todo":
        check_keys(data, ("id", "text", "status"), path)
        return cls(
            id=check_str(require(data, "id", path), f"{path}.id"),
            text=check_str(require(data, "text", path), f"{path}.text"),
            status=check_enum(require(data, "status", path), E.TodoStatus, f"{path}.status"),
        )


@dataclass
class PriceWindow:
    """TaskState.budget.price_window。"""

    from_ts: str  # 契约字段名 "from"
    to_ts: str  # 契约字段名 "to"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str) -> "PriceWindow":
        check_keys(data, ("from", "to"), path)
        return cls(
            from_ts=check_timestamp(require(data, "from", path), f"{path}.from"),
            to_ts=check_timestamp(require(data, "to", path), f"{path}.to"),
        )

    def to_dict(self) -> dict:
        return {"from": self.from_ts, "to": self.to_ts}


@dataclass
class Budget:
    """TaskState.budget（Budget Lease，M3 联动扣减）。"""

    token_max: int
    token_used: int
    action_max: int
    action_used: int
    deadline: str | None = None  # UTC ISO-8601
    price_window: PriceWindow | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "budget") -> "Budget":
        check_keys(data, ("token_max", "token_used", "action_max", "action_used", "deadline", "price_window"), path)
        price_window = data.get("price_window")
        return cls(
            token_max=check_int(require(data, "token_max", path), f"{path}.token_max"),
            token_used=check_int(require(data, "token_used", path), f"{path}.token_used"),
            action_max=check_int(require(data, "action_max", path), f"{path}.action_max"),
            action_used=check_int(require(data, "action_used", path), f"{path}.action_used"),
            deadline=None if data.get("deadline") is None else check_timestamp(data["deadline"], f"{path}.deadline"),
            price_window=None if price_window is None else PriceWindow.from_dict(price_window, f"{path}.price_window"),
        )


@dataclass
class TaskState:
    """M2 持有、M1 读写（01 §2.3）。"""

    task_id: str
    version: int  # 乐观锁，每次变更 +1
    status: E.TaskStatus
    current_stage: str
    plan: list
    todos: list
    budget: Budget
    artifacts: list
    evidence_refs: list
    context_manifest_hash: str
    updated_at: str  # UTC ISO-8601
    subtasks: list | None = None  # L3+ 委派

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TaskState":
        check_keys(data, (
            "task_id", "version", "status", "current_stage", "plan", "todos",
            "budget", "artifacts", "subtasks", "evidence_refs",
            "context_manifest_hash", "updated_at",
        ), "TaskState")
        plan_raw = require(data, "plan", "TaskState")
        if not isinstance(plan_raw, list):
            raise _ContractError("TaskState.plan", "必须是列表")
        todos_raw = require(data, "todos", "TaskState")
        if not isinstance(todos_raw, list):
            raise _ContractError("TaskState.todos", "必须是列表")
        subtasks = data.get("subtasks")
        return cls(
            task_id=check_str(require(data, "task_id", "TaskState"), "TaskState.task_id"),
            version=check_int(require(data, "version", "TaskState"), "TaskState.version"),
            status=check_enum(require(data, "status", "TaskState"), E.TaskStatus, "TaskState.status"),
            current_stage=check_str(require(data, "current_stage", "TaskState"), "TaskState.current_stage"),
            plan=[PlanStep.from_dict(item, f"TaskState.plan[{i}]") for i, item in enumerate(plan_raw)],
            todos=[Todo.from_dict(item, f"TaskState.todos[{i}]") for i, item in enumerate(todos_raw)],
            budget=Budget.from_dict(require(data, "budget", "TaskState")),
            artifacts=check_str_list(require(data, "artifacts", "TaskState"), "TaskState.artifacts"),
            subtasks=None if subtasks is None else check_str_list(subtasks, "TaskState.subtasks"),
            evidence_refs=check_str_list(require(data, "evidence_refs", "TaskState"), "TaskState.evidence_refs"),
            context_manifest_hash=check_str(
                require(data, "context_manifest_hash", "TaskState"), "TaskState.context_manifest_hash"
            ),
            updated_at=check_timestamp(require(data, "updated_at", "TaskState"), "TaskState.updated_at"),
        )

    def to_dict(self) -> dict:
        out = asdict_plain(self)
        # PriceWindow 的契约字段名是 from/to（Python 关键字，内部改名存取）
        if self.budget.price_window is not None:
            out["budget"]["price_window"] = self.budget.price_window.to_dict()
        return out


# ---------------------------------------------------------------- §2.4
@dataclass
class ContextSource:
    """ContextManifest.sources[]。"""

    name: str
    type: E.SourceType
    tokens: int
    priority: Any  # 数值或等级串，契约未约束类型
    origin: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str) -> "ContextSource":
        check_keys(data, ("name", "type", "tokens", "priority", "origin"), path)
        return cls(
            name=check_str(require(data, "name", path), f"{path}.name"),
            type=check_enum(require(data, "type", path), E.SourceType, f"{path}.type"),
            tokens=check_int(require(data, "tokens", path), f"{path}.tokens"),
            priority=require(data, "priority", path),
            origin=check_str(require(data, "origin", path), f"{path}.origin"),
        )


@dataclass
class ContextManifest:
    """M2→M1 每轮生成（01 §2.4）。

    hash 确定性：同 task 状态 + 同轮输入 → 必须同 hash（纯函数，无时钟泄漏）。
    """

    task_id: str
    turn: int
    sources: list
    total_tokens: int
    budget_remaining: int
    compiled_at: str  # UTC ISO-8601
    hash: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContextManifest":
        check_keys(data, (
            "task_id", "turn", "sources", "total_tokens", "budget_remaining",
            "compiled_at", "hash",
        ), "ContextManifest")
        sources_raw = require(data, "sources", "ContextManifest")
        if not isinstance(sources_raw, list):
            raise _ContractError("ContextManifest.sources", "必须是列表")
        return cls(
            task_id=check_str(require(data, "task_id", "ContextManifest"), "ContextManifest.task_id"),
            turn=check_int(require(data, "turn", "ContextManifest"), "ContextManifest.turn"),
            sources=[ContextSource.from_dict(item, f"ContextManifest.sources[{i}]") for i, item in enumerate(sources_raw)],
            total_tokens=check_int(require(data, "total_tokens", "ContextManifest"), "ContextManifest.total_tokens"),
            budget_remaining=check_int(
                require(data, "budget_remaining", "ContextManifest"), "ContextManifest.budget_remaining"
            ),
            compiled_at=check_timestamp(
                require(data, "compiled_at", "ContextManifest"), "ContextManifest.compiled_at"
            ),
            hash=check_str(require(data, "hash", "ContextManifest"), "ContextManifest.hash"),
        )

    def to_dict(self) -> dict:
        return asdict_plain(self)


# ---------------------------------------------------------------- §2.5
@dataclass
class EventRecord:
    """全系统事件，追加写 runtime/events/*.jsonl（01 §2.5）。

    横切约定（01 §8）：缺 trace_id 的事件在写入时被拒（from_dict 强制）。
    """

    event_id: str
    type: E.EventType
    subject: str
    payload: dict
    occurred_at: str  # UTC ISO-8601
    trace_id: str
    producer: str  # 模块 id

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EventRecord":
        check_keys(data, (
            "event_id", "type", "subject", "payload", "occurred_at", "trace_id", "producer",
        ), "EventRecord")
        return cls(
            event_id=check_id(require(data, "event_id", "EventRecord"), "EventRecord.event_id"),
            type=check_enum(require(data, "type", "EventRecord"), E.EventType, "EventRecord.type"),
            subject=check_str(require(data, "subject", "EventRecord"), "EventRecord.subject"),
            payload=check_mapping(require(data, "payload", "EventRecord"), "EventRecord.payload"),
            occurred_at=check_timestamp(require(data, "occurred_at", "EventRecord"), "EventRecord.occurred_at"),
            trace_id=check_str(require(data, "trace_id", "EventRecord"), "EventRecord.trace_id"),
            producer=check_str(require(data, "producer", "EventRecord"), "EventRecord.producer"),
        )

    def to_dict(self) -> dict:
        return asdict_plain(self)


# ---------------------------------------------------------------- §2.6
@dataclass
class CreatedBy:
    """ArtifactRecord.created_by。"""

    task_id: str
    action_id: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str) -> "CreatedBy":
        check_keys(data, ("task_id", "action_id"), path)
        return cls(
            task_id=check_str(require(data, "task_id", path), f"{path}.task_id"),
            action_id=check_str(require(data, "action_id", path), f"{path}.action_id"),
        )


@dataclass
class ValidationCheck:
    """ArtifactRecord.validation.checks[]。"""

    name: str
    passed: bool
    detail: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str) -> "ValidationCheck":
        check_keys(data, ("name", "passed", "detail"), path)
        return cls(
            name=check_str(require(data, "name", path), f"{path}.name"),
            passed=check_bool(require(data, "passed", path), f"{path}.passed"),
            detail=check_str(require(data, "detail", path), f"{path}.detail"),
        )


@dataclass
class ArtifactValidation:
    """ArtifactRecord.validation。"""

    passed: bool
    checks: list

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str) -> "ArtifactValidation":
        check_keys(data, ("passed", "checks"), path)
        checks_raw = require(data, "checks", path)
        if not isinstance(checks_raw, list):
            raise _ContractError(f"{path}.checks", "必须是列表")
        return cls(
            passed=check_bool(require(data, "passed", path), f"{path}.passed"),
            checks=[ValidationCheck.from_dict(item, f"{path}.checks[{i}]") for i, item in enumerate(checks_raw)],
        )


@dataclass
class ArtifactRecord:
    """M2 持有（01 §2.6）。"""

    artifact_id: str
    type: E.ArtifactType
    status: E.ArtifactStatus
    schema_id: str  # 内容 schema 版本，如 "report.daily@v1"
    content_ref: str  # workspace 内相对路径
    created_by: CreatedBy
    version: int
    validation: ArtifactValidation | None = None
    supersedes: str | None = None  # 替代链

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactRecord":
        check_keys(data, (
            "artifact_id", "type", "status", "schema_id", "content_ref",
            "created_by", "validation", "version", "supersedes",
        ), "ArtifactRecord")
        validation = data.get("validation")
        supersedes = data.get("supersedes")
        return cls(
            artifact_id=check_id(require(data, "artifact_id", "ArtifactRecord"), "ArtifactRecord.artifact_id"),
            type=check_enum(require(data, "type", "ArtifactRecord"), E.ArtifactType, "ArtifactRecord.type"),
            status=check_enum(require(data, "status", "ArtifactRecord"), E.ArtifactStatus, "ArtifactRecord.status"),
            schema_id=check_str(require(data, "schema_id", "ArtifactRecord"), "ArtifactRecord.schema_id"),
            content_ref=check_str(require(data, "content_ref", "ArtifactRecord"), "ArtifactRecord.content_ref"),
            created_by=CreatedBy.from_dict(require(data, "created_by", "ArtifactRecord"), "ArtifactRecord.created_by"),
            version=check_int(require(data, "version", "ArtifactRecord"), "ArtifactRecord.version"),
            validation=None if validation is None else ArtifactValidation.from_dict(validation, "ArtifactRecord.validation"),
            supersedes=None if supersedes is None else check_str(supersedes, "ArtifactRecord.supersedes"),
        )

    def to_dict(self) -> dict:
        return asdict_plain(self)
