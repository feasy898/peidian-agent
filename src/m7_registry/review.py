# -*- coding: utf-8 -*-
"""m7_registry.review · 变更评审流水线（SPEC-M7-03；M7 §2 ``review.py``）。

状态机（表驱动，``REVIEW_TRANSITIONS``；EVAL 断言与
``tests/fixtures/m7_state_machines.yaml`` diff 为空）::

    PROPOSED → EVALUATING | REJECTED | WITHDRAWN
    EVALUATING → APPROVED | REJECTED | WITHDRAWN
    APPROVED → PUBLISHED
    PUBLISHED / REJECTED / WITHDRAWN 为终态

提案必含三要素：动机（motivation）+ 影响面（impact）+ 关联 Badcase（badcases）。

评审通过前置（SPEC-M7-03）：黄金集跑分不低于现行——``start_evaluation`` 消费
M6 评估归档（``run_golden`` 的 report.json，引用 M6 结果，M7 不自己跑分）：
candidate 总分（``totals.score_100``，缺则 ``pass_rate``×100）≥ baseline
（baseline 缺省取现行已发布 release 的 golden_scores，无现行 release 时为 0）。

**跳过评审直接发布在 publish 入口被拒（代码级断言，无旁路）**：
``publish_asset``（01 §3.7 冻结 API）是资产置 PUBLISHED 的唯一入口——
它同时校验 (a) review 记录存在且 state==APPROVED、(b) 该记录在评审 journal
中真实存在（伪造的 ReviewRecord 数据对象也过不了）、(c) 版本匹配资产当前
chain；任一不满足 → :class:`ReviewBypassError` + 审计事件（``release.published``
``{stage: asset-publish, rejected: true}``——事件目录无 review.* 主题，沿用
M1/M2/M3/M6"就近落主题+rejected 标记"先例）。资产状态迁移入口
``AssetStore._set_status`` 为模块私有，publish_asset 是其唯一持久化调用方。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

from contracts import EventType

from .assets import AssetNotFoundError, AssetStore, AssetRecord

__all__ = [
    "REVIEW_TRANSITIONS",
    "REVIEW_TERMINALS",
    "ReviewError",
    "IllegalReviewTransitionError",
    "ProposalIncompleteError",
    "ReviewBypassError",
    "GoldenRegressionError",
    "ReviewRecord",
    "ReviewPipeline",
    "publish_asset",
    "load_m6_report",
    "score_of_report",
]

#: 评审流状态机（M7 §2；与 tests/fixtures/m7_state_machines.yaml diff 必须为空）
REVIEW_TRANSITIONS = {
    "PROPOSED": ("EVALUATING", "REJECTED", "WITHDRAWN"),
    "EVALUATING": ("APPROVED", "REJECTED", "WITHDRAWN"),
    "APPROVED": ("PUBLISHED",),
    "PUBLISHED": (),
    "REJECTED": (),
    "WITHDRAWN": (),
}

REVIEW_TERMINALS = ("PUBLISHED", "REJECTED", "WITHDRAWN")


class ReviewError(ValueError):
    """评审流基错误。"""


class IllegalReviewTransitionError(ReviewError):
    """非法状态迁移。"""


class ProposalIncompleteError(ReviewError):
    """提案缺动机/影响面/关联 Badcase（SPEC-M7-03）。"""


class ReviewBypassError(PermissionError, ReviewError):
    """跳过评审直接发布被拒（publish 入口代码级断言）。"""


class GoldenRegressionError(ReviewError):
    """黄金集跑分低于现行（评审通过前置不满足）。"""


def _now() -> str:
    from m2_information.timestamps import utc_now_iso

    return utc_now_iso()


def _ulid() -> str:
    from m2_information.ids import new_ulid

    return new_ulid()


# ---------------------------------------------------------------------------
# M6 结果引用（消费 runs/eval/<stamp>-<release>/report.json；M7 不自己跑分）
# ---------------------------------------------------------------------------
_M6_REPORT_REQUIRED = ("release_id", "mode", "golden_set_version", "cases",
                       "pass_rate", "totals")


def load_m6_report(path: Path | str | Mapping) -> dict:
    """装载并形状校验一份 M6 评估归档（evaluator report 结构标记）。"""
    if isinstance(path, Mapping):
        report = dict(path)
        origin = "<inline>"
    else:
        source = Path(path)
        if not source.is_file():
            raise ReviewError(f"M6 评估归档不存在: {source}")
        report = json.loads(source.read_text(encoding="utf-8"))
        origin = str(source)
    missing = [key for key in _M6_REPORT_REQUIRED if key not in report]
    if missing:
        raise ReviewError(f"{origin}: 非 M6 评估归档形态（缺字段 {missing}）")
    if str(report.get("mode")) != "SIMULATION":
        raise ReviewError(f"{origin}: M6 评估归档 mode 必须为 SIMULATION（01 §8）")
    if not isinstance(report.get("cases"), list):
        raise ReviewError(f"{origin}: M6 评估归档 cases 必须是列表")
    return report


def score_of_report(report: Mapping) -> float:
    """跑分口径：totals.score_100（百分制）；缺则 pass_rate×100。"""
    totals = report.get("totals") or {}
    try:
        return float(totals["score_100"])
    except (KeyError, TypeError, ValueError):
        return float(report.get("pass_rate") or 0.0) * 100.0


# ---------------------------------------------------------------------------
# 评审记录与流水线
# ---------------------------------------------------------------------------
class ReviewRecord:
    """一条资产版本的评审记录（提案→评估→批准→发布 全程留痕）。"""

    __slots__ = ("proposal_id", "asset_id", "chain", "version", "motivation",
                 "impact", "badcases", "state", "golden", "history", "created_at",
                 "decided_at")

    def __init__(self, proposal_id: str, asset_id: str, chain: int, version: str,
                 motivation: str, impact: str, badcases: list, state: str,
                 golden: dict | None, history: list, created_at: str,
                 decided_at: str | None = None) -> None:
        self.proposal_id = proposal_id
        self.asset_id = asset_id
        self.chain = chain
        self.version = version
        self.motivation = motivation
        self.impact = impact
        self.badcases = list(badcases)
        self.state = state
        self.golden = dict(golden or {})
        self.history = list(history)
        self.created_at = created_at
        self.decided_at = decided_at

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id, "asset_id": self.asset_id,
            "chain": self.chain, "version": self.version,
            "motivation": self.motivation, "impact": self.impact,
            "badcases": self.badcases, "state": self.state,
            "golden": self.golden, "history": self.history,
            "created_at": self.created_at, "decided_at": self.decided_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> "ReviewRecord":
        return cls(str(data["proposal_id"]), str(data["asset_id"]),
                   int(data["chain"]), str(data["version"]),
                   str(data.get("motivation") or ""), str(data.get("impact") or ""),
                   list(data.get("badcases") or []), str(data.get("state") or ""),
                   dict(data.get("golden") or {}), list(data.get("history") or []),
                   str(data.get("created_at") or ""), data.get("decided_at"))

    def to_contract_payload(self) -> dict:
        """01 §3.7 ``publish_asset(asset_id, review)`` 的 review 载荷形态。"""
        return self.to_dict()


class ReviewPipeline:
    """评审流水线：journal 追加写 + 重放重建（与资产/发布 journal 同款）。"""

    def __init__(self, store: AssetStore,
                 journal_path: Path | str | None = None,
                 sink: Callable[[dict], Any] | None = None,
                 now_fn: Callable[[], str] | None = None) -> None:
        self.store = store
        self.journal_path = Path(journal_path) if journal_path is not None else None
        self.sink = sink
        self.now_fn = now_fn or _now
        self._proposals: dict[str, ReviewRecord] = {}
        if self.journal_path is not None and self.journal_path.is_file():
            for line in self.journal_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("op") == "proposal":
                    record = ReviewRecord.from_dict(entry["record"])
                    self._proposals[record.proposal_id] = record

    # ------------------------------------------------------------ journal
    def _persist(self, record: ReviewRecord) -> None:
        if self.journal_path is None:
            return
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"op": "proposal", "record": record.to_dict()},
                                    ensure_ascii=False, sort_keys=True,
                                    default=str) + "\n")

    def _emit(self, record: ReviewRecord, from_state: str, to_state: str,
              extra: dict | None = None) -> None:
        """评审迁移审计事件（就近主题 release.published + stage=review）。"""
        if self.sink is None:
            return
        from contracts import EventRecord

        payload = {"stage": "review", "from": from_state, "to": to_state,
                   "proposal_id": record.proposal_id,
                   "asset": f"{record.asset_id}@{record.version}",
                   "chain": record.chain, **(extra or {})}
        event = {
            "event_id": _ulid(),
            "type": EventType.RELEASE_PUBLISHED.value,
            "subject": record.asset_id,
            "payload": payload,
            "occurred_at": self.now_fn(),
            "trace_id": f"trace-review-{record.proposal_id}",
            "producer": "M7",
        }
        try:
            EventRecord.from_dict(event)
        except Exception as exc:  # noqa: BLE001 - 审计事件必须合约
            raise ReviewError(f"评审审计事件不合约: {exc}") from exc
        self.sink(event)

    def _transition(self, record: ReviewRecord, to_state: str) -> None:
        from_state = record.state
        allowed = REVIEW_TRANSITIONS.get(from_state, ())
        if to_state not in allowed:
            raise IllegalReviewTransitionError(
                f"评审流非法迁移 {from_state}→{to_state}"
                f"（合法: {list(allowed) or ['<终态>']}）")
        record.state = to_state
        record.history.append({"from": from_state, "to": to_state,
                               "at": self.now_fn()})

    # ------------------------------------------------------------ 流水线步骤
    def submit_proposal(self, asset_id: str, *, motivation: str, impact: str,
                        badcases: list | None = None) -> ReviewRecord:
        """提交变更提案 → PROPOSED（提案必含动机+影响面+关联 Badcase）。"""
        record = self.store.latest(asset_id)  # 未注册即 AssetNotFoundError
        if not str(motivation or "").strip():
            raise ProposalIncompleteError("提案缺动机（motivation）")
        if not str(impact or "").strip():
            raise ProposalIncompleteError("提案缺影响面（impact）")
        if badcases is None or not list(badcases):
            raise ProposalIncompleteError(
                "提案缺关联 Badcase（badcases；无关联时显式传 ['none']）")
        proposal = ReviewRecord(
            proposal_id=f"rev-{record.asset_id}-{record.chain:03d}",
            asset_id=record.asset_id, chain=record.chain, version=record.version,
            motivation=str(motivation), impact=str(impact), badcases=list(badcases),
            state="PROPOSED", golden=None,
            history=[{"from": None, "to": "PROPOSED", "at": self.now_fn()}],
            created_at=self.now_fn())
        if proposal.proposal_id in self._proposals:
            raise ReviewError(
                f"提案 {proposal.proposal_id} 已存在（该版本已有在途/已完成评审）")
        self._proposals[proposal.proposal_id] = proposal
        self._persist(proposal)
        self._emit(proposal, None, "PROPOSED")
        return proposal

    def start_evaluation(self, proposal_id: str, *, candidate_run_ref: str | Mapping,
                         baseline_run_ref: str | Mapping | None = None,
                         baseline_score: float | None = None) -> ReviewRecord:
        """EVALUATING → 黄金跑分比对（引用 M6 结果；SPEC-M7-03 前置）。

        candidate = 变更后版本的 M6 评估归档；baseline 缺省取现行已发布 release
        的 golden_scores（无现行 release 时按 0 计——首个 release 无可回归基线）。
        跑分不低于现行 → APPROVED，否则 → REJECTED（GoldenRegressionError 语义
        落在记录 state，同时抛出供调用方感知）。
        """
        record = self._require(proposal_id)
        candidate = load_m6_report(candidate_run_ref)
        if baseline_run_ref is not None:
            baseline_report = load_m6_report(baseline_run_ref)
            baseline = score_of_report(baseline_report)
        elif baseline_score is not None:
            baseline = float(baseline_score)
        else:
            baseline = self._current_baseline(record.asset_id)
        candidate_score = score_of_report(candidate)
        self._transition(record, "EVALUATING")
        record.golden = {
            "candidate_run_ref": str(candidate_run_ref),
            "candidate_score": round(candidate_score, 4),
            "baseline_score": round(baseline, 4),
            "golden_set_version": str(candidate.get("golden_set_version") or ""),
            "pass_rate": candidate.get("pass_rate"),
        }
        self._persist(record)
        self._emit(record, "PROPOSED", "EVALUATING", {"golden": record.golden})
        if candidate_score + 1e-9 < baseline:
            record.decided_at = self.now_fn()
            self._transition(record, "REJECTED")
            self._persist(record)
            self._emit(record, "EVALUATING", "REJECTED",
                       {"reason": "黄金集跑分低于现行（SPEC-M7-03 前置）"})
            raise GoldenRegressionError(
                f"评审通过前置不满足：candidate {candidate_score:.2f}"
                f" < 现行 baseline {baseline:.2f}（引用 M6 结果）")
        record.decided_at = self.now_fn()
        self._transition(record, "APPROVED")
        self._persist(record)
        self._emit(record, "EVALUATING", "APPROVED", {"golden": record.golden})
        return record

    def reject(self, proposal_id: str, reason: str) -> ReviewRecord:
        """拒绝分支（PROPOSED/EVALUATING → REJECTED）。"""
        record = self._require(proposal_id)
        from_state = record.state
        self._transition(record, "REJECTED")
        record.decided_at = self.now_fn()
        self._persist(record)
        self._emit(record, from_state, "REJECTED", {"reason": str(reason)})
        return record

    def withdraw(self, proposal_id: str, reason: str = "") -> ReviewRecord:
        """撤回分支（PROPOSED/EVALUATING → WITHDRAWN）。"""
        record = self._require(proposal_id)
        from_state = record.state
        self._transition(record, "WITHDRAWN")
        record.decided_at = self.now_fn()
        self._persist(record)
        self._emit(record, from_state, "WITHDRAWN", {"reason": str(reason)})
        return record

    # ------------------------------------------------------------ 辅助
    def _require(self, proposal_id: str) -> ReviewRecord:
        record = self._proposals.get(str(proposal_id))
        if record is None:
            raise ReviewError(f"评审提案不存在: {proposal_id!r}")
        return record

    def get(self, proposal_id: str) -> ReviewRecord:
        return self._require(proposal_id)

    def proposal_of(self, asset_id: str, chain: int | None = None) -> ReviewRecord | None:
        """资产（缺省当前 chain）的评审记录。"""
        target_chain = chain if chain is not None else self.store.latest(asset_id).chain
        for record in self._proposals.values():
            if record.asset_id == asset_id and record.chain == target_chain:
                return record
        return None

    def _current_baseline(self, asset_id: str) -> float:
        """现行基线：已发布 release 的 golden_scores（release.py 注入读取器）。"""
        reader = getattr(self, "baseline_reader", None)
        if reader is None:
            return 0.0
        scores = reader()
        if not scores:
            return 0.0
        return score_of_report(scores)


def publish_asset(asset_id: str, review: ReviewRecord | Mapping, *,
                  store: AssetStore, pipeline: ReviewPipeline) -> str:
    """01 §3.7 冻结 API：``publish_asset(asset_id, review) -> status``。

    **评审门禁（SPEC-M7-03，代码级断言无旁路）**，全部满足才置 PUBLISHED：
    1. review 是评审 journal 中真实存在的记录（伪造数据对象过不了）；
    2. 记录 state == APPROVED（跳过评审直接发布被拒）；
    3. 记录绑定 asset_id+chain 与资产当前版本一致（旧版本评审不能发布新版本）；
    4. 评审通过前置的黄金成绩在记录内留痕（golden.candidate_score 存在）。

    拒绝路径：ReviewBypassError + 审计事件 ``release.published
    {stage: asset-publish, rejected: true, reason}``。
    """
    def audit(reason: str, payload: dict | None = None) -> None:
        if pipeline.sink is None:
            return
        from contracts import EventRecord

        event = {
            "event_id": _ulid(),
            "type": EventType.RELEASE_PUBLISHED.value,
            "subject": asset_id,
            "payload": {"stage": "asset-publish", "rejected": True,
                        "reason": reason, **(payload or {})},
            "occurred_at": pipeline.now_fn(),
            "trace_id": f"trace-publish-{asset_id}",
            "producer": "M7",
        }
        try:
            EventRecord.from_dict(event)
        except Exception as exc:  # noqa: BLE001
            raise ReviewError(f"发布拒绝审计事件不合约: {exc}") from exc
        pipeline.sink(event)

    payload = review.to_contract_payload() if isinstance(review, ReviewRecord) else dict(review or {})
    proposal_id = str(payload.get("proposal_id") or "")
    journal_record = pipeline._proposals.get(proposal_id)
    if journal_record is None:
        reason = f"评审记录不在评审 journal 中（proposal_id={proposal_id!r}）——" \
                 f"跳过评审直接发布被拒（SPEC-M7-03）"
        audit(reason, {"state": payload.get("state")})
        raise ReviewBypassError(f"publish_asset 拒绝: {reason}")
    try:
        current: AssetRecord = store.latest(asset_id)
    except AssetNotFoundError as exc:
        audit(f"资产未注册: {asset_id!r}")
        raise ReviewBypassError(f"publish_asset 拒绝: {exc}") from exc
    if journal_record.state != "APPROVED":
        reason = (f"评审状态 {journal_record.state} != APPROVED——"
                  f"跳过评审直接发布被拒（SPEC-M7-03）")
        audit(reason, {"state": journal_record.state})
        raise ReviewBypassError(f"publish_asset 拒绝: {reason}")
    if journal_record.asset_id != asset_id or journal_record.chain != current.chain:
        reason = (f"评审记录版本失配（review 绑定 {journal_record.asset_id}"
                  f"@chain{journal_record.chain}，资产当前 chain{current.chain}）")
        audit(reason)
        raise ReviewBypassError(f"publish_asset 拒绝: {reason}")
    if "candidate_score" not in (journal_record.golden or {}):
        reason = "评审记录缺黄金成绩留痕（评审通过前置未执行）"
        audit(reason)
        raise ReviewBypassError(f"publish_asset 拒绝: {reason}")
    # 通过：评审流 APPROVED→PUBLISHED + 资产状态 PUBLISHED（唯一入口）
    pipeline._transition(journal_record, "PUBLISHED")
    journal_record.decided_at = pipeline.now_fn()
    pipeline._persist(journal_record)
    pipeline._emit(journal_record, "APPROVED", "PUBLISHED")
    store._set_status(asset_id, "PUBLISHED")
    return store.status_of(asset_id)
