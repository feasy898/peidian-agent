# dsl/ · ParkDSL 规则语言与生成引擎（worker-A 线1）

园区电力系统的**唯一描述语言**：一份 YAML 描述拓扑+参数 → 校验 → 导出为前端可渲染的 JSON。

```
dsl/
├── docs/dsl-spec.md      人读规范（定案理由/元件表/ID 约定/校验规则/遥测公式）
├── dsl_spec.yaml         机器可读规范 = validate.py 唯一裁决源
├── validate.py           CLI: validate / export / summary（Python 3.12 + pyyaml）
├── examples/             三档样例各 1 份（全部过校验）
├── prompts/              LLM 三档生成模板 + run_gen.py 运行器 + 配额台账
└── tests/run_tests.py    全量测试（正向 3 + 负向 8 + 导出 3 + tier 推断）
```

常用命令（仓库根，`. .venv/bin/activate`）：

```bash
python dsl/validate.py validate dsl/examples/park-simple-01.yaml   # 单文件校验
python dsl/validate.py export   dsl/examples/park-medium-01.yaml -o web/public/data/park-medium-01.json
python dsl/validate.py summary  dsl/examples/park-*.yaml           # 规模与 tier 推断
python dsl/tests/run_tests.py                                      # 全量测试，退出码为证
```

LLM 生成（配额 ≤3 次真实调用，自动记 `prompts/quota-ledger.md`；key 走 env/stdin 不进 argv）：

```bash
python dsl/prompts/run_gen.py --tier simple --brief "20 万平米研发园区..." \
  --out dsl/examples/generated.yaml --validate --api-key-stdin
```

与故障线（worker-B）的对齐点：**元件 ID**（`docs/dsl-spec.md` §5）与**事件格式**（`web/docs/fault-events.md`）。冲突提交 judge 裁决。
