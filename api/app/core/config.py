from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    jwt_secret: str = Field(min_length=32)
    access_token_minutes: int = 30
    refresh_token_days: int = 30


settings = Settings()
