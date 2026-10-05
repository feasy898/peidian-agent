# -*- coding: utf-8 -*-
"""m4_semantic.regulation · 规程索引与检索（specs/M4-semantic-ontology.md SPEC-M4-05）。

- 规则 ID → 条款（clauses）+ 判据结构（criterion：metric/criterion 文本/thresholds 阶梯，
  来自 ``regulations/REG-TECH.yaml``；安全/经营/运维条款为 clauses+可选 criteria）；
- 关键词检索（中文无分词：查询串滑窗 2-gram 对 title+clauses+criterion 打分排序）；
- ``rules_for_scope``：对象类型 → 直接约束规则 ID（REG-TECH 条款 scope 字段数据驱动，
  供 OntologyView 注入"直接约束规则 ID"，SPEC-M4-04）；
- ``unknown_rule_ids``：报告类 Artifact 引用的规则 ID 存在性核对（SPEC-M4-05 与
  ADDENDUM §B report.daily@v1 regulation_refs 联动，M2 schema 校验调用）。

规程引用规范（01 §8）：一切规程引用=规则 ID（如 PHYS-TX-LOAD），不引用原文行号。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .loader import LoadedOntology, load_ontology

__all__ = ["RegulationIndex", "retrieve_rule", "search_regulations", "rules_for_scope",
           "rule_id_checker"]

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _ngrams(text: str, size: int = 2) -> set:
    """中文 2-gram 集合（含单个非中文字符词元），用于无分词匹配。"""
    normalized = re.sub(r"\s+", "", str(text))
    grams: set = set()
    if not normalized:
        return grams
    if len(normalized) == 1:
        return {normalized}
    for i in range(len(normalized) - size + 1):
        grams.add(normalized[i:i + size])
    return grams


class RegulationIndex:
    """规则 ID 索引（四份规程文件合一；loader 加载时已做跨文件 ID 唯一性校验）。"""

    def __init__(self, loaded: LoadedOntology) -> None:
        self.loaded = loaded
        self._by_id: dict = {}
        for file_id, data in (loaded.regulations or {}).items():
            for item in (data or {}).get("rules") or []:
                rule_id = item.get("id")
                if not rule_id:
                    continue
                self._by_id[rule_id] = {
                    "rule_id": rule_id,
                    "file": file_id,
                    "title": item.get("title", ""),
                    "category": item.get("category", ""),
                    "scope": item.get("scope"),
                    "parent": item.get("parent"),
                    "clauses": [str(c) for c in item.get("clauses") or []],
                    "criterion": self._criterion(item),
                    "_text": " ".join(filter(None, [
                        str(item.get("title", "")),
                        " ".join(str(c) for c in item.get("clauses") or []),
                        str(item.get("criterion", "") or ""),
                        str((item.get("criteria") or {}).get("metric", "") or ""),
                        str(rule_id),
                    ])),
                }
        # ontology/rules.yaml 注册表核对（规则 ID 必须两侧同源；不一致在 loader 层已拒，
        # 此处仅提供联合视图）
        self.registry_ids = set(loaded.rules or {})

    @staticmethod
    def _criterion(item: Mapping[str, Any]) -> dict:
        """判据结构：REG-TECH 的 metric/criterion/thresholds 或 REG-OP 的 criteria。"""
        criterion: dict = {}
        if item.get("metric"):
            criterion["metric"] = item["metric"]
        if item.get("unit"):
            criterion["unit"] = item["unit"]
        if item.get("criterion"):
            criterion["expression"] = str(item["criterion"])
        if isinstance(item.get("thresholds"), list) and item["thresholds"]:
            criterion["thresholds"] = [dict(t) for t in item["thresholds"]]
        if isinstance(item.get("criteria"), Mapping):
            criterion["metrics"] = dict(item["criteria"])
        return criterion

    # ------------------------------------------------------------------
    def rule_ids(self) -> list:
        """全部可引用规则 ID（排序稳定）。"""
        return sorted(self._by_id)

    def existing_rule_ids(self) -> set:
        return set(self._by_id)

    def unknown_rule_ids(self, refs: Iterable[str]) -> list:
        """引用清单中不存在的规则 ID（SPEC-M4-05：报告引用必须全部可解析）。"""
        return sorted({str(r) for r in refs or ()} - set(self._by_id))

    def get(self, rule_id: str) -> dict | None:
        entry = self._by_id.get(str(rule_id))
        if entry is None:
            return None
        return {k: v for k, v in entry.items() if not k.startswith("_")}

    def retrieve(self, rule_id: str) -> dict:
        """规则 ID → 条款 + 判据结构（未知 ID → KeyError 语义 ValueError）。"""
        entry = self.get(rule_id)
        if entry is None:
            known = "、".join(self.rule_ids())
            raise ValueError(f"未知规则 ID: {rule_id!r}（可引用: {known}）")
        return entry

    def search(self, query: str, limit: int = 5) -> list:
        """关键词检索（2-gram 打分）：返回 [{rule_id, score, clauses, criterion}]，降序。"""
        grams = _ngrams(query)
        if not grams:
            return []
        scored: list = []
        for rule_id, entry in self._by_id.items():
            text_grams = _ngrams(entry["_text"])
            overlap = len(grams & text_grams)
            if overlap:
                item = {k: v for k, v in entry.items() if not k.startswith("_")}
                scored.append({**item, "score": overlap})
        scored.sort(key=lambda x: (-x["score"], x["rule_id"]))
        return scored[: int(limit) if limit else len(scored)]

    def rules_for_scope(self, type_id: str) -> list:
        """对象类型 → 直接约束规则 ID（数据驱动：条款 scope 字段，按 ID 排序）。"""
        return sorted(
            rule_id for rule_id, entry in self._by_id.items()
            if entry.get("scope") == type_id
        )


# ---------------------------------------------------------------------------
# 模块级算子
# ---------------------------------------------------------------------------
def retrieve_rule(rule_id: str, loaded: LoadedOntology | None = None) -> dict:
    """规则 ID → 条款 + 判据结构。"""
    return RegulationIndex(loaded or load_ontology()).retrieve(rule_id)


def rule_id_checker(repo_root: Path | str | None = None,
                    loaded: LoadedOntology | None = None) -> Callable[[Iterable[str]], list]:
    """M4→M2 联动钩子（SPEC-M4-05 / ADDENDUM §B）。

    返回 ``unknown_rule_ids`` 绑定函数，注入 ``InformationLayer(rule_id_checker=…)``
    后，report.daily@v1 等 schema 校验即对 regulation_refs 做规则 ID 存在性核对
    （不存在 → REJECTED，而非仅形态校验）。
    """
    index = RegulationIndex(loaded if loaded is not None
                            else load_ontology(repo_root=repo_root))
    return index.unknown_rule_ids


def search_regulations(query: str, limit: int = 5,
                       loaded: LoadedOntology | None = None) -> list:
    """关键词检索规程条款。"""
    return RegulationIndex(loaded or load_ontology()).search(query, limit=limit)


def rules_for_scope(type_id: str, loaded: LoadedOntology | None = None) -> list:
    """对象类型 → 直接约束规则 ID。"""
    return RegulationIndex(loaded or load_ontology()).rules_for_scope(type_id)
