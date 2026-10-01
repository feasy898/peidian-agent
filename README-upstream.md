# peidian-agent · 园区配电运维智能体

面向园区配电运维（10kV/0.4kV 配电房、储能/光伏/充电桩）的智能体系统：受控行动网关（Policy 三值 + HITL 审批）、两票制安全红线、证据化完成验证、仿真驱动的 EVAL 与黄金集飞轮。

## 仓库结构

```text
specs/        开发包规格（README 索引、00 本体、01 冻结契约、M1–M7 模块 spec、ADDENDUM 补遗）
ontology/     本体 YAML（对象/关系/动作/规则/枚举/种子实例，运行期只读）
regulations/  虚拟规程（REG-SAFE / REG-COMM / REG-TECH / REG-OP）
src/          m1_core / m2_information / m3_action / m4_semantic /
              m5_simulation / m6_flywheel / m7_registry + contracts
scenarios/    开发用仿真场景（dev-*.yaml）
golden/dev/   开发黄金集（cases/*.yaml）
tests/        EVAL 用例（test_m*.yaml，数据驱动）+ CHANGELOG.md
releases/     ReleaseBundle（不可变发布）
```

## 开发顺序

M4 → M5 → M2 → M3 → M1 → M6 → M7（依赖驱动，详见 `specs/README.md` §2）。

## 验收（holdout）说明

最终验收使用独立的 HOLDOUT 测试集（15 场景 + PARK-002 独立实例），**不在本仓库内**，由验收人持有。开发期间禁止以任何形式使用 holdout 数据做调优、修 bug、扩充黄金集；CI 断言仓库内 grep `PARK-002|TARIFF-2026B|OP-1x` 零命中。

## 工程约定

- Python 3.11+；SQLite 单文件起步；YAML 数据驱动（tests/ontology/golden/scenarios 全部文件化）。
- LLM 调用统一走 `src/m1_core/model_client`（provider 适配，mock 模式全离线跑 EVAL）。
- 时间纪律：电价判定只允许 M5 BUSINESS 时钟；CI 扫描业务代码无 wall-clock 判价。

## EVAL 运行方式

```bash
python run_evals.py --module m4     # 在仓库根（本目录）运行；--selftest / --module all 同
```

runner 以脚本自身位置锚定仓库根（pathlib，不假设其他 cwd）；摘要行输出 stdout（ASCII），
明细写 `runtime/eval_results.json`（仓库内）。若在仓库的上级目录执行同名命令，
由该目录下的转发启动器委托本仓库 runner（单一事实源在本仓库，上级目录仅转发）。
