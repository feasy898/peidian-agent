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

### 2.1 如实登记：CB/CP 两处交叉待复裁

ParkDSL 语义：`CB`=CapacitorBank（可投切电容器组，state "ON"/"OFF"）；`CP`=母线联络点
（coupler，环网常开）。按裁决表字面（switchgear↔SG/CB、capacitor↔CP）会把电容器组成
开关、把联络点成电容。**适配落地建议按电气语义**：`CB→capacitor`（or switchgear 承载投切面）、
`CP→switchgear(normally:OPEN, operable:true)`——后者正是 worker-B 转供所需的联络开关
（fault/README.md §2"倒闸转供需要联络开关"）。桥实现方可两读；FaultEvent schema 不受影响；
**差异已提交 judge 复裁，未擅改裁决文本**。

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

## 4. python↔node 桥握手（worker-B 线4 交付 `fault/bridge.py`；server.js 已备客户端）

- **进程模型**：一请求一进程。server.js spawn 桥命令，写 stdin 后等 stdout 关闭。
- **命令解析**：env `FAULT_BRIDGE_CMD`（空格分词，如 `"python3.12 fault/bridge.py"`）；
  未设 env 时 server 探测默认路径 `<repo>/fault/bridge.py` + 解释器
  `<repo>/.venv/bin/python`（缺则 `python3`）；文件不存在 → 跳过桥。
- **stdin**（UTF-8 JSON，一次性写入后关 stdin）：
  `{"park": <parkdsl-web/1 全量 JSON 原样>, "text": "<用户输入>"}`
- **stdout**：单个 FaultEvent v0.2 JSON（§3）。stderr=日志（服务端不解析）。
- **退出码**：0=成功且 stdout 可解析；非 0 / JSON 解析失败 / 缺 `event_id` 或 `agent` /
  超 20s → 服务端记日志并沿回退链降级：**bridge → FAULT_MODULE → mock**，页面不瘫。
- **超时**：20s（env `FAULT_BRIDGE_TIMEOUT_MS` 可调）。
- 桥内职责（worker-B）：按 §2 映射把 parkJson 经 `Topology.from_dict` 装载（adapter 在桥侧，
  worker-A 导出格式零改动）、`nl_to_fault`/规则兜底解析 text、`engine.run` 推演、
  抽取 steps/actions/events 组装 FaultEvent（`source:"fault-engine"`）。

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
