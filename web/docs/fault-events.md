# FaultEvent 接口契约 v0.2（worker-A 线2 ⇄ worker-B 线3/线4 集成基准）

> **v0.2 变更**：按 judge 第 2 轮【接口裁决（即时生效）】升级——
> ①元件 ID 唯一权威源与 fault 侧 kind 映射表（§2）；②FaultEvent v0.1 为集成基准，本版只做**可选字段扩展**（§3）；
> ③前端时间线口径=同时消费 `agent.step`（looked_at/found/why）与 `action.executed`（by=agent|human）两类事件（§5）；
> ④新增 python↔node 桥握手契约（§4，供 worker-B 线4 交付 `fault/bridge.py` 对齐）。
> 状态：映射表按裁决记录；其中 CB/CP 两处与 ParkDSL 语义交叉，已登记待复裁（§2.1，不影响 schema）。

## 1. 注入请求（不变）

`POST /api/fault`  body:

```json
{ "park": "PARK-201", "text": "2 号变压器重瓦斯跳闸" }
```

- `park`：ParkDSL `park.id`，服务端按 `^PARK-[0-9]{3}$` 白名单校验后查表；
- `text`：自然语言故障描述（LLM/规则解析出 targets）。
- **白名单纪律（Mimosa advisory② 集成复核项）**：请求参数永不触达文件系统路径——
  桥命令只来自 env（操作面），事件流落盘路径只由服务端代码/测试显式给定；body 出现
  `path/file/out/dir` 等键直接 400。

## 2. 元件 ID 与 kind 映射（judge 裁决①）

- **唯一权威源 = ParkDSL 导出 JSON**（`web/public/data/*.json` 的 nodes/links，
  ID 正则见 `dsl/docs/dsl-spec.md` §5）。
- fault 侧 kind 映射表（裁决原文）：

| fault kind | ParkDSL 前缀/元素 |
|---|---|
| grid_infeed | GRID |
| line | LN（links kind:line） |
| transformer | TX |
| bus | BUS |
| switchgear | SG / CB |
| bess | BESS |
| pv | PV |
| evcharger | EVC |
| load | LD |
| capacitor | CP |

### 2.1 CB/CP 交叉：两侧实现已同向收敛，提请 judge 追认

ParkDSL 语义：`CB`=CapacitorBank（可投切电容器组，state "ON"/"OFF"）；`CP`=母线联络点
（coupler，环网常开）。按裁决表字面（switchgear↔SG/CB、capacitor↔CP）会把电容器组成
开关、把联络点成电容。worker-A 在本节初版提出按电气语义适配的建议；**worker-B 线4
park_adapter.py（提交 fe8c6ea）已按同一方向落地**：CP（coupler）→ 常开开关（switchgear，
normally:OPEN，转供所需联络点）、CapacitorBank → capacitor 叶元件，并附证据
（dsl/examples/park-complex-01.yaml:66）作"有声偏离"登记。两侧实现一致，FaultEvent schema
不受影响；**提请 judge 对该偏离追认**，追认后本节可并回 §2 正表。

## 3. FaultEvent v0.2（v0.1 基础上，全部为可选扩展字段）

```jsonc
{
  "event_id": "FLT-20261001-0003",
  "ts": "2026-10-01T12:30:00.000Z",
  "park_id": "PARK-201",
  "request_text": "2 号变压器重瓦斯跳闸",
  "type": "transformer.trip",          // v0.1 口径不变；桥模式可为 fault DSL 四类 SHORT_CIRCUIT/LINE_BREAK/TX_OVERLOAD/PV_TRIP
  "severity": "P0",
  "targets": ["TX-A02"],               // 引用 ParkDSL 元件 ID（权威源）
  "telemetry_effects": [ { "component": "TX-A02", "metric": "power", "multiplier": 0.0 } ],
  "agent": {
    "mode": "auto",
    "total_ms": 3600,
    "steps": [
      {
        "idx": 1, "title": "告警确认", "detail": "…", "refs": ["SG-A02"],
        "phase": "confirm",              // v0.2 可选：引擎 8 相 confirm/diagnose/judge/plan/isolate/restore/summary/verify
        "looked_at": ["TX-01"],          // v0.2 可选：看了什么（元件 ID 列表）
        "found": {"anomaly": "ANO-001"}, // v0.2 可选：判了什么（键值摘要）
        "why": "…",                      // v0.2 可选：为什么
        "conclusion": "…"                // v0.2 可选：本步结论
      }
    ]
  },
  "actions": [                           // v0.2 可选：ops 通道 action.executed 投影
    { "action_id": "ACT-001", "op": "open", "target": "SG-A02", "by": "agent",
      "result": "ok", "note": "SG-A02: CLOSED → OPEN", "reason": "隔离 …", "ts": "…" }
  ],
  "events": [                            // v0.2 可选：control/fault 通道关键标记投影
    { "type": "fault.detected", "severity": "P0", "target": "TX-A02" },
    { "type": "control.passed", "note": "agent 已关闭，交人工" },
    { "type": "anomaly.cleared", "by": "human" }
  ],
  "source": "mock"                       // mock | fault-engine | stub（联调桩）
}
```

- v0.1 消费方（只读 steps[].title/detail）完全不受影响；
- mock 兜底继续产出 v0.1 形态（无扩展字段），前端按字段存在性渐进渲染。

## 4. python↔node 桥握手（**v0.2.1 按实际交付 `fault/bridge.py` 修订**；server.js 已按此实现）

- **进程模型**：一请求一进程。server.js spawn 桥命令，stdin 一次性写入后关闭，收满 stdout。
- **命令解析**：env `FAULT_BRIDGE_CMD`（空格分词）可覆盖；缺省探测 `<repo>/fault/bridge.py`，
  解释器优先 `<repo>/.venv/bin/python`（缺则 env `FAULT_BRIDGE_PYTHON`/`python3`）。
- **stdin**（UTF-8 JSON）：
  `{"mode":"simulate", "park":<parkdsl-web/1 全量 JSON 原样>, "text":"<用户输入>", "agent_enabled":true, "horizon_s":6}`
- **stdout**：`{"ok":true, "fault_event":<FaultEvent 基线>, "events":[<EventBus 原始事件流>],
  "llm":{"used":bool,"reason":str}, "summary":{...}, "switches":{...}}`。
- **拒绝语义（零信任，不静默兜底）**：白名单/校验拒绝 → 桥 exit 3 +
  `{"ok":false,"rejected":true,"reasons":[...]}` → server.js 转 **HTTP 422** 透传 reasons（前端如实展示）。
  其余桥故障（spawn 失败/非 JSON/超时 20s）→ 才沿回退链 **bridge → FAULT_MODULE → mock**。
- **server.js 投影（judge 裁决③）**：把 `events[]` 中 `agent.step`（phase/looked_at/found/why/conclusion）
  合并进 `fault_event.agent.steps`，`action.executed|rejected` → `actions[]`，control/fault 标记 →
  `events[]`（§3），并置 `source:"fault-engine"`、`engine:{llm,summary}`。
- 离线兜底：无 `HIGRESS_API_KEY` 时桥内规则解析器接管（关键词：短路/接地/闪络/相间、断线/断相、
  过载/重载、光伏脱网/脱扣；目标建议用显式元件 ID）；LLM 凭据到位后同一入口自动走真实 LLM（线4 配额 ≤4）。

## 5. 前端时间线口径（judge 裁决③）

时间线同时消费两类事件（web/public/js/faults.js）：

1. **`agent.step`（时间线主体）**：有 `phase/looked_at/found/why` 时渲染为
   `[phase] title → 看：<looked_at>｜判：<found 摘要>｜据：<why>（→ conclusion）`；
   无扩展字段时回退 v0.1 的 title/detail。
2. **`action.executed`（操作审计 chips）**：`op target by result`——`by=agent` 绿、
   `by=human` 蓝，`result!=ok` 红；置于时间线尾部"操作面"分组。
3. **control/fault 标记**（events[]）：`control.passed`=「已交人工」横幅、
   `anomaly.cleared by=human`=「人工定位清除」徽标、`fault.detected`=检测时间戳。

人工模式（人机对比）行为不变：注入后隐藏 agent 时间线、拓扑点选判分走
`POST /api/human/attempt`（契约同 v0.1 §3）。

## 6. mock 解析口径（不变，web/faultstore.js）

显式 ID → targets；口语序号（"2 号变压器"）→ 类型内字典序第 N 台；关键词分类
type/severity（重瓦斯/差动→P0，短路/断线→P1，过载→P2…）；遥测效应：跳闸→功率归零、
母线故障→电压×0.6 且下游归零、电压类→×0.92。
