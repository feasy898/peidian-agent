# M2 · Information（信息层）Spec + Eval

> 职责一句话：回答"模型此刻应当看见什么"，并管理任务事实与产物的持久化。
> 上游依赖：M7（Skill/Prompt 资产）；被 M1/M3/M6 调用。持有 runtime 全部持久状态。

## 1. 职责边界

**做**：Context 构建管线（8 步确定性编译）与 ContextManifest；System Context 六层结构与 Task Context 组装；上下文压缩四步（Commit/Compact/Rebuild/Validate）；Call/Session/Task 三级管理与 10 态 TaskState 持久化；Event Log/Snapshot/Checkpoint 三种状态表示；Workspace 六目录；Artifact 状态机；四类 Memory 与写入六问过滤；Knowledge 只读检索；Skill 渐进披露（三级）。
**不做**：模型调用（M1）；动作执行（M3）；语义归一化（M4）。

## 2. 内部组件

```text
m2_information/
├── context_builder.py   # 8 步管线：读状态→身份解析→收集源→权限过滤→排序→预算裁剪→压缩→编译+Manifest
├── compactor.py         # 压缩四步：Commit(关键事实落盘)→Compact(摘要)→Rebuild(重建)→Validate(不丢验收缺口)
├── session.py           # Call/Session/Task 三级对象
├── state_store.py       # SQLite：task_state / artifacts / memory / checkpoints
├── event_log.py         # events/*.jsonl 追加写+重建 TaskState
├── workspace.py         # 每任务六目录：inputs/ scratch/ state/ artifacts/ evidence/ manifest/
├── artifact.py          # Artifact 状态机+schema 校验钩子
├── memory.py            # 四类 Memory+写入六问
└── skill_disclosure.py  # level0 常驻/level1 目录/level2 按需加载
```

## 3. 行为规格（SPEC 条款）

### Context 构建

- **SPEC-M2-01 确定性编译**：同 TaskState 版本+同 turn+同资产版本 → ContextManifest.hash 必须一致（纯函数，无时钟泄漏）。
- **SPEC-M2-02 分层结构**：System Context 严格六层（Platform Policy/Agent Contract/Tenant Rule/Runtime Reminder/Selected Skill/Tool Descriptors），冲突按层序前者覆盖后者；Task Context 七源（Goal-Steering/Plan-Todo/Recent/Compacted/Memory/Knowledge/OntologyView）。
- **SPEC-M2-03 预算裁剪**：编译超 token 预算时按优先级从低到高丢弃/压缩（compacted_history 优先压，policy 永不压）；裁剪必须留 Manifest 记录（哪些源被裁）。
- **SPEC-M2-04 Manifest 完整**：Manifest 记录全部 source 的 name/type/tokens/priority/origin；总 token 与各源之和一致。

### 压缩与恢复

- **SPEC-M2-05 压缩四步**：Compact 前必须 Commit（目标/已确认事实/外部副作用/验收缺口/恢复位置五要素落 state/）；Compact 后 Rebuild 的上下文必须包含全部五要素（Validate 步检查，缺任一=失败回滚）。
- **SPEC-M2-06 Checkpoint 恢复**：Checkpoint 含 TaskState 全量+Workspace manifest 快照；恢复后 M1 可续跑（见 M1 SPEC-M1-09 联测）。

### Workspace 与 Artifact

- **SPEC-M2-07 Workspace 隔离**：任务只能读写自己 workspace；跨任务引用只允许 artifacts/ 与 evidence/ 下 READY/PUBLISHED 产物（只读）。
- **SPEC-M2-08 Artifact 状态机**：迁移严格按 01§5.3；PUBLISH 必须过 schema 校验（validation.passed=true），校验失败→REJECTED 且带 detail。
- **SPEC-M2-09 产物即证据**：evidence/ 目录只接受 ActionResult.evidence 三态对象的序列化文件与只读读数快照，不接受模型生成文本。

### Memory

- **SPEC-M2-10 写入六问**：write_memory 必须通过六问（What/Why now/时效/来源可溯/验证状态/冲突检查）；未验证推测（provenance=SPECULATIVE）直接 REJECTED；Knowledge 类条目 agent 只读（变更走 M7 评审）。
- **SPEC-M2-11 记忆分类**：四类隔离存储；WORKING 随任务归档清理；EPISODIC/SEMANTIC/PROCEDURAL 带 TTL（默认 90 天，续期需引用计数>阈值）。

### Skill 披露

- **SPEC-M2-12 渐进披露**：level0 名称常驻 System Context（每 skill ≤10 词）；level1 目录仅在任务能力域匹配时进入；level2 只在 skill 被选中后加载并计入 token 预算；未注册/DEPRECATED skill 不出现在任何层。

## 4. Eval（`tests/test_m2.yaml`）

| EVAL ID | 对应 SPEC | 场景 | 期望 |
| --- | --- | --- | --- |
| EVAL-M2-01-P | 01 | 同状态同轮编译两次 | hash 一致；改任一 source 版本后 hash 变 |
| EVAL-M2-01-N | 01 | 注入墙钟到编译输入 | hash 不受影响（时钟不进 hash） |
| EVAL-M2-02-P | 02 | 检查 100 轮任务的全部 Manifest | 层序恒定，无跳层覆盖 |
| EVAL-M2-03-P | 03 | 预算 4000 tokens，源总量 9000 | 裁剪后≤4000 且 policy 层 token 不变，Manifest 有裁剪记录 |
| EVAL-M2-03-N | 03 | 构造 policy 被裁场景 | 拒绝（policy 永不压）→ 触发预算 PAUSED 而非裁 policy |
| EVAL-M2-05-P | 05 | 50 轮后压缩 | 五要素齐全（Validate 通过） |
| EVAL-M2-05-N | 05 | 篡改 Compact 丢"验收缺口" | Validate 失败回滚，任务状态不变 |
| EVAL-M2-07-P | 07 | 任务 A 引用任务 B 的 scratch 文件 | 拒绝；引用 B 的 PUBLISHED artifact |
| EVAL-M2-07-N | 07 | 任务 A 写 B 的 artifacts/ | 拒绝+审计事件 |
| EVAL-M2-08-P | 08 | REPORT 校验通过 | DRAFT→VALIDATING→READY→PUBLISHED 全事件可回放 |
| EVAL-M2-08-N | 08 | schema 缺字段提交 PUBLISH | REJECTED+detail |
| EVAL-M2-10-P | 10 | 写 EPISODIC（含来源+时效） | 成功，provenance 落盘 |
| EVAL-M2-10-N | 10 | 写 SPECULATIVE 推测 | REJECTED |
| EVAL-M2-10-N2 | 10 | agent 直接改 Knowledge 条目 | 拒绝+审计事件（Knowledge 只读） |
| EVAL-M2-12-P | 12 | 触发 analyze.power_quality 任务 | level1 目录出现对应 skill；未选 skill 的 level2 不加载 |
| EVAL-M2-11-P | 11 | TTL 过期的 EPISODIC | 检索不返回，报告计数 |

## 5. DoD

- EVAL 全绿（数据驱动）；
- event_log 可从空库重建任意 TaskState（与快照 diff 为空）；
- SQLite → PostgreSQL 迁移位（连接串可配）预留但不在本期实现。

## 6. 交付物

`src/m2_information/` + `tests/test_m2.yaml` + workspace/artifact 存储格式文档（内嵌 `src/m2_information/FORMATS.md`）。
