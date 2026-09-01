"""认证路由 — 注册 / 登录 / 刷新

- 登录失败对「用户不存在」与「密码错误」返回相同信息，不给枚举账号的信号；
- refresh 轮换：每次刷新签发全新 access + refresh，旧 refresh 在自然过期前仍有效
  （无服务端撤销表，MVP 取舍：登出 = 客户端丢弃；服务端吊销是明确的演进点）。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse
from app.services import security

router = APIRouter()


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        accessToken=security.create_access_token(user.id),
        refreshToken=security.create_refresh_token(user.id),
        expiresIn=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        username=user.username,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    exists = db.query(User).filter(User.username == data.username).first()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已被注册")
    user = User(username=data.username, password_hash=security.hash_password(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not security.verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    return _token_response(user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)):
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    try:
        payload = security.decode_token(data.refreshToken, security.REFRESH_TOKEN_TYPE)
    except security.TokenError:
        raise unauthorized
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise unauthorized
    return _token_response(user)
