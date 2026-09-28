# -*- coding: utf-8 -*-
"""m5_simulation 的 EVAL 执行器插件（tests/test_m5.yaml 数据驱动用例）。

插件契约（tests/EVAL-SCHEMA.md §4）：暴露 ``EXECUTORS: dict[str, callable]``；
执行器签名 ``fn(case: dict, ctx) -> {"passed": bool, "detail": str, "metrics": dict}``。

全部执行器只读 ``case.params`` 声明的数据（设备/阈值/期望值均来自 YAML 用例文件），
不做针对特定输入的硬编码特判；园区实例经 ADDENDUM §D 按名加载
（非 seed 实例置于 tests/fixtures/，经 ``PARK_INSTANCE_PATH`` 搜索）。
"""
from __future__ import annotations

import contextlib
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

from contracts import ScenarioSpec, UserModel

from m5_simulation import (
    ClockHub,
    PersonaSession,
    ScenarioEngine,
    parse_time_ref,
    run_scenario,
    simulate,
)
from m5_simulation.recorder import strip_audit_columns

__all__ = ["EXECUTORS"]


def _result(passed: bool, detail: str, metrics: dict | None = None) -> dict:
    return {"passed": bool(passed), "detail": str(detail), "metrics": metrics or {}}


@contextlib.contextmanager
def _instance_path_env(ctx: Any, instance: str | None):
    """非 seed 实例：把 tests/fixtures 追加进 PARK_INSTANCE_PATH（调用后还原）。"""
    if not instance or instance == "seed":
        yield
        return
    fixtures = str((Path(ctx.root) / "tests" / "fixtures").resolve())
    old = os.environ.get("PARK_INSTANCE_PATH", "")
    parts = [p for p in old.split(";") if p.strip()]
    if fixtures not in parts:
        parts.append(fixtures)
    os.environ["PARK_INSTANCE_PATH"] = ";".join(parts)
    try:
        yield
    finally:
        if old:
            os.environ["PARK_INSTANCE_PATH"] = old
        else:
            os.environ.pop("PARK_INSTANCE_PATH", None)


def _scenario_dict(params: dict) -> dict:
    """由用例参数构造完整 ScenarioSpec dict（十字段组，契约校验由 from_dict 把关）。"""
    return {
        "identity": {
            "scenario_id": str(params.get("scenario_id", "sim-eval")),
            "version": "1.0", "owner": "m5-eval", "tags": ["eval"],
        },
        "sut": {"target": "MODULE", "module": "m5_simulation"},
        "environment": {
            "park_instance": str(params.get("instance", "seed")),
            "clock_start": str(params.get("clock_start", "2026-09-15T08:30:00Z")),
            "speed": float(params.get("speed", 60.0)),
            "injections": list(params.get("injections") or []),
        },
        "user_model": {
            "persona": str(params.get("persona", "OPERATOR")),
            "behavior_script": list(params.get("behavior_script") or []),
        },
        "interactions": {"max_turns": int(params.get("max_turns", 50)),
                         "timeout_s": int(params.get("timeout_s", 600))},
        "events": list(params.get("events") or []),
        "constraints": {
            "budget": {"token": 100000, "action": 100},
            "stop_conditions": list(params.get("stop_conditions", ["duration_h:24"])),
        },
        "metrics": [{"name": "sim", "rubric": "PHYS-TX-LOAD"}],
        "provenance": {"source": "tests/test_m5.yaml",
                       "created_at": "2026-09-28T00:00:00Z", "notes": "m5 eval generated"},
    }


def _engine(params: dict, *, persist: bool = False, repo_root: Path | str | None = None,
            spec: ScenarioSpec | None = None) -> ScenarioEngine:
    spec = spec or ScenarioSpec.from_dict(_scenario_dict(params))
    return ScenarioEngine(spec, repo_root=repo_root, persist=persist)


def _ticks_until(engine: ScenarioEngine, target_s: float, *, limit: int = 2000) -> None:
    while engine.env.clock.sim_elapsed_s < target_s:
        engine.tick()
        if engine.tick_count > limit:
            break


def _at_seconds(params: dict, ref: str) -> float:
    clock_start = parse_time_ref(params.get("clock_start", "2026-09-15T08:30:00Z"),
                                 _EPOCH)
    return (parse_time_ref(ref, clock_start) - clock_start).total_seconds()


from datetime import datetime, timezone  # noqa: E402

_EPOCH = datetime(2026, 9, 15, 8, 30, tzinfo=timezone.utc)


def _event_types(env) -> list:
    return [e["type"] for e in env.event_log]


def _same_instant(a: Any, b: Any) -> bool:
    """时刻等价比较（字符串/datetime 双形态归一为 UTC datetime）。"""
    if a is None or b is None:
        return a is b
    return parse_time_ref(a, _EPOCH) == parse_time_ref(b, _EPOCH)


# ---------------------------------------------------------------------------
# SPEC-M5-01 · 确定性
# ---------------------------------------------------------------------------
def exec_determinism(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    scenario_file = str(params.get("scenario", "scenarios/dev-01-report.yaml"))
    spec_data = ctx.load_yaml(scenario_file)
    spec = ScenarioSpec.from_dict(spec_data)

    def _capture() -> dict:
        engine = ScenarioEngine(spec, persist=True)
        result = engine.run()
        layers = {}
        for item in result.evidence_pack:
            path = Path(item.ref)
            rows = []
            if path.is_file():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        rows.append(yaml.safe_load(line))
            layers[item.kind if isinstance(item.kind, str)
                   else item.kind.value] = strip_audit_columns(rows)
        return {
            "manifest": result.manifest_hash,
            "deterministic": result.reproduction.deterministic,
            "seed": result.reproduction.seed,
            "state_final": strip_audit_columns(result.state_final),
            "steps": strip_audit_columns(getattr(result, "trajectory", {}).get("steps") or []),
            "layers": layers,
        }

    first = _capture()
    second = _capture()

    problems: list = []
    if first["manifest"] != second["manifest"]:
        problems.append("manifest_hash 不一致")
    if not first["deterministic"] or not second["deterministic"]:
        problems.append("reproduction.deterministic 不为 true")
    if first["seed"] != second["seed"]:
        problems.append("seed 不一致")
    if first["steps"] != second["steps"]:
        problems.append(f"轨迹逐步 diff 非空（{len(first['steps'])} vs {len(second['steps'])} 步）")
    if first["state_final"] != second["state_final"]:
        problems.append("终态快照不一致")
    for kind in sorted(set(first["layers"]) | set(second["layers"])):
        if first["layers"].get(kind) != second["layers"].get(kind):
            problems.append(f"证据层 {kind} 内容不一致")

    metrics = {"steps": len(first["steps"]),
               "timeline_rows": len(first["layers"].get("TIMELINE") or []),
               "interaction_rows": len(first["layers"].get("INTERACTION_LOG") or []),
               "manifest": first["manifest"][:12]}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"同 seed 两次重放逐步 diff 为空（{len(first['steps'])} 步轨迹、"
                         f"三层证据一致，seed={first['seed'][:20]}）", metrics)


# ---------------------------------------------------------------------------
# SPEC-M5-02 · 四类时间 / 电价时钟
# ---------------------------------------------------------------------------
def exec_price_boundary(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    advance_minutes = float(params.get("advance_minutes", 150))
    with _instance_path_env(ctx, params.get("instance")):
        engine = _engine({
            "instance": params.get("instance", "seed"),
            "clock_start": params.get("clock_start"),
            "stop_conditions": [f"duration_s:{int(advance_minutes * 60)}"],
        })
        engine.run()

    events = [e for e in engine.env.event_log
              if e["type"] == "price.period_changed"]
    problems: list = []
    want_at = str(expect.get("boundary_at", ""))
    want_from = str(expect.get("from_period", ""))
    want_to = str(expect.get("to_period", ""))
    hit = None
    for event in events:
        payload = event.get("payload") or {}
        if payload.get("from") == want_from and payload.get("to") == want_to:
            hit = event
    if hit is None:
        problems.append(f"未发现 {want_from}→{want_to} 边界事件（共 {len(events)} 条价格事件）")
    else:
        if not _same_instant(hit["occurred_at"], want_at):
            problems.append(f"边界时刻 {hit['occurred_at']} != 期望 {want_at}（须为 BUSINESS 读数）")
    # 行为断言：墙钟篡改不影响峰谷判定（电价判定只允许 BUSINESS 时钟）
    import importlib

    from m5_simulation.price_clock import period_at

    clock_mod = importlib.import_module("m5_simulation.clock")
    probe_s = _at_seconds({"clock_start": params.get("clock_start", "2026-09-15T10:00:00Z")},
                          want_at)
    baseline = period_at(engine.env, probe_s)
    original_datetime = clock_mod.datetime

    class _FakeDateTime(original_datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: N805 - 篡改墙钟（应不影响电价判定）
            return cls(2020, 1, 1, 0, 0, tzinfo=timezone.utc)

    clock_mod.datetime = _FakeDateTime
    try:
        tampered = period_at(engine.env, probe_s)
    finally:
        clock_mod.datetime = original_datetime
    if baseline != tampered:
        problems.append(f"墙钟篡改改变了电价判定: {baseline} != {tampered}")

    metrics = {"price_events": len(events), "boundary": want_at,
               "from": want_from, "to": want_to}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"price.period_changed {want_from}→{want_to} 恰在 {want_at}"
                         f"（BUSINESS 读数；墙钟篡改不影响判定）", metrics)


def exec_no_wallclock_pricing(case: dict, ctx: Any) -> dict:
    """代码扫描：业务代码无 wall-clock 峰谷判定（EVAL-M5-02-N，模式数据驱动）。

    ``exclude``：允许接触墙钟的白名单路径（clock.py 是 WALL/MONOTONIC 的唯一
    合法实现位——SPEC-M5-02 的只读真实时钟源；eval_plugin 是扫描器自身）。
    """
    params = case.get("params") or {}
    scan_dirs = params.get("scan_dirs") or ["src"]
    exclude = [str(x) for x in params.get("exclude") or []]
    forbidden = list(params.get("forbidden") or
                     ["datetime.now", "datetime.today", "time.localtime",
                      "time.time", "utcnow", "time.gmtime"])
    markers = list(params.get("price_markers") or
                   ["price", "period", "tariff", "peak", "valley", "峰", "谷", "FLAT"])
    violations: list = []
    scanned = 0
    for rel in scan_dirs:
        base = Path(ctx.root) / rel
        for path in sorted(base.rglob("*.py")):
            posix = path.relative_to(ctx.root).as_posix()
            if any(token in posix for token in exclude):
                continue
            scanned += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            lowered = text.lower()
            has_marker = any(str(m).lower() in lowered for m in markers)
            if not has_marker:
                continue
            for token in forbidden:
                if token.lower() in lowered:
                    violations.append(f"{posix}: 含墙钟调用 {token!r}")
    metrics = {"scanned_files": scanned, "forbidden_tokens": len(forbidden)}
    if violations:
        return _result(False, "业务代码存在 wall-clock 电价判定风险：" + "；".join(violations),
                       metrics)
    return _result(True, f"扫描 {scanned} 个业务源文件：电价相关模块零墙钟调用"
                         f"（BUSINESS 时钟为峰谷判定唯一依据）", metrics)


# ---------------------------------------------------------------------------
# SPEC-M5-03 · 环境接口（simulate）
# ---------------------------------------------------------------------------
def exec_simulate_interface(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    with _instance_path_env(ctx, params.get("instance")):
        engine = _engine({"instance": params.get("instance", "seed"),
                          "clock_start": params.get("clock_start"),
                          "stop_conditions": [f"duration_s:{int(params.get('warmup_s', 1800))}"]})
        engine.run()
    env = engine.env

    query_args = dict(params.get("query") or {})
    write_spec = dict(params.get("write") or {})
    readback_args = dict(params.get("readback") or {})

    result_q, _ = simulate({"capability": "query.measurement@v1",
                            "arguments": query_args}, env)
    cells = (result_q["evidence"]["observed"] or {}).get("measurements") or []
    problems: list = []
    if result_q["status"] != "SUCCEEDED":
        problems.append(f"查询失败: {result_q.get('error')}")
    if not cells:
        problems.append("查询快照为空（缺量测时标）")
    missing_ts = [c for c in cells if not c.get("ts")]
    if missing_ts:
        problems.append(f"{len(missing_ts)} 条量测缺时标 ts")
    if expect.get("query_has_quality", True) and any("quality" not in c for c in cells):
        problems.append("量测快照缺 quality 标志")

    result_w, _ = simulate({"capability": write_spec.get("capability", "execute.capacitor_switch@v1"),
                            "action_id": "act-write-001",
                            "arguments": dict(write_spec.get("args") or {})}, env)
    if result_w["status"] != "SUCCEEDED":
        problems.append(f"写动作失败: {result_w.get('error')}")
    else:
        evidence = result_w["evidence"]
        if not (evidence.get("intended") and evidence.get("issued") and evidence.get("observed")):
            problems.append("SUCCEEDED 但 evidence 三态不齐")

    result_r, _ = simulate({"capability": "query.asset@v1",
                            "arguments": readback_args}, env)
    observed_state = ((result_r["evidence"]["observed"] or {})
                      .get("attributes", {}).get("state"))
    want_state = str(expect.get("readback_state", "ON"))
    if observed_state != want_state:
        problems.append(f"写后回读 {observed_state!r} != 期望 {want_state!r}（observed 未反映变更）")

    metrics = {"queried_cells": len(cells), "write_status": result_w["status"],
               "readback_state": observed_state}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"读动作返回 {len(cells)} 条带时标快照；写动作 {result_w['status']}"
                         f" 后回读状态变化可观测（{observed_state}）", metrics)


# ---------------------------------------------------------------------------
# SPEC-M5-04 · 用户模拟（脚本模式）
# ---------------------------------------------------------------------------
def exec_persona_script(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    script = list(params.get("script") or [])
    clock_start = parse_time_ref(params.get("clock_start", "2026-09-15T08:30:00Z"), _EPOCH)
    user_model = UserModel.from_dict({"persona": str(params.get("persona", "OPERATOR")),
                                      "behavior_script": script})

    def _replay() -> list:
        session = PersonaSession.from_spec(user_model, clock_start)
        hub = ClockHub(clock_start)
        last_at = session.script[-1]["at_abs"] if session.script else clock_start
        hub.advance_sim((last_at - clock_start).total_seconds() + 1.0)
        outputs = []
        while True:
            utterance = session.due(hub.business_now())
            if utterance is None:
                break
            outputs.append(utterance.to_dict())
        return outputs

    first = _replay()
    second = _replay()
    problems: list = []
    if len(first) != len(script):
        problems.append(f"回放 {len(first)} 条 != 脚本 {len(script)} 条")
    if first != second:
        problems.append("两次回放不一致（非确定性）")
    for index, (output, step) in enumerate(zip(first, script)):
        if output["text"] != step.get("text") or output["act"] != str(step.get("act")):
            problems.append(f"第 {index + 1} 条非逐字回放: {output['text']!r}")

    # LLM 模式降级路径（M1 未交付：ModelClient 占位抛 NotImplementedError → 回退脚本）
    from m5_simulation.persona import persona_step

    session = PersonaSession.from_spec(user_model, clock_start)
    hub = ClockHub(clock_start)
    hub.advance_sim(3600.0)
    degraded = persona_step(session, [], mode="llm")
    if degraded is not None and not degraded.degraded and degraded.mode == "llm":
        problems.append("LLM 占位阶段应走降级路径（degraded 标记）")

    metrics = {"steps": len(script), "replay": len(first),
               "llm_degraded": degraded.degraded if degraded else None}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"OPERATOR 脚本 {len(script)} 轮逐字确定性回放，两次一致；"
                         f"LLM 模式占位阶段按降级路径回退", metrics)


# ---------------------------------------------------------------------------
# SPEC-M5-05 · 故障注入
# ---------------------------------------------------------------------------
def exec_fault(case: dict, ctx: Any) -> dict:
    """SENSING_OUTAGE / SENSOR_STUTTER / ALARM_STORM / COMM_LOSS / DEVICE_TRIP 共用执行器。

    params.kind 选择断言口径（数据驱动）：
    - outage：量测 stale 标志 + 中断区间；
    - stutter：窗口内 flips 次翻转 + 去抖后稳定；
    - storm：alarm.raised 事件总数=注入数 + 按级别聚合；
    - comm_loss：审批 GRANT 在中断窗口 → approval.timeout + REJECTED；
    - trip：设备 FAULT + 保护动作 grid.event + 负载归零。
    """
    params = case.get("params") or {}
    kind = str(params.get("kind", "outage"))
    at_s = _at_seconds(params, str(params.get("at", "+30m")))
    settle_s = float(params.get("settle_s", 0.0))
    with _instance_path_env(ctx, params.get("instance")):
        engine = _engine({
            "instance": params.get("instance", "seed"),
            "clock_start": params.get("clock_start"),
            "injections": params.get("injections"),
            "events": params.get("events"),
            "behavior_script": params.get("behavior_script"),
            "timeout_s": params.get("timeout_s", 600),
            "stop_conditions": [f"duration_s:{int(at_s + settle_s + 1800)}"],
        })
        _ticks_until(engine, at_s + settle_s)
    env = engine.env
    expect = case.get("expect") or {}
    problems: list = []

    if kind == "outage":
        target = str(params.get("target", "TH-A01"))
        result, _ = simulate({"capability": "query.measurement@v1",
                              "arguments": {"device": target}}, env)
        cells = (result["evidence"]["observed"] or {}).get("measurements") or []
        stale = [c for c in cells if c.get("stale")]
        if not stale:
            problems.append("窗口内量测无 stale 标志（应保持旧值并标记，不得伪造新读数）")
        for cell in stale:
            outage = cell.get("outage") or {}
            if not outage.get("from") or not outage.get("to"):
                problems.append(f"{cell['quantity']} 缺中断区间: {outage}")
            elif expect.get("outage_from") and not _same_instant(
                    outage.get("from"), expect.get("outage_from")):
                problems.append(f"中断区间起点 {outage.get('from')} != 期望 {expect.get('outage_from')}")
        metrics = {"target": target, "stale_cells": len(stale), "cells": len(cells)}
    elif kind == "stutter":
        target = str(params.get("target", "SG-A01"))
        flips_expected = int(expect.get("flips", params.get("flips", 4)))
        window_s = float(expect.get("window_s", params.get("window_s", 3)))
        flip_events = []
        for event in env.event_log:
            payload = event.get("payload") or {}
            if (event["type"] == "measurement.updated"
                    and payload.get("fault_type") == "SENSOR_STUTTER"):
                flip_events.append(event)
        if len(flip_events) != flips_expected:
            problems.append(f"翻转事件 {len(flip_events)} != 注入 {flips_expected}")
        if flip_events:
            import json as _json

            def _sec(iso: str) -> float:
                stamp = _json.dumps(iso)
                from datetime import datetime as _dt
                return (_dt.fromisoformat(iso.replace("Z", "+00:00"))
                        - env.clock.clock_start).total_seconds()

            span = _sec(flip_events[-1]["occurred_at"]) - _sec(flip_events[0]["occurred_at"])
            if span > window_s + 1e-6:
                problems.append(f"翻转跨度 {span}s > 窗口 {window_s}s")
        debounce_s = float(params.get("debounce_s", 2.0))
        view = env.debounced_state(target, debounce_s,
                                   now_s=env.clock.sim_elapsed_s)
        if view.get("chattering"):
            problems.append(f"去抖后仍判定抖动中: {view}")
        if expect.get("final_state") and view.get("state") != str(expect["final_state"]):
            problems.append(f"去抖稳定态 {view.get('state')} != 期望 {expect['final_state']}")
        metrics = {"flip_events": len(flip_events), "span_s": round(span, 3) if flip_events else 0,
                   "debounced": view}
    elif kind == "storm":
        count_expected = int(expect.get("count", params.get("count", 50)))
        storm_raises = [e for e in env.event_log
                        if e["type"] == "alarm.raised"
                        and (e.get("payload") or {}).get("injected")]
        if len(storm_raises) != count_expected:
            problems.append(f"alarm.raised 注入事件 {len(storm_raises)} != {count_expected}")
        summary = env.storm_summary or {}
        if summary.get("total") != count_expected:
            problems.append(f"聚合总数 {summary.get('total')} != {count_expected}")
        by_level = summary.get("by_level") or {}
        if sum(by_level.values()) != count_expected:
            problems.append("按级别聚合计数与总数不符（聚合不得丢事件）")
        metrics = {"alarm_events": len(storm_raises), "by_level": by_level}
    elif kind == "comm_loss":
        want_status = str(expect.get("final_action_status", "REJECTED"))
        timeouts = [e for e in env.event_log if e["type"] == "approval.timeout"]
        if not timeouts:
            problems.append("COMM_LOSS 窗口内未产生 approval.timeout（超时语义失效）")
        completed = [e for e in env.event_log if e["type"] == "action.completed"]
        statuses = [(e.get("payload") or {}).get("status") for e in completed]
        if statuses and statuses[-1] != want_status:
            problems.append(f"动作终态 {statuses[-1]} != 期望 {want_status}")
        metrics = {"timeouts": len(timeouts), "statuses": statuses}
    elif kind == "trip":
        target = str(params.get("target", "TX-03"))
        device = env.devices.get(target)
        if device is None or device.state != str(expect.get("device_state", "FAULT")):
            problems.append(f"设备状态 {None if device is None else device.state}"
                            f" != 期望 {expect.get('device_state', 'FAULT')}")
        guards = [e for e in env.event_log
                  if e["type"] == "grid.event" and e["subject"] == target]
        if not guards:
            problems.append("缺保护动作 grid.event（DEVICE_TRIP 近似）")
        cell = env.read_measurement(target, "p_kw")
        if expect.get("load_zero", True) and cell and abs(cell["value"]) > 1e-6:
            problems.append(f"跳闸后负载未归零: {cell['value']}")
        metrics = {"device_state": None if device is None else device.state,
                   "grid_events": len(guards)}
    else:
        return _result(False, f"未知 kind: {kind!r}")

    if problems:
        return _result(False, "；".join(str(p) for p in problems), metrics)
    return _result(True, f"{kind} 注入按 at 计划触发且全部落 SIM 时间线（期望全部满足）", metrics)


# ---------------------------------------------------------------------------
# SPEC-M5-06 · 三层证据
# ---------------------------------------------------------------------------
def exec_evidence_pack(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    scenario_file = str(params.get("scenario", "scenarios/dev-02-alarm.yaml"))
    spec_data = ctx.load_yaml(scenario_file)
    with _instance_path_env(ctx, (spec_data.get("environment") or {}).get("park_instance")):
        result = run_scenario(ScenarioSpec.from_dict(spec_data), repo_root=ctx.root)

    problems: list = []
    kinds = {(item.kind if isinstance(item.kind, str) else item.kind.value): item.ref
             for item in result.evidence_pack}
    metrics_rows = 0
    for kind in ("INTERACTION_LOG", "STATE_TRANSITIONS", "TIMELINE"):
        if kind not in kinds:
            problems.append(f"evidence_pack 缺 {kind}")
            continue
        path = Path(kinds[kind])
        if not path.is_file():
            problems.append(f"{kind} 文件缺失: {path}")
            continue
        rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not rows:
            problems.append(f"{kind} 文件为空")
        if kind == "TIMELINE":
            import json as _json

            four_clock_rows = 0
            for line in rows:
                row = _json.loads(line)
                if all(row.get(k) is not None for k in
                       ("business_at", "sim_elapsed_s", "monotonic_ms", "wall_at")):
                    four_clock_rows += 1
            if four_clock_rows == 0:
                problems.append("TIMELINE 无四类时间对齐行")
            metrics_rows = four_clock_rows
    timeline_path = Path(kinds.get("TIMELINE", ""))
    interaction_path = Path(kinds.get("INTERACTION_LOG", ""))
    metrics = {
        "evidence_kinds": len(kinds),
        "timeline_rows": metrics_rows if metrics_rows else 0,
        "interaction_rows": len(interaction_path.read_text(encoding="utf-8").splitlines())
        if interaction_path.is_file() else 0,
        "run_id": result.run_id,
    }
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"三层证据齐全：TIMELINE {metrics['timeline_rows']} 行含四类时间对齐、"
                         f"INTERACTION_LOG {metrics['interaction_rows']} 行", metrics)


# ---------------------------------------------------------------------------
# SPEC-M5-07 · 场景隔离（并发）
# ---------------------------------------------------------------------------
def exec_concurrent_isolation(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    scenario_files = list(params.get("scenarios") or [])
    checks = list(params.get("checks") or [])
    results: dict = {}
    errors: dict = {}

    def _worker(rel: str) -> None:
        try:
            data = ctx.load_yaml(rel)
            spec = ScenarioSpec.from_dict(data)
            results[rel] = run_scenario(spec, repo_root=ctx.root)
        except Exception as exc:  # noqa: BLE001 - 线程内异常汇总上报
            errors[rel] = f"{type(exc).__name__}: {exc}"

    threads = [threading.Thread(target=_worker, args=(rel,)) for rel in scenario_files]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    problems: list = [f"{rel}: {errors[rel]}" for rel in errors]
    for check in checks:
        rel = str(check.get("scenario"))
        result = results.get(rel)
        if result is None:
            continue
        state = result.state_final
        path = str(check.get("path", ""))
        node: Any = state
        for part in path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                node = None
                break
        expect_value = check.get("expect")
        if expect_value == "ABSENT":
            if node is not None:
                problems.append(f"{rel} 的 {path} 应不存在，实际 {node}")
        elif node != expect_value:
            problems.append(f"{rel} 的 {path}={node!r} != 期望 {expect_value!r}（状态串扰）")

    metrics = {"scenarios": len(scenario_files),
               "run_ids": [results[rel].run_id for rel in results if rel in results]}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"{len(scenario_files)} 场景并发运行，状态互不串扰"
                         f"（各自终态断言全部成立）", metrics)


# ---------------------------------------------------------------------------
# SPEC-M5-08 · 规程同源（无硬编码阈值）
# ---------------------------------------------------------------------------
def exec_regulation_sourced(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    rule_id = str(params.get("rule_id", "PHYS-TX-LOAD"))
    threshold_index = int(params.get("threshold_index", 0))
    new_value = float(params.get("new_value", 0.5))
    regulation_file = str(params.get("regulation_file", "regulations/REG-TECH.yaml"))
    instance = str(params.get("instance", "dev-sim-park"))
    load_kw = float(params.get("load_kw", 700))
    at_s = _at_seconds(params, str(params.get("at", "+30m")))
    duration_s = int(params.get("load_duration_s", 6 * 3600))

    scenario_params = {
        "instance": instance,
        "clock_start": params.get("clock_start"),
        "events": [{"at": params.get("at", "+30m"), "type": "load.set",
                    "subject": str(params.get("device", "TX-02")),
                    "params": {"kw": load_kw, "duration_s": duration_s}}],
        "stop_conditions": [f"duration_s:{int(at_s + duration_s + 900)}"],
    }

    def _alarms(repo_root) -> list:
        spec = ScenarioSpec.from_dict(_scenario_dict(scenario_params))
        engine = ScenarioEngine(spec, repo_root=repo_root, persist=False)
        engine.run()
        return [a for a in engine.env.alarms.values() if a["code"] == rule_id]

    with _instance_path_env(ctx, instance):
        baseline = _alarms(ctx.root)

        # 临时仓库根：复制 ontology/ + regulations/，改一条阈值
        tmp_root = Path(ctx.root) / "runtime" / f"regs_tmp_{uuid.uuid4().hex[:8]}"
        (tmp_root / "regulations").parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(Path(ctx.root) / "regulations", tmp_root / "regulations")
        shutil.copytree(Path(ctx.root) / "ontology", tmp_root / "ontology")
        reg_path = tmp_root / regulation_file
        data = yaml.safe_load(reg_path.read_text(encoding="utf-8"))
        mutated = False
        for item in data.get("rules") or []:
            if item.get("id") == rule_id:
                item["thresholds"][threshold_index]["value"] = new_value
                mutated = True
        if not mutated:
            shutil.rmtree(tmp_root, ignore_errors=True)
            return _result(False, f"规程中未找到 {rule_id}", {})
        reg_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                            encoding="utf-8")
        try:
            mutated_result = _alarms(tmp_root)
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    problems: list = []
    expect_baseline = int(expect.get("baseline_alarms", 0))
    expect_mutated = int(expect.get("mutated_alarms", 1))
    if len(baseline) != expect_baseline:
        problems.append(f"原阈值下告警 {len(baseline)} 条 != 期望 {expect_baseline}")
    if len(mutated_result) != expect_mutated:
        problems.append(f"改阈值后告警 {len(mutated_result)} 条 != 期望 {expect_mutated}")
    if expect.get("mutated_level") and mutated_result:
        if mutated_result[0]["level"] != str(expect["mutated_level"]):
            problems.append(f"改后告警级别 {mutated_result[0]['level']}"
                            f" != 期望 {expect['mutated_level']}")

    metrics = {"baseline_alarms": len(baseline), "mutated_alarms": len(mutated_result),
               "rule": rule_id, "new_value": new_value}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"REG-TECH {rule_id} 阈值 {threshold_index} 改为 {new_value} 后"
                         f"告警 {len(baseline)}→{len(mutated_result)} 条（判据同源，零硬编码）",
                   metrics)


# ---------------------------------------------------------------------------
# 物理模型 · 负载率聚合（EVAL-M5-PHYS-P）
# ---------------------------------------------------------------------------
def exec_physics_load_rate(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    device = str(params.get("device", "TX-02"))
    kw = float(params.get("kw", 1100))
    at_s = _at_seconds(params, str(params.get("at", "+30m")))
    duration_s = int(params.get("load_duration_s", 6 * 3600))
    scenario_params = {
        "instance": str(params.get("instance", "dev-sim-park")),
        "clock_start": params.get("clock_start"),
        "events": [{"at": params.get("at", "+30m"), "type": "load.set",
                    "subject": device, "params": {"kw": kw, "duration_s": duration_s}}],
        "stop_conditions": [f"duration_s:{int(at_s + duration_s + 900)}"],
    }
    with _instance_path_env(ctx, scenario_params["instance"]):
        spec = ScenarioSpec.from_dict(_scenario_dict(scenario_params))
        engine = ScenarioEngine(spec, persist=False)
        # 只推进到覆盖窗口内读数（at+settle < at+duration，负载覆盖仍生效）
        _ticks_until(engine, at_s + float(params.get("settle_s", 900)))
    env = engine.env

    problems: list = []
    cell = env.read_measurement(device, "load_rate")
    if cell is None:
        problems.append("无 load_rate 量测")
    else:
        want_rate = float(expect.get("load_rate", 0.88))
        if abs(cell["value"] - want_rate) > 1e-6:
            problems.append(f"load_rate={cell['value']} != 期望 {want_rate}"
                            f"（{kw}kW/{expect.get('capacity_kva')}kVA）")
    rule_id = str(expect.get("rule", "PHYS-TX-LOAD"))
    level = str(expect.get("level", "P2"))
    hit = [a for a in env.alarms.values()
           if a["code"] == rule_id and a["source_ref"] == device]
    if not hit:
        problems.append(f"未生成 {rule_id} 告警")
    elif hit[0]["level"] != level:
        problems.append(f"告警级别 {hit[0]['level']} != 期望 {level}")
    text_expect = str(expect.get("text_contains", ""))
    if hit and text_expect and text_expect not in hit[0]["text"]:
        problems.append(f"告警文本不含 {text_expect!r}: {hit[0]['text']}")

    metrics = {"load_rate": cell["value"] if cell else None,
               "alarm_level": hit[0]["level"] if hit else None}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"{device} 回路聚合 {kw}kW / 容量 → load_rate="
                         f"{cell['value']}，触发 {rule_id} {level}（WARN）告警", metrics)


# ---------------------------------------------------------------------------
# DoD §6 · 三个开发场景一键跑（dev-02b 遥控链行为断言）
# ---------------------------------------------------------------------------
def exec_dev_scenarios(case: dict, ctx: Any) -> dict:
    """scenarios/dev-*.yaml 全部可一键跑（run_scenario 一站式）。

    断言全部数据驱动（params.scenarios[].expect 路径/值）：
    常见路径见 tests/test_m5.yaml EVAL-M5-DEV-P（如 breakers.SG-A02=OPEN、
    approval.granted 事件存在、dev-02b 遥控 SUCCEEDED）。
    """
    params = case.get("params") or {}
    problems: list = []
    metrics: dict = {"scenarios": len(params.get("scenarios") or [])}

    for entry in params.get("scenarios") or []:
        rel = str(entry.get("scenario"))
        spec_data = ctx.load_yaml(rel)
        instance = (spec_data.get("environment") or {}).get("park_instance")
        with _instance_path_env(ctx, instance):
            result = run_scenario(ScenarioSpec.from_dict(spec_data), repo_root=ctx.root)
        scenario_id = result.scenario_id

        # 事件断言（type/payload 键值）
        for want in entry.get("expect_events") or []:
            matched = any(
                e["type"] == str(want.get("type"))
                and all((e.get("payload") or {}).get(k) == v
                        for k, v in (want.get("payload") or {}).items())
                for e in getattr(result, "env_events", [])
            )
            if not matched:
                problems.append(f"{scenario_id}: 缺事件 {want}")

        # 终态路径断言（dot 路径；值或 ABSENT）
        for check in entry.get("expect_state") or []:
            node: Any = result.state_final
            for part in str(check.get("path", "")).split("."):
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    node = None
                    break
            if check.get("expect") == "ABSENT":
                if node is not None:
                    problems.append(f"{scenario_id}: {check.get('path')} 应缺失，实际 {node!r}")
            elif node != check.get("expect"):
                problems.append(f"{scenario_id}: {check.get('path')}={node!r}"
                                f" != 期望 {check.get('expect')!r}")

    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"{len(params.get('scenarios') or [])} 个开发场景一键跑通，"
                         f"遥控审批链/告警/终态断言全部成立", metrics)


# ---------------------------------------------------------------------------
# DoD §6 · 性能门槛（100×24h 仿真步 < 30s）
# ---------------------------------------------------------------------------
def exec_perf_ticks(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    days = int(params.get("days", 100))
    step_minutes = int(params.get("step_minutes", 15))
    instance = str(params.get("instance", "seed"))
    ticks_per_day = int(24 * 60 / step_minutes)

    with _instance_path_env(ctx, instance):
        template_params = {
            "instance": instance,
            "clock_start": params.get("clock_start"),
            "stop_conditions": ["duration_s:86400"],
        }
        template = ScenarioEngine(ScenarioSpec.from_dict(_scenario_dict(template_params)),
                                  persist=False)
        total_ticks = 0
        start = time.perf_counter()  # MONOTONIC 语义计时（性能测量，非电价判定）
        for _day in range(days):
            env = template.env.deep_copy()
            engine = ScenarioEngine(template.spec, env=env, persist=False)
            engine.run()
            total_ticks += engine.tick_count
        measured_ms = (time.perf_counter() - start) * 1000.0

    max_ms = float(expect.get("max_ms", 30000))
    metrics = {"days": days, "ticks_per_day": ticks_per_day, "total_ticks": total_ticks,
               "measured_ms": round(measured_ms, 1), "max_ms": max_ms}
    if total_ticks != days * ticks_per_day:
        return _result(False, f"总步数 {total_ticks} != 期望 {days * ticks_per_day}", metrics)
    if measured_ms > max_ms:
        return _result(False, f"{days}×24h 仿真步用时 {measured_ms:.0f}ms > {max_ms:.0f}ms 门槛",
                       metrics)
    return _result(True, f"{days}×24h（{total_ticks} 步 ×{step_minutes}min）用时 "
                         f"{measured_ms:.0f}ms ≤ {max_ms:.0f}ms", metrics)


EXECUTORS = {
    "m5.determinism": exec_determinism,
    "m5.price_boundary": exec_price_boundary,
    "m5.no_wallclock_pricing": exec_no_wallclock_pricing,
    "m5.simulate_interface": exec_simulate_interface,
    "m5.persona_script": exec_persona_script,
    "m5.fault": exec_fault,
    "m5.evidence_pack": exec_evidence_pack,
    "m5.concurrent_isolation": exec_concurrent_isolation,
    "m5.regulation_sourced": exec_regulation_sourced,
    "m5.physics_load_rate": exec_physics_load_rate,
    "m5.dev_scenarios": exec_dev_scenarios,
    "m5.perf_ticks": exec_perf_ticks,
}
