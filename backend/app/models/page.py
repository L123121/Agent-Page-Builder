"""Page ORM 模型"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, JSON, String, Text

from app.database import Base
from app.utils.id_generator import generate_id


class Page(Base):
    __tablename__ = "pages"

    id = Column(String, primary_key=True, default=generate_id)
    title = Column(String(100), default="未命名页面", nullable=False)
    description = Column(Text, default="")
    user_id = Column(String, nullable=False, default="anonymous", index=True)
    component_data = Column(JSON, default=list)
    canvas_style = Column(JSON, default=dict)
    share_token = Column(String, nullable=True, index=True)
    is_public = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 默认画布样式
    DEFAULT_CANVAS_STYLE = {
        "width": 1200,
        "height": 740,
        "scale": 100,
        "color": "#000",
        "opacity": 1,
        "backgroundColor": "#fff",
        "fontSize": 14,
    }

    def __init__(self, **kwargs):
        if "canvas_style" not in kwargs or not kwargs["canvas_style"]:
            kwargs["canvas_style"] = self.DEFAULT_CANVAS_STYLE
        super().__init__(**kwargs)

    def to_dict(self) -> dict:
        return {
            "_id": self.id,
            "title": self.title,
            "description": self.description or "",
            "userId": self.user_id,
            "componentData": self.component_data or [],
            "canvasStyle": self.canvas_style or self.DEFAULT_CANVAS_STYLE,
            "shareToken": self.share_token,
            "isPublic": self.is_public,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_summary(self) -> dict:
        return {
            "_id": self.id,
            "title": self.title,
            "description": self.description or "",
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "isPublic": self.is_public,
        }
