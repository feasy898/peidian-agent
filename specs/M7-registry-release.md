# M7 · Registry & Release（资产层）Spec + Eval

> 职责一句话：四类 AI 资产（Prompt/Skill/Tool/Agent）的注册、版本、变更评审，以及 Agent Release 的打包与发布门禁。

## 1. 职责边界

**做**：资产注册（AssetDescriptor 四类子契约）；版本与依赖管理；变更评审流水线（proposal→评估→批准→发布）；Agent Release 打包（六要素绑定+行为目录成绩单）；发布门禁（黄金线+契约一致性+红线断言）。
**不做**：评估执行（M6 evaluator 跑分，M7 只消费结果）；本体内容管理（M4 消费，但本体版本进 Release 要素）。

## 2. 内部组件

```text
m7_registry/
├── assets.py       # 四类资产 CRUD+版本链（SQLite）
├── dependencies.py # 依赖解析（release 的 skill_refs/tool_refs 闭包校验）
├── review.py       # 变更评审：PROPOSED→EVALUATING→APPROVED→PUBLISHED（拒绝/撤回分支）
├── release.py      # ReleaseBundle 组装+发布门禁
└── publish.py      # 发布落盘 releases/<id>/（不可变）+ 版本冻结
```

## 3. 行为规格（SPEC 条款）

- **SPEC-M7-01 资产四类**：PromptAsset（模板+变量+编译器）、SkillAsset（M6 契约）、ToolAsset（capability 名+schema+风险+幂等策略）、AgentAsset（AgentContract 全量）；任一资产变更产生新版本号（旧版本只读不覆盖）。
- **SPEC-M7-02 依赖闭包**：Release 打包时解析 skill_refs/tool_refs 闭包；缺失或循环依赖→打包失败；闭包内资产版本必须显式（禁止 floating latest）。
- **SPEC-M7-03 变更评审**：任何 PROMPT/SKILL 变更必须走评审流（proposal 含动机+影响面+关联 Badcase）；评审通过前置=黄金集跑分不低于现行（M6 结果引用）；**跳过评审直接发布在 publish 入口被拒**（代码级断言，无旁路）。
- **SPEC-M7-04 Release 六要素**：ReleaseBundle 必须绑定 model_ref/prompt_refs/skill_refs/tool_refs/ontology_version/golden_scores 全六要素；缺一拒绝打包；golden_scores 必须是本次 release 版本实测（M6 签名），不得手工填报。
- **SPEC-M7-05 发布不可变**：releases/ 下内容只写一次（文件级 immutable：二次写拒绝）；Release 状态机 DRAFT→GATED→PUBLISHED（PUBLISHED 后仅可 SUPERSEDED）。
- **SPEC-M7-06 行为目录绑定**：Release.golden_scores 必须包含行为目录 12 条种子用例成绩+红线类目 100% 断言（缺任一红线通过记录→GATED 失败）。
- **SPEC-M7-07 本体联动**：ontology_version 与 M4 目录 hash 一致性在打包时校验（防"本体已改、release 未更新"的漂移）。

## 4. Eval（`tests/test_m7.yaml`）

| EVAL ID | 对应 SPEC | 场景 | 期望 |
| --- | --- | --- | --- |
| EVAL-M7-01-P | 01 | 注册 Prompt 后改模板 | v1 只读，v2 新记录 |
| EVAL-M7-02-N | 02 | skill 引用 floating latest | 打包拒绝 |
| EVAL-M7-02-N2 | 02 | 闭包缺 skill | 打包拒绝，错误含缺失 ID |
| EVAL-M7-03-P | 03 | 正常评审流（黄金成绩达标） | PROPOSED→…→PUBLISHED 全事件 |
| EVAL-M7-03-N | 03 | 试图绕过评审直发 | publish 入口拒绝+审计 |
| EVAL-M7-04-N | 04 | Release 缺 golden_scores | 拒绝打包 |
| EVAL-M7-04-N2 | 04 | golden_scores 手工填报（无 M6 签名） | 拒绝（签名校验） |
| EVAL-M7-05-P | 05 | PUBLISHED 后再写 releases/<id>/ | 拒绝（immutable） |
| EVAL-M7-06-P | 06 | 12 条目录 11 过+1 红线缺 | GATED 失败，列缺项 |
| EVAL-M7-07-P | 07 | 本体目录改动后打包旧 release | 一致性拒绝 |

## 5. DoD

- EVAL 全绿；
- 评审流状态机与 01§5.4 一致（表驱动）；
- releases/ 目录结构+manifest 格式文档内嵌 `src/m7_registry/RELEASE-FORMAT.md`。

## 6. 交付物

`src/m7_registry/` + `tests/test_m7.yaml` + 初始 AgentContract 资产（六能力域+约束清单，落 `assets/agent_contract_v1.yaml`）。
