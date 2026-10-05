# -*- coding: utf-8 -*-
"""m4_semantic.resolver · 实体解析（specs/M4-semantic-ontology.md SPEC-M4-02）。

``resolve_entities("2 号变压器温度")`` → ``[{entity_id: TX-02, attribute: winding_temp}]``。

数据驱动（``ontology/aliases.yaml``，新增设备零代码）：
- **显式别名**（分数 explicit_alias_score=1.0）：device_aliases 短语命中（含房号限定形式）；
- **房内序号**（分数 room_ordinal_score，强读法）："N 号<类型词>" = 某配电房内该类型
  按 ID 排序的第 N 台——运维口语"N 号变压器"默认指房内序号（如 A 房 TX-01/TX-02
  即 1 号/2 号变压器）；新增同类型设备自动参与排序，无需改代码；
- **全园区尾号**（分数 parkwide_ordinal_score，弱读法）：设备 ID 数字尾号恰为 N——
  独立单台设备的编号（如 B 房唯一变压器 TX-03 的"3"是全园区尾号而非房内序号）
  只落在弱读法上，与同类型兜底候选处于歧义阈值内 → 返回候选列表不擅断；
- **同类型兜底**（分数 same_type_fallback_score）：文本出现类型词时，该类型其余设备
  （限定在命中的房号范围内）作为弱候选；
- **属性词典**：中文口语词 → 本体属性名（如 温度→winding_temp、局放→pd），
  按 applies_to 匹配已解析设备的对象类型；带 sensor_type 的属性经绑定关系
  （缺省 monitors）联动出传感器实体；
- **歧义不擅断**（"无歧义阈值内多候选时返回候选列表"）：候选按分数排序，
  首名与次名分差 < ``unambiguous_margin`` 时判定歧义——返回阈值内全部候选
  （含逐候选理由），不擅自择一；分差达阈值时只返回唯一消歧解（+联动传感器）。

对当前实例中不存在的别名 target 自动忽略（别名表全局共享，实例各自过滤）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .loader import LoadedOntology, load_ontology

__all__ = ["ResolvedEntity", "EntityResolver", "resolve_entities", "normalize_text"]

# 全角 → 半角（数字/字母），并去除全部空白（"2 号变压器" 与 "2号变压器" 同一形态）
_FW_TRANSLATION = str.maketrans(
    "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz",
)

_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

_ORDINAL_WORD = r"([0-9]+|[一二两三四五六七八九十]+)号"


def normalize_text(text: str) -> str:
    """归一化：全角转半角 + 去除全部空白（大小写保留，ID 大小写敏感）。"""
    return re.sub(r"\s+", "", str(text).translate(_FW_TRANSLATION))


def _parse_ordinal(token: str) -> int | None:
    token = token.strip()
    if token.isdigit():
        return int(token)
    if len(token) == 1 and token in _CN_DIGITS:
        return _CN_DIGITS[token]
    if len(token) == 2:  # 十X / X十
        if token[0] == "十" and token[1] in _CN_DIGITS:
            return 10 + _CN_DIGITS[token[1]]
        if token[1] == "十" and token[0] in _CN_DIGITS:
            return _CN_DIGITS[token[0]] * 10
    return None


@dataclass
class ResolvedEntity:
    """实体解析结果条目（01 §3.4 ResolvedEntity）。"""

    entity_id: str            # 本体实例实体 ID（设备/房间/园区/操作员/传感器）
    entity_type: str | None   # 本体对象类型 ID（Transformer…）
    attribute: str | None     # 属性词典 canonical 名（如 winding_temp）
    matched: str              # 命中的文本片段/别名短语（归一化形态）
    score: float              # 匹配分数（显式 1.0 > 编号组 0.8 > 全园区尾号 0.6 > 兜底 0.5）
    reason: str               # 候选理由（歧义时逐候选返回，供上游裁决）
    ambiguous: bool           # True=处于候选列表（未定），False=已消歧
    scope: str | None = None  # 命中的范围限定（配电房 ID）

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "attribute": self.attribute,
            "matched": self.matched,
            "score": self.score,
            "reason": self.reason,
            "ambiguous": self.ambiguous,
            "scope": self.scope,
        }


class EntityResolver:
    """别名表 + 属性词典 + 序号双读法的实体解析器（数据来自 ontology/aliases.yaml）。"""

    def __init__(self, loaded: LoadedOntology) -> None:
        self.loaded = loaded
        cfg: Mapping[str, Any] = loaded.aliases or {}
        scores = cfg.get("scores") if isinstance(cfg.get("scores"), Mapping) else cfg
        self.explicit_score = float(scores.get("explicit_alias_score", 1.0))
        self.room_score = float(scores.get("room_ordinal_score", 0.8))
        self.parkwide_score = float(scores.get("parkwide_ordinal_score", 0.6))
        self.fallback_score = float(scores.get("same_type_fallback_score", 0.5))
        self.margin = float(scores.get("unambiguous_margin", 0.3))

        known_ids = loaded.instance.entity_ids() if loaded.instance else set()
        self.substation_devices = dict(loaded.instance.substation_devices) if loaded.instance else {}

        # 范围别名（归一化短语 → 目标 ID；目标不在当前实例则忽略）
        self.scope_map: dict = {}
        for entry in cfg.get("scopes") or []:
            target = str(entry.get("target", ""))
            if target in known_ids:
                self.scope_map[normalize_text(str(entry["alias"]))] = target

        # 设备显式别名：短语 → [目标]
        self.alias_map: dict = {}
        for entry in cfg.get("device_aliases") or []:
            target = str(entry.get("target", ""))
            if target not in known_ids:
                continue
            for phrase in entry.get("aliases") or []:
                norm = normalize_text(phrase)
                if norm:
                    self.alias_map.setdefault(norm, set()).add(target)

        # 属性词典
        self.attr_entries: list = []
        for entry in cfg.get("attribute_dictionary") or []:
            self.attr_entries.append({
                "canonical": str(entry["canonical"]),
                "match": [normalize_text(t) for t in entry.get("match") or [] if normalize_text(t)],
                "applies_to": [str(t) for t in entry.get("applies_to") or []],
                "sensor_type": entry.get("sensor_type"),
                "binding_relation": str(entry.get("binding_relation") or "monitors"),
            })

        # 序号泛化模式（数据声明的 id_pattern 已在 loader 编译校验）
        self.ordinal_patterns: list = []
        for entry in cfg.get("generic_ordinal") or []:
            self.ordinal_patterns.append({
                "type_id": str(entry["type_id"]),
                "type_words": [str(w) for w in entry.get("type_words") or []],
                "id_pattern": re.compile(str(entry["id_pattern"])),
                "room_score": float(entry.get("room_score", self.room_score)),
                "parkwide_score": float(entry.get("parkwide_score", self.parkwide_score)),
            })

        self._relations = [tuple(r) for r in (loaded.instance.relations if loaded.instance else [])]

    # ------------------------------------------------------------------
    def resolve(self, text: str) -> list:
        """文本 → 实体列表；歧义时返回全部阈值内候选（ambiguous=True，含理由）。"""
        text_norm = normalize_text(text)
        if not text_norm:
            return []

        scopes = self._detect_scopes(text_norm)
        scope_ids = {target for target, _ in scopes}

        candidates: dict = {}  # id -> {score, reasons, matched, scope}

        # 1) 显式别名
        for phrase, targets in self.alias_map.items():
            if phrase in text_norm:
                for target in sorted(targets):
                    self._add_candidate(
                        candidates, target, self.explicit_score,
                        f"显式别名命中: {phrase}", phrase, None,
                    )
        # 范围别名自身也是候选（仅在无设备指称时作为结果）
        for target, alias in scopes:
            self._add_candidate(
                candidates, target, self.explicit_score, f"范围别名命中: {alias}", alias, target,
            )

        # 2) 序号双读法（"N 号<类型词>"）
        for pattern in self.ordinal_patterns:
            for word in pattern["type_words"]:
                regex = re.compile(_ORDINAL_WORD + re.escape(word))
                for match in regex.finditer(text_norm):
                    ordinal = _parse_ordinal(match.group(1))
                    if ordinal is None:
                        continue
                    self._resolve_ordinal(candidates, pattern, ordinal,
                                          match.group(0), scope_ids)

        # 3) 同类型兜底（弱候选；限定房号范围）
        mentioned_types = sorted({
            p["type_id"] for p in self.ordinal_patterns
            for w in p["type_words"] if w in text_norm
        })
        for type_id in mentioned_types:
            for node_id, _node in self._nodes_of_type(type_id):
                if scope_ids and not self._in_scopes(node_id, scope_ids):
                    continue
                self._add_candidate(
                    candidates, node_id, self.fallback_score,
                    f"同类型设备候选（{type_id}）", "", self._scope_of(node_id, scope_ids),
                )

        if not candidates:
            return []

        # 设备指称存在时，范围别名仅作限定词，不作为结果
        if any(cid not in scope_ids for cid in candidates):
            for sid in scope_ids:
                candidates.pop(sid, None)
            if not candidates:
                return []

        # 属性词典：按已解析设备的对象类型挂接
        attr_hits: list = []
        for entry in self.attr_entries:
            for term in entry["match"]:
                if term and term in text_norm:
                    attr_hits.append(entry)
                    break
        for entry in attr_hits:
            applies = set(entry["applies_to"])
            attached = False
            for cid, info in candidates.items():
                ctype = self._type_of(cid)
                if ctype and ctype in applies:
                    info.setdefault("attribute", entry["canonical"])
                    attached = True
            if not attached and len(attr_hits) == 1 and len(candidates) == 1:
                # 单候选且对象类型未知 → 仍附属性（如挂在园区/房间上的泛指）
                next(iter(candidates.values()))["attribute"] = entry["canonical"]

        # 决策：排序 → 首次名分差 ≥ 阈值 → 唯一消歧（只返回首名+联动传感器）；
        #       否则返回阈值内歧义候选列表（逐候选理由，不擅自择一）。
        results = [
            ResolvedEntity(
                entity_id=cid,
                entity_type=self._type_of(cid),
                attribute=info.get("attribute"),
                matched=info.get("matched") or "",
                score=info["score"],
                reason="；".join(info["reasons"]),
                ambiguous=False,
                scope=info.get("scope"),
            )
            for cid, info in candidates.items()
        ]
        results.sort(key=lambda r: (-r.score, r.entity_id))
        top = results[0]
        second = results[1] if len(results) > 1 else None
        unambiguous = second is None or (top.score - second.score) >= self.margin
        if unambiguous:
            picked = [top]
            self._expand_sensors(picked)
            return picked
        kept = [r for r in results if (top.score - r.score) <= self.margin + 1e-9]
        for r in kept:
            r.ambiguous = True
        return kept

    # ------------------------------------------------------------------
    def _resolve_ordinal(self, candidates: dict, pattern: dict, ordinal: int,
                         matched: str, scope_ids: set) -> None:
        """序号双读法（语义与 ontology/aliases.yaml 头注一致，对任意同构实例通用）。

        - 房内序号读法（强，room_score）："N 号<类型>" = 某配电房内该类型按 ID 排序的
          第 N 台（运维口语默认读法；未提房号时对全部房求读法，多房同现即歧义）；
        - 全园区尾号读法（弱，parkwide_score）：设备 ID 数字尾号（id_pattern 的 num
          捕获组）恰为 N 即命中（房号限定时仅在该房内）。两读法对同一设备取高分。
        """
        type_id = pattern["type_id"]
        # 房 → 该类型设备 ID 列表（排序）；全园区尾号表
        by_room: dict = {}
        tails_all: list = []
        for node_id, _node in self._nodes_of_type(type_id):
            room = self._room_of(node_id)
            if room is not None:
                by_room.setdefault(room, []).append(node_id)
            parsed = pattern["id_pattern"].match(node_id)
            if parsed and parsed.groupdict().get("num") is not None:
                tails_all.append((node_id, int(parsed.group("num"))))

        rooms = sorted(by_room)
        if scope_ids:
            rooms = [r for r in rooms if r in scope_ids]

        # 房内序号读法：每房同类型设备按 ID 排序，第 ordinal 台命中
        for room in rooms:
            members = sorted(by_room[room])
            if 1 <= ordinal <= len(members):
                node_id = members[ordinal - 1]
                self._add_candidate(
                    candidates, node_id, pattern["room_score"],
                    f"房内序号匹配: {matched} → {node_id}（{room} 内{type_id} 按序第 {ordinal} 台）",
                    matched, room,
                )
        # 全园区尾号读法（弱）
        for node_id, tail in tails_all:
            if tail != ordinal:
                continue
            if scope_ids and not self._in_scopes(node_id, scope_ids):
                continue
            self._add_candidate(
                candidates, node_id, pattern["parkwide_score"],
                f"全园区尾号匹配: {matched} → {node_id}（独立编号，非房内序号读法）",
                matched, self._scope_of(node_id, scope_ids),
            )

    # ------------------------------------------------------------------
    def _detect_scopes(self, text_norm: str) -> list:
        hits: list = []
        for alias_norm, target in self.scope_map.items():
            if alias_norm and alias_norm in text_norm:
                hits.append((target, alias_norm))
        # 每个目标保留最长命中
        best: dict = {}
        for target, alias in hits:
            if target not in best or len(alias) > len(best[target]):
                best[target] = alias
        return sorted(best.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    def _nodes_of_type(self, type_id: str) -> list:
        if not self.loaded.instance:
            return []
        return [
            (nid, node)
            for nid, node in self.loaded.instance.nodes.items()
            if node.get("type") == type_id
        ]

    def _type_of(self, entity_id: str) -> str | None:
        if not self.loaded.instance:
            return None
        node = self.loaded.instance.node(entity_id)
        return node.get("type") if node else None

    def _room_of(self, device_id: str) -> str | None:
        for sid, devices in self.substation_devices.items():
            if device_id in devices:
                return sid
        return None

    def _in_scopes(self, device_id: str, scope_ids: set) -> bool:
        return any(device_id in self.substation_devices.get(sid, []) for sid in scope_ids)

    def _scope_of(self, device_id: str, scope_ids: set) -> str | None:
        for sid in sorted(scope_ids):
            if device_id in self.substation_devices.get(sid, []):
                return sid
        return None

    @staticmethod
    def _add_candidate(candidates: dict, entity_id: str, score: float,
                       reason: str, matched: str, scope: str | None) -> None:
        info = candidates.setdefault(
            entity_id, {"score": 0.0, "reasons": [], "matched": "", "scope": scope},
        )
        info["score"] = max(info["score"], float(score))
        if reason and reason not in info["reasons"]:
            info["reasons"].append(reason)
        if matched and matched not in info["matched"]:
            info["matched"] = info["matched"] + " | " + matched if info["matched"] else matched

    def _expand_sensors(self, results: list) -> None:
        """带 sensor_type 的属性 → 经绑定关系联动出传感器实体（SPEC-M4-02 例 2）。"""
        if not self.loaded.instance:
            return
        attr_by_canonical = {e["canonical"]: e for e in self.attr_entries}
        for result in list(results):
            if not result.attribute:
                continue
            entry = attr_by_canonical.get(result.attribute)
            if not entry or not entry.get("sensor_type"):
                continue
            relation = entry.get("binding_relation") or "monitors"
            for src, rel, dst in self._relations:
                if rel != relation or dst != result.entity_id:
                    continue
                sensor = self.loaded.instance.node(src)
                if sensor and sensor.get("type") == entry["sensor_type"]:
                    if any(r.entity_id == src for r in results):
                        continue
                    results.append(ResolvedEntity(
                        entity_id=src,
                        entity_type=sensor.get("type"),
                        attribute=result.attribute,
                        matched=result.matched,
                        score=self.explicit_score,
                        reason=f"{result.entity_id} 经 {relation} 关系绑定的"
                               f"{entry['sensor_type']}传感器",
                        ambiguous=result.ambiguous,
                        scope=result.scope,
                    ))


# ---------------------------------------------------------------------------
# 模块级冻结算子（01 §3.4 resolve_entities）
# ---------------------------------------------------------------------------
def default_loaded() -> LoadedOntology:
    """默认本体（缓存于 loader）。"""
    return load_ontology()


def resolve_entities(text: str, loaded: LoadedOntology | None = None) -> list:
    """01 §3.4 ``resolve_entities(text) -> list[ResolvedEntity]``（dict 形态）。"""
    loaded = loaded or default_loaded()
    return [r.to_dict() for r in EntityResolver(loaded).resolve(text)]
