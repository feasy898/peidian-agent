#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-
"""arena/tests/test_gen_scenario.py · gen_scenario + model_gateway 单测（gen_scenario 落地验收）。

覆盖（≥6，每条零信任门各自一测）：
  A. parse_draft：代码围栏剥离 / 非 JSON 拒绝 / 非 dict 拒绝
  B. check_draft：kind 不在故障库 / criteria_ref 非库绑定真实 R 编号 / note 自带标准编号 /
     类型-元件不兼容 / 注入 params 越界（与引擎 PARAM_SPECS 同款）/ 慢爬升检不可行
  C. 装配同构 + dsl.validate_dsl 权威校验通过；续号 next_scene_no
  D. model_gateway：env 优先序（key/base）/ 无 key fail-closed / llm_agent 无 key 回退 mock
  E. dryrun_gate：检出不可达场景被拒（detected=0）

运行：python arena/tests/test_gen_scenario.py   （退出码 0=全过）
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from arena.gen_scenario import (  # noqa: E402
    FEWSHOT, assemble_yaml, basis_inventory, build_system_prompt, check_draft,
    dryrun_gate, load_fault_summary, load_reference_rs, next_scene_no, parse_draft)
from arena.model_gateway import KEY_ENV_VARS, ModelGateway, find_api_key  # noqa: E402
from dsl.validate import validate_dsl  # noqa: E402

CASES: list[tuple[str, bool]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    CASES.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  —— {detail}" if detail and not ok else ""))


LIB = load_fault_summary()
RS = load_reference_rs()
INV = basis_inventory("PARK-202")


def good_draft() -> dict:
    return copy.deepcopy(FEWSHOT[0])


# ================================================================ A. 解析
def t_parse_fence():
    text = "前言\n```json\n" + json.dumps({"a": 1}) + "\n```\n后记"
    data, why = parse_draft(text)
    record("parse_draft 剥围栏取 JSON", data == {"a": 1} and not why, str(why))


def t_parse_bad_json():
    data, why = parse_draft("这不是 JSON {")
    record("parse_draft 非 JSON 拒绝", data is None and bool(why))


def t_parse_non_dict():
    data, why = parse_draft("[1,2,3]")
    record("parse_draft 非 dict 拒绝", data is None and any("对象" in w for w in why))


# ================================================================ B. 语义校验拒绝
def t_check_bad_kind():
    d = good_draft()
    d["faults"][0]["kind"] = "short_circuit"   # 引擎原生但不在 11 类库 → 生成器拒绝
    why = check_draft(d, basis="PARK-202", faultlib=LIB, valid_rs=RS)
    record("check 拒绝非故障库 kind", any("不在故障库 11 类" in w for w in why), str(why))


def t_check_bad_criteria_ref():
    d = good_draft()
    d["faults"][0]["criteria_ref"] = "R999"    # 库该类型未绑定的编号
    why = check_draft(d, basis="PARK-202", faultlib=LIB, valid_rs=RS)
    record("check 拒绝非库绑定 R 编号", any("库条目绑定" in w for w in why), str(why))
    d2 = good_draft()
    d2["faults"][0]["criteria_ref"] = "Rxxxx"  # 非 R 编号格式
    why2 = check_draft(d2, basis="PARK-202", faultlib=LIB, valid_rs=RS)
    record("check 拒绝非 R 编号格式", any("R 编号" in w for w in why2), str(why2))


def t_check_note_std_cite():
    d = good_draft()
    d["faults"][0]["note"] = "依据 Q/GDW 11060-2013 分级处置"   # note 冒充文献 → 拒
    why = check_draft(d, basis="PARK-202", faultlib=LIB, valid_rs=RS)
    record("check 拒绝 note 自带标准编号", any("标准编号" in w for w in why), str(why))


def t_check_incompat_target():
    d = good_draft()
    d["faults"][0]["target"] = "TX-B01"        # partial_discharge 兼容 switchgear/transformer —— 换成必拒面
    d["faults"][0]["kind"] = "temperature_rise"  # 只兼容 switchgear
    why = check_draft(d, basis="PARK-202", faultlib=LIB, valid_rs=RS)
    record("check 拒绝类型-元件不兼容", any("不兼容" in w for w in why), str(why))


def t_check_param_domain():
    d = good_draft()
    d["injections"][0]["params"]["baseline_db"] = 99   # PARAM_SPECS [0,60] 越界
    why = check_draft(d, basis="PARK-202", faultlib=LIB, valid_rs=RS)
    record("check 拒绝注入参数越界(引擎同款)", any("越界" in w for w in why), str(why))
    d2 = good_draft()
    d2["injections"][0]["params"]["hallucinated_param"] = 1
    why2 = check_draft(d2, basis="PARK-202", faultlib=LIB, valid_rs=RS)
    record("check 拒绝幻觉参数名", any("合法参数" in w for w in why2), str(why2))


def t_check_infeasible_ramp():
    d = good_draft()
    d["injections"][0]["at_sim_s"] = 81000
    d["injections"][0]["params"] = {"baseline_db": 16, "growth_db_per_h": 0.1,
                                    "threshold_db": 20, "repair_s": 7200}   # 40h 才越限，剩余 25h 来不及
    why = check_draft(d, basis="PARK-202", faultlib=LIB, valid_rs=RS)
    record("check 拒绝慢爬升检不可行", any("检出可行性" in w for w in why), str(why))


# ================================================================ C. 装配 + 续号
def t_assemble_and_validate():
    import tempfile
    ok_all, detail = True, ""
    for i, d in enumerate(FEWSHOT):
        text = assemble_yaml(d, basis="PARK-202", scene_no=950 + i, subject="单测", model="glm-4-flash")
        cfg = yaml.safe_load(text)
        errs = validate_dsl(cfg, origin=f"<test-{i}>")
        if errs:
            ok_all, detail = False, "; ".join(e.line() for e in errs)
        if cfg.get("source") and "llm-draft" not in cfg["source"]:
            ok_all, detail = False, f"source 标注缺失: {cfg.get('source')}"
    record("装配 YAML 与 S-20x 同构且过 dsl 权威校验（含诚实 source 标注）", ok_all, detail)


def t_next_scene_no():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        base = next_scene_no(td)
        (Path(td) / "S-220.yaml").write_text("api: parkdsl/1\n", encoding="utf-8")
        after = next_scene_no(td)
        (Path(td) / "S-233.yaml").write_text("api: parkdsl/1\n", encoding="utf-8")
        after2 = next_scene_no(td)
        record("next_scene_no 续号（空库 201 / S-220→221 / S-233→234）",
               base == 201 and after == 221 and after2 == 234,
               f"{base}/{after}/{after2}")


def t_system_prompt_carries_contract():
    s = build_system_prompt(LIB)
    need = ["partial_discharge", "criteria_ref", "R37", "injections", "shift_handover"]
    missing = [k for k in need if k not in s]
    record("系统提示词携带故障库类型/R 编号/schema/few-shot", not missing, f"缺 {missing}")


# ================================================================ D. model_gateway env 回退
def t_gateway_env_priority():
    env = {"BIGMODEL_API_KEY": "kb", "LLM_BASE_URL": "https://b.example/v4"}
    ok1 = find_api_key(env) == "kb" and ModelGateway(env=env).base_url == "https://b.example/v4"
    env2 = {"OPENAI_API_KEY": "ko", "PD_MODEL_API_KEY": "kp"}   # legacy 尾位
    ok2 = find_api_key(env2) == "ko"
    env3 = {"PD_MODEL_API_KEY": "kp"}
    ok3 = find_api_key(env3) == "kp"
    record("gateway env 优先序 LLM>BIGMODEL>OPENAI>PD(legacy)", ok1 and ok2 and ok3)


def t_gateway_nokey_fail_closed():
    gw = ModelGateway(env={})
    raised = False
    try:
        gw.chat("s", "u")
    except Exception as exc:   # GatewayError，fail-closed
        raised = "API key" in str(exc)
    record("gateway 无 key fail-closed（GatewayError，不静默）",
           raised and not gw.enabled and KEY_ENV_VARS[0] == "LLM_API_KEY")


def t_llm_agent_mock_fallback():
    saved = {k: os.environ.get(k) for k in KEY_ENV_VARS}
    try:
        for k in KEY_ENV_VARS:
            os.environ.pop(k, None)
        from arena.llm_agent import LLMDiagnosisAgent
        agent = LLMDiagnosisAgent()
        r = agent.diagnose({"hint": "HARMONIC", "target": "BUS-A2", "severity": "P2",
                            "evidence": {}}, {})
        record("llm_agent 无 key 回退 mock（收编后行为不变）",
               not agent.enabled and r.get("source") == "mock", str(r.get("source")))
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


# ================================================================ E. 干跑门
def t_dryrun_gate_rejects_undetectable():
    d = good_draft()
    d["injections"][0]["at_sim_s"] = 0
    d["injections"][0]["params"] = {"baseline_db": 0, "growth_db_per_h": 1,
                                    "threshold_db": 20, "repair_s": 7200}
    d["duration_sim_s"] = 43200   # 12h：20dB 需 20h，永不可检出
    d["calendar_events"] = d["calendar_events"][:2]
    text = assemble_yaml(d, basis="PARK-202", scene_no=990, subject="单测", model="glm-4-flash")
    cfg = yaml.safe_load(text)
    errs = validate_dsl(cfg, origin="<gate-test>")
    if errs:
        record("dryrun_gate 拒绝检出不可达场景", False, "; ".join(e.line() for e in errs))
        return
    ok, summary, why = dryrun_gate(cfg, runs_root=ROOT / "runtime" / "gen-drytest",
                                   run_id="gen-test-gate")
    record("dryrun_gate 拒绝检出不可达场景（detected=0）",
           not ok and any("detected" in w for w in why), str(why))


if __name__ == "__main__":
    print("== arena/tests/test_gen_scenario.py")
    for fn in (t_parse_fence, t_parse_bad_json, t_parse_non_dict,
               t_check_bad_kind, t_check_bad_criteria_ref, t_check_note_std_cite,
               t_check_incompat_target, t_check_param_domain, t_check_infeasible_ramp,
               t_assemble_and_validate, t_next_scene_no, t_system_prompt_carries_contract,
               t_gateway_env_priority, t_gateway_nokey_fail_closed, t_llm_agent_mock_fallback,
               t_dryrun_gate_rejects_undetectable):
        fn()
    n_fail = sum(1 for _, ok in CASES if not ok)
    print(f"\nTOTAL cases={len(CASES)} failed={n_fail}")
    print("RESULT:", "PASS" if n_fail == 0 else "FAIL")
    sys.exit(0 if n_fail == 0 else 1)
