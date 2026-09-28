# -*- coding: utf-8 -*-
"""m5_simulation.physics · 简化物理模型（specs/M5-simulation.md §2，显式精度边界）。

模型（规格原文逐条落实）：
- **负荷**：园区实例日形状曲线（load_curve.shape，24 点小时粒度）× 15 分钟线性插值
  × seed 控制的乘性扰动；
- **聚合**：回路级 P/Q → 馈线 → 变压器；变压器负载率 = 回路聚合有功 / 额定容量
  （规格口径为数值比，EVAL-M5-PHYS：1100kW / 1250kVA = 0.88）；
- **电压**：Bus 电压 = 标称 × (1 − 0.04 × 馈线负载率)（k=0.04 为规格给定配系数）；
- **BESS**：SOC 一阶积分（充放电功率 × dt / 容量），充放电受 SOC 上下限约束
  （上下限取自规程 PHYS-BESS-SOC 阈值，数据驱动非硬编码）；
- **精度边界**：不仿真暂态/谐波频谱/保护动作时序，这些以事件注入近似
  （injector.py）。

物理模型常数（非告警阈值；告警阈值一律来自 regulations/REG-TECH.yaml，
SPEC-M5-08）集中在 ``MODEL_DEFAULTS``，可经 ``model_params`` 逐场景覆盖。
"""
from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

from contracts import EventType

from .env import SimEnv

__all__ = ["MODEL_DEFAULTS", "PhysicsEngine", "interpolate_shape"]

#: 物理模型常数（规格给定或建模缺省；非告警阈值）
MODEL_DEFAULTS: dict[str, Any] = {
    "voltage_drop_k": 0.04,     # M5 §2：电压=标称×(1−k×馈线负载率)
    "power_factor": 0.92,       # 缺省功率因数（设备/回路属性可覆盖）
    "ambient_c": 25.0,          # 环境温度
    "tx_temp_rise_c": 55.0,     # 变压器满载温升 K（顶油温升类建模常数；
                                # temp = ambient + rise×load_rate + 事件漂移，
                                # 阈值 85℃ 在 REG-TECH PHYS-TX-TEMP，非代码）
    "thd_base": 0.03,           # THD 基线
    "thd_load_coeff": 0.01,     # THD 随负载率分量
    "noise_amplitude": 0.03,   # 负荷扰动幅度（±3%，seed 控制）
    "pv_peak_factor": 0.65,     # 光伏正午出力系数
    "pv_day_start_h": 7.0,      # 日出（小时）
    "pv_day_end_h": 18.0,       # 日落（小时）
    "soc_deadband": 0.5,        # SOC 触界吸附带（%），防积分抖动
}


def interpolate_shape(shape: list, hour_float: float) -> float:
    """24 点小时形状 → 15 分钟粒度线性插值（首尾环绕：23 点 ↔ 0 点）。"""
    if not shape:
        return 0.0
    if len(shape) == 1:
        return float(shape[0])
    h = hour_float % 24.0
    i0 = int(h)
    frac = h - i0
    i1 = (i0 + 1) % len(shape)
    return float(shape[i0]) * (1.0 - frac) + float(shape[i1]) * frac


class PhysicsEngine:
    """每步物理推进：负荷→DER→聚合→电压→BESS→温度/THD→量测落库。

    引擎自身无内部状态（全部状态在 SimEnv），保证同 env 重放确定性。
    """

    def __init__(self, model_params: dict | None = None) -> None:
        self.params = dict(MODEL_DEFAULTS)
        if model_params:
            self.params.update(model_params)

    # ---------------------------------------------------------------- 主入口
    def step(self, env: SimEnv, sim_elapsed_s: float) -> dict:
        """推进一个物理步（在 tick 的目标时刻 ``sim_elapsed_s`` 求值并落量测）。

        返回本步园区级摘要（观测快照的一部分）。
        """
        params = self.params
        moment = env.clock.clock_start + timedelta(seconds=sim_elapsed_s)
        hour = moment.hour + moment.minute / 60.0 + moment.second / 3600.0

        noise_amp = float(params["noise_amplitude"])
        noise = 1.0 + env.rng.uniform(-noise_amp, noise_amp) if noise_amp > 0 else 1.0

        # ---- 园区总负荷（日形状 × 插值 × 扰动）
        shape = (env.load_curve or {}).get("shape") or [0.0]
        base_kw = float((env.load_curve or {}).get("base_kw") or 0.0)
        park_gross_kw = base_kw * interpolate_shape(shape, hour) * noise

        # ---- PV 出力（白天钟形，夜 0；逐台落量测）
        pv_out_kw = 0.0
        for pv in env.devices_by_type("PV"):
            pv_device_out = self._pv_output(pv, hour, noise_amp, env)
            pv_out_kw += pv_device_out
            env.write_measurement(pv.id, "output_kw", pv_device_out, "kW", sim_elapsed_s)

        # ---- 环境传感（温湿度/局放；量测生成口径：模型常数 + seed 扰动）
        ambient_c = float(params["ambient_c"])
        for sensor in env.devices_by_type("TempHumiditySensor"):
            env.write_measurement(sensor.id, "temp_c",
                                  ambient_c + env.rng.uniform(-1.0, 1.0), "degC",
                                  sim_elapsed_s)
            env.write_measurement(sensor.id, "humidity_pct",
                                  55.0 + env.rng.uniform(-5.0, 5.0), "percent",
                                  sim_elapsed_s)
        for sensor in env.devices_by_type("PDSensor"):
            env.write_measurement(sensor.id, "pd_pc", env.rng.uniform(30.0, 120.0), "pC",
                                  sim_elapsed_s)

        # ---- BESS 充放电（价段驱动）+ SOC 一阶积分
        bess_net_kw = 0.0
        for bess in env.devices_by_type("BESS"):
            bess_net_kw += self._bess_step(env, bess, sim_elapsed_s)

        park_net_kw = park_gross_kw - pv_out_kw + bess_net_kw

        # ---- 回路 → 馈线 → 变压器聚合
        tx_loads = self._aggregate_transformers(env, park_net_kw)
        feeder_loads = self._aggregate_feeders(env, tx_loads, park_net_kw, sim_elapsed_s)

        # ---- 电压近似（Bus：标称×(1−k×馈线负载率)）
        park_rate = (park_net_kw / env.contract_capacity_kw) if env.contract_capacity_kw else 0.0
        self._update_buses(env, feeder_loads, park_rate, sim_elapsed_s)

        # ---- 变压器量测与温度
        for tx_id, load in tx_loads.items():
            device = env.devices[tx_id]
            capacity = float(device.attributes.get("capacity_kva") or 0.0)
            load_rate = load["p_kw"] / capacity if capacity > 0 else 0.0
            env.write_measurement(tx_id, "p_kw", load["p_kw"], "kW", sim_elapsed_s)
            env.write_measurement(tx_id, "q_kvar", load["q_kvar"], "kvar", sim_elapsed_s)
            env.write_measurement(tx_id, "load_rate", load_rate, "ratio", sim_elapsed_s)
            temp_c = (float(params["ambient_c"])
                      + float(params["tx_temp_rise_c"]) * load_rate
                      + device.temp_drift_c)
            env.write_measurement(tx_id, "winding_temp_c", temp_c, "degC", sim_elapsed_s)

        # ---- 馈线功率因数（考核量测）
        for fd_id, load in feeder_loads.items():
            env.write_measurement(fd_id, "p_kw", load["p_kw"], "kW", sim_elapsed_s)
            env.write_measurement(fd_id, "power_factor", load["power_factor"], "ratio",
                                  sim_elapsed_s)

        return {
            "business_at": env.iso_at(sim_elapsed_s),
            "sim_elapsed_s": sim_elapsed_s,
            "park_gross_kw": round(park_gross_kw, 3),
            "pv_out_kw": round(pv_out_kw, 3),
            "bess_net_kw": round(bess_net_kw, 3),
            "park_net_kw": round(park_net_kw, 3),
            "transformer_load_rate": {
                k: round(v["p_kw"] / float(env.devices[k].attributes.get("capacity_kva") or 1.0), 4)
                for k, v in tx_loads.items()
            },
        }

    # ---------------------------------------------------------------- 子模型
    def _pv_output(self, pv, hour: float, noise_amp: float, env: SimEnv) -> float:
        capacity = float(pv.attributes.get("capacity_kwp") or 0.0)
        if capacity <= 0:
            return 0.0
        start, end = float(self.params["pv_day_start_h"]), float(self.params["pv_day_end_h"])
        if not (start <= hour <= end):
            return 0.0
        mid = (start + end) / 2.0
        half = max((end - start) / 2.0, 1e-9)
        solar = max(0.0, 1.0 - ((hour - mid) / half) ** 2)
        noise = 1.0 + env.rng.uniform(-noise_amp, noise_amp) if noise_amp > 0 else 1.0
        return capacity * float(self.params["pv_peak_factor"]) * solar * noise

    def _soc_bounds(self, env: SimEnv, bess) -> tuple[float, float]:
        """SOC 运行上下限：取规程 PHYS-BESS-SOC 阈值（数据驱动，SPEC-M5-08）。"""
        rule = env.ontology.regulations.get("REG-TECH", {}).get("rules") or []
        values = []
        for item in rule:
            if item.get("id") == "PHYS-BESS-SOC":
                for threshold in item.get("thresholds") or []:
                    if threshold.get("value") is not None:
                        values.append(float(threshold["value"]))
        if len(values) >= 2:
            return min(values) + float(self.params["soc_deadband"]), \
                   max(values) - float(self.params["soc_deadband"])
        # 规程缺失时的物理量程兜底（0-100 为百分数表示的物理范围，
        # 非运行限值阈值；此时告警引擎同样因无规则而不判定，SPEC-M5-08）
        return 0.0, 100.0

    def _bess_step(self, env: SimEnv, bess, sim_elapsed_s: float) -> float:
        """BESS 一阶积分：返回本步净充电功率（+充/−放，kW）。"""
        from .price_clock import period_at

        capacity = float(bess.attributes.get("capacity_kwh") or 0.0)
        power_kw = float(bess.attributes.get("power_kw") or 0.0)
        if capacity <= 0 or power_kw <= 0 or bess.soc is None:
            return 0.0
        if bess.state != "RUNNING":
            env.write_measurement(bess.id, "soc", bess.soc, "percent", sim_elapsed_s)
            env.write_measurement(bess.id, "p_kw", 0.0, "kW", sim_elapsed_s)
            return 0.0

        period = period_at(env, sim_elapsed_s)
        ptype = period["type"] if period else "FLAT"
        soc_min, soc_max = self._soc_bounds(env, bess)

        p = 0.0  # +充电 / −放电
        if ptype in ("VALLEY",) and bess.soc < soc_max:
            p = power_kw                       # 谷充
        elif ptype in ("PEAK", "SHARP") and bess.soc > soc_min:
            p = -power_kw                      # 峰放
        # 触界即停（充放电受 SOC 上下限约束）
        if p > 0 and bess.soc >= soc_max:
            p = 0.0
        if p < 0 and bess.soc <= soc_min:
            p = 0.0

        dt_h = env.step_s / 3600.0
        delta_soc = p * dt_h / capacity * 100.0
        new_soc = bess.soc + delta_soc
        # 积分截断到运行区间（一阶积分 + 上下限约束）
        new_soc = max(soc_min - float(self.params["soc_deadband"]),
                      min(soc_max + float(self.params["soc_deadband"]), new_soc))
        if soc_min <= new_soc <= soc_max:
            bess.soc = new_soc
        else:  # 触界：夹到界上并停功率
            bess.soc = max(soc_min, min(soc_max, new_soc))
            p = 0.0

        env.write_measurement(bess.id, "soc", bess.soc, "percent", sim_elapsed_s)
        env.write_measurement(bess.id, "p_kw", p, "kW", sim_elapsed_s)
        return p

    def _power_factor_of(self, env: SimEnv, node_id: str) -> float:
        device = env.devices.get(node_id)
        if device is not None and device.attributes.get("power_factor") is not None:
            return float(device.attributes["power_factor"])
        return float(self.params["power_factor"])

    def _aggregate_transformers(self, env: SimEnv, park_net_kw: float) -> dict:
        """回路 P/Q → 馈线 → 变压器聚合；负载率口径 = 聚合有功 / 容量。

        园区净负荷按运行中变压器容量分摊；``load.set`` 事件覆盖为绝对值
        （不受扰动影响，供精确判据使用，EVAL-M5-PHYS）。
        """
        # 运行中变压器按容量分摊园区净负荷（FAULT 设备不计）
        running = [d for d in env.devices_by_type("Transformer") if d.state == "RUNNING"]
        total_capacity = sum(float(d.attributes.get("capacity_kva") or 0.0) for d in running)

        loads: dict[str, dict] = {}
        for tx in env.devices_by_type("Transformer"):
            capacity = float(tx.attributes.get("capacity_kva") or 0.0)
            override = env.load_overrides.get(tx.id)
            # 事件覆盖（load.set）：绝对值，不受扰动（精确判据用）
            if override is not None and (override.get("until_s") is None
                                         or override["until_s"] > env.clock.sim_elapsed_s):
                p_kw = float(override["kw"])
            elif tx.state != "RUNNING" or total_capacity <= 0:
                p_kw = 0.0
            else:
                p_kw = park_net_kw * (capacity / total_capacity)
            pf = self._power_factor_of(env, tx.id)
            q_kvar = p_kw * math.tan(math.acos(min(max(pf, 0.05), 1.0)))
            loads[tx.id] = {"p_kw": p_kw, "q_kvar": q_kvar, "power_factor": pf,
                            "capacity_kva": capacity}
        return loads

    def _aggregate_feeders(self, env: SimEnv, tx_loads: dict, park_net_kw: float,
                           sim_elapsed_s: float) -> dict:
        """馈线聚合：Σ上游变压器有功；馈线容量缺省取 Σ上游变压器容量。"""
        feeders: dict[str, dict] = {}
        for feeder in env.devices_by_type("Feeder"):
            upstream = env.upstream_transformers(feeder.id)
            p_kw = sum(tx_loads.get(tx, {}).get("p_kw", 0.0) for tx in upstream)
            capacity = float(env.devices[feeder.id].attributes.get("capacity_kw") or 0.0)
            if capacity <= 0:
                capacity = sum(tx_loads.get(tx, {}).get("capacity_kva", 0.0) for tx in upstream)
            pf = self._power_factor_of(env, feeder.id)
            feeders[feeder.id] = {"p_kw": p_kw, "capacity_kw": capacity, "power_factor": pf,
                                  "upstream": upstream}
            env.write_measurement(feeder.id, "load_rate",
                                  p_kw / capacity if capacity > 0 else 0.0,
                                  "ratio", sim_elapsed_s)
        return feeders

    def _update_buses(self, env: SimEnv, feeder_loads: dict, park_rate: float,
                      sim_elapsed_s: float) -> None:
        """Bus 电压 = 标称 × (1 − k × 馈线负载率)；THD = 基线 + 负载分量（可事件覆盖）。"""
        k = float(self.params["voltage_drop_k"])
        for bus in env.devices_by_type("Bus"):
            nominal = _parse_voltage_level(bus.attributes.get("voltage_level"))
            # 该母线关联馈线的负载率（无馈线节点的实例退化为园区负载率）
            related = [f for f, load in feeder_loads.items()
                       if any(env.devices.get(tx) is not None and
                              _same_bus(env, tx, bus.id) for tx in load.get("upstream", []))]
            if related:
                rate = max(
                    (feeder_loads[f]["p_kw"] / feeder_loads[f]["capacity_kw"])
                    if feeder_loads[f]["capacity_kw"] > 0 else 0.0
                    for f in related
                )
            else:
                rate = park_rate
            u_kv = nominal * (1.0 - k * rate)
            deviation = abs(u_kv / nominal - 1.0) if nominal > 0 else 0.0
            env.write_measurement(bus.id, "u_kv", u_kv, "kV", sim_elapsed_s)
            env.write_measurement(bus.id, "voltage_deviation", deviation, "ratio", sim_elapsed_s)

            thd = bus.thd_override if bus.thd_override is not None else (
                float(self.params["thd_base"]) + float(self.params["thd_load_coeff"]) * rate
            )
            env.write_measurement(bus.id, "thd_u", thd, "ratio", sim_elapsed_s)


def _parse_voltage_level(value: Any) -> float:
    """'10kV'/'0.4kV'/10 → 标称千伏数。"""
    if value is None:
        return 10.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).lower().replace("kv", "").replace("v", "").strip()
    try:
        volt = float(text)
    except ValueError:
        return 10.0
    return volt / 1000.0 if volt > 1000 else volt


def _same_bus(env: SimEnv, tx_id: str, bus_id: str) -> bool:
    """变压器是否挂接在该母线（connected_to）。"""
    return any(d == bus_id for _s, _r, d in env.relation("connected_to", src=tx_id))
