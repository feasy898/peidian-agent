# -*- coding: utf-8 -*-
"""fault.park_adapter · ParkDSL 导出 JSON（parkdsl-web/1）→ fault.Topology 适配器。

judge 第 2 轮裁决的 kind 映射表落地：grid_infeed↔GRID、line↔LN、transformer↔TX、
bus↔BUS、switchgear↔SG/CB、bess↔BESS、pv↔PV、evcharger↔EVC、load↔LD、capacitor↔CP。

⚠️ 一处对 judge 映射表的**有声偏离**（待仲裁，见 worklog 第 2 轮）：CP 前缀在 ParkDSL
中是**联络点（coupler，常开）**而非电容——dsl/examples/park-complex-01.yaml:66
`{from: BUS-A1, to: BUS-C1, kind: coupler, id: CP-01, state: OPEN}`（文件注释：A–C
联络点常开，闭环校验由此通过）。若按字表把 CP 映射为 capacitor 叶元件，复杂园区将失去
唯一联络通道、倒闸转供不可达。本适配器按域语义实现：links kind=coupler → switchgear
（normally=state, operable）；设备型 Capacitor（如出现）→ capacitor 叶。请 judge 复核。

模型映射：
- nodes：GridInlet→grid_infeed；Bus→bus；Transformer→transformer **边**（沿 direct
  链找两侧母线，高压侧为 from）；Switchgear→switchgear **边**（串联于 direct 链，
  normally=params.state）；Load/EVCharger→load（base_kw=peak_kw/total_power_kw）；
  PV→pv；BESS→bess；Capacitor→capacitor。
  注：EVC 落 KIND_LOAD（按负荷参与潮流，逐字映射见 attrs.src_kind）；BESS/CAP 为
  **潮流中性**叶（fault 引擎不为其建潮流模型），README §9 已声明。
- links：kind=line → line 边（rated_kw≈ampacity_a×进线电压×√3，缺省 3000）；
  kind=coupler → switchgear 边（normally=state，operable）；kind=direct → 不生成
  独立边，被 TX/SG 边与叶挂接吸收；无法吸收的 direct 残链 → 合成内部 DIR-N line 边
  （仅引擎内部用，**非 ParkDSL 权威 ID，永不作为故障目标产出**）。
"""
from __future__ import annotations

from typing import Any

from .topology import (Element, KIND_BESS, KIND_BUS, KIND_CAP, KIND_INFEED,
                       KIND_LINE, KIND_LOAD, KIND_PV, KIND_SW, KIND_TX,
                       Topology)

__all__ = ["park_to_topology", "AdapterError"]

_DIR_SEQ = [0]   # 合成内部 DIR-N 边计数（进程内单调；仅引擎内部用，非 ParkDSL 权威 ID）


class AdapterError(ValueError):
    pass


def _vnom_kv(node: dict) -> float:
    raw = str(node.get("params", {}).get("voltage_level", "0.4kV"))
    digits = "".join(ch for ch in raw if ch.isdigit() or ch == ".")
    try:
        return float(digits) if digits else 0.4
    except ValueError:
        return 0.4


def _rated_kw(ampacity_a: Any, kv: float) -> float:
    try:
        return round(float(ampacity_a) * kv * 1.732, 1)
    except (TypeError, ValueError):
        return 3000.0


def park_to_topology(park_json: dict) -> Topology:
    if not isinstance(park_json, dict) or park_json.get("api") != "parkdsl-web/1":
        raise AdapterError("park JSON 必须是 parkdsl-web/1 导出格式")
    meta = park_json.get("park") or {}
    park_id = str(meta.get("id") or "PARK-UNKNOWN")
    try:
        in_kv = float("".join(c for c in str(meta.get("incoming_voltage", "10kV"))
                              if c.isdigit() or c == ".") or 10.0)
    except ValueError:
        in_kv = 10.0
    nodes: list[dict] = park_json.get("nodes") or []
    links: list[dict] = park_json.get("links") or []
    by_id = {n["id"]: n for n in nodes}
    if len(by_id) != len(nodes):
        raise AdapterError(f"nodes 存在重复 ID（park={park_id}）")

    elements: list[Element] = []
    consumed: set[int] = set()          # 已吸收的 direct link 下标

    # ① 节点型：电源 / 母线
    for n in nodes:
        t = n["type"]
        if t == "GridInlet":
            elements.append(Element(n["id"], KIND_INFEED,
                                    n.get("label") or n["id"], dict(n.get("params", {}))))
        elif t == "Bus":
            elements.append(Element(n["id"], KIND_BUS,
                                    n.get("label") or n["id"], dict(n.get("params", {}))))

    def _direct_nbrs(node_id: str, skip: set[int] = frozenset()) -> list[tuple[int, str]]:
        out = []
        for i, lk in enumerate(links):
            if lk["kind"] != "direct" or i in skip or i in consumed:
                continue
            if lk["from"] == node_id:
                out.append((i, lk["to"]))
            elif lk["to"] == node_id:
                out.append((i, lk["from"]))
        return out

    # ② 叶元件（经 direct 链挂接唯一母线）
    for n in nodes:
        t, nid = n["type"], n["id"]
        if t in ("Load", "EVCharger"):
            base = float(n.get("params", {}).get("peak_kw")
                         or n.get("params", {}).get("total_power_kw") or 0)
            elements.append(Element(nid, KIND_LOAD, n.get("label") or nid,
                                    {"base_kw": base, "src_kind": t}))
        elif t == "PV":
            elements.append(Element(nid, KIND_PV, n.get("label") or nid,
                                    {"capacity_kwp": float(n.get("params", {}).get("capacity_kwp") or 0)}))
        elif t == "BESS":
            elements.append(Element(nid, KIND_BESS, n.get("label") or nid,
                                    dict(n.get("params", {}))))
        elif t in ("Capacitor", "CapacitorBank"):
            elements.append(Element(nid, KIND_CAP, n.get("label") or nid,
                                    dict(n.get("params", {}))))
        else:
            continue
        nbrs = _direct_nbrs(nid)
        buses = [o for _i, o in nbrs if by_id.get(o, {}).get("type") == "Bus"]
        if len(buses) != 1:
            raise AdapterError(f"叶元件 {nid} 应经 direct 链挂接唯一母线（实得 {len(buses)}）")
        elements[-1].at = buses[0]
        for i, o in nbrs:
            if o == buses[0]:
                consumed.add(i)

    # ③ 变压器边 + 链上开关边
    for n in nodes:
        if n["type"] != "Transformer":
            continue
        tx_id = n["id"]
        nbrs = _direct_nbrs(tx_id)
        if len(nbrs) != 2:
            raise AdapterError(f"变压器 {tx_id} 应有两条 direct 链（实得 {len(nbrs)}）")

        def walk(start: int, nid: str) -> list[tuple[int, str]]:
            """沿 direct 链从 TX 邻居走到非开关设备；返回 [(link_idx, node_id), …]。"""
            chain: list[tuple[int, str]] = []
            cur_idx, cur = start, nid
            while True:
                chain.append((cur_idx, cur))
                node = by_id.get(cur)
                if node is None:
                    raise AdapterError(f"direct 链引用未知设备 {cur}")
                if node["type"] != "Switchgear":
                    return chain
                nxt = _direct_nbrs(cur, skip={cur_idx})
                if len(nxt) != 1:
                    raise AdapterError(f"开关 {cur} 的 direct 链分叉/断头（{len(nxt)} 向）")
                cur_idx, cur = nxt[0]

        sides = [walk(i, o) for i, o in nbrs]
        sides.sort(key=lambda s: _vnom_kv(by_id[s[-1][1]])
                   if by_id[s[-1][1]]["type"] == "Bus" else -1.0, reverse=True)
        built: list[str] = []          # 两侧紧邻 TX 的元件 id
        for side in sides:
            terminal = side[-1][1]
            if by_id[terminal]["type"] != "Bus":
                raise AdapterError(f"变压器 {tx_id} 的 direct 链末端不是母线（{terminal}）")
            path = [terminal] + [nid for _i, nid in reversed(side[:-1])] + [tx_id]
            for j in range(1, len(path) - 1):
                m_id = path[j]
                m = by_id[m_id]
                if m["type"] == "Switchgear":
                    state = str(m.get("params", {}).get("state", "CLOSED"))
                    elements.append(Element(m_id, KIND_SW,
                                            m.get("label") or m_id,
                                            {"normally": state, "operable": True,
                                             "src_kind": "Switchgear"},
                                            frm=path[j - 1], to=path[j + 1]))
                else:
                    _DIR_SEQ[0] += 1
                    elements.append(Element(f"DIR-{_DIR_SEQ[0]:03d}", KIND_LINE,
                                            f"内部直连（{path[j - 1]}–{path[j + 1]}）",
                                            {"internal": True}, frm=path[j - 1],
                                            to=path[j + 1]))
            for i, _nid in side:
                consumed.add(i)
            built.append(path[-2])   # 紧邻 TX 的本侧元件（无中间设备时即母线）
        elements.append(Element(tx_id, KIND_TX, n.get("label") or tx_id,
                                dict(n.get("params", {})), frm=built[0], to=built[1]))

    # ④ line / coupler 链接
    for lk in links:
        lp = lk.get("params") or {}
        if lk["kind"] == "line":
            elements.append(Element(str(lk.get("id") or f"LN-{lk['from']}-{lk['to']}"),
                                    KIND_LINE, str(lk.get("id") or "线路"),
                                    {"rated_kw": _rated_kw(lp.get("ampacity_a"), in_kv),
                                     "length_km": lp.get("length_km")},
                                    frm=lk["from"], to=lk["to"]))
        elif lk["kind"] == "coupler":
            elements.append(Element(str(lk.get("id") or f"CP-{lk['from']}-{lk['to']}"),
                                    KIND_SW, str(lk.get("id") or "联络点"),
                                    {"normally": str(lk.get("state") or "OPEN"),
                                     "operable": True, "src_kind": "Coupler"},
                                    frm=lk["from"], to=lk["to"]))

    # ⑤ 残余 direct 直连（兜底：合成内部 DIR 边）
    for i, lk in enumerate(links):
        if lk["kind"] == "direct" and i not in consumed:
            _DIR_SEQ[0] += 1
            elements.append(Element(f"DIR-{_DIR_SEQ[0]:03d}", KIND_LINE,
                                    f"内部直连（{lk['from']}–{lk['to']}）",
                                    {"internal": True}, frm=lk["from"], to=lk["to"]))

    return Topology(park_id, elements)
