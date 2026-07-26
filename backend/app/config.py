"""应用配置 — 从环境变量读取"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Server
    PORT: int = 8000
    DATABASE_URL: str = "sqlite:///./lowcode.db"
    CORS_ORIGINS: str = "http://localhost:8080,http://localhost:5173"

    # JWT
    JWT_SECRET: str = "dev-only-lowcode-jwt-secret"
    JWT_EXPIRES_IN: str = "7d"

    # AI (StepFun, OpenAI-compatible)
    AI_API_KEY: str = ""
    AI_BASE_URL: str = "https://api.stepfun.com/step_plan/v1"
    AI_MODEL: str = "step-3.7-flash"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()