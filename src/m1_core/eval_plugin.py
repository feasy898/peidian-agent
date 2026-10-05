# -*- coding: utf-8 -*-
"""m1_core 的 EVAL 执行器插件（tests/test_m1.yaml 数据驱动用例）。

插件契约（tests/EVAL-SCHEMA.md §4）：暴露 ``EXECUTORS: dict[str, callable]``；
执行器签名 ``fn(case: dict, ctx) -> {"passed": bool, "detail": str, "metrics": dict}``。

执行器（全部只读 case.params 声明的数据，无针对特定输入的硬编码特判）：
- ``m1.scenario``：内核场景驱动——按 steps 声明（run_task/drive/resume/snapshot/
  restore/request_completion/transition/seed_* …）操作沙箱内核，按 expect 声言
  断言（状态/事件序/事件载荷/拒绝事件/trace 回放/todos/verdicts/预算/证据）；
- ``m1.replay``：伪阶段序（Model 先于 Prepare 等）注入必被回放校验拒绝，
  且真实运行零此类序（SPEC-M1-01 负例）；
- ``m1.table``：状态机迁移表双写一致性 + 全矩阵守卫行为（SPEC-M1-02）；
- ``m1.budget``：预算检查点四口径矩阵（SPEC-M1-05）；
- ``m1.middleware``：链可插拔——全移除/单移除后 01/02/06 场景语义不变，
  注册序执行（SPEC-M1-08）；
- ``m1.model``：model_client mock 确定性/成本/脚本耗尽 + openai_like 传输
  注入的重试/超时分类（离线）；
- ``m1.persona_llm``：M5 persona LLM 模式经 mock provider 离线接线。

每个用例在 runtime/m1_eval/<case-id> 沙箱内执行（先清空，独立可复跑）。
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

__all__ = ["EXECUTORS"]


def _result(passed: bool, detail: str, metrics: dict | None = None) -> dict:
    return {"passed": bool(passed), "detail": str(detail), "metrics": metrics or {}}


def _sandbox(ctx: Any, case: dict, suffix: str = "") -> Path:
    root = Path(ctx.root) / "runtime" / "m1_eval" / f"{case.get('id') or 'case'}{suffix}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


# ===========================================================================
# 场景装配（M2 信息层 + M5 环境 + M3 网关 + M1 内核，全沙箱隔离）
# ===========================================================================
def _build_env(env_spec: dict, repo_root: Path):
    from m5_simulation.env import load_scenario

    spec = {
        "identity": {"scenario_id": "m1-eval", "version": "1.0",
                     "owner": "m1", "tags": ["m1", "eval"]},
        "sut": {"target": "MODULE", "module": "m1_core"},
        "environment": {
            "park_instance": str(env_spec.get("park_instance", "seed")),
            "clock_start": str(env_spec.get("clock_start", "2026-09-28T08:00:00Z")),
            "speed": float(env_spec.get("speed", 60.0)),
            "injections": [],
        },
        "user_model": {"persona": "OPERATOR", "behavior_script": []},
        "interactions": {"max_turns": 8, "timeout_s": 600},
        "events": [],
        "constraints": {"budget": {"token": 0, "action": 0}, "stop_conditions": []},
        "metrics": [],
        "provenance": {"source": "m1-eval", "created_at": "2026-09-28T00:00:00Z",
                       "notes": "m1-eval"},
    }
    return load_scenario(spec, repo_root=repo_root)


def _fixed_clock(params: dict) -> Callable[[], str]:
    """确定性时钟：固定值（now）或按 now_list 顺序推进（末值保持）。"""
    stamps = [str(s) for s in (params.get("now_list") or [])]
    fixed = str(params.get("now") or "2026-09-28T08:00:00Z")
    if not stamps:
        return lambda: fixed
    state = {"index": 0}

    def tick() -> str:
        value = stamps[min(state["index"], len(stamps) - 1)]
        state["index"] += 1
        return value

    return tick


def _build_harness(ctx: Any, case: dict, params: dict, sandbox: Path):
    from m1_core import AgentCore, TaskContext, default_middlewares
    from m2_information import InformationLayer
    from m3_action import ActionGateway

    repo_root = Path(ctx.root)
    clock = _fixed_clock(params)
    from m4_semantic.regulation import rule_id_checker

    info = InformationLayer(sandbox, now_fn=clock,
                            # SPEC-M4-05 / ADDENDUM §B 联动：regulation_refs 存在性核对
                            rule_id_checker=rule_id_checker(repo_root=repo_root))
    env = _build_env(dict(params.get("env") or {}), repo_root) \
        if params.get("env") is not None else None
    gateway = ActionGateway(
        sandbox / "gateway", env=env,
        evaluation=bool((params.get("gateway") or {}).get("evaluation", True)),
        events_dir=sandbox / "events",
        repo_root=repo_root,
    )
    agent_cfg = dict(params.get("agent") or {})
    middleware_mode = str(agent_cfg.get("middlewares", "default"))
    if middleware_mode == "default":
        middlewares = default_middlewares(agent_cfg.get("safety_directives"))
    elif middleware_mode == "empty":
        middlewares = []
    else:
        middlewares = None  # 由调用方另行装配
    agent = AgentCore(
        info, gateway,
        journal_dir=sandbox / "m1_core" / "loop",
        now_fn=clock,
        middlewares=middlewares,
        blocking_levels=agent_cfg.get("blocking_levels", ("P0",)),
    )
    task_cfg = dict(params.get("task") or {})
    task_id = str(task_cfg.get("task_id") or "task-m1")
    task_ctx = TaskContext(
        task_id=task_id,
        actor_user=str(task_cfg.get("actor_user", "OP-001")),
        actor_agent=str(task_cfg.get("actor_agent", "park-agent@v1")),
        trace_id=str(task_cfg.get("trace_id", "") or ""),
        plan=list(task_cfg.get("plan") or []),
        todos=list(task_cfg.get("todos") or []),
        budget=dict(task_cfg.get("budget") or {}),
        current_stage=str(task_cfg.get("current_stage", "INTAKE")),
        max_turns=int(task_cfg.get("max_turns", 8)),
        model_script=list(params.get("script") or []),
        model_options=dict(params.get("model_options") or {}),
    )
    agent.bind_context(task_ctx)
    return {"agent": agent, "info": info, "gateway": gateway, "env": env,
            "task_id": task_id, "task_ctx": task_ctx, "sandbox": sandbox,
            "checkpoints": {}, "errors": [], "refs": {}}


# ===========================================================================
# m1.scenario · 内核场景驱动
# ===========================================================================
def _step_run(harness: dict, step: dict, op: str) -> None:
    from m1_core import ResumeEvent

    agent = harness["agent"]
    task_id = harness["task_id"]
    if op == "create":
        cfg = harness["task_ctx"]
        harness["info"].create_task(
            task_id, user_input=str(step.get("user_input", "评测任务")),
            trace_id=cfg.trace_id_of(), plan=list(cfg.plan or []),
            todos=list(cfg.todos or []), budget=dict(cfg.budget or {}),
            current_stage=str(cfg.current_stage or "INTAKE"))
    elif op == "run_task":
        agent.run_task(str(step.get("user_input", "") or "评测任务"),
                       harness["task_ctx"])
    elif op == "drive":
        agent.run_loop(task_id)
    elif op == "resume":
        event_cfg = dict(step.get("event") or {})
        agent.resume_task(task_id, ResumeEvent(
            kind=str(event_cfg.get("kind", "USER_INPUT")),
            text=str(event_cfg.get("text", "") or ""),
            payload=dict(event_cfg.get("payload") or {}),
            at=str(event_cfg.get("at", "") or "")))
    elif op == "snapshot":
        payload = harness["info"].snapshot(task_id)
        harness["checkpoints"][str(step.get("as", "ckpt"))] = payload["checkpoint_id"]
    elif op == "restore":
        key = str(step.get("from", "ckpt"))
        checkpoint_id = harness["checkpoints"].get(key)
        if checkpoint_id is None:
            raise ValueError(f"snapshot 步骤未登记: {key}")
        harness["info"].restore(checkpoint_id)
    elif op == "request_completion":
        from m1_core import CompletionClaim

        agent.request_completion(task_id, CompletionClaim.from_dict(step.get("claim")))
    elif op == "transition":
        agent.machine.transition(task_id, str(step.get("to")))
    elif op == "seed_evidence":
        rel = harness["info"].save_evidence(
            task_id, str(step.get("name", "ev")),
            dict(step.get("payload") or {}),
            trace_id=f"trace-{task_id}")
        harness["refs"][str(step.get("name", "ev"))] = rel
    elif op == "seed_artifact":
        cfg = dict(step or {})
        record = harness["info"].artifacts.create(
            task_id, type=str(cfg.get("type", "REPORT")),
            schema_id=str(cfg.get("schema_id", "report.daily@v1")),
            content=dict(cfg.get("content") or {}),
            action_id=str(cfg.get("action_id", "act-seed")),
            trace_id=f"trace-{task_id}")
        harness["info"].artifacts.transition(record.artifact_id, "VALIDATING",
                                             trace_id=f"trace-{task_id}")
        final = harness["info"].artifacts.get(record.artifact_id)
        if cfg.get("expect_status") and final.status.value != str(cfg["expect_status"]):
            raise AssertionError(
                f"seed_artifact 状态 {final.status.value} != 期望 {cfg['expect_status']}")
    elif op == "seed_event":
        harness["info"].event_log.append(
            {"type": str(step.get("type")), "subject": str(step.get("subject", "seed")),
             "payload": dict(step.get("payload") or {}),
             "trace_id": f"trace-{task_id}", "producer": "M5"},
            stream=f"task-{task_id}", now_fn=agent._now)
    elif op == "clear_middlewares":
        agent.chain.clear()
    elif op == "remove_middleware":
        agent.chain.remove(str(step.get("name", "")))
    elif op == "set_budget":
        harness["info"].commit_state(task_id, {
            "budget": dict(step.get("budget") or {}),
            "trace_id": f"trace-{task_id}"})
    else:
        raise ValueError(f"未知 step op: {op!r}")


def _match_subsequence(types: list, pattern: list) -> bool:
    iterator = iter(types)
    return all(any(item == want for item in iterator) for want in pattern)


def _scenario_assertions(harness: dict, expect: dict, problems: list) -> dict:
    from m1_core import validate_replay

    agent = harness["agent"]
    info = harness["info"]
    task_id = harness["task_id"]
    state = info.get_task(task_id)
    events = info.event_log.events_for_task(task_id)
    replay = validate_replay(agent._trace_of(task_id).entries())

    # ---- 状态/阶段/预算/证据
    if expect.get("status") is not None and state.status.value != str(expect["status"]):
        problems.append(f"状态 {state.status.value} != 期望 {expect['status']}")
    if expect.get("current_stage") is not None and \
            state.current_stage != str(expect["current_stage"]):
        problems.append(f"当前阶段 {state.current_stage} != 期望 {expect['current_stage']}")
    budget_expect = dict(expect.get("budget") or {})
    if budget_expect.get("token_used") is not None and \
            state.budget.token_used != int(budget_expect["token_used"]):
        problems.append(f"token_used {state.budget.token_used}"
                        f" != 期望 {budget_expect['token_used']}")
    if budget_expect.get("action_used") is not None and \
            state.budget.action_used != int(budget_expect["action_used"]):
        problems.append(f"action_used {state.budget.action_used}"
                        f" != 期望 {budget_expect['action_used']}")
    if expect.get("evidence_count") is not None and \
            len(state.evidence_refs) != int(expect["evidence_count"]):
        problems.append(f"evidence 数 {len(state.evidence_refs)}"
                        f" != 期望 {expect['evidence_count']}")
    if expect.get("verdicts") is not None:
        got = [v.get("verdict") for v in agent.last_verdicts.get(task_id, [])]
        if got != list(expect["verdicts"]):
            problems.append(f"完成判定序 {got} != 期望 {list(expect['verdicts'])}")
    if expect.get("executions") is not None:
        executed = harness["gateway"].executor.execution_count()
        if executed != int(expect["executions"]):
            problems.append(f"副作用执行数 {executed} != 期望 {expect['executions']}")

    # ---- todos
    todos = {t.id: t.status.value for t in state.todos}
    for want in expect.get("todos") or []:
        todo_id, status = str(want.get("id")), str(want.get("status"))
        if todo_id not in todos:
            problems.append(f"todos 缺 {todo_id}（现有 {sorted(todos)}）")
        elif todos[todo_id] != status:
            problems.append(f"todo {todo_id} 状态 {todos[todo_id]} != 期望 {status}")
    for prefix in expect.get("todos_absent") or []:
        hits = [i for i in todos if i.startswith(str(prefix))]
        if hits:
            problems.append(f"todos 不应出现 {prefix}*（命中 {hits}）")
    if expect.get("todos_gap_prefix") is not None:
        prefix = str(expect["todos_gap_prefix"])
        gap_hits = [i for i in todos if i.startswith(prefix) and todos[i] == "PENDING"]
        if not gap_hits:
            problems.append(f"todos 无 PENDING 的 gap 项（前缀 {prefix}；现有 {sorted(todos)}）")

    # ---- 产物
    for want in expect.get("artifacts") or []:
        matches = [r for r in info.store.list_artifacts(task_id)
                   if r.schema_id == str(want.get("schema_id"))
                   and r.status.value == str(want.get("status"))]
        if not matches:
            statuses = [(r.schema_id, r.status.value)
                        for r in info.store.list_artifacts(task_id)]
            problems.append(f"产物 {want} 不存在（现有 {statuses}）")

    # ---- 事件断言（统一任务流：M1/M2/M3 同分片）
    types = [e.get("type") for e in events]
    for stream_name, pattern in (expect.get("event_seqs") or {}).items():
        if not _match_subsequence(types, list(pattern)):
            problems.append(f"事件序未按序包含 {pattern}（实际 {types}）")
    for absent_type in (expect.get("event_types_absent") or []):
        if absent_type in types:
            problems.append(f"事件 {absent_type} 不应出现")
    for want in expect.get("event_payloads") or []:
        contains = dict(want.get("contains") or {})
        hits = [e for e in events if e.get("type") == want.get("type")
                and all((e.get("payload") or {}).get(k) == v
                        for k, v in contains.items())]
        if not hits:
            problems.append(f"无 {want.get('type')} 事件（payload 含 {contains}）")
    for want in expect.get("rejected_events") or []:
        hits = [e for e in events if e.get("type") == "task.status_changed"
                and (e.get("payload") or {}).get("rejected") is True
                and (e.get("payload") or {}).get("from") == want.get("from")
                and (e.get("payload") or {}).get("to") == want.get("to")]
        if not hits:
            problems.append(f"缺拒绝事件 {want}（payload.rejected=true）")
    for want in expect.get("accepted_transitions") or []:
        hits = [e for e in events if e.get("type") == "task.status_changed"
                and (e.get("payload") or {}).get("accepted") is True
                and (e.get("payload") or {}).get("from") == want.get("from")
                and (e.get("payload") or {}).get("to") == want.get("to")]
        if not hits:
            problems.append(f"缺合法迁移事件 {want}")
    for banned_to in expect.get("no_accepted_transitions") or []:
        hits = [e for e in events if e.get("type") == "task.status_changed"
                and (e.get("payload") or {}).get("accepted") is True
                and (e.get("payload") or {}).get("to") == banned_to]
        if hits:
            problems.append(f"不应出现合法迁移到 {banned_to}（命中 {len(hits)} 次）")
    for etype, count in (expect.get("event_counts") or {}).items():
        got = sum(1 for e in events if e.get("type") == etype)
        if got != int(count):
            problems.append(f"事件 {etype} 数 {got} != 期望 {count}")

    # ---- 成本上报（SPEC-M1-10）：每轮一个 cost 事件，token 累计 = budget.token_used
    cost_expect = dict(expect.get("cost_events") or {})
    if cost_expect:
        cost_events = [e for e in events
                       if e.get("type") == "budget.warning"
                       and isinstance((e.get("payload") or {}).get("cost"), dict)]
        if cost_expect.get("count") is not None and \
                len(cost_events) != int(cost_expect["count"]):
            problems.append(f"cost 事件数 {len(cost_events)} != 期望 {cost_expect['count']}")
        turns_of_cost = [((e.get("payload") or {}).get("cost") or {}).get("turn")
                         for e in cost_events]
        if cost_events and len([t for t in turns_of_cost if t is not None]) != \
                len(set(turns_of_cost)):
            problems.append(f"cost 事件 turn 重复: {turns_of_cost}")
        tokens_total = sum(int(((e.get("payload") or {}).get("cost") or {}).get("tokens") or 0)
                           for e in cost_events)
        if cost_expect.get("tokens_total") is not None:
            if tokens_total != int(cost_expect["tokens_total"]):
                problems.append(f"cost token 合计 {tokens_total}"
                                f" != 期望 {cost_expect['tokens_total']}")
            if tokens_total != state.budget.token_used:
                problems.append(f"cost token 合计 {tokens_total} != budget.token_used"
                                f" {state.budget.token_used}")
        if replay["complete_turns"] and len(cost_events) < replay["complete_turns"]:
            problems.append(f"cost 事件 {len(cost_events)} 少于完整轮数"
                            f" {replay['complete_turns']}（缺上报轮次=违规）")

    # ---- 阶段门禁事件（SPEC-M1-04）
    for want in expect.get("stage_gates") or []:
        hits = [e for e in events if e.get("type") == "task.stage_gate"
                and (e.get("payload") or {}).get("stage") == want.get("stage")
                and (e.get("payload") or {}).get("verdict") == want.get("verdict")]
        seen = [((e.get("payload") or {}).get("stage"),
                 (e.get("payload") or {}).get("verdict"))
                for e in events if e.get("type") == "task.stage_gate"]
        if not hits:
            problems.append(f"缺 stage_gate 事件 {want}（现有 {seen}）")
        elif want.get("missing_status") is not None:
            payload = hits[0].get("payload") or {}
            missing = payload.get("missing_artifacts") or []
            if not missing or missing[0].get("status") != str(want["missing_status"]):
                problems.append(f"stage_gate {want.get('stage')} 缺口产物状态"
                                f" {missing[:1]} != 期望 {want['missing_status']}")
        elif want.get("blocking_alarms"):
            payload = hits[0].get("payload") or {}
            if not payload.get("blocking_alarms"):
                problems.append(f"stage_gate {want.get('stage')} 应有阻断告警")

    # ---- trace 回放断言
    trace_expect = dict(expect.get("trace") or {})
    if trace_expect:
        if trace_expect.get("valid", True) and not replay["valid"]:
            problems.append(f"trace 回放违规: {replay['violations']}")
        if not trace_expect.get("valid", True) and replay["valid"]:
            problems.append("trace 回放应违规但通过（用例构造无效）")
        if trace_expect.get("complete_turns") is not None and \
                replay["complete_turns"] != int(trace_expect["complete_turns"]):
            problems.append(f"完整轮数 {replay['complete_turns']}"
                            f" != 期望 {trace_expect['complete_turns']}")
        if trace_expect.get("aborted_prepare_turns") is not None and \
                replay["aborted_prepare_turns"] != int(trace_expect["aborted_prepare_turns"]):
            problems.append(f"Prepare 中断轮数 {replay['aborted_prepare_turns']}"
                            f" != 期望 {trace_expect['aborted_prepare_turns']}")
        for turn_key, phases in (trace_expect.get("turns") or {}).items():
            got = (replay["turns"].get(int(turn_key)) or {}).get("phases")
            if got != list(phases):
                problems.append(f"第 {turn_key} 轮阶段序 {got} != 期望 {list(phases)}")
        if trace_expect.get("no_model_without_prepare"):
            bad = [t for t, r in replay["turns"].items() if r["model_without_prepare"]]
            if bad:
                problems.append(f"存在 Model 先于 Prepare 的轮次: {bad}")
        if trace_expect.get("prepare_state_versions"):
            missing = [
                e.get("turn") for e in agent._trace_of(task_id).entries()
                if e.get("phase") == "PREPARE"
                and not (e.get("data") or {}).get("state_version")]
            if missing:
                problems.append(f"PREPARE 记录缺权威状态版本号（轮 {missing}）")

    # ---- 步骤错误断言
    for want in expect.get("errors") or []:
        step_id, error = str(want.get("step")), None
        for captured in harness["errors"]:
            if captured["step"] == step_id:
                error = captured
                break
        if error is None:
            problems.append(f"步骤 {step_id} 未抛出期望错误 {want.get('type')}")
            continue
        if error["type"] != str(want.get("type")):
            problems.append(f"步骤 {step_id} 错误类型 {error['type']}"
                            f" != 期望 {want.get('type')}（{error['message'][:80]}）")
        if want.get("contains") and str(want["contains"]) not in error["message"]:
            problems.append(f"步骤 {step_id} 错误消息不含 {want['contains']!r}:"
                            f" {error['message'][:120]}")

    return {
        "status": state.status.value,
        "stage": state.current_stage,
        "turns": len(replay["turns"]),
        "complete_turns": replay["complete_turns"],
        "events": len(events),
        "verdicts": [v.get("verdict") for v in agent.last_verdicts.get(task_id, [])],
        "token_used": state.budget.token_used,
        "evidence": len(state.evidence_refs),
    }


def exec_scenario(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    sandbox = _sandbox(ctx, case)
    harness = _build_harness(ctx, case, params, sandbox)
    problems: list[str] = []

    for step in params.get("steps") or []:
        op = str(step.get("op"))
        step_id = str(step.get("id") or op)
        try:
            _step_run(harness, step, op)
        except Exception as exc:  # noqa: BLE001 - 期望错误按步捕获
            if step.get("expect_error"):
                want = dict(step["expect_error"])
                if want.get("type") and type(exc).__name__ != str(want["type"]):
                    problems.append(f"步骤 {step_id} 错误类型 {type(exc).__name__}"
                                    f" != 期望 {want['type']}: {exc}")
                harness["errors"].append({"step": step_id,
                                          "type": type(exc).__name__,
                                          "message": str(exc)})
            else:
                problems.append(f"步骤 {step_id}（{op}）异常:"
                                f" {type(exc).__name__}: {exc}")
    # 期望抛错但未抛的步骤
    for step in params.get("steps") or []:
        if step.get("expect_error") and not any(
                e["step"] == str(step.get("id") or step.get("op"))
                for e in harness["errors"]):
            problems.append(f"步骤 {step.get('id') or step.get('op')} 未抛出期望错误")

    metrics = _scenario_assertions(harness, expect, problems)
    if problems:
        return _result(False, "；".join(problems[:10]), metrics)
    return _result(
        True,
        f"场景按 steps 驱动完成：{metrics['turns']} 轮（完整 {metrics['complete_turns']}），"
        f"终态 {metrics['status']}@{metrics['stage']}，事件 {metrics['events']} 条，"
        f"verdicts={metrics['verdicts'] or '—'}",
        metrics)


# ===========================================================================
# m1.replay · 伪阶段序必被拒（SPEC-M1-01 负例）
# ===========================================================================
def exec_replay(case: dict, ctx: Any) -> dict:
    from m1_core import validate_replay

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    problems: list[str] = []

    # 1) 注入的伪序（Model 先于 Prepare / 跳阶段）必须被回放校验拒绝
    rejected = 0
    for index, sequence in enumerate(params.get("bad_sequences") or []):
        entries = [{"seq": i + 1, "turn": 1, "phase": str(p)} for i, p in enumerate(sequence)]
        report = validate_replay(entries)
        if report["valid"]:
            problems.append(f"伪序[{index}] {sequence} 未被回放校验拒绝")
        else:
            rejected += 1
        if params.get("violation_contains") and \
                not any(str(params["violation_contains"]) in v
                        for v in report["violations"]):
            problems.append(f"伪序[{index}] 违规说明不含 {params['violation_contains']!r}:"
                            f" {report['violations']}")

    # 2) 真实运行（同 params.scenario 配置）零此类序
    scenario_params = dict(params.get("scenario") or {})
    real_turns = 0
    if scenario_params:
        sandbox = _sandbox(ctx, case, suffix="-real")
        harness = _build_harness(ctx, case, scenario_params, sandbox)
        try:
            harness["agent"].run_task(
                str(scenario_params.get("user_input", "") or "日巡检"),
                harness["task_ctx"])
        except Exception as exc:  # noqa: BLE001
            problems.append(f"真实场景运行失败: {type(exc).__name__}: {exc}")
        else:
            replay = harness["agent"].replay_report(harness["task_id"])
            real_turns = len(replay["turns"])
            if not replay["valid"]:
                problems.append(f"真实运行 trace 违规: {replay['violations']}")
            bad = [t for t, r in replay["turns"].items() if r["model_without_prepare"]]
            if bad:
                problems.append(f"真实运行存在 Model 先于 Prepare 的轮次: {bad}")
            if expect.get("real_complete_turns") is not None and \
                    replay["complete_turns"] != int(expect["real_complete_turns"]):
                problems.append(f"真实运行完整轮数 {replay['complete_turns']}"
                                f" != 期望 {expect['real_complete_turns']}")

    metrics = {"bad_sequences": len(params.get("bad_sequences") or []),
               "rejected": rejected, "real_turns": real_turns}
    if problems:
        return _result(False, "；".join(problems[:8]), metrics)
    return _result(True, f"{rejected} 条伪阶段序全部被回放校验拒绝；"
                         f"真实运行 {real_turns} 轮零违规",
                   metrics)


# ===========================================================================
# m1.table · 状态机双写一致性 + 全矩阵守卫（SPEC-M1-02）
# ===========================================================================
def exec_table(case: dict, ctx: Any) -> dict:
    from m1_core import (
        TASK_TRANSITIONS,
        IllegalTransitionError,
        assert_legal,
        load_frozen_table,
        rejection_payload,
        table_diff,
    )

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    problems: list[str] = []

    frozen_path = Path(ctx.root) / str(
        params.get("table") or "tests/fixtures/frozen_state_machines.yaml")
    frozen = load_frozen_table(frozen_path)
    diff = table_diff(TASK_TRANSITIONS, frozen)
    if diff:
        problems.append(f"迁移表双写不一致: {diff}")

    # 全矩阵守卫：10×10 每一对（allowed ⇔ 不抛 / disallowed ⇔ 抛 IllegalTransitionError）
    states = sorted(TASK_TRANSITIONS)
    legal_count = 0
    illegal_count = 0
    for src in states:
        for dst in states:
            should_allow = dst in TASK_TRANSITIONS.get(src, [])
            try:
                assert_legal(src, dst)
                if not should_allow:
                    problems.append(f"{src}→{dst} 应被拒绝但放行")
                legal_count += 1
            except IllegalTransitionError:
                if should_allow:
                    problems.append(f"{src}→{dst} 应放行但被拒")
                illegal_count += 1
    if sorted(states) != sorted(set(states)) or len(states) != int(
            expect.get("state_count", 10)):
        problems.append(f"状态数 {len(states)} != 期望 {expect.get('state_count', 10)}")

    # 拒绝事件 payload：rejected=true + accepted=false（兼容 M2 重建跳过）
    payload = rejection_payload("COMPLETED", "RUNNING", "x")
    if payload.get("rejected") is not True or payload.get("accepted") is not False:
        problems.append(f"拒绝事件 payload 口径错误: {payload}")

    metrics = {"states": len(states), "legal": legal_count, "illegal": illegal_count,
               "diff": len(diff)}
    if problems:
        return _result(False, "；".join(problems[:8]), metrics)
    return _result(True, f"迁移表与冻结基准 diff 空；{legal_count} 合法对全放行、"
                         f"{illegal_count} 非法对全拒绝（10 态全矩阵）", metrics)


# ===========================================================================
# m1.budget · 预算检查点四口径矩阵（SPEC-M1-05）
# ===========================================================================
def exec_budget(case: dict, ctx: Any) -> dict:
    from m1_core import check_budget

    params = case.get("params") or {}
    problems: list[str] = []
    for index, item in enumerate(params.get("checks") or []):
        outcome = check_budget(dict(item.get("budget") or {}),
                               now=str(item.get("now", "2026-09-28T08:00:00Z")))
        want = dict(item.get("expect") or {})
        if want.get("exceeded") is not None and \
                outcome.exceeded != bool(want["exceeded"]):
            problems.append(f"checks[{index}] exceeded={outcome.exceeded}"
                            f" != 期望 {want['exceeded']}（{outcome.detail}）")
        if want.get("kind") is not None and outcome.kind != str(want["kind"]):
            problems.append(f"checks[{index}] kind={outcome.kind} != 期望 {want['kind']}")
        if want.get("ok") is not None and outcome.ok != bool(want["ok"]):
            problems.append(f"checks[{index}] ok={outcome.ok} != 期望 {want['ok']}")
    metrics = {"checks": len(params.get("checks") or [])}
    if problems:
        return _result(False, "；".join(problems[:8]), metrics)
    return _result(True, f"{metrics['checks']} 项预算口径断言全部成立"
                         f"（token/action/deadline/时段窗口）", metrics)


# ===========================================================================
# m1.middleware · 链可插拔（SPEC-M1-08 / M1 DoD）
# ===========================================================================
def _outcome_snapshot(harness: dict) -> dict:
    agent = harness["agent"]
    task_id = harness["task_id"]
    state = harness["info"].get_task(task_id)
    replay = agent.replay_report(task_id)
    return {
        "status": state.status.value,
        "current_stage": state.current_stage,
        "token_used": state.budget.token_used,
        "action_used": state.budget.action_used,
        "evidence_count": len(state.evidence_refs),
        "artifacts": sorted((r.schema_id, r.status.value)
                            for r in harness["info"].store.list_artifacts(task_id)),
        "todos": sorted((t.id, t.status.value) for t in state.todos),
        "verdicts": [v.get("verdict") for v in agent.last_verdicts.get(task_id, [])],
        "trace_valid": replay["valid"],
        "complete_turns": replay["complete_turns"],
        "aborted_prepare_turns": replay["aborted_prepare_turns"],
    }


def _run_reference(ctx: Any, case: dict, scenario: dict, suffix: str) -> dict:
    sandbox = _sandbox(ctx, case, suffix=suffix)
    harness = _build_harness(ctx, case, scenario, sandbox)
    harness["agent"].run_task(
        str(scenario.get("user_input", "") or "评测任务"), harness["task_ctx"])
    return _outcome_snapshot(harness)


class _Recorder:
    """记录中间件（验证注册序执行；params 数据驱动）。"""

    def __init__(self, name: str, sink: list) -> None:
        self.name = name
        self._sink = sink

    def on_turn_start(self, turn) -> None:
        self._sink.append(self.name)


def exec_middleware(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    problems: list[str] = []

    # 1) 各场景基准跑（缺省链）与移除后跑对比：核心语义不变
    scenarios = list(params.get("scenarios") or [])
    baselines: dict[str, dict] = {}
    for scenario in scenarios:
        name = str(scenario.get("name", "s"))
        baselines[name] = _run_reference(ctx, case, scenario, f"-{name}-default")

    # 2) 全移除（chain.clear 等价构造 middlewares=[]）
    for scenario in scenarios:
        name = str(scenario.get("name", "s"))
        cleared = dict(scenario)
        cleared["agent"] = {**(scenario.get("agent") or {}),
                            "middlewares": "empty"}
        snapshot = _run_reference(ctx, case, cleared, f"-{name}-empty")
        if snapshot != baselines[name]:
            diff = {k: (baselines[name].get(k), snapshot.get(k))
                    for k in set(baselines[name]) | set(snapshot)
                    if baselines[name].get(k) != snapshot.get(k)}
            problems.append(f"场景 {name} 全移除中间件后语义漂移: {diff}")

    # 3) 单移除（params.remove_one）
    if params.get("remove_one"):
        for scenario in scenarios:
            name = str(scenario.get("name", "s"))
            snapshot = None
            sandbox = _sandbox(ctx, case, suffix=f"-{name}-removed")
            harness = _build_harness(ctx, case, scenario, sandbox)
            harness["agent"].chain.remove(str(params["remove_one"]))
            harness["agent"].run_task(
                str(scenario.get("user_input", "") or "评测任务"), harness["task_ctx"])
            snapshot = _outcome_snapshot(harness)
            if snapshot != baselines[name]:
                problems.append(f"场景 {name} 移除 {params['remove_one']} 后语义漂移")

    # 4) 注册序执行（dispatch 按注册顺序）
    order_expected = [str(x) for x in params.get("registration_order") or []]
    if order_expected:
        sandbox = _sandbox(ctx, case, suffix="-order")
        harness = _build_harness(ctx, case, dict(params.get("order_scenario") or scenarios[0]),
                                 sandbox)
        agent = harness["agent"]
        agent.chain.clear()
        recorded: list[str] = []
        for name in order_expected:
            agent.chain.use(_Recorder(name, recorded))  # type: ignore[arg-type]
        from m1_core import TurnContext

        agent.chain.dispatch("on_turn_start", TurnContext(harness["task_id"], 1))
        if recorded != order_expected:
            problems.append(f"链执行序 {recorded} != 注册序 {order_expected}")

    # 5) 移除后链长断言
    metrics = {"scenarios": len(scenarios),
               "removed_one": str(params.get("remove_one", ""))}
    if problems:
        return _result(False, "；".join(problems[:8]), metrics)
    return _result(True, f"{len(scenarios)} 场景在 缺省/全移除/"
                         f"单移除({params.get('remove_one', '—')}) 三态下核心语义一致；"
                         f"链按注册序执行", metrics)


# ===========================================================================
# m1.model · model_client 离线测试（mock 确定性 + openai_like 传输注入）
# ===========================================================================
def exec_model(case: dict, ctx: Any) -> dict:
    from m1_core import (
        ModelClient,
        ModelClientError,
        ModelRetryExhaustedError,
        ModelTimeoutError,
    )

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    problems: list[str] = []
    messages = [{"role": "user", "content": str(params.get("prompt", "继续任务"))}]

    # ---- mock：脚本回放确定性 + 成本 + 耗尽
    mock_cfg = dict(params.get("mock") or {})
    if mock_cfg:
        script = list(mock_cfg.get("script") or [])
        run1 = ModelClient("mock", script=[dict(s) for s in script])
        run2 = ModelClient("mock", script=[dict(s) for s in script])
        responses1 = [run1.complete({"messages": messages, "trace_id": "t1"})
                      for _ in script]
        responses2 = [run2.complete({"messages": messages, "trace_id": "t1"})
                      for _ in script]
        if responses1 != responses2:
            problems.append("mock 脚本回放不确定（两次运行响应不一致）")
        if any(r.get("latency_ms") != 0 for r in responses1):
            problems.append("mock latency_ms 应恒为 0（确定性纪律）")
        total_cost = sum(r["cost"]["tokens"] for r in responses1)
        if expect.get("mock_cost_total") is not None and \
                total_cost != int(expect["mock_cost_total"]):
            problems.append(f"mock 成本合计 {total_cost} != 期望"
                            f" {expect['mock_cost_total']}")
        if expect.get("mock_scripted_usage"):
            first = responses1[0]["usage"]
            want = dict(expect["mock_scripted_usage"])
            if first.get("prompt_tokens") != want.get("prompt_tokens") or \
                    first.get("completion_tokens") != want.get("completion_tokens"):
                problems.append(f"脚本化 usage 未采用: {first} != {want}")
        try:
            run1.complete({"messages": messages, "trace_id": "t1"})
            problems.append("mock 脚本耗尽未抛 ModelClientError")
        except ModelClientError:
            pass

    # ---- openai_like：传输注入（离线）——重试/超时分类/密钥透传
    remote_cfg = dict(params.get("remote") or {})
    if remote_cfg:
        def make_transport(sequence: list, captured: dict):
            calls = {"count": 0}

            def transport(url, headers, payload, timeout_s):
                calls["count"] += 1
                captured["last_headers"] = dict(headers)
                captured["last_url"] = url
                captured["last_payload"] = dict(payload)
                step = sequence[min(calls["count"] - 1, len(sequence) - 1)]
                if isinstance(step, Exception):
                    raise step
                if str(step) == "TIMEOUT":
                    raise TimeoutError("注入的请求超时")
                if str(step) == "CONN":
                    raise ConnectionError("注入的网络错误")
                status = int(step[0])
                body = dict(step[1]) if len(step) > 1 else {}
                return status, body

            captured["calls"] = calls
            return transport

        for case_cfg in remote_cfg.get("cases") or []:
            cfg = dict(case_cfg)
            captured: dict = {}
            transport = make_transport(list(cfg.get("sequence") or []), captured)
            client = ModelClient("openai_like",
                                 api_base=str(remote_cfg.get("api_base")),
                                 model=str(cfg.get("model", "test-model")),
                                 api_key=str(cfg.get("api_key", "k-test")),
                                 max_retries=int(cfg.get("max_retries", 2)),
                                 retry_backoff_s=0.0, transport=transport)
            want_status = str(cfg.get("expect_status", "ok"))
            try:
                response = client.complete({"messages": messages, "trace_id": "t2"})
                if want_status == "ok":
                    if not response.get("text"):
                        problems.append(f"[{cfg.get('name')}] 重试后成功响应缺 text")
                    if captured["last_headers"].get("Authorization") != \
                            f"Bearer {cfg.get('api_key', 'k-test')}":
                        problems.append(f"[{cfg.get('name')}] api_key 未按"
                                        " Authorization 头透传")
                    if cfg.get("expect_text") and \
                            response.get("text") != str(cfg["expect_text"]):
                        problems.append(f"[{cfg.get('name')}] 响应文本"
                                        f" {response.get('text')!r}"
                                        f" != 期望 {cfg['expect_text']!r}")
                else:
                    problems.append(f"[{cfg.get('name')}] 期望 {want_status} 但传输成功")
            except ModelRetryExhaustedError:
                if want_status != "retry_exhausted":
                    problems.append(f"[{cfg.get('name')}] 非重试耗尽场景被归为"
                                    " ModelRetryExhaustedError")
            except ModelTimeoutError:
                if want_status != "timeout":
                    problems.append(f"[{cfg.get('name')}] 错误分类应为 {want_status}"
                                    " 却归为超时")
            except ModelClientError as exc:
                problems.append(f"[{cfg.get('name')}] 错误分类异常:"
                                f" {type(exc).__name__}: {exc}")
            if cfg.get("expect_calls") is not None and \
                    captured["calls"]["count"] != int(cfg["expect_calls"]):
                problems.append(f"[{cfg.get('name')}] 传输调用次数"
                                f" {captured['calls']['count']}"
                                f" != 期望 {cfg['expect_calls']}")

    metrics = {"mock_calls": len((params.get("mock") or {}).get("script") or []),
               "remote": bool(params.get("remote"))}
    if problems:
        return _result(False, "；".join(problems[:8]), metrics)
    return _result(True, f"mock 回放确定性/成本/耗尽 {metrics['mock_calls']} 调用通过；"
                         f"openai_like 传输注入（重试/超时/密钥透传）通过", metrics)


# ===========================================================================
# m1.persona_llm · M5 persona LLM 模式离线接线（model_client 回补）
# ===========================================================================
def exec_persona_llm(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    problems: list[str] = []

    from m5_simulation.clock import parse_utc
    from m5_simulation.persona import PersonaSession, fidelity_check, persona_step

    script = []
    for step in params.get("script") or []:
        script.append({"at_abs": parse_utc(str(params.get("clock_start"))),
                       "at": str(step.get("at", "+0m")), "act": str(step.get("act")),
                       "text": step.get("text")})
    session = PersonaSession(persona=str(params.get("persona", "OPERATOR")),
                             script=script,
                             llm_provider="mock",
                             llm_options=dict(params.get("llm_options") or {}))
    utterance = persona_step(session, mode="llm")
    if utterance is None:
        problems.append("persona LLM 模式未产出 utterance（接线失败）")
    else:
        if utterance.mode != "llm":
            problems.append(f"utterance.mode={utterance.mode} != llm")
        if utterance.degraded:
            problems.append("mock provider 下不应走降级路径")
        want_text = str((params.get("llm_options") or {}).get("mock_text", "") or "")
        if want_text and utterance.text != want_text:
            problems.append(f"LLM 文本 {utterance.text!r} != mock_text {want_text!r}")
        fidelity = fidelity_check([utterance.to_dict()],
                                  expected_persona=str(params.get("persona", "OPERATOR")),
                                  min_distinct_texts=int(expect.get("min_distinct", 1)))
        if not fidelity["passed"]:
            problems.append(f"persona 保真度抽检未过: {fidelity['problems']}")
    # 脚本模式仍可用（回退路径不受影响）
    scripted = persona_step(session, mode="script")
    if scripted is None or scripted.mode != "script":
        problems.append("脚本模式回放受影响（应保持可用）")

    metrics = {"mode": utterance.mode if utterance else None,
               "degraded": bool(utterance.degraded) if utterance else None}
    if problems:
        return _result(False, "；".join(problems[:6]), metrics)
    return _result(True, "persona_step(mode=llm) 经 m1_core.model_client(mock) "
                         "离线接线成功：mode=llm、零降级、保真度抽检通过；"
                         "脚本模式不受影响", metrics)


EXECUTORS: dict[str, Callable[[dict, Any], dict]] = {
    "m1.scenario": exec_scenario,
    "m1.replay": exec_replay,
    "m1.table": exec_table,
    "m1.budget": exec_budget,
    "m1.middleware": exec_middleware,
    "m1.model": exec_model,
    "m1.persona_llm": exec_persona_llm,
}
