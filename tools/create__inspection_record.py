# -*- coding: utf-8 -*-
"""tools.create__inspection_record · 登记巡检记录适配器（create.inspection_record@v1）。"""
from __future__ import annotations

from ._base import real_mock_execute, sim_execute

ACTION_ID = "create.inspection_record"
VERSION = "v1"
PARAMS_SCHEMA = {
    "type": "object",
    "required": ["route", "items", "inspector"],
    "properties": {
        "route": {"type": "string", "description": "巡检路线"},
        "items": {"type": "array",
                  "items": {"type": "object",
                            "properties": {"device": {"type": "string"},
                                           "part": {"type": "string"},
                                           "method": {"type": "string"},
                                           "result": {"type": "string"}}},
                  "description": "巡检条目（设备/部位/方法/结果，00 §1.1.D）"},
        "inspector": {"type": "string", "description": "巡检人"},
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
    marker = env.artifacts.get(action_id or "")
    if marker is None:
        return None
    return {"artifact_marker": marker}


def verify(arguments, issued, observed):
    return observed is not None and observed.get("artifact_marker") is not None
