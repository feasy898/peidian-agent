# -*- coding: utf-8 -*-
"""m4_semantic.coverage · 本体覆盖率监测（specs/M4-semantic-ontology.md SPEC-M4-06，00 §4）。

- 概念注册表（何谓"已在本体注册"）：对象类型/关系/动作/规则 ID + 实例实体 ID +
  属性词典 canonical 名——全部来自 ontology/ 与实例数据，不硬编码；
- 任务级报告：``record_task(task_id, concepts)`` → {hits, total, ratio, missing}；
- 窗口级报告（01 §3.4 ``coverage_report(window)``）：聚合窗口内全部任务（月报进 M7）；
- 缺失概念 ≥ 30%（即命中率 < 70%，00 §4）→ 产出 ``badcase.opened`` **候选事件**
  （EventRecord dict，经 contracts 校验；持久化由 M2/M6 事件流负责，M4 只产出）。

任务报告落盘 ``runtime/coverage/task-<task_id>.json``（缺失清单可追溯）。
时间戳一律 UTC ISO-8601（datetime.now(timezone.utc)，仅用于记录，不参与电价判定）。
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .loader import LoadedOntology, default_repo_root, load_ontology

__all__ = ["CoverageMonitor", "coverage_report", "MISSING_BADCASE_THRESHOLD"]

#: 缺失概念比例阈值（≥ 触发 badcase.opened 候选；等价命中率 < 70%，00 §4）
MISSING_BADCASE_THRESHOLD = 0.30

_SAFE_FILE_RE = re.compile(r"[^0-9A-Za-z._-]+")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_name(task_id: str) -> str:
    cleaned = _SAFE_FILE_RE.sub("_", str(task_id)).strip("._")
    return cleaned[:80] or "task"


class CoverageMonitor:
    """覆盖率监测器（任务级记录 + 窗口聚合 + badcase 候选事件产出）。"""

    def __init__(
        self,
        loaded: LoadedOntology | None = None,
        *,
        persist_dir: Path | str | None = None,
        missing_threshold: float = MISSING_BADCASE_THRESHOLD,
    ) -> None:
        self.loaded = loaded or load_ontology()
        self.missing_threshold = float(missing_threshold)
        self.persist_dir = (Path(persist_dir) if persist_dir
                            else Path(self.loaded.repo_root) / "runtime" / "coverage")
        self.tasks: dict = {}  # task_id -> 报告 dict
        self._registry: set = set()

    # ------------------------------------------------------------------
    @property
    def concept_registry(self) -> set:
        """已注册概念全集（惰性构建；本体运行期只读，构建一次）。"""
        if not self._registry:
            loaded = self.loaded
            registry = set(loaded.object_types)
            registry |= set(loaded.relation_types)
            registry |= set(loaded.action_ids())
            registry |= set(loaded.rules)
            from .regulation import RegulationIndex
            registry |= set(RegulationIndex(loaded).existing_rule_ids())
            for entry in (loaded.aliases or {}).get("attribute_dictionary") or []:
                if entry.get("canonical"):
                    registry.add(str(entry["canonical"]))
            if loaded.instance is not None:
                registry |= loaded.instance.entity_ids()
            self._registry = registry
        return self._registry

    # ------------------------------------------------------------------
    def record_task(
        self,
        task_id: str,
        concepts: Iterable[str],
        *,
        trace_id: str | None = None,
        persist: bool = True,
    ) -> dict:
        """任务结束记录涉及概念 → 任务级覆盖率报告（含缺失清单与候选事件）。"""
        concept_list = [str(c) for c in concepts or ()]
        registry = self.concept_registry
        hits = [c for c in concept_list if c in registry]
        missing = [c for c in concept_list if c not in registry]
        total = len(concept_list)
        ratio = (len(hits) / total) if total else 1.0
        missing_ratio = 1.0 - ratio

        report: dict = {
            "task_id": str(task_id),
            "recorded_at": _utc_now_iso(),
            "ontology_version": self.loaded.version,
            "hits": len(hits),
            "total": total,
            "ratio": round(ratio, 4),
            "missing_ratio": round(missing_ratio, 4),
            "missing": missing,
            "candidate_events": [],
        }
        if total and missing_ratio >= self.missing_threshold - 1e-9:
            report["candidate_events"].append(
                self._badcase_candidate_event(task_id, report, trace_id)
            )

        self.tasks[str(task_id)] = report
        if persist:
            self._persist(report)
        return report

    # ------------------------------------------------------------------
    def _badcase_candidate_event(self, task_id: str, report: Mapping[str, Any],
                                 trace_id: str | None) -> dict:
        """``badcase.opened`` 候选事件（EventRecord dict，经 contracts 校验）。"""
        from contracts import EventRecord

        payload = {
            "candidate": True,
            "reason": "ontology_coverage_missing",
            "task_id": str(task_id),
            "missing_ratio": report.get("missing_ratio"),
            "missing": list(report.get("missing") or []),
            "ontology_version": report.get("ontology_version"),
        }
        record = {
            "event_id": f"01M4COV{uuid.uuid4().hex[:16].upper()}",
            "type": "badcase.opened",
            "subject": str(task_id),
            "payload": payload,
            "occurred_at": report.get("recorded_at") or _utc_now_iso(),
            "trace_id": trace_id or f"cov-{task_id}",
            "producer": "M4",
        }
        EventRecord.from_dict(record)  # 结构校验（缺 trace_id/非法枚举在产出即拒）
        return record

    def _persist(self, report: Mapping[str, Any]) -> Path:
        path = self.persist_dir / f"task-{_safe_name(report['task_id'])}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path

    # ------------------------------------------------------------------
    def load_persisted(self) -> list:
        """读取落盘的任务报告（窗口聚合用）。"""
        reports: list = []
        if not self.persist_dir.is_dir():
            return reports
        for path in sorted(self.persist_dir.glob("task-*.json")):
            try:
                reports.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return reports

    def coverage_report(self, window: Mapping[str, Any] | None = None) -> dict:
        """01 §3.4 ``coverage_report(window) -> {hits, total, ratio, missing[]}``。

        window：None=全部已记录任务；{task_ids: [...]}=指定任务；{from,to}=UTC ISO 时间窗
        （recorded_at 落窗内）。聚合口径：hits/total 求和，missing 取并集（保序去重）。
        """
        reports = list(self.tasks.values()) or self.load_persisted()
        if window:
            if window.get("task_ids") is not None:
                wanted = {str(t) for t in window["task_ids"]}
                reports = [r for r in reports if str(r.get("task_id")) in wanted]
            elif window.get("from") or window.get("to"):
                lo = str(window.get("from") or "")
                hi = str(window.get("to") or "9999")
                reports = [
                    r for r in reports
                    if lo <= str(r.get("recorded_at") or "") <= hi
                ]
        hits = sum(int(r.get("hits") or 0) for r in reports)
        total = sum(int(r.get("total") or 0) for r in reports)
        ratio = (hits / total) if total else 1.0
        missing: list = []
        seen: set = set()
        for r in reports:
            for concept in r.get("missing") or []:
                if concept not in seen:
                    seen.add(concept)
                    missing.append(concept)
        return {
            "tasks": len(reports),
            "hits": hits,
            "total": total,
            "ratio": round(ratio, 4),
            "missing": missing,
        }


# ---------------------------------------------------------------------------
# 模块级算子（01 §3.4）
# ---------------------------------------------------------------------------
def coverage_report(
    window: Mapping[str, Any] | None = None,
    *,
    monitor: CoverageMonitor | None = None,
) -> dict:
    """01 §3.4 ``coverage_report(window) -> {hits, total, ratio, missing[]}``。"""
    return (monitor or CoverageMonitor()).coverage_report(window)
