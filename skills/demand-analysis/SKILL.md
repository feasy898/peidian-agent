# skills/demand-analysis/SKILL.md · level2 全文（渐进披露第三级；加载才计费）

## 需量分析与容需切换测算（skill.demand-analysis@0.1.0）

适用：园区整体月度需量规律分析（不针对单一用户是否超需）与「按需量计费 vs 按容量计费」
切换决策的数据支撑。判据口径 PHYS-DEMAND（REG-TECH）。

### 数据与口径（全部只读权威源，不另行发挥）

1. **园区台账**：`ontology/seed.yaml` PARK-001——合同容量 `contract_capacity_kw`、
   台账月最大需量 `demand_*.peak_kw`（15min 口径）、日形状 `load_curve_*.shape`（24 点）×
   `base_kw`、电价时段表 `price_schedule`（峰/平/谷窗口）。
2. **判据阈值**：`regulations/REG-TECH.yaml` 规则 PHYS-DEMAND——`demand_ratio = 月最大需量/
   合同容量`，>1.00 → P2 预警、>1.05 → P0 越限（阈值只在规程库里，不在代码里）。
3. **合成序列**（演示口径，无历史量测时的确定性替代）：30 天 × 96 点/天 15 分钟粒度，
   逐点 = `base_kw × interpolate_shape(shape, hour) × 日因子 × 扰动`；插值函数复用
   `src/m5_simulation/physics.py interpolate_shape`（M5 物理层同一约定，含 23↔0 点环绕）；
   扰动幅度 0.03 与 M5 `MODEL_DEFAULTS.noise_amplitude` 同口径；随机源 `random.Random(seed)`
   固定 seed 逐点消耗。全序列等比标定：月最大 15 分钟需量 = 台账 `peak_kw`。
4. **电价参数**：两档基本电价为显式参数，演示默认 需量 48 元/kW·月、容量 32 元/kW·月——
   **演示参数，按当地目录电价替换**。

### 统计定义

- **月最大需量**：全月 2880 个 15 分钟点的最大值（15min 滑窗口径的单元），附发生日期/时刻
  与所在电价时段。
- **Top5 高峰日**：按日内最大 15 分钟需量降序取前 5 个自然日。
- **峰段电量占比**：峰段窗口（电价时段表 `type: PEAK`，本园区 10:00-12:00 与 18:00-21:00）
  电量 / 全月总电量（每点电量 = kW × 0.25h）。
- **负荷率**：全月平均负荷 / 月最大需量。

### 容需切换测算

| 计费方式 | 公式 | 演示默认代入 |
| --- | --- | --- |
| 按需量 | 月基本电费 = 月最大需量 × 需量电价 | 1720 kW × 48 = 82,560 元/月 |
| 按容量 | 月基本电费 = 合同容量 × 容量电价 | 2000 kW × 32 = 64,000 元/月 |

**临界点** `MD* = 合同容量 × 容量电价 ÷ 需量电价`（演示默认 2000×32÷48 ≈ 1333.33 kW）：
月最大需量 **低于** MD* → 按需量计费划算；**高于** MD* → 按容量计费划算。
输出对比表、临界点、月/年节省额与建议；换档决策须经业主确认后向供电公司申请，本技能只出数。

### 判据联动（PHYS-DEMAND）

- `demand_ratio = 月最大需量 / 合同容量`；分级阈值读规程库并换算成 kW 线：
  预警线 = 1.00 × 合同容量（P2）、越限线 = 1.05 × 合同容量（P0）；
- 结论必须引用规则 ID `PHYS-DEMAND`；任意假设需量值（what-if）同样走该分级函数。

### 输出结构（键封闭，tests/test_m8.yaml SPEC-M8-06 断言面）

```
result = {
  skill, generated_by_meta{script, seed, interval_min, days},
  park{id, tariff, contract_capacity_kw, demand_month, ledger_peak_kw,
       base_kw, synthesis{method, day_factor_range, jitter_amplitude,
       calibration, calibration_peak_kw}},
  series_stats{points, month_peak_kw, month_peak_at, month_peak_period, top5_days[],
    energy_kwh, mean_kw, load_factor, period_energy_ratio{PEAK/FLAT/VALLEY},
    peak_windows[]},
  billing{demand_price_yuan_per_kw_month, capacity_price_yuan_per_kw_month,
    param_note, demand_billing_yuan, capacity_billing_yuan, cheaper,
    saving_yuan_per_month, saving_yuan_per_year, threshold_kw, threshold_note},
  criteria{rule_ids[], source, demand_ratio, warn_over, breach_over,
    warn_kw, breach_kw, level, margin_to_warn_kw, conclusion},
  recommendation
}
```

### 证据要求（evidence_policy）

- 数据源字段与文件路径（seed.yaml / REG-TECH.yaml 的规则 ID 与阈值原文）；
- 合成口径声明（插值/日因子/扰动/标定），不得冒充实测历史；
- 电价参数标注「演示参数，按当地目录电价替换」；
- 拒绝带病出数：非法参数 ValueError（中文原因）。

### 边界声明

合成序列是演示口径（真实运行应以关口表 15 分钟历史数据替换，接口不变）；
容需切换的档位变更须走供电营业流程，本技能输出仅为决策数据支撑。
