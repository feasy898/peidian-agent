# -*- coding: utf-8 -*-
"""m3_action.registry · 能力注册表（CapabilityDescriptor：参数 schema+风险声明+幂等键策略）。

三事实区分（SPEC-M3-01）：模型看见（Context Tool Descriptor，M2）≠ 注册（本注册表）
≠ 授权（policy_engine）。注册表是"存在性"权威：
- 16 个动作独立注册（SPEC-M3-03：``create.switch_order`` 与 ``execute.remote_control``
  严禁合并；注册表与 ``ontology/actions.yaml`` 的 diff 必须为空——CI 断言）；
- 风险声明（risk_level/reversible/compensation）与缺省 Policy/policy_locked 均以
  ``ontology/actions.yaml`` 为数据源（运行期只读），代码不重复声明；
- 参数 schema 与幂等键策略来自 ``tools/`` 适配器声明（tools/__init__.ADAPTERS）。

冻结 API（01 §3.3）：``register_capability(capability: CapabilityDescriptor) -> CapabilityId``。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from contracts import PolicyDecision, RiskLevel

__all__ = [
    "CapabilityDescriptor",
    "CapabilityRegistry",
    "IMMUTABLE_DENY_ACTIONS",
    "PERMANENT_ASK_ACTIONS",
    "load_default_registry",
    "load_actions_table",
    "registry_vs_actions_table_diff",
    "assert_immutable_consistency",
]

# ---------------------------------------------------------------------------
# 不可改清单（硬编码第一重表达，SPEC-M3-05）
# ---------------------------------------------------------------------------
#: 缺省 DENY 永久不可覆盖（任何角色/审批均不可翻转）——与 ontology/actions.yaml
#: 中 default_policy=DENY 且 policy_locked=true 的集合一致（CI 断言第二重表达）。
IMMUTABLE_DENY_ACTIONS = frozenset({
    "modify.protection_setting",
    "modify.asset_history",
    "bypass.approval",
})

#: 缺省 ASK 永久（审批只放行单次，不改缺省）——同上双重表达。
PERMANENT_ASK_ACTIONS = frozenset({"execute.remote_control"})

#: 幂等键策略受控集
IDEMPOTENCY_POLICIES = frozenset({"CALLER_PROVIDED", "CALLER_PROVIDED_UNIQUE_ARGS"})


def default_repo_root() -> Path:
    """仓库根 = src/m3_action/ 的上两级（pathlib 推断，不依赖 cwd）。"""
    return Path(__file__).resolve().parents[2]


def load_actions_table(repo_root: Path | str | None = None) -> dict:
    """读 ontology/actions.yaml（动作表数据权威，运行期只读）。"""
    root = Path(repo_root) if repo_root else default_repo_root()
    data = yaml.safe_load((root / "ontology" / "actions.yaml").read_text(encoding="utf-8"))
    return {action["id"]: action for action in (data.get("actions") or [])}


# ---------------------------------------------------------------------------
# CapabilityDescriptor
# ---------------------------------------------------------------------------
@dataclass
class CapabilityDescriptor:
    """能力描述符：注册事实（schema+风险声明+幂等键策略+披露面）。

    风险/缺省 Policy 字段与 ontology/actions.yaml 同源；``adapter`` 为
    tools/ 适配器模块（SIMULATION 实作 + REAL mock 签名）。
    """

    capability_id: str                    # "动作ID@版本"
    action_id: str
    version: str
    name_cn: str
    risk_level: RiskLevel
    reversible: bool
    compensation: str | None
    default_policy: PolicyDecision
    policy_locked: bool
    params_schema: dict = field(default_factory=dict)
    idempotency_key_policy: str = "CALLER_PROVIDED"
    write_class: bool = False
    disclosed_roles: list = field(default_factory=list)  # 空 = 对全部角色披露
    adapter: Any = None                    # tools 适配器模块（可选：策略类注册可无执行器）

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CapabilityDescriptor":
        disclosed = list(data.get("disclosed_roles") or [])
        adapter = data.get("adapter")
        if isinstance(adapter, str):
            adapter = _load_adapter_module(adapter)
        policy = data.get("default_policy")
        return cls(
            capability_id=str(data["capability_id"]),
            action_id=str(data["action_id"]),
            version=str(data["version"]),
            name_cn=str(data.get("name_cn", "")),
            risk_level=RiskLevel(str(data["risk_level"])),
            reversible=bool(data.get("reversible", False)),
            compensation=data.get("compensation"),
            default_policy=policy if isinstance(policy, PolicyDecision)
            else PolicyDecision(str(policy)),
            policy_locked=bool(data.get("policy_locked", False)),
            params_schema=dict(data.get("params_schema") or {}),
            idempotency_key_policy=str(data.get("idempotency_key_policy",
                                                "CALLER_PROVIDED")),
            write_class=bool(data.get("write_class", False)),
            disclosed_roles=disclosed,
            adapter=adapter,
        )

    def validate(self) -> None:
        """注册时自校验：capability_id 格式、幂等策略受控、版本一致。"""
        if "@" not in self.capability_id:
            raise ValueError(f"capability_id 必须为 '动作ID@版本' 格式: {self.capability_id!r}")
        action_part, _, version_part = self.capability_id.partition("@")
        if not action_part or not version_part:
            raise ValueError(f"capability_id 的动作 ID 与版本均不能为空: {self.capability_id!r}")
        if action_part != self.action_id:
            raise ValueError(
                f"capability_id 动作段 {action_part!r} 与 action_id {self.action_id!r} 不一致")
        if version_part != self.version:
            raise ValueError(
                f"capability_id 版本段 {version_part!r} 与 version {self.version!r} 不一致")
        if self.idempotency_key_policy not in IDEMPOTENCY_POLICIES:
            raise ValueError(
                f"idempotency_key_policy 受控集外: {self.idempotency_key_policy!r}"
                f"（允许: {'/'.join(sorted(IDEMPOTENCY_POLICIES))}）")


def _load_adapter_module(name: str):
    """按模块名装载 tools 适配器（sys.path 兜底加仓库根，pathlib 推断不依赖 cwd）。"""
    import importlib

    root = default_repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return importlib.import_module(f"tools.{name}")


# ---------------------------------------------------------------------------
# CapabilityRegistry
# ---------------------------------------------------------------------------
class CapabilityRegistry:
    """能力注册表：存在性权威（注册 ≠ 授权 ≠ 模型可见）。"""

    def __init__(self, descriptors: list[CapabilityDescriptor] | None = None) -> None:
        self._by_capability: dict[str, CapabilityDescriptor] = {}
        self._by_action: dict[str, CapabilityDescriptor] = {}
        for descriptor in descriptors or []:
            self.register_capability(descriptor)

    # -------------------------------------------------- 冻结 API（01 §3.3）
    def register_capability(self, capability: CapabilityDescriptor) -> str:
        """注册一个能力（重复注册同 capability_id → 覆盖更新，返回 CapabilityId）。"""
        capability.validate()
        self._by_capability[capability.capability_id] = capability
        self._by_action[capability.action_id] = capability
        return capability.capability_id

    # -------------------------------------------------- 查询
    def get(self, capability: str) -> CapabilityDescriptor | None:
        return self._by_capability.get(str(capability))

    def by_action(self, action_id: str) -> CapabilityDescriptor | None:
        return self._by_action.get(str(action_id))

    def action_ids(self) -> list:
        return sorted(self._by_action.keys())

    def capability_ids(self) -> list:
        return sorted(self._by_capability.keys())

    def descriptors(self) -> list:
        return [self._by_action[a] for a in self.action_ids()]

    def __len__(self) -> int:
        return len(self._by_action)


def _default_adapters(repo_root: Path | str | None) -> dict:
    root = Path(repo_root) if repo_root else default_repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from tools import ADAPTERS  # 延迟导入：tools 位于仓库根（非 src 包）

    return ADAPTERS


def load_default_registry(repo_root: Path | str | None = None) -> CapabilityRegistry:
    """从 ontology/actions.yaml（风险/Policy 权威）+ tools/ 适配器（schema/幂等策略）
    装配 16 个能力的缺省注册表。

    装配即断言：适配器动作集与动作表动作集 diff 必须为空（SPEC-M3-03）。
    """
    actions = load_actions_table(repo_root)
    adapters = _default_adapters(repo_root)
    diff = sorted((set(actions) - set(adapters)) | (set(adapters) - set(actions)))
    if diff:
        raise ValueError(
            f"注册表装配失败：tools/ 适配器与 ontology/actions.yaml 动作集 diff 非空: {diff}")
    descriptors = []
    for action_id, action in actions.items():
        adapter = adapters[action_id]
        descriptors.append(CapabilityDescriptor(
            capability_id=f"{action_id}@{adapter.VERSION}",
            action_id=action_id,
            version=adapter.VERSION,
            name_cn=str(action.get("name_cn", "")),
            risk_level=RiskLevel(str(action["risk_level"])),
            reversible=bool(action.get("reversible", False)),
            compensation=action.get("compensation"),
            default_policy=PolicyDecision(str(action["default_policy"])),
            policy_locked=bool(action.get("policy_locked", False)),
            params_schema=dict(getattr(adapter, "PARAMS_SCHEMA", {}) or {}),
            idempotency_key_policy=str(getattr(adapter, "IDEMPOTENCY_KEY_POLICY",
                                               "CALLER_PROVIDED")),
            write_class=bool(getattr(adapter, "WRITE_CLASS", False)),
            disclosed_roles=list(getattr(adapter, "DISCLOSED_ROLES", []) or []),
            adapter=adapter,
        ))
    return CapabilityRegistry(descriptors)


# ---------------------------------------------------------------------------
# CI 断言：注册表 vs 本体动作表 / 不可改清单双重表达
# ---------------------------------------------------------------------------
def registry_vs_actions_table_diff(registry: CapabilityRegistry,
                                   repo_root: Path | str | None = None) -> list:
    """注册表与 ontology/actions.yaml 的 diff（空列表 = 完全对齐）。

    比对两层：
    1. 动作 ID 集合（缺注册/多注册）；
    2. 逐动作风险声明与缺省 Policy（risk_level/reversible/default_policy/policy_locked）。
    """
    actions = load_actions_table(repo_root)
    diffs: list = []
    registered = set(registry.action_ids())
    for missing in sorted(set(actions) - registered):
        diffs.append(f"未注册: {missing}")
    for extra in sorted(registered - set(actions)):
        diffs.append(f"多余注册: {extra}")
    for action_id in sorted(set(actions) & registered):
        descriptor = registry.by_action(action_id)
        action = actions[action_id]
        checks = (
            ("risk_level", descriptor.risk_level.value, str(action.get("risk_level"))),
            ("reversible", descriptor.reversible, bool(action.get("reversible", False))),
            ("default_policy", descriptor.default_policy.value, str(action.get("default_policy"))),
            ("policy_locked", descriptor.policy_locked, bool(action.get("policy_locked", False))),
        )
        for field_name, got, want in checks:
            if got != want:
                diffs.append(f"{action_id}.{field_name}: 注册表={got!r} != 动作表={want!r}")
    return diffs


def assert_immutable_consistency(repo_root: Path | str | None = None) -> dict:
    """不可改清单双重表达一致性断言（硬编码 vs ontology/actions.yaml policy_locked）。

    返回比对结果 dict（一致=空 diffs）；不一致时 diffs 列出两方向差异。
    """
    actions = load_actions_table(repo_root)
    yaml_locked_deny = {aid for aid, a in actions.items()
                        if a.get("default_policy") == "DENY" and a.get("policy_locked")}
    yaml_locked_ask = {aid for aid, a in actions.items()
                       if a.get("default_policy") == "ASK" and a.get("policy_locked")}
    diffs = []
    for direction, hardcoded, from_yaml in (
        ("DENY: 硬编码-动作表", set(IMMUTABLE_DENY_ACTIONS), yaml_locked_deny),
        ("DENY: 动作表-硬编码", yaml_locked_deny, set(IMMUTABLE_DENY_ACTIONS)),
        ("ASK: 硬编码-动作表", set(PERMANENT_ASK_ACTIONS), yaml_locked_ask),
        ("ASK: 动作表-硬编码", yaml_locked_ask, set(PERMANENT_ASK_ACTIONS)),
    ):
        for item in sorted(hardcoded - from_yaml):
            diffs.append(f"{direction}: {item}")
    return {"immutable_deny": sorted(IMMUTABLE_DENY_ACTIONS),
            "permanent_ask": sorted(PERMANENT_ASK_ACTIONS),
            "yaml_locked_deny": sorted(yaml_locked_deny),
            "yaml_locked_ask": sorted(yaml_locked_ask),
            "diffs": diffs}
