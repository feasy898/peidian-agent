# M4 · Semantic（本体语义层）Spec + Eval

> 职责一句话：让 agent 用本体理解园区配电世界——实体解析、多跳查询、概念视图注入、覆盖率监测。
> 数据源：`ontology/*.yaml`（00-ontology.md 机器可读版）与 `regulations/*.yaml`。本体运行期只读。

## 1. 职责边界

**做**：本体加载与版本管理（目录 hash）；实体解析（文本→本体实体链接）；图查询（三跳内）；OntologyView 生成（Context 注入用，按 token 预算裁剪）；规程条款检索（按规则 ID/关键词）；覆盖率监测与缺失报告。
**不做**：本体编辑（走 M7 变更评审）；业务判断（规则判定在 M3 policy 与 M5 仿真判据中）。

## 2. 内部组件

```text
m4_semantic/
├── loader.py        # ontology/ 加载+完整性校验（枚举封闭性/引用完整性/动作表一致性）
├── resolver.py      # 实体解析：别名表+模糊匹配（设备号/简称/名称）
├── graph.py         # 内存图（networkx 或等价），三跳查询
├── view.py          # OntologyView：选中实体的邻域摘要（含关键属性+关系+约束规则 ID）
├── regulation.py    # 规程索引（规则 ID→条款文本+判据结构）
└── coverage.py      # 覆盖率统计（任务级+窗口级）
```

## 3. 行为规格（SPEC 条款）

- **SPEC-M4-01 加载校验**：加载时校验——关系引用的对象/设备均存在；动作表与 M3 注册表对齐（接口：导出动作清单）；枚举值全部在受控词表内。任一失败→拒绝加载（启动失败优于带病运行）。
- **SPEC-M4-02 实体解析**：`resolve_entities("2 号变压器温度")` → [{TX-02, attr: winding_temp}]（别名：N 号→ID 映射表 + 属性词典）；无歧义阈值内多候选时返回候选列表（不擅自择一）。
- **SPEC-M4-03 三跳查询**：支持 00§1.2 三种查询模式（告警影响面/过载研判/消缺闭环）；跳数>3 拒绝并提示分解查询。
- **SPEC-M4-04 OntologyView 预算化**：注入 Context 的概念视图带 token 预算；超预算时保留：对象核心属性+关系邻域+直接约束规则 ID，丢弃远端路径（被裁内容记入 Manifest origin=ONTOLOGY_VIEW, trimmed=true）。
- **SPEC-M4-05 规程引用规范**：所有规程引用以规则 ID 形式返回（如 PHYS-TX-LOAD）；报告类 Artifact 引用条款时必须带规则 ID（M2 schema 校验联动）。
- **SPEC-M4-06 覆盖率监测**：每任务结束后输出 task 级报告（命中/涉及/缺失清单）；窗口聚合月报进 M7；缺失概念≥30% 触发 `badcase.opened` 候选事件。
- **SPEC-M4-07 版本管理**：本体版本=ontology/ 目录内容 hash；ReleaseBundle.ontology_version 必须与本层报告一致；版本不匹配的任务拒绝启动（防本体漂移）。

## 4. Eval（`tests/test_m4.yaml`）

| EVAL ID | 对应 SPEC | 场景 | 期望 |
| --- | --- | --- | --- |
| EVAL-M4-01-P | 01 | 加载合法本体 | 成功，版本 hash 稳定 |
| EVAL-M4-01-N | 01 | 种子中引用不存在设备 | 启动拒绝，错误含缺失 ID |
| EVAL-M4-01-N2 | 01 | 动作表与 M3 注册表 diff 非空 | 加载拒绝（对齐失败） |
| EVAL-M4-02-P | 02 | "2 号变压器温度""A 房 1 号柜局放" | 正确实体（TX-02/SG-A01+PD-A01） |
| EVAL-M4-02-N | 02 | "3 号变压器"（PARK-001 只有 TX-01/02/03 但语义歧义） | 返回候选列表含理由，不猜 |
| EVAL-M4-03-P | 03 | 告警 TX-01→同母线设备 | 返回 BUS-A1 邻域正确集合 |
| EVAL-M4-03-P2 | 03 | 负荷→回路→变压器→容量 | 三跳链完整（含 capacity_kva） |
| EVAL-M4-03-N | 03 | 四跳查询 | 拒绝+建议分解 |
| EVAL-M4-04-P | 04 | 预算 200 tokens 的大邻域 | 裁剪后≤200，含核心属性+规则 ID，Manifest 有 trim 记录 |
| EVAL-M4-05-P | 05 | 检索"变压器负载率要求" | 返回 PHYS-TX-LOAD 条款+判据结构 |
| EVAL-M4-06-P | 06 | 任务涉及 10 概念、3 个未注册 | 报告 ratio=0.7，缺失清单落盘 |
| EVAL-M4-07-P | 07 | Release 指定旧本体版本运行 | 任务启动拒绝（版本不匹配） |

## 5. DoD

- EVAL 全绿；
- 三种查询模式端到端时延 < 50ms（内存图）；
- resolver 别名表以数据文件维护（`ontology/aliases.yaml`，新增设备零代码）。

## 6. 交付物

`src/m4_semantic/` + `ontology/aliases.yaml` + `tests/test_m4.yaml`。

