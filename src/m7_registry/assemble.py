# -*- coding: utf-8 -*-
"""m7_registry.assemble · Release 组装 CLI（本阶段收尾：组装并发布 rel-0001）。

流程（全部数据驱动，零 release 特判；``--release-id`` 可指向任意同构 release）::

    1. 注册四类资产（PROMPT×2 / SKILL×1 / TOOL×16 / AGENT×1）：
       - PROMPT/AGENT：prompts/*.yaml 与 assets/agent_contract_v1.yaml 落盘文件；
       - TOOL：ontology/actions.yaml × tools/<id>.py 适配器声明机械装配；
    2. M6 实测：``GoldenEvaluator.run_golden(release_id)``（SIMULATION 离线，
       12 条黄金种子；发布前经 tests/fixtures/mock_releases/<id>.yaml 解析）；
    3. ``import_golden_scores``（M6 签名，禁手工填报）；
    4. 逐资产评审流（proposal→EVALUATING→APPROVED→publish_asset；基线=无现行
       release 时 0 分——首个 release 无可回归基线）；
    5. ``build_release``（六要素+闭包+本体 hash 一致性）→ ``gate_release``
       （12 条目录全过+红线 100%）→ ``publish_release``（只写一次）；
    6. 复核：resolve_release manifest 校验 + M6 evaluator 按发布物重跑确认。

已发布（releases/<id>/ 存在）时进入只读复核模式：manifest 完整性 + 签名 + 黄金
重跑，不产生任何写入（SPEC-M7-05 immutable）。

用法（仓库根）::

    PYTHONPATH=src python -m m7_registry.assemble --release-id rel-0001
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

import yaml

from contracts import CONTRACT_VERSION

from .agent_contract import AgentContract, catalog_index, load_agent_contract
from .assets import AssetStore
from .publish import (
    ImmutableReleaseError,
    ReleaseStateMachine,
    publish_release,
    resolve_release,
)
from .release import GateResult, build_release, gate_release, import_golden_scores
from .review import ReviewPipeline, publish_asset

__all__ = ["repo_root", "tool_descriptors", "assemble", "main"]

AGENT_CONTRACT_PATH = "assets/agent_contract_v1.yaml"
PROMPT_FILES = ("prompts/daily-inspection.yaml", "prompts/overload-response.yaml")
SKILL_FILES = ("skills/overload-response/SKILL.yaml",)
MOCK_RELEASE_DIR = "tests/fixtures/mock_releases"
REGISTRY_DIR = "runtime/m7_registry"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def tool_descriptors(root: Path) -> list:
    """从 ontology/actions.yaml × tools/<id>.py 适配器声明机械装配 ToolAsset。"""
    actions = yaml.safe_load((root / "ontology" / "actions.yaml")
                             .read_text(encoding="utf-8"))["actions"]
    descriptors: list = []
    for action in actions:
        action_id = str(action["id"])
        module = importlib.import_module("tools." + action_id.replace(".", "__"))
        capability = f"{action_id}@{module.VERSION}"
        descriptors.append({
            "asset_id": f"tools/{action_id}",
            "version": str(module.VERSION),
            "capability": capability,
            "params_schema": module.PARAMS_SCHEMA,
            "risk": {
                "level": str(action["risk_level"]),
                "reversible": bool(action.get("reversible")),
                "reversible_note": str(action.get("reversible_note") or ""),
                "default_policy": str(action.get("default_policy")),
                "policy_locked": bool(action.get("policy_locked")),
            },
            "idempotency_policy": str(module.IDEMPOTENCY_KEY_POLICY),
            "write_class": bool(module.WRITE_CLASS),
            "disclosed_roles": list(module.DISCLOSED_ROLES),
            "dependencies": [],
        })
    return descriptors


def assemble(release_id: str, *, root: Path | None = None,
             model_ref: str = "mock-scripted@offline-v1") -> dict:
    """组装+门禁+发布（或已发布时只读复核）。返回执行摘要 dict。"""
    root = Path(root) if root is not None else repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    releases_dir = root / "releases"
    reg_dir = root / REGISTRY_DIR
    reg_dir.mkdir(parents=True, exist_ok=True)
    sink_events: list = []

    def sink(event: dict) -> None:
        sink_events.append(event)

    contract: AgentContract = load_agent_contract(root / AGENT_CONTRACT_PATH)
    store = AssetStore(reg_dir / "assets.jsonl")
    review = ReviewPipeline(store, reg_dir / "reviews.jsonl", sink=sink)
    machine = ReleaseStateMachine(reg_dir / "releases.jsonl",
                                  releases_dir=releases_dir, sink=sink)
    catalog = catalog_index(contract)

    if (releases_dir / release_id).exists():
        return _verify_published(release_id, root=root, contract=contract,
                                 catalog=catalog, events=sink_events)

    # ---------------------------------------------------------------- 1 资产
    registered = []
    for rel in PROMPT_FILES:
        descriptor = yaml.safe_load((root / rel).read_text(encoding="utf-8"))
        registered.append(store.register_asset("PROMPT", descriptor))
    for rel in SKILL_FILES:
        descriptor = yaml.safe_load((root / rel).read_text(encoding="utf-8"))
        registered.append(store.register_asset("SKILL", descriptor))
    for descriptor in tool_descriptors(root):
        registered.append(store.register_asset("TOOL", descriptor))
    agent_contract_descriptor = contract.to_dict()
    registered.append(store.register_asset("AGENT", agent_contract_descriptor))

    # ---------------------------------------------------------------- 2 M6 实测
    from m6_flywheel.evaluator import GoldenEvaluator

    evaluator = GoldenEvaluator(golden_dir=root / "golden" / "dev",
                                runs_dir=root / "runs", mode="SIMULATION")
    report = evaluator.run_golden(release_id)
    run_dirs = sorted((root / "runs" / "eval").glob(f"*-{release_id}"))
    report_path = run_dirs[-1] / "report.json"
    if report["totals"]["cases"] != len(catalog):
        raise SystemExit(f"M6 实测覆盖 {report['totals']['cases']} 条 != 行为目录 {len(catalog)} 条")
    if report["failures"]:
        raise SystemExit(f"M6 实测存在未过案例 {report['failures']}（黄金线未达成，不予打包）")

    # ---------------------------------------------------------------- 3 签名成绩
    scores = import_golden_scores(report_path, catalog, release_id=release_id,
                                  run_ref=str(report_path.relative_to(root)))

    # ---------------------------------------------------------------- 4 评审流
    motivation = (f"{release_id} 首个 Agent Release：资产基线冻结"
                  f"（{len(registered)} 项四类资产）")
    impact = "影响面=全部能力域行为承诺（AgentContract v1 六域+约束清单）"
    for asset_id, _chain in registered:
        proposal = review.submit_proposal(
            asset_id, motivation=motivation, impact=impact,
            badcases=["none"])
        review.start_evaluation(proposal.proposal_id,
                                candidate_run_ref=str(report_path))
        status = publish_asset(asset_id, proposal, store=store, pipeline=review)
        if status != "PUBLISHED":
            raise SystemExit(f"资产 {asset_id} 发布失败: {status}")

    # ---------------------------------------------------------------- 5 打包+门禁+发布
    def _refs_of(*types: str) -> list:
        return [f"{r.asset_id}@{r.version}" for r in store.all_assets()
                if r.type in types]

    draft = {
        "release_id": release_id,
        "model_ref": model_ref,
        "prompt_refs": _refs_of("PROMPT"),
        "skill_refs": _refs_of("SKILL"),
        "tool_refs": _refs_of("TOOL"),
        "ontology_version": None,  # 由 build_release 对照 M4 目录 hash 填充
        "golden_scores": scores,
        "frozen_scenarios": ["dev-01-report", "dev-02-alarm", "dev-02b-remote"],
        "contract_version": CONTRACT_VERSION,
        "agent_ref": (f"{contract.contract_id}@{contract.version}"),
    }
    from m4_semantic import compute_ontology_version

    draft["ontology_version"] = compute_ontology_version(root / "ontology")
    built = build_release(draft, store=store, contract=contract,
                          ontology_dir=root / "ontology", repo_root=root)
    gate: GateResult = gate_release(built, contract=contract,
                                    ontology_dir=root / "ontology")
    if not gate.passed:
        raise SystemExit(f"发布门禁未通过: {json.dumps(gate.to_dict(), ensure_ascii=False)}")
    evidence_cases = root / MOCK_RELEASE_DIR / f"{release_id}.yaml"
    result = publish_release(built, gate, releases_dir=releases_dir,
                             machine=machine, store=store,
                             evidence_report=report_path,
                             evidence_cases=evidence_cases)

    # ---------------------------------------------------------------- 6 复核
    resolved = resolve_release(release_id, releases_dir=releases_dir, repo_root=root)
    re_eval = GoldenEvaluator(golden_dir=root / "golden" / "dev",
                              runs_dir=root / "runs", mode="SIMULATION"
                              ).run_golden(release_id)
    return {
        "release_id": release_id,
        "action": "published",
        "assets": len(registered),
        "gate": gate.to_dict(),
        "golden_pass_rate": report["pass_rate"],
        "golden_score_100": report["totals"]["score_100"],
        "published_at": result["manifest"]["published_at"],
        "manifest_files": sorted(resolved["manifest"]["files"]),
        "re_eval_pass_rate": re_eval["pass_rate"],
        "audit_events": len(sink_events),
    }


def _verify_published(release_id: str, *, root: Path, contract: AgentContract,
                      catalog: dict, events: list) -> dict:
    """已发布：只读复核（manifest 完整性 + 签名 + 黄金重跑），零写入。"""
    from .release import verify_golden_scores

    resolved = resolve_release(release_id, releases_dir=root / "releases",
                               repo_root=root)
    bundle = resolved["bundle"]
    signature = verify_golden_scores(bundle.to_dict()["golden_scores"],
                                     release_id=release_id, catalog=catalog,
                                     release_dir=resolved["path"])
    from m6_flywheel.evaluator import GoldenEvaluator

    re_eval = GoldenEvaluator(golden_dir=root / "golden" / "dev",
                              runs_dir=root / "runs", mode="SIMULATION"
                              ).run_golden(release_id)
    return {
        "release_id": release_id,
        "action": "verified",
        "manifest_files": sorted(resolved["manifest"]["files"]),
        "signature_digest": signature["digest"][:12],
        "golden_pass_rate": re_eval["pass_rate"],
        "golden_score_100": re_eval["totals"]["score_100"],
        "failures": re_eval["failures"],
    }


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="M7 Release 组装 CLI（注册→评审→打包→门禁→发布/复核）")
    parser.add_argument("--release-id", default="rel-0001",
                        help="release id（缺省 rel-0001）")
    parser.add_argument("--model-ref", default="mock-scripted@offline-v1",
                        help="model_ref 六要素之一（缺省离线 mock）")
    args = parser.parse_args(argv)
    try:
        summary = assemble(args.release_id, model_ref=args.model_ref)
    except ImmutableReleaseError as exc:
        print(f"ASSEMBLE REFUSED: {exc}")
        return 1
    print(f"RELEASE {summary['release_id']} action={summary['action']} "
          f"pass_rate={summary['golden_pass_rate']} "
          f"score_100={summary['golden_score_100']} "
          f"files={len(summary['manifest_files'])} result=OK")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
