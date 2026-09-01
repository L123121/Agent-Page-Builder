"""密码哈希与 JWT 签发/校验 — 认证核心工具层。

设计要点：
- 密码用 bcrypt（自动加盐，cost 因子默认 12），校验用 hmac 比对防时序差异；
- 双 token：access（30 分钟，随请求携带）+ refresh（7 天，仅用于换新 token），
  类型声明在 JWT `type` claim 中，跨类型使用会被拒绝；
- JWT_SECRET 从环境注入，默认值仅用于本地开发——生产必须配置，
  泄露 = 任何人可伪造任意用户的 token。
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import settings

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


class TokenError(Exception):
    """token 无效（过期 / 篡改 / 类型不符）——统一映射为 401"""


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _create_token(user_id: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: str) -> str:
    return _create_token(user_id, ACCESS_TOKEN_TYPE, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(user_id: str) -> str:
    return _create_token(user_id, REFRESH_TOKEN_TYPE, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    """解码并校验 token，类型不符/过期/篡改统一抛 TokenError。"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as error:
        raise TokenError("token 已过期") from error
    except jwt.InvalidTokenError as error:
        raise TokenError("token 无效") from error
    if payload.get("type") != expected_type:
        raise TokenError("token 类型不符")
    if not payload.get("sub"):
        raise TokenError("token 缺少主体")
    return payload
