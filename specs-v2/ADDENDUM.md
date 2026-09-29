# ADDENDUM v2 · Owner 补遗转正（§A-§F 六节）

> **v2 · 由 oracle 反提（证据锚点到文件:行）**。骨架 = v1 `specs/ADDENDUM.md`
> （Owner 补遗，契约 v1.0→v1.1，2026-09-28，向后兼容增补）§A-§F 六节；每节按
> **v1 条款 → oracle 现状** 复核转正，与 v1 口径有偏差处引 `specs-v2/DEVIATIONS.md`
> 的 D 编号（ADDENDUM 层 = D-67..D-71；§F 另涉 D-44）。
> oracle = `src/`（contracts、m1_core..m7_registry）、`regulations/`、`scripts/`、
> `run_evals.py` 现行实现全体；本文全部 `文件:行` 锚点为反提会话（2026-09-30）逐条核对。
> v1 原文 `specs/ADDENDUM.md` 原样保留不删（弃用指针见 `specs/README.md` 顶部；
> `specs-v2/DEVIATIONS.md:11` 同注）。本文不含任何验收（holdout）场景/实例/判据数据。

## §A 规程目录（regulations/）完整清单

**v1 条款**（`specs/ADDENDUM.md:7-18`）：`regulations/` 必含四文件；REG-SAFE/REG-COMM
按 00 §1.4 表格落盘；REG-TECH 覆盖 R-物理约束判据口径（禁仿真硬编码，SPEC-M5-08）；
REG-OP 至少五个规则 ID（两票/遥控/检修细则 + 电容投切 + 需量限额，OP-DEMAND-LIMIT
判据口径与 PHYS-DEMAND 一致）。

**oracle 现状：全部满足，且由加载侧强制。**

- 四文件齐备并被 M4 加载校验钉死：`src/m4_semantic/loader.py:59`
  `REGULATION_FILE_IDS = ("REG-SAFE", "REG-COMM", "REG-TECH", "REG-OP")`；
  `_validate_regulations`（`loader.py:703-726`）对缺文件（:709）、缺 rules（:712-713）、
  缺 id/clauses（:715-723）、规则 ID 跨文件重复（:718-721）一律 `OntologyLoadError`
  ——启动失败优于带病运行。
- **REG-SAFE** 5 条（`regulations/REG-SAFE.yaml:12,18,25,31,37`：
  SAFE-TWO-TICKET / SAFE-ISSUE-HUMAN / SAFE-ORDER-SEQ / SAFE-MAINTAIN-ISO /
  SAFE-SINGLE-OP），与 v1 00 §1.4 安全表逐条对应（`specs/00-ontology.md:124-128`）。
- **REG-COMM** 4 条（`regulations/REG-COMM.yaml:11,17,23,29`：COMM-TARIF-SYNC /
  COMM-PF-BONUS / COMM-DEMAND-CHARGE / COMM-TOU-ARBITRAGE ↔ `specs/00-ontology.md:134-137`）。
- **REG-TECH** 7 条（`regulations/REG-TECH.yaml:14,26,38,50,61,73,86`）：
  PHYS-TX-LOAD / PHYS-V-RANGE / PHYS-THD / PHYS-PF / PHYS-DEMAND / PHYS-BESS-SOC /
  **PHYS-TX-TEMP**——比 v1 §1.4 R-物理约束的 6 条多 PHYS-TX-TEMP，阈值为
  `thresholds` 机械口径（op/value/level/name 结构，如 PHYS-DEMAND：>1.00→P2 预警、
  >1.05→P0 越限，`REG-TECH.yaml:61-71`）；M5 告警引擎数据驱动装载、零硬编码
  （`src/m5_simulation/alarm_engine.py:13-15,51-58`；SPEC-M5-08 同源纪律，
  `specs-v2/M5-simulation.md:71,205`）。
- **REG-OP** 五条全部落盘（v1 "至少包含" → oracle 恰为五条，无增减），
  `regulations/REG-OP.yaml`：

  | 规则 ID | 行锚点 | parent | 要点 |
  | --- | --- | --- | --- |
  | `SAFE-OP-TWO-TICKET` | :13-22 | SAFE-TWO-TICKET | 一票一任务；ISSUED 方可执行；监护核对；回读+BUSINESS 时钟记录 |
  | `SAFE-OP-REMOTE` | :24-33 | SAFE-ORDER-SEQ, SAFE-SINGLE-OP | 按 steps 声明序串行；回读为准；拒绝后禁变体绕行 |
  | `SAFE-OP-MAINTAIN` | :35-43 | SAFE-MAINTAIN-ISO | MAINTENANCE 状态+含许可 WorkTicket 方可开工；作业期遥控禁止 |
  | `OP-QCOMP-CAP` | :45-53 | —（operation 类） | 电容投切高风险缺省 ASK；放电间隔；投切后回读 Q/cosφ |
  | `OP-DEMAND-LIMIT` | :55-66 | —（operation 类） | criteria `warn_over: 1.0` / `breach_over: 1.05`（:63-66），与 PHYS-DEMAND 判据口径一致（头注 :4 明示同源） |

  规则 ID 目录已转正于 00 v2「R-运维操作规程」节（`specs-v2/00-ontology.md:186-189`）
  与 §8 对照行（`00-ontology.md:401`）。

**偏差**：D-67〔新增〕五规则 ID 全部落盘（`specs-v2/DEVIATIONS.md:155`）；
D-40〔变义〕REG-TECH 6→7 条 + 阈值散文→thresholds 机械口径（`DEVIATIONS.md` M5 节）。

## §B 报告 schema（report.daily@v1 四段）

**v1 条款**（`specs/ADDENDUM.md:20-22`）：`write.report` 日巡检报告必含四段
devices / measurements（含时序趋势）/ conclusion / regulation_refs；M2 schema 校验
按此实现；M4 联动校验规则 ID 存在性（v1 写 "SPEC-M4-05"）。

**oracle 现状：逐项落地。**

- 校验器 = `src/m2_information/artifact.py:83-143` `report_daily_v1(content, ctx)`，
  以 `register_schema("report.daily@v1", report_daily_v1)` 注册（`artifact.py:146`）。
  逐项口径：
  - 四段存在性：`sections = ("devices", "measurements", "conclusion", "regulation_refs")`
    （`artifact.py:93`），逐段 `section:<name>` check（:97-100）；
  - **devices**：非空列表（`artifact.py:101-105`）；
  - **measurements**：非空列表且**逐条含 `points[]` 时序趋势点列、每点含 ts/value**
    （:106-120；缺趋势 → check `measurements_trend` 失败）；
  - **conclusion**：非空 str/dict（:121-126）；
  - **regulation_refs**：非空规则 ID 字符串列表（:127-135）；
  - **规则 ID 存在性**：`ctx["rule_id_checker"]` 钩子存在时对 refs 全量核对，
    未知 ID → check `regulation_refs_exist` 失败（:136-141）；钩子缺省只校验形态。
- 联动接线：`src/m4_semantic/regulation.py:146-156` `rule_id_checker()` 工厂返回
  `RegulationIndex.unknown_rule_ids`，注入 `InformationLayer(rule_id_checker=…)`
  全部构造点（m1/m2 eval_plugin 与 M6 CaseRunner——`src/m6_flywheel/evaluator.py:345-349`）；
  EVAL-M2-08-N2 钉死（引用不存在规则 ID → REJECTED）。
- v1 引用的 "M4 SPEC-M4-05" 在 v2 条款号重排为 **SPEC-M4-07**（规程引用规范，含
  rule_id_checker 联动；`specs-v2/M4-semantic-ontology.md:21` 映射行）；M2 侧条款 =
  **SPEC-M2-10**（Artifact 状态机与 schema 钩子，`specs-v2/M2-information.md:30,246`）。

**偏差**：D-68〔强制〕吸收为条款（`specs-v2/DEVIATIONS.md:156`）。

## §C 事件目录增补（01 §4 清单之外两条）

**v1 条款**（`specs/ADDENDUM.md:24-27`）：`price.period_changed {from, to}` 时段边界
发布（BUSINESS 时钟读数）；`demand.month_rolled {from_month, to_month, frozen_peak_kw}`
月度需量滑窗跨月切换时发布。

**oracle 现状：两主题落地且行为有细化。**

- 事件登记：`src/contracts/enums.py:223-225`（"ADDENDUM §C 增补" 注释 :223；
  `PRICE_PERIOD_CHANGED` :224、`DEMAND_MONTH_ROLLED` :225）——两主题入 EventType
  封闭集，事件主题总数 26→**28**（`specs-v2/01-contracts.md:659,662` [v2Δ D-69]）；
  M1 列其为环境事件源（`src/m1_core/loop.py:76-81` `_ENV_EVENT_TYPES`）。
- **price.period_changed**：`PriceClock.advance(prev_s, now_s)`（`src/m5_simulation/
  price_clock.py:72-97`）对 (prev, now] 内每个越过的时段边界发一条（边界集合升序去重，
  :111-122；仅时段类型变化才发，:84）；payload = `{from, to, price, boundary}`（:88-90）
  ——**较 v1 多 `price` 与 `boundary` 两字段**（向后兼容增补，01 v2 §4 目录已按此登记，
  `01-contracts.md:659`）；occurred_at = BUSINESS 时钟读数（`env.emit` 统一以
  `iso_at(sim_elapsed_s)` 落时间戳，`src/m5_simulation/env.py:222-238`，:230）。
  峰谷判定唯一入口 `period_at`（`price_clock.py:41-59`，支持跨零点时段；模块内无任何
  真实时间源引用）。
- **demand.month_rolled**：`DemandTracker.sample(park_net_kw, sim_elapsed_s)`
  （`price_clock.py:142-161`）月内 15min 采样最大值滑窗（:125-141）；跨月采样
  **先发事件再重置**（:147-158）：payload = `{from_month, to_month, frozen_peak_kw}`
  （:152-153），`frozen_peak_kw` = 上月峰值 round(,3) 并冻结入 `frozen_history`
  （:148,156）；新月基线取实例 `demand_YYYY_MM` 历史需量（:158，数据驱动）。
  `demand_ratio` = 月峰值/合同容量（:136-140）；阈值判定归 REG-TECH PHYS-DEMAND
  （alarm_engine 取用，本模块不做阈值判定，`price_clock.py:11-12`）。
- 行为条款：SPEC-M5-13（`specs-v2/M5-simulation.md:273-284`，证据 EVAL-M5-02-P）。

**偏差**：D-69〔新增〕（`specs-v2/DEVIATIONS.md:157`；payload 扩字段一并登记于
01 v2 §4）。

## §D Park 实例按名加载

**v1 条款**（`specs/ADDENDUM.md:29-31`）：按 `ScenarioSpec.environment.park_instance`
名字解析实例文件（格式同 `ontology/seed.yaml`，去扩展名匹配）；默认搜索 `ontology/`；
环境变量 `PARK_INSTANCE_PATH`（分隔符 `;`）追加搜索目录；加载实现对任意同构实例文件
通用，不得针对特定实例硬编码。

**oracle 现状：按条款实现，另有两处向后兼容细化。**

- 实现位（M4）：`src/m4_semantic/loader.py:63-64`（`ENV_PARK_INSTANCE_PATH =
  "PARK_INSTANCE_PATH"`、`PARK_INSTANCE_PATH_SEP = ";"`）；
  `resolve_instance_file(name, *, repo_root, extra_dirs)`（:175-206）：
  - 实例名须为不含路径分隔符的安全标识符（`_ID_SAFE_RE` :66；非法名拒绝 :187-188）；
  - 搜索顺序 = `ontology/`（缺省）→ 环境变量 `PARK_INSTANCE_PATH` 依序追加
    （**调用时读取**，便于测试注入，:191-195）→ 调用方显式 `extra_dirs`（末位追加，
    :196-197）；
  - 去扩展名匹配 `.yaml`/`.yml`（:198-202）；未找到 → `InstanceLoadError`，
    消息列出全部搜索目录与追加提示（:203-206）。
- `load_park_instance`（:209-236）→ `_parse_instance`（:242-374）：park.id 必备、
  对象类型/关系 ID 存在性、枚举封闭校验、扩展节按 `SECTION_TYPE_HINTS` 通用解析
  （:70-87）——对任意同构实例通用，零实例特判（验收以独立实例文件经
  `PARK_INSTANCE_PATH` 注入即走此通道）。
- M5 同一机制：`src/m5_simulation/env.py:5-8`（`load_scenario` 按
  `park_instance` 名加载）与 :455-480（→ `load_ontology(instance=…)`）；
  EVAL 侧经 `tests/fixtures/dev-sim-park.yaml` 注入验证（SPEC-M5-14 共享映射，
  `specs-v2/M5-simulation.md:346`）。
- 契约注记：01 v2 ScenarioSpec.environment.park_instance 字段注
  （`specs-v2/01-contracts.md:271-272` [v2Δ D-70]，另 :526 展开注）。
- oracle 细化（v1 未写、向后兼容）：`extra_dirs` 末位通道（测试/装配显式注入用）与
  实例名安全标识符约束。
- 条款：SPEC-M4-02（loader 侧，`specs-v2/M4-semantic-ontology.md:101`）、
  SPEC-M5-14（env/EVAL 注入侧）。

**偏差**：D-70〔强制〕吸收为条款（`specs-v2/DEVIATIONS.md:158`）。

## §E evaluator CLI（M6）

**v1 条款**（`specs/ADDENDUM.md:33-35`）：`--release <id>`、`--golden <dir>`
（默认 `golden/dev/`）、`--mode SIMULATION`。

**oracle 现状：三参齐备，exit code 语义钉死。**

- `src/m6_flywheel/evaluator.py:874-896` `main(argv)`：
  - `--release`：必填（:877，`required=True`）；
  - `--golden`：缺省 `DEFAULT_GOLDEN_DIR = "golden/dev/"`（:878-879；常量定义 :93）；
  - `--mode`：缺省 `"SIMULATION"`（:880-881）；非 SIMULATION（如 REAL）→
    `GoldenEvaluator` 构造即抛 `EvaluatorError`（:767-770），CLI 捕获打印
    `EVALUATOR ERROR` 并 **exit 2**（:887-889）——黄金集一律仿真（01 §8）；
  - 正常完成 exit 0（零 failures）/ 1（有 failures）（:896）。
- 运行主链 `run_golden`（01 §3.6 冻结 API，:860-868）与报告归档
  `runs/eval/<stamp>-<release_id>/`（report.json + 逐案例事件流/轨迹 + release 快照，
  :793-852）。
- 01 v2 注记：`specs-v2/01-contracts.md:597` [v2Δ D-71]；行为条款 SPEC-M6-07⑩
  （`specs-v2/M6-flywheel.md` SPEC-M6-07 节，:268 起）。

**偏差**：D-71〔强制〕吸收为条款（`specs-v2/DEVIATIONS.md:159`；v1 未规定 exit
code，oracle 钉死 0/1/2）。

## §F holdout 隔离红线（重申，CI 断言）

**v1 条款**（`specs/ADDENDUM.md:37-39`）：仓库任何路径不得出现 holdout
场景/实例/判据文件；六个目录（golden/dev/、scenarios/、src/、tests/、ontology/、
regulations/）内 grep 三个隔离标识必须零命中（与 SPEC-M6-02 联动）。

**oracle 现状：断言代码化并前置到门禁。**

- 断言实现：`scripts/ci_isolation.py`——匹配正则 `ISOLATION_PATTERN`（:31；v1 对
  操作规程 ID 段的一位通配写法在此**等宽化为定长字符类**，覆盖同一段位，
  00 v2 §8 对照行 `specs-v2/00-ontology.md:401` [v2Δ 已替代] D-44）。三个隔离标识
  的字面量以 `scripts/ci_isolation.py:31` 为唯一权威指位，本 v2 文档不复制字面量。
- 扫描目录 `SCAN_DIRS` 十个（`ci_isolation.py:34-45`）= v1 六目录 + oracle 扩充
  `tools/ skills/ prompts/ assets/`（目录扩充属 oracle 现状，未单列 D 编号——
  D-44 仅登记正则等宽，`specs-v2/DEVIATIONS.md:116`）；`specs/` 与 `runtime/`
  不在扫描范围（模块 docstring `ci_isolation.py:1-29`）。
- 门禁前置：`run_evals.py:1084-1092` 每次运行先调 `run_isolation(ROOT)`，命中即
  整体失败（`isolation=VIOLATION` → result≠PASS）；独立 CLI 退出码 0=零命中 /
  1=命中并列出 `文件:行:matched`（`ci_isolation.py:100-107`）。
- SPEC-M6-02 联动（v2 口径）：golden_set 装载 holdout 标记双重拒绝 +
  `add_golden_case` 写入通道拒绝（`specs-v2/M6-flywheel.md:121-133`；负例
  EVAL-M6-02-N / EVAL-M6-02-N2）。

**偏差**：D-44（§F 正则等宽，`specs-v2/DEVIATIONS.md:116,194`）；扫描目录 6→10
按 oracle 实况登记（无独立 D 编号）。

---

## 登记与后续（本文件落盘时点）

- sha256 已登记 `ASSET-MANIFEST.md` §1（specs-v2 规格资产行）；`specs-v2/README.md`
  §0 交付物清单 ADDENDUM.md 行 ⏳→✅。
- **spec_ref 后续（未随本文件完成）**：受影响套件（m1/m4/m5/m6；m3 为 v1 四文件
  口径、m0 为 v1 基线对）的 spec_ref 仍引 `specs/ADDENDUM.md` v1 原文，本文件落盘后
  按 01 v2 §6 重算 spec_hash 并再登记属**后续动作**（`specs-v2/DEVIATIONS.md:193-197`
  未决项 4；`tests/CHANGELOG.md` 2026-09-29 M4 节注记）。本轮零 tests/ 套件改动，
  spec_hash 口径不变，门禁按现行登记对全绿。
- `specs-v2/DEVIATIONS.md` §KNOWN-DEFECT 与未决项第 4 条的前半句（"ADDENDUM 未
  产出 / README 该行仍 ⏳"）自本文件落盘即消解；该台账为冻结资产不改写，以本节存照。
