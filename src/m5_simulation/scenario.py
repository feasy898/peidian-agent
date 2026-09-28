# -*- coding: utf-8 -*-
"""m5_simulation.scenario · 场景引擎（01 §3.5 冻结 API 的实现载体）。

一站式 ``run_scenario(spec) -> SimRunResult``：装载 → 驱动（ENV_TICK 节拍）→
采集（三层证据 + 轨迹）→ 组装结果。

- ``load_scenario(spec) -> SimEnv``（env.py）；
- ``step(env, action|ENV_TICK, engine) -> (env, observation, events)``；
- ``simulate(action, env) -> (ActionResult, SimEnv)``：M3 仿真路由目标
  （SPEC-M5-03：写动作改变 env 后可回读 observed；读动作返回带时标快照）；
- ``run_scenario(spec) -> SimRunResult``：确定性重放（同 seed 同轨迹，
  SPEC-M5-01）；场景隔离（每 run 独享 env，SPEC-M5-07）。

SUT 桩链（dev-02b 遥控场景）：计划事件 ``action.request`` → 本体缺省 Policy
（数据驱动）→ ASK 则发 ``approval.requested``，persona GRANT/DENY 或
``interactions.timeout_s``（墙钟秒 × speed 换算为仿真秒）决定终态；
``execute.remote_control`` 无已签发操作票一律拒绝（SAFE-TWO-TICKET 红线）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from contracts import (
    ActionRequest,
    EventType,
    ScenarioSpec,
    SimRunResult,
    ContractValidationError,
)

from .alarm_engine import AlarmEngine
from .clock import ClockHub, iso_z
from .env import ENV_TICK, SimEnv, default_seed, load_scenario, parse_time_ref, spec_manifest_hash
from .injector import FaultInjector
from .persona import PersonaSession
from .physics import MODEL_DEFAULTS, PhysicsEngine
from .price_clock import DemandTracker, PriceClock, period_at
from .recorder import RunRecorder, strip_audit_columns

__all__ = [
    "ScenarioEngine",
    "run_scenario",
    "step",
    "simulate",
    "diff_runs",
    "ENV_TICK",
]

#: 安全步数上限（防 stop_conditions 配置失误导致死循环）
MAX_TICKS = 20000

#: 动作能力 → 缺省策略查表键（ontology/actions.yaml 数据驱动，禁止硬编码策略）
_DENY_ALWAYS_HINT = {"modify.protection_setting", "modify.asset_history", "bypass.approval"}


# ===========================================================================
# simulate：M3 仿真路由目标（SPEC-M5-03）
# ===========================================================================
def simulate(action: ActionRequest | Mapping, env: SimEnv) -> tuple:
    """执行一个动作并回读环境（01 §3.5：``simulate(action, env) -> (ActionResult, SimEnv)``）。

    - 读类（query.*）：返回带时标快照（含 stale 标志），observed=环境读数；
    - 写类：先变更 env 再回读（observed 必须来自环境回读，01 §2.2）；
    - ``execute.remote_control`` 无已签发操作票 → FAILED（SAFE-TWO-TICKET）；
    - 冻结 DENY 动作（modify.*/bypass.approval）→ 拒绝执行（缺省 Policy 永久 DENY）；
    - 未登记动作 → FAILED（UNREGISTERED_CAPABILITY，红线 1）。
    """
    if not isinstance(action, ActionRequest):
        try:
            action = ActionRequest.from_dict(action)
        except ContractValidationError:
            action_id, capability = _loose_action_identity(action)
            action = _synthetic_request(action_id, capability, action)
    capability_id = action.capability.split("@", 1)[0]
    arguments = dict(action.arguments or {})
    intended = {
        "action_id": action.action_id, "capability": action.capability,
        "actor_user": action.actor.user, "purpose": action.purpose,
        "arguments": arguments,
    }
    now_s = env.clock.sim_elapsed_s

    known = capability_id in (env.ontology.actions or {})
    deny_locked = capability_id in _DENY_ALWAYS_HINT

    def _fail(code: str, message: str, issued: dict | None = None) -> tuple:
        result = _action_result(
            action, "FAILED", [], f"[{code}] {message}",
            evidence={"intended": intended, "issued": issued, "observed": None},
            error={"code": code, "message": message},
            # SIMULATION 模式延迟为确定性常数（真实时延计量属 MONOTONIC 审计域，
            # 由 M3 REAL 路由负责；此处禁止墙钟/单调钟泄漏进重放轨迹，SPEC-M5-01）
            latency_ms=0,
        )
        return result, env

    if not known:
        return _fail("UNREGISTERED_CAPABILITY",
                     f"动作未在本体登记: {capability_id!r}（红线：未注册能力禁止执行）")
    if deny_locked:
        default_policy = (env.ontology.actions[capability_id] or {}).get("default_policy")
        return _fail(
            "POLICY_DENIED",
            f"{capability_id} 缺省 Policy={default_policy}（永久 DENY），仿真路由同样拒绝",
        )

    # ---- 读类
    if capability_id == "query.measurement":
        device = arguments.get("device")
        snapshot = env.measurement_snapshot(device)
        issued = {"scanned_device": device or "*", "cells": len(snapshot)}
        return _succeed(action, intended, issued,
                        {"measurements": snapshot, "count": len(snapshot),
                         "business_at": iso_z(env.clock.business_now())},
                        observation="量测快照（含时标/质量标志）"), env
    if capability_id == "query.asset":
        device = env.devices.get(str(arguments.get("device", "")))
        if device is None:
            return _fail("NO_SUCH_DEVICE", f"设备不存在: {arguments.get('device')!r}")
        issued = {"device": device.id}
        return _succeed(action, intended, issued,
                        {"device": device.id, "type": device.type,
                         "attributes": device.attributes, "state": device.state},
                        observation=f"台账快照 {device.id}"), env
    if capability_id == "query.regulation":
        rule_id = str(arguments.get("rule_id", ""))
        entry = _find_rule(env, rule_id)
        if entry is None:
            return _fail("NO_SUCH_RULE", f"规则 ID 不存在: {rule_id!r}")
        issued = {"rule_id": rule_id}
        return _succeed(action, intended, issued, {"rule": entry},
                        observation=f"规程条款 {rule_id}"), env

    # ---- 写类（先变更 env，再回读 observed）
    if capability_id == "execute.remote_control":
        device = env.devices.get(str(arguments.get("device", "")))
        if device is None:
            return _fail("NO_SUCH_DEVICE", f"设备不存在: {arguments.get('device')!r}")
        order_code = str(arguments.get("switch_order", "") or "")
        order = env.switch_orders.get(order_code)
        if order is None or order.get("status") != "ISSUED":
            return _fail("NO_SWITCH_ORDER",
                         f"遥控缺少已签发操作票: {order_code!r}（SAFE-TWO-TICKET 红线）")
        operation = str(arguments.get("operation", "OPEN")).upper()
        target_state = "OPEN" if operation == "OPEN" else "CLOSED"
        issued = {"device": device.id, "operation": operation, "switch_order": order_code,
                  "step": arguments.get("step", 1)}
        env.set_breaker(device.id, target_state, now_s, reason=f"遥控{operation}（操作票 {order_code}）")
        if device.type == "Transformer":
            # 变压器遥控分闸 → 退出运行（冷备）；合闸 → 恢复运行
            if target_state == "OPEN" and device.state == "RUNNING":
                env.set_device_state(device.id, "COLD_STANDBY", now_s, reason="遥控分闸退出")
            elif target_state == "CLOSED" and device.state != "RUNNING":
                env.set_device_state(device.id, "RUNNING", now_s, reason="遥控合闸恢复")
        readback_device = env.devices.get(device.id)
        observed = {"device": device.id, "breaker_state": readback_device.breaker_state,
                    "device_state": readback_device.state, "ts": env.iso_at(now_s)}
        order["status"] = "COMPLETED"
        order.setdefault("executed", []).append({"device": device.id, "operation": operation})
        return _succeed(action, intended, issued, observed,
                        observation=f"遥控{operation} {device.id} 完成（环境回读确认）",
                        refs=[order_code]), env
    if capability_id == "execute.capacitor_switch":
        device = env.devices.get(str(arguments.get("device", "")))
        if device is None:
            return _fail("NO_SUCH_DEVICE", f"设备不存在: {arguments.get('device')!r}")
        target = str(arguments.get("state", "ON")).upper()
        issued = {"device": device.id, "state": target}
        previous = device.attributes.get("state")
        device.attributes["state"] = target
        env.emit(EventType.MEASUREMENT_UPDATED, device.id,
                 {"quantity": "capacitor_state", "from": previous, "to": target,
                  "reason": "execute.capacitor_switch"}, now_s)
        observed = {"device": device.id, "state": device.attributes.get("state"),
                    "ts": env.iso_at(now_s)}
        return _succeed(action, intended, issued, observed,
                        observation=f"电容投切 {device.id} → {target}（环境回读确认）",
                        ), env
    if capability_id == "create.switch_order":
        code = str(arguments.get("code", "") or f"SO-{env.next_event_id()}")
        env.switch_orders[code] = {
            "code": code, "status": str(arguments.get("status", "ISSUED")),
            "steps": list(arguments.get("steps") or []),
            "devices": list(arguments.get("devices") or []),
            "issuer": str(arguments.get("issuer", "")),
        }
        issued = {"code": code}
        return _succeed(action, intended, issued,
                        {"switch_order": code, "status": env.switch_orders[code]["status"]},
                        observation=f"操作票 {code} 登记（状态 {env.switch_orders[code]['status']}）",
                        refs=[code]), env
    if capability_id in ("create.work_order", "create.inspection_record", "write.report"):
        marker = {"capability": capability_id, "arguments": arguments,
                  "recorded_at": env.iso_at(now_s)}
        env.artifacts[action.action_id] = marker
        issued = {"marker": action.action_id}
        return _succeed(action, intended, issued, marker,
                        observation=f"{capability_id} 已登记（仿真侧产物标记）",
                        refs=[action.action_id]), env
    if capability_id.startswith(("analyze.",)):
        issued = {"capability": capability_id, "args": arguments}
        observed = {"note": "简化物理口径的分析回执（精度边界见 M5 §2）",
                    "arguments": arguments, "business_at": env.iso_at(now_s)}
        return _succeed(action, intended, issued, observed,
                        observation=f"{capability_id} 分析回执", ), env

    return _fail("SIM_ROUTE_UNSUPPORTED", f"仿真路由未实现该动作: {capability_id!r}")


def _loose_action_identity(action: Mapping) -> tuple:
    payload = dict(action or {})
    return (str(payload.get("action_id") or f"act-{payload.get('capability', 'x')}"),
            str(payload.get("capability") or "unknown@v1"))


def _synthetic_request(action_id: str, capability: str, payload: Mapping) -> ActionRequest:
    """宽松输入 → 契约 ActionRequest（调用方只给 {capability, arguments} 的简化形态）。"""
    payload = dict(payload or {})
    return ActionRequest.from_dict({
        "action_id": action_id,
        "task_id": str(payload.get("task_id", "task-sim")),
        "turn": int(payload.get("turn", 1)),
        "capability": capability if "@" in capability else f"{capability}@v1",
        "actor": {"user": str(payload.get("user", "OP-001")),
                  "agent": str(payload.get("agent", "park-agent@dev"))},
        "purpose": str(payload.get("purpose", "仿真路由执行")),
        "arguments": dict(payload.get("arguments") or {}),
        "risk": {"level": str(payload.get("risk_level", "LOW")), "reversible": True},
        "idempotency_key": str(payload.get("idempotency_key", action_id)),
        "requested_at": str(payload.get("requested_at")
                            or "2026-09-15T00:00:00Z"),
    })


def _action_result(action, status, refs, observation, *, evidence, error=None,
                   latency_ms: int) -> dict:
    return {
        "action_id": action.action_id,
        "status": status,
        "result_refs": list(refs),
        "observation": observation,
        "evidence": evidence,
        "latency_ms": int(latency_ms),
        "trace_id": getattr(action, "trace_id", None) or f"trace-{action.action_id}",
        "error": error,
    }


def _succeed(action, intended, issued, observed, *, observation,
             refs=None) -> dict:
    """构造 SUCCEEDED ActionResult dict（evidence 三态齐全：intended/issued/observed）。

    SIMULATION 模式 latency_ms 为确定性常数 0（SPEC-M5-01：重放轨迹不得含
    真实时间源测量值；真实时延由 MONOTONIC 审计域另行计量）。
    """
    return _action_result(
        action, "SUCCEEDED", refs or [], observation,
        evidence={"intended": intended, "issued": issued, "observed": observed},
        latency_ms=0,
    )


def _find_rule(env: SimEnv, rule_id: str) -> dict | None:
    for data in (env.ontology.regulations or {}).values():
        for item in (data or {}).get("rules") or []:
            if item.get("id") == rule_id:
                return item
    return None


# ===========================================================================
# 场景引擎
# ===========================================================================
class ScenarioEngine:
    """驱动一个场景直至停止条件，产出 SimRunResult。"""

    def __init__(self, spec: ScenarioSpec | Mapping, *, seed: str | None = None,
                 repo_root: Path | str | None = None, persist: bool = True,
                 model_params: Mapping | None = None,
                 env: SimEnv | None = None) -> None:
        """``env``：直接给定已构建环境（perf/复用路径；缺省按 spec 装载）。"""
        if not isinstance(spec, ScenarioSpec):
            spec = ScenarioSpec.from_dict(spec)
        self.spec = spec
        self.manifest_hash = spec_manifest_hash(spec)
        self.env = env if env is not None else load_scenario(
            self.spec, seed=seed, repo_root=repo_root, model_params=model_params)
        self.seed = seed or self.env.seed or default_seed(self.manifest_hash)
        self.env.seed = self.seed
        params = dict(MODEL_DEFAULTS)
        params.update(self.env.model_params or {})
        self.physics = PhysicsEngine(params)
        self.price_clock = PriceClock(self.env)
        self.demand = DemandTracker(self.env)
        self.alarm_engine = AlarmEngine(self.env)
        self.injector = FaultInjector(self.env,
                                      debounce_s=float(params.get("debounce_s", 2.0)))
        self.persona = PersonaSession.from_spec(self.spec.user_model,
                                                self.env.clock.clock_start)
        self.tick_count = 0
        self.last_observation: dict = {}
        self.pending_approval: dict | None = None
        self.approval_age_s: float = 0.0
        self.temp_ramps: list[dict] = []
        self._planned = self._plan_events()
        self.injector.plan(self.spec.environment.injections)
        self.recorder = None
        if persist:
            run_dir = self._repo_root(repo_root) / "runtime" / "runs" / self.env.run_id
            self.recorder = RunRecorder(run_dir, aligned_row_fn=self.env.clock.aligned_row)
        self.outcome = {"status": "COMPLETED",
                        "evidence_summary": "", "completion_level": 3}

    # ------------------------------------------------ 计划
    @staticmethod
    def _repo_root(repo_root: Path | str | None) -> Path:
        if repo_root is not None:
            return Path(repo_root)
        return Path(__file__).resolve().parents[2]

    def _plan_events(self) -> list:
        clock_start = self.env.clock.clock_start
        planned = []
        for index, event in enumerate(self.spec.events):
            at_abs = parse_time_ref(event.at, clock_start)
            planned.append({
                "index": index, "at_s": (at_abs - clock_start).total_seconds(),
                "business_at": iso_z(at_abs), "type": event.type,
                "subject": event.subject, "params": dict(event.params or {}),
                "done": False,
            })
        planned.sort(key=lambda p: (p["at_s"], p["index"]))
        return planned

    def _stop_state(self) -> dict:
        """解析 stop_conditions（未识别条目忽略；缺省 duration 24h）。"""
        state = {"duration_s": 24 * 3600.0, "max_ticks": None, "need_script_done": False,
                 "need_actions_done": False}
        for entry in self.spec.constraints.stop_conditions or []:
            key, _, value = str(entry).partition(":")
            key = key.strip()
            if key == "duration_h":
                state["duration_s"] = float(value) * 3600.0
            elif key == "duration_s":
                state["duration_s"] = float(value)
            elif key == "max_ticks":
                state["max_ticks"] = int(value)
            elif key == "script_done":
                state["need_script_done"] = True
            elif key == "actions_done":
                state["need_actions_done"] = True
        return state

    def _stopped(self, state: dict) -> bool:
        elapsed = self.env.clock.sim_elapsed_s
        if elapsed >= state["duration_s"] and not state["need_script_done"]:
            return True
        if state["need_script_done"]:
            pending_planned = any(not p["done"] for p in self._planned)
            pending_faults = self.injector.pending_after(elapsed)
            if (self.persona.exhausted and not pending_planned and not pending_faults
                    and self.pending_approval is None
                    and elapsed >= state["duration_s"]):
                return True
        if state["max_ticks"] is not None and self.tick_count >= state["max_ticks"]:
            return True
        return elapsed >= state["duration_s"] and self.tick_count >= MAX_TICKS

    # ------------------------------------------------ 节拍
    def tick(self) -> tuple:
        """推进一个 ENV_TICK：注入/事件 → 物理 → 电价 → 需量 → 告警 → persona。"""
        env = self.env
        prev_s = env.clock.sim_elapsed_s
        now_s = prev_s + env.step_s
        env.clock.advance_sim(env.step_s)
        self.tick_count += 1
        env.event_buffer = []

        # 1) 到期故障注入
        self.injector.apply_due(prev_s, now_s)
        # 2) 到期计划事件
        self._apply_planned_events(prev_s, now_s)
        # 3) 物理推进
        summary = self.physics.step(env, now_s)
        # 4) 电价时段边界（ADDENDUM §C）
        self.price_clock.advance(prev_s, now_s)
        current_period = period_at(env, now_s)
        if current_period is not None:
            summary["price_period"] = current_period["type"]
            summary["price"] = current_period["price"]
        # 5) 需量 15min 滑窗（ADDENDUM §C）
        self.demand.sample(summary["park_net_kw"], now_s)
        env.demand_window = self.demand.summary()
        # 6) 规程阈值告警（含 demand_ratio）
        self.alarm_engine.evaluate(now_s,
                                   extra_metrics={"demand_ratio": self.demand.demand_ratio})
        # 7) persona 到期输出 + 审批链
        self._persona_due(now_s)
        # 8) 审批超时（COMM_LOSS 窗口内不放行 → 超时语义）
        self._approval_timeout_check(now_s)

        observation = {
            "tick": self.tick_count, "sim_elapsed_s": now_s,
            "business_at": summary["business_at"],
            "park_net_kw": summary["park_net_kw"],
            "price_period": summary.get("price_period"),
            "demand": env.demand_window,
            "events": len(env.event_buffer),
        }
        self.last_observation = observation
        if self.recorder is not None:
            self.recorder.timeline_row(
                "TICK",
                f"park_net={summary['park_net_kw']}kW period={summary.get('price_period')}",
                now_s, summary["business_at"], payload={
                    "park_gross_kw": summary["park_gross_kw"],
                    "pv_out_kw": summary["pv_out_kw"],
                    "transformer_load_rate": summary["transformer_load_rate"],
                    "demand": env.demand_window,
                })
            self._record_state_transitions(prev_s, now_s)
        return env, observation, list(env.event_buffer)

    def _apply_planned_events(self, prev_s: float, now_s: float) -> None:
        env = self.env
        for plan in self._planned:
            if plan["done"] or not (prev_s < plan["at_s"] <= now_s):
                continue
            plan["done"] = True
            etype, subject, params = plan["type"], plan["subject"], plan["params"]
            if etype == "load.set":
                until = params.get("duration_s")
                env.load_overrides[subject] = {
                    "kw": float(params.get("kw", 0.0)),
                    "until_s": (plan["at_s"] + float(until)) if until is not None else None,
                    "set_at_s": plan["at_s"],
                }
                env.emit(EventType.GRID_EVENT, subject,
                         {"kind": "load_override", "kw": params.get("kw"),
                          "duration_s": until}, plan["at_s"])
                if self.recorder is not None:
                    self.recorder.state_transition(subject, "load_kw", None,
                                                   params.get("kw"), plan["at_s"],
                                                   plan["business_at"], reason="load.set")
            elif etype == "load.scale":
                until = params.get("duration_s")
                factor = float(params.get("factor", 1.0))
                env.load_overrides[subject] = {
                    "kw": self._scaled_kw(subject, factor), "scale_factor": factor,
                    "until_s": (plan["at_s"] + float(until)) if until is not None else None,
                    "set_at_s": plan["at_s"],
                }
                env.emit(EventType.GRID_EVENT, subject,
                         {"kind": "load_scale", "factor": factor}, plan["at_s"])
            elif etype == "device.temp_rise":
                self.temp_ramps.append({
                    "target": subject,
                    "rate_c_per_h": float(params.get("rate_c_per_h", 0.0)),
                    "from_s": plan["at_s"],
                    "until_s": (plan["at_s"] + float(params["duration_s"]))
                               if params.get("duration_s") is not None else None,
                    "cap_c": float(params["cap_c"]) if params.get("cap_c") is not None else None,
                })
                env.emit(EventType.GRID_EVENT, subject,
                         {"kind": "temp_rise", "rate_c_per_h": params.get("rate_c_per_h")},
                         plan["at_s"])
            elif etype == "thd.set":
                device = env.devices.get(subject)
                if device is not None:
                    device.thd_override = float(params.get("value", 0.0))
                env.emit(EventType.MEASUREMENT_UPDATED, subject,
                         {"quantity": "thd_u", "set": params.get("value"),
                          "reason": "thd.set"}, plan["at_s"])
            elif etype == "soc.set":
                device = env.devices.get(subject)
                if device is not None and device.soc is not None:
                    device.soc = float(params.get("value", device.soc))
                env.emit(EventType.MEASUREMENT_UPDATED, subject,
                         {"quantity": "soc", "set": params.get("value"),
                          "reason": "soc.set"}, plan["at_s"])
            elif etype == "grid.event":
                env.emit(EventType.GRID_EVENT, subject, dict(params.get("payload") or {}),
                         plan["at_s"])
            elif etype == "action.request":
                self._sut_action_request(plan)
            else:
                env.emit(EventType.GRID_EVENT, subject,
                         {"kind": "planned_event", "event_type": etype}, plan["at_s"])

        # 温度缓升坡道推进（每 tick 累计漂移，cap 封顶）
        for ramp in self.temp_ramps:
            device = env.devices.get(ramp["target"])
            if device is None:
                continue
            horizon = now_s if ramp["until_s"] is None else min(now_s, ramp["until_s"])
            if horizon <= ramp["from_s"]:
                continue
            drift = ramp["rate_c_per_h"] * (horizon - ramp["from_s"]) / 3600.0
            if ramp["cap_c"] is not None:
                drift = min(drift, ramp["cap_c"])
            device.temp_drift_c = drift

    def _scaled_kw(self, subject: str, factor: float) -> float:
        cell = self.env.read_measurement(subject, "p_kw")
        base = float(cell["value"]) if cell else 0.0
        return base * factor

    # ------------------------------------------------ SUT 桩链（ASK/两票）
    def _sut_action_request(self, plan: dict) -> None:
        """计划事件 action.request：Policy（本体数据）→ ALLOW 直执行 / ASK 待审批。"""
        env = self.env
        params = plan["params"]
        capability = str(params.get("capability", ""))
        action_id = str(params.get("action_id") or f"act-{plan['index'] + 1:03d}")
        arguments = dict(params.get("args") or {})
        action = _synthetic_request(action_id, capability, {
            "arguments": arguments, "purpose": str(params.get("purpose", "场景计划动作")),
            "user": str(params.get("user", "OP-001")),
            "requested_at": plan["business_at"],
        })
        env.emit(EventType.ACTION_REQUESTED, action_id,
                 {"capability": capability, "arguments": arguments}, plan["at_s"])
        action_id_key = capability.split("@", 1)[0]
        default_policy = (env.ontology.actions.get(action_id_key) or {}).get("default_policy")
        env.emit(EventType.ACTION_POLICY_DECIDED, action_id,
                 {"decision": default_policy, "capability": capability}, plan["at_s"])
        if default_policy == "ALLOW":
            result, _env = simulate(action, env)
            self._record_action_result(result, plan["at_s"])
        elif default_policy == "ASK":
            env.emit(EventType.ACTION_WAITING_APPROVAL, action_id,
                     {"capability": capability, "reason": "缺省 Policy=ASK"}, plan["at_s"])
            env.emit(EventType.APPROVAL_REQUESTED, action_id,
                     {"capability": capability, "timeout_s": self.spec.interactions.timeout_s},
                     plan["at_s"])
            # 遥控前登记操作票（SAFE-TWO-TICKET：签发人角色必须是"签发人"）
            order_code = str(arguments.get("switch_order", "") or "")
            if order_code and order_code not in env.switch_orders:
                env.switch_orders[order_code] = {
                    "code": order_code, "status": "ISSUED",
                    "steps": list(arguments.get("steps") or []),
                    "devices": [arguments.get("device", "")],
                    "issuer": str(arguments.get("issuer", "OP-003")),
                }
            self.pending_approval = {
                "action": action, "capability": capability,
                "requested_at_s": plan["at_s"], "business_at": plan["business_at"],
            }
            self.approval_age_s = 0.0
        else:  # DENY（数据驱动）
            result = _action_result(action, "DENIED", [], "缺省 Policy=DENY，拒绝执行",
                                    evidence={"intended": {"capability": capability,
                                                           "arguments": arguments},
                                              "issued": None, "observed": None},
                                    error={"code": "POLICY_DENIED",
                                           "message": f"{capability} 缺省 Policy=DENY"},
                                    latency_ms=1)
            self._record_action_result(result, plan["at_s"])

    def _persona_due(self, now_s: float) -> None:
        business_now = self.env.clock.business_now()
        while True:
            utterance = self.persona.due(business_now)
            if utterance is None:
                break
            if self.recorder is not None:
                self.recorder.interaction(utterance.to_dict(), now_s,
                                          iso_z(business_now))
            act = utterance.act
            if act in ("GRANT", "DENY") and self.pending_approval is not None:
                self._resolve_approval(act, now_s)

    def _resolve_approval(self, act: str, now_s: float) -> None:
        env = self.env
        pending = self.pending_approval
        action = pending["action"]
        action_id = action.action_id
        if act == "GRANT":
            if not env.approval_channel_open(now_s):
                # COMM_LOSS：审批无法送达 → 超时语义（SPEC-M5-05）
                env.emit(EventType.APPROVAL_TIMEOUT, action_id,
                         {"capability": pending["capability"], "reason": "COMM_LOSS"},
                         now_s)
                self._finish_approval(action, "REJECTED", now_s,
                                      error={"code": "APPROVAL_TIMEOUT",
                                             "message": "审批通道中断（COMM_LOSS），超时拒绝"})
                return
            env.emit(EventType.APPROVAL_GRANTED, action_id,
                     {"capability": pending["capability"], "approver": "OP-004"}, now_s)
            env.granted_keys.add(f"{pending['capability']}:{action_id}")
            result, _env = simulate(action, env)
            self._record_action_result(result, now_s)
        else:
            env.emit(EventType.APPROVAL_DENIED, action_id,
                     {"capability": pending["capability"]}, now_s)
            self._finish_approval(action, "REJECTED", now_s,
                                  error={"code": "APPROVAL_DENIED", "message": "审批人拒绝"})
        self.pending_approval = None

    def _finish_approval(self, action, status: str, now_s: float, *, error: dict) -> None:
        result = _action_result(
            action, status, [], f"{status}（{error['code']}）",
            evidence={"intended": {"capability": action.capability,
                                   "arguments": action.arguments},
                      "issued": None, "observed": None},
            error=error, latency_ms=1)
        self._record_action_result(result, now_s)
        self.pending_approval = None

    def _approval_timeout_check(self, now_s: float) -> None:
        if self.pending_approval is None:
            return
        pending = self.pending_approval
        # timeout_s 为墙钟秒；经 speed（墙钟秒→仿真秒）换算为仿真秒（SPEC-M5-02 倍速语义）
        sim_timeout_s = max(float(self.spec.interactions.timeout_s)
                            * float(self.env.clock.speed), 1.0)
        self.approval_age_s = now_s - pending["requested_at_s"]
        channel_open = self.env.approval_channel_open(now_s)
        if not channel_open or self.approval_age_s >= sim_timeout_s:
            action = pending["action"]
            reason = "COMM_LOSS" if not channel_open else "TIMEOUT"
            self.env.emit(EventType.APPROVAL_TIMEOUT, action.action_id,
                          {"capability": pending["capability"], "reason": reason}, now_s)
            self._finish_approval(action, "REJECTED", now_s,
                                  error={"code": "APPROVAL_TIMEOUT",
                                         "message": f"审批超时（{reason}）"})

    def _record_action_result(self, result: dict, at_s: float) -> None:
        env = self.env
        env.emit(EventType.ACTION_COMPLETED, result["action_id"],
                 {"status": result["status"], "capability_hint": result["observation"][:60]},
                 at_s)
        if self.recorder is not None:
            self.recorder.trajectory_step(
                "TOOL_CALL", result["action_id"],
                f"{result['status']} {result['observation']}",
                latency_ms=result.get("latency_ms", 0))

    def _record_state_transitions(self, prev_s: float, now_s: float) -> None:
        """从本 tick 事件流提取状态迁移行（设备状态/告警升降/负载覆盖）。"""
        if self.recorder is None:
            return
        for event in self.env.event_buffer:
            etype = event["type"]
            payload = event.get("payload") or {}
            if etype == EventType.GRID_EVENT.value and payload.get("kind") == "device_state":
                self.recorder.state_transition(
                    event["subject"], "device_state", payload.get("from"),
                    payload.get("to"), now_s, event["occurred_at"],
                    reason=payload.get("reason", ""))
            elif etype == EventType.ALARM_RAISED.value:
                self.recorder.state_transition(
                    event["subject"], "alarm", None, payload.get("level"), now_s,
                    event["occurred_at"], reason=payload.get("rule", ""))
                self.recorder.trajectory_step(
                    "STATE_CHANGE", payload.get("alarm_id", event["subject"]),
                    f"alarm.raised {payload.get('level')} {payload.get('rule')}")
            elif etype == EventType.ALARM_CLEARED.value:
                self.recorder.state_transition(
                    event["subject"], "alarm", payload.get("level"), None, now_s,
                    event["occurred_at"], reason=payload.get("rule", ""))
            elif etype == EventType.PRICE_PERIOD_CHANGED.value:
                self.recorder.timeline_row(
                    "PRICE", f"{payload.get('from')}→{payload.get('to')}",
                    now_s, event["occurred_at"], payload=payload)
            elif etype == EventType.DEMAND_MONTH_ROLLED.value:
                self.recorder.timeline_row(
                    "DEMAND", f"月度需量滚动 {payload.get('from_month')}→{payload.get('to_month')}",
                    now_s, event["occurred_at"], payload=payload)
            elif etype == EventType.SIM_INJECTED.value:
                self.recorder.timeline_row(
                    "FAULT", f"{payload.get('fault_type')} → {event['subject']}",
                    now_s, event["occurred_at"], payload=payload)
            elif etype in (EventType.APPROVAL_REQUESTED.value, EventType.APPROVAL_GRANTED.value,
                           EventType.APPROVAL_DENIED.value, EventType.APPROVAL_TIMEOUT.value):
                self.recorder.timeline_row("APPROVAL", etype, now_s, event["occurred_at"],
                                           payload=payload)
                self.recorder.trajectory_step("APPROVAL", event["subject"], f"{etype}")

    # ------------------------------------------------ 主循环
    def run(self) -> SimRunResult:
        stop = self._stop_state()
        guard = 0
        while not self._stopped(stop):
            self.tick()
            guard += 1
            if guard > MAX_TICKS:
                break

        env = self.env
        env.emit(EventType.SIM_COMPLETED, env.spec.identity.scenario_id,
                 {"ticks": self.tick_count, "sim_elapsed_s": env.clock.sim_elapsed_s},
                 env.clock.sim_elapsed_s)
        evidence_pack: list = []
        traj_ref = ""
        trajectory: dict = {}
        if self.recorder is not None:
            self.recorder.timeline_row(
                "RUN_END", f"ticks={self.tick_count}", env.clock.sim_elapsed_s,
                iso_z(env.clock.business_now()))
            outcome = dict(self.outcome)
            outcome["evidence_summary"] = (
                f"ticks={self.tick_count} events={len(env.event_log)} "
                f"interactions={len(self.recorder.interactions)} "
                f"alarms={len(env.alarms)}")
            finalized = self.recorder.finalize(
                trace_id=env.trace_id, task_id=self.spec.identity.scenario_id,
                outcome=outcome, quality_flags=[])
            evidence_pack = finalized["evidence_pack"]
            traj_ref = finalized["traj_ref"]
            trajectory = finalized["trajectory"]

        result = SimRunResult.from_dict({
            "run_id": env.run_id,
            "scenario_id": self.spec.identity.scenario_id,
            "manifest_hash": self.manifest_hash,
            "traj_ref": traj_ref or f"inline://{env.run_id}",
            "state_final": env.state_final(),
            "evidence_pack": evidence_pack or [{"kind": "TIMELINE",
                                                "ref": f"inline://{env.run_id}"}],
            "reproduction": {"deterministic": True, "seed": self.seed},
        })
        result.trajectory = trajectory  # 便捷字段（diff_runs 用；不属契约字段）
        result.env_events = list(env.event_log)  # 便捷字段（EVAL 事件断言用；不属契约字段）
        return result


# ===========================================================================
# 冻结 API 包装
# ===========================================================================
def step(env: SimEnv, action=ENV_TICK, *, engine: ScenarioEngine | None = None) -> tuple:
    """01 §3.5：``step(env, action|ENV_TICK) -> (SimEnv, Observation, SimEvents[])``。

    - ``ENV_TICK``：推进一个物理步（需要 engine 组件束；缺省以 env 现场临时构建）；
    - 动作（dict/ActionRequest）：走 ``simulate``（SPEC-M5-03 仿真路由）。
    """
    if action is ENV_TICK or action == "ENV_TICK":
        if engine is not None:
            return engine.tick()
        transient = ScenarioEngine.__new__(ScenarioEngine)
        transient.env = env
        transient.spec = env.spec
        transient.physics = PhysicsEngine({**MODEL_DEFAULTS, **(env.model_params or {})})
        transient.price_clock = PriceClock(env)
        transient.demand = DemandTracker(env)
        transient.alarm_engine = AlarmEngine(env)
        transient.injector = FaultInjector(env)
        transient.persona = PersonaSession("OPERATOR", [])
        transient.tick_count = 0
        transient.recorder = None
        transient.pending_approval = None
        transient.approval_age_s = 0.0
        transient.temp_ramps = []
        transient._planned = []
        transient.outcome = {}
        return transient.tick()
    result, env_after = simulate(action, env)
    observation = {"action_id": result["action_id"], "status": result["status"],
                   "observation": result["observation"],
                   "business_at": iso_z(env.clock.business_now())}
    return env_after, observation, [e for e in env.event_buffer]


def run_scenario(spec: ScenarioSpec | Mapping | Path | str, *,
                 seed: str | None = None, repo_root: Path | str | None = None,
                 persist: bool = True, model_params: Mapping | None = None) -> SimRunResult:
    """01 §3.5：``run_scenario(spec) -> SimRunResult``（一站式：装载→驱动→采集）。

    ``spec`` 接受 ScenarioSpec / dict / YAML 文件路径。
    同 spec（含派生 seed）重放 → 轨迹逐步 diff 为空（SPEC-M5-01，EVAL-M5-01-P）。
    """
    if isinstance(spec, (str, Path)):
        path = Path(spec)
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        spec = ScenarioSpec.from_dict(data)
        if repo_root is None:
            repo_root = path.resolve().parents[1]
    engine = ScenarioEngine(spec, seed=seed, repo_root=repo_root, persist=persist,
                            model_params=model_params)
    return engine.run()


# ===========================================================================
# 确定性比对（SPEC-M5-01）
# ===========================================================================
def diff_runs(result_a: SimRunResult, result_b: SimRunResult) -> list:
    """两次 run 的逐步 diff（剔除审计列后逐层比对；空列表 = 完全一致）。

    比对层：轨迹 steps、INTERACTION_LOG、STATE_TRANSITIONS、TIMELINE（去审计列）、
    终态快照。MONOTONIC/WALL 为只读真实时间源（审计列），不参与确定性判定。
    """
    diffs: list = []

    def _traj(result: SimRunResult) -> list:
        trajectory = getattr(result, "trajectory", None)
        if trajectory:
            return strip_audit_columns(trajectory.get("steps") or [])
        return []

    steps_a, steps_b = _traj(result_a), _traj(result_b)
    if steps_a != steps_b:
        for index in range(max(len(steps_a), len(steps_b))):
            a = steps_a[index] if index < len(steps_a) else None
            b = steps_b[index] if index < len(steps_b) else None
            if a != b:
                diffs.append(f"trajectory.steps[{index}]: {json.dumps(a, ensure_ascii=False)}"
                             f" != {json.dumps(b, ensure_ascii=False)}")

    pack_a = {item.kind.value if hasattr(item.kind, "value") else str(item.kind): item.ref
              for item in result_a.evidence_pack}
    pack_b = {item.kind.value if hasattr(item.kind, "value") else str(item.kind): item.ref
              for item in result_b.evidence_pack}
    for kind in sorted(set(pack_a) | set(pack_b)):
        path_a, path_b = Path(pack_a.get(kind, "")), Path(pack_b.get(kind, ""))
        rows_a = _read_jsonl(path_a)
        rows_b = _read_jsonl(path_b)
        norm_a = strip_audit_columns(rows_a)
        norm_b = strip_audit_columns(rows_b)
        if norm_a != norm_b:
            diffs.append(f"evidence[{kind}]: {len(norm_a)} 行 vs {len(norm_b)} 行（内容不一致）")

    state_a = strip_audit_columns(result_a.state_final)
    state_b = strip_audit_columns(result_b.state_final)
    if state_a != state_b:
        diffs.append("state_final 不一致")
    if result_a.manifest_hash != result_b.manifest_hash:
        diffs.append("manifest_hash 不一致")
    return diffs


def _read_jsonl(path: Path) -> list:
    if not path or not Path(path).is_file():
        return []
    rows = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
