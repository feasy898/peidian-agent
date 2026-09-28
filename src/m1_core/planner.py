# -*- coding: utf-8 -*-
"""m1_core.planner · 计划结构管理（plan 结构 = 01 §2.3）。

TaskState.plan 为 PlanStep 列表（``{stage, gate, artifacts_expected}``），
TaskState.todos 为 Todo 列表（``{id, text, status}``）。本模块提供：

- 阶段导航：当前阶段定位 / 下一阶段 / 最终阶段（SPEC-M1-09 恢复语义的依据）；
- Todo 管理：DONE 粘滞（已 DONE 不重开，幂等续跑）、gap 项构造与幂等注入
  （SPEC-M1-04：门禁缺口写入 todos）；
- 模型 todo 提议的受控应用（只能更新既有项或追加新项，不能篡改 DONE）。

全部函数纯数据操作（无 IO/无时钟），供 loop/gates/completion 复用。
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

__all__ = [
    "plan_steps",
    "stage_step",
    "stage_index",
    "final_step",
    "next_stage",
    "is_final_stage",
    "todo_by_id",
    "todo_status",
    "pending_todos",
    "apply_todo_updates",
    "gap_todo",
    "build_gap_todos",
    "merge_gap_todos",
    "sanitize_stage_slug",
]


# ---------------------------------------------------------------- 阶段导航
def plan_steps(state: Any) -> list[dict]:
    """TaskState.plan → dict 列表（兼容 dataclass/契约结构）。"""
    steps = []
    for step in getattr(state, "plan", None) or []:
        if isinstance(step, Mapping):
            steps.append({
                "stage": str(step.get("stage", "")),
                "gate": str(step.get("gate", "")),
                "artifacts_expected": [str(a) for a in step.get("artifacts_expected") or []],
            })
        else:  # contracts.PlanStep
            steps.append({
                "stage": str(step.stage),
                "gate": str(step.gate),
                "artifacts_expected": [str(a) for a in step.artifacts_expected],
            })
    return steps


def stage_step(state: Any, stage: str) -> dict | None:
    """定位 stage 的 plan 步（无则 None）。"""
    for step in plan_steps(state):
        if step["stage"] == str(stage):
            return step
    return None


def stage_index(state: Any, stage: str) -> int:
    """stage 在 plan 中的序号（0 基；不在 plan 返回 -1）。"""
    for index, step in enumerate(plan_steps(state)):
        if step["stage"] == str(stage):
            return index
    return -1


def final_step(state: Any) -> dict | None:
    """最终阶段步（plan 为空返回 None）。"""
    steps = plan_steps(state)
    return steps[-1] if steps else None


def next_stage(state: Any) -> str | None:
    """当前阶段的下一阶段（最终阶段返回 None）。"""
    steps = plan_steps(state)
    current = str(getattr(state, "current_stage", "") or "")
    for index, step in enumerate(steps):
        if step["stage"] == current:
            if index + 1 < len(steps):
                return steps[index + 1]["stage"]
            return None
    # 当前阶段不在 plan（如空 plan）：从第一阶段起
    return steps[0]["stage"] if steps else None


def is_final_stage(state: Any) -> bool:
    """当前阶段是否 plan 最终阶段（空 plan 视为最终）。"""
    final = final_step(state)
    if final is None:
        return True
    return str(getattr(state, "current_stage", "") or "") == final["stage"]


# ---------------------------------------------------------------- Todo 管理
def _todo_dict(todo: Any) -> dict:
    if isinstance(todo, Mapping):
        return {
            "id": str(todo.get("id", "")),
            "text": str(todo.get("text", "")),
            "status": str(todo.get("status", "PENDING")),
        }
    return {"id": str(todo.id), "text": str(todo.text),
            "status": str(todo.status.value if hasattr(todo.status, "value") else todo.status)}


def todos_of(state: Any) -> list[dict]:
    return [_todo_dict(t) for t in getattr(state, "todos", None) or []]


def todo_by_id(state: Any, todo_id: str) -> dict | None:
    for todo in todos_of(state):
        if todo["id"] == str(todo_id):
            return todo
    return None


def todo_status(state: Any, todo_id: str) -> str | None:
    todo = todo_by_id(state, todo_id)
    return None if todo is None else todo["status"]


def pending_todos(state: Any) -> list[dict]:
    """未完成 todos（DONE 不含——幂等续跑只驱动剩余项）。"""
    return [t for t in todos_of(state) if t["status"] != "DONE"]


def apply_todo_updates(state: Any, updates: Iterable[Mapping] | None) -> tuple[list[dict], list[str]]:
    """应用模型 todo 提议，返回 (新 todos 列表, 被忽略项说明)（不修改原状态）。

    规则：
    - 只允许 PENDING/IN_PROGRESS/DONE 三态；
    - **DONE 粘滞**：已 DONE 的项不可回退（SPEC-M1-09 幂等续跑）；
    - 既有项按 id 更新 status；未知 id 且带 text 的提议追加为新项；
    - 未知 id 且无 text 的提议忽略（说明进 ignored）。
    """
    todos = todos_of(state)
    index = {t["id"]: i for i, t in enumerate(todos)}
    ignored: list[str] = []
    for update in updates or []:
        if not isinstance(update, Mapping):
            continue
        todo_id = str(update.get("id", ""))
        status = str(update.get("status", "PENDING"))
        if not todo_id or status not in ("PENDING", "IN_PROGRESS", "DONE"):
            ignored.append(todo_id or "<空id>")
            continue
        if todo_id in index:
            current = todos[index[todo_id]]
            if current["status"] == "DONE" and status != "DONE":
                ignored.append(f"{todo_id}(DONE 粘滞)")
                continue
            todos[index[todo_id]] = {**current, "status": status}
        elif update.get("text"):
            todos.append({"id": todo_id, "text": str(update["text"]), "status": status})
        else:
            ignored.append(f"{todo_id}(未知且无 text)")
    return todos, ignored


# ---------------------------------------------------------------- Gap todos
_STAGE_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_stage_slug(stage: str) -> str:
    """阶段名 → gap todo id 安全片段。"""
    return _STAGE_SLUG_RE.sub("-", str(stage)).strip("-") or "stage"


def gap_todo(stage: str, ref: str, reason: str) -> dict:
    """构造一个门禁缺口 todo（id 确定性：gap-<stage>-<n>，幂等注入不重复）。"""
    return {
        "id": f"gap-{sanitize_stage_slug(stage)}-{_ref_slug(ref)}",
        "text": f"阶段门禁缺口：{stage} 需要产物 {ref}（{reason}）",
        "status": "PENDING",
    }


def _ref_slug(ref: str) -> str:
    return sanitize_stage_slug(str(ref).rsplit("@", 1)[0]).lower() or "item"


def build_gap_todos(stage: str, missing: Iterable[Mapping],
                    extra_reasons: Iterable[str] = ()) -> list[dict]:
    """由门禁缺口清单构造 gap todos（产物缺口 + 阻断原因）。"""
    todos = [
        gap_todo(stage, str(item.get("ref", "")), str(item.get("reason", "")))
        for item in missing
    ]
    for reason in extra_reasons:
        if not reason:
            continue
        todos.append({
            "id": f"gap-{sanitize_stage_slug(stage)}-{len(todos) + 1}",
            "text": f"阶段门禁缺口：{stage}（{reason}）",
            "status": "PENDING",
        })
    return todos


def merge_gap_todos(state: Any, gaps: Iterable[Mapping]) -> list[dict]:
    """幂等合并 gap todos（同 id 已存在则保留既有项，不重复注入）。"""
    todos = todos_of(state)
    known = {t["id"] for t in todos}
    for gap in gaps:
        if str(gap.get("id")) not in known:
            todos.append(_todo_dict(gap))
            known.add(str(gap.get("id")))
    return todos
