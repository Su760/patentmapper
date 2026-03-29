from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    groq_api_key: str = ""
    patentsview_key: str = ""
    patentsview_enabled: bool = True
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


settings = Settings()
