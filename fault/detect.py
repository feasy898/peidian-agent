# -*- coding: utf-8 -*-
"""fault.detect · 异常检测（阈值判 + 拓扑断判 + v1.1 通用信号判据）。

阈值口径：
- 既有四类：regulations/REG-TECH.yaml PHYS-TX-LOAD（过载预警 >0.80 P2 / 重过载
  >1.00 P0）；短路电流信号与塌陷电压为 fault.telemetry 声明的仿真近似值；
- v1.1 通用信号：DEFAULT_CRITERIA（每条带出处：【标准条文】/【工程惯例】标注明细），
  可由外部（arena 故障库/regulations）覆盖注入。

检测器只读遥测与判据，不读注入计划（诚实检测：它"看不见"答案）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .topology import KIND_BUS, KIND_LINE, KIND_PV, KIND_TX, Topology

__all__ = ["Anomaly", "Detector", "Criterion", "DEFAULT_CRITERIA", "METRIC_HINTS",
           "TH_TX_WARN", "TH_TX_TRIP", "TH_SC_CURRENT", "TH_DEAD_BUS", "TH_PV_MIN"]

TH_TX_WARN = 0.80    # REG-TECH PHYS-TX-LOAD：>0.80 过载预警 P2
TH_TX_TRIP = 1.00    # REG-TECH PHYS-TX-LOAD：>1.00 重过载 P0（触发响应）
TH_SC_CURRENT = 4.0  # 电流信号 >4pu 判短路征兆（故障电流≈+6pu，正常≤0.5）
TH_DEAD_BUS = 0.10   # 母线电压 <0.1pu 判失电
TH_PV_MIN = 0.05     # 光伏出力 <5% 装机且日照正常 → 脱网征兆


@dataclass
class Criterion:
    """一条通用信号判据（v1.1）。出处必须标明【标准条文】或【工程惯例】。"""

    comparator: str        # ">" / "<" / "==" / "!="
    threshold: float | str # 数值阈值；字符串判据（如保护模式串）为原样值
    duration_s: float      # 信号持续时间门槛（防抖动误报；0=即时）
    severity: str          # P0 / P2
    source: str            # 出处（带 R 编号=docs/theory/references.md）
    guard: tuple | None = None   # (metric, comparator, value)：防与既有规则叠报
    conflict_hints: tuple = ()   # 同目标存在这些活动异常时抑制本条（主导原因优先）


# v1.1 通用信号判据表（缺省口径；arena/faults 库或 regulations 可覆盖）。
# 出处分级：判据来源见 docs/theory/equipment.md §6（R31–R50）——
# 【标准条文】= 国标/行标明文；【工程惯例】= 行业通行做法，须专家复核后采用。
DEFAULT_CRITERIA: dict[str, Criterion] = {
    "tev_db": Criterion(">", 20, 600, "P2",
                        "TEV >20dB 注意级【工程惯例】（Q/GDW 11060-2013 分级；案例实证 R37）"),
    "contact_temp_c": Criterion(">", 90, 300, "P2",
                                "无线测温告警 90℃【工程惯例】；温升限值基准 GB/T 11022-2020（R35，表3 逐值待核）"),
    "thdu_pct": Criterion(">", 5.0, 900, "P2",
                          "0.38kV THDu ≤5%【标准条文】GB/T 14549-1993（R32）"),
    "neg_seq_unbalance_pct": Criterion(">", 2.0, 900, "P2",
                                       "负序电压不平衡度 ≤2%（短时 4%）【标准条文】GB/T 15543-2008（R33）"),
    "load_ratio": Criterion(">", 1.0, 600, "P0",
                            "线路/母线重载告警【工程惯例】（0.8 预警 / 1.0 告警；TX 走 TX_OVERLOAD 专用规则）"),
    "oil_temp_c": Criterion(">", 85.0, 1800, "P0",
                            "顶层油温不宜经常超过 85℃【行标口径】DL/T 572-2021（R39）；"
                            "同目标有活动 TX_OVERLOAD 时归过载主导，不叠报",
                            conflict_hints=("TX_OVERLOAD",)),
    "dc_insulation_kohm": Criterion("<", 25, 60, "P2",
                                    "220V 直流绝缘告警约 25kΩ【工程惯例】（R41/R42 两套口径冲突，取惯用值）"),
    "phase_voltage_pu": Criterion(">", 1.7, 120, "P0",
                                  "小电流接地非故障相升 √3≈1.73 倍【工程惯例】（R45；GB/T 14285-2023 选线 ≤300Ω，R43）"),
    "phase_current_dev_pct": Criterion(">", 15, 60, "P2",
                                       "相电流差 >15% 告警【工程惯例】（缺相征兆）"),
    "room_temp_c": Criterion(">", 40, 300, "P2",
                             "配电房 >40℃ 告警（运行区间 5~35℃）【工程惯例，DB11/527 体系】"),
    "smoke_alarm": Criterion(">", 0.5, 0, "P0", "烟感触发即告警【工程惯例】"),
    "water_alarm": Criterion(">", 0.5, 0, "P0", "水浸触发即告警【工程惯例】"),
    "relay_error": Criterion(">", 0.5, 60, "P2",
                             "保护装置告警信号（自研口径；处置红线：严禁自改定值，契约 R3）"),
}

# 遥测信号 → 异常 hint（与 fault.dsl FAULT_TYPES 同名；signature 见 fault/agent.py）
METRIC_HINTS: dict[str, str] = {
    "tev_db": "PARTIAL_DISCHARGE",
    "contact_temp_c": "TEMPERATURE_RISE",
    "thdu_pct": "HARMONIC",
    "neg_seq_unbalance_pct": "THREE_PHASE_UNBALANCE",
    "load_ratio": "OVER_LIMIT",
    "oil_temp_c": "TRANSFORMER_FAULT",
    "dc_insulation_kohm": "DC_GROUND_FAULT",
    "phase_voltage_pu": "SINGLE_PHASE_GROUND",
    "phase_current_dev_pct": "PHASE_LOSS",
    "room_temp_c": "ENVIRONMENTAL",
    "smoke_alarm": "ENVIRONMENTAL",
    "water_alarm": "ENVIRONMENTAL",
    "relay_error": "PROTECTION_MALOPERATION",
}


@dataclass
class Anomaly:
    """一条异常（检测器输出；hint/target 是"嫌疑"，非注入答案）。"""

    anomaly_id: str
    hint: str                 # SHORT_CIRCUIT / LINE_BREAK / TX_OVERLOAD / PV_TRIP
    target: str               # 嫌疑元件
    severity: str             # P0/P2
    evidence: dict = field(default_factory=dict)
    first_seen_s: float = 0.0
    status: str = "active"    # active → cleared
    acked: bool = False

    def key(self) -> tuple:
        return (self.hint, self.target)


class Detector:
    """每拍扫描：返回 (new 异常列表, cleared 异常列表)。同键异常不重复上报。"""

    def __init__(self, topo: Topology, criteria: dict[str, Criterion] | None = None,
                 target_criteria: dict[tuple[str, str], Criterion] | None = None) -> None:
        self.topo = topo
        self._seq = 0
        self.active: dict[tuple, Anomaly] = {}
        self.criteria: dict[str, Criterion] = dict(DEFAULT_CRITERIA)
        if criteria:
            self.criteria.update(criteria)
        # 每设备告警配置（element_id, metric）→ 判据：来自园区 DSL faults 节的
        # detection 块——这是园区**配置的监控阈值**（同真实 SCADA 的告警定值），
        # 不是注入计划；检测器据此按设备分压级/分类型判定，诚实性不受影响。
        self.target_criteria: dict[tuple[str, str], Criterion] = dict(target_criteria or {})
        self._since: dict[tuple, float] = {}   # 信号键 → 首次越限仿真秒（持续时间判据）

    # ------------------------------------------------------------------
    def scan(self, sample: dict, switch_states: dict[str, str],
             sim_s: float, energ: set[str]) -> tuple[list[Anomaly], list[Anomaly]]:
        topo = self.topo
        seen_keys: set[tuple] = set()
        new: list[Anomaly] = []

        def raise_anom(hint: str, target: str, severity: str, ev: dict) -> None:
            key = (hint, target)
            seen_keys.add(key)
            if key in self.active:
                self.active[key].evidence = ev  # 证据刷新
                return
            self._seq += 1
            a = Anomaly(f"ANO-{self._seq:03d}", hint, target, severity,
                        ev, sim_s)
            self.active[key] = a
            new.append(a)

        # ① 短路征兆：任一有源边电流 >4pu → 定位=路径最深的越限边
        cand: list[tuple[int, str, dict]] = []
        for eid in topo.ids():
            e = topo.get(eid)
            if e.kind not in (KIND_LINE, KIND_TX):
                continue
            cr = float(sample.get(eid, {}).get("current_ratio", 0.0))
            if cr > TH_SC_CURRENT:
                # payload 边界显式排序（第 4 轮确定性治理：跨 PYTHONHASHSEED 不漂序）
                dead_in_zone = sorted(
                    b for b in topo.zone(eid)
                    if topo.kind_of(b) == KIND_BUS
                    and float(sample.get(b, {}).get("v_pu", 1)) < 0.5)
                cand.append((len(topo.path_to_source(eid)), eid,
                             {"current_ratio": cr,
                              "collapsed_buses": dead_in_zone}))
        if cand:
            cand.sort(key=lambda x: (-x[0], x[1]))  # 路径最深优先，同深按 id
            depth, eid, ev = cand[0]
            ev["basis"] = f"电流 {ev['current_ratio']}pu > {TH_SC_CURRENT}pu 且下游电压塌陷"
            raise_anom("SHORT_CIRCUIT", eid, "P0", ev)

        # ② 断线征兆：失电母线 + 供电通路开关全合 + 路径上"电源侧第一零流边"
        #    （浅者优先：断点=带电区与失电区的边界边；深遍会误选断点下游的
        #    同为零流的主变/线路——整园失电时尤其如此，第 2 轮矩阵实证后修正）
        for bid in topo.ids():
            b = topo.get(bid)
            if b.kind != KIND_BUS:
                continue
            if float(sample.get(bid, {}).get("v_pu", 1)) >= TH_DEAD_BUS:
                continue
            if not topo.feeds_closed(bid, switch_states):
                continue  # 开关分闸导致的失电=计划停运，非异常
            path = topo.path_to_source(bid)
            zero_edges = [x for x in path
                          if topo.kind_of(x) in (KIND_LINE, KIND_TX)
                          and float(sample.get(x, {}).get("current_ratio", 1.0)) < 0.05]
            if zero_edges:
                zero_edges.sort(key=lambda x: (len(topo.path_to_source(x)), x))
                tgt = zero_edges[0]
                raise_anom("LINE_BREAK", tgt, "P0", {
                    "dead_bus": bid,
                    "v_pu": sample[bid]["v_pu"],
                    "zero_flow_edge": tgt,
                    "basis": f"{bid} 失电而供电通路开关全合，电源侧第一零流边为 {tgt}",
                })

        # ③ 变压器过载（阈值 REG-TECH PHYS-TX-LOAD；短路电流信号下不误报——
        #    故障电流 shown 于 current_ratio，>4pu 时按短路征兆处理而非过载）
        for e in topo.by_kind(KIND_TX):
            lr = float(sample.get(e.id, {}).get("load_rate", 0.0))
            cr = float(sample.get(e.id, {}).get("current_ratio", 0.0))
            if lr > TH_TX_TRIP and cr <= TH_SC_CURRENT:
                raise_anom("TX_OVERLOAD", e.id, "P0", {
                    "load_rate": lr, "threshold": TH_TX_TRIP,
                    "oil_temp_c": sample.get(e.id, {}).get("oil_temp_c"),
                    "basis": f"负载率 {lr:.3f} > {TH_TX_TRIP:.2f}（PHYS-TX-LOAD 重过载 P0）",
                })

        # ④ 光伏脱网征兆：日照正常但出力≈0 且母线带电且不在塌陷区
        for e in topo.by_kind(KIND_PV):
            t = sample.get(e.id, {})
            if not t:
                continue
            cap = float(e.attrs.get("capacity_kwp", 0))
            bus = topo.get(e.at)
            if float(t.get("daylight", 0)) > 0.3 \
                    and float(t.get("kw", 0)) < TH_PV_MIN * cap \
                    and bus.id in energ \
                    and float(sample.get(bus.id, {}).get("v_pu", 0)) > 0.9:
                raise_anom("PV_TRIP", e.id, "P2", {
                    "kw": t.get("kw"), "capacity_kwp": cap,
                    "daylight": t.get("daylight"),
                    "basis": f"日照 {t.get('daylight')} 正常而出力 {t.get('kw')}kW ≈ 0（装机 {cap}kWp）",
                })

        # ④.5 v1.1 通用信号判据（诚实检测：只读遥测+判据配置，不读注入计划）
        for eid, sig in sample.items():
            if not isinstance(sig, dict):
                continue
            for metric, hint in METRIC_HINTS.items():
                if metric not in sig:
                    continue
                # 每设备配置优先（园区 DSL faults 节 detection），回退全局判据
                crit = self.target_criteria.get((eid, metric)) \
                    or self.criteria.get(metric)
                if crit is None:
                    continue
                val = sig[metric]
                if isinstance(val, bool):
                    val = 1 if val else 0
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    # 非数值信号（如保护装置模式串）：仅 == / != 可比，其余判据跳过
                    if crit.comparator in ("==", "!="):
                        val = str(val)
                    else:
                        continue
                key = (hint, eid)
                if isinstance(val, str):
                    ok = ((val == str(crit.threshold)) if crit.comparator == "=="
                          else (val != str(crit.threshold)) if crit.comparator == "!="
                          else False)
                else:
                    ok = (val > crit.threshold) if crit.comparator == ">" else \
                         (val < crit.threshold) if crit.comparator == "<" else \
                         (val == crit.threshold)
                if ok and crit.guard is not None:
                    gmetric, gcomp, gval = crit.guard
                    gv = sig.get(gmetric)
                    if gv is not None:
                        try:
                            gv = float(gv)
                        except (TypeError, ValueError):
                            gv = None
                    if gv is not None:
                        gok = (gv > gval) if gcomp == ">" else \
                              (gv < gval) if gcomp == "<" else (gv == gval)
                        if gok:
                            ok = False   # 被既有规则解释（过载温升归 TX_OVERLOAD）
                if ok and crit.conflict_hints:
                    if any((h, eid) in self.active for h in crit.conflict_hints):
                        ok = False       # 主导原因（同目标活动异常）优先，不叠报
                if ok:
                    first = self._since.get(key)
                    if first is None:
                        self._since[key] = sim_s
                        first = sim_s
                    if sim_s - first + 1e-9 >= crit.duration_s:
                        seen_keys.add(key)
                        ev = {"metric": metric, "value": sig[metric],
                              "threshold": crit.threshold,
                              "comparator": crit.comparator,
                              "duration_s": crit.duration_s,
                              "source": crit.source,
                              "basis": f"{metric}={sig[metric]} {crit.comparator} "
                                       f"{crit.threshold} 持续 {crit.duration_s}s"}
                        if key in self.active:
                            self.active[key].evidence = ev
                        else:
                            self._seq += 1
                            a = Anomaly(f"ANO-{self._seq:03d}", hint, eid,
                                        crit.severity, ev, sim_s)
                            self.active[key] = a
                            new.append(a)
                else:
                    self._since.pop(key, None)

        # ⑤ 清除：先前 active 而本轮征兆消失者
        cleared = [a for k, a in self.active.items()
                   if k not in seen_keys and a.status == "active"]
        for a in cleared:
            a.status = "cleared"
        return new, cleared

    def warn_crossings(self, sample: dict, sim_s: float) -> list[dict]:
        """0.8<负载率≤1.0 的预警穿越（只报事件，不建异常）。调用方去重。"""
        out = []
        for e in self.topo.by_kind(KIND_TX):
            lr = float(sample.get(e.id, {}).get("load_rate", 0.0))
            cr = float(sample.get(e.id, {}).get("current_ratio", 0.0))
            if TH_TX_WARN < lr <= TH_TX_TRIP and cr <= TH_SC_CURRENT:
                out.append({"target": e.id, "load_rate": lr, "sim_s": sim_s,
                            "basis": f"负载率 {lr:.3f} 落入预警区（>{TH_TX_WARN:.2f}）"})
        return out
