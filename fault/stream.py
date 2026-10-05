# -*- coding: utf-8 -*-
"""fault.stream · 事件流（EventBus）：append-only JSONL，全 UI 时间线唯一数据源。

通道：control（模式开关）/ fault（注入·检测·清除）/ agent（反应步骤流）/
ops（拉闸·倒闸·复位操作）/ telemetry（按需快照，不逐拍写入）。
事件 schema 与 worker-A web/ 的对接契约见 fault/README.md §4。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Optional

__all__ = ["EventBus"]

CHANNELS = ("control", "fault", "agent", "ops", "telemetry")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") \
        + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


class EventBus:
    """线程安全 append-only 事件流：内存 list + 可选 JSONL 落盘 + 订阅回调。"""

    def __init__(self) -> None:
        self._events: list[dict] = []
        self._lock = threading.Lock()
        self._subs: list[Callable[[dict], None]] = []
        self._sink_path: Optional[str] = None

    # ---------------------------------------------------------------- 写
    def append(self, channel: str, etype: str, payload: dict[str, Any],
               sim_s: float = 0.0) -> dict:
        if channel not in CHANNELS:
            raise ValueError(f"未知事件通道: {channel!r}（允许: {CHANNELS}）")
        with self._lock:
            evt = {
                "seq": len(self._events) + 1,
                "ts": utc_now_iso(),
                "sim_s": round(float(sim_s), 3),
                "channel": channel,
                "type": etype,
                "payload": payload,
            }
            self._events.append(evt)
        for sub in list(self._subs):
            try:
                sub(evt)
            except Exception:  # 订阅者异常不阻断事件流
                pass
        return evt

    def attach_jsonl_sink(self, path: str) -> None:
        """此后所有事件追加写 JSONL 文件（UTF-8，一行一事件）。"""
        if self._sink_path is None:
            self._subs.append(self._sink_write)
        self._sink_path = path

    # ---------------------------------------------------------------- 读
    def to_list(self, channel: Optional[str] = None,
                etype: Optional[str] = None) -> list[dict]:
        out = self._events
        if channel is not None:
            out = [e for e in out if e["channel"] == channel]
        if etype is not None:
            out = [e for e in out if e["type"] == etype]
        return list(out)

    def since(self, seq: int) -> list[dict]:
        """前端轮询增量：seq 之后的事件。"""
        return [e for e in self._events if e["seq"] > seq]

    def __len__(self) -> int:
        return len(self._events)

    # ---------------------------------------------------------------- 落盘
    def write_jsonl(self, path: str, channel: Optional[str] = None) -> int:
        evts = self.to_list(channel=channel)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for e in evts:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return len(evts)

    def _sink_write(self, evt: dict) -> None:
        if self._sink_path:
            with open(self._sink_path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(evt, ensure_ascii=False) + "\n")
