# -*- coding: utf-8 -*-
"""m3_action.observer · Observation 组装与证据三态（SPEC-M3-09；01 §2.2）。

Evidence 三态规则：
- ``SUCCEEDED`` 必须 intended/issued/observed 三者齐全；
- ``observed`` 只认**环境回读**（SIMULATION=M5 环境回读；REAL=适配器二次读）——
  执行器自报成功不构成 observed；
- 执行器自报 SUCCEEDED 但环境回读未兑现 issued 声明 → 降级 FAILED
  （OBSERVATION_MISMATCH），绝不标 SUCCEEDED。

Observation 文本：结构化序列化 + 中文摘要（给模型看）。
"""
from __future__ import annotations

import json
from typing import Any

__all__ = ["Observer", "OBSERVATION_MISMATCH"]

OBSERVATION_MISMATCH = "OBSERVATION_MISMATCH"


class Observer:
    """证据组装器：独立回读环境（经适配器 readback），不信执行器自报。"""

    def __init__(self) -> None:
        self.observation_seq = 0

    # -------------------------------------------------- 回读
    def readback(self, adapter: Any, env: Any, arguments: dict, action_id: str) -> dict | None:
        """环境回读（adapter.readback 只负责"读哪里"，判定归本 observer）。"""
        if adapter is None or not hasattr(adapter, "readback") or env is None:
            return None
        return adapter.readback(env, arguments, action_id)

    def verify(self, adapter: Any, arguments: dict, issued: dict | None,
               observed: dict | None) -> bool:
        """回读是否兑现 issued 声明（adapter.verify 提供动作核对口径）。"""
        if observed is None:
            return False
        if adapter is None or not hasattr(adapter, "verify"):
            return False
        try:
            return bool(adapter.verify(arguments, issued or {}, observed))
        except Exception:  # noqa: BLE001 - 核对器异常按不通过处理（保守降级）
            return False

    # -------------------------------------------------- 结果组装
    def assemble(self, *, action_id: str, trace_id: str, intended: dict,
                 exec_result: dict | None, observed: dict | None, verify_ok: bool,
                 latency_ms: int = 0) -> dict:
        """组装最终 ActionResult dict（证据三态 + 自报降级）。"""
        self.observation_seq += 1
        exec_status = str((exec_result or {}).get("status", ""))
        issued = (exec_result or {}).get("evidence", {}).get("issued")
        refs = list((exec_result or {}).get("result_refs") or [])

        if exec_status == "SUCCEEDED" and not verify_ok:
            # SPEC-M3-09：自报成功不构成 observed——回读未兑现 → 降级 FAILED
            error = ((exec_result or {}).get("error") or {}).get("code")
            return {
                "action_id": action_id, "status": "FAILED",
                "result_refs": refs,
                "observation": self._text(action_id, "FAILED",
                                          f"环境回读未兑现执行声明（OBSERVATION_MISMATCH）"),
                "evidence": {"intended": intended, "issued": issued,
                             "observed": observed},
                "latency_ms": int(latency_ms), "trace_id": trace_id,
                "error": {"code": OBSERVATION_MISMATCH,
                          "message": (f"执行器自报 SUCCEEDED 但环境回读未确认"
                                      f"（自报错误码={error!r}）；observed 只认环境回读，"
                                      "降级 FAILED（SPEC-M3-09）")},
            }
        if exec_status == "SUCCEEDED":
            return {
                "action_id": action_id, "status": "SUCCEEDED",
                "result_refs": refs,
                "observation": self._text(action_id, "SUCCEEDED", "环境回读确认"),
                "evidence": {"intended": intended, "issued": issued,
                             "observed": observed},
                "latency_ms": int(latency_ms), "trace_id": trace_id,
                "error": None,
            }
        # FAILED / 其他：保留执行器结论（observed 尽量补环境回读）
        error = (exec_result or {}).get("error") or {}
        return {
            "action_id": action_id, "status": exec_status or "FAILED",
            "result_refs": refs,
            "observation": self._text(action_id, exec_status or "FAILED",
                                      str(error.get("message", ""))[:120]),
            "evidence": {"intended": intended, "issued": issued,
                         "observed": observed},
            "latency_ms": int(latency_ms), "trace_id": trace_id,
            "error": {"code": str(error.get("code", "EXECUTION_FAILED")),
                      "message": str(error.get("message", "执行失败"))} if error
            else None,
        }

    @staticmethod
    def _text(action_id: str, status: str, note: str) -> str:
        """Observation 文本（给模型看）：结构化序列化 + 中文摘要。"""
        return json.dumps({
            "action_id": action_id, "status": status,
            "note": note,
        }, ensure_ascii=False)
