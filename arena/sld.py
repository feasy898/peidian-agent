# -*- coding: utf-8 -*-
"""arena.sld · ParkDSL → SVG 单线图（目标6：人类工程师可理解成果）。

单线图（Single Line Diagram）是电力工程师的标准"阅读语言"——
每种设备用标准符号表示，按电压等级从左到右/从上到下排列。

符号体系（IEC 60617 简化版）：
- 母线：粗水平线
- 变压器：两个相交圆
- 断路器/开关：方框（闭合=实心/打开=空心）
- 线路：直线+阻抗标记
- 负荷：箭头
- 光伏：太阳符号
- 储能：电池符号
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

__all__ = ["generate_sld", "SLDGenerator"]

# SVG 样式常量
_COLORS = {
    "hv": "#2196F3",     # 高压（蓝）
    "lv": "#4CAF50",     # 低压（绿）
    "fault": "#F44336",  # 故障（红）
    "offline": "#9E9E9E", # 失电（灰）
    "normal": "#333",    # 正常（深灰）
    "label": "#555",     # 标签
    "bg": "#FAFAFA",
    "grid": "#E0E0E0",
}

_SYM = {
    "grid_infeed": "⌀",     # 电源
    "bus": "━",             # 母线
    "transformer": "◎◎",    # 变压器（双圆）
    "switchgear": "□",      # 开关
    "line": "──",           # 线路
    "load": "▼",            # 负荷（箭头）
    "pv": "☀",             # 光伏
    "bess": "▮▮",           # 储能
    "evcharger": "⚡",      # 充电桩
}


class SLDGenerator:
    """ParkDSL 导出 JSON → SVG 单线图。"""

    def __init__(self, export: dict):
        self.export = export
        self.nodes = {n["id"]: n for n in export.get("nodes", [])}
        self.links = export.get("links", [])
        self.park = export.get("park", {})
        # 布局参数
        self.w = 1200
        self.h = 800
        self.margin = 60

    def generate(self, switch_states: dict[str, str] | None = None,
                 fault_targets: set[str] | None = None,
                 offline_buses: set[str] | None = None) -> str:
        """生成 SVG 字符串。可传入当前开关状态/故障目标/失电母线做着色。"""
        switch_states = switch_states or {}
        fault_targets = fault_targets or set()
        offline_buses = offline_buses or set()

        # 计算布局（分层：电源→高压母线→变压器→低压母线→负荷）
        layout = self._compute_layout()

        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" '
            f'style="font-family: sans-serif; background: {_COLORS["bg"]}">',
            f'<rect width="100%" height="100%" fill="{_COLORS["bg"]}"/>',
            f'<text x="{self.margin}" y="30" font-size="16" font-weight="bold" '
            f'fill="{_COLORS["normal"]}">{self.park.get("name", "园区单线图")}</text>',
        ]

        # 绘制连线
        for link in self.links:
            svg_parts.append(self._draw_link(link, layout, switch_states, fault_targets))

        # 绘制元件
        for nid, pos in layout.items():
            node = self.nodes.get(nid, {})
            is_fault = nid in fault_targets
            is_offline = nid in offline_buses
            svg_parts.append(self._draw_node(nid, node, pos, is_fault, is_offline, switch_states))

        svg_parts.append("</svg>")
        return "\n".join(svg_parts)

    # ================================================================ 布局
    def _compute_layout(self) -> dict[str, tuple[float, float]]:
        """分层布局：按电压等级排列。返回 {node_id: (x, y)}。"""
        layout = {}
        # 层1: 电源（最左）
        sources = [n for n in self.nodes.values() if n.get("type") == "GridInlet"]
        # 层2: 高压母线（10kV）
        hv_buses = [n for n in self.nodes.values()
                    if n.get("type") == "Bus" and "10" in str(n.get("params", {}).get("voltage_level", ""))]
        # 层3: 变压器
        trafos = [n for n in self.nodes.values() if n.get("type") == "Transformer"]
        # 层4: 低压母线（0.4kV）
        lv_buses = [n for n in self.nodes.values()
                    if n.get("type") == "Bus" and "0.4" in str(n.get("params", {}).get("voltage_level", ""))]
        # 层5: 负荷/DER
        loads = [n for n in self.nodes.values()
                 if n.get("type") in ("Load", "EVCharger", "PV", "BESS")]

        x_step = (self.w - 2 * self.margin) / 5
        y_center = self.h / 2

        # 电源在最左
        for i, n in enumerate(sources):
            layout[n["id"]] = (self.margin + 20, y_center - 100 + i * 200)

        # 高压母线（竖排）
        for i, n in enumerate(sorted(hv_buses, key=lambda x: x["id"])):
            layout[n["id"]] = (self.margin + x_step, self.margin + 100 + i * 180)

        # 变压器（在高低压母线之间）
        for i, n in enumerate(sorted(trafos, key=lambda x: x["id"])):
            layout[n["id"]] = (self.margin + 2 * x_step, self.margin + 100 + i * 180)

        # 低压母线
        for i, n in enumerate(sorted(lv_buses, key=lambda x: x["id"])):
            layout[n["id"]] = (self.margin + 3 * x_step, self.margin + 100 + i * 180)

        # 负荷/DER（最右，分散排列）
        for i, n in enumerate(sorted(loads, key=lambda x: x["id"])):
            col = i // 4
            row = i % 4
            layout[n["id"]] = (self.margin + 4 * x_step + col * 80,
                               self.margin + 60 + row * 140)

        return layout

    # ================================================================ 绘制
    def _draw_node(self, nid: str, node: dict, pos: tuple[float, float],
                   is_fault: bool, is_offline: bool,
                   switch_states: dict) -> str:
        x, y = pos
        ntype = node.get("type", "")
        color = _COLORS["fault"] if is_fault else (
            _COLORS["offline"] if is_offline else _COLORS["normal"])
        sym = _SYM.get(ntype, "○")

        parts = [f'<g transform="translate({x}, {y})">']

        if ntype == "Bus":
            # 母线：粗水平线
            w = 80
            parts.append(f'<line x1="-{w//2}" y1="0" x2="{w//2}" y2="0" '
                        f'stroke="{color}" stroke-width="4" stroke-linecap="round"/>')
        elif ntype == "GridInlet":
            # 电源：圆圈
            parts.append(f'<circle cx="0" cy="0" r="20" fill="none" stroke="{color}" stroke-width="2"/>')
            parts.append(f'<text x="0" y="5" text-anchor="middle" font-size="14" fill="{color}">⌀</text>')
        elif ntype == "Transformer":
            # 变压器：双圆
            parts.append(f'<circle cx="-12" cy="0" r="16" fill="none" stroke="{color}" stroke-width="2"/>')
            parts.append(f'<circle cx="12" cy="0" r="16" fill="none" stroke="{color}" stroke-width="2"/>')
        elif ntype == "Switchgear":
            # 开关：方框（实心=闭合，空心=打开）
            state = switch_states.get(nid, node.get("params", {}).get("state", "CLOSED"))
            fill = color if state == "CLOSED" else "none"
            parts.append(f'<rect x="-12" y="-12" width="24" height="24" fill="{fill}" '
                        f'stroke="{color}" stroke-width="2"/>')
        elif ntype == "PV":
            parts.append(f'<circle cx="0" cy="0" r="14" fill="none" stroke="{color}" stroke-width="2"/>')
            parts.append(f'<text x="0" y="5" text-anchor="middle" font-size="14" fill="{color}">☀</text>')
        elif ntype == "BESS":
            parts.append(f'<rect x="-14" y="-8" width="28" height="16" fill="none" stroke="{color}" stroke-width="2"/>')
            parts.append(f'<line x1="-4" y1="-8" x2="-4" y2="8" stroke="{color}" stroke-width="2"/>')
        elif ntype == "Load":
            # 负荷：箭头
            parts.append(f'<polygon points="0,-14 10,6 -10,6" fill="none" stroke="{color}" stroke-width="2"/>')
        else:
            parts.append(f'<circle cx="0" cy="0" r="12" fill="none" stroke="{color}" stroke-width="2"/>')

        # 标签
        label = nid
        parts.append(f'<text x="0" y="35" text-anchor="middle" font-size="11" '
                    f'fill="{_COLORS["label"]}">{label}</text>')

        # 参数标签（容量等）
        params = node.get("params", {})
        if "capacity_kva" in params:
            parts.append(f'<text x="0" y="50" text-anchor="middle" font-size="9" '
                        f'fill="{_COLORS["label"]}">{params["capacity_kva"]}kVA</text>')
        elif "peak_kw" in params:
            parts.append(f'<text x="0" y="50" text-anchor="middle" font-size="9" '
                        f'fill="{_COLORS["label"]}">{params["peak_kw"]}kW</text>')

        parts.append("</g>")
        return "\n".join(parts)

    def _draw_link(self, link: dict, layout: dict,
                   switch_states: dict, fault_targets: set) -> str:
        frm = link.get("from", "")
        to = link.get("to", "")
        if frm not in layout or to not in layout:
            return ""
        x1, y1 = layout[frm]
        x2, y2 = layout[to]
        color = _COLORS["fault"] if (frm in fault_targets or to in fault_targets) else _COLORS["normal"]
        style = 'stroke-dasharray="8,4"' if link.get("kind") == "coupler" else ""
        return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                f'stroke="{color}" stroke-width="1.5" {style}/>')


def generate_sld(export: dict, **kwargs) -> str:
    """便捷入口：ParkDSL export → SVG。"""
    gen = SLDGenerator(export)
    return gen.generate(**kwargs)
