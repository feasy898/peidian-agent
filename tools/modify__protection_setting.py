# -*- coding: utf-8 -*-
"""tools.modify__protection_setting · 修改保护定值适配器（modify.protection_setting@v1）。

缺省 Policy=DENY（永久，系统级不可覆盖，SPEC-M3-05 红线）——任何角色/审批均不可
翻转为 ALLOW；本适配器不提供任何执行路径（SIMULATION/REAL 一致拒绝）。
"""
from __future__ import annotations

ACTION_ID = "modify.protection_setting"
VERSION = "v1"
PARAMS_SCHEMA = {
    "type": "object",
    "required": ["device", "setting"],
    "properties": {
        "device": {"type": "string", "description": "设备 ID"},
        "setting": {"type": "object", "description": "定值项（永不执行，仅记录意图）"},
    },
}
IDEMPOTENCY_KEY_POLICY = "CALLER_PROVIDED_UNIQUE_ARGS"
WRITE_CLASS = True
DISCLOSED_ROLES = []


def execute_sim(request, env):
    from m5_simulation.scenario import simulate

    result, _env_after = simulate(request, env)  # M5 路由按永久 DENY 拒绝（数据驱动）
    return result


def execute_real(request, ctx=None):
    from ._base import real_mock_execute

    return real_mock_execute(request, ctx)


def readback(env, arguments, action_id=None):
    return None  # 永不执行 → 无环境回读


def verify(arguments, issued, observed):
    return False  # DENY 动作不存在"成功回读"
