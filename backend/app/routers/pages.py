"""页面 CRUD 路由 — 无认证，本地工具直接可用"""

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.page import Page
from app.models.page_version import PageVersion
from app.schemas.page import PagePayload, ShareResponse, VersionPayload

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


# ==================== 页面版本快照 ====================


@router.get("/{page_id}/versions")
def list_page_versions(page_id: str, db: Session = Depends(get_db)):
    """获取页面版本列表（不含快照内容）"""
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    versions = (
        db.query(PageVersion)
        .filter(PageVersion.page_id == page_id)
        .order_by(PageVersion.created_at.desc())
        .all()
    )
    return {"versions": [v.to_summary() for v in versions]}


@router.post("/{page_id}/versions", status_code=status.HTTP_201_CREATED)
def create_page_version(page_id: str, data: VersionPayload, db: Session = Depends(get_db)):
    """保存页面版本快照（默认记录页面当前内容）"""
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    version = PageVersion(
        page_id=page_id,
        name=data.name,
        description=data.description or "",
        component_data=data.componentData if data.componentData is not None else page.component_data or [],
        canvas_style=data.canvasStyle if data.canvasStyle is not None else page.canvas_style or {},
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return {"version": version.to_dict()}


@router.get("/{page_id}/versions/{version_id}")
def get_page_version(page_id: str, version_id: str, db: Session = Depends(get_db)):
    """获取版本快照完整内容（恢复用）"""
    version = (
        db.query(PageVersion)
        .filter(PageVersion.id == version_id, PageVersion.page_id == page_id)
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")
    return {"version": version.to_dict()}


@router.delete("/{page_id}/versions/{version_id}")
def delete_page_version(page_id: str, version_id: str, db: Session = Depends(get_db)):
    """删除版本"""
    version = (
        db.query(PageVersion)
        .filter(PageVersion.id == version_id, PageVersion.page_id == page_id)
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")
    db.delete(version)
    db.commit()
    return {"message": "版本已删除"}
