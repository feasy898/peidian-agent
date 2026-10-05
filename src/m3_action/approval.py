# -*- coding: utf-8 -*-
"""m3_action.approval · 审批队列（HITL）：持久化 + 超时（SPEC-M3-04/07；M3 §2）。

- 持久化：``runtime/m3_action/approvals.jsonl`` 追加写日志（enqueued/resolved/
  expired 三类记录）；重启时重放日志重建 pending 集——WAITING_APPROVAL 项不丢
  （M3 §5 DoD）。条目携带完整 ActionRequest dict，重启后 GRANT 仍可继续执行；
- 超时：WAITING_APPROVAL 超过 ``approval_timeout_s``（默认 300s，M3 §3 SPEC-M3-07）
  → REJECTED（payload 带 timeout），对应任务收 ``approval.timeout`` 事件；
- 审批放行只消费一次性条目（resolve 后不可重放）——不改 Policy 缺省（SPEC-M3-05）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .clocking import normalize_ts, seconds_between, to_jsonable

__all__ = ["ApprovalQueue", "ApprovalEntry", "DEFAULT_APPROVAL_TIMEOUT_S"]

#: 审批超时缺省（SPEC-M3-07：默认 300s；301s 无响应 → REJECTED/timeout）
DEFAULT_APPROVAL_TIMEOUT_S = 300.0

_JOURNAL_KINDS = ("enqueued", "resolved", "expired")


@dataclass
class ApprovalEntry:
    """待审批条目（WAITING_APPROVAL 的持久化形态）。"""

    action_id: str
    task_id: str
    capability: str
    trace_id: str
    requested_at: str           # ActionRequest.requested_at（UTC ISO-8601）
    created_at: str             # 入队时刻（超时基准）
    timeout_s: float
    request: dict               # 完整 ActionRequest dict（重启后可继续执行）
    status: str = "WAITING_APPROVAL"
    resolved_by: str | None = None
    resolved_at: str | None = None
    resolution: str | None = None   # GRANT / DENY / TIMEOUT

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id, "task_id": self.task_id,
            "capability": self.capability, "trace_id": self.trace_id,
            "requested_at": self.requested_at, "created_at": self.created_at,
            "timeout_s": self.timeout_s, "request": self.request,
            "status": self.status, "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at, "resolution": self.resolution,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ApprovalEntry":
        return cls(**{k: data.get(k) for k in (
            "action_id", "task_id", "capability", "trace_id", "requested_at",
            "created_at", "timeout_s", "request", "status", "resolved_by",
            "resolved_at", "resolution")})

    def waited_s(self, now: str) -> float:
        return seconds_between(normalize_ts(now), normalize_ts(self.created_at))

    def is_due(self, now: str) -> bool:
        return self.waited_s(now) >= float(self.timeout_s)


class ApprovalQueue:
    """持久化审批队列（JSONL 日志重放重建）。"""

    def __init__(self, journal_path: Path, timeout_s: float = DEFAULT_APPROVAL_TIMEOUT_S) -> None:
        self.journal_path = Path(journal_path)
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_timeout_s = float(timeout_s)
        self._entries: dict[str, ApprovalEntry] = {}
        self._history: list[dict] = []
        self._replay()

    # -------------------------------------------------- 持久化
    def _replay(self) -> None:
        """重放日志重建 pending 集（重启不丢 WAITING_APPROVAL 项）。"""
        if not self.journal_path.is_file():
            return
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            kind = record.get("kind")
            if kind == "enqueued":
                entry = ApprovalEntry.from_dict(record.get("entry") or {})
                if entry.action_id:
                    self._entries[entry.action_id] = entry
                    self._history.append(record)
            elif kind in ("resolved", "expired"):
                entry = record.get("entry") or {}
                action_id = entry.get("action_id") or record.get("action_id")
                pending = self._entries.pop(action_id, None)
                merged = pending.to_dict() if pending else entry
                if kind == "resolved":
                    merged.update({"status": "REJECTED", "resolution": record.get("decision"),
                                   "resolved_by": record.get("approver"),
                                   "resolved_at": record.get("at")})
                else:
                    merged.update({"status": "REJECTED", "resolution": "TIMEOUT",
                                   "resolved_at": record.get("at"),
                                   "timeout": True})
                record = {**record, "entry": merged}
                self._history.append(record)

    def _append(self, record: dict) -> None:
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._history.append(record)

    # -------------------------------------------------- 队列操作
    def enqueue(self, *, action_id: str, task_id: str, capability: str, trace_id: str,
                requested_at: str, created_at: str, request: dict,
                timeout_s: float | None = None) -> ApprovalEntry:
        if action_id in self._entries:
            return self._entries[action_id]  # 同 action 重复入队幂等
        entry = ApprovalEntry(
            action_id=action_id, task_id=task_id, capability=capability,
            trace_id=trace_id, requested_at=requested_at, created_at=created_at,
            timeout_s=float(timeout_s if timeout_s is not None else self.default_timeout_s),
            request=dict(request))
        self._entries[action_id] = entry
        self._append({"kind": "enqueued", "entry": entry.to_dict()})
        return entry

    def get(self, action_id: str) -> ApprovalEntry | None:
        return self._entries.get(action_id)

    def pending(self) -> list:
        return [self._entries[a] for a in sorted(self._entries)]

    def resolve(self, action_id: str, decision: str, approver: str, *, at: str) -> ApprovalEntry | None:
        """审批决断（GRANT/DENY）——一次性消费条目。"""
        entry = self._entries.pop(action_id, None)
        if entry is None:
            return None
        self._append({"kind": "resolved", "action_id": action_id,
                      "decision": decision, "approver": approver, "at": at,
                      "entry": entry.to_dict()})
        return entry

    def expire_due(self, now: str) -> list:
        """到期批量超时（返回被超时条目；消费条目并落 expired 记录）。"""
        expired: list[ApprovalEntry] = []
        for action_id in sorted(self._entries):
            entry = self._entries[action_id]
            if entry.is_due(now):
                expired.append(entry)
        for entry in expired:
            self._entries.pop(entry.action_id, None)
            self._append({"kind": "expired", "action_id": entry.action_id, "at": now,
                          "entry": entry.to_dict()})
        return expired

    def journal_records(self) -> list:
        return list(self._history)
