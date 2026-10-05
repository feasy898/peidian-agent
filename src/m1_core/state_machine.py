# -*- coding: utf-8 -*-
"""m1_core.state_machine · 任务状态机迁移守卫（specs/M1-agent-core.md SPEC-M1-02）。

迁移表 = specs/01-contracts.md §5.1 的机械转写，**硬编码（TASK_TRANSITIONS）+
表驱动文件（tests/fixtures/frozen_state_machines.yaml machines.task）双写**；
``table_diff`` 断言两侧 diff 为空（M1 DoD：迁移表与 01§5.1 完全一致）。

守卫语义（SPEC-M1-02 / 01 §5.1）：
- 所有迁移走本表；非法迁移抛 :class:`IllegalTransitionError`；
- 任务保持原状态（守卫在提交之前拦截，权威状态不动）；
- 落 ``task.status_changed`` 拒绝事件：``payload.rejected = true``（并携带
  ``accepted = false`` 以兼容 M2 事件重建协议——重建时跳过 accepted=false 事件）；
- 终态 COMPLETED 只能经完成判定（SPEC-M1-06）：无已接受 CompletionClaim 的
  COMPLETED 迁移抛 :class:`CompletionRequiredError`（IllegalTransitionError 子类）。

权威状态外置 M2（01 §2.3）：合法迁移委托 ``commit_state``（版本+1、事件落盘）；
本模块不持有任何任务数据。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

__all__ = [
    "TASK_TRANSITIONS",
    "TASK_STATES",
    "TERMINAL_STATUSES",
    "IllegalTransitionError",
    "CompletionRequiredError",
    "transition_allowed",
    "assert_legal",
    "load_frozen_table",
    "table_diff",
    "assert_table_consistency",
    "rejection_payload",
    "TaskStateMachine",
]

# ---------------------------------------------------------------- 01 §5.1
#: 任务状态机迁移表（硬编码侧；与 tests/fixtures/frozen_state_machines.yaml
#: machines.task 必须逐键逐值一致——table_diff 为空）
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

TASK_STATES: tuple[str, ...] = tuple(TASK_TRANSITIONS)

#: 终态（只读）
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"COMPLETED", "FAILED", "CANCELLED"}
)

#: 冻结基准表（表驱动文件侧）缺省位置
FROZEN_TABLE_REL = "tests/fixtures/frozen_state_machines.yaml"


class IllegalTransitionError(ValueError):
    """非法任务状态迁移（01 §5.1：抛错 + 任务保持原状态 + 落拒绝事件）。"""

    def __init__(self, from_status: str, to_status: str, machine: str = "task") -> None:
        self.from_status = from_status
        self.to_status = to_status
        self.machine = machine
        allowed = TASK_TRANSITIONS.get(from_status, [])
        super().__init__(
            f"[{machine}] 非法迁移 {from_status}→{to_status}"
            f"（{from_status} 仅允许 → {'/'.join(allowed) or '（终态只读）'}）"
        )


class CompletionRequiredError(IllegalTransitionError):
    """无已接受 CompletionClaim 的 COMPLETED 迁移（SPEC-M1-06：申请与判定分离）。"""

    def __init__(self, from_status: str) -> None:
        message = (
            "终态 COMPLETED 必须经完成判定（request_completion 且 verdict=ACCEPTED），"
            f"任务 {from_status} 无已接受的 CompletionClaim"
        )
        super().__init__(from_status, "COMPLETED")
        self.message = message
        # 重写异常文本（保留 IllegalTransitionError 类型语义）
        self.args = (f"[task] {message}",)


def transition_allowed(from_status: str, to_status: str) -> bool:
    """迁移是否在 01 §5.1 表内。"""
    return to_status in TASK_TRANSITIONS.get(from_status, [])


def assert_legal(from_status: str, to_status: str) -> None:
    """断言迁移合法；非法抛 IllegalTransitionError（任务保持原状态）。"""
    if not transition_allowed(from_status, to_status):
        raise IllegalTransitionError(from_status, to_status)


# ---------------------------------------------------------------- 双写校验
def load_frozen_table(path: Path | str) -> dict[str, list[str]]:
    """读表驱动文件（frozen_state_machines.yaml）的 task 机迁移表。"""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    machines = data.get("machines") or {}
    table = machines.get("task")
    if not isinstance(table, dict) or not table:
        raise ValueError(f"冻结基准文件缺 machines.task 迁移表: {path}")
    return {str(k): [str(v) for v in vs] for k, vs in table.items()}


def table_diff(code_table: Mapping[str, list] | None = None,
               file_table: Mapping[str, list] | None = None,
               *, frozen_path: Path | str | None = None) -> dict[str, dict]:
    """硬编码表 vs 表驱动文件的 diff（空 dict = 完全一致）。

    任一侧缺省时从缺省来源取（code=TASK_TRANSITIONS，file=冻结基准文件）。
    """
    code = dict(TASK_TRANSITIONS if code_table is None else code_table)
    if file_table is None:
        file_table = load_frozen_table(
            frozen_path if frozen_path is not None else _default_frozen_path()
        )
    file = {str(k): list(v) for k, v in file_table.items()}
    diff: dict[str, dict] = {}
    for key in sorted(set(code) | set(file)):
        left, right = code.get(key), file.get(key)
        if left is None:
            diff[key] = {"only_in": "file", "file": right}
        elif right is None:
            diff[key] = {"only_in": "code", "code": left}
        elif list(left) != list(right):
            diff[key] = {"code": list(left), "file": list(right)}
    return diff


def assert_table_consistency(*, frozen_path: Path | str | None = None) -> dict:
    """双写一致性断言：diff 非空抛 ValueError（供 EVAL 与装配期调用）。"""
    diff = table_diff(frozen_path=frozen_path)
    if diff:
        raise ValueError(f"任务状态机迁移表双写不一致（01 §5.1）: {diff}")
    return {"states": len(TASK_TRANSITIONS), "diff": diff,
            "frozen_table": str(frozen_path or FROZEN_TABLE_REL)}


def _default_frozen_path() -> Path:
    """冻结基准文件缺省位置（仓库根/tests/fixtures/…，自本文件向上推断）。"""
    return Path(__file__).resolve().parents[2] / FROZEN_TABLE_REL


def rejection_payload(from_status: str, to_status: str, reason: str) -> dict:
    """拒绝事件 payload（SPEC-M1-02：rejected=true；accepted=false 兼容 M2 重建）。"""
    return {
        "from": from_status,
        "to": to_status,
        "rejected": True,
        "accepted": False,
        "reason": reason,
    }


class TaskStateMachine:
    """10 态迁移守卫（权威状态委托 M2 commit_state；本机不持有数据）。

    依赖注入（全部可测、无全局态）：
    - ``get_task(task_id) -> TaskState``：权威状态读取（M2）；
    - ``commit(task_id, mutation) -> TaskState``：权威状态提交（M2，版本+1）；
    - ``emit(task_id, event_type, payload, trace_id) -> None``：事件落流（M2 流）；
    - ``is_completable(task_id) -> bool``：COMPLETED 门禁（完成判定登记表）。
    """

    def __init__(
        self,
        *,
        get_task: Callable[[str], Any],
        commit: Callable[[str, dict], Any],
        emit: Callable[[str, str, dict, str], None],
        is_completable: Callable[[str], bool] | None = None,
    ) -> None:
        self.get_task = get_task
        self.commit = commit
        self.emit = emit
        self.is_completable = is_completable or (lambda _task_id: False)

    def transition(self, task_id: str, to_status: str, *,
                   mutation: dict | None = None, trace_id: str = "",
                   reason: str = "") -> Any:
        """守卫迁移：非法→拒绝事件+抛错（任务保持原状态）；合法→委托提交。"""
        state = self.get_task(task_id)
        current = state.status.value
        if to_status == current:
            # 非状态字段提交（todos/plan/budget 等）：不构成状态迁移
            return self.commit(task_id, dict(mutation or {}))
        if not transition_allowed(current, to_status):
            self.emit(task_id, "task.status_changed",
                      rejection_payload(current, to_status,
                                        reason or f"非法迁移（01 §5.1）：{current}→{to_status}"),
                      trace_id or f"task-{task_id}")
            raise IllegalTransitionError(current, to_status)
        if to_status == "COMPLETED" and not self.is_completable(task_id):
            message = CompletionRequiredError(current).message
            self.emit(task_id, "task.status_changed",
                      rejection_payload(current, to_status, message),
                      trace_id or f"task-{task_id}")
            raise CompletionRequiredError(current)
        payload = dict(mutation or {})
        payload["status"] = to_status
        return self.commit(task_id, payload)
