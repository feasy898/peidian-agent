# -*- coding: utf-8 -*-
"""m5_simulation · Simulation（仿真层）：环境模拟器、用户模拟器、场景引擎、四类时间。

specs/M5-simulation.md 全部 SPEC 条款（01–08 + 物理模型）的实现入口；
01 §3.5 冻结 API 在此统一导出：

- ``load_scenario(spec) -> SimEnv``
- ``step(env, action | ENV_TICK) -> (SimEnv, Observation, SimEvents[])``
- ``simulate(action, env) -> (ActionResult, SimEnv)``   # M3 仿真路由目标
- ``persona_step(persona, history) -> UserUtterance``
- ``clock(mode) -> ClockReading``                        # 四类时间
- ``inject(env, fault) -> SimEnv``
- ``run_scenario(spec) -> SimRunResult``                 # 场景引擎一站式

判据纪律（SPEC-M5-08）：告警阈值一律来自 regulations/REG-TECH.yaml（经
m4_semantic 装载），仿真代码零硬编码阈值；电价判定只允许 BUSINESS 时钟
（SPEC-M5-02，01 §8）。
"""
from __future__ import annotations

from .clock import ClockHub, ClockMode, ClockReading, clock
from .env import (
    DEFAULT_STEP_S,
    ENV_TICK,
    DeviceRuntime,
    MeasurementCell,
    SimEnv,
    canonical_spec_dict,
    default_seed,
    load_scenario,
    parse_time_ref,
    spec_manifest_hash,
)
from .physics import MODEL_DEFAULTS, PhysicsEngine, interpolate_shape
from .price_clock import DemandTracker, PriceClock, month_key, period_at
from .alarm_engine import AlarmEngine, aggregate_by_level
from .persona import PersonaSession, UserUtterance, fidelity_check, persona_step
from .injector import FAULT_TYPES, FaultInjector, inject
from .recorder import AUDIT_COLUMNS, RunRecorder, strip_audit_columns
from .scenario import ScenarioEngine, diff_runs, run_scenario, simulate, step

__all__ = [
    # 01 §3.5 冻结 API
    "load_scenario", "step", "simulate", "persona_step", "clock", "inject",
    "run_scenario",
    # env（SPEC-M5-03/07）
    "SimEnv", "DeviceRuntime", "MeasurementCell", "ENV_TICK", "DEFAULT_STEP_S",
    "spec_manifest_hash", "canonical_spec_dict", "default_seed", "parse_time_ref",
    # clock（SPEC-M5-02）
    "ClockHub", "ClockMode", "ClockReading",
    # physics（M5 §2 物理模型）
    "PhysicsEngine", "MODEL_DEFAULTS", "interpolate_shape",
    # price_clock（ADDENDUM §C）
    "PriceClock", "DemandTracker", "period_at", "month_key",
    # alarm_engine（SPEC-M5-08）
    "AlarmEngine", "aggregate_by_level",
    # persona（SPEC-M5-04）
    "PersonaSession", "UserUtterance", "fidelity_check",
    # injector（SPEC-M5-05）
    "FaultInjector", "FAULT_TYPES",
    # recorder（SPEC-M5-06）
    "RunRecorder", "AUDIT_COLUMNS", "strip_audit_columns",
    # scenario
    "ScenarioEngine", "diff_runs",
]
