# plan-m1 补充说明 · 首轮变异运行无效（infra-failure survivors 处置记录）

> 日期：2026-09-29。本文件是 `.mutations/plan-m1.json`（工具装载的纯变异对象数组，
> 不可夹带说明条目——`load_plan` 要求每项含全部 REQUIRED_PLAN_FIELDS）的 **invalid
> 标注 sidecar**，对应交办单首轮变异结论 `survivors=["结果文件缺失","工具失败: …
> can't open file 'D:\\workspace\\xunfei4\\scripts\\mutation_test.py': [Errno 2]
> No such file or directory"]`、`kill_rate=无效`、`redline_all_killed=false`。

## 首轮两个 "survivor" 均为无效运行产物（非行为缺口）

| 首轮 survivor 值 | 定性 | 证据 |
| --- | --- | --- |
| `结果文件缺失` | 无效——`.mutations/results-m1.json` 从未生成 | 2026-09-29 17:23 实查：`.mutations/` 仅有 plan-*.json 与 m3/m6 运行产物，无 results-m1.json |
| `工具失败: can't open file 'D:\workspace\xunfei4\scripts\mutation_test.py'` | 无效——调用方以**父目录**为仓库根调用工具 | 工具实位于 `peidian-agent/scripts/mutation_test.py`（本仓库 `scripts/`），`D:\workspace\xunfei4\scripts\` 不存在；工具自身 `ROOT = Path(__file__).resolve().parents[1]` 以文件位置锚定仓库根（scripts/mutation_test.py:46） |

结论：首轮 **不是** "变异存活"，而是 "工具未运行"——kill_rate=无效 与
redline_all_killed=false 均为运行失败的伴生值，不构成任何 oracle 行为的无守护证据。
按交办单 "若 survivor 是无效变异则在 plan 中标注 invalid 说明" 条款，此两条标注为
**invalid（运行无效）**，已通过按正确路径重跑取得真实结果（见下）。

## 重跑记录

1. `python scripts/mutation_test.py --module m1 --plan .mutations/plan-m1.json --check-plan`
   → `[check-plan] OK module=m1: 7 个变异全部可定位`（2026-09-29 实跑）。
2. 首次 `--baseline` 重跑（17:36）：基线 30/30 PASS exit 0；但 7 个变异全部
   `skipped_dirty`——oracle 口径存在 1 行已跟踪改动，实为 **M6 工程师的变异轮正在
   进行中**（进程实拍：`mutation_test.py --module m6 --plan .mutations/plan-m6.json
   --baseline` + 子进程 `run_evals.py --module m6`；`src/m6_flywheel/golden_set.py`
   于 17:37:33 被其合法变异、待其工具自还原）。该次 results-m1.json 全
   skipped_dirty，不作为 kill 依据；按纪律等待并行轮结束后重跑。
3. **最终重跑（2026-09-29 17:53，M6/M3 并行轮结束后的干净窗口内执行）**：
   `python scripts/mutation_test.py --module m1 --plan .mutations/plan-m1.json --baseline --require-clean-scope oracle`
   → 基线 exit 0（`EVALS mode=m1 … cases=30/30 failed=0 result=PASS`，`baseline-m1.json`）；
   变异轮 **planned=7 valid=7 killed=7 survivors=[] redline_all_killed=true**
   （`.mutations/results-m1.json`；每个变异 find_count=1、restored=true、hash_match=true——
   oracle 逐次强制还原且行尾归一化 hash 一致，零残留）。

## 最终逐变异处置（全部 killed，无需补用例、无 invalid 变异）

| 变异 id | redline | 杀手用例（计划声明 ↔ 实测 eval_summary 失败数） | 处置 |
| --- | --- | --- | --- |
| m1-completion-gate-off | 是 | EVAL-M1-06-N（CompletionRequiredError）｜29/30 fail=1 | killed，无需动作 |
| m1-frozen-table-completed-edge | 否 | EVAL-M1-TABLE-P（fixture diff）+ 全矩阵｜28/30 fail=2 | killed，无需动作 |
| m1-forged-ref-verdict-downgrade | 是 | EVAL-M1-07-N（伪造引用 REJECTED）｜29/30 fail=1 | killed，无需动作 |
| m1-act-real-route | 是 | m1 场景全链（SIMULATION 固定路由被 M3 门禁拒）｜18/30 fail=12 | killed，无需动作 |
| m1-artifact-ready-accepted-drop | 否 | 01-P/12-P（产物 READY 完成判定 ACCEPTED）等｜23/30 fail=7 | killed，无需动作 |
| m1-budget-token-exhaustion-late | 否 | EVAL-M1-05-P2（恰等耗尽）+ 05-P｜27/30 fail=3 | killed，无需动作 |
| m1-ssrf-global-only-off | 是 | EVAL-M1-14-N + 14-N2（回环/云元数据 fail-closed）｜28/30 fail=2 | killed，无需动作 |

结论：交办单所述 "eval 覆盖缺口" 不存在——首轮 survivors 系运行无效（工具路径错误），
真实变异轮 7/7 全杀、红线全灭（redline_all_killed=true）。本模块未新增/删改任何
EVAL 断言（无缺口可补，更无削弱断言情形）；oracle 零修改（变异由工具受控应用并
已强制还原，`git status` oracle 口径在本次运行窗口内为空）。
