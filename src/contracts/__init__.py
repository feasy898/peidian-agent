# -*- coding: utf-8 -*-
"""src/contracts · 冻结契约代码化（specs/01-contracts.md §2，ADDENDUM 升版 v1.1）。

导出全部 12 个冻结数据结构（§2.1–§2.12）与全部受控枚举。
- ``<结构>.from_dict(data)``：加载即校验（字段必填/类型/枚举封闭集/时间戳 UTC/未知字段拒绝）；
- ``<结构>.to_dict()``：无损序列化回普通 dict（round-trip 逐字段相等）。

变更纪律：本包是 01 §2 的机械映射，改动必须走 01 §7 契约变更流程，
禁止跳过评审直接修改（01 §7.4）。
"""
from __future__ import annotations

from .assets import (
    CostTotal,
    Disclosure,
    ExpectedBehavior,
    GoldenCase,
    GoldenScores,
    Outcome,
    ReleaseBundle,
    SkillDescriptor,
    SkillEntry,
    TrajectoryRecord,
    TrajectoryStep,
)
from .base import ContractValidationError
from .core import (
    ActionError,
    ActionRequest,
    ActionResult,
    Actor,
    ArtifactRecord,
    ArtifactValidation,
    Budget,
    ContextManifest,
    ContextSource,
    CreatedBy,
    EventRecord,
    Evidence,
    PlanStep,
    PriceWindow,
    Risk,
    TaskState,
    Todo,
    ValidationCheck,
)
from .enums import (
    ActionStatus,
    AlarmLevel,
    ArtifactStatus,
    ArtifactType,
    BehaviorAct,
    CapabilityDomain,
    DeviceState,
    EventType,
    EvidenceKind,
    GoldenJudge,
    GoldenSource,
    MemoryType,
    Persona,
    PolicyDecision,
    PricePeriodType,
    RiskLevel,
    SkillStatus,
    SourceType,
    SutTarget,
    TodoStatus,
    TrajectoryStepType,
    WorkOrderStatus,
    SwitchOrderStatus,
    TaskStatus,
    CONTROLLED_VOCABULARY,
)
from .simulation import (
    BehaviorStep,
    Constraints,
    Environment,
    EvidencePackItem,
    FaultInjection,
    Interactions,
    Metric,
    PlannedEvent,
    Provenance,
    Reproduction,
    ScenarioIdentity,
    ScenarioSpec,
    SimRunResult,
    Sut,
    UserModel,
)

__all__ = [
    # 数据结构（§2.1-§2.12）
    "ActionRequest", "ActionResult", "TaskState", "ContextManifest",
    "EventRecord", "ArtifactRecord", "SkillDescriptor", "ScenarioSpec",
    "SimRunResult", "GoldenCase", "TrajectoryRecord", "ReleaseBundle",
    # 嵌套子结构
    "Actor", "Risk", "Evidence", "ActionError", "PlanStep", "Todo",
    "PriceWindow", "Budget", "ContextSource", "CreatedBy", "ValidationCheck",
    "ArtifactValidation", "ScenarioIdentity", "Sut", "FaultInjection",
    "Environment", "BehaviorStep", "UserModel", "Interactions", "PlannedEvent",
    "Constraints", "Metric", "Provenance", "EvidencePackItem", "Reproduction",
    "Disclosure", "SkillEntry", "ExpectedBehavior", "TrajectoryStep",
    "Outcome", "CostTotal", "GoldenScores",
    # 枚举
    "AlarmLevel", "TaskStatus", "ActionStatus", "ArtifactStatus", "DeviceState",
    "WorkOrderStatus", "SwitchOrderStatus", "PricePeriodType", "MemoryType",
    "RiskLevel", "PolicyDecision", "ArtifactType", "SourceType", "EventType",
    "CapabilityDomain", "SkillStatus", "TodoStatus", "SutTarget", "Persona",
    "BehaviorAct", "EvidenceKind", "GoldenJudge", "GoldenSource",
    "TrajectoryStepType", "CONTROLLED_VOCABULARY",
    # 异常与元数据
    "ContractValidationError", "STRUCTURES", "CONTRACT_VERSION", "EVENT_CATALOG",
]

#: 冻结契约版本：01-contracts v1.0 + ADDENDUM（v1.0 → v1.1）
CONTRACT_VERSION = "1.1"

#: 结构名 → 数据类（供通用执行器/插件按名取用）
STRUCTURES = {
    "ActionRequest": ActionRequest,
    "ActionResult": ActionResult,
    "TaskState": TaskState,
    "ContextManifest": ContextManifest,
    "EventRecord": EventRecord,
    "ArtifactRecord": ArtifactRecord,
    "SkillDescriptor": SkillDescriptor,
    "ScenarioSpec": ScenarioSpec,
    "SimRunResult": SimRunResult,
    "GoldenCase": GoldenCase,
    "TrajectoryRecord": TrajectoryRecord,
    "ReleaseBundle": ReleaseBundle,
}

#: 事件主题目录（01 §4 + ADDENDUM §C，字符串字面量即事件 type）
EVENT_CATALOG = [e.value for e in EventType]
