# -*- coding: utf-8 -*-
"""tests/m7_eval_extra.py · M7 EVAL v2 补充执行器（specs-v2/M7-registry-release.md §4）。

插件契约同 tests/EVAL-SCHEMA.md §4：暴露 ``EXECUTORS: dict[str, callable]``；
执行器签名 ``fn(case: dict, ctx) -> {"passed": bool, "detail": str, "metrics": dict}``。

只补 oracle 执行器（``src/m7_registry/eval_plugin.py``，本轮零改动）没有的四个执行面：

- ``m7.descriptor_validation``  SPEC-M7-01 资产描述子校验拒绝（AssetValidationError）；
- ``m7.review_guards``          SPEC-M7-05 提案三要素守卫 + 终态不可改写；
- ``m7.contract_validation``    SPEC-M7-14 AgentContract 校验拒绝（AgentContractError）；
- ``m7.diff``                   SPEC-M7-15 ``diff_release`` 结构化差分。

全部数据驱动（断言数据取自用例 params/expect，零案例特判）；沙箱=内存 AssetStore
（now_fn 固定常数，确定性，无落盘），与 oracle 插件同一错误类型断言口径。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_SRC = str(Path(__file__).resolve().parents[1] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from m7_registry import agent_contract, assets, publish, review  # noqa: E402

__all__ = ["EXECUTORS"]

_NOW = "2026-09-28T00:00:00Z"


def _result(passed: bool, detail: str, metrics: dict | None = None) -> dict:
    return {"passed": bool(passed), "detail": str(detail), "metrics": metrics or {}}


# ---------------------------------------------------------------------------
# SPEC-M7-01 · 资产描述子校验拒绝（validate_descriptor → AssetValidationError）
# ---------------------------------------------------------------------------
def exec_descriptor_validation(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    problems: list = []
    probes = list(params.get("probes") or [])
    for probe in probes:
        name = str(probe.get("name") or probe.get("asset_type"))
        try:
            assets.validate_descriptor(str(probe.get("asset_type")),
                                       probe.get("descriptor") or {})
        except assets.AssetValidationError as exc:
            for token in probe.get("error_contains") or []:
                if token not in str(exc):
                    problems.append(f"{name}: 拒绝消息未含 {token!r}: {exc}")
        except Exception as exc:  # noqa: BLE001 - 异常类型不符即失败
            problems.append(f"{name}: 异常类型 {type(exc).__name__} "
                            f"!= AssetValidationError: {exc}")
        else:
            problems.append(f"{name}: 期望拒绝但注册校验通过")
    metrics = {"probes": len(probes)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"子契约校验 {len(probes)} 态全部按预期拒绝"
                         f"（AssetValidationError，消息达口径）", metrics)


# ---------------------------------------------------------------------------
# SPEC-M7-05 · 提案三要素守卫 + 终态不可改写（ProposalIncompleteError /
# IllegalReviewTransitionError；终态只读）
# ---------------------------------------------------------------------------
def exec_review_guards(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    store = assets.AssetStore(now_fn=lambda: _NOW)
    for item in params.get("assets") or []:
        store.register_asset(str(item["type"]), item["descriptor"])
    pipeline = review.ReviewPipeline(store, now_fn=lambda: _NOW)
    problems: list = []
    checked = 0

    # 1) 提案缺动机/影响面/关联 Badcase → ProposalIncompleteError
    invalid = list(params.get("invalid_proposals") or [])
    for probe in invalid:
        name = str(probe.get("name") or probe.get("field"))
        kwargs = dict(probe.get("kwargs") or {})
        asset_id = str(probe.get("asset_id") or "")
        try:
            pipeline.submit_proposal(asset_id, **kwargs)
            problems.append(f"{name}: 期望拒绝但提案被受理")
        except review.ProposalIncompleteError as exc:
            for token in probe.get("error_contains") or []:
                if token not in str(exc):
                    problems.append(f"{name}: 拒绝消息未含 {token!r}: {exc}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{name}: 异常类型 {type(exc).__name__} "
                            f"!= ProposalIncompleteError: {exc}")
    checked += len(invalid)

    # 2) 合法提案 → reject 进终态 → 再拒绝/再撤回被拒，终态不被改写
    terminal = list(params.get("terminal_probes") or [])
    valid = params.get("valid_proposal") or None
    if valid:
        proposal = pipeline.submit_proposal(
            str(valid["asset_id"]),
            motivation=str(valid.get("motivation") or "变更动机"),
            impact=str(valid.get("impact") or "影响面"),
            badcases=list(valid.get("badcases") or ["none"]))
        pipeline.reject(proposal.proposal_id, str(valid.get("reject_reason") or "判据未过"))
        record = pipeline.get(proposal.proposal_id)
        if record.state != "REJECTED":
            problems.append(f"reject 后状态 {record.state!r} != REJECTED")
        for probe in terminal:
            name = str(probe.get("name") or probe.get("kind"))
            kind = str(probe.get("kind"))
            try:
                if kind == "reject":
                    pipeline.reject(proposal.proposal_id, "again")
                elif kind == "withdraw":
                    pipeline.withdraw(proposal.proposal_id, "again")
                else:
                    problems.append(f"{name}: 未知探针 kind {kind!r}")
                    continue
                problems.append(f"{name}: 终态迁移未被拒绝")
            except review.IllegalReviewTransitionError as exc:
                for token in probe.get("error_contains") or []:
                    if token not in str(exc):
                        problems.append(f"{name}: 拒绝消息未含 {token!r}: {exc}")
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{name}: 异常类型 {type(exc).__name__} "
                                f"!= IllegalReviewTransitionError: {exc}")
        final_state = str(expect.get("final_state") or "REJECTED")
        if pipeline.get(proposal.proposal_id).state != final_state:
            problems.append(f"探针后终态被改写: {pipeline.get(proposal.proposal_id).state!r}"
                            f" != {final_state!r}")
        checked += len(terminal)

    # 3) publish_state 探针：REJECTED 终态且黄金成绩留痕在档的记录直发 →
    #    四重门禁之第 2 重（state==APPROVED）是唯一拦截位（journal 在/chain 配/留痕在）
    probe_cfg = params.get("publish_state_probe") or None
    if probe_cfg:
        report = {
            "release_id": "rel-review-guard",
            "mode": "SIMULATION",
            "golden_set_version": "dev-guard",
            "cases": [{"case_id": "case_001", "passed": False}],
            "pass_rate": 0.0,
            "totals": {"cases": 1, "passed": 0,
                       "score_100": float(probe_cfg.get("candidate_score_100", 10.0))},
        }
        sandbox = Path(ctx.root) / "runtime" / "m7_eval" / str(case.get("id") or "case")
        sandbox.mkdir(parents=True, exist_ok=True)
        report_path = sandbox / "candidate.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        asset_id = str(probe_cfg["asset_id"])
        p2 = pipeline.submit_proposal(asset_id, motivation="评审守卫探针",
                                      impact="隔离 publish_asset 第 2 重门禁",
                                      badcases=["none"])
        try:
            pipeline.start_evaluation(p2.proposal_id,
                                      candidate_run_ref=str(report_path),
                                      baseline_score=float(probe_cfg.get(
                                          "baseline_score", 100.0)))
            problems.append("publish_state 探针前置不成立：期望 candidate<baseline "
                            "判 REJECTED，实际 APPROVED")
        except review.GoldenRegressionError:
            pass
        rec2 = pipeline.get(p2.proposal_id)
        if rec2.state != "REJECTED":
            problems.append(f"publish_state 探针前置态 {rec2.state!r} != REJECTED")
        elif "candidate_score" not in (rec2.golden or {}):
            problems.append("publish_state 探针前置不成立：黄金成绩留痕缺失")
        else:
            try:
                review.publish_asset(asset_id, p2, store=store, pipeline=pipeline)
                problems.append("REJECTED+黄金留痕记录被置 PUBLISHED"
                                "（state==APPROVED 门禁失效，SPEC-M7-07 第 2 重失守）")
            except review.ReviewBypassError as exc:
                checked += 1
                for token in probe_cfg.get("error_contains") or []:
                    if token not in str(exc):
                        problems.append(f"publish_state 拒绝消息未含 {token!r}: {exc}")
            if store.status_of(asset_id) == "PUBLISHED":
                problems.append("被拒资产状态翻成 PUBLISHED"
                                "（state==APPROVED 门禁失效，SPEC-M7-07 第 2 重失守）")

    metrics = {"invalid_proposals": len(invalid), "terminal_probes": len(terminal),
               "publish_state_probe": bool(probe_cfg)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    parts = []
    if invalid:
        parts.append(f"提案三要素守卫 {len(invalid)} 态全拒（ProposalIncompleteError）")
    if valid:
        parts.append(f"REJECTED 终态后再拒绝/再撤回 {len(terminal)} 探针全拒"
                     f"（IllegalReviewTransitionError）且终态不被改写")
    if probe_cfg:
        parts.append("REJECTED+黄金留痕直发被拒（唯一拦截位=state==APPROVED 门禁，"
                     "ReviewBypassError 消息达口径）")
    return _result(True, "；".join(parts) + f"（断言点 {checked + 1 if probe_cfg else checked}）",
                   metrics)


# ---------------------------------------------------------------------------
# SPEC-M7-14 · AgentContract 校验拒绝（AgentContract.from_dict → AgentContractError）
# ---------------------------------------------------------------------------
def exec_contract_validation(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    problems: list = []
    probes = list(params.get("probes") or [])
    for probe in probes:
        name = str(probe.get("name") or "probe")
        try:
            agent_contract.AgentContract.from_dict(probe.get("descriptor") or {})
        except agent_contract.AgentContractError as exc:
            for token in probe.get("error_contains") or []:
                if token not in str(exc):
                    problems.append(f"{name}: 拒绝消息未含 {token!r}: {exc}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{name}: 异常类型 {type(exc).__name__} "
                            f"!= AgentContractError: {exc}")
        else:
            problems.append(f"{name}: 期望拒绝但校验通过")
    metrics = {"probes": len(probes)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"AgentContract 校验 {len(probes)} 态全部按预期拒绝"
                         f"（AgentContractError，消息达口径）", metrics)


# ---------------------------------------------------------------------------
# SPEC-M7-15 · diff_release 结构化差分（两 bundle dict → diff 逐键比对）
# ---------------------------------------------------------------------------
def exec_diff(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    diff = publish.diff_release(params.get("a") or {}, params.get("b") or {})
    problems: list = []
    fields = expect.get("fields") or {}
    for key, want_value in fields.items():
        got = diff.get(key)
        if got != want_value:
            problems.append(f"diff.{key} = {got!r} != 期望 {want_value!r}")
    metrics = {"diff_keys": sorted(diff), "compared": sorted(fields)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"diff_release 差分 {len(fields)} 键逐字段等于期望"
                         f"（a={diff.get('a')} b={diff.get('b')}）", metrics)


EXECUTORS = {
    "m7.descriptor_validation": exec_descriptor_validation,
    "m7.review_guards": exec_review_guards,
    "m7.contract_validation": exec_contract_validation,
    "m7.diff": exec_diff,
}
