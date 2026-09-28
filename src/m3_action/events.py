# -*- coding: utf-8 -*-
"""m3_action.events · 事件日志（追加写 runtime/events/*.jsonl）。

契约（specs/01-contracts.md §4/§8）：
- ``runtime/events/*.jsonl`` 为追加写唯一权威流；每条记录经 ``contracts.EventRecord``
  校验（缺 trace_id 在写入时被拒）；
- 分片命名与 M2 对齐：``task-<task_id>.jsonl``（任务全生命周期事件同一分片）。

确定性：event_id 为分片内递增序号（``EVT-M3-<seq>``，从既有文件行数续起），
不引入随机量——同操作序重放产生逐字节相同的事件流（配合 M5 确定性重放纪律）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from contracts import EventRecord

from .clocking import now_iso, to_jsonable

__all__ = ["EventJournal", "EventWriteError"]

_STREAM_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


class EventWriteError(ValueError):
    """事件写入被拒（契约校验失败）。"""


class EventJournal:
    """M3 事件追加写日志（EventRecord 契约校验 + 确定性序号）。"""

    producer = "M3"

    def __init__(self, events_dir: Path, *, now_fn: Callable[[], str] | None = None) -> None:
        self.events_dir = Path(events_dir)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self._now_fn = now_fn or now_iso
        self._seq: dict[str, int] = {}

    # ------------------------------------------------------------------ 写
    def stream_path(self, stream: str) -> Path:
        safe = _STREAM_SAFE_RE.sub("_", str(stream)) or "default"
        return self.events_dir / f"{safe}.jsonl"

    def _next_event_id(self, stream: str) -> str:
        if stream not in self._seq:
            path = self.stream_path(stream)
            count = 0
            if path.is_file():
                with path.open("r", encoding="utf-8") as handle:
                    count = sum(1 for line in handle if line.strip())
            self._seq[stream] = count
        self._seq[stream] += 1
        return f"EVT-M3-{self._seq[stream]:06d}"

    def append(
        self,
        event_type: str,
        subject: str,
        payload: dict,
        *,
        trace_id: str,
        occurred_at: str | None = None,
        stream: str | None = None,
        producer: str = "M3",
    ) -> dict:
        """追加一条事件（契约校验失败抛 EventWriteError，缺 trace_id 即拒）。"""
        record = {
            "event_id": self._next_event_id(stream or f"subject-{subject}"),
            "type": event_type,
            "subject": subject,
            "payload": to_jsonable(dict(payload or {})),
            "occurred_at": to_jsonable(occurred_at or self._now_fn()),
            "trace_id": trace_id,
            "producer": producer,
        }
        try:
            rec = EventRecord.from_dict(record)
        except Exception as exc:  # noqa: BLE001 - 统一转 EventWriteError
            raise EventWriteError(f"事件写入被拒: {exc}") from exc
        target = self.stream_path(stream) if stream else self.stream_path(f"subject-{rec.subject}")
        line = json.dumps(rec.to_dict(), ensure_ascii=False)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return rec.to_dict()

    # ------------------------------------------------------------------ 读
    def read(self, stream: str) -> list[dict]:
        path = self.stream_path(stream)
        if not path.is_file():
            return []
        records: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
        return records

    def read_all(self) -> list[dict]:
        out: list[dict] = []
        for path in sorted(self.events_dir.glob("*.jsonl")):
            out.extend(self.read(path.stem))
        return out

    @staticmethod
    def task_stream(task_id: str) -> str:
        return f"task-{task_id}"
