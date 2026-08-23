"""PageVersion ORM 模型 — 页面版本快照"""

from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, Text

from app.database import Base
from app.models.page import utcnow
from app.utils.id_generator import generate_id


class PageVersion(Base):
    __tablename__ = "page_versions"

    id = Column(String, primary_key=True, default=generate_id)
    page_id = Column(
        String, ForeignKey("pages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(100), nullable=False)
    description = Column(Text, default="")
    component_data = Column(JSON, default=list)
    canvas_style = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self) -> dict:
        """完整快照（恢复用）"""
        return {
            "_id": self.id,
            "pageId": self.page_id,
            "name": self.name,
            "description": self.description or "",
            "componentData": self.component_data or [],
            "canvasStyle": self.canvas_style or {},
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }

    def to_summary(self) -> dict:
        """列表摘要（不含快照内容，避免列表接口传大量数据）"""
        return {
            "_id": self.id,
            "pageId": self.page_id,
            "name": self.name,
            "description": self.description or "",
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
