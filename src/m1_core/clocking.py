# -*- coding: utf-8 -*-
"""m1_core.clocking · 时间助手（执行内核时间域）。

M1 无电价判定义务（01 §8：电价判定只允许 M5 BUSINESS 时钟；本模块不含任何
电价语义）。执行内核的"当前时刻"是运行域量：
- EVAL/黄金集一律显式注入 ``now_fn``（确定性重放，不触墙钟）；
- 生产缺省 ``now_iso()`` 是 m1_core 内唯一真实时间源读取位（集中于此，
  便于审计与 CI 扫描；与 m2_information.timestamps / m3_action.clocking 同口径）。
"""
from __future__ import annotations

from datetime import datetime, timezone

__all__ = ["parse_iso", "iso_z", "normalize_ts", "now_iso"]


def parse_iso(value: str | datetime) -> datetime:
    """UTC ISO-8601（或 datetime）→ UTC datetime（contracts 两种时间戳形态都收）。"""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_z(value: datetime) -> str:
    """datetime → UTC ISO-8601（Z 后缀，秒粒度）。"""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_ts(value: str | datetime) -> str:
    """时间戳归一为 UTC ISO-8601 字符串（YAML 未加引号会解析出 datetime）。"""
    return value if isinstance(value, str) else iso_z(value)


def now_iso() -> str:  # pragma: no cover - 仅生产缺省；EVAL 一律注入
    """墙钟当前时刻（UTC ISO-8601）。

    m1_core 唯一真实时间源读取位：只服务执行内核的缺省时间戳（事件 occurred_at、
    预算租约的 deadline/时段比较缺省基准），与电价判定无关（01 §8：判价只允许
    M5 BUSINESS 时钟）。
    """
    return iso_z(datetime.now(timezone.utc))
