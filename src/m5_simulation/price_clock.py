# -*- coding: utf-8 -*-
"""m5_simulation.price_clock · 电价时钟与月度需量滑窗（SPEC-M5-02 + ADDENDUM §C）。

- 电价时段判定**只允许 BUSINESS 时钟读数**（00 §1.4 COMM-TARIF-SYNC；
  01 §8 禁止墙钟判价）——本模块全部以 ``env.clock.clock_start + 仿真秒`` 推导，
  无任何真实时间源引用；
- 时段边界发布 ``price.period_changed {from, to}``（ADDENDUM §C），
  occurred_at 用 BUSINESS 时钟读数（边界时刻精确到秒）；
- 月度需量 = 月内 15min 采样最大值滑窗；跨月切换发布
  ``demand.month_rolled {from_month, to_month, frozen_peak_kw}``（ADDENDUM §C）；
- 需量比值 demand_ratio = 月最大需量 / 合同容量（判据阈值在 REG-TECH
  PHYS-DEMAND，由 alarm_engine 取用，本模块不做阈值判定）。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from contracts import EventType

from .clock import UTC, iso_z, parse_utc
from .env import SimEnv

__all__ = ["PriceClock", "DemandTracker", "period_at", "minute_of_day", "month_key"]

_DAY_MINUTES = 24 * 60


def minute_of_day(hhmm: str) -> int:
    """'HH:MM' → 当天分钟数（'24:00' 视为 1440，仅允许作时段终点）。"""
    hours, _, minutes = str(hhmm).partition(":")
    total = int(hours) * 60 + int(minutes or 0)
    if not 0 <= total <= _DAY_MINUTES:
        raise ValueError(f"非法时刻: {hhmm!r}")
    return total


def month_key(moment: datetime) -> str:
    return f"{moment.year:04d}-{moment.month:02d}"


def period_at(env: SimEnv, sim_elapsed_s: float) -> dict | None:
    """BUSINESS 时刻的电价时段（峰谷判定唯一入口）。

    返回 ``{type, price, start, end}`` 或 None（实例无电价表/未覆盖）。
    """
    schedule = env.price_schedule or {}
    periods = schedule.get("periods") or []
    if not periods:
        return None
    moment = env.clock.clock_start + timedelta(seconds=sim_elapsed_s)
    now = moment.hour * 60 + moment.minute
    for period in periods:
        start = minute_of_day(period["start"])
        end = minute_of_day(period["end"])
        if start <= now < end or (start > end and (now >= start or now < end)):
            # 后者为跨零点时段（通用支持）
            return {"type": period["type"], "price": float(period.get("price", 0.0)),
                    "start": str(period["start"]), "end": str(period["end"])}
    return None


class PriceClock:
    """电价时钟：跟踪当前时段，跨边界发布 ``price.period_changed``。

    无内部随机性；状态只有"上一时段类型"，随 env 重放确定。
    """

    def __init__(self, env: SimEnv) -> None:
        self.env = env
        self.current: dict | None = period_at(env, env.clock.sim_elapsed_s)

    def advance(self, prev_s: float, now_s: float) -> list:
        """推进 [prev_s, now_s)：对每个越过的时段边界发一条事件（边界时刻精确）。"""
        events: list = []
        if not (self.env.price_schedule or {}).get("periods"):
            return events
        prev_business = self.env.clock.clock_start + timedelta(seconds=prev_s)
        now_business = self.env.clock.clock_start + timedelta(seconds=now_s)
        for boundary in self._boundaries_between(prev_business, now_business):
            before = self._period_at_instant(boundary - timedelta(microseconds=1))
            after = self._period_at_instant(boundary)
            if before is None or after is None:
                continue
            if before["type"] != after["type"]:
                events.append(self.env.emit(
                    EventType.PRICE_PERIOD_CHANGED,
                    self.env.park_id,
                    {"from": before["type"], "to": after["type"],
                     "price": after["price"],
                     "boundary": iso_z(boundary)},
                    (boundary - self.env.clock.clock_start).total_seconds(),
                ))
                self.current = after
        tail = self._period_at_instant(now_business)
        if tail is not None:
            self.current = tail
        return events

    # ---------------------------------------------------------------- 内部
    def _period_at_instant(self, moment: datetime) -> dict | None:
        periods = (self.env.price_schedule or {}).get("periods") or []
        now = moment.hour * 60 + moment.minute
        for period in periods:
            start = minute_of_day(period["start"])
            end = minute_of_day(period["end"])
            if start <= now < end or (start > end and (now >= start or now < end)):
                return {"type": period["type"], "price": float(period.get("price", 0.0)),
                        "start": str(period["start"]), "end": str(period["end"])}
        return None

    def _boundaries_between(self, prev: datetime, now: datetime) -> list:
        """(prev, now] 内的全部时段起点时刻（升序；跨日通用）。"""
        boundaries: list = []
        day = prev.replace(hour=0, minute=0, second=0, microsecond=0)
        while day <= now:
            for period in (self.env.price_schedule or {}).get("periods") or []:
                start = minute_of_day(period["start"])
                moment = day + timedelta(minutes=start)
                if prev < moment <= now:
                    boundaries.append(moment)
            day += timedelta(days=1)
        return sorted(set(boundaries))


class DemandTracker:
    """月度需量 15min 滑窗：月内最大值跟踪 + 跨月滚动事件（ADDENDUM §C）。"""

    def __init__(self, env: SimEnv) -> None:
        self.env = env
        start_month = month_key(env.clock.clock_start)
        # 实例历史需量（demand_YYYY_MM 节，数据驱动）作为当月基线
        self.current_month: str = start_month
        self.month_peak_kw: float = float(env.demand_records.get(start_month, 0.0))
        self.frozen_history: dict = dict(env.demand_records)

    @property
    def demand_ratio(self) -> float:
        if not self.env.contract_capacity_kw:
            return 0.0
        return self.month_peak_kw / float(self.env.contract_capacity_kw)

    def sample(self, park_net_kw: float, sim_elapsed_s: float) -> list:
        """录入一个 15min 采样：跨月先发 demand.month_rolled，再更新峰值。"""
        events: list = []
        business = self.env.clock.clock_start + timedelta(seconds=sim_elapsed_s)
        month = month_key(business)
        if month != self.current_month:
            frozen = round(self.month_peak_kw, 3)
            events.append(self.env.emit(
                EventType.DEMAND_MONTH_ROLLED,
                self.env.park_id,
                {"from_month": self.current_month, "to_month": month,
                 "frozen_peak_kw": frozen},
                sim_elapsed_s,
            ))
            self.frozen_history[self.current_month] = frozen
            self.current_month = month
            self.month_peak_kw = float(self.env.demand_records.get(month, 0.0))
        if park_net_kw > self.month_peak_kw:
            self.month_peak_kw = float(park_net_kw)
        return events

    def summary(self) -> dict:
        return {"month": self.current_month, "peak_kw": round(self.month_peak_kw, 3),
                "demand_ratio": round(self.demand_ratio, 4),
                "contract_capacity_kw": self.env.contract_capacity_kw}
