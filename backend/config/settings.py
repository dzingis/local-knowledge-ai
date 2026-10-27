import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    watch_enabled: bool = False
    watch_folders: Annotated[list[str], NoDecode] = Field(default_factory=list)
    watch_recursive: bool = True
    watch_debounce_seconds: float = Field(default=2.0, gt=0)
    watch_poll_interval: float = Field(default=30.0, gt=0)
    watch_ignore_patterns: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ['~$*', '*.tmp', '*.part']
    )

    @field_validator('watch_folders', 'watch_ignore_patterns', mode='before')
    @classmethod
    def parse_watch_list(cls, value: Any, info: ValidationInfo) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                values = []
            elif stripped.startswith('['):
                values = json.loads(stripped)
            else:
                values = [item.strip() for item in stripped.split(',') if item.strip()]
        else:
            values = value
        if info.field_name == 'watch_ignore_patterns' and isinstance(values, list):
            return list(dict.fromkeys([*values, '~$*', '*.tmp', '*.part']))
        return values


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
