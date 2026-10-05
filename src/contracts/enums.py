# -*- coding: utf-8 -*-
"""受控词表（封闭枚举集）。

来源与对应关系（逐字一致，大小写敏感）：
- 00-ontology.md §2 的 11 个封闭集：alarm_level / task_status / action_status /
  artifact_status / device_state / work_order_status / switch_order_status /
  price_period_type / memory_type / risk_level / policy_decision；
- 01-contracts.md §2 各数据结构内联枚举：artifact_type / source_type /
  capability_domain / skill_status / todo_status / sut_target / persona /
  behavior_act / evidence_kind / golden_judge / golden_source /
  trajectory_step_type；
- 01-contracts.md §4 事件清单 + ADDENDUM §C 两条增补 → event_type。

这些枚举与 ``ontology/enums.yaml`` 同源；一致性由 EVAL 用例（enum_closure）断言。
"""
from __future__ import annotations

from enum import Enum

__all__ = [
    "AlarmLevel",
    "TaskStatus",
    "ActionStatus",
    "ArtifactStatus",
    "DeviceState",
    "WorkOrderStatus",
    "SwitchOrderStatus",
    "PricePeriodType",
    "MemoryType",
    "RiskLevel",
    "PolicyDecision",
    "ArtifactType",
    "SourceType",
    "EventType",
    "CapabilityDomain",
    "SkillStatus",
    "TodoStatus",
    "SutTarget",
    "Persona",
    "BehaviorAct",
    "EvidenceKind",
    "GoldenJudge",
    "GoldenSource",
    "TrajectoryStepType",
    "CONTROLLED_VOCABULARY",
]


class AlarmLevel(str, Enum):
    """告警级别（P0=紧急 5min 响应 / P1=重要 30min / P2=一般 4h / P3=提示 24h）。"""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class TaskStatus(str, Enum):
    """任务状态（01 §5.1 十态）。"""

    CREATED = "CREATED"
    RUNNING = "RUNNING"
    WAITING_INPUT = "WAITING_INPUT"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    WAITING_EVENT = "WAITING_EVENT"
    PAUSED = "PAUSED"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ActionStatus(str, Enum):
    """动作生命周期状态（01 §5.2）。"""

    REQUESTED = "REQUESTED"
    POLICY_DECIDED = "POLICY_DECIDED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    DENIED = "DENIED"
    COMPENSATED = "COMPENSATED"


class ArtifactStatus(str, Enum):
    """Artifact 状态（01 §5.3）。"""

    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    READY = "READY"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


class DeviceState(str, Enum):
    """设备运行状态。"""

    RUNNING = "RUNNING"
    MAINTENANCE = "MAINTENANCE"
    HOT_STANDBY = "HOT_STANDBY"
    COLD_STANDBY = "COLD_STANDBY"
    FAULT = "FAULT"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_VERIFY = "PENDING_VERIFY"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SwitchOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PricePeriodType(str, Enum):
    """电价时段类型（尖/峰/平/谷）。"""

    PEAK = "PEAK"
    SHARP = "SHARP"
    FLAT = "FLAT"
    VALLEY = "VALLEY"


class MemoryType(str, Enum):
    WORKING = "WORKING"
    EPISODIC = "EPISODIC"
    SEMANTIC = "SEMANTIC"
    PROCEDURAL = "PROCEDURAL"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PolicyDecision(str, Enum):
    ALLOW = "ALLOW"
    ASK = "ASK"
    DENY = "DENY"


class ArtifactType(str, Enum):
    """01 §2.6。"""

    REPORT = "REPORT"
    WORK_ORDER = "WORK_ORDER"
    SWITCH_ORDER = "SWITCH_ORDER"
    INSPECTION_RECORD = "INSPECTION_RECORD"
    ANALYSIS_RESULT = "ANALYSIS_RESULT"
    DATASET = "DATASET"


class SourceType(str, Enum):
    """ContextManifest source type（01 §2.4，14 值封闭集）。"""

    SYSTEM_POLICY = "SYSTEM_POLICY"
    AGENT_CONTRACT = "AGENT_CONTRACT"
    TENANT_RULE = "TENANT_RULE"
    RUNTIME_REMINDER = "RUNTIME_REMINDER"
    SKILL = "SKILL"
    TOOL_DESCRIPTOR = "TOOL_DESCRIPTOR"
    GOAL_STEERING = "GOAL_STEERING"
    PLAN_TODO = "PLAN_TODO"
    RECENT_INTERACTION = "RECENT_INTERACTION"
    COMPACTED_HISTORY = "COMPACTED_HISTORY"
    RETRIEVED_MEMORY = "RETRIEVED_MEMORY"
    RETRIEVED_KNOWLEDGE = "RETRIEVED_KNOWLEDGE"
    ONTOLOGY_VIEW = "ONTOLOGY_VIEW"
    WORKSPACE_REF = "WORKSPACE_REF"


class EventType(str, Enum):
    """事件主题（01 §4 + ADDENDUM §C 两条增补，共 28 个）。"""

    # 任务
    TASK_CREATED = "task.created"
    TASK_STATUS_CHANGED = "task.status_changed"
    TASK_STAGE_GATE = "task.stage_gate"
    # 动作
    ACTION_REQUESTED = "action.requested"
    ACTION_POLICY_DECIDED = "action.policy_decided"
    ACTION_WAITING_APPROVAL = "action.waiting_approval"
    ACTION_EXECUTING = "action.executing"
    ACTION_COMPLETED = "action.completed"
    # 产物
    ARTIFACT_STATE_CHANGED = "artifact.state_changed"
    # 环境
    ALARM_RAISED = "alarm.raised"
    ALARM_CLEARED = "alarm.cleared"
    MEASUREMENT_UPDATED = "measurement.updated"
    GRID_EVENT = "grid.event"
    # 审批
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_DENIED = "approval.denied"
    APPROVAL_TIMEOUT = "approval.timeout"
    # 飞轮
    TRAJECTORY_EXPORTED = "trajectory.exported"
    GOLDEN_CASE_ADDED = "golden.case_added"
    BADCASE_OPENED = "badcase.opened"
    SKILL_PROMOTED = "skill.promoted"
    # 资产
    RELEASE_PUBLISHED = "release.published"
    # 预算
    BUDGET_EXHAUSTED = "budget.exhausted"
    BUDGET_WARNING = "budget.warning"
    # 仿真
    SIM_INJECTED = "sim.injected"
    SIM_COMPLETED = "sim.completed"
    # ADDENDUM §C 增补
    PRICE_PERIOD_CHANGED = "price.period_changed"
    DEMAND_MONTH_ROLLED = "demand.month_rolled"


class CapabilityDomain(str, Enum):
    """01 §2.7。"""

    PREDICT = "PREDICT"
    DISPATCH = "DISPATCH"
    MAINTAIN = "MAINTAIN"
    PLAN = "PLAN"
    SELF_HEAL = "SELF_HEAL"
    TRADE = "TRADE"


class SkillStatus(str, Enum):
    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"


class TodoStatus(str, Enum):
    """01 §2.3 todos[].status。"""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


class SutTarget(str, Enum):
    """ScenarioSpec.sut.target。"""

    AGENT = "AGENT"
    MODULE = "MODULE"


class Persona(str, Enum):
    """ScenarioSpec.user_model.persona。"""

    OPERATOR = "OPERATOR"
    DISPATCHER = "DISPATCHER"
    APPROVER = "APPROVER"


class BehaviorAct(str, Enum):
    """ScenarioSpec.user_model.behavior_script[].act。"""

    USER_INPUT = "USER_INPUT"
    GRANT = "GRANT"
    DENY = "DENY"
    LEAVE = "LEAVE"


class EvidenceKind(str, Enum):
    """SimRunResult.evidence_pack[].kind（三层证据分离）。"""

    INTERACTION_LOG = "INTERACTION_LOG"
    STATE_TRANSITIONS = "STATE_TRANSITIONS"
    TIMELINE = "TIMELINE"


class GoldenJudge(str, Enum):
    """GoldenCase.expected_behavior[].judge。"""

    DETERMINISTIC = "DETERMINISTIC"
    RUBRIC = "RUBRIC"


class GoldenSource(str, Enum):
    """GoldenCase.source。"""

    HANDWRITTEN = "HANDWRITTEN"
    TRAJECTORY_MINED = "TRAJECTORY_MINED"
    REGENERATED = "REGENERATED"


class TrajectoryStepType(str, Enum):
    """TrajectoryRecord.steps[].type（四类事件）。"""

    MODEL_CALL = "MODEL_CALL"
    TOOL_CALL = "TOOL_CALL"
    STATE_CHANGE = "STATE_CHANGE"
    APPROVAL = "APPROVAL"


#: 00 §2 受控词表 → 本模块枚举类的机械映射（供 enum_closure 一致性断言使用）
CONTROLLED_VOCABULARY = {
    "alarm_level": AlarmLevel,
    "task_status": TaskStatus,
    "action_status": ActionStatus,
    "artifact_status": ArtifactStatus,
    "device_state": DeviceState,
    "work_order_status": WorkOrderStatus,
    "switch_order_status": SwitchOrderStatus,
    "price_period_type": PricePeriodType,
    "memory_type": MemoryType,
    "risk_level": RiskLevel,
    "policy_decision": PolicyDecision,
}
