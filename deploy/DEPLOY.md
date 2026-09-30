# 部署手册 · hkmingdajiaoyu.com/peidian-agent（worker-B · 线4-4）

> 状态：**部署包就绪，未执行线上部署**——GPU 机与 windev-01 均无 srv-1 通道
> （`ssh srv-1` 两端 DNS 均不可解析，2026-10-01 实测；无凭据不翻找，红线1）。
> 本手册按 owner 纪律编写：caddy 变更走**只读核对 → 最小 diff → reload 前 cp 备份**。
> 执行人：任何持 srv-1 通道的运维/owner；预计 10 分钟。

## 0. 包内容

```
deploy/
├── DEPLOY.md                    本手册
├── peidian-agent.service        systemd 单元（node server.js 常驻）
├── caddy-peidian-agent.conf     caddy 站点最小 diff 片段（只贴增量，见 §3）
└── pack.sh                      从 git 仓打发布 tar（git archive，不含 .venv/node_modules）
```

## 1. 架构

```
浏览器 ──https──> caddy(srv-1, hkmingdajiaoyu.com)
                    └─ /peidian-agent/* ──(strip 前缀)──> 127.0.0.1:8787  node web/server.js
                                                              ├─ 静态: web/public/
                                                              ├─ API:  /api/*
                                                              └─ FAULT_MODULE=fault/web_module.js
                                                                    └─ spawn .venv/bin/python fault/bridge.py
                                                                         └─ Higress(100.100.0.6:8080, key 经 bao 注入 env)
```

## 2. 上线步骤（srv-1）

1. **传输**：GPU 机 `bash deploy/pack.sh`（产物 `peidian-agent-release-<sha>.tar.gz`）→
   scp 到 srv-1 `/opt/peidian-agent/`。
2. **解包**：`tar xzf peidian-agent-release-*.tar.gz -C /opt/peidian-agent --strip-components=1`。
3. **运行时**：srv-1 需 node ≥18 与 python3.12+pyyaml。若缺：
   `dnf install nodejs python3.12 && python3.12 -m pip install pyyaml -i https://mirrors.aliyun.com/pypi/simple/`，
   并在仓库根建 venv：`python3.12 -m venv .venv`（web_module.js 默认用 `<repo>/.venv/bin/python`，
   可用 `PYTHON_BIN` 环境变量覆盖；**勿指向 3.11**——judge 第 2 轮已证 3.11 假红）。
4. **自测（不上流量）**：
   `PORT=8787 FAULT_MODULE=/opt/peidian-agent/fault/web_module.js node web/server.js`
   → `curl -s localhost:8787/api/health`（应 3 parks）→
   `curl -s -X POST localhost:8787/api/fault -d '{"park":"PARK-201","text":"TX-A01 三相短路"}'`
   （应 source=agent、targets=[TX-A01]、agent.steps≥3）。
5. **systemd**：`cp deploy/peidian-agent.service /etc/systemd/system/ &&
   systemctl daemon-reload && systemctl enable --now peidian-agent`。
6. **caddy**（§3 最小 diff）：备份 → 追加 → 核对 → reload。
7. **验收**：`curl -s https://hkmingdajiaoyu.com/peidian-agent/api/health` 200；
   浏览器开 `https://hkmingdajiaoyu.com/peidian-agent/` 走一遍：切园区/注故障/
   步骤时间线/人机对比开关。回滚：`systemctl stop peidian-agent` + caddy 还原备份。

## 3. caddy 最小 diff（先只读核对！）

```bash
# ① 只读核对现状（不改任何东西）
ssh srv-1 'caddy version; ps aux | grep [c]addy; caddy environ | head -3'
ssh srv-1 'cat /etc/caddy/Caddyfile'          # 或实际配置路径（systemctl cat caddy 可见）
# ② 备份（reload 前必做，owner 纪律）
ssh srv-1 'cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date +%Y%m%d-%H%M%S)'
# ③ 追加增量（见 deploy/caddy-peidian-agent.conf，仅新增 site 块，不动既有行）
# ④ 核对 + reload
ssh srv-1 'caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy'
```

## 4. ⚠️ 上线前唯一代码改动项（worker-A，2 分钟）

前端 `web/public/js/api.js` 的 API 路径是**绝对路径**（`/api/parks` 等 6 处）。
挂在 `/peidian-agent/` 前缀下时浏览器会请求到主站根的 `/api/*` → 404。
二选一：
- **B（推荐）**：api.js 六处 URL 去掉前导 `/` 改相对（`api/parks`、`api/park/`、
  `api/telemetry?…`、`api/fault`、`api/fault/clear`、`api/human/attempt`）——
  静态资源（`css/`、`js/`）已是相对路径无需动；worker-A 顺带回归 web/tests/smoke.sh。
- **A（零改动临时）**：caddy 里同时把 `/api/*` 指到 8787（片段中已注释标出）。
  缺点：占用主站全局 `/api` 命名空间，仅当主站确认无同名路由时可用。

## 5. 密钥与配额

- Higress key：srv-1 经 bao 注入 systemd 单元 `EnvironmentFile=/etc/peidian-agent/env`
  （内容 `HIGRESS_API_KEY=…`，权限 600 root；**不入仓不入日志**）。
  未注入时桥自动离线兜底（规则解析，`llm.used=false`），页面不瘫——已实证
  （矩阵 25/25 在 FORCE_OFFLINE 下全过）。
- 模型配额：线4 端到端联调 ≤4 次真实调用，当前 **0/4**（凭据未到位）。

## 6. 已知边界（如实）

- 桥对故障文本限 1..500 字符、park.id 白名单 `^[A-Z0-9][A-Z0-9-]{0,31}$`
  （web_module.js 入口守卫；server.js 静态面自带 normalize+startsWith 防穿越）。
- 进线线路（LN-01 等）无上游断路器：断线类故障 agent 如实"升级人工"而非强操作——
  ParkDSL 生成园区若需自动隔离，建议进线加 Switchgear（交 worker-A/dsl 轮）。
- 矩阵与样例：`fault/examples/matrix-round2.{json,md}`（GPU 机实跑 25/25 PASS）。
