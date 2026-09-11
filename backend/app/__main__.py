import uvicorn

from app.config import Settings, load_settings


def build_uvicorn_options(settings: Settings) -> dict[str, str | int | bool]:
    """把已验证配置转换为 Uvicorn（后端服务器）的启动参数。"""
    return {
        "host": settings.api_host,
        "port": settings.api_port,
        "reload": True,
    }


def main() -> None:
    """使用统一配置启动服务，使 API_HOST 和 API_PORT 真正生效。"""
    settings = load_settings()
    uvicorn.run("app.main:app", **build_uvicorn_options(settings))


if __name__ == "__main__":
    main()
