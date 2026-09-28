# -*- coding: utf-8 -*-
"""m3_action.clocking · 时间助手（审批超时域）。

M3 无电价判定义务（01 §8 电价判定只允许 M5 BUSINESS 时钟；本模块不含任何
电价语义）。审批超时的缺省"当前时刻"是运行域审计量：
- EVAL/黄金集一律显式传 ``now``（确定性重放，不触墙钟）；
- 生产缺省 ``now_iso()`` 是本模块唯一墙钟读取位（集中于此，便于审计与扫描）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

__all__ = ["parse_iso", "iso_add_seconds", "seconds_between", "now_iso", "iso_z",
           "to_jsonable", "normalize_ts"]


def parse_iso(value: str | datetime) -> datetime:
    """UTC ISO-8601（或 datetime）→ UTC datetime（contracts 两种时间戳形态都收）。"""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_ts(value: str | datetime) -> str:
    """时间戳归一为 UTC ISO-8601 字符串（YAML 未加引号会解析出 datetime）。"""
    return value if isinstance(value, str) else iso_z(value)


def to_jsonable(value):
    """递归转 JSON 可序列化形态（datetime → UTC ISO-8601 字符串）。"""
    if isinstance(value, datetime):
        return iso_z(value)
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def iso_z(value: datetime) -> str:
    """datetime → UTC ISO-8601（Z 后缀，秒粒度）。"""
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_add_seconds(value: str, seconds: float) -> str:
    return iso_z(parse_iso(value) + timedelta(seconds=seconds))


def seconds_between(later: str, earlier: str) -> float:
    """later - earlier（秒）。"""
    return (parse_iso(later) - parse_iso(earlier)).total_seconds()


def now_iso() -> str:  # pragma: no cover - 仅生产缺省；EVAL 不触
    """墙钟当前时刻（UTC ISO-8601）。

    本模块唯一真实时间源读取位：只服务审批超时的缺省比较与事件时间戳缺省，
    与电价判定无关（01 §8：判价只允许 M5 BUSINESS 时钟）。
    """
    return iso_z(datetime.now(timezone.utc))
