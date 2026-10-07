#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-
"""arena/tests/run_tests.py · 练习场回归测试（TASK.md §2.4 D-1..D-3 断言）。

覆盖：
  A. D-1 练习场可跑：CLI 跑样例 exit 0，五件记录齐全（events/states/actions/meta/eval）
  B. D-2 故障注入四步留痕：planned→injected→detected→cleared 链路完整
  C. D-3 时间推移自然变化：业务日历事件带 business_at、仿真钟到点、倍速语义在案
  D. 确定性：同 seed 双跑事件流逐事件一致（剥墙钟 ts）
  E. 人机对比：agent 关闭→异常照检+交人工；人工 ack/注入走同款执行器
  F. 故障库：11 条目装配 + 判据覆盖 + compat 零信任
  G. 零信任：未知 kind / 幽灵注入在 DSL 层被拒（E-FAULT/E-SCEN）
  H. eval 摘要字段完整（收敛统计所需口径）
  I. llm_agent prompt 遥测序列化：全量遥测进 prompt / target 不匹配兜底 /
     不可序列化值退化 str / 空遥测如实声明（2026-10-05 首调改进项回归）

退出码: 0=全过  1=有失败。用法: python arena/tests/run_tests.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from arena.engine import ArenaEngine, ScenarioRejected, load_scenario  # noqa: E402
from arena.faultlib import FaultLibError, load_fault_library  # noqa: E402

EXAMPLE = ROOT / "dsl" / "examples" / "park-arena-01.yaml"
VALIDATE = ROOT / "dsl" / "validate.py"
PY = sys.executable

CASES: list[tuple[str, bool]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    CASES.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  —— {detail}" if detail and not ok else ""))


def trimmed_config(path: Path, duration_s: int = 108000) -> dict:
    """样例的紧凑版（保留全部 faults/calendar，缩短时长）——测试提速用。"""
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["scenario"]["duration_sim_s"] = duration_s
    cfg["scenario"]["clock_speed"] = 600
    cfg["scenario"]["injections"] = [
        {"fault": "F-PD-01", "at_sim_s": 0},
        {"fault": "F-HARM-01", "at_sim_s": 3600},
    ]
    return cfg


def events_of(run_dir: Path) -> list[dict]:
    p = run_dir / "events.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        print("== A. D-1 可跑：CLI + 五件记录 ==")
        rundir = root / "cli"
        r = subprocess.run(
            [PY, str(ROOT / "arena" / "run_scenario.py"), "--config", str(EXAMPLE),
             "--seed", "7", "--runs-root", str(rundir)],
            capture_output=True, text=True, timeout=1500)
        rc_ok = r.returncode == 0
        record("cli exit 0", rc_ok, (r.stdout + r.stderr).strip()[:300])
        run_dir = rundir / "PARK-202-s7"
        files_ok = all((run_dir / f).exists() for f in
                       ("events.jsonl", "states.json", "actions.json",
                        "meta.json", "eval.json", "scenario.yaml"))
        record("五件记录齐全", files_ok, str(sorted(p.name for p in run_dir.glob('*'))))
        if files_ok:
            ev = events_of(run_dir)
            kinds = {e["type"] for e in ev}
            record("run 记录含注入/日历/动作面",
                   {"fault.planned", "fault.injected", "ops.patrol"} <= kinds,
                   str(sorted(kinds))[:200])

        print("== B. D-2 四步留痕 ==")
        cfg = trimmed_config(EXAMPLE)
        ae = ArenaEngine(cfg, seed=42, runs_root=root / "b")
        res = ae.run()
        ev = events_of(ae.run_dir)
        seq_types = [e["type"] for e in ev]
        for step in ("fault.planned", "fault.injected", "fault.detected"):
            record(f"四步留痕·{step}", step in seq_types)
        planned = {e["payload"]["fault_id"] for e in ev if e["type"] == "fault.planned"}
        detected = {e["payload"]["hint"] for e in ev if e["type"] == "fault.detected"}
        record("两条注入都有计划且均检出",
               planned == {"F-PD-01", "F-HARM-01"} and
               detected == {"PARTIAL_DISCHARGE", "HARMONIC"},
               f"planned={planned} detected={detected}")
        repaired = [e for e in ev if e["type"] == "ops.repair_completed"]
        record("状态类故障消缺闭环（repair_scheduled→completed）",
               len(repaired) >= 2, f"completed={len(repaired)}")

        print("== C. D-3 时间推移自然变化 ==")
        cal = [e for e in ev if str(e["type"]).startswith("ops.")
               and (e["payload"] or {}).get("source") == "arena.calendar"]
        record("业务日历事件成链（交接班/巡检/报告）",
               {"ops.shift_handover", "ops.patrol", "ops.report"} <= {e["type"] for e in cal})
        biz_ok = bool(cal) and all("business_at" in e["payload"] for e in cal)
        record("日历事件带业务时间戳", biz_ok)
        record("仿真钟推进到场景时长",
               abs(res.sim_s_final - float(cfg["scenario"]["duration_sim_s"])) < 1.0,
               f"final={res.sim_s_final}")
        meta = json.loads((ae.run_dir / "meta.json").read_text(encoding="utf-8"))
        record("倍速与时钟起点在案",
               meta["idle_dt"] > 0 and meta["clock_start"].endswith("Z"))

        print("== D. 确定性（同 seed 双跑）==")
        ae2 = ArenaEngine(trimmed_config(EXAMPLE), seed=42, runs_root=root / "d")
        ae2.run()
        strip = lambda evts: [{k: v for k, v in e.items() if k != "ts"} for e in evts]
        e1, e2 = strip(events_of(ae.run_dir)), strip(events_of(ae2.run_dir))
        record("同 seed 双跑事件流逐事件一致", e1 == e2,
               f"len {len(e1)} vs {len(e2)}")

        print("== E. 人机对比 ==")
        cfg_h = trimmed_config(EXAMPLE)
        ah = ArenaEngine(cfg_h, seed=42, agent_enabled=False, runs_root=root / "e")
        res_h = ah.run()
        evh = events_of(ah.run_dir)
        passed = [e for e in evh if e["type"] == "control.passed"]
        agent_steps = [e for e in evh if e["channel"] == "agent"]
        record("agent 关闭：异常照检且交人工（control.passed），零 agent 步骤",
               len(passed) >= 2 and not agent_steps,
               f"passed={len(passed)} agent_steps={len(agent_steps)}")
        # 人工动作：ack + 手动注入（同款执行器）。F-TEMP-01 不在本场景注入计划内，
        # 用于验证手动注入路径；重复注入同型故障会被引擎零信任拒绝（另有用例）。
        target = None
        for a in ah.engine.detector.active.values():
            target = a.anomaly_id
            break
        act = None
        if target:
            act = ah.human_action("ack", target, "人工确认派工")
        inj = ah.manual_inject("F-TEMP-01")
        record("人工 ack 与手动注入走同款执行器",
               bool(act and act.get("ok")) and inj.get("ok") is True,
               f"ack_ok={bool(act and act.get('ok'))} inject={inj}")
        dup = ah.manual_inject("F-HARM-01")
        record("重复注入同型故障被零信任拒绝",
               dup.get("ok") is False and dup.get("rejected") is True, str(dup)[:160])
        ah.submit_human({"op": "agent", "value": "on"})
        record("submit_human 队列可交还 agent", ah._human_queue and
               ah._human_queue[0][1]["op"] == "agent")

        print("== F. 故障库装配 ==")
        lib = load_fault_library()
        record("11 条目 + 11 判据装配",
               len(lib.entries) == 11 and len(lib.criteria) == 11,
               f"entries={len(lib.entries)} criteria={len(lib.criteria)}")
        det = ae.engine.detector
        record("库判据进入检测器（如 tev_db>20 持续600s）",
               det.criteria.get("tev_db") is not None
               and det.criteria["tev_db"].threshold == 20.0
               and det.criteria["tev_db"].duration_s == 600.0)
        record("每设备配置判据在案（DSL faults 节→SG-A01 tev_db）",
               ("SG-A01", "tev_db") in det.target_criteria)

        print("== G. 零信任 ==")
        bad_kind = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
        bad_kind["faults"][0]["kind"] = "dragon_fire"
        p = root / "bad-kind.yaml"
        p.write_text(yaml.safe_dump(bad_kind, allow_unicode=True), encoding="utf-8")
        rv = subprocess.run([PY, str(VALIDATE), "validate", str(p)],
                            capture_output=True, text=True)
        record("未知 kind → E-FAULT 拒绝", rv.returncode == 1 and "E-FAULT" in rv.stdout,
               rv.stdout.strip()[:160])
        try:
            ArenaEngine(bad_kind, seed=1, runs_root=root / "g")
            rej = False
        except ScenarioRejected:
            rej = True
        record("引擎层同样拒绝坏场景", rej)

        print("== H. eval 摘要口径 ==")
        d = res.to_dict()
        need = ("run_id", "park_id", "seed", "agent_enabled", "sim_s_final",
                "injections", "anomalies", "gateway", "latency", "events_total")
        record("eval.json 字段齐备（收敛统计口径）",
               all(k in d for k in need) and
               {"detected", "cleared", "escalated"} <= set(d["anomalies"]) and
               {"actions_total", "rejected"} <= set(d["gateway"]))
        eval_file = json.loads((ae.run_dir / "eval.json").read_text(encoding="utf-8"))
        record("落盘 eval 与返回一致", eval_file == json.loads(json.dumps(d)))

    # I. llm_agent prompt 遥测序列化（2026-10-05 首调"未提供遥测数据"改进项回归）
    # 全部为确定性 prompt 侧断言（不发网络请求；真调证据另见 evidence/ 真调日志）。
    print("== I. llm_agent prompt 遥测序列化 ==")
    from arena.llm_agent import LLMDiagnosisAgent

    agent = LLMDiagnosisAgent(api_key="unit-test-key")  # 仅构造，不发起调用
    telem = {"SG-A01": {"tev_db": 20.51, "state": "CLOSED"},
             "BUS-A1": {"v_pu": 1.0}, "TX-A01": {"load_rate": 0.6}}
    # I-1 target 命中：目标元件带标注且全量元件都在
    p_hit = agent._build_prompt({"hint": "PARTIAL_DISCHARGE", "target": "SG-A01",
                                 "severity": "P2", "evidence": {"metric": "tev_db"}},
                                telem, None, None)
    record("I-1 遥测全量进 prompt（目标命中）",
           "【目标元件】" in p_hit and all(k in p_hit for k in telem)
           and "20.51" in p_hit and "共 3 元件" in p_hit)
    # I-2 target 对不上任何元件（旧版根因：遥测段为空）→ 现仍全量进 prompt
    p_miss = agent._build_prompt({"hint": "HARMONIC", "target": "TX-99",
                                  "severity": "P2", "evidence": {}},
                                 telem, None, None)
    record("I-2 target 不匹配仍全量进 prompt（旧版此处为空）",
           all(k in p_miss for k in telem) and "共 3 元件" in p_miss)
    # I-3 不可 JSON 序列化的值 → default=str 兜底，不炸不丢
    p_raw = agent._build_prompt({"hint": "HARMONIC", "target": "BUS-A1",
                                 "severity": "P2", "evidence": {"obj": object()}},
                                {"BUS-A1": {"thdu_pct": 6.8, "tags": {"odd"}}},
                                None, None)
    record("I-3 不可序列化值兜底 str 不炸不丢",
           "thdu_pct" in p_raw and "odd" in p_raw)
    # I-4 空遥测：如实声明并禁止编造（不再是无标题空段）
    p_empty = agent._build_prompt({"hint": "HARMONIC", "target": "BUS-A1",
                                   "severity": "P2", "evidence": {}},
                                  {}, None, None)
    record("I-4 空遥测如实声明", "本拍无遥测样本" in p_empty)

    failed = [n for n, o in CASES if not o]
    print(f"\nTOTAL cases={len(CASES)} failed={len(failed)}")
    for n in failed:
        print(f"  FAILED: {n}")
    print("RESULT:", "PASS" if not failed else "FAIL")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
