# -*- coding: utf-8 -*-
"""tests/m6_eval_extra.py · M6 EVAL v2 补充执行器（specs-v2/M6-flywheel.md §3/§4）。

插件契约同 tests/EVAL-SCHEMA.md §4：暴露 ``EXECUTORS: dict[str, callable]``；
执行器签名 ``fn(case: dict, ctx) -> {"passed": bool, "detail": str, "metrics": dict}``。

只补 oracle 执行器（``src/m6_flywheel/eval_plugin.py``，零改动）没有的执行面：

- ``m6.golden_add_case``  SPEC-M6-02③⑧ 冻结 API ``add_golden_case`` 开发写入通道：
  holdout 标记条目拒绝（零事件）/ 正例落盘+manifest 登记+golden.case_added 事件 /
  同 case_id 旧版本重交拒绝（版本必须严格递增）。
- ``m6.attest_verify``    SPEC-M6-08①② 签名凭证直接探测：attest_report 确定性
  （同报告同签名）+ 合法凭证 verify 通过 + expect 绑定；篡改载荷/伪造签名/非 M6
  签名方/缺字段/expect 不符全部 AttestationError（变异 m6-attest-signature-off
  的直接杀伤面——载荷级签名重算比对在 M7 消费侧探测中不可达）。

全部数据驱动（断言数据取自用例 params/expect，零案例特判）；沙箱 =
``runtime/m6_eval/<case-id>/golden-add``（先清空独立可复跑，与 oracle 插件同一
沙箱约定）；now_fn 固定常数（确定性）；对 oracle 只读调用（写入只落沙箱；
attest 为纯计算零落盘）。
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

_SRC = str(Path(__file__).resolve().parents[1] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from m6_flywheel.attest import (  # noqa: E402
    ATTEST_KIND,
    AttestationError,
    attest_report,
    verify_attestation,
)
from m6_flywheel.golden_set import (  # noqa: E402
    MANIFEST_NAME,
    GoldenSetError,
    add_golden_case,
    load_golden_set,
)

__all__ = ["EXECUTORS"]

_NOW = "2026-09-28T00:00:00Z"


def _result(passed: bool, detail: str, metrics: dict | None = None) -> dict:
    return {"passed": bool(passed), "detail": str(detail), "metrics": metrics or {}}


def _sandbox(ctx: Any, case: dict) -> Path:
    root = (Path(ctx.root) / "runtime" / "m6_eval" / str(case.get("id") or "case")
            / "golden-add")
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    return root


def exec_golden_add_case(case: dict, ctx: Any) -> dict:
    """SPEC-M6-02③⑧ 开发写入通道（add_golden_case 冻结 API）三面探测。

    params: {normal_case, holdout_case, stale_version_case}（均为 GoldenCase 契约
    形态的 dict；stale_version_case 与 normal_case 同 case_id、版本未递增）。
    expect: {add_error_contains: [token...], stale_error_contains: [token...],
             case_added_events: n}
    """
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    root = _sandbox(ctx, case)
    problems: list = []
    audit: list = []

    def sink(event: dict) -> None:
        audit.append(event)

    # ---- 正例：普通 dev 案例经写入通道落盘（写文件 + 重建 manifest + 事件恰 1 条）
    normal = dict(params.get("normal_case") or {})
    if normal:
        case_id = str(normal.get("case_id"))
        returned = add_golden_case(dict(normal), root, now_fn=lambda: _NOW, sink=sink)
        if returned != case_id:
            problems.append(f"add_golden_case 返回 {returned!r} != {case_id!r}")
        target = root / f"case_{case_id}.yaml"
        if not target.is_file():
            problems.append(f"案例未落盘: {target.name}")
        manifest = yaml.safe_load((root / MANIFEST_NAME).read_text(encoding="utf-8")) or {}
        registered = {str(item.get("case_id")): item
                      for item in manifest.get("cases") or []}
        if case_id not in registered:
            problems.append("manifest 未登记新案例")
        elif not str(registered[case_id].get("sha256") or ""):
            problems.append("manifest 登记缺 sha256")

    # ---- 负例①（SPEC-M6-02③ 禁止类）：holdout 标记条目 → GoldenSetError，零事件
    holdout = dict(params.get("holdout_case") or {})
    if holdout:
        events_before = len(audit)
        try:
            add_golden_case(dict(holdout), root, now_fn=lambda: _NOW, sink=sink)
            problems.append("holdout 标记条目经开发写入通道未被拒绝"
                            "（SPEC-M6-02③ 失守）")
        except GoldenSetError as exc:
            for token in expect.get("add_error_contains") or []:
                if token not in str(exc):
                    problems.append(f"holdout 拒绝消息不含 {token!r}: {exc}")
        if len(audit) != events_before:
            problems.append("holdout 拒绝路径发出了事件（应零事件）")

    # ---- 负例②（SPEC-M6-02⑧）：同 case_id 版本未递增重交 → GoldenSetError
    stale = dict(params.get("stale_version_case") or {})
    if stale:
        try:
            add_golden_case(dict(stale), root, now_fn=lambda: _NOW, sink=sink)
            problems.append("同 case_id 旧版本重交未被拒绝（SPEC-M6-02⑧ 失守）")
        except GoldenSetError as exc:
            for token in expect.get("stale_error_contains") or []:
                if token not in str(exc):
                    problems.append(f"版本递增拒绝消息不含 {token!r}: {exc}")

    # ---- 收尾：目录装载只含正常案例（holdout 条目未混入），事件数=期望
    cases = load_golden_set(root)
    loaded_ids = sorted(c.case_id for c in cases)
    want_ids = sorted({str((params.get("normal_case") or {}).get("case_id") or "")}
                      - {""})
    if loaded_ids != want_ids:
        problems.append(f"装载集合 {loaded_ids} != 期望 {want_ids}（写入通道泄露）")
    want_events = int(expect.get("case_added_events") or 0)
    if len(audit) != want_events:
        problems.append(f"golden.case_added 事件 {len(audit)} 条 != 期望 {want_events}")
    for event in audit:
        if (str(event.get("type")) != "golden.case_added"
                or str(event.get("producer")) != "M6"):
            problems.append(f"审计事件不合约: {json.dumps(event, ensure_ascii=False)[:120]}")

    metrics = {"loaded": loaded_ids, "events": len(audit)}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"开发写入通道三面成立：正例落盘+manifest+事件恰 {want_events} 条；"
                         f"holdout 标记条目拒绝（零事件）；同 id 旧版本重交拒绝；"
                         f"装载集合无泄露 {loaded_ids}", metrics)


def exec_attest_verify(case: dict, ctx: Any) -> dict:
    """SPEC-M6-08①② 签名凭证探测（纯计算，无落盘）。

    params: {report: evaluator 报告形态 dict, tamper_probes: [{mode, error_contains,
    expect_release_id?}]}。tamper mode：tamper_payload_cases / tamper_payload_pass_rate /
    tamper_signature / wrong_producer / drop_payload_key / expect_binding。
    expect: {producer: "M6", kind: M6-GOLDEN-RUN-v1}
    """
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    report = dict(params.get("report") or {})
    problems: list = []
    if not report:
        return _result(False, "params.report 必填", {})

    # ---- 正例：attest_report 确定性（payload 不含时间戳 → 同报告同签名，可复算）
    attestation = attest_report(report)
    again = attest_report(report)
    if again != attestation:
        problems.append("attest_report 非确定性（同报告两次签名不一致）")
    if str(attestation.get("producer")) != str(expect.get("producer") or "M6"):
        problems.append(f"producer={attestation.get('producer')!r} != 期望 M6")
    if str(attestation.get("kind")) != str(expect.get("kind") or ATTEST_KIND):
        problems.append(f"kind={attestation.get('kind')!r} != 期望 {ATTEST_KIND!r}")
    # 合法凭证 verify 通过（无 expect 与带 expect 绑定两种）
    try:
        verify_attestation(attestation)
        verify_attestation(attestation, expect={"release_id": str(report.get("release_id"))})
    except AttestationError as exc:
        problems.append(f"合法凭证被误拒: {exc}")

    # ---- 负例：篡改/伪造/绑定不符全部 AttestationError（载荷级签名重算比对）
    killed_probes = 0
    for index, probe in enumerate(params.get("tamper_probes") or []):
        variant = copy.deepcopy(attestation)
        mode = str(probe.get("mode") or "")
        if mode == "tamper_payload_cases":
            variant["payload"]["cases"][0]["passed"] = \
                not bool(variant["payload"]["cases"][0].get("passed"))
        elif mode == "tamper_payload_pass_rate":
            variant["payload"]["pass_rate"] = 0.99
        elif mode == "tamper_signature":
            variant["signature"] = "sha256:" + "0" * 64
        elif mode == "wrong_producer":
            variant["producer"] = "HUMAN"
        elif mode == "drop_payload_key":
            variant["payload"].pop("mode", None)
        elif mode == "expect_binding":
            pass  # 凭证不改，expect 绑定其它 release
        else:
            problems.append(f"tamper_probes[{index}] 未知 mode: {mode!r}")
            continue
        expect_kwargs = {}
        if probe.get("expect_release_id"):
            expect_kwargs["expect"] = {"release_id": str(probe["expect_release_id"])}
        try:
            verify_attestation(variant, **expect_kwargs)
            problems.append(f"篡改变体 {mode!r} 未被拒绝（SPEC-M6-08② 失守）")
        except AttestationError as exc:
            killed_probes += 1
            for token in probe.get("error_contains") or []:
                if token not in str(exc):
                    problems.append(f"变体 {mode!r} 拒绝消息不含 {token!r}: {exc}")

    metrics = {"probes": len(params.get("tamper_probes") or []),
               "killed_probes": killed_probes,
               "signature_prefix": str(attestation.get("signature"))[:15]}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"attest 三面成立：同报告同签名（确定性复算）；合法凭证 verify"
                         f"通过（含 expect={report.get('release_id')!r} 绑定）；"
                         f"{killed_probes} 个篡改变体全部 AttestationError 拒绝", metrics)


EXECUTORS = {
    "m6.golden_add_case": exec_golden_add_case,
    "m6.attest_verify": exec_attest_verify,
}
