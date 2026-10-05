# EVAL-SCHEMA · tests/test_m<id>.yaml 用例文件规范（S0 制定，全模块通用）

> 本文是 `run_evals.py` 读取的 EVAL 用例文件（suite 文件）的**权威 schema 说明**。
> 后续 M1–M7 模块的 `tests/test_m<id>.yaml` 必须遵循本文；schema 校验由 runner 内
> `validate_suite_schema` 执行，校验失败整个 suite 记 `INVALID`（验收不通过）。
> 用例一律数据驱动，**runner 不允许硬编码特判**；模块特有逻辑通过"插件执行器"注入。

## 1. Suite 文件结构

文件位置：`tests/test_<module>.yaml`（module ∈ `m0..m7`；`m0` 为 S0 基座套件）。

```yaml
suite: m1                          # 必填；模块 id，必须是 m0..m7 之一
title: M1 Agent Core EVAL          # 必填；中文标题
spec_ref:                          # 必填；本套件的行为规格来源（字符串或字符串列表）
  - specs/M1-agent-core.md
  - specs/01-contracts.md
spec_hash: <sha256 hex>            # 必填；spec_ref 列表按序拼接文件字节的 sha256（01§6 口径）
executors:                         # 可选；模块注册的自定义执行器插件
  - module: m1_core.eval_plugin    #   import 路径（sys.path 含 src/）；须暴露 EXECUTORS dict
cases:                             # 必填；非空用例列表
  - id: EVAL-M1-01-P               # 必填；格式 EVAL-M<模块号>-<序号>-(P|N<n> 或 P<n>)，正则 ^EVAL-M\d+-[A-Za-z0-9]+-(P\d*|N\d*)$
    spec: SPEC-M1-01               # 必填；对应行为规格条款 ID（或契约小节引用）
    title: 正常 3 轮任务            # 必填；中文场景描述
    form: event_sequence           # 必填；Eval 形态（见 §2）
    executor: m1.replay            # 可选；显式指定插件执行器（缺省按 form 取内置执行器）
    params: { }                    # 必填；执行器输入（按 form/执行器定义）
    expect: { }                    # 必填；期望（按 form/执行器定义，可为空对象）
    skip: {reason: "M5 未交付"}    # 可选；跳过（必须给原因）；SKIPPED 不算失败
```

**spec_hash 协议（01§6 重生成协议）**：runner 每次加载 suite 时对 `spec_ref` 文件
重算 sha256 并与声明的 `spec_hash` 比对，不一致 → suite 记 `SPEC_DRIFT`
（规格已变更而 EVAL 未重生成），该模块验收失败。重生成后在 `tests/CHANGELOG.md`
登记新的 `spec_hash → eval_hash` 对。`eval_hash` 由 runner 计算（suite 文件本身的
sha256），随每次运行写入 `runtime/eval_results.json`。

## 2. Eval 形态（七类必备 + 一个通用形态）

| form | 形态 | 内置执行器 params | expect |
| --- | --- | --- | --- |
| `event_sequence` | 事件序回放 | `{file: <jsonl>, pattern: [<事件type 或 "*">...]}`；逐条按 `contracts.EventRecord` 校验（缺 trace_id 即拒），pattern 按序匹配（`*` 通配单条） | `{matched: true}` 或 `{error_contains}` |
| `state_transition` | 状态迁移断言 | `{machine: task\|action\|artifact, table: <yaml>, checks: [{from, to, expect: allowed\|rejected}]}` | checks 自带期望 |
| `policy_decision` | 策略三值 | `{capability, actions_table, role_override?, actor_role?}`；参照语义：缺省 Policy + 单向收紧（ALLOW→ASK→DENY）+ 不可改清单（policy_locked） | `{decision: ALLOW\|ASK\|DENY, override_rejected?}` |
| `idempotency` | 幂等 | `{requests: [ActionRequest dict, ...]}`；同 key 返回首个结果不重复执行 | `{same_action_id: bool, executions: n}` |
| `expression` | 表达式判据 | `{expression, facts}`；安全求值器（无 eval/exec），见 §3 | `{result: bool}` 或 `{error_contains}` |
| `negative_rejection` | 负向拒绝 | `{attempt: contract_load\|event_append\|ontology_load\|regulation_load, structure?, payload?, file?}` | `{error_contains?}`；未拒绝=失败 |
| `performance` | 性能门槛 | `{workload: ontology_load_all\|contract_roundtrip\|event_validate, iterations, structure?, payload?}`；计时用 `time.perf_counter`（MONOTONIC 语义） | `{max_ms}`；超门槛=失败 |
| `contract` | （通用）冻结结构 round-trip / 预期拒绝 | `{structure: <01§2 结构名>, op: roundtrip\|reject, payload}` | roundtrip：`to_dict` 与 payload 归一化相等；reject：`{error_contains?}` |

形态语义说明：

- **事件序回放**：断言"事件流里按顺序出现/不出现什么"。JSONL 每行一个 EventRecord
  dict；pattern 为事件 `type` 字面量的有序序列（允许 `*` 通配符），按有序子序列匹配。
- **状态迁移断言**：迁移表文件为 `{machines: {task: {状态: [可达状态...]}, ...}}`；
  S0 提供 `tests/fixtures/frozen_state_machines.yaml`（01§5 三状态机的机械转写，
  M1/M2/M3 的表驱动实现必须与它 diff 为空）。
- **策略三值**：`role_override` 语义 = M3 的"单向收紧"（ALLOW→ASK、ALLOW→DENY、
  ASK→DENY 允许；放宽一律拒绝且决策维持缺省）；`policy_locked: true` 的动作
  （remote_control 的 ASK、三个 CRITICAL 的 DENY）任何覆盖都被拒绝。
  此内置执行器是**参照实现**（判定对象是 ontology/actions.yaml 数据），M3 的
  policy_engine 交付后应以 M3 执行器为准并保留本形态的参数/期望口径。
- **幂等**：`requests` 逐个经 `ActionRequest.from_dict` 契约校验后按
  `idempotency_key` 入模拟表；`executions` = 实际执行的次数。
- **表达式判据**：语法见 §3。这是 M6 `deterministic` 判据的基座口径；
  M6 交付 `JUDGE-SYNTAX.md` 后可扩展，但不得破坏本文列出的最小语法。
- **负向拒绝**：`contract_load`/`event_append` 走契约校验（`ContractValidationError`）；
  `ontology_load`/`regulation_load` 走轻量本体校验（枚举封闭性 + 规则/动作必有 id，
  见 runner 内 `validate_ontology_data`）。
- **性能门槛**：内置 workload 三种；模块可用插件执行器实现自定义 workload
  （返回 `metrics.measured_ms`）。门槛值是**数据**（写在 `expect.max_ms`），不是代码。

## 3. 判据表达式语法（expression 形态）

- 字面量：数字（`1`、`0.9`）、字符串（`'COMPLETED'` 或 `"COMPLETED"`）、
  布尔（`true/false/True/False`）、空值（`null/None`）、列表 `[a, b]`。
- facts 引用：点分路径 `outcome.status`、`evidence.observed_present`。
- **全大写裸标识符**（`^[A-Z][A-Z0-9_]*$`，且不是 facts 路径）按枚举字符串常量处理：
  `outcome.status == COMPLETED` 等价于 `outcome.status == 'COMPLETED'`（兼容 M6 判据惯例）。
- 运算符（优先级从低到高）：`or/||` → `and/&&` → `not/!` → 比较
  `== != > < >= <= in` → `+ -` → `* / %` → 一元 `+ -` → 括号/字面量/路径。
- 禁止：函数调用、赋值、属性执行、`eval/exec`、import——求值器只读 facts。
- 未知标识符/语法错误 → `ExpressionError`（用例可用 `expect.error_contains` 断言）。

## 4. 插件执行器协议（模块自定义）

```python
# src/m1_core/eval_plugin.py（示例）
EXECUTORS = {
    "m1.replay": replay_executor,   # 名字约定：<包>.<功能>
}

def replay_executor(case: dict, ctx) -> dict:
    # case = 用例 dict（params/expect 原样可读）
    # ctx  = EvalContext：ctx.root（仓库根 Path）、ctx.resolve(rel)、
    #        ctx.load_yaml(rel)、ctx.load_jsonl(rel)；sys.path 已含 src/（可 import contracts）
    return {"passed": True, "detail": "中文说明", "metrics": {"任意": "标量"}}
```

- suite 用 `executors: [{module: ...}]` 声明；case 用 `executor: <名字>` 指定。
- 插件导入失败 / 未暴露 `EXECUTORS` / 执行器不可调用 → suite 记 `INVALID`。
- 插件执行器内部异常由 runner 捕获记 `FAILED`（含 traceback 摘要），不会中断整个运行。
- S0 参考实现：`src/contracts/eval_plugin.py`（contracts.roundtrip / enum_closure /
  actions_table / rules_registry / seed_check）。

## 5. 运行与退出码

```bash
python run_evals.py --selftest        # schema 自检 + 隔离断言 + 目录完整性
python run_evals.py --module m1      # 单模块
python run_evals.py --module all     # 全量（m0..m7）
```

- **每次运行先跑隔离断言**（scripts/ci_isolation.py）；命中即整体失败。
- 摘要行为 ASCII（`EVALS mode=... isolation=... modules=... cases=... result=...`）；
  明细（逐用例 status/detail/metrics/duration_ms）写 `runtime/eval_results.json`。
- 退出码：`0` 全部通过；`1` 存在失败（含隔离/完整性/schema/SPEC_DRIFT）；`2` 用法错误。
- suite 文件缺失 → 该模块记 `PENDING`（不算失败，待模块交付补齐后纳入）；
  suite 存在但任一用例失败 → 模块失败。
- 用例级状态：`PASSED` / `FAILED` / `SKIPPED`（带 skip.reason）。
