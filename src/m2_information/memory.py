# -*- coding: utf-8 -*-
"""m2_information.memory · 四类 Memory + 写入六问 + Knowledge 只读。

specs/M2-information.md SPEC-M2-10 / SPEC-M2-11：

- 四类隔离存储：WORKING / EPISODIC / SEMANTIC / PROCEDURAL（00§2 memory_type）；
- 写入六问（What / Why now / 时效 / 来源可溯 / 验证状态 / 冲突检查）——
  未通过返回哨兵值 ``"REJECTED"``（01§3.2 ``write_memory -> MemoryId | REJECTED``），
  最近一次拒绝原因保留在 ``last_rejection`` 供审计；
  未验证推测（provenance.verification == SPECULATIVE）直接 REJECTED；
- Knowledge 类条目 agent 只读（变更走 M7 评审）：``KnowledgeBase.mutate`` 一律拒绝
  并落审计事件；
- TTL：EPISODIC/SEMANTIC/PROCEDURAL 默认 90 天；续期需引用计数 > 阈值
  （默认 3）；WORKING 随任务归档清理（``archive_task``）。

写入六问与 provenance 结构详见 ``src/m2_information/FORMATS.md``。
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .ids import new_ulid
from .state_store import StateStore
from .timestamps import add_days, is_expired, utc_now_iso

__all__ = [
    "MemoryStore",
    "KnowledgeBase",
    "KnowledgeReadOnlyError",
    "MemoryRenewalRejectedError",
    "SIX_QUESTIONS",
    "DEFAULT_TTL_DAYS",
    "RENEWAL_REF_THRESHOLD",
    "VERIFICATION_LEVELS",
    "REJECTED",
]

#: 契约哨兵：write_memory 未过六问时的返回值（01§3.2）
REJECTED = "REJECTED"

#: 写入六问（SPEC-M2-10）
SIX_QUESTIONS = (
    ("what", "What：记什么（subject+claim 非空）"),
    ("why_now", "Why now：为何此刻写入（provenance.why_now）"),
    ("timeliness", "时效：TTL/有效期（provenance.ttl_days 或 valid_until）"),
    ("provenance", "来源可溯：provenance.source + trace_id"),
    ("verification", "验证状态：verification ∈ VERIFIED/UNVERIFIED/SPECULATIVE"),
    ("conflict", "冲突检查：与既有同主题记忆矛盾时的处置"),
)

DEFAULT_TTL_DAYS = 90
RENEWAL_REF_THRESHOLD = 3
VERIFICATION_LEVELS = ("VERIFIED", "UNVERIFIED", "SPECULATIVE")
_TTL_TYPES = ("EPISODIC", "SEMANTIC", "PROCEDURAL")


class MemoryRenewalRejectedError(ValueError):
    """续期被拒（引用计数未过阈值）。"""


class KnowledgeReadOnlyError(PermissionError):
    """Knowledge 条目对 agent 只读（变更走 M7 评审）。"""


Auditor = Callable[[str, str, dict, str], None]


class MemoryStore:
    """四类记忆 + 写入六问过滤。"""

    def __init__(
        self,
        store: StateStore,
        *,
        auditor: Auditor | None = None,
        now_fn: Callable[[], str] = utc_now_iso,
        id_gen: Callable[[], str] = new_ulid,
        default_ttl_days: int = DEFAULT_TTL_DAYS,
        renewal_threshold: int = RENEWAL_REF_THRESHOLD,
    ) -> None:
        self.store = store
        self.auditor = auditor
        self._now = now_fn
        self._id = id_gen
        self.default_ttl_days = int(default_ttl_days)
        self.renewal_threshold = int(renewal_threshold)
        #: 最近一次六问拒绝（{question, reason, task_id}），供审计/测试断言
        self.last_rejection: dict | None = None

    # -------------------------------------------------------------- 写
    def write(self, task_id: str, content: Any, mem_type: str, provenance: dict) -> str:
        """写入记忆：通过六问返回 memory_id；未通过返回 "REJECTED"（不抛错）。"""
        try:
            return self._write_checked(task_id, content, mem_type, provenance)
        except _SilentReject:
            return REJECTED

    def _write_checked(self, task_id: str, content: Any, mem_type: str, provenance: dict) -> str:
        if mem_type not in _TTL_TYPES + ("WORKING",):
            self._reject(task_id, "what", f"记忆类型越界: {mem_type!r}")
        subject, claim = self._normalize_content(content)
        prov = dict(provenance or {})
        now = self._now()

        # 六问逐问校验（顺序即规格顺序）
        if not subject or not claim:
            self._reject(task_id, "what", "content 需含非空 subject 与 claim")
        if not str(prov.get("why_now") or "").strip():
            self._reject(task_id, "why_now", "provenance.why_now 缺失（为何此刻写入）")
        valid_until = self._resolve_ttl(mem_type, prov, now)
        if valid_until is None:
            self._reject(task_id, "timeliness",
                         "时效未声明：provenance 需含 ttl_days 或 valid_until（WORKING 随任务归档，豁免）")
        if not str(prov.get("source") or "").strip() or not str(prov.get("trace_id") or "").strip():
            self._reject(task_id, "provenance", "来源不可溯：provenance.source 与 trace_id 必填")
        verification = str(prov.get("verification") or "").strip()
        if verification not in VERIFICATION_LEVELS:
            self._reject(task_id, "verification",
                         f"验证状态越界: {verification!r}（允许 {'/'.join(VERIFICATION_LEVELS)}）")
        if verification == "SPECULATIVE":
            self._reject(task_id, "verification",
                         "未验证推测（SPECULATIVE）直接拒绝：先取得环境/执行证据再写入")
        supersede_ids = self._conflict_scan(mem_type, subject, claim, verification)
        if supersede_ids is None:
            self._reject(task_id, "conflict",
                         f"与既有 VERIFIED 记忆同主题矛盾且新条目未验证: subject={subject!r}")

        memory_id = f"mem-{self._id()}"
        self.store.execute(
            "INSERT INTO memory(memory_id, task_id, mem_type, subject, content_json,"
            " provenance_json, ref_count, superseded_by, created_at, valid_until, archived)"
            " VALUES(?,?,?,?,?,?,0,'',?,?,0)",
            (
                memory_id, task_id, mem_type, subject,
                json.dumps({"subject": subject, "claim": claim}, ensure_ascii=False),
                json.dumps({**prov, "verification": verification, "valid_until": valid_until},
                           ensure_ascii=False),
                now, valid_until,
            ),
        )
        for old_id in supersede_ids or []:
            self.store.execute(
                "UPDATE memory SET superseded_by=? WHERE memory_id=?", (memory_id, old_id)
            )
        return memory_id

    # -------------------------------------------------------------- 读
    def retrieve(self, query: str, task_id: str | None = None, *,
                 mem_type: str | None = None, now: str | None = None) -> list[dict]:
        """检索记忆（TTL 过期/归档/被替代条目不返回；词法确定性匹配）。"""
        moment = now or self._now()
        rows = self.store.execute(
            "SELECT * FROM memory WHERE archived=0 AND (superseded_by IS NULL"
            " OR superseded_by='')"
            + (" AND task_id=?" if task_id else "")
            + (" AND mem_type=?" if mem_type else "")
            + " ORDER BY created_at, memory_id",
            tuple(x for x in (task_id, mem_type) if x),
        )
        return [self._entry(r) for r in rows
                if not is_expired(r["valid_until"], moment) and self._matches(r, query)]

    def expired_report(self, task_id: str | None = None, *, now: str | None = None) -> dict:
        """TTL 过期报告（检索不返回的过期条目计数，SPEC-M2-11 EVAL 口径）。"""
        moment = now or self._now()
        rows = self.store.execute(
            "SELECT memory_id, valid_until FROM memory WHERE archived=0"
            + (" AND task_id=?" if task_id else ""),
            (task_id,) if task_id else (),
        )
        expired = [r["memory_id"] for r in rows if is_expired(r["valid_until"], moment)]
        return {"expired": len(expired), "ids": sorted(expired), "now": moment}

    def get(self, memory_id: str) -> dict:
        rows = self.store.execute("SELECT * FROM memory WHERE memory_id=?", (memory_id,))
        if not rows:
            raise KeyError(f"记忆条目不存在: {memory_id}")
        return self._entry(rows[0])

    def reference(self, memory_id: str) -> int:
        """引用计数 +1（检索命中并实际使用时调用；续期依据）。"""
        self.store.execute(
            "UPDATE memory SET ref_count=ref_count+1 WHERE memory_id=?", (memory_id,)
        )
        return self.get(memory_id)["ref_count"]

    def renew(self, memory_id: str, *, extra_days: int | None = None) -> dict:
        """续期：引用计数 > 阈值才允许（SPEC-M2-11）。"""
        entry = self.get(memory_id)
        if entry["ref_count"] <= self.renewal_threshold:
            raise MemoryRenewalRejectedError(
                f"记忆 {memory_id} 引用计数 {entry['ref_count']} 未过阈值"
                f"（>{self.renewal_threshold}），不予续期"
            )
        days = int(extra_days or self.default_ttl_days)
        base = entry["valid_until"] if entry["valid_until"] > entry["created_at"] \
            else entry["created_at"]
        new_until = add_days(base, days)
        self.store.execute(
            "UPDATE memory SET valid_until=? WHERE memory_id=?", (new_until, memory_id)
        )
        return {**entry, "valid_until": new_until}

    def archive_task(self, task_id: str) -> int:
        """任务归档：WORKING 记忆随任务清理（归档，检索不可见）。"""
        return self.store.execute_write(
            "UPDATE memory SET archived=1 WHERE task_id=? AND mem_type='WORKING'"
            " AND archived=0",
            (task_id,),
        )

    # -------------------------------------------------------------- 内部
    def _normalize_content(self, content: Any) -> tuple[str, str]:
        if isinstance(content, dict):
            return str(content.get("subject") or "").strip(), str(content.get("claim") or "").strip()
        if isinstance(content, str) and content.strip():
            return content.strip()[:80], content.strip()
        return "", ""

    def _resolve_ttl(self, mem_type: str, prov: dict, now: str) -> str | None:
        """时效：显式 valid_until / ttl_days 优先，否则类型默认 TTL；WORKING 豁免。"""
        if mem_type == "WORKING":
            return ""
        valid_until = str(prov.get("valid_until") or "").strip()
        if valid_until:
            return valid_until
        ttl = prov.get("ttl_days")
        if ttl is not None:
            return add_days(now, float(ttl))
        if mem_type in _TTL_TYPES:
            return add_days(now, float(self.default_ttl_days))
        return None

    def _conflict_scan(self, mem_type: str, subject: str,
                       claim: str, verification: str) -> list | None:
        """冲突检查：返回应被新条目替代的旧条目 id 列表；存在不可解冲突返回 None。"""
        rows = self.store.execute(
            "SELECT memory_id, content_json, provenance_json FROM memory"
            " WHERE mem_type=? AND subject=? AND archived=0"
            " AND (superseded_by IS NULL OR superseded_by='')",
            (mem_type, subject),
        )
        supersede: list[str] = []
        for row in rows:
            existing = json.loads(row["content_json"])
            existing_prov = json.loads(row["provenance_json"])
            if existing.get("claim") == claim:
                continue  # 同断言重复写入不视为冲突（幂等语义由引用计数表达）
            if existing_prov.get("verification") == "VERIFIED" and verification != "VERIFIED":
                return None  # 未验证新条目不得覆盖 VERIFIED 旧条目
            if verification == "VERIFIED":
                supersede.append(row["memory_id"])
        return supersede

    def _matches(self, row: dict, query: str) -> bool:
        text = str(query or "").strip().lower()
        if not text:
            return True
        content = json.loads(row["content_json"])
        haystack = f"{row['subject'] or ''} {content.get('claim') or ''}".lower()
        return any(token and token in haystack for token in text.split())

    def _entry(self, row: dict) -> dict:
        return {
            "memory_id": row["memory_id"],
            "task_id": row["task_id"],
            "type": row["mem_type"],
            "content": json.loads(row["content_json"]),
            "provenance": json.loads(row["provenance_json"]),
            "ref_count": row["ref_count"],
            "superseded_by": row["superseded_by"] or "",
            "created_at": row["created_at"],
            "valid_until": row["valid_until"] or "",
            "archived": bool(row["archived"]),
        }

    def _reject(self, task_id: str, question: str, reason: str) -> None:
        self.last_rejection = {"question": question, "reason": reason, "task_id": task_id}
        raise _SilentReject()


class _SilentReject(Exception):
    """内部控制流：write 的六问失败统一转 "REJECTED" 返回（01§3.2 契约哨兵）。"""


class KnowledgeBase:
    """Knowledge 条目库：agent 只读检索；注册走 M7 评审通道；变更一律拒绝。"""

    def __init__(
        self,
        store: StateStore,
        *,
        auditor: Auditor | None = None,
        now_fn: Callable[[], str] = utc_now_iso,
        id_gen: Callable[[], str] = new_ulid,
    ) -> None:
        self.store = store
        self.auditor = auditor
        self._now = now_fn
        self._id = id_gen

    def register(self, entry: dict, *, review: dict) -> str:
        """注册 Knowledge 条目（M7 评审通道：review.reviewer/review_ref 必填）。"""
        if not str(review.get("reviewer") or "").strip() or \
                not str(review.get("review_ref") or "").strip():
            raise KnowledgeReadOnlyError(
                "Knowledge 注册必须携带 M7 评审信息（review.reviewer / review.review_ref）"
            )
        entry_id = f"kn-{self._id()}"
        self.store.execute(
            "INSERT INTO knowledge(entry_id, content_json, review_json, registered_at)"
            " VALUES(?,?,?,?)",
            (
                entry_id,
                json.dumps(entry, ensure_ascii=False),
                json.dumps(review, ensure_ascii=False),
                self._now(),
            ),
        )
        return entry_id

    def retrieve(self, query: str, task_id: str | None = None) -> list[dict]:
        """只读检索（词法确定性匹配；与 Memory 检索同口径）。"""
        text = str(query or "").strip().lower()
        rows = self.store.execute(
            "SELECT * FROM knowledge ORDER BY registered_at, entry_id"
        )
        out = []
        for row in rows:
            content = json.loads(row["content_json"])
            haystack = json.dumps(content, ensure_ascii=False).lower()
            if not text or any(token and token in haystack for token in text.split()):
                out.append({
                    "entry_id": row["entry_id"],
                    "content": content,
                    "review": json.loads(row["review_json"]),
                    "registered_at": row["registered_at"],
                })
        return out

    def get(self, entry_id: str) -> dict:
        rows = self.store.execute("SELECT * FROM knowledge WHERE entry_id=?", (entry_id,))
        if not rows:
            raise KeyError(f"Knowledge 条目不存在: {entry_id}")
        row = rows[0]
        return {
            "entry_id": row["entry_id"],
            "content": json.loads(row["content_json"]),
            "review": json.loads(row["review_json"]),
            "registered_at": row["registered_at"],
        }

    def mutate(self, entry_id: str, *, actor: str = "agent",
               change: dict | None = None) -> None:
        """agent 直接变更 Knowledge → 一律拒绝 + 审计事件（SPEC-M2-10）。"""
        error = KnowledgeReadOnlyError(
            f"Knowledge 条目 {entry_id} 对 agent 只读：变更须走 M7 评审通道"
            f"（actor={actor}, change={json.dumps(change or {}, ensure_ascii=False)}）"
        )
        if self.auditor is not None:
            self.auditor(
                "action.policy_decided",
                str(entry_id),
                {
                    "decision": "DENY",
                    "capability": "knowledge.mutate",
                    "actor": actor,
                    "entry_id": str(entry_id),
                    "reason": "Knowledge 只读（变更走 M7 评审）",
                },
                "audit-knowledge",
            )
        raise error
