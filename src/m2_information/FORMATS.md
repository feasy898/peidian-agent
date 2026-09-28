# M2 · Workspace / Artifact / 状态存储格式（FORMATS.md）

> specs/M2-information.md §6 交付物：workspace/artifact 存储格式文档（本文件）。
> 全部文件为 UTF-8；时间戳一律 UTC ISO-8601（`2026-09-28T08:00:00Z`）。

## 1. 运行期布局（InformationLayer root，缺省 `runtime/`）

```text
<root>/
├── state.db                     # SQLite（见 §4）
├── events/                      # 追加写事件流（01§4 唯一权威流）
│   ├── task-<task_id>.jsonl     #   任务全生命周期事件分片（task.*/action.*/artifact.*/budget.*）
│   └── audit-knowledge.jsonl    #   Knowledge 只读拒绝等审计事件
├── workspaces/
│   └── <task_id 净化>/
│       ├── inputs/  scratch/  state/  artifacts/  evidence/  manifest/   # 六目录（SPEC-M2-07）
│       └── .workspace.json      # {"task_id": 原始 id, "dirs": [六目录]}
└── skills_fulltext/             # 可选：SkillDescriptor.disclosure.level2_ref 指向的全文文件根
```

- task_id 目录名净化规则：`[^A-Za-z0-9._-]` → `_`（原始 id 存 `.workspace.json`）；
- 事件分片名同样净化；每行一个 EventRecord JSON（contracts 校验，缺 trace_id 写入即拒）。

## 2. Workspace 六目录内容

| 目录 | 内容 | 写入方 |
| --- | --- | --- |
| `inputs/` | 任务原始输入快照（用户指令、环境注入） | M1/M2 |
| `scratch/` | 中间草稿（跨任务**不可**引用） | 任务自身 |
| `state/` | Compact 五要素与压缩记录、Checkpoint（见 §3） | compactor/snapshot |
| `artifacts/` | 产物内容文件（跨任务仅 READY/PUBLISHED 只读） | artifact 管理器 |
| `evidence/` | 三态证据与只读读数快照（跨任务只读；内容门禁见 §3.3） | save_evidence |
| `manifest/` | 每轮编译记录 `turn-<n>.json`（见 §3.4） | context_builder |

路径纪律：相对路径、禁止 `..`/绝对路径/盘符；顶层必须落六目录之一。

## 3. 关键文件格式

### 3.1 Compact 五要素（`state/compact-<turn>.yaml`，compactor.commit 产物）

```yaml
task_id: task-xxx
turn: 50
committed_at: 2026-09-28T08:00:00Z
goal: 生成日巡检报告           # task.created.payload.user_input
confirmed_facts:              # action.completed(status=SUCCEEDED) 的 capability→observation
  - "query.measurement@v1 → 读数正常"
external_side_effects:        # result_refs + 已就绪产物
  - {kind: artifact, artifact_id: art-xxx, status: PUBLISHED}
acceptance_gaps:              # plan.artifacts_expected 未产出 ∪ 未完成 todos
  - "预期产物未产出: report.daily@v1"
recovery_position:            # 恢复锚点
  {stage: report, turn: 50, version: 12, status: RUNNING, next_hint: todo-2}
```

空要素以中文占位句落盘（要素"在场"与"取值为空"是两回事，Validate 只认在场性）。

### 3.2 压缩记录（`state/compacted-<turn>.yaml`，Compact 成功产物）

```yaml
task_id: task-xxx
turn: 50
trace_id: trace-xxx
elements: {goal: …, confirmed_facts: …, external_side_effects: …,
           acceptance_gaps: …, recovery_position: …}
context_text: |               # Rebuild 产物：五要素分节文本（进入 COMPACTED_HISTORY 源）
  【压缩历史】
  [目标｜goal] …
tokens: 369                   # estimate_tokens(context_text)
```

context_builder 收集源时取 `turn ≤ 当前轮` 的最大 turn 记录；存在压缩记录时
RECENT_INTERACTION 收缩为压缩点之后的增量（`[turn=N]` 行过滤）。

### 3.3 evidence/ 文件（`evidence/<name>.json`）

只接受两种封装（SPEC-M2-09，其余拒绝 `EvidenceRejectedError`）：

```json
{"kind": "action_evidence", "action_id": "act-901",
 "evidence": {"intended": {...}, "issued": {...}, "observed": {...}}}
```

```json
{"kind": "measurement_snapshot",
 "points": [{"device_ref": "TX-01", "quantity": "winding_temp", "value": 74,
             "unit": "C", "ts": "2026-09-28T08:00:00Z"}]}
```

### 3.4 编译记录（`manifest/turn-<n>.json`）

```json
{"manifest": {…ContextManifest 契约 dict…},
 "blocks": [{"layer": "system|task|extra", "type": "…", "name": "…", "text": "…", "tokens": 0}],
 "trim_log": [{"action": "dropped|compressed|refused", "name": "…", "type": "…",
                "tokens_before": 1500, "tokens_after": 0}],
 "filter_log": [{"name": "…", "type": "…", "reason": "权限不满足（requires 不匹配）"}],
 "conflicts": [{"key": "approval_channel", "kept": "strict", "dropped": "loose", "loser": "…"}],
 "directives": {"approval_channel": "strict"}}
```

被裁源在 Manifest 内以 `tokens: 0` 留档，`origin` 追加注记 `;trimmed=dropped@priority=<P>`
（压缩为 `;trimmed=superseded_by_compact@turn=<N>`）——ContextManifest 契约字段封闭
（01§2.4 五字段），裁剪记录以 origin 注记 + 本文件 trim_log 双落。

### 3.5 Checkpoint（`state/checkpoint-<ckpt-id>.json` + checkpoints 表）

```json
{"checkpoint_id": "ckpt-<ulid>", "task_id": "task-xxx",
 "created_at": "…", "state": {…TaskState 全量 dict…},
 "workspace_manifest": {"task_id": "…", "dirs": [六目录],
   "files": {"scratch": {"scratch/draft.txt": "<sha256>"}, …}, "file_count": 1}}
```

## 4. SQLite（`state.db`）

| 表 | 列 | 说明 |
| --- | --- | --- |
| `task_state` | task_id PK, version, status, updated_at, state_json | TaskState 全量 JSON；乐观锁 version |
| `artifacts` | artifact_id PK, task_id, status, record_json | ArtifactRecord JSON |
| `memory` | memory_id PK, task_id, mem_type, subject, content_json, provenance_json, ref_count, superseded_by, created_at, valid_until, archived | 四类记忆（WORKING/EPISODIC/SEMANTIC/PROCEDURAL）；valid_until 空串=无 TTL |
| `knowledge` | entry_id PK, content_json, review_json, registered_at | Knowledge 只读条目（M7 评审通道注册；agent 变更一律拒绝+审计） |
| `checkpoints` | checkpoint_id PK, task_id, created_at, payload_json | Checkpoint 全量 |
| `sessions` / `calls` | 见 session.py | Call⊂Session⊂Task 三级（规格四表之上的超集） |

- 连接串可配（DoD §5 迁移位）：`StateStore(dsn)`，`sqlite:///<path>` 或裸路径 → SQLite；
  `postgres*` → `NotImplementedError`（本期不实现，仅预留）；
- `content_json`：`{"subject", "claim"}`；`provenance_json`：写入六问的输入
  `{why_now, source, trace_id, verification, valid_until, ttl_days?}`（verification ∈
  VERIFIED/UNVERIFIED/SPECULATIVE；SPECULATIVE 直接 REJECTED）。

## 5. Artifact 内容文件与状态机

- 内容路径：`artifacts/<artifact_id>/v<version>.json`（content_ref 为 workspace 相对路径）；
- 迁移表：01§5.3（`artifact.ARTIFACT_TRANSITIONS`，与
  `tests/fixtures/frozen_state_machines.yaml` diff 为空，EVAL-M2-08-P2 断言）；
- 每次迁移落 `artifact.state_changed {from, to}`（创建为 `NONE→DRAFT`）；
- schema 钩子：`artifact.register_schema(schema_id, fn)`，签名
  `fn(content, ctx) -> {"passed": bool, "checks": [{name, passed, detail}]}`；
  内置 `report.daily@v1`（ADDENDUM §B 四段：devices/measurements(points 时序趋势)/
  conclusion/regulation_refs；`ctx["rule_id_checker"]` 为 M4 规则 ID 存在性联动钩子）；
  未注册 schema_id 校验即失败（不可 PUBLISH）。

## 6. 事件语义（M2 落流口径）

| 场景 | 事件 | 载荷要点 |
| --- | --- | --- |
| 建任务 | `task.created` | `{user_input, turn, state: 初始全量}`（重建锚点） |
| 状态提交 | `task.status_changed` | `{from, to, accepted: true, mutation, version, updated_at}`；from==to 表示非状态字段提交（事件目录无 task.updated，登记偏差） |
| 非法迁移 | `task.status_changed` | `{accepted: false, reason}`（重建时跳过） |
| 恢复 | `task.status_changed` | `{restored_from: ckpt-id, state: 恢复后全量}` |
| 产物迁移 | `artifact.state_changed` | `{from, to, task_id, schema_id, version}` |
| 预算耗尽 | `budget.exhausted` | `{kind: "token", budget, policy_tokens}`（policy 永不裁，任务转 PAUSED） |
| 跨任务写拒绝 | `action.policy_decided` | `{decision: "DENY", capability: "workspace.write_cross", …}`（事件目录无独立安全主题，登记偏差） |
| Knowledge 变更拒绝 | `action.policy_decided` | `{decision: "DENY", capability: "knowledge.mutate", …}`（同上） |
