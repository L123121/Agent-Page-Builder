"""nanoid 风格 ID 生成器"""

import secrets
import string

ALPHABET = "useandom-26T198340PX75pxJACKVERYMINDBUSHWOLF_GQZbfghjklqvwyzrict"
DEFAULT_SIZE = 12


def generate_id(size: int = DEFAULT_SIZE) -> str:
    """生成 URL 安全的随机 ID"""
    return "".join(secrets.choice(ALPHABET) for _ in range(size))