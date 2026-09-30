# -*- coding: utf-8 -*-
"""fault/run_tests.py · 线3 自测运行器（退出码为证；EVALS 风格输出）。

覆盖：
  A. DSL 白名单/参数域/兼容矩阵/YAML roundtrip（越界即拒）
  B. LLM 桥：规则解析兜底、对 LLM 输出零信任（乱码/越界 JSON 一律拒）、提示词落盘
  C. 四类故障端到端：注入→检测→agent 步骤流（可解释）→隔离/倒闸→清除
  D. 人机对比开关：关闭后零 agent 步骤、人工同款操作面、非法操作拒绝、中途再开
  E. 事件流：JSONL 落盘、seq 单调、schema 封闭；事件流样例写 fault/examples/
  F. 确定性：同 seed 双跑事件流逐事件一致（除墙钟 ts）
运行：python fault/run_tests.py   （退出码 0=全过）
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from fault import (  # noqa: E402
    DAYLIGHT, Engine, EventBus, FaultRejected, Topology, demo_park,
    fault_to_yaml, nl_to_fault, parse_fault_yaml, parse_llm_output,
    render_prompt, rule_parse, validate_fault_dict,
)
from fault.llm_bridge import PROMPT_PATH  # noqa: E402

EXAMPLES = os.path.join(HERE, "examples")

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def sc_tx01(**over):
    d = {"type": "SHORT_CIRCUIT", "target": "TX-01", "at_s": 1.0,
         "params": {"phase": "three", "impedance_ohm": 0.1, "permanent": True},
         "note": "1号主变三相短路"}
    d.update(over)
    return d


def mk_engine(agent=True):
    return Engine(demo_park(), seed=20261001, agent_enabled=agent)


def steps_of(stream, ano_id=None):
    return [e for e in stream.to_list(channel="agent")
            if ano_id is None or e["payload"]["anomaly_id"] == ano_id]


def ops_of(stream, by=None, op=None):
    return [e for e in stream.to_list(channel="ops")
            if (by is None or e["payload"]["by"] == by)
            and (op is None or e["payload"]["op"] == op)]


def assert_common_integrity(stream):
    seqs = [e["seq"] for e in stream.to_list()]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), "seq 必须单调唯一"
    for e in stream.to_list():
        assert set(e) == {"seq", "ts", "sim_s", "channel", "type", "payload"}
        assert TS_RE.match(e["ts"]), f"ts 非法: {e['ts']}"
        assert isinstance(e["payload"], dict)


# ================================================================ A. DSL
def t_dsl_whitelist_accept():
    topo = demo_park()
    ok = [
        {"type": "SHORT_CIRCUIT", "target": "TX-01"},
        {"type": "SHORT_CIRCUIT", "target": "LN-A1"},
        {"type": "LINE_BREAK", "target": "LN-A1"},
        {"type": "TX_OVERLOAD", "target": "TX-02", "params": {"overload_ratio": 1.2}},
        {"type": "PV_TRIP", "target": "PV-01", "params": {"reason": "over_voltage"}},
    ]
    for raw in ok:
        spec = validate_fault_dict(raw, topo, seq=1)
        assert spec.params, f"{raw['type']} 默认参数必须回填"
    spec = validate_fault_dict({"type": "TX_OVERLOAD", "target": "TX-02"}, topo, seq=1)
    assert spec.params["overload_ratio"] == 1.2, "过载默认 ratio=1.2"
    assert spec.fault_id == "FLT-001"


def t_dsl_reject_four_ways():
    topo = demo_park()
    # ① 类型越界
    try:
        validate_fault_dict({"type": "BUS_HIT_BY_BIRD", "target": "BUS-A1"}, topo)
        raise AssertionError("类型越界未拒")
    except FaultRejected as e:
        assert any("白名单" in r for r in e.reasons), e.reasons
    # ② 目标不存在
    try:
        validate_fault_dict({"type": "SHORT_CIRCUIT", "target": "TX-99"}, topo)
        raise AssertionError("未知元件未拒")
    except FaultRejected as e:
        assert any("不存在" in r for r in e.reasons)
    # ③ 类型-元件不匹配
    for raw in ({"type": "PV_TRIP", "target": "TX-01"},
                {"type": "TX_OVERLOAD", "target": "PV-01"},
                {"type": "LINE_BREAK", "target": "BUS-A1"}):
        try:
            validate_fault_dict(raw, topo)
            raise AssertionError(f"不匹配未拒: {raw}")
        except FaultRejected as e:
            assert any("不匹配" in r for r in e.reasons)
    # ④ 参数越界/未知键/类型错
    for raw in ({"type": "TX_OVERLOAD", "target": "TX-01", "params": {"overload_ratio": 5.0}},
                {"type": "SHORT_CIRCUIT", "target": "LN-A1", "params": {"impedance_ohm": -1}},
                {"type": "SHORT_CIRCUIT", "target": "LN-A1", "params": {"magic": 1}},
                {"type": "SHORT_CIRCUIT", "target": "LN-A1", "params": {"phase": "four"}},
                {"type": "TX_OVERLOAD", "target": "TX-01", "at_s": -3}):
        try:
            validate_fault_dict(raw, topo)
            raise AssertionError(f"参数越界未拒: {raw}")
        except FaultRejected:
            pass


def t_dsl_yaml_roundtrip():
    topo = demo_park()
    raw = {"fault_id": "FLT-X1", "type": "SHORT_CIRCUIT", "target": "TX-01",
           "at_s": 2.5, "params": {"phase": "two", "impedance_ohm": 1.5},
           "note": "往返测试"}
    spec = validate_fault_dict(raw, topo)
    text = fault_to_yaml(spec)
    spec2 = parse_fault_yaml(text, topo)
    assert spec2.to_dict() == spec.to_dict(), (spec.to_dict(), spec2.to_dict())


def t_dsl_engine_duplicate_reject():
    eng = mk_engine()
    eng.inject(sc_tx01())
    try:
        eng.inject(sc_tx01())
        raise AssertionError("同型同目标重复注入未拒")
    except FaultRejected as e:
        assert any("同型" in r for r in e.reasons)


# ================================================================ B. LLM 桥
def t_llm_rule_parser():
    topo = demo_park()
    cases = [
        ("1号主变发生三相短路，赶紧处理", "SHORT_CIRCUIT", "TX-01", "three"),
        ("A区出线1断线了", "LINE_BREAK", "LN-A1", None),
        ("1号主变过载120%", "TX_OVERLOAD", "TX-01", None),
        ("2号主变过载到115%", "TX_OVERLOAD", "TX-02", None),
        ("屋顶光伏1脱网了", "PV_TRIP", "PV-01", None),
    ]
    for text, t, tgt, phase in cases:
        spec = rule_parse(text, topo)
        assert spec.type == t and spec.target == tgt, (text, spec.type, spec.target)
        if phase:
            assert spec.params["phase"] == phase
    # 过载比例解析
    assert rule_parse("1号主变过载120%", topo).params["overload_ratio"] == 1.2
    # 识别不了要如实拒绝
    for bad in ("帮我把电价改了", "今天天气怎么样"):
        try:
            rule_parse(bad, topo)
            raise AssertionError(f"应拒绝: {bad}")
        except FaultRejected:
            pass


class FakeLLM:
    """可脚本化的假 LLM（测试零真实调用，不占模型配额）。"""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    def chat(self, system, user):
        self.calls += 1
        return self.reply


class FakeLLMDown:
    """模拟通道故障：chat 抛异常（非输出越界）。"""

    def chat(self, system, user):
        raise RuntimeError("connection refused（模拟通道故障）")


def t_llm_zero_trust_guard():
    topo = demo_park()
    # 乱码/非 JSON
    for bad in ("我想想啊……", "```yaml\ntype: SHORT_CIRCUIT\n```"):
        try:
            parse_llm_output(bad, topo)
            raise AssertionError(f"应拒: {bad!r}")
        except FaultRejected as e:
            assert any("JSON" in r for r in e.reasons)
    # 白名单外类型
    try:
        parse_llm_output('{"type":"GRID_ATTACK","target":"GRID-A"}', topo)
        raise AssertionError("白名单外未拒")
    except FaultRejected:
        pass
    # 未知目标 / 类型不匹配
    for bad in ('{"type":"SHORT_CIRCUIT","target":"TX-99"}',
                '{"type":"TX_OVERLOAD","target":"PV-01"}',
                '{"type":"TX_OVERLOAD","target":"TX-02","params":{"overload_ratio":9}}'):
        try:
            parse_llm_output(bad, topo)
            raise AssertionError(f"应拒: {bad}")
        except FaultRejected:
            pass
    # LLM 自我拒绝也要透传
    try:
        parse_llm_output('{"rejected":true,"reasons":["不在白名单"]}', topo)
        raise AssertionError("LLM 拒绝应透传")
    except FaultRejected as e:
        assert any("LLM" in r for r in e.reasons)
    # 合法输出放行且带来源标注
    spec = parse_llm_output(
        '{"type":"TX_OVERLOAD","target":"TX-02","params":{"overload_ratio":1.3},'
        '"note":"模拟高负载"}', topo)
    assert spec.type == "TX_OVERLOAD" and spec.target == "TX-02"
    assert spec.params["overload_ratio"] == 1.3 and "LLM" in spec.note
    # SSRF 加固：base_url 仅允许 http(s)（Mimosa advisory 处置）
    from fault import HigressClient
    for bad in ("file:///etc/passwd", "ftp://100.100.0.6", "http://", "gopher://x"):
        try:
            HigressClient(base_url=bad)
            raise AssertionError(f"base_url 未拒: {bad}")
        except ValueError:
            pass
    assert HigressClient(base_url="http://100.100.0.6:8080").base_url \
        == "http://100.100.0.6:8080"
    # nl_to_fault：LLM 通道故障（chat 抛异常）→ 规则兜底，页面不瘫
    spec = nl_to_fault("1号主变三相短路", topo, client=FakeLLMDown())
    assert spec.type == "SHORT_CIRCUIT" and spec.target == "TX-01"
    # nl_to_fault：LLM 输出垃圾文本（通道应答但不可解析）→ 如实拒绝不兜底
    try:
        nl_to_fault("1号主变三相短路", topo, client=FakeLLM("网络超时了，请重试"))
        raise AssertionError("垃圾回复应拒绝而非兜底")
    except FaultRejected:
        pass
    # nl_to_fault：LLM 明确越界 → 如实拒绝，不静默兜底（注入是危险操作）
    try:
        nl_to_fault("随便来点故障", topo, client=FakeLLM('{"type":"MAGIC","target":"TX-01"}'))
        raise AssertionError("LLM 越界应拒绝")
    except FaultRejected:
        pass


def t_llm_prompt_on_disk():
    assert os.path.isfile(PROMPT_PATH), f"提示词未落盘: {PROMPT_PATH}"
    tpl = open(PROMPT_PATH, encoding="utf-8").read()
    for token in ("SHORT_CIRCUIT", "LINE_BREAK", "TX_OVERLOAD", "PV_TRIP",
                  "{{ELEMENTS}}", "rejected"):
        assert token in tpl, f"提示词缺 {token}"
    rendered = render_prompt(demo_park())
    assert "{{ELEMENTS}}" not in rendered
    assert "TX-01" in rendered and "PV-01" in rendered


# ================================================================ C. 四类端到端
def t_e2e_short_circuit():
    eng = mk_engine()
    eng.inject(sc_tx01())
    eng.run(4.0)
    s = eng.stream
    assert_common_integrity(s)
    inj = [e for e in s.to_list("fault", "fault.injected")]
    assert len(inj) == 1 and inj[0]["payload"]["target"] == "TX-01"
    det = [e for e in s.to_list("fault", "fault.detected")]
    assert det and det[0]["payload"]["hint"] == "SHORT_CIRCUIT" \
        and det[0]["payload"]["target"] == "TX-01" \
        and det[0]["payload"]["severity"] == "P0"
    ano_id = det[0]["payload"]["anomaly_id"]
    steps = steps_of(s, ano_id)
    assert len(steps) >= 8, f"步骤流过短: {len(steps)}"
    assert steps[0]["payload"]["phase"] == "confirm"
    for st in steps:
        p = st["payload"]
        assert p["why"], f"步骤{p['step_no']} 缺 why"
        assert p["looked_at"], f"步骤{p['step_no']} 缺 looked_at"
        assert "found" in p
    phases = [x["payload"]["phase"] for x in steps]
    assert "judge" in phases and "plan" in phases and "verify" in phases, phases
    # 隔离 + 转供动作
    opened = {e["payload"]["target"] for e in ops_of(s, by="agent", op="open")}
    assert opened == {"SG-A1H", "SG-A02"}, opened
    closed = [e for e in ops_of(s, by="agent", op="close")]
    assert [e["payload"]["target"] for e in closed] == ["SG-TIE"]
    assert all(e["payload"]["result"] in ("ok", "noop") for e in ops_of(s))
    clr = [e for e in s.to_list("fault", "anomaly.cleared")]
    assert clr and clr[0]["payload"]["by"] == "agent"
    # 状态终态：故障隔离、负荷恢复
    snap = eng.state_snapshot()
    assert snap["switches"]["SG-A1H"] == "OPEN"
    assert snap["switches"]["SG-A02"] == "OPEN"
    assert snap["switches"]["SG-TIE"] == "CLOSED"
    assert snap["sample"]["BUS-A2"]["v_pu"] == 1.0
    assert snap["sample"]["BUS-A3"]["v_pu"] == 1.0
    assert snap["sample"]["TX-01"]["current_ratio"] < 4.0, "隔离后不得再有故障电流"
    assert snap["sample"]["LOAD-A1"]["kw"] > 100, "转供后 A3 负荷应恢复供电"
    # 事件流样例落盘
    n = s.write_jsonl(os.path.join(EXAMPLES, "eventstream-sc-tx01.jsonl"))
    assert n == len(s)
    _write_fault_example("sc_tx01")


def t_e2e_line_break():
    eng = mk_engine()
    eng.inject({"type": "LINE_BREAK", "target": "LN-A1", "at_s": 1.0,
                "params": {"phase": "single", "permanent": True},
                "note": "A区出线1断线"})
    eng.run(4.0)
    s = eng.stream
    assert_common_integrity(s)
    det = [e for e in s.to_list("fault", "fault.detected")]
    assert det and det[0]["payload"]["hint"] == "LINE_BREAK" \
        and det[0]["payload"]["target"] == "LN-A1"
    ano_id = det[0]["payload"]["anomaly_id"]
    steps = steps_of(s, ano_id)
    assert len(steps) >= 8
    assert all(x["payload"]["why"] for x in steps)
    opened = {e["payload"]["target"] for e in ops_of(s, by="agent", op="open")}
    assert opened == {"SG-A01"}, opened
    assert not ops_of(s, by="agent", op="close"), "故障区下游不得转供恢复"
    assert [e for e in s.to_list("fault", "anomaly.cleared")], "隔离后异常应清除"
    snap = eng.state_snapshot()
    assert snap["sample"]["BUS-A3"]["v_pu"] == 0.0, "故障区下游保持停运待抢修"
    assert snap["sample"]["PV-01"]["kw"] == 0.0, "失电母线光伏联锁脱网"
    # 判别与小结可解释性：断线签名 + 抢修结论
    all_text = json.dumps([x["payload"] for x in steps], ensure_ascii=False)
    assert "断线" in all_text and ("抢修" in all_text or "待抢修" in all_text)
    # 不许误报光伏脱网异常（母线失电导致的出力为 0 是联锁不是异常）
    assert not any(k[0] == "PV_TRIP" for k in eng.detector.active), \
        "失电联锁不得误报 PV_TRIP 异常"
    s.write_jsonl(os.path.join(EXAMPLES, "eventstream-lb-lna1.jsonl"))
    _write_fault_example("lb_ln_a1")


def t_e2e_tx_overload():
    eng = mk_engine()
    eng.inject({"type": "TX_OVERLOAD", "target": "TX-01", "at_s": 1.0,
                "params": {"overload_ratio": 1.1, "cause": "下游负荷骤增"},
                "note": "1号主变重过载"})
    eng.run(4.0)
    s = eng.stream
    assert_common_integrity(s)
    det = [e for e in s.to_list("fault", "fault.detected")]
    assert det and det[0]["payload"]["hint"] == "TX_OVERLOAD" \
        and det[0]["payload"]["target"] == "TX-01" \
        and det[0]["payload"]["severity"] == "P0"
    ano_id = det[0]["payload"]["anomaly_id"]
    steps = steps_of(s, ano_id)
    assert len(steps) >= 8
    all_text = json.dumps([x["payload"] for x in steps], ensure_ascii=False)
    assert "PHYS-TX-LOAD" in all_text or "1.0" in all_text, "判据引用应可追溯"
    opened = {e["payload"]["target"] for e in ops_of(s, by="agent", op="open")}
    assert opened == {"SG-A1H", "SG-A02"}, opened
    assert [e["payload"]["target"] for e in ops_of(s, by="agent", op="close")] == ["SG-TIE"]
    clr = s.to_list("fault", "anomaly.cleared")
    assert clr and clr[0]["payload"]["by"] == "agent"
    snap = eng.state_snapshot()
    tx1 = snap["sample"]["TX-01"]["load_rate"]
    tx2 = snap["sample"]["TX-02"]["load_rate"]
    assert tx1 < 0.8, f"转供后 TX-01 应解除过载: {tx1}"
    assert 0.8 <= tx2 < 1.0, f"转供后 TX-02 应接载且不越限: {tx2}"
    assert tx2 > 0.8, "TX-02 应体现转供负载（高位运行）"
    warn = [e for e in s.to_list("fault", "threshold.warn")]
    assert any(w["payload"]["target"] == "TX-02" for w in warn), \
        "转供后 TX-02 高位应触发预警事件"
    assert [e for e in s.to_list("control", "control.escalated")] == [], \
        "本场景不得有升级（方案应一次成功）"
    s.write_jsonl(os.path.join(EXAMPLES, "eventstream-txover-tx01.jsonl"))
    _write_fault_example("tx_overload_tx01")


def t_e2e_pv_trip():
    eng = mk_engine()
    eng.inject({"type": "PV_TRIP", "target": "PV-01", "at_s": 1.0,
                "params": {"lost_ratio": 1.0, "reason": "over_voltage"},
                "note": "光伏脱网"})
    eng.run(4.0)
    s = eng.stream
    assert_common_integrity(s)
    det = [e for e in s.to_list("fault", "fault.detected")]
    assert det and det[0]["payload"]["hint"] == "PV_TRIP" \
        and det[0]["payload"]["target"] == "PV-01" \
        and det[0]["payload"]["severity"] == "P2"
    ano_id = det[0]["payload"]["anomaly_id"]
    steps = steps_of(s, ano_id)
    assert len(steps) >= 5, f"PV 步骤流过短: {len(steps)}"
    assert all(x["payload"]["why"] for x in steps)
    # 不做任何开关操作，只有告警确认
    assert not ops_of(s, by="agent", op="open") and not ops_of(s, by="agent", op="close")
    acks = [e for e in ops_of(s, by="agent", op="ack")]
    assert acks and acks[0]["payload"]["target"] == ano_id
    all_text = json.dumps([x["payload"] for x in steps], ensure_ascii=False)
    assert "运维" in all_text, "结论应包含转运维处置"
    # 故障保持（待消缺）——如实不报清除
    assert not s.to_list("fault", "anomaly.cleared"), "消缺前不得假报清除"
    assert eng.detector.active[("PV_TRIP", "PV-01")].acked, "异常应标记已确认"
    s.write_jsonl(os.path.join(EXAMPLES, "eventstream-pvtrip-pv01.jsonl"))
    _write_fault_example("pv_trip_pv01")


# ================================================================ D. 人机对比
def t_human_mode_switch():
    eng = mk_engine()
    eng.set_agent_enabled(False, note="人机对比：交人工")
    assert [e for e in eng.stream.to_list("control", "mode.agent_disabled")]
    eng.inject({"type": "TX_OVERLOAD", "target": "TX-01", "at_s": 1.0,
                "params": {"overload_ratio": 1.1}, "note": "人工模式过载"})
    eng.run(1.5)
    s = eng.stream
    det = s.to_list("fault", "fault.detected")
    assert det and det[0]["payload"]["hint"] == "TX_OVERLOAD"
    ano_id = det[0]["payload"]["anomaly_id"]
    passed = s.to_list("control", "control.passed")
    assert passed and passed[0]["payload"]["anomaly_id"] == ano_id
    assert not s.to_list("agent"), "人工模式不得有任何 agent 步骤"
    assert not ops_of(s, by="agent")
    # 人工用同款操作面处置
    for act in ({"op": "open", "target": "SG-A1H", "reason": "人工隔离1号主变"},
                {"op": "open", "target": "SG-A02", "reason": "人工隔离低压侧"},
                {"op": "close", "target": "SG-TIE", "reason": "人工倒闸转供"}):
        r = eng.human_action(act)
        assert r["ok"] and r["result"] == "ok", (act, r)
    # 非法操作：越界 op 与不可遥控目标都要拒
    r = eng.human_action({"op": "detonate", "target": "TX-01", "reason": "越界"})
    assert not r["ok"]
    r = eng.human_action({"op": "open", "target": "TX-01", "reason": "主变不是开关"})
    assert not r["ok"]
    rej = s.to_list("ops", "action.rejected")
    assert len(rej) == 2 and all(e["payload"]["by"] == "human" for e in rej)
    eng.run(4.0)
    clr = [e for e in s.to_list("fault", "anomaly.cleared")]
    assert clr and clr[0]["payload"]["by"] == "human", "人工处置清除应归属 human"
    assert not s.to_list("agent"), "全程零 agent 步骤"
    # 中途把 agent 打开：后续新异常由 agent 接管
    eng.set_agent_enabled(True, note="人机对比：agent 接管")
    assert [e for e in s.to_list("control", "mode.agent_enabled")]
    eng.inject({"type": "PV_TRIP", "target": "PV-01", "at_s": 5.0,
                "params": {"reason": "equipment"}, "note": "agent 接管光伏脱网"})
    eng.run(8.0)
    agent_steps = s.to_list("agent")
    assert agent_steps, "重开后 agent 应接管新异常"
    assert all(e["payload"]["anomaly_id"] != ano_id for e in agent_steps), \
        "重开前的人工异常不得被 agent 补写步骤"
    s.write_jsonl(os.path.join(EXAMPLES, "eventstream-human-mode.jsonl"))


# ================================================================ E/F. 流与确定性
def _scenario(eng):
    eng.inject(sc_tx01())
    eng.inject({"type": "PV_TRIP", "target": "PV-01", "at_s": 3.0,
                "params": {"reason": "over_voltage"}, "note": "混合场景"})
    eng.run(6.0)


def t_stream_schema_and_determinism():
    s1, s2 = EventBus(), EventBus()
    e1 = Engine(demo_park(), seed=7, stream=s1)
    e2 = Engine(demo_park(), seed=7, stream=s2)
    _scenario(e1)
    _scenario(e2)
    strip = lambda evts: [{k: v for k, v in e.items() if k != "ts"} for e in evts]
    assert strip(s1.to_list()) == strip(s2.to_list()), "同 seed 双跑必须逐事件一致"
    assert_common_integrity(s1)
    # 混合场景行为：两类异常都被检出，agent 都有步骤
    hints = {e["payload"]["hint"] for e in s1.to_list("fault", "fault.detected")}
    assert hints == {"SHORT_CIRCUIT", "PV_TRIP"}, hints
    p = os.path.join(EXAMPLES, "eventstream-mixed-determinism.jsonl")
    n = s1.write_jsonl(p)
    with open(p, encoding="utf-8") as f:
        lines = [json.loads(x) for x in f]
    assert len(lines) == n and [x["seq"] for x in lines] == list(range(1, n + 1))


# ================================================================ 样例 DSL
FAULT_EXAMPLES = {
    "sc_tx01.yaml": """# 示例：1号主变三相短路（四类之一 SHORT_CIRCUIT）
fault_id: FLT-EX-SC-01
type: SHORT_CIRCUIT
target: TX-01            # 变压器（line/transformer 允许）
at_s: 0.0                # 仿真秒
params:
  phase: three           # single|two|three
  impedance_ohm: 0.1     # (0, 50]
  permanent: true
note: 1号主变三相短路（演示样例）
""",
    "lb_ln_a1.yaml": """# 示例：A区出线1断线（四类之一 LINE_BREAK）
fault_id: FLT-EX-LB-01
type: LINE_BREAK
target: LN-A1            # 仅 line
at_s: 0.0
params:
  phase: single
  permanent: true
note: A区出线1单相断线（演示样例）
""",
    "tx_overload_tx01.yaml": """# 示例：1号主变重过载（四类之一 TX_OVERLOAD）
fault_id: FLT-EX-TXO-01
type: TX_OVERLOAD
target: TX-01            # 仅 transformer
at_s: 0.0
params:
  overload_ratio: 1.1    # (1.0, 3.0]；>1.0 触发 P0（REG-TECH PHYS-TX-LOAD 口径）
  cause: 下游负荷骤增
note: 1号主变 110% 重过载（演示样例）
""",
    "pv_trip_pv01.yaml": """# 示例：屋顶光伏脱网（四类之一 PV_TRIP）
fault_id: FLT-EX-PVT-01
type: PV_TRIP
target: PV-01            # 仅 pv
at_s: 0.0
params:
  lost_ratio: 1.0        # (0, 1.0]
  reason: over_voltage   # over_voltage|over_frequency|island|equipment
note: 光伏过压脱网（演示样例）
""",
}


def _write_fault_example(name):
    return name  # 样例 YAML 统一由 main() 写盘


def main():
    os.makedirs(EXAMPLES, exist_ok=True)
    for fname, text in FAULT_EXAMPLES.items():
        with open(os.path.join(EXAMPLES, fname), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(text)
    cases = [(k, globals()[k]) for k in
             ["t_dsl_whitelist_accept", "t_dsl_reject_four_ways",
              "t_dsl_yaml_roundtrip", "t_dsl_engine_duplicate_reject",
              "t_llm_rule_parser", "t_llm_zero_trust_guard",
              "t_llm_prompt_on_disk", "t_e2e_short_circuit",
              "t_e2e_line_break", "t_e2e_tx_overload", "t_e2e_pv_trip",
              "t_human_mode_switch", "t_stream_schema_and_determinism"]]
    failed = []
    for name, fn in cases:
        try:
            fn()
            print(f"  PASS {name}")
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            failed.append((name, repr(exc)))
            print(f"  FAIL {name}: {exc}")
    total, ok = len(cases), len(cases) - len(failed)
    print(f"FAULT-TESTS mode=all cases={ok}/{total} failed={len(failed)} "
          f"result={'PASS' if not failed else 'FAIL'}")
    if failed:
        for name, err in failed:
            print(f"  failed: {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
