# -*- coding: utf-8 -*-
"""m2_information.session · Call/Session/Task 三级管理。

specs/M2-information.md §2：``session.py  # Call/Session/Task 三级对象``。

层级：Call ⊂ Session ⊂ Task——
- Task：一次任务（TaskState 权威状态，state_store 持有）；
- Session：任务内一段连续执行段（任务恢复/等待返回后重开会话）；
- Call：一次模型调用（绑定 turn 与当轮 ContextManifest hash，供 M6 轨迹采集）。

持久化：StateStore 的 sessions/calls 表（task_state 四表之上的超集表，
偏差已登记 tests/CHANGELOG.md）。
"""
from __future__ import annotations

from typing import Any, Callable

from .ids import new_ulid
from .state_store import StateStore, TaskStateNotFoundError
from .timestamps import utc_now_iso

__all__ = ["SessionRecord", "CallRecord", "SessionManager", "SessionNotFoundError"]


class SessionNotFoundError(KeyError):
    """会话/调用不存在。"""


def _row_to_session(row: dict) -> dict:
    return {
        "session_id": row["session_id"],
        "task_id": row["task_id"],
        "started_at": row["started_at"],
        "ended_at": row.get("ended_at") or "",
        "meta": _loads(row.get("meta_json")),
    }


def _row_to_call(row: dict) -> dict:
    return {
        "call_id": row["call_id"],
        "session_id": row["session_id"],
        "task_id": row["task_id"],
        "turn": row["turn"],
        "manifest_hash": row.get("manifest_hash") or "",
        "tokens": row.get("tokens") or 0,
        "created_at": row["created_at"],
    }


def _loads(text: Any) -> dict:
    import json

    return json.loads(text or "{}")


class SessionRecord(dict):
    """会话记录（dict 便捷子类）。"""

    @property
    def session_id(self) -> str:
        return self["session_id"]


class CallRecord(dict):
    """调用记录。"""

    @property
    def call_id(self) -> str:
        return self["call_id"]


class SessionManager:
    """三级对象管理（持久化到 StateStore.sessions/calls）。"""

    def __init__(self, store: StateStore, *, now_fn: Callable[[], str] = utc_now_iso,
                 id_gen: Callable[[], str] = new_ulid) -> None:
        self.store = store
        self._now = now_fn
        self._id = id_gen

    def open_session(self, task_id: str, *, trace_id: str = "") -> SessionRecord:
        """为任务开一段会话（任务必须已存在；重复开段=新 session）。"""
        if not self.store.has_task(task_id):
            raise TaskStateNotFoundError(f"任务不存在，无法开会话: {task_id}")
        session_id = f"sess-{self._id()}"
        now = self._now()
        self.store.execute(
            "INSERT INTO sessions(session_id, task_id, started_at, ended_at, meta_json)"
            " VALUES(?,?,?,'',?)",
            (session_id, task_id, now, _dumps({"trace_id": trace_id})),
        )
        return SessionRecord({"session_id": session_id, "task_id": task_id,
                              "started_at": now, "ended_at": "", "meta": {"trace_id": trace_id}})

    def end_session(self, session_id: str) -> SessionRecord:
        row = self._session_row(session_id)
        self.store.execute(
            "UPDATE sessions SET ended_at=? WHERE session_id=?",
            (self._now(), session_id),
        )
        session = _row_to_session(row)
        session["ended_at"] = self._now()
        return SessionRecord(session)

    def begin_call(self, session_id: str, *, turn: int, manifest_hash: str = "") -> CallRecord:
        row = self._session_row(session_id)
        call_id = f"call-{self._id()}"
        now = self._now()
        self.store.execute(
            "INSERT INTO calls(call_id, session_id, task_id, turn, manifest_hash, tokens,"
            " created_at) VALUES(?,?,?,?,0,?,?)",
            (call_id, session_id, row["task_id"], int(turn), manifest_hash, now),
        )
        return CallRecord({"call_id": call_id, "session_id": session_id,
                           "task_id": row["task_id"], "turn": int(turn),
                           "manifest_hash": manifest_hash, "tokens": 0, "created_at": now})

    def end_call(self, call_id: str, *, tokens: int) -> CallRecord:
        row = self._call_row(call_id)
        self.store.execute(
            "UPDATE calls SET tokens=? WHERE call_id=?", (int(tokens), call_id)
        )
        call = _row_to_call(row)
        call["tokens"] = int(tokens)
        return CallRecord(call)

    def session(self, session_id: str) -> SessionRecord:
        return SessionRecord(_row_to_session(self._session_row(session_id)))

    def call(self, call_id: str) -> CallRecord:
        return CallRecord(_row_to_call(self._call_row(call_id)))

    def calls_of(self, session_id: str) -> list[CallRecord]:
        rows = self.store.execute(
            "SELECT * FROM calls WHERE session_id=? ORDER BY created_at, call_id",
            (session_id,),
        )
        return [CallRecord(_row_to_call(r)) for r in rows]

    def sessions_of_task(self, task_id: str) -> list[SessionRecord]:
        rows = self.store.execute(
            "SELECT * FROM sessions WHERE task_id=? ORDER BY started_at, session_id",
            (task_id,),
        )
        return [SessionRecord(_row_to_session(r)) for r in rows]

    def lineage(self, call_id: str) -> dict:
        """Call ⊂ Session ⊂ Task 归属链。"""
        call = _row_to_call(self._call_row(call_id))
        session = _row_to_session(self._session_row(call["session_id"]))
        return {"call": call, "session": session, "task_id": session["task_id"]}

    # ---------------------------------------------------------- 内部
    def _session_row(self, session_id: str) -> dict:
        rows = self.store.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        )
        if not rows:
            raise SessionNotFoundError(f"会话不存在: {session_id}")
        return rows[0]

    def _call_row(self, call_id: str) -> dict:
        rows = self.store.execute("SELECT * FROM calls WHERE call_id=?", (call_id,))
        if not rows:
            raise SessionNotFoundError(f"调用不存在: {call_id}")
        return rows[0]


def _dumps(obj: dict) -> str:
    import json

    return json.dumps(obj or {}, ensure_ascii=False)
