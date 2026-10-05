# -*- coding: utf-8 -*-
"""m2_information.compactor · 上下文压缩四步（Commit → Compact → Rebuild → Validate）。

specs/M2-information.md SPEC-M2-05：

- Compact 前必须 Commit：五要素（goal 目标 / confirmed_facts 已确认事实 /
  external_side_effects 外部副作用 / acceptance_gaps 验收缺口 /
  recovery_position 恢复位置）落 ``workspace/state/``；
- Compact 产出摘要并落 ``state/compacted-<turn>.yaml``（context_builder 的
  COMPACTED_HISTORY 源）；
- Rebuild 从摘要重建上下文片段；Validate 检查五要素齐全，缺任一 = 失败回滚
  （删除压缩产物，任务状态与版本不变，抛 CompactValidationError）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import yaml

from .context_builder import estimate_tokens
from .timestamps import utc_now_iso

__all__ = [
    "Compactor",
    "CompactValidationError",
    "FIVE_ELEMENTS",
    "ELEMENT_NAMES_CN",
]

FIVE_ELEMENTS = (
    "goal", "confirmed_facts", "external_side_effects", "acceptance_gaps",
    "recovery_position",
)
ELEMENT_NAMES_CN = {
    "goal": "目标",
    "confirmed_facts": "已确认事实",
    "external_side_effects": "外部副作用",
    "acceptance_gaps": "验收缺口",
    "recovery_position": "恢复位置",
}


class CompactValidationError(RuntimeError):
    """Rebuild 后五要素不齐 → 失败回滚。"""

    def __init__(self, missing: list[str], message: str) -> None:
        super().__init__(message)
        self.missing = missing


class Compactor:
    """压缩四步执行器（依赖注入，与 ContextBuilder 同一 workspace 体系）。"""

    def __init__(
        self,
        *,
        state_reader: Callable[[str], Any],
        workspace_of: Callable[[str], Any],
        event_log,
        artifact_lister: Callable[[str], list] | None = None,
        commit_fn: Callable[[str, dict], Any] | None = None,
        now_fn: Callable[[], str] = utc_now_iso,
    ) -> None:
        self.state_reader = state_reader
        self.workspace_of = workspace_of
        self.event_log = event_log
        self.artifact_lister = artifact_lister or (lambda task_id: [])
        self.commit_fn = commit_fn
        self._now = now_fn

    # ================================================================ 1 Commit
    def extract_commit(self, task_id: str, turn: int) -> dict:
        """从权威状态与事件流提取五要素（确定性，无模型调用）。"""
        state = self.state_reader(task_id)
        events = self.event_log.events_for_task(task_id)

        goal = ""
        for event in events:
            if event.get("type") == "task.created":
                goal = str((event.get("payload") or {}).get("user_input") or "")
                break
        confirmed: list[str] = []
        side_effects: list[dict] = []
        for event in events:
            if event.get("type") != "action.completed":
                continue
            payload = event.get("payload") or {}
            if payload.get("status") == "SUCCEEDED":
                confirmed.append(
                    f"{payload.get('capability', '?')} → {payload.get('observation', '')}"
                )
            for ref in payload.get("result_refs") or []:
                side_effects.append({"kind": "result_ref", "ref": ref})
        for record in self.artifact_lister(task_id):
            status = record.status.value if hasattr(record, "status") else str(record.get("status"))
            if status in ("READY", "PUBLISHED", "ARCHIVED"):
                side_effects.append({"kind": "artifact", "artifact_id": record.artifact_id,
                                     "status": status})

        expected: list[str] = []
        for step in state.plan:
            for want in step.artifacts_expected:
                if want not in expected:
                    expected.append(want)
        produced = {record.schema_id for record in self.artifact_lister(task_id)}
        missing_artifacts = [item for item in expected if item not in produced]
        open_todos = [t.id for t in state.todos if t.status.value != "DONE"]
        gaps = [f"预期产物未产出: {item}" for item in missing_artifacts] + \
               [f"待办未完成: {item}" for item in open_todos]

        return {
            "task_id": task_id,
            "turn": int(turn),
            "committed_at": self._now(),
            "goal": goal or f"（任务 {task_id}：目标未在 task.created 声明）",
            # 空要素以占位句落盘：要素"在场"与要素"取值为空"是两回事（Validate 口径）
            "confirmed_facts": confirmed or ["（截至压缩点无已确认事实）"],
            "external_side_effects": side_effects or ["（截至压缩点无外部副作用）"],
            "acceptance_gaps": gaps or ["（当前无验收缺口：预期产物齐备且待办全部完成）"],
            "recovery_position": {
                "stage": state.current_stage,
                "turn": int(turn),
                "version": state.version,
                "status": state.status.value,
                "next_hint": open_todos[0] if open_todos else (state.plan[-1].stage
                                                              if state.plan else ""),
            },
        }

    def commit(self, task_id: str, turn: int, *, trace_id: str = "") -> str:
        """五要素落盘 ``state/compact-<turn>.yaml``；返回相对路径。"""
        record = self.extract_commit(task_id, turn)
        ws = self.workspace_of(task_id)
        rel = f"state/compact-{int(turn)}.yaml"
        ws.write(rel, yaml.safe_dump(record, allow_unicode=True, sort_keys=True))
        return rel

    # ================================================================ 2-4
    def compact(
        self,
        task_id: str,
        turn: int,
        *,
        trace_id: str = "",
        summarizer: Callable[[dict], dict] | None = None,
    ) -> dict:
        """Compact→Rebuild→Validate（Commit 在内部先执行）。

        ``summarizer``：可注入的摘要器（默认确定性五要素摘要）；返回须含全部
        五要素键（值非空），否则 Validate 失败回滚。
        """
        commit_rel = self.commit(task_id, turn, trace_id=trace_id)
        ws = self.workspace_of(task_id)
        commit_record = yaml.safe_load(ws.read(commit_rel))
        summary = (summarizer or default_summarizer)(commit_record)

        compact_rel = f"state/compacted-{int(turn)}.yaml"
        rebuilt = self.rebuild(summary)
        try:
            self.validate(rebuilt)
        except CompactValidationError as exc:
            # 失败回滚：压缩产物尚未写出；删除本次 Commit 产物，任务状态不变
            # （本流程未提交任何 mutation，TaskState 版本与状态均不变）
            ws.delete(commit_rel)
            raise CompactValidationError(
                exc.missing,
                f"压缩回滚：Rebuild 缺五要素 {exc.missing}（turn={turn}），"
                f"Commit 产物已删除，任务状态不变",
            ) from exc

        context_text = rebuilt["context_text"]
        payload = {
            "task_id": task_id,
            "turn": int(turn),
            "trace_id": trace_id,
            "elements": {name: summary.get(name) for name in FIVE_ELEMENTS},
            "context_text": context_text,
            "tokens": estimate_tokens(context_text),
        }
        ws.write(compact_rel, yaml.safe_dump(payload, allow_unicode=True, sort_keys=True))
        if self.commit_fn is not None:
            # 成功才提交（version+1；from==to 的状态提交事件，见 tests/CHANGELOG.md）
            self.commit_fn(task_id, {
                "compact_ref": compact_rel,
                "note": f"compact@turn={turn}",
            })
        return {"commit_ref": commit_rel, "compact_ref": compact_rel,
                "rebuilt": rebuilt, "tokens": payload["tokens"], "rollback": False}

    # ================================================================ 3 Rebuild
    def rebuild(self, summary: dict) -> dict:
        """从摘要重建上下文片段（五要素分节文本 + 元数据）。"""
        sections = []
        for name in FIVE_ELEMENTS:
            value = summary.get(name)
            sections.append((name, value))
        text_parts = ["【压缩历史】"]
        for name, value in sections:
            if isinstance(value, (list, dict)):
                rendered = yaml.safe_dump(value, allow_unicode=True, sort_keys=True).strip()
            else:
                rendered = str(value or "").strip()
            text_parts.append(f"[{ELEMENT_NAMES_CN[name]}｜{name}]")
            text_parts.append(rendered if rendered else "（缺）")
        return {
            "context_text": "\n".join(text_parts),
            "elements": {name: summary.get(name) for name in FIVE_ELEMENTS},
            "tokens": estimate_tokens("\n".join(text_parts)),
        }

    # ================================================================ 4 Validate
    @staticmethod
    def validate(rebuilt: dict) -> list[str]:
        """五要素齐全性校验：缺任一抛 CompactValidationError（= 失败回滚）。"""
        missing: list[str] = []
        for name in FIVE_ELEMENTS:
            value = (rebuilt.get("elements") or {}).get(name)
            if value is None:
                missing.append(name)
            elif isinstance(value, (list, dict, str)) and not value:
                missing.append(name)
        text = str(rebuilt.get("context_text") or "")
        for name in FIVE_ELEMENTS:
            if name not in text and ELEMENT_NAMES_CN[name] not in text:
                if name not in missing:
                    missing.append(name)
        if missing:
            seen: list[str] = []
            for name in missing:
                if name not in seen:
                    seen.append(name)
            raise CompactValidationError(
                seen,
                f"Rebuild 上下文缺五要素: {seen}（缺任一=失败回滚）",
            )
        return []

    # ---------------------------------------------------------------- 读
    def load_compacted(self, task_id: str, *, upto_turn: int | None = None) -> dict | None:
        """读最近一次（turn ≤ upto_turn）压缩记录；无则 None。"""
        ws = self.workspace_of(task_id)
        state_dir: Path = ws.sub("state")
        if not state_dir.is_dir():
            return None
        best: tuple[int, Path] | None = None
        for path in state_dir.glob("compacted-*.yaml"):
            try:
                record_turn = int(path.stem.replace("compacted-", ""))
            except ValueError:
                continue
            if upto_turn is not None and record_turn > upto_turn:
                continue
            if best is None or record_turn > best[0]:
                best = (record_turn, path)
        if best is None:
            return None
        return yaml.safe_load(best[1].read_text(encoding="utf-8")) or None


def default_summarizer(commit_record: dict) -> dict:
    """确定性默认摘要器：五要素原样保留（不丢要素是 SPEC-M2-05 的硬约束）。"""
    return {name: commit_record.get(name) for name in FIVE_ELEMENTS}
