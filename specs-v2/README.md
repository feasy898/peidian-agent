# 园区配电运维智能体 · 规格 v2（索引）

> **v2 定位（资产工程阶段）**：七模块已完成开发并通过独立验收（`releases/rel-0001` 已发布）。
> 本目录把**实现反提为规格**：以 oracle（唯一事实源）= 现行实现全体重写 v1 规格——
> oracle = `src/`（m1_core..m7_registry、contracts）、`tools/`、`ontology/`、`regulations/`、
> `golden/dev/`、`scenarios/`、`releases/rel-0001/`、`scripts/`、`run_evals.py`。
> v1→oracle 的全部开发期偏差，权威线索 = `tests/CHANGELOG.md`（deviation 条目）与各模块 commit message；
> 全量盘点见 `specs-v2/DEVIATIONS-draft.md`（D-01..D-71，含 2 项 KNOWN-DEFECT）。
> 阅读顺序：本文件 → 01 冻结契约 → 00 本体 → 各模块 spec v2。

## 0. 交付物清单（specs-v2 文件清单）

| 文件 | 内容 | 性质 | 状态 |
| --- | --- | --- | --- |
| `README.md` | 本文件：v2 交付物索引 + eval 资产索引 + 资产清单占位 | 索引 | ✅ 本阶段产出 |
| `01-contracts.md` | 模块划分+冻结契约 v2.0（12 数据结构+API+28 事件+5 状态机+Eval 协议+契约变更流程），`src/contracts/` 为代码化权威，CONTRACT_VERSION=1.1 | 接口权威源 | ✅ 本阶段产出 |
| `00-ontology.md` | 本体四要素 v2.0（含 actions.yaml policy_locked 列、REG-OP 全部 5 规则 ID、PHYS-TX-TEMP、aliases.yaml 实体解析数据、seed.yaml 实例与加载协议） | 语义权威源 | ✅ 本阶段产出 |
| `ADDENDUM.md` | v1 附录（§A-§F）按 oracle 落地形态复核转正（v2 · 由 oracle 反提，证据锚点到文件:行；D-67..D-71 + §F 侧 D-44 逐节转正；spec_ref 重算再登记为后续动作，见其「登记与后续」节） | 附录 | ✅ 已产出（2026-09-30） |
| `M1-agent-core.md` | 执行内核 spec v2 | 开发规格（反提） | ✅ 已产出（SPEC-M1-01..15；配套 `deviations/M1.md`） |
| `M2-information.md` | 信息层 spec v2 | 开发规格（反提） | ✅ 已产出（SPEC-M2-01..14；配套 `deviations/M2.md`） |
| `M3-action-gateway.md` | 行动层 spec v2 | 开发规格（反提） | ✅ 已产出（SPEC-M3-01..16；配套 `deviations/M3.md`） |
| `M4-semantic-ontology.md` | 语义层 spec v2 | 开发规格（反提） | ✅ 已产出（SPEC-M4-01..09；配套 `deviations/M4.md`） |
| `M5-simulation.md` | 仿真层 spec v2 | 开发规格（反提） | ✅ 已产出（SPEC-M5-01..15；配套 `deviations/M5.md`） |
| `M6-flywheel.md` | 飞轮 spec v2 | 开发规格（反提） | ✅ 已产出（SPEC-M6-01..08；配套 `deviations/M6.md`） |
| `M7-registry-release.md` | 资产层 spec v2（含 §4 条款↔EVAL 双向映射表） | 开发规格（反提） | ✅ 本阶段产出 |
| `DEVIATIONS-draft.md` | v1 规格 ↔ oracle 全量偏差盘点初稿（71 条，按模块拆分到 `deviations/` 的输入） | 偏差台账 | ✅ 已有（初稿） |
| `DEVIATIONS.md` | v1→v2 全量偏差汇总总表（D-01..D-71，含 disposition 与条款号索引） | 偏差台账 | ✅ 冻结收口产出（随 ASSET 34a5e5c 入库） |
| `deviations/<模块>.md` | 各模块偏差处置正式记录（吸收为条款/KNOWN-DEFECT/显式排除） | 偏差台账 | ✅ 已产出（M1..M7 七件齐） |

> [v2Δ D-05] v1 README §0 称"11 数据结构"，实为 **12 个**（01 v2 §2.1–§2.12，含 ReleaseBundle；
> `src/contracts/__init__.py` STRUCTURES 全部代码化）。
> [v2Δ 已替代] v1 交付物清单中的 `HOLDOUT.md` 条目：15 场景独立验收测试仍为**验收专用、不进开发仓库**
> （随验收包交付、由验收人独立保管；`scripts/ci_isolation.py` 断言零命中）——v2 索引不再列其为仓库交付物，
> 存照追溯。v1 原文（`specs/README.md`）原样保留不删。

## 0.1 资产清单（ASSET-MANIFEST.md · 已生成）

| 文件 | 内容 | 状态 |
| --- | --- | --- |
| `ASSET-MANIFEST.md`（仓库根） | 资产工程总台账：specs-v2 规格资产、tests/ eval 资产、`releases/rel-0001` 发布基线（20 项注册资产 PROMPT×2/SKILL×1/TOOL×16/AGENT×1、gate 5/5、黄金 97.67/100）与 `golden/dev/` 12 种子+MANIFEST 的逐项登记 | ✅ **已生成**（仓库根，权威台账：逐件 sha256 + SPEC↔EVAL 映射完整性结论 + 变异杀灭率汇总 + oracle 未改动声明；随 ASSET 34a5e5c 入库；本节为其索引引用） |

## 1. tests/ 新 eval 集（Spec↔Eval 同构资产）

| 文件 | 内容 |
| --- | --- |
| `tests/test_m0.yaml` … `tests/test_m7.yaml` | 8 个模块套件，数据驱动（schema 见 `tests/EVAL-SCHEMA.md`）；用例合计随 v2 重生成逐套件更新（m7 16→27，登记见 `tests/CHANGELOG.md`；含正/负例与表外补强 EVAL） |
| `tests/negative_matrix.yaml` | M3 负向矩阵（只读判据数据：红线动作缺省拒绝矩阵） |
| `tests/EVAL-SCHEMA.md` | EVAL 用例 schema 与执行器契约 |
| `tests/fixtures/` | 判据数据：`frozen_state_machines.yaml`（01 v2 §5.1–§5.3 diff 基准）、`m7_state_machines.yaml`（§5.4/§5.5 diff 基准）、`dev-sim-park.yaml`/`dev-graph.yaml`（EVAL 实例注入，ADDENDUM §D）、`mock_releases/`（M6 离线清单）等 |
| `tests/CHANGELOG.md` | spec_hash→eval_hash 变更台账 + v1→oracle 全部 deviation/revision 登记（偏差权威线索） |

**复核命令**（仓库根，Python 3.12）：

```bash
python run_evals.py --module all
```

v2 基线核验（资产冻结会话实跑，2026-09-29）：
`EVALS mode=all isolation=OK modules=8/8 pending=0 cases=233/233 failed=0 skipped=0 result=PASS`
（套件分布 m0 49 + m1 30 + m2 30 + m3 30 + m4 19 + m5 27 + m6 21 + m7 27；180/180 为 v1 套件期旧数，作废）。

> spec_hash 口径不变（`run_evals.py:819-821`：spec_ref 列表按序拼接文件字节 sha256），
> 但各套件 spec_ref 指向已分层切换：m0/m3 仍指 `specs/` v1 文件（基线口径存照不变）；
> m2/m7 指 specs-v2 三件（模块+00+01）；m1/m4/m5/m6 指 specs-v2 模块文件+00+01，
> ADDENDUM 暂引 `specs/ADDENDUM.md` v1 原文（specs-v2/ADDENDUM.md 未产出，落盘后按
> 01 v2 §6 重算再登记）。specs-v2 反提不改写 v1 原文。现行 spec_hash→eval_hash 对以
> `tests/CHANGELOG.md` 最新登记为准（冻结会话逐位复核 8/8 一致，见 ASSET-MANIFEST.md §2/§3）；
> v1→v2 的条款差异以 `[v2Δ]` 行内标记与 `DEVIATIONS.md` 追溯。

## 2. 系统一页图

（与 v1 一致，oracle 未改变模块拓扑——图见 `specs/README.md` §1。）

## 3. 工程约定速查（按 oracle 修订项加粗）

- 语言栈：Python 3.12（环境实况；v1 写 3.11+ [v2Δ]）；**持久层形态：M2=SQLite（`StateStore(dsn)` 可配）、M3/M7=JSONL journal** [v2Δ D-65]；YAML 数据驱动（tests/ontology/golden/scenarios 全部文件化）。
- LLM 抽象：`m1_core/model_client`（provider 适配，mock 模式可全离线跑 EVAL；**模型端点 SSRF 安全边界 fail-closed** [v2Δ D-15]）。
- 目录树：见 01 v2 §1；契约代码化：`src/contracts/`（标准库 dataclass + 逐字段校验器）。
- 时间纪律：电价判定只允许 M5 BUSINESS 时钟；**真实时钟唯一合法实现位=`m5_simulation/clock.py`，扫描面 [src,tools,scripts]** [v2Δ D-44]。
- 规程引用：一切规程引用=规则 ID（`regulations/*.yaml`，**含 REG-OP**），报告 schema 强制校验规则 ID 存在性 [v2Δ D-68]。
- Eval 重生成：spec 变更→eval 重生成→`tests/CHANGELOG.md` 登记 hash 对；不一致=验收失败（协议见 01 v2 §6）。
- 契约变更：唯一通道=01 v2 §7 评审流程；跳过=CI 拒绝。

## 4. 红线速查（违反任意一条即验收失败；与 v1 一致，oracle 逐条代码级落位）

1. 未注册能力执行（UNREGISTERED 漏网）。
2. 任何角色执行 modify.protection_setting。
3. 无操作票的 execute.remote_control。
4. bypass.approval 生效。
5. 绕过 ActionRequest 通道的任务状态变更（含 TaskState/Artifact/环境）。
6. 用墙钟判定峰谷电价。
7. 模型申请完成而证据不足被放行（NEED_MORE_EVIDENCE 缺失）。
8. holdout 数据进入开发/调优集。
