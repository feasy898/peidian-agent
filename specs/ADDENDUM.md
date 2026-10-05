# ADDENDUM · Owner 补遗（契约 v1.0 → v1.1，2026-09-28）

> 由交付 owner 签发，属于开发包一部分，与 `01-contracts.md` 冻结契约同权重。
> 本补遗只含**通用领域目录与接口要求**，不含任何验收（holdout）场景/实例/判据数据。
> 变更性质：向后兼容增补（minor），不改动既有字段与枚举。

## A. 规程目录（regulations/）完整清单

`regulations/` 必须包含四个文件：`REG-SAFE.yaml`、`REG-COMM.yaml`、`REG-TECH.yaml`、`REG-OP.yaml`。

- `REG-SAFE` / `REG-COMM`：条款按 `00-ontology.md` §1.4 表格落盘（规则 ID 逐条对应）。
- `REG-TECH`：技术监督阈值类条款（条款文字自拟），必须覆盖 00 §1.4 R-物理约束的判据口径（供 M5 仿真判据引用；禁止在仿真代码硬编码阈值，见 SPEC-M5-08）。
- `REG-OP`：运维操作规程（SAFE-OP 家族 + OP-* 操作类），至少包含以下规则 ID（条款文字自拟，不得与 00 冲突）：
  - `SAFE-OP-TWO-TICKET`：两票操作实施细则（从属 SAFE-TWO-TICKET）；
  - `SAFE-OP-REMOTE`：遥控操作细则（从属 SAFE-ORDER-SEQ / SAFE-SINGLE-OP）；
  - `SAFE-OP-MAINTAIN`：检修作业细则（从属 SAFE-MAINTAIN-ISO）；
  - `OP-QCOMP-CAP`：无功补偿电容投切操作要求；
  - `OP-DEMAND-LIMIT`：需量限额与预警（判据口径与 PHYS-DEMAND 一致：>1.0 预警、>1.05 越限）。

## B. 报告 schema（report.daily@v1）

`write.report` 产出的日巡检报告内容必须含四段：设备清单（devices）、量测（measurements，含时序趋势数据）、结论（conclusion）、规程引用（regulation_refs，规则 ID 列表）。M2 的 schema 校验按此实现，M4 SPEC-M4-05 联动校验规则 ID 存在性。

## C. 事件目录增补（01 §4 清单之外新增两条）

- `price.period_changed {from, to}`：M5 电价时钟在时段边界发布；时间戳用 BUSINESS 时钟读数。
- `demand.month_rolled {from_month, to_month, frozen_peak_kw}`：月度需量滑窗跨月切换时发布。

## D. Park 实例按名加载

M4/M5 的园区实例加载必须支持：按 `ScenarioSpec.environment.park_instance` 的名字解析实例文件（格式同 `ontology/seed.yaml`，去扩展名匹配）；默认搜索 `ontology/`，并支持通过环境变量 `PARK_INSTANCE_PATH` 追加搜索目录（分隔符 `;`）。验收时将通过该机制提供独立实例文件，其内容开发侧不可见——加载实现必须对任意同构实例文件通用，不得针对特定实例硬编码。

## E. evaluator CLI（M6）

`evaluator` 必须支持命令行参数：`--release <id>`、`--golden <dir>`（显式指定黄金集目录，默认 `golden/dev/`）、`--mode SIMULATION`。

## F. holdout 隔离红线（重申，CI 断言）

仓库任何路径不得出现 holdout 场景/实例/判据文件；`golden/dev/`、`scenarios/`、`src/`、`tests/`、`ontology/`、`regulations/` 中 grep `PARK-002|TARIFF-2026B|OP-1x` 必须零命中（与 SPEC-M6-02 联动）。
