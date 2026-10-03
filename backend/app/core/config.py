from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    serpapi_key: str = ""
    lens_api_key: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""
    mock_mode: bool = False
    serpapi_enabled: bool = True
    stripe_secret_key: str = ""
    stripe_pro_price_id: str = ""
    stripe_webhook_secret: str = ""

    # Every provider-backed operation consumes a non-refundable reservation.
    free_job_limit: int = Field(default=3, ge=0)
    free_claims_limit: int = Field(default=3, ge=0)
    free_ideation_limit: int = Field(default=6, ge=0)
    pro_job_limit: int = Field(default=100, ge=0)
    pro_claims_limit: int = Field(default=100, ge=0)
    pro_ideation_limit: int = Field(default=200, ge=0)
    global_operation_limit: int = Field(default=1000, ge=0)
    quota_window_days: int = Field(default=30, ge=1, le=365)
    invention_min_chars: int = Field(default=20, ge=1)
    invention_max_chars: int = Field(default=2000, ge=20)
    ideation_title_max_chars: int = Field(default=200, ge=1)
    ideation_description_max_chars: int = Field(default=4000, ge=1)


settings = Settings()
