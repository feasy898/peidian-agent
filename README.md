# peidian-agent —— 园区配电运维智能体

> 接手文档 ｜ 任务卡见 [TASK.md](TASK.md)（**owner 已裁定目标转向，以 TASK.md 为准**）｜ 项目原始自述见 [README-upstream.md](README-upstream.md)

## 项目是什么

面向 10kV/0.4kV 园区配电（含储能/光伏/充电桩）的运维 agent 系统。工程主线：「受控行动网关（Policy 三值 + HITL 审批）+ 两票制红线 + 仿真驱动 EVAL + 黄金集飞轮」。已完成 M0–M9 模块族、ParkDSL 园区规则语言、数字孪生前端（web/）、故障注入引擎（fault/）与部署包（deploy/）。

**安全设计核心**：危险动作（遥控/操作票）必须过受控网关；创建操作票 ≠ 执行遥控；两票制签发权永远在人（HITL 不可委派）；最终验收用与开发隔离的 holdout 独立实例。

## 架构一句话

ParkDSL 描述园区拓扑与规程 → 仿真环境（伪遥测/故障注入）→ agent 走「confirm/diagnose/judge/plan/isolate/restore/summary/verify」八相反应流，每个动作过 Policy 三值网关（allow/deny/需人工），全链留事件流证据。

## 构建与运行

- 环境：**Python 3.12 必须**（3.11 编译 `context_builder.py` 报语法错；pyproject 里 `>=3.11` 的声明待修正为 `>=3.12`，见已知问题）。
- 依赖安装：以 `pyproject.toml` 为准（`pip install -e .` 或按 README-upstream）。
- 评测门禁：`python run_evals.py --module all`
- 隔离扫描：`python scripts/ci_isolation.py`
- ParkDSL 套件：`python dsl/tests/run_tests.py`
- 故障注入套件：`fault/run_tests.py`（或 `python -m ...`，见 fault/README）
- 端到端演示：`python demo/run_demo.py --flow all`

## 验收基线（2026-10-01 迁移后实测）

| 门 | 命令 | 基线 |
|---|---|---|
| G0-1 评测门禁 | `python run_evals.py --module all` | **233/233 PASS, exit 0（约 1 分钟）** |
| G0-2 隔离扫描 | `python scripts/ci_isolation.py` | **ISOLATION OK: zero hits**（仓内 grep holdout 关键词零命中） |
| G0-3 ParkDSL | `python dsl/tests/run_tests.py` | **25/25 PASS**（含 v1.1 练习场三节 10 个新用例） |
| G0-4 故障注入 | fault 套件 | **13/13 PASS**（含四类故障端到端） |
| G0-5 演示流 | `python demo/run_demo.py --flow all` | 全判据通过（pass_rate=1.0） |

## 已知问题

1. **目标转向（2026-10-01 owner 裁定）**：在接入真实系统之前，先建「用户侧园区电力经营管理」理论认识 → 冻结 agent 行为契约 → 划分模块 → 构建模拟练习场（数万次模拟收敛最佳行为逻辑）。既有 M0–M9/ParkDSL/门禁体系作为工程底盘保留，复用/改造/废弃三态判定见 TASK.md。
2. **pyproject 声明与实际不符**：`>=3.11` 应为 `>=3.12`（3.11 下 6 个用例 SyntaxError），待修。
3. **holdout 纪律**：holdout 独立验收实例不在本仓库内（物理隔离）；`scripts/ci_isolation.py` 是防泄漏门，任何改动后必须保持 zero hits。
4. **LLM 注入桥**：`fault/llm_bridge.py` 支持 Higress 式网关注入（key 走环境变量，fail-closed 离线兜底）；无凭据时全链离线可跑（FakeLLM 脚本化验证），真实模型调用为 0 是当前实测态。
