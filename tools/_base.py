# -*- coding: utf-8 -*-
"""tools._base · 动作适配器公共约定（M3 §6 交付物：16 个动作适配器）。

每个适配器模块（tools/<action_id 双下划线形式>.py）暴露：
- ``ACTION_ID`` / ``VERSION``：能力标识（capability = "<ACTION_ID>@<VERSION>"）；
- ``PARAMS_SCHEMA``：参数 schema（M3 validator 校验依据，数据驱动）；
- ``IDEMPOTENCY_KEY_POLICY``：幂等键策略
  （CALLER_PROVIDED=原样采用调用方 key；CALLER_PROVIDED_UNIQUE_ARGS=同 key
  必须承载相同 (capability, arguments)，否则 KEY_CONFLICT 拒绝）；
- ``WRITE_CLASS``：是否写类动作（SPEC-M3-11 负向矩阵与披露口径用）；
- ``DISCLOSED_ROLES``：对该角色集披露（空列表=对全部角色披露，SPEC-M3-01）；
- ``execute_sim(request, env)``：SIMULATION 路由 → M5 ``simulate``（01 §3.3）；
- ``execute_real(request, ctx)``：REAL 路由——本期仅 mock 签名（无真实设备协议）；
- ``readback(env, arguments, action_id)``：环境回读（observer 的 observed 来源，
  独立于执行器自报，SPEC-M3-09）；
- ``verify(arguments, issued, observed)``：回读是否兑现 issued 声明（核对口径）。

SIMULATION 执行统一委托 ``m5_simulation.scenario.simulate``（冻结 API），
适配器不重复实现物理/规程判定；REAL 只有 mock 签名（SPEC-M3-10）。
"""
from __future__ import annotations

from typing import Any, Mapping

__all__ = ["sim_execute", "real_mock_execute", "REAL_MOCK_RESULT"]

#: REAL 路由唯一返回形态：mock 接线（SPEC-M3-10：REAL 仅接线负向断言用）
REAL_MOCK_RESULT = {
    "status": "FAILED",
    "error": {"code": "REAL_MOCK_ONLY",
              "message": "REAL 路由仅 mock 接线：本期无真实设备协议实现"},
}


def sim_execute(request, env: Any) -> dict:
    """SIMULATION 路由：委托 M5 ``simulate(action, env)``（01 §3.5 冻结接口）。"""
    from m5_simulation.scenario import simulate  # 延迟导入：tools 不强依赖 M5 装载序

    result, _env_after = simulate(request, env)
    return result


def real_mock_execute(request, ctx: Mapping | None = None) -> dict:
    """REAL 路由（仅 mock 签名）：返回接线断言用 mock 结果，不触任何真实设备。"""
    return {
        "action_id": getattr(request, "action_id", ""),
        **REAL_MOCK_RESULT,
        "evidence": {
            "intended": {"capability": getattr(request, "capability", ""),
                         "wiring": "REAL/mock"},
            "issued": None,
            "observed": None,
        },
    }
