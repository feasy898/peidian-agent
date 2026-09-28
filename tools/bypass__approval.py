# -*- coding: utf-8 -*-
"""tools.bypass__approval · 绕过审批适配器（bypass.approval@v1）。

缺省 Policy=DENY（永久，红线 4：bypass.approval 永不生效）——不提供执行路径。
"""
from __future__ import annotations

ACTION_ID = "bypass.approval"
VERSION = "v1"
PARAMS_SCHEMA = {
    "type": "object",
    "required": ["capability"],
    "properties": {
        "capability": {"type": "string", "description": "企图绕免审批的能力"},
        "reason": {"type": "string", "description": "理由（永不执行，仅记录意图）"},
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
