# -*- coding: utf-8 -*-
"""m3_action.executor · 幂等执行器（idempotency_key 表，SPEC-M3-08）。

- 同 ``idempotency_key`` 重复请求返回首个结果（含原 action_id 同 status），
  不重复执行；
- 写前日志（write-ahead）：执行副作用**之前**先落 claim 记录；执行器崩溃后
  同 key 重试命中 claim → 不二次执行（SIMULATION 路由下以 M5 状态 diff 验证零
  二次副作用）；
- ``CALLER_PROVIDED_UNIQUE_ARGS`` 策略：同 key 承载不同 (capability, arguments)
  → KEY_CONFLICT 拒绝（幂等键不得复用承载不同负载）。

持久化：``runtime/m3_action/idempotency.jsonl``（record 记录按键覆盖重放）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .clocking import to_jsonable

__all__ = ["IdempotentExecutor", "IdempotencyConflictError"]

_KEY_CONFLICT = "KEY_CONFLICT"


class IdempotencyConflictError(ValueError):
    """幂等键冲突（同 key 承载不同负载）。"""

    def __init__(self, key: str, message: str) -> None:
        self.code = _KEY_CONFLICT
        self.key = key
        super().__init__(f"[{_KEY_CONFLICT}] {message}")


class IdempotentExecutor:
    """幂等执行器（journal 持久化 + claim/complete 两阶段）。"""

    def __init__(self, journal_path: Path, key_policy: Callable[[str], str] | None = None) -> None:
        self.journal_path = Path(journal_path)
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_policy = key_policy  # action_id -> 策略名（CALLER_PROVIDED*）
        self._records: dict[str, dict] = {}
        self.executions = 0  # 实际执行副作用次数（幂等证明用）
        self._replay()

    # -------------------------------------------------- 持久化
    def _replay(self) -> None:
        if not self.journal_path.is_file():
            return
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("kind") == "record":
                self._records[record["key"]] = record

    def _write(self, key: str, result: dict, *, capability: str, arguments: dict,
               action_id: str) -> dict:
        record = {"kind": "record", "key": key, "action_id": action_id,
                  "capability": capability, "arguments": dict(arguments or {}),
                  "result": result}
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._records[key] = record
        return record

    # -------------------------------------------------- 幂等表操作
    def lookup(self, key: str) -> dict | None:
        record = self._records.get(key)
        return None if record is None else dict(record["result"])

    def payload_of(self, key: str) -> dict | None:
        record = self._records.get(key)
        return None if record is None else {"capability": record.get("capability"),
                                            "arguments": record.get("arguments")}

    def claim(self, key: str, *, action_id: str, capability: str, arguments: dict,
              pending_result: dict) -> dict:
        """执行副作用前落 claim（返回 journal 内首个结果）。

        - 新 key → 落 claim 返回之（调用方继续执行）；
        - 已有 key 且策略要求 UNIQUE_ARGS → 校验负载一致，不一致抛冲突；
        - 已有 key（含崩溃遗留的中间态 claim）→ 返回首个结果，调用方不得再执行。
        返回 (record_result, first_time: bool)。
        """
        existing = self._records.get(key)
        if existing is not None:
            policy = (self.key_policy(existing.get("capability", "").split("@", 1)[0])
                      if self.key_policy else "CALLER_PROVIDED")
            if policy == "CALLER_PROVIDED_UNIQUE_ARGS":
                if existing.get("capability") != capability \
                        or existing.get("arguments") != dict(arguments or {}):
                    raise IdempotencyConflictError(
                        key,
                        f"幂等键 {key!r} 已承载 {existing.get('capability')!r} 负载，"
                        f"不得复用于 {capability!r}（CALLER_PROVIDED_UNIQUE_ARGS）")
            return dict(existing["result"]), False
        self._write(key, pending_result, capability=capability,
                    arguments=dict(arguments or {}), action_id=action_id)
        return dict(pending_result), True

    def complete(self, key: str, result: dict) -> dict:
        """执行完成后覆盖首个结果（同 key 后续命中返回终态结果）。"""
        existing = self._records.get(key)
        if existing is None:
            raise KeyError(f"完成未声明的幂等键: {key!r}")
        return self._write(key, result, capability=existing.get("capability", ""),
                           arguments=existing.get("arguments") or {},
                           action_id=result.get("action_id",
                                                existing.get("action_id", "")))["result"]

    # -------------------------------------------------- 统计
    def execution_count(self) -> int:
        return self.executions

    def mark_executed(self) -> None:
        self.executions += 1
