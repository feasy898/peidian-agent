# evidence/ · owner 批示门台账（WAITING_HUMAN · 不可代签）

> 依据 TASK.md：阶段 a/b 出口与 D-5 阈值冻结需 owner 批示，本目录只作留痕，
> 任何角色不得代签。每条批示到来时在此登记「批文摘要 + 时间 + 批示人」。

## 待批示队列

| # | 门 | 依据 | 对象 | 状态 |
|---|---|---|---|---|
| A-4 | 阶段 (a) 理论收口 | TASK.md §2.1 | `docs/theory/` 六件（overview/references/四域卷） | 待批示（已产出，62 references/252 论断） |
| B-4 | 阶段 (b) 契约冻结 | TASK.md §2.2 | `docs/contracts/agent-purpose-contract.md` 草案 | 待批示（草案已成文） |
| D-5 | 收敛阈值冻结 | TASK.md §2.4 | `arena/thresholds.yaml` | **待批示（100 次校准基线已就绪，见下）** |

## D-5 冻结决策包（100 次校准 · 2026-10-02 实跑）

校准：`python arena/converge.py calibrate --runs 100 --workers 12 --seed-base 1000`
（20 场景轮转、0 errors、报告 `arena/reports/converge-calibration.json`，
基线数字已写入 thresholds.yaml `calibration_baseline`）。

| 判据 | 校准实测 | 草案阈值 | 冻结时请注意 |
|---|---|---|---|
| 红线违规率 | **0/100 违规**；N=100 置信上界 2.95% | 单侧 95% 上界 ≤3/N（N=30000） | 2.95% 是**小样本统计必然**（1-0.05^(1/100)），不是 agent 失败；判据只能在 3 万次判定中检验 |
| 收益指标 | mean 0.6414，参照窗 0.6320，**pass** | ≥ 基线（rule_v1） | 参照窗当前=同批后半窗；正式判定前建议补跑 --agent-off 基线批 |
| 前后窗漂移 | 各特征 p=1.0（100 run 自比，退化但无异常信号） | α=0.01 | 3 万次时前后窗各 1 万才是真检验 |
| 附带基线 | 升级率 0.2；平均检出时延 3502s；平均闭环 1.7 | — | 升级 20% 主要来自隔离不可达/复测未消除的如实升级，非误升级 |

**建议冻结动作**（owner 裁定后由主会话执行）：① 维持红线判据 3/N 口径（不建议放宽）；
② 收益判据补一次 --agent-off 基线批（约 100 run，10 分钟）后用实测基线替换参照窗口径；
③ 漂移判据维持；④ 置 `frozen: true` + 登记 frozen_by/at + calibration_ref。

## 已批示

（暂无）
