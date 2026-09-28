# -*- coding: utf-8 -*-
"""tools.query__regulation · 检索规程适配器（query.regulation@v1）。"""
from __future__ import annotations

from ._base import real_mock_execute, sim_execute

ACTION_ID = "query.regulation"
VERSION = "v1"
PARAMS_SCHEMA = {
    "type": "object",
    "required": ["rule_id"],
    "properties": {
        "rule_id": {"type": "string", "description": "规则 ID（如 PHYS-TX-LOAD）"},
    },
}
IDEMPOTENCY_KEY_POLICY = "CALLER_PROVIDED"
WRITE_CLASS = False
DISCLOSED_ROLES = []


def execute_sim(request, env):
    return sim_execute(request, env)


def execute_real(request, ctx=None):
    return real_mock_execute(request, ctx)


def readback(env, arguments, action_id=None):
    rule_id = str(arguments.get("rule_id", ""))
    for data in (env.ontology.regulations or {}).values():
        for item in (data or {}).get("rules") or []:
            if item.get("id") == rule_id:
                return {"rule": item}
    return None


def verify(arguments, issued, observed):
    if observed is None:
        return False
    rule = observed.get("rule") or {}
    return rule.get("id") == str(arguments.get("rule_id", ""))
