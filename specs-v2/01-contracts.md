# 01 · 模块划分与模块间冻结契约（v2.0）

> 本文件定义 7 个模块的职责边界与模块间**冻结契约**（Frozen Contracts）：数据结构、调用接口、事件、状态机。
> 冻结含义：开发期间任何模块不得单方面变更本文件定义的接口；变更必须走契约变更流程（见 §7）并全员同步。
> 全部数据结构以 YAML/JSON 表达，字段名与枚举值大小写敏感。
>
> **v2 重生成说明（资产工程阶段）**：本文件由 v1（`specs/01-contracts.md`，v1.0 + ADDENDUM v1.1）按
> **oracle（唯一事实源）** 重生成——oracle = 现行实现全体（`src/contracts/` 为本文件的代码化权威）。
> 已发布冻结契约版本 `CONTRACT_VERSION = "1.1"`（`src/contracts/__init__.py:117`；rel-0001 manifest 同值）。
> 结构与 v1 保持同序同编号便于 diff；**每处与 v1 的差异加行内标记 `[v2Δ: 偏差依据 evidence]`**，
> 未标记部分与 v1 语义一致。冻结结构条目共 **12 个（§2.1–§2.12）**。
> [v2Δ D-05: specs/README.md:11 原文称"11 数据结构"，01§2 实定义 12 个（§2.1–§2.12 含 ReleaseBundle），
> oracle 按 12 全部代码化（`src/contracts/__init__.py:94-96` STRUCTURES）；tests/CHANGELOG.md S0 登记 6]

---

## 1. 模块划分总览

| 模块 ID | 名称 | 一句话职责 | 上游依赖 |
| --- | --- | --- | --- |
| `M1` | Agent Core（执行内核） | Agent Loop 五阶段、任务状态机、阶段门禁、完成验证 | M2, M3, M4 |
| `M2` | Information（信息层） | Context 构建管线、状态外置、Workspace/Artifact、Memory/Skill 披露 | M7 |
| `M3` | Action Gateway（行动层） | 能力注册、Policy 三值、HITL、执行路由、幂等 | M5, M7 |
| `M4` | Semantic（本体语义层） | 本体加载、实体解析、多跳查询、覆盖率监测 | —（读 ontology/） |
| `M5` | Simulation（仿真层） | 环境模拟器、用户模拟器、场景引擎、四类时间 | M4 |
| `M6` | Flywheel（飞轮层） | 轨迹采集、黄金集、Badcase、受控自进化 | M2, M7 |
| `M7` | Registry & Release（资产层） | 四类资产注册/版本/变更评审、Agent Release 打包 | — |

**部署形态**：单进程多模块（进程内调用优先）；M3 对外执行与 M5 仿真通过适配器隔离。
持久层形态 [v2Δ D-65: v1 写"SQLite 单文件起步（runtime/state.db）"；oracle 实为分层持久形态——
M2=SQLite（`StateStore(dsn)` 连接串可配，`postgres*` 抛 NotImplementedError 即 DoD"预留不实现"落地形态，
`src/m2_information/state_store.py:228-236`；tests/CHANGELOG.md M2 登记 7/8）、
M3/M7=JSONL journal 追加写+重放重建（`runtime/m3_action/idempotency.jsonl`、`runtime/m3_action/approvals.jsonl`、
`runtime/m7_registry/assets.jsonl`；`src/m3_action/executor.py:79-98`、`src/m3_action/approval.py:22`、
`src/m7_registry/assets.py:20-24`；tests/CHANGELOG.md M3 登记 5、M7 登记 8）]：
事件流追加写 `runtime/events/<stream>.jsonl`（按 stream 分片，缺省 `task-<task_id>` 一任务一分片；
`src/m2_information/event_log.py:50-53`）[v2Δ: 补分片口径——v1 只写 `runtime/events/*.jsonl`，oracle 实现按流分片]。

**目录树（开发约定，按 oracle 实际布局修订）**：

```text
peidian-agent/
├── ontology/            # 本体 YAML（00-ontology.md 的机器可读版）
│   ├── objects.yaml  relations.yaml  actions.yaml  rules.yaml  enums.yaml
│   ├── seed.yaml        # PARK-001 种子实例（缺省实例）
│   └── aliases.yaml     # M4 实体解析数据文件（别名/序号读法/属性词典，数据可调）
├── regulations/         # 虚拟规程（REG-SAFE.yaml / REG-COMM.yaml / REG-TECH.yaml / REG-OP.yaml）
├── skills/              # Skill 资产（每个 skill 一个目录：SKILL.yaml+正文+脚本）
├── prompts/             # Prompt 资产（版本化）
├── assets/              # AgentContract 等资产定义（assets/agent_contract_v1.yaml）
├── tools/               # 工具适配器（一动作一模块：<action_id 的 "."→"__">.py，共 16 个 + _base.py 公共约定）
├── src/
│   ├── m1_core/  m2_information/  m3_action/  m4_semantic/
│   ├── m5_simulation/  m6_flywheel/  m7_registry/
│   └── contracts/      # 本文件数据结构的代码化（标准库 dataclass + 逐字段校验器）
├── golden/              # 黄金集（dev 集平铺：case_001..012.yaml + MANIFEST.yaml + rubrics.yaml；兼容 cases/ 子目录）
├── scenarios/           # 开发用仿真场景（dev-*.yaml）
├── releases/            # 发布物（rel-0001/，M7 只写一次）
├── scripts/             # CI 脚本（ci_isolation.py 隔离断言等）
├── runtime/             # 运行期产物（state.db / events / workspaces / artifacts / m3_action / m7_registry / runs，git ignore）
└── tests/               # EVAL 用例（数据驱动 YAML：tests/test_m*.yaml + negative_matrix.yaml + fixtures/）
```

[v2Δ D-27: v1 目录树写 `tools/ # 工具适配器（每个 action family 一个）`；oracle 实为 16 个适配器一动作一模块
（模块名=动作 ID 的 "."→"__"，如 `create__switch_order.py`），`tools/_base.py` 公共约定；
tests/CHANGELOG.md M3 登记 4]
[v2Δ D-52: v1 写 `golden/ # 黄金集（cases/*.yaml）`；oracle 12 条种子直落 `golden/dev/` 平铺
（加载器兼容 cases/ 子目录，`src/m6_flywheel/golden_set.py:49-51`）；tests/CHANGELOG.md M6 登记 6]
[v2Δ: 补 regulations/REG-OP.yaml、ontology/aliases.yaml、assets/、releases/、scripts/——均为 oracle 实有而 v1 树未列]

---

## 2. 冻结数据结构（Frozen Data Structures）

全部结构登记于 `src/contracts/`（代码化+运行时校验）。字段缺省必填=是，除非标注 optional。

**校验基础设施约定（§2 全部结构统一适用，`src/contracts/base.py`）**：

1. **未知字段拒绝**：每个结构/嵌套子结构 `from_dict` 以 `check_keys` 封闭字段集校验，
   未知字段（含拼写漂移）一律抛 `ContractValidationError`。[v2Δ D-17: v1 未写封闭字段集；oracle
   全部结构 `check_keys` 强制（`src/contracts/base.py:73-77`）；tests/CHANGELOG.md M2 登记 1]
2. **时间戳双形态**：`timestamp` 字段接受 UTC ISO-8601 **字符串**（`2026-09-15T08:30:00Z` / `…+00:00`，
   不接受无时区或非 UTC 偏移）与 pyyaml 把未加引号时间戳解析出的 **UTC `datetime` 对象**（tz-naive /
   非 UTC 拒绝），round-trip 原值保留不改写。[v2Δ D-04: v1 只写"一律 UTC ISO-8601"；oracle
   `check_timestamp` 双形态放行（`src/contracts/base.py:126-149`）；tests/CHANGELOG.md S0 登记 4]
3. **标识符宽松口径**：`string(ulid)` 标注的标识符按 `check_id` 校验=**非空字符串**（ULID 与业务编号
   体系双兼容，不强制 ULID 形态）。[v2Δ D-03: v1 写 `string(ulid)`；oracle `check_id` 宽松
   （`src/contracts/base.py:164-166`，"宽松以兼容既有编号体系"）；tests/CHANGELOG.md S0/M3 登记]
4. **capability 格式**：`"动作ID@版本"`（如 `query.measurement@v1`），`@` 两侧均不得为空
   （`check_capability_format`，`src/contracts/base.py:169-177`）。
5. **枚举封闭集**：枚举按契约字面量匹配（成员值即字面量，大小写敏感），越界即
   `ContractValidationError`；受控词表与 `ontology/enums.yaml` 同源，一致性由 EVAL `contracts.enum_closure` 断言
   （`src/contracts/enums.py:311-323` CONTROLLED_VOCABULARY）。

### 2.1 ActionRequest（M1→M3）

```yaml
ActionRequest:
  action_id: string(ulid)          # 唯一（按 check_id=非空字符串校验，见 §2 约定 3 [v2Δ D-03]）
  task_id: string                  # 归属任务
  turn: int                        # 任务内轮次
  capability: string               # 格式 "动作ID@版本"，如 "query.measurement@v1"（check_capability_format 强制）
  actor:
    user: string                   # 发起用户 id（Operator）
    agent: string                  # agent id@版本
    on_behalf_of: string optional  # 委托链（L3+ 才使用）
  purpose: string                  # 一句话目的（进审计）
  arguments: object                # 动作参数（按 capability schema 校验）
  risk: {level: enum(risk_level), reversible: bool, compensation: string optional}
  idempotency_key: string          # 同 key 重复请求必须幂等（幂等键两档策略见 §3.3 [v2Δ D-28]）
  requested_at: timestamp          # UTC（双形态见 §2 约定 2 [v2Δ D-04]）
```

代码化：`src/contracts/core.py:94-136`（`ActionRequest`/`Actor`/`Risk`，字段封闭集校验）。

### 2.2 ActionResult（M3→M1）

```yaml
ActionResult:
  action_id: string
  status: enum(action_status)
  result_refs: list[string]        # Artifact/资源引用
  observation: string              # 给模型看的 Observation 文本（结构化序列化）
  evidence:
    intended: object               # 计划动作（=ActionRequest 摘要）
    issued: object optional        # 已发出动作（执行器确认）
    observed: object optional      # 环境确认结果（真实读数/状态回读）
  error: {code: string, message: string} optional
  latency_ms: int
  trace_id: string
```

**Evidence 三态规则**：`SUCCEEDED` 必须三者齐全（`from_dict` 构造时强制校验，非约定即抛
`ContractValidationError`，`src/contracts/core.py:197-204`）[v2Δ: v1 为文字规则，oracle 已代码级强制]；
`EXECUTING` 允许 intended+issued；观察结果必须来自环境回读，不得由执行器自报
（M3 Observer 独立回读；失联执行器降级 FAILED/OBSERVATION_MISMATCH
[v2Δ D-29: SPEC-M3-09 的可测落位——执行落 `env.deep_copy()` 副本，observer 回读真实环境
（`src/m3_action/gateway.py`/`observer.py`）；tests/CHANGELOG.md M3 登记 8]）。

### 2.3 TaskState（M2 持有，M1 读写）

```yaml
TaskState:
  task_id: string
  version: int                     # 乐观锁，每次变更 +1
  status: enum(task_status)
  current_stage: string            # 阶段门禁当前阶段
  plan: list[{stage: string, gate: string, artifacts_expected: list[string]}]
  todos: list[{id: string, text: string, status: enum(PENDING/IN_PROGRESS/DONE)}]
  budget:                          # Budget Lease（M3 联动扣减）
    token_max: int
    token_used: int
    action_max: int
    action_used: int
    deadline: timestamp optional
    price_window: {from: timestamp, to: timestamp} optional
  artifacts: list[string]          # ArtifactRecord id
  subtasks: list[string] optional  # L3+ 委派
  evidence_refs: list[string]      # 完成验证引用
  context_manifest_hash: string    # 最近一轮 Context 指纹
  updated_at: timestamp
```

- 字段集封闭（§2 约定 1）；`price_window` 契约字段名 `from`/`to`（Python 关键字，内部改名存取，
  `src/contracts/core.py:260-276`）。
- [v2Δ D-12: 预算耗尽判定口径——`used ≥ max` 即租约耗尽、deadline 判 `now > deadline`、
  price_window 判 `now ∉ [from,to]`，比较基准一律为注入 now；m1_core 内唯一真实时钟读取位=
  `clocking.now_iso()`，budget.py/loop.py 零墙钟（`src/m1_core/budget.py:85-102`）；
  tests/CHANGELOG.md M1 登记 6]
- [v2Δ D-14: TaskState 冻结结构无轮次字段——trace 轮次台账取 LoopTrace 日志最大轮号+1，
  Checkpoint 恢复后轮号续增，任务语义续跑点由 plan 当前阶段+todos 决定
  （`src/m1_core/trace.py:83,122`）；tests/CHANGELOG.md M1 登记 9]

### 2.4 ContextManifest（M2→M1，每轮生成）

```yaml
ContextManifest:
  task_id: string
  turn: int
  sources: list[{name, type(enum), tokens, priority, origin}]
  # source 五字段为封闭集（check_keys 拒未知字段）[v2Δ D-17]
  # type 枚举（14 值封闭集）：SYSTEM_POLICY/AGENT_CONTRACT/TENANT_RULE/RUNTIME_REMINDER/SKILL/
  #           TOOL_DESCRIPTOR/GOAL_STEERING/PLAN_TODO/RECENT_INTERACTION/
  #           COMPACTED_HISTORY/RETRIEVED_MEMORY/RETRIEVED_KNOWLEDGE/ONTOLOGY_VIEW/WORKSPACE_REF
  total_tokens: int
  budget_remaining: int
  compiled_at: timestamp
  hash: string                     # 同 task 状态+同轮输入 → 必须同 hash（确定性）
```

- `priority` 类型契约未约束（数值或等级串均可，`src/contracts/core.py:369`）。
- 裁剪记录"双落" [v2Δ D-17]：被裁源在 Manifest 内 `tokens=0` 留存 + `origin` 追加
  `;trimmed=dropped@priority=<P>` 注记；完整 trim_log/filter_log/conflicts/directives 落
  `workspace/manifest/turn-<n>.json`（FORMATS.md §3.4；`src/m2_information/context_builder.py`）。
- [v2Δ D-23: hash 确定性输入口径成文——sha256(规范 JSON{task_id, turn, version, sources 五元组,
  total_tokens})；`compiled_at` 与 ULID 随机量不进 hash；System 层源 origin 携带内容 hash、
  Skill 源 origin 携带 `skill_id@version` 指纹（资产版本变化必然翻转 hash）
  （`src/m2_information/context_builder.py`）；tests/CHANGELOG.md M2 登记 9]
- [v2Δ D-19: policy 永不裁的负向口径代码级强制——仅剩 SYSTEM_POLICY 层仍超预算→拒绝编译、
  `budget.exhausted{kind:token}` + RUNNING→PAUSED、抛 `ContextBudgetExceededError`，
  不产出超额 Manifest（`src/m2_information/context_builder.py`）；tests/CHANGELOG.md M2 登记 4]

### 2.5 EventRecord（全系统事件，追加写 `runtime/events/*.jsonl`）

```yaml
EventRecord:
  event_id: string                 # 唯一性域=事件流；接受 ULID 与流内序号双形态 [v2Δ D-03]
  type: enum(event_type)           # 见 §4 事件清单（28 主题封闭集）
  subject: string                  # task_id/action_id/artifact_id/alarm_id…
  payload: object
  occurred_at: timestamp
  trace_id: string                 # 缺 trace_id 的事件在写入时被拒（from_dict 强制，01 §8）
  producer: string                 # 模块 id
```

[v2Δ D-03: v1 写 `event_id: string(ulid)`；oracle 放宽为非空字符串并实际存在**流内序号**形态——
M5 `EVT-<run_id>-<seq:06d>`（`src/m5_simulation/env.py:207-209`）、M3 `EVT-M3-<seq>`（journal 重放续序，
`src/m3_action/events.py:57`；tests/CHANGELOG.md M3 登记 9）——与 ULID 双形态并存，唯一性域=事件流]

### 2.6 ArtifactRecord（M2 持有）

```yaml
ArtifactRecord:
  artifact_id: string(ulid)        # 按 check_id=非空字符串校验 [v2Δ D-03]
  type: enum(REPORT/WORK_ORDER/SWITCH_ORDER/INSPECTION_RECORD/ANALYSIS_RESULT/DATASET)
  status: enum(artifact_status)
  schema_id: string                # 内容 schema 版本，如 "report.daily@v1"
  content_ref: string              # 文件路径（workspace 内相对路径）
  created_by: {task_id, action_id}
  validation: {passed: bool, checks: list[{name, passed, detail}]} optional
  version: int
  supersedes: string optional      # 替代链
```

代码化：`src/contracts/core.py:514-549`。同 action_id 重复入账幂等跳过
（created_by.action_id 去重守卫）[v2Δ D-11: write.report SUCCEEDED 后由数据驱动产物策略
（`DEFAULT_ARTIFACT_POLICY`，构造可覆盖）自动落 M2 ArtifactRecord（DRAFT→VALIDATING→READY），
同 action_id 重放幂等（复核修复项，commit 9062518）（`src/m1_core/loop.py:84-90,642-673`）；
tests/CHANGELOG.md M1 登记 5+复核修订 1]。

### 2.7 SkillDescriptor（M7 持有，M2 披露）

```yaml
SkillDescriptor:
  skill_id: string
  version: string                  # semver
  capability_domain: enum(PREDICT/DISPATCH/MAINTAIN/PLAN/SELF_HEAL/TRADE)
  disclosure:                      # 渐进披露三级
    level0: string                 # 名称（常驻 System Context，≤10 词）
    level1: string                 # 一段描述（目录层）
    level2_ref: string             # 全文（加载进上下文才计费）
  entry: {prompt_ref optional, script optional, checklist optional}
  evidence_policy: string          # 使用该 skill 时的证据要求
  owner: string
  status: enum(DRAFT/REVIEW/PUBLISHED/DEPRECATED)
```

代码化：`src/contracts/assets.py:44-120`。行为口径 [v2Δ D-21: 披露可见状态缺省仅 PUBLISHED
（DRAFT/REVIEW 未过 M7 发布门禁同样不入层，`SkillRegistry(visible_status=...)` 可调）；
level0 ≤10 词注册即强校验（CJK 每字 1 词、ASCII 按空白分词）；任务能力域与 skill 域匹配=集合交集
（task_domains 为编译入参）（`src/m2_information/skill_disclosure.py:70-74,111-114`）；
tests/CHANGELOG.md M2 登记 6]。

### 2.8 ScenarioSpec（M5 场景规格，十字段组）

```yaml
ScenarioSpec:
  identity: {scenario_id, version, owner, tags[]}
  sut: {target: enum(AGENT/MODULE), module optional, agent_release optional}
  environment:                     # 环境初始化
    park_instance: string          # Park 实例按名加载（去扩展名匹配 .yaml/.yml；默认搜索 ontology/，
                                   # PARK_INSTANCE_PATH（分隔符 ";"）追加目录）[v2Δ D-70]
    clock_start: timestamp
    speed: float                   # 仿真时间流速（墙钟秒→仿真秒换算基准 [v2Δ D-41]）
    injections: list[{at, type, target, params}]   # 故障注入计划
  user_model:                      # 用户模拟器
    persona: enum(OPERATOR/DISPATCHER/APPROVER)
    behavior_script: list[{at, act(USER_INPUT/GRANT/DENY/LEAVE), text optional}]
  interactions: {max_turns: int, timeout_s: int}
  events: list[{at, type, subject, params}]        # 环境事件计划（告警/量测/开关变位）
  constraints: {budget{token,action}, stop_conditions[]}
  metrics: list[{name, rubric}]    # 判据引用（黄金判据或规程条款）
  provenance: {source, created_at, notes}
```

- `at` 字段为**时间引用**（`check_time_ref`：非空字符串或 pyyaml 解析出的 `datetime` 均接受，
  格式由 M5 约定；`src/contracts/simulation.py:92-102`）[v2Δ D-04: v1 未区分 at 与 timestamp 的
  校验口径；tests/CHANGELOG.md S0 登记 4]。
- `interactions.timeout_s` 语义=墙钟秒；场景引擎按 speed 换算为仿真秒后再判审批超时
  [v2Δ D-41: tests/CHANGELOG.md M5 登记 4；`src/m5_simulation/scenario.py`]。
- 本结构无独立 seed 字段；缺省种子由 manifest_hash 派生（见 §2.9 reproduction.seed）[v2Δ D-38]。

### 2.9 SimRunResult（M5 输出，三层证据分离）

```yaml
SimRunResult:
  run_id: string
  scenario_id: string
  manifest_hash: string            # ScenarioSpec 内容 hash（复现性）
  traj_ref: string                 # TrajectoryRecord 引用
  state_final: object              # 仿真环境终态
  evidence_pack:
    - {kind: INTERACTION_LOG, ref}
    - {kind: STATE_TRANSITIONS, ref}
    - {kind: TIMELINE, ref}        # 含四类时间对齐表
  reproduction:
    deterministic: bool            # 同 seed 同轨迹必须 true
    seed: string                   # 实际使用的种子（缺省由 manifest_hash 派生，run_scenario(seed=...) 可覆盖）
```

[v2Δ D-38: v1 未写种子来源；oracle 缺省种子=manifest_hash 派生（同规格同种子→确定性重放），
`run_scenario(seed=...)` 显式覆盖，`reproduction.seed` 记录实际值
（`src/m5_simulation/scenario.py:352-356,795-800`）；tests/CHANGELOG.md M5 登记 1]

### 2.10 GoldenCase（M6 黄金集）

```yaml
GoldenCase:
  case_id: string
  version: int
  task_input: string               # 用户原始指令
  environment_seed: string         # 环境种子（M5 可复现）
  scenario_ref: string optional
  expected_behavior: list[{clause: string, judge: enum(DETERMINISTIC/RUBRIC)}]
  # DETERMINISTIC: 机器判据（如 status 必须 COMPLETED 且 evidence 三态齐）
  # RUBRIC: 规程/行为判据（按规则 ID 或行为目录条目 ID 锚定；评分单外置 golden/dev/rubrics.yaml）
  source: enum(HANDWRITTEN/TRAJECTORY_MINED/REGENERATED)
  excluded_from: list[string]      # 标注 "holdout" 的案例禁止进开发集（dev 集加载遇 holdout 标记直接拒绝）
```

[v2Δ D-49: rubric 评分单不内嵌案例文件（GoldenCase 冻结契约拒未知字段），外置
`golden/dev/rubrics.yaml`（case_id→评分单，DEFAULT 兜底），RUBRIC clause 按规则 ID 或行为目录条目
ID 锚定；五维权重和=1（`src/m6_flywheel/judges.py:166-177`）；tests/CHANGELOG.md M6 登记 2/5]
[v2Δ D-52: dev 集遇 holdout 标记条目直接拒绝（`src/m6_flywheel/golden_set.py:96-97`）；
tests/CHANGELOG.md M6 登记 6]

### 2.11 TrajectoryRecord（M6 采集）

```yaml
TrajectoryRecord:
  trace_id: string
  task_id: string
  release_id: string               # 必填（离线导出经 export_trajectory(release_id=...) 兜底 [v2Δ D-57]）
  steps: list[{seq, type(MODEL_CALL/TOOL_CALL/STATE_CHANGE/APPROVAL), ref, summary, latency_ms, cost}]
  outcome: {status, evidence_summary, completion_level(1-5)}
  cost_total: {tokens, currency}
  quality_flags: list[string]      # 如 LATEX_STUCK/LOOP/REFUSAL_MISSING
```

[v2Δ D-57: `export_trajectory(trace_id)` 增 `release_id` 形参（缺省 `"sim"`）——本结构 release_id 必填的
离线兼容，向后兼容（`src/m6_flywheel/trajectory.py:191,307`）]
[v2Δ D-48: MODEL_CALL 步判定口径=`budget.warning`/`budget.exhausted` 且 `payload.kind=="token"`
（事件目录无 model.* 主题，M1 成本通道的沿用）；action 类预算事件归 STATE_CHANGE；事件→步型映射为
全函数（28 主题覆盖，缺省 STATE_CHANGE）（`src/m6_flywheel/trajectory.py:57-59,105-107`）；
tests/CHANGELOG.md M6 登记 1]

### 2.12 ReleaseBundle（M7 打包）

```yaml
ReleaseBundle:
  release_id: string               # 如 rel-0003
  model_ref: string                # 模型+版本+端点配置
  prompt_refs: list[string]        # prompts/ 带 hash
  skill_refs: list[string]         # skills/ 带 hash
  tool_refs: list[string]          # tools/ 注册清单
  ontology_version: string         # ontology/ 目录 hash
  golden_scores: {golden_set_version, pass_rate, by_domain{...}}
  frozen_scenarios: list[string]   # 随 release 冻结的场景 id
  contract_version: string         # 本文件版本（现行 "1.1"）
```

[v2Δ D-61: 六要素**空值口径**——model_ref/ontology_version/golden_scores 非空、prompt/skill/tool_refs
**非空列表**才视为已绑定（空列表=要素缺失），缺一拒绝打包；RELEASE-FORMAT.md §2 登记
（`src/m7_registry/release.py:57-59`）；tests/CHANGELOG.md M7 登记 3]
[v2Δ: `contract_version` 语义=01-contracts 版本，ADDENDUM 升版后为 `1.1`
（`src/contracts/__init__.py:117`；`src/contracts/assets.py:318`）]

---

## 3. 冻结调用接口（Frozen APIs）

进程内接口以函数签名表达（语言无关描述；HTTP/gRPC 可后置）。签名为 oracle 实际入口
（`src/m1_core/loop.py`、`src/m2_information/__init__.py`、`src/m3_action/gateway.py`、
`src/m4_semantic/`、`src/m5_simulation/`、`src/m6_flywheel/`、`src/m7_registry/`）。

### 3.1 M1 Agent Core

```text
run_task(user_input: string, task_ctx: TaskContext) -> TaskState
  # 主入口：创建/恢复任务，驱动 Agent Loop 直至 WAITING_* 或终态
resume_task(task_id: string, event: ResumeEvent) -> TaskState
  # ResumeEvent ∈ {USER_INPUT, APPROVAL_GRANTED, APPROVAL_DENIED, ENV_EVENT, TIMEOUT}
request_completion(task_id: string, claim: CompletionClaim) -> CompletionVerdict
  # 模型申请完成；M1 用证据判定，verdict ∈ {ACCEPTED, NEED_MORE_EVIDENCE, REJECTED}
```

- [v2Δ D-16: TaskContext 缺省 `actor_user="OP-001"`、`actor_agent="park-agent@v1"` 为构造入参可覆盖的
  硬编码缺省值（`src/m1_core/loop.py:100-101`）——显式成文，无行为锁定]
- [v2Δ D-13: **ResumeEvent 状态-种类匹配矩阵**（v1 §3.1 只列种类未列状态匹配）——
  PAUSED 接受任意种类但恢复前重查预算（仍超限→`LoopNotResumableError` 保持 PAUSED）；
  WAITING_INPUT→USER_INPUT；WAITING_APPROVAL→APPROVAL_GRANTED/APPROVAL_DENIED/TIMEOUT；
  WAITING_EVENT→ENV_EVENT；VERIFYING→USER_INPUT/ENV_EVENT/TIMEOUT；错配即拒
  （`src/m1_core/loop.py:65-75,196-252` `_RESUME_RULES`）；tests/CHANGELOG.md M1 登记 8]
- [v2Δ D-09: 完成门禁落位——`TaskStateMachine.is_completable` + `CompletionRequiredError`
  （IllegalTransitionError 子类），无完成 claim 的 COMPLETED 迁移拒绝；拒绝事件同时带
  `rejected:true`（M1 口径）与 `accepted:false`（M2 重建跳过口径）
  （`src/m1_core/state_machine.py:85-97`）；tests/CHANGELOG.md M1 登记 3]
- [v2Δ D-07: Loop 五阶段回放校验（replay_report）的数据源是 M1 审计件
  `runtime/<root>/m1_core/loop/task-<id>.jsonl`（LoopTrace），不是 §4 事件流；校验规则=每轮为
  PREPARE→MODEL→ACT→OBSERVE→VERIFY 的阶段序前缀（仅 PREPARE=预算中断轮合法）——LoopTrace 审计件
  与事件流双轨定位，权威状态仍在 M2（`src/m1_core/trace.py`、`src/m1_core/loop.py:799-801`）；
  tests/CHANGELOG.md M1 登记 1]
- [v2Δ D-10: 产物过门匹配双口径——`plan.artifacts_expected` 按 artifact_id 精确匹配**或** schema_id
  匹配（计划先于产物存在、ULID 无法预知），过门状态=GATE_PASS_STATUSES（READY/PUBLISHED）
  （`src/m1_core/gates.py:28-29`）；tests/CHANGELOG.md M1 登记 4]
- [v2Δ D-15: 模型端点安全边界——model_client 建连前 `_assert_safe_endpoint()` fail-closed
  （https-only、拒 URL 内嵌凭据、解析地址全公网、`PD_MODEL_ALLOW_PRIVATE_HOSTS` 白名单）；缺省传输
  `http.client` 直连，错误语义保持（非 2xx 原样返回/超时→TimeoutError/网络错→ConnectionError）
  （`src/m1_core/model_client.py:106-168`）；tests/CHANGELOG.md 2026-09-29 提交门禁安全修复；commit 400a5a2]

### 3.2 M2 Information

```text
compile_context(task_id: string, turn: int) -> ContextManifest
commit_state(task_id: string, mutation: StateMutation) -> TaskState     # 版本+1，事件落盘
snapshot(task_id: string) -> Checkpoint
restore(checkpoint_id: string) -> TaskState
write_memory(task_id, content, type: memory_type, provenance) -> MemoryId | REJECTED
retrieve_memory(query, task_id) -> list[MemoryEntry]
disclose_skill(skill_id, level: 0|1|2) -> SkillView                      # 三级披露
save_artifact(record: ArtifactRecord) -> ArtifactRecord
validate_artifact(artifact_id) -> ValidationReport
```

- [v2Δ D-20: `write_memory` 未过六问返回**字面量哨兵 `"REJECTED"`**（字符串，不抛错），最近拒绝原因存
  `MemoryStore.last_rejection`，SPECULATIVE 归因 verification 问——v1 `MemoryId | REJECTED` 联合类型
  语义的落地形态（`src/m2_information/memory.py:40,89,279`）；tests/CHANGELOG.md M2 登记 5]
- [v2Δ D-18: `commit_state` 非状态字段（todos/plan/budget/context_manifest_hash 等）提交落
  `task.status_changed{from==to}`+mutation/version/updated_at，事件重建按同一 `apply_state_mutation`
  折叠（单一变更语义）；非法迁移拒绝事件 `accepted=false`，重建时跳过
  （`src/m2_information/state_store.py:114-125`）；tests/CHANGELOG.md M2 登记 2——并入 §4 D-06 扩展通道]
- [v2Δ D-22: StateStore 表超集——规格四表（task_state/artifacts/memory/checkpoints）之外增
  knowledge/sessions/calls 三表（Knowledge 只读条目与 Call⊂Session⊂Task 三级管理）；
  `StateStore(dsn)` 连接串可配，`postgres*` 抛 NotImplementedError（DoD"预留不实现"落地形态）
  （`src/m2_information/state_store.py:164-237`）；tests/CHANGELOG.md M2 登记 7/8——超集不违反最小集]
- [v2Δ D-68: `save_artifact` 对 `report.daily@v1` 执行四段校验（devices 非空列表/measurements 逐条含
  points 时序趋势点列 ts/value/conclusion 非空/regulation_refs 规则 ID 列表）；规则 ID 存在性经
  `m4_semantic.regulation.rule_id_checker()` 工厂注入全部 InformationLayer 构造点（EVAL-M2-08-N2：
  引用 PHYS-BOGUS-999→REJECTED）（`src/m2_information/artifact.py:83-124`；
  tests/CHANGELOG.md 独立评审缺口修复 2)]

### 3.3 M3 Action Gateway

```text
register_capability(capability: CapabilityDescriptor) -> CapabilityId
execute_action(request: ActionRequest) -> ActionResult                    # 同步边界
  # 内部路由：mode ∈ {REAL, SIMULATION}；SIMULATION → M5.simulate()
query_policy(capability, actor, context) -> PolicyDecision(ALLOW/ASK/DENY)
submit_approval(action_id, decision: GRANT/DENY, approver) -> ActionResult
check_approval_timeouts(now) -> list                                      # 审批超时批处理 [v2Δ]
```

**幂等规则**：同 `idempotency_key` 的重复请求返回首个结果（含原 action_id），不重复执行。

- [v2Δ D-28: 幂等键**两档策略**——CALLER_PROVIDED / CALLER_PROVIDED_UNIQUE_ARGS（同 key 承载不同
  (capability, arguments)→`KEY_CONFLICT` 拒绝不进主链）；write-ahead journal
  `runtime/m3_action/idempotency.jsonl`（副作用前先落 claim，崩溃后同 key 重试返回首个结果）；
  审批队列持久化 `runtime/m3_action/approvals.jsonl`（重启重放重建 pending，超时缺省 300s）；
  审批终态（DENY/timeout）幂等回写 journal（独立评审修复 5）（`src/m3_action/executor.py:79-98`、
  `src/m3_action/approval.py:22`）；tests/CHANGELOG.md M3 登记 5/6/7]
- [v2Δ D-24: **准入失败不进生命周期**——契约/注册/披露/schema/路由（REAL 被拒）失败发生在 §5.2
  REQUESTED 之前→状态 REJECTED、不落 `action.requested`（不进事件主链）、审计落
  `action.policy_decided{decision:DENY, stage:admission}`（`src/m3_action/gateway.py`）；
  tests/CHANGELOG.md M3 登记 1]
- [v2Δ D-25: 不可改清单（policy_locked）语义——对 ASK 锁定动作（execute.remote_control）拒绝**一切**
  覆盖，含收紧 ASK→DENY；SPEC-M3-11 矩阵对 remote_control 期望缺省 ASK（WAITING_APPROVAL 零副作用
  同样成立）（`src/m3_action/policy_engine.py:106-107,145-146`；`src/m3_action/registry.py:41-48`）；
  tests/CHANGELOG.md M3 登记 2]
- [v2Δ D-26: 角色收紧基准=**当前生效判定**（已存覆盖优先于缺省）——已收紧为 ASK 的角色再请求 ALLOW
  （即使 ALLOW==缺省）属放宽被拒；合法收紧方向=ALLOW→ASK / ALLOW→DENY / ASK→DENY
  （`src/m3_action/policy_engine.py:29-31,154`）；tests/CHANGELOG.md M3 登记 3]
- [v2Δ D-32: 审批权 fail-closed——`submit_approval` 仅已登记且角色=审批人可决断；未登记人员
  （角色 None）与实例未登记任何人员一律 REJECTED/`APPROVER_NOT_AUTHORIZED`
  （`src/m3_action/gateway.py:244-275`）；tests/CHANGELOG.md 安全规程判据落地 4；commit 06ce55a]
- [v2Δ D-31: REAL 门禁三重——非评估上下文（gateway evaluation=True 或 `PD_EVALUATION` 置位强制
  SIMULATION）+ 环境变量 `PD_REAL_MODE` + 双人开关（两个不同审批人 id）齐备才路由 REAL，且仅 mock
  适配器（FAILED/`REAL_MOCK_ONLY`）（`src/m3_action/router.py:21-23,50-54,65-73`）；
  tests/CHANGELOG.md M3 登记 10]
- [v2Δ D-30: trace/事件确定性口径——ActionRequest 冻结无 trace 字段→trace_id 从 task 派生
  （`trace-<task_id>`）；event_id=流内递增 `EVT-M3-<seq>`（journal 重放续序，见 §2.5）；
  SIMULATION latency_ms=0（真实时延属 MONOTONIC 审计域）；tests/CHANGELOG.md M3 登记 9]
- [v2Δ D-27: 数据权威装配——16 适配器（`tools/`）的参数 schema/幂等键策略/披露面来自适配器声明，
  风险/缺省 Policy 来自 `ontology/actions.yaml`，装配即断言 diff 空（registry_vs_actions_table_diff）
  （`tools/_base.py`；`src/m3_action/registry.py:276` sys.path 兜底）；tests/CHANGELOG.md M3 登记 4]
- [v2Δ D-33: `create.switch_order` PARAMS_SCHEMA `status` 枚举收窄为 `[DRAFT]`（原 `[DRAFT, ISSUED]`
  缺省 ISSUED——agent 可零审批自铸已签发票）；DRAFT→ISSUED 只能由持证签发人（角色数据源=实例
  `env.operators`）在 agent 动作集外完成；M5 simulate 对非 DRAFT 请求一律 FAILED/`SAFE_ISSUE_HUMAN`
  （M3 SCHEMA_INVALID 拒绝 + M5 判据层兜底双保险）（`tools/create__switch_order.py:31-35`；
  `src/m5_simulation/scenario.py:230-250`）；tests/CHANGELOG.md 安全规程判据落地 1；commit 06ce55a]

### 3.4 M4 Semantic

```text
load_ontology(version: string) -> LoadedOntology
resolve_entities(text: string) -> list[ResolvedEntity]                    # 实体链接
query_graph(pattern: GraphPattern, hops ≤ 3) -> list[GraphNode/Edge]
concept_view(entity_ids: list[string]) -> OntologyView                    # 注入 Context 用
coverage_report(window) -> {hits, total, ratio, missing[]}
```

- [v2Δ D-34: 实体解析歧义判据机械口径（全数据驱动 `ontology/aliases.yaml`，新增设备零代码）——
  显式别名 1.0 / 房内序号强读法 0.8 / 全园区尾号弱读法 0.6 / 同类型兜底 0.5，按
  `unambiguous_margin`(0.3) 判唯一/歧义；"唯一消歧"=结果无 ambiguous 标记，结果集可含联动传感器
  （"A 房 1 号柜局放"→SG-A01+PD-A01）（`src/m4_semantic/resolver.py:102-105`）；
  tests/CHANGELOG.md M4 登记 2/3——数据文件全文见 00 v2 §6]
- [v2Δ D-35: 三跳查询机械路径与跳数计数口径——"负荷→回路→变压器→容量约束"=
  LoadCurve -metered_at-> Feeder -upstream_of(in)-> Transformer + 属性拾取 capacity_kva；
  **属性拾取步不计关系跳数**（模式声明 hops=3，路径关系跳数=2）（`src/m4_semantic/graph.py`）；
  tests/CHANGELOG.md M4 登记 4]
- [v2Δ D-36: token 计量口径——CJK 字符 1 token/字 + ASCII 词元 1/串（确定性估算 `estimate_tokens`，
  无模型调用）（`src/m4_semantic/view.py:31-36`）；tests/CHANGELOG.md M4 登记 7]
- [v2Δ D-37: SPEC-M4-06 触发口径——缺失概念比例 ≥30%（命中率 <70%）产出 `badcase.opened`
  **候选事件**（EventRecord 经 contracts 校验，producer=M4，payload.candidate=true）；事件持久化归
  M2/M6、M4 只产出候选；任务级报告落 `runtime/coverage/task-<id>.json`
  （`src/m4_semantic/coverage.py:28-29,120-135`）；tests/CHANGELOG.md M4 登记 6——见 00 v2 §4]
- [v2Δ D-70: Park 实例按名加载——去扩展名匹配（.yaml/.yml），默认搜索 `ontology/`，
  `PARK_INSTANCE_PATH`（分隔符 ";"）追加目录；M4 loader 与 M5 env 同一机制，对任意同构实例通用
  （`src/m4_semantic/loader.py:63-64,181-198`）；tests/CHANGELOG.md M4 登记 1]

### 3.5 M5 Simulation

```text
load_scenario(spec: ScenarioSpec) -> SimEnv
step(env: SimEnv, action: SimAction | ENV_TICK) -> (SimEnv, Observation, SimEvents[])
simulate(action: ActionRequest, env: SimEnv) -> (ActionResult, SimEnv)    # M3 仿真路由目标
persona_step(persona, history) -> UserUtterance                            # 用户模拟器
clock(mode: BUSINESS/SIM_LOGICAL/MONOTONIC/WALL) -> ClockReading           # 四类时间
inject(env, fault: FaultSpec) -> SimEnv                                    # 故障注入
run_scenario(spec) -> SimRunResult                                         # 场景引擎一站式
diff_runs(result_a, result_b) -> list                                      # 确定性 diff [v2Δ]
```

- [v2Δ D-41: `interactions.timeout_s` 墙钟秒→按 speed 换算仿真秒后判审批超时（同 §2.8）]
- [v2Δ D-42: SIMULATION 时延确定性——`latency_ms` 为确定性常数（真实时延属 MONOTONIC 审计域）；
  `AUDIT_COLUMNS=("monotonic_ms","wall_at","latency_ms")` 三列在确定性 diff（diff_runs）中按约定剔除，
  判据列 business_at/sim_elapsed_s 逐步比对；已知小疵：DENY/审批终态路径用常数 `latency_ms=1`
  （仍确定性且被 diff 剔除，随条款统一非 KNOWN-DEFECT）（`src/m5_simulation/scenario.py:112-114,320-326`、
  `src/m5_simulation/recorder.py:25`）；tests/CHANGELOG.md M5 复核修订 1+M5 登记 9]
- [v2Δ D-44: 墙钟扫描口径——`m5_simulation/clock.py` 是 WALL/MONOTONIC 只读真实时钟的唯一合法实现位
  （排除清单是用例数据非代码特判）；EVAL-M5-02-N 扫描面 scan_dirs=[src,tools,scripts]（业务代码全口径）
  （`src/m5_simulation/clock.py:145-149`；`scripts/ci_isolation.py:31`）；tests/CHANGELOG.md M5 登记 8]
- [v2Δ D-46: SAFE 三规约在 M5 判据层强制执行（v1 00§1.4 只声明规则未指定执行位）——
  SAFE-ISSUE-HUMAN（非持证签发只登记 DRAFT 并落合规事件；DRAFT→ISSUED 只能由持证签发人完成）、
  SAFE-ORDER-SEQ（跳步 FAILED/`SAFE_ORDER_SEQ`；多步票逐步放行、全部完成才 COMPLETED）、
  SAFE-SINGLE-OP（票级 executing 互斥，重复执行流 FAILED/`SAFE_SINGLE_OP`）
  （`src/m5_simulation/scenario.py:166-208,336,543-565,603-622`）；tests/CHANGELOG.md 安全规程判据落地 1/2/3；
  commit 06ce55a——条款全文见 00 v2 §1.4]
- [v2Δ D-47: simulate 的 DENY 路径数据驱动化+终态对齐——按 `ontology/actions.yaml` default_policy 现算
  （与 M3 assert_immutable_consistency 同源，无第三份硬编码清单）；终态 DENIED（§5.2 冻结迁移）
  （`src/m5_simulation/scenario.py:628-636`）；tests/CHANGELOG.md 独立评审缺口修复 3；commit 06ce55a]
- [v2Δ D-43: EVAL 实例注入机制——开发实例 `tests/fixtures/dev-sim-park.yaml`（同构仅改容量）与
  `tests/fixtures/dev-graph.yaml`（同构含运行对象）经 ADDENDUM §D `PARK_INSTANCE_PATH` 注入，
  同一代码路径服务任意同构实例（EVAL 实例与生产实例分离）；tests/CHANGELOG.md M5 登记 7+M4 登记 1]

### 3.6 M6 Flywheel

```text
export_trajectory(trace_id, *, release_id: string = "sim") -> TrajectoryRecord  # [v2Δ D-57 形参扩展]
add_golden_case(case: GoldenCase) -> CaseId
run_golden(release_id, golden_set_version) -> {pass_rate, failures[]}
open_badcase(evidence: BadcaseEvidence) -> BadcaseId
promote_to_skill(badcase_id, skill_draft: SkillDescriptor) -> SkillId     # 受控自进化入口（走 M7 评审）
```

- [v2Δ D-50: evaluator release 解析序（向后兼容）——`releases/<id>/evaluation/cases.yaml`（发布物自带
  评估清单）→ `releases/<id>/release.yaml` → `tests/fixtures/mock_releases/<id>.yaml` → 内建通用 mock；
  mock 行为全数据驱动零案例特判（`src/m6_flywheel/evaluator.py:94,168-171`）；
  tests/CHANGELOG.md M6 登记 3+M7 登记 9]
- [v2Δ D-51: **黄金链路真实化**——黄金跑分的被测对象=真实 M2/M3 链：CaseRunner 每条计划步经真实
  M3 ActionGateway.execute_action 全链（准入→幂等 claim→三值 Policy→审批队列→SIMULATION 路由→
  Observer 回读+自报降级），审批决断走真实 submit_approval/check_approval_timeouts，task 生命周期经
  M2 InformationLayer（§5.1 迁移表+乐观锁）；mock 计划只声明何时请求何能力+审批决定，不再伪造事件
  （`src/m6_flywheel/evaluator.py:480-528`）；tests/CHANGELOG.md 独立评审缺口修复 1；commit 06ce55a]
- [v2Δ D-55: 评估与调优单向（SPEC-M6-06）代码级落位——ReleaseGuard 只暴露只读成绩读取，直改 release
  状态请求被拒并落审计事件 `release.published{rejected:true, requested_status, reason}`
  （`src/m6_flywheel/evaluator.py:192-230`）；tests/CHANGELOG.md M6 登记 4]
- [v2Δ D-56: Skill 化门槛代码级强制（SPEC-M6-05）——MIN_OCCURRENCES=3（≥3 个不同任务实例出现且判据
  通过），候选 SkillDescriptor status 强制 REVIEW（走 M7 评审）+`skill.promoted` 事件，evidence_policy
  强制含黄金成绩提升证明引用（`src/m6_flywheel/skillize.py:34,137,154`）；commit 1f30e77]
- [v2Δ D-53: Badcase ADOPTED 判据口径——candidate 在关联案例通过**且**总分（百分制=mean(rubric 总分)
  ×20）≥ current 才 ADOPTED；A/B 须同 golden_set_version（硬校验）；实验记录归档
  `<archive_dir>/experiments/<badcase_id>.json`；中间态均可 REJECTED 终结（无法复现→REJECTED）
  （`src/m6_flywheel/badcase.py:50-55,218-240`）；tests/CHANGELOG.md M6 登记 7]
- [v2Δ D-54: 评估归档形态——evaluator 结果落 `runs/eval/<UTC 时标>-<release_id>/`（report.json+逐案例
  事件流/轨迹+release 快照）；EVAL 内归档进沙箱 `runtime/m6_eval/<case>/`；runs/ 整体 gitignore
  （eval 产物不进 git）（`src/m6_flywheel/evaluator.py`）；tests/CHANGELOG.md M6 登记 8；commit 0391c9f]
- [v2Δ D-71: evaluator CLI——`--release <id>`（必填）、`--golden <dir>`（缺省 `golden/dev/`）、
  `--mode`（缺省 SIMULATION，REAL 拒绝 exit 2）（`src/m6_flywheel/evaluator.py:877-880`）；
  tests/CHANGELOG.md M6 登记（CLI 三参实测，REAL 拒绝 exit 2）]
- [v2Δ D-58 · KNOWN-DEFECT（验收发现未修，登记不修）: evaluator 场景人因硬编码——ASK 动作审批决断
  一律以硬编码审批人 `OP-004` 调 gateway.submit_approval，计划步 actor.user 缺省硬编码 `OP-001`
  （场景人因仅 issue_by 签发链已数据化）；交办单引用行号 :509，当前代码硬编码实位于 :520/:523+:503
  （行号漂移）（`src/m6_flywheel/evaluator.py:503,520,523`）；v2 将"审批决断人来自场景数据"列为改进条款]

### 3.7 M7 Registry & Release

```text
register_asset(type: PROMPT/SKILL/TOOL/AGENT, descriptor) -> AssetId+Version
publish_asset(asset_id, review: ReviewRecord) -> status                    # 变更评审门禁
build_release(bundle_draft) -> ReleaseBundle
resolve_release(release_id) -> ResolvedRelease                             # 运行时装配
diff_release(a, b) -> ReleaseDiff                                          # 轨迹漂移对比用
```

- [v2Δ D-65: 资产存储形态——JSONL journal（`runtime/m7_registry/assets.jsonl` 追加写+重放重建），
  非 v1 §1 组件表所注 SQLite；chain 整数=版本链权威；内容 hash 未变的更新拒绝（版本号不空转）；
  `publish_asset` 是资产置 PUBLISHED 的唯一入口（`AssetStore._set_status` 模块私有，无公开 setter——
  SPEC-M7-03 无旁路代码级落位）（`src/m7_registry/assets.py:20-24,439-443`）；
  tests/CHANGELOG.md M7 登记 8——持久层形态横切口径见 §8]
- [v2Δ D-63: golden_scores 双层签名链+run_ref 解析序——`by_domain.signature`（M7 digest=sha256(canonical
  成绩载荷)）+ `attestation`（M6 侧 `m6_flywheel.attest` 对逐案例成绩摘要签名）；校验链=digest 重算→
  run_ref 归档装载→attestation 重算→从归档重推成绩逐块相等；`import_golden_scores` 唯一合法产出口
  （报告 release_id 必须等于打包 release，全部数字机械推导）；by_domain 四块=capability/category/
  catalog/red_line（目录映射来自 AgentContract behavior_catalog）；run_ref 解析序=绝对路径→release 目录
  内相对（digest 不含 run_ref 故发布改写不断链）→仓库根相对（`src/m7_registry/release.py:103-171`；
  `src/m6_flywheel/attest.py`）；tests/CHANGELOG.md M7 登记 5/6]
- [v2Δ D-64: 评审基线口径——candidate 总分（M6 报告 totals.score_100，缺则 pass_rate×100）≥ 现行已发布
  release 的 golden_scores；无现行 release 时基线=0；M7 只消费 M6 归档结果不自己跑分
  （`src/m7_registry/review.py` golden-not-below-current 前置）；tests/CHANGELOG.md M7 登记 7]
- [v2Δ D-62: AgentContract 绑定通道——冻结 ReleaseBundle（§2.12）无 agent 字段不可擅改→绑定落发布目录
  `agent_contract.yaml` 快照 + `manifest.yaml.agent_contract`（asset_id/version/sha256）；
  `bundle_draft` 必须携带 `agent_ref`（M7 自有子契约字段）缺失拒绝打包；AgentContract 资产=六能力域+
  12 约束+行为目录绑定 12 黄金种子（`assets/agent_contract_v1.yaml`；`releases/rel-0001/manifest.yaml:6-10`；
  `src/m7_registry/agent_contract.py:60-100`）；tests/CHANGELOG.md M7 登记 4]
- [v2Δ D-66: rel-0001 发布基线+assemble CLI——`PYTHONPATH=src python -m m7_registry.assemble --release-id
  rel-0001`（注册 20 项资产 PROMPT×2/SKILL×1/TOOL×16/AGENT×1 全部经评审流 publish_asset 发布→M6 实测
  12 种子全过 97.67/100→签名导入→六要素打包→门禁 5 项全过→只写一次发布）；已发布后 CLI 重入为只读
  复核模式；发布物含 `evaluation/`（report.json+cases.yaml）（`releases/rel-0001/manifest.yaml`；
  `src/m7_registry/assemble.py`）；tests/CHANGELOG.md M7 登记 10——资产基线登记见 ASSET-MANIFEST.md]
- [v2Δ D-60: 评审流/Release 状态机为 M7 自建表驱动——v1 M7 §5 DoD 引用的"01§5.4"不存在（v1 §5 只有
  5.1-5.3），本 v2 新增 §5.4/§5.5 两台状态机（见下）；tests/CHANGELOG.md M7 登记 1/2]

---

## 4. 冻结事件清单（EventBus 主题，28 主题封闭集）

```text
task.created | task.status_changed {from,to} | task.stage_gate {stage, verdict}
action.requested | action.policy_decided {decision} | action.waiting_approval
action.executing | action.completed {status}
artifact.state_changed {from,to}
alarm.raised | alarm.cleared | measurement.updated | grid.event
approval.requested | approval.granted | approval.denied
approval.timeout
trajectory.exported | golden.case_added | badcase.opened | skill.promoted
release.published
budget.exhausted {kind} | budget.warning {kind, remaining}
sim.injected {fault_type} | sim.completed
price.period_changed {from,to,price,boundary} | demand.month_rolled {from_month,to_month,frozen_peak_kw}
```

[v2Δ D-69: ADDENDUM §C 两事件落地核对——`price.period_changed` 在时段边界以 BUSINESS 时钟发布；
`demand.month_rolled` 在 15min 采样跨月时先发后重置；两主题已入 contracts.EventType 封闭集
（`src/contracts/enums.py:224-225`；`src/m5_simulation/price_clock.py:75-92,143-160`）；
`src/m1_core/loop.py:78-81` 列为 M1 环境事件源——事件主题总数 26→**28**]

**就近落主题扩展通道族（封闭目录下的扩展规则）**
[v2Δ D-06: v1 §4 无对应主题；oracle 在不扩目录的前提下以"就近主题+payload 细分/rejected 标记"落地
扩展语义。成文如下（`src/contracts/enums.py:185-225` 目录不变）]：

1. `budget.warning {kind: token, remaining, cost{…}}` 兼作**每轮模型成本上报**通道
   （SPEC-M1-10 要求 cost 字段但目录无 model.*/cost 主题；`src/m1_core/loop.py:687-689`；
   tests/CHANGELOG.md M1 登记 2）。
2. **非状态字段提交**（todos/plan/budget/context_manifest_hash 等）落
   `task.status_changed {from==to}` + mutation/version/updated_at，事件重建按同一 `apply_state_mutation`
   折叠（`src/m2_information/state_store.py:114-125`；tests/CHANGELOG.md M2 登记 2）。
3. **跨域审计**落 `action.policy_decided {decision: DENY}`：M2 workspace.write_cross/knowledge.mutate
   （`src/m2_information/workspace.py:227`）、M3 准入拒绝 `stage: admission`
   （`src/m3_action/gateway.py:268-275`；tests/CHANGELOG.md M2 登记 3、M3 登记 1）。
4. **调优侧/评审侧审计**落 `release.published {rejected:true, requested_status, reason}`（M6 评估单向
   守卫）与 `release.published {stage: review|asset-publish, from, to}`（M7 评审/发布迁移审计）
   （`src/m6_flywheel/evaluator.py:215-230`；`src/m7_registry/review.py`；tests/CHANGELOG.md
   M6 登记 4、M7 登记 2）。

**事件溯源规则**：`runtime/events/*.jsonl` 为追加写唯一权威流（按 stream 分片，缺省 `task-<task_id>`
一任务一分片 [v2Δ: `src/m2_information/event_log.py:50-53`]）；TaskState 可由事件流重建（重建协议：
`task.created` payload.state 为初始全量 → `task.status_changed`（accepted != false）逐条折叠 →
`contracts.TaskState.from_dict` 终校验 [v2Δ: 补 oracle 重建协议，`src/m2_information/event_log.py:20-32`]）；
任何模块不得仅凭消息队列内容变更权威状态。

---

## 5. 冻结状态机

迁移表的判据数据固化于 `tests/fixtures/frozen_state_machines.yaml`（§5.1–§5.3；M1/M2/M3 的表驱动实现
必须与本表 diff 为空）[v2Δ D-02: 补 fixture 定位——conditional 迁移单独登记于
conditional_transitions 节]。

### 5.1 任务状态机（10 态，合法迁移表）

```text
CREATED → RUNNING | CANCELLED
RUNNING → WAITING_INPUT | WAITING_APPROVAL | WAITING_EVENT | PAUSED | VERIFYING | FAILED | CANCELLED
WAITING_INPUT → RUNNING | CANCELLED
WAITING_APPROVAL → RUNNING | CANCELLED            # DENY → RUNNING（带拒绝观测）或 CANCELLED
WAITING_EVENT → RUNNING | CANCELLED
PAUSED → RUNNING | CANCELLED
VERIFYING → COMPLETED | RUNNING | FAILED          # 证据不足回 RUNNING
COMPLETED/FAILED/CANCELLED 为终态（只读）
```

**非法迁移必须抛 `IllegalTransitionError` 并落 `task.status_changed` 拒绝事件**
（拒绝事件同时带 `rejected:true` 与 `accepted:false` 双标记 [v2Δ D-09]）。

### 5.2 Action 生命周期

```text
REQUESTED → POLICY_DECIDED → (DENY→DENIED) | (ASK→WAITING_APPROVAL) | (ALLOW→EXECUTING)
WAITING_APPROVAL → EXECUTING(GRANT) | REJECTED(DENY/timeout)
EXECUTING → SUCCEEDED | FAILED
FAILED 且 reversible 且有 compensation → COMPENSATED（条件迁移，可选）
超时统一：WAITING_APPROVAL 超 approval_timeout_s → REJECTED(payload 带 timeout）
```

[v2Δ D-01: v1 原文 `DENY→DENYED` 系笔误，oracle 终态按 00§2 枚举落为 **DENIED**
（`src/contracts/enums.py:83`；与 M5 simulate 拒绝终态、M3 gateway 一致）；
tests/CHANGELOG.md S0 登记 1]
[v2Δ D-02: v1 把 `FAILED→COMPENSATED` 与无条件迁移并列；oracle 以 **conditional_transitions** 标注
（条件=reversible 且有 compensation），不进无条件迁移表（`tests/fixtures/frozen_state_machines.yaml`
conditional_transitions 节；tests/CHANGELOG.md S0 登记 2）]
[v2Δ D-24: 准入失败不进生命周期——契约/注册/披露/schema/REAL 路由拒绝发生在 REQUESTED 之前→状态
REJECTED、不落 `action.requested`（不进事件主链）、审计落 `action.policy_decided{decision:DENY,
stage:admission}`（同 §3.3）]

### 5.3 Artifact 状态机

```text
DRAFT → VALIDATING → READY → PUBLISHED → ARCHIVED
VALIDATING → REJECTED → DRAFT(修订)
PUBLISHED 被新版本替代 → ARCHIVED(supersedes 链)
DRAFT/READY 可 → DELETED（软删，留记录）
```

### 5.4 评审流状态机（M7 Review，6 态）[v2Δ D-60 新增：v1 M7 §5 DoD 引用的"01§5.4"不存在，oracle 为
M7 自建表驱动，v2 转正入契约]

```text
PROPOSED → EVALUATING | REJECTED | WITHDRAWN
EVALUATING → APPROVED | REJECTED | WITHDRAWN
APPROVED → PUBLISHED
PUBLISHED/REJECTED/WITHDRAWN 为终态（只读）
```

（`src/m7_registry/review.py:54-60` REVIEW_TRANSITIONS；与 `tests/fixtures/m7_state_machines.yaml`
diff 为空（EVAL-M7-TABLE-P）；提案=motivation+impact+badcases，评审基线口径见 §3.7 D-64；
评审审计落 `release.published{stage:review,…}`）

### 5.5 Release 状态机（M7，4 态）[v2Δ D-60 新增：同上]

```text
DRAFT → GATED → PUBLISHED
PUBLISHED → SUPERSEDED（仅此一迁）
SUPERSEDED 为终态（只读）
```

（`src/m7_registry/publish.py:130-138` RELEASE_TRANSITIONS；发布物只写一次，发布后任何文件改写拒绝
（ImmutableReleaseError）；评审/发布审计落 `release.published{stage:asset-publish,…}`）

---

## 6. Eval 重生成协议（Spec↔Eval 同构）

1. 每条行为规格条款 `SPEC-<模块>-<序号>` 必须映射至少一个 EVAL 用例：正例 `EVAL-<模块>-<序号>-P*`，可测负例 `EVAL-<模块>-<序号>-N*`（若条款是禁止类，负例=尝试违反必须被拒）。
2. EVAL 用例文件落 `tests/test_m<模块>.yaml`（数据驱动，runner 读文件执行，不硬编码）。
3. SPEC 变更时（含措辞导致行为语义变化），受影响 EVAL 必须重生成并在 `tests/CHANGELOG.md` 登记 `spec_hash → eval_hash` 对；无登记的 EVAL 与 SPEC 不一致视为验收失败。
   spec_hash 口径：`spec_ref`（字符串或列表）按序拼接文件字节取 sha256（`run_evals.py:819-821`）[v2Δ: 补机械口径]。
4. 重生成允许使用 LLM 辅助，但产物必须人工/规则复核落盘（生成过程不进黄金集）。
5. 全部 EVAL 合计通过率 100%（正例通过 + 负例正确拒绝）才达到模块 DoD。

> v2 基线核验（本会话实跑）：`python run_evals.py --module all` →
> `EVALS mode=all isolation=OK modules=8/8 pending=0 cases=180/180 failed=0 skipped=0 result=PASS`。

---

## 7. 契约变更流程（冻结的解冻唯一通道）

1. 提交 `contracts/CHANGE-PROPOSAL.md`（动机+影响面+新旧对照）。
2. 七模块代表评审（缺席视为反对）。
3. 通过后：本文件升版（语义化版本 minor/patch），全部依赖模块同步适配，EVAL 重生成，回归全绿。
4. 禁止跳过评审直接改代码化契约 `src/contracts/`（`src/contracts/__init__.py` 模块 docstring 同此纪律）。

---

## 8. 横切约定

- **trace_id 贯穿**：Task→Action→Event→Artifact→Trajectory 全链同 trace_id；缺 trace_id 的事件在写入时被拒（EventRecord.from_dict 强制）。trace_id 从 task 派生（`trace-<task_id>`）——ActionRequest 冻结结构无 trace 字段 [v2Δ D-30: tests/CHANGELOG.md M3 登记 9]。
- **时间戳**：一律 UTC ISO-8601；数据文件未加引号时间戳按 UTC `datetime` 双形态放行（§2 约定 2，非 UTC 拒绝）[v2Δ D-04]；业务时间（峰谷）用 M5 clock 的 BUSINESS 读数，不得用墙钟直接判价（唯一合法真实时钟位=`m5_simulation/clock.py` [v2Δ D-44]）。
- **持久层形态**：M2=SQLite（`StateStore(dsn)` 可配连接串，postgres 预留 NotImplementedError）；M3/M7=JSONL journal（追加写+重放重建）[v2Δ D-65: v1 只写 SQLite 单文件起步；tests/CHANGELOG.md M7 登记 8]。
- **语言**：代码标识符英文；用户可见文本中文；规程引用一律用规则 ID（如 `PHYS-TX-LOAD`），不引用原文行号。
- **LLM 抽象**：模型调用统一走 `m1_core/model_client`（provider 适配层，支持本地/云端切换），禁止业务模块直连 SDK；模型端点安全边界（SSRF fail-closed，见 §3.1 D-15）为横切安全条款 [v2Δ D-15]。
- **仿真即默认**：EVAL 与黄金集一律在 SIMULATION 模式跑；REAL 模式仅接线测试（负向断言）使用（门禁三重见 §3.3 D-31）。
- **事件目录扩展纪律**：28 主题封闭集；新增语义优先"就近主题+payload 细分/rejected 标记"（§4 扩展通道族），扩目录必须走 §7 契约变更流程 [v2Δ D-06]。

---

## 9. v1→v2 条款追溯（不删除的替代条款）

v1 未实现却已被 oracle 替代的表述一律保留追溯，不直接删除：

| v1 条目 | v1 原文口径 | oracle 现行口径 | 处置 |
| --- | --- | --- | --- |
| README §0 "11 数据结构" | 11 个冻结数据结构 | 12 个（§2.1–§2.12） | [v2Δ 已替代] D-05（v1 README 仍原样保留于 specs/，本表存照） |
| §1 目录树 `tools/ 每个 action family 一个` | 按 action family 分模块 | 一动作一模块（16 个，"."→"__"） | [v2Δ 已替代] D-27 |
| §1 目录树 `golden/ cases/*.yaml` | cases/ 子目录 | golden/dev/ 平铺（兼容 cases/） | [v2Δ 已替代] D-52 |
| §1 部署形态 "SQLite 单文件起步" | 统一 SQLite | M2=SQLite；M3/M7=JSONL journal | [v2Δ 已替代] D-65 |
| §2.1/§2.5/§2.6 等 `string(ulid)` | 强制 ULID 形态 | check_id=非空字符串（双形态） | [v2Δ 已替代] D-03 |
| §3.2 `write_memory -> MemoryId \| REJECTED` | 联合类型语义 | 哨兵字符串 `"REJECTED"` | [v2Δ 已替代] D-20 |
| §3.2 `save_artifact -> ArtifactId` | 返回 id | 返回 ArtifactRecord | [v2Δ 已替代]（oracle `src/m2_information/__init__.py:353`） |
| §3.6 `export_trajectory(trace_id)` | 单形参 | 增 release_id 形参（缺省 "sim"） | [v2Δ 已替代] D-57 |
| §5.2 `DENY→DENYED` | DENYED 拼写 | DENIED（00§2 枚举） | [v2Δ 已替代] D-01 |
| §5.2 `FAILED→COMPENSATED` 无条件迁移 | 无条件迁移表 | conditional_transitions（reversible 且有 compensation） | [v2Δ 已替代] D-02 |
| （M7 §5 DoD 引用）"01§5.4" | v1 不存在的引用节 | 本 v2 §5.4/§5.5 转正 | [v2Δ 已替代] D-60 |
| §8 "时间戳一律 UTC ISO-8601"（单形态） | 仅字符串 | 字符串+UTC datetime 双形态 | [v2Δ 已替代] D-04 |
