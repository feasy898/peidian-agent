# -*- coding: utf-8 -*-
"""m2_information.event_log · 事件流（追加写唯一权威流 + TaskState 重建）。

契约（specs/01-contracts.md §4 / §8；specs/M2-information.md §2）：
- ``runtime/events/*.jsonl`` 为追加写唯一权威流；TaskState 可由事件流重建；
- 每条记录经 ``contracts.EventRecord`` 校验（缺 trace_id 在写入时被拒）；
- 任何模块不得仅凭消息队列内容变更权威状态。

分片：按 ``stream``（默认 task-<task_id>）一个任务一个文件，任务全生命周期
事件（task.*/action.*/artifact.*/budget.* 等）落同一分片，供回放与重建。

重建协议（rebuild_task_state）：
1. ``task.created`` 的 ``payload.state`` 为初始全量 TaskState dict；
2. ``task.status_changed``（``payload.accepted != false``）逐条折叠：
   - ``payload.mutation`` 按状态变更语义应用到 TaskState dict；
   - ``payload.state``（restore 快照）出现时整量替换；
   - ``payload.to/version/updated_at`` 覆盖对应字段；
3. 折叠结果经 ``contracts.TaskState.from_dict`` 终校验，与库内快照 diff 为空
   （M2 DoD §5）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from contracts import EventRecord

from .ids import new_ulid
from .state_store import TaskStateNotFoundError, apply_state_mutation

__all__ = ["EventLog", "EventAppendError"]

_STREAM_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


class EventAppendError(ValueError):
    """事件写入被拒（契约校验失败）。"""


class EventLog:
    """events/*.jsonl 追加写事件流。"""

    def __init__(self, events_dir: Path) -> None:
        self.events_dir = Path(events_dir)
        self.events_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ 写
    def stream_path(self, stream: str) -> Path:
        """流文件路径（流名净化，仅允许安全字符）。"""
        safe = _STREAM_SAFE_RE.sub("_", str(stream)) or "default"
        return self.events_dir / f"{safe}.jsonl"

    def append(
        self,
        record: dict | EventRecord,
        *,
        stream: str | None = None,
        now_fn: Callable[[], str] | None = None,
    ) -> EventRecord:
        """追加一条事件；缺 trace_id/枚举越界等契约失败即抛 EventAppendError。"""
        if isinstance(record, EventRecord):
            rec = record
        else:
            payload = dict(record)
            payload.setdefault("event_id", new_ulid())
            if not payload.get("occurred_at"):
                payload["occurred_at"] = (now_fn or _default_now)()
            try:
                rec = EventRecord.from_dict(payload)
            except Exception as exc:  # noqa: BLE001 - 统一转 EventAppendError
                raise EventAppendError(f"事件写入被拒: {exc}") from exc
        target = self.stream_path(stream if stream else f"subject-{rec.subject}")
        line = json.dumps(rec.to_dict(), ensure_ascii=False)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return rec

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

    def read_records(self, stream: str) -> list[EventRecord]:
        return [EventRecord.from_dict(item) for item in self.read(stream)]

    def streams(self) -> list[str]:
        return sorted(p.stem for p in self.events_dir.glob("*.jsonl"))

    def task_stream_name(self, task_id: str) -> str:
        return f"task-{task_id}"

    def events_for_task(self, task_id: str) -> list[dict]:
        return self.read(self.task_stream_name(task_id))

    def query(
        self, task_id: str, *types: str, subject: str | None = None
    ) -> list[dict]:
        """按 type/subject 过滤任务事件（回放辅助）。"""
        wanted = set(types)
        out = []
        for item in self.events_for_task(task_id):
            if wanted and item.get("type") not in wanted:
                continue
            if subject is not None and item.get("subject") != subject:
                continue
            out.append(item)
        return out

    # -------------------------------------------------------------- 重建
    def rebuild_task_state(self, task_id: str) -> Any:
        """从事件流重建 TaskState（不依赖 SQLite；空流 → TaskStateNotFoundError）。"""
        state: dict | None = None
        for event in self.events_for_task(task_id):
            etype = event.get("type")
            payload = event.get("payload") or {}
            if etype == "task.created":
                state = dict(payload.get("state") or {})
                state.setdefault("task_id", task_id)
            elif etype == "task.status_changed":
                if payload.get("accepted") is False:
                    continue  # 非法迁移拒绝事件，不改变权威状态
                if state is None:
                    raise TaskStateNotFoundError(
                        f"任务 {task_id} 缺 task.created 事件，无法重建"
                    )
                if isinstance(payload.get("state"), dict):
                    state = dict(payload["state"])
                elif isinstance(payload.get("mutation"), dict):
                    apply_state_mutation(state, payload["mutation"])
                if payload.get("to"):
                    state["status"] = payload["to"]
                if payload.get("version") is not None:
                    state["version"] = int(payload["version"])
                if payload.get("updated_at"):
                    state["updated_at"] = payload["updated_at"]
        if state is None:
            raise TaskStateNotFoundError(f"任务 {task_id} 无事件流，无法重建")
        from contracts import TaskState  # 局部导入避免模块级循环

        return TaskState.from_dict(state)


def _default_now() -> str:  # pragma: no cover - 由 timestamps 统一
    from .timestamps import utc_now_iso

    return utc_now_iso()
