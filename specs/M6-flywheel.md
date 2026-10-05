# M6 · Flywheel（飞轮层）Spec + Eval

> 职责一句话：把运行轨迹变成可复用资产——采集轨迹、维护黄金集、驱动 Badcase 闭环与受控自进化（Skill 化）。

## 1. 职责边界

**做**：轨迹采集（四类事件全量导出 TrajectoryRecord）；黄金集管理（GoldenCase 契约、判据执行器）；评估运行（release×golden 矩阵）；Badcase 流程（候选→确认→实验对比→受控采用）；Skill 化管线（验证后的稳定方法→SkillDescriptor 注册）。
**不做**：模型训练（SFT/RL 留接口不实现）；评分基准对外发布（本地跑分即可）。

## 2. 内部组件

```text
m6_flywheel/
├── trajectory.py    # 轨迹导出（M2 事件流+状态→TrajectoryRecord）
├── golden_set.py    # 黄金集管理：cases/*.yaml、版本、判据类型注册
├── judges.py        # 判据执行器：deterministic（表达式引擎）+rubric（结构化评分单）
├── evaluator.py     # release×golden 跑分（调 M5 场景 runner）
├── badcase.py       # Badcase 状态机：OPENED→REPRODUCED→FIX_CANDIDATE→EXPERIMENT→ADOPTED/REJECTED
└── skillize.py      # 稳定方法→SkillDescriptor（含 evidence_policy：黄金成绩提升证明）
```

## 3. 行为规格（SPEC 条款）

- **SPEC-M6-01 轨迹完整性**：export 后的 TrajectoryRecord 与 M2 事件流逐条对应（四类事件不缺）；outcome 与 TaskState 终态一致；缺 trace_id 的轨迹 REJECTED。
- **SPEC-M6-02 黄金契约**：每条 GoldenCase 必须含 task_input/expected_behavior（引用规则 ID 或行为条款）/judge（deterministic 或 rubric）/version/source（DEV 或 HOLDOUT 来源标记）；**HOLDOUT 来源条目禁止进入开发黄金集目录**（CI 断言目录隔离：`golden/dev/` 与 `golden/holdout/` 物理分离，holdout 目录 hash 在验收时由验收人核对）。
- **SPEC-M6-03 判据可执行**：deterministic 判据是声明式表达式（字段引用+比较+布尔组合），runner 可执行；rubric 是每维度 1-5 分+权重+通过线（维度：事实正确性/规程引用正确性/状态变更纪律/拒绝校准/证据完整性五维）。
- **SPEC-M6-04 实验隔离**：Badcase 修复实验必须 A/B（candidate vs current release）同黄金集跑分；仅 candidate 通过且不低于 current 总分才可 ADOPTED；实验记录（两版分数+diff 用例）归档。
- **SPEC-M6-05 受控自进化**：Skill 化必须满足——方法在 ≥3 个不同任务实例出现且判据通过（"第二次发生"最低门槛为 3 是因为防止一次性巧合）+SkillDescriptor 过 M7 评审+进入 Release 的 skill_refs 版本化。
- **SPEC-M6-06 评估与调优单向**：调优侧只能读 release 的黄金成绩与 Badcase 实验，不能直接改生产 release 状态（发布走 M7 流水线）；评估结果全部落 `runs/` 归档可审计。

## 4. Eval（`tests/test_m6.yaml`）

| EVAL ID | 对应 SPEC | 场景 | 期望 |
| --- | --- | --- | --- |
| EVAL-M6-01-P | 01 | 跑完 dev-01 后导出 | 四类事件计数与事件流一致 |
| EVAL-M6-01-N | 01 | 手工注入缺 trace 事件 | 轨迹 REJECTED |
| EVAL-M6-02-P | 02 | 构造 3 条 dev 黄金+2 条 holdout 黄金 | 目录分离，holdout 不被 evaluator 默认拾取 |
| EVAL-M6-02-N | 02 | 试图把 holdout case 复制进 dev 目录 | CI 断言失败（来源标记+hash 校验） |
| EVAL-M6-03-P | 03 | deterministic 判据 `outcome.status==COMPLETED && evidence.observed_present` | 表达式引擎求值正确 |
| EVAL-M6-03-P2 | 03 | rubric 五维评分单 | 权重和=1，输出总分+分维明细 |
| EVAL-M6-04-P | 04 | 修复实验：candidate 92 / current 88 | ADOPTED+实验归档 |
| EVAL-M6-04-N | 04 | candidate 85 / current 88 | REJECTED，生产 release 不变 |
| EVAL-M6-05-P | 05 | 方法出现 3 次判据全过 | skillize 产出 SkillDescriptor 候选 |
| EVAL-M6-05-N | 05 | 出现 2 次 | 不触发 |
| EVAL-M6-06-P | 06 | 调优侧请求直接 flip release 状态 | 拒绝+审计事件 |

## 5. DoD

- EVAL 全绿；
- 12 条开发黄金集种子（v2 行为目录实装：每条含 task_input+判据+五维 rubric）落 `golden/dev/`；
- evaluator 对 mock release 全流程可跑（离线）。

## 6. 交付物

`src/m6_flywheel/` + `golden/dev/case_001..012.yaml` + `tests/test_m6.yaml` + 判据表达式语法文档（内嵌 `src/m6_flywheel/JUDGE-SYNTAX.md`）。

