#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calc_demand.py · 需量分析与容需切换测算（skill.demand-analysis@0.1.0 的确定性脚本）。

数据源（全部只读权威源）：
- ontology/seed.yaml          PARK-001 台账（合同容量 / 月最大需量 / 日形状×base / 电价时段表）；
- regulations/REG-TECH.yaml   PHYS-DEMAND 判据阈值（>1.00 → P2 预警、>1.05 → P0 越限）。

口径（SKILL.md §数据与口径）：
- 30 天 × 96 点/天 15 分钟序列，逐点 = base_kw × interpolate_shape(shape, hour) × 日因子 × 扰动；
  插值复用 M5 物理层 src/m5_simulation/physics.py interpolate_shape（同约定，含 23↔0 环绕）；
  扰动幅度 0.03 与 M5 MODEL_DEFAULTS.noise_amplitude 同口径；random.Random(seed) 固定种子。
- 全序列等比标定：月最大 15 分钟需量 = 台账 demand_*.peak_kw（不冒充实测，演示口径）。
- 容需两档基本电价为显式参数（演示默认 48 / 32 元/kW·月，标注「演示参数，按当地目录电价替换」）；
  临界点 MD* = 合同容量 × 容量电价 ÷ 需量电价。

用法（任何 cwd）：
    python skills/demand-analysis/calc_demand.py            # 叙事文本输出
    python skills/demand-analysis/calc_demand.py --json     # 结果对象 JSON（确定性重放口径）
退出码：0 = 正常出数；2 = 参数非法（ValueError，中文原因，不粉饰）。
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
_SRC = str(REPO / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import yaml  # noqa: E402

from m5_simulation.physics import interpolate_shape  # noqa: E402

SKILL_ID = "skill.demand-analysis"
SKILL_VERSION = "0.1.0"
SEED_FILE = "ontology/seed.yaml"
REG_TECH_FILE = "regulations/REG-TECH.yaml"
DEMAND_RULE_ID = "PHYS-DEMAND"
PARAM_NOTE = "演示参数，按当地目录电价替换"

#: 演示默认参数（SKILL.yaml parameters 同源；调用方可显式覆盖）
DEFAULT_PARAMS: dict[str, Any] = {
    "demand_price_yuan_per_kw_month": 48.0,
    "capacity_price_yuan_per_kw_month": 32.0,
    "seed": 20260901,
    "days": 30,
    "interval_min": 15,
    "day_factor_range": (0.86, 1.00),
    "jitter_amplitude": 0.03,
}


# ---------------------------------------------------------------------------
# 权威数据装载
# ---------------------------------------------------------------------------
def load_park(repo: Path = REPO) -> dict:
    """seed.yaml → 园区台账字段（demand_* / load_curve_* 按前缀发现，不硬编码月份）。"""
    data = yaml.safe_load((repo / SEED_FILE).read_text(encoding="utf-8")) or {}
    park = data.get("park") or {}
    demand_keys = [k for k in (data or {}) if k.startswith("demand_")]
    curve_keys = [k for k in (data or {}) if k.startswith("load_curve_")]
    if not demand_keys:
        raise ValueError(f"{SEED_FILE}: 缺 demand_* 台账需量字段")
    if not curve_keys:
        raise ValueError(f"{SEED_FILE}: 缺 load_curve_* 日形状字段")
    demand = data[demand_keys[0]] or {}
    curve = data[curve_keys[0]] or {}
    schedule = data.get("price_schedule") or {}
    shape = curve.get("shape") or []
    if len(shape) != 24 or not shape:
        raise ValueError(f"{SEED_FILE}: load_curve shape 必须为 24 点小时形状")
    return {
        "id": park.get("id"),
        "tariff": park.get("tariff"),
        "contract_capacity_kw": float(park.get("contract_capacity_kw") or 0),
        "demand_month": str(demand.get("month") or demand_keys[0].removeprefix("demand_")),
        "ledger_peak_kw": float(demand.get("peak_kw") or 0),
        "base_kw": float(curve.get("base_kw") or 0),
        "shape": [float(v) for v in shape],
        "periods": [dict(p) for p in (schedule.get("periods") or [])],
    }


def load_demand_thresholds(repo: Path = REPO) -> dict:
    """REG-TECH PHYS-DEMAND 阈值（判据唯一来源；不在代码里另设口径）。"""
    data = yaml.safe_load((repo / REG_TECH_FILE).read_text(encoding="utf-8")) or {}
    rule = next((r for r in (data.get("rules") or []) if r.get("id") == DEMAND_RULE_ID), None)
    if rule is None:
        raise ValueError(f"{REG_TECH_FILE}: 缺规则 {DEMAND_RULE_ID}")
    warn = breach = None
    for t in rule.get("thresholds") or []:
        if t.get("op") == ">" and t.get("level") == "P2":
            warn = float(t.get("value"))
        elif t.get("op") == ">" and t.get("level") == "P0":
            breach = float(t.get("value"))
    if warn is None or breach is None:
        raise ValueError(f"{REG_TECH_FILE}: {DEMAND_RULE_ID} 阈值不全（需 P2/P0 两档）")
    return {"warn_over": warn, "breach_over": breach, "title": rule.get("title")}


# ---------------------------------------------------------------------------
# 序列合成与统计
# ---------------------------------------------------------------------------
def _month_start(month: str) -> date:
    return datetime.strptime(month, "%Y-%m").date()


def synthesize_series(park: dict, params: dict) -> list[dict]:
    """30 天 × 96 点 15 分钟序列（确定性：单 Random 按固定顺序消耗）。

    逐点 = base_kw × interpolate_shape(shape, hour) × 日因子 × (1 ± jitter)；
    全序列等比标定月峰 = 台账 ledger_peak_kw，标定点直接钉住台账值（消浮点尾差）。
    """
    days = int(params["days"])
    interval = int(params["interval_min"])
    if interval <= 0 or 24 * 60 % interval != 0:
        raise ValueError(f"interval_min 必须整除 24h（15 分钟口径），实际 {interval}")
    per_day = 24 * 60 // interval
    lo, hi = params["day_factor_range"]
    if not (0.0 < lo <= hi <= 1.0):
        raise ValueError(f"day_factor_range 需满足 0<低≤高≤1，实际 [{lo}, {hi}]")
    jitter = float(params["jitter_amplitude"])
    if not (0.0 <= jitter < 1.0):
        raise ValueError(f"jitter_amplitude 需在 [0,1)，实际 {jitter}")

    rng = random.Random(int(params["seed"]))
    start = _month_start(park["demand_month"])
    raw: list[float] = []
    points: list[dict] = []
    for d in range(days):
        factor = rng.uniform(lo, hi)
        day = start + timedelta(days=d)
        for slot in range(per_day):
            hour = slot * interval / 60.0
            noise = 1.0 + rng.uniform(-jitter, jitter)
            kw = park["base_kw"] * interpolate_shape(park["shape"], hour) * factor * noise
            raw.append(kw)
            points.append({
                "ts": f"{day.isoformat()}T{int(hour):02d}:{int(round(hour % 1 * 60)):02d}:00Z",
                "kw": kw,
            })
    peak = max(raw)
    scale = park["ledger_peak_kw"] / peak
    argmax = raw.index(peak)
    for i, p in enumerate(points):
        p["kw"] = round(p["kw"] * scale, 3)
    points[argmax]["kw"] = float(park["ledger_peak_kw"])  # 标定锚点：月峰=台账值
    return points


def _period_of(periods: list[dict], hhmm: str) -> str | None:
    for p in periods:
        if str(p.get("start")) <= hhmm < str(p.get("end")):
            return str(p.get("type"))
    return None


def compute_stats(park: dict, points: list[dict], params: dict) -> dict:
    """月峰/时刻/Top5 高峰日/峰段电量占比/负荷率（定义见 SKILL.md §统计定义）。"""
    interval_h = int(params["interval_min"]) / 60.0
    peak_point = max(points, key=lambda p: p["kw"])
    hhmm = peak_point["ts"][11:16]
    # 峰段窗口（电价时段表 type=PEAK）：窗口列表 + 峰段占比分母为全月总电量
    peak_windows = [f"{p['start']}-{p['end']}" for p in park["periods"] if p.get("type") == "PEAK"]
    energy_by_type: dict[str, float] = {"PEAK": 0.0, "FLAT": 0.0, "VALLEY": 0.0}
    total_energy = 0.0
    for p in points:
        etype = _period_of(park["periods"], p["ts"][11:16]) or "FLAT"
        kwh = p["kw"] * interval_h
        energy_by_type[etype] = energy_by_type.get(etype, 0.0) + kwh
        total_energy += kwh
    # Top5 高峰日：日内最大 15 分钟需量降序
    by_day: dict[str, dict] = {}
    for p in points:
        d = p["ts"][:10]
        cur = by_day.get(d)
        if cur is None or p["kw"] > cur["peak_kw"]:
            by_day[d] = {"date": d, "peak_kw": p["kw"], "peak_at": p["ts"]}
    top5 = sorted(by_day.values(), key=lambda x: (-x["peak_kw"], x["date"]))[:5]
    mean_kw = total_energy / (len(points) * interval_h)
    month_peak = max(p["kw"] for p in points)
    return {
        "points": len(points),
        "month_peak_kw": round(month_peak, 3),
        "month_peak_at": peak_point["ts"],
        "month_peak_period": _period_of(park["periods"], hhmm) or "未知",
        "top5_days": [
            {"date": t["date"], "peak_kw": round(t["peak_kw"], 3),
             "peak_at": t["peak_at"][11:16]} for t in top5],
        "energy_kwh": round(total_energy, 1),
        "mean_kw": round(mean_kw, 2),
        "load_factor": round(mean_kw / month_peak, 4),
        "period_energy_ratio": {
            k: round(v / total_energy, 4) for k, v in sorted(energy_by_type.items())},
        "peak_windows": peak_windows,
        "peak_energy_ratio": round(energy_by_type.get("PEAK", 0.0) / total_energy, 4),
    }


# ---------------------------------------------------------------------------
# 容需切换测算 + 判据联动
# ---------------------------------------------------------------------------
def compute_billing(month_peak_kw: float, contract_capacity_kw: float, params: dict) -> dict:
    """两档基本电费对比 + 临界点（SPEC-M8-02；电价为显式参数，演示默认 48/32）。"""
    p_dem = float(params["demand_price_yuan_per_kw_month"])
    p_cap = float(params["capacity_price_yuan_per_kw_month"])
    if p_dem <= 0:
        raise ValueError(f"demand_price_yuan_per_kw_month 必须为正数（临界点公式分母），实际 {p_dem}")
    if p_cap < 0:
        raise ValueError(f"capacity_price_yuan_per_kw_month 不得为负，实际 {p_cap}")
    demand_billing = month_peak_kw * p_dem
    capacity_billing = contract_capacity_kw * p_cap
    cheaper = "demand" if demand_billing < capacity_billing else "capacity"
    saving = abs(demand_billing - capacity_billing)
    threshold = contract_capacity_kw * p_cap / p_dem
    return {
        "demand_price_yuan_per_kw_month": p_dem,
        "capacity_price_yuan_per_kw_month": p_cap,
        "param_note": PARAM_NOTE,
        "demand_billing_yuan": round(demand_billing, 2),
        "capacity_billing_yuan": round(capacity_billing, 2),
        "cheaper": cheaper,
        "saving_yuan_per_month": round(saving, 2),
        "saving_yuan_per_year": round(saving * 12, 2),
        "threshold_kw": round(threshold, 2),
        "threshold_note": (f"月最大需量低于 {threshold:.2f} kW 时按需量计费划算，"
                           f"高于则按容量计费划算"),
    }


def judge_demand(kw: float, contract_capacity_kw: float, thresholds: dict) -> dict:
    """PHYS-DEMAND 分级（阈值出自规程库；结论必须引用规则 ID）。"""
    ratio = kw / contract_capacity_kw
    warn_over = float(thresholds["warn_over"])
    breach_over = float(thresholds["breach_over"])
    if ratio > breach_over:
        level, label = "P0", "需量越限"
    elif ratio > warn_over:
        level, label = "P2", "需量预警"
    else:
        level, label = "NORMAL", "正常（未触预警线）"
    return {
        "kw": round(float(kw), 3),
        "demand_ratio": round(ratio, 4),
        "level": level,
        "label": label,
        "rule_ids": [DEMAND_RULE_ID],
        "warn_kw": round(warn_over * contract_capacity_kw, 3),
        "breach_kw": round(breach_over * contract_capacity_kw, 3),
    }


def compute_criteria(month_peak_kw: float, park: dict, thresholds: dict) -> dict:
    verdict = judge_demand(month_peak_kw, park["contract_capacity_kw"], thresholds)
    margin = verdict["warn_kw"] - month_peak_kw
    conclusion = (f"demand_ratio = {verdict['demand_ratio']:.2f}（{month_peak_kw:.0f}/"
                  f"{park['contract_capacity_kw']:.0f}）→ {verdict['label']}；"
                  f"预警线 {verdict['warn_kw']:.0f} kW（ratio>{thresholds['warn_over']}，P2）、"
                  f"越限线 {verdict['breach_kw']:.0f} kW（ratio>{thresholds['breach_over']}，P0）"
                  f"——判据 {DEMAND_RULE_ID}《{thresholds['title']}》"
                  f"（{REG_TECH_FILE}），阈值在规程库不在代码里")
    return {
        "rule_ids": [DEMAND_RULE_ID],
        "source": REG_TECH_FILE,
        "demand_ratio": verdict["demand_ratio"],
        "warn_over": float(thresholds["warn_over"]),
        "breach_over": float(thresholds["breach_over"]),
        "warn_kw": verdict["warn_kw"],
        "breach_kw": verdict["breach_kw"],
        "level": verdict["level"],
        "margin_to_warn_kw": round(margin, 3),
        "conclusion": conclusion,
    }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def run_analysis(params: dict | None = None, repo: Path = REPO) -> dict:
    """完整分析（确定性：同 params 同输出；结构见 SKILL.md §输出结构）。"""
    merged = dict(DEFAULT_PARAMS)
    merged["day_factor_range"] = tuple(DEFAULT_PARAMS["day_factor_range"])
    for key, value in (params or {}).items():
        merged[key] = tuple(value) if key == "day_factor_range" and isinstance(value, list) else value
    park = load_park(repo)
    if park["contract_capacity_kw"] <= 0:
        raise ValueError(f"{SEED_FILE}: park.contract_capacity_kw 必须为正")
    if park["ledger_peak_kw"] <= 0:
        raise ValueError(f"{SEED_FILE}: demand_*.peak_kw 必须为正")
    if int(merged["days"]) <= 0:
        raise ValueError(f"days 必须为正整数，实际 {merged['days']}")
    thresholds = load_demand_thresholds(repo)
    points = synthesize_series(park, merged)
    stats = compute_stats(park, points, merged)
    billing = compute_billing(stats["month_peak_kw"], park["contract_capacity_kw"], merged)
    criteria = compute_criteria(stats["month_peak_kw"], park, thresholds)
    cheaper_cn = "按需量计费" if billing["cheaper"] == "demand" else "按容量计费"
    recommendation = (
        f"当前月最大需量 {stats['month_peak_kw']:.0f} kW（{billing['threshold_kw']:.2f} kW 临界点"
        f"{'之上' if stats['month_peak_kw'] > billing['threshold_kw'] else '之下'}）：{cheaper_cn}更省，"
        f"月省 {billing['saving_yuan_per_month']:.0f} 元、年省 {billing['saving_yuan_per_year']:.0f} 元；"
        f"需量侧同时距 {criteria['warn_kw']:.0f} kW 预警线余量 {criteria['margin_to_warn_kw']:.0f} kW"
        f"（{DEMAND_RULE_ID}）。月最大需量落在临界点哪一侧是此消彼长的：经需量管控（错峰/储能顶峰）"
        f"使其越过分界，档位建议即反转，宜按月复盘滚动复核；"
        f"两档电价为{PARAM_NOTE}，换档须经业主确认后向供电公司申请。")
    return {
        "skill": f"{SKILL_ID}@{SKILL_VERSION}",
        "meta": {
            "script": "skills/demand-analysis/calc_demand.py",
            "seed": int(merged["seed"]),
            "interval_min": int(merged["interval_min"]),
            "days": int(merged["days"]),
        },
        "park": {
            "id": park["id"],
            "tariff": park["tariff"],
            "contract_capacity_kw": park["contract_capacity_kw"],
            "demand_month": park["demand_month"],
            "ledger_peak_kw": park["ledger_peak_kw"],
            "base_kw": park["base_kw"],
            "synthesis": {
                "method": "M5 interpolate_shape 15min 插值 × 日因子 × 固定 seed 扰动（演示口径，非实测历史）",
                "day_factor_range": [merged["day_factor_range"][0], merged["day_factor_range"][1]],
                "jitter_amplitude": float(merged["jitter_amplitude"]),
                "calibration": "全序列等比标定：月最大 15min 需量 = 台账 demand_*.peak_kw",
                "calibration_peak_kw": park["ledger_peak_kw"],
            },
        },
        "series_stats": stats,
        "billing": billing,
        "criteria": criteria,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# 叙事文本（CLI 演示输出）
# ---------------------------------------------------------------------------
def render_text(result: dict) -> str:
    park, stats, bill, crit = result["park"], result["series_stats"], result["billing"], result["criteria"]
    lines: list[str] = []
    lines.append(f"◆ 需量分析 · {result['skill']}（园区 {park['id']} · 电价表 {park['tariff']} · "
                 f"{park['demand_month']}）")
    lines.append(f"  数据源：ontology/seed.yaml（合同容量 {park['contract_capacity_kw']:.0f} kW · "
                 f"台账月峰 {park['ledger_peak_kw']:.0f} kW · base {park['base_kw']:.0f} kW）")
    lines.append(f"  合成口径：{park['synthesis']['method']}，seed={result['meta']['seed']}，"
                 f"标定月峰={park['synthesis']['calibration_peak_kw']:.0f} kW")
    lines.append("")
    lines.append(f"◆ 需量规律（{stats['points']} 个 15min 点）")
    lines.append(f"  月最大需量 {stats['month_peak_kw']:.1f} kW @ {stats['month_peak_at']}"
                 f"（所在时段 {stats['month_peak_period']}）")
    lines.append(f"  Top5 高峰日（按日内最大 15min 需量）：")
    for t in stats["top5_days"]:
        lines.append(f"    {t['date']}  {t['peak_kw']:7.1f} kW  @ {t['peak_at']}")
    lines.append(f"  峰段电量占比 {stats['peak_energy_ratio']:.1%}（窗口 {'、'.join(stats['peak_windows'])}）"
                 f"  平 {stats['period_energy_ratio'].get('FLAT', 0):.1%}"
                 f"  谷 {stats['period_energy_ratio'].get('VALLEY', 0):.1%}")
    lines.append(f"  负荷率 {stats['load_factor']:.1%}（平均 {stats['mean_kw']:.0f} kW / 月峰 "
                 f"{stats['month_peak_kw']:.0f} kW）· 全月电量 {stats['energy_kwh']:,.0f} kWh")
    lines.append("")
    lines.append("◆ 容需切换测算（基本电费两档对比）")
    lines.append(f"  {'计费方式':<6}{'计费基数':>10}{'单价(元/kW·月)':>16}{'月基本电费(元)':>16}")
    lines.append(f"  {'按需量':<6}{stats['month_peak_kw']:>10.0f}{bill['demand_price_yuan_per_kw_month']:>16.0f}"
                 f"{bill['demand_billing_yuan']:>16,.0f}")
    lines.append(f"  {'按容量':<6}{park['contract_capacity_kw']:>10.0f}{bill['capacity_price_yuan_per_kw_month']:>16.0f}"
                 f"{bill['capacity_billing_yuan']:>16,.0f}")
    lines.append(f"  临界点 {bill['threshold_kw']:.2f} kW ="
                 f"{park['contract_capacity_kw']:.0f}×{bill['capacity_price_yuan_per_kw_month']:.0f}"
                 f"÷{bill['demand_price_yuan_per_kw_month']:.0f}（合同容量×容量电价÷需量电价）——"
                 f"{bill['threshold_note']}")
    lines.append(f"  当前更省：{'按需量计费' if bill['cheaper'] == 'demand' else '按容量计费'}"
                 f"（月省 {bill['saving_yuan_per_month']:,.0f} 元 / 年省 {bill['saving_yuan_per_year']:,.0f} 元）")
    lines.append(f"  电价参数：{bill['param_note']}")
    lines.append("")
    lines.append(f"◆ 判据联动（{', '.join(crit['rule_ids'])} · {crit['source']}）")
    lines.append(f"  {crit['conclusion']}")
    lines.append("")
    lines.append("◆ 建议")
    lines.append(f"  {result['recommendation']}")
    return "\n".join(lines)


def main(argv: list | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="skills/demand-analysis/calc_demand.py",
                                     description="需量分析与容需切换测算（确定性，固定 seed）")
    parser.add_argument("--json", action="store_true", help="输出结果对象 JSON（重放/评测口径）")
    parser.add_argument("--demand-price", type=float, default=DEFAULT_PARAMS["demand_price_yuan_per_kw_month"],
                        help="需量电价 元/kW·月（演示参数，按当地目录电价替换）")
    parser.add_argument("--capacity-price", type=float, default=DEFAULT_PARAMS["capacity_price_yuan_per_kw_month"],
                        help="容量电价 元/kW·月（演示参数，按当地目录电价替换）")
    parser.add_argument("--seed", type=int, default=DEFAULT_PARAMS["seed"], help="合成随机种子")
    args = parser.parse_args(argv)
    try:
        result = run_analysis({
            "demand_price_yuan_per_kw_month": args.demand_price,
            "capacity_price_yuan_per_kw_month": args.capacity_price,
            "seed": args.seed,
        })
    except ValueError as exc:
        print(f"[参数非法] {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
          if args.json else render_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
