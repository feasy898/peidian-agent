# -*- coding: utf-8 -*-
"""m7_registry · Registry & Release（资产层）：四类资产注册/版本/变更评审、
Agent Release 打包与发布门禁（specs/M7-registry-release.md）。

01 §3.7 冻结 API（本包出口）::

    register_asset(type: PROMPT/SKILL/TOOL/AGENT, descriptor) -> AssetId+Version
    publish_asset(asset_id, review: ReviewRecord) -> status
    build_release(bundle_draft) -> ReleaseBundle（含六要素/闭包/签名校验）
    resolve_release(release_id) -> ResolvedRelease
    diff_release(a, b) -> ReleaseDiff

发布物目录/字段口径见 ``RELEASE-FORMAT.md``；组装 CLI 见 ``assemble``
（``PYTHONPATH=src python -m m7_registry.assemble --release-id rel-0001``）。
"""
from __future__ import annotations

from .agent_contract import (
    CATEGORIES,
    RED_LINE_CATEGORY,
    AgentContract,
    AgentContractError,
    catalog_index,
    load_agent_contract,
)
from .assets import (
    ASSET_TYPES,
    AssetError,
    AssetExistsError,
    AssetImmutableError,
    AssetNotFoundError,
    AssetRecord,
    AssetStore,
    AssetUnchangedError,
    AssetValidationError,
    parse_ref,
    qualify_ref,
    register_asset,
)
from .dependencies import (
    ClosureResult,
    CyclicDependencyError,
    DependencyError,
    FloatingVersionError,
    MissingDependencyError,
    resolve_closure,
)
from .publish import (
    ImmutableReleaseError,
    IllegalReleaseTransitionError,
    PublishError,
    ReleaseStateMachine,
    diff_release,
    publish_release,
    resolve_release,
    supersede_release,
    write_release_file,
)
from .release import (
    SIX_ELEMENTS,
    GateResult,
    GoldenSignatureError,
    OntologyDriftError,
    ReleaseBuildError,
    RELEASE_TRANSITIONS,
    build_release,
    gate_release,
    import_golden_scores,
    verify_golden_scores,
)
from .review import (
    REVIEW_TRANSITIONS,
    GoldenRegressionError,
    IllegalReviewTransitionError,
    ProposalIncompleteError,
    ReviewBypassError,
    ReviewError,
    ReviewPipeline,
    ReviewRecord,
    publish_asset,
    score_of_report,
)

__all__ = [
    # 01 §3.7 冻结 API
    "register_asset", "publish_asset", "build_release", "resolve_release",
    "diff_release",
    # 资产层
    "ASSET_TYPES", "AssetStore", "AssetRecord", "AssetError",
    "AssetExistsError", "AssetImmutableError", "AssetUnchangedError",
    "AssetNotFoundError", "AssetValidationError", "parse_ref", "qualify_ref",    # AgentContract
    "AgentContract", "AgentContractError", "load_agent_contract",
    "catalog_index", "CATEGORIES", "RED_LINE_CATEGORY",
    # 依赖闭包
    "resolve_closure", "ClosureResult", "DependencyError",
    "FloatingVersionError", "MissingDependencyError", "CyclicDependencyError",
    # 评审流
    "ReviewPipeline", "ReviewRecord", "REVIEW_TRANSITIONS", "ReviewError",
    "IllegalReviewTransitionError", "ProposalIncompleteError",
    "ReviewBypassError", "GoldenRegressionError", "score_of_report",
    # 打包/门禁
    "SIX_ELEMENTS", "RELEASE_TRANSITIONS", "ReleaseBuildError",
    "GoldenSignatureError", "OntologyDriftError", "GateResult",
    "import_golden_scores", "verify_golden_scores", "gate_release",
    # 发布
    "publish_release", "write_release_file", "supersede_release",
    "ReleaseStateMachine", "ImmutableReleaseError",
    "IllegalReleaseTransitionError", "PublishError",
]
