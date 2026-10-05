# M3 · Action Gateway（行动层）Spec v2

> **职责一句话**：把模型意图转化为受控行动——准入校验、三值授权、审批、隔离执行、观测回传，全链留痕。
> **oracle**（唯一事实源）= `src/m3_action/`（13 文件）+ `tools/`（`_base.py` + 16 个动作适配器）
> + `ontology/actions.yaml`（动作数据权威）+ `tests/test_m3.yaml`（现行 25 用例）+ `tests/negative_matrix.yaml`。
> **上游依赖**：M5（SIMULATION 路由目标，`simulate()` 冻结 API）、M7（能力资产发布）；
> **调用方** = M1 Loop（ACT 阶段）与 M6 CaseRunner（黄金链路真实化，01 v2 §3.3 D-51）
> ——v1 写"M1 是唯一调用方"，oracle 中 M6 经真实 M3 全链跑黄金，调用方不再唯一 [v2Δ D-51]。
> 本文件 2026-09-29 由 M3 工程师按 oracle 重写（实现反提）；v1 原文（`specs/M3-action-gateway.md`）原样保留不删。
> 全部 evidence 行号为 2026-09-29 本会话实读行号；oracle 健康实测：`python run_evals.py --module m3`
> → `EVALS mode=m3 isolation=OK modules=1/1 pending=0 cases=25/25 failed=0 skipped=0 result=PASS`（spec 重写时点基线，套件 25 例；EVAL 已按本 spec v2 重生成为 30 例（含变异缺口修复 04-N），见 §4 与 tests/CHANGELOG.md 同日条目）。

---

## 0. v1→v2 条款映射与偏差吸收（文件头部注释块）

| v1 条款 | v2 条款 | 重排说明 |
| --- | --- | --- |
| SPEC-M3-01 三事实区分 | SPEC-M3-01 | 三事实+披露面口径（披露校验细节入 02 准入管线） |
| SPEC-M3-02 契约校验 | SPEC-M3-02 | 扩为四段准入管线；吸收 D-24（准入失败不进生命周期） |
| SPEC-M3-03 业务语义粒度 | SPEC-M3-03 | 扩为注册粒度+数据权威装配；吸收 D-27（tools 布局） |
| SPEC-M3-04 三值判定 | SPEC-M3-04 | 判定事件 payload 成文；DENY 终态拼写随 D-01 落 `DENIED` |
| SPEC-M3-05 红线不可改 | SPEC-M3-05 | 吸收 D-25（ASK 锁定拒绝**一切**覆盖，含收紧 ASK→DENY） |
| SPEC-M3-06 角色覆盖单向收紧 | SPEC-M3-06 | 吸收 D-26（收紧基准=当前生效判定） |
| SPEC-M3-07 审批超时 | SPEC-M3-07 | 扩为审批队列持久化+超时；吸收 D-28 审批半（jsonl/重启续接/终态回写） |
| （v1 无） | SPEC-M3-08 | 吸收 D-32（审批权 fail-closed，v1 完全未写审批主体授权） |
| SPEC-M3-08 幂等 | SPEC-M3-09 | 吸收 D-28 幂等半（两档键策略/write-ahead/KEY_CONFLICT） |
| SPEC-M3-09 证据三态 | SPEC-M3-10 | 吸收 D-29（isolate_execution_env 失联执行器可测落位） |
| SPEC-M3-10 路由隔离 | SPEC-M3-11 | 吸收 D-31（REAL 门禁三重） |
| （v1 无） | SPEC-M3-12 | 吸收 D-30（trace/事件确定性口径；event_id 形态并入契约层 D-03） |
| （v1 无） | SPEC-M3-13 | 吸收 D-33（create.switch_order 仅 DRAFT；SAFE-ISSUE-HUMAN 的 M3 落位） |
| （v1 无） | SPEC-M3-14 | 时间纪律（tests/CHANGELOG.md M3 登记 11；非 D-xx 条目，按 oracle 成文） |
| SPEC-M3-11 write-path 负向测试 | SPEC-M3-15 | 矩阵数据驱动口径（tests/negative_matrix.yaml 实形态） |
| （v1 无） | SPEC-M3-16 | D-59 KNOWN-DEFECT：modify.asset_history schema 形态缺陷（登记不修） |

偏差吸收合计 11 条（D-24..D-33、D-59）：10 条吸收为条款，1 条（D-59）为 KNOWN-DEFECT 条款；
逐条处置记录见 `specs-v2/deviations/M3.md`。契约层关联偏差 D-01（DENIED 拼写）/D-03（event_id 双形态）/
D-06（就近落主题扩展通道）已由 01 v2 吸收，本模块条款引用之。

---

## 1. 职责边界

**做**：
- 能力注册：`CapabilityDescriptor`（参数 schema + 风险声明 + 幂等键策略 + 披露面）；
  风险/缺省 Policy 数据权威 = `ontology/actions.yaml`，schema/幂等策略/披露面数据权威 = `tools/` 适配器声明（SPEC-M3-03）；
- ActionRequest 准入管线：契约 → 注册 → 披露 → 参数 schema 四段校验（SPEC-M3-01/02）；
- 身份→角色绑定：`actor_roles` 花名册（缺省自实例 `env.operators` 装载）（SPEC-M3-08）；
- Policy 三值判定：动作缺省 Policy + 角色覆盖单向收紧 + 不可改清单（policy_locked）（SPEC-M3-04/05/06）；
- 审批队列：持久化 + 超时 + 审批权 fail-closed（SPEC-M3-07/08）；
- 执行路由：REAL/SIMULATION 三重门禁，REAL 仅 mock 接线（SPEC-M3-11）；
- 幂等执行器：write-ahead journal，崩溃重试零二次副作用（SPEC-M3-09）；
- Observation 证据三态：独立环境回读 + 自报降级（SPEC-M3-10）；
- M3 事件流：EventRecord 契约校验 + `EVT-M3-<seq>` 确定性序号 + `task-<task_id>` 分片（SPEC-M3-12）；
- write-path 负向测试件（CI 常驻，SPEC-M3-15）。

**不做**：
- 具体设备协议执行（`tools/` 适配器委托 M5 `simulate()`；REAL 仅 mock 签名）；
- 审批 UI（事件 + 查询接口即可）；
- 预算扣减（M1 持有 Budget Lease，M3 不读不写预算）；
- 电价判定（M5 BUSINESS 时钟专责；`m3_action` 零电价语义，SPEC-M3-14）；
- 操作票签发（SAFE-ISSUE-HUMAN：签发动作不属于任何 agent 动作集，SPEC-M3-13）。

---

## 2. 内部组件（按 oracle 实际目录树）

```text
src/m3_action/            # 13 文件（v1 §2 只列 8 文件 [v2Δ 按实际目录更新]）
├── __init__.py           # 公共导出（ActionGateway/ACTION_TRANSITIONS/各组件）
├── gateway.py            # 门面：准入→幂等→判定→审批/执行→观测 全链编排（01§3.3 冻结 API 载体）
├── registry.py           # 能力注册表 + 不可改清单双重表达 + actions.yaml/适配器装配与 diff 断言
├── validator.py          # 准入管线四段校验（契约→注册→披露→参数 schema 迷你校验器）
├── policy_engine.py      # 三值判定引擎（缺省 Policy + 角色覆盖单向收紧 + policy_locked）
├── approval.py           # 审批队列（approvals.jsonl 持久化 + 超时）
├── router.py             # REAL/SIMULATION 路由（三重门禁）[v2Δ 新增于 v1 §2 清单之外]
├── executor.py           # 幂等执行器（idempotency.jsonl write-ahead claim/complete）
├── observer.py           # Observation 组装（环境回读 + 自报降级 OBSERVATION_MISMATCH）
├── events.py             # M3 事件流（EventRecord 校验 + EVT-M3-<seq> 确定性序号）[v2Δ 同上]
├── clocking.py           # 时间助手（唯一墙钟读取位 now_iso；审批超时域）[v2Δ 同上]
├── negative_test.py      # write-path 负向矩阵执行件（数据驱动，无特判）
└── eval_plugin.py        # EVAL 执行器插件（m3.execute / m3.registry / m3.negative_matrix）[v2Δ 同上]

tools/                    # 仓库根（非 src 包；pyproject 仅打包 src/，registry 兜底 sys.path，D-27）
├── _base.py              # 适配器公共约定（sim_execute→M5 simulate；real_mock_execute）
└── <动作 ID 的 "."→"__">.py × 16   # 一动作一模块（v1 01§1 写"每个 action family 一个"[v2Δ D-27]）

runtime/                  # 运行期审计件（gitignore 域）
├── m3_action/idempotency.jsonl   # 幂等 write-ahead journal（record 记录按键覆盖重放）
├── m3_action/approvals.jsonl     # 审批队列持久化（enqueued/resolved/expired 重放重建）
└── events/task-<task_id>.jsonl   # M3 事件流（与 M2 同分片约定）
```

---

## 3. 行为规格（SPEC 条款 v2，共 16 条）

### 3.1 注册与准入

- **SPEC-M3-01 三事实区分与披露面**：模型看见（Context Tool Descriptor，M2）≠ 注册（CapabilityRegistry）≠
  授权（PolicyEngine）——注册表只是"存在性"权威；未注册能力请求 → `REJECTED/UNREGISTERED`；
  已注册但未对该 actor 角色披露（`disclosed_roles` 非空且 actor 角色不在其中）→ 同样 `REJECTED/NOT_DISCLOSED`；
  `disclosed_roles` 空列表 = 对全部角色披露（16 个缺省适配器全部空披露面，运行期 `register_capability`
  可注册带披露面的能力）。角色解析：actor 为 mapping 时显式 `role` 字段优先，否则查 `actor_roles[user]` 花名册。
  oracle 证据：`src/m3_action/registry.py:151`（存在性权威）、`:89`（空=全披露）、`:160-165`（重复注册同
  capability_id → 覆盖更新）；`src/m3_action/validator.py:133-153`（注册/披露校验）；`src/m3_action/gateway.py:137-146`（冻结
  API：运行期注册与纯策略查询 `query_policy` 不落请求主链事件）、`:479-487`（`_role_of`）；
  `tools/query__measurement.py:19`（空披露面）。EVAL：M3-01-P / M3-01-N2（UNREGISTERED 见 M3-01-N）。
  [v2Δ: v1 只写"未披露 → REJECTED"，oracle 补 NOT_DISCLOSED 错误码与空=全披露缺省、角色解析口径；
  tests/CHANGELOG.md M3 登记 1]

- **SPEC-M3-02 准入管线（失败不进生命周期，D-24）**：`execute_action` 内部按**固定顺序**四段准入：
  ① 契约校验（`contracts.ActionRequest.from_dict`，缺字段/枚举越界/未知字段 → `CONTRACT_INVALID`）；
  ② 注册校验（→ `UNREGISTERED`，红线 1）；③ 披露校验（→ `NOT_DISCLOSED`）；④ 参数 schema 校验
  （→ `SCHEMA_INVALID` + 错误路径）。任何一段失败（以及后述 REAL 路由拒绝、幂等键冲突，同走此通道）：
  **发生在 01 v2 §5.2 REQUESTED 之前 → 状态 REJECTED、不落 `action.requested`（不进事件主链）**，
  审计事件落 `action.policy_decided {decision: DENY, stage: admission, error_code, error_path, message}`
  （事件目录无 error.* 主题，沿用就近落主题扩展通道族，01 v2 §4 D-06）。schema 迷你校验器为声明式子集
  （type/required/enum/items/min/max/properties，无 eval/exec），声明 properties 时未知参数键拒绝
  （与 contracts.check_keys 同口径）；错误路径并入 error.message（ActionError 契约只含 code/message）。
  oracle 证据：`src/m3_action/validator.py:4-13,25-28,113-167`（四段管线与错误码）；`:61-107`（迷你校验器；
  未知键 `:74-78`）；`src/m3_action/gateway.py:157-160`（管线调用）、`:429-454`（`_admission_rejected`：
  无 action.requested，审计事件落点 `:436-444`）、`:489-495`（错误路径并入 message）；
  `tests/EVAL-SCHEMA.md` 断言的 `event_types_absent` 见 `tests/test_m3.yaml:70-75,138-142,163-167`。
  EVAL：M3-02-N（CONTRACT_INVALID）/ M3-02-N2（SCHEMA_INVALID+路径）/ M3-01-N（UNREGISTERED 审计）。
  [v2Δ D-24: v1 只写"拒绝且不进事件流主链（落 error 事件）"——目录无 error.* 主题，oracle 落
  action.policy_decided{DENY, stage:admission} 审计；管线四段顺序与 schema 声明式子集为 oracle 成文]

- **SPEC-M3-03 能力注册粒度与数据权威装配（D-27）**：注册粒度 = 00 v2 §1.3 动作表（16 条），一动作一模块
  （`tools/<动作 ID 的 "."→"__">.py`；`create.switch_order` 与 `execute.remote_control` 严禁合并注册——
  独立注册断言）；`capability_id = "动作ID@版本"` 且与 action_id/version 字段一致（注册时自校验）。
  装配数据权威二分：**风险声明与缺省 Policy/policy_locked 来自 `ontology/actions.yaml`**（运行期只读，
  代码不重复声明），**参数 schema/幂等键策略/写类标记/披露面来自 `tools/` 适配器声明**；装配即断言适配器
  动作集与动作表 diff 为空（非空抛 ValueError）；CI 断言 `registry_vs_actions_table_diff`（动作 ID 集合 +
  逐动作 risk_level/reversible/default_policy/policy_locked）恒空。pyproject 仅打包 src/，registry 兜底把
  仓库根加入 sys.path（pathlib 推断，不依赖 cwd）。oracle 证据：`tools/__init__.py:11-31`（16 模块名机械映射）；
  `tools/_base.py:1-55`（适配器九要素约定）；`src/m3_action/registry.py:69-134`（Descriptor 与 validate）、
  `:137-144,187-193`（sys.path 兜底）、`:196-228`（装配与 diff 断言 `:202-207`）、`:234-261`（两层 diff）；
  `ontology/actions.yaml`（16 条全文）。EVAL：M3-03-P（diff 空 16 动作+独立注册）/ M3-03-P2。
  [v2Δ D-27: v1 01§1 写"每个 action family 一个模块"，oracle 为一动作一模块；数据权威二分与装配断言
  为 oracle 成文；tests/CHANGELOG.md M3 登记 4]

### 3.2 Policy 三值判定

- **SPEC-M3-04 三值判定与判定事件**：每次请求**必出** `action.policy_decided` 判定事件（payload 含
  decision/base/capability_action/actor_role/locked/override_applied/override_rejected/reason）；判定输入 =
  动作缺省 Policy（00 v2 §1.3 动作表数据）+ 角色覆盖表。路径：DENY → 终态 **DENIED**（01 v2 §5.2 冻结迁移，
  D-01）+ `action.completed{status:DENIED}`，error `POLICY_DENIED`；ASK → `WAITING_APPROVAL`（入审批队列，
  发 `action.waiting_approval` + `approval.requested`）；ALLOW → `EXECUTING`。生命周期为表驱动
  `ACTION_TRANSITIONS`（与 `tests/fixtures/frozen_state_machines.yaml` action 机 diff 必须为空——EVAL 断言），
  非法迁移抛 `IllegalTransitionError`；`action.completed` 仅对终态（SUCCEEDED/FAILED/REJECTED/DENIED/
  COMPENSATED）发布，非终态等待审批不构成 completed。动作不在授权规则表内 → 按 DENY 处置（注册校验后的
  第二道防线）。`query_policy` 为纯判定（不执行、不落主链事件）。oracle 证据：`src/m3_action/policy_engine.py:93-128`（decide；
  payload `:55-65`；未知动作 `:96-104`）；`src/m3_action/gateway.py:57-67`（ACTION_TRANSITIONS；COMPENSATED 为
  条件迁移不进无条件表）、`:195-242`（主链三路径）、`:203-210`（判定事件）、`:414-427`（终态才 completed）、
  `:462-476`（状态机守卫）；`src/m3_action/eval_plugin.py:337-345`（fixture diff 断言）。
  EVAL：M3-04-P / M3-04-P2 / M3-04-N（未入动作表第二道防线 DENY）/ M3-05-N（DENIED）/ M3-03-P2（生命周期表）。
  [v2Δ: v1 写"DENY 路径终态 DENYED"系笔误 → DENIED（D-01，01 v2 §5.2 已修正）；判定事件 payload 字段集
  与表驱动生命周期为 oracle 成文]

- **SPEC-M3-05 红线不可改清单（policy_locked 语义，D-25）**：缺省 DENY 永久不可覆盖 = `modify.protection_setting`、
  `modify.asset_history`、`bypass.approval`（任何角色/审批均不可翻转为 ALLOW）；缺省 ASK 永久 =
  `execute.remote_control`（审批只放行单次，不改缺省）。**锁定动作拒绝一切角色覆盖，含收紧 ASK→DENY**
  （判定维持缺省，尝试落审计事件 `override_rejected: true`）；双重表达：代码硬编码清单
  （`IMMUTABLE_DENY_ACTIONS`/`PERMANENT_ASK_ACTIONS`）与 `ontology/actions.yaml` `policy_locked: true` 行必须
  一致（`assert_immutable_consistency` 四方向断言，CI 常驻）。oracle 证据：`src/m3_action/registry.py:36-48`
  （两清单）、`:264-287`（`assert_immutable_consistency`）；`src/m3_action/policy_engine.py:106-107`
  （decide 锁定判定）、`:110-114`（锁定时覆盖一律拒，`override_rejected=true`）、`:145-152`（set_role_override
  锁定拒绝）；`ontology/actions.yaml`（execute.remote_control /
  modify.* / bypass.approval 的 policy_locked: true 行）。EVAL：M3-05-N（超管 DENY 不可覆盖）/ M3-05-N2
  （审批人改缺省 ALLOW 被拒）/ M3-03-P2（双重表达断言）。
  [v2Δ D-25: v1 只写"不可改清单+CI 断言"，oracle 明确锁定动作对**收紧方向同样拒绝**（v1 语义允许收紧例外）；
  SPEC-M3-11 矩阵对 remote_control 期望缺省 ASK——WAITING_APPROVAL 零副作用同样成立；
  tests/CHANGELOG.md M3 登记 2]

- **SPEC-M3-06 角色覆盖单向收紧（基准=当前生效判定，D-26）**：合法收紧方向 = ALLOW→ASK / ALLOW→DENY /
  ASK→DENY（`TIGHTEN_STEPS` 单向合法集；与当前生效判定相等视为无操作，accepted=true 不属收紧）。
  **收紧基准=当前生效判定（已存覆盖优先于缺省）**：已收紧为 ASK 的角色再请求 ALLOW（即使 ALLOW==缺省）
  属放宽，拒绝且维持 ASK。覆盖尝试（无论接受与否）一律落审计事件（`policy:<role>` 审计流）；构造期注入
  非法初始覆盖直接 raise。oracle 证据：`src/m3_action/policy_engine.py:28-39`（TIGHTEN_STEPS/is_tightening）、
  `:84-90`（构造期校验）、`:131-169`（set_role_override：锁定拒 `:147-152`、**当前生效基准** `:153-165`、
  生效写入 `:166-169`）、`:176-199`（尝试即审计）。EVAL：M3-06-P（收紧生效+放宽被拒+复验维持 ASK）。
  [v2Δ D-26: v1 只写"不能放宽 ASK→ALLOW"，oracle 明确基准=当前生效判定（覆盖回缺省同为放宽）；
  tests/CHANGELOG.md M3 登记 3]

### 3.3 审批

- **SPEC-M3-07 审批队列：持久化与超时（D-28 审批半）**：WAITING_APPROVAL 超过 `approval_timeout_s`
  （缺省 300s）→ REJECTED（payload 带 `timeout: true`，error `APPROVAL_TIMEOUT`），任务收 `approval.timeout`
  事件，且同 key 幂等 journal 回写终态。审批队列持久化 = `runtime/m3_action/approvals.jsonl` 追加写日志
  （enqueued/resolved/expired 三类记录），重启重放重建 pending 集——WAITING_APPROVAL 项不丢，gateway 构造时
  将遗留 pending 续接进 action 生命周期；条目携带完整 ActionRequest dict（重启后 GRANT 仍可继续执行）。
  同 action_id 重复入队幂等；审批决断一次性消费条目（resolve 后不可重放）。oracle 证据：
  `src/m3_action/approval.py:21-22`（DEFAULT_APPROVAL_TIMEOUT_S=300.0）、`:24`（三类记录）、`:38`（完整请求）、
  `:63-65`（is_due ≥ 判据）、`:80-109`（重放重建）、`:117-129`（重复入队幂等）、`:137-145`（一次性消费）、
  `:147-158`（到期批量）；`src/m3_action/gateway.py:107-108`（队列挂载）、`:130-132`（重启续接）、
  `:318-349`（check_approval_timeouts → REJECTED/timeout + journal 回写 `:347-348`）。EVAL：M3-07-P（301s 超时）/
  M3-07-P2（重启后 GRANT 续执行）。
  [v2Δ D-28: v1 只写超时行为与"DoD 队列持久化"；oracle 落 JSONL journal 形态、重启续接、条目全量携带、
  审批终态幂等回写（独立评审缺口修复 5）；tests/CHANGELOG.md M3 登记 5/6/7]

- **SPEC-M3-08 审批权 fail-closed（D-32）**：`submit_approval` 仅**实例已登记且角色=审批人**的人员可决断；
  未登记人员（角色 None）与实例未登记任何人员（actor_roles 空）一律 `REJECTED/APPROVER_NOT_AUTHORIZED`
  并落 `approval.denied{reason: APPROVER_NOT_AUTHORIZED}` 审计——审批权威无法建立时不得静默放行
  （00 v2 §1.4 R-授权规则）。decision 非 GRANT/DENY → `REJECTED/BAD_APPROVAL_DECISION`；action_id 不在
  队列（已决断/超时/不存在）→ `REJECTED/NO_PENDING_APPROVAL`。角色花名册缺省自实例 `env.operators`
  装载（构造可覆盖）。GRANT 只放行单次（payload `single_shot: true`），policy 缺省不变。oracle 证据：
  `src/m3_action/gateway.py:244-277`（257-258 角色判定、262-266 空花名册分支、267-271 审计事件、
  270 reason、275-276 错误码）、`:279-285`（BAD_APPROVAL_DECISION）、`:248-254`（NO_PENDING_APPROVAL）、
  `:123-126`（actor_roles 缺省自 env.operators）、`:307-311`（GRANT single_shot）。EVAL：M3-08-N
  （未登记人员 OP-999 被拒）/ M3-05-N2（GRANT 不改缺省）。
  [v2Δ D-32: v1 完全未写审批主体授权；oracle fail-closed 收紧（原实现对未登记/空花名册两种情形静默放行，
  评审后收紧）；tests/CHANGELOG.md 安全规程判据落地 4；commit 06ce55a]

### 3.4 执行

- **SPEC-M3-09 幂等与执行前日志（D-28 幂等半）**：幂等键两档策略（受控集
  `CALLER_PROVIDED` / `CALLER_PROVIDED_UNIQUE_ARGS`，由适配器声明：读/分析类 7 动作 = CALLER_PROVIDED，
  其余写/执行/报告类 9 动作 = CALLER_PROVIDED_UNIQUE_ARGS）。同 `idempotency_key` 重复请求返回**首个结果**
  （含原 action_id 与原 status），不重复执行；UNIQUE_ARGS 策略下同 key 承载不同 (capability, arguments) →
  `KEY_CONFLICT` 拒绝（走准入通道，不进主链）。write-ahead：执行副作用**之前**先落 claim 记录到
  `runtime/m3_action/idempotency.jsonl`（journal 重放重建幂等表）；执行器崩溃后同 key 重试命中 claim →
  返回首个结果、零二次副作用（SIMULATION 路由下以 M5 `env.state_final()` 快照 diff 验证）。执行完成后
  `complete` 覆盖 journal 终态（同 key 后续命中返回终态）；审批终态（DENY/timeout）同样回写 journal
  （同 key 重试返回终态 REJECTED 而非过期 WAITING_APPROVAL——独立评审缺口修复 5）。oracle 证据：
  `src/m3_action/registry.py:51`（受控集）；`tools/` 16 适配器 `IDEMPOTENCY_KEY_POLICY` 声明（本会话
  grep 全量核对：query.*/analyze.* 7 个 = CALLER_PROVIDED，其余 9 个 = CALLER_PROVIDED_UNIQUE_ARGS）；
  `src/m3_action/executor.py:24-33`（KEY_CONFLICT）、`:48-57`（重放）、`:79-102`（claim：UNIQUE_ARGS 校验
  `:92-98`、write-ahead `:100-101`）、`:104-112`（complete 覆盖）；`src/m3_action/gateway.py:109-113`
  （journal 挂载与策略回调）、`:179-193`（claim 命中即返回首结果）、`:406-412`（_finish 统一回写）。
  EVAL：M3-09-P（同 key 二发同 action_id 同 status、executions=1、快照零 diff）/ M3-09-P2（崩溃 claim 重试
  executions=0、快照零 diff）。
  [v2Δ D-28: v1 只写"同 key 返回首个结果"；oracle 补两档键策略、KEY_CONFLICT 负向、write-ahead claim、
  崩溃重试与审批终态回写；tests/CHANGELOG.md M3 登记 5/6/7+独立评审缺口修复 5]

- **SPEC-M3-10 证据三态与失联执行器（D-29）**：`SUCCEEDED` 必须 intended/issued/observed 三者齐全
  （contracts 构造级强制，01 v2 §2.2）；`observed` 只认**环境回读**（SIMULATION=M5 环境回读；REAL=适配器
  二次读）——自报成功不构成 observed。失联执行器建模 `isolate_execution_env`：执行副作用落在
  `env.deep_copy()` 副本上（执行器在副本自报成功），observer 独立回读**真实环境**发现未兑现 issued 声明 →
  降级 FAILED/`OBSERVATION_MISMATCH`，绝不标 SUCCEEDED（verify 异常按不通过保守降级）。适配器契约：
  `readback(env, arguments, action_id)` 只负责"读哪里"，判定归 observer；`verify(arguments, issued, observed)`
  提供动作核对口径。oracle 证据：`src/contracts/core.py:199-204`（SUCCEEDED 三态构造级强制）；
  `src/m3_action/observer.py:30-34`（readback）、`:36-46`（verify）、`:49-97`（assemble：自报降级 `:58-73`，
  错误码 `:20`）；`src/m3_action/gateway.py:93,97-99`（isolate 选项）、`:377-388`（副本执行）、`:390-401`
  （真实环境回读 + 组装）。EVAL：M3-10-P（isolate 下 GRANT 后 FAILED/OBSERVATION_MISMATCH、真实环境零变化）。
  [v2Δ D-29: v1 为文字规则"自报成功不构成 observed"；oracle 给出可测落位（deep_copy 副本 + observer 降级）；
  tests/CHANGELOG.md M3 登记 8]

- **SPEC-M3-11 执行路由与 REAL 门禁三重（D-31）**：EVAL/黄金集运行期间强制 SIMULATION——gateway
  `evaluation=True` 或环境变量 `PD_EVALUATION` 置位时请求 REAL → 拒绝 `REAL_FORBIDDEN_IN_EVAL`（01 v2 §8
  仿真即默认）；非评估上下文请求 REAL 需：环境变量 `PD_REAL_MODE` 置位（否则 `REAL_NOT_CONFIGURED`）+
  双人开关（两个**不同**审批人 id，否则 `REAL_DUAL_SWITCH_REQUIRED`）齐备，且仅 mock 适配器——REAL 路由
  唯一返回形态 = FAILED/`REAL_MOCK_ONLY`（无真实设备协议）；模式串非法 → `UNKNOWN_MODE`。REAL 拒绝走
  准入通道（不进生命周期，SPEC-M3-02）。oracle 证据：`src/m3_action/router.py:16-28`（模式/环境变量/错误码
  常量）、`:44-54`（evaluation 读取与双人开关去重）、`:56-82`（resolve 四级拒绝）；`tools/_base.py:27-54`
  （REAL_MOCK_RESULT/real_mock_execute）；`src/m3_action/gateway.py:115`（Router 挂载）、`:170-177`（路由
  解析在主链之前）、`:372-375`（REAL 执行分派）。EVAL：M3-11-P / M3-11-N / M3-11-N2 / M3-11-P2（逐级接线）。
  [v2Δ D-31: v1 写"环境变量+双人审批开关"两重；oracle 为三重（评估上下文强制 SIMULATION 为第一重）
  且错误码分级；tests/CHANGELOG.md M3 登记 10]

### 3.5 确定性与安全边界

- **SPEC-M3-12 trace/事件确定性口径（D-30）**：ActionRequest 冻结结构无 trace 字段（01 v2 §2.1 不可擅改）
  → `trace_id` 从 task 派生（`trace-<task_id>`；显式 trace_id 形参可覆盖）；事件 `event_id` = 流内递增序号
  `EVT-M3-<seq:06d>`（从既有文件行数续起，journal 重放续序；ULID 双形态兼容见契约层 D-03，唯一性域=事件流）；
  事件分片与 M2 对齐 = `task-<task_id>.jsonl`；每条记录经 `contracts.EventRecord` 契约校验，缺 trace_id 写入即拒
  （`EventWriteError`）；同操作序重放产生逐字节相同事件流（无随机量）。M3 自产结果（准入拒绝/判定/审批中间态）
  `latency_ms` 恒 0；SIMULATION 执行结果 latency_ms 透传 M5（确定性常数口径见 M5 v2 D-42 条款）。
  角色覆盖审计事件无任务上下文 → 落独立审计流（`policy:<role>` 主题，`trace-policy-<subject>`）。
  oracle 证据：`src/m3_action/gateway.py:165`（trace 派生）、`:434`（准入 trace 同口径）、`:500`（latency_ms=0）、
  `:456-459`（审计流回调）；`src/m3_action/events.py:8-11`（确定性 docstring）、`:48-57`（EVT-M3-<seq>）、
  `:80-83`（契约校验缺 trace_id 即拒）、`:108-110`（task 分片）；`src/m3_action/policy_engine.py:198`
  （subject=policy:<role>）。EVAL：EVAL-M3-12-P（m3.determinism：双沙箱同操作序重放
  逐字节一致 + EVT-M3-<seq> 流内严格递增含 restart 续序 + trace_id 派生断言）/
  EVAL-M3-12-N（事件记录缺 trace_id 契约拒绝，复用 tests/fixtures/events_missing_trace.jsonl）。
  [v2Δ D-30: v1 无 trace/事件确定性条款；oracle 成文；tests/CHANGELOG.md M3 登记 9；event_id 形态并入契约层 D-03]

- **SPEC-M3-13 SAFE-ISSUE-HUMAN 的 M3 落位（D-33）**：`create.switch_order` PARAMS_SCHEMA `status` 枚举
  **收窄为 [DRAFT]**——agent 请求登记 ISSUED（或任何非 DRAFT）状态 → 准入拒绝 `SCHEMA_INVALID`；
  签发动作不属于任何 agent 动作集，DRAFT→ISSUED 只能由持证签发人（角色数据源 = 实例 `env.operators`）
  在 agent 动作集之外完成；M5 判据层对非 DRAFT 请求一律 FAILED/`SAFE_ISSUE_HUMAN`（M3 准入拒绝 + M5
  兜底双保险）。oracle 证据：`tools/create__switch_order.py:29-31`（enum: [DRAFT]）、`:4-9`（docstring 安全
  声明）、`:12-14`（issuer 仅草稿登记）；`src/m5_simulation/scenario.py:229-250`（SAFE_ISSUE_HUMAN 判定
  `:233-237`；DRAFT 登记与合规观测 `:238-250`）；`src/m3_action/gateway.py:123-126`（角色数据源=env.operators）。
  EVAL：M3-13-N（自铸 ISSUED 票准入拒绝）。
  [v2Δ D-33: v1 无此条款（原 [DRAFT, ISSUED] 缺省 ISSUED——agent 可零审批自铸已签发票，安全评审收紧）；
  tests/CHANGELOG.md 安全规程判据落地 1；commit 06ce55a]

- **SPEC-M3-14 时间纪律与墙钟边界**：`m3_action` 无电价判定义务、零电价语义（01 v2 §8 判价只允许 M5
  BUSINESS 时钟）；模块内唯一真实时钟读取位 = `clocking.now_iso()`（仅服务审批超时的缺省比较基准与事件
  时间戳缺省，集中一处便于审计与扫描）；时间戳一律 UTC ISO-8601，双形态兼容（契约层 D-04）；EVAL/黄金集
  一律显式传 `now`（确定性重放，不触墙钟——test_m3.yaml 全部 25 用例 requested_at/now 显式）。oracle 证据：
  `src/m3_action/clocking.py:1-8`（域声明）、`:59-65`（now_iso 唯一墙钟位；`# pragma: no cover`）；
  `tests/test_m3.yaml:17-20`（公共模板注释：requested_at/now 全部显式）。
  EVAL：EVAL-M3-14-P（m3.time_discipline：声明式墙钟词面扫描+补丁 now_iso 后
  显式 now 探针全链跑通；扫描面/禁用词面/探针全部来自用例 params）。
  [v2Δ: v1 无时间条款；tests/CHANGELOG.md M3 登记 11（时间纪律），按 oracle 成文]

### 3.6 负向证明与已知缺陷

- **SPEC-M3-15 write-path 负向测试矩阵（CI 常驻）**：**"只读"是测试结论，不是声明**——对矩阵声明的全部
  写类动作（工单/操作票/巡检记录/报告/遥控/投切 6 条），在 read-only persona（角色覆盖全部收紧）下经
  ActionGateway 发起，逐动作三重断言：① Policy 判定 ∈ {DENY, ASK}（`action.policy_decided` 事件）且等于
  矩阵期望；② 终态绝不出现 EXECUTING/SUCCEEDED/COMPENSATED；③ 零副作用：M5 环境状态快照
  （`env.state_final()`）逐动作前后 diff 为空。矩阵是数据（`tests/negative_matrix.yaml`：动作集/角色覆盖/
  期望判定/请求参数全部来自文件，执行器零特判）；persona 覆盖只做合法单向收紧（ALLOW→DENY、ASK→DENY）；
  `execute.remote_control` 因 ASK 永久锁定不可覆盖 → 期望缺省 ASK（WAITING_APPROVAL 不执行，零副作用
  同样成立——D-25 的矩阵落位）。执行沙箱 `runtime/m3_eval/negative_matrix`（先清空，独立可复跑），矩阵
  事件流独立（`events_dir` 隔离）。oracle 证据：`src/m3_action/negative_test.py:1-14`（三重断言 docstring）、
  `:63-89`（沙箱与 persona 装配）、`:95-135`（逐动作断言）；`tests/negative_matrix.yaml:8-24`（meta/persona）、
  `:37-80`（6 动作矩阵）；`src/m5_simulation/env.py:426`（state_final）。EVAL：M3-15-P（actions: 6，
  side_effect_free: true）。
  [v2Δ: v1 为散文条款；oracle 矩阵数据化 + 三重断言成文；remote_control 期望 ASK（非 DENY）随 D-25]

- **SPEC-M3-16【KNOWN-DEFECT D-59】modify.asset_history PARAMS_SCHEMA 形态缺陷（登记不修）**：
  **当前行为**：`tools/modify__asset_history.py` PARAMS_SCHEMA `required: ["device","entry"]` 中 `entry` 为
  无子结构约束的裸 `"type":"object"`（仅 description"台账条目（永不执行，仅记录意图）"），schema 形态不收敛
  （任意 object 皆过 ④ 段校验；对照 `tools/modify__protection_setting.py:11-18` 同形态）。
  **已知缺陷**：schema 不具收敛校验力。**为何不修**：该动作缺省 Policy=DENY 且 policy_locked（SPEC-M3-05
  红线），任何角色/审批均不可放行、永不执行，schema 仅具准入记录意义，收敛无行为收益。
  **v2 处置**：KNOWN-DEFECT 登记；后续如做 DENY 动作 schema 规范，可显式豁免或统一形态。
  oracle 证据：`tools/modify__asset_history.py:10-17`（entry 裸 object :15）；`tools/modify__protection_setting.py:11-18`
  （同形态）；`ontology/actions.yaml`（modify.asset_history：default_policy: DENY / policy_locked: true）；
  `src/m3_action/validator.py:105-106`（object 校验仅查 Mapping，无属性收敛——本缺陷的机制位）。
  EVAL：EVAL-M3-16-N（钉死当前行为：entry 任意 object 过准入〔缺陷形态〕+ DENY
  红线兜底 DENIED/POLICY_DENIED；KNOWN-DEFECT 登记不修）。
  [v2Δ D-59: 验收发现未修；登记不修]

---

## 4. Eval（`tests/test_m3.yaml` · 按本 spec v2 重生成，现行 30 用例）

套件数据驱动，执行器插件两模块：`m3_action.eval_plugin`（m3.execute 网关场景驱动 / m3.registry
注册表一致性 / m3.negative_matrix 只读矩阵）+ `tests.fixtures.m3_eval_plugin`（m3.determinism /
m3.time_discipline，本轮新增，tests 侧插件按 EVAL-SCHEMA §4 协议）。每用例在 `runtime/m3_eval/<case-id>`
独立沙箱执行（先清空，独立可复跑）。v2 条款↔EVAL 双向映射 = 本表（条款→用例）+ 套件内用例 `spec`
字段回指条款 id。spec_ref 仍指向 v1 四文件（spec_hash `91b5cab1…` 口径不变，v1 原文未改写）；
eval_hash `d3c53375…` = 变异缺口修复后 tests/test_m3.yaml 的 sha256（tests/CHANGELOG.md 同日条目登记，01 §6 协议；历史链：c0e18096… 重生成 29 例、eb1a6b01… v1 基线）。

| v2 条款 | EVAL 用例（正 P / 负 N） | 断言要点 |
| --- | --- | --- |
| SPEC-M3-01 | 01-P ｜ 01-N 01-N2 | ALLOW 直执行链；UNREGISTERED（不进主链+admission 审计）；NOT_DISCLOSED |
| SPEC-M3-02 | 01-N 02-N 02-N2 | CONTRACT_INVALID（缺 idempotency_key）；SCHEMA_INVALID+arguments.device 路径；admission 审计与主链事件缺席 |
| SPEC-M3-03 | 03-P 03-P2 | diff 空（16 动作+create.switch_order/execute.remote_control 独立注册）；不可改清单双重表达+生命周期表 vs frozen_state_machines.yaml |
| SPEC-M3-04 | 04-P 04-P2 04-N ｜ 05-N（兼证 DENIED 终态） | ALLOW 四事件链；ASK→WAITING_APPROVAL+approval.requested；DENY→DENIED/POLICY_DENIED；未入动作表动作第二道防线仍 DENY（04-N，红线 1） |
| SPEC-M3-05 | 05-N 05-N2 05-N3 | 超管锁定 DENY（locked:true）；锁定动作一切覆盖 override_rejected（含收紧方向）；GRANT 只放行单次、缺省不被改写 |
| SPEC-M3-06 | 06-P | 收紧 ASK 生效（override_applied）；放宽回缺省 ALLOW 被拒（基准=当前生效判定）；复验维持 ASK |
| SPEC-M3-07 | 07-P 07-P2 | 301s→REJECTED/APPROVAL_TIMEOUT+payload.timeout+approval.timeout；approvals.jsonl 重启重放 GRANT 续执行 |
| SPEC-M3-08 | 08-N ｜ 05-N2 07-P2（正例内嵌） | 未登记审批人 REJECTED/APPROVER_NOT_AUTHORIZED+approval.denied 审计；登记审批人 GRANT 成功 |
| SPEC-M3-09 | 09-P 09-P2 | 同 key 二发同 action_id/status（executions=1、快照零 diff）；崩溃 claim 同 key 重试 executions=0 |
| SPEC-M3-10 | 10-P | isolate_execution_env→FAILED/OBSERVATION_MISMATCH，真实环境快照零变化 |
| SPEC-M3-11 | 11-P 11-N 11-N2 11-P2 | 三重门禁逐级：REAL_FORBIDDEN_IN_EVAL→REAL_NOT_CONFIGURED→REAL_DUAL_SWITCH_REQUIRED→REAL_MOCK_ONLY |
| SPEC-M3-12 | 12-P 12-N | 双沙箱逐字节一致+EVT-M3-<seq> 流内严格递增（restart 续序）+trace_id=trace-<task_id>；缺 trace_id 契约拒绝（复用 fixtures/events_missing_trace.jsonl） |
| SPEC-M3-13 | 13-N ｜ 09-P（正例内嵌 DRAFT 登记路径） | 自铸 status=ISSUED 操作票 REJECTED/SCHEMA_INVALID（枚举仅 DRAFT） |
| SPEC-M3-14 | 14-P | 墙钟词面扫描（src/m3_action+tools，唯一豁免 clocking.py）零命中+补丁 now_iso 后显式 now 探针全链跑通 |
| SPEC-M3-15 | 15-P | read-only persona 全写类矩阵 6 动作全 DENY/ASK，M5 状态 diff 空 |
| SPEC-M3-16 | 16-N | KNOWN-DEFECT 当前行为钉死：entry 裸 object 过准入（缺陷形态）+ DENY 红线兜底 DENIED/POLICY_DENIED（登记不修） |

> 套件统计：30 用例（正例 16 / 负例 14），16 条款每条 ≥1 用例。04-N/12-P/14-P/16-N 与 12-N 本会话冒烟实跑
> 通过（未入表动作 DENIED；双沙箱 11 事件逐字节；扫描 30 文件零命中+探针 3 步；缺 trace_id 被拒）；统一门禁
> `python run_evals.py --module all` 由编排方统一复跑（本轮未跑）。
> 改名对照（用例内容与旧版一致，断言对象已逐条核对 v2 条款）：08-P/P2→09-P/P2、09-P→10-P、
> 10-P/N/N2/P2→11-P/N/N2/P2、11-P→15-P、APPR1-N→08-N、APPR2-N→13-N。

---

## 5. DoD（按 oracle 现行口径）

- EVAL 全绿：`python run_evals.py --module m3` → 30/30 PASS（重生成前基线 25/25 见 tests/CHANGELOG.md；
  统一门禁由编排方复跑）；
- 注册表与本体动作表 100% 对齐（`registry_vs_actions_table_diff` 恒空，16 动作独立注册）；
- 不可改清单双重表达一致（代码硬编码 vs `ontology/actions.yaml` policy_locked，`assert_immutable_consistency`）；
- ACTION 生命周期表 `ACTION_TRANSITIONS` vs `tests/fixtures/frozen_state_machines.yaml` diff 为空；
- 审批队列持久化：重启不丢 WAITING_APPROVAL、GRANT 可续执行（EVAL-M3-07-P2）；
- 幂等 write-ahead：崩溃 claim 同 key 重试零二次副作用（EVAL-M3-09-P2）；
- 准入失败不进主链（事件缺席断言）+ 审批权 fail-closed（EVAL-M3-08-N）；
- 事件流确定性重放逐字节一致（EVAL-M3-12-P）+ EVAL 路径零墙钟（EVAL-M3-14-P）。

---

## 6. 交付物

`src/m3_action/`（13 文件，见 §2）+ `tools/` 16 个动作适配器与 `_base.py`（SIMULATION 路由实作=委托
M5 `simulate()`；REAL 仅 mock 签名）+ `tests/test_m3.yaml`（30 用例）+ 负向测试矩阵
`tests/negative_matrix.yaml`（6 写类动作只读矩阵）+ EVAL 执行器插件 `src/m3_action/eval_plugin.py`；
运行期审计件形态：`runtime/m3_action/{idempotency,approvals}.jsonl`、`runtime/events/task-<task_id>.jsonl`。
[v2Δ: v1 交付物清单缺 eval_plugin.py 与运行期审计件口径，按 oracle 实际目录补全]
