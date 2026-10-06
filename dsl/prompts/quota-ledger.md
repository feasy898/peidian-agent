# 模型调用配额台账 · worker-A 线1（上限 3 次，与 worker-B 共享项目总额 ≤10）

> run_gen.py 每次发起真实调用自动追加一行；离线核验以本表为准。
> 2026-10-01：**0/3 已用** —— Higress(100.100.0.6:8080) 探测 `/v1/models`=404、无凭据请求 `/v1/chat/completions`=401，
> GPU 机无 bao CLI、env 无 LLM_API_KEY，本 worker 无取钥路径（红线：不翻找密钥）。
> 三档提示词已落盘并经"规范内嵌完整性"自检（prompts 内含元件表/ID 约定/档位判据/输出骨架），
> 真实模型验证**未执行**，如实挂起待凭据就绪后补验。

| 时间 | tier | model | 状态 | 备注 |
|---|---|---|---|---|
| 2026-10-06 15:17 | simple | qwen3-32b | CALL_FAIL | HTTP 400 from https://open.bigmodel.cn/api/coding/paas/v4 |
| 2026-10-06 15:18 | simple | glm-4-flash | OK | 979B out=/tmp/gen-park-simple.yaml |
