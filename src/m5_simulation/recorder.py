# -*- coding: utf-8 -*-
"""m5_simulation.recorder · 三层证据采集（SPEC-M5-06）。

SimRunResult.evidence_pack 三件（01 §2.9 EvidenceKind）：

- ``INTERACTION_LOG``    用户模拟器输出逐条记录（persona/act/text/at）；
- ``STATE_TRANSITIONS``  环境状态迁移记录（设备状态/分合位/告警升降/负载覆盖）；
- ``TIMELINE``           四类时间对齐表——每行同时携带 BUSINESS 时刻（业务事件
                         标 BUSINESS 时刻，ADDENDUM §C 口径）、SIM_LOGICAL 秒、
                         MONOTONIC 毫秒与 WALL 时刻（后两列为审计列，
                         **不参与确定性 diff**，见 scenario.diff_runs）。

文件落 ``runtime/runs/<run_id>/``（git ignore 的运行期产物目录）；
``ref`` 为仓库根相对路径（SimRunResult.evidence_pack[].ref）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["RunRecorder", "AUDIT_COLUMNS", "strip_audit_columns"]

#: TIMELINE/轨迹行中的审计列（真实时间源或其派生测量；确定性比对时剔除）
AUDIT_COLUMNS = ("monotonic_ms", "wall_at", "latency_ms")

_EVIDENCE_FILES = {
    "INTERACTION_LOG": "interaction_log.jsonl",
    "STATE_TRANSITIONS": "state_transitions.jsonl",
    "TIMELINE": "timeline.jsonl",
}


def strip_audit_columns(row: dict) -> dict:
    """剔除审计列（确定性 diff 口径：BUSINESS/SIM 为判据列，MONOTONIC/WALL 为审计列）。"""
    if isinstance(row, dict):
        return {k: strip_audit_columns(v) for k, v in row.items() if k not in AUDIT_COLUMNS}
    if isinstance(row, list):
        return [strip_audit_columns(item) for item in row]
    return row


class RunRecorder:
    """单次 run 的三层证据采集器（每 run 独立目录，SPEC-M5-07 隔离）。"""

    def __init__(self, run_dir: Path, *, aligned_row_fn=None) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._aligned_row_fn = aligned_row_fn  # () -> 四时钟对齐行
        self.interactions: list[dict] = []
        self.state_transitions: list[dict] = []
        self.timeline: list[dict] = []
        self.trajectory_steps: list[dict] = []
        self._seq = 0

    # ------------------------------------------------ 行构造
    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _audit(self) -> dict:
        if self._aligned_row_fn is not None:
            return {k: v for k, v in self._aligned_row_fn().items() if k in AUDIT_COLUMNS}
        return {"monotonic_ms": None, "wall_at": None}

    # ------------------------------------------------ 三层证据
    def interaction(self, utterance: dict, sim_elapsed_s: float, business_at: str) -> dict:
        row = {
            "seq": self._next_seq(), "persona": utterance.get("persona"),
            "act": utterance.get("act"), "text": utterance.get("text"),
            "mode": utterance.get("mode", "script"),
            "degraded": bool(utterance.get("degraded", False)),
            "business_at": business_at, "sim_elapsed_s": sim_elapsed_s,
            **self._audit(),
        }
        self.interactions.append(row)
        self.timeline_row("INTERACTION", f"{row['persona']}:{row['act']} {row['text'] or ''}",
                          sim_elapsed_s, business_at)
        return row

    def state_transition(self, subject: str, field: str, from_value: Any, to_value: Any,
                         sim_elapsed_s: float, business_at: str, *, reason: str = "") -> dict:
        row = {
            "seq": self._next_seq(), "subject": subject, "field": field,
            "from": from_value, "to": to_value, "reason": reason,
            "business_at": business_at, "sim_elapsed_s": sim_elapsed_s,
            **self._audit(),
        }
        self.state_transitions.append(row)
        return row

    def timeline_row(self, kind: str, summary: str, sim_elapsed_s: float,
                     business_at: str, *, payload: dict | None = None) -> dict:
        row = {
            "seq": self._next_seq(), "kind": kind, "summary": summary,
            "business_at": business_at, "sim_elapsed_s": sim_elapsed_s,
            **self._audit(),
        }
        if payload:
            row["payload"] = payload
        self.timeline.append(row)
        return row

    # ------------------------------------------------ 轨迹（M6 采集口径）
    def trajectory_step(self, step_type: str, ref: str, summary: str, *,
                        latency_ms: int = 0, cost: Any = 0) -> dict:
        step = {
            "seq": len(self.trajectory_steps) + 1, "type": step_type, "ref": ref,
            "summary": summary, "latency_ms": int(latency_ms), "cost": cost,
        }
        self.trajectory_steps.append(step)
        return step

    # ------------------------------------------------ 落盘
    def finalize(self, *, trace_id: str, task_id: str, release_id: str = "sim",
                 outcome: dict | None = None, quality_flags: list | None = None,
                 cost_total: dict | None = None) -> dict:
        """写三层证据 + 轨迹文件；返回 {evidence_pack, traj_ref, trajectory}。"""
        refs: list[dict] = []
        layers = {
            "INTERACTION_LOG": self.interactions,
            "STATE_TRANSITIONS": self.state_transitions,
            "TIMELINE": self.timeline,
        }
        for kind in ("INTERACTION_LOG", "STATE_TRANSITIONS", "TIMELINE"):
            path = self.run_dir / _EVIDENCE_FILES[kind]
            with path.open("w", encoding="utf-8") as handle:
                for row in layers[kind]:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            refs.append({"kind": kind, "ref": path.as_posix()})

        trajectory = {
            "trace_id": trace_id, "task_id": task_id, "release_id": release_id,
            "steps": self.trajectory_steps,
            "outcome": outcome or {"status": "COMPLETED",
                                   "evidence_summary": f"三层证据 {len(self.timeline)} 行时间线",
                                   "completion_level": 3},
            "cost_total": cost_total or {"tokens": 0, "currency": 0},
            "quality_flags": list(quality_flags or []),
        }
        traj_path = self.run_dir / "trajectory.json"
        traj_path.write_text(json.dumps(trajectory, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        return {"evidence_pack": refs, "traj_ref": traj_path.as_posix(),
                "trajectory": trajectory}
