#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_evals.py — 全项目 EVAL 总 runner（仓库骨架与 EVAL 验收基座 S0）。

用法（仓库根运行）::

    python run_evals.py --selftest          # schema 自检 + 隔离断言 + 目录完整性
    python run_evals.py --module m0         # 执行 tests/test_m0.yaml（S0 基座用例）
    python run_evals.py --module m1..m7     # 执行对应模块 EVAL
    python run_evals.py --module all        # 全量（m0..m7，未交付模块记 PENDING）

规则：
- 每次运行先跑隔离断言（scripts/ci_isolation.py）——命中即失败；
- 用例全部数据驱动（tests/test_m<id>.yaml，schema 见 tests/EVAL-SCHEMA.md），无硬编码特判；
- 支持模块注册自定义执行器插件（suite.executors[].module → EXECUTORS 字典）；
- 摘要行 ASCII；明细写 runtime/eval_results.json；
- 退出码：0 = 全部通过；1 = 存在失败；2 = 用法错误。

七类 Eval 形态（EVAL-SCHEMA.md 详述）：
  event_sequence      事件序回放
  state_transition    状态迁移断言
  policy_decision     策略三值
  idempotency         幂等
  expression          表达式判据
  negative_rejection  负向拒绝
  performance         性能门槛
另设通用形态 contract（冻结结构 round-trip / 拒绝）作为契约基座用例。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
SCRIPTS_DIR = ROOT / "scripts"
RESULTS_PATH = ROOT / "runtime" / "eval_results.json"

# src 布局：contracts / m1_core..m7_registry 以顶层包导入；scripts 供 ci_isolation 导入
for _p in (str(SRC_DIR), str(SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml  # noqa: E402

from contracts import ContractValidationError, STRUCTURES  # noqa: E402
import ci_isolation  # noqa: E402

#: m0 = S0 基座套件；m1..m7 = 模块套件（按交付顺序逐步补齐 test_m<id>.yaml）
MODULES = ("m0", "m1", "m2", "m3", "m4", "m5", "m6", "m7")
SUITE_TEMPLATE = "tests/test_{module}.yaml"  # module="m1" → tests/test_m1.yaml

#: Eval 形态（七类必备 + contract 通用形态）
EVAL_FORMS = (
    "event_sequence",
    "state_transition",
    "policy_decision",
    "idempotency",
    "expression",
    "negative_rejection",
    "performance",
    "contract",
)
SEVEN_MANDATORY_FORMS = EVAL_FORMS[:7]

CASE_ID_RE = re.compile(r"^EVAL-M\d+-[A-Za-z0-9]+-(P\d*|N\d*)$")

SCHEMA_DOC = ROOT / "tests" / "EVAL-SCHEMA.md"

# ---------------------------------------------------------------------------
# 目录完整性（--selftest）：specs/01§1 目录树 + ADDENDUM A/B 交付物
# ---------------------------------------------------------------------------
REQUIRED_DIRS = (
    "ontology", "regulations", "skills", "prompts", "tools",
    "golden/dev", "golden/dev/cases", "scenarios", "releases", "assets",
    "runtime", "scripts", "tests", "tests/fixtures",
    "src/contracts",
    "src/m1_core", "src/m2_information", "src/m3_action", "src/m4_semantic",
    "src/m5_simulation", "src/m6_flywheel", "src/m7_registry",
)
REQUIRED_FILES = (
    "pyproject.toml",
    "run_evals.py",
    "scripts/ci_isolation.py",
    "tests/EVAL-SCHEMA.md",
    "tests/CHANGELOG.md",
    "ontology/objects.yaml", "ontology/relations.yaml", "ontology/actions.yaml",
    "ontology/rules.yaml", "ontology/enums.yaml", "ontology/seed.yaml",
    "regulations/REG-SAFE.yaml", "regulations/REG-COMM.yaml",
    "regulations/REG-TECH.yaml", "regulations/REG-OP.yaml",
    "src/contracts/__init__.py",
    "src/m1_core/__init__.py", "src/m1_core/model_client.py",
    "src/m2_information/__init__.py", "src/m3_action/__init__.py",
    "src/m4_semantic/__init__.py", "src/m5_simulation/__init__.py",
    "src/m6_flywheel/__init__.py", "src/m7_registry/__init__.py",
)

ONTOLOGY_FILES = (
    "ontology/objects.yaml", "ontology/relations.yaml", "ontology/actions.yaml",
    "ontology/rules.yaml", "ontology/enums.yaml", "ontology/seed.yaml",
)
REGULATION_FILES = (
    "regulations/REG-SAFE.yaml", "regulations/REG-COMM.yaml",
    "regulations/REG-TECH.yaml", "regulations/REG-OP.yaml",
)


# ===========================================================================
# 安全表达式求值器（expression 形态）
# ===========================================================================
class ExpressionError(ValueError):
    """表达式语法/求值错误。"""


_EXPR_TOKEN_RE = re.compile(
    r"""\s*(?:
        (?P<num>\d+\.\d+|\d+)
      | (?P<str>'[^']*'|"[^"]*")
      | (?P<op>==|!=|>=|<=|&&|\|\||[><]|[+\-*/%!()\[\],.])
      | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
    )""",
    re.VERBOSE,
)

_CAPS_WORD_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

_KEYWORDS = {"and", "or", "not", "in", "true", "false", "null", "None", "True", "False"}


def _tokenize(text: str) -> list:
    tokens: list = []
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        m = _EXPR_TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            raise ExpressionError(f"无法解析的字符: {text[pos]!r}（位置 {pos}）")
        kind = m.lastgroup
        value = m.group(kind)
        tokens.append((kind, value))
        pos = m.end()
    tokens.append(("end", ""))
    return tokens


class _ExprParser:
    """递归下降：or < and < not < 比较 < 加减 < 乘除 < 一元 < 后缀 < 原子。"""

    def __init__(self, tokens: list, facts: dict) -> None:
        self.tokens = tokens
        self.i = 0
        self.facts = facts

    def _peek(self):
        return self.tokens[self.i]

    def _next(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def _expect_op(self, ops: str):
        kind, value = self._peek()
        if kind == "op" and value in ops:
            self.i += 1
            return value
        raise ExpressionError(f"期望操作符 {ops!r}，实际 {value!r}")

    def parse(self):
        value = self._or()
        if self._peek()[0] != "end":
            raise ExpressionError(f"表达式末尾有多余内容: {self._peek()[1]!r}")
        return value

    def _or(self):
        value = self._and()
        while self._peek() in (("op", "||"), ("word", "or")):
            self._next()
            rhs = self._and()
            value = bool(value) or bool(rhs)
        return value

    def _and(self):
        value = self._not()
        while self._peek() in (("op", "&&"), ("word", "and")):
            self._next()
            rhs = self._not()
            value = bool(value) and bool(rhs)
        return value

    def _not(self):
        if self._peek() in (("op", "!"), ("word", "not")):
            self._next()
            return not bool(self._not())
        return self._comparison()

    def _comparison(self):
        left = self._add()
        kind, value = self._peek()
        if kind == "op" and value in ("==", "!=", ">", "<", ">=", "<="):
            self._next()
            right = self._add()
            if value == "==":
                return left == right
            if value == "!=":
                return left != right
            if value == ">":
                return left > right
            if value == "<":
                return left < right
            if value == ">=":
                return left >= right
            return left <= right
        if (kind, value) == ("word", "in"):
            self._next()
            right = self._add()
            return left in right
        return left

    def _add(self):
        value = self._mul()
        while True:
            kind, value_op = self._peek()
            if kind == "op" and value_op in ("+", "-"):
                self._next()
                rhs = self._mul()
                value = value + rhs if value_op == "+" else value - rhs
            else:
                return value

    def _mul(self):
        value = self._unary()
        while True:
            kind, value_op = self._peek()
            if kind == "op" and value_op in ("*", "/", "%"):
                self._next()
                rhs = self._unary()
                if value_op == "*":
                    value = value * rhs
                elif value_op == "/":
                    value = value / rhs
                else:
                    value = value % rhs
            else:
                return value

    def _unary(self):
        kind, value = self._peek()
        if kind == "op" and value in ("-", "+"):
            self._next()
            num = self._unary()
            return -num if value == "-" else num
        return self._postfix()

    def _postfix(self):
        return self._primary()

    def _primary(self):
        kind, value = self._next()
        if kind == "num":
            return float(value) if "." in value else int(value)
        if kind == "str":
            return value[1:-1]
        if kind == "op" and value == "(":
            inner = self._or()
            self._expect_op(")")
            return inner
        if kind == "op" and value == "[":
            items = []
            if self._peek() != ("op", "]"):
                items.append(self._or())
                while self._peek() == ("op", ","):
                    self._next()
                    items.append(self._or())
            self._expect_op("]")
            return items
        if kind == "word":
            lowered = value.lower()
            if value in ("True", "true"):
                return True
            if value in ("False", "false"):
                return False
            if value in ("None", "null"):
                return None
            if lowered in ("and", "or", "not", "in"):
                raise ExpressionError(f"关键字位置错误: {value!r}")
            # 点分路径（facts 引用）：a.b.c
            path = [value]
            while self._peek() == ("op", "."):
                self._next()
                kind2, value2 = self._next()
                if kind2 != "word":
                    raise ExpressionError(f"属性访问后必须是标识符，实际 {value2!r}")
                path.append(value2)
            resolved = _resolve_path(self.facts, path)
            if resolved is not _MISSING:
                return resolved
            if _CAPS_WORD_RE.match(value):
                # 全大写裸标识符 → 枚举字符串常量（判据表达式惯例）
                return value
            raise ExpressionError(f"未知标识符: {'.'.join(path)}")
        raise ExpressionError(f"意外的记号: {value!r}")


_MISSING = object()


def _resolve_path(facts: dict, path: list):
    node: Any = facts
    for part in path:
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return _MISSING
    return node


def evaluate_expression(text: str, facts: dict) -> Any:
    """求值判据表达式（无 eval/exec；标识符只解析到 facts 与大写枚举常量）。"""
    return _ExprParser(_tokenize(text), facts).parse()


# ===========================================================================
# Eval 上下文与执行器
# ===========================================================================
class EvalContext:
    """执行器运行上下文（ctx）：路径解析 + YAML 加载 + contracts 访问。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve(self, relpath: str) -> Path:
        return (self.root / relpath).resolve()

    def load_yaml(self, relpath: str) -> Any:
        with self.resolve(relpath).open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def load_jsonl(self, relpath: str) -> list:
        records = []
        with self.resolve(relpath).open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                line = line.strip()
                if line:
                    records.append((line_no, json.loads(line)))
        return records


def _strip_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(item) for item in value]
    return value


class OntologyValidationError(ValueError):
    """本体/规程数据结构校验失败（负向拒绝用）。"""


def validate_ontology_data(data: Any, origin: str) -> None:
    """轻量本体校验：枚举封闭性 + 规则/动作必须有 ID（负向拒绝执行器用）。"""
    if not isinstance(data, dict):
        raise OntologyValidationError(f"{origin}: 顶层必须是对象")
    if "enums" in data:
        for name, values in data["enums"].items():
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise OntologyValidationError(f"{origin}: enums.{name} 必须为字符串列表")
    for section in ("actions", "rules"):
        for item in data.get(section) or []:
            if not isinstance(item, dict) or not item.get("id"):
                raise OntologyValidationError(f"{origin}: {section}[] 缺 id")
            if section == "actions":
                from contracts import PolicyDecision, RiskLevel

                try:
                    RiskLevel(item.get("risk_level"))
                except ValueError:
                    raise OntologyValidationError(
                        f"{origin}: 动作 {item.get('id')} risk_level 枚举越界: {item.get('risk_level')!r}"
                    ) from None
                try:
                    PolicyDecision(item.get("default_policy"))
                except ValueError:
                    raise OntologyValidationError(
                        f"{origin}: 动作 {item.get('id')} default_policy 枚举越界: {item.get('default_policy')!r}"
                    ) from None


# --- 内置执行器（按 form 注册）--------------------------------------------
def exec_contract(case: dict, ctx: EvalContext) -> dict:
    """冻结结构 round-trip / 预期拒绝。params: {structure, op, payload}"""
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    structure = params.get("structure")
    op = params.get("op", "roundtrip")
    payload = params.get("payload")
    cls = STRUCTURES.get(structure or "")
    if cls is None:
        return {"passed": False, "detail": f"未知结构名: {structure!r}", "metrics": {}}
    if op == "roundtrip":
        try:
            obj = cls.from_dict(payload)
        except ContractValidationError as exc:
            return {"passed": False, "detail": f"{structure} 构造被拒: {exc}", "metrics": {}}
        back = _strip_none(obj.to_dict())
        want = _strip_none(payload)
        if back != want:
            keys_only_back = sorted(set(_flatten_keys(back)) - set(_flatten_keys(want)))
            keys_only_want = sorted(set(_flatten_keys(want)) - set(_flatten_keys(back)))
            detail = f"{structure} round-trip 不一致；仅返回侧有: {keys_only_back}；仅输入侧有: {keys_only_want}"
            return {"passed": False, "detail": detail, "metrics": {"structure": structure}}
        return {"passed": True, "detail": f"{structure} round-trip 逐字段一致", "metrics": {"structure": structure}}
    if op == "reject":
        try:
            cls.from_dict(payload)
        except ContractValidationError as exc:
            contains = expect.get("error_contains")
            if contains and contains not in str(exc):
                return {
                    "passed": False,
                    "detail": f"已拒绝但消息不含 {contains!r}: {exc}",
                    "metrics": {"structure": structure},
                }
            return {"passed": True, "detail": f"按预期拒绝: {exc}", "metrics": {"structure": structure}}
        return {"passed": False, "detail": "期望拒绝但构造成功", "metrics": {"structure": structure}}
    return {"passed": False, "detail": f"未知 op: {op!r}（roundtrip|reject）", "metrics": {}}


def _flatten_keys(value: Any, prefix: str = "") -> set:
    keys = set()
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            keys.add(path)
            keys |= _flatten_keys(item, path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            keys |= _flatten_keys(item, f"{prefix}[{index}]")
    return keys


def exec_state_transition(case: dict, ctx: EvalContext) -> dict:
    """状态迁移断言。params: {machine, table, checks: [{from, to, expect}]}"""
    params = case.get("params") or {}
    table_rel = params.get("table", "tests/fixtures/frozen_state_machines.yaml")
    machine = params.get("machine")
    checks = params.get("checks") or []
    if not machine or not checks:
        return {"passed": False, "detail": "params 需要 machine 与非空 checks", "metrics": {}}
    try:
        data = ctx.load_yaml(table_rel)
    except OSError as exc:
        return {"passed": False, "detail": f"迁移表无法读取: {exc}", "metrics": {}}
    machines = (data or {}).get("machines") or {}
    table = machines.get(machine)
    if table is None:
        return {"passed": False, "detail": f"迁移表中无状态机: {machine!r}", "metrics": {}}
    failures = []
    for index, check in enumerate(checks):
        src = check.get("from")
        dst = check.get("to")
        want = check.get("expect", "allowed")
        allowed = dst in (table.get(src) or [])
        if want == "allowed" and not allowed:
            failures.append(f"checks[{index}]: {src}→{dst} 应允许，实际拒绝")
        elif want == "rejected" and allowed:
            failures.append(f"checks[{index}]: {src}→{dst} 应拒绝，实际允许")
        elif want not in ("allowed", "rejected"):
            failures.append(f"checks[{index}]: expect 必须为 allowed|rejected")
    metrics = {"machine": machine, "checks": len(checks)}
    if failures:
        return {"passed": False, "detail": "; ".join(failures), "metrics": metrics}
    return {"passed": True, "detail": f"{machine} 状态机 {len(checks)} 项迁移断言全部成立", "metrics": metrics}


_TIGHTENS = {("ALLOW", "ASK"), ("ALLOW", "DENY"), ("ASK", "DENY")}


def exec_policy_decision(case: dict, ctx: EvalContext) -> dict:
    """策略三值（参照实现：缺省 Policy + 单向收紧 + 不可改清单）。

    params: {capability, actions_table, role_override?, actor_role?}
    expect: {decision, override_rejected?}
    """
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    capability = str(params.get("capability") or "")
    action_id = capability.split("@", 1)[0]
    table_rel = params.get("actions_table", "ontology/actions.yaml")
    data = ctx.load_yaml(table_rel) or {}
    actions = {action.get("id"): action for action in (data.get("actions") or [])}
    action = actions.get(action_id)
    if action is None:
        return {"passed": False, "detail": f"动作表无此动作: {action_id!r}", "metrics": {}}
    base = action.get("default_policy")
    locked = bool(action.get("policy_locked"))
    override = params.get("role_override")
    override_rejected = False
    if override is None or override == base:
        decision = base
    elif locked:
        decision = base
        override_rejected = True
    elif (base, override) in _TIGHTENS:
        decision = override
    else:
        decision = base
        override_rejected = True
    metrics = {
        "capability": capability,
        "decision": decision,
        "override_rejected": override_rejected,
        "policy_locked": locked,
    }
    want_decision = expect.get("decision")
    if want_decision is not None and decision != want_decision:
        return {"passed": False, "detail": f"判定 {decision!r} != 期望 {want_decision!r}", "metrics": metrics}
    want_rejected = expect.get("override_rejected")
    if want_rejected is not None and override_rejected != bool(want_rejected):
        return {
            "passed": False,
            "detail": f"override_rejected={override_rejected} != 期望 {want_rejected}",
            "metrics": metrics,
        }
    return {"passed": True, "detail": f"决策={decision}（base={base}, locked={locked}）", "metrics": metrics}


def exec_idempotency(case: dict, ctx: EvalContext) -> dict:
    """幂等（参照实现：同 idempotency_key 返回首个结果，不重复执行）。

    params: {requests: [ActionRequest dict, ...]}
    expect: {same_action_id: true, executions: n}
    """
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    requests = params.get("requests") or []
    if len(requests) < 2:
        return {"passed": False, "detail": "idempotency 需要 ≥2 个重复请求", "metrics": {}}
    table: dict = {}
    executions = 0
    results: list = []
    for index, payload in enumerate(requests):
        try:
            request = STRUCTURES["ActionRequest"].from_dict(payload)
        except ContractValidationError as exc:
            return {"passed": False, "detail": f"requests[{index}] 契约校验失败: {exc}", "metrics": {}}
        key = request.idempotency_key
        if key in table:
            results.append(table[key])
        else:
            executions += 1
            record = {"action_id": request.action_id, "status": "SUCCEEDED"}
            table[key] = record
            results.append(record)
    first = results[0]
    same_action = all(r["action_id"] == first["action_id"] for r in results)
    metrics = {"requests": len(requests), "executions": executions, "distinct_keys": len(table)}
    problems = []
    if expect.get("same_action_id") and not same_action:
        problems.append("重复请求返回了不同 action_id")
    if "executions" in expect and executions != expect["executions"]:
        problems.append(f"执行次数 {executions} != 期望 {expect['executions']}")
    if problems:
        return {"passed": False, "detail": "; ".join(problems), "metrics": metrics}
    detail = f"{len(requests)} 请求 / {len(table)} 个幂等键，仅执行 {executions} 次，结果一致"
    return {"passed": True, "detail": detail, "metrics": metrics}


def exec_expression(case: dict, ctx: EvalContext) -> dict:
    """表达式判据。params: {expression, facts}；expect: {result} 或 {error_contains}"""
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    expression = params.get("expression") or ""
    facts = params.get("facts") or {}
    try:
        value = evaluate_expression(expression, facts)
    except ExpressionError as exc:
        contains = expect.get("error_contains")
        if contains and contains in str(exc):
            return {"passed": True, "detail": f"表达式按预期报错: {exc}", "metrics": {"expression": expression}}
        return {"passed": False, "detail": f"表达式求值失败: {exc}", "metrics": {"expression": expression}}
    metrics = {"expression": expression, "value": value if isinstance(value, (bool, int, float, str)) else str(value)}
    if "error_contains" in expect:
        return {"passed": False, "detail": "期望表达式报错但求值成功", "metrics": metrics}
    if "result" in expect:
        if value == expect["result"] and isinstance(value, bool):
            return {"passed": True, "detail": f"表达式求值 = {value}", "metrics": metrics}
        return {"passed": False, "detail": f"表达式求值 {value!r} != 期望 {expect['result']!r}", "metrics": metrics}
    if isinstance(value, bool):
        return {"passed": value, "detail": f"表达式求值 = {value}（truthy 判定）", "metrics": metrics}
    return {"passed": False, "detail": f"表达式结果非布尔: {value!r}", "metrics": metrics}


def exec_negative_rejection(case: dict, ctx: EvalContext) -> dict:
    """负向拒绝。params: {attempt, structure?, payload?, file?}；expect: {error_contains?}

    attempt: contract_load | event_append | ontology_load | regulation_load
    """
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    attempt = params.get("attempt")
    error: Exception | None = None
    try:
        if attempt == "contract_load":
            cls = STRUCTURES.get(params.get("structure") or "")
            if cls is None:
                return {"passed": False, "detail": f"未知结构: {params.get('structure')!r}", "metrics": {}}
            cls.from_dict(params.get("payload"))
        elif attempt == "event_append":
            STRUCTURES["EventRecord"].from_dict(params.get("payload"))
        elif attempt in ("ontology_load", "regulation_load"):
            relpath = params.get("file")
            if not relpath:
                return {"passed": False, "detail": "ontology_load/regulation_load 需要 params.file", "metrics": {}}
            data = ctx.load_yaml(relpath)
            validate_ontology_data(data, relpath)
        else:
            return {"passed": False, "detail": f"未知 attempt: {attempt!r}", "metrics": {}}
    except (ContractValidationError, OntologyValidationError) as exc:
        error = exc
    except Exception as exc:  # 其他异常也视为"拒绝"，但仍按 error_contains 校验
        error = exc
    metrics = {"attempt": attempt}
    if error is None:
        return {"passed": False, "detail": "期望拒绝但未拒绝", "metrics": metrics}
    contains = expect.get("error_contains")
    if contains and contains not in str(error):
        return {"passed": False, "detail": f"已拒绝但消息不含 {contains!r}: {error}", "metrics": metrics}
    return {"passed": True, "detail": f"按预期拒绝（{type(error).__name__}）: {error}", "metrics": metrics}


def exec_performance(case: dict, ctx: EvalContext) -> dict:
    """性能门槛。params: {workload, iterations?, payload?}；expect: {max_ms}

    workload: ontology_load_all | contract_roundtrip | event_validate
    计时用 time.perf_counter（MONOTONIC 语义；禁止墙钟判价与此无关——此处非电价判定）。
    """
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    workload = params.get("workload")
    iterations = int(params.get("iterations", 1))
    max_ms = expect.get("max_ms")
    if not workload or max_ms is None:
        return {"passed": False, "detail": "params.workload 与 expect.max_ms 必填", "metrics": {}}

    def workload_ontology_load_all() -> None:
        for _ in range(iterations):
            for rel in ONTOLOGY_FILES + REGULATION_FILES:
                ctx.load_yaml(rel)

    def workload_contract_roundtrip() -> None:
        payload = params.get("payload")
        cls = STRUCTURES.get(params.get("structure") or "ActionRequest")
        for _ in range(iterations):
            cls.from_dict(payload).to_dict()

    def workload_event_validate() -> None:
        payload = params.get("payload")
        for _ in range(iterations):
            STRUCTURES["EventRecord"].from_dict(payload)

    workloads = {
        "ontology_load_all": workload_ontology_load_all,
        "contract_roundtrip": workload_contract_roundtrip,
        "event_validate": workload_event_validate,
    }
    fn = workloads.get(workload)
    if fn is None:
        return {"passed": False, "detail": f"未知 workload: {workload!r}", "metrics": {}}
    start = time.perf_counter()
    try:
        fn()
    except Exception as exc:
        return {"passed": False, "detail": f"workload 执行失败: {exc}", "metrics": {}}
    measured_ms = (time.perf_counter() - start) * 1000.0
    metrics = {"workload": workload, "iterations": iterations, "measured_ms": round(measured_ms, 2), "max_ms": max_ms}
    if measured_ms <= float(max_ms):
        return {
            "passed": True,
            "detail": f"{workload}×{iterations} 用时 {measured_ms:.1f}ms ≤ {max_ms}ms",
            "metrics": metrics,
        }
    return {
        "passed": False,
        "detail": f"{workload}×{iterations} 用时 {measured_ms:.1f}ms > {max_ms}ms 门槛",
        "metrics": metrics,
    }


def exec_event_sequence(case: dict, ctx: EvalContext) -> dict:
    """事件序回放断言。params: {file, pattern, allow_extra?}

    pattern：事件 type 字面量的有序序列；``*`` 通配单个事件。
    JSONL 中每条记录按 contracts.EventRecord 校验（缺 trace_id 即拒绝）。
    expect: {matched: true} 或 {error_contains}
    """
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    relpath = params.get("file")
    pattern = params.get("pattern") or []
    if not relpath:
        return {"passed": False, "detail": "params.file 必填", "metrics": {}}
    try:
        records = ctx.load_jsonl(relpath)
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "detail": f"事件文件无法读取: {exc}", "metrics": {}}
    event_types: list = []
    try:
        for line_no, payload in records:
            record = STRUCTURES["EventRecord"].from_dict(payload)
            event_types.append(record.type.value)
    except ContractValidationError as exc:
        contains = expect.get("error_contains")
        if contains and contains in str(exc):
            return {"passed": True, "detail": f"事件文件按预期被拒: {exc}", "metrics": {"file": relpath}}
        return {"passed": False, "detail": f"事件文件校验失败: {exc}", "metrics": {"file": relpath}}

    cursor = 0
    misses = []
    for want in pattern:
        if want == "*":
            if cursor >= len(event_types):
                misses.append(f"通配符 * 无可匹配事件（模式 {pattern}）")
                continue
            cursor += 1
            continue
        found = None
        for idx in range(cursor, len(event_types)):
            if event_types[idx] == want:
                found = idx
                break
        if found is None:
            misses.append(f"事件 {want!r} 未按序出现（模式 {pattern}）")
            cursor = len(event_types)
            break
        cursor = found + 1
    metrics = {"file": relpath, "events": len(event_types), "pattern": pattern}
    if misses:
        return {"passed": False, "detail": "; ".join(misses), "metrics": metrics}
    return {
        "passed": True,
        "detail": f"事件序匹配：{len(event_types)} 条事件符合模式（{len(pattern)} 段）",
        "metrics": metrics,
    }


BUILTIN_EXECUTORS: dict = {
    "contract": exec_contract,
    "state_transition": exec_state_transition,
    "policy_decision": exec_policy_decision,
    "idempotency": exec_idempotency,
    "expression": exec_expression,
    "negative_rejection": exec_negative_rejection,
    "performance": exec_performance,
    "event_sequence": exec_event_sequence,
}


# ===========================================================================
# Suite schema 校验
# ===========================================================================
def validate_suite_schema(data: Any, source: str) -> list:
    """校验 suite YAML；返回错误列表（空 = 通过）。"""
    errors: list = []
    if not isinstance(data, dict):
        return [f"{source}: 顶层必须是对象"]
    for key in ("suite", "title", "spec_ref", "spec_hash", "cases"):
        if key not in data:
            errors.append(f"{source}: 缺 suite 级字段 {key}")
    if errors:
        return errors
    if data["suite"] not in MODULES:
        errors.append(f"{source}: suite 必须是 {'/'.join(MODULES)}，实际 {data['suite']!r}")
    if not isinstance(data["cases"], list) or not data["cases"]:
        errors.append(f"{source}: cases 必须为非空列表")
        return errors
    executors = data.get("executors") or []
    if not isinstance(executors, list):
        errors.append(f"{source}: executors 必须为列表")
    for index, executor in enumerate(executors):
        if not isinstance(executor, dict) or not executor.get("module"):
            errors.append(f"{source}: executors[{index}] 需要 module 字段")
    for index, case in enumerate(data["cases"]):
        prefix = f"{source}: cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix} 必须为对象")
            continue
        case_id = case.get("id")
        if not case_id or not CASE_ID_RE.match(str(case_id)):
            errors.append(f"{prefix}: id 缺失或不符合 EVAL-M<模块>-<序号>-(P|N<n>) 格式: {case_id!r}")
        for key in ("spec", "title", "form", "params"):
            if key not in case:
                errors.append(f"{prefix}({case_id}): 缺字段 {key}")
        if "form" in case and case["form"] not in EVAL_FORMS:
            errors.append(f"{prefix}({case_id}): form 越界 {case['form']!r}（允许: {'/'.join(EVAL_FORMS)}）")
        if "params" in case and not isinstance(case["params"], dict):
            errors.append(f"{prefix}({case_id}): params 必须为对象")
        if "expect" in case and not isinstance(case["expect"], dict):
            errors.append(f"{prefix}({case_id}): expect 必须为对象")
        if "executor" in case and not isinstance(case["executor"], str):
            errors.append(f"{prefix}({case_id}): executor 必须为字符串（插件执行器名）")
        if "skip" in case and not (isinstance(case["skip"], dict) and case["skip"].get("reason")):
            errors.append(f"{prefix}({case_id}): skip 必须为 {{reason: ...}}")
    return errors


def compute_spec_hash(spec_ref: Any) -> str:
    """spec_ref（字符串或列表）按序拼接文件字节取 sha256 —— 01§6 spec_hash 口径。"""
    files = [spec_ref] if isinstance(spec_ref, str) else list(spec_ref or [])
    digest = hashlib.sha256()
    for rel in files:
        digest.update((ROOT / rel).read_bytes())
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ===========================================================================
# 运行
# ===========================================================================
def load_plugin_executors(suite: dict, source: str) -> tuple:
    """加载 suite.executors 声明的插件模块；返回 (注册表 dict, 错误列表)。"""
    registry: dict = {}
    errors: list = []
    for index, entry in enumerate(suite.get("executors") or []):
        module_name = entry.get("module")
        if not module_name:
            continue
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{source}: executors[{index}] 模块 {module_name} 导入失败: {exc}")
            continue
        table = getattr(module, "EXECUTORS", None)
        if not isinstance(table, dict) or not table:
            errors.append(f"{source}: executors[{index}] 模块 {module_name} 未暴露 EXECUTORS 字典")
            continue
        for name, fn in table.items():
            if not callable(fn):
                errors.append(f"{source}: 插件执行器 {module_name}.{name} 不可调用")
                continue
            registry[name] = fn
    return registry, errors


def run_case(case: dict, plugin_registry: dict, ctx: EvalContext) -> dict:
    """执行单条用例，返回结果记录。"""
    started = time.perf_counter()
    base = {
        "id": case.get("id"),
        "spec": case.get("spec"),
        "title": case.get("title"),
        "form": case.get("form"),
        "executor": case.get("executor") or case.get("form"),
    }
    if "skip" in case:
        return {**base, "status": "SKIPPED", "passed": False,
                "detail": f"跳过：{case['skip'].get('reason', '')}", "duration_ms": 0.0, "metrics": {}}
    form = case.get("form")
    executor_name = case.get("executor")
    if executor_name:
        fn = plugin_registry.get(executor_name)
        if fn is None:
            return {**base, "status": "FAILED", "passed": False,
                    "detail": f"插件执行器未注册: {executor_name!r}", "duration_ms": 0.0, "metrics": {}}
    else:
        fn = BUILTIN_EXECUTORS.get(form)
        if fn is None:
            return {**base, "status": "FAILED", "passed": False,
                    "detail": f"form 无内置执行器: {form!r}", "duration_ms": 0.0, "metrics": {}}
    try:
        outcome = fn(case, ctx)
    except Exception as exc:  # noqa: BLE001 - 执行器异常按失败用例记录
        return {**base, "status": "FAILED", "passed": False,
                "detail": f"执行器异常: {type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}",
                "duration_ms": round((time.perf_counter() - started) * 1000.0, 2), "metrics": {}}
    passed = bool(outcome.get("passed"))
    return {**base, "status": "PASSED" if passed else "FAILED", "passed": passed,
            "detail": str(outcome.get("detail", "")),
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
            "metrics": outcome.get("metrics") or {}}


def run_module_suite(module: str, ctx: EvalContext) -> dict:
    """运行单个模块套件；文件缺失 → PENDING（不算失败，待模块交付补齐）。"""
    suite_rel = SUITE_TEMPLATE.format(module=module)
    suite_path = ROOT / suite_rel
    report: dict = {"module": module, "suite_file": suite_rel, "status": "PENDING",
                    "spec_ref": None, "spec_hash": None, "eval_hash": None,
                    "cases": [], "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0}}
    if not suite_path.exists():
        return report
    report["eval_hash"] = sha256_file(suite_path)
    try:
        data = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        report["status"] = "INVALID"
        report["cases"] = [{"id": None, "status": "FAILED", "passed": False,
                            "detail": f"suite YAML 解析失败: {exc}", "title": suite_rel,
                            "spec": None, "form": None, "executor": None,
                            "duration_ms": 0.0, "metrics": {}}]
        _fill_summary(report)
        return report
    schema_errors = validate_suite_schema(data, suite_rel)
    if schema_errors:
        report["status"] = "INVALID"
        report["cases"] = [{"id": None, "status": "FAILED", "passed": False,
                            "detail": "schema 校验失败: " + "; ".join(schema_errors),
                            "title": suite_rel, "spec": None, "form": None, "executor": None,
                            "duration_ms": 0.0, "metrics": {}}]
        _fill_summary(report)
        return report
    declared_spec_hash = data["spec_hash"]
    actual_spec_hash = compute_spec_hash(data["spec_ref"])
    report["spec_ref"] = data["spec_ref"]
    report["spec_hash"] = actual_spec_hash
    if declared_spec_hash != actual_spec_hash:
        report["status"] = "SPEC_DRIFT"
        report["cases"] = [{"id": None, "status": "FAILED", "passed": False,
                            "detail": (
                                "SPEC 与 EVAL 不一致（01§6）：spec_hash 声明值与重算值不同——"
                                "规格已变更而用例未重生成登记。"
                                f"声明={declared_spec_hash} 重算={actual_spec_hash}"
                            ),
                            "title": suite_rel, "spec": None, "form": None, "executor": None,
                            "duration_ms": 0.0, "metrics": {}}]
        _fill_summary(report)
        return report
    plugin_registry, plugin_errors = load_plugin_executors(data, suite_rel)
    if plugin_errors:
        report["status"] = "INVALID"
        report["cases"] = [{"id": None, "status": "FAILED", "passed": False,
                            "detail": "; ".join(plugin_errors), "title": suite_rel,
                            "spec": None, "form": None, "executor": None,
                            "duration_ms": 0.0, "metrics": {}}]
        _fill_summary(report)
        return report
    report["status"] = "RAN"
    for case in data["cases"]:
        report["cases"].append(run_case(case, plugin_registry, ctx))
    _fill_summary(report)
    return report


def _fill_summary(report: dict) -> None:
    cases = report["cases"]
    report["summary"] = {
        "total": len(cases),
        "passed": sum(1 for c in cases if c.get("status") == "PASSED"),
        "failed": sum(1 for c in cases if c.get("status") == "FAILED"),
        "skipped": sum(1 for c in cases if c.get("status") == "SKIPPED"),
    }


def check_directory_integrity() -> tuple:
    """目录完整性（严格校验，不静默创建）：返回 (missing 列表, 检查项数)。"""
    missing: list = []
    checked = 0
    for rel in REQUIRED_DIRS:
        checked += 1
        if not (ROOT / rel).is_dir():
            missing.append(f"dir:{rel}")
    for rel in REQUIRED_FILES:
        checked += 1
        if not (ROOT / rel).is_file():
            missing.append(f"file:{rel}")
    return missing, checked


def check_schema_doc() -> list:
    """EVAL-SCHEMA.md 必须登记全部 Eval 形态。"""
    if not SCHEMA_DOC.exists():
        return [f"{SCHEMA_DOC.name} 不存在"]
    text = SCHEMA_DOC.read_text(encoding="utf-8")
    missing = [form for form in EVAL_FORMS if form not in text]
    if missing:
        return [f"EVAL-SCHEMA.md 未登记形态: {', '.join(missing)}"]
    return []


def run_selftest(ctx: EvalContext) -> dict:
    """--selftest：schema 自检 + 隔离断言 + 目录完整性。"""
    report: dict = {"schema_selfcheck": {"ok": True, "errors": []}}
    errors: list = []
    # 1) 目录完整性
    missing, checked = check_directory_integrity()
    report["integrity"] = {"ok": not missing, "missing": missing, "checked": checked}
    if missing:
        errors.append(f"目录完整性缺失: {', '.join(missing)}")
    # 2) schema 自检：现行 suite 必须通过校验
    for module in MODULES:
        suite_path = ROOT / SUITE_TEMPLATE.format(module=module)
        if not suite_path.exists():
            continue
        data = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
        schema_errors = validate_suite_schema(data, suite_path.name)
        if schema_errors:
            errors.extend(schema_errors)
    # 3) schema 负样本必须被拒绝
    bad_samples = (
        ({"suite": "m0", "title": "x", "spec_ref": [], "spec_hash": "x", "cases": [{"spec": "s", "title": "t", "form": "contract", "params": {}}]},
         "cases[0]: id 缺失"),
        ({"suite": "m0", "title": "x", "spec_ref": [], "spec_hash": "x", "cases": [{"id": "EVAL-M0-01-P", "spec": "s", "title": "t", "form": "no_such_form", "params": {}}]},
         "form 越界"),
        ({"suite": "m0", "title": "x", "spec_ref": [], "spec_hash": "x", "cases": [{"id": "EVAL-M0-01-P", "spec": "s", "title": "t", "form": "contract"}]},
         "缺字段 params"),
        ({"suite": "m9", "title": "x", "spec_ref": [], "spec_hash": "x", "cases": [{"id": "EVAL-M9-01-P", "spec": "s", "title": "t", "form": "contract", "params": {}}]},
         "suite 必须是"),
        ({"suite": "m0", "title": "x", "spec_ref": [], "spec_hash": "x", "cases": [{"id": "BAD-ID", "spec": "s", "title": "t", "form": "contract", "params": {}}]},
         "id 缺失或不符合"),
    )
    for sample, hint in bad_samples:
        found = validate_suite_schema(sample, "selftest-bad-sample")
        if not any(hint in err for err in found):
            errors.append(f"schema 负样本未被拒绝（应含 {hint!r}）: {found}")
    # 4) EVAL-SCHEMA.md 登记七类形态
    doc_errors = check_schema_doc()
    report["schema_selfcheck"]["errors"] = list(errors) + doc_errors
    report["schema_selfcheck"]["ok"] = not (errors or doc_errors)
    if doc_errors:
        errors.extend(doc_errors)
    report["ok"] = not errors
    report["errors"] = errors
    return report


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ascii_summary(mode: str, isolation_ok: bool, module_reports: list, extra: dict, ok: bool) -> str:
    ran = [r for r in module_reports if r["status"] == "RAN"]
    pending = [r for r in module_reports if r["status"] == "PENDING"]
    cases_total = sum(r["summary"]["total"] for r in module_reports)
    cases_passed = sum(r["summary"]["passed"] for r in module_reports)
    cases_failed = sum(r["summary"]["failed"] for r in module_reports)
    cases_skipped = sum(r["summary"]["skipped"] for r in module_reports)
    parts = [
        f"EVALS mode={mode}",
        f"isolation={'OK' if isolation_ok else 'VIOLATION'}",
        f"modules={len(ran)}/{len(module_reports)} pending={len(pending)}",
        f"cases={cases_passed}/{cases_total} failed={cases_failed} skipped={cases_skipped}",
    ]
    for key, value in extra.items():
        parts.append(f"{key}={value}")
    parts.append(f"result={'PASS' if ok else 'FAIL'}")
    return " ".join(parts)


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="全项目 EVAL 总 runner（先隔离断言，再执行用例）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--selftest", action="store_true", help="schema 自检 + 隔离断言 + 目录完整性")
    group.add_argument("--module", metavar="m0..m7|all", help="执行 tests/test_m<id>.yaml")
    args = parser.parse_args(argv)

    ctx = EvalContext(ROOT)
    mode: str
    if args.selftest:
        mode = "selftest"
    elif args.module == "all":
        mode = "all"
    elif args.module in MODULES:
        mode = args.module
    else:
        parser.error(f"--module 必须为 {'/'.join(MODULES)} 或 all")
        return 2  # pragma: no cover

    # 纪律：每次运行先跑隔离断言
    hits = ci_isolation.run_isolation(ROOT)
    isolation_ok = not hits

    if not RESULTS_PATH.parent.exists():
        RESULTS_PATH.parent.mkdir(parents=True)

    module_reports: list = []
    extra: dict = {}
    overall_ok = isolation_ok

    if args.selftest:
        selftest = run_selftest(ctx)
        overall_ok = overall_ok and bool(selftest["ok"])
        extra = {"integrity": "OK" if selftest["integrity"]["ok"] else "MISSING",
                 "schema": "OK" if selftest["schema_selfcheck"]["ok"] else "BAD"}
        payload = {
            "generated_at": utc_now_iso(), "mode": mode,
            "isolation": {"ok": isolation_ok, "hits": [{"file": h.rel_path, "line": h.line_no, "matched": h.matched} for h in hits]},
            "selftest": selftest, "modules": module_reports,
            "summary": {"cases_total": 0, "cases_passed": 0, "cases_failed": 0, "cases_skipped": 0},
        }
    else:
        targets = list(MODULES) if args.module == "all" else [args.module]
        for module in targets:
            module_reports.append(run_module_suite(module, ctx))
        cases_total = sum(r["summary"]["total"] for r in module_reports)
        cases_failed = sum(r["summary"]["failed"] for r in module_reports)
        suite_level_bad = sum(1 for r in module_reports if r["status"] in ("INVALID", "SPEC_DRIFT"))
        overall_ok = isolation_ok and cases_failed == 0 and suite_level_bad == 0
        payload = {
            "generated_at": utc_now_iso(), "mode": mode,
            "isolation": {"ok": isolation_ok, "hits": [{"file": h.rel_path, "line": h.line_no, "matched": h.matched} for h in hits]},
            "modules": module_reports,
            "summary": {
                "modules_total": len(module_reports),
                "modules_pending": sum(1 for r in module_reports if r["status"] == "PENDING"),
                "cases_total": cases_total,
                "cases_passed": sum(r["summary"]["passed"] for r in module_reports),
                "cases_failed": cases_failed,
                "cases_skipped": sum(r["summary"]["skipped"] for r in module_reports),
            },
        }

    RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(ascii_summary(mode, isolation_ok, module_reports, extra, overall_ok))
    print(f"details -> {RESULTS_PATH.relative_to(ROOT).as_posix()}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
