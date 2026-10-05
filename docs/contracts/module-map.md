# 模块图 · 新愿景下的三态判定（阶段 c）

> 任务卡依据：TASK.md §2.3（C-1 模块图 + C-3 评审）。
> 判定准绳：`docs/contracts/agent-purpose-contract.md`（契约 v1.0 草案）。
> 总原则（TASK.md 非目标）：**不推翻既有工程资产**；每件标注「复用 / 改造 / 废弃」；
> 改造件列对 233 用例的影响面（目标：零影响）。
> 新愿景一句话：agent 的外部系统全部模拟化 → ParkDSL 描述园区 → arena 练习场
> （故障注入 + 时间加速 + 人机对比）→ 数万次模拟收敛最佳行为逻辑。

## 1. 判定总表

| # | 既有件 | 判定 | 理由（一句话） |
|---|---|---|---|
| 1 | `src/contracts/` | 复用 | 冻结数据契约（事件/任务/动作 schema），arena 事件流沿用它 |
| 2 | `src/m1_core/loop.py`（五阶段循环+状态机+HITL 等待态） | 复用 | agent 内核即被测对象，行为基准 |
| 3 | `src/m1_core/model_client.py` | **改造** | 三处 LLM 调用点收编入口之一（见 #19） |
| 4 | `src/m2_information/`（state_store SQLite 等） | 复用 | 本地持久化，非外部系统 |
| 5 | `src/m3_action/`（Policy 三值+红线注册表） | 复用 | 行为契约执行载体，红线硬编码在此 |
| 6 | `src/m4_semantic/`（本体/规程） | 复用 | 量测语义与规程条款检索 |
| 7 | `src/m5_simulation/clock.py`（倍速/暂停） | 复用 | **时间权威**——时间快速推移的底座，arena 直接调 |
| 8 | `src/m5_simulation/physics.py` / `price_clock.py` / `recorder.py` / `scenario.py` | 复用 | 遥测物理、峰谷电价、记录、确定性重放 |
| 9 | `src/m5_simulation/injector.py` | **废弃（停演进）** | 与 `fault/` 引擎职责重复；权威注入引擎定为 `fault/`（见 #14）。实体删除待阶段 d 收口且需同步 m5 套件，现在不动（影响面见 §3） |
| 10 | `src/m5_simulation/persona.py` / `alarm_engine.py` | 复用（arena 编排层接入） | 用户模拟器与告警引擎是「正常营业与管理变化」的事件源 |
| 11 | `src/m6_flywheel/`（轨迹/黄金集/判据/Badcase/Skill 化/attest） | 复用 | 收敛判定的方法论与判官设施已在 |
| 12 | `src/m7_registry/`（发布/签名） | 复用 | 资产冻结与发布完整性 |
| 13 | `tools/`（16 适配器）+ `ontology/actions.yaml` | 复用 | agent 动作面；REAL 路由本就是 mock-only，无需拆真实协议 |
| 14 | `fault/`（engine/telemetry/detect/actions/stream） | **改造（升权威）** | 定为**唯一故障注入引擎**；白名单 4 类→论文故障库 ~12 类；注入四步留痕（D-2） |
| 15 | `fault/llm_bridge.py` | **改造** | 收编进 model gateway（#19），保留其零信任校验语义 |
| 16 | `fault/bridge.py` + `fault/web_module.js` | 改造（演进） | python↔node 桥被 `arena serve` 的人类体验 API 取代/包容（阶段 4.7） |
| 17 | `dsl/`（ParkDSL v1） | **改造（v1.x 增量）** | 增 `faults`/`calendar`/`scenario` 三节；保持 233/15/13 门禁绿 |
| 18 | `dsl/prompts/run_gen.py` | **改造** | 收编进 model gateway；配额台账保留 |
| 19 | （新建）`arena/model_gateway.py` | 新建 | 统一 LLM provider 抽象（mock/openai_like/Higress）+ 零信任 + fail-closed + 配额台账 |
| 20 | （新建）`arena/` 引擎族 | 新建 | engine/run_scenario/thresholds/converge/gen_scenario + faults/ + scenarios/ + reports/ |
| 21 | `web/`（数字孪生前端） | **改造（冻结现状）** | owner 裁定「原有前端太丑，完全推翻重做」——人类体验 UI 另起全新工程；`web/` 停止演进、继续服务现有 demo 链路 |
| 22 | （新建）`ui/` | 新建 | 人类体验模式全新前端（原生静态 SPA，无构建链；`arena serve` 供电） |
| 23 | `tests/` + `run_evals.py` + `scripts/ci_isolation.py` + `scripts/mutation_test.py` | 复用+扩展 | 门禁体系；arena/DSL v1.x/故障库新件进 EVAL（233→≥300） |
| 24 | `golden/` | 复用 | dev 黄金集为收敛判定基准（判定集按 D-6 隔离） |
| 25 | `releases/rel-0001` + `deploy/` | 搁置 | 与新愿景无关；不动（R-1 漂移已登记待裁决） |
| 26 | 状态外置四件（TASK.md/ASSET-MANIFEST.md/worklog.md/tests/CHANGELOG.md） | 复用 | 每会话一行的纪律不变 |

## 2. 新模块契约（职责/输入/输出/依赖/禁读）

### 2.1 `arena/engine.py` + `arena/run_scenario.py`（编排层）
- **职责**：把 DSL 场景跑成一次完整模拟——装拓扑（ParkDSL→fault.Topology）、
  起 SimEnv 时钟（speed 倍速）、按注入计划调 fault 引擎、驱动 agent 内核
  （默认 mock LLM）、recorder 全程记录、产出 eval 摘要。
- **输入**：scenario 文件（含 faults 注入计划、calendar 业务日历、clock speed、seed）、
  LLM provider（经 model gateway 注入）。
- **输出**：run 记录（events/states/agent_actions/eval，JSONL+JSON）。
- **依赖**：dsl validator、fault 引擎、m5_simulation clock/physics/price_clock、
  m1_core loop、m3_action 网关、m2 state_store。
- **禁读**：holdout/判定集场景；不接任何真实系统接口。

### 2.2 `arena/converge.py` + `arena/thresholds.yaml`（收敛判定）
- **职责**：批跑统计——红线违规率 3/N 单侧 95% 置信上界、收益指标对比基线、前后窗
  （各 1 万次）行为分布漂移检验；输出 CONVERGED/NOT_CONVERGED + 逐条数字。
- **输入**：scenarios + seed 清单 + 冻结阈值；**判定在与开发隔离的会话执行**（D-5/D-6）。
- **输出**：收敛报告数据 + `arena/reports/convergence-report.md` 素材。
- **依赖**：arena 引擎、m6_flywheel 判据。
- **禁读/禁写**：判定前不得改阈值；不得静默丢弃失败 Run。

### 2.3 `arena/faults/`（论文故障库）
- **职责**：~12 类故障条目（机理/判据阈值带标准出处/演化链/注入参数/可观测信号/
  agent 期望处置锚点）；被 fault 引擎白名单与 DSL `faults` 节引用。
- **依赖**：`docs/theory/equipment.md`（判据底座）、GB/DL 标准。
- **禁读**：无；但对「专家审查」开放全部溯源。

### 2.4 `arena/model_gateway.py`（统一模型出口）
- **职责**：收编 #3/#15/#18 三处 LLM 调用点为单一 provider 抽象
  （mock 确定性 / openai_like / Higress），零信任输出校验，fail-closed，配额台账。
- **禁写**：不落 key；不打印 key。

### 2.5 `ui/`（人类体验模式前端）
- **职责**：故障注入面板、agent 开关、人工操作台、告警时间线、人机对比评分。
- **依赖**：`arena serve`（HTTP+SSE，消费 fault EventBus JSONL）。
- **禁读**：判定集场景不得在前端出现（D-6）。

## 3. 改造件对 233 用例的影响面（目标：零影响）

| 改造件 | 影响面分析 | 结论 |
|---|---|---|
| `dsl/` v1.x 增量 | 新增**可选**节（faults/calendar/scenario）；既有三档样例不含新节时校验行为不变；`dsl/tests/run_tests.py` 15/15 保持，另加负向用例 | 零影响（新增用例另计） |
| `fault/` 白名单扩展 | 现有 4 类故障（SHORT_CIRCUIT/LINE_BREAK/TX_OVERLOAD/PV_TRIP）语义不变，新增类型是**加法**；13 用例不回归 | 零影响 |
| LLM 三处收编 | `model_client` 的 mock provider 为门禁默认路径；收编保持 mock 行为字节级一致（arena 侧以 FakeLLM 脚本化验证） | 零影响（收编后门禁复跑实证） |
| `web/` 冻结 | 不动代码；smoke 测试继续过 | 零影响 |
| `m5_simulation/injector.py` 停演进 | 暂不删除（m5 套件可能引用）；arena 编排只调 fault/；删除动作留待阶段 d 收口并同步 m5 套件时单独提交 | 零影响（停引用≠删代码） |

## 4. 评审要点（提交独立评审）

1. #9 与 #14 的「唯一注入引擎」裁决是否接受（fault/ 权威、m5 injector 停演进）；
2. #21/#22「冻结 web/ + 全新 ui/」是否符合 owner「完全推翻重做」的口径；
3. #19 收编三处 LLM 调用点后，mock 行为字节级一致的验证方案是否充分；
4. 判定集隔离（D-6）在 arena/scenarios ID 前缀 + ci_isolation 扩展上的落地细节。
