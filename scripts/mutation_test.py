# -*- coding: utf-8 -*-
"""mutation_test.py · 受控变异测试工具（量化 EVAL 对 oracle 行为的覆盖）。

定位与纪律（ASSET 资产工程阶段引入）：
- 本脚本是**唯一允许触碰 oracle 的变异工具**：变异 = 按计划文件对 oracle 文件做
  精确子串替换，跑模块 EVAL 记录退出码，然后**强制 git 还原并校验 hash 一致**。
- 变异目标只允许 oracle 路径（src/ tools/ ontology/ regulations/ golden/
  scenarios/ releases/ scripts/ run_evals.py）；计划文件声明其他路径一律拒收。
- 每个变异执行序列（任一步失败：还原并继续下一个；还原失败：整轮中止）：
    1. ``git status`` 必须干净（脏树 → 该变异记 invalid 跳过；口径见下）；
    2. 校验 ``find`` 在 target 中恰好出现 1 次（否则记 invalid 跳过，不应用）；
       Windows 工作区可能为 CRLF 行尾：精确匹配 0 次时自动尝试 CRLF 变体
       （find/replace 中 ``\n`` → ``\r\n``；命中即按该变体应用，结果记 find_variant）；
    3. 应用替换（字节级 utf-8，不做行尾转换）；
    4. ``python run_evals.py --module <mX>`` 记录退出码（非 0 = killed）；
    5. ``git checkout -- <target>`` 强制还原；
    6. 还原校验：``git status --porcelain -- <target>`` 为空（git 权威判定）且
       **行尾归一化 sha256**（``\r\n``→``\n`` 后取 sha256）与变异前一致——
       autocrlf 环境下 checkout 可能把 LF 工作文件重写为 CRLF，字节级比对会误报；
       归一化仍不一致 → 再还原一次；仍不一致 → 中止整轮。

"干净"口径（--require-clean-scope）：
- ``oracle``（缺省）：仅要求 **oracle 路径无未提交的已跟踪文件改动**——变异/还原/
  hash 比对只作用于 oracle 文件，这是保证该序列安全的最小充分条件；
- ``all``：要求整个仓库无未提交的已跟踪文件改动（最严格）。
- 两种口径都忽略 **未跟踪文件**（--untracked-files=no）：工具自身产物
  （.mutations/）与并行交付物（specs-v2/ 等）不应自锁工具。

用法（仓库根运行）::

    python scripts/mutation_test.py --module m3 --plan .mutations/plan-m3.json
    python scripts/mutation_test.py --module m3 --plan .mutations/plan-m3.json \\
        --baseline --require-clean-scope all

- ``--baseline``：变异前先跑一遍无变异 EVAL，退出码写 ``.mutations/baseline-<mX>.json``
  （survivor 结论只有在基线全绿时才可解读）。
- 结果写 ``.mutations/results-<mX>.json``（顶层键集固定，见 RESULT_KEYS）；
  stdout 末行 = 同一结果 JSON 的单行压缩版。

退出码：0 = 全部变异处置完毕（killed/survivor 都是正常结论）；
        1 = 还原失败等不安全状态（整轮中止）；2 = 用法/计划文件错误。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / ".mutations"

#: 变异目标允许的 oracle 路径白名单（与本仓库 oracle 口径一致；工具层强制）
ORACLE_ROOTS = (
    "src", "tools", "ontology", "regulations", "golden",
    "scenarios", "releases", "scripts", "run_evals.py",
)

#: 结果 JSON 顶层键集（口径固定，消费方按此解析）
RESULT_KEYS = ("module", "planned", "valid", "killed", "survivors",
               "redline_all_killed", "per_mutation")

#: 单个变异的 EVAL 超时（秒）；超时视为行为改变（killed，note 标注 timed_out）
EVAL_TIMEOUT_S = 900

#: 必填计划字段
REQUIRED_PLAN_FIELDS = ("id", "redline", "target", "find", "replace", "description")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    """仓库根执行 git 子命令（文本输出）。"""
    proc = subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败 (rc={proc.returncode}): "
                           f"{(proc.stderr or proc.stdout).strip()[:400]}")
    return proc


def dirty_lines(scope: str) -> list[str]:
    """未提交的**已跟踪文件改动**行（忽略未跟踪文件）。

    scope="oracle" 只看 oracle 路径；scope="all" 看全仓库。
    """
    args = ["status", "--porcelain", "--untracked-files=no", "--"]
    if scope == "oracle":
        args.extend(ORACLE_ROOTS)
    return git(args).stdout.splitlines()


def _target_within_oracle(target_rel: str) -> str | None:
    """校验目标路径合法（oracle 白名单内、无越界），返回 posix 相对路径或错误信息。"""
    if not target_rel or Path(target_rel).is_absolute() or "\\" in target_rel:
        return f"target 必须是仓库根相对 posix 路径: {target_rel!r}"
    parts = Path(target_rel).parts
    if any(p in ("..", ".") for p in parts):
        return f"target 不允许路径越界: {target_rel!r}"
    top = parts[0] if parts else ""
    if target_rel == "run_evals.py":
        return None
    if top not in ORACLE_ROOTS:
        return (f"target 不在 oracle 白名单 ({'/'.join(ORACLE_ROOTS)}): {target_rel!r}"
                "——本工具只允许触碰 oracle")
    if len(parts) < 2:
        return f"target 必须具体到文件: {target_rel!r}"
    return None


def load_plan(plan_path: Path) -> tuple[str, list[dict]]:
    """装载并校验计划文件；返回 (module, mutations)。"""
    try:
        raw = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"计划文件不可读: {plan_path} ({exc})")
    if not isinstance(raw, list) or not raw:
        raise SystemExit(f"计划文件必须是变异对象数组（非空）: {plan_path}")
    seen_ids: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise SystemExit(f"计划第 {index} 项必须是对象")
        missing = [k for k in REQUIRED_PLAN_FIELDS if k not in item]
        if missing:
            raise SystemExit(f"计划第 {index} 项缺字段: {missing}")
        if item["id"] in seen_ids:
            raise SystemExit(f"计划变异 id 重复: {item['id']!r}")
        seen_ids.add(item["id"])
        if not isinstance(item["redline"], bool):
            raise SystemExit(f"计划变异 {item['id']}: redline 必须为布尔")
        err = _target_within_oracle(str(item["target"]))
        if err:
            raise SystemExit(f"计划变异 {item['id']}: {err}")
        if item["find"] == item["replace"]:
            raise SystemExit(f"计划变异 {item['id']}: find 与 replace 相同（非变异）")
    module = plan_path.stem.removeprefix("plan-")
    return module, raw


def run_evals(module: str) -> tuple[int | None, str, bool]:
    """跑模块 EVAL；返回 (退出码, 摘要输出, 是否超时)。"""
    try:
        proc = subprocess.run(
            [sys.executable, "run_evals.py", "--module", module],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=EVAL_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        tail = exc.stdout if isinstance(exc.stdout, str) else ""
        return None, tail.strip()[-400:], True
    combined = (proc.stdout or "") + (proc.stderr or "")
    summary = ""
    for line in combined.splitlines():
        if line.startswith("EVALS "):
            summary = line.strip()
    return proc.returncode, summary or combined.strip()[-400:], False


def restore_target(target_rel: str) -> None:
    git(["checkout", "--", target_rel])


def norm_sha256(text: str) -> str:
    """行尾归一化 sha256（\r\n → \n）——autocrlf 环境下的还原比对基准。"""
    return sha256_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def locate_find(text: str, find: str, replace: str) -> tuple[str, str, str] | None:
    """在 text 中定位 find：先精确匹配，0 次且文本含 CRLF 时尝试 CRLF 变体。

    返回 (变体 find, 变体 replace, 变体名)；恰好 1 次才返回，否则 None。
    """
    for variant_find, variant_replace, name in (
            (find, replace, "LF"),
            (find.replace("\n", "\r\n"), replace.replace("\n", "\r\n"), "CRLF")):
        if text.count(variant_find) == 1:
            return variant_find, variant_replace, name
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="受控变异测试：变异 oracle → 跑模块 EVAL → 强制还原 → 比对 hash")
    parser.add_argument("--module", required=True, metavar="m0..m7",
                        help="被测模块（决定 run_evals.py --module 参数与结果文件名）")
    parser.add_argument("--plan", required=True, metavar="plan.json",
                        help="变异计划文件（JSON 数组，字段见模块 docstring）")
    parser.add_argument("--baseline", action="store_true",
                        help="变异前先跑无变异基线 EVAL（写 .mutations/baseline-<mX>.json）")
    parser.add_argument("--require-clean-scope", choices=("oracle", "all"),
                        default="oracle", metavar="{oracle,all}",
                        help="git 干净口径：oracle=仅 oracle 路径（缺省）；all=全仓库")
    parser.add_argument("--check-plan", action="store_true",
                        help="只做静态校验（目标存在性 + find 恰好 1 次），不应用不跑 EVAL")
    args = parser.parse_args(argv)

    if args.module not in tuple(f"m{i}" for i in range(8)):
        parser.error(f"--module 必须为 m0..m7，实际 {args.module!r}")
    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = ROOT / plan_path
    module, mutations = load_plan(plan_path)
    if module != args.module:
        print(f"[mutation] 警告：计划文件名模块 {module!r} != --module {args.module!r}，"
              f"以 --module 为准", file=sys.stderr)
        module = args.module
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - 控制台不支持时保持默认
        pass

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.check_plan:
        bad = []
        for item in mutations:
            target_abs = ROOT / str(item["target"])
            if not target_abs.is_file():
                bad.append((item["id"], f"目标文件不存在: {item['target']}"))
                continue
            try:
                text = target_abs.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                bad.append((item["id"], f"非 utf-8 文本: {item['target']}"))
                continue
            if locate_find(text, str(item["find"]), str(item["replace"])) is None:
                total = text.count(str(item["find"])) + text.count(
                    str(item["find"]).replace("\n", "\r\n"))
                bad.append((item["id"], f"find 出现 {total} 次（要求恰好 1 次）"))
        if bad:
            for mid, why in bad:
                print(f"[check-plan] FAIL {mid}: {why}", file=sys.stderr)
            return 1
        print(f"[check-plan] OK module={module}: {len(mutations)} 个变异全部可定位")
        return 0

    if args.baseline:
        print(f"[mutation] 基线 EVAL（无变异）module={module} ...")
        base_rc, base_summary, base_timeout = run_evals(module)
        (RESULTS_DIR / f"baseline-{module}.json").write_text(
            json.dumps({"module": module, "exit_code": base_rc,
                        "timed_out": base_timeout, "summary": base_summary,
                        "generated_at": utc_now_iso()},
                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[mutation] 基线退出码={base_rc} {base_summary}")
        if base_rc != 0:
            print("[mutation] 基线非 0：survivor 结论不可解读；结果照常产出，"
                  "请先修复基线", file=sys.stderr)

    per_mutation: list[dict] = []
    survivors: list[dict] = []
    for item in mutations:
        mid = str(item["id"])
        target_rel = str(item["target"])
        target_abs = ROOT / target_rel
        entry: dict = {
            "id": mid, "redline": bool(item["redline"]), "target": target_rel,
            "description": str(item["description"]), "status": "invalid",
            "find_count": 0, "exit_code": None, "timed_out": False,
            "killed": False, "restored": False, "hash_match": None, "note": "",
        }

        def finish(entry: dict = entry, status: str = "", note: str = "") -> None:
            entry["status"] = status
            if note:
                entry["note"] = note
            per_mutation.append(entry)
            print(f"[mutation] {entry['id']}: {status}"
                  + (f" exit={entry['exit_code']}" if entry["exit_code"] is not None else "")
                  + (f" ({note})" if note else ""))

        # 1) git 干净检查（口径见 --require-clean-scope；未跟踪文件一律忽略）
        dirty = dirty_lines(args.require_clean_scope)
        if dirty:
            finish(status="skipped_dirty",
                   note=f"git status 非干净（{args.require_clean_scope} 口径，"
                        f"{len(dirty)} 行已跟踪改动）")
            continue
        # 2) find 恰好出现 1 次（字节级 utf-8；CRLF 工作区自动尝试 CRLF 变体）
        if not target_abs.is_file():
            finish(status="invalid", note=f"目标文件不存在: {target_rel}")
            continue
        original = target_abs.read_bytes()
        try:
            text = original.decode("utf-8")
        except UnicodeDecodeError:
            finish(status="invalid", note="目标文件非 utf-8 文本，拒绝变异")
            continue
        original_hash = norm_sha256(text)
        located = locate_find(text, str(item["find"]), str(item["replace"]))
        if located is None:
            total = text.count(str(item["find"])) + text.count(
                str(item["find"]).replace("\n", "\r\n"))
            entry["find_count"] = total
            finish(status="invalid",
                   note=f"find 出现 {total} 次（要求恰好 1 次），跳过不应用")
            continue
        variant_find, variant_replace, variant_name = located
        entry["find_count"] = 1
        entry["find_variant"] = variant_name
        # 3)-5) 应用替换 → 跑 EVAL → 强制还原（失败再试一次；仍失败中止整轮）
        mutated_text = text.replace(variant_find, variant_replace, 1)
        try:
            target_abs.write_bytes(mutated_text.encode("utf-8"))
            exit_code, summary, timed_out = run_evals(module)
            entry["exit_code"] = exit_code
            entry["timed_out"] = timed_out
            entry["eval_summary"] = summary
            entry["killed"] = timed_out or (exit_code != 0)
        except Exception as exc:  # noqa: BLE001 - 任何一步失败都要还原并继续
            entry["note"] = f"eval 执行异常: {type(exc).__name__}: {exc}"[:400]
        finally:
            restored_ok = False
            for _attempt in (1, 2):
                restore_target(target_rel)
                back = target_abs.read_bytes().decode("utf-8", errors="replace")
                git_clean = not git(["status", "--porcelain", "--", target_rel]).stdout
                # autocrlf 下 checkout 可能把 LF 工作文件重写为 CRLF：
                # 权威判定 = git 视角干净 且 行尾归一化 hash 与变异前一致
                if git_clean and norm_sha256(back) == original_hash:
                    restored_ok = True
                    break
            if not restored_ok:
                entry["restored"] = False
                entry["hash_match"] = False
                per_mutation.append(entry)
                print(f"[mutation] {mid}: 还原失败，中止整轮（oracle 可能残留变异）",
                      file=sys.stderr)
                return 1
            entry["restored"] = True
            entry["hash_match"] = True
            if target_abs.read_bytes() != original:
                entry["note"] = "还原后 git 重写行尾（autocrlf；归一化内容一致）"
        if not entry["killed"]:
            survivors.append({"id": mid, "description": str(item["description"])})
        finish(status="killed" if entry["killed"] else "survived")

    redline_items = [e for e in per_mutation if e["redline"]]
    applied = ("killed", "survived")
    redline_all_killed = (
        bool(redline_items)
        and all(e["killed"] for e in redline_items if e["status"] in applied)
        and not any(e["redline"] and e["status"] not in applied for e in per_mutation))

    result = {
        "module": module,
        "planned": len(mutations),
        "valid": sum(1 for e in per_mutation if e["status"] in applied),
        "killed": sum(1 for e in per_mutation if e["killed"]),
        "survivors": survivors,
        "redline_all_killed": redline_all_killed,
        "per_mutation": per_mutation,
    }
    assert tuple(result) == RESULT_KEYS, "结果键集漂移（RESULT_KEYS 口径）"
    out_path = RESULTS_DIR / f"results-{module}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"[mutation] 结果 -> {out_path.relative_to(ROOT).as_posix()} "
          f"(planned={result['planned']} valid={result['valid']} "
          f"killed={result['killed']} survivors={len(survivors)} "
          f"redline_all_killed={redline_all_killed})")
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
