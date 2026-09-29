# -*- coding: utf-8 -*-
"""tests/m9_eval_extra.py · M9 应急分级技能（skills/emergency-grading）EVAL 插件。

插件契约同 tests/EVAL-SCHEMA.md §4：暴露 ``EXECUTORS: dict[str, callable]``，
执行器签名 ``fn(case: dict, ctx) -> {"passed": bool, "detail": str, "metrics": dict}``。

四个执行器（全部数据驱动，断言取自用例 params/expect，零案例特判）：

- ``m9.grade``           通用分级断言（级别/时限/P 级/basis 逐条/岗位清单/升降级条件/
                         manual_review），EG-SPEC-02/03/04/05 正反面共用；
- ``m9.determinism``    EG-SPEC-06 确定性：模块路径多轮渲染逐字节一致 + CLI(--json)
                         双跑输出一致且与内存结果等价；
- ``m9.data_driven``     EG-SPEC-07 数据驱动性：沙箱副本改映射条目（级别/时限/P 级），
                         baseline 与 patched 判定随之分化；线上 SKILL.yaml 零改动
                         （前后 sha256 相等）；替换表经 load_mapping 重载复算一致；
- ``m9.negative_input`` EG-SPEC-08 负向拒绝：缺 id/空 type/重复 id → GradeInputError；
                         映射表事件类型二义 → MappingError。

运行入口（run_evals.py 的 MODULES 门禁固定 m0..m7 只读，m9 不进该门禁；本入口以
同一 runner 路径——schema 校验 + spec_hash 重算比对 + 插件加载 + 逐用例执行——运行
tests/test_m9.yaml）::

    python tests/m9_eval_extra.py        # 仓库根；退出码 0=全过 1=有失败
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any

import yaml

_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parent
GRADE_PATH = _REPO_ROOT / "skills" / "emergency-grading" / "grade.py"
SKILL_YAML = _REPO_ROOT / "skills" / "emergency-grading" / "SKILL.yaml"

__all__ = ["EXECUTORS", "main"]

_GRADE_CACHE: dict = {}


def _grade_module():
    """按文件位置加载 skills/emergency-grading/grade.py（目录名含连字符，无法常规 import）。"""
    cached = _GRADE_CACHE.get("mod")
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location("emergency_grading_grade", GRADE_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - 环境异常
        raise ImportError(f"无法加载 {GRADE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _GRADE_CACHE["mod"] = module
    return module


def _result(passed: bool, detail: str, metrics: dict | None = None) -> dict:
    return {"passed": bool(passed), "detail": str(detail), "metrics": metrics or {}}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sandbox(ctx: Any, case: dict) -> Path:
    box = Path(ctx.root) / "runtime" / "m9_eval" / str(case.get("id") or "case")
    box.mkdir(parents=True, exist_ok=True)
    return box


def _assert_contains(haystack: list, tokens: list, label: str, problems: list) -> None:
    for token in tokens or []:
        if not any(token in str(item) for item in haystack):
            problems.append(f"{label} 未包含 {token!r}（实际 {len(haystack)} 条）")


# ---------------------------------------------------------------------------
# m9.grade · 通用分级断言（EG-SPEC-02/03/04/05）
# ---------------------------------------------------------------------------
def exec_grade(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    module = _grade_module()
    mapping = module.load_mapping(SKILL_YAML)
    result = module.grade(params.get("alarms") or [], mapping)
    problems: list = []

    for key in ("decision", "suggested_level", "level_name", "p_priority",
                "time_limit_minutes", "contributing_levels"):
        if key in expect and result.get(key) != expect[key]:
            problems.append(f"{key}={result.get(key)!r} != 期望 {expect[key]!r}")

    if "basis" in expect:
        got = [{k: item.get(k) for k in ("alarm_id", "rule_id", "level")}
               for item in (result.get("basis") or [])]
        if got != expect["basis"]:
            problems.append(f"basis（告警ID×条款×级别，按输入序）不一致: {got} != 期望 {expect['basis']}")

    if "posts_expected" in expect:
        got_posts = list((result.get("posts") or {}).keys())
        if got_posts != list(expect["posts_expected"]):
            problems.append(f"posts 岗位序列 {got_posts} != 期望 {list(expect['posts_expected'])}")

    for post, tokens in (expect.get("post_ops_contain") or {}).items():
        ops = (result.get("posts") or {}).get(post) or []
        _assert_contains(ops, tokens, f"posts[{post}]", problems)

    if "manual_review_ids" in expect:
        got_ids = [item.get("alarm_id") for item in (result.get("manual_review") or [])]
        if got_ids != list(expect["manual_review_ids"]):
            problems.append(f"manual_review ids {got_ids} != 期望 {list(expect['manual_review_ids'])}")

    _assert_contains(result.get("escalate_when") or [], expect.get("escalate_contains"),
                     "escalate_when", problems)
    _assert_contains(result.get("release_when") or [], expect.get("release_contains"),
                     "release_when", problems)

    metrics = {"decision": result.get("decision"), "level": result.get("suggested_level"),
               "time_limit_minutes": result.get("time_limit_minutes"),
               "basis_entries": len(result.get("basis") or []),
               "manual_review": len(result.get("manual_review") or [])}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"分级断言全部成立（level={result.get('suggested_level')!r} "
                         f"时限={result.get('time_limit_minutes')}min "
                         f"basis={len(result.get('basis') or [])} 条 "
                         f"manual_review={len(result.get('manual_review') or [])} 条）", metrics)


# ---------------------------------------------------------------------------
# m9.determinism · EG-SPEC-06 确定性
# ---------------------------------------------------------------------------
def exec_determinism(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    module = _grade_module()
    alarms = params.get("alarms") or []
    runs = int(params.get("runs") or 2)

    renders: list = []
    results: list = []
    for _ in range(runs):
        mapping = module.load_mapping(SKILL_YAML)  # 每轮从盘上重载
        one = module.grade(alarms, mapping)
        results.append(one)
        renders.append(module.render(one))
    problems: list = []
    if len(set(renders)) != 1:
        problems.append(f"{runs} 轮渲染不一致（逐字节）")
    for one in results[1:]:
        if one != results[0]:
            problems.append("多轮内存结果 dict 不一致")
    if not renders or not renders[0].strip():
        problems.append("渲染输出为空")

    # CLI 通道（--json）双跑：输出一致且与内存结果等价
    box = _sandbox(ctx, case)
    input_path = box / "input.yaml"
    input_path.write_text(yaml.safe_dump({"alarms": alarms}, allow_unicode=True, sort_keys=False),
                          encoding="utf-8")
    cli_outputs: list = []
    exit_codes: list = []
    for _ in range(2):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = module.main([str(input_path), "--json"])
        cli_outputs.append(buffer.getvalue())
        exit_codes.append(code)
    if exit_codes != [0, 0]:
        problems.append(f"CLI 退出码 {exit_codes} != [0, 0]")
    if len(set(cli_outputs)) != 1:
        problems.append("CLI 双跑输出不一致")
    else:
        try:
            if json.loads(cli_outputs[0]) != results[0]:
                problems.append("CLI JSON 输出与内存结果不等价")
        except json.JSONDecodeError as exc:
            problems.append(f"CLI 输出非 JSON: {exc}")
    for token in expect.get("contains") or []:
        if token not in renders[0]:
            problems.append(f"渲染输出未包含 {token!r}")

    digest = hashlib.sha256(renders[0].encode("utf-8")).hexdigest()[:16]
    metrics = {"runs": runs, "render_sha256_16": digest, "cli_exit": exit_codes}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"{runs} 轮模块渲染 + 2 次 CLI 双跑全部逐字节一致"
                         f"（render sha256[:16]={digest}）", metrics)


# ---------------------------------------------------------------------------
# m9.data_driven · EG-SPEC-07 数据驱动性（沙箱副本改表，线上表零改动）
# ---------------------------------------------------------------------------
def exec_data_driven(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    module = _grade_module()
    alarms = params.get("alarms") or []
    patch = params.get("patch") or {}

    before_sha = _sha256(SKILL_YAML)
    mapping = module.load_mapping(SKILL_YAML)
    baseline = module.grade(alarms, mapping)

    patched = copy.deepcopy(mapping)
    hit = 0
    for rule in patched.get("rules") or []:
        if rule.get("rule_id") == patch.get("rule_id"):
            rule.update(patch.get("set") or {})
            hit += 1
    problems: list = []
    if hit != 1:
        problems.append(f"沙箱副本命中规则 {hit} 条（patch.rule_id={patch.get('rule_id')!r}），应为 1")

    after = module.grade(alarms, patched)
    after_sha = _sha256(SKILL_YAML)
    if before_sha != after_sha:
        problems.append(f"线上 SKILL.yaml 被改动（sha256 {before_sha[:16]}… → {after_sha[:16]}…）")

    for label, probe in (("baseline", baseline), ("patched", after)):
        want = expect.get(label) or {}
        for key in ("suggested_level", "level_name", "p_priority", "time_limit_minutes"):
            if key in want and probe.get(key) != want[key]:
                problems.append(f"{label}.{key}={probe.get(key)!r} != 期望 {want[key]!r}")

    # 替换表落盘 → load_mapping 重载 → 复算一致（证明「整表替换预案」路径可用）
    box = _sandbox(ctx, case)
    replacement = box / "mapping-patched.yaml"
    replacement.write_text(yaml.safe_dump(
        {"emergency_grading": patched}, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8")
    reloaded = module.grade(alarms, module.load_mapping(replacement))
    if reloaded != after:
        problems.append("替换表落盘重载后的复算结果与内存 patched 结果不一致")

    metrics = {"rule_id": patch.get("rule_id"), "set": patch.get("set"),
               "baseline_level": baseline.get("suggested_level"),
               "patched_level": after.get("suggested_level"),
               "skill_yaml_sha256_16": after_sha[:16]}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"改表前 {expect.get('baseline', {}).get('suggested_level')!r}/"
                         f"{expect.get('baseline', {}).get('time_limit_minutes')}min → 改表后 "
                         f"{after.get('suggested_level')!r}/{after.get('time_limit_minutes')}min；"
                         f"线上表 sha256 前后一致（{after_sha[:16]}…），替换表重载复算一致", metrics)


# ---------------------------------------------------------------------------
# m9.negative_input · EG-SPEC-08 负向拒绝
# ---------------------------------------------------------------------------
def exec_negative_input(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    module = _grade_module()
    mapping = module.load_mapping(SKILL_YAML)
    problems: list = []
    checked = 0

    for probe in params.get("probes") or []:
        name = str(probe.get("name") or "probe")
        kind = str(probe.get("kind") or "alarms")
        try:
            if kind == "alarms":
                module.grade(probe.get("alarms") or [], mapping)
            elif kind == "mapping":
                box = _sandbox(ctx, case)
                bad_path = box / f"mapping-{name}.yaml"
                bad_path.write_text(yaml.safe_dump(probe.get("mapping"),
                                                   allow_unicode=True, sort_keys=False),
                                    encoding="utf-8")
                module.load_mapping(bad_path)
            else:
                problems.append(f"{name}: 未知探针 kind {kind!r}")
                continue
        except module.GradeInputError as exc:
            checked += 1
            for token in probe.get("error_contains") or []:
                if token not in str(exc):
                    problems.append(f"{name}: 拒绝消息未含 {token!r}: {exc}")
        except module.MappingError as exc:
            checked += 1
            for token in probe.get("error_contains") or []:
                if token not in str(exc):
                    problems.append(f"{name}: 拒绝消息未含 {token!r}: {exc}")
        except Exception as exc:  # noqa: BLE001 - 异常类型不符即失败
            problems.append(f"{name}: 异常类型 {type(exc).__name__} 非 GradeInputError/MappingError: {exc}")
        else:
            problems.append(f"{name}: 期望拒绝但判定通过")

    metrics = {"probes": len(params.get("probes") or []), "rejected": checked}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"{checked} 个探针全部按预期拒绝（异常类型与消息达口径）", metrics)


EXECUTORS = {
    "m9.grade": exec_grade,
    "m9.determinism": exec_determinism,
    "m9.data_driven": exec_data_driven,
    "m9.negative_input": exec_negative_input,
}


# ---------------------------------------------------------------------------
# 套件运行入口：以 run_evals 同一 runner 路径执行 tests/test_m9.yaml
# ---------------------------------------------------------------------------
def main(argv: list | None = None) -> int:
    root_str = str(_REPO_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    import run_evals

    saved = run_evals.MODULES
    run_evals.MODULES = saved + ("m9",)  # 仅本进程内扩一名，不改 run_evals.py 文件
    try:
        ctx = run_evals.EvalContext(run_evals.ROOT)
        report = run_evals.run_module_suite("m9", ctx)
    finally:
        run_evals.MODULES = saved

    for item in report["cases"]:
        print(f"[{item['status']}] {item['id']} :: {item['title']} :: {item['detail'][:200]}")
    summary = report["summary"]
    ok = report["status"] == "RAN" and summary["failed"] == 0
    print(f"EVALS-M9 mode=suite status={report['status']} "
          f"cases={summary['passed']}/{summary['total']} failed={summary['failed']} "
          f"skipped={summary['skipped']} result={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
