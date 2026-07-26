"""页面 CRUD 路由 — 无认证，本地工具直接可用"""

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.page import Page
from app.schemas.page import PageInfo, PagePayload, PageSummary, ShareResponse

router = APIRouter()

# 默认匿名用户 ID（本地工具模式，不要求登录）
DEFAULT_USER_ID = "anonymous"


@router.get("")
def list_pages(db: Session = Depends(get_db)):
    """获取所有页面列表（不含 componentData）"""
    pages = (
        db.query(Page)
        .order_by(Page.updated_at.desc())
        .all()
    )
    return {"pages": [p.to_summary() for p in pages]}


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_page(
    data: PagePayload,
    db: Session = Depends(get_db),
):
    """创建新页面"""
    page = Page(
        title=data.title or "未命名页面",
        description=data.description or "",
        user_id=DEFAULT_USER_ID,
        component_data=data.componentData or [],
        canvas_style=data.canvasStyle or Page.DEFAULT_CANVAS_STYLE,
    )
    db.add(page)
    db.commit()
    db.refresh(page)
    return {"page": page.to_dict()}


@router.get("/{page_id}")
def get_page(
    page_id: str,
    db: Session = Depends(get_db),
):
    """获取页面详情"""
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    return {"page": page.to_dict()}


@router.put("/{page_id}")
def update_page(
    page_id: str,
    data: PagePayload,
    db: Session = Depends(get_db),
):
    """更新页面"""
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")

    update_data = data.model_dump(exclude_none=True)
    if "title" in update_data:
        page.title = update_data["title"]
    if "description" in update_data:
        page.description = update_data["description"]
    if "componentData" in update_data:
        page.component_data = update_data["componentData"]
    if "canvasStyle" in update_data:
        page.canvas_style = update_data["canvasStyle"]

    db.commit()
    db.refresh(page)
    return {"page": page.to_dict()}


@router.delete("/{page_id}")
def delete_page(
    page_id: str,
    db: Session = Depends(get_db),
):
    """删除页面"""
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    db.delete(page)
    db.commit()
    return {"message": "页面已删除"}


@router.post("/{page_id}/share")
def share_page(
    page_id: str,
    db: Session = Depends(get_db),
):
    """生成分享链接"""
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")

    if not page.share_token:
        page.share_token = secrets.token_hex(16)
        page.is_public = True
        db.commit()
        db.refresh(page)

    share_url = f"/preview?share={page.share_token}"
    return ShareResponse(shareToken=page.share_token, shareUrl=share_url)


@router.delete("/{page_id}/share")
def unshare_page(
    page_id: str,
    db: Session = Depends(get_db),
):
    """取消分享"""
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")

    page.share_token = None
    page.is_public = False
    db.commit()
    return {"message": "已取消分享"}