#!/usr/bin/env bash
# web/tests/smoke.sh · web 冒烟测试（GPU/本机 bash 通用）
# 前置：web/public/data/ 已有园区导出 JSON（dsl/validate.py export）。
# 断言：探活 / 静态页 / 遥测确定性（同 t 双跑一致）/ 遥测在动（不同 t 结果不同）/
#       故障注入 → FaultEvent schema / 人工判分。任一失败退出码 1。
set -u
cd "$(dirname "$0")/.."   # web/
PORT="${SMOKE_PORT:-8891}"
BASE="http://127.0.0.1:${PORT}"
FAILS=0

say() { printf '%s\n' "$*"; }
check() { # name, ok(0/1), detail
  if [ "$2" = "0" ]; then say "  PASS  $1"; else say "  FAIL  $1 —— $3"; FAILS=$((FAILS+1)); fi
}

command -v node >/dev/null 2>&1 || { say "node 不存在"; exit 2; }
ls public/data/*.json >/dev/null 2>&1 || { say "public/data 无园区 JSON（先跑 dsl/validate.py export）"; exit 2; }

PORT="$PORT" node server.js &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT

# 等待探活（最多 8s）
ok=1
for i in $(seq 1 16); do
  curl -sf "$BASE/api/health" >/dev/null 2>&1 && { ok=0; break; }
  sleep 0.5
done
check "server 探活" $ok "health 不通"

PARK=$(curl -sf "$BASE/api/parks" | node -e 'let d="";process.stdin.on("data",c=>d+=c).on("end",()=>{const j=JSON.parse(d);console.log(j.parks[0].id)})')
say "  (测试园区: $PARK)"

# 1) 静态首页
code=$(curl -s -o /tmp/smoke_index.html -w '%{http_code}' "$BASE/")
check "GET / → 200 且含视图骨架" $([ "$code" = "200" ] && grep -q 'view-overview' /tmp/smoke_index.html && echo 0 || echo 1) "code=$code"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/js/app.js")
check "静态 js 可达" $([ "$code" = "200" ] && echo 0 || echo 1) "code=$code"

# 2) park 全量
curl -sf "$BASE/api/park/$PARK" > /tmp/smoke_park.json
check "GET /api/park/:id → parkdsl-web/1" $(node -e 'const j=require("/tmp/smoke_park.json");process.exit(j.api==="parkdsl-web/1"&&j.nodes.length>0?0:1)' && echo 0 || echo 1) "schema 不符"

# 3) 遥测确定性：同 t 双跑逐字节一致
T=$(( $(date +%s) / 15 * 15 ))
curl -sf "$BASE/api/telemetry?park=$PARK&t=$T&points=8" -o /tmp/smoke_tel_a.json
curl -sf "$BASE/api/telemetry?park=$PARK&t=$T&points=8" -o /tmp/smoke_tel_b.json
check "遥测确定性（同 t 双跑逐字节一致）" $(cmp -s /tmp/smoke_tel_a.json /tmp/smoke_tel_b.json && echo 0 || echo 1) "两次响应不同"

# 4) 遥测在动：t 与 t+900 差异
curl -sf "$BASE/api/telemetry?park=$PARK&t=$((T+900))&points=8" -o /tmp/smoke_tel_c.json
check "遥测在动（t+900 响应不同）" $(cmp -s /tmp/smoke_tel_a.json /tmp/smoke_tel_c.json && echo 1 || echo 0) "两次响应相同（不动）"
# 且数值确实非零
if node -e 'const j=require("/tmp/smoke_tel_a.json");const s=Object.values(j.series).find(x=>x.p_kw&&x.p_kw.some(v=>Math.abs(v)>0.5));process.exit(s?0:1)'; then
  check "遥测数值非零" 0 ""
else
  check "遥测数值非零" 1 "全部≈0"
fi

# 5) 故障注入 → FaultEvent schema
curl -sf -X POST "$BASE/api/fault" -H 'Content-Type: application/json' \
  -d "{\"park\":\"$PARK\",\"text\":\"2 号变压器重瓦斯跳闸\"}" > /tmp/smoke_fault.json
check "POST /api/fault → FaultEvent（event_id/targets/telemetry_effects/agent.steps）" $(node -e '
const j=require("/tmp/smoke_fault.json");
const ok = j.event_id && Array.isArray(j.targets) && j.targets.length>0 &&
  Array.isArray(j.telemetry_effects) && j.agent && Array.isArray(j.agent.steps) && j.agent.steps.length>=5;
process.exit(ok?0:1)' && echo 0 || echo 1) "schema 不符"
node -e 'const j=require("/tmp/smoke_fault.json");console.log("  (fault:", j.event_id, j.type, j.severity, "targets="+j.targets.join(","), "steps="+j.agent.steps.length + ")")'

# 6) 故障后遥测受影响（注入 vs 清除后同 t 不同）
curl -sf "$BASE/api/telemetry?park=$PARK&t=$T&points=4" -o /tmp/smoke_tel_fault.json
curl -sf -X POST "$BASE/api/fault/clear" -H 'Content-Type: application/json' -d "{\"park\":\"$PARK\"}" >/dev/null
curl -sf "$BASE/api/telemetry?park=$PARK&t=$T&points=4" -o /tmp/smoke_tel_clean.json
check "故障注入改变遥测（效应生效）" $(cmp -s /tmp/smoke_tel_fault.json /tmp/smoke_tel_clean.json && echo 1 || echo 0) "注入前后遥测相同"

# 7) 人工判分（错选 → verdict 字段存在）
curl -sf -X POST "$BASE/api/human/attempt" -H 'Content-Type: application/json' \
  -d "{\"park\":\"$PARK\",\"targets\":[\"NOPE\"],\"started_at\":$(date +%s000)}" > /tmp/smoke_attempt.json
# 注意：clear 后无活动事件应 404；重注一次再判
curl -sf -X POST "$BASE/api/fault" -H 'Content-Type: application/json' \
  -d "{\"park\":\"$PARK\",\"text\":\"1 号线路断线\"}" >/dev/null
curl -sf -X POST "$BASE/api/human/attempt" -H 'Content-Type: application/json' \
  -d "{\"park\":\"$PARK\",\"targets\":[\"SG-A01\"],\"started_at\":$(date +%s000)}" > /tmp/smoke_attempt.json
check "POST /api/human/attempt → 判分字段" $(node -e '
const j=require("/tmp/smoke_attempt.json");
process.exit(j.verdict&&typeof j.precision==="number"&&Array.isArray(j.truth)?0:1)' && echo 0 || echo 1) "字段缺失"
curl -sf -X POST "$BASE/api/fault/clear" -H 'Content-Type: application/json' -d "{\"park\":\"$PARK\"}" >/dev/null

say ""

# ============ 第 2 节：桥管道 + 白名单（fault-events.md v0.2 §4/§1） ============
say "== BRIDGE 管道（stub 桩验证 server.js spawn/回退链；桥本体归 worker-B 线4） =="
kill $SRV 2>/dev/null; wait $SRV 2>/dev/null
STUB=/tmp/pd_stub_bridge.$$.py
cat > "$STUB" <<'PYEOF'
import sys, json
req = json.loads(sys.stdin.read())
park = req.get("park", {})
text = req.get("text", "")
pid = park.get("park", {}).get("id", "?")
nodes = [n["id"] for n in park.get("nodes", [])]
tgt = nodes[:1] or ["X"]
print(json.dumps({
  "event_id": "FLT-STUB-0001", "ts": "2026-10-01T00:00:00Z", "park_id": pid,
  "request_text": text, "type": "SHORT_CIRCUIT", "severity": "P0",
  "targets": tgt, "telemetry_effects": [],
  "agent": {"mode": "auto", "total_ms": 50, "steps": [
    {"idx": 1, "title": "告警确认", "detail": "stub", "phase": "confirm",
     "looked_at": nodes[:3], "found": {"k": "v"}, "why": "stub why", "conclusion": "stub done"}]},
  "actions": [{"action_id": "ACT-S1", "op": "open", "target": tgt[0], "by": "agent",
               "result": "ok", "reason": "stub isolate"}],
  "events": [{"type": "fault.detected", "severity": "P0", "target": tgt[0]}],
  "source": "stub"
}, ensure_ascii=False))
PYEOF

PORT="$PORT" FAULT_BRIDGE_CMD="python3 $STUB" node server.js &
SRV2=$!
ok=1
for i in $(seq 1 16); do curl -sf "$BASE/api/health" >/dev/null 2>&1 && { ok=0; break; }; sleep 0.5; done
check "bridge 模式探活" $ok "health 不通"
PARK2=$(curl -sf "$BASE/api/parks" | node -e 'let d="";process.stdin.on("data",c=>d+=c).on("end",()=>{console.log(JSON.parse(d).parks[0].id)})')
curl -sf -X POST "$BASE/api/fault" -H 'Content-Type: application/json' \
  -d "{\"park\":\"$PARK2\",\"text\":\"stub 注入测试\"}" > /tmp/smoke_bfault.json
check "桥生效：source=stub 且 steps[].looked_at/actions[].by 齐全（v0.2 扩展字段贯通）" $(node -e '
const j=require("/tmp/smoke_bfault.json");
const ok = j.source==="stub" && Array.isArray(j.agent.steps[0].looked_at) &&
  Array.isArray(j.actions) && j.actions[0].by==="agent" && Array.isArray(j.events);
process.exit(ok?0:1)' && echo 0 || echo 1) "桥管道未生效或 schema 不符"

# 桥失败 → 回退 mock（回退链 bridge→mock）。先杀上一实例等端口释放，避免 EADDRINUSE 竞态
kill $SRV2 2>/dev/null; wait $SRV2 2>/dev/null; sleep 0.6
PORT="$PORT" FAULT_BRIDGE_CMD="/bin/false" node server.js &
SRV2B=$!
for i in $(seq 1 16); do curl -sf "$BASE/api/health" >/dev/null 2>&1 && break; sleep 0.5; done
curl -sf -X POST "$BASE/api/fault" -H 'Content-Type: application/json' \
  -d "{\"park\":\"$PARK2\",\"text\":\"桥挂了测试\"}" > /tmp/smoke_fallback.json
check "桥失败回退 mock（source=mock，页面不瘫）" $(node -e '
const j=require("/tmp/smoke_fallback.json");process.exit(j.source==="mock"&&j.event_id?0:1)' && echo 0 || echo 1) "回退链未生效"
curl -sf -X POST "$BASE/api/fault/clear" -H 'Content-Type: application/json' -d "{\"park\":\"$PARK2\"}" >/dev/null
kill $SRV2B 2>/dev/null; wait $SRV2B 2>/dev/null; sleep 0.6

# 白名单（Mimosa advisory② 复核项）
PORT="$PORT" node server.js &
SRV3=$!
for i in $(seq 1 16); do curl -sf "$BASE/api/health" >/dev/null 2>&1 && break; sleep 0.5; done
c1=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/fault" -H 'Content-Type: application/json' -d '{"park":"../etc","text":"x"}')
check "白名单：非法 park（../etc）→ 400" $([ "$c1" = "400" ] && echo 0 || echo 1) "code=$c1"
c2=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/fault" -H 'Content-Type: application/json' \
  -d "{\"park\":\"$PARK2\",\"text\":\"x\",\"path\":\"/tmp/evil.jsonl\"}")
check "白名单：body 带 path 键 → 400" $([ "$c2" = "400" ] && echo 0 || echo 1) "code=$c2"
c3=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/telemetry?park=PARK-XX&points=1")
check "白名单：telemetry 非法 park（PARK-XX 不匹配正则）→ 400" $([ "$c3" = "400" ] && echo 0 || echo 1) "code=$c3"
kill $SRV3 2>/dev/null; wait $SRV3 2>/dev/null

say ""
if [ "$FAILS" = "0" ]; then say "WEB-SMOKE RESULT: PASS (all checks)"; exit 0; fi
say "WEB-SMOKE RESULT: FAIL ($FAILS failed)"; exit 1
