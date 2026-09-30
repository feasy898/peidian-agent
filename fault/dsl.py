# -*- coding: utf-8 -*-
"""fault.dsl · 故障 DSL：四类故障事件的定义 / 校验 / YAML 序列化。

四类白名单（越界即拒，SPEC 来源：owner 夜班令线3-1/3-2）：
  SHORT_CIRCUIT 短路   LINE_BREAK 断线   TX_OVERLOAD 变压器过载   PV_TRIP 光伏脱网

元件 ID 引用线1拓扑 DSL 约定（ontology/seed.yaml 同名口径；worker-A dsl/ 落位后
以其生成物为准，本模块只依赖 fault.topology.Topology 读取面）。
"""
from __future__ import annotations

import copy
import yaml

from .topology import KIND_LINE, KIND_PV, KIND_TX, KIND_BUS, Topology

__all__ = [
    "FAULT_TYPES", "COMPAT_KINDS", "PARAM_SPECS", "DEFAULT_PARAMS",
    "FaultSpec", "FaultRejected", "parse_fault_yaml", "validate_fault_dict",
    "fault_to_yaml",
]

FAULT_TYPES = ("SHORT_CIRCUIT", "LINE_BREAK", "TX_OVERLOAD", "PV_TRIP")

# 类型-元件类别兼容矩阵（越界组合直接拒绝）
COMPAT_KINDS: dict[str, frozenset] = {
    "SHORT_CIRCUIT": frozenset({KIND_LINE, KIND_TX}),
    "LINE_BREAK": frozenset({KIND_LINE}),
    "TX_OVERLOAD": frozenset({KIND_TX}),
    "PV_TRIP": frozenset({KIND_PV}),
}

# 参数规格：name -> (类型, 约束说明, 校验函数(v,s)->bool, 默认值)
PARAM_SPECS: dict[str, tuple] = {
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
