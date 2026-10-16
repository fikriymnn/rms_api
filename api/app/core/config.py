from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    jwt_secret: str = Field(min_length=32)
    access_token_minutes: int = 30
    refresh_token_days: int = 30
    photo_dir: str = "/data/photos"
    photo_retention_days: int = 90
    max_gps_accuracy_m: int = 80
    geofence_tolerance_m: int = 10


settings = Settings()
