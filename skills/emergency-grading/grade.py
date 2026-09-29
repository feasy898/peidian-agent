#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""grade.py — 应急预警分级分类确定性判定脚本（skill.emergency-grading@0.1.0）。

输入：当前告警/事件集（YAML 文件，``alarms: [{id, type, device?, detail?}, ...]``
或直接一个告警列表）。输出（stdout，YAML，``--json`` 切 JSON）：

    decision / suggested_level / level_name / p_priority / time_limit_minutes
    contributing_levels / basis（逐告警：告警 ID × 映射条款 rule_id × 级别）
    posts（值班员/调度员/签发人/审批人 各自操作清单）
    escalate_when / release_when（升级与解除条件）
    manual_review（未知事件：上报人工判定，不猜级）

确定性纪律：
- 分级逻辑零硬编码——唯一数据源是同目录 SKILL.yaml 的 ``emergency_grading`` 映射表；
  整表替换为园区备案应急预案后行为随之变化，无需改代码（EG-SPEC-01/07）。
- 多告警取最高级（severity rank 最小者），同级并列按输入顺序稳定输出（EG-SPEC-03）。
- 未知事件类型一律进 manual_review（上报人工判定），绝不输出猜测级别（EG-SPEC-05）。
- 同输入 + 同映射 → 输出逐字节一致（无时钟、无随机、无字典序抖动；EG-SPEC-06）。
- 输入校验：缺 id / 空 type / 重复 id → 拒绝并退出码 2（EG-SPEC-08）。

用法（仓库根或任意目录均可）::

    python skills/emergency-grading/grade.py skills/emergency-grading/examples/demo-input.yaml
    python skills/emergency-grading/grade.py input.yaml --json
    python skills/emergency-grading/grade.py input.yaml --mapping /path/to/园区预案SKILL.yaml

行为规格条款（EG-SPEC-01..08）全文见 skills/emergency-grading/SKILL.md。
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

import yaml

SKILL_DIR = Path(__file__).resolve().parent
DEFAULT_MAPPING_PATH = SKILL_DIR / "SKILL.yaml"

_POSTS_ORDER_DEFAULT = ["值班员", "调度员", "签发人", "审批人"]
_LEVEL_KEYS_DEFAULT = ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ"]


class GradeInputError(ValueError):
    """输入告警/事件集不合法（缺 id / 空 type / 重复 id 等）。"""


class MappingError(ValueError):
    """映射表（SKILL.yaml emergency_grading 节）结构不合法。"""


# ---------------------------------------------------------------------------
# 映射表加载与校验
# ---------------------------------------------------------------------------
def load_mapping(path: str | Path | None = None) -> dict:
    """加载并校验映射表；缺省取本技能目录的 SKILL.yaml。"""
    mapping_path = Path(path) if path is not None else DEFAULT_MAPPING_PATH
    try:
        raw = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MappingError(f"映射表无法读取: {mapping_path} ({exc})") from None
    except yaml.YAMLError as exc:
        raise MappingError(f"映射表 YAML 解析失败: {mapping_path} ({exc})") from None
    if not isinstance(raw, dict) or not isinstance(raw.get("emergency_grading"), dict):
        raise MappingError(f"映射表缺少 emergency_grading 节: {mapping_path}")
    table = raw["emergency_grading"]
    problems: list = []
    levels = table.get("levels")
    if not isinstance(levels, dict) or not levels:
        problems.append("levels 必须为非空映射")
    else:
        ranks = [lv.get("rank") for lv in levels.values() if isinstance(lv, dict)]
        if len(ranks) != len(levels) or len(set(ranks)) != len(ranks):
            problems.append("levels 各级别 rank 必须唯一且齐全")
        for key, lv in levels.items():
            if not isinstance(lv, dict) or not isinstance(lv.get("rank"), int):
                problems.append(f"levels[{key!r}] 缺整型 rank")
    rules = table.get("rules")
    if not isinstance(rules, list) or not rules:
        problems.append("rules 必须为非空列表")
    else:
        seen_types: dict = {}
        for idx, rule in enumerate(rules):
            rid = rule.get("rule_id") if isinstance(rule, dict) else None
            if not rid:
                problems.append(f"rules[{idx}] 缺 rule_id")
                continue
            types = rule.get("event_types")
            if not isinstance(types, list) or not types or not all(
                isinstance(t, str) and t for t in types
            ):
                problems.append(f"{rid}: event_types 必须为非空字符串列表")
            else:
                for t in types:
                    if t in seen_types:
                        problems.append(
                            f"事件类型 {t!r} 同时命中 {seen_types[t]} 与 {rid}（二义）")
                    seen_types[t] = rid
            if levels and rule.get("level") not in levels:
                problems.append(f"{rid}: level {rule.get('level')!r} 未在 levels 定义")
            if not isinstance(rule.get("time_limit_minutes"), int) or rule["time_limit_minutes"] <= 0:
                problems.append(f"{rid}: time_limit_minutes 必须为正整数")
            posts = rule.get("posts")
            if not isinstance(posts, dict) or not posts:
                problems.append(f"{rid}: posts 必须为非空映射")
    if problems:
        raise MappingError("映射表校验失败: " + "; ".join(problems))
    return table


def _merge_ordered(*groups: list) -> list:
    """按序合并去重（保首个出现顺序；确定性）。"""
    seen: set = set()
    out: list = []
    for group in groups:
        for item in group or []:
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


# ---------------------------------------------------------------------------
# 输入加载与校验
# ---------------------------------------------------------------------------
def normalize_alarms(payload: Any) -> list:
    """接受 {alarms: [...]} 或裸列表；逐条校验并原序返回。"""
    if isinstance(payload, dict):
        alarms = payload.get("alarms")
    else:
        alarms = payload
    if not isinstance(alarms, list):
        raise GradeInputError("输入必须是 {alarms: [...]} 或告警列表（YAML）")
    seen_ids: set = set()
    for idx, alarm in enumerate(alarms):
        if not isinstance(alarm, dict):
            raise GradeInputError(f"alarms[{idx}] 必须为对象，实际 {type(alarm).__name__}")
        alarm_id = alarm.get("id")
        if not isinstance(alarm_id, str) or not alarm_id.strip():
            raise GradeInputError(f"alarms[{idx}] 缺非空字符串 id")
        if alarm_id in seen_ids:
            raise GradeInputError(f"告警 id 重复: {alarm_id!r}（同 id 多条将使依据不可追溯）")
        seen_ids.add(alarm_id)
        alarm_type = alarm.get("type")
        if not isinstance(alarm_type, str) or not alarm_type.strip():
            raise GradeInputError(f"alarms[{idx}]（id={alarm_id}）缺非空字符串 type")
    return alarms


def load_input(path: str | Path) -> list:
    input_path = Path(path)
    try:
        payload = yaml.safe_load(input_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GradeInputError(f"输入文件无法读取: {input_path} ({exc})") from None
    except yaml.YAMLError as exc:
        raise GradeInputError(f"输入 YAML 解析失败: {input_path} ({exc})") from None
    return normalize_alarms(payload)


# ---------------------------------------------------------------------------
# 分级判定（纯函数）
# ---------------------------------------------------------------------------
def grade(alarms: list, mapping: dict) -> dict:
    """对已校验的告警集按映射表判定；返回结果 dict（确定性，无副作用）。"""
    alarms = normalize_alarms(alarms)  # 双保险：直接调用 API 也过校验
    levels: dict = mapping["levels"]
    rules: list = mapping["rules"]
    rank_of = {key: lv["rank"] for key, lv in levels.items()}
    rule_by_type: dict = {}
    for rule in rules:
        for t in rule["event_types"]:
            rule_by_type[t] = rule
    posts_order = mapping.get("posts_order") or _POSTS_ORDER_DEFAULT
    fallback = mapping.get("manual_fallback") or {}

    basis: list = []
    manual_review: list = []
    for alarm in alarms:
        rule = rule_by_type.get(alarm["type"])
        if rule is None:
            manual_review.append({
                "alarm_id": alarm["id"],
                "type": alarm["type"],
                "action": fallback.get("action") or "上报人工判定",
                "reason": str(fallback.get("reason_template") or
                              "事件类型 {type}（告警 {id}）未登记于应急分级映射表，系统不猜测级别"
                              ).format(type=alarm["type"], id=alarm["id"]),
            })
            continue
        basis.append({
            "alarm_id": alarm["id"],
            "type": alarm["type"],
            "rule_id": rule["rule_id"],
            "feature": rule["feature"],
            "level": rule["level"],
            "p_priority": rule.get("p_priority"),
            "time_limit_minutes": rule["time_limit_minutes"],
        })

    matched_rules = [rule_by_type[a["type"]] for a in alarms if a["type"] in rule_by_type]
    escalate_when = _merge_ordered(*[r.get("escalate_when") for r in matched_rules])
    release_when = _merge_ordered(*[r.get("release_when") for r in matched_rules])

    if not basis:
        # 全部未知：不猜级，移交人工（EG-SPEC-05）
        result = {
            "decision": "MANUAL_REQUIRED",
            "suggested_level": None,
            "level_name": None,
            "p_priority": None,
            "time_limit_minutes": None,
            "contributing_levels": [],
            "basis": [],
            "posts": dict(fallback.get("posts") or {}),
            "escalate_when": escalate_when + ([str(fallback.get("escalate_note_template") or
                "存在未登记事件类型（{ids}），级别判定权移交人工").format(
                ids="、".join(m["alarm_id"] for m in manual_review))]
                if manual_review else []),
            "release_when": release_when,
            "manual_review": manual_review,
            "mapping_id": mapping.get("mapping_id"),
        }
        return result

    top_rank = min(rank_of[b["level"]] for b in basis)
    top_entries = [b for b in basis if rank_of[b["level"]] == top_rank]  # 输入序
    suggested_level = top_entries[0]["level"]
    contributing_levels: list = []
    for key, lv in sorted(levels.items(), key=lambda kv: kv[1]["rank"]):
        if any(b["level"] == key for b in basis):
            contributing_levels.append(key)

    posts: dict = {}
    for post in posts_order:
        ops = _merge_ordered(*[r.get("posts", {}).get(post) for r in matched_rules])
        if ops:
            posts[post] = ops

    result = {
        "decision": "AUTO_GRADED",
        "suggested_level": suggested_level,
        "level_name": levels[suggested_level].get("name"),
        "p_priority": top_entries[0]["p_priority"],
        "time_limit_minutes": min(b["time_limit_minutes"] for b in top_entries),
        "contributing_levels": contributing_levels,
        "basis": basis,
        "posts": posts,
        "escalate_when": escalate_when + ([str(fallback.get("escalate_note_template") or
            "存在未登记事件类型（{ids}），级别判定权移交人工").format(
            ids="、".join(m["alarm_id"] for m in manual_review))]
            if manual_review else []),
        "release_when": release_when,
        "manual_review": manual_review,
        "mapping_id": mapping.get("mapping_id"),
    }
    return result


def render(result: dict) -> str:
    """结果 → 稳定 YAML 文本（sort_keys=False，字段按构造序）。"""
    return yaml.safe_dump(result, allow_unicode=True, sort_keys=False, width=100)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="应急预警分级分类确定性判定（数据源=同目录 SKILL.yaml 映射表）")
    parser.add_argument("input", help="告警/事件集 YAML 文件（{alarms: [...]} 或裸列表）")
    parser.add_argument("--mapping", default=None,
                        help="映射表路径（缺省=本技能 SKILL.yaml；可指向园区预案替换表）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出（缺省 YAML）")
    args = parser.parse_args(argv)
    try:
        alarms = load_input(args.input)
        mapping = load_mapping(args.mapping)
        result = grade(alarms, mapping)
    except (GradeInputError, MappingError) as exc:
        print(f"[grade] 拒绝: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render(result), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
