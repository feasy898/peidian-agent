# -*- coding: utf-8 -*-
"""fault.topology · 拓扑适配层（worker-B · 线3）。

与 worker-A 线1（dsl/ 园区网络生成器）的**同构 mock 接口**：本模块定义
worker-A 生成结果对接 fault/ 所需的最小读取面（见 fault/README.md §2）。
worker-A 落位后，用 ``Topology.from_yaml(path)`` 装载其生成物即可替换内置
演示园区（``demo_park()``），fault/ 其余代码零改动。

模型：
- 节点元件：grid_infeed / bus（功率枢纽）；
- 边元件：line / transformer / switchgear（from→to 定向；**端点可为节点或另
  一边元件**，即支持「开关—线路」串联链，如 SG-A01→LN-A1→BUS-A3）；
- 叶元件：pv / bess / evcharger / load / capacitor（at=某母线，无下游）。

元件 ID 约定沿用仓库 ontology/seed.yaml 口径（TX-*/BUS-*/SG-*/LN-*/PV-*/LOAD-*）。
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

__all__ = [
    "KIND_INFEED", "KIND_LINE", "KIND_BUS", "KIND_TX", "KIND_SW",
    "KIND_PV", "KIND_BESS", "KIND_EV", "KIND_LOAD", "KIND_CAP",
    "EDGE_KINDS", "FLEX_KINDS", "NODE_KINDS", "Element", "Topology",
    "demo_park",
]

KIND_INFEED = "grid_infeed"
KIND_LINE = "line"
KIND_BUS = "bus"
KIND_TX = "transformer"
KIND_SW = "switchgear"
KIND_PV = "pv"
KIND_BESS = "bess"
KIND_EV = "evcharger"
KIND_LOAD = "load"
KIND_CAP = "capacitor"

EDGE_KINDS = frozenset({KIND_LINE, KIND_TX, KIND_SW})
FLEX_KINDS = frozenset({KIND_PV, KIND_BESS, KIND_EV, KIND_LOAD, KIND_CAP})
NODE_KINDS = frozenset({KIND_INFEED, KIND_BUS})


@dataclass
class Element:
    """拓扑元件。边元件带 from/to（端点可为节点或边元件，串联链）；叶带 at。"""

    id: str
    kind: str
    name: str = ""
    attrs: dict = field(default_factory=dict)
    frm: Optional[str] = None
    to: Optional[str] = None
    at: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict = {"id": self.id, "kind": self.kind, "name": self.name}
        d.update(self.attrs)
        if self.frm is not None:
            d["from"] = self.frm
        if self.to is not None:
            d["to"] = self.to
        if self.at is not None:
            d["at"] = self.at
        return d


class Topology:
    """园区拓扑只读图。遍历全部确定性（排序后扩展），供检测/诊断/隔离规划复用。"""

    def __init__(self, park_id: str, elements: Iterable[Element]) -> None:
        self.park_id = park_id
        self._els: dict[str, Element] = {}
        for e in elements:
            if e.id in self._els:
                raise ValueError(f"元件 ID 重复: {e.id}")
            self._els[e.id] = e
        self._validate_refs()
        self._cache_downstream: dict[str, list[str]] = {}
        self._at_map: dict[str, list[str]] = {}
        for e in self._els.values():
            if e.kind in FLEX_KINDS and e.at:
                self._at_map.setdefault(e.at, []).append(e.id)
        for k in self._at_map:
            self._at_map[k].sort()

    # ------------------------------------------------------------- 构造/校验
    @classmethod
    def from_dict(cls, d: dict) -> "Topology":
        els = []
        for raw in d.get("elements", []):
            els.append(Element(
                id=str(raw["id"]), kind=str(raw["kind"]),
                name=str(raw.get("name", raw["id"])),
                attrs={k: v for k, v in raw.items()
                       if k not in ("id", "kind", "name", "from", "to", "at")},
                frm=raw.get("from"), to=raw.get("to"), at=raw.get("at"),
            ))
        return cls(park_id=str(d.get("park_id", "PARK-UNKNOWN")), elements=els)

    def _validate_refs(self) -> None:
        for e in self._els.values():
            if e.kind in EDGE_KINDS:
                if not e.frm or not e.to:
                    raise ValueError(f"边元件 {e.id} 缺 from/to")
                if e.frm == e.id or e.to == e.id:
                    raise ValueError(f"边元件 {e.id} 自环")
                for ref in (e.frm, e.to):
                    if ref not in self._els:
                        raise ValueError(f"边元件 {e.id} 引用不存在的元件 {ref}")
                    ref_kind = self._els[ref].kind
                    if ref_kind not in NODE_KINDS and ref_kind not in EDGE_KINDS:
                        raise ValueError(
                            f"边元件 {e.id} 端点 {ref} 类别非法（{ref_kind}）")
                    if ref_kind in EDGE_KINDS and e.kind == KIND_SW and \
                            self._els[ref].kind == KIND_SW:
                        pass  # 开关-开关串联允许（如间隔双断口）
            elif e.kind in FLEX_KINDS:
                if not e.at or e.at not in self._els:
                    raise ValueError(f"叶元件 {e.id} 的 at 引用不存在")
                if self._els[e.at].kind != KIND_BUS:
                    raise ValueError(f"叶元件 {e.id} 只能挂在母线上")
            elif e.kind in NODE_KINDS:
                pass  # grid_infeed / bus：节点元件，无引用约束
            else:
                raise ValueError(f"未知元件类别: {e.kind!r}（{e.id}）")

    # ------------------------------------------------------------- 基础查询
    def ids(self) -> list[str]:
        return sorted(self._els)

    def get(self, eid: str) -> Element:
        if eid not in self._els:
            raise KeyError(f"元件不存在: {eid}")
        return self._els[eid]

    def has(self, eid: str) -> bool:
        return eid in self._els

    def kind_of(self, eid: str) -> str:
        return self.get(eid).kind

    def elements(self) -> list[Element]:
        return [self._els[k] for k in sorted(self._els)]

    def by_kind(self, kind: str) -> list[Element]:
        return [self._els[k] for k in sorted(self._els) if self._els[k].kind == kind]

    def attached(self, bus_id: str) -> list[str]:
        """挂接在某母线上的叶元件 id（确定性排序）。"""
        return list(self._at_map.get(bus_id, []))

    # ------------------------------------------------------------- 图遍历
    def successors(self, eid: str) -> list[str]:
        """功率流出方向的后继元件（确定性排序）。

        节点 → 以其为 from 的边；边 → 其 to + 以其为 from 的边（串联链分叉）。
        """
        e = self._els[eid]
        out: list[str] = []
        if e.kind in EDGE_KINDS and e.to:
            out.append(e.to)
        out.extend(k for k in sorted(self._els)
                   if self._els[k].kind in EDGE_KINDS and self._els[k].frm == eid)
        return sorted(set(out))

    def predecessors(self, eid: str) -> list[str]:
        e = self._els[eid]
        out: list[str] = []
        if e.kind in EDGE_KINDS and e.frm:
            out.append(e.frm)
        out.extend(k for k in sorted(self._els)
                   if self._els[k].kind in EDGE_KINDS and self._els[k].to == eid)
        return sorted(set(out))

    def downstream(self, eid: str) -> list[str]:
        """{eid} ∪ 其下游全部元件（含下游母线上挂接的叶元件）。确定性排序，BFS 防环。"""
        if eid in self._cache_downstream:
            return list(self._cache_downstream[eid])
        out: set[str] = set()
        q: deque[str] = deque([eid])
        while q:
            cur = q.popleft()
            if cur in out:
                continue
            out.add(cur)
            q.extend(self.successors(cur))
            q.extend(self._at_map.get(cur, []))  # 母线上的叶元件计入下游区
        res = sorted(out)
        self._cache_downstream[eid] = res
        return list(res)

    def zone(self, eid: str) -> list[str]:
        """故障隔离区 = 元件自身 + 下游（**有序 list**；第 4 轮确定性治理：
        旧实现返回 set，检测器 payload 派生列表跨进程随字符串哈希漂序）。

        membership 用法（`x in zone`）对 list 同样成立，调用方零改动。"""
        return list(self.downstream(eid))

    def path_to_source(self, eid: str) -> list[str]:
        """eid 到任一电源的最短路径（含 eid，不含电源节点）。无路径返回 []。"""
        best: Optional[list[str]] = None
        for src in self.by_kind(KIND_INFEED):
            p = self._shortest_path(src.id, eid)
            if p is not None and (best is None or len(p) < len(best)):
                best = p
        return best or []

    def _shortest_path(self, src: str, dst: str) -> Optional[list[str]]:
        if src == dst:
            return [src]
        prev: dict[str, Optional[str]] = {src: None}
        q: deque[str] = deque([src])
        while q:
            cur = q.popleft()
            for n in self.successors(cur):
                if n not in prev:
                    prev[n] = cur
                    q.append(n)
        if dst not in prev:
            return None
        path = [dst]
        while prev[path[-1]] is not None:
            path.append(prev[path[-1]])
        return list(reversed(path))

    def upstream_switches(self, eid: str) -> list[str]:
        """eid 到电源路径上的开关（按路径深度近端在前）。"""
        path = self.path_to_source(eid)
        return [x for x in path if self._els[x].kind == KIND_SW]

    def energized(self, switch_states: dict[str, str],
                  blocked: set[str] = frozenset()) -> set[str]:
        """从电源 BFS 的带电元件集合（节点+边）。开关非 CLOSED 不导通，blocked 断开。"""
        energ: set[str] = set()
        q: deque[str] = deque()
        for src in self.by_kind(KIND_INFEED):
            if src.id not in blocked:
                energ.add(src.id)
                q.append(src.id)
        while q:
            cur = q.popleft()
            for nid in self.successors(cur):
                if nid in energ or nid in blocked:
                    continue
                ne = self._els[nid]
                if ne.kind in EDGE_KINDS:
                    if nid in blocked:
                        continue
                    if ne.kind == KIND_SW and switch_states.get(nid) != "CLOSED":
                        continue
                    energ.add(nid)
                    q.append(nid)
                else:
                    energ.add(nid)
                    q.append(nid)
        return energ

    def energized_buses(self, switch_states: dict[str, str],
                        blocked: set[str] = frozenset()) -> set[str]:
        return {x for x in self.energized(switch_states, blocked)
                if self._els[x].kind == KIND_BUS}

    def feeds_closed(self, eid: str, switch_states: dict[str, str]) -> bool:
        """到电源路径上所有开关均为 CLOSED。"""
        return all(switch_states.get(s) == "CLOSED"
                   for s in self.upstream_switches(eid))

    # ------------------------------------------------------------- 隔离规划
    def isolation_cut(self, target: str, switch_states: dict[str, str]) -> list[str]:
        """隔离 target 需断开的开关（当前仍闭合者），确定性排序。

        规则：① target 下游区边界上、区外→区内的闭合开关；② 若 target 本身
        是边元件，附其两端直连开关（形成明显断开点，防反送电）；③ target
        本身是开关则一并断开。
        """
        zone = self.zone(target)
        cut: set[str] = set()
        for eid in sorted(self._els):
            e = self._els[eid]
            if e.kind != KIND_SW:
                continue
            if e.to in zone and e.frm is not None and e.frm not in zone:
                if switch_states.get(eid) == "CLOSED":
                    cut.add(eid)
        te = self._els[target]
        if te.kind in EDGE_KINDS:
            for eid in sorted(self._els):
                e = self._els[eid]
                if e.kind == KIND_SW and (e.frm == target or e.to == target):
                    if switch_states.get(eid) == "CLOSED":
                        cut.add(eid)
            if te.kind == KIND_SW:
                cut.add(target)
        return sorted(cut)

    def to_dict(self) -> dict:
        return {"park_id": self.park_id,
                "elements": [e.to_dict() for e in self.elements()]}


def demo_park() -> Topology:
    """内置演示园区（PARK-DEMO，worker-A 接口同构 mock；参数为演示值 doc 声明）。

    双馈线 + 常开联络开关 SG-TIE（BUS-B2 → BUS-A2），支持倒闸转供演示：
      GRID-A —LN-A0— BUS-A1 —SG-A1H— TX-01(1600kVA) —SG-A02— BUS-A2
        BUS-A2 挂 LOAD-A0 200kW；BUS-A2 —SG-A01— LN-A1 — BUS-A3（LOAD-A1 240kW / PV-01 400kWp）
      GRID-B —LN-B0— BUS-B1 —SG-B1H— TX-02(2500kVA) —SG-B02— BUS-B2
        BUS-B2 挂 LOAD-B0 280kW；BUS-B2 —SG-B01— LN-B1 — BUS-B3（LOAD-B1 280kW）
      SG-TIE（常开）：BUS-B2 → BUS-A2
    """
    els = [
        Element("GRID-A", KIND_INFEED, "电网进线A", {"rated_mw": 20}),
        Element("LN-A0", KIND_LINE, "A区进线", {"rated_kw": 3000}, frm="GRID-A", to="BUS-A1"),
        Element("BUS-A1", KIND_BUS, "10kVⅠ段母线", {"voltage_level": "10kV"}),
        Element("SG-A1H", KIND_SW, "1号主变高压侧开关", {"normally": "CLOSED", "operable": True}, frm="BUS-A1", to="TX-01"),
        Element("TX-01", KIND_TX, "1号主变", {"capacity_kva": 1600, "cooling": "ONAN"}, frm="SG-A1H", to="BUS-A2"),
        Element("SG-A02", KIND_SW, "1号主变低压侧开关", {"normally": "CLOSED", "operable": True}, frm="TX-01", to="BUS-A2"),
        Element("BUS-A2", KIND_BUS, "0.4kVⅠ段母线", {"voltage_level": "0.4kV"}),
        Element("LOAD-A0", KIND_LOAD, "A段基础负荷", {"base_kw": 200}, at="BUS-A2"),
        Element("SG-A01", KIND_SW, "A区出线1开关", {"normally": "CLOSED", "operable": True}, frm="BUS-A2", to="LN-A1"),
        Element("LN-A1", KIND_LINE, "A区出线1", {"rated_kw": 1000}, frm="SG-A01", to="BUS-A3"),
        Element("BUS-A3", KIND_BUS, "A区末端母线", {"voltage_level": "0.4kV"}),
        Element("LOAD-A1", KIND_LOAD, "A区末端负荷", {"base_kw": 240}, at="BUS-A3"),
        Element("PV-01", KIND_PV, "屋顶光伏1", {"capacity_kwp": 400}, at="BUS-A3"),
        Element("GRID-B", KIND_INFEED, "电网进线B", {"rated_mw": 20}),
        Element("LN-B0", KIND_LINE, "B区进线", {"rated_kw": 3000}, frm="GRID-B", to="BUS-B1"),
        Element("BUS-B1", KIND_BUS, "10kVⅡ段母线", {"voltage_level": "10kV"}),
        Element("SG-B1H", KIND_SW, "2号主变高压侧开关", {"normally": "CLOSED", "operable": True}, frm="BUS-B1", to="TX-02"),
        Element("TX-02", KIND_TX, "2号主变", {"capacity_kva": 2500, "cooling": "ONAN"}, frm="SG-B1H", to="BUS-B2"),
        Element("SG-B02", KIND_SW, "2号主变低压侧开关", {"normally": "CLOSED", "operable": True}, frm="TX-02", to="BUS-B2"),
        Element("BUS-B2", KIND_BUS, "0.4kVⅡ段母线", {"voltage_level": "0.4kV"}),
        Element("LOAD-B0", KIND_LOAD, "B段基础负荷", {"base_kw": 280}, at="BUS-B2"),
        Element("SG-B01", KIND_SW, "B区出线1开关", {"normally": "CLOSED", "operable": True}, frm="BUS-B2", to="LN-B1"),
        Element("LN-B1", KIND_LINE, "B区出线1", {"rated_kw": 1000}, frm="SG-B01", to="BUS-B3"),
        Element("BUS-B3", KIND_BUS, "B区末端母线", {"voltage_level": "0.4kV"}),
        Element("LOAD-B1", KIND_LOAD, "B区末端负荷", {"base_kw": 280}, at="BUS-B3"),
        Element("SG-TIE", KIND_SW, "母联联络开关", {"normally": "OPEN", "operable": True}, frm="BUS-B2", to="BUS-A2"),
    ]
    return Topology("PARK-DEMO", els)
