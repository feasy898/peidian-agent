# -*- coding: utf-8 -*-
"""tools.execute__remote_control · 遥控分/合闸适配器（execute.remote_control@v1）。

缺省 Policy=ASK（永久，不可被任何角色改为 ALLOW——审批只放行单次，SPEC-M3-05）；
两票制（SAFE-TWO-TICKET）由 M5 仿真路由强制：无已签发操作票一律 FAILED。
"""
from __future__ import annotations

from ._base import real_mock_execute, sim_execute

ACTION_ID = "execute.remote_control"
VERSION = "v1"
PARAMS_SCHEMA = {
    "type": "object",
    "required": ["device", "operation", "switch_order"],
    "properties": {
        "device": {"type": "string", "description": "被控设备 ID"},
        "operation": {"type": "string", "enum": ["OPEN", "CLOSE"],
                      "description": "分闸/合闸"},
        "switch_order": {"type": "string",
                         "description": "操作票编号（SAFE-TWO-TICKET：必须已签发）"},
        "step": {"type": "int", "description": "操作票步骤号（SAFE-ORDER-SEQ）", "min": 1},
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
    """环境回读：设备断路器状态 + 运行态（独立于执行器自报，SPEC-M3-09）。"""
    device = env.devices.get(str(arguments.get("device", "")))
    if device is None:
        return None
    return {"device": device.id, "breaker_state": device.breaker_state,
            "device_state": device.state,
            "ts": env.iso_at(env.clock.sim_elapsed_s)}


def verify(arguments, issued, observed):
    """核对：环境回读的断路器状态必须兑现 issued 声明的操作目标。"""
    if observed is None:
        return False
    operation = str(arguments.get("operation", "OPEN")).upper()
    target = "OPEN" if operation == "OPEN" else "CLOSED"
    return observed.get("breaker_state") == target
