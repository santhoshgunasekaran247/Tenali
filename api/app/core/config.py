from __future__ import annotations

import os
from dataclasses import dataclass


def _parse_origins(value: str | None) -> list[str]:
    if not value:
        return ["http://localhost:5173", "http://127.0.0.1:5173"]
    return [origin.strip() for origin in value.split(",") if origin.strip()]


@dataclass(frozen=True)
class Settings:
    app_title: str = "Tenali Business System API"
    app_version: str = "1.0.0"
    app_description: str = "Backend API for the Tenali business operating system."
    cors_origins: list[str] = None  # type: ignore[assignment]


settings = Settings(
    cors_origins=_parse_origins(os.getenv("CORS_ORIGINS")),
)
