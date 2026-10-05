#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-
"""arena/harvest_runs.py · 打捞已落盘 run 记录 → partial JSON（判定批的救命索）。

用途：判定批因超时/中断丢失内存结果时，从 runs 目录里的 eval.json 重建 partial，
供 converge.py --merge 合并判定。只读 run 目录，不重跑任何仿真。

用法::

    python arena/harvest_runs.py --runs-root runs/judge-30k \
        --out runtime/judge-partials/partial-harvested-<tag>.json [--tag t1]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harvest_runs.py", description="打捞 run 记录为 partial")
    ap.add_argument("--runs-root", required=True, help="run 记录根目录（含 <run_id>/eval.json）")
    ap.add_argument("--out", required=True, help="输出 partial JSON 路径")
    ap.add_argument("--tag", default="harvest", help="partial 文件名标签")
    args = ap.parse_args(argv)

    root = Path(args.runs_root)
    if not root.is_dir():
        print(f"NO RUNS DIR: {root}")
        return 2
    items: list[dict] = []
    bad = 0
    for d in sorted(root.iterdir()):
        ev = d / "eval.json"
        if not d.is_dir() or not ev.is_file():
            continue
        try:
            items.append(json.loads(ev.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError):
            bad += 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    name = out if out.suffix == ".json" else out / f"partial-harvested-{args.tag}.json"
    name.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    print(f"HARVEST OK: {len(items)} runs -> {name} (bad={bad})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
