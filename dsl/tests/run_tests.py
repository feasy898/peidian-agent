#!/usr/bin/env python3.12
"""run_tests.py · ParkDSL v1 全量测试（worker-A 线1）

覆盖：
  A. 三档样例 validate 全过（退出码 0）
  B. 负向样例各触发指定位错误码（重复 ID/悬空引用/变压器过载/档位不符/闭环运行/电压域/api 错）
  C. 三档样例 export → JSON 可解析且结构完整（api/nodes/links/telemetry）
  D. tier 推断一致性（summary 口径）

退出码: 0=全过  1=有失败（逐条打印 [FAIL]）
用法: python dsl/tests/run_tests.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DSL = HERE.parent
REPO = DSL.parent
VALIDATE = DSL / "validate.py"
EXAMPLES = DSL / "examples"
PY = sys.executable

CASES: list[tuple[str, bool]] = []  # (描述, 是否通过)


def record(name: str, ok: bool, detail: str = "") -> None:
    CASES.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  —— {detail}" if detail and not ok else ""))


def run_validate(target: str) -> tuple[int, str]:
    p = subprocess.run([PY, str(VALIDATE), "validate", target],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def main() -> int:
    print("== A. 三档样例校验（退出码 0 为证） ==")
    for f in sorted(EXAMPLES.glob("park-*.yaml")):
        rc, out = run_validate(str(f))
        record(f"validate {f.name}", rc == 0 and "PASS" in out, out.strip()[:200])

    print("== B. 负向用例（必须报对应错误码且退出码 1） ==")
    neg = json.loads((HERE / "negative_cases.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as td:
        for case in neg:
            p = Path(td) / f"{case['name']}.yaml"
            text = (EXAMPLES / case.get("base", "park-simple-01.yaml")).read_text(encoding="utf-8")
            for old, new in case["patch"]:
                if old not in text:
                    print(f"    [BUG] patch 目标未命中: {old[:50]!r}")
                text = text.replace(old, new, 1)
            p.write_text(text, encoding="utf-8")
            rc, out = run_validate(str(p))
            hit = rc == 1 and case["expect_code"] in out
            record(f"negative/{case['name']} → {case['expect_code']}", hit,
                   f"rc={rc} out={out.strip()[:200]}")

        print("== C. export → parkdsl-web/1 JSON 结构完整 ==")
        for f in sorted(EXAMPLES.glob("park-*.yaml")):
            outp = Path(td) / f"{f.stem}.json"
            r = subprocess.run([PY, str(VALIDATE), "export", str(f), "-o", str(outp)],
                               capture_output=True, text=True)
            ok = r.returncode == 0 and outp.exists()
            data = {}
            if ok:
                try:
                    data = json.loads(outp.read_text(encoding="utf-8"))
                    ok = (data.get("api") == "parkdsl-web/1" and len(data.get("nodes", [])) > 0
                          and len(data.get("links", [])) > 0
                          and data.get("telemetry", {}).get("seed") is not None)
                except json.JSONDecodeError as e:
                    ok = False
                    print(f"    json error: {e}")
            record(f"export {f.name}", ok, (r.stdout + r.stderr).strip()[:200])

    print("== D. summary tier 推断一致性 ==")
    r = subprocess.run([PY, str(VALIDATE), "summary"] + [str(f) for f in sorted(EXAMPLES.glob('park-*.yaml'))],
                       capture_output=True, text=True)
    ok = r.returncode == 0
    for tier in ("simple", "medium", "complex"):
        ok = ok and f"tier={tier}" in r.stdout
    record("summary 三档推断", ok, r.stdout + r.stderr)

    failed = [n for n, o in CASES if not o]
    print(f"\nTOTAL cases={len(CASES)} failed={len(failed)}")
    for n in failed:
        print(f"  FAILED: {n}")
    print("RESULT:", "PASS" if not failed else "FAIL")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
