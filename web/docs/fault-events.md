# FaultEvent 接口契约 v0.1（worker-A 线2 ⇄ worker-B 线3 对齐草案）

> 状态：**草案待 judge 裁决**。worker-A 前端与服务端已按本契约实现并以 mock 兜底；
> worker-B 线3（故障与 agent 反应）就绪后按"接入方式"替换 mock 即可，前端零改动。
> 元件 ID 的**唯一权威源** = ParkDSL 导出 JSON（`dsl/docs/dsl-spec.md` §5 的 ID 约定）。

## 1. 注入请求

`POST /api/fault`  body:

```json
{ "park": "PARK-201", "text": "2 号变压器重瓦斯跳闸" }
```

- `park`：ParkDSL `park.id`；
- `text`：自然语言故障描述（LLM/规则解析出 targets）。

## 2. FaultEvent 响应（JSON）

```json
{
  "event_id": "FLT-20261001-0003",
  "ts": "2026-10-01T12:30:00.000Z",
  "park_id": "PARK-201",
  "request_text": "2 号变压器重瓦斯跳闸",
  "type": "transformer.trip",          // transformer.trip|fire|bus.deenergized|bus.fault|line.fault|breaker.trip|overload|comm.loss|voltage.sag|generic.alarm
  "severity": "P0",                    // P0|P1|P2|P3（对齐仓内 AlarmLevel 语义）
  "targets": ["TX-A02"],               // 引用 ParkDSL 元件 ID（权威源）
  "telemetry_effects": [               // 遥测乘子（服务端叠加在确定性遥测上）
    { "component": "TX-A02", "metric": "power", "multiplier": 0.0 }
  ],
  "agent": {                           // worker-B 线3 的核心产出；mock 为演示管线
    "mode": "auto",
    "total_ms": 3600,                  // 端到端处置耗时（演示计时口径）
    "steps": [
      { "idx": 1, "title": "告警接入与确认", "detail": "…", "refs": ["SG-A02"] }
      // refs[] 引用元件 ID / 规程条目
    ]
  },
  "source": "mock"                     // mock | agent（worker-B 接入后置 "agent" 并可加 module 字段）
}
```

## 3. 人机对比（可关闭 agent）

- 模式切换在前端（Agent 自动 ⇄ 人工定位）；人工模式下 `agent` 字段不渲染。
- 判分：`POST /api/human/attempt` body `{ "park", "targets": ["TX-A02"], "started_at": <ms> }`
  → `{ "verdict": "CORRECT|PARTIAL|WRONG", "hits", "precision", "recall", "elapsed_ms", "truth" }`。

## 4. worker-B 接入方式（不改前端）

- 服务端挂点：`web/server.js` 启动时读 env `FAULT_MODULE=/abs/path/module.js`，
  要求模块导出 `inject(parkJson, text) -> FaultEvent`（同 §2 schema，含 `telemetry_effects`）。
  模块异常自动回退 mock（日志留痕），前端不感知。
- 若 worker-B 另起独立服务，则保持 `/api/fault` 响应 schema 不变，改由反代/环境变量指向即可。

## 5. mock 解析口径（当前实现，web/faultstore.js）

1. 文本含显式元件 ID（如 `LN-03`）→ 直接取为 targets；
2. 口语序号（"2 号变压器"）→ 该类型元件按 ID 字典序取第 2 台；
3. 关键词分类定 type/severity（重瓦斯/差动→P0；短路/断线→P1；过载→P2…）；
4. 遥测效应：跳闸→目标功率归零；母线故障→电压×0.6 且下游功率归零；电压类→×0.92。
