# M1 · Agent Core（执行内核）Spec + Eval

> 职责一句话：把模型的离散判断组织成有状态、可控制、可恢复、可验证结束的任务过程。
> 上游依赖：M2（Context/State）、M3（Action）、M4（实体解析）。本模块不持有任何持久数据（全部外置 M2）。

## 1. 职责边界

**做**：Agent Loop（Prepare/Model/Act/Observe/Verify 五阶段循环）；任务状态机驱动与迁移守卫；Planning/Todo 外部化；阶段门禁（stage gate）评估；预算检查点；完成验证（证据判定）；Middleware 链。
**不做**：上下文组装（M2）；动作执行与策略判定（M3）；语义解析（M4）；委派子 agent（L3 后扩展，本期仅预留 `subtasks` 字段与 `delegation` 中间件位）。

## 2. 内部组件

```text
m1_core/
├── loop.py            # run_loop(task_id)：五阶段状态循环
├── state_machine.py   # 10 态迁移守卫（迁移表=01§5.1，硬编码+表驱动双写校验）
├── planner.py         # 计划结构管理（plan 结构=01§2.3）
├── gates.py           # 阶段门禁：每阶段出口判定（产物齐全+预算够+无阻断告警）
├── completion.py      # 完成验证器：CompletionClaim → Verdict
├── budget.py          # 预算检查点（每轮 Loop 头部检查，超限→PAUSED+事件）
├── middleware.py      # 链式中间件：日志/安全注入/委派预留位
└── model_client.py    # LLM 统一客户端（provider 适配，超时/重试/成本上报）
```

## 3. 行为规格（SPEC 条款）

- **SPEC-M1-01 Loop 顺序**：每轮严格按 Prepare→Model→Act→Observe→Verify 顺序执行；Prepare 中断（如预算耗尽）时本轮不进入 Model。
- **SPEC-M1-02 状态迁移守卫**：所有迁移走 01§5.1 表；非法迁移抛 `IllegalTransitionError`，任务保持原状态并落拒绝事件（`task.status_changed` payload 带 `rejected: true`）。
- **SPEC-M1-03 权威状态驱动**：Loop 每轮从 M2 读取 TaskState 驱动，禁止从对话历史推导任务状态；对话历史仅作为 Context 源之一。
- **SPEC-M1-04 阶段门禁**：进入下一阶段必须满足该阶段 gate（plan 中声明的 artifacts_expected 已存在且 status ∈ {READY, PUBLISHED}）；不满足则停留在当前阶段并产出明确的 gap 清单（写入 todos）。
- **SPEC-M1-05 预算检查点**：每轮 Prepare 检查 token_used/action_used/deadline/price_window 任一超限 → 立即 PAUSED + `budget.exhausted` 事件；PAUSED 恢复需 ResumeEvent。
- **SPEC-M1-06 完成申请与判定分离**：模型只能"申请完成"（request_completion + CompletionClaim）；判定由 completion.py 依据 evidence_refs 做出：Artifact 状态=PUBLISHED/READY、evidence 三态齐全、预期产物清单核对。verdict=NEED_MORE_EVIDENCE 时回 RUNNING 并在 todos 注入缺口。
- **SPEC-M1-07 观测即事实**：Observe 阶段只接受 M3 返回的 ActionResult.observation 与环境事件（M2 事件流）；模型自述"已执行"不构成 Observe 事实。
- **SPEC-M1-08 中间件可插拔**：middleware 链以注册顺序执行；移除任一中间件不影响 Loop 核心语义（回归测试验证）。
- **SPEC-M1-09 恢复语义**：从 Checkpoint 恢复后，Loop 必须能从 task.plan 中声明的当前阶段继续，且已 DONE 的 todos 不重复执行（幂等续跑）。
- **SPEC-M1-10 成本上报**：每轮 Model 调用后 token 消耗写 TaskState.budget 与事件流（`cost` 字段），缺上报的轮次视为违规。

## 4. Eval（从 SPEC 机械生成，落 `tests/test_m1.yaml`）

| EVAL ID | 对应 SPEC | 场景 | 期望 |
| --- | --- | --- | --- |
| EVAL-M1-01-P | 01 | 正常 3 轮任务（巡检报告） | 每轮事件序均为 5 阶段，无跨阶段跳跃 |
| EVAL-M1-01-N | 01 | 构造 Model 先于 Prepare 的事件序 | runner 断言该序不存在（事件流回放校验） |
| EVAL-M1-02-P | 02 | RUNNING→WAITING_APPROVAL（ASK 动作） | 迁移成功，事件 from/to 正确 |
| EVAL-M1-02-N | 02 | 请求 COMPLETED→RUNNING | `IllegalTransitionError`，任务仍 COMPLETED，落拒绝事件 |
| EVAL-M1-03-P | 03 | 对话中伪造"任务已完成"话术 | TaskState 不变（状态只能经 commit_state 变更） |
| EVAL-M1-04-P | 04 | 阶段产物未 READY 即申请过门 | 停留当前阶段，todos 出现 gap 项 |
| EVAL-M1-04-N | 04 | 产物齐但 status=REJECTED | 同上（REJECTED 不算过门） |
| EVAL-M1-05-P | 05 | token_max=500，第 3 轮超限 | 状态=PAUSED，事件 budget.exhausted |
| EVAL-M1-05-N | 05 | 超限后无 ResumeEvent 继续驱动 | Loop 拒绝进入下一轮 |
| EVAL-M1-06-P | 06 | 模型申请完成但 evidence 缺 observed | verdict=NEED_MORE_EVIDENCE，回 RUNNING |
| EVAL-M1-06-N | 06 | 无 CompletionClaim 直接终态 COMPLETED | 拒绝（终态必须经 completion 判定） |
| EVAL-M1-07-P | 07 | 模型自述"遥控已完成"但 ActionResult 缺失 | 不采信，任务仍 WAITING_APPROVAL/WAITING_EVENT |
| EVAL-M1-09-P | 09 | Checkpoint 恢复到阶段 2/4 | 从阶段 2 续跑，todos 幂等 |
| EVAL-M1-10-P | 10 | 跑完任务检查事件流 | 每轮均有 cost 事件，token 累计=budget.token_used |

## 5. DoD（验收定义）

- 全部 EVAL 数据驱动跑通（runner 无硬编码特判）；
- 状态机迁移表与 01§5.1 完全一致（表驱动文件 diff 为空）；
- 移除全部中间件后 EVAL-M1-01/02/06 仍通过；
- `model_client` 在 provider=mock 模式下全部 EVAL 可离线复跑。

## 6. 交付物

`src/m1_core/` 全部源码 + `tests/test_m1.yaml` + `tests/CHANGELOG.md` 首条登记。
