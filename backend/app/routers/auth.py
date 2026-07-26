"""认证路由 — 注册 / 登录"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, UserInfo

router = APIRouter()


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    # 检查用户名或邮箱是否已存在
    existing = db.query(User).filter(
        (User.username == data.username) | (User.email == data.email)
    ).first()
    if existing:
        if existing.username == data.username:
            raise HTTPException(status_code=409, detail="用户名已存在")
        raise HTTPException(status_code=409, detail="邮箱已被注册")

    # 创建用户
    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # 签发 token
    token = create_access_token(user.id)
    return AuthResponse(token=token, user=UserInfo(**user.to_dict()))


@router.post("/login", response_model=AuthResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    # 通过用户名或邮箱查找
    user = db.query(User).filter(
        (User.username == data.username) | (User.email == data.username)
    ).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 签发 token
    token = create_access_token(user.id)
    return AuthResponse(token=token, user=UserInfo(**user.to_dict()))