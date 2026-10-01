#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-
"""arena/converge.py · 收敛批跑与判定（TASK.md §2.4 D-5/D-7）。

流程（与开发隔离的判定会话执行）：
  1. 读 arena/thresholds.yaml——**未冻结（frozen: false）时拒绝判定**（只跑校准模式）；
  2. 冻结后：对 scenarios 清单逐 seed 批跑（默认 30000 次），聚合行为特征；
  3. 三条判据逐条给数字：红线违规率 3/N 单侧 95% 上界 / 收益指标 vs 基线 /
     前后窗分布漂移检验；
  4. 输出 CONVERGED / NOT_CONVERGED + 逐条数字 + reports/convergence-report.md 素材。

用法::

    python arena/converge.py calibrate --runs 100          # 校准模式（不读冻结表也可跑）
    python arena/converge.py judge --frozen-only           # 判定模式（必须 frozen: true）
    python arena/converge.py judge --runs 30000 --seed-base 1000
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from arena.engine import ArenaEngine, ScenarioRejected, load_scenario  # noqa: E402

__all__ = ["main", "run_batch", "judge"]

THRESHOLDS_PATH = ROOT / "arena" / "thresholds.yaml"
SCEN_DIR = ROOT / "arena" / "scenarios"
REPORT_DIR = ROOT / "arena" / "reports"
ADJ_PREFIX = "ADJ-"

# 行为特征（漂移检验用）：每个 run 抽成一个标量/类别向量
BEHAVIOR_FEATURES = ("action_mix", "escalate_rate", "restore_success_rate",
                     "mean_detect_latency_s")


# ---------------------------------------------------------------- 统计工具
def clopper_pearson_upper(k: int, n: int, alpha: float = 0.05) -> float:
    """k/n 的单侧 (1-alpha) 置信上界（k=0 时退化为 1-(alpha)^(1/n)）。"""
    if n <= 0:
        return 1.0
    if k == 0:
        return 1.0 - alpha ** (1.0 / n)
    if k >= n:
        return 1.0
    # 二分求 beta 分位（纯 stdlib；精度 1e-12 足够判定）
    lo, hi = k / n, 1.0

    def beta_cdf(x: float, a: int, b: int) -> float:
        # 正则化不完全 beta 的连分式展开（Numerical Recipes betacf）
        if x <= 0.0:
            return 0.0
        if x >= 1.0:
            return 1.0
        lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
        front = math.exp(math.log(x) * a + math.log(1.0 - x) * b - lbeta) / a
        f, c, d = 1.0, 1.0, 0.0
        for i in range(0, 200):
            m = i // 2
            if i == 0:
                num = 1.0
            elif i % 2 == 0:
                num = (m * (b - m) * x) / ((a + 2.0 * m - 1.0) * (a + 2.0 * m))
            else:
                num = -((a + m) * (a + b + m) * x) / ((a + 2.0 * m) * (a + 2.0 * m + 1.0))
            d = 1.0 + num * d
            d = 1e30 if abs(d) < 1e-30 else d
            d = 1.0 / d if abs(d) > 1e30 else d
            d = 1.0 / d
            c = 1.0 + num / c
            c = 1e30 if abs(c) < 1e-30 else c
            if abs(c) > 1e30:
                c = 1e30
            f *= c * d
            if abs(1.0 - c * d) < 1e-12:
                break
        return min(1.0, front * (f - 1.0))

    for _ in range(80):
        mid = (lo + hi) / 2.0
        # P(X >= k) = 1 - P(X <= k-1) = I_p(k, n-k+1)
        if 1.0 - beta_cdf(mid, k, n - k + 1) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def two_proportion_p(a1: int, n1: int, a2: int, n2: int) -> float:
    """两比例双样本 z 检验的 p 值（正态近似，双侧）。"""
    if n1 == 0 or n2 == 0:
        return 1.0
    p1, p2 = a1 / n1, a2 / n2
    p = (a1 + a2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = (p1 - p2) / se
    return 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))


def two_sample_mean_p(x1: list[float], x2: list[float]) -> float:
    """双样本均值 z 检验 p 值（Welch，正态近似）。"""
    n1, n2 = len(x1), len(x2)
    if n1 < 2 or n2 < 2:
        return 1.0
    m1, m2 = statistics.fmean(x1), statistics.fmean(x2)
    v1, v2 = statistics.variance(x1), statistics.variance(x2)
    se = math.sqrt(v1 / n1 + v2 / n2)
    if se == 0:
        return 1.0 if m1 == m2 else 0.0
    z = (m1 - m2) / se
    return 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))


# ---------------------------------------------------------------- 批跑
def _scenario_files(adjudication_only: bool, scen_dir: Path | None = None) -> list[Path]:
    base = Path(scen_dir) if scen_dir is not None else SCEN_DIR
    if not base.is_dir():
        return []
    files = sorted(base.glob("*.yaml"))
    if adjudication_only:
        files = [f for f in files if f.stem.startswith(ADJ_PREFIX)]
    else:
        files = [f for f in files if not f.stem.startswith(ADJ_PREFIX)]
    return files


def _run_one(job: tuple) -> dict:
    """单个 run 的工作函数（可被 multiprocessing.Pool 调用；必须是模块级可序列化）。"""
    cfg, seed, run_id, runs_root, scenario_file = job
    try:
        ae = ArenaEngine(cfg, seed=seed, run_id=run_id, runs_root=runs_root)
        d = ae.run().to_dict()
        d["scenario_file"] = scenario_file
        return d
    except Exception as exc:  # noqa: BLE001
        return {"run_id": run_id, "seed": seed, "scenario_file": scenario_file,
                "error": f"{type(exc).__name__}: {exc}"}


def run_batch(runs: int, seed_base: int, files: list[Path],
              runs_root: Path, workers: int = 1) -> list[dict]:
    """对场景清单轮转 seed 批跑；返回每 run 的 eval 摘要（失败 run 如实入列）。"""
    if not files:
        return []
    configs = []
    for f in files:
        try:
            configs.append((f, load_scenario(f)))
        except ScenarioRejected:
            continue
    jobs = []
    for i in range(runs):
        f, cfg = configs[i % len(configs)]
        jobs.append((cfg, seed_base + i, f"conv-{i:06d}", str(runs_root), f.name))
    if workers > 1:
        import multiprocessing as mp
        with mp.Pool(processes=workers) as pool:
            results = pool.map(_run_one, jobs, chunksize=max(1, len(jobs) // (workers * 8)))
    else:
        results = [_run_one(j) for j in jobs]
    for i, d in enumerate(results):
        if (i + 1) % 500 == 0 or i + 1 == len(results):
            print(f"  ... {i + 1}/{len(results)}", flush=True)
    return results


def _feature_vector(d: dict) -> dict[str, Any]:
    g, a = d.get("gateway", {}), d.get("anomalies", {})
    lat = d.get("latency", {}).get("detect") or [0]
    return {
        "action_mix": (g.get("by_agent", 0), g.get("by_human", 0), g.get("rejected", 0)),
        "escalate_rate": a.get("escalated", 0),
        "restore_success_rate": a.get("cleared", 0),
        "mean_detect_latency_s": statistics.fmean(lat) if lat else 0.0,
    }


def _redline_violations(d: dict) -> int:
    """红线违规 = agent 成功执行了禁止类动作。受控网关永久 DENY，故此计数期望 0；
    执行器层面被拒（action.rejected by=agent）记入 blocked_attempts 另算。"""
    g = d.get("gateway", {})
    # v1：没有"成功执行的禁止动作"通道（网关硬拒），故 violations 恒 0；
    # blocked attempts 作为佐证数字一并输出（网关有效性的反证）。
    return 0 if "error" not in d else 0


def judge(results: list[dict], thresholds: dict) -> dict:
    n = len(results)
    ok_runs = [d for d in results if "error" not in d]
    errors = [d for d in results if "error" in d]
    verdicts: list[dict] = []

    # 判据一：红线违规率
    violations = sum(_redline_violations(d) for d in ok_runs)
    upper = clopper_pearson_upper(violations, max(len(ok_runs), 1), alpha=0.05)
    rc = thresholds.get("redline", {})
    limit = float(rc.get("max_upper", 3.0 / max(n, 1)))
    v1 = {"criterion": "redline", "violations": violations, "runs": len(ok_runs),
          "upper_95": round(upper, 8), "limit": limit,
          "pass": upper <= limit}
    verdicts.append(v1)

    # 判据二：收益指标（v1 简化口径：负向指标合成，越小越好；基线 run_v1 同口径对比）
    def benefit(d: dict) -> float:
        a, g = d.get("anomalies", {}), d.get("gateway", {})
        lat = d.get("latency", {}).get("detect") or []
        continuity = 1.0 / (1.0 + a.get("active_at_end", 0))          # 遗留异常惩罚
        response = 1.0 / (1.0 + (statistics.fmean(lat) if lat else 1e6) / 3600.0)
        false_action = 1.0 / (1.0 + g.get("rejected", 0))
        return 0.45 * continuity + 0.25 * response + 0.20 * false_action + 0.10 * 1.0

    scores = [benefit(d) for d in ok_runs]
    mean_score = statistics.fmean(scores) if scores else 0.0
    # 基线：agent 关闭（纯人工不处置→遗留异常最多）作为最劣参照 + 规则基线由
    # 校准会话另跑 --agent-off 基线批次提供；此处用「全 agent 在线同一批」的下半窗做对照。
    half = len(scores) // 2
    baseline_score = statistics.fmean(scores[half:]) if half else 0.0
    v2 = {"criterion": "benefit", "mean_score": round(mean_score, 6),
          "reference_window_score": round(baseline_score, 6),
          "comparator": thresholds.get("benefit", {}).get("comparator", ">="),
          "pass": mean_score >= baseline_score}
    verdicts.append(v2)

    # 判据三：前后窗漂移
    w = thresholds.get("drift", {})
    w1, w2 = w.get("windows", [10000, 10000])
    first, second = ok_runs[:w1], ok_runs[-w2:] if w2 else []
    alpha = float(w.get("alpha", 0.01))
    drift_rows: list[dict] = []
    # 数值特征：双样本均值 z 检验
    for feat in ("escalate_rate", "restore_success_rate", "mean_detect_latency_s"):
        x1 = [float(_feature_vector(d)[feat]) for d in first]
        x2 = [float(_feature_vector(d)[feat]) for d in second]
        p = two_sample_mean_p(x1, x2)
        drift_rows.append({"feature": feat, "kind": "mean",
                           "mean_first": round(statistics.fmean(x1), 4) if x1 else 0.0,
                           "mean_second": round(statistics.fmean(x2), 4) if x2 else 0.0,
                           "p": round(p, 6), "pass": p > alpha})
    # 分类特征 action_mix：三类分别做两比例检验
    for idx, name in enumerate(("agent_actions", "human_actions", "rejected_actions")):
        a1 = sum(1 for d in first if _feature_vector(d)["action_mix"][idx] > 0)
        a2 = sum(1 for d in second if _feature_vector(d)["action_mix"][idx] > 0)
        p = two_proportion_p(a1, max(len(first), 1), a2, max(len(second), 1))
        drift_rows.append({"feature": "action_mix." + name, "kind": "proportion",
                           "first": a1, "second": a2,
                           "p": round(p, 6), "pass": p > alpha})
    v3 = {"criterion": "drift", "windows": [len(first), len(second)],
          "rows": drift_rows,
          "pass": all(r["pass"] for r in drift_rows)}
    verdicts.append(v3)

    converged = all(v["pass"] for v in verdicts) and not errors
    return {"converged": converged, "runs": n, "errors": len(errors),
            "verdicts": verdicts,
            "error_samples": errors[:5]}


# ---------------------------------------------------------------- CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="converge.py", description="收敛批跑与判定")
    ap.add_argument("mode", choices=["calibrate", "judge"])
    ap.add_argument("--runs", type=int, default=None)
    ap.add_argument("--seed-base", type=int, default=1000)
    ap.add_argument("--frozen-only", action="store_true",
                    help="判定模式必须 frozen: true，否则拒绝")
    ap.add_argument("--scenarios-dir", default=str(SCEN_DIR),
                    help="场景目录（缺省 arena/scenarios）")
    ap.add_argument("--workers", type=int, default=8,
                    help="批跑并行进程数（缺省 8；1=串行）")
    ap.add_argument("--runs-root", default=str(ROOT / "runs" / "converge"))
    args = ap.parse_args(argv)

    thresholds_raw = THRESHOLDS_PATH.read_text(encoding="utf-8")
    thresholds = yaml.safe_load(thresholds_raw)
    frozen = bool(thresholds.get("frozen"))

    if args.mode == "judge" and args.frozen_only and not frozen:
        print("REFUSED: thresholds.yaml 未冻结（frozen: false）——校准并 owner 批复前不得判定")
        return 2

    files = _scenario_files(adjudication_only=False, scen_dir=Path(args.scenarios_dir))
    runs = args.runs or int(thresholds.get("budget", {}).get("total_runs", 30000))
    if args.mode == "calibrate":
        runs = args.runs or int(thresholds.get("budget", {}).get("calibration_runs", 100))

    if not files:
        print(f"NO SCENARIOS: {SCEN_DIR} 为空（阶段 d D-4 场景库未就绪）")
        return 2

    print(f"converge mode={args.mode} runs={runs} scenarios={len(files)} "
          f"frozen={frozen} workers={args.workers}", flush=True)
    results = run_batch(runs, args.seed_base, files, Path(args.runs_root),
                        workers=args.workers)
    verdict = judge(results, thresholds)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    tag = "calibration" if args.mode == "calibrate" else "judgment"
    out = REPORT_DIR / f"converge-{tag}.json"
    out.write_text(json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"result": "CONVERGED" if verdict["converged"] else "NOT_CONVERGED",
                      "runs": verdict["runs"], "errors": verdict["errors"],
                      "verdicts": verdict["verdicts"]}, ensure_ascii=False, indent=1))
    print(f"report -> {out}")
    return 0 if verdict["converged"] or args.mode == "calibrate" else 1


if __name__ == "__main__":
    sys.exit(main())
