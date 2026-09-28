# -*- coding: utf-8 -*-
"""tools.analyze__load_forecast · 负荷预测适配器（analyze.load_forecast@v1）。"""
from __future__ import annotations

from ._base import real_mock_execute, sim_execute

ACTION_ID = "analyze.load_forecast"
VERSION = "v1"
PARAMS_SCHEMA = {
    "type": "object",
    "required": ["horizon_h"],
    "properties": {
        "horizon_h": {"type": "int", "description": "预测时长（小时）", "min": 1},
        "device": {"type": "string", "description": "设备 ID（缺省=园区口径）"},
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
    return {"arguments": dict(arguments), "business_at": env.iso_at(env.clock.sim_elapsed_s)}


def verify(arguments, issued, observed):
    return observed is not None
