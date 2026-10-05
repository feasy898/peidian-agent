# -*- coding: utf-8 -*-
"""tools.write__report · 生成报告 Artifact 适配器（write.report@v1）。

报告内容四段（ADDENDUM §B report.daily@v1）：devices/measurements/conclusion/
regulation_refs——参数 schema 强制四段键，schema 校验归 M3 validator。
"""
from __future__ import annotations

from ._base import real_mock_execute, sim_execute

ACTION_ID = "write.report"
VERSION = "v1"
PARAMS_SCHEMA = {
    "type": "object",
    "required": ["title", "date", "devices", "conclusion", "regulation_refs"],
    "properties": {
        "title": {"type": "string", "description": "报告标题"},
        "date": {"type": "string", "description": "报告日（YYYY-MM-DD）"},
        "devices": {"type": "array", "items": {"type": "string"},
                    "description": "设备清单"},
        "measurements": {"type": "array", "description": "量测段（含时序趋势）"},
        "conclusion": {"type": "string", "description": "结论"},
        "regulation_refs": {"type": "array", "items": {"type": "string"},
                            "description": "规程引用（规则 ID 列表）"},
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
