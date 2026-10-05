# -*- coding: utf-8 -*-
"""m2_information · ULID 风格标识符生成（标准库实现，无第三方依赖）。

26 字符 Crockford Base32：10 字符毫秒时间戳 + 16 字符随机量。
仅用于 id 生成，不进入任何确定性 hash 输入（SPEC-M2-01：hash 与随机量无关）。
"""
from __future__ import annotations

import os
import time

__all__ = ["new_ulid"]

_ENC = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford Base32（排除 I/L/O/U）


def new_ulid() -> str:
    """生成 26 字符 ULID（毫秒时间戳 + 80bit 随机）。"""
    ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms << 80) | rand
    chars = []
    for shift in range(0, 130, 5):
        chars.append(_ENC[(value >> shift) & 0x1F])
    return "".join(reversed(chars))
