# ui/ · 人类体验模式前端（全新重做 · 零构建链）

> owner 裁定：原有 web/ 前端「太丑，完全推翻重新做」。本目录是**独立全新工程**，
> 与旧 `web/`（数字孪生 demo）无任何共用代码；旧 web/ 停止演进、仅服务存量 demo。

## 运行

```bash
python arena/serve.py --port 8790        # API + SSE + 本前端静态服务
# 浏览器打开 http://127.0.0.1:8790
```

## 功能（对应愿景「开放给人类体验」）

| 区 | 能力 |
|---|---|
| 左·选择场景 | 场景库（arena/scenarios）/ 园区样例（dsl/examples）切换、seed、**agent 接管开关**（关闭=人类挑战模式） |
| 左·故障注入 | 场景绑定的故障一键注入（confirm 二次确认，危险操作全程留痕） |
| 左·人工操作台 | open/close/ack + 目标 + 原因——与 agent **同款执行器**，非法操作被拒并留痕 |
| 中·事件时间线 | SSE 实时事件流（control/fault/agent/ops 分色过滤），最多 400 条滚动 |
| 中·统计条 | 检出/闭环/升级/人工动作/agent 步骤/营业事件实时计数 |
| 右·agent 开关 | 运行中随时切换 agent 在线/人工接管（control 事件落流） |
| 右·活动异常 | 异常卡（hint@target + 判据证据）+ 一键 ack 派工 |
| 右·run 记录 | eval 摘要（检出/闭环/升级/时延） |

## 技术口径

- 纯静态三件套（index.html / app.css / app.js），无 npm、无构建链（与旧 web/ 一致的
  零依赖哲学，但视觉与信息架构完全重做：深色调度舱、等宽数字、分色时间线）。
- 唯一数据源是 `arena/serve.py`（HTTP+SSE 消费 fault EventBus）；前端不直接读仓库文件。
- 安全边界：serve 只读仓库内文件、只写 `runs/`；无真实系统接口（契约 §4）。

## 待办（后续迭代）

- 遥测面板（P/Q/V/I 实时曲线，消费 telemetry 通道快照）；
- 人机对比评分卡（人类 vs agent 检测时延并列，rubric 化）；
- 园区单线图（ParkDSL 拓扑 SVG 渲染，替代纯文字时间线）。
