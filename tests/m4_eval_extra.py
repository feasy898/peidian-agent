# tests/m4_eval_extra.py
# M4 补充执行器（变异覆盖缺口修复轮 2026-09-29）：oracle 执行器
# （src/m4_semantic/eval_plugin.py，9 个）没有的「加载期数据漂移」负向执行面——
# enums↔contracts 受控词表双向同源断言（SPEC-M4-01）需要向 loader 注入漂移副本才能测负向。
#
# 纪律：不改 oracle——在 runtime/ 临时副本目录上注入数据漂移，用后即删；
# 全部判据数据来自用例 params/expect（数据驱动，零案例特判）。
# 插件契约（tests/EVAL-SCHEMA.md §4）：暴露 EXECUTORS；
# 执行器签名 fn(case, ctx) -> {"passed": bool, "detail": str, "metrics": dict}。
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any, Mapping

import yaml

from m4_semantic.loader import OntologyLoadError, load_ontology

__all__ = ["EXECUTORS"]


def _apply_op(data: Any, op: Mapping[str, Any]) -> None:
    """按 {path: 'a.b.c', op: set|remove_key|remove_value, value} 对已加载 YAML 就地变更。

    - set：node[last] = value；
    - remove_key：删除键 last；
    - remove_value：从 node[last]（列表）中移除等于 value 的项（字符串比较）。
    """
    keys = str(op["path"]).split(".")
    node = data
    for key in keys[:-1]:
        node = node[key]
    last = keys[-1]
    kind = str(op.get("op", "set"))
    if kind == "set":
        node[last] = op.get("value")
    elif kind == "remove_key":
        node.pop(last, None)
    elif kind == "remove_value":
        node[last] = [v for v in (node[last] or []) if str(v) != str(op.get("value"))]
    else:
        raise ValueError(f"未知 patch op: {kind!r}")


def exec_loader_drift(case: dict, ctx) -> dict:
    """加载期数据漂移负向：复制 ontology/ 到临时副本，按 params.patch 注入数据变更，
    再 ``load_ontology(ontology_dir=副本, use_cache=False)`` 断言按预期拒绝。

    params: {ontology_dir?: 缺省 "ontology", instance?: 缺省 None（不装载实例）,
             patch: {<ontology/ 内相对文件名>: [{path, op, value}, ...]}}
    expect: {error_contains?, error_type?}（与 m4.load_reject 同一口径）
    """
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    src = Path(ctx.root) / str(params.get("ontology_dir", "ontology"))
    tmp = Path(ctx.root) / "runtime" / f"ontology_drift_{uuid.uuid4().hex[:8]}"
    problems: list = []
    error: Exception | None = None
    metrics = {"patches": 0}
    try:
        shutil.copytree(src, tmp)
        for rel, ops in (params.get("patch") or {}).items():
            path = tmp / str(rel)
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            for op in ops or []:
                _apply_op(data, op)
                metrics["patches"] += 1
            path.write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=True),
                encoding="utf-8",
            )
        try:
            load_ontology(ontology_dir=tmp,
                          instance=params.get("instance"),
                          use_cache=False)
        except OntologyLoadError as exc:
            error = exc
        if error is None:
            problems.append("期望加载拒绝但加载成功（漂移副本未被拒）")
        else:
            contains = expect.get("error_contains")
            if contains and str(contains) not in str(error):
                problems.append(f"已拒绝但消息不含 {contains!r}: {error}")
            want_type = expect.get("error_type")
            if want_type and type(error).__name__ != str(want_type):
                problems.append(f"异常类型 {type(error).__name__} != {want_type}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if problems:
        return {"passed": False, "detail": "；".join(problems), "metrics": metrics}
    return {"passed": True,
            "detail": f"漂移副本按预期拒绝（{type(error).__name__}）: {error}",
            "metrics": metrics}


EXECUTORS = {
    "m4.loader_drift": exec_loader_drift,
}
