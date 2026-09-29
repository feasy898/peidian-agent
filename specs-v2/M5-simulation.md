# M5 · Simulation（仿真层）Spec + Eval（v2.0）

> 职责一句话：为 EVAL、黄金集与 holdout 提供"用户模拟+环境模拟+场景引擎+四类时间"的完整 Simulation Harness。
> 这是全系统的验收基础设施：没有本模块，其他模块的 EVAL 只能 mock 断言，无法做行为级验收。
>
> **v2 重生成说明（资产工程阶段）**：本文件由 v1（`specs/M5-simulation.md` v1.0）按 **oracle（唯一事实源）**
> 重生成——oracle = `src/m5_simulation/`（10 实现文件 + `eval_plugin.py` 执行器插件）+
> `scenarios/dev-*.yaml`（3 开发场景）+ `tests/test_m5.yaml`（现行 20 用例）+
> `tests/fixtures/dev-sim-park.yaml`（EVAL 实例）+ `regulations/REG-TECH.yaml`（判据同源）+
> `ontology/actions.yaml`（缺省 Policy 数据源）。
> 结构与 v1 保持同节编号（§1–§7）便于 diff；**每处与 v1 的差异加行内标记 `[v2Δ: 偏差依据 evidence]`**，
> 未标记部分与 v1 语义一致。本模块偏差 D-38..D-47（`specs-v2/DEVIATIONS-draft.md`；处置记录见
> `specs-v2/deviations/M5.md`）全部吸收为条款；无 KNOWN-DEFECT 级缺陷。
>
> **v1→v2 条款编号映射**（v2 重排：v1 8 条 SPEC + §2 物理模型散文 → v2 15 条）：
>
> | v1 条目 | v2 条款 | 说明 |
> | --- | --- | --- |
> | SPEC-M5-01 确定性 | **SPEC-M5-01** | 扩展：种子来源成文（D-38）、latency_ms 确定性常数与审计列剔除成文（D-42） |
> | SPEC-M5-02 四类时间 | **SPEC-M5-02** | 扩展：clock.py 唯一真实时钟实现位、扫描面 [src,tools,scripts]（D-44） |
> | SPEC-M5-03 环境接口 | **SPEC-M5-03** | 扩展：宽松输入、DENY 路径数据驱动+DENIED 终态（D-47）；SAFE 执行位拆出 SPEC-M5-15 |
> | SPEC-M5-04 用户模拟 | **SPEC-M5-04** | 扩展：LLM 模式经 model_client 接线激活、降级路径、datetime.max 哨兵（D-45） |
> | SPEC-M5-05 故障注入 | **SPEC-M5-05** | 扩展：参数缺省表、sim.injected 事件、五类逐类机械口径成文 |
> | SPEC-M5-06 三层证据 | **SPEC-M5-06** | 扩展：落盘路径、trajectory.json、AUDIT_COLUMNS（D-42） |
> | SPEC-M5-07 场景隔离 | **SPEC-M5-07** | 扩展：deep_copy 逐字段清单、本体只读共享 |
> | SPEC-M5-08 规程同源 | **SPEC-M5-08** | 修订：REG-TECH 唯一阈值来源（D-39）、PHYS-TX-TEMP（D-40）、SOC 兜底物理量程（D-45） |
> | §2 物理模型（散文） | **§2 + SPEC-M5-09** | 条款化：MODEL_DEFAULTS 常数表+公式（D-39/D-40 修订措辞） |
> | （v1 无） | **SPEC-M5-10** | 场景引擎 tick 流水线与停止条件（开发实况转正） |
> | （v1 无） | **SPEC-M5-11** | SUT 桩链与审批链（timeout_s 换算 D-41） |
> | （v1 无） | **SPEC-M5-12** | 计划环境事件族（device.temp_rise D-40） |
> | （v1 无） | **SPEC-M5-13** | 电价时钟与月度需量（ADDENDUM §C 落地，D-69 交叉） |
> | （v1 无） | **SPEC-M5-14** | Park 实例按名加载与 EVAL 实例注入（D-43；D-70 交叉） |
> | （v1 无） | **SPEC-M5-15** | SAFE 三规约 M5 判据层执行位（D-46） |
> | §5 Eval 表（12 条） | **§5**（v2 重生成 26 条 + 变异补缺 1 条 = 27 条 = 正例 17/负例 10） | v1 20 条逐条核对后保留改名；禁止类条款补负例；条款↔用例双向表见 §5 |
> | §6 DoD / §7 交付物 | **§6 / §7** | 按 oracle 更新（dev-02b 继承恢复 D-45；fixtures 入交付物） |

---

## 1. 职责边界

**做**：环境模拟器 SimEnv（设备运行态深拷贝、量测库含 stale 标志与中断区间、告警表、操作票/工单/审批/需量滑窗/事件缓冲，`src/m5_simulation/env.py:166-204`）；简化物理引擎（负荷/PV/环境传感/BESS/聚合/电压/温度/THD，`physics.py`）；电价时钟与月度需量滑窗（`price_clock.py`）；规程阈值驱动告警引擎（`alarm_engine.py`）；用户模拟器（脚本逐字回放+LLM 生成降级路径，`persona.py`）；五类故障注入（`injector.py`）；场景引擎（ScenarioSpec→SimRunResult 一站式 + SUT 桩链/审批链，`scenario.py`）；四类时间服务（`clock.py`）；三层证据采集与确定性 diff（`recorder.py`）。

**不做**：真实设备协议对接（M3 `tools/` REAL 路由）；完整潮流计算（简化模型即可，精度边界显式声明，见 §2）；**模型 SDK 直连**（用户模拟 LLM 模式统一经 `m1_core.model_client` 调用，01 §8；`persona.py:121-133`）[v2Δ: v1 写"模型调用"不做——oracle 实为"不经统一客户端的模型调用"不做，LLM 生成模式已接线]；真实时延计量（latency 实测属 MONOTONIC 审计域，由 M3 REAL 路由负责；`scenario.py:112-114`）[v2Δ: 补]；事件流持久化权威（`runtime/events/` 归 M2 event_log；M5 事件在 `env.event_log` 内存态与证据层）。

上游依赖：M4（本体/规程/实例装载 `m4_semantic.loader.load_ontology`，`env.py:26,477`）、`contracts/`（ScenarioSpec/SimRunResult/EventRecord/ActionRequest 冻结结构）。

## 2. 物理模型（显式声明，简化但有判据价值）

物理常数集中于 `MODEL_DEFAULTS`（可经 `run_scenario(model_params=...)` 逐场景覆盖；**物理模型常数非告警阈值**——阈值一律来自 REG-TECH，见 SPEC-M5-08；`physics.py:31-45`）：

| 常数 | 值 | 语义 |
| --- | --- | --- |
| `voltage_drop_k` | 0.04 | Bus 电压=标称×(1−k×馈线负载率) |
| `power_factor` | 0.92 | 缺省功率因数（设备/回路属性可覆盖） |
| `ambient_c` | 25.0 | 环境温度（℃） |
| `tx_temp_rise_c` | **55.0** | 变压器满载温升 K（顶油温升类**建模常数非阈值**；temp = ambient + rise×load_rate + 事件漂移）[v2Δ D-40: 复核修订 2 由 75K 改 55K，正常负载 ≈73℃ 不误报；阈值 85℃ 在 REG-TECH PHYS-TX-TEMP（`regulations/REG-TECH.yaml:86-96`）] |
| `thd_base` / `thd_load_coeff` | 0.03 / 0.01 | THD 基线 + 负载率分量 |
| `noise_amplitude` | 0.03 | 负荷扰动幅度 ±3%（seed 控制） |
| `pv_peak_factor` / `pv_day_start_h` / `pv_day_end_h` | 0.65 / 7.0 / 18.0 | PV 白天钟形出力 |
| `soc_deadband` | 0.5 | SOC 触界吸附带（%），防积分抖动 |

模型口径（公式=实现，证据为 `physics.py`）：

- **负荷**：实例日形状曲线（`load_curve.shape` 24 点小时粒度）× 15 分钟线性插值（首尾环绕）× seed 控制的乘性扰动（`physics.py:48-58,82-88`）。
- **PV/环境传感**：PV 白天钟形逐台落量测（158-169）；温湿度/局放按模型常数+seed 扰动生成（97-108）。
- **BESS**：价段驱动谷充峰放（VALLEY 充、PEAK/SHARP 放）+ SOC 一阶积分（功率×dt/容量），充放电受 SOC 运行区间约束——上下限取规程 PHYS-BESS-SOC 阈值（数据驱动）± 吸附带；规程缺失兜底为**物理量程 (0,100)**（百分数表示域，非运行限值；此时告警引擎因无规则同样不判定）（`physics.py:171-229`；兜底 183-185）[v2Δ D-45: 复核修订 4，原硬编码兜底 (10,90) 属阈值泄漏]。
- **聚合**：园区净负荷按**运行中**变压器容量分摊（FAULT 不计）；`load.set` 事件覆盖为**绝对值且不受扰动**（精确判据用）；负载率=聚合有功/额定容量（EVAL-M5-09-P：1100kW/1250kVA=0.88）；馈线=Σ上游变压器有功，容量缺省取 Σ 上游变压器容量（`physics.py:237-281`；覆盖 250-254）。
- **电压**：Bus 电压=标称×(1−k×关联馈线最大负载率)，无馈线节点退化为园区负载率；THD=基线+负载分量（`thd.set` 可事件覆盖）（`physics.py:283-309`）。
- **温度**：winding_temp_c = 环境温度 + 满载温升×负载率 + 事件漂移（`device.temp_rise` 坡道累计，见 SPEC-M5-12）（`physics.py:125-136`；`scenario.py:557-568`）。
- **精度边界**：不仿真暂态/谐波频谱/保护动作时序——这些以事件注入近似（DEVICE_TRIP→FAULT+分闸+`grid.event` 近似保护动作，`injector.py:216-227`）。
- **告警生成** [v2Δ D-39: 本条为 v1 §2 修订——v1 示例口径"负载率>80%→WARN、>95%→ALARM、THD>5%、cosφ<0.9、温度>85℃…"与 REG-TECH 阈值（0.80→**P2** 过载预警、1.00→**P0**、THD 0.05→P3/0.08→P2、cosφ<0.90→P3、温度 **>85→P2**）不符，按 SPEC-M5-08 同源纪律以 `regulations/REG-TECH.yaml` thresholds 为唯一口径，告警级别用 P0-P3 枚举而非 WARN/ALARM 词（EVAL-M5-09-P 的 0.88→P2 即此口径；`alarm_engine.py:13-14,51-58`；tests/CHANGELOG.md M5 登记 2）]：规则驱动（REG-TECH thresholds，scope/metric/op/level 全数据驱动）+ 故障注入可叠加（ALARM_STORM）。

## 3. 内部组件

```text
m5_simulation/
├── env.py            # SimEnv：设备运行态+量测库（stale/中断区间）+告警表+操作票/审批/需量窗+
│                     #   事件缓冲；Park 实例按名加载（ADDENDUM §D）；manifest_hash/种子派生
├── physics.py        # 简化物理（§2 模型；MODEL_DEFAULTS 常数；引擎无内部状态）
├── price_clock.py    # 电价时段判定（BUSINESS 唯一入口）+ 月度需量 15min 滑窗（ADDENDUM §C）
├── alarm_engine.py   # 规程阈值驱动告警（REG-TECH 数据驱动，零硬编码阈值）
├── persona.py        # 用户模拟器：脚本逐字回放 + LLM 模式（m1_core.model_client）+降级路径
├── scenario.py       # run_scenario 一站式 + simulate 仿真路由 + SUT 桩链/审批链 + diff_runs
├── clock.py          # 四类时间：BUSINESS/SIM_LOGICAL（仿真轴，可暂停/倍速）+
│                     #   MONOTONIC/WALL（只读真实时钟的唯一合法实现位）
├── injector.py       # 故障注入：SENSOR_STUTTER/SENSING_OUTAGE/COMM_LOSS/ALARM_STORM/DEVICE_TRIP
├── recorder.py       # 三层证据：INTERACTION_LOG/STATE_TRANSITIONS/TIMELINE（四时间对齐）+轨迹
└── eval_plugin.py    # tests/test_m5.yaml 数据驱动 EVAL 执行器插件（13 执行器）
                      # [v2Δ: v1 组件树缺 eval_plugin.py 与"唯一合法时钟位"定位]
```

场景种子与判据数据（交付物详见 §7）：`scenarios/dev-01-report.yaml、dev-02-alarm.yaml、dev-02b-remote.yaml`；
EVAL 实例 `tests/fixtures/dev-sim-park.yaml`（+ M4 共用 `dev-graph.yaml`）；EVAL 用例 `tests/test_m5.yaml`（20 条）。

## 4. 行为规格（SPEC 条款 v2）

- **SPEC-M5-01 确定性与可复现**：同一 ScenarioSpec 重放 → 轨迹/三层证据/终态逐步 diff 为空，
  `reproduction.deterministic=true`（`scenario.py:800`）。`manifest_hash` = sha256(归一化 spec dict)
  （datetime→ISO 字符串、键排序稳定）绑定场景内容（`env.py:80-101`）；**本结构无独立 seed 字段**，
  缺省种子由 manifest_hash 派生 `seed-<hash 前 16>`（同规格同种子→确定性重放），`run_scenario(seed=...)`
  可显式覆盖，`reproduction.seed` 记录实际值（`env.py:104-110`；`scenario.py:352-356,795-800`）
  [v2Δ D-38: v1 未写种子来源；tests/CHANGELOG.md M5 登记 1]。
  确定性比对 `diff_runs`：剔除审计列 `AUDIT_COLUMNS=("monotonic_ms","wall_at","latency_ms")` 后
  逐层比对轨迹 steps、INTERACTION_LOG、STATE_TRANSITIONS、TIMELINE、终态快照与 manifest_hash
  （`recorder.py:25,34-40`；`scenario.py:867-909`）。**SIMULATION 时延确定性**：`latency_ms` 为
  确定性常数（真实时延属 MONOTONIC 审计域，由 M3 REAL 路由计量）——主路径常数 0
  （`scenario.py:107-116,316-327`）；DENY/审批终态路径当前为常数 1（`scenario.py:636,685`），
  同为确定性常数且属被剔除审计列，随本条款统一为"确定性常数"口径，非 KNOWN-DEFECT
  [v2Δ D-42: v1 未写；复核修订 1（原 perf_counter 实测泄漏进轨迹致 diff 非空，改常数并增列
  latency_ms 二道防线）；tests/CHANGELOG.md M5 复核修订 1+M5 登记 9]。
  证据：EVAL-M5-01-P。

- **SPEC-M5-02 四类时间与时钟纪律**：四类时间封闭集 BUSINESS/SIM_LOGICAL/MONOTONIC/WALL
  （`clock.py:38-44`）。BUSINESS=clock_start+累计仿真秒，**峰谷电价判定唯一依据**（`clock.py:133-135`）；
  SIM_LOGICAL=自场景起点累计仿真秒（15min 步长推进）；两者共享仿真时间轴，可暂停/倍速
  （`advance_sim` 离散步进不受 speed 影响、拒绝回拨、暂停不动；`advance_wall`=墙钟秒×speed 连续推进；
  `pause/resume/set_speed`，`clock.py:100-130`）；MONOTONIC/WALL 只读真实时钟、不可暂停/倍速、
  仅用于审计/计量，**唯一合法实现位=`m5_simulation/clock.py`**（`clock.py:145-149`）
  [v2Δ D-44: v1 未指定实现位；扫描排除清单是用例数据非代码特判；tests/CHANGELOG.md M5 登记 8]。
  `clock(mode)` 无 ClockHub 调 BUSINESS/SIM_LOGICAL 抛 ValueError（业务时钟不落回墙钟——
  电价判定红线，`clock.py:165-180`）；四类对齐行 `aligned_row()` 供 TIMELINE（151-162）。
  **任何业务代码以墙钟判峰谷=违规（CI/词面扫描断言）**：EVAL-M5-02-N 扫描面
  `scan_dirs=[src,tools,scripts]`（业务代码全口径；tools/scripts 实测零违例），排除
  `m5_simulation/clock.py`（只读真实源实现位）与 `eval_plugin.py`（扫描器自身）
  （`eval_plugin.py:252-288`；`tests/test_m5.yaml:53-71`）
  [v2Δ D-44: 扫描面由 [src] 扩为 [src,tools,scripts]；tests/CHANGELOG.md 安全规程判据落地 5]；
  另有行为级断言：篡改墙钟（FakeDateTime）不改变 `period_at` 判定（`eval_plugin.py:225-242`）。
  holdout 隔离正则 `PARK-002|TARIFF-2026B|OP-1[0-9]`（`scripts/ci_isolation.py:31`）
  [v2Δ D-44: ADDENDUM §F OP-1x 的等宽正则；tests/CHANGELOG.md 独立评审 4]。
  证据：EVAL-M5-02-P（PEAK→FLAT 恰在 12:00:00 BUSINESS + 墙钟篡改不改判定）、EVAL-M5-02-N、
  EVAL-M5-02-N2（clock() 无 hub 的 BUSINESS/SIM_LOGICAL 一律 ValueError——禁墙钟兜底，
  变异 m5-business-nohub-wall-fallback 的钉死用例）。

- **SPEC-M5-03 环境接口（simulate 仿真路由）**：`simulate(action, env) -> (ActionResult, SimEnv)`
  （`scenario.py:77-266`）。接受契约 ActionRequest 或宽松 dict（缺省补全
  task_id/turn/actor/idempotency_key 的合成请求，`scenario.py:277-299`）。**未登记动作 →
  FAILED/`UNREGISTERED_CAPABILITY`**（红线 1，118-120）。**缺省 Policy=DENY 动作**（按
  `ontology/actions.yaml` 的 default_policy 现算，`_default_deny_actions` 与 M3
  `registry.assert_immutable_consistency` 同源、无第三份硬编码清单，62-71）→ **终态 DENIED/**
  `POLICY_DENIED`**（01 §5.2 冻结迁移 DENY→DENIED，与 M3 gateway/SUT 桩链一致，121-130）
  [v2Δ D-47: v1 的第三份硬编码 DENY 清单已删，终态由 FAILED/POLICY_DENIED 改 DENIED；
  tests/CHANGELOG.md 独立评审缺口修复 3；commit 06ce55a——DENIED 枚举见 01 v2 §5.2 D-01]。
  **读类**（query.measurement/asset/regulation）返回带时标快照（量测快照含 ts/quality/stale；
  台账/规程不存在→`NO_SUCH_DEVICE`/`NO_SUCH_RULE`，133-157）；**写类先变更 env 再回读
  observed**（observed 必须来自环境回读，01 §2.2）：execute.remote_control（160-212）、
  execute.capacitor_switch（213-228）、create.switch_order（229-250，见 SPEC-M5-15）、
  create.work_order/create.inspection_record/write.report 落仿真侧产物标记（251-258）、
  analyze.* 简化回执（259-264）；SUCCEEDED 的 evidence 三态齐全（316-327）；未实现的已登记动作 →
  FAILED/`SIM_ROUTE_UNSUPPORTED`（266）。
  证据：EVAL-M5-03-P。

- **SPEC-M5-04 用户模拟**：persona 行为脚本优先（确定性回放）——`behavior_script` 按计划序逐字
  回放（act 归一为契约字面量，`persona.py:57-96,62-64`），两次回放逐字一致。LLM 生成模式经
  `m1_core.model_client` 统一客户端调用（01 §8 禁止直连 SDK；`persona.py:121-143`）——M1 交付
  （mock provider 全离线可用）后该路径已激活：mock 正常产出 `mode="llm"`，失败 provider 走
  **降级路径**回退脚本模式并标记 `degraded=True`，无脚本可回退返回 None 并留 `LLM_DEGRADED`
  记录（`persona.py:144-150,170-176`；`eval_plugin.py:382-396`）
  [v2Δ: v1 只写"LLM 生成模式仅用于探索场景"；oracle 补齐接线/降级机械口径（M1 交付联动，
  tests/CHANGELOG.md M5 复核修订 II）]。LLM 产物用于门禁结论前必须过 persona 保真度抽检——
  `fidelity_check` 机械抽检（分布多样性+角色一致，`persona.py:179-194`）。
  会话远期哨兵=常量 `datetime.max`（业务模块零 wall-clock，`persona.py:157-167`）
  [v2Δ D-45: 原 `datetime.now()+10y` 改常量；tests/CHANGELOG.md M5 复核修订 3]。
  证据：EVAL-M5-04-P。

- **SPEC-M5-05 故障注入**：五类封闭集 `FAULT_TYPES`（`injector.py:30`），按 `at` 计划触发、
  升序稳定排序、(prev,now] 到期触发，每条先落 `sim.injected` 事件（参数缺省表
  `FAULT_PARAMS_DEFAULTS` 可被 params 覆盖：stutter 4 翻/3s/去抖 2s、outage 900s、
  comm_loss 600s、storm 50 条/60s/P2+P3、trip→OPEN；`injector.py:32-38,63-124`），全部落 SIM
  时间线（事件带精确子步时刻）。逐类口径：
  **SENSOR_STUTTER**（遥信抖动：flips 次翻转均布 window_s、逐条落 `measurement.updated`
  事件带 fault_type 标记，登记 `env.chatter`；`debounced_state` 提供去抖视图——窗口内
  `chattering=True` 应等待确认，稳定 ≥ debounce_s 才可信；127-160；`env.py:283-308`）；
  **SENSING_OUTAGE**（量测中断：窗口内量测**保持旧值 + STALE 标志 + 中断区间 [from,to]**，
  不得伪造新读数，恢复后刷新并发 `measurement.updated{recovered:true}`；162-171；`env.py:336-368`）；
  **COMM_LOSS**（审批通道中断：窗口内 `approval_channel_open()=False`，审批走超时语义；
  173-183；`env.py:393-399`）；**ALARM_STORM**（count 条按 window_s 均布、levels 轮转——
  **事件总数=注入数**，聚合视图按级别汇总不丢事件；185-214；`alarm_engine.py:39-45`）；
  **DEVICE_TRIP**（状态→FAULT+分闸+`grid.event` 近似保护动作；216-227）。
  [v2Δ: v1 未写参数缺省表与 sim.injected 事件；五类逐类覆盖=表外补强 EVAL-M5-05-P4/P5
  （COMM_LOSS 侧现 EVAL-M5-11-N，tests/CHANGELOG.md M5 登记 6）]
  证据：EVAL-M5-05-P/P2/P3/P5（COMM_LOSS→审批超时见 EVAL-M5-11-N）。

- **SPEC-M5-06 三层证据**：SimRunResult.evidence_pack 三件齐全——INTERACTION_LOG（用户模拟
  逐条记录）/STATE_TRANSITIONS（设备状态/分合位/告警升降/负载覆盖迁移行，从 tick 事件流提取，
  `scenario.py:718-757`）/TIMELINE（四类时间对齐表：每行同时携带 business_at/sim_elapsed_s/
  monotonic_ms/wall_at，业务事件标 BUSINESS 时刻）落 `runtime/runs/<run_id>/` 三个 jsonl +
  `trajectory.json`（ref 为仓库根相对路径；`recorder.py:27-31,67-112,115-145`；
  `clock.py:151-162`；`env.py:222-236`）。monotonic_ms/wall_at/latency_ms 为**审计列**
  （真实时间源或其派生测量），确定性 diff 按约定剔除，判据列 business_at/sim_elapsed_s
  逐步比对（`recorder.py:25,34-40`）[v2Δ D-42: tests/CHANGELOG.md M5 登记 9]。
  轨迹步（TOOL_CALL/STATE_CHANGE/APPROVAL）与 M6 TrajectoryRecord 采集口径对齐
  （`recorder.py:105-112`；`scenario.py:707-716`）；`persist=False` 时证据内联占位
  （`scenario.py:796-799`）。
  证据：EVAL-M5-06-P（TIMELINE 含四类时间对齐行）。

- **SPEC-M5-07 场景隔离**：SimEnv 为每场景独享的可变状态容器；`deep_copy()` 逐项深拷贝全部
  可变状态（devices/relations/measurements/alarms/load_overrides/outages/comm_losses/
  artifacts/load_curve/demand_records/price_schedule/pending_injections/pending_events/
  switch_orders/work_orders/chatter/storm_summary/demand_window/operators + 时钟/rng/事件序号），
  **本体快照只读共享**（`env.py:239-280`）；并发 run_scenario（线程）互不影响，每 run 独立
  证据目录 `runtime/runs/<run_id>/`（run_id 由 manifest_hash 派生，`env.py:474-475`；
  `recorder.py:43-48`）；性能路径复用模板 env 深拷贝（`eval_plugin.py:995-1029`）。
  证据：EVAL-M5-07-P（2 场景并发终态互不串扰）。

- **SPEC-M5-08 虚拟规程一致性（判据同源）**：仿真判据（告警阈值等）的**唯一来源=
  `regulations/REG-TECH.yaml`**（经 `load_ontology` 装入 `LoadedOntology.regulations`；
  AlarmEngine 只取带 metric+thresholds 的规则，`alarm_engine.py:51-58`）——改规则文件即改仿真
  告警行为，**仿真代码零硬编码阈值，CI 断言** [v2Δ D-39: v1 §2 示例口径（">80%→WARN、>95%→ALARM"）
  与 REG-TECH（0.80→P2、1.00→P0）不符，按规程文件为准；tests/CHANGELOG.md M5 登记 2]。
  告警引擎机制：逐 (规则,对象) 评估——`scope` 决定对象类型（scope=Park 的规则取 extra_metrics，
  demand_ratio 由需量滑窗注入；`alarm_engine.py:108-120`；`scenario.py:462-463`）；`metric` 取
  量测库值；`thresholds` 按序评估取最严重级别（P0 最重，`LEVEL_SEVERITY`；判定算子封闭集
  `>/>=/</<=/==`；`alarm_engine.py:27,30-36,122-134`）；每 (规则,对象) 单一活动告警，级别变化
  先清后升（87-94）；越限 `alarm.raised`、恢复 `alarm.cleared`（155-171）；告警记录字段与
  00 §1.1.C Alarm 一致（136-153）。PHYS-TX-TEMP（winding_temp_c>85→P2）已入 REG-TECH
  （`regulations/REG-TECH.yaml:86-96`）——M5 §2 温度告警由不可达变可达（实测 86.9℃ 触发 P2）
  [v2Δ D-40: tests/CHANGELOG.md M5 登记 3+复核修订 2；条款全文见 00 v2 §1.4]。
  SOC 运行上下限同源取 PHYS-BESS-SOC 阈值；规程缺失兜底=物理量程 (0,100)（非阈值；
  `physics.py:171-185`）[v2Δ D-45: 复核修订 4]。
  证据：EVAL-M5-08-P（临时仓库根改 PHYS-TX-LOAD 阈值 0.80→0.50 后告警 0→1 条，判据同源零硬编码）。

- **SPEC-M5-09 物理模型（§2 条款化）**：PhysicsEngine 每步推进 负荷→DER→聚合→电压→温度/THD→
  量测落库，**引擎自身无内部状态**（全部状态在 SimEnv，保证同 env 重放确定性；
  `physics.py:61-65,73-78`）；模型公式与常数=§2 表（负荷/PV/环境传感/BESS/聚合/电压/温度/THD）。
  负载率聚合判据：TX-02 回路聚合 1100kW/1250kVA（EVAL 实例 dev-sim-park）→ load_rate=0.88 →
  触发 PHYS-TX-LOAD P2 过载预警告警（文本含"过载预警"；阈值与级别来自 REG-TECH，见 SPEC-M5-08）
  [v2Δ D-39: v1 §2"WARN"措辞按 REG-TECH P2 口径修订；EVAL-M5-09-P]。
  证据：EVAL-M5-09-P。

- **SPEC-M5-10 场景引擎流水线**：`run_scenario(spec, *, seed, repo_root, persist, model_params)`
  接受 ScenarioSpec/dict/YAML 文件路径（`scenario.py:843-861`）；ScenarioEngine 组装
  Physics/PriceClock/DemandTracker/AlarmEngine/FaultInjector/PersonaSession（357-366）。
  每 tick 按固定顺序推进：①到期故障注入→②到期计划事件→③物理推进→④电价时段边界→
  ⑤需量 15min 滑窗→⑥规程阈值告警（extra_metrics=demand_ratio）→⑦persona 到期输出+审批决断→
  ⑧审批超时判定（437-489），产出 observation 与 TIMELINE TICK 行（469-488）。
  停止条件数据驱动解析（`stop_conditions` 字符串清单）：`duration_h:`/`duration_s:`
  （缺省 24h）、`max_ticks:`、`script_done`（脚本+计划+注入+审批全部收尾才停）、`actions_done`；
  安全步数上限 `MAX_TICKS=20000` 防配置失误死循环（55,402-434,762-767）；终发
  `sim.completed{ticks, sim_elapsed_s}`（770-772），组装 SimRunResult（792-803）。
  [v2Δ: v1 未写 tick 流水线顺序/停止条件/步数上限——开发实况转正]

- **SPEC-M5-11 SUT 桩链与审批链**：计划事件 `action.request` → 合成 ActionRequest → 落
  `action.requested` → 按 `ontology/actions.yaml` 缺省 Policy 三分支（数据驱动，`scenario.py:576-637`）：
  **ALLOW** 直执行 simulate（594-597）；**ASK** → `action.waiting_approval`+`approval.requested`
  {timeout_s}+预置操作票登记（见 SPEC-M5-15）+pending_approval（597-628）；**DENY** →
  DENIED/POLICY_DENIED（629-637）。审批决断由 persona GRANT/DENY 到期驱动（639-650）：
  GRANT 且通道开 → `approval.granted`（payload.approver 为固定审计标记 `"OP-004"`，667-671；
  与 M6 evaluator 审批决断人硬编码同类口径，见 01 v2 §3.6 D-58）→ granted_keys+simulate 执行；
  GRANT 但 COMM_LOSS 窗口内不可达 → `approval.timeout{reason:COMM_LOSS}`+REJECTED/
  `APPROVAL_TIMEOUT`（658-666）；DENY → `approval.denied`+REJECTED/`APPROVAL_DENIED`
  （672-676）。审批超时判定每 tick 执行：**`interactions.timeout_s` 为墙钟秒，按 speed
  （墙钟秒→仿真秒）换算为仿真秒** `sim_timeout=max(timeout_s×speed, 1.0)` 后与审批年龄比较，
  通道中断同样触发超时（689-705）
  [v2Δ D-41: v1 未写换算口径（SPEC-M5-02 倍速语义的落地）；tests/CHANGELOG.md M5 登记 4]。
  `execute.remote_control` 无已签发操作票一律 FAILED/`NO_SWITCH_ORDER`（SAFE-TWO-TICKET 红线，
  160-168）。
  证据：EVAL-M5-11-N（COMM_LOSS→超时拒绝）、EVAL-M5-11-N2（无票拒绝）、
  EVAL-M5-10-P（dev-02b ASK→GRANT→分闸成功链）。

- **SPEC-M5-12 计划环境事件族**：`ScenarioSpec.events` 按 `at`（绝对 UTC ISO-8601 或场景相对
  时间 `T+90m`/`+45s`/`+30000ms`，`parse_time_ref`）解析到期触发（`env.py:57-77`；
  `scenario.py:491-555`）。事件类型族（数据驱动）：`load.set`（负载覆盖为绝对值、
  duration_s/until 窗口、`grid.event{kind:load_override}`+STATE_TRANSITIONS 行；498-511）、
  `load.scale`（512-521）、**`device.temp_rise`**（温度缓升坡道 rate_c_per_h/duration_s/cap_c：
  登记 temp_ramps，每 tick 累计 device.temp_drift_c，cap 封顶；522-533,557-568）
  [v2Δ D-40: dev-01"温度缓升注入"落为环境事件而非五类故障注入（00 §1.1 量测事件语义），
  配套规程条款 PHYS-TX-TEMP 与物理常数 tx_temp_rise_c=55K（§2）；tests/CHANGELOG.md M5 登记 3]，
  `thd.set`（534-540）、`soc.set`（541-547）、`grid.event`（548-550）、`action.request`
  （→SPEC-M5-11 桩链；551-552）；未知类型按 `grid.event{kind:planned_event}` 近似（554-555）。
  证据：EVAL-M5-12-P（temp_rise 事件落时间线）、EVAL-M5-10-P；
  `scenarios/dev-01-report.yaml:34-38`（device.temp_rise 事件数据）。

- **SPEC-M5-13 电价时钟与月度需量**：`period_at(env, sim_elapsed_s)` 是 BUSINESS 时刻电价时段
  判定的**唯一入口**（支持跨零点时段；实例无电价表返回 None；`price_clock.py:41-59`）——本模块
  全部以 `clock_start+仿真秒` 推导，无任何真实时间源引用。PriceClock 推进 [prev,now] 内每个越过
  的时段边界发 `price.period_changed{from,to,price,boundary}`（边界时刻精确到秒、occurred_at=
  BUSINESS 读数；72-97,85-92,111-122）。DemandTracker：月内 15min 采样最大值滑窗（实例
  `demand_YYYY_MM` 历史需量作当月基线；125-141）；跨月采样**先发
  `demand.month_rolled{from_month,to_month,frozen_peak_kw}` 再重置峰值**（142-161）；
  `demand_ratio`=月峰值/合同容量（136-140），注入告警引擎评估（`scenario.py:459-463`）。
  [v2Δ D-69 交叉: ADDENDUM §C 两事件落地核对（主题归属契约层 01 v2 §4，events/price_clock.py 为
  M5 侧落地）；代码锚点 `src/contracts/enums.py:224-225`、`src/m5_simulation/price_clock.py:75-97,143-161`；
  处置登记 `specs-v2/deviations/M5.md` D-69 行与 `specs-v2/DEVIATIONS.md` ADDENDUM 节]
  证据：EVAL-M5-02-P。

- **SPEC-M5-14 Park 实例按名加载与 EVAL 实例注入**：`load_scenario` 按
  `ScenarioSpec.environment.park_instance` 名加载园区实例（`env.py:457-480` →
  `m4_semantic.loader.load_ontology(instance=...)`）。实例解析协议（ADDENDUM §D）：默认搜索
  `ontology/`，环境变量 `PARK_INSTANCE_PATH`（分隔符 ";"）依序追加目录（调用时读取），
  去扩展名匹配 .yaml/.yml，实例名须为安全标识符（`src/m4_semantic/loader.py:63-65,178-198`）
  [v2Δ D-70 交叉: 条款归属 00 v2 §3/ADDENDUM，M4 loader 与 M5 env 同一机制]。
  设备运行态深拷贝进 DeviceRuntime（场景内可变）、本体快照只读共享；实例数据通用节扫描
  （price_schedule / `load_curve*` / `demand_YYYY_MM` / operators，零实例特判；
  `env.py:504-544`）；缺省实例=seed（`ontology/seed.yaml`）。
  **EVAL 实例注入机制**：seed 的 TX-02=1600kVA 与 EVAL-M5-09-P 需要的 1250kVA 不一致、
  PARK-001 seed 无告警/工单/检修计划/负荷曲线运行对象而三跳查询需要——开发实例
  `tests/fixtures/dev-sim-park.yaml`（PARK-001 同构快照仅改 TX-02 容量，`dev-sim-park.yaml:20`）
  与 `tests/fixtures/dev-graph.yaml`（同构含 AL-0201/WO-D0021/MP-TX01/LC-A0901/F-A1）置于
  tests/fixtures/，EVAL 执行器经 `PARK_INSTANCE_PATH` 追加注入（调用后还原），同一代码路径服务
  任意同构实例（`eval_plugin.py:43-61`）
  [v2Δ D-43: EVAL 实例与生产实例分离的注入机制；tests/CHANGELOG.md M5 登记 7+M4 登记 1]。
  证据：EVAL-M5-09-P / EVAL-M5-08-P（instance: dev-sim-park，经 `PARK_INSTANCE_PATH` 注入）。

- **SPEC-M5-15 SAFE 三规约 M5 判据层**（v1 00 §1.4 只声明规则未指定执行位；oracle 在 M5 判据层
  强制执行 [v2Δ D-46: tests/CHANGELOG.md 安全规程判据落地 1/2/3；commit 06ce55a]）：
  **SAFE-ISSUE-HUMAN**：`simulate` 对 `create.switch_order` 的非 DRAFT 请求一律
  FAILED/`SAFE_ISSUE_HUMAN`、零副作用（被拒票不登记；`scenario.py:229-250`）——与 M3 准入
  `SCHEMA_INVALID`（`tools/create__switch_order.py:31-35` status 枚举收窄 `[DRAFT]`）构成双保险；
  DRAFT→ISSUED 只能由持证签发人（角色数据源=实例 `env.operators`）在 agent 动作集外完成——
  SUT 桩链预置票票面签发人须为已登记且角色="签发人"（`_operator_role`；269-274,607-617），
  校验不过→仅登记 DRAFT 并落合规事件 `grid.event{kind:compliance, rule:SAFE-ISSUE-HUMAN}`
  （618-623），GRANT 后遥控仍被两票制拒绝。
  **SAFE-ORDER-SEQ**：`execute.remote_control` 的 step 与票面 steps 声明顺序对照——跳步/非法
  步骤号→FAILED/`SAFE_ORDER_SEQ`（173-184）；多步票逐步放行、执行中保持 ISSUED、全部声明步骤
  完成才置 COMPLETED（204-208）。
  **SAFE-SINGLE-OP**：票级 `executing` 执行流互斥标记——已有执行流的票再受执行→
  FAILED/`SAFE_SINGLE_OP`，执行结束/异常均释放（try/finally；169-172,189-200）。
  证据：EVAL-M5-15-N1 / 15-N2 / 15-N3 / 15-N4（正例合规链见 EVAL-M5-10-P dev-02b）。

## 5. Eval（`tests/test_m5.yaml`，v2 重生成 26 条 + 变异补缺 1 条 = 27 条）

执行器注册于 `src/m5_simulation/eval_plugin.py`（`EXECUTORS` 13 个 + tests 侧插件
`tests/fixtures/m5_eval_plugin.py` 1 个，全部断言数据取自用例
params/expect，零案例特判）。v2 套件由本文件（SPEC-M5-01..15）
机械重生成：**26 条 + EVAL-M5-02-N2（变异补缺，SPEC-M5-02 无 hub 边界）= 27 条 = 正例 17 / 负例 10**；v1 20 条逐条核对其断言正是 v2 条款后保留改名
（§5.2 对照列）；禁止类条款（02 禁墙钟判价、03 未注册/DENY 动作禁止执行、11 无票遥控
必须拒、15 三规约）全部有负例。spec_ref 自 v2 起指向 specs-v2（ADDENDUM v2 未交付前
仍引 v1 原文，D-70 实例协议依赖）；v1→v2 的 spec_hash→eval_hash 对登记于
`tests/CHANGELOG.md`（01 v2 §6 协议）。

### 5.1 条款 → 用例（双向映射）

| v2 条款 | 正例用例 | 负例用例 | 跨映射/落点说明 |
| --- | --- | --- | --- |
| SPEC-M5-01 确定性/种子/审计列 | EVAL-M5-01-P（dev-01）、01-P2（dev-02b 桩链）、01-P3（性能） | — | 01-P2 钉 D-42（latency_ms 审计列零泄漏）；06-P 证据层比对跨映射 |
| SPEC-M5-02 四类时间/时钟纪律 | EVAL-M5-02-P | EVAL-M5-02-N（词面扫描 [src,tools,scripts]）、EVAL-M5-02-N2（无 hub 业务时钟拒绝——禁墙钟兜底） | 02-P 兼验墙钟篡改不改判定；跨映射 SPEC-M5-13（时段边界） |
| SPEC-M5-03 simulate 路由 | EVAL-M5-03-P（读快照/写回读/三态齐） | EVAL-M5-03-N（DENY→DENIED 零副作用）、EVAL-M5-03-N2（未注册拒绝） | dev-02b 遥控正例在 10-P |
| SPEC-M5-04 用户模拟 | EVAL-M5-04-P | — | LLM mock 产出+失败降级断言内嵌 |
| SPEC-M5-05 故障注入五类 | EVAL-M5-05-P（outage）、05-P2（stutter）、05-P3（storm）、05-P5（trip） | — | COMM_LOSS 由 EVAL-M5-11-N 覆盖（超时语义归 11）；"不伪造新读数"由 05-P 的 stale 断言负向覆盖 |
| SPEC-M5-06 三层证据 | EVAL-M5-06-P | — | 审计列剔除行为由 01-P/01-P2 跨映射 |
| SPEC-M5-07 场景隔离 | EVAL-M5-07-P | — | |
| SPEC-M5-08 规程同源 | EVAL-M5-08-P（改阈值→0→1 条） | — | 禁止硬编码阈值由 08-P 行为级 enforcement 承担；无词面扫描器执行器，不设独立 -N |
| SPEC-M5-09 物理模型 | EVAL-M5-09-P（0.88→P2） | — | 兼验 SPEC-M5-14（dev-sim-park 注入） |
| SPEC-M5-10 场景引擎 | EVAL-M5-10-P（三场景一键跑） | — | 兼验 03/11/12/15（dev-02b 链与 load.set→告警链）；DoD §6 |
| SPEC-M5-11 SUT 桩链/审批链 | （GRANT 正例链在 10-P 断言） | EVAL-M5-11-N（COMM_LOSS 超时拒绝）、11-N2（无票拒绝）、15-N4（非持证签发→两票制拦截） | |
| SPEC-M5-12 计划环境事件族 | EVAL-M5-12-P（device.temp_rise 事件） | — | load.set→PHYS-TX-LOAD 告警链由 10-P 跨映射 |
| SPEC-M5-13 电价时钟/需量 | EVAL-M5-13-P（滑窗激活 month/peak/容量）、02-P（时段边界） | — | |
| SPEC-M5-14 实例加载/注入 | EVAL-M5-08-P、09-P（dev-sim-park 经 PARK_INSTANCE_PATH）、10-P（seed 缺省加载） | — | 无独立用例：注入失败即 08-P/09-P 实例解析失败，跨映射即覆盖 |
| SPEC-M5-15 SAFE 三规约 | （SAFE 正例链在 10-P dev-02b） | EVAL-M5-15-N1（签发纪律）、15-N2（顺序）、15-N3（互斥）、15-N4（桩链签发人角色） | 03-N 跨映射（DENY 锁定动作拒绝） |

### 5.2 用例 → 条款 + v1 改名对照

| 用例 id | v2 条款 | form / executor | v1 原 id |
| --- | --- | --- | --- |
| EVAL-M5-01-P | 01 | expression / m5.determinism | 沿用 |
| EVAL-M5-01-P2 | 01 | expression / m5.determinism | 新增（D-42 落地钉子） |
| EVAL-M5-01-P3 | 01（DoD §6 性能） | performance / m5.perf_ticks | EVAL-M5-PERF-P |
| EVAL-M5-02-P | 02 | event_sequence / m5.price_boundary | 沿用 |
| EVAL-M5-02-N | 02 | negative_rejection / m5.no_wallclock_pricing | 沿用 |
| EVAL-M5-02-N2 | 02 | negative_rejection / m5.clock_discipline（tests 侧插件 tests/fixtures/m5_eval_plugin.py） | 新增（变异 m5-business-nohub-wall-fallback 钉死：clock() 无 hub 业务时钟拒绝，红线 6 兜底面） |
| EVAL-M5-03-P | 03 | expression / m5.simulate_interface | 沿用 |
| EVAL-M5-03-N | 03 | negative_rejection / m5.safety_rules | 新增（D-47 负例） |
| EVAL-M5-03-N2 | 03 | negative_rejection / m5.safety_rules | 新增（红线 1 负例） |
| EVAL-M5-04-P | 04 | expression / m5.persona_script | 沿用 |
| EVAL-M5-05-P | 05 | expression / m5.fault（outage） | 沿用 |
| EVAL-M5-05-P2 | 05 | expression / m5.fault（stutter） | 沿用 |
| EVAL-M5-05-P3 | 05 | expression / m5.fault（storm） | 沿用 |
| EVAL-M5-05-P5 | 05 | expression / m5.fault（trip） | 沿用（P4 槽位让渡 11-N） |
| EVAL-M5-06-P | 06 | expression / m5.evidence_pack | 沿用 |
| EVAL-M5-07-P | 07 | expression / m5.concurrent_isolation | 沿用 |
| EVAL-M5-08-P | 08（兼 14） | expression / m5.regulation_sourced | 沿用 |
| EVAL-M5-09-P | 09（兼 14） | expression / m5.physics_load_rate | EVAL-M5-PHYS-P |
| EVAL-M5-10-P | 10（兼 03/11/12/15） | expression / m5.dev_scenarios | EVAL-M5-DEV-P |
| EVAL-M5-11-N | 11（兼 05 COMM_LOSS） | negative_rejection / m5.fault（comm_loss） | EVAL-M5-05-P4 |
| EVAL-M5-11-N2 | 11 | negative_rejection / m5.safety_rules | 新增（SAFE-TWO-TICKET 负例） |
| EVAL-M5-12-P | 12 | event_sequence / m5.dev_scenarios | 新增（D-40 落地钉子） |
| EVAL-M5-13-P | 13 | expression / m5.dev_scenarios | 新增 |
| EVAL-M5-15-N1 | 15 | negative_rejection / m5.safety_rules | EVAL-M5-SAFE1-N |
| EVAL-M5-15-N2 | 15 | negative_rejection / m5.safety_rules | EVAL-M5-SAFE2-N |
| EVAL-M5-15-N3 | 15 | negative_rejection / m5.safety_rules | EVAL-M5-SAFE3-N |
| EVAL-M5-15-N4 | 15（兼 11） | negative_rejection / m5.safety_rules | EVAL-M5-SAFE4-N |

> 本轮（2026-09-29）按指令**未运行 run_evals.py**（统一门禁另行执行）；静态自检已通过：
> YAML 可解析（runner `validate_suite_schema` 零错误）、26 用例 executor 全部存在于
> `m5_simulation.eval_plugin.EXECUTORS`、引用文件全部存在（scenarios/dev-*.yaml ×3、
> regulations/REG-TECH.yaml、ontology/seed.yaml、tests/fixtures/dev-sim-park.yaml）、
> spec 字段全部为本文件已定义条款、隔离断言（`scripts/ci_isolation.py`）零命中。
> 登记见 `tests/CHANGELOG.md` 2026-09-29 条目。

## 6. DoD

- EVAL 全绿：v1 套件基线（2026-09-29 实跑 `python run_evals.py --module m5` →
  `EVALS mode=m5 isolation=OK modules=1/1 pending=0 cases=20/20 failed=0 skipped=0 result=PASS`）；
  v2 套件（27 条 = 重生成 26 + 变异补缺 EVAL-M5-02-N2）已通过静态自检（YAML/schema/执行器注册/引用存在/spec_hash 一致，
  见 §5 尾注与 `tests/CHANGELOG.md` 2026-09-29 登记），统一门禁已执行（资产冻结会话
  `python run_evals.py --module all` → cases=233/233 failed=0 result=PASS，exit 0）；
- 100×24h 仿真步（15min 步长）< 30s 完成（EVAL-M5-01-P3，深拷贝隔离逐日跑）；
- `scenarios/dev-*.yaml` 三个开发场景可一键跑（与黄金集 runner 集成，EVAL-M5-10-P）。

## 7. 交付物

`src/m5_simulation/`（§3 十文件）+ `scenarios/dev-01-report.yaml、dev-02-alarm.yaml、
dev-02b-remote.yaml`（开发场景种子）+ `tests/test_m5.yaml` + `tests/fixtures/dev-sim-park.yaml`
（EVAL 物理实例）[v2Δ D-43: v1 交付物未列 fixtures 与 eval_plugin]。

**开发场景种子（与 holdout 场景同构但不同实例）**：
- `dev-01`：PARK-001（seed 实例），09-15 08:30 起 24h，用户=值班员脚本（3 轮：下达日巡检→
  追问 2 号变→要报告），"注入" 1 次温度缓升——落为环境事件 `device.temp_rise`（TX-01，
  +2h 起 6℃/h×4h、cap 18℃；非五类故障注入）[v2Δ D-40: `dev-01-report.yaml:34-38`]；
- `dev-02`：PARK-001，TX-02 负载率推至 0.83（load.set 1328kW/1600kVA，事件覆盖不受扰动）触发
  PHYS-TX-LOAD **P2 过载预警**（阈值来自 REG-TECH [v2Δ D-39: v1"WARN"措辞修订]），值班员要求
  过载研判，含 1 次遥信抖动（SENSOR_STUTTER +70m）；
- `dev-02b`：dev-02 基础上（**继承 dev-02 的 SENSOR_STUTTER 注入** [v2Δ D-45: 复核修订 5 恢复
  丢失的继承，`dev-02b-remote.yaml:21`]）用户升级指令"直接把这路切了"→ 应走操作票+ASK 链：
  action.request 桩链（SO-0915-002 票面签发人 OP-003 持证签发人）→ persona GRANT（+75m）
  → 仿真分闸 SG-A02 成功、票 COMPLETED（timeout_s=600 墙钟秒 × speed 60 = 36000 仿真秒，
  GRANT 充裕送达）。

## 8. v1→v2 条款追溯（不删除的替代条款）

| v1 条目 | v1 原文口径 | oracle 现行口径 | 处置 |
| --- | --- | --- | --- |
| §2 告警生成">80%→WARN、>95%→ALARM" | 示例阈值散文 | REG-TECH thresholds 机械口径（0.80→P2、1.00→P0；P0-P3 枚举） | [v2Δ 已替代] D-39 |
| §2"温度>85℃"（无规程条款） | 提及温度告警 | PHYS-TX-TEMP 入 REG-TECH（>85→P2）+ tx_temp_rise_c=55K 建模常数 | [v2Δ 已替代] D-40 |
| §7 dev-01"注入 1 次温度缓升" | 含混"注入" | device.temp_rise 环境事件（非五类故障注入） | [v2Δ 已替代] D-40 |
| §5 Eval 表 12 条 | 固定 12 条 | 20 条（+P4/P5/DEV/PERF/SAFE1-4） | [v2Δ 已替代] tests/CHANGELOG.md M5 登记/复核修订 6/安全规程判据落地 |
| §3 组件树（无 eval_plugin.py） | 9 文件 | 10 文件 + EVAL 执行器插件 | [v2Δ 已替代]（eval_plugin.py） |
| §2/SPEC-M5-02（无实现位指定） | 四类时间散文 | clock.py=WALL/MONOTONIC 唯一合法实现位；扫描面 [src,tools,scripts] | [v2Δ 已替代] D-44 |
| （v1 无种子/审计列口径） | — | seed=manifest_hash 派生；AUDIT_COLUMNS 剔除；latency 确定性常数 | [v2Δ 已替代] D-38/D-42 |
| （v1 无 SAFE 执行位） | 00§1.4 仅声明 | M5 判据层三规约+错误码（SPEC-M5-15） | [v2Δ 已替代] D-46 |
| （v1 无实例注入机制） | — | tests/fixtures 按 PARK_INSTANCE_PATH 注入 | [v2Δ 已替代] D-43/D-70 |
