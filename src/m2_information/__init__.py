# -*- coding: utf-8 -*-
"""m2_information · Information（信息层）：Context 构建管线、状态外置、
Workspace/Artifact、Memory/Skill 披露（specs/M2-information.md）。

冻结调用接口（specs/01-contracts.md §3.2）由 :class:`InformationLayer` 提供：

    compile_context(task_id, turn) -> ContextManifest
    commit_state(task_id, mutation) -> TaskState        # 版本+1，事件落盘
    snapshot(task_id) -> Checkpoint
    restore(checkpoint_id) -> TaskState
    write_memory(task_id, content, type, provenance) -> MemoryId | "REJECTED"
    retrieve_memory(query, task_id) -> list[MemoryEntry]
    disclose_skill(skill_id, level) -> SkillView        # 三级披露
    save_artifact(record) -> ArtifactId
    validate_artifact(artifact_id) -> ValidationReport

运行期布局（详见 FORMATS.md）::

    <root>/state.db          SQLite（task_state/artifacts/memory/checkpoints+…）
    <root>/events/*.jsonl    追加写事件流（task-<id> 分片）
    <root>/workspaces/<task>/{inputs,scratch,state,artifacts,evidence,manifest}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable

from contracts import ArtifactRecord, ContextManifest, Evidence, TaskState

from .artifact import ArtifactManager, ArtifactValidationError, report_daily_v1
from .compactor import Compactor, CompactValidationError, FIVE_ELEMENTS
from .context_builder import (
    ContextBudgetExceededError,
    ContextBuilder,
    CompiledContext,
    estimate_tokens,
)
from .event_log import EventAppendError, EventLog
from .ids import new_ulid
from .memory import (
    KnowledgeBase,
    KnowledgeReadOnlyError,
    MemoryRenewalRejectedError,
    MemoryStore,
    REJECTED,
)
from .session import SessionManager
from .skill_disclosure import SkillRegistry, SkillView
from .state_store import (
    IllegalTransitionError,
    MutationError,
    StateStore,
    TaskStateNotFoundError,
    apply_state_mutation,
    default_initial_state,
    transition_allowed,
)
from .timestamps import utc_now_iso
from .workspace import WorkspaceIsolationError, WorkspaceManager

__all__ = [
    "InformationLayer",
    "EvidenceRejectedError",
    # 重导出（模块内组件与错误）
    "EventLog", "EventAppendError", "StateStore", "TaskStateNotFoundError",
    "IllegalTransitionError", "MutationError", "apply_state_mutation",
    "transition_allowed", "WorkspaceManager", "WorkspaceIsolationError",
    "ArtifactManager", "ArtifactValidationError", "report_daily_v1",
    "MemoryStore", "KnowledgeBase", "KnowledgeReadOnlyError",
    "MemoryRenewalRejectedError", "REJECTED", "SkillRegistry", "SkillView",
    "SessionManager", "ContextBuilder", "CompiledContext",
    "ContextBudgetExceededError", "estimate_tokens", "Compactor",
    "CompactValidationError", "FIVE_ELEMENTS",
]


class EvidenceRejectedError(ValueError):
    """evidence/ 目录拒绝非三态证据/只读读数快照的内容（SPEC-M2-09）。"""


def _audit_via_event_log(event_log: EventLog, now_fn: Callable[[], str]) -> Callable:
    def auditor(event_type: str, subject: str, payload: dict, stream: str) -> None:
        event_log.append(
            {
                "type": event_type,
                "subject": subject,
                "payload": payload,
                "trace_id": payload.get("trace_id") or f"audit-{subject}",
                "producer": "M2",
            },
            stream=stream,
            now_fn=now_fn,
        )

    return auditor


class InformationLayer:
    """信息层门面（持有 runtime 全部持久状态；进程内单例语义）。"""

    def __init__(
        self,
        root: Path | str,
        *,
        dsn: str | None = None,
        skills: Iterable[dict] | None = None,
        skills_dir: Path | None = None,
        now_fn: Callable[[], str] | None = None,
        tools: Iterable[dict] | None = None,
        rule_id_checker: Callable[[list], list] | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._now = now_fn or utc_now_iso
        self.event_log = EventLog(self.root / "events")
        self.store = StateStore(dsn or (self.root / "state.db"))
        auditor = _audit_via_event_log(self.event_log, self._now)
        self.workspaces = WorkspaceManager(
            self.root / "workspaces",
            artifact_status_of=self._artifact_status_of,
            auditor=auditor,
        )
        self.memory = MemoryStore(self.store, auditor=auditor, now_fn=self._now)
        self.knowledge = KnowledgeBase(self.store, auditor=auditor, now_fn=self._now)
        self.skills = SkillRegistry(skills, skills_dir=skills_dir,
                                    level2_root=self.root / "skills_fulltext")
        self.artifacts = ArtifactManager(
            self.store, self.workspaces, self.event_log,
            rule_id_checker=rule_id_checker, now_fn=self._now,
        )
        self.sessions = SessionManager(self.store, now_fn=self._now)
        self.compactor = Compactor(
            state_reader=self.get_task,
            workspace_of=lambda task_id: self.workspaces.workspace(task_id),
            event_log=self.event_log,
            artifact_lister=self.store.list_artifacts,
            commit_fn=self.commit_state,
            now_fn=self._now,
        )
        self.builder = ContextBuilder(
            state_reader=self.get_task,
            event_log=self.event_log,
            skills=self.skills,
            workspace_of=lambda task_id: self.workspaces.workspace(task_id, create=False),
            memory_retriever=lambda query, task_id: self.memory.retrieve(query, task_id),
            knowledge_retriever=lambda query, task_id: self.knowledge.retrieve(query, task_id),
            commit_fn=self.commit_state,
            emit_fn=self._emit,
            now_fn=self._now,
            tools=tools,
        )

    # ================================================== 任务生命周期（M1 用）
    def create_task(
        self,
        task_id: str,
        *,
        user_input: str,
        trace_id: str,
        plan: list[dict] | None = None,
        todos: list[dict] | None = None,
        budget: dict | None = None,
        current_stage: str = "INTAKE",
        status: str = "CREATED",
        turn: int = 0,
    ) -> TaskState:
        """创建任务（task.created 事件 + 初始 TaskState 落库 + 工作区）。"""
        if self.store.has_task(task_id):
            raise ValueError(f"任务已存在: {task_id}")
        state = default_initial_state(
            task_id, status=status, current_stage=current_stage,
            plan=plan or [], todos=todos or [], budget=budget,
        )
        parsed = TaskState.from_dict(state)
        self.store.create_task(parsed)
        self.workspaces.workspace(task_id)
        self.event_log.append(
            {
                "type": "task.created",
                "subject": task_id,
                "payload": {
                    "user_input": user_input,
                    "turn": int(turn),
                    "state": parsed.to_dict(),
                },
                "trace_id": trace_id,
                "producer": "M2",
            },
            stream=f"task-{task_id}",
            now_fn=self._now,
        )
        return parsed

    def get_task(self, task_id: str) -> TaskState:
        return self.store.get_task(task_id)

    def commit_state(self, task_id: str, mutation: dict) -> TaskState:
        """状态提交：乐观锁版本+1；非法迁移抛 IllegalTransitionError 并落拒绝事件。"""
        current = self.store.get_task(task_id)
        data = current.to_dict()
        from_status = data["status"]
        to_status = mutation.get("status") or from_status
        if to_status != from_status and not transition_allowed(from_status, to_status):
            self.event_log.append(
                {
                    "type": "task.status_changed",
                    "subject": task_id,
                    "payload": {
                        "from": from_status, "to": to_status, "accepted": False,
                        "reason": f"非法迁移（01§5.1）：{from_status}→{to_status}",
                    },
                    "trace_id": mutation.get("trace_id") or f"task-{task_id}",
                    "producer": "M2",
                },
                stream=f"task-{task_id}",
                now_fn=self._now,
            )
            raise IllegalTransitionError(from_status, to_status)
        apply_state_mutation(data, dict(mutation))
        data["version"] = current.version + 1
        data["updated_at"] = self._now()
        if to_status != from_status:
            data["status"] = to_status
        new_state = TaskState.from_dict(data)
        self.store.put_task(new_state, expected_version=current.version)
        self.event_log.append(
            {
                "type": "task.status_changed",
                "subject": task_id,
                "payload": {
                    "from": from_status, "to": to_status, "accepted": True,
                    "mutation": {k: v for k, v in mutation.items()
                                 if k not in ("trace_id",)},
                    "version": new_state.version,
                    "updated_at": new_state.updated_at,
                },
                "trace_id": mutation.get("trace_id") or f"task-{task_id}",
                "producer": "M2",
            },
            stream=f"task-{task_id}",
            now_fn=self._now,
        )
        return new_state

    # ================================================== 01§3.2 冻结接口
    def compile_context(
        self, task_id: str, turn: int, *, persist: bool = True, **options
    ) -> ContextManifest:
        """八步编译（SPEC-M2-01..04）；编译记录持久化到 workspace manifest/。"""
        compiled = self.builder.compile(task_id, int(turn), **options)
        if persist:
            ws = self.workspaces.workspace(task_id)
            record = {
                "manifest": compiled.manifest.to_dict(),
                "blocks": compiled.blocks,
                "trim_log": compiled.trim_log,
                "filter_log": compiled.filter_log,
                "conflicts": compiled.conflicts,
                "directives": compiled.directives,
            }
            rel = f"manifest/turn-{int(turn)}.json"
            ws.write(rel, json.dumps(record, ensure_ascii=False, indent=2))
            compiled.record_path = rel
            self.commit_state(task_id, {
                "context_manifest_hash": compiled.manifest.hash,
                "note": f"compiled@turn={turn}",
                "trace_id": f"task-{task_id}",
            })
        return compiled.manifest

    def compile_full(self, task_id: str, turn: int, **options) -> CompiledContext:
        """同 compile_context，但返回完整编译记录（trim/filter/conflicts 供审计）。"""
        return self.builder.compile(task_id, int(turn), **options)

    def snapshot(self, task_id: str) -> dict:
        """Checkpoint：TaskState 全量 + Workspace manifest 快照（SPEC-M2-06）。"""
        state = self.store.get_task(task_id)
        ws = self.workspaces.workspace(task_id)
        checkpoint_id = f"ckpt-{new_ulid()}"
        payload = {
            "checkpoint_id": checkpoint_id,
            "task_id": task_id,
            "created_at": self._now(),
            "state": state.to_dict(),
            "workspace_manifest": ws.manifest_snapshot(),
        }
        self.store.save_checkpoint(payload)
        ws.write(f"state/checkpoint-{checkpoint_id}.json",
                 json.dumps(payload, ensure_ascii=False, indent=2))
        return payload

    def restore(self, checkpoint_id: str) -> TaskState:
        """从 Checkpoint 恢复（迁移合法性校验 + 恢复事件落流，M1 可续跑）。"""
        payload = self.store.get_checkpoint(checkpoint_id)
        task_id = payload["task_id"]
        current = self.store.get_task(task_id)
        target = dict(payload["state"])
        if target["status"] != current.status.value and \
                not transition_allowed(current.status.value, target["status"]):
            self.event_log.append(
                {
                    "type": "task.status_changed",
                    "subject": task_id,
                    "payload": {
                        "from": current.status.value, "to": target["status"],
                        "accepted": False,
                        "reason": "恢复目标状态与当前状态之间迁移非法（01§5.1）",
                    },
                    "trace_id": f"restore-{checkpoint_id}",
                    "producer": "M2",
                },
                stream=f"task-{task_id}",
                now_fn=self._now,
            )
            raise IllegalTransitionError(current.status.value, target["status"])
        target["version"] = current.version + 1
        target["updated_at"] = self._now()
        restored = TaskState.from_dict(target)
        self.store.put_task(restored, expected_version=current.version)
        self.event_log.append(
            {
                "type": "task.status_changed",
                "subject": task_id,
                "payload": {
                    "from": current.status.value, "to": restored.status.value,
                    "accepted": True,
                    "restored_from": checkpoint_id,
                    "state": restored.to_dict(),
                    "version": restored.version,
                    "updated_at": restored.updated_at,
                },
                "trace_id": f"restore-{checkpoint_id}",
                "producer": "M2",
            },
            stream=f"task-{task_id}",
            now_fn=self._now,
        )
        return restored

    def write_memory(self, task_id: str, content, type: str, provenance: dict) -> str:
        """写入六问（SPEC-M2-10）：通过返回 memory_id，否则返回 "REJECTED"。"""
        return self.memory.write(task_id, content, type, provenance)

    def retrieve_memory(self, query: str, task_id: str | None = None) -> list[dict]:
        """检索记忆（TTL 过期/归档/被替代不返回；过期计数见 memory.expired_report）。"""
        return self.memory.retrieve(query, task_id)

    def disclose_skill(self, skill_id: str, level: int) -> SkillView:
        """三级披露（SPEC-M2-12）：level0 常驻/level1 目录/level2 选中加载。"""
        return self.skills.disclose(skill_id, int(level))

    def save_artifact(self, record: dict | ArtifactRecord, *,
                      content: dict | None = None) -> str:
        """落 DRAFT ArtifactRecord（01§3.2 save_artifact）。"""
        if isinstance(record, ArtifactRecord):
            parsed = record
        else:
            data = dict(record)
            data.setdefault("status", "DRAFT")
            data.setdefault("version", 1)
            data.setdefault("validation", None)
            data.setdefault("supersedes", None)
            parsed = ArtifactRecord.from_dict(data)
        if parsed.status.value != "DRAFT":
            raise ArtifactValidationError(
                f"save_artifact 仅接受 DRAFT 产物（新建），实际 {parsed.status.value}"
            )
        if content is not None:
            ws = self.workspaces.workspace(parsed.created_by.task_id)
            ws.write(parsed.content_ref,
                     json.dumps(content, ensure_ascii=False, indent=2))
        self.store.save_artifact(parsed)
        return parsed.artifact_id

    def validate_artifact(self, artifact_id: str) -> dict:
        """schema 校验（01§3.2 validate_artifact）→ ValidationReport dict。"""
        record = self.store.get_artifact(artifact_id)
        return self.artifacts.run_schema(record)

    # ================================================== SPEC-M2-09 证据门
    def save_evidence(self, task_id: str, name: str, payload, *,
                      trace_id: str) -> str:
        """evidence/ 只接受三态证据序列化与只读读数快照（SPEC-M2-09）。

        - 三态证据：``{"action_id", "evidence": {intended[, issued][, observed]}}``
          （contracts.Evidence 校验）；
        - 只读读数快照：dict/list，元素含 device_ref/quantity/value/ts。
        其余（模型生成文本等）拒绝。
        """
        normalized = self._normalize_evidence(payload)
        rel = f"evidence/{_safe_name(name)}.json"
        ws = self.workspaces.workspace(task_id)
        ws.write(rel, json.dumps(normalized, ensure_ascii=False, indent=2))
        return rel

    @staticmethod
    def _normalize_evidence(payload) -> dict:
        if isinstance(payload, dict) and "intended" in payload:
            Evidence.from_dict(payload)  # 三态契约校验
            return {"kind": "action_evidence", "evidence": payload}
        if isinstance(payload, dict) and "evidence" in payload and \
                isinstance(payload["evidence"], dict) and \
                "intended" in payload["evidence"] and "action_id" in payload:
            Evidence.from_dict(payload["evidence"])
            return {"kind": "action_evidence", "evidence": payload["evidence"],
                    "action_id": payload["action_id"]}
        if isinstance(payload, (list, dict)):
            items = payload if isinstance(payload, list) else [payload]
            if items and all(
                isinstance(item, dict) and item.get("device_ref")
                and item.get("quantity") is not None and "value" in item
                and item.get("ts") for item in items
            ):
                return {"kind": "measurement_snapshot", "points": list(items)}
        raise EvidenceRejectedError(
            "evidence/ 只接受 ActionResult.evidence 三态对象序列化与只读读数快照"
            "（device_ref/quantity/value/ts），不接受模型生成文本"
        )

    # ================================================== 辅助（模块内/测试）
    def rebuild_task_state(self, task_id: str) -> TaskState:
        """从事件流重建 TaskState（DoD：与库内快照 diff 为空）。"""
        return self.event_log.rebuild_task_state(task_id)

    def read_cross_task(self, actor_task: str, owner_task: str, rel: str) -> str:
        return self.workspaces.read_cross(actor_task, owner_task, rel)

    def write_cross_task(self, actor_task: str, owner_task: str, rel: str, data) -> None:
        self.workspaces.write_cross(actor_task, owner_task, rel, data)

    def workspace_of(self, task_id: str):
        return self.workspaces.workspace(task_id)

    def _artifact_status_of(self, owner_task: str, rel: str) -> str | None:
        return self.artifacts.status_of_content(owner_task, rel)

    def _emit(self, event_type: str, subject: str, payload: dict, stream: str) -> None:
        self.event_log.append(
            {
                "type": event_type,
                "subject": subject,
                "payload": payload,
                "trace_id": payload.get("trace_id") or f"task-{subject}",
                "producer": "M2",
            },
            stream=stream,
            now_fn=self._now,
        )


def _safe_name(name: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", str(name))
    return cleaned or "evidence"
