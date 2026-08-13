"""LLM 客户端 — 模块级单例，复用连接池避免每次请求 new 实例"""

import logging
from typing import Optional

from langchain_openai import ChatOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# ==================== 单例 LLM 客户端 ====================

_llm_client: Optional[ChatOpenAI] = None


def get_llm_client() -> ChatOpenAI:
    """获取 LLM 客户端单例（延迟初始化，线程安全由 GIL 保证）"""
    global _llm_client
    if _llm_client is None:
        _llm_client = ChatOpenAI(
            model=settings.AI_MODEL,
            api_key=settings.AI_API_KEY,
            base_url=settings.AI_BASE_URL,
            temperature=0.7,
            max_tokens=4096,
        )
        logger.info(f"[AI] LLM client initialized: model={settings.AI_MODEL}")
    return _llm_client


def reset_llm_client() -> None:
    """重置 LLM 客户端（用于测试或配置变更后）"""
    global _llm_client
    _llm_client = None
