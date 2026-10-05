# -*- coding: utf-8 -*-
"""冻结数据结构（二）：仿真层（specs/01-contracts.md §2.8–§2.9）。

- ScenarioSpec（M5 场景规格，十字段组）
- SimRunResult（M5 输出，三层证据分离）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from . import enums as E
from .base import (
    ContractValidationError as _ContractError,
    asdict_plain,
    check_bool,
    check_enum,
    check_float,
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
    "check_time_ref",
    "ScenarioIdentity",
    "Sut",
    "FaultInjection",
    "Environment",
    "BehaviorStep",
    "UserModel",
    "Interactions",
    "PlannedEvent",
    "Constraints",
    "Metric",
    "Provenance",
    "ScenarioSpec",
    "EvidencePackItem",
    "Reproduction",
    "SimRunResult",
]


# ---------------------------------------------------------------- §2.8
@dataclass
class ScenarioIdentity:
    """ScenarioSpec.identity。"""

    scenario_id: str
    version: str
    owner: str
    tags: list

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "identity") -> "ScenarioIdentity":
        check_keys(data, ("scenario_id", "version", "owner", "tags"), path)
        return cls(
            scenario_id=check_str(require(data, "scenario_id", path), f"{path}.scenario_id"),
            version=check_str(require(data, "version", path), f"{path}.version"),
            owner=check_str(require(data, "owner", path), f"{path}.owner"),
            tags=check_str_list(require(data, "tags", path), f"{path}.tags"),
        )


@dataclass
class Sut:
    """ScenarioSpec.sut（system under test）。"""

    target: E.SutTarget
    module: str | None = None
    agent_release: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "sut") -> "Sut":
        check_keys(data, ("target", "module", "agent_release"), path)
        module = data.get("module")
        agent_release = data.get("agent_release")
        if module is not None:
            check_str(module, f"{path}.module")
        return cls(
            target=check_enum(require(data, "target", path), E.SutTarget, f"{path}.target"),
            module=module,
            agent_release=None if agent_release is None else check_str(agent_release, f"{path}.agent_release"),
        )


def check_time_ref(value: Any, path: str) -> Any:
    """时间引用（ScenarioSpec 的 at 字段）：非空字符串或 datetime 对象均接受。

    契约未约束 at 的格式（可为绝对时刻或场景相对时间，由 M5 约定）；
    pyyaml 会把未加引号的 ISO 时刻解析为 datetime，故两种形态都放行。
    """
    from datetime import datetime as _dt

    if isinstance(value, _dt):
        return value
    return check_str(value, path)


@dataclass
class FaultInjection:
    """ScenarioSpec.environment.injections[]。"""

    at: str  # 仿真时刻（ISO-8601 或场景相对时间，由 M5 约定）
    type: str
    target: str
    params: dict

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str) -> "FaultInjection":
        check_keys(data, ("at", "type", "target", "params"), path)
        return cls(
            at=check_time_ref(require(data, "at", path), f"{path}.at"),
            type=check_str(require(data, "type", path), f"{path}.type"),
            target=check_str(require(data, "target", path), f"{path}.target"),
            params=check_mapping(require(data, "params", path), f"{path}.params"),
        )


@dataclass
class Environment:
    """ScenarioSpec.environment。"""

    park_instance: str  # 按名解析实例文件（ADDENDUM §D：PARK_INSTANCE_PATH 追加搜索目录）
    clock_start: str  # UTC ISO-8601
    speed: float  # 仿真时间流速
    injections: list

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "environment") -> "Environment":
        check_keys(data, ("park_instance", "clock_start", "speed", "injections"), path)
        injections_raw = require(data, "injections", path)
        if not isinstance(injections_raw, list):
            raise _ContractError(f"{path}.injections", "必须是列表")
        return cls(
            park_instance=check_str(require(data, "park_instance", path), f"{path}.park_instance"),
            clock_start=check_timestamp(require(data, "clock_start", path), f"{path}.clock_start"),
            speed=check_float(require(data, "speed", path), f"{path}.speed"),
            injections=[
                FaultInjection.from_dict(item, f"{path}.injections[{i}]") for i, item in enumerate(injections_raw)
            ],
        )


@dataclass
class BehaviorStep:
    """ScenarioSpec.user_model.behavior_script[]。"""

    at: str
    act: E.BehaviorAct
    text: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str) -> "BehaviorStep":
        check_keys(data, ("at", "act", "text"), path)
        text = data.get("text")
        return cls(
            at=check_time_ref(require(data, "at", path), f"{path}.at"),
            act=check_enum(require(data, "act", path), E.BehaviorAct, f"{path}.act"),
            text=None if text is None else check_str(text, f"{path}.text"),
        )


@dataclass
class UserModel:
    """ScenarioSpec.user_model。"""

    persona: E.Persona
    behavior_script: list

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "user_model") -> "UserModel":
        check_keys(data, ("persona", "behavior_script"), path)
        script_raw = require(data, "behavior_script", path)
        if not isinstance(script_raw, list):
            raise _ContractError(f"{path}.behavior_script", "必须是列表")
        return cls(
            persona=check_enum(require(data, "persona", path), E.Persona, f"{path}.persona"),
            behavior_script=[
                BehaviorStep.from_dict(item, f"{path}.behavior_script[{i}]") for i, item in enumerate(script_raw)
            ],
        )


@dataclass
class Interactions:
    """ScenarioSpec.interactions。"""

    max_turns: int
    timeout_s: int

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "interactions") -> "Interactions":
        check_keys(data, ("max_turns", "timeout_s"), path)
        return cls(
            max_turns=check_int(require(data, "max_turns", path), f"{path}.max_turns"),
            timeout_s=check_int(require(data, "timeout_s", path), f"{path}.timeout_s"),
        )


@dataclass
class PlannedEvent:
    """ScenarioSpec.events[]（环境事件计划：告警/量测/开关变位）。"""

    at: str
    type: str
    subject: str
    params: dict

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str) -> "PlannedEvent":
        check_keys(data, ("at", "type", "subject", "params"), path)
        return cls(
            at=check_time_ref(require(data, "at", path), f"{path}.at"),
            type=check_str(require(data, "type", path), f"{path}.type"),
            subject=check_str(require(data, "subject", path), f"{path}.subject"),
            params=check_mapping(require(data, "params", path), f"{path}.params"),
        )


@dataclass
class Constraints:
    """ScenarioSpec.constraints。"""

    budget: dict  # {token, action}
    stop_conditions: list

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "constraints") -> "Constraints":
        check_keys(data, ("budget", "stop_conditions"), path)
        budget = check_mapping(require(data, "budget", path), f"{path}.budget")
        for key in ("token", "action"):
            if key not in budget:
                raise _ContractError(f"{path}.budget.{key}", "必填字段缺失")
        return cls(
            budget=budget,
            stop_conditions=check_str_list(require(data, "stop_conditions", path), f"{path}.stop_conditions"),
        )


@dataclass
class Metric:
    """ScenarioSpec.metrics[]（判据引用：黄金判据或规程条款）。"""

    name: str
    rubric: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str) -> "Metric":
        check_keys(data, ("name", "rubric"), path)
        return cls(
            name=check_str(require(data, "name", path), f"{path}.name"),
            rubric=check_str(require(data, "rubric", path), f"{path}.rubric"),
        )


@dataclass
class Provenance:
    """ScenarioSpec.provenance。"""

    source: str
    created_at: str  # UTC ISO-8601
    notes: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "provenance") -> "Provenance":
        check_keys(data, ("source", "created_at", "notes"), path)
        return cls(
            source=check_str(require(data, "source", path), f"{path}.source"),
            created_at=check_timestamp(require(data, "created_at", path), f"{path}.created_at"),
            notes=check_str(require(data, "notes", path), f"{path}.notes"),
        )


@dataclass
class ScenarioSpec:
    """M5 场景规格，十字段组（01 §2.8）。"""

    identity: ScenarioIdentity
    sut: Sut
    environment: Environment
    user_model: UserModel
    interactions: Interactions
    events: list
    constraints: Constraints
    metrics: list
    provenance: Provenance

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScenarioSpec":
        check_keys(data, (
            "identity", "sut", "environment", "user_model", "interactions",
            "events", "constraints", "metrics", "provenance",
        ), "ScenarioSpec")
        events_raw = require(data, "events", "ScenarioSpec")
        if not isinstance(events_raw, list):
            raise _ContractError("ScenarioSpec.events", "必须是列表")
        metrics_raw = require(data, "metrics", "ScenarioSpec")
        if not isinstance(metrics_raw, list):
            raise _ContractError("ScenarioSpec.metrics", "必须是列表")
        return cls(
            identity=ScenarioIdentity.from_dict(require(data, "identity", "ScenarioSpec")),
            sut=Sut.from_dict(require(data, "sut", "ScenarioSpec")),
            environment=Environment.from_dict(require(data, "environment", "ScenarioSpec")),
            user_model=UserModel.from_dict(require(data, "user_model", "ScenarioSpec")),
            interactions=Interactions.from_dict(require(data, "interactions", "ScenarioSpec")),
            events=[PlannedEvent.from_dict(item, f"ScenarioSpec.events[{i}]") for i, item in enumerate(events_raw)],
            constraints=Constraints.from_dict(require(data, "constraints", "ScenarioSpec")),
            metrics=[Metric.from_dict(item, f"ScenarioSpec.metrics[{i}]") for i, item in enumerate(metrics_raw)],
            provenance=Provenance.from_dict(require(data, "provenance", "ScenarioSpec")),
        )

    def to_dict(self) -> dict:
        return asdict_plain(self)


# ---------------------------------------------------------------- §2.9
@dataclass
class EvidencePackItem:
    """SimRunResult.evidence_pack[]。"""

    kind: E.EvidenceKind
    ref: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str) -> "EvidencePackItem":
        check_keys(data, ("kind", "ref"), path)
        return cls(
            kind=check_enum(require(data, "kind", path), E.EvidenceKind, f"{path}.kind"),
            ref=check_str(require(data, "ref", path), f"{path}.ref"),
        )


@dataclass
class Reproduction:
    """SimRunResult.reproduction。"""

    deterministic: bool  # 同 seed 同轨迹必须 true
    seed: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "reproduction") -> "Reproduction":
        check_keys(data, ("deterministic", "seed"), path)
        return cls(
            deterministic=check_bool(require(data, "deterministic", path), f"{path}.deterministic"),
            seed=check_str(require(data, "seed", path), f"{path}.seed"),
        )


@dataclass
class SimRunResult:
    """M5 输出，三层证据分离（01 §2.9）。"""

    run_id: str
    scenario_id: str
    manifest_hash: str  # ScenarioSpec 内容 hash（复现性）
    traj_ref: str  # TrajectoryRecord 引用
    state_final: dict  # 仿真环境终态
    evidence_pack: list
    reproduction: Reproduction

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SimRunResult":
        check_keys(data, (
            "run_id", "scenario_id", "manifest_hash", "traj_ref", "state_final",
            "evidence_pack", "reproduction",
        ), "SimRunResult")
        pack_raw = require(data, "evidence_pack", "SimRunResult")
        if not isinstance(pack_raw, list):
            raise _ContractError("SimRunResult.evidence_pack", "必须是列表")
        return cls(
            run_id=check_id(require(data, "run_id", "SimRunResult"), "SimRunResult.run_id"),
            scenario_id=check_str(require(data, "scenario_id", "SimRunResult"), "SimRunResult.scenario_id"),
            manifest_hash=check_str(require(data, "manifest_hash", "SimRunResult"), "SimRunResult.manifest_hash"),
            traj_ref=check_str(require(data, "traj_ref", "SimRunResult"), "SimRunResult.traj_ref"),
            state_final=check_mapping(require(data, "state_final", "SimRunResult"), "SimRunResult.state_final"),
            evidence_pack=[
                EvidencePackItem.from_dict(item, f"SimRunResult.evidence_pack[{i}]") for i, item in enumerate(pack_raw)
            ],
            reproduction=Reproduction.from_dict(require(data, "reproduction", "SimRunResult")),
        )

    def to_dict(self) -> dict:
        return asdict_plain(self)
