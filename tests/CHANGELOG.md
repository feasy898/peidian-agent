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

---

## 2026-09-28 · M6 飞轮首条登记（轨迹/黄金集/判据引擎/Badcase/Skill 化）

- **模块**：M6（`src/m6_flywheel/` 六组件 + `golden/dev/` 12 条种子 + rubrics +
  MANIFEST + `src/m6_flywheel/JUDGE-SYNTAX.md` + `tests/test_m6.yaml` +
  `src/m6_flywheel/eval_plugin.py` + `tests/fixtures/mock_releases/mock-rel-0001.yaml`）
- **spec_ref**（按序拼接取 hash）：
  - `specs/M6-flywheel.md`
  - `specs/00-ontology.md`
  - `specs/01-contracts.md`
  - `specs/ADDENDUM.md`
- **spec_hash → eval_hash**：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m6.yaml | `4377e37c88459245433899a33b26675e9455a7755e1cd216ffb1235e862445fe` | `72c216b3ae5ee1b9cf1824455a6d53db7a5ba017d6f2dcdb8b8d22c2a0276a1d` |

- **覆盖范围**：M6 §4 Eval 表 11 条机械生成（SPEC-M6-01/02/03/04/05/06 正例+
  负例），另含 3 条表外补强——EVAL-M6-01-P2（四类步型全覆盖逐条对应+事件→步型
  冻结映射钉死在用例数据）、EVAL-M6-02-P2（DoD §5：12 条种子契约/来源标记/
  manifest hash/五维评分单齐备）、EVAL-M6-EVAL-P（DoD §5：evaluator 对 mock
  release 全流程离线可跑，12 种子全过，runs/ 归档+二次评估确定性）。合计 14 条。
- **登记的偏差与落盘口径**（机械落盘必要消歧，未改冻结语义）：
  1. **MODEL_CALL 事件足迹**：01 §4 事件目录无 model.* 主题；轨迹四类步型中
     MODEL_CALL 的判定口径=``budget.warning/budget.exhausted`` 且
     ``payload.kind == "token"``（M1 已把该通道兼作每轮模型成本上报——M1 登记
     偏差 2 的沿用），action 类预算事件归 STATE_CHANGE。
  2. **五维评分单位置**：GoldenCase 冻结契约拒绝未知字段（contracts.check_keys），
     rubric 评分单不内嵌案例文件，落 ``golden/dev/rubrics.yaml``（case_id →
     评分单，DEFAULT 兜底）；RUBRIC clause 按契约注释作评分锚定 ID（规则 ID 或
     行为目录条目 ID）。
  3. **mock release**：M7 未交付（releases/ 空），evaluator 的 release 解析序=
     ``releases/<id>/release.yaml``（M7 发布物优先）→
     ``tests/fixtures/mock_releases/<id>.yaml``（离线清单）→ 内建通用 mock；
     mock 行为全部数据驱动（events/injections/plan/expect_capabilities），零案例
     特判。黄金集 12 种子对 mock-rel-0001 全过（97.67/100）。
  4. **SPEC-M6-06 审计主题**：事件目录无 release.* 拒绝主题，调优侧直改 release
     状态的拒绝审计落 ``release.published {rejected: true, requested_status,
     reason}``（沿用 M1/M3"就近落主题+rejected 标记"先例）。
  5. **判据表达式引擎**：实现于 ``m6_flywheel.judges``（无 eval/exec，与
     EVAL-SCHEMA §3 最小语法同构），扩展 ``not in`` 成员否定（JUDGE-SYNTAX §1.3
     登记；不破坏最小语法集）。
  6. **黄金集目录形态**：12 条种子按 M6 §6 交付物口径直落 ``golden/dev/``
     （case_001..012.yaml）；加载器同时支持 01 §1 的 cases/ 子目录形态；
     MANIFEST.yaml 登记逐文件 sha256+来源标记（CI hash 校验基准），
     ``python -m m6_flywheel.golden_set verify golden/dev`` 可独立执行。
  7. **Badcase 决策规则**：candidate 在关联案例通过 且 总分（百分制=
     mean(rubric 总分)×20）≥ current 才 ADOPTED；A/B 报告须同 golden_set_version
     （同黄金集硬校验）；实验记录（两版分数+diff 用例）归档
     ``<archive_dir>/experiments/<badcase_id>.json``。
  8. **评估归档**：evaluator 结果落 ``runs/eval/<UTC 时标>-<release_id>/``
     （report.json + 逐案例事件流/轨迹 + release 快照）；EVAL 内运行归档进沙箱
     ``runtime/m6_eval/<case>/``，CLI 运行落仓库根 ``runs/``（runs/acceptance/
     已 gitignore，eval 产物不进 git）。
- **复核门禁实测**：`python run_evals.py --module m6` 14/14 exit 0；突变验证六项
  （删 APPROVAL 映射/废缺 trace 拒绝/badcase 无条件采纳/skillize 门槛降 2/
  ReleaseGuard 放行/篡改黄金案例文件）全部被对应用例捕获后恢复全绿；CLI
  （ADDENDUM §E）`--release/--golden/--mode` 三参实测（REAL 拒绝 exit 2）；
  隔离断言零命中。

---

## 2026-09-28 · M7 资产层首条登记（注册/版本/评审/Release + rel-0001 发布）

- **模块**：M7（`src/m7_registry/` 七组件 + `RELEASE-FORMAT.md` +
  `assets/agent_contract_v1.yaml` + `prompts/daily-inspection.yaml、
  prompts/overload-response.yaml` + `skills/overload-response/`（SKILL.yaml+SKILL.md）+
  `tests/test_m7.yaml` + `src/m7_registry/eval_plugin.py` +
  `tests/fixtures/m7_state_machines.yaml` + `tests/fixtures/mock_releases/rel-0001.yaml`
  + `releases/rel-0001/`（首个 Agent Release 发布物））
- **spec_ref**（按序拼接取 hash）：
  - `specs/M7-registry-release.md`
  - `specs/00-ontology.md`
  - `specs/01-contracts.md`
  - `specs/ADDENDUM.md`
- **spec_hash → eval_hash**：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m7.yaml | `63631346e9622b06421faca778f4c8106d050abbbed2c461d362941661253dc6` | `12da220ff3d4c8c193a84b0fd2e6de3478b1ef060405c83aaabe515cc35fbaa0` |

- **覆盖范围**：M7 §4 Eval 表 10 条机械生成（SPEC-M7-01/02/03/04/05/06/07 正例+
  负例），另含 6 条表外补强——EVAL-M7-01-P2（四类资产齐备+版本链纪律全查：
  重复注册/空转更新/显式 chain 改写全拒）、EVAL-M7-02-P（闭包正例：解析+打包
  通过）、EVAL-M7-02-N3（循环依赖→打包失败，规格明列而表缺）、EVAL-M7-03-P2
  （评审拒绝分支：跑分低于现行→REJECTED）、EVAL-M7-TABLE-P（DoD §5：评审流/
  Release 状态机与 fixture diff 空+非法迁移行为级拒绝）、EVAL-M7-REL-P（端到端：
  M6 实测→签名→资产评审→六要素打包→门禁→只写一次发布→manifest/签名/按发布物
  重跑复核）。合计 16 条。
- **登记的偏差与落盘口径**（机械落盘必要消歧，未改任何冻结语义）：
  1. **M7 §5 DoD 引用的"01§5.4"不存在**（01 §5 只有 5.1-5.3 三状态机）：评审流
     状态机按 M7 §2/§3 行为规格落盘（PROPOSED→EVALUATING→APPROVED→PUBLISHED，
     REJECTED/WITHDRAWN 分支），表驱动 `review.REVIEW_TRANSITIONS` 与
     `tests/fixtures/m7_state_machines.yaml`（新增 fixture，不动 S0 的
     frozen_state_machines.yaml）diff 为空；Release 状态机 DRAFT→GATED→PUBLISHED
     （PUBLISHED 后仅可 SUPERSEDED）同款落盘。
  2. **评审/资产审计事件主题**：01 §4 事件目录无 review.*/asset.* 主题——评审
     迁移落 `release.published {stage: review, from, to}`、publish 入口拒绝落
     `{stage: asset-publish, rejected: true}`（沿用 M1/M2/M3/M6"就近落主题+
     payload 细分"先例）；全部事件经 contracts.EventRecord 校验。
  3. **六要素的空值口径**：model_ref/ontology_version/golden_scores 非空、
     prompt/skill/tool_refs 非空列表才视为"已绑定"（空列表=要素缺失，缺一拒绝
     打包）；RELEASE-FORMAT.md §2 登记。
  4. **AgentContract 绑定通道**：冻结 ReleaseBundle（01 §2.12）无 agent 字段、
     不可擅改——AgentContract 资产绑定落发布目录 `agent_contract.yaml` 快照 +
     `manifest.yaml.agent_contract`（asset_id/version/sha256）；bundle_draft 必须
     携带 agent_ref（M7 自有子契约字段，非冻结结构字段），缺失拒绝打包。
  5. **M6 签名双层口径**：`by_domain.signature`（M7 侧 digest=sha256(canonical
     成绩载荷)）+ `attestation`（M6 侧凭证 `m6_flywheel.attest`：对评估报告逐
     案例成绩摘要签名，producer=M6）；校验链=digest 重算→run_ref 归档装载→
     attestation 重算→从归档重推全部成绩逐块相等。`import_golden_scores` 是
     唯一合法产出口（报告 release_id 必须等于打包 release；全部数字机械推导）。
     by_domain 四块：capability（六能力域）/category（四类目）/catalog（12 条
     种子逐条）/red_line（100% 断言记录）——目录映射来自 AgentContract 资产
     behavior_catalog（数据源，非代码）。
  6. **run_ref 解析序**：绝对路径 → release 目录内相对（发布后指向
     `evaluation/report.json` 副本，digest 不含 run_ref 故发布时改写不断链）→
     仓库根相对。
  7. **评审基线**：candidate 总分（M6 报告 totals.score_100，缺则 pass_rate×100）
     ≥ 现行已发布 release 的 golden_scores；无现行 release 时基线=0（首个
     release 无可回归基线）。M7 只消费 M6 结果（runs/eval/ 归档），不自己跑分。
  8. **资产存储**：JSONL journal（runtime/m7_registry/assets.jsonl）追加写+重放
     重建（M3 幂等 journal 先例）；chain 整数为版本链权威，描述子自身 version
     串（semver/v1）为 ref 组成部分；内容 hash 未变的更新拒绝（版本号不空转）。
     publish_asset 是资产置 PUBLISHED 的唯一入口（AssetStore._set_status 模块
     私有，无公开 setter）——SPEC-M7-03 无旁路的代码级落位。
  9. **M6 evaluator 解析序扩展**（向后兼容增补）：release 解析新增首位候选
     `releases/<id>/evaluation/cases.yaml`（发布物自带评估清单，重跑黄金集与
     发布前实测同源）；既有候选次序不变，M6 既有用例行为零变化（--module m6
     14/14 复测通过）。
  10. **rel-0001 发布物**：`PYTHONPATH=src python -m m7_registry.assemble
      --release-id rel-0001`（注册 20 项资产：PROMPT×2/SKILL×1/TOOL×16/AGENT×1，
      全部经评审流 publish_asset 发布 → M6 实测 12 种子全过 97.67/100 → 签名
      导入 → 六要素打包 → 门禁 5 项全过 → 只写一次发布）；已发布后 CLI 重入为
      只读复核模式（manifest/签名/黄金重跑，零写入）。发布前 M6 实测经
      `tests/fixtures/mock_releases/rel-0001.yaml`（与 mock-rel-0001 同源案例
      清单）解析。
- **并发写手协调登记**（M5 先例的同款情形）：本阶段开发期间另一会话
  （dwfrun-c5e0dc03 actor_1_5）并发写入了 `src/m6_flywheel/attest.py`、
  `m6_flywheel/__init__.py` 的 attest 导出（**采纳保留**——M6 侧签名凭证正是
  SPEC-M7-04"带 M6 签名"的签名源，本模块按偏差 5 双层口径集成消费）与一份
  SQLite 版 `m7_registry/assets.py`+`common.py`（**未采纳**——与在途的
  JSONL AssetStore 全管线互斥，快照存 runtime/concurrent_writer_snapshot/ 供
  审计）；其 23:03 对 assets.py 的覆写在落地前被本侧恢复版本覆盖（.mimosa
  hook-state 可考）。
- **复核门禁实测**：`python run_evals.py --module m7` 16/16 exit 0（含突变验证
  四项：publish 接受伪造评审记录/放行 floating 版本/门禁废红线检查/只写一次
  守卫放行——分别被 EVAL-M7-03-N/02-N/06-P/05-P+REL-P 捕获后恢复全绿）；
  `--module all` 173/173 exit 0（m0 49 + m1 20 + m2 22 + m3 23 + m4 13 +
  m5 16 + m6 14 + m7 16；rel-0001 发布前后各一轮）；CLI 复核
  `python -m m7_registry.assemble --release-id rel-0001`（verify 模式 12 种子
  重跑 1.0/97.67）；`python -m m6_flywheel.evaluator --release rel-0001` 按发布
  物评估清单重跑 PASS；隔离断言零命中。

---

## 2026-09-28 · 独立评审缺口修复（M2/M3/M5/M6 四模块六项）

- **模块**：M2/M3/M5/M6（独立评审 six findings 处置；spec 未变更，spec_hash 不变）
- **spec_hash → eval_hash**（受影响 suite 的新版登记）：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m2.yaml | `00756a50360d11fa5f1f71baf038139d4caffc1c1fb5ad8be79efde50c717e00` | `72820122d481b65f6edb5644949571615067d7757869ea80f3f1dedd26ea6157` |
  | test_m6.yaml | `4377e37c88459245433899a33b26675e9455a7755e1cd216ffb1235e862445fe` | `566aa15af27600d89f72eabe6e81adf5b9622325855db5044fbe306a0e24e2cb` |

- **修订内容**（评审 medium×3 全修、low×3 全处置）：
  1. **M6 黄金/红线链路真实化（medium）**：CaseRunner 原先由评估器自造
     action.policy_decided（抄 ontology 缺省 Policy）、按 mock 计划元数据合成
     approval.* 事件、自发 task.status_changed{accepted:true}——黄金跑分证明的
     只是 M5 simulate 内部检查+脚本计划。现改为：每条计划步经 **M3
     ActionGateway.execute_action** 全链（契约/注册/披露/schema 准入 → 幂等
     claim → PolicyEngine 三值判定（含角色/锁定语义）→ 审批队列 → SIMULATION
     路由 → Observer 环境回读+自报降级）；审批决断走真实
     submit_approval/check_approval_timeouts（COMM_LOSS 窗口内不放行 → 超时
     语义保留）；task 生命周期经 **M2 InformationLayer**（create_task +
     commit_state，01§5.1 迁移表+乐观锁校验，RUNNING→VERIFYING→COMPLETED
     合法路径）；mock 计划只声明「何时请求何能力+审批决定」，不再伪造事件。
     12 种子对真实链全过（97.67/100 不变）；M7 rel-0001 门禁复跑通过。
  2. **M4→M2 规则 ID 存在性联动接线（medium）**：ADDENDUM §B「M4 SPEC-M4-05
     联动校验规则 ID 存在性」原先只是 artifact.py 可选钩子、全仓无注入点。
     现 `m4_semantic.regulation.rule_id_checker()` 工厂（绑定
     RegulationIndex.unknown_rule_ids）注入全部 InformationLayer 构造点
     （m1/m2 eval_plugin、M6 CaseRunner）；新增 EVAL-M2-08-N2（report.daily@v1
     引用 PHYS-BOGUS-999 → REJECTED「规则 ID 不存在」）钉死联动行为。
  3. **M5 simulate 拒绝口径数据驱动+终态对齐（medium）**：删除第三份硬编码
     DENY 清单 `_DENY_ALWAYS_HINT`，改按 `ontology/actions.yaml` 的
     default_policy=DENY 现算（与 M3 registry.assert_immutable_consistency 同
     源，无交叉校验缺口）；该路径终态由 FAILED/POLICY_DENIED 改为 **DENIED**
     （01§5.2 冻结迁移 DENY→DENIED，与 SUT 桩链及 M3 gateway 一致）。
  4. **CI 隔离正则宽化（low）**：窄正则（OP-1 后接 0 再接 [1-4]）→ 宽正则 `OP-1[0-9]`（ADDENDUM §F
     原文 `OP-1x` 通配一位的等宽正则，覆盖 OP-1 开头后接一位数字的整段）；宽模式对全部
     交付目录实测零命中。
  5. **M3 审批终态幂等 journal 回写（low）**：submit_approval(DENY) 与
     check_approval_timeouts 原先只落事件不回写幂等 journal（同 key 重试返回
     过期 WAITING_APPROVAL）；现走 _finish → executor.complete，重试返回终态
     REJECTED（含 APPROVAL_DENIED/APPROVAL_TIMEOUT 错误码）。实测
     ASK→DENY→同 key 重试 与 ASK→超时→重试 均返回终态。
  6. **HOLDOUT.md 交付位置澄清（low）**：specs/README.md §0 的 HOLDOUT.md 行
     补注——该文件随验收包交付、由验收人独立保管，不进开发仓库（ADDENDUM §F
     红线：仓库任何路径不得出现 holdout 场景/实例/判据文件，CI 断言零命中）。
  7. **mock release 计划数据 schema 对齐**（1 的配套）：三份清单
     （mock-rel-0001.yaml / rel-0001.yaml / releases/rel-0001/evaluation/
     cases.yaml）+ test_m6 内联 A/B 计划的参数补齐为 gateway PARAMS_SCHEMA
     合规形态（write.report 四段齐、analyze.load_forecast 补 horizon_h、
     create.switch_order steps 转字符串数组、modify.protection_setting 的
     setting 转对象）——真实链准入校验生效后的必要数据修正。
- **复核门禁实测**：`python run_evals.py --module all` 174/174 exit 0（m0 49 +
  m1 20 + m2 23 + m3 23 + m4 13 + m5 16 + m6 14 + m7 16）；隔离断言（宽化
  正则）零命中。

---

## 2026-09-28 · 安全规程判据落地缺口修复（M3/M5 五项）

- **模块**：M3/M5（独立评审 SAFE 系 findings 处置；specs 未变更，spec_hash 不变）
- **spec_hash → eval_hash**（受影响 suite 的新版登记）：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m3.yaml | `91b5cab10ea229719052f1b9498ea75eeb17d539ebf94734f76885c40a4eaa8c` | `eb1a6b01093cdea59a119f3a549a5791fc948787b9176de8fce40dbbe32e4285` |
  | test_m5.yaml | `54bb8cb6cc6004505198f6894e436925f97946bc32691bece62eafba79afa97b` | `577055177ee5cf2b15f1b34c4afea454025b4d272fddc7e930dd74a818e2c0c2` |

- **修订内容**：
  1. **SAFE-ISSUE-HUMAN 强制（medium）**：`tools/create__switch_order.py` status
     枚举收窄为 `[DRAFT]`（原 `[DRAFT, ISSUED]` 缺省 ISSUED——agent 可零审批
     自铸已签发票）；M5 `simulate()` 对 `create.switch_order` 的非 DRAFT 请求
     一律 FAILED/`SAFE_ISSUE_HUMAN`（双保险：M3 准入 SCHEMA_INVALID 拒绝 +
     M5 判据层兜底）。DRAFT→ISSUED 的签发只能由持证签发人在 agent 动作集之外
     完成（M6 evaluator `issue_by` 场景人因签发 + M5 桩链预置票签发人角色校验，
     角色数据源=实例 `env.operators`）。
  2. **SAFE-ORDER-SEQ 强制（medium）**：`execute.remote_control` 的 step 与票面
     `steps` 声明顺序对照（跳步 → FAILED/`SAFE_ORDER_SEQ`）；多步票逐步放行、
     全部声明步骤完成才置 COMPLETED（执行中保持 ISSUED）。
  3. **SAFE-SINGLE-OP 强制（medium）**：票级 `executing` 执行流互斥标记——
     已有执行流的票再受执行 → FAILED/`SAFE_SINGLE_OP`（结束/异常均释放）。
  4. **M3 审批权 fail-closed（low）**：`submit_approval` 审批主体校验收紧——
     仅已登记且角色=审批人 可决断；未登记人员（角色 None）与实例未登记任何
     人员（actor_roles 为空）一律 REJECTED/`APPROVER_NOT_AUTHORIZED`（原实现
     对两种情形静默放行）。空花名册分支经直连 Python 用例实测。
  5. **EVAL-M5-02-N 扫描面补全（low）**：wall-clock 电价词面扫描 `scan_dirs`
     由 `[src]` 扩为 `[src, tools, scripts]`（SPEC-M5-02/README§4"业务代码"
     全口径；实测 tools/scripts 零违例）。
- **新增负向 EVAL**：EVAL-M5-SAFE1-N/SAFE2-N/SAFE3-N/SAFE4-N（执行器
  `m5.safety_rules`，断言数据全部取自用例 params/expect）、EVAL-M3-APPR1-N
  （未登记人员审批被拒）、EVAL-M3-APPR2-N（自签 ISSUED 票准入拒绝）。
  m5 套件 16→20 条、m3 套件 23→25 条。

---

## 2026-09-29 · 提交门禁安全修复（M1 model_client SSRF 边界）

- **模块**：M1（push 前安全扫描高危强制拦截项；`src/m1_core/model_client.py`
  `_urllib_transport` 对 `api_base` 拼接的端点 URL 无任何校验即
  `urllib.request.urlopen`——SSRF）。
- **修订**：新增 `_assert_safe_endpoint()` 在真实网络调用前强制校验（fail-closed）：
  scheme 仅 https（明文 http 须显式 `PD_MODEL_ALLOW_INSECURE_HTTP=1`）；拒绝
  URL 内嵌凭据（userinfo）；DNS 解析后全部地址必须公网（拒绝回环/私网/链路
  本地含云元数据 169.254.169.254/CGNAT 100.64/10/ULA/保留段）；tailnet/局域网
  端点经 `PD_MODEL_ALLOW_PRIVATE_HOSTS` 显式白名单放行（精确主机匹配）。
  注入 transport 的离线测试路径不触网、不受影响；实测公网放行、回环/元数据/
  私网/CGNAT/userinfo/明文 http 全拒、白名单与明文放行开关生效。
- **配套**：缺省传输由 `urllib.request.urlopen`（黑名单调用形态）改写为
  `http.client` 直连（HTTPS/HTTP 按 scheme、错误语义保持：非 2xx 原样返回
  (status, parsed)、超时→TimeoutError、网络错误→ConnectionError）；实测真实
  公网端点 POST 通路正常（无密钥 401 原样返回）。

---

## 2026-09-29 · M6 EVAL v2 重生成（specs-v2 反提：SPEC-M6-01..08 → 19 条）

- **模块**：M6（`tests/test_m6.yaml` 整体重生成；`specs-v2/M6-flywheel.md` §4
  条款↔用例双向映射表同步更新、§5/§6 条数修订 14→19）
- **spec_ref**（按序拼接取 hash；v2 起指向 specs-v2——本套件用例的 spec 字段
  引用 v2 条款 SPEC-M6-01..08）：
  - `specs-v2/M6-flywheel.md`
  - `specs-v2/00-ontology.md`
  - `specs-v2/01-contracts.md`
  - `specs/ADDENDUM.md`（v2 附录未交付前仍引 v1 原文，D-71 CLI 条款依赖）
- **spec_hash → eval_hash**（01 v2 §6 协议）：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m6.yaml | `8b5b941d608e842f90e62de752ea358a9bb7ac5e85267f6572ec36805ecb2aba` | `ebb3a2e73c345f7d4fe58624c9a7ae25c7bbc48928692994b5bcee7e1f63f1e0` |

  v1 基线存照：spec_ref=v1 四文件，spec_hash `4377e37c88459245433899a33b26675e9455a7755e1cd216ffb1235e862445fe`
  → eval_hash `566aa15af27600d89f72eabe6e81adf5b9622325855db5044fbe306a0e24e2cb`（2026-09-28 独立评审缺口修复版，14 条）。

- **重生成内容**（v1 14 条 → v2 19 条 = 正例 10 / 负例 9）：
  1. **映射完整**：v2 八条款（SPEC-M6-01..08）每条 ≥1 用例；禁止类条款全部有
     负例——02⑥（holdout 禁入 dev）、06（调优侧直改状态）、08②（禁手工填报）。
     双向映射表见 `specs-v2/M6-flywheel.md` §4。
  2. **保留改名**：v1 用例逐条核对其断言正是 v2 条款后沿用——条款序号 01..05
     不变；`EVAL-M6-06-P` → **`EVAL-M6-06-N`**（禁止类按 01 v2 §6 以"尝试违反
     必须被拒"负例表达，断言不变：只读成绩可读 + 直改拒绝 + 审计合约校验）；
     `EVAL-M6-EVAL-P` → **`EVAL-M6-07-P`**（条款重排 SPEC-M6-06→07，断言不变：
     mock-rel-0001 全流程 12/12 + runs/ 归档 + 二次评估确定性）。
  3. **新增负例**：`EVAL-M6-01-N2`（空事件列表 → REJECTED[EMPTY_TRACE]）、
     `EVAL-M6-01-N3`（trace_id 不一致 → REJECTED[TRACE_MISMATCH]）——补全 01④
     六类拒绝口径；`EVAL-M6-03-N`（facts 缺路径 → ExpressionError"未知标识符"，
     自 v1 EVAL-M6-03-P 的内嵌负检查独立成条）。
  4. **新增条款用例**：SPEC-M6-08（attest 签名凭证，v1 无对应条款）——
     `EVAL-M6-08-P`（import_golden_scores 经 m6_flywheel.attest 产出口签名 →
     消费侧校验通过）与 `EVAL-M6-08-N`（凭证缺失/tampered_pass_rate/
     wrong_producer 三变体全部被拒）。经 suite 声明第二插件模块
     `m7_registry.eval_plugin` 复用既有 `m7.six_elements` 执行器（其探针在消费侧
     重算 M6 attest 凭证并逐块比对——`src/m7_registry/release.py:254-275`），
     **零新增执行器代码**。
  5. **不设用例的条款落点**（映射表内如实注明）：SPEC-M6-07 的 mode≠SIMULATION /
     CLI REAL 拒绝（⑩）无现成执行器可表达（CLI 三参实测记录见本文件 2026-09-28
     M6 首条登记）；SPEC-M6-07⑪ KNOWN-DEFECT（D-58 审批人硬编码）**故意不设
     用例**——缺陷登记条款不得固化为期望行为，改进条款落地时随重生成补负例。
- **静态自检**（本会话实跑；**未运行 run_evals.py，统一门禁另行执行**）：
  YAML 可解析（19 用例）；suite 级字段/用例必填字段/case id 正则
  `^EVAL-M\d+-[A-Za-z0-9]+-(P\d*|N\d*)$`/form 越界全查通过；全部 case executor
  存在于声明插件注册表（m6_flywheel.eval_plugin 12 个 + m7_registry.eval_plugin
  9 个）；引用路径全部存在（scenarios/dev-01-report.yaml、golden/dev{,/MANIFEST.yaml,
  /rubrics.yaml}、tests/fixtures/mock_releases/mock-rel-0001.yaml、
  assets/agent_contract_v1.yaml、prompts/×2、skills/overload-response/SKILL.yaml、
  ontology/）；spec_hash 声明值与按 `run_evals.py:819-825` 口径重算一致
  （重算算法以 v1 套件 eval_hash 复现 `566aa15a…` 交叉验证）。

---

## 2026-09-29 · M7 EVAL v2 重生成（specs-v2 反提 → tests/test_m7.yaml 整体替换）

- **模块**：M7
- **触发**：`specs-v2/M7-registry-release.md`（SPEC-M7-01..17）反提完成，按 01 v2 §6 协议
  重生成本套件；规格 §4.1/§4.2（条款↔用例双向映射表）为本套件权威用例清单。
- **spec_ref 变更**：`specs/{M7-registry-release,00-ontology,01-contracts,ADDENDUM}.md`
  （v1 四文件）→ `specs-v2/{M7-registry-release,00-ontology,01-contracts}.md`（v2 三文件；
  `specs-v2/ADDENDUM.md` 未产出且 M7 条款无 ADDENDUM 依赖，暂不列入）。
- **spec_hash → eval_hash**（01§6 协议）：

  | suite | 代 | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- | --- |
  | test_m7.yaml | v1 | `63631346e9622b06421faca778f4c8106d050abbbed2c461d362941661253dc6` | `12da220ff3d4c8c193a84b0fd2e6de3478b1ef060405c83aaabe515cc35fbaa0` |
  | test_m7.yaml | v2 | `e986db497cbf10d9c2bed9dd0cce7efed107801621d1fdc3f9acb9d418b2fd1c` | `7b366416f1cce8a29cccc594d252568423b43d7b323fc2c0cb27d786c3c765e5` |

- **覆盖范围**：27 条（P 11 / N 16，含变异驱动增补 EVAL-M7-07-N3），SPEC-M7-01..17 全部映射（13/17 经共享映射，
  见规格 §4.2）。执行器两组：`src/m7_registry/eval_plugin.py` 9 个（oracle，本轮零改动）
  + **新增 `tests/m7_eval_extra.py`** 4 个补充执行器（`m7.descriptor_validation` /
  `m7.review_guards` / `m7.contract_validation` / `m7.diff`——补 oracle 执行器没有的
  执行面：描述子校验拒绝、提案三要素守卫+终态不可改写、AgentContract 校验拒绝、
  diff_release 差分；全部数据驱动零案例特判，插件契约同 EVAL-SCHEMA §4）。
- **用例 id 对照**（v1→v2，逐条核对断言归属 v2 条款）：01-P→02-P；01-P2→01-P（合并
  版本链更新）；02-P→04-P；02-N→03-N；02-N2→04-N；02-N3→04-N2；03-P→05-P；
  03-P2→06-N；03-N→07-N；04-N→08-N；04-N2→09-N；05-P→12-N（12-P 为其正例拆分）；
  06-P→10-N；07-P→11-N；TABLE-P→TABLE-P；REL-P→REL-P；新增 01-N（子契约校验 8 态）、
  05-N（提案守卫+终态只读）、06-P（基线达标→PUBLISHED）、07-N2（在途提案直发拒绝）、
  08-P（六要素齐备打包通过）、10-P（门禁 5 项全过）、12-P（resolve 复核+SUPERSEDED）、
  14-N（AgentContract 校验 7 态）、15-P（diff_release 差分）。
- **静态自检**（本会话实跑，2026-09-29；按重生成轮约定**未运行 run_evals.py**）：
  ① YAML 解析 OK（suite=m7，26 用例，P11/N15，id 正则与唯一性 OK）；②
  `run_evals.validate_suite_schema` 零错误（仅导入模块函数做校验，未执行用例）；
  ③ 执行器名 13 个全部注册（`m7_registry.eval_plugin` 9 + `tests.m7_eval_extra` 4，
  两模块导入成功）；④ fixtures/文件引用存在（`tests/fixtures/m7_state_machines.yaml`、
  `tests/fixtures/mock_releases/mock-rel-0001.yaml`、`golden/dev`、
  `assets/agent_contract_v1.yaml`、`ontology/rules.yaml`）；⑤ spec_hash 重算与声明一致。
  全绿结论以统一门禁 `python run_evals.py --module all` 为准。
- **修订（同日，回归门禁后）**：`python run_evals.py --module m7` 首轮 24/26 FAIL，2 条
  **用例构造错误**（非 oracle 缺陷、非规格误描述，未改 oracle/规格），修正后复跑
  **26/26 PASS**（`EVALS mode=m7 isolation=OK modules=1/1 pending=0 cases=26/26
  failed=0 skipped=0 result=PASS`）：
  1. EVAL-M7-01-N「compiler 非法」探针误传 `variables: []`——`_require_keys` 视空列表为
     缺必填（`assets.py:139`），在 compiler 校验前报「缺必填字段 'variables'」；
     改 `variables: [x]` 使校验推进到 compiler 正则。
  2. EVAL-M7-04-N2 两处：`_prompt_b` 锚丢失回边（dependencies 空 → 环从未被检出）
     改回 A↔B 互指；且原样混入 skill_v1（entry.prompt_ref 指向未注册的
     prompts/eval-report）产生噪声缺失错误——改注册参与环的 `skill.eval-cycle`
     （entry.prompt_ref/dependencies 均指环入口 eval-a），skill_refs 非空使打包断言
     越过六要素检查（`release.py:307-311` 先于 :328 闭包解析）精确落「循环依赖」口径。
  eval_hash 相应更新为上表 v2 行现值（spec_hash 不变：本修订只动用例文件）。
- **变异轮处置（同日）**：上游变异报告 survivors=["结果文件缺失","工具失败: …（父目录下
  无 scripts/mutation_test.py）"] 判定为**无效运行**——工具实位于 `peidian-agent/scripts/`，
  上游以父目录为仓库根调用，m7 变异从未执行（当时无 results-m7.json），非真实 survivor。
  从仓库根实跑：`python scripts/mutation_test.py --module m7 --plan .mutations/plan-m7.json
  --baseline --require-clean-scope oracle` → baseline 26/26 exit 0（.mutations/baseline-m7.json）；
  9 变异因兄弟模块并发变异轮持续弄脏 oracle 全部 skipped_dirty（三种轮询策略重试同）。
  静态杀伤链核对 9 变异发现 **1 个真实覆盖缺口**：`m7-approved-gate-off`（publish_asset
  第 2 重门禁 state==APPROVED 失效会存活——07-N 被第 1 重 journal 存在性拦截、07-N2 被
  第 4 重黄金留痕兜底，均不能唯一归因第 2 重）。修复：**新增 EVAL-M7-07-N3**（REJECTED
  终态+黄金留痕在档直发，唯一拦截位=第 2 重；`m7.review_guards` 执行器分段条件化+
  publish_state_probe），套件 26→27（P11/N16），27/27 PASS 实跑确认。spec_hash 相应
  更新（规格 §4.1/§4.2 映射与计数同步）→ 上表 v2 行现值。全量 9 变异动态验证因并发
  变异队列死锁未完成，按裁决以 `.mutations/plan-m7-single.json` 定向单变异动态验证
  补强（结果见 .mutations/results-m7-single.json），其余 8 变异以静态杀伤映射为证；
  全量动态验证待统一门禁（oracle 静默窗口）补跑。
- **定向单变异动态验证结局（同日 18:34 干净窗实跑）**：`m7-approved-gate-off` →
  **killed**（planned=1/valid=1/killed=1，redline_all_killed=true；eval 26/27，唯一失败
  用例=EVAL-M7-07-N3——变异放行第 2 重门禁后，REJECTED→PUBLISHED 触发评审状态机
  非法迁移异常，用例失败即杀；评审状态机表=第二道防线且由 EVAL-M7-TABLE-P 覆盖）；
  还原校验 restored=true + hash_match=true（autocrlf 归一化）。提交后干净 oracle 复跑
  **27/27 PASS**。全量 9 变异动态验证仍待统一门禁补跑（静态映射+基线+单变异动态
  证据已足量支撑本轮缺口闭合）。
- **全量 9 变异动态验证完成（同日 18:43-18:48 干净窗，两轮拼接）**：①full 轮
  （plan-m7.json）5/5 可执行变异全杀——approved-gate-off（26/27，唯一失败=07-N3）、
  ontology-drift-off（26/27→11-N）、floating-allow（26/27→03-N）、six-elements-empty-ok
  （26/27→08-N，CRLF 变体命中）、release-table-edited（25/27→TABLE-P diff+12-N 行为
  探针）；前 4 个变异（均指 publish.py/release.py）被中途恢复的兄弟队列撞上
  skipped_dirty。②remaining 轮（plan-m7-remaining.json，仅含该 4 变异）干净窗 4/4
  全杀——writeonce-file-off（24/27→12-N+12-P 补写探针）、republish-off（25/27→12-N）、
  manifest-hash-off（26/27→REL-P 篡改检测）、golden-digest-off（26/27→09-N）；
  redline_all_killed=true。两轮拼接=**9/9 动态杀灭、零 survivor、零 invalid**；全部
  变异还原校验通过（restored+hash_match），轮后干净 oracle 复跑 **27/27 PASS**。
  结果存档：.mutations/results-m7-full.json、.mutations/results-m7-remaining.json
  （results-m7.json 为最后一次运行的工具固定输出名）。

---

## 2026-09-29 · M4 EVAL v2 重生成（specs-v2 反提：SPEC-M4-01..09 → 17 条）

- **模块**：M4（`tests/test_m4.yaml` 整体重生成；`specs-v2/M4-semantic-ontology.md` §4.1
  条款↔用例双向映射表、§4.2 用例总表、§4.3 v1→v2 用例去向同步更新，头注/§3.3/§5/§6 条数修订 13→17）
- **spec_ref 变更**：`specs/{M4-semantic-ontology,00-ontology,01-contracts}.md` + `specs/ADDENDUM.md`
  （v1 四文件）→ `specs-v2/{M4-semantic-ontology,00-ontology,01-contracts}.md` + `specs/ADDENDUM.md`
  （v2 三件；用例 spec 字段引用 v2 条款 SPEC-M4-01..09。ADDENDUM 暂仍引 v1 原文——
  specs-v2/ADDENDUM.md 未产出，M4 条款 §SPEC-M4-02/07 依赖 §D/§B，其落盘后须重算 spec_hash 再登记）。
- **spec_hash → eval_hash**（01§6 协议）：

  | suite | 代 | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- | --- |
  | test_m4.yaml | v1 | `f93c7c26f4b63512e5d14efb81ce5c1506f5e7bcbfd731954d4fcbc1d07abbb8` | `513d21fffa02f54b63466d2450474a42a2140f8553a6af848c6583171e12db54` |
  | test_m4.yaml | v2 | `8856222724ccae05a8942c5e65f1e5660d577c756540925168a00dc00fb3010a` | `75eb55911e4fc82a00ec6d3b3ef561e239bd79f1d9d8c273fde6f2a29dc22cd8` |

- **重生成内容**（v1 13 条 → v2 17 条 = 正例 10 / 负例 7；执行器 9 个原样重用，
  `src/m4_semantic/` 零改动）：
  1. **映射完整**：v2 九条款（SPEC-M4-01..09）每条 ≥1 用例；禁止性负例落位——
     01（注册表不对齐拒绝）、02（实例文件不存在/引用悬空拒绝）、03（版本不匹配拒绝启动）、
     08（未达阈值不得触发候选事件）；SPEC-M4-04-N1 为"歧义不擅断"负向面
     （全部候选带 ambiguous 标记、不擅自择一）。
  2. **保留改名（13 条，逐条核对断言归属 v2 条款）**：01-P 不变；01-N(instance_missing_ref)
     → **02-N2**（实例引用校验属 v2 SPEC-M4-02，非本体五文件校验）；01-N2(registry_misaligned)
     → **01-N1**；02-P→**04-P1**；02-N→**04-N1**；03-P→**05-P1**；03-P2→**05-P2**；
     03-N→**05-N1**；04-P→**06-P1**；05-P→**07-P1**；06-P→**08-P1**；07-P(version_mismatch)
     → **03-N1**（v2 条款重排 07→03）；PERF-P→**09-P1**（归入执行器插件条款，含 DoD §5）。
     两处条款号漂移（→02-N2、→03-N1）系 v2 重排所致，断言本身未变。
  3. **新增 4 条（映射补全）**：`EVAL-M4-02-P1`（§D 非缺省实例按名加载正例——原 13 条
     仅经图查询间接覆盖 SPEC-M4-02）；`EVAL-M4-02-N1`（unknown_instance_file 拒绝路径，
     `m4.load_reject` 实有 attempt 而 v1 用例未覆盖）；`EVAL-M4-05-P3`（defect_closure
     第三种查询模式落位——v1 三模式仅测其二；WO-D0021→AL-0201→TX-01→MP-TX01，
     属性拾取 next_due 不计跳）；`EVAL-M4-08-N1`（7 概念全部已注册 → ratio=1.0、
     零候选事件，D-37 触发口径的禁止性负例）。
- **静态自检**（本会话实跑，2026-09-29；按重生成轮约定**未运行 run_evals.py，统一门禁另行执行**）：
  ① YAML 解析 OK（suite=m4，17 用例，P10/N7，id 正则 `^EVAL-M\d+-[A-Za-z0-9]+-(P\d*|N\d*)$`
  与唯一性 OK，suite 级/用例必填字段齐备，form 全部在七类+contract 内）；
  ② 执行器名 17 条全部存在于 `m4_semantic.eval_plugin.EXECUTORS`（9 个）；
  ③ 引用路径存在（`tests/fixtures/bad_instance_missing_ref.yaml`、`ontology/actions.yaml`、
  dev-graph 经 PARK_INSTANCE_PATH 机制解析）；④ spec_hash 声明值与按 `run_evals.py:819-825`
  口径对 spec_ref 重算一致（`88562227…`）；⑤ SPEC-M4-01..09 经用例 spec 字段全覆盖；
  ⑥ 新增 4 用例另做执行器函数直调干跑（不经 run_evals.py）：4/4 passed=True。
  全绿结论以统一门禁 `python run_evals.py --module all` 为准。

---

## 2026-09-29 · M2 EVAL v2 重生成（specs-v2 反提基线，整体替换）

- **模块**：M2（`tests/test_m2.yaml` 整体重生成；行为规格基线切换为
  `specs-v2/M2-information.md` SPEC-M2-01..14，条款全文见该文件，偏差处置见
  `specs-v2/deviations/M2.md`）。本轮仅静态自检（YAML 解析 / runner
  `validate_suite_schema` 零错误 / 执行器名注册存在 / fixtures 存在 /
  spec_hash 复算一致），**未运行 run_evals.py，统一门禁另行执行**。
- **spec_ref**（按序拼接取 hash；v1→v2 变更：M2 规格切 specs-v2，ADDENDUM §B
  内容已折叠入 01 v2 §3.2 D-68 与 SPEC-M2-10，v2 目录暂无 ADDENDUM 文件故不列）：
  - `specs-v2/M2-information.md`
  - `specs-v2/00-ontology.md`
  - `specs-v2/01-contracts.md`
- **spec_hash → eval_hash**（01 v2 §6 协议）：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m2.yaml | `83ec12f5069533687d8363f2f3c3582c8cb7d75ffa6ce6dfadbcd1524d4c9156` | `ede475e6f9784e88d1eb968cd42ef1d84cfba4d9649332ffe230b44cd7bbf8b1` |

  v1 基线存照：spec_ref=v1 四文件，spec_hash `00756a50360d11fa5f1f71baf038139d4caffc1c1fb5ad8be79efde50c717e00`
  → eval_hash `72820122d481b65f6edb5644949571615067d7757869ea80f3f1dedd26ea6157`（2026-09-28 独立评审缺口修复版，23 条）。

- **覆盖范围**：v2 条款 14 条全部映射 ≥1 用例，合计 27 条（正例 14 + 负例 13）；
  双向映射表见 `specs-v2/M2-information.md` §4（每条用例 `spec:` 字段反向登记条款，
  多条款用例以 `/` 连接）。
- **保留改名**（v1 23 条逐条核对其断言正是 v2 条款后沿用，判据数据不变）：
  EVAL-M2-01-P/N、02-P、03-P/N、04-P、05-P/N、06-P 同名保留；
  EVLOG-P→**EVAL-M2-07-P**（重建协议主条款改挂 SPEC-M2-07，兼 06/08）；
  07-P/N（workspace）→**09-P/N**；08-P→**10-P**；08-P2→**10-P2**（兼 07）；
  08-N→**10-N**；08-N2→**10-N2**；09-P/N（evidence）→**11-P/N**；
  10-P/N/N2（memory）→**12-P/N/N2**；11-P→**13-P**；12-P→**14-P**。
- **新增 4 条负例**（均用现有执行面，零 src 改动）：
  1. EVAL-M2-02-N：source type 14 值封闭集越界（`contract` 内置，ContextManifest
     reject，期望 `枚举越界`）——SPEC-M2-02 封闭枚举负例。
  2. EVAL-M2-04-N：source 携带未知字段（`contract` 内置，期望 `未知字段`）——
     SPEC-M2-04 source 五字段封闭集（D-17）负例。
  3. EVAL-M2-07-N：事件缺 trace_id 写入即拒（`negative_rejection` 内置
     event_append，期望 `必填字段缺失`）——SPEC-M2-07 事件基础设施负例（01§8 横切）。
  4. EVAL-M2-14-N：DEPRECATED/REVIEW skill 全层不可见 + `disclose` 拒绝
     （`m2.skill_disclosure` 聚焦参数）——SPEC-M2-14 禁止类负例（D-21 可见状态口径）。
- **登记的口径与披露**：
  1. **SPEC-M2-08 覆盖缺口（如实登记）**：sessions/calls 表与 `StateStore(dsn)`
     `postgres*`→NotImplementedError 分支无用例——22 个执行器
     （`src/m2_information/eval_plugin.py`）均不触及，插件位于 src/ 本阶段不可改写；
     条款的 SQLite 持久形态由 EVAL-M2-06-P（checkpoints 表）/07-P（task_state/
     artifacts 表全生命周期）随行覆盖。待 eval 插件扩展轮补专条。
  2. **v1 头注"合计 22 条"存照**：该注释为 EVAL-M2-08-N2 加入前旧计数，随本轮
     整体替换一并消除；23 条终态与 22 条初版登记均见上文各节。
  3. 保留用例的任务 id 局部改名（如 task-m2-07a→task-m2-09wa）仅防混淆，沙箱按
     case id 隔离，不影响判据。
- **静态自检（本轮实跑）**：`yaml.safe_load` 解析通过；27 id 全部匹配
  `^EVAL-M\d+-[A-Za-z0-9]+-(P\d*|N\d*)$` 且唯一；22 个插件执行器名全部注册于
  `m2_information.eval_plugin.EXECUTORS`、3 条内置形态用例（contract/
  negative_rejection）合法；`tests/fixtures/frozen_state_machines.yaml` 存在；
  runner `validate_suite_schema` 零错误；spec_hash 声明值 = `compute_spec_hash`
  重算值；三内置负例的拒绝消息经契约探针实测（`枚举越界`/`未知字段`/
  `[EventRecord.trace_id] 必填字段缺失`）。
## 2026-09-29 · M5 EVAL v2 重生成（specs-v2 反提：SPEC-M5-01..15 → 26 条）

- **模块**：M5（`tests/test_m5.yaml` 整体重生成；`specs-v2/M5-simulation.md` §5
  条款↔用例双向映射表同步更新、§6 DoD 口径修订）
- **spec_ref**（按序拼接取 hash；v2 起指向 specs-v2——本套件用例的 spec 字段
  引用 v2 条款 SPEC-M5-01..15）：
  - `specs-v2/M5-simulation.md`
  - `specs-v2/00-ontology.md`
  - `specs-v2/01-contracts.md`
  - `specs/ADDENDUM.md`（v2 附录未交付前仍引 v1 原文，D-70 实例协议依赖）
- **spec_hash → eval_hash**（01 v2 §6 协议）：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m5.yaml | `b2d4f03a7a32af10c557f38f8f48e2f75da8643b96194eb2a96542d669eea0ae` | `17670b696a59a815145efd04ca963aff8c081f0d90ffa5091868a66e7739c79b` |

  hash 刷新存照：登记后规范正文做纯文字同步（§2/§4/§6 证据行内旧用例 id 改为新 id，条款语义零变化），spec_hash 字节口径随之刷新为本行登记值；eval_hash 为刷新后套件文件 sha256。
  v1 基线存照：spec_ref=v1 四文件，spec_hash `54bb8cb6cc6004505198f6894e436925f97946bc32691bece62eafba79afa97b`
  → eval_hash `577055177ee5cf2b15f1b34c4afea454025b4d272fddc7e930dd74a818e2c0c2`（2026-09-28
  安全规程判据落地版，20 条；其 executors/fixtures 约定与 13 执行器全部沿用）。

- **重生成内容**（v1 20 条 → v2 26 条 = 正例 17 / 负例 9）：
  1. **映射完整**：v2 十五条款（SPEC-M5-01..15）每条 ≥1 用例（SPEC-M5-14 经
     08-P/09-P/10-P 跨映射：dev-sim-park 经 PARK_INSTANCE_PATH、seed 缺省加载，
     注入失败即用例失败）；禁止类条款全部有负例——02（禁墙钟判价）、
     03（未注册禁止执行/DENY 动作禁止执行）、11（无票遥控必须拒）、15（三规约）。
     双向映射表见 `specs-v2/M5-simulation.md` §5。
  2. **保留改名**（逐条核对其断言正是 v2 条款）：`EVAL-M5-PHYS-P`→**09-P**、
     `EVAL-M5-DEV-P`→**10-P**、`EVAL-M5-05-P4`→**`EVAL-M5-11-N`**（COMM_LOSS 审批
     超时语义归 SPEC-M5-11；COMM_LOSS 注入行为在 §5.1 跨映射 SPEC-M5-05）、
     `EVAL-M5-SAFE1..4-N`→**15-N1..N4**、`EVAL-M5-PERF-P`→**01-P3**；其余 id 沿用
     （05-P5 保留原号，P4 槽位让渡 11-N）。
  3. **新增正例**：`EVAL-M5-01-P2`（dev-02b 含 SUT 桩链动作与审批链两次重放逐步
     diff 空——D-42 latency_ms 审计列不泄漏进重放轨迹的落地钉子，v1 仅测 dev-01）、
     `EVAL-M5-12-P`（dev-01 `device.temp_rise` 计划事件按 at 触发并落
     `grid.event`（kind=temp_rise）——D-40 事件族断言）、`EVAL-M5-13-P`（dev-01 24h
     推进后需量 15min 滑窗激活：month=2026-09 / peak_kw=1720（seed 基线
     `demand_2026_09`，ontology/seed.yaml:62）/ contract_capacity_kw=2000）。
  4. **新增负例**（复用既有执行器的数据驱动断言面，零新增执行器代码）：
     `EVAL-M5-03-N`（modify.protection_setting 缺省 Policy=DENY → DENIED/
     POLICY_DENIED 零副作用——D-47 负例；m5.safety_rules kind=issue_human 的
     status/error_code/order_absent 断言面）、`EVAL-M5-03-N2`（query.ghost 未登记 →
     FAILED/UNREGISTERED_CAPABILITY，红线 1）、`EVAL-M5-11-N2`（空票号不预置票 →
     FAILED/NO_SWITCH_ORDER、断路器零副作用；kind=order_seq）。
  5. **不设独立用例的落点**（映射表内如实注明）：SPEC-M5-08"禁止硬编码阈值"由
     08-P 行为级 enforcement 承担（改阈值→告警 0→1 条；无词面扫描器执行器，
     不设独立 -N）；SPEC-M5-05"不得伪造新读数"由 05-P 的 stale 断言负向覆盖
     （中断窗口内不存在新鲜读数）。
- **静态自检**（本会话实跑；**未运行 run_evals.py，统一门禁另行执行**）：
  YAML 可解析（26 用例）；runner `validate_suite_schema` 零错误；全部 case executor
  存在于声明插件注册表（m5_simulation.eval_plugin 13 个）；引用文件全部存在
  （scenarios/dev-01-report.yaml、dev-02-alarm.yaml、dev-02b-remote.yaml、
  regulations/REG-TECH.yaml、ontology/seed.yaml、tests/fixtures/dev-sim-park.yaml）；
  spec 字段全部为 specs-v2/M5-simulation.md 已定义条款；spec_hash 声明值与按
  `run_evals.py:819-825` 口径对 specs-v2 四文件重算一致；隔离断言
  （`scripts/ci_isolation.py:31` 的 ISOLATION_PATTERN——验收实例/电价方案/OP-1x 段字面量，此处不引用原文以免自命中）零命中。


---

## 2026-09-29 · M3 EVAL 重生成（specs-v2/M3-action-gateway.md v2 条款对齐）

- **模块**：M3（`tests/test_m3.yaml` 整体替换 + 新增 `tests/fixtures/m3_eval_plugin.py` 执行器插件
  + `tests/__init__.py` 包标记）
- **触发**：specs-v2/M3-action-gateway.md 反提重生成（v2 条款 SPEC-M3-01..16，吸收 D-24..D-33/D-59）；
  按 01 §6 协议受影响 EVAL 重生成并登记。
- **spec_hash → eval_hash**：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m3.yaml | `91b5cab10ea229719052f1b9498ea75eeb17d539ebf94734f76885c40a4eaa8c`（口径不变：spec_ref 仍为 v1 四文件，原文未改写） | `c0e180962818aa1672882d96b3c6aa0cb334966f50b91799f56988e984f68be5`（重生成后套件文件 sha256） |

- **条款映射**：SPEC-M3-01..16 每条款 ≥1 用例（共 29：正例 16 / 负例 13）；双向映射表落
  specs-v2/M3-action-gateway.md §4，套件用例 `spec` 字段回指 v2 条款 id。
- **改名**（用例内容与旧版一致，断言对象逐条核对 v2 条款）：08-P/P2→09-P/P2（幂等→SPEC-M3-09）、
  09-P→10-P（证据三态→SPEC-M3-10）、10-P/N/N2/P2→11-P/N/N2/P2（路由三重→SPEC-M3-11）、
  11-P→15-P（负向矩阵→SPEC-M3-15）、APPR1-N→08-N（审批权 fail-closed→SPEC-M3-08）、
  APPR2-N→13-N（SAFE-ISSUE-HUMAN 准入拒绝→SPEC-M3-13）；其余 id 不变、spec 字段更新为 v2 条款号。
- **新增用例**：EVAL-M3-12-P（m3.determinism：双沙箱同操作序重放任务事件流逐字节一致 +
  EVT-M3-<seq> 流内严格递增含 restart 续序 + trace_id=trace-<task_id> 派生）、EVAL-M3-12-N（事件记录
  缺 trace_id → EventRecord 契约拒绝；复用 fixtures/events_missing_trace.jsonl）、EVAL-M3-14-P
  （m3.time_discipline：m3_action/tools 墙钟词面扫描零命中〔唯一豁免 clocking.py〕+ 补丁 now_iso
  三处绑定后显式 now 探针全链跑通）、EVAL-M3-16-N（D-59 KNOWN-DEFECT 当前行为钉死：
  modify.asset_history entry 裸 object 仍过准入 → DENY 红线兜底 DENIED/POLICY_DENIED）。
- **新增 tests 侧资产**：`tests/fixtures/m3_eval_plugin.py`（m3.determinism/m3.time_discipline 两执行器；
  复用 m3_action.eval_plugin 的沙箱/环境/网关装配约定，扫描面/词面/探针/期望全部来自用例
  params/expect，零案例特判）；`tests/__init__.py`（包标记——site-packages 存在同名第三方 tests 包
  抢占模块名，无包标记时 suite.executors 无法装载 tests.fixtures.*，已实测并修复导入失败）。
- **静态自检**（本会话实跑；统一门禁本轮未跑）：`yaml.safe_load` 29 例 OK；
  `run_evals.validate_suite_schema` → 零错误；`compute_spec_hash(spec_ref)` 与声明值一致
  （91b5cab1…，v1 文件未变）；5 执行器全部可导入并注册（m3.execute/m3.registry/m3.negative_matrix/
  m3.determinism/m3.time_discipline），套件内执行器名零缺失；fixtures 引用全部存在
  （negative_matrix.yaml / events_missing_trace.jsonl / frozen_state_machines.yaml / actions.yaml）；
  新执行器与 12-N 冒烟实跑通过（12-P 双沙箱 11 事件逐字节；14-P 扫描 30 文件零命中+探针 3 步；
  12-N "[EventRecord.trace_id] 必填字段缺失"）。
- **复核门禁**：待编排方统一执行 `python run_evals.py --module all`（本轮按指令未运行）。

---

## 2026-09-29 · M1 EVAL v2 重生成（specs-v2 反提：SPEC-M1-01..15 → 30 条，整体替换）

- **模块**：M1（`tests/test_m1.yaml` 整体重生成；行为规格基线切换为
  `specs-v2/M1-agent-core.md` SPEC-M1-01..15，条款全文见该文件，偏差处置见
  `specs-v2/deviations/M1.md`）。本轮仅静态自检（YAML 解析 / runner
  `validate_suite_schema` 零错误 / 执行器名注册存在 / fixtures 存在 /
  spec_hash 复算一致），**未运行 run_evals.py，统一门禁另行执行**。
- **spec_ref**（按序拼接取 hash；v1→v2 变更：M1 规格切 specs-v2，ADDENDUM 暂指
  v1 原文——specs-v2/ADDENDUM.md 尚未落盘，落盘后随其登记一并升级）：
  - `specs-v2/M1-agent-core.md`
  - `specs-v2/00-ontology.md`
  - `specs-v2/01-contracts.md`
  - `specs/ADDENDUM.md`
- **spec_hash → eval_hash**（01 v2 §6 协议）：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m1.yaml | `e34bf32589ee73f255084c4995732343a51ab82078cc68105dbf4f4783958434` | `8a09c9e6a1bfb4dd16a99c35dbe2c833ad5c7a16b6455614090810c23675940d` |

  v1 基线存照：spec_ref=v1 四文件（specs/），spec_hash
  `c8a2cd2b51a8462b74d1f8877515cd3a2e2583d2b8c636de7481badea44589ec` → eval_hash
  `b0f28d6ae30493471d7017ea83f6087edd0d20cd2961e4fe9e4d6b58cb122dd3`（2026-09-28
  首条登记，20 条）→ `7307d4417bea4c860c0237e9e37c2514032c03a6566c748205f94a6f0d02aa28`
  （2026-09-28 复核修订，20 条）。

- **覆盖范围**：v2 条款 15 条全部映射 ≥1 用例，合计 30 条（正例 17 + 负例 13）；
  双向映射表见 `specs-v2/M1-agent-core.md` §4（§4.1 条款→用例、§4.2 用例→条款
  速查；每条用例 `spec:` 字段登记主条款）。
- **保留用例（v1 逐条核对其断言正是 v2 条款后沿用，判据数据不变）**：
  EVAL-M1-01-P、02-P、02-N、TABLE-P、04-P、04-N、GATE-P2、05-P、05-N、05-P2、
  06-P、06-N、07-P、09-P、10-P、MW-P、MODEL-P、MODEL-P2（18 条）。
- **改名/拆分 3 处**：
  1. v1 EVAL-M1-03-P（伪造完成话术）→ **EVAL-M1-03-N**——按 v2 条款语义定位为
     SPEC-M1-03 禁止类负例（模型文本不构成状态依据，尝试违反必须被拒）。
  2. 新增 **EVAL-M1-03-P**（prepare_state_versions 权威状态正例）——自 v1 01-P
     的 trace 断言面拆出，SPEC-M1-03 正例独立成条。
  3. v1 EVAL-M1-01-N（伪序注入+真实运行合体）拆为 **EVAL-M1-01-N**（伪序注入，
     SPEC-M1-01 负例）与 **EVAL-M1-11-P**（真实运行 trace 合法，SPEC-M1-11 正例）。
- **新增 7 条**（均用现有执行面，零 src 改动）：
  1. EVAL-M1-07-N：模型伪造证据引用申请完成 → verdict REJECTED（伪造引用=申请
     无效，completion.py fabricated 路径）——SPEC-M1-07 禁止类负例（自述/伪造
     证据不构成完成依据）兼 SPEC-M1-06 REJECTED 三值覆盖。
  2. EVAL-M1-09-N：Resume 状态-种类矩阵错配三连拒（WAITING_APPROVAL×USER_INPUT/
     ENV_EVENT、WAITING_INPUT×ENV_EVENT → LoopNotResumableError）——SPEC-M1-09
     矩阵负例（D-13），正向 GRANT 决断随行验证。
  3. EVAL-M1-11-N：伪阶段序注入（乱序/跳阶段/重复/OBSERVE 单阶段）逐条被
     validate_replay 拒绝——SPEC-M1-11 负例（与 01-N 互补：不同伪序集）。
  4. EVAL-M1-12-P：write.report SUCCEEDED → 产物策略自动落 ArtifactRecord
     （action.completed → artifact.state_changed → task.stage_gate 事件序）——
     SPEC-M1-12 正例（D-11）。
  5. EVAL-M1-12-N：同 action_id 幂等重放（同 todo 同参同 capability 二轮重入）→
     executions=1、artifact.state_changed 恰 3 条（NONE→DRAFT→VALIDATING→READY，
     created_by.action_id 去重守卫后零二次产物）、evidence_count=1——SPEC-M1-12
     幂等负例（D-11 复核修复项用例化；3 事件计数口径经
     `src/m2_information/artifact.py` create/`_emit` 逐条核对）。
  6. EVAL-M1-14-N / 14-N2：模型端点解析到非公网地址（回环 127.0.0.1 / 云元数据
     169.254.169.254）→ 建连前 fail-closed 拒绝——SPEC-M1-14 禁止类负例（D-15）。
     **可达路径披露**：经 `m1.scenario` 的 `model_options{provider: openai_like}`
     使 `AgentCore._model_of` 构造**缺省传输**（不注入 transport）的 ModelClient，
     `_urllib_transport` 首行 `_assert_safe_endpoint` 在建连前拒绝（离线零触网，
     拒绝消息含解析地址，已经契约探针实测两地址全拒）；"注入 transport 的离线
     路径不受边界约束"之正例由 EVAL-M1-MODEL-P 同证（api_base 为不可解析假主机、
     transport 注入、零触网通过）；公网放行需真实网络，离线 EVAL 不覆盖（以
     2026-09-29 提交门禁安全修复节的人工探针记录为准）。
  7. EVAL-M1-15-N：tool_calls capability 缺 "@" 版本段 → LoopError 拒绝且无
     action.requested（契约前置校验先于网关）——SPEC-M1-15 负例。
- **登记的口径与披露**：
  1. **v1 头注"合计 20 条"存照**：随本轮整体替换消除；v1 套件 20 条终态与两代
     eval_hash 见上文 M1 各节。
  2. EVAL-M1-01-P 的 `prepare_state_versions` 断言移至 03-P（05-N/06-P 保留各自
     trace 断言），01-P 聚焦轮阶段序与轮驱动——断言面拆分不改变判据数据。
  3. SPEC-M1-05 的 PAUSED 恢复重查由 05-N 第二步（resume 仍超限被拒）覆盖，
     SPEC-M1-09 的矩阵错配由 09-N 覆盖——两条款共享恢复语义的分工在 v2 §4 映射表
     注明。
  4. specs-v2/README.md §1 "合计 180 用例"基线计数因本套件 20→30 暂显陈旧（全量
     待统一门禁摘要刷新），以本轮 CHANGELOG 登记为准。
  5. 全部用例复用 `m1_core.eval_plugin` 现有 7 执行器（scenario/replay/table/
     budget/middleware/model/persona_llm），未新增 tests 侧执行器模块（SPEC-M1-14
     经 model_options 缺省传输路径覆盖，见新增 6 的披露）。
- **静态自检（本轮实跑）**：`yaml.safe_load` 解析通过；30 id 全部匹配
  `^EVAL-M\d+-[A-Za-z0-9]+-(P\d*|N\d*)$` 且唯一；7 个执行器名全部注册于
  `m1_core.eval_plugin.EXECUTORS`；`tests/fixtures/frozen_state_machines.yaml`
  存在；runner `validate_suite_schema` 零错误；spec_hash 声明值 =
  `compute_spec_hash` 重算值（`e34bf325…58434`，含 v2 §4 双向映射表定稿——
  §4.2 速查由短 id 改为完整用例 id 后 spec 随之重算，spec_hash/eval_hash 同步
  刷新为本表终值）；SSRF 两负例拒绝消息经 `_assert_safe_endpoint` 探针实测
  （127.0.0.1 / 169.254.169.254 全拒，消息含地址字面量）。
- **复核门禁**：待编排方统一执行 `python run_evals.py --module all`（本轮按指令
  未运行）。

---

## 2026-09-29 · 变异测试工具落地（scripts/mutation_test.py + .mutations/ 7 计划，ASSET 资产工程）

- **性质**：EVAL 资产质量度量工具（非 SPEC/EVAL 语义变更；不触碰任何 suite 文件，
  spec_hash/eval_hash 基线不变）。用途 = 对 oracle 做受控变异并跑模块 EVAL，
  量化"eval 对 oracle 行为的覆盖"（killed/survivor；redline 变异全灭为验收口径之一）。
- **工具**：`scripts/mutation_test.py`（oracle 触碰唯一受控通道：应用变异 →
  `python run_evals.py --module <mX>` 记退出码 → `git checkout -- <target>` 强制还原 →
  git 干净 + 行尾归一化 sha256 双重校验；killed = 模块 EVAL 退出码非 0；结果写
  `.mutations/results-<mX>.json` 固定七键，stdout 末行输出单行压缩 JSON）。
  变异目标白名单硬约束于 oracle 路径（src/tools/ontology/regulations/golden/
  scenarios/releases/scripts/run_evals.py）；`--check-plan` 静态校验 find 恰好 1 次；
  `--baseline` 先跑无变异基线。Windows autocrlf 适配：find 精确匹配 0 次自动尝试
  CRLF 变体（结果记 `find_variant`）；还原校验用行尾归一化 hash（checkout 可能把
  LF 工作文件重写为 CRLF，字节级比对会误报）。
- **git"干净"口径披露（重要）**：本工具缺省 `--require-clean-scope oracle`（仅要求
  oracle 路径无未提交的已跟踪改动——变异/还原/hash 比对只作用于 oracle 文件，这是
  该序列安全的最小充分条件），`--require-clean-scope all` 提供全仓库最严格口径；
  两口径均忽略未跟踪文件（工具自身产物 .mutations/ 与并行交付物不应自锁）。
  本轮自测时仓库携带并行阶段的 tests/** 未提交改动（非本工具产物、不在 oracle
  白名单），故自测按缺省 oracle 口径执行；全部交付提交后可用 all 口径复跑。
- **计划资产**：`.mutations/plan-m{1..7}.json` 共 52 条变异（6-10 条/模块，
  redline 条款优先；逐条对照 specs-v2 条款与 tests/ 用例选取，find 均为
  经 `--check-plan` 静态校验的恰好一次精确子串，变异后文件全部 ast.parse 通过）：
  m1=7（完成门禁/冻结表/伪造引用判定/SIMULATION 固定路由/产物就绪集/预算耗尽边界/SSRF is_global）、
  m2=6（policy 永不裁/Knowledge mutate 拒绝/跨任务写拒绝/规则 ID 存在性/评审通道必填/乐观锁）、
  m3=8（不可改 DENY 清单删行/PERMANENT_ASK 改名/EVAL 强制 SIMULATION/审批 fail-closed/SAFE-ISSUE-HUMAN 枚举/自报降级/单向收紧边/未知动作第二道防线）、
  m4=7（三跳上限两道闸/注册表对齐/版本漂移/实例校验/歧义阈值/受控词表同源）、
  m5=7（墙钟判价/两票制/SAFE-ISSUE-HUMAN/SAFE-ORDER-SEQ/SAFE-SINGLE-OP/REG-TECH 装载/业务时钟禁墙钟兜底）、
  m6=8（holdout 标记判定/装载拒绝/写入通道拒绝/ReleaseGuard 单向/attest 签名/技能化门槛/A-B 采纳/轨迹 trace 校验）、
  m7=9（发布不可变两处/manifest sha256 复核/digest 重算/APPROVED 门禁/本体漂移/floating 拒绝/六要素/状态机冻结表）。
- **自测（本轮实跑，m3 全计划 8 条 + 基线）**：
  `python scripts/mutation_test.py --module m3 --plan .mutations/plan-m3.json --baseline`
  → 基线 29/29 PASS exit 0；**7/8 killed**（immutable-deny 删行 27/29 失败 2、
  permanent-ask 改名 27/29 失败 2、router 评估门禁 28/29 失败 1、审批 fail-closed
  28/29 失败 1、SAFE-ISSUE-HUMAN 枚举 28/29 失败 1、自报降级 28/29 失败 1、
  单向收紧删边 28/29 失败 1——均 exit 1 且还原后 hash 一致）；还原后复跑
  `python run_evals.py --module m3` → 29/29 PASS exit 0（还原正确独立复核）。
- **自测暴露的覆盖缺口（survivor，登记待处置）**：`m3-unknown-action-allow`
  （`src/m3_action/policy_engine.py` decide() 未知动作按 DENY 的第二道防线改判
  ALLOW）→ m3 29/29 仍 PASS——现行 eval 均在准入段即拒未注册动作（SPEC-M3-02），
  未有用例穿透到判定引擎对"动作不在授权规则表内"的兜底分支；如需补盖可增加
  `query_policy` 纯判定负例（不进主链、无副作用）。`redline_all_killed=false`
  即由此一条引起，其余 6 条 redline 变异全部被杀。
- **产物清单**：`scripts/mutation_test.py`、`.mutations/plan-m1..m7.json`、
  `.mutations/results-m3.json`、`.mutations/baseline-m3.json`、
  `.mutations/selftest-m3-stdout.log`/`selftest-m3-stderr.log`（自测原始输出）。
  m1/m2/m4-m7 计划已静态校验、未实跑（按任务边界只要求 m3 自测；全量跑批
  约需 7×8×~22s，可在 all 口径下随统一门禁执行）。


---

## 2026-09-29 · M3 EVAL 变异缺口修复（survivor m3-unknown-action-allow）

- **触发**：`scripts/mutation_test.py --module m3 --plan .mutations/plan-m3.json`（8 变异，仓库根实跑）：
  7 killed / 1 survivor——`m3-unknown-action-allow`（`src/m3_action/policy_engine.py` decide 未知动作
  分支 DENY→ALLOW 改判无用例守护）。编排方转述的 survivors=["结果文件缺失","工具失败:…\scripts  mutation_test.py"] 为**外层 cwd 误跑伪影**（脚本与 results 均在仓库根 `peidian-agent/` 下）；
  权威结果 = 仓库根 `.mutations/results-m3.json`（planned=8/valid=8/killed=7/survivor=1，redline_all_killed=false）。
- **缺口定性**：真实缺口（非无效变异）——运行期 `register_capability` 可注册 `ontology/actions.yaml`
  之外的动作（如 EVAL-M3-01-N2 的 custom_telemetry 形态），注册/披露段通过后直达
  `policy_engine.decide` 未知动作分支；原套件无任何用例请求"已注册但未入动作表"的能力。
  SPEC-M3-04 条款正文已含"动作不在授权规则表内 → 按 DENY 处置（第二道防线）"，无需升格条款。
- **修复**：新增 **EVAL-M3-04-N**（SPEC-M3-04 禁止类负例）：注册 `query.adhoc_telemetry@v1`
  （default_policy 自声明 ALLOW、disclosed_roles 空越披露段）→ 断言 decisions=DENY、
  REJECTED 无关而 status=DENIED/POLICY_DENIED、事件序 [action.requested, action.policy_decided,
  action.completed] 且 action.executing 缺席。变异注入（判 ALLOW）后该用例转 FAILED
  （ALLOW→EXECUTING→ADAPTER_MISSING，status/error_code/事件序三处失配）→ 被杀。
- **spec_hash → eval_hash**：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m3.yaml | `91b5cab10ea229719052f1b9498ea75eeb17d539ebf94734f76885c40a4eaa8c`（不变） | `d3c53375dfe964a369f64aad4115de7921e9554e9b42b4bfef3c48cc93e0d8a7`（30 例套件 sha256） |

- **套件现状**：30 用例（正例 16 / 负例 14）；静态自检零错（schema/执行器名/fixtures）；04-N 冒烟
  PASSED（oracle 现行：未入表动作 DENIED、0 次副作用）。specs-v2/M3-action-gateway.md §3/§4/§5
  与头部计数已同步（29→30）。
- **复核**：修复后重跑变异测试确认全杀（结果见 .mutations/results-m3.json 新版与本条目补记）。

---

## 2026-09-29 · M5 EVAL 变异缺口修复（survivor m5-business-nohub-wall-fallback）

- **触发**：`python scripts/mutation_test.py --module m5 --plan .mutations/plan-m5.json --baseline`
  （仓库根实跑）：基线 26/26 PASS exit 0；7 变异 killed 6 / **survivor 1**——
  `m5-business-nohub-wall-fallback`（`src/m5_simulation/clock.py` `clock()` 的"BUSINESS/SIM_LOGICAL
  无 ClockHub 抛 ValueError"守卫被禁用 → 业务时钟落回墙钟兜底仍 26/26 全绿 = 无用例守护）。
  编排方转述的 survivors=["结果文件缺失","工具失败:…D:\workspace\xunfei4\scripts\mutation_test.py
  No such file"] 为**外层 cwd 误跑伪影**（脚本与 results 均在仓库根 `peidian-agent/` 下），
  已在 `.mutations/plan-m5-invalidation-note.json` 标注 invalid；权威结果 =
  **存照 `.mutations/results-m5.first-run.json`**（planned=7/valid=7/killed=6/survivor=1，
  redline_all_killed=false；results-m5.json 后被并行模块变异期间的 skipped_dirty 运行覆盖）。
- **缺口定性**：真实缺口（非无效变异）——SPEC-M5-02 条款正文已含"clock(mode) 无 ClockHub 调
  BUSINESS/SIM_LOGICAL 抛 ValueError（业务时钟不落回墙钟）"，但 m5 套件 26 用例无一调用
  `clock()` 无 hub 边界（m5_simulation.eval_plugin 13 执行器亦未直接断言）。
- **修复**：新增 **EVAL-M5-02-N2**（SPEC-M5-02 禁止类负例，form=negative_rejection）：执行器
  `m5.clock_discipline` 注册于 **tests 侧插件 `tests/fixtures/m5_eval_plugin.py`**（tests/ 非
  oracle；协议同 `tests.fixtures.m3_eval_plugin` 先例；探针模式/期望全部数据驱动零案例特判）——
  无 hub 的 BUSINESS/SIM_LOGICAL `clock()` 一律 ValueError（expect.error_contains="ClockHub"）；
  带 hub 业务时钟正常读数（正对照，防"一律拒绝"式退化实现假阳性，断言语义未削弱）；
  WALL/MONOTONIC 无 hub 合法（只读真实时钟审计面）。变异注入后 02-N2 转 FAILED（无 hub 调用
  返回墙钟兜底读数而非异常）→ 被杀。套件 26→27 用例（正例 17 / 负例 10）；
  specs-v2/M5-simulation.md §5 双向映射表与 SPEC-M5-02 证据行已同步（条款正文无需升格）。
- **spec_hash → eval_hash**（01 v2 §6 协议；本对取代 2026-09-29 v2 重生成登记对）：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m5.yaml | `46051061b7a9be9153833488015dc5bf0db672d7d413698c062477a9acc64a33` | `31d55310f34a244b8bbda3f6a0840be2837bfbea260d9dfdafa4906da6e462da`（27 例套件 sha256） |

  hash 刷新原因：§5 映射表与证据行同步属 spec_ref 字节变化，spec_hash 随之刷新；
  oracle（src/ 等）零改动。
- **复核（已执行证据链，截至本条目终版补记）**：
  1. **survivor 已杀（执行确认）**：`python scripts/mutation_test.py --module m5
     --plan .mutations/plan-m5-recheck.json`（单变异窗口实跑）→
     `m5-business-nohub-wall-fallback` **killed**（exit 1；eval `cases=26/27 failed=1`
     ——失败用例即新增的 EVAL-M5-02-N2；restored=true、hash_match=true）；
     工具输出存照 `.mutations/results-m5.recheck.json`。
  2. **另两变异在 27 例套件复确认 killed**：全计划窗口跑中 `m5-price-wallclock`（26/27
     failed=1）与 `m5-two-ticket-off`（25/27 failed=2）killed 后窗口被并行写入关闭。
  3. **其余 4 变异**（SAFE-ISSUE-HUMAN/ORDER-SEQ/SINGLE-OP/REG-TECH 装载）：26 例套件
     executed kill 见存照 `.mutations/results-m5.first-run.json`（per_mutation 逐条
     exit 1）；27 例套件对 26 例为纯增量（仅新增 02-N2 一例），killed 判定单调保持。
  4. **正式汇总版 results-m5.json**：多次全计划复跑均因并行模块工程师的受控变异
     改动 oracle 树而 `skipped_dirty`（先后观测 `src/m3_action/gateway.py`、
     `src/m2_information/context_builder.py`、`src/m1_core/model_client.py` 未提交改动，
     非本模块产物；结果文件被覆盖为 skipped 版）——**7/7 汇总确认随统一门禁在干净
     oracle 树上复跑，以届时 `.mutations/results-m5.json` 为权威**；本轮全部 7 变异
     均已有 executed kill 证据（6 条全计划/部分计划实跑 + survivor 单变异实跑）。

---

## 2026-09-29 · M2 EVAL v2 修订（变异测试缺口补齐：乐观锁 + Knowledge 注册门禁）

- **模块**：M2（`tests/test_m2.yaml` 29 条；新增 `tests/m2_eval_extra.py` tests 侧
  补充执行器 2 个；`specs-v2/M2-information.md` §4 映射表同步——spec_hash 随之变更）。
- **首跑无效存照**：本轮变异测试首次调用误以工作区根路径执行
  （`D:\workspace\xunfei4\scripts\mutation_test.py` 不存在；实际工具在
  `peidian-agent/scripts/mutation_test.py`），工具从未执行、`.mutations/results-m2.json`
  未产出，上报的 2 条 survivor（"结果文件缺失"/"工具失败"）均为运行无效产物、
  非真实覆盖缺口。已在 `.mutations/plan-m2.json` 逐条目注记
  `invalid_first_run_note`，并在仓库根以正确路径重跑（本节即为重跑前置修订）。
- **真实缺口处置**（plan-m2 的 2 个探测变异预言命中）：变异前静态核对 plan-m2 六条
  变异与现有 27 用例，确认 4 条 redline 变异有守护（03-N/12-N2/09-N/10-N2），
  2 条探测变异无用例——补齐（零 oracle 改动，执行器落 tests/ 侧）：
  1. **EVAL-M2-07-N2**（执行器 `m2x.optimistic_lock`）：`put_task` 以过期
     `expected_version` 提交（过期快照携带 version 回退 + current_stage=TAMPERED
     可探测篡改）→ 必须 `OptimisticLockError`（消息含"版本冲突"）且库内版本不被污染；
     合法基线提交仍递增。守护 plan-m2 `m2-optimistic-lock-off`。
  2. **EVAL-M2-12-N3**（执行器 `m2x.knowledge_register_gate`）：Knowledge 注册缺
     `review.reviewer` / `review.review_ref` / 两者皆缺 三个变体 → 一律
     `KnowledgeReadOnlyError`（消息含"评审"）；被拒条目不泄入检索；完整评审信息
     注册成功且评审信息随条目落盘。守护 plan-m2 `m2-knowledge-register-open`。
- **spec_hash → eval_hash**（01 v2 §6 协议；spec_ref 三件不变，§4 映射表更新致
  spec_hash 变更）：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m2.yaml | `1a02565f1a9972b423a19ca723ffc0545f1f90d1c692a5030dea6c819fa4ae9b` | `8deac6b164df780443de51338e1f4e0cda7d4fca710bcc6bc7b7ac087455d17f` |

  前版登记对（v2 重生成 27 条）存照：spec_hash
  `83ec12f5069533687d8363f2f3c3582c8cb7d75ffa6ce6dfadbcd1524d4c9156` → eval_hash
  `ede475e6f9784e88d1eb968cd42ef1d84cfba4d9649332ffe230b44cd7bbf8b1`。
- **静态自检与冒烟（本轮实跑）**：`validate_suite_schema` 零错误；spec_hash 声明值
  = `compute_spec_hash` 重算值；EVAL-M2-07-N2 / 12-N3 执行器直连冒烟 PASSED
  （「过期基线 v1 提交被拒（版本保持 v2 未污染），合法提交递增至 v3」/
  「3 个缺评审信息变体全部被拒；完整评审注册可检索且评审信息落盘」）；
  变异杀伤由 `python scripts/mutation_test.py --module m2
  --plan .mutations/plan-m2.json --baseline` 重跑实证（结果见
  `.mutations/results-m2.json`、`.mutations/baseline-m2.json`）。

- **复核补记（同日）**：修复后仓库根重跑 `python scripts/mutation_test.py --module m3 --plan
  .mutations/plan-m3.json --baseline` → baseline 30/30 exit 0；planned=8 valid=8 **killed=8
  survivors=[] redline_all_killed=true**（m3-unknown-action-allow 变异下 29/30 failed=1，由
  EVAL-M3-04-N 击杀）；8/8 restored=true、hash_match=true（oracle 零残留）。注：首次重跑曾
  8×skipped_dirty——M6 模块变异序列并行进行中（src/m6_flywheel/attest.py 中间态），等待其还原
  完成后（oracle 转干净）再跑即全杀；本工具未触碰任何 oracle 之外的文件状态。

---

## 2026-09-29 · M4 变异覆盖缺口修复（mutation survivors → 19 条；红线变异全杀）

- **模块**：M4（受控变异测试 `scripts/mutation_test.py --module m4 --plan .mutations/plan-m4.json`
  反证 EVAL 覆盖；`tests/test_m4.yaml` 增补 2 用例 + 新增补充执行器插件 `tests/m4_eval_extra.py`）
- **上轮登记勘误（工具侧，非覆盖缺口）**：本轮收到的变异结果
  `survivors=["结果文件缺失","工具失败: can't open file 'D:\workspace\xunfei4\scripts\mutation_test.py'"]`
  系变异工具自**父目录**（`D:\workspace\xunfei4`）启动、未进入仓库根所致——`results-m4.json`
  根本未产出，两条"survivor"均为启动失败伪影，非行为变异存活。已从仓库根重跑受控工具修正。
  首次重跑遇并行模块变异窗口（m6 `src/m6_flywheel/golden_set.py` 在变异中，工具 dirty 守卫
  按设计跳过全部变异），窗口关闭后重跑成功：`planned=7 valid=7 killed=4 survivors=3`。
- **真实变异结论与处置**（plan 7 变异 = 红线 5 + 非红线 2）：
  1. `m4-hop-declared-gate-off`（红线，survived→**已杀**）：声明跳数闸失效后 EVAL-M4-05-N1
     的四跳查询仍被第二道闸（关系步数>3）拒绝——两道闸共享一个负例、声明闸无独立守护。
     补 **EVAL-M4-05-N2**（hops=4 声明但路径仅 1 跳关系 → 仍拒绝；oracle 报错
     "查询跳数 4 超过上限 3：建议分解…"，关系步数闸的报错形态"查询路径含 N 跳关系"不含此断言串，
     断言未削弱）。重跑实测 killed。
  2. `m4-vocab-crosscheck-off`（非红线探测项，survived→**已杀**）：enums↔contracts 双向同源
     断言（SPEC-M4-01 分项校验第 1 项）无用例注入漂移。新增补充执行器 **`m4.loader_drift`**
     （`tests/m4_eval_extra.py`：ontology/ 临时副本注入 patch → `load_ontology(ontology_dir=副本,
     use_cache=False)` 断言拒绝；数据驱动零案例特判，不改 oracle——`src/` 零改动），
     补 **EVAL-M4-01-N3**（副本 enums.yaml 移除 alarm_level/P3 → 期望
     `OntologyLoadError` 含"受控词表不一致"）。重跑实测 killed。
  3. `m4-ambiguity-margin-shrink`（非红线，survived→**标注 invalid**）：死缺省变异——
     `resolver.py:100` 的 scores 取值在"aliases.yaml 无嵌套 scores 键"时回退顶层映射，而
     `ontology/aliases.yaml:28` 顶层提供 `unambiguous_margin: 0.3`，缺省分支不可达，
     变异 0.3→0.05 无行为效果（EVAL 全绿是正确结论）。已在 `.mutations/plan-m4.json` 该项标注
     `disposition: invalid` + 判据；真实阈值守护由 EVAL-M4-04-N1（数据文件 0.3 生效面）承担。
- **映射与登记同步**：`specs-v2/M4-semantic-ontology.md` §4.1/§4.2/§4.3 双向映射表更新
  （SPEC-M4-01 负例 +N3、SPEC-M4-05 负例 +N2）、§3.1/§3.3/§5/§6 条数与交付物修订（17→19）。
- **spec_hash → eval_hash**（01§6 协议；映射表变更 → spec_hash 重算）：

  | suite | 代 | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- | --- |
  | test_m4.yaml | v1 | `f93c7c26f4b63512e5d14efb81ce5c1506f5e7bcbfd731954d4fcbc1d07abbb8` | `513d21fffa02f54b63466d2450474a42a2140f8553a6af848c6583171e12db54` |
  | test_m4.yaml | v2-初版（17 条） | `8856222724ccae05a8942c5e65f1e5660d577c756540925168a00dc00fb3010a` | `75eb55911e4fc82a00ec6d3b3ef561e239bd79f1d9d8c273fde6f2a29dc22cd8` |
  | test_m4.yaml | v2-变异修复版（19 条） | `299018e7353da3663941e572dd85ced127686ab72b6edc63bbd0fdef27f44884` | `ab448986d22cb1a07422e47367c0b1949e02f4856a53130a2eb665a1a3bd12d2` |

- **静态自检**（本会话实跑，2026-09-29）：19 用例 YAML 可解析、schema 字段/id 正则全过；
  执行器 10 个全部注册（`m4_semantic.eval_plugin` 9 + `tests.m4_eval_extra` 1，导入成功）；
  fixtures 引用存在；spec_hash 声明与重算一致；SPEC-M4-01..09 全覆盖（P10/N9）；
  新增 2 用例 oracle 下直调干跑 2/2 passed（N3 报错"enums.alarm_level 与 contracts 受控词表不一致"、
  N2 报错"查询跳数 4 超过上限 3"）。变异复跑结论与全绿门禁以
  `python run_evals.py --module all` 及 `.mutations/results-m4.json` 最终版为准。

---

## 2026-09-29 · M6 EVAL v2-r2（变异测试补缺：add_golden_case 写入通道覆盖）

- **模块**：M6（`tests/test_m6.yaml` 19→20 条；新增 `tests/m6_eval_extra.py`；
  `specs-v2/M6-flywheel.md` §4 映射表/§5/§6 同步；处置说明
  `.mutations/plan-m6-notes.md`）
- **诱因**：scripts/mutation_test.py 重跑 plan-m6 实证 survivor
  `m6-holdout-addcase-allow`——`add_golden_case` 开发写入通道 holdout 拒绝
  （`src/m6_flywheel/golden_set.py:278-281`，SPEC-M6-02③⑧）失效后 eval 仍全绿
  （v1/v2 均无用例覆盖该冻结 API）。交办单所报另两条 survivors
  （"结果文件缺失"/"工具失败 …xunfei4\scripts\mutation_test.py"）定性为 harness
  伪幸存者（以父目录为根调用致工具未启动），见 `.mutations/plan-m6-notes.md`。
- **修复**（零 oracle 改动、断言不弱化）：新增 tests 侧执行器
  `m6.golden_add_case`（`tests/m6_eval_extra.py`，EVAL-SCHEMA §4 插件协议，
  `tests.m7_eval_extra` 同款先例）+ 用例 **EVAL-M6-02-N2**（spec=SPEC-M6-02，
  禁止类负例）：正例经 `add_golden_case` 落盘+manifest 登记（含 sha256）+
  `golden.case_added` 事件恰 1 条（producer=M6）；holdout 标记条目
  GoldenSetError（含 holdout/SPEC-M6-02）且零事件；同 id 旧版本重交拒绝
  （含"严格递增"）；目录装载集合无泄露。
- **spec_ref**（按序拼接取 hash，run_evals.py:819-825 口径）：
  - `specs-v2/M6-flywheel.md`（§4 映射表更新后重算）
  - `specs-v2/00-ontology.md`
  - `specs-v2/01-contracts.md`
  - `specs/ADDENDUM.md`
- **spec_hash → eval_hash**（01 v2 §6 协议）：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m6.yaml | `9f4e695893a3b762d53cc9e2e6de3d87de2c9a96ee411d8a249a5ce6d827d956` | `6a7b69864e686162625b2f617f71277929c903ddccd9b92346b25a9a85e7df3b` |

  上版（v2-r1，19 条）存照：spec `8b5b941d608e842f90e62de752ea358a9bb7ac5e85267f6572ec36805ecb2aba`
  → eval `ebb3a2e73c345f7d4fe58624c9a7ae25c7bbc48928692994b5bcee7e1f63f1e0`。

- **验证**（本会话实跑）：
  1. 静态自检：YAML 解析 OK；20 用例 schema/id 正则/form 全过；执行器注册核查
     （m6_flywheel.eval_plugin 12 + m7_registry.eval_plugin + tests.m6_eval_extra
     1，实际 import 验证）；引用路径存在；spec_hash 重算一致。
  2. 变异基线：`cases=20/20 failed=0 result=PASS`。
  3. 变异核查：单变异计划（plan-m6-fixcheck）下 survivor
     `m6-holdout-addcase-allow` 由 **survived 转 killed**
     （`cases=19/20 failed=1 result=FAIL`，恰为 EVAL-M6-02-N2 捕获；
     restored=true、hash_match=true）；全计划 8 变异完整结果见
     `.mutations/results-m6.json` 最新 valid=8 运行（并发变异测试期间
     skipped_dirty 者经重试循环补齐，过程日志 `.mutations/run-m6-attempt*.log`）。

---

## 2026-09-29 · M2 变异复跑结论（真实 survivor 已杀：redline_all_killed=True）

- **模块**：M2（对上文"M2 EVAL v2 修订"节的收尾登记；`tests/test_m2.yaml` 最终 30 条）。
- **有效变异轮结论**（`python scripts/mutation_test.py --module m2
  --plan .mutations/plan-m2.json --baseline`，仓库根正确路径，oracle 干净窗口内实跑；
  权威结果 `.mutations/results-m2.json` + `.mutations/baseline-m2.json`）：
  `planned=6 valid=6 killed=6 survivors=0 redline_all_killed=True`；基线
  `cases=30/30 failed=0 result=PASS`（exit 0）；6 个变异全部 restored+hash_match。
- **真实 survivor 的发现与处置**：首轮有效运行（29 条用例基线）曾报 1 条真实
  survivor——`m2-crosswrite-allow`（红线级，`src/m2_information/workspace.py` 跨任务写
  兜底拒绝 `raise error`→`return` 解除后 EVAL 仍全绿）。根因：EVAL-M2-09-N 的目标
  `artifacts/evil.txt` 在 `_check_cross` 即被拒（走 re-raise 路径，变异不触达），v2
  SPEC-M2-09 明文的"即便路径类别属只读可读也一律拒绝"兜底分支无用例。处置：新增
  **EVAL-M2-09-N2**（目标 `evidence/leak.json`——路径类别通过跨任务读白名单，必须走
  兜底拒绝分支；断言拒绝+未落盘+审计事件不变），复用现有执行器 `m2.workspace_crosswrite`，
  零 oracle 改动；复跑 6/6 全杀。EVAL-M2-09-N 原判据未削弱。
- **并发干扰存照**：本模块重跑期间多次进入 `skipped_dirty`（并行工程师的 m1/m6 等
  变异轮持有 oracle 路径）；`skipped_dirty` 轮的 results-m2.json（valid=0）均为运行
  无效产物，以本节记录的有效轮为准。工具的 oracle 干净检查+强制还原+归一化 hash
  比对全程生效（6/6 restored）。
- **最终登记对**（与上文修订节一致）：spec_hash
  `7f2096f2a8e3b9c9838d72bbf5a0248a479576efca28d3de803b46ad8160e154` → eval_hash
  `9a755cb06b63c2f3c3fab7649d37af4cf64ee4d742e9de6cc129ae04fb239d81`（上文修订节的
  1a02565f→8deac6b1 为 29 条中间态，存照；规格 §4 映射表 09 行与新增 7 条说明为
  本对 spec_hash 的组成部分）。

---

## 2026-09-29 · M6 EVAL v2-r3（变异测试补缺 II：attest 载荷级签名比对；全 8 变异杀灭）

- **模块**：M6（`tests/test_m6.yaml` 20→21 条；`tests/m6_eval_extra.py` 增执行器
  `m6.attest_verify`；`specs-v2/M6-flywheel.md` §4 映射表/§5/§6 同步；
  处置说明 `.mutations/plan-m6-notes.md` §5）
- **诱因**：20 条套件下首次完整变异运行（valid=8）暴露 redline survivor
  `m6-attest-signature-off`——`src/m6_flywheel/attest.py:115` 载荷级签名重算比对
  （`if signature != recomputed`）失效后 eval 仍全绿。根因：EVAL-M6-08-N 三探针
  均在 M7 消费侧被拒（结构检查/digest/producer 先于 attest 重算，见
  `src/m7_registry/release.py:223-240,255-259`），attest 重算比对不可达。
- **修复**（零 oracle 改动、断言不弱化）：执行器 `m6.attest_verify`（attest 纯
  计算，零落盘、零事件）+ 用例 **EVAL-M6-08-N2**（spec=SPEC-M6-08，禁止类负例）：
  同报告两次签名确定性复算一致、producer/kind 合约、合法凭证 verify 通过（含
  expect 绑定）；6 个篡改变体（payload.cases / payload.pass_rate / 伪造
  signature → "签名校验失败"；非 M6 producer → "签名方"；缺 payload 字段 →
  "缺字段"；expect 绑定其它 release → 含 release_id 的不符拒绝）全部
  AttestationError——`if False and signature != recomputed` 变异使前三个变体
  逃逸即用例失败，杀伤面直达。
- **spec_ref**（按序拼接取 hash，run_evals.py:819-825 口径）：
  - `specs-v2/M6-flywheel.md`（§4 映射表更新后重算）
  - `specs-v2/00-ontology.md`
  - `specs-v2/01-contracts.md`
  - `specs/ADDENDUM.md`
- **spec_hash → eval_hash**（01 v2 §6 协议）：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m6.yaml | `4596d50fbf4575cb483b5a6a28933da34e83772d57a66760d2e9863afa360d61` | `2ed3637d407562a491c67d780de702de29d834ee1608bd201a7a8b26afaff769` |

  上版（v2-r2，20 条）存照：spec `9f4e695893a3b762d53cc9e2e6de3d87de2c9a96ee411d8a249a5ce6d827d956`
  → eval `6a7b69864e686162625b2f617f71277929c903ddccd9b92346b25a9a85e7df3b`。

- **验证**（本会话实跑）：
  1. 静态自检：21 用例 schema/id/form/执行器注册/spec_hash 重算全过，
     映射完整（SPEC-M6-01..08，正例 10 / 负例 11）。
  2. 基线：`EVALS mode=m6 … cases=21/21 failed=0 result=PASS`。
  3. 全计划变异终局（`.mutations/results-m6.json`）：
     `planned=8 valid=8 killed=8 survivors=0 redline_all_killed=True`
     （8/8 含 5 个 redline 变异全部 killed；全部 restored=true、hash_match=true；
     oracle 路径 `git status` 干净复核）。并发变异测试期间的 skipped_dirty /
     index.lock 中断均经重试循环与当场还原处置（过程日志
     `.mutations/run-m6-attempt*.log`）。

---

## 2026-09-29 · 资产冻结收口（M5 全量变异权威重跑 + 统一门禁复跑 + 冻结台账）

- **M5 全量变异权威重跑（上文 M5 变异缺口修复节所预约的统一门禁复跑，已执行）**：
  `python scripts/mutation_test.py --module m5 --plan .mutations/plan-m5.json --baseline`
  （仓库根、干净 oracle 窗口、无并发变异）→ 基线 `cases=27/27 failed=0 result=PASS`
  exit 0；**planned=7 valid=7 killed=7 survivors=0 redline_all_killed=true**（7/7 全部
  executed kill、restored=true、hash_match=true，轮后 oracle 树复核干净）。权威结果
  `.mutations/results-m5.json`（覆盖此前 skipped_dirty 版）；`.mutations/plan-m5-recheck.json`
  单变异计划完成历史使命，两份存照（first-run/recheck）保留。至此 7 模块 52 变异
  权威终局：51 条行为变异全杀、1 条无效变异（m4-ambiguity-margin-shrink，plan-m4.json
  disposition=invalid）、红线全模块 true——汇总见 `ASSET-MANIFEST.md` §4。
- **统一门禁复跑（冻结门禁）**：`python run_evals.py --module all` →
  `EVALS mode=all isolation=OK modules=8/8 pending=0 cases=233/233 failed=0 skipped=0
  result=PASS`（exit 0；runner 按 run_evals.py:819-825 口径重算 8 套件 spec_hash 与
  声明值一致）。8 套件 eval_hash 与本台账最新登记对逐位一致（冻结会话逐文件实测）。
- **冻结产出**：`specs-v2/DEVIATIONS.md`（D-01..D-71 全量偏差汇总表，含 disposition 与
  条款号索引；正式处置以 deviations/M1..M7.md 为准）、`ASSET-MANIFEST.md`（specs-v2/
  19 件 + tests/test_m0..m7.yaml sha256、映射完整性结论、变异杀灭率汇总、oracle 未改动
  声明——基线 commit `1fd8901`）、`specs/README.md` 顶部弃用指针一行（v1 原文未动）。
  本条目为台账收口登记，无 spec/eval 内容变更（spec_hash/eval_hash 登记对不变）。

---

## 2026-09-29 · 独立复核修复（v2 索引/计数/指针文档卫生 + SPEC-M6-02⑦ 公式钉死；m1/m2/m5/m6 spec_hash 重算登记）

- **触发**：独立复核（冻结后）指出 5 项——①specs-v2/README.md 交付物表 M1..M6 与
  deviations 七件状态列仍标 ⏳（实际全部已产出）、ASSET-MANIFEST.md 标「占位」（实际已
  生成）、m7 记 16→26（实际 27）、基线门禁记 180/180（v1 期旧数，实际 233）、spec_ref
  口径写「各套件仍指 v1」（与 m2/m5/m7 实际 specs-v2 指向矛盾）；②M5/M3/M2/M1 规格内
  用例计数未随末轮变异补缺回写（M5 26→27、M3 29/25→30、M2 27→30、M1 交付物 20→30）
  及 tests/test_m5.yaml 头注 26；③M5 SPEC-M5-13 证据指针「tests/CHANGELOG.md ADDENDUM
  §C」悬空（该文件无 §C 章节；代码事实经复核为真）；④隔离字面口径：specs-v2 树命中 7 行
  （全部为隔离条款自述/与 v1 同源的 holdout 设计描述，golden/scenarios/src/tests 四树零
  命中，ci_isolation 扫描面本就排除 specs/，隔离意图未破）——照实登记 ASSET-MANIFEST §8，
  是否显式裁剪 00 v2 §5 holdout 参数描述待 owner 裁决；⑤SPEC-M6-02⑦ golden_set_version
  公式未指明排序单元与拼接分隔符。
- **修复**（零 oracle 改动）：①README.md 五处状态/数字/口径改为实况（ADDENDUM.md 行保持
  ⏳——仍未产出）；②四处计数与 test_m5.yaml 头注回写实况（套件用例数不变：总数仍 233）；
  ③指针改为代码锚点（`src/contracts/enums.py:224-225`、`price_clock.py:75-97,143-161`）+
  处置登记位（deviations/M5.md D-69 行、DEVIATIONS.md ADDENDUM 节）；⑤SPEC-M6-02⑦ 按
  `golden_set.py:248-255` 钉死精确定义（排序单元=`"<文件名>:<文件字节 sha256 十六进制>"`、
  竖线 `"|"` 拼接、sha256 前 16 位、前缀目录名）——冻结会话按该定义对 `golden/dev` 重算得
  `dev-f7e4e295e43be004`，与 `releases/rel-0001/release.yaml` 登记值及 oracle 函数输出三方
  逐位一致。
- **spec_hash → eval_hash**（01 v2 §6 协议；上述修订使 M1/M2/M5/M6 规格 spec_ref 字节变化，
  四套件 spec_hash 重算、套件文件 spec_hash 字段同步回写、eval_hash 随文件字节更新；本轮
  纯文档/头注修订，条款语义与用例断言零变化，总数 233 不变）：

  | suite | 新 spec_hash (sha256) | 新 eval_hash (sha256) |
  | --- | --- | --- |
  | test_m1.yaml | `0b5be472b45c879f3675be791358d04a618d21dbd172c876ef3032dd0123cac0` | `e7ab5eb5bfc565dfd0f2ba576197499f0307a093baef6d5a202ec99b1b2e1eda` |
  | test_m2.yaml | `8804ebce740f13259912dbfd1edbd0f35e657c50a160b0cedcf4a7b5a515feaa` | `487d754ce6bf36200e744f5b07a336a6b01cdd652a3bd4834ce59cc5f0cea8cb` |
  | test_m5.yaml | `641cab4d9261324dae2bdd23009f39ff07e7c139d755897d3d3e176bc7de4e5d` | `ffd71edc0031b09aa5f70773ac0defcf34a228ef60bd70ed87ad01f1aef5766a` |
  | test_m6.yaml | `f90a3d34f23387a115dde173cc4601ff8b965941c7de6280b32773055d39ebce` | `f847adec42e3d474894ef0757ce8a1798646eb223bb1777ea25d1ca9824ec72c` |

  前版登记对存照：m1 `e34bf325…`→`8a09c9e6…`；m2 `7f2096f2…`→`9a755cb0…`；m5
  `46051061…`→`31d55310…`；m6 `4596d50f…`→`2ed3637d…`（均为本文件上文各节登记值）。
  m3（spec_ref=v1 四文件，本轮只改 specs-v2/M3 文档计数，不入 hash）/m0/m4/m7 套件
  hash 对不变。
- **门禁**：修复后统一门禁复跑 `python run_evals.py --module all`（本节登记时点实跑，
  结果与退出码见 ASSET-MANIFEST.md §7 复核修复轮记录）。

---

## 2026-09-30 · M9 套件新增（应急分级技能 skills/emergency-grading 雏形；汇报前夜 Q&A 弹药）

- **背景**：观众提出「应急预警的分级分类：什么情况启动哪个级别的应急、哪个级别对应
  哪些岗位哪些操作」。新增技能 `skills/emergency-grading/`（SKILL.yaml 描述子+数据驱动
  映射表 / SKILL.md 行为规格 EG-SPEC-01..08 / grade.py 确定性判定脚本 + examples 样例），
  不进演示主线。映射表覆盖 10 类事件（重瓦斯/差动跳闸、母线失压、火灾、重过载、通信
  全中断、直流接地、电缆沟水浸、台风暴雨预警、轻瓦斯），四级 Ⅰ/Ⅱ/Ⅲ/Ⅳ × 响应时限 ×
  四岗位（值班员/调度员/签发人/审批人）操作清单 × 升级/解除条件；与系统告警级别
  P0-P3 对齐（P0→[Ⅰ,Ⅱ]、P1→[Ⅱ,Ⅲ]、P2→[Ⅲ,Ⅳ]、P3→[Ⅳ]，响应语义锚
  `src/contracts/enums.py:50-55`），表内注明为示范规则、可整表替换园区备案预案
  （grade.py 零硬编码，`--mapping` 指向替换表即换档）。
- **套件**：`tests/test_m9.yaml` 8 例（P 6 / N 2）——01-P 分级正确性（basis 引用
  告警 ID×rule_id）/ 02-P 多告警取最高级 / 03-P 时限与岗位输出 / 04-N 未知事件兜底
  （MANUAL_REQUIRED、不猜级、上报人工判定）/ 05-P 确定性（3 轮渲染 + 2 次 CLI 双跑
  逐字节一致）/ 06-P 数据驱动性（沙箱副本改 EMG-R09 条目 Ⅳ→Ⅱ，线上表 sha256 前后
  不变，替换表落盘重载复算一致）/ 07-N 负向拒绝（缺 id、空 type、重复 id →
  GradeInputError；映射事件类型二义 → MappingError）/ 08-P 混合场景（已知Ⅱ+未知并存，
  升级/解除条件输出）。
- **执行器插件**：`tests/m9_eval_extra.py`（EXECUTORS 4 个：m9.grade / m9.determinism /
  m9.data_driven / m9.negative_input；沙箱 `runtime/m9_eval/<case>/`）。
- **spec_hash → eval_hash**（01§6 口径；spec_ref = skills/emergency-grading/{SKILL.yaml,
  SKILL.md} 按序拼接字节）：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m9.yaml | `a0aaf1fb86df73389d95fa6d6d217945ce5a5d32b01afb74fa02c76fa0d1c667` | `ec782db02250a48048ca228b1fa21b8e3d01b5916431fb82df93d39964275b32` |

- **运行方式与门禁关系**：`run_evals.py` 的 MODULES 固定 m0..m7（核心资产只读，本夜不
  改），m9 不进 `--module all` 门禁；套件经插件入口 `python tests/m9_eval_extra.py`
  以同一 runner 路径执行（schema 校验 + spec_hash 重算比对 + 插件加载 + 逐用例执行），
  本轮实跑 `EVALS-M9 mode=suite status=RAN cases=8/8 failed=0 skipped=0 result=PASS`
  （exit 0）。
- **门禁**：新增后统一门禁复跑 `python run_evals.py --module all` →
  `EVALS mode=all isolation=OK modules=8/8 pending=0 cases=233/233 failed=0 skipped=0
  result=PASS`（exit 0，本轮实跑）；`python scripts/ci_isolation.py` → 零命中
  （新增 skills/ 与 tests/ 文件按 ISOLATION_PATTERN 实扫，exit 0）。
