# -*- coding: utf-8 -*-
"""tools.create__work_order · 创建工单适配器（create.work_order@v1）。"""
from __future__ import annotations

from ._base import real_mock_execute, sim_execute

ACTION_ID = "create.work_order"
VERSION = "v1"
PARAMS_SCHEMA = {
    "type": "object",
    "required": ["code", "type"],
    "properties": {
        "code": {"type": "string", "description": "工单编号"},
        "type": {"type": "string", "enum": ["消缺", "检修", "巡检"],
                 "description": "工单类型（00 §1.1.D WorkOrder.type）"},
        "priority": {"type": "string", "description": "优先级"},
        "related_alarm": {"type": "string", "description": "关联告警 ID"},
        "assignee": {"type": "string", "description": "处理人"},
        "description": {"type": "string", "description": "工单描述"},
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
