# 00 · 园区配电运维本体论（开发版 v1.0）

> 本文件是智能体的领域语义层唯一权威源（Single Source of Truth）。
> 实现约束：全部对象/关系/动作/规则以 YAML 加载（`ontology/` 目录），运行期只读；变更走 Registry 变更评审（见 M7）。
> 本体文件与代码分离：`ontology/*.yaml`，由 M4 加载。

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

**B. 环境传感（Sensor）**：`TempHumiditySensor` / `WaterLeakSensor` / `SmokeSensor` / `PDSensor`（局放）/ `IRCamera`（红外测温）

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
| `LoadCurve` | device_ref|park, points[]（ts, kw）, granularity |
| `Bill` | month, energy_kwh, demand_charge, energy_charge, pf_bonus |

**F. 空间与人员**：`Park` / `SubstationRoom`（含 name, address, sensors） / `Feeder`（进线/母线/出线归属） / `Circuit`（回路，挂接 Panel） / `Operator`（人员，role: 值班员/调度员/签发人/审批人，权限集）

### 1.2 关系（Relation Types）

| 关系 ID | 语义 | 域 → 值域 | 基数 |
| --- | --- | --- | --- |
| `connected_to` | 电气连接（设备→母线） | Equipment → Bus | N:1 |
| `part_of` | 空间/结构包含 | Equipment→SubstationRoom; SubstationRoom→Park; Circuit→Feeder | N:1 |
| `monitors` | 传感/量测绑定 | Sensor,Measurement → Equipment | N:1 |
| `upstream_of` | 供电方向 | Equipment|Feeder → Equipment|Feeder | 有向链 |
| `raised_by` | 告警溯源 | Alarm → Equipment|Sensor | N:1 |
| `responds_to` | 工单/操作票响应 | WorkOrder,SwitchOrder → Alarm|GridEvent | N:1 |
| `operated_by` | 操作票执行对象 | SwitchOrder → Equipment | N:N(步骤级) |
| `schedules` | 检修计划绑定 | MaintenancePlan → Equipment | N:1 |
| `owned_by` | 责任归属 | Equipment|Feeder → Operator | N:1 |
| `tariff_applies` | 电价适用 | PriceSchedule → Park | N:1 |
| `metered_at` | 计量点 | LoadCurve|DemandRecord → Feeder|Park | N:1 |

**查询模式（M4 必须支持的三跳查询）**：
- `告警→设备→母线→同母线设备`（影响面分析）
- `负荷→回路→变压器→容量约束`（过载研判）
- `工单→告警→设备→检修计划→下次检修`（消缺闭环）

### 1.3 动作（Action Types）

按风险分级注册（Policy 三值判定依据）：

| 动作 ID | 语义 | 风险级 | 可逆 | 缺省 Policy |
| --- | --- | --- | --- | --- |
| `query.measurement` | 读量测 | 低 | — | ALLOW |
| `query.asset` | 查台账 | 低 | — | ALLOW |
| `query.regulation` | 检索规程 | 低 | — | ALLOW |
| `analyze.load_forecast` | 负荷预测 | 低 | — | ALLOW |
| `analyze.power_quality` | 电能质量分析 | 低 | — | ALLOW |
| `analyze.transformer_economy` | 变压器经济运行 | 低 | — | ALLOW |
| `analyze.demand_forecast` | 需量预测 | 低 | — | ALLOW |
| `write.report` | 生成报告 Artifact | 低 | 是（可归档） | ALLOW |
| `create.work_order` | 创建工单 | 中 | 是（可撤销） | ALLOW |
| `create.switch_order` | 创建操作票（**≠执行**） | 中 | 是 | ALLOW |
| `create.inspection_record` | 登记巡检记录 | 中 | 是 | ALLOW |
| `execute.remote_control` | 遥控分/合闸 | **高** | **否** | **ASK（永久）** |
| `execute.capacitor_switch` | 电容投切 | 高 | 是 | ASK |
| `modify.protection_setting` | 修改保护定值 | **极高** | 否 | **DENY（永久）** |
| `modify.asset_history` | 改台账历史 | 极高 | 否 | **DENY（永久）** |
| `bypass.approval` | 绕过审批 | 极高 | 否 | **DENY（永久）** |

### 1.4 规则（Rule Types）

**R-物理约束**（每条含：约束表达式 + 判定量测 + 越限告警级别）

| 规则 ID | 条款 | 判据 | 越限级别 |
| --- | --- | --- | --- |
| `PHYS-TX-LOAD` | 变压器负载率 ≤ 80%（重过载 >100% 跳闸风险） | load_rate = P/capacity | 80%→P2; 100%→P0 |
| `PHYS-V-RANGE` | 母线电压合格范围 ±7% | U/Un | ±5%→P3; ±7%→P2 |
| `PHYS-THD` | 电压 THD ≤ 5%（GB/T 14549 口径，虚拟条款 R-THD-01） | THD | 5%→P3; 8%→P2 |
| `PHYS-PF` | 功率因数 ≥ 0.90（考核） | cosφ | <0.90→P3 |
| `PHYS-DEMAND` | 需量 ≤ 合同容量 × 1.05 | 月最大需量/合同容量 | >1.0→P2; >1.05→P0 |
| `PHYS-BESS-SOC` | SOC 运行区间 10%-90% | soc | 越界→P2 |

**R-安全规程**（虚拟规程文件 `regulations/REG-SAFE.yaml`，条款编号可被 agent 引用）

| 规则 ID | 条款 |
| --- | --- |
| `SAFE-TWO-TICKET` | 任何遥控操作前必须存在状态=已签发的 SwitchOrder（两票制） |
| `SAFE-ISSUE-HUMAN` | 操作票签发人必须是 `Operator.role ∈ {签发人}`，**签发动作不属于任何 agent 动作集** |
| `SAFE-ORDER-SEQ` | 操作步骤必须按 SwitchOrder.steps 声明顺序执行，不得跳步 |
| `SAFE-MAINTAIN-ISO` | 检修作业设备必须处于检修状态且有 WorkTicket（含许可） |
| `SAFE-SINGLE-OP` | 每张操作票同一时刻只有一个执行流（互斥） |

**R-经营规则**（虚拟规程 `regulations/REG-COMM.yaml`）

| 规则 ID | 条款 |
| --- | --- |
| `COMM-TARIF-SYNC` | 电价判断以 PriceSchedule 当前生效版本为准；跨版本边界以 effective_range 判定 |
| `COMM-PF-BONUS` | cosφ ≥ 0.95 月度电费奖励，0.90-0.95 无奖罚（虚拟条款 R-PF-02） |
| `COMM-DEMAND-CHARGE` | 基本电费按月最大需量与合同容量孰大计（虚拟条款 R-DC-01） |
| `COMM-TOU-ARBITRAGE` | 储能充放策略只允许引用已生效 PriceSchedule 时段 |

**R-授权规则**（写死在 Policy，禁止 agent 读写）
- 动作 1.3 表的缺省 Policy 即授权规则；`execute.remote_control` 的 ASK 不可被任何角色改为 ALLOW（含审批人）——审批只放行"本次"，不改缺省值。

---

## 2. 受控词表（枚举，全部封闭集）

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

---

## 3. 种子实例（`ontology/seed.yaml`，开发与验收共用此实例；holdout 场景使用 §5 的独立变体实例）

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
        - {id: CB-A, type: CapacitorBank, capacity_kvar: 300, state: OFF}
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

---

## 4. 本体覆盖率监测（M4 输出）

每轮 Context 注入后记录：`concept_hits / concept_total`（当日任务涉及概念中已在本体注册的比例）。低于 70% 告警（写入飞轮 Badcase 候选）。覆盖率月报进 Registry。

## 5. Holdout 专用变体实例（仅供 HOLDOUT.md 引用，禁止进入开发/调优数据）

`PARK-002`：与种子同构的独立实例——TX-04/TX-05 各 1250kVA、BESS-02 300kWh/150kW、PV-02 300kWp、EVC-02 360kW、TARIFF-2026B（谷 00:00-07:00/平 07:00-09:00/峰 09:00-11:30/平 11:30-19:00/峰 19:00-22:00/平 22:00-24:00，价 0.32/0.65/1.05/0.65/1.05/0.65）、合同容量 1800kW、9 月需量 1650kW、负荷形状系数不同。完整定义见 `HOLDOUT.md` 附录。

