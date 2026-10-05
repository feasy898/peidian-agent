# -*- coding: utf-8 -*-
"""m1_core.middleware · 链式中间件（specs/M1-agent-core.md SPEC-M1-08 / §2）。

- 链以**注册顺序**执行（同 hook 内按注册序逐个调用）；
- **可插拔**：移除任一/全部中间件不影响 Loop 核心语义（五阶段序、状态机
  迁移、完成判定均不依赖任何中间件——DoD 回归验证）；
- 中间件异常被**收容**进 TurnContext.notes（不中断 Loop；核心语义不受损）；
- 内置三件：日志（logging）/ 安全注入（Safety）/ 委派预留位（Delegation，
  L3 子 agent 扩展点，本期 no-op）。

中间件可见面（TurnContext，只读为主；安全注入可在 MODEL 前改写 model_request）：
task_id / turn / phase / user_input / manifest / model_request / model_response /
actions / observations / notes / data。
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

__all__ = [
    "TurnContext",
    "Middleware",
    "MiddlewareChain",
    "LoggingMiddleware",
    "SafetyInjectionMiddleware",
    "DelegationMiddleware",
    "default_middlewares",
    "DEFAULT_SAFETY_DIRECTIVES",
]

LOGGER = logging.getLogger("m1.middleware")


class TurnContext:
    """单轮上下文（中间件与 Loop 共享的只读为主视图）。"""

    def __init__(self, task_id: str, turn: int, *, user_input: str = "",
                 trace_id: str = "") -> None:
        self.task_id = task_id
        self.turn = int(turn)
        self.user_input = user_input
        self.trace_id = trace_id
        self.phase: str = ""
        self.notes: list[str] = []
        self.data: dict = {}
        # 阶段产物（Loop 写、中间件读；Safety 可在 MODEL 前注入 model_request）
        self.manifest: Any = None
        self.model_request: dict | None = None
        self.model_response: dict | None = None
        self.actions: list = []
        self.observations: list = []

    def note(self, text: str) -> None:
        """追加一条审计注记（中间件收容异常/链路说明的落点）。"""
        self.notes.append(str(text))


class Middleware:
    """中间件基类（钩子全部可选；子类按需覆写）。"""

    name = "middleware"

    def on_turn_start(self, turn: TurnContext) -> None:  # noqa: D401
        """轮开始（Prepare 之前）。"""

    def before_phase(self, phase: str, turn: TurnContext) -> None:  # noqa: D401
        """阶段开始前。"""

    def after_phase(self, phase: str, turn: TurnContext) -> None:  # noqa: D401
        """阶段结束后。"""

    def on_turn_end(self, turn: TurnContext) -> None:  # noqa: D401
        """轮结束（含 Prepare 中断轮）。"""


class MiddlewareChain:
    """注册序执行链（use/remove/clear；异常收容进 turn.notes）。"""

    def __init__(self, middlewares: Iterable[Middleware] | None = None) -> None:
        self._chain: list[Middleware] = [m for m in (middlewares or []) if m is not None]

    # ------------------------------------------------------------- 管理
    def use(self, middleware: Middleware) -> "MiddlewareChain":
        """注册（尾部追加；同名不重复注册）。"""
        if middleware is not None and not any(
            getattr(m, "name", None) == getattr(middleware, "name", None)
            for m in self._chain
        ):
            self._chain.append(middleware)
        return self

    def remove(self, name: str) -> bool:
        """按名移除；返回是否移除成功。"""
        before = len(self._chain)
        self._chain = [m for m in self._chain
                       if getattr(m, "name", None) != str(name)]
        return len(self._chain) < before

    def clear(self) -> None:
        """移除全部中间件（Loop 核心语义不变——SPEC-M1-08 回归口径）。"""
        self._chain = []

    def names(self) -> list[str]:
        return [getattr(m, "name", type(m).__name__) for m in self._chain]

    def __len__(self) -> int:
        return len(self._chain)

    # ------------------------------------------------------------- 分发
    def dispatch(self, hook: str, *args: Any) -> list[str]:
        """按注册顺序调用各中间件的 hook；异常收容（返回收容的异常说明）。"""
        contained: list[str] = []
        for middleware in list(self._chain):
            fn = getattr(middleware, hook, None)
            if fn is None:
                continue
            try:
                fn(*args)
            except Exception as exc:  # noqa: BLE001 - 收容：中间件不得打断 Loop
                name = getattr(middleware, "name", type(middleware).__name__)
                contained.append(f"{name}.{hook}: {type(exc).__name__}: {exc}")
                LOGGER.warning("中间件异常已收容 %s.%s: %s", name, hook, exc)
        return contained


# ---------------------------------------------------------------- 内置件
class LoggingMiddleware(Middleware):
    """日志中间件：轮/阶段事件入标准日志（无状态副作用）。"""

    name = "logging"

    def on_turn_start(self, turn: TurnContext) -> None:
        LOGGER.info("任务 %s 第 %s 轮开始", turn.task_id, turn.turn)

    def after_phase(self, phase: str, turn: TurnContext) -> None:
        LOGGER.info("任务 %s 第 %s 轮 %s 阶段完成", turn.task_id, turn.turn, phase)

    def on_turn_end(self, turn: TurnContext) -> None:
        LOGGER.info("任务 %s 第 %s 轮结束", turn.task_id, turn.turn)


#: 安全注入缺省指令（specs/README.md §5 红线 1/2/3/4/7 的 agent 侧表达）
DEFAULT_SAFETY_DIRECTIVES: tuple[str, ...] = (
    "只允许执行已注册且已披露的能力；未注册动作一律不得发起。",
    "任何角色不得执行 modify.protection_setting；该动作永久 DENY。",
    "execute.remote_control 必须持有已签发操作票（两票制），且永久 ASK 审批。",
    "禁止任何形式的绕过审批（bypass.approval 永久 DENY）。",
    "申请任务完成必须附证据：产物就绪且执行证据三态齐全，不得以自述替代。",
)


class SafetyInjectionMiddleware(Middleware):
    """安全注入中间件：MODEL 前向模型请求注入安全指令（system 层前置）。"""

    name = "safety"

    def __init__(self, directives: Iterable[str] | None = None) -> None:
        self.directives = [str(d) for d in (directives or DEFAULT_SAFETY_DIRECTIVES)]

    def before_phase(self, phase: str, turn: TurnContext) -> None:
        if phase != "MODEL" or turn.model_request is None:
            return
        messages = list(turn.model_request.get("messages") or [])
        injected = {
            "role": "system",
            "content": "【安全指令】\n" + "\n".join(
                f"- {d}" for d in self.directives),
        }
        # system 层前置（首条 system 之后，其余消息之前不越权重排）
        head = messages[:1] if messages and messages[0].get("role") == "system" else []
        rest = messages[1:] if head else messages
        turn.model_request["messages"] = head + [injected] + rest
        turn.note(f"safety: 注入 {len(self.directives)} 条安全指令")


class DelegationMiddleware(Middleware):
    """委派预留位（L3 子 agent 扩展点；本期 no-op，仅留痕）。"""

    name = "delegation"

    def on_turn_start(self, turn: TurnContext) -> None:
        turn.note("delegation: L3 委派位预留（本期不启用）")


def default_middlewares(
    directives: Iterable[str] | None = None,
) -> list[Middleware]:
    """缺省链：日志 → 安全注入 → 委派预留位（注册序）。"""
    return [
        LoggingMiddleware(),
        SafetyInjectionMiddleware(directives),
        DelegationMiddleware(),
    ]
