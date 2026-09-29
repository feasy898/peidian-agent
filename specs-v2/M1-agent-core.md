# M1 · Agent Core（执行内核）Spec v2

> **v2 定位（资产工程反提）**：本文件由 v1 `specs/M1-agent-core.md` 按 **oracle（唯一事实源=现行实现全体）**
> 逐条重写，对照面 = `src/m1_core/` 全部源码 + `tools/` 适配器（经 M3 registry 间接消费）+
> `tests/test_m1.yaml` 现行 20 用例。v1 原文保留于 `specs/` 不改写。
> M1 模块偏差（D-07..D-16）权威线索 = `tests/CHANGELOG.md`（M1 首条登记 / M1 复核修订 /
> 2026-09-29 提交门禁安全修复）与 commit 588da80、9062518、400a5a2；
> 正式处置记录 = `specs-v2/deviations/M1.md`。
> 交叉引用：01 v2（§2.3 TaskState、§3.1 冻结 API 与 D-xx 标记、§4 事件目录 + D-06 扩展通道族、
> §5.1 任务状态机、§8 横切约定）。
> **oracle 健康基线（本会话实跑，2026-09-29）**：`python run_evals.py --module all` →
> `EVALS mode=all isolation=OK modules=8/8 pending=0 cases=180/180 failed=0 skipped=0 result=PASS`；
> `python run_evals.py --module m1` → `cases=20/20 failed=0 result=PASS`。

<!--
v1→v2 条款映射（v2 编号重排表；每条 v2 条款内另带 [v2Δ] 依据标记）：
  v1 SPEC-M1-01 → v2 SPEC-M1-01（轮驱动口径按 oracle 收紧；轮号台账拆至 v2-11）
  v1 SPEC-M1-02 → v2 SPEC-M1-02（吸收 D-09：拒绝事件双标记 + 完成门禁）
  v1 SPEC-M1-03 → v2 SPEC-M1-03（补 state_version 审计）
  v1 SPEC-M1-04 → v2 SPEC-M1-04（吸收 D-10 匹配双口径；补 task.stage_gate 事件）
  v1 SPEC-M1-05 → v2 SPEC-M1-05（吸收 D-12 四口径 + D-13 的 PAUSED 恢复重查）
  v1 SPEC-M1-06 → v2 SPEC-M1-06（吸收 D-09 完成门禁落位；补 REJECTED/伪造引用三值）
  v1 SPEC-M1-07 → v2 SPEC-M1-07（环境事件主题集对齐 01 v2 §4 28 主题）
  v1 SPEC-M1-08 → v2 SPEC-M1-08（补异常收容与安全指令成文）
  v1 SPEC-M1-09 → v2 SPEC-M1-09（吸收 D-13 状态-种类矩阵）
  v1 SPEC-M1-10 → v2 SPEC-M1-10（吸收 D-08/D-06 成本上报通道）
  v1 无条款（五阶段回放校验） → v2 SPEC-M1-11（新增；吸收 D-07 + D-14）
  v1 无条款（产物自动落位）     → v2 SPEC-M1-12（新增；吸收 D-11）
  v1 §2 组件 model_client（无条款） → v2 SPEC-M1-13 + SPEC-M1-14（新增；吸收 D-15）
  v1 无条款（Act 动作请求构造）     → v2 SPEC-M1-15（新增）
  v1 无（TaskContext 缺省执行者）   → 显式排除（D-16；成文于 §2 组件注记，不设行为条款）
D-16 为显式排除项（构造入参可覆盖的缺省值，无行为锁定），不设独立 SPEC 条款。
-->

## 1. 职责边界

**做**：Agent Loop 五阶段循环（Prepare/Model/Act/Observe/Verify）与轮驱动；任务状态机迁移守卫
（硬编码表 + 冻结 fixture 双写校验）；Planning/Todo 外部化管理（阶段导航、DONE 粘滞、gap 注入与解除）；
阶段门禁三条件评估；预算检查点四口径；完成申请判定分离（三值裁定）；Act 阶段 ActionRequest 构造与
M3 网关调用；Observe 证据落盘与产物自动落位策略；恢复语义（ResumeEvent 状态-种类矩阵 + 审批决断
路由 + Checkpoint 幂等续跑）；LoopTrace 运行期审计件与五阶段回放校验；中间件链；LLM 统一客户端
（mock 离线确定性 / openai_like 适配 + 模型端点 SSRF 安全边界）。

**不做**：上下文编译与权威状态持久（M2，`commit_state`/`compile_context` 由 M2 提供）；
动作策略判定/执行/审批队列/幂等 journal（M3）；本体语义解析（M4，仅经 M2 构造点的
`rule_id_checker` 注入间接联动，ADDENDUM §B）；电价判价（01 v2 §8：判价只允许 M5 BUSINESS 时钟；
M1 的 `price_window` 预算口径只做时段窗口比较，比较基准为注入 now）；委派子 agent（L3 后扩展，
本期仅预留 `TaskState.subtasks` 字段与 `DelegationMiddleware` no-op 位）。

**状态纪律**：本模块不持有任何**权威**任务数据（全部外置 M2）；名下唯一的持久文件是 LoopTrace
运行期**审计件** `runtime/<root>/m1_core/loop/task-<task_id>.jsonl`（追加写，仅作五阶段序审计，
非权威状态）[v2Δ D-07: v1 写"不持有任何持久数据"，oracle 实有该审计件——见 SPEC-M1-11]。

## 2. 内部组件（按 oracle 实际目录树）

```text
m1_core/
├── __init__.py        # 门面导出（冻结 API + 状态机/预算/门禁/完成/中间件/客户端/trace 全部公共符号）
├── loop.py            # AgentCore 门面：run_task / resume_task / request_completion（冻结 API 01 v2 §3.1）
│                      #   + run_loop 五阶段驱动 + Prepare/Model/Act/Observe/Verify 细分
├── state_machine.py   # 10 态迁移守卫：TASK_TRANSITIONS 硬编码 vs frozen_state_machines.yaml 双写 diff 空
├── planner.py         # 计划/Todo 纯数据操作（阶段导航、DONE 粘滞、gap todos 构造与幂等注入）
├── gates.py           # 阶段门禁三条件（产物齐全/预算余量/无阻断告警）+ GATE_PASS_STATUSES
├── completion.py      # 完成验证器（三值裁定、三态证据核对、伪造引用识别、claim_fingerprint）
├── budget.py          # 预算检查点（token/action/deadline/price_window 四口径；now 一律入参）
├── middleware.py      # 链式中间件（日志/安全注入/委派预留位；注册序执行、异常收容）
├── model_client.py    # LLM 统一客户端（mock 脚本回放 / openai_like 适配 + SSRF 边界 + 重试/超时分类）
├── trace.py           # LoopTrace 追加写审计件 + validate_replay 五阶段回放校验（纯函数）
├── clocking.py        # 时间助手（parse_iso/iso_z/normalize_ts；now_iso = m1_core 唯一真实时钟读取位）
├── ids.py             # 标识符（new_seq_id 进程内确定性递增；new_ulid 复用 m2_information.ids）
└── eval_plugin.py     # EVAL 执行器插件（7 执行器：m1.scenario/replay/table/budget/middleware/model/persona_llm）
```

> [v2Δ: v1 §2 树缺 `clocking.py`/`ids.py`/`eval_plugin.py`/`__init__.py` 四文件，且 `middleware.py`
> 描述少"异常收容"；按 oracle 补齐。]
> [v2Δ 显式排除 D-16: `TaskContext` 缺省 `actor_user="OP-001"`、`actor_agent="park-agent@v1"`
> 为构造入参可覆盖的硬编码缺省值（`src/m1_core/loop.py:106-107`），无行为锁定，不设行为条款
> （偏差台账登记；01 v2 §3.1 同步成文）。初稿证据行号 `:100-101` 已按当前文件漂移修正为 `:106-107`。]
> **tools/ 关系**：M1 不直接依赖 `tools/` 适配器（一动作一模块，`tools/_base.py` 公共约定，
> 01 v2 §3.3 D-27）；Act 阶段经 M3 网关执行，模型工具清单与风险缺省值经
> `gateway.registry.descriptors()` / `registry.get/by_action` 描述符获得（`src/m1_core/loop.py:596-601,704-707`）。

## 3. 行为规格（SPEC 条款 v2）

### SPEC-M1-01 Loop 五阶段顺序与轮驱动

- 每轮严格按 `PREPARE → MODEL → ACT → OBSERVE → VERIFY` 顺序执行（`PHASE_ORDER`，
  `src/m1_core/trace.py:28`；`_run_turn` 各阶段 dispatch 序，`src/m1_core/loop.py:348-441`）。
- Prepare 中断（预算耗尽）时本轮止于 PREPARE，不进入 Model（`src/m1_core/loop.py:351-365`），
  trace 记 `aborted_prepare` 轮。
- 轮驱动：终态直接返回；非 RUNNING 的等待/暂停态直接调 `run_loop` 抛 `LoopNotResumableError`
  （必须经 `resume_task` 携带 ResumeEvent）；CREATED 先自动迁 RUNNING 再循环；
  轮末状态离开 RUNNING 即退出循环；`max_turns` 用尽 → `WAITING_INPUT`；
  仅首轮携带 `user_input`，后续轮为空。
- 证据：`src/m1_core/loop.py:293-335`（`run_loop`）、`:305-312`（CREATED/等待态守卫）、
  `:324-329`（max_turns→WAITING_INPUT）、`:338-441`（`_run_turn`）。
- [v2Δ: v1-01 只写五阶段序与 Prepare 中断；oracle 补齐轮驱动口径（max_turns→WAITING_INPUT、
  等待态必须经 resume_task、CREATED 自动 RUNNING），依据 tests/CHANGELOG.md M1 登记 1/9 与
  EVAL-M1-01-P / EVAL-M1-05-N。]

### SPEC-M1-02 任务状态机迁移守卫

- 所有迁移走 `TASK_TRANSITIONS`（10 态硬编码表，`src/m1_core/state_machine.py:44-58`）；该表与
  `tests/fixtures/frozen_state_machines.yaml` machines.task 双写，`table_diff` 必须为空
  （`:121-152`；本会话实测 `assert_table_consistency()` → `{'states': 10, 'diff': {}}`）。
- 非法迁移：落 `task.status_changed` 拒绝事件（payload = `{from, to, rejected: true, accepted: false,
  reason}`，`src/m1_core/state_machine.py:160-168,203-208`）并抛 `IllegalTransitionError`，
  任务保持原状态（守卫在提交前拦截）。
- `to_status == current` 视为非状态字段提交（todos/plan/budget/context_manifest_hash 等），
  直接委托 M2 `commit_state` 折叠（`:199-202`；对应 01 v2 §4 D-06 扩展通道 2）。
- 终态 COMPLETED 门禁：无已接受 CompletionClaim 的 COMPLETED 迁移抛 `CompletionRequiredError`
  （`IllegalTransitionError` 子类）并落拒绝事件（`:85-97,209-214`；门禁谓词
  `is_completable` 由 AgentCore 注入=完成判定登记表，`src/m1_core/loop.py:171-176`）。
- 合法迁移委托 M2 `commit_state`（版本+1、事件落盘），本模块不持有任务数据（`:215-217`）。
- 证据：`src/m1_core/state_machine.py:44-58,85-97,99-107,160-168,194-217`。
- [v2Δ D-09: 拒绝事件双标记（`rejected:true` M1 口径 + `accepted:false` M2 重建跳过口径）与
  完成门禁落位（is_completable + CompletionRequiredError），依据 tests/CHANGELOG.md M1 登记 3；
  v1-02 只写 `rejected: true`。]

### SPEC-M1-03 权威状态驱动

- Loop 每轮 Prepare 从 M2 读取 TaskState 驱动（`src/m1_core/loop.py:349,368`）；ACT 前、VERIFY 各
  步骤前后均重读权威状态（`:397,448,457,500,527`）；状态只能经 M2 `commit_state` 变更
  （`:783-786`）；对话历史/模型文本不构成状态依据。
- PREPARE 阶段记录携带权威状态版本号 `state_version`（`:362-363,369-376`；EVAL 断言
  `prepare_state_versions`，`src/m1_core/eval_plugin.py:405-411`）。
- 证据：`src/m1_core/loop.py:349,368,397,783-786`。
- [v2Δ: 补 state_version 轮级审计口径（EVAL-M1-01-P）；v1-03 语义保留。]

### SPEC-M1-04 阶段门禁三条件

- 每轮 Verify 评估当前 plan 步出口门禁（`src/m1_core/loop.py:456-491`），三条件：
  1. **产物齐全**：`plan.artifacts_expected` 每项命中（**artifact_id 精确匹配或 schema_id 匹配**
     双口径，`src/m1_core/loop.py:814-822`）且 status ∈ `GATE_PASS_STATUSES = ("READY", "PUBLISHED")`
     （`src/m1_core/gates.py:29,101-112`；REJECTED/DRAFT 不算过门）；
  2. **预算余量**：token/action 余量 ≥ floor（缺省 1）（`src/m1_core/gates.py:114-118`）；
  3. **无阻断告警**：任务事件流中 `alarm.raised`（payload.level ∈ blocking_levels，缺省 `("P0",)`）
     未被后续 `alarm.cleared` 抵消（`src/m1_core/gates.py:59-75,120`）。
- 三者齐 → PASSED：发 `task.stage_gate {stage, verdict: PASSED, …}` 事件（`src/m1_core/loop.py:464-470`）；
  既有 gap todos（`gap-<stage>-*` / `gap-completion-*`）置 DONE；`next_stage` 前进并提交
  （`:471-484`；`src/m1_core/planner.py:79-89`）。
- 不满足 → BLOCKED：同样发 `task.stage_gate` 事件，`merge_gap_todos` 幂等注入 gap todos
  （同 id 不重复）（`src/m1_core/loop.py:485-491`；`src/m1_core/planner.py:206-214`）。
- 当前阶段不在 plan（空 plan/阶段名漂移）视为无门禁可评、直接通过（`src/m1_core/gates.py:96-99`）。
- 证据：`src/m1_core/gates.py:29,59-75,78-145`；`src/m1_core/loop.py:456-491,814-822`。
- [v2Δ D-10: 产物匹配双口径（artifact_id **或** schema_id——计划先于产物存在、ULID 无法预知），
  依据 tests/CHANGELOG.md M1 登记 4。]
- [v2Δ: 补 `task.stage_gate` 事件与 gap 解除口径（v1-04 只写"停留当前阶段 + gap 清单写入 todos"）。]

### SPEC-M1-05 预算检查点四口径

- 每轮 Prepare 检查预算租约（`src/m1_core/loop.py:351`）；超限类别
  `BUDGET_KINDS = ("token", "action", "deadline", "price_window")`（`src/m1_core/budget.py:34`）：
  - token/action：`used ≥ max` 即租约耗尽（`src/m1_core/budget.py:85-88`）；
  - deadline：`now > deadline`（`:89-92`）；
  - price_window：`now ∉ [from, to]`（含边界闭区间，`:93-102`）。
- 任一超限 → 发 `budget.exhausted {kind, detail, turn, exceeded_kinds}`（`src/m1_core/loop.py:354-357`）
  + 迁 PAUSED（`:358-359`）+ 本轮不进 Model。
- 比较基准一律为**注入的 now**（`AgentCore(now_fn=…)`，`src/m1_core/loop.py:156`；
  `check_budget(budget, now=…)`，`src/m1_core/budget.py:74`）；`budget.py`/`loop.py` 零墙钟；
  m1_core 内唯一真实时钟读取位 = `clocking.now_iso()`（仅生产缺省，`src/m1_core/clocking.py:38-45`）。
- PAUSED 恢复：恢复前重查预算，仍超限 → `LoopNotResumableError`、任务保持 PAUSED
  （`src/m1_core/loop.py:216-222`）。
- 证据：`src/m1_core/budget.py:34,74-108`；`src/m1_core/loop.py:156,216-222,351-365`。
- [v2Δ D-12: 判定口径成文（used≥max / now>deadline / now∉[from,to] / 注入 now），依据
  tests/CHANGELOG.md M1 登记 6；EVAL-M1-05-P2 四口径矩阵钉死。]

### SPEC-M1-06 完成申请与判定分离

- 冻结 API `request_completion(task_id, claim) -> CompletionVerdict`（`src/m1_core/loop.py:253-290`）；
  模型只能申请（CompletionClaim），判定由 `CompletionVerifier.judge` 依据权威证据做出；
  三值 `VERDICTS = ("ACCEPTED", "NEED_MORE_EVIDENCE", "REJECTED")`（`src/m1_core/completion.py:37`）。
- 只有 RUNNING/VERIFYING 可申请；其余状态返回 `REJECTED`（"任务处于 X"）且不迁移
  （`src/m1_core/loop.py:261-268`）；RUNNING 先迁 VERIFYING（reason=completion_claim，`:269-272`）。
- 判定依据（纯函数，不改状态，`src/m1_core/completion.py:112-195`）：
  - A. 预期产物清单 = plan **最终阶段** `artifacts_expected` ∪ `claim.expected_artifacts`（`:198-209`）；
    每项按 artifact_id 或 schema_id 解析（与阶段门禁同口径，`:211-222`），
    status ∈ `ACCEPTED_ARTIFACT_STATUSES = ("READY", "PUBLISHED")` 才算就绪（`:40,127-138`）；
  - B. 执行证据 = `state.evidence_refs` ∪ `claim.evidence_refs` 去重（`:140-143`）；每条解析 M2 工作区
    `evidence/` 下 `{"kind": "action_evidence"}` 三态序列化（`:224-239`），`intended/issued/observed`
    三态齐全才计完整（`:151-155`）；
  - C. 至少一条三态齐全的执行证据（`:166-177`）。
- 裁定：存在伪造引用（产物/证据引用无法解析）→ `REJECTED`（申请无效而非证据不足，gaps 清空，
  `:180-185`）；可解析但不完整 → `NEED_MORE_EVIDENCE` + gaps（`:186-190`）；全部通过 → `ACCEPTED`
  （`:191-195`）。
- 裁定执行：ACCEPTED → 登记 claim 指纹（`claim_fingerprint` = sha256 规范 JSON，
  `src/m1_core/completion.py:69-74`）→ VERIFYING→COMPLETED（`src/m1_core/loop.py:275-281`）；
  NEED_MORE_EVIDENCE → VERIFYING→RUNNING，gaps 注入 todos 并在 mutation.note 记录理由
  （`:282-290`）。
- 无 Claim 的 COMPLETED 迁移在守卫层拒绝（SPEC-M1-02 `CompletionRequiredError`）。
- 证据：`src/m1_core/completion.py:37,40,69-74,112-195,198-239`；`src/m1_core/loop.py:253-290,493-498`。
- [v2Δ D-09: 完成门禁落位，依据 tests/CHANGELOG.md M1 登记 3。]
- [v2Δ: 补 REJECTED（伪造引用）三值与"预期清单并集"口径；v1-06 只写 NEED_MORE_EVIDENCE 路径。]

### SPEC-M1-07 观测即事实

- Observe 只采信两类事实：M3 返回的 `ActionResult`（每 action 一条 observation 摘要，
  `src/m1_core/loop.py:608-613`）与任务事件流中的**环境事件**——
  `_ENV_EVENT_TYPES = (alarm.raised, alarm.cleared, measurement.updated, grid.event,
  price.period_changed, demand.month_rolled)`（`src/m1_core/loop.py:78-81,629-640`）。
- 环境事件按 `event_id` 去重：此前轮已观测过的（记录于 LoopTrace 各轮 `env_event_ids`）不再重复采信
  （`:629-640`）。
- 模型自述"已执行/已完成"不构成观测或证据；完成判定证据必须来自工作区 `evidence/` 落盘的三态序列化
  （SPEC-M1-06 B；EVAL-M1-07-P）。
- SUCCEEDED 动作：三态证据序列化经 `info.save_evidence` 落 M2 工作区 `evidence/` 并
  `evidence_refs_add` 入账（`src/m1_core/loop.py:614-623`）；随后触发产物策略（SPEC-M1-12）。
- 证据：`src/m1_core/loop.py:78-81,604-640`。
- [v2Δ: 环境事件主题集补 `price.period_changed`/`demand.month_rolled`（01 v2 §4 28 主题封闭集，
  D-69 转正）；v1-07 语义保留。]

### SPEC-M1-08 中间件可插拔

- 链按**注册顺序**执行（`dispatch` 逐个调用，`src/m1_core/middleware.py:110-123`）；`use` 尾部追加、
  同名不重复注册（`:83-90`）；`remove(name)` / `clear()` 管理（`:92-101`）。
- **异常收容**：中间件异常被捕获收容进 `TurnContext.notes`，不中断 Loop、核心语义不受损（`:117-122`）。
- 内置三件（缺省链 `default_middlewares()`，`:185-193`）：
  `LoggingMiddleware`（轮/阶段日志，`:127-139`）；
  `SafetyInjectionMiddleware`（MODEL 阶段前向模型请求注入安全指令，system 层前置，
  `:152-173`；`DEFAULT_SAFETY_DIRECTIVES` = README v1 §4 红线 1/2/3/4/7 的 agent 侧表达五条，
  `:143-149`）；
  `DelegationMiddleware`（L3 委派预留位，本期 no-op 留痕，`:176-182`）。
- 移除任一/全部中间件不影响 Loop 核心语义：EVAL-M1-MW-P 以 report3（01）/ask_wait（02）/need_more
  （06 形态）三场景在 缺省/全移除/单移除(safety) 三态下核心语义快照一致 + 注册序断言验证
  （`src/m1_core/eval_plugin.py:670-733`）。
- 证据：`src/m1_core/middleware.py:76-123,127-193`；`src/m1_core/eval_plugin.py:670-733`。
- [v2Δ: 补异常收容、内置件与安全指令内容成文；v1-08"可插拔+回归验证"语义保留。]

### SPEC-M1-09 恢复语义（ResumeEvent 矩阵 + 审批决断路由 + 幂等续跑）

- `ResumeKind = (USER_INPUT, APPROVAL_GRANTED, APPROVAL_DENIED, ENV_EVENT, TIMEOUT)`
  （`src/m1_core/loop.py:66`）；未知种类抛 `LoopError`（`:201-202`）。
- **状态-种类匹配矩阵** `_RESUME_RULES`（`src/m1_core/loop.py:69-75`；本会话实测值）：
  `PAUSED` 接受任意种类（但恢复前重查预算，SPEC-M1-05）；`WAITING_INPUT`→USER_INPUT；
  `WAITING_APPROVAL`→APPROVAL_GRANTED/APPROVAL_DENIED/TIMEOUT；`WAITING_EVENT`→ENV_EVENT；
  `VERIFYING`→USER_INPUT/ENV_EVENT/TIMEOUT。错配即拒 `LoopNotResumableError`（`:210-214`）。
- 终态只读（直接返回，`:205-206`）；CREATED/RUNNING 直接续跑 `run_loop`（`:207-208`）。
- WAITING_APPROVAL 恢复 = 审批决断路由：TIMEOUT → `gateway.check_approval_timeouts(now)`
  （`:739-741`）；GRANTED/DENY → `gateway.submit_approval(action_id, GRANT/DENY, approver, now)`
  （`:742-747`）；approver 取 `event.payload.approver` → 花名册首个"审批人"角色用户
  （`_default_approver`，`:771-777`）→ 字面量 `"APPROVER"` 兜底；审批主体授权（角色=审批人）
  由 M3 fail-closed 把关（01 v2 §3.3 D-32）。决断后的执行结果按 Observe 同口径入账
  （证据落盘/产物策略/动作预算，`_absorb_approval_result`，`:750-769`）；无 pending 审批条目直接回
  RUNNING（`:735-736`）。
- **Checkpoint 幂等续跑**：恢复后轮号从 LoopTrace 最大轮号 +1 续增（`src/m1_core/trace.py:82-85`；
  `src/m1_core/loop.py:330`）；任务语义续跑点由 plan 当前阶段 + todos 决定；绑定 DONE todo 的动作
  跳过（`:554-558`）；同幂等键动作由 M3 回放首结果、零二次副作用（EVAL-M1-09-P：executions=3）。
- **DONE 粘滞**：模型 todo_updates 不可回退已 DONE 项（`src/m1_core/planner.py:154-157`）；
  未知 id 且无 text 的提议忽略并说明（`:159-162`）。
- 证据：`src/m1_core/loop.py:65-75,196-251,544-560,729-777`；`src/m1_core/planner.py:133-163`；
  `src/m1_core/trace.py:82-85`。
- [v2Δ D-13: 状态-种类矩阵成文（v1 01§3.1 只列 ResumeEvent 种类、未列状态匹配矩阵），依据
  tests/CHANGELOG.md M1 登记 8。]
- [v2Δ D-14: 轮号台账口径（TaskState 冻结结构无轮次字段），依据 tests/CHANGELOG.md M1 登记 9
  （与 SPEC-M1-11 合并成文）。]

### SPEC-M1-10 成本上报通道

- 每轮 Model 调用后：`token_used_delta` 提交 `TaskState.budget`（`src/m1_core/loop.py:675-684`）
  + 发 `budget.warning {kind: "token", remaining, turn, cost{…, turn, token_used_delta}}`
  （`:685-693`）——01 §4 事件目录为冻结封闭集、无 model.*/cost 主题，`budget.warning` 兼作每轮
  成本上报通道（01 v2 §4 D-06 扩展通道 1，payload 保留 kind/remaining 语义字段并扩展 cost）。
- 缺上报的轮次视为违规：EVAL 断言 cost 事件数 ≥ 完整轮数、cost.turn 不重复、cost token 合计 =
  `budget.token_used`（`src/m1_core/eval_plugin.py:334-359`；EVAL-M1-10-P）。
- Act 阶段动作扣减：`action_used_delta = len(actions)`（`src/m1_core/loop.py:401-406`）；审批恢复
  成功入账 `action_used_delta = 1`（`:765-769`）。
- 证据：`src/m1_core/loop.py:401-406,675-693,765-769`；`src/m1_core/eval_plugin.py:334-359`。
- [v2Δ D-08: 上报通道 = `budget.warning` 兼作（并入 D-06 系统级扩展通道族），依据
  tests/CHANGELOG.md M1 登记 2；v1-10 只写"事件流 cost 字段"未指明主题。]

### SPEC-M1-11 LoopTrace 审计件与五阶段回放校验〔新增〕

- 五阶段序的回放数据源是 M1 运行期**审计件**
  `runtime/<root>/m1_core/loop/task-<task_id>.jsonl`（LoopTrace 追加写，每行一条阶段记录
  `{seq, task_id, turn, phase, at, trace_id, summary, data}`；文件名流名净化，
  `src/m1_core/trace.py:33-36`；缺省目录 = `Path(info.root)/"m1_core"/"loop"`，
  `src/m1_core/loop.py:157-158`）——01 §4 事件目录冻结封闭集、无 loop 阶段主题。
  **双轨定位**：权威状态在 M2（事件流），阶段序审计在 LoopTrace（与 M3 幂等 journal 同类的
  运行期审计件，非权威状态）。
- 各阶段记录的 data 摘要：PREPARE={manifest_hash, manifest_tokens, state_version, status,
  current_stage}（预算中断轮记 `{aborted: true, budget, state_version}`）；MODEL={cost, usage,
  tool_calls}；ACT={actions, skipped}；OBSERVE={observations, env_event_ids}；VERIFY=verify 汇总
  （`src/m1_core/loop.py:360-376,387-391,407-413,421-428,435-437`）。
- `validate_replay`（纯函数，`src/m1_core/trace.py:91-154`）：每轮阶段序必须是
  `PREPARE→MODEL→ACT→OBSERVE→VERIFY` 的**前缀**（完整轮=5 阶段；仅 PREPARE=预算中断轮合法）；
  MODEL 先于 PREPARE / 跳阶段 / 同阶段重复 → 违规；turn 序号严格递增（不可回退/复用）；
  seq 全局递增。`AgentCore.replay_report(task_id)` 暴露校验入口（`src/m1_core/loop.py:829-831`）。
- 注入的伪序必被拒、真实运行零此类序（EVAL-M1-01-N：5 条伪序全拒 + 真实运行 3 轮零违规；
  本会话实测 `validate_replay([MODEL,PREPARE])` → invalid，`[PREPARE]` 单轮 →
  `aborted_prepare_turns=1`）。
- 轮次台账：轮号 = LoopTrace 日志最大轮号 + 1（TaskState 冻结结构无轮次字段，
  `src/m1_core/loop.py:330`；`src/m1_core/trace.py:82-85`）；记录 seq = 既有行数 + 1（确定性递增，
  `src/m1_core/trace.py:87-88`）。
- 证据：`src/m1_core/trace.py:28,33-36,39-88,91-154`；`src/m1_core/loop.py:157-158,330,799-801,829-831`。
- [v2Δ D-07: 回放数据源 = LoopTrace 审计件而非 01§4 事件流，依据 tests/CHANGELOG.md M1 登记 1。]
- [v2Δ D-14: 轮号台账成文，依据 tests/CHANGELOG.md M1 登记 9。]

### SPEC-M1-12 产物自动落位策略〔新增〕

- `write.report` SUCCEEDED 后，由数据驱动产物策略 `DEFAULT_ARTIFACT_POLICY`
  （`src/m1_core/loop.py:84-90`：`write.report → {artifact_type: REPORT,
  schema_id: report.daily@v1, content_sections: [devices, measurements, conclusion,
  regulation_refs]}`；构造入参 `artifact_policy` 可覆盖）自动创建 M2 ArtifactRecord；
  content 取 `ActionResult.evidence.intended.arguments` 按 `content_sections` 拾取（`:652-662`）。
- 产物状态机：create（DRAFT）→ VALIDATING（schema 校验）→ 校验通过续迁 READY、失败停 REJECTED
  带 detail（`:663-669`；M2 ArtifactManager 语义）；产物 id 入 `TaskState.artifacts`（`:670-673`）。
- **幂等入账**：同 `action_id` 已存在 ArtifactRecord 则整体跳过（`created_by.action_id` 去重守卫，
  `:648-651`）——M3 幂等键回放返回首结果时，同 action 重入 Observe 不产生重复产物
  （Checkpoint 恢复重放安全）。
- 审批恢复路径的 SUCCEEDED 同样走该策略（`_absorb_approval_result` → `_apply_artifact_policy`，
  `:750-769`）。
- 证据：`src/m1_core/loop.py:84-90,642-673,750-769`。
- [v2Δ D-11: v1 无此条款；同 action_id 幂等守卫为首版缺失、复核补齐（commit 588da80 → 9062518），
  依据 tests/CHANGELOG.md M1 登记 5 + M1 复核修订 1。]

### SPEC-M1-13 模型客户端统一入口与确定性纪律〔新增〕

- 模型调用统一走 `m1_core.model_client`（01 v2 §8 横切：禁止业务模块直连 SDK）；
  `PROVIDERS = ("mock", "openai_like")`（`src/m1_core/model_client.py:48`），未知 provider 抛
  `ModelClientError`（`:213-215`）。
- **mock**：确定性离线脚本回放——`script` 逐条消费、耗尽抛 `ModelClientError`（`:250-255`）；
  无脚本时确定性回声（`:281-289`）；usage 缺省按 `estimate_tokens` 确定性估算
  （CJK 每字 1 token + ASCII 词元每串 1 token，与 M2 同口径，`:68-93`）；脚本化 usage 优先
  （`:291-300`）；`latency_ms` 恒 0（`:270`，重放逐字节一致）；行为键
  `todo_updates/completion_claim/request_input/wait_event/fail` 透传（`:273-278`）。
- **openai_like**：POST `{api_base}/chat/completions`（`:316`）；密钥经构造注入或环境变量
  `PD_MODEL_API_KEY`/`OPENAI_API_KEY`（`:51,352-358`），仅入 Authorization 头，永不入代码/日志/
  事件/调用审计（`:226`）；可重试错误（429/500/502/503/504/超时/网络错）按 `max_retries` 有界重试
  + 退避（`:53,319-341`）；重试预算耗尽 → `ModelRetryExhaustedError`（超时类原样抛
  `ModelTimeoutError`，`:342-346`）；不可重试的非 2xx → `ModelClientError` 原样带错误消息
  （`:338-340`）；`latency_ms` = `time.perf_counter` 实测（MONOTONIC 审计域，非业务判据，
  `:384`）。
- 传输层可注入（`transport` 形参——离线测试重试/超时分类不触网，`:209,224`；EVAL-M1-MODEL-P）。
- M5 persona LLM 模式经 mock provider 离线接线（`m5_simulation.persona persona_step(mode="llm")`
  后端；EVAL-M1-MODEL-P2）。
- 证据：`src/m1_core/model_client.py:48,51,53,68-93,194-247,250-300,303-346,352-389`。
- [v2Δ D-15（前半）: v1 §2 组件仅"provider 适配，超时/重试/成本上报"一句、无行为条款；
  成文依据 tests/CHANGELOG.md M1 登记（EVAL-M1-MODEL-P/P2）。]

### SPEC-M1-14 模型端点 SSRF 安全边界〔新增〕

- 缺省传输 `_urllib_transport` 在建连前强制 `_assert_safe_endpoint`（fail-closed，
  `src/m1_core/model_client.py:161`；校验体 `:116-150`）：
  - scheme 仅 https；明文 http 须显式 `PD_MODEL_ALLOW_INSECURE_HTTP=1`（`:107,124-128`）；
  - 拒 URL 内嵌凭据（userinfo）（`:129-130`）；
  - 缺主机名拒绝（`:131-133`）；
  - DNS 解析出的**全部地址**必须公网（`ip.is_global`）——拒回环/私网/链路本地（含云元数据
    169.254.169.254）/CGNAT（100.64/10，含 tailnet）/ULA/保留段（`:137-150`）；
  - 私网/tailnet 端点例外必须显式声明：`PD_MODEL_ALLOW_PRIVATE_HOSTS`（逗号分隔，
    精确主机匹配）白名单放行（`:108,111-113,134-136`）。
- 缺省传输为 stdlib `http.client` 直连（HTTPS/HTTP 按 scheme，`:153-191`）；错误语义保持：
  非 2xx 原样返回 `(status, parsed_body)` 不抛异常（`:189-191`）、超时→`TimeoutError`
  （`:179-180`）、网络错误→`ConnectionError`（`:181-182`）。
- 注入 `transport` 的离线测试路径不触网、不受此边界约束（`:209`）。
- 本会话实测（fail-closed 探针）：`http://api.example.com`（明文）、`https://user:pw@…`（userinfo）、
  `https://127.0.0.1`（回环）、`https://169.254.169.254`（云元数据）、`https://100.100.0.2`（CGNAT）
  全部 REJECTED。
- 证据：`src/m1_core/model_client.py:102-150,153-191`。
- [v2Δ D-15（后半）: 安全边界条款（v1 完全未写；提交门禁安全扫描高危修复，缺省传输由
  urlopen 改写为 http.client 直连），依据 tests/CHANGELOG.md 2026-09-29 提交门禁安全修复、
  commit 400a5a2。]

### SPEC-M1-15 Act 阶段动作请求构造〔新增〕

- Act 阶段逐个执行模型 `tool_calls`（`src/m1_core/loop.py:551-560`）；`capability` 必须为
  `"动作ID@版本"`（缺 `@` 抛 `LoopError`，`:564-566`）。
- 幂等键：`call.idempotency_key` 优先；缺省派生
  `"{task_id}:todo:{todo_id}:{capability}"`（绑定 todo 时）或
  `"{task_id}:turn{turn}:{index}:{capability}"`（无 todo 时）（`:568-570`）。
- `action_id`：`call.action_id` 优先，缺省 `act-<ULID>`（`:571`）。
- `risk`：`call.risk` 声明优先；否则查 `gateway.registry` 能力描述符
  （`descriptor.risk_level/reversible/compensation`）；均缺 → `{level: LOW, reversible: false,
  compensation: None}`（`:588-602`）。
- 绑定 DONE todo 的动作跳过（幂等续跑，`:554-558`）；actor 取 `TaskContext`
  （`actor_user/actor_agent`，`:577`；缺省值见 §2 D-16 注记）。
- `ActionRequest.from_dict` 契约前置校验（失败即抛、不进网关，`:584`）；执行经
  `gateway.execute_action(request, mode="SIMULATION", trace_id=trace_id)`（`:585-586`——M1 调用点
  固定 SIMULATION 路由；REAL 仅由 M3 门禁三重放行，01 v2 §3.3 D-31）。
- Model 请求的 tools 清单来自 `gateway.registry.descriptors()`（capability_id + name_cn，
  `:704-707`；底层即 `tools/` 16 适配器经 M3 注册，`tools/_base.py`）。
- 证据：`src/m1_core/loop.py:544-602,704-707`；`tools/_base.py`。
- [v2Δ: v1 §2 仅一句"tool_calls 逐个经 M3 网关执行"；机械落盘口径（capability 格式/幂等键派生/
  风险解析/SIMULATION 固定路由）按 oracle 成文。]

## 4. Eval（v2 机械重生成，整体替换落 `tests/test_m1.yaml`）

> **v2 重生成（2026-09-29，01 v2 §6 协议）**：套件由 v1 的 20 条整体替换为 30 条；
> `spec_ref` 升级为 specs-v2 文件（ADDENDUM 暂指 `specs/ADDENDUM.md` v1 原文——
> specs-v2/ADDENDUM.md 落盘后随其登记一并升级）；`spec_hash → eval_hash` 登记见
> `tests/CHANGELOG.md` 本轮条目（v1 套件两代 hash 存照）。正/负例方向、用例主条款
> 见各用例 `spec:` 字段（用例→条款方向）；下表为条款→用例方向，两向合成完整映射。
> 本轮按重生成约定**未运行** `run_evals.py`（统一门禁后置）；已做静态自检
> （YAML 可解析 / schema 静态校验零错 / 执行器名全部注册 / fixtures 引用存在 /
> spec_hash 重算一致）。

### 4.1 条款 → 用例（双向表之条款方向）

| v2 条款 | 正例 | 负例 | 断言要点 |
| --- | --- | --- | --- |
| SPEC-M1-01 | EVAL-M1-01-P | EVAL-M1-01-N | 每轮 5 阶段序（trace.turns 逐轮断言）+ 轮驱动（COMPLETED/max_turns→WAITING_INPUT）；伪阶段序注入必被拒 |
| SPEC-M1-02 | EVAL-M1-02-P、EVAL-M1-TABLE-P | EVAL-M1-02-N | ASK→WAITING_APPROVAL 合法迁移事件；非法迁移抛 IllegalTransitionError+双标记拒绝事件；双写 diff 空+10 态全矩阵 |
| SPEC-M1-03 | EVAL-M1-03-P | EVAL-M1-03-N | PREPARE 记录携带权威状态版本（prepare_state_versions）；伪造完成话术零状态迁移 |
| SPEC-M1-04 | EVAL-M1-04-P、EVAL-M1-GATE-P2 | EVAL-M1-04-N | 产物未就绪 BLOCKED+gap 注入；P0 告警阻断/清除恢复；REJECTED 状态不过门 |
| SPEC-M1-05 | EVAL-M1-05-P、EVAL-M1-05-P2 | EVAL-M1-05-N | token 超限 PAUSED+budget.exhausted+第 3 轮仅 PREPARE；四口径矩阵；PAUSED 恢复重查拒绝 |
| SPEC-M1-06 | EVAL-M1-06-P | EVAL-M1-06-N | 证据缺 observed→NEED_MORE_EVIDENCE+缺口 todos+VERIFYING→RUNNING；无 Claim 迁 COMPLETED→CompletionRequiredError |
| SPEC-M1-07 | EVAL-M1-07-P | EVAL-M1-07-N | 真实 ActionResult 观测采信（GRANT 决断后 SUCCEEDED+evidence）；伪造证据引用→verdict REJECTED（申请无效） |
| SPEC-M1-08 | EVAL-M1-MW-P | —（可插拔为性质条款，负例=MW-P 三态对比隐含） | 三场景×缺省/全移除/单移除(safety) 核心语义一致+注册序执行 |
| SPEC-M1-09 | EVAL-M1-09-P | EVAL-M1-09-N | Checkpoint 恢复幂等续跑（DONE 跳过+同键回放 executions=3）；Resume 状态-种类矩阵错配三连拒 |
| SPEC-M1-10 | EVAL-M1-10-P | —（缺上报=违规系 EVAL 自身断言，无外部禁止面） | 每轮 cost 事件、turn 不重复、tokens_total=budget.token_used |
| SPEC-M1-11 | EVAL-M1-11-P | EVAL-M1-11-N | 真实运行 trace 合法+零 model_without_prepare+complete_turns；伪序（乱序/跳阶段/重复）逐条拒绝 |
| SPEC-M1-12 | EVAL-M1-12-P | EVAL-M1-12-N | write.report SUCCEEDED→产物自动 READY（DRAFT→VALIDATING→READY 事件序）；同 action_id 重放零二次产物（artifact.state_changed 恰 3 条、executions=1） |
| SPEC-M1-13 | EVAL-M1-MODEL-P、EVAL-M1-MODEL-P2 | —（脚本耗尽/超时分类负例内嵌于 MODEL-P） | mock 确定性/脚本化成本/耗尽抛错+openai_like 传输注入重试分类；persona LLM 离线接线 |
| SPEC-M1-14 | —（公网放行需真实网络，离线 EVAL 不覆盖；注入 transport 路径不受边界约束由 EVAL-M1-MODEL-P 同证） | EVAL-M1-14-N、EVAL-M1-14-N2 | 端点解析到非公网地址（回环 127.0.0.1 / 云元数据 169.254.169.254）建连前 fail-closed 拒绝（ModelClientError/SSRF） |
| SPEC-M1-15 | EVAL-M1-02-P、EVAL-M1-09-P | EVAL-M1-15-N | 动作请求构造全链（幂等键派生/risk 解析/SIMULATION 固定路由）；capability 缺 "@" 版本段→LoopError 拒绝 |

### 4.2 用例 → 条款（双向表之用例方向，速查）

| EVAL id | 条款（主/兼） |
| --- | --- |
| EVAL-M1-01-P | 01 |
| EVAL-M1-01-N | 01、11 |
| EVAL-M1-02-P | 02、15 |
| EVAL-M1-02-N | 02 |
| EVAL-M1-TABLE-P | 02 |
| EVAL-M1-03-P | 03 |
| EVAL-M1-03-N | 03 |
| EVAL-M1-04-P | 04 |
| EVAL-M1-04-N | 04 |
| EVAL-M1-GATE-P2 | 04 |
| EVAL-M1-05-P | 01、05、11 |
| EVAL-M1-05-N | 05、09 |
| EVAL-M1-05-P2 | 05 |
| EVAL-M1-06-P | 04、06、09 |
| EVAL-M1-06-N | 02、06 |
| EVAL-M1-07-P | 07、09 |
| EVAL-M1-07-N | 06、07 |
| EVAL-M1-MW-P | 08 |
| EVAL-M1-09-P | 09、12 |
| EVAL-M1-09-N | 09 |
| EVAL-M1-10-P | 10 |
| EVAL-M1-11-P | 11 |
| EVAL-M1-11-N | 01、11 |
| EVAL-M1-12-P | 12 |
| EVAL-M1-12-N | 12 |
| EVAL-M1-MODEL-P | 13、14 |
| EVAL-M1-MODEL-P2 | 13 |
| EVAL-M1-14-N | 14 |
| EVAL-M1-14-N2 | 14 |
| EVAL-M1-15-N | 15 |

**复核命令**（仓库根，Python 3.12）：`python run_evals.py --module m1`（统一门禁执行；
本轮静态自检通过，见文件头注）。

## 5. DoD（验收定义）

| DoD 条目 | oracle 达成状态 |
| --- | --- |
| 全部 EVAL 数据驱动跑通（runner 无硬编码特判） | ⏳ v2 重生成套件（30 条）待统一门禁（本轮按约定未运行 run_evals.py）；v1 套件历史基线 20/20 PASS 见 tests/CHANGELOG.md |
| 状态机迁移表与 01§5.1 完全一致（双写 diff 空） | ✅ 本会话实测 `assert_table_consistency()` → `{'states': 10, 'diff': {}}`；EVAL-M1-TABLE-P 另含 10 态全矩阵守卫 |
| 移除全部中间件后 01/02/06 场景仍通过 | ✅ EVAL-M1-MW-P：report3/ask_wait/need_more 三场景 × 三态语义一致（06 形态 need_more 为复核修订补齐） |
| `model_client` provider=mock 全部 EVAL 离线复跑 | ⏳ v2 套件全部用例离线可跑（mock/传输注入/SSRF 建连前拒绝均零触网）；v1 套件历史基线 `--module all` 180/180 PASS |
| [v2Δ] 模型端点 SSRF 边界 fail-closed | ✅ 本会话实测五类恶意端点全拒（见 SPEC-M1-14）；EVAL-M1-14-N/N2 营用例化（回环/云元数据）；登记依据 tests/CHANGELOG.md 2026-09-29 |
| [v2Δ] 突变验证（改迁移表/拆完成门禁/废预算检查点/Observe 采信自述均被捕获） | 📋 tests/CHANGELOG.md M1 首条登记记录（v1 套件登记时实跑通过；本会话未复跑突变项） |

## 6. 交付物

- `src/m1_core/` 全部源码（13 文件，见 §2 组件树）；
- `tests/test_m1.yaml`：30 条数据驱动 EVAL（v2 重生成 30 条 = 正例 17/负例 13；v1 阶段 20 条
  = §4 表 14 条机械生成 + 6 条表外补强，登记对照见 `tests/CHANGELOG.md` 2026-09-29
  「M1 EVAL v2 重生成」节）；
- `src/m1_core/eval_plugin.py`：7 执行器插件（EVAL-SCHEMA §4 插件契约）；
- `tests/fixtures/frozen_state_machines.yaml`（machines.task 双写基准，S0 fixture、M1 消费）；
- `tests/CHANGELOG.md` M1 登记 3 条：首条登记（spec_hash `c8a2cd2b…`→eval_hash
  `b0f28d6a…`）、复核修订（产物幂等 + need_more 场景，eval_hash `7307d441…`）、
  2026-09-29 提交门禁安全修复（SSRF）。

> [v2Δ: v1 §6 仅列"src/m1_core/ 全部源码 + tests/test_m1.yaml + tests/CHANGELOG.md 首条登记"；
> oracle 实有 eval_plugin.py 与 3 条登记，按实际交付面修订。]
