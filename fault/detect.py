# -*- coding: utf-8 -*-
"""fault.detect · 异常检测（阈值判 + 拓扑断判），输入=遥测样本，输出=异常事件。

阈值口径（doc 来源：仓库 regulations/REG-TECH.yaml PHYS-TX-LOAD —— 过载预警
>0.80 P2 / 重过载 >1.00 P0）；短路电流信号与塌陷电压为 fault.telemetry 声明的
仿真近似值。检测器只读遥测与开关态，不读注入计划（诚实检测：它"看不见"答案）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .topology import KIND_BUS, KIND_LINE, KIND_PV, KIND_TX, Topology

__all__ = ["Anomaly", "Detector", "TH_TX_WARN", "TH_TX_TRIP",
           "TH_SC_CURRENT", "TH_DEAD_BUS", "TH_PV_MIN"]

TH_TX_WARN = 0.80    # REG-TECH PHYS-TX-LOAD：>0.80 过载预警 P2
TH_TX_TRIP = 1.00    # REG-TECH PHYS-TX-LOAD：>1.00 重过载 P0（触发响应）
TH_SC_CURRENT = 4.0  # 电流信号 >4pu 判短路征兆（故障电流≈+6pu，正常≤0.5）
TH_DEAD_BUS = 0.10   # 母线电压 <0.1pu 判失电
TH_PV_MIN = 0.05     # 光伏出力 <5% 装机且日照正常 → 脱网征兆


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

    def __init__(self, topo: Topology) -> None:
        self.topo = topo
        self._seq = 0
        self.active: dict[tuple, Anomaly] = {}

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
                dead_in_zone = [b for b in topo.zone(eid)
                                if topo.kind_of(b) == KIND_BUS
                                and float(sample.get(b, {}).get("v_pu", 1)) < 0.5]
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
