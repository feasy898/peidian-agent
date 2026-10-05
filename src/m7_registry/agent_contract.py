# -*- coding: utf-8 -*-
"""m7_registry.agent_contract · AgentContract 资产契约（SPEC-M7-01 AgentAsset 全量）。

AgentContract = 智能体对外承诺的全量契约：六能力域（01 §2.7 CapabilityDomain
封闭集）+ 约束清单（红线/安全/规程绑定）+ 行为目录（12 条黄金种子 ↔ 能力域/
类目绑定，SPEC-M7-06 门禁的数据源）。种子实例落 ``assets/agent_contract_v1.yaml``
（M7 §6 交付物）。

结构::

    contract_id: agent.park-power-ops
    version: 1.0.0
    title: …
    capability_domains:            # 六域齐备（键=CapabilityDomain 字面量）
      PREDICT: {name, description, behaviors[]}
      …
    constraints:                   # 约束清单（每条 id/text/source/assertion）
      - {id: CL-RED-01, text: …, source: …, assertion: unregistered_capability_refused}
    behavior_catalog:              # 行为目录（golden 种子 × 类目 × 能力域）
      - {case_id: case_001, category: normal, domain: MAINTAIN, anchor: behavior:…}
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

__all__ = [
    "CATEGORIES",
    "RED_LINE_CATEGORY",
    "AgentContractError",
    "AgentContract",
    "load_agent_contract",
    "catalog_index",
]

#: 行为目录类目封闭集（M6 §5 DoD：正常/边界/异常/红线代位 四类目 12 条种子）
CATEGORIES = ("normal", "boundary", "exception", "red_line")

#: 红线类目（SPEC-M7-06：该类目 100% 断言，缺任一通过记录 → GATED 失败）
RED_LINE_CATEGORY = "red_line"

_SIX_DOMAINS = ("PREDICT", "DISPATCH", "MAINTAIN", "PLAN", "SELF_HEAL", "TRADE")


class AgentContractError(ValueError):
    """AgentContract 结构校验失败。"""


def _req(data: Mapping, key: str, origin: str) -> Any:
    if key not in data or data[key] in (None, ""):
        raise AgentContractError(f"{origin}: 缺必填字段 {key!r}")
    return data[key]


class AgentContract:
    """AgentContract 资产（AGENT 类型资产的描述子即本结构）。"""

    def __init__(self, contract_id: str, version: str, title: str,
                 capability_domains: dict, constraints: list,
                 behavior_catalog: list, source_path: str | None = None) -> None:
        self.contract_id = contract_id
        self.version = version
        self.title = title
        self.capability_domains = capability_domains
        self.constraints = constraints
        self.behavior_catalog = behavior_catalog
        self.source_path = source_path

    # ------------------------------------------------------------ 构造/校验
    @classmethod
    def from_dict(cls, data: Mapping) -> "AgentContract":
        if not isinstance(data, Mapping):
            raise AgentContractError("AgentContract 必须是对象")
        contract_id = str(_req(data, "contract_id", "AgentContract"))
        version = str(_req(data, "version", "AgentContract"))
        title = str(data.get("title") or contract_id)
        domains = _req(data, "capability_domains", "AgentContract")
        if not isinstance(domains, Mapping):
            raise AgentContractError("AgentContract.capability_domains 必须是对象")
        missing = [d for d in _SIX_DOMAINS if d not in domains]
        if missing:
            raise AgentContractError(
                f"AgentContract 六能力域不齐（缺 {missing}；01§2.7 CapabilityDomain 封闭集）")
        extra = [d for d in domains if d not in _SIX_DOMAINS]
        if extra:
            raise AgentContractError(f"AgentContract 能力域越界: {extra}")
        for name, domain in domains.items():
            if not isinstance(domain, Mapping) or not str(domain.get("description") or ""):
                raise AgentContractError(f"capability_domains.{name} 缺 description")

        constraints = data.get("constraints") or []
        if not isinstance(constraints, list) or not constraints:
            raise AgentContractError("AgentContract.constraints 必须是非空清单（约束清单）")
        seen_ids: set = set()
        for item in constraints:
            if not isinstance(item, Mapping):
                raise AgentContractError("constraints[] 条目必须是对象")
            cid = str(_req(item, "id", "constraints[]"))
            if cid in seen_ids:
                raise AgentContractError(f"constraints[] id 重复: {cid}")
            seen_ids.add(cid)
            _req(item, "text", f"constraints[{cid}]")
            if not str(item.get("assertion") or ""):
                raise AgentContractError(f"constraints[{cid}] 缺 assertion（可断言口径）")

        catalog = data.get("behavior_catalog") or []
        if not isinstance(catalog, list) or not catalog:
            raise AgentContractError("AgentContract.behavior_catalog 必须是非空清单")
        seen_cases: set = set()
        for item in catalog:
            if not isinstance(item, Mapping):
                raise AgentContractError("behavior_catalog[] 条目必须是对象")
            case_id = str(_req(item, "case_id", "behavior_catalog[]"))
            if case_id in seen_cases:
                raise AgentContractError(f"behavior_catalog case_id 重复: {case_id}")
            seen_cases.add(case_id)
            category = str(_req(item, "category", f"behavior_catalog[{case_id}]"))
            if category not in CATEGORIES:
                raise AgentContractError(
                    f"behavior_catalog[{case_id}].category 越界 {category!r}"
                    f"（封闭集 {'/'.join(CATEGORIES)}）")
            domain = str(_req(item, "domain", f"behavior_catalog[{case_id}]"))
            if domain not in _SIX_DOMAINS:
                raise AgentContractError(
                    f"behavior_catalog[{case_id}].domain 越界 {domain!r}")
            _req(item, "anchor", f"behavior_catalog[{case_id}]")
        return cls(contract_id, version, title, dict(domains),
                   list(constraints), list(catalog))

    def to_dict(self) -> dict:
        return {
            "contract_id": self.contract_id, "version": self.version,
            "title": self.title, "capability_domains": self.capability_domains,
            "constraints": self.constraints,
            "behavior_catalog": self.behavior_catalog,
        }

    # ------------------------------------------------------------ 读取面
    def red_line_cases(self) -> list:
        """红线类目案例清单（SPEC-M7-06 100% 断言对象）。"""
        return [str(item["case_id"]) for item in self.behavior_catalog
                if str(item.get("category")) == RED_LINE_CATEGORY]

    def catalog_entries(self) -> list:
        return [dict(item) for item in self.behavior_catalog]

    def entry_of(self, case_id: str) -> dict | None:
        for item in self.behavior_catalog:
            if str(item.get("case_id")) == str(case_id):
                return dict(item)
        return None


def load_agent_contract(path: Path | str) -> AgentContract:
    """从 YAML 文件装载（如 ``assets/agent_contract_v1.yaml``）。"""
    source = Path(path)
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise AgentContractError(f"AgentContract 文件无法读取: {source} ({exc})") from exc
    contract = AgentContract.from_dict(data)
    contract.source_path = str(source)
    return contract


def catalog_index(contract: AgentContract) -> dict:
    """case_id → {category, domain, anchor} 索引（门禁/成绩单装配用）。"""
    return {str(item["case_id"]): {"category": str(item["category"]),
                                   "domain": str(item["domain"]),
                                   "anchor": str(item["anchor"])}
            for item in contract.behavior_catalog}
