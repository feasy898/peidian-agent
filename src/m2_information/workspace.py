# -*- coding: utf-8 -*-
"""m2_information.workspace · 每任务六目录工作区与跨任务隔离。

specs/M2-information.md §2：``workspace.py  # 每任务六目录：inputs/ scratch/
state/ artifacts/ evidence/ manifest/``。

SPEC-M2-07 Workspace 隔离：
- 任务只能读写自己 workspace；跨任务引用只允许 artifacts/ 与 evidence/ 下
  READY/PUBLISHED 产物（只读）；
- 跨任务写一律拒绝并落审计事件（action.policy_decided {decision: DENY}，
  事件目录中无独立 security 主题——登记偏差见 tests/CHANGELOG.md）。

存储格式详见 ``src/m2_information/FORMATS.md``。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable

__all__ = [
    "Workspace",
    "WorkspaceManager",
    "WorkspaceIsolationError",
    "WorkspacePathError",
    "SIX_DIRS",
]

SIX_DIRS = ("inputs", "scratch", "state", "artifacts", "evidence", "manifest")

_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]")
_FORBIDDEN_SUBDIRS = {".git", "__pycache__"}


class WorkspaceIsolationError(PermissionError):
    """跨任务访问被拒（SPEC-M2-07）。"""

    def __init__(self, message: str, *, actor_task: str = "", owner_task: str = "",
                 rel_path: str = "") -> None:
        super().__init__(message)
        self.actor_task = actor_task
        self.owner_task = owner_task
        self.rel_path = rel_path


class WorkspacePathError(ValueError):
    """工作区路径非法（绝对路径/越界穿越/非法目录段）。"""


class Workspace:
    """单任务工作区（六目录）。"""

    def __init__(self, base: Path, task_id: str) -> None:
        self.task_id = task_id
        self.root = Path(base) / _SANITIZE_RE.sub("_", task_id)

    def ensure(self) -> "Workspace":
        self.root.mkdir(parents=True, exist_ok=True)
        for name in SIX_DIRS:
            (self.root / name).mkdir(exist_ok=True)
        meta = {"task_id": self.task_id, "dirs": list(SIX_DIRS)}
        (self.root / ".workspace.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return self

    # -------------------------------------------------------------- 路径
    def resolve(self, rel: str) -> Path:
        """相对路径 → 绝对路径（拒绝绝对路径与 ``..`` 越界）。"""
        if not isinstance(rel, str) or not rel:
            raise WorkspacePathError("工作区相对路径不能为空")
        rel = rel.replace("\\", "/")
        if rel.startswith(("/")) or ":" in rel.split("/", 1)[0]:
            raise WorkspacePathError(f"工作区路径必须是相对路径: {rel!r}")
        parts = [p for p in rel.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise WorkspacePathError(f"工作区路径禁止越界（..）: {rel!r}")
        if not parts:
            raise WorkspacePathError(f"工作区路径为空: {rel!r}")
        if parts[0] not in SIX_DIRS:
            raise WorkspacePathError(
                f"工作区路径必须落在六目录之一（{'/'.join(SIX_DIRS)}）: {rel!r}"
            )
        if any(p in _FORBIDDEN_SUBDIRS for p in parts):
            raise WorkspacePathError(f"工作区路径含禁止目录段: {rel!r}")
        return (self.root.joinpath(*parts)).resolve()

    def sub(self, name: str) -> Path:
        if name not in SIX_DIRS:
            raise WorkspacePathError(f"未知工作区目录: {name!r}")
        return self.root / name

    # -------------------------------------------------------------- 读写
    def write(self, rel: str, data: str | bytes) -> str:
        target = self.resolve(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            target.write_bytes(data)
        else:
            target.write_text(str(data), encoding="utf-8")
        return rel

    def read(self, rel: str) -> str:
        target = self.resolve(rel)
        if not target.is_file():
            raise FileNotFoundError(f"工作区文件不存在: {rel!r}（任务 {self.task_id}）")
        return target.read_text(encoding="utf-8")

    def read_bytes(self, rel: str) -> bytes:
        target = self.resolve(rel)
        if not target.is_file():
            raise FileNotFoundError(f"工作区文件不存在: {rel!r}（任务 {self.task_id}）")
        return target.read_bytes()

    def exists(self, rel: str) -> bool:
        try:
            return self.resolve(rel).is_file()
        except WorkspacePathError:
            return False

    def delete(self, rel: str) -> None:
        target = self.resolve(rel)
        if target.is_file():
            target.unlink()

    # -------------------------------------------------------------- 快照
    def list_files(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {name: [] for name in SIX_DIRS}
        for name in SIX_DIRS:
            base = self.root / name
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    out[name].append(path.relative_to(self.root).as_posix())
        return out

    def manifest_snapshot(self) -> dict:
        """六目录文件清单 + sha256（Checkpoint 的 Workspace manifest 快照）。"""
        files = self.list_files()
        digest_map: dict[str, dict[str, str]] = {}
        for name, rels in files.items():
            digest_map[name] = {
                rel: hashlib.sha256(self.read_bytes(rel)).hexdigest() for rel in rels
            }
        total = sum(len(v) for v in files.values())
        return {
            "task_id": self.task_id,
            "dirs": sorted(SIX_DIRS),
            "files": digest_map,
            "file_count": total,
        }


Auditor = Callable[[str, str, dict, str], None]  # (event_type, subject, payload, stream)


class WorkspaceManager:
    """任务工作区管理器（隔离规则的执行点）。"""

    def __init__(
        self,
        base: Path,
        *,
        artifact_status_of: Callable[[str, str], str | None] | None = None,
        auditor: Auditor | None = None,
    ) -> None:
        self.base = Path(base)
        self.base.mkdir(parents=True, exist_ok=True)
        self._artifact_status_of = artifact_status_of or (lambda owner, rel: None)
        self._auditor = auditor

    def workspace(self, task_id: str, *, create: bool = True) -> Workspace:
        ws = Workspace(self.base, task_id)
        return ws.ensure() if create else ws

    # ---------------------------------------------------------- 跨任务
    def read_cross(self, actor_task: str, owner_task: str, rel: str) -> str:
        """跨任务读：仅 artifacts/（READY/PUBLISHED）与 evidence/（只读环境事实）。"""
        self._check_cross(actor_task, owner_task, rel, action="read")
        return self.workspace(owner_task).read(rel)

    def write_cross(self, actor_task: str, owner_task: str, rel: str, data) -> None:
        """跨任务写：一律拒绝 + 审计事件（SPEC-M2-07）。"""
        try:
            self._check_cross(actor_task, owner_task, rel, action="write")
        except WorkspaceIsolationError as exc:
            self._emit_audit(actor_task, owner_task, rel, "write", str(exc))
            raise
        # 即便路径类别允许（只读读），跨任务写也一律拒绝
        error = WorkspaceIsolationError(
            f"跨任务写被拒：任务 {actor_task} 不得写入任务 {owner_task} 的 {rel}"
            f"（跨任务引用只读）",
            actor_task=actor_task, owner_task=owner_task, rel_path=rel,
        )
        self._emit_audit(actor_task, owner_task, rel, "write", str(error))
        raise error

    def _check_cross(self, actor_task: str, owner_task: str, rel: str, *, action: str) -> None:
        if actor_task == owner_task:
            return  # 自身工作区不受跨任务规则约束
        action_cn = {"read": "读", "write": "写"}.get(action, action)
        normalized = rel.replace("\\", "/")
        top = normalized.split("/", 1)[0]
        if top not in ("artifacts", "evidence"):
            raise WorkspaceIsolationError(
                f"跨任务{action_cn}被拒：{rel!r} 不在 artifacts/ 或 evidence/ 下"
                f"（actor={actor_task}, owner={owner_task}）",
                actor_task=actor_task, owner_task=owner_task, rel_path=rel,
            )
        if top == "artifacts":
            status = self._artifact_status_of(owner_task, normalized)
            if status not in ("READY", "PUBLISHED"):
                raise WorkspaceIsolationError(
                    f"跨任务{action_cn}被拒：{rel!r} 的产物状态为 {status!r}"
                    f"（仅 READY/PUBLISHED 可被跨任务引用，actor={actor_task}）",
                    actor_task=actor_task, owner_task=owner_task, rel_path=rel,
                )

    def _emit_audit(self, actor_task: str, owner_task: str, rel: str,
                    action: str, reason: str) -> None:
        if self._auditor is None:
            return
        self._auditor(
            "action.policy_decided",
            actor_task,
            {
                "decision": "DENY",
                "capability": f"workspace.{action}_cross",
                "actor_task": actor_task,
                "owner_task": owner_task,
                "path": rel,
                "reason": reason,
            },
            f"task-{actor_task}",
        )
