# -*- coding: utf-8 -*-
"""m2_information · UTC 时间戳统一出口。

约定（specs/01-contracts.md §8）：时间戳一律 UTC ISO-8601。
本模块是 m2_information 内唯一接触真实时钟的位置（M5 的 WALL/MONOTONIC 读数
除外）；电价判定与 M2 无关，M2 的时间戳仅用于事件与状态落盘，且所有入口均支持
``now`` 注入以保证 EVAL 可离线确定性复跑。

注意：本文件必须保持不含任何电价语义字样（CI 墙钟扫描口径，EVAL-M5-02-N）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

__all__ = ["utc_now_iso", "normalize_iso", "add_days", "is_expired"]

_FMT = "%Y-%m-%dT%H:%M:%SZ"


def utc_now_iso() -> str:
    """当前 UTC 时间，ISO-8601（秒粒度，Z 后缀）。"""
    return datetime.now(timezone.utc).strftime(_FMT)


def normalize_iso(value) -> str:
    """datetime/字符串 → 规范 UTC ISO-8601 字符串（round-trip 保真）。"""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime(_FMT)
    text = str(value).strip()
    if text.endswith(("z", "Z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime(_FMT)


def add_days(iso: str, days: float) -> str:
    """UTC 时间戳加天数（TTL/续期计算）。"""
    base = datetime.strptime(normalize_iso(iso), _FMT).replace(tzinfo=timezone.utc)
    return (base + timedelta(days=days)).strftime(_FMT)


def is_expired(valid_until: str, now: str) -> bool:
    """有效期比较（valid_until 为空串表示无 TTL，永不过期）。"""
    if not valid_until:
        return False
    return normalize_iso(valid_until) < normalize_iso(now)
