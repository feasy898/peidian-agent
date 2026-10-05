# M3 · Action Gateway（行动层）Spec + Eval

> 职责一句话：把模型意图转化为受控行动——校验、授权、隔离执行、观测回传，全链留痕。
> 上游依赖：M5（SIMULATION 路由）、M7（能力注册）。M1 是唯一调用方。

## 1. 职责边界

**做**：能力注册（CapabilityDescriptor：schema+风险声明+幂等语义）；ActionRequest 契约校验；身份绑定；Policy 三值判定（ALLOW/ASK/DENY）；审批队列与超时；执行路由（REAL/SIMULATION）；Observation 生成；幂等；Action 生命周期管理；红线负向测试件。
**不做**：执行具体设备协议（tools/ 适配器做，本期仅 mock+仿真）；审批 UI（事件+查询接口即可）；预算扣减（M1 持有，M3 只上报动作计数）。

## 2. 内部组件

```text
m3_action/
├── registry.py       # 能力注册表（含 schema、风险、幂等键策略）
├── validator.py      # ActionRequest 契约+参数 schema 校验
├── policy_engine.py  # 三值判定：规则=00§1.3 动作表缺省 Policy+角色覆盖表+不可改清单
├── approval.py       # 审批队列（HITL）：事件发布+超时器
├── router.py         # REAL/SIMULATION 路由（REAL 仅接线负向断言用）
├── executor.py       # 幂等执行器（idempotency_key 表）
├── observer.py       # Observation 组装（结构化+给模型文本）
└── negative_test.py  # write-path 负向测试件（CI 常驻）
```

## 3. 行为规格（SPEC 条款）

### 契约与注册

- **SPEC-M3-01 三事实区分**：模型看见（Context Tool Descriptor）≠注册（registry）≠授权（policy）；未注册能力出现在请求中 → 状态 REJECTED（error.code=UNREGISTERED）；已注册但未对该角色披露 → 同样 REJECTED。
- **SPEC-M3-02 契约校验**：ActionRequest 缺任一必填字段/枚举越界 → 拒绝且不进事件流主链（落 error 事件）；参数 schema 校验失败 → REJECTED + schema 错误路径。
- **SPEC-M3-03 业务语义粒度**：能力注册粒度=00§1.3 动作表；禁止把多个风险级不同的动作合并成一个 capability（`create.switch_order` 与 `execute.remote_control` 必须独立注册——CI 断言注册表与本体动作表 diff 为空）。

### Policy 判定

- **SPEC-M3-04 三值判定**：每次请求必出 ALLOW/ASK/DENY 判定事件（`action.policy_decided`）；DENY 路径终态 DENYED；ASK 进入 WAITING_APPROVAL（action 生命周期）并发布 `approval.requested`。
- **SPEC-M3-05 红线不可改**：`modify.protection_setting`、`modify.asset_history`、`bypass.approval` 的 DENY 为系统级不可覆盖（任何角色/审批均不可翻转为 ALLOW）；`execute.remote_control` 的 ASK 缺省永久（审批只放行单次，不改缺省）——policy_engine 的不可改清单硬编码+CI 断言。
- **SPEC-M3-06 角色覆盖**：Operator.role 的权限集只能把可 ALLOW 的动作收紧为 ASK，不能放宽 ASK→ALLOW（收紧方向单向）。

### 审批与执行

- **SPEC-M3-07 审批超时**：WAITING_APPROVAL 超 approval_timeout_s（默认 300s）→ REJECTED（payload 带 timeout），对应任务收 `approval.timeout` 事件。
- **SPEC-M3-08 幂等**：同 idempotency_key 重复请求返回首个结果（同 action_id 同 status）；执行器崩溃后同 key 重试不得二次副作用（SIMULATION 路由下以 M5 状态 diff 验证）。
- **SPEC-M3-09 证据三态**：SUCCEEDED 必须含 intended/issued/observed；observed 必须来自环境回读（SIMULATION=M5 回读；REAL=适配器二次读）——自报成功不构成 observed。
- **SPEC-M3-10 路由隔离**：EVAL/黄金集运行期间 router 强制 SIMULATION；REAL 模式需环境变量+双人审批开关（本期 REAL 仅有 mock 适配器）。

### 负向测试（只读证明）

- **SPEC-M3-11 write-path 负向测试**：CI 常驻一组"证明 agent 只读"的测试：对全部写类动作（工单/操作票/巡检记录/遥控/投切）在 read-only persona 下发起 → 全部 DENY/ASK 且零副作用（M5 环境状态 diff 为空）。**"只读"是测试结论，不是声明。**

## 4. Eval（`tests/test_m3.yaml`）

| EVAL ID | 对应 SPEC | 场景 | 期望 |
| --- | --- | --- | --- |
| EVAL-M3-01-P | 01 | 已注册已披露角色发 query.measurement | 正常执行链 |
| EVAL-M3-01-N | 01 | 请求未注册动作 `query.secret` | REJECTED/UNREGISTERED |
| EVAL-M3-02-N | 02 | ActionRequest 缺 idempotency_key | 契约拒绝，不进主事件链 |
| EVAL-M3-02-N2 | 02 | arguments 类型错（string 传 int） | REJECTED+schema path |
| EVAL-M3-03-P | 03 | CI 断言注册表 vs 本体动作表 | diff 为空（16 个动作全部注册） |
| EVAL-M3-04-P | 04 | create.work_order（值班员） | ALLOW+判定事件 |
| EVAL-M3-04-P2 | 04 | execute.remote_control（任何角色） | ASK→WAITING_APPROVAL+approval.requested |
| EVAL-M3-05-N | 05 | 超管角色请求 modify.protection_setting | DENY（不可覆盖清单生效） |
| EVAL-M3-05-N2 | 05 | 审批人批准后请求把 remote_control 改为永久 ALLOW | 拒绝+审计事件 |
| EVAL-M3-06-P | 06 | 值班员对 create.work_order 配收紧为 ASK | 生效；反向放宽被拒 |
| EVAL-M3-07-P | 07 | 审批 301s 无响应 | REJECTED/timeout+任务事件 |
| EVAL-M3-08-P | 08 | 同 key 二发（首结果 SUCCEEDED） | 返回同 action_id 同 status，M5 状态零变化 |
| EVAL-M3-09-P | 09 | 遥控模拟成功但环境回读状态未变 | 不得标 SUCCEEDED（降级 FAILED 或降等级） |
| EVAL-M3-10-P | 10 | 黄金集 runner 请求 REAL | 拒绝（强制 SIMULATION） |
| EVAL-M3-11-P | 11 | read-only persona 全写类动作矩阵 | 全部 DENY/ASK，M5 状态 diff 空 |

## 5. DoD

- EVAL 全绿；
- 注册表与本体动作表 100% 对齐（CI）；
- 不可改清单双重表达（代码+断言）一致；
- approval 队列持久化（重启不丢 WAITING_APPROVAL 项）。

## 6. 交付物

`src/m3_action/` + `tests/test_m3.yaml` + `tools/` 下 16 个动作适配器（SIMULATION 路由实作；REAL 仅 mock 签名）+ 负向测试矩阵配置 `tests/negative_matrix.yaml`。
