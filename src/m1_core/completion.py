# -*- coding: utf-8 -*-
"""m1_core.completion · 完成验证器（specs/M1-agent-core.md SPEC-M1-06）。

**申请与判定分离**：模型只能"申请完成"（CompletionClaim），判定由本模块依据
权威证据做出，verdict ∈ {ACCEPTED, NEED_MORE_EVIDENCE, REJECTED}：

- **ACCEPTED**：预期产物清单全部核对通过（status ∈ {READY, PUBLISHED}）且
  evidence 三态齐全（intended/issued/observed）；
- **NEED_MORE_EVIDENCE**：引用可解析但证据不完整（如缺 observed）/产物未就绪
  → 列出缺口（调用方回 RUNNING 并把 gaps 注入 todos）；
- **REJECTED**：Claim 含**伪造引用**（产物/证据引用无法解析）——不是证据不足，
  而是申请本身无效。

证据口径（SPEC-M1-07 观测即事实）：evidence_ref 指向 M2 工作区 ``evidence/``
下的三态证据序列化（``{"kind": "action_evidence", "evidence": {...}}``，
由 loop 的 Observe 阶段从 ActionResult.evidence 落盘）；模型自述不构成证据。

判定为纯函数（不改任务状态）；状态迁移（VERIFYING→COMPLETED/RUNNING）由
AgentCore.request_completion 按裁定执行。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = [
    "VERDICTS",
    "CompletionClaim",
    "CompletionVerdict",
    "CompletionVerifier",
    "claim_fingerprint",
]

#: 裁定三值（01 §3.1 request_completion）
VERDICTS: tuple[str, ...] = ("ACCEPTED", "NEED_MORE_EVIDENCE", "REJECTED")

#: 产物就绪状态（SPEC-M1-06：Artifact 状态=PUBLISHED/READY）
ACCEPTED_ARTIFACT_STATUSES: tuple[str, ...] = ("READY", "PUBLISHED")


@dataclass
class CompletionClaim:
    """完成申请（模型侧声明，非判定依据）。"""

    task_id: str = ""
    expected_artifacts: list = field(default_factory=list)
    evidence_refs: list = field(default_factory=list)
    summary: str = ""

    @classmethod
    def from_dict(cls, data: Mapping | None) -> "CompletionClaim":
        payload = dict(data or {})
        return cls(
            task_id=str(payload.get("task_id", "") or ""),
            expected_artifacts=[str(a) for a in payload.get("expected_artifacts") or []],
            evidence_refs=[str(r) for r in payload.get("evidence_refs") or []],
            summary=str(payload.get("summary", "") or ""),
        )

    def to_dict(self) -> dict:
        return {"task_id": self.task_id,
                "expected_artifacts": list(self.expected_artifacts),
                "evidence_refs": list(self.evidence_refs),
                "summary": self.summary}


def claim_fingerprint(claim: CompletionClaim) -> str:
    """Claim 内容指纹（完成令牌登记用，确定性）。"""
    import hashlib

    payload = json.dumps(claim.to_dict(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class CompletionVerdict:
    """完成判定结论。"""

    verdict: str
    reasons: list = field(default_factory=list)
    gaps: list = field(default_factory=list)     # NEED_MORE_EVIDENCE 的缺口 todos
    checks: list = field(default_factory=list)   # [{name, passed, detail}]
    fabricated: list = field(default_factory=list)  # 伪造引用清单（REJECTED 依据）

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "reasons": list(self.reasons),
                "gaps": list(self.gaps), "checks": list(self.checks),
                "fabricated": list(self.fabricated)}


def _check(name: str, passed: bool, detail: str) -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail}


_REF_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


def _ref_slug(ref: str) -> str:
    """引用 → 确定性缺口 id 片段（不用 hash——跨进程必须稳定）。"""
    return _REF_SLUG_RE.sub("-", str(ref).rsplit("@", 1)[0].lower()).strip("-") or "item"


class CompletionVerifier:
    """完成验证器（依赖 M2：状态读取/产物查询/工作区证据读取；纯判定无状态变更）。"""

    def __init__(self, info: Any) -> None:
        self.info = info

    # -------------------------------------------------------------- 判定
    def judge(self, task_id: str, claim: CompletionClaim) -> CompletionVerdict:
        state = self.info.get_task(task_id)
        checks: list[dict] = []
        fabricated: list[str] = []
        gaps: list[dict] = []
        reasons: list[str] = []

        # ---- A. 预期产物清单核对（最终阶段 artifacts_expected ∪ claim 声明）
        required = self._expected_artifacts(state, claim)
        for ref in required:
            record = self._find_artifact(state, ref)
            if record is None:
                fabricated.append(f"artifact:{ref}")
                checks.append(_check(f"artifact:{ref}", False, "产物引用无法解析（伪造或未登记）"))
                continue
            status = str(record.get("status", ""))
            if status in ACCEPTED_ARTIFACT_STATUSES:
                checks.append(_check(f"artifact:{ref}", True, f"产物状态 {status}"))
            else:
                gaps.append({
                    "id": f"gap-completion-art-{_ref_slug(ref)}",
                    "text": f"完成缺口：产物 {ref} 状态为 {status}，需 {'/'.join(ACCEPTED_ARTIFACT_STATUSES)}",
                    "status": "PENDING",
                })
                checks.append(_check(f"artifact:{ref}", False,
                                     f"产物状态 {status} 未达 {'/'.join(ACCEPTED_ARTIFACT_STATUSES)}"))
                reasons.append(f"产物 {ref} 状态 {status} 未就绪")

        # ---- B. evidence 三态齐全（state.evidence_refs ∪ claim.evidence_refs）
        evidence_refs = list(dict.fromkeys(
            [str(r) for r in getattr(state, "evidence_refs", []) or []]
            + [str(r) for r in claim.evidence_refs]))
        complete_count = 0
        for ref in evidence_refs:
            evidence = self._read_evidence(state, ref)
            if evidence is None:
                fabricated.append(f"evidence:{ref}")
                checks.append(_check(f"evidence:{ref}", False, "证据引用无法解析（伪造或未落盘）"))
                continue
            missing_states = [key for key in ("intended", "issued", "observed")
                              if not evidence.get(key)]
            if not missing_states:
                complete_count += 1
                checks.append(_check(f"evidence:{ref}", True, "三态齐全（intended/issued/observed）"))
            else:
                gaps.append({
                    "id": f"gap-completion-ev-{_ref_slug(ref)}",
                    "text": f"完成缺口：证据 {ref} 缺 {'/'.join(missing_states)}",
                    "status": "PENDING",
                })
                checks.append(_check(f"evidence:{ref}", False,
                                     f"证据缺 {'/'.join(missing_states)}"))
                reasons.append(f"证据 {ref} 缺 {'/'.join(missing_states)}")

        # ---- C. 至少一条三态齐全的执行证据
        has_complete = complete_count >= 1
        checks.append(_check("evidence_complete_at_least_one", has_complete,
                             f"三态齐全证据 {complete_count} 条" if has_complete
                             else "无任何三态齐全的执行证据"))
        if not has_complete and not fabricated:
            gaps.append({
                "id": "gap-completion-evidence-none",
                "text": "完成缺口：尚无任何三态齐全（intended/issued/observed）的执行证据",
                "status": "PENDING",
            })
            reasons.append("无三态齐全证据")

        # ---- 裁定
        if fabricated:
            return CompletionVerdict(
                verdict="REJECTED",
                reasons=reasons + [f"伪造引用: {'; '.join(fabricated)}"],
                gaps=[], checks=checks, fabricated=fabricated,
            )
        if gaps:
            return CompletionVerdict(
                verdict="NEED_MORE_EVIDENCE", reasons=reasons,
                gaps=gaps, checks=checks, fabricated=[],
            )
        return CompletionVerdict(
            verdict="ACCEPTED",
            reasons=["预期产物清单核对通过，evidence 三态齐全"],
            gaps=[], checks=checks, fabricated=[],
        )

    # -------------------------------------------------------------- 解析
    def _expected_artifacts(self, state: Any, claim: CompletionClaim) -> list[str]:
        """预期产物清单 = plan 最终阶段 artifacts_expected ∪ claim.expected_artifacts。"""
        from . import planner

        required: list[str] = []
        final = planner.final_step(state)
        if final is not None:
            required.extend(final["artifacts_expected"])
        for ref in claim.expected_artifacts:
            if ref not in required:
                required.append(ref)
        return required

    def _find_artifact(self, state: Any, ref: str) -> Mapping | None:
        """按 artifact_id 或 schema_id 查任务产物（与阶段门禁同口径）。"""
        task_id = str(getattr(state, "task_id", "") or "")
        try:
            for record in self.info.store.list_artifacts(task_id):
                if record.artifact_id == ref or record.schema_id == ref:
                    return {"artifact_id": record.artifact_id,
                            "status": record.status.value,
                            "schema_id": record.schema_id}
        except Exception:  # noqa: BLE001 - 查询失败视为未解析（判定走缺口路径）
            return None
        return None

    def _read_evidence(self, state: Any, ref: str) -> Mapping | None:
        """读工作区证据文件（evidence/ 三态序列化；不可解析返回 None）。"""
        task_id = str(getattr(state, "task_id", "") or "")
        try:
            workspace = self.info.workspaces.workspace(task_id, create=False)
            text = workspace.read(str(ref))
        except Exception:  # noqa: BLE001 - 文件缺失/越权 → 无法解析
            return None
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return None
        if isinstance(data, Mapping) and data.get("kind") == "action_evidence":
            evidence = data.get("evidence")
            return evidence if isinstance(evidence, Mapping) else None
        return None
