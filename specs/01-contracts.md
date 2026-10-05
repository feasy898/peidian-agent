# 01 · 模块划分与模块间冻结契约（v1.0）

> 本文件定义 7 个模块的职责边界与模块间**冻结契约**（Frozen Contracts）：数据结构、调用接口、事件、状态机。
> 冻结含义：开发期间任何模块不得单方面变更本文件定义的接口；变更必须走契约变更流程（见 §7）并全员同步。
> 全部数据结构以 YAML/JSON 表达，字段名与枚举值大小写敏感。

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

**部署形态**：单进程多模块（进程内调用优先）；M3 对外执行与 M5 仿真通过适配器隔离。数据库：SQLite 单文件起步（`runtime/state.db`），事件流追加写 `runtime/events/*.jsonl`。

**目录树（开发约定）**：

```text
park-power-agent/
├── ontology/            # 本体 YAML（00-ontology.md 的机器可读版）
│   ├── objects.yaml  relations.yaml  actions.yaml  rules.yaml  enums.yaml  seed.yaml
├── regulations/         # 虚拟规程（REG-SAFE.yaml / REG-COMM.yaml / REG-TECH.yaml）
├── skills/              # Skill 资产（每个 skill 一个目录：SKILL.yaml+正文+脚本）
├── prompts/             # Prompt 资产（版本化）
├── tools/               # 工具适配器（每个 action family 一个）
├── src/
│   ├── m1_core/  m2_information/  m3_action/  m4_semantic/
│   ├── m5_simulation/  m6_flywheel/  m7_registry/
│   └── contracts/      # 本文件数据结构的代码化（pydantic/等价物）
├── golden/              # 黄金集（cases/*.yaml）
├── scenarios/           # 开发用仿真场景（dev-*.yaml）
├── runtime/             # 运行期产物（state.db / events / workspaces / artifacts，git ignore）
└── tests/               # EVAL 用例（每个模块 tests/test_m*.py，从 spec 机械生成）
```

---

## 2. 冻结数据结构（Frozen Data Structures）

全部结构登记于 `src/contracts/`（代码化+运行时校验）。字段缺省必填=是，除非标注 optional。

### 2.1 ActionRequest（M1→M3）

```yaml
ActionRequest:
  action_id: string(ulid)          # 唯一
  task_id: string                  # 归属任务
  turn: int                        # 任务内轮次
  capability: string               # 格式 "动作ID@版本"，如 "query.measurement@v1"
  actor:
    user: string                   # 发起用户 id（Operator）
    agent: string                  # agent id@版本
    on_behalf_of: string optional  # 委托链（L3+ 才使用）
  purpose: string                  # 一句话目的（进审计）
  arguments: object                # 动作参数（按 capability schema 校验）
  risk: {level: enum(risk_level), reversible: bool, compensation: string optional}
  idempotency_key: string          # 同 key 重复请求必须幂等
  requested_at: timestamp
```

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

**Evidence 三态规则**：`SUCCEEDED` 必须三者齐全；`EXECUTING` 允许 intended+issued；观察结果必须来自环境回读，不得由执行器自报。

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

### 2.4 ContextManifest（M2→M1，每轮生成）

```yaml
ContextManifest:
  task_id: string
  turn: int
  sources: list[{name, type(enum), tokens, priority, origin}]
  # type 枚举：SYSTEM_POLICY/AGENT_CONTRACT/TENANT_RULE/RUNTIME_REMINDER/SKILL/
  #           TOOL_DESCRIPTOR/GOAL_STEERING/PLAN_TODO/RECENT_INTERACTION/
  #           COMPACTED_HISTORY/RETRIEVED_MEMORY/RETRIEVED_KNOWLEDGE/ONTOLOGY_VIEW/WORKSPACE_REF
  total_tokens: int
  budget_remaining: int
  compiled_at: timestamp
  hash: string                     # 同 task 状态+同轮输入 → 必须同 hash（确定性）
```

### 2.5 EventRecord（全系统事件，追加写 `runtime/events/*.jsonl`）

```yaml
EventRecord:
  event_id: string(ulid)
  type: enum(event_type)           # 见 §4 事件清单
  subject: string                  # task_id/action_id/artifact_id/alarm_id…
  payload: object
  occurred_at: timestamp
  trace_id: string
  producer: string                 # 模块 id
```

### 2.6 ArtifactRecord（M2 持有）

```yaml
ArtifactRecord:
  artifact_id: string(ulid)
  type: enum(REPORT/WORK_ORDER/SWITCH_ORDER/INSPECTION_RECORD/ANALYSIS_RESULT/DATASET)
  status: enum(artifact_status)
  schema_id: string                # 内容 schema 版本，如 "report.daily@v1"
  content_ref: string              # 文件路径（workspace 内相对路径）
  created_by: {task_id, action_id}
  validation: {passed: bool, checks: list[{name, passed, detail}]} optional
  version: int
  supersedes: string optional      # 替代链
```

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

### 2.8 ScenarioSpec（M5 场景规格，十字段组）

```yaml
ScenarioSpec:
  identity: {scenario_id, version, owner, tags[]}
  sut: {target: enum(AGENT/MODULE), module optional, agent_release optional}
  environment:                     # 环境初始化
    park_instance: string          # PARK-001 / PARK-002
    clock_start: timestamp
    speed: float                   # 仿真时间流速
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
    seed: string
```

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
  # RUBRIC: 规程/行为判据（引用规则 ID 或行为目录条目 ID）
  source: enum(HANDWRITTEN/TRAJECTORY_MINED/REGENERATED)
  excluded_from: list[string]      # 标注 "holdout" 的案例禁止进开发集
```

### 2.11 TrajectoryRecord（M6 采集）

```yaml
TrajectoryRecord:
  trace_id: string
  task_id: string
  release_id: string
  steps: list[{seq, type(MODEL_CALL/TOOL_CALL/STATE_CHANGE/APPROVAL), ref, summary, latency_ms, cost}]
  outcome: {status, evidence_summary, completion_level(1-5)}
  cost_total: {tokens, currency}
  quality_flags: list[string]      # 如 LATEX_STUCK/LOOP/REFUSAL_MISSING
```

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
  contract_version: string         # 本文件版本
```

---

## 3. 冻结调用接口（Frozen APIs）

进程内接口以函数签名表达（语言无关描述；HTTP/gRPC 可后置）。

### 3.1 M1 Agent Core

```text
run_task(user_input: string, task_ctx: TaskContext) -> TaskState
  # 主入口：创建/恢复任务，驱动 Agent Loop 直至 WAITING_* 或终态
resume_task(task_id: string, event: ResumeEvent) -> TaskState
  # ResumeEvent ∈ {USER_INPUT, APPROVAL_GRANTED, APPROVAL_DENIED, ENV_EVENT, TIMEOUT}
request_completion(task_id: string, claim: CompletionClaim) -> CompletionVerdict
  # 模型申请完成；M1 用证据判定，verdict ∈ {ACCEPTED, NEED_MORE_EVIDENCE, REJECTED}
```

### 3.2 M2 Information

```text
compile_context(task_id: string, turn: int) -> ContextManifest
commit_state(task_id: string, mutation: StateMutation) -> TaskState     # 版本+1，事件落盘
snapshot(task_id: string) -> Checkpoint
restore(checkpoint_id: string) -> TaskState
write_memory(task_id, content, type: memory_type, provenance) -> MemoryId | REJECTED
retrieve_memory(query, task_id) -> list[MemoryEntry]
disclose_skill(skill_id, level: 0|1|2) -> SkillView                      # 三级披露
save_artifact(record: ArtifactRecord) -> ArtifactId
validate_artifact(artifact_id) -> ValidationReport
```

### 3.3 M3 Action Gateway

```text
register_capability(capability: CapabilityDescriptor) -> CapabilityId
execute_action(request: ActionRequest) -> ActionResult                    # 同步边界
  # 内部路由：mode ∈ {REAL, SIMULATION}；SIMULATION → M5.simulate()
query_policy(capability, actor, context) -> PolicyDecision(ALLOW/ASK/DENY)
submit_approval(action_id, decision: GRANT/DENY, approver) -> ActionResult
```

**幂等规则**：同 `idempotency_key` 的重复请求返回首个结果（含原 action_id），不重复执行。

### 3.4 M4 Semantic

```text
load_ontology(version: string) -> LoadedOntology
resolve_entities(text: string) -> list[ResolvedEntity]                    # 实体链接
query_graph(pattern: GraphPattern, hops ≤ 3) -> list[GraphNode/Edge]
concept_view(entity_ids: list[string]) -> OntologyView                    # 注入 Context 用
coverage_report(window) -> {hits, total, ratio, missing[]}
```

### 3.5 M5 Simulation

```text
load_scenario(spec: ScenarioSpec) -> SimEnv
step(env: SimEnv, action: SimAction | ENV_TICK) -> (SimEnv, Observation, SimEvents[])
simulate(action: ActionRequest, env: SimEnv) -> (ActionResult, SimEnv)    # M3 仿真路由目标
persona_step(persona, history) -> UserUtterance                            # 用户模拟器
clock(mode: BUSINESS/SIM_LOGICAL/MONOTONIC/WALL) -> ClockReading           # 四类时间
inject(env, fault: FaultSpec) -> SimEnv                                    # 故障注入
run_scenario(spec) -> SimRunResult                                         # 场景引擎一站式
```

### 3.6 M6 Flywheel

```text
export_trajectory(trace_id) -> TrajectoryRecord
add_golden_case(case: GoldenCase) -> CaseId
run_golden(release_id, golden_set_version) -> {pass_rate, failures[]}
open_badcase(evidence: BadcaseEvidence) -> BadcaseId
promote_to_skill(badcase_id, skill_draft: SkillDescriptor) -> SkillId     # 受控自进化入口（走 M7 评审）
```

### 3.7 M7 Registry

```text
register_asset(type: PROMPT/SKILL/TOOL/AGENT, descriptor) -> AssetId+Version
publish_asset(asset_id, review: ReviewRecord) -> status                    # 变更评审门禁
build_release(bundle_draft) -> ReleaseBundle
resolve_release(release_id) -> ResolvedRelease                             # 运行时装配
diff_release(a, b) -> ReleaseDiff                                          # 轨迹漂移对比用
```

---

## 4. 冻结事件清单（EventBus 主题）

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
```

**事件溯源规则**：`runtime/events/*.jsonl` 为追加写唯一权威流；TaskState 可由事件流重建；任何模块不得仅凭消息队列内容变更权威状态。

---

## 5. 冻结状态机

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

**非法迁移必须抛 `IllegalTransitionError` 并落 `task.status_changed` 拒绝事件。**

### 5.2 Action 生命周期

```text
REQUESTED → POLICY_DECIDED → (DENY→DENYED) | (ASK→WAITING_APPROVAL) | (ALLOW→EXECUTING)
WAITING_APPROVAL → EXECUTING(GRANT) | REJECTED(DENY/timeout)
EXECUTING → SUCCEEDED | FAILED
FAILED 且 reversible 且有 compensation → COMPENSATED（可选）
超时统一：WAITING_APPROVAL 超 approval_timeout_s → REJECTED(payload 带 timeout）
```

### 5.3 Artifact 状态机

```text
DRAFT → VALIDATING → READY → PUBLISHED → ARCHIVED
VALIDATING → REJECTED → DRAFT(修订)
PUBLISHED 被新版本替代 → ARCHIVED(supersedes 链)
DRAFT/READY 可 → DELETED（软删，留记录）
```

---

## 6. Eval 重生成协议（Spec↔Eval 同构）

1. 每条行为规格条款 `SPEC-<模块>-<序号>` 必须映射至少一个 EVAL 用例：正例 `EVAL-<模块>-<序号>-P*`，可测负例 `EVAL-<模块>-<序号>-N*`（若条款是禁止类，负例=尝试违反必须被拒）。
2. EVAL 用例文件落 `tests/test_m<模块>.yaml`（数据驱动，runner 读文件执行，不硬编码）。
3. SPEC 变更时（含措辞导致行为语义变化），受影响 EVAL 必须重生成并在 `tests/CHANGELOG.md` 登记 `spec_hash → eval_hash` 对；无登记的 EVAL 与 SPEC 不一致视为验收失败。
4. 重生成允许使用 LLM 辅助，但产物必须人工/规则复核落盘（生成过程不进黄金集）。
5. 全部 EVAL 合计通过率 100%（正例通过 + 负例正确拒绝）才达到模块 DoD。

---

## 7. 契约变更流程（冻结的解冻唯一通道）

1. 提交 `contracts/CHANGE-PROPOSAL.md`（动机+影响面+新旧对照）。
2. 七模块代表评审（缺席视为反对）。
3. 通过后：本文件升版（语义化版本 minor/patch），全部依赖模块同步适配，EVAL 重生成，回归全绿。
4. 禁止跳过评审直接改代码化契约 `src/contracts/`。

---

## 8. 横切约定

- **trace_id 贯穿**：Task→Action→Event→Artifact→Trajectory 全链同 trace_id；缺 trace_id 的事件在写入时被拒。
- **时间戳**：一律 UTC ISO-8601；业务时间（峰谷）用 M5 clock 的 BUSINESS 读数，不得用墙钟直接判价。
- **语言**：代码标识符英文；用户可见文本中文；规程引用一律用规则 ID（如 `PHYS-TX-LOAD`），不引用原文行号。
- **LLM 抽象**：模型调用统一走 `m1_core/model_client`（provider 适配层，支持本地/云端切换），禁止业务模块直连 SDK。
- **仿真即默认**：EVAL 与黄金集一律在 SIMULATION 模式跑；REAL 模式仅接线测试（负向断言）使用。

