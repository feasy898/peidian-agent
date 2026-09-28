# -*- coding: utf-8 -*-
"""m3_action.router · REAL/SIMULATION 执行路由（SPEC-M3-10）。

- EVAL/黄金集运行期间（``evaluation=True``）强制 SIMULATION：请求 REAL → 拒绝
  （01 §8"仿真即默认"；REAL 仅接线负向断言使用）；
- REAL 需环境变量（``PD_REAL_MODE``）+ 双人开关（两个不同审批人 id）同时满足；
- 本期 REAL 仅有 mock 适配器（tools._base.real_mock_execute）——无真实设备协议。
"""
from __future__ import annotations

import os
from typing import Iterable

__all__ = ["Router", "RouterModeError", "REAL_ENV_VAR", "MODE_SIMULATION", "MODE_REAL"]

MODE_SIMULATION = "SIMULATION"
MODE_REAL = "REAL"
MODES = (MODE_SIMULATION, MODE_REAL)

#: REAL 模式环境变量开关（SPEC-M3-10：需环境变量+双人开关）
REAL_ENV_VAR = "PD_REAL_MODE"
#: EVAL/黄金集上下文环境标记（run_evals/黄金 runner 置位时 router 强制 SIMULATION）
EVALUATION_ENV_VAR = "PD_EVALUATION"

_REAL_FORBIDDEN_IN_EVAL = "REAL_FORBIDDEN_IN_EVAL"
_REAL_NOT_CONFIGURED = "REAL_NOT_CONFIGURED"
_REAL_DUAL_SWITCH_REQUIRED = "REAL_DUAL_SWITCH_REQUIRED"
_REAL_ADAPTER_MISSING = "REAL_ADAPTER_MISSING"


class RouterModeError(ValueError):
    """路由拒绝（code 见 SPEC-M3-10 各分支）。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def _env_flag(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in ("1", "true", "yes", "on")


class Router:
    """执行路由器（无状态判定 + 环境开关读取）。"""

    def __init__(self, *, evaluation: bool | None = None,
                 dual_approvers: Iterable[str] | None = None,
                 real_env_var: str = REAL_ENV_VAR) -> None:
        self.evaluation = _env_flag(EVALUATION_ENV_VAR) if evaluation is None \
            else bool(evaluation)
        self.real_env_var = real_env_var
        approvers = [a for a in (dual_approvers or []) if str(a).strip()]
        self.dual_approvers = approvers if len(set(approvers)) >= 2 else None

    def resolve(self, requested_mode: str, descriptor=None) -> str:
        """解析执行模式；REAL 被拒时抛 RouterModeError（code 区分拒绝原因）。"""
        mode = str(requested_mode or MODE_SIMULATION).upper()
        if mode not in MODES:
            raise RouterModeError(
                "UNKNOWN_MODE", f"执行模式必须是 {'/'.join(MODES)}，实际为 {requested_mode!r}")
        if mode == MODE_SIMULATION:
            return MODE_SIMULATION
        # REAL 分支：三重门禁
        if self.evaluation:
            raise RouterModeError(
                _REAL_FORBIDDEN_IN_EVAL,
                "EVAL/黄金集运行期间强制 SIMULATION（01 §8 仿真即默认；REAL 仅接线负向断言用）")
        if not _env_flag(self.real_env_var):
            raise RouterModeError(
                _REAL_NOT_CONFIGURED,
                f"REAL 模式需环境变量 {self.real_env_var}=1（当前未设置）")
        if self.dual_approvers is None:
            raise RouterModeError(
                _REAL_DUAL_SWITCH_REQUIRED,
                "REAL 模式需双人开关（两个不同审批人同时放行），当前未满足")
        if descriptor is not None and not hasattr(descriptor.adapter, "execute_real") \
                and descriptor.adapter is not None:
            raise RouterModeError(
                _REAL_ADAPTER_MISSING,
                f"能力 {descriptor.capability_id} 无 REAL 适配器（本期 REAL 仅 mock 接线）")
        return MODE_REAL
