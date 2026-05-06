from app.core.config import Settings


def test_cors_origins_parsing() -> None:
    settings = Settings(
        cors_origins="http://localhost:3000,http://127.0.0.1:3000",
    )

    assert settings.cors_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]
