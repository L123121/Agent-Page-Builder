"""低代码平台服务端 — FastAPI 入口"""

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, get_db
from app.models.page import Page
from app.routers import pages, ai


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时创建表
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Low-Code Platform API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 配置
origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["http://localhost:8080", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载路由
app.include_router(pages.router, prefix="/api/pages")
app.include_router(ai.router, prefix="/api/ai")


@app.get("/api/health")
def health_check():
    return {"status": "ok", "timestamp": time.time()}


@app.get("/api/shared/{token}")
def get_shared_page(token: str, db: Session = Depends(get_db)):
    """按分享 token 获取公开页面"""
    page = db.query(Page).filter(Page.share_token == token, Page.is_public == True).first()
    if not page:
        raise HTTPException(status_code=404, detail="分享页面不存在或已取消分享")
    return {"page": page.to_dict()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=True)
