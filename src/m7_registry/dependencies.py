# -*- coding: utf-8 -*-
"""m7_registry.dependencies · Release 依赖闭包解析（SPEC-M7-02）。

打包时解析 ``skill_refs``/``tool_refs``（含 ``prompt_refs``）的传递闭包：

- **显式版本**：闭包内一切引用必须 ``<asset_id>@<version>``（可带 ``#hash``）；
  缺版本或 floating token（latest/* /head/…）→ :class:`FloatingVersionError`；
- **缺失**：引用在注册表中不存在（或版本不存在）→ :class:`MissingDependencyError`
  （错误消息含缺失 ID，EVAL-M7-02-N2 口径）；
- **循环**：依赖图出现回边 → :class:`CyclicDependencyError`（列出环路）。

依赖边来源（全部数据驱动，读描述子）：
- SKILL：``entry.prompt_ref``（01 §2.7）+ 描述子 ``dependencies[]``；
- PROMPT/TOOL/AGENT：描述子 ``dependencies[]``。
"""
from __future__ import annotations

from typing import Iterable, Mapping

from .assets import AssetNotFoundError, AssetStore, AssetValidationError, parse_ref

__all__ = [
    "DependencyError",
    "FloatingVersionError",
    "MissingDependencyError",
    "CyclicDependencyError",
    "ClosureResult",
    "resolve_closure",
    "declared_dependencies",
]


class DependencyError(ValueError):
    """依赖解析基错误（打包失败口径）。"""


class FloatingVersionError(DependencyError):
    """floating 版本引用（SPEC-M7-02 禁止）。"""


class MissingDependencyError(DependencyError):
    """闭包缺资产（错误消息含缺失 ID）。"""


class CyclicDependencyError(DependencyError):
    """循环依赖。"""


def declared_dependencies(record) -> list:
    """一条资产记录声明的依赖引用（SKILL 含 entry.prompt_ref）。"""
    deps: list = []
    if record.type == "SKILL":
        prompt_ref = (record.descriptor.get("entry") or {}).get("prompt_ref")
        if prompt_ref:
            deps.append(str(prompt_ref))
    deps.extend(str(item) for item in record.descriptor.get("dependencies") or [])
    return deps


class ClosureResult:
    """闭包解析结果：refs（含 hash 的合格引用集合）+ 边集 + 错误清单。"""

    def __init__(self, refs: dict, edges: list, errors: list) -> None:
        self.refs = refs          # asset_id -> qualified ref（闭包全量）
        self.edges = edges        # [[from_ref, to_ref], ...]（去重稳定序）
        self.errors = errors      # DependencyError 列表（空 = 可打包）

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {"refs": self.refs, "edges": self.edges,
                "errors": [str(e) for e in self.errors]}


def _resolve_record(store: AssetStore, ref: str, errors: list):
    """解析单条引用 → 记录；floating/缺失归类入 errors。"""
    try:
        parsed = parse_ref(ref)
    except AssetValidationError as exc:
        errors.append(FloatingVersionError(str(exc)))
        return None, None
    try:
        record = store.resolve_ref(f"{parsed['asset_id']}@{parsed['version']}")
    except AssetNotFoundError as exc:
        errors.append(MissingDependencyError(
            f"闭包缺失资产 {parsed['asset_id']}@{parsed['version']}"
            f"（引用 {ref!r}）：{exc}"))
        return None, None
    return record, parsed


def resolve_closure(store: AssetStore,
                    skill_refs: Iterable[str],
                    tool_refs: Iterable[str],
                    prompt_refs: Iterable[str] = ()) -> ClosureResult:
    """解析 skill/tool/prompt 三组种子的传递闭包。

    任一错误（floating/缺失/循环）都进入 ``errors``（打包失败；SPEC-M7-02）。
    全部解析成功时 ``refs`` 覆盖闭包全量节点（含种子自身）。
    """
    errors: list = []
    edges: list = []
    visited: dict = {}   # asset_id -> qualified ref
    on_path: dict = {}   # asset_id -> 栈序（环检测）
    order: list = []

    def walk(ref: str, path: list, from_ref: str | None = None) -> None:
        record, parsed = _resolve_record(store, ref, errors)
        if record is None:
            return
        asset_id = record.asset_id
        qualified = record.ref()
        if from_ref is not None:
            edges.append([from_ref, qualified])
        if asset_id in on_path:
            cycle = path[path.index(asset_id):] + [asset_id]
            errors.append(CyclicDependencyError(
                "闭包存在循环依赖: " + " -> ".join(cycle)))
            return
        if asset_id in visited:
            return
        visited[asset_id] = qualified
        order.append(asset_id)
        on_path[asset_id] = len(path)
        for dep in declared_dependencies(record):
            walk(dep, path + [asset_id], qualified)
        on_path.pop(asset_id, None)

    for ref in list(skill_refs) + list(tool_refs) + list(prompt_refs):
        walk(str(ref), [])

    dedup_edges: list = []
    seen: set = set()
    for edge in edges:
        key = tuple(edge)
        if key not in seen:
            seen.add(key)
            dedup_edges.append(edge)
    refs = {asset_id: visited[asset_id] for asset_id in order}
    return ClosureResult(refs, dedup_edges, errors)
