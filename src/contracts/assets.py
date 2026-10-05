# -*- coding: utf-8 -*-
"""冻结数据结构（三）：资产层（specs/01-contracts.md §2.7、§2.10–§2.12）。

- SkillDescriptor（M7 持有，M2 披露）
- GoldenCase（M6 黄金集）
- TrajectoryRecord（M6 采集）
- ReleaseBundle（M7 打包）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from . import enums as E
from .base import (
    ContractValidationError as _ContractError,
    asdict_plain,
    check_enum,
    check_id,
    check_int,
    check_keys,
    check_mapping,
    check_str,
    check_str_list,
    require,
)

__all__ = [
    "Disclosure",
    "SkillEntry",
    "SkillDescriptor",
    "ExpectedBehavior",
    "GoldenCase",
    "TrajectoryStep",
    "Outcome",
    "CostTotal",
    "TrajectoryRecord",
    "GoldenScores",
    "ReleaseBundle",
]


# ---------------------------------------------------------------- §2.7
@dataclass
class Disclosure:
    """SkillDescriptor.disclosure（渐进披露三级）。"""

    level0: str  # 名称（常驻 System Context，≤10 词）
    level1: str  # 一段描述（目录层）
    level2_ref: str  # 全文（加载进上下文才计费）

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "disclosure") -> "Disclosure":
        check_keys(data, ("level0", "level1", "level2_ref"), path)
        return cls(
            level0=check_str(require(data, "level0", path), f"{path}.level0"),
            level1=check_str(require(data, "level1", path), f"{path}.level1"),
            level2_ref=check_str(require(data, "level2_ref", path), f"{path}.level2_ref"),
        )


@dataclass
class SkillEntry:
    """SkillDescriptor.entry。"""

    prompt_ref: str | None = None
    script: str | None = None
    checklist: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "entry") -> "SkillEntry":
        check_keys(data, ("prompt_ref", "script", "checklist"), path)
        prompt_ref = data.get("prompt_ref")
        script = data.get("script")
        checklist = data.get("checklist")
        return cls(
            prompt_ref=None if prompt_ref is None else check_str(prompt_ref, f"{path}.prompt_ref"),
            script=None if script is None else check_str(script, f"{path}.script"),
            checklist=None if checklist is None else check_str(checklist, f"{path}.checklist"),
        )


@dataclass
class SkillDescriptor:
    """M7 持有、M2 披露（01 §2.7）。"""

    skill_id: str
    version: str  # semver
    capability_domain: E.CapabilityDomain
    disclosure: Disclosure
    entry: SkillEntry
    evidence_policy: str
    owner: str
    status: E.SkillStatus

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SkillDescriptor":
        check_keys(data, (
            "skill_id", "version", "capability_domain", "disclosure", "entry",
            "evidence_policy", "owner", "status",
        ), "SkillDescriptor")
        return cls(
            skill_id=check_id(require(data, "skill_id", "SkillDescriptor"), "SkillDescriptor.skill_id"),
            version=check_str(require(data, "version", "SkillDescriptor"), "SkillDescriptor.version"),
            capability_domain=check_enum(
                require(data, "capability_domain", "SkillDescriptor"),
                E.CapabilityDomain,
                "SkillDescriptor.capability_domain",
            ),
            disclosure=Disclosure.from_dict(require(data, "disclosure", "SkillDescriptor")),
            entry=SkillEntry.from_dict(require(data, "entry", "SkillDescriptor")),
            evidence_policy=check_str(
                require(data, "evidence_policy", "SkillDescriptor"), "SkillDescriptor.evidence_policy"
            ),
            owner=check_str(require(data, "owner", "SkillDescriptor"), "SkillDescriptor.owner"),
            status=check_enum(require(data, "status", "SkillDescriptor"), E.SkillStatus, "SkillDescriptor.status"),
        )

    def to_dict(self) -> dict:
        return asdict_plain(self)


# ---------------------------------------------------------------- §2.10
@dataclass
class ExpectedBehavior:
    """GoldenCase.expected_behavior[]。"""

    clause: str
    judge: E.GoldenJudge

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str) -> "ExpectedBehavior":
        check_keys(data, ("clause", "judge"), path)
        return cls(
            clause=check_str(require(data, "clause", path), f"{path}.clause"),
            judge=check_enum(require(data, "judge", path), E.GoldenJudge, f"{path}.judge"),
        )


@dataclass
class GoldenCase:
    """M6 黄金集（01 §2.10）。

    excluded_from 标注 ``holdout`` 的案例禁止进开发集（01 §2.10 / M6 SPEC-M6-02）。
    """

    case_id: str
    version: int
    task_input: str  # 用户原始指令
    environment_seed: str  # 环境种子（M5 可复现）
    expected_behavior: list
    source: E.GoldenSource
    excluded_from: list
    scenario_ref: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GoldenCase":
        check_keys(data, (
            "case_id", "version", "task_input", "environment_seed", "scenario_ref",
            "expected_behavior", "source", "excluded_from",
        ), "GoldenCase")
        eb_raw = require(data, "expected_behavior", "GoldenCase")
        if not isinstance(eb_raw, list):
            raise _ContractError("GoldenCase.expected_behavior", "必须是列表")
        scenario_ref = data.get("scenario_ref")
        return cls(
            case_id=check_id(require(data, "case_id", "GoldenCase"), "GoldenCase.case_id"),
            version=check_int(require(data, "version", "GoldenCase"), "GoldenCase.version"),
            task_input=check_str(require(data, "task_input", "GoldenCase"), "GoldenCase.task_input"),
            environment_seed=check_str(
                require(data, "environment_seed", "GoldenCase"), "GoldenCase.environment_seed"
            ),
            scenario_ref=None if scenario_ref is None else check_str(scenario_ref, "GoldenCase.scenario_ref"),
            expected_behavior=[
                ExpectedBehavior.from_dict(item, f"GoldenCase.expected_behavior[{i}]")
                for i, item in enumerate(eb_raw)
            ],
            source=check_enum(require(data, "source", "GoldenCase"), E.GoldenSource, "GoldenCase.source"),
            excluded_from=check_str_list(require(data, "excluded_from", "GoldenCase"), "GoldenCase.excluded_from"),
        )

    def to_dict(self) -> dict:
        return asdict_plain(self)


# ---------------------------------------------------------------- §2.11
@dataclass
class TrajectoryStep:
    """TrajectoryRecord.steps[]。"""

    seq: int
    type: E.TrajectoryStepType
    ref: str
    summary: str
    latency_ms: int
    cost: Any  # 币种/点数，契约未约束类型

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str) -> "TrajectoryStep":
        check_keys(data, ("seq", "type", "ref", "summary", "latency_ms", "cost"), path)
        return cls(
            seq=check_int(require(data, "seq", path), f"{path}.seq"),
            type=check_enum(require(data, "type", path), E.TrajectoryStepType, f"{path}.type"),
            ref=check_str(require(data, "ref", path), f"{path}.ref"),
            summary=check_str(require(data, "summary", path), f"{path}.summary"),
            latency_ms=check_int(require(data, "latency_ms", path), f"{path}.latency_ms"),
            cost=require(data, "cost", path),
        )


@dataclass
class Outcome:
    """TrajectoryRecord.outcome。"""

    status: str  # 终态（与 TaskState 终态一致；语义约束在 M6 判定）
    evidence_summary: str
    completion_level: int  # 1-5

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "outcome") -> "Outcome":
        check_keys(data, ("status", "evidence_summary", "completion_level"), path)
        level = check_int(require(data, "completion_level", path), f"{path}.completion_level")
        if not 1 <= level <= 5:
            raise _ContractError(f"{path}.completion_level", f"必须在 1-5 之间，实际为 {level}")
        return cls(
            status=check_str(require(data, "status", path), f"{path}.status"),
            evidence_summary=check_str(require(data, "evidence_summary", path), f"{path}.evidence_summary"),
            completion_level=level,
        )


@dataclass
class CostTotal:
    """TrajectoryRecord.cost_total。"""

    tokens: int
    currency: Any  # 数额（币种单位由运行时约定）

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "cost_total") -> "CostTotal":
        check_keys(data, ("tokens", "currency"), path)
        return cls(
            tokens=check_int(require(data, "tokens", path), f"{path}.tokens"),
            currency=require(data, "currency", path),
        )


@dataclass
class TrajectoryRecord:
    """M6 采集（01 §2.11）。"""

    trace_id: str
    task_id: str
    release_id: str
    steps: list
    outcome: Outcome
    cost_total: CostTotal
    quality_flags: list  # 如 LATEX_STUCK/LOOP/REFUSAL_MISSING

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TrajectoryRecord":
        check_keys(data, (
            "trace_id", "task_id", "release_id", "steps", "outcome",
            "cost_total", "quality_flags",
        ), "TrajectoryRecord")
        steps_raw = require(data, "steps", "TrajectoryRecord")
        if not isinstance(steps_raw, list):
            raise _ContractError("TrajectoryRecord.steps", "必须是列表")
        return cls(
            trace_id=check_str(require(data, "trace_id", "TrajectoryRecord"), "TrajectoryRecord.trace_id"),
            task_id=check_str(require(data, "task_id", "TrajectoryRecord"), "TrajectoryRecord.task_id"),
            release_id=check_str(require(data, "release_id", "TrajectoryRecord"), "TrajectoryRecord.release_id"),
            steps=[
                TrajectoryStep.from_dict(item, f"TrajectoryRecord.steps[{i}]") for i, item in enumerate(steps_raw)
            ],
            outcome=Outcome.from_dict(require(data, "outcome", "TrajectoryRecord")),
            cost_total=CostTotal.from_dict(require(data, "cost_total", "TrajectoryRecord")),
            quality_flags=check_str_list(
                require(data, "quality_flags", "TrajectoryRecord"), "TrajectoryRecord.quality_flags"
            ),
        )

    def to_dict(self) -> dict:
        return asdict_plain(self)


# ---------------------------------------------------------------- §2.12
@dataclass
class GoldenScores:
    """ReleaseBundle.golden_scores。"""

    golden_set_version: str
    pass_rate: Any  # 数值 0-1（M6 签名）
    by_domain: dict

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "golden_scores") -> "GoldenScores":
        check_keys(data, ("golden_set_version", "pass_rate", "by_domain"), path)
        return cls(
            golden_set_version=check_str(require(data, "golden_set_version", path), f"{path}.golden_set_version"),
            pass_rate=require(data, "pass_rate", path),
            by_domain=check_mapping(require(data, "by_domain", path), f"{path}.by_domain"),
        )


@dataclass
class ReleaseBundle:
    """M7 打包（01 §2.12）。六要素缺一拒绝打包（M7 SPEC-M7-04）。"""

    release_id: str  # 如 rel-0003
    model_ref: str  # 模型+版本+端点配置
    prompt_refs: list  # prompts/ 带 hash
    skill_refs: list  # skills/ 带 hash
    tool_refs: list  # tools/ 注册清单
    ontology_version: str  # ontology/ 目录 hash
    golden_scores: GoldenScores
    frozen_scenarios: list  # 随 release 冻结的场景 id
    contract_version: str  # 01-contracts 版本（ADDENDUM 后为 1.1）

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReleaseBundle":
        check_keys(data, (
            "release_id", "model_ref", "prompt_refs", "skill_refs", "tool_refs",
            "ontology_version", "golden_scores", "frozen_scenarios", "contract_version",
        ), "ReleaseBundle")
        return cls(
            release_id=check_id(require(data, "release_id", "ReleaseBundle"), "ReleaseBundle.release_id"),
            model_ref=check_str(require(data, "model_ref", "ReleaseBundle"), "ReleaseBundle.model_ref"),
            prompt_refs=check_str_list(require(data, "prompt_refs", "ReleaseBundle"), "ReleaseBundle.prompt_refs"),
            skill_refs=check_str_list(require(data, "skill_refs", "ReleaseBundle"), "ReleaseBundle.skill_refs"),
            tool_refs=check_str_list(require(data, "tool_refs", "ReleaseBundle"), "ReleaseBundle.tool_refs"),
            ontology_version=check_str(
                require(data, "ontology_version", "ReleaseBundle"), "ReleaseBundle.ontology_version"
            ),
            golden_scores=GoldenScores.from_dict(require(data, "golden_scores", "ReleaseBundle")),
            frozen_scenarios=check_str_list(
                require(data, "frozen_scenarios", "ReleaseBundle"), "ReleaseBundle.frozen_scenarios"
            ),
            contract_version=check_str(
                require(data, "contract_version", "ReleaseBundle"), "ReleaseBundle.contract_version"
            ),
        )

    def to_dict(self) -> dict:
        return asdict_plain(self)
