# -*- coding: utf-8 -*-
"""tests/m8_eval_extra.py · M8 需量分析与容需切换技能（skills/demand-analysis）EVAL 插件。

插件契约同 tests/EVAL-SCHEMA.md §4：暴露 ``EXECUTORS: dict[str, callable]``，
执行器签名 ``fn(case: dict, ctx) -> {"passed": bool, "detail": str, "metrics": dict}``。

五个执行器（全部数据驱动，断言取自用例 params/expect，零案例特判）：

- ``m8.stats``        SPEC-M8-01 需量统计正确性（月峰标定/时刻/Top5/峰段占比/负荷率）；
- ``m8.billing``      SPEC-M8-02/04 临界点数学与参数敏感性（两档基本电费、分界点、
                      假设检验、换价变体与建议反转）；
- ``m8.criteria``     SPEC-M8-03 判据引用（PHYS-DEMAND 分级逐点核对，阈值与
                      regulations/REG-TECH.yaml 原文交叉比对，结论引用规则 ID）；
- ``m8.determinism``  SPEC-M8-05 确定性重放（API 多轮 + CLI(--json) 双跑逐字节一致，
                      换 seed 序列分化）；
- ``m8.negative``     SPEC-M8-07 无效参数拒绝（ValueError，中文原因达口径）。

运行入口（run_evals.py 的 MODULES 门禁固定 m0..m7 只读，m8 不进该门禁，与 M9 套件
同口径；本入口以同一 runner 路径——schema 校验 + spec_hash 重算比对 + 插件加载 +
逐用例执行——运行 tests/test_m8.yaml）::

    python tests/m8_eval_extra.py        # 仓库根；退出码 0=全过 1=有失败
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parent
CALC_PATH = _REPO_ROOT / "skills" / "demand-analysis" / "calc_demand.py"
REG_TECH = _REPO_ROOT / "regulations" / "REG-TECH.yaml"

__all__ = ["EXECUTORS", "main"]

_CALC_CACHE: dict = {}


def _calc_module():
    """按文件位置加载 skills/demand-analysis/calc_demand.py（目录名含连字符，无法常规 import）。"""
    cached = _CALC_CACHE.get("mod")
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location("demand_analysis_calc", CALC_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - 环境异常
        raise ImportError(f"无法加载 {CALC_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _CALC_CACHE["mod"] = module
    return module


def _result(passed: bool, detail: str, metrics: dict | None = None) -> dict:
    return {"passed": bool(passed), "detail": str(detail), "metrics": metrics or {}}


def _in_range(value: float, bounds: list) -> bool:
    return len(bounds) == 2 and float(bounds[0]) <= float(value) <= float(bounds[1])


def _close(value: float, want: float, tol: float) -> bool:
    return abs(float(value) - float(want)) <= float(tol)


# ---------------------------------------------------------------------------
# m8.stats · SPEC-M8-01 需量统计正确性
# ---------------------------------------------------------------------------
def exec_stats(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    calc = _calc_module()
    result = calc.run_analysis(params or None, repo=ctx.root if hasattr(ctx, "root") else _REPO_ROOT)
    park, stats = result["park"], result["series_stats"]
    problems: list = []

    for section, key in (("park", "park_id"), ("park", "tariff"),
                         ("park", "contract_capacity_kw"), ("park", "ledger_peak_kw"),
                         ("series_stats", "points"), ("series_stats", "month_peak_kw"),
                         ("series_stats", "month_peak_at"), ("series_stats", "month_peak_period")):
        if key in expect:
            source = park if section == "park" else stats
            if source.get(key if key != "park_id" else "id") != expect[key]:
                problems.append(f"{section}.{key}={source.get(key if key != 'park_id' else 'id')!r}"
                                f" != 期望 {expect[key]!r}")

    if "top5_dates" in expect:
        got = [t["date"] for t in stats["top5_days"]]
        if got != list(expect["top5_dates"]):
            problems.append(f"top5 日期序 {got} != 期望 {expect['top5_dates']}")
        if len(set(got)) != len(got):
            problems.append(f"top5 高峰日日期重复: {got}")
    if "top5_peaks_kw" in expect:
        got = [t["peak_kw"] for t in stats["top5_days"]]
        if got != list(expect["top5_peaks_kw"]):
            problems.append(f"top5 峰值序 {got} != 期望 {expect['top5_peaks_kw']}")
    if "peak_windows" in expect and stats["peak_windows"] != list(expect["peak_windows"]):
        problems.append(f"峰段窗口 {stats['peak_windows']} != 期望 {expect['peak_windows']}")
    if "peak_energy_ratio_range" in expect and not _in_range(stats["peak_energy_ratio"],
                                                             expect["peak_energy_ratio_range"]):
        problems.append(f"峰段电量占比 {stats['peak_energy_ratio']} 不在 {expect['peak_energy_ratio_range']}")
    if "load_factor_range" in expect and not _in_range(stats["load_factor"], expect["load_factor_range"]):
        problems.append(f"负荷率 {stats['load_factor']} 不在 {expect['load_factor_range']}")
    if "period_ratio_sum_to" in expect:
        total = sum(stats["period_energy_ratio"].values())
        if not _close(total, expect["period_ratio_sum_to"], 1e-3):
            problems.append(f"峰平谷占比合计 {total} != {expect['period_ratio_sum_to']}")
    if "calibration_note_contains" in expect:
        note = json.dumps(park["synthesis"], ensure_ascii=False)
        for token in expect["calibration_note_contains"]:
            if token not in note:
                problems.append(f"标定口径未提及 {token!r}")
    # 口径自证：月峰必须等于台账值（SPEC-M8-01 标定定义）
    if stats["month_peak_kw"] != park["ledger_peak_kw"]:
        problems.append(f"月峰 {stats['month_peak_kw']} != 台账 {park['ledger_peak_kw']}（标定失效）")

    metrics = {"month_peak_kw": stats["month_peak_kw"], "month_peak_at": stats["month_peak_at"],
               "load_factor": stats["load_factor"], "peak_energy_ratio": stats["peak_energy_ratio"]}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"月峰 {stats['month_peak_kw']:.1f} kW @ {stats['month_peak_at']}"
                         f"（{stats['month_peak_period']}段，=台账标定）；Top5 {stats['top5_days'][0]['date']}"
                         f" 等 5 日；峰段占比 {stats['peak_energy_ratio']:.1%}；"
                         f"负荷率 {stats['load_factor']:.1%}", metrics)


# ---------------------------------------------------------------------------
# m8.billing · SPEC-M8-02 临界点数学 + SPEC-M8-04 参数敏感性
# ---------------------------------------------------------------------------
def exec_billing(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    calc = _calc_module()
    repo = ctx.root if hasattr(ctx, "root") else _REPO_ROOT
    problems: list = []
    metrics: dict = {}

    base = {
        "month_peak_kw": float(params.get("month_peak_kw", 1720)),
        "contract_capacity_kw": float(params.get("contract_capacity_kw", 2000)),
        "demand_price_yuan_per_kw_month": float(params.get("demand_price", 48)),
        "capacity_price_yuan_per_kw_month": float(params.get("capacity_price", 32)),
    }
    if "variants" in params:  # SPEC-M8-04：换价变体逐一复算
        recommendations: list = []
        for i, variant in enumerate(params["variants"]):
            merged = dict(base)
            merged.update({"demand_price_yuan_per_kw_month": float(variant["demand_price"]),
                           "capacity_price_yuan_per_kw_month": float(variant["capacity_price"])})
            bill = calc.compute_billing(merged["month_peak_kw"], merged["contract_capacity_kw"], merged)
            if i < len(expect.get("variant_thresholds_kw") or []) and not _close(
                    bill["threshold_kw"], expect["variant_thresholds_kw"][i], 0.01):
                problems.append(f"变体{i} 临界点 {bill['threshold_kw']} != 期望 "
                                f"{expect['variant_thresholds_kw'][i]}")
            if i < len(expect.get("variant_cheaper") or []) and \
                    bill["cheaper"] != expect["variant_cheaper"][i]:
                problems.append(f"变体{i} 更省档 {bill['cheaper']} != 期望 {expect['variant_cheaper'][i]}")
            if i < len(expect.get("variant_savings_yuan_per_month") or []) and not _close(
                    bill["saving_yuan_per_month"], expect["variant_savings_yuan_per_month"][i], 0.01):
                problems.append(f"变体{i} 月省 {bill['saving_yuan_per_month']} != 期望 "
                                f"{expect['variant_savings_yuan_per_month'][i]}")
            # 全链重跑（同价参数）验证建议语随参数反转（结论不硬编码）
            full = calc.run_analysis({
                "demand_price_yuan_per_kw_month": merged["demand_price_yuan_per_kw_month"],
                "capacity_price_yuan_per_kw_month": merged["capacity_price_yuan_per_kw_month"]}, repo=repo)
            recommendations.append(full["recommendation"])
            if i < len(expect.get("variant_recommendation_contains") or []):
                for token in expect["variant_recommendation_contains"][i]:
                    if token not in full["recommendation"]:
                        problems.append(f"变体{i} 建议语未含 {token!r}（换价后结论未反转？）")
            metrics[f"variant{i}"] = {"threshold_kw": bill["threshold_kw"], "cheaper": bill["cheaper"]}
        # 两变体建议语必须分化（参数敏感性反证：不是同一句模板）
        if len(recommendations) == 2 and recommendations[0] == recommendations[1]:
            problems.append("两变体建议语完全相同——结论未随电价参数变化")
        if problems:
            return _result(False, "；".join(problems), metrics)
        return _result(True, f"{len(params['variants'])} 个换价变体：临界点/更省档/月省/建议语全部随参数"
                             f"数据驱动反转（非硬编码结论）", metrics)

    bill = calc.compute_billing(base["month_peak_kw"], base["contract_capacity_kw"], base)
    for key in ("demand_billing_yuan", "capacity_billing_yuan", "saving_yuan_per_month"):
        if key in expect and not _close(bill[key], expect[key], 0.01):
            problems.append(f"{key}={bill[key]!r} != 期望 {expect[key]!r}")
    if "cheaper" in expect and bill["cheaper"] != expect["cheaper"]:
        problems.append(f"cheaper={bill['cheaper']!r} != 期望 {expect['cheaper']!r}")
    if "threshold_kw" in expect and not _close(bill["threshold_kw"], expect["threshold_kw"],
                                               expect.get("threshold_tolerance", 0.01)):
        problems.append(f"threshold_kw={bill['threshold_kw']} != 期望 {expect['threshold_kw']}")
    if "param_note_contains" in expect:
        for token in expect["param_note_contains"]:
            if token not in bill["param_note"]:
                problems.append(f"param_note 未含 {token!r}（演示参数标注缺失）")
    if "hypothetical_md_kw" in expect:  # 分界两侧假设检验：临界点上下各取一点
        got_cheaper = []
        for md in params["hypothetical_md_kw"]:
            probe = calc.compute_billing(float(md), base["contract_capacity_kw"], base)
            got_cheaper.append(probe["cheaper"])
        if got_cheaper != list(expect["hypothetical_cheaper"]):
            problems.append(f"假设 MD {params['hypothetical_md_kw']} 的更省档 {got_cheaper}"
                            f" != 期望 {expect['hypothetical_cheaper']}")
        metrics["hypothetical_cheaper"] = got_cheaper
    metrics.update({"threshold_kw": bill["threshold_kw"], "cheaper": bill["cheaper"],
                    "demand_billing_yuan": bill["demand_billing_yuan"],
                    "capacity_billing_yuan": bill["capacity_billing_yuan"]})
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"按需 {bill['demand_billing_yuan']:,.0f} vs 按容"
                         f" {bill['capacity_billing_yuan']:,.0f} 元/月；临界点"
                         f" {bill['threshold_kw']:.2f} kW；更省={bill['cheaper']}"
                         f"（月省 {bill['saving_yuan_per_month']:,.0f}）", metrics)


# ---------------------------------------------------------------------------
# m8.criteria · SPEC-M8-03 判据引用（PHYS-DEMAND 分级 + 规程库交叉比对）
# ---------------------------------------------------------------------------
def exec_criteria(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    calc = _calc_module()
    repo = ctx.root if hasattr(ctx, "root") else _REPO_ROOT
    problems: list = []
    capacity = float(params.get("contract_capacity_kw", 2000))

    thresholds = calc.load_demand_thresholds(repo)
    # 阈值与规程库原文交叉比对（判据唯一来源，代码不另设口径）
    import yaml
    reg = yaml.safe_load(REG_TECH.read_text(encoding="utf-8")) or {}
    rule = next(r for r in reg.get("rules") or [] if r.get("id") == "PHYS-DEMAND")
    reg_warn = next(float(t["value"]) for t in rule["thresholds"] if t.get("level") == "P2")
    reg_breach = next(float(t["value"]) for t in rule["thresholds"] if t.get("level") == "P0")
    if (thresholds["warn_over"], thresholds["breach_over"]) != (reg_warn, reg_breach):
        problems.append(f"执行器阈值 ({thresholds['warn_over']}, {thresholds['breach_over']})"
                        f" != 规程库原文 ({reg_warn}, {reg_breach})")

    verdicts = [calc.judge_demand(float(kw), capacity, thresholds) for kw in params.get("whatif_kw") or []]
    got_levels = [v["level"] for v in verdicts]
    if got_levels != list(expect.get("levels") or []):
        problems.append(f"分级序 {got_levels} != 期望 {expect['levels']}")
    got_ratios = [v["demand_ratio"] for v in verdicts]
    if got_ratios != list(expect.get("ratios") or []):
        problems.append(f"需量比序 {got_ratios} != 期望 {expect['ratios']}")
    if expect.get("rule_ids") and any(v["rule_ids"] != list(expect["rule_ids"]) for v in verdicts):
        problems.append(f"存在未引用规则 ID {expect['rule_ids']} 的分级结论")
    if "warn_kw" in expect and verdicts[0]["warn_kw"] != float(expect["warn_kw"]):
        problems.append(f"预警线 {verdicts[0]['warn_kw']} != 期望 {expect['warn_kw']}")
    if "breach_kw" in expect and verdicts[0]["breach_kw"] != float(expect["breach_kw"]):
        problems.append(f"越限线 {verdicts[0]['breach_kw']} != 期望 {expect['breach_kw']}")
    if expect.get("thresholds_source") and calc.REG_TECH_FILE != expect["thresholds_source"]:
        problems.append(f"阈值读取源 {calc.REG_TECH_FILE} != 期望 {expect['thresholds_source']}")

    # 全链结论引用（run_analysis 的 criteria.conclusion 必须含规则 ID 与两线）
    result = calc.run_analysis(repo=repo)
    crit = result["criteria"]
    for token in expect.get("conclusion_contains") or []:
        if token not in crit["conclusion"]:
            problems.append(f"结论未含 {token!r}")
    if crit["rule_ids"] != list(expect.get("rule_ids") or ["PHYS-DEMAND"]):
        problems.append(f"结论 rule_ids {crit['rule_ids']} != 期望 {expect['rule_ids']}")

    metrics = {"levels": got_levels, "warn_kw": verdicts[0]["warn_kw"] if verdicts else None,
               "breach_kw": verdicts[0]["breach_kw"] if verdicts else None,
               "reg_thresholds": [reg_warn, reg_breach]}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"{len(verdicts)} 点分级全对（阈值 {reg_warn}/{reg_breach} 与"
                         f" {expect.get('thresholds_source')} 原文一致）；结论引用"
                         f" {expect['rule_ids']}，预警线 {expect['warn_kw']}kW / 越限线"
                         f" {expect['breach_kw']}kW", metrics)


# ---------------------------------------------------------------------------
# m8.determinism · SPEC-M8-05 确定性重放
# ---------------------------------------------------------------------------
def exec_determinism(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    calc = _calc_module()
    repo = ctx.root if hasattr(ctx, "root") else _REPO_ROOT
    problems: list = []
    seed = int(params.get("seed", 20260901))
    runs = int(params.get("runs", 3))

    dumps = [json.dumps(calc.run_analysis({"seed": seed}, repo=repo),
                        ensure_ascii=False, sort_keys=True) for _ in range(runs)]
    api_identical = len(set(dumps)) == 1
    if expect.get("api_identical") and not api_identical:
        problems.append(f"API {runs} 轮渲染出现 {len(set(dumps))} 种输出")

    sandbox = repo / "runtime" / "m8_eval" / str(case.get("id") or "case")
    sandbox.mkdir(parents=True, exist_ok=True)
    outs = []
    for i in range(2):
        out = sandbox / f"cli-run{i}.json"
        proc = subprocess.run([sys.executable, str(CALC_PATH), "--json", "--seed", str(seed)],
                              capture_output=True, text=True, encoding="utf-8", cwd=str(sandbox))
        if proc.returncode != 0:
            problems.append(f"CLI run{i} 退出码 {proc.returncode}: {proc.stderr[:120]}")
            return _result(False, "；".join(problems), {})
        out.write_text(proc.stdout, encoding="utf-8")
        outs.append(proc.stdout)
    cli_identical = outs[0] == outs[1]
    if expect.get("cli_identical") and not cli_identical:
        problems.append("CLI(--json) 双跑输出不一致")
    cli_matches_api = json.loads(outs[0]) == json.loads(dumps[0])
    if expect.get("cli_matches_api") and not cli_matches_api:
        problems.append("CLI 输出与 API 内存结果不等价")

    if params.get("alt_seed") is not None:
        alt = json.dumps(calc.run_analysis({"seed": int(params["alt_seed"])}, repo=repo),
                         ensure_ascii=False, sort_keys=True)
        alt_differs = alt != dumps[0]
        if expect.get("alt_seed_differs") and not alt_differs:
            problems.append(f"换 seed({params['alt_seed']}) 输出与原 seed 相同（疑似缓存假象）")

    metrics = {"runs": runs, "api_identical": api_identical, "cli_identical": cli_identical,
               "cli_matches_api": cli_matches_api}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"API {runs} 轮 + CLI 双跑逐字节一致，且 CLI 与内存结果等价；"
                         f"换 seed 序列分化（确定性=种子驱动，非缓存）", metrics)


# ---------------------------------------------------------------------------
# m8.schema · SPEC-M8-06 输出 schema（键封闭 + 类型）
# ---------------------------------------------------------------------------
def exec_schema(case: dict, ctx: Any) -> dict:
    expect = case.get("expect") or {}
    calc = _calc_module()
    repo = ctx.root if hasattr(ctx, "root") else _REPO_ROOT
    result = calc.run_analysis(repo=repo)
    problems: list = []

    def check_keys(label: str, obj: dict, want: list) -> None:
        got = sorted(obj.keys())
        if got != sorted(want):
            problems.append(f"{label} 键集 {got} != 期望 {sorted(want)}")

    check_keys("顶层", result, expect.get("top_keys") or [])
    check_keys("park", result["park"], expect.get("park_keys") or [])
    check_keys("series_stats", result["series_stats"], expect.get("series_stats_keys") or [])
    check_keys("billing", result["billing"], expect.get("billing_keys") or [])
    check_keys("criteria", result["criteria"], expect.get("criteria_keys") or [])
    for i, day in enumerate(result["series_stats"]["top5_days"]):
        check_keys(f"top5_days[{i}]", day, expect.get("top5_day_keys") or [])

    type_probes = [
        ("month_peak_kw", result["series_stats"]["month_peak_kw"], (int, float)),
        ("load_factor", result["series_stats"]["load_factor"], (int, float)),
        ("threshold_kw", result["billing"]["threshold_kw"], (int, float)),
        ("demand_ratio", result["criteria"]["demand_ratio"], (int, float)),
        ("points", result["series_stats"]["points"], int),
        ("rule_ids", result["criteria"]["rule_ids"], list),
        ("recommendation", result["recommendation"], str),
        ("peak_windows", result["series_stats"]["peak_windows"], list),
    ]
    for name, value, types in type_probes:
        if not isinstance(value, types) or isinstance(value, bool):
            problems.append(f"{name} 类型 {type(value).__name__} != {types}")
    # 值域：负荷率与需量比 ∈ (0,1+]，Top5 恰 5 条
    if not 0.0 < result["series_stats"]["load_factor"] <= 1.0:
        problems.append(f"负荷率 {result['series_stats']['load_factor']} 越出 (0,1]")
    if len(result["series_stats"]["top5_days"]) != 5:
        problems.append(f"top5_days {len(result['series_stats']['top5_days'])} 条 != 5")

    metrics = {"top_keys": len(result), "series_stats_keys": len(result["series_stats"]),
               "billing_keys": len(result["billing"]), "criteria_keys": len(result["criteria"])}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"五段键封闭（{metrics}）+ 标量类型/值域全达口径（JSON 可序列化）", metrics)


# ---------------------------------------------------------------------------
# m8.negative · SPEC-M8-07 无效参数拒绝
# ---------------------------------------------------------------------------
def exec_negative(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    calc = _calc_module()
    repo = ctx.root if hasattr(ctx, "root") else _REPO_ROOT
    problems: list = []
    checked = 0

    for probe in params.get("probes") or []:
        name = str(probe.get("name") or "probe")
        try:
            calc.run_analysis(probe.get("params") or {}, repo=repo)
        except ValueError as exc:
            checked += 1
            for token in probe.get("error_contains") or []:
                if token not in str(exc):
                    problems.append(f"{name}: 拒绝消息未含 {token!r}: {exc}")
        except Exception as exc:  # noqa: BLE001 - 异常类型不符即失败
            problems.append(f"{name}: 异常类型 {type(exc).__name__} != {expect.get('exception_type')}: {exc}")
        else:
            problems.append(f"{name}: 期望拒绝但分析出数（带病输出）")

    metrics = {"probes": len(params.get("probes") or []), "rejected": checked}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"{checked} 个探针全部按预期拒绝（{expect.get('exception_type')}"
                         f"，中文原因达口径）", metrics)


EXECUTORS = {
    "m8.stats": exec_stats,
    "m8.billing": exec_billing,
    "m8.criteria": exec_criteria,
    "m8.determinism": exec_determinism,
    "m8.schema": exec_schema,
    "m8.negative": exec_negative,
}


# ---------------------------------------------------------------------------
# 套件运行入口：以 run_evals 同一 runner 路径执行 tests/test_m8.yaml
# ---------------------------------------------------------------------------
def main(argv: list | None = None) -> int:
    root_str = str(_REPO_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    import run_evals

    saved = run_evals.MODULES
    run_evals.MODULES = saved + ("m8",)  # 仅本进程内扩一名，不改 run_evals.py 文件
    try:
        ctx = run_evals.EvalContext(run_evals.ROOT)
        report = run_evals.run_module_suite("m8", ctx)
    finally:
        run_evals.MODULES = saved

    for item in report["cases"]:
        print(f"[{item['status']}] {item['id']} :: {item['title']} :: {item['detail'][:200]}")
    summary = report["summary"]
    ok = report["status"] == "RAN" and summary["failed"] == 0
    print(f"EVALS-M8 mode=suite status={report['status']} "
          f"cases={summary['passed']}/{summary['total']} failed={summary['failed']} "
          f"skipped={summary['skipped']} result={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
