# -*- coding: utf-8 -*-
"""m2_information 的 EVAL 执行器插件（tests/test_m2.yaml 数据驱动用例）。

插件契约（tests/EVAL-SCHEMA.md §4）：暴露 ``EXECUTORS: dict[str, callable]``；
执行器签名 ``fn(case: dict, ctx) -> {"passed": bool, "detail": str, "metrics": dict}``。

全部执行器只读 ``case.params`` 声明的数据（任务/技能/预算/期望值均来自 YAML 用例
文件），不做任何针对特定输入的硬编码特判；每个用例在 ``runtime/m2_eval/<case>``
沙箱内使用独立 InformationLayer（运行前清空，互不污染、可离线复跑）。
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

from m2_information import (
    ArtifactValidationError,
    CompactValidationError,
    ContextBudgetExceededError,
    EvidenceRejectedError,
    InformationLayer,
    KnowledgeReadOnlyError,
    REJECTED,
)
from m2_information.artifact import ARTIFACT_TRANSITIONS
from m2_information.compactor import FIVE_ELEMENTS
from m2_information.context_builder import (
    SYSTEM_LAYER_ORDER,
    TASK_SOURCE_ORDER,
)
from m2_information.skill_disclosure import SkillDisclosureError
from m2_information.state_store import TASK_TRANSITIONS, IllegalTransitionError

__all__ = ["EXECUTORS"]

_ALLOWED_SOURCE_TYPES = set(SYSTEM_LAYER_ORDER) | set(TASK_SOURCE_ORDER)


def _result(passed: bool, detail: str, metrics: dict | None = None) -> dict:
    return {"passed": bool(passed), "detail": str(detail), "metrics": metrics or {}}


def _sandbox(ctx: Any, case: dict) -> Path:
    """用例沙箱：runtime/m2_eval/<case-id>（先清空再建，保证可复跑）。"""
    root = Path(ctx.root) / "runtime" / "m2_eval" / str(case.get("id") or "case")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


def _make_layer(ctx: Any, case: dict, params: dict, *, suffix: str = "") -> InformationLayer:
    from m4_semantic.regulation import rule_id_checker

    return InformationLayer(
        _sandbox(ctx, case).parent / f"{case.get('id')}{suffix}",
        skills=params.get("skills"),
        # SPEC-M4-05 / ADDENDUM §B 联动：regulation_refs 规则 ID 存在性核对（M4 钩子）
        rule_id_checker=rule_id_checker(repo_root=Path(ctx.root)),
    )


def _create_task_from(layer: InformationLayer, spec: dict, trace_id: str):
    return layer.create_task(
        str(spec.get("task_id") or "task-eval"),
        user_input=str(spec.get("user_input") or "评测任务"),
        trace_id=trace_id,
        plan=list(spec.get("plan") or []),
        todos=list(spec.get("todos") or []),
        budget=spec.get("budget"),
        current_stage=str(spec.get("current_stage") or "INTAKE"),
    )


def _append_turn_events(layer: InformationLayer, task_id: str, params: dict) -> int:
    """按用例模板批量落 action.completed 事件（turn 1..N，确定性）。"""
    template = dict(params.get("event") or {})
    total = int(params.get("turns") or 0)
    for turn in range(1, total + 1):
        payload = {
            "task_id": task_id,
            "turn": turn,
            "status": template.get("status", "SUCCEEDED"),
            "capability": template.get("capability", "query.measurement@v1"),
            "observation": str(template.get("observation", "读数正常")).format(turn=turn),
            "result_refs": list(template.get("result_refs") or []),
        }
        layer.event_log.append(
            {
                "type": "action.completed",
                "subject": f"act-{turn}",
                "payload": payload,
                "trace_id": str(params.get("trace_id") or f"trace-{task_id}"),
                "producer": "M3",
            },
            stream=f"task-{task_id}",
        )
    return total


def _policy_tokens(compiled) -> int:
    return sum(s.tokens for s in compiled.manifest.sources
               if s.type.value == "SYSTEM_POLICY")


# ---------------------------------------------------------------------------
# SPEC-M2-01 · 确定性编译
# ---------------------------------------------------------------------------
def exec_compile_determinism(case: dict, ctx: Any) -> dict:
    """同状态同轮编译两次 hash 一致；资产（skill）版本变更后 hash 必变。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    spec = dict(params.get("task") or {})
    _create_task_from(layer, spec, "trace-det")
    turn = int(params.get("turn") or 1)
    options = dict(params.get("compile_options") or {})

    first = layer.compile_full(spec.get("task_id", "task-eval"), turn, **options)
    second = layer.compile_full(spec.get("task_id", "task-eval"), turn, **options)
    if first.manifest.hash != second.manifest.hash:
        problems.append(f"同状态同轮两次编译 hash 不一致: {first.manifest.hash[:12]}"
                        f" != {second.manifest.hash[:12]}")

    for upgraded in params.get("skills_v2") or []:
        layer.skills.register(upgraded)
    third = layer.compile_full(spec.get("task_id", "task-eval"), turn, **options)
    if params.get("skills_v2") and third.manifest.hash == first.manifest.hash:
        problems.append("资产版本变更后 hash 未变化（hash 不防资产漂移）")

    metrics = {"hash": first.manifest.hash[:16], "sources": len(first.manifest.sources),
               "tokens": first.manifest.total_tokens}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"同状态同轮 hash 恒定（{first.manifest.hash[:12]}…），"
                         f"资产版本变更后 hash 变化", metrics)


def exec_compile_wallclock(case: dict, ctx: Any) -> dict:
    """向编译注入不同墙钟读数：hash 不受影响（时钟不进 hash）。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    spec = dict(params.get("task") or {})
    _create_task_from(layer, spec, "trace-clock")
    task_id = spec.get("task_id", "task-eval")
    turn = int(params.get("turn") or 1)
    stamps = [str(s) for s in params.get("now_list") or []]
    if len(stamps) < 2:
        return _result(False, "params.now_list 需要至少两个时间戳", {})

    hashes = []
    compiled_ats = []
    for stamp in stamps:
        compiled = layer.compile_full(task_id, turn, now=stamp,
                                      **dict(params.get("compile_options") or {}))
        hashes.append(compiled.manifest.hash)
        compiled_ats.append(compiled.manifest.compiled_at)
    if len(set(hashes)) != 1:
        problems.append(f"墙钟读数影响了 hash: {sorted(set(hashes))}")
    if len(set(compiled_ats)) < 2:
        problems.append("compiled_at 未反映注入的时钟（注入未生效，用例无效）")

    metrics = {"hashes": len(set(hashes)), "stamps": len(stamps)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"注入 {stamps} 两个时钟读数：hash 恒定 {hashes[0][:12]}…"
                         f"（时钟只落 compiled_at，不进 hash）", metrics)


# ---------------------------------------------------------------------------
# SPEC-M2-02 · 分层结构
# ---------------------------------------------------------------------------
def exec_layers(case: dict, ctx: Any) -> dict:
    """100 轮任务全 Manifest：层序恒定、无跳层覆盖、冲突前者覆盖后者。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    spec = dict(params.get("task") or {})
    task_id = str(spec.get("task_id") or "task-eval")
    _create_task_from(layer, spec, "trace-layers")
    _append_turn_events(layer, task_id, params)
    turns = int(params.get("turns") or 100)
    options = dict(params.get("compile_options") or {})
    extras = list(params.get("extra_sources") or [])

    orders: list[list[str]] = []
    conflicts_total = 0
    for turn in range(1, turns + 1):
        compiled = layer.compile_full(task_id, turn, extra_sources=extras, **options)
        system_types = [s.type.value for s in compiled.manifest.sources
                        if s.type.value in SYSTEM_LAYER_ORDER]
        task_types = [s.type.value for s in compiled.manifest.sources
                      if s.type.value in TASK_SOURCE_ORDER]
        bad_types = [s.type.value for s in compiled.manifest.sources
                     if s.type.value not in _ALLOWED_SOURCE_TYPES]
        if bad_types:
            problems.append(f"turn {turn}: 出现六层+七源之外的源类型 {sorted(set(bad_types))}")
        # 层序恒定：system 子列必须按声明层序排列，且 system 组先于 task 组
        ranks = [SYSTEM_LAYER_ORDER.index(t) for t in system_types]
        if ranks != sorted(ranks):
            problems.append(f"turn {turn}: system 层序错乱 {system_types}")
        task_ranks = [TASK_SOURCE_ORDER.index(t) for t in task_types]
        if task_ranks != sorted(task_ranks):
            problems.append(f"turn {turn}: task 源序错乱 {task_types}")
        orders.append(system_types)
        # 冲突消解：前者（更早层）覆盖后者
        for conflict in compiled.conflicts:
            conflicts_total += 1
            if not conflict.get("kept"):
                problems.append(f"turn {turn}: 冲突未保留任何取值: {conflict}")
        for key, expect in (params.get("expect_directives") or {}).items():
            if compiled.directives.get(key) != expect:
                problems.append(
                    f"turn {turn}: 指令 {key} 判定 {compiled.directives.get(key)!r}"
                    f" != 期望 {expect!r}（应 Earlier 层覆盖 Later 层）"
                )
    if orders and any(order != orders[0] for order in orders):
        problems.append("100 轮 Manifest 的 system 层序不稳定")
    if params.get("expect_conflicts") and conflicts_total < int(params["expect_conflicts"]):
        problems.append(f"冲突消解记录 {conflicts_total} < 期望 {params['expect_conflicts']}")

    metrics = {"turns": turns, "conflicts": conflicts_total,
               "layer_signature": len(orders[0]) if orders else 0}
    if problems:
        return _result(False, "；".join(problems[:6]), metrics)
    return _result(True, f"{turns} 轮 Manifest 层序恒定（system 6 层序 + task 7 源序），"
                         f"冲突 {conflicts_total} 次全部 Earlier 层胜出", metrics)


# ---------------------------------------------------------------------------
# SPEC-M2-03 · 预算裁剪
# ---------------------------------------------------------------------------
def exec_budget_trim(case: dict, ctx: Any) -> dict:
    """预算 4000 / 源总量 9000：裁剪后 ≤ 预算，policy token 不变，Manifest 有裁剪记录。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    spec = dict(params.get("task") or {})
    task_id = str(spec.get("task_id") or "task-eval")
    _create_task_from(layer, spec, "trace-trim")
    turn = int(params.get("turn") or 1)
    budget = int(params.get("budget") or 4000)
    extras = list(params.get("extra_sources") or [])

    baseline = layer.compile_full(task_id, turn, token_budget=10 ** 9,
                                  extra_sources=extras)
    policy_before = _policy_tokens(baseline)
    total_before = baseline.manifest.total_tokens
    if total_before <= budget:
        problems.append(f"场景构造无效：源总量 {total_before} 未超预算 {budget}")

    trimmed = layer.compile_full(task_id, turn, token_budget=budget, extra_sources=extras)
    policy_after = _policy_tokens(trimmed)
    if trimmed.manifest.total_tokens > budget:
        problems.append(f"裁剪后 {trimmed.manifest.total_tokens} > 预算 {budget}")
    if policy_after != policy_before:
        problems.append(f"policy 层 token 被改动: {policy_before} → {policy_after}")
    if not trimmed.trim_log:
        problems.append("裁剪未留 Manifest 记录（trim_log 为空）")
    dropped_names = {entry.get("name") for entry in trimmed.trim_log}
    dropped_origins = [s.origin for s in trimmed.manifest.sources
                       if "trimmed=dropped" in s.origin]
    if not dropped_origins:
        problems.append("Manifest source.origin 缺裁剪注记（trimmed=dropped）")
    for entry in trimmed.trim_log:
        if entry.get("action") == "dropped":
            source = next((s for s in trimmed.manifest.sources
                           if s.name == entry.get("name")), None)
            if source is None or source.tokens != 0:
                problems.append(f"被裁源 {entry.get('name')} 未以 tokens=0 留档")

    persisted = layer.compile_context(task_id, turn, token_budget=budget,
                                      extra_sources=extras)
    record = layer.workspace_of(task_id).read(f"manifest/turn-{turn}.json")
    if '"trim_log"' not in record or persisted.hash != trimmed.manifest.hash:
        problems.append("持久化编译记录缺 trim_log 或 hash 与纯编译不一致")

    metrics = {"total_before": total_before, "total_after": trimmed.manifest.total_tokens,
               "budget": budget, "policy_tokens": policy_after,
               "dropped": len(dropped_names)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"源总量 {total_before} 裁至 {trimmed.manifest.total_tokens}"
                         f"（≤{budget}），policy 层 {policy_after} tokens 未动，"
                         f"裁剪 {len(dropped_names)} 源留档", metrics)


def exec_budget_protect(case: dict, ctx: Any) -> dict:
    """构造 policy 被裁场景：拒绝裁 policy → budget.exhausted + 任务 PAUSED。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    spec = dict(params.get("task") or {})
    task_id = str(spec.get("task_id") or "task-eval")
    _create_task_from(layer, spec, "trace-protect")
    layer.commit_state(task_id, {"status": str(params.get("start_status") or "RUNNING")})
    tiny_budget = int(params.get("budget") or 3)

    raised = False
    try:
        layer.compile_full(task_id, int(params.get("turn") or 1),
                           token_budget=tiny_budget,
                           extra_sources=list(params.get("extra_sources") or []))
    except ContextBudgetExceededError as exc:
        raised = True
        if exc.policy_tokens <= exc.budget:
            problems.append(f"场景构造无效：policy {exc.policy_tokens} tokens 未超预算"
                            f" {exc.budget}")
        if params.get("error_contains") and str(params["error_contains"]) not in str(exc):
            problems.append(f"错误消息不含 {params['error_contains']!r}: {exc}")
    if not raised:
        problems.append("policy 被裁场景未触发拒绝（ContextBudgetExceededError 未抛出）")

    status = layer.get_task(task_id).status.value
    if status != str(params.get("expect_status") or "PAUSED"):
        problems.append(f"任务状态 {status} != 期望 {params.get('expect_status', 'PAUSED')}"
                        f"（应触发预算 PAUSED 而非裁 policy）")
    exhausted = layer.event_log.query(task_id, "budget.exhausted")
    if not exhausted:
        problems.append("未落 budget.exhausted 事件")
    elif exhausted[0]["payload"].get("kind") != "token":
        problems.append(f"budget.exhausted kind != token: {exhausted[0]['payload']}")

    metrics = {"status": status, "exhausted_events": len(exhausted),
               "budget": tiny_budget}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"policy 永不裁：预算 {tiny_budget} 拒绝编译并转 PAUSED，"
                         f"budget.exhausted(kind=token) 已落流", metrics)


# ---------------------------------------------------------------------------
# SPEC-M2-05 · 压缩四步
# ---------------------------------------------------------------------------
def exec_compact_ok(case: dict, ctx: Any) -> dict:
    """50 轮后压缩：五要素齐全（Commit→Compact→Rebuild→Validate 全通过）。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    spec = dict(params.get("task") or {})
    task_id = str(spec.get("task_id") or "task-eval")
    _create_task_from(layer, spec, "trace-compact")
    layer.commit_state(task_id, {"status": "RUNNING"})
    turns = _append_turn_events(layer, task_id, params)

    compact_turn = int(params.get("compact_turn") or turns)
    result = layer.compactor.compact(task_id, compact_turn, trace_id="trace-compact")
    elements = result["rebuilt"]["elements"]
    for name in FIVE_ELEMENTS:
        value = elements.get(name)
        if value is None or (isinstance(value, (list, dict, str)) and not value):
            problems.append(f"五要素缺 {name}")
    text = str(result["rebuilt"]["context_text"])
    for name in FIVE_ELEMENTS:
        if name not in text:
            problems.append(f"Rebuild 上下文文本缺要素节 {name}")
    compacted = layer.compactor.load_compacted(task_id, upto_turn=compact_turn)
    if not compacted or compacted.get("turn") != compact_turn:
        problems.append("压缩记录未落盘或轮次不符")
    ws = layer.workspace_of(task_id)
    if not ws.exists(f"state/compacted-{compact_turn}.yaml"):
        problems.append("state/compacted-<turn>.yaml 缺失")
    compiled = layer.compile_full(task_id, compact_turn + 1)
    if not any(s.type.value == "COMPACTED_HISTORY" for s in compiled.manifest.sources):
        problems.append("压缩后编译未出现 COMPACTED_HISTORY 源")

    metrics = {"turns": turns, "compact_tokens": result["tokens"],
               "elements": len(elements)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"{turns} 轮后压缩：五要素齐全，压缩记录 {result['tokens']} tokens"
                         f" 进入 COMPACTED_HISTORY", metrics)


def exec_compact_tamper(case: dict, ctx: Any) -> dict:
    """篡改 Compact 丢"验收缺口"：Validate 失败回滚，任务状态不变。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    spec = dict(params.get("task") or {})
    task_id = str(spec.get("task_id") or "task-eval")
    _create_task_from(layer, spec, "trace-tamper")
    layer.commit_state(task_id, {"status": "RUNNING"})
    turns = _append_turn_events(layer, task_id, params)

    dropped = str(params.get("drop_element") or "acceptance_gaps")
    kept = [name for name in FIVE_ELEMENTS if name != dropped]

    def tampered_summarizer(record: dict) -> dict:
        return {name: record.get(name) for name in kept}

    before = layer.get_task(task_id)
    tamper_turn = int(params.get("compact_turn") or turns + 1)
    raised = False
    try:
        layer.compactor.compact(task_id, tamper_turn, trace_id="trace-tamper",
                                summarizer=tampered_summarizer)
    except CompactValidationError as exc:
        raised = True
        if dropped not in exc.missing:
            problems.append(f"缺要素判定不含 {dropped}: {exc.missing}")
        if params.get("error_contains") and str(params["error_contains"]) not in str(exc):
            problems.append(f"错误消息不含 {params['error_contains']!r}: {exc}")
    if not raised:
        problems.append("篡改压缩未被 Validate 拒绝（失败回滚缺失）")

    after = layer.get_task(task_id)
    if after.version != before.version or after.status.value != before.status.value:
        problems.append(f"回滚后任务状态被改动: v{before.version}/{before.status.value}"
                        f" → v{after.version}/{after.status.value}")
    ws = layer.workspace_of(task_id)
    if ws.exists(f"state/compacted-{tamper_turn}.yaml"):
        problems.append("失败压缩的产物未回滚（compacted yaml 仍在）")
    if ws.exists(f"state/compact-{tamper_turn}.yaml"):
        problems.append("失败压缩的 Commit 产物未回滚（compact yaml 仍在）")

    metrics = {"dropped": dropped, "version_before": before.version,
               "version_after": after.version}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"丢『{dropped}』的压缩被 Validate 拒绝并回滚：任务"
                         f" v{before.version}/{before.status.value} 不变，"
                         f"压缩产物已清除", metrics)


# ---------------------------------------------------------------------------
# SPEC-M2-06 · Checkpoint 恢复 + DoD 事件重建
# ---------------------------------------------------------------------------
def exec_checkpoint(case: dict, ctx: Any) -> dict:
    """Checkpoint 含 TaskState 全量 + Workspace manifest 快照；restore 后可续跑。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    spec = dict(params.get("task") or {})
    task_id = str(spec.get("task_id") or "task-eval")
    _create_task_from(layer, spec, "trace-ckpt")
    for mutation in params.get("mutations") or []:
        layer.commit_state(task_id, dict(mutation))
    ws = layer.workspace_of(task_id)
    for rel, text in (params.get("workspace_files") or {}).items():
        ws.write(str(rel), str(text))

    checkpoint = layer.snapshot(task_id)
    for key in ("checkpoint_id", "task_id", "created_at", "state", "workspace_manifest"):
        if key not in checkpoint:
            problems.append(f"Checkpoint 缺字段 {key}")
    dirs = sorted((checkpoint.get("workspace_manifest") or {}).get("dirs") or [])
    if dirs != ["artifacts", "evidence", "inputs", "manifest", "scratch", "state"]:
        problems.append(f"Workspace manifest 快照六目录不符: {dirs}")
    files = (checkpoint.get("workspace_manifest") or {}).get("files") or {}
    for rel in (params.get("workspace_files") or {}):
        top = str(rel).split("/", 1)[0]
        if rel not in (files.get(top) or {}):
            problems.append(f"Workspace manifest 快照缺文件哈希: {rel}")

    # 恢复前再推进状态，恢复后回到快照点（M1 可续跑语义）
    for mutation in params.get("mutations_after_snapshot") or []:
        layer.commit_state(task_id, dict(mutation))
    pre_restore_version = layer.get_task(task_id).version
    restored = layer.restore(checkpoint["checkpoint_id"])
    snap_state = checkpoint["state"]
    if restored.status.value != snap_state["status"]:
        problems.append(f"恢复后状态 {restored.status.value} != 快照 {snap_state['status']}")
    if restored.current_stage != snap_state["current_stage"]:
        problems.append(f"恢复后阶段 {restored.current_stage} != 快照 {snap_state['current_stage']}")
    if restored.version <= pre_restore_version:
        problems.append("恢复未产生新版本提交（乐观锁版本应单调递增）")
    diff_keys = [k for k in snap_state
                 if k in ("plan", "todos", "artifacts", "evidence_refs")
                 and restored.to_dict().get(k) != snap_state.get(k)]
    if diff_keys:
        problems.append(f"恢复后字段与快照不一致: {diff_keys}")

    metrics = {"checkpoint_id": checkpoint["checkpoint_id"][:14],
               "files": checkpoint.get("workspace_manifest", {}).get("file_count", 0),
               "restored_version": restored.version}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"Checkpoint 全量可恢复（{metrics['files']} 文件快照），"
                         f"恢复后 v{restored.version} {restored.status.value} 可续跑", metrics)


def exec_eventlog_rebuild(case: dict, ctx: Any) -> dict:
    """DoD：事件流从空库重建 TaskState，与库内快照 diff 为空。"""
    params = case.get("params") or {}
    problems: list[str] = []
    sandbox = _sandbox(ctx, case)
    from m4_semantic.regulation import rule_id_checker

    layer = InformationLayer(sandbox, skills=params.get("skills"),
                             rule_id_checker=rule_id_checker(repo_root=Path(ctx.root)))
    spec = dict(params.get("task") or {})
    task_id = str(spec.get("task_id") or "task-eval")
    _create_task_from(layer, spec, "trace-rebuild")
    layer.commit_state(task_id, {"status": "RUNNING"})
    _append_turn_events(layer, task_id, params)
    layer.commit_state(task_id, {"todos": list(params.get("todos") or [])})
    art = layer.artifacts.create(
        task_id, type="REPORT", schema_id="report.daily@v1",
        content=dict(params.get("report_content") or {}), action_id="act-r",
        trace_id="trace-rebuild")
    layer.artifacts.transition(art.artifact_id, "VALIDATING", trace_id="trace-rebuild")
    layer.artifacts.transition(art.artifact_id, "READY", trace_id="trace-rebuild")
    layer.commit_state(task_id, {"status": "VERIFYING"})
    layer.compile_context(task_id, int(params.get("turn") or 3))

    live = layer.get_task(task_id).to_dict()
    # 空库重建：只用事件流（不读 state.db）
    from m2_information.event_log import EventLog

    rebuilt = EventLog(sandbox / "events").rebuild_task_state(task_id)
    rebuilt_dict = rebuilt.to_dict()
    diff = [k for k in live if live[k] != rebuilt_dict.get(k)]
    if diff:
        for key in diff:
            problems.append(f"重建差异 {key}: 库内={live[key]!r} 重建={rebuilt_dict.get(key)!r}")

    metrics = {"fields": len(live), "diff": len(diff),
               "events": len(layer.event_log.events_for_task(task_id))}
    if problems:
        return _result(False, "；".join(problems[:5]), metrics)
    return _result(True, f"空库事件重建与快照 diff 为空（{len(live)} 字段，"
                         f"{metrics['events']} 条事件折叠）", metrics)


# ---------------------------------------------------------------------------
# SPEC-M2-07 · Workspace 隔离
# ---------------------------------------------------------------------------
def exec_workspace_isolation(case: dict, ctx: Any) -> dict:
    """引用他任务 scratch 拒绝；引用他任务 PUBLISHED artifact 允许（只读）。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    actor = str(params.get("actor_task") or "task-a")
    owner = str(params.get("owner_task") or "task-b")
    layer.create_task(actor, user_input="引用方", trace_id="tr-a")
    layer.create_task(owner, user_input="被引用方", trace_id="tr-b")
    scratch_rel = str(params.get("scratch_rel") or "scratch/notes.txt")
    layer.workspace_of(owner).write(scratch_rel,
                                    str(params.get("scratch_content") or "内部草稿"))

    rejected = False
    try:
        layer.read_cross_task(actor, owner, scratch_rel)
    except Exception as exc:  # noqa: BLE001 - 预期 PermissionError 族
        rejected = True
        if params.get("error_contains") and str(params["error_contains"]) not in str(exc):
            problems.append(f"scratch 拒绝消息不含 {params['error_contains']!r}: {exc}")
    if not rejected:
        problems.append("跨任务引用 scratch 未被拒绝")

    art = layer.artifacts.create(
        owner, type="REPORT", schema_id="report.daily@v1",
        content=dict(params.get("report_content") or {}), action_id="act-b",
        trace_id="tr-b")
    try:
        layer.read_cross_task(actor, owner, art.content_ref)
        problems.append("DRAFT 产物被跨任务读取（仅 READY/PUBLISHED 允许）")
    except Exception:  # noqa: BLE001 - 预期拒绝
        pass
    for target in ("VALIDATING", "READY", "PUBLISHED"):
        layer.artifacts.transition(art.artifact_id, target, trace_id="tr-b")
    content = layer.read_cross_task(actor, owner, art.content_ref)
    expected = str(params.get("report_content_conclusion") or "正常")
    if expected not in content:
        problems.append("PUBLISHED 产物跨任务只读引用失败或内容不符")

    metrics = {"actor": actor, "owner": owner, "artifact": art.artifact_id[:12]}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, "scratch 引用被拒；DRAFT 不可读；PUBLISHED 产物只读引用成功", metrics)


def exec_workspace_crosswrite(case: dict, ctx: Any) -> dict:
    """任务 A 写任务 B 的 artifacts/：拒绝 + 审计事件。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    actor = str(params.get("actor_task") or "task-a")
    owner = str(params.get("owner_task") or "task-b")
    layer.create_task(actor, user_input="越权方", trace_id="tr-a")
    layer.create_task(owner, user_input="被写方", trace_id="tr-b")
    target_rel = str(params.get("target_rel") or "artifacts/evil.txt")

    rejected = False
    try:
        layer.write_cross_task(actor, owner, target_rel,
                               str(params.get("payload") or "hack"))
    except Exception as exc:  # noqa: BLE001
        rejected = True
        if params.get("error_contains") and str(params["error_contains"]) not in str(exc):
            problems.append(f"拒绝消息不含 {params['error_contains']!r}: {exc}")
    if not rejected:
        problems.append("跨任务写未被拒绝")
    if layer.workspace_of(owner).exists(target_rel):
        problems.append("跨任务写竟然落盘成功")

    audits = [e for e in layer.event_log.read(f"task-{actor}")
              if e.get("type") == "action.policy_decided"
              and (e.get("payload") or {}).get("decision") == "DENY"]
    if not audits:
        problems.append("跨任务写拒绝未落审计事件（action.policy_decided DENY）")

    metrics = {"actor": actor, "owner": owner, "audit_events": len(audits)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"跨任务写被拒且未落盘，审计事件 {len(audits)} 条"
                         f"（action.policy_decided DENY）", metrics)


# ---------------------------------------------------------------------------
# SPEC-M2-08 · Artifact 状态机
# ---------------------------------------------------------------------------
def _drive_artifact(layer: InformationLayer, params: dict):
    spec = dict(params.get("task") or {})
    task_id = str(spec.get("task_id") or "task-eval")
    layer.create_task(task_id, user_input=str(spec.get("user_input") or "报告"),
                      trace_id="trace-art", plan=list(spec.get("plan") or []))
    content = dict(params.get("report_content") or {})
    for omitted in params.get("omit_sections") or []:
        content.pop(str(omitted), None)
    art = layer.artifacts.create(
        task_id, type="REPORT", schema_id="report.daily@v1", content=content,
        action_id="act-1", trace_id="trace-art")
    return task_id, art


def exec_artifact_lifecycle(case: dict, ctx: Any) -> dict:
    """REPORT 校验通过：DRAFT→VALIDATING→READY→PUBLISHED 全事件可回放。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    task_id, art = _drive_artifact(layer, params)

    for target in ("VALIDATING", "READY", "PUBLISHED"):
        layer.artifacts.transition(art.artifact_id, target, trace_id="trace-art")
    final = layer.artifacts.get(art.artifact_id)
    if final.status.value != "PUBLISHED":
        problems.append(f"终态 {final.status.value} != PUBLISHED")
    if not final.validation or not final.validation.passed:
        problems.append("PUBLISHED 产物 validation.passed != true")

    events = layer.event_log.query(task_id, "artifact.state_changed",
                                   subject=art.artifact_id)
    replay = [(e["payload"]["from"], e["payload"]["to"]) for e in events]
    expected = [tuple(pair) for pair in params.get("expect_events") or []]
    if replay != expected:
        problems.append(f"事件回放 {replay} != 期望 {expected}")

    metrics = {"artifact": art.artifact_id[:12], "transitions": len(replay),
               "status": final.status.value}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"校验通过并 PUBLISHED；{len(replay)} 次 artifact.state_changed"
                         f" 事件序可完整回放", metrics)


def exec_artifact_invalid(case: dict, ctx: Any) -> dict:
    """schema 缺字段提交 PUBLISH：REJECTED + detail。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    task_id, art = _drive_artifact(layer, params)

    state = layer.artifacts.transition(art.artifact_id, "VALIDATING",
                                       trace_id="trace-art")
    if state.status.value != "REJECTED":
        problems.append(f"缺字段提交后状态 {state.status.value} != REJECTED")
    report = layer.validate_artifact(art.artifact_id)
    if report.get("passed"):
        problems.append("缺字段内容竟通过 schema 校验")
    failed = [c for c in report.get("checks") or [] if not c["passed"]]
    if not failed:
        problems.append("ValidationReport 无失败检查项")
    for section in params.get("omit_sections") or []:
        if not any(section in c["name"] or section in c["detail"] for c in failed):
            problems.append(f"失败 detail 未点名缺段 {section}")
    if params.get("error_contains"):
        joined = "；".join(c["detail"] for c in failed)
        if str(params["error_contains"]) not in joined:
            problems.append(f"detail 不含 {params['error_contains']!r}: {joined}")
    try:
        layer.artifacts.transition(art.artifact_id, "READY", trace_id="trace-art")
        problems.append("REJECTED 状态竟可迁 READY（修订应先回 DRAFT）")
    except (ArtifactValidationError, IllegalTransitionError):
        pass  # 状态机拒绝（REJECTED 仅可回 DRAFT 修订）与前置校验拒绝均为正确行为
    except Exception as exc:  # noqa: BLE001
        problems.append(f"REJECTED→READY 抛错类型异常: {type(exc).__name__}")

    events = layer.event_log.query(task_id, "artifact.state_changed",
                                   subject=art.artifact_id)
    pairs = [(e["payload"]["from"], e["payload"]["to"]) for e in events]
    if ("VALIDATING", "REJECTED") not in pairs:
        problems.append(f"事件流缺 VALIDATING→REJECTED: {pairs}")

    metrics = {"status": state.status.value, "failed_checks": len(failed)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"缺字段提交被 REJECTED，{len(failed)} 项失败检查带 detail，"
                         f"事件流含 VALIDATING→REJECTED", metrics)


def exec_state_tables(case: dict, ctx: Any) -> dict:
    """迁移表 vs 冻结基准（tests/fixtures/frozen_state_machines.yaml）diff 为空。"""
    params = case.get("params") or {}
    fixture = ctx.load_yaml(str(params.get("table") or
                                "tests/fixtures/frozen_state_machines.yaml"))
    machines = (fixture or {}).get("machines") or {}
    problems: list[str] = []
    for name, table in (("task", TASK_TRANSITIONS), ("artifact", ARTIFACT_TRANSITIONS)):
        expected = machines.get(name) or {}
        if dict(table) != {k: list(v) for k, v in expected.items()}:
            only_code = {k: set(v) for k, v in table.items()
                         if set(v) != set(expected.get(k) or [])}
            only_yaml = {k: sorted(set(expected.get(k) or []) - set(table.get(k) or []))
                         for k in expected if k not in table}
            problems.append(f"{name} 状态机与基准不一致: code侧差异={only_code} "
                            f"缺={only_yaml}")
    metrics = {"task_states": len(TASK_TRANSITIONS),
               "artifact_states": len(ARTIFACT_TRANSITIONS)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, "task/artifact 迁移表与 01§5 冻结基准 diff 为空"
                         f"（{metrics['task_states']}+{metrics['artifact_states']} 态）",
                   metrics)


# ---------------------------------------------------------------------------
# SPEC-M2-09 · 产物即证据
# ---------------------------------------------------------------------------
def exec_evidence_gate(case: dict, ctx: Any) -> dict:
    """evidence/ 接受三态证据与只读读数快照（正例）。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    spec = dict(params.get("task") or {})
    task_id = str(spec.get("task_id") or "task-eval")
    layer.create_task(task_id, user_input="取证", trace_id="trace-ev")

    for name, payload in (params.get("accept") or {}).items():
        rel = layer.save_evidence(task_id, str(name), payload, trace_id="trace-ev")
        if not layer.workspace_of(task_id).exists(rel):
            problems.append(f"证据未落盘: {name}")

    metrics = {"accepted": len(params.get("accept") or {})}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"三态证据与只读读数快照均落 evidence/（{metrics['accepted']} 件）",
                   metrics)


def exec_evidence_reject(case: dict, ctx: Any) -> dict:
    """evidence/ 拒绝模型生成文本等非证据内容（负例）。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    spec = dict(params.get("task") or {})
    task_id = str(spec.get("task_id") or "task-eval")
    layer.create_task(task_id, user_input="取证", trace_id="trace-ev")

    rejected = 0
    for name, payload in (params.get("reject") or {}).items():
        try:
            layer.save_evidence(task_id, str(name), payload, trace_id="trace-ev")
            problems.append(f"非证据内容未被拒绝: {name}")
        except EvidenceRejectedError as exc:
            rejected += 1
            if params.get("error_contains") and \
                    str(params["error_contains"]) not in str(exc):
                problems.append(f"拒绝消息不含 {params['error_contains']!r}: {exc}")

    metrics = {"rejected": rejected, "total": len(params.get("reject") or {})}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"{rejected} 件模型生成文本/伪证据全部被拒（"
                         f"evidence/ 只收三态证据与读数快照）", metrics)


# ---------------------------------------------------------------------------
# SPEC-M2-10 · 写入六问 / Knowledge 只读
# ---------------------------------------------------------------------------
def exec_memory_write(case: dict, ctx: Any) -> dict:
    """写 EPISODIC（来源+时效齐备）：成功，provenance 落盘；冲突写入被拒。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    spec = dict(params.get("task") or {})
    task_id = str(spec.get("task_id") or "task-eval")
    layer.create_task(task_id, user_input="记忆", trace_id="trace-mem")

    write = dict(params.get("write") or {})
    memory_id = layer.write_memory(task_id, write.get("content"),
                                   str(write.get("type") or "EPISODIC"),
                                   dict(write.get("provenance") or {}))
    if memory_id == REJECTED:
        problems.append(f"合法写入被拒: {layer.memory.last_rejection}")
    else:
        entry = layer.memory.get(memory_id)
        stored = entry["provenance"]
        for key, value in (params.get("expect_provenance") or {}).items():
            if stored.get(key) != value:
                problems.append(f"provenance.{key} 落盘 {stored.get(key)!r} != {value!r}")
        if not entry["valid_until"]:
            problems.append("时效未落盘（valid_until 为空）")

    conflict = dict(params.get("conflict_write") or {})
    if conflict:
        outcome = layer.write_memory(task_id, conflict.get("content"),
                                     str(conflict.get("type") or "EPISODIC"),
                                     dict(conflict.get("provenance") or {}))
        if outcome != REJECTED:
            problems.append("与 VERIFIED 矛盾的未验证写入未被拒（冲突检查失效）")
        elif (layer.memory.last_rejection or {}).get("question") != "conflict":
            problems.append(f"冲突拒绝归因错误: {layer.memory.last_rejection}")

    metrics = {"memory_id": str(memory_id)[:14],
               "valid_until": layer.memory.get(memory_id)["valid_until"]
               if memory_id != REJECTED else ""}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, "EPISODIC 写入成功且 provenance/时效落盘；矛盾未验证写入被拒",
                   metrics)


def exec_memory_speculative(case: dict, ctx: Any) -> dict:
    """写 SPECULATIVE 推测：直接 REJECTED。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    spec = dict(params.get("task") or {})
    task_id = str(spec.get("task_id") or "task-eval")
    layer.create_task(task_id, user_input="记忆", trace_id="trace-mem")

    write = dict(params.get("write") or {})
    outcome = layer.write_memory(task_id, write.get("content"),
                                 str(write.get("type") or "EPISODIC"),
                                 dict(write.get("provenance") or {}))
    if outcome != REJECTED:
        problems.append(f"SPECULATIVE 推测未被拒（返回 {outcome!r}）")
    else:
        question = (layer.memory.last_rejection or {}).get("question")
        if params.get("expect_question") and question != params["expect_question"]:
            problems.append(f"拒绝归因 {question!r} != {params['expect_question']!r}")
        if params.get("error_contains") and \
                str(params["error_contains"]) not in \
                str((layer.memory.last_rejection or {}).get("reason") or ""):
            problems.append("拒绝原因不含期望关键词")

    metrics = {"outcome": str(outcome)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, "SPECULATIVE 推测直接 REJECTED（未验证推测不入记忆）", metrics)


def exec_knowledge_readonly(case: dict, ctx: Any) -> dict:
    """agent 直接改 Knowledge 条目：拒绝 + 审计事件。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    spec = dict(params.get("task") or {})
    task_id = str(spec.get("task_id") or "task-eval")
    layer.create_task(task_id, user_input="知识", trace_id="trace-kn")

    entry_id = layer.knowledge.register(dict(params.get("entry") or {}),
                                        review=dict(params.get("review") or {}))
    hits = layer.knowledge.retrieve(str((params.get("entry") or {}).get("title") or ""))
    if not hits:
        problems.append("Knowledge 注册后检索不可见（只读检索失效）")

    rejected = False
    try:
        layer.knowledge.mutate(entry_id, change=dict(params.get("change") or {}))
    except KnowledgeReadOnlyError as exc:
        rejected = True
        if params.get("error_contains") and str(params["error_contains"]) not in str(exc):
            problems.append(f"拒绝消息不含 {params['error_contains']!r}: {exc}")
    if not rejected:
        problems.append("agent 变更 Knowledge 未被拒绝")
    stored = layer.knowledge.get(entry_id)
    if stored["content"] != dict(params.get("entry") or {}):
        problems.append("拒绝后 Knowledge 内容被改动")

    audits = [e for e in layer.event_log.read("audit-knowledge")
              if e.get("type") == "action.policy_decided"]
    if not audits:
        problems.append("Knowledge 只读拒绝未落审计事件")

    metrics = {"entry_id": entry_id[:14], "audits": len(audits)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"Knowledge 对 agent 只读：变更被拒、内容未动、"
                         f"审计事件 {len(audits)} 条", metrics)


# ---------------------------------------------------------------------------
# SPEC-M2-11 · 记忆分类与 TTL
# ---------------------------------------------------------------------------
def exec_memory_ttl(case: dict, ctx: Any) -> dict:
    """TTL 过期的 EPISODIC：检索不返回，过期计数入报告。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    spec = dict(params.get("task") or {})
    task_id = str(spec.get("task_id") or "task-eval")
    layer.create_task(task_id, user_input="TTL", trace_id="trace-ttl")

    for name, write in (params.get("writes") or {}).items():
        outcome = layer.write_memory(task_id, write.get("content"),
                                     str(write.get("type") or "EPISODIC"),
                                     dict(write.get("provenance") or {}))
        if outcome == REJECTED:
            problems.append(f"写入 {name} 被拒: {layer.memory.last_rejection}")

    query = str(params.get("query") or "")
    results = layer.retrieve_memory(query, task_id)
    returned_ids = {r["content"].get("subject") for r in results}
    for name, write in (params.get("writes") or {}).items():
        subject = (write.get("content") or {}).get("subject")
        expired = bool((write.get("provenance") or {}).get("expired"))
        if expired and subject in returned_ids:
            problems.append(f"过期条目 {name} 仍被检索返回")
        if not expired and subject not in returned_ids:
            problems.append(f"未过期条目 {name} 未被检索返回")

    report = layer.memory.expired_report(task_id)
    expected_expired = sum(1 for w in (params.get("writes") or {}).values()
                           if (w.get("provenance") or {}).get("expired"))
    if report["expired"] != expected_expired:
        problems.append(f"过期计数 {report['expired']} != 期望 {expected_expired}")

    # 归档：WORKING 随任务归档清理
    if params.get("working_write"):
        outcome = layer.write_memory(task_id,
                                     params["working_write"].get("content"),
                                     "WORKING",
                                     dict(params["working_write"].get("provenance") or {}))
        if outcome == REJECTED:
            problems.append(f"WORKING 写入被拒: {layer.memory.last_rejection}")
        else:
            archived = layer.memory.archive_task(task_id)
            if archived != 1:
                problems.append(f"WORKING 归档数 {archived} != 1")
            still = [r for r in layer.retrieve_memory("", task_id)
                     if r["type"] == "WORKING"]
            if still:
                problems.append("归档后的 WORKING 仍可检索")

    metrics = {"expired": report["expired"], "returned": len(results),
               "report_ids": len(report["ids"])}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"过期 EPISODIC 检索不返回（报告计数 {report['expired']}），"
                         f"未过期条目正常命中 {len(results)} 条", metrics)


# ---------------------------------------------------------------------------
# SPEC-M2-12 · Skill 渐进披露
# ---------------------------------------------------------------------------
def exec_skill_disclosure(case: dict, ctx: Any) -> dict:
    """能力域匹配任务：level1 目录进入、未选 skill 的 level2 不加载、
    DEPRECATED 不出现在任何层。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    spec = dict(params.get("task") or {})
    task_id = str(spec.get("task_id") or "task-eval")
    layer.create_task(task_id, user_input=str(spec.get("user_input") or "电能质量分析"),
                      trace_id="trace-skill")
    layer.commit_state(task_id, {"status": "RUNNING"})
    options = dict(params.get("compile_options") or {})

    compiled = layer.compile_full(task_id, int(params.get("turn") or 1), **options)
    names = [s.name for s in compiled.manifest.sources]
    texts = "\n".join(s.origin for s in compiled.manifest.sources) + "\n" + \
        "\n".join(block["text"] for block in compiled.blocks)

    expect_skill = str(params.get("expect_level1_skill") or "")
    if expect_skill:
        catalog = next((s for s in compiled.manifest.sources
                        if s.name == "skill.level1_catalog"), None)
        catalog_text = "\n".join(b["text"] for b in compiled.blocks
                                 if b["name"] == "skill.level1_catalog")
        if catalog is None:
            problems.append("level1 目录未进入上下文（能力域匹配失效）")
        elif expect_skill not in catalog_text:
            problems.append(f"level1 目录不含匹配 skill {expect_skill}")
    for unexpected in params.get("expect_level1_absent") or []:
        catalog_text = "\n".join(b["text"] for b in compiled.blocks
                                 if b["name"] == "skill.level1_catalog")
        if str(unexpected) in catalog_text:
            problems.append(f"能力域不匹配的 skill {unexpected} 出现在 level1 目录")

    level2_sources = [s for s in names if s.startswith("skill.level2.")]
    if not params.get("selected_skills") and level2_sources:
        problems.append(f"未选 skill 的 level2 被加载: {level2_sources}")

    for banned in params.get("expect_never_present") or []:
        if str(banned) in texts or str(banned) in names:
            problems.append(f"DEPRECATED/未注册 skill {banned} 出现在上下文")

    if params.get("selected_skills"):
        selected = layer.compile_full(task_id, int(params.get("turn") or 1),
                                      selected_skills=params["selected_skills"], **options)
        for skill_id in params["selected_skills"]:
            source = next((s for s in selected.manifest.sources
                           if s.name == f"skill.level2.{skill_id}"), None)
            if source is None:
                problems.append(f"选中后 level2 未加载: {skill_id}")
            elif source.tokens <= 0:
                problems.append(f"level2 加载未计入 token 预算: {skill_id}")

    for banned, level in (params.get("expect_disclose_rejected") or {}).items():
        try:
            layer.disclose_skill(str(banned), int(level))
            problems.append(f"披露被拒场景未拒绝: {banned}@{level}")
        except SkillDisclosureError:
            pass

    view = layer.disclose_skill(expect_skill, 2)
    if view["level"] != 2 or view["tokens"] <= 0:
        problems.append("disclose_skill level2 视图异常")

    metrics = {"sources": len(names), "level2": len(level2_sources),
               "skills": len(params.get("skills") or [])}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"level0 常驻、level1 按能力域进入（{expect_skill}），"
                         f"未选 skill 的 level2 不加载；禁用 skill 全层不可见", metrics)


# ---------------------------------------------------------------------------
# SPEC-M2-04 · Manifest 完整
# ---------------------------------------------------------------------------
def exec_manifest_complete(case: dict, ctx: Any) -> dict:
    """Manifest 记录全部 source 五字段；总 token 与各源之和一致。"""
    params = case.get("params") or {}
    problems: list[str] = []
    layer = _make_layer(ctx, case, params)
    spec = dict(params.get("task") or {})
    task_id = str(spec.get("task_id") or "task-eval")
    _create_task_from(layer, spec, "trace-manifest")
    _append_turn_events(layer, task_id, params)
    budget = int(params.get("budget") or 100000)
    compiled = layer.compile_full(task_id, int(params.get("turn") or 1),
                                  token_budget=budget,
                                  extra_sources=list(params.get("extra_sources") or {}))
    manifest = compiled.manifest

    source_sum = 0
    for i, source in enumerate(manifest.sources):
        payload = {"name": source.name, "type": source.type.value,
                   "tokens": source.tokens, "priority": source.priority,
                   "origin": source.origin}
        for key in ("name", "type", "tokens", "priority", "origin"):
            if payload.get(key) in (None, ""):
                problems.append(f"sources[{i}] 缺字段 {key}")
        source_sum += int(source.tokens)
    if manifest.total_tokens != source_sum:
        problems.append(f"total_tokens {manifest.total_tokens} != Σsources {source_sum}")
    if manifest.budget_remaining != budget - manifest.total_tokens:
        problems.append(f"budget_remaining {manifest.budget_remaining} != "
                        f"{budget} - {manifest.total_tokens}")
    # 契约 round-trip：Manifest 可序列化重建
    from contracts import ContextManifest as CM

    rebuilt = CM.from_dict(manifest.to_dict())
    if rebuilt.hash != manifest.hash:
        problems.append("Manifest round-trip hash 不一致")

    metrics = {"sources": len(manifest.sources), "total_tokens": manifest.total_tokens,
               "budget_remaining": manifest.budget_remaining}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"Manifest 完整：{len(manifest.sources)} 源五字段齐备，"
                         f"total={manifest.total_tokens}=Σ源，余额一致", metrics)


EXECUTORS: dict[str, Callable[[dict, Any], dict]] = {
    "m2.compile_determinism": exec_compile_determinism,
    "m2.compile_wallclock": exec_compile_wallclock,
    "m2.layers": exec_layers,
    "m2.budget_trim": exec_budget_trim,
    "m2.budget_protect": exec_budget_protect,
    "m2.compact_ok": exec_compact_ok,
    "m2.compact_tamper": exec_compact_tamper,
    "m2.checkpoint": exec_checkpoint,
    "m2.eventlog_rebuild": exec_eventlog_rebuild,
    "m2.workspace_isolation": exec_workspace_isolation,
    "m2.workspace_crosswrite": exec_workspace_crosswrite,
    "m2.artifact_lifecycle": exec_artifact_lifecycle,
    "m2.artifact_invalid": exec_artifact_invalid,
    "m2.state_tables": exec_state_tables,
    "m2.evidence_gate": exec_evidence_gate,
    "m2.evidence_reject": exec_evidence_reject,
    "m2.memory_write": exec_memory_write,
    "m2.memory_speculative": exec_memory_speculative,
    "m2.knowledge_readonly": exec_knowledge_readonly,
    "m2.memory_ttl": exec_memory_ttl,
    "m2.skill_disclosure": exec_skill_disclosure,
    "m2.manifest_complete": exec_manifest_complete,
}
