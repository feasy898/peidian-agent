# -*- coding: utf-8 -*-
"""contracts 的 EVAL 执行器插件（run_evals.py 插件机制的参考实现）。

注册方式（tests/test_m<id>.yaml）::

    executors:
      - module: contracts.eval_plugin   # import 路径（sys.path 含 src/）

插件契约：模块必须暴露 ``EXECUTORS: dict[str, callable]``；
执行器签名 ``fn(case: dict, ctx) -> dict``，返回::

    {"passed": bool, "detail": str, "metrics": dict}

本插件的执行器均为"数据 vs 规格"机械核对（specs/00-ontology.md 与
ADDENDUM 的表格在下方独立转写），不偏向任何业务模块。
"""
from __future__ import annotations

from typing import Any

import yaml

from contracts import (
    ContractValidationError,
    PolicyDecision,
    RiskLevel,
    STRUCTURES,
)

__all__ = ["EXECUTORS"]

# ---------------------------------------------------------------------------
# 00-ontology.md §1.3 动作表（独立转写，用作双写校验基准）
# id -> (risk_level, reversible, default_policy, policy_locked)
# ---------------------------------------------------------------------------
EXPECTED_ACTIONS = {
    "query.measurement": ("LOW", False, "ALLOW", False),
    "query.asset": ("LOW", False, "ALLOW", False),
    "query.regulation": ("LOW", False, "ALLOW", False),
    "analyze.load_forecast": ("LOW", False, "ALLOW", False),
    "analyze.power_quality": ("LOW", False, "ALLOW", False),
    "analyze.transformer_economy": ("LOW", False, "ALLOW", False),
    "analyze.demand_forecast": ("LOW", False, "ALLOW", False),
    "write.report": ("LOW", True, "ALLOW", False),
    "create.work_order": ("MEDIUM", True, "ALLOW", False),
    "create.switch_order": ("MEDIUM", True, "ALLOW", False),
    "create.inspection_record": ("MEDIUM", True, "ALLOW", False),
    "execute.remote_control": ("HIGH", False, "ASK", True),
    "execute.capacitor_switch": ("HIGH", True, "ASK", False),
    "modify.protection_setting": ("CRITICAL", False, "DENY", True),
    "modify.asset_history": ("CRITICAL", False, "DENY", True),
    "bypass.approval": ("CRITICAL", False, "DENY", True),
}

# 00 §1.4 / ADDENDUM §A 要求的规程条款 ID 清单（独立转写）
EXPECTED_REGULATIONS = {
    "REG-SAFE": {
        "SAFE-TWO-TICKET", "SAFE-ISSUE-HUMAN", "SAFE-ORDER-SEQ",
        "SAFE-MAINTAIN-ISO", "SAFE-SINGLE-OP",
    },
    "REG-COMM": {
        "COMM-TARIF-SYNC", "COMM-PF-BONUS", "COMM-DEMAND-CHARGE", "COMM-TOU-ARBITRAGE",
    },
    "REG-TECH": {
        "PHYS-TX-LOAD", "PHYS-V-RANGE", "PHYS-THD", "PHYS-PF",
        "PHYS-DEMAND", "PHYS-BESS-SOC",
    },
    "REG-OP": {
        "SAFE-OP-TWO-TICKET", "SAFE-OP-REMOTE", "SAFE-OP-MAINTAIN",
        "OP-QCOMP-CAP", "OP-DEMAND-LIMIT",
    },
}

EXPECTED_RULES_PHYSICAL = {
    "PHYS-TX-LOAD", "PHYS-V-RANGE", "PHYS-THD", "PHYS-PF",
    "PHYS-DEMAND", "PHYS-BESS-SOC",
}
EXPECTED_RULES_SAFETY = {
    "SAFE-TWO-TICKET", "SAFE-ISSUE-HUMAN", "SAFE-ORDER-SEQ",
    "SAFE-MAINTAIN-ISO", "SAFE-SINGLE-OP",
}
EXPECTED_RULES_COMMERCIAL = {
    "COMM-TARIF-SYNC", "COMM-PF-BONUS", "COMM-DEMAND-CHARGE", "COMM-TOU-ARBITRAGE",
}

_OPERATOR_ROLES = {"值班员", "调度员", "签发人", "审批人"}


def _result(passed: bool, detail: str, metrics: dict | None = None) -> dict:
    return {"passed": passed, "detail": detail, "metrics": metrics or {}}


def _load_yaml(ctx: Any, relpath: str) -> Any:
    return ctx.load_yaml(relpath)


# ---------------------------------------------------------------------------
# 执行器：contracts.roundtrip —— 冻结结构 round-trip（插件路径演示）
# ---------------------------------------------------------------------------
def exec_roundtrip(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    structure = params.get("structure")
    payload = params.get("payload")
    expect = case.get("expect") or {}
    if structure not in STRUCTURES:
        return _result(False, f"未知结构名: {structure!r}")
    cls = STRUCTURES[structure]
    try:
        obj = cls.from_dict(payload)
    except ContractValidationError as exc:
        return _result(False, f"{structure}.from_dict 校验失败: {exc}")
    back = obj.to_dict()
    if _strip_none(back) != _strip_none(payload):
        return _result(False, f"{structure} round-trip 与输入不一致", {"structure": structure})
    if expect.get("error_contains"):
        return _result(False, "期望校验失败但构造成功")
    return _result(True, f"{structure} round-trip 一致（插件执行器）", {"structure": structure})


# ---------------------------------------------------------------------------
# 执行器：contracts.enum_closure —— contracts 枚举 vs ontology/enums.yaml
# ---------------------------------------------------------------------------
def exec_enum_closure(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    relpath = params.get("vocabulary_file", "ontology/enums.yaml")
    data = _load_yaml(ctx, relpath)
    yaml_enums = data.get("enums") or {}
    from contracts import CONTROLLED_VOCABULARY

    diffs: list = []
    for name, enum_cls in CONTROLLED_VOCABULARY.items():
        yaml_values = set(yaml_enums.get(name) or [])
        code_values = {member.value for member in enum_cls}
        if yaml_values != code_values:
            diffs.append(
                f"{name}: code={sorted(code_values)} yaml={sorted(yaml_values)}"
            )
    missing = sorted(set(yaml_enums) - set(CONTROLLED_VOCABULARY))
    if missing:
        diffs.append(f"enums.yaml 中存在 contracts 未登记的词表: {', '.join(missing)}")
    if diffs:
        return _result(False, "; ".join(diffs), {"checked": len(CONTROLLED_VOCABULARY)})
    return _result(
        True,
        f"受控词表一致（{len(CONTROLLED_VOCABULARY)} 组封闭集）",
        {"checked": len(CONTROLLED_VOCABULARY)},
    )


# ---------------------------------------------------------------------------
# 执行器：contracts.actions_table —— ontology/actions.yaml vs 00 §1.3 动作表
# ---------------------------------------------------------------------------
def exec_actions_table(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    relpath = params.get("actions_file", "ontology/actions.yaml")
    data = _load_yaml(ctx, relpath)
    actions = data.get("actions") or []
    problems: list = []
    by_id: dict = {}
    for action in actions:
        aid = action.get("id")
        if aid in by_id:
            problems.append(f"动作 ID 重复: {aid}")
        by_id[aid] = action
        try:
            RiskLevel(action.get("risk_level"))
        except ValueError:
            problems.append(f"{aid}: risk_level 越界 {action.get('risk_level')!r}")
        try:
            PolicyDecision(action.get("default_policy"))
        except ValueError:
            problems.append(f"{aid}: default_policy 越界 {action.get('default_policy')!r}")
        if not isinstance(action.get("reversible"), bool):
            problems.append(f"{aid}: reversible 必须为布尔")
        if not isinstance(action.get("policy_locked"), bool):
            problems.append(f"{aid}: policy_locked 必须为布尔")

    expected_ids = set(EXPECTED_ACTIONS)
    actual_ids = set(by_id)
    if actual_ids != expected_ids:
        problems.append(
            f"动作表与 00§1.3 不一致: 缺失={sorted(expected_ids - actual_ids)} "
            f"多出={sorted(actual_ids - expected_ids)}"
        )
    for aid, (risk, reversible, policy, locked) in EXPECTED_ACTIONS.items():
        action = by_id.get(aid)
        if action is None:
            continue
        if action.get("risk_level") != risk:
            problems.append(f"{aid}: risk_level {action.get('risk_level')!r} != {risk!r}")
        if action.get("reversible") != reversible:
            problems.append(f"{aid}: reversible {action.get('reversible')!r} != {reversible!r}")
        if action.get("default_policy") != policy:
            problems.append(f"{aid}: default_policy {action.get('default_policy')!r} != {policy!r}")
        if action.get("policy_locked") != locked:
            problems.append(f"{aid}: policy_locked {action.get('policy_locked')!r} != {locked!r}")

    if problems:
        return _result(False, "; ".join(problems), {"actions": len(actions)})
    return _result(
        True,
        f"动作表与 00§1.3 完全一致（{len(actions)} 条，含风险级/可逆性/缺省 Policy/不可改标记）",
        {"actions": len(actions)},
    )


# ---------------------------------------------------------------------------
# 执行器：contracts.rules_registry —— rules.yaml + regulations/ 条款覆盖核对
# ---------------------------------------------------------------------------
def exec_rules_registry(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    rules_rel = params.get("rules_file", "ontology/rules.yaml")
    regulations_dir = params.get("regulations_dir", "regulations")
    problems: list = []

    rules_data = _load_yaml(ctx, rules_rel)
    rules = rules_data.get("rules") or []
    by_category: dict = {}
    rule_ids = set()
    for rule in rules:
        rid = rule.get("id")
        if rid in rule_ids:
            problems.append(f"规则 ID 重复: {rid}")
        rule_ids.add(rid)
        by_category.setdefault(rule.get("category"), set()).add(rid)

    if by_category.get("physical") != EXPECTED_RULES_PHYSICAL:
        problems.append(f"physical 规则集不符: {sorted(by_category.get('physical') or [])}")
    if by_category.get("safety") != EXPECTED_RULES_SAFETY:
        problems.append(f"safety 规则集不符: {sorted(by_category.get('safety') or [])}")
    if by_category.get("commercial") != EXPECTED_RULES_COMMERCIAL:
        problems.append(f"commercial 规则集不符: {sorted(by_category.get('commercial') or [])}")

    for file_id, expected in EXPECTED_REGULATIONS.items():
        data = _load_yaml(ctx, f"{regulations_dir}/{file_id}.yaml")
        actual = {rule.get("id") for rule in (data.get("rules") or [])}
        missing = expected - actual
        if missing:
            problems.append(f"{file_id} 缺失条款: {sorted(missing)}")

    if problems:
        return _result(False, "; ".join(problems), {"rules": len(rule_ids)})
    return _result(
        True,
        f"规则注册表与四份规程条款覆盖完整（rules={len(rule_ids)}）",
        {"rules": len(rule_ids)},
    )


# ---------------------------------------------------------------------------
# 执行器：contracts.seed_check —— 园区种子实例完整性（引用/电价时段/曲线）
# ---------------------------------------------------------------------------
def _parse_hhmm(text: str) -> int:
    hours, _, minutes = str(text).partition(":")
    return int(hours) * 60 + int(minutes)


def exec_seed_check(case: dict, ctx: Any) -> dict:
    params = case.get("params") or {}
    relpath = params.get("seed_file", "ontology/seed.yaml")
    data = _load_yaml(ctx, relpath)
    problems: list = []

    park = data.get("park") or {}
    for key in ("id", "name", "tariff", "contract_capacity_kw"):
        if not park.get(key):
            problems.append(f"park.{key} 缺失")
    device_ids: set = set()
    substation_ids: set = set()
    for substation in park.get("substations") or []:
        sid = substation.get("id")
        if not sid:
            problems.append("配电房缺 id")
            continue
        if sid in substation_ids:
            problems.append(f"配电房 ID 重复: {sid}")
        substation_ids.add(sid)
        for device in substation.get("devices") or []:
            did = device.get("id")
            if not did or not device.get("type"):
                problems.append(f"设备缺 id/type: {device}")
                continue
            if did in device_ids:
                problems.append(f"设备 ID 重复: {did}")
            device_ids.add(did)

    known_ids = device_ids | substation_ids | {park.get("id")} | {
        op.get("id") for op in (data.get("operators") or []) if op.get("id")
    }
    for triple in data.get("relations") or []:
        if not (isinstance(triple, list) and len(triple) == 3):
            problems.append(f"关系三元组格式错误: {triple}")
            continue
        src, rel, dst = triple
        if src not in known_ids:
            problems.append(f"关系引用不存在的主体的 src: {src!r} ({rel})")
        if dst not in known_ids:
            problems.append(f"关系引用不存在的主体的 dst: {dst!r} ({rel})")

    op_ids = {op.get("id") for op in (data.get("operators") or [])}
    if len(op_ids) != len(data.get("operators") or []):
        problems.append("操作员 ID 重复")
    for operator in data.get("operators") or []:
        if operator.get("role") not in _OPERATOR_ROLES:
            problems.append(f"操作员角色越界: {operator}")

    schedule = data.get("price_schedule") or {}
    if park.get("tariff") and schedule.get("id") != park.get("tariff"):
        problems.append("price_schedule.id 与 park.tariff 不一致")
    periods = schedule.get("periods") or []
    cursor = 0
    for period in periods:
        if period.get("type") not in {"PEAK", "SHARP", "FLAT", "VALLEY"}:
            problems.append(f"电价时段类型越界: {period}")
        start = _parse_hhmm(period.get("start"))
        end = _parse_hhmm(period.get("end"))
        if start != cursor:
            problems.append(f"电价时段不连续: {period}（期望起点 {cursor} 分钟）")
        if end <= start:
            problems.append(f"电价时段起止倒置: {period}")
        if not isinstance(period.get("price"), (int, float)):
            problems.append(f"电价价格必须为数值: {period}")
        cursor = end
    if cursor != 24 * 60:
        problems.append(f"电价时段未覆盖全天 24h（终点 {cursor} 分钟）")

    demand = data.get("demand_2026_09") or {}
    if not isinstance(demand.get("peak_kw"), (int, float)):
        problems.append("demand_2026_09.peak_kw 缺失或非数值")
    if not demand.get("month"):
        problems.append("demand_2026_09.month 缺失")
    curve = data.get("load_curve_2026_09") or {}
    shape = curve.get("shape") or []
    if len(shape) != 24 or not all(isinstance(v, (int, float)) for v in shape):
        problems.append(f"load_curve_2026_09.shape 必须 24 个数值，实际 {len(shape)}")
    if not isinstance(curve.get("base_kw"), (int, float)):
        problems.append("load_curve_2026_09.base_kw 缺失或非数值")

    metrics = {
        "devices": len(device_ids),
        "substations": len(substation_ids),
        "relations": len(data.get("relations") or []),
        "operators": len(data.get("operators") or []),
        "price_periods": len(periods),
    }
    if problems:
        return _result(False, "; ".join(problems), metrics)
    return _result(True, "种子实例完整：引用可解析、电价时段覆盖 24h、负荷曲线 24 点", metrics)


def _strip_none(value: Any) -> Any:
    """递归剔除 None 字段，用于 round-trip 归一化比较。"""
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(item) for item in value]
    return value


EXECUTORS = {
    "contracts.roundtrip": exec_roundtrip,
    "contracts.enum_closure": exec_enum_closure,
    "contracts.actions_table": exec_actions_table,
    "contracts.rules_registry": exec_rules_registry,
    "contracts.seed_check": exec_seed_check,
}
