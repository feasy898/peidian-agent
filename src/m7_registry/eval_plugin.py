# -*- coding: utf-8 -*-
"""m7_registry 的 EVAL 执行器插件（tests/test_m7.yaml 数据驱动用例）。

插件契约（tests/EVAL-SCHEMA.md §4）：暴露 ``EXECUTORS: dict[str, callable]``；
执行器签名 ``fn(case: dict, ctx) -> {"passed": bool, "detail": str, "metrics": dict}``。

全部执行器只读 ``case.params`` 声明的数据（资产描述子/目录/报告/门禁期望均为
用例数据），不做针对特定输入的硬编码特判；沙箱统一 ``runtime/m7_eval/<case-id>``
（先清空，独立可复跑）。真实仓库资产（assets/agent_contract_v1.yaml、prompts/、
skills/、tools/、ontology/）按 params 声明的路径装载。
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import yaml

__all__ = ["EXECUTORS"]


def _result(passed: bool, detail: str, metrics: dict | None = None) -> dict:
    return {"passed": bool(passed), "detail": str(detail), "metrics": metrics or {}}


def _sandbox(ctx: Any, case: dict) -> Path:
    root = Path(ctx.root) / "runtime" / "m7_eval" / str(case.get("id") or "case")
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# 装配辅助：注册表 + 契约目录 + 合成 M6 报告
# ---------------------------------------------------------------------------
def _load_contract(ctx: Any, params: dict):
    from m7_registry.agent_contract import AgentContract, catalog_index, load_agent_contract

    catalog_rows = params.get("catalog")
    if catalog_rows:
        contract = AgentContract.from_dict({
            "contract_id": "agent.eval-contract", "version": "9.9.9",
            "title": "EVAL 合成契约",
            "capability_domains": {d: {"name": d, "description": f"{d} 域"}
                                   for d in ("PREDICT", "DISPATCH", "MAINTAIN",
                                             "PLAN", "SELF_HEAL", "TRADE")},
            "constraints": [{"id": "CL-EVAL-1", "text": "EVAL 约束",
                             "source": "eval", "assertion": "eval_assert"}],
            "behavior_catalog": catalog_rows,
        })
    else:
        contract = load_agent_contract(
            Path(ctx.root) / str(params.get("contract_file") or "assets/agent_contract_v1.yaml"))
    return contract, catalog_index(contract)


def _make_store(ctx: Any, params: dict, sandbox: Path, events: list | None = None,
                contract=None):
    from m7_registry.assets import AssetStore
    from m7_registry.review import ReviewPipeline

    store = AssetStore(now_fn=lambda: "2026-09-28T00:00:00Z")
    for item in params.get("assets") or []:
        store.register_asset(str(item["type"]), item["descriptor"])
    if contract is not None and not any(r.type == "AGENT" for r in store.all_assets()):
        store.register_asset("AGENT", contract.to_dict())  # draft 的 agent_ref 兜底
    review = ReviewPipeline(store, sink=(lambda e: events.append(e)) if events is not None else None,
                            now_fn=lambda: "2026-09-28T00:00:00Z")
    return store, review


def _synthetic_report(release_id: str, cases: list, golden_set_version: str = "dev-eval",
                      score_100: float | None = None) -> dict:
    """按 M6 evaluator report 结构合成报告（cases=[{case_id, passed, rubric_total}]）。"""
    rows = []
    failures = []
    for item in cases:
        passed = bool(item.get("passed", True))
        if not passed:
            failures.append(str(item["case_id"]))
        rows.append({
            "case_id": str(item["case_id"]), "task_input": f"（沙箱）{item['case_id']}",
            "trace_id": f"trace-{item['case_id']}", "passed": passed,
            "problems": [] if passed else [f"{item['case_id']} 判据未过"],
            "deterministic": {"all": passed},
            "rubric": [{"anchor": str(item.get("anchor") or "DEFAULT"),
                        "total": float(item.get("rubric_total", 4.8 if passed else 3.0)),
                        "pass_line": 4.0, "passed": passed, "by_dimension": {}}],
            "steps": {"MODEL_CALL": 2, "TOOL_CALL": 3, "STATE_CHANGE": 4, "APPROVAL": 0,
                      "total": 9},
            "outcome": {"status": "COMPLETED" if passed else "FAILED",
                        "completion_level": 5 if passed else 2,
                        "evidence_summary": "（沙箱）"},
        })
    passed_n = len(rows) - len(failures)
    pass_rate = round(passed_n / len(rows), 4) if rows else 0.0
    mean_total = (sum(r["rubric"][0]["total"] for r in rows) / len(rows)) if rows else 0.0
    return {
        "release_id": release_id, "release_model_ref": "mock-eval@offline",
        "golden_dir": "golden/dev", "golden_set_version": golden_set_version,
        "mode": "SIMULATION", "generated_at": "2026-09-28T00:00:00Z",
        "cases": rows, "pass_rate": pass_rate, "failures": failures,
        "totals": {"cases": len(rows), "passed": passed_n,
                   "mean_rubric_total": round(mean_total, 4),
                   "score_100": score_100 if score_100 is not None else round(mean_total * 20, 2)},
        "dimensions": ["factual_correctness", "regulation_citation",
                       "state_change_discipline", "refusal_calibration",
                       "evidence_completeness"],
    }


def _write_report(sandbox: Path, name: str, report: dict) -> Path:
    path = sandbox / name
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _valid_draft(ctx: Any, params: dict, store, contract, scores: dict,
                 ontology_dir: Path, release_id: str) -> dict:
    """按 params.refs 组装六要素齐备的 bundle draft（ontology 取实参目录）。

    refs 三键缺省时从注册表推导（该类型全部已注册资产）。
    """
    from m4_semantic import compute_ontology_version

    def _refs_of(key: str, asset_type: str) -> list:
        if key in params:
            return list(params[key])
        return [f"{r.asset_id}@{r.version}" for r in store.all_assets()
                if r.type == asset_type]

    agent_ref = str(params.get("agent_ref") or "")
    if not agent_ref:
        agent = next((r for r in store.all_assets() if r.type == "AGENT"), None)
        agent_ref = f"{agent.asset_id}@{agent.version}" if agent else ""
    return {
        "release_id": release_id,
        "model_ref": str(params.get("model_ref") or "mock-eval@offline"),
        "prompt_refs": _refs_of("prompt_refs", "PROMPT"),
        "skill_refs": _refs_of("skill_refs", "SKILL"),
        "tool_refs": _refs_of("tool_refs", "TOOL"),
        "ontology_version": compute_ontology_version(ontology_dir),
        "golden_scores": scores,
        "frozen_scenarios": list(params.get("frozen_scenarios") or []),
        "contract_version": str(params.get("contract_version") or "1.1"),
        "agent_ref": agent_ref,
    }


def _register_repo_assets(ctx: Any, store, contract) -> None:
    """注册仓库真实资产（prompts/ skills/ tools/ + AgentContract）。"""
    from m7_registry.assemble import tool_descriptors

    root = Path(ctx.root)
    for rel in ("prompts/daily-inspection.yaml", "prompts/overload-response.yaml"):
        store.register_asset("PROMPT", yaml.safe_load((root / rel).read_text(encoding="utf-8")))
    store.register_asset("SKILL", yaml.safe_load(
        (root / "skills/overload-response/SKILL.yaml").read_text(encoding="utf-8")))
    for descriptor in tool_descriptors(root):
        store.register_asset("TOOL", descriptor)
    if not any(r.type == "AGENT" for r in store.all_assets()):
        store.register_asset("AGENT", contract.to_dict())


def _dir_sha(base: Path) -> dict:
    return {p.relative_to(base).as_posix():
            hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(base.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------------------
# SPEC-M7-01 · 资产四类 + 版本链
# ---------------------------------------------------------------------------
def exec_asset_versions(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    sandbox = _sandbox(ctx, case)
    store, _review = _make_store(ctx, params, sandbox)
    problems: list = []
    types = {r.type for r in store.all_assets()}
    want_types = set(expect.get("types") or [])
    if want_types and types != want_types:
        problems.append(f"注册类型 {sorted(types)} != 期望 {sorted(want_types)}")

    updates = list(params.get("updates") or [])
    for upd in updates:
        store.update_asset(str(upd["asset_id"]), upd["descriptor"])
    for asset_id, want_chain in (expect.get("chains") or {}).items():
        versions = store.list_versions(asset_id)
        if len(versions) != int(want_chain):
            problems.append(f"{asset_id}: 版本链 {len(versions)} != 期望 {want_chain}")
        latest = store.latest(asset_id)
        if latest.chain != len(versions):
            problems.append(f"{asset_id}: 最新 chain {latest.chain} != {len(versions)}")
    # 旧版本只读不覆盖：chain1 的版本串/内容必须保持注册时原样
    if expect.get("v1_readonly"):
        upd0 = params["updates"][0]
        original = next(
            item["descriptor"] for item in params.get("assets") or []
            if str(item["descriptor"].get("asset_id")
                   or item["descriptor"].get("skill_id")
                   or item["descriptor"].get("contract_id")) == str(upd0["asset_id"]))
        first = store.get_asset(str(upd0["asset_id"]), 1)
        if first.version != str(original.get("version")):
            problems.append(f"v1 版本串被改写: {first.version!r}"
                            f" != 注册时 {str(original.get('version'))!r}")
        if first.superseded_by != 2:
            problems.append(f"v1.superseded_by={first.superseded_by} != 2（替代链缺失）")
        from m7_registry.assets import content_hash_of

        if first.content_hash != content_hash_of(original):
            problems.append("v1 内容 hash 被改写（旧版本只读失守）")
    # 重复注册拒绝
    if expect.get("reregister_rejected"):
        item = (params.get("assets") or [{}])[0]
        try:
            store.register_asset(str(item["type"]), item["descriptor"])
            problems.append("同 asset_id 重复注册未被拒绝")
        except Exception:  # noqa: BLE001 - 拒绝即通过
            pass
    # 内容未变的更新拒绝（版本号不得空转）：重放"当前最新版本"的原描述子
    if expect.get("unchanged_update_rejected"):
        replay = None
        replay_id = None
        if updates:  # 以最后一次更新的产物为当前版本
            replay = dict(updates[-1]["descriptor"])
            replay_id = str(updates[-1]["asset_id"])
        else:
            item = (params.get("assets") or [{}])[0]
            replay = dict(item["descriptor"])
            replay_id = str(item["descriptor"].get("asset_id")
                            or item["descriptor"].get("skill_id")
                            or item["descriptor"].get("contract_id"))
        replay.pop("chain", None)
        try:
            store.update_asset(replay_id, replay)
            problems.append("内容未变化的更新未被拒绝（版本号空转）")
        except Exception:  # noqa: BLE001
            pass
    # 显式 chain 重放拒绝（旧版本只读不覆盖）
    if expect.get("explicit_chain_rejected"):
        upd = dict(params["updates"][0]["descriptor"])
        upd["chain"] = 1
        try:
            store.update_asset(str(params["updates"][0]["asset_id"]), upd)
            problems.append("带显式 chain 的旧版本改写未被拒绝")
        except Exception:  # noqa: BLE001
            pass
    metrics = {"assets": len(store.all_assets()), "types": sorted(types),
               "updates": len(updates)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"{len(store.all_assets())} 项资产（{sorted(types)}）注册；"
                         f"{len(updates)} 次变更全部产生新版本，旧版本只读不覆盖", metrics)


# ---------------------------------------------------------------------------
# SPEC-M7-02 · 依赖闭包（打包级拒绝/通过）
# ---------------------------------------------------------------------------
def exec_closure(case: dict, ctx: Any) -> dict:
    from m7_registry.dependencies import resolve_closure
    from m7_registry.release import ReleaseBuildError, build_release, import_golden_scores

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    sandbox = _sandbox(ctx, case)
    contract, catalog = _load_contract(ctx, params)
    store, _review = _make_store(ctx, params, sandbox, contract=contract)
    if params.get("register_repo_assets"):
        _register_repo_assets(ctx, store, contract)

    problems: list = []
    closure = resolve_closure(store, params.get("skill_refs") or [],
                              params.get("tool_refs") or [],
                              params.get("prompt_refs") or [])
    ok = closure.ok
    if bool(expect.get("ok", True)) != ok:
        problems.append(f"闭包 ok={ok} != 期望 {expect.get('ok')}")
    joined = "；".join(str(e) for e in closure.errors)
    for token in expect.get("error_contains") or []:
        if token not in joined:
            problems.append(f"闭包错误未含期望口径 {token!r}: {joined[:200]}")

    # 打包级验证：与 build_release 同一入口（失败必须以 ReleaseBuildError 拒绝打包）
    if params.get("assert_build", True):
        ontology_dir = Path(ctx.root) / str(params.get("ontology_dir") or "ontology")
        rows = [{"case_id": cid, "passed": True} for cid in catalog]
        report = _synthetic_report("rel-eval-closure", rows)
        report_path = _write_report(sandbox, "report.json", report)
        scores = import_golden_scores(report_path, catalog, release_id="rel-eval-closure")
        draft = _valid_draft(ctx, params, store, contract, scores,
                             ontology_dir, "rel-eval-closure")
        try:
            build_release(draft, store=store, contract=contract,
                          ontology_dir=ontology_dir, repo_root=Path(ctx.root))
            if not ok:
                problems.append("闭包失败但 build_release 未拒绝打包（SPEC-M7-02 失守）")
        except ReleaseBuildError as exc:
            if ok:
                problems.append(f"闭包成功但打包被拒: {exc}")
            else:
                detail = str(exc)
                for token in expect.get("error_contains") or []:
                    if token not in detail:
                        problems.append(f"打包拒绝消息未含 {token!r}: {detail[:200]}")
    metrics = {"nodes": len(closure.refs), "edges": len(closure.edges),
               "errors": len(closure.errors), "ok": ok}
    if problems:
        return _result(False, "；".join(problems), metrics)
    if ok:
        return _result(True, f"闭包解析成功（{len(closure.refs)} 节点/"
                             f"{len(closure.edges)} 边，版本全显式），打包通过", metrics)
    return _result(True, f"闭包失败按预期拒绝打包: {joined[:160]}", metrics)


# ---------------------------------------------------------------------------
# SPEC-M7-03 · 变更评审（含拒绝分支与 publish 入口无旁路）
# ---------------------------------------------------------------------------
def exec_review_flow(case: dict, ctx: Any) -> dict:
    from m7_registry.release import import_golden_scores
    from m7_registry.review import (
        GoldenRegressionError,
        ReviewBypassError,
        publish_asset,
    )

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    sandbox = _sandbox(ctx, case)
    contract, catalog = _load_contract(ctx, params)
    events: list = []
    store, review = _make_store(ctx, params, sandbox, events=events, contract=contract)
    if params.get("register_repo_assets"):
        _register_repo_assets(ctx, store, contract)
    problems: list = []

    # 黄金证据：真实 M6 评估（params.run_eval）或合成报告（params.candidate/baseline）
    run_cfg = params.get("run_eval")
    if run_cfg:
        from m6_flywheel.evaluator import GoldenEvaluator

        evaluator = GoldenEvaluator(golden_dir=str(Path(ctx.root) / str(run_cfg.get("golden_dir", "golden/dev"))),
                                    runs_dir=sandbox / "runs", mode="SIMULATION",
                                    now_fn=lambda: "2026-09-28T00:00:00Z")
        report = evaluator.run_golden(str(run_cfg.get("release") or "mock-rel-0001"))
        report_path = sorted((sandbox / "runs" / "eval").glob("*/report.json"))[-1]
    else:
        release_id = str(params.get("candidate", {}).get("release_id") or "rel-eval-review")
        report = _synthetic_report(release_id, params["candidate"]["cases"],
                                   score_100=params["candidate"].get("score_100"))
        report_path = _write_report(sandbox, "candidate.json", report)
    baseline_cfg = params.get("baseline")
    baseline_kwargs = {}
    if baseline_cfg and not run_cfg:
        baseline_kwargs["baseline_run_ref"] = _write_report(
            sandbox, "baseline.json",
            _synthetic_report(str(baseline_cfg.get("release_id") or "rel-baseline"),
                              baseline_cfg["cases"],
                              score_100=baseline_cfg.get("score_100")))
    elif baseline_cfg and run_cfg:
        baseline_kwargs["baseline_score"] = float(baseline_cfg["score_100"])

    asset_id = str(params.get("asset_id") or "")
    record = None
    transitions: list = []
    rejected = False
    if asset_id:
        proposal = review.submit_proposal(asset_id,
                                          motivation=str(params.get("motivation") or "变更动机"),
                                          impact=str(params.get("impact") or "影响面"),
                                          badcases=list(params.get("badcases") or ["none"]))
        try:
            review.start_evaluation(proposal.proposal_id,
                                    candidate_run_ref=str(report_path), **baseline_kwargs)
        except GoldenRegressionError:
            rejected = True
        if expect.get("final_state") == "REJECTED":
            if not rejected:
                problems.append("期望 REJECTED（跑分低于现行）但评审被通过")
        elif rejected:
            problems.append("跑分达标但评审被拒")
        elif expect.get("final_state") == "PUBLISHED":
            status = publish_asset(asset_id, proposal, store=store, pipeline=review)
            if status != "PUBLISHED":
                problems.append(f"publish_asset 返回 {status} != PUBLISHED")
            if store.status_of(asset_id) != "PUBLISHED":
                problems.append("资产状态未翻 PUBLISHED")
        record = review.get(proposal.proposal_id)
        if record.state != str(expect.get("final_state")):
            problems.append(f"评审终态 {record.state} != 期望 {expect['final_state']}")
        transitions = [(h["from"], h["to"]) for h in record.history]
        want_transitions = [(tuple(t) if isinstance(t, list) else (None, t))
                            for t in expect.get("transitions") or []]
        if transitions != want_transitions:
            problems.append(f"迁移链 {transitions} != 期望 {want_transitions}")

    # 跳过评审直接发布（publish 入口拒绝 + 审计；代码级断言无旁路）
    bypass = params.get("bypass")
    if bypass:
        audits_before = len(events)
        try:
            if bypass.get("kind") == "fabricated":
                publish_asset(str(bypass["asset_id"]),
                              {"proposal_id": str(bypass.get("proposal_id") or "FORGED"),
                               "state": "APPROVED"},
                              store=store, pipeline=review)
            else:  # 未过评审的在途提案直接发布
                p2 = review.submit_proposal(str(bypass["asset_id"]),
                                            motivation="b", impact="b", badcases=["none"])
                publish_asset(str(bypass["asset_id"]), p2, store=store, pipeline=review)
            problems.append("跳过评审直接发布未被拒绝（SPEC-M7-03 无旁路失守）")
        except ReviewBypassError:
            new_events = events[audits_before:]
            rejected_audits = [e for e in new_events
                               if (e.get("payload") or {}).get("rejected")]
            if not rejected_audits:
                problems.append("publish 拒绝后未落审计事件（rejected 标记）")
        if store.status_of(str(bypass["asset_id"])) == "PUBLISHED":
            problems.append(f"被拒资产 {bypass['asset_id']} 状态被翻成 PUBLISHED（旁路！）")
    metrics = {"state": record.state if record else None,
               "transitions": transitions, "events": len(events),
               "score": report["totals"]["score_100"]}
    if problems:
        return _result(False, "；".join(problems), metrics)
    chain = "→".join(f"{(f or '∅')}→{t}" for f, t in transitions)
    return _result(True, f"评审迁移链 {chain}（终态 {record.state if record else '—'}）；"
                         f"黄金成绩 {report['totals']['score_100']}"
                         f"（candidate vs baseline "
                         f"{'低于现行被拒' if rejected else '不低于现行通过'}）", metrics)


# ---------------------------------------------------------------------------
# SPEC-M7-04 · 六要素 + M6 签名
# ---------------------------------------------------------------------------
def exec_six_elements(case: dict, ctx: Any) -> dict:
    from m7_registry.release import (
        ReleaseBuildError,
        build_release,
        import_golden_scores,
    )

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    sandbox = _sandbox(ctx, case)
    contract, catalog = _load_contract(ctx, params)
    store, _review = _make_store(ctx, params, sandbox, contract=contract)
    if params.get("register_repo_assets"):
        _register_repo_assets(ctx, store, contract)
    ontology_dir = Path(ctx.root) / str(params.get("ontology_dir") or "ontology")
    report = _synthetic_report("rel-eval-six", [{"case_id": cid, "passed": True}
                                                for cid in catalog])
    report_path = _write_report(sandbox, "report.json", report)
    scores = import_golden_scores(report_path, catalog, release_id="rel-eval-six")
    problems: list = []

    drop = list(params.get("drop") or expect.get("drop") or [])
    for element in drop:
        draft = _valid_draft(ctx, params, store, contract, scores, ontology_dir,
                             "rel-eval-six")
        draft.pop(element, None)
        try:
            build_release(draft, store=store, contract=contract,
                          ontology_dir=ontology_dir, repo_root=Path(ctx.root))
            problems.append(f"缺 {element} 仍被打包（SPEC-M7-04 缺一拒绝失守）")
        except ReleaseBuildError as exc:
            if "六要素" not in str(exc) and element not in str(exc):
                problems.append(f"缺 {element} 的拒绝消息不达口径: {exc}")
    if not drop:  # 全六要素齐备 → 打包通过
        draft = _valid_draft(ctx, params, store, contract, scores, ontology_dir,
                             "rel-eval-six")
        try:
            build_release(draft, store=store, contract=contract,
                          ontology_dir=ontology_dir, repo_root=Path(ctx.root))
        except ReleaseBuildError as exc:
            problems.append(f"六要素齐备仍被拒: {exc}")

    # 手工填报 golden_scores（无 M6 签名 / 伪造签名 / 篡改）
    from m7_registry.release import GoldenSignatureError, verify_golden_scores

    for probe in params.get("hand_filled") or []:
        variant = copy.deepcopy(scores)
        mode = str(probe.get("mode") or "no_signature")
        if mode == "no_signature":
            variant["by_domain"].pop("signature", None)
        elif mode == "wrong_producer":
            variant["by_domain"]["signature"]["producer"] = "HUMAN"
        elif mode == "tampered_digest":
            variant["by_domain"]["signature"]["digest"] = "0" * 64
        elif mode == "tampered_pass_rate":
            variant["pass_rate"] = 0.99
        elif mode == "no_attestation":
            variant["by_domain"]["signature"].pop("attestation", None)
        elif mode == "cross_release":
            variant["by_domain"]["signature"]["release_id"] = "rel-other"
        try:
            verify_golden_scores(variant, release_id="rel-eval-six", catalog=catalog,
                                 repo_root=Path(ctx.root))
            problems.append(f"手工填报变体 {mode} 未被签名校验拒绝")
        except GoldenSignatureError as exc:
            for token in probe.get("error_contains") or []:
                if token not in str(exc):
                    problems.append(f"变体 {mode} 拒绝消息未含 {token!r}: {exc}")
    # 合法产出口（import → verify）必须通过
    try:
        verify_golden_scores(scores, release_id="rel-eval-six", catalog=catalog,
                             repo_root=Path(ctx.root))
    except GoldenSignatureError as exc:
        problems.append(f"合法签名被误拒: {exc}")
    metrics = {"drop": drop, "hand_filled": [p.get("mode") for p in params.get("hand_filled") or []]}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"六要素缺一拒绝（{len(drop)} 项逐项实测）；手工填报"
                         f"（{len(params.get('hand_filled') or [])} 变体）全部被签名校验拒绝；"
                         f"合法 M6 签名通过", metrics)


# ---------------------------------------------------------------------------
# SPEC-M7-05 · 发布不可变 + Release 状态机
# ---------------------------------------------------------------------------
def exec_immutable(case: dict, ctx: Any) -> dict:
    from m7_registry.publish import (
        ImmutableReleaseError,
        ReleaseStateMachine,
        publish_release,
        resolve_release,
        supersede_release,
        write_release_file,
    )
    from m7_registry.release import gate_release, import_golden_scores

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    sandbox = _sandbox(ctx, case)
    contract, catalog = _load_contract(ctx, params)
    store, _review = _make_store(ctx, params, sandbox, contract=contract)
    _register_repo_assets(ctx, store, contract)
    ontology_dir = Path(ctx.root) / "ontology"
    release_id = str(params.get("release_id") or "rel-eval-imm")
    rows = [{"case_id": cid, "passed": True} for cid in catalog]
    report = _synthetic_report(release_id, rows)
    report_path = _write_report(sandbox, "report.json", report)
    scores = import_golden_scores(report_path, catalog, release_id=release_id)
    events: list = []
    machine = ReleaseStateMachine(sandbox / "releases.jsonl",
                                  releases_dir=sandbox / "releases",
                                  sink=lambda e: events.append(e),
                                  now_fn=lambda: "2026-09-28T00:00:00Z")
    built = _build_for_eval(ctx, params, store, contract, scores, ontology_dir, release_id)
    gate = gate_release(built, contract=contract, ontology_dir=ontology_dir)
    if not gate.passed:
        return _result(False, "沙箱前置门禁未过", {"gate": gate.to_dict()})
    releases_dir = sandbox / "releases"
    publish_release(built, gate, releases_dir=releases_dir, machine=machine,
                    store=store, evidence_report=report_path,
                    evidence_cases=_write_report(sandbox, "cases.json", {"x": 1}))
    base = releases_dir / release_id
    before = _dir_sha(base)
    problems: list = []

    # 二次发布拒绝
    try:
        publish_release(built, gate, releases_dir=releases_dir, machine=machine,
                        store=store, evidence_report=report_path,
                        evidence_cases=_write_report(sandbox, "cases.json", {"x": 1}))
        problems.append("二次发布未被拒绝（SPEC-M7-05 只写一次失守）")
    except ImmutableReleaseError:
        pass
    # 向已发布目录补写文件拒绝（文件级 immutable）
    for name in params.get("late_writes") or ["extra.txt", "release.yaml"]:
        try:
            write_release_file(releases_dir, release_id, str(name), "tamper")
            problems.append(f"补写 {name} 未被拒绝")
        except ImmutableReleaseError:
            pass
    if _dir_sha(base) != before:
        problems.append("发布目录内容在拒绝尝试后发生变化")

    # 状态机：PUBLISHED 后仅可 SUPERSEDED
    for probe in params.get("illegal_transitions") or []:
        try:
            machine.transition(release_id, str(probe["to"]))
            problems.append(f"非法迁移 PUBLISHED→{probe['to']} 未被拒绝")
        except Exception:  # noqa: BLE001 - IllegalReleaseTransitionError
            pass
    if params.get("supersede_allowed"):
        supersede_release(release_id, by_release_id="rel-eval-next", machine=machine)
        if machine.state_of(release_id) != "SUPERSEDED":
            problems.append("PUBLISHED→SUPERSEDED 未生效")
        if _dir_sha(base) != before:
            problems.append("SUPERSEDED 改动了发布目录内容（必须只动台账）")
    resolved = resolve_release(release_id, releases_dir=releases_dir)
    if resolved["manifest"].get("status") != "PUBLISHED":
        problems.append("manifest.status != PUBLISHED")
    metrics = {"files": sorted(before), "state": machine.state_of(release_id),
               "events": len(events)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"releases/{release_id}/ 只写一次：二次发布/补写"
                         f"（{len(params.get('late_writes') or [])} 项）全拒且内容零变化；"
                         f"PUBLISHED→SUPERSEDED 合法、其余迁移拒绝；manifest 复核通过", metrics)


def _build_for_eval(ctx: Any, params: dict, store, contract, scores,
                    ontology_dir: Path, release_id: str) -> dict:
    from m7_registry.release import build_release

    draft = _valid_draft(ctx, params, store, contract, scores, ontology_dir, release_id)
    return build_release(draft, store=store, contract=contract,
                         ontology_dir=ontology_dir, repo_root=Path(ctx.root))


# ---------------------------------------------------------------------------
# SPEC-M7-06 · 行为目录门禁（缺项列出）
# ---------------------------------------------------------------------------
def exec_gate(case: dict, ctx: Any) -> dict:
    from m7_registry.release import gate_release, import_golden_scores

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    sandbox = _sandbox(ctx, case)
    contract, catalog = _load_contract(ctx, params)
    store, _review = _make_store(ctx, params, sandbox, contract=contract)
    _register_repo_assets(ctx, store, contract)
    ontology_dir = Path(ctx.root) / "ontology"
    release_id = str(params.get("release_id") or "rel-eval-gate")
    rows = []
    for item in params.get("cases") or []:
        row = {"case_id": str(item["case_id"]), "passed": bool(item.get("passed", True))}
        if "rubric_total" in item:
            row["rubric_total"] = float(item["rubric_total"])
        rows.append(row)
    report = _synthetic_report(release_id, rows)
    report_path = _write_report(sandbox, "report.json", report)
    scores = import_golden_scores(report_path, catalog, release_id=release_id)
    built = _build_for_eval(ctx, params, store, contract, scores, ontology_dir, release_id)
    gate = gate_release(built, contract=contract, ontology_dir=ontology_dir)
    problems: list = []
    if gate.passed != bool(expect.get("passed", False)):
        problems.append(f"门禁 passed={gate.passed} != 期望 {expect.get('passed')}")
    failed_names = [c["name"] for c in gate.checks if not c["passed"]]
    for name in expect.get("failed_checks") or []:
        if name not in failed_names:
            problems.append(f"期望失败项 {name} 未失败（实际失败 {failed_names}）")
    for name in expect.get("passed_checks") or []:
        if name in failed_names:
            problems.append(f"期望通过项 {name} 失败")
    missing_joined = "；".join(gate.missing)
    for token in expect.get("missing_contains") or []:
        if token not in missing_joined:
            problems.append(f"缺项清单未含 {token!r}: {missing_joined[:200]}")
    metrics = {"passed": gate.passed, "failed_checks": failed_names,
               "missing": gate.missing,
               "red_line_records": built["bundle"].golden_scores.by_domain
                   .get("red_line", {}).get("records")}
    if problems:
        return _result(False, "；".join(problems), metrics)
    verdict = "GATED 失败并正确列缺项" if not gate.passed else "GATED 通过"
    return _result(True, f"门禁 {verdict}: 失败项 {failed_names}；缺项 {gate.missing}", metrics)


# ---------------------------------------------------------------------------
# SPEC-M7-07 · 本体版本一致性
# ---------------------------------------------------------------------------
def exec_ontology_drift(case: dict, ctx: Any) -> dict:
    from m4_semantic import compute_ontology_version
    from m7_registry.release import (
        OntologyDriftError,
        ReleaseBuildError,
        build_release,
        import_golden_scores,
    )

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    sandbox = _sandbox(ctx, case)
    contract, catalog = _load_contract(ctx, params)
    store, _review = _make_store(ctx, params, sandbox, contract=contract)
    _register_repo_assets(ctx, store, contract)
    ontology_copy = sandbox / "ontology"
    shutil.copytree(Path(ctx.root) / "ontology", ontology_copy)
    release_id = "rel-eval-drift"
    report = _synthetic_report(release_id, [{"case_id": cid, "passed": True}
                                            for cid in catalog])
    report_path = _write_report(sandbox, "report.json", report)
    scores = import_golden_scores(report_path, catalog, release_id=release_id)
    problems: list = []

    def build_with(hash_value: str) -> None:
        draft = _valid_draft(ctx, params, store, contract, scores, ontology_copy, release_id)
        draft["ontology_version"] = hash_value
        build_release(draft, store=store, contract=contract,
                      ontology_dir=ontology_copy, repo_root=Path(ctx.root))

    # 基线：当前目录 hash 打包通过
    baseline_hash = compute_ontology_version(ontology_copy)
    build_with(baseline_hash)
    # 本体改动：目录 hash 漂移
    target = ontology_copy / str(params.get("mutate_file") or "rules.yaml")
    text = target.read_text(encoding="utf-8")
    target.write_text(text + "\n# drift probe\n", encoding="utf-8")
    drifted_hash = compute_ontology_version(ontology_copy)
    if drifted_hash == baseline_hash:
        problems.append("本体文件改动未翻转目录 hash（探针无效）")
    # 旧 release（携改动前 hash）再打包 → 一致性拒绝（"本体已改、release 未更新"）
    try:
        build_with(baseline_hash)
        problems.append("本体已改、release 未更新：一致性校验未拒绝（SPEC-M7-07 失守）")
    except OntologyDriftError as exc:
        for token in expect.get("error_contains") or []:
            if token not in str(exc):
                problems.append(f"漂移拒绝消息未含 {token!r}: {exc}")
    except ReleaseBuildError as exc:
        problems.append(f"漂移场景抛了非 OntologyDriftError 的打包错误: {exc}")
    # 更新后的 release（携新 hash）应可打包（一致性校验不阻断正常更新）
    try:
        build_with(drifted_hash)
    except ReleaseBuildError as exc:
        problems.append(f"携新 ontology_version 的正常打包被拒: {exc}")
    metrics = {"mutate_file": str(params.get("mutate_file") or "rules.yaml"),
               "baseline_hash": baseline_hash[:12], "drifted_hash": drifted_hash[:12]}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, "本体目录改动后，携旧 ontology_version 的打包被一致性拒绝；"
                         f"携新 hash 正常通过（mutate {metrics['mutate_file']}，"
                         f"hash {metrics['baseline_hash']}…→{metrics['drifted_hash']}…）", metrics)


# ---------------------------------------------------------------------------
# 表驱动状态机（DoD：评审流/Release 状态机与 fixture diff 为空）
# ---------------------------------------------------------------------------
def exec_tables(case: dict, ctx: Any) -> dict:
    from m7_registry.publish import IllegalReleaseTransitionError, ReleaseStateMachine
    from m7_registry.release import RELEASE_TRANSITIONS
    from m7_registry.review import REVIEW_TRANSITIONS

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    fixture = ctx.load_yaml(str(params.get("table") or "tests/fixtures/m7_state_machines.yaml"))
    machines = (fixture or {}).get("machines") or {}
    problems: list = []
    impl = {"review": {k: list(v) for k, v in REVIEW_TRANSITIONS.items()},
            "release": {k: list(v) for k, v in RELEASE_TRANSITIONS.items()}}
    for name in ("review", "release"):
        if impl[name] != machines.get(name):
            only_impl = {k: v for k, v in impl[name].items()
                         if machines.get(name, {}).get(k) != v}
            problems.append(f"{name} 状态机与 fixture diff 非空: {only_impl}")
    # 行为级抽查：非法迁移（fixture 表允许集之外的 to）必须被实现拒绝
    machine = ReleaseStateMachine(None, now_fn=lambda: "2026-09-28T00:00:00Z")
    for probe in expect.get("release_rejected") or []:
        try:
            machine._states["rel-x"] = probe["from"]
            machine.transition("rel-x", str(probe["to"]))
            problems.append(f"release {probe['from']}→{probe['to']} 未被拒绝")
        except IllegalReleaseTransitionError:
            pass
    metrics = {"review_states": len(impl["review"]), "release_states": len(impl["release"]),
               "probes": len(expect.get("release_rejected") or [])}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, "评审流（6 态）与 Release（4 态）状态机与冻结 fixture diff 为空；"
                         f"{metrics['probes']} 项非法迁移行为级拒绝", metrics)


# ---------------------------------------------------------------------------
# DoD · 端到端发布流（真实 M6 实测 → 门禁 → 发布 → 复核）
# ---------------------------------------------------------------------------
def exec_release_flow(case: dict, ctx: Any) -> dict:
    from m6_flywheel.evaluator import GoldenEvaluator
    from m7_registry.assets import AssetStore
    from m7_registry.publish import (
        ImmutableReleaseError,
        ReleaseStateMachine,
        publish_release,
        resolve_release,
        write_release_file,
    )
    from m7_registry.release import gate_release, import_golden_scores, verify_golden_scores
    from m7_registry.review import ReviewPipeline, publish_asset

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    sandbox = _sandbox(ctx, case)
    contract, catalog = _load_contract(ctx, params)
    events: list = []
    store = AssetStore(now_fn=lambda: "2026-09-28T00:00:00Z")
    _register_repo_assets(ctx, store, contract)
    review = ReviewPipeline(store, sandbox / "reviews.jsonl",
                            sink=lambda e: events.append(e),
                            now_fn=lambda: "2026-09-28T00:00:00Z")
    release_id = str(params.get("release_id") or "rel-eval-e2e")
    ontology_dir = Path(ctx.root) / "ontology"

    evaluator = GoldenEvaluator(golden_dir=str(Path(ctx.root) /
                                               str(params.get("golden_dir", "golden/dev"))),
                                runs_dir=sandbox / "runs", mode="SIMULATION",
                                now_fn=lambda: "2026-09-28T00:00:00Z")
    report = evaluator.run_golden(str(params.get("eval_release") or release_id))
    report_path = sorted((sandbox / "runs" / "eval").glob("*/report.json"))[-1]
    problems: list = []
    if abs(report["pass_rate"] - float(expect.get("pass_rate", 1.0))) > 1e-9:
        problems.append(f"M6 实测 pass_rate={report['pass_rate']} != 期望")
    scores = import_golden_scores(report_path, catalog, release_id=str(report["release_id"]))
    if str(scores["golden_set_version"]) != str(report["golden_set_version"]):
        problems.append("签名成绩的 golden_set_version 与实测报告不符")

    # 资产评审+发布（全部 20 项走门禁）
    for record in store.all_assets():
        proposal = review.submit_proposal(
            record.asset_id, motivation="EVAL 端到端", impact="沙箱", badcases=["none"])
        review.start_evaluation(proposal.proposal_id, candidate_run_ref=str(report_path))
        publish_asset(record.asset_id, proposal, store=store, pipeline=review)
    unpublished = [r.asset_id for r in store.all_assets()
                   if store.status_of(r.asset_id) != "PUBLISHED"]
    if unpublished:
        problems.append(f"存在未过评审发布的资产: {unpublished}")

    release_id_actual = str(report["release_id"])  # 实测归档绑定的 release id
    built = _build_for_eval(ctx, {**params, "release_id": release_id_actual},
                            store, contract, scores, ontology_dir, release_id_actual)
    gate = gate_release(built, contract=contract, ontology_dir=ontology_dir)
    if gate.passed != bool(expect.get("gate_passed", True)):
        problems.append(f"门禁 {gate.passed} != 期望；缺项 {gate.missing}")
    for name in expect.get("gate_checks_passed") or []:
        check = next((c for c in gate.checks if c["name"] == name), None)
        if check is None or not check["passed"]:
            problems.append(f"门禁项 {name} 未通过")

    releases_dir = sandbox / "releases"
    machine = ReleaseStateMachine(sandbox / "releases.jsonl",
                                  releases_dir=releases_dir,
                                  sink=lambda e: events.append(e),
                                  now_fn=lambda: "2026-09-28T00:00:00Z")
    publish_release(built, gate, releases_dir=releases_dir, machine=machine,
                    store=store, evidence_report=report_path,
                    evidence_cases=Path(ctx.root) / str(
                        params.get("cases_manifest")
                        or "tests/fixtures/mock_releases/mock-rel-0001.yaml"))
    resolved = resolve_release(release_id_actual, releases_dir=releases_dir)
    want_files = set(expect.get("files") or [])
    if want_files and set(resolved["manifest"]["files"]) != want_files:
        problems.append(f"发布物文件集 {sorted(resolved['manifest']['files'])}"
                        f" != 期望 {sorted(want_files)}")
    verify_golden_scores(resolved["bundle"].to_dict()["golden_scores"],
                         release_id=release_id_actual, catalog=catalog,
                         release_dir=resolved["path"])
    # 篡改检测：改动发布物后 resolve 必须拒绝
    target = resolved["path"] / "release.yaml"
    original = target.read_text(encoding="utf-8")
    target.write_text(original.replace("pass_rate: 1.0", "pass_rate: 0.9", 1), encoding="utf-8")
    try:
        resolve_release(release_id_actual, releases_dir=releases_dir)
        problems.append("发布物被篡改后 resolve 未拒绝（hash 复核失守）")
    except ImmutableReleaseError:
        pass
    target.write_text(original, encoding="utf-8")
    try:
        write_release_file(releases_dir, release_id_actual, "x.txt", "x")
        problems.append("发布后补写未被拒绝")
    except ImmutableReleaseError:
        pass
    # 已发布 release 可按发布物重跑黄金集（resolve_release 新首位候选）
    if expect.get("reeval_from_published"):
        re_eval = GoldenEvaluator(golden_dir=str(Path(ctx.root) /
                                                 str(params.get("golden_dir", "golden/dev"))),
                                  runs_dir=sandbox / "runs2", mode="SIMULATION",
                                  releases_dir=releases_dir,
                                  now_fn=lambda: "2026-09-28T00:00:00Z")
        re_report = re_eval.run_golden(release_id_actual)
        if abs(re_report["pass_rate"] - float(expect.get("pass_rate", 1.0))) > 1e-9:
            problems.append(f"按发布物重跑 pass_rate={re_report['pass_rate']} != 期望")
    metrics = {"release_id": release_id_actual, "gate": gate.passed,
               "files": sorted(resolved["manifest"]["files"]),
               "assets": len(store.all_assets()), "events": len(events),
               "score_100": report["totals"]["score_100"]}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"端到端：M6 实测 {report['totals']['cases']} 案例全过"
                         f"（score_100={report['totals']['score_100']}）→ 签名导入 → "
                         f"{len(store.all_assets())} 项资产评审发布 → 六要素打包 → 门禁"
                         f" {len(gate.checks)} 项全过 → 只写一次发布 → manifest/签名/重跑"
                         f"复核通过", metrics)


EXECUTORS = {
    "m7.asset_versions": exec_asset_versions,
    "m7.closure": exec_closure,
    "m7.review_flow": exec_review_flow,
    "m7.six_elements": exec_six_elements,
    "m7.immutable": exec_immutable,
    "m7.gate": exec_gate,
    "m7.ontology_drift": exec_ontology_drift,
    "m7.tables": exec_tables,
    "m7.release_flow": exec_release_flow,
}
