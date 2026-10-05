# -*- coding: utf-8 -*-
"""m6_flywheel.badcase · Badcase 闭环（SPEC-M6-04）。

状态机（M6 §2，非法迁移抛 ``IllegalBadcaseTransitionError``）：

```text
OPENED → REPRODUCED → FIX_CANDIDATE → EXPERIMENT → ADOPTED | REJECTED
（OPENED/REPRODUCED/FIX_CANDIDATE/EXPERIMENT 均可 → REJECTED 终结）
```

实验隔离（SPEC-M6-04）：
- A/B = candidate vs current release **同黄金集**跑分（两份报告由 evaluator 产出，
  本模块只消费）；实验记录（两版分数 + diff 用例）归档落盘；
- 决策规则：**仅 candidate 在 badcase 关联案例上通过 且 candidate 总分 ≥
  current 总分** 才 ADOPTED；否则 REJECTED（生产 release 不变——本模块不持有
  任何生产 release 写入口，发布走 M7 流水线，SPEC-M6-06）。

持久化：``badcases.jsonl``（追加写，事件溯源式重建）+ ``experiments/`` 归档。
``badcase.opened`` 事件走 01 §4 冻结目录（sink 注入）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from contracts import EventType

__all__ = [
    "BADCASE_TRANSITIONS",
    "BadcaseError",
    "IllegalBadcaseTransitionError",
    "BadcaseEvidence",
    "BadcaseRecord",
    "BadcaseStore",
    "BadcaseWorkflow",
    "open_badcase",
]

OPENED = "OPENED"
REPRODUCED = "REPRODUCED"
FIX_CANDIDATE = "FIX_CANDIDATE"
EXPERIMENT = "EXPERIMENT"
ADOPTED = "ADOPTED"
REJECTED = "REJECTED"

#: 合法迁移表（数据驱动；M6 §2 状态机）
BADCASE_TRANSITIONS: dict[str, list[str]] = {
    OPENED: [REPRODUCED, REJECTED],
    REPRODUCED: [FIX_CANDIDATE, REJECTED],
    FIX_CANDIDATE: [EXPERIMENT, REJECTED],
    EXPERIMENT: [ADOPTED, REJECTED],
    ADOPTED: [],
    REJECTED: [],
}


class BadcaseError(ValueError):
    """Badcase 流程错误。"""


class IllegalBadcaseTransitionError(BadcaseError):
    """非法状态迁移。"""


@dataclass
class BadcaseEvidence:
    """BadcaseEvidence（01 §3.6 open_badcase 入参）：失败现场证据。"""

    case_id: str
    trace_id: str
    summary: str
    release_id: str = ""
    detail: str = ""
    observed_at: str = ""

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id, "trace_id": self.trace_id,
            "summary": self.summary, "release_id": self.release_id,
            "detail": self.detail, "observed_at": self.observed_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> "BadcaseEvidence":
        return cls(
            case_id=str(data.get("case_id") or ""),
            trace_id=str(data.get("trace_id") or ""),
            summary=str(data.get("summary") or ""),
            release_id=str(data.get("release_id") or ""),
            detail=str(data.get("detail") or ""),
            observed_at=str(data.get("observed_at") or ""),
        )


def _now_iso() -> str:
    from m2_information.timestamps import utc_now_iso

    return utc_now_iso()


@dataclass
class BadcaseRecord:
    """Badcase 台账记录（事件溯源折叠态）。"""

    badcase_id: str
    status: str = OPENED
    evidence: dict = field(default_factory=dict)
    opened_at: str = ""
    transitions: list = field(default_factory=list)
    experiment: dict = field(default_factory=dict)
    decision_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "badcase_id": self.badcase_id, "status": self.status,
            "evidence": self.evidence, "opened_at": self.opened_at,
            "transitions": self.transitions, "experiment": self.experiment,
            "decision_reason": self.decision_reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> "BadcaseRecord":
        return cls(
            badcase_id=str(data.get("badcase_id") or ""),
            status=str(data.get("status") or OPENED),
            evidence=dict(data.get("evidence") or {}),
            opened_at=str(data.get("opened_at") or ""),
            transitions=list(data.get("transitions") or []),
            experiment=dict(data.get("experiment") or {}),
            decision_reason=str(data.get("decision_reason") or ""),
        )


class BadcaseStore:
    """badcases.jsonl 追加写台账（重启可重建）。"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _entries(self) -> dict[str, dict]:
        records: dict[str, dict] = {}
        if not self.path.is_file():
            return records
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            records[str(entry.get("badcase_id"))] = entry
        return records

    def list(self) -> list[BadcaseRecord]:
        return [BadcaseRecord.from_dict(item)
                for _, item in sorted(self._entries().items())]

    def get(self, badcase_id: str) -> BadcaseRecord:
        entry = self._entries().get(badcase_id)
        if entry is None:
            raise BadcaseError(f"badcase 不存在: {badcase_id!r}")
        return BadcaseRecord.from_dict(entry)

    def append(self, record: BadcaseRecord) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")


class BadcaseWorkflow:
    """Badcase 状态机驱动 + A/B 实验隔离（SPEC-M6-04）。"""

    def __init__(self, store: BadcaseStore, *, archive_dir: Path | str | None = None,
                 sink: Callable[[dict], Any] | None = None,
                 now_fn: Callable[[], str] | None = None) -> None:
        self.store = store
        self.archive_dir = Path(archive_dir) if archive_dir is not None else store.path.parent
        self.sink = sink
        self.now_fn = now_fn or _now_iso

    # -------------------------------------------------------------- 状态机
    def _transition(self, record: BadcaseRecord, to_status: str,
                    note: str = "") -> BadcaseRecord:
        allowed = BADCASE_TRANSITIONS.get(record.status) or []
        if to_status not in allowed:
            raise IllegalBadcaseTransitionError(
                f"badcase {record.badcase_id}: {record.status} → {to_status} 非法"
                f"（允许: {allowed or ['<终态>']}）")
        record.transitions.append({
            "from": record.status, "to": to_status, "at": self.now_fn(),
            "note": note,
        })
        record.status = to_status
        self.store.append(record)
        return record

    def open(self, evidence: BadcaseEvidence | Mapping,
             *, badcase_id: str | None = None) -> str:
        """01 §3.6：``open_badcase(evidence) -> BadcaseId``。"""
        if not isinstance(evidence, BadcaseEvidence):
            evidence = BadcaseEvidence.from_dict(evidence)
        if not evidence.case_id or not evidence.trace_id:
            raise BadcaseError("BadcaseEvidence.case_id/trace_id 必填")
        badcase_id = badcase_id or f"bc-{evidence.case_id}-{len(self.store.list()) + 1:04d}"
        record = BadcaseRecord(
            badcase_id=badcase_id, status=OPENED,
            evidence={**evidence.to_dict(),
                      "observed_at": evidence.observed_at or self.now_fn()},
            opened_at=self.now_fn(), transitions=[])
        self.store.append(record)
        self._emit(badcase_id, {"case_id": evidence.case_id,
                                "trace_id": evidence.trace_id,
                                "summary": evidence.summary})
        return badcase_id

    def reproduce(self, badcase_id: str, *, reproduced: bool,
                  note: str = "") -> BadcaseRecord:
        """复现确认：失败仍现 → REPRODUCED；无法复现 → REJECTED（非真 badcase）。"""
        record = self.store.get(badcase_id)
        if reproduced:
            return self._transition(record, REPRODUCED, note or "失败复现")
        return self._transition(record, REJECTED, note or "无法复现，关闭")

    def submit_fix_candidate(self, badcase_id: str, candidate_release_id: str,
                             *, note: str = "") -> BadcaseRecord:
        record = self.store.get(badcase_id)
        record.experiment = {
            **record.experiment,
            "current_release": record.experiment.get("current_release")
            or record.evidence.get("release_id") or "",
            "candidate_release": str(candidate_release_id),
        }
        self.store.append(record)
        self._transition(record, FIX_CANDIDATE, note or f"候选 {candidate_release_id}")
        return record

    # -------------------------------------------------------------- A/B 实验
    def run_experiment(self, badcase_id: str, *, current_report: Mapping,
                       candidate_report: Mapping,
                       golden_set_version: str = "") -> BadcaseRecord:
        """A/B 同黄金集对比（SPEC-M6-04）：两版分数 + diff 用例 + 自动决策 + 归档。

        决策：candidate 在关联案例上通过 且 candidate 总分 ≥ current 总分 →
        ADOPTED；否则 REJECTED（生产 release 不变）。
        """
        record = self.store.get(badcase_id)
        if record.status != FIX_CANDIDATE:
            raise IllegalBadcaseTransitionError(
                f"badcase {badcase_id}: 实验须从 {FIX_CANDIDATE} 进入，"
                f"当前 {record.status}")
        case_id = str(record.evidence.get("case_id") or "")
        current_cases = {str(item.get("case_id")): item
                         for item in current_report.get("cases") or []}
        candidate_cases = {str(item.get("case_id")): item
                           for item in candidate_report.get("cases") or []}
        if case_id not in current_cases or case_id not in candidate_cases:
            raise BadcaseError(
                f"A/B 报告缺 badcase 关联案例 {case_id!r}（两版必须同黄金集全量跑分）")
        if (str(current_report.get("golden_set_version"))
                != str(candidate_report.get("golden_set_version"))):
            raise BadcaseError("A/B 必须同黄金集（golden_set_version 不一致）")

        diff_cases = sorted(
            case_id_ for case_id_ in set(current_cases) & set(candidate_cases)
            if bool(current_cases[case_id_].get("passed"))
            != bool(candidate_cases[case_id_].get("passed"))
        )
        current_total = float((current_report.get("totals") or {}).get("score_100") or 0.0)
        candidate_total = float((candidate_report.get("totals") or {}).get("score_100") or 0.0)
        candidate_case_passed = bool(candidate_cases[case_id].get("passed"))

        record.experiment = {
            **record.experiment,
            "golden_set_version": str(candidate_report.get("golden_set_version")
                                      or golden_set_version),
            "current_total": current_total,
            "candidate_total": candidate_total,
            "candidate_case_passed": candidate_case_passed,
            "diff_cases": diff_cases,
            "current_pass_rate": current_report.get("pass_rate"),
            "candidate_pass_rate": candidate_report.get("pass_rate"),
            "archive": self._archive(record, current_report, candidate_report,
                                     diff_cases),
        }
        self.store.append(record)
        self._transition(record, EXPERIMENT, note="A/B 同黄金集跑分完成")
        if candidate_case_passed and candidate_total >= current_total:
            record.decision_reason = (
                f"candidate 通过关联案例且总分 {candidate_total} ≥ current "
                f"{current_total}（SPEC-M6-04 采纳条件）")
            self._transition(record, ADOPTED, note=record.decision_reason)
        else:
            record.decision_reason = (
                f"candidate 未满足采纳条件（案例通过={candidate_case_passed}，"
                f"总分 {candidate_total} < current {current_total} 或案例未通过）"
                "——生产 release 不变")
            self._transition(record, REJECTED, note=record.decision_reason)
        return record

    def _archive(self, record: BadcaseRecord, current_report: Mapping,
                 candidate_report: Mapping, diff_cases: list) -> str:
        """实验记录归档（两版分数+diff 用例；SPEC-M6-04）。"""
        experiments = self.archive_dir / "experiments"
        experiments.mkdir(parents=True, exist_ok=True)
        payload = {
            "badcase_id": record.badcase_id,
            "evidence": record.evidence,
            "golden_set_version": candidate_report.get("golden_set_version"),
            "current": {
                "release_id": current_report.get("release_id"),
                "score_100": (current_report.get("totals") or {}).get("score_100"),
                "pass_rate": current_report.get("pass_rate"),
                "failures": current_report.get("failures"),
            },
            "candidate": {
                "release_id": candidate_report.get("release_id"),
                "score_100": (candidate_report.get("totals") or {}).get("score_100"),
                "pass_rate": candidate_report.get("pass_rate"),
                "failures": candidate_report.get("failures"),
            },
            "diff_cases": diff_cases,
            "archived_at": self.now_fn(),
        }
        path = experiments / f"{record.badcase_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        return path.as_posix()

    def _emit(self, badcase_id: str, payload: dict) -> None:
        if self.sink is None:
            return
        from m2_information.ids import new_ulid

        self.sink({
            "event_id": new_ulid(),
            "type": EventType.BADCASE_OPENED.value,
            "subject": badcase_id,
            "payload": payload,
            "occurred_at": self.now_fn(),
            "trace_id": f"trace-{badcase_id}",
            "producer": "M6",
        })


def open_badcase(evidence: BadcaseEvidence | Mapping, *,
                 store_path: Path | str | None = None,
                 repo_root: Path | str | None = None,
                 sink: Callable[[dict], Any] | None = None) -> str:
    """01 §3.6 冻结 API：``open_badcase(evidence) -> BadcaseId``。"""
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    path = store_path or root / "runtime" / "m6_flywheel" / "badcases.jsonl"
    workflow = BadcaseWorkflow(BadcaseStore(path), sink=sink)
    return workflow.open(evidence)
