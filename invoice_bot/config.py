"""Strict application configuration."""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    """Raised when required configuration is invalid."""


@dataclass(frozen=True)
class Choice:
    """Configured inline keyboard choice."""

    key: str
    code: int
    name: str


@dataclass(frozen=True)
class Settings:
    """Validated runtime settings."""

    telegram_token: str
    telegram_proxy_url: str
    bitrix_url: str
    bitrix_timeout: float
    dadata_url: str
    dadata_timeout: float
    dadata_api_key: str
    dadata_secret_key: str
    max_concurrent: int
    max_attempts: int
    max_file_size: int
    max_pdf_pages: int
    ocr_language: str
    ocr_dpi: int
    temp_dir: Path
    cleanup_time: str
    retention_days: int
    log_dir: Path
    log_retention_days: int
    log_level: str
    invoice_types: tuple[Choice, ...]
    dds_articles: tuple[Choice, ...]


def _choices(parser: configparser.ConfigParser, section: str) -> tuple[Choice, ...]:
    if not parser.has_section(section):
        raise ConfigError(f"Отсутствует секция [{section}]")
    result = []
    for key, value in parser.items(section):
        try:
            code, name = value.split("|", 1)
            result.append(Choice(key, int(code), name.strip()))
        except (ValueError, TypeError) as error:
            raise ConfigError(f"Некорректный вариант [{section}] {key}") from error
    if not result:
        raise ConfigError(f"Секция [{section}] пуста")
    return tuple(result)


def load_settings(path: str | Path = "config.ini") -> Settings:
    """Load INI config with secret overrides from environment."""

    parser = configparser.ConfigParser(interpolation=None)
    if not parser.read(path, encoding="utf-8"):
        raise ConfigError(f"Не найден файл конфигурации: {path}")

    def required(section: str, key: str, env: str | None = None) -> str:
        value = os.getenv(env, "") if env else ""
        value = value or parser.get(section, key, fallback="").strip()
        if not value or value == "CHANGE_ME":
            raise ConfigError(f"Не задан параметр [{section}] {key}")
        return value

    try:
        cleanup_time = parser.get("cleanup", "run_time")
        hours, minutes = map(int, cleanup_time.split(":"))
        if not 0 <= hours < 24 or not 0 <= minutes < 60:
            raise ValueError
        settings = Settings(
            telegram_token=required("telegram", "bot_token", "TELEGRAM_BOT_TOKEN"),
            telegram_proxy_url=required("telegram", "proxy_url", "TELEGRAM_PROXY_URL"),
            bitrix_url=required("bitrix", "endpoint_url", "BITRIX_ENDPOINT_URL"),
            bitrix_timeout=parser.getfloat("bitrix", "request_timeout_seconds"),
            dadata_url=parser.get("dadata", "endpoint_url"),
            dadata_timeout=parser.getfloat("dadata", "request_timeout_seconds"),
            dadata_api_key=required("dadata", "api_key", "DADATA_API_KEY"),
            dadata_secret_key=required("dadata", "secret_key", "DADATA_SECRET_KEY"),
            max_concurrent=parser.getint("processing", "max_concurrent_invoices"),
            max_attempts=parser.getint("processing", "max_send_attempts"),
            max_file_size=parser.getint("processing", "max_file_size_mb") * 1024 * 1024,
            max_pdf_pages=parser.getint("processing", "max_pdf_pages"),
            ocr_language=parser.get("ocr", "language"),
            ocr_dpi=parser.getint("ocr", "dpi"),
            temp_dir=Path(parser.get("storage", "temp_dir")),
            cleanup_time=cleanup_time,
            retention_days=parser.getint("cleanup", "retention_days"),
            log_dir=Path(parser.get("logging", "log_dir")),
            log_retention_days=parser.getint("logging", "retention_days"),
            log_level=parser.get("logging", "level"),
            invoice_types=_choices(parser, "invoice_types"),
            dds_articles=_choices(parser, "dds_articles"),
        )
    except (configparser.Error, ValueError) as error:
        raise ConfigError("Конфигурация содержит некорректное значение") from error
    if min(settings.max_concurrent, settings.max_attempts, settings.retention_days) < 1:
        raise ConfigError("Лимиты конфигурации должны быть положительными")
    return settings
