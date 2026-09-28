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

---

## 2026-09-28 · M2 信息层首条登记（Context/状态/Artifact/Memory/Skill 披露）

- **模块**：M2（`src/m2_information/` + `src/m2_information/FORMATS.md` +
  `tests/test_m2.yaml` + `src/m2_information/eval_plugin.py`）
- **spec_ref**（按序拼接取 hash）：
  - `specs/M2-information.md`
  - `specs/00-ontology.md`
  - `specs/01-contracts.md`
  - `specs/ADDENDUM.md`
- **spec_hash → eval_hash**：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m2.yaml | `00756a50360d11fa5f1f71baf038139d4caffc1c1fb5ad8be79efde50c717e00` | `b658309ab823b56ee0bd94b6ff1957435b7366d19023b5acc56198d1074ac5f8` |

- **覆盖范围**：M2 §4 Eval 表 16 条机械生成（SPEC-M2-01/02/03/05/07/08/10/11/12
  各条款正例+负例），另含 6 条表外补齐——01§6 要求每条 SPEC 条款至少映射一个
  用例，而 §4 表缺 SPEC-M2-04/06/09 行：补 EVAL-M2-04-P（Manifest 完整）、
  EVAL-M2-06-P（Checkpoint 全量+恢复）、EVAL-M2-09-P/09-N（evidence/ 门禁正负）、
  EVAL-M2-08-P2（task/artifact 迁移表与 frozen_state_machines.yaml diff 为空）、
  EVAL-M2-EVLOG-P（DoD §5：空库事件重建 TaskState 与快照 diff 为空）。
  合计 22 条，全部通过（22/22）。
- **登记的偏差与落盘口径**（均为机械落盘时的必要消歧，未改任何冻结语义）：
  1. **ContextManifest 裁剪记录**：01§2.4 的 source 五字段为封闭集（contracts
     check_keys 拒绝未知字段），裁剪记录以双落方式留档——被裁源在 Manifest 内
     `tokens=0` 留存、`origin` 追加 `;trimmed=dropped@priority=<P>` 注记；完整
     trim_log/filter_log/conflicts/directives 落 `workspace/manifest/turn-<n>.json`
     编译记录（FORMATS.md §3.4）。
  2. **非状态字段的状态提交事件**：01§4 事件目录无 task.updated；非状态字段
     （todos/plan/budget/context_manifest_hash 等）提交落 `task.status_changed`
     且 `from==to`、载荷带 mutation/version/updated_at，事件重建按同一
     `apply_state_mutation` 折叠（单一变更语义口径）。非法迁移拒绝事件
     `accepted=false`，重建时跳过。
  3. **审计事件主题**：跨任务写拒绝与 Knowledge 只读拒绝需落审计事件，但事件
     目录无独立安全主题——落 `action.policy_decided {decision: DENY,
     capability: workspace.write_cross|knowledge.mutate}`（producer=M2）。
  4. **policy 永不裁的负向口径**（EVAL-M2-03-N）：仅剩 SYSTEM_POLICY 层仍超预算
     时拒绝编译——落 `budget.exhausted {kind: token}` 并将任务 RUNNING→PAUSED
     （合法迁移），抛 `ContextBudgetExceededError`；不产出超额 Manifest。
  5. **write_memory 契约哨兵**：01§3.2 返回 `MemoryId | REJECTED`——六问未过
     返回字符串 `"REJECTED"`（不抛错），最近拒绝原因存
     `MemoryStore.last_rejection`；SPECULATIVE 归因 verification 问。
  6. **Skill 披露面**：SPEC-M2-12 仅明令"未注册与 DEPRECATED 不出现在任何层"；
     实现默认可见状态为 PUBLISHED（DRAFT/REVIEW 未过 M7 发布门禁同样不入层，
     可经 `SkillRegistry(visible_status=...)` 调整）；level0 ≤10 词在注册时强校验
     （词数口径：CJK 每字 1 词，ASCII 按空白分词）。任务能力域与 skill 域的匹配
     为集合交集（task_domains 为编译入参，来自任务目标/动作元数据）。
  7. **超集表**：StateStore 在规格四表（task_state/artifacts/memory/checkpoints）
     之上增 knowledge/sessions/calls 三表（Knowledge 只读条目与 Call⊂Session⊂Task
     三级管理），不违反规格最小集。
  8. **PostgreSQL 迁移位**（DoD §5）：`StateStore(dsn)` 连接串可配；
     `postgres*` 抛 NotImplementedError（本期不实现）。
  9. **hash 确定性输入**：sha256(规范 JSON{task_id, turn, version, sources 五元组,
     total_tokens})；`compiled_at`（时钟）与 ULID 随机量不进 hash；System 层源
     origin 携带内容 hash、Skill 源 origin 携带 `skill_id@version` 指纹，资产
     版本变化必然翻转 hash。
  10. **电价语义隔离**：M2 无电价判定义务；CI 墙钟扫描口径下 m2_information
      源码不含任何电价标记词，真实时钟仅存在于 ids.py/timestamps.py
      （时间戳落盘用途，非电价判定）。
- **复核门禁实测**：`python run_evals.py --module m2` 22/22 exit 0；
  `--module all` 100/100 exit 0（m0 49 + m2 22 + m4 13 + m5 16）；隔离断言零命中。

---

## 2026-09-28 · M3 行动网关首条登记（Policy 三值/审批/幂等）

- **模块**：M3（`src/m3_action/` + `tools/` 16 个动作适配器 + `tests/test_m3.yaml` +
  `tests/negative_matrix.yaml` + `src/m3_action/eval_plugin.py`）
- **spec_ref**（按序拼接取 hash）：
  - `specs/M3-action-gateway.md`
  - `specs/00-ontology.md`
  - `specs/01-contracts.md`
  - `specs/ADDENDUM.md`
- **spec_hash → eval_hash**：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m3.yaml | `91b5cab10ea229719052f1b9498ea75eeb17d539ebf94734f76885c40a4eaa8c` | `0579c547d5380180657c08ec9bec6297a74b9287df78ef11f388a68115e3c8de` |

- **覆盖范围**：M3 §4 Eval 表 15 条机械生成（SPEC-M3-01..11 各条款正例+负例），
  另含 8 条表外补强——EVAL-M3-01-N2（已注册未披露角色，SPEC-M3-01 后半）、
  03-P2（不可改清单双重表达+生命周期表 vs frozen_state_machines diff 空，DoD）、
  05-N3（GRANT 只放行单次不改缺省）、07-P2（approval 队列重启持久化，DoD §5）、
  08-P2（执行器崩溃 claim 后同 key 重试零二次副作用）、10-N/N2/P2（REAL 三重
  门禁逐级接线负向）。合计 23 条，全部通过（23/23）。
- **登记的偏差与落盘口径**（均为机械落盘时的必要消歧，未改任何冻结语义）：
  1. **准入失败不进生命周期**：契约/注册/披露/schema/路由（REAL 被拒）失败发生
     在 01§5.2 REQUESTED 之前，状态 REJECTED（SPEC-M3-01/02 口径），不落
     `action.requested`（不进事件主链）；审计事件沿用 M2 先例落
     `action.policy_decided {decision: DENY, stage: admission}`（事件目录无
     error.* 主题，producer=M3）。
  2. **不可改清单对 ASK 锁定动作拒绝一切覆盖**（含收紧 ASK→DENY）——与
     tests/EVAL-SCHEMA.md §2 policy_decision 参照语义（policy_locked 任何覆盖
     被拒）一致；SPEC-M3-11 矩阵对 execute.remote_control 期望缺省 ASK
     （WAITING_APPROVAL，不执行，零副作用同样成立）。
  3. **SPEC-M3-06 收紧基准=当前生效判定**（已存覆盖优先于缺省）：已收紧为 ASK
     的角色再请求 ALLOW（即使 ALLOW==缺省）属放宽，拒绝且维持 ASK。
  4. **tools/ 布局**：16 个动作适配器位于仓库根 tools/（01 §1 目录树约定，
     每个 action 一个模块，模块名=动作 ID 的 "."→"__"）；pyproject 仅打包 src/
     包，EVAL/运行从仓库根装载（registry 兜底把仓库根加入 sys.path，pathlib
     推断不依赖 cwd）。参数 schema/幂等键策略/披露面来自适配器声明，风险/缺省
     Policy 来自 ontology/actions.yaml（数据权威，装配即断言 diff 空）。
  5. **幂等键策略两档**：CALLER_PROVIDED（原样采用，读/分析类）与
     CALLER_PROVIDED_UNIQUE_ARGS（同 key 不得承载不同 (capability, arguments)，
     写/执行类——冲突 REJECTED/KEY_CONFLICT，不进主链）。
  6. **幂等 write-ahead**：runtime/m3_action/idempotency.jsonl 在副作用前先落
     claim；崩溃后同 key 重试命中 claim 返回首个结果不执行（EVAL-M3-08-P2 以
     M5 state_final 快照 diff 验证零二次副作用）。
  7. **审批持久化**：runtime/m3_action/approvals.jsonl（enqueued/resolved/
     expired 重放重建 pending，条目携带完整 ActionRequest——重启后 GRANT 仍可
     继续执行，EVAL-M3-07-P2）。
  8. **失联执行器建模**：gateway `isolate_execution_env` 选项让执行落在
     env.deep_copy()（执行器在副本上自报成功），observer 独立回读真实环境发现
     未兑现 issued 声明 → 降级 FAILED/OBSERVATION_MISMATCH（SPEC-M3-09
     "自报成功不构成 observed" 的可测落位）。
  9. **trace/事件确定性**：ActionRequest 无 trace 字段（01§2.1 冻结不可加），
     trace_id 从 task 派生（`trace-<task_id>`）；event_id 为流内递增序号
     （EVT-M3-<seq>，journal 重放续序）；SIMULATION latency_ms=0（与 M5 复核
     口径一致，真实时延属 MONOTONIC 审计域）。事件分片与 M2 同名
     `task-<task_id>.jsonl`；EVAL 用例事件流隔离在 runtime/m3_eval/<case>/events。
  10. **REAL 门禁三重**：非评估上下文 + 环境变量 PD_REAL_MODE + 双人开关
      （两个不同审批人 id）齐备才路由 REAL，且仅 mock 适配器
      （FAILED/REAL_MOCK_ONLY）；评估上下文（gateway evaluation=True 或
      PD_EVALUATION 置位）强制 SIMULATION（01 §8 仿真即默认）。
  11. **时间纪律**：m3_action 无电价语义；唯一墙钟读取位是 clocking.now_iso()
      （审批超时缺省与事件时间戳缺省，EVAL 一律显式传 now 不触墙钟）。
- **复核门禁实测**：`python run_evals.py --module m3` 23/23 exit 0（重复运行
  结果稳定）；`--module all` 123/123 exit 0（m0 49 + m2 22 + m3 23 + m4 13 +
  m5 16）；隔离断言零命中。

---

## 2026-09-28 · M5 复核修订 II（M1 交付联动：persona LLM 接线激活）

- **模块**：M5（`src/m5_simulation/eval_plugin.py` 的 EVAL-M5-04-P 执行器；
  spec 未变更、`tests/test_m5.yaml` 未变更——spec_hash/eval_hash 登记对不变）
- **修订内容**：M1 交付 model_client（mock provider 全离线可用）后，SPEC-M5-04
  "LLM 生成模式（接口预留）……M1 交付后此路径自动生效，无需改本模块" 的预留
  路径被激活：persona_step(mode="llm") 经 mock provider 正常产出（mode=llm、
  零降级），占位期断言"LLM 必走降级路径"随之失效。执行器更新为交付后口径：
  mock 正常产出 + 失败 provider（openai_like 缺端点）仍走降级回退（degraded
  标记）。由 M1 交付触发，登记于 M1 首条登记（见下节）联动说明。
- **复核门禁实测**：`--module m5` 16/16 exit 0；`--module all` 143/143 exit 0。

---

## 2026-09-28 · M1 执行内核首条登记（Loop/状态机/完成验证）

- **模块**：M1（`src/m1_core/` 全部源码 + `tests/test_m1.yaml` +
  `src/m1_core/eval_plugin.py`）
- **spec_ref**（按序拼接取 hash）：
  - `specs/M1-agent-core.md`
  - `specs/00-ontology.md`
  - `specs/01-contracts.md`
  - `specs/ADDENDUM.md`
- **spec_hash → eval_hash**：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m1.yaml | `c8a2cd2b51a8462b74d1f8877515cd3a2e2583d2b8c636de7481badea44589ec` | `b0f28d6ae30493471d7017ea83f6087edd0d20cd2961e4fe9e4d6b58cb122dd3` |

- **覆盖范围**：M1 §4 Eval 表 14 条机械生成（SPEC-M1-01/02/03/04/05/06/07/09/10
  各条款正例+负例），另含 6 条表外补强——EVAL-M1-TABLE-P（DoD：迁移表硬编码 vs
  frozen_state_machines.yaml 双写 diff 空 + 10 态全矩阵守卫）、EVAL-M1-05-P2
  （SPEC-M1-05 四口径矩阵：token/action/deadline/时段窗口）、EVAL-M1-GATE-P2
  （SPEC-M1-04 §2 门禁三条件的阻断告警口径与清除恢复）、EVAL-M1-MW-P
  （SPEC-M1-08/DoD：全移除/单移除中间件后 01/02/06 场景语义不变 + 注册序执行）、
  EVAL-M1-MODEL-P/P2（model_client mock 离线确定性/脚本化成本/耗尽 +
  openai_like 传输注入重试/超时分类/密钥透传；M5 persona LLM 模式离线接线回补）。
  合计 20 条，全部通过（20/20）。
- **登记的偏差与落盘口径**（均为机械落盘时的必要消歧，未改任何冻结语义）：
  1. **五阶段回放数据源**：01 §4 事件目录为冻结封闭集（无 loop 阶段主题），
     Loop 五阶段序的回放校验数据源为 M1 运行期审计件
     `runtime/<root>/m1_core/loop/task-<id>.jsonl`（LoopTrace 追加写；权威状态
     仍在 M2，此为 M3 幂等 journal 同类的审计件）。校验规则：每轮阶段序必须是
     PREPARE→MODEL→ACT→OBSERVE→VERIFY 的前缀（仅 PREPARE=预算中断轮合法）。
  2. **成本上报事件主题**：事件目录无 model.*/cost 主题——SPEC-M1-10 的每轮
     cost 字段以 `budget.warning {kind: token, remaining, cost{…}}` 兼作上报
     通道（保留 kind/remaining 语义字段并扩展 cost；沿用 M2"无独立审计主题时
     就近落主题"先例）。
  3. **完成门禁的位置**：无 Claim 的 COMPLETED 拒绝在 M1 守卫层
     （TaskStateMachine 的 is_completable 门禁 + CompletionRequiredError，
     为 IllegalTransitionError 子类）；拒绝事件 payload 同时带
     `rejected: true`（SPEC-M1-02 口径）与 `accepted: false`（M2 事件重建
     协议跳过口径）。
  4. **产物过门匹配口径**：plan.artifacts_expected 条目按 artifact_id 精确
     匹配或 schema_id 匹配（计划先于产物存在，ULID 无法预知；两口径同时支持，
     不针对特定实例硬编码）。
  5. **产物自动落位**：write.report SUCCEEDED 后由 loop 产物策略（数据驱动
     DEFAULT_ARTIFACT_POLICY，构造可覆盖）落 M2 ArtifactRecord：
     DRAFT→VALIDATING→（校验过）READY 两步迁移（M2 ArtifactManager 语义），
     同 action_id 重复入账幂等跳过（Checkpoint 恢复重放不产生重复产物）。
  6. **预算耗尽判定口径**：used ≥ max 即视为租约耗尽（无余量进入下一轮模型
     调用）；deadline 判 now > deadline；时段窗口判 now ∉ [from, to]。比较基准
     一律为注入的 now（EVAL 固定时钟；生产缺省 clocking.now_iso——m1_core 内
     唯一真实时间源读取位，budget.py/loop.py 零墙钟）。
  7. **M5 persona LLM 接线激活**（联动上文"M5 复核修订 II"）：M1 model_client
     mock provider 落地后 persona_step(mode="llm") 零降级可用；失败 provider
     降级路径保持（EVAL-M1-MODEL-P2 + 更新后的 EVAL-M5-04-P 双侧覆盖）。
  8. **PAUSED 恢复语义**：PAUSED 接受任意 ResumeEvent 种类，但恢复前重查预算
     ——仍超限则拒绝恢复（LoopNotResumableError，任务保持 PAUSED）；WAITING_*
     各态只接受 01 §3.1 对应种类，错配即拒。
  9. **trace 轮次台账**：轮号取自 LoopTrace 日志最大轮号 +1（TaskState 无轮次
     字段且冻结不可加）；Checkpoint 恢复后轮号继续递增（审计连续），任务语义
     续跑点由 plan 当前阶段 + todos 决定（SPEC-M1-09）。
- **复核门禁实测**：`python run_evals.py --module m1` 20/20 exit 0（含突变
  验证：改迁移表/拆完成门禁/废预算检查点/Observe 采信自述 四类故意破坏均被
  对应用例捕获）；`--module all` 143/143 exit 0（m0 49 + m1 20 + m2 22 +
  m3 23 + m4 13 + m5 16；连续 8 次全绿）；隔离断言零命中。

---

## 2026-09-28 · M1 复核修订（独立复核发现的两处缺口修复）

- **模块**：M1（`src/m1_core/loop.py` 产物策略幂等入账 + `tests/test_m1.yaml`
  EVAL-M1-MW-P 场景补齐；spec 未变更，spec_hash 不变）
- **spec_hash → eval_hash**：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m1.yaml | `c8a2cd2b51a8462b74d1f8877515cd3a2e2583d2b8c636de7481badea44589ec` | `7307d4417bea4c860c0237e9e37c2514032c03a6566c748205f94a6f0d02aa28` |

- **修订内容**（复核 588da80 交付时实测发现）：
  1. **产物策略幂等入账补齐**：首条登记偏差 5 声明"同 action_id 重复入账
     幂等跳过"但实现缺失——复现实测：同幂等键（同 todo_id 同参数）重发
     write.report，M3 正确回放首结果零二次执行，但 loop 重复落第二条
     ArtifactRecord（2 条 READY）。补 created_by.action_id 去重守卫后实测
     1 条 READY、M3 执行计数 1、TaskState.artifacts 无重复。
  2. **EVAL-M1-MW-P 补 06 形态场景**：用例标题与 M1 DoD 均为"移除全部
     中间件后 EVAL-M1-01/02/06 仍通过"，但场景列表只有 01（report3）与
     02（ask_wait）。补 need_more 场景（write.report 缺 measurements 段 →
     产物 REJECTED → 完成申请 NEED_MORE_EVIDENCE；纯 run_task 可达，无
     seed 步骤依赖），三场景在 缺省/全移除/单移除(safety) 三态下语义一致。
- **复核门禁实测**：`python run_evals.py --module m1` 20/20 exit 0；
  `--module all` 143/143 exit 0；`--selftest` integrity=OK schema=OK；
  隔离断言零命中（scripts/ci_isolation.py 的 holdout 实例隔离正则对全部
  交付目录 grep 零命中）；src/ 电价词面文件墙钟 token 终扫零命中。
