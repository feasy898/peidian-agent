# -*- coding: utf-8 -*-
"""m4_semantic 的 EVAL 执行器插件（tests/test_m4.yaml 数据驱动用例）。

插件契约（tests/EVAL-SCHEMA.md §4）：暴露 ``EXECUTORS: dict[str, callable]``；
执行器签名 ``fn(case: dict, ctx) -> {"passed": bool, "detail": str, "metrics": dict}``。

全部执行器只读 ``case.params`` 声明的数据（文本/ID/预算/期望值均来自 YAML 用例文件），
不做任何针对特定输入的硬编码特判；园区实例经 ADDENDUM §D 按名加载
（``dev-graph`` 等开发实例置于 tests/fixtures/，经 ``PARK_INSTANCE_PATH`` 搜索）。
"""
from __future__ import annotations

import contextlib
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

from m4_semantic.coverage import CoverageMonitor
from m4_semantic.graph import GraphQueryError, OntologyGraph
from m4_semantic.loader import (
    OntologyLoadError,
    compute_ontology_version,
    load_ontology,
)
from m4_semantic.regulation import RegulationIndex
from m4_semantic.resolver import resolve_entities
from m4_semantic.view import concept_view

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


def _loaded_for(ctx: Any, params: dict):
    """按 params.instance 名加载本体（seed=默认 ontology/；其余经 fixtures 搜索）。"""
    instance = params.get("instance", "seed")
    with _instance_path_env(ctx, instance):
        return load_ontology(instance=instance, use_cache=False)


def _norm(value: Any) -> str:
    """终端属性值归一化（YAML 解析出的 date/datetime → ISO 字符串）。"""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


# ---------------------------------------------------------------------------
# SPEC-M4-01/07 · 加载与版本
# ---------------------------------------------------------------------------
def exec_load_ok(case: dict, ctx: Any) -> dict:
    """加载合法本体：成功、版本=目录内容 hash 且稳定、动作清单导出完整。"""
    params = case.get("params") or {}
    problems: list = []

    loaded = load_ontology(use_cache=False)
    version = loaded.version

    ontology_dir = Path(ctx.root) / "ontology"
    computed = compute_ontology_version(ontology_dir)
    if version != computed:
        problems.append(f"版本与目录内容 hash 不一致: {version[:12]} != {computed[:12]}")

    again = load_ontology(use_cache=False)
    if again.version != version:
        problems.append("重复加载版本不稳定（同内容应同 hash）")

    # 内容敏感性：复制 ontology/ 到 runtime 临时目录，改动一字节 → hash 必变
    tmp_dir = Path(ctx.root) / "runtime" / f"ontology_copy_{uuid.uuid4().hex[:8]}"
    try:
        shutil.copytree(ontology_dir, tmp_dir)
        before = compute_ontology_version(tmp_dir)
        (tmp_dir / "rules.yaml").write_text(
            (tmp_dir / "rules.yaml").read_text(encoding="utf-8") + "\n# mutation\n",
            encoding="utf-8",
        )
        after = compute_ontology_version(tmp_dir)
        if before != version:
            problems.append("复制目录 hash 与源目录不一致（copy 语义破坏）")
        if after == before:
            problems.append("目录内容变更后 hash 未变化（版本不防漂移）")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 动作清单导出（M3 注册表对齐断言接口，SPEC-M4-01）
    actions_data = ctx.load_yaml(params.get("actions_file", "ontology/actions.yaml"))
    want_ids = [a.get("id") for a in (actions_data or {}).get("actions") or []]
    manifest = loaded.action_manifest()
    got_ids = [m.get("id") for m in manifest]
    if got_ids != want_ids:
        problems.append(f"action_manifest 与 actions.yaml 不一致: {got_ids} != {want_ids}")
    for item in manifest:
        for field in ("risk_level", "default_policy", "reversible", "policy_locked"):
            if item.get(field) is None:
                problems.append(f"action_manifest[{item.get('id')}] 缺 {field}")

    if loaded.instance is None or not loaded.instance.park_id:
        problems.append("默认实例未加载（park.id 缺失）")

    metrics = {
        "version": version[:16],
        "actions": len(manifest),
        "instance_park": loaded.instance.park_id if loaded.instance else "",
    }
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"加载成功：版本 hash 稳定且内容敏感，动作清单 {len(manifest)} 条可导出", metrics)


def exec_load_reject(case: dict, ctx: Any) -> dict:
    """负向加载拒绝：实例引用悬空 / 注册表不对齐 / 版本不匹配（启动失败优于带病运行）。"""
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    attempt = params.get("attempt")
    problems: list = []

    error: Exception | None = None
    try:
        if attempt == "instance_missing_ref":
            data = ctx.load_yaml(params.get("file", "tests/fixtures/bad_instance_missing_ref.yaml"))
            load_ontology(instance="bad-instance", instance_data=data, use_cache=False)
        elif attempt == "registry_misaligned":
            registry = [str(x) for x in params.get("registry") or []]
            load_ontology(registry=registry, use_cache=False)
        elif attempt == "version_mismatch":
            load_ontology(version=str(params.get("version")), use_cache=False)
        elif attempt == "unknown_instance_file":
            with _instance_path_env(ctx, params.get("instance", "no-such-instance")):
                load_ontology(instance=str(params.get("instance", "no-such-instance")),
                              use_cache=False)
        else:
            return _result(False, f"未知 attempt: {attempt!r}")
    except OntologyLoadError as exc:
        error = exc

    metrics = {"attempt": str(attempt)}
    if error is None:
        return _result(False, "期望拒绝但加载成功（带病运行）", metrics)
    contains = expect.get("error_contains")
    if contains and str(contains) not in str(error):
        problems.append(f"已拒绝但消息不含 {contains!r}: {error}")
    want_type = expect.get("error_type")
    if want_type and type(error).__name__ != str(want_type):
        problems.append(f"异常类型 {type(error).__name__} != {want_type}")
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"按预期拒绝（{type(error).__name__}）: {error}", metrics)


# ---------------------------------------------------------------------------
# SPEC-M4-02 · 实体解析
# ---------------------------------------------------------------------------
def exec_resolve(case: dict, ctx: Any) -> dict:
    """实体解析：唯一消歧 / 歧义候选列表（数据驱动文本与期望）。"""
    params = case.get("params") or {}
    loaded = _loaded_for(ctx, params)
    problems: list = []
    details: list = []

    for query in params.get("queries") or []:
        text = str(query.get("text", ""))
        want = query.get("expect") or {}
        results = resolve_entities(text, loaded=loaded)
        ids = [r["entity_id"] for r in results]

        if want.get("unique"):
            # 唯一消歧 = 无歧义候选（结果可含联动传感器，如 SG-A01+PD-A01）
            ambiguous = [r["entity_id"] for r in results if r["ambiguous"]]
            if not results:
                problems.append(f"{text!r}: 无解析结果")
            elif ambiguous:
                problems.append(f"{text!r}: 期望唯一消歧，实体 {ambiguous} 仍带歧义标记")
        if want.get("entity_ids") is not None:
            if sorted(ids) != sorted(str(x) for x in want["entity_ids"]):
                problems.append(f"{text!r}: 实体集 {sorted(ids)} != 期望 {sorted(want['entity_ids'])}")
        for entity_id, attr in (want.get("attributes") or {}).items():
            hit = next((r for r in results if r["entity_id"] == entity_id), None)
            if hit is None:
                problems.append(f"{text!r}: 缺实体 {entity_id}")
            elif hit.get("attribute") != attr:
                problems.append(f"{text!r}: {entity_id}.attribute={hit.get('attribute')!r} != {attr!r}")
        if want.get("all_ambiguous"):
            bad = [r["entity_id"] for r in results if not r["ambiguous"]]
            if bad or len(results) < int(want.get("min_candidates", 2)):
                problems.append(f"{text!r}: 期望全部歧义候选（≥{want.get('min_candidates', 2)}），"
                                f"实际 {len(results)} 条，非歧义={bad}")
        if want.get("contains_entity"):
            if str(want["contains_entity"]) not in ids:
                problems.append(f"{text!r}: 候选列表不含 {want['contains_entity']}")
        if want.get("reasons_nonempty"):
            empty = [r["entity_id"] for r in results if not (r.get("reason") or "").strip()]
            if empty:
                problems.append(f"{text!r}: 候选 {empty} 缺理由")
        details.append(f"{text!r}→{ids}")

    metrics = {"queries": len(params.get("queries") or []),
               "instance": str(params.get("instance", "seed"))}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, "；".join(details), metrics)


# ---------------------------------------------------------------------------
# SPEC-M4-03 · 三跳查询
# ---------------------------------------------------------------------------
def _graph_for(loaded) -> OntologyGraph:
    return OntologyGraph(
        loaded.instance,
        relation_ids=set(loaded.relation_types),
        query_pattern_ids={p.get("id") for p in loaded.query_patterns},
    )


def exec_query(case: dict, ctx: Any) -> dict:
    """三跳查询模式执行：终端集合 / 节点链 / 终端属性拾取（数据驱动）。"""
    params = case.get("params") or {}
    loaded = _loaded_for(ctx, params)
    problems: list = []

    graph = _graph_for(loaded)
    results = graph.query({"start": str(params.get("start")), "mode": str(params.get("mode"))})

    if not results:
        return _result(False, f"查询无结果: {params.get('start')} / {params.get('mode')}",
                       {"instance": str(params.get("instance", "seed"))})

    terminals = sorted({p["nodes"][-1]["id"] for p in results})
    if params.get("expect_terminal_ids") is not None:
        want = sorted(str(x) for x in params["expect_terminal_ids"])
        if terminals != want:
            problems.append(f"终端集合 {terminals} != 期望 {want}")

    if params.get("expect_node_chain"):
        chain = [n["id"] for n in results[0]["nodes"]]
        want_chain = [str(x) for x in params["expect_node_chain"]]
        if chain != want_chain:
            problems.append(f"首路径节点链 {chain} != 期望 {want_chain}")

    if params.get("expect_hops") is not None:
        bad = {p["hops"] for p in results} - {int(params["expect_hops"])}
        if bad:
            problems.append(f"关系跳数出现 {sorted(bad)}，期望全部 == {params['expect_hops']}")

    for name, value in (params.get("expect_terminal_attributes") or {}).items():
        values = {p["terminal_attributes"].get(name) for p in results}
        if not any(_norm(v) == _norm(value) for v in values):
            problems.append(f"终端属性 {name} 取值 {sorted(_norm(v) for v in values)} 不含期望 {value!r}")

    if params.get("expect_pattern_hops") is not None:
        declared = next((p.get("hops") for p in loaded.query_patterns
                         if p.get("id") == params.get("mode")), None)
        if declared != int(params["expect_pattern_hops"]):
            problems.append(f"查询模式声明跳数 {declared} != 期望 {params['expect_pattern_hops']}")

    metrics = {"paths": len(results), "terminals": ",".join(terminals),
               "instance": str(params.get("instance", "seed"))}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"{params.get('mode')} 命中 {len(results)} 条路径，终端={terminals}", metrics)


def exec_query_reject(case: dict, ctx: Any) -> dict:
    """跳数 >3 拒绝并建议分解查询（SPEC-M4-03）。"""
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    loaded = _loaded_for(ctx, params)
    graph = _graph_for(loaded)
    pattern = params.get("pattern") or {}
    try:
        graph.query(pattern)
    except GraphQueryError as exc:
        contains = expect.get("error_contains")
        if contains and str(contains) not in str(exc):
            return _result(False, f"已拒绝但消息不含 {contains!r}: {exc}", {"start": pattern.get("start")})
        return _result(True, f"按预期拒绝（建议分解）: {exc}", {"start": str(pattern.get("start"))})
    return _result(False, "期望拒绝但查询被执行（跳数上限失效）", {"start": str(pattern.get("start"))})


# ---------------------------------------------------------------------------
# SPEC-M4-04 · OntologyView 预算化
# ---------------------------------------------------------------------------
def exec_view(case: dict, ctx: Any) -> dict:
    """概念视图：预算裁剪后 token ≤ 预算、保核心属性+规则 ID、trim 记录落 Manifest source。"""
    params = case.get("params") or {}
    loaded = _loaded_for(ctx, params)
    problems: list = []

    view = concept_view(
        [str(e) for e in params.get("entity_ids") or []],
        token_budget=int(params.get("token_budget", 1024)),
        loaded=loaded,
    )
    max_tokens = params.get("max_tokens", params.get("token_budget"))
    if view.tokens > int(max_tokens):
        problems.append(f"裁剪后 token {view.tokens} > 上限 {max_tokens}")

    for entity_id, attr in (params.get("require_core_attribute") or {}).items():
        entry = next((e for e in view.entries if e["entity_id"] == entity_id), None)
        if entry is None:
            problems.append(f"实体 {entity_id} 未保留在视图中")
        elif attr not in (entry.get("core_attributes") or {}):
            problems.append(f"{entity_id} 核心属性缺 {attr}（被裁或缺失）")

    for entity_id, rule_ids in (params.get("require_rule_ids") or {}).items():
        entry = next((e for e in view.entries if e["entity_id"] == entity_id), None)
        got = set((entry or {}).get("constraint_rule_ids") or [])
        missing = set(rule_ids) - got
        if missing:
            problems.append(f"{entity_id} 直接约束规则 ID 缺 {sorted(missing)}")

    if params.get("require_trimmed") and not view.trimmed:
        problems.append("期望有裁剪记录（trimmed）但为空")
    if params.get("require_entries") is not None and len(view.entries) != int(params["require_entries"]):
        problems.append(f"保留实体数 {len(view.entries)} != 期望 {params['require_entries']}")

    source = view.to_manifest_source()
    if params.get("require_manifest_trimmed") and not source.get("trimmed"):
        problems.append("Manifest source 缺 trimmed=true 记录")
    if source.get("type") != "ONTOLOGY_VIEW":
        problems.append(f"Manifest source.type={source.get('type')!r} != ONTOLOGY_VIEW")

    metrics = {"tokens": view.tokens, "budget": view.token_budget,
               "entries": len(view.entries), "trimmed": len(view.trimmed)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"视图 {view.tokens}/{view.token_budget} tokens，"
                         f"保留 {len(view.entries)} 实体、裁剪 {len(view.trimmed)} 项", metrics)


# ---------------------------------------------------------------------------
# SPEC-M4-05 · 规程检索
# ---------------------------------------------------------------------------
def exec_regulation(case: dict, ctx: Any) -> dict:
    """规则 ID→条款+判据结构检索；关键词检索命中期望规则。"""
    params = case.get("params") or {}
    loaded = _loaded_for(ctx, params)
    index = RegulationIndex(loaded)
    problems: list = []

    if params.get("query"):
        hits = index.search(str(params["query"]))
        if not hits:
            return _result(False, f"检索无结果: {params['query']!r}", {})
        top = hits[0]
        if params.get("expect_rule_id") and top["rule_id"] != str(params["expect_rule_id"]):
            problems.append(f"检索首选 {top['rule_id']} != 期望 {params['expect_rule_id']}")
        entry = top
    else:
        entry = index.retrieve(str(params.get("rule_id")))

    if int(params.get("expect_clauses_at_least", 1)) > len(entry.get("clauses") or []):
        problems.append(f"条款条数 {len(entry.get('clauses') or [])} 少于期望")
    criterion = entry.get("criterion") or {}
    for field in params.get("expect_criterion_fields") or []:
        if field not in criterion:
            problems.append(f"判据结构缺 {field}: {criterion}")
    if params.get("expect_scope") and entry.get("scope") != params["expect_scope"]:
        problems.append(f"scope {entry.get('scope')!r} != {params['expect_scope']!r}")
    for rid in params.get("expect_unknown_refs") or []:
        if rid not in index.unknown_rule_ids([rid]):
            problems.append(f"引用 {rid} 应判不存在")

    metrics = {"rule_id": entry.get("rule_id", ""),
               "criterion_fields": ",".join(sorted(criterion))}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"命中 {entry.get('rule_id')}（条款 {len(entry.get('clauses') or [])} 条，"
                         f"判据 {sorted(criterion)}）", metrics)


# ---------------------------------------------------------------------------
# SPEC-M4-06 · 覆盖率监测
# ---------------------------------------------------------------------------
def exec_coverage(case: dict, ctx: Any) -> dict:
    """任务级覆盖率报告：ratio/缺失清单落盘；缺失 ≥30% 触发 badcase.opened 候选事件。"""
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    loaded = _loaded_for(ctx, params)
    persist_dir = Path(ctx.root) / str(params.get("persist_dir", "runtime/coverage"))
    monitor = CoverageMonitor(loaded, persist_dir=persist_dir)

    task_id = str(params.get("task_id", "task-eval"))
    concepts = [str(c) for c in params.get("concepts") or []]
    report = monitor.record_task(task_id, concepts,
                                 trace_id=params.get("trace_id") or f"trace-{task_id}")

    problems: list = []
    if "hits" in expect and report["hits"] != int(expect["hits"]):
        problems.append(f"hits {report['hits']} != {expect['hits']}")
    if "total" in expect and report["total"] != int(expect["total"]):
        problems.append(f"total {report['total']} != {expect['total']}")
    if "ratio" in expect and abs(report["ratio"] - float(expect["ratio"])) > 1e-6:
        problems.append(f"ratio {report['ratio']} != {expect['ratio']}")
    if expect.get("missing") is not None:
        if sorted(report["missing"]) != sorted(str(x) for x in expect["missing"]):
            problems.append(f"缺失清单 {sorted(report['missing'])} != {sorted(expect['missing'])}")
    events = report.get("candidate_events") or []
    if expect.get("candidate_event"):
        if not events:
            problems.append("期望触发 badcase.opened 候选事件但未触发")
        elif str(expect["candidate_event"]) not in {e.get("type") for e in events}:
            problems.append(f"候选事件类型 {[e.get('type') for e in events]} 不含 {expect['candidate_event']}")
    elif expect.get("candidate_event") is False and events:
        problems.append("未达缺失阈值却触发了候选事件")
    persisted = persist_dir / f"task-{task_id}.json"
    if expect.get("persisted") and not persisted.is_file():
        problems.append(f"缺失清单未落盘: {persisted}")

    metrics = {"hits": report["hits"], "total": report["total"], "ratio": report["ratio"],
               "missing": len(report["missing"]), "candidate_events": len(events)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"覆盖率 {report['hits']}/{report['total']}={report['ratio']}，"
                         f"缺失 {len(report['missing'])} 项已落盘，候选事件 {len(events)} 条", metrics)


# ---------------------------------------------------------------------------
# DoD §5 · 三种查询模式端到端时延
# ---------------------------------------------------------------------------
def exec_query_latency(case: dict, ctx: Any) -> dict:
    """三种查询模式端到端（内存图构建+查询）时延门槛（DoD：< 50ms）。"""
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    max_ms = expect.get("max_ms")
    if max_ms is None:
        return _result(False, "expect.max_ms 必填", {})
    loaded = _loaded_for(ctx, params)
    iterations = int(params.get("iterations", 5))

    metrics: dict = {}
    problems: list = []
    for run in params.get("runs") or []:
        mode, start = str(run.get("mode")), str(run.get("start"))
        worst = 0.0
        for _ in range(iterations):
            t0 = time.perf_counter()  # MONOTONIC 语义计时（非电价判定）
            graph = _graph_for(loaded)
            graph.query({"start": start, "mode": mode})
            worst = max(worst, (time.perf_counter() - t0) * 1000.0)
        metrics[f"{mode}_max_ms"] = round(worst, 3)
        if worst > float(max_ms):
            problems.append(f"{mode} 端到端 {worst:.1f}ms > {max_ms}ms")

    metrics["measured_ms"] = max((v for k, v in metrics.items() if k.endswith("_max_ms")), default=0.0)
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"三种模式端到端均 ≤ {metrics['measured_ms']:.2f}ms（门槛 {max_ms}ms，"
                         f"每模式 {iterations} 次取最坏）", metrics)


EXECUTORS = {
    "m4.load_ok": exec_load_ok,
    "m4.load_reject": exec_load_reject,
    "m4.resolve": exec_resolve,
    "m4.query": exec_query,
    "m4.query_reject": exec_query_reject,
    "m4.view": exec_view,
    "m4.regulation": exec_regulation,
    "m4.coverage": exec_coverage,
    "m4.query_latency": exec_query_latency,
}
