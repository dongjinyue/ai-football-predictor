import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = Path("data/processed/football_predictor.duckdb")


@dataclass(frozen=True)
class Settings:
    """应用运行配置；路径在这里统一解析，避免各模块各自读取环境变量。"""

    database_path: Path
    api_host: str
    api_port: int


def load_settings(
    env_file: Path | None = None,
    project_root: Path = PROJECT_ROOT,
) -> Settings:
    """读取根目录 .env，并让终端中显式设置的环境变量拥有更高优先级。"""
    values = {
        key: value
        for key, value in dotenv_values(env_file or project_root / ".env").items()
        if value is not None
    }
    values.update(os.environ)

    configured_path = Path(values.get("DATABASE_PATH", str(DEFAULT_DATABASE_PATH)))
    database_path = (
        configured_path
        if configured_path.is_absolute()
        else project_root / configured_path
    )

    return Settings(
        database_path=database_path,
        api_host=values.get("API_HOST", "127.0.0.1"),
        api_port=int(values.get("API_PORT", "8000")),
    )
