# arena/ · 园区配电模拟练习场（阶段 d 核心交付）

> 任务卡见 [../TASK.md](../TASK.md) §2.4（D-1~D-7 目标态契约）。本目录当前为骨架，
> 各件按阶段 d 计划逐步落地并在此登记。

## 目标态入口（TASK.md 裁决口径）

```bash
python arena/run_scenario.py --config <scenario> --seed 42   # 单场景，产出 run 记录
python arena/converge.py                                      # 批跑 + CONVERGED/NOT_CONVERGED
```

## 规划件

| 件 | 职责 | 状态 |
|---|---|---|
| `engine.py` | 编排：DSL 场景 → SimEnv（时钟倍速）→ fault 注入 → agent 内核 → recorder → eval | 待建 |
| `run_scenario.py` | 单场景 CLI（D-1） | 待建 |
| `thresholds.yaml` | 收敛判据预冻结（D-5） | 待建 |
| `converge.py` | 批跑统计 + 收敛判定（D-5） | 待建 |
| `gen_scenario.py` | LLM 规则化场景生成（零信任入库） | 待建 |
| `faults/` | 论文故障库（判据阈值带标准出处） | 待建 |
| `scenarios/` | ≥20 带来源场景（D-4） | 待建 |
| `reports/` | 收敛报告（D-7） | 待建 |

## 边界（不可越过）

- 全替身仿真：被测 agent 的每个动作落在模拟世界内，不出现任何真实电力系统接口；
- 判定集场景与开发调参隔离（TASK.md D-6）；
- 真实 LLM 调用走统一 model gateway（env 注入 key，fail-closed），配额台账在案；
- Python 3.12（本机 Windows 检出已锁 LF 行尾，见 ../.gitattributes）。
