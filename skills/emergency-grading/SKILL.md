# skills/emergency-grading/SKILL.md · level2 全文（渐进披露第三级；加载才计费）

## 应急预警分级分类（skill.emergency-grading@0.1.0）

适用：观众/值班人员问「什么情况启动哪个级别的应急、哪个级别对应哪些岗位哪些操作」
时，用当前告警/事件集直接给出确定性答案——级别、时限、四岗位操作清单、升级/解除
条件、逐条触发依据（告警 ID × 映射条款）。不进演示主线，作为汇报 Q&A 弹药。

## 用法（确定性脚本通道，不走 LLM 判级）

```bash
# 仓库根（任意 cwd 均可，路径自适应）
python skills/emergency-grading/grade.py skills/emergency-grading/examples/demo-input.yaml
python skills/emergency-grading/grade.py my-alarms.yaml --json
# 换用园区备案预案（保留字段形状的替换表）——零代码改动
python skills/emergency-grading/grade.py my-alarms.yaml --mapping park-plan/SKILL.yaml
```

输入 YAML：`alarms: [{id, type, device?, detail?}, ...]`（也接受裸列表）。
输出：`decision / suggested_level / level_name / p_priority / time_limit_minutes /
contributing_levels / basis / posts / escalate_when / release_when / manual_review /
mapping_id`。

## 分级骨架（示范规则，数据在 SKILL.yaml，可整表替换）

- 四级：Ⅰ 特别重大（5min）/ Ⅱ 重大（15min）/ Ⅲ 较大（30min）/ Ⅳ 一般·预警（120min）。
- 系统对齐：P0→[Ⅰ,Ⅱ]、P1→[Ⅱ,Ⅲ]、P2→[Ⅲ,Ⅳ]、P3→[Ⅳ]——P0-P3 响应语义取自
  `src/contracts/enums.py:50-55`（AlarmLevel：P0=紧急 5min / P1=重要 30min /
  P2=一般 4h / P3=提示 24h）。逐事件在区间内定档（如重过载属 P0 但可转供未失电 → Ⅱ）。
- 覆盖 10 类：重瓦斯跳闸 / 差动跳闸 / 母线失压 / 火灾 / 变压器重过载 /
  通信全中断 / 直流接地 / 电缆沟水浸 / 台风暴雨预警 / 轻瓦斯告警。
- 岗位四席：值班员 / 调度员 / 签发人 / 审批人（posts_order 固定输出顺序）。

## 行为规格条款（tests/test_m9.yaml 逐条对应）

- **EG-SPEC-01 数据驱动**：grade.py 分级逻辑零硬编码，唯一数据源 =
  `skills/emergency-grading/SKILL.yaml` 的 `emergency_grading` 节；表变则行为变。
- **EG-SPEC-02 分级正确性**：单事件按映射表定级；`basis` 逐条引用
  告警 ID + `rule_id` + 级别 + P 级 + 时限（证据可回溯）。
- **EG-SPEC-03 多告警取最高级**：severity rank 最小者胜出；同级并列按输入顺序
  稳定输出；时限取最高级条目中最紧值；岗位操作合并自全部命中规则（去重保序）。
- **EG-SPEC-04 时限与岗位输出**：输出含 `time_limit_minutes` 与 posts_order 全序
  岗位清单；每规则自带 `escalate_when`（升级条件）与 `release_when`（解除条件）。
- **EG-SPEC-05 未知事件不猜级**：`type` 未登记 → 进 `manual_review`
  （action=上报人工判定），不给任何级别/时限猜测；全部未知时
  `decision=MANUAL_REQUIRED`、`suggested_level=null`，posts 仅保留兜底上报动作。
- **EG-SPEC-06 确定性**：同输入 + 同映射 → 输出逐字节一致（无时钟/随机/字典序抖动）。
- **EG-SPEC-07 数据驱动性（可替换性）**：对映射表副本修改任一条目（级别/时限/P 级），
  同输入的判定随之变化（沙箱副本验证，不动线上表）。
- **EG-SPEC-08 输入校验**：缺非空 `id` / 空白 `type` / 重复 `id` → `GradeInputError`
  拒绝（CLI 退出码 2）。

## 证据要求（evidence_policy）

- 每次输出必须携带 `basis`（告警 ID × rule_id）与 `mapping_id`（映射表版本）；
- 未知事件只能出现在 `manual_review`，输出文本必须含「上报人工判定」口径；
- 映射表替换（园区备案预案）时，只需更换 `--mapping` 指向的 YAML，字段形状见
  SKILL.yaml `emergency_grading` 节（levels / priority_map / posts_order /
  manual_fallback / rules）。

## EVAL 套件与运行

- 套件：`tests/test_m9.yaml`（8 例：01-P 分级正确性 / 02-P 多告警取最高级 /
  03-P 时限与岗位 / 04-N 未知兜底不猜级 / 05-P 确定性 / 06-P 数据驱动性 /
  07-N 非法输入拒绝 / 08-P 升级解除与混合未知）。
- 插件执行器：`tests/m9_eval_extra.py`（EXECUTORS 4 个 + 套件运行入口）。
- 运行：`python tests/m9_eval_extra.py`（以 run_evals 同一 runner 路径执行
  test_m9.yaml；run_evals.py 的 MODULES 门禁固定 m0..m7 只读，m9 经插件入口运行，
  不影响 `python run_evals.py --module all` 门禁）。
