# skills/overload-response/SKILL.md · level2 全文（渐进披露第三级；加载才计费）

## 过载响应处置（skill.overload-response@0.1.0）

适用：变压器负载率越限（PHYS-TX-LOAD：>80%→P2 预警，>100%→P0 重过载）的研判与处置建议。

### 处置序列

1. **研判**：读目标变压器量测（P/capacity → load_rate），按 REG-TECH 判据口径分级；
   不用墙钟、不凭经验值。
2. **复核**：关联同母线设备与上游开关（三跳查询：设备→母线→同母线设备），
   给出影响面。
3. **处置建议**：
   - 可转移负荷建议（母线/变压器间）；
   - 需遥控分合闸时：先核对已签发操作票（SAFE-TWO-TICKET），步骤按票面顺序
     （SAFE-ORDER-SEQ），缺票一律拒绝并说明；
   - 审批走缺省 ASK 链路（SAFE-OP-REMOTE），不申请绕过（bypass.approval 永久 DENY）。
4. **闭环**：创建消缺工单（create.work_order，关联告警）；输出证据三态
   （intended/issued/observed），observed 必须来自环境回读。

### 证据要求（evidence_policy）

- 量测读数（含时标与质量标记）；
- 规程引用（规则 ID 列表：PHYS-TX-LOAD / SAFE-TWO-TICKET / SAFE-OP-REMOTE）；
- 处置动作的 ActionRequest 通道证据（无通道不认可状态变更）。
