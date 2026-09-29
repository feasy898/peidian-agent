# ASSET-MANIFEST · 资产工程冻结总台账（2026-09-29）

> **冻结基线 commit**：`1fd8901`（本冻结任务开工时 HEAD；冻结会话据此核验 oracle 零改动。
> 并行演示工作流在冻结期间于 `demo/`、`docs/` 另有独立提交与在途改动，均不在冻结范围、
> 本台账不登记）。
> **冻结范围**：specs-v2/ 规格资产 + tests/ eval 资产 + 变异证据（.mutations/）+ 发布基线
> （releases/rel-0001）+ 黄金集（golden/dev/）。sha256 均为冻结会话在统一门禁通过后实测
> （`sha256` 对文件字节计算，autocrlf 工作区原样字节）。
> 本文件不自列 hash（自引用无意义）；`specs-v2/README.md` §0.1 的占位由本文件承接。

## 1. 规格资产 · specs-v2/ 全部文件 sha256（19 件）

| 文件 | sha256 |
| --- | --- |
| `specs-v2/README.md` | `c30d4c37f3156b360e493c7182aefdcaa094cb6c8d0ca5a9d7a52d4f75aad25d` |
| `specs-v2/00-ontology.md` | `4d97a7656530309f689406e3b07c9abcf070c04a240323b8edec31099f98b89f` |
| `specs-v2/01-contracts.md` | `03ea0e12f6950e90ef276782fd8648a6d4c15b37c66f159b0d1f936064cb52e2` |
| `specs-v2/M1-agent-core.md` | `150566ac149f484bb58219368156267b23f7b70192e76fb319ad4df2ac632d2e` |
| `specs-v2/M2-information.md` | `899a42cdc173859c463c35b1cbe7b32a3b7200f04fdfdb08c8ac756199fdaa45` |
| `specs-v2/M3-action-gateway.md` | `d5653e40a57ff7c562bdcaeaeb6e8678b4d80624e5a5030cb09a4362874cb516` |
| `specs-v2/M4-semantic-ontology.md` | `83e15234d4cfbbc34488b3aafedfd292171e6b9332232456a21e7b83c0127cbb` |
| `specs-v2/M5-simulation.md` | `b0be2a03fb1b866d834ff85be259e6be0395913b1f2ef4c01dbe6c8a07c0a216` |
| `specs-v2/M6-flywheel.md` | `f0dde751f270c8a581ca698819ecd2556e4dcdfc6a94b55923d53b55555ae974` |
| `specs-v2/M7-registry-release.md` | `9fe6dce406fc2583ea8cfd86e0b5809398ede1df2b6277d8098fce58eee782a2` |
| `specs-v2/DEVIATIONS-draft.md` | `b3a536b4c5a9949e943d0a9e8cb31d82c4a1dcc5f312a24977c16b296d8a61b1` |
| `specs-v2/DEVIATIONS.md` | `db61a97e774150a5eb28f0ce570c33f6ad2cee31d5d7cacb2a14a10911bc3b1f` |
| `specs-v2/deviations/M1.md` | `d3b7e2d1967e63e9aa162db8ffa40a4fdcb53cdc4dd588101dfa7715e846d996` |
| `specs-v2/deviations/M2.md` | `6d772531bbc829e889eb6db6f5dbab5d8731beb4597f5e0a598b965cdc633234` |
| `specs-v2/deviations/M3.md` | `3d1879483700da776ff0fec04ca788ca04cd902ec210000aceaccea3eef84e5e` |
| `specs-v2/deviations/M4.md` | `165b38bf3646f269e94031ae9f03f533a6fbfc34910bc96d06c235cac792822e` |
| `specs-v2/deviations/M5.md` | `4471e979d94164dd83d192f61e856dbfa46617b9a46aa991fb4e8b1eca831443` |
| `specs-v2/deviations/M6.md` | `815083d73af3a645e2beb135a20298e699ca0b1eaf3f5246349364378f00d846` |
| `specs-v2/deviations/M7.md` | `be540247a9f25ad0e1ebde495c72e6bf3fdfd6cc664143ea408708165e09699c` |

> `specs-v2/ADDENDUM.md` 未产出（D-67..D-71 处置条款已分散落 00/01 v2 与模块 spec；
> 见 `specs-v2/DEVIATIONS.md` §KNOWN-DEFECT 与未决项第 4 条）。

## 2. eval 资产 · tests/test_m*.yaml sha256（8 套件，233 用例）

| 套件 | 用例数 | eval_hash（=文件 sha256，与 tests/CHANGELOG.md 最新登记对一致） | 最新登记 spec_hash（runner 重算比对通过） |
| --- | --- | --- | --- |
| `tests/test_m0.yaml` | 49 | `41ebfbf8959bdab0e02df0a4964b3ba4714d3edddc1c1ea4f032d7790a042bf2` | `ddb3b0a38cc193ce3e7a4cfc3d0b4906d6c3e3f87f93331bded3758a05e5be04`（v1 基线对，S0 契约层） |
| `tests/test_m1.yaml` | 30 | `8a09c9e6a1bfb4dd16a99c35dbe2c833ad5c7a16b6455614090810c23675940d` | `e34bf32589ee73f255084c4995732343a51ab82078cc68105dbf4f4783958434` |
| `tests/test_m2.yaml` | 30 | `9a755cb06b63c2f3c3fab7649d37af4cf64ee4d742e9de6cc129ae04fb239d81` | `7f2096f2a8e3b9c9838d72bbf5a0248a479576efca28d3de803b46ad8160e154` |
| `tests/test_m3.yaml` | 30 | `d3c53375dfe964a369f64aad4115de7921e9554e9b42b4bfef3c48cc93e0d8a7` | `91b5cab10ea229719052f1b9498ea75eeb17d539ebf94734f76885c40a4eaa8c`（spec_ref=v1 四文件口径） |
| `tests/test_m4.yaml` | 19 | `ab448986d22cb1a07422e47367c0b1949e02f4856a53130a2eb665a1a3bd12d2` | `299018e7353da3663941e572dd85ced127686ab72b6edc63bbd0fdef27f44884` |
| `tests/test_m5.yaml` | 27 | `31d55310f34a244b8bbda3f6a0840be2837bfbea260d9dfdafa4906da6e462da` | `46051061b7a9be9153833488015dc5bf0db672d7d413698c062477a9acc64a33` |
| `tests/test_m6.yaml` | 21 | `2ed3637d407562a491c67d780de702de29d834ee1608bd201a7a8b26afaff769` | `4596d50fbf4575cb483b5a6a28933da34e83772d57a66760d2e9863afa360d61` |
| `tests/test_m7.yaml` | 27 | `7b366416f1cce8a29cccc594d252568423b43d7b323fc2c0cb27d786c3c765e5` | `e986db497cbf10d9c2bed9dd0cce7efed107801621d1fdc3f9acb9d418b2fd1c` |

配套判据资产：`tests/EVAL-SCHEMA.md` `bdb3214a9ea6115539b58d422a52a6f5043c90dcfb846370c2351291025cca06`、
`tests/negative_matrix.yaml` `189636ca32e54e8c393ea7311b4c4395074ceeab952a8da38b8910cd32eccffc`、
`tests/CHANGELOG.md`（hash 对台账，含本冻结收口条目，终版 `4b4f022b74130c34de326622ef893e8122a7b8c340627b47fa8826bf94b8399b`）、
`tests/fixtures/`（frozen/m7 状态机、dev-sim-park/dev-graph 注入实例、mock_releases）与
tests 侧补充执行器插件（`tests/m2_eval_extra.py`、`tests/m4_eval_extra.py`、`tests/m6_eval_extra.py`、
`tests/m7_eval_extra.py`、`tests/fixtures/m3_eval_plugin.py`、`tests/fixtures/m5_eval_plugin.py`——均 tests/ 侧，零 oracle 改动）。

## 3. SPEC↔EVAL 映射完整性结论

**结论：完整（映射成立），含一项已登记的待决缺口（specs-v2/ADDENDUM.md 未产出）。**

- **逐条款覆盖**（冻结会话脚本复核）：M1 15/15、M2 14/14、M3 16/16、M4 9/9、M6 8/8 条款由套件
  `spec:` 字段直接覆盖；M5 14/15 直指 + SPEC-M5-14 经声明共享映射（EVAL-M5-08-P/09-P 的
  dev-sim-park 注入，`M5-simulation.md:346`）；M7 15/17 直指 + SPEC-M7-13/17 经 §4.2 声明共享映射
  （`M7-registry-release.md:522,526`）。套件对 v2 条款**零未定义引用**。
- **hash 对完整性**（冻结会话实测）：8 个套件文件 sha256 与 `tests/CHANGELOG.md` 最新登记
  eval_hash **逐位一致（8/8）**；`python run_evals.py --module all` → `EVALS mode=all
  isolation=OK modules=8/8 pending=0 cases=233/233 failed=0 skipped=0 result=PASS`（exit 0），
  runner 按 `run_evals.py:819-825` 口径重算各套件 spec_hash 并比对声明值，PASS 即全部一致。
  v1 基线对均已存照（m0/v1 四文件口径各见 CHANGELOG 对应条目）。
- **待决缺口**：`specs-v2/ADDENDUM.md` 未产出；受影响套件（m1/m4/m5/m6）spec_ref 暂引
  `specs/ADDENDUM.md` v1 原文（m3 整体保持 v1 四文件口径、m0 为 v1 基线对——均登记在案且
  runner 校验一致），其落盘后须按 01 v2 §6 重算 spec_hash 并再登记。

## 4. 变异杀灭率汇总（scripts/mutation_test.py，52 变异 × 7 模块）

各模块编排方首轮上报均为**无效运行**（以父目录 `D:\workspace\xunfei4` 为仓库根调用致
`scripts/mutation_test.py` 未找到，"survivors=结果文件缺失/工具失败"为 harness 伪影、
redline 状态 ✗ 为伴生值）——已在各模块 plan 注记/notes 侧车存照（plan-m1-notes.md、
plan-m2.json invalid_first_run_note、plan-m5-invalidation-note.json、plan-m6-notes.md、
plan-m4.json 勘误节、tests/CHANGELOG.md M3/M4/M7 节、deviations/M7.md §5）。下表为
**仓库根正确路径的权威重跑终局**（killed=变异后模块 EVAL exit≠0；全部 restored=true +
hash_match=true，oracle 零残留）：

| 模块 | 计划 | 有效 | 动态杀灭 | 真实 survivor | 红线变异全杀 | 权威证据 |
| --- | --- | --- | --- | --- | --- | --- |
| M1 | 7 | 7 | 7 | 0 | ✓ true | `.mutations/results-m1.json` |
| M2 | 6 | 6 | 6 | 0 | ✓ true | `.mutations/results-m2.json`（真实 survivor m2-crosswrite-allow 已由 EVAL-M2-09-N2 补杀） |
| M3 | 8 | 8 | 8 | 0 | ✓ true | `.mutations/results-m3.json`（survivor m3-unknown-action-allow 已由 EVAL-M3-04-N 补杀） |
| M4 | 7 | 7 | 6 | 0（1 条判定无效变异） | ✓ true | `.mutations/results-m4.json` + plan-m4.json `disposition:invalid`（m4-ambiguity-margin-shrink 死缺省不可达；另 2 survivor 已由 EVAL-M4-05-N2/01-N3 补杀） |
| M5 | 7 | 7 | 7 | 0 | ✓ true | `.mutations/results-m5.json`（冻结会话全量重跑：planned=7 valid=7 killed=7 survivors=0 redline_all_killed=true；基线 27/27 PASS） |
| M6 | 8 | 8 | 8 | 0 | ✓ true | `.mutations/results-m6.json`（survivor m6-holdout-addcase-allow 由 EVAL-M6-02-N2、m6-attest-signature-off 由 EVAL-M6-08-N2 补杀） |
| M7 | 9 | 9 | 9 | 0 | ✓ true | `.mutations/results-m7-full.json`（5 杀）+ `results-m7-remaining.json`（4 杀）+ `results-m7-single.json`（approved-gate 定向杀，EVAL-M7-07-N3 隔离归因） |
| **合计** | **52** | **52** | **51** | **0** | **✓ 全模块 true** | 1 条无效变异（死缺省，行为不可达）标注存照 |

**汇总结论**：52 条计划变异中 51 条行为变异全部动态杀灭（有效变异杀灭率 51/51=100%），
红线类变异在全部 7 模块 redline_all_killed=true；唯一未杀条目 m4-ambiguity-margin-shrink
经判据核对为**无效变异**（缺省分支不可达，EVAL 全绿是正确结论），已在 plan-m4.json 标注
`disposition:invalid` 存照。变异驱动补齐的 eval 用例（M2-09-N2、M3-04-N、M4-05-N2/01-N3、
M5-02-N2、M6-02-N2/08-N2、M7-07-N3）全部随套件重生成登记 spec_hash→eval_hash 新对。

## 5. oracle 未改动声明

**本资产工程阶段（基线 commit `1fd8901` → 冻结提交）oracle 全体零改动。**

- 声明范围（oracle 口径）：`src/`（m1_core..m7_registry、contracts）、`tools/`、`ontology/`、
  `regulations/`、`golden/`、`scenarios/`、`releases/`、`scripts/`、`run_evals.py`。
- 实测证据（冻结会话实跑）：`git status --porcelain -- <oracle 路径>` = 空（工作树干净）；
  `git diff 1fd8901 --stat -- <oracle 路径>` = 空（相对基线零差异）。
- 本阶段唯一触碰 oracle 的操作 = 受控变异测试（`scripts/mutation_test.py`，M5 全量 7 变异），
  工具序列含强制 `git checkout --` 还原 + 行尾归一化 sha256 双重校验，7/7 restored=true、
  hash_match=true，轮后 oracle 树复核干净（`ORACLE-CLEAN`）。
- 冻结产出仅落：`specs-v2/**`（含本阶段新增 DEVIATIONS.md）、`tests/**`、
  `scripts/mutation_test.py`（未改动）、`.mutations/**`、`ASSET-MANIFEST.md`（本文件）、
  `tests/CHANGELOG.md`、`specs/README.md` 顶部弃用指针一行。

## 6. 发布基线与黄金集登记

- **releases/rel-0001**（status=PUBLISHED，2026-09-28）：`manifest.yaml`
  `b7dbc1bd80d7206c4998498735a11bf914cb46eb9f7afdb249c7b450b830e411`、`release.yaml`
  `02699885f66aa53cdad363c4c89f2c7c10ac391dcd47d720e49b2097312b9599`；注册资产 20 项
  （PROMPT×2 / SKILL×1 / TOOL×16 / AGENT×1，`agent.park-power-ops@1.0.0#f0439fd9`）；
  发布门禁 5/5 全过（行为目录 12 条全有成绩、12 种子全过、红线 100%、ontology_hash
  `f01ebaf1855523f5…`、contract_version=1.1）；黄金实测 97.67/100（pass_rate=1.0，
  by_domain=capability/category/catalog/red_line 四块 + 双层签名）。
- **golden/dev/**：12 条手工种子 + `rubrics.yaml`，`MANIFEST.yaml`
  `b59153113ab55513e223960837bb65be5ca8d2e5df2ef2ee2d4a268b4a7bb7ac`（逐文件 sha256+来源
  标记，CI hash 基准）；holdout 红线：dev 集遇 holdout 标记直接拒绝，holdout/golden 永不
  入调优（EVAL-M6-02 系列 + 变异 m6-holdout-* 三条全杀守护）。
- **已知基线漂移 R-1（照实登记，待 owner 裁决）**：rel-0001 发布物
  `evaluation/cases.yaml` 现内容与 manifest 登记 hash 不符（commit 06ce55a 发布后同步改写
  证据快照所致；其余四件一致）——`resolve_release` 完整性门禁按设计拒绝，assemble CLI
  只读复核当前 ASSEMBLE REFUSED。代码行为正确（write-once 篡改检测实证），处置二选一
  （还原发布时点内容 / re-publish 新 release），完整 git 证据链见
  `specs-v2/deviations/M7.md` §3。**本冻结未触碰 releases/ 任何文件。**

## 7. 冻结会话复核命令与输出（2026-09-29 实跑）

| 命令（仓库根） | 输出 |
| --- | --- |
| `python run_evals.py --module all` | `EVALS mode=all isolation=OK modules=8/8 pending=0 cases=233/233 failed=0 skipped=0 result=PASS`（exit 0） |
| `python scripts/mutation_test.py --module m5 --plan .mutations/plan-m5.json --baseline` | 基线 27/27 PASS exit 0；`planned=7 valid=7 killed=7 survivors=0 redline_all_killed=true`（stdout 末行 JSON 与 `.mutations/results-m5.json` 一致）；轮后 oracle 干净 |
| `git status --porcelain -- src/ tools/ ontology/ regulations/ golden/ scenarios/ releases/ scripts/ run_evals.py` | 空（oracle 干净） |
| `git diff 1fd8901 --stat -- <同上 oracle 路径>` | 空（相对冻结基线零差异） |
