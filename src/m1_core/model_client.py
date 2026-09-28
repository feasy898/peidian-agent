# -*- coding: utf-8 -*-
"""m1_core.model_client · LLM 统一客户端（specs/01-contracts.md §8 / M1 §2）。

- 模型调用统一走本客户端（provider 适配层）；**禁止业务模块直连 SDK**；
- **provider=mock**：确定性离线实现（脚本化回放，不触网——M1 DoD：mock 模式
  全部 EVAL 可离线复跑）；亦作为 M5 persona LLM 模式的离线接线后端
  （m5_simulation.persona persona_step(mode="llm")）；
- **provider=openai_like**：云端适配（OpenAI 兼容 chat/completions；端点/密钥
  经构造注入或环境变量，密钥永不入代码/日志/事件）；传输层可注入
  （``transport``——离线测试重试/超时分类，不触网）；
- 超时/重试：可重试错误（429/5xx/网络错误）按 ``max_retries`` 有界重试，
  预算耗尽抛 :class:`ModelRetryExhaustedError` / :class:`ModelTimeoutError`。

调用/返回形态（占位契约的落位，向后兼容）::

    request  = {messages: [{role, content}...], tools?: [...],
                temperature?: float, max_tokens?: int, trace_id: str}
    response = {text: str, tool_calls?: [...],
                usage: {prompt_tokens, completion_tokens, total_tokens},
                cost:   {tokens, prompt_tokens, completion_tokens},
                provider, model, latency_ms, trace_id}

确定性纪律：mock 模式 latency_ms 恒为 0、无随机量（重放逐字节一致，
与 M3/M5 SIMULATION 口径对齐）；openai_like 的 latency_ms 为实测审计量
（MONOTONIC 域，用 time.perf_counter——非业务判据）。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping

__all__ = [
    "PROVIDERS",
    "ModelClientError",
    "ModelTimeoutError",
    "ModelRetryExhaustedError",
    "ModelClient",
    "estimate_tokens",
]

#: 支持的 provider（适配点注册表）
PROVIDERS: tuple[str, ...] = ("mock", "openai_like")

#: 密钥环境变量（按序探测；密钥永不入代码与日志）
_API_KEY_ENV_VARS = ("PD_MODEL_API_KEY", "OPENAI_API_KEY")

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class ModelClientError(RuntimeError):
    """模型调用失败（provider 错误/配置缺失/脚本耗尽）。"""


class ModelTimeoutError(ModelClientError):
    """模型调用超时（重试预算耗尽）。"""


class ModelRetryExhaustedError(ModelClientError):
    """可重试错误耗尽重试预算。"""


def estimate_tokens(text: Any) -> int:
    """确定性 token 估算：CJK 每字 1 token + ASCII 词元每串 1 token。

    与 m2_information.context_builder.estimate_tokens 同口径（跨层一致），
    本地实现避免 M1→M2 的循环依赖。
    """
    if text is None:
        return 0
    if not isinstance(text, str):
        try:
            text = json.dumps(text, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(text)
    tokens = 0
    in_ascii = False
    for ch in text:
        if ord(ch) > 0x2E80:  # CJK 及全角区
            tokens += 1
            in_ascii = False
        elif ch.isalnum():
            if not in_ascii:
                tokens += 1
                in_ascii = True
        else:
            in_ascii = False
    return tokens


def _messages_text(messages: list) -> str:
    return "\n".join(
        str(m.get("content", "")) for m in messages if isinstance(m, Mapping)
    )


def _urllib_transport(url: str, headers: dict, payload: dict,
                      timeout_s: float) -> tuple[int, dict]:
    """缺省 HTTP 传输（stdlib urllib；返回 (status, body_dict)）。"""
    request = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(timeout_s)) as response:
            body = response.read().decode("utf-8")
            return int(response.status), (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            parsed = json.loads(body) if body else {}
        except (TypeError, ValueError):
            parsed = {"error": {"message": body[:500]}}
        return int(exc.code), parsed
    except urllib.error.URLError as exc:
        reason = str(getattr(exc, "reason", "") or exc)
        if "timed out" in reason.lower() or "timeout" in reason.lower():
            raise TimeoutError(f"请求超时（{timeout_s}s）: {reason}") from exc
        raise ConnectionError(f"网络错误: {reason}") from exc


class ModelClient:
    """统一模型客户端（provider 适配 + 超时/重试 + 成本上报）。"""

    def __init__(
        self,
        provider: str = "mock",
        *,
        model: str | None = None,
        script: list | None = None,
        mock_text: str | None = None,
        api_base: str | None = None,
        api_key: str | None = None,
        timeout_s: float = 30.0,
        max_retries: int = 2,
        retry_backoff_s: float = 0.2,
        transport: Callable[[str, dict, dict, float], tuple[int, dict]] | None = None,
        **options: Any,
    ) -> None:
        self.provider = str(provider)
        if self.provider not in PROVIDERS:
            raise ModelClientError(
                f"未知 provider: {self.provider!r}（允许: {'/'.join(PROVIDERS)}）")
        self.model = str(model or ("mock-1" if self.provider == "mock" else "gpt-default"))
        self.script = [dict(item) for item in (script or [])]
        self.mock_text = mock_text
        self.api_base = str(api_base or "").rstrip("/")
        self._api_key = api_key
        self.timeout_s = float(timeout_s)
        self.max_retries = int(max_retries)
        self.retry_backoff_s = float(retry_backoff_s)
        self.transport = transport or _urllib_transport
        self.options = dict(options)
        self.calls: list[dict] = []  # 调用审计（request 摘要 + usage；密钥绝不入内）
        self._mock_cursor = 0

    # ------------------------------------------------------------- 主入口
    def complete(self, request: Mapping) -> dict:
        """发起一次模型调用（request/response 形态见模块 docstring）。"""
        payload = dict(request or {})
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ModelClientError("ModelRequest.messages 必须为非空列表")
        trace_id = str(payload.get("trace_id", "") or "")
        if self.provider == "mock":
            response = self._complete_mock(payload, messages, trace_id)
        else:
            response = self._complete_remote(payload, messages, trace_id)
        self.calls.append({
            "trace_id": trace_id,
            "provider": self.provider,
            "usage": dict(response["usage"]),
            "cost": dict(response["cost"]),
        })
        return response

    # ------------------------------------------------------------- mock
    def _complete_mock(self, payload: dict, messages: list, trace_id: str) -> dict:
        if self.script:
            if not self._mock_cursor < len(self.script):
                raise ModelClientError(
                    f"mock 脚本已耗尽（第 {self._mock_cursor + 1} 次调用无对应响应；"
                    f"脚本共 {len(self.script)} 条）")
            scripted = dict(self.script[self._mock_cursor])
            self._mock_cursor += 1
        else:
            scripted = {"text": self.mock_text} if self.mock_text else {}
        text = str(scripted.get("text", "") or self._mock_text(messages))
        usage = self._usage_of(scripted, messages, text)
        response = {
            "text": text,
            "usage": usage,
            "cost": {"tokens": usage["total_tokens"],
                     "prompt_tokens": usage["prompt_tokens"],
                     "completion_tokens": usage["completion_tokens"]},
            "provider": "mock",
            "model": self.model,
            "latency_ms": 0,
            "trace_id": trace_id,
        }
        if scripted.get("tool_calls") is not None:
            response["tool_calls"] = list(scripted["tool_calls"])
        for key in ("todo_updates", "completion_claim", "request_input",
                    "wait_event", "fail"):
            if scripted.get(key) is not None:
                response[key] = scripted[key]
        return response

    @staticmethod
    def _mock_text(messages: list) -> str:
        """无脚本时的确定性回声（persona 离线接线：非空文本即可用）。"""
        user_text = ""
        for message in reversed(messages):
            if isinstance(message, Mapping) and str(message.get("role")) == "user":
                user_text = str(message.get("content", ""))
                break
        return f"（mock 模型回声）{user_text[:120] or '收到'}"

    def _usage_of(self, scripted: Mapping, messages: list, text: str) -> dict:
        usage = scripted.get("usage") or {}
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        if prompt <= 0:
            prompt = estimate_tokens(_messages_text(messages))
        if completion <= 0:
            completion = estimate_tokens(text)
        return {"prompt_tokens": prompt, "completion_tokens": completion,
                "total_tokens": prompt + completion}

    # ------------------------------------------------------------- remote
    def _complete_remote(self, payload: dict, messages: list, trace_id: str) -> dict:
        if not self.api_base:
            raise ModelClientError("openai_like 需要 api_base（端点配置注入）")
        api_key = self._api_key or self._env_api_key()
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        body: dict = {"model": self.model, "messages": [dict(m) for m in messages]}
        if payload.get("tools") is not None:
            body["tools"] = list(payload["tools"])
        if payload.get("temperature") is not None:
            body["temperature"] = float(payload["temperature"])
        if payload.get("max_tokens") is not None:
            body["max_tokens"] = int(payload["max_tokens"])

        url = f"{self.api_base}/chat/completions"
        started = time.perf_counter()
        last_error: Exception | None = None
        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                status, data = self.transport(url, headers, body, self.timeout_s)
            except TimeoutError as exc:
                last_error = ModelTimeoutError(
                    f"模型调用超时（尝试 {attempt}/{attempts}）: {exc}")
                self._backoff(attempt, attempts)
                continue
            except (ConnectionError, OSError) as exc:
                last_error = ModelClientError(
                    f"网络错误（尝试 {attempt}/{attempts}）: {exc}")
                self._backoff(attempt, attempts)
                continue
            if status in _RETRYABLE_STATUS:
                last_error = ModelClientError(
                    f"HTTP {status}（可重试，尝试 {attempt}/{attempts}）")
                self._backoff(attempt, attempts)
                continue
            if status != 200:
                raise ModelClientError(
                    f"HTTP {status}: {self._error_message(data)}")
            return self._parse_openai_response(data, trace_id, started)
        # 重试预算耗尽：超时类原样抛，其余包成 ModelRetryExhaustedError
        if isinstance(last_error, ModelTimeoutError):
            raise last_error
        raise ModelRetryExhaustedError(
            f"重试预算耗尽（{attempts} 次尝试均失败）: {last_error}") from last_error

    def _backoff(self, attempt: int, attempts: int) -> None:
        if attempt < attempts and self.retry_backoff_s > 0:
            time.sleep(self.retry_backoff_s)

    @staticmethod
    def _env_api_key() -> str | None:
        for var in _API_KEY_ENV_VARS:
            value = os.environ.get(var)
            if value:
                return value
        return None

    @staticmethod
    def _error_message(data: Mapping) -> str:
        error = (data or {}).get("error") or {}
        message = error.get("message") if isinstance(error, Mapping) else None
        return str(message or data)[:300]

    def _parse_openai_response(self, data: Mapping, trace_id: str,
                               started: float) -> dict:
        choices = (data or {}).get("choices") or []
        if not choices:
            raise ModelClientError(f"响应缺 choices: {str(data)[:200]}")
        message = dict(choices[0].get("message") or {})
        text = str(message.get("content") or "")
        usage = dict((data or {}).get("usage") or {})
        prompt = int(usage.get("prompt_tokens") or 0) or estimate_tokens(text)
        completion = int(usage.get("completion_tokens") or 0) or estimate_tokens(text)
        response = {
            "text": text,
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                      "total_tokens": prompt + completion},
            "cost": {"tokens": prompt + completion,
                     "prompt_tokens": prompt, "completion_tokens": completion},
            "provider": self.provider,
            "model": self.model,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "trace_id": trace_id,
        }
        if message.get("tool_calls") is not None:
            response["tool_calls"] = list(message["tool_calls"])
        return response
