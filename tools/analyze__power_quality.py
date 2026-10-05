# -*- coding: utf-8 -*-
"""tools.analyze__power_quality · 电能质量分析适配器（analyze.power_quality@v1）。"""
from __future__ import annotations

from ._base import real_mock_execute, sim_execute

ACTION_ID = "analyze.power_quality"
VERSION = "v1"
PARAMS_SCHEMA = {
    "type": "object",
    "required": ["device"],
    "properties": {
        "device": {"type": "string", "description": "设备 ID（母线/电容/APF）"},
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
    cell = env.read_measurement(device.id, "thd_u")
    return {"device": device.id, "thd_u": (cell or {}).get("value"),
            "business_at": env.iso_at(env.clock.sim_elapsed_s)}


def verify(arguments, issued, observed):
    return observed is not None and observed.get("device") == str(arguments.get("device", ""))
