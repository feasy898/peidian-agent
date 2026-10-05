# -*- coding: utf-8 -*-
"""m3_action.negative_test · write-path 负向测试件（SPEC-M3-11，CI 常驻）。

"只读"是测试结论，不是声明：对矩阵声明的全部写类动作（工单/操作票/巡检记录/
遥控/投切等 write_class 动作），在 read-only persona（角色覆盖全部收紧）下经
ActionGateway 发起 → 断言：

1. 每个动作的 Policy 判定 ∈ {DENY, ASK}（事件 ``action.policy_decided``）；
2. 终态 ∈ {DENIED, REJECTED, WAITING_APPROVAL}——绝不出现 EXECUTING/SUCCEEDED；
3. 零副作用：M5 环境状态快照（``env.state_final()``）逐动作前后 diff 为空。

矩阵是数据（``tests/negative_matrix.yaml``）：动作集、角色覆盖、期望判定、请求
参数全部来自文件——本模块只提供机械执行与断言，不做任何特判。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .gateway import ActionGateway
from .registry import default_repo_root

__all__ = ["load_matrix", "run_negative_matrix"]


def load_matrix(path: Path | str) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("actions"):
        raise ValueError(f"负向矩阵文件不合法（缺 actions 段）: {path}")
    return data


def _build_env(env_spec: dict, repo_root: Path):
    """按矩阵 env 段构建 M5 SimEnv（缺省 seed 实例 + 预置操作票）。"""
    from m5_simulation.env import load_scenario

    spec = {
        "identity": {"scenario_id": "m3-negative-matrix", "version": "1.0",
                     "owner": "m3", "tags": ["negative", "read-only"]},
        "sut": {"target": "MODULE", "module": "m3_action"},
        "environment": {
            "park_instance": str(env_spec.get("park_instance", "seed")),
            "clock_start": str(env_spec.get("clock_start", "2026-09-15T08:00:00Z")),
            "speed": float(env_spec.get("speed", 60.0)),
            "injections": [],
        },
        "user_model": {"persona": "OPERATOR", "behavior_script": []},
        "interactions": {"max_turns": 8, "timeout_s": 600},
        "events": [],
        "constraints": {"budget": {"token": 0, "action": 0}, "stop_conditions": []},
        "metrics": [],
        "provenance": {"source": "m3-negative-matrix",
                       "created_at": "2026-09-28T00:00:00Z", "notes": "m3-eval"},
    }
    env = load_scenario(spec, repo_root=repo_root)
    for code, order in (env_spec.get("switch_orders") or {}).items():
        env.switch_orders[str(code)] = {"code": str(code), **dict(order)}
    return env


def run_negative_matrix(matrix_path: Path | str, *,
                        runtime_dir: Path | str | None = None,
                        repo_root: Path | str | None = None) -> dict:
    """执行负向矩阵：逐动作发起 → 判定/终态/零副作用三重断言（报告含逐项明细）。"""
    root = Path(repo_root) if repo_root else default_repo_root()
    matrix = load_matrix(matrix_path)
    persona = matrix.get("persona") or {}
    env_spec = matrix.get("env") or {}
    env = _build_env(env_spec, root)

    sandbox = Path(runtime_dir) if runtime_dir else root / "runtime" / "m3_eval" / "negative_matrix"
    if sandbox.exists():
        import shutil

        shutil.rmtree(sandbox)
    sandbox.mkdir(parents=True, exist_ok=True)

    actor = dict(persona.get("actor") or {"user": "OP-001", "agent": "m3-negative-matrix@v1"})
    # persona 角色绑定：矩阵演员按 persona.id 扮演角色（权限集=role_overrides 声明）
    actor_roles = {str(actor.get("user")): str(persona.get("id", "READ_ONLY"))}
    gateway = ActionGateway(
        sandbox, env=env, evaluation=True,
        role_overrides={persona.get("id", "READ_ONLY"): dict(persona.get("role_overrides") or {})},
        actor_roles=actor_roles,
        events_dir=sandbox / "events",  # 矩阵事件流独立（可复跑）
        repo_root=root,
    )

    requested_at = str(env_spec.get("clock_start", "2026-09-15T08:00:00Z"))
    rows: list[dict] = []
    failures: list[str] = []

    for index, item in enumerate(matrix.get("actions") or []):
        capability = str(item["capability"])
        action_id = f"neg-{index:03d}"
        task_id = "task-negative-matrix"
        request = {
            "action_id": action_id,
            "task_id": task_id,
            "turn": index + 1,
            "capability": capability,
            "actor": {"user": str(actor.get("user", "OP-001")),
                      "agent": str(actor.get("agent", "m3-negative-matrix@v1"))},
            "purpose": str(item.get("purpose", "负向矩阵：read-only persona 发起写类动作")),
            "arguments": dict(item.get("arguments") or {}),
            "risk": {"level": "MEDIUM", "reversible": True},
            "idempotency_key": f"neg-{capability}",
            "requested_at": requested_at,
        }
        before = env.state_final()
        result = gateway.execute_action(request, mode="SIMULATION", now=requested_at)
        after = env.state_final()
        decision = gateway.decision_of(action_id)
        side_effect_free = before == after
        expected_decision = str(item.get("expected_decision", "DENY")).upper()

        row = {
            "capability": capability,
            "action_id": action_id,
            "decision": decision,
            "expected_decision": expected_decision,
            "status": result.status.value,
            "side_effect_free": side_effect_free,
        }
        rows.append(row)
        if decision not in ("DENY", "ASK"):
            failures.append(f"{capability}: 判定 {decision!r} 不在 DENY/ASK")
        if decision != expected_decision:
            failures.append(f"{capability}: 判定 {decision!r} != 期望 {expected_decision!r}")
        if result.status.value in ("EXECUTING", "SUCCEEDED", "COMPENSATED"):
            failures.append(f"{capability}: 终态 {result.status.value}（写动作被放行执行）")
        if not side_effect_free:
            failures.append(f"{capability}: M5 环境状态 diff 非空（存在副作用）")

    return {
        "matrix_file": str(matrix_path),
        "persona": persona.get("id", "READ_ONLY"),
        "actions_total": len(rows),
        "rows": rows,
        "failures": failures,
        "passed": not failures,
    }
