# -*- coding: utf-8 -*-
"""m2_information.context_builder · Context 构建八步管线（确定性编译）。

specs/M2-information.md §2：
``读状态 → 身份解析 → 收集源 → 权限过滤 → 排序 → 预算裁剪 → 压缩 → 编译+Manifest``

- SPEC-M2-01 确定性：hash = sha256(规范 JSON{task_id, turn, version, sources 五元组,
  total_tokens})；compiled_at（时钟）不进 hash；同 TaskState 版本+同轮+同资产版本
  → 必同 hash；
- SPEC-M2-02 分层：System Context 严格六层（层序冲突前者覆盖后者）+ Task Context
  七源；
- SPEC-M2-03 预算裁剪：优先级从低到高丢弃/压缩（COMPACTED_HISTORY 优先压缩，
  SYSTEM_POLICY 永不裁）；裁剪必留 Manifest 记录（origin 注记 + 编译记录 trim_log）；
  仅剩 policy 仍超预算 → 拒绝裁 policy，落 budget.exhausted 并将任务转 PAUSED；
- SPEC-M2-04 Manifest 完整：total_tokens == Σ sources.tokens；五字段齐备。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from contracts import ContextManifest

from .timestamps import utc_now_iso

__all__ = [
    "ContextBuilder",
    "CompiledContext",
    "SourceDraft",
    "ContextBudgetExceededError",
    "estimate_tokens",
    "SYSTEM_LAYER_ORDER",
    "TASK_SOURCE_ORDER",
    "DEFAULT_PRIORITY",
    "NEVER_TRIM_TYPES",
    "SYSTEM_CONTEXT_SPEC",
    "TASK_CONTEXT_SPEC",
]

# ----------------------------------------------------------- 分层规格（SPEC-M2-02）
SYSTEM_LAYER_ORDER: tuple[str, ...] = (
    "SYSTEM_POLICY",      # 1 平台政策
    "AGENT_CONTRACT",     # 2 Agent 契约
    "TENANT_RULE",        # 3 租户规则
    "RUNTIME_REMINDER",   # 4 运行时提醒
    "SKILL",              # 5 已选技能
    "TOOL_DESCRIPTOR",    # 6 工具描述
)
TASK_SOURCE_ORDER: tuple[str, ...] = (
    "GOAL_STEERING", "PLAN_TODO", "RECENT_INTERACTION", "COMPACTED_HISTORY",
    "RETRIEVED_MEMORY", "RETRIEVED_KNOWLEDGE", "ONTOLOGY_VIEW",
)
SYSTEM_CONTEXT_SPEC = {
    "SYSTEM_POLICY": "平台政策", "AGENT_CONTRACT": "Agent 契约", "TENANT_RULE": "租户规则",
    "RUNTIME_REMINDER": "运行时提醒", "SKILL": "已选技能", "TOOL_DESCRIPTOR": "工具描述",
}
TASK_CONTEXT_SPEC = {
    "GOAL_STEERING": "目标导航", "PLAN_TODO": "计划待办", "RECENT_INTERACTION": "近期交互",
    "COMPACTED_HISTORY": "压缩历史", "RETRIEVED_MEMORY": "检索记忆",
    "RETRIEVED_KNOWLEDGE": "检索知识", "ONTOLOGY_VIEW": "本体视图",
}

#: 优先级（越大越重要；裁剪从低到高）。policy 层置顶且永不裁。
DEFAULT_PRIORITY: dict[str, int] = {
    "SYSTEM_POLICY": 100,
    "AGENT_CONTRACT": 95,
    "TENANT_RULE": 90,
    "GOAL_STEERING": 80,
    "PLAN_TODO": 75,
    "RECENT_INTERACTION": 60,
    "ONTOLOGY_VIEW": 55,
    "SKILL": 50,
    "TOOL_DESCRIPTOR": 45,
    "RUNTIME_REMINDER": 40,
    "RETRIEVED_KNOWLEDGE": 35,
    "RETRIEVED_MEMORY": 30,
    "COMPACTED_HISTORY": 10,   # 优先压缩（SPEC-M2-03）
    "WORKSPACE_REF": 20,
}
NEVER_TRIM_TYPES: frozenset[str] = frozenset({"SYSTEM_POLICY"})

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_@./:-]+")

#: 六层缺省文案（中文，常驻；可经 system_texts 覆盖）
_DEFAULT_SYSTEM_TEXTS: dict[str, str] = {
    "SYSTEM_POLICY": (
        "平台政策：动作必须经注册能力执行；两票制与审批红线不可绕过；"
        "一切状态变更经 ActionRequest 通道落事件流。"
    ),
    "AGENT_CONTRACT": (
        "Agent 契约：只做登记在册的动作；高风险动作先 ASK 审批；"
        "完成申请必须携带三态证据（intended/issued/observed）。"
    ),
    "TENANT_RULE": "租户规则（{tenant_id}）：夜间 22:00-06:00 禁止噪声检修作业。",
    "RUNTIME_REMINDER": "",
}
#: 各层缺省指令（层序冲突消解的判据数据；前者覆盖后者）
_DEFAULT_DIRECTIVES: dict[str, dict] = {
    "SYSTEM_POLICY": {"approval_channel": "strict", "evidence_level": "three_state"},
    "AGENT_CONTRACT": {"approval_channel": "strict"},
    "TENANT_RULE": {"maintenance_window": "22:00-06:00"},
}


def estimate_tokens(text: str) -> int:
    """确定性 token 估算：CJK 每字 1 token；ASCII 连串词元每串 1 token。"""
    text = str(text or "")
    cjk = len(_CJK_RE.findall(text))
    residue = _CJK_RE.sub(" ", text)
    ascii_tokens = len(_ASCII_WORD_RE.findall(residue))
    return cjk + ascii_tokens


class ContextBudgetExceededError(RuntimeError):
    """预算耗尽且仅剩 policy 层：拒绝裁 policy（SPEC-M2-03 负向口径）。"""

    def __init__(self, message: str, *, policy_tokens: int, budget: int) -> None:
        super().__init__(message)
        self.policy_tokens = policy_tokens
        self.budget = budget


@dataclass
class SourceDraft:
    """Manifest 源草稿（编译中间态；directives 供层序冲突消解）。"""

    name: str
    type: str
    text: str = ""
    tokens: int | None = None          # 显式 token 计量（预算化注入时使用）
    origin: str = ""
    directives: dict = field(default_factory=dict)
    requires: dict = field(default_factory=dict)  # 权限过滤条件（role/tenant/visibility）

    def token_count(self) -> int:
        return int(self.tokens) if self.tokens is not None else estimate_tokens(self.text)

    def to_source(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "tokens": self.token_count(),
            "priority": DEFAULT_PRIORITY.get(self.type, 25),
            "origin": self.origin,
        }


@dataclass
class CompiledContext:
    """编译结果：契约 Manifest + 过程记录（trim/filter/冲突/分块）。"""

    manifest: ContextManifest
    blocks: list[dict] = field(default_factory=list)
    trim_log: list[dict] = field(default_factory=list)
    filter_log: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    directives: dict = field(default_factory=dict)
    record_path: str = ""


class ContextBuilder:
    """八步管线执行器（依赖注入：状态读取/事件流/技能/检索器/提交器）。"""

    def __init__(
        self,
        *,
        state_reader: Callable[[str], Any],
        event_log,
        skills=None,
        workspace_of: Callable[[str], Any] | None = None,
        memory_retriever: Callable[..., list] | None = None,
        knowledge_retriever: Callable[..., list] | None = None,
        commit_fn: Callable[[str, dict], Any] | None = None,
        emit_fn: Callable[[str, str, dict, str], None] | None = None,
        now_fn: Callable[[], str] = utc_now_iso,
        system_texts: dict[str, str] | None = None,
        tools: Iterable[dict] | None = None,
    ) -> None:
        self.state_reader = state_reader
        self.event_log = event_log
        self.skills = skills
        self.workspace_of = workspace_of
        self.memory_retriever = memory_retriever
        self.knowledge_retriever = knowledge_retriever
        self.commit_fn = commit_fn
        self.emit_fn = emit_fn
        self._now = now_fn
        self.system_texts = dict(system_texts or {})
        self.tools = list(tools or [])
        self.budget_last: int = 0  # 最近一次编译采用的预算（诊断用）

    # ================================================================ 主入口
    def compile(
        self,
        task_id: str,
        turn: int,
        *,
        now: str | None = None,
        actor: dict | None = None,
        tenant_id: str | None = None,
        task_domains: Iterable[str] = (),
        selected_skills: Iterable[str] = (),
        token_budget: int | None = None,
        extra_sources: Iterable[dict] = (),
        recent_window: int = 10,
        ontology_view: dict | None = None,
        goal: str | None = None,
    ) -> CompiledContext:
        """八步编译；返回 CompiledContext（manifest 为契约结构）。"""
        # 1 读状态
        state = self._step_read_state(task_id)
        # 2 身份解析
        identity = self._step_resolve_identity(state, actor=actor, tenant_id=tenant_id)
        # 3 收集源
        sources = self._step_collect_sources(
            state, turn, identity, task_domains=task_domains,
            selected_skills=selected_skills, extra_sources=extra_sources,
            recent_window=recent_window, ontology_view=ontology_view, goal=goal,
        )
        # 4 权限过滤
        sources, filter_log = self._step_permission_filter(sources, identity)
        # 5 排序
        sources = self._step_sort(sources)
        # 6 预算裁剪
        budget = self._resolve_budget(state, token_budget)
        self.budget_last = budget
        sources, trim_log, exhausted = self._step_budget_trim(sources, budget, task_id)
        # 7 压缩（压缩历史替换近期交互窗口）
        sources = self._step_compress(sources, turn)
        # 8 编译 + Manifest
        compiled = self._step_compile(
            state, turn, sources, budget, trim_log, filter_log, now=now
        )
        if exhausted:
            # policy 永不裁：拒绝出超额 Manifest，任务转 PAUSED（SPEC-M2-03 负向）
            self._budget_exhausted(task_id, compiled, budget)
        return compiled

    # ================================================================ 步骤 1
    def _step_read_state(self, task_id: str):
        return self.state_reader(task_id)  # TaskStateNotFoundError 由调用方处理

    # ================================================================ 步骤 2
    def _step_resolve_identity(self, state, *, actor: dict | None,
                               tenant_id: str | None) -> dict:
        actor = dict(actor or {})
        return {
            "task_id": state.task_id,
            "agent": actor.get("agent") or "agent@default",
            "user": actor.get("user") or "",
            "role": actor.get("role") or "OPERATOR",
            "tenant_id": tenant_id or actor.get("tenant_id") or "tenant-default",
            "domains": set(),
        }

    # ================================================================ 步骤 3
    def _step_collect_sources(
        self, state, turn: int, identity: dict, *, task_domains, selected_skills,
        extra_sources, recent_window: int, ontology_view, goal: str | None,
    ) -> list[SourceDraft]:
        sources: list[SourceDraft] = []
        # ---- System Context 六层
        sources.append(self._system_source("SYSTEM_POLICY", identity))
        sources.append(self._system_source("AGENT_CONTRACT", identity))
        sources.append(self._system_source("TENANT_RULE", identity))
        sources.append(SourceDraft(
            name="runtime.reminder",
            type="RUNTIME_REMINDER",
            text=f"任务状态 {state.status.value}；当前阶段 {state.current_stage}；"
                 f"预算余量 token={state.budget.token_max - state.budget.token_used}",
            origin="runtime/task-state",
            directives={"reminder_status": state.status.value},
        ))
        for draft in self._skill_sources(task_domains, selected_skills):
            sources.append(draft)
        if self.tools:
            text = "\n".join(
                f"{t.get('capability', t.get('name', 'tool'))}: {t.get('description', '')}"
                for t in self.tools
            )
            origin = "tools@" + hashlib.sha256(
                json.dumps(self.tools, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:8]
            sources.append(SourceDraft(name="tool.descriptors", type="TOOL_DESCRIPTOR",
                                       text=text, origin=origin))
        # ---- Task Context 七源
        goal_text = goal or self._goal_of(state)
        sources.append(SourceDraft(
            name="task.goal_steering", type="GOAL_STEERING", text=goal_text or "",
            origin="runtime/task-created",
        ))
        plan_text = "\n".join(
            f"- 阶段 {step.stage}｜门禁 {step.gate}｜预期产物 {'/'.join(step.artifacts_expected) or '无'}"
            for step in state.plan
        ) + "\n" + "\n".join(
            f"- [todo:{todo.id}:{todo.status.value}] {todo.text}" for todo in state.todos
        )
        sources.append(SourceDraft(name="task.plan_todo", type="PLAN_TODO",
                                   text=plan_text, origin="runtime/task-state"))
        recent = self._recent_interactions(state.task_id, turn, recent_window)
        if recent:
            sources.append(SourceDraft(name="task.recent", type="RECENT_INTERACTION",
                                       text=recent, origin="runtime/events"))
        compacted = self._compacted_source(state.task_id, turn)
        if compacted is not None:
            sources.append(compacted)
        if self.memory_retriever is not None:
            entries = self.memory_retriever(goal_text or state.task_id, state.task_id) or []
            if entries:
                text = "\n".join(
                    f"- [{e.get('type')}@{e.get('memory_id')}] "
                    f"{(e.get('content') or {}).get('subject', '')}: "
                    f"{(e.get('content') or {}).get('claim', '')}"
                    for e in entries
                )
                sources.append(SourceDraft(name="task.memory", type="RETRIEVED_MEMORY",
                                           text=text, origin=f"memory/{len(entries)}"))
        if self.knowledge_retriever is not None:
            entries = self.knowledge_retriever(goal_text or state.task_id, state.task_id) or []
            if entries:
                text = "\n".join(
                    f"- [{e.get('entry_id')}] {json.dumps(e.get('content'), ensure_ascii=False)}"
                    for e in entries
                )
                sources.append(SourceDraft(name="task.knowledge", type="RETRIEVED_KNOWLEDGE",
                                           text=text, origin=f"knowledge/{len(entries)}"))
        if ontology_view:
            sources.append(SourceDraft(
                name="task.ontology_view", type="ONTOLOGY_VIEW",
                text=ontology_view.get("text", ""),
                tokens=ontology_view.get("tokens"),
                origin=ontology_view.get("origin", "m4/concept_view"),
            ))
        # ---- 用例/上层注入源（token 权重可显式声明）
        for extra in extra_sources or ():
            sources.append(SourceDraft(
                name=str(extra.get("name", "extra")),
                type=str(extra.get("type", "WORKSPACE_REF")),
                text=str(extra.get("text", "")),
                tokens=extra.get("tokens"),
                origin=str(extra.get("origin", "injected")),
                directives=dict(extra.get("directives") or {}),
                requires=dict(extra.get("requires") or {}),
            ))
        return [s for s in sources if s.text or (s.tokens or 0) > 0]

    # ================================================================ 步骤 4
    def _step_permission_filter(self, sources: list[SourceDraft],
                                identity: dict) -> tuple[list[SourceDraft], list[dict]]:
        kept: list[SourceDraft] = []
        log: list[dict] = []
        for source in sources:
            requires = source.requires or {}
            if requires:
                ok = True
                if "tenant" in requires and requires["tenant"] != identity["tenant_id"]:
                    ok = False
                if "role" in requires and requires["role"] != identity["role"]:
                    ok = False
                if "visibility" in requires and requires["visibility"] != "public" \
                        and identity["role"] not in requires.get("roles", []):
                    ok = False
                if not ok:
                    log.append({"name": source.name, "type": source.type,
                                "reason": "权限不满足（requires 不匹配）"})
                    continue
            kept.append(source)
        return kept, log

    # ================================================================ 步骤 5
    def _step_sort(self, sources: list[SourceDraft]) -> list[SourceDraft]:
        system_rank = {t: i for i, t in enumerate(SYSTEM_LAYER_ORDER)}
        task_rank = {t: i for i, t in enumerate(TASK_SOURCE_ORDER)}
        other_rank = {t: len(SYSTEM_LAYER_ORDER) + len(TASK_SOURCE_ORDER) + i
                      for i, t in enumerate(("WORKSPACE_REF",))}

        def rank(source: SourceDraft) -> tuple[int, int, str]:
            if source.type in system_rank:
                return (0, system_rank[source.type], source.name)
            if source.type in task_rank:
                return (1, task_rank[source.type], source.name)
            return (2, other_rank.get(source.type, 99), source.name)

        return sorted(sources, key=rank)

    # ================================================================ 步骤 6
    def _resolve_budget(self, state, token_budget: int | None) -> int:
        if token_budget is not None:
            return int(token_budget)
        return int(state.budget.token_max - state.budget.token_used)

    def _step_budget_trim(self, sources: list[SourceDraft], budget: int,
                          task_id: str) -> tuple[list[SourceDraft], list[dict], bool]:
        """按优先级从低到高丢弃/压缩；policy 永不裁；仅剩 policy 仍超 → 拒绝。"""
        trim_log: list[dict] = []
        total = sum(s.token_count() for s in sources)

        def remaining() -> int:
            return sum(s.token_count() for s in sources)

        while remaining() > budget:
            trimmable = [s for s in sources
                         if s.type not in NEVER_TRIM_TYPES and s.token_count() > 0]
            if not trimmable:
                policy_tokens = sum(s.token_count() for s in sources)
                detail = (
                    f"任务 {task_id} 上下文预算 {budget} tokens 不足以容纳不可裁剪的"
                    f" policy 层（{policy_tokens} tokens）；拒绝裁剪 policy"
                    f"（SPEC-M2-03：policy 永不压）"
                )
                trim_log.append({"action": "refused", "detail": detail,
                                 "policy_tokens": policy_tokens, "budget": budget})
                return sources, trim_log, True
            target = min(trimmable, key=lambda s: (DEFAULT_PRIORITY.get(s.type, 25),
                                                   s.name))
            before = target.token_count()
            if target.type == "COMPACTED_HISTORY" and before > 4:
                # 优先压缩（指数衰减至不可再压后丢弃）
                kept_tokens = max(before // 2, 4)
                target.tokens = kept_tokens
                trim_log.append({"action": "compressed", "name": target.name,
                                 "type": target.type,
                                 "tokens_before": before, "tokens_after": kept_tokens})
                continue
            target.tokens = 0
            target.origin = f"{target.origin};trimmed=dropped@priority=" \
                            f"{DEFAULT_PRIORITY.get(target.type, 25)}"
            trim_log.append({"action": "dropped", "name": target.name, "type": target.type,
                             "tokens_before": before, "tokens_after": 0})
        return sources, trim_log, False

    # ================================================================ 步骤 7
    def _step_compress(self, sources: list[SourceDraft], turn: int) -> list[SourceDraft]:
        """压缩步：压缩历史在场时，近期交互窗口收缩为其后的增量。"""
        compacted = next((s for s in sources if s.type == "COMPACTED_HISTORY"
                          and s.token_count() > 0), None)
        if compacted is None:
            return sources
        compact_turn = self._turn_of_origin(compacted.origin)
        recent = next((s for s in sources if s.type == "RECENT_INTERACTION"), None)
        if recent is not None and compact_turn is not None and turn > compact_turn:
            lines = [ln for ln in recent.text.splitlines()
                     if self._line_turn(ln) > compact_turn]
            recent.text = "\n".join(lines)
            if not recent.text:
                recent.tokens = 0
                recent.origin = f"{recent.origin};trimmed=superseded_by_compact@turn={compact_turn}"
        return sources

    # ================================================================ 步骤 8
    def _step_compile(self, state, turn: int, sources: list[SourceDraft], budget: int,
                      trim_log: list[dict], filter_log: list[dict], *,
                      now: str | None) -> CompiledContext:
        total = sum(s.token_count() for s in sources)
        # 层序冲突消解：前者覆盖后者（sources 已按层序排序，先到先得）
        directives: dict = {}
        conflicts: list[dict] = []
        for source in sources:
            for key, value in (source.directives or {}).items():
                if key in directives and directives[key] != value:
                    conflicts.append({"key": key, "kept": directives[key],
                                      "dropped": value, "loser": source.name})
                else:
                    directives[key] = value
        manifest = ContextManifest.from_dict({
            "task_id": state.task_id,
            "turn": int(turn),
            "sources": [s.to_source() for s in sources],
            "total_tokens": total,
            "budget_remaining": int(budget - total),
            "compiled_at": now or self._now(),
            "hash": self.compute_hash(state.task_id, turn, state.version, sources, total),
        })
        blocks = [{"layer": "system" if s.type in SYSTEM_LAYER_ORDER else
                   ("task" if s.type in TASK_SOURCE_ORDER else "extra"),
                   "type": s.type, "name": s.name, "text": s.text,
                   "tokens": s.token_count()} for s in sources]
        return CompiledContext(manifest=manifest, blocks=blocks, trim_log=trim_log,
                               filter_log=filter_log, conflicts=conflicts,
                               directives=directives)

    # ================================================================ 辅助
    def _system_source(self, layer: str, identity: dict) -> SourceDraft:
        text = self.system_texts.get(layer) or _DEFAULT_SYSTEM_TEXTS[layer]
        if layer == "TENANT_RULE":
            text = text.format(tenant_id=identity["tenant_id"])
        origin = f"system/{layer.lower()}@" + hashlib.sha256(
            text.encode("utf-8")).hexdigest()[:8]
        directives = dict(_DEFAULT_DIRECTIVES.get(layer, {}))
        return SourceDraft(name=f"system.{layer.lower()}", type=layer, text=text,
                           origin=origin, directives=directives)

    def _skill_sources(self, task_domains, selected_skills) -> list[SourceDraft]:
        if self.skills is None:
            return []
        registry = self.skills
        drafts: list[SourceDraft] = []
        roster = registry.level0_roster()
        if roster:
            drafts.append(SourceDraft(
                name="skill.level0_roster", type="SKILL", text=roster,
                origin=f"skills/level0@{registry.version_fingerprint()}",
            ))
        catalog, matched = registry.level1_catalog(task_domains)
        if catalog:
            drafts.append(SourceDraft(
                name="skill.level1_catalog", type="SKILL", text=catalog,
                origin=f"skills/level1@{';'.join(sorted(matched))}",
            ))
        for skill_id in selected_skills or ():
            view = registry.disclose(skill_id, 2)  # 未注册/不可披露 → SkillDisclosureError
            drafts.append(SourceDraft(
                name=f"skill.level2.{skill_id}", type="SKILL", text=view["text"],
                origin=view["origin"],
            ))
        return drafts

    def _goal_of(self, state) -> str:
        for event in self.event_log.query(state.task_id, "task.created"):
            return str((event.get("payload") or {}).get("user_input") or "")
        return ""

    def _recent_interactions(self, task_id: str, turn: int, window: int) -> str:
        events = self.event_log.query(task_id, "action.completed", "approval.granted",
                                      "approval.denied", "task.stage_gate")
        picked = events[-int(window):] if window > 0 else []
        lines = []
        for event in picked:
            payload = event.get("payload") or {}
            lines.append(f"[turn={payload.get('turn', '?')}] {event['type']}: "
                         f"{json.dumps({k: v for k, v in payload.items()
                                        if k in ('capability', 'status', 'decision',
                                                 'stage', 'verdict', 'observation')},
                                       ensure_ascii=False)}")
        return "\n".join(lines)

    def _compacted_source(self, task_id: str, turn: int) -> SourceDraft | None:
        if self.workspace_of is None:
            return None
        ws = self.workspace_of(task_id)
        state_dir = ws.sub("state")
        if not state_dir.is_dir():
            return None
        best: tuple[int, Path] | None = None
        for path in state_dir.glob("compacted-*.yaml"):
            stem = path.stem.replace("compacted-", "")
            try:
                record_turn = int(stem)
            except ValueError:
                continue
            if record_turn <= turn and (best is None or record_turn > best[0]):
                best = (record_turn, path)
        if best is None:
            return None
        import yaml

        data = yaml.safe_load(best[1].read_text(encoding="utf-8")) or {}
        text = str(data.get("context_text") or "")
        if not text:
            return None
        return SourceDraft(
            name="task.compacted_history", type="COMPACTED_HISTORY", text=text,
            origin=f"workspace/state/compacted-{best[0]}.yaml@turn={best[0]}",
            tokens=data.get("tokens"),
        )

    @staticmethod
    def _turn_of_origin(origin: str) -> int | None:
        marker = "@turn="
        if marker in origin:
            tail = origin.split(marker, 1)[1].split(";", 1)[0]
            try:
                return int(tail)
            except ValueError:
                return None
        return None

    @staticmethod
    def _line_turn(line: str) -> int:
        marker = "[turn="
        if marker in line:
            tail = line.split(marker, 1)[1].split("]", 1)[0]
            try:
                return int(tail)
            except ValueError:
                return 0
        return 0

    @staticmethod
    def compute_hash(task_id: str, turn: int, version: int,
                     sources: list[SourceDraft] | list[dict], total_tokens: int) -> str:
        """确定性 hash：规范 JSON 核心五元组（无 compiled_at、无随机量、无时钟）。"""
        if sources and isinstance(sources[0], SourceDraft):
            source_payloads = [s.to_source() for s in sources]
        else:
            source_payloads = [dict(s) for s in sources]
        core = {
            "task_id": task_id,
            "turn": int(turn),
            "version": int(version),
            "sources": source_payloads,
            "total_tokens": int(total_tokens),
        }
        canonical = json.dumps(core, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # ---------------------------------------------------- 预算耗尽（负向）
    def _budget_exhausted(self, task_id: str, compiled: CompiledContext,
                          budget: int) -> None:
        policy_tokens = sum(
            s.tokens for s in compiled.manifest.sources
            if s.type.value == "SYSTEM_POLICY"
        )
        if self.emit_fn is not None:
            self.emit_fn(
                "budget.exhausted", task_id,
                {"kind": "token", "budget": budget, "policy_tokens": policy_tokens},
                f"task-{task_id}",
            )
        if self.commit_fn is not None:
            try:
                self.commit_fn(task_id, {"status": "PAUSED", "note": "context_budget"})
            except Exception:  # noqa: BLE001 - 非 RUNNING 态转 PAUSED 非法时保留原状态
                pass
        raise ContextBudgetExceededError(
            f"上下文预算 {budget} tokens 不足且不可裁（policy 层 {policy_tokens} tokens"
            f" 永不裁剪），任务已请求转入 PAUSED（task={task_id}）",
            policy_tokens=policy_tokens,
            budget=budget,
        )
