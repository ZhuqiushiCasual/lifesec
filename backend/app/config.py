import os


class Settings:
    database_url: str = os.environ.get(
        "DATABASE_URL",
        "",
    )
    secret_key: str = os.environ.get("SECRET_KEY", "change-me-in-production")
    openai_base_url: str = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com")
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    openai_model: str = os.environ.get("OPENAI_MODEL", "deepseek-v4-pro")
    cors_origins: str = os.environ.get("CORS_ORIGINS", "*")
    debug: bool = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",")]


settings = Settings()
