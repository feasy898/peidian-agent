# -*- coding: utf-8 -*-
"""m4_semantic · Semantic（本体语义层）：本体加载、实体解析、多跳查询、覆盖率监测。

specs/M4-semantic-ontology.md 全部 SPEC 条款（01/02/03/04/05/06/07）的实现入口；
01 §3.4 冻结 API 在此统一导出：

- ``load_ontology(version) -> LoadedOntology``
- ``resolve_entities(text) -> list[ResolvedEntity]``
- ``query_graph(pattern, hops ≤ 3) -> list``
- ``concept_view(entity_ids) -> OntologyView``
- ``coverage_report(window) -> {hits, total, ratio, missing[]}``

数据源：``ontology/*.yaml``（含 aliases.yaml）与 ``regulations/*.yaml``，运行期只读。
"""
from .loader import (
    InstanceLoadError,
    LoadedOntology,
    OntologyLoadError,
    OntologyVersionMismatchError,
    ParkInstance,
    RegistryAlignmentError,
    compute_ontology_version,
    load_ontology,
    load_park_instance,
    resolve_instance_file,
)
from .resolver import EntityResolver, ResolvedEntity, resolve_entities
from .graph import GraphQueryError, OntologyGraph, QUERY_TEMPLATES, query_graph
from .regulation import RegulationIndex, retrieve_rule, search_regulations
from .view import OntologyView, concept_view
from .coverage import CoverageMonitor, coverage_report

__all__ = [
    # loader（SPEC-M4-01/07，ADDENDUM §D）
    "load_ontology", "LoadedOntology", "ParkInstance",
    "load_park_instance", "resolve_instance_file", "compute_ontology_version",
    "OntologyLoadError", "OntologyVersionMismatchError", "RegistryAlignmentError",
    "InstanceLoadError",
    # resolver（SPEC-M4-02）
    "resolve_entities", "ResolvedEntity", "EntityResolver",
    # graph（SPEC-M4-03）
    "query_graph", "OntologyGraph", "QUERY_TEMPLATES", "GraphQueryError",
    # view（SPEC-M4-04）
    "concept_view", "OntologyView",
    # regulation（SPEC-M4-05）
    "RegulationIndex", "retrieve_rule", "search_regulations",
    # coverage（SPEC-M4-06）
    "coverage_report", "CoverageMonitor",
]
