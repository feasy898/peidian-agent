# -*- coding: utf-8 -*-
"""m2_information.skill_disclosure · Skill 渐进披露（三级）。

specs/M2-information.md SPEC-M2-12（01§2.7 SkillDescriptor）：

- level0：名称常驻 System Context（每 skill ≤10 词，注册即校验）；
- level1：目录（一段描述）仅在任务能力域匹配时进入上下文；
- level2：全文只在 skill 被选中后加载，并计入 token 预算；
- 未注册与 DEPRECATED skill 不出现在任何层。

披露面（登记偏差见 tests/CHANGELOG.md）：默认仅 PUBLISHED skill 可披露
（DRAFT/REVIEW 未过 M7 发布门禁，与 DEPRECATED 同样不入任何层）。
词数口径：CJK 每字 1 词，ASCII 按空白分词（确定性，无模型调用）。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Iterable

from contracts import SkillDescriptor

__all__ = [
    "SkillRegistry",
    "SkillView",
    "SkillDisclosureError",
    "count_words",
    "LEVEL0_MAX_WORDS",
]

LEVEL0_MAX_WORDS = 10
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")


def count_words(text: str) -> int:
    """词数：CJK 字符每字计 1；其余按空白切分计词。"""
    text = str(text or "")
    cjk = len(_CJK_RE.findall(text))
    stripped = _CJK_RE.sub(" ", text)
    ascii_words = len([w for w in stripped.split() if w])
    return cjk + ascii_words


class SkillDisclosureError(ValueError):
    """Skill 披露违规（level0 超长 / 未注册 / DEPRECATED / 未发布）。"""


class SkillView(dict):
    """披露视图：{skill_id, version, level, text, tokens, origin}。"""

    @property
    def tokens(self) -> int:
        return int(self.get("tokens") or 0)


def _estimate(text: str) -> int:
    from .context_builder import estimate_tokens

    return estimate_tokens(text)


class SkillRegistry:
    """Skill 注册表与三级披露（条目来源：显式列表或 skills 目录扫描）。"""

    def __init__(
        self,
        entries: Iterable[dict] | None = None,
        *,
        skills_dir: Path | None = None,
        visible_status: tuple[str, ...] = ("PUBLISHED",),
        level2_root: Path | None = None,
    ) -> None:
        self.visible_status = tuple(visible_status)
        self.level2_root = Path(level2_root) if level2_root else None
        self._descriptors: dict[str, SkillDescriptor] = {}
        self._versions: dict[str, str] = {}
        for entry in list(entries or []):
            self.register(entry)
        if skills_dir is not None:
            self._scan_dir(Path(skills_dir))

    # -------------------------------------------------------------- 注册
    def register(self, entry: dict) -> SkillDescriptor:
        descriptor = entry if isinstance(entry, SkillDescriptor) \
            else SkillDescriptor.from_dict(entry)
        words = count_words(descriptor.disclosure.level0)
        if words > LEVEL0_MAX_WORDS:
            raise SkillDisclosureError(
                f"skill {descriptor.skill_id} 的 level0 名称 {words} 词 > 上限"
                f" {LEVEL0_MAX_WORDS} 词（SPEC-M2-12）"
            )
        self._descriptors[descriptor.skill_id] = descriptor
        self._versions[descriptor.skill_id] = descriptor.version
        return descriptor

    def _scan_dir(self, skills_dir: Path) -> None:
        import yaml

        for manifest in sorted(skills_dir.glob("*/SKILL.yaml")):
            data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.register(data)

    # -------------------------------------------------------------- 查询
    def descriptor(self, skill_id: str) -> SkillDescriptor:
        if skill_id not in self._descriptors:
            raise SkillDisclosureError(f"未注册 skill: {skill_id}（任何层不得出现）")
        return self._descriptors[skill_id]

    def visible_ids(self) -> list[str]:
        """可披露集合：已注册 ∩ 状态 ∈ visible_status（DEPRECATED 永不出现）。"""
        return sorted(
            sid for sid, desc in self._descriptors.items()
            if desc.status.value in self.visible_status
        )

    def version_fingerprint(self) -> str:
        """资产版本指纹：sorted(skill_id@version) 连接（进 Context origin，影响 hash）。"""
        return ";".join(
            f"{sid}@{self._versions[sid]}" for sid in sorted(self._descriptors)
            if sid in self.visible_ids()
        )

    # -------------------------------------------------------------- 三级
    def level0_roster(self) -> str:
        """level0 常驻名册（每 skill 一行：id: 名称）。"""
        lines = [
            f"{sid}: {self._descriptors[sid].disclosure.level0}"
            for sid in self.visible_ids()
        ]
        return "\n".join(lines)

    def level1_catalog(self, task_domains: Iterable[str]) -> tuple[str, list[str]]:
        """level1 目录：仅任务能力域匹配的 skill 进入（返回文本与命中 id）。"""
        domains = {str(d) for d in (task_domains or ())}
        matched = [
            sid for sid in self.visible_ids()
            if self._descriptors[sid].capability_domain.value in domains
        ]
        lines = [
            f"{sid} [{self._descriptors[sid].capability_domain.value}] "
            f"{self._descriptors[sid].disclosure.level1}"
            for sid in matched
        ]
        return "\n".join(lines), matched

    def level2_text(self, skill_id: str) -> str:
        """level2 全文（level2_ref 为文件名时读 level2_root 下文件）。"""
        descriptor = self.descriptor(skill_id)
        ref = descriptor.disclosure.level2_ref
        if self.level2_root is not None and not ref.startswith(("http://", "https://")):
            candidate = self.level2_root / ref
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8")
        return ref

    def disclose(self, skill_id: str, level: int) -> SkillView:
        """三级披露入口（01§3.2 disclose_skill）：level ∈ {0,1,2}。"""
        descriptor = self.descriptor(skill_id)
        if descriptor.status.value not in self.visible_status:
            raise SkillDisclosureError(
                f"skill {skill_id} 状态 {descriptor.status.value} 不可披露"
                f"（可见状态：{'/'.join(self.visible_status)}；DEPRECATED 任何层不得出现）"
            )
        if level == 0:
            text = descriptor.disclosure.level0
        elif level == 1:
            text = descriptor.disclosure.level1
        elif level == 2:
            text = self.level2_text(skill_id)
        else:
            raise SkillDisclosureError(f"披露级别必须为 0|1|2，实际 {level!r}")
        return SkillView({
            "skill_id": skill_id,
            "version": descriptor.version,
            "capability_domain": descriptor.capability_domain.value,
            "level": int(level),
            "text": text,
            "tokens": _estimate(text),
            "origin": f"skills/{skill_id}@{descriptor.version}",
        })
