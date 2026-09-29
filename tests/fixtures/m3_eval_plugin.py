# -*- coding: utf-8 -*-
"""tests.fixtures.m3_eval_plugin · M3 v2 套件补充执行器（tests 侧插件，EVAL-SCHEMA.md §4 协议）。

按 SPEC v2（specs-v2/M3-action-gateway.md）重生成 EVAL 时新增的两个执行器，
覆盖 m3_action.eval_plugin 三执行器不直接断言的两类条款；全部数据驱动
（扫描面/禁用词面/探针步骤/期望全部来自 case.params/expect，无案例特判），
并复用 eval_plugin 的沙箱/环境/网关装配约定（_build_env/_build_gateway）：

- ``m3.determinism``（SPEC-M3-12）：双沙箱同操作序重放 → 任务事件流逐字节一致；
  event_id 形态 ``EVT-M3-<seq:06d>`` 且流内从 1 严格递增（restart 后 journal 续序
  由连续性一并钉死）；任务流事件 trace_id == ``trace-<task_id>``（从 task 派生）。
- ``m3.time_discipline``（SPEC-M3-14）：声明式墙钟词面扫描（scan_dirs × forbidden，
  allow_files 豁免 clocking.py 唯一合法读取位）+ 探针流程——把 now_iso 的三处绑定
  （m3_action.clocking / m3_action.gateway / m3_action.events）补丁为 raiser 后，
  显式 now 的整链流程仍跑通 = EVAL 路径零墙钟读取。
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

__all__ = ["EXECUTORS"]


def _result(passed: bool, detail: str, metrics: dict | None = None) -> dict:
    return {"passed": bool(passed), "detail": str(detail), "metrics": metrics or {}}


def _fresh_sandbox(ctx, case_id: str, tag: str):
    root = Path(ctx.root) / "runtime" / "m3_eval" / f"{case_id}-{tag}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


def _run_gateway_steps(gateway, steps, problems, tag):
    """按 steps 顺序驱动网关（子集 op：request/approve/expire/restart；全部显式 now）。"""
    for step in steps or []:
        op = str(step.get("op"))
        if op == "request":
            gateway.execute_action(
                dict(step.get("request") or {}),
                mode=str(step.get("mode", "SIMULATION")),
                now=step.get("now"))
        elif op == "approve":
            gateway.submit_approval(
                str(step.get("action_id")), str(step.get("decision")),
                str(step.get("approver")), now=step.get("now"))
        elif op == "expire":
            gateway.check_approval_timeouts(step.get("now"))
        else:
            problems.append(f"{tag}: 未知 op {op!r}")


# ===========================================================================
# m3.determinism · SPEC-M3-12（trace/事件确定性口径）
# ===========================================================================
_EVENT_ID_RE = re.compile(r"^EVT-M3-(\d+)$")


def exec_determinism(case: dict, ctx) -> dict:
    from m3_action.eval_plugin import _build_env, _build_gateway

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    repo_root = Path(ctx.root)
    case_id = str(case.get("id") or "m3-determinism")
    problems: list = []

    # 双沙箱同操作序重放（步骤/now 全部来自 params，两次装配零共享状态）
    runs: dict[str, dict[str, bytes]] = {}
    for tag in ("A", "B"):
        sandbox = _fresh_sandbox(ctx, case_id, tag)
        env = _build_env(dict(params.get("env") or {}), repo_root)
        gateway = _build_gateway(params, sandbox, env, repo_root)
        local_problems: list = []
        for step in params.get("steps") or []:
            op = str(step.get("op"))
            if op == "restart":
                gateway = _build_gateway(params, sandbox, env, repo_root)  # 重启：journal 重放续接
            else:
                _run_gateway_steps(gateway, [step], local_problems, tag)
        problems.extend(local_problems)
        streams: dict[str, bytes] = {}
        events_dir = sandbox / "events"
        if events_dir.is_dir():
            for path in sorted(events_dir.glob("task-*.jsonl")):
                streams[path.name] = path.read_bytes()
        runs[tag] = streams

    # 1) 确定性重放：任务事件流逐字节一致（event_id 序号/occurred_at 全部派生自显式 now）
    if expect.get("byte_identical", True):
        if runs["A"].keys() != runs["B"].keys():
            problems.append(f"双沙箱事件流集合不一致: {sorted(runs['A'])} vs {sorted(runs['B'])}")
        else:
            for name in sorted(runs["A"]):
                if runs["A"][name] != runs["B"][name]:
                    problems.append(f"{name}: 双沙箱事件流不逐字节一致")

    # 2) event_id 形态 + 流内严格递增（restart 续序一并覆盖）+ trace_id 派生
    prefix = str(expect.get("event_id_prefix") or "EVT-M3-")
    trace_prefix = str(expect.get("trace_prefix") or "trace-")
    seq_continuous = bool(expect.get("seq_continuous", True))
    total_events = 0
    for name, raw in runs["A"].items():
        task_id = name[len("task-"):-len(".jsonl")]
        last_seq = 0
        for line in raw.decode("utf-8").splitlines():
            if not line.strip():
                continue
            total_events += 1
            record = json.loads(line)
            event_id = str(record.get("event_id") or "")
            matched = _EVENT_ID_RE.match(event_id)
            if not matched or not event_id.startswith(prefix):
                problems.append(f"{name}: event_id 形态不符 {event_id!r}")
                continue
            seq = int(matched.group(1))
            if seq_continuous and seq != last_seq + 1:
                problems.append(f"{name}: event_id 序号不连续 {last_seq}→{seq}（{event_id}）")
            last_seq = seq
            want_trace = f"{trace_prefix}{task_id}"
            got_trace = str(record.get("trace_id") or "")
            if expect.get("trace_derive", True) and got_trace != want_trace:
                problems.append(f"{name}: trace_id={got_trace!r} != 派生期望 {want_trace!r}")

    metrics = {"streams": len(runs["A"]), "events": total_events,
               "byte_identical": runs["A"] == runs["B"]}
    if problems:
        return _result(False, "；".join(problems[:10]), metrics)
    return _result(True, (f"双沙箱 {len(runs['A'])} 个任务流 {total_events} 条事件逐字节一致；"
                          f"event_id {prefix}<seq> 流内严格递增；trace_id 全部由 task 派生"), metrics)


# ===========================================================================
# m3.time_discipline · SPEC-M3-14（时间纪律与墙钟边界）
# ===========================================================================
def exec_time_discipline(case: dict, ctx) -> dict:
    from m3_action.eval_plugin import _build_env, _build_gateway

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    repo_root = Path(ctx.root)
    case_id = str(case.get("id") or "m3-time-discipline")
    problems: list = []

    # 1) 声明式词面扫描：scan_dirs × forbidden，allow_files 豁免（唯一合法读取位）
    scanned = 0
    allow = {str(p) for p in (params.get("allow_files") or [])}
    for scan_dir in params.get("scan_dirs") or []:
        base = repo_root / str(scan_dir)
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(repo_root).as_posix()
            if rel in allow or "__pycache__" in rel:
                continue
            scanned += 1
            text = path.read_text(encoding="utf-8")
            for token in params.get("forbidden") or []:
                if str(token) in text:
                    problems.append(f"{rel}: 命中墙钟词面 {token!r}")

    # 2) 探针流程：now_iso 三处绑定补丁为 raiser，显式 now 整链跑通 = 零墙钟读取
    statuses: dict = {}
    probe = params.get("probe")
    if probe:
        import m3_action.clocking as clocking_mod
        import m3_action.events as events_mod
        import m3_action.gateway as gateway_mod
        from m3_action.eval_plugin import _build_gateway

        def _wall_clock_touched(*_args, **_kwargs):
            raise AssertionError("EVAL 路径读取了墙钟（now_iso 被调用）")

        targets = [(clocking_mod, "now_iso"), (gateway_mod, "now_iso"), (events_mod, "now_iso")]
        saved = [(mod, name, getattr(mod, name)) for mod, name in targets]
        sandbox = _fresh_sandbox(ctx, case_id, "probe")
        try:
            for mod, name, _original in saved:
                setattr(mod, name, _wall_clock_touched)
            env = _build_env(dict(probe.get("env") or {}), repo_root)
            gateway = _build_gateway(probe, sandbox, env, repo_root)
            steps = probe.get("steps") or []
            for step in steps:
                step_id = str(step.get("id") or step.get("op"))
                op = str(step.get("op"))
                if op == "request":
                    result = gateway.execute_action(
                        dict(step.get("request") or {}),
                        mode=str(step.get("mode", "SIMULATION")),
                        now=step.get("now"))
                    statuses[step_id] = result.status.value
                elif op == "approve":
                    result = gateway.submit_approval(
                        str(step.get("action_id")), str(step.get("decision")),
                        str(step.get("approver")), now=step.get("now"))
                    statuses[step_id] = result.status.value
                else:
                    problems.append(f"probe: 未知 op {op!r}")
        except AssertionError as exc:
            problems.append(f"探针流程失败: {exc}")
        finally:
            for mod, name, original in saved:
                setattr(mod, name, original)
        for step_id, want in (expect.get("probe_results") or {}).items():
            if statuses.get(step_id) != str(want):
                problems.append(f"probe_results[{step_id}]={statuses.get(step_id)!r} != 期望 {want!r}")

    metrics = {"scanned_files": scanned, "probe_statuses": statuses}
    if problems:
        return _result(False, "；".join(problems[:10]), metrics)
    return _result(True, (f"墙钟词面扫描 {scanned} 文件零命中（唯一豁免=允许清单）；"
                          f"补丁 now_iso 后探针 {len(statuses)} 步全部跑通（EVAL 零墙钟）"), metrics)


EXECUTORS = {
    "m3.determinism": exec_determinism,
    "m3.time_discipline": exec_time_discipline,
}
