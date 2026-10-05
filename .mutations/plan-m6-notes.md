# plan-m6-notes · 变异测试运行处置说明（M6 工程师登记，2026-09-29）

## 1. 交办单所报 survivors 的定性：两条均为 harness 伪幸存者（invalid，非行为变异）

交办单 survivors=["结果文件缺失","工具失败: …can't open file
'D:\\\\workspace\\\\xunfei4\\\\scripts\\\\mutation_test.py': [Errno 2] No such file or directory"]：

- `scripts/mutation_test.py` 实际位于**仓库根** `peidian-agent/scripts/mutation_test.py`；
  该次调用以父目录 `D:\workspace\xunfei4` 为根解析脚本路径 → python 未找到文件，
  **工具从未启动**（本会话实查：`ls scripts/mutation_test.py` 存在；
  `.mutations/results-m6.json` 当时不存在，与"结果文件缺失"互证）。
- 因此两条 survivor **不指向任何 oracle 行为变异**，无 EVAL 可杀——定性 invalid，
  不是覆盖缺口。正确处置 = 从仓库根重跑受控变异测试（已执行，见下）。
- `plan-m6.json` 本体 8 个变异全部有效（`--check-plan` 实跑：
  `[check-plan] OK module=m6: 8 个变异全部可定位`），逐条无需标 invalid。

## 2. 真实重跑发现 1 个真 survivor（已修复）

第一次正确重跑（仓库根，`--baseline`，2026-09-29）：

- 基线：`cases=19/19 failed=0 result=PASS`（v2 套件绿）。
- killed：m6-holdout-marker-invisible / m6-holdout-load-allow / m6-release-flip-allow。
- **survived：`m6-holdout-addcase-allow`（真缺口）**——`add_golden_case` 开发写入
  通道的 holdout 拒绝（`src/m6_flywheel/golden_set.py:278-281`，v2 条款
  SPEC-M6-02③⑧）失效后 eval 仍全绿：v1/v2 套件均无用例覆盖该冻结 API 写入通道。
- 中断：m6-attest-signature-off 变异已应用后，还原步骤撞上并行进程的
  `.git/index.lock`（另一模块工程师并发变异测试），工具按设计中止；
  **遗留变异已当场核实并 `git checkout` 还原**（`git status -- src/` 干净 +
  `attest.py:115` 复原为 `if signature != recomputed:`）。
  另有 3 个变异（skillize/ab-adopt/trajectory）未及执行。

## 3. 修复（不改 oracle、不弱化断言）

- 新增 `tests/m6_eval_extra.py`（EVAL-SCHEMA §4 插件协议，`tests.m7_eval_extra` /
  `tests/fixtures/m3_eval_plugin.py` 同款 tests 侧先例）：执行器
  `m6.golden_add_case`——对 `add_golden_case` 冻结 API 三面探测（正例落盘+
  manifest 登记 sha256+`golden.case_added` 事件恰 1 条 / holdout 标记条目
  GoldenSetError 且零事件 / 同 id 旧版本重交拒绝），全部数据驱动、对 oracle
  只读调用（写入只落沙箱）。
- `tests/test_m6.yaml` 增用例 **EVAL-M6-02-N2**（spec=SPEC-M6-02，禁止类负例）；
  套件 19→20 条（正例 10 / 负例 10）。
- `specs-v2/M6-flywheel.md` §4 双向映射表同步（02 行 + 用例行 + 执行器说明），
  §5/§6 条数修订；spec_hash 重算 = `9f4e695893a3b762d53cc9e2e6de3d87de2c9a96ee411d8a249a5ce6d827d956`
  （spec_ref：specs-v2/M6-flywheel.md + specs-v2/00-ontology.md +
  specs-v2/01-contracts.md + specs/ADDENDUM.md，run_evals.py:819-825 口径）。
- 登记 tests/CHANGELOG.md（v2-r2 条目，eval_hash 以套件落盘字节为准）。

## 4. 修复验证

- 基线复跑：`cases=20/20 failed=0 result=PASS`（20 条版）。
- 单变异核查（`.mutations/plan-m6-fixcheck.json`，仅含该 survivor）：
  **killed**，`eval_summary="EVALS mode=m6 … cases=19/20 failed=1 result=FAIL"`
  （恰为新用例捕获变异），`restored=true, hash_match=true`。
- 全计划 8 变异完整结果以 `.mutations/results-m6.json` 最新一次
  `valid=8` 的运行为准（并发变异测试使 oracle 路径间歇性 dirty，工具按设计
  `skipped_dirty` 跳过；重试循环直至 valid=8，过程日志 `run-m6-attempt*.log`）。

## 5. 第二轮：redline survivor m6-attest-signature-off（已修复，2026-09-29）

20 条套件下的首次完整 8 变异运行（valid=8）暴露第二个真 survivor（redline）：
`m6-attest-signature-off`——`attest.py:115` 载荷级签名重算比对失效后 eval 仍全绿。
根因：EVAL-M6-08-N 的三个探针均经 M7 消费侧被拒（no_attestation 在
`release.py:255` 结构检查即拒；tampered_pass_rate/wrong_producer 被 M7 digest /
producer 检查拒），**attest 重算比对在既有用例中不可达**（plan 描述已预警
"M7 digest 双保险"）。

修复：`tests/m6_eval_extra.py` 增执行器 `m6.attest_verify`（SPEC-M6-08①② 直接
探测面）+ 用例 **EVAL-M6-08-N2**——同报告两次签名确定性复算、合法凭证 verify
通过（含 expect 绑定）、6 个篡改变体（payload.cases / payload.pass_rate /
signature 伪造 → "签名校验失败"；非 M6 producer → "签名方"；缺 payload 字段 →
"缺字段"；expect 绑定其它 release → 含 release_id 的不符拒绝）全部
AttestationError。套件 20→21 条（正例 10 / 负例 11）；spec_hash 重算 =
`4596d50fbf4575cb483b5a6a28933da34e83772d57a66760d2e9863afa360d61`。

**最终完整运行**（21 条基线 `cases=21/21 failed=0 result=PASS`）：
`planned=8 valid=8 killed=8 survivors=0 redline_all_killed=True`
（`.mutations/results-m6.json`；全部 restored=true、hash_match=true；
oracle 路径 git status 干净复核）。
