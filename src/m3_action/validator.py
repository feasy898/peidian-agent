# -*- coding: utf-8 -*-
"""m3_action.validator · ActionRequest 契约校验 + 参数 schema 校验（SPEC-M3-02）。

准入管线（顺序）：
1. 契约校验：``contracts.ActionRequest.from_dict``（缺字段/枚举越界/未知字段）；
2. 注册校验：capability 动作 ID 必须已注册（否则 UNREGISTERED，SPEC-M3-01）；
3. 披露校验：动作已注册但未对该 actor 角色披露 → NOT_DISCLOSED（SPEC-M3-01）；
4. 参数 schema 校验：arguments 违反描述符 schema → SCHEMA_INVALID + 错误路径。

任何阶段失败 → 不进事件主链（gateway 只落审计事件），状态 REJECTED。
schema 迷你校验器只支持声明式子集（type/required/enum/items/min/max/properties），
不引入 eval/exec，安全且数据驱动。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from contracts import ActionRequest, ContractValidationError

from .registry import CapabilityRegistry

__all__ = ["ValidationOutcome", "RequestValidator", "validate_params_schema"]

_ERROR_CODE_UNREGISTERED = "UNREGISTERED"
_ERROR_CODE_NOT_DISCLOSED = "NOT_DISCLOSED"
_ERROR_CODE_CONTRACT = "CONTRACT_INVALID"
_ERROR_CODE_SCHEMA = "SCHEMA_INVALID"


@dataclass
class ValidationOutcome:
    """校验结论：通过=.request 有值；失败=error 三元组。"""

    request: ActionRequest | None = None
    action_id: str | None = None
    ok: bool = False
    error_code: str | None = None
    error_path: str | None = None
    message: str = ""
    intended: dict = field(default_factory=dict)  # 失败时尽量保留的意图摘要（审计用）

    @property
    def failure(self) -> dict:
        return {"code": self.error_code, "path": self.error_path, "message": self.message}


# ---------------------------------------------------------------------------
# 参数 schema 迷你校验器（tools 适配器 PARAMS_SCHEMA 声明子集）
# ---------------------------------------------------------------------------
_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "bool": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, Mapping),
}


def validate_params_schema(schema: Mapping, arguments: Mapping, path: str = "arguments") -> list:
    """按声明式 schema 校验 arguments，返回错误路径列表（空=通过）。

    schema 子集：type/required/enum/items/min/max/properties（嵌套 object/array）。
    未知参数键：schema 声明了 properties 时拒绝（防拼写漂移，与 contracts.check_keys 同口径）。
    """
    errors: list = []
    if not isinstance(arguments, Mapping):
        return [f"{path}: 必须是对象（mapping），实际为 {type(arguments).__name__}"]
    properties = schema.get("properties") or {}
    for key in schema.get("required") or []:
        if key not in arguments or arguments.get(key) is None:
            errors.append(f"{path}.{key}: 必填参数缺失")
    for key, value in arguments.items():
        if key not in properties:
            if properties:
                errors.append(f"{path}.{key}: 未知参数（schema 未声明）")
            continue
        errors.extend(_check_property(properties[key], value, f"{path}.{key}"))
    return errors


def _check_property(rule: Mapping, value: Any, path: str) -> list:
    errors: list = []
    declared = str(rule.get("type", "string"))
    check = _TYPE_CHECKS.get(declared)
    if check is None:
        errors.append(f"{path}: schema 声明了未知类型 {declared!r}")
        return errors
    if not check(value):
        errors.append(
            f"{path}: 必须是 {declared}，实际为 {type(value).__name__}"
            f"（值 {value!r}）")
        return errors
    if "enum" in rule and value not in rule["enum"]:
        errors.append(f"{path}: 枚举越界: {value!r}（允许: {'/'.join(map(str, rule['enum']))}）")
    if declared in ("int", "number"):
        if "min" in rule and value < rule["min"]:
            errors.append(f"{path}: {value!r} < 下限 {rule['min']!r}")
        if "max" in rule and value > rule["max"]:
            errors.append(f"{path}: {value!r} > 上限 {rule['max']!r}")
    if declared == "array" and isinstance(rule.get("items"), Mapping):
        for index, item in enumerate(value):
            errors.extend(_check_property(rule["items"], item, f"{path}[{index}]"))
    if declared == "object" and isinstance(rule.get("properties"), Mapping):
        errors.extend(validate_params_schema(rule, value, path))
    return errors


# ---------------------------------------------------------------------------
# 准入管线
# ---------------------------------------------------------------------------
class RequestValidator:
    """ActionRequest 准入校验器（契约 → 注册 → 披露 → 参数 schema）。"""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry

    def validate(self, payload: Mapping, actor_role: str | None = None) -> ValidationOutcome:
        # 1) 契约校验（缺字段/枚举越界 → 不进主链）
        try:
            request = ActionRequest.from_dict(dict(payload or {}))
        except ContractValidationError as exc:
            return ValidationOutcome(
                error_code=_ERROR_CODE_CONTRACT,
                error_path=exc.path,
                message=str(exc),
                intended=_sanitize_raw(payload),
            )
        action_id = request.capability.split("@", 1)[0]

        # 2) 注册校验（UNREGISTERED——红线 1：未注册能力禁止执行）
        descriptor = self.registry.get(request.capability) or self.registry.by_action(action_id)
        if descriptor is None:
            return ValidationOutcome(
                action_id=action_id,
                error_code=_ERROR_CODE_UNREGISTERED,
                error_path="ActionRequest.capability",
                message=f"动作未注册: {request.capability!r}",
                intended=_intended_of(request),
            )

        # 3) 披露校验（已注册但未对该角色披露 → 同样 REJECTED，SPEC-M3-01）
        if descriptor.disclosed_roles and actor_role not in descriptor.disclosed_roles:
            return ValidationOutcome(
                request=request,
                action_id=action_id,
                error_code=_ERROR_CODE_NOT_DISCLOSED,
                error_path="actor",
                message=(f"能力 {request.capability} 未对角色 {actor_role!r} 披露"
                         f"（披露面: {'/'.join(descriptor.disclosed_roles)}）"),
                intended=_intended_of(request),
            )

        # 4) 参数 schema 校验（失败 → REJECTED + schema 错误路径）
        schema_errors = validate_params_schema(descriptor.params_schema, request.arguments)
        if schema_errors:
            return ValidationOutcome(
                request=request,
                action_id=action_id,
                error_code=_ERROR_CODE_SCHEMA,
                error_path=schema_errors[0].rsplit(":", 1)[0],
                message="；".join(schema_errors),
                intended=_intended_of(request),
            )
        return ValidationOutcome(request=request, action_id=action_id, ok=True,
                                 intended=_intended_of(request))


def _intended_of(request: ActionRequest) -> dict:
    """计划动作摘要（=ActionRequest 摘要，01 §2.2 evidence.intended）。"""
    return {
        "action_id": request.action_id,
        "task_id": request.task_id,
        "capability": request.capability,
        "actor_user": request.actor.user,
        "actor_agent": request.actor.agent,
        "purpose": request.purpose,
        "arguments": dict(request.arguments),
        "idempotency_key": request.idempotency_key,
    }


def _sanitize_raw(payload: Mapping) -> dict:
    """契约失败时的意图留痕（原始请求可序列化摘要；可能不完整）。"""
    try:
        raw = dict(payload or {})
    except (TypeError, ValueError):  # pragma: no cover - 防御
        return {"raw": repr(payload)}
    return {
        "raw_capability": raw.get("capability"),
        "raw_action_id": raw.get("action_id"),
        "raw_task_id": raw.get("task_id"),
        "incomplete": True,
    }
