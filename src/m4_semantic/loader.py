# -*- coding: utf-8 -*-
"""m4_semantic.loader · 本体加载与完整性校验（specs/M4-semantic-ontology.md SPEC-M4-01/07）。

职责：
- 加载 ``ontology/*.yaml``（00-ontology.md 的机器可读版）与 ``regulations/*.yaml``、
  ``ontology/aliases.yaml``，运行期只读；
- 完整性校验（任一失败 → 拒绝加载，"启动失败优于带病运行"）：
  * 关系引用的实体/对象均存在，关系 ID 必须已注册（SPEC-M4-01）；
  * 动作表与 M3 注册表对齐（接口：``LoadedOntology.action_manifest`` 导出动作清单，
    M3 用它做注册表对齐断言；加载时可传入 registry 做 diff，非空即拒）；
  * 枚举值全部在受控词表内（ontology/enums.yaml 与 src/contracts 同源封闭集；
    实例数据中的枚举字段逐项封闭校验）；
- 版本管理：本体版本 = ontology/ 目录内容 hash（sha256，文件名+字节）；
  ``load_ontology(version=...)`` 传入期望版本不一致即拒绝（防本体漂移，SPEC-M4-07）；
- 园区实例按名加载（ADDENDUM §D）：默认搜索 ``ontology/``，
  环境变量 ``PARK_INSTANCE_PATH``（分隔符 ";"）追加搜索目录；
  加载实现对任意同构实例文件通用，不针对特定实例硬编码。

依赖约定：``contracts`` 包位于 src/，需在 sys.path（run_evals.py / pytest 配置已保证）。
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from contracts import CONTROLLED_VOCABULARY

__all__ = [
    "OntologyLoadError",
    "OntologyVersionMismatchError",
    "RegistryAlignmentError",
    "InstanceLoadError",
    "LoadedOntology",
    "ParkInstance",
    "load_ontology",
    "load_park_instance",
    "resolve_instance_file",
    "compute_ontology_version",
    "default_repo_root",
    "reset_cache",
    "ONTOLOGY_FILE_NAMES",
    "REGULATION_FILE_IDS",
    "DEFAULT_INSTANCE_NAME",
    "ENV_PARK_INSTANCE_PATH",
    "PARK_INSTANCE_PATH_SEP",
]

#: ontology/ 必需文件（00-ontology.md 四要素 + 受控词表 + 种子实例）
ONTOLOGY_FILE_NAMES = (
    "objects.yaml", "relations.yaml", "actions.yaml", "rules.yaml", "enums.yaml",
)
#: regulations/ 必需规程（ADDENDUM §A）
REGULATION_FILE_IDS = ("REG-SAFE", "REG-COMM", "REG-TECH", "REG-OP")
#: 默认园区实例名（ontology/seed.yaml，00 §3）
DEFAULT_INSTANCE_NAME = "seed"
#: 实例搜索环境变量与分隔符（ADDENDUM §D）
ENV_PARK_INSTANCE_PATH = "PARK_INSTANCE_PATH"
PARK_INSTANCE_PATH_SEP = ";"

_ID_SAFE_RE = re.compile(r"^[\w][\w\-\.]*$")

#: 顶层"list[dict 且含 id]"节的默认对象类型提示（实例通用解析，非特定实例硬编码；
#: 实体显式给出 type/otype 时优先）
SECTION_TYPE_HINTS = {
    "alarms": "Alarm",
    "work_orders": "WorkOrder",
    "switch_orders": "SwitchOrder",
    "work_tickets": "WorkTicket",
    "maintenance_plans": "MaintenancePlan",
    "inspection_records": "InspectionRecord",
    "asset_records": "AssetRecord",
    "load_curves": "LoadCurve",
    "demand_records": "DemandRecord",
    "bills": "Bill",
    "measurements": "Measurement",
    "grid_events": "GridEvent",
    "operating_states": "OperatingState",
    "feeders": "Feeder",
    "circuits": "Circuit",
    "panels": "Panel",
}

#: 实例数据的枚举封闭校验点：对象类型 → (字段, 受控词表名)
_INSTANCE_ENUM_FIELDS = {
    "Alarm": (("level", "alarm_level"),),
    "OperatingState": (("state", "device_state"),),
    "WorkOrder": (("status", "work_order_status"),),
    "SwitchOrder": (("status", "switch_order_status"),),
}


class OntologyLoadError(ValueError):
    """本体/规程/别名数据加载或完整性校验失败（SPEC-M4-01：拒绝加载）。"""


class OntologyVersionMismatchError(OntologyLoadError):
    """期望本体版本与目录内容 hash 不一致（SPEC-M4-07：任务拒绝启动）。"""


class RegistryAlignmentError(OntologyLoadError):
    """动作表与 M3 注册表 diff 非空（SPEC-M4-01：对齐失败，加载拒绝）。"""


class InstanceLoadError(OntologyLoadError):
    """园区实例文件缺失或结构非法（ADDENDUM §D）。"""


def default_repo_root() -> Path:
    """仓库根 = src/m4_semantic/loader.py 的上两级。"""
    return Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 版本管理：本体版本 = ontology/ 目录内容 hash（SPEC-M4-07）
# ---------------------------------------------------------------------------
def compute_ontology_version(ontology_dir: Path | str) -> str:
    """对目录内全部文件按相对路径排序后拼接（路径 + \\0 + 字节 + \\0）取 sha256。

    任意文件内容或增删都会改变版本 → ReleaseBundle.ontology_version 可据此防漂移。
    """
    odir = Path(ontology_dir)
    if not odir.is_dir():
        raise OntologyLoadError(f"本体目录不存在: {odir}")
    files = sorted(p for p in odir.rglob("*") if p.is_file())
    if not files:
        raise OntologyLoadError(f"本体目录为空: {odir}")
    digest = hashlib.sha256()
    for path in files:
        rel = path.relative_to(odir).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(path.read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# 园区实例（ADDENDUM §D：按名加载 + PARK_INSTANCE_PATH 搜索）
# ---------------------------------------------------------------------------
@dataclass
class ParkInstance:
    """园区实例（格式同 ontology/seed.yaml）：节点 + 关系三元组 + 结构索引。"""

    name: str                                  # 实例名（文件名去扩展名）
    source: str                                # 来源路径描述
    data: dict                                 # 原始数据
    nodes: dict = field(default_factory=dict)  # id -> {id,type,attributes,section}
    relations: list = field(default_factory=list)  # [[src, rel, dst], ...]
    park_id: str | None = None
    substation_devices: dict = field(default_factory=dict)  # SR-id -> [device ids]

    def node(self, entity_id: str) -> dict | None:
        return self.nodes.get(entity_id)

    def entity_ids(self) -> set:
        return set(self.nodes)

    def devices_of(self, substation_id: str) -> list:
        return list(self.substation_devices.get(substation_id, []))

    def nodes_by_type(self, type_id: str) -> list:
        return [nid for nid, n in self.nodes.items() if n.get("type") == type_id]

    @property
    def device_count(self) -> int:
        return sum(len(v) for v in self.substation_devices.values())


def resolve_instance_file(
    name: str,
    *,
    repo_root: Path | str | None = None,
    extra_dirs: Iterable[Path | str] | None = None,
) -> Path:
    """按名解析实例文件（去扩展名匹配 .yaml/.yml）。

    搜索顺序（ADDENDUM §D）：默认 ``ontology/`` → 环境变量 ``PARK_INSTANCE_PATH``
    （";" 分隔，依序追加）→ 调用方显式 extra_dirs（末位追加）。
    环境变量在调用时读取（便于测试注入）。
    """
    if not name or not _ID_SAFE_RE.match(name):
        raise InstanceLoadError(f"非法实例名: {name!r}（须为不含路径分隔符的标识符）")
    root = Path(repo_root) if repo_root else default_repo_root()
    search_dirs: list[Path] = [root / "ontology"]
    env_value = os.environ.get(ENV_PARK_INSTANCE_PATH, "")
    for part in env_value.split(PARK_INSTANCE_PATH_SEP):
        part = part.strip()
        if part:
            search_dirs.append(Path(part))
    for d in extra_dirs or ():
        search_dirs.append(Path(d))
    for d in search_dirs:
        for ext in (".yaml", ".yml"):
            candidate = d / f"{name}{ext}"
            if candidate.is_file():
                return candidate
    listed = ", ".join(str(d) for d in search_dirs)
    raise InstanceLoadError(
        f"园区实例文件未找到: {name!r}（搜索目录: {listed}；可用 {ENV_PARK_INSTANCE_PATH} 追加）"
    )


def load_park_instance(
    name: str,
    *,
    repo_root: Path | str | None = None,
    extra_dirs: Iterable[Path | str] | None = None,
    context: "LoadedOntology | None" = None,
    data: Mapping[str, Any] | None = None,
) -> ParkInstance:
    """按名加载园区实例并做完整性校验。

    ``data`` 直接给实例内容（内联/测试用）；否则按 ``resolve_instance_file`` 找文件。
    ``context`` 缺省时自行加载本体上下文（对象类型/关系/枚举）。
    """
    if context is None:
        context = load_ontology(repo_root=repo_root, instance=None)
    source = "inline"
    if data is None:
        path = resolve_instance_file(name, repo_root=repo_root, extra_dirs=extra_dirs)
        data = _load_yaml_file(path)
        source = str(path)
    return _parse_instance(
        data,
        name=name,
        source=source,
        known_types=set(context.object_types),
        relation_ids=set(context.relation_types),
        enums=context.enums,
    )


# ---------------------------------------------------------------------------
# 实例解析与校验
# ---------------------------------------------------------------------------
def _parse_instance(
    data: Any,
    *,
    name: str,
    source: str,
    known_types: set,
    relation_ids: set,
    enums: Mapping[str, Sequence[str]],
) -> ParkInstance:
    """实例数据 → ParkInstance（校验：结构/类型/关系引用/枚举封闭，任一失败即拒）。"""
    if not isinstance(data, Mapping):
        raise InstanceLoadError(f"实例 {name!r}: 顶层必须是对象（mapping）")

    inst = ParkInstance(name=name, source=source, data=dict(data))
    problems: list = []

    def add_node(entity_id: str, type_id: str | None, attributes: dict, section: str) -> None:
        if entity_id in inst.nodes:
            problems.append(f"实体 ID 重复: {entity_id!r}（节 {section}）")
            return
        if type_id is not None and type_id not in known_types:
            problems.append(f"实体 {entity_id!r} 类型越界: {type_id!r}（本体对象类型不存在）")
            return
        inst.nodes[entity_id] = {
            "id": entity_id,
            "type": type_id,
            "attributes": dict(attributes),
            "section": section,
        }

    park = data.get("park")
    if not isinstance(park, Mapping) or not park.get("id"):
        raise InstanceLoadError(f"实例 {name!r}: park.id 缺失（园区实例必须有园区标识）")
    inst.park_id = str(park["id"])
    park_attrs = {k: v for k, v in park.items() if k != "substations"}
    add_node(inst.park_id, "Park", park_attrs, "park")

    substations = park.get("substations") or []
    if not isinstance(substations, list):
        raise InstanceLoadError(f"实例 {name!r}: park.substations 必须为列表")
    for substation in substations:
        if not isinstance(substation, Mapping) or not substation.get("id"):
            problems.append(f"实例 {name!r}: 配电房缺 id: {substation!r}")
            continue
        sid = str(substation["id"])
        add_node(sid, "SubstationRoom",
                 {k: v for k, v in substation.items() if k != "devices"}, "substations")
        devices = substation.get("devices") or []
        if not isinstance(devices, list):
            problems.append(f"实例 {name!r}: 配电房 {sid!r} 的 devices 必须为列表")
            continue
        for device in devices:
            if not isinstance(device, Mapping) or not device.get("id"):
                problems.append(f"实例 {name!r}: 配电房 {sid!r} 存在缺 id 的设备: {device!r}")
                continue
            did = str(device["id"])
            dtype = device.get("type")
            if not dtype:
                problems.append(f"实例 {name!r}: 设备 {did!r} 缺 type")
                continue
            add_node(did, str(dtype),
                     {k: v for k, v in device.items() if k not in ("id", "type")}, "devices")
            inst.substation_devices.setdefault(sid, []).append(did)

    for op in data.get("operators") or []:
        if not isinstance(op, Mapping) or not op.get("id"):
            problems.append(f"实例 {name!r}: 操作员缺 id: {op!r}")
            continue
        add_node(str(op["id"]), "Operator",
                 {k: v for k, v in op.items() if k != "id"}, "operators")

    schedule = data.get("price_schedule")
    if isinstance(schedule, Mapping) and schedule.get("id"):
        add_node(str(schedule["id"]), "PriceSchedule",
                 {k: v for k, v in schedule.items() if k != "id"}, "price_schedule")

    # 通用扩展节：任意顶层 list[dict 且含 id]（告警/工单/检修计划/负荷曲线等），
    # 对任意同构实例通用，不针对特定实例硬编码。
    for section, value in data.items():
        if section in ("park", "relations", "operators", "price_schedule", "meta"):
            continue
        if not isinstance(value, list):
            continue
        for entity in value:
            if not isinstance(entity, Mapping) or not entity.get("id"):
                continue
            eid = str(entity["id"])
            type_id = _entity_type(entity, section, known_types)
            attrs = {k: v for k, v in entity.items() if k not in ("id", "type", "otype")}
            add_node(eid, type_id, attrs, section)

    # 关系三元组：关系 ID 必须注册，两端必须存在（SPEC-M4-01）
    known_ids = inst.entity_ids()
    for triple in data.get("relations") or []:
        if not (isinstance(triple, (list, tuple)) and len(triple) == 3):
            problems.append(f"实例 {name!r}: 关系三元组格式错误（须为 [src, rel, dst]）: {triple!r}")
            continue
        src, rel, dst = (str(x) for x in triple)
        if rel not in relation_ids:
            problems.append(f"实例 {name!r}: 关系 ID 未在本体注册: {rel!r}（{src} → {dst}）")
            continue
        if src not in known_ids:
            problems.append(f"实例 {name!r}: 关系引用不存在的实体: {src!r}（{rel} → {dst}）")
            continue
        if dst not in known_ids:
            problems.append(f"实例 {name!r}: 关系引用不存在的实体: {dst!r}（{src} -{rel}->）")
            continue
        inst.relations.append([src, rel, dst])

    # 枚举封闭校验（实例数据中的受控词表字段）
    for nid, node in inst.nodes.items():
        checks = _INSTANCE_ENUM_FIELDS.get(node.get("type") or "")
        attrs = node["attributes"]
        for field_name, vocab_name in checks or ():
            value = attrs.get(field_name)
            if value is None:
                continue
            allowed = set(enums.get(vocab_name) or [])
            if allowed and str(value) not in allowed:
                problems.append(
                    f"实例 {name!r}: 实体 {nid!r} 字段 {field_name} 枚举越界: {value!r}（{vocab_name}）"
                )
    if isinstance(schedule, Mapping):
        for period in schedule.get("periods") or []:
            allowed = set(enums.get("price_period_type") or [])
            if allowed and str(period.get("type")) not in allowed:
                problems.append(
                    f"实例 {name!r}: 电价时段类型越界: {period.get('type')!r}（price_period_type）"
                )

    if problems:
        raise InstanceLoadError(f"实例 {name!r} 校验失败（拒绝加载）: " + "；".join(problems))
    return inst


def _entity_type(entity: Mapping[str, Any], section: str, known_types: set) -> str | None:
    """实体对象类型解析：显式 otype > 显式 type（须为本体对象类型）> 节名提示。"""
    explicit = entity.get("otype")
    if isinstance(explicit, str) and explicit:
        return explicit
    declared = entity.get("type")
    if isinstance(declared, str) and declared in known_types:
        return declared
    return SECTION_TYPE_HINTS.get(section)


# ---------------------------------------------------------------------------
# LoadedOntology
# ---------------------------------------------------------------------------
@dataclass
class LoadedOntology:
    """已加载并校验通过的本体（运行期只读快照）。"""

    version: str                    # ontology/ 目录内容 hash（sha256 hex）
    ontology_dir: str
    repo_root: str
    enums: dict                     # 词表名 -> [值]
    object_types: dict              # 类型 ID -> {name_cn, attributes, group}
    object_groups: dict             # 组名 -> {description, types: [类型 ID]}
    relation_types: dict            # 关系 ID -> 定义
    query_patterns: list            # 00 §1.2 三跳查询模式声明
    actions: dict                   # 动作 ID -> 定义（保持文件序）
    action_order: list
    rules: dict                     # 规则 ID -> 定义（ontology/rules.yaml 注册表）
    aliases: dict                   # ontology/aliases.yaml 原始数据
    regulations: dict               # REG-ID -> 规程数据
    instance: ParkInstance | None   # 默认/指定园区实例

    # ---- 动作清单导出（M3 注册表对齐断言接口，SPEC-M4-01）----
    def action_manifest(self) -> list:
        """导出动作清单（按 actions.yaml 文件序）：M3 逐条注册并据此做对齐断言。"""
        return [
            {
                "id": action_id,
                "name_cn": self.actions[action_id].get("name_cn", ""),
                "risk_level": self.actions[action_id].get("risk_level"),
                "reversible": self.actions[action_id].get("reversible"),
                "default_policy": self.actions[action_id].get("default_policy"),
                "policy_locked": self.actions[action_id].get("policy_locked", False),
            }
            for action_id in self.action_order
        ]

    def action_ids(self) -> list:
        return list(self.action_order)

    def align_registry(self, registry: Iterable[str]) -> None:
        """动作表 ↔ 注册表 对齐断言：diff 非空 → RegistryAlignmentError（加载拒绝）。"""
        if registry is None:
            return
        want = set(self.action_ids())
        got = {str(x) for x in registry}
        missing = sorted(want - got)
        extra = sorted(got - want)
        if missing or extra:
            raise RegistryAlignmentError(
                "动作表与 M3 注册表对齐失败："
                f"动作表中缺失于注册表={missing}，注册表多出={extra}"
            )

    def attribute_dictionary(self) -> list:
        """属性词典（aliases.yaml）。"""
        return list((self.aliases or {}).get("attribute_dictionary") or [])

    def constraint_rules_for(self, type_id: str) -> list:
        """对象类型 → 直接约束规则 ID（由 REG-TECH 条款 scope 字段数据驱动）。"""
        from .regulation import RegulationIndex

        return RegulationIndex(self).rules_for_scope(type_id)


# ---------------------------------------------------------------------------
# 主入口：load_ontology（01 §3.4 冻结 API）
# ---------------------------------------------------------------------------
_CACHE: dict = {}


def reset_cache() -> None:
    """清空默认本体缓存（测试用）。"""
    _CACHE.clear()


def load_ontology(
    version: str | None = None,
    *,
    repo_root: Path | str | None = None,
    ontology_dir: Path | str | None = None,
    registry: Iterable[str] | None = None,
    instance: str | None = DEFAULT_INSTANCE_NAME,
    instance_data: Mapping[str, Any] | None = None,
    use_cache: bool = True,
) -> LoadedOntology:
    """加载本体（01 §3.4 ``load_ontology(version) -> LoadedOntology``）。

    - ``version``：期望的本体版本（目录内容 hash）；给定且不一致 → OntologyVersionMismatchError
      （SPEC-M4-07：版本不匹配的任务拒绝启动）。None = 接受当前内容并返回其 hash。
    - ``registry``：M3 已注册能力（动作 ID 集合）；给定则做对齐断言（SPEC-M4-01）。
    - ``instance``：园区实例名（默认 "seed"；None/空 = 不加载实例）。
    - ``instance_data``：内联实例内容（取代实例文件；负向测试件用）。
    """
    root = Path(repo_root) if repo_root else default_repo_root()
    odir = Path(ontology_dir) if ontology_dir else root / "ontology"
    computed = compute_ontology_version(odir)  # 目录不存在/为空 → OntologyLoadError
    if version is not None and str(version) != computed:
        raise OntologyVersionMismatchError(
            f"本体版本不匹配：期望 {version}，实际（ontology/ 目录内容 hash）={computed}；"
            "任务拒绝启动（防本体漂移，SPEC-M4-07）"
        )

    registry_list = None if registry is None else sorted({str(x) for x in registry})
    cache_key = (str(odir.resolve()), computed, instance or "",
                 None if registry_list is None else tuple(registry_list))
    if use_cache and instance_data is None and cache_key in _CACHE:
        return _CACHE[cache_key]

    raw = {name: _load_yaml_file(odir / name) for name in ONTOLOGY_FILE_NAMES}
    enums = _validate_enums(raw["enums.yaml"])
    object_types, object_groups = _validate_objects(raw["objects.yaml"])
    relation_types, query_patterns = _validate_relations(
        raw["relations.yaml"], object_types, object_groups
    )
    actions, action_order = _validate_actions(raw["actions.yaml"], enums)
    rules = _validate_rules(raw["rules.yaml"])
    regulations = _validate_regulations(root)
    aliases = _validate_aliases(odir / "aliases.yaml")

    if instance:
        if instance_data is not None:
            inst = _parse_instance(
                instance_data, name=instance, source="inline",
                known_types=set(object_types), relation_ids=set(relation_types), enums=enums,
            )
        else:
            path = resolve_instance_file(instance, repo_root=root)
            inst = _parse_instance(
                _load_yaml_file(path), name=instance, source=str(path),
                known_types=set(object_types), relation_ids=set(relation_types), enums=enums,
            )
    else:
        inst = None

    loaded = LoadedOntology(
        version=computed,
        ontology_dir=str(odir),
        repo_root=str(root),
        enums=enums,
        object_types=object_types,
        object_groups=object_groups,
        relation_types=relation_types,
        query_patterns=query_patterns,
        actions=actions,
        action_order=action_order,
        rules=rules,
        aliases=aliases,
        regulations=regulations,
        instance=inst,
    )
    loaded.align_registry(registry_list)  # 对齐失败 → RegistryAlignmentError

    if use_cache and instance_data is None:
        _CACHE[cache_key] = loaded
    return loaded


# ---------------------------------------------------------------------------
# 分项校验
# ---------------------------------------------------------------------------
def _load_yaml_file(path: Path) -> Any:
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except OSError as exc:
        raise OntologyLoadError(f"本体文件无法读取: {path}（{exc}）") from None
    except yaml.YAMLError as exc:
        raise OntologyLoadError(f"本体文件 YAML 解析失败: {path}（{exc}）") from None


def _validate_enums(data: Any) -> dict:
    enums = (data or {}).get("enums")
    if not isinstance(enums, dict) or not enums:
        raise OntologyLoadError("ontology/enums.yaml: 缺少 enums 映射")
    for name, values in enums.items():
        if not isinstance(values, list) or not values or not all(
            isinstance(v, str) and v for v in values
        ):
            raise OntologyLoadError(f"enums.{name} 必须为非空字符串列表")
    # 与 src/contracts 受控词表同源封闭校验（双向一致，启动失败优于带病运行）
    for name, enum_cls in CONTROLLED_VOCABULARY.items():
        code_values = {member.value for member in enum_cls}
        yaml_values = set(enums.get(name) or [])
        if yaml_values != code_values:
            raise OntologyLoadError(
                f"enums.{name} 与 contracts 受控词表不一致: yaml={sorted(yaml_values)} "
                f"code={sorted(code_values)}"
            )
    extra = sorted(set(enums) - set(CONTROLLED_VOCABULARY))
    if extra:
        raise OntologyLoadError(f"enums.yaml 存在 contracts 未登记的词表: {extra}")
    return {k: list(v) for k, v in enums.items()}


def _validate_objects(data: Any) -> tuple:
    groups = (data or {}).get("object_groups")
    if not isinstance(groups, dict) or not groups:
        raise OntologyLoadError("ontology/objects.yaml: 缺少 object_groups")
    object_types: dict = {}
    object_groups: dict = {}
    for group_key, group in groups.items():
        gkey = str(group_key)
        types = (group or {}).get("types") or []
        if not isinstance(types, list) or not types:
            raise OntologyLoadError(f"object_groups.{gkey}: types 缺失或为空")
        object_groups[gkey] = {
            "description": (group or {}).get("description", ""),
            "types": [],
        }
        for item in types:
            type_id = (item or {}).get("id")
            if not type_id:
                raise OntologyLoadError(f"object_groups.{gkey}: 存在缺 id 的对象类型")
            if type_id in object_types:
                raise OntologyLoadError(f"对象类型 ID 重复: {type_id!r}")
            object_types[type_id] = {
                "name_cn": item.get("name_cn", ""),
                "attributes": [str(a) for a in (item.get("attributes") or [])],
                "measurement_bindings": list(item.get("measurement_bindings") or []),
                "group": gkey,
            }
            object_groups[gkey]["types"].append(type_id)
    return object_types, object_groups


def _validate_relations(data: Any, object_types: dict, object_groups: dict) -> tuple:
    relations = (data or {}).get("relations")
    if not isinstance(relations, list) or not relations:
        raise OntologyLoadError("ontology/relations.yaml: relations 缺失或为空")
    group_names = {g.lower() for g in object_groups}
    relation_types: dict = {}
    for item in relations:
        rid = (item or {}).get("id")
        if not rid:
            raise OntologyLoadError("relations: 存在缺 id 的关系类型")
        if rid in relation_types:
            raise OntologyLoadError(f"关系类型 ID 重复: {rid!r}")
        for side in ("domain", "range"):
            raw_value = item.get(side)
            if not raw_value:
                raise OntologyLoadError(f"关系 {rid!r}: 缺 {side}")
            for token in str(raw_value).split(","):
                token = token.strip()
                if not token:
                    continue
                if token not in object_types and token.lower() not in group_names:
                    raise OntologyLoadError(
                        f"关系 {rid!r} 的 {side} 引用未知对象类型/组: {token!r}"
                    )
        relation_types[rid] = dict(item)
    patterns = []
    for item in (data or {}).get("query_patterns") or []:
        pid = (item or {}).get("id")
        if not pid:
            raise OntologyLoadError("query_patterns: 存在缺 id 的查询模式")
        hops = item.get("hops")
        if not isinstance(hops, int) or isinstance(hops, bool) or hops < 1 or hops > 3:
            raise OntologyLoadError(f"查询模式 {pid!r}: hops 必须为 1..3 的整数，实际 {hops!r}")
        patterns.append(dict(item))
    return relation_types, patterns


def _validate_actions(data: Any, enums: dict) -> tuple:
    actions = (data or {}).get("actions")
    if not isinstance(actions, list) or not actions:
        raise OntologyLoadError("ontology/actions.yaml: actions 缺失或为空")
    risk_values = set(enums.get("risk_level") or [])
    policy_values = set(enums.get("policy_decision") or [])
    by_id: dict = {}
    order: list = []
    for item in actions:
        action_id = (item or {}).get("id")
        if not action_id:
            raise OntologyLoadError("actions: 存在缺 id 的动作")
        if action_id in by_id:
            raise OntologyLoadError(f"动作 ID 重复: {action_id!r}")
        if item.get("risk_level") not in risk_values:
            raise OntologyLoadError(
                f"动作 {action_id!r} risk_level 枚举越界: {item.get('risk_level')!r}"
            )
        if item.get("default_policy") not in policy_values:
            raise OntologyLoadError(
                f"动作 {action_id!r} default_policy 枚举越界: {item.get('default_policy')!r}"
            )
        if not isinstance(item.get("reversible"), bool):
            raise OntologyLoadError(f"动作 {action_id!r}: reversible 必须为布尔")
        if not isinstance(item.get("policy_locked"), bool):
            raise OntologyLoadError(f"动作 {action_id!r}: policy_locked 必须为布尔")
        by_id[action_id] = dict(item)
        order.append(action_id)
    return by_id, order


def _validate_rules(data: Any) -> dict:
    rules = (data or {}).get("rules")
    if not isinstance(rules, list) or not rules:
        raise OntologyLoadError("ontology/rules.yaml: rules 缺失或为空")
    categories = (data or {}).get("categories") or {}
    by_id: dict = {}
    for item in rules:
        rid = (item or {}).get("id")
        if not rid:
            raise OntologyLoadError("rules: 存在缺 id 的规则")
        if rid in by_id:
            raise OntologyLoadError(f"规则 ID 重复: {rid!r}")
        category = item.get("category")
        if category not in categories:
            raise OntologyLoadError(
                f"规则 {rid!r}: category 越界 {category!r}（categories={sorted(categories)}）"
            )
        by_id[rid] = dict(item)
    return by_id


def _validate_regulations(root: Path) -> dict:
    regulations: dict = {}
    seen_ids: dict = {}
    for file_id in REGULATION_FILE_IDS:
        path = root / "regulations" / f"{file_id}.yaml"
        if not path.is_file():
            raise OntologyLoadError(f"规程文件缺失: regulations/{file_id}.yaml（ADDENDUM §A）")
        data = _load_yaml_file(path)
        rules = (data or {}).get("rules")
        if not isinstance(rules, list) or not rules:
            raise OntologyLoadError(f"regulations/{file_id}.yaml: rules 缺失或为空")
        for item in rules:
            rid = (item or {}).get("id")
            if not rid:
                raise OntologyLoadError(f"regulations/{file_id}.yaml: 存在缺 id 的条款")
            if rid in seen_ids:
                raise OntologyLoadError(
                    f"规则 ID 跨文件重复: {rid!r}（{seen_ids[rid]} 与 {file_id}）"
                )
            if not (item.get("clauses") or []):
                raise OntologyLoadError(f"regulations/{file_id}.yaml: 条款 {rid!r} 缺 clauses")
            seen_ids[rid] = file_id
        regulations[file_id] = data
    return regulations


def _validate_aliases(path: Path) -> dict:
    if not Path(path).is_file():
        return {}  # 别名表可选（缺失时 resolver 仅剩 ID 直配）；仓库交付必须包含
    data = _load_yaml_file(path) or {}
    if not isinstance(data, dict):
        raise OntologyLoadError("ontology/aliases.yaml: 顶层必须是对象")
    scores = data.get("scores") if isinstance(data.get("scores"), dict) else data
    for key in ("explicit_alias_score", "room_ordinal_score", "parkwide_ordinal_score",
                "same_type_fallback_score", "unambiguous_margin"):
        if key in scores and not isinstance(scores[key], (int, float)):
            raise OntologyLoadError(f"aliases.yaml: scores.{key} 必须为数值")
    for entry in data.get("device_aliases") or []:
        if not isinstance(entry, dict) or not entry.get("target") or not entry.get("aliases"):
            raise OntologyLoadError(f"aliases.yaml: device_aliases 条目须含 target+aliases: {entry!r}")
    for entry in data.get("attribute_dictionary") or []:
        if not isinstance(entry, dict) or not entry.get("canonical") or not entry.get("match"):
            raise OntologyLoadError(f"aliases.yaml: attribute_dictionary 条目须含 canonical+match: {entry!r}")
    for entry in data.get("generic_ordinal") or []:
        if not isinstance(entry, dict) or not entry.get("type_id") or not entry.get("id_pattern"):
            raise OntologyLoadError(f"aliases.yaml: generic_ordinal 条目须含 type_id+id_pattern: {entry!r}")
        try:
            re.compile(entry["id_pattern"])
        except re.error as exc:
            raise OntologyLoadError(f"aliases.yaml: id_pattern 无法编译: {entry['id_pattern']!r}（{exc}）") from None
    for entry in data.get("scopes") or []:
        if not isinstance(entry, dict) or not entry.get("alias") or not entry.get("target"):
            raise OntologyLoadError(f"aliases.yaml: scopes 条目须含 alias+target: {entry!r}")
    return data
