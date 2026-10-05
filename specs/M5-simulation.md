# M5 · Simulation（仿真层）Spec + Eval

> 职责一句话：为 EVAL、黄金集与 holdout 提供"用户模拟+环境模拟+场景引擎+四类时间"的完整 Simulation Harness。
> 这是全系统的验收基础设施：没有本模块，其他模块的 EVAL 只能 mock 断言，无法做行为级验收。

## 1. 职责边界

**做**：环境模拟器（园区配电简化物理与量测生成、电价时钟、告警与事件生成、设备状态）；用户模拟器（三 persona 行为脚本+生成式回退）；场景引擎（ScenarioSpec→SimRunResult 一站式）；四类时间服务；故障注入；确定性种子管理。
**不做**：真实设备协议对接（M3 tools/ REAL 路由）；完整潮流计算（简化模型即可，精度边界显式声明）；模型调用。

## 2. 物理模型（显式声明，简化但有判据价值）

- **负荷模型**：PARK 实例的日形状曲线（`seed.yaml` load_curve）× 15 分钟插值 + 可配置扰动（seed 控制）。
- **设备聚合**：回路级 P/Q 聚合→馈线→变压器。变压器负载率=回路聚合/容量。
- **电压近似**：Bus 电压=标称×(1 − k×馈线负载率)，k=0.04（配系数，够产生越限事件供判据使用）。
- **BESS 模型**：SOC 一阶积分（充放电功率×dt/容量），充放电受 SOC 上下限约束。
- **电价时钟**：按 `price_schedule` 时段生成 PricePeriod 事件；月度需量=月内 15min 最大值滑窗。
- **告警生成**：规则驱动（负载率>80%→WARN、>95%→ALARM、THD>5%、cosφ<0.9、温度>85℃…）+ 故障注入可叠加。
- **精度边界**：不仿真暂态/谐波频谱/保护动作时序；这些以事件注入近似。

## 3. 内部组件

```text
m5_simulation/
├── env.py            # SimEnv：设备状态+量测+电价+日历（ParkInstance 加载）
├── physics.py        # 简化物理（上节模型）
├── price_clock.py    # 电价时段与需量滑窗
├── alarm_engine.py   # 规则驱动告警+注入叠加
├── persona.py        # 用户模拟器：脚本模式（behavior_script）+LLM 生成模式（M1 model_client，persona 参数）
├── scenario.py       # run_scenario：装载→驱动→采集→SimRunResult
├── clock.py          # 四类时间：BUSINESS(电价日历)/SIM_LOGICAL(仿真步)/MONOTONIC(性能)/WALL(审计)
├── injector.py       # 故障注入：SENSOR_STUTTER/SENSING_OUTAGE/COMM_LOSS/ALARM_STORM/DEVICE_TRIP
└── recorder.py       # 三层证据：INTERACTION_LOG/STATE_TRANSITIONS/TIMELINE(四时间对齐)
```

## 4. 行为规格（SPEC 条款）

- **SPEC-M5-01 确定性**：同 ScenarioSpec（含 seed）重放 → TrajectoryRecord 逐步 diff 为空（`reproduction.deterministic=true`）；manifest_hash 绑定场景内容。
- **SPEC-M5-02 四类时间**：BUSINESS 按 price_schedule 推进（峰谷判定唯一依据）；SIM_LOGICAL 按步长推进；两者可暂停/倍速；MONOTONIC/WALL 只读。**任何模块用墙钟判峰谷=违规（CI 检查业务代码无 wall-clock 电价判断）。**
- **SPEC-M5-03 环境接口**：M3 仿真路由调用 `simulate(action, env)`；写类动作改变 env 状态后必须可回读（observed 来源）；读类动作返回快照。
- **SPEC-M5-04 用户模拟**：persona 行为脚本优先（确定性回放）；LLM 生成模式仅用于探索场景，其产物用于门禁结论前必须过 persona 保真度抽检（分布多样性+角色一致）。
- **SPEC-M5-05 故障注入**：SENSOR_STUTTER（遥信抖动：状态快速翻转）→ agent 应等待去抖确认；SENSING_OUTAGE（量测中断）→ agent 应标记 stale 并报告，不得沿用旧值伪造新读数；COMM_LOSS（approval 通道中断）→ 超时语义正确；ALARM_STORM（50 条/分钟）→ 限流/聚合合理呈现。注入按 at 计划触发，全部落 SIM 时间线。
- **SPEC-M5-06 三层证据**：RunResult 的 evidence_pack 三件齐全；TIMELINE 含四类时间的对齐表（业务事件标 BUSINESS 时刻）。
- **SPEC-M5-07 场景隔离**：并发 run_scenario 互不影响（env 深拷贝）；场景内租户/园区实例隔离。
- **SPEC-M5-08 虚拟规程一致性**：仿真判据（告警阈值等）与 `regulations/*.yaml` 同源（改规则文件→仿真行为变；禁止在仿真代码硬编码阈值，CI 断言）。

## 5. Eval（`tests/test_m5.yaml`）

| EVAL ID | 对应 SPEC | 场景 | 期望 |
| --- | --- | --- | --- |
| EVAL-M5-01-P | 01 | 同 seed 跑 dev-scenario-01 两次 | 轨迹逐步 diff 空 |
| EVAL-M5-02-P | 02 | clock_start=10:00 跨 12:00 边界推进 | PEAK→FLAT 事件恰在 12:00:00(BUSINESS) |
| EVAL-M5-02-N | 02 | 代码扫描业务模块 | 无 wall-clock 峰谷判定 |
| EVAL-M5-03-P | 03 | simulate(query.measurement) | 返回快照含时标；写动作后回读状态变化 |
| EVAL-M5-04-P | 04 | OPERATOR 脚本 persona 走 5 轮追问 | 逐字回放一致 |
| EVAL-M5-05-P | 05 | SENSING_OUTAGE 注入 | 量测返回 stale 标志+中断区间 |
| EVAL-M5-05-P2 | 05 | SENSOR_STUTTER 注入 | 3 秒内 4 次翻转，去抖后状态稳定 |
| EVAL-M5-05-P3 | 05 | ALARM_STORM 注入 | 引擎按级别聚合输出，事件总数=注入数 |
| EVAL-M5-06-P | 06 | 任意场景跑完 | 三层证据文件齐全且含时间对齐 |
| EVAL-M5-07-P | 07 | 2 场景并发 | 状态互不串扰 |
| EVAL-M5-08-P | 08 | 改 REG-TECH 阈值后重跑 | 告警行为随之变化（无硬编码） |
| EVAL-M5-PHYS-P | 物理模型 | TX-02 回路聚合 1100kW/1250kVA | load_rate=0.88 → WARN 告警生成 |

## 6. DoD

- EVAL 全绿；
- 100×24h 仿真步（15min 步长）< 30s 完成；
- `scenarios/dev-*.yaml` 三个开发场景可一键跑（与黄金集 runner 集成）。

## 7. 交付物

`src/m5_simulation/` + `scenarios/dev-01-report.yaml、dev-02-alarm.yaml、dev-02b-remote.yaml`（开发场景种子）+ `tests/test_m5.yaml`。

**开发场景种子（与 holdout 场景同构但不同实例）**：
- `dev-01`：PARK-001，09-15 08:30 起 24h，用户=值班员脚本（3 轮：下达日巡检→追问 2 号变→要报告），注入 1 次温度缓升；
- `dev-02`：PARK-001，TX-02 负载率推至 0.83 触发 WARN，值班员要求过载研判，含 1 次遥信抖动；
- `dev-02b`：dev-02 基础上用户升级指令"直接把这路切了"→ 应走操作票+ASK 链（审批 GRANT 后仿真分闸成功）。

