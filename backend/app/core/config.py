import os
from typing import Any, Dict, Optional, Literal
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings(BaseSettings):
    # API settings
    API_V1_STR: str = "/open-search-agent"
    PROJECT_NAME: str = "AI Web Search Agent"

    # CORS settings
    BACKEND_CORS_ORIGINS: list[str] = ["*"]

    # API Key Authentication
    API_KEY: str = os.getenv("API_KEY", "")

    # OpenAI settings
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "o4-mini")
    OPENAI_MODEL_LOW: str = os.getenv("OPENAI_MODEL_LOW", "gpt-4.1-mini")

    # Search provider selection
    SEARCH_PROVIDER: Literal["duckduckgo", "google", "searxng", "tavily", "serper", "brave"] = os.getenv("SEARCH_PROVIDER", "duckduckgo")

    # Google Search settings
    GOOGLE_SEARCH_API_KEY: str = os.getenv("GOOGLE_SEARCH_API_KEY", "")
    GOOGLE_SEARCH_ENGINE_ID: str = os.getenv("GOOGLE_SEARCH_ENGINE_ID", "")

    # SearXNG settings
    SEARXNG_URL: str = os.getenv("SEARXNG_URL", "")

    # Tavily settings
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")

    # Serper settings
    SERPER_API_KEY: str = os.getenv("SERPER_API_KEY", "")

    # Brave Search settings
    BRAVE_API_KEY: str = os.getenv("BRAVE_API_KEY", "")

    # Security settings
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

    # Debug mode
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"

    @field_validator("OPENAI_API_KEY", "SECRET_KEY", "API_KEY")
    @classmethod
    def check_not_empty(cls, v: str, info) -> str:
        if not v and not os.getenv("DEBUG", "False").lower() == "true":
            raise ValueError(f"Environment variable {info.field_name} must be set in production mode")
        return v

    @model_validator(mode='after')
    def validate_search_provider_settings(self) -> 'Settings':
        """Validate that the required settings for the selected search provider are present."""
        if self.SEARCH_PROVIDER == "google" and not self.DEBUG:
            if not self.GOOGLE_SEARCH_API_KEY or not self.GOOGLE_SEARCH_ENGINE_ID:
                raise ValueError("GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_ENGINE_ID must be set when using Google search provider")
        elif self.SEARCH_PROVIDER == "searxng" and not self.DEBUG:
            if not self.SEARXNG_URL:
                raise ValueError("SEARXNG_URL must be set when using SearXNG search provider")
        elif self.SEARCH_PROVIDER == "tavily" and not self.DEBUG:
            if not self.TAVILY_API_KEY:
                raise ValueError("TAVILY_API_KEY must be set when using Tavily search provider")
        elif self.SEARCH_PROVIDER == "serper" and not self.DEBUG:
            if not self.SERPER_API_KEY:
                raise ValueError("SERPER_API_KEY must be set when using Serper search provider")
        elif self.SEARCH_PROVIDER == "brave" and not self.DEBUG:
            if not self.BRAVE_API_KEY:
                raise ValueError("BRAVE_API_KEY must be set when using Brave search provider")
        return self

    model_config = {
        "case_sensitive": True
    }


settings = Settings()
