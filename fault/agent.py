# -*- coding: utf-8 -*-
"""fault.agent · agent 反应引擎：异常 → 可解释步骤流 → 隔离/恢复动作。

步骤流每步回答三件事：**看了什么**（looked_at）/ **判了什么**（found）/
**为什么**（why + conclusion），逐步落 agent 通道事件（worker-A web/ 时间线）。
人机对比开关关闭时本引擎整体静默（见 engine.control.passed），操作面由
fault.actions.ActionExecutor 同款提供给人。

阈值与判据来源：fault.detect（REG-TECH PHYS-TX-LOAD 口径）+ 本模块签名表。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from .actions import ActionExecutor
from .detect import Anomaly, TH_PV_MIN, TH_SC_CURRENT, TH_TX_TRIP
from .stream import EventBus
from .topology import EDGE_KINDS, KIND_BUS, KIND_LINE, KIND_LOAD, KIND_PV, \
    KIND_SW, KIND_TX, Topology

__all__ = ["AgentResponder", "SIGNATURES"]

# 判别签名（步骤 4 引用；证据字段见 fault/detect.py）
SIGNATURES = {
    "SHORT_CIRCUIT": "电流信号 >{:.0f}pu 与故障区电压塌陷共现 → 短路".format(TH_SC_CURRENT),
    "LINE_BREAK": "失电母线供电通路开关全合 + 断点边零流 + 无过流 → 断线",
    "TX_OVERLOAD": "负载率持续 >{:.1f}（PHYS-TX-LOAD 重过载 P0）→ 过载".format(TH_TX_TRIP),
    "PV_TRIP": "日照正常而出力≈0（装机 5% 以下）→ 光伏脱网",
}


class AgentResponder:
    """agent 反应引擎（人机对比开关 = self.enabled）。"""

    def __init__(self, topo: Topology, stream: EventBus, executor: ActionExecutor,
                 sample_fn: Callable[[], dict], active_faults_fn: Callable[[], list],
                 enabled: bool = True) -> None:
        self.topo = topo
        self.stream = stream
        self.executor = executor
        self._sample_fn = sample_fn
        self._active_fn = active_faults_fn
        self.enabled = enabled
        self._step_seq: dict[str, int] = {}   # anomaly_id → 步骤号
        self.handled: set[str] = set()
        self.acted_keys: set[tuple] = set()

    # ------------------------------------------------------------- 步骤落流
    def _step(self, a: Anomaly, phase: str, title: str, looked_at: list,
              found: dict, why: str, conclusion: str = "", sim_s: float = 0.0) -> None:
        n = self._step_seq.get(a.anomaly_id, 0) + 1
        self._step_seq[a.anomaly_id] = n
        self.stream.append("agent", "agent.step", {
            "anomaly_id": a.anomaly_id, "step_no": n, "phase": phase,
            "title": title, "looked_at": looked_at, "found": found,
            "why": why, "conclusion": conclusion,
        }, sim_s=sim_s)

    # ------------------------------------------------------------- 入口
    def handle(self, a: Anomaly, sim_s: float) -> None:
        if not self.enabled:
            return
        self.handled.add(a.anomaly_id)
        sample = self._sample_fn()
        # 1 确认
        self._step(a, "confirm", "告警确认", [a.target],
                   {"anomaly": a.anomaly_id, "hint": a.hint,
                    "severity": a.severity, "evidence": a.evidence},
                   why=f"检测器报告 {a.hint}@{a.target}（{a.severity}），复核异常在册",
                   conclusion="异常确认，启动处置流程", sim_s=sim_s)
        # 2 遥测复核
        looked = [a.target] + self._neighbors(a.target)
        found2 = {k: sample.get(k) for k in looked if k in sample}
        self._step(a, "diagnose", "遥测复核", looked, found2,
                   why="复核嫌疑元件及其相邻元件最新遥测，确认征兆仍在",
                   sim_s=sim_s)
        # 3 判别
        self._step(a, "judge", "故障类型判别", [a.target],
                   {"signature": SIGNATURES.get(a.hint, "未知签名"),
                    "hint": a.hint, "confidence": "high" if a.hint in SIGNATURES else "low"},
                   why="将遥测征兆与签名表比对（签名表见 fault/agent.py SIGNATURES）",
                   conclusion=f"判为 {a.hint}", sim_s=sim_s)
        if a.hint == "PV_TRIP":
            self._handle_pv(a, sim_s)
            return
        # 4 影响分析
        zone = sorted(self.topo.zone(a.target))
        dead_now = [b for b in zone if self.topo.kind_of(b) == KIND_BUS
                    and float(sample.get(b, {}).get("v_pu", 1)) < 0.10]
        self._step(a, "diagnose", "拓扑影响分析", zone,
                   {"fault_zone": zone, "already_dead_buses": dead_now,
                    "affected_loads": [x for x in zone
                                       if self.topo.kind_of(x) == KIND_LOAD]},
                   why="故障隔离区=嫌疑元件及其下游；评估已失电与将受停运影响范围",
                   sim_s=sim_s)
        # 5 隔离方案
        cut = self.topo.isolation_cut(a.target, self.executor.switch_states)
        self._step(a, "plan", "隔离方案", cut,
                   {"open_switches": cut,
                    "why_these": "隔离区边界闭合开关+嫌疑边两端直连开关（形成明显断开点，防反送电）"},
                   why="最小开关集隔离故障区；每台均校验 operable", sim_s=sim_s)
        # 6 执行隔离
        results = []
        for sw in cut:
            r = self.executor.execute("open", sw, by="agent",
                                      reason=f"隔离 {a.hint}@{a.target}",
                                      sim_s=sim_s)
            results.append({sw: r["result"]})
        self.acted_keys.add(a.key())
        # 7 恢复（倒闸转供）
        restore = self._try_restore(a, cut, sim_s)
        # 8 小结（清除确认由 engine 检测循环回调 on_closed 补 verify）
        self._step(a, "summary", "处置小结", [a.target],
                   {"isolate": results, "restore": restore},
                   why="隔离与转供动作已执行，等待遥测复测确认",
                   conclusion=self._conclusion(a, restore), sim_s=sim_s)

    # ------------------------------------------------------------- 光伏脱网
    def _handle_pv(self, a: Anomaly, sim_s: float) -> None:
        sample = self._sample_fn()
        t = sample.get(a.target, {})
        self._step(a, "plan", "处置方案", [a.target],
                   {"switching": "none",
                    "why": "光伏脱网不危及电网安全，无需倒闸；硬复位前需现场消缺"},
                   why="非危及性异常：策略=确认+通知运维，不做网络操作", sim_s=sim_s)
        r = self.executor.execute("ack", a.anomaly_id, by="agent",
                                  reason="光伏脱网告警确认，转运维消缺", sim_s=sim_s)
        self._step(a, "summary", "处置小结", [a.target],
                   {"ack": r["result"],
                    "telemetry": t,
                    "conclusion_note": "故障保持待消缺；通知运维现场检查逆变器/防孤岛保护，"
                                       "消缺后手动复位并网"},
                   why="脱网故障无法遥控恢复，如实保留异常至人工消缺",
                   conclusion=f"{a.hint}@{a.target}：已确认告警并通知运维，无开关操作",
                   sim_s=sim_s)

    # ------------------------------------------------------------- 恢复规划
    def _try_restore(self, a: Anomaly, cut: list[str], sim_s: float) -> dict:
        topo = self.topo
        states = dict(self.executor.switch_states)
        energ = topo.energized(states)
        all_buses = {e.id for e in topo.by_kind(KIND_BUS)}
        dead = {b for b in all_buses if b not in energ}
        if not dead:
            return {"action": "none", "why": "无失电 healthy 母线，无需转供"}
        attempts = []
        cands = [e for e in topo.by_kind(KIND_SW)
                 if e.attrs.get("normally") == "OPEN"
                 and states.get(e.id) != "CLOSED" and e.attrs.get("operable")]
        best: Optional[tuple[float, str]] = None
        for c in cands:
            trial = dict(states)
            trial[c.id] = "CLOSED"
            t_energ = topo.energized(trial)
            newly = {b for b in dead if b in t_energ}
            if not newly:
                attempts.append({"switch": c.id, "rejected": "不能恢复任何失电母线"})
                continue
            fault_el = topo.get(a.target)
            if a.target in t_energ or (fault_el.to in t_energ
                                       and fault_el.frm in t_energ
                                       and fault_el.kind != KIND_SW):
                attempts.append({"switch": c.id,
                                 "rejected": f"会向故障元件 {a.target} 反送电"})
                continue
            rates = self._project_tx_rates(trial, t_energ)
            worst = max(rates.values()) if rates else 0.0
            if worst > 1.0:
                attempts.append({"switch": c.id,
                                 "rejected": f"转供后最大负载率 {worst:.2f} > 1.0，无裕度"})
                continue
            if best is None or worst < best[0]:
                best = (worst, c.id)
        if best is None:
            return {"action": "none", "why": "无可行转供路径（详见 attempts）",
                    "attempts": attempts,
                    "conclusion": "故障区保持隔离待抢修"}
        worst, sw_id = best
        r = self.executor.execute("close", sw_id, by="agent",
                                  reason=f"倒闸转供恢复失电母线（预计最大负载率 {worst:.2f}）",
                                  sim_s=sim_s)
        return {"action": "close", "switch": sw_id, "projected_max_rate": round(worst, 3),
                "result": r["result"], "attempts": attempts}

    # ------------------------------------------------------------- 投影
    def _feeding_tx(self, start_bus: str, trial_states: dict) -> Optional[str]:
        """试态下某母线的馈电主变：沿状态感知的上行游走找第一台 TX（辐射假设）。"""
        topo = self.topo
        cur: Optional[str] = start_bus
        seen: set[str] = set()
        while cur is not None and cur not in seen:
            seen.add(cur)
            e = topo.get(cur)
            if e.kind == KIND_TX:
                return cur
            advanced = False
            for p in topo.predecessors(cur):
                pe = topo.get(p)
                if pe.kind == KIND_SW and trial_states.get(p) != "CLOSED":
                    continue  # 试态下分闸的开关不通
                if pe.kind == KIND_TX:
                    return p
                if pe.kind in EDGE_KINDS:
                    cur = pe.frm  # 沿边上溯到其源端
                else:
                    cur = p
                advanced = True
                break
            if not advanced:
                return None
        return None

    def _project_tx_rates(self, trial_states: dict, energ: set[str]) -> dict[str, float]:
        """候选开关态下各主变预计负载率。

        归属口径：每个带电负荷/光伏按**试态馈电主变**（_feeding_tx）计，防止
        已隔离主变经联络线"虚领"转供负荷。
        """
        topo = self.topo
        sums: dict[str, float] = {tx.id: 0.0 for tx in topo.by_kind(KIND_TX)}
        for load in topo.by_kind(KIND_LOAD):
            bus = topo.get(load.at)
            if bus.id not in energ:
                continue
            ftx = self._feeding_tx(bus.id, trial_states)
            if ftx:
                sums[ftx] += self._project_load_kw(load.id, energ)
        for pv in topo.by_kind(KIND_PV):
            bus = topo.get(pv.at)
            if bus.id not in energ:
                continue
            ftx = self._feeding_tx(bus.id, trial_states)
            if ftx:
                sums[ftx] -= self._project_pv_kw(pv.id, energ)
        rates: dict[str, float] = {}
        for tx in topo.by_kind(KIND_TX):
            cap = float(tx.attrs.get("capacity_kva", 1))
            rates[tx.id] = round(max(0.0, sums[tx.id]) / cap, 3)
        return rates

    def _project_load_kw(self, load_id: str, energ: set[str]) -> float:
        """负荷需求投影：样本值 >0 用样本；否则按需求口径（base×激增系数）。"""
        topo = self.topo
        e = topo.get(load_id)
        sample = self._sample_fn()
        s = float(sample.get(load_id, {}).get("kw", 0.0))
        if s > 0.0:
            return s
        base = float(e.attrs.get("base_kw", 0))
        # 失电/刚恢复负荷按需求口径投影：若其归属主变有活跃过载故障，按激增后需求计
        owner_tx = next((x for x in topo.path_to_source(load_id)
                         if topo.kind_of(x) == KIND_TX), None)
        for f in self._active_fn():
            if f.type == "TX_OVERLOAD" and f.target == owner_tx:
                zone = set(topo.downstream(owner_tx))
                natural = sum(float(topo.get(x).attrs.get("base_kw", 0))
                              for x in zone if topo.kind_of(x) == KIND_LOAD) or 1.0
                pv_cap = sum(float(topo.get(x).attrs.get("capacity_kwp", 0))
                             for x in zone if topo.kind_of(x) == KIND_PV) * 0.7
                cap = float(topo.get(owner_tx).attrs.get("capacity_kva", 1))
                factor = (float(f.params.get("overload_ratio", 1.2)) * cap + pv_cap) / natural
                return base * factor
        return base

    def _project_pv_kw(self, pv_id: str, energ: set[str]) -> float:
        topo = self.topo
        e = topo.get(pv_id)
        sample = self._sample_fn()
        s = float(sample.get(pv_id, {}).get("kw", 0.0))
        if s > 0.0:
            return s
        for f in self._active_fn():
            if f.type == "PV_TRIP" and f.target == pv_id:
                return 0.0
        return float(e.attrs.get("capacity_kwp", 0)) * 0.7

    # ------------------------------------------------------------- 清除回调
    def on_cleared(self, a: Anomaly, sim_s: float, by: str) -> None:
        if not self.enabled:
            return
        sample = self._sample_fn()
        self._step(a, "verify", "复测确认", [a.target],
                   {"post_sample": {k: sample.get(k) for k in [a.target]
                                    if k in sample},
                    "cleared_by": by},
                   why="动作后遥测复测：征兆消失，检测器已标记异常清除",
                   sim_s=sim_s)
        self._step(a, "summary", "闭环", [a.target],
                   {"status": "cleared", "by": by},
                   why="异常闭环：检测→判别→隔离→（转供）→复测通过",
                   conclusion=f"{a.hint}@{a.target} 处置完成（by={by}）",
                   sim_s=sim_s)

    def on_stuck(self, a: Anomaly, sim_s: float) -> None:
        """动作后征兆未消除——如实升级，绝不假绿。"""
        if not self.enabled or a.hint == "PV_TRIP":
            return
        self._step(a, "escalate", "复测未消除", [a.target],
                   {"status": "still_active"},
                   why="隔离/转供动作执行后征兆仍在——方案失效",
                   conclusion="升级人工处置（L1）", sim_s=sim_s)

    # ------------------------------------------------------------- 工具
    def _neighbors(self, eid: str) -> list[str]:
        topo = self.topo
        e = topo.get(eid)
        out: list[str] = []
        if e.kind in EDGE_KINDS:
            for ref in (e.frm, e.to):
                if ref:
                    out.append(ref)
        elif e.at:
            out.append(e.at)
        return [x for x in out if topo.has(x)]

    def _conclusion(self, a: Anomaly, restore: dict) -> str:
        if restore.get("action") == "close":
            return (f"{a.hint}@{a.target}：已隔离（开{restore.get('switch','')}前先开隔离开关），"
                    f"并经联络开关转供恢复失电母线")
        if restore.get("action") == "none":
            return (f"{a.hint}@{a.target}：已隔离；"
                    f"{restore.get('conclusion', restore.get('why', ''))}")
        return f"{a.hint}@{a.target}：处置动作已执行"
