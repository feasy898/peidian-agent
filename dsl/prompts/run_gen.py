#!/usr/bin/env python3.12
"""run_gen.py · ParkDSL 生成提示词运行器（worker-A 线1）

真实模型调用面：OpenAI 兼容 /chat/completions——**经 arena.model_gateway 收编**
（module-map #18/#19；env 优先序 LLM_API_KEY/BIGMODEL_API_KEY/OPENAI_API_KEY，
base 同理；--base-url/--model 显式参数优先，历史缺省不变）。
配额纪律：线1 全程 ≤3 次真实调用；每次成功调用自动追加 quota-ledger.md。

密钥纪律（红线1）：API key 只经 env(优先序见 model_gateway) 或 stdin(--api-key-stdin) 进入，
绝不进 argv/日志/产物。argv-free。

用法:
  python run_gen.py --tier simple  --brief "..." [--out park.yaml] [--api-key-stdin] [--validate]
退出码: 0=生成且(若--validate)校验通过  1=生成/校验失败  2=用法/环境错误
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:      # arena.model_gateway 在仓根 arena/ 包内
    sys.path.insert(0, str(ROOT))
VALIDATE = HERE.parent / "validate.py"
LEDGER = HERE / "quota-ledger.md"
TIERS = ("simple", "medium", "complex")
QUOTA_LIMIT = 3


def _ledger_count() -> int:
    if not LEDGER.exists():
        return 0
    return len(re.findall(r"^\| \d{4}-", LEDGER.read_text(encoding="utf-8"), re.M))


def _ledger_append(tier: str, status: str, model: str, note: str) -> None:
    ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(f"| {ts} | {tier} | {model} | {status} | {note} |\n")


def _find_key() -> str:
    """env key 探测收编 model_gateway（优先序 LLM_API_KEY > BIGMODEL_API_KEY > OPENAI_API_KEY）。"""
    from arena.model_gateway import find_api_key   # sys.path 已在模块头指向仓根
    return find_api_key() or ""


def _read_key_from_stdin() -> str:
    print("粘贴 API key 后回车（输入不回显、不落日志）：", file=sys.stderr)
    return sys.stdin.readline().strip()


def _chat(base: str, model: str, key: str, system: str, user: str, timeout: int = 120) -> str:
    """经 model_gateway 发 OpenAI 兼容对话（key 只进请求头；失败如实抛异常）。"""
    from arena.model_gateway import ModelGateway   # sys.path 已在模块头指向仓根

    gw = ModelGateway(api_key=key, base_url=base, model=model, timeout_s=timeout)
    return gw.chat(system, user, temperature=0.4)


def _extract_yaml(text: str) -> str | None:
    m = re.search(r"```yaml\s*(.*?)```", text, re.S)
    if m:
        return m.group(1).strip()
    if text.lstrip().startswith("api:"):
        return text.strip()
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="run_gen.py")
    ap.add_argument("--tier", choices=TIERS, required=True)
    ap.add_argument("--brief", required=True, help="用户对园区的自然语言描述")
    ap.add_argument("--out", help="生成 DSL 落盘路径")
    ap.add_argument("--api-key-stdin", action="store_true", help="从 stdin 读 key（不进 argv）")
    ap.add_argument("--validate", action="store_true", help="生成后立即过 validate.py 校验")
    ap.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL", "http://100.100.0.6:8080/v1"))
    ap.add_argument("--model", default=os.environ.get("LLM_MODEL", "qwen3-32b"))
    args = ap.parse_args(argv)

    if _ledger_count() >= QUOTA_LIMIT:
        print(f"[QUOTA] 线1 真实调用配额已用满（{QUOTA_LIMIT} 次），拒绝调用。台账: {LEDGER}")
        return 2
    key = _find_key() or (_read_key_from_stdin() if args.api_key_stdin else "")
    if not key:
        print("[E-NOKEY] 无 API key：设 env LLM_API_KEY/BIGMODEL_API_KEY/OPENAI_API_KEY "
              "或 --api-key-stdin。（密钥零打印：key 不进 argv/日志）")
        return 2

    prompt_file = HERE / f"gen-{args.tier}.prompt.md"
    system = prompt_file.read_text(encoding="utf-8")
    system = re.sub(r"^> .*?\n", "", system, flags=re.M)  # 去掉头部引注行
    try:
        text = _chat(args.base_url, args.model, key, system, args.brief)
    except Exception as e:  # noqa: BLE001 —— 网络面异常统一大声失败
        _ledger_append(args.tier, "CALL_FAIL", args.model, str(e)[:80])
        print(f"[E-CALL] 调用失败: {e}")
        return 1
    yaml_text = _extract_yaml(text)
    if not yaml_text:
        _ledger_append(args.tier, "PARSE_FAIL", args.model, "no yaml block")
        print("[E-PARSE] 模型输出中未找到 ```yaml 代码块")
        print(text[:400])
        return 1
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(yaml_text + "\n", encoding="utf-8")
        print(f"[OK] DSL 已写 {args.out} ({len(yaml_text)} 字节)")
    else:
        print(yaml_text)
    _ledger_append(args.tier, "OK", args.model, f"{len(yaml_text)}B out={args.out or '-'}")

    if args.validate:
        target = args.out
        if not target:
            import tempfile
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as tf:
                tf.write(yaml_text + "\n")
                target = tf.name
        rc = subprocess.run([sys.executable, str(VALIDATE), "validate", target]).returncode
        return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
