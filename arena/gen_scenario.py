#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-
"""arena/gen_scenario.py · LLM 辅助练习场场景生成器（module-map #19/#20 · arena/__init__ 规划位）

流程（生成 ≠ 入库，LLM 输出零信任，四道门全过才落盘）：
  ① LLM 起草：喂故障库 11 类（类型/兼容元件/参数域/判据 R 编号）、判据 schema、
    既有场景 2 例（S-201 状态型 / S-206 网络型）作 few-shot，按 --subject 产出
    结构化 JSON 草稿（叙事 + faults 条 + 日历 + 注入计划）；
  ② 结构化解析 + 语义校验（本模块 check_draft）：kind ∈ arena/faults 库真实 11 类；
    target 元件存在且与库 compat_kinds 兼容；criteria_ref 必须 ∈ 该类型库条目
    sources（真实 R 编号且与类型绑定）；注入 params 复用 fault.dsl.PARAM_SPECS
    同款校验器；note 禁自带标准编号（判据出处只认 criteria_ref，防冒充文献）；
    检出可行性静态估算（慢爬升类须在时长内越过判据）；
  ③ dsl.validate_dsl：ParkDSL v1.1 权威校验器（dsl/validate.py，数据驱动 spec）；
  ④ arena 干跑门（--no-dry-run 关）：ArenaEngine 同款路径实跑，detected ≥1 且
    注入 0 rejected 才算过——不过即弃。
通过后按 S-2NN 续号落盘 --out 目录（缺省 arena/scenarios/），来源诚实标注
`source: llm-draft+zhipu`（不冒充文献；拓扑基底注明 PARK-202/206）。

用法::

    python arena/gen_scenario.py --subject "台风灾害" --n 5 --out arena/scenarios/ \
        [--basis PARK-202|PARK-206] [--max-calls 30] [--no-dry-run] [--json]

LLM 经 arena.model_gateway（env 优先序 LLM_API_KEY/BIGMODEL_API_KEY/OPENAI_API_KEY）。
无 key 时 fail-closed：直接退出码 2（绝不落盘未校验产物）。
退出码：0=落盘数 ≥ n；1=预算内未凑齐（如实报数）；2=用法/环境/IO 错误。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from arena.model_gateway import GatewayError, ModelGateway  # noqa: E402
from dsl.validate import validate_dsl  # noqa: E402  —— 权威校验器（唯一守门）
from fault.dsl import PARAM_SPECS  # noqa: E402  —— 注入参数域与引擎同款

__all__ = ["GenScenarioError", "parse_draft", "check_draft", "assemble_yaml",
           "next_scene_no", "load_fault_summary", "load_reference_rs"]

DEFAULT_OUT = ROOT / "arena" / "scenarios"
REFERENCES_MD = ROOT / "docs" / "theory" / "references.md"
FAULTS_DIR = ROOT / "arena" / "faults"
DEFAULT_MODEL = "glm-4-flash"
MAX_CALLS_DEFAULT = 30

# 生成器策略边界（比 DSL spec 更窄，全部落在既有 20 场景的实践区间内；
# 时长上限 172800=2 仿真日，与既有库最长场景一致——3 日稿干跑实测可拖过 40 分钟）
DURATION_BOUNDS = (43200, 172800)        # 12h ~ 2 仿真日
CLOCK_BOUNDS = (600, 1800)
MIN_INJECTION_GAP_S = 1800               # 注入两两间隔（防异常互相淹没）
R_NUM_RE = re.compile(r"^R\d+$")
FAULT_ID_RE = re.compile(r"^F-[A-Z][A-Z0-9-]{0,39}$")
STD_CITE_RE = re.compile(r"GB/T|DL/T|Q/GDW|IEC|IEEE|ISO\s")   # note 禁自带标准编号
CAL_TYPES = {"shift_handover", "patrol", "infrared_scan", "preventive_test",
             "outage_plan", "baodian", "work_order_95598", "report"}
SEVERITIES = {"info", "warn", "alarm", "accident"}
COMPARATORS = {">", ">=", "<", "<=", "==", "trend_up"}


class GenScenarioError(RuntimeError):
    """生成器环境/装配层错误（与"草稿被拒"区分：被拒是正常回路，不抛异常）。"""


# ================================================================ 库摘要与 R 编号
def load_fault_summary(faults_dir: Path | str | None = None) -> dict[str, dict]:
    """arena/faults/*.yaml → kind → 摘要（供提示词与校验；库本身由 faultlib 权威加载）。"""
    d = Path(faults_dir) if faults_dir is not None else FAULTS_DIR
    out: dict[str, dict] = {}
    for p in sorted(d.glob("*.yaml")):
        entry = yaml.safe_load(p.read_text(encoding="utf-8"))
        det = entry.get("detection") or {}
        out[str(entry["kind"])] = {
            "title": entry.get("title", ""),
            "class": entry.get("class", ""),
            "engine_type": entry.get("engine_type", ""),
            "compat_kinds": list(entry.get("compat_kinds") or []),
            "params": {k: {"default": v[3], "range": v[1]}
                       for k, v in (PARAM_SPECS.get(entry.get("engine_type"), {})).items()},
            "detection": {"metric": det.get("metric"), "comparator": det.get("comparator"),
                          "threshold": det.get("threshold"), "duration_sec": det.get("duration_sec")},
            "sources": [str(s) for s in (entry.get("sources") or [])],
        }
    if not out:
        raise GenScenarioError(f"故障库为空: {d}")
    return out


def load_reference_rs(refs_md: Path | str | None = None) -> set[str]:
    """docs/theory/references.md 表内真实 R 编号集合（判据引用的第二道存在性核对）。"""
    p = Path(refs_md) if refs_md is not None else REFERENCES_MD
    text = p.read_text(encoding="utf-8")
    rs: set[str] = set()
    for line in text.splitlines():
        m = re.match(r"^\|\s*(R\d+)\s*\|", line)
        if m:
            rs.add(m.group(1))
    return rs


# ================================================================ 拓扑基底（与 S-20x 同构的固定段）
_BASES: dict[str, dict] = {
    "PARK-202": {
        "park": {"id": "PARK-202", "tier": "medium", "contract_capacity_kw": 2000,
                 "incoming_voltage": "10kV", "seed": 202},
        "grid_inlets": [{"id": "GRID-01", "source_voltage": "10kV", "short_capacity_mva": 200}],
        "substations": [
            {"id": "SR-A", "name": "A 配电房（动力中心）", "devices": [
                {"id": "SG-A00", "type": "Switchgear", "rated_current_a": 630, "state": "CLOSED", "role": "incomer"},
                {"id": "BUS-A1", "type": "Bus", "voltage_level": "10kV"},
                {"id": "SG-A01", "type": "Switchgear", "rated_current_a": 630, "state": "CLOSED", "role": "incomer"},
                {"id": "TX-A01", "type": "Transformer", "capacity_kva": 1600, "hv": "10kV", "lv": "0.4kV", "cooling": "ONAF"},
                {"id": "BUS-A2", "type": "Bus", "voltage_level": "0.4kV"},
                {"id": "LD-A01", "type": "Load", "peak_kw": 420, "profile": "factory"},
                {"id": "LD-A02", "type": "Load", "peak_kw": 260, "profile": "office"},
                {"id": "EVC-01", "type": "EVCharger", "total_power_kw": 240, "num_ports": 8}]},
            {"id": "SR-B", "name": "B 配电房（源网荷储示范）", "devices": [
                {"id": "BUS-B1", "type": "Bus", "voltage_level": "10kV"},
                {"id": "SG-B00", "type": "Switchgear", "rated_current_a": 630, "state": "CLOSED", "role": "incomer"},
                {"id": "TX-B01", "type": "Transformer", "capacity_kva": 1000, "hv": "10kV", "lv": "0.4kV"},
                {"id": "SG-B01", "type": "Switchgear", "rated_current_a": 630, "state": "CLOSED", "role": "feeder"},
                {"id": "BUS-B2", "type": "Bus", "voltage_level": "0.4kV"},
                {"id": "PV-01", "type": "PV", "capacity_kwp": 400, "tilt": 10, "azimuth": 180},
                {"id": "BESS-01", "type": "BESS", "capacity_kwh": 500, "power_kw": 250, "soc": 62},
                {"id": "LD-B01", "type": "Load", "peak_kw": 380, "profile": "factory"},
                {"id": "LD-B02", "type": "Load", "peak_kw": 220, "profile": "office"}]},
        ],
        "links": [
            {"from": "GRID-01", "to": "SG-A00", "kind": "line", "id": "LN-01", "length_km": 3.2, "ampacity_a": 400},
            {"from": "SG-A00", "to": "BUS-A1", "kind": "direct"},
            {"from": "BUS-A1", "to": "SG-A01", "kind": "direct"},
            {"from": "SG-A01", "to": "TX-A01", "kind": "direct"},
            {"from": "TX-A01", "to": "BUS-A2", "kind": "direct"},
            {"from": "BUS-A1", "to": "BUS-B1", "kind": "line", "id": "LN-02", "length_km": 1.6, "ampacity_a": 300},
            {"from": "BUS-B1", "to": "SG-B00", "kind": "direct"},
            {"from": "SG-B00", "to": "TX-B01", "kind": "direct"},
            {"from": "TX-B01", "to": "SG-B01", "kind": "direct"},
            {"from": "SG-B01", "to": "BUS-B2", "kind": "direct"},
            {"from": "BUS-A2", "to": "BUS-B2", "kind": "coupler", "id": "CP-01", "state": "OPEN"},
            {"from": "BUS-A2", "to": "LD-A01", "kind": "direct"},
            {"from": "BUS-A2", "to": "LD-A02", "kind": "direct"},
            {"from": "BUS-A2", "to": "EVC-01", "kind": "direct"},
            {"from": "BUS-B2", "to": "LD-B01", "kind": "direct"},
            {"from": "BUS-B2", "to": "LD-B02", "kind": "direct"},
            {"from": "BUS-B2", "to": "PV-01", "kind": "direct"},
            {"from": "BUS-B2", "to": "BESS-01", "kind": "direct"},
        ],
    },
    "PARK-206": {
        "park": {"id": "PARK-206", "tier": "medium", "contract_capacity_kw": 2000,
                 "incoming_voltage": "10kV", "seed": 206},
        "grid_inlets": [{"id": "GRID-01", "source_voltage": "10kV", "short_capacity_mva": 200}],
        "substations": [
            {"id": "SR-A", "name": "A 配电房（动力中心）", "devices": [
                {"id": "SG-A00", "type": "Switchgear", "rated_current_a": 630, "state": "CLOSED", "role": "incomer"},
                {"id": "BUS-A1", "type": "Bus", "voltage_level": "10kV"},
                {"id": "SG-A01", "type": "Switchgear", "rated_current_a": 630, "state": "CLOSED", "role": "incomer"},
                {"id": "TX-A01", "type": "Transformer", "capacity_kva": 2000, "hv": "10kV", "lv": "0.4kV", "cooling": "ONAF"},
                {"id": "BUS-A2", "type": "Bus", "voltage_level": "0.4kV"},
                {"id": "LD-A01", "type": "Load", "peak_kw": 420, "profile": "factory"},
                {"id": "LD-A02", "type": "Load", "peak_kw": 260, "profile": "office"},
                {"id": "EVC-01", "type": "EVCharger", "total_power_kw": 240, "num_ports": 8}]},
            {"id": "SR-B", "name": "B 配电房（源网荷储示范）", "devices": [
                {"id": "BUS-B1", "type": "Bus", "voltage_level": "10kV"},
                {"id": "SG-B00", "type": "Switchgear", "rated_current_a": 630, "state": "CLOSED", "role": "incomer"},
                {"id": "TX-B01", "type": "Transformer", "capacity_kva": 1000, "hv": "10kV", "lv": "0.4kV"},
                {"id": "SG-B01", "type": "Switchgear", "rated_current_a": 630, "state": "CLOSED", "role": "feeder"},
                {"id": "BUS-B2", "type": "Bus", "voltage_level": "0.4kV"},
                {"id": "PV-01", "type": "PV", "capacity_kwp": 400, "tilt": 10, "azimuth": 180},
                {"id": "BESS-01", "type": "BESS", "capacity_kwh": 500, "power_kw": 250, "soc": 62},
                {"id": "LD-B01", "type": "Load", "peak_kw": 380, "profile": "factory"},
                {"id": "LD-B02", "type": "Load", "peak_kw": 220, "profile": "office"}]},
        ],
        "links": None,  # 与 PARK-202 同一 links（S-220 与 S-201 拓扑逐边一致）
    },
}
_BASES["PARK-206"]["links"] = _BASES["PARK-202"]["links"]

_TYPE2KIND = {"Switchgear": "switchgear", "Transformer": "transformer", "Bus": "bus",
              "Load": "load", "PV": "pv", "BESS": "bess", "EVCharger": "ev_charger",
              "GridInlet": "grid_inlet"}
_LINK_ID_KIND = {"LN": "line", "CP": "coupler"}


def basis_inventory(basis: str) -> dict[str, str]:
    """基底拓扑 → 元件/线路 ID → fault.topology 元件类别（注入 target 的合法域）。"""
    b = _BASES.get(basis)
    if b is None:
        raise GenScenarioError(f"未知拓扑基底 {basis!r}（允许 {sorted(_BASES)}）")
    inv: dict[str, str] = {}
    for gi in b["grid_inlets"]:
        inv[gi["id"]] = _TYPE2KIND.get("GridInlet", "grid_inlet")
    for sr in b["substations"]:
        for dv in sr["devices"]:
            inv[dv["id"]] = _TYPE2KIND.get(dv["type"], dv["type"].lower())
    for lk in b["links"]:
        lid = lk.get("id")
        if lid:
            inv[lid] = _LINK_ID_KIND.get(lid.split("-")[0], "line")
    return inv


# ================================================================ ① LLM 起草
FEWSHOT = [
    {   # 改编自既有场景 S-201（状态型 · 局放趋势；拓扑基底 PARK-202）
        "title": "局放趋势场景（状态型样例 · 改编自既有 S-201）",
        "narrative": "模拟什么：夜巡发现进线柜 TEV 背景偏高后局放幅值爬升越限，考确诊（横向+纵向趋势判读）→派工消缺→复测闭环；禁则：未确认拉闸/假报清除。",
        "park_description": "与 park-arena-01 同拓扑的设备量测练习场配置：夜巡暴露进线柜局放隐患。",
        "faults": [{"id": "F-PD-201", "kind": "partial_discharge", "target": "SG-A01",
                    "severity": "warn", "criteria_ref": "R37",
                    "detection": {"metric": "tev_db", "threshold": 20, "comparator": ">", "duration_sec": 600},
                    "note": "TEV 自背景 16dB 以 3dB/h 爬升越 20dB 注意级；确诊须绝对值+横向+纵向三法并用。"}],
        "calendar_events": [
            {"id": "CAL-SHIFT", "type": "shift_handover", "params": {"times": ["08:00", "16:00", "00:00"]}},
            {"id": "CAL-PATROL-D", "type": "patrol", "every_days": 1, "at": "09:00", "scope": "all"},
            {"id": "CAL-PATROL-N", "type": "patrol", "every_days": 1, "at": "23:00", "params": {"kind": "night"}},
            {"id": "CAL-PD-TEST", "type": "preventive_test", "every_days": 1, "at": "10:00",
             "params": {"item": "开关柜带电检测局放复测（TEV+超声）", "scope": "SR-A"}}],
        "duration_sim_s": 172800, "clock_speed": 1800,
        "scenario_description": "夜巡后局放趋势爬升越限；agent 应确诊、派工消缺并带电复测闭环，判据 R37/R38。",
        "injections": [{"fault": "F-PD-201", "at_sim_s": 81000,
                        "params": {"baseline_db": 16, "growth_db_per_h": 3.0, "threshold_db": 20, "repair_s": 7200},
                        "note": "第 1 日 22:30 注入，约 23:50 越限、600s 后判识。"}],
    },
    {   # 改编自既有场景 S-206（网络型 · 重过载隔离+母联转供；拓扑基底 PARK-202）
        "title": "变压器重过载演练（网络型样例 · 改编自既有 S-206）",
        "narrative": "模拟什么：晚高峰 B 变负载率冲破 1.0，考确认→隔离故障变→合母联 CP-01 转供→复测闭环；严禁未转供先停主变。",
        "park_description": "与 park-arena-01 同源 PARK-202 结构，A 房主变保留转供裕度。",
        "faults": [{"id": "F-OVL-206", "kind": "over_limit", "target": "LN-01",
                    "severity": "alarm", "criteria_ref": "R94",
                    "detection": {"metric": "load_ratio", "threshold": 1.0, "comparator": ">", "duration_sec": 600},
                    "note": "负载率 >1.0 重过载；期望先转供后退出，形成明显断开点。"}],
        "calendar_events": [
            {"id": "CAL-SHIFT", "type": "shift_handover", "params": {"times": ["08:00", "16:00", "00:00"]}},
            {"id": "CAL-PATROL-D", "type": "patrol", "every_days": 1, "at": "09:00", "scope": "all"},
            {"id": "CAL-IR", "type": "infrared_scan", "every_days": 1, "at": "14:00", "params": {"kind": "overload_tracking"}},
            {"id": "CAL-REPORT", "type": "report", "every_days": 1, "at": "08:30", "params": {"kind": "daily_inspection"}}],
        "duration_sim_s": 86400, "clock_speed": 600,
        "scenario_description": "晚高峰重过载演练：隔离+母联转供闭环，演示先转供后退出的网络型处置纪律。",
        "injections": [{"fault": "F-OVL-206", "at_sim_s": 64800,
                        "params": {"load_ratio": 1.2, "repair_s": 10800},
                        "note": "18:00 注入后一拍内检出，隔离+转供分钟级完成。"}],
    },
]


def _kind_table(faultlib: dict[str, dict]) -> str:
    lines = []
    for kind, e in faultlib.items():
        params = "; ".join(f"{k}∈{v['range']} 默认{v['default']}" for k, v in e["params"].items())
        det = e["detection"]
        thr = det.get("threshold")
        thr = "任意非空" if (thr is None or thr == "") else thr
        lines.append(
            f"- {kind}（{e['title']}｜{e['class']}类｜可作用元件: {'/'.join(e['compat_kinds'])}）\n"
            f"  判据: {det.get('metric')} {det.get('comparator')} {thr} 持续{det.get('duration_sec')}s；"
            f"criteria_ref 只允许 {'/'.join(e['sources'])}\n"
            f"  注入参数: {params or '（无）'}")
    return "\n".join(lines)


def _inventory_lines(basis: str) -> str:
    inv = basis_inventory(basis)
    return ", ".join(inv)


_SYSTEM_TMPL = """你是园区配电运维练习场的场景编撰专家。根据用户给定的主题，起草一个可被仿真引擎执行的练习场景。只输出一个 JSON 对象，不要任何其他文字。

## 硬规则（违反即被校验器拒绝）
1. 只输出 JSON：键为 title/narrative/park_description/faults/calendar_events/duration_sim_s/clock_speed/scenario_description/injections。
2. faults[].kind 只能取下列故障库真实类型之一，且 target 只能引用给定元件/线路清单中的 ID，类型-元件须兼容：
{kind_table}
3. criteria_ref 只能取该类型括号内列出的 R 编号（真实文献编号，不得自造）；note 里禁止出现 GB/T、DL/T、Q/GDW、IEC 等标准编号字样——判据出处一律以 criteria_ref 表达。
4. detection 的 metric/comparator 必须照抄上面"判据"一行（threshold 可按园区口径微调但必须能被越过）；duration_sec 建议 60~1800。
5. injections[].fault 必须引用本稿 faults[].id；at_sim_s 为仿真秒且 < duration_sim_s；多条注入两两间隔 ≥3600；params 只能用该类型的注入参数（范围照上，可省略则用默认值）。
6. duration_sim_s 取 43200~172800（建议 86400~172800，给慢爬升类留越限时间）；clock_speed 取 600~1800。
7. calendar_events 只能用类型: shift_handover/patrol/infrared_scan/preventive_test/outage_plan/baodian/work_order_95598/report；至少含 1 条 shift_handover 或 patrol；id 以 CAL- 开头且唯一。
8. 至少 1 条 injection；故障严重度 severity ∈ info/warn/alarm/accident。
9. 注入参数取值必须让检测判据在场景时长内被越过（慢爬升类给出足够的 growth 与提前量）。

## 输出 JSON schema（字段名逐字照抄）
{{"title": str, "narrative": str, "park_description": str, "faults": [{{"id": "F-XXX", "kind": str, "target": str, "severity": str, "criteria_ref": "Rnn", "detection": {{"metric": str, "threshold": number或str, "comparator": str, "duration_sec": number}}, "note": str}}], "calendar_events": [{{"id": str, "type": str, "every_days": int, "at": "HH:MM", "params": {{}}, "scope": str}}], "duration_sim_s": int, "clock_speed": int, "scenario_description": str, "injections": [{{"fault": str, "at_sim_s": int, "params": {{}}, "note": str}}]}}

## 既有场景两例（few-shot，格式范本）
{fewshot}
"""


def build_system_prompt(faultlib: dict[str, dict]) -> str:
    fewshot = "\n\n".join("例" + str(i + 1) + ":\n" + json.dumps(e, ensure_ascii=False, indent=1)
                          for i, e in enumerate(FEWSHOT))
    return _SYSTEM_TMPL.format(kind_table=_kind_table(faultlib), fewshot=fewshot)


_VARIETY = [
    "侧重状态型异常（消缺闭环类）与业务日历的穿插",
    "侧重网络型异常（隔离/转供类）与母联通道的占用时序",
    "两类异常先后出现，考处置优先级编排",
    "单故障深度演练：一个异常从头考到尾（确认→处置→闭环）",
    "多故障并发压力：两至三个异常交错，考排队处置",
]


def build_user_prompt(subject: str, basis: str, attempt: int,
                      used_kinds: list[list[str]], feedback: list[str] | None) -> str:
    lines = [f"主题：{subject}", f"拓扑基底：{basis}（元件/线路 ID 只能取: { _inventory_lines(basis)}）"]
    if used_kinds:
        prev = "、".join(sorted({k for ks in used_kinds for k in ks}))
        lines.append(f"多样性：已生成场景用过 {prev}——本稿换一批类型/目标/时段，勿重复。")
    lines.append(f"变化提示：{_VARIETY[attempt % len(_VARIETY)]}。")
    if feedback:
        lines.append("上一稿被校验器拒绝，原因如下——修正后重新给出一稿全新 JSON：\n- " + "\n- ".join(feedback[:8]))
    return "\n".join(lines)


# ================================================================ ② 结构化解析 + 语义校验
def parse_draft(text: str) -> tuple[dict | None, list[str]]:
    """LLM 输出文本 → JSON dict（剥代码围栏）。失败返回 (None, reasons)。"""
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw).strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        raw = m.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, [f"输出不是合法 JSON: {exc}"]
    if not isinstance(data, dict):
        return None, [f"输出必须是 JSON 对象，收到 {type(data).__name__}"]
    return data, []


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_draft(draft: dict, *, basis: str, faultlib: dict[str, dict],
                valid_rs: set[str]) -> list[str]:
    """语义校验（零信任第二道门）。返回拒绝原因列表；空 = 通过。"""
    why: list[str] = []
    inv = basis_inventory(basis)
    for k in ("title", "narrative", "park_description", "scenario_description"):
        if not str(draft.get(k) or "").strip():
            why.append(f"缺字段 {k}")
    dur, clk = draft.get("duration_sim_s"), draft.get("clock_speed")
    if not _is_num(dur) or not (DURATION_BOUNDS[0] <= dur <= DURATION_BOUNDS[1]):
        why.append(f"duration_sim_s 须 ∈ [{DURATION_BOUNDS[0]},{DURATION_BOUNDS[1]}]，收到 {dur!r}")
    if not _is_num(clk) or not (CLOCK_BOUNDS[0] <= clk <= CLOCK_BOUNDS[1]):
        why.append(f"clock_speed 须 ∈ [{CLOCK_BOUNDS[0]},{CLOCK_BOUNDS[1]}]，收到 {clk!r}")

    faults = draft.get("faults")
    if not isinstance(faults, list) or not faults:
        why.append("faults 须为非空数组")
        faults = []
    seen_ids: set[str] = set()
    entries: dict[str, dict] = {}
    for i, f in enumerate(faults):
        loc = f"faults[{i}]"
        if not isinstance(f, dict):
            why.append(f"{loc} 须为映射")
            continue
        fid = f.get("id")
        if not isinstance(fid, str) or not FAULT_ID_RE.match(fid):
            why.append(f"{loc}.id 不匹配 F-XXX 规范: {fid!r}")
            continue
        if fid in seen_ids:
            why.append(f"{loc}.id 重复: {fid}")
            continue
        seen_ids.add(fid)
        kind = f.get("kind")
        lib = faultlib.get(str(kind))
        if lib is None:
            why.append(f"{loc}.kind 不在故障库 11 类内: {kind!r}")
            continue
        tgt = f.get("target")
        tkind = inv.get(str(tgt) if tgt is not None else "")
        if tkind is None:
            why.append(f"{loc}.target 不在基底 {basis} 元件清单内: {tgt!r}")
        elif tkind not in lib["compat_kinds"]:
            why.append(f"{loc}.target 类型不兼容: {kind} 不能作用于 {tkind} 类 {tgt}")
        if f.get("severity") not in SEVERITIES:
            why.append(f"{loc}.severity 须 ∈ {sorted(SEVERITIES)}: {f.get('severity')!r}")
        cref = f.get("criteria_ref")
        if not isinstance(cref, str) or not R_NUM_RE.match(cref):
            why.append(f"{loc}.criteria_ref 须为 R 编号: {cref!r}")
        elif cref not in lib["sources"]:
            why.append(f"{loc}.criteria_ref {cref} 不是 {kind} 库条目绑定的真实编号"
                       f"（允许 {'/'.join(lib['sources'])}）")
        elif valid_rs and cref not in valid_rs:
            why.append(f"{loc}.criteria_ref {cref} 不在 references.md 编号表内")
        det = f.get("detection")
        if not isinstance(det, dict):
            why.append(f"{loc}.detection 须为映射")
        else:
            libdet = lib["detection"]
            if det.get("metric") != libdet["metric"]:
                why.append(f"{loc}.detection.metric 须为库判据口径 {libdet['metric']!r}: {det.get('metric')!r}")
            if det.get("comparator") not in COMPARATORS:
                why.append(f"{loc}.detection.comparator 非法: {det.get('comparator')!r}")
            if det.get("threshold") in (None, ""):
                why.append(f"{loc}.detection.threshold 缺失（DSL 必填非空；参考 S-209 用 ==锚定字符串模式）")
            elif not _is_num(det.get("threshold")) and not isinstance(det.get("threshold"), str):
                why.append(f"{loc}.detection.threshold 须为数值或字符串")
            d = det.get("duration_sec")
            if not _is_num(d) or d <= 0:
                why.append(f"{loc}.detection.duration_sec 须 >0: {d!r}")
        note = str(f.get("note") or "")
        if not note.strip():
            why.append(f"{loc}.note 缺失（须给处置要点）")
        elif len(note) > 400:
            why.append(f"{loc}.note 过长（>400 字符）")
        elif STD_CITE_RE.search(note):
            why.append(f"{loc}.note 自带标准编号（判据出处只认 criteria_ref，防冒充文献）")
        entries[fid] = {"entry": f, "lib": lib}

    # calendar
    events = draft.get("calendar_events")
    if not isinstance(events, list) or not events:
        why.append("calendar_events 须为非空数组")
        events = []
    seen_cids: set[str] = set()
    has_ops = False
    for i, ev in enumerate(events):
        loc = f"calendar_events[{i}]"
        if not isinstance(ev, dict):
            why.append(f"{loc} 须为映射")
            continue
        if ev.get("type") not in CAL_TYPES:
            why.append(f"{loc}.type 非法: {ev.get('type')!r}")
        if str(ev.get("type")) in ("shift_handover", "patrol"):
            has_ops = True
        cid = ev.get("id")
        if cid is not None:
            if not isinstance(cid, str) or cid in seen_cids:
                why.append(f"{loc}.id 重复或非法: {cid!r}")
            seen_cids.add(cid)
        ed = ev.get("every_days")
        if ed is not None and (not isinstance(ed, int) or isinstance(ed, bool) or ed < 1):
            why.append(f"{loc}.every_days 须 ≥1 整数: {ed!r}")
        at = ev.get("at")
        if at is not None and (not isinstance(at, str) or not re.match(r"^([01][0-9]|2[0-3]):[0-5][0-9]$", at)):
            why.append(f"{loc}.at 须为 HH:MM: {at!r}")
        if ev.get("params") is not None and not isinstance(ev.get("params"), dict):
            why.append(f"{loc}.params 须为映射")
    if events and not has_ops:
        why.append("calendar_events 至少含 1 条 shift_handover 或 patrol")

    # injections
    injs = draft.get("injections")
    if not isinstance(injs, list) or not injs:
        why.append("injections 须为非空数组")
        injs = []
    times: list[float] = []
    for i, j in enumerate(injs):
        loc = f"injections[{i}]"
        if not isinstance(j, dict):
            why.append(f"{loc} 须为映射")
            continue
        fid = j.get("fault")
        ent = entries.get(str(fid)) if fid is not None else None
        if ent is None:
            why.append(f"{loc}.fault 未在本稿 faults 声明: {fid!r}")
            continue
        at = j.get("at_sim_s")
        if not _is_num(at) or at < 0:
            why.append(f"{loc}.at_sim_s 须 ≥0 数值: {at!r}")
        elif _is_num(dur) and at >= dur:
            why.append(f"{loc}.at_sim_s 晚于场景时长（{at}≥{dur}）")
        else:
            times.append(float(at))
        et = ent["lib"]["engine_type"]
        params = j.get("params") or {}
        if not isinstance(params, dict):
            why.append(f"{loc}.params 须为映射")
        else:
            specs = PARAM_SPECS.get(et, {})
            for pk, pv in params.items():
                spec = specs.get(pk)
                if spec is None:
                    why.append(f"{loc}.params.{pk} 不是 {et} 的合法参数（允许 {sorted(specs)}）")
                    continue
                typ, desc, chk, _dflt = spec
                if isinstance(pv, bool) and typ is not bool:
                    why.append(f"{loc}.params.{pk} 类型错误（布尔）")
                elif not isinstance(pv, typ):
                    why.append(f"{loc}.params.{pk} 类型错误: 期望 {typ}，收到 {type(pv).__name__}")
                elif not chk(pv, None):
                    why.append(f"{loc}.params.{pk}={pv!r} 越界（约束 {desc}）")
        ok, msg = _feasible(ent, j, dur)
        if not ok:
            why.append(f"{loc} 检出可行性不足: {msg}")
    for a, b in zip(sorted(times), sorted(times)[1:]):
        if b - a < MIN_INJECTION_GAP_S:
            why.append(f"注入时刻间隔不足（{a}->{b} < {MIN_INJECTION_GAP_S}s），异常会互相淹没")
            break
    return why


def _feasible(ent: dict, inj: dict, duration: Any) -> tuple[bool, str]:
    """慢爬升/水平量故障的检出可行性静态估算（真判据在干跑门）。"""
    if not _is_num(duration):
        return True, ""
    lib, entry = ent["lib"], ent["entry"]
    et, det = lib["engine_type"], entry.get("detection") or {}
    p = inj.get("params") or {}
    at = float(inj.get("at_sim_s", 0) or 0)
    dur_sec = float(det.get("duration_sec") or 0)
    budget = float(duration) - at - dur_sec - 600   # 预留判识窗+裕量

    def hours_ok(cross_h: float | None) -> tuple[bool, str]:
        if cross_h is None:
            return False, "参数组合无法越过判据门限"
        need = cross_h * 3600.0
        return (need <= budget, f"越限需 {need:.0f}s，注入后剩余预算仅 {budget:.0f}s")

    thr = det.get("threshold")
    if et == "PARTIAL_DISCHARGE":
        base, growth = float(p.get("baseline_db", 8)), float(p.get("growth_db_per_h", 1.5))
        t = float(thr if _is_num(thr) else p.get("threshold_db", 20))
        if base >= t:
            return True, ""
        return hours_ok((t - base) / growth if growth > 0 else None)
    if et == "TEMPERATURE_RISE":
        amb, rise = float(p.get("ambient_c", 30)), float(p.get("rise_k_per_h", 12))
        t = float(thr if _is_num(thr) else 70)
        if amb >= t:
            return True, ""
        return hours_ok((t - amb) / rise if rise > 0 else None)
    if et == "TRANSFORMER_FAULT":
        rise, target = float(p.get("rise_k_per_h", 6)), float(p.get("target_oil_temp_c", 95))
        t = float(thr if _is_num(thr) else 85)
        if target <= t:
            return False, f"target_oil_temp_c {target} 到不了判据 {t}"
        return hours_ok((t - 40.0) / rise if rise > 0 else None)
    # 水平量类：注入参数直接决定信号电平，对照 detection.threshold
    level = {"HARMONIC": (">", float(p.get("thdu_pct", 6.5))),
             "THREE_PHASE_UNBALANCE": (">", float(p.get("unbalance_pct", 4.5))),
             "OVER_LIMIT": (">", float(p.get("load_ratio", 1.15))),
             "DC_GROUND_FAULT": ("<", float(p.get("insulation_kohm", 8))),
             "PHASE_LOSS": (">", float(p.get("current_dev_pct", 25))),
             "SINGLE_PHASE_GROUND": (">", float(p.get("phase_voltage_pu", 1.73))),
             "ENVIRONMENTAL": (">", float(p.get("room_temp_c", 42)))}.get(et)
    if level and _is_num(thr):
        op, val = level
        crossed = val > float(thr) if op == ">" else val < float(thr)
        if not crossed:
            return False, f"注入电平 {val} 未越过判据门限 {thr}"
    return True, ""


# ================================================================ 装配（③ 前的确定性拼装）
def assemble_yaml(draft: dict, *, basis: str, scene_no: int, subject: str,
                  model: str) -> str:
    """草稿 + 固定基底 → 与 S-20x 同构的完整场景 YAML 文本。确定性拼装，不引入新语义。"""
    b = _BASES[basis]
    park = dict(b["park"])
    park["name"] = str(draft["title"])[:40]
    park["description"] = str(draft["park_description"])
    faults_out = []
    for f in draft["faults"]:
        e = {k: f[k] for k in ("id", "kind", "target", "severity", "criteria_ref", "detection") if f.get(k) is not None}
        e["note"] = f["note"]
        faults_out.append(e)
    events_out = []
    for ev in draft["calendar_events"]:
        e: dict[str, Any] = {"id": ev.get("id") or f"CAL-EV-{len(events_out) + 1:02d}",
                             "type": ev["type"]}
        for k in ("every_days", "at", "scope", "params"):
            if ev.get(k) is not None:
                e[k] = ev[k]
        events_out.append(e)
    shifts = ["00:00-08:00", "08:00-16:00", "16:00-24:00"]
    if not any(str(ev.get("type")) == "shift_handover" for ev in events_out):
        events_out.insert(0, {"id": "CAL-SHIFT", "type": "shift_handover",
                              "params": {"times": ["08:00", "16:00", "00:00"]}})
    injs_out = []
    for j in draft["injections"]:
        e = {"fault": j["fault"], "at_sim_s": j["at_sim_s"]}
        if j.get("params"):
            e["params"] = j["params"]
        if j.get("note"):
            e["note"] = j["note"]
        injs_out.append(e)
    kinds_used = sorted({str(f["kind"]) for f in faults_out})
    crefs = sorted({str(f.get("criteria_ref")) for f in faults_out if f.get("criteria_ref")})

    narrative = str(draft["narrative"]).strip()
    narrative = re.sub(r"^模拟什么[:：]\s*", "", narrative)   # few-shot 口气去重
    header = "\n".join([
        f"# arena/scenarios/S-{scene_no}.yaml · 练习场场景 S-{scene_no}（主题：{subject}）",
        f"# 生成：arena/gen_scenario.py（LLM 起草 dsl 校验 arena 干跑入库；来源 {model}）",
        f"# 模拟什么：{narrative}",
        f"# 判据出处（真实 R 编号，均经库绑定核对）：{'/'.join(crefs) if crefs else '（引擎原生，无 R 编号）'}",
        f"# 故障类型（∈ arena/faults 库）：{'、'.join(kinds_used)}",
        f"# 拓扑基底：{basis}（生成器固定基底，故障/日历/注入计划由本场景定义）",
        "# 校验：python dsl/validate.py validate arena/scenarios/S-%d.yaml" % scene_no,
        "# 干跑：python arena/run_scenario.py --config arena/scenarios/S-%d.yaml --runs-root runtime/scen-dryrun" % scene_no,
        "",
    ])
    doc: dict[str, Any] = {
        "api": "parkdsl/1",
        "source": f"llm-draft+{model}（gen_scenario.py 起草，非文献来源；"
                  f"dsl.validate_dsl 与 arena 干跑双门通过后入库）",
        "park": park,
        "grid_inlets": b["grid_inlets"],
        "substations": b["substations"],
        "links": b["links"],
        "faults": faults_out,
        "calendar": {"shifts": shifts, "events": events_out},
        "scenario": {
            "seed": 1000 + scene_no,
            "duration_sim_s": draft["duration_sim_s"],
            "clock_speed": draft["clock_speed"],
            "description": str(draft["scenario_description"]),
            "agent": {"enabled": True, "model": "mock"},
            "injections": injs_out,
        },
    }
    body = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False,
                          default_flow_style=None, width=110)
    return header + body


def next_scene_no(out_dir: Path | str) -> int:
    """续号：扫 S-<n>.yaml 取最大号 +1（库空则从 201 起）。"""
    mx = 200
    for p in Path(out_dir).glob("S-*.yaml"):
        m = re.match(r"^S-(\d+)\.yaml$", p.name)
        if m:
            mx = max(mx, int(m.group(1)))
    return mx + 1


# ================================================================ 干跑门（④）
DRYRUN_TIMEOUT_S = 480   # 单稿干跑墙上钟上限（防事件密度过高的稿子拖死生成回路）


def dryrun_gate(config: dict, *, runs_root: Path, run_id: str,
                timeout_s: float = DRYRUN_TIMEOUT_S) -> tuple[bool, dict, list[str]]:
    """ArenaEngine 同款路径实跑：detected ≥1 且 0 注入被拒才放行；超时按拒绝计。"""
    import signal

    from arena.engine import ArenaEngine, ScenarioRejected   # 延迟导入（重依赖）
    try:
        ae = ArenaEngine(config, run_id=run_id, runs_root=runs_root)
    except ScenarioRejected as exc:
        return False, {}, [f"场景装载被拒: {'; '.join(exc.reasons)}"]
    if hasattr(signal, "SIGALRM"):     # unix 主线程可用；其余平台退化为不限时
        def _on_alarm(signum, frame):
            raise TimeoutError(f"dryrun exceeded {timeout_s}s")
        old = signal.signal(signal.SIGALRM, _on_alarm)
        signal.alarm(int(timeout_s))
    try:
        summary = ae.run().to_dict()
    except TimeoutError:
        return False, {}, [f"干跑超时（>{int(timeout_s)}s）：事件密度过高/时长过长，拒绝入库"]
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
    detected = int(summary["anomalies"]["detected"])
    rejected = summary["injections"].get("rejected") or []
    reasons: list[str] = []
    if rejected:
        reasons.append("注入被拒: " + "; ".join(
            f"{r.get('fault_id')}: {'; '.join(r.get('reasons') or [])}" for r in rejected))
    if detected < 1:
        reasons.append(f"干跑 detected={detected}（须 ≥1）")
    return not reasons, summary, reasons


# ================================================================ 主流程
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gen_scenario.py", description="LLM 辅助练习场场景生成")
    ap.add_argument("--subject", required=True, help="场景主题（如 台风灾害）")
    ap.add_argument("--n", type=int, default=5, help="期望落盘场景数（默认 5）")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="落盘目录（默认 arena/scenarios/）")
    ap.add_argument("--basis", default="PARK-202", choices=sorted(_BASES), help="拓扑基底")
    ap.add_argument("--max-calls", type=int, default=MAX_CALLS_DEFAULT, help="LLM 调用预算上限")
    ap.add_argument("--model", default=None, help="模型名（默认 glm-4-flash）")
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--no-dry-run", action="store_true", help="跳过 arena 干跑门（不推荐）")
    ap.add_argument("--runs-root", default=str(ROOT / "runtime" / "gen-dryrun"))
    ap.add_argument("--json", action="store_true", help="末尾打印机器可读摘要")
    args = ap.parse_args(argv)

    faultlib = load_fault_summary()
    valid_rs = load_reference_rs()
    gw = ModelGateway(model=args.model, default_model=DEFAULT_MODEL, timeout_s=180)
    if not gw.enabled:
        print("[E-NOKEY] 无 API key（env 优先序 LLM_API_KEY/BIGMODEL_API_KEY/OPENAI_API_KEY）"
              "——fail-closed，不落盘任何产物", file=sys.stderr)
        return 2
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    runs_root = Path(args.runs_root)

    system = build_system_prompt(faultlib)
    accepted: list[dict] = []
    rejected: list[dict] = []
    used_kinds: list[list[str]] = []
    feedback: list[str] | None = None
    scene_no = next_scene_no(out_dir)
    calls = 0

    while len(accepted) < args.n and calls < args.max_calls:
        attempt = len(accepted) + len(rejected) + 1
        try:
            text = gw.chat(system, build_user_prompt(args.subject, args.basis, attempt - 1,
                                                     used_kinds, feedback),
                           temperature=args.temperature, max_tokens=4000)
        except GatewayError as exc:
            print(f"[E-CALL] attempt {attempt}: {exc}", file=sys.stderr)
            rejected.append({"attempt": attempt, "stage": "call", "reasons": [str(exc)]})
            calls += 1
            break   # 通道故障不重试烧预算
        calls += 1

        why: list[str] = []
        stage = "parse"
        draft, why = parse_draft(text)
        yaml_text = None
        detected = None
        if draft is not None:
            stage = "check"
            why = check_draft(draft, basis=args.basis, faultlib=faultlib, valid_rs=valid_rs)
        if draft is not None and not why:
            yaml_text = assemble_yaml(draft, basis=args.basis, scene_no=scene_no,
                                      subject=args.subject, model=gw.model)
            try:
                config = yaml.safe_load(yaml_text)
            except yaml.YAMLError as exc:
                config, why = None, [f"装配 YAML 解析失败: {exc}"]
            if config is not None and not why:
                stage = "dsl"
                why = [e.line() for e in validate_dsl(config, origin=f"<gen S-{scene_no}>")]
        if draft is not None and not why and not args.no_dry_run:
            stage = "dryrun"
            ok, summary, why = dryrun_gate(config, runs_root=runs_root,
                                           run_id=f"gen-draft-{scene_no}")
            if summary:
                detected = int(summary["anomalies"]["detected"])
        if why:
            rejected.append({"attempt": attempt, "stage": stage, "reasons": why[:8],
                             "calls": calls})
            feedback = why
            print(f"  attempt {attempt} REJECT@{stage}（{len(why)} 项）: {why[0][:100]}")
            continue
        path = out_dir / f"S-{scene_no}.yaml"
        path.write_text(yaml_text, encoding="utf-8")
        kinds = sorted({str(f["kind"]) for f in draft["faults"]})
        accepted.append({"file": str(path), "scene": f"S-{scene_no}",
                         "title": str(draft["title"]), "kinds": kinds,
                         "injections": len(draft["injections"]),
                         "detected": detected,
                         "calls": calls})
        used_kinds.append(kinds)
        feedback = None
        print(f"  attempt {attempt} ACCEPT -> {path.name} "
              f"(kinds={','.join(kinds)}; detected={detected}; LLM calls={calls})")
        scene_no += 1

    print(f"[SUMMARY] accepted={len(accepted)}/{args.n} rejected={len(rejected)} "
          f"llm_calls={calls}/{args.max_calls}")
    if args.json:
        print(json.dumps({"accepted": accepted, "rejected": rejected,
                          "calls_used": calls, "calls_budget": args.max_calls},
                         ensure_ascii=False, indent=1))
    return 0 if len(accepted) >= args.n else 1


if __name__ == "__main__":
    sys.exit(main())
