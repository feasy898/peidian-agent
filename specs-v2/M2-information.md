# M2 · Information（信息层）Spec v2 + Eval

> 职责一句话：回答"模型此刻应当看见什么"，并管理任务事实、事件流与产物的持久化。
> 上游依赖：M7（Skill/Prompt 资产，经 `SkillRegistry` 注入披露面）；被 M1/M3/M6 调用
> （M6 CaseRunner 的任务生命周期同样经 `InformationLayer`）。持有 runtime 全部持久状态。
>
> **v2 重生成说明（资产工程阶段）**：本文件由 v1（`specs/M2-information.md`）按
> **oracle（唯一事实源）** 重生成——oracle = 现行实现全体（M2 侧 = `src/m2_information/` 全部
> 14 个文件 + `src/contracts/` 相关结构 + `tests/test_m2.yaml` 23 用例；v2 EVAL 已按本文件
> 条款整体重生成为 27 条，见 §4 与 `tests/CHANGELOG.md` 2026-09-29 节）。
> 每条 SPEC 给出**行为陈述 + oracle 证据（文件:行）**；与 v1 的差异以行内标记
> `[v2Δ: 偏差依据 evidence]` 标注，未标记部分与 v1 语义一致。
> oracle 健康复核（本会话实跑，2026-09-29）：`python run_evals.py --module m2` →
> `EVALS mode=m2 isolation=OK modules=1/1 pending=0 cases=23/23 failed=0 skipped=0 result=PASS`。

## 0. v1→v2 条款映射（重排对照）

| v1 条款 | v2 条款 | 说明 |
| --- | --- | --- |
| SPEC-M2-01 确定性编译 | **SPEC-M2-01** | 并入 D-23：hash 输入机械口径成文 |
| SPEC-M2-02 分层结构 | **SPEC-M2-02** | 补层序排序/冲突记录/权限过滤/身份缺省口径 |
| SPEC-M2-03 预算裁剪 | **SPEC-M2-03** | 并入 D-19：policy 永不裁负向口径代码级成文；补 token 计量口径 |
| SPEC-M2-04 Manifest 完整 | **SPEC-M2-04** | 并入 D-17：source 五字段封闭集 + 裁剪记录双落 |
| SPEC-M2-05 压缩四步 | **SPEC-M2-05** | 补五要素提取规则/空要素占位/回滚语义 |
| SPEC-M2-06 Checkpoint 恢复 | **SPEC-M2-06** | 补恢复迁移校验/恢复事件/事件重建协议细则 |
| （v1 无条款，01§3.2 语义） | **SPEC-M2-07**（新增） | 吸收 D-18/D-06②③：状态提交与事件溯源 |
| （v1 §2/§5 DoD，无条款） | **SPEC-M2-08**（新增） | 吸收 D-22：持久层形态与会话三级 |
| SPEC-M2-07 Workspace 隔离 | **SPEC-M2-09** | 补路径纪律/审计事件主题（D-06③） |
| SPEC-M2-08 Artifact 状态机 | **SPEC-M2-10** | 吸收 D-68：report.daily@v1 四段 + 规则 ID 存在性；补替代链/未注册 schema 拒绝 |
| SPEC-M2-09 产物即证据 | **SPEC-M2-11** | 补两种封装形态（FORMATS.md §3.3） |
| SPEC-M2-10 写入六问 | **SPEC-M2-12** | 吸收 D-20：哨兵字符串 `"REJECTED"`；补冲突检查/注册通道 |
| SPEC-M2-11 记忆分类 | **SPEC-M2-13** | 补续期阈值=3/检索过滤口径 |
| SPEC-M2-12 渐进披露 | **SPEC-M2-14** | 吸收 D-21：可见状态缺省仅 PUBLISHED/词数口径/域匹配交集 |

> 系统级偏差 D-06（事件目录"就近落主题"扩展通道族）的 M2 落地部分（②非状态字段提交、
> ③跨域审计）分别并入 SPEC-M2-07 / SPEC-M2-09 / SPEC-M2-12，不设独立条款；
> 条款全文见 01 v2 §4。

## 1. 职责边界

**做**：Context 八步确定性编译管线与 ContextManifest（hash 确定性口径）；System Context 六层 + Task Context 七源分层与冲突消解；预算裁剪（policy 永不裁，负向拒绝）；上下文压缩四步（五要素）；TaskState 权威持有（乐观锁 + 事件溯源重建，`runtime/events/*.jsonl` 追加写按流分片）；Checkpoint 快照/恢复；Workspace 六目录与跨任务隔离（含审计事件）；Artifact 状态机与 schema 校验钩子（内置 `report.daily@v1` 四段 + 规则 ID 存在性联动）；evidence/ 门禁；四类 Memory + 写入六问 + Knowledge 只读；Skill 渐进披露（三级）。
**不做**：模型调用（M1 `model_client`）；动作执行/准入/审批（M3）；语义归一化与实体解析（M4）；环境仿真与电价判定（M5——M2 无电价语义，源码零电价标记词，CI 墙钟扫描口径）；`tools/` 16 个动作适配器属 M3，M2 不持有。

## 2. 内部组件（按 oracle 实际目录树）

```text
m2_information/
├── __init__.py          # InformationLayer 门面：01§3.2 冻结接口 + 任务生命周期/证据门/跨任务读写
├── context_builder.py   # 八步管线：读状态→身份解析→收集源→权限过滤→排序→预算裁剪→压缩→编译+Manifest
├── compactor.py         # 压缩四步：Commit(五要素确定性提取落盘)→Compact→Rebuild→Validate(失败回滚)
├── state_store.py       # SQLite 七表（task_state/artifacts/memory/checkpoints + 超集 knowledge/sessions/calls）；
│                        #   TASK_TRANSITIONS（01§5.1 机械转写）/ apply_state_mutation（单一变更语义）
├── event_log.py         # events/*.jsonl 追加写（按 stream 分片，缺省 task-<task_id>）+ rebuild_task_state
├── session.py           # Call ⊂ Session ⊂ Task 三级管理（持久化 sessions/calls 表）
├── workspace.py         # 每任务六目录 + 路径纪律 + 跨任务隔离（拒绝落审计事件）
├── artifact.py          # Artifact 状态机（01§5.3）+ schema 校验钩子（report.daily@v1）
├── memory.py            # 四类 Memory + 写入六问 + KnowledgeBase（只读/评审通道）
├── skill_disclosure.py  # 三级披露（可见状态/词数上限/能力域交集）
├── ids.py               # ULID（标准库实现；仅用于 id 生成，不进任何确定性 hash）
├── timestamps.py        # UTC ISO-8601 唯一真实时钟位（全部入口支持 now 注入）
├── eval_plugin.py       # EVAL 执行器插件（EXECUTORS 22 个，服务 tests/test_m2.yaml 23 用例）
└── FORMATS.md           # 存储格式文档（运行期布局/六目录/五要素/evidence/SQLite 表/事件语义）
```

[v2Δ: v1 §2 组件树缺 `__init__.py`（门面）、`ids.py`、`timestamps.py`、`eval_plugin.py` 四件，
`state_store.py` 行实为**七表**（四表+三超集表，D-22），`event_log.py` 补"按流分片+重建"职责；
组件职责按 oracle 实况修订]

## 3. 行为规格（SPEC 条款 v2）

### Context 构建

- **SPEC-M2-01 确定性编译与 hash 口径**：同 TaskState 版本 + 同 turn + 同源内容/同资产版本
  → `ContextManifest.hash` 必须一致（纯函数，无时钟泄漏）。hash 输入机械口径 =
  `sha256(规范 JSON{task_id, turn, version, sources 五元组列表, total_tokens})`
  （`sort_keys`、紧凑分隔符、`ensure_ascii=False`）；`compiled_at`（时钟）与 ULID 随机量**不进 hash**。
  System 层源 origin 携带文本内容 sha256 前 8 位；Skill 层 level0 源 origin 携带
  `skills/level0@<version_fingerprint>`（= sorted(`skill_id@version`)），level2 源 origin 为
  `skills/<skill_id>@<version>` → 资产版本变化必然翻转 hash。ULID 仅用于 id 生成。
  证据：`src/m2_information/context_builder.py:594-611`（compute_hash）、`:488-496`（system origin）、
  `:507,513`（skill origin）、`src/m2_information/skill_disclosure.py:117-122`（version_fingerprint）、
  `:180`；`src/m2_information/ids.py:1-25`；执行器 `src/m2_information/eval_plugin.py:110-169`。
  [v2Δ D-23: v1 只写"同状态同轮 hash 一致（纯函数，无时钟泄漏）"；oracle 将 hash 输入成文为
  核心五元组并排除 compiled_at/随机量（`src/m2_information/context_builder.py:594-611`）；
  tests/CHANGELOG.md M2 登记 9]

- **SPEC-M2-02 分层结构**：System Context 严格六层封闭集
  `SYSTEM_LAYER_ORDER` = SYSTEM_POLICY/AGENT_CONTRACT/TENANT_RULE/RUNTIME_REMINDER/SKILL/TOOL_DESCRIPTOR；
  Task Context 七源封闭集 `TASK_SOURCE_ORDER` = GOAL_STEERING/PLAN_TODO/RECENT_INTERACTION/
  COMPACTED_HISTORY/RETRIEVED_MEMORY/RETRIEVED_KNOWLEDGE/ONTOLOGY_VIEW；合计 14 值
  （`contracts.SourceType` 封闭枚举，越界拒绝）。源排序：system 组(0)→task 组(1)→注入源组(2，
  如 WORKSPACE_REF)，组内按声明层序、再按 name。冲突消解：`directives` 按排序后先到先得，
  前者（更早层）覆盖后者，被覆盖取值记入 `conflicts {key, kept, dropped, loser}`。
  权限过滤（步骤 4）：源声明 `requires {tenant/role/visibility}` 不满足身份时滤除并记 `filter_log`。
  身份解析（步骤 2）缺省值：agent=`agent@default`、role=`OPERATOR`、tenant=`tenant-default`
  （编译入参 `actor/tenant_id` 可覆盖）。各层缺省文案/指令可经 `system_texts` 覆盖；
  RUNTIME_REMINDER 层缺省携带任务状态/阶段/预算余量。
  证据：`src/m2_information/context_builder.py:45-56`（层序）、`:376-389`（排序）、`:460-469`（冲突）、
  `:353-373`（权限过滤）、`:249-259`（身份缺省）、`:90-107,271-278,488-496`（缺省文案/指令）；
  `src/contracts/enums.py:166-182`；`src/contracts/core.py:362-380`（source 校验）。
  [v2Δ: v1 只写"冲突按层序前者覆盖后者"；oracle 补机械排序/冲突记录/权限过滤/身份缺省——
  身份缺省为构造入参可覆盖的缺省值，无行为锁定（同 M1 D-16 处置口径显式成文）；
  100 轮层序恒定由 EVAL-M2-02-P 断言（`src/m2_information/eval_plugin.py:175-229`）]

- **SPEC-M2-03 预算裁剪（policy 永不裁）**：预算取值=显式 `token_budget` 优先，否则
  `TaskState.budget.token_max - token_used`。token 计量口径：`estimate_tokens` = CJK 字符
  1 token/字 + ASCII 连串词元 1 token/串（确定性估算，无模型调用）。裁剪按 `DEFAULT_PRIORITY`
  从低到高逐源处理：COMPACTED_HISTORY 优先"压缩"（tokens 减半至下限 4，不可再压后丢弃）；
  其余源丢弃（tokens=0）；未登记类型缺省优先级 25。
  **负向口径（policy 永不裁）**：`NEVER_TRIM_TYPES={SYSTEM_POLICY}`；仅剩 policy 层仍超预算时
  **拒绝编译**（`trim_log` 记 `refused`，不产出超额 Manifest）→ 落
  `budget.exhausted {kind: token, budget, policy_tokens}` → `commit_state` 请求 RUNNING→PAUSED
  （非 RUNNING 态非法迁移时保留原状态）→ 抛 `ContextBudgetExceededError`（携带
  policy_tokens/budget 属性）。压缩步（步骤 7）：COMPACTED_HISTORY 在场时 RECENT_INTERACTION
  收缩为压缩点之后的增量（`[turn=N]` 行过滤；被完全替代则 tokens=0 + origin 注记
  `;trimmed=superseded_by_compact@turn=<N>`）。
  证据：`src/m2_information/context_builder.py:392-395`（预算）、`:110-116`（计量）、
  `:68-84`（优先级/NEVER_TRIM）、`:397-435`（裁剪+refused）、`:614-636`（budget.exhausted+PAUSED+异常）、
  `:438-453`（压缩步）；`src/m2_information/state_store.py:44-58`（RUNNING→PAUSED 合法迁移）。
  [v2Δ D-19: v1 仅在 EVAL-M2-03-N 期望中隐含"policy 永不压→触发预算 PAUSED"；oracle 代码级强制
  拒绝编译+budget.exhausted+PAUSED+异常，不产出超额 Manifest
  （`src/m2_information/context_builder.py:397-435,614-636`）；tests/CHANGELOG.md M2 登记 4]
  [v2Δ: v1 未写 token 计量口径——`estimate_tokens` CJK 每字 1+ASCII 每串 1
  （`context_builder.py:110-116`；与 M4 D-36 同构口径）；"compacted_history 优先压"落为
  tokens 减半至下限 4 的机械口径（`:422-428`）]

- **SPEC-M2-04 Manifest 完整与裁剪双落**：Manifest 七字段（task_id/turn/sources/total_tokens/
  budget_remaining/compiled_at/hash）封闭校验；source 五字段（name/type/tokens/priority/origin）
  为**封闭集**（`check_keys` 拒未知字段，含拼写漂移）；`priority` 契约未约束类型（oracle 用数值）。
  不变量：`total_tokens == Σ sources.tokens`；`budget_remaining == 预算 - total_tokens`；
  Manifest round-trip（`to_dict`/`from_dict`）hash 不变。
  **裁剪记录双落**：被裁源在 Manifest 内 `tokens=0` 留存 + `origin` 追加
  `;trimmed=dropped@priority=<P>`（压缩替代注记见 SPEC-M2-03）；完整
  `trim_log/filter_log/conflicts/directives` 落 `workspace manifest/turn-<n>.json` 编译记录
  （FORMATS.md §3.4）。编译持久化缺省开启（`persist=True`），并把 hash 经
  `commit_state` 提交进 `TaskState.context_manifest_hash`（该提交本身为 from==to 的
  非状态字段事件，见 SPEC-M2-07）。
  证据：`src/contracts/core.py:384-422`（Manifest）、`:362-380`（ContextSource 五字段）；
  `src/m2_information/context_builder.py:456-485`（编译）、`:430-434`（origin 注记）；
  `src/m2_information/__init__.py:247-270`（持久化+hash 提交）；`src/m2_information/eval_plugin.py:1036-1077`；
  `src/m2_information/FORMATS.md:90-104`（§3.4）。
  [v2Δ D-17: v1 只写"裁剪必须留 Manifest 记录"；ContextManifest 契约字段封闭无法加字段——
  oracle 以 origin 注记 + 编译记录文件**双落**（`context_builder.py:430-434`；
  `__init__.py:252-264`；FORMATS.md §3.4）；tests/CHANGELOG.md M2 登记 1]

### 压缩与恢复

- **SPEC-M2-05 压缩四步**：Commit → Compact → Rebuild → Validate。五要素
  `FIVE_ELEMENTS` = goal / confirmed_facts / external_side_effects / acceptance_gaps /
  recovery_position。Commit 为**确定性提取**（无模型调用）：goal=task.created.payload.user_input；
  confirmed_facts=action.completed(SUCCEEDED) 的 capability→observation；
  external_side_effects=result_refs ∪ READY/PUBLISHED/ARCHIVED 产物；
  acceptance_gaps=plan.artifacts_expected 未产出（按 schema_id 比对）∪ 未完成 todos；
  recovery_position={stage, turn, version, status, next_hint}；空要素以占位句落盘
  （要素"在场"与"取值为空"两回事，Validate 只认在场性），落 `state/compact-<turn>.yaml`。
  Compact 产出摘要落 `state/compacted-<turn>.yaml`（elements + context_text + tokens）；
  Rebuild 产出五要素分节文本；Validate 校验五要素在场（含 context_text 分节标题），
  缺任一抛 `CompactValidationError`。**失败回滚**：删除本次 Commit 产物、压缩产物不写出、
  任务状态与版本不变（流程未提交任何 mutation）；成功才经 `commit_fn` 提交
  （compact_ref/note，version+1）。摘要器可注入（`summarizer`），缺省确定性摘要器五要素原样保留。
  证据：`src/m2_information/compactor.py:31-34`（五要素）、`:73-129`（extract_commit）、
  `:116-120`（占位句）、`:140-189`（compact+回滚）、`:192-210`（rebuild）、`:213-237`（validate）、
  `:240-258`（load_compacted）、`:261-263`（缺省摘要器）。
  [v2Δ: v1 只写四步名与五要素名；oracle 补五要素确定性提取规则、空要素占位句口径与
  回滚语义（`compactor.py:73-129,160-170`）——v1 未写 Commit 提取规则]

- **SPEC-M2-06 Checkpoint 恢复与事件重建**：Checkpoint 载荷 =
  {checkpoint_id, task_id, created_at, state(TaskState 全量 dict), workspace_manifest(六目录
  文件清单 + 逐文件 sha256 + file_count)}，落 checkpoints 表 + `state/checkpoint-<id>.json` 双写。
  restore：迁移合法性校验（当前状态→快照状态不在 01§5.1 表则拒绝并落拒绝事件后抛
  `IllegalTransitionError`）；版本 = current.version+1 乐观锁提交（恢复必产生新版本）；
  落 `task.status_changed {accepted:true, restored_from, state:恢复后全量}`。
  **事件重建协议（DoD）**：`task.created` 的 payload.state 为初始全量 → `task.status_changed`
  （`accepted != false`）逐条折叠（payload.state 快照整量替换 / payload.mutation 按
  `apply_state_mutation` 应用 / to/version/updated_at 覆盖）→ `contracts.TaskState.from_dict`
  终校验；空流抛 `TaskStateNotFoundError`；重建不依赖 SQLite，与库内快照 diff 为空。
  证据：`src/m2_information/__init__.py:276-291`（snapshot）、`:293-339`（restore）；
  `src/m2_information/workspace.py:140-154`（manifest_snapshot）；
  `src/m2_information/event_log.py:20-32`（协议 docstring）、`:119-149`（rebuild_task_state）。
  [v2Δ: v1 只写"Checkpoint 含 TaskState 全量+Workspace manifest 快照；恢复后 M1 可续跑"；
  oracle 补恢复迁移校验+恢复事件+版本单调递增（`__init__.py:293-339`）与重建协议机械细则
  （`event_log.py:119-149`；协议入 01 v2 §4 事件溯源规则）]

### 状态与持久化

- **SPEC-M2-07 状态提交与事件溯源**（新增条款）：`commit_state` 为任务状态唯一变更入口——
  mutation 按 `apply_state_mutation` 应用（**单一变更语义**，commit 与事件重建共用）：
  字段级变更键 `FIELD_MUTATION_KEYS`（status/current_stage/plan/todos/budget/artifacts_add/
  artifacts_remove/evidence_refs_add/context_manifest_hash/subtasks/subtasks_add）+ 元键
  `META_MUTATION_KEYS`（compact_ref/note/restored_from/trace_id）；budget 支持整量替换、
  `*_delta` 增量与 `clear_deadline`；列表增删去重；未登记键抛 `MutationError`（防拼写漂移
  静默丢失）。版本乐观锁：`put_task(expected_version)` 不符抛 `OptimisticLockError`，
  提交成功 version+1。事件落流：非法迁移（`transition_allowed=False`，01§5.1 表）→ 落
  `task.status_changed {accepted:false, reason}` 拒绝事件并抛 `IllegalTransitionError`；
  合法 → 落 `{from, to, accepted:true, mutation, version, updated_at}`。
  **非状态字段提交**（todos/plan/budget/context_manifest_hash 等）落
  `task.status_changed {from==to}`（事件目录无 task.updated 主题——就近落主题，D-06②）；
  事件重建按同一 `apply_state_mutation` 折叠。事件流基础设施：`runtime/events/<stream>.jsonl`
  追加写按流分片（缺省 `task-<task_id>`，流名净化）；每条经 `contracts.EventRecord` 校验，
  缺 trace_id/枚举越界写入即拒（`EventAppendError`）。
  证据：`src/m2_information/state_store.py:44-58`（TASK_TRANSITIONS）、`:61-62`（transition_allowed）、
  `:65-76`（IllegalTransitionError）、`:100-160`（apply_state_mutation）、`:277-296`（乐观锁）；
  `src/m2_information/__init__.py:198-244`（commit_state）；
  `src/m2_information/event_log.py:50-78`（append/分片/校验）。
  [v2Δ D-18/D-06: v1 无对应行为条款；oracle 非状态字段提交落 `task.status_changed{from==to}`
  并按同一 `apply_state_mutation` 折叠、非法迁移拒绝事件 `accepted=false` 重建时跳过
  （`src/m2_information/state_store.py:114-160`；`event_log.py:129-130`）；
  tests/CHANGELOG.md M2 登记 2——01 v2 §4 扩展通道 2]

- **SPEC-M2-08 持久层形态与会话三级**（新增条款）：StateStore=SQLite，schema 共**七表**——
  规格四表 task_state/artifacts/memory/checkpoints + 超集三表 knowledge/sessions/calls
  （超集不违反规格最小集）。DSN 可配：`sqlite:///<path>` 或裸路径 → SQLite；`postgres*` 抛
  `NotImplementedError`（PostgreSQL 迁移位**预留不实现**的落地形态）。每次操作独立连接；
  artifact 按 artifact_id INSERT OR REPLACE。
  会话三级：Call ⊂ Session ⊂ Task——SessionManager 提供 open_session/end_session/
  begin_call/end_call/lineage（Call 绑定 turn 与当轮 ContextManifest hash，供 M6 轨迹采集），
  持久化 sessions/calls 表。
  时钟纪律：m2_information 内唯一真实时钟位 = `timestamps.utc_now_iso`（及 ids 的毫秒
  时间戳成分），全部入口支持 `now` 注入保证 EVAL 离线确定性复跑；源码零电价语义字样
  （CI 墙钟扫描口径）。
  证据：`src/m2_information/state_store.py:163-222`（_SCHEMA 七表）、`:228-242`（DSN/NotImplementedError）；
  `src/m2_information/session.py:73-152`；`src/m2_information/timestamps.py:1-22`；`src/m2_information/ids.py:1-25`。
  [v2Δ D-22: v1 §2 组件表只写四表、DoD 写"SQLite→PostgreSQL 迁移位预留"；oracle 实为四表 +
  knowledge/sessions/calls 超集，`StateStore(dsn)` 连接串可配、`postgres*` 抛 NotImplementedError
  即"预留不实现"的落地形态（`src/m2_information/state_store.py:163-242`）；
  tests/CHANGELOG.md M2 登记 7/8]
  [v2Δ: 时钟纪律成文（tests/CHANGELOG.md M2 登记 10，表外登记口径）]

### Workspace 与 Artifact

- **SPEC-M2-09 Workspace 隔离**：每任务六目录封闭集 inputs/ scratch/ state/ artifacts/
  evidence/ manifest/；目录名净化 `[^A-Za-z0-9._-]→_`，原始 id 存 `.workspace.json`。
  路径纪律：相对路径，拒绝绝对路径/盘符/`..` 越界/空段，顶层必须落六目录之一，
  禁 `.git`/`__pycache__` 目录段。跨任务**读**：仅 `artifacts/`（产物状态 READY/PUBLISHED，
  按 ArtifactRecord.content_ref 判定）与 `evidence/`（只读环境事实），其余目录拒绝。
  跨任务**写**：一律拒绝（即便路径类别属只读可读）并落审计事件
  `action.policy_decided {decision: DENY, capability: workspace.write_cross, …}`（producer=M2，
  就近落主题——事件目录无独立安全主题，D-06③）。
  证据：`src/m2_information/workspace.py:31`（六目录）、`:33,56-67`（净化/登记）、`:70-88`（路径纪律）、
  `:180-220`（跨任务读判定）、`:185-199`（写拒绝）、`:222-238`（审计事件）；
  `src/m2_information/__init__.py:426-436`（门面入口）。
  [v2Δ D-06: v1 只写"拒绝+审计事件"未指定主题；oracle 落 `action.policy_decided DENY`
  （`workspace.py:222-238`）；tests/CHANGELOG.md M2 登记 3——01 v2 §4 扩展通道 3]

- **SPEC-M2-10 Artifact 状态机与 schema 钩子**：迁移严格按 01§5.3 冻结表
  （`ARTIFACT_TRANSITIONS`，与 `tests/fixtures/frozen_state_machines.yaml` diff 为空，
  EVAL-M2-08-P2 断言）；每次迁移落 `artifact.state_changed {from, to, task_id, schema_id,
  version}`（创建为 NONE→DRAFT），事件序可回放。VALIDATING 步自动执行 schema 校验：
  通过→READY、不通过→自动落 REJECTED（`validation.checks` 带逐项 name/passed/detail）；
  迁往 READY/PUBLISHED 的前置门禁：`validation.passed == true`，否则 `ArtifactValidationError`。
  `save_artifact` 仅接受 DRAFT 新建；`publish_new_version` 替代链（仅 PUBLISHED 可被替代：
  新记录 supersedes 旧 id、version+1，旧记录 PUBLISHED→ARCHIVED）；`soft_delete` 软删留记录。
  schema 钩子：`register_schema(schema_id, fn)` 注册表（同 id 覆盖=升级），统一签名
  `fn(content, ctx) -> {"passed": bool, "checks": [...]}`；**未注册 schema_id 校验即失败**
  （不可 PUBLISH）。内置 `report.daily@v1` 四段校验：devices（非空列表）/ measurements
  （非空且逐条含 points 时序趋势点列，每点含 ts/value）/ conclusion（非空）/
  regulation_refs（非空规则 ID 字符串列表）；**规则 ID 存在性**经 `ctx["rule_id_checker"]`
  联动（`m4_semantic.regulation.rule_id_checker()` 工厂注入全部 InformationLayer 构造点；
  钩子缺省时仅校验形态）。
  证据：`src/m2_information/artifact.py:44-52`（迁移表）、`:55,70-76`（注册表）、`:83-146`
  （report_daily_v1 + 注册）、`:170-202`（create）、`:205-240`（transition+自动 REJECTED+门禁）、
  `:242-265`（替代链/软删）、`:268-278`（未注册拒绝）、`:322-340`（事件）；
  `src/m2_information/__init__.py:353-379`（save_artifact DRAFT-only/validate_artifact）、`:102-131`
  （rule_id_checker 注入位）；`src/m4_semantic/regulation.py:146-156`；执行器
  `src/m2_information/eval_plugin.py:630-727`。
  [v2Δ D-68: v1 SPEC-M2-08 只写"PUBLISH 必须过 schema 校验（validation.passed=true）"；
  oracle 四段 schema + 规则 ID 存在性校验落 `artifact.report_daily_v1`，钩子经独立评审修复
  接线到全部 InformationLayer 构造点（EVAL-M2-08-N2：引用 PHYS-BOGUS-999→REJECTED 钉死）
  （`src/m2_information/artifact.py:83-146`；`src/m4_semantic/regulation.py:146-156`）；
  tests/CHANGELOG.md 独立评审缺口修复 2——ADDENDUM §B 落地核对 D-68]
  [v2Δ: 补 VALIDATING 自动校验分支/READY-PUBLISHED 前置门禁/替代链/soft_delete/
  未注册 schema 拒绝——v1 未写机械口径]

- **SPEC-M2-11 证据门（产物即证据）**：`evidence/` 只接受两种封装，其余
  （模型生成文本、无证据结构的伪内容）抛 `EvidenceRejectedError`：
  ① 三态证据 `{"kind": "action_evidence", "action_id"?, "evidence": {intended[, issued][, observed]}}`
  —— 经 `contracts.Evidence` 契约校验（两种键位形态均接受）；
  ② 只读读数快照 `{"kind": "measurement_snapshot", "points": [{device_ref, quantity, value, ts, …}]}`
  （dict 单点或 list 多点）。
  文件名净化（`_safe_name`：非法字符→`_`）；落盘为 `evidence/<name>.json`。
  证据：`src/m2_information/__init__.py:382-419`（save_evidence + _normalize_evidence）、
  `:452-456`（_safe_name）；`src/m2_information/FORMATS.md:75-88`（§3.3）；
  `src/contracts/core.py:139-154`（Evidence 契约）；执行器 `src/m2_information/eval_plugin.py:733-778`。
  [v2Δ: v1"不接受模型生成文本"落为**白名单封装 + Evidence 契约校验**（`__init__.py:397-419`）；
  封装形态成文于 FORMATS.md §3.3（v1 未写）]

### Memory

- **SPEC-M2-12 写入六问与 Knowledge 只读**：`write_memory` 必须通过六问（顺序即校验顺序）：
  what（content 需含非空 subject+claim）/ why_now（provenance.why_now 非空）/ timeliness
  （provenance.ttl_days 或 valid_until；WORKING 随任务归档豁免）/ provenance（source 与
  trace_id 必填）/ verification（∈ VERIFIED/UNVERIFIED/SPECULATIVE）/ conflict（与既有同主题
  记忆的处置）。未过任一问 → **返回字面量哨兵字符串 `"REJECTED"`（不抛错）**，最近拒绝原因
  `{question, reason, task_id}` 存 `MemoryStore.last_rejection` 供审计；SPECULATIVE 直接拒绝
  且归因 verification 问。冲突检查机械口径：同主题同断言=幂等不冲突；未验证新条目与
  VERIFIED 旧条目矛盾=拒绝；VERIFIED 新条目替代旧条目（旧条目置 superseded_by）。
  Knowledge 类条目 agent 只读：注册走 M7 评审通道（`review.reviewer`/`review.review_ref`
  必填，缺失抛 `KnowledgeReadOnlyError`）；`mutate` 一律拒绝 + 审计事件
  `action.policy_decided {decision: DENY, capability: knowledge.mutate}`（producer=M2，D-06③）。
  证据：`src/m2_information/memory.py:40`（REJECTED 哨兵）、`:43-54`（六问/常量）、`:88-89`
  （last_rejection）、`:92-146`（write/逐问校验）、`:121-123`（SPECULATIVE）、`:235-254`
  （冲突扫描）、`:278-284`（_reject/_SilentReject）；`:287-374`（KnowledgeBase）。
  [v2Δ D-20: v1 §3.2 写 `MemoryId | REJECTED` 联合类型语义；oracle 落为哨兵字符串
  `"REJECTED"`（不抛错），拒绝原因存 `last_rejection`（`src/m2_information/memory.py:40,97,279`）；
  tests/CHANGELOG.md M2 登记 5]
  [v2Δ D-06: Knowledge 拒绝审计落 `action.policy_decided DENY`（`memory.py:361-373`）；
  tests/CHANGELOG.md M2 登记 3]
  [v2Δ: 冲突检查机械口径与注册评审必填——v1 未写]

- **SPEC-M2-13 记忆分类与 TTL**：四类隔离存储 WORKING/EPISODIC/SEMANTIC/PROCEDURAL
  （`MemoryType` 封闭集；越界类型按 what 问拒绝）。TTL：EPISODIC/SEMANTIC/PROCEDURAL 缺省
  90 天（`DEFAULT_TTL_DAYS`）；显式 `valid_until` / `ttl_days` 优先；WORKING 无 TTL（valid_until
  空串=永不过期，随任务归档清理）。检索：TTL 过期/归档/被替代（superseded_by）条目不返回；
  词法确定性匹配（大小写不敏感分词命中）；`expired_report` 输出过期计数与 id 清单。
  续期：引用计数 **> 3**（`RENEWAL_REF_THRESHOLD`，严格大于）才允许，否则
  `MemoryRenewalRejectedError`；引用计数经 `reference()` 在检索命中并实际使用时累加。
  WORKING 归档：`archive_task(task_id)` 置 archived=1（检索不可见）。
  证据：`src/m2_information/memory.py:52-55`（常量）、`:100-101`（类型越界）、`:149-173`
  （retrieve/expired_report）、`:181-211`（reference/renew/archive_task）、`:221-233`（TTL 解析）、
  `:256-262`（匹配）；`src/contracts/enums.py:135-139`；执行器 `src/m2_information/eval_plugin.py:900-955`。
  [v2Δ: v1 写"默认 90 天，续期需引用计数>阈值"未给阈值——oracle 阈值=3 成文
  （`memory.py:53,191`）；检索过滤（过期/归档/被替代）与 expired_report 口径成文]

### Skill 披露

- **SPEC-M2-14 渐进披露**：三级——level0 名称常驻 System Context（名册每 skill 一行
  `id: 名称`，每 skill ≤10 词）；level1 目录仅在任务能力域匹配时进入；level2 全文只在
  skill 被选中后加载并计入 token 预算。词数口径：CJK 每字 1 词 + ASCII 按空白分词
  （`count_words`）；level0 超限**注册即抛** `SkillDisclosureError`。**可见状态缺省仅
  PUBLISHED**（`visible_status=("PUBLISHED",)`）：DRAFT/REVIEW 未过 M7 发布门禁同样不入
  任何层（与 DEPRECATED 一致），`disclose` 对不可见状态抛 `SkillDisclosureError`，
  `SkillRegistry(visible_status=...)` 可调；未注册 skill 任何层不得出现（查询即抛）。
  能力域匹配=集合交集（`task_domains` 为编译入参 ∩ `skill.capability_domain`）。
  `version_fingerprint` = sorted(`skill_id@version`)（仅可见集）进 level0 origin → 资产版本
  变化翻转 hash（联动 SPEC-M2-01）。level2 文本解析：`level2_ref` 为文件名时读
  `level2_root`（InformationLayer root 下 skills_fulltext/）文件，否则原样作为文本。
  证据：`src/m2_information/skill_disclosure.py:31`（LEVEL0_MAX_WORDS）、`:35-41`（count_words）、
  `:65-80`（visible_status 缺省）、`:83-94`（注册强校验）、`:105-122`（未注册/可见集/指纹）、
  `:125-145`（level0/level1）、`:147-181`（level2/disclose）；`src/m2_information/context_builder.py:498-521`
  （三源注入）；`src/contracts/assets.py:42-119`（§2.7 Disclosure/SkillEntry/SkillDescriptor 契约）；
  执行器 `src/m2_information/eval_plugin.py:961-1030`。
  [v2Δ D-21: v1 SPEC-M2-12 仅明令"未注册/DEPRECATED skill 不出现在任何层"；oracle 可见状态
  缺省仅 PUBLISHED（DRAFT/REVIEW 同样不入层、可调）、level0 ≤10 词注册即强校验
  （CJK 每字 1 词、ASCII 按空白分词）、能力域匹配=集合交集
  （`src/m2_information/skill_disclosure.py:70-74,86-91,111-145`）；
  tests/CHANGELOG.md M2 登记 6]

## 4. Eval（`tests/test_m2.yaml`，v2 重生成 30 条）

> **v2 重生成（2026-09-29）**：suite 已按本文件 v2 条款整体替换——spec_ref 切换为
> `specs-v2/M2-information.md` + `specs-v2/00-ontology.md` + `specs-v2/01-contracts.md`
> （v1 spec_ref 中的 ADDENDUM §B 内容已折叠入 01 v2 §3.2 D-68 与本文件 SPEC-M2-10，
> v2 目录暂无 ADDENDUM 文件；spec_hash→eval_hash 登记见 `tests/CHANGELOG.md` 2026-09-29 节）。
> 执行器注册于 `src/m2_information/eval_plugin.py`（EXECUTORS 22 个，本阶段不改动）+
> `tests/m2_eval_extra.py`（tests 侧补充执行器 2 个，EVAL-SCHEMA §4 协议，零 oracle 改动）；
> EVAL-M2-02-N / 04-N / 07-N 使用 runner 内置执行器（`contract` / `negative_rejection` 形态）。
> **双向映射**：下表左列每条款 ≥1 用例；每条用例的 `spec:` 字段反向登记其条款
> （多条款用例以 `/` 连接）。

| v2 条款 | 正例 | 负例 | 覆盖要点（v2 口径） |
| --- | --- | --- | --- |
| SPEC-M2-01 | EVAL-M2-01-P | EVAL-M2-01-N | 同状态同轮 hash 恒定、skill 版本变更翻转；注入墙钟只落 compiled_at |
| SPEC-M2-02 | EVAL-M2-02-P | EVAL-M2-02-N | 100 轮层序恒定+冲突前者胜出；source type 14 值封闭集越界拒绝 |
| SPEC-M2-03 | EVAL-M2-03-P（兼 04） | EVAL-M2-03-N | 预算裁剪 policy 不动+trim_log/origin 留档；policy 被裁场景拒绝编译→budget.exhausted+PAUSED |
| SPEC-M2-04 | EVAL-M2-04-P | EVAL-M2-04-N | 五字段齐备/总账一致/round-trip；source 未知字段拒绝（封闭字段集） |
| SPEC-M2-05 | EVAL-M2-05-P | EVAL-M2-05-N | 五要素齐备落盘进 COMPACTED_HISTORY；丢要素 Validate 拒绝并回滚 |
| SPEC-M2-06 | EVAL-M2-06-P、EVAL-M2-07-P | —（非禁止类） | Checkpoint 全量快照/恢复可续跑；空库事件重建与快照 diff 为空（DoD） |
| SPEC-M2-07 | EVAL-M2-07-P、EVAL-M2-10-P2（兼 10） | EVAL-M2-07-N、EVAL-M2-07-N2 | apply_state_mutation 单一语义折叠重建；task/artifact 迁移表冻结基准 diff 空；缺 trace_id 事件写入即拒；put_task 乐观锁（过期基线拒绝且版本不被污染） |
| SPEC-M2-08 | EVAL-M2-06-P、EVAL-M2-07-P（StateStore 持久栈随行覆盖） | — | SQLite 持久形态随全生命周期用例覆盖；sessions/calls 表与 DSN NotImplementedError 分支无用例（执行器插件位于 src/，本阶段不改动——覆盖缺口如实登记，待 eval 插件扩展轮补齐） |
| SPEC-M2-09 | EVAL-M2-09-P | EVAL-M2-09-N、EVAL-M2-09-N2 | 跨任务只读规则（scratch 拒/DRAFT 不可读/PUBLISHED 只读）；跨任务写拒绝+审计事件（含通过 _check_cross 的 evidence/ 路径——兜底一律拒绝分支，plan-m2 m2-crosswrite-allow 守护） |
| SPEC-M2-10 | EVAL-M2-10-P、EVAL-M2-10-P2（兼 07） | EVAL-M2-10-N、EVAL-M2-10-N2 | 生命周期事件序回放；缺段 REJECTED+detail；规则 ID 存在性（D-68） |
| SPEC-M2-11 | EVAL-M2-11-P | EVAL-M2-11-N | 两种封装（三态证据/读数快照）接受；模型生成文本拒绝 |
| SPEC-M2-12 | EVAL-M2-12-P | EVAL-M2-12-N、EVAL-M2-12-N2、EVAL-M2-12-N3 | 六问写入+冲突检查；SPECULATIVE 归因 verification 拒绝；Knowledge 只读+审计；注册通道评审必填（缺 reviewer/review_ref 拒绝） |
| SPEC-M2-13 | EVAL-M2-13-P | —（过期不返回断言内嵌于 P） | TTL 过期检索不返回+计数入报告；WORKING 归档后不可检索 |
| SPEC-M2-14 | EVAL-M2-14-P | EVAL-M2-14-N | 三级披露/能力域交集匹配；DEPRECATED/REVIEW 全层不可见且披露被拒 |

> **v1→v2 用例 id 映射**（保留用例逐条核对断言与 v2 条款一致后重排；改名不改变判据数据）：
> EVAL-M2-01-P/N、02-P、03-P/N、04-P、05-P/N、06-P 同名保留；
> EVAL-M2-EVLOG-P→**EVAL-M2-07-P**（重建协议主条款改挂 SPEC-M2-07，兼 06/08）；
> EVAL-M2-07-P/N（workspace）→**EVAL-M2-09-P/N**；EVAL-M2-08-P→**EVAL-M2-10-P**；
> EVAL-M2-08-P2→**EVAL-M2-10-P2**（兼 07）；EVAL-M2-08-N→**EVAL-M2-10-N**；
> EVAL-M2-08-N2→**EVAL-M2-10-N2**；EVAL-M2-09-P/N（evidence）→**EVAL-M2-11-P/N**；
> EVAL-M2-10-P/N/N2（memory）→**EVAL-M2-12-P/N/N2**；EVAL-M2-11-P→**EVAL-M2-13-P**；
> EVAL-M2-12-P→**EVAL-M2-14-P**。
> 新增 7 条（v2 重生成 4 条 + 2026-09-29 变异测试缺口补齐 3 条）：EVAL-M2-02-N（type 封闭集）、
> EVAL-M2-04-N（source 封闭字段集）、EVAL-M2-07-N（事件缺 trace_id 写入即拒）、
> EVAL-M2-14-N（不可见状态不入层+披露拒绝）；补齐轮——EVAL-M2-07-N2（put_task 乐观锁，
> plan-m2 变异 m2-optimistic-lock-off 的守护）、EVAL-M2-12-N3（Knowledge 注册评审必填，
> plan-m2 变异 m2-knowledge-register-open 的守护）、EVAL-M2-09-N2（跨任务写兜底拒绝分支，
> plan-m2 变异 m2-crosswrite-allow 的守护）；执行器 tests/m2_eval_extra.py。

复核命令（仓库根，Python 3.12）：`python run_evals.py --module m2`
（本轮重生成后由统一门禁实跑；重生成会话仅做静态自检——YAML 可解析、执行器名存在、
fixtures 引用存在、spec_hash 声明值与重算一致，见 `tests/CHANGELOG.md` 登记。）

## 5. DoD

- EVAL 全绿（数据驱动）：`python run_evals.py --module m2` → 23/23 PASS（本会话实跑，
  2026-09-29；全套基线 `--module all` 180/180 PASS 见 specs-v2/README.md §1）。
- event_log 可从空库重建任意 TaskState，与库内快照 diff 为空（EVAL-M2-EVLOG-P）。
- SQLite → PostgreSQL 迁移位预留但本期不实现：`StateStore(dsn)` 连接串可配，
  `postgres*` 抛 NotImplementedError（SPEC-M2-08 的落地形态，非缺口）。
- task/artifact 迁移表与 `tests/fixtures/frozen_state_machines.yaml` diff 为空（EVAL-M2-08-P2）。

## 6. 交付物

- `src/m2_information/`（14 件，含 `FORMATS.md` 存储格式文档与 `eval_plugin.py` 执行器插件）。
- `tests/test_m2.yaml`（27 条数据驱动用例，2026-09-29 起按本文件 v2 条款整体重生成；
  spec_ref 指向 specs-v2 三件（00/01/M2），spec_hash→eval_hash 登记对见 `tests/CHANGELOG.md`
  2026-09-29 节；历史 22/23 条阶段的登记与"合计 22 条"旧头注说明留档同文件）。
- `tests/fixtures/frozen_state_machines.yaml`（task/artifact 迁移表冻结基准；S0 套件共用）。
