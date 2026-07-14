from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _csv_env(name: str, default: str = "") -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: _csv_env(
            "HELPER_ALLOWED_ORIGINS",
            (
                "https://towardsai.com,https://www.towardsai.com,"
                "https://academy.towardsai.net,https://towardsai.net,"
                "https://www.towardsai.net"
            ),
        )
    )
    allowed_hosts: tuple[str, ...] = field(
        default_factory=lambda: _csv_env(
            "HELPER_ALLOWED_HOSTS",
            (
                "towardsai.com,www.towardsai.com,academy.towardsai.net,"
                "towardsai.net,www.towardsai.net"
            ),
        )
    )
    site_wide_hosts: tuple[str, ...] = field(
        default_factory=lambda: _csv_env(
            "HELPER_SITE_WIDE_HOSTS",
            "towardsai.com,www.towardsai.com",
        )
    )
    deepseek_api_key: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", "").strip()
    )
    deepseek_base_url: str = field(
        default_factory=lambda: (
            os.getenv(
                "DEEPSEEK_BASE_URL",
                "https://api.deepseek.com",
            )
            .strip()
            .rstrip("/")
            or "https://api.deepseek.com"
        )
    )
    deepseek_thinking_type: str = field(
        default_factory=lambda: (
            os.getenv(
                "HELPER_DEEPSEEK_THINKING",
                "disabled",
            ).strip()
            or "disabled"
        )
    )
    primary_model_name: str = field(
        default_factory=lambda: (
            os.getenv(
                "HELPER_PRIMARY_MODEL",
                os.getenv("HELPER_MODEL", "deepseek-v4-flash"),
            ).strip()
            or "deepseek-v4-flash"
        )
    )
    gemini_api_key: str = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY", "").strip()
    )
    fallback_model_name: str = field(
        default_factory=lambda: (
            os.getenv(
                "HELPER_FALLBACK_MODEL",
                "gemini-2.5-flash",
            ).strip()
            or "gemini-2.5-flash"
        )
    )
    max_output_tokens: int = field(
        default_factory=lambda: _int_env("HELPER_MAX_OUTPUT_TOKENS", 420)
    )
    llm_request_timeout_seconds: float = field(
        default_factory=lambda: _float_env("HELPER_LLM_REQUEST_TIMEOUT_SECONDS", 20.0)
    )
    max_body_bytes: int = field(
        default_factory=lambda: _int_env("HELPER_MAX_BODY_BYTES", 64 * 1024)
    )
    max_query_chars: int = field(
        default_factory=lambda: _int_env("HELPER_MAX_QUERY_CHARS", 600)
    )
    max_history_turns: int = field(
        default_factory=lambda: _int_env("HELPER_MAX_HISTORY_TURNS", 8)
    )
    rate_limit_per_minute: int = field(
        default_factory=lambda: _int_env("HELPER_RATE_LIMIT_PER_MINUTE", 3)
    )
    rate_limit_per_day: int = field(
        default_factory=lambda: _int_env("HELPER_RATE_LIMIT_PER_DAY", 20)
    )
    rate_limit_global_per_minute: int = field(
        default_factory=lambda: _int_env("HELPER_GLOBAL_RATE_LIMIT_PER_MINUTE", 120)
    )
    opik_enabled: bool = field(default_factory=lambda: _bool_env("OPIK_ENABLED", False))
    opik_api_key: str = field(
        default_factory=lambda: os.getenv("OPIK_API_KEY", "").strip()
    )
    opik_workspace: str = field(
        default_factory=lambda: os.getenv("OPIK_WORKSPACE", "").strip()
    )
    opik_project_name: str = field(
        default_factory=lambda: (
            os.getenv(
                "OPIK_PROJECT_NAME",
                "towards-ai-helper",
            ).strip()
            or "towards-ai-helper"
        )
    )
    opik_max_text_chars: int = field(
        default_factory=lambda: _int_env("OPIK_MAX_TEXT_CHARS", 4000)
    )

    def cors_origins(self) -> list[str]:
        return list(self.allowed_origins)

    @property
    def model_name(self) -> str:
        return self.primary_model_name


settings = Settings()
