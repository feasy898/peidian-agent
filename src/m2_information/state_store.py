# -*- coding: utf-8 -*-
"""m2_information.state_store · SQLite 持久状态仓（task_state/artifacts/memory/checkpoints）。

specs/M2-information.md §2：``state_store.py  # SQLite：task_state / artifacts /
memory / checkpoints``；specs/01-contracts.md §1 部署形态：SQLite 单文件起步
（runtime/state.db）。

- 连接串可配（DoD §5 的 PostgreSQL 迁移位）：``sqlite:///<path>`` / 裸路径 →
  SQLite；``postgres*`` → NotImplementedError（迁移位预留，本期不实现）；
- 乐观锁：``put_task(expected_version=...)`` 版本不符抛 OptimisticLockError；
- 任务状态机迁移表 ``TASK_TRANSITIONS`` 为 01 §5.1 机械转写（EVAL 断言与
  tests/fixtures/frozen_state_machines.yaml diff 为空）；
- ``apply_state_mutation`` 是 commit_state 与事件重建共用的变更语义（单一口径）。

附加表（超集，不违反规格）：knowledge（Knowledge 只读条目，M7 评审通道注册）、
sessions/calls（Call/Session/Task 三级管理，session.py 使用）。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from contracts import ArtifactRecord, TaskState

from .timestamps import utc_now_iso

__all__ = [
    "StateStore",
    "TASK_TRANSITIONS",
    "IllegalTransitionError",
    "TaskStateNotFoundError",
    "ArtifactRecordNotFoundError",
    "CheckpointNotFoundError",
    "OptimisticLockError",
    "MutationError",
    "apply_state_mutation",
    "transition_allowed",
]

# ---------------------------------------------------------------- 01 §5.1
TASK_TRANSITIONS: dict[str, list[str]] = {
    "CREATED": ["RUNNING", "CANCELLED"],
    "RUNNING": [
        "WAITING_INPUT", "WAITING_APPROVAL", "WAITING_EVENT",
        "PAUSED", "VERIFYING", "FAILED", "CANCELLED",
    ],
    "WAITING_INPUT": ["RUNNING", "CANCELLED"],
    "WAITING_APPROVAL": ["RUNNING", "CANCELLED"],
    "WAITING_EVENT": ["RUNNING", "CANCELLED"],
    "PAUSED": ["RUNNING", "CANCELLED"],
    "VERIFYING": ["COMPLETED", "RUNNING", "FAILED"],
    "COMPLETED": [],
    "FAILED": [],
    "CANCELLED": [],
}


def transition_allowed(from_status: str, to_status: str) -> bool:
    return to_status in TASK_TRANSITIONS.get(from_status, [])


class IllegalTransitionError(ValueError):
    """非法任务状态迁移（01 §5.1：抛错并落 task.status_changed 拒绝事件）。"""

    def __init__(self, from_status: str, to_status: str, machine: str = "task") -> None:
        self.from_status = from_status
        self.to_status = to_status
        self.machine = machine
        allowed = TASK_TRANSITIONS.get(from_status, [])
        super().__init__(
            f"[{machine}] 非法迁移 {from_status}→{to_status}"
            f"（{from_status} 仅允许 → {'/'.join(allowed) or '（终态只读）'}）"
        )


class TaskStateNotFoundError(KeyError):
    """任务状态不存在。"""


class ArtifactRecordNotFoundError(KeyError):
    """Artifact 记录不存在。"""


class CheckpointNotFoundError(KeyError):
    """Checkpoint 不存在。"""


class OptimisticLockError(RuntimeError):
    """乐观锁冲突（版本不符）。"""


class MutationError(ValueError):
    """StateMutation 含未知字段。"""


#: TaskState 字段级变更键（budget 为部分合并；*_add/*_remove 为列表增删）
FIELD_MUTATION_KEYS = (
    "status", "current_stage", "plan", "todos", "budget",
    "artifacts_add", "artifacts_remove", "evidence_refs_add",
    "context_manifest_hash", "subtasks", "subtasks_add",
)
#: 事件载荷允许携带、但不落入 TaskState 字段的元键（如 compact_ref/note/trace_id）
META_MUTATION_KEYS = ("compact_ref", "note", "restored_from", "trace_id")

_BUDGET_DELTA_KEYS = (
    "token_used_delta", "action_used_delta", "token_max_delta", "action_max_delta",
)
_BUDGET_SET_KEYS = ("token_max", "token_used", "action_max", "action_used", "deadline")


def apply_state_mutation(state: dict, mutation: dict) -> None:
    """将 StateMutation 就地应用到 TaskState dict（commit_state 与事件重建共用）。

    - ``budget`` 支持整量替换（dict 含 token_max 等集合键）或 ``*_delta`` 增量；
    - ``artifacts_add/remove``、``evidence_refs_add``、``subtasks_add`` 去重增删；
    - 未登记键抛 MutationError（防拼写漂移静默丢失）。
    """
    for key in mutation:
        if key not in FIELD_MUTATION_KEYS and key not in META_MUTATION_KEYS:
            raise MutationError(f"StateMutation 含未知字段: {key!r}")
    if "status" in mutation and mutation["status"] is not None:
        state["status"] = mutation["status"]
    if "current_stage" in mutation and mutation["current_stage"] is not None:
        state["current_stage"] = mutation["current_stage"]
    if "plan" in mutation and mutation["plan"] is not None:
        state["plan"] = list(mutation["plan"])
    if "todos" in mutation and mutation["todos"] is not None:
        state["todos"] = list(mutation["todos"])
    if isinstance(mutation.get("budget"), dict):
        budget = dict(state.get("budget") or {})
        for key, value in mutation["budget"].items():
            if key in _BUDGET_SET_KEYS:
                budget[key] = value
            elif key in _BUDGET_DELTA_KEYS:
                base_key = key[: -len("_delta")]
                budget[base_key] = int(budget.get(base_key, 0)) + int(value)
            elif key == "clear_deadline":
                budget.pop("deadline", None)
            else:
                raise MutationError(f"budget 变更含未知字段: {key!r}")
        state["budget"] = budget
    for key in ("artifacts_add", "evidence_refs_add", "subtasks_add"):
        if mutation.get(key):
            field = {"artifacts_add": "artifacts", "evidence_refs_add": "evidence_refs",
                     "subtasks_add": "subtasks"}[key]
            bucket = list(state.get(field) or [])
            for item in mutation[key]:
                if item not in bucket:
                    bucket.append(item)
            state[field] = bucket
    if mutation.get("artifacts_remove"):
        removed = set(mutation["artifacts_remove"])
        state["artifacts"] = [a for a in (state.get("artifacts") or []) if a not in removed]
    if "subtasks" in mutation and mutation["subtasks"] is not None:
        state["subtasks"] = list(mutation["subtasks"])
    if "context_manifest_hash" in mutation and mutation["context_manifest_hash"] is not None:
        state["context_manifest_hash"] = mutation["context_manifest_hash"]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_state(
  task_id TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  status TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  state_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts(
  artifact_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  status TEXT NOT NULL,
  record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id);
CREATE TABLE IF NOT EXISTS memory(
  memory_id TEXT PRIMARY KEY,
  task_id TEXT,
  mem_type TEXT NOT NULL,
  subject TEXT,
  content_json TEXT NOT NULL,
  provenance_json TEXT NOT NULL,
  ref_count INTEGER NOT NULL DEFAULT 0,
  superseded_by TEXT,
  created_at TEXT NOT NULL,
  valid_until TEXT NOT NULL DEFAULT '',
  archived INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_memory_type ON memory(mem_type);
CREATE TABLE IF NOT EXISTS knowledge(
  entry_id TEXT PRIMARY KEY,
  content_json TEXT NOT NULL,
  review_json TEXT NOT NULL,
  registered_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkpoints(
  checkpoint_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_task ON checkpoints(task_id);
CREATE TABLE IF NOT EXISTS sessions(
  session_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT DEFAULT '',
  meta_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS calls(
  call_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  turn INTEGER NOT NULL DEFAULT 0,
  manifest_hash TEXT DEFAULT '',
  tokens INTEGER DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_calls_session ON calls(session_id);
"""


class StateStore:
    """SQLite 状态仓（线程外使用；每次操作独立连接，避免跨线程共享）。"""

    def __init__(self, dsn: str | Path) -> None:
        self.dsn = str(dsn)
        if self.dsn.startswith("postgres"):
            raise NotImplementedError(
                "PostgreSQL 迁移位预留（M2 DoD §5：连接串可配，本期仅 SQLite）"
            )
        if self.dsn.startswith("sqlite:///"):
            path = Path(self.dsn[len("sqlite:///"):])
        else:
            path = Path(self.dsn)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = path
        with closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------ task
    def create_task(self, state: TaskState) -> TaskState:
        data = state.to_dict()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO task_state(task_id, version, status, updated_at, state_json)"
                " VALUES(?,?,?,?,?)",
                (data["task_id"], data["version"], data["status"], data["updated_at"],
                 json.dumps(data, ensure_ascii=False)),
            )
        return state

    def get_task(self, task_id: str) -> TaskState:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT state_json FROM task_state WHERE task_id=?", (task_id,)
            ).fetchone()
        if row is None:
            raise TaskStateNotFoundError(f"任务不存在: {task_id}")
        return TaskState.from_dict(json.loads(row["state_json"]))

    def has_task(self, task_id: str) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT 1 FROM task_state WHERE task_id=?", (task_id,)
            ).fetchone()
        return row is not None

    def put_task(self, state: TaskState, *, expected_version: int) -> TaskState:
        data = state.to_dict()
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT version FROM task_state WHERE task_id=?", (data["task_id"],)
            ).fetchone()
            if row is None:
                raise TaskStateNotFoundError(f"任务不存在: {data['task_id']}")
            if row["version"] != expected_version:
                raise OptimisticLockError(
                    f"任务 {data['task_id']} 版本冲突：库内 v{row['version']}，"
                    f"提交基线 v{expected_version}"
                )
            conn.execute(
                "UPDATE task_state SET version=?, status=?, updated_at=?, state_json=?"
                " WHERE task_id=?",
                (data["version"], data["status"], data["updated_at"],
                 json.dumps(data, ensure_ascii=False), data["task_id"]),
            )
        return state

    def list_tasks(self) -> list[str]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT task_id FROM task_state ORDER BY task_id").fetchall()
        return [r["task_id"] for r in rows]

    # -------------------------------------------------------- artifacts
    def save_artifact(self, record: ArtifactRecord) -> ArtifactRecord:
        data = record.to_dict()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO artifacts(artifact_id, task_id, status, record_json)"
                " VALUES(?,?,?,?)",
                (data["artifact_id"], data["created_by"]["task_id"], data["status"],
                 json.dumps(data, ensure_ascii=False)),
            )
        return record

    def get_artifact(self, artifact_id: str) -> ArtifactRecord:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT record_json FROM artifacts WHERE artifact_id=?", (artifact_id,)
            ).fetchone()
        if row is None:
            raise ArtifactRecordNotFoundError(f"Artifact 不存在: {artifact_id}")
        return ArtifactRecord.from_dict(json.loads(row["record_json"]))

    def list_artifacts(self, task_id: str) -> list[ArtifactRecord]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT record_json FROM artifacts WHERE task_id=? ORDER BY artifact_id",
                (task_id,),
            ).fetchall()
        return [ArtifactRecord.from_dict(json.loads(r["record_json"])) for r in rows]

    # ---------------------------------------------------------- memory
    def execute(self, sql: str, params: tuple = ()) -> list[dict]:
        """受控读写入口（SELECT 返回行；写语句提交事务；调用方负责 SQL 安全）。"""
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def execute_write(self, sql: str, params: tuple = ()) -> int:
        """受控写入入口（INSERT/UPDATE/DELETE），提交事务并返回受影响行数。"""
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(sql, params)
            return cursor.rowcount

    # ----------------------------------------------------- checkpoints
    def save_checkpoint(self, payload: dict) -> dict:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO checkpoints(checkpoint_id, task_id, created_at,"
                " payload_json) VALUES(?,?,?,?)",
                (payload["checkpoint_id"], payload["task_id"], payload["created_at"],
                 json.dumps(payload, ensure_ascii=False)),
            )
        return payload

    def get_checkpoint(self, checkpoint_id: str) -> dict:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT payload_json FROM checkpoints WHERE checkpoint_id=?", (checkpoint_id,)
            ).fetchone()
        if row is None:
            raise CheckpointNotFoundError(f"Checkpoint 不存在: {checkpoint_id}")
        return json.loads(row["payload_json"])

    def list_checkpoints(self, task_id: str) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT payload_json FROM checkpoints WHERE task_id=? ORDER BY created_at",
                (task_id,),
            ).fetchall()
        return [json.loads(r["payload_json"]) for r in rows]


def default_initial_state(
    task_id: str,
    *,
    status: str = "CREATED",
    current_stage: str = "INTAKE",
    plan: list | None = None,
    todos: list | None = None,
    budget: dict | None = None,
) -> dict:
    """构造合法初始 TaskState dict（task.created 事件载荷的 state 基线）。"""
    now = utc_now_iso()
    return {
        "task_id": task_id,
        "version": 1,
        "status": status,
        "current_stage": current_stage,
        "plan": list(plan or []),
        "todos": list(todos or []),
        "budget": dict(
            budget
            or {"token_max": 100000, "token_used": 0, "action_max": 100, "action_used": 0}
        ),
        "artifacts": [],
        "subtasks": None,
        "evidence_refs": [],
        "context_manifest_hash": "EMPTY",
        "updated_at": now,
    }
