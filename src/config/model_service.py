from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelServiceConfig(BaseSettings):
    base_url: str = "https://api.siliconflow.cn/v1"
    api_key: str = ""
    default_timeout: int = 30
    max_retries: int = 3

    model_config = SettingsConfigDict(env_prefix="MODEL_")
