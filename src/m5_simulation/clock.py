# -*- coding: utf-8 -*-
"""m5_simulation.clock · 四类时间服务（specs/M5-simulation.md SPEC-M5-02）。

四类时间（01 §3.5 ``clock(mode) -> ClockReading``）：

- ``BUSINESS``    业务日历时钟：由仿真时间轴（clock_start + 已推进仿真秒数）派生，
                  是**峰谷电价判定的唯一依据**（00 §1.4 COMM-TARIF-SYNC；
                  01 §8 禁止用墙钟判价）。可暂停/倍速（随仿真轴）。
- ``SIM_LOGICAL`` 仿真步时钟：自场景起点累计的仿真秒数（15min 步长推进）。可暂停/倍速。
- ``MONOTONIC``   单调时钟（性能计时）：``time.get_monotonic()`` 只读，不可暂停/倍速。
- ``WALL``        墙钟（审计）：UTC 当前时刻只读，不可暂停/倍速；仅用于审计/计量，
                  任何业务判定（电价/需量/告警）不得引用。

倍速语义：``speed`` 为"每墙钟秒对应的仿真秒数"。离散推进（``advance_sim``，
ENV_TICK 物理步）不受 speed 影响（步长即仿真时间）；连续推进
（``advance_wall``，实时交互模式）按 speed 换算为仿真时间。暂停对两者同时生效
（BUSINESS/SIM_LOGICAL 共享同一仿真时间轴：暂停即双双停走，恢复即同步续走）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

__all__ = [
    "ClockMode",
    "ClockReading",
    "ClockHub",
    "clock",
    "UTC",
]

UTC = timezone.utc


class ClockMode(str, Enum):
    """四类时间模式（封闭集，字面量与 01 §3.5 一致）。"""

    BUSINESS = "BUSINESS"
    SIM_LOGICAL = "SIM_LOGICAL"
    MONOTONIC = "MONOTONIC"
    WALL = "WALL"


def iso_z(value: datetime) -> str:
    """UTC datetime → ISO-8601 'Z' 后缀字符串（横切约定：时间戳一律 UTC ISO-8601）。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ClockReading:
    """一次时钟读数（四类时间对齐表的一行）。"""

    mode: str              # BUSINESS / SIM_LOGICAL / MONOTONIC / WALL
    business_at: str | None   # BUSINESS 读数（UTC ISO-8601；仅 BUSINESS 类读数有值）
    sim_elapsed_s: float | None  # SIM_LOGICAL 读数（累计仿真秒）
    monotonic_ms: float | None   # MONOTONIC 读数（毫秒）
    wall_at: str | None      # WALL 读数（UTC ISO-8601；审计专用）
    paused: bool            # 仿真轴当前是否暂停（只对 BUSINESS/SIM_LOGICAL 有意义）
    speed: float            # 当前倍速（墙钟秒 → 仿真秒 的换算系数）

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "business_at": self.business_at,
            "sim_elapsed_s": self.sim_elapsed_s,
            "monotonic_ms": self.monotonic_ms,
            "wall_at": self.wall_at,
            "paused": self.paused,
            "speed": self.speed,
        }


class ClockHub:
    """仿真时间轴（BUSINESS/SIM_LOGICAL 的共同底座）+ 只读真实时钟读数。

    - ``clock_start``：场景起点（BUSINESS 日历时刻，UTC）；
    - ``sim_elapsed_s``：SIM_LOGICAL 累计仿真秒；
    - ``speed``：倍速；``paused``：暂停标记；
    - MONOTONIC/WALL 每次读取即时取真实时钟，只读、不受暂停/倍速影响。
    """

    def __init__(self, clock_start: datetime, speed: float = 1.0) -> None:
        if not isinstance(clock_start, datetime):
            raise TypeError(f"clock_start 必须为 datetime，实际 {type(clock_start).__name__}")
        if clock_start.tzinfo is None:
            clock_start = clock_start.replace(tzinfo=UTC)
        self.clock_start = clock_start.astimezone(UTC)
        if not isinstance(speed, (int, float)) or isinstance(speed, bool) or speed <= 0:
            raise ValueError(f"speed 必须为正数（墙钟秒→仿真秒），实际 {speed!r}")
        self.speed = float(speed)
        self.sim_elapsed_s = 0.0
        self.paused = False

    # ------------------------------------------------ 仿真轴推进（可暂停/倍速）
    def advance_sim(self, seconds: float) -> float:
        """离散推进仿真时间（ENV_TICK 步长）。暂停时不动，返回实际推进量。"""
        if seconds < 0:
            raise ValueError(f"仿真时间不可回拨：{seconds!r}")
        if self.paused:
            return 0.0
        self.sim_elapsed_s += float(seconds)
        return float(seconds)

    def advance_wall(self, wall_seconds: float) -> float:
        """连续推进（实时交互）：仿真推进量 = 墙钟秒 × speed。暂停时不动。"""
        if wall_seconds < 0:
            raise ValueError(f"墙钟时间不可回拨：{wall_seconds!r}")
        if self.paused:
            return 0.0
        advanced = float(wall_seconds) * self.speed
        self.sim_elapsed_s += advanced
        return advanced

    def pause(self) -> None:
        """暂停 BUSINESS/SIM_LOGICAL（MONOTONIC/WALL 为只读真实源，不受影响）。"""
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def set_speed(self, speed: float) -> None:
        """调整倍速（正数）。只影响后续 advance_wall 的换算，不改动已推进量。"""
        if not isinstance(speed, (int, float)) or isinstance(speed, bool) or speed <= 0:
            raise ValueError(f"speed 必须为正数，实际 {speed!r}")
        self.speed = float(speed)

    # ------------------------------------------------ 读数
    def business_now(self) -> datetime:
        """BUSINESS 读数：clock_start + 累计仿真秒（峰谷判定唯一依据）。"""
        return self.clock_start + timedelta(seconds=self.sim_elapsed_s)

    def reading(self, mode: ClockMode | str) -> ClockReading:
        mode = ClockMode(mode)
        if mode is ClockMode.BUSINESS:
            return ClockReading("BUSINESS", iso_z(self.business_now()), None, None, None,
                                self.paused, self.speed)
        if mode is ClockMode.SIM_LOGICAL:
            return ClockReading("SIM_LOGICAL", None, self.sim_elapsed_s, None, None,
                                self.paused, self.speed)
        if mode is ClockMode.MONOTONIC:
            return ClockReading("MONOTONIC", None, None, time.monotonic() * 1000.0, None,
                                self.paused, self.speed)
        return ClockReading("WALL", None, None, None,
                            iso_z(datetime.now(UTC)), self.paused, self.speed)

    def aligned_row(self) -> dict:
        """四类时间一次对齐读数（TIMELINE 对齐表的一行；monotonic/wall 为审计列）。"""
        business = self.reading(ClockMode.BUSINESS)
        logical = self.reading(ClockMode.SIM_LOGICAL)
        monotonic = self.reading(ClockMode.MONOTONIC)
        wall = self.reading(ClockMode.WALL)
        return {
            "business_at": business.business_at,
            "sim_elapsed_s": logical.sim_elapsed_s,
            "monotonic_ms": monotonic.monotonic_ms,
            "wall_at": wall.wall_at,
        }


def clock(mode: ClockMode | str, service: ClockHub | None = None) -> ClockReading:
    """01 §3.5 冻结 API：``clock(mode) -> ClockReading``。

    - MONOTONIC / WALL：无状态只读，``service`` 可空；
    - BUSINESS / SIM_LOGICAL：必须携带 ``service``（仿真时间轴），
      缺省抛 ``ValueError``（业务时钟不落回墙钟——电价判定红线）。
    """
    mode = ClockMode(mode)
    if mode in (ClockMode.BUSINESS, ClockMode.SIM_LOGICAL) and service is None:
        raise ValueError(
            f"{mode.value} 读数必须提供 ClockHub（仿真时间轴）；"
            "BUSINESS/SIM_LOGICAL 不存在无源的缺省值（禁止以墙钟兜底，01 §8）"
        )
    if service is None:
        return ClockHub(clock_start=datetime.now(UTC)).reading(mode)
    return service.reading(mode)


def parse_utc(value: Any) -> datetime:
    """字符串/datetime → UTC datetime（容错 pyyaml 把未加引号时间戳解析为 datetime）。"""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
