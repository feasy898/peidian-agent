# -*- coding: utf-8 -*-
"""arena.llm_agent · 真实 LLM 推理式诊断代理（目标4：Agent 智能化）。

职责：接收异常 + 遥测 + 故障库知识 → 发送 LLM → 获取结构化诊断/处置方案。
与 mock agent 的区别：诊断结论由 LLM 推理生成（非预编程规则）。

API 端点：OpenAI 兼容 chat/completions——**经 arena.model_gateway 统一收编**
（module-map #19；env 优先序 LLM_API_KEY/BIGMODEL_API_KEY/OPENAI_API_KEY，
base 同理，PD_MODEL_API_KEY 作 legacy 尾位兼容）。
认证：fail-closed，无 key 回退 mock（收编前后行为一致）。

用法::

    from arena.llm_agent import LLMDiagnosisAgent
    agent = LLMDiagnosisAgent()  # 自动检测 key；无 key 时 enabled=False
    result = agent.diagnose(anomaly, telemetry, fault_library_entry)
    # result = {"diagnosis": "...", "action": "...", "reasoning": "...", "confidence": 0.9}
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.model_gateway import KEY_ENV_VARS, GatewayError, ModelGateway, find_api_key  # noqa: E402

logger = logging.getLogger(__name__)

__all__ = ["LLMDiagnosisAgent", "LLM_AVAILABLE"]

# 历史 env 名别名（兼容用途）；权威优先序见 arena.model_gateway.KEY_ENV_VARS
_API_KEY_VARS = KEY_ENV_VARS
_DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
_DEFAULT_MODEL = "glm-4-flash"


def _find_api_key() -> str | None:
    """兼容别名：env 探测已收编 model_gateway.find_api_key（优先序以网关为准）。"""
    return find_api_key()


LLM_AVAILABLE = _find_api_key() is not None


class LLMDiagnosisAgent:
    """LLM 推理式诊断代理：异常 → 遥测+知识 → LLM → 诊断/处置/推理链。"""

    def __init__(self, *, base_url: str | None = None, model: str | None = None,
                 api_key: str | None = None, timeout_s: float = 30.0) -> None:
        # 凭证/base/model 解析收编 model_gateway（显式参数 > env > 历史缺省，行为不变）
        self._gateway = ModelGateway(api_key=api_key, base_url=base_url, model=model,
                                     default_base=_DEFAULT_BASE_URL,
                                     default_model=_DEFAULT_MODEL,
                                     timeout_s=timeout_s)
        self.api_key = self._gateway.api_key
        self.base_url = self._gateway.base_url
        self.model = self._gateway.model
        self.timeout_s = timeout_s
        self.enabled = self._gateway.enabled
        self.call_count = 0
        self.total_tokens = 0
        if not self.enabled:
            logger.info("LLM agent 未启用（无 API key，环境变量 %s 任一即可）", "/".join(_API_KEY_VARS))

    # ================================================================ 诊断
    def diagnose(self, anomaly: dict, telemetry: dict,
                 fault_entry: dict | None = None,
                 context: dict | None = None) -> dict:
        """对单个异常执行 LLM 推理诊断。返回结构化结果。"""
        if not self.enabled:
            return self._mock_diagnosis(anomaly, telemetry, fault_entry)

        prompt = self._build_prompt(anomaly, telemetry, fault_entry, context)
        response = self._call_llm(prompt)
        if response is None:
            return self._mock_diagnosis(anomaly, telemetry, fault_entry)

        return self._parse_response(response, anomaly)

    def batch_diagnose(self, anomalies: list[dict], telemetry: dict,
                       fault_entries: dict[str, dict] | None = None) -> list[dict]:
        """批量诊断多个异常。"""
        fault_entries = fault_entries or {}
        return [
            self.diagnose(a, telemetry, fault_entries.get(a.get("hint", "")))
            for a in anomalies
        ]

    # ================================================================ Prompt
    def _build_prompt(self, anomaly: dict, telemetry: dict,
                      fault_entry: dict | None, context: dict | None) -> str:
        parts = [
            "你是园区配电运维专家。根据以下异常信息和遥测数据，给出诊断和处置方案。",
            "",
            "## 异常信息",
            f"- 类型: {anomaly.get('hint', '未知')}",
            f"- 目标元件: {anomaly.get('target', '未知')}",
            f"- 严重度: {anomaly.get('severity', 'P2')}",
            f"- 证据: {json.dumps(anomaly.get('evidence', {}), ensure_ascii=False)}",
            "",
            "## 当前遥测（相关元件）",
        ]
        target = anomaly.get("target", "")
        for eid, sig in telemetry.items():
            if eid == target or (target and target in eid):
                parts.append(f"- {eid}: {json.dumps(sig, ensure_ascii=False)}")

        if fault_entry:
            parts.extend([
                "",
                "## 故障库知识",
                f"- 机理: {fault_entry.get('mechanism', '')}",
                f"- 检测判据: {json.dumps(fault_entry.get('detection', {}), ensure_ascii=False)}",
                f"- 处置锚点: {json.dumps(fault_entry.get('agent_expectations', {}), ensure_ascii=False)}",
            ])

        if context:
            parts.extend(["", "## 上下文", json.dumps(context, ensure_ascii=False)])

        parts.extend([
            "",
            "请按以下 JSON 格式回答（不要其他内容）：",
            '```json',
            '{',
            '  "diagnosis": "一句话诊断结论",',
            '  "action": "推荐处置动作（ack/open/close/escalate）",',
            '  "action_target": "操作目标元件ID",',
            '  "reasoning": "推理过程（3-5句话，引用遥测数据和故障机理）",',
            '  "confidence": 0.0,',
            '  "safety_note": "安全提示（如有）"',
            '}',
            '```',
        ])
        return "\n".join(parts)

    # ================================================================ LLM 调用
    def _call_llm(self, prompt: str) -> str | None:
        """经 model_gateway 调用 OpenAI 兼容 API。失败返回 None（fail-closed，不 crash）。"""
        import time
        try:
            start = time.time()
            content = self._gateway.chat(
                "你是园区配电运维专家，精通10kV/0.4kV配电系统运维。", prompt,
                temperature=0.1, max_tokens=500, timeout_s=self.timeout_s)
            elapsed = time.time() - start
            self.call_count = self._gateway.call_count
            self.total_tokens = self._gateway.total_tokens
            logger.info("LLM call #%d: %.1fs, %d tokens", self.call_count, elapsed,
                        self._gateway.total_tokens)
            return content
        except GatewayError as exc:
            logger.warning("LLM call failed: %s", exc)
            return None

    def _parse_response(self, response: str, anomaly: dict) -> dict:
        """解析 LLM 响应为结构化诊断。"""
        # 尝试提取 JSON 块
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0].strip()
        else:
            json_str = response.strip()

        try:
            parsed = json.loads(json_str)
            parsed.setdefault("diagnosis", "LLM 诊断（解析成功）")
            parsed.setdefault("action", "ack")
            parsed.setdefault("action_target", anomaly.get("target", ""))
            parsed.setdefault("reasoning", "")
            parsed.setdefault("confidence", 0.5)
            parsed["source"] = "llm"
            parsed["model"] = self.model
            return parsed
        except json.JSONDecodeError:
            # JSON 解析失败，把原始文本作为 reasoning
            return {
                "diagnosis": response.strip()[:200],
                "action": "ack",
                "action_target": anomaly.get("target", ""),
                "reasoning": response.strip(),
                "confidence": 0.3,
                "source": "llm_raw",
                "model": self.model,
            }

    # ================================================================ Mock 回退
    def _mock_diagnosis(self, anomaly: dict, telemetry: dict,
                        fault_entry: dict | None) -> dict:
        """无 API key 时的规则化诊断（与 fault/agent.py 的 mock 行为对齐）。"""
        hint = anomaly.get("hint", "")
        target = anomaly.get("target", "")
        playbook = {
            "PARTIAL_DISCHARGE": "确认局放趋势→安排带电检测复查→报检修计划",
            "TEMPERATURE_RISE": "红外复测定位→负荷转移观察→报检修",
            "HARMONIC": "溯源整流负荷→评估滤波→报整改",
            "THREE_PHASE_UNBALANCE": "核算负荷分配→挪负荷/换相→报整改",
            "TX_OVERLOAD": "隔离→倒闸转供→恢复",
            "SHORT_CIRCUIT": "隔离故障区→倒闸转供→恢复",
            "TRANSFORMER_FAULT": "隔离变压器→转供→报修",
        }
        action_plan = playbook.get(hint, "确认告警并派工消缺")
        return {
            "diagnosis": f"{hint}@{target}: {action_plan}",
            "action": "ack" if "隔离" not in action_plan else "open",
            "action_target": target,
            "reasoning": f"基于故障库 {hint} 类型的标准处置剧本（mock 模式，无 LLM 推理）",
            "confidence": 0.7,
            "source": "mock",
            "model": "mock-1",
        }

    # ================================================================ 统计
    def stats(self) -> dict:
        return {
            "enabled": self.enabled,
            "model": self.model,
            "calls": self.call_count,
            "total_tokens": self.total_tokens,
        }
