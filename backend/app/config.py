"""应用配置 — 从环境变量读取"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Server
    PORT: int = 8000
    DATABASE_URL: str = "sqlite:///./lowcode.db"
    CORS_ORIGINS: str = "http://localhost:8080,http://localhost:5173"

    # Auth (JWT 双 token)
    JWT_SECRET: str = "dev-secret-change-me-in-env"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # AI (StepFun, OpenAI-compatible)
    AI_API_KEY: str = ""
    AI_BASE_URL: str = "https://api.stepfun.com/step_plan/v1"
    AI_MODEL: str = "step-3.7-flash"
    AI_MAX_RETRIES: int = 3
    AI_RETRY_BACKOFF_BASE: int = 2
    AI_MAX_AGENT_STEPS: int = 6
    AI_DEFAULT_CANVAS_WIDTH: int = 375
    AI_DEFAULT_CANVAS_HEIGHT: int = 667

    # Agent 状态持久化：memory（默认）| redis（需安装 langgraph-checkpoint-redis）
    AI_CHECKPOINT_BACKEND: str = "memory"
    AI_REDIS_URL: str = ""
    AI_THREAD_TTL_SECONDS: int = 3600

    # 可观测性（LangSmith，可选）
    LANGSMITH_TRACING: bool = False
    LANGSMITH_API_KEY: str = ""
    LANGSMITH_PROJECT: str = "lowcode-agent"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
