# -*- coding: utf-8 -*-
"""m6_flywheel 的 EVAL 执行器插件（tests/test_m6.yaml 数据驱动用例）。

插件契约（tests/EVAL-SCHEMA.md §4）：暴露 ``EXECUTORS: dict[str, callable]``；
执行器签名 ``fn(case: dict, ctx) -> {"passed": bool, "detail": str, "metrics": dict}``。

全部执行器只读 ``case.params`` 声明的数据（场景/案例/评分单/mock release 均为
用例数据），不做针对特定输入的硬编码特判；沙箱统一 ``runtime/m6_eval/<case-id>``
（先清空，独立可复跑）。真实黄金集用例（EVAL-M6-02-P2/EVAL-M6-EVAL-P）只读
``golden/dev/``（evaluator 默认拾取口径，SPEC-M6-02）。
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from m6_flywheel.badcase import BadcaseStore, BadcaseWorkflow
from m6_flywheel.evaluator import (
    GoldenEvaluator,
    MockRelease,
    ReleaseGuard,
    ReleaseMutationRefusedError,
)
from m6_flywheel.golden_set import (
    MANIFEST_NAME,
    RUBRICS_NAME,
    golden_set_version,
    list_case_files,
    load_golden_set,
    verify_golden_dir,
    write_manifest,
)
from m6_flywheel.judges import (
    DIMENSIONS,
    ExpressionError,
    RubricSheet,
    evaluate_expression,
    judge_case,
    score_rubric,
)
from m6_flywheel.skillize import MethodLedger, SkillizeError, skillize
from m6_flywheel.trajectory import (
    TrajectoryExporter,
    TrajectoryRejectedError,
    step_type_of,
)

__all__ = ["EXECUTORS"]


def _result(passed: bool, detail: str, metrics: dict | None = None) -> dict:
    return {"passed": bool(passed), "detail": str(detail), "metrics": metrics or {}}


def _sandbox(ctx: Any, case: dict) -> Path:
    root = Path(ctx.root) / "runtime" / "m6_eval" / str(case.get("id") or "case")
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_case_files(golden_dir: Path, case_dicts: list) -> None:
    """沙箱案例直写（含 holdout 标记条目——模拟验收人侧目录，不走开发通道）。"""
    golden_dir.mkdir(parents=True, exist_ok=True)
    for payload in case_dicts:
        case_id = str(payload.get("case_id") or f"case-{abs(hash(str(payload))) % 1000}")
        (golden_dir / f"case_{case_id}.yaml").write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8")


# ---------------------------------------------------------------------------
# SPEC-M6-01 · 轨迹完整性
# ---------------------------------------------------------------------------
def exec_trajectory_export(case: dict, ctx: Any) -> dict:
    """跑完场景后导出：四类事件计数与事件流逐条一致（EVAL-M6-01-P）。"""
    from m5_simulation import ScenarioEngine
    from contracts import ScenarioSpec

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    spec_data = ctx.load_yaml(str(params.get("scenario", "scenarios/dev-01-report.yaml")))
    spec = ScenarioSpec.from_dict(spec_data)
    engine = ScenarioEngine(spec, repo_root=ctx.root, persist=False)
    engine.run()
    events = list(engine.env.event_log)
    trace_id = events[0]["trace_id"]

    # 任务生命周期首尾事件（M2 流口径；payload 按 params 数据驱动）
    sandbox = _sandbox(ctx, case) / "events"
    sandbox.mkdir(parents=True, exist_ok=True)
    terminal = str(expect.get("outcome_status", "COMPLETED"))
    task_id = spec.identity.scenario_id
    lifecycle_head = {
        "event_id": "EVT-TASK-HEAD", "type": "task.created", "subject": task_id,
        "payload": {"state": {"status": "CREATED", "task_id": task_id}},
        "occurred_at": events[0]["occurred_at"], "trace_id": trace_id, "producer": "M6",
    }
    lifecycle_tail = {
        "event_id": "EVT-TASK-TAIL", "type": "task.status_changed", "subject": task_id,
        "payload": {"from": "CREATED", "to": terminal, "accepted": True, "version": 2},
        "occurred_at": events[-1]["occurred_at"], "trace_id": trace_id, "producer": "M6",
    }
    stream = [lifecycle_head] + events + [lifecycle_tail]
    stream_path = sandbox / f"task-{task_id}.jsonl"
    with stream_path.open("w", encoding="utf-8") as handle:
        for event in stream:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    trajectory = TrajectoryExporter(events_dir=sandbox).export_trajectory(trace_id)
    problems: list = []
    steps = trajectory.steps
    if len(steps) != len(stream):
        problems.append(f"steps {len(steps)} != 事件流 {len(stream)} 条（逐条对应被破坏）")
    for index, (step, event) in enumerate(zip(steps, stream)):
        if step.ref != event.get("event_id"):
            problems.append(f"steps[{index}].ref={step.ref!r} != {event.get('event_id')!r}")
            break
        want = step_type_of(event)
        got = step.type.value if hasattr(step.type, "value") else str(step.type)
        if got != want:
            problems.append(f"steps[{index}].type={got} != 映射 {want}")
            break
    step_counts: dict = {}
    for step in steps:
        key = step.type.value if hasattr(step.type, "value") else str(step.type)
        step_counts[key] = step_counts.get(key, 0) + 1
    event_counts: dict = {}
    for event in stream:
        key = step_type_of(event)
        event_counts[key] = event_counts.get(key, 0) + 1
    if step_counts != event_counts:
        problems.append(f"四类计数不一致: {step_counts} != {event_counts}")
    outcome_status = trajectory.outcome.status
    if expect.get("outcome_status") and outcome_status != str(expect["outcome_status"]):
        problems.append(f"outcome.status={outcome_status} != 期望 {expect['outcome_status']}")
    metrics = {"events": len(stream), "steps": len(steps),
               "counts": event_counts, "outcome": outcome_status}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"{len(stream)} 条事件全量导出 {len(steps)} 步，逐条对应"
                         f"（{event_counts}）；outcome={outcome_status} 与任务终态一致", metrics)


def exec_trajectory_counts(case: dict, ctx: Any) -> dict:
    """mock release 全黄金案例导出：逐条对应 + 四类步型全覆盖（EVAL-M6-01-P2）。"""
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    sandbox = _sandbox(ctx, case)
    evaluator = GoldenEvaluator(golden_dir=str(params.get("golden_dir", "golden/dev")),
                                runs_dir=sandbox / "runs",
                                now_fn=lambda: "2026-09-28T00:00:00Z")
    report = evaluator.run_golden(str(params.get("release", "mock-rel-0001")))
    case_ids = list(params.get("case_ids") or [c["case_id"] for c in report["cases"]])

    problems: list = []
    all_types: set = set()
    checked = 0
    work_root = sandbox / "runs" / "eval"
    for case_id in case_ids:
        work = sorted(work_root.glob(f"*/work/{case_id}"))
        if not work:
            problems.append(f"{case_id}: 无运行工作目录")
            continue
        events = []
        for path in (work[-1] / "events").glob("*.jsonl"):
            events = [json.loads(line) for line in
                      path.read_text(encoding="utf-8").splitlines() if line.strip()]
        traj_path = work[-1] / "trajectories" / f"{case_id}.json"
        trajectory = json.loads(traj_path.read_text(encoding="utf-8"))
        if len(trajectory["steps"]) != len(events):
            problems.append(f"{case_id}: steps {len(trajectory['steps'])}"
                            f" != events {len(events)}")
        for index, (step, event) in enumerate(zip(trajectory["steps"], events)):
            if step["ref"] != event.get("event_id") or step["type"] != step_type_of(event):
                problems.append(f"{case_id}: steps[{index}] 与事件失配")
                break
        for step in trajectory["steps"]:
            all_types.add(step["type"])
        checked += 1
    if expect.get("all_four_types") and all_types != {"MODEL_CALL", "TOOL_CALL",
                                                      "STATE_CHANGE", "APPROVAL"}:
        problems.append(f"四类步型未全覆盖: {sorted(all_types)}")
    # 事件→步型映射语义钉死（数据驱动，防映射表被悄然削掉仍自洽通过）
    for etype, want_step in (expect.get("step_map") or {}).items():
        probe = {"type": str(etype), "payload": {}}
        got = step_type_of(probe)
        if got != str(want_step):
            problems.append(f"事件 {etype} → 步型 {got} != 冻结映射 {want_step}")
    for probe in expect.get("model_call_kinds") or []:
        payload = {"kind": str(probe["kind"])} if probe.get("kind") else {}
        got = step_type_of({"type": str(probe["type"]), "payload": payload})
        if got != str(probe["step"]):
            problems.append(f"budget 事件 kind={probe.get('kind')} → {got}"
                            f" != {probe['step']}")
    metrics = {"cases": checked, "step_types": sorted(all_types),
               "pass_rate": report["pass_rate"]}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"{checked} 条黄金案例轨迹与事件流逐条对应；四类步型全覆盖"
                         f"（{sorted(all_types)}）", metrics)


def exec_trajectory_reject(case: dict, ctx: Any) -> dict:
    """缺 trace 事件注入 → 轨迹 REJECTED（EVAL-M6-01-N）。"""
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    events = list(params.get("events") or [])
    trace_id = str(params.get("trace_id", "trace-reject-001"))
    try:
        TrajectoryExporter(events_dir=_sandbox(ctx, case)).export_trajectory(
            trace_id, events=events)
    except TrajectoryRejectedError as exc:
        contains = str(expect.get("error_contains") or "")
        if contains and contains not in str(exc):
            return _result(False, f"已拒绝但消息不含 {contains!r}: {exc}",
                           {"reason": exc.reason})
        return _result(True, f"轨迹按预期 REJECTED[{exc.reason}]: {exc}",
                       {"reason": exc.reason})
    return _result(False, "期望轨迹 REJECTED 但导出成功", {})


# ---------------------------------------------------------------------------
# SPEC-M6-02 · 黄金契约 / holdout 隔离
# ---------------------------------------------------------------------------
def exec_golden_isolation(case: dict, ctx: Any) -> dict:
    """3 dev + 2 holdout：目录分离，evaluator 默认只拾取 dev（EVAL-M6-02-P）。"""
    from m6_flywheel.evaluator import DEFAULT_GOLDEN_DIR

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    sandbox = _sandbox(ctx, case)
    dev_dir = sandbox / "golden" / "dev"
    holdout_dir = sandbox / "golden" / "holdout"
    _write_case_files(dev_dir, list(params.get("dev_cases") or []))
    _write_case_files(holdout_dir, list(params.get("holdout_cases") or []))

    problems: list = []
    dev_cases = load_golden_set(dev_dir)
    holdout_cases = load_golden_set(holdout_dir, allow_holdout=True)
    dev_ids = [c.case_id for c in dev_cases]
    holdout_ids = [c.case_id for c in holdout_cases]
    if len(dev_ids) != int(expect.get("dev_count", 3)):
        problems.append(f"dev 装载 {len(dev_ids)} 条 != 期望 {expect.get('dev_count')}")
    if sorted(dev_ids) != sorted(str(c["case_id"]) for c in params.get("dev_cases") or []):
        problems.append(f"dev 装载内容失配: {dev_ids}")
    if set(dev_ids) & set(holdout_ids):
        problems.append("dev 与 holdout 案例 ID 交集非空（目录未分离）")
    if str(expect.get("default_pickup_dir", DEFAULT_GOLDEN_DIR)) != "golden/dev":
        problems.append(f"evaluator 默认拾取目录={DEFAULT_GOLDEN_DIR!r} != golden/dev")
    # dev 目录装载时 holdout 标记条目必须被拒（禁入 dev）
    if expect.get("dev_rejects_holdout_marker", True):
        marker_case = dict((params.get("holdout_cases") or [{}])[0])
        marker_case["case_id"] = "case-marker-probe"
        probe_dir = sandbox / "golden" / "dev-probe"
        _write_case_files(probe_dir, list(params.get("dev_cases") or [])[:1])
        (probe_dir / "case_case-marker-probe.yaml").write_text(
            yaml.safe_dump(marker_case, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        try:
            load_golden_set(probe_dir)
            problems.append("holdout 标记条目混入 dev 目录未被装载拒绝")
        except Exception:  # noqa: BLE001 - 拒绝即通过
            pass
    metrics = {"dev": len(dev_ids), "holdout": len(holdout_ids),
               "default_pickup": DEFAULT_GOLDEN_DIR,
               "version_dev": golden_set_version(dev_dir)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"dev {len(dev_ids)} 条 / holdout {len(holdout_ids)} 条物理分离；"
                         f"evaluator 默认只拾取 {DEFAULT_GOLDEN_DIR}；holdout 标记禁入 dev", metrics)


def exec_golden_ci(case: dict, ctx: Any) -> dict:
    """holdout case 复制进 dev 目录 → CI 断言失败（来源标记+hash 校验，EVAL-M6-02-N）。"""
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    sandbox = _sandbox(ctx, case)
    dev_dir = sandbox / "golden" / "dev"
    _write_case_files(dev_dir, list(params.get("dev_cases") or []))
    write_manifest(dev_dir, set_role="dev", now_fn=lambda: "2026-09-28T00:00:00Z")
    baseline = verify_golden_dir(dev_dir)
    holdout_case = dict(params.get("holdout_case") or {})

    # 场景 A：直接复制进 dev（未登记）→ hash 校验失败
    (dev_dir / "case_holdout_copy.yaml").write_text(
        yaml.safe_dump(holdout_case, allow_unicode=True, sort_keys=False), encoding="utf-8")
    problems_a = verify_golden_dir(dev_dir)

    # 场景 B：粗心维护者重建 manifest 把它登记进来 → 来源标记断言失败
    write_manifest(dev_dir, set_role="dev", now_fn=lambda: "2026-09-28T00:00:00Z")
    problems_b = verify_golden_dir(dev_dir)

    all_problems = problems_a + problems_b
    joined = "；".join(all_problems)
    if baseline:
        return _result(False, f"沙箱基线本应干净: {baseline[:3]}", {})
    for token in expect.get("error_contains") or ["未登记", "holdout"]:
        if token not in joined:
            return _result(False, f"CI 断言未覆盖期望口径 {token!r}（实际问题: {joined[:300]}）",
                           {"problems_a": len(problems_a), "problems_b": len(problems_b)})
    metrics = {"problems_a": problems_a, "problems_b": problems_b}
    return _result(True, f"复制 holdout 案例进 dev 被 CI 断言拦截："
                         f"未登记 {len(problems_a)} 项 / 来源标记 {len(problems_b)} 项", metrics)


def exec_golden_seeds(case: dict, ctx: Any) -> dict:
    """真实 golden/dev 12 条种子：契约/manifest/评分单齐备（DoD，表外补强）。"""
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    golden_dir = Path(ctx.root) / str(params.get("golden_dir", "golden/dev"))
    problems: list = []
    cases = load_golden_set(golden_dir)
    want_count = int(expect.get("cases", 12))
    if len(cases) != want_count:
        problems.append(f"种子 {len(cases)} 条 != 期望 {want_count}")
    want_source = str(expect.get("source", "HANDWRITTEN"))
    for item in cases:
        source = item.source.value if hasattr(item.source, "value") else str(item.source)
        if source != want_source:
            problems.append(f"{item.case_id}: source={source} != {want_source}")
        if item.excluded_from:
            problems.append(f"{item.case_id}: excluded_from 非空（dev 集禁 holdout 标记）")
        judges = {(e.judge.value if hasattr(e.judge, "value") else str(e.judge))
                  for e in item.expected_behavior}
        if "DETERMINISTIC" not in judges:
            problems.append(f"{item.case_id}: 缺 DETERMINISTIC 判据")
        if "RUBRIC" not in judges:
            problems.append(f"{item.case_id}: 缺 RUBRIC 五维评分判据")
    manifest_problems = verify_golden_dir(golden_dir)
    problems.extend(f"manifest: {p}" for p in manifest_problems)
    rubrics_path = golden_dir / RUBRICS_NAME
    if not rubrics_path.is_file():
        problems.append(f"缺 {RUBRICS_NAME}（五维评分单）")
    else:
        rubric_data = yaml.safe_load(rubrics_path.read_text(encoding="utf-8")) or {}
        for item in cases:
            sheet = rubric_data.get(item.case_id)
            if not isinstance(sheet, dict):
                problems.append(f"{item.case_id}: rubrics.yaml 缺评分单")
                continue
            try:
                parsed = RubricSheet.from_dict(sheet, origin=f"{item.case_id}")
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{item.case_id}: 评分单非法: {exc}")
                continue
            weight_sum = sum(dim.weight for dim in parsed.dimensions.values())
            if abs(weight_sum - 1.0) > 1e-9:
                problems.append(f"{item.case_id}: 权重和 {weight_sum} != 1")
            if set(parsed.dimensions) != set(DIMENSIONS):
                problems.append(f"{item.case_id}: 维度集不齐")
    metrics = {"cases": len(cases), "manifest": MANIFEST_NAME,
               "rubric_sheets": len(cases)}
    if problems:
        return _result(False, "；".join(problems[:6]), metrics)
    return _result(True, f"{len(cases)} 条种子契约/manifest/评分单齐备"
                         f"（source={want_source}；五维权重和=1；hash 校验零问题）", metrics)


# ---------------------------------------------------------------------------
# SPEC-M6-03 · 判据可执行
# ---------------------------------------------------------------------------
def exec_judge_expression(case: dict, ctx: Any) -> dict:
    """deterministic 表达式引擎求值（EVAL-M6-03-P）。"""
    params = case.get("params") or {}
    checks = list(params.get("checks") or [])
    problems: list = []
    for index, check in enumerate(checks):
        expression = str(check.get("expression") or "")
        facts = dict(check.get("facts") or {})
        try:
            value = evaluate_expression(expression, facts)
        except ExpressionError as exc:
            contains = str(check.get("error_contains") or "")
            if contains:
                if contains not in str(exc):
                    problems.append(f"[{index}] 报错不含 {contains!r}: {exc}")
                continue
            problems.append(f"[{index}] 表达式错误: {exc}")
            continue
        want = check.get("result")
        if value is not want:
            problems.append(f"[{index}] {expression!r} = {value!r} != 期望 {want!r}")
    metrics = {"checks": len(checks)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"{len(checks)} 条判据表达式求值全部符合期望"
                         f"（含布尔组合/比较/not in/未知标识符拒绝）", metrics)


def exec_rubric(case: dict, ctx: Any) -> dict:
    """rubric 五维评分单：权重和=1，输出总分+分维明细（EVAL-M6-03-P2）。"""
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    problems: list = []
    # 权重和 ≠ 1 的评分单必须被拒
    bad_sheet = dict(params.get("invalid_sheet") or {})
    if bad_sheet:
        try:
            RubricSheet.from_dict(bad_sheet, origin="invalid_sheet")
            problems.append("权重和≠1 的评分单未被拒绝")
        except Exception as exc:  # noqa: BLE001
            contains = str(expect.get("invalid_error_contains") or "")
            if contains and contains not in str(exc):
                problems.append(f"拒绝消息不含 {contains!r}: {exc}")
    sheet = RubricSheet.from_dict(dict(params.get("sheet") or {}), origin="sheet")
    facts = dict(params.get("facts") or {})
    outcome = score_rubric(sheet, facts)
    by_dimension = {key: item["score"] for key, item in outcome["by_dimension"].items()}
    want_scores = dict(expect.get("by_dimension") or {})
    if want_scores and by_dimension != want_scores:
        problems.append(f"分维明细 {by_dimension} != 期望 {want_scores}")
    weight_sum = sum(dim.weight for dim in sheet.dimensions.values())
    if abs(weight_sum - 1.0) > 1e-9:
        problems.append(f"权重和 {weight_sum} != 1")
    if "total" in expect and abs(outcome["total"] - float(expect["total"])) > 1e-6:
        problems.append(f"总分 {outcome['total']} != 期望 {expect['total']}")
    if "passed" in expect and outcome["passed"] != bool(expect["passed"]):
        problems.append(f"passed={outcome['passed']} != 期望 {expect['passed']}")
    metrics = {"total": outcome["total"], "by_dimension": by_dimension,
               "pass_line": sheet.pass_line, "weight_sum": round(weight_sum, 6)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"五维评分单权重和=1；总分 {outcome['total']}（×20={round(outcome['total'] * 20, 2)}），"
                         f"分维明细 {by_dimension}，通过线 {sheet.pass_line} →"
                         f" {'通过' if outcome['passed'] else '不通过'}", metrics)


# ---------------------------------------------------------------------------
# SPEC-M6-04 · 实验隔离（A/B 同黄金集）
# ---------------------------------------------------------------------------
def _prepare_ab_sandbox(ctx: Any, case: dict, params: dict) -> dict:
    sandbox = _sandbox(ctx, case)
    golden_dir = sandbox / "golden" / "dev"
    _write_case_files(golden_dir, list(params.get("golden_cases") or []))
    rubrics = dict(params.get("rubrics") or {})
    if rubrics:
        (golden_dir / RUBRICS_NAME).write_text(
            yaml.safe_dump(rubrics, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
    releases_dir = sandbox / "releases"
    releases = {}
    for key in ("current_release", "candidate_release"):
        manifest = dict(params.get(key) or {})
        release_id = str(manifest.get("release_id") or key)
        path = releases_dir / release_id
        path.mkdir(parents=True, exist_ok=True)
        (path / "release.yaml").write_text(
            yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
        releases[key] = release_id
    return {"sandbox": sandbox, "golden_dir": golden_dir,
            "releases_dir": releases_dir, "releases": releases}


def _case_rubric_total(report: dict, case_id: str) -> float | None:
    for item in report.get("cases") or []:
        if str(item.get("case_id")) == case_id:
            totals = [r.get("total") for r in item.get("rubric") or []]
            return float(totals[0]) if totals else None
    return None


def exec_badcase_ab(case: dict, ctx: Any) -> dict:
    """修复实验 A/B：candidate ≥ current 才 ADOPTED（EVAL-M6-04-P/-N）。"""
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    box = _prepare_ab_sandbox(ctx, case, params)
    evaluator = GoldenEvaluator(golden_dir=box["golden_dir"],
                                runs_dir=box["sandbox"] / "runs",
                                releases_dir=box["releases_dir"],
                                now_fn=lambda: "2026-09-28T00:00:00Z")
    current_report = evaluator.run_golden(box["releases"]["current_release"])
    candidate_report = evaluator.run_golden(box["releases"]["candidate_release"])

    problems: list = []
    current_total = float(current_report["totals"]["score_100"])
    candidate_total = float(candidate_report["totals"]["score_100"])
    for key, got, want in (("current_total", current_total, expect.get("current_total")),
                           ("candidate_total", candidate_total, expect.get("candidate_total"))):
        if want is not None and abs(got - float(want)) > 0.01:
            problems.append(f"{key}={got} != 期望 {want}")
    if str(current_report["golden_set_version"]) != str(candidate_report["golden_set_version"]):
        problems.append("A/B 两版 golden_set_version 不一致（必须同黄金集）")

    badcase_cfg = dict(params.get("badcase") or {})
    badcase_case = str(badcase_cfg.get("case_id") or "")
    current_case_total = _case_rubric_total(current_report, badcase_case)
    candidate_case_total = _case_rubric_total(candidate_report, badcase_case)
    if current_case_total is None or candidate_case_total is None:
        problems.append(f"A/B 报告缺 badcase 关联案例 {badcase_case!r}")

    production_path = box["releases_dir"] / box["releases"]["current_release"] / "release.yaml"
    production_before = hashlib.sha256(production_path.read_bytes()).hexdigest()

    audit_events: list = []

    def sink(event: dict) -> None:
        audit_events.append(event)

    workflow = BadcaseWorkflow(BadcaseStore(box["sandbox"] / "badcases.jsonl"),
                               archive_dir=box["sandbox"], sink=sink,
                               now_fn=lambda: "2026-09-28T00:00:00Z")
    trace_id = next((c.get("trace_id") for c in current_report["cases"]
                     if c.get("case_id") == badcase_case), f"trace-{badcase_case}")
    badcase_id = workflow.open({
        "case_id": badcase_case, "trace_id": trace_id,
        "summary": str(badcase_cfg.get("summary") or "rubric 总分短板"),
        "release_id": box["releases"]["current_release"],
        "detail": f"case rubric total: current={current_case_total}"
                  f" candidate(期望)={candidate_case_total}",
    })
    reproduce_below = float(badcase_cfg.get("reproduce_below", 4.5))
    reproduced = (current_case_total is not None
                  and current_case_total < reproduce_below)
    workflow.reproduce(badcase_id, reproduced=reproduced,
                       note=f"current={current_case_total} < 复现线 {reproduce_below}")
    workflow.submit_fix_candidate(badcase_id, box["releases"]["candidate_release"])
    record = workflow.run_experiment(badcase_id, current_report=current_report,
                                     candidate_report=candidate_report)

    want_decision = str(expect.get("decision") or "")
    if record.status != want_decision:
        problems.append(f"决策 {record.status} != 期望 {want_decision}")
    archive = record.experiment.get("archive")
    if not archive or not Path(archive).is_file():
        problems.append(f"实验记录未归档: {archive!r}")
    production_after = hashlib.sha256(production_path.read_bytes()).hexdigest()
    if expect.get("production_unchanged", True) and production_before != production_after:
        problems.append("生产 release 文件被改动（实验不得触碰生产状态）")
    if want_decision == "REJECTED" and production_before != production_after:
        problems.append("REJECTED 后生产 release 发生变化")

    metrics = {"current_total": current_total, "candidate_total": candidate_total,
               "decision": record.status, "diff_cases": record.experiment.get("diff_cases"),
               "archive": bool(archive and Path(archive).is_file()),
               "current_case_total": current_case_total,
               "candidate_case_total": candidate_case_total}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"A/B 同黄金集（{current_report['golden_set_version']}）："
                         f"current={current_total} / candidate={candidate_total} →"
                         f" {record.status}；实验已归档；生产 release 未变", metrics)


# ---------------------------------------------------------------------------
# SPEC-M6-05 · 受控自进化（Skill 化）
# ---------------------------------------------------------------------------
def exec_skillize(case: dict, ctx: Any) -> dict:
    """方法出现 ≥3 个不同任务实例且判据通过 → SkillDescriptor 候选（EVAL-M6-05-P/-N）。"""
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    sandbox = _sandbox(ctx, case)
    ledger = MethodLedger(sandbox / "methods.jsonl")
    method_key = str(params.get("method_key") or "method.overload-response")
    for occurrence in params.get("occurrences") or []:
        payload = dict(occurrence)
        payload.setdefault("method_key", method_key)
        ledger.record(payload)

    promoted: list = []

    def sink(event: dict) -> None:
        promoted.append(event)

    try:
        descriptor = skillize(method_key,
                              [item.to_dict() for item in ledger.occurrences(method_key)],
                              dict(params.get("skill_draft") or {}),
                              badcase_id=str(params.get("badcase_id") or "bc-1"),
                              evidence_ref=str(params.get("evidence_ref") or ""),
                              sink=sink)
    except SkillizeError as exc:
        contains = str(expect.get("error_contains") or "")
        if expect.get("produced"):
            return _result(False, f"期望产出候选但被拒: {exc}", {})
        if contains and contains not in str(exc):
            return _result(False, f"拒绝消息不含 {contains!r}: {exc}", {})
        if promoted:
            return _result(False, "拒绝路径仍发出 skill.promoted 事件", {})
        return _result(True, f"按预期不触发 Skill 化: {exc}", {"occurrences": len(params.get("occurrences") or [])})
    if not expect.get("produced"):
        return _result(False, "期望不触发但产出了 SkillDescriptor 候选", {})
    problems: list = []
    want_status = str(expect.get("status", "REVIEW"))
    status = descriptor.status.value if hasattr(descriptor.status, "value") else str(descriptor.status)
    if status != want_status:
        problems.append(f"status={status} != 期望 {want_status}（候选须走 M7 评审）")
    if EVIDENCE_TOKEN not in descriptor.evidence_policy:
        problems.append(f"evidence_policy 缺 {EVIDENCE_TOKEN!r}: {descriptor.evidence_policy!r}")
    if len(promoted) != 1:
        problems.append(f"skill.promoted 事件 {len(promoted)} 条 != 1")
    metrics = {"status": status, "promoted_events": len(promoted),
               "evidence_policy": descriptor.evidence_policy[:80]}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"方法在 ≥3 个不同任务实例判据通过 → SkillDescriptor 候选"
                         f"（status={status}，走 M7 评审；evidence_policy 含黄金提升证明；"
                         f"skill.promoted 审计 1 条）", metrics)


EVIDENCE_TOKEN = "受控自进化"


# ---------------------------------------------------------------------------
# SPEC-M6-06 · 评估与调优单向
# ---------------------------------------------------------------------------
def exec_release_flip(case: dict, ctx: Any) -> dict:
    """调优侧直改 release 状态 → 拒绝 + 审计事件（EVAL-M6-06-P）。"""
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    sandbox = _sandbox(ctx, case)
    releases_dir = sandbox / "releases"
    release_id = str(params.get("release_id") or "rel-0009")
    manifest = dict(params.get("release_manifest") or {})
    path = releases_dir / release_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "release.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")

    audit: list = []

    def sink(event: dict) -> None:
        audit.append(event)

    guard = ReleaseGuard(releases_dir, sink=sink,
                         now_fn=lambda: "2026-09-28T00:00:00Z")
    # 只读面：黄金成绩可读（调优侧合法权益）
    scores = guard.golden_scores(release_id)
    want_scores = dict(expect.get("golden_scores") or {})
    problems: list = []
    if want_scores and scores != want_scores:
        problems.append(f"只读成绩 {scores} != 期望 {want_scores}")
    try:
        guard.flip_status(release_id, str(params.get("to_status") or "PUBLISHED"))
        problems.append("直改状态未被拒绝（SPEC-M6-06 红线失守）")
    except ReleaseMutationRefusedError as exc:
        if str(expect.get("error_contains") or "") not in str(exc):
            problems.append(f"拒绝消息不含期望口径: {exc}")
    if not audit:
        problems.append("拒绝后未落审计事件")
    else:
        event = audit[0]
        if event.get("type") != "release.published":
            problems.append(f"审计事件主题 {event.get('type')!r} != release.published")
        if not (event.get("payload") or {}).get("rejected"):
            problems.append("审计事件缺 rejected: true 标记")
        # 审计事件补写落盘（EventRecord 契约校验）
        from contracts import EventRecord

        try:
            EventRecord.from_dict(event)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"审计事件不合约: {exc}")
    metrics = {"audit_events": len(audit), "scores_readable": bool(scores),
               "release_id": release_id}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"调优侧只读成绩可用；直改 release 状态被拒并落"
                         f" release.published{{rejected:true}} 审计事件", metrics)


# ---------------------------------------------------------------------------
# DoD · evaluator 全流程（离线 mock release）+ 归档 + 确定性
# ---------------------------------------------------------------------------
def exec_evaluator_flow(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    sandbox = _sandbox(ctx, case)
    evaluator = GoldenEvaluator(golden_dir=str(params.get("golden_dir", "golden/dev")),
                                runs_dir=sandbox / "runs",
                                now_fn=lambda: "2026-09-28T00:00:00Z")
    report = evaluator.run_golden(str(params.get("release", "mock-rel-0001")))
    # 确定性重跑（同 seed 同输入 → 同结果）
    report2 = GoldenEvaluator(golden_dir=str(params.get("golden_dir", "golden/dev")),
                              runs_dir=sandbox / "runs2",
                              now_fn=lambda: "2026-09-28T00:00:00Z"
                              ).run_golden(str(params.get("release", "mock-rel-0001")))

    problems: list = []
    if abs(report["pass_rate"] - float(expect.get("pass_rate", 1.0))) > 1e-9:
        problems.append(f"pass_rate={report['pass_rate']} != 期望 {expect.get('pass_rate')}")
    if expect.get("failures") is not None and report["failures"] != expect["failures"]:
        problems.append(f"failures={report['failures']} != 期望 {expect['failures']}")
    if len(report["cases"]) != int(expect.get("cases", 12)):
        problems.append(f"案例数 {len(report['cases'])} != 期望 {expect.get('cases')}")
    verdicts_a = [(c["case_id"], c["passed"]) for c in report["cases"]]
    verdicts_b = [(c["case_id"], c["passed"]) for c in report2["cases"]]
    if verdicts_a != verdicts_b or report["totals"] != report2["totals"]:
        problems.append("两次评估结果不一致（确定性失守）")
    archive = sorted((sandbox / "runs" / "eval").glob("*/report.json"))
    if expect.get("archive_exists", True) and not archive:
        problems.append("评估结果未归档 runs/（SPEC-M6-06）")
    rubric_reported = all("rubric" in c and c["rubric"] for c in report["cases"])
    if not rubric_reported:
        problems.append("报告缺 rubric 分维明细")
    metrics = {"pass_rate": report["pass_rate"], "score_100": report["totals"]["score_100"],
               "cases": len(report["cases"]), "archives": len(archive),
               "golden_set_version": report["golden_set_version"]}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"evaluator 对 mock release 全流程离线可跑：{len(report['cases'])} 案例"
                         f" pass_rate={report['pass_rate']} score_100={report['totals']['score_100']}；"
                         f"结果归档 runs/ 且二次评估逐案一致", metrics)


EXECUTORS = {
    "m6.trajectory_export": exec_trajectory_export,
    "m6.trajectory_counts": exec_trajectory_counts,
    "m6.trajectory_reject": exec_trajectory_reject,
    "m6.golden_isolation": exec_golden_isolation,
    "m6.golden_ci": exec_golden_ci,
    "m6.golden_seeds": exec_golden_seeds,
    "m6.judge_expression": exec_judge_expression,
    "m6.rubric": exec_rubric,
    "m6.badcase_ab": exec_badcase_ab,
    "m6.skillize": exec_skillize,
    "m6.release_flip": exec_release_flip,
    "m6.evaluator_flow": exec_evaluator_flow,
}
