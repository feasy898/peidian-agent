# -*- coding: utf-8 -*-
"""tools.query__measurement · 读量测适配器（query.measurement@v1）。"""
from __future__ import annotations

from ._base import real_mock_execute, sim_execute

ACTION_ID = "query.measurement"
VERSION = "v1"
PARAMS_SCHEMA = {
    "type": "object",
    "required": [],
    "properties": {
        "device": {"type": "string", "description": "设备 ID（缺省=全园区快照）"},
        "quantity": {"type": "string", "description": "量测量（如 P/Q/U/I/cosφ）"},
    },
}
IDEMPOTENCY_KEY_POLICY = "CALLER_PROVIDED"
WRITE_CLASS = False
DISCLOSED_ROLES = []  # 空 = 对全部角色披露


def execute_sim(request, env):
    return sim_execute(request, env)


def execute_real(request, ctx=None):
    return real_mock_execute(request, ctx)


def readback(env, arguments, action_id=None):
    """环境回读：量测快照（带时标/质量标志）——直接读环境，不信执行器自报。"""
    device = arguments.get("device")
    snapshot = env.measurement_snapshot(device)
    return {"measurements": snapshot, "count": len(snapshot),
            "business_at": env.iso_at(env.clock.sim_elapsed_s)}


def verify(arguments, issued, observed):
    return observed is not None and isinstance(observed.get("measurements"), list)
