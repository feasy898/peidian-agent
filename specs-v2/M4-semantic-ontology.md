# M4 · Semantic（本体语义层）Spec + Eval（v2.0）

> 职责一句话：让 agent 用本体理解园区配电世界——本体加载与园区实例解析、实体解析、多跳查询、概念视图注入、规程检索、覆盖率监测。
> 数据源：`ontology/*.yaml`（00 v2 的机器可读版，含 `aliases.yaml`）与 `regulations/*.yaml`。本体运行期只读。
>
> **v2 重生成说明（资产工程阶段）**：本文件由 v1（`specs/M4-semantic-ontology.md`）按 **oracle（唯一事实源）**
> 重生成——oracle = `src/m4_semantic/`（loader/resolver/graph/view/regulation/coverage/eval_plugin/__init__）
> + `ontology/*.yaml` + `tests/test_m4.yaml`（v1 基线 13 用例；v2 重生成版 19 用例，§4）+ `tests/fixtures/dev-graph.yaml`。
> 结构与 v1 保持同节编号（§1–§6）便于 diff；**每处与 v1 的差异加行内标记 `[v2Δ: 偏差依据 evidence]`**，
> 未标记部分与 v1 语义一致。v1→v2 条款重排映射见下方注释块；偏差处置正式记录见 `specs-v2/deviations/M4.md`。

<!--
v1→v2 条款重排映射（v2 重排：加载簇 → 能力簇 → eval 资产簇）：

  v1 SPEC-M4-01 加载校验            → v2 SPEC-M4-01（扩充分项校验清单：枚举与 contracts 同源断言等）
  （v1 无园区实例加载协议条款）      → v2 SPEC-M4-02（新增：ADDENDUM §D 按名加载 + 实例校验；D-70）
  v1 SPEC-M4-07 版本管理            → v2 SPEC-M4-03（补 hash 计算口径与内容敏感性断言）
  v1 SPEC-M4-02 实体解析            → v2 SPEC-M4-04（吸收 D-34：序号双读法打分与消歧机械口径）
  v1 SPEC-M4-03 三跳查询            → v2 SPEC-M4-05（吸收 D-35：跳数计数口径；补 entry 变体/自定义路径）
  v1 SPEC-M4-04 OntologyView        → v2 SPEC-M4-06（吸收 D-36：token 计量口径；补三段装箱/trim 登记）
  v1 SPEC-M4-05 规程引用规范        → v2 SPEC-M4-07（补 criterion 结构/2-gram 检索/scope/rule_id_checker 联动）
  v1 SPEC-M4-06 覆盖率监测          → v2 SPEC-M4-08（吸收 D-37：候选事件机制与职责切分成文）
  （v1 无执行器插件条款）            → v2 SPEC-M4-09（新增：EVAL 执行器契约 + DoD 时延门槛数据驱动；M4 登记 5）

偏差吸收：D-34..D-37（M4 全部 4 条）+ D-70（M4 侧半条，实例加载机制实现位在 m4_semantic/loader.py，
M5 env 同一机制）；无 KNOWN-DEFECT 归属 M4。复核命令（oracle 基线实跑，2026-09-29）：
`python run_evals.py --module m4` → `EVALS mode=m4 isolation=OK modules=1/1 pending=0 cases=13/13 failed=0 skipped=0 result=PASS`。
本规格定稿后已按 01 v2 §6 机械重生成 `tests/test_m4.yaml`（13→19 用例，条款↔用例双向映射见 §4.1），
并经受控变异测试（`scripts/mutation_test.py`，plan-m4 7 变异）反证覆盖：5 个红线变异全部被杀
（redline_all_killed=true），据此补 2 个缺口用例（EVAL-M4-01-N3 词表漂移、EVAL-M4-05-N2 声明跳数闸专项，
2026-09-29 变异覆盖缺口修复轮）；
重生成与修复登记（spec_hash→eval_hash 对）见 `tests/CHANGELOG.md` 2026-09-29 条目，
全量统一门禁（run_evals.py）由资产工程收口轮执行。
-->

---

## 1. 职责边界

**做**（oracle 实现全量，`src/m4_semantic/`）：

- 本体加载与完整性校验：`ontology/` 五必需文件 + `regulations/` 四规程 + `aliases.yaml`（可选），七项分项校验，任一失败拒绝加载（启动失败优于带病运行）（`loader.py`）；
- 园区实例按名加载与实例校验（ADDENDUM §D：默认搜索 `ontology/`，`PARK_INSTANCE_PATH` 追加；对任意同构实例通用、零实例特判）（`loader.py`）；
- 版本管理：本体版本 = `ontology/` 目录内容 hash（sha256），版本不匹配任务拒绝启动（防本体漂移）（`loader.py`）；
- 实体解析（文本→本体实体链接）：别名表 + 属性词典 + 序号双读法，全数据驱动（`ontology/aliases.yaml`），歧义不擅断（`resolver.py`）；
- 图查询：内存图（networkx MultiDiGraph）+ 00 §1.2 三种查询模式 + 三跳上限与分解建议（`graph.py`）；
- OntologyView 概念视图生成（Context 注入用，token 预算裁剪 + 被裁内容登记）（`view.py`）；
- 规程索引与检索：规则 ID→条款+判据结构、关键词检索、对象类型直接约束规则、规则 ID 存在性核对（联动 M2/M6 schema 校验）（`regulation.py`）；
- 覆盖率监测：任务级报告 + 窗口聚合 + `badcase.opened` 候选事件**产出**（`coverage.py`）；
- EVAL 执行器插件：`tests/test_m4.yaml` 数据驱动用例的执行器注册（`eval_plugin.py`）。

**不做**：

- 本体编辑（运行期只读；本体变更走 M7 变更评审）；
- 业务判断（规则判定在 M3 policy 与 M5 仿真判据中；M4 只做本体语义检索与联动）；
- `badcase.opened` 候选事件的**持久化与处置**（事件持久化归 M2/M6 事件流，候选处置归 M6 Badcase 流水线；M4 只产出候选）[v2Δ D-37 职责切分成文]；
- 墙钟业务判定：模块内真实时间只用于记录与性能测量（`coverage.py:34-35` `recorded_at` 用 UTC now、`coverage.py:12-13` 注明仅用于记录、不参与电价判定；`eval_plugin.py:464` 时延 DoD 用 `time.perf_counter`（MONOTONIC 语义）——均不参与电价/业务判定，不在 EVAL-M5-02-N 墙钟电价扫描的违例面（该扫描按 price_markers 圈定检查面，`src/m5_simulation/eval_plugin.py:250-283`））[v2Δ: 补口径成文]。

## 2. 内部组件

```text
m4_semantic/
├── __init__.py      # 01 §3.4 冻结 API 统一导出（load_ontology/resolve_entities/query_graph/
│                    #   concept_view/coverage_report 等 19 个公开名）
├── loader.py        # ontology/ 加载+七项完整性校验；本体版本=目录内容 hash；园区实例按名加载
│                    #   （ADDENDUM §D：resolve_instance_file/load_park_instance/ParkInstance）
├── resolver.py      # 实体解析：别名表+范围别名+属性词典+序号双读法（数据驱动 aliases.yaml，
│                    #   新增设备零代码）；打分/消歧决策/传感器联动
├── graph.py         # 内存图（networkx MultiDiGraph）+三种查询模式模板（含 entry 变体）+三跳上限
├── view.py          # OntologyView：token 预算三段贪心装箱+逐段 trimmed 登记+estimate_tokens
├── regulation.py    # 规程索引（规则 ID→条款+判据 criterion 结构；2-gram 检索；scope；
│                    #   unknown_rule_ids / rule_id_checker 联动钩子）
├── coverage.py      # 覆盖率监测（概念注册表+任务级报告+窗口聚合+badcase.opened 候选事件产出）
└── eval_plugin.py   # tests/test_m4.yaml 执行器插件（EXECUTORS：9 个执行器，EVAL-SCHEMA §4 契约）
```

[v2Δ: v1 §2 树缺 `eval_plugin.py` 与 `__init__.py`（v1 交付物清单亦未列）；oracle 为实有组件，
EVAL 数据驱动套件的执行器注册位（tests/EVAL-SCHEMA.md §4 插件契约）]

依赖约定：`contracts` 包位于 `src/`，需在 sys.path（`run_evals.py` / pytest 配置保证；
M3 registry 亦有同类 sys.path 兜底先例，见 01 v2 §3.3 D-27）。

## 3. 行为规格（SPEC 条款）

### 3.1 加载与版本

- **SPEC-M4-01 本体加载与完整性校验**：冻结 API `load_ontology(version=None, *, repo_root, ontology_dir, registry, instance, instance_data, use_cache=True) -> LoadedOntology`（`loader.py:464-543`）。加载 `ontology/` 五必需文件（objects/relations/actions/rules/enums.yaml，`loader.py:55-57`）+ `regulations/` 四规程（REG-SAFE/REG-COMM/REG-TECH/REG-OP，`loader.py:59`）+ `ontology/aliases.yaml`（可选，缺失时 resolver 仅剩 ID 直配；仓库交付必须包含，`loader.py:729-731`），运行期只读。分项校验（任一失败→`OntologyLoadError` 拒绝加载，错误聚合可追溯）：
  1. **enums**：每组为非空字符串列表；与 `src/contracts` `CONTROLLED_VOCABULARY` **双向同源断言**（yaml 侧缺失/多出/值不同均拒；contracts 未登记的词表拒绝）（`loader.py:559-580`）；
  2. **objects**：`object_groups` 必填，组内 `types` 非空，对象类型 ID 全局唯一（`loader.py:583-611`）；
  3. **relations**：非空、ID 唯一、domain/range 逗号分隔的每个 token 必须是已定义对象类型或组名；`query_patterns` 每项必须有 id 且 hops 为 1..3 整数（`loader.py:614-648`）；
  4. **actions**：非空、ID 唯一、`risk_level`/`default_policy` 枚举封闭（受控词表）、`reversible`/`policy_locked` 必须布尔（`loader.py:651-679`）；
  5. **rules**：非空、ID 唯一、category 必须在 categories 注册（`loader.py:682-700`）；
  6. **regulations**：四文件必须存在、`rules` 非空、条款 ID **跨文件唯一**、每条款 `clauses` 非空（`loader.py:703-726`）；
  7. **aliases**：存在时校验 scores 五分数键为数值、`device_aliases`（target+aliases）、`attribute_dictionary`（canonical+match）、`generic_ordinal`（type_id+可编译 id_pattern）、`scopes`（alias+target）（`loader.py:729-756`）。

  动作清单导出（M3 注册表对齐接口）：`LoadedOntology.action_manifest()` 按 actions.yaml 文件序导出（id/name_cn/risk_level/reversible/default_policy/policy_locked）；`align_registry(registry)` diff 非空（动作表缺失于注册表 / 注册表多出）→ `RegistryAlignmentError` 加载拒绝（`loader.py:411-440`）。本会话实测：`load_ontology(registry=["bogus.action"])` → `RegistryAlignmentError`。
  实例装载：`instance` 缺省 `"seed"`（`DEFAULT_INSTANCE_NAME`，`loader.py:61`），None/空=不加载实例；`instance_data` 内联实例取代实例文件（负向测试件用）；`use_cache=True` 按（目录、版本 hash、instance、registry）键缓存，内联实例不进缓存；`reset_cache()` 供测试清空（`loader.py:456-461,492-495,541-543`）。
  - oracle 证据：`src/m4_semantic/loader.py:55-57,59,61,411-440,456-543,559-580,583-611,614-648,651-679,682-700,703-726,729-756`。
  - [v2Δ: v1 一句"加载时校验——关系引用均存在；动作表与 M3 注册表对齐；枚举值在受控词表内"；oracle 细化为七项分项校验 + 枚举与 contracts **双向**同源断言 + 动作表对齐的具体 diff 语义（缺失/多出双向报出）+ 缓存与内联实例装载形态；tests/CHANGELOG.md S0 登记（受控词表同源）]

- **SPEC-M4-02 园区实例按名加载（ADDENDUM §D）**：`resolve_instance_file(name, *, repo_root, extra_dirs) -> Path` 按名解析实例文件，**去扩展名匹配（.yaml/.yml）**；搜索顺序 = `ontology/` → 环境变量 `PARK_INSTANCE_PATH`（分隔符 ";"，依序追加，调用时读取）→ 调用方显式 `extra_dirs`（末位）；实例名须为不含路径分隔符的标识符（`_ID_SAFE_RE`），未找到 → `InstanceLoadError`（消息列出全部搜索目录）（`loader.py:63-64,66,175-206`）。`load_park_instance(name, ...)` 返回 `ParkInstance`（节点表 + 关系三元组 + `substation_devices` 房-设备索引）（`loader.py:146-172,209-236`）。
  实例校验（任一失败→`InstanceLoadError`，全部问题汇总一次报出）：顶层必须为对象且 `park.id` 必填；实体 ID 全局唯一；设备必须带 id+type 且 type 须为本体对象类型（实体可显式 `otype` 覆盖；未声明时按节名提示 `SECTION_TYPE_HINTS` 兜底）；关系三元组 [src, rel, dst] 的关系 ID 必须已注册、两端实体必须存在；实例数据枚举封闭校验（Alarm.level→alarm_level、OperatingState.state→device_state、WorkOrder.status→work_order_status、SwitchOrder.status→switch_order_status、电价时段 type→price_period_type）（`loader.py:90-95,242-385`）。**通用扩展节**：任意顶层 list[dict 且含 id] 节（告警/工单/检修计划/负荷曲线等）自动入图——对任意同构实例通用，零实例特判（`loader.py:318-331`）。本会话实测：`PARK_INSTANCE_PATH=tests/fixtures` 后 `resolve_instance_file("dev-graph")` → `tests/fixtures/dev-graph.yaml`。
  - oracle 证据：`src/m4_semantic/loader.py:63-64,66,70-95,146-236,242-385`；`tests/fixtures/dev-graph.yaml:1-9`（EVAL 注入实例，与 seed 同构）。
  - [v2Δ D-70: v1 无实例加载协议条款（00 v1 §3 仅给种子实例内容）；oracle 按 ADDENDUM §D 落地为 M4 loader 机制，M5 env 同一机制、同一代码路径服务任意同构实例（EVAL 实例 `dev-graph.yaml`/`dev-sim-park.yaml` 经此注入）；tests/CHANGELOG.md M4 登记 1 + M5 登记 7；00 v2 §3 已转正]

- **SPEC-M4-03 版本管理（防本体漂移）**：本体版本 = `ontology/` 目录内容 hash——目录内全部文件按相对路径排序，拼接（相对路径 + \0 + 字节 + \0）取 sha256；任意文件内容或增删都改变版本（`loader.py:122-140`）。`load_ontology(version=...)` 传入期望版本与实际不一致 → `OntologyVersionMismatchError`（任务拒绝启动）；None = 接受当前内容并返回其 hash（`loader.py:485-489`）。`ReleaseBundle.ontology_version` 必须与本层报告一致（01 v2 §2.12 六要素之一）。EVAL-M4-01-P 断言：同内容重复加载版本稳定 + 内容敏感性（复制目录改动一字节 → hash 必变）（`eval_plugin.py:84-111`）。本会话实测：`load_ontology(version="deadbeef")` → `OntologyVersionMismatchError`。
  - oracle 证据：`src/m4_semantic/loader.py:122-140,485-489`；`src/m4_semantic/eval_plugin.py:84-111`。
  - [v2Δ: 与 v1 SPEC-M4-07 语义一致；v2 补 hash 计算机械口径与内容敏感性断言的 oracle 证据（条款号由 07 重排为 03，加载簇内聚）]

### 3.2 语义能力

- **SPEC-M4-04 实体解析（数据驱动 + 序号双读法 + 消歧机械口径）**：冻结 API `resolve_entities(text, loaded=None) -> list[dict]`（`ResolvedEntity.to_dict` 形态：entity_id/entity_type/attribute/matched/score/reason/ambiguous/scope）（`resolver.py:68-91,403-406`）。
  归一化：全角→半角（数字/字母）+ 去除全部空白（"2 号变压器"≡"2号变压器"；大小写保留，ID 大小写敏感）；中文序号（一/两/…/十、十X/X十）可解析（`resolver.py:36-65`）。
  打分模型（**全数据驱动** `ontology/aliases.yaml` 顶层分数键，loader 逐键数值校验；缺省 explicit 1.0 / room_ordinal 0.8 / parkwide_ordinal 0.6 / same_type_fallback 0.5 / unambiguous_margin 0.3）：
  1. **显式别名**：`device_aliases` 短语命中（1.0）；target 不在当前实例自动忽略——别名表全局共享、实例各自过滤（`resolver.py:118-126`）；
  2. **范围别名**（`scopes`，如 "A 房"→SR-A）：命中后作为房号限定，缩小序号/兜底候选搜索范围；仅当无设备指称时自身作为结果；每目标保留最长命中（`resolver.py:111-115,173-176,206-211,309-319`）；
  3. **序号双读法**（"N 号<类型词>"，`generic_ordinal` 数据声明 type_words + id_pattern 的 num 捕获组锚定 `$`）：**房内序号强读法**（0.8）=某配电房内该类型按 ID 排序的第 N 台（运维口语默认读法；未提房号时对全部房求读法，多房同现即歧义）；**全园区尾号弱读法**（0.6）=设备 ID 数字尾号恰为 N；同设备多读法取最高分。新增同类型设备自动参与排序，无需改代码（`resolver.py:140-148,179-187,261-306,352-361`）；
  4. **同类型兜底**（0.5）：文本出现类型词时，该（范围内）类型全部设备为弱候选（`resolver.py:189-201`）。

  **属性词典**：中文口语词→canonical 属性名（温度→winding_temp、局放→pd），按 `applies_to` 匹配已解析设备的对象类型挂接；单候选且对象类型未知时仍附属性（泛指）（`resolver.py:129-137,213-230`）。
  **消歧决策（D-34 机械口径）**：候选按 (-score, entity_id) 排序；首名与次名分差 ≥ `unambiguous_margin`(0.3) → **唯一消歧**（只返回首名+联动传感器）；否则返回阈值内全部候选（`ambiguous=True`，逐候选 `reason`，不擅自择一）。"唯一消歧"语义 = 结果**无 ambiguous 标记**；结果集可含联动传感器（`resolver.py:232-258`）。
  **传感器联动**：带 `sensor_type` 的属性经绑定关系（缺省 `monitors`）联动出传感器实体（如 "A 房 1 号柜局放"→SG-A01+PD-A01 两条）（`resolver.py:363-392`）。
  本会话实测：`"2 号变压器温度"`→`[TX-02(0.8, ambiguous=False, attribute=winding_temp)]`；`"3 号变压器"`→`[(TX-03,0.6),(TX-01,0.5),(TX-02,0.5)]` 全部 `ambiguous=True`（含理由）；`"A 房 1 号柜局放"`→`[SG-A01(0.8), PD-A01(1.0)]` 均 `ambiguous=False`。
  - oracle 证据：`src/m4_semantic/resolver.py:36-65,68-91,101-105,111-148,153-258,261-306,352-392,403-406`；`ontology/aliases.yaml:24-28`（分数）、`:32-36`（scopes）、`:40-46`（device_aliases）、`:50-61`（attribute_dictionary）、`:66-73`（generic_ordinal）。
  - [v2Δ D-34: v1 写"别名：N 号→ID 映射表 + 属性词典；无歧义阈值内多候选时返回候选列表（不擅自择一）"；oracle 为**序号双读法打分模型**全数据驱动（房内序号/全园区尾号/同类型兜底 + margin 机械口径），"唯一消歧"=无 ambiguous 标记且可含联动传感器；tests/CHANGELOG.md M4 登记 2/3；数据文件全文转正见 00 v2 §6]

- **SPEC-M4-05 图查询（三种查询模式 + 三跳上限 + 跳数计数口径）**：冻结 API `query_graph(pattern, loaded=None) -> list`（`graph.py:244-257`；实例未加载→拒绝）。`OntologyGraph` = networkx MultiDiGraph（节点=实例实体带 type/attributes，边=实例关系三元组，方向=声明序 src→dst）（`graph.py:67-84`）。
  **三种查询模式**（00 §1.2，模式 ID 与 `ontology/relations.yaml` query_patterns 同 ID，模式声明 hops=3）：`alarm_impact`（告警→设备→母线→同母线设备）/ `overload_analysis`（负荷→回路→变压器→容量约束）/ `defect_closure`（工单→告警→设备→检修计划→下次检修）；每模式带 **entry_type 变体**——起点已定位到中间环节时（如只知告警源设备）按起点对象类型选择变体，None=通用变体（按声明序取首个匹配）（`graph.py:31-60,223-238`）。
  **自定义路径**：`steps=[[relation, direction] | ["attribute", 属性名]...]`，direction∈out/in/any；关系步的关系 ID 必须已在本体注册（`graph.py:93-108,206-221`）。
  **三跳上限（两道闸）**：`pattern.hops` 声明 >3，或展开后关系步数 >3 → `GraphQueryError`"超过上限 3：建议分解为多次三跳内查询"（`graph.py:26-27,140-148,159-164`）；两道闸相互独立，各有专项负例（EVAL-M4-05-N1 四跳关系步路径、EVAL-M4-05-N2 声明 hops=4 但路径仅 1 跳关系——后者由变异测试 m4-hop-declared-gate-off 反证补齐，2026-09-29）。本会话实测：4 跳查询拒绝且消息含"分解"。
  **跳数计数口径（D-35）**：**属性拾取步（"attribute"）不计关系跳数**——仅从路径末端节点读取约束属性（capacity_kva/next_due 等），计入 `terminal_attributes` 而非 `hops`；结果路径 `hops`=关系边数（`graph.py:159-175,193-203`）。实测：`overload_analysis` 自 LC-A0901（dev-graph 实例）→ 节点链 [LC-A0901, F-A1, TX-01]、hops=2（模式声明 hops=3）、terminal `capacity_kva`=1600；`alarm_impact` 自 AL-0201 → 终端 {TX-02, TX-03}、hops=3。
  **其余约束**：未知模式 / 本体未声明该模式（query_patterns 校验）/ 起点不存在 → 拒绝；环路防护（路径内重复节点跳过）；结果形态 `[{mode, start, nodes, edges, hops, terminal_attributes}]`（`graph.py:134-138,181-183,224-229,193-203`）。视图支撑：`neighborhood(node_id, hops)` 无向 BFS 距离图（远端路径判定用）（`graph.py:110-124`）。
  - oracle 证据：`src/m4_semantic/graph.py:26-27,31-60,67-124,127-238,244-257`；`ontology/relations.yaml:77-89`（三模式声明 hops=3）。
  - [v2Δ D-35: v1 写"支持三种查询模式；跳数>3 拒绝并提示分解查询"；oracle 补 entry 变体、自定义 steps、"负荷→回路→变压器→容量约束"的机械路径（LoadCurve -metered_at-> Feeder -upstream_of(in)-> Transformer + 属性拾取）与**属性拾取步不计关系跳数**口径、关系注册校验与环路防护；tests/CHANGELOG.md M4 登记 4；00 v2 §1.2 已同步]

- **SPEC-M4-06 OntologyView 预算化概念视图（token 计量口径）**：冻结 API `concept_view(entity_ids, token_budget=1024, *, loaded, max_edges=8) -> OntologyView`（`view.py:116-221`）。
  **装配口径**：逐实体三段（core_attributes → relations → constraint_rule_ids）+ 实体头（id+类型）必入，按实体顺序贪心装箱：段落装不进预算即裁掉并记 `trimmed`（kind=core_attributes/relation_neighborhood/constraint_rules；实体头超预算→整实体不装，kind=entity_header）；关系邻域截断 `max_edges`(8) 亦记 trimmed（`view.py:169-216,88-113`）。核心属性口径：实例属性 ∩ objects.yaml 声明属性；类型未声明属性时按 key 排序取前 8（`view.py:88-95`）。**远端路径（≥2 跳邻域）一律不注入**，存在即记 trimmed（kind=remote_path）（`view.py:159-167`）；实体不存在记 trimmed（kind=unknown_entity）；本体未加载实例→视图为空并记 no_instance（`view.py:137-140,148-151`）。
  **token 计量口径（D-36）**：`estimate_tokens(text)` = CJK 字符 1 token/字 + ASCII 词元（`[A-Za-z0-9_@.\-]+` 连续串）1 token/串——确定性估算、无模型调用；datetime/date 先转 ISO 字符串再计量；视图 `tokens` = 逐保留实体条目的估算合计（`view.py:27-48,218-220`）。实测：`estimate_tokens("温度TX-01")`=3。
  **Manifest 联动**：`OntologyView.to_manifest_source()` → ContextManifest source 条目（name=ontology_view, type=ONTOLOGY_VIEW, priority=2, origin=ontology_view, tokens, trimmed=有裁剪即 true, entity_ids）（`view.py:66-76`）；M2 context_builder 以 type=ONTOLOGY_VIEW 落 `task.ontology_view` source（`src/m2_information/context_builder.py:334-337`）。实测：dev-graph 实例 entity_ids=[AL-0201,TX-01,BUS-A1,WO-D0021]、预算 200 → tokens=193≤200、entries=4、trimmed 含 remote_path、source.trimmed=True。
  - oracle 证据：`src/m4_semantic/view.py:27-48,51-85,88-113,116-221`；`src/m2_information/context_builder.py:334-337`。
  - [v2Δ D-36: v1 写"超预算时保留：对象核心属性+关系邻域+直接约束规则 ID，丢弃远端路径（被裁内容记入 Manifest origin=ONTOLOGY_VIEW, trimmed=true）"；oracle 细化为三段贪心装箱+逐段 trimmed 登记（含 entity_header/unknown_entity/no_instance/截断记录）+ **CJK 1/字 + ASCII 词元 1/串** 的确定性 token 计量口径；tests/CHANGELOG.md M4 登记 7]

- **SPEC-M4-07 规程引用规范（规则 ID + 判据结构 + 存在性联动）**：一切规程引用以规则 ID 形式返回（如 PHYS-TX-LOAD），不引用原文行号（`regulation.py:12`）。
  `RegulationIndex`：四份规程合一索引（loader 已做跨文件 ID 唯一性校验，SPEC-M4-01 第 6 项）；条目 = rule_id/file/title/category/scope/parent/clauses/criterion；**criterion 判据结构** = metric/unit/expression（criterion 文本）/thresholds 阶梯（REG-TECH）或 metrics 映射（REG-OP criteria）（`regulation.py:41-87`）。
  `retrieve(rule_id)` → 条款+判据结构；未知 ID → ValueError（列出全部可引用 ID）（`regulation.py:107-113`）。实测：PHYS-TX-LOAD criterion={metric, expression, thresholds:[{op:>,value:0.8,level:P2,过载预警},{op:>,value:1.0,level:P0,重过载跳闸风险}]}。
  **关键词检索**：中文无分词——查询串滑窗 2-gram 对 title+clauses+criterion+metric+rule_id 打分（重叠数），按 (-score, rule_id) 排序，limit 缺省 5（`regulation.py:28-38,115-128`）。
  `rules_for_scope(type_id)`：对象类型→直接约束规则 ID（REG-TECH 条款 `scope` 字段数据驱动，按 ID 排序）；OntologyView 约束规则段与 `LoadedOntology.constraint_rules_for` 同源（`regulation.py:130-135`；`loader.py:446-450`）。实测：Transformer→[PHYS-TX-LOAD, PHYS-TX-TEMP]。
  **M4→M2 存在性联动（ADDENDUM §B）**：`rule_id_checker()` 工厂返回 `unknown_rule_ids` 绑定函数，注入 `InformationLayer(rule_id_checker=…)` 后，report.daily@v1 等 schema 校验对 `regulation_refs` 做规则 ID 存在性核对（不存在→REJECTED，非仅形态校验）（`regulation.py:97-99,146-156`）；注入点 = M1/M2 eval_plugin 与 M6 CaseRunner（`src/m1_core/eval_plugin.py:98`、`src/m2_information/eval_plugin.py:60,493`、`src/m6_flywheel/evaluator.py:348`；核对落位 `src/m2_information/artifact.py:136-137`）。
  - oracle 证据：`src/m4_semantic/regulation.py:12,28-38,41-87,97-156,165-167`；`src/m2_information/artifact.py:136-137`。
  - [v2Δ: v1 写"所有规程引用以规则 ID 形式返回；报告类 Artifact 引用条款时必须带规则 ID（M2 schema 校验联动）"；oracle 补 criterion 判据结构、2-gram 检索算法、scope 数据驱动口径与 rule_id_checker 工厂注入的具体落位（ADDENDUM §B 转正；tests/CHANGELOG.md 独立评审缺口修复 2）]

- **SPEC-M4-08 覆盖率监测与 badcase 候选事件（触发口径与职责切分）**：
  **概念注册表**（何谓"已在本体注册"）：对象类型 ∪ 关系 ∪ 动作 ID ∪ rules.yaml 规则 ID ∪ regulations 条款 ID ∪ 属性词典 canonical 名 ∪ 实例实体 ID——全部来自 ontology/ 与实例数据，不硬编码；惰性构建一次（`coverage.py:61-78`）。
  **任务级报告**：`record_task(task_id, concepts, *, trace_id=None, persist=True) -> dict` → {task_id, recorded_at(UTC), ontology_version, hits, total, ratio(4 位舍入), missing_ratio, missing, candidate_events}；空概念列表 ratio=1.0 且不产事件（`coverage.py:81-117`）。
  **触发口径（D-37）**：缺失概念比例 ≥ `MISSING_BADCASE_THRESHOLD`(0.30)（等价命中率 <70%，00 §4）→ 产出 `badcase.opened` **候选事件**：EventRecord dict 经 `contracts.EventRecord.from_dict` 结构校验（缺 trace_id/非法枚举在产出即拒），`producer="M4"`、`payload.candidate=true`、payload 含 reason=ontology_coverage_missing/task_id/missing_ratio/missing/ontology_version、event_id=`01M4COV`+uuid 片段、occurred_at、trace_id（缺省 `cov-<task_id>`）（`coverage.py:28-29,109-112,120-143`）。实测：10 概念 3 未注册→ratio=0.7、事件类型 badcase.opened、producer=M4、candidate=true。
  **职责切分**：M4 只产出候选；事件持久化（runtime/events/ 事件流）归 M2/M6；候选处置归 M6 Badcase 流水线。任务级报告落 `runtime/coverage/task-<task_id>.json`（文件名安全化、截 80 字符）（`coverage.py:12-13,38-40,145-151`）。
  **窗口聚合**（01 §3.4 `coverage_report(window)`）：window=None=全部已记录任务；{task_ids:[…]} 指定任务；或 {from,to} UTC ISO 时间窗（按 recorded_at）；聚合口径 hits/total 求和、missing 并集（保序去重）；结果 {tasks, hits, total, ratio, missing}；覆盖率月报进 M7（`coverage.py:166-200`）。
  - oracle 证据：`src/m4_semantic/coverage.py:12-13,28-29,38-40,61-78,81-117,120-151,166-212`。
  - [v2Δ D-37: v1 M4 条款已有"缺失概念≥30% 触发 badcase.opened 候选事件"表述；oracle 细化为 contracts 产出即校验 + producer=M4/payload.candidate=true 机械形态 + **持久化归 M2/M6、M4 只产出候选**的职责切分 + 报告落盘与窗口聚合口径（00 v1 §4 原文"低于 70% 告警（写入飞轮 Badcase 候选）"按 oracle 修正，见 00 v2 §4）；tests/CHANGELOG.md M4 登记 6]

### 3.3 eval 资产

- **SPEC-M4-09 EVAL 执行器插件（数据驱动用例的执行器契约）**：`tests/test_m4.yaml` 的执行器注册于 `src/m4_semantic/eval_plugin.py`（`EXECUTORS`，EVAL-SCHEMA §4 插件契约：`fn(case, ctx) -> {"passed": bool, "detail": str, "metrics": dict}`）；9 个执行器：`m4.load_ok` / `m4.load_reject` / `m4.resolve` / `m4.query` / `m4.query_reject` / `m4.view` / `m4.regulation` / `m4.coverage` / `m4.query_latency`（`eval_plugin.py:479-489`）；另有 1 个**补充执行器** `m4.loader_drift`（`tests/m4_eval_extra.py`，变异覆盖缺口修复轮新增——oracle 执行器没有的"加载期数据漂移"负向执行面：ontology/ 临时副本注入 patch 后 `load_ontology(ontology_dir=副本)` 断言拒绝，不改 oracle，`tests/m4_eval_extra.py:47-90`）。
  全部执行器只读 `case.params` 声明的数据（文本/ID/预算/期望值均来自 YAML 用例文件），零输入特判；非 seed 实例经 `PARK_INSTANCE_PATH` 追加 `tests/fixtures` 注入（用例结束还原环境）（`eval_plugin.py:41-66`）。
  覆盖口径：load_ok=版本 hash 稳定+内容敏感性（复制目录改一字节 hash 必变）+动作清单与 actions.yaml 逐条一致+默认实例加载；load_reject=四类负向（实例悬空引用/注册表不对齐/版本不匹配/实例文件不存在）断言异常类型与消息；resolve=唯一消歧（无 ambiguous 标记）/候选列表（all_ambiguous+min_candidates+contains_entity+reasons_nonempty）/属性挂接；query=终端集合/首路径节点链/关系跳数/终端属性/模式声明跳数；query_reject=>3 跳拒绝且消息含"分解"；view=tokens≤上限/核心属性/规则 ID/trimmed/Manifest source type=ONTOLOGY_VIEW；regulation=检索首选/条款数/判据字段/scope/未知引用；coverage=hits/total/ratio/missing/候选事件/落盘（`eval_plugin.py:79-442`）。
  **DoD §5 时延门槛常态化**：EVAL-M4-09-P1（performance 形态；v1 id EVAL-M4-PERF-P 改名对应）——三种查询模式端到端（内存图构建+查询）门槛 max_ms=50 为用例数据非代码，每模式 iterations 次取最坏；登记实测 ≤0.32ms（`eval_plugin.py:448-476`）。
  - oracle 证据：`src/m4_semantic/eval_plugin.py:41-66,79-476,479-489`；`tests/test_m4.yaml:17-18,303-318`（v2 重生成版套件的 executors 声明与时延用例）。
  - [v2Δ: v1 §4 仅列 12 条用例、无执行器契约条款；oracle 13 用例（12 条机械生成 + 1 条 DoD 时延）+ 9 执行器；EVAL-M4-PERF-P 为 DoD §5 自测的常态化落盘（规格 §4 表外补强，eval 资产登记）；tests/CHANGELOG.md M4 登记 5。v2 重生成把它改名 EVAL-M4-09-P1 归入本条款，套件扩为 17 用例（§4）]

## 4. Eval（`tests/test_m4.yaml`，v2 重生成 + 变异缺口修复版 · 19 用例）

[v2Δ D-重生成: 按 01 v2 §6 协议机械重生成——spec_ref 改指 specs-v2 三件（v2 条款 id 的定义处）+ `specs/ADDENDUM.md`
（specs-v2/ADDENDUM.md 尚未生成，见 specs-v2/README.md 交付物清单；其落盘后须重算 spec_hash 再登记）。
v1 版基线对（spec_ref=specs/ v1 四件）：spec_hash `f93c7c26f4b63512e5d14efb81ce5c1506f5e7bcbfd731954d4fcbc1d07abbb8`
→ eval_hash `513d21fffa02f54b63466d2450474a42a2140f8553a6af848c6583171e12db54`（tests/CHANGELOG.md 2026-09-28 M4 登记）；
v1→v2 登记对见 `tests/CHANGELOG.md` 2026-09-29 条目。执行器 9 个原样重用（`src/m4_semantic/eval_plugin.py`）。]

### 4.1 条款→用例双向映射

| v2 条款 | 正例（P） | 负例（N） | 覆盖要点 |
| --- | --- | --- | --- |
| SPEC-M4-01 加载校验 | EVAL-M4-01-P | EVAL-M4-01-N1 / EVAL-M4-01-N3 | 分项校验+版本 hash 稳定/内容敏感+动作清单导出；注册表 diff 非空拒绝；enums↔contracts 词表漂移拒绝 |
| SPEC-M4-02 实例按名加载 | EVAL-M4-02-P1 | EVAL-M4-02-N1 / EVAL-M4-02-N2 | §D 搜索序加载正例；实例文件不存在拒绝；实例引用悬空校验拒绝 |
| SPEC-M4-03 版本管理 | （正例断言内嵌 EVAL-M4-01-P：同内容 hash 稳定+内容敏感） | EVAL-M4-03-N1 | 版本不匹配任务拒绝启动 |
| SPEC-M4-04 实体解析 | EVAL-M4-04-P1 | EVAL-M4-04-N1 | 唯一消歧（无 ambiguous 标记+联动传感器）；歧义候选不擅断 |
| SPEC-M4-05 图查询 | EVAL-M4-05-P1 / P2 / P3 | EVAL-M4-05-N1 / EVAL-M4-05-N2 | 三种查询模式逐一落位（含跳数计数口径）；关系步数闸与声明跳数闸各有专项负例 |
| SPEC-M4-06 OntologyView | EVAL-M4-06-P1 | —（预算裁剪无禁止性负例；裁剪不足即正例断言失败） | token 预算+trim 登记+Manifest 联动 |
| SPEC-M4-07 规程引用 | EVAL-M4-07-P1 | （未知引用断言内嵌：NO-SUCH-RULE 判不存在） | 检索+判据结构+scope+存在性联动判据面 |
| SPEC-M4-08 覆盖率 | EVAL-M4-08-P1 | EVAL-M4-08-N1 | ≥30% 触发候选事件+落盘；未达阈值不得触发（禁止性负例） |
| SPEC-M4-09 执行器插件 | EVAL-M4-09-P1 | —（插件契约无禁止性负例） | 9 oracle 执行器+1 补充执行器；DoD §5 时延门槛数据驱动 |

### 4.2 用例总表

| EVAL ID | SPEC | form / executor | 场景 | 期望 |
| --- | --- | --- | --- | --- |
| EVAL-M4-01-P | 01 | expression / m4.load_ok | 加载合法本体 | 成功，版本 hash 稳定且内容敏感，动作清单 16 条与 actions.yaml 一致，默认实例已加载 |
| EVAL-M4-01-N1 | 01 | negative_rejection / m4.load_reject | 注册表 diff 非空（缺 query.measurement、多 bogus.action） | `RegistryAlignmentError`（消息含"对齐失败"） |
| EVAL-M4-01-N3 | 01 | negative_rejection / m4.loader_drift | enums 副本漂移（alarm_level 移除 P3） | `OntologyLoadError`（消息含"受控词表不一致"） |
| EVAL-M4-02-P1 | 02 | expression / m4.resolve | 非缺省实例 dev-graph 按名加载（§D）+ 其上实体解析 | 唯一消歧 SG-A01+PD-A01（attribute=pd） |
| EVAL-M4-02-N1 | 02 | negative_rejection / m4.load_reject | 实例名不在任何搜索目录 | `InstanceLoadError`（消息含"园区实例文件未找到"） |
| EVAL-M4-02-N2 | 02 | negative_rejection / m4.load_reject | 实例关系引用不存在设备（TX-09/SG-A09） | `InstanceLoadError`，错误含缺失 ID |
| EVAL-M4-03-N1 | 03 | negative_rejection / m4.load_reject | 期望版本 ≠ 目录内容 hash | `OntologyVersionMismatchError`（消息含"版本不匹配"） |
| EVAL-M4-04-P1 | 04 | expression / m4.resolve | "2 号变压器温度""A 房 1 号柜局放" | 唯一消歧：TX-02+winding_temp；SG-A01+PD-A01（联动传感器） |
| EVAL-M4-04-N1 | 04 | expression / m4.resolve | "3 号变压器"（无房拥有第 3 台变压器） | 候选≥3 含 TX-03，全部 ambiguous、含理由，不猜 |
| EVAL-M4-05-P1 | 05 | expression / m4.query | 告警影响面 AL-0201 | 终端 {TX-02,TX-03}，首链 [AL-0201,TX-01,BUS-A1,TX-02]，hops=3=模式声明 |
| EVAL-M4-05-P2 | 05 | expression / m4.query | 过载研判 LC-A0901 | 终端 TX-01，链 [LC-A0901,F-A1,TX-01]，hops=2（属性拾取 capacity_kva=1600 不计跳），模式声明 hops=3 |
| EVAL-M4-05-P3 | 05 | expression / m4.query | 消缺闭环 WO-D0021 | 终端 MP-TX01，链 [WO-D0021,AL-0201,TX-01,MP-TX01]，terminal next_due=2026-12-05，hops=3 |
| EVAL-M4-05-N1 | 05 | negative_rejection / m4.query_reject | 四跳查询（关系步数闸） | 拒绝，消息含"分解" |
| EVAL-M4-05-N2 | 05 | negative_rejection / m4.query_reject | 声明 hops=4 但路径仅 1 跳关系（声明跳数闸专项） | 拒绝，消息含"分解" |
| EVAL-M4-06-P1 | 06 | expression / m4.view | 预算 200 tokens 的大邻域 | tokens≤200，保核心属性+规则 ID，trimmed+Manifest source 带 trimmed=true |
| EVAL-M4-07-P1 | 07 | expression / m4.regulation | 检索"变压器负载率要求" | PHYS-TX-LOAD 条款+判据（metric/thresholds），scope=Transformer，NO-SUCH-RULE 判不存在 |
| EVAL-M4-08-P1 | 08 | expression / m4.coverage | 10 概念 3 个未注册 | ratio=0.7，`badcase.opened` 候选事件，缺失清单落盘 |
| EVAL-M4-08-N1 | 08 | expression / m4.coverage | 7 概念全部已注册 | ratio=1.0、零缺失、不触发候选事件（禁止性负例），报告仍落盘 |
| EVAL-M4-09-P1 | 09 | performance / m4.query_latency | 三种查询模式端到端 ×5 次取最坏 | < 50ms（数据驱动门槛） |

### 4.3 v1→v2 用例去向（逐条核对后保留改名/新增）

| v1 用例 | v2 用例 | 核对结论 |
| --- | --- | --- |
| EVAL-M4-01-P | EVAL-M4-01-P | 保留原名；断言（七项校验/hash 稳定+内容敏感/动作清单/默认实例）逐项对应 v2 SPEC-M4-01 |
| EVAL-M4-01-N（instance_missing_ref） | EVAL-M4-02-N2 | 改条款归属：实例引用校验属 v2 SPEC-M4-02（实例校验），非本体五文件校验 |
| EVAL-M4-01-N2（registry_misaligned） | EVAL-M4-01-N1 | 改名；断言不变，对应 v2 SPEC-M4-01 对齐断言 |
| EVAL-M4-02-P | EVAL-M4-04-P1 | 改名；断言不变——v2 SPEC-M4-04（序号双读法/唯一消歧/联动传感器）的机械口径即该断言 |
| EVAL-M4-02-N | EVAL-M4-04-N1 | 改名；断言（all_ambiguous+min_candidates+reasons）即 D-34 消歧阈值的负向面 |
| EVAL-M4-03-P | EVAL-M4-05-P1 | 改名；断言含 expect_hops=3=expect_pattern_hops，对应 v2 SPEC-M4-05 跳数口径 |
| EVAL-M4-03-P2 | EVAL-M4-05-P2 | 改名；断言 hops=2≠声明 3 即 D-35"属性拾取不计跳"口径 |
| EVAL-M4-03-N | EVAL-M4-05-N1 | 改名；>3 跳拒绝+建议分解 |
| EVAL-M4-04-P | EVAL-M4-06-P1 | 改名；断言 tokens≤预算/核心属性/规则 ID/trimmed/Manifest 即 v2 SPEC-M4-06 |
| EVAL-M4-05-P | EVAL-M4-07-P1 | 改名；断言含 expect_unknown_refs（存在性联动）即 v2 SPEC-M4-07 |
| EVAL-M4-06-P | EVAL-M4-08-P1 | 改名；断言 ratio=0.7+候选事件+落盘即 v2 SPEC-M4-08（D-37） |
| EVAL-M4-07-P（version_mismatch） | EVAL-M4-03-N1 | 改条款号：版本管理在 v2 重排为 SPEC-M4-03 |
| EVAL-M4-PERF-P | EVAL-M4-09-P1 | 改名并归入 v2 SPEC-M4-09（执行器插件条款，含 DoD §5） |
| （v1 无） | EVAL-M4-02-P1 | 新增：§D 非缺省实例按名加载正例（原 13 条对 §D 仅间接覆盖） |
| （v1 无） | EVAL-M4-02-N1 | 新增：unknown_instance_file 拒绝路径（执行器 `m4.load_reject` 实有 attempt，v1 用例未覆盖） |
| （v1 无） | EVAL-M4-05-P3 | 新增：defect_closure 模式落位（v1 三模式仅测其二） |
| （v1 无） | EVAL-M4-08-N1 | 新增：未达阈值不得触发候选事件（禁止性负例） |
| （v1 无） | EVAL-M4-01-N3 | 变异缺口修复轮新增（2026-09-29）：enums↔contracts 词表漂移拒绝——变异 m4-vocab-crosscheck-off 存活反证的盲区，经补充执行器 `m4.loader_drift`（tests/m4_eval_extra.py，不改 oracle）落位 |
| （v1 无） | EVAL-M4-05-N2 | 变异缺口修复轮新增（2026-09-29）：声明跳数闸专项负例——变异 m4-hop-declared-gate-off 存活反证 EVAL-M4-05-N1 被关系步数闸共同击杀、声明闸无独立守护 |

## 5. DoD

- EVAL 全绿（oracle 基线实跑：`python run_evals.py --module m4` → `cases=13/13 failed=0 result=PASS`；
  v2 重生成+变异缺口修复版 19 用例已做静态自检（YAML schema/执行器名/fixtures 引用）与新增用例直调干跑，
  受控变异测试 5 红线变异全杀（redline_all_killed=true），统一门禁由资产工程收口轮执行）；
- 三种查询模式端到端时延 < 50ms（内存图；数据驱动门槛 EVAL-M4-09-P1；CHANGELOG M4 登记 5 实测 ≤0.32ms）；
- resolver 别名表以数据文件维护（`ontology/aliases.yaml`，新增设备零代码——"N 号<类型>"序号读法按 `generic_ordinal` 泛化匹配，显式别名刻意不收录该形式，D-34）。

## 6. 交付物

- `src/m4_semantic/`（loader/resolver/graph/view/regulation/coverage/eval_plugin/__init__）[v2Δ: 补 eval_plugin.py 与 __init__.py]；
- `ontology/aliases.yaml`（实体解析数据文件）；
- `tests/test_m4.yaml`（19 用例，v2 重生成+变异缺口修复版，spec_ref 指向 specs-v2）+ `tests/m4_eval_extra.py`（补充执行器 m4.loader_drift，不改 oracle）+ `tests/fixtures/dev-graph.yaml`（EVAL 图查询实例注入，ADDENDUM §D 机制）[v2Δ: 补 dev-graph.yaml——v1 交付物清单未列而 oracle 实有]；
- 运行期产物（gitignore，不进 git）：`runtime/coverage/task-<task_id>.json`（任务级覆盖率报告落盘）。
