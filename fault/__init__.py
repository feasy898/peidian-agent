# -*- coding: utf-8 -*-
"""fault · 园区配电故障注入与 agent 反应（worker-B · 线3）。

模块图：engine（编排）→ dsl（故障白名单校验）→ telemetry（伪遥测）→
detect（异常检测）→ agent（可解释步骤流）→ actions（人机同款操作面）→
stream（事件流 JSONL）；llm_bridge（自然语言定向注入，LLM+规则兜底）。
接口契约与集成说明见 fault/README.md。
"""
from .actions import ActionExecutor, OPS_WHITELIST
from .agent import AgentResponder, SIGNATURES
from .detect import Anomaly, Detector, TH_PV_MIN, TH_SC_CURRENT, \
    TH_TX_TRIP, TH_TX_WARN
from .dsl import (COMPAT_KINDS, DEFAULT_PARAMS, FAULT_TYPES, FaultRejected,
                  FaultSpec, fault_to_yaml, parse_fault_yaml,
                  validate_fault_dict)
from .engine import Engine
from .llm_bridge import HigressClient, nl_to_fault, parse_llm_output, \
    render_prompt, rule_parse
from .stream import EventBus
from .telemetry import DAYLIGHT, TelemetryModel
from .topology import Topology, demo_park

__version__ = "0.1.0"

__all__ = [
    "Engine", "EventBus", "Topology", "demo_park",
    "FaultSpec", "FaultRejected", "FAULT_TYPES", "COMPAT_KINDS",
    "DEFAULT_PARAMS", "validate_fault_dict", "parse_fault_yaml",
    "fault_to_yaml",
    "Detector", "Anomaly", "TH_TX_WARN", "TH_TX_TRIP", "TH_SC_CURRENT",
    "TH_PV_MIN",
    "AgentResponder", "SIGNATURES", "ActionExecutor", "OPS_WHITELIST",
    "TelemetryModel", "DAYLIGHT",
    "nl_to_fault", "rule_parse", "parse_llm_output", "render_prompt",
    "HigressClient",
]
