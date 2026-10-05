# -*- coding: utf-8 -*-
"""tools · 动作适配器注册清单（M3 §6 交付物：16 个动作适配器）。

一个动作一个适配器模块（SPEC-M3-03：注册粒度=00§1.3 动作表，禁止合并）；
模块名 = 动作 ID 的 "." 替换为 "__"（如 ``create__switch_order``）。
``ADAPTERS`` 为 action_id → 适配器模块 的机械映射，由 M3 registry 装配
CapabilityDescriptor（风险/缺省 Policy 来自 ontology/actions.yaml 数据）。
"""
from __future__ import annotations

import importlib
from types import ModuleType

#: 16 个动作适配器模块名（与 ontology/actions.yaml 动作 ID 一一对应）
ADAPTER_MODULE_NAMES = (
    "query__measurement",
    "query__asset",
    "query__regulation",
    "analyze__load_forecast",
    "analyze__power_quality",
    "analyze__transformer_economy",
    "analyze__demand_forecast",
    "write__report",
    "create__work_order",
    "create__switch_order",
    "create__inspection_record",
    "execute__remote_control",
    "execute__capacitor_switch",
    "modify__protection_setting",
    "modify__asset_history",
    "bypass__approval",
)


def _load() -> dict:
    adapters: dict[str, ModuleType] = {}
    for name in ADAPTER_MODULE_NAMES:
        module = importlib.import_module(f".{name}", __package__)
        adapters[module.ACTION_ID] = module
    return adapters


#: action_id → 适配器模块（ACTION_ID/VERSION/PARAMS_SCHEMA/IDEMPOTENCY_KEY_POLICY/
#: WRITE_CLASS/DISCLOSED_ROLES/execute_sim/execute_real/readback/verify）
ADAPTERS: dict = _load()

__all__ = ["ADAPTERS", "ADAPTER_MODULE_NAMES"]
