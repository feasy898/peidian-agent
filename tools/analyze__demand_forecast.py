# -*- coding: utf-8 -*-
"""tools.analyze__demand_forecast · 需量预测适配器（analyze.demand_forecast@v1）。"""
from __future__ import annotations

from ._base import real_mock_execute, sim_execute

ACTION_ID = "analyze.demand_forecast"
VERSION = "v1"
PARAMS_SCHEMA = {
    "type": "object",
    "required": ["month"],
    "properties": {
        "month": {"type": "string", "description": "目标月份（YYYY-MM）"},
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
    month = str(arguments.get("month", ""))
    peak = env.demand_records.get(month)
    window = dict(env.demand_window or {})
    return {"month": month, "history_peak_kw": peak,
            "current_window": window,
            "contract_capacity_kw": env.contract_capacity_kw}


def verify(arguments, issued, observed):
    return observed is not None and observed.get("month") == str(arguments.get("month", ""))
