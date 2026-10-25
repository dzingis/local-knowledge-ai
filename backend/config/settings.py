from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore',
    )

    app_name: str = 'Local Knowledge AI'
    app_version: str = '0.1.0'

    sql_server: str = 'sqlserver'
    sql_database: str = 'AIKnowledge'
    sql_user: str = 'sa'
    sql_password: str = 'ChangeThisPassword!'
    sql_port: int = 1433

    qdrant_host: str = 'qdrant'
    qdrant_port: int = 6333

    ollama_host: str = 'ollama'
    ollama_port: int = 11434

    openwebui_port: int = 3000
    backend_port: int = 8000

    log_level: str = 'INFO'
    log_dir: Path = Path('logs')


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
