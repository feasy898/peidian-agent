# -*- coding: utf-8 -*-
"""tools.execute__capacitor_switch · 电容投切适配器（execute.capacitor_switch@v1）。"""
from __future__ import annotations

from ._base import real_mock_execute, sim_execute

ACTION_ID = "execute.capacitor_switch"
VERSION = "v1"
PARAMS_SCHEMA = {
    "type": "object",
    "required": ["device", "state"],
    "properties": {
        "device": {"type": "string", "description": "无功补偿装置 ID"},
        "state": {"type": "string", "enum": ["ON", "OFF"], "description": "投入/切除"},
    },
}
IDEMPOTENCY_KEY_POLICY = "CALLER_PROVIDED_UNIQUE_ARGS"
WRITE_CLASS = True
DISCLOSED_ROLES = []


def execute_sim(request, env):
    return sim_execute(request, env)


def execute_real(request, ctx=None):
    return real_mock_execute(request, ctx)


def readback(env, arguments, action_id=None):
    device = env.devices.get(str(arguments.get("device", "")))
    if device is None:
        return None
    return {"device": device.id, "state": device.attributes.get("state"),
            "ts": env.iso_at(env.clock.sim_elapsed_s)}


def verify(arguments, issued, observed):
    if observed is None:
        return False
    target = str(arguments.get("state", "ON")).upper()
    return observed.get("state") == target
