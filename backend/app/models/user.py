"""User ORM 模型 — 认证主体与页面归属"""

from sqlalchemy import Column, DateTime, String

from app.database import Base
from app.models.page import utcnow
from app.utils.id_generator import generate_id


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: generate_id(12))
    username = Column(String(32), unique=True, index=True, nullable=False)
    # bcrypt 哈希（60 字符），预留余量
    password_hash = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=utcnow)
