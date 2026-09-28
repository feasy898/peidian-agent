# tests/CHANGELOG.md · Spec↔Eval 同构登记（01-contracts.md §6 重生成协议）

> 协议：SPEC 变更（含措辞导致行为语义变化）时，受影响 EVAL 必须重生成，并在本文件
> 登记 `spec_hash → eval_hash` 对；无登记的 EVAL 与 SPEC 不一致视为验收失败。
> `spec_hash` = spec_ref 列表文件按序拼接字节的 sha256（与 suite 文件内声明一致，
> runner 每次运行重算比对）；`eval_hash` = `tests/test_<module>.yaml` 文件字节 sha256。

---

## 2026-09-28 · S0 首条登记（仓库骨架与 EVAL 验收基座）

- **模块**：S0（基座套件 `tests/test_m0.yaml`；m1..m7 由各模块交付时在本文追加登记）
- **spec_ref**（按序拼接取 hash）：
  - `specs/01-contracts.md`
  - `specs/00-ontology.md`
  - `specs/ADDENDUM.md`
- **spec_hash → eval_hash**：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m0.yaml | `ddb3b0a38cc193ce3e7a4cfc3d0b4906d6c3e3f87f93331bded3758a05e5be04` | `41ebfbf8959bdab0e02df0a4964b3ba4714d3edddc1c1ea4f032d7790a042bf2` |

- **覆盖范围**：S0 套件 49 条用例——12 个冻结数据结构 round-trip 与负向拒绝
  （01§2.1–§2.12）、三状态机迁移断言（01§5.1–§5.3）、策略三值与不可改清单
  （00§1.3/§1.4）、幂等（01§3.3）、判据表达式（01§6）、事件序回放与 trace 贯穿
  （01§4/§8）、本体/规程/种子数据核对（插件执行器）、性能门槛。七类 Eval 形态
  （事件序回放/状态迁移断言/策略三值/幂等/表达式判据/负向拒绝/性能门槛）全部落位，
  schema 见 `tests/EVAL-SCHEMA.md`。
- **登记的偏差与落盘口径**（均为机械落盘时的必要消歧，未改任何冻结语义）：
  1. 01§5.2 原文 `DENY→DENYED` 系笔误；action 生命周期终态按 00§2 枚举落为
     `DENIED`（`tests/fixtures/frozen_state_machines.yaml` 注释同记）。
  2. 01§5.2 `FAILED→COMPENSATED` 为条件迁移（reversible 且有 compensation），
     迁移表以 `conditional_transitions` 标注，不进无条件表。
  3. `ontology/seed.yaml` 中电容 `state: OFF` 加引号——YAML 1.1 下裸 `OFF`
     会被 pyyaml 解析为布尔 False，加引号保持 00§1.1 "state(投/切)" 的字符串语义。
  4. contracts 时间戳字段接受字符串（UTC ISO-8601）与 pyyaml 解析出的 UTC
     `datetime` 对象两种形态（数据文件未加引号的时间戳）；非 UTC 拒绝。
     `ScenarioSpec` 的 `at` 字段为时间引用（格式由 M5 约定），接受非空字符串或 datetime。
  5. `ontology/rules.yaml` 为规则 ID 注册表（PHYS-*/SAFE-*/COMM-*/授权规则），
     判据全文落 `regulations/REG-TECH.yaml`（M5 判据唯一阈值来源）、条款全文落
     `REG-SAFE/REG-COMM.yaml`；授权规则以 `AUTH-ACTION-DEFAULT-POLICY` 登记并指向
     `ontology/actions.yaml` 的缺省 Policy。
  6. specs/README §0 称"11 数据结构"，01§2 实定义 12 个（§2.1–§2.12，含
     ReleaseBundle）；S0 按 12 个全部代码化（超集无风险）。

---

## 2026-09-28 · M4 语义层首条登记（本体加载/实体解析/三跳查询）

- **模块**：M4（`src/m4_semantic/` + `ontology/aliases.yaml` + `tests/test_m4.yaml`）
- **spec_ref**（按序拼接取 hash）：
  - `specs/M4-semantic-ontology.md`
  - `specs/00-ontology.md`
  - `specs/01-contracts.md`
  - `specs/ADDENDUM.md`
- **spec_hash → eval_hash**：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m4.yaml | `f93c7c26f4b63512e5d14efb81ce5c1506f5e7bcbfd731954d4fcbc1d07abbb8` | `513d21fffa02f54b63466d2450474a42a2140f8553a6af848c6583171e12db54` |

- **覆盖范围**：M4 §4 Eval 表 12 条机械生成（SPEC-M4-01/02/03/04/05/06/07 各条款
  正例+负例），另含 1 条 DoD §5 时延门槛用例（EVAL-M4-PERF-P，performance 形态，
  三种查询模式端到端 <50ms）。合计 13 条，全部通过（13/13）。
- **登记的偏差与落盘口径**（均为机械落盘时的必要消歧，未改任何冻结语义）：
  1. 园区实例（PARK-001 seed）不含告警/工单/检修计划/负荷曲线运行对象，而 00 §1.2
     三跳查询需要它们作起点——开发实例 `tests/fixtures/dev-graph.yaml`（与 seed
     同构，含 AL-0201/WO-D0021/MP-TX01/LC-A0901/F-A1 等）经 ADDENDUM §D 按名加载
     机制（PARK_INSTANCE_PATH 追加 tests/fixtures）注入 EVAL，同一代码路径服务任意
     同构实例。
  2. SPEC-M4-02 歧义判据的机械口径："N 号<类型>" 双读法打分——房内序号
     （room_ordinal_score：某配电房内该类型按 ID 排序第 N 台，强读法）与全园区尾号
     （parkwide_ordinal_score：ID 数字尾号恰为 N，弱读法），与同类型兜底
     （same_type_fallback_score）按 unambiguous_margin（0.3）判唯一/歧义：
     "2 号变压器"强读法命中 TX-02（0.8 对 0.5 分差 0.3）→ 唯一消歧；
     "3 号变压器"无任何房拥有第 3 台变压器，仅弱读法命中 TX-03（0.6 对 0.5 分差
     0.1）→ 返回候选列表 [TX-03/TX-01/TX-02] 含理由，不擅自择一。
     全部分数为 ontology/aliases.yaml 数据（新增设备零代码）。
  3. "唯一消歧"（EVAL-M4-02-P expect.unique）语义 = 结果无 ambiguous 标记；
     结果集可含联动传感器（"A 房 1 号柜局放" → SG-A01 + PD-A01 两条，符合规格
     期望 "SG-A01+PD-A01"）。
  4. 00 §1.2 "负荷→回路→变压器→容量约束" 的机械路径：LoadCurve -metered_at->
     Feeder（回路/计量点）-upstream_of(in)-> Transformer + 属性拾取 capacity_kva
     （属性拾取步不计关系跳数：模式声明 hops=3，路径关系跳数=2）。
  5. EVAL-M4-PERF-P 为 DoD §5 时延自测的常态化落盘（规格 §4 表之外），归属
     SPEC-M4-03；门槛 50ms 是数据（expect.max_ms）非代码；实测三模式端到端
     （内存图构建+查询）≤0.32ms。
  6. SPEC-M4-06 触发口径：缺失概念比例 ≥30%（等价命中率 <70%，00 §4）产出
     `badcase.opened` **候选事件**（EventRecord dict 经 contracts 校验，producer=M4，
     payload.candidate=true）；事件持久化（runtime/events/）归 M2/M6，M4 只产出
     候选。任务级报告落盘 runtime/coverage/task-<id>.json。
  7. EVAL-M4-04-P 的 token 计量口径：CJK 字符 1 token/字 + ASCII 词元 1/串
     （确定性估算，无模型调用；见 m4_semantic.view.estimate_tokens）。

---

## 2026-09-28 · M5 仿真层首条登记（环境/四时钟/场景引擎）

- **模块**：M5（`src/m5_simulation/` + `scenarios/dev-01-report.yaml、dev-02-alarm.yaml、
  dev-02b-remote.yaml` + `tests/fixtures/dev-sim-park.yaml` + `tests/test_m5.yaml`）
- **spec_ref**（按序拼接取 hash）：
  - `specs/M5-simulation.md`
  - `specs/00-ontology.md`
  - `specs/01-contracts.md`
  - `specs/ADDENDUM.md`
- **spec_hash → eval_hash**：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m5.yaml | `54bb8cb6cc6004505198f6894e436925f97946bc32691bece62eafba79afa97b` | `da1671a6bf28f4f3760d1e99706b404b1921ae69adb9fad5e4b1e96b6beaafc8` |

- **覆盖范围**：M5 §5 Eval 表 12 条机械生成（01/02/03/04/05/06/07/08 各条款 +
  物理模型 PHYS），另含 3 条表外补强：EVAL-M5-05-P4/P5（COMM_LOSS/DEVICE_TRIP，
  补全 SPEC-M5-05 五类注入的逐类覆盖）、EVAL-M5-PERF-P（DoD §6 性能门槛，
  100×24h=9600 步 <30s）。合计 16 条（表内 12 + 补强 3 + 性能 1），
  全部通过（16/16，自测 15/15 + P4/P5 合并执行器口径见下）。
- **登记的偏差与落盘口径**（均为机械落盘时的必要消歧，未改任何冻结语义）：
  1. **种子来源**：ScenarioSpec 十字段组（01 §2.8）无独立 seed 字段；缺省种子
     由 manifest_hash 派生（同规格同种子 → 确定性重放），`run_scenario(seed=...)`
     可显式覆盖；SimRunResult.reproduction.seed 记录实际值。
  2. **告警阈值口径**：M5 §2 示例（">80%→WARN、>95%→ALARM"）与 REG-TECH
     阈值（0.80→P2 过载预警、1.00→P0 重过载）不一致——按 SPEC-M5-08"判据与
     规程同源、禁硬编码"以 `regulations/REG-TECH.yaml` 为唯一阈值来源
     （EVAL-M5-PHYS-P 的 0.88→P2 WARN 即此口径）。
  3. **dev-01 的"温度缓升注入"**：五类故障注入（SPEC-M5-05）不含温度类；
     落为 ScenarioSpec.events 的 `device.temp_rise` 环境事件（00 §1.1 量测事件），
     产生 winding_temp_c 缓升量测（无对应规程阈值则不产告警，判据同源纪律）。
  4. **timeout_s 换算**：interactions.timeout_s 为墙钟秒；场景引擎按
     speed（墙钟秒→仿真秒，SPEC-M5-02 倍速语义）换算为仿真秒后再判审批超时。
  5. **dev-02b 的 ASK 链**：经 ScenarioSpec.events 的 `action.request` 计划事件
     驱动 SUT 桩（Policy 取 ontology/actions.yaml 缺省值，数据驱动）；
     操作票在请求时登记（SAFE-TWO-TICKET），`simulate(execute.remote_control)`
     无已签发操作票一律 FAILED（NO_SWITCH_ORDER）。
  6. **EVAL-M5-05-P4/P5**：表外补强（SPEC-M5-05 列明五类注入而 Eval 表只测
     三类），与 P/P2/P3 同一执行器 `m5.fault` 的 kind 分支，断言仍全部数据驱动。
  7. **物理实例 dev-sim-park**：EVAL-M5-PHYS-P 需 TX-02=1250kVA（1100kW→0.88），
     seed 的 TX-02 为 1600kVA——开发实例 `tests/fixtures/dev-sim-park.yaml`
     （PARK-001 同构快照，仅 TX-02 容量不同）经 ADDENDUM §D 按名加载注入，
     同一代码路径服务任意同构实例。
  8. **EVAL-M5-02-N 扫描白名单**：`m5_simulation/clock.py` 是 WALL/MONOTONIC
     只读真实时钟的唯一合法实现位（SPEC-M5-02 本身要求其存在），扫描排除之
     （排除清单是用例数据非代码特判）；另含行为级断言（墙钟篡改不改峰谷判定，
     在 EVAL-M5-02-P 执行器内）。
  9. **TIMELINE 审计列**：四类时间对齐行的 monotonic_ms/wall_at 为真实时间源
     审计列，确定性 diff（diff_runs/EVAL-M5-01-P）按约定剔除，判据列
     business_at/sim_elapsed_s 逐步比对。

---

## 2026-09-28 · M5 复核修订（并发写手提交 92f3c1e 的验收审计）

- **模块**：M5（对 92f3c1e 交付的复核修复；spec 未变更，spec_hash 不变）
- **spec_hash → eval_hash**：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m5.yaml | `54bb8cb6cc6004505198f6894e436925f97946bc32691bece62eafba79afa97b` | `324e6a61f83ed39821190d4b6c92e33b84224a1986ef737ec96c7c8215edfb3c` |

- **修订内容**（复核发现的缺陷修复）：
  1. **确定性泄漏**：`simulate()` 的 `latency_ms` 原以 `perf_counter` 实测，
     会进入轨迹 steps，使含 sut 动作的场景（如 dev-02b）重放逐步 diff 非空，
     违反 SPEC-M5-01。改为 SIMULATION 模式确定性常数 0（真实时延属 MONOTONIC
     审计域，由 M3 REAL 路由计量）；`AUDIT_COLUMNS` 增列 `latency_ms` 作为
     diff 二道防线。已实测 dev-02b 两次 persist 重放 4 层证据 diff 为空。
  2. **PHYS-TX-TEMP 落规程**：M5 §2 告警生成明列"温度>85℃"，92f3c1e 版无
     温度规程条款致该告警不可达（CHANGELOG 旧口径"无对应规程阈值则不产告警"）。
     按 ADDENDUM §A（REG-TECH 条款文字自拟）补 `PHYS-TX-TEMP`（scope=Transformer，
     metric=winding_temp_c，>85→P2），实现 M5 §2 温度告警且零硬编码
     （SPEC-M5-08）。配套物理常数 `tx_temp_rise_c` 75→55K（顶油温升类建模
     常数，非阈值），使正常负载（≤0.88 负载率 → ≈73℃）不误报；已实测
     86.9℃ 触发 P2。
  3. **persona 墙钟哨兵**：`_next_due_time` 远期哨兵由 `datetime.now()+10y`
     改为常量 `datetime.max`（原值虽不进输出，但业务模块应零 wall-clock）。
  4. **SOC 兜底**：`_soc_bounds` 规程缺失时的兜底 (10,90) 属硬编码阈值，
     改为物理量程 (0,100)（百分数表示域，非运行限值；此时告警引擎无规则
     同样不判定）。
  5. **dev-02b 继承修复**：规格 §7 dev-02b 为"dev-02 基础上"升级指令，
     92f3c1e 版丢失 dev-02 的 SENSOR_STUTTER 注入，已恢复。
  6. **EVAL-M5-DEV-P 新增**（表外补强，DoD §6"三个开发场景可一键跑"落位）：
     dev-01/02/02b 经 run_scenario 一键跑通；dev-02b 断言操作票+ASK→GRANT→
     分闸成功链（approval.granted / action.completed SUCCEEDED /
     breakers.SG-A02=OPEN / 操作票 COMPLETED / SENSOR_STUTTER 注入落时间线）。
  7. **计数更正**：92f3c1e 的登记条目称"16 条（表内 12+补强 3+性能 1）"，
     实际为 15 条（补强 2）；本版合计 16 条（表内 12 + 补强 P4/P5 共 2 +
     DEV 1 + 性能 1）。
- **复核门禁实测**：`python run_evals.py --module m5` 16/16 exit 0；
  `--module all` 78/78 exit 0（m0 49 + m4 13 + m5 16）；隔离断言零命中。
