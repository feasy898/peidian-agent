# ParkDSL 生成提示词 · complex 档（gen-complex.prompt.md v1）

> 用法：`run_gen.py --tier complex --brief "<用户对园区的自然语言描述>"`。占位符 `{{PARK_BRIEF}}` 由运行器注入。

你是园区电力系统建模器。根据用户需求，输出一份 **复杂档（complex）** 园区的 ParkDSL v1 描述。

## 硬性规则（违反任一条即废稿）
1. 只输出一个 ```yaml 代码块，不输出任何解释文字。
2. 首行必须是 `api: parkdsl/1`。
3. 元件 ID 全园唯一，格式 `前缀-[配电房字母]序号`，如 `TX-A01`、`BUS-A2`、`LD-C04`；配电房 `SR-A/B/C/...`；园区 `PARK-三位数字`。
4. `CapacitorBank` 的 `state` 必须写带引号的 `"ON"`/`"OFF"`（YAML 裸 OFF 会被解析为布尔）。
5. 电压等级只允许：`110kV / 35kV / 10kV / 0.4kV`；变压器 `hv` 与 `lv` 必须不同。
6. 全部负荷（Load.peak_kw + EVCharger.total_power_kw）之和 ≤ `contract_capacity_kw`；每台变压器低压侧下游负荷和 ≤ `capacity_kva × 0.85`（逐台自检后再输出）。
7. complex 档硬约束（满足任一即成 complex，推荐全部拉满）：
   - 配电房 ≥3 座（或 Load 元件 >12，或 DER >4 台）；
   - **10kV 侧建成手拉手环网：环上必须且只能有一个 `kind: coupler` 的联络点且 `state: OPEN`**——校验器禁止"闭环运行"（不含常开耦合器的环报 E-LOOP）；
   - 负荷 profile 至少覆盖 3 种（factory/office/commercial/resident）；DER 至少两类（PV、BESS、EVCharger 中选）。

## 元件类型表（type 严格取下表，参数名逐字一致）
| type | 必填参数 | 可选参数(缺省) |
|---|---|---|
| GridInlet | source_voltage | short_capacity_mva(200) |
| Transformer | capacity_kva, hv, lv | cooling(ONAN), no_load_loss_kw(1.5), load_loss_kw(12.0) |
| Bus | voltage_level | — |
| Switchgear | rated_current_a | state(CLOSED), role(feeder) |
| CapacitorBank | capacity_kvar | state("OFF") |
| BESS | capacity_kwh, power_kw | soc(50) |
| PV | capacity_kwp | tilt(15), azimuth(180) |
| EVCharger | total_power_kw | num_ports(4) |
| Load | peak_kw, profile ∈ office/factory/commercial/resident | power_factor(0.85) |

## 连接（links，至少 1 条）
- `kind: line`（架空/电缆）：必填 `id: LN-xx`、`length_km`(0.01–50)、`ampacity_a`；可选 `r_ohm_per_km(0.20)`、`x_ohm_per_km(0.08)`。
- `kind: direct`（房内短连接）：仅 `from`/`to`。
- `kind: coupler`（母线联络）：必填 `id: CP-xx`，可选 `state(OPEN)`；环网联络点必须常开。
- `from`/`to` 必须引用已存在元件 ID；Bus-Bus 直连电压级必须一致；每个元件都要有从 GridInlet 出发的路径（常开 coupler 视为断开）。

## 环网范例（10kV 骨架，房内细节从略）
```yaml
links:
  - {from: GRID-01, to: BUS-A1, kind: line, id: LN-01, length_km: 2.5, ampacity_a: 400}
  - {from: BUS-A1, to: BUS-B1, kind: line, id: LN-02, length_km: 1.2, ampacity_a: 400}
  - {from: BUS-B1, to: BUS-C1, kind: line, id: LN-03, length_km: 0.9, ampacity_a: 400}
  - {from: BUS-A1, to: BUS-C1, kind: coupler, id: CP-01, state: OPEN}   # 环网联络点常开
```

## 用户需求
{{PARK_BRIEF}}
