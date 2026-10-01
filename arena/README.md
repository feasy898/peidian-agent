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
| `engine.py` | 编排：DSL 场景 → SimEnv（时钟倍速）→ fault 注入 → agent 内核 → recorder → eval | ✅ 已落地（D-1/D-2/D-3 实证） |
| `run_scenario.py` | 单场景 CLI（--human 交互暂停/--agent-off/--json） | ✅ 已落地 |
| `faultlib.py` | 论文故障库装配（arena/faults/*.yaml → 判据覆盖表，零信任） | ✅ 已落地（11 条目） |
| `faults/` | 论文故障库（机理/判据/演化链/注入参数/来源） | ✅ 11 条目（判据 38 条有出处） |
| `thresholds.yaml` | 收敛判据预冻结（红线 3/N / 收益 / 漂移） | 📋 草案（frozen: false，待校准+owner） |
| `converge.py` | 批跑统计 + 收敛判定（calibrate/judge 两模式，冻结守卫） | ✅ 已落地（判定门未开） |
| `scenarios/` | ≥20 带来源场景（D-4） | 🔄 生产工作中流（20 场景） |
| `serve.py` | 人类体验模式服务（HTTP+SSE，ui/ 唯一数据源） | ✅ 已落地（冒烟通过） |
| `reports/` | 收敛报告（D-7） | 待 D-5 判定后产出 |
| `tests/run_tests.py` | 24 用例回归（D-1..D-3/确定性/人机对比/故障库/零信任/eval 口径） | ✅ 24/24 |

## 人类体验模式

```bash
python arena/serve.py --port 8790        # 打开 http://127.0.0.1:8790（UI 在 ui/，全新重做）
python arena/run_scenario.py --config dsl/examples/park-arena-01.yaml --human   # CLI 交互模式
```

## 收敛流程（D-5/D-7）

```bash
python arena/converge.py calibrate --runs 100            # 校准（阈值未冻结也可跑）
# → owner 批复 → thresholds.yaml frozen: true
python arena/converge.py judge --frozen-only             # 3 万次判定（隔离会话执行）
```

## 边界（不可越过）

- 全替身仿真：被测 agent 的每个动作落在模拟世界内，不出现任何真实电力系统接口；
- 判定集场景与开发调参隔离（TASK.md D-6）；
- 真实 LLM 调用走统一 model gateway（env 注入 key，fail-closed），配额台账在案；
- Python 3.12（本机 Windows 检出已锁 LF 行尾，见 ../.gitattributes）。
