# arena/data — 真实时序负荷/光伏形状数据

`load_profiles.yaml` 提供 24 点（小时粒度）标准化负荷与光伏形状，与
`dsl/dsl_spec.yaml` 的 `telemetry.shapes` 同构（引擎线性插值，max = 1.000）。
数据为**真实测量级基准数据**，非人工构造。

## 来源：SimBench

- 项目官网：<https://simbench.de>　文档：<https://simbench.readthedocs.io>
- 论文：Meinecke, S.; et al. *"SimBench—A Benchmark Dataset of Electric Power
  Systems with a High Share of Renewable Energies."* Energies 2020, 13(4), 865.
  DOI: [10.3390/en13040865](https://doi.org/10.3390/en13040865)
- 许可：Open Data Commons Attribution License (ODC-BY) 1.0（允许再分发，需署名）。
- 获取方式（本机已实测可复现）：

  ```bash
  pip install simbench        # v1.6.3，自动带上 pandapower
  ```

  ```python
  import simbench as sb
  net = sb.get_simbench_net("1-LV-urban6--0-sw")     # LV 低压网（-sw = 含开关）
  prof = sb.get_absolute_values(net, profiles_instead_of_study_cases=True)
  load_p_mw = prof[("load", "p_mw")]   # 全年 15min × 35136 点（参考年 2016）
  pv_p_mw   = prof[("sgen", "p_mw")]   # 光伏（net.sgen, type=PV）
  ```

## 本次提取的网络

| SimBench 代码 | 规模 | 负荷剖面 | PV 剖面 |
|---|---|---|---|
| `1-LV-urban6--0-sw` | 111 负荷 + 5 PV（城市混合低压网） | H0-A/B/C/L/G（住宅）×102，G1-A/B/C（商业零售）、G4-A/B（工业两班）、G6-A（服务业）×9 | PV2/PV5/PV6/PV8（朝向变体） |
| `1-LV-rural1--0-sw` | 13 负荷 + 4 PV（农村低压网） | H0-A/B/C ×3，L1-A、L2-A（农业）×10 | PV5/PV6/PV8 |

时间分辨率：15 min，参考年 2016（闰年，366 天 × 96 点 = 35136 步）。

## 处理链（yaml 内数值如何得出）

1. 按剖面族**容量加权聚合**（直接把同族负荷的 MW 曲线求和，物理意义 = 馈线级合成曲线）；
2. 按小时聚合为**年均日形状**（全年同时刻均值，24 点）；
3. 除以**日均峰值**归一化 → max = 1.000（与 dsl_spec.shapes 约定一致）。

`shape_meta` 记录"日均峰值 / 全年峰值"比值：值越小表示该类负荷峰谷差越大
（如住宅 0.288 → 尖峰型；商业 0.526 → 平缓型）。

## 剖面族命名（德国标准负荷剖面）

| 前缀 | 含义 | arena 映射 |
|---|---|---|
| H0 | 住宅（A/B/C/L/G 为变体） | `resident` |
| G1 | 商业零售（营业日型） | `commercial` |
| G4 | 工业（两班制） | `factory` |
| G6 | 服务业（午后峰） | `office`（代理）＋并入 `commercial` |
| L1/L2 | 农业 | `agricultural` |
| PV1–PV8 | 光伏不同朝向 | `pv` |

注意：SimBench 没有专门的"写字楼"剖面，`office` 取 G6（服务业）作为最近似代理，
 yaml 内已标注。若不合适，可回退使用 dsl_spec 内置人工 office 形状。

## 已知特征

- 年均日 PV 峰约在 10–11 时（全年平均含冬季短日照及数据时制所致）。
  需要正午峰形时可用 `profiles_detail.pv_PV6`（峰 10–11 时、下午坡度更缓）
  或 dsl_spec 内置 `pv`（峰 13 时）。
- `profiles_detail` 保留全部 17 条原始剖面逐条形状（H0×5、G1×3、G4×2、G6×1、L×2、PV×4），
  供细分场景/多样性建模直接引用。

## 环境备注

`pip install simbench` 时 pip 将全局 pandapower 从 3.2.2 升级到 3.5.5（simbench 1.6.3
的依赖要求），并升级 numpy/pandera 等。已验证 arena 现有代码在 pandapower 3.5.5 下
导入与潮流计算正常（见 arena/tests）。SimBench 原始 CSV 会在首次 `get_simbench_net`
时缓存到用户目录，之后可离线复现。
