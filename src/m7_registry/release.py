# -*- coding: utf-8 -*-
"""m7_registry.release · ReleaseBundle 组装+发布门禁（SPEC-M7-04/06/07）。

**六要素绑定（SPEC-M7-04）**：model_ref / prompt_refs / skill_refs / tool_refs /
ontology_version / golden_scores 缺一拒绝打包；golden_scores 必须是本次 release
实测且带 M6 签名（``golden_scores.by_domain.signature``），禁手工填报——
``import_golden_scores`` 是唯一合法产出口（从 M6 评估归档推导全部数字并计算
签名 digest）；``verify_golden_scores`` 重算 digest + 从归档重推成绩比对。

**M6 签名口径**（RELEASE-FORMAT.md §3）::

    by_domain.signature = {producer: M6, algorithm: sha256,
                           digest: sha256(canonical(成绩载荷)),
                           release_id, run_ref, generated_at}

    digest 输入 = canonical_json({release_id, golden_set_version, pass_rate,
                                  by_domain 去掉 signature})

**行为目录绑定（SPEC-M7-06）**：by_domain 携带 capability（六能力域成绩）/
category（四类目成绩）/ catalog（12 条种子逐条成绩）/ red_line（红线类目
通过记录）四块；门禁 ``gate_release`` 断言目录齐备+全过+红线 100%。

**本体联动（SPEC-M7-07）**：打包时校验 ontology_version 与 M4
``compute_ontology_version(ontology/)`` 一致（防"本体已改、release 未更新"）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from contracts import CONTRACT_VERSION, ReleaseBundle

from .agent_contract import RED_LINE_CATEGORY, AgentContract, catalog_index
from .assets import AssetStore, canonical_json, qualify_ref
from .dependencies import resolve_closure
from .review import load_m6_report

__all__ = [
    "SIX_ELEMENTS",
    "ReleaseBuildError",
    "GoldenSignatureError",
    "OntologyDriftError",
    "GateResult",
    "import_golden_scores",
    "scores_payload",
    "signature_digest",
    "verify_golden_scores",
    "build_release",
    "gate_release",
    "RELEASE_TRANSITIONS",
]

#: 六要素（SPEC-M7-04；缺一拒绝打包）
SIX_ELEMENTS = ("model_ref", "prompt_refs", "skill_refs", "tool_refs",
                "ontology_version", "golden_scores")

#: Release 状态机（SPEC-M7-05；与 tests/fixtures/m7_state_machines.yaml diff 为空）
RELEASE_TRANSITIONS = {
    "DRAFT": ("GATED",),
    "GATED": ("PUBLISHED",),
    "PUBLISHED": ("SUPERSEDED",),
    "SUPERSEDED": (),
}


class ReleaseBuildError(ValueError):
    """打包失败（六要素缺失/闭包失败/签名失败/本体漂移）。"""


class GoldenSignatureError(ReleaseBuildError):
    """golden_scores 无有效 M6 签名或与归档证据不符（禁手工填报）。"""


class OntologyDriftError(ReleaseBuildError):
    """ontology_version 与 M4 目录 hash 不一致（SPEC-M7-07）。"""


def _now() -> str:
    from m2_information.timestamps import utc_now_iso

    return utc_now_iso()


# ===========================================================================
# M6 签名：成绩导入 / digest / 校验
# ===========================================================================
def scores_payload(scores: Mapping) -> dict:
    """成绩载荷（digest 输入）：golden_scores 去掉 by_domain.signature。"""
    by_domain = {k: v for k, v in dict(scores.get("by_domain") or {}).items()
                 if k != "signature"}
    return {
        "release_id": str(scores.get("_release_id") or ""),
        "golden_set_version": str(scores.get("golden_set_version") or ""),
        "pass_rate": scores.get("pass_rate"),
        "by_domain": by_domain,
    }


def signature_digest(scores: Mapping, release_id: str) -> str:
    payload = scores_payload({**dict(scores), "_release_id": release_id})
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _derive_by_domain(report: Mapping, catalog: Mapping) -> dict:
    """从 M6 归档+行为目录推导 by_domain（capability/category/catalog/red_line）。"""
    case_rows = {}
    for item in report.get("cases") or []:
        case_id = str(item.get("case_id"))
        if case_id in case_rows:
            raise GoldenSignatureError(f"M6 归档案例重复: {case_id}")
        rubric_totals = [r.get("total") for r in item.get("rubric") or []]
        case_rows[case_id] = {
            "passed": bool(item.get("passed")),
            "rubric_total": (round(float(rubric_totals[0]), 4)
                             if rubric_totals else None),
        }
    unknown = sorted(set(case_rows) - set(catalog))
    if unknown:
        raise GoldenSignatureError(
            f"M6 归档含行为目录之外的案例 {unknown}（目录: {sorted(catalog)}）")
    capability: dict = {}
    category: dict = {}
    catalog_records: dict = {}
    for case_id, entry in catalog.items():
        if case_id not in case_rows:
            continue  # 目录完整性由 gate 断言（import 允许子集报告）
        row = case_rows[case_id]
        catalog_records[case_id] = {
            "category": entry["category"], "domain": entry["domain"],
            "anchor": entry["anchor"], "passed": row["passed"],
            "rubric_total": row["rubric_total"],
        }
        for bucket, key in ((capability, entry["domain"]), (category, entry["category"])):
            stats = bucket.setdefault(key, {"cases": 0, "passed": 0})
            stats["cases"] += 1
            stats["passed"] += 1 if row["passed"] else 0
    red_cases = sorted(cid for cid, e in catalog.items()
                       if e["category"] == RED_LINE_CATEGORY)
    red_records = {cid: ("passed" if case_rows.get(cid, {}).get("passed")
                         else "missing") for cid in red_cases}
    red_passed = sum(1 for v in red_records.values() if v == "passed")
    return {
        "capability": {k: capability[k] for k in sorted(capability)},
        "category": {k: category[k] for k in sorted(category)},
        "catalog": {cid: catalog_records[cid] for cid in sorted(catalog_records)},
        "red_line": {
            "pass_rate": round(red_passed / len(red_cases), 4) if red_cases else 0.0,
            "records": red_records,
        },
    }


def import_golden_scores(report: Path | str | Mapping, catalog: Mapping, *,
                         release_id: str,
                         now_fn: Callable[[], str] | None = None,
                         run_ref: str | None = None) -> dict:
    """唯一合法的 golden_scores 产出口：从 M6 评估归档推导成绩并签名。

    - 归档必须属于本 release（report.release_id == release_id，"本次 release 实测"）；
    - 全部数字（pass_rate/类目/目录/红线）机械推导，调用方无法注入手工值；
    - 返回带 ``by_domain.signature``（producer=M6）的成绩对象。
    """
    loaded = load_m6_report(report)
    if str(loaded.get("release_id")) != str(release_id):
        raise GoldenSignatureError(
            f"golden_scores 必须是本次 release 实测：归档 release_id="
            f"{loaded.get('release_id')!r} != {release_id!r}（SPEC-M7-04）")
    by_domain = _derive_by_domain(loaded, dict(catalog))
    scores = {
        "golden_set_version": str(loaded.get("golden_set_version") or ""),
        "pass_rate": loaded.get("pass_rate"),
        "by_domain": by_domain,
    }
    digest = signature_digest(scores, release_id)
    from m6_flywheel.attest import attest_report

    scores["by_domain"]["signature"] = {
        "producer": "M6",
        "algorithm": "sha256",
        "digest": digest,
        "release_id": str(release_id),
        "run_ref": str(run_ref if run_ref is not None
                       else (str(report) if not isinstance(report, Mapping) else "<inline>")),
        "attestation": attest_report(loaded),  # M6 侧签名凭证（attest.py：逐案例成绩签名）
        "generated_at": (now_fn or _now)(),
    }
    return scores


def _resolve_run_ref(run_ref: str, *, repo_root: Path | None = None,
                     release_dir: Path | None = None) -> Path:
    """run_ref 解析序：绝对路径 → release 目录内相对 → 仓库根相对。"""
    candidate = Path(run_ref)
    if candidate.is_absolute():
        return candidate
    if release_dir is not None and (release_dir / candidate).is_file():
        return release_dir / candidate
    if repo_root is not None and (repo_root / candidate).is_file():
        return repo_root / candidate
    return candidate


def verify_golden_scores(scores: Mapping, *, release_id: str, catalog: Mapping,
                         repo_root: Path | str | None = None,
                         release_dir: Path | None = None) -> dict:
    """签名校验（SPEC-M7-04：无 M6 签名/手工填报一律拒绝）。

    1. by_domain.signature 存在且 producer=M6 / algorithm=sha256；
    2. digest 与成绩载荷重算一致（改任何一个数字即失配）；
    3. run_ref 归档可装载、release_id 一致、从中重推的成绩与声明逐块相等。
    """
    if not isinstance(scores, Mapping):
        raise GoldenSignatureError("golden_scores 必须是对象")
    by_domain = scores.get("by_domain")
    if not isinstance(by_domain, Mapping):
        raise GoldenSignatureError("golden_scores.by_domain 缺失")
    signature = by_domain.get("signature")
    if not isinstance(signature, Mapping):
        raise GoldenSignatureError(
            "golden_scores 缺 M6 签名（by_domain.signature）——手工填报被拒"
            f"（SPEC-M7-04；入口=import_golden_scores）")
    if str(signature.get("producer")) != "M6":
        raise GoldenSignatureError(
            f"签名 producer={signature.get('producer')!r} != 'M6'（非 M6 实测签名）")
    if str(signature.get("algorithm")) != "sha256":
        raise GoldenSignatureError(
            f"签名 algorithm={signature.get('algorithm')!r} != 'sha256'")
    if str(signature.get("release_id")) != str(release_id):
        raise GoldenSignatureError(
            f"签名绑定 release_id={signature.get('release_id')!r} != {release_id!r}"
            f"（成绩非本次 release 实测）")
    digest = signature_digest(scores, release_id)
    if digest != str(signature.get("digest")):
        raise GoldenSignatureError(
            f"golden_scores 签名 digest 不符（声明 {str(signature.get('digest'))[:12]}…"
            f" 重算 {digest[:12]}…）——成绩被手工改动（SPEC-M7-04 禁手工填报）")
    run_ref = str(signature.get("run_ref") or "")
    root = Path(repo_root) if repo_root is not None else None
    report_path = _resolve_run_ref(run_ref, repo_root=root, release_dir=release_dir)
    if not report_path.is_file():
        raise GoldenSignatureError(
            f"M6 评估归档缺失: {report_path}（签名证据链断裂）")
    try:
        report = load_m6_report(report_path)
    except Exception as exc:  # noqa: BLE001
        raise GoldenSignatureError(f"M6 评估归档不可用: {exc}") from exc
    if str(report.get("release_id")) != str(release_id):
        raise GoldenSignatureError(
            f"签名证据归档 release_id={report.get('release_id')!r} != {release_id!r}")
    # M6 侧签名凭证（m6_flywheel.attest）：逐案例成绩摘要签名，重算比对
    attestation = signature.get("attestation")
    if not isinstance(attestation, Mapping):
        raise GoldenSignatureError(
            "签名缺 M6 凭证（by_domain.signature.attestation）——"
            "成绩非经 M6 attest 产出口（SPEC-M7-04 禁手工填报）")
    from m6_flywheel.attest import AttestationError, attest_report, verify_attestation

    try:
        verify_attestation(attestation, expect={"release_id": str(release_id)})
        if attest_report(report) != dict(attestation):
            raise GoldenSignatureError(
                "M6 签名凭证与归档报告不符（凭证非本归档实测产物）")
    except AttestationError as exc:
        raise GoldenSignatureError(f"M6 签名凭证校验失败: {exc}") from exc
    derived = _derive_by_domain(report, dict(catalog))
    for block in ("capability", "category", "catalog", "red_line"):
        if by_domain.get(block) != derived[block]:
            raise GoldenSignatureError(
                f"golden_scores.by_domain.{block} 与 M6 归档重推结果不符"
                f"（声明 {json.dumps(by_domain.get(block), ensure_ascii=False)[:120]}"
                f" ≠ 重推 {json.dumps(derived[block], ensure_ascii=False)[:120]}）")
    if scores.get("pass_rate") != report.get("pass_rate"):
        raise GoldenSignatureError(
            f"golden_scores.pass_rate={scores.get('pass_rate')!r} != 归档 "
            f"{report.get('pass_rate')!r}")
    if str(scores.get("golden_set_version")) != str(report.get("golden_set_version")):
        raise GoldenSignatureError("golden_scores.golden_set_version 与归档不符")
    return {"digest": digest, "run_ref": run_ref,
            "cases": len(report.get("cases") or [])}


# ===========================================================================
# 打包（build_release）与门禁（gate_release）
# ===========================================================================
def _ontology_hash(ontology_dir: Path | str) -> str:
    from m4_semantic import compute_ontology_version

    return compute_ontology_version(ontology_dir)


def build_release(draft: Mapping, *, store: AssetStore, contract: AgentContract,
                  ontology_dir: Path | str,
                  repo_root: Path | str | None = None) -> dict:
    """组装 ReleaseBundle（01 §3.7 冻结 API；六要素+闭包+签名+本体一致性）。

    draft 必含六要素（缺一拒绝）+ agent_ref（AgentContract 资产绑定；冻结
    ReleaseBundle 无 agent 字段，绑定落发布目录 manifest，RELEASE-FORMAT §2）。
    返回 ``{bundle: ReleaseBundle, closure: ClosureResult, signature: dict,
    agent_ref: str}``；bundle.prompt/skill/tool_refs 为带内容 hash 的合格引用。
    """
    if not isinstance(draft, Mapping):
        raise ReleaseBuildError("bundle_draft 必须是对象")
    missing = [name for name in SIX_ELEMENTS
               if name not in draft or draft[name] in (None, "", [], {})]
    if missing:
        raise ReleaseBuildError(
            f"Release 六要素缺失 {missing}（SPEC-M7-04：缺一拒绝打包）")
    agent_ref = str(draft.get("agent_ref") or "")
    if not agent_ref:
        raise ReleaseBuildError(
            "bundle_draft 缺 agent_ref（AgentContract 资产绑定；M7 §6 交付物）")
    agent_record = store.resolve_ref(agent_ref)
    if agent_record.type != "AGENT":
        raise ReleaseBuildError(
            f"agent_ref 必须指向 AGENT 资产，实际 {agent_record.type}")

    release_id = str(draft.get("release_id") or "")
    catalog = catalog_index(contract)
    root = Path(repo_root) if repo_root is not None else None
    signature_info = verify_golden_scores(
        draft["golden_scores"], release_id=release_id, catalog=catalog,
        repo_root=root)

    closure = resolve_closure(store, draft["skill_refs"], draft["tool_refs"],
                              draft["prompt_refs"])
    if not closure.ok:
        raise ReleaseBuildError(
            "依赖闭包解析失败（SPEC-M7-02）："
            + "；".join(str(e) for e in closure.errors))

    actual_hash = _ontology_hash(ontology_dir)
    if str(draft["ontology_version"]) != actual_hash:
        raise OntologyDriftError(
            f"ontology_version 与 M4 目录 hash 不一致（SPEC-M7-07）："
            f"draft={str(draft['ontology_version'])[:16]}… 实际={actual_hash[:16]}…"
            f"（本体已改、release 未更新）")
    contract_version = str(draft.get("contract_version") or CONTRACT_VERSION)
    if contract_version != CONTRACT_VERSION:
        raise ReleaseBuildError(
            f"contract_version {contract_version!r} != 冻结契约版本 {CONTRACT_VERSION!r}")

    bundle_payload = {
        "release_id": release_id,
        "model_ref": str(draft["model_ref"]),
        "prompt_refs": sorted(store.resolve_ref(r).ref() for r in draft["prompt_refs"]),
        "skill_refs": sorted(store.resolve_ref(r).ref() for r in draft["skill_refs"]),
        "tool_refs": sorted(store.resolve_ref(r).ref() for r in draft["tool_refs"]),
        "ontology_version": actual_hash,
        "golden_scores": draft["golden_scores"],
        "frozen_scenarios": [str(s) for s in draft.get("frozen_scenarios") or []],
        "contract_version": contract_version,
    }
    bundle = ReleaseBundle.from_dict(bundle_payload)
    return {"bundle": bundle, "closure": closure,
            "signature": signature_info, "agent_ref": agent_record.ref(),
            "catalog": catalog}


class GateResult:
    """发布门禁结论（SPEC-M7-05/06：GATED 判定）。"""

    def __init__(self, release_id: str, checks: list, missing: list) -> None:
        self.release_id = release_id
        self.checks = checks
        self.missing = missing

    @property
    def passed(self) -> bool:
        return all(c["passed"] for c in self.checks) and not self.missing

    def to_dict(self) -> dict:
        return {"release_id": self.release_id, "passed": self.passed,
                "checks": self.checks, "missing": self.missing}


def gate_release(built: Mapping, *, contract: AgentContract,
                 ontology_dir: Path | str) -> GateResult:
    """发布门禁：黄金线（12 条目录全过）+ 红线 100% + 契约一致性。

    - catalog_complete：行为目录每条案例都有成绩记录（缺项列入 missing）；
    - catalog_passed：12 条种子全过（黄金线）；
    - red_line_100pct：红线类目 100% 且逐条通过记录在档（缺任一→GATED 失败）；
    - ontology_hash / contract_version：与打包时一致的复校。
    """
    bundle: ReleaseBundle = built["bundle"]
    catalog = built["catalog"]
    scores = bundle.golden_scores
    by_domain = dict(scores.by_domain or {})
    catalog_block = dict(by_domain.get("catalog") or {})
    red_block = dict(by_domain.get("red_line") or {})
    records = dict(red_block.get("records") or {})
    checks: list = []
    missing: list = []

    missing_cases = sorted(set(catalog) - set(catalog_block))
    for case_id in missing_cases:
        entry = catalog[case_id]
        missing.append(
            f"{case_id}（{entry['category']}/{entry['domain']}）无成绩记录")
    checks.append({
        "name": "catalog_complete",
        "passed": not missing_cases,
        "detail": (f"行为目录 {len(catalog)} 条全部有成绩记录"
                   if not missing_cases else f"缺成绩记录: {missing_cases}"),
    })
    failed_cases = sorted(cid for cid, row in catalog_block.items()
                          if not row.get("passed"))
    checks.append({
        "name": "catalog_passed",
        "passed": not failed_cases,
        "detail": ("黄金线达成：12 条种子全过" if not failed_cases
                   else f"黄金线未达成（未过案例）: {failed_cases}"),
    })
    red_cases = contract.red_line_cases()
    red_missing = [cid for cid in red_cases
                   if records.get(cid) != "passed"]
    for case_id in red_missing:
        missing.append(f"{case_id}（red_line）缺红线通过记录")
    red_rate = red_block.get("pass_rate")
    red_ok = (not red_missing and red_cases
              and float(red_rate or 0.0) >= 1.0)
    checks.append({
        "name": "red_line_100pct",
        "passed": bool(red_ok),
        "detail": (f"红线类目 100%（{len(red_cases)} 条通过记录在档）" if red_ok
                   else f"红线类目未达 100%：pass_rate={red_rate}，"
                        f"缺通过记录 {red_missing}"),
    })
    checks.append({
        "name": "ontology_hash",
        "passed": bundle.ontology_version == _ontology_hash(ontology_dir),
        "detail": f"ontology_version={str(bundle.ontology_version)[:16]}…",
    })
    checks.append({
        "name": "contract_version",
        "passed": bundle.contract_version == CONTRACT_VERSION,
        "detail": f"contract_version={bundle.contract_version}（现行 {CONTRACT_VERSION}）",
    })
    return GateResult(str(bundle.release_id), checks, missing)
