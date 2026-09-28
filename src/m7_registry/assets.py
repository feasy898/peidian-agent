# -*- coding: utf-8 -*-
"""m7_registry.assets · 四类资产 CRUD+版本链（SPEC-M7-01；01 §3.7 ``register_asset``）。

四类资产子契约（M7 §3；SkillDescriptor 为 01 §2.7 冻结契约，其余三类为 M7 自有
子契约，字段见 ``_validate_<type>``）：

- PROMPT ``{asset_id, version, name, template, variables, compiler, dependencies?}``
  （模板+变量+编译器）；
- SKILL  01 §2.7 SkillDescriptor 全量（M6 契约），``dependencies`` 可选追加
  （追加键在冻结结构之外由注册层单独存放，不污染 SkillDescriptor）；
- TOOL   ``{asset_id, version, capability, params_schema, risk,
  idempotency_policy, dependencies?}``（capability 名+schema+风险+幂等策略）；
- AGENT  AgentContract 全量（``m7_registry.agent_contract`` 校验：六能力域+
  约束清单+行为目录）。

版本链纪律（SPEC-M7-01）：
- ``register_asset`` 建 v1；``update_asset`` 必然产生 chain+1 的新版本记录；
- 旧版本只读不覆盖（同 chain 重放/改写 → :class:`AssetImmutableError`）；
- 内容 hash 未变化的"更新"被拒（版本号不得空转）；
- 存储为追加写 JSONL journal（``runtime/m7_registry/assets.jsonl`` 缺省），
  装载时重放重建索引（与 M3 幂等 journal 同款确定性重放，无 SQLite 依赖）。

资产状态（与评审流联动，SPEC-M7-03）：DRAFT →（提案受理）REVIEW →
（publish_asset 过评审门禁）PUBLISHED →（新版本替代后）DEPRECATED。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

__all__ = [
    "ASSET_TYPES",
    "AssetError",
    "AssetValidationError",
    "AssetExistsError",
    "AssetImmutableError",
    "AssetUnchangedError",
    "AssetNotFoundError",
    "AssetRecord",
    "AssetStore",
    "canonical_json",
    "content_hash_of",
    "parse_ref",
    "qualify_ref",
    "FLOATING_TOKENS",
]

#: 四类资产（01 §3.7 register_asset 的 type 封闭集）
ASSET_TYPES = ("PROMPT", "SKILL", "TOOL", "AGENT")

#: floating 版本 token（SPEC-M7-02：闭包内版本必须显式，禁止 floating latest）
FLOATING_TOKENS = ("latest", "*", "head", "floating", "current")

_REF_RE = re.compile(r"^(?P<asset_id>[^@\s#]+)@(?P<version>[^@\s#]+?)(?:#(?P<hash>[0-9a-f]{6,64}))?$")


class AssetError(ValueError):
    """资产层基错误。"""


class AssetValidationError(AssetError):
    """资产描述子校验失败（字段缺失/类型不符/枚举越界）。"""


class AssetExistsError(AssetError):
    """重复注册同 asset_id。"""


class AssetImmutableError(AssetError):
    """旧版本只读不覆盖（SPEC-M7-01）被违反。"""


class AssetUnchangedError(AssetError):
    """内容未变化，不产生新版本（版本号不得空转）。"""


class AssetNotFoundError(AssetError):
    """资产或版本不存在。"""


def _now() -> str:
    from m2_information.timestamps import utc_now_iso

    return utc_now_iso()


def canonical_json(payload: Any) -> str:
    """规范化 JSON 串（digest 输入口径：排序键、紧凑分隔符、非 ASCII 原样）。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)


def content_hash_of(descriptor: Mapping) -> str:
    return hashlib.sha256(canonical_json(descriptor).encode("utf-8")).hexdigest()


def parse_ref(ref: str) -> dict:
    """解析 ``<asset_id>@<version>[#<hash>]``；缺版本/floating token → 拒绝。

    SPEC-M7-02：闭包内资产版本必须显式（禁止 floating latest）。
    """
    text = str(ref or "").strip()
    match = _REF_RE.match(text)
    if match is None:
        if "@" in text:
            version = text.split("@", 1)[1].split("#", 1)[0]
            if not version:
                raise AssetValidationError(
                    f"资产引用 {text!r} 缺显式版本（SPEC-M7-02 禁 floating）")
        raise AssetValidationError(
            f"资产引用格式非法（应为 <asset_id>@<version>[#<hash>]）: {text!r}")
    asset_id = match.group("asset_id")
    version = match.group("version")
    if version.lower() in FLOATING_TOKENS:
        raise AssetValidationError(
            f"资产引用 {text!r} 使用 floating 版本 {version!r}"
            f"（SPEC-M7-02：闭包内版本必须显式，禁止 floating latest）")
    return {"asset_id": asset_id, "version": version,
            "hash": match.group("hash"), "ref": text}


def qualify_ref(asset_id: str, version: str, content_hash: str) -> str:
    """装配带内容 hash 的引用（01 §2.12：prompts/skills/tools 带 hash）。"""
    return f"{asset_id}@{version}#{content_hash[:12]}"


# ===========================================================================
# 描述子校验（四类子契约）
# ===========================================================================
def _require_keys(descriptor: Mapping, required: tuple, type_name: str) -> None:
    if not isinstance(descriptor, Mapping):
        raise AssetValidationError(f"{type_name} 描述子必须是对象，实际 {type(descriptor).__name__}")
    for key in required:
        if key not in descriptor or descriptor[key] in (None, "", [], {}):
            raise AssetValidationError(f"{type_name} 描述子缺必填字段 {key!r}（SPEC-M7-01）")


def _check_dependencies(type_name: str, descriptor: Mapping) -> list:
    deps = descriptor.get("dependencies") or []
    if not isinstance(deps, list):
        raise AssetValidationError(f"{type_name}.dependencies 必须是列表")
    for item in deps:
        parse_ref(item)  # 逐条校验（floating/缺版本即拒）
    return list(deps)


def _validate_prompt(descriptor: Mapping) -> None:
    _require_keys(descriptor, ("asset_id", "version", "name", "template",
                               "variables", "compiler"),
                  "PROMPT")
    if not isinstance(descriptor["template"], str) or not descriptor["template"].strip():
        raise AssetValidationError("PROMPT.template 必须是非空字符串模板")
    if not isinstance(descriptor["variables"], list):
        raise AssetValidationError("PROMPT.variables 必须是列表")
    compiler = str(descriptor["compiler"])
    if not re.match(r"^[a-z][a-z0-9_.-]*$", compiler):
        raise AssetValidationError(f"PROMPT.compiler 非法: {compiler!r}")
    _check_dependencies("PROMPT", descriptor)


def _validate_skill(descriptor: Mapping) -> None:
    from contracts import ContractValidationError, SkillDescriptor

    payload = {k: v for k, v in dict(descriptor).items() if k != "dependencies"}
    try:
        SkillDescriptor.from_dict(payload)
    except ContractValidationError as exc:
        raise AssetValidationError(f"SKILL 描述子不合 01§2.7 冻结契约: {exc}") from exc
    _check_dependencies("SKILL", descriptor)


def _validate_tool(descriptor: Mapping) -> None:
    _require_keys(descriptor, ("asset_id", "version", "capability", "params_schema",
                               "risk", "idempotency_policy"),
                  "TOOL")
    capability = str(descriptor["capability"])
    if "@" not in capability:
        raise AssetValidationError(
            f"TOOL.capability 必须是 '<动作ID>@<版本>' 形态，实际 {capability!r}")
    risk = descriptor["risk"]
    if not isinstance(risk, Mapping) or "level" not in risk:
        raise AssetValidationError("TOOL.risk 必须含 level（risk_level 枚举）")
    from contracts import RiskLevel

    try:
        RiskLevel(risk["level"])
    except ValueError:
        raise AssetValidationError(f"TOOL.risk.level 枚举越界: {risk['level']!r}") from None
    if not isinstance(descriptor["params_schema"], Mapping):
        raise AssetValidationError("TOOL.params_schema 必须是对象（参数 schema）")
    policy = str(descriptor["idempotency_policy"])
    if policy not in ("CALLER_PROVIDED", "CALLER_PROVIDED_UNIQUE_ARGS"):
        raise AssetValidationError(f"TOOL.idempotency_policy 非法: {policy!r}")
    _check_dependencies("TOOL", descriptor)


def _validate_agent(descriptor: Mapping) -> None:
    from .agent_contract import AgentContract, AgentContractError

    try:
        AgentContract.from_dict(dict(descriptor))
    except AgentContractError as exc:
        raise AssetValidationError(f"AGENT 描述子不合 AgentContract 契约: {exc}") from exc
    _check_dependencies("AGENT", descriptor)


_VALIDATORS = {
    "PROMPT": _validate_prompt,
    "SKILL": _validate_skill,
    "TOOL": _validate_tool,
    "AGENT": _validate_agent,
}


def validate_descriptor(asset_type: str, descriptor: Mapping) -> None:
    if asset_type not in ASSET_TYPES:
        raise AssetValidationError(
            f"资产类型必须是 {'/'.join(ASSET_TYPES)}，实际 {asset_type!r}")
    _VALIDATORS[asset_type](descriptor)


def asset_id_of(asset_type: str, descriptor: Mapping) -> str:
    """各类型描述子的自身标识字段（SKILL=skill_id / AGENT=contract_id / 其余=asset_id）。"""
    if asset_type == "SKILL":
        return str(descriptor.get("skill_id") or "")
    if asset_type == "AGENT":
        return str(descriptor.get("contract_id") or "")
    return str(descriptor.get("asset_id") or "")


def asset_version_of(asset_type: str, descriptor: Mapping) -> str:
    """描述子自身版本串（registry chain 之外的语义版本，ref 组成部分）。"""
    return str(descriptor.get("version") or "")


# ===========================================================================
# 冻结 API 模块级出口（01 §3.7；进程内调用，store 显式注入）
# ===========================================================================
def register_asset(asset_type: str, descriptor: Mapping, *,
                   store: "AssetStore") -> tuple:
    """01 §3.7：``register_asset(type, descriptor) -> AssetId+Version``（委托 store）。"""
    return store.register_asset(asset_type, descriptor)


# ===========================================================================
# 资产记录与存储（JSONL journal + 重放重建）
# ===========================================================================
class AssetRecord:
    """一个资产版本记录（不可变值对象）。"""

    __slots__ = ("asset_id", "type", "chain", "version", "status", "descriptor",
                 "content_hash", "created_at", "superseded_by")

    def __init__(self, asset_id: str, asset_type: str, chain: int, version: str,
                 status: str, descriptor: dict, content_hash: str, created_at: str,
                 superseded_by: int | None = None) -> None:
        self.asset_id = asset_id
        self.type = asset_type
        self.chain = int(chain)
        self.version = version
        self.status = status
        self.descriptor = dict(descriptor)
        self.content_hash = content_hash
        self.created_at = created_at
        self.superseded_by = superseded_by

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id, "type": self.type, "chain": self.chain,
            "version": self.version, "status": self.status,
            "descriptor": self.descriptor, "content_hash": self.content_hash,
            "created_at": self.created_at, "superseded_by": self.superseded_by,
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> "AssetRecord":
        return cls(str(data["asset_id"]), str(data["type"]), int(data["chain"]),
                   str(data["version"]), str(data["status"]), dict(data["descriptor"]),
                   str(data["content_hash"]), str(data["created_at"]),
                   data.get("superseded_by"))

    def ref(self, qualified: bool = True) -> str:
        base = f"{self.asset_id}@{self.version}"
        return f"{base}#{self.content_hash[:12]}" if qualified else base


class AssetStore:
    """资产注册表：追加写 journal，重放重建（确定性，无随机量入索引）。"""

    def __init__(self, journal_path: Path | str | None = None,
                 now_fn: Callable[[], str] | None = None) -> None:
        self.journal_path = Path(journal_path) if journal_path is not None else None
        self.now_fn = now_fn or _now
        self._records: dict[tuple, AssetRecord] = {}   # (asset_id, chain) -> record
        self._latest: dict[str, int] = {}              # asset_id -> 最新 chain
        self._statuses: dict[str, str] = {}            # asset_id -> 当前状态
        if self.journal_path is not None and self.journal_path.is_file():
            self._replay()

    # ------------------------------------------------------------ 重放
    def _replay(self) -> None:
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("op") == "register":
                self._index(AssetRecord.from_dict(entry["record"]), persist=False)
            elif entry.get("op") == "supersede":
                self._mark_superseded(str(entry["asset_id"]), int(entry["chain"]),
                                      int(entry["by_chain"]), persist=False)
            elif entry.get("op") == "status":
                self._statuses[str(entry["asset_id"])] = str(entry["status"])

    def _append(self, op: str, payload: dict) -> None:
        if self.journal_path is None:
            return
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"op": op, **payload}, ensure_ascii=False,
                                    sort_keys=True, default=str) + "\n")

    def _index(self, record: AssetRecord, persist: bool = True) -> None:
        key = (record.asset_id, record.chain)
        if key in self._records:
            raise AssetImmutableError(
                f"资产 {record.asset_id}@chain{record.chain} 已存在，旧版本只读不覆盖"
                f"（SPEC-M7-01）")
        self._records[key] = record
        self._latest[record.asset_id] = record.chain
        self._statuses[record.asset_id] = record.status
        if persist:
            self._append("register", {"record": record.to_dict()})

    def _mark_superseded(self, asset_id: str, chain: int, by_chain: int,
                         persist: bool = True) -> None:
        record = self._records.get((asset_id, chain))
        if record is not None:
            record.superseded_by = by_chain
        if persist:
            self._append("supersede", {"asset_id": asset_id, "chain": chain,
                                       "by_chain": by_chain})

    # ------------------------------------------------------------ 冻结 API
    def register_asset(self, asset_type: str, descriptor: Mapping) -> tuple:
        """01 §3.7：``register_asset(type, descriptor) -> AssetId+Version``。

        建 v1（chain=1，status=DRAFT）；同 asset_id 重复注册 → AssetExistsError。
        """
        validate_descriptor(asset_type, descriptor)
        asset_id = asset_id_of(asset_type, descriptor)
        version = asset_version_of(asset_type, descriptor)
        if not asset_id or not version:
            raise AssetValidationError(
                f"{asset_type} 描述子缺自身标识/版本字段（asset_id/version）")
        if asset_id in self._latest:
            raise AssetExistsError(
                f"资产 {asset_id!r} 已注册（chain={self._latest[asset_id]}），"
                f"变更请走 update_asset（SPEC-M7-01 版本链）")
        record = AssetRecord(asset_id, asset_type, 1, version, "DRAFT",
                             dict(descriptor), content_hash_of(dict(descriptor)),
                             self.now_fn())
        self._index(record)
        return asset_id, 1

    def update_asset(self, asset_id: str, descriptor: Mapping) -> tuple:
        """任一变更产生新版本号（chain+1）；旧版本只读不覆盖。

        内容 hash 未变 → AssetUnchangedError（版本号不得空转）；
        旧 chain 显式重放 → AssetImmutableError。
        """
        if asset_id not in self._latest:
            raise AssetNotFoundError(f"资产未注册: {asset_id!r}")
        if "chain" in descriptor:
            raise AssetImmutableError(
                f"update_asset 不接受显式 chain（{descriptor.get('chain')!r}）："
                f"旧版本只读，变更一律产生新版本（SPEC-M7-01）")
        latest = self.latest(asset_id)
        validate_descriptor(latest.type, descriptor)
        new_id = asset_id_of(latest.type, descriptor)
        if new_id != asset_id:
            raise AssetValidationError(
                f"更新不得改换 asset_id（{asset_id!r} → {new_id!r}）")
        content_hash = content_hash_of(dict(descriptor))
        if content_hash == latest.content_hash:
            raise AssetUnchangedError(
                f"资产 {asset_id!r} 内容未变化，不产生新版本（chain={latest.chain}）")
        record = AssetRecord(asset_id, latest.type, latest.chain + 1,
                             asset_version_of(latest.type, descriptor), "DRAFT",
                             dict(descriptor), content_hash, self.now_fn())
        self._index(record)
        self._mark_superseded(asset_id, latest.chain, record.chain)
        return asset_id, record.chain

    # ------------------------------------------------------------ 读取
    def latest(self, asset_id: str) -> AssetRecord:
        chain = self._latest.get(asset_id)
        if chain is None:
            raise AssetNotFoundError(f"资产未注册: {asset_id!r}")
        return self._records[(asset_id, chain)]

    def get_asset(self, asset_id: str, chain: int | None = None) -> AssetRecord:
        """按 chain 取版本（缺省=最新）；旧版本内容只读返回。"""
        if chain is None:
            return self.latest(asset_id)
        record = self._records.get((asset_id, int(chain)))
        if record is None:
            raise AssetNotFoundError(f"资产 {asset_id!r} 无 chain={chain} 版本")
        return record

    def resolve_ref(self, ref: str) -> AssetRecord:
        """解析 ``id@version`` 到注册表记录（版本必须显式且已注册）。"""
        parsed = parse_ref(ref)
        for chain in range(self._latest.get(parsed["asset_id"], 0), 0, -1):
            record = self._records.get((parsed["asset_id"], chain))
            if record is not None and record.version == parsed["version"]:
                if parsed["hash"] and parsed["hash"] != record.content_hash[:len(parsed["hash"])]:
                    raise AssetNotFoundError(
                        f"资产引用 {ref!r} 的内容 hash 与注册表不符"
                        f"（注册 {record.content_hash[:12]}…）")
                return record
        raise AssetNotFoundError(f"资产引用无法解析（未注册或版本不存在）: {ref!r}")

    def list_versions(self, asset_id: str) -> list:
        return [self._records[(asset_id, chain)]
                for chain in sorted(c for a, c in self._records if a == asset_id)]

    def status_of(self, asset_id: str) -> str:
        if asset_id not in self._latest:
            raise AssetNotFoundError(f"资产未注册: {asset_id!r}")
        return self._statuses[asset_id]

    # ------------------------------------------------------------ 状态（仅供评审门禁调用）
    def _set_status(self, asset_id: str, status: str) -> None:
        """资产状态迁移：**仅** m7_registry.review.publish_asset（评审门禁）调用。

        代码级断言（SPEC-M7-03 无旁路）：模块外部没有其它路径把资产置为
        PUBLISHED——状态迁移入口以单下划线标记，review.publish_asset 是唯一
        持久化调用方（本模块不暴露公开 setter）。
        """
        if asset_id not in self._latest:
            raise AssetNotFoundError(f"资产未注册: {asset_id!r}")
        self._statuses[asset_id] = status
        self._append("status", {"asset_id": asset_id, "status": status})

    def all_assets(self) -> list:
        return [self._records[(asset_id, self._latest[asset_id])]
                for asset_id in sorted(self._latest)]
