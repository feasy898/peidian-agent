# -*- coding: utf-8 -*-
"""m1_core.ids · 标识符生成。

- ``new_seq_id(prefix)``：进程内确定性递增序号（EVAL 重放口径——action_id 等
  进入事件流的标识不引入随机量，与 M3 事件序号纪律同源）；
- ``new_ulid``：复用 M2 的 ULID 生成（仅非重放敏感标识，如 checkpoint 名）。
"""
from __future__ import annotations

import itertools

from m2_information.ids import new_ulid  # noqa: F401  (re-export)

__all__ = ["new_seq_id", "new_ulid"]

_COUNTER = itertools.count(1)


def new_seq_id(prefix: str = "id") -> str:
    """确定性递增标识：``<prefix>-<n>``（进程内单调）。"""
    return f"{prefix}-{next(_COUNTER):06d}"
