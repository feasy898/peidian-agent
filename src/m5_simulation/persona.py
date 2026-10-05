# -*- coding: utf-8 -*-
"""m5_simulation.persona · 用户模拟器（SPEC-M5-04）。

- **脚本模式（先行）**：``behavior_script`` 逐字确定性回放——同脚本同输出，
  不含任何随机性/模型调用（EVAL-M5-04-P：5 轮追问逐字一致）；
- **LLM 生成模式（接口预留）**：``persona_step(..., mode="llm")`` 经
  ``m1_core.model_client`` 统一客户端调用（01 §8：禁止业务模块直连 SDK）。
  当前 model_client 为 M1 占位实现（NotImplementedError）——调用点已就位，
  失败即走**降级路径**：回退脚本模式（有脚本时逐字回放，标记 degraded）；
  无脚本返回 None（调用方等待）。M1 交付后此路径自动生效，无需改本模块。
- LLM 产物用于门禁结论前必须过 persona 保真度抽检（SPEC-M5-04），
  ``fidelity_check`` 提供机械抽检（分布多样性 + 角色一致）供上层调用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from contracts import BehaviorAct, Persona

from .clock import parse_utc
from .env import parse_time_ref

__all__ = ["UserUtterance", "PersonaSession", "persona_step", "fidelity_check"]


@dataclass
class UserUtterance:
    """一次用户输出（persona_step 的返回）。"""

    persona: str          # OPERATOR / DISPATCHER / APPROVER
    act: str              # USER_INPUT / GRANT / DENY / LEAVE
    text: str | None      # 逐字文本（GRANT/DENY/LEAVE 可无）
    at: str               # 计划触发时刻（BUSINESS UTC ISO-8601）
    mode: str = "script"  # script / llm
    degraded: bool = False  # LLM 失败降级产生时为 true

    def to_dict(self) -> dict:
        return {
            "persona": self.persona, "act": self.act, "text": self.text,
            "at": self.at, "mode": self.mode, "degraded": self.degraded,
        }


@dataclass
class PersonaSession:
    """用户模拟器会话（脚本队列 + 可选 LLM 配置）。"""

    persona: Persona | str
    script: list = field(default_factory=list)   # [{at, act, text}]（计划序）
    cursor: int = 0
    llm_provider: str = "mock"                   # M1 model_client provider
    llm_options: dict = field(default_factory=dict)
    _history: list = field(default_factory=list)

    @classmethod
    def from_spec(cls, user_model, clock_start) -> "PersonaSession":
        """ScenarioSpec.user_model → 会话（脚本步骤时间引用解析为绝对时刻）。"""
        steps = []
        for step in user_model.behavior_script:
            # BehaviorAct 是 str 枚举：成员本身 isinstance(x, str) 为真，
            # 统一经 .value 归一为契约字面量（"GRANT" 而非 "BehaviorAct.GRANT"）
            act = step.act
            act_value = act.value if isinstance(act, BehaviorAct) else str(act)
            steps.append({
                "at_abs": parse_time_ref(step.at, clock_start),
                "at": step.at,
                "act": act_value,
                "text": step.text,
            })
        persona = user_model.persona
        persona_value = persona.value if isinstance(persona, Persona) else str(persona)
        return cls(persona=persona_value, script=steps)

    def due(self, business_now) -> UserUtterance | None:
        """弹出一条到期步骤（at ≤ business_now）；无到期返回 None（确定性）。"""
        while self.cursor < len(self.script):
            step = self.script[self.cursor]
            if step["at_abs"] <= business_now:
                self.cursor += 1
                utterance = UserUtterance(
                    persona=str(self.persona.value if isinstance(self.persona, Persona)
                                else self.persona),
                    act=str(step["act"]),
                    text=step["text"],
                    at=_iso(step["at_abs"]),
                    mode="script",
                )
                self._history.append(utterance.to_dict())
                return utterance
            return None
        return None

    @property
    def exhausted(self) -> bool:
        return self.cursor >= len(self.script)


def _iso(moment) -> str:
    from .clock import iso_z

    return iso_z(parse_utc(moment))


def persona_step(persona: PersonaSession, history: list | None = None,
                 *, mode: str = "script", prompt_context: dict | None = None) -> UserUtterance | None:
    """01 §3.5 冻结 API：``persona_step(persona, history) -> UserUtterance``。

    - mode="script"（缺省）：到期脚本步骤逐字回放；未到期/耗尽返回 None；
    - mode="llm"：经 ``m1_core.model_client`` 生成（M1 交付后生效）；
      失败（当前占位抛 NotImplementedError / ModelClientError）走降级路径：
      回退脚本模式并标记 ``degraded=True``；无脚本可回退时返回 None。
    """
    if not isinstance(persona, PersonaSession):
        raise TypeError(f"persona 必须为 PersonaSession，实际 {type(persona).__name__}")
    if history:
        persona._history.extend(
            item if isinstance(item, dict) else dict(item) for item in history[-len(history):]
        )

    if mode == "llm":
        try:
            from m1_core.model_client import ModelClient  # 统一客户端（01 §8）

            client = ModelClient(provider=persona.llm_provider, **persona.llm_options)
            response = client.complete({
                "messages": [
                    {"role": "system",
                     "content": f"你是园区配电运维用户模拟器，角色={persona.persona}。"},
                    {"role": "user", "content": str(prompt_context or "给出下一步用户指令。")},
                ],
                "trace_id": f"persona-{id(persona):x}",
            })
            text = str(response.get("text", "")).strip()
            if text:
                utterance = UserUtterance(
                    persona=str(persona.persona), act="USER_INPUT", text=text,
                    at=_iso(persona.script[0]["at_abs"]) if persona.script else "",
                    mode="llm",
                )
                persona._history.append(utterance.to_dict())
                return utterance
            raise RuntimeError("LLM 返回空文本")
        except Exception as exc:  # noqa: BLE001 - 降级路径：模型不可用不中断仿真
            fallback = persona.due(_next_due_time(persona))
            if fallback is not None:
                fallback.degraded = True
                return fallback
            _llm_degrade_note(persona, exc)
            return None

    # 脚本模式：由调用方（场景引擎）传入当前 BUSINESS 时刻驱动；
    # 直接调用时弹出下一条已到期步骤（history 驱动的简化路径）。
    return persona.due(_next_due_time(persona))


def _next_due_time(persona: PersonaSession):
    """会话内下一条到期时刻（无步骤取确定性远期哨兵，保证 due 判定确定）。

    远期哨兵用 ``datetime.max``（常量），不用墙钟——本模块不得引入任何
    真实时间源（SPEC-M5-02：业务路径零 wall-clock）。
    """
    from datetime import datetime, timezone

    if persona.cursor < len(persona.script):
        return persona.script[persona.cursor]["at_abs"]
    return datetime.max.replace(tzinfo=timezone.utc)


def _llm_degrade_note(persona: PersonaSession, exc: Exception) -> None:
    """降级记录（不中断；M1 交付后此路径自然失效）。"""
    persona._history.append({
        "persona": str(persona.persona), "act": "LLM_DEGRADED",
        "text": None, "at": None, "mode": "llm", "degraded": True,
        "error": f"{type(exc).__name__}: {exc}",
    })


def fidelity_check(utterances: list, *, expected_persona: str | None = None,
                   min_distinct_texts: int = 1) -> dict:
    """persona 保真度机械抽检（SPEC-M5-04：分布多样性 + 角色一致）。

    LLM 产物用于门禁结论前的最低机械门槛；语义级抽检由人工/规程判据补充。
    """
    problems: list = []
    texts = [u.get("text") for u in utterances if u.get("text")]
    personas = {str(u.get("persona")) for u in utterances}
    if len(set(texts)) < min_distinct_texts:
        problems.append(f"文本多样性不足：{len(set(texts))} < {min_distinct_texts}")
    if expected_persona is not None and personas - {expected_persona}:
        problems.append(f"角色不一致：{sorted(personas - {expected_persona})}")
    return {"passed": not problems, "problems": problems,
            "samples": len(utterances), "distinct_texts": len(set(texts)),
            "personas": sorted(personas)}
