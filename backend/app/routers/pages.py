"""页面 CRUD 路由 — JWT 鉴权 + 按用户归属隔离

所有端点要求 Bearer access token；页面查询统一按 `user_id == 当前用户` 过滤，
他人页面返回 404（与不存在同语义，避免资源枚举）。公开分享走
`GET /api/shared/{token}`（main.py，匿名只读），分享/取消分享需归属者操作。
"""

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.page import Page
from app.models.page_version import PageVersion
from app.models.user import User
from app.schemas.page import PagePayload, ShareResponse, VersionPayload

router = APIRouter()


def _get_owned_page(page_id: str, user: User, db: Session) -> Page:
    """取当前用户拥有的页面；他人的/不存在的一律 404。"""
    page = (
        db.query(Page)
        .filter(Page.id == page_id, Page.user_id == user.id)
        .first()
    )
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    return page


@router.get("")
def list_pages(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取当前用户的页面列表（不含 componentData）"""
    pages = (
        db.query(Page)
        .filter(Page.user_id == user.id)
        .order_by(Page.updated_at.desc())
        .all()
    )
    return {"pages": [p.to_summary() for p in pages]}


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_page(
    data: PagePayload,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建新页面（归属当前用户）"""
    page = Page(
        title=data.title or "未命名页面",
        description=data.description or "",
        user_id=user.id,
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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取页面详情（仅归属者）"""
    page = _get_owned_page(page_id, user, db)
    return {"page": page.to_dict()}


@router.put("/{page_id}")
def update_page(
    page_id: str,
    data: PagePayload,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新页面（仅归属者）"""
    page = _get_owned_page(page_id, user, db)

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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除页面（仅归属者）"""
    page = _get_owned_page(page_id, user, db)
    db.delete(page)
    db.commit()
    return {"message": "页面已删除"}


@router.post("/{page_id}/share")
def share_page(
    page_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """生成分享链接（仅归属者）"""
    page = _get_owned_page(page_id, user, db)

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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """取消分享（仅归属者）"""
    page = _get_owned_page(page_id, user, db)

    page.share_token = None
    page.is_public = False
    db.commit()
    return {"message": "已取消分享"}


# ==================== 页面版本快照 ====================


@router.get("/{page_id}/versions")
def list_page_versions(
    page_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取页面版本列表（不含快照内容；仅归属者）"""
    _get_owned_page(page_id, user, db)
    versions = (
        db.query(PageVersion)
        .filter(PageVersion.page_id == page_id)
        .order_by(PageVersion.created_at.desc())
        .all()
    )
    return {"versions": [v.to_summary() for v in versions]}


@router.post("/{page_id}/versions", status_code=status.HTTP_201_CREATED)
def create_page_version(
    page_id: str,
    data: VersionPayload,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """保存页面版本快照（默认记录页面当前内容；仅归属者）"""
    page = _get_owned_page(page_id, user, db)
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
def get_page_version(
    page_id: str,
    version_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取版本快照完整内容（恢复用；仅归属者）"""
    _get_owned_page(page_id, user, db)
    version = (
        db.query(PageVersion)
        .filter(PageVersion.id == version_id, PageVersion.page_id == page_id)
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")
    return {"version": version.to_dict()}


@router.delete("/{page_id}/versions/{version_id}")
def delete_page_version(
    page_id: str,
    version_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除版本（仅归属者）"""
    _get_owned_page(page_id, user, db)
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
