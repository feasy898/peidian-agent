# -*- coding: utf-8 -*-
"""m3_action · Action Gateway（行动层，specs/M3-action-gateway.md）。

能力注册（CapabilityDescriptor：schema+风险声明+幂等键策略）、ActionRequest 契约
校验、Policy 三值判定（ALLOW/ASK/DENY）、审批队列与超时、REAL/SIMULATION 执行
路由、Observation 证据三态、幂等、write-path 负向测试件。

冻结 API（01 §3.3）由 :class:`ActionGateway` 承载：
``register_capability / execute_action / query_policy / submit_approval``。
"""
from __future__ import annotations

from .approval import ApprovalEntry, ApprovalQueue, DEFAULT_APPROVAL_TIMEOUT_S
from .events import EventJournal, EventWriteError
from .executor import IdempotencyConflictError, IdempotentExecutor
from .gateway import ACTION_TRANSITIONS, ActionGateway, IllegalTransitionError
from .observer import OBSERVATION_MISMATCH, Observer
from .policy_engine import PolicyEngine, PolicyVerdict
from .registry import (
    IMMUTABLE_DENY_ACTIONS,
    PERMANENT_ASK_ACTIONS,
    CapabilityDescriptor,
    CapabilityRegistry,
    assert_immutable_consistency,
    load_actions_table,
    load_default_registry,
    registry_vs_actions_table_diff,
)
from .router import Router, RouterModeError
from .validator import RequestValidator, validate_params_schema

__all__ = [
    "ActionGateway",
    "IllegalTransitionError",
    "ACTION_TRANSITIONS",
    "CapabilityDescriptor",
    "CapabilityRegistry",
    "load_default_registry",
    "load_actions_table",
    "registry_vs_actions_table_diff",
    "assert_immutable_consistency",
    "IMMUTABLE_DENY_ACTIONS",
    "PERMANENT_ASK_ACTIONS",
    "PolicyEngine",
    "PolicyVerdict",
    "RequestValidator",
    "validate_params_schema",
    "ApprovalQueue",
    "ApprovalEntry",
    "DEFAULT_APPROVAL_TIMEOUT_S",
    "EventJournal",
    "EventWriteError",
    "IdempotentExecutor",
    "IdempotencyConflictError",
    "Observer",
    "OBSERVATION_MISMATCH",
    "Router",
    "RouterModeError",
]
