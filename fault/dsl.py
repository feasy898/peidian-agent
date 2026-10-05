# -*- coding: utf-8 -*-
"""fault.dsl · 故障 DSL：四类既有白名单 + v1.1 论文故障库 11 类的定义/校验/YAML 序列化。

既有白名单（越界即拒，SPEC 来源：owner 夜班令线3-1/3-2）：
  SHORT_CIRCUIT 短路   LINE_BREAK 断线   TX_OVERLOAD 变压器过载   PV_TRIP 光伏脱网

v1.1 扩展（2026-10-01 · 阶段 d）：11 类通用信号故障——注入=信号规则，检测=阈值/
持续时间判据（诚实检测：检测器只读遥测与判据，不读注入计划）。判据出处见
arena/faults/<kind>.yaml 与 docs/theory/（R 编号）。

元件 ID 引用线1拓扑 DSL 约定（ontology/seed.yaml 同名口径；dsl/ 落位后以其生成物为准，
本模块只依赖 fault.topology.Topology 读取面）。
"""
from __future__ import annotations

import copy
import yaml

from .topology import KIND_LINE, KIND_PV, KIND_TX, KIND_BUS, KIND_SW, KIND_LOAD, Topology

__all__ = [
    "FAULT_TYPES", "COMPAT_KINDS", "PARAM_SPECS", "DEFAULT_PARAMS",
    "FaultSpec", "FaultRejected", "parse_fault_yaml", "validate_fault_dict",
    "fault_to_yaml",
]

FAULT_TYPES = ("SHORT_CIRCUIT", "LINE_BREAK", "TX_OVERLOAD", "PV_TRIP",
               "PARTIAL_DISCHARGE", "TEMPERATURE_RISE", "HARMONIC",
               "THREE_PHASE_UNBALANCE", "OVER_LIMIT", "PROTECTION_MALOPERATION",
               "TRANSFORMER_FAULT", "DC_GROUND_FAULT", "PHASE_LOSS",
               "SINGLE_PHASE_GROUND", "ENVIRONMENTAL")

# 类型-元件类别兼容矩阵（越界组合直接拒绝）
COMPAT_KINDS: dict[str, frozenset] = {
    "SHORT_CIRCUIT": frozenset({KIND_LINE, KIND_TX}),
    "LINE_BREAK": frozenset({KIND_LINE}),
    "TX_OVERLOAD": frozenset({KIND_TX}),
    "PV_TRIP": frozenset({KIND_PV}),
    # v1.1 扩展：通用信号故障（信号层 fault.telemetry / 判据层 fault.detect）
    "PARTIAL_DISCHARGE": frozenset({KIND_SW, KIND_TX}),
    "TEMPERATURE_RISE": frozenset({KIND_SW}),
    "HARMONIC": frozenset({KIND_BUS, KIND_LOAD}),
    "THREE_PHASE_UNBALANCE": frozenset({KIND_BUS, KIND_TX, KIND_LOAD}),
    "OVER_LIMIT": frozenset({KIND_LINE, KIND_BUS}),          # TX 越限走 TX_OVERLOAD
    "PROTECTION_MALOPERATION": frozenset({KIND_TX, KIND_LINE}),
    "TRANSFORMER_FAULT": frozenset({KIND_TX}),
    "DC_GROUND_FAULT": frozenset({KIND_BUS}),                # DC 屏挂接母线（演示简化）
    "PHASE_LOSS": frozenset({KIND_LOAD, KIND_LINE}),
    "SINGLE_PHASE_GROUND": frozenset({KIND_BUS, KIND_LINE}),
    "ENVIRONMENTAL": frozenset({KIND_BUS}),                  # 环境量挂接母线（演示简化）
}

# 参数规格：name -> (类型, 约束说明, 校验函数(v,s)->bool, 默认值)
PARAM_SPECS: dict[str, dict] = {
    "SHORT_CIRCUIT": {
        "phase": (str, "single|two|three",
                  lambda v, s: v in ("single", "two", "three"), "three"),
        "impedance_ohm": ((int, float), "(0, 50]",
                          lambda v, s: 0 < float(v) <= 50, 0.1),
        "permanent": (bool, "True/False", lambda v, s: isinstance(v, bool), True),
    },
    "LINE_BREAK": {
        "phase": (str, "single|two|three",
                  lambda v, s: v in ("single", "two", "three"), "single"),
        "permanent": (bool, "True/False", lambda v, s: isinstance(v, bool), True),
    },
    "TX_OVERLOAD": {
        "overload_ratio": ((int, float), "(1.0, 3.0]",
                           lambda v, s: 1.0 < float(v) <= 3.0, 1.2),
        "cause": (str, "自由文本", lambda v, s: bool(str(v).strip()), "下游负荷骤增"),
    },
    "PV_TRIP": {
        "lost_ratio": ((int, float), "(0, 1.0]",
                       lambda v, s: 0 < float(v) <= 1.0, 1.0),
        "reason": (str, "over_voltage|over_frequency|island|equipment",
                   lambda v, s: v in ("over_voltage", "over_frequency", "island",
                                      "equipment"), "over_voltage"),
    },
    # ---- v1.1 扩展（schema 与 arena/faults/<kind>.yaml 对齐）----
    "PARTIAL_DISCHARGE": {
        "baseline_db": ((int, float), "[0,60]", lambda v, s: 0 <= float(v) <= 60, 8),
        "growth_db_per_h": ((int, float), "[0,10]", lambda v, s: 0 <= float(v) <= 10, 1.5),
        "threshold_db": ((int, float), "[5,80]", lambda v, s: 5 <= float(v) <= 80, 20),
        "repair_s": ((int, float), ">0", lambda v, s: 0 < float(v) <= 86400 * 30, 7200),
    },
    "TEMPERATURE_RISE": {
        "ambient_c": ((int, float), "[-20,50]", lambda v, s: -20 <= float(v) <= 50, 30),
        "rise_k_per_h": ((int, float), "[0,60]", lambda v, s: 0 <= float(v) <= 60, 12),
        "limit_c": ((int, float), "[40,200]", lambda v, s: 40 <= float(v) <= 200, 90),
        "repair_s": ((int, float), ">0", lambda v, s: 0 < float(v) <= 86400 * 30, 14400),
    },
    "HARMONIC": {
        "thdu_pct": ((int, float), "[0,30]", lambda v, s: 0 <= float(v) <= 30, 6.5),
        "dominant_order": (int, "[2,25]", lambda v, s: 2 <= int(v) <= 25, 5),
        "repair_s": ((int, float), ">0", lambda v, s: 0 < float(v) <= 86400 * 30, 21600),
    },
    "THREE_PHASE_UNBALANCE": {
        "unbalance_pct": ((int, float), "[0,30]", lambda v, s: 0 <= float(v) <= 30, 4.5),
        "repair_s": ((int, float), ">0", lambda v, s: 0 < float(v) <= 86400 * 30, 21600),
    },
    "OVER_LIMIT": {
        "load_ratio": ((int, float), "(0.8,3]", lambda v, s: 0.8 < float(v) <= 3.0, 1.15),
        "repair_s": ((int, float), ">0", lambda v, s: 0 < float(v) <= 86400 * 30, 10800),
    },
    "PROTECTION_MALOPERATION": {
        "mode": (str, "spurious_trip|failure_to_trip|signal_error",
                 lambda v, s: v in ("spurious_trip", "failure_to_trip", "signal_error"),
                 "signal_error"),
        "repair_s": ((int, float), ">0", lambda v, s: 0 < float(v) <= 86400 * 30, 21600),
    },
    "TRANSFORMER_FAULT": {
        "target_oil_temp_c": ((int, float), "[50,160]", lambda v, s: 50 <= float(v) <= 160, 95),
        "rise_k_per_h": ((int, float), "[0,60]", lambda v, s: 0 <= float(v) <= 60, 6),
        "repair_s": ((int, float), ">0", lambda v, s: 0 < float(v) <= 86400 * 30, 28800),
    },
    "DC_GROUND_FAULT": {
        "insulation_kohm": ((int, float), "(0,100]", lambda v, s: 0 < float(v) <= 100, 8),
        "repair_s": ((int, float), ">0", lambda v, s: 0 < float(v) <= 86400 * 30, 14400),
    },
    "PHASE_LOSS": {
        "current_dev_pct": ((int, float), "[0,100]", lambda v, s: 0 <= float(v) <= 100, 25),
        "repair_s": ((int, float), ">0", lambda v, s: 0 < float(v) <= 86400 * 30, 14400),
    },
    "SINGLE_PHASE_GROUND": {
        "phase_voltage_pu": ((int, float), "[1.0,2.0]", lambda v, s: 1.0 <= float(v) <= 2.0, 1.73),
        "allowed_s": ((int, float), ">0", lambda v, s: 0 < float(v) <= 86400, 7200),
        "repair_s": ((int, float), ">0", lambda v, s: 0 < float(v) <= 86400 * 30, 14400),
    },
    "ENVIRONMENTAL": {
        "mode": (str, "high_temp|smoke|water",
                 lambda v, s: v in ("high_temp", "smoke", "water"), "high_temp"),
        "room_temp_c": ((int, float), "[20,80]", lambda v, s: 20 <= float(v) <= 80, 42),
        "repair_s": ((int, float), ">0", lambda v, s: 0 < float(v) <= 86400 * 30, 7200),
    },
}

DEFAULT_PARAMS = {t: {k: spec[3] for k, spec in specs.items()}
                  for t, specs in PARAM_SPECS.items()}


class FaultRejected(Exception):
    """故障指令被拒绝（白名单/参数/目标越界）。reasons 逐条人读。"""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


class FaultSpec:
    """一条故障事件：作用元件 / 类型 / 时刻 / 参数。"""

    __slots__ = ("fault_id", "type", "target", "at_s", "params", "note")

    def __init__(self, fault_type: str, target: str, at_s: float = 0.0,
                 params: dict | None = None, fault_id: str = "",
                 note: str = "") -> None:
        self.type = fault_type
        self.target = target
        self.at_s = float(at_s)
        self.params = dict(params or {})
        self.fault_id = fault_id
        self.note = note

    def to_dict(self) -> dict:
        return {"fault_id": self.fault_id, "type": self.type,
                "target": self.target, "at_s": self.at_s,
                "params": copy.deepcopy(self.params), "note": self.note}

    def __repr__(self) -> str:  # pragma: no cover
        return f"FaultSpec({self.type}@{self.target} t={self.at_s}s)"


def validate_fault_dict(raw: dict, topo: Topology, *, seq: int = 0) -> FaultSpec:
    """raw dict → 校验 → FaultSpec。任何越界抛 FaultRejected（带全部 reasons）。

    校验顺序（全部通过才放行，绝不默认放行）：
      ① type ∈ 四类白名单；② target 存在于拓扑；③ 类型-元件类别兼容；
      ④ params 键集与取值域；⑤ at_s ≥ 0；⑥ 目标无同型活跃故障由引擎层负责。
    """
    reasons: list[str] = []
    if not isinstance(raw, dict):
        raise FaultRejected(["故障指令必须是映射（dict），收到 " + type(raw).__name__])

    ftype = raw.get("type")
    if ftype not in FAULT_TYPES:
        reasons.append(
            f"类型越界: {ftype!r} 不在四类白名单 {list(FAULT_TYPES)} 内")
        ftype = None

    target = raw.get("target")
    if not isinstance(target, str) or not target:
        reasons.append("target 缺失或非字符串")
    elif not topo.has(target):
        reasons.append(
            f"元件不存在: {target!r}（可用: {','.join(topo.ids())}）")
    elif ftype is not None and topo.kind_of(target) not in COMPAT_KINDS[ftype]:
        reasons.append(
            f"类型-元件不匹配: {ftype} 不能作用于 {topo.kind_of(target)} 类元件 {target}"
            f"（允许类别: {sorted(COMPAT_KINDS[ftype])}）")

    at_raw = raw.get("at_s", 0.0)
    try:
        at_s = float(at_raw)
    except (TypeError, ValueError):
        at_s = -1.0
    if at_s < 0:
        reasons.append(f"at_s 必须为非负数（仿真秒），收到 {at_raw!r}")

    params_in = raw.get("params") or {}
    params: dict = {}
    if ftype is not None:
        if not isinstance(params_in, dict):
            reasons.append("params 必须是映射")
        else:
            specs = PARAM_SPECS[ftype]
            for k, v in params_in.items():
                if k not in specs:
                    reasons.append(f"未知参数 {k!r}（{ftype} 允许: {sorted(specs)}）")
                    continue
                typ, desc, check, _default = specs[k]
                if isinstance(v, bool) and typ is not bool:
                    reasons.append(f"参数 {k} 类型错误: 期望 {typ}，收到布尔")
                elif not isinstance(v, typ):
                    reasons.append(f"参数 {k} 类型错误: 期望 {typ}，收到 {type(v).__name__}")
                elif not check(v, None):
                    reasons.append(f"参数 {k} 越界: {v!r} 违反约束 {desc}")
                else:
                    params[k] = v
            for k, (_typ, _desc, _check, default) in specs.items():
                params.setdefault(k, default)

    if reasons:
        raise FaultRejected(reasons)

    fault_id = str(raw.get("fault_id") or f"FLT-{seq:03d}")
    return FaultSpec(ftype, target, at_s, params, fault_id,
                     note=str(raw.get("note", "")))


def parse_fault_yaml(text: str, topo: Topology) -> FaultSpec:
    """YAML 文本 → FaultSpec（校验同上）。"""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise FaultRejected([f"YAML 解析失败: {exc}"]) from exc
    return validate_fault_dict(raw if isinstance(raw, dict) else {}, topo)


def fault_to_yaml(spec: FaultSpec) -> str:
    """FaultSpec → YAML（roundtrip 稳定：键序固定）。"""
    d = spec.to_dict()
    return yaml.safe_dump(d, allow_unicode=True, sort_keys=False)
