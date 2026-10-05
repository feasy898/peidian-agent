# -*- coding: utf-8 -*-
"""m5_simulation.env · SimEnv：设备状态+量测+电价+日历（ParkInstance 按名加载）。

- ``load_scenario(spec) -> SimEnv``（01 §3.5 冻结 API）：按
  ``ScenarioSpec.environment.park_instance`` 名字加载园区实例（ADDENDUM §D：
  默认 ``ontology/``，``PARK_INSTANCE_PATH``（";" 分隔）追加搜索目录）；
- SimEnv 为每场景独享的可变状态容器（SPEC-M5-07 场景隔离）：
  设备运行态（深拷贝自实例）、量测库（含 stale 标志与中断区间）、
  告警表、故障注入窗口、事件缓冲；
- 事件统一以 ``contracts.EventRecord`` 落 SIM 时间线（occurred_at=BUSINESS 读数，
  ADDENDUM §C：price.period_changed / demand.month_rolled 同口径）。
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from contracts import EventRecord, EventType, ScenarioSpec

from m4_semantic.loader import LoadedOntology, load_ontology

from .clock import ClockHub, iso_z, parse_utc

__all__ = [
    "ENV_TICK",
    "SimEnv",
    "DeviceRuntime",
    "MeasurementCell",
    "load_scenario",
    "canonical_spec_dict",
    "spec_manifest_hash",
    "parse_time_ref",
    "default_seed",
]

#: ENV_TICK 哨兵：step() 的"环境节拍"动作（非 SimAction）
class _EnvTick:
    def __repr__(self) -> str:  # pragma: no cover
        return "ENV_TICK"


ENV_TICK = _EnvTick()

#: 缺省物理步长（15min，M5 §2 负荷模型口径）
DEFAULT_STEP_S = 900.0

#: 量测质量（封闭小词表：好/陈旧）
QUALITY_GOOD = "GOOD"
QUALITY_STALE = "STALE"

_REL_RE = re.compile(r"^(?:T\+|\+)(\d+(?:\.\d+)?)(ms|s|m|h)$", re.IGNORECASE)
_REL_UNIT_S = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def parse_time_ref(value: Any, clock_start: datetime) -> datetime:
    """ScenarioSpec 的 ``at`` 时间引用 → 绝对 UTC 时刻。

    契约（contracts.simulation.check_time_ref）接受非空字符串或 datetime；
    本引擎约定两种形态：
    - 绝对 UTC ISO-8601（``2026-09-15T11:00:00Z``）；
    - 场景相对时间（``+90m`` / ``T+1.5h`` / ``+45s`` / ``+30000ms``，自 clock_start 起）。
    """
    if isinstance(value, datetime):
        return parse_utc(value)
    text = str(value).strip()
    match = _REL_RE.match(text)
    if match:
        amount = float(match.group(1))
        unit = match.group(2).lower()
        return clock_start + timedelta(seconds=amount * _REL_UNIT_S[unit])
    return parse_utc(text)


def _normalize(value: Any) -> Any:
    """规格 dict 归一化：datetime → ISO 字符串（canonical hash 口径）。"""
    if isinstance(value, datetime):
        return iso_z(value)
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    return value


def canonical_spec_dict(spec: ScenarioSpec | Mapping) -> dict:
    """ScenarioSpec → 归一化 dict（排序稳定，可 hash/比对）。"""
    data = spec.to_dict() if isinstance(spec, ScenarioSpec) else dict(spec)
    return _normalize(data)


def spec_manifest_hash(spec: ScenarioSpec | Mapping) -> str:
    """ScenarioSpec 内容 hash（SimRunResult.manifest_hash，复现性绑定）。"""
    return hashlib.sha256(
        json.dumps(canonical_spec_dict(spec), ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def default_seed(manifest_hash: str) -> str:
    """缺省种子：由 manifest_hash 派生（同规格同种子 → 确定性重放）。

    契约 ScenarioSpec 十字段组无独立 seed 字段（01 §2.8）；
    SimRunResult.reproduction.seed 记录实际使用值；run_scenario(seed=...) 可显式覆盖。
    """
    return f"seed-{manifest_hash[:16]}"


# ---------------------------------------------------------------------------
# 运行态结构
# ---------------------------------------------------------------------------
@dataclass
class DeviceRuntime:
    """设备运行态（深拷贝自 ParkInstance，场景内可变）。"""

    id: str
    type: str
    attributes: dict
    state: str = "RUNNING"              # device_state 枚举字面量
    breaker_state: str | None = None    # Switchgear/BESS 等分合状态
    soc: float | None = None            # BESS 荷电状态（百分数）
    temp_drift_c: float = 0.0           # 事件叠加的温度漂移（度）
    thd_override: float | None = None   # 事件叠加的 THD 覆盖值

    def to_summary(self) -> dict:
        out = {"id": self.id, "type": self.type, "state": self.state}
        if self.breaker_state is not None:
            out["breaker_state"] = self.breaker_state
        if self.soc is not None:
            out["soc"] = round(self.soc, 3)
        return out


@dataclass
class MeasurementCell:
    """单个 (device, quantity) 量测单元（含质量与中断区间）。"""

    device: str
    quantity: str
    value: float
    unit: str
    ts: str                 # 最近一次有效更新的 BUSINESS 时刻（UTC ISO-8601）
    sim_elapsed_s: float
    quality: str = QUALITY_GOOD
    stale_since: str | None = None
    outage: dict | None = None   # {"from": ISO, "to": ISO|None, "from_s": float, "to_s": float|None}

    def to_dict(self) -> dict:
        out = {
            "device": self.device, "quantity": self.quantity,
            "value": round(self.value, 4), "unit": self.unit,
            "ts": self.ts, "sim_elapsed_s": self.sim_elapsed_s,
            "quality": self.quality, "stale": self.quality == QUALITY_STALE,
        }
        if self.stale_since is not None:
            out["stale_since"] = self.stale_since
        if self.outage is not None:
            out["outage"] = {k: v for k, v in self.outage.items() if v is not None}
        return out


@dataclass
class SimEnv:
    """仿真环境（每场景独享；SPEC-M5-07：并发场景互不影响）。"""

    spec: ScenarioSpec
    ontology: LoadedOntology                     # 只读共享（本体/规程阈值）
    park_id: str
    contract_capacity_kw: float | None
    clock: ClockHub
    rng: random.Random
    step_s: float
    devices: dict = field(default_factory=dict)          # id -> DeviceRuntime
    relations: list = field(default_factory=list)        # [[src, rel, dst], ...]
    measurements: dict = field(default_factory=dict)     # "device:quantity" -> MeasurementCell
    alarms: dict = field(default_factory=dict)           # alarm_id -> 告警记录
    load_overrides: dict = field(default_factory=dict)   # device -> {"kw": float, "until_s": float|None}
    outages: list = field(default_factory=list)          # 量测中断窗口（SENSING_OUTAGE）
    comm_losses: list = field(default_factory=list)      # 审批通道中断窗口（COMM_LOSS）
    artifacts: dict = field(default_factory=dict)        # 仿真侧产物标记（write.* 动作）
    load_curve: dict = field(default_factory=dict)       # {shape: [24], base_kw}
    demand_records: dict = field(default_factory=dict)   # "YYYY-MM" -> peak_kw（实例历史需量）
    price_schedule: dict = field(default_factory=dict)   # 实例电价时段表
    event_buffer: list = field(default_factory=list)     # 当前 step 产出的事件（EventRecord dict）
    event_log: list = field(default_factory=list)        # 全量事件历史（按序）
    model_params: dict = field(default_factory=dict)     # 物理模型常数（可覆盖，非告警阈值）
    pending_injections: list = field(default_factory=list)  # [{fault, due_s, done}]
    pending_events: list = field(default_factory=list)      # [{event, due_s, done}]
    switch_orders: dict = field(default_factory=dict)    # code -> {status, steps, devices, ...}
    work_orders: list = field(default_factory=list)      # 运行中工单
    granted_keys: set = field(default_factory=set)       # 已获审批的动作键（GRANT 后放行）
    chatter: dict = field(default_factory=dict)          # target -> {flips, debounce_s, final_state}
    storm_summary: dict = field(default_factory=dict)    # ALARM_STORM 聚合输出 {by_level, total}
    demand_window: dict = field(default_factory=dict)    # {month, peak_kw} 当月 15min 滑窗峰值
    operators: list = field(default_factory=list)        # 实例操作员（角色校验用）
    seed: str = ""
    run_id: str = "run-dev"
    trace_id: str = "trace-dev"
    _event_seq: int = 0
    _alarm_seq: int = 0

    # ------------------------------------------------ 事件与标识（确定性）
    def next_event_id(self) -> str:
        self._event_seq += 1
        return f"EVT-{self.run_id}-{self._event_seq:06d}"

    def next_alarm_id(self) -> str:
        self._alarm_seq += 1
        return f"AL-{self.run_id}-{self._alarm_seq:05d}"

    def iso_at(self, sim_elapsed_s: float, *, ms: bool = False) -> str:
        """SIM 时间 → BUSINESS ISO 时刻。"""
        moment = self.clock.clock_start + timedelta(seconds=sim_elapsed_s)
        if ms and moment.microsecond:
            return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"
        return iso_z(moment)

    def emit(self, event_type: EventType | str, subject: str, payload: dict,
             sim_elapsed_s: float) -> dict:
        """落一条 SIM 时间线事件（contracts.EventRecord 校验通过才入列）。"""
        record = EventRecord.from_dict({
            "event_id": self.next_event_id(),
            "type": EventType(event_type).value,
            "subject": subject,
            "payload": payload,
            "occurred_at": self.iso_at(sim_elapsed_s, ms=True),
            "trace_id": self.trace_id,
            "producer": "M5",
        })
        self.event_buffer.append(record.to_dict())
        self.event_log.append(record.to_dict())
        return record.to_dict()

    # ------------------------------------------------ 场景隔离（SPEC-M5-07）
    def deep_copy(self) -> "SimEnv":
        """深拷贝环境（本体快照只读共享；可变状态逐项复制）。

        并发 run_scenario 各持独立 env；对副本的任何变更不影响原环境。
        """
        import copy as _copy

        clone = SimEnv(
            spec=self.spec,
            ontology=self.ontology,
            park_id=self.park_id,
            contract_capacity_kw=self.contract_capacity_kw,
            clock=_copy.deepcopy(self.clock),
            rng=_copy.deepcopy(self.rng),
            step_s=self.step_s,
            run_id=self.run_id,
            trace_id=self.trace_id,
            seed=self.seed,
            model_params=_copy.deepcopy(self.model_params),
        )
        clone.devices = _copy.deepcopy(self.devices)
        clone.relations = _copy.deepcopy(self.relations)
        clone.measurements = _copy.deepcopy(self.measurements)
        clone.alarms = _copy.deepcopy(self.alarms)
        clone.load_overrides = _copy.deepcopy(self.load_overrides)
        clone.outages = _copy.deepcopy(self.outages)
        clone.comm_losses = _copy.deepcopy(self.comm_losses)
        clone.artifacts = _copy.deepcopy(self.artifacts)
        clone.load_curve = _copy.deepcopy(self.load_curve)
        clone.demand_records = _copy.deepcopy(self.demand_records)
        clone.price_schedule = _copy.deepcopy(self.price_schedule)
        clone.pending_injections = _copy.deepcopy(self.pending_injections)
        clone.pending_events = _copy.deepcopy(self.pending_events)
        clone.switch_orders = _copy.deepcopy(self.switch_orders)
        clone.work_orders = _copy.deepcopy(self.work_orders)
        clone.chatter = _copy.deepcopy(self.chatter)
        clone.storm_summary = _copy.deepcopy(self.storm_summary)
        clone.demand_window = _copy.deepcopy(self.demand_window)
        clone.operators = _copy.deepcopy(self.operators)
        clone._event_seq = self._event_seq
        clone._alarm_seq = self._alarm_seq
        return clone

    # ------------------------------------------------ 遥信去抖（SPEC-M5-05）
    def debounced_state(self, target: str, debounce_s: float, *,
                        now_s: float | None = None) -> dict:
        """去抖后的遥信状态（agent 侧等待确认的观测接口）。

        - 窗口内仍有翻转 → ``chattering=True``（应等待去抖确认，不据此操作）；
        - 最近一次翻转距今 ≥ debounce_s → ``chattering=False``，状态稳定。
        """
        window = self.chatter.get(target)
        device = self.devices.get(target)
        if window is None or device is None:
            return {"device": target, "state": None, "chattering": False,
                    "flips_in_window": 0}
        now = self.clock.sim_elapsed_s if now_s is None else float(now_s)
        flips = window.get("flips") or []
        recent = [flip for flip in flips if now - flip["at_s"] < float(debounce_s)]
        last_at = flips[-1]["at_s"] if flips else 0.0
        stable = (not recent) and (now - last_at) >= float(debounce_s)
        return {
            "device": target,
            "state": window.get("final_state") if stable else
                     (flips[-1]["state"] if flips else device.breaker_state),
            "chattering": not stable,
            "flips_in_window": len(recent),
            "flips_total": len(flips),
            "debounce_s": float(debounce_s),
        }

    # ------------------------------------------------ 拓扑（关系数据驱动，任意同构实例通用）
    def devices_by_type(self, type_id: str) -> list:
        return [d for d in self.devices.values() if d.type == type_id]

    def relation(self, rel_id: str, *, src: str | None = None, dst: str | None = None) -> list:
        """按关系 ID（可选端点过滤）取三元组列表。"""
        return [
            [s, r, d] for s, r, d in self.relations
            if r == rel_id and (src is None or s == src) and (dst is None or d == dst)
        ]

    def upstream_transformers(self, feeder_id: str) -> list:
        """馈线的上游变压器：[TX, upstream_of, feeder]。"""
        return [s for s, _r, d in self.relation("upstream_of", dst=feeder_id)
                if s in self.devices and self.devices[s].type == "Transformer"]

    def attached_circuits(self, node_id: str) -> list:
        """挂接在馈线/变压器下的回路：[Circuit, part_of, node]。"""
        return [s for s, _r, d in self.relation("part_of", dst=node_id)
                if s in self.devices and self.devices[s].type == "Circuit"]

    # ------------------------------------------------ 量测存取
    @staticmethod
    def measurement_key(device: str, quantity: str) -> str:
        return f"{device}:{quantity}"

    def write_measurement(self, device: str, quantity: str, value: float, unit: str,
                          sim_elapsed_s: float) -> MeasurementCell:
        """写入量测（若处于中断窗口 → 保持旧值并标记 STALE，不伪造新读数）。"""
        key = f"{device}:{quantity}"
        outage = self.active_outage(device, sim_elapsed_s)
        cell = self.measurements.get(key)
        if outage is not None:
            if cell is None:
                cell = MeasurementCell(device, quantity, value, unit, self.iso_at(sim_elapsed_s),
                                        sim_elapsed_s)
                self.measurements[key] = cell
            cell.quality = QUALITY_STALE
            cell.stale_since = cell.stale_since or outage["from"]
            cell.outage = outage
            return cell
        if cell is None:
            cell = MeasurementCell(device, quantity, value, unit, self.iso_at(sim_elapsed_s),
                                    sim_elapsed_s)
            self.measurements[key] = cell
        else:
            was_stale = cell.quality == QUALITY_STALE
            cell.value = value
            cell.ts = self.iso_at(sim_elapsed_s)
            cell.sim_elapsed_s = sim_elapsed_s
            cell.quality = QUALITY_GOOD
            cell.stale_since = None
            cell.outage = None
            if was_stale:
                # 中断恢复：量测刷新（恢复点可回读，不再沿用旧值）
                self.emit(EventType.MEASUREMENT_UPDATED, device,
                          {"quantity": quantity, "quality": QUALITY_GOOD, "recovered": True},
                          sim_elapsed_s)
        return cell

    def read_measurement(self, device: str, quantity: str) -> dict | None:
        cell = self.measurements.get(f"{device}:{quantity}")
        return None if cell is None else cell.to_dict()

    def measurement_snapshot(self, device: str | None = None) -> list:
        cells = [c.to_dict() for c in self.measurements.values()
                 if device is None or c.device == device]
        return sorted(cells, key=lambda c: (c["device"], c["quantity"]))

    # ------------------------------------------------ 故障窗口查询
    def active_outage(self, target: str, sim_elapsed_s: float) -> dict | None:
        """目标设备当前是否处于量测中断窗口（返回窗口描述或 None）。"""
        for outage in self.outages:
            if outage["target"] != target:
                continue
            start, end = outage["from_s"], outage["to_s"]
            if start <= sim_elapsed_s and (end is None or sim_elapsed_s < end):
                return outage
        return None

    def sensing_available(self, target: str, sim_elapsed_s: float) -> bool:
        return self.active_outage(target, sim_elapsed_s) is None

    def approval_channel_open(self, sim_elapsed_s: float) -> bool:
        """审批通道是否可用（COMM_LOSS 窗口内不可用）。"""
        for loss in self.comm_losses:
            start, end = loss["from_s"], loss["to_s"]
            if start <= sim_elapsed_s and (end is None or sim_elapsed_s < end):
                return False
        return True

    # ------------------------------------------------ 设备状态
    def set_device_state(self, device_id: str, state: str, sim_elapsed_s: float, *,
                         reason: str) -> None:
        device = self.devices.get(device_id)
        if device is None or device.state == state:
            return
        previous = device.state
        device.state = state
        self.emit(EventType.GRID_EVENT, device_id,
                  {"kind": "device_state", "from": previous, "to": state, "reason": reason},
                  sim_elapsed_s)

    def set_breaker(self, device_id: str, breaker_state: str, sim_elapsed_s: float, *,
                    reason: str) -> None:
        device = self.devices.get(device_id)
        if device is None:
            return
        previous = device.breaker_state
        device.breaker_state = breaker_state
        self.emit(EventType.MEASUREMENT_UPDATED, device_id,
                  {"quantity": "breaker_state", "from": previous, "to": breaker_state,
                   "reason": reason},
                  sim_elapsed_s)

    # ------------------------------------------------ 终态快照
    def state_final(self) -> dict:
        return {
            "park_id": self.park_id,
            "business_at": iso_z(self.clock.business_now()),
            "sim_elapsed_s": self.clock.sim_elapsed_s,
            "devices": {d.id: d.to_summary() for d in self.devices.values()},
            "active_alarms": sorted(
                a["alarm_id"] for a in self.alarms.values() if a["cleared_at"] is None
            ),
            "alarms_total": len(self.alarms),
            "switch_orders": {
                code: {"status": order.get("status"),
                       "devices": order.get("devices", []),
                       "issuer": order.get("issuer")}
                for code, order in self.switch_orders.items()
            },
            "breakers": {d.id: d.breaker_state for d in self.devices.values()
                         if d.breaker_state is not None},
            "storm_summary": dict(self.storm_summary),
            "demand_window": dict(self.demand_window),
            "load_overrides": {k: v.get("kw") for k, v in self.load_overrides.items()
                               if v.get("until_s") is None or v["until_s"] > self.clock.sim_elapsed_s},
        }


# ---------------------------------------------------------------------------
# load_scenario（01 §3.5 冻结 API）
# ---------------------------------------------------------------------------
_SECTIONS_SKIP = ("park", "relations", "operators", "price_schedule", "meta")


def load_scenario(
    spec: ScenarioSpec | Mapping,
    *,
    seed: str | None = None,
    repo_root: Path | str | None = None,
    model_params: Mapping | None = None,
    step_s: float = DEFAULT_STEP_S,
) -> SimEnv:
    """装载场景：按名加载园区实例 → 构建独享 SimEnv（SPEC-M5-03/07）。

    - 实例解析走 ADDENDUM §D（ontology/ 默认 + PARK_INSTANCE_PATH 追加）；
    - 规程阈值经 ``load_ontology`` 一并装载（SPEC-M5-08：判据同源，无硬编码）；
    - 环境可变状态全部深拷贝/重建，本体快照只读共享。
    """
    if not isinstance(spec, ScenarioSpec):
        spec = ScenarioSpec.from_dict(spec)

    manifest = spec_manifest_hash(spec)
    run_id = f"run-{manifest[:16]}"
    env_name = spec.environment.park_instance
    loaded = load_ontology(instance=env_name, repo_root=repo_root, use_cache=False)
    instance = loaded.instance
    if instance is None:
        raise ValueError(f"园区实例未加载: {env_name!r}")

    clock_start = parse_utc(spec.environment.clock_start)
    hub = ClockHub(clock_start, speed=spec.environment.speed)
    effective_seed = seed or default_seed(manifest)

    park_attrs = instance.node(instance.park_id)["attributes"]
    contract_capacity = park_attrs.get("contract_capacity_kw")

    env = SimEnv(
        spec=spec,
        ontology=loaded,
        park_id=instance.park_id,
        contract_capacity_kw=float(contract_capacity) if contract_capacity else None,
        clock=hub,
        rng=random.Random(effective_seed),
        step_s=float(step_s),
        relations=[list(r) for r in instance.relations],
        run_id=run_id,
        trace_id=f"trace-{run_id}",
        seed=effective_seed,
        model_params=dict(model_params or {}),
    )

    # 设备运行态：深拷贝实例属性（场景内可变）
    import copy as _copy

    for node_id, node in instance.nodes.items():
        ntype = node.get("type")
        if ntype in ("Park", "SubstationRoom", "Operator", "PriceSchedule"):
            continue
        attrs = _copy.deepcopy(node.get("attributes") or {})
        breaker = attrs.pop("breaker_state", None)
        soc = attrs.pop("soc", None)
        env.devices[node_id] = DeviceRuntime(
            id=node_id,
            type=str(ntype),
            attributes=attrs,
            breaker_state=str(breaker) if breaker is not None else None,
            soc=float(soc) if soc is not None else None,
        )

    # 电价时段表（实例数据驱动；缺省无峰谷）
    schedule_node = instance.node(str((instance.data.get("price_schedule") or {}).get("id", ""))) \
        if isinstance(instance.data.get("price_schedule"), Mapping) else None
    if schedule_node is not None:
        env.price_schedule = _copy.deepcopy(schedule_node["attributes"])

    # 负荷日形状与历史需量：通用节扫描（load_curve_* / demand_YYYY_MM）
    for key, value in (instance.data or {}).items():
        if key.startswith("load_curve") and isinstance(value, Mapping) and value.get("shape"):
            env.load_curve = _copy.deepcopy(dict(value))
        match = re.match(r"^demand_(\d{4})_(\d{2})$", key)
        if match and isinstance(value, Mapping) and value.get("peak_kw") is not None:
            env.demand_records[f"{match.group(1)}-{match.group(2)}"] = float(value["peak_kw"])

    # 操作员（角色校验：SAFE-ISSUE-HUMAN 签发人必须是人员）
    env.operators = _copy.deepcopy(list(instance.data.get("operators") or []))

    # 当月需量滑窗初值：起点月份有历史记录则继承，否则从 0 起算
    start_month = clock_start.strftime("%Y-%m")
    env.demand_window = {
        "month": start_month,
        "peak_kw": env.demand_records.get(start_month, 0.0),
    }

    # 计划注入与环境事件：at → 仿真秒（due_s），由 advance 按计划触发（SPEC-M5-05）
    for fault in spec.environment.injections:
        due = parse_time_ref(fault.at, clock_start)
        env.pending_injections.append({
            "fault": {"type": fault.type, "target": fault.target,
                      "params": dict(fault.params or {})},
            "due_s": (due - clock_start).total_seconds(),
            "done": False,
        })
    for event in spec.events:
        due = parse_time_ref(event.at, clock_start)
        env.pending_events.append({
            "event": {"type": event.type, "subject": event.subject,
                      "params": dict(event.params or {})},
            "due_s": (due - clock_start).total_seconds(),
            "done": False,
        })

    return env
