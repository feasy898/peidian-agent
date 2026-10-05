# -*- coding: utf-8 -*-
"""m1_core.trace · Loop 轮次/阶段日志与回放校验（SPEC-M1-01）。

事件目录（01 §4）是冻结封闭集，无 loop 阶段主题——五阶段序的回放数据源是本
模块的追加写日志 ``runtime/m1_core/loop/task-<id>.jsonl``（每行一条阶段记录；
与 M3 幂等 journal 同类的 M1 运行期审计件，非权威状态——权威状态外置 M2）。

回放校验（validate_replay）：每轮阶段序必须是
``PREPARE → MODEL → ACT → OBSERVE → VERIFY`` 的**前缀**：
- 完整轮 = 5 阶段；仅 PREPARE = 预算中断轮（合法，SPEC-M1-01 后半）；
- MODEL 先于 PREPARE / 跳阶段（如 PREPARE→ACT）/ 同阶段重复 → 违规；
- turn 序号必须严格递增（不可回退/复用）；seq 全局递增。

"EVAL-M1-01-N：构造 Model 先于 Prepare 的事件序"由本校验器拒绝——
违规序在真实运行中不存在、注入的伪序必被拒。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .ids import new_seq_id

__all__ = ["PHASE_ORDER", "LoopTrace", "validate_replay", "trace_path"]

#: 五阶段固定序（SPEC-M1-01）
PHASE_ORDER: tuple[str, ...] = ("PREPARE", "MODEL", "ACT", "OBSERVE", "VERIFY")

_PREPARE = PHASE_ORDER[0]


def trace_path(journal_dir: Path | str, task_id: str) -> Path:
    """日志文件路径（<journal_dir>/task-<task_id>.jsonl，流名净化）。"""
    safe = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in str(task_id))
    return Path(journal_dir) / f"task-{safe or 'default'}.jsonl"


class LoopTrace:
    """追加写阶段日志（每任务一个文件；M1 运行期审计件）。"""

    def __init__(self, journal_dir: Path | str, task_id: str) -> None:
        self.journal_dir = Path(journal_dir)
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.task_id = str(task_id)
        self.path = trace_path(self.journal_dir, task_id)

    def append(self, *, turn: int, phase: str, at: str, trace_id: str = "",
               summary: str = "", data: Mapping | None = None) -> dict:
        """追加一条阶段记录（seq 取既有行数，确定性递增）。"""
        entry = {
            "seq": self._next_seq(),
            "task_id": self.task_id,
            "turn": int(turn),
            "phase": str(phase),
            "at": str(at),
            "trace_id": str(trace_id or f"task-{self.task_id}"),
            "summary": str(summary),
            "data": dict(data or {}),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def entries(self) -> list[dict]:
        if not self.path.is_file():
            return []
        rows: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows

    def turns(self) -> dict[int, list[dict]]:
        """按轮分组的阶段记录（保序）。"""
        grouped: dict[int, list[dict]] = {}
        for entry in self.entries():
            grouped.setdefault(int(entry["turn"]), []).append(entry)
        return grouped

    def last_turn(self) -> int:
        """最大轮号（无记录返回 0——续跑从 1 起编）。"""
        entries = self.entries()
        return max((int(e["turn"]) for e in entries), default=0)

    def _next_seq(self) -> int:
        return len(self.entries()) + 1


def validate_replay(entries: Iterable[Mapping]) -> dict:
    """回放校验（纯函数）：返回 {valid, violations, turns, complete_turns,
    aborted_prepare_turns}。

    规则见模块 docstring；violations 为中文违规说明列表（空=通过）。
    """
    rows = [dict(e) for e in entries]
    violations: list[str] = []
    turns: dict[int, list[str]] = {}

    last_seq = 0
    for index, entry in enumerate(rows):
        seq = entry.get("seq")
        if not isinstance(seq, int) or seq <= last_seq:
            violations.append(
                f"记录[{index}] seq 非递增: {seq!r}（上一条 {last_seq}）")
        else:
            last_seq = seq
        phase = str(entry.get("phase", ""))
        if phase not in PHASE_ORDER:
            violations.append(
                f"记录[{index}] 未知阶段 {phase!r}（允许: {'/'.join(PHASE_ORDER)}）")
        turns.setdefault(int(entry.get("turn", 0)), []).append(phase)

    expected_turn = None
    complete_turns = 0
    aborted_prepare_turns = 0
    turn_reports: dict[int, dict] = {}
    for turn in sorted(turns):
        phases = turns[turn]
        if expected_turn is not None and turn <= expected_turn:
            violations.append(f"轮号未严格递增: {turn}（此前 {expected_turn}）")
        expected_turn = turn
        # 阶段序必须是 PHASE_ORDER 的前缀
        prefix_ok = len(phases) <= len(PHASE_ORDER) and all(
            phases[i] == PHASE_ORDER[i] for i in range(len(phases))
        )
        if not prefix_ok:
            violations.append(
                f"第 {turn} 轮阶段序 {phases} 不是 {'/'.join(PHASE_ORDER)} 的前缀"
                "（乱序/跳阶段/重复）")
        if len(set(phases)) != len(phases):
            violations.append(f"第 {turn} 轮存在重复阶段: {phases}")
        if not phases or phases[0] != _PREPARE:
            violations.append(f"第 {turn} 轮未从 PREPARE 起始: {phases}")
        if phases == list(PHASE_ORDER):
            complete_turns += 1
        elif phases == [_PREPARE]:
            aborted_prepare_turns += 1
        turn_reports[turn] = {
            "phases": phases,
            "complete": phases == list(PHASE_ORDER),
            "aborted_prepare": phases == [_PREPARE],
            "model_without_prepare": "MODEL" in phases and phases[0] != _PREPARE,
        }

    return {
        "valid": not violations,
        "violations": violations,
        "turns": turn_reports,
        "complete_turns": complete_turns,
        "aborted_prepare_turns": aborted_prepare_turns,
        "entries": len(rows),
    }


def new_turn_id() -> str:  # pragma: no cover - 预留（轨迹导出用）
    return new_seq_id("turn")
