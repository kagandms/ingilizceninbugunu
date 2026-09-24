import os
from typing import Optional

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    from pydantic import SecretStr, Field
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False

    class SecretStr:
        def __init__(self, value: str = ""):
            self._value = value or ""
        def get_secret_value(self) -> str:
            return self._value
        def __repr__(self) -> str:
            return "**********"
        def __str__(self) -> str:
            return "**********"

    class Field:
        def __init__(self, default=None, **kwargs):
            self.default = default

if HAS_PYDANTIC:
    class Settings(BaseSettings):
        MAX_POST_CHARS: int = 470

        # Meta Threads API
        THREADS_ACCESS_TOKEN: SecretStr = Field(default=SecretStr(""))
        THREADS_USER_ID: str = Field(default="")
        THREADS_APP_ID: str = Field(default="")
        THREADS_APP_SECRET: SecretStr = Field(default=SecretStr(""))
        THREADS_API_BASE_URL: str = Field(default="https://graph.threads.net/v1.0")

        # Turso Database (HTTPS API)
        TURSO_DATABASE_URL: str = Field(default="")
        TURSO_AUTH_TOKEN: SecretStr = Field(default=SecretStr(""))

        # Monitoring & Alerts
        HEALTHCHECKS_PING_URL: Optional[str] = Field(default=None)
        TELEGRAM_ALERT_BOT_TOKEN: SecretStr = Field(default=SecretStr(""))
        TELEGRAM_ALERT_CHAT_ID: Optional[str] = Field(default=None)

        # Cloudinary Image Hosting
        CLOUDINARY_CLOUD_NAME: str = Field(default="")
        CLOUDINARY_API_KEY: str = Field(default="")
        CLOUDINARY_API_SECRET: SecretStr = Field(default=SecretStr(""))

        # OpenRouter AI
        OPENROUTER_API_KEY: SecretStr = Field(default=SecretStr(""))
        AI_MODEL: str = Field(default="google/gemini-2.5-flash")
        BACKUP_MODEL: str = Field(default="meta-llama/llama-3.3-70b-instruct")
        TERTIARY_MODEL: str = Field(default="qwen/qwen-2.5-72b-instruct")

        # Operational Controls
        DRY_RUN: bool = Field(default=True)
        LOG_LEVEL: str = Field(default="INFO")
        TIMEZONE: str = Field(default="Europe/Istanbul")

        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore"
        )

    settings = Settings()

else:
    class StandaloneSettings:
        MAX_POST_CHARS: int = 470

        def __init__(self):
            # Load from .env if present
            env_vars = {}
            if os.path.exists(".env"):
                with open(".env", "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            env_vars[k.strip()] = v.strip().strip('"').strip("'")

            def get_val(key, default=""):
                return os.getenv(key, env_vars.get(key, default))

            self.THREADS_ACCESS_TOKEN = SecretStr(get_val("THREADS_ACCESS_TOKEN"))
            self.THREADS_USER_ID = get_val("THREADS_USER_ID")
            self.THREADS_APP_ID = get_val("THREADS_APP_ID")
            self.THREADS_APP_SECRET = SecretStr(get_val("THREADS_APP_SECRET"))
            self.THREADS_API_BASE_URL = get_val("THREADS_API_BASE_URL", "https://graph.threads.net/v1.0")

            self.TURSO_DATABASE_URL = get_val("TURSO_DATABASE_URL")
            self.TURSO_AUTH_TOKEN = SecretStr(get_val("TURSO_AUTH_TOKEN"))

            self.HEALTHCHECKS_PING_URL = get_val("HEALTHCHECKS_PING_URL") or None
            self.TELEGRAM_ALERT_BOT_TOKEN = SecretStr(get_val("TELEGRAM_ALERT_BOT_TOKEN"))
            self.TELEGRAM_ALERT_CHAT_ID = get_val("TELEGRAM_ALERT_CHAT_ID") or None

            self.CLOUDINARY_CLOUD_NAME = get_val("CLOUDINARY_CLOUD_NAME")
            self.CLOUDINARY_API_KEY = get_val("CLOUDINARY_API_KEY")
            self.CLOUDINARY_API_SECRET = SecretStr(get_val("CLOUDINARY_API_SECRET"))

            self.OPENROUTER_API_KEY = SecretStr(get_val("OPENROUTER_API_KEY"))
            self.AI_MODEL = get_val("AI_MODEL", "google/gemini-2.5-flash")
            self.BACKUP_MODEL = get_val("BACKUP_MODEL", "meta-llama/llama-3.3-70b-instruct")
            self.TERTIARY_MODEL = get_val("TERTIARY_MODEL", "qwen/qwen-2.5-72b-instruct")

            self.DRY_RUN = get_val("DRY_RUN", "true").lower() == "true"
            self.LOG_LEVEL = get_val("LOG_LEVEL", "INFO")
            self.TIMEZONE = get_val("TIMEZONE", "Europe/Istanbul")

    settings = StandaloneSettings()
