# -*- coding: utf-8 -*-
"""fault.telemetry · 伪实时遥测（确定性，seeded）。

口径（演示简化，README §5 声明）：
- 演示窗内负荷形状恒定（shape=1.0）、日照恒定（daylight=0.7），噪声 ±3%（seed）；
- 母线电压：供电路径通=1.0pu，失电=0；短路叠加塌陷（故障区 0.15pu、父母母线
  0.6pu，声明值）；**短路被隔离（任一侧开关分闸）后故障电流与塌陷即消失**；
- 短路在供电通路有源边上注入故障电流信号 current_ratio ≈ +6.0（仿真近似声明，
  正常 ≤0.5）——供检测器判别，非物理潮流；
- TX_OVERLOAD 以"下游负荷骤增"物理化：按 overload_ratio 反推 surge_kw 增量
  摊到下游负荷（计及光伏抵消），倒闸转供后自然缓解；
- 线路/变压器功率 = 其**电气可达**下游（沿带电元件 BFS）负荷代数和，防串联链
  隔离后重复计入；
- v1.1 通用信号故障（arena/faults 库）：注入=信号规则——爬升类按线性速率封顶
  （局放 dB/触头温度/油温），阶跃类直接置值（谐波/不平衡/绝缘/相电压/环境量）；
  **目标断电即信号消失**（隔离即消除，与隔离型故障语义一致）。
"""
from __future__ import annotations

import random
from collections import deque
from typing import Any

from .topology import KIND_BESS, KIND_BUS, KIND_CAP, KIND_LINE, KIND_LOAD, \
    KIND_PV, KIND_SW, KIND_TX, Topology

__all__ = ["TelemetryModel", "DAYLIGHT", "FAULT_CURRENT_PU", "GENERIC_TYPES"]

DAYLIGHT = 0.7    # 演示恒定日照因子（伪遥测简化声明）
NOISE = 0.03
FAULT_CURRENT_PU = 6.0

# 叶元件（挂接母线的非边元件）——通用信号以所挂母线带电为准（v1.1）
LEAF_KINDS = (KIND_LOAD, KIND_PV, KIND_BESS, KIND_CAP)

# v1.1 通用信号故障集合（注入=信号规则；检测判据见 fault.detect.DEFAULT_CRITERIA）
GENERIC_TYPES = frozenset({
    "PARTIAL_DISCHARGE", "TEMPERATURE_RISE", "HARMONIC", "THREE_PHASE_UNBALANCE",
    "OVER_LIMIT", "PROTECTION_MALOPERATION", "TRANSFORMER_FAULT", "DC_GROUND_FAULT",
    "PHASE_LOSS", "SINGLE_PHASE_GROUND", "ENVIRONMENTAL",
})


class TelemetryModel:
    """给定拓扑 / 开关态 / 已生效故障 → 单拍遥测样本 {element_id: {量测…}}。"""

    def __init__(self, topo: Topology, seed: int = 20261001) -> None:
        self.topo = topo
        self.rng = random.Random(seed)
        self.tick_no = 0

    # ------------------------------------------------------------------
    def sample(self, switch_states: dict[str, str],
               active_faults: list,
               sim_s: float | None = None) -> dict[str, dict[str, Any]]:
        topo = self.topo
        sc_edges = [f for f in active_faults if f.type == "SHORT_CIRCUIT"]
        lb_edges = {f.target for f in active_faults if f.type == "LINE_BREAK"}
        tx_over = {f.target: float(f.params.get("overload_ratio", 1.2))
                   for f in active_faults if f.type == "TX_OVERLOAD"}
        pv_trip = {f.target for f in active_faults if f.type == "PV_TRIP"}
        # 短路只在"仍由电源馈电"时产生故障电流/电压塌陷（隔离后消失）
        sc_fed = {f.target for f in sc_edges if topo.feeds_closed(f.target, switch_states)}
        sc_set = {f.target for f in sc_edges}

        # ① 带电计算（断线边视为导线断裂，阻断下游）
        energ = topo.energized(switch_states, blocked=set(lb_edges))

        # ② 电压塌陷区（仅 fed 短路）
        sag_zone: set[str] = set()
        sag_parent: set[str] = set()
        for eid in sc_fed:
            zone = topo.zone(eid)
            sag_zone |= {x for x in zone if topo.kind_of(x) == KIND_BUS}
            te = topo.get(eid)
            for node in (te.frm, te.to):
                if node and topo.kind_of(node) == KIND_BUS and node not in sag_zone:
                    sag_parent.add(node)

        # ③ TX_OVERLOAD surge 反推（计及光伏抵消）。注意：激增是负荷侧需求，
        #    不随故障变是否被隔离而消失——隔离+转供后由受供主变真实承接。
        surge_kw: dict[str, float] = {}
        for tx_id, ratio in tx_over.items():
            zone = set(topo.downstream(tx_id))
            loads = [x for x in zone if topo.kind_of(x) == KIND_LOAD]
            pvs = [x for x in zone if topo.kind_of(x) == KIND_PV]
            natural = sum(float(topo.get(x).attrs.get("base_kw", 0)) for x in loads)
            pv_cap = sum(float(topo.get(x).attrs.get("capacity_kwp", 0)) for x in pvs) * DAYLIGHT
            cap = float(topo.get(tx_id).attrs.get("capacity_kva", 1.0))
            surge_kw[tx_id] = max(0.0, ratio * cap + pv_cap - natural)

        # ④ 负荷/光伏出样（母线带电且不在塌陷区才有出力）
        out: dict[str, dict[str, Any]] = {}
        for e in topo.elements():
            eid = e.id
            if e.kind == KIND_BUS:
                v = 1.0 if eid in energ else 0.0
                if eid in sag_zone:
                    v = 0.15
                elif eid in sag_parent:
                    v = 0.60
                out[eid] = {"v_pu": v}
            elif e.kind == KIND_LOAD:
                bus = topo.get(e.at)
                kw = 0.0
                if bus.id in energ and bus.id not in sag_zone:
                    kw = float(e.attrs.get("base_kw", 0)) * (1 + self.rng.uniform(-NOISE, NOISE))
                    for tx_id, surge in surge_kw.items():
                        # 只摊派给该故障变下游区内的负荷（分区归属，防跨区误摊）
                        if e.id not in set(topo.downstream(tx_id)):
                            continue
                        zone_loads = [x for x in topo.downstream(tx_id)
                                      if topo.kind_of(x) == KIND_LOAD]
                        zone_sum = sum(float(topo.get(x).attrs.get("base_kw", 0))
                                       for x in zone_loads) or 1.0
                        kw += surge * float(e.attrs.get("base_kw", 0)) / zone_sum
                out[eid] = {"kw": round(kw, 1)}
            elif e.kind == KIND_PV:
                bus = topo.get(e.at)
                kw = 0.0
                if bus.id in energ and bus.id not in sag_zone and eid not in pv_trip:
                    kw = float(e.attrs.get("capacity_kwp", 0)) * DAYLIGHT \
                        * (1 + self.rng.uniform(-NOISE, NOISE))
                out[eid] = {"kw": round(kw, 1), "daylight": DAYLIGHT,
                            "tripped": eid in pv_trip}

        # ⑤ 有源边出样：电气可达下游负荷代数和（防串联链重复计入）
        for e in topo.elements():
            if e.kind not in (KIND_LINE, KIND_TX):
                continue
            kw = 0.0
            if e.id in energ:
                kw = self._elec_net_kw(e.id, energ, out)
            cap = float(e.attrs.get("capacity_kva", 0)) or float(e.attrs.get("rated_kw", 1))
            ratio = kw / cap
            if e.id in sc_fed and (e.id in sc_set or self._sc_path(e.id, sc_fed)):
                ratio += FAULT_CURRENT_PU
            if e.id in lb_edges:
                ratio, kw = 0.0, 0.0
            d: dict[str, Any] = {"kw": round(kw, 1), "current_ratio": round(ratio, 3)}
            if e.kind == KIND_TX:
                d["load_rate"] = round(min(ratio, 9.9), 3)
                d["oil_temp_c"] = round(min(40 + 60 * ratio, 180.0), 1)
            out[e.id] = d

        # ⑤.5 v1.1 通用信号故障（目标断电即信号消失；sim_s=None 时取基线值）
        self._generic_signals(out, active_faults, energ, float(sim_s or 0.0))

        # ⑥ 开关位置（合并写入：不冲掉⑤.5 通用信号，如 tev_db/contact_temp_c）
        for e in topo.elements():
            if e.kind == KIND_SW:
                out[e.id] = {**out.get(e.id, {}),
                             "state": switch_states.get(e.id, "OPEN")}
        return out

    # ------------------------------------------------------------------
    def _generic_signals(self, out: dict[str, dict[str, Any]], active_faults: list,
                         energ: set[str], sim_s: float) -> None:
        """v1.1：已生效通用故障 → 遥测信号。爬升类=线性速率封顶，阶跃类=置值。

        信号只在目标**带电**时出现——隔离/断电即消除（与隔离型故障语义一致）。
        判据（阈值/持续时间）不在此层：检测器按 fault.detect.DEFAULT_CRITERIA
        独立判定（诚实检测：不读注入计划）。
        """
        for f in active_faults:
            if f.type not in GENERIC_TYPES:
                continue
            tgt = f.target
            if not self.topo.has(tgt):
                continue
            te = self.topo.get(tgt)
            if te.kind in LEAF_KINDS:
                # 叶元件（负荷/光伏/储能/电容）不在带电图内：以所挂母线带电为准
                bus = te.at
                if bus is None or bus not in energ:
                    continue
            elif tgt not in energ:
                continue
            p = f.params
            elapsed_h = max(0.0, sim_s - float(getattr(f, "at_s", 0.0) or 0.0)) / 3600.0
            sig = out.setdefault(tgt, {})
            if f.type == "PARTIAL_DISCHARGE":
                base = float(p.get("baseline_db", 8))
                v = min(base + float(p.get("growth_db_per_h", 1.5)) * elapsed_h, 60.0)
                sig["tev_db"] = round(v, 2)
            elif f.type == "TEMPERATURE_RISE":
                amb = float(p.get("ambient_c", 30))
                v = min(amb + float(p.get("rise_k_per_h", 12)) * elapsed_h,
                        float(p.get("limit_c", 90)))
                sig["contact_temp_c"] = round(v, 1)
            elif f.type == "HARMONIC":
                sig["thdu_pct"] = round(float(p.get("thdu_pct", 6.5)), 2)
                sig["dominant_order"] = int(p.get("dominant_order", 5))
            elif f.type == "THREE_PHASE_UNBALANCE":
                sig["neg_seq_unbalance_pct"] = round(float(p.get("unbalance_pct", 4.5)), 2)
            elif f.type == "OVER_LIMIT":
                sig["load_ratio"] = round(float(p.get("load_ratio", 1.15)), 3)
            elif f.type == "PROTECTION_MALOPERATION":
                sig["relay_error"] = str(p.get("mode", "signal_error"))
            elif f.type == "TRANSFORMER_FAULT":
                target = float(p.get("target_oil_temp_c", 95))
                ramp = min(40.0 + float(p.get("rise_k_per_h", 6)) * elapsed_h, target)
                cur = float(sig.get("oil_temp_c", 0.0) or 0.0)
                sig["oil_temp_c"] = round(max(cur, 40.0, ramp), 1)
            elif f.type == "DC_GROUND_FAULT":
                sig["dc_insulation_kohm"] = round(float(p.get("insulation_kohm", 8)), 1)
            elif f.type == "PHASE_LOSS":
                sig["phase_current_dev_pct"] = round(float(p.get("current_dev_pct", 25)), 1)
            elif f.type == "SINGLE_PHASE_GROUND":
                sig["phase_voltage_pu"] = round(float(p.get("phase_voltage_pu", 1.73)), 3)
            elif f.type == "ENVIRONMENTAL":
                mode = str(p.get("mode", "high_temp"))
                if mode == "smoke":
                    sig["smoke_alarm"] = True
                elif mode == "water":
                    sig["water_alarm"] = True
                else:
                    sig["room_temp_c"] = round(float(p.get("room_temp_c", 42)), 1)

    # ------------------------------------------------------------------
    def _elec_net_kw(self, eid: str, energ: set[str], out: dict) -> float:
        """沿带电元件从 eid 下游电气可达区汇总（Σ负荷 − Σ光伏），防环。

        叶元件（负荷/光伏）经母线 attached() 计入，不走 successors（它们不在
        带电图内）。
        """
        topo = self.topo
        e = topo.get(eid)
        start = e.to
        if not start or start not in energ:
            return 0.0
        seen = {eid, e.frm}
        q: deque[str] = deque([start])
        kw = 0.0
        while q:
            cur = q.popleft()
            if cur in seen:
                continue
            seen.add(cur)
            ce = topo.get(cur)
            if ce.kind == KIND_LOAD:
                kw += out.get(cur, {}).get("kw", 0.0)
            elif ce.kind == KIND_PV:
                kw -= out.get(cur, {}).get("kw", 0.0)
            for nid in topo.successors(cur):
                if nid in energ and nid not in seen:
                    q.append(nid)
            for fid in topo.attached(cur):  # 母线挂接负荷/光伏
                if fid in seen:
                    continue
                seen.add(fid)
                fe = topo.get(fid)
                if fe.kind == KIND_LOAD:
                    kw += out.get(fid, {}).get("kw", 0.0)
                elif fe.kind == KIND_PV:
                    kw -= out.get(fid, {}).get("kw", 0.0)
        return max(0.0, kw)

    def _sc_path(self, eid: str, sc_fed: set[str]) -> bool:
        """eid 是否位于某 fed 短路点到电源的供电路径上（故障电流流经）。"""
        topo = self.topo
        for sc in sc_fed:
            path = set(topo.path_to_source(sc))
            if eid in path and eid != sc:
                return True
        return False

    def snapshot_event_payload(self, sample: dict) -> dict:
        """telemetry 通道快照（前端按需拉，非逐拍）。"""
        return {"tick": self.tick_no, "elements": sample}
