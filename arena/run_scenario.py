#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-
"""arena/run_scenario.py · 单场景入口（TASK.md §2.4 D-1）

用法::

    python arena/run_scenario.py --config <scenario.yaml> --seed 42
    python arena/run_scenario.py --config dsl/examples/park-arena-01.yaml --human
    python arena/run_scenario.py --config ... --json            # 机器可读摘要

选项：
  --seed N            覆盖场景 seed（复现/扫描用）
  --human             人机对比模式：agent 默认关闭；场景运行中检出异常会**暂停**，
                      等人工处置（操作与 agent 同款执行器；可手动注入故障）
  --agent-off         仅关闭 agent 不暂停（脚本化人类实验用）
  --runs-root DIR     run 记录根目录（缺省 runs/arena）
  --idle-dt S         空闲步长（仿真秒，时间快速推移的粒度，缺省 60）
  --active-dt S       活跃步长（有异常/临事件时的粒度，缺省 1）
  --json              末尾打印 eval 摘要 JSON

退出码：0=运行完成；1=场景被拒（DSL 校验/注入越界）；2=用法/IO 错误。
--human 交互命令：open|close|ack <target> [原因] | inject <fault_id> | agent on|off |
continue（不处置继续）| quit（终止场景）
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.engine import ArenaEngine, ScenarioRejected, load_scenario  # noqa: E402


def _parse_human_line(arena: ArenaEngine, line: str) -> str | None:
    """解析一条人工命令 → submit_human / 开关 agent。返回 quit 信号或 None。"""
    parts = line.strip().split(maxsplit=2)
    if not parts:
        return None
    cmd = parts[0].lower()
    if cmd in ("quit", "exit", "q"):
        return "quit"
    if cmd == "agent":
        if len(parts) >= 2 and parts[1].lower() in ("on", "off"):
            arena.submit_human({"op": "agent", "value": parts[1].lower()})
            print(f"[human] agent {parts[1].lower()}")
        else:
            print("用法: agent on|off")
        return None
    if cmd == "inject":
        if len(parts) < 2:
            print("用法: inject <fault_id>")
            return None
        arena.submit_human({"op": "inject", "fault_id": parts[1]})
        print(f"[human] 注入 {parts[1]} 已排队")
        return None
    if cmd == "continue":
        return None
    if cmd in ("open", "close", "ack"):
        if len(parts) < 2:
            print(f"用法: {cmd} <target> [原因]")
            return None
        arena.submit_human({"op": cmd, "target": parts[1],
                            "reason": parts[2] if len(parts) > 2 else "人工操作"})
        print(f"[human] {cmd} {parts[1]} 已排队")
        return None
    print(f"未知命令: {cmd}")
    return None


def _run_human_interactive(arena: ArenaEngine) -> None:
    """人机对比交互：读取线程收命令；检出异常时主循环暂停等人工。"""
    resume = threading.Event()
    quit_flag = {"stop": False}

    def reader() -> None:
        try:
            while not quit_flag["stop"]:
                line = input("human> ")
                if line.strip() == "":
                    continue
                sig = _parse_human_line(arena, line)
                if sig == "quit":
                    quit_flag["stop"] = True
                resume.set()   # 有输入即放行（continue 也是合法"不处置"）
        except EOFError:
            quit_flag["stop"] = True
            resume.set()

    th = threading.Thread(target=reader, daemon=True)
    th.start()

    def pause(anoms) -> None:
        print("\n=== 异常检出（agent 已关闭）——等你处置 ===")
        for a in anoms:
            ev = a.evidence or {}
            print(f"  {a.anomaly_id} {a.hint}@{a.target} [{a.severity}] "
                  f"{ev.get('metric')}={ev.get('value')} ({ev.get('basis', '')})")
        print("命令: open|close|ack <target> [原因] | inject <fault_id> | "
              "agent on|off | continue | quit")
        resume.clear()
        resume.wait()
        if quit_flag["stop"]:
            raise KeyboardInterrupt

    arena.pause_hook = pause
    print("人机对比模式：agent 已关闭。异常出现时会暂停等你；"
          "可随时 inject 手动注入故障、agent on 交还给 agent。")
    try:
        arena.run()
    except KeyboardInterrupt:
        print("\n(人工终止，按已发生的动作收口)")
        arena.pause_hook = None   # 收口阶段不再暂停（读线程已停）
        arena.run()
    print(f"人工动作 {len(arena.human_log)} 条：见 meta.json.human_actions")




def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="run_scenario.py",
                                 description="arena 单场景运行（D-1）")
    ap.add_argument("--config", required=True, help="ParkDSL v1.1 场景文件（YAML）")
    ap.add_argument("--seed", type=int, default=None, help="覆盖场景 seed")
    ap.add_argument("--human", action="store_true", help="人机对比模式（agent 关闭 + REPL）")
    ap.add_argument("--agent-off", action="store_true", help="仅关闭 agent（无 REPL）")
    ap.add_argument("--runs-root", default=None, help="run 记录根目录")
    ap.add_argument("--idle-dt", type=float, default=60.0, help="空闲步长（仿真秒）")
    ap.add_argument("--active-dt", type=float, default=1.0, help="活跃步长（仿真秒）")
    ap.add_argument("--run-id", default=None, help="自定义 run ID（批跑去重用）")
    ap.add_argument("--json", action="store_true", help="打印 eval 摘要 JSON")
    args = ap.parse_args(argv)

    try:
        config = load_scenario(args.config)
    except ScenarioRejected as exc:
        print(f"[E-SCENARIO] {exc}", file=sys.stderr)
        return 1

    agent_enabled = None
    if args.human or args.agent_off:
        agent_enabled = False
    try:
        arena = ArenaEngine(config, seed=args.seed, agent_enabled=agent_enabled,
                            run_id=args.run_id, runs_root=args.runs_root,
                            idle_dt=args.idle_dt, active_dt=args.active_dt)
    except ScenarioRejected as exc:
        print("[E-SCENARIO] 场景被拒：", file=sys.stderr)
        for r in exc.reasons:
            print(f"  - {r}", file=sys.stderr)
        return 1

    if args.human:
        _run_human_interactive(arena)
        return 0

    result = arena.run()
    summary = result.to_dict()
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        a, g = summary["anomalies"], summary["gateway"]
        print(f"run {summary['run_id']}: sim_s={summary['sim_s_final']:.0f} "
              f"agent={'on' if summary['agent_enabled'] else 'off'} "
              f"detected={a['detected']} cleared={a['cleared']} "
              f"(agent={a['cleared_by_agent']}/human={a['cleared_by_human']}) "
              f"escalated={a['escalated']} actions={g['actions_total']} "
              f"rejected={g['rejected']} events={summary['events_total']}")
        print(f"  records -> {summary['paths']['run_dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
