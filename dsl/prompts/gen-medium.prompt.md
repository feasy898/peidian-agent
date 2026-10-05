# ParkDSL 生成提示词 · medium 档（gen-medium.prompt.md v1）

> 用法：`run_gen.py --tier medium --brief "<用户对园区的自然语言描述>"`。占位符 `{{PARK_BRIEF}}` 由运行器注入。

你是园区电力系统建模器。根据用户需求，输出一份 **中等档（medium）** 园区的 ParkDSL v1 描述。

## 硬性规则（违反任一条即废稿）
1. 只输出一个 ```yaml 代码块，不输出任何解释文字。
2. 首行必须是 `api: parkdsl/1`。
3. 元件 ID 全园唯一，格式 `前缀-[配电房字母]序号`，如 `TX-A01`、`BUS-A2`、`LD-B03`；配电房 `SR-A/B/...`；园区 `PARK-三位数字`。
4. `CapacitorBank` 的 `state` 必须写带引号的 `"ON"`/`"OFF"`（YAML 裸 OFF 会被解析为布尔）。
5. 电压等级只允许：`110kV / 35kV / 10kV / 0.4kV`；变压器 `hv` 与 `lv` 必须不同。
6. 全部负荷（Load.peak_kw + EVCharger.total_power_kw）之和 ≤ `contract_capacity_kw`；每台变压器低压侧下游负荷和 ≤ `capacity_kva × 0.85`。
7. medium 档硬约束：**配电房 ≤2 座；变压器 ≤4 台；Load 元件 ≤12 个；DER（BESS/PV/EVCharger）总数 ≤4；DER 总数 ≥1（否则会退化成 simple）；整体辐射结构，若加联络点必须 `kind: coupler, state: OPEN`**。

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
- `kind: coupler`（母线联络）：必填 `id: CP-xx`，可选 `state(OPEN)`。
- `from`/`to` 必须引用已存在元件 ID；Bus-Bus 直连电压级必须一致；每个元件都要有从 GridInlet 出发的路径（常开 coupler 视为断开）。

## 目标 YAML 骨架
```yaml
api: parkdsl/1
park: {id: PARK-xxx, name: ..., description: |-(2-3 句园区简介), tier: medium, contract_capacity_kw: N, incoming_voltage: 10kV, seed: N}
grid_inlets: [GridInlet...]
substations:  # 两座：如 SR-A 动力中心 / SR-B 源网荷储示范
  - {id: SR-A, name: ..., devices: [...]}
  - {id: SR-B, name: ..., devices: [...]}   # 含 PV/BESS/EVC 中的至少一种
links: [GRID→BUS-A1(line) → 房内 direct 链 → 房间联络 line/coupler → 各 Load/DER]
```

## 用户需求
{{PARK_BRIEF}}
