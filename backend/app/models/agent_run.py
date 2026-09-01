"""AgentRun 模型 — 每次 Agent 调用的运行记录（可观测性落库）

用途：
- 运行统计（成功率 / 自省修正率 / 停留阶段分布）
- 失败与修正 case 沉淀：corrections 非空或 error 的运行即 golden 候选，
  由 eval/golden_suggest.py 扫描导出，形成「线上失败 → 回归用例」飞轮
"""

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text

from app.database import Base
from app.models.page import utcnow


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=utcnow, index=True)
    thread_id = Column(String, index=True)
    stage = Column(String)                      # 本次请求的起始阶段
    # success | waiting（interrupt 挂起）| degraded（LLM 不可用走本地 fallback）| error
    status = Column(String, index=True)
    source = Column(String)                     # chat | chat_stream
    prompt = Column(Text)                       # 截断存储
    reply = Column(Text)                        # 截断存储
    error = Column(Text)                        # 截断存储
    actions_count = Column(Integer, default=0)
    # [{"type": "tool_not_allowed", "step": 1, ...}] 自省修正轮次摘要
    corrections = Column(JSON, default=list)
    # 最终验证报告摘要 {valid, errorCount, warningCount}
    validation = Column(JSON)
    duration_ms = Column(Integer)
