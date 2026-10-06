# -*- coding: utf-8 -*-
"""arena.model_gateway · 统一 LLM 薄网关（module-map #19：mock/openai_like 收编入口）。

职责（薄，刻意不厚）：
  - env 凭证解析**唯一权威**：key 优先序 LLM_API_KEY > BIGMODEL_API_KEY >
    OPENAI_API_KEY > PD_MODEL_API_KEY(legacy)；base_url 同理
    LLM_BASE_URL > BIGMODEL_BASE_URL > OPENAI_BASE_URL（model 走 LLM_MODEL）。
  - OpenAI 兼容 /chat/completions 一发式调用 + 用量统计 + fail-closed 异常面
    （GatewayError，绝不吃异常——由调用方决定回退语义）。
  - 零信任纪律：key 只经环境变量/显式参数进入，不进 argv/日志/repr；
    base_url 仅允许 http(s)（与 fault.llm_bridge.HigressClient 同款 SSRF 加固）。

收编范围（本轮"两调用点"，module-map #3/#18）：
  - arena.llm_agent.LLMDiagnosisAgent（原 BIGMODEL_API_KEY/PD_MODEL_API_KEY/OPENAI_API_KEY
    三序 + LLM_BASE_URL → 改经本网关；无 key 回退 mock 的行为不变）
  - dsl.prompts.run_gen（原 LLM_API_KEY env / --base-url/--model 缺省值不变 → 改经本网关）
  fault.llm_bridge.HigressClient（Higress 内网通道）本轮不动（module-map #15 另行收编）。

用法::

    gw = ModelGateway()                    # 自动探 env；无 key 时 enabled=False
    gw = ModelGateway(default_base="https://open.bigmodel.cn/api/paas/v4",
                      default_model="glm-4-flash")
    text = gw.chat("系统提示", "用户输入", temperature=0.1)
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

__all__ = ["ModelGateway", "GatewayError", "KEY_ENV_VARS", "BASE_ENV_VARS",
           "find_api_key", "find_base_url"]

# env 优先序（本仓统一口径）：LLM_* 为通用名，BIGMODEL_* 为 zhipu 厂商名，
# OPENAI_* 为 OpenAI 兼容惯例；PD_MODEL_API_KEY 为 m1_core 旧名（legacy 尾位兼容）。
KEY_ENV_VARS = ("LLM_API_KEY", "BIGMODEL_API_KEY", "OPENAI_API_KEY", "PD_MODEL_API_KEY")
BASE_ENV_VARS = ("LLM_BASE_URL", "BIGMODEL_BASE_URL", "OPENAI_BASE_URL")
MODEL_ENV_VAR = "LLM_MODEL"

_BASE_RE = re.compile(r"^https?://[A-Za-z0-9.\-_]+(?::\d+)?(?:/[A-Za-z0-9.\-/]*)?$")


class GatewayError(RuntimeError):
    """网关调用失败（无 key / 网络 / HTTP / 响应结构）。fail-closed 语义：如实抛出。"""


def find_api_key(env: dict | None = None) -> str | None:
    """按 KEY_ENV_VARS 优先序找第一个非空 key；找不到返回 None。"""
    src = os.environ if env is None else env
    for var in KEY_ENV_VARS:
        key = str(src.get(var, "") or "").strip()
        if key:
            return key
    return None


def find_base_url(env: dict | None = None) -> str | None:
    """按 BASE_ENV_VARS 优先序找第一个非空 base；找不到返回 None。"""
    src = os.environ if env is None else env
    for var in BASE_ENV_VARS:
        base = str(src.get(var, "") or "").strip()
        if base:
            return base
    return None


class ModelGateway:
    """OpenAI 兼容对话薄网关：env 探测 + 单发 chat + 用量台账。

    api_key/base_url/model 显式参数 > env > 调用方 default_*（caller 自留历史缺省，
    保证收编前后行为零变）。enabled=False（无 key）时 chat() 抛 GatewayError——
    回退策略（mock/规则兜底/退出码）归调用方，网关绝不擅自降级。
    """

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, default_base: str = "",
                 default_model: str = "", timeout_s: float = 120.0,
                 env: dict | None = None) -> None:
        src = os.environ if env is None else env
        self.api_key = str(api_key or "").strip() or find_api_key(src) or ""
        base = str(base_url or "").strip() or find_base_url(src) or default_base
        self.base_url = str(base or "").rstrip("/")
        self.model = str(model or "").strip() \
            or str(src.get(MODEL_ENV_VAR, "") or "").strip() or default_model
        self.timeout_s = float(timeout_s)
        self.call_count = 0
        self.total_tokens = 0
        if self.base_url and not _BASE_RE.match(self.base_url):
            raise GatewayError(f"base_url 非法（仅允许 http(s)://host[:port][/path]）: {self.base_url}")
        self.enabled = bool(self.api_key)

    # ---------------------------------------------------------------- chat
    def chat(self, system: str, user: str, *, temperature: float = 0.0,
             max_tokens: int | None = None, timeout_s: float | None = None) -> str:
        """单发对话，返回 assistant 文本。任何失败抛 GatewayError（不静默）。"""
        if not self.api_key:
            raise GatewayError(
                "无 API key（env 优先序 " + "/".join(KEY_ENV_VARS) + " 任一即可）")
        if not self.base_url:
            raise GatewayError("base_url 未配置（显式参数或 " + "/".join(BASE_ENV_VARS) + "）")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        url = f"{self.base_url}/chat/completions"
        req = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})  # key 只进请求头
        try:
            with urllib.request.urlopen(req, timeout=timeout_s or self.timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise GatewayError(f"HTTP {exc.code} from {self.base_url}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GatewayError(f"网络失败: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise GatewayError(f"响应非 JSON: {exc}") from exc
        try:
            usage = data.get("usage") or {}
            self.total_tokens += int(usage.get("total_tokens", 0) or 0)
            self.call_count += 1
            content = data["choices"][0]["message"].get("content", "")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GatewayError(f"响应结构异常: {exc}") from exc
        if not isinstance(content, str):
            raise GatewayError("响应 content 非字符串")
        return content

    # ---------------------------------------------------------------- 台账
    def stats(self) -> dict:
        return {"enabled": self.enabled, "model": self.model,
                "base_url": self.base_url, "calls": self.call_count,
                "total_tokens": self.total_tokens}

    def __repr__(self) -> str:  # 零打印纪律：key 绝不入 repr/日志
        return (f"ModelGateway(model={self.model!r}, base_url={self.base_url!r}, "
                f"enabled={self.enabled}, calls={self.call_count})")
