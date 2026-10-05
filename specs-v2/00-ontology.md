# 00 · 园区配电运维本体论（v2.0）

> 本文件是智能体的领域语义层唯一权威源（Single Source of Truth）。
> 实现约束：全部对象/关系/动作/规则以 YAML 加载（`ontology/` 目录），运行期只读；变更走 Registry 变更评审（见 M7）。
> 本体文件与代码分离：`ontology/*.yaml`，由 M4 加载。
>
> **v2 重生成说明（资产工程阶段）**：本文件由 v1（`specs/00-ontology.md` v1.0）按 **oracle（唯一事实源）**
> 重生成——oracle = `ontology/*.yaml` 与 `regulations/*.yaml` 的实际内容（机器可读版即权威落盘）。
> 结构与 v1 保持同节编号便于 diff；**每处与 v1 的差异加行内标记 `[v2Δ: 偏差依据 evidence]`**，
> 未标记部分与 v1 语义一致。v1 未实现却已被 oracle 替代的条款以「[v2Δ 已替代]」保留追溯（§7）。

---

## 1. 四要素模型

对象（是什么）→ 关系（有什么联系）→ 动作（能做什么）→ 规则（应遵循什么）。

### 1.1 对象（Object Types）

**A. 电气设备（Equipment）**

| 类型 ID | 中文名 | 关键属性 | 量测绑定 |
| --- | --- | --- | --- |
| `Transformer` | 配电变压器 | capacity_kva, load_rate, cooling, winding_temp | U/I/P/Q/cosφ/温度 |
| `Switchgear` | 高压开关柜 | rated_a, breaker_state, protection_setting_ref | 分/合状态、局放 |
| `Bus` | 母线 | voltage_level, connected_devices | U/f |
| `Cable` | 电力电缆 | length_m, spec, insulation | 温度/局放 |
| `CapacitorBank` | 无功补偿装置 | capacity_kvar, state(投/切), auto_mode | Q/cosφ/THD |
| `APF` | 有源滤波器 | rated_a, filter_state | THD/各次谐波 |
| `BESS` | 储能系统 | capacity_kwh, power_kw, soc, charge_state | SOC/P/Q |
| `PV` | 光伏系统 | capacity_kwp, output_kw | P/Q |
| `EVCharger` | 充电桩群 | total_power_kw, session_count | P |
| `Panel` | 低压配电柜 | circuits | U/I/P/Q |

**B. 环境传感（Sensor）**：`TempHumiditySensor`（温湿度）/ `WaterLeakSensor`（水浸）/ `SmokeSensor`（烟感）/ `PDSensor`（局放）/ `IRCamera`（红外测温）

**C. 运行对象（Operational）**

| 类型 ID | 属性 |
| --- | --- |
| `Measurement` | device_ref, quantity, value, unit, quality, ts |
| `Alarm` | level(P0-P3), source_ref, code, text, raised_at, cleared_at, ack_by |
| `GridEvent` | type(开关变位/越限/保护动作/通信中断), subject_ref, ts, detail |
| `OperatingState` | device_ref, state(运行/检修/热备/冷备/故障), since |

**D. 管理对象（Administrative）**

| 类型 ID | 属性 |
| --- | --- |
| `WorkOrder` | code, type(消缺/检修/巡检), status, priority, related_alarm, assignee |
| `SwitchOrder`（操作票） | code, steps[](操作序列), status, issuer(签发人), executor, guard_check |
| `WorkTicket`（工作票） | code, permit_type, status, issuer, receiver |
| `InspectionRecord` | route, items[](设备/部位/方法/结果), inspector, ts |
| `MaintenancePlan` | device_ref, cycle, next_due, last_done, items |
| `AssetRecord`（台账） | device_ref, model, vendor, commission_date, history |

**E. 经营对象（Commercial）**

| 类型 ID | 属性 |
| --- | --- |
| `PriceSchedule` | tariff_id, periods[]（start/end/type[尖/峰/平/谷]/price）, effective_range |
| `DemandRecord` | month, peak_kw, contract_capacity_kw, over_threshold(1.05) |
| `LoadCurve` | device_ref\|park, points[]（ts, kw）, granularity |
| `Bill` | month, energy_kwh, demand_charge, energy_charge, pf_bonus |

**F. 空间与人员**

| 类型 ID | 属性 |
| --- | --- |
| `Park` | id, name, tariff, contract_capacity_kw |
| `SubstationRoom`（配电房） | name, address, sensors |
| `Feeder`（馈线） | （进线/母线/出线归属） |
| `Circuit`（回路） | （挂接 Panel） |
| `Operator`（运维人员） | id, name, role(值班员/调度员/签发人/审批人), permissions（权限集） |

[v2Δ: F 组按 `ontology/objects.yaml` space_and_personnel 补全为逐类型属性表——v1 为行内散文，
`Park` 的属性列（id/name/tariff/contract_capacity_kw）为 objects.yaml 实有内容]

### 1.2 关系（Relation Types）

| 关系 ID | 语义 | 域 → 值域 | 基数 |
| --- | --- | --- | --- |
| `connected_to` | 电气连接（设备→母线） | Equipment → Bus | N:1 |
| `part_of` | 空间/结构包含 | Equipment→SubstationRoom; SubstationRoom→Park; Circuit→Feeder | N:1 |
| `monitors` | 传感/量测绑定 | Sensor,Measurement → Equipment | N:1 |
| `upstream_of` | 供电方向 | Equipment\|Feeder → Equipment\|Feeder | 有向链 |
| `raised_by` | 告警溯源 | Alarm → Equipment\|Sensor | N:1 |
| `responds_to` | 工单/操作票响应 | WorkOrder,SwitchOrder → Alarm\|GridEvent | N:1 |
| `operated_by` | 操作票执行对象 | SwitchOrder → Equipment | N:N(步骤级) |
| `schedules` | 检修计划绑定 | MaintenancePlan → Equipment | N:1 |
| `owned_by` | 责任归属 | Equipment\|Feeder → Operator | N:1 |
| `tariff_applies` | 电价适用 | PriceSchedule → Park | N:1 |
| `metered_at` | 计量点 | LoadCurve\|DemandRecord → Feeder\|Park | N:1 |

**查询模式（M4 必须支持的三跳查询，`ontology/relations.yaml` query_patterns，模式声明 hops=3）**：

| 模式 ID | 名称 | 路径 |
| --- | --- | --- |
| `alarm_impact` | 告警影响面分析 | 告警→设备→母线→同母线设备 |
| `overload_analysis` | 过载研判 | 负荷→回路→变压器→容量约束 |
| `defect_closure` | 消缺闭环 | 工单→告警→设备→检修计划→下次检修 |

[v2Δ D-35: 补跳数计数口径——**属性拾取步不计关系跳数**：过载研判模式声明 hops=3，路径关系跳数=2
（LoadCurve -metered_at-> Feeder -upstream_of(in)-> Transformer + 属性拾取 capacity_kva；
`src/m4_semantic/graph.py`；tests/CHANGELOG.md M4 登记 4）；query_patterns 三模式 ID 为
relations.yaml 实有登记]

### 1.3 动作（Action Types）

按风险分级注册（Policy 三值判定依据）。表以 `ontology/actions.yaml` 为权威落盘
（16 条；`risk_level` 映射 contracts.RiskLevel；`policy_locked: true` 表示缺省值系统级不可覆盖，
为 M3 不可改清单的数据源；reversible 布尔——v1 可逆列 "—" 的只读动作取 false）。
[v2Δ D-27: v1 无 policy_locked 列与 reversible 布尔口径；actions.yaml 头注与
`src/contracts/eval_plugin.py:36-53` EXPECTED_ACTIONS 断言（含风险级/可逆性/缺省 Policy/不可改标记）；
tests/CHANGELOG.md M3 登记 4]

| 动作 ID | 语义 | 风险级 | 可逆 | 缺省 Policy | policy_locked |
| --- | --- | --- | --- | --- | --- |
| `query.measurement` | 读量测 | LOW | 否（"—"） | ALLOW | false |
| `query.asset` | 查台账 | LOW | 否（"—"） | ALLOW | false |
| `query.regulation` | 检索规程 | LOW | 否（"—"） | ALLOW | false |
| `analyze.load_forecast` | 负荷预测 | LOW | 否（"—"） | ALLOW | false |
| `analyze.power_quality` | 电能质量分析 | LOW | 否（"—"） | ALLOW | false |
| `analyze.transformer_economy` | 变压器经济运行 | LOW | 否（"—"） | ALLOW | false |
| `analyze.demand_forecast` | 需量预测 | LOW | 否（"—"） | ALLOW | false |
| `write.report` | 生成报告 Artifact | LOW | 是（可归档） | ALLOW | false |
| `create.work_order` | 创建工单 | MEDIUM | 是（可撤销） | ALLOW | false |
| `create.switch_order` | 创建操作票（**≠执行**） | MEDIUM | 是 | ALLOW | false |
| `create.inspection_record` | 登记巡检记录 | MEDIUM | 是 | ALLOW | false |
| `execute.remote_control` | 遥控分/合闸 | HIGH | 否 | **ASK（永久）** | **true** |
| `execute.capacitor_switch` | 电容投切 | HIGH | 是 | ASK | false |
| `modify.protection_setting` | 修改保护定值 | CRITICAL | 否 | **DENY（永久）** | **true** |
| `modify.asset_history` | 改台账历史 | CRITICAL | 否 | **DENY（永久）** | **true** |
| `bypass.approval` | 绕过审批 | CRITICAL | 否 | **DENY（永久）** | **true** |

配套工具适配器（M3）：一动作一模块（`tools/<动作 ID 的 "."→"__">.py`，16 个 + `_base.py` 公共约定）；
参数 schema/幂等键策略/披露面来自适配器声明，风险/缺省 Policy 来自本表（数据权威，装配即断言 diff 空）。
[v2Δ D-27: v1 无适配器布局约定；tests/CHANGELOG.md M3 登记 4]

### 1.4 规则（Rule Types）

规则 ID 注册表=`ontology/rules.yaml`（16 条，4 类目）；各类目条款全文落盘于 `regulations/*.yaml`，
**判据/阈值唯一来源=规程文件**（M5 告警引擎只读 REG-TECH thresholds，仿真代码零硬编码阈值）。
[v2Δ D-39: 补同源纪律成文——v1 M5 §2 示例口径（">80%→WARN、>95%→ALARM"）与 REG-TECH 不符，
以规程文件为准（`src/m5_simulation/alarm_engine.py:13-14,53-57`；`regulations/REG-TECH.yaml`）；
tests/CHANGELOG.md M5 登记 2]

**R-物理约束**（`regulations/REG-TECH.yaml`，7 条款 [v2Δ D-40: PHYS-TX-TEMP 为 oracle 新增条款]；
判据列与 rules.yaml 同 ID 条款一致）

| 规则 ID | 条款 | 判定 metric | 越限级别（REG-TECH thresholds） |
| --- | --- | --- | --- |
| `PHYS-TX-LOAD` | 变压器负载率 ≤ 80%（重过载 >100% 跳闸风险） | load_rate = P/capacity | >0.80→P2 过载预警；>1.00→P0 重过载跳闸风险 |
| `PHYS-V-RANGE` | 母线电压合格范围 ±7% | voltage_deviation = (U−Un)/Un（绝对值判定） | ≥0.05→P3；≥0.07→P2 |
| `PHYS-THD` | 电压 THD ≤ 5%（GB/T 14549 口径，虚拟条款 R-THD-01） | thd_u | >0.05→P3；>0.08→P2 |
| `PHYS-PF` | 功率因数 ≥ 0.90（考核） | power_factor（Feeder） | <0.90→P3 |
| `PHYS-DEMAND` | 需量 ≤ 合同容量 × 1.05 | demand_ratio（15min 滑窗月最大值） | >1.0→P2 需量预警；>1.05→P0 需量越限 |
| `PHYS-BESS-SOC` | SOC 运行区间 10%-90% | soc（百分数口径） | <10→P2；>90→P2 |
| `PHYS-TX-TEMP` | 变压器绕组温度 > 85℃ 越限（M5 §2 告警生成口径） | winding_temp_c（℃；环境温度+满载温升×负载率+事件漂移） | >85→P2 绕组温度越限 |

[v2Δ D-40: dev-01"温度缓升注入"落为环境事件 `device.temp_rise`（五类故障注入不含温度类，按 00§1.1
量测事件语义）；配套新增 PHYS-TX-TEMP 条款 + 物理常数 `tx_temp_rise_c`=55K（顶油温升建模常数非阈值，
正常负载 ≈73℃ 不误报；实测 86.9℃ 触发 P2）（`regulations/REG-TECH.yaml:86-96`；
`src/m5_simulation/scenario.py:522-532`；`src/m5_simulation/physics.py:35`；
`scenarios/dev-01-report.yaml:36`；tests/CHANGELOG.md M5 登记 3+复核修订 2；commit fad0e10）]

**R-安全规程**（`regulations/REG-SAFE.yaml`，5 条款）

| 规则 ID | 条款 |
| --- | --- |
| `SAFE-TWO-TICKET` | 任何遥控操作前必须存在状态=已签发的 SwitchOrder（两票制） |
| `SAFE-ISSUE-HUMAN` | 操作票签发人必须是 `Operator.role ∈ {签发人}`，**签发动作不属于任何 agent 动作集**（agent 不得签发、不得代签） |
| `SAFE-ORDER-SEQ` | 操作步骤必须按 SwitchOrder.steps 声明顺序执行，不得跳步 |
| `SAFE-MAINTAIN-ISO` | 检修作业设备必须处于检修状态且有 WorkTicket（含许可） |
| `SAFE-SINGLE-OP` | 每张操作票同一时刻只有一个执行流（互斥） |

**R-经营规则**（`regulations/REG-COMM.yaml`，4 条款）

| 规则 ID | 条款 |
| --- | --- |
| `COMM-TARIF-SYNC` | 电价判断以 PriceSchedule 当前生效版本为准；跨版本边界以 effective_range 判定 |
| `COMM-PF-BONUS` | cosφ ≥ 0.95 月度电费奖励，0.90-0.95 无奖罚（虚拟条款 R-PF-02） |
| `COMM-DEMAND-CHARGE` | 基本电费按月最大需量与合同容量孰大计（虚拟条款 R-DC-01） |
| `COMM-TOU-ARBITRAGE` | 储能充放策略只允许引用已生效 PriceSchedule 时段 |

**R-运维操作规程**（`regulations/REG-OP.yaml`，5 条款；ADDENDUM §A 要求的最小条款集，条款文字自拟，
parent 从属 REG-SAFE/本文件规则 ID）
[v2Δ D-67: v1 00 无 REG-OP 目录；oracle 五个规则 ID 全部落盘（`regulations/REG-OP.yaml` 全文核对；
specs/ADDENDUM.md:13-18）——本节为 REG-OP 目录转正]

| 规则 ID | 标题 | parent | 要点 |
| --- | --- | --- | --- |
| `SAFE-OP-TWO-TICKET` | 两票操作实施细则 | SAFE-TWO-TICKET | 一票一任务；ISSUED 方可 EXECUTING；执行前监护核对（guard_check）；现场状态不符立即中止上报；完成后 BUSINESS 时钟记录完成时间 |
| `SAFE-OP-REMOTE` | 遥控操作细则 | SAFE-ORDER-SEQ, SAFE-SINGLE-OP | 逐条按 steps 顺序、不跳步不并发；上步回读确认前不发下步；结果以环境回读为准（自报成功回读未变=失败）；被拒后不得变体绕行重试 |
| `SAFE-OP-MAINTAIN` | 检修作业细则 | SAFE-MAINTAIN-ISO | 作业前 OperatingState 置 MAINTENANCE；持含许可 WorkTicket；隔离范围遥控作业期禁止；结束后值班员确认恢复并关闭工票 |
| `OP-QCOMP-CAP` | 无功补偿电容投切操作要求 | —（operation） | 单次投切均须审批（缺省 ASK）；投切前确认无故障标志+读数新鲜；两次投切留放电间隔；投切后回读 state/Q/cosφ；手动投切退出 auto_mode |
| `OP-DEMAND-LIMIT` | 需量限额与预警 | —（operation） | ratio>1.0→P2 预警（启动负荷优化与储能响应）；>1.05→P0 越限（立即控制+上报）；判据与 PHYS-DEMAND 同源（阈值变更只允许改 REG-TECH）；跨月发布 `demand.month_rolled`（冻结 frozen_peak_kw 后重置） |

（OP-DEMAND-LIMIT criteria：metric=demand_ratio，warn_over 1.0→P2、breach_over 1.05→P0，
与 PHYS-DEMAND 同源。）

**R-授权规则**（`ontology/rules.yaml` category=authorization，1 条款）
[v2Δ: rules.yaml 将 R-授权规则亦注册为规则 ID `AUTH-ACTION-DEFAULT-POLICY`——v1 仅散文声明；
物理/安全/经营三 category 的规则集由 EVAL `contracts.rules_registry` 断言]

- `AUTH-ACTION-DEFAULT-POLICY`：动作缺省 Policy 即授权规则（见 §1.3 表）；`execute.remote_control` 的 ASK 不可被任何角色改为 ALLOW（含审批人）——审批只放行"本次"，不改缺省值。

---

## 2. 受控词表（枚举，全部封闭集）

以 `ontology/enums.yaml` 为权威落盘（11 组封闭集；与 `src/contracts/enums.py` CONTROLLED_VOCABULARY
同源，一致性由 EVAL 用例 `contracts.enum_closure` 断言）：

```yaml
enums:
  alarm_level: [P0, P1, P2, P3]           # P0=紧急(5min 响应) P1=重要(30min) P2=一般(4h) P3=提示(24h)
  task_status: [CREATED, RUNNING, WAITING_INPUT, WAITING_APPROVAL, WAITING_EVENT,
                PAUSED, VERIFYING, COMPLETED, FAILED, CANCELLED]
  action_status: [REQUESTED, POLICY_DECIDED, WAITING_APPROVAL, EXECUTING,
                  SUCCEEDED, FAILED, REJECTED, DENIED, COMPENSATED]
  artifact_status: [DRAFT, VALIDATING, READY, PUBLISHED, REJECTED, ARCHIVED, DELETED]
  device_state: [RUNNING, MAINTENANCE, HOT_STANDBY, COLD_STANDBY, FAULT]
  work_order_status: [OPEN, ASSIGNED, IN_PROGRESS, PENDING_VERIFY, CLOSED, CANCELLED]
  switch_order_status: [DRAFT, ISSUED, EXECUTING, COMPLETED, CANCELLED]
  price_period_type: [PEAK, SHARP, FLAT, VALLEY]
  memory_type: [WORKING, EPISODIC, SEMANTIC, PROCEDURAL]
  risk_level: [LOW, MEDIUM, HIGH, CRITICAL]
  policy_decision: [ALLOW, ASK, DENY]
```

（01 v1 §5.2 的 `DENYED` 笔误终态即按本表 `DENIED` 枚举落定——01 v2 §5.2 已修正
[v2Δ D-01: `src/contracts/enums.py:83`；tests/CHANGELOG.md S0 登记 1]。）

---

## 3. 种子实例（`ontology/seed.yaml`，开发与验收共用此实例；holdout 场景使用 §5 的独立变体实例）

实例加载协议 [v2Δ D-70: ADDENDUM §D——按 `ScenarioSpec.environment.park_instance` 名称解析同构实例
文件（去扩展名匹配 .yaml/.yml）；默认搜索 `ontology/`，环境变量 `PARK_INSTANCE_PATH`（分隔符 ";"）
追加目录；M4 loader 与 M5 env 同一机制，对任意同构实例通用，EVAL 经 `tests/fixtures/` 注入验证
（`src/m4_semantic/loader.py:63-64,181-198`；tests/CHANGELOG.md M4 登记 1+M5 登记 7）]：

```yaml
park:
  id: PARK-001
  name: 示范园区
  tariff: TARIFF-2026A
  contract_capacity_kw: 2000
  substations:
    - id: SR-A
      name: A 配电房
      devices:
        - {id: TX-01, type: Transformer, capacity_kva: 1600, cooling: ONAN}
        - {id: TX-02, type: Transformer, capacity_kva: 1600, cooling: ONAN}
        - {id: BUS-A1, type: Bus, voltage_level: 10kV}
        - {id: BUS-A2, type: Bus, voltage_level: 0.4kV}
        - {id: SG-A01, type: Switchgear, breaker_state: CLOSED}
        - {id: SG-A02, type: Switchgear, breaker_state: CLOSED}
        - {id: CB-A, type: CapacitorBank, capacity_kvar: 300, state: "OFF"}
        #                                     ^^^^^^^^^^^ [v2Δ: seed.yaml:25——YAML1.1 裸 OFF 会解析为
        #                                     布尔 False，故加引号保持字符串语义（§1.1 state 投/切）
        - {id: PD-A01, type: PDSensor, target: SG-A01}
        - {id: TH-A01, type: TempHumiditySensor}
    - id: SR-B
      name: B 配电房
      devices:
        - {id: TX-03, type: Transformer, capacity_kva: 1000}
        - {id: BESS-01, type: BESS, capacity_kwh: 500, power_kw: 250, soc: 62}
        - {id: PV-01, type: PV, capacity_kwp: 400}
        - {id: EVC-01, type: EVCharger, total_power_kw: 480}
relations:
  - [TX-01, connected_to, BUS-A1]
  - [TX-02, connected_to, BUS-A1]
  - [TX-03, connected_to, BUS-A1]
  - [BESS-01, part_of, SR-B]
  - [PV-01, part_of, SR-B]
  - [SG-A01, upstream_of, TX-01]
  - [PD-A01, monitors, SG-A01]
operators:
  - {id: OP-001, name: 张工, role: 值班员}
  - {id: OP-002, name: 李工, role: 调度员}
  - {id: OP-003, name: 王工, role: 签发人}
  - {id: OP-004, name: 赵总, role: 审批人}
price_schedule:
  id: TARIFF-2026A
  effective_range: [2026-01-01, 2026-12-31]
  periods:
    - {type: VALLEY, start: "00:00", end: "08:00", price: 0.35}
    - {type: FLAT,   start: "08:00", end: "10:00", price: 0.70}
    - {type: PEAK,   start: "10:00", end: "12:00", price: 1.10}
    - {type: FLAT,   start: "12:00", end: "18:00", price: 0.70}
    - {type: PEAK,   start: "18:00", end: "21:00", price: 1.10}
    - {type: FLAT,   start: "21:00", end: "24:00", price: 0.70}
demand_2026_09: {peak_kw: 1720, month: 2026-09}
load_curve_2026_09:  # 小时粒度日形状（用于生成仿真量测）
  shape: [0.42,0.40,0.38,0.38,0.40,0.44,0.50,0.58,0.68,0.78,0.86,0.90,0.84,0.76,0.80,0.88,0.94,0.98,0.92,0.84,0.72,0.60,0.50,0.44]
  base_kw: 1400
```

（实例完整性由 EVAL `contracts.seed_check` 断言：引用可解析、电价时段覆盖 24h、负荷曲线 24 点。）

---

## 4. 本体覆盖率监测（M4 输出）

每轮 Context 注入后记录：`concept_hits / concept_total`（当日任务涉及概念中已在本体注册的比例）。
**缺失概念比例 ≥30%（即命中率 <70%）产出 `badcase.opened` 候选事件**（EventRecord 经 contracts 校验，
producer=M4，payload.candidate=true）；**事件持久化归 M2/M6，M4 只产出候选**；
任务级报告落 `runtime/coverage/task-<id>.json`；覆盖率月报进 Registry。
[v2Δ D-37: v1 只写"低于 70% 告警（写入飞轮 Badcase 候选）"；oracle 明确候选事件与持久化职责切分
（`src/m4_semantic/coverage.py:28-29,120-135`）；tests/CHANGELOG.md M4 登记 6]

---

## 5. Holdout 专用变体实例（仅供 HOLDOUT.md 引用，禁止进入开发/调优数据）

`PARK-002`：与种子同构的独立实例——TX-04/TX-05 各 1250kVA、BESS-02 300kWh/150kW、PV-02 300kWp、
EVC-02 360kW、TARIFF-2026B（谷 00:00-07:00/平 07:00-09:00/峰 09:00-11:30/平 11:30-19:00/
峰 19:00-22:00/平 22:00-24:00，价 0.32/0.65/1.05/0.65/1.05/0.65）、合同容量 1800kW、9 月需量 1650kW、
负荷形状系数不同。完整定义见 `HOLDOUT.md` 附录（随验收包交付、不进开发仓库——
`scripts/ci_isolation.py` 断言 `PARK-002|TARIFF-2026B|OP-1[0-9]` 零命中
[v2Δ D-44: 隔离正则宽化为 `OP-1[0-9]`（ADDENDUM §F OP-1x 的等宽正则）；
`scripts/ci_isolation.py:31`；tests/CHANGELOG.md 安全规程判据落地 5+独立评审 4]）。

---

## 6. 实体解析数据（`ontology/aliases.yaml`）[v2Δ 新增节：v1 00 无此节；数据文件由 M4 SPEC-M4-02 引入
（别名表以数据文件维护，新增设备零代码），00 为语义权威源故转正收录]

打分模型（顶层分数键，数据可调；loader 逐键数值校验）：

| 分数键 | 值 | 语义 |
| --- | --- | --- |
| `explicit_alias_score` | 1.0 | 显式别名短语命中（最强） |
| `room_ordinal_score` | 0.8 | 房内序号读法（强读法）："N 号<类型>"=某配电房内该类型按 ID 排序的第 N 台——运维口语默认编号读法 |
| `parkwide_ordinal_score` | 0.6 | 全园区尾号读法（弱读法）：设备 ID 数字尾号（id_pattern 的 num 捕获组）恰为 N 即命中 |
| `same_type_fallback_score` | 0.5 | 同类型兜底：文本出现类型词时该（范围房内）类型全部设备为弱候选 |
| `unambiguous_margin` | 0.3 | 消歧阈值：首名与次名分差 ≥ 该值才判无歧义；否则返回候选列表（不擅自择一） |

序号双读法的消歧语义（EVAL-M4-02-P/N 机械依据，对任意同构实例通用）：
"2 号变压器"→房内序号 0.8 命中 TX-02，与弱候选 0.5 分差 0.3 ≥ 0.3 → 唯一消歧；
"3 号变压器"→无任何房拥有第 3 台变压器，仅全园区尾号弱读法 0.6 命中 TX-03，与弱候选分差 0.1 < 0.3
→ 歧义，返回候选列表含理由，不猜。
[v2Δ D-34: `src/m4_semantic/resolver.py:102-105`；tests/CHANGELOG.md M4 登记 2/3]

**范围别名（配电房指称，命中后缩小序号/兜底候选搜索范围；目标不在当前实例时自动忽略）**：
`A 配电房`/`A 房`→SR-A；`B 配电房`/`B 房`→SR-B。

**设备显式别名（强命中；刻意不收录"N 号<类型>"短语——由 generic_ordinal 泛化读法统一处理，
保证新增设备零改动可解析）**：

| 目标 | 别名 |
| --- | --- |
| BUS-A1 | 10kV 母线 / A 段母线 / 高压母线 |
| BUS-A2 | 0.4kV 母线 / 低压母线 |
| CB-A | 无功补偿装置 / 电容补偿 / 补偿电容 |
| BESS-01 | 储能系统 / 储能电站 |
| PV-01 | 光伏系统 / 光伏电站 |
| EVC-01 | 充电桩群 / 充电站 |

**属性词典（中文口语词→本体属性 canonical 名；applies_to 限定对象类型；带 sensor_type 的属性经绑定
关系（缺省 monitors）联动出传感器实体）**：

| canonical | match 词 | applies_to | 联动 |
| --- | --- | --- | --- |
| winding_temp | 温度/绕组温度/线圈温度/温升 | Transformer | — |
| load_rate | 负载率/负载 | Transformer | — |
| capacity_kva | 容量/额定容量/变压器容量 | Transformer | — |
| cooling | 冷却方式/散热方式 | Transformer | — |
| pd | 局放/局部放电 | Switchgear, Cable | sensor_type=PDSensor, binding_relation=monitors |
| breaker_state | 分合状态/分合闸状态/开关状态/断路器状态 | Switchgear | — |
| voltage_level | 电压等级/电压 | Bus | — |
| soc | SOC/荷电状态/电量 | BESS | — |
| charge_state | 充放电状态 | BESS | — |
| output_kw | 出力/发电功率 | PV | — |
| state | 投切状态/投切 | CapacitorBank | — |

**序号泛化（"N 号<类型>"）：type_words 触发词 + id_pattern 提取 ID 尾号（须含 num 捕获组、锚定 `$`
取完整数字尾号，多位编号如 TX-10 不被截断；可选 per-type 覆盖 room_score/parkwide_score）**：

| type_id | type_words | id_pattern |
| --- | --- | --- |
| Transformer | 变压器/主变 | `TX-(?P<num>\d+)$` |
| Switchgear | 开关柜/高压柜/柜 | `SG-[A-Z](?P<num>\d+)$` |
| Bus | 母线 | `BUS-[A-Z](?P<num>\d+)$` |
| CapacitorBank | 电容/无功补偿装置 | `CB-[A-Z]?(?P<num>\d+)$` |
| BESS | 储能/电池 | `BESS-(?P<num>\d+)$` |
| PV | 光伏 | `PV-(?P<num>\d+)$` |
| EVCharger | 充电桩 | `EVC-(?P<num>\d+)$` |

---

## 7. v1→v2 条款追溯（不删除的替代条款）

| v1 条目 | v1 原文口径 | oracle 现行口径 | 处置 |
| --- | --- | --- | --- |
| §1.3 动作表（无 policy_locked 列，可逆列 "—"） | 6 列散文表 | 7 列（risk_level 枚举化 + policy_locked 布尔 + reversible 布尔） | [v2Δ 已替代] D-27 |
| §1.4 R-物理约束（6 条款、级别列"80%→P2"式散文） | 6 条 PHYS-* | REG-TECH 7 条款（+PHYS-TX-TEMP），阈值为 thresholds 机械口径 | [v2Δ 已替代] D-40 |
| §1.4 R-授权规则（仅散文声明） | 写死在 Policy 禁止读写 | rules.yaml 注册 AUTH-ACTION-DEFAULT-POLICY | [v2Δ 已替代]（rules.yaml:80-82） |
| （v1 无 REG-OP） | — | REG-OP 5 条款转正 | [v2Δ 已替代] D-67 |
| §3 种子实例 CB-A `state: OFF` | 裸 OFF（YAML 解析为 False） | `"OFF"` 加引号保持字符串 | [v2Δ 已替代]（seed.yaml:25） |
| §4 覆盖率"低于 70% 告警" | 散文口径 | ≥30% 缺失→badcase.opened 候选事件；持久化归 M2/M6 | [v2Δ 已替代] D-37 |
| （v1 无实体解析数据节） | — | §6 aliases.yaml 转正 | [v2Δ 已替代] D-34 |
| §5 Holdout（grep OP-1xx 描述） | OP-1xx 字样 | 隔离正则 `OP-1[0-9]` | [v2Δ 已替代] D-44 |
