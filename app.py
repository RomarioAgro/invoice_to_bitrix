"""Invoice bot entrypoint."""

from invoice_bot.config import load_settings
from invoice_bot.logging_setup import configure_logging
from invoice_bot.telegram_app import build_application


def main() -> None:
    """Load configuration and start Telegram long polling."""

    settings = load_settings()
    configure_logging(settings.log_dir, settings.log_level, settings.log_retention_days)
    build_application(settings).run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
