# -*- coding: utf-8 -*-
"""tests.m2_eval_extra · M2 v2 套件补充执行器（tests 侧插件，EVAL-SCHEMA.md §4 协议）。

按 SPEC v2（specs-v2/M2-information.md）覆盖 m2_information.eval_plugin 22 执行器
不直接断言的两类条款（2026-09-29 变异测试 plan-m2 两个探测变异的缺口补齐）；
全部数据驱动（任务/提交/期望全部来自 case.params/expect，无案例特判），
复用 InformationLayer 沙箱装配约定（runtime/m2_eval/<case> 先清空再建）：

- ``m2x.optimistic_lock``（SPEC-M2-07 乐观锁）：put_task 以过期 expected_version
  提交 → 必须 OptimisticLockError 且库内版本不被污染；合法基线提交仍成功。
- ``m2x.knowledge_register_gate``（SPEC-M2-12 注册通道）：Knowledge 注册缺
  review.reviewer / review.review_ref → 必须 KnowledgeReadOnlyError（mutate 前
  的注册门禁）；完整评审信息注册成功且只读检索可见。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from m2_information import InformationLayer
from m2_information.state_store import OptimisticLockError
from m2_information.memory import KnowledgeReadOnlyError
from contracts import TaskState

__all__ = ["EXECUTORS"]


def _result(passed: bool, detail: str, metrics: dict | None = None) -> dict:
    return {"passed": bool(passed), "detail": str(detail), "metrics": metrics or {}}


def _sandbox(ctx, case: dict) -> Path:
    """用例沙箱：runtime/m2_eval/<case-id>（先清空再建，保证可复跑）。"""
    root = Path(ctx.root) / "runtime" / "m2_eval" / str(case.get("id") or "case-extra")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


# ---------------------------------------------------------------------------
# m2x.optimistic_lock · SPEC-M2-07（put_task 乐观锁版本冲突校验）
# ---------------------------------------------------------------------------
def exec_optimistic_lock(case: dict, ctx) -> dict:
    """过期基线提交必须被乐观锁拒绝；拒绝后库内版本不被污染。

    params: {task: {task_id, user_input, ...}, mutations: [commit_state mutation],
             stale_expected_version: int, error_contains?: str}
    """
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    problems: list[str] = []
    layer = InformationLayer(_sandbox(ctx, case))
    spec = dict(params.get("task") or {})
    task_id = str(spec.get("task_id") or "task-eval")
    layer.create_task(task_id, user_input=str(spec.get("user_input") or "评测任务"),
                      trace_id="trace-lock", plan=list(spec.get("plan") or []),
                      todos=list(spec.get("todos") or []))
    for mutation in params.get("mutations") or []:
        layer.commit_state(task_id, dict(mutation))
    current = layer.get_task(task_id)

    stale_version = int(params.get("stale_expected_version") or 0)
    # 过期快照：version 置回过期基线并携带可探测的字段篡改——锁失效时库内将被真实污染
    stale_data = current.to_dict()
    stale_data["version"] = stale_version
    stale_data["current_stage"] = "TAMPERED"
    stale_state = TaskState.from_dict(stale_data)
    raised = False
    try:
        layer.store.put_task(stale_state, expected_version=stale_version)
    except OptimisticLockError as exc:
        raised = True
        contains = expect.get("error_contains") or params.get("error_contains")
        if contains and str(contains) not in str(exc):
            problems.append(f"拒绝消息不含 {contains!r}: {exc}")
    if not raised:
        problems.append(f"过期基线 v{stale_version} 提交未被拒绝"
                        f"（乐观锁失效，库内版本被污染为 v{layer.get_task(task_id).version}）")

    after = layer.get_task(task_id)
    if after.version != current.version:
        problems.append(f"被拒提交污染了库内版本: v{current.version} → v{after.version}")

    # 合法基线提交仍应成功（版本单调递增）
    legal = layer.commit_state(task_id, {"note": "legal-baseline"})
    if legal.version <= current.version:
        problems.append(f"合法基线提交未递增版本: v{current.version} → v{legal.version}")

    metrics = {"version": after.version, "stale_expected_version": stale_version}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"过期基线 v{stale_version} 提交被拒（版本保持 v{current.version}"
                         f" 未污染），合法提交递增至 v{legal.version}", metrics)


# ---------------------------------------------------------------------------
# m2x.knowledge_register_gate · SPEC-M2-12（Knowledge 注册 M7 评审通道必填）
# ---------------------------------------------------------------------------
def exec_knowledge_register_gate(case: dict, ctx) -> dict:
    """缺 reviewer/review_ref 的 Knowledge 注册必须被拒；完整评审注册成功且检索可见。

    params: {task: {task_id, user_input}, entry: {...}, rejected_reviews: {名: review},
             full_review: {reviewer, review_ref}, error_contains?: str}
    """
    params = case.get("params") or {}
    expect = case.get("expect") or {}
    problems: list[str] = []
    layer = InformationLayer(_sandbox(ctx, case))
    entry = dict(params.get("entry") or {})
    contains = expect.get("error_contains") or params.get("error_contains")

    for name, review in (params.get("rejected_reviews") or {}).items():
        raised = False
        try:
            layer.knowledge.register(dict(entry), review=dict(review or {}))
        except KnowledgeReadOnlyError as exc:
            raised = True
            if contains and str(contains) not in str(exc):
                problems.append(f"{name}: 拒绝消息不含 {contains!r}: {exc}")
        if not raised:
            problems.append(f"{name}: 缺评审信息的注册未被拒绝（review={review!r}）")

    title = str(entry.get("title") or "")
    registered = layer.knowledge.retrieve(title)
    if registered:
        problems.append("被拒注册的条目不应可见（检索泄露）")

    full_review = dict(params.get("full_review") or {})
    entry_id = layer.knowledge.register(dict(entry), review=full_review)
    hits = layer.knowledge.retrieve(title)
    if not hits or hits[0].get("entry_id") != entry_id:
        problems.append("完整评审通道注册后检索不可见")
    stored = layer.knowledge.get(entry_id)
    if stored.get("review") != full_review:
        problems.append(f"评审信息未随条目落盘: {stored.get('review')!r}")

    metrics = {"rejected": len(params.get("rejected_reviews") or {})}
    if problems:
        return _result(False, "；".join(problems), metrics)
    return _result(True, f"{metrics['rejected']} 个缺评审信息变体全部被拒；"
                         f"完整评审注册 {entry_id[:12]}… 可检索且评审信息落盘", metrics)


EXECUTORS = {
    "m2x.optimistic_lock": exec_optimistic_lock,
    "m2x.knowledge_register_gate": exec_knowledge_register_gate,
}
