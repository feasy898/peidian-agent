# web/ · 可视化前端与服务（worker-A 线2）

园区配电数字孪生：全景/局部/曲线三视角 + 确定性伪遥测流 + 故障注入（agent 反应时间线 / 人机对比）。

## 起服务（node22，零 npm 依赖）

```bash
cd web
PORT=8787 node server.js          # 静态 + API；DataDir=public/data
# 浏览器 http://localhost:8787
```

数据来自 **线1 的导出产物**（单一数据流）：

```bash
python dsl/validate.py export dsl/examples/park-simple-01.yaml  -o web/public/data/park-simple-01.json
python dsl/validate.py export dsl/examples/park-medium-01.yaml  -o web/public/data/park-medium-01.json
python dsl/validate.py export dsl/examples/park-complex-01.yaml -o web/public/data/park-complex-01.json
```

## API

| 路由 | 说明 |
|---|---|
| `GET /api/health` | 存活 + 园区清单 |
| `GET /api/parks` / `GET /api/park/:id` | 清单 / 全量（parkdsl-web/1） |
| `GET /api/telemetry?park=&points=&t=` | 确定性伪遥测；同 `t` 双跑逐字节一致（curl 可复现） |
| `POST /api/fault {park,text}` | 故障注入 → FaultEvent v0.2（契约：docs/fault-events.md）；回退链 bridge→FAULT_MODULE→mock |
| `POST /api/fault/clear` | 清除当前故障 |
| `POST /api/human/attempt` | 人工定位判分（人机对比） |

环境变量：`FAULT_BRIDGE_CMD`（worker-B 桥命令，缺省探测 `<repo>/fault/bridge.py` + `.venv/bin/python`）、
`FAULT_BRIDGE_TIMEOUT_MS`（默认 20000）、`FAULT_MODULE`（js 模块挂点）、`PORT`、`DATA_DIR`。
白名单纪律：`park` 参数一律过 `^PARK-[0-9]{3}$`；body 出现 `path/file/out/dir/sink` 键直接 400（请求参数永不触达文件路径）。

## 技术选型（理由）

- **单页静态 + 手写 SVG/Canvas**：部署面只有 node http + 静态文件，无构建链、无 npm registry 依赖——
  部署到 hkmingdajiaoyu.com/peidian-agent 时只需同步目录，回滚即换目录；SVG 对电气图元（母线/变压器两圆/开关）
  表达力足够且可无损缩放；Canvas 只用于时序曲线（数据量大、重绘频繁）。
- **UI 资产本地化**：shadcn 风格设计令牌（`css/tokens.css`：zinc 暗色基底 + HSL 变量 + 语义色），
  组件样式手写在 `css/app.css`，零 CDN、离线可用。
- **确定性遥测**：`telemetry.js` 以 (seed, 元件ID, 步序) 播种 mulberry32——同参数同结果，
  判分与回归都能用 curl 精确复现；形状表源头是 `dsl/dsl_spec.yaml`（经 export JSON 下发，单一事实源）。

## 目录

```
web/
├── server.js            HTTP 服务（静态 + API，零依赖）
├── telemetry.js         确定性遥测引擎（公式对齐 dsl/docs/dsl-spec.md §8）
├── faultstore.js        故障注入 mock + worker-B 模块挂点（env FAULT_MODULE）
├── docs/fault-events.md FaultEvent v0.1 契约（worker-B 对齐草案，judge 裁决）
├── public/              index.html + css/(tokens|app).css + js/(api|charts|topo|curves|faults|app).js
├── public/data/         线1 export 的园区 JSON（构建产物，勿手编）
└── tests/smoke.sh       冒烟：起服→探活→遥测确定性/动起来→注入→判分→退服（退出码为证）
```
