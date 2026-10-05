# -*- coding: utf-8 -*-
"""m2_information.artifact · Artifact 状态机 + schema 校验钩子。

specs/01-contracts.md §5.3（冻结迁移表）与 specs/M2-information.md SPEC-M2-08：

    DRAFT → VALIDATING → READY → PUBLISHED → ARCHIVED
    VALIDATING → REJECTED → DRAFT(修订)
    DRAFT/READY 可 → DELETED（软删，留记录）

- PUBLISH 必须过 schema 校验（validation.passed=true）；校验失败 → REJECTED
  且 validation.checks 带逐项 detail；
- 迁移非法抛 IllegalTransitionError（复用 01§5.1 异常类型，machine=artifact）；
- 每次迁移落 ``artifact.state_changed {from,to}``` 事件（含创建 NONE→DRAFT），
  事件序可回放（EVAL-M2-08-P）。

schema 钩子：``register_schema(schema_id, validator)``；内置 ``report.daily@v1``
（ADDENDUM §B 四段：devices / measurements（含时序趋势）/ conclusion /
regulation_refs）。规则 ID 存在性由 M4 联动（``rule_id_checker`` 注入钩子）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from contracts import ArtifactRecord

from .ids import new_ulid
from .state_store import IllegalTransitionError, StateStore
from .timestamps import utc_now_iso

__all__ = [
    "ARTIFACT_TRANSITIONS",
    "ArtifactManager",
    "ArtifactContentError",
    "ArtifactValidationError",
    "SchemaNotRegisteredError",
    "register_schema",
    "report_daily_v1",
    "SCHEMA_VALIDATORS",
]

# ---------------------------------------------------------------- 01 §5.3
ARTIFACT_TRANSITIONS: dict[str, list[str]] = {
    "DRAFT": ["VALIDATING", "DELETED"],
    "VALIDATING": ["READY", "REJECTED"],
    "REJECTED": ["DRAFT"],
    "READY": ["PUBLISHED", "DELETED"],
    "PUBLISHED": ["ARCHIVED"],
    "ARCHIVED": [],
    "DELETED": [],
}

#: 已注册内容 schema 校验器（schema_id → fn(content, ctx) -> ValidationReport dict）
SCHEMA_VALIDATORS: dict[str, Callable[[dict, dict], dict]] = {}


class ArtifactContentError(ValueError):
    """产物内容文件读写失败。"""


class ArtifactValidationError(ValueError):
    """产物状态迁移前置校验失败（如未过 schema 校验即 PUBLISH）。"""


class SchemaNotRegisteredError(ValueError):
    """schema_id 未注册校验器。"""


def register_schema(schema_id: str, validator: Callable[[dict, dict], dict]) -> None:
    """注册内容 schema 校验钩子（M4/M7 可扩展；同 id 覆盖=升级）。

    统一签名 ``validator(content: dict, ctx: dict) -> {"passed": bool, "checks": [...]}``；
    ``ctx["rule_id_checker"]`` 为规则 ID 存在性联动钩子（可缺省）。
    """
    SCHEMA_VALIDATORS[schema_id] = validator


def _check(name: str, passed: bool, detail: str) -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail}


def report_daily_v1(content: dict, ctx: dict | None = None) -> dict:
    """``report.daily@v1`` 四段 schema（ADDENDUM §B）。

    必含四段：devices（设备清单）、measurements（量测，含时序趋势数据：
    每条含 points 时序点列）、conclusion（结论）、regulation_refs（规则 ID 列表）。
    ``ctx["rule_id_checker"]``：规则 ID 存在性钩子（M4 SPEC-M4-05 联动；缺省
    不校验存在性，仅校验形态）。
    """
    rule_id_checker = (ctx or {}).get("rule_id_checker")
    checks: list[dict] = []
    sections = ("devices", "measurements", "conclusion", "regulation_refs")
    if not isinstance(content, dict):
        return {"passed": False, "checks": [_check("content_is_object", False,
                                                   "报告内容必须是对象")]}
    for section in sections:
        checks.append(_check(f"section:{section}", section in content,
                             f"四段 schema 缺少段 {section}" if section not in content
                             else "段存在"))
    devices = content.get("devices")
    checks.append(_check(
        "devices_is_list", isinstance(devices, list) and len(devices) > 0,
        "devices 必须为非空设备清单列表",
    ))
    measurements = content.get("measurements")
    trend_ok = isinstance(measurements, list) and len(measurements) > 0
    trend_detail = "measurements 必须为非空量测列表"
    if trend_ok:
        for i, item in enumerate(measurements):
            points = (item or {}).get("points") if isinstance(item, dict) else None
            if not isinstance(points, list) or not points or not all(
                isinstance(p, dict) and "ts" in p and "value" in p for p in points
            ):
                trend_ok = False
                trend_detail = f"measurements[{i}] 缺时序趋势数据（points[]，每点含 ts/value）"
                break
    if trend_ok:
        trend_detail = f"量测 {len(measurements)} 条均含时序趋势点列"
    checks.append(_check("measurements_trend", trend_ok, trend_detail))
    conclusion = content.get("conclusion")
    checks.append(_check(
        "conclusion_nonempty",
        isinstance(conclusion, (str, dict)) and bool(str(conclusion).strip()),
        "conclusion 不能为空",
    ))
    refs = content.get("regulation_refs")
    refs_ok = isinstance(refs, list) and len(refs) > 0 and all(
        isinstance(r, str) and r.strip() for r in refs
    )
    checks.append(_check(
        "regulation_refs_ids", refs_ok,
        "regulation_refs 必须为非空规则 ID 字符串列表" if not refs_ok
        else f"规则 ID 引用 {len(refs)} 条",
    ))
    if refs_ok and rule_id_checker is not None:
        unknown = list(rule_id_checker(list(refs)))
        checks.append(_check(
            "regulation_refs_exist", not unknown,
            f"规则 ID 不存在: {sorted(unknown)}" if unknown else "全部规则 ID 可解析",
        ))
    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks}


register_schema("report.daily@v1", report_daily_v1)


class ArtifactManager:
    """Artifact 生命周期管理（状态机 + 内容文件 + 事件）。"""

    def __init__(
        self,
        store: StateStore,
        workspaces,  # WorkspaceManager（避免循环导入，鸭子类型）
        event_log,
        *,
        rule_id_checker: Callable[[list], list] | None = None,
        now_fn: Callable[[], str] = utc_now_iso,
        id_gen: Callable[[], str] = new_ulid,
    ) -> None:
        self.store = store
        self.workspaces = workspaces
        self.event_log = event_log
        self.rule_id_checker = rule_id_checker
        self._now = now_fn
        self._id = id_gen

    # -------------------------------------------------------------- 创建
    def create(
        self,
        task_id: str,
        *,
        type: str,
        schema_id: str,
        content: dict | None = None,
        action_id: str,
        trace_id: str,
        version: int = 1,
        supersedes: str | None = None,
    ) -> ArtifactRecord:
        """创建 DRAFT 产物；content 写入工作区 artifacts/<id>/v<n>.json。"""
        artifact_id = f"art-{self._id()}"
        content_ref = f"artifacts/{artifact_id}/v{version}.json"
        record = {
            "artifact_id": artifact_id,
            "type": type,
            "status": "DRAFT",
            "schema_id": schema_id,
            "content_ref": content_ref,
            "created_by": {"task_id": task_id, "action_id": action_id},
            "validation": None,
            "version": version,
            "supersedes": supersedes,
        }
        parsed = ArtifactRecord.from_dict(record)
        if content is not None:
            ws = self.workspaces.workspace(task_id)
            ws.write(content_ref, json.dumps(content, ensure_ascii=False, indent=2))
        self.store.save_artifact(parsed)
        self._emit(task_id, trace_id, "NONE", "DRAFT", parsed)
        return parsed

    # -------------------------------------------------------------- 迁移
    def transition(
        self,
        artifact_id: str,
        to_status: str,
        *,
        trace_id: str,
        validation: dict | None = None,
    ) -> ArtifactRecord:
        """按 01§5.3 迁移；校验失败自动落 REJECTED（带 detail）。"""
        record = self.store.get_artifact(artifact_id)
        current = record.status.value
        if to_status not in ARTIFACT_TRANSITIONS.get(current, []):
            raise IllegalTransitionError(current, to_status, machine="artifact")
        if to_status == "VALIDATING":
            report = validation if validation is not None else self.run_schema(record)
            updated = self._with_validation(record, report)
            target = "READY" if report["passed"] else "REJECTED"
            # DRAFT→VALIDATING 事件 + 校验结论事件（REJECTED 或停留 VALIDATING）
            self.store.save_artifact(self._retarget(updated, "VALIDATING"))
            self._emit(record.created_by.task_id, trace_id, current, "VALIDATING", updated)
            if not report["passed"]:
                self.store.save_artifact(self._retarget(updated, "REJECTED"))
                self._emit(record.created_by.task_id, trace_id, "VALIDATING", "REJECTED", updated)
                return self.store.get_artifact(artifact_id)
            return self.store.get_artifact(artifact_id)
        if to_status in ("READY", "PUBLISHED"):
            report = record.validation
            if report is None or not report.passed:
                raise ArtifactValidationError(
                    f"产物 {artifact_id} 未通过 schema 校验（validation.passed != true），"
                    f"禁止 {current}→{to_status}"
                )
        updated = self._retarget(record, to_status)
        self.store.save_artifact(updated)
        self._emit(record.created_by.task_id, trace_id, current, to_status, updated)
        return updated

    def publish_new_version(
        self, artifact_id: str, *, content: dict, trace_id: str
    ) -> tuple[ArtifactRecord, ArtifactRecord]:
        """新版本替代：新记录 supersedes 旧 id，旧记录 PUBLISHED→ARCHIVED。"""
        old = self.store.get_artifact(artifact_id)
        if old.status.value != "PUBLISHED":
            raise ArtifactValidationError(
                f"仅 PUBLISHED 产物可被新版本替代，当前 {old.status.value}"
            )
        fresh = self.create(
            old.created_by.task_id,
            type=old.type.value,
            schema_id=old.schema_id,
            content=content,
            action_id=old.created_by.action_id,
            trace_id=trace_id,
            version=old.version + 1,
            supersedes=old.artifact_id,
        )
        archived = self.transition(artifact_id, "ARCHIVED", trace_id=trace_id)
        return fresh, archived

    def soft_delete(self, artifact_id: str, *, trace_id: str) -> ArtifactRecord:
        return self.transition(artifact_id, "DELETED", trace_id=trace_id)

    # -------------------------------------------------------------- 校验
    def run_schema(self, record: ArtifactRecord) -> dict:
        """执行 schema 校验钩子（内容从工作区读取；统一 ``fn(content, ctx)`` 签名）。"""
        validator = SCHEMA_VALIDATORS.get(record.schema_id)
        content = self.load_content(record)
        if validator is None:
            return {
                "passed": False,
                "checks": [_check("schema_registered", False,
                                  f"schema_id 未注册校验器: {record.schema_id}")],
            }
        return validator(content, {"rule_id_checker": self.rule_id_checker})

    def load_content(self, record: ArtifactRecord | str) -> dict:
        artifact = self.store.get_artifact(record) if isinstance(record, str) else record
        ws = self.workspaces.workspace(artifact.created_by.task_id, create=False)
        try:
            text = ws.read(artifact.content_ref)
        except FileNotFoundError as exc:
            raise ArtifactContentError(
                f"产物内容文件不可读: {artifact.content_ref}（{exc}）"
            ) from exc
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ArtifactContentError(f"产物内容非 JSON: {exc}") from exc

    def get(self, artifact_id: str) -> ArtifactRecord:
        return self.store.get_artifact(artifact_id)

    def status_of_content(self, task_id: str, rel_path: str) -> str | None:
        """按内容路径查产物状态（WorkspaceManager 跨任务读判定用）。"""
        normalized = rel_path.replace("\\", "/")
        for record in self.store.list_artifacts(task_id):
            if record.content_ref == normalized:
                return record.status.value
        return None

    # -------------------------------------------------------------- 内部
    def _retarget(self, record: ArtifactRecord, status: str) -> ArtifactRecord:
        data = record.to_dict()
        data["status"] = status
        return ArtifactRecord.from_dict(data)

    def _with_validation(self, record: ArtifactRecord, report: dict) -> ArtifactRecord:
        data = record.to_dict()
        data["validation"] = {
            "passed": bool(report.get("passed")),
            "checks": [
                {"name": c["name"], "passed": bool(c["passed"]), "detail": str(c["detail"])}
                for c in report.get("checks") or []
            ],
        }
        return ArtifactRecord.from_dict(data)

    def _emit(self, task_id: str, trace_id: str, from_status: str,
              to_status: str, record: ArtifactRecord) -> None:
        self.event_log.append(
            {
                "type": "artifact.state_changed",
                "subject": record.artifact_id,
                "payload": {
                    "from": from_status,
                    "to": to_status,
                    "task_id": task_id,
                    "schema_id": record.schema_id,
                    "version": record.version,
                },
                "trace_id": trace_id,
                "producer": "M2",
            },
            stream=f"task-{task_id}",
            now_fn=self._now,
        )
