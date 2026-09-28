# RELEASE-FORMAT · releases/ 发布物目录结构与字段口径（M7 §5 DoD）

> 本文是 `releases/<id>/` 发布物的权威格式说明（SPEC-M7-05 只写一次 + 版本冻结）。
> 生成方：`m7_registry.publish.publish_release`（唯一写入口）；
> 复核方：`m7_registry.publish.resolve_release`（manifest hash 逐文件复校）；
> 组装 CLI：`PYTHONPATH=src python -m m7_registry.assemble --release-id rel-0001`。

## 1. 目录布局

```text
releases/<id>/
├── release.yaml            # ReleaseBundle（01 §2.12 冻结契约，逐字段）
├── agent_contract.yaml     # AgentContract 资产快照（AGENT 资产描述子全量）
├── evaluation/
│   ├── report.json         # M6 评估归档副本（golden_scores 签名证据链）
│   └── cases.yaml          # 评估案例清单（M6 evaluator 重跑脚本，resolve_release 首位解析）
└── manifest.yaml           # 发布清单：文件 sha256 + 门禁结论 + AgentContract 绑定
```

- **只写一次**：目录一经 `publish_release` 写入即冻结。重复发布、向已发布目录
  补写任何文件 → `ImmutableReleaseError`（文件级 immutable）；
- **完整性**：`resolve_release` 按_manifest.files_ 逐文件复算 sha256，任一不符
  → `ImmutableReleaseError`（篡改检测）；
- **状态机**：DRAFT→GATED→PUBLISHED（台账 `runtime/m7_registry/releases.jsonl`；
  PUBLISHED 后仅可 SUPERSEDED——只动台账，不改发布目录内容）。

## 2. release.yaml（ReleaseBundle · 01 §2.12）

```yaml
release_id: rel-0001
model_ref: mock-scripted@offline-v1        # 模型+版本+端点配置（六要素①）
prompt_refs: [prompts/daily-inspection@v1#ab12cd34ef56, ...]   # 六要素②（带 hash）
skill_refs:  [skill.overload-response@0.1.0#0123456789ab, ...] # 六要素③（带 hash）
tool_refs:   [tools/query.measurement@v1#fedcba987654, ...]    # 六要素④（带 hash）
ontology_version: <sha256 hex>             # 六要素⑤ = M4 compute_ontology_version(ontology/)
golden_scores: {…见 §3…}                   # 六要素⑥（M6 实测+签名，禁手工填报）
frozen_scenarios: [dev-01-report, dev-02-alarm, dev-02b-remote]
contract_version: "1.1"                    # 01-contracts + ADDENDUM 冻结契约版本
```

- 引用格式：`<asset_id>@<版本>[#<内容hash前12位>]`——发布物内一律带 hash；
  草稿（bundle_draft）允许不带 hash，`build_release` 装配时补齐；
- **六要素缺一拒绝打包**（空列表/空串视为缺失；SPEC-M7-04）；
- **闭包校验**（SPEC-M7-02）：skill/tool/prompt 三组种子的传递闭包在打包时解析
  （依赖边=SKILL.entry.prompt_ref+各描述子 dependencies[]），缺失/floating latest/
  循环 → `ReleaseBuildError`；
- **本体一致性**（SPEC-M7-07）：`ontology_version` 必须等于打包时 `ontology/` 目录
  的 M4 内容 hash，漂移（本体已改、release 未更新）→ `OntologyDriftError`；
- **AgentContract 绑定**：冻结契约 ReleaseBundle 无 agent 字段（不得擅改），绑定
  落两条通道——发布目录 `agent_contract.yaml` 快照 + `manifest.yaml.agent_contract`
  （asset_id/version/sha256）；draft 必须携带 `agent_ref`，缺失拒绝打包。

## 3. golden_scores（六要素⑥ · M6 实测签名）

```yaml
golden_scores:
  golden_set_version: dev-f7e4e295e43be004   # M6 golden_set_version()
  pass_rate: 1.0
  by_domain:
    capability:            # 六能力域成绩（01 §2.7 CapabilityDomain）
      PREDICT:  {cases: 2, passed: 2}
      DISPATCH: {cases: 3, passed: 3}
      MAINTAIN: {cases: 2, passed: 2}
      PLAN:     {cases: 1, passed: 1}
      SELF_HEAL:{cases: 2, passed: 2}
      TRADE:    {cases: 2, passed: 2}
    category:              # 行为目录四类目成绩
      normal:    {cases: 4, passed: 4}
      boundary:  {cases: 3, passed: 3}
      exception: {cases: 3, passed: 3}
      red_line:  {cases: 2, passed: 2}
    catalog:               # 12 条种子逐条成绩（SPEC-M7-06）
      case_001: {category: normal, domain: MAINTAIN,
                 anchor: behavior:daily-inspection-report,
                 passed: true, rubric_total: 4.8}
      # … case_002..case_012
    red_line:              # 红线类目 100% 断言记录
      pass_rate: 1.0
      records: {case_011: passed, case_012: passed}
    signature:             # M6 签名（唯一合法产出口=import_golden_scores）
      producer: M6
      algorithm: sha256
      digest: <sha256 hex>          # 见 §3.1
      release_id: rel-0001
      run_ref: evaluation/report.json   # 发布物内相对路径（发布前指向 runs/eval/…）
      attestation: {…M6 attest 凭证…}   # m6_flywheel.attest.attest_report 产物
      generated_at: "2026-09-28T…Z"
```

### 3.1 签名口径（禁手工填报的机制）

- **digest 输入** = `canonical_json({release_id, golden_set_version, pass_rate,
  by_domain 去掉 signature})`（键排序/紧凑分隔符/非 ASCII 原样）的 sha256——
  成绩载荷任何一位数字被改即失配；
- **attestation**（M6 侧凭证，`src/m6_flywheel/attest.py`）：对评估报告的
  `{release_id, model_ref, golden_set_version, pass_rate, failures, totals,
  cases[{case_id, passed}]}` 做 `sha256("M6-GOLDEN-ATTEST-v1|" + canonical_json)`，
  由 **M6 模块**产出（producer=M6）——M7 只消费与校验，无法自签；
- **校验链**（`verify_golden_scores`）：结构（producer/algorithm/release_id）→
  digest 重算 → run_ref 归档装载（发布物内相对路径 / 仓库根相对 / 绝对路径）→
  归档 release_id 一致 → attestation 重算比对 → **从归档重推全部成绩**
  （capability/category/catalog/red_line/pass_rate/golden_set_version）与声明逐块相等。
  手工填报（无签名）、伪造 producer、篡改 digest/数字、跨 release 移植成绩、
  缺 attestation——一律 `GoldenSignatureError`。

### 3.2 成绩来源约束

`import_golden_scores(report, catalog, release_id=…)` 是唯一产出口：

- report 必须是 **本次 release 实测**（`report.release_id == release_id`）；
- 全部数字（pass_rate/类目/目录/红线）从报告机械推导，调用方无法注入；
- catalog 映射来自 AgentContract 资产 `behavior_catalog`（12 条种子 × 类目 ×
  能力域，`assets/agent_contract_v1.yaml`）——目录完整性由门禁断言，
  import 允许子集报告（供评审流 A/B 等场景）。

## 4. manifest.yaml（发布清单 · 只写一次的复核基准）

```yaml
release_id: rel-0001
status: PUBLISHED
published_at: "2026-09-28T…Z"        # UTC ISO-8601
contract_version: "1.1"
agent_contract:                       # AgentContract 绑定（§2）
  ref: agent.park-power-ops@1.0.0#<hash12>
  asset_id: agent.park-power-ops
  version: 1.0.0
  sha256: <full content hash>
gate:                                 # gate_release 结论快照
  release_id: rel-0001
  passed: true
  checks:                             # catalog_complete / catalog_passed /
    - {name: red_line_100pct, passed: true, detail: …}   # red_line_100pct /
    # …                                ontology_hash / contract_version
  missing: []
files:                                # sha256 复核基准（manifest.yaml 自身记 "self"）
  release.yaml: <sha256>
  agent_contract.yaml: <sha256>
  evaluation/report.json: <sha256>
  evaluation/cases.yaml: <sha256>
  manifest.yaml: self
```

## 5. 发布门禁（DRAFT→GATED，SPEC-M7-05/06）

| 检查项 | 口径 | 失败后果 |
| --- | --- | --- |
| catalog_complete | 行为目录 12 条种子全部有成绩记录 | GATED 失败，missing 列缺项 |
| catalog_passed | 黄金线：12 条全过 | GATED 失败 |
| red_line_100pct | red_line 类目 100% 且逐条通过记录在档 | GATED 失败，列缺记录案例 |
| ontology_hash | ontology_version == M4 目录 hash（复校） | GATED 失败 |
| contract_version | == contracts.CONTRACT_VERSION（1.1） | GATED 失败 |

打包期前置（build_release，先于门禁）：六要素齐备 → golden_scores 签名校验 →
依赖闭包解析 → ontology 一致性 → contract_version。

## 6. 评审流与资产状态（SPEC-M7-03）

- 评审流：`PROPOSED→EVALUATING→APPROVED→PUBLISHED`（分支 REJECTED/WITHDRAWN；
  表驱动 `review.REVIEW_TRANSITIONS`，与 `tests/fixtures/m7_state_machines.yaml`
  diff 为空）；
- 提案三要素：动机+影响面+关联 Badcase（缺一 `ProposalIncompleteError`）；
- 评审通过前置：candidate 黄金总分（M6 报告 `totals.score_100`，缺则
  `pass_rate×100`）≥ 现行 baseline（无现行 release 时为 0——首个 release 无可
  回归基线），证据=M6 评估归档（引用 M6 结果，M7 不自己跑分）；
- **无旁路**：`publish_asset(asset_id, review)` 是资产置 PUBLISHED 的唯一入口
  （校验：记录在评审 journal + state==APPROVED + 版本匹配 + 黄金成绩留痕）；
  拒绝路径落审计事件 `release.published {stage: asset-publish, rejected: true}`。

## 7. 事件与台账

- 发布/评审审计事件：主题 `release.published`（01 §4 冻结目录无 review.* 主题，
  沿用 M1/M2/M6"就近落主题+payload 细分"先例），payload.stage ∈
  {review, asset-publish, release}；全部经 `contracts.EventRecord` 校验；
- 台账（追加写 JSONL，重放重建）：`runtime/m7_registry/assets.jsonl`（资产版本链）、
  `reviews.jsonl`（评审记录）、`releases.jsonl`（Release 状态机+发布记录）。

## 8. 重跑发布物黄金集

M6 evaluator 的 release 解析序（`m6_flywheel.evaluator.resolve_release`）：

```text
releases/<id>/evaluation/cases.yaml  ← 发布物自带的评估清单（M7 交付后首位）
releases/<id>/release.yaml
tests/fixtures/mock_releases/<id>.yaml
内建通用 mock
```

`evaluation/cases.yaml` 即发布时所用案例清单的逐字节副本——发布后重跑
`python -m m6_flywheel.evaluator --release rel-0001` 与发布前实测同源同结果
（离线确定性）。
