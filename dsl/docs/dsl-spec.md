# ParkDSL v1 · 园区电力系统描述语言规范

> peidian-agent · worker-A 线1 ｜ 版本 parkdsl/1 ｜ 2026-10-01
> 机器可读规范（唯一裁决源）：`dsl/dsl_spec.yaml`；本文是人读规范，冲突时以 `dsl_spec.yaml` + `dsl/validate.py` 实际校验为准。
> 考古兼容：ID 风格沿用 `ontology/seed.yaml`（TX-01/BUS-A1/BESS-01/PV-01/SR-A），本文将其规则化。

## 1. 定案与理由

- **格式定案：YAML**（不再提供 JSON 口径）。理由：① 本仓既有资产（ontology/scenarios/skills/prompts）全 YAML，pyyaml 是唯一运行时依赖；② 允许注释，LLM 生成与人工修订都更可读；③ 与 M5 场景加载协议（ScenarioSpec→park_instance）同构，未来可互换。
- 生成器/校验器：`dsl/validate.py`（Python 3.12，数据驱动读 `dsl/dsl_spec.yaml`）。子命令：`validate` / `export` / `summary`。
- 导出：`validate.py export` 把 DSL 变成 `parkdsl-web/1` JSON，供 `web/` 前端直接加载（线1→线2 单向数据流）。

## 2. 顶层结构

```yaml
api: parkdsl/1                     # 必填，固定
park:
  id: PARK-001                     # ^PARK-[0-9]{3}$
  name: 星辰智造产业园              # 园区名（前端简介面板标题）
  description: |-                  # 园区简介（前端简介面板正文，支持多行）
    …
  tier: medium                     # simple | medium | complex（三档，声明值，校验器按 §7 复核）
  contract_capacity_kw: 2000       # 合同容量，>0
  incoming_voltage: 10kV           # 进线电压等级
  seed: 42                         # 可选 int，伪遥测确定性种子（缺省 42）

grid_inlets:                       # 上级电源（≥1）；本数组内元件可省略 type（默认 GridInlet）
  - id: GRID-01
    source_voltage: 10kV
    short_capacity_mva: 200

substations:                       # 配电房（≥1）
  - id: SR-A                       # ^SR-[A-Z]$（全园唯一）
    name: A 配电房
    devices:                       # 元件清单，见 §3
      - {id: TX-A01, type: Transformer, capacity_kva: 1600, hv: 10kV, lv: 0.4kV}
      - {id: BUS-A2, type: Bus, voltage_level: 0.4kV}
      - {id: LD-A01, type: Load, peak_kw: 420, profile: factory}

links:                             # 连接（全园一级，≥1）
  - {from: GRID-01, to: BUS-A1, kind: line, id: LN-01, length_km: 2.5, ampacity_a: 400}
  - {from: TX-A01, to: BUS-A2, kind: direct}
  - {from: BUS-A2, to: BUS-B1, kind: coupler, id: CP-01, state: OPEN}
```

## 3. 元件类型表（type ∈ 下表；前缀即 ID 前缀）

| type | ID 前缀 | 必填参数 | 可选参数（缺省） | 说明 |
|---|---|---|---|---|
| GridInlet | GRID | source_voltage | short_capacity_mva(200) | 上级电源/进线点 |
| Transformer | TX | capacity_kva, hv, lv | cooling(ONAN), no_load_loss_kw(1.5), load_loss_kw(12.0) | hv≠lv；两端电压级必须不同 |
| Bus | BUS | voltage_level | — | 母线；同电压级母线方可直连 |
| Switchgear | SG | rated_current_a | state(CLOSED), role(feeder) | role=coupler 时为联络开关 |
| CapacitorBank | CB | capacity_kvar | state(OFF) | 投/切状态字串 "ON"/"OFF"（YAML 裸 OFF 是布尔，必须加引号） |
| BESS | BESS | capacity_kwh, power_kw | soc(50) | 储能；soc∈[0,100] |
| PV | PV | capacity_kwp | tilt(15), azimuth(180) | 光伏 |
| EVCharger | EVC | total_power_kw | num_ports(4) | 充电桩群，计入负荷 |
| Load | LD | peak_kw, profile | power_factor(0.85) | profile ∈ office/factory/commercial/resident |

线路不作为 devices 元件，而是 link 的 `kind: line`（见 §4）。电压等级取值域：`110kV / 35kV / 10kV / 0.4kV`。

## 4. 连接（links）

| kind | 必填 | 可选 | 语义 |
|---|---|---|---|
| line | from, to, id, length_km, ampacity_a | r_ohm_per_km(0.20), x_ohm_per_km(0.08) | 架空/电缆线路，id 前缀 LN |
| direct | from, to | — | 房内短连接（柜-变-母线），无线路参数 |
| coupler | from, to, id | state(OPEN) | 母线联络，id 前缀 CP；辐射运行时常开 |

- `from`/`to` 必须引用已存在元件 ID（不含 SR/PARK）。
- 电压一致性（P-V07）：两端均为 Bus 的 link，`voltage_level` 必须相同；跨电压级必须经 Transformer（校验器对以 TX 为端点的 link 跳过该检查）。

## 5. 元件 ID 约定（故障事件对齐接口 · 与 worker-B 的契约）

1. **正则**（机器可读版见 `dsl_spec.yaml` id_rules）：
   - 元件：`^(GRID|LN|TX|BUS|SG|CB|BESS|PV|EVC|LD|CP)-[A-Z]?[0-9]{1,2}$`（`[A-Z]`=配电房字母，推荐携带；序号推荐两位补零，兼容考古 `seed.yaml` 单数字风格如 `BUS-A1`）
   - 配电房：`^SR-[A-Z]$`；园区：`^PARK-[0-9]{3}$`
2. **全园唯一**：devices 的 id、links 的 id（LN/CP）共处同一命名空间，不得重复。
3. **推荐读法**：`TX-A01` = A 房 01 号变压器；不带房字母（BESS-01/PV-01）= 全园顺序编号（与 seed.yaml 考古一致）。
4. **故障事件引用**：故障注入请求以自然语言描述 + `targets[]` 引用本节 ID（如 `"2 号变压器重瓦斯跳闸" → targets: ["TX-A01"]`）。前端/agent 侧事件格式契约草案：`web/docs/fault-events.md`（worker-B 未落位前由本文件承载定义，冲突由 judge 裁决）。**元件 ID 以本 DSL 导出的 JSON 为唯一权威源**。

## 6. 校验规则（validate.py 全量执行；错误码可 grep）

| 码 | 级别 | 规则 |
|---|---|---|
| E-API | error | `api` 必须为 `parkdsl/1` |
| E-PARK | error | park 必填 id/name/description/tier/contract_capacity_kw；tier 取值合法；contract_capacity_kw>0 |
| E-DEV | error | 元件 type ∈ §3 表；必填参数齐全；数值范围合法（capacity>0、soc∈[0,100]、pf∈(0,1]、电压级 ∈ 取值域） |
| E-ID | error | ID 不匹配正则 / 重复 / SR 重复 |
| E-LINK | error | link 端点不存在；kind:line 缺 id/length_km/ampacity_a；coupler 缺 id |
| E-TOPO | error | 连通性断裂：任一元件从所有 GridInlet 均不可达（OPEN coupler 视为断开） |
| E-VOLT | error | Bus-Bus 相连电压级不一致 |
| E-CAP | error | ① Σ(Load.peak_kw + EVC.total_power_kw) > contract_capacity_kw；② 某台变压器低压侧下游 Σpeak > capacity_kva×0.85 |
| E-LOOP | error | 存在不含 OPEN coupler 的环（闭环运行必须常开联络点）；simple 档存在任意环即 error |
| E-TIER | error | 声明 tier 与 §7 规模判据推断不符（错误信息给出推断值） |

全部通过输出 `PARK-DSL VALIDATION PASS`，退出码 0；任一 error 退出码 1，逐条打印 `[错误码] 位置: 可读原因(实际值)`。

## 7. 档位（tier）规模判据（校验器据此复核声明）

| 判据 | simple | medium | complex |
|---|---|---|---|
| substations | =1 | ≤2 | 无上限 |
| Transformer 台数 | ≤2 | ≤4 | 无上限 |
| Load 元件数 | ≤6 | ≤12 | >12 或其余超界 |
| DER 台数（BESS+PV+EVC） | 0 | ≤4 | >4 |

推断规则：先试 simple 判据，不满足试 medium，仍不满足即 complex；与 `park.tier` 不一致 → E-TIER。

## 8. 伪遥测公式（导出 JSON 的 telemetry 节 + web/server.js 实现同一套）

- 步长 `step_sec=15`；任意元件在时刻 t 的有功：
  `P(id,t) = rated(id) × shape(profile(id), t) × (1 + ε(id,t))`
  `ε(id,t) = 0.04·(u(id,t)−0.5)·2 + 0.02·sin(2π·t/600 + φ(id))`，u 为以 (seed,id,步序) 播种的确定性 PRNG（mulberry32），φ=id 哈希相位。
- `shape`：24 点日形状线性插值，按 profile 取表（office/factory/commercial/resident/pv/bess），pv 为白天钟形、bess 谷充峰放（±0.5 归一）。
- 母线电压：`V = Vnom × (1 − 0.03·loading + 0.004·noise)`；电流 `I = P·1000/(√3·V·pf)`。
- 同 `(seed, id, t)` 必得同值（curl 复现实证），故障注入的 `telemetry_effects` 以乘子叠加其上。

## 9. 三档样例与 LLM 提示词

- 样例：`examples/park-simple-01.yaml`、`park-medium-01.yaml`、`park-complex-01.yaml`、`park-arena-01.yaml`（全部过 §6 校验，`dsl/tests/run_tests.py` 退出码为证；末者为 v1.1 练习场三节示范）。
- 提示词：`prompts/gen-{simple,medium,complex}.prompt.md`，内嵌本规范要点+完整元件表+tier 判据+few-shot；运行器 `prompts/run_gen.py`（OpenAI 兼容 /v1/chat/completions，凭证经 env/stdin，argv-free；产物直接接 `validate.py validate` 复核）。
- 真实模型配额：线1 ≤3 次（台账 `prompts/quota-ledger.md`）。

## 10. v1.1 增量：练习场三节（faults / calendar / scenario）

> 2026-10-01 · 阶段 d（模拟练习场）落地。**全部为可选顶层节**：不含这些节的文件
> 校验与导出行为与 v1 完全一致（向后兼容，api 仍为 parkdsl/1）。裁决源仍是
> `dsl_spec.yaml` 的 `extensions:` 块；`validate.py` 在基础校验全过后才校验三节
> （错误码 E-FAULT / E-CAL / E-SCEN），避免结构错误层叠。示范样例：
> `examples/park-arena-01.yaml`。

### 10.1 `faults`：故障库引用条

把 `arena/faults` 论文故障库的条目**绑定**到本园设备与判据（库是判据权威，DSL 是绑定层）：

```yaml
faults:
  - id: F-PD-01                    # ^F-[A-Z][A-Z0-9-]{0,39}$，节内唯一
    kind: partial_discharge        # 必须 ∈ arena/faults 库 16 类（4 类既有白名单 + 12 类论文扩展）
    target: SG-A01                 # 可选；绑定元件 ID（不写=园区级/库级条目）
    severity: warn                 # info | warn | alarm | accident
    criteria_ref: R37              # ^R[0-9]+$ → docs/theory/references.md 编号（判据出处）
    detection:                     # 告警判据（可选）
      metric: tev_db               # 测点名
      threshold: 20
      comparator: ">"              # > >= < <= == 或 trend_up（趋势型）
      duration_sec: 600            # 持续时间（>0）
      window: trend                # 可选：趋势窗口
    note: TEV 横向+纵向趋势判读…    # 人读备注
```

- `kind` 16 类：`short_circuit / line_break / overload / pv_trip`（既有引擎白名单）
  + `partial_discharge / temperature_rise / harmonic / three_phase_unbalance / over_limit /
  protection_maloperation / transformer_fault / dc_ground_fault / phase_loss /
  single_phase_ground / environmental`（论文扩展）。
- 判据阈值须带出处：`criteria_ref` 指向理论卷参考文献；没有把握的判据在 `note` 标明
  【工程惯例/待核】——这条是"经得起电力专家审查"的硬约束。

### 10.2 `calendar`：业务日历（正常营业与管理变化的事件源）

```yaml
calendar:
  shifts: ["00:00-08:00", "08:00-16:00", "16:00-24:00"]   # HH:MM-HH:MM（尾端可 24:00）
  events:
    - {id: CAL-PATROL-D, type: patrol, every_days: 1, at: "09:00", scope: all}
    - {id: CAL-UPS, type: preventive_test, every_days: 90, params: {item: ups_battery_capacity}}
    - {id: CAL-95598, type: work_order_95598, params: {response_min: 45}}
```

- `type` 8 类：`shift_handover / patrol / infrared_scan / preventive_test / outage_plan /
  baodian / work_order_95598 / report`（对齐两票三制、DL/T 1102 巡检周期、95598 时限等，
  依据见 `docs/theory/`）。
- `every_days` ≥1 整数；`at` 为 HH:MM；`params` 自由映射放类型专属参数。

### 10.3 `scenario`：倍速场景 + 注入计划

```yaml
scenario:
  seed: 202                        # ≥0 整数
  duration_sim_s: 604800           # 场景总长（仿真秒）= 7 仿真日
  clock_speed: 600                 # 每墙钟秒对应 600 仿真秒（10 分钟倍速）
  agent: {enabled: true, model: mock}   # 被测 agent 开关（人机对比的总开关）
  injections:                      # 注入计划（四步留痕：计划→执行→命中→恢复）
    - {fault: F-PD-01, at_sim_s: 86400}  # fault 必须引用本文件 faults 节的条目 ID
```

- `clock_speed` ∈ [0.1, 3600]；`at_sim_s` ≥0 且 < `duration_sim_s`；`agent.enabled=false`
  即「关闭 agent 交给人类」的人类体验模式入口（TASK.md D-1..D-3 的 DSL 侧）。
- `injections[].params` 可带类型专属注入参数（如 `overload_ratio`）。

### 10.4 导出透传

`validate.py export` 在 `parkdsl-web/1` JSON 中新增 `faults / calendar / scenario` 三个键
（缺省为空容器），arena 引擎与前端直接消费；`api/nodes/links/telemetry` 既有结构不变。
