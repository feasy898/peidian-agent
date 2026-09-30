#!/usr/bin/env python3.12
"""ParkDSL v1 校验器/导出器 · peidian-agent worker-A 线1

子命令:
  validate <file.yaml> [...]   校验 DSL（--json 机器可读输出）
  export   <file.yaml> -o out.json   导出 parkdsl-web/1 JSON（web/ 前端数据源）
  summary  <file.yaml> [...]   规模摘要与 tier 推断

退出码: 0=全部通过  1=校验错误  2=用法/IO 错误
规范唯一裁决源: dsl/dsl_spec.yaml（数据驱动，本文不硬编码类型表）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

SPEC_PATH = Path(__file__).resolve().parent / "dsl_spec.yaml"
SPEC = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))

VOLTAGES = set(SPEC["voltage_levels"])
ID_DEVICE = re.compile(SPEC["id_rules"]["device"])
ID_SR = re.compile(SPEC["id_rules"]["substation"])
ID_PARK = re.compile(SPEC["id_rules"]["park"])
DEVICE_TYPES = SPEC["device_types"]
LINK_KINDS = SPEC["link_kinds"]
TIER_RULES = SPEC["tier_rules"]
DER_TYPES = set(SPEC["der_types"])


class Err:
    __slots__ = ("code", "loc", "msg", "actual")

    def __init__(self, code: str, loc: str, msg: str, actual=None):
        self.code, self.loc, self.msg, self.actual = code, loc, msg, actual

    def line(self) -> str:
        s = f"[{self.code}] {self.loc}: {self.msg}"
        if self.actual is not None:
            s += f" (实际: {self.actual})"
        return s


def _check_param(errs, loc, name, spec, value):
    if not isinstance(spec, dict):
        return
    t = spec.get("type")
    if t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errs.append(Err("E-DEV", loc, f"参数 {name} 应为数值", actual=repr(value)))
            return
    if t == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
        errs.append(Err("E-DEV", loc, f"参数 {name} 应为整数", actual=repr(value)))
    if "min" in spec and isinstance(value, (int, float)) and not isinstance(value, bool) and value < spec["min"]:
        errs.append(Err("E-DEV", loc, f"参数 {name} 低于下限 {spec['min']}", actual=value))
    if "max" in spec and isinstance(value, (int, float)) and not isinstance(value, bool) and value > spec["max"]:
        errs.append(Err("E-DEV", loc, f"参数 {name} 超过上限 {spec['max']}", actual=value))
    if "enum" in spec and value not in spec["enum"]:
        errs.append(Err("E-DEV", loc, f"参数 {name} 取值非法，允许 {spec['enum']}", actual=repr(value)))
    if spec.get("voltage") or name.endswith("voltage") or name in ("hv", "lv", "source_voltage", "voltage_level"):
        if value not in VOLTAGES:
            errs.append(Err("E-DEV", loc, f"参数 {name} 电压等级须 ∈ {sorted(VOLTAGES)}", actual=repr(value)))


def load_dsl(path: Path):
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return None, [Err("E-YAML", str(path), f"YAML 解析失败: {str(e).splitlines()[0]}")]
    if not isinstance(data, dict):
        return None, [Err("E-API", str(path), "顶层必须是映射", actual=type(data).__name__)]
    return data, []


def infer_tier(stats: dict) -> str:
    keymap = {"substations": "substations_max", "transformers": "transformers_max",
              "loads": "loads_max", "der": "der_max"}
    for tier in ("simple", "medium", "complex"):
        r = TIER_RULES[tier]
        if all(r[keymap[k]] is None or stats[k] <= r[keymap[k]] for k in keymap):
            return tier
    return "complex"


def validate_dsl(data: dict, origin: str = "<dsl>") -> list[Err]:
    errs: list[Err] = []
    if data.get("api") != SPEC["api"]:
        errs.append(Err("E-API", origin, f"api 必须为 {SPEC['api']!r}", actual=repr(data.get("api"))))
        return errs

    # ---- park 头 ----
    park = data.get("park")
    if not isinstance(park, dict):
        errs.append(Err("E-PARK", f"{origin}.park", "缺少 park 映射"))
        return errs
    for k in SPEC["park_required"]:
        if park.get(k) in (None, ""):
            errs.append(Err("E-PARK", f"{origin}.park.{k}", "必填字段缺失"))
    if park.get("tier") not in SPEC["park_tiers"]:
        errs.append(Err("E-PARK", f"{origin}.park.tier",
                        f"tier 须 ∈ {SPEC['park_tiers']}", actual=repr(park.get("tier"))))
    cck = park.get("contract_capacity_kw")
    if isinstance(cck, (int, float)) and not isinstance(cck, bool) and cck <= 0:
        errs.append(Err("E-PARK", f"{origin}.park.contract_capacity_kw", "合同容量必须 >0", actual=cck))
    if isinstance(park.get("id"), str) and not ID_PARK.match(park["id"]):
        errs.append(Err("E-ID", f"{origin}.park.id", "园区 ID 不匹配正则",
                        actual=park["id"]))

    # ---- devices（grid_inlets + substations.devices 同一命名空间）----
    devices: dict[str, dict] = {}
    devs_seq: list[tuple[str, dict, str]] = []  # (id, dev, loc)

    def take_devices(raw, sub_id: str | None, loc_prefix: str, default_type: str | None = None):
        if not isinstance(raw, list):
            errs.append(Err("E-DEV", loc_prefix, "devices 必须是数组"))
            return
        for i, d in enumerate(raw):
            loc = f"{loc_prefix}[{i}]"
            if not isinstance(d, dict):
                errs.append(Err("E-DEV", loc, "元件必须是映射", actual=repr(d)[:60]))
                continue
            d = dict(d)
            if d.get("type") is None and default_type is not None:
                d["type"] = default_type   # grid_inlets 元件可省 type（默认 GridInlet）
            did, dtype = d.get("id"), d.get("type")
            if not isinstance(did, str) or not ID_DEVICE.match(did):
                errs.append(Err("E-ID", f"{loc}.id", "元件 ID 不匹配正则", actual=repr(did)))
                continue
            if did in devices:
                errs.append(Err("E-ID", f"{loc}.id", f"元件 ID 重复（先见于 {devices[did]['_loc']}）",
                                actual=did))
                continue
            spec_t = DEVICE_TYPES.get(dtype)
            if spec_t is None:
                errs.append(Err("E-DEV", loc, f"未知元件类型，允许 {sorted(DEVICE_TYPES)}",
                                actual=repr(dtype)))
                continue
            dd = dict(d)
            dd["_loc"], dd["_sub"] = loc, sub_id
            devices[did] = dd
            devs_seq.append((did, dd, loc))
            for k in spec_t["required"]:
                if k not in d:
                    errs.append(Err("E-DEV", loc, f"类型 {dtype} 缺必填参数 {k}"))
            for k, pspec in {**spec_t["required"], **spec_t.get("optional", {})}.items():
                if k in d:
                    if pspec == "voltage":
                        if d[k] not in VOLTAGES:
                            errs.append(Err("E-DEV", f"{loc}.{k}",
                                            f"参数 {k} 电压等级须 ∈ {sorted(VOLTAGES)}", actual=repr(d[k])))
                    else:
                        _check_param(errs, f"{loc}.{k}", k, pspec, d[k])
            if dtype == "Transformer" and d.get("hv") == d.get("lv"):
                errs.append(Err("E-DEV", f"{loc}.lv", "变压器 hv/lv 必须不同", actual=d.get("lv")))

    gi = data.get("grid_inlets", [])
    if not isinstance(gi, list) or not gi:
        errs.append(Err("E-DEV", f"{origin}.grid_inlets", "grid_inlets 必须为非空数组"))
    else:
        take_devices(gi, None, f"{origin}.grid_inlets", default_type="GridInlet")
    subs_raw = data.get("substations", [])
    if not isinstance(subs_raw, list) or not subs_raw:
        errs.append(Err("E-DEV", f"{origin}.substations", "substations 必须为非空数组"))
        subs = []
    else:
        subs = []
        seen_sr = set()
        for i, s in enumerate(subs_raw):
            loc = f"{origin}.substations[{i}]"
            if not isinstance(s, dict) or not isinstance(s.get("id"), str) or not ID_SR.match(s.get("id", "")):
                errs.append(Err("E-ID", f"{loc}.id", "配电房 ID 须匹配 ^SR-[A-Z]$", actual=repr(s.get("id") if isinstance(s, dict) else s)))
                continue
            if s["id"] in seen_sr:
                errs.append(Err("E-ID", f"{loc}.id", "配电房 ID 重复", actual=s["id"]))
            seen_sr.add(s["id"])
            subs.append(s)
            take_devices(s.get("devices"), s["id"], f"{loc}.devices")

    # ---- links ----
    links = data.get("links", [])
    if not isinstance(links, list) or not links:
        errs.append(Err("E-LINK", f"{origin}.links", "links 必须为非空数组"))
        links = []
    edges: list[tuple[str, str, dict, str]] = []
    link_ids = set(devices)
    for i, lk in enumerate(links):
        loc = f"{origin}.links[{i}]"
        if not isinstance(lk, dict):
            errs.append(Err("E-LINK", loc, "link 必须是映射", actual=repr(lk)[:60]))
            continue
        kind = lk.get("kind")
        if kind not in LINK_KINDS:
            errs.append(Err("E-LINK", loc, f"kind 须 ∈ {sorted(LINK_KINDS)}", actual=repr(kind)))
            continue
        lspec = LINK_KINDS[kind]
        lid = lk.get("id")
        if lspec.get("prefix") or kind == "coupler":
            if not isinstance(lid, str) or not ID_DEVICE.match(lid):
                errs.append(Err("E-LINK", f"{loc}.id", f"kind:{kind} 必须带合法 id（前缀 {lspec.get('prefix', 'CP')}）",
                                actual=repr(lid)))
            elif lid in link_ids:
                errs.append(Err("E-LINK", f"{loc}.id", "link ID 与既有 ID 重复（同一命名空间）", actual=lid))
            else:
                link_ids.add(lid)
        for k, pspec in lspec.get("required", {}).items():
            if k == "id":
                continue
            if k not in lk:
                errs.append(Err("E-LINK", loc, f"kind:{kind} 缺必填参数 {k}"))
            else:
                _check_param(errs, f"{loc}.{k}", k, pspec, lk[k])
        fr, to = lk.get("from"), lk.get("to")
        for end, key in ((fr, "from"), (to, "to")):
            if end not in devices:
                errs.append(Err("E-LINK", f"{loc}.{key}", "端点引用的元件不存在", actual=repr(end)))
        if fr == to and fr is not None:
            errs.append(Err("E-LINK", loc, "自环连接", actual=fr))
        edges.append((fr, to, lk, loc))

    if errs:
        return errs

    # ---- E-VOLT：Bus-Bus 直连电压一致 ----
    for fr, to, lk, loc in edges:
        a, b = devices.get(fr, {}), devices.get(to, {})
        if a.get("type") == "Bus" and b.get("type") == "Bus" and \
           a.get("voltage_level") != b.get("voltage_level"):
            errs.append(Err("E-VOLT", loc, "Bus-Bus 直连电压级不一致（跨压须经变压器）",
                            actual=f"{a.get('voltage_level')} vs {b.get('voltage_level')}"))

    # ---- 拓扑图（常开耦合器断开 = 可运行拓扑）----
    def open_coupler(lk: dict) -> bool:
        return lk.get("kind") == "coupler" and lk.get("state", LINK_KINDS["coupler"]["optional"]["state"]["default"]) == "OPEN"

    operable = [(fr, to) for fr, to, lk, _ in edges if not open_coupler(lk)]
    adj: dict[str, list[str]] = {did: [] for did in devices}
    for fr, to in operable:
        if fr in adj and to in adj:
            adj[fr].append(to)
            adj[to].append(fr)

    inlets = [d for d, dd in devices.items() if dd["type"] == "GridInlet"]
    seen: set[str] = set()
    stack = list(inlets)
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(m for m in adj[n] if m not in seen)
    for did in devices:
        if did not in seen:
            errs.append(Err("E-TOPO", devices[did]["_loc"],
                            f"元件 {did} 从任何上级电源不可达（常开耦合器视为断开）", actual=did))

    # ---- E-LOOP：环检测（DFS 回边）----
    def find_back_edge(pair_list):
        adjx: dict[str, list[str]] = {did: [] for did in devices}
        for fr, to in pair_list:
            if fr in adjx and to in adjx:
                adjx[fr].append(to)
                adjx[to].append(fr)
        color = {d: 0 for d in devices}  # 0 白 1 灰 2 黑
        for root in devices:
            if color[root]:
                continue
            color[root] = 1
            # 栈帧 [node, parent, iter, parent_edge_skipped]——父边只豁免一次，
            # 否则平行边（双回线）构成的环会被当成父子回访漏检
            stack2 = [[root, None, iter(adjx[root]), False]]
            while stack2:
                top = stack2[-1]
                node, parent, it = top[0], top[1], top[2]
                advanced = False
                for nxt in it:
                    if nxt == parent and not top[3]:
                        top[3] = True
                        continue
                    if color[nxt] == 1:
                        return (node, nxt)
                    if color[nxt] == 0:
                        color[nxt] = 1
                        stack2.append([nxt, node, iter(adjx[nxt]), False])
                        advanced = True
                        break
                if not advanced:
                    color[node] = 2
                    stack2.pop()
        return None

    be_op = find_back_edge(operable)
    if be_op:
        errs.append(Err("E-LOOP", f"{origin}.links",
                        f"存在闭环运行路径（{be_op[0]}–{be_op[1]}）：环上联络点必须常开", actual=be_op))
    if park.get("tier") == "simple":
        be_full = find_back_edge([(fr, to) for fr, to, _, _ in edges])
        if be_full:
            errs.append(Err("E-LOOP", f"{origin}.links",
                            f"simple 档不允许任何环网结构（{be_full[0]}–{be_full[1]}）", actual=be_full))

    # ---- E-CAP ----
    def rated_kw(dd: dict) -> float:
        t = dd["type"]
        if t == "Load":
            return float(dd.get("peak_kw", 0))
        if t == "EVCharger":
            return float(dd.get("total_power_kw", 0))
        return 0.0

    total_load = sum(rated_kw(dd) for dd in devices.values())
    if cck and isinstance(cck, (int, float)) and total_load > cck:
        errs.append(Err("E-CAP", f"{origin}.park.contract_capacity_kw",
                        f"Σ(负荷+充电桩)={total_load:.0f}kW 超过合同容量 {cck}kW",
                        actual=f"{total_load:.0f}>{cck}"))

    factor = SPEC["topology_rules"]["tx_loading_factor"]
    for did, dd in [(d, devices[d]) for d in devices if devices[d]["type"] == "Transformer"]:
        lv = dd.get("lv")
        lv_neighbor = None
        for fr, to in operable:
            other = to if fr == did else fr if to == did else None
            if other is None:
                continue
            od = devices[other]
            if od.get("type") == "Bus" and od.get("voltage_level") == lv:
                lv_neighbor = other
                break
        if lv_neighbor is None:
            continue
        # 去掉该 TX 后从 lv 侧可达的负荷
        adj2: dict[str, list[str]] = {k: [] for k in devices}
        for fr, to in operable:
            if fr == did or to == did:
                continue
            adj2[fr].append(to)
            adj2[to].append(fr)
        reach, stack3 = set(), [lv_neighbor]
        while stack3:
            n = stack3.pop()
            if n in reach:
                continue
            reach.add(n)
            stack3.extend(adj2[n])
        down = sum(rated_kw(devices[r]) for r in reach if devices[r]["type"] in ("Load", "EVCharger"))
        cap = float(dd.get("capacity_kva", 0)) * factor
        if down > cap > 0:
            errs.append(Err("E-CAP", dd["_loc"],
                            f"变压器 {did} 低压侧下游 Σpeak={down:.0f}kW 超过容载上限 {cap:.0f}kW"
                            f"（{dd.get('capacity_kva')}kVA×{factor}）", actual=f"{down:.0f}>{cap:.0f}"))

    # ---- E-TIER：规模判据复核 ----
    stats = {
        "substations": len(subs),
        "transformers": sum(1 for dd in devices.values() if dd["type"] == "Transformer"),
        "loads": sum(1 for dd in devices.values() if dd["type"] == "Load"),
        "der": sum(1 for dd in devices.values() if dd["type"] in DER_TYPES),
    }
    inferred = infer_tier(stats)
    if park.get("tier") != inferred:
        errs.append(Err("E-TIER", f"{origin}.park.tier",
                        f"声明 tier={park.get('tier')} 与规模判据推断不符（{stats}），建议 tier={inferred}",
                        actual=stats))
    return errs


def build_export(data: dict, source: str) -> dict:
    """DSL → parkdsl-web/1（web/ 前端唯一数据源）"""
    park = data["park"]
    nodes, links_out, comps, buses = [], [], [], []
    subs_index = {s["id"]: s.get("name", s["id"]) for s in data.get("substations", [])}
    for raw in list(data.get("grid_inlets", [])):
        nodes.append({"id": raw["id"], "type": raw.get("type", "GridInlet"),
                      "label": raw.get("source_voltage", ""),
                      "substation": None, "params": {k: v for k, v in raw.items() if not k.startswith("_")}})
    for sub in data.get("substations", []):
        for raw in sub.get("devices", []):
            nodes.append({"id": raw["id"], "type": raw["type"],
                          "label": raw.get("label", raw["id"]),
                          "substation": sub["id"], "substation_name": subs_index.get(sub["id"]),
                          "params": {k: v for k, v in raw.items() if not k.startswith("_")}})
    for lk in data.get("links", []):
        links_out.append({"id": lk.get("id"), "from": lk["from"], "to": lk["to"], "kind": lk["kind"],
                          "state": lk.get("state"), "params": {k: v for k, v in lk.items()
                                                               if k not in ("from", "to", "kind", "id", "state")}})
    for n in nodes:
        t, p = n["type"], n["params"]
        if t == "Load":
            comps.append({"id": n["id"], "metric": "power", "rated_kw": p.get("peak_kw"),
                          "profile": p.get("profile"), "pf": p.get("power_factor", 0.85)})
        elif t == "EVCharger":
            comps.append({"id": n["id"], "metric": "power", "rated_kw": p.get("total_power_kw"),
                          "profile": "commercial", "pf": 0.9})
        elif t == "PV":
            comps.append({"id": n["id"], "metric": "power", "rated_kw": p.get("capacity_kwp"),
                          "profile": "pv", "pf": 1.0})
        elif t == "BESS":
            comps.append({"id": n["id"], "metric": "power", "rated_kw": p.get("power_kw"),
                          "profile": "bess", "pf": 0.95})
        elif t == "Bus":
            buses.append({"id": n["id"], "vnom_kv": float(str(p.get("voltage_level", "0.4kV")).replace("kV", ""))})
        elif t == "Transformer":
            comps.append({"id": n["id"], "metric": "loading", "rated_kva": p.get("capacity_kva"),
                          "profile": None, "pf": 0.85})
    return {
        "api": "parkdsl-web/1",
        "source": source,
        "park": {"id": park["id"], "name": park["name"], "description": park.get("description", ""),
                 "tier": park["tier"], "contract_capacity_kw": park.get("contract_capacity_kw"),
                 "incoming_voltage": park.get("incoming_voltage", "10kV"),
                 "seed": park.get("seed", 42)},
        "substations": [{"id": s["id"], "name": s.get("name", s["id"])} for s in data.get("substations", [])],
        "nodes": nodes,
        "links": links_out,
        "telemetry": {"seed": park.get("seed", 42), "step_sec": SPEC["telemetry"]["step_sec"],
                      "noise_amplitude": SPEC["telemetry"]["noise_amplitude"],
                      "wander_amplitude": SPEC["telemetry"]["wander_amplitude"],
                      "wander_period_sec": SPEC["telemetry"]["wander_period_sec"],
                      "voltage_drop_factor": SPEC["telemetry"]["voltage_drop_factor"],
                      "voltage_noise": SPEC["telemetry"]["voltage_noise"],
                      "shapes": SPEC["telemetry"]["shapes"],
                      "components": comps, "buses": buses},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="validate.py", description="ParkDSL v1 校验/导出")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("files", nargs="+")
    v.add_argument("--json", action="store_true")
    e = sub.add_parser("export")
    e.add_argument("file")
    e.add_argument("-o", "--out", required=True)
    s = sub.add_parser("summary")
    s.add_argument("files", nargs="+")
    args = ap.parse_args(argv)

    if args.cmd in ("validate", "summary"):
        rc = 0
        report = []
        for f in args.files:
            p = Path(f)
            if not p.exists():
                print(f"[E-IO] {f}: 文件不存在")
                rc = 2
                continue
            data, errs = load_dsl(p)
            if data is not None:
                errs = validate_dsl(data, origin=str(p))
            if args.cmd == "summary" and data is not None and not errs:
                park = data["park"]
                subs = data.get("substations", [])
                devs = [d for s in subs for d in s.get("devices", [])] + list(data.get("grid_inlets", []))
                stats = {"substations": len(subs),
                         "transformers": sum(1 for d in devs if d.get("type") == "Transformer"),
                         "loads": sum(1 for d in devs if d.get("type") == "Load"),
                         "der": sum(1 for d in devs if d.get("type") in DER_TYPES)}
                line = f"{p.name}: tier={park['tier']} name={park['name']} {stats}"
                report.append(line)
                print(line)
            if errs:
                rc = max(rc, 1)
                print(f"{p}: FAIL ({len(errs)} 错误)")
                for er in errs:
                    print("  " + er.line())
            else:
                if args.cmd == "validate":
                    print(f"{p}: PARK-DSL VALIDATION PASS")
            if getattr(args, "json", False):
                report.append({"file": str(p), "ok": not errs,
                               "errors": [e.line() for e in errs]})
        if getattr(args, "json", False):
            print(json.dumps({"pass": rc == 0, "results": report}, ensure_ascii=False))
        return rc

    # export
    p = Path(args.file)
    if not p.exists():
        print(f"[E-IO] {p}: 文件不存在")
        return 2
    data, errs = load_dsl(p)
    if data is not None:
        errs = validate_dsl(data, origin=str(p))
    if errs:
        print(f"{p}: 拒绝导出（校验未通过 {len(errs)} 错误）")
        for er in errs:
            print("  " + er.line())
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build_export(data, str(p)), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"export {p.name} -> {out} OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
