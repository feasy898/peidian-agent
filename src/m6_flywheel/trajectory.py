# -*- coding: utf-8 -*-
"""m6_flywheel.trajectory · 轨迹导出（SPEC-M6-01）。

M2 事件流（``runtime/events/*.jsonl``，追加写唯一权威流）→ TrajectoryRecord
（01 §2.11）：四类步型（MODEL_CALL/TOOL_CALL/STATE_CHANGE/APPROVAL）全量导出，
与事件流**逐条对应**（第 i 步 ⇔ 第 i 条事件：``steps[i].ref == events[i].event_id``）。

- 事件 → 步型映射是**全函数**（28 个事件主题全覆盖，缺省 STATE_CHANGE）：
  - ``TOOL_CALL``    action.requested / action.policy_decided / action.executing /
                     action.completed；
  - ``APPROVAL``     action.waiting_approval / approval.requested / approval.granted /
                     approval.denied / approval.timeout；
  - ``MODEL_CALL``   budget.warning / budget.exhausted 且 ``payload.kind == "token"``
                     （M1 口径：事件目录无 model.* 主题，budget.warning{kind: token,
                     cost{…}} 兼作每轮模型调用成本上报通道——M1 CHANGELOG 偏差 2）；
  - ``STATE_CHANGE`` 其余全部（task.*/artifact.*/alarm.*/measurement.updated/
                     grid.event/budget.{action 类}/sim.*/price.period_changed/
                     demand.month_rolled/release.published 等）。
- 拒绝口径：事件缺 trace_id / trace_id 不一致 / 事件契约不合法 / outcome 与
  TaskState 终态不一致 → ``TrajectoryRejectedError``（轨迹 REJECTED，不落盘）。
- outcome.status 从任务生命周期事件推导（``task.created`` 初始 + 逐条
  ``task.status_changed{accepted != false}`` 折叠），与 M2 事件重建协议同口径；
  无生命周期事件 → ``UNKNOWN`` + 质量旗标 ``NO_TASK_LIFECYCLE``。
- 确定性纪律：不读任何真实时钟（latency/cost 取自事件 payload，缺省 0）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from contracts import EventType, TrajectoryRecord, TrajectoryStepType

__all__ = [
    "TrajectoryRejectedError",
    "EVENT_STEP_RULES",
    "step_type_of",
    "collect_events_for_trace",
    "derive_outcome_status",
    "TrajectoryExporter",
    "export_trajectory",
]

#: 事件主题 → 步型 显式映射（全函数：未列出者走 DEFAULT = STATE_CHANGE）
EVENT_STEP_RULES: dict[str, str] = {
    # TOOL_CALL：动作链（请求→策略→执行→完成）
    EventType.ACTION_REQUESTED.value: TrajectoryStepType.TOOL_CALL.value,
    EventType.ACTION_POLICY_DECIDED.value: TrajectoryStepType.TOOL_CALL.value,
    EventType.ACTION_EXECUTING.value: TrajectoryStepType.TOOL_CALL.value,
    EventType.ACTION_COMPLETED.value: TrajectoryStepType.TOOL_CALL.value,
    # APPROVAL：审批链（含进入等待审批）
    EventType.ACTION_WAITING_APPROVAL.value: TrajectoryStepType.APPROVAL.value,
    EventType.APPROVAL_REQUESTED.value: TrajectoryStepType.APPROVAL.value,
    EventType.APPROVAL_GRANTED.value: TrajectoryStepType.APPROVAL.value,
    EventType.APPROVAL_DENIED.value: TrajectoryStepType.APPROVAL.value,
    EventType.APPROVAL_TIMEOUT.value: TrajectoryStepType.APPROVAL.value,
    # MODEL_CALL：模型调用成本通道（payload.kind == token，见模块 docstring）
    EventType.BUDGET_WARNING.value: TrajectoryStepType.MODEL_CALL.value,
    EventType.BUDGET_EXHAUSTED.value: TrajectoryStepType.MODEL_CALL.value,
}

_DEFAULT_STEP_TYPE = TrajectoryStepType.STATE_CHANGE.value

#: 质量旗标（TrajectoryRecord.quality_flags；01 §2.11 示例 LATEX_STUCK/LOOP/…）
FLAG_NO_TASK_LIFECYCLE = "NO_TASK_LIFECYCLE"
FLAG_LOOP = "LOOP"
FLAG_EMPTY = "EMPTY_TRAJECTORY"

#: 连续重复步（type+ref+summary 全同）判定阈值
LOOP_REPEAT_THRESHOLD = 3

#: outcome.completion_level 推导表（终态越完整分越高，1-5）
_COMPLETION_LEVEL = {
    "COMPLETED": 5,
    "VERIFYING": 4,
    "RUNNING": 3,
    "WAITING_INPUT": 3,
    "WAITING_APPROVAL": 3,
    "WAITING_EVENT": 3,
    "PAUSED": 2,
    "CREATED": 1,
    "FAILED": 1,
    "CANCELLED": 1,
    "UNKNOWN": 1,
}

_TASK_CREATED = EventType.TASK_CREATED.value
_TASK_STATUS_CHANGED = EventType.TASK_STATUS_CHANGED.value


class TrajectoryRejectedError(ValueError):
    """轨迹导出被拒（SPEC-M6-01：缺 trace_id / 状态不一致 / 事件不合法）。"""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"轨迹 REJECTED[{reason}] {detail}" if detail
                         else f"轨迹 REJECTED[{reason}]")


def step_type_of(event: Mapping) -> str:
    """事件 → 四类步型之一（全函数；budget.* 按 payload.kind 细分）。"""
    etype = str(event.get("type") or "")
    mapped = EVENT_STEP_RULES.get(etype, _DEFAULT_STEP_TYPE)
    if mapped == TrajectoryStepType.MODEL_CALL.value:
        kind = str((event.get("payload") or {}).get("kind") or "")
        if kind and kind != "token":
            # action 类预算事件不是模型调用足迹 → 状态变更
            return _DEFAULT_STEP_TYPE
    return mapped


def collect_events_for_trace(events_dir: Path | str, trace_id: str) -> list[dict]:
    """扫描 ``*.jsonl`` 事件流，取同 trace 事件（多分片按 (文件名, 行序) 稳定排序）。"""
    base = Path(events_dir)
    records: list[tuple[str, int, dict]] = []
    for path in sorted(base.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise TrajectoryRejectedError(
                        "BAD_EVENT_STREAM", f"{path.name}:{line_no} JSON 解析失败: {exc}"
                    ) from exc
                if record.get("trace_id") == trace_id:
                    records.append((path.name, line_no, record))
    records.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in records]


def derive_outcome_status(events: Iterable[Mapping]) -> str:
    """任务终态推导：task.created 初始 + 逐条 task.status_changed 折叠（M2 同口径）。"""
    status = "UNKNOWN"
    for event in events:
        etype = str(event.get("type") or "")
        payload = event.get("payload") or {}
        if etype == _TASK_CREATED:
            state = payload.get("state") or {}
            status = str(state.get("status") or "CREATED")
        elif etype == _TASK_STATUS_CHANGED:
            if payload.get("accepted") is False:
                continue  # 非法迁移拒绝事件，不改变权威状态
            if payload.get("to"):
                status = str(payload["to"])
            elif isinstance(payload.get("state"), dict):
                status = str(payload["state"].get("status") or status)
    return status


def _summary_of(event: Mapping) -> str:
    payload = event.get("payload") or {}
    bits = []
    for key in ("from", "to", "decision", "status", "kind", "level", "rule", "quantity"):
        if key in payload:
            bits.append(f"{key}={payload[key]}")
    summary = " ".join(bits)
    return f"{event.get('type')} {event.get('subject')}".strip() + (f" {summary}" if summary else "")


def _detect_loop(steps: list[dict]) -> bool:
    same = 1
    for index in range(1, len(steps)):
        prev, curr = steps[index - 1], steps[index]
        if (prev["type"], prev["ref"], prev["summary"]) == (curr["type"], curr["ref"], curr["summary"]):
            same += 1
            if same >= LOOP_REPEAT_THRESHOLD:
                return True
        else:
            same = 1
    return False


class TrajectoryExporter:
    """轨迹导出器（01 §3.6 冻结 API ``export_trajectory(trace_id)`` 的载体）。

    ``events_dir``：M2 事件流目录（缺省仓库根 ``runtime/events/``）。
    ``sink``：导出成功/拒绝后的审计事件回写（EventLog.append 兼容 callable；
    主题 ``trajectory.exported``，拒绝时 payload 带 ``rejected: true``）。
    """

    def __init__(self, events_dir: Path | str | None = None,
                 sink: Callable[[dict], Any] | None = None) -> None:
        self.events_dir = Path(events_dir) if events_dir is not None else default_events_dir()
        self.sink = sink

    # -------------------------------------------------------------- 主入口
    def export_trajectory(self, trace_id: str, *, release_id: str = "sim",
                          task_state: Mapping | None = None,
                          events: list[Mapping] | None = None) -> TrajectoryRecord:
        """导出一条轨迹；任何拒绝口径触发 ``TrajectoryRejectedError``（轨迹 REJECTED）。"""
        if not trace_id:
            raise TrajectoryRejectedError("MISSING_TRACE_ID", "trace_id 为空")
        stream = list(events) if events is not None else collect_events_for_trace(
            self.events_dir, trace_id)
        if not stream:
            raise TrajectoryRejectedError("EMPTY_TRACE",
                                          f"事件流中无 trace_id={trace_id!r} 的事件")
        # 逐条校验：缺 trace_id / trace 不一致 / 事件契约不合法 → REJECTED
        for index, event in enumerate(stream):
            event_trace = event.get("trace_id")
            if not event_trace:
                raise TrajectoryRejectedError(
                    "MISSING_TRACE_ID",
                    f"events[{index}] ({event.get('event_id')}) 缺 trace_id")
            if event_trace != trace_id:
                raise TrajectoryRejectedError(
                    "TRACE_MISMATCH",
                    f"events[{index}] ({event.get('event_id')}) trace_id={event_trace!r}"
                    f" != {trace_id!r}")
            from contracts import ContractValidationError, EventRecord

            try:
                EventRecord.from_dict(dict(event))
            except ContractValidationError as exc:
                raise TrajectoryRejectedError(
                    "INVALID_EVENT", f"events[{index}] 契约校验失败: {exc}") from exc

        steps = [
            {
                "seq": index + 1,
                "type": step_type_of(event),
                "ref": str(event.get("event_id") or f"evt-{index + 1}"),
                "summary": _summary_of(event)[:200],
                "latency_ms": int((event.get("payload") or {}).get("latency_ms") or 0),
                "cost": ((event.get("payload") or {}).get("cost")
                         if step_type_of(event) == TrajectoryStepType.MODEL_CALL.value else 0),
            }
            for index, event in enumerate(stream)
        ]

        outcome_status = derive_outcome_status(stream)
        if task_state is not None:
            state_status = str(getattr(task_state, "status", None)
                               or (task_state.get("status") if isinstance(task_state, Mapping)
                                   else "") or "")
            if state_status and state_status != outcome_status:
                raise TrajectoryRejectedError(
                    "INCONSISTENT_OUTCOME",
                    f"outcome.status={outcome_status!r} 与 TaskState 终态 {state_status!r} 不一致")

        flags: list[str] = []
        if outcome_status == "UNKNOWN":
            flags.append(FLAG_NO_TASK_LIFECYCLE)
        if not steps:
            flags.append(FLAG_EMPTY)
        if _detect_loop(steps):
            flags.append(FLAG_LOOP)

        tokens = sum(int((step["cost"] or {}).get("tokens") or 0)
                     if isinstance(step["cost"], Mapping) else 0 for step in steps)
        record = TrajectoryRecord.from_dict({
            "trace_id": trace_id,
            "task_id": str((stream[0].get("subject") or "").removeprefix("task-")
                           or trace_id),
            "release_id": release_id,
            "steps": steps,
            "outcome": {
                "status": outcome_status,
                "evidence_summary": (
                    f"steps={len(steps)} "
                    + " ".join(f"{t}={sum(1 for s in steps if s['type'] == t)}"
                               for t in ("MODEL_CALL", "TOOL_CALL", "STATE_CHANGE", "APPROVAL"))),
                "completion_level": _COMPLETION_LEVEL.get(outcome_status, 1),
            },
            "cost_total": {"tokens": tokens, "currency": 0},
            "quality_flags": flags,
        })
        self._audit(trace_id, {"rejected": False, "steps": len(steps),
                               "outcome_status": outcome_status})
        return record

    def reject_and_audit(self, trace_id: str, reason: str, detail: str = "") -> None:
        """拒绝口径的审计回写（REJECTED 轨迹不产出 TrajectoryRecord）。"""
        self._audit(trace_id or "", {"rejected": True, "reason": reason, "detail": detail})

    def _audit(self, trace_id: str, payload: dict) -> None:
        if self.sink is None:
            return
        from m2_information.ids import new_ulid
        from m2_information.timestamps import utc_now_iso

        self.sink({
            "event_id": new_ulid(),
            "type": EventType.TRAJECTORY_EXPORTED.value,
            "subject": trace_id or "unknown-trace",
            "payload": payload,
            "occurred_at": utc_now_iso(),
            "trace_id": trace_id or "unknown-trace",
            "producer": "M6",
        })


def default_events_dir(repo_root: Path | str | None = None) -> Path:
    """缺省事件流目录：仓库根 ``runtime/events/``（pathlib 推断，不依赖 cwd）。"""
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    return root / "runtime" / "events"


def default_exporter(repo_root: Path | str | None = None) -> TrajectoryExporter:
    return TrajectoryExporter(events_dir=default_events_dir(repo_root))


def export_trajectory(trace_id: str, *, release_id: str = "sim",
                      task_state: Mapping | None = None,
                      events: list[Mapping] | None = None,
                      events_dir: Path | str | None = None,
                      sink: Callable[[dict], Any] | None = None) -> TrajectoryRecord:
    """01 §3.6 冻结 API：``export_trajectory(trace_id) -> TrajectoryRecord``。

    events_dir/events/sink 为注入点（EVAL 沙箱与运行期接线用；缺省读仓库
    ``runtime/events/`` 权威流）。
    """
    exporter = TrajectoryExporter(events_dir=events_dir, sink=sink)
    return exporter.export_trajectory(trace_id, release_id=release_id,
                                      task_state=task_state, events=events)
