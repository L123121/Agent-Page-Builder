"""FastAPI 依赖 — 当前用户解析（Bearer JWT）"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services import security

# auto_error=False：缺少 header 时返回 None，由我们自己给统一的 401 语义
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """解析 Authorization: Bearer <access token>，返回当前用户；失败一律 401。"""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未登录或登录已过期",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise unauthorized
    try:
        payload = security.decode_token(credentials.credentials, security.ACCESS_TOKEN_TYPE)
    except security.TokenError:
        raise unauthorized
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise unauthorized
    return user
