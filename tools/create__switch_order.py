# -*- coding: utf-8 -*-
"""tools.create__switch_order · 创建操作票适配器（create.switch_order@v1）。

SPEC-M3-03：创建操作票 ≠ 执行遥控——与 execute.remote_control 严格独立注册，
禁止合并为同一 capability（风险级/缺省 Policy 均不同）。
SAFE-ISSUE-HUMAN（00§1.4 / REG-SAFE）：签发动作不属于任何 agent 动作集——
本适配器只能登记 DRAFT 草稿票；status 枚举不含 ISSUED，DRAFT→ISSUED 的签发
只能由实例已登记且角色=签发人 的人员在 agent 动作集之外完成（M5 判据层
SAFE_ISSUE_HUMAN 双重兜底）。
"""
from __future__ import annotations

from ._base import real_mock_execute, sim_execute

ACTION_ID = "create.switch_order"
VERSION = "v1"
PARAMS_SCHEMA = {
    "type": "object",
    "required": ["code", "steps", "issuer"],
    "properties": {
        "code": {"type": "string", "description": "操作票编号"},
        "steps": {"type": "array", "items": {"type": "string"},
                  "description": "操作序列（SAFE-ORDER-SEQ 执行顺序依据）"},
        "devices": {"type": "array", "items": {"type": "string"},
                    "description": "操作对象设备"},
        "issuer": {"type": "string",
                   "description": "拟定签发人（仅草稿登记；签发须由持证签发人完成——"
                                  "SAFE-ISSUE-HUMAN：agent 不得签发、不得代签）"},
        "status": {"type": "string", "enum": ["DRAFT"],
                   "description": "登记状态（仅 DRAFT 草稿票；签发状态 ISSUED 不属于 "
                                  "agent 动作集——SAFE-ISSUE-HUMAN）"},
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
    order = env.switch_orders.get(str(arguments.get("code", "")))
    if order is None:
        return None
    return {"switch_order": {k: order.get(k) for k in ("code", "status", "steps", "issuer")}}


def verify(arguments, issued, observed):
    if observed is None:
        return False
    order = observed.get("switch_order") or {}
    return order.get("code") == str(arguments.get("code", "")) and order.get("status") is not None
