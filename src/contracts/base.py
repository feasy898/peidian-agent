# -*- coding: utf-8 -*-
"""契约校验基础设施。

仅依赖标准库：为冻结数据结构提供统一的字段校验工具与异常类型。
约定（specs/01-contracts.md §8）：
- 时间戳一律 UTC ISO-8601；
- 枚举为封闭集，越界即校验失败；
- 校验错误统一抛 ContractValidationError，消息含字段路径（点分）。
"""
from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence

__all__ = [
    "ContractValidationError",
    "asdict_plain",
    "require",
    "check_str",
    "check_int",
    "check_float",
    "check_bool",
    "check_enum",
    "check_timestamp",
    "check_str_list",
    "check_mapping",
    "check_id",
    "check_capability_format",
    "check_keys",
]


class ContractValidationError(ValueError):
    """冻结契约校验失败。

    attributes:
        path: 点分字段路径，如 "risk.level"；
        message: 中文错误描述。
    """

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"[{path}] {message}")


def _enum_to_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _plain_dict_factory(pairs):
    """dataclass asdict 工厂：枚举成员序列化为契约字面量（str）。"""
    return {key: _enum_to_value(val) for key, val in pairs}


def asdict_plain(obj: Any) -> dict:
    """asdict 且枚举落为字面量：to_dict 的统一实现。"""
    return asdict(obj, dict_factory=_plain_dict_factory)


def require(data: Mapping[str, Any], field: str, path: str) -> Any:
    """取必填字段；缺失或为 None 抛错。"""
    if not isinstance(data, Mapping):
        raise ContractValidationError(path, "必须是对象（mapping）")
    if field not in data or data[field] is None:
        raise ContractValidationError(f"{path}.{field}" if path else field, "必填字段缺失")
    return data[field]


def check_keys(data: Mapping[str, Any], allowed: Sequence[str], path: str) -> None:
    """拒绝未知字段（防拼写漂移导致字段静默丢失）。"""
    unknown = sorted(set(data.keys()) - set(allowed))
    if unknown:
        raise ContractValidationError(path, f"存在未知字段: {', '.join(unknown)}")


def check_str(value: Any, path: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ContractValidationError(path, f"必须是字符串，实际为 {type(value).__name__}")
    if not allow_empty and not value:
        raise ContractValidationError(path, "不能为空字符串")
    return value


def check_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(path, f"必须是整数，实际为 {type(value).__name__}")
    return value


def check_float(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(path, f"必须是数值，实际为 {type(value).__name__}")
    return float(value)


def check_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ContractValidationError(path, f"必须是布尔值，实际为 {type(value).__name__}")
    return value


def check_enum(value: Any, enum_cls: type, path: str) -> Any:
    """枚举封闭集校验：按契约字面量（成员值）匹配，大小写敏感。

    枚举值即契约字面量（如事件主题 ``task.created``、状态 ``WAITING_INPUT``）。
    """
    if not isinstance(value, str):
        raise ContractValidationError(path, f"枚举必须是字符串，实际为 {type(value).__name__}")
    try:
        return enum_cls(value)
    except ValueError:
        allowed = "/".join(member.value for member in enum_cls)
        raise ContractValidationError(path, f"枚举越界: {value!r}（允许值: {allowed}）") from None


_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|\+00:00|-00:00)$"
)


def check_timestamp(value: Any, path: str) -> Any:
    """UTC ISO-8601 时间戳校验（保留原值，round-trip 不改写）。

    接受两种形态：
    - 字符串：``2026-09-15T08:30:00Z`` / ``...+00:00``（不接受无时区或非 UTC 偏移）；
    - ``datetime.datetime``：YAML 加载器会把未加引号的 ISO 时间戳解析为 datetime
      （pyyaml 行为），此处按 UTC tz-aware 放行并原样保留（tz-naive / 非 UTC 拒绝）。
    """
    if isinstance(value, datetime):
        tz = value.tzinfo
        if tz is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ContractValidationError(path, f"datetime 时间戳必须是 UTC，实际为 {value!r}")
        return value
    check_str(value, path)
    if not _TS_RE.match(value):
        raise ContractValidationError(
            path, f"必须是 UTC ISO-8601 时间戳（如 2026-09-15T08:30:00Z），实际为 {value!r}"
        )
    try:
        # Python 3.11+ 的 fromisoformat 直接接受 'Z' 后缀
        datetime.fromisoformat(value).astimezone(timezone.utc)
    except ValueError as exc:  # pragma: no cover - 正则已拦截绝大多数
        raise ContractValidationError(path, f"时间戳无法解析: {exc}") from exc
    return value


def check_str_list(value: Any, path: str) -> list:
    if not isinstance(value, list):
        raise ContractValidationError(path, f"必须是字符串列表，实际为 {type(value).__name__}")
    return [check_str(item, f"{path}[{i}]", allow_empty=False) for i, item in enumerate(value)]


def check_mapping(value: Any, path: str) -> dict:
    if not isinstance(value, Mapping):
        raise ContractValidationError(path, f"必须是对象（mapping），实际为 {type(value).__name__}")
    return dict(value)


def check_id(value: Any, path: str) -> str:
    """标识符校验（ULID/业务编号统一按非空字符串处理，宽松以兼容既有编号体系）。"""
    return check_str(value, path)


def check_capability_format(value: Any, path: str) -> str:
    """capability 格式："动作ID@版本"，如 ``query.measurement@v1``（01 §2.1）。"""
    check_str(value, path)
    if "@" not in value:
        raise ContractValidationError(path, f"capability 必须为 '动作ID@版本' 格式，实际为 {value!r}")
    action_id, _, version = value.partition("@")
    if not action_id or not version:
        raise ContractValidationError(path, f"capability 的动作 ID 与版本均不能为空，实际为 {value!r}")
    return value
