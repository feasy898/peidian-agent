# -*- coding: utf-8 -*-
"""arena.faultlib · 论文故障库（arena/faults/*.yaml）加载与判据装配。

库条目是判据的**权威来源**（机理/判据/演化链/sources 俱全，出处不合规不入库）；
本模块把条目的 detection 块装配成 fault.detect.Criterion 覆盖表，供
arena.ArenaEngine 注入 fault.Engine（Detector）。缺失的 metric 回退
DEFAULT_CRITERIA（引擎内置工程口径）。

零信任：加载时逐条核对 engine_type ∈ fault.dsl.FAULT_TYPES、
compat_kinds 与 COMPAT_KINDS 一致、detection 五件套齐；不符即抛 FaultLibError，
绝不让错库进判据链。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from fault.detect import Criterion
from fault.dsl import COMPAT_KINDS, FAULT_TYPES

__all__ = ["FaultLibError", "FaultLibrary", "HINT_SEVERITY"]

ROOT = Path(__file__).resolve().parents[1]
FAULTS_DIR = ROOT / "arena" / "faults"

# hint → 异常级别（库条目无 severity 字段时的引擎侧口径；P0=事故级 P2=预警级）
HINT_SEVERITY: dict[str, str] = {
    "PARTIAL_DISCHARGE": "P2",
    "TEMPERATURE_RISE": "P2",
    "HARMONIC": "P2",
    "THREE_PHASE_UNBALANCE": "P2",
    "OVER_LIMIT": "P2",   # 库阈值取 0.8 预警档（1.0 越限档由园区 DSL 配置），严重度按预警
    "PROTECTION_MALOPERATION": "P2",
    "TRANSFORMER_FAULT": "P0",
    "DC_GROUND_FAULT": "P2",
    "PHASE_LOSS": "P2",
    "SINGLE_PHASE_GROUND": "P0",
    "ENVIRONMENTAL": "P2",   # 烟感/水浸子模式的即时告警见 DEFAULT_CRITERIA（P0）
}

_DET_REQUIRED = ("metric", "comparator", "threshold", "duration_sec", "source")
_ENTRY_REQUIRED = ("kind", "title", "class", "engine_type", "compat_kinds", "params",
                   "detection", "mechanism", "evolution", "signals",
                   "agent_expectations", "sources")


class FaultLibError(ValueError):
    """故障库加载/校验失败。"""


class FaultLibrary:
    """arena/faults/*.yaml 的内存库：criteria 覆盖表 + 条目注册表。"""

    def __init__(self, entries: dict[str, dict], criteria: dict[str, Criterion]) -> None:
        self.entries = entries              # engine_type → 条目 dict
        self.criteria = criteria            # metric → Criterion（覆盖表）

    def criterion_for(self, metric: str) -> Criterion | None:
        return self.criteria.get(metric)

    def entry_for(self, engine_type: str) -> dict | None:
        return self.entries.get(engine_type)


def load_fault_library(faults_dir: Path | str | None = None) -> FaultLibrary:
    d = Path(faults_dir) if faults_dir is not None else FAULTS_DIR
    if not d.is_dir():
        return FaultLibrary({}, {})
    entries: dict[str, dict] = {}
    criteria: dict[str, Criterion] = {}
    problems: list[str] = []
    for path in sorted(d.glob("*.yaml")):
        try:
            entry = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise FaultLibError(f"{path.name}: YAML 解析失败: {exc}") from exc
        if not isinstance(entry, dict):
            raise FaultLibError(f"{path.name}: 顶层必须是映射")
        for k in _ENTRY_REQUIRED:
            if k not in entry:
                problems.append(f"{path.name}: 缺字段 {k}")
        kind = entry.get("kind")
        if kind != path.stem:
            problems.append(f"{path.name}: kind 与文件名不一致")
        etype = str(entry.get("engine_type", ""))
        if etype not in FAULT_TYPES:
            problems.append(f"{path.name}: engine_type {etype!r} 不在引擎 FAULT_TYPES")
        compat = entry.get("compat_kinds")
        if isinstance(compat, list) and etype in COMPAT_KINDS:
            want = set(COMPAT_KINDS[etype])
            got = {str(x) for x in compat}
            # COMPAT_KINDS 的值是 topology.KIND_* 常量（与 compat_kinds 同名字串）
            if got != want:
                problems.append(f"{path.name}: compat_kinds {sorted(got)} != 引擎 {sorted(want)}")
        det = entry.get("detection")
        if not isinstance(det, dict):
            problems.append(f"{path.name}: detection 必须是映射")
            continue
        for k in _DET_REQUIRED:
            if k not in det:
                problems.append(f"{path.name}: detection 缺 {k}")
        hint = etype if etype in FAULT_TYPES else None
        if hint and all(k in det for k in _DET_REQUIRED):
            try:
                threshold: float | str = float(det["threshold"])
            except (TypeError, ValueError):
                threshold = str(det["threshold"])   # 非数值判据（如「!=」空串）原样保留
            criteria[str(det["metric"])] = Criterion(
                comparator=str(det["comparator"]),
                threshold=threshold,
                duration_s=float(det["duration_sec"]),
                severity=HINT_SEVERITY.get(hint, "P2"),
                source=str(det["source"]) + f"（库条目 {path.name}）",
            )
        if etype:
            entries[etype] = entry
    if problems:
        raise FaultLibError("故障库校验失败:\n  " + "\n  ".join(problems))
    return FaultLibrary(entries, criteria)


def summarize(lib: FaultLibrary) -> str:
    """一行摘要（日志/报告用）。"""
    return (f"faultlib entries={len(lib.entries)} criteria={len(lib.criteria)} "
            f"metrics={sorted(lib.criteria)}")
