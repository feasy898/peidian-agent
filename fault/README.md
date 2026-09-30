# fault/ · 故障注入与 agent 反应（worker-B · 线3）

owner 北极星（2026-10-01 夜班令）中的两块：
**通过与 LLM 沟通定向注入故障**、**实时展示 agent 反应步骤（可视化时间线）**、
**人机对比模式**。本目录为纯后端引擎 + 事件流，不含 UI（worker-A web/ 消费本接口）。

## 1. 模块图

```
llm_bridge ──► dsl（四类白名单校验，越界即拒）
                 │ FaultSpec
                 ▼
engine（编排：注入时刻表→遥测→检测→反应→操作→事件流）
  ├─ topology   拓扑只读图（与 worker-A dsl/ 的同构 mock 接口，§2）
  ├─ telemetry  伪实时遥测（确定性 seed，§5）
  ├─ detect     异常检测（阈值判 + 拓扑断判，只读遥测不读注入计划）
  ├─ agent      反应引擎（可解释步骤流，§3）
  ├─ actions    操作执行器（agent 与人工同款操作面，§6）
  └─ stream     事件流 EventBus（append-only JSONL，§4）
```

运行自测：`python fault/run_tests.py`（13 用例，退出码 0=全过；
事件流样例落盘 `fault/examples/eventstream-*.jsonl`）。

## 2. 拓扑接口（对 worker-A 线1 dsl/ 的对接契约）

worker-A 生成器落位后，产出满足以下 schema 的 dict/YAML，用
`Topology.from_dict(d)`（或补一个 `from_yaml`）装载即可替换内置演示园区
`demo_park()`，fault/ 其余代码**零改动**：

```yaml
park_id: PARK-001
elements:                      # 全部元件平铺
  - {id: GRID-A, kind: grid_infeed, name: 电网进线A, rated_mw: 20}
  - {id: LN-A0, kind: line, name: A区进线, from: GRID-A, to: BUS-A1, rated_kw: 3000}
  - {id: SG-A01, kind: switchgear, name: A区出线1开关, from: BUS-A2, to: LN-A1,
     normally: CLOSED, operable: true}          # 开关必须给 operable 才可遥控
  - {id: TX-01, kind: transformer, name: 1号主变, from: BUS-A1, to: BUS-A2,
     capacity_kva: 1600}
  - {id: BUS-A2, kind: bus, name: 0.4kVⅠ段母线, voltage_level: 0.4kV}
  - {id: LOAD-A1, kind: load, name: A区末端负荷, at: BUS-A2, base_kw: 240}
  - {id: PV-01, kind: pv, name: 屋顶光伏1, at: BUS-A3, capacity_kwp: 400}
```

约束（违者构造时 ValueError）：
- kind ∈ {grid_infeed, bus, line, transformer, switchgear, pv, bess, evcharger, load, capacitor}；
- 边元件（line/transformer/switchgear）带 `from`/`to`，端点可为节点或另一边元件
  （支持开关-线路串联链）；叶元件（pv/bess/evcharger/load/capacitor）带 `at`=母线；
- ID 全局唯一；元件 ID 约定沿用仓库 ontology/seed.yaml 口径（TX-*/BUS-*/SG-*/LN-*）；
- **倒闸转供需要联络开关**：复杂园区建议每对主变低压段间给一台
  `normally: OPEN` 的联络开关（无联络开关时 agent 只隔离不转供，如实报告待抢修）。

## 3. agent 反应引擎（步骤流语义）

检测→处置流程固定 8 相（`agent.step` 事件 `payload.phase`）：
`confirm → diagnose(遥测复核/影响分析) → judge → plan → isolate(执行) →
restore(倒闸转供,可选) → summary →(engine 复测)→ verify → 闭环 summary`。

每步必须给出 **looked_at（看了什么）/ found（判了什么）/ why（为什么）**——
前端时间线按此三字段渲染，缺一不可（测试断言）。判别签名表：
`fault/agent.py SIGNATURES`；阈值：`fault/detect.py`（过载阈值 doc 来源
仓库 `regulations/REG-TECH.yaml:23-24` PHYS-TX-LOAD：>0.80 P2 预警、>1.00 P0 重过载）。

四类故障的处置策略（演示逻辑，可扩展）：
| 类型 | 隔离 | 恢复 |
|---|---|---|
| SHORT_CIRCUIT(变压器) | 开两侧直连开关（明显断开点） | 联络开关倒闸转供失电母线（带负载率投影校验） |
| LINE_BREAK(线路) | 开馈线开关 | 故障区下游**不**转供（会带故障），如实报"待抢修" |
| TX_OVERLOAD | 故障变退出（两侧开关） | 全负荷经联络开关转供，转供后高位触发 threshold.warn |
| PV_TRIP | 无网络操作 | 告警确认（ack）+ 通知运维，消缺前异常保持（不假报清除） |

动作后复测未消除 → `control.escalated` + `agent.step(phase=escalate)`，绝不假绿。

## 4. 事件流 schema（对 worker-A web/ 的数据契约）

`EventBus` 单调 seq，每事件：
```json
{"seq": 12, "ts": "2026-10-01T12:00:05.123Z", "sim_s": 4.0,
 "channel": "agent", "type": "agent.step", "payload": {...}}
```
- channel ∈ {control, fault, agent, ops, telemetry}；
- control: `mode.agent_enabled / mode.agent_disabled / control.passed / control.escalated`
- fault: `fault.planned / fault.injected / fault.detected / anomaly.cleared / threshold.warn`
- agent: `agent.step`（时间线主体）
- ops: `action.executed / action.rejected`（含 by=agent|human，操作审计）
- 增量拉取：`stream.since(seq)`；整流落盘：`stream.write_jsonl(path, channel=None)`。
- 前端管道建议：SSE/WebSocket 从 engine 包一层即可；本目录不实现 HTTP。

## 5. 伪遥测口径（演示简化，均为声明值 doc）

负荷形状恒定 1.0、日照恒定 DAYLIGHT=0.7、噪声 ±3%（seed 确定）；
短路=故障电流信号 +6.0pu + 故障区电压 0.15pu（隔离后消失）；
断线=边阻断、下游失电、光伏联锁脱网；过载=下游负荷按 overload_ratio 反推激增；
光伏脱网=出力 0。检测器只读遥测与开关态，**不读注入计划**（诚实检测）。

## 6. 人机对比模式（操作面契约）

- 总开关：`engine.set_agent_enabled(bool, note)` → control 事件；
- 关闭后：异常照常 `fault.detected`，随后 `control.passed`（交人工），
  **零 agent 步骤**；
- 人工操作与 agent 完全同款执行器：
  `engine.human_action({"op": "open|close|ack", "target": "SG-A01", "reason": "..."})`
  → 同一 `ActionExecutor` → 同一 ops 事件（by=human）→ 同一异常清除归属
  （`anomaly.cleared.by=human`）；
- 非法操作（白名单外 op / 非开关目标 / 不可遥控 / ack 不存在异常）→
  `action.rejected`，绝不放行。

## 7. LLM 定向注入（线3-2）

- 提示词落盘 `fault/prompts/inject_system.md`（`{{ELEMENTS}}` 由
  `render_prompt(topology)` 按当前拓扑填充）；
- 调用：`nl_to_fault(text, topo, client=HigressClient())`——
  Higress 100.100.0.6:8080（key 经 bao 注入环境变量 `HIGRESS_API_KEY`，
  argv-free 零打印）；client=None 或通道故障 → 规则解析器离线兜底，页面不瘫；
- **零信任**：LLM 输出一律过 `dsl.validate_fault_dict`（四类白名单/参数域/
  元件存在性/类型-元件兼容），越界 → `FaultRejected`（逐条中文理由），
  不静默兜底（注入是危险操作）；
- 本轮测试用 FakeLLM 脚本化验证守门逻辑，**零真实模型调用**（配额 0/3 消耗）。

## 8. 已知边界（如实声明）

- 演示拓扑为辐射状，合联络开关形成双端供电时功率求和按带电可达 BFS，不做潮流；
- 短路故障电流 +6pu 为仿真信号非物理计算（M5 精度边界同口径声明）；
- 复杂园区（worker-A 生成）若多主变/多联络，agent 转供按"最大投影负载率最小"
  贪心选择单台联络开关，不做全局优化；
- 遥测 tick dt=0.5s（Engine 可调），事件 sim_s 为仿真秒。

## 9. python↔node 桥与真实园区接入（线4-1，第 2 轮新增）

- `park_adapter.py`：ParkDSL 导出 JSON（parkdsl-web/1）→ `Topology`。kind 映射按
  judge 第 2 轮裁决；**CP=联络点（coupler→常开开关）**，CapacitorBank→capacitor 叶
  （judge 表中 "capacitor↔CP" 疑笔误，已在 worklog 第 2 轮提请仲裁）。EVC 按负荷参与
  潮流；BESS/CapacitorBank 潮流中性（未建充放模型，如实声明）。
- `bridge.py`：CLI 桥（stdin JSON→stdout JSON）。`mode=inject` 纯解析；`mode=simulate`
  全链路（NL→DSL→引擎→FaultEvent v0.1 + 完整事件流 + 开关终态 + 处置摘要）。拒绝
  → `{"ok":false,"rejected":true,"reasons":[…]}` exit 3。环境无 `HIGRESS_API_KEY` 或
  `FAULT_BRIDGE_FORCE_OFFLINE=1` → 规则解析兜底，`llm.used=false` 留证，页面不瘫。
- `web_module.js`：node 挂点模块（`FAULT_MODULE=<repo>/fault/web_module.js`，
  server.js 零改动）。`inject(parkJson,text)`=simulate(auto) 的 FaultEvent（含
  agent.steps）；`simulate(parkJson,opts)` 供 v0.2 时间线取完整事件流。入口守卫：
  park.id 白名单 `^[A-Z0-9][A-Z0-9-]{0,31}$`、text 1..500 字符、30s 超时、16MB 上限；
  默认解释器 `<repo>/.venv/bin/python`（`PYTHON_BIN` 可覆盖；勿用 3.11）。
- `run_matrix.py`：端到端矩阵（3 档园区×4 类故障×人机两态+拒绝探针），结果落盘
  `examples/matrix-round2.{json,md}`。GPU 机实跑 25/25 PASS exit 0（2 格 N/A：
  简单档无光伏）。
