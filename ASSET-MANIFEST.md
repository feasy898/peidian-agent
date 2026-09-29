# ASSET-MANIFEST · 资产工程冻结总台账（2026-09-29）

> **冻结基线 commit**：`1fd8901`（本冻结任务开工时 HEAD；冻结会话据此核验 oracle 零改动。
> 并行演示工作流在冻结期间于 `demo/`、`docs/` 另有独立提交与在途改动，均不在冻结范围、
> 本台账不登记）。
> **冻结范围**：specs-v2/ 规格资产 + tests/ eval 资产 + 变异证据（.mutations/）+ 发布基线
> （releases/rel-0001）+ 黄金集（golden/dev/）。sha256 均为冻结会话在统一门禁通过后实测
> （`sha256` 对文件字节计算，autocrlf 工作区原样字节）。
> 本文件不自列 hash（自引用无意义）；`specs-v2/README.md` §0.1 的占位由本文件承接。

## 1. 规格资产 · specs-v2/ 全部文件 sha256（20 件）

| 文件 | sha256 |
| --- | --- |
| `specs-v2/README.md` | `371ffbf2cde6483824440c7e3edcb94a4255f102182d7e99d39cd3581c95c4e1` |
| `specs-v2/00-ontology.md` | `4d97a7656530309f689406e3b07c9abcf070c04a240323b8edec31099f98b89f` |
| `specs-v2/01-contracts.md` | `03ea0e12f6950e90ef276782fd8648a6d4c15b37c66f159b0d1f936064cb52e2` |
| `specs-v2/M1-agent-core.md` | `04e561060348b47eeddded5dd7bb1cb5462a6e5acd50a1b4102059f7139513d4` |
| `specs-v2/M2-information.md` | `1cc8dfa82ed164a9f58b7f9a8c53d0470facdfd7f60b38a3c3798f69b485efe7` |
| `specs-v2/M3-action-gateway.md` | `294a1346e9b35499e97024c34d281ee2a5bbd2e8a6ecb60de6eb593d1b790c80` |
| `specs-v2/M4-semantic-ontology.md` | `83e15234d4cfbbc34488b3aafedfd292171e6b9332232456a21e7b83c0127cbb` |
| `specs-v2/M5-simulation.md` | `3e8b63ddb2b5ff5a2b7f7331a1cecf341ce149a2cdeab50eaee5eaddb052dedb` |
| `specs-v2/M6-flywheel.md` | `ca7cd46fad831bd82a7184068457c1221628643f39c150c4aa8d447e9fc72213` |
| `specs-v2/M7-registry-release.md` | `9fe6dce406fc2583ea8cfd86e0b5809398ede1df2b6277d8098fce58eee782a2` |
| `specs-v2/DEVIATIONS-draft.md` | `b3a536b4c5a9949e943d0a9e8cb31d82c4a1dcc5f312a24977c16b296d8a61b1` |
| `specs-v2/DEVIATIONS.md` | `db61a97e774150a5eb28f0ce570c33f6ad2cee31d5d7cacb2a14a10911bc3b1f` |
| `specs-v2/ADDENDUM.md` | `a05bb6b17ea5fc2d2d6eed5ce6d0d06588893b1677d326953b7261aad8e9cb72`（2026-09-30 增补行：v1 §A-§F 按 oracle 转正，D-67..D-71 + §F 侧 D-44；spec_ref 重算再登记为后续动作，见其「登记与后续」节） |
| `specs-v2/deviations/M1.md` | `d3b7e2d1967e63e9aa162db8ffa40a4fdcb53cdc4dd588101dfa7715e846d996` |
| `specs-v2/deviations/M2.md` | `6d772531bbc829e889eb6db6f5dbab5d8731beb4597f5e0a598b965cdc633234` |
| `specs-v2/deviations/M3.md` | `3d1879483700da776ff0fec04ca788ca04cd902ec210000aceaccea3eef84e5e` |
| `specs-v2/deviations/M4.md` | `165b38bf3646f269e94031ae9f03f533a6fbfc34910bc96d06c235cac792822e` |
| `specs-v2/deviations/M5.md` | `4471e979d94164dd83d192f61e856dbfa46617b9a46aa991fb4e8b1eca831443` |
| `specs-v2/deviations/M6.md` | `815083d73af3a645e2beb135a20298e699ca0b1eaf3f5246349364378f00d846` |
| `specs-v2/deviations/M7.md` | `be540247a9f25ad0e1ebde495c72e6bf3fdfd6cc664143ea408708165e09699c` |

> `specs-v2/ADDENDUM.md` 已产出（2026-09-30 增补：D-67..D-71 处置条款仍以 00/01 v2 与
> 模块 spec 为权威正文，本件为 §A-§F 逐节转正 + 证据锚点汇集；`specs-v2/DEVIATIONS.md`
> §KNOWN-DEFECT 与未决项第 4 条前半句自此消解，spec_hash 重算再登记仍待后续）。

## 2. eval 资产 · tests/test_m*.yaml sha256（8 套件，233 用例）

| 套件 | 用例数 | eval_hash（=文件 sha256，与 tests/CHANGELOG.md 最新登记对一致） | 最新登记 spec_hash（runner 重算比对通过） |
| --- | --- | --- | --- |
| `tests/test_m0.yaml` | 49 | `41ebfbf8959bdab0e02df0a4964b3ba4714d3edddc1c1ea4f032d7790a042bf2` | `ddb3b0a38cc193ce3e7a4cfc3d0b4906d6c3e3f87f93331bded3758a05e5be04`（v1 基线对，S0 契约层） |
| `tests/test_m1.yaml` | 30 | `e7ab5eb5bfc565dfd0f2ba576197499f0307a093baef6d5a202ec99b1b2e1eda` | `0b5be472b45c879f3675be791358d04a618d21dbd172c876ef3032dd0123cac0`（复核修复轮重算，前版存照 CHANGELOG） |
| `tests/test_m2.yaml` | 30 | `487d754ce6bf36200e744f5b07a336a6b01cdd652a3bd4834ce59cc5f0cea8cb` | `8804ebce740f13259912dbfd1edbd0f35e657c50a160b0cedcf4a7b5a515feaa`（复核修复轮重算，前版存照 CHANGELOG） |
| `tests/test_m3.yaml` | 30 | `d3c53375dfe964a369f64aad4115de7921e9554e9b42b4bfef3c48cc93e0d8a7` | `91b5cab10ea229719052f1b9498ea75eeb17d539ebf94734f76885c40a4eaa8c`（spec_ref=v1 四文件口径） |
| `tests/test_m4.yaml` | 19 | `ab448986d22cb1a07422e47367c0b1949e02f4856a53130a2eb665a1a3bd12d2` | `299018e7353da3663941e572dd85ced127686ab72b6edc63bbd0fdef27f44884` |
| `tests/test_m5.yaml` | 27 | `ffd71edc0031b09aa5f70773ac0defcf34a228ef60bd70ed87ad01f1aef5766a` | `641cab4d9261324dae2bdd23009f39ff07e7c139d755897d3d3e176bc7de4e5d`（复核修复轮重算，前版存照 CHANGELOG） |
| `tests/test_m6.yaml` | 21 | `f847adec42e3d474894ef0757ce8a1798646eb223bb1777ea25d1ca9824ec72c` | `f90a3d34f23387a115dde173cc4601ff8b965941c7de6280b32773055d39ebce`（复核修复轮重算，前版存照 CHANGELOG） |
| `tests/test_m7.yaml` | 27 | `7b366416f1cce8a29cccc594d252568423b43d7b323fc2c0cb27d786c3c765e5` | `e986db497cbf10d9c2bed9dd0cce7efed107801621d1fdc3f9acb9d418b2fd1c` |
| `tests/test_m9.yaml` | 8 | `ec782db02250a48048ca228b1fa21b8e3d01b5916431fb82df93d39964275b32` | `a0aaf1fb86df73389d95fa6d6d217945ce5a5d32b01afb74fa02c76fa0d1c667`（2026-09-30 汇报前夜新增：应急分级技能雏形套件，spec_ref=skills/emergency-grading/{SKILL.yaml,SKILL.md}；不属冻结 8 套件口径） |

配套判据资产：`tests/EVAL-SCHEMA.md` `bdb3214a9ea6115539b58d422a52a6f5043c90dcfb846370c2351291025cca06`、
`tests/negative_matrix.yaml` `189636ca32e54e8c393ea7311b4c4395074ceeab952a8da38b8910cd32eccffc`、
`tests/CHANGELOG.md`（hash 对台账，含冻结收口与独立复核修复两轮登记，终版 `5b23b9d38ccaefebc29b982e09d535556bcd25a330ac0a1d63d64e1909152ebd`）、
`tests/fixtures/`（frozen/m7 状态机、dev-sim-park/dev-graph 注入实例、mock_releases）与
tests 侧补充执行器插件（`tests/m2_eval_extra.py`、`tests/m4_eval_extra.py`、`tests/m6_eval_extra.py`、
`tests/m7_eval_extra.py`、`tests/fixtures/m3_eval_plugin.py`、`tests/fixtures/m5_eval_plugin.py`——均 tests/ 侧，零 oracle 改动）。

> **m9 增行注记（2026-09-30）**：`tests/test_m9.yaml`（8 例）+ 插件 `tests/m9_eval_extra.py`
> 为汇报前夜新增的应急分级技能雏形套件（skills/emergency-grading/），不属冻结 8 套件
> 口径；`run_evals.py` 的 MODULES 固定 m0..m7（只读未改），m9 经
> `python tests/m9_eval_extra.py` 以同一 runner 路径运行（本轮实跑 8/8 PASS exit 0，
> spec_hash/eval_hash 登记对见 tests/CHANGELOG.md 2026-09-30 节）；统一门禁
> `python run_evals.py --module all` 复跑 233/233 PASS 不受影响，ci_isolation 实扫零命中。

## 3. SPEC↔EVAL 映射完整性结论

**结论：完整（映射成立），含一项已登记的待决后续（specs-v2/ADDENDUM.md 已于 2026-09-30 产出并登记 §1；受影响套件 spec_hash 重算再登记待做）。**

- **逐条款覆盖**（冻结会话脚本复核）：M1 15/15、M2 14/14、M3 16/16、M4 9/9、M6 8/8 条款由套件
  `spec:` 字段直接覆盖；M5 14/15 直指 + SPEC-M5-14 经声明共享映射（EVAL-M5-08-P/09-P 的
  dev-sim-park 注入，`M5-simulation.md:346`）；M7 15/17 直指 + SPEC-M7-13/17 经 §4.2 声明共享映射
  （`M7-registry-release.md:522,526`）。套件对 v2 条款**零未定义引用**。
- **hash 对完整性**（冻结会话实测，复核修复轮后仍成立）：8 个套件文件 sha256 与
  `tests/CHANGELOG.md` 最新登记 eval_hash **逐位一致（8/8）**；`python run_evals.py --module all`
  全绿（复核修复轮记录见 §7/§8，runner 按 `run_evals.py:819-825` 口径重算各套件 spec_hash
  并比对声明值，PASS 即全部一致）。复核修复轮（文档卫生修订）使 m1/m2/m5/m6 四套件
  spec_hash/eval_hash 更新并已按 01 v2 §6 重新登记（前版对存照 CHANGELOG 同日节）；
  用例总数 233 与断言零变化。
  v1 基线对均已存照（m0/v1 四文件口径各见 CHANGELOG 对应条目）。
- **实现者口径补全（复核发现⑤）**：SPEC-M6-02⑦ `golden_set_version` 已按
  `golden_set.py:248-255` 钉死精确定义（排序单元=`"<文件名>:<文件字节 sha256>"`、`"|"`
  拼接、sha256 前 16 位、前缀目录名；对 `golden/dev` 重算=`dev-f7e4e295e43be004`，
  与 rel-0001 登记值及 oracle 函数三方一致）。另一实现面注记：`scenarios/dev-*.yaml`、
  EVAL 执行器插件与 runner 属资产给定量（tests 侧可按 `tests/EVAL-SCHEMA.md` §4 契约与
  用例 params/expect 重建等效件，非逐字节复刻）。
- **待决后续**（2026-09-30 行级回写）：`specs-v2/ADDENDUM.md` 已产出（§1 已登记 sha256）；
  受影响套件（m1/m4/m5/m6）spec_ref 仍引
  `specs/ADDENDUM.md` v1 原文（m3 整体保持 v1 四文件口径、m0 为 v1 基线对——均登记在案且
  runner 校验一致），按 01 v2 §6 重算 spec_hash 并再登记为后续动作（该轮落盘时零 tests/
  套件改动，门禁按现行登记对全绿）。

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
| `python run_evals.py --module all` | `EVALS mode=all isolation=OK modules=8/8 pending=0 cases=233/233 failed=0 skipped=0 result=PASS`（exit 0；冻结收口轮与 §8 复核修复轮各实跑一次，后者为最终登记值） |
| `python scripts/mutation_test.py --module m5 --plan .mutations/plan-m5.json --baseline` | 基线 27/27 PASS exit 0；`planned=7 valid=7 killed=7 survivors=0 redline_all_killed=true`（stdout 末行 JSON 与 `.mutations/results-m5.json` 一致）；轮后 oracle 干净 |
| `git status --porcelain -- src/ tools/ ontology/ regulations/ golden/ scenarios/ releases/ scripts/ run_evals.py` | 空（oracle 干净） |
| `git diff 1fd8901 --stat -- <同上 oracle 路径>` | 空（相对冻结基线零差异） |

## 8. 独立复核修复登记（冻结后第一轮，2026-09-29）

独立复核指出 5 项，全部处置完毕（零 oracle 改动；登记对重算见 §2/§3 与
tests/CHANGELOG.md「独立复核修复」节）：

| # | 发现 | 处置 |
| --- | --- | --- |
| 1（medium） | specs-v2/README.md 索引与冻结实况不一致：M1..M6 与 deviations 七件状态 ⏳（实际已产出）、ASSET-MANIFEST 标「占位」、m7 记 16→26（实际 27）、门禁记 180/180（v1 期旧数）、spec_ref 口径写「各套件仍指 v1」 | **已修**：README §0 交付物表六行改 ✅（ADDENDUM.md 行保持 ⏳——仍未产出）、§0.1 改「已生成」、m7→27、基线→233/233（并标注 180 为作废旧数）、§1 注记改分层口径（m0/m3 仍 v1；m2/m7 specs-v2 三件；m1/m4/m5/m6 specs-v2+00/01，ADDENDUM 暂引 v1 原文） |
| 2（low） | M5（26→27）、M3（29/25→30）、M2（27→30）、M1（交付物 20→30）规格内用例计数未随末轮变异补缺回写；tests/test_m5.yaml 头注 26 | **已修**：四处规格计数与 test_m5.yaml 头注回写实况（套件用例数与断言零变化，总数仍 233） |
| 3（low） | M5 SPEC-M5-13 证据指针「tests/CHANGELOG.md ADDENDUM §C」悬空（该文件无 §C 节；代码事实为真） | **已修**：指针改为代码锚点（`src/contracts/enums.py:224-225`、`price_clock.py:75-97,143-161`）+ 处置登记位（deviations/M5.md D-69 行、DEVIATIONS.md ADDENDUM 节） |
| 4（low） | 隔离字面口径：specs-v2 树命中 7 行（00-ontology.md:318-319,322、deviations/M5.md:19、DEVIATIONS-draft.md:224、M5-simulation.md:128），全部为隔离条款自述或与 v1 同源的 holdout 设计描述（PARK-002/TARIFF-2026B 拓扑参数逐字继承 v1 specs/00-ontology.md:230，v1 验收已放行）；golden/ scenarios/ src/ tests/ 四树零命中；scripts/ci_isolation.py 扫描面本就排除 specs/ | **照实登记（真隔离面完好，非泄漏）**：`ci_isolation` 门禁不受影响（扫描面 [src,tools,scripts]）。是否显式裁剪 00 v2 §5 的 holdout 参数描述、或在复核口径中将 specs-v2 声明为豁免树——**待 owner 裁决**，本轮不擅改 |
| 5（low） | SPEC-M6-02⑦ golden_set_version 公式未指明排序单元与分隔符（跨实现不可复算）；场景文件/执行器插件为给定量非逐字节规格面 | **已修⑤(1)**：公式按 `golden_set.py:248-255` 钉死进 M6-flywheel.md §3（排序单元/`"|"` 分隔/前 16 位/目录名前缀；重算 `dev-f7e4e295e43be004` 与 rel-0001 登记、oracle 函数三方一致）。⑤(2) 作为实现面注记登记于 §3 |

- 本轮 spec 内容修订（README/M1/M2/M3/M5/M6 六文件）使 m1/m2/m5/m6 套件 spec_hash 重算、
  eval_hash 随文件字节更新，均按 01 v2 §6 重新登记（前版对存照 CHANGELOG）；m0/m3/m4/m7
  套件 hash 对不变。修复后统一门禁复跑 `python run_evals.py --module all` →
  `EVALS mode=all isolation=OK modules=8/8 pending=0 cases=233/233 failed=0 skipped=0
  result=PASS`（exit 0，本轮实跑）。
