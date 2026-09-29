# specs-v2 · DEVIATIONS 初稿（v1 规格 + ADDENDUM ↔ oracle 全量偏差盘点）

> 生成：2026-09-29，偏差盘点员（资产工程阶段）。本文件为**初稿**，后续按 module 拆分到 `specs-v2/deviations/<模块>.md`。
>
> **oracle**（唯一事实源）= 现行实现全体：`src/`（m1_core..m7_registry、contracts）、`tools/`、`ontology/`、`regulations/`、`golden/dev/`、`scenarios/`、`releases/rel-0001/`、`scripts/`、`run_evals.py`。
> **v1 规格** = `specs/README.md`、`specs/00-ontology.md`、`specs/01-contracts.md`、`specs/M1..M7`、`specs/ADDENDUM.md`。
> **偏差线索权威源** = `tests/CHANGELOG.md` 全部 deviation/revision 条目 + git 全部模块 commit message（9a71dcc S0 → 400a5a2 M1 SSRF，共 16 commits）+ 本会话逐文件代码核对。
>
> **oracle 健康核验**（本会话实跑）：`python run_evals.py --module all` → `EVALS mode=all isolation=OK modules=8/8 pending=0 cases=180/180 failed=0 skipped=0 result=PASS`。
>
> **类型标注**：〔新增〕=v1 没写的行为；〔变义〕=v1 措辞已不符；〔强制〕=v1 只在 Eval 表/DoD 隐含、oracle 已代码级强制；〔缺陷〕=KNOWN-DEFECT（验收发现未修）；〔扩展〕=API/数据的向后兼容增补。
> **v2 处置取值**：吸收为条款-N ｜ KNOWN-DEFECT ｜ 显式排除（说明）。
>
> 表外补强 EVAL（EVAL-M*-…-P2/P2/N2/N3/PERF/SAFE*/APPR*/EVLOG/DEV 等）一律是 **eval 资产登记**，不构成规格条款缺口，不设独立偏差条目；其中改变行为口径的（如 EVAL-M2-08-N2 规则 ID 联动、EVAL-M5-SAFE*）已并入对应行为条目。

---

## S0 / 冻结契约层（01/00/README）

### D-01〔变义〕Action 生命周期 DENY 终态拼写：v1 写 `DENY→DENYED`，oracle 为 `DENIED`
- **evidence**：`src/contracts/enums.py:83`（DENIED）；`tests/CHANGELOG.md`（2026-09-28 S0 登记 1：01§5.2 原文系笔误，按 00§2 枚举落 `DENIED`）。
- **v2 处置**：吸收为条款——DENY 判定终态统一 `DENIED`（同时与 M5 simulate 拒绝终态、M3 gateway 一致）。

### D-02〔变义〕`FAILED→COMPENSATED` 实为条件迁移（reversible 且有 compensation），不进无条件迁移表
- **evidence**：`tests/CHANGELOG.md`（S0 登记 2）；`tests/fixtures/frozen_state_machines.yaml`（conditional_transitions 标注）。
- **v2 处置**：吸收为条款——状态机表区分无条件迁移与 conditional_transitions。

### D-03〔变义〕`EventRecord.event_id` 契约标注 `string(ulid)`，oracle 放宽为非空字符串并实际存在"流内序号"形态
- **evidence**：`src/contracts/base.py:164-166`（check_id＝非空字符串，注释"宽松以兼容既有编号体系"）；`src/m5_simulation/env.py:209`（`EVT-<run_id>-<seq:06d>`）；`tests/CHANGELOG.md`（M3 登记 9：`EVT-M3-<seq>`，journal 重放续序）。
- **v2 处置**：吸收为条款——event_id 接受 ULID 与流内序号两种形态（唯一性域=事件流）。

### D-04〔变义〕时间戳字段接受 UTC ISO-8601 字符串与 pyyaml UTC datetime 双形态；`ScenarioSpec.at` 为时间引用（非空字符串或 datetime）
- **evidence**：`src/contracts/base.py:126`（check_timestamp）；`tests/CHANGELOG.md`（S0 登记 4）。
- **v2 处置**：吸收为条款——数据文件未加引号时间戳的兼容口径；非 UTC 拒绝不变。

### D-05〔变义〕README §0 称"11 数据结构"，01§2 实定义 12 个（§2.1–§2.12，含 ReleaseBundle）
- **evidence**：`specs/README.md:11`；`specs/01-contracts.md` §2；`tests/CHANGELOG.md`（S0 登记 6，按 12 全部代码化）。
- **v2 处置**：吸收为条款——计数修正为 12。

### D-06〔新增·系统级〕事件目录封闭集下的"就近落主题"扩展通道族（v1 §4 无对应主题）
- **内容**：①`budget.warning{kind:token,remaining,cost{…}}` 兼作每轮模型成本上报（M1 SPEC-M1-10）；②非状态字段提交落 `task.status_changed{from==to}`+mutation/version/updated_at（M2）；③跨域审计落 `action.policy_decided{decision:DENY}`（M2 workspace.write_cross/knowledge.mutate、M3 准入拒绝 stage:admission）；④调优侧/评审侧审计落 `release.published{rejected:true}`、`release.published{stage:review,from,to}`（M6/M7）。
- **evidence**：`src/m1_core/loop.py:687-689`；`src/m2_information/state_store.py:114-125`；`src/m2_information/workspace.py:227`；`src/m3_action/gateway.py:268-275`；`src/m6_flywheel/evaluator.py:215-230`；`src/m7_registry/review.py`（评审迁移事件）；`tests/CHANGELOG.md`（M1 登记 2、M2 登记 2/3、M3 登记 1、M6 登记 4、M7 登记 2）。
- **v2 处置**：吸收为条款——把"冻结事件目录 + 就近主题 + payload 细分/rejected 标记"的扩展规则成文（或评估扩充事件目录）。

---

## M1 Agent Core

### D-07〔新增〕Loop 五阶段回放校验的数据源是 M1 审计件 `runtime/<root>/m1_core/loop/task-<id>.jsonl`（LoopTrace），不是 01§4 事件流
- 校验规则：每轮阶段序必须是 PREPARE→MODEL→ACT→OBSERVE→VERIFY 的前缀（仅 PREPARE=预算中断轮合法）。
- **evidence**：`src/m1_core/trace.py`；`src/m1_core/loop.py`（`_trace_of`）；`tests/CHANGELOG.md`（M1 登记 1）。
- **v2 处置**：吸收为条款——LoopTrace 审计件与事件流双轨的定位（权威状态仍在 M2）。

### D-08〔新增〕每轮成本上报以 `budget.warning{kind:token,remaining,cost{…}}` 兼作通道（事件目录无 model.*/cost 主题）
- **evidence**：`src/m1_core/loop.py:687-689`；`tests/CHANGELOG.md`（M1 登记 2）。
- **v2 处置**：吸收为条款（并入 D-06 的系统级条款，M1 侧引用）。

### D-09〔新增〕完成门禁落位：`TaskStateMachine.is_completable` 门禁 + `CompletionRequiredError`（IllegalTransitionError 子类）；拒绝事件同时携带 `rejected:true`（M1 口径）与 `accepted:false`（M2 重建跳过口径）
- **evidence**：`src/m1_core/state_machine.py:85-97`；`tests/CHANGELOG.md`（M1 登记 3）。
- **v2 处置**：吸收为条款——SPEC-M1-02/06 的双标记口径。

### D-10〔新增〕产物过门匹配双口径：`plan.artifacts_expected` 按 artifact_id 精确匹配**或** schema_id 匹配（计划先于产物存在，ULID 无法预知）
- **evidence**：`tests/CHANGELOG.md`（M1 登记 4）；`src/m1_core/gates.py`（GATE_PASS_STATUSES=("READY","PUBLISHED")）。
- **v2 处置**：吸收为条款。

### D-11〔新增〕write.report SUCCEEDED 后由数据驱动产物策略（`DEFAULT_ARTIFACT_POLICY`，构造可覆盖）自动落 M2 ArtifactRecord（DRAFT→VALIDATING→READY）；同 action_id 重复入账幂等跳过（复核修复项：首版缺失，实测同 key 重发产生 2 条 READY 后补 created_by.action_id 去重守卫）
- **evidence**：`src/m1_core/loop.py:84-90`；`tests/CHANGELOG.md`（M1 登记 5 + M1 复核修订 1；commit 588da80、9062518）。
- **v2 处置**：吸收为条款——产物自动落位策略与幂等入账。

### D-12〔新增〕预算耗尽判定口径：used ≥ max 即租约耗尽；deadline 判 `now > deadline`；price_window 判 `now ∉ [from,to]`；比较基准一律为注入的 now（m1_core 内唯一真实时钟读取位=`clocking.now_iso()`，budget.py/loop.py 零墙钟）
- **evidence**：`src/m1_core/budget.py:85-102`；`tests/CHANGELOG.md`（M1 登记 6）。
- **v2 处置**：吸收为条款。

### D-13〔新增〕ResumeEvent 状态-种类矩阵：PAUSED 接受任意种类但恢复前重查预算（仍超限→`LoopNotResumableError` 保持 PAUSED）；WAITING_INPUT→USER_INPUT、WAITING_APPROVAL→GRANTED/DENIED/TIMEOUT、WAITING_EVENT→ENV_EVENT、VERIFYING→USER_INPUT/ENV_EVENT/TIMEOUT，错配即拒
- **evidence**：`src/m1_core/loop.py:65-75,196-252`；`tests/CHANGELOG.md`（M1 登记 8）。
- **v2 处置**：吸收为条款——v1 01§3.1 只列种类未列状态匹配矩阵。

### D-14〔新增〕trace 轮次台账：轮号=LoopTrace 日志最大轮号+1（TaskState 冻结无轮次字段）；Checkpoint 恢复后轮号继续递增（任务语义续跑点由 plan 当前阶段+todos 决定）
- **evidence**：`src/m1_core/trace.py:83,122`；`tests/CHANGELOG.md`（M1 登记 9）。
- **v2 处置**：吸收为条款。

### D-15〔新增〕model_client SSRF 边界：`_assert_safe_endpoint()` 建连前 fail-closed（scheme 仅 https，明文须 `PD_MODEL_ALLOW_INSECURE_HTTP=1`；拒 URL 内嵌凭据；解析地址全公网，拒回环/私网/链路本地/云元数据/CGNAT/ULA；`PD_MODEL_ALLOW_PRIVATE_HOSTS` 精确主机白名单）；缺省传输由 urlopen 改写为 `http.client` 直连（错误语义保持：非 2xx 原样返回、超时→TimeoutError、网络错误→ConnectionError）
- v1 M1 §2 对 model_client 仅"provider 适配，超时/重试/成本上报"。
- **evidence**：`src/m1_core/model_client.py:106-168`；`tests/CHANGELOG.md`（2026-09-29 提交门禁安全修复）；commit 400a5a2。
- **v2 处置**：吸收为条款——模型端点安全边界（安全条款）。

### D-16〔新增·minor〕TaskContext 缺省 `actor_user="OP-001"`、`actor_agent="park-agent@v1"` 硬编码缺省值
- **evidence**：`src/m1_core/loop.py:100-101`。
- **v2 处置**：显式排除——构造入参可覆盖的缺省值，无行为锁定；v2 可将缺省值显式成文。

---

## M2 Information

### D-17〔新增〕ContextManifest source 五字段为封闭集（check_keys 拒未知字段）；裁剪记录"双落"：被裁源在 Manifest 内 `tokens=0` 留存 + `origin` 追加 `;trimmed=dropped@priority=<P>` 注记；完整 trim_log/filter_log/conflicts/directives 落 `workspace/manifest/turn-<n>.json`（FORMATS.md §3.4）
- **evidence**：`src/contracts/core.py:362-380`（ContextSource）；`src/m2_information/context_builder.py`；`tests/CHANGELOG.md`（M2 登记 1）。
- **v2 处置**：吸收为条款。

### D-18〔新增〕非状态字段（todos/plan/budget/context_manifest_hash 等）提交落 `task.status_changed{from==to}`+mutation/version/updated_at，事件重建按同一 `apply_state_mutation` 折叠（单一变更语义）；非法迁移拒绝事件 `accepted=false`，重建时跳过
- **evidence**：`src/m2_information/state_store.py:114-125`；`tests/CHANGELOG.md`（M2 登记 2）。
- **v2 处置**：吸收为条款（并入 D-06）。

### D-19〔强制〕policy 永不裁的负向口径：仅剩 SYSTEM_POLICY 层仍超预算→拒绝编译、`budget.exhausted{kind:token}` + RUNNING→PAUSED（合法迁移）、抛 `ContextBudgetExceededError`，不产出超额 Manifest
- v1 仅在 EVAL-M2-03-N 期望中隐含。
- **evidence**：`tests/CHANGELOG.md`（M2 登记 4）；`src/m2_information/context_builder.py`/`compactor.py`。
- **v2 处置**：吸收为条款。

### D-20〔变义〕write_memory 未过六问返回**字面量哨兵 `"REJECTED"`**（不抛错）；最近拒绝原因存 `MemoryStore.last_rejection`；SPECULATIVE 归因 verification 问
- v1 §3.2 写 `-> MemoryId | REJECTED`（联合类型语义），oracle 以字符串哨兵落地。
- **evidence**：`src/m2_information/memory.py:40,89,279`；`tests/CHANGELOG.md`（M2 登记 5）。
- **v2 处置**：吸收为条款——返回形态明确为哨兵字符串。

### D-21〔变义〕Skill 披露可见状态缺省仅 PUBLISHED（DRAFT/REVIEW 未过 M7 发布门禁同样不入层；`SkillRegistry(visible_status=...)` 可调）；level0 ≤10 词注册即强校验（CJK 每字 1 词、ASCII 按空白分词）；任务能力域与 skill 域匹配=集合交集（task_domains 为编译入参）
- v1 SPEC-M2-12 仅明令"未注册与 DEPRECATED 不出现在任何层"。
- **evidence**：`src/m2_information/skill_disclosure.py:70-74,111-114`；`tests/CHANGELOG.md`（M2 登记 6）。
- **v2 处置**：吸收为条款。

### D-22〔变义〕StateStore 表超集：规格四表（task_state/artifacts/memory/checkpoints）+ knowledge/sessions/calls 三表（Knowledge 只读条目与 Call⊂Session⊂Task 三级管理）；PostgreSQL 迁移位=`StateStore(dsn)` 连接串可配、`postgres*` 抛 NotImplementedError
- **evidence**：`src/m2_information/state_store.py:164-237`；`tests/CHANGELOG.md`（M2 登记 7/8）。
- **v2 处置**：吸收为条款——超集不违反最小集；NotImplementedError 为 DoD"预留不实现"的落地形态。

### D-23〔新增〕Manifest hash 确定性输入口径：sha256(规范 JSON{task_id, turn, version, sources 五元组, total_tokens})；`compiled_at` 与 ULID 随机量不进 hash；System 层源 origin 携带内容 hash、Skill 源 origin 携带 `skill_id@version` 指纹（资产版本变化必然翻转 hash）
- **evidence**：`tests/CHANGELOG.md`（M2 登记 9）；`src/m2_information/context_builder.py`。
- **v2 处置**：吸收为条款。

---

## M3 Action Gateway

### D-24〔新增〕准入失败不进生命周期：契约/注册/披露/schema/路由（REAL 被拒）失败发生在 01§5.2 REQUESTED 之前→状态 REJECTED、不落 `action.requested`（不进事件主链）、审计落 `action.policy_decided{decision:DENY, stage:admission}`
- **evidence**：`src/m3_action/gateway.py`（execute_action 准入管线）；`tests/CHANGELOG.md`（M3 登记 1）。
- **v2 处置**：吸收为条款。

### D-25〔变义〕不可改清单对 ASK 锁定动作（execute.remote_control）拒绝**一切**覆盖，含收紧 ASK→DENY；SPEC-M3-11 矩阵对 remote_control 期望缺省 ASK（WAITING_APPROVAL 零副作用成立）
- **evidence**：`src/m3_action/policy_engine.py:106-107,145-146`；`src/m3_action/registry.py:41-48`（IMMUTABLE_DENY_ACTIONS / PERMANENT_ASK_ACTIONS 双重表达）；`tests/CHANGELOG.md`（M3 登记 2）。
- **v2 处置**：吸收为条款——policy_locked 语义（与 EVAL-SCHEMA §2 参照一致）。

### D-26〔变义〕角色收紧基准=**当前生效判定**（已存覆盖优先于缺省）：已收紧为 ASK 的角色再请求 ALLOW（即使 ALLOW==缺省）属放宽，拒绝且维持 ASK；合法收紧方向=ALLOW→ASK / ALLOW→DENY / ASK→DENY
- **evidence**：`src/m3_action/policy_engine.py:29-31,154`；`tests/CHANGELOG.md`（M3 登记 3）。
- **v2 处置**：吸收为条款。

### D-27〔变义〕tools/ 布局与数据权威装配：16 个适配器一动作一模块（模块名=动作 ID 的 "."→"__"，v1 01§1 写"每个 action family 一个"）；pyproject 仅打包 src/，registry 兜底把仓库根加入 sys.path；参数 schema/幂等键策略/披露面来自适配器声明，风险/缺省 Policy 来自 `ontology/actions.yaml`（数据权威，装配即断言 diff 空）
- **evidence**：`tools/_base.py`；`src/m3_action/registry.py:276`；`tests/CHANGELOG.md`（M3 登记 4）。
- **v2 处置**：吸收为条款。

### D-28〔新增〕幂等与持久化形态族：幂等键两档策略（CALLER_PROVIDED / CALLER_PROVIDED_UNIQUE_ARGS——同 key 承载不同 (capability, arguments)→`KEY_CONFLICT` 拒绝不进主链）；write-ahead journal `runtime/m3_action/idempotency.jsonl`（副作用前先落 claim，崩溃后同 key 重试返回首个结果）；审批队列持久化 `runtime/m3_action/approvals.jsonl`（重启重放重建 pending）；审批终态（DENY/timeout）幂等回写 journal（复核修复项：原只落事件不回写，同 key 重试曾返回过期 WAITING_APPROVAL）
- **evidence**：`src/m3_action/executor.py:79-98`；`src/m3_action/approval.py:22`（DEFAULT_APPROVAL_TIMEOUT_S=300.0）；`tests/CHANGELOG.md`（M3 登记 5/6/7 + 独立评审缺口修复 5）。
- **v2 处置**：吸收为条款。

### D-29〔新增〕失联执行器建模 `isolate_execution_env`：执行落在 `env.deep_copy()`（执行器在副本上自报成功），observer 独立回读真实环境发现未兑现 issued 声明→降级 FAILED/`OBSERVATION_MISMATCH`（SPEC-M3-09"自报成功不构成 observed"的可测落位）
- **evidence**：`src/m3_action/gateway.py`/`observer.py`；`tests/CHANGELOG.md`（M3 登记 8）。
- **v2 处置**：吸收为条款。

### D-30〔新增〕trace/事件确定性口径：ActionRequest 冻结无 trace 字段→trace_id 从 task 派生（`trace-<task_id>`）；event_id=流内递增序号（`EVT-M3-<seq>`，journal 重放续序）；SIMULATION latency_ms=0（真实时延属 MONOTONIC 审计域）
- **evidence**：`tests/CHANGELOG.md`（M3 登记 9）；`src/m3_action/gateway.py`。
- **v2 处置**：吸收为条款（event_id 形态并入 D-03）。

### D-31〔变义〕REAL 门禁三重：非评估上下文（gateway `evaluation=True` 或 `PD_EVALUATION` 置位强制 SIMULATION）+ 环境变量 `PD_REAL_MODE` + 双人开关（两个不同审批人 id）齐备才路由 REAL，且仅 mock 适配器（FAILED/`REAL_MOCK_ONLY`）
- v1 SPEC-M3-10 只写"环境变量+双人审批开关"。
- **evidence**：`src/m3_action/router.py:21-23,50-54,65-73`；`tests/CHANGELOG.md`（M3 登记 10）。
- **v2 处置**：吸收为条款。

### D-32〔新增〕审批权 fail-closed：`submit_approval` 仅已登记且角色=审批人可决断；未登记人员（角色 None）与实例未登记任何人员（actor_roles 空）一律 REJECTED/`APPROVER_NOT_AUTHORIZED`（原实现两种情形静默放行，评审后收紧）
- **evidence**：`src/m3_action/gateway.py:244-275`（257-258 角色判定、270 错误码）；`tests/CHANGELOG.md`（安全规程判据落地 4）；commit 06ce55a。
- **v2 处置**：吸收为条款——审批主体授权（v1 完全未写）。

### D-33〔变义〕`create.switch_order` PARAMS_SCHEMA `status` 枚举收窄为 `[DRAFT]`（原 `[DRAFT, ISSUED]` 缺省 ISSUED——agent 可零审批自铸已签发票）；DRAFT→ISSUED 只能由持证签发人（角色数据源=实例 `env.operators`）在 agent 动作集之外完成；M5 simulate 对非 DRAFT 请求一律 FAILED/`SAFE_ISSUE_HUMAN`（M3 SCHEMA_INVALID 拒绝 + M5 判据层兜底双保险）
- **evidence**：`tools/create__switch_order.py:31-35`；`src/m5_simulation/scenario.py:230-250`；`tests/CHANGELOG.md`（安全规程判据落地 1）；commit 06ce55a。
- **v2 处置**：吸收为条款——SAFE-ISSUE-HUMAN 的代码级落位。

### D-59〔缺陷〕`tools/modify__asset_history.py` PARAMS_SCHEMA 形态缺陷（验收已发现、未修）：`required: ["device","entry"]` 中 `entry` 为无子结构约束的裸 `"type":"object"`（仅 description"台账条目（永不执行，仅记录意图）"），schema 形态不收敛；该动作缺省 DENY 永不执行，schema 仅具准入记录意义
- **evidence**：`tools/modify__asset_history.py:10-17`（第 13 行起 properties 形态；任务交办单引用行号 :509 同源的验收指认项）；对照 `tools/modify__protection_setting.py:11-18` 同形态。
- **v2 处置**：KNOWN-DEFECT——登记不修（DENY 红线动作，schema 收敛无行为收益）；v2 可在 DENY 动作 schema 规范中显式豁免或统一。

---

## M4 Semantic

### D-34〔新增〕实体解析歧义判据机械口径（全数据驱动 `ontology/aliases.yaml`，新增设备零代码）：房内序号强读法 0.8 / 全园区尾号弱读法 0.6 / 同类型兜底 0.5，按 `unambiguous_margin`(0.3) 判唯一/歧义；"唯一消歧"语义=结果无 ambiguous 标记，结果集可含联动传感器（"A 房 1 号柜局放"→SG-A01+PD-A01 两条）
- **evidence**：`src/m4_semantic/resolver.py:102-105`；`ontology/aliases.yaml:25`；`tests/CHANGELOG.md`（M4 登记 2/3）。
- **v2 处置**：吸收为条款。

### D-35〔新增〕"负荷→回路→变压器→容量约束"机械路径：LoadCurve -metered_at-> Feeder -upstream_of(in)-> Transformer + 属性拾取 capacity_kva（属性拾取步不计关系跳数：模式声明 hops=3，路径关系跳数=2）
- **evidence**：`tests/CHANGELOG.md`（M4 登记 4）；`src/m4_semantic/graph.py`。
- **v2 处置**：吸收为条款——跳数计数口径。

### D-36〔新增〕token 计量口径：CJK 字符 1 token/字 + ASCII 词元 1/串（确定性估算，无模型调用；`estimate_tokens`）
- **evidence**：`src/m4_semantic/view.py:31-36`；`tests/CHANGELOG.md`（M4 登记 7）。
- **v2 处置**：吸收为条款。

### D-37〔变义〕SPEC-M4-06 触发口径：缺失概念比例 ≥30%（等价命中率 <70%）产出 `badcase.opened` **候选事件**（EventRecord dict 经 contracts 校验，producer=M4，payload.candidate=true）；事件持久化归 M2/M6，M4 只产出候选；任务级报告落 `runtime/coverage/task-<id>.json`
- **evidence**：`src/m4_semantic/coverage.py:28-29,120-135`；`tests/CHANGELOG.md`（M4 登记 6）。
- **v2 处置**：吸收为条款——"候选"与"持久化"职责切分。

---

## M5 Simulation

### D-38〔新增〕场景种子来源：ScenarioSpec 十字段组（01§2.8）无独立 seed 字段→缺省种子由 manifest_hash 派生（同规格同种子→确定性重放）；`run_scenario(seed=...)` 可显式覆盖；`SimRunResult.reproduction.seed` 记录实际值
- **evidence**：`src/m5_simulation/scenario.py:352-356,795-800`；`tests/CHANGELOG.md`（M5 登记 1）。
- **v2 处置**：吸收为条款。

### D-39〔变义〕告警阈值唯一来源=`regulations/REG-TECH.yaml`（SPEC-M5-08 同源纪律）；v1 M5 §2 示例口径（">80%→WARN、>95%→ALARM"）与 REG-TECH（0.80→P2 过载预警、1.00→P0 重过载）不符，按规程文件为准（EVAL-M5-PHYS-P 的 0.88→P2 WARN 即此口径）
- **evidence**：`src/m5_simulation/alarm_engine.py:13-14,53-57`；`regulations/REG-TECH.yaml:14`（PHYS-TX-LOAD）；`tests/CHANGELOG.md`（M5 登记 2）。
- **v2 处置**：吸收为条款并修订 M5 §2 措辞。

### D-40〔新增〕dev-01"温度缓升注入"落为环境事件 `device.temp_rise`（五类故障注入不含温度类；00§1.1 量测事件语义）；配套新增规程条款 `PHYS-TX-TEMP`（REG-TECH，scope=Transformer，metric=winding_temp_c，>85→P2，ADDENDUM §A"条款文字自拟"授权）+ 物理常数 `tx_temp_rise_c` 55K（顶油温升类建模常数，非阈值，正常负载 ≈73℃ 不误报）
- 复核前旧口径"无对应规程阈值则不产告警"使 M5 §2 明列的"温度>85℃"告警不可达，已按同源纪律修复（实测 86.9℃ 触发 P2）。
- **evidence**：`src/m5_simulation/scenario.py:522-532`；`regulations/REG-TECH.yaml:86`；`src/m5_simulation/physics.py:35`；`scenarios/dev-01-report.yaml:36`；`tests/CHANGELOG.md`（M5 登记 3 + M5 复核修订 2）；commit fad0e10。
- **v2 处置**：吸收为条款——PHYS-TX-TEMP 入规则目录；dev-01 事件类型成文。

### D-41〔新增〕`interactions.timeout_s` 语义：墙钟秒；场景引擎按 speed（墙钟秒→仿真秒，SPEC-M5-02 倍速语义）换算为仿真秒后再判审批超时
- **evidence**：`tests/CHANGELOG.md`（M5 登记 4）；`src/m5_simulation/scenario.py`。
- **v2 处置**：吸收为条款。

### D-42〔变义〕SIMULATION 时延确定性：`latency_ms` 为确定性常数 0（真实时延属 MONOTONIC 审计域，由 M3 REAL 路由计量）；`AUDIT_COLUMNS=("monotonic_ms","wall_at","latency_ms")` 三列在确定性 diff（diff_runs）中按约定剔除，判据列 business_at/sim_elapsed_s 逐步比对。已知小疵：`scenario.py:636,685` 的 DENY/审批终态路径用常数 `latency_ms=1`（仍确定性、diff 中被剔除，但与"常数 0"口径不一致）
- **evidence**：`src/m5_simulation/scenario.py:112-114,320-326,636,685`；`src/m5_simulation/recorder.py:25`；`tests/CHANGELOG.md`（M5 复核修订 1 + M5 登记 9）。
- **v2 处置**：吸收为条款（diff 剔除列成文）；latency_ms=1 小疵随条款统一（修正成本≈0，可作为 v2 落地时的顺手项，非 KNOWN-DEFECT）。

### D-43〔新增〕EVAL 实例注入机制：seed 的 TX-02=1600kVA 与 EVAL-M5-PHYS-P 需要的 1250kVA 不一致、PARK-001 seed 无告警/工单/检修计划/负荷曲线运行对象而三跳查询需要——开发实例 `tests/fixtures/dev-sim-park.yaml`（同构快照仅改容量）与 `tests/fixtures/dev-graph.yaml`（同构含 AL-0201/WO-D0021/MP-TX01/LC-A0901/F-A1）经 ADDENDUM §D `PARK_INSTANCE_PATH` 追加 `tests/fixtures` 注入，同一代码路径服务任意同构实例
- **evidence**：`tests/fixtures/dev-sim-park.yaml:20`；`tests/fixtures/dev-graph.yaml`；`tests/CHANGELOG.md`（M5 登记 7 + M4 登记 1）。
- **v2 处置**：吸收为条款——EVAL 实例与生产实例分离的注入机制。

### D-44〔强制〕墙钟扫描口径：`m5_simulation/clock.py` 是 WALL/MONOTONIC 只读真实时钟的唯一合法实现位（SPEC-M5-02 本身要求其存在，扫描排除之——排除清单是用例数据非代码特判）；EVAL-M5-02-N 扫描面 `scan_dirs=[src,tools,scripts]`（SPEC-M5-02/README §4"业务代码"全口径）；CI 隔离正则宽化为 `PARK-002|TARIFF-2026B|OP-1[0-9]`（ADDENDUM §F `OP-1x` 的等宽正则）
- **evidence**：`src/m5_simulation/clock.py:145-149`；`scripts/ci_isolation.py:31`；`tests/CHANGELOG.md`（M5 登记 8 + 安全规程判据落地 5 + 独立评审 4）。
- **v2 处置**：吸收为条款。

### D-45〔新增〕M5 复核审计三小项：persona 远期哨兵由 `datetime.now()+10y` 改常量 `datetime.max`（业务模块零 wall-clock）；`_soc_bounds` 规程缺失兜底由硬编码 (10,90) 改物理量程 (0,100)；dev-02b 恢复丢失的 dev-02 SENSOR_STUTTER 注入继承（规格 §7"dev-02 基础上"）
- **evidence**：`src/m5_simulation/persona.py:157-160`；`src/m5_simulation/physics.py:171`；`scenarios/dev-02b-remote.yaml:21`；`tests/CHANGELOG.md`（M5 复核修订 3/4/5）；commit fad0e10。
- **v2 处置**：吸收为条款。

### D-46〔强制〕SAFE 三规约在 M5 判据层强制执行（v1 00§1.4 只声明规则、未指定执行位； Eval 表亦未覆盖）：SAFE-ISSUE-HUMAN（agent 动作集外签发；桩链预置票签发人角色校验自 `env.operators`，非持证只登记 DRAFT 并落合规事件 grid.event{kind: switch_order_issued}）；SAFE-ORDER-SEQ（remote_control step 与票面 steps 声明顺序对照，跳步 FAILED/`SAFE_ORDER_SEQ`；多步票逐步放行、全部完成才 COMPLETED，执行中保持 ISSUED）；SAFE-SINGLE-OP（票级 `executing` 互斥标记，重复执行流 FAILED/`SAFE_SINGLE_OP`，结束/异常均释放）
- **evidence**：`src/m5_simulation/scenario.py:166-208,336,543-565,603-622`；`tests/CHANGELOG.md`（安全规程判据落地 1/2/3）；commit 06ce55a。
- **v2 处置**：吸收为条款——SAFE-* 的执行位与错误码。

### D-47〔变义〕M5 simulate 的 DENY 路径数据驱动化 + 终态对齐：删除第三份硬编码 DENY 清单 `_DENY_ALWAYS_HINT`，改按 `ontology/actions.yaml` 的 default_policy 现算（与 M3 registry.assert_immutable_consistency 同源）；该路径终态由 FAILED/POLICY_DENIED 改为 **DENIED**（01§5.2 冻结迁移 DENY→DENIED，与 SUT 桩链及 M3 gateway 一致）
- **evidence**：`src/m5_simulation/scenario.py:628-636`；`tests/CHANGELOG.md`（独立评审缺口修复 3）；commit 06ce55a。
- **v2 处置**：吸收为条款（并入 D-01/D-06）。

---

## M6 Flywheel

### D-48〔新增〕MODEL_CALL 轨迹步判定口径=`budget.warning/budget.exhausted` 且 `payload.kind=="token"`（01§4 事件目录无 model.* 主题；M1 成本通道的沿用）；action 类预算事件归 STATE_CHANGE；事件→步型映射为全函数（28 主题全覆盖，缺省 STATE_CHANGE）
- **evidence**：`src/m6_flywheel/trajectory.py:57-59,105-107`；`tests/CHANGELOG.md`（M6 登记 1）。
- **v2 处置**：吸收为条款。

### D-49〔新增〕判据引擎落位：rubric 评分单不内嵌案例文件（GoldenCase 冻结契约拒未知字段），外置 `golden/dev/rubrics.yaml`（case_id→评分单，DEFAULT 兜底），RUBRIC clause 按契约注释作评分锚定 ID；表达式引擎实现于 `m6_flywheel.judges`（无 eval/exec，与 EVAL-SCHEMA §3 最小语法同构），扩展 `not in` 成员否定（JUDGE-SYNTAX §1.3 登记）；五维权重和=1，输出总分+分维明细
- **evidence**：`src/m6_flywheel/judges.py:166-177`；`golden/dev/rubrics.yaml`；`tests/CHANGELOG.md`（M6 登记 2/5）。
- **v2 处置**：吸收为条款。

### D-50〔扩展〕evaluator release 解析序（向后兼容增补）：`releases/<id>/evaluation/cases.yaml`（M7 发布物自带评估清单，重跑与发布前实测同源）→ `releases/<id>/release.yaml` → `tests/fixtures/mock_releases/<id>.yaml`（离线清单）→ 内建通用 mock；mock 行为全部数据驱动（events/injections/plan/expect_capabilities），零案例特判
- **evidence**：`src/m6_flywheel/evaluator.py:94,168-171`；`tests/CHANGELOG.md`（M6 登记 3 + M7 登记 9）。
- **v2 处置**：吸收为条款。

### D-51〔新增〕黄金链路真实化（独立评审 medium 修复）：CaseRunner 每条计划步经 **M3 ActionGateway.execute_action 全链**（准入→幂等 claim→PolicyEngine 三值→审批队列→SIMULATION 路由→Observer 回读+自报降级）；审批决断走真实 submit_approval/check_approval_timeouts；task 生命周期经 **M2 InformationLayer**（create_task+commit_state，01§5.1 迁移表+乐观锁）；mock 计划只声明"何时请求何能力+审批决定"，不再伪造事件；12 种子对真实链全过（97.67/100 不变）
- **evidence**：`src/m6_flywheel/evaluator.py:480-528`；`tests/CHANGELOG.md`（独立评审缺口修复 1）；commit 06ce55a。
- **v2 处置**：吸收为条款——黄金跑分的被测对象=真实 M2/M3 链（v1 未写明）。

### D-52〔变义〕黄金集目录形态：12 条种子按 M6 §6 交付物口径直落 `golden/dev/` 平铺（case_001..012.yaml；v1 01§1 目录树写 `golden/ cases/*.yaml`）；加载器同时支持 cases/ 子目录形态；`MANIFEST.yaml` 登记逐文件 sha256+来源标记（CI hash 校验基准）；`python -m m6_flywheel.golden_set verify golden/dev` 独立可执行；dev 集遇 holdout 标记条目直接拒绝
- **evidence**：`src/m6_flywheel/golden_set.py:49-51,96-97`；`golden/dev/MANIFEST.yaml`；`tests/CHANGELOG.md`（M6 登记 6）。
- **v2 处置**：吸收为条款。

### D-53〔新增〕Badcase ADOPTED 判据口径：candidate 在关联案例通过**且**总分（百分制=mean(rubric 总分)×20）≥ current 才 ADOPTED；A/B 报告须同 golden_set_version（同黄金集硬校验）；实验记录（两版分数+diff 用例）归档 `<archive_dir>/experiments/<badcase_id>.json`；状态机 OPENED→REPRODUCED→FIX_CANDIDATE→EXPERIMENT→ADOPTED/REJECTED（中间态均可 REJECTED 终结；无法复现→REJECTED）
- **evidence**：`src/m6_flywheel/badcase.py:50-55,218-240`；`tests/CHANGELOG.md`（M6 登记 7）。
- **v2 处置**：吸收为条款。

### D-54〔新增〕评估归档形态：evaluator 结果落 `runs/eval/<UTC 时标>-<release_id>/`（report.json+逐案例事件流/轨迹+release 快照）；EVAL 内运行归档进沙箱 `runtime/m6_eval/<case>/`；runs/ 目录整体 gitignore（eval 产物不进 git，tracked runs/.gitkeep 保留目录）
- **evidence**：`src/m6_flywheel/evaluator.py`；`tests/CHANGELOG.md`（M6 登记 8）；commit 0391c9f。
- **v2 处置**：吸收为条款。

### D-55〔强制〕评估与调优单向（SPEC-M6-06）代码级落位：`ReleaseGuard` 只暴露只读成绩读取；直改 release 状态请求被拒并落审计事件 `release.published{rejected:true, requested_status, reason}`（沿用就近主题先例）
- **evidence**：`src/m6_flywheel/evaluator.py:192-230`；`tests/CHANGELOG.md`（M6 登记 4）。
- **v2 处置**：吸收为条款。

### D-56〔强制〕Skill 化门槛（SPEC-M6-05）代码级落位：`MIN_OCCURRENCES=3`（≥3 个不同任务实例出现且判据通过）；候选 SkillDescriptor status 强制 REVIEW（走 M7 变更评审）+ `skill.promoted` 事件；evidence_policy 强制含黄金成绩提升证明引用
- **evidence**：`src/m6_flywheel/skillize.py:34,137,154`；`tests/CHANGELOG.md`（M6 交付；commit 1f30e77）。
- **v2 处置**：吸收为条款。

### D-57〔扩展〕`export_trajectory(trace_id, *, release_id="sim")` 增加 release_id 形参（缺省 "sim"）——TrajectoryRecord 契约 release_id 必填的离线兼容；v1 签名 `export_trajectory(trace_id)`
- **evidence**：`src/m6_flywheel/trajectory.py:191,307`。
- **v2 处置**：吸收为条款——API 形参扩展（向后兼容）。

### D-58〔缺陷〕evaluator 场景人因硬编码（验收已发现、未修）：ASK 动作审批决断一律以硬编码审批人 `"OP-004"` 调 `gateway.submit_approval`；计划步 actor.user 缺省硬编码 `"OP-001"`——场景人因仅部分数据化（`issue_by` 声明持证签发人已数据驱动，审批人未然）。交办单引用行号 :509；当前代码审批人硬编码位于 :520/:523、user 缺省位于 :503
- **evidence**：`src/m6_flywheel/evaluator.py:503,520,523`（544-565 为已数据化的 issue_by 链）；交办单"src/m6_flywheel/evaluator.py:509 审批人硬编码"。
- **v2 处置**：KNOWN-DEFECT——登记不修（mock 计划域内行为，验收已放行 rel-0001）；v2 将"审批决断人来自场景数据"列为改进条款。

---

## M7 Registry & Release

### D-60〔变义〕评审流/Release 状态机为 M7 自建表驱动（v1 M7 §5 DoD 引用的"01§5.4"不存在——01 §5 只有 5.1-5.3）：REVIEW_TRANSITIONS（PROPOSED→EVALUATING|REJECTED|WITHDRAWN；EVALUATING→APPROVED|REJECTED|WITHDRAWN；APPROVED→PUBLISHED；PUBLISHED/REJECTED/WITHDRAWN 终态）与 `tests/fixtures/m7_state_machines.yaml` diff 为空（新 fixture，不动 S0 frozen_state_machines.yaml）；Release 状态机 DRAFT→GATED→PUBLISHED（PUBLISHED 后仅 SUPERSEDED）；评审/发布审计事件落 `release.published{stage: review|asset-publish, …}`
- **evidence**：`src/m7_registry/review.py:54-60`；`src/m7_registry/publish.py:130-138`；`tests/fixtures/m7_state_machines.yaml`；`tests/CHANGELOG.md`（M7 登记 1/2）。
- **v2 处置**：吸收为条款——v2 的 01 应新增 §5.4/§5.5 两台状态机。

### D-61〔新增〕六要素"空值口径"：model_ref/ontology_version/golden_scores 非空、prompt/skill/tool_refs **非空列表**才视为已绑定（空列表=要素缺失，缺一拒绝打包）；RELEASE-FORMAT.md §2 登记
- **evidence**：`src/m7_registry/release.py:57-59`（SIX_ELEMENTS）；`src/m7_registry/RELEASE-FORMAT.md`；`tests/CHANGELOG.md`（M7 登记 3）。
- **v2 处置**：吸收为条款。

### D-62〔新增〕AgentContract 绑定通道：冻结 ReleaseBundle（01§2.12）无 agent 字段不可擅改→绑定落发布目录 `agent_contract.yaml` 快照 + `manifest.yaml.agent_contract`（asset_id/version/sha256）；`bundle_draft` 必须携带 `agent_ref`（M7 自有子契约字段，非冻结结构字段），缺失拒绝打包；AgentContract 资产=六能力域+12 约束+行为目录绑定 12 黄金种子（`assets/agent_contract_v1.yaml`）
- **evidence**：`releases/rel-0001/manifest.yaml:6-10`；`src/m7_registry/agent_contract.py:60-100`；`assets/agent_contract_v1.yaml`；`tests/CHANGELOG.md`（M7 登记 4）。
- **v2 处置**：吸收为条款。

### D-63〔新增〕golden_scores 双层签名链 + run_ref 解析序：`by_domain.signature`（M7 侧 digest=sha256(canonical 成绩载荷)）+ `attestation`（M6 侧凭证 `m6_flywheel.attest` 对逐案例成绩摘要签名，producer=M6）；校验链=digest 重算→run_ref 归档装载→attestation 重算→从归档重推全部成绩逐块相等；`import_golden_scores` 唯一合法产出口（报告 release_id 必须等于打包 release；全部数字机械推导）；by_domain 四块=capability（六能力域）/category（四类目）/catalog（12 种子逐条）/red_line（100% 断言记录），目录映射来自 AgentContract behavior_catalog（数据源非代码）；run_ref 解析序=绝对路径→release 目录内相对（发布后指向 evaluation/report.json 副本，digest 不含 run_ref 故发布改写不断链）→仓库根相对
- **evidence**：`src/m7_registry/release.py:103-171`；`src/m6_flywheel/attest.py:1-30`；`tests/CHANGELOG.md`（M7 登记 5/6）。
- **v2 处置**：吸收为条款。

### D-64〔新增〕评审基线口径：candidate 总分（M6 报告 totals.score_100，缺则 pass_rate×100）≥ 现行已发布 release 的 golden_scores；无现行 release 时基线=0（首个 release 无可回归基线）；M7 只消费 M6 结果（runs/eval/ 归档），不自己跑分
- **evidence**：`src/m7_registry/review.py`（golden-not-below-current 前置）；`tests/CHANGELOG.md`（M7 登记 7）。
- **v2 处置**：吸收为条款。

### D-65〔变义〕资产存储形态：v1 M7 §2 组件表注明 `assets.py # 四类资产 CRUD+版本链（SQLite）`，oracle 实为 **JSONL journal**（`runtime/m7_registry/assets.jsonl` 追加写+重放重建，M3 幂等 journal 先例）；chain 整数=版本链权威，描述子自身 version 串（semver/v1）为 ref 组成部分；内容 hash 未变的更新拒绝（版本号不空转）；re-register/unchanged-update/explicit-chain 改写全拒；`publish_asset` 是资产置 PUBLISHED 的唯一入口（`AssetStore._set_status` 模块私有，无公开 setter——SPEC-M7-03"无旁路"代码级落位）
- **evidence**：`src/m7_registry/assets.py:20-24,439-443`；`specs/M7-registry-release.md:14`；`tests/CHANGELOG.md`（M7 登记 8）。
- **v2 处置**：吸收为条款——修订 M7 §2 措辞（SQLite→JSONL journal），或在 v2 统一"持久层形态"横切条款（M2=SQLite、M3/M7=JSONL journal）。

### D-66〔新增〕rel-0001 发布基线 + assemble CLI：`PYTHONPATH=src python -m m7_registry.assemble --release-id rel-0001`（注册 20 项资产 PROMPT×2/SKILL×1/TOOL×16/AGENT×1，全部经评审流 publish_asset 发布→M6 实测 12 种子全过 97.67/100→签名导入→六要素打包→门禁 5 项全过→只写一次发布）；已发布后 CLI 重入为只读复核模式（manifest/签名/黄金重跑，零写入）；发布物含 `evaluation/`（report.json+cases.yaml）
- **evidence**：`releases/rel-0001/manifest.yaml`（status: PUBLISHED、gate 5/5、files sha256）；`src/m7_registry/assemble.py`；`tests/CHANGELOG.md`（M7 登记 10）。
- **v2 处置**：吸收为条款（发布物形态）+ 资产基线登记。

---

## ADDENDUM 五项落地形态核对（本会话逐项实证）

### D-67〔新增〕ADDENDUM §A REG-OP：五个规则 ID 全部落盘 `regulations/REG-OP.yaml`
- SAFE-OP-TWO-TICKET（parent SAFE-TWO-TICKET）/ SAFE-OP-REMOTE（parent SAFE-ORDER-SEQ, SAFE-SINGLE-OP）/ SAFE-OP-MAINTAIN（parent SAFE-MAINTAIN-ISO）/ OP-QCOMP-CAP / OP-DEMAND-LIMIT（criteria 与 PHYS-DEMAND 同源：warn_over 1.0→P2、breach_over 1.05→P0）均带自拟条款文字与从属关系，未与 00 冲突。
- **evidence**：`regulations/REG-OP.yaml`（全文核对）；`specs/ADDENDUM.md:13-18`。
- **v2 处置**：吸收为条款（REG-OP 目录转正入 00 规则目录）。

### D-68〔强制〕ADDENDUM §B report.daily@v1 四段：`report_daily_v1` 校验 devices（非空列表）/ measurements（非空且逐条含 points 时序趋势点列 ts/value）/ conclusion（非空）/ regulation_refs（规则 ID 列表）四段；规则 ID 存在性经 `m4_semantic.regulation.rule_id_checker()` 工厂注入全部 InformationLayer 构造点（m1/m2 eval_plugin、M6 CaseRunner），EVAL-M2-08-N2 钉死（引用 PHYS-BOGUS-999→REJECTED）
- **evidence**：`src/m2_information/artifact.py:83-124`；`src/m4_semantic/regulation.py:146-156`；`src/m1_core/loop.py:84-90`（content_sections 四段）；`tests/CHANGELOG.md`（独立评审缺口修复 2）。
- **v2 处置**：吸收为条款。

### D-69〔新增〕ADDENDUM §C 两事件落地：`price.period_changed {from, to, price, boundary}` 在时段边界（BUSINESS 时钟读数）发布；`demand.month_rolled {from_month, to_month, frozen_peak_kw}` 在 15min 采样跨月切换时先发后重置；两主题已入 contracts.EventType 封闭集（共 28 主题）
- **evidence**：`src/m5_simulation/price_clock.py:75-92,143-160`；`src/contracts/enums.py:224-225`；`src/m1_core/loop.py:78-81`（列为环境事件主题）。
- **v2 处置**：吸收为条款。

### D-70〔强制〕ADDENDUM §D Park 实例按名加载：去扩展名匹配（.yaml/.yml），默认搜索 `ontology/`，`PARK_INSTANCE_PATH`（分隔符 ";"）追加目录；M4 loader 与 M5 env 同一机制实现；加载实现对任意同构实例通用（EVAL 经 fixtures 注入验证，零实例特判）
- **evidence**：`src/m4_semantic/loader.py:63-64,181-198`；`src/m5_simulation/env.py:6,465-467`；`tests/CHANGELOG.md`（M4 登记 1、M5 登记 7）。
- **v2 处置**：吸收为条款。

### D-71〔强制〕ADDENDUM §E evaluator CLI：`--release <id>`（必填）、`--golden <dir>`（缺省 `golden/dev/` = DEFAULT_GOLDEN_DIR）、`--mode`（缺省 SIMULATION；REAL 拒绝 exit 2）
- **evidence**：`src/m6_flywheel/evaluator.py:877-880`（与 :29-30 docstring）；`tests/CHANGELOG.md`（M6 登记：CLI 三参实测，REAL 拒绝 exit 2）。
- **v2 处置**：吸收为条款。

---

## 汇总统计与后续拆分

| 模块 | 条目 | KNOWN-DEFECT |
| --- | --- | --- |
| S0/契约 | D-01..D-06（6） | — |
| M1 | D-07..D-16（10） | — |
| M2 | D-17..D-23（7） | — |
| M3/tools | D-24..D-33、D-59（11） | D-59 |
| M4 | D-34..D-37（4） | — |
| M5 | D-38..D-47（10） | — |
| M6 | D-48..D-58（11） | D-58 |
| M7 | D-60..D-66（7） | — |
| ADDENDUM | D-67..D-71（5） | — |
| **合计** | **71** | **2（交办单指认 2 项均已核实定位）** |

- 交办单指认 KNOWN-DEFECT 核对：`src/m6_flywheel/evaluator.py:509 审批人硬编码` → 实际定位 `:520/:523`（硬编码 `"OP-004"`）+ `:503`（缺省 `"OP-001"`），记 D-58；`tools/modify__asset_history.py:13 schema 形态` → `:10-17`（entry 裸 object），记 D-59。
- 拆分指引：每模块工程师按本文件 D-编号认领，落 `specs-v2/deviations/<模块>.md`；S0/契约层（D-01..D-06）与 ADDENDUM 层（D-67..D-71）建议由契约负责人统一处置后再分发给模块。
