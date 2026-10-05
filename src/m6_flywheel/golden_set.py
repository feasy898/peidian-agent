# -*- coding: utf-8 -*-
"""m6_flywheel.golden_set · 黄金集管理（SPEC-M6-02）。

- 黄金集目录物理分离：``golden/dev/``（开发集）与 ``golden/holdout/``（验收集，
  git ignore、验收时由验收人核对 hash）互不引用；
- 每条 GoldenCase 经冻结契约校验（01 §2.10）；**来源标记**（``source`` /
  ``excluded_from`` 含 ``holdout``）标注 holdout 的条目禁止进入开发目录
  （装载与校验双重拒绝）；
- **hash 校验**：``golden/dev/MANIFEST.yaml`` 登记每个案例文件的 sha256 与来源
  标记；文件未登记/被改动/出现未登记文件 → CI 断言失败（EVAL-M6-02-N）；
- 01 §3.6 冻结 API：``add_golden_case(case) -> CaseId``（写文件+重建 manifest+
  落 ``golden.case_added`` 事件）。

案例文件拾取：``golden/<set>/case_*.yaml``（M6 §6 交付物口径：case_001..012.yaml
直落 set 根）；``cases/`` 子目录同样支持（01 §1 目录树的 cases/*.yaml 口径）。
``rubrics.yaml`` 是评分单登记文件（非案例，manifest 单列）。
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from contracts import EventType, GoldenCase

__all__ = [
    "GoldenSetError",
    "DEFAULT_DEV_DIR",
    "MANIFEST_NAME",
    "RUBRICS_NAME",
    "list_case_files",
    "load_case_file",
    "load_golden_set",
    "is_holdout_marked",
    "build_manifest",
    "write_manifest",
    "verify_golden_dir",
    "add_golden_case",
    "load_rubrics",
    "golden_set_version",
    "main",
]

DEFAULT_DEV_DIR = "golden/dev"
MANIFEST_NAME = "MANIFEST.yaml"
RUBRICS_NAME = "rubrics.yaml"
HOLDOUT_MARKER = "holdout"
#: manifest 允许登记的非案例文件（案例目录的配套数据）
KNOWN_AUX_FILES = (RUBRICS_NAME, ".gitkeep")


class GoldenSetError(ValueError):
    """黄金集管理错误（契约不过/holdout 禁入 dev/重复登记等）。"""


def repo_root_of(repo_root: Path | str | None = None) -> Path:
    return Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]


def is_holdout_marked(case: GoldenCase | Mapping) -> bool:
    """来源标记判定：excluded_from 含 holdout（01 §2.10：此类案例禁止进开发集）。"""
    excluded = getattr(case, "excluded_from", None)
    if excluded is None and isinstance(case, Mapping):
        excluded = case.get("excluded_from")
    return HOLDOUT_MARKER in (excluded or [])


def list_case_files(golden_dir: Path | str) -> list[Path]:
    """案例文件（set 根 + cases/ 子目录，按路径排序稳定）。"""
    base = Path(golden_dir)
    files = sorted(base.glob("case_*.yaml")) + sorted((base / "cases").glob("case_*.yaml"))
    return files


def load_case_file(path: Path | str) -> GoldenCase:
    """加载并契约校验单条案例（01 §2.10 GoldenCase 冻结结构）。"""
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise GoldenSetError(f"案例文件无法读取: {path} ({exc})") from exc
    if not isinstance(data, Mapping):
        raise GoldenSetError(f"案例文件顶层必须是对象: {path}")
    from contracts import ContractValidationError

    try:
        return GoldenCase.from_dict(dict(data))
    except ContractValidationError as exc:
        raise GoldenSetError(f"案例契约校验失败 {path.name}: {exc}") from exc


def load_golden_set(golden_dir: Path | str, *, allow_holdout: bool = False) -> list[GoldenCase]:
    """装载一个黄金集目录；dev 集遇 holdout 标记条目直接拒绝（SPEC-M6-02）。"""
    base = Path(golden_dir)
    if not base.is_dir():
        raise GoldenSetError(f"黄金集目录不存在: {base}")
    cases: list[GoldenCase] = []
    offenders: list[str] = []
    seen_ids: dict[str, str] = {}
    for path in list_case_files(base):
        case = load_case_file(path)
        if not allow_holdout and is_holdout_marked(case):
            offenders.append(f"{path.name}({case.case_id})")
        if case.case_id in seen_ids:
            raise GoldenSetError(f"case_id 重复: {case.case_id}"
                                 f"（{seen_ids[case.case_id]} 与 {path.name}）")
        seen_ids[case.case_id] = path.name
        if not case.expected_behavior:
            raise GoldenSetError(f"{path.name}: expected_behavior 不能为空（SPEC-M6-02）")
        cases.append(case)
    if offenders:
        raise GoldenSetError(
            "holdout 来源条目禁止进入开发黄金集目录（SPEC-M6-02）: " + ", ".join(offenders))
    return cases


# ---------------------------------------------------------------- manifest
def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(golden_dir: Path | str, *, set_role: str | None = None,
                   now_fn: Callable[[], str] | None = None) -> dict:
    """构建目录 manifest：每个案例文件的 sha256 + 来源标记（hash 校验的基准）。"""
    base = Path(golden_dir)
    role = set_role or ("holdout" if "holdout" in base.name else "dev")
    entries = []
    for path in list_case_files(base):
        case = load_case_file(path)
        entries.append({
            "file": path.name,
            "case_id": case.case_id,
            "version": case.version,
            "source": case.source.value if hasattr(case.source, "value") else str(case.source),
            "excluded_from": list(case.excluded_from or []),
            "sha256": _sha256_file(path),
        })
    aux = sorted(
        ({"file": p.name, "sha256": _sha256_file(p)}
         for p in base.iterdir()
         if p.is_file() and p.name not in (MANIFEST_NAME,)
         and p.name in KNOWN_AUX_FILES),
        key=lambda item: str(item["file"]))
    return {
        "set_role": role,
        "dir": base.name,
        "generated_at": (now_fn or _now)(),
        "cases": entries,
        "aux_files": aux,
    }


def _now() -> str:
    from m2_information.timestamps import utc_now_iso

    return utc_now_iso()


def write_manifest(golden_dir: Path | str, *, set_role: str | None = None,
                   now_fn: Callable[[], str] | None = None) -> Path:
    """（重建并）写 manifest——add_golden_case 与维护命令的统一出口。"""
    base = Path(golden_dir)
    manifest = build_manifest(base, set_role=set_role, now_fn=now_fn)
    path = base / MANIFEST_NAME
    path.write_text(
        "# golden MANIFEST · 由 m6_flywheel.golden_set 维护（hash 校验基准，勿手改）\n"
        + yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    return path


def verify_golden_dir(golden_dir: Path | str, *, expect_role: str = "dev") -> list[str]:
    """CI 断言（SPEC-M6-02）：来源标记 + hash 校验；返回问题列表（空=通过）。

    检查项：
    1. manifest 存在且 ``set_role`` 与目录角色一致；
    2. 每个案例文件都已登记且 sha256 一致（被复制进来的未登记文件即失败）；
    3. manifest 登记的文件实际存在（防静默删除）；
    4. dev 目录内任何案例不得带 holdout 来源标记（excluded_from）；
    5. 目录内不得有未登记的案例/未知文件（aux 白名单除外）。
    """
    base = Path(golden_dir)
    problems: list[str] = []
    manifest_path = base / MANIFEST_NAME
    if not manifest_path.is_file():
        return [f"{base}: 缺 {MANIFEST_NAME}（先运行 golden_set manifest 生成）"]
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return [f"{manifest_path}: manifest YAML 解析失败: {exc}"]
    if str(manifest.get("set_role")) != expect_role:
        problems.append(f"{base}: manifest.set_role={manifest.get('set_role')!r}"
                        f" != 期望 {expect_role!r}")
    registered: dict[str, dict] = {str(item.get("file")): item
                                   for item in manifest.get("cases") or []}
    actual_files = {path.name for path in list_case_files(base)}
    for name in sorted(actual_files - set(registered)):
        problems.append(f"{base.name}/{name}: 未登记（不在 manifest，hash 校验失败）")
    for name, item in sorted(registered.items()):
        path = base / name
        if not path.is_file():
            problems.append(f"{base.name}/{name}: manifest 已登记但文件缺失")
            continue
        digest = _sha256_file(path)
        if digest != str(item.get("sha256")):
            problems.append(f"{base.name}/{name}: sha256 与 manifest 不一致"
                            f"（登记 {str(item.get('sha256'))[:12]}… 实际 {digest[:12]}…）")
        if expect_role == "dev" and HOLDOUT_MARKER in (item.get("excluded_from") or []):
            problems.append(f"{base.name}/{name}: 来源标记含 holdout，禁止进入开发集")
    aux_registered: dict[str, str] = {}
    for item in manifest.get("aux_files") or []:
        if isinstance(item, Mapping):
            aux_registered[str(item.get("file"))] = str(item.get("sha256") or "")
        else:
            aux_registered[str(item)] = ""
    for name, digest in sorted(aux_registered.items()):
        path = base / name
        if path.is_file() and digest and _sha256_file(path) != digest:
            problems.append(f"{base.name}/{name}: 配套文件 sha256 与 manifest 不一致")
    known = actual_files | set(registered) | set(aux_registered) | {MANIFEST_NAME}
    for path in sorted(base.iterdir()):
        if path.is_file() and path.name not in known:
            problems.append(f"{base.name}/{path.name}: 未登记文件（案例目录只允许"
                            f" case_*.yaml / {RUBRICS_NAME} / MANIFEST）")
    return problems


# ---------------------------------------------------------------- rubrics
def load_rubrics(golden_dir: Path | str) -> dict:
    """装载评分单（rubrics.yaml：case_id/DEFAULT → RubricSheet；缺省内置 DEFAULT）。"""
    from .judges import RubricSheet, default_sheet

    path = Path(golden_dir) / RUBRICS_NAME
    sheets: dict = {"DEFAULT": default_sheet()}
    if not path.is_file():
        return sheets
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for key, sheet_data in data.items():
        sheets[str(key)] = RubricSheet.from_dict(sheet_data or {},
                                                 origin=f"{RUBRICS_NAME}:{key}")
    return sheets


def golden_set_version(golden_dir: Path | str) -> str:
    """黄金集版本号：manifest 案例条目（case_id+sha256）排序串的 sha256 前 16 位。"""
    base = Path(golden_dir)
    parts = []
    for path in list_case_files(base):
        parts.append(f"{path.name}:{_sha256_file(path)}")
    digest = hashlib.sha256("|".join(sorted(parts)).encode("utf-8")).hexdigest()
    return f"{base.name}-{digest[:16]}"


# ---------------------------------------------------------------- 冻结 API
def add_golden_case(case: GoldenCase | Mapping, golden_dir: Path | str,
                    *, now_fn: Callable[[], str] | None = None,
                    sink: Callable[[dict], Any] | None = None) -> str:
    """01 §3.6：``add_golden_case(case) -> CaseId``。

    校验（SPEC-M6-02）→ 落 ``case_<id>.yaml`` → 重建 manifest → 落
    ``golden.case_added`` 事件。dev 目录拒绝 holdout 标记条目与同 case_id 重复。
    """
    if not isinstance(case, GoldenCase):
        from contracts import ContractValidationError

        try:
            case = GoldenCase.from_dict(dict(case))
        except ContractValidationError as exc:
            raise GoldenSetError(f"案例契约校验失败: {exc}") from exc
    base = Path(golden_dir)
    base.mkdir(parents=True, exist_ok=True)
    if not case.expected_behavior:
        raise GoldenSetError("expected_behavior 不能为空（SPEC-M6-02）")
    if "holdout" in base.resolve().as_posix() or is_holdout_marked(case):
        # 开发侧通道一律拒绝 holdout 标记条目（holdout 集由验收人离线维护）
        raise GoldenSetError(f"案例 {case.case_id} 带 holdout 来源标记，"
                             "禁止经开发通道写入（SPEC-M6-02）")
    target = base / f"case_{case.case_id}.yaml"
    if target.exists():
        existing = load_case_file(target)
        if existing.version >= case.version:
            raise GoldenSetError(
                f"案例 {case.case_id} 已存在（version={existing.version}），"
                f"新版本必须严格递增（当前提交 version={case.version}）")
    payload = case.to_dict()
    target.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8")
    write_manifest(base, now_fn=now_fn)
    if sink is not None:
        from m2_information.ids import new_ulid

        sink({
            "event_id": new_ulid(),
            "type": EventType.GOLDEN_CASE_ADDED.value,
            "subject": case.case_id,
            "payload": {"version": case.version,
                        "source": case.source.value if hasattr(case.source, "value")
                        else str(case.source),
                        "file": target.name},
            "occurred_at": (now_fn or _now)(),
            "trace_id": f"trace-golden-{case.case_id}",
            "producer": "M6",
        })
    return case.case_id


# ---------------------------------------------------------------- CLI
def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="黄金集管理（manifest 生成 / CI 校验）")
    parser.add_argument("command", choices=["manifest", "verify"])
    parser.add_argument("golden_dir", nargs="?", default=DEFAULT_DEV_DIR)
    parser.add_argument("--role", default=None, help="manifest set_role（缺省按目录名推断）")
    args = parser.parse_args(argv)
    golden_dir = Path(args.golden_dir)
    if args.command == "manifest":
        path = write_manifest(golden_dir, set_role=args.role)
        print(f"manifest -> {path}")
        return 0
    problems = verify_golden_dir(golden_dir,
                                 expect_role=args.role or "dev")
    if problems:
        print(f"GOLDEN VERIFY FAIL: {len(problems)} problem(s)")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    count = len(list_case_files(golden_dir))
    print(f"GOLDEN VERIFY OK: {golden_dir} cases={count} role={args.role or 'dev'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
