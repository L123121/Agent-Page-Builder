"""User ORM 模型"""

from datetime import datetime

from sqlalchemy import Column, DateTime, String
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.id_generator import generate_id


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_id)
    username = Column(String(20), unique=True, nullable=False, index=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    avatar = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    pages = relationship("Page", back_populates="user")

    def to_dict(self) -> dict:
        return {
            "_id": self.id,
            "username": self.username,
            "email": self.email,
            "avatar": self.avatar or "",
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }