# -*- coding: utf-8 -*-
"""fault.llm_bridge · 自然语言 → 故障 DSL 的定向注入接口。

链路（owner 夜班令线3-2）：
  用户中文 → LLM（Higress 100.100.0.6:8080，提示词落盘 fault/prompts/）→ JSON
           → dsl.validate_fault_dict（四类白名单 + 参数域 + 元件存在性，越界即拒）
  LLM 不可达/未配置 → 规则解析器离线兜底（关键词+元件名匹配），页面不瘫。

安全设计：**绝不信任 LLM 输出**——无论来源，一律过同一校验器；拒绝时返回
逐条 reasons。密钥零打印：真实调用经 HigressClient 从环境变量读凭证
（argv-free，由 bao 包装进程注入），本模块代码与日志不落任何密钥。
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Optional

from .dsl import FAULT_TYPES, FaultRejected, FaultSpec, validate_fault_dict
from .topology import Topology

__all__ = ["nl_to_fault", "parse_llm_output", "rule_parse", "render_prompt",
           "HigressClient", "PROMPT_PATH"]

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts",
                           "inject_system.md")

# 关键词 → 类型（规则解析器兜底用；顺序即优先级）
_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("光伏脱网", "光伏退出", "逆变器脱扣", "光伏跳", "防孤岛动作", "脱网"), "PV_TRIP"),
    (("过载", "重载", "超容", "负载率"), "TX_OVERLOAD"),
    (("断线", "断相", "导线断"), "LINE_BREAK"),
    (("短路", "接地", "闪络", "相间"), "SHORT_CIRCUIT"),
]

_RATIO_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


# ================================================================ 提示词
def render_prompt(topo: Topology) -> str:
    """读落盘提示词模板并填充当前拓扑元件清单（target 只能取这些 id）。"""
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        tpl = f.read()
    lines = []
    for e in topo.elements():
        desc = f"- {e.id}（{e.kind}，{e.name}）"
        lines.append(desc)
    return tpl.replace("{{ELEMENTS}}", "\n".join(lines))


# ================================================================ 规则解析（离线兜底）
def rule_parse(text: str, topo: Topology) -> FaultSpec:
    """关键词 + 元件名/ID 匹配 → FaultSpec（校验同 LLM 路径，越界即拒）。"""
    reasons: list[str] = []
    ftype = None
    for kws, t in _KEYWORDS:
        if any(k in text for k in kws):
            ftype = t
            break
    if ftype is None:
        raise FaultRejected([f"规则解析器未能识别故障类型（关键词未命中，白名单 {list(FAULT_TYPES)}）"])

    target = None
    # ① 元件 ID 直引
    for eid in topo.ids():
        if re.search(r"\b" + re.escape(eid) + r"\b", text):
            target = eid
            break
    # ② 元件名子串
    if target is None:
        for e in topo.elements():
            if e.name and e.name in text:
                target = e.id
                break
    if target is None:
        # ③ 唯一类别推断（如"光伏"全园唯一）
        kind_hint = {"PV_TRIP": "pv", "TX_OVERLOAD": "transformer"}.get(ftype)
        if kind_hint:
            cands = topo.by_kind(kind_hint)
            if len(cands) == 1:
                target = cands[0].id
    if target is None:
        reasons.append("未能识别目标元件（可用: " + ",".join(topo.ids()) + "）")
        raise FaultRejected(reasons)

    params: dict = {}
    m = _RATIO_RE.search(text)
    if ftype == "TX_OVERLOAD" and m:
        params["overload_ratio"] = round(float(m.group(1)) / 100.0, 4)
    if ftype == "SHORT_CIRCUIT":
        if "两相" in text:
            params["phase"] = "two"
        elif "三相" in text or "三相" in text:
            params["phase"] = "three"
        elif "单相" in text or "接地" in text:
            params["phase"] = "single"
    raw = {"type": ftype, "target": target, "at_s": 0.0, "params": params,
           "note": f"规则解析器自: {text[:50]}"}
    return validate_fault_dict(raw, topo, seq=0)


# ================================================================ LLM 输出解析（不信任，一律校验）
def parse_llm_output(text: str, topo: Topology, *, seq: int = 0) -> FaultSpec:
    """LLM 返回文本 → JSON → 校验 → FaultSpec。非法/越界 → FaultRejected。"""
    raw_text = text.strip()
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw_text).strip()
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise FaultRejected([f"LLM 输出不是合法 JSON: {exc}"]) from exc
    if not isinstance(data, dict):
        raise FaultRejected(["LLM 输出必须是 JSON 对象"])
    if data.get("rejected"):
        rs = data.get("reasons") or ["LLM 未给出理由"]
        raise FaultRejected(["LLM 侧拒绝: " + "; ".join(str(r) for r in rs)])
    data.setdefault("at_s", 0.0)
    data["note"] = str(data.get("note", "")) + " [来源: LLM]"
    return validate_fault_dict(data, topo, seq=seq)


# ================================================================ 总入口
def nl_to_fault(text: str, topo: Topology, client: Optional[Any] = None,
                *, seq: int = 0) -> FaultSpec:
    """自然语言 → FaultSpec。client=None 走规则兜底；否则 LLM 优先、失败落兜底。"""
    if client is None:
        return rule_parse(text, topo)
    try:
        prompt = render_prompt(topo)
        out = client.chat(prompt, text)
        return parse_llm_output(out, topo, seq=seq)
    except FaultRejected:
        raise  # LLM 明确拒绝/输出越界：如实拒绝（不静默兜底——注入是危险操作）
    except Exception:
        return rule_parse(text, topo)  # 通道故障 → 离线兜底，页面不瘫


# ================================================================ Higress 客户端
class HigressClient:
    """经 Higress 的 OpenAI 兼容对话客户端（模型流量唯一入口，W-07 口径）。

    凭证从环境变量读取（HIGRESS_API_KEY / HIGRESS_BASE_URL，由 bao 包装进程
    注入，TTL≤1h）——argv-free，零打印，不进日志。
    """

    def __init__(self, model: str = "qoder-default",
                 base_url: Optional[str] = None, api_key: Optional[str] = None,
                 timeout_s: int = 30) -> None:
        self.base_url = (base_url or os.environ.get("HIGRESS_BASE_URL")
                         or "http://100.100.0.6:8080").rstrip("/")
        self.api_key = api_key or os.environ.get("HIGRESS_API_KEY") or ""
        self.model = model
        self.timeout_s = timeout_s

    def chat(self, system_prompt: str, user_text: str) -> str:
        if not self.api_key:
            raise RuntimeError("HIGRESS_API_KEY 未设置（经 bao 注入；零打印纪律）")
        url = f"{self.base_url}/v1/chat/completions"
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Higress HTTP {exc.code}") from exc
        return data["choices"][0]["message"]["content"]
