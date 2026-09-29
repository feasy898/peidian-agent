# -*- coding: utf-8 -*-
"""tests.fixtures.m5_eval_plugin · M5 套件补充执行器（tests 侧插件，EVAL-SCHEMA.md §4 协议）。

变异驱动补强（.mutations/results-m5.json survivor ``m5-business-nohub-wall-fallback``）：
``m5_simulation.clock.clock`` 对 BUSINESS/SIM_LOGICAL 无 ClockHub 调用必须抛
``ValueError``（业务时钟不落回墙钟——01 v2 §8/SPEC-M5-02 时钟纪律；红线 6 的兜底面）。
m3_action.eval_plugin 与 m5_simulation.eval_plugin 均未直接断言该边界，本插件补齐：

- ``m5.clock_discipline``（SPEC-M5-02）：无 hub 的 BUSINESS/SIM_LOGICAL 调用一律拒绝
  （异常类型断言 + 可选 error_contains）；带 hub 的业务时钟正常读数（正对照，
  防止"一律拒绝"式退化实现假阳性）；WALL/MONOTONIC 无 hub 合法（只读真实时钟审计面）。
  全部探针模式/时刻/期望来自 case.params/expect，零案例特判。
"""
from __future__ import annotations

__all__ = ["EXECUTORS"]


def exec_clock_discipline(case: dict, ctx) -> dict:
    """时钟纪律探针（SPEC-M5-02）：params.probes 声明式执行，expect.error_contains 可选。"""
    from m5_simulation.clock import ClockHub, clock, parse_utc

    params = case.get("params") or {}
    expect = case.get("expect") or {}
    probes = list(params.get("probes") or [])
    if not probes:
        return {"passed": False, "detail": "params.probes 必填（探针清单）", "metrics": {}}

    problems: list = []
    rejected: list = []
    readable: list = []
    for index, probe in enumerate(probes):
        mode = str(probe.get("mode", ""))
        want = str(probe.get("expect", "reject"))  # reject | reading
        clock_start = probe.get("clock_start")
        service = ClockHub(parse_utc(clock_start)) if (probe.get("with_hub") and clock_start) else None
        try:
            reading = clock(mode, service)
            error = None
        except Exception as exc:  # noqa: BLE001 - 探针按异常类型/消息判定
            reading, error = None, exc

        if want == "reject":
            if error is None:
                problems.append(
                    f"probes[{index}] {mode} 无 hub 调用未拒绝（返回 {reading.to_dict()}）"
                    "——业务时钟不得落回墙钟兜底"
                )
                continue
            contains = expect.get("error_contains")
            if contains and contains not in str(error):
                problems.append(f"probes[{index}] {mode} 拒绝消息不含 {contains!r}: {error}")
            rejected.append(mode)
        elif want == "reading":
            if error is not None:
                problems.append(f"probes[{index}] {mode}（with_hub={probe.get('with_hub')}）"
                                f"读数失败: {type(error).__name__}: {error}")
                continue
            if str(reading.mode) != mode:
                problems.append(f"probes[{index}] 读数 mode {reading.mode!r} != 请求 {mode!r}")
            readable.append(mode)
        else:
            problems.append(f"probes[{index}] 未知 expect: {want!r}（reject|reading）")

    metrics = {"probes": len(probes), "rejected": rejected, "readable": readable}
    if problems:
        return {"passed": False, "detail": "；".join(problems), "metrics": metrics}
    return {"passed": True,
            "detail": f"时钟纪律探针全过：无 hub 业务时钟 {rejected} 一律拒绝"
                      f"（禁墙钟兜底），带 hub {readable} 正常读数",
            "metrics": metrics}


EXECUTORS = {
    "m5.clock_discipline": exec_clock_discipline,
}
