# -*- coding: utf-8 -*-
"""tools.query__asset · 查台账适配器（query.asset@v1）。"""
from __future__ import annotations

from ._base import real_mock_execute, sim_execute

ACTION_ID = "query.asset"
VERSION = "v1"
PARAMS_SCHEMA = {
    "type": "object",
    "required": ["device"],
    "properties": {
        "device": {"type": "string", "description": "设备 ID"},
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
    device = env.devices.get(str(arguments.get("device", "")))
    if device is None:
        return None
    return {"device": device.id, "type": device.type,
            "attributes": device.attributes, "state": device.state}


def verify(arguments, issued, observed):
    return observed is not None and observed.get("device") == str(arguments.get("device", ""))
