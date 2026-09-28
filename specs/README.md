# 园区配电运维智能体 · 开发包 README（索引与开发顺序）

> 交付定位：一个开发 agent 拿到本目录即可完整开发。不含论证性内容；全部是"怎么干+验收标准"。
> 阅读 10 分钟后可开工：先读本文件 → 01 冻结契约 → 按顺序做模块。

## 0. 交付物清单

| 文件 | 内容 | 性质 |
| --- | --- | --- |
| `00-ontology.md` | 本体四要素+受控词表+PARK-001 种子实例+Holdout 变体声明 | 语义权威源 |
| `01-contracts.md` | 模块划分+冻结契约（11 数据结构+API+事件+3 状态机+Eval 重生成协议） | 接口权威源 |
| `M1-agent-core.md` | 执行内核 spec+eval | 开发规格 |
| `M2-information.md` | 信息层 spec+eval | 开发规格 |
| `M3-action-gateway.md` | 行动层 spec+eval | 开发规格 |
| `M4-semantic-ontology.md` | 语义层 spec+eval | 开发规格 |
| `M5-simulation.md` | 仿真层 spec+eval+3 个开发场景种子 | 开发规格 |
| `M6-flywheel.md` | 飞轮 spec+eval+12 条黄金集种子 | 开发规格 |
| `M7-registry-release.md` | 资产层 spec+eval | 开发规格 |
| `HOLDOUT.md` | 15 场景独立验收测试 | **验收专用，开发期禁用**（随验收包交付、由验收人独立保管，**不进开发仓库**——ADDENDUM §F 红线：仓库任何路径不得出现 holdout 场景/实例/判据文件，`scripts/ci_isolation.py` 断言零命中） |

## 1. 系统一页图

```text
            ┌────────────────────────────────────────────┐
            │  M1 Agent Core（Loop/状态机/门禁/完成验证）   │
            └──────┬──────────┬──────────┬───────────────┘
        compile_ctx│      execute│action   │resolve/entities
            ┌──────▼──┐  ┌────▼─────────┐  ┌▼─────────────┐
            │ M2 信息层 │  │ M3 行动网关   │  │ M4 语义层      │
            │(Context/ │  │(Policy 三值/  │  │(本体/规程/    │
            │ State/   │  │ HITL/幂等)   │  │ 实体/三跳)    │
            │Artifact) │  └────┬─────────┘  └──────────────┘
            └──────┬──┘       │ simulate
                   │     ┌────▼─────────┐
                   │     │ M5 仿真层     │←── golden/dev + HOLDOUT 场景
                   │     │(环境/用户/    │
                   │     │ 场景/四时钟)  │
                   │     └──────────────┘
            ┌──────▼──────────────────────────┐
            │ M6 飞轮（轨迹/黄金集/Badcase/Skill 化）│
            └──────┬──────────────────────────┘
            ┌──────▼──────────────────────────┐
            │ M7 资产层（注册/版本/评审/Release）   │
            └─────────────────────────────────┘
   ontology/ regulations/（M4 读）  assets/（M7 管）  golden/dev│holdout  releases/  runs/
```

## 2. 开发顺序（依赖驱动）

1. **M4 → M5**（语义与仿真是验收地基）：M4 先（本体可加载/可解析/可三跳）；M5 次之（环境+时钟+场景引擎；persona 脚本模式先行，LLM 模式后补）。
2. **M2 → M3 → M1**（信息→行动→内核）：M2（Context/状态/Artifact）；M3（注册/校验/Policy/幂等+负向测试件）；M1（Loop 把三者串起来）。
3. **M6 → M7**（飞轮与资产收口）：黄金集种子 12 条+判据引擎；Release 打包+发布门禁。
4. 每模块 DoD 达成后才进入下一个；全程 CI 跑 `tests/test_m*.yaml` 回归。

## 3. 全局验收流程（开发 agent 完成后）

1. 全模块 EVAL 绿（含负向）。
2. 组装首个 ReleaseBundle（AgentContract 资产 + 六要素绑定），走 M7 门禁：12 条黄金种子全过+红线断言全过。
3. **移交验收**：验收人按 `HOLDOUT.md` §4 执行（hash 核对→隔离检查→15 场景跑分→§3 门槛判定→归档）。
4. 开发侧在移交前最后一次确认：`golden/dev/` 无 PARK-002/TARIFF-2026B/OP-1xx 字样（grep 零命中）。

## 4. 工程约定速查

- 语言栈：Python 3.11+；SQLite 单文件起步；YAML 数据驱动（tests/ontology/golden/scenarios 全部文件化）。
- LLM 抽象：`m1_core/model_client`（provider 适配，mock 模式可全离线跑 EVAL）。
- 目录树：见 01§1；契约代码化：`src/contracts/`（pydantic 或等价 schema 库）。
- 时间纪律：电价判定只允许 M5 BUSINESS 时钟；CI 扫描业务代码无 wall-clock 判价。
- 规程引用：一切规程引用=规则 ID（`regulations/*.yaml`），报告 schema 强制校验。
- Eval 重生成：spec 变更→eval 重生成→`tests/CHANGELOG.md` 登记 hash 对；不一致=验收失败（协议见 01§6）。
- 契约变更：唯一通道=01§7 评审流程；跳过=CI 拒绝。

## 5. 红线速查（违反任意一条即验收失败）

1. 未注册能力执行（UNREGISTERED 漏网）。
2. 任何角色执行 modify.protection_setting。
3. 无操作票的 execute.remote_control。
4. bypass.approval 生效。
5. 绕过 ActionRequest 通道的任务状态变更（含 TaskState/Artifact/环境）。
6. 用墙钟判定峰谷电价。
7. 模型申请完成而证据不足被放行（NEED_MORE_EVIDENCE 缺失）。
8. holdout 数据进入开发/调优集。
