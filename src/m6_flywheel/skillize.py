# -*- coding: utf-8 -*-
"""m6_flywheel.skillize · 受控自进化入口（SPEC-M6-05）。

Skill 化双门槛：
1. **≥3 个不同任务实例出现且判据通过**（"第二次发生"最低门槛为 3——防一次性
   巧合；判据通过 = 该次任务轨迹在黄金判据下 passed）；
2. 产出 ``SkillDescriptor`` **候选**（status=REVIEW，走 M7 变更评审；
   01 §3.6 ``promote_to_skill(badcase_id, skill_draft)``——M7 交付前只产出候选，
   不发布）。

evidence_policy 必须含黄金成绩提升证明口径（SPEC-M6-02 §2 skillize 组件：
"含 evidence_policy：黄金成绩提升证明"）——由 ``promote_to_skill`` 强制追加
A/B 实验引用；``skill.promoted`` 事件（01 §4）在候选产出时落审计。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from contracts import EventType, SkillDescriptor

__all__ = [
    "MIN_OCCURRENCES",
    "SkillizeError",
    "MethodOccurrence",
    "MethodLedger",
    "skillize",
    "promote_to_skill",
]

#: 最低出现门槛（SPEC-M6-05：≥3 个不同任务实例）
MIN_OCCURRENCES = 3

#: evidence_policy 强制口径（黄金成绩提升证明）
EVIDENCE_POLICY_REQUIRED = "golden-ab-proof"


class SkillizeError(ValueError):
    """Skill 化不满足门槛/草案非法。"""


@dataclass
class MethodOccurrence:
    """方法出现记录（判据通过口径：judge_passed=True）。"""

    method_key: str
    trace_id: str
    task_id: str
    judge_passed: bool
    case_id: str = ""
    occurred_at: str = ""

    def to_dict(self) -> dict:
        return {
            "method_key": self.method_key, "trace_id": self.trace_id,
            "task_id": self.task_id, "judge_passed": bool(self.judge_passed),
            "case_id": self.case_id, "occurred_at": self.occurred_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> "MethodOccurrence":
        return cls(
            method_key=str(data.get("method_key") or ""),
            trace_id=str(data.get("trace_id") or ""),
            task_id=str(data.get("task_id") or ""),
            judge_passed=bool(data.get("judge_passed")),
            case_id=str(data.get("case_id") or ""),
            occurred_at=str(data.get("occurred_at") or ""),
        )


class MethodLedger:
    """方法出现台账（methods.jsonl 追加写；occurrences 按记录序重建）。"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, occurrence: MethodOccurrence | Mapping) -> MethodOccurrence:
        if not isinstance(occurrence, MethodOccurrence):
            occurrence = MethodOccurrence.from_dict(occurrence)
        if not occurrence.method_key or not occurrence.task_id:
            raise SkillizeError("MethodOccurrence.method_key/task_id 必填")
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(occurrence.to_dict(), ensure_ascii=False) + "\n")
        return occurrence

    def occurrences(self, method_key: str) -> list[MethodOccurrence]:
        items: list[MethodOccurrence] = []
        if not self.path.is_file():
            return items
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            entry = MethodOccurrence.from_dict(json.loads(line))
            if entry.method_key == method_key:
                items.append(entry)
        return items


def _now_iso() -> str:
    from m2_information.timestamps import utc_now_iso

    return utc_now_iso()


def skillize(method_key: str, occurrences: Iterable[Mapping], skill_draft: Mapping, *,
             badcase_id: str = "", evidence_ref: str = "",
             sink: Callable[[dict], Any] | None = None,
             now_fn: Callable[[], str] | None = None) -> SkillDescriptor:
    """门槛校验 + 产出 SkillDescriptor 候选（不满足门槛抛 ``SkillizeError``）。

    - 判据通过口径：``judge_passed`` 为真的出现记录；
    - 不同任务实例：通过的记录里不同 ``task_id`` 计数 ≥ ``MIN_OCCURRENCES``；
    - 候选 status 强制 ``REVIEW``（M7 评审），evidence_policy 强制含
      黄金成绩提升证明（追加 A/B 实验引用）。
    """
    now_fn = now_fn or _now_iso
    passing = [MethodOccurrence.from_dict(item) for item in occurrences
               if bool(item.get("judge_passed"))]
    distinct_tasks = {item.task_id for item in passing}
    if len(distinct_tasks) < MIN_OCCURRENCES:
        raise SkillizeError(
            f"方法 {method_key!r} 仅在 {len(distinct_tasks)} 个不同任务实例判据通过，"
            f"不足 {MIN_OCCURRENCES} 个（SPEC-M6-05 防一次性巧合门槛），不触发 Skill 化")

    draft = dict(skill_draft)
    evidence_policy = str(draft.get("evidence_policy") or "")
    proof_note = (f"受控自进化：{len(distinct_tasks)} 个任务实例判据通过"
                  f"（≥{MIN_OCCURRENCES}）")
    if evidence_ref:
        proof_note += f"；黄金成绩提升证明：{evidence_ref}"
    draft["evidence_policy"] = (evidence_policy + " | " if evidence_policy else "") + proof_note
    draft["status"] = "REVIEW"  # 候选：走 M7 变更评审（SPEC-M6-05）
    from contracts import ContractValidationError

    try:
        descriptor = SkillDescriptor.from_dict(draft)
    except ContractValidationError as exc:
        raise SkillizeError(f"SkillDescriptor 草案契约校验失败: {exc}") from exc

    if sink is not None:
        from m2_information.ids import new_ulid

        sink({
            "event_id": new_ulid(),
            "type": EventType.SKILL_PROMOTED.value,
            "subject": descriptor.skill_id,
            "payload": {
                "method_key": method_key,
                "stage": "CANDIDATE_FOR_M7_REVIEW",
                "distinct_tasks": sorted(distinct_tasks),
                "badcase_id": badcase_id,
                "evidence_policy": descriptor.evidence_policy,
            },
            "occurred_at": now_fn(),
            "trace_id": f"trace-skill-{descriptor.skill_id}",
            "producer": "M6",
        })
    return descriptor


def promote_to_skill(badcase_id: str, skill_draft: Mapping, *,
                     ledger: MethodLedger | None = None,
                     store=None, repo_root: Path | str | None = None,
                     sink: Callable[[dict], Any] | None = None) -> SkillDescriptor:
    """01 §3.6 冻结 API：``promote_to_skill(badcase_id, skill_draft) -> SkillId``。

    出现记录取方法台账（method_key = 草案 skill_id）；A/B 提升证明取该 badcase
    的实验归档（若台账可查）。
    """
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    if ledger is None:
        ledger = MethodLedger(root / "runtime" / "m6_flywheel" / "methods.jsonl")
    method_key = str(dict(skill_draft).get("skill_id") or "")
    if not method_key:
        raise SkillizeError("skill_draft.skill_id 必填（方法台账主键）")
    occurrences = [item.to_dict() for item in ledger.occurrences(method_key)]
    evidence_ref = ""
    if store is not None:
        try:
            record = store.get(badcase_id)
            archive = (record.experiment or {}).get("archive")
            if archive:
                evidence_ref = str(archive)
        except Exception:  # noqa: BLE001 - 台账缺 badcase 不阻断候选产出
            evidence_ref = ""
    return skillize(method_key, occurrences, skill_draft, badcase_id=badcase_id,
                    evidence_ref=evidence_ref, sink=sink)
