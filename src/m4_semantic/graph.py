# -*- coding: utf-8 -*-
"""m4_semantic.graph · 内存图与三跳查询（specs/M4-semantic-ontology.md SPEC-M4-03）。

- 内存图：networkx MultiDiGraph，节点=园区实例实体（设备/房间/园区/操作员/告警/工单/
  检修计划/负荷曲线…），边=实例关系三元组（方向=声明序 src→dst）。
- 三种查询模式（00 §1.2，mode ID 与 ontology/relations.yaml query_patterns 一致）：
  * alarm_impact      告警影响面：告警→设备→母线→同母线设备；
  * overload_analysis 过载研判：负荷→回路（计量点）→变压器→容量约束（属性拾取）；
  * defect_closure    消缺闭环：工单→告警→设备→检修计划→下次检修（属性拾取）。
- 起点已定位到中间环节时（如只知告警源设备），模板提供 entry 变体，按起点对象类型选择。
- 跳数上限 3：hops>3 或关系步数>3 → 拒绝并建议分解查询（SPEC-M4-03）。
- 属性拾取步（"attribute"）不计入关系跳数，仅从路径末端节点读取约束属性
  （如 capacity_kva / next_due），对应中文路径中"容量约束/下次检修"语义。
"""
from __future__ import annotations

from collections import deque
from typing import Any, Mapping

import networkx as nx

from .loader import LoadedOntology, ParkInstance, load_ontology

__all__ = ["GraphQueryError", "QUERY_TEMPLATES", "OntologyGraph", "query_graph"]

#: 关系跳数上限（00 §1.2：三跳内查询）
MAX_HOPS = 3

#: 00 §1.2 三种查询模式的模板（relation 序列 + 属性拾取；entry=起点对象类型，
#: None=起点已定位到中间环节的变体，按声明序选择首个 entry_type 匹配项）
QUERY_TEMPLATES: dict = {
    "alarm_impact": {
        "name_cn": "告警影响面分析",
        "path_cn": "告警→设备→母线→同母线设备",
        "hops": 3,
        "variants": [
            {"entry_type": "Alarm", "steps": [("raised_by", "out"), ("connected_to", "out"), ("connected_to", "in")]},
            {"entry_type": None, "steps": [("connected_to", "out"), ("connected_to", "in")]},
        ],
    },
    "overload_analysis": {
        "name_cn": "过载研判",
        "path_cn": "负荷→回路→变压器→容量约束",
        "hops": 3,
        "variants": [
            {"entry_type": "LoadCurve", "steps": [("metered_at", "out"), ("upstream_of", "in"), ("attribute", "capacity_kva")]},
            {"entry_type": None, "steps": [("upstream_of", "in"), ("attribute", "capacity_kva")]},
        ],
    },
    "defect_closure": {
        "name_cn": "消缺闭环",
        "path_cn": "工单→告警→设备→检修计划→下次检修",
        "hops": 3,
        "variants": [
            {"entry_type": "WorkOrder", "steps": [("responds_to", "out"), ("raised_by", "out"), ("schedules", "in"), ("attribute", "next_due")]},
            {"entry_type": "Alarm", "steps": [("raised_by", "out"), ("schedules", "in"), ("attribute", "next_due")]},
            {"entry_type": None, "steps": [("schedules", "in"), ("attribute", "next_due")]},
        ],
    },
}


class GraphQueryError(ValueError):
    """图查询非法（起点不存在/跳数超限/模式未知等）。"""


class OntologyGraph:
    """园区实例内存图（networkx MultiDiGraph）+ 三跳内查询。"""

    def __init__(
        self,
        instance: ParkInstance,
        *,
        relation_ids: set | None = None,
        query_pattern_ids: set | None = None,
    ) -> None:
        self.instance = instance
        self.relation_ids = set(relation_ids) if relation_ids is not None else {r[1] for r in instance.relations}
        self.query_pattern_ids = set(query_pattern_ids) if query_pattern_ids is not None else set(QUERY_TEMPLATES)
        self.G = nx.MultiDiGraph()
        for node_id, node in instance.nodes.items():
            self.G.add_node(node_id, type=node.get("type"), attributes=node.get("attributes") or {})
        for src, rel, dst in instance.relations:
            self.G.add_edge(src, dst, key=rel, relation=rel)

    # ------------------------------------------------------------------
    def node(self, node_id: str) -> dict | None:
        data = self.G.nodes.get(node_id)
        if data is None:
            return None
        return {"id": node_id, "type": data.get("type"), "attributes": dict(data.get("attributes") or {})}

    def _step_neighbors(self, node_id: str, relation: str, direction: str) -> list:
        """沿指定关系走一步；direction: out（本节点为 src）/ in（本节点为 dst）/ any。"""
        if direction not in ("out", "in", "any"):
            raise GraphQueryError(f"方向非法: {direction!r}（允许 out/in/any）")
        if relation not in self.relation_ids:
            raise GraphQueryError(f"关系 ID 未在本体注册: {relation!r}")
        found: list = []
        if direction in ("out", "any"):
            for _u, v, _k, data in self.G.out_edges(node_id, keys=True, data=True):
                if data.get("relation") == relation and v not in found:
                    found.append(v)
        if direction in ("in", "any"):
            for u, _v, _k, data in self.G.in_edges(node_id, keys=True, data=True):
                if data.get("relation") == relation and u not in found:
                    found.append(u)
        return found

    def neighborhood(self, node_id: str, hops: int = 2) -> dict:
        """无向邻域（任意关系），返回 {node_id: 距离}（含自身 0）。"""
        if node_id not in self.G:
            return {}
        distances = {node_id: 0}
        frontier = deque([node_id])
        while frontier:
            current = frontier.popleft()
            if distances[current] >= hops:
                continue
            for neighbor in nx.all_neighbors(self.G, current):
                if neighbor not in distances:
                    distances[neighbor] = distances[current] + 1
                    frontier.append(neighbor)
        return distances

    # ------------------------------------------------------------------
    def query(self, pattern: Mapping[str, Any]) -> list:
        """执行查询（01 §3.4 ``query_graph(pattern, hops ≤ 3)``）。

        pattern: {start: 实体 ID, mode: 三模式之一 | steps: [[relation, direction] | ["attribute", 名]...],
                  hops: 声明跳数（≤3，仅作上限校验）}
        返回路径列表：每条 {mode, start, nodes, edges, hops, terminal_attributes}。
        """
        start = pattern.get("start")
        if not start or not isinstance(start, str):
            raise GraphQueryError("pattern.start 必填（起点实体 ID）")
        if start not in self.G:
            raise GraphQueryError(f"查询起点不存在于实例图: {start!r}")

        declared_hops = pattern.get("hops")
        if declared_hops is not None:
            if isinstance(declared_hops, bool) or not isinstance(declared_hops, int):
                raise GraphQueryError(f"pattern.hops 必须为整数，实际 {declared_hops!r}")
            if declared_hops > MAX_HOPS:
                raise GraphQueryError(
                    f"查询跳数 {declared_hops} 超过上限 {MAX_HOPS}："
                    "建议分解为多次三跳内查询（00 §1.2 查询模式）"
                )

        mode = pattern.get("mode")
        steps = pattern.get("steps")
        if steps:
            normalized = self._normalize_steps(steps)
        elif mode:
            normalized, mode = self._template_steps(mode, start)
        else:
            raise GraphQueryError("pattern 需要 mode（三查询模式之一）或 steps（自定义路径）")

        relation_steps = [s for s in normalized if s[0] != "attribute"]
        if len(relation_steps) > MAX_HOPS:
            raise GraphQueryError(
                f"查询路径含 {len(relation_steps)} 跳关系，超过上限 {MAX_HOPS}："
                "建议分解为多次三跳内查询（00 §1.2 查询模式）"
            )

        # 逐层展开：paths = [{nodes: [id...], edges: [(src, rel, dst)...], terminal: {}}]
        paths = [{"nodes": [start], "edges": [], "terminal": None}]
        for step in normalized:
            if step[0] == "attribute":
                for path in paths:
                    tail = path["nodes"][-1]
                    value = self.G.nodes[tail].get("attributes", {}).get(step[1])
                    if path["terminal"] is None:
                        path["terminal"] = {}
                    path["terminal"][step[1]] = value
                continue
            _tag, relation, direction = step
            next_paths = []
            for path in paths:
                tail = path["nodes"][-1]
                for neighbor in self._step_neighbors(tail, relation, direction):
                    if neighbor in path["nodes"]:  # 环路防护
                        continue
                    next_paths.append({
                        "nodes": path["nodes"] + [neighbor],
                        "edges": path["edges"] + [(tail, relation, neighbor)],
                        "terminal": path["terminal"],
                    })
            paths = next_paths
            if not paths:
                break

        results = []
        for path in paths:
            results.append({
                "mode": mode,
                "start": start,
                "nodes": [self.node(nid) for nid in path["nodes"]],
                "edges": [{"src": s, "relation": r, "dst": d} for s, r, d in path["edges"]],
                "hops": len(path["edges"]),
                "terminal_attributes": path["terminal"],
            })
        return results

    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_steps(steps) -> list:
        normalized = []
        for step in steps:
            if not (isinstance(step, (list, tuple)) and len(step) == 2):
                raise GraphQueryError(f"步骤格式错误（须为 [relation, direction] 或 ['attribute', 名]）: {step!r}")
            tag, value = step[0], step[1]
            if tag == "attribute":
                if not value or not isinstance(value, str):
                    raise GraphQueryError(f"属性拾取步须为 ['attribute', 属性名]: {step!r}")
                normalized.append(("attribute", str(value)))
            else:
                if not isinstance(tag, str) or not isinstance(value, str):
                    raise GraphQueryError(f"关系步须为 [relation, direction]: {step!r}")
                normalized.append(("relation", str(tag), str(value)))
        return normalized

    def _template_steps(self, mode: str, start: str) -> tuple:
        if mode not in QUERY_TEMPLATES:
            raise GraphQueryError(
                f"未知查询模式: {mode!r}（支持: {', '.join(sorted(QUERY_TEMPLATES))}）"
            )
        if self.query_pattern_ids and mode not in self.query_pattern_ids:
            raise GraphQueryError(f"本体未声明查询模式: {mode!r}（relations.yaml query_patterns）")
        node_type = self.G.nodes[start].get("type")
        variants = QUERY_TEMPLATES[mode]["variants"]
        variant = next((v for v in variants if v.get("entry_type") == node_type), None)
        if variant is None:
            variant = next((v for v in variants if not v.get("entry_type")), variants[0])
        steps = [("relation", rel, direction) for rel, direction in variant["steps"]
                 if rel != "attribute"]
        steps += [("attribute", value) for rel, value in variant["steps"] if rel == "attribute"]
        return steps, mode


# ---------------------------------------------------------------------------
# 模块级冻结算子（01 §3.4 query_graph）
# ---------------------------------------------------------------------------
def query_graph(pattern: Mapping[str, Any], loaded: LoadedOntology | None = None) -> list:
    """01 §3.4 ``query_graph(pattern: GraphPattern, hops ≤ 3) -> list[GraphNode/Edge]``。

    基于默认实例（loaded.instance）构建内存图并执行查询。
    """
    loaded = loaded or load_ontology()
    if loaded.instance is None:
        raise GraphQueryError("本体未加载园区实例，无法执行图查询")
    graph = OntologyGraph(
        loaded.instance,
        relation_ids=set(loaded.relation_types),
        query_pattern_ids={p.get("id") for p in loaded.query_patterns},
    )
    return graph.query(pattern)
