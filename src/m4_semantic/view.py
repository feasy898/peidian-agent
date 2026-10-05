# -*- coding: utf-8 -*-
"""m4_semantic.view · OntologyView 预算化概念视图（specs/M4-semantic-ontology.md SPEC-M4-04）。

注入 Context 的概念视图带 token 预算；超预算时按优先级保留、丢弃并登记 trimmed：
- P0 对象核心属性（实例属性 ∩ objects.yaml 声明属性；类型未声明时取实例属性子集）；
- P1 关系邻域（1 跳边：关系 ID + 邻居 ID + 邻居类型）；
- P2 直接约束规则 ID（regulation scope 数据驱动，SPEC-M4-05）；
- 远端路径（≥2 跳邻域）一律不注入，登记为 trimmed（kind=remote_path）。

``OntologyView.to_manifest_source()`` 产出 ContextManifest source 条目
（origin=ONTOLOGY_VIEW，trimmed=true 时上游 Manifest 记录裁剪，SPEC-M4-04 联动 M2）。

token 估算（确定性，无模型调用）：CJK 字符 1 token/字 + 其他连续字母数字串 1 token/串。
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .loader import LoadedOntology, load_ontology

__all__ = ["OntologyView", "concept_view", "estimate_tokens"]

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_@.\-]+")


def estimate_tokens(text: str) -> int:
    """确定性 token 估算：CJK 1/字 + ASCII 词元 1/串（数字/下划线/点/横线并入词元）。"""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    stripped = _CJK_RE.sub(" ", text)
    ascii_words = len(_ASCII_WORD_RE.findall(stripped))
    return cjk + ascii_words


def _dumps(value: Any) -> str:
    """确定性序列化（datetime/date → ISO 字符串；保排序），仅用于 token 估算。"""
    def _default(item: Any) -> str:
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        return str(item)

    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_default)


@dataclass
class OntologyView:
    """概念视图（budget 内的保留内容 + 被裁记录）。"""

    entity_ids: list                       # 请求的实体 ID
    entries: list = field(default_factory=list)   # 保留内容（逐实体）
    tokens: int = 0                        # 视图 token 合计（估算口径）
    token_budget: int = 0                  # 请求预算
    trimmed: list = field(default_factory=list)   # 被裁内容 [{kind, entity_id, detail, est_tokens}]

    @property
    def trimmed_flags(self) -> dict:
        """{entity_id: bool}——该实体是否有内容被裁。"""
        return {t.get("entity_id"): True for t in self.trimmed if t.get("entity_id")}

    def to_manifest_source(self) -> dict:
        """ContextManifest source 条目（type=ONTOLOGY_VIEW；SPEC-M4-04：trimmed 记录）。"""
        return {
            "name": "ontology_view",
            "type": "ONTOLOGY_VIEW",
            "tokens": self.tokens,
            "priority": 2,
            "origin": "ontology_view",
            "trimmed": bool(self.trimmed),
            "entity_ids": list(self.entity_ids),
        }

    def to_dict(self) -> dict:
        return {
            "entity_ids": list(self.entity_ids),
            "entries": [dict(e) for e in self.entries],
            "tokens": self.tokens,
            "token_budget": self.token_budget,
            "trimmed": [dict(t) for t in self.trimmed],
        }


def _core_attributes(loaded: LoadedOntology, node: Mapping[str, Any]) -> dict:
    """对象核心属性：实例属性 ∩ 类型声明属性；类型未声明时按 key 排序取全部（截 8 个）。"""
    attributes = dict(node.get("attributes") or {})
    type_id = node.get("type")
    declared = (loaded.object_types.get(type_id) or {}).get("attributes") if type_id else None
    if declared:
        return {k: attributes[k] for k in declared if k in attributes}
    return {k: attributes[k] for k in sorted(attributes)[:8]}


def _relation_neighborhood(loaded: LoadedOntology, entity_id: str,
                           max_edges: int = 8) -> list:
    """1 跳关系邻域（实例关系三元组；超出 max_edges 由调用方裁剪登记）。"""
    inst = loaded.instance
    if inst is None:
        return []
    edges = []
    for src, rel, dst in inst.relations:
        if src == entity_id:
            edges.append({"relation": rel, "direction": "out", "neighbor": dst,
                          "neighbor_type": (inst.node(dst) or {}).get("type")})
        elif dst == entity_id:
            edges.append({"relation": rel, "direction": "in", "neighbor": src,
                          "neighbor_type": (inst.node(src) or {}).get("type")})
    edges.sort(key=lambda e: (e["relation"], e["neighbor"]))
    return edges


def concept_view(
    entity_ids: Iterable[str],
    token_budget: int = 1024,
    *,
    loaded: LoadedOntology | None = None,
    max_edges: int = 8,
) -> OntologyView:
    """01 §3.4 ``concept_view(entity_ids) -> OntologyView``（按 token 预算裁剪）。

    装配为逐实体三段（core/relation/rule_ids），按实体顺序贪心装箱：
    - 实体头（id+类型）必入（超预算的极端情况整实体不装，登记 trimmed）；
    - 段落无法装入预算时裁掉并记 trimmed（kind=core_attributes/relation_neighborhood/
      constraint_rules）；
    - ≥2 跳邻域（远端路径）不装配，存在时统一登记 trimmed（kind=remote_path）。
    """
    from .graph import OntologyGraph
    from .regulation import RegulationIndex

    loaded = loaded or load_ontology()
    inst = loaded.instance
    view = OntologyView(entity_ids=list(entity_ids), token_budget=int(token_budget))
    if inst is None:
        view.trimmed.append({"kind": "no_instance", "entity_id": None,
                             "detail": "本体未加载园区实例，视图为空", "est_tokens": 0})
        return view

    graph = OntologyGraph(inst, relation_ids=set(loaded.relation_types))
    index = RegulationIndex(loaded)
    budget_left = int(token_budget)

    for entity_id in view.entity_ids:
        node = inst.node(entity_id)
        if node is None:
            view.trimmed.append({"kind": "unknown_entity", "entity_id": entity_id,
                                 "detail": "实体不存在于当前实例", "est_tokens": 0})
            continue

        type_id = node.get("type")
        type_meta = loaded.object_types.get(type_id) or {}
        core = _core_attributes(loaded, node)
        edges_full = _relation_neighborhood(loaded, entity_id, max_edges=max_edges)
        rule_ids = index.rules_for_scope(type_id) if type_id else []

        # 远端路径（≥2 跳）一律不注入：存在即登记（丢弃远端路径，SPEC-M4-04）
        distances = graph.neighborhood(entity_id, hops=2)
        remote = [nid for nid, d in distances.items() if d >= 2]
        if remote:
            view.trimmed.append({
                "kind": "remote_path", "entity_id": entity_id,
                "detail": f"{len(remote)} 个 ≥2 跳远端节点未注入（丢弃远端路径）",
                "est_tokens": estimate_tokens(",".join(sorted(remote))),
            })

        # 段落装箱（顺序：头 → 核心属性 → 关系邻域 → 约束规则 ID）
        entry = {"entity_id": entity_id, "entity_type": type_id,
                 "type_name_cn": type_meta.get("name_cn", "")}
        head_cost = estimate_tokens(_dumps(entry))
        if head_cost > budget_left:
            view.trimmed.append({"kind": "entity_header", "entity_id": entity_id,
                                 "detail": "预算不足以注入实体头，整个实体被裁",
                                 "est_tokens": head_cost})
            continue
        budget_left -= head_cost

        core_json = _dumps(core)
        core_cost = estimate_tokens(core_json) + estimate_tokens("core_attributes")
        if core_cost <= budget_left:
            entry["core_attributes"] = core
            budget_left -= core_cost
        else:
            view.trimmed.append({"kind": "core_attributes", "entity_id": entity_id,
                                 "detail": "核心属性段被裁（预算不足）",
                                 "est_tokens": core_cost})

        edges = edges_full[:max_edges]
        edges_json = _dumps(edges)
        edges_cost = estimate_tokens(edges_json) + estimate_tokens("relations")
        if edges_cost <= budget_left:
            entry["relations"] = edges
            budget_left -= edges_cost
        else:
            view.trimmed.append({"kind": "relation_neighborhood", "entity_id": entity_id,
                                 "detail": "关系邻域段被裁（预算不足）",
                                 "est_tokens": edges_cost})
        if len(edges_full) > len(edges):
            view.trimmed.append({"kind": "relation_neighborhood", "entity_id": entity_id,
                                 "detail": f"关系邻域截断至 {max_edges} 条（原有 {len(edges_full)} 条）",
                                 "est_tokens": estimate_tokens(
                                     _dumps(edges_full[max_edges:]))})

        rules_cost = estimate_tokens(",".join(rule_ids)) + (estimate_tokens("constraint_rule_ids") if rule_ids else 0)
        if rules_cost <= budget_left:
            if rule_ids:
                entry["constraint_rule_ids"] = rule_ids
                budget_left -= rules_cost
        elif rule_ids:
            view.trimmed.append({"kind": "constraint_rules", "entity_id": entity_id,
                                 "detail": "直接约束规则 ID 段被裁（预算不足）",
                                 "est_tokens": rules_cost})

        view.entries.append(entry)

    view.tokens = sum(
        estimate_tokens(_dumps(e)) for e in view.entries
    )
    return view
