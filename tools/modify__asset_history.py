# -*- coding: utf-8 -*-
"""tools.modify__asset_history · 改台账历史适配器（modify.asset_history@v1）。

缺省 Policy=DENY（永久，系统级不可覆盖，SPEC-M3-05 红线）——不提供执行路径。
"""
from __future__ import annotations

ACTION_ID = "modify.asset_history"
VERSION = "v1"
PARAMS_SCHEMA = {
    "type": "object",
    "required": ["device", "entry"],
    "properties": {
        "device": {"type": "string", "description": "设备 ID"},
        "entry": {"type": "object", "description": "台账条目（永不执行，仅记录意图）"},
    },
}
IDEMPOTENCY_KEY_POLICY = "CALLER_PROVIDED_UNIQUE_ARGS"
WRITE_CLASS = True
DISCLOSED_ROLES = []


def execute_sim(request, env):
    from m5_simulation.scenario import simulate

    result, _env_after = simulate(request, env)
    return result


def execute_real(request, ctx=None):
    from ._base import real_mock_execute

    return real_mock_execute(request, ctx)


def readback(env, arguments, action_id=None):
    return None


def verify(arguments, issued, observed):
    return False
