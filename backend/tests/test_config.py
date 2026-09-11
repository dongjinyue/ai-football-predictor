from pathlib import Path

from app.__main__ import build_uvicorn_options
from app.config import load_settings


def test_load_settings_reads_repository_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_PATH=custom/data.duckdb\n"
        "API_HOST=0.0.0.0\n"
        "API_PORT=9123\n",
        encoding="utf-8",
    )

    settings = load_settings(env_file=env_file, project_root=tmp_path)

    assert settings.database_path == tmp_path / "custom" / "data.duckdb"
    assert settings.api_host == "0.0.0.0"
    assert settings.api_port == 9123


def test_environment_variables_override_env_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("API_PORT=9123\n", encoding="utf-8")
    monkeypatch.setenv("API_PORT", "9234")

    settings = load_settings(env_file=env_file, project_root=tmp_path)

    assert settings.api_port == 9234


def test_uvicorn_options_use_loaded_host_and_port(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("API_HOST=0.0.0.0\nAPI_PORT=9123\n", encoding="utf-8")
    settings = load_settings(env_file=env_file, project_root=tmp_path)

    options = build_uvicorn_options(settings)

    assert options == {"host": "0.0.0.0", "port": 9123, "reload": True}
