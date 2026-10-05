# specs-v2 · DEVIATIONS（v1 规格 ↔ oracle 全量偏差总表，资产冻结版）

> **生成**：2026-09-29 资产冻结员（资产工程阶段收口）。本文件是 v1→v2 全量偏差的**汇总总表**：
> 逐模块正式处置见 `specs-v2/deviations/M1..M7.md`（本表 disposition 与条款号以其为准），
> 盘点初稿见 `specs-v2/DEVIATIONS-draft.md`（D-01..D-71 划分与摘要的来源）。
> 三者关系：draft（盘点）→ deviations/<模块>.md（逐条按 oracle 复核后的正式处置）→ 本文件（冻结汇总）。
>
> **oracle**（唯一事实源）= 现行实现全体：`src/`（m1_core..m7_registry、contracts）、`tools/`、
> `ontology/`、`regulations/`、`golden/dev/`、`scenarios/`、`releases/rel-0001/`、`scripts/`、`run_evals.py`。
> **v1 规格** = `specs/README.md`、`specs/00-ontology.md`、`specs/01-contracts.md`、`specs/M1..M7`、
> `specs/ADDENDUM.md`（v1 原文保留不删，`specs/README.md` 顶部有弃用指针）。
> **偏差权威线索** = `tests/CHANGELOG.md` 全部 deviation/revision 条目 + 各模块 commit message。
>
> **类型**：〔新增〕v1 没写的行为；〔变义〕v1 措辞已不符；〔强制〕v1 仅隐含、oracle 已代码级强制；
> 〔扩展〕API/数据的向后兼容增补；〔缺陷〕KNOWN-DEFECT（验收发现未修）。
> **处置取值**：吸收为条款（v2 条款号）｜ KNOWN-DEFECT（登记不修）｜ 显式排除（说明）。
> 表外补强 EVAL（`-P2/-N2/-N3/PERF/SAFE*/APPR*/EVLOG/DEV` 等）一律是 eval 资产登记，
> 不构成规格条款缺口，不设独立偏差条目；其中改变行为口径的已并入对应行为条目。
>
> **oracle 健康核验（冻结会话实跑，2026-09-29）**：`python run_evals.py --module all` 与
> `python scripts/mutation_test.py --module m5 --plan .mutations/plan-m5.json --baseline`
>（全 7 变异 killed、还原校验全过、轮后 oracle 树干净）——见 ASSET-MANIFEST.md。

## 汇总统计

| 层/模块 | 条目 | 吸收为条款 | KNOWN-DEFECT | 显式排除 | 正式处置记录 |
| --- | --- | --- | --- | --- | --- |
| S0/契约层 | D-01..D-06（6） | 6 | — | — | 01 v2 内 `[v2Δ]` 标记 + 各模块文件交叉引用行 |
| M1 | D-07..D-16（10） | 9 | — | 1（D-16） | deviations/M1.md |
| M2 | D-17..D-23（7） | 7 | — | — | deviations/M2.md |
| M3/tools | D-24..D-33、D-59（11） | 10 | 1（D-59） | — | deviations/M3.md |
| M4 | D-34..D-37（4） | 4 | — | — | deviations/M4.md |
| M5 | D-38..D-47（10） | 10 | — | — | deviations/M5.md |
| M6 | D-48..D-58（11） | 10 | 1（D-58） | — | deviations/M6.md |
| M7 | D-60..D-66（7） | 7 | — | — | deviations/M7.md |
| ADDENDUM | D-67..D-71（5） | 5 | — | — | 00/01 v2 `[v2Δ]` 标记 + M2/M4/M5/M6.md 侧落地行 |
| **合计** | **71** | **68** | **2** | **1** | — |

---

## S0 / 冻结契约层（D-01..D-06）

| D-编号 | 类型 | 偏差（摘要） | v2 处置与条款号索引 | 证据锚点 |
| --- | --- | --- | --- | --- |
| D-01 | 〔变义〕 | DENY 判定终态拼写：v1 写 `DENY→DENYED`，oracle 为 `DENIED` | 吸收为条款——01 v2 §5.2 冻结迁移表与 `§8 v1→v2 对照表:820`（`[v2Δ D-01]`）；关联 M3 SPEC-M3-04、M5 SPEC-M5-03（D-47 终态对齐） | `src/contracts/enums.py:83`；`01-contracts.md:725,820`；tests/CHANGELOG.md S0 登记 1 |
| D-02 | 〔变义〕 | `FAILED→COMPENSATED` 实为条件迁移（reversible 且有 compensation），不进无条件迁移表 | 吸收为条款——01 v2 §5.2 状态机表区分无条件迁移与 `conditional_transitions`（`:696-697,728-730`；`§8:821`） | `tests/fixtures/frozen_state_machines.yaml`（conditional_transitions）；tests/CHANGELOG.md S0 登记 2 |
| D-03 | 〔变义〕 | `EventRecord.event_id` 契约标注 `string(ulid)`，oracle 放宽为非空字符串并存在"流内序号"形态 | 吸收为条款——01 v2 §2 注记 `:99,:207,:224`（唯一性域=事件流，双形态）；关联 M3 SPEC-M3-12（`EVT-M3-<seq>`） | `src/contracts/base.py:164-166`；`src/m5_simulation/env.py:209`；tests/CHANGELOG.md M3 登记 9 |
| D-04 | 〔变义〕 | 时间戳字段接受 UTC ISO-8601 字符串与 pyyaml UTC datetime 双形态；`ScenarioSpec.at` 为时间引用 | 吸收为条款——01 v2 §2 约定 2 注记 `:111` 与 §8 `:797`（非 UTC 拒绝不变）；关联 M3 SPEC-M3-14 | `src/contracts/base.py:126`；tests/CHANGELOG.md S0 登记 4 |
| D-05 | 〔变义〕 | v1 README §0 称"11 数据结构"，01§2 实定义 **12 个**（§2.1–§2.12，含 ReleaseBundle） | 吸收为条款——计数修正 12；specs-v2/README.md §0 `[v2Δ D-05]`（`README.md:29`）；01 v2 §2.1–§2.12 | `specs/README.md:11`；`src/contracts/__init__.py`（STRUCTURES 全部代码化）；tests/CHANGELOG.md S0 登记 6 |
| D-06 | 〔新增·系统级〕 | 事件目录封闭集（28 主题）下的"就近落主题"扩展通道族：①`budget.warning{kind:token,cost{…}}` 兼成本上报；②非状态字段提交落 `task.status_changed{from==to}`；③跨域审计落 `action.policy_decided{DENY,stage:admission}`；④调优/评审侧审计落 `release.published{rejected:true / stage:…}` | 吸收为条款——01 v2 §4 扩展通道族成文（`§8:802`）；模块落位：M1 SPEC-M1-10、M2 SPEC-M2-07/09/12、M3 SPEC-M3-02、M6 SPEC-M6-01③/06②、M7 SPEC-M7-17 | `src/m1_core/loop.py:685-693`；`src/m2_information/workspace.py:222-238`；`src/m3_action/gateway.py:429-454`；`src/m6_flywheel/evaluator.py:222-236`；`src/m7_registry/review.py:218-242` |

## M1 Agent Core（D-07..D-16，正式记录 = deviations/M1.md）

| D-编号 | 类型 | 偏差（摘要） | v2 处置 | v2 条款号 |
| --- | --- | --- | --- | --- |
| D-07 | 〔新增〕 | Loop 五阶段回放校验数据源=M1 审计件 LoopTrace（`runtime/<root>/m1_core/loop/task-<id>.jsonl`），非 01§4 事件流；每轮为 PREPARE→MODEL→ACT→OBSERVE→VERIFY 前缀 | 吸收为条款——LoopTrace 与事件流双轨定位 | SPEC-M1-11 |
| D-08 | 〔新增〕 | 每轮成本上报以 `budget.warning{kind:token,cost{…}}` 兼作通道 | 吸收为条款（并入 D-06，M1 侧引用） | SPEC-M1-10 |
| D-09 | 〔新增〕 | 完成门禁：`is_completable` + `CompletionRequiredError`；拒绝事件双标记 `rejected:true`/`accepted:false` | 吸收为条款 | SPEC-M1-02、SPEC-M1-06 |
| D-10 | 〔新增〕 | 产物过门匹配双口径：artifact_id 精确**或** schema_id 匹配 | 吸收为条款 | SPEC-M1-04（SPEC-M1-06 同口径引用） |
| D-11 | 〔新增〕 | write.report 后数据驱动产物策略自动落 ArtifactRecord（DRAFT→VALIDATING→READY）；同 action_id 幂等去重 | 吸收为条款 | SPEC-M1-12 |
| D-12 | 〔新增〕 | 预算耗尽口径：used≥max；deadline `now>deadline`；price_window `now∉[from,to]`；基准=注入 now（唯一真实时钟位 `clocking.now_iso()`） | 吸收为条款 | SPEC-M1-05 |
| D-13 | 〔新增〕 | ResumeEvent 状态-种类匹配矩阵（PAUSED 重查预算等），错配即拒 | 吸收为条款 | SPEC-M1-09（PAUSED 重查见 SPEC-M1-05） |
| D-14 | 〔新增〕 | trace 轮次台账：轮号=LoopTrace 最大轮号+1，Checkpoint 恢后续增 | 吸收为条款 | SPEC-M1-11（恢复语义见 SPEC-M1-09） |
| D-15 | 〔新增〕 | model_client SSRF 边界 `_assert_safe_endpoint()` fail-closed（仅 https/拒内嵌凭据/拒私网回环元数据 CGNAT ULA/白名单 env）+ 缺省传输改 `http.client` 直连 | 吸收为条款——安全边界条款（客户端行为 + SSRF 边界两条） | SPEC-M1-13、SPEC-M1-14 |
| D-16 | 〔新增·minor〕 | TaskContext 缺省 `actor_user="OP-001"`、`actor_agent="park-agent@v1"` 硬编码 | **显式排除**——构造入参可覆盖的缺省值，无行为锁定；v2 §2 组件注记与 01 v2 §3.1 成文 | （无条款；SPEC-M1-15 注记） |

## M2 Information（D-17..D-23 + D-68 侧落地，正式记录 = deviations/M2.md）

| D-编号 | 类型 | 偏差（摘要） | v2 处置 | v2 条款号 |
| --- | --- | --- | --- | --- |
| D-17 | 〔新增〕 | ContextManifest source 五字段封闭集；裁剪记录"双落"（tokens=0 留存 + origin 注记 + `workspace/manifest/turn-<n>.json`） | 吸收为条款 | SPEC-M2-04 |
| D-18 | 〔新增〕 | 非状态字段提交落 `task.status_changed{from==to}`，重建按同一 `apply_state_mutation` 折叠 | 吸收为条款（01 v2 §4 扩展通道 2 = D-06②） | SPEC-M2-07 |
| D-19 | 〔强制〕 | policy 永不裁负向口径：仅剩 SYSTEM_POLICY 仍超预算→拒绝编译 + `budget.exhausted` + PAUSED + `ContextBudgetExceededError` | 吸收为条款 | SPEC-M2-03 |
| D-20 | 〔变义〕 | write_memory 未过六问返回字面量哨兵 `"REJECTED"`；`last_rejection`；SPECULATIVE 归因 verification 问 | 吸收为条款 | SPEC-M2-12 |
| D-21 | 〔变义〕 | Skill 披露可见状态缺省仅 PUBLISHED；level0 ≤10 词强校验；域匹配=集合交集 | 吸收为条款 | SPEC-M2-14 |
| D-22 | 〔变义〕 | StateStore 表超集（+knowledge/sessions/calls）；`StateStore(dsn)` 可配、`postgres*` 抛 NotImplementedError | 吸收为条款（超集不违反最小集） | SPEC-M2-08 |
| D-23 | 〔新增〕 | Manifest hash 确定性输入口径（五元组规范 JSON；`compiled_at`/ULID 不进 hash；origin 指纹） | 吸收为条款 | SPEC-M2-01 |
| D-68（M2 侧） | 〔强制〕 | ADDENDUM §B report.daily@v1 四段校验 + 规则 ID 存在性（`rule_id_checker()` 工厂注入全部构造点） | 吸收为条款 | SPEC-M2-10 |

## M3 Action Gateway（D-24..D-33、D-59，正式记录 = deviations/M3.md）

| D-编号 | 类型 | 偏差（摘要） | v2 处置 | v2 条款号 |
| --- | --- | --- | --- | --- |
| D-24 | 〔新增〕 | 准入失败不进生命周期：状态 REJECTED、不落 `action.requested`，审计落 `action.policy_decided{DENY,stage:admission}` | 吸收为条款 | SPEC-M3-02 |
| D-25 | 〔变义〕 | 不可改清单对 ASK 锁定动作拒绝**一切**覆盖（含收紧 ASK→DENY） | 吸收为条款（policy_locked 语义） | SPEC-M3-05（矩阵见 SPEC-M3-15） |
| D-26 | 〔变义〕 | 角色收紧基准=当前生效判定（已存覆盖优先于缺省）；合法方向 ALLOW→ASK/ALLOW→DENY/ASK→DENY | 吸收为条款 | SPEC-M3-06 |
| D-27 | 〔变义〕 | tools/ 16 适配器一动作一模块（"."→"__"）；registry 兜底 sys.path；schema/幂等键/披露面=适配器声明，风险/缺省 Policy=`ontology/actions.yaml`（装配即断言 diff 空） | 吸收为条款 | SPEC-M3-03 |
| D-28 | 〔新增〕 | 幂等两档策略 + write-ahead journal `idempotency.jsonl` + 审批队列持久化 `approvals.jsonl` + 终态幂等回写 | 吸收为条款 | SPEC-M3-09（幂等）+ SPEC-M3-07（审批） |
| D-29 | 〔新增〕 | 失联执行器 `isolate_execution_env`：副本执行 + observer 独立回读降级 FAILED/`OBSERVATION_MISMATCH` | 吸收为条款 | SPEC-M3-10 |
| D-30 | 〔新增〕 | trace_id 从 task 派生（`trace-<task_id>`）；event_id=流内序号；SIMULATION latency_ms=0 | 吸收为条款（event_id 形态并入 D-03） | SPEC-M3-12 |
| D-31 | 〔变义〕 | REAL 门禁三重（评估上下文强制 SIMULATION + `PD_REAL_MODE` + 双人开关），仅 mock 适配器 | 吸收为条款 | SPEC-M3-11 |
| D-32 | 〔新增〕 | 审批权 fail-closed：仅已登记角色=审批人可决断；未登记/空花名册一律 REJECTED/`APPROVER_NOT_AUTHORIZED` | 吸收为条款 | SPEC-M3-08 |
| D-33 | 〔变义〕 | `create.switch_order` status 枚举收窄 `[DRAFT]`；DRAFT→ISSUED 仅持证签发人（`env.operators`）在 agent 动作集外完成；M5 非 DRAFT 一律 FAILED/`SAFE_ISSUE_HUMAN` | 吸收为条款（SAFE-ISSUE-HUMAN 的 M3 落位） | SPEC-M3-13 |
| D-59 | 〔缺陷〕 | **KNOWN-DEFECT**：`tools/modify__asset_history.py` PARAMS_SCHEMA `entry` 为裸 `"type":"object"`（无子结构约束）；该动作缺省 DENY 永不执行 | **KNOWN-DEFECT**——登记不修（DENY 红线动作，schema 收敛无行为收益） | SPEC-M3-16（当前行为+已知缺陷条款） |

## M4 Semantic（D-34..D-37 + D-70 侧落地，正式记录 = deviations/M4.md）

| D-编号 | 类型 | 偏差（摘要） | v2 处置 | v2 条款号 |
| --- | --- | --- | --- | --- |
| D-34 | 〔新增〕 | 实体解析歧义判据机械口径（aliases.yaml 数据驱动：0.8/0.6/0.5 + margin 0.3；"唯一消歧"语义） | 吸收为条款 | SPEC-M4-04 |
| D-35 | 〔新增〕 | 三跳路径：属性拾取步不计关系跳数（hops=3 声明，关系跳数=2） | 吸收为条款 | SPEC-M4-05（00 v2 §1.2 同步） |
| D-36 | 〔新增〕 | token 计量：CJK 1 token/字 + ASCII 词元 1/串（确定性估算） | 吸收为条款 | SPEC-M4-06 |
| D-37 | 〔变义〕 | 缺失概念比例 ≥30% 产出 `badcase.opened` **候选事件**（producer=M4）；持久化归 M2/M6；报告落 `runtime/coverage/task-<id>.json` | 吸收为条款（"候选"与"持久化"职责切分） | SPEC-M4-08 |
| D-70（M4 侧） | 〔强制〕 | ADDENDUM §D Park 实例按名加载（去扩展名/`ontology/` 缺省/`PARK_INSTANCE_PATH` 追加；同构实例通用） | 吸收为条款（M4 侧；M5 侧同条登记） | SPEC-M4-02 |

## M5 Simulation（D-38..D-47 + D-69/D-70 侧落地，正式记录 = deviations/M5.md）

| D-编号 | 类型 | 偏差（摘要） | v2 处置 | v2 条款号 |
| --- | --- | --- | --- | --- |
| D-38 | 〔新增〕 | 缺省种子由 manifest_hash 派生（确定性重放）；`run_scenario(seed=...)` 可覆盖 | 吸收为条款 | SPEC-M5-01 |
| D-39 | 〔变义〕 | 告警阈值唯一来源=`regulations/REG-TECH.yaml`（v1 §2 示例口径作废） | 吸收为条款并修订 M5 §2 措辞 | SPEC-M5-08（§2/SPEC-M5-09 同步） |
| D-40 | 〔新增〕 | dev-01 温度缓升注入=环境事件 `device.temp_rise`；新增规程条款 PHYS-TX-TEMP（>85→P2）+ 物理常数 `tx_temp_rise_c` 55K | 吸收为条款（PHYS-TX-TEMP 入规则目录） | SPEC-M5-12 / SPEC-M5-08（00 v2 §1.4） |
| D-41 | 〔新增〕 | `interactions.timeout_s`=墙钟秒，按 speed 换算仿真秒后判审批超时 | 吸收为条款 | SPEC-M5-11（SPEC-M5-02 交叉） |
| D-42 | 〔变义〕 | SIMULATION latency=确定性常数；diff 剔除 `AUDIT_COLUMNS` 三列；DENY/审批终态路径常数 1（已知小疵，随条款统一，非缺陷） | 吸收为条款（diff 剔除列成文） | SPEC-M5-01 / SPEC-M5-06 |
| D-43 | 〔新增〕 | EVAL 实例注入机制（`tests/fixtures/dev-sim-park.yaml`/`dev-graph.yaml` 经 `PARK_INSTANCE_PATH`，零实例特判） | 吸收为条款 | SPEC-M5-14 |
| D-44 | 〔强制〕 | 墙钟扫描口径：`m5_simulation/clock.py` 为唯一合法真实时钟实现位；扫描面 `[src,tools,scripts]`；CI 正则 `OP-1[0-9]` 等宽 | 吸收为条款 | SPEC-M5-02 |
| D-45 | 〔新增〕 | 复核审计三小项：persona 哨兵 `datetime.max`；`_soc_bounds` 物理量程 (0,100)；dev-02b 恢复 SENSOR_STUTTER 继承 | 吸收为条款 | SPEC-M5-04 / SPEC-M5-08 / §7 |
| D-46 | 〔强制〕 | SAFE 三规约在 M5 判据层强制（SAFE-ISSUE-HUMAN / SAFE-ORDER-SEQ / SAFE-SINGLE-OP，错误码与执行位） | 吸收为条款 | SPEC-M5-15（SPEC-M5-03 交叉） |
| D-47 | 〔变义〕 | DENY 路径数据驱动化（删 `_DENY_ALWAYS_HINT`，按 actions.yaml 现算）；终态改 **DENIED** | 吸收为条款（并入 D-01/D-06） | SPEC-M5-03 |
| D-69（M5 侧） | 〔扩展〕 | ADDENDUM §C 两事件落地（`price.period_changed` / `demand.month_rolled`，BUSINESS 时钟发布，共 28 主题） | 吸收为条款（正式记录归 ADDENDUM 层，此处交叉引用） | SPEC-M5-13 |
| D-70（M5 侧） | 〔扩展〕 | ADDENDUM §D Park 实例按名加载（M5 env 同一机制） | 吸收为条款（交叉引用，不重复计数） | SPEC-M5-14 |

## M6 Flywheel（D-48..D-58，正式记录 = deviations/M6.md）

| D-编号 | 类型 | 偏差（摘要） | v2 处置 | v2 条款号 |
| --- | --- | --- | --- | --- |
| D-48 | 〔新增〕 | MODEL_CALL 步判定=`budget.warning/exhausted` 且 `payload.kind=="token"`；事件→步型全函数映射 | 吸收为条款 | SPEC-M6-01③ |
| D-49 | 〔新增〕 | 判据引擎：rubric 外置 `golden/dev/rubrics.yaml`；表达式引擎无 eval/exec（扩展 `not in`）；五维权重和=1 | 吸收为条款 | SPEC-M6-03③④⑤ |
| D-50 | 〔扩展〕 | evaluator release 解析序扩展：`evaluation/cases.yaml` → `release.yaml` → mock 清单 → 内建 mock（向后兼容） | 吸收为条款 | SPEC-M6-07② |
| D-51 | 〔新增〕 | 黄金链路真实化：CaseRunner 经真实 M3 全链 + M2 生命周期；mock 计划不伪造事件 | 吸收为条款 | SPEC-M6-07③ |
| D-52 | 〔变义〕 | 黄金集 12 种子平铺 `golden/dev/`（兼容 cases/ 子目录）；MANIFEST 逐文件 sha256；verify 独立可执行；holdout 标记拒绝 | 吸收为条款 | SPEC-M6-02①③⑤⑥ |
| D-53 | 〔新增〕 | Badcase ADOPTED 判据：案例通过且总分 ≥ current；同 golden_set_version 硬校验；中间态可 REJECTED | 吸收为条款 | SPEC-M6-04①⑤⑥⑦ |
| D-54 | 〔新增〕 | 评估归档 `runs/eval/<UTC 时标>-<release_id>/`；EVAL 沙箱 `runtime/m6_eval/`；runs/ gitignore | 吸收为条款 | SPEC-M6-07⑨ |
| D-55 | 〔强制〕 | 评估与调优单向代码级落位：ReleaseGuard 只读；直改拒绝并落 `release.published{rejected:true,…}` | 吸收为条款 | SPEC-M6-06①② |
| D-56 | 〔强制〕 | Skill 化门槛：MIN_OCCURRENCES=3；候选 status 强制 REVIEW + `skill.promoted`；evidence_policy 强制 | 吸收为条款 | SPEC-M6-05①②③④ |
| D-57 | 〔扩展〕 | `export_trajectory(trace_id, *, release_id="sim")` 形参扩展（向后兼容） | 吸收为条款 | SPEC-M6-01① |
| D-58 | 〔缺陷〕 | **KNOWN-DEFECT**：evaluator 场景人因硬编码——审批决断人 `"OP-004"`（:520/:523）、actor.user 缺省 `"OP-001"`（:503）；仅 issue_by 签发链已数据化 | **KNOWN-DEFECT**——登记不修（mock 计划域内行为，rel-0001 验收已放行）；v2 改进条款：审批决断人来自场景数据 | SPEC-M6-07⑪ |

## M7 Registry & Release（D-60..D-66，正式记录 = deviations/M7.md）

| D-编号 | 类型 | 偏差（摘要） | v2 处置 | v2 条款号 |
| --- | --- | --- | --- | --- |
| D-60 | 〔变义〕 | 评审流/Release 状态机为 M7 自建表驱动（v1 引用的"01§5.4"不存在）；与 `m7_state_machines.yaml` diff 为空；审计落 `release.published{stage:…}` | 吸收为条款（01 v2 新增 §5.4/§5.5） | SPEC-M7-05、SPEC-M7-12、SPEC-M7-17 |
| D-61 | 〔新增〕 | 六要素空值口径：非空标量 + prompt/skill/tool_refs **非空列表**才视为已绑定 | 吸收为条款 | SPEC-M7-08 |
| D-62 | 〔新增〕 | AgentContract 绑定通道：发布目录快照 + `manifest.yaml.agent_contract`；`bundle_draft` 必携 `agent_ref` | 吸收为条款 | SPEC-M7-08（agent_ref）、SPEC-M7-13、SPEC-M7-14 |
| D-63 | 〔新增〕 | golden_scores 双层签名链（M7 digest + M6 attest）+ run_ref 三级解析序 + `import_golden_scores` 唯一产出口 | 吸收为条款 | SPEC-M7-09 |
| D-64 | 〔新增〕 | 评审基线：candidate 总分 ≥ 现行 release golden_scores；无现行 release 基线=0；M7 只消费不跑分 | 吸收为条款 | SPEC-M7-06 |
| D-65 | 〔变义〕 | 资产存储=JSONL journal（v1 写 SQLite）；chain 整数=版本链权威；未变更更新拒绝；`publish_asset` 唯一置 PUBLISHED 入口 | 吸收为条款（M7 §2 措辞修订 + 01 v2 §8 持久层形态横切条款） | SPEC-M7-02、SPEC-M7-07、SPEC-M7-17 |
| D-66 | 〔新增〕 | rel-0001 发布基线 + assemble CLI（20 资产全链发布；重入=只读复核；发布物含 `evaluation/`） | 吸收为条款（发布物形态+CLI）+ 资产基线登记（ASSET-MANIFEST.md 承接） | SPEC-M7-13、SPEC-M7-16 |

## ADDENDUM（D-67..D-71）

| D-编号 | 类型 | 偏差（摘要） | v2 处置与条款号索引 | 证据锚点 |
| --- | --- | --- | --- | --- |
| D-67 | 〔新增〕 | ADDENDUM §A REG-OP 五个规则 ID 全部落盘 `regulations/REG-OP.yaml`（SAFE-OP-TWO-TICKET/SAFE-OP-REMOTE/SAFE-OP-MAINTAIN/OP-QCOMP-CAP/OP-DEMAND-LIMIT，含从属关系） | 吸收为条款——00 v2「R-运维操作规程」节 REG-OP 目录转正（`00-ontology.md:186-189`；`§8 对照:401` `[v2Δ 已替代] D-67`） | `regulations/REG-OP.yaml` 全文核对；`specs/ADDENDUM.md:13-18` |
| D-68 | 〔强制〕 | ADDENDUM §B report.daily@v1 四段校验 + 规则 ID 存在性联动（`rule_id_checker()` 注入 m1/m2 eval_plugin、M6 CaseRunner） | 吸收为条款——SPEC-M2-10（M2 侧 artifact.py）、SPEC-M4-07（checker 工厂）、SPEC-M6-07③（CaseRunner 注入） | `src/m2_information/artifact.py:83-146`；`src/m4_semantic/regulation.py:146-156`；tests/CHANGELOG.md 独立评审缺口修复 2 |
| D-69 | 〔新增〕 | ADDENDUM §C 两事件落地：`price.period_changed{from,to,price,boundary}` / `demand.month_rolled{from_month,to_month,frozen_peak_kw}` 入 EventType 封闭集（28 主题） | 吸收为条款——01 v2 §4 事件目录（`01-contracts.md:659,662` `[v2Δ D-69]`）；行为条款 SPEC-M5-13 | `src/m5_simulation/price_clock.py:75-97,143-161`；`src/contracts/enums.py:224-225` |
| D-70 | 〔强制〕 | ADDENDUM §D Park 实例按名加载：去扩展名匹配、缺省 `ontology/`、`PARK_INSTANCE_PATH`（";"）追加；M4 loader 与 M5 env 同一机制，同构实例通用 | 吸收为条款——01 v2 注记（`01-contracts.md:272` `[v2Δ D-70]`）；SPEC-M4-02（loader 侧）、SPEC-M5-14（env/注入侧） | `src/m4_semantic/loader.py:63-64,175-206`；`src/m5_simulation/env.py:6,465-467`；tests/CHANGELOG.md M4 登记 1 + M5 登记 7 |
| D-71 | 〔强制〕 | ADDENDUM §E evaluator CLI：`--release`（必填）/`--golden`（缺省 `golden/dev/`）/`--mode`（REAL 拒绝 exit 2） | 吸收为条款——01 v2 注记（`01-contracts.md:597` `[v2Δ D-71]`）；行为条款 SPEC-M6-07⑩ | `src/m6_flywheel/evaluator.py:877-880`；tests/CHANGELOG.md M6 CLI 三参实测 |

---

## v2 条款号索引（模块 × 条款数 × 偏差来源）

| 模块 v2 规格 | v2 条款 | 条款数 | 全部映射偏差 | 非偏差性扩充 |
| --- | --- | --- | --- | --- |
| `M1-agent-core.md` | SPEC-M1-01..15 | 15 | D-07..D-15（+契约层 D-03/D-04/D-06 注记） | D-16 显式排除成文；SPEC-M1-15（actor 引用） |
| `M2-information.md` | SPEC-M2-01..14 | 14 | D-17..D-23、D-68、D-06②③ | — |
| `M3-action-gateway.md` | SPEC-M3-01..16 | 16 | D-24..D-33、D-59、D-01/D-03/D-04/D-06 引用 | — |
| `M4-semantic-ontology.md` | SPEC-M4-01..09 | 9 | D-34..D-37、D-70 | SPEC-M4-01（七项分项校验细化）、SPEC-M4-09（eval 资产同构，新增条款） |
| `M5-simulation.md` | SPEC-M5-01..15 | 15 | D-38..D-47、D-69/D-70 交叉、D-01 引用 | §2 物理模型条款化 |
| `M6-flywheel.md` | SPEC-M6-01..08 | 8 | D-48..D-57、D-58（KNOWN-DEFECT 条款）、D-71 引用 | SPEC-M6-07（评估运行全流程）、SPEC-M6-08（签名凭证）为新增条款 |
| `M7-registry-release.md` | SPEC-M7-01..17 | 17 | D-60..D-66、D-06/D-50 承接 | §4.1/§4.2 条款↔用例双向映射表 |
| 契约/本体（00+01 v2） | — | — | D-01..D-06、D-67、D-69、D-70、D-71（`[v2Δ]` 行内标记）+ 持久层横切（D-65） | §5.4/§5.5 两台状态机（D-60） |

> 用例映射完整性（冻结会话复核）：M1..M7 每条 v2 条款 ≥1 条 EVAL 用例覆盖——直接
> `spec:` 字段直指或经规格 §4/§5 映射表声明的共享映射（SPEC-M5-14 经 EVAL-M5-08-P/09-P
> 的 dev-sim-park 注入、SPEC-M7-13/17 经 REL-P/05-P/07-N/07-N3/12-P 共享映射，
> `M5-simulation.md:346`、`M7-registry-release.md:522,526`）；套件无未定义条款引用。
> 详见 ASSET-MANIFEST.md §映射完整性。

## KNOWN-DEFECT 与未决项

1. **D-58**（M6）：evaluator 场景人因硬编码（审批人 `OP-004` / user 缺省 `OP-001`）——登记不修，
   v2 改进条款见 SPEC-M6-07⑪（deviations/M6.md）。
2. **D-59**（M3/tools）：`modify__asset_history.py` schema `entry` 裸 object——登记不修，
   DENY 红线动作永不执行（deviations/M3.md）。
3. **R-1**（M7，资产工程阶段新发现，非 v1→oracle 偏差）：rel-0001 发布物
   `evaluation/cases.yaml` 与 manifest 登记 hash 不符（commit 06ce55a 发布后同步改写
   证据快照所致）——resolve_release 完整性门禁按设计拒绝，CLI 只读复核当前 ASSEMBLE
   REFUSED；处置二选一（还原发布时点内容 / re-publish），**待资产工程 owner 裁决**
   （deviations/M7.md §3 有完整 git 证据链与两个方案）。
4. **specs-v2/ADDENDUM.md 未产出**：v1 ADDENDUM §A-§F 已按 oracle 落地形态逐项核对
   （D-67..D-71 + D-44 的 §F 正则等宽），处置条款已分散落 00/01 v2 与模块 spec；
   `specs-v2/README.md` §0 交付物清单该行仍为 ⏳。受影响套件（m1/m3/m4/m5/m6/m7）的
   spec_ref 暂引 `specs/ADDENDUM.md` v1 原文（m2/m7 无 ADDENDUM 依赖不引），其落盘后
   须按 01 v2 §6 重算 spec_hash 并再登记（tests/CHANGELOG.md 2026-09-29 M4 节已注记）。
