# -*- coding: utf-8 -*-
"""CI 隔离断言（specs/README.md §3.4 / specs/ADDENDUM.md §F）。

holdout 独立验收实例的字样（场景 ID、电价方案 ID、操作规程 ID 段）不得出现在
开发仓库的任何交付目录中。本脚本对以下目录递归扫描（specs/ 与 runtime/ 不在
扫描范围；.git 与仓库根的说明性文档同样不涉及交付目录）：

    golden/ scenarios/ src/ tests/ ontology/ regulations/
    tools/ skills/ prompts/ assets/

匹配正则： ``PARK-002|TARIFF-2026B|OP-1[0-9]``

退出码：0 = 全部零命中；1 = 存在命中（列出命中文件与行号）。

用法：
    python scripts/ci_isolation.py            # 以仓库根（脚本父目录的父目录）为基准
    python scripts/ci_isolation.py --root X   # 显式指定仓库根

本模块同时作为库使用：``run_isolation(root) -> list[IsolationHit]``
（run_evals.py 每次运行前先调用隔离断言）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 隔离正则：独立验收实例的实例 ID / 电价方案 ID / 操作规程 ID 段
# （ADDENDUM §F 原文 ``OP-1x`` 通配一位 → 等宽正则 ``OP-1[0-9]``，覆盖 OP-10..OP-19 段）
ISOLATION_PATTERN = r"PARK-002|TARIFF-2026B|OP-1[0-9]"

# 扫描目录（相对仓库根）；与 ADDENDUM §F 的目录清单一致
SCAN_DIRS = (
    "golden",
    "scenarios",
    "src",
    "tests",
    "ontology",
    "regulations",
    "tools",
    "skills",
    "prompts",
    "assets",
)

_TEXT_SUFFIXES = frozenset({
    ".py", ".yaml", ".yml", ".json", ".jsonl", ".md", ".txt", ".toml", ".cfg",
    ".ini", ".sh", ".bat", ".ps1", ".sql", ".csv", ".html", ".js", ".ts",
})  # 仅作文档说明；扫描对全部文件按文本读取，不按后缀过滤


class IsolationHit:
    """一次命中。"""

    def __init__(self, rel_path: str, line_no: int, line_text: str, matched: str) -> None:
        self.rel_path = rel_path
        self.line_no = line_no
        self.line_text = line_text
        self.matched = matched

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"IsolationHit({self.rel_path}:{self.line_no} matched={self.matched!r})"


def repo_root_from_script() -> Path:
    """仓库根 = scripts/ 的父目录。"""
    return Path(__file__).resolve().parent.parent


def run_isolation(root: Path | None = None) -> list:
    """执行隔离扫描，返回命中列表（空列表 = 通过）。"""
    root = (root or repo_root_from_script()).resolve()
    pattern = re.compile(ISOLATION_PATTERN)
    hits: list = []
    for name in SCAN_DIRS:
        base = root / name
        if not base.exists():
            continue  # 目录存在性由 run_evals --selftest 的目录完整性断言负责
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            # 全部按文本读取（errors=replace），保证任何文件都不漏检
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = path.relative_to(root).as_posix()
            for line_no, line in enumerate(text.splitlines(), start=1):
                m = pattern.search(line)
                if m:
                    hits.append(IsolationHit(rel, line_no, line.strip()[:200], m.group(0)))
    return hits


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="holdout 隔离断言（命中即验收作废）")
    parser.add_argument("--root", type=Path, default=None, help="仓库根目录（默认：脚本位置推断）")
    args = parser.parse_args(argv)

    hits = run_isolation(args.root)
    if hits:
        print(f"ISOLATION VIOLATION: {len(hits)} hit(s)")
        for hit in hits:
            print(f"  {hit.rel_path}:{hit.line_no}: matched={hit.matched!r} :: {hit.line_text}")
        return 1
    print(f"ISOLATION OK: pattern={ISOLATION_PATTERN!r} zero hits in {', '.join(SCAN_DIRS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
