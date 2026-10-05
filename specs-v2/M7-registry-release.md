# M7 · Registry & Release（资产层）Spec v2 + Eval

> **v2 定位**：本文件由 oracle（唯一事实源）反提——以 `src/m7_registry/` 现行实现
> （8 组件 + RELEASE-FORMAT.md）、`tools/` 适配器声明、`tests/test_m7.yaml` 现行 16 用例、
> `releases/rel-0001/` 发布基线逐条对照重写；v1 原文（`specs/M7-registry-release.md`）保留不删。
>
> **v1→v2 条款映射**（v2 编号重排，映射不删除）：
>
> | v1 条款 | v2 条款 | 说明 |
> | --- | --- | --- |
> | SPEC-M7-01 资产四类 | §2.1 + §2.2 + §2.3 | 拆为：四类子契约校验 / 版本链与不可变 / 引用与解析 |
> | SPEC-M7-02 依赖闭包 | §2.4 | 增依赖边数据源与三类错误口径 |
> | SPEC-M7-03 变更评审 | §2.5 + §2.6 + §2.7 | 拆为：评审流状态机 / 评审基线 / publish_asset 无旁路 |
> | SPEC-M7-04 Release 六要素 | §2.8 + §2.9 | 拆为：六要素绑定（含空值口径 D-61）/ M6 双层签名链（D-63） |
> | SPEC-M7-05 发布不可变 | §2.12 | 并入 Release 状态机 + 只写一次 + resolve 复核 |
> | SPEC-M7-06 行为目录绑定 | §2.10 | 落位为 gate_release 五项检查 |
> | SPEC-M7-07 本体联动 | §2.11 | 增 M4 目录 hash 机械口径 |
> | （v1 未成文） | §2.13–§2.17 | 发布物形态 / AgentContract 契约 / diff_release / rel-0001 基线+CLI / 审计事件与台账 |
>
> 偏差吸收：D-60→§2.5/§2.12/§2.17；D-61→§2.8；D-62→§2.13/§2.14；D-63→§2.9；
> D-64→§2.6；D-65→§2.2/§2.7/§2.17；D-66→§2.16（台账见 `specs-v2/deviations/M7.md`）。

## 1. 职责边界

**做**：四类 AI 资产（PROMPT/SKILL/TOOL/AGENT）注册、版本链与内容 hash 引用解析（JSONL journal 持久层）；Release 依赖闭包解析；变更评审流（表驱动 6 态 + M6 结果引用基线比对）；`publish_asset` 唯一发布入口（代码级无旁路）；ReleaseBundle 打包（六要素 + golden_scores 双层签名 + 闭包 + 本体一致性）；发布门禁（行为目录全过 + 红线 100% + 本体 hash + 契约版本）；发布落盘（`releases/<id>/` 只写一次 + manifest sha256 复核）；运行时装配 `resolve_release` 与差分 `diff_release`；AgentContract 资产契约；组装 CLI（rel-0001 基线）。
**不做**：评估执行（M6 evaluator 跑分——M7 只消费 `runs/eval/` 归档并校验其签名，自己不跑分）；本体内容管理（M4；本体版本 hash 进 Release 要素）；冻结契约定义（`src/contracts/`——ReleaseBundle/SkillDescriptor 是冻结结构的**消费者**，改动走 01 v2 §7 契约变更流程）。

## 2. 内部组件（实际目录树）

```text
m7_registry/
├── assets.py           # 四类资产 CRUD+版本链（JSONL journal 追加写+重放重建；SPEC-M7-01/02/03）
├── dependencies.py     # Release 依赖闭包解析（缺失/floating/循环 → 打包失败；SPEC-M7-04）
├── agent_contract.py   # AgentContract 资产契约（六能力域+约束清单+行为目录；SPEC-M7-14）
├── review.py           # 变更评审流（表驱动 6 态+基线比对+publish_asset；SPEC-M7-05/06/07）
├── release.py          # ReleaseBundle 组装+golden_scores 签名+发布门禁（SPEC-M7-08/09/10/11）
├── publish.py          # 发布落盘（只写一次）+Release 状态机+resolve/diff（SPEC-M7-12/13/15）
├── assemble.py         # 组装 CLI（注册→M6 实测→签名→评审→打包→门禁→发布/只读复核；SPEC-M7-16）
├── eval_plugin.py      # tests/test_m7.yaml 数据驱动用例执行器（9 执行器，沙箱 runtime/m7_eval/<case>）
└── RELEASE-FORMAT.md   # releases/<id>/ 发布物目录与字段口径的权威说明（M7 §5 DoD）
```

> [v2Δ D-65] v1 组件表所注 `assets.py（SQLite）` 与 oracle 不符：持久层实为 **JSONL journal**
> （`runtime/m7_registry/assets.jsonl` 追加写+重放重建，M3 幂等 journal 同款）；
> 横切口径=「M2=SQLite、M3/M7=JSONL journal」（01 v2 §8）。台账文件属 runtime/（gitignore），
> 非提交交付物。

## 3. 行为规格（SPEC 条款）

> 每条给出行为陈述 + oracle 证据（文件:行）+ 与 v1 的差异标记。条款编号为 v2 重排
> （映射见文件头）；除标注外，"拒绝"一律以模块异常实现（`AssetError`/`ReviewError`/
> `DependencyError`/`ReleaseBuildError`/`PublishError` 各族），拒绝即 EVAL 负例通过判据。

### SPEC-M7-01 资产四类与子契约校验

资产类型为封闭集 `ASSET_TYPES = (PROMPT, SKILL, TOOL, AGENT)`，类型越界注册被拒
（`src/m7_registry/assets.py:54,220-224`）。四类子契约逐字段校验（`_VALIDATORS` 分派，
`src/m7_registry/assets.py:212-217`）：

- **PROMPT**：必填 `asset_id/version/name/template/variables/compiler`；`template` 非空字符串；
  `variables` 列表；`compiler` 匹配 `^[a-z][a-z0-9_.-]*$`（`src/m7_registry/assets.py:152-163`）。
- **SKILL**：整体须合 01 §2.7 冻结契约（`SkillDescriptor.from_dict` 校验，违规字段报
  `AssetValidationError`）；`dependencies` 为冻结结构之外的注册层外挂键，单剥离出、不污染
  SkillDescriptor（`src/m7_registry/assets.py:166-174`）。
- **TOOL**：必填 `asset_id/version/capability/params_schema/risk/idempotency_policy`；
  `capability` 必须 `<动作ID>@<版本>` 形态；`risk.level` ∈ `contracts.RiskLevel` 枚举；
  `params_schema` 必须是对象；`idempotency_policy` ∈ `{CALLER_PROVIDED, CALLER_PROVIDED_UNIQUE_ARGS}`
  两档（与 M3 幂等键策略同源）（`src/m7_registry/assets.py:177-199`）。
- **AGENT**：整体须合 AgentContract 契约（SPEC-M7-14）（`src/m7_registry/assets.py:202-209`）。
- 任一类型的 `dependencies` 若提供必须是列表，且逐条经 `parse_ref` 校验（floating/缺版本即拒）
  （`src/m7_registry/assets.py:143-149`）。
- 各类型自身标识/版本字段：SKILL=`skill_id`、AGENT=`contract_id`、其余=`asset_id`；缺标识或
  版本注册被拒（`src/m7_registry/assets.py:227-233,356-360`）。

[v2Δ: v1 仅一句"PROMPT（模板+变量+编译器）、SkillAsset（M6 契约）、ToolAsset、AgentAsset"；
v2 按实现把四类子契约逐字段成文——依据 `src/m7_registry/assets.py:135-224`；tests/CHANGELOG.md M7 登记]

### SPEC-M7-02 版本链与不可变

- `register_asset(type, descriptor) -> (asset_id, 1)`：建 chain=1、status=DRAFT 的版本记录；
  同 asset_id 重复注册 → `AssetExistsError`（`src/m7_registry/assets.py:350-369`）。
- `update_asset(asset_id, descriptor)`：任一变更**必然**产生 chain+1 的新版本记录，旧记录
  `superseded_by` 回填新 chain（`src/m7_registry/assets.py:371-398`）；chain 整数=版本链权威，
  描述子自身 `version` 串（semver/v1）是 ref 组成部分（`src/m7_registry/assets.py:236-238,287-289`）。
- **旧版本只读不覆盖**：同 chain 重放/改写 → `AssetImmutableError`（`src/m7_registry/assets.py:328-338`）；
  update 携带显式 `chain` → 拒绝；更新改换 asset_id → 拒绝（`src/m7_registry/assets.py:379-388`）。
- **版本号不空转**：内容 hash 未变化的"更新"→ `AssetUnchangedError`；内容 hash =
  `sha256(canonical_json(descriptor))`（排序键、紧凑分隔符、非 ASCII 原样）
  （`src/m7_registry/assets.py:92-99,389-392`）。
- 版本读取面：`latest` / `get_asset(id, chain=缺省最新)`（旧版本内容只读返回）/
  `list_versions`（按 chain 升序全量）/ `status_of` / `all_assets`
  （`src/m7_registry/assets.py:400-453`）。

[v2Δ D-65: v1 SPEC-M7-01 仅"任一资产变更产生新版本号（旧版本只读不覆盖）"一句；v2 补实现口径——
chain 权威、内容 hash 未变拒绝（不空转）、显式 chain/改 id/重复注册三重拒绝。依据
`src/m7_registry/assets.py:350-398`；tests/CHANGELOG.md M7 登记 8；EVAL-M7-01-P/01-P2]

### SPEC-M7-03 资产引用与版本解析

- 引用形态 `<asset_id>@<version>[#<hash>]`（hash 为内容 sha256 前 6–64 位十六进制；
  正则 `_REF_RE`，`src/m7_registry/assets.py:59`）。
- **floating 版本封闭集拒绝**：version ∈ `FLOATING_TOKENS = (latest, *, head, floating, current)`
  （大小写不敏感）或缺版本 → `AssetValidationError`（SPEC-M7-02 禁 floating latest）
  （`src/m7_registry/assets.py:57,102-124`）。
- `resolve_ref(ref)`：按 id 从最新 chain 向下匹配 version；引用带 hash 时与记录
  `content_hash` 前缀比对，不符 → `AssetNotFoundError`；未注册/版本不存在同样拒绝
  （`src/m7_registry/assets.py:416-427`）。
- `qualify_ref(id, version, hash)` 装配带 12 位内容 hash 的发布级引用（01 §2.12：
  prompts/skills/tools 带 hash）（`src/m7_registry/assets.py:127-129`）。

[v2Δ: v1 把"禁止 floating latest"写在依赖闭包条款内；v2 单列——引用解析是注册表面向
bundle_draft/闭包共用的底层行为。依据 `src/m7_registry/assets.py:102-129,416-427`]

### SPEC-M7-04 Release 依赖闭包

- `resolve_closure(store, skill_refs, tool_refs, prompt_refs)`：对三组种子解析**传递闭包**
  （DFS，环检测 + 去重稳定边序），返回 `ClosureResult{refs（asset_id→带 hash 合格引用）,
  edges, errors}`（`src/m7_registry/dependencies.py:94-142`）。
- **依赖边来源（全部数据驱动，读描述子）**：SKILL=`entry.prompt_ref`（01 §2.7）+ 描述子
  `dependencies[]`；PROMPT/TOOL/AGENT=`dependencies[]`（`src/m7_registry/dependencies.py:49-57`）。
- 三类失败归入 `errors`（打包失败口径）：`FloatingVersionError`（缺版本/floating token）、
  `MissingDependencyError`（**错误消息含缺失资产 ID**）、`CyclicDependencyError`（列出环路）
  （`src/m7_registry/dependencies.py:37-48,77-91,117-121`）。
- **打包级强制**：`build_release` 对闭包 `not ok` → `ReleaseBuildError` 拒绝打包（错误消息
  拼接全部闭包错误）（`src/m7_registry/release.py:328-333`）。

[v2Δ: v1 仅"解析 skill_refs/tool_refs 闭包；缺失或循环→打包失败；禁止 floating latest"；
v2 补 prompt_refs 第三组种子、依赖边数据源、错误分类与打包级断言。依据
`src/m7_registry/dependencies.py` 全文 + `src/m7_registry/release.py:328-333`；EVAL-M7-02-P/-N/-N2/-N3]

### SPEC-M7-05 变更评审流（表驱动状态机）

- 评审流状态机 `REVIEW_TRANSITIONS`（6 态，表驱动；与 `tests/fixtures/m7_state_machines.yaml`
  diff 为空，EVAL-M7-TABLE-P）：

  ```text
  PROPOSED → EVALUATING | REJECTED | WITHDRAWN
  EVALUATING → APPROVED | REJECTED | WITHDRAWN
  APPROVED → PUBLISHED
  PUBLISHED / REJECTED / WITHDRAWN 为终态（REVIEW_TERMINALS）
  ```

  （`src/m7_registry/review.py:54-63`；01 v2 §5.4；非法迁移 → `IllegalReviewTransitionError`，
  `src/m7_registry/review.py:244-253`）
- **提案三要素**：`submit_proposal` 必含动机（motivation）+ 影响面（impact）+ 关联 Badcase
  （badcases；无关联时显式传 `['none']`），缺一 → `ProposalIncompleteError`；proposal_id =
  `rev-<asset_id>-<chain:03d>`，同版本重复提案拒绝（`src/m7_registry/review.py:256-280`）。
- 每次迁移留痕 `history[{from, to, at}]`，决定时间落 `decided_at`
  （`src/m7_registry/review.py:244-253,313,321`）。
- `reject`（PROPOSED/EVALUATING→REJECTED）与 `withdraw`（→WITHDRAWN）分支
  （`src/m7_registry/review.py:327-345`）。
- 评审记录持久化为追加写 journal（`runtime/m7_registry/reviews.jsonl`，重放重建）
  （`src/m7_registry/review.py:186-216`）。
- 每次迁移落审计事件 `release.published {stage: review, from, to, proposal_id, asset, chain,…}`
  （SPEC-M7-17）（`src/m7_registry/review.py:218-242`）。

[v2Δ D-60: v1 M7 §5 DoD 引用的"01§5.4"不存在（v1 01 §5 只有 5.1–5.3）；oracle 为 M7 自建
表驱动，v2 转正为 01 v2 §5.4 冻结状态机。依据 `src/m7_registry/review.py:54-63` +
`tests/fixtures/m7_state_machines.yaml`；tests/CHANGELOG.md M7 登记 1/2]

### SPEC-M7-06 评审基线（M6 结果引用，M7 不自己跑分）

- 评估证据=M6 评估归档（`runs/eval/<stamp>-<release>/report.json`）；`load_m6_report` 形状
  校验：必含 `release_id/mode/golden_set_version/cases/pass_rate/totals`，且 `mode` 必须
  SIMULATION（01 §8 仿真即默认），违规 → `ReviewError`（`src/m7_registry/review.py:101-123`）。
- **跑分口径**：candidate 总分 = `totals.score_100`（百分制），缺则 `pass_rate×100`
  （`src/m7_registry/review.py:126-132`）。
- `start_evaluation(proposal_id, candidate_run_ref, …)`：candidate ≥ baseline（+1e-9 容差）
  → APPROVED；低于 → 迁 REJECTED 并抛 `GoldenRegressionError`（语义先落记录 state 再抛出）
  （`src/m7_registry/review.py:282-325`）。
- **baseline 来源优先级**：显式 `baseline_run_ref`（M6 归档）→ 显式 `baseline_score` →
  现行已发布 release 的 golden_scores（`baseline_reader` 注入读取器）；**无现行 release 时
  基线=0**（首个 release 无可回归基线）（`src/m7_registry/review.py:294-300,365-373`）。
- 比对证据留痕于记录 `golden = {candidate_run_ref, candidate_score, baseline_score,
  golden_set_version, pass_rate}`（`src/m7_registry/review.py:303-309`）。

[v2Δ D-64: v1 仅"评审通过前置=黄金集跑分不低于现行（M6 结果引用）"；v2 补跑分取值口径、
baseline 三来源与无现行 release=0 的机械口径。依据 `src/m7_registry/review.py:126-132,282-325,365-373`；
tests/CHANGELOG.md M7 登记 7；EVAL-M7-03-P2]

### SPEC-M7-07 publish_asset 唯一发布入口（无旁路，代码级断言）

`publish_asset(asset_id, review, *, store, pipeline) -> status` 是资产置 PUBLISHED 的
**唯一入口**，四重门禁全部满足才执行；任一不满足 → `ReviewBypassError` + 审计事件
`release.published {stage: asset-publish, rejected: true, reason}`：

1. review 是评审 journal 中**真实存在**的记录（伪造的 ReviewRecord 数据对象过不了）；
2. 记录 state == APPROVED（跳过评审直接发布被拒）；
3. 记录绑定 asset_id+chain 与资产当前版本一致（旧版本评审不能发布新版本）；
4. 评审通过前置的黄金成绩在记录内留痕（`golden.candidate_score` 存在）。

（`src/m7_registry/review.py:376-443`；审计 `:389-408`）
通过路径：评审流 APPROVED→PUBLISHED 迁移 + `store._set_status(asset_id, "PUBLISHED")`；
`AssetStore._set_status` 为模块私有（单下划线、无公开 setter），`publish_asset` 是其唯一
持久化调用方（`src/m7_registry/assets.py:439-449`；`src/m7_registry/review.py:437-443`）。

[v2Δ D-65: v1 仅"跳过评审直接发布在 publish 入口被拒（代码级断言，无旁路）"；v2 补四重
门禁逐条与"模块私有 setter"的代码级落位。依据 `src/m7_registry/review.py:376-443` +
`src/m7_registry/assets.py:439-449`；tests/CHANGELOG.md M7 登记 8；EVAL-M7-03-N]

### SPEC-M7-08 Release 六要素绑定（含空值口径）

- `SIX_ELEMENTS = (model_ref, prompt_refs, skill_refs, tool_refs, ontology_version,
  golden_scores)`；`build_release` 对六要素逐项检查，**缺失或空值拒绝打包**
  （`ReleaseBuildError`，错误消息列缺失要素名）（`src/m7_registry/release.py:57-59,307-311`）。
- **空值口径**：标量要素（model_ref/ontology_version/golden_scores）取非空；列表要素
  （prompt_refs/skill_refs/tool_refs）须**非空列表**——`None/""/[]/{}` 一律视为"要素缺失"
  （`src/m7_registry/release.py:307-311`；`src/m7_registry/RELEASE-FORMAT.md` §2）。
- **agent_ref 必带**：bundle_draft 必须携带 `agent_ref`（AgentContract 资产绑定；M7 自有
  子契约字段，冻结 ReleaseBundle 无 agent 字段、不可擅改）且须解析为 AGENT 类型资产，
  缺失/类型不符拒绝打包（`src/m7_registry/release.py:312-319`）。
- `contract_version` 必须等于 `contracts.CONTRACT_VERSION`（现行 "1.1"），不符拒绝打包
  （`src/m7_registry/release.py:341-344`；`src/contracts/__init__.py:117`）。
- 装配产物：prompt/skill/tool_refs 经 `resolve_ref` 逐条解析并补齐内容 hash 后**排序**
  写入 bundle；`ontology_version` 以 M4 目录实测 hash 回填；经 `ReleaseBundle.from_dict`
  （01 §2.12 冻结契约逐字段校验）落为 bundle（`src/m7_registry/release.py:346-357`；
  `src/contracts/assets.py:307-343`）。

[v2Δ D-61: v1 仅"缺一拒绝打包"；v2 补空值口径（空列表=缺失）与 agent_ref/contract_version
两道打包前置。依据 `src/m7_registry/release.py:307-344`；tests/CHANGELOG.md M7 登记 3/4；
EVAL-M7-04-N（六要素逐项 drop 实测）]

### SPEC-M7-09 golden_scores 双层签名链（禁手工填报）

- **唯一合法产出口 `import_golden_scores(report, catalog, *, release_id, …)`**：
  归档必须属于本 release（`report.release_id == release_id`，否则 `GoldenSignatureError`）；
  全部数字（pass_rate/类目/目录/红线）从报告**机械推导**，调用方无法注入手工值
  （`src/m7_registry/release.py:157-191`）。
- **by_domain 四块**（目录映射来自 AgentContract 资产 `behavior_catalog`，数据源非代码）：
  `capability`（六能力域 {cases, passed}）/ `category`（四类目）/ `catalog`（12 种子逐条
  {category, domain, anchor, passed, rubric_total}）/ `red_line`（{pass_rate, records:
  case_id→passed|missing}）；归档含目录之外案例 → `GoldenSignatureError`；import 允许子集
  报告（供评审流 A/B），目录完整性由门禁断言（SPEC-M7-10）（`src/m7_registry/release.py:108-154`）。
- **M7 侧签名**：`by_domain.signature = {producer: M6, algorithm: sha256,
  digest: sha256(canonical_json({release_id, golden_set_version, pass_rate, by_domain 去掉
  signature})), release_id, run_ref, attestation, generated_at}`——canonical_json=排序键/
  紧凑分隔符/非 ASCII 原样（`src/m7_registry/release.py:91-105,180-190`）。
- **M6 侧凭证 attestation**：`m6_flywheel.attest.attest_report(report)` 对
  `{kind: M6-GOLDEN-RUN-v1, release_id, model_ref, golden_set_version, golden_dir, mode,
  pass_rate, failures, totals, cases[{case_id, passed}]}` 做
  `sha256("M6-GOLDEN-ATTEST-v1|" + canonical_json(payload))` 签名——**由 M6 模块产出
  （producer=M6），M7 只消费与校验，无法自签**；payload 不含时间戳（同报告同签名可复算）
  （`src/m6_flywheel/attest.py:39-41,57-92`）。
- **校验链 `verify_golden_scores`**（打包/发布/复核共用）：① 结构（signature 存在且
  producer=M6、algorithm=sha256、绑定 release_id 一致）→ ② digest 重算比对（改任何一个
  数字即失配）→ ③ run_ref 归档装载（解析序：绝对路径 → release 目录内相对 → 仓库根相对）
  且归档 release_id 一致 → ④ attestation 重算比对（凭证非本归档实测产物即拒）→ ⑤ **从归档
  重推全部成绩**（capability/category/catalog/red_line/pass_rate/golden_set_version）与声明
  **逐块相等**。手工填报（无签名）、伪造 producer、篡改 digest/数字、跨 release 移植成绩、
  缺 attestation 一律 `GoldenSignatureError`（`src/m7_registry/release.py:194-283`）。
- **发布改写不断链**：digest 输入不含 run_ref，`publish_release` 把签名 run_ref 改写为
  发布目录内相对路径 `evaluation/report.json` 后重走签名校验自证
  （`src/m7_registry/publish.py:222-226,261-263`；`src/m7_registry/release.py:194-204`）。

[v2Δ D-63: v1 仅"golden_scores 必须是本次 release 版本实测（M6 签名），不得手工填报"；
v2 把双层签名链、by_domain 四块、校验链五步与 run_ref 解析序全部成文。依据
`src/m7_registry/release.py:91-283` + `src/m6_flywheel/attest.py`；tests/CHANGELOG.md M7 登记 5/6；
EVAL-M7-04-N2（6 种手工填报变体全拒）]

### SPEC-M7-10 发布门禁（行为目录 + 红线 100% + 一致性复校）

`gate_release(built, *, contract, ontology_dir) -> GateResult` 五项检查（`checks` 逐项
{name, passed, detail}；`missing` 列缺项；`passed = 全 checks 通过且 missing 为空`）——
门禁失败即 GATED 失败，不产出可发布状态（`src/m7_registry/release.py:363-377,380-443`）：

| 检查项 | 口径 | 失败后果 |
| --- | --- | --- |
| `catalog_complete` | 行为目录（AgentContract.behavior_catalog，12 条种子）每条案例都有成绩记录 | GATED 失败，missing 列缺项（含类目/能力域标注） |
| `catalog_passed` | 黄金线：12 条种子全过（逐条 `passed=true`） | GATED 失败，detail 列未过案例 |
| `red_line_100pct` | red_line 类目 `pass_rate ≥ 1.0` **且**逐条通过记录在档（`records[cid]=='passed'`，缺任一 → 失败） | GATED 失败，missing 列缺通过记录案例 |
| `ontology_hash` | `bundle.ontology_version == M4 目录实测 hash`（打包一致性的复校） | GATED 失败 |
| `contract_version` | `bundle.contract_version == contracts.CONTRACT_VERSION` | GATED 失败 |

（`src/m7_registry/release.py:399-443`；红线案例清单来自 `AgentContract.red_line_cases()`
`src/m7_registry/agent_contract.py:141-144`）

[v2Δ: v1 SPEC-M7-06 为"必须包含行为目录 12 条种子用例成绩+红线类目 100% 断言（缺任一红线
通过记录→GATED 失败）"；v2 落位为五项检查表并补 catalog_passed/ontology_hash/contract_version
三项（v1 隐含于打包/DoD 未单列门禁项）。依据 `src/m7_registry/release.py:380-443`；
EVAL-M7-06-P（11 过+case_011 红线缺 → catalog_complete 与 red_line_100pct 失败并列缺项）]

### SPEC-M7-11 本体一致性（防"本体已改、release 未更新"）

- 打包时校验 `draft.ontology_version` 与 M4 `compute_ontology_version(ontology/)` 实测值
  一致；不一致 → `OntologyDriftError`（`src/m7_registry/release.py:289-292,335-340`）。
- M4 目录 hash 机械口径：对目录内全部文件按相对路径排序后拼接（路径 + \0 + 字节 + \0）
  取 sha256——任意文件内容或增删都会改变版本（`src/m4_semantic/loader.py:122-134`）。
- 门禁 `ontology_hash` 项在 GATED 判定时对 bundle 携带值复校（SPEC-M7-10）
  （`src/m7_registry/release.py:433-437`）。

[v2Δ: 与 v1 SPEC-M7-07 语义一致；v2 补 M4 hash 机械口径与门禁复校位。依据
`src/m7_registry/release.py:335-340,433-437`；EVAL-M7-07-P（漂移拒绝+携新 hash 正常通过）]

### SPEC-M7-12 Release 状态机与发布不可变

- Release 状态机 `RELEASE_TRANSITIONS`（4 态，表驱动；与 `tests/fixtures/m7_state_machines.yaml`
  diff 为空，EVAL-M7-TABLE-P）：

  ```text
  DRAFT → GATED → PUBLISHED
  PUBLISHED → SUPERSEDED（仅此一迁）
  SUPERSEDED 为终态（只读）
  ```

  （`src/m7_registry/release.py:61-67`；01 v2 §5.5；非法迁移 → `IllegalReleaseTransitionError`，
  `src/m7_registry/publish.py:128-143`）
- **台账**：`ReleaseStateMachine` 以追加写 journal（`runtime/m7_registry/releases.jsonl`）
  重放重建状态；台账缺失但发布目录存在 → 按 PUBLISHED 事实重建（journal 丢失/外部核验场景）
  （`src/m7_registry/publish.py:83-126`）。
- **发布前置**：`publish_release` 要求 `gate.passed`（未过 → `PublishError`，DRAFT→GATED
  未达成）；DRAFT 先迁 GATED（gate 结论快照入台账 payload）；状态非 DRAFT/GATED 拒绝发布
  （`src/m7_registry/publish.py:190-217`）。
- **只写一次（文件级 immutable）**：`releases/<id>/` 一经发布即冻结——`publish_release`
  二次发布（目录已存在）与 `write_release_file` 向已发布目录补写任何文件 →
  `ImmutableReleaseError`（`src/m7_registry/publish.py:176-187,203-206`）。
- **一次性全量写**：`release.yaml / agent_contract.yaml / evaluation/report.json /
  evaluation/cases.yaml` 逐文件落盘并即时计算 sha256 入 manifest；`manifest.yaml` 自身记
  `"self"`（`src/m7_registry/publish.py:228-259`）。
- **发布后自证**：签名 run_ref 改指发布目录内证据副本后重走 `verify_golden_scores`
  （SPEC-M7-09）（`src/m7_registry/publish.py:222-226,261-263`）。
- **PUBLISHED 后**：`publish_release` 末尾迁 PUBLISHED（expect=GATED）+ 发布记录入台账 +
  发布事件（SPEC-M7-17）；`supersede_release(id, by_release_id=…)` 是唯一合法发布后迁移，
  只动台账、不触发布目录内容（`src/m7_registry/publish.py:264-283`）。
- **resolve_release（运行时装配 + 防篡改）**：装载发布物并按 `manifest.files` 逐文件复算
  sha256，登记文件缺失或 hash 不符 → `ImmutableReleaseError`；返回
  `{release_id, path, bundle, manifest}`（`src/m7_registry/publish.py:289-314`）。

[v2Δ D-60: v1 SPEC-M7-05 的状态机口径与 oracle 一致，v2 补台账重建规则与发布后自证；
状态机来源由 v1"引用 01§5.4"改为 01 v2 §5.5 冻结表。依据 `src/m7_registry/publish.py:83-314`；
tests/CHANGELOG.md M7 登记 1/2；EVAL-M7-05-P / EVAL-M7-TABLE-P / EVAL-M7-REL-P（篡改检测）]

### SPEC-M7-13 发布物形态与 manifest（RELEASE-FORMAT）

- 发布目录标准五件：`release.yaml / agent_contract.yaml / evaluation/report.json /
  evaluation/cases.yaml / manifest.yaml`（`RELEASE_FILES`；`src/m7_registry/publish.py:47-49`）。
- `release.yaml` = ReleaseBundle（01 §2.12 冻结契约逐字段）；`agent_contract.yaml` =
  AGENT 资产描述子全量快照；`evaluation/` = M6 评估证据副本（report.json + cases.yaml，
  后者是发布时所用案例清单的逐字节副本，M6 evaluator 重跑的权威脚本）
  （`src/m7_registry/publish.py:228-236`；`src/m7_registry/RELEASE-FORMAT.md` §1–§2、§8）。
- `manifest.yaml` 字段口径：`release_id / status: PUBLISHED / published_at（UTC ISO-8601）/
  contract_version / agent_contract{ref, asset_id, version, sha256} / gate（gate_release 结论
  快照） / files（sha256 复核基准，manifest.yaml 记 "self"）`
  （`src/m7_registry/publish.py:237-259`；`src/m7_registry/RELEASE-FORMAT.md` §4）。
- **AgentContract 绑定双通道**：冻结 ReleaseBundle 无 agent 字段不可擅改 → 绑定落发布目录
  `agent_contract.yaml` 快照 + `manifest.yaml.agent_contract`（D-62；bundle 侧仅 `agent_ref`
  草稿字段，不进冻结结构）（`src/m7_registry/publish.py:219,242-245`）。
- 目录布局与字段口径权威说明 = `src/m7_registry/RELEASE-FORMAT.md`（v1 DoD 承诺，oracle 已落）。

[v2Δ D-62/D-66: v1 未定义发布物形态（仅"releases/ 下内容只写一次"）；v2 按实现成文。
依据 `src/m7_registry/publish.py:47-49,219-259` + `src/m7_registry/RELEASE-FORMAT.md` 全文 +
`releases/rel-0001/manifest.yaml`；tests/CHANGELOG.md M7 登记 4/10；EVAL-M7-REL-P（五件集比对）]

### SPEC-M7-14 AgentContract 资产契约

AGENT 类型资产的描述子即 AgentContract（`src/m7_registry/agent_contract.py:57-58`），
`from_dict` 逐项校验（违规 → `AgentContractError` → 注册层包装为 `AssetValidationError`）：

- 必填 `contract_id/version`（title 缺省取 contract_id）（`src/m7_registry/agent_contract.py:76-78`）。
- **六能力域封闭集**：`capability_domains` 必须齐备 `_SIX_DOMAINS = (PREDICT, DISPATCH,
  MAINTAIN, PLAN, SELF_HEAL, TRADE)`（01 §2.7 CapabilityDomain），缺域/越界域拒绝；每域
  `description` 必填（`src/m7_registry/agent_contract.py:44,79-91`）。
- **约束清单**：`constraints` 必须非空列表；每条必填 `id`（全清单唯一）/`text`/`assertion`
  （可断言口径）（`src/m7_registry/agent_contract.py:93-106`）。
- **行为目录**：`behavior_catalog` 必须非空列表；每条必填 `case_id`（唯一）/`category`
  （封闭集 `CATEGORIES = (normal, boundary, exception, red_line)`）/`domain`（六域封闭集）/
  `anchor`（规则 ID 或行为目录条目 ID 锚定）（`src/m7_registry/agent_contract.py:39-42,108-128`）。
- 读取面：`red_line_cases()`（红线类目案例清单——SPEC-M7-10 100% 断言对象）、
  `catalog_entries()`、`entry_of(case_id)`、`catalog_index(contract)`（case_id→
  {category, domain, anchor} 索引，门禁/成绩单装配数据源）
  （`src/m7_registry/agent_contract.py:141-173`）。
- 种子实例：`assets/agent_contract_v1.yaml`（`contract_id: agent.park-power-ops@1.0.0`，
  六域 + 12 约束 + 12 条目录条目绑定 12 黄金种子；实测 grep 计数 constraints=12、
  case_id=12）——v1 §6 交付物承诺，oracle 已落。

[v2Δ D-62: v1 §6 仅一句"初始 AgentContract 资产（六能力域+约束清单）"；v2 把结构校验与
读取面成文。依据 `src/m7_registry/agent_contract.py` 全文 + `assets/agent_contract_v1.yaml`；
tests/CHANGELOG.md M7 登记 4；EVAL-M7-01-P2 及全套门禁用例均经本契约装载]

### SPEC-M7-15 diff_release（轨迹漂移对比）

`diff_release(a, b)` 对两个 release（`resolve_release` 结果或 bundle dict）产出结构化差分
（`src/m7_registry/publish.py:317-355`）：

- 标量变化布尔：`model_ref_changed / ontology_changed / contract_version_changed`；
- 引用集差分（prompt_refs/skill_refs/tool_refs/frozen_scenarios 四键）：按 `@` 前资产名
  归并后产出 `added / removed / changed`（同名不同版本/内容即 changed）；
- 成绩差分 `golden_delta`：`pass_rate_a/b`、`golden_set_version_a/b`。

[v2Δ: v1 仅在 01 §3.7 留一行 `diff_release(a, b) -> ReleaseDiff`（轨迹漂移对比用），M7 §3
未展开；v2 按实现成文。依据 `src/m7_registry/publish.py:317-355`]

### SPEC-M7-16 rel-0001 发布基线与 assemble CLI

- **CLI**：`PYTHONPATH=src python -m m7_registry.assemble --release-id rel-0001`
  （`--model-ref` 缺省 `mock-scripted@offline-v1`）；已发布（`releases/<id>/` 存在）时重入
  **只读复核模式**：manifest 完整性 + 签名校验 + M6 黄金重跑，零写入
  （`src/m7_registry/assemble.py:18-24,110-113,210-234,237-255`）。
- **首发流程（全部数据驱动，零 release 特判，`--release-id` 可指向任意同构 release）**
  （`src/m7_registry/assemble.py:90-207`）：
  1. 注册四类资产 **20 项**（PROMPT×2=`prompts/*.yaml`；SKILL×1=`skills/overload-response/
     SKILL.yaml`；TOOL×16=`ontology/actions.yaml` × `tools/<id>.py` 适配器声明**机械装配**
     ——`capability=f"<action_id>@{module.VERSION}"`、`params_schema`/幂等策略/披露面取自
     适配器模块声明（`tools/_base.py:6-17`），`risk{level, reversible, reversible_note,
     default_policy, policy_locked}` 取自 ontology/actions.yaml；AGENT=`assets/
     agent_contract_v1.yaml`）（`src/m7_registry/assemble.py:50-53,61-87,115-126`）；
  2. M6 实测：`GoldenEvaluator.run_golden(release_id)`（SIMULATION 离线，12 条黄金种子；
     发布前经 `tests/fixtures/mock_releases/rel-0001.yaml` 解析）；实测覆盖数 ≠ 行为目录
     条数或存在未过案例 → SystemExit（黄金线未达成不予打包）
     （`src/m7_registry/assemble.py:128-139`）；
  3. `import_golden_scores` 签名导入（SPEC-M7-09 唯一产出口）
     （`src/m7_registry/assemble.py:141-143`）；
  4. 逐资产评审流（proposal→EVALUATING→APPROVED→publish_asset；首个 release 无现行基线=0）
     （`src/m7_registry/assemble.py:145-157`）；
  5. `build_release`（六要素+闭包+本体一致性）→ `gate_release`（12 条目录全过+红线 100%）
     → `publish_release`（只写一次）（`src/m7_registry/assemble.py:159-189`）；
  6. 复核：`resolve_release` manifest 校验 + M6 evaluator 按发布物重跑
     （`src/m7_registry/assemble.py:191-207`）。
- **rel-0001 基线（已发布）**：`releases/rel-0001/manifest.yaml` 登记 status: PUBLISHED、
  published_at 2026-09-28T15:09:45Z、gate 5/5 全过、files 五件 sha256、agent_contract 绑定
  `agent.park-power-ops@1.0.0`（sha256 f0439fd9…）；`release.yaml` 登记六要素：2 prompt +
  1 skill + 16 tool（全部带内容 hash）+ ontology_version `f01ebaf1…` + golden_scores
  （pass_rate 1.0、12/12 目录、红线 2/2、M6 双层签名 digest `4ef8da05…`、score_100 97.67）
  + frozen_scenarios 3 条（`releases/rel-0001/manifest.yaml:1-36`；
  `releases/rel-0001/release.yaml:1-196`）。资产基线逐项登记见 `ASSET-MANIFEST.md`。

[v2Δ D-66: v1 无 assemble CLI 与发布基线条款；v2 按实现成文。依据 `src/m7_registry/assemble.py`
全文 + `releases/rel-0001/`；tests/CHANGELOG.md M7 登记 10；EVAL-M7-REL-P（沙箱同构端到端）]

> **基线现状注记（资产工程阶段实测，2026-09-29）**：CLI 只读复核模式当前对 rel-0001 报
> `ASSEMBLE REFUSED: … evaluation/cases.yaml: sha256 与 manifest 不一致（内容被改动）`——
> 根因与影响面见 `specs-v2/deviations/M7.md` R-1：发布物完整性门禁按设计拒绝（SPEC-M7-12
> resolve_release 行为正确的实证），属发布后证据快照被后续授权提交同步改写造成的基线漂移，
> 非 M7 代码缺陷。

### SPEC-M7-17 审计事件与台账（就近主题 + JSONL journal）

- **审计事件主题=`release.published`**（01 §4/contracts.EventType 28 主题封闭集无
  `review.*`/`asset.*` 主题——沿用 M1/M2/M3/M6"就近落主题 + payload 细分/rejected 标记"
  扩展通道族，01 v2 §4/D-06）：payload.stage ∈ `{review, asset-publish, release}`，
  全部事件经 `contracts.EventRecord.from_dict` 校验后入 sink（合约校验失败抛错）
  （`src/m7_registry/review.py:218-242,389-408`；`src/m7_registry/publish.py:152-170`；
  `src/contracts/enums.py:216`）。
- 事件形态：评审迁移 `{stage: review, from, to, proposal_id, asset, chain[, golden|reason]}`；
  publish 拒绝 `{stage: asset-publish, rejected: true, reason[, state]}`；发布成功
  `{stage: release, gate_checks, golden_pass_rate, agent_contract}`；trace_id 分别为
  `trace-review-<proposal_id>` / `trace-publish-<asset_id>` / `trace-release-<release_id>`，
  producer=M7（`src/m7_registry/review.py:225-241,394-408`；`src/m7_registry/publish.py:157-170,270-274`）。
- **三本 JSONL 台账**（追加写 + 重放重建，M3 幂等 journal 同款；属 runtime/ gitignore 态）：
  `runtime/m7_registry/assets.jsonl`（op: register/supersede/status——资产版本链）、
  `reviews.jsonl`（op: proposal——评审记录）、`releases.jsonl`（op: transition/record——
  Release 状态机+发布记录）（`src/m7_registry/assets.py:292-347`；
  `src/m7_registry/review.py:186-216`；`src/m7_registry/publish.py:83-147`；
  `src/m7_registry/RELEASE-FORMAT.md` §7）。

[v2Δ D-60/D-65: v1 未定义评审/发布审计事件与台账形态；v2 按实现成文（事件主题归属 01 v2 §4
扩展通道族 D-06，台账形态归属 01 v2 §8 持久层横切 D-65）。依据上文所引各处；
tests/CHANGELOG.md M7 登记 2/8；EVAL-M7-03-P（迁移链+事件断言）/ EVAL-M7-03-N（拒绝审计）]

## 4. Eval（`tests/test_m7.yaml`，v2 重生成）

套件头（v2）：`spec_ref` = `specs-v2/M7-registry-release.md`、`specs-v2/00-ontology.md`、
`specs-v2/01-contracts.md` 三文件按序拼接 sha256（`run_evals.py:819-821` 口径；01 v2 §6
协议）。v1→v2 的 `spec_hash → eval_hash` 对登记于 `tests/CHANGELOG.md`（v1 组合为
`specs/` 四文件含 ADDENDUM；`specs-v2/ADDENDUM.md` 未产出⏳暂不入 spec_ref——M7 v2 条款
不依赖 ADDENDUM §A-§F 作行为约束，见 CHANGELOG 同日注）。

执行器两组：`src/m7_registry/eval_plugin.py` 9 个（oracle，本轮零改动）+
`tests/m7_eval_extra.py` 4 个（**v2 重生成新增补充执行器**：SPEC-M7-01 子契约校验拒绝 /
SPEC-M7-05 评审守卫 / SPEC-M7-14 AgentContract 校验 / SPEC-M7-15 diff_release 的执行面；
同款插件契约 EVAL-SCHEMA §4，全部数据驱动零案例特判）。用例沙箱 `runtime/m7_eval/<case>`
先清空独立可复跑；v2 编号重排后用例 id 与 v2 条款号对齐（EVAL-M7-<条款号>-P/N*），
现行用例仍正确描述 oracle 的保留改名（对照见 tests/CHANGELOG.md 同日登记）。

### 4.1 用例清单（case→条款）

| EVAL ID | spec | form | 执行器 | 场景 | 期望 |
| --- | --- | --- | --- | --- | --- |
| EVAL-M7-01-P | SPEC-M7-01 | contract | m7.asset_versions | 四类资产（PROMPT/SKILL/TOOL/AGENT）齐注册+版本链更新 | 类型封闭集齐；各 chain 符合更新次数；旧版本只读（版本串/内容 hash 原样、superseded_by 回填） |
| EVAL-M7-01-N | SPEC-M7-01 | negative_rejection | m7.descriptor_validation | 子契约校验拒绝 8 态（类型越界/缺必填/compiler 非法/TOOL capability 形态/idempotency_policy 越界/risk.level 越界/SKILL 违反 01§2.7/AGENT 缺域） | 全部 AssetValidationError 且消息达口径 |
| EVAL-M7-02-P | SPEC-M7-02 | contract | m7.asset_versions | 注册 Prompt 后改模板 | chain=2；v1 只读（版本串/内容 hash 原样+superseded_by=2） |
| EVAL-M7-02-N | SPEC-M7-02 | negative_rejection | m7.asset_versions | 重复注册/内容未变更新（空转）/显式 chain 改写旧版本 | 三类全拒（AssetExistsError/AssetUnchangedError/AssetImmutableError） |
| EVAL-M7-03-N | SPEC-M7-03 | negative_rejection | m7.closure | skill 引用 floating latest | 闭包+打包双重拒绝，错误含 floating/SPEC-M7-02 |
| EVAL-M7-04-P | SPEC-M7-04 | contract | m7.closure | 显式版本闭包解析+打包 | 闭包成功（节点/边），打包通过 |
| EVAL-M7-04-N | SPEC-M7-04 | negative_rejection | m7.closure | 闭包缺 skill（skill.ghost） | 打包拒绝，错误含缺失 ID |
| EVAL-M7-04-N2 | SPEC-M7-04 | negative_rejection | m7.closure | 循环依赖（prompt A↔B） | 打包失败，错误含"循环依赖" |
| EVAL-M7-05-P | SPEC-M7-05 | event_sequence | m7.review_flow | 正常评审流（真实 M6 实测达标） | PROPOSED→EVALUATING→APPROVED→PUBLISHED 全迁移留痕+审计事件 |
| EVAL-M7-05-N | SPEC-M7-05 | negative_rejection | m7.review_guards | 提案缺动机/影响面/Badcase；REJECTED 终态后再拒绝/再撤回 | ProposalIncompleteError / IllegalReviewTransitionError；终态不被改写 |
| EVAL-M7-06-P | SPEC-M7-06 | contract | m7.review_flow | 显式 baseline（90）下 candidate 达标（92） | EVALUATING→APPROVED→PUBLISHED；golden 比对留痕 |
| EVAL-M7-06-N | SPEC-M7-06 | negative_rejection | m7.review_flow | candidate 85 < baseline 90 | PROPOSED→EVALUATING→REJECTED（GoldenRegressionError 语义） |
| EVAL-M7-07-N | SPEC-M7-07 | negative_rejection | m7.review_flow | 伪造"已批准"评审记录直发 | publish 入口 ReviewBypassError+rejected 审计；资产状态不翻 |
| EVAL-M7-07-N2 | SPEC-M7-07 | negative_rejection | m7.review_flow | 在途未批准提案（PROPOSED）直发 | 同上（state != APPROVED 拒绝） |
| EVAL-M7-07-N3 | SPEC-M7-07 | negative_rejection | m7.review_guards | REJECTED 终态但黄金成绩留痕在档的评审记录直发（隔离四重门禁之第 2 重 state==APPROVED——前两用例分别被第 1/第 4 重拦截，不能唯一归因） | ReviewBypassError 且消息含 REJECTED/APPROVED；资产状态不翻 |
| EVAL-M7-08-P | SPEC-M7-08 | contract | m7.six_elements | 六要素+agent_ref 齐备 | 打包通过；import→verify 合法签名链通过 |
| EVAL-M7-08-N | SPEC-M7-08 | negative_rejection | m7.six_elements | 六要素逐项 drop | 每项缺失均拒绝打包，消息达口径 |
| EVAL-M7-09-N | SPEC-M7-09 | negative_rejection | m7.six_elements | 手工填报 6 变体（无签名/伪造 producer/篡改 digest/篡改 pass_rate/缺 attestation/跨 release） | 全部 GoldenSignatureError 且消息达口径 |
| EVAL-M7-10-P | SPEC-M7-10 | contract | m7.gate | 12 条目录全过+红线 100% | 门禁 5 项全过（GATED 达成） |
| EVAL-M7-10-N | SPEC-M7-10 | contract | m7.gate | 12 条目录 11 过+case_011（red_line）缺 | GATED 失败：catalog_complete+red_line_100pct 失败，missing 列 case_011 |
| EVAL-M7-11-N | SPEC-M7-11 | negative_rejection | m7.ontology_drift | 本体目录改动后携旧 hash 打包 | OntologyDriftError（含"不一致/SPEC-M7-07"）；携新 hash 不被阻断（同案例断言） |
| EVAL-M7-12-P | SPEC-M7-12 | contract | m7.immutable | 发布成功后 resolve 复核+PUBLISHED→SUPERSEDED | manifest.status=PUBLISHED；SUPERSEDED 合法且只动台账（内容零变化） |
| EVAL-M7-12-N | SPEC-M7-12 | negative_rejection | m7.immutable | 二次发布/向已发布目录补写 3 文件/非法迁移（GATED、DRAFT、重复 PUBLISHED） | 全部 ImmutableReleaseError/IllegalReleaseTransitionError；内容零变化 |
| EVAL-M7-14-N | SPEC-M7-14 | negative_rejection | m7.contract_validation | AgentContract 校验拒绝 7 态（缺域/越界域/约束缺 assertion/约束 id 重复/类目越界/domain 越界/case_id 重复） | 全部 AgentContractError 且消息达口径 |
| EVAL-M7-15-P | SPEC-M7-15 | contract | m7.diff | 两 bundle 差分（引用增/删/改+标量变化+成绩差分） | diff 结构逐字段等于期望（added/removed/changed、*_changed、golden_delta） |
| EVAL-M7-TABLE-P | SPEC-M7-05 | state_transition | m7.tables | 评审流（6 态）/Release（4 态）状态机 vs 冻结 fixture | diff 为空；5 项 release 非法迁移行为级拒绝 |
| EVAL-M7-REL-P | SPEC-M7-16 | contract | m7.release_flow | 端到端：真实 M6 实测→签名→20 资产评审发布→六要素打包→门禁 5 项→只写一次发布→manifest/签名/篡改检测/按发布物重跑 | 全链通过；发布物恰为标准五件 |

### 4.2 条款→用例双向索引（clause→cases）

| v2 条款 | 用例 id（P=正例，N=负例） |
| --- | --- |
| SPEC-M7-01 | EVAL-M7-01-P、EVAL-M7-01-N |
| SPEC-M7-02 | EVAL-M7-02-P、EVAL-M7-02-N |
| SPEC-M7-03 | EVAL-M7-03-N（floating 拒绝）、EVAL-M7-04-P（引用解析经闭包/打包装配）、EVAL-M7-REL-P（发布级引用补 hash） |
| SPEC-M7-04 | EVAL-M7-04-P、EVAL-M7-04-N、EVAL-M7-04-N2 |
| SPEC-M7-05 | EVAL-M7-05-P、EVAL-M7-05-N、EVAL-M7-TABLE-P |
| SPEC-M7-06 | EVAL-M7-06-P、EVAL-M7-06-N |
| SPEC-M7-07 | EVAL-M7-06-P（评审后 publish 生效）、EVAL-M7-07-N（第 1 重门禁：journal 存在性）、EVAL-M7-07-N2（命中第 2 重但被第 4 重兜底）、EVAL-M7-07-N3（隔离第 2 重：REJECTED+黄金留痕直发） |
| SPEC-M7-08 | EVAL-M7-08-P、EVAL-M7-08-N、EVAL-M7-REL-P |
| SPEC-M7-09 | EVAL-M7-08-P（合法签名链）、EVAL-M7-09-N、EVAL-M7-REL-P（发布改写 run_ref 后自证） |
| SPEC-M7-10 | EVAL-M7-10-P、EVAL-M7-10-N、EVAL-M7-REL-P（门禁 5 项） |
| SPEC-M7-11 | EVAL-M7-11-N（漂移拒绝+携新 hash 不阻断） |
| SPEC-M7-12 | EVAL-M7-12-P、EVAL-M7-12-N、EVAL-M7-TABLE-P（release 状态机）、EVAL-M7-REL-P（篡改检测） |
| SPEC-M7-13 | EVAL-M7-REL-P（标准五件+manifest 形态）、EVAL-M7-12-P（manifest.status 复核） |
| SPEC-M7-14 | EVAL-M7-10-P、EVAL-M7-REL-P（真实资产契约装载 12 条目录）、EVAL-M7-14-N |
| SPEC-M7-15 | EVAL-M7-15-P |
| SPEC-M7-16 | EVAL-M7-REL-P（沙箱同构端到端；仓库基线 CLI 现状见 deviations/M7.md R-1） |
| SPEC-M7-17 | EVAL-M7-05-P（迁移+事件留痕）、EVAL-M7-07-N（拒绝审计 rejected 标记）、EVAL-M7-07-N3（同）、EVAL-M7-REL-P（三本 journal 落盘+发布事件） |

**复核命令**（仓库根，Python 3.12）：`python run_evals.py --module m7`。v1 套件末次实跑
（2026-09-29，重生成前）：`EVALS mode=m7 … cases=16/16 failed=0 … result=PASS`；v2 套件
（本轮整体替换，27 条：P 11 / N 16，含变异驱动增补 EVAL-M7-07-N3）按约定本轮**未运行** runner，静态自检（YAML/schema/
执行器注册/fixtures 存在/spec_hash 重算）通过——命令与输出见 `tests/CHANGELOG.md` 同日
登记，全绿结论以统一门禁为准。

## 5. DoD

- EVAL 全绿（v2 套件 27 条，待统一门禁运行；v1 套件 16/16 存档含 4 项突变验证：publish
  接受伪造评审记录 / 放行 floating 版本 / 门禁废红线检查 / 只写一次守卫放行，均被对应
  负例捕获——tests/CHANGELOG.md M7 登记）；
- 评审流/Release 状态机与 `tests/fixtures/m7_state_machines.yaml` diff 为空（01 v2 §5.4/§5.5）；
- releases/ 目录结构 + manifest 格式文档内嵌 `src/m7_registry/RELEASE-FORMAT.md`；
- `publish_asset` 无旁路（`AssetStore._set_status` 模块私有，唯一持久化调用方=评审门禁）。

## 6. 交付物

`src/m7_registry/`（8 组件 + RELEASE-FORMAT.md）+ `tests/test_m7.yaml`（27 用例，v2 重生成）+
`src/m7_registry/eval_plugin.py`（9 执行器）+ `tests/m7_eval_extra.py`（4 个 v2 补充执行器）+
`tests/fixtures/m7_state_machines.yaml`
（状态机冻结基准）+ `assets/agent_contract_v1.yaml`（AgentContract 种子：六域+12 约束+
12 目录条目）+ `prompts/daily-inspection.yaml、prompts/overload-response.yaml` +
`skills/overload-response/`（SKILL.yaml+SKILL.md）+ `tests/fixtures/mock_releases/
{rel-0001,mock-rel-0001}.yaml`（发布前 M6 实测/离线重跑清单）+ `releases/rel-0001/`
（首个 Agent Release 发布物，20 项注册资产 PROMPT×2/SKILL×1/TOOL×16/AGENT×1）；
运行时台账 `runtime/m7_registry/{assets,reviews,releases}.jsonl`（gitignore，非提交物）。
