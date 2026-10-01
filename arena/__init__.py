# -*- coding: utf-8 -*-
"""peidian-agent · arena —— 园区配电模拟练习场（阶段 d 核心交付）。

定位见 TASK.md §2.4：全替身仿真——被测 agent 的每个动作落在模拟世界内；
不出现任何真实电力系统接口；被测的是决策行为，不是模型。

模块规划（随阶段 d 迭代落地）：
    engine.py        编排：DSL 场景 → SimEnv（时钟倍速）→ fault 注入 → agent 内核 → recorder → eval
    run_scenario.py  单场景入口：python arena/run_scenario.py --config <scenario> --seed 42
    converge.py      批跑统计：红线违规率 3/N 置信上界、收益指标、前后窗漂移判据
    gen_scenario.py  LLM 规则化场景生成：规则约束 → 生成 → 零信任 DSL 校验 → 干跑 → 入库
    thresholds.yaml  收敛判据（判定前冻结，判定后不可改）
    scenarios/       场景库（每个标注来源：论文案例/事故复盘/规程）
    faults/          论文故障库（机理/判据阈值/演化链/注入参数/来源）
    reports/         收敛报告与证据
"""

__version__ = "0.1.0"
