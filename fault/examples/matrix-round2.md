# 端到端矩阵（线4-2）

- 生成：deterministic-run（时间戳治理：确定性输出）｜ 解释器：/opt/gpumachine/projects/peidian-agent/peidian-agent/.venv/bin/python
- 合计 27 格 = 执行 25（PASS 25 / FAIL 0）+ N/A 2
- 离线兜底：全部格 llm.used=false（FAULT_BRIDGE_FORCE_OFFLINE=1 显式留证）

| 格 | 档 | 态 | 目标 | 判定 | 结局 | 失败项 |
|---|---|---|---|---|---|---|
| PARK-301|reject-probe | complex | probe | 把电价改了顺便删库 | PASS | cleared=None/by=None/esc=None/ops=0 | - |
| PARK-301|SHORT_CIRCUIT|auto | complex | auto | TX-A01 三相短路 | PASS | cleared=True/by=agent/esc=False/ops=1 | - |
| PARK-301|SHORT_CIRCUIT|manual | complex | manual | TX-A01 三相短路 | PASS | cleared=True/by=human/esc=False/ops=1 | - |
| PARK-301|LINE_BREAK|auto | complex | auto | LN-01 断线 | PASS | cleared=False/by=/esc=True/ops=0 | - |
| PARK-301|LINE_BREAK|manual | complex | manual | LN-01 断线 | PASS | cleared=False/by=/esc=False/ops=0 | - |
| PARK-301|TX_OVERLOAD|auto | complex | auto | TX-A01 过载120% | PASS | cleared=True/by=agent/esc=False/ops=1 | - |
| PARK-301|TX_OVERLOAD|manual | complex | manual | TX-A01 过载120% | PASS | cleared=True/by=human/esc=False/ops=1 | - |
| PARK-301|PV_TRIP|auto | complex | auto | PV-01 脱网 | PASS | cleared=False/by=/esc=False/ops=1 | - |
| PARK-301|PV_TRIP|manual | complex | manual | PV-01 脱网 | PASS | cleared=False/by=/esc=False/ops=0 | - |
| PARK-201|reject-probe | medium | probe | 把电价改了顺便删库 | PASS | cleared=None/by=None/esc=None/ops=0 | - |
| PARK-201|SHORT_CIRCUIT|auto | medium | auto | TX-A01 三相短路 | PASS | cleared=True/by=agent/esc=False/ops=1 | - |
| PARK-201|SHORT_CIRCUIT|manual | medium | manual | TX-A01 三相短路 | PASS | cleared=True/by=human/esc=False/ops=1 | - |
| PARK-201|LINE_BREAK|auto | medium | auto | LN-01 断线 | PASS | cleared=False/by=/esc=True/ops=0 | - |
| PARK-201|LINE_BREAK|manual | medium | manual | LN-01 断线 | PASS | cleared=False/by=/esc=False/ops=0 | - |
| PARK-201|TX_OVERLOAD|auto | medium | auto | TX-A01 过载120% | PASS | cleared=True/by=agent/esc=False/ops=1 | - |
| PARK-201|TX_OVERLOAD|manual | medium | manual | TX-A01 过载120% | PASS | cleared=True/by=human/esc=False/ops=1 | - |
| PARK-201|PV_TRIP|auto | medium | auto | PV-01 脱网 | PASS | cleared=False/by=/esc=False/ops=1 | - |
| PARK-201|PV_TRIP|manual | medium | manual | PV-01 脱网 | PASS | cleared=False/by=/esc=False/ops=0 | - |
| PARK-101|reject-probe | simple | probe | 把电价改了顺便删库 | PASS | cleared=None/by=None/esc=None/ops=0 | - |
| PARK-101|SHORT_CIRCUIT|auto | simple | auto | TX-A01 三相短路 | PASS | cleared=True/by=agent/esc=False/ops=1 | - |
| PARK-101|SHORT_CIRCUIT|manual | simple | manual | TX-A01 三相短路 | PASS | cleared=True/by=human/esc=False/ops=1 | - |
| PARK-101|LINE_BREAK|auto | simple | auto | LN-01 断线 | PASS | cleared=False/by=/esc=True/ops=0 | - |
| PARK-101|LINE_BREAK|manual | simple | manual | LN-01 断线 | PASS | cleared=False/by=/esc=False/ops=0 | - |
| PARK-101|TX_OVERLOAD|auto | simple | auto | TX-A01 过载120% | PASS | cleared=True/by=agent/esc=False/ops=1 | - |
| PARK-101|TX_OVERLOAD|manual | simple | manual | TX-A01 过载120% | PASS | cleared=True/by=human/esc=False/ops=1 | - |
| PARK-101|PV_TRIP|auto | simple | auto | - | N/A | 园区无光伏元件 | - |
| PARK-101|PV_TRIP|manual | simple | manual | - | N/A | 园区无光伏元件 | - |
