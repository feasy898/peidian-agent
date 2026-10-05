# -*- coding: utf-8 -*-
"""m7_registry.publish · 发布落盘 releases/<id>/（不可变）+ 版本冻结（SPEC-M7-05）。

- **只写一次（文件级 immutable）**：``releases/<id>/`` 一经发布即冻结——
  目录已存在时任何再写（重复 publish、补写文件）→
  :class:`ImmutableReleaseError`；manifest.sha256 登记全部文件 hash，
  ``resolve_release`` 逐文件复校；
- **Release 状态机**：DRAFT→GATED→PUBLISHED（PUBLISHED 后仅可 SUPERSEDED；
  表驱动 ``m7_registry.release.RELEASE_TRANSITIONS``，非法迁移抛
  :class:`IllegalReleaseTransitionError`）；
- **版本冻结**：发布物=ReleaseBundle（六要素带内容 hash）+ AgentContract 快照
  + M6 评估证据（report.json/cases.yaml，签名 run_ref 指向发布目录内副本）+
  manifest（文件 hash 清单）；
- 状态与审计落追加写 journal（``runtime/m7_registry/releases.jsonl`` 缺省）；
  发布事件 ``release.published {stage: release}``（01 §4 主题）。

目录布局与字段口径见 ``src/m7_registry/RELEASE-FORMAT.md``。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from contracts import EventType, ReleaseBundle

from .assets import AssetStore
from .release import GateResult, verify_golden_scores

__all__ = [
    "ImmutableReleaseError",
    "IllegalReleaseTransitionError",
    "PublishError",
    "RELEASE_FILES",
    "ReleaseJournal",
    "ReleaseStateMachine",
    "publish_release",
    "write_release_file",
    "supersede_release",
    "resolve_release",
    "diff_release",
]

#: 发布目录标准文件（manifest 之外的交付件）
RELEASE_FILES = ("release.yaml", "agent_contract.yaml", "evaluation/report.json",
                 "evaluation/cases.yaml", "manifest.yaml")


class PublishError(ValueError):
    """发布失败基错误。"""


class ImmutableReleaseError(PublishError):
    """releases/<id>/ 只写一次被违反（二次写拒绝）。"""


class IllegalReleaseTransitionError(PublishError):
    """Release 状态机非法迁移。"""


def _now() -> str:
    from m2_information.timestamps import utc_now_iso

    return utc_now_iso()


def _ulid() -> str:
    from m2_information.ids import new_ulid

    return new_ulid()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ===========================================================================
# Release journal（状态机权威台账：追加写 + 重放）
# ===========================================================================
class ReleaseStateMachine:
    """表驱动状态机（RELEASE_TRANSITIONS）+ journal 台账。"""

    def __init__(self, journal_path: Path | str | None = None,
                 releases_dir: Path | str | None = None,
                 sink: Callable[[dict], Any] | None = None,
                 now_fn: Callable[[], str] | None = None) -> None:
        from .release import RELEASE_TRANSITIONS

        self.transitions = RELEASE_TRANSITIONS
        self.journal_path = Path(journal_path) if journal_path is not None else None
        self.releases_dir = Path(releases_dir) if releases_dir is not None else None
        self.sink = sink
        self.now_fn = now_fn or _now
        self._states: dict[str, str] = {}
        self._records: dict[str, dict] = {}
        if self.journal_path is not None and self.journal_path.is_file():
            for line in self.journal_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("op") == "transition":
                    self._states[str(entry["release_id"])] = str(entry["to"])
                elif entry.get("op") == "record":
                    self._records[str(entry["release_id"])] = dict(entry["record"])

    # ------------------------------------------------------------ 台账
    def _append(self, op: str, payload: dict) -> None:
        if self.journal_path is None:
            return
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"op": op, **payload}, ensure_ascii=False,
                                    sort_keys=True, default=str) + "\n")

    def state_of(self, release_id: str) -> str:
        state = self._states.get(str(release_id))
        if state is not None:
            return state
        # 台账缺失但发布目录在（journal 丢失/外部核验场景）→ 按 PUBLISHED 事实重建
        if self.releases_dir is not None and (self.releases_dir / str(release_id)).is_dir():
            return "PUBLISHED"
        return "DRAFT"

    def transition(self, release_id: str, to_state: str, *, expect: str | None = None,
                   payload: dict | None = None) -> str:
        from_state = self.state_of(release_id)
        if expect is not None and from_state != expect:
            raise IllegalReleaseTransitionError(
                f"release {release_id!r} 状态 {from_state} != 期望前置 {expect}")
        allowed = self.transitions.get(from_state, ())
        if to_state not in allowed:
            raise IllegalReleaseTransitionError(
                f"Release 状态机非法迁移 {from_state}→{to_state}"
                f"（合法: {list(allowed) or ['<终态>']}；PUBLISHED 后仅可 SUPERSEDED）")
        self._states[str(release_id)] = to_state
        self._append("transition", {"release_id": release_id, "from": from_state,
                                    "to": to_state, "at": self.now_fn(),
                                    **(payload or {})})
        return to_state

    def record(self, release_id: str, rec: dict) -> None:
        self._records[str(release_id)] = dict(rec)
        self._append("record", {"release_id": release_id, "record": rec})

    def get_record(self, release_id: str) -> dict | None:
        return self._records.get(str(release_id))

    def _emit_published(self, release_id: str, extra: dict) -> None:
        if self.sink is None:
            return
        from contracts import EventRecord

        event = {
            "event_id": _ulid(),
            "type": EventType.RELEASE_PUBLISHED.value,
            "subject": release_id,
            "payload": {"stage": "release", **extra},
            "occurred_at": self.now_fn(),
            "trace_id": f"trace-release-{release_id}",
            "producer": "M7",
        }
        try:
            EventRecord.from_dict(event)
        except Exception as exc:  # noqa: BLE001
            raise PublishError(f"发布事件不合约: {exc}") from exc
        self.sink(event)


# ===========================================================================
# 发布落盘（不可变）
# ===========================================================================
def write_release_file(releases_dir: Path | str, release_id: str, name: str,
                       content: str) -> Path:
    """向 releases/<id>/ 写一个文件——目录已存在（已发布）即拒（二次写拒绝）。"""
    base = Path(releases_dir) / str(release_id)
    if base.exists():
        raise ImmutableReleaseError(
            f"releases/{release_id}/ 已存在，内容只写一次（SPEC-M7-05 immutable）："
            f"拒绝写入 {name!r}")
    target = base / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def publish_release(built: Mapping, gate: GateResult, *,
                    releases_dir: Path | str,
                    machine: ReleaseStateMachine,
                    store: AssetStore,
                    evidence_report: Path | str,
                    evidence_cases: Path | str,
                    now_fn: Callable[[], str] | None = None) -> dict:
    """GATED→PUBLISHED：落盘发布物（一次性全量写）+ 状态迁移 + 发布事件。

    前置：gate.passed（DRAFT 只能经 GATED 发布；未过门禁发布 → PublishError）。
    """
    bundle: ReleaseBundle = built["bundle"]
    release_id = str(bundle.release_id)
    base = Path(releases_dir) / release_id
    if base.exists():
        raise ImmutableReleaseError(
            f"releases/{release_id}/ 已存在（SPEC-M7-05 只写一次）：二次发布被拒")
    if not gate.passed:
        raise PublishError(
            f"发布门禁未通过（DRAFT→GATED 未达成，缺项 {gate.missing}）："
            f"拒绝发布 {release_id}")
    state = machine.state_of(release_id)
    if state == "DRAFT":
        machine.transition(release_id, "GATED", expect="DRAFT",
                           payload={"gate": gate.to_dict()})
    elif state != "GATED":
        raise IllegalReleaseTransitionError(
            f"release {release_id!r} 当前状态 {state}，发布前置必须为 GATED")

    agent_record = store.resolve_ref(str(built["agent_ref"]))
    stamp = (now_fn or machine.now_fn)()

    # 1) M6 证据副本（签名 run_ref 改指发布目录内相对路径；digest 不含 run_ref）
    scores = bundle.to_dict()["golden_scores"]
    scores["by_domain"]["signature"]["run_ref"] = "evaluation/report.json"
    bundle_payload = bundle.to_dict()
    bundle_payload["golden_scores"] = scores

    files: dict[str, str] = {
        "release.yaml": yaml.safe_dump(bundle_payload, allow_unicode=True,
                                       sort_keys=False, default_flow_style=False),
        "agent_contract.yaml": yaml.safe_dump(agent_record.descriptor,
                                              allow_unicode=True, sort_keys=False,
                                              default_flow_style=False),
        "evaluation/report.json": Path(evidence_report).read_text(encoding="utf-8"),
        "evaluation/cases.yaml": Path(evidence_cases).read_text(encoding="utf-8"),
    }
    manifest = {
        "release_id": release_id,
        "status": "PUBLISHED",
        "published_at": stamp,
        "contract_version": bundle.contract_version,
        "agent_contract": {"ref": built["agent_ref"],
                           "asset_id": agent_record.asset_id,
                           "version": agent_record.version,
                           "sha256": agent_record.content_hash},
        "gate": gate.to_dict(),
        "files": {},
    }
    # 一次性写入全部发布物（base 目录此刻必须不存在——开头已断言）
    for name, content in files.items():
        target = base / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        manifest["files"][name] = _sha256_file(target)
    manifest["files"]["manifest.yaml"] = "self"
    (base / "manifest.yaml").write_text(
        "# releases/<id>/manifest.yaml · M7 发布清单（只写一次；文件 hash 复核基准）\n"
        + yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8")

    # 发布后完整性自证：签名 run_ref 已指向发布目录内证据副本，重走签名校验
    verify_golden_scores(scores, release_id=release_id, catalog=built["catalog"],
                         release_dir=base)
    machine.transition(release_id, "PUBLISHED", expect="GATED")
    machine.record(release_id, {
        "release_id": release_id, "published_at": stamp,
        "agent_contract": manifest["agent_contract"],
        "files": {k: v for k, v in manifest["files"].items() if v != "self"},
    })
    machine._emit_published(release_id, {
        "gate_checks": [c["name"] for c in gate.checks],
        "golden_pass_rate": bundle_payload["golden_scores"].get("pass_rate"),
        "agent_contract": built["agent_ref"],
    })
    return {"release_id": release_id, "path": str(base),
            "manifest": manifest, "state": "PUBLISHED"}


def supersede_release(release_id: str, *, by_release_id: str,
                      machine: ReleaseStateMachine) -> str:
    """PUBLISHED→SUPERSEDED（唯一合法的发布后迁移；不触碰发布目录内容）。"""
    return machine.transition(release_id, "SUPERSEDED", expect="PUBLISHED",
                              payload={"superseded_by": by_release_id})


# ===========================================================================
# resolve / diff（01 §3.7 冻结 API）
# ===========================================================================
def resolve_release(release_id: str, *, releases_dir: Path | str,
                    repo_root: Path | str | None = None) -> dict:
    """运行时装配：装载发布物并复校 manifest 文件 hash（防篡改）。"""
    base = Path(releases_dir) / str(release_id)
    if not base.is_dir():
        raise PublishError(f"release 不存在: {release_id!r}（{base}）")
    manifest_path = base / "manifest.yaml"
    if not manifest_path.is_file():
        raise PublishError(f"release 缺 manifest.yaml: {base}")
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    problems: list = []
    for name, digest in (manifest.get("files") or {}).items():
        if digest == "self":
            continue
        path = base / name
        if not path.is_file():
            problems.append(f"{name}: manifest 已登记但文件缺失")
        elif _sha256_file(path) != str(digest):
            problems.append(f"{name}: sha256 与 manifest 不一致（内容被改动）")
    if problems:
        raise ImmutableReleaseError(
            f"release {release_id!r} 发布物完整性校验失败: " + "; ".join(problems))
    bundle = ReleaseBundle.from_dict(
        yaml.safe_load((base / "release.yaml").read_text(encoding="utf-8")))
    return {"release_id": release_id, "path": base, "bundle": bundle,
            "manifest": manifest}


def diff_release(a: Mapping, b: Mapping) -> dict:
    """两 release 差分（轨迹漂移对比用；a/b 为 resolve_release 结果或 bundle dict）。"""
    def _bundle(item: Mapping) -> dict:
        if isinstance(item.get("bundle"), ReleaseBundle):
            return item["bundle"].to_dict()
        if isinstance(item.get("bundle"), Mapping):
            return dict(item["bundle"])
        return dict(item)

    left, right = _bundle(a), _bundle(b)

    def _split(refs: list) -> dict:
        table: dict = {}
        for ref in refs or []:
            name = str(ref).split("@", 1)[0]
            table[name] = str(ref)
        return table

    diff: dict = {
        "a": str(left.get("release_id")), "b": str(right.get("release_id")),
        "model_ref_changed": left.get("model_ref") != right.get("model_ref"),
        "ontology_changed": left.get("ontology_version") != right.get("ontology_version"),
        "contract_version_changed": left.get("contract_version") != right.get("contract_version"),
    }
    for key in ("prompt_refs", "skill_refs", "tool_refs", "frozen_scenarios"):
        la, lb = _split(left.get(key)), _split(right.get(key))
        diff[key] = {
            "added": sorted(set(lb) - set(la)),
            "removed": sorted(set(la) - set(lb)),
            "changed": sorted(n for n in set(la) & set(lb) if la[n] != lb[n]),
        }
    ga = dict((left.get("golden_scores") or {}))
    gb = dict((right.get("golden_scores") or {}))
    diff["golden_delta"] = {
        "pass_rate_a": ga.get("pass_rate"), "pass_rate_b": gb.get("pass_rate"),
        "golden_set_version_a": ga.get("golden_set_version"),
        "golden_set_version_b": gb.get("golden_set_version"),
    }
    return diff
