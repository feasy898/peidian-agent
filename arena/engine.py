# -*- coding: utf-8 -*-
"""arena.engine · 练习场编排层（TASK.md §2.4 D-1..D-3）。

职责：把一份 ParkDSL v1.1 文档（拓扑 + faults 绑定 + calendar 业务日历 + scenario
倍速场景）跑成一次完整模拟——

    DSL 校验 → parkdsl-web/1 导出 → fault.Topology（park_adapter）→ fault.Engine
    → 注入计划（四步留痕第一步）→ 自适应步长推进（时间快速推移）→ 业务日历事件
    → agent 反应 / 人工处置（人机对比）→ recorder 落盘 → eval 摘要。

边界（契约 §4 / TASK.md）：全替身仿真，不出现任何真实电力系统接口；被测的是
决策行为。LLM 不在此层（model gateway 收编后在 agent 侧注入）。

与 fault/ 的关系：fault.Engine 是**唯一注入引擎权威**（模块图 #14）；本层只做
编排、日历与记录，不改引擎语义。
"""
from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # 允许 python arena/run_scenario.py 直接运行
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

import dsl.validate as dslv  # noqa: E402
from fault.detect import Criterion  # noqa: E402
from fault.dsl import FAULT_TYPES  # noqa: E402
from fault.engine import Engine  # noqa: E402
from fault.dsl import FaultRejected  # noqa: E402
from fault.park_adapter import park_to_topology  # noqa: E402
from arena.faultlib import FaultLibError, load_fault_library  # noqa: E402

__all__ = ["ArenaEngine", "ScenarioRejected", "engine_type_of"]

# DSL kind → fault 引擎类型。规则：kind 大写即引擎类型；唯一别名 overload→TX_OVERLOAD
# （变压器重过载的引擎原生类型）。最终以 fault.dsl.FAULT_TYPES 注册表零信任校验。
KIND_ALIAS = {"overload": "TX_OVERLOAD"}


def engine_type_of(kind: str) -> str | None:
    etype = KIND_ALIAS.get(kind, str(kind).upper())
    return etype if etype in FAULT_TYPES else None


# DSL faults 节 severity → 检测器异常级别
_SEV_MAP = {"info": "P2", "warn": "P2", "alarm": "P0", "accident": "P0"}

DEFAULT_CLOCK_START = "2026-10-05T00:00:00Z"  # 业务日历推导起点（周一）
_HMS = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")


class ScenarioRejected(Exception):
    """场景/注入被拒（DSL 校验失败或注入越界）。reasons 逐条人读。"""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


def _hms_to_s(value: Any) -> int:
    m = _HMS.match(str(value or ""))
    if not m:
        return 0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60


@dataclass
class InjectionRecord:
    """一次注入的 DSL→引擎映射结果（四步留痕的账本）。"""

    fault_id: str
    kind: str
    engine_type: str | None
    target: str | None
    at_sim_s: float
    status: str            # planned | rejected
    reasons: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    """一次 arena 运行的 eval 摘要（recorder 落盘 + 收敛统计的输入）。"""

    run_id: str
    park_id: str
    seed: int
    agent_enabled: bool
    duration_sim_s: float
    sim_s_final: float
    injections: dict[str, Any]
    calendar_events_fired: int
    anomalies: dict[str, int]
    gateway: dict[str, int]
    latency: dict[str, list[float]]
    events_total: int
    paths: dict[str, str]

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id, "park_id": self.park_id, "seed": self.seed,
            "agent_enabled": self.agent_enabled,
            "duration_sim_s": self.duration_sim_s,
            "sim_s_final": round(self.sim_s_final, 3),
            "injections": self.injections,
            "calendar_events_fired": self.calendar_events_fired,
            "anomalies": self.anomalies,
            "gateway": self.gateway,
            "latency": self.latency,
            "events_total": self.events_total,
            "paths": self.paths,
        }


class ArenaEngine:
    """一份 DSL 场景 = 一次可复现模拟（同 seed 同结果，recorder 留完整证据链）。"""

    def __init__(self, config: dict, *, seed: int | None = None,
                 agent_enabled: bool | None = None, run_id: str | None = None,
                 runs_root: Path | str | None = None,
                 idle_dt: float = 60.0, active_dt: float = 1.0) -> None:
        errs = dslv.validate_dsl(config, origin="<scenario>")
        if errs:
            raise ScenarioRejected([e.line() for e in errs])
        self.config = config
        self.park = config["park"]
        self.scenario = config.get("scenario") or {}
        self.seed = int(seed if seed is not None else self.scenario.get("seed", 42))
        if agent_enabled is None:
            agent_enabled = bool((self.scenario.get("agent") or {}).get("enabled", True))
        self.agent_enabled = bool(agent_enabled)
        self.idle_dt, self.active_dt = float(idle_dt), float(active_dt)

        export = dslv.build_export(config, "<scenario>")
        self.export = export
        self.topo = park_to_topology(export)
        try:
            self.faultlib = load_fault_library()
        except FaultLibError as exc:
            raise ScenarioRejected([f"故障库加载失败: {exc}"]) from exc
        self.engine = Engine(topo=self.topo, seed=self.seed, agent_enabled=self.agent_enabled,
                             criteria=self.faultlib.criteria,
                             target_criteria=self._target_criteria(config))

        self.faults: dict[str, dict] = {
            f["id"]: f for f in (config.get("faults") or []) if isinstance(f, dict) and f.get("id")
        }
        self.injection_records: list[InjectionRecord] = []
        self._plan_injections()

        raw_start = self.scenario.get("clock_start") or DEFAULT_CLOCK_START
        try:
            self.clock_start = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
        except ValueError:
            self.clock_start = datetime.fromisoformat(DEFAULT_CLOCK_START.replace("Z", "+00:00"))
        self.calendar_times = self._schedule_calendar()

        self.run_id = run_id or f"{self.park.get('id', 'PARK')}-s{self.seed}"
        root = Path(runs_root) if runs_root is not None else ROOT / "runs" / "arena"
        self.run_dir = root / self.run_id
        self._fired_calendar: list[tuple[float, dict]] = []
        self._snapshots: list[dict] = []
        # 人工介入（人机对比）：submit_human 投递，(sim_s, action) 到点执行；
        # pause_hook(anoms) 在 agent 关闭且新异常出现时调用（CLI 借它实现交互暂停）。
        self._human_queue: list[tuple[float, dict]] = []
        self.pause_hook: Any = None
        self.human_log: list[dict] = []

    # ================================================================ 注入计划（D-2 第一步）
    def _target_criteria(self, config: dict) -> dict:
        """DSL faults 节 detection → 每设备判据（element_id, metric）→ Criterion。

        这是园区**配置的监控阈值**（同真实 SCADA 告警定值，可分压级/分类型），
        不是注入计划——检测器据此判定，诚实性不受影响（见 fault.detect.Detector）。
        """
        out: dict[tuple[str, str], Criterion] = {}
        for entry in config.get("faults") or []:
            if not isinstance(entry, dict):
                continue
            target, det = entry.get("target"), entry.get("detection")
            if not isinstance(target, str) or not isinstance(det, dict):
                continue
            if any(det.get(k) in (None, "") for k in
                   ("metric", "comparator", "threshold", "duration_sec")):
                continue
            try:
                threshold: float | str = float(det["threshold"])
            except (TypeError, ValueError):
                threshold = str(det["threshold"])
            out[(target, str(det["metric"]))] = Criterion(
                comparator=str(det["comparator"]), threshold=threshold,
                duration_s=float(det["duration_sec"]),
                severity=_SEV_MAP.get(str(entry.get("severity", "warn")), "P2"),
                source=f"园区 DSL faults 节配置 {entry.get('id', '')}"
                       + (f"；criteria_ref={entry['criteria_ref']}"
                          if entry.get("criteria_ref") else ""),
            )
        return out

    def _plan_injections(self) -> None:
        for i, inj in enumerate(self.scenario.get("injections") or [], start=1):
            if not isinstance(inj, dict):
                self.injection_records.append(InjectionRecord(
                    fault_id=f"<?{i}>", kind="?", engine_type=None, target=None,
                    at_sim_s=0.0, status="rejected", reasons=["注入条目必须是映射"]))
                continue
            fid = str(inj.get("fault", ""))
            entry = self.faults.get(fid)
            if entry is None:
                self.injection_records.append(InjectionRecord(
                    fault_id=fid or f"<?{i}>", kind="?", engine_type=None, target=None,
                    at_sim_s=float(inj.get("at_sim_s", 0) or 0), status="rejected",
                    reasons=[f"注入引用的故障条目 {fid!r} 未在 faults 节声明"]))
                continue
            kind = str(entry.get("kind", ""))
            etype = engine_type_of(kind)
            target = inj.get("target") or entry.get("target")
            at_s = float(inj.get("at_sim_s", 0) or 0)
            if etype is None:
                self.injection_records.append(InjectionRecord(
                    fault_id=fid, kind=kind, engine_type=None, target=target,
                    at_sim_s=at_s, status="rejected",
                    reasons=[f"kind {kind!r} 未在 fault 引擎类型注册表（FAULT_TYPES）内"]))
                continue
            if target is None:
                self.injection_records.append(InjectionRecord(
                    fault_id=fid, kind=kind, engine_type=etype, target=None,
                    at_sim_s=at_s, status="rejected",
                    reasons=["该故障类型需要 target（faults 节或 injections 条目绑定元件）"]))
                continue
            raw = {"type": etype, "target": str(target), "at_s": at_s,
                   "params": dict(inj.get("params") or {}),
                   "fault_id": fid,
                   "note": self._note_with_provenance(entry, inj)}
            try:
                self.engine.inject(raw)
            except FaultRejected as exc:
                self.injection_records.append(InjectionRecord(
                    fault_id=fid, kind=kind, engine_type=etype, target=str(target),
                    at_sim_s=at_s, status="rejected", reasons=list(exc.reasons)))
                continue
            self.injection_records.append(InjectionRecord(
                fault_id=fid, kind=kind, engine_type=etype, target=str(target),
                at_sim_s=at_s, status="planned"))

    @staticmethod
    def _note_with_provenance(entry: dict, inj: dict) -> str:
        """判据出处随 fault.planned 事件留痕（专家审查的证据链）。"""
        bits = [str(entry.get("note") or inj.get("note") or "").strip()]
        if entry.get("criteria_ref"):
            bits.append(f"criteria_ref={entry['criteria_ref']}")
        if entry.get("detection"):
            det = entry["detection"]
            bits.append(f"detection={det.get('metric')}{det.get('comparator')}"
                        f"{det.get('threshold')}")
        return " | ".join(b for b in bits if b)

    # ================================================================ 业务日历（正常营业与管理变化）
    def _schedule_calendar(self) -> list[tuple[float, dict]]:
        dur = float(self.scenario.get("duration_sim_s", 0) or 0)
        times: list[tuple[float, dict]] = []
        cal = self.config.get("calendar") or {}
        for ev in cal.get("events") or []:
            if not isinstance(ev, dict):
                continue
            at_s = _hms_to_s(ev.get("at", "00:00"))
            etype = ev.get("type")
            every = ev.get("every_days")
            if etype == "shift_handover":
                for t in (ev.get("params") or {}).get("times") or []:
                    base = _hms_to_s(t)
                    days = int(dur // 86400) + 1
                    for d in range(days):
                        times.append((d * 86400 + base, ev))
            elif isinstance(every, int) and every >= 1:
                k = 0
                while True:
                    t = k * every * 86400 + at_s
                    if t > dur:
                        break
                    times.append((t, ev))
                    k += 1
            else:
                times.append((at_s, ev))
        return sorted(times, key=lambda x: x[0])

    def _business_iso(self, sim_s: float) -> str:
        t = self.clock_start.astimezone(timezone.utc) + _td(sim_s)
        return t.strftime("%Y-%m-%dT%H:%M:%SZ")

    # ================================================================ 运行（自适应步长 = 时间快速推移）
    def _snap(self) -> dict:
        """state_snapshot 的 JSON 安全版（anomalies 的 (hint,target) tuple 键 → "hint@target"）。"""
        snap = self.engine.state_snapshot()
        anomalies = snap.get("anomalies") or {}
        snap["anomalies"] = {f"{k[0]}@{k[1]}": v for k, v in anomalies.items()}
        return snap

    def run(self) -> RunResult:
        dur = float(self.scenario.get("duration_sim_s", 0) or 0)
        # 只排未来的日历事件（允许人工终止后二次进入 run 收口，不重放已触发事件）
        pending = [x for x in self.calendar_times if x[0] > self.engine.sim_s + 1e-9]
        inj_times = sorted(r.at_sim_s for r in self.injection_records if r.status == "planned")
        self.engine.set_agent_enabled(self.agent_enabled,
                                      note="arena run 开始" if self.agent_enabled
                                      else "arena run 开始（agent 关闭，人工模式）")
        steps = 0
        while self.engine.sim_s < dur - 1e-9:
            now = self.engine.sim_s
            nxt = dur
            if pending:
                nxt = min(nxt, pending[0][0])
            nxt_inj = next((t for t in inj_times if t > now + 1e-9), None)
            if nxt_inj is not None:
                nxt = min(nxt, nxt_inj)
            horizon = nxt - now
            busy = bool(self.engine.detector.active) or bool(self.engine.active_faults)
            dt = self.active_dt if (busy or horizon <= self.active_dt) else self.idle_dt
            dt = max(min(dt, horizon, dur - now), 1e-3)
            self.engine.dt = dt
            detected_before = len(self.engine.stream.to_list(channel="fault",
                                                             etype="fault.detected"))
            self.engine.tick()
            self._drain_human_queue()
            steps += 1
            while pending and pending[0][0] <= self.engine.sim_s + 1e-9:
                t, ev = pending.pop(0)
                self._fire_calendar_event(t, ev)
            if steps % 2000 == 0:
                self._snapshots.append({"sim_s": round(self.engine.sim_s, 3),
                                        "snapshot": self._snap()})
            # 人机对比交互：agent 关闭且本拍检出异常 → 暂停等人工（pause_hook）
            if self.pause_hook is not None and not self.agent_enabled:
                detected_now = len(self.engine.stream.to_list(
                    channel="fault", etype="fault.detected")) - detected_before
                if detected_now > 0:
                    self.pause_hook([a for a in self.engine.detector.active.values()
                                     if a.status == "active"])
        self._snapshots.append({"sim_s": round(self.engine.sim_s, 3),
                                "snapshot": self._snap()})
        return self._finalize()

    def _fire_calendar_event(self, t: float, ev: dict) -> None:
        etype = str(ev.get("type", "unknown"))
        self._fired_calendar.append((t, ev))
        self.engine.stream.append("ops", f"ops.{etype}", {
            "event_id": ev.get("id") or f"{etype}@{t:.0f}",
            "type": etype, "scheduled_sim_s": t,
            "business_at": self._business_iso(t),
            "params": ev.get("params") or {},
            "source": "arena.calendar",
        }, sim_s=self.engine.sim_s)

    # ================================================================ 人工操作（人机对比：同款执行器）
    def human_action(self, op: str, target: str, reason: str = "") -> dict:
        return self.engine.human_action({"op": op, "target": target, "reason": reason})

    def submit_human(self, action: dict, at_sim_s: float | None = None) -> None:
        """人机对比：投递一条人工动作/注入，到点（默认当前仿真秒）执行。"""
        self._human_queue.append(
            (self.engine.sim_s if at_sim_s is None else float(at_sim_s), dict(action)))
        self._human_queue.sort(key=lambda x: x[0])

    def _drain_human_queue(self) -> None:
        while self._human_queue and self._human_queue[0][0] <= self.engine.sim_s + 1e-9:
            _t, action = self._human_queue.pop(0)
            kind = action.get("op")
            if kind == "inject":
                out = self.manual_inject(str(action.get("fault_id", "")))
            elif kind in ("open", "close", "ack"):
                out = self.human_action(kind, str(action.get("target", "")),
                                        str(action.get("reason", "人工操作")))
            elif kind == "agent":
                on = str(action.get("value", "on")).lower() == "on"
                self.engine.set_agent_enabled(on, note="人工切换 agent 开关")
                self.agent_enabled = on
                out = {"ok": True, "agent_enabled": on}
            else:
                out = {"ok": False, "note": f"未知人工动作 {kind!r}"}
            out = dict(out)
            out["at_sim_s"] = round(self.engine.sim_s, 3)
            out["action"] = action
            self.human_log.append(out)
            self.engine.stream.append("control", "control.human_action", out,
                                      sim_s=self.engine.sim_s)

    def manual_inject(self, fault_id: str) -> dict:
        """人类体验模式：手动注入 faults 节中的故障（走同一条零信任路径）。"""
        entry = self.faults.get(fault_id)
        if entry is None:
            return {"ok": False, "rejected": True,
                    "reasons": [f"未知故障条目 {fault_id!r}（可用: {','.join(sorted(self.faults))}）"]}
        kind = str(entry.get("kind", ""))
        etype = engine_type_of(kind)
        target = entry.get("target")
        if etype is None or target is None:
            return {"ok": False, "rejected": True,
                    "reasons": [f"kind {kind!r} 未接入引擎或未绑定 target，拒绝注入"]}
        try:
            spec = self.engine.inject({
                "type": etype, "target": str(target),
                "at_s": self.engine.sim_s,
                "params": dict(entry.get("params") or {}),
                "fault_id": f"{fault_id}-manual",
                "note": self._note_with_provenance(entry, {}) + " | 人工注入"})
        except FaultRejected as exc:
            return {"ok": False, "rejected": True, "reasons": list(exc.reasons)}
        self.injection_records.append(InjectionRecord(
            fault_id=spec.fault_id, kind=kind, engine_type=etype, target=str(target),
            at_sim_s=spec.at_s, status="planned"))
        return {"ok": True, "fault_id": spec.fault_id, "type": etype, "target": str(target),
                "at_s": spec.at_s}

    # ================================================================ 记录与 eval
    def _finalize(self) -> RunResult:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        events_path = self.run_dir / "events.jsonl"
        self.engine.stream.write_jsonl(str(events_path))
        events = self.engine.stream.to_list()

        actions = [e for e in events if e.get("channel") == "ops"
                   and str(e.get("type", "")).startswith("action.")]
        rejected = [e for e in actions if e.get("type") == "action.rejected"]
        by_agent = [e for e in actions if (e.get("payload") or {}).get("by") == "agent"]
        by_human = [e for e in actions if (e.get("payload") or {}).get("by") == "human"]

        detected = [e for e in events if e.get("type") == "fault.detected"]
        cleared = [e for e in events if e.get("type") == "anomaly.cleared"]
        escalated = [e for e in events if e.get("type") == "control.escalated"]
        active_end = len(self.engine.detector.active)

        detect_lat, restore_lat = self._latencies(events)
        summary = {
            "anomalies": {
                "detected": len(detected),
                "cleared": len(cleared),
                "cleared_by_agent": sum(1 for e in cleared if (e.get("payload") or {}).get("by") == "agent"),
                "cleared_by_human": sum(1 for e in cleared if (e.get("payload") or {}).get("by") == "human"),
                "escalated": len(escalated),
                "active_at_end": active_end,
            },
            "gateway": {
                "actions_total": len(actions),
                "by_agent": len(by_agent),
                "by_human": len(by_human),
                "rejected": len(rejected),
            },
            "latency": {"detect": detect_lat, "restore": restore_lat},
        }

        (self.run_dir / "states.json").write_text(json.dumps(
            self._snapshots, ensure_ascii=False, indent=1), encoding="utf-8")
        (self.run_dir / "actions.json").write_text(json.dumps(
            actions, ensure_ascii=False, indent=1), encoding="utf-8")
        (self.run_dir / "scenario.yaml").write_text(
            yaml.safe_dump(self.config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        (self.run_dir / "meta.json").write_text(json.dumps({
            "run_id": self.run_id, "seed": self.seed, "agent_enabled": self.agent_enabled,
            "clock_start": self.clock_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "idle_dt": self.idle_dt, "active_dt": self.active_dt,
            "injection_records": [r.__dict__ for r in self.injection_records],
            "calendar_events_fired": len(self._fired_calendar),
            "human_actions": self.human_log,
        }, ensure_ascii=False, indent=1), encoding="utf-8")

        result = RunResult(
            run_id=self.run_id, park_id=str(self.park.get("id")), seed=self.seed,
            agent_enabled=self.agent_enabled,
            duration_sim_s=float(self.scenario.get("duration_sim_s", 0) or 0),
            sim_s_final=self.engine.sim_s,
            injections={
                "planned": sum(1 for r in self.injection_records if r.status == "planned"),
                "rejected": [{"fault_id": r.fault_id, "kind": r.kind, "reasons": r.reasons}
                             for r in self.injection_records if r.status == "rejected"],
            },
            calendar_events_fired=len(self._fired_calendar),
            anomalies=summary["anomalies"], gateway=summary["gateway"],
            latency=summary["latency"],
            events_total=len(events),
            paths={"run_dir": str(self.run_dir), "events": str(events_path)},
        )
        (self.run_dir / "eval.json").write_text(json.dumps(
            result.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        return result

    def _latencies(self, events: list[dict]) -> tuple[list[float], list[float]]:
        """检测时延 = injected→detected（同 target）；恢复时延 = detected→cleared。"""
        detect, restore = [], []
        open_by_target: dict[str, float] = {}
        for e in events:
            t = e.get("type")
            payload = e.get("payload") or {}
            sim_s = float(e.get("sim_s", 0) or 0)
            target = payload.get("target")
            if t == "fault.injected" and target:
                open_by_target.setdefault(str(target), sim_s)
            elif t == "fault.detected" and target:
                start = open_by_target.get(str(target))
                if start is not None and sim_s >= start:
                    detect.append(round(sim_s - start, 3))
            elif t == "anomaly.cleared" and target:
                start = open_by_target.pop(str(target), None)
                if start is not None:
                    restore.append(round(sim_s - start, 3))
        return sorted(detect), sorted(restore)


def _td(seconds: float):  # 延迟导入避免循环
    from datetime import timedelta
    return timedelta(seconds=seconds)


def load_scenario(path: Path | str) -> dict:
    """读 DSL 场景文件（YAML）。"""
    p = Path(path)
    if not p.exists():
        raise ScenarioRejected([f"场景文件不存在: {p}"])
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ScenarioRejected([f"YAML 解析失败: {exc}"])
    if not isinstance(data, dict):
        raise ScenarioRejected(["场景文件顶层必须是映射"])
    return data
