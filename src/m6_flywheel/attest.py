# -*- coding: utf-8 -*-
"""m6_flywheel.attest · M6 黄金跑分签名（M7 SPEC-M7-04 消费侧的签名源）。

M7 打包要求 ``golden_scores`` 必须是本次 release 实测且带 M6 签名（SPEC-M7-04，
"不得手工填报"）；M6 evaluator 的跑分报告（``GoldenEvaluator.run_golden`` 返回值）
经本模块产出**签名凭证（attestation）**：对报告的逐案例成绩做规范化摘要签名，
M7 打包/评审/门禁时重算校验，任一字段被改动即失配拒绝。

签名口径（确定性、离线、无密钥）::

    payload   = {kind, release_id, model_ref, golden_set_version, golden_dir,
                 mode, pass_rate, failures, totals, cases:[{case_id, passed}...]}
    signature = "sha256:" + sha256("M6-GOLDEN-ATTEST-v1|" + canonical_json(payload))

- canonical_json：``json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False)``；
- payload 不含时间戳（同报告同签名，可复算）；``generated_at``/逐案例判据明细不进
  签名（成绩摘要是被绑定对象，明细以 report 快照随发布物归档）；
- 防伪造边界：签名完整性绑定"逐案例成绩 ↔ 汇总字段 ↔ release_id"；M7 门禁另行
  校验 payload 与当前黄金集目录版本/案例数一致（RELEASE-FORMAT.md §签名）。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

__all__ = [
    "ATTEST_KIND",
    "SIGNATURE_PREFIX",
    "AttestationError",
    "attestation_payload",
    "canonical_json",
    "sign_payload",
    "attest_report",
    "verify_attestation",
]

#: 签名凭证类型标识（版本化；口径变更必须升版）
ATTEST_KIND = "M6-GOLDEN-RUN-v1"
#: 签名域分隔前缀（防跨域重放：不同用途的摘要不通用）
SIGNATURE_PREFIX = "M6-GOLDEN-ATTEST-v1|"

_PAYLOAD_KEYS = ("kind", "release_id", "model_ref", "golden_set_version",
                 "golden_dir", "mode", "pass_rate", "failures", "totals", "cases")


class AttestationError(ValueError):
    """签名凭证缺失/被篡改/结构非法。"""


def canonical_json(payload: Mapping[str, Any]) -> str:
    """规范化 JSON（键排序、紧凑分隔符、保留非 ASCII）——签名输入唯一口径。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def attestation_payload(report: Mapping[str, Any]) -> dict:
    """从 M6 evaluator 报告提取被签名载荷（逐案例成绩 + 汇总）。"""
    cases = [{"case_id": str(item.get("case_id")),
              "passed": bool(item.get("passed"))}
             for item in (report.get("cases") or [])]
    return {
        "kind": ATTEST_KIND,
        "release_id": str(report.get("release_id") or ""),
        "model_ref": str(report.get("release_model_ref") or ""),
        "golden_set_version": str(report.get("golden_set_version") or ""),
        "golden_dir": str(report.get("golden_dir") or ""),
        "mode": str(report.get("mode") or ""),
        "pass_rate": report.get("pass_rate"),
        "failures": list(report.get("failures") or []),
        "totals": dict(report.get("totals") or {}),
        "cases": cases,
    }


def sign_payload(payload: Mapping[str, Any]) -> str:
    """对载荷签名（域分隔前缀 + 规范化 JSON 的 sha256）。"""
    digest = hashlib.sha256(
        (SIGNATURE_PREFIX + canonical_json(payload)).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def attest_report(report: Mapping[str, Any]) -> dict:
    """M6 evaluator 报告 → 签名凭证（producer=M6；随发布物归档、供 M7 校验）。"""
    payload = attestation_payload(report)
    return {
        "producer": "M6",
        "kind": ATTEST_KIND,
        "evaluator": "m6_flywheel.evaluator",
        "payload": payload,
        "signature": sign_payload(payload),
    }


def verify_attestation(attestation: Mapping[str, Any], *, expect: Mapping[str, Any] | None = None) -> dict:
    """校验签名凭证：结构 + 签名重算 + 期望字段比对；失败抛 ``AttestationError``。

    expect（可选）：{release_id, golden_set_version, ...} —— M7 打包时绑定
    "本次 release 实测"（SPEC-M7-04：payload 的 release_id 必须等于被打包 release）。
    返回通过校验的 payload。
    """
    if not isinstance(attestation, Mapping):
        raise AttestationError("签名凭证必须是对象")
    payload = attestation.get("payload")
    if not isinstance(payload, Mapping):
        raise AttestationError("签名凭证缺 payload")
    for key in _PAYLOAD_KEYS:
        if key not in payload:
            raise AttestationError(f"签名 payload 缺字段: {key}")
    if str(payload.get("kind")) != ATTEST_KIND:
        raise AttestationError(
            f"签名凭证类型不符: {payload.get('kind')!r} != {ATTEST_KIND!r}")
    signature = str(attestation.get("signature") or "")
    recomputed = sign_payload(payload)
    if signature != recomputed:
        raise AttestationError(
            "签名校验失败（golden_scores 与实测凭证不一致，疑似手工填报/篡改）: "
            f"凭证 {signature[:20]}… != 重算 {recomputed[:20]}…")
    producer = str(attestation.get("producer") or "")
    if producer != "M6":
        raise AttestationError(f"签名方必须是 M6，实际 {producer!r}")
    for key, want in (expect or {}).items():
        got = payload.get(key)
        if key == "pass_rate":
            if got is None or abs(float(got) - float(want)) > 1e-9:
                raise AttestationError(
                    f"payload.{key}={got!r} 与期望 {want!r} 不符")
        elif got != want:
            raise AttestationError(f"payload.{key}={got!r} 与期望 {want!r} 不符")
    return dict(payload)
