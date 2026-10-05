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

## D-5 冻结记录（已生效）

**owner 批示**（2026-10-02 会话）：「全部按照你建议的方式操作。然后继续。你先全部做完再看看」——即：①红线维持 3/N；②补 agent-off 基线批后冻结；③漂移维持。

**冻结内容**（`arena/thresholds.yaml` v1.0，frozen: true，frozen_at 2026-10-02）：
- 红线：单侧 95% 置信上界 ≤3/N（N=30000），Clopper-Pearson 口径，未放宽；
- 收益：baseline_score = **0.6735**（agent-off 实测，seeds 2000-2099，100 run 0 errors），
  comparator ">="、tolerance 0；agent-on 同口径校准 0.9197（seeds 1000-1099）；
- 漂移：前后窗各 1 万次，α=0.01，六特征（数值 z 检验 + action_mix 三分类比例检验）；
- 判定种子段 10000-39999（与校准 1000-1099/基线 2000-2099 不重叠）；
- 分块执行：5×6000、workers=12、run 记录 keep-every=20 抽样（摘要全量入 partial JSON）。

**判定执行**：隔离会话工作流 `dwfrun-61d550b5`（冻结算验→5 分块→merge→D-7 报告→独立复核）。
**纪律说明**：同一批 20 场景既用于校准又用于判定——TASK.md D-5 流程本身即「校准→冻结→数万次批跑」
同一语料；D-6 的「判定集未出现在开发期调参记录」以「阈值先冻结、判定会话零调参」满足
（判定工作流子代理无开发上下文，只读冻结产物）。

## 已批示

（暂无——A-4/B-4 仍待）
