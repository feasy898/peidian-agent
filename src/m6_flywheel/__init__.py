# -*- coding: utf-8 -*-
"""m6_flywheel · Flywheel（飞轮层）：轨迹采集、黄金集、Badcase、受控自进化。

specs/M6-flywheel.md 全部 SPEC 条款（01–06）实现；01 §3.6 冻结 API 在此统一导出：

- ``export_trajectory(trace_id) -> TrajectoryRecord``   # trajectory.py
- ``add_golden_case(case) -> CaseId``                   # golden_set.py
- ``run_golden(release_id, golden_set_version)``        # evaluator.py
- ``open_badcase(evidence) -> BadcaseId``               # badcase.py
- ``promote_to_skill(badcase_id, skill_draft)``         # skillize.py（走 M7 评审）

组件（M6 §2）：trajectory / golden_set / judges（JUDGE-SYNTAX.md）/ evaluator /
badcase / skillize。子模块按需惰性导出（PEP 562，避免 ``python -m`` 双导入告警）。
"""
from __future__ import annotations

from pathlib import Path

#: 仓库根（pathlib 推断，不依赖 cwd）
REPO_ROOT = Path(__file__).resolve().parents[2]

#: 惰性导出表（名字 -> (子模块, 属性)）
_LAZY_EXPORTS = {
    # trajectory（SPEC-M6-01）
    "export_trajectory": ("trajectory", "export_trajectory"),
    "TrajectoryExporter": ("trajectory", "TrajectoryExporter"),
    "TrajectoryRejectedError": ("trajectory", "TrajectoryRejectedError"),
    # golden_set（SPEC-M6-02）
    "add_golden_case": ("golden_set", "add_golden_case"),
    "load_golden_set": ("golden_set", "load_golden_set"),
    "verify_golden_dir": ("golden_set", "verify_golden_dir"),
    "GoldenSetError": ("golden_set", "GoldenSetError"),
    # judges（SPEC-M6-03）
    "judge_case": ("judges", "judge_case"),
    "score_rubric": ("judges", "score_rubric"),
    # evaluator（SPEC-M6-06）
    "run_golden": ("evaluator", "run_golden"),
    "GoldenEvaluator": ("evaluator", "GoldenEvaluator"),
    "ReleaseGuard": ("evaluator", "ReleaseGuard"),
    "ReleaseMutationRefusedError": ("evaluator", "ReleaseMutationRefusedError"),
    "EvaluatorError": ("evaluator", "EvaluatorError"),
    # badcase（SPEC-M6-04）
    "open_badcase": ("badcase", "open_badcase"),
    "BadcaseWorkflow": ("badcase", "BadcaseWorkflow"),
    "BadcaseStore": ("badcase", "BadcaseStore"),
    "BadcaseEvidence": ("badcase", "BadcaseEvidence"),
    # skillize（SPEC-M6-05）
    "promote_to_skill": ("skillize", "promote_to_skill"),
    "skillize": ("skillize", "skillize"),
    "MethodLedger": ("skillize", "MethodLedger"),
    "SkillizeError": ("skillize", "SkillizeError"),
    # attest（M6 黄金跑分签名；M7 SPEC-M7-04 消费侧签名源）
    "attest_report": ("attest", "attest_report"),
    "verify_attestation": ("attest", "verify_attestation"),
    "attestation_payload": ("attest", "attestation_payload"),
    "sign_payload": ("attest", "sign_payload"),
    "AttestationError": ("attest", "AttestationError"),
}


def __getattr__(name: str):
    entry = _LAZY_EXPORTS.get(name)
    if entry is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(f".{entry[0]}", package=__name__)
    return getattr(module, entry[1])


__all__ = sorted(_LAZY_EXPORTS)
