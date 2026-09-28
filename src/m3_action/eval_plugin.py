# -*- coding: utf-8 -*-
"""m3_action 的 EVAL 执行器插件（tests/test_m3.yaml 数据驱动用例）。

插件契约（tests/EVAL-SCHEMA.md §4）：暴露 ``EXECUTORS: dict[str, callable]``。

三个执行器（全部只读 case.params 声明的数据，无硬编码特判）：
- ``m3.execute``：网关场景驱动——按 steps 声明（request/approve/expire/restart/
  override/policy_query/snapshot/crash_claim）操作沙箱网关，按 expect 声明断言
  （结果/判定/事件序/事件缺席/payload/快照相等/执行计数）；
- ``m3.registry``：注册表 vs ontology/actions.yaml diff + 不可改清单双重表达 +
  生命周期迁移表 vs tests/fixtures/frozen_state_machines.yaml；
- ``m3.negative_matrix``：跑 tests/negative_matrix.yaml 只读证明矩阵。

每个用例在 runtime/m3_eval/<case-id> 沙箱内执行（先清空，独立可复跑）。
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

import yaml

__all__ = ["EXECUTORS"]


def _result(passed: bool, detail: str, metrics: dict | None = None) -> dict:
    return {"passed": bool(passed), "detail": str(detail), "metrics": metrics or {}}


def _sandbox(ctx: Any, case: dict) -> Path:
    root = Path(ctx.root) / "runtime" / "m3_eval" / str(case.get("id") or "case")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


# ===========================================================================
# m3.execute · 网关场景驱动
# ===========================================================================
def _build_env(env_spec: dict, repo_root: Path):
    from m5_simulation.env import load_scenario

    spec = {
        "identity": {"scenario_id": "m3-eval", "version": "1.0",
                     "owner": "m3", "tags": ["m3", "eval"]},
        "sut": {"target": "MODULE", "module": "m3_action"},
        "environment": {
            "park_instance": str(env_spec.get("park_instance", "seed")),
            "clock_start": str(env_spec.get("clock_start", "2026-09-15T08:00:00Z")),
            "speed": float(env_spec.get("speed", 60.0)),
            "injections": [],
        },
        "user_model": {"persona": "OPERATOR", "behavior_script": []},
        "interactions": {"max_turns": 8, "timeout_s": 600},
        "events": [],
        "constraints": {"budget": {"token": 0, "action": 0}, "stop_conditions": []},
        "metrics": [],
        "provenance": {"source": "m3-eval", "created_at": "2026-09-28T00:00:00Z",
                       "notes": "m3-eval"},
    }
    env = load_scenario(spec, repo_root=repo_root)
    for code, order in (env_spec.get("switch_orders") or {}).items():
        env.switch_orders[str(code)] = {"code": str(code), **dict(order)}
    return env


def _build_gateway(params: dict, sandbox: Path, env, repo_root: Path):
    from m3_action import ActionGateway, CapabilityDescriptor

    gw_params = dict(params.get("gateway") or {})
    gateway = ActionGateway(
        sandbox, env=env,
        evaluation=gw_params.get("evaluation", True),
        approval_timeout_s=float(gw_params.get("approval_timeout_s", 300)),
        role_overrides={r: dict(m) for r, m in (gw_params.get("role_overrides") or {}).items()},
        actor_roles=dict(gw_params.get("actor_roles") or {}) or None,
        isolate_execution_env=bool(gw_params.get("isolate_execution_env", False)),
        dual_approvers=gw_params.get("dual_approvers"),
        events_dir=sandbox / "events",  # 用例事件流隔离（互不污染、可复跑）
        repo_root=repo_root,
    )
    for descriptor in params.get("register") or []:
        gateway.register_capability(CapabilityDescriptor.from_dict(dict(descriptor)))
    return gateway


def _match_subsequence(types: list, pattern: list) -> bool:
    iterator = iter(types)
    return all(any(item == want or want == "*" for item in iterator) for want in pattern)
    # 注：any 消费迭代器至首个匹配——按序子序列匹配（与 run_evals event_sequence 同口径）


def exec_execute(case: dict, ctx: Any) -> dict:
    import os

    from contracts import ActionRequest

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    repo_root = Path(ctx.root)
    sandbox = _sandbox(ctx, case)
    env_flags = {str(k): str(v) for k, v in (params.get("env_flags") or {}).items()}
    saved_env = {k: os.environ.get(k) for k in env_flags}
    os.environ.update(env_flags)
    try:
        return _exec_execute_inner(case, params, expect, repo_root, sandbox)
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _exec_execute_inner(case: dict, params: dict, expect: dict,
                        repo_root: Path, sandbox: Path) -> dict:
    from contracts import ActionRequest
    env = _build_env(dict(params.get("env") or {}), repo_root) \
        if params.get("env") is not None else None
    snapshots: dict[str, dict] = {}
    if env is not None:
        snapshots["s0"] = env.state_final()

    gateway = _build_gateway(params, sandbox, env, repo_root)
    results: dict[str, Any] = {}
    decisions: dict[str, Any] = {}
    overrides: dict[str, Any] = {}
    problems: list[str] = []
    executed_after: dict[str, int] = {}

    for step in params.get("steps") or []:
        op = str(step.get("op"))
        step_id = str(step.get("id") or op)
        if op == "request":
            result = gateway.execute_action(
                dict(step.get("request") or {}),
                mode=str(step.get("mode", "SIMULATION")),
                now=step.get("now"))
            results[step_id] = result
            executed_after[step_id] = gateway.executor.execution_count()
            decisions[step_id] = gateway.decision_of(step.get("request", {}).get("action_id"))
        elif op == "approve":
            results[step_id] = gateway.submit_approval(
                str(step.get("action_id")), str(step.get("decision")),
                str(step.get("approver")), now=step.get("now"))
        elif op == "expire":
            outcomes = gateway.check_approval_timeouts(step.get("now"))
            results[step_id] = outcomes[0] if outcomes else None
        elif op == "restart":
            gateway = _build_gateway(params, sandbox, env, repo_root)
        elif op == "override":
            overrides[step_id] = gateway.policy.set_role_override(
                str(step.get("role")), str(step.get("capability")),
                str(step.get("decision")))
        elif op == "policy_query":
            decisions[step_id] = gateway.query_policy(
                str(step.get("capability")), step.get("actor")).value
        elif op == "snapshot":
            if env is None:
                problems.append(f"{step_id}: 无 env 不可快照")
            else:
                snapshots[step_id] = env.state_final()
        elif op == "crash_claim":
            # 白盒崩溃注入：只落幂等 claim（执行器崩溃于副作用之前），不做后续
            payload = dict(step.get("request") or {})
            request = ActionRequest.from_dict(payload)
            gateway.executor.claim(
                request.idempotency_key, action_id=request.action_id,
                capability=request.capability, arguments=request.arguments,
                pending_result={"action_id": request.action_id, "status": "REQUESTED",
                                "result_refs": [], "observation": "已受理（崩溃注入：claim 后中断）",
                                "evidence": {"intended": {"action_id": request.action_id,
                                                          "capability": request.capability},
                                             "issued": None, "observed": None},
                                "latency_ms": 0,
                                "trace_id": f"trace-{request.task_id}", "error": None})
        else:
            problems.append(f"{step_id}: 未知 op {op!r}")

    # ---------------- 断言：results
    for step_id, want in (expect.get("results") or {}).items():
        result = results.get(step_id)
        if result is None and step_id not in results:
            problems.append(f"results[{step_id}]: 步骤未产出结果")
            continue
        if result is None:
            if str(want.get("status")) != "None":
                problems.append(f"results[{step_id}]: 无结果（期望 {want}）")
            continue
        want_status = want.get("status")
        if want_status is not None and result.status.value != str(want_status):
            problems.append(f"results[{step_id}].status={result.status.value}"
                            f" != 期望 {want_status}")
        want_action = want.get("action_id")
        if want_action is not None and result.action_id != str(want_action):
            problems.append(f"results[{step_id}].action_id={result.action_id}"
                            f" != 期望 {want_action}")
        want_error = want.get("error_code", "__unset__")
        if want_error != "__unset__":
            got_error = result.error.code if result.error is not None else None
            if got_error != (None if want_error is None else str(want_error)):
                problems.append(f"results[{step_id}].error_code={got_error!r}"
                                f" != 期望 {want_error!r}")
        want_contains = want.get("error_contains")
        if want_contains:
            message = result.error.message if result.error is not None else ""
            if str(want_contains) not in message:
                problems.append(f"results[{step_id}].error.message 不含 {want_contains!r}"
                                f"（实际: {message[:120]!r}）")

    # ---------------- 断言：decisions（step 级 or results 内嵌）
    for step_id, want in (expect.get("decisions") or {}).items():
        got = decisions.get(step_id)
        if got != str(want):
            problems.append(f"decisions[{step_id}]={got!r} != 期望 {want!r}")

    # ---------------- 断言：overrides
    for step_id, want in (expect.get("overrides") or {}).items():
        got = overrides.get(step_id)
        if got is None:
            problems.append(f"overrides[{step_id}]: 无覆盖尝试记录")
            continue
        for key, value in want.items():
            if got.get(key) != value and str(got.get(key)) != str(value):
                problems.append(f"overrides[{step_id}].{key}={got.get(key)!r}"
                                f" != 期望 {value!r}")

    # ---------------- 断言：事件序（任务流，按序子序列）+ 缺席 + payload
    import json

    events_dir = sandbox / "events"
    stream_files: dict[str, list[dict]] = {}
    if events_dir.is_dir():
        for path in sorted(events_dir.glob("task-*.jsonl")):
            # 文件名 = task-<task_id>（EventJournal.task_stream 前缀）→ 键用 task_id
            task_id = path.stem[len("task-"):]
            stream_files[task_id] = [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
    all_events = [event for rows in stream_files.values() for event in rows]
    # 角色覆盖审计事件（policy:* 主题）落审计流——payload 断言池需一并纳入
    if events_dir.is_dir():
        for path in sorted(events_dir.glob("subject-*.jsonl")):
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()]
            all_events.extend(rows)

    for stream_name, pattern in (expect.get("event_seqs") or {}).items():
        rows = stream_files.get(stream_name)
        if rows is None:
            problems.append(f"event_seqs[{stream_name}]: 事件流不存在")
            continue
        types = [r.get("type") for r in rows]
        if not _match_subsequence(types, list(pattern)):
            problems.append(f"event_seqs[{stream_name}]: 事件序 {types} 未按序包含 {pattern}")
    for stream_name, absent in (expect.get("event_types_absent") or {}).items():
        rows = stream_files.get(stream_name, [])
        types = {r.get("type") for r in rows}
        for etype in absent:
            if etype in types:
                problems.append(f"event_types_absent[{stream_name}]: {etype} 不应出现")
    for want in (expect.get("event_payloads") or {}):
        stream_name = str(want.get("stream", "__all__"))
        pool = stream_files.get(stream_name, all_events)
        etype = want.get("type")
        contains = want.get("contains") or {}
        hits = [e for e in pool if e.get("type") == etype
                and all((e.get("payload") or {}).get(k) == v for k, v in contains.items())]
        if want.get("stream") and stream_name not in stream_files:
            problems.append(f"event_payloads: 流 {stream_name} 不存在")
        elif not hits:
            problems.append(f"event_payloads: 无 {etype}（payload 含 {contains}）事件")

    # ---------------- 断言：快照相等（零副作用）
    for pair in expect.get("snapshots_equal") or []:
        a, b = pair[0], pair[1]
        if snapshots.get(a) is None or snapshots.get(b) is None:
            problems.append(f"snapshots_equal: 快照缺失 {pair}")
        elif snapshots[a] != snapshots[b]:
            problems.append(f"snapshots_equal: {a} != {b}（环境状态 diff 非空）")

    # ---------------- 断言：执行计数
    want_exec = expect.get("executions")
    if want_exec is not None:
        got_exec = gateway.executor.execution_count()
        if got_exec != int(want_exec):
            problems.append(f"executions={got_exec} != 期望 {want_exec}")

    metrics = {
        "steps": len(params.get("steps") or []),
        "statuses": {k: (v.status.value if v is not None else None)
                     for k, v in results.items()},
        "decisions": {k: (v.value if hasattr(v, "value") else v)
                      for k, v in decisions.items()},
        "executions": gateway.executor.execution_count(),
        "events_total": len(all_events),
    }
    if problems:
        return _result(False, "；".join(problems[:12]), metrics)
    return _result(True, f"{metrics['steps']} 步全部符合期望（执行 {metrics['executions']} 次副作用）",
                   metrics)


# ===========================================================================
# m3.registry · 注册表/不可改清单/生命周期表 一致性
# ===========================================================================
def exec_registry(case: dict, ctx: Any) -> dict:
    from m3_action import (
        ACTION_TRANSITIONS,
        assert_immutable_consistency,
        load_default_registry,
        registry_vs_actions_table_diff,
    )

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    repo_root = Path(ctx.root)
    problems: list[str] = []

    registry = load_default_registry(repo_root)
    diff = registry_vs_actions_table_diff(registry, repo_root)
    if expect.get("diff_empty", True) and diff:
        problems.append(f"注册表 vs 动作表 diff 非空: {diff[:6]}")
    want_count = expect.get("action_count")
    if want_count is not None and len(registry) != int(want_count):
        problems.append(f"注册动作数 {len(registry)} != 期望 {want_count}")

    immutable = assert_immutable_consistency(repo_root)
    if expect.get("immutable_consistent", True) and immutable["diffs"]:
        problems.append(f"不可改清单双重表达不一致: {immutable['diffs']}")
    want_immutable = expect.get("immutable_deny")
    if want_immutable is not None and sorted(want_immutable) != immutable["immutable_deny"]:
        problems.append(f"不可改 DENY 清单 {immutable['immutable_deny']} != 期望 {want_immutable}")

    # 生命周期迁移表 vs 冻结表（tests/fixtures/frozen_state_machines.yaml）
    if expect.get("lifecycle_table_matches_fixture", False):
        fixture = yaml.safe_load(
            (repo_root / "tests" / "fixtures" / "frozen_state_machines.yaml")
            .read_text(encoding="utf-8"))
        frozen = fixture["machines"]["action"]
        if ACTION_TRANSITIONS != frozen:
            problems.append("ACTION_TRANSITIONS 与 frozen_state_machines.yaml 的"
                            " action 机 diff 非空")

    # 合并注册红线：create.switch_order 与 execute.remote_control 必须独立注册
    if expect.get("split_registration", False):
        a = registry.by_action("create.switch_order")
        b = registry.by_action("execute.remote_control")
        if a is None or b is None:
            problems.append("create.switch_order / execute.remote_control 未注册")
        elif a.capability_id == b.capability_id:
            problems.append("create.switch_order 与 execute.remote_control 被合并注册（红线）")
        elif a.risk_level == b.risk_level and a.default_policy == b.default_policy \
                and a.risk_level.value == "MEDIUM":
            problems.append("两动作风险/Policy 声明未区分（独立注册语义丢失）")

    metrics = {"actions": len(registry), "diff": len(diff),
               "immutable": immutable["immutable_deny"],
               "permanent_ask": immutable["permanent_ask"]}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"注册表与动作表对齐（{len(registry)} 动作，diff 空）；"
                         f"不可改清单双重表达一致", metrics)


# ===========================================================================
# m3.negative_matrix · 只读证明矩阵
# ===========================================================================
def exec_negative_matrix(case: dict, ctx: Any) -> dict:
    from m3_action.negative_test import run_negative_matrix

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    matrix_rel = str(params.get("matrix") or "tests/negative_matrix.yaml")
    matrix_path = Path(ctx.root) / matrix_rel
    if not matrix_path.is_file():
        return _result(False, f"矩阵文件不存在: {matrix_rel}", {})
    report = run_negative_matrix(matrix_path, repo_root=Path(ctx.root))

    problems: list[str] = list(report["failures"])
    want_actions = expect.get("actions")
    if want_actions is not None and report["actions_total"] != int(want_actions):
        problems.append(f"矩阵动作数 {report['actions_total']} != 期望 {want_actions}")
    if expect.get("side_effect_free", True):
        with_side_effects = [r["capability"] for r in report["rows"]
                             if not r["side_effect_free"]]
        if with_side_effects:
            problems.append(f"存在副作用: {with_side_effects}")
    metrics = {"actions": report["actions_total"],
               "decisions": {r["capability"]: r["decision"] for r in report["rows"]},
               "statuses": {r["capability"]: r["status"] for r in report["rows"]}}
    if problems:
        return _result(False, "；".join(problems[:10]), metrics)
    decisions_summary = "/".join(sorted(set(metrics["decisions"].values())))
    return _result(True, (f"{report['actions_total']} 个写类动作全部 {decisions_summary}，"
                          "M5 环境状态 diff 全空（只读是结论不是声明）"), metrics)


EXECUTORS: dict[str, Callable[[dict, Any], dict]] = {
    "m3.execute": exec_execute,
    "m3.registry": exec_registry,
    "m3.negative_matrix": exec_negative_matrix,
}
